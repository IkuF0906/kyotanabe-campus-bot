"""データの読み込みと、時間割・電車・地図・カレンダーの処理。対話には関与しない。"""
import csv
import json
import datetime as dt
from pathlib import Path

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


def find_course(classes, text):
    """発話中に含まれる授業名・略称を探す（長い名前を優先）。"""
    cands = []
    for c in classes:
        for name in [c["name"], *c.get("aliases", [])]:
            if name.lower() in text.lower():
                cands.append((len(name), c))
    return max(cands, key=lambda x: x[0])[1] if cands else None


def describe_class(c):
    s, e = PERIODS[c["period"]]
    b = BUILDINGS[c["building"]]["name"] if c.get("building") in BUILDINGS else ""
    room = f"{b} {c.get('room', '')}".strip() or "教室未登録"
    return f"{c['period']}限 {c['name']}（{room}、{s:%H:%M}〜{e:%H:%M}）"


# ---------- 場所 ----------

def find_place(text):
    for b in BUILDINGS.values():
        if any(a in text for a in [b["name"], *b["aliases"]]):
            return b
    for s in STATIONS.values():
        if any(a in text for a in [s["name"], *s["aliases"]]):
            return s
    return None


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


def next_trains(depart_at, station_id, direction, walk_min, n=3):
    """depart_at に建物を出て walk_min 分歩いたとき、乗れる電車を n 本返す。"""
    arrive = depart_at + dt.timedelta(minutes=walk_min)
    daytype = "holiday" if depart_at.weekday() >= 5 else "weekday"  # 祝日は未対応
    times = sorted(r["time"] for r in TRAINS
                   if r["station"] == station_id and r["direction"] == direction and r["daytype"] == daytype)
    return arrive, [t for t in times if t >= arrive.time()][:n]


def plan_trains(depart_at, building_id, station_id, direction, n=3):
    """建物を depart_at に出たときの到着時刻と、乗れる電車 [(時刻, 区分)] を返す。
    駅での待ちが3分未満の電車は「急げば」とし、その次をおすすめにする。"""
    walk = walk_minutes(building_id, station_id)
    arrive, times = next_trains(depart_at, station_id, direction, walk, n)
    tight = [(dt.datetime.combine(arrive.date(), t) - arrive).seconds < 180 for t in times]
    best = next((i for i, x in enumerate(tight) if not x), 0)
    tags = ["おすすめ" if i == best else "急げば間に合う" if tight[i] else "" for i in range(len(times))]
    return walk, arrive, list(zip(times, tags))


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
