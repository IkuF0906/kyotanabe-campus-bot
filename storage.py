"""時間割・課題・設定をブラウザ（localStorage）に保存する。サーバーには何も残さない。

最初の実行で保存済みの内容を読み込み、以降は実行のたびに最新の状態を書き込む。
JavaScript が動かない環境（AppTest など）では読み込みが返ってこず、初期データのまま動く。
"""
import json

import streamlit as st

KEY = "kyotanabe-bot-v1"

_JS = """
export default function ({ data, setStateValue }) {
  const key = "%s";
  try {
    if (data.mode === "load") setStateValue("loaded", localStorage.getItem(key) ?? "");
    else if (data.mode === "save") localStorage.setItem(key, data.value);
  } catch (e) {
    if (data.mode === "load") setStateValue("loaded", "");  // 保存が使えないブラウザでも先へ進む
  }
}
""" % KEY

_store = st.components.v2.component("local_store", js=_JS)


def sync(bot):
    """ページを描いた後に呼ぶ。読み込みが済んでいなければ読み込み、済んでいれば保存する。"""
    ss = st.session_state
    if not ss.get("storage_loaded"):
        result = _store(key="local_store", data={"mode": "load"}, default={"loaded": None},
                        on_loaded_change=lambda: None, height=0)
        if result.loaded is None:
            return  # ブラウザからの返事待ち（返ってきたら再実行される）
        ss.storage_loaded = True
        if result.loaded and bot.load(_parse(result.loaded)):
            st.rerun()  # 読み込んだ内容で描き直す
        return
    _store(key="local_store", data={"mode": "save", "value": json.dumps(bot.dump(), ensure_ascii=False)},
           height=0)


def _parse(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return None
