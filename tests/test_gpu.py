"""Reaching the box — the failure classification that decides whether `gpu ssh`
waits or gives up. A freshly-rented box resets the first handshakes while it
boots; a wrong key never comes good by waiting. The tool must tell them apart."""

from __future__ import annotations

from mor import gpu


def _run(monkeypatch, rc, out, err):
    monkeypatch.setattr(gpu, "run", lambda *a, **k: (rc, out, err))


def test_handshake_reset_is_transient(monkeypatch):
    # the exact field signature reported from a booting box
    _run(monkeypatch, 255, "",
         "kex_exchange_identification: read: Connection reset by peer\n"
         "Connection reset by 213.5.130.43 port 24439")
    ok, why, transient = gpu.check_connection(["-p", "24439", "root@213.5.130.43"])
    assert ok is False and transient is True
    assert "booting" in why or "rate-limiting" in why


def test_connection_refused_is_transient(monkeypatch):
    _run(monkeypatch, 255, "", "ssh: connect to host x port 22: Connection refused")
    ok, _why, transient = gpu.check_connection(["root@x"])
    assert ok is False and transient is True


def test_timeout_is_transient(monkeypatch):
    _run(monkeypatch, 124, "", "timed out after 30s")
    ok, _why, transient = gpu.check_connection(["root@x"])
    assert ok is False and transient is True


def test_auth_denied_is_permanent(monkeypatch):
    # waiting never fixes a wrong key — don't retry it
    _run(monkeypatch, 255, "", "root@x: Permission denied (publickey).")
    ok, why, transient = gpu.check_connection(["root@x"])
    assert ok is False and transient is False and "key" in why


def test_no_ssh_binary_is_permanent(monkeypatch):
    _run(monkeypatch, 127, "", "ssh binary not found")
    ok, _why, transient = gpu.check_connection(["root@x"])
    assert ok is False and transient is False


def test_success(monkeypatch):
    _run(monkeypatch, 0, "MOR_OK\n", "")
    ok, why, transient = gpu.check_connection(["root@x"])
    assert ok is True and why == "ok" and transient is False
