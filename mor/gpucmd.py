"""`mor gpu …` — one command to reach your model on a rented GPU box.

    mor gpu ssh -p 24439 root@1.2.3.4 -L 8080:localhost:8080

does the whole thing: reach the box (retrying while it boots), detect the GPUs,
pick a VRAM/context tier, install vLLM (or build llama.cpp), launch the server,
open the SSH tunnel, and poll until the model answers — then point the harness at
`http://localhost:<port>/v1` by writing it into MoRE's config, so `mor`, `mor
ping`, and every session use it automatically.

The provisioning primitives live in ``mor/gpu.py`` (unchanged, well-tested); this
module is the operator-facing glue and the tunnel/box bookkeeping. The tunnel is a
detached background process tracked by PID, so it outlives the command that
started it — close the shell and the served model stays up; `mor gpu off` drops it.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time

from mor import ui
from mor.config import load_json, mor_home, save_json, set_config


def _state_path():
    return mor_home() / "gpu.json"


def _load() -> dict:
    return load_json(_state_path(), {})


def _save(state: dict) -> None:
    save_json(_state_path(), state)


# -- tunnel (detached, PID-tracked) ----------------------------------------
def _alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _kill_tunnel(state: dict) -> None:
    pid = state.get("tunnel_pid")
    if _alive(pid):
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass
    state["tunnel_pid"] = None


def _open_tunnel(ssh_args: list, out) -> int | None:
    """Launch a detached `ssh -N …` tunnel. Returns its PID, or None on failure."""
    logf = mor_home() / "gpu-tunnel.log"
    logf.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ssh", "-N",
           "-o", "StrictHostKeyChecking=accept-new",
           "-o", "BatchMode=yes",
           "-o", "ServerAliveInterval=30",
           "-o", "ExitOnForwardFailure=yes",
           "-o", "ConnectTimeout=15"] + ssh_args
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=logf.open("w"), start_new_session=True)
    except FileNotFoundError:
        out(ui.red("  ssh not found on PATH."))
        return None
    # give it a moment to fail fast (bad forward, auth) before we trust it
    for _ in range(25):
        if proc.poll() is not None:
            tail = ""
            try:
                tail = logf.read_text().strip().splitlines()[-1][:200]
            except (OSError, IndexError):
                pass
            out(ui.red("  ⛓  tunnel failed to come up.") + (ui.dim("  " + tail) if tail else ""))
            return None
        time.sleep(0.1)
    return proc.pid


def _spinner(stop: "threading.Event", label: str) -> None:
    if not sys.stdout.isatty():
        return
    frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    i, t0 = 0, time.time()
    while not stop.is_set():
        sys.stdout.write(f"\r  {ui.cyan(frames[i % len(frames)])} {label}… {time.time()-t0:4.1f}s")
        sys.stdout.flush()
        i += 1
        time.sleep(0.1)
    if sys.stdout.isatty():
        sys.stdout.write("\r" + " " * 60 + "\r")
        sys.stdout.flush()


# -- the command ------------------------------------------------------------
def handle(rest: str, out=print) -> None:
    from mor import gpu as gpumod
    from mor.models import CATALOG, DEFAULT_KEY, get_spec

    parts = rest.split()
    sub = parts[0].lower() if parts else "status"
    state = _load()

    if sub == "ssh":
        ssh_args = parts[1:]
        # forgive a pasted full ssh line: `gpu ssh ssh -p … host -L …` — the
        # leading `ssh` is redundant (gpu ssh already means "over ssh") and would
        # otherwise be read as the hostname. Drop it.
        while ssh_args and ssh_args[0] == "ssh":
            ssh_args = ssh_args[1:]
        fwd = gpumod.parse_forward(ssh_args)
        if not fwd:
            out(ui.yellow("usage: mor gpu ssh <ssh args including -L localport:host:remoteport>"))
            out(ui.dim("  e.g. mor gpu ssh -p 24439 root@1.2.3.4 -L 8080:localhost:8080"))
            return
        local_port, _rhost, rport = fwd
        cargs = gpumod.conn_args(ssh_args)
        spec = get_spec(state.get("model_id"))

        # 1. reach the box, waiting out the transient resets of a booting box
        out(ui.dim("  reaching the box…"))
        ok, why, transient = gpumod.check_connection(cargs)
        tries = 0
        while not ok and transient and tries < 4:
            tries += 1
            out(ui.dim(f"  {why} — still coming up; retry {tries}/4 in 12s (Ctrl-C to stop)"))
            time.sleep(12)
            ok, why, transient = gpumod.check_connection(cargs)
        if not ok:
            out(ui.red("  can't reach the box: ") + ui.dim(why))
            return

        # 2. detect GPUs + plan the tier
        try:
            gpus = gpumod.detect_gpus(cargs)
            tp, max_len, util, total_gb = gpumod.plan(gpus, spec)
        except gpumod.ProvisionError as e:
            out(ui.red("  " + str(e)))
            return
        out(ui.green(f"  {len(gpus)}× GPU · {total_gb}GB VRAM")
            + ui.dim(f"  ({', '.join(n for n, _ in gpus)})"))
        out(ui.dim(f"  serving {spec.label} · context {max_len} · port {rport}"))

        # 3. install runtime + launch server (slides off a squatted box port)
        try:
            new_rport = gpumod.launch(cargs, spec, tp, max_len, util, rport, out,
                                      auto_port=True)
        except gpumod.ProvisionError as e:
            out(ui.red("  " + str(e)))
            return
        if new_rport != rport:
            ssh_args = gpumod.replace_forward(ssh_args, new_rport)
            out(ui.dim(f"  tunnel follows the slide → -L {local_port}:localhost:{new_rport}"))

        # 4. open the tunnel (detached, survives this command)
        _kill_tunnel(state)
        pid = _open_tunnel(ssh_args, out)
        if pid is None:
            return

        # 5. wait for the weights to load and the endpoint to answer
        ready = gpumod.wait_ready(cargs, local_port, spec, out)
        base_url = f"http://localhost:{local_port}/v1"
        state.update(base_url=base_url, served=True, model=spec.served_name,
                     model_id=spec.key, ssh_conn=cargs, local_port=local_port,
                     tunnel_pid=pid)
        _save(state)
        # point the whole harness at it
        set_config(base_url=base_url, model=spec.served_name)
        if ready:
            out(ui.green(f"  ⛓  the model is up at {base_url}")
                + ui.dim(f"  (model: {spec.served_name}). Try `mor ping`, then `mor`."))
        else:
            out(ui.yellow("  tunnel up and the server is launching, but it didn't "
                          "answer in time — weights may still be loading."))
            out(ui.dim("     check with `mor gpu status` or `mor ping` in a few minutes."))

    elif sub in ("model", "models"):
        if len(parts) < 2:
            cur = state.get("model_id", DEFAULT_KEY)
            for k, s in CATALOG.items():
                mark = ui.green("→") if k == cur else " "
                out(f"  {mark} {ui.cyan(k):16} {ui.dim(s.label)}")
            out(ui.dim("  pick:  mor gpu model <key>   (served on the next `mor gpu ssh …`)"))
            return
        key = parts[1]
        if key not in CATALOG:
            out(ui.yellow(f"unknown model '{key}' — one of: {', '.join(CATALOG)}"))
            return
        spec = get_spec(key)
        state.update(model_id=key, model=spec.served_name)
        _save(state)
        if state.get("served"):
            set_config(model=spec.served_name)
        out(ui.green(f"  model → {spec.label}"))
        out(ui.dim(f"  needs ~{spec.min_total_gb}GB VRAM · {spec.weights_note}"))

    elif sub in ("test", "ping"):
        from mor.cli import _cmd_ping
        _cmd_ping()

    elif sub == "serve":  # point at an already-reachable url by hand
        if len(parts) < 2:
            out(ui.yellow("usage: mor gpu serve <base_url> [model]"))
            return
        base_url = parts[1].rstrip("/")
        model = parts[2] if len(parts) > 2 else state.get("model", "local")
        state.update(base_url=base_url, served=True, model=model)
        _save(state)
        set_config(base_url=base_url, model=model)
        out(ui.green(f"  pointed at {base_url} (model: {model})."))

    elif sub == "down":  # stop the server on the box AND drop the tunnel
        cargs = state.get("ssh_conn")
        if cargs:
            out(ui.dim("  stopping the model server on the box…"))
            gpumod.stop(cargs)
        _kill_tunnel(state)
        state["served"] = False
        _save(state)
        set_config(base_url="")
        out(ui.dim("  server stopped, tunnel down — the harness falls back offline."))

    elif sub in ("off", "detach"):  # drop the tunnel; leave the server running
        _kill_tunnel(state)
        state["served"] = False
        _save(state)
        set_config(base_url="")
        out(ui.dim("  tunnel down — offline. (server left running; `mor gpu down` stops it.)"))

    else:  # status
        if state.get("served"):
            live = "tunnel live" if _alive(state.get("tunnel_pid")) else "no tunnel process"
            out(ui.dim(f"  served: {state.get('base_url')} (model: {state.get('model')}) — {live}"))
        else:
            out(ui.dim("  no GPU attached. `mor gpu ssh <ssh… -L port:host:port>` to serve a model."))
