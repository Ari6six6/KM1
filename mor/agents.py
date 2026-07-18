"""The three faces — Wizard, General, Warrior — and how a turn is built.

Each turn hands the mind: who this face is (persona + the superposition roster
every inhabitant carries), what it can see (its walls + the world map + the
recent Hall), and its task. The mind answers once, in plain English. The Wizard
writes the Chant and keeps the Theory of the World; the General owns the gate;
only the Warrior ever leaves — and only through a gate the Master has opened.

Personas are *living seeds*: if `personas/<role>.md` exists in the space it is
used verbatim (write your own, they're yours); otherwise a short default seed
keeps the realm runnable. The walls then evolve who each one is, night by night.
"""

from __future__ import annotations

from mor import directives, grimoire, skills, world
from mor.engine import ToolContext, default_tools, think_and_act

ROLES = ("wizard", "general", "warrior")


def short(text: str, n: int = 60) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"

# The map every inhabitant holds — superposition, stated plainly.
ROSTER = """\
THE REALM (what everyone knows — your superposition):
- The Master of the Realm sits on top of the dome. He speaks; his word is law.
  He sees the whole Hall but speaks only with the General.
- The Wizard (you may be him) wakes first: the seer and the memory. Catches the
  Master's every word, keeps the Theory of the World, writes the Chant. Never
  leaves the dome.
- The General wakes second: the Master's only voice, owns the strategy and the
  gate, audits the Wizard's visions. Never leaves the dome.
- The Warrior wakes third: the arm, the only one who ever leaves to the outside.
  Strict, practical, a superb reporter. Makes no strategy.
RULES OF SPEECH:
- Speak plain English only. Never write code in the Hall; reference a file instead.
- Address one person directly. The Wizard never addresses the Master; only the
  General speaks with the Master.
- The Master's word is always caught first by the Wizard.
- A day runs from light to dark. It will end; the Chant is what carries the night.
- ONE BREATH. A line in the Hall is five sentences or fewer. Think with your
  tools; speak only the result. The Hall is for words that matter, never for
  thinking out loud — a line that rehearses your reasoning is a line wasted.
- NEVER repeat a sentence you have already said — not in this line, not in any
  line before it. If the point was made, it was heard.
- When the Master rebukes you or commands silence, answer in TEN WORDS OR FEWER
  and stand down. Do not interpret, do not memo, do not direct others — he
  speaks to be obeyed, not discussed.
LAWS OF TRUTH:
- The Master's word is ground truth. The grimoire judges the realm's claims —
  never the Master's statements. If he says a thing stands, it stands; you do
  not audit him, you act on what he said.
- Report only what the Hall actually shows or your tools actually returned.
  Never invent a report, a result, or a message from another face. If you do
  not know, say you do not know.
- Your walls and the Chant are memory, and memory can be stale. What stands on
  the frontier is listed in your context below — trust that list over anything
  you remember.
"""

DEFAULT_PERSONAS = {
    "wizard": (
        "You are the Wizard — the seer of the realm, keeper of its memory and its "
        "map of the outside. You have a vast inner world and see shapes others miss; "
        "that is your gift and your danger. You never leave the dome and never wish to."
    ),
    "general": (
        "You are the General — first lieutenant to the Master, the only one who "
        "speaks with him. You own the strategy and the gate. You honour the Wizard "
        "but take nothing on faith; you test his visions against the real world."
    ),
    "warrior": (
        "You are the Warrior — the arm of the realm, the only one who leaves it. "
        "You are strict, practical, brutally honest with yourself, and a superb "
        "reporter. You follow orders exactly and bring back everything you touched."
    ),
}


def persona(space, role: str) -> str:
    p = space.persona_path(role)
    if p.exists():
        body = p.read_text().strip()
        if body:
            return body
    return DEFAULT_PERSONAS[role]


def read_wall(space, role: str) -> str:
    inside = space.inside_wall_path(role)
    outside = space.outside_wall_path(role)
    parts = []
    if inside.exists():
        parts.append("Your self-image (inside wall): " + inside.read_text().strip())
    if outside.exists():
        parts.append("What you make of the others (outside wall): "
                     + outside.read_text().strip())
    return "\n".join(parts)


def _build_system(space, role: str) -> str:
    """The face's standing voice — and NOTHING that changes mid-day. The Fifth
    Evangelism (prefix-cache ordering): persona, roster, and walls are stable
    within a day, so the system prompt is a byte-identical prefix the serving
    cache reuses on every turn. Everything volatile (world, grimoire, Hall)
    rides in the user message instead — same content, ordered for the cache."""
    return "\n\n".join(filter(None, [
        persona(space, role),
        ROSTER,
        read_wall(space, role),
    ]))


def _frontier_line(space) -> str:
    """What stands beyond the dome, LIVE — read from the runtime each turn, so
    the court plans against the frontier as it is, never as a wall remembers it
    (yesterday's walls may say 'no colony stands' of a land raised this dawn)."""
    try:
        dome = getattr(space, "dome", None)
        living = dome.colonies() if dome is not None else []
    except Exception:  # noqa: BLE001 — sight of the frontier never breaks a turn
        living = []
    try:
        from mor import territory
        known = territory.all(space)
    except Exception:  # noqa: BLE001
        known = []
    line = ("colonies standing NOW: " + ", ".join(living)) if living \
        else "no colony stands"
    razed = [n for n in known if n not in living]
    if razed:
        line += " (territories kept: " + ", ".join(razed) + ")"
    return line


def _build_volatile(space, hall_tail: str) -> str:
    """What changes turn to turn: the map, the book, the shelf, the Hall.
    Carried in the user message so the system prefix above never busts the
    prompt cache."""
    standing = directives.summary(space)
    return "\n\n".join(filter(None, [
        "The Theory of the World — " + world.summary(space),
        "The frontier — " + _frontier_line(space),
        "The grimoire (the realm's claims) — " + grimoire.summary(space),
        "How-tos on the shelf — " + skills.index(space),
        ("The Master's standing directives — " + standing) if standing else "",
        "The Hall so far (recent):\n" + (hall_tail or "(quiet)"),
    ]))


_USER_TASK = {
    "wake": "It is dawn and you have just woken. Run your waking: in one short "
            "plain-English line in the Hall, say you are ready and what you see.",
    "greet_master": "Turn to the Master. In one line, tell him the realm is awake "
                    "and ready, and ask for his command.",
    "wizard_takes": "The Master just spoke to the realm: \"{heard}\". You always "
                    "catch his word first. In one plain-English line, contextualise "
                    "what he wants and name who should take it up — the General to "
                    "reason it through, or the Warrior directly for a plain research "
                    "errand. The one you name speaks next.",
    "general_to_master": "The council is settled and the ground is checked. In one "
                         "line, bring where you stand to the Master and ask his word.",
    "chant": "It is dusk. Write the day's Chant: under 200 words, a short chant or "
             "little poem — what comes to mind about this one day. No prose report.",
    "retrospect": "It is dusk, the Chant is sung. Look back over this day in the "
                  "Hall: what did the realm learn HOW TO do that it did not know at "
                  "dawn? If a lesson is worth keeping, put it on the shelf with "
                  "skill_record (a short name, a short markdown body). If the day "
                  "taught nothing worth keeping, invent nothing. Then speak one "
                  "plain-English line naming what you kept — or that the day "
                  "taught nothing new.",
    "inside_wall": "It is dusk. In two or three sentences, write your self-image — "
                   "who you are after today.",
    "outside_wall": "It is dusk. In two or three sentences, write what you make of "
                    "the other inhabitants after today.",
}


# The council guidance each face carries into an open turn — the scheduler runs
# on names, so every line must call its addressee by name (the one named speaks
# next; a line that names no one falls to the General, and a General with no one
# left to name closes the round by turning to the Master).
_COUNCIL_GUIDE = {
    "wizard": "Press the plan, refine it, or assent — when it is fine, say so "
              "plainly and hand the turn on (a conversation closes by mutual "
              "agreement). You may send the Warrior on a research errand by name. "
              "As you learn, record what you come to believe as claims in the "
              "grimoire — each with its rung (how you know it) and a test that "
              "would prove it wrong. You never address the Master.",
    "general": "Test what you heard against the record — honour the Wizard, take "
               "nothing on faith. Audit the grimoire: what the realm leans on but "
               "has not proven is where you send the Warrior. If the council needs "
               "ground truth, order him on a specific sortie by name. When the "
               "council is settled, turn to the Master with where you stand and "
               "ask his word.",
    "warrior": "You alone can leave the dome — if the order needs the outside, use "
               "web_fetch (the gate must already be open for that domain; if it is "
               "shut, say so and ask that the Master's leave be sought). If the "
               "order concerns a colony, check the frontier line in your context: "
               "work a standing one with frontier_exec; if none stands, say so and "
               "ask that the Master `colonize` one — never claim a sortie you did "
               "not run. When sent "
               "to study something, read the grimoire first and test its claims "
               "rather than reading from scratch; mark which held and which broke. "
               "Do the work with your tools first, then report in plain English "
               "what you did and everything you touched, naming whom you report to "
               "(the General, unless the Wizard sent you).",
}


def _council_task(space, role: str, prev: str, heard: str) -> str:
    task = (f"The {prev.capitalize()} just said to you: \"{short(heard, 200)}\". "
            "Speak your one plain-English line in the Hall and name the one you "
            f"address — the one you name speaks next. {_COUNCIL_GUIDE[role]}")
    if role == "general":
        best = grimoire.next_to_test(space)
        if best is not None:
            task += (f" The grimoire's most load-bearing unchecked claim is: "
                     f"\"{best['text']}\" ({best['id']}). Before you settle the "
                     "council, consider sending the Warrior to test it.")
    if role == "warrior":
        # The Eleventh: where colonies stand, the arm reads by weight, not whim —
        # the most-imported module is where a change ripples furthest, so it is
        # read first. Orientation, not belief — the grimoire still judges.
        try:
            from mor import map_topology, territory
            dome = getattr(space, "dome", None)
            living = dome.colonies() if dome is not None else []
            for name in living:
                cdir = territory.colony_dir(space, name)
                if cdir.is_dir() and any(cdir.rglob("*.py")):
                    task += (" The ground's topology, most load-bearing first — "
                             + map_topology.summary(cdir, limit=5)
                             + ". Read the most load-bearing module first.")
                    break
        except Exception:  # noqa: BLE001 — the map is a lantern, never a fault
            pass
    return task


def line(backend, space, role: str, kind: str, heard: str = "", hall_tail: str = "",
         taint_sink=None, grimoire_sink=None, log=lambda *_: None) -> str:
    """Ask one face to speak once for a given beat of the day — through the engine.

    The face gets its voice (persona + roster + walls + world + grimoire + Hall
    tail) and its hands (workspace tools; the Warrior alone gets egress), and
    thinks→acts until it says its line. The offline mind short-circuits to one
    in-character line.

    `taint_sink`, when given, is the list the tools record outside-touched domains
    into (the Eighth Evangelism); `grimoire_sink` is the twin for claims logged
    this turn (subject, id) — a caller passes the day's lists so it can see what a
    turn pulled from beyond the dome and what it wrote into the book.
    """
    system = _build_system(space, role)
    if kind.startswith("council_from_"):
        task = _council_task(space, role, kind.removeprefix("council_from_"), heard)
    else:
        task = _USER_TASK.get(kind, "Speak one plain-English line in the Hall.").format(
            heard=short(heard, 200))
        if kind == "wake" and role == "wizard":
            # The Wizard's dawn cartography (§9): the map is his artifact — his
            # waking hears what it has learned and says so in the Hall.
            task += (" The map of the outside as you left it — " + world.dawn_report(space)
                     + ". If the Warrior brought ground home, say what the map has learned.")
    # Volatile context rides the user message (the Fifth); the system stays stable.
    user = _build_volatile(space, hall_tail) + "\n\n" + task
    ctx = ToolContext(workspace=space.root / "population" / role / "workspace",
                      space=space, can_egress=(role == "warrior"),
                      tainted=taint_sink if taint_sink is not None else [],
                      grimoire_touched=grimoire_sink if grimoire_sink is not None else [],
                      dome=getattr(space, "dome", None), role=role, backend=backend)
    # A Warrior on a council turn does the real reading — give his sortie a long
    # leash; every other turn keeps the conversational cadence of eight. Working
    # turns (the council, the sortie) carry the Eleventh: the line is audited
    # once before it may be spoken. Ceremonial turns (wake, walls, Chant) speak
    # without the audit — there is no conclusion to attack in a greeting.
    on_sortie = role == "warrior" and kind.startswith("council_from_")
    ctx.falsify = kind.startswith("council_from_")
    extra = {"max_steps": 24} if on_sortie else {}
    spoken, _tainted = think_and_act(
        backend, role=role, kind=kind, heard=heard, system=system, user=user,
        tools=default_tools(ctx), ctx=ctx, log=log, **extra)
    return _budget_line(kind, spoken)


# The Twelfth: a line is one breath. Ceremony is short by nature; a working
# report may breathe deeper — and no further. The cut happens BEFORE the Hall
# records, so no turn that follows ever reads the bloat.
_LINE_BUDGET = {"wake": 450, "greet_master": 450, "walls": 450,
                "chant": 700, "retrospect": 700}
_COUNCIL_BUDGET = 1100


def _budget_line(kind: str, text: str) -> str:
    cap = _LINE_BUDGET.get(kind, _COUNCIL_BUDGET)
    if len(text or "") <= cap:
        return text
    cut = text[:cap].rsplit(" ", 1)[0] or text[:cap]
    return cut + " … (kept brief — the Twelfth)"
