"""dev の評価用発話がすべて正しく判定されるか。test はここでは見ない（最後の評価だけに使う）。"""

import evaluate


def test_dev_all_correct():
    _, _, errors = evaluate.evaluate(evaluate.load("dev"))
    assert errors == [], "間違えた dev の発話（正解 → 判定）:\n" + "\n".join(f"{t}（{g} → {o}）" for t, g, o in errors)
