"""Shared fixtures: every test gets its own MoRE home on disk."""

from __future__ import annotations

import pytest


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("MOR_HOME", str(tmp_path))
    monkeypatch.delenv("MOR_BASE_URL", raising=False)
    from mor.config import Project
    return Project("test").ensure()
