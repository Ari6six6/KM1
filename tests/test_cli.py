"""The CLI surface: config, ping, and the workspace override."""

from __future__ import annotations

import mor.llm as llm
from mor import cli
from mor.config import endpoint
from mor.llm import ChatResult


def test_config_sets_endpoint_and_shell(project, capsys):
    cli.main(["config", "--base-url", "http://box:8080/v1", "--model", "glm",
              "--shell", "container"])
    cfg = endpoint()
    assert cfg["base_url"] == "http://box:8080/v1"
    assert cfg["model"] == "glm"
    assert cfg["shell"] == "container"


def test_config_rejects_bad_shell_mode(project):
    assert cli.main(["config", "--shell", "banana"]) == 2


def test_ping_with_no_endpoint_reports_and_exits_nonzero(project, capsys):
    assert cli.main(["ping"]) == 1
    assert "no endpoint" in capsys.readouterr().out


def test_ping_hits_the_endpoint(project, monkeypatch, capsys):
    cli.main(["config", "--base-url", "http://box:8080/v1", "--model", "glm"])

    class FakeClient:
        def __init__(self, cfg):
            pass

        def chat(self, messages, tools=None):
            return ChatResult(content="pong")

    monkeypatch.setattr(llm, "OpenAIClient", FakeClient)
    assert cli.main(["ping"]) == 0
    assert "pong" in capsys.readouterr().out


def test_workspace_override_points_the_crew_at_a_real_dir(project, tmp_path, monkeypatch):
    target = tmp_path / "myrepo"
    target.mkdir()
    monkeypatch.delenv("MOR_WORKSPACE", raising=False)
    cli._pop_workspace(["--workspace", str(target), "run", "x"])
    # after _pop_workspace, the override is live for the process
    from mor.config import load_project
    assert load_project().workspace == target.resolve()


def test_version(capsys):
    cli.main(["version"])
    assert "mor" in capsys.readouterr().out
