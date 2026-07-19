"""The mind registry + the selection window — many boxes, one active mind.

The Master rents his own boxes (his hunt, his deals), pastes one ssh string, and
the harness does the rest — BYO is the primary path. He runs more than one, so the
harness keeps a **registry** of boxes (BYO-adopted or rented) and, when more than
one mind is serving, asks which to use.

The registry reuses the Field's event log (no second store): a box is a projection
of ``box`` events — adopt / release / dead / rate. The active mind is a tiny piece
of project state that survives daemon restarts. Routing: zero serving → the offline
stand-in; exactly one → auto-route, no prompt; more than one with no active → the
numbered selection window.
"""

from __future__ import annotations

from mor.config import load_json, save_json
from mor.field import Field


def _mind_path(project):
    return project.root / "mind.json"


def register_box(project, *, label, base_url, model, ssh_host=None, ssh_port=None,
                 rate=0.0, source="byo") -> None:
    Field(project)._record("box", action="adopt", label=label,
                           base_url=(base_url or "").rstrip("/"), model=model,
                           ssh_host=ssh_host, ssh_port=ssh_port, rate=float(rate),
                           source=source, state="serving")


def _project(project) -> dict:
    boxes = {}
    for e in Field(project).events:
        if e.get("kind") != "box":
            continue
        b = boxes.setdefault(e["label"], {"label": e["label"], "state": "down", "rate": 0.0})
        action = e.get("action")
        if action == "adopt":
            b.update(base_url=e.get("base_url"), model=e.get("model"),
                     ssh_host=e.get("ssh_host"), ssh_port=e.get("ssh_port"),
                     rate=float(e.get("rate", 0.0)), source=e.get("source", "byo"),
                     state="serving")
        elif action == "release":
            b["state"] = "released"
        elif action == "dead":
            b["state"] = "dead"
        elif action == "rate":
            b["rate"] = float(e.get("rate", 0.0))
    return boxes


def boxes(project) -> list:
    return list(_project(project).values())


def serving(project) -> list:
    return [b for b in boxes(project) if b.get("state") == "serving"]


def get(project, label_or_index):
    bs = boxes(project)
    for b in bs:
        if b["label"] == label_or_index:
            return b
    try:                                   # a 1-based index into the serving list
        n = int(label_or_index)
        sv = serving(project)
        if 1 <= n <= len(sv):
            return sv[n - 1]
    except (ValueError, TypeError):
        pass
    return None


def active(project):
    return load_json(_mind_path(project), {}).get("active")


def set_active(project, label) -> None:
    save_json(_mind_path(project), {"active": label})


def chosen(project) -> tuple:
    """The mind to route a run to: (box_or_None, needs_selection). Zero serving →
    offline; one → auto; many with a valid active → that; many with none → select."""
    sv = serving(project)
    if not sv:
        return None, False
    if len(sv) == 1:
        return sv[0], False
    a = active(project)
    for b in sv:
        if b["label"] == a:
            return b, False
    return None, True


def set_rate(project, label, rate) -> bool:
    b = get(project, label)
    if not b:
        return False
    Field(project)._record("box", action="rate", label=b["label"], rate=float(rate))
    return True


def release(project, label):
    b = get(project, label)
    if not b:
        return None
    Field(project)._record("box", action="release", label=b["label"])
    return b


def next_byo_label(project, host) -> str:
    prefix = f"byo-{host}-"
    n = sum(1 for b in boxes(project) if b["label"].startswith(prefix))
    return f"{prefix}{n + 1}"


def prompt_selection(project, ask=input, out=print):
    """The Termux-friendly numbered picker; remembers the choice as active."""
    sv = serving(project)
    out("  more than one mind is serving — which one?")
    for i, b in enumerate(sv, 1):
        out(f"    {i}. {b['label']} · {b.get('model')} · {b.get('base_url')}")
    try:
        choice = ask(f"  which mind? [1..{len(sv)}] ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    b = get(project, choice)
    if b and b.get("state") == "serving":
        set_active(project, b["label"])
        return b
    return None
