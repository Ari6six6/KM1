"""The scheduler and a whole session end to end."""

from __future__ import annotations

from mor.session import Session, next_speaker
from mor.llm import ScriptClient


NAMES = ["lead", "researcher", "worker"]


# --- the name-mention scheduler --------------------------------------------
def test_named_teammate_speaks_next():
    assert next_speaker("lead", "researcher, look into this.", NAMES, "lead") == "researcher"


def test_lead_addressing_operator_closes_the_round():
    assert next_speaker("lead", "operator, here is the result.", NAMES, "lead") == "operator"


def test_teammate_addressing_operator_is_routed_to_lead():
    # only the lead speaks with the operator
    assert next_speaker("worker", "operator, it is done.", NAMES, "lead") == "lead"


def test_a_line_naming_no_one_falls_to_the_lead():
    assert next_speaker("worker", "I finished the task.", NAMES, "lead") == "lead"


def test_speaker_does_not_address_itself():
    assert next_speaker("lead", "I, the lead, will ask researcher next.", NAMES, "lead") == "researcher"


# --- a full session --------------------------------------------------------
def test_offline_session_runs_and_terminates(project):
    s = Session(project, echo=False)   # no endpoint set -> offline MockClient
    s.run_task("take stock of the workspace")
    entries = s.transcript.entries()
    assert entries[0]["speaker"] == "operator"
    # the round must close with the lead turning to the operator
    assert entries[-1]["speaker"] == "lead"
    assert entries[-1]["addressee"] == "operator"


def test_scripted_session_delegates_and_closes(project):
    # lead delegates to worker; worker writes a file and hands back; lead closes.
    script = ScriptClient([
        {"text": "worker, please create hello.txt."},
        {"tools": [{"tool": "write_file", "args": {"path": "hello.txt",
                                                   "content": "hi"}}],
         "say": None},
        {"text": "Done — wrote hello.txt. lead, over to you."},
        {"text": "operator, hello.txt is created."},
    ])
    s = Session(project, echo=False, client=script)
    s.run_task("create a hello file")
    assert (project.workspace / "hello.txt").read_text() == "hi"
    last = s.transcript.entries()[-1]
    assert last["speaker"] == "lead" and last["addressee"] == "operator"


def test_no_face_reads_another_faces_private_context(project):
    """R0 acceptance — the context-assembly audit. A face is built from its own
    system prompt and the shared Hall only; what a teammate read privately (a tool
    observation) never enters anyone's context. Only the Hall line it spoke crosses."""
    secret = "SECRETMARKER-9f3x"
    project.workspace.mkdir(parents=True, exist_ok=True)
    (project.workspace / "secret.txt").write_text(f"{secret} the north road is clear")
    script = ScriptClient([
        {"text": "researcher, read secret.txt and give a one-line summary. "},
        {"tool": "read_file", "args": {"path": "secret.txt"}},   # private observation
        {"text": "I read it; summary: the road is open. lead, over to you."},
        {"text": "operator, the road is open."},
    ])
    seen = []
    s = Session(project, echo=False, client=script, on_turn=seen.append)
    s.run_task("scout the north road")

    assert seen, "no turns were captured"
    # the secret the researcher read privately never entered any face's context
    assert all(secret not in t["user"] and secret not in t["system"] for t in seen)
    # but the line the researcher *spoke* in the Hall did reach the lead
    assert any("the road is open" in t["user"] for t in seen)


def test_taint_flag_is_raised_when_outside_data_is_used(project):
    project.allow("example.com")
    s = Session(project, echo=False)
    # simulate the researcher having fetched something this task
    before = len(s.tainted)
    s.tainted.append("example.com")
    flagged = s._flag("all good.", before)
    assert "unverified" in flagged and "example.com" in flagged
