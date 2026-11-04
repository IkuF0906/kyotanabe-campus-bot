"""画面を開いて話しかけても例外が出ないか（Streamlit の AppTest で、ブラウザなしに動かす）。"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_app_runs_and_replies():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    n = len(at.chat_message)
    at.chat_input[0].set_value("今から帰る").run()
    assert not at.exception
    assert len(at.chat_message) > n
