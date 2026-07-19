"""mored — the headless daemon. A real server on an ephemeral port, driven over
HTTP by the thin client: auth, an order that runs inside the daemon, listing, and
restart-resume (state rebuilt from the event log by a fresh daemon)."""

from __future__ import annotations

import threading
import time
import urllib.error

import pytest

from mor.daemon import make_server, DaemonClient
from mor.order import OrderStore


@pytest.fixture()
def daemon(project):
    httpd = make_server(project, host="127.0.0.1", port=0, token="test-token")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    client = DaemonClient(f"http://127.0.0.1:{port}", "test-token", timeout=10)
    yield httpd, client, project
    httpd.shutdown()
    httpd.server_close()


def _wait_terminal(client, oid, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        state = client.get(oid)["state"]
        if state in ("delivered", "failed"):
            return state
        time.sleep(0.02)
    raise AssertionError(f"order {oid} never reached a terminal state")


def test_health_is_open_and_reports_the_project(daemon):
    _httpd, client, project = daemon
    h = client.health()
    assert h["ok"] is True and h["project"] == project.name


def test_auth_is_required_for_orders(daemon):
    _httpd, client, _project = daemon
    bad = DaemonClient(client.base_url, "wrong-token", timeout=10)
    with pytest.raises(urllib.error.HTTPError) as ei:
        bad.orders()
    assert ei.value.code == 401


def test_order_runs_inside_the_daemon_and_delivers(daemon):
    _httpd, client, project = daemon
    resp = client.submit("research", "what is in the workspace?")
    oid = resp["id"]
    assert resp["state"] == "received"          # returned before the work finishes
    state = _wait_terminal(client, oid)
    assert state == "delivered"
    # the artifact was produced by the daemon, on disk, without a client attached
    report = project.root / "orders" / oid / "report.md"
    assert report.exists() and "what is in the workspace?" in report.read_text()


def test_orders_list_and_get(daemon):
    _httpd, client, _project = daemon
    oid = client.submit("research", "list me")["id"]
    _wait_terminal(client, oid)
    ids = [o["id"] for o in client.orders()]
    assert oid in ids
    full = client.get(oid)
    assert full["state"] == "delivered" and "report.md" in full["artifacts"]


def test_a_restarted_daemon_resumes_order_state(daemon):
    _httpd, client, project = daemon
    oid = client.submit("research", "persist me")["id"]
    _wait_terminal(client, oid)
    # a brand-new daemon (as after kill -9) rebuilds state from the event log alone
    fresh = make_server(project, host="127.0.0.1", port=0, token="test-token")
    try:
        thread = threading.Thread(target=fresh.serve_forever, daemon=True)
        thread.start()
        fresh_client = DaemonClient(f"http://127.0.0.1:{fresh.server_address[1]}",
                                    "test-token", timeout=10)
        assert fresh_client.get(oid)["state"] == "delivered"
        assert oid in [o["id"] for o in fresh_client.orders()]
    finally:
        fresh.shutdown()
        fresh.server_close()


def test_a_restarted_daemon_resumes_a_stranded_order(project):
    """G1 — Kimi's kill -9 experiment as a test. An order marked executing and never
    finished (as a killed daemon leaves it) is re-executed to delivery by the next
    daemon, and the log carries a `resumed` scar."""
    store = OrderStore(project)
    stranded = store.create("research", "interrupted work")
    stranded.record("planned")
    stranded.record("executing")            # the crash: stuck here, never delivered
    assert stranded.state == "executing"

    # a fresh daemon starts (make_server reconciles) and finishes the order
    httpd = make_server(project, host="127.0.0.1", port=0, token="test-token")
    try:
        assert stranded.id in httpd.resumed
        end = time.time() + 10
        while time.time() < end:
            if store.load(stranded.id).state in ("delivered", "failed"):
                break
            time.sleep(0.02)
        reloaded = store.load(stranded.id)
        assert reloaded.state == "delivered"
        assert any(e["kind"] == "resumed" and e.get("from_state") == "executing"
                   for e in reloaded.events)
    finally:
        httpd.server_close()
