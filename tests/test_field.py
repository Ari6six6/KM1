"""The Field — compute lifecycle, cost to the cent, and the wallet test: a crash
between intent-to-rent and fact-rented resolves to exactly one box, never two."""

from __future__ import annotations

import time

from mor.field import Field, FakeProvider, VastProvider, make_provider, pick_offer

SPEC = {"rate_per_hour": 0.40}


def _provider(project):
    return FakeProvider(project.root / "field" / "fp.json")


def test_fake_provider_rent_is_idempotent_by_key(project):
    p = _provider(project)
    a = p.rent(SPEC, key="k1")
    b = p.rent(SPEC, key="k1")          # same key, same box
    assert a["id"] == b["id"]
    assert len(p.list_instances()) == 1


def test_lifecycle_cold_to_serving_to_dead(project):
    field = Field(project, provider=_provider(project))
    assert field.state == "cold"
    field.up(SPEC)
    assert field.state == "serving"
    assert field.current_instance() is not None
    assert len(field.provider.list_instances()) == 1
    bill = field.down()
    assert field.state == "dead"
    assert bill >= 0.0
    assert field.provider.list_instances() == []     # box destroyed at the provider


def test_cost_ledger_to_the_cent(project):
    field = Field(project, provider=_provider(project))
    field.up(SPEC)
    # pretend the box has been up for exactly half an hour
    field._last_rent_fact()["t"] = time.time() - 1800
    assert field.cost_to_date() == round(0.40 * 0.5, 2)   # $0.20, to the cent


def test_the_wallet_test_no_double_box_on_crash(project):
    """The centerpiece. A crash after the rent effect reached the provider but
    before the fact was recorded must resolve to exactly one box."""
    provider = _provider(project)
    crashed = Field(project, provider=provider)
    key = crashed.rent_key(0)
    crashed._record("intent", action="rent", key=key, spec=SPEC)
    provider.rent(SPEC, key=key)                     # the effect reached the provider
    # ...crash here: no fact recorded
    assert crashed.state == "renting"
    assert len(provider.list_instances()) == 1

    # a restarted Field reads the same log and reconciles against ground truth
    restarted = Field(project, provider=provider)
    fixed = restarted.reconcile()
    assert key in fixed
    assert restarted._fact_for(key) is not None      # the box was adopted, not re-rented
    assert restarted.state == "provisioning"
    assert len(provider.list_instances()) == 1       # STILL exactly one box


def test_up_after_a_crashed_rent_adopts_the_box_not_a_second(project):
    """The lifecycle-level wallet guard: `up` run again after a crash-mid-rent
    adopts the existing box and serves it — it does not rent a second one."""
    provider = _provider(project)
    crashed = Field(project, provider=provider)
    key = crashed.rent_key(0)
    crashed._record("intent", action="rent", key=key, spec=SPEC)
    provider.rent(SPEC, key=key)                     # box exists, no fact (the crash)

    restarted = Field(project, provider=provider)
    restarted.up(SPEC)                               # operator just runs `up` again
    assert restarted.state == "serving"
    assert len(provider.list_instances()) == 1       # adopted, never doubled


def test_reconcile_is_a_noop_when_nothing_is_pending(project):
    provider = _provider(project)
    field = Field(project, provider=provider)
    field.up(SPEC)
    fresh = Field(project, provider=provider)
    assert fresh.reconcile() == []
    assert fresh.state == "serving"
    assert len(provider.list_instances()) == 1


def test_up_after_down_rents_a_fresh_box(project):
    provider = _provider(project)
    field = Field(project, provider=provider)
    first = field.up(SPEC)["id"]
    field.down()
    second = field.up(SPEC)["id"]
    assert first != second
    assert field.state == "serving"
    assert len(provider.list_instances()) == 1       # the dead one is gone


def test_make_provider_picks_demo_then_vast(project, monkeypatch):
    monkeypatch.delenv("MOR_VAST_KEY", raising=False)
    prov, mode = make_provider(project)
    assert isinstance(prov, FakeProvider) and mode == "demo"
    monkeypatch.setenv("MOR_VAST_KEY", "secret-key")
    prov2, mode2 = make_provider(project)
    assert isinstance(prov2, VastProvider) and mode2 == "vast"


# --- V1-WIRE: offer discovery, auto-rent, SSH surfaced, provision seam --------
def test_pick_offer_chooses_the_cheapest_that_qualifies():
    offers = [
        {"id": 1, "gpu_ram": 24 * 1024, "reliability2": 0.99, "dph_total": 0.60},
        {"id": 2, "gpu_ram": 48 * 1024, "reliability2": 0.99, "dph_total": 0.40},  # winner
        {"id": 3, "gpu_ram": 16 * 1024, "reliability2": 0.99, "dph_total": 0.10},  # too small
        {"id": 4, "gpu_ram": 24 * 1024, "reliability2": 0.50, "dph_total": 0.20},  # unreliable
    ]
    pick = pick_offer(offers, {"min_gpu_ram_gb": 24, "min_reliability": 0.9})
    assert pick["offer_id"] == "2" and pick["rate_per_hour"] == 0.40
    assert pick_offer([], {}) is None
    assert pick_offer([{"id": 9, "gpu_ram": 8 * 1024, "dph_total": 0.1}],
                      {"min_gpu_ram_gb": 24}) is None


def test_fake_provider_discovers_an_offer_and_surfaces_ssh(project):
    inst = _provider(project).rent({}, key="k")      # no offer_id → discovers one
    assert inst["ssh_host"] and inst["ssh_port"] == 22222
    assert inst["rate_per_hour"] == 0.40


def test_field_up_surfaces_ssh_in_the_fact(project):
    field = Field(project, provider=_provider(project))
    field.up(SPEC)
    assert field._last_rent_fact()["instance"].get("ssh_host")


def test_field_up_calls_the_provision_seam_with_the_box(project):
    field = Field(project, provider=_provider(project))
    seen = []
    field.up(SPEC, provision=lambda inst: seen.append(inst["id"]))
    assert seen and seen[0] == field.current_instance()["id"]


def test_vast_rent_auto_discovers_and_rents_an_offer(monkeypatch):
    client = VastProvider("key")
    calls = []

    def fake_call(method, path, body=None):
        calls.append((method, path))
        if path == "/instances/":
            return {"instances": []}
        if path == "/bundles/":
            return {"offers": [
                {"id": 111, "gpu_ram": 24 * 1024, "reliability2": 0.99, "dph_total": 0.50},
                {"id": 222, "gpu_ram": 48 * 1024, "reliability2": 0.99, "dph_total": 0.30},
                {"id": 333, "gpu_ram": 8 * 1024, "reliability2": 0.99, "dph_total": 0.10}]}
        if path.startswith("/asks/"):
            return {"new_contract": 9001}
        return {}

    monkeypatch.setattr(client, "_call", fake_call)
    inst = client.rent({"min_gpu_ram_gb": 24}, key="k")
    assert inst["id"] == "9001"
    assert inst["rate_per_hour"] == 0.30            # cheapest meeting 24GB (offer 222)
    assert ("PUT", "/asks/222/") in calls
