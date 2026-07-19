"""The Field — compute lifecycle, cost to the cent, and the wallet test: a crash
between intent-to-rent and fact-rented resolves to exactly one box, never two."""

from __future__ import annotations

import time

from mor.field import Field, FakeProvider, VastProvider, make_provider

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
