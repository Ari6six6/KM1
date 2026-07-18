"""The Theory of the World — the Wizard's map of everywhere the realm has reached.

The Warrior gathers the raw facts on his sorties (domains, IPs, paths, what came
back); the Wizard folds them into this persistent JSON map at dawn; the General
reads it for strategy. Plain data — a cartography of the outside, kept honest.

Per place the map holds (§9): the domain, the IPs it resolved to (services that
share an IP are known to share one), the paths touched, what came back, and the
days it was touched — visits alone lie about cadence; days don't.
"""

from __future__ import annotations

import time
from urllib.parse import urlparse

from mor.config import load_json, save_json

_MAX_PATHS = 10   # distinct paths remembered per place
_MAX_NOTES = 5    # freshest reports kept per place
_MAX_DAYS = 30    # day-cadence memory per place


def _domain_of(target: str) -> str:
    t = target.strip()
    if "://" not in t:
        t = "//" + t
    host = urlparse(t).hostname or target.strip()
    return host.lower()


def load(space) -> dict:
    return load_json(space.world_path(), {"places": {}})


def save(space, data) -> None:
    save_json(space.world_path(), data)


def record_sortie(space, target: str, note: str = "", ips=None, path: str = "") -> dict:
    """Fold one Warrior sortie into the map. Returns the place record.

    Old records (domain/visits/notes only) are upgraded in place — nothing the
    realm already knew is lost, the new ground just accretes."""
    data = load(space)
    places = data.setdefault("places", {})
    domain = _domain_of(target)
    today = time.strftime("%Y-%m-%d")
    place = places.setdefault(domain, {
        "domain": domain,
        "first_seen": today,
        "visits": 0,
        "notes": [],
    })
    # upgrade path for maps written before the full cartography
    place.setdefault("ips", [])
    place.setdefault("paths", [])
    place.setdefault("days", [])
    place["visits"] += 1
    place["last_seen"] = today
    for ip in (ips or []):
        if ip not in place["ips"]:
            place["ips"].append(ip)
    if path and path not in place["paths"] and len(place["paths"]) < _MAX_PATHS:
        place["paths"].append(path)
    if today not in place["days"]:
        place["days"] = (place["days"] + [today])[-_MAX_DAYS:]
    if note:
        place["notes"] = (place.get("notes", []) + [note])[-_MAX_NOTES:]
    save(space, data)
    return place


def _cadence(place: dict) -> str:
    days = len(place.get("days", []))
    visits = place.get("visits", 0)
    if days > 1:
        return f"{visits}× over {days} days"
    return f"{visits}×"


def _shared_ips(places: dict) -> list:
    """[(ip, [domains])] where one address hosts more than one known place —
    the spec's 'if services share an IP, that's known'."""
    by_ip: dict = {}
    for d, p in places.items():
        for ip in p.get("ips", []):
            by_ip.setdefault(ip, []).append(d)
    return [(ip, sorted(ds)) for ip, ds in by_ip.items() if len(ds) > 1]


def summary(space, limit: int = 6) -> str:
    """A one-line-per-place digest the faces read for strategy and sight."""
    places = load(space).get("places", {})
    if not places:
        return "the map of the outside is still blank — we have touched nothing yet"
    ranked = sorted(places.values(), key=lambda p: p.get("visits", 0), reverse=True)
    bits = []
    for p in ranked[:limit]:
        ip = f" [{p['ips'][0]}]" if p.get("ips") else ""
        bits.append(f"{p['domain']}{ip} (seen {_cadence(p)})")
    line = "known places: " + ", ".join(bits)
    shared = _shared_ips(places)
    if shared:
        line += " — shared ground: " + "; ".join(
            f"{ip} hosts {', '.join(ds)}" for ip, ds in shared[:3])
    return line


def dawn_report(space, limit: int = 6) -> str:
    """The Wizard's waking cartography: the size of the map and what moved most
    recently — so his first words can say what the realm has learned."""
    places = load(space).get("places", {})
    if not places:
        return "the map is still blank — nothing touched yet"
    last = max(p.get("last_seen", "") for p in places.values())
    touched = sorted(d for d, p in places.items() if p.get("last_seen") == last)
    report = (f"{len(places)} known place{'s' if len(places) != 1 else ''}; "
              f"last touched ({last}): {', '.join(touched[:limit])}")
    try:  # the frontier, on the same map: colonies planted, territories kept
        from mor import territory
        lands = territory.all(space)
        if lands:
            standing = [n for n in lands if territory.load(space, n).get("standing")]
            report += (f" — the frontier: {len(lands)} territor"
                       f"{'y' if len(lands) == 1 else 'ies'} known"
                       + (f", {len(standing)} standing" if standing else ""))
    except Exception:  # noqa: BLE001 — the map never breaks a waking
        pass
    return report
