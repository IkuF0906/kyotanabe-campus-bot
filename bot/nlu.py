"""ルールベースの自然言語理解：意図(intent)の判定と、日付・時限などのスロット抽出。"""

import datetime as dt
import re
import unicodedata

WEEKDAY_JA = "月火水木金土日"

# 意図ごとのキーワード。上から順に判定する（先に当たったものを採用）
TASK_WORDS = r"(レポート|課題|宿題|小テスト|提出物|締切|締め切り|〆切|やること)"
QUESTION = r"(\?|一覧|教えて|確認|見せて|ある？|あるっけ|残って|何がある)"

INTENT_RULES = [
    ("help", r"(ヘルプ|使い方|何ができる|なにができる)"),
    (
        "settings",
        r"(設定|変更|変え|いつも).*(駅|方面|興戸|同志社前|京都|奈良|京橋|木津)"
        r"|(駅|方面|興戸|同志社前).*(設定|変更|変え|にして|にする)",
    ),
    ("go_home", r"(帰る|帰り|帰ろ|帰宅|かえる|電車|終電|次の便|駅まで)"),
    ("where", r"(どこ|場所|行き方|どうやって行|道案内|地図|マップ|行きたい)"),
    ("timetable", r"(授業|時間割|何限|限目|コマ|空いて|次は|^次(なに|何|なん))"),
    ("greet", r"(こんにちは|こんばんは|おはよう|ありがとう|はじめまして)"),
]

YES = r"^(はい|うん|ok|おk|お願い|おねがい|それで|いいよ|いいです|大丈夫|そう|y)"
NO = r"^(いいえ|いや|違う|ちがう|ちゃう|no|n$|だめ)"
RANGE_WORDS = r"(今日|きょう|明日|あした|今週|来週|再来週|\d+日以内)"
CANCEL = r"(キャンセル|やめる|やめて|取り消し|もういい)"


def normalize(text):
    # 全角英数→半角、などの表記ゆれをまとめる
    return unicodedata.normalize("NFKC", text).strip()


CLASS_EDIT = r"(追加|登録|入れて|変更|消して|削除|消す|外して|取り消)"
CLASS_DELETE = r"(消して|削除|消す|外して|取り消)"


# 「レポート出た」(出された) と「レポート出した」(提出した) を区別する
TASK_DONE = r"(終わった|終わらせた|終えた|出した|提出した|提出済|提出完了|完了|済んだ|済ませた|片付いた|やった)"


def detect_intent(text):
    if re.search(TASK_WORDS, text):
        adding = re.search(r"(あった|出た|出され|追加|登録)", text)
        asking = re.search(QUESTION + r"|っけ", text)
        # 「出したっけ？」は確認の質問なので完了にしない。「3限終わった、レポート出た」は登録
        if re.search(TASK_DONE, text) and not asking and not adding:
            return "done_task"
        if re.search(CLASS_DELETE, text):
            return "delete_task"
        if asking and not adding:
            return "list_tasks"
        # 「来週の課題」「今日の宿題」：期間＋「の」＋課題の語だけなら一覧とみなす（「明日小テスト」は登録）
        if not adding and re.search(RANGE_WORDS + "の" + TASK_WORDS, text):
            return "list_tasks"
        return "add_task"
    if find_slot(text):
        if re.search(QUESTION + r"|何|なに|どこ", text):
            return "where" if "どこ" in text else "timetable"  # 「月曜5限は？」「水2どこ？」
        # 「月曜2限に線形代数を追加」「火3は英語」「金1消して」
        if re.search(CLASS_EDIT, text) or re.search(r"(限目?|[1-7])\s*(は|に)\s*\S", text):
            return "edit_class"
    for name, pat in INTENT_RULES:
        if re.search(pat, text):
            return name
    return "unknown"


def is_yes(text):
    return re.search(YES, text, re.I) is not None


def is_no(text):
    return re.search(NO, text, re.I) is not None


def is_cancel(text):
    return re.search(CANCEL, text) is not None


# ---------- 日付 ----------


def _roll_month(year, month, day, today):
    """月指定なしの「15日」を、今日以降で最も近い日付にする。"""
    for k in range(13):
        y, m = year + (month - 1 + k) // 12, (month - 1 + k) % 12 + 1
        try:
            d = dt.date(y, m, day)
        except ValueError:
            continue
        if d >= today:
            return d
    return None


def find_dates(text, today):
    """発話中の日付表現をすべて (文字位置の終わり, date) のリストで返す。"""
    found = []
    rel = {"今日": 0, "きょう": 0, "明日": 1, "あした": 1, "明後日": 2, "あさって": 2}
    for word, off in rel.items():
        for m in re.finditer(word, text):
            found.append((m.start(), m.end(), today + dt.timedelta(days=off)))
    for m in re.finditer(r"(\d+)日後", text):
        found.append((m.start(), m.end(), today + dt.timedelta(days=int(m.group(1)))))
    for m in re.finditer(r"(\d{1,2})[/月](\d{1,2})日?", text):
        mo, d = int(m.group(1)), int(m.group(2))
        try:
            date = dt.date(today.year, mo, d)
            if date < today:
                date = dt.date(today.year + 1, mo, d)
            found.append((m.start(), m.end(), date))
        except ValueError:
            pass
    for m in re.finditer(r"(?<![\d/月])(\d{1,2})日(?!後)", text):
        if any(s <= m.start() < e for s, e, _ in found):
            continue  # 「11月15日」の「15日」は二重に拾わない
        d = _roll_month(today.year, today.month, int(m.group(1)), today)
        if d:
            found.append((m.start(), m.end(), d))
    for m in re.finditer(r"(今週|来週|再来週)?の?([月火水木金土日])曜", text):
        wd = WEEKDAY_JA.index(m.group(2))
        week = {"今週": 0, "来週": 1, "再来週": 2}.get(m.group(1))
        if week is None:  # 「金曜まで」→ 次に来る金曜（今日が金曜なら来週）
            delta = (wd - today.weekday()) % 7 or 7
            d = today + dt.timedelta(days=delta)
        else:
            monday = today - dt.timedelta(days=today.weekday())
            d = monday + dt.timedelta(days=7 * week + wd)
        found.append((m.start(), m.end(), d))
    return sorted(found)


def find_deadline(text, today):
    """「今日レポートあった、15日まで」のように日付が複数あるとき、締切らしいものを選ぶ。"""
    dates = find_dates(text, today)
    if not dates:
        return None
    for s, e, d in dates:  # 直後に「まで」「締切」が続く日付
        if re.match(r"\s*(まで|迄|締切|締め切り|〆切|が期限|提出)", text[e:]):
            return d
    for s, e, d in dates:  # 直前に「締切」「期限」がある日付
        if re.search(r"(締切|締め切り|〆切|期限|提出日?)(は|:)?\s*$", text[:s]):
            return d
    later = [d for s, e, d in dates if d > today]  # 「今日」は課題が出た日の可能性が高い
    return later[-1] if later else None


def find_range(text, today):
    """課題一覧の絞り込み：「今日」「明日」「今週」「来週」「3日以内」→ (開始日, 終了日)。なければ None。"""
    monday = today - dt.timedelta(days=today.weekday())
    if re.search(r"再来週", text):
        return monday + dt.timedelta(days=14), monday + dt.timedelta(days=20)
    if re.search(r"来週", text):
        return monday + dt.timedelta(days=7), monday + dt.timedelta(days=13)
    if re.search(r"今週", text):
        return today, monday + dt.timedelta(days=6)
    m = re.search(r"(\d+)日以内", text)
    if m:
        return today, today + dt.timedelta(days=int(m.group(1)))
    if re.search(r"(明日|あした)", text):
        return today + dt.timedelta(days=1), today + dt.timedelta(days=1)
    if re.search(r"(今日|きょう)", text):
        return today, today
    return None


def find_day(text, today):
    """時間割の質問用：「明日の授業」「金曜の時間割」などの対象日。"""
    dates = find_dates(text, today)
    return dates[0][2] if dates else None


def find_period(text):
    m = re.search(r"([1-7])限", text)
    return int(m.group(1)) if m else None


SLOT_RE = re.compile(r"(?<![\d/])([月火水木金])(?:曜日?)?の?\s*([1-7])\s*(?:時?限目?|コマ目?)?")


def find_slot(text):
    """「月曜2限」「火3」「金曜日の1時限目」→ (曜日, 時限, 文字範囲)。"""
    m = SLOT_RE.search(text)
    if not m:
        return None
    return WEEKDAY_JA.index(m.group(1)), int(m.group(2)), m.span()


def is_delete(text):
    return re.search(CLASS_DELETE, text) is not None


def find_room(text):
    """教室番号（JM301、TC1-102 など）。"""
    m = re.search(r"(?<![A-Za-z])([A-Za-z]{1,3}\d?-?\d{2,4})(?!\d)", text)
    return m.group(1).upper() if m else None


def clean_class_name(text):
    """時限や教室を取り除いた残りから、授業名だけを取り出す。"""
    s = re.sub(
        r"(を|に|は)?\s*(追加|登録|入れ|変更)(して|する|します|しといて|しておいて|お願い|ください|て)*", " ", text
    )
    s = re.sub(r"(の授業|授業|教室|で)\s*$", "", s.strip())
    s = re.sub(r"[、。,.!！\s]+", " ", s).strip()
    return s.strip(" にはをのでと") or None


def find_task_kind(text):
    m = re.search(r"(レポート|小テスト|宿題|課題|提出物)", text)
    return m.group(1) if m else "課題"


# ---------- 表記ゆれ（ひらがな・カタカナ、誤字） ----------


def to_hira(text):
    """カタカナをひらがなに、英字を小文字にそろえる（照合用）。"""
    return "".join(chr(ord(ch) - 0x60) if "ァ" <= ch <= "ヶ" else ch for ch in text).lower()


def _edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def fuzzy_contains(name, text):
    """name が text の中に、誤字込みで含まれるか。完全一致は 1.0、誤字込みなら 1未満、なければ 0。
    3文字以下は完全一致のみ（「知真館」「香知館」のように1文字違いの別名があるため）。
    4文字は同じ長さで1文字違いまで、5〜6文字は1文字の違い・抜け・余分まで、7文字以上は2文字まで。"""
    n, t = to_hira(name), to_hira(text)
    if n in t:
        return 1.0
    if len(n) <= 3:
        return 0.0
    limit, widths = (
        (1, [len(n)])
        if len(n) == 4
        else (1, [len(n) - 1, len(n), len(n) + 1])
        if len(n) <= 6
        else (2, [len(n) - 1, len(n), len(n) + 1])
    )
    best = None
    for w in widths:
        for i in range(0, len(t) - w + 1):
            d = _edit_distance(n, t[i : i + w])
            best = d if best is None else min(best, d)
    return 1 - best / len(n) if best is not None and best <= limit else 0.0
