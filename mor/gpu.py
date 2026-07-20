"""Provision a model server on the box behind one SSH string — ported from the
Hermes harness and rewired so `gpu ssh <ssh…>` does the whole thing:

  parse the ssh args  →  detect the GPUs  →  pick a VRAM/context tier  →  install
  vLLM (FP8) or build llama.cpp (GGUF)  →  launch the server  →  (tunnel)  →  poll
  until the weights are loaded and the OpenAI endpoint answers.

Stdlib only: commands run over the `ssh` binary (subprocess), readiness is polled
over `urllib`. The server writes ~/vllm.pid and ~/vllm.log so status/teardown stay
runtime-agnostic, exactly as in Hermes.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request

from mor import ui
from mor.models import ModelSpec

VENV_DIR = "~/.mor-venv"
VLLM_BIN = f"{VENV_DIR}/bin/vllm"
LLAMA_DIR = "~/.mor-llama"
LLAMA_BIN = f"{LLAMA_DIR}/llama-server"
LLAMA_REPO = "https://github.com/ggml-org/llama.cpp"


class ProvisionError(Exception):
    pass


# ---- SSH plumbing: reuse the operator's own ssh args ----------------------
def conn_args(ssh_args: list) -> list:
    """The connection part of a pasted ssh command: drop `-N` and the `-L`
    forward (those belong to the tunnel), keep host/port/user/-i/etc."""
    out, i = [], 0
    while i < len(ssh_args):
        a = ssh_args[i]
        if a == "-N":
            i += 1
            continue
        if a == "-L":
            i += 2
            continue
        if a.startswith("-L") and len(a) > 2:
            i += 1
            continue
        out.append(a)
        i += 1
    return out


def replace_forward(ssh_args: list, new_remote_port: int) -> list:
    """The same ssh args with the `-L` forward's box-side port swapped — when
    the launch slides the server to a free port, the tunnel must follow it."""
    out = list(ssh_args)
    for i, a in enumerate(out):
        if a == "-L" and i + 1 < len(out):
            bits = out[i + 1].split(":")
            if len(bits) in (2, 3):
                bits[-1] = str(new_remote_port)
                out[i + 1] = ":".join(bits)
            return out
        if a.startswith("-L") and len(a) > 2:
            bits = a[2:].split(":")
            if len(bits) in (2, 3):
                bits[-1] = str(new_remote_port)
                out[i] = "-L" + ":".join(bits)
            return out
    return out


def parse_forward(ssh_args: list):
    """(local_port, remote_host, remote_port) from a `-L lp:host:rp` forward.

    Returns None for anything malformed — a pasted ssh line must never take
    the shell down with it."""
    val = ""
    for i, a in enumerate(ssh_args):
        if a == "-L" and i + 1 < len(ssh_args):
            val = ssh_args[i + 1]
            break
        if a.startswith("-L") and len(a) > 2:
            val = a[2:]
            break
    if not val:
        return None
    bits = val.split(":")
    try:
        if len(bits) == 3:
            lp, host, rp = int(bits[0]), bits[1], int(bits[2])
        elif len(bits) == 2:  # lp:rp -> localhost
            lp, host, rp = int(bits[0]), "127.0.0.1", int(bits[1])
        else:
            return None
    except ValueError:
        return None
    if not host or not (1 <= lp <= 65535) or not (1 <= rp <= 65535):
        return None
    return lp, host, rp


_SSH_OPTS = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
             "-o", "ConnectTimeout=15"]


def run(cargs: list, command: str, timeout: int = 120):
    """Run a remote command; returns (rc, stdout, stderr)."""
    try:
        p = subprocess.run(["ssh", *_SSH_OPTS, *cargs, command],
                           capture_output=True, text=True, errors="replace",
                           timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    except FileNotFoundError:
        return 127, "", "ssh binary not found"


# ---- the install/launch commands (ported from Hermes provision.py) --------
_APT_WAIT = (
    "apt_wait() { for _i in $(seq 1 60); do apt-get \"$@\" 2>/tmp/.mor_apt && return 0; "
    "grep -q 'Could not get lock\\|is held by process' /tmp/.mor_apt || "
    "{ cat /tmp/.mor_apt >&2; return 1; }; sleep 5; done; cat /tmp/.mor_apt >&2; return 1; }; "
)
_NET_WAIT = (
    "net_wait() { for _i in $(seq 1 24); do \"$@\" 2>/tmp/.mor_net && return 0; "
    "grep -qiE 'could not resolve host|temporary failure in name resolution|network is unreachable|"
    "could not connect to|connection timed out' /tmp/.mor_net || "
    "{ cat /tmp/.mor_net >&2; return 1; }; sleep 5; done; cat /tmp/.mor_net >&2; return 1; }; "
)
# `ssh host "command"` runs non-interactively, so .bashrc's CUDA exports (PATH,
# LD_LIBRARY_PATH — where the box's real, versioned libcublas/libcudart live)
# never apply: cmake still finds nvcc, but the linker falls back to broken stubs
# and dies with "undefined reference to ...@libcublas.so.NN". Find the real
# toolkit dirs ourselves and export them before the build, whatever the shell
# init did or didn't do.
_CUDA_ENV = (
    "for _d in /usr/local/cuda*/lib64 /usr/local/cuda*/targets/*/lib; do "
    "[ -d \"$_d\" ] && export LD_LIBRARY_PATH=\"$_d:$LD_LIBRARY_PATH\" "
    "LIBRARY_PATH=\"$_d:$LIBRARY_PATH\"; done; "
    "for _b in /usr/local/cuda*/bin; do [ -d \"$_b\" ] && export PATH=\"$_b:$PATH\"; done; "
)


def detect_gpus(cargs: list):
    rc, out, err = run(cargs, "nvidia-smi --query-gpu=name,memory.total "
                              "--format=csv,noheader,nounits", timeout=30)
    if rc != 0:
        raise ProvisionError(f"nvidia-smi failed: {(err or out).strip()[:200]}")
    gpus = []
    for line in out.strip().splitlines():
        try:
            name, mem = line.rsplit(",", 1)
            gpus.append((name.strip(), int(float(mem.strip()))))
        except ValueError:
            continue
    return gpus


def plan(gpus: list, spec: ModelSpec):
    """-> (tensor_parallel, max_model_len, gpu_mem_util, total_gb). Raises if the
    box is too small for the chosen model."""
    if not gpus:
        raise ProvisionError("no GPUs detected on the box (nvidia-smi empty)")
    total_gb = sum(mb for _, mb in gpus) // 1024
    if total_gb < spec.min_total_gb:
        from mor.models import smaller_quants
        fits = [s for s in smaller_quants(spec) if s.min_total_gb <= total_gb]
        if fits:
            best = fits[-1]   # the highest-quality quant that still fits this box
            hint = (f"This box holds {best.label.split(' · ')[-1]}: "
                    f"`gpu model {best.key}` then re-serve (needs ~{best.min_total_gb}GB).")
        else:
            smaller = smaller_quants(spec)
            hint = (f"Even the smallest {spec.served_name} row (`gpu model "
                    f"{smaller[0].key}`, ~{smaller[0].min_total_gb}GB) won't fit — rent a "
                    "bigger box." if smaller else "Pick a smaller model or a bigger box.")
        raise ProvisionError(
            f"only {total_gb}GB total VRAM across {len(gpus)} GPU(s) — {spec.label} "
            f"needs ~{spec.min_total_gb}GB+. {hint}")
    max_len = spec.context_beyond
    for threshold, length in spec.context_tiers:
        if total_gb < threshold:
            max_len = length
            break
    util = 0.95 if total_gb < 72 else 0.92
    return len(gpus), max_len, util, total_gb


def _vllm_cmd(spec: ModelSpec, tp: int, max_len: int, util: float, port: int) -> str:
    parts = [VLLM_BIN, "serve", spec.repo,
             f"--served-model-name {spec.served_name}",
             f"--quantization {spec.quantization}",
             f"--tensor-parallel-size {tp}",
             f"--max-model-len {max_len}",
             f"--gpu-memory-utilization {util}",
             f"--enable-auto-tool-choice --tool-call-parser {spec.tool_call_parser}",
             "--host 127.0.0.1", f"--port {port}"]
    if spec.tokenizer:
        parts.append(f"--tokenizer {spec.tokenizer}")
    return " ".join(parts)


def _llama_cmd(spec: ModelSpec, max_len: int, port: int) -> str:
    if spec.gguf_file:
        weights = [f"--hf-repo {spec.repo}", f"--hf-file {spec.gguf_file}"]
    else:
        weights = [f"-hf {spec.repo}:{spec.gguf_quant}"]
    return " ".join([LLAMA_BIN, *weights, f"--alias {spec.served_name}",
                     "--host 127.0.0.1", f"--port {port}",
                     f"--ctx-size {max_len}", "--n-gpu-layers 999", "--jinja"])


def _install_vllm(cargs: list, log) -> None:
    log(ui.dim("  installing vLLM (first time can take several minutes)…"))
    cmd = (_APT_WAIT +
           f"test -x {VLLM_BIN} && exit 0; "
           f"python3 -m venv --system-site-packages {VENV_DIR} 2>/dev/null || "
           f"{{ apt_wait update -qq && apt_wait install -y -qq python3-venv && "
           f"python3 -m venv --system-site-packages {VENV_DIR}; }} && "
           f"{VENV_DIR}/bin/pip install -q -U pip vllm hf_transfer")
    rc, _, err = run(cargs, cmd, timeout=1800)
    if rc != 0:
        raise ProvisionError(f"vLLM install failed: {err.strip()[-500:]}")


def _install_llama(cargs: list, log) -> None:
    log(ui.dim("  building llama.cpp with CUDA (first time can take several minutes)…"))
    cmd = (_APT_WAIT + _NET_WAIT +
           f"test -x {LLAMA_BIN} && exit 0; mkdir -p {LLAMA_DIR} && "
           "apt_wait update -qq && apt_wait install -y -qq git cmake build-essential "
           "libcurl4-openssl-dev && "
           f"rm -rf {LLAMA_DIR}/src && "
           f"net_wait git clone --depth 1 {LLAMA_REPO} {LLAMA_DIR}/src && "
           "CUDA_ARCH=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader "
           "2>/dev/null | head -1 | tr -d '. '); " + _CUDA_ENV +
           f"cmake -S {LLAMA_DIR}/src -B {LLAMA_DIR}/src/build -DGGML_CUDA=ON "
           "-DLLAMA_CURL=ON -DCMAKE_BUILD_TYPE=Release "
           "${CUDA_ARCH:+-DCMAKE_CUDA_ARCHITECTURES=$CUDA_ARCH} && "
           f"cmake --build {LLAMA_DIR}/src/build --config Release -j --target llama-server && "
           f"cp {LLAMA_DIR}/src/build/bin/llama-server {LLAMA_BIN}")
    rc, _, err = run(cargs, cmd, timeout=3600)
    if rc != 0:
        raise ProvisionError(f"llama.cpp build failed: {err.strip()[-500:]}")


def _launch_prefix() -> str:
    """The env that rides the launch command. HF_TOKEN (P2-3) is passed through when
    set, so a gated repo serves instead of failing with an opaque download error."""
    import os
    import shlex
    parts = ["HF_HUB_ENABLE_HF_TRANSFER=1"]
    tok = os.environ.get("HF_TOKEN")
    if tok:
        parts.insert(0, f"HF_TOKEN={shlex.quote(tok)}")
    return " ".join(parts) + " "


def server_running(cargs: list) -> bool:
    # pid-alive AND cmdline-match (P2-2): a reused pid after a box reboot (a stray
    # `sleep` inheriting the old pid) must not read as "already serving".
    rc, out, _ = run(cargs, "P=$(cat ~/vllm.pid 2>/dev/null) && kill -0 $P 2>/dev/null && "
                            "tr '\\0' ' ' < /proc/$P/cmdline 2>/dev/null | "
                            "grep -qE 'vllm|llama-server' && echo RUNNING")
    return "RUNNING" in out


def _register_cuda_libs(cargs: list) -> None:
    """Teach the box's dynamic linker where the CUDA toolkit lives, once and for
    all. Exporting LD_LIBRARY_PATH only helps the one shell that launches — but a
    crash-on-exec ("libcudart.so.NN: cannot open shared object file") strikes any
    session that forgets to. Writing the toolkit dirs into ld.so.conf and running
    ldconfig fixes it system-wide, so the server starts no matter who launches it.
    Idempotent and cheap; best-effort (needs root, which a rented box gives)."""
    run(cargs, "ls -d /usr/local/cuda*/lib64 /usr/local/cuda*/targets/*/lib "
               "2>/dev/null > /etc/ld.so.conf.d/cuda-mor.conf && ldconfig", timeout=30)


def _clear_stale_and_check_port(cargs: list, port: int) -> str:
    """Clear orphaned llama-servers and report if `port` is still held by something
    else. We only get here with no tracked-alive server (server_running returned
    False), so a leftover llama-server is a lost orphan from an earlier session
    holding the port — kill it. If the port is *still* taken afterwards, it's
    another service on the box (vast.ai often squats on 8080): return what holds
    it so the caller can fail with a clear 'use a different port' message rather
    than a silent, forever-failing bind. Returns '' when the port is free."""
    # kill both llama-server and vllm-serve orphans (P2-2) — either can squat the port
    run(cargs, "pkill -9 -f llama-server 2>/dev/null; pkill -9 -f 'vllm serve' "
               "2>/dev/null; sleep 1", timeout=20)
    rc, out, _ = run(cargs, f"ss -tln 2>/dev/null | grep ':{port} ' || true", timeout=20)
    return out.strip()


def launch(cargs: list, spec: ModelSpec, tp, max_len, util, port: int, log,
           auto_port: bool = False) -> int:
    """Install the runtime and launch the server. Returns the box-side port the
    server actually bound — with `auto_port`, a held port slides to a free one
    (and the caller slides the tunnel forward with it) instead of failing."""
    if server_running(cargs):
        log(ui.yellow("  a model server is already running on the box "
                      "(gpu down to relaunch)."))
        return port
    if spec.server == "llama_cpp":
        _install_llama(cargs, log)
        _register_cuda_libs(cargs)  # so llama-server finds libcudart/libcublas on exec
        held = _clear_stale_and_check_port(cargs, port)
        if held and auto_port:
            # The magic: don't make the Master re-type the forward — slide the
            # box-side port ourselves and report where the server landed.
            alt = port + 10000 if port < 55535 else 8000
            if _clear_stale_and_check_port(cargs, alt):
                raise ProvisionError(
                    f"ports {port} and {alt} are both held on the box — pick a "
                    "free remote port for your -L forward by hand.")
            log(ui.yellow(f"  port {port} is held on the box — sliding the "
                          f"server to {alt} (your local side stays as is)."))
            port = alt
        elif held:
            alt = port + 10000 if port < 55535 else 8000
            raise ProvisionError(
                f"port {port} on the box is already held by another service — the "
                f"server can never bind it. Re-run with a different remote port in "
                f"your -L forward, e.g. -L {port}:localhost:{alt}  (your local "
                f"{port} still works; only the box-side port moves).")
        cmd = _llama_cmd(spec, max_len, port)
    else:
        _install_vllm(cargs, log)
        cmd = _vllm_cmd(spec, tp, max_len, util, port)
    log(ui.dim(f"  launching: {cmd[:120]}…"))
    # Belt-and-suspenders with the ldconfig registration above: the build's CUDA
    # env (`_CUDA_ENV`) lived only in that ssh session — this is a separate one.
    # llama-server is dynamically linked against the toolkit's libcublas/libcudart;
    # if the linker can't find them it dies on exec, silently, before it opens a
    # socket or a download — which looks exactly like a hung download bar.
    env_setup = _CUDA_ENV if spec.server == "llama_cpp" else ""
    rc, _, err = run(cargs, env_setup + _launch_prefix() + "nohup " + cmd +
                     " > ~/vllm.log 2>&1 & echo $! > ~/vllm.pid", timeout=60)
    if rc != 0:
        raise ProvisionError(f"launch failed: {err.strip()[-400:]}")
    return port


def stop(cargs: list) -> None:
    run(cargs, "kill $(cat ~/vllm.pid) 2>/dev/null; rm -f ~/vllm.pid", timeout=30)


# ---- readiness: poll until the weights load and the endpoint answers ------
def _cache_bytes(cargs: list):
    rc, out, _ = run(cargs, "du -sb ~/.cache/llama.cpp ~/.cache/huggingface 2>/dev/null "
                            "| awk '{s+=$1} END{print s+0}'", timeout=20)
    try:
        return int(out.strip()) if rc == 0 else None
    except ValueError:
        return None


def _weights_total(spec: ModelSpec):
    import re
    m = re.search(r"(\d+(?:\.\d+)?)\s*GB", spec.weights_note or "")
    return int(float(m.group(1)) * 1_000_000_000) if m else None


def _fmt(n: int) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def endpoint_up(local_port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{local_port}/v1/models",
                                    timeout=5) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def wait_ready(cargs: list, local_port: int, spec: ModelSpec, log,
               deadline_s: int = 2400) -> bool:
    """Poll until the endpoint answers, showing a download bar while weights land.

    A crash on exec (e.g. the runtime linker can't find a shared lib) kills the
    process in under a second but looks, from here, identical to a slow
    download — the bar just sits at 0%. Rather than silently waiting out the
    full deadline (burning rental time on a dead box), check the process is
    still alive once warm-up has had a moment, and bail out with the crash
    reason the instant it isn't."""
    import sys
    total = _weights_total(spec)
    start = time.time()
    baseline = None
    tty = sys.stdout.isatty()
    log(ui.dim(f"  waiting for the oracle to wake — {spec.weights_note}"))
    while time.time() - start < deadline_s:
        if endpoint_up(local_port):
            if tty:
                sys.stdout.write("\r" + " " * 72 + "\r")
                sys.stdout.flush()
            return True
        if time.time() - start > 8 and not server_running(cargs):
            if tty:
                sys.stdout.write("\r" + " " * 72 + "\r")
                sys.stdout.flush()
            rc, out, _ = run(cargs, "tail -n 15 ~/vllm.log 2>/dev/null", timeout=20)
            log(ui.red("  ✗ the server process died before it came up."))
            for ln in (out.strip().splitlines() if rc == 0 and out.strip() else []):
                log(ui.dim("  | " + ln[:200]))
            return False
        cur = _cache_bytes(cargs)
        if cur is not None and baseline is None:
            baseline = cur
        if cur is not None and total and tty:
            got = max(0, cur - (baseline or 0))
            frac = min(0.99, got / total)
            sys.stdout.write("\r  " + ui.cyan(ui.bar(frac, label=f"weights {_fmt(got)}/{_fmt(total)}")))
            sys.stdout.flush()
        else:
            # No total or piped: stream a few fresh log lines so warm-up/errors show.
            rc, out, _ = run(cargs, "tail -n 3 ~/vllm.log 2>/dev/null", timeout=20)
            if rc == 0 and out.strip():
                for ln in out.strip().splitlines()[-3:]:
                    log(ui.dim("  | " + ln[:150]))
        time.sleep(4)
    if tty:
        sys.stdout.write("\r" + " " * 72 + "\r")
        sys.stdout.flush()
    return False


def check_connection(cargs: list):
    """Try to reach the box. Returns (ok, reason, transient). `transient` marks a
    failure worth *waiting on*: a freshly-rented box resets or refuses the first
    handshakes for the first half-minute while sshd comes up, then answers — so
    the caller retries those instead of giving up on the first reset. Auth
    failures and a missing ssh binary are permanent — waiting never fixes them."""
    rc, out, err = run(cargs, "echo MOR_OK", timeout=30)
    if rc == 0 and "MOR_OK" in out:
        return True, "ok", False
    low = ((err or "") + (out or "")).lower()
    if rc == 127:
        return False, "ssh binary not found on this machine", False
    if "permission denied" in low or "no such identity" in low:
        return False, ("auth denied — the box isn't accepting your SSH key "
                       "(add it / ssh-agent)"), False
    # The classic freshly-booted-box signature: TCP connected, but sshd reset the
    # handshake before its banner. Almost always still coming up, or fail2ban
    # briefly rate-limiting new connections — worth a wait, not a wrong key.
    if ("kex_exchange_identification" in low or "reset by peer" in low
            or "connection reset" in low):
        return False, ("the box reset the SSH handshake — almost always still "
                       "booting, or briefly rate-limiting new connections"), True
    if "connection refused" in low:
        return False, ("connection refused — sshd isn't up yet; the box may still "
                       "be booting"), True
    if rc == 124:
        return False, "no answer in 30s — wrong host/port, or the box is still booting", True
    return False, f"ssh failed: {(err or out).strip()[:160] or f'exit {rc}'}", False
