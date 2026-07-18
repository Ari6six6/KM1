"""Shared ground for the suite: every test gets its own realm-home on disk."""

from __future__ import annotations

import pytest


@pytest.fixture()
def space(tmp_path, monkeypatch):
    monkeypatch.setenv("MOR_HOME", str(tmp_path))
    from mor.config import Space
    return Space("test").ensure()
