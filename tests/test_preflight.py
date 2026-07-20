"""R2.2 — provisioning preflight: the gates that fail in seconds, not at minute 30.

All offline: the HF API, df, the compute-capability, and the completion are stubbed,
exactly as the existing ssh tests stub ssh."""

from __future__ import annotations

from mor import preflight
from mor.models import GLM, HERMES


# -- P0-1 resolution --------------------------------------------------------
def test_model_preflight_fails_fast_on_a_missing_repo():
    ok, msg, _ = preflight.model_preflight(GLM, fetcher=lambda url: (404, None))
    assert not ok and "does not resolve" in msg


def test_model_preflight_flags_a_gated_repo():
    ok, msg, _ = preflight.model_preflight(HERMES, fetcher=lambda url: (401, None))
    assert not ok and "HF_TOKEN" in msg


def test_model_preflight_catches_a_wrong_gguf_filename_and_suggests():
    def fetch(url):
        if url.endswith("/tree/main"):
            return 200, [{"path": "GLM-Actually-Named-Q8.gguf"}, {"path": "README.md"}]
        return 200, {"id": GLM.repo}
    ok, msg, suggestions = preflight.model_preflight(GLM, fetcher=fetch)
    assert not ok and "is not in repo" in msg
    assert "GLM-Actually-Named-Q8.gguf" in suggestions


def test_model_preflight_passes_when_the_file_is_present():
    def fetch(url):
        if url.endswith("/tree/main"):
            return 200, [{"path": GLM.gguf_file}]
        return 200, {"id": GLM.repo}
    ok, _, _ = preflight.model_preflight(GLM, fetcher=fetch)
    assert ok


def test_model_preflight_validates_the_quant_tag_and_lists_what_is_there():
    # a gguf_quant row (glm-q4) whose quant isn't in the repo fails fast, naming
    # the quants that ARE — not a burned hour on a bad row.
    from mor.models import GLM_Q4

    def fetch(url):
        if url.endswith("/tree/main"):
            return 200, [{"path": "GLM-4.7-Flash-...-Q5_K_M.gguf"},
                         {"path": "GLM-4.7-Flash-...-Q8_0.gguf"}]
        return 200, {"id": GLM_Q4.repo}

    ok, msg, avail = preflight.model_preflight(GLM_Q4, fetcher=fetch)
    assert not ok and "Q4_K_M" in msg
    assert any("Q5_K_M" in f for f in avail)


def test_model_preflight_passes_when_the_quant_is_present():
    from mor.models import GLM_Q4

    def fetch(url):
        if url.endswith("/tree/main"):
            return 200, [{"path": "GLM-4.7-Flash-Balanced-Q4_K_M.gguf"}]
        return 200, {"id": GLM_Q4.repo}

    ok, _, _ = preflight.model_preflight(GLM_Q4, fetcher=fetch)
    assert ok


def test_model_preflight_is_inconclusive_when_hf_is_unreachable():
    ok, msg, _ = preflight.model_preflight(GLM, fetcher=lambda url: (0, None))
    assert ok and "proceeding" in msg


# -- P0-2 disk --------------------------------------------------------------
def test_disk_preflight_refuses_a_too_small_box_with_numbers():
    ok, msg, _ = preflight.disk_preflight(GLM, 40 * 10**9)   # 40GB box, GLM needs ~68
    assert not ok and "40GB" in msg and "resize" in msg


def test_disk_preflight_passes_a_big_enough_box():
    ok, _, _ = preflight.disk_preflight(GLM, 120 * 10**9)
    assert ok


# -- P1-2 capability --------------------------------------------------------
def test_capability_gate_vetoes_fp8_below_8_9():
    ok, msg, _ = preflight.capability_preflight(HERMES, 7.5)   # FP8 on a T4
    assert not ok and "GGUF" in msg


def test_capability_gate_allows_fp8_on_ada_and_gguf_anywhere():
    assert preflight.capability_preflight(HERMES, 8.9)[0]
    assert preflight.capability_preflight(GLM, 7.5)[0]          # GGUF is fine on a T4


# -- P1-1 the canary --------------------------------------------------------
def test_canary_passes_only_on_a_parseable_tool_call():
    good = lambda port, body: (200, {"choices": [{"message": {"tool_calls": [{"id": "1"}]}}]})
    assert preflight.canary(8080, "glm", poster=good)[0]


def test_canary_fails_when_models_list_but_tool_calls_do_not():
    no_tools = lambda port, body: (200, {"choices": [{"message": {"content": "4"}}]})
    ok, msg, _ = preflight.canary(8080, "glm", poster=no_tools)
    assert not ok and "tool-call-parser" in msg


def test_canary_fails_when_the_endpoint_errors():
    ok, msg, _ = preflight.canary(8080, "glm", poster=lambda port, body: (500, None))
    assert not ok and "did not answer" in msg
