"""The `mor gpu` glue: state, model selection, and safe degradation.

The SSH/provisioning primitives are covered by test_gpu.py; here we pin the
operator-facing command and its integration with the harness config.
"""

from __future__ import annotations

from mor import gpucmd
from mor.config import endpoint


def test_model_selection_updates_state(project):
    gpucmd.handle("model qwen")
    assert gpucmd._load()["model_id"] == "qwen"


def test_unknown_model_is_rejected(project, capsys):
    gpucmd.handle("model no-such-model")
    assert "unknown model" in capsys.readouterr().out


def test_status_when_nothing_attached(project, capsys):
    gpucmd.handle("status")
    assert "no GPU attached" in capsys.readouterr().out


def test_serve_points_the_harness_config(project):
    gpucmd.handle("serve http://localhost:8080/v1 my-model")
    cfg = endpoint()
    assert cfg["base_url"] == "http://localhost:8080/v1"
    assert cfg["model"] == "my-model"


def test_off_clears_the_endpoint(project):
    gpucmd.handle("serve http://box:8080/v1 m")
    gpucmd.handle("off")
    assert endpoint()["base_url"] == ""


def test_ssh_with_bad_forward_shows_usage(project, capsys):
    gpucmd.handle("ssh root@1.2.3.4")   # no -L forward
    assert "usage" in capsys.readouterr().out.lower()


def test_ssh_forgives_a_pasted_leading_ssh_word(project, monkeypatch, capsys):
    # `gpu ssh ssh -p … host -L …` (the whole ssh line pasted) must not treat
    # the literal "ssh" as the hostname.
    seen = {}
    from mor import gpu
    monkeypatch.setattr(gpu, "run", lambda cargs, *a, **k: seen.setdefault("cargs", cargs)
                        or (255, "", "Permission denied (publickey)."))
    gpucmd.handle("ssh ssh -p 11849 root@87.116.91.146 -L 8080:localhost:8080")
    assert "ssh" not in seen["cargs"]          # the redundant word was dropped
    assert "root@87.116.91.146" in seen["cargs"]


def test_ssh_degrades_when_the_box_is_unreachable(project, monkeypatch, capsys):
    # force the connection probe to report a permanent failure
    from mor import gpu
    monkeypatch.setattr(gpu, "run", lambda *a, **k: (127, "", "ssh binary not found"))
    gpucmd.handle("ssh -p 22 root@1.2.3.4 -L 8080:localhost:8080")
    assert "can't reach the box" in capsys.readouterr().out
