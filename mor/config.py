"""Paths, project state, the model endpoint, and the web allowlist.

MoRE keeps its home under ``$MOR_HOME`` (default ``~/.mor``). A *project* is one
working world on disk: its shared workspace, saved transcripts, persistent notes,
and its own web allowlist. Everything here is plain files and JSON — nothing to
install, easy to inspect, easy to delete.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse


def mor_home() -> Path:
    return Path(os.environ.get("MOR_HOME", str(Path.home() / ".mor")))


def config_path() -> Path:
    return mor_home() / "config.json"


def projects_root() -> Path:
    return mor_home() / "projects"


# --------------------------------------------------------------------------
# small JSON helpers (atomic write, so a crash never leaves a torn file)
# --------------------------------------------------------------------------
def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# the model endpoint
# --------------------------------------------------------------------------
def endpoint() -> dict:
    """How to reach the model. Env wins over the config file, so you can point at
    a different server for one run without editing anything:

        MOR_BASE_URL   e.g. http://localhost:8080/v1  (vLLM, llama.cpp, Ollama, …)
        MOR_MODEL      the model name the server expects
        MOR_API_KEY    if the server wants one (default "-")

    With no base URL set anywhere, MoRE runs on the built-in offline stand-in so
    the crew still moves on a fresh clone.
    """
    cfg = load_json(config_path(), {})
    base = os.environ.get("MOR_BASE_URL") or cfg.get("base_url") or ""
    return {
        "base_url": base.rstrip("/"),
        "model": os.environ.get("MOR_MODEL") or cfg.get("model") or "local",
        "api_key": os.environ.get("MOR_API_KEY") or cfg.get("api_key") or "-",
        "temperature": float(cfg.get("temperature", 0.6)),
        "max_tokens": int(cfg.get("max_tokens", 2048)),
        "timeout": float(cfg.get("timeout", 300)),
        "allow_shell": bool(cfg.get("allow_shell", False)),
    }


def set_config(**kwargs) -> dict:
    cfg = load_json(config_path(), {})
    cfg.update({k: v for k, v in kwargs.items() if v is not None})
    save_json(config_path(), cfg)
    return cfg


# --------------------------------------------------------------------------
# projects
# --------------------------------------------------------------------------
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def valid_project_name(name: str) -> bool:
    return bool(_NAME.match(name or ""))


def current_project_file() -> Path:
    return mor_home() / "current_project"


def current_project_name() -> str:
    f = current_project_file()
    if f.exists():
        name = f.read_text().strip()
        if name:
            return name
    return "default"


def use_project(name: str) -> None:
    mor_home().mkdir(parents=True, exist_ok=True)
    current_project_file().write_text(name.strip() + "\n")


class Project:
    """One working world on disk."""

    def __init__(self, name: str):
        self.name = name
        self.root = projects_root() / name

    def ensure(self) -> "Project":
        for sub in ("workspace", "sessions"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        return self

    @property
    def workspace(self) -> Path:
        return self.root / "workspace"

    @property
    def notes_path(self) -> Path:
        # A plain markdown file the crew can append to and read back — the
        # project's long-term memory between sessions.
        return self.root / "notes.md"

    def notes(self) -> str:
        p = self.notes_path
        return p.read_text().strip() if p.exists() else ""

    def session_path(self, stamp: str) -> Path:
        return self.root / "sessions" / f"{stamp}.jsonl"

    # --- web allowlist ---------------------------------------------------
    # The one egress rail: a tool may fetch a URL only for a domain the operator
    # has allowed. ``*`` opens the whole public web at once.
    @property
    def allow_path(self) -> Path:
        return self.root / "allow.json"

    def allowlist(self) -> list:
        return load_json(self.allow_path, {"domains": []}).get("domains", [])

    def egress_allowed(self, domain: str) -> bool:
        al = self.allowlist()
        return "*" in al or domain in al

    _HOSTNAME = re.compile(
        r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)*[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

    @classmethod
    def normalize_domain(cls, domain: str) -> str:
        """Store what the operator types as a bare hostname the fetcher can match:
        lowercase, no scheme, no path, no port. Returns '' for input that names no
        host (so the allowlist never silently fills with junk)."""
        d = (domain or "").strip().lower()
        if not d or d == "*":
            return d
        if "://" not in d:
            d = "//" + d
        host = (urlparse(d).hostname or "").rstrip(".")
        return host if cls._HOSTNAME.match(host) else ""

    def allow(self, domain: str) -> str:
        domain = self.normalize_domain(domain)
        if not domain:
            return ""
        data = load_json(self.allow_path, {"domains": []})
        domains = data.setdefault("domains", [])
        if domain not in domains:
            domains.append(domain)
        save_json(self.allow_path, data)
        return domain

    def disallow(self, domain: str) -> bool:
        domain = self.normalize_domain(domain)
        data = load_json(self.allow_path, {"domains": []})
        domains = data.get("domains", [])
        if domain in domains:
            domains.remove(domain)
            save_json(self.allow_path, data)
            return True
        return False


def load_project() -> Project:
    return Project(current_project_name()).ensure()
