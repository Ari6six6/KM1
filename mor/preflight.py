"""Provisioning preflight — prove the box can serve before it spends the hour.

The GPU module carries the Master's scar tissue; these are the gates that stop the
three failures that have burned rentals, each converted from a 40-minute discovery
into a three-second answer:

  P0-1  resolution — the model repo AND the exact GGUF file resolve on Hugging Face
        before any install. The catalog is self-declared "aspirational"; this
        discharges it with a real check, not hope.
  P0-2  disk — df vs weights × 1.1 before the download, so a build never dies at
        95% on a box too small.
  P1-1  the canary — one real tool-calling completion through the tunnel before
        "up" may print. Up must mean *can think*, not just *lists models*.
  P1-2  capability — FP8 needs Ada (8.9)/Hopper (9.0); veto it on a T4/A10 before
        the install crashes it.

Every check is a pure function over injected I/O (an HF fetcher, a df number, a
compute-capability, a completion poster), so all of it tests with no box and no
network — exactly as the existing ssh tests stub ssh.
"""

from __future__ import annotations

import json
import re
import urllib.request

# each check returns (ok: bool, message: str, suggestions: list)


# -- P0-1 resolution --------------------------------------------------------
def _hf_fetch(url: str):
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            return getattr(r, "status", 200), json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:  # noqa: F821 (urllib.error via urllib.request)
        return e.code, None
    except Exception:  # noqa: BLE001 — HF unreachable is inconclusive, not fatal
        return 0, None


def model_preflight(spec, fetcher=None) -> tuple:
    fetcher = fetcher or _hf_fetch
    status, _ = fetcher(f"https://huggingface.co/api/models/{spec.repo}")
    if status == 404:
        return False, f"model repo '{spec.repo}' does not resolve on Hugging Face", []
    if status in (401, 403):
        return False, f"'{spec.repo}' is gated — set HF_TOKEN and accept the license first", []
    if status != 200:
        return True, f"could not verify '{spec.repo}' (HF unreachable) — proceeding", []
    if spec.gguf_file:
        tstatus, tree = fetcher(f"https://huggingface.co/api/models/{spec.repo}/tree/main")
        if tstatus == 200 and isinstance(tree, list):
            files = [it.get("path", "") for it in tree if isinstance(it, dict)]
            if spec.gguf_file not in files:
                near = [f for f in files if f.endswith(".gguf")][:5]
                return False, f"file '{spec.gguf_file}' is not in repo '{spec.repo}'", near
    return True, f"'{spec.repo}' resolves", []


# -- P0-2 disk --------------------------------------------------------------
def weights_bytes(spec):
    m = re.search(r"(\d+(?:\.\d+)?)\s*GB", spec.weights_note or "")
    return int(float(m.group(1)) * 1_000_000_000) if m else None


def disk_preflight(spec, avail_bytes) -> tuple:
    need = weights_bytes(spec)
    if need is None or avail_bytes is None:
        return True, "disk need unknown — proceeding", []
    need = int(need * 1.1)
    if avail_bytes < need:
        return (False, f"needs ~{need / 1e9:.0f}GB, box has {avail_bytes / 1e9:.0f}GB — "
                "resize the disk in the console and re-run", [])
    return True, f"disk ok ({avail_bytes / 1e9:.0f}GB free, need ~{need / 1e9:.0f}GB)", []


# -- P1-2 capability --------------------------------------------------------
def capability_preflight(spec, compute_cap) -> tuple:
    if spec.quantization == "fp8" and compute_cap is not None and compute_cap < 8.9:
        return (False, f"FP8 needs compute capability 8.9+ (Ada/Hopper); this GPU is "
                f"{compute_cap} — pick a GGUF row, e.g. `gpu model qwen`", [])
    return True, "capability ok", []


# -- P1-1 the canary --------------------------------------------------------
def _post_completion(local_port: int, body: dict):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{local_port}/v1/chat/completions",
                                 data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return getattr(r, "status", 200), json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:  # noqa: F821
        return e.code, None
    except Exception:  # noqa: BLE001
        return 0, None


def canary(local_port: int, served_name: str, poster=None) -> tuple:
    """Up must mean *can think*: one tool-calling completion that must come back
    with a parseable tool_call. A server can list models while tool-call turns fail
    (bad parser, template mismatch) — this catches exactly that."""
    poster = poster or _post_completion
    body = {"model": served_name,
            "messages": [{"role": "user", "content": "Add 2 and 2 using the add tool."}],
            "tools": [{"type": "function", "function": {
                "name": "add", "description": "add two numbers",
                "parameters": {"type": "object",
                               "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                               "required": ["a", "b"]}}}],
            "tool_choice": "auto", "max_tokens": 128}
    status, data = poster(local_port, body)
    if status != 200 or not isinstance(data, dict):
        return False, f"the endpoint did not answer a completion (status {status})", []
    try:
        if data["choices"][0]["message"].get("tool_calls"):
            return True, "the model answered a tool call — it can think", []
    except (KeyError, IndexError, TypeError):
        pass
    return (False, "the server lists models but tool-calling failed — check the "
            "--tool-call-parser or the chat template", [])


# -- thin live wrappers (the box side; not unit-tested) ---------------------
def remote_free_bytes(cargs):
    from mor.gpu import run
    rc, out, _ = run(cargs, "df -PB1 ~/.cache 2>/dev/null | awk 'NR==2{print $4}' || "
                            "df -PB1 ~ 2>/dev/null | awk 'NR==2{print $4}'", timeout=20)
    try:
        return int(out.strip()) if rc == 0 and out.strip() else None
    except ValueError:
        return None


def detect_compute_cap(cargs):
    from mor.gpu import run
    rc, out, _ = run(cargs, "nvidia-smi --query-gpu=compute_cap --format=csv,noheader "
                            "2>/dev/null | head -1", timeout=20)
    try:
        return float(out.strip()) if rc == 0 and out.strip() else None
    except ValueError:
        return None
