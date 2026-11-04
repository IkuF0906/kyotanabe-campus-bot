"""京田辺キャンパス チャットボット（試作版）。起動: streamlit run app.py"""
import datetime as dt

import streamlit as st

import storage
import views
from bot import services as sv
from bot.dialogue import Bot

st.set_page_config(page_title="京田辺キャンパスbot", page_icon=":material/train:", layout="wide")

# 共通のスタイル：本文の最大幅と、時刻表示（等幅・桁そろえ）
st.html("""<style>
.block-container {max-width: 1120px; padding-top: 48px}
.t {font-family: var(--st-code-font, "JetBrains Mono", monospace); font-variant-numeric: tabular-nums}
</style>""")

if "bot" not in st.session_state:
    st.session_state.bot = Bot()
bot = st.session_state.bot


def reset():
    # 時間割・課題・設定を初期状態に戻す（直後の保存でブラウザの内容も上書きされる）
    st.session_state.bot = Bot()
    st.session_state.pop("history", None)


def page(func, title, icon, default=False):
    # 各ページに共通の bot と now を渡す
    return st.Page(lambda: func(bot, now), title=title, icon=icon, url_path=func.__name__, default=default)


nav = st.navigation([
    page(views.chat_page, "チャット", ":material/chat_bubble:", default=True),
    page(views.timetable_page, "時間割", ":material/calendar_view_week:"),
    page(views.reminder_page, "リマインダー", ":material/notifications:"),
    page(views.train_page, "電車", ":material/train:"),
    page(views.map_page, "マップ", ":material/map:"),
], position="sidebar")

# ---------- デモ用の時刻（全ページ共通、ナビの下に小さく） ----------
with st.sidebar:
    with st.expander("デモ用の時刻", icon=":material/schedule:"):
        fixed = st.toggle("時刻を指定する", value=True, help="デモで「4限の後」などを再現するため")
        d = st.date_input("日付", dt.date.today(), disabled=not fixed)
        t = st.time_input("時刻", dt.time(14, 50), step=300, disabled=not fixed)
    now = dt.datetime.combine(d, t) if fixed else dt.datetime.now()
    st.caption(f"現在 {now:%m/%d}（{sv.WEEKDAY_JA[now.weekday()]}）{now:%H:%M}")
    views.miss_log(bot)
    st.button("保存データを消す", icon=":material/restart_alt:", on_click=reset, type="tertiary",
              help="時間割・課題・設定はこのブラウザに保存されます。初期状態に戻します")

nav.run()
with st.sidebar:
    storage.sync(bot)
