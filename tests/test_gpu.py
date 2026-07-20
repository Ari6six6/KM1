"""Reaching the box — the failure classification that decides whether `gpu ssh`
waits or gives up. A freshly-rented box resets the first handshakes while it
boots; a wrong key never comes good by waiting. The tool must tell them apart."""

from __future__ import annotations

from mor import gpu


def _run(monkeypatch, rc, out, err):
    monkeypatch.setattr(gpu, "run", lambda *a, **k: (rc, out, err))


def test_glm_has_smaller_quants_that_fit_small_boxes():
    from mor.models import GLM, GLM_Q4, smaller_quants
    keys = [s.key for s in smaller_quants(GLM)]
    assert keys == ["glm-q4", "glm-q5"]          # ordered by VRAM floor, ascending
    assert GLM_Q4.min_total_gb < GLM.min_total_gb and GLM_Q4.is_gguf


def test_plan_too_small_box_names_the_quant_that_fits():
    import pytest
    from mor.models import GLM
    # a 4x8GB box (32GB) can't hold GLM FP16 (66GB) but can hold glm-q5 (30GB)
    gpus = [("RTX", 8192)] * 4
    with pytest.raises(gpu.ProvisionError) as ei:
        gpu.plan(gpus, GLM)
    msg = str(ei.value)
    assert "only 32GB" in msg and "4 GPU(s)" in msg and "gpu model glm-q5" in msg


def test_plan_fits_a_smaller_quant_on_the_same_box():
    from mor.models import GLM_Q4
    tp, max_len, util, total = gpu.plan([("RTX", 8192)] * 4, GLM_Q4)   # 32GB total
    assert tp == 4 and total == 32 and max_len > 0


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


def test_launch_prefix_passes_hf_token_when_set(monkeypatch):
    """P2-3 — a gated repo (like the GLM row) serves when HF_TOKEN is set."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert "HF_TOKEN" not in gpu._launch_prefix()
    assert "HF_HUB_ENABLE_HF_TRANSFER=1" in gpu._launch_prefix()
    monkeypatch.setenv("HF_TOKEN", "hf_secret123")
    assert "HF_TOKEN=hf_secret123" in gpu._launch_prefix()
