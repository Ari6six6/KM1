"""Tier 1 — the realized aspirations, pinned.

The Fifth Evangelism (a byte-stable system prefix the serving cache can hold),
§9 (the Theory of the World as a real cartography: IPs, paths, cadence, the
Wizard's dawn report), and §4 (the Master's word is always the next turn — a
queued word closes a running round honestly, never interrupts a thought).
"""

from __future__ import annotations

import pytest

from mor import world
from mor.agents import line
from mor.engine import ScriptBackend
from mor.engine.backend import Backend, ChatResult
from mor.engine.tools import _web_fetch, ToolContext
from mor.realm import Realm


# --- the Fifth: the system prefix never moves -------------------------------
class CaptureBackend(Backend):
    def __init__(self):
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append([dict(m) for m in messages])
        return ChatResult(content="a line for the Hall")


def test_system_prompt_is_byte_stable_as_the_hall_moves(space):
    b = CaptureBackend()
    line(b, space, "wizard", "wake", hall_tail="general: first version")
    line(b, space, "wizard", "wake", hall_tail="general: a wholly different tail")
    sys_a, sys_b = (c[0]["content"] for c in b.calls)
    assert sys_a == sys_b  # persona + roster + walls — cacheable, byte-identical
    # ...while the volatile ground rides the user turn, not the system
    assert "first version" in b.calls[0][1]["content"]
    assert "wholly different tail" in b.calls[1][1]["content"]
    assert "The Hall so far" not in sys_a


def test_the_wizards_waking_carries_the_dawn_cartography(space):
    world.record_sortie(space, "example.com", "GET 200", ips=["93.184.216.34"])
    b = CaptureBackend()
    line(b, space, "wizard", "wake", hall_tail="")
    user = b.calls[0][1]["content"]
    assert "1 known place" in user and "example.com" in user
    # ...but only the Wizard cartographs at dawn (the General just reads the map)
    line(b, space, "general", "wake", hall_tail="")
    assert "last touched" not in b.calls[1][1]["content"]


# --- §9: the Theory of the World as a real cartography -----------------------
def test_sorties_accrete_ips_paths_and_days(space):
    world.record_sortie(space, "example.com", "GET 200", ips=["93.184.216.34"], path="/")
    world.record_sortie(space, "https://example.com/docs", "GET 200",
                        ips=["93.184.216.34"], path="/docs")
    p = world.load(space)["places"]["example.com"]
    assert p["ips"] == ["93.184.216.34"]            # deduped
    assert p["paths"] == ["/", "/docs"]             # in the order first touched
    assert p["visits"] == 2 and len(p["days"]) == 1
    assert p["first_seen"] and p["last_seen"]


def test_an_old_map_is_upgraded_not_lost(space):
    from mor.config import save_json
    save_json(space.world_path(), {"places": {"old.example": {
        "domain": "old.example", "first_seen": "2026-01-01",
        "visits": 4, "notes": ["GET 200, 12 bytes"], "last_seen": "2026-01-02"}}})
    world.record_sortie(space, "old.example", "GET 200", ips=["10.1.1.1"], path="/x")
    p = world.load(space)["places"]["old.example"]
    assert p["visits"] == 5 and p["notes"]          # the old record survived
    assert p["ips"] == ["10.1.1.1"] and p["paths"] == ["/x"] and p["days"]


def test_summary_shows_ip_cadence_and_shared_ground(space):
    from mor.config import save_json
    save_json(space.world_path(), {"places": {
        "a.example": {"domain": "a.example", "visits": 5, "ips": ["1.2.3.4"],
                      "paths": ["/"], "days": ["d1", "d2", "d3"], "notes": []},
        "b.example": {"domain": "b.example", "visits": 1, "ips": ["1.2.3.4"],
                      "paths": [], "days": ["d2"], "notes": []},
    }})
    s = world.summary(space)
    assert "a.example [1.2.3.4] (seen 5× over 3 days)" in s
    assert "shared ground: 1.2.3.4 hosts a.example, b.example" in s


def test_dawn_report_names_what_moved_most_recently(space):
    assert "blank" in world.dawn_report(space)
    world.record_sortie(space, "example.com", "GET 200")
    r = world.dawn_report(space)
    assert "1 known place" in r and "example.com" in r


def test_a_fetch_records_where_the_place_lives(space, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])

    class FakeResp:
        status = 200

        def read(self, n=None):
            return b"<html>mapped</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("mor.engine.tools._open_one_hop", lambda *a, **k: FakeResp())
    ws = space.root / "population" / "warrior" / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    ctx = ToolContext(workspace=ws, space=space, can_egress=True, tainted=[], role="warrior")
    space.authorize("example.com")
    _web_fetch({"url": "http://example.com/docs/deep"}, ctx)
    p = world.load(space)["places"]["example.com"]
    assert p["ips"] == ["93.184.216.34"] and p["paths"] == ["/docs/deep"]


# --- §4: the Master's word is always the next turn ---------------------------
def _realm(space, monkeypatch):
    monkeypatch.setattr("mor.engine.dome.probe_runtime", lambda: "")
    return Realm(space, echo=False)


def test_a_waiting_master_word_closes_the_round_early(space, monkeypatch):
    r = _realm(space, monkeypatch)
    r.light()
    r.backend = ScriptBackend([
        {"text": "General, weigh this with me."},      # the Wizard's catch
        {"text": "Master — where we stand so far."},   # the honest early close
    ])
    r.pending_master = lambda: True  # the Master typed mid-round
    r.master_says("Ponder this at length.")
    tail = [(e["speaker"], e["addressee"]) for e in r.hall.entries()[-3:]]
    assert tail == [("master", None), ("wizard", "general"), ("general", "master")]
    assert "waiting" in r.hall.entries()[-1]["text"]
    r.dark()


def test_no_waiting_word_means_a_full_round(space, monkeypatch):
    r = _realm(space, monkeypatch)
    r.light()
    r.backend = ScriptBackend([
        {"text": "A plain errand — Warrior, go."},
        {"text": "Done. General, reporting."},
        {"text": "Master — it is done. Your word?"},
    ])
    r.pending_master = lambda: False
    r.master_says("Run the errand.")
    tail = [(e["speaker"], e["addressee"]) for e in r.hall.entries()[-4:]]
    assert tail == [("master", None), ("wizard", "warrior"),
                    ("warrior", "general"), ("general", "master")]
    assert "waiting" not in r.hall.entries()[-1]["text"]
    r.dark()


# --- the shell's dispatch, driven directly -----------------------------------
def test_dispatch_commands_and_quiet_text(space, monkeypatch, capsys):
    from mor.cli import _dispatch
    r = _realm(space, monkeypatch)
    assert _dispatch(r, "authorize example.com") is True
    assert space.egress_allowed("example.com")
    assert _dispatch(r, "some thought typed while asleep") is True
    assert "asleep" in capsys.readouterr().out
    assert _dispatch(r, "light") is True and r.awake
    assert _dispatch(r, "dark") is True and not r.awake
    assert _dispatch(r, "quit") is False
