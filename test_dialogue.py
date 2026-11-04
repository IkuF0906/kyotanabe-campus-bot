"""画面なしで対話と部品を確認する。実行: python test_dialogue.py（-v で対話の全文を表示）

各シナリオは (発話, 応答に含まれるべき文字列) の並び。期待する文字列が None ならその応答は確認しない。
"""
import datetime as dt
import json
import sys

from bot import nlu
from bot import services as sv
from bot.dialogue import Bot

NOW = dt.datetime(2026, 11, 4, 14, 50)  # 水曜 14:50（3限 情報倫理の直後）
VERBOSE = "-v" in sys.argv

SCENARIOS = {
    "課題の登録（授業を時間割から推定→確認）": [
        ("今日レポートあった、15日まで", "情報倫理"), ("はい", "登録しました"), ("課題一覧", "11/15"),
    ],
    "推定が違う→授業名を聞き直す": [
        ("レポート出た", "締切はいつ"), ("いいえ", "どの授業"), ("プロ演", "締切はいつ"), ("来週金曜", "11/13"),
    ],
    "誤字の授業名は確認してから登録": [
        ("線型代数のレポート、20日まで", "**線形代数**"), ("はい", "登録しました"),
    ],
    "締切を聞いている途中で別の話題": [
        ("レポートあった", "締切はいつ"), ("ヘルプ", "こんなことができます"),
    ],
    "期間・授業で絞り込み": [
        ("データベースの課題、11/6締切", "登録しました"), ("線形代数の課題、11/20まで", "登録しました"),
        ("今週の締切は？", "データベース論"), ("来週の課題", "はありません"), ("線形代数の課題ある？", "線形代数の課題です"),
    ],
    "課題の完了（候補が複数→選ぶ）と削除（確認）": [
        ("データベースの課題、11/6締切", None), ("線形代数のレポート、11/20まで", None),
        ("課題終わった", "どの課題"), ("2つ目", "線形代数"),
        ("データベースの課題消して", "削除しますか"), ("はい", "削除しました"), ("課題一覧", "ありません"),
    ],
    "「2つ目」は表示した順（締切順）で数える": [
        ("線形代数のレポート、11/20まで", None), ("データベースの課題、11/6締切", None),
        ("課題終わった", "どの課題"), ("2つ目", "線形代数"),
    ],
    "同じ授業の課題をボタンで選ぶ": [
        ("データベースの課題、11/6締切", None), ("データベースのレポート、11/10まで", None),
        ("データベースの課題消して", "どの課題"), ("データベース論 レポート（11/10）", "レポートを削除しました"),
    ],
    "確認の質問では完了にしない／「出た」は登録": [
        ("線形代数のレポート、11/20まで", None), ("線形代数のレポート出したっけ？", "線形代数の課題です"),
        ("3限終わった、レポート出た", "締切はいつ"),
    ],
    "確認に関係ない返事は聞き直す": [
        ("データベースの課題、11/6締切", None), ("データベースの課題消して", "削除しますか"),
        ("どっちでもない", "「はい」か「いいえ」"), ("キャンセル", "キャンセルしました"),
    ],
    "最寄り駅の質問と、駅の設定": [
        ("最寄り駅はどこ？", "同志社前駅の場所"), ("場所教えて", "どの建物"), ("最寄りは興戸にして", "興戸駅"),
    ],
    "電車（今いる建物・時限・駅の指定・設定）": [
        ("今から帰る", "香知館から"), ("興戸から帰る", None), ("いつも興戸の奈良方面に設定", "興戸駅（奈良方面）"),
        ("4限のあと帰る", "16:25 に出る場合"),
    ],
    "時間割": [
        ("次の授業は？", "プログラミング演習"), ("明日の時間割", "確率統計"), ("月曜5限は？", "空きコマ"),
    ],
    "場所（誤字・授業名・聞き返し）": [
        ("情報メデイア館どこ", "のことですね"), ("次の教室どこ？", "JM105"), ("場所教えて", "どの建物"), ("図書館", "地図"),
    ],
    "時間割の登録（教室を聞き返す）・置き換え・削除": [
        ("月曜4限に情報理論を追加", "教室はどこ"), ("恵道館 KD305", "登録しました"), ("月曜の授業", "情報理論"),
        ("水2にネットワーク論入れて", "置き換えますか"), ("はい", "教室はどこ"), ("情報メディア館 JM202", "ネットワーク論"),
        ("金1消して", "削除していいですか"), ("はい", "削除しました"), ("火4削除", None), ("いいえ", "やめました"),
    ],
    "確認していないのに「はい」": [("はい", "確認していることはありません")],
    "わからない発話": [("あいうえお", "理解できませんでした")],
}


def run_scenarios():
    failures = 0
    for title, turns in SCENARIOS.items():
        bot = Bot()
        if VERBOSE:
            print("=" * 60 + f"\n{title}")
        for utt, expect in turns:
            r = bot.respond(utt, NOW)
            if VERBOSE:
                print(f"> {utt}\n  {r.text}" + (f"\n  [{' / '.join(r.choices)}]" if r.choices else ""))
            if expect is not None and expect not in r.text:
                failures += 1
                print(f"NG {title}: 「{utt}」の応答に「{expect}」がない\n   → {r.text}")
    return failures


def check(cond, label):
    if not cond:
        print(f"NG {label}")
    return 0 if cond else 1


def run_units():
    f = 0
    today = NOW.date()
    # 日付・締切
    f += check(nlu.find_deadline("今日レポートあった、15日まで", today) == dt.date(2026, 11, 15), "締切: 15日まで")
    f += check(nlu.find_deadline("11/3まで", today) == dt.date(2027, 11, 3), "締切: 過ぎた日付は翌年")
    f += check(nlu.find_range("今週", today) == (today, dt.date(2026, 11, 8)), "期間: 今週")
    # 表記ゆれ
    f += check(nlu.fuzzy_contains("線形代数", "線型代数") > 0, "誤字: 線型代数")
    f += check(nlu.fuzzy_contains("情報倫理", "情報理論を追加") == 0, "誤字: 情報理論は情報倫理ではない")
    f += check(nlu.fuzzy_contains("知真館", "知心館") == 0, "誤字: 3文字は完全一致のみ")
    f += check(nlu.fuzzy_contains("プログラミング演習", "ぷろぐらみんぐ演習") == 1.0, "かな: ひらがな・カタカナ")
    # ダイヤ
    f += check(sv.day_type(dt.date(2026, 11, 23)) == "holiday", "ダイヤ: 勤労感謝の日")
    f += check(sv.day_type(dt.date(2026, 12, 31)) == "holiday", "ダイヤ: 年末")
    f += check(sv.day_type(dt.date(2026, 11, 7)) == "saturday", "ダイヤ: 土曜")
    f += check(len(sv.timetable("kodo", "京都方面", dt.date(2026, 11, 7))) > 0, "ダイヤ: 土曜は休日ダイヤで代用")
    _, _, trains = sv.plan_trains(dt.datetime(2026, 11, 4, 23, 50), "jm", "kodo", "京都方面")
    f += check(trains == [], "電車: 終電後は空")
    # 保存と復元
    b = Bot()
    b.add_task("線形代数", "レポート", dt.date(2026, 11, 15))
    b.log_miss("あいうえお", "unknown", NOW, "test")
    c = Bot()
    f += check(c.load(json.loads(json.dumps(b.dump(), ensure_ascii=False))), "保存: 読み込める")
    f += check(c.tasks == b.tasks and c.misses == b.misses, "保存: 内容が同じ")
    c.add_task("x", "課題", today)
    f += check(c.tasks[-1]["id"] == 2, "保存: 読み込み後の課題番号が続く")
    f += check(Bot().load(None) is False and Bot().load({"tasks": [{"deadline": "x"}]}) is False, "保存: 壊れた内容は無視")
    return f


if __name__ == "__main__":
    failures = run_scenarios() + run_units()
    n = sum(len(t) for t in SCENARIOS.values())
    print(f"シナリオ {len(SCENARIOS)}件（{n}発話）と部品の確認: " + ("すべて OK" if not failures else f"NG {failures}件"))
    sys.exit(1 if failures else 0)
