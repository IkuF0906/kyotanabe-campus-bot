"""意図判定（nlu.detect_intent）の正解率を測る。実行: python evaluate.py [dev|test|all]

data/eval/utterances.csv の発話を判定し、意図ごとの正解率・取り違え・間違えた発話を表示する。
dev はルールの改善に使ってよい発話、test は改善に使わず最後の評価だけに使う発話。
アプリの「通じなかった発話」から書き出した CSV の発話も、正解の意図を付けて dev に足していく。
"""

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

from bot import nlu

PATH = Path(__file__).resolve().parent / "data" / "eval" / "utterances.csv"


def load(split):
    with open(PATH, encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if split == "all" or r["split"] == split]


def evaluate(rows):
    per = defaultdict(lambda: [0, 0])  # 意図 → [正解数, 件数]
    confusion = Counter()
    errors = []
    for r in rows:
        got = nlu.detect_intent(nlu.normalize(r["text"]))
        per[r["intent"]][1] += 1
        if got == r["intent"]:
            per[r["intent"]][0] += 1
        else:
            confusion[(r["intent"], got)] += 1
            errors.append((r["text"], r["intent"], got))
    return per, confusion, errors


def main():
    split = sys.argv[1] if len(sys.argv) > 1 else "dev"
    rows = load(split)
    per, confusion, errors = evaluate(rows)
    ok = sum(c for c, _ in per.values())
    print(f"[{split}] 正解率 {ok}/{len(rows)} = {ok / len(rows):.1%}\n")
    print(f"{'意図':<12}{'正解':>6}{'件数':>6}{'正解率':>8}")
    for intent, (c, n) in sorted(per.items()):
        print(f"{intent:<12}{c:>6}{n:>6}{c / n:>8.0%}")
    if confusion:
        print("\n取り違え（正解 → 判定）")
        for (gold, got), n in confusion.most_common():
            print(f"  {gold} → {got}: {n}")
        print("\n間違えた発話")
        for text, gold, got in errors:
            print(f"  {text}　（正解 {gold} / 判定 {got}）")


if __name__ == "__main__":
    main()
