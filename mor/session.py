"""The session — a crew working one task at a time in a shared transcript.

Turn order is read from the words themselves: an agent ends its line by naming
who speaks next, and that agent goes next (``next_speaker`` below). The lead is
the hub — it opens each round and closes it by turning to the operator. A hard
turn cap guarantees every round ends.
"""

from __future__ import annotations

import re
import time

from mor.agent import build_system, load_crew
from mor.config import load_project
from mor.llm import MockClient, make_client
from mor.loop import think_and_act
from mor.tools import ToolContext, build_tools
from mor.transcript import Transcript
from mor import ui

_OPERATOR_ALIASES = ("operator", "user")
_MAX_TURNS = 10


def next_speaker(speaker: str, text: str, names: list, lead: str) -> str:
    """Who speaks next after ``speaker`` said ``text``.

    The first name the line calls (that isn't the speaker's own) wins. Naming the
    operator closes the round when the lead says it, and is routed to the lead
    when anyone else says it (only the lead speaks with the operator). A line that
    names no one falls to the lead — and the lead, with no one to hand to, turns
    to the operator, which is how a round ends.
    """
    vocab = [n.lower() for n in names] + list(_OPERATOR_ALIASES)
    pattern = re.compile(r"\b(" + "|".join(re.escape(v) for v in vocab) + r")\b",
                         re.IGNORECASE)
    seen = set()
    for m in pattern.finditer(text or ""):
        name = m.group(1).lower()
        if name in seen:
            continue
        seen.add(name)
        if name == speaker.lower():
            continue
        if name in _OPERATOR_ALIASES:
            return "operator" if speaker == lead else lead
        return name
    return "operator" if speaker == lead else lead


class Session:
    def __init__(self, project=None, *, echo: bool = True, client=None):
        self.project = project or load_project()
        self.crew = load_crew(self.project)
        self.names = [a.name for a in self.crew]
        self.lead = self.crew[0].name
        self.by_name = {a.name: a for a in self.crew}
        if client is not None:
            self.client, self.mode = client, "test"
        else:
            self.client, self.mode = make_client()
        from mor.config import endpoint
        self.allow_shell = endpoint().get("allow_shell", False)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.transcript = Transcript(self.project.session_path(stamp), echo=echo)
        self.tainted: list = []

    # -- one task --------------------------------------------------------
    def run_task(self, text: str) -> None:
        tr = self.transcript
        tr.post("operator", self.lead, text)
        before = len(self.tainted)
        speaker, heard_from, heard = self.lead, "operator", text

        for turn in range(_MAX_TURNS):
            spoken = self._speak(speaker, heard_from, heard, opening=(turn == 0))
            addressee = next_speaker(speaker, spoken, self.names, self.lead)
            if speaker == self.lead and addressee == "operator":
                tr.post(self.lead, "operator", self._flag(spoken, before))
                return
            tr.post(speaker, addressee, spoken)
            heard_from, speaker, heard = speaker, addressee, spoken

        # cap hit: make the lead close honestly rather than let it wander
        spoken = self._speak(self.lead, heard_from, heard, opening=False, close=True)
        tr.post(self.lead, "operator", self._flag(spoken, before))

    # -- one agent's turn ------------------------------------------------
    def _speak(self, name: str, heard_from: str, heard: str, *,
               opening: bool, close: bool = False) -> str:
        agent = self.by_name[name]
        system = build_system(agent, self.crew, self.lead, self.project.notes())
        ctx = ToolContext(workspace=self.project.workspace, project=self.project,
                          can_egress=agent.can_egress, allow_shell=self.allow_shell,
                          tainted=self.tainted)
        tools = build_tools(agent.tools, ctx)
        user = self._task(name, heard_from, heard, opening=opening, close=close)
        seed = self._seed(name, opening=opening, close=close)
        steps = 12 if (agent.can_egress or "run_shell" in agent.tools) else 8
        spoken, _ = think_and_act(
            self.client, system=system, user=user, tools=tools, ctx=ctx,
            seed=seed, log=lambda m: print(ui.dim(m)) if self.transcript.echo else None,
            max_steps=steps)
        return spoken

    def _task(self, name: str, heard_from: str, heard: str, *,
              opening: bool, close: bool) -> str:
        context = "Recent transcript:\n" + self.transcript.tail_text() + "\n\n"
        if close:
            return (context + "The round has run long. Bring the operator a clear, "
                    "plain-English summary of where things stand, and address the "
                    "operator.")
        if opening and name == self.lead:
            return (context + f"The operator asked: \"{heard}\". This begins the "
                    "round. Break it into steps and delegate to a teammate by name, "
                    "or handle a read-only part yourself. End by naming who speaks "
                    "next.")
        return (context + f"It is your turn. {heard_from} said to you: \"{heard}\". "
                "Do your part with your tools, then speak one plain-English line and "
                "name who should speak next.")

    def _seed(self, name: str, *, opening: bool, close: bool) -> str:
        """A deterministic in-character line for the offline MockClient, so a
        session still moves and terminates with no model. Ignored by real models."""
        teammates = [n for n in self.names if n != self.lead]
        first = teammates[0] if teammates else self.lead
        if close or (name == self.lead and not opening):
            return ("Thanks — that covers it. Operator, here is where we stand: the "
                    "crew looked it over and reported back.")
        if name == self.lead and opening:
            return (f"Understood. {first}, please take the first look and report "
                    "back to the lead.")
        return "I've done my part and noted what I found. Lead, over to you."

    def _flag(self, text: str, before: int) -> str:
        new = self.tainted[before:]
        if not new:
            return text
        return (f"⚠ this rests on data fetched from outside ({', '.join(sorted(set(new)))}) "
                f"— treat as unverified until checked. " + text)


def run_headless(task: str) -> None:
    """One task, printed, then exit — for scripting (`mor run \"...\"`)."""
    Session().run_task(task)
