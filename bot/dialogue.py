"""対話管理：意図ごとの処理、足りない情報の聞き返し（スロットフィリング）、確認。"""
import copy
import datetime as dt
import re
from dataclasses import dataclass, field

from . import nlu
from . import services as sv


@dataclass
class Reply:
    text: str
    places: list = field(default_factory=list)  # 地図に表示する目的地
    origin: dict = None                          # 地図に表示する出発地（推定した現在地）
    links: list = field(default_factory=list)   # (ラベル, URL)
    choices: list = field(default_factory=list) # 返答の候補（画面ではボタンとして表示）
    train: dict = None                           # 電車の計画（画面では発車標カードとして表示）


YES_NO = ["はい", "いいえ"]
EXAMPLES = ["今から帰る", "次の授業は？", "課題一覧", "ヘルプ"]

HELP = """こんなことができます（例）:
- 「月曜2限に線形代数を追加」「金1消して」… 時間割を登録・削除
- 「今日レポートあった、15日まで」… 課題を登録（授業名は時間割から推定）
- 「課題一覧」「今週の締切は？」… 登録した課題を表示
- 「今から帰る」「4限のあと帰る」「興戸から帰る」… 乗れる電車を提案
- 「次の授業は？」「明日の時間割」… 時間割を表示
- 「情報メディア館どこ？」「次の教室どこ？」… 地図と道案内リンク
- 「いつも興戸の京都方面に設定」… 帰りの駅・方面を変更"""


def _fmt_date(d):
    return f"{d.month}/{d.day}({sv.WEEKDAY_JA[d.weekday()]})"


class Bot:
    def __init__(self):
        self.classes = copy.deepcopy(sv.DEFAULT_CLASSES)  # 利用者の時間割
        self.tasks = []  # {"course", "kind", "deadline", "done"}
        self.settings = {"station": "dmae", "direction": {"kodo": "京都方面", "dmae": "京橋方面"}}
        self.pending = None  # 聞き返し中の状態 {"intent", "slots", "awaiting"}

    # ---------- 入口 ----------

    def respond(self, text, now):
        text = nlu.normalize(text)
        self.now = now
        if self.pending:
            if nlu.is_cancel(text):
                self.pending = None
                return Reply("キャンセルしました。")
            reply = self._continue_pending(text, now)
            if reply:
                return reply
            self.pending = None  # 答えになっていなければ、新しい話題として処理する

        intent = nlu.detect_intent(text)
        handler = getattr(self, f"_on_{intent}", self._on_unknown)
        return handler(text, now)

    def notice(self, now):
        """起動時に出すリマインド（明日までの締切）。"""
        soon = sorted(sv.tasks_due_soon(self.tasks, now.date()), key=lambda t: t["deadline"])
        if not soon:
            return None
        lines = [f"- {_fmt_date(t['deadline'])} {t['course']} {t['kind']}" for t in soon]
        return "締切が近い課題があります\n" + "\n".join(lines)

    # ---------- 画面（時間割・リマインダー）からも使う操作 ----------

    def add_task(self, course, kind, deadline):
        self._next_id = getattr(self, "_next_id", 0) + 1
        self.tasks.append({"id": self._next_id, "course": course, "kind": kind, "deadline": deadline, "done": False})

    def remove_task(self, task_id):
        self.tasks = [t for t in self.tasks if t["id"] != task_id]

    def set_class(self, weekday, period, name, building, room):
        """その曜日・時限の授業を登録（既にあれば置き換え）。"""
        self.remove_class(weekday, period)
        self.classes.append({"weekday": weekday, "period": period, "name": name, "aliases": [],
                             "building": building, "room": room})

    def remove_class(self, weekday, period):
        self.classes = [c for c in self.classes if not (c["weekday"] == weekday and c["period"] == period)]

    def open_tasks(self, today):
        return sorted((t for t in self.tasks if not t["done"] and t["deadline"] >= today),
                      key=lambda t: t["deadline"])

    # ---------- 課題の登録（スロット: course, deadline） ----------

    def _on_add_task(self, text, now):
        slots = {"kind": nlu.find_task_kind(text), "course": None, "inferred": False,
                 "deadline": nlu.find_deadline(text, now.date())}
        c = sv.find_course(self.classes, text)
        period = nlu.find_period(text)
        if not c and period:
            c = sv.class_at(self.classes, now.weekday(), period)
        if not c:
            # 授業名がなければ、今受けている or 直前に終わった授業だと推定する
            c = sv.latest_started_class(self.classes, now)
            slots["inferred"] = c is not None
        slots["course"] = c["name"] if c else None
        return self._fill_task(slots)

    def _ask_course(self, slots, prefix=""):
        self.pending = {"intent": "add_task", "slots": slots, "awaiting": "course"}
        today = [c["name"] for c in sv.classes_on(self.classes, self.now.weekday())]  # 今日の授業を候補に
        return Reply(f"{prefix}どの授業の{slots['kind']}ですか？", choices=today)

    def _fill_task(self, slots):
        if not slots["course"]:
            return self._ask_course(slots)
        if not slots["deadline"]:
            self.pending = {"intent": "add_task", "slots": slots, "awaiting": "deadline"}
            guess = "（時間割から推定。違えば授業名を教えてください）" if slots["inferred"] else ""
            return Reply(f"{slots['course']}の{slots['kind']}ですね{guess}。締切はいつですか？（例: 15日、来週金曜）",
                         choices=["明日", "7日後", "14日後"])
        if slots["inferred"]:
            self.pending = {"intent": "add_task", "slots": slots, "awaiting": "confirm"}
            return Reply(f"時間割から推定しました。\n**{slots['course']}** の{slots['kind']}、"
                         f"締切 **{_fmt_date(slots['deadline'])}** で登録していいですか？", choices=YES_NO)
        return self._register_task(slots)

    def _register_task(self, slots):
        self.pending = None
        self.add_task(slots["course"], slots["kind"], slots["deadline"])
        return Reply(f"登録しました：{slots['course']} {slots['kind']}（締切 {_fmt_date(slots['deadline'])}）\n"
                     "前日にリマインドします。スマホに通知したい場合は「リマインダー」タブから .ics でカレンダーに追加できます。")

    def _continue_pending(self, text, now):
        """聞き返しへの返答を処理する。答えになっていなければ None。"""
        p = self.pending
        slots = p["slots"]
        if p["intent"] == "add_task":
            if p["awaiting"] == "confirm":
                if nlu.is_yes(text):
                    return self._register_task(slots)
                if nlu.is_no(text):
                    slots["course"], slots["inferred"] = None, False
                    return self._ask_course(slots, "失礼しました。")
                return None
            if p["awaiting"] == "course":
                c = sv.find_course(self.classes, text)
                if c:
                    slots["course"] = c["name"]
                elif nlu.detect_intent(text) == "unknown":
                    slots["course"] = text  # 時間割にない授業名もそのまま受け付ける
                else:
                    return None
                return self._fill_task(slots)
            if p["awaiting"] == "deadline":
                c = sv.find_course(self.classes, text)
                if c:  # 締切を聞いている途中で授業名の訂正が来た
                    slots["course"], slots["inferred"] = c["name"], False
                elif slots["inferred"] and nlu.is_no(text):
                    slots["course"], slots["inferred"] = None, False
                    return self._ask_course(slots, "失礼しました。")
                d = nlu.find_deadline(text, now.date()) or nlu.find_day(text, now.date())
                if not d and c:
                    return self._fill_task(slots)
                if not d:
                    if nlu.detect_intent(text) != "unknown":
                        return None
                    return Reply("日付がわかりませんでした。「15日」「11/20」「来週金曜」のように教えてください。")
                slots["deadline"] = d
                return self._fill_task(slots)
        if p["intent"] == "edit_class":
            return self._continue_class(text, slots, p["awaiting"])
        if p["intent"] == "where" and p["awaiting"] == "place":
            place = sv.find_place(text)
            return self._show_place(place) if place else None
        if p["intent"] == "settings" and p["awaiting"] == "station":
            return self._on_settings(text, now) if sv.find_station(text) else None
        return None

    # ---------- 時間割の登録・削除（スロット: 曜日・時限, 授業名, 教室） ----------

    def _on_edit_class(self, text, now):
        wd, period, (s, e) = nlu.find_slot(text)
        rest = text[:s] + " " + text[e:]
        slots = {"weekday": wd, "period": period, "name": None, "building": "", "room": "", "room_asked": False}
        slot_name = f"{sv.WEEKDAY_JA[wd]}曜{period}限"
        current = sv.class_at(self.classes, wd, period)

        if nlu.is_delete(text):
            if not current:
                return Reply(f"{slot_name}には授業が登録されていません。")
            self.pending = {"intent": "edit_class", "slots": slots, "awaiting": "confirm_delete"}
            return Reply(f"{slot_name}の **{current['name']}** を削除していいですか？", choices=YES_NO)

        # 教室（建物名・教室番号）を取り除いた残りを授業名とみなす
        place = sv.find_place(rest)
        if place and place["id"] in sv.BUILDINGS:
            slots["building"] = place["id"]
            for a in [place["name"], *place["aliases"]]:
                rest = rest.replace(a, " ")
        room = nlu.find_room(rest)
        if room:
            slots["room"] = room
            rest = rest.replace(room, " ").replace(room.lower(), " ")
        slots["name"] = nlu.clean_class_name(rest)
        return self._fill_class(slots)

    def _fill_class(self, slots):
        wd, period = slots["weekday"], slots["period"]
        slot_name = f"{sv.WEEKDAY_JA[wd]}曜{period}限"
        if not slots["name"]:
            self.pending = {"intent": "edit_class", "slots": slots, "awaiting": "name"}
            return Reply(f"{slot_name}に登録する授業名を教えてください。")
        current = sv.class_at(self.classes, wd, period)
        if current and current["name"] != slots["name"] and not slots.get("overwrite_ok"):
            self.pending = {"intent": "edit_class", "slots": slots, "awaiting": "confirm_overwrite"}
            return Reply(f"{slot_name}には **{current['name']}** が入っています。**{slots['name']}** に置き換えますか？",
                         choices=YES_NO)
        if not (slots["building"] or slots["room"] or slots["room_asked"]):
            slots["room_asked"] = True
            self.pending = {"intent": "edit_class", "slots": slots, "awaiting": "room"}
            return Reply(f"{slot_name}「{slots['name']}」ですね。教室はどこですか？\n"
                         "（例: 恵道館 KD201。わからなければ「なし」）",
                         choices=["なし"] + [b["name"] for b in sv.BUILDINGS.values()][:3])
        self.pending = None
        self.set_class(wd, period, slots["name"], slots["building"], slots["room"])
        where = " ".join(x for x in [sv.BUILDINGS.get(slots["building"], {}).get("name", ""), slots["room"]] if x)
        return Reply(f"登録しました：{slot_name} {slots['name']}" + (f"（{where}）" if where else "") +
                     "\n「時間割」タブにも反映されています。")

    def _continue_class(self, text, slots, awaiting):
        wd, period = slots["weekday"], slots["period"]
        if awaiting == "confirm_delete":
            if nlu.is_yes(text):
                name = sv.class_at(self.classes, wd, period)["name"]
                self.pending = None
                self.remove_class(wd, period)
                return Reply(f"{sv.WEEKDAY_JA[wd]}曜{period}限の{name}を削除しました。")
            if nlu.is_no(text):
                self.pending = None
                return Reply("削除をやめました。")
            return None
        if awaiting == "confirm_overwrite":
            if nlu.is_yes(text):
                slots["overwrite_ok"] = True
                return self._fill_class(slots)
            if nlu.is_no(text):
                self.pending = None
                return Reply("登録をやめました。")
            return None
        if nlu.detect_intent(text) not in ("unknown", "where"):
            return None  # 別の話題に移った
        if awaiting == "name":
            slots["name"] = nlu.clean_class_name(text)
            return self._fill_class(slots)
        if awaiting == "room":
            if nlu.is_yes(text):
                return Reply("建物名と教室番号を教えてください。（例: 恵道館 KD201）", choices=["なし"])
            if not (nlu.is_no(text) or re.search(r"^(なし|無し|いらない|不要|スキップ|未定|わからない|後で)", text)):
                place = sv.find_place(text)
                if place and place["id"] in sv.BUILDINGS:
                    slots["building"] = place["id"]
                slots["room"] = nlu.find_room(text) or ("" if slots["building"] else text)
            return self._fill_class(slots)
        return None

    def _on_list_tasks(self, text, now):
        tasks = self.open_tasks(now.date())
        if not tasks:
            return Reply("登録されている課題はありません。")
        lines = []
        for t in tasks:
            days = (t["deadline"] - now.date()).days
            left = "今日" if days == 0 else "明日" if days == 1 else f"あと{days}日"
            lines.append(f"- {_fmt_date(t['deadline'])}（{left}）{t['course']} {t['kind']}")
        return Reply("登録中の課題です：\n" + "\n".join(lines))

    # ---------- 帰りの電車 ----------

    def _on_go_home(self, text, now):
        station = sv.find_station(text) or self.settings["station"]
        direction = sv.find_direction(text, station) or self.settings["direction"][station]
        period = nlu.find_period(text)
        notes = []

        if period and sv.class_at(self.classes, now.weekday(), period):
            c = sv.class_at(self.classes, now.weekday(), period)
            depart = dt.datetime.combine(now.date(), sv.PERIODS[period][1])
            notes.append(f"{period}限（{c['name']}）が終わる {depart:%H:%M} に出る場合")
        elif "今" not in text and sv.ongoing_class(self.classes, now):
            c = sv.ongoing_class(self.classes, now)
            depart = dt.datetime.combine(now.date(), sv.PERIODS[c["period"]][1])
            notes.append(f"今は{c['period']}限（{c['name']}）中なので、終わる {depart:%H:%M} に出る場合")
        else:
            c = sv.latest_started_class(self.classes, now)
            depart = now

        # 今いる建物 = 直近の授業の教室がある建物、と推定
        building = c.get("building") if c else None
        origin = sv.BUILDINGS.get(building)
        walk, arrive, trains = sv.plan_trains(depart, building, station, direction)
        where = f"{origin['name']}から" if origin else "キャンパスから"
        st = sv.STATIONS[station]

        # 画面では train を発車標カードとして描く。文章は前置き（いつ出る想定か）だけ
        plan = {"station": station, "direction": direction, "walk": walk, "arrive": arrive, "trains": trains,
                "origin": origin["name"] if origin else "キャンパス"}
        text = "\n".join(notes) if notes else f"{where}{st['name']}へ向かう場合の電車です"
        if not trains:
            text += f"\n今日の{direction}の電車はもうありません"
        return Reply(text, places=[st], origin=origin, train=plan,
                     links=[(f"{st['name']}への道案内", sv.maps_url(st))])

    def _on_settings(self, text, now):
        station = sv.find_station(text)
        if not station:
            self.pending = {"intent": "settings", "slots": {}, "awaiting": "station"}
            return Reply("どちらの駅にしますか？", choices=["興戸", "同志社前"])
        self.settings["station"] = station
        d = sv.find_direction(text, station)
        if d:
            self.settings["direction"][station] = d
        st = sv.STATIONS[station]
        return Reply(f"帰りの駅を {st['name']}（{self.settings['direction'][station]}）に設定しました。")

    # ---------- 時間割 ----------

    def _on_timetable(self, text, now):
        slot = nlu.find_slot(text)
        if slot:  # 「月曜5限は？」
            wd, period, _ = slot
            c = sv.class_at(self.classes, wd, period)
            if not c:
                return Reply(f"{sv.WEEKDAY_JA[wd]}曜{period}限は空きコマです。",
                             choices=[f"{sv.WEEKDAY_JA[wd]}曜{period}限に授業を追加"])
            return Reply(f"{sv.WEEKDAY_JA[wd]}曜の {sv.describe_class(c)} です。")
        day = nlu.find_day(text, now.date())
        # 日付の指定がなく「今日」「時間割」でもなければ「次の授業」の質問とみなす
        if day is None and ("次" in text or not ("今日" in text or "時間割" in text)):
            c, d = sv.next_class(self.classes, now)
            if not c:
                return Reply("この先1週間の授業は見つかりませんでした。")
            when = "今日" if d == now.date() else _fmt_date(d)
            b = sv.BUILDINGS.get(c.get("building"))
            msg = f"次の授業は {when} の {sv.describe_class(c)} です。"
            if not b:
                return Reply(msg)
            return Reply(msg, places=[b], links=[(f"{b['name']}への道案内", sv.maps_url(b))])
        day = day or now.date()
        cs = sv.classes_on(self.classes, day.weekday())
        if not cs:
            return Reply(f"{_fmt_date(day)} は授業がありません。")
        return Reply(f"{_fmt_date(day)} の授業：\n" + "\n".join(f"- {sv.describe_class(c)}" for c in cs))

    # ---------- 場所 ----------

    def _on_where(self, text, now):
        place = sv.find_place(text)
        if not place:
            c = sv.find_course(self.classes, text)
            slot = nlu.find_slot(text)
            if not c and slot:  # 「水2どこ？」
                c = sv.class_at(self.classes, slot[0], slot[1])
            if not c and "次" in text:
                c, _ = sv.next_class(self.classes, now)
            if c and c.get("building") in sv.BUILDINGS:
                b = sv.BUILDINGS[c["building"]]
                r = self._show_place(b)
                r.text = f"{c['name']}の教室は {b['name']} {c.get('room', '')} です。\n" + r.text
                return r
        if not place:
            self.pending = {"intent": "where", "slots": {}, "awaiting": "place"}
            return Reply("どの建物ですか？", choices=[b["name"] for b in sv.BUILDINGS.values()])
        return self._show_place(place)

    def _show_place(self, place):
        self.pending = None
        return Reply(f"{place['name']}の場所を地図に表示しました。現在地からの道案内はリンクから開けます。",
                     places=[place], links=[(f"{place['name']}への道案内（Googleマップ）", sv.maps_url(place))])

    # ---------- その他 ----------

    def _on_help(self, text, now):
        return Reply(HELP)

    def _on_greet(self, text, now):
        return Reply("こんにちは。時間割・課題・帰りの電車・教室の場所について聞いてください", choices=EXAMPLES)

    def _on_unknown(self, text, now):
        return Reply("すみません、うまく理解できませんでした。\n" + HELP, choices=EXAMPLES)
