"""データの読み込みと、時間割・電車・地図・カレンダーの処理。対話には関与しない。"""
import csv
import json
import datetime as dt
from pathlib import Path

import jpholiday

from .nlu import fuzzy_contains

DATA = Path(__file__).resolve().parent.parent / "data"
WEEKDAY_JA = "月火水木金土日"


def _load(name):
    with open(DATA / name, encoding="utf-8") as f:
        return json.load(f)


def _hm(s):
    h, m = map(int, s.split(":"))
    return dt.time(h, m)


PERIODS = {p["period"]: (_hm(p["start"]), _hm(p["end"])) for p in _load("periods.json")["periods"]}
DEFAULT_CLASSES = _load("timetable.json")["classes"]  # 初期値（ダミー）
_places = _load("places.json")
BUILDINGS = {b["id"]: b for b in _places["buildings"]}
STATIONS = {s["id"]: s for s in _places["stations"]}


def _load_trains():
    rows = []
    with open(DATA / "trains.csv", encoding="utf-8") as f:
        lines = (l for l in f if not l.startswith("#"))
        for r in csv.DictReader(lines):
            r["time"] = _hm(r["time"])
            rows.append(r)
    return rows


TRAINS = _load_trains()


# ---------- 時間割（classes は利用者ごとの授業リスト） ----------

def classes_on(classes, weekday):
    return sorted((c for c in classes if c["weekday"] == weekday), key=lambda c: c["period"])


def class_at(classes, weekday, period):
    return next((c for c in classes if c["weekday"] == weekday and c["period"] == period), None)


def latest_started_class(classes, now):
    """今日、開始時刻を過ぎた授業のうち最後のもの（受講中 or 直前に終わった授業）。"""
    started = [c for c in classes_on(classes, now.weekday()) if PERIODS[c["period"]][0] <= now.time()]
    return started[-1] if started else None


def ongoing_class(classes, now):
    c = latest_started_class(classes, now)
    if c and now.time() <= PERIODS[c["period"]][1]:
        return c
    return None


def next_class(classes, now):
    """今以降で最初の授業と、その日付を返す（1週間先まで探す）。"""
    for offset in range(8):
        day = now.date() + dt.timedelta(days=offset)
        for c in classes_on(classes, day.weekday()):
            if offset > 0 or PERIODS[c["period"]][0] > now.time():
                return c, day
    return None, None


def best_match(items, text, names=lambda x: [x["name"], *x.get("aliases", [])]):
    """text に名前（略称を含む）が出てくる item を探す。→ (item, 一致度)。一致度 1.0 は完全一致、1未満は誤字込み。
    完全一致を優先し、同じ一致度なら長い名前を優先する（「データベース論」>「データベース」）。"""
    best, key = None, (0.0, 0)
    for item in items:
        for name in names(item):
            score = fuzzy_contains(name, text)
            if score and (score, len(name)) > key:
                best, key = item, (score, len(name))
    return best, key[0]


def find_course(classes, text):
    """発話中の授業名・略称（完全一致のみ。ひらがな・カタカナの違いは同じとみなす）。"""
    c, score = best_match(classes, text)
    return c if score == 1.0 else None


def guess_course(classes, text):
    """誤字も許して授業を探す。→ (授業, 完全一致か)"""
    c, score = best_match(classes, text)
    return c, score == 1.0


def describe_class(c):
    s, e = PERIODS[c["period"]]
    b = BUILDINGS[c["building"]]["name"] if c.get("building") in BUILDINGS else ""
    room = f"{b} {c.get('room', '')}".strip() or "教室未登録"
    return f"{c['period']}限 {c['name']}（{room}、{s:%H:%M}〜{e:%H:%M}）"


# ---------- 場所 ----------

def guess_place(text):
    """建物・駅を探す（建物を優先、誤字も許す）。→ (場所, 完全一致か)"""
    found = [best_match(group, text) for group in (BUILDINGS.values(), STATIONS.values())]
    exact = next((p for p, score in found if score == 1.0), None)
    if exact:
        return exact, True
    p, score = max(found, key=lambda x: x[1])
    return (p, False) if score else (None, False)


def find_place(text):
    """建物か駅（完全一致のみ）。"""
    p, exact = guess_place(text)
    return p if exact else None


def maps_url(place):
    # Google マップの経路URL（APIキー不要）。現在地からの徒歩ルートを開く
    return f"https://www.google.com/maps/dir/?api=1&destination={place['lat']},{place['lng']}&travelmode=walking"


# ---------- 電車 ----------

def find_station(text):
    for s in STATIONS.values():
        if any(a.lower() in text.lower() for a in s["aliases"]):
            return s["id"]
    return None


def find_direction(text, station_id):
    for d in STATIONS[station_id]["directions"]:
        if d.replace("方面", "") in text:
            return d
    return None


def walk_minutes(building_id, station_id, default=12):
    b = BUILDINGS.get(building_id)
    return b["walk"][station_id] if b else default


YEAR_END = {(12, 30), (12, 31), (1, 1), (1, 2), (1, 3)}  # 鉄道各社は年末年始を休日ダイヤで運転する


def day_type(date):
    """その日のダイヤ：平日 weekday / 土曜 saturday / 日曜・祝日・年末年始 holiday。"""
    if date.weekday() == 6 or jpholiday.is_holiday(date) or (date.month, date.day) in YEAR_END:
        return "holiday"
    return "saturday" if date.weekday() == 5 else "weekday"


def day_label(date):
    return "平日ダイヤ" if day_type(date) == "weekday" else "土休日ダイヤ"


def timetable(station_id, direction, date):
    """その日の時刻表（時刻順）。土曜ダイヤが無い駅は休日ダイヤを使う。"""
    rows = [r for r in TRAINS if r["station"] == station_id and r["direction"] == direction]
    kind = day_type(date)
    if kind == "saturday" and not any(r["daytype"] == "saturday" for r in rows):
        kind = "holiday"
    return sorted((r for r in rows if r["daytype"] == kind), key=lambda r: r["time"])


def next_trains(depart_at, station_id, direction, walk_min, n=3):
    """depart_at に建物を出て walk_min 分歩いたとき、乗れる電車を n 本返す。"""
    arrive = depart_at + dt.timedelta(minutes=walk_min)
    if arrive.date() != depart_at.date():
        return arrive, []  # 日付をまたぐ（終電後）
    rows = timetable(station_id, direction, depart_at.date())
    return arrive, [r for r in rows if r["time"] >= arrive.time()][:n]


def plan_trains(depart_at, building_id, station_id, direction, n=3):
    """建物を depart_at に出たときの到着時刻と、乗れる電車 [(電車, 区分)] を返す。
    電車は {"time", "type", "dest"}。駅での待ちが3分未満の電車は「急げば」とし、その次をおすすめにする。"""
    walk = walk_minutes(building_id, station_id)
    arrive, rows = next_trains(depart_at, station_id, direction, walk, n)
    tight = [(dt.datetime.combine(arrive.date(), r["time"]) - arrive).seconds < 180 for r in rows]
    best = next((i for i, x in enumerate(tight) if not x), 0)
    tags = ["おすすめ" if i == best else "急げば間に合う" if tight[i] else "" for i in range(len(rows))]
    return walk, arrive, list(zip(rows, tags))


def train_label(r):
    """「急行 京都行」。普通は種別を省く。"""
    kind = "" if r.get("type") in ("", "普通", None) else r["type"] + " "
    return f"{kind}{r['dest']}行" if r.get("dest") else kind.strip()


# ---------- 課題・カレンダー ----------

def tasks_due_soon(tasks, today, days=1):
    return [t for t in tasks if not t["done"] and 0 <= (t["deadline"] - today).days <= days]


def make_ics(tasks):
    """課題を終日予定として書き出す。締切前日 18:00 に通知（VALARM）。"""
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//kyotanabe-bot//JA"]
    for i, t in enumerate(t for t in tasks if not t["done"]):
        d = t["deadline"]
        lines += [
            "BEGIN:VEVENT",
            f"UID:task-{i}-{d:%Y%m%d}@kyotanabe-bot",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{d:%Y%m%d}",
            f"DTEND;VALUE=DATE:{d + dt.timedelta(days=1):%Y%m%d}",
            f"SUMMARY:【締切】{t['course']} {t['kind']}",
            "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:明日締切: {t['course']} {t['kind']}",
            "TRIGGER:-PT6H", "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
