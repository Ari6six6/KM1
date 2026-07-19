"""mored — the daemon that owns the realm and works in the dark.

The REPL is a session; a daemon is a presence. ``mored`` runs headless behind a
small, token-authed, loopback HTTP+SSE API (stdlib only). A client — the ``mor``
CLI, or anything that can speak HTTP — submits an **order**; the daemon runs it
**in its own process**, so the work continues whether or not a client is
attached, and the artifact lands on disk. Because an order's state is a projection
of its event log, a daemon that is killed and restarted resumes every order's
state exactly.

This is R0's "it's alive" with one client. The self-healing tunnel, the provider
lifecycle, and multi-client kill-9 replay are later stones; the shape they attach
to is here.

    GET  /health                     liveness (open) — project + orders on disk
    GET  /orders                     list orders (auth)
    POST /orders {kind, brief}       start an order; returns its id (auth)
    GET  /orders/<id>                one order's state + artifacts (auth)
    GET  /orders/<id>/stream         SSE: the order's Hall, live, then `done` (auth)
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mor.order import OrderStore, execute_order

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
_TERMINAL = ("delivered", "failed")


def _brief(order) -> dict:
    return {"id": order.id, "kind": order.kind, "state": order.state, "brief": order.brief}


def _full(order) -> dict:
    d = _brief(order)
    d["artifacts"] = [p.name for p in order.artifacts()]
    d["events"] = len(order.events)
    return d


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):    # keep the daemon quiet; the Hall is the log
        pass

    # -- helpers ---------------------------------------------------------
    def _auth_ok(self) -> bool:
        return self.headers.get("Authorization", "") == f"Bearer {self.server.token}"

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _run_order(self, oid: str) -> None:
        order = self.server.store.load(oid)
        if order is not None:
            execute_order(self.server.project, order, echo=False)

    # -- routes ----------------------------------------------------------
    def do_GET(self):
        if self.path == "/health":
            return self._json(200, {"ok": True, "project": self.server.project.name,
                                    "orders": len(self.server.store.list())})
        if not self._auth_ok():
            return self._json(401, {"error": "unauthorized"})
        parts = [p for p in self.path.split("/") if p]
        if self.path == "/orders":
            return self._json(200, {"orders": [_brief(o) for o in self.server.store.list()]})
        if len(parts) == 2 and parts[0] == "orders":
            order = self.server.store.load(parts[1])
            return self._json(200, _full(order)) if order else \
                self._json(404, {"error": "no such order"})
        if len(parts) == 3 and parts[0] == "orders" and parts[2] == "stream":
            return self._stream(parts[1])
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._auth_ok():
            return self._json(401, {"error": "unauthorized"})
        if self.path != "/orders":
            return self._json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json(400, {"error": "bad json"})
        kind = (payload.get("kind") or "research").strip()
        brief = (payload.get("brief") or "").strip()
        if not brief:
            return self._json(400, {"error": "brief required"})
        # Create synchronously so the client gets a real id, then run in the daemon
        # off the request thread — the order outlives this connection.
        order = self.server.store.create(kind, brief)
        threading.Thread(target=self._run_order, args=(order.id,), daemon=True).start()
        return self._json(202, {"id": order.id, "state": order.state})

    def _stream(self, oid: str) -> None:
        order = self.server.store.load(oid)
        if order is None:
            return self._json(404, {"error": "no such order"})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        hall, pos, deadline = order.hall_path, 0, time.time() + 300
        try:
            while time.time() < deadline:
                if hall.exists():
                    with hall.open() as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos = f.tell()
                    for ln in chunk.splitlines():
                        if ln.strip():
                            self.wfile.write(f"data: {ln}\n\n".encode())
                            self.wfile.flush()
                current = self.server.store.load(oid)
                if current and current.state in _TERMINAL:
                    self.wfile.write(f"event: done\ndata: {json.dumps({'state': current.state})}\n\n"
                                     .encode())
                    self.wfile.flush()
                    return
                time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError):
            return   # the client walked away; the order runs on regardless


def make_server(project=None, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                token: str | None = None) -> ThreadingHTTPServer:
    from mor.config import load_project, daemon_token
    project = project or load_project()
    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.project = project
    httpd.store = OrderStore(project)
    httpd.token = token or daemon_token()
    return httpd


def serve(project=None, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Run the daemon in the foreground until interrupted (headless: nohup / &)."""
    from mor import ui
    from mor.config import current_project_name
    httpd = make_server(project, host, port)
    url = f"http://{host}:{port}"
    print(ui.green(f"  mored up · {url} · project {current_project_name()}"))
    print(ui.dim(f"  token at $MOR_HOME/daemon_token · GET {url}/health for liveness"))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(ui.dim("\n  mored down."))
    finally:
        httpd.server_close()


# --------------------------------------------------------------------------
class DaemonClient:
    """A thin client for the daemon — how the CLI (and a phone) talk to the realm."""

    def __init__(self, base_url: str, token: str, timeout: float = 300):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _req(self, method: str, path: str, body=None, auth: bool = True):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.base_url + path, data=data,
                                     headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    def health(self) -> dict:
        return self._req("GET", "/health", auth=False)

    def submit(self, kind: str, brief: str) -> dict:
        return self._req("POST", "/orders", {"kind": kind, "brief": brief})

    def orders(self) -> list:
        return self._req("GET", "/orders").get("orders", [])

    def get(self, oid: str) -> dict:
        return self._req("GET", f"/orders/{oid}")
