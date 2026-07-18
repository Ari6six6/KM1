"""The container-isolation helper: command construction and safe degradation."""

from __future__ import annotations

import subprocess

from mor import sandbox


def test_run_in_container_builds_a_locked_down_command(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw

        class R:
            returncode = 0
            stdout = "ok\n"
            stderr = ""
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    rc, out, err = sandbox.run_in_container(tmp_path, "echo hi", runtime="docker",
                                            network="none")
    cmd = captured["cmd"]
    assert rc == 0 and "ok" in out
    assert cmd[:3] == ["docker", "run", "--rm"]
    # the workspace is mounted, nothing else; no host access, no network
    assert "-v" in cmd and f"{tmp_path.resolve()}:/work" in cmd
    assert "--network" in cmd and "none" in cmd
    assert "--cap-drop" in cmd and "ALL" in cmd
    assert "no-new-privileges" in " ".join(cmd)
    # the command is passed as an argument, never interpolated into a host shell
    assert cmd[-3:] == ["sh", "-lc", "echo hi"]


def test_probe_runtime_rejects_a_down_daemon(monkeypatch):
    # docker present but `docker version` exits non-zero (daemon unreachable)
    def fake_run(argv, **kw):
        class R:
            returncode = 1
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert sandbox.probe_runtime() == ""


def test_probe_runtime_accepts_a_live_runtime(monkeypatch):
    def fake_run(argv, **kw):
        class R:
            returncode = 0 if argv[0] == "docker" else 1
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert sandbox.probe_runtime() == "docker"
