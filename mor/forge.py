"""The tools.d forge — where a hard-won lesson becomes a new hand.

The Third Evangelism put how-to *notes* on the shelf. Notes advise; they do
not act. The forge closes the gap: a face may write a small Python module into
`<space>/tools.d/`, and from the next turn on it is a real tool in the loop —
the realm's capabilities grow by the realm's own hand, not by waiting for its
makers.

The contract a forged module must keep (small on purpose):

    NAME = "my_tool"                # tool name (letters, digits, _ -)
    DESCRIPTION = "what it does"    # one honest line for the mind
    PARAMETERS = {...}              # JSON schema for the arguments
    def run(args: dict, ctx) -> str: ...

A forged tool gets the SAME ToolContext the built-ins get — workspace-jailed
like them, egress-bound like them. The forge grants no escape: a forged module
runs inside the realm's process but the rails it must respect are the same
ones every hand respects. A module that fails to import, or breaks the
contract, is refused and named — never half-loaded.

Safety: forged tools are code the realm wrote for itself, reviewed the way the
Smith's changes are — the suite stays green or the day does not ship them.
The Master can always see what stands in tools.d; `forge list` shows it.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")

_CONTRACT_ERROR = (
    "a forged tool is a .py module defining NAME, DESCRIPTION, PARAMETERS "
    "(a JSON-schema dict) and run(args, ctx) -> str"
)


def tools_dir(space) -> Path:
    return space.root / "tools.d"


def valid_name(name: str) -> bool:
    return bool(_NAME.match(name or ""))


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(f"mor_forged_{path.stem}", path)
    if spec is None or spec.loader is None:
        return None, "could not build an import spec"
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001 — a broken tool must not break the realm
        return None, f"{type(e).__name__}: {e}"
    return mod, ""


def _check_contract(mod) -> str:
    name = getattr(mod, "NAME", None)
    desc = getattr(mod, "DESCRIPTION", None)
    params = getattr(mod, "PARAMETERS", None)
    run = getattr(mod, "run", None)
    if not (isinstance(name, str) and valid_name(name)):
        return f"NAME missing or invalid — {_CONTRACT_ERROR}"
    if not (isinstance(desc, str) and desc.strip()):
        return f"DESCRIPTION missing — {_CONTRACT_ERROR}"
    if not isinstance(params, dict) or params.get("type") != "object":
        return f"PARAMETERS must be a JSON-schema object dict — {_CONTRACT_ERROR}"
    if not callable(run):
        return f"run(args, ctx) missing — {_CONTRACT_ERROR}"
    return ""


def forge(space, name: str, source: str) -> str:
    """Write a new tool module into tools.d and validate it immediately.
    Returns an error string, or '' on success — the tool stands from the next
    tool-build on."""
    name = (name or "").strip()
    if not valid_name(name):
        return "a tool name starts with a letter: letters, digits, _ - (max 64)"
    if not (source or "").strip():
        return "the forge needs source, not silence"
    if "import os" in source and ("remove" in source or "rmdir" in source):
        return "refused: the forge grants no deletion — reverts belong to git"
    d = tools_dir(space)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.py"
    path.write_text(source, "utf-8")
    mod, err = _load_module(path)
    if mod is None:
        path.unlink()
        return f"the module did not import, so nothing was forged: {err}"
    err = _check_contract(mod)
    if err:
        path.unlink()
        return f"the module broke the contract, so nothing was forged: {err}"
    if getattr(mod, "NAME") != name:
        path.unlink()
        return (f"NAME says '{getattr(mod, 'NAME')}' but the file is '{name}.py' "
                "— they must match, so nothing was forged")
    return ""


def load_forged(space, Tool):
    """Load every valid forged module as a Tool. Modules that fail are skipped
    (and visible via `forge list`), never fatal. `Tool` is the engine's Tool
    class, passed in so the forge never imports the engine (no import cycle)."""
    d = tools_dir(space)
    out = []
    if not d.is_dir():
        return out
    builtins = set()  # names a forged tool may never shadow
    for path in sorted(d.glob("*.py")):
        mod, err = _load_module(path)
        if mod is None or _check_contract(mod):
            continue
        if mod.NAME in builtins:
            continue

        def _make(m):
            def _run(args, ctx):
                try:
                    result = m.run(args or {}, ctx)
                    return str(result)
                except Exception as e:  # noqa: BLE001
                    return f"ERROR in forged tool {m.NAME}: {type(e).__name__}: {e}"
            return _run

        out.append(Tool(mod.NAME, mod.DESCRIPTION.strip(), mod.PARAMETERS,
                        _make(mod)))
    return out


def list_forged(space) -> list:
    """[(name, status)] for every module standing in tools.d — valid or not."""
    d = tools_dir(space)
    out = []
    if not d.is_dir():
        return out
    for path in sorted(d.glob("*.py")):
        mod, err = _load_module(path)
        if mod is None:
            out.append((path.stem, f"BROKEN: {err}"))
            continue
        cerr = _check_contract(mod)
        out.append((path.stem, "forged and standing" if not cerr else f"REFUSED: {cerr}"))
    return out
