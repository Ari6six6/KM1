"""The live token line: inert off a TTY, streams and clears on one."""

from __future__ import annotations

import sys

from mor import ui


def test_streamer_is_inert_off_a_tty(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
    with ui.Streamer("lead") as st:
        assert st.active is False       # no output on a pipe
        st.feed("some tokens")          # never raises, prints nothing
    assert st.active is False
    assert capsys.readouterr().out == ""


def test_streamer_renders_tokens_and_clears_on_a_tty(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    with ui.Streamer("worker") as st:
        assert st.active is True
        st.feed("hello ")
        st.feed("world")
    out = capsys.readouterr().out
    assert "worker" in out and "world" in out and "\r" in out   # drew, then cleared
