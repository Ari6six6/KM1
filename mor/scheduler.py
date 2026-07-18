"""The name-mention scheduler — who speaks next, read from the Hall itself.

The spec's own words (THE_REALM §10.2): *reads the Hall, sees who was named,
runs that agent next — turns, not parallelism.* This is that reader. A face
speaks its line; the first inhabitant the line names is the one who speaks
next. No fixed beats: the council branches where the words point it.

The rules of speech (§3) are enforced here, not asked for:
  - Rule 2 (the Wizard always catches the Master's word first) lives in the
    realm, before this scheduler ever runs.
  - Rule 3/4: only the General speaks with the Master. Anyone else naming the
    Master is routed to the General — the Master's voice — instead.
  - A line that names no one falls to the natural hub: the General. A General
    with no one left to name turns to the Master — which is how a council
    round *closes* (§3.6: a conversation ends by agreement, and the General
    brings the settled ground up).
"""

from __future__ import annotations

import re

ROLES = ("wizard", "general", "warrior")
_NAME = re.compile(r"\b(master|wizard|general|warrior)\b", re.IGNORECASE)


def named(text: str) -> list:
    """Every inhabitant a line names, in the order it names them, once each."""
    seen, out = set(), []
    for m in _NAME.finditer(text or ""):
        name = m.group(1).lower()
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def resolve_addressee(speaker: str, text: str) -> str:
    """Whom this line is spoken to — the first name it calls that isn't the
    speaker's own, under the rules of speech. Returns a role, or "master"
    (only ever for the General — that is the close of a council round)."""
    for name in named(text):
        if name == speaker:
            continue  # speaking of yourself is not an address
        if name == "master" and speaker != "general":
            return "general"  # only the General speaks with the Master (§3.4)
        return name
    # No one named: the hub catches it — and the General, with no one left to
    # name, turns to the Master, which closes the round.
    return "master" if speaker == "general" else "general"
