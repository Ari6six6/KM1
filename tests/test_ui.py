"""The thinking-ticker: inert off a TTY, live on one."""

from __future__ import annotations

import sys

from mor import ui


def test_spinner_is_inert_off_a_tty(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
    with ui.Spinner("lead is thinking") as sp:
        assert sp.active is False       # no thread, no output on a pipe
        sp.set("lead · web_fetch")      # never raises
    assert sp.active is False


def test_spinner_runs_and_clears_on_a_tty(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    import time
    with ui.Spinner("worker is thinking") as sp:
        assert sp.active is True
        time.sleep(0.25)                # let it draw a few frames
        sp.set("worker · run_shell")
    out = capsys.readouterr().out
    assert "worker" in out and "\r" in out   # it drew, then cleared the line
