"""watch — recurring orders that fire on schedule with no client attached."""

from __future__ import annotations

import time

import pytest

from mor.watch import (Watch, WatchStore, WatchScheduler, parse_interval,
                       run_due_watches)
from mor.order import OrderStore


def test_parse_interval():
    assert parse_interval("90s") == 90
    assert parse_interval("30m") == 1800
    assert parse_interval("6h") == 21600
    assert parse_interval("1d") == 86400
    assert parse_interval("1h30m") == 5400
    assert parse_interval("120") == 120
    for bad in ("", "soon", "0", "5x"):
        with pytest.raises(ValueError):
            parse_interval(bad)


def test_watch_is_due_only_after_its_interval():
    w = Watch(id="w", kind="research", brief="b", every=3600, last_run=1000.0)
    assert w.due(1000.0) is False
    assert w.due(1000.0 + 3599) is False
    assert w.due(1000.0 + 3600) is True


def test_store_add_list_remove(project):
    store = WatchStore(project)
    w = store.add("research", "watch the ford", 3600)
    assert [x.id for x in store.list()] == [w.id]
    assert store.remove(w.id) is True
    assert store.list() == []
    assert store.remove("nope") is False


def test_run_due_watches_fires_once_then_waits(project):
    store = WatchStore(project)
    w = store.add("research", "what changed?", 3600)
    now = time.time()
    fired = run_due_watches(project, store, now)         # never run → due
    assert len(fired) == 1
    # the fired order really delivered, with no client attached (offline)
    assert OrderStore(project).load(fired[0]).state == "delivered"
    # immediately after, it is no longer due
    assert run_due_watches(project, store, now + 1) == []
    # once the interval passes, it fires again
    assert len(run_due_watches(project, store, now + 3601)) == 1


def test_scheduler_tick_fires_a_due_watch(project):
    store = WatchStore(project)
    store.add("research", "hourly recon", 3600)
    events = []
    sched = WatchScheduler(project, store, on_event=events.append)
    fired = sched.tick()
    assert len(fired) == 1
    assert any("watch fired" in e for e in events)


def test_scheduler_start_stop_is_clean(project):
    sched = WatchScheduler(project, interval=0.01)
    sched.start()
    sched.stop()
