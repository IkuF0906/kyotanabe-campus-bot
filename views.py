"""各タブ（ページ）の画面。どのページも同じ Bot（時間割・課題・設定）を見る。"""
import datetime as dt
from html import escape

import streamlit as st

from bot import services as sv
from bot.mapview import make_map

DAYS = "月火水木金"
ACCENT = "#550071"  # 同志社パープル。おすすめ便・受講中・主要ボタンだけに使う

INTRO = "京田辺キャンパスの時間割・課題・帰りの電車・教室の場所を、話しかけて確認・登録できます"
INTRO_CHOICES = ["今から帰る", "次の授業は？", "月曜2限に線形代数を追加", "ヘルプ"]


def _fmt_date(d):
    return f"{d.month}/{d.day}（{sv.WEEKDAY_JA[d.weekday()]}）"


def _left(d, today):
    n = (d - today).days
    return "今日" if n == 0 else "明日" if n == 1 else f"あと{n}日" if n > 0 else f"{-n}日超過"


def _map(places, origin=None, height=320):
    st.iframe(make_map(places, origin), height=height)


def _notice(bot, now):
    """明日までの締切（リマインド）。色は「今日・明日」の文字だけに付ける。"""
    soon = sorted(sv.tasks_due_soon(bot.tasks, now.date()), key=lambda t: t["deadline"])
    if not soon:
        return
    with st.container(border=True):
        st.markdown(":material/schedule: **締切が近い課題**  \n" + "  \n".join(
            f":red[{_left(t['deadline'], now.date())}]　{t['course']} {t['kind']}" for t in soon))


# ---------- 発車標カード（電車ページとチャットで共通） ----------

CARD_CSS = """<style>
.tc {background:#fff; border:1px solid rgba(23,23,23,.08); border-radius:12px; padding:20px; height:100%}
.tc-st {display:flex; align-items:baseline; gap:8px; font-size:15px; font-weight:500; color:#171717}
.tc-st small {font-size:13px; font-weight:400; color:#737373}
.tc-main {display:flex; align-items:baseline; gap:12px; margin-top:16px}
.tc-time {font-size:44px; line-height:1; font-weight:500; color:#171717}
.tc.lead .tc-time {color:__A__}
.tc-dir {font-size:14px; color:#525252}
.tc-in {margin-left:auto; font-size:13px; color:#525252}
.tc-sub {margin-top:8px; font-size:13px; color:#737373}
.tc-next {margin-top:16px; padding-top:12px; border-top:1px solid rgba(23,23,23,.08);
          display:flex; flex-wrap:wrap; gap:4px 20px; font-size:14px; color:#525252}
.tc-next em {font-style:normal; font-size:12px; color:#737373; margin-left:4px}
</style>""".replace("__A__", ACCENT)


def train_card(plan, now, lead=True):
    """plan: dialogue/services が返す電車の計画。lead=True のカードだけ時刻を強調色にする。"""
    s = sv.STATIONS[plan["station"]]
    head = (f'<div class="tc-st">{escape(s["name"])}<small>{escape(s["line"])}</small></div>')
    sub = f'{escape(plan["origin"])}から徒歩{plan["walk"]}分 · <span class="t">{plan["arrive"]:%H:%M}</span>着'
    trains = plan["trains"]
    best = next((t for t, tag in trains if tag == "おすすめ"), None)
    if best is None:
        body = f'<div class="tc-main"><span class="tc-time">本日終了</span></div><div class="tc-sub">{sub}</div>'
    else:
        mins = int((dt.datetime.combine(now.date(), best) - now).total_seconds() // 60)
        rest = "".join(f'<span><span class="t">{t:%H:%M}</span>' + (f"<em>{tag}</em>" if tag else "") + "</span>"
                       for t, tag in trains if t != best)
        body = (f'<div class="tc-main"><span class="tc-time t">{best:%H:%M}</span>'
                f'<span class="tc-dir">{escape(plan["direction"])}</span>'
                f'<span class="tc-in">発車まで<span class="t">{mins}</span>分</span></div>'
                f'<div class="tc-sub">{sub}</div>'
                + (f'<div class="tc-next">{rest}</div>' if rest else ""))
    st.html(CARD_CSS + f'<div class="tc{" lead" if lead else ""}">{head}{body}</div>')


# ---------- チャット ----------

AVATARS = {"assistant": ":material/school:", "user": ":material/person:"}


def _send(bot, now, text):
    reply = bot.respond(text, now)
    st.session_state.history += [
        {"role": "user", "text": text},
        {"role": "assistant", "text": reply.text, "places": reply.places, "origin": reply.origin,
         "links": reply.links, "choices": reply.choices, "train": reply.train},
    ]
    st.rerun()


def chat_page(bot, now):
    if "history" not in st.session_state:
        st.session_state.history = [{"role": "assistant", "text": INTRO, "choices": INTRO_CHOICES}]
    _notice(bot, now)

    history = st.session_state.history
    for i, msg in enumerate(history):
        with st.chat_message(msg["role"], avatar=AVATARS[msg["role"]]):
            if msg["text"]:
                st.markdown(msg["text"].replace("\n", "  \n"))
            if msg.get("train"):
                train_card(msg["train"], now)
            if msg.get("places"):
                _map(msg["places"], msg.get("origin"), height=280)
            for label, url in msg.get("links", []):
                st.link_button(label, url, icon=":material/directions_walk:")
            # 返答の候補は最新のメッセージにだけボタンで出す（押すとその文を送ったのと同じ）
            if i == len(history) - 1 and msg.get("choices"):
                with st.container(horizontal=True):
                    for j, choice in enumerate(msg["choices"]):
                        kind = "primary" if choice == "はい" else "secondary"
                        if st.button(choice, key=f"choice_{i}_{j}", type=kind):
                            _send(bot, now, choice)

    if text := st.chat_input("メッセージ（例: 今日レポートあった、15日まで）"):
        _send(bot, now, text)


# ---------- 時間割 ----------

TABLE_CSS = """<style>
.tt {width:100%; border-collapse:collapse; table-layout:fixed; font-size:13px; background:#fff;
     border:1px solid rgba(23,23,23,.08); border-radius:12px; overflow:hidden}
.tt th, .tt td {border:1px solid rgba(23,23,23,.08); padding:8px; vertical-align:top}
.tt th {height:36px; text-align:center; font-weight:500; color:#525252}
.tt th.today {color:__A__}
.tt td.today {background:#f7f7f8}
.tt td.now {box-shadow:inset 3px 0 0 __A__}
.tt .p {width:64px; text-align:center; font-weight:500; color:#171717}
.tt .p .t {display:block; margin-top:4px; font-size:11px; font-weight:400; color:#737373; line-height:16px}
.tt .name {font-weight:500; color:#171717; line-height:20px; text-wrap:balance}
.tt .room {font-size:12px; color:#737373; line-height:16px}
.tt .tag {display:inline-block; margin-bottom:4px; padding:0 6px; border-radius:4px; font-size:11px; line-height:18px}
.tt .tag.now {background:__A__; color:#fff}
.tt .tag.next {box-shadow:inset 0 0 0 1px __A__; color:__A__}
.tt .task {margin-top:4px; font-size:12px; color:#525252}
.tt .task::before {content:""; display:inline-block; width:6px; height:6px; margin-right:6px; border-radius:3px;
                   background:#dc2626; vertical-align:1px}
</style>""".replace("__A__", ACCENT)


def timetable_page(bot, now):
    st.title("時間割")
    today = now.weekday()
    ongoing = sv.ongoing_class(bot.classes, now)
    nxt, nxt_day = sv.next_class(bot.classes, now)
    open_count = {}
    for t in bot.open_tasks(now.date()):
        open_count[t["course"]] = open_count.get(t["course"], 0) + 1

    head = "".join(f'<th class="{"today" if i == today else ""}">{d}</th>' for i, d in enumerate(DAYS))
    rows = []
    for p, (s, e) in sv.PERIODS.items():
        cells = []
        for wd in range(5):
            c = sv.class_at(bot.classes, wd, p)
            cls = ["today"] if wd == today else []
            body = ""
            if c:
                b = sv.BUILDINGS.get(c.get("building"), {}).get("name", "")
                if c is ongoing:
                    cls.append("now")
                    body += '<span class="tag now">受講中</span><br>'
                elif c is nxt and nxt_day == now.date():
                    body += '<span class="tag next">次</span><br>'
                body += (f'<div class="name">{escape(c["name"])}</div>'
                         f'<div class="room">{escape(b)} {escape(c.get("room", ""))}</div>')
                if open_count.get(c["name"]):
                    body += f'<div class="task">課題 {open_count[c["name"]]}件</div>'
            cells.append(f'<td class="{" ".join(cls)}">{body}</td>')
        rows.append(f'<tr><td class="p">{p}限<span class="t">{s:%H:%M}<br>{e:%H:%M}</span></td>{"".join(cells)}</tr>')
    st.html(TABLE_CSS + f'<table class="tt"><tr><th class="p"></th>{head}</tr>{"".join(rows)}</table>')
    st.caption("赤い点は締切前の課題がある授業。チャットで「今日レポートあった、15日まで」と送ると付きます")

    with st.expander("授業を追加・変更・削除", icon=":material/edit:"):
        c1, c2 = st.columns(2)
        wd = c1.selectbox("曜日", range(5), format_func=lambda i: DAYS[i], index=min(today, 4))
        p = c2.selectbox("時限", list(sv.PERIODS), format_func=lambda i: f"{i}限")
        cur = sv.class_at(bot.classes, wd, p)
        bids = [""] + list(sv.BUILDINGS)
        with st.form("class_form", clear_on_submit=False, border=False):
            name = st.text_input("授業名", cur["name"] if cur else "")
            c3, c4 = st.columns(2)
            building = c3.selectbox("建物", bids, index=bids.index(cur["building"]) if cur and cur.get("building") in bids else 0,
                                    format_func=lambda i: sv.BUILDINGS[i]["name"] if i else "未登録")
            room = c4.text_input("教室", cur.get("room", "") if cur else "")
            with st.container(horizontal=True):
                if st.form_submit_button("保存", type="primary") and name.strip():
                    bot.set_class(wd, p, name.strip(), building, room.strip())
                    st.rerun()
                if st.form_submit_button("この時限を空にする") and cur:
                    bot.remove_class(wd, p)
                    st.rerun()


# ---------- リマインダー ----------

def reminder_page(bot, now):
    st.title("リマインダー")
    today = now.date()
    tasks = bot.open_tasks(today)
    overdue = [t for t in bot.tasks if not t["done"] and t["deadline"] < today]

    if not tasks and not overdue:
        st.caption("締切前の課題はありません。チャットで「今日レポートあった、15日まで」と送るか、下から追加できます")
    for t in overdue + tasks:
        with st.container(border=True):
            a, b, c = st.columns([0.06, 0.8, 0.14], vertical_alignment="center")
            if a.checkbox("完了", key=f"done{t['id']}", label_visibility="collapsed"):
                t["done"] = True
                st.rerun()
            left = _left(t["deadline"], today)
            left = f":red[{left}]" if (t["deadline"] - today).days <= 1 else left
            b.markdown(f"**{t['course']}**　{t['kind']}  \n:gray[締切 {_fmt_date(t['deadline'])}]　{left}")
            if c.button("削除", key=f"del{t['id']}", icon=":material/delete:", type="tertiary"):
                bot.remove_task(t["id"])
                st.rerun()

    if tasks or overdue:
        st.download_button("カレンダーに追加", sv.make_ics(bot.tasks), file_name="tasks.ics", mime="text/calendar",
                           type="primary", icon=":material/event:", help="締切の前日18時に通知する .ics ファイル")

    # 課題がないときは追加欄を最初から開いておく
    with st.expander("課題を追加", icon=":material/add:", expanded=not (tasks or overdue)):
        courses = sorted({c["name"] for c in bot.classes}) + ["その他"]
        with st.form("task_form", clear_on_submit=True, border=False):
            c1, c2 = st.columns(2)
            course = c1.selectbox("授業", courses)
            other = c2.text_input("授業名（その他のとき）")
            c3, c4 = st.columns(2)
            kind = c3.selectbox("種類", ["レポート", "課題", "小テスト", "宿題"])
            deadline = c4.date_input("締切", today + dt.timedelta(days=7), min_value=today)
            if st.form_submit_button("追加", type="primary"):
                name = other.strip() if course == "その他" else course
                if name:
                    bot.add_task(name, kind, deadline)
                    st.rerun()

    done = [t for t in bot.tasks if t["done"]]
    if done:
        with st.expander(f"完了した課題 {len(done)}件"):
            for t in done:
                st.markdown(f":gray[~~{t['course']} {t['kind']}（{_fmt_date(t['deadline'])}）~~]")


# ---------- 電車 ----------

def train_page(bot, now):
    st.title("帰りの電車")
    last = sv.latest_started_class(bot.classes, now)

    c1, c2, c3 = st.columns(3)
    bids = list(sv.BUILDINGS)
    default_b = last["building"] if last and last.get("building") in bids else bids[0]
    building = c1.selectbox("今いる建物", bids, index=bids.index(default_b),
                            format_func=lambda i: sv.BUILDINGS[i]["name"], help="初期値は直近の授業の建物")
    todays = sv.classes_on(bot.classes, now.weekday())
    opts = ["今すぐ"] + [f"{c['period']}限（{c['name']}）の後" for c in todays if sv.PERIODS[c["period"]][1] > now.time()]
    when = c2.selectbox("出発", opts)
    depart = now
    if when != "今すぐ":
        depart = dt.datetime.combine(now.date(), sv.PERIODS[int(when.split("限")[0])][1])
    ids = list(sv.STATIONS)
    station = c3.selectbox("いつもの駅", ids, index=ids.index(bot.settings["station"]),
                           format_func=lambda i: sv.STATIONS[i]["name"])
    bot.settings["station"] = station

    # 2駅を並べて比べる。いつもの駅を左に置き、その時刻だけ強調色にする
    cols = st.columns(2)
    for col, sid in zip(cols, sorted(ids, key=lambda i: i != station)):
        s = sv.STATIONS[sid]
        with col:
            dirs = s["directions"]
            bot.settings["direction"][sid] = st.segmented_control(
                f"{s['name']}の方面", dirs, default=bot.settings["direction"][sid], key=f"dir_{sid}",
                label_visibility="collapsed") or bot.settings["direction"][sid]
            walk, arrive, trains = sv.plan_trains(depart, building, sid, bot.settings["direction"][sid])
            train_card({"station": sid, "direction": bot.settings["direction"][sid], "walk": walk, "arrive": arrive,
                        "trains": trains, "origin": sv.BUILDINGS[building]["name"]}, now, lead=sid == station)
            st.link_button("駅までの道案内", sv.maps_url(s), icon=":material/directions_walk:", width="stretch")

    _map([sv.STATIONS[station]], sv.BUILDINGS[building], height=300)
    st.caption("時刻表はダミーデータ、駅までの徒歩分は推定値です")


# ---------- マップ ----------

def map_page(bot, now):
    st.title("キャンパスマップ")
    places = {**sv.BUILDINGS, **sv.STATIONS}
    nxt, _ = sv.next_class(bot.classes, now)
    default = nxt["building"] if nxt and nxt.get("building") in places else next(iter(places))
    keys = list(places)
    c1, c2 = st.columns([0.6, 0.4], vertical_alignment="bottom")
    pid = c1.selectbox("場所", keys, index=keys.index(default), format_func=lambda k: places[k]["name"],
                       help="初期値は次の授業の建物")
    p = places[pid]
    c2.link_button(f"{p['name']}への道案内", sv.maps_url(p), type="primary", icon=":material/directions_walk:",
                   width="stretch")
    _map([p], height=420)

    here = [c for c in bot.classes if c.get("building") == pid]
    if here:
        st.subheader("この建物の授業")
        st.markdown("  \n".join(
            f"{DAYS[c['weekday']]}{c['period']}限　{c['name']}　:gray[{c.get('room', '')}]"
            for c in sorted(here, key=lambda c: (c["weekday"], c["period"]))))
