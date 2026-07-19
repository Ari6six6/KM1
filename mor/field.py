"""The Field — the realm owns its compute.

The operator rents GPUs by the hour. The Field is the lifecycle that owns them so
he never holds a dead box or a surprise bill: **rent → provision → serve → drain →
destroy**, with a cost meter running the whole time.

It is event-sourced, and the events carry the discipline the whole project is
built toward — the facts/effects boundary:

  * an **intent** says the realm *wants* something (rent a box);
  * an **effect** is the irreversible act dispatched to the provider;
  * a **fact** records that it *demonstrably happened*, with the provider's own
    evidence (the instance id).

Renting a box is not idempotent on replay — so replay never re-executes an effect.
Instead every rent carries an **idempotency key** (``mor-rent-<project>-<n>``);
the provider dedupes on it, and on startup the Field **reconciles** against
provider ground truth. A crash between "intent: rent" and "fact: rented" therefore
resolves to **exactly one box, never two** — the wallet test.

Two providers behind one interface: ``FakeProvider`` (file-backed, deterministic —
the offline/DEMO default, and what the tests drive) and ``VastProvider`` (the real
vast.ai adapter). The real provisioning bones in ``gpu.py`` slot in as the
PROVISIONING step unchanged; this module is the state machine around them.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

from mor.config import load_json, save_json

STATES = ("cold", "renting", "provisioning", "serving", "draining", "dead")


# ==========================================================================
# providers
# ==========================================================================
class Provider:
    name = "provider"

    def rent(self, spec: dict, *, key: str) -> dict:
        """Rent an instance. **Idempotent by key**: the same key returns the same
        instance, never a second box. Returns an instance dict with at least
        ``id``, ``label`` (= key), and ``rate_per_hour``."""
        raise NotImplementedError

    def status(self, instance_id: str) -> str:
        raise NotImplementedError

    def destroy(self, instance_id: str) -> None:
        raise NotImplementedError

    def list_instances(self) -> list:
        """Provider ground truth: the instances that actually exist right now."""
        raise NotImplementedError


class FakeProvider(Provider):
    """A deterministic, file-backed stand-in — the offline/DEMO provider and the
    one the tests drive. The file *is* the external ground truth that survives a
    Field crash, exactly as a real provider's servers would."""

    name = "fake"

    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> dict:
        return load_json(self.path, {"instances": {}, "by_key": {}})

    def rent(self, spec: dict, *, key: str) -> dict:
        d = self._load()
        if key in d["by_key"]:                       # idempotent — one box per key
            return d["instances"][d["by_key"][key]]
        iid = "fake-" + os.urandom(3).hex()
        inst = {"id": iid, "label": key, "provider": "fake", "state": "serving",
                "rate_per_hour": float(spec.get("rate_per_hour", 0.40))}
        d["instances"][iid] = inst
        d["by_key"][key] = iid
        save_json(self.path, d)
        return inst

    def status(self, instance_id: str) -> str:
        return self._load()["instances"].get(instance_id, {}).get("state", "gone")

    def destroy(self, instance_id: str) -> None:
        d = self._load()
        if instance_id in d["instances"]:
            d["instances"][instance_id]["state"] = "destroyed"
            d["by_key"] = {k: v for k, v in d["by_key"].items() if v != instance_id}
            save_json(self.path, d)

    def list_instances(self) -> list:
        return [i for i in self._load()["instances"].values() if i["state"] != "destroyed"]


class VastProvider(Provider):
    """The real vast.ai adapter (REST over stdlib urllib, behind the API key).

    NOTE: structurally complete but **not yet validated against the live
    service** — like the model catalog, treat endpoints as aspirational until a
    real rent has been run. The label carries the idempotency key so
    ``list_instances`` can reconcile; vast has no server-side idempotency, so
    ``rent`` first lists and reuses any instance already tagged with the key.
    """

    name = "vast"
    BASE = "https://console.vast.ai/api/v0"

    def __init__(self, api_key: str, timeout: float = 30):
        self.api_key = api_key
        self.timeout = timeout

    def _call(self, method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.BASE}{path}", data=data, method=method,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")

    def rent(self, spec: dict, *, key: str) -> dict:
        for inst in self.list_instances():           # reuse if the key already ran
            if inst.get("label") == key:
                return inst
        offer = spec.get("offer_id")
        payload = {"client_id": "me", "image": spec.get("image", "vllm/vllm-openai:latest"),
                   "label": key, "disk": spec.get("disk", 40)}
        resp = self._call("PUT", f"/asks/{offer}/", payload)
        iid = str(resp.get("new_contract") or resp.get("id"))
        return {"id": iid, "label": key, "provider": "vast",
                "rate_per_hour": float(spec.get("rate_per_hour", 0.0))}

    def status(self, instance_id: str) -> str:
        for inst in self.list_instances():
            if str(inst["id"]) == str(instance_id):
                return inst.get("state", "unknown")
        return "gone"

    def destroy(self, instance_id: str) -> None:
        self._call("DELETE", f"/instances/{instance_id}/")

    def list_instances(self) -> list:
        resp = self._call("GET", "/instances/")
        out = []
        for row in resp.get("instances", []):
            out.append({"id": str(row.get("id")), "label": row.get("label"),
                        "provider": "vast", "state": row.get("actual_status", "unknown"),
                        "rate_per_hour": float(row.get("dph_total", 0.0))})
        return out


def make_provider(project):
    """VastProvider if an API key is configured, else the file-backed FakeProvider
    (DEMO). Returns (provider, mode) where mode is 'vast' or 'demo'."""
    key = os.environ.get("MOR_VAST_KEY") or load_json(_config_path(), {}).get("vast_api_key")
    if key:
        return VastProvider(key), "vast"
    return FakeProvider(project.root / "field" / "fake_provider.json"), "demo"


def _config_path():
    from mor.config import config_path
    return config_path()


# ==========================================================================
# the Field
# ==========================================================================
class Field:
    """The compute lifecycle of one project, as an event log + a state machine."""

    def __init__(self, project, provider=None):
        self.project = project
        self.dir = project.root / "field"
        self.events_path = self.dir / "events.jsonl"
        self.events = self._load_events()
        if provider is not None:
            self.provider, self.mode = provider, getattr(provider, "name", "provider")
        else:
            self.provider, self.mode = make_provider(project)

    # -- event log -------------------------------------------------------
    def _load_events(self) -> list:
        if not self.events_path.exists():
            return []
        out = []
        for raw in self.events_path.read_text().splitlines():
            raw = raw.strip()
            if raw:
                try:
                    out.append(json.loads(raw))
                except ValueError:
                    continue
        return out

    def _record(self, kind: str, **payload) -> dict:
        event = {"seq": len(self.events), "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "t": time.time(), "kind": kind, **payload}
        self.events.append(event)
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a") as f:
            f.write(json.dumps(event) + "\n")
        return event

    # -- projections -----------------------------------------------------
    @property
    def state(self) -> str:
        state = "cold"
        for e in self.events:
            k, a = e["kind"], e.get("action")
            if k == "intent" and a == "rent":
                state = "renting"
            elif k == "fact" and a == "rent":
                state = "provisioning"
            elif k == "serving":
                state = "serving"
            elif k == "intent" and a == "destroy":
                state = "draining"
            elif k == "fact" and a == "destroy":
                state = "dead"
        return state

    def _rent_intents(self) -> list:
        return [e for e in self.events if e["kind"] == "intent" and e.get("action") == "rent"]

    def _fact_for(self, key: str):
        return next((e for e in self.events if e["kind"] == "fact"
                     and e.get("action") == "rent" and e.get("key") == key), None)

    def _last_rent_fact(self):
        facts = [e for e in self.events if e["kind"] == "fact" and e.get("action") == "rent"]
        return facts[-1] if facts else None

    def _last_destroy_fact(self):
        facts = [e for e in self.events if e["kind"] == "fact" and e.get("action") == "destroy"]
        return facts[-1] if facts else None

    def rent_key(self, n: int) -> str:
        return f"mor-rent-{self.project.name}-{n}"

    def current_instance(self):
        fact = self._last_rent_fact()
        if not fact:
            return None
        df = self._last_destroy_fact()
        if df and df["t"] >= fact["t"]:
            return None
        return fact["instance"]

    def cost_to_date(self) -> float:
        """Dollars spent on the current (or just-ended) box, to the cent."""
        fact = self._last_rent_fact()
        if not fact:
            return 0.0
        rate = float(fact["instance"].get("rate_per_hour", 0.0))
        df = self._last_destroy_fact()
        end = df["t"] if (df and df["t"] >= fact["t"]) else time.time()
        return round(rate * max(0.0, end - fact["t"]) / 3600.0, 2)

    # -- the effects boundary: rent exactly once -------------------------
    def _ensure_rented(self, key: str, spec: dict) -> dict:
        """Record the intent (once), dispatch the rent effect (idempotent by key),
        record the fact (once). Safe to call again after a crash — the provider
        dedupes on the key, so this never makes a second box."""
        if not any(e.get("key") == key for e in self._rent_intents()):
            self._record("intent", action="rent", key=key, spec=spec)
        instance = self.provider.rent(spec, key=key)     # idempotent
        if not self._fact_for(key):
            self._record("fact", action="rent", key=key, instance=instance)
        return instance

    def reconcile(self) -> list:
        """On startup, resolve any rent intent that has no fact against provider
        ground truth — adopting the box the effect already created rather than
        renting a second one. Returns the keys reconciled."""
        fixed = []
        for intent in self._rent_intents():
            key = intent.get("key")
            if key and not self._fact_for(key):
                self._ensure_rented(key, intent.get("spec", {}))
                fixed.append(key)
        return fixed

    # -- the lifecycle ---------------------------------------------------
    def up(self, spec: dict | None = None, *, provision=None) -> dict:
        """Acquire and serve a box. ``provision`` (a callable taking the instance)
        is where gpu.py's real provisioning slots in; the DEMO path skips it.

        Reconciles first and **adopts an existing box** rather than renting a new
        one, so calling ``up`` after a crash (or twice) never doubles the box —
        the wallet invariant holds at the lifecycle level, not just in replay."""
        spec = spec or {"rate_per_hour": 0.40}
        self.reconcile()
        instance = self.current_instance()
        if instance is None:
            key = self.rent_key(len(self._rent_intents()))
            instance = self._ensure_rented(key, spec)
        if provision is not None:
            provision(instance)
        if self.state != "serving":
            self._record("serving", instance_id=instance["id"])
        return instance

    def down(self) -> float:
        """Drain and destroy the current box; record and return the final bill."""
        instance = self.current_instance()
        if instance is None:
            return self.cost_to_date()
        self._record("intent", action="destroy", instance_id=instance["id"])
        self.provider.destroy(instance["id"])
        bill = self.cost_to_date()
        self._record("fact", action="destroy", instance_id=instance["id"], bill=bill)
        return bill

    def summary(self) -> dict:
        inst = self.current_instance()
        return {"state": self.state, "mode": self.mode,
                "instance": inst["id"] if inst else None,
                "rate_per_hour": inst["rate_per_hour"] if inst else 0.0,
                "cost": self.cost_to_date()}
