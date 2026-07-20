"""The order — the unit of work the realm does.

The debate's synthesis: *the order is the unit of work; the Hall is the unit of
being.* An order doesn't bypass the crew — it is executed **through** the Hall (the
shared transcript), and the artifact drops at the end. A chat round narrates; an
order delivers a file you can read, run, or scp.

An order is durable and event-sourced, in miniature — the seed of the realm-wide
Ledger to come. Every step is an append-only event under
``orders/<id>/events.jsonl``; the order's **state is a projection of those events**,
so it survives a restart: reload the events, replay them, and you know exactly
where the order stood. Nothing is a live variable that a crash can lose.

    received → planned → executing → verifying → delivered | failed

Three kinds so far — ``research`` (a sourced answer), ``build`` (code + a test in
the workspace), ``fetch`` (pull and save from the web) — differ only in how the
work is framed and which face leads; the order object is the same. Each writes
``report.md``: the crew's conclusion plus the Hall that produced it. Offline (no
model) it still delivers, labelled DEMO, so the whole flow moves on a fresh clone.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_LIFECYCLE = ("received", "planned", "executing", "verifying", "delivered", "failed")

KINDS = ("research", "build", "fetch")

_KIND_TASKS = {
    "research": "Research this and deliver a clear, well-sourced answer: {brief}",
    "build": ("Build this in the shared workspace: {brief}. Write the code and a "
              "test for it; if a shell is enabled, run the test and report whether "
              "it passed. The deliverable is the working files plus a short report "
              "of what you built and how you verified it."),
    "fetch": ("Fetch this from the public web and save what you retrieve into the "
              "workspace: {brief}. Report each source you touched (web data is "
              "TAINTED until it has been checked) and the path you saved it to."),
}


def _task_for(kind: str, brief: str) -> str:
    body = _KIND_TASKS.get(kind, _KIND_TASKS["research"]).format(brief=brief)
    return (body + "\n\nWork it as a crew and finish with a clear, plain-English "
            "result for the operator — that becomes the delivered report.")


def _new_id(kind: str) -> str:
    """A sortable, unique order id: a microsecond timestamp (so reverse string sort
    is newest-first) plus a short random tail (so a collision never happens)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return f"{stamp}-{os.urandom(2).hex()}-{kind}"


@dataclass
class Order:
    id: str
    kind: str
    brief: str
    dir: Path
    events: list = field(default_factory=list)

    # -- event log (the substrate) ---------------------------------------
    @property
    def events_path(self) -> Path:
        return self.dir / "events.jsonl"

    @property
    def hall_path(self) -> Path:
        return self.dir / "hall.jsonl"

    def record(self, event_kind: str, **payload) -> dict:
        """Append one event and return it. The only way order state ever changes.
        ``event_kind`` is the event's own type (a lifecycle state); the order's
        kind, when carried, rides in the payload as ``order_kind``."""
        event = {"seq": len(self.events), "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "kind": event_kind, **payload}
        self.events.append(event)
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a") as f:
            f.write(json.dumps(event) + "\n")
        return event

    # -- state, as a projection of the events ----------------------------
    @property
    def state(self) -> str:
        for e in reversed(self.events):
            if e["kind"] in _LIFECYCLE:
                return e["kind"]
        return "received"

    @property
    def brief_of_record(self) -> str:
        for e in self.events:
            if e["kind"] == "received":
                return e.get("brief", self.brief)
        return self.brief

    def artifacts(self) -> list:
        """Absolute paths of delivered artifacts that still exist on disk."""
        out = []
        for e in self.events:
            if e["kind"] == "delivered":
                p = self.dir / e.get("artifact", "")
                if p.exists():
                    out.append(p)
        return out


class OrderStore:
    """The orders of one project — plain directories under ``orders/``."""

    def __init__(self, project):
        self.root = project.root / "orders"

    def create(self, kind: str, brief: str) -> Order:
        oid = _new_id(kind)
        order = Order(id=oid, kind=kind, brief=brief, dir=self.root / oid)
        order.dir.mkdir(parents=True, exist_ok=True)
        order.record("received", order_kind=kind, brief=brief)
        return order

    def load(self, oid: str) -> "Order | None":
        d = self.root / oid
        ep = d / "events.jsonl"
        if not ep.exists():
            return None
        events = []
        for raw in ep.read_text().splitlines():
            raw = raw.strip()
            if raw:
                try:
                    events.append(json.loads(raw))
                except ValueError:
                    continue
        rec = next((e for e in events if e["kind"] == "received"), {})
        order = Order(id=oid, kind=rec.get("order_kind", "order"),
                      brief=rec.get("brief", ""), dir=d, events=events)
        return order

    def list(self) -> list:
        if not self.root.exists():
            return []
        ids = sorted((p.name for p in self.root.iterdir()
                      if p.is_dir() and (p / "events.jsonl").exists()), reverse=True)
        return [o for o in (self.load(i) for i in ids) if o is not None]


def _render_report(order: Order, entries: list, mode: str) -> str:
    """The delivered artifact: the crew's conclusion, then the Hall that made it."""
    conclusion = ""
    for e in reversed(entries):
        if e.get("addressee") == "operator":
            conclusion = e.get("text", "")
            break
    lines = [f"# {order.kind.title()}: {order.brief}", "",
             conclusion or "_(the crew produced no closing line)_", "",
             "---", "", "## How the crew worked (the Hall)", ""]
    for e in entries:
        who = e.get("speaker", "?")
        to = e.get("addressee")
        arrow = f" → {to}" if to else ""
        lines.append(f"- **{who}{arrow}:** {e.get('text', '')}")
    tag = "offline stand-in (DEMO)" if mode == "offline" else f"model ({mode})"
    lines += ["", "---", f"_generated by MoRE · order `{order.id}` · via the {tag}_", ""]
    return "\n".join(lines)


def execute_order(project, order: Order, *, client=None, echo: bool = True,
                  on_turn=None) -> Order:
    """Run an order through the Hall as a **bounded gate loop**, leaving the best
    artifact of up to ``B+1`` attempts. Every transition is an event, so the whole
    life is on disk the instant it happens — a crash mid-loop resumes at its last
    recorded attempt.

    The cycle: freeze a rubric at ``planned`` (an event, never a spoken line — the
    two walls), then work → score → decide. On a measured shortfall with an armed
    gate, loop back to ``executing`` carrying the failing components forward; on
    accept (or an advisory read) deliver the **argmax** attempt; on exhaustion fail
    with the best score and the critique — a stop with a reason, not a graveyard.
    Offline and on uncalibrated kinds the gate is advisory: it scores and flags but
    never blocks, so a fresh clone still delivers, labelled DEMO."""
    from mor.session import Session   # local import: session imports config only
    from mor import fitness
    from mor.config import gate_params

    try:
        budget = gate_params()["budget"]
        rubric = fitness.make_rubric(order.kind, order.brief, client=client)
        order.record("planned", plan=(f"gate the {order.kind}: work, score against a "
                                      f"frozen rubric, keep the best of ≤{budget + 1} attempts"))
        # Wall 1 (temporal): the rubric is an event at seq k, before any work.
        # Wall 2 (contextual): it rides order.record — the event log — never the
        # Transcript, so no face reads its own exam. `mor` proves both by `cat`.
        rubric_evt = order.record("rubric", order_kind=order.kind,
                                  authored_by=rubric["authored_by"], checks=rubric["checks"])

        best = None            # (scalar, report_text, mode, attempt, fit)
        carry = None           # failing components + critique from the last attempt
        for attempt in range(budget + 1):
            order.record("executing", attempt=attempt)
            session = Session(project, echo=echo, client=client,
                              transcript_path=order.hall_path, on_turn=on_turn)
            task = _task_for(order.kind, order.brief)
            if carry:          # coaching after a scored failure — the near side of Wall 2
                task = task + "\n\n" + fitness.coaching(carry)
            session.run_task(task)
            entries = session.transcript.entries()
            report_text = _render_report(order, entries, session.mode)

            adir = order.dir / "attempts" / str(attempt)
            adir.mkdir(parents=True, exist_ok=True)
            (adir / "report.md").write_text(report_text)

            order.record("verifying", attempt=attempt)
            fit = fitness.score(order.kind, order.brief, report_text,
                                project.workspace, rubric, client=client)
            order.record("fitness", attempt=attempt, rubric_seq=rubric_evt["seq"],
                         vector=fit["vector"], weights=fit["weights"], scalar=fit["scalar"],
                         failing=fit["failing"], critique=fit["critique"])

            if best is None or fit["scalar"] > best[0]:
                best = (fit["scalar"], report_text, session.mode, attempt, fit)

            verdict, _theta = fitness.gate(fit["scalar"], order.kind, project)
            if verdict != "reject":         # accept or advisory — stop, keep this
                break
            if attempt < budget:            # a licensed shortfall — coach and retry
                carry = {"failing": fit["failing"], "critique": fit["critique"]}
                order.record("retry", attempt=attempt + 1, carry=carry)

        # Terminal — keep-best: the trajectory may thrash; the deliverable can't.
        best_scalar, best_text, best_mode, best_attempt, best_fit = best
        (order.dir / "report.md").write_text(best_text)
        verdict, theta = fitness.gate(best_scalar, order.kind, project)
        if verdict == "reject":
            order.record("failed",
                         reason=f"below the gate — best {best_scalar:.2f} < θ {theta:.2f} "
                                f"after {budget + 1} attempts",
                         best_attempt=best_attempt, best_score=round(best_scalar, 4),
                         critique=best_fit["critique"])
        else:
            order.record("delivered", artifact="report.md", mode=best_mode,
                         chosen_attempt=best_attempt, score=round(best_scalar, 4),
                         gate=("advisory" if theta is None else "armed"))
    except Exception as e:  # noqa: BLE001 — a bad turn fails the order, never the daemon
        order.record("failed", reason=f"{type(e).__name__}: {str(e)[:200]}")
    return order


def run_order(project, kind: str, brief: str, *, client=None, echo: bool = True,
              store: "OrderStore | None" = None, on_turn=None) -> Order:
    """Create an order and execute it end to end. Returns the delivered (or failed)
    Order."""
    store = store or OrderStore(project)
    order = store.create(kind, brief)
    return execute_order(project, order, client=client, echo=echo, on_turn=on_turn)
