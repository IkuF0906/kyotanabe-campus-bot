"""画面なしで対話シナリオを確認する。実行: python test_dialogue.py"""
import datetime as dt

from bot.dialogue import Bot

NOW = dt.datetime(2026, 11, 4, 14, 50)  # 水曜 14:50（3限 情報倫理の直後）

SCENARIOS = [
    ["今日レポートあった、15日まで", "はい", "課題一覧"],
    ["レポート出た", "いいえ", "プロ演", "来週金曜"],
    ["今から帰る", "興戸から帰る", "いつも興戸の奈良方面に設定", "4限のあと帰る"],
    ["次の授業は？", "明日の時間割", "月曜の授業"],
    ["情報メディア館どこ？", "次の教室どこ？", "場所教えて", "図書館"],
    ["データベースの課題、11/20締切", "宿題ある？"],
    ["レポートあった", "ヘルプ"],  # 締切を聞き返している途中で話題が変わる
    ["あいうえお"],
    # 時間割の登録・削除
    ["月曜4限に情報理論を追加", "恵道館 KD305", "月曜の授業"],
    ["火曜日の2時限目は データ構造、知真館TC1-201で"],
    ["水2にネットワーク論入れて", "はい", "はい", "情報メディア館 JM202"],  # 既存の授業の置き換え
    ["水曜2限どこ？", "月曜5限は？"],
    ["木曜3限追加して", "統計演習", "なし", "木曜の授業"],
    ["金1消して", "はい", "金曜の授業"],
    ["火4削除", "いいえ"],
    ["月曜5限は？"],                                 # 質問は登録にしない
    ["いつもの駅を変更", "興戸"],
]

for sc in SCENARIOS:
    bot = Bot()
    print("=" * 60)
    for utt in sc:
        r = bot.respond(utt, NOW)
        print(f"👤 {utt}\n🤖 {r.text}")
        for label, url in r.links:
            print(f"   🔗 {label}: {url}")
        if r.train:
            p = r.train
            print(f"   🚃 {p['station']} {p['direction']} 徒歩{p['walk']}分 {p['arrive']:%H:%M}着: "
                  + ", ".join(f"{t:%H:%M}{'(' + tag + ')' if tag else ''}" for t, tag in p["trains"]))
        if r.choices:
            print("   🔘 " + " / ".join(r.choices))
        print()
