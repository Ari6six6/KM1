"""The dome and the bodies — embodiment, cut from Hermes's sandbox/village.

Each face gets a real container body on a local Docker network (the dome). The
dome is `--internal` (kernel air-gap: siblings reach each other by name, nothing
reaches the internet), and EVERY body — the Warrior's included — lives on it and
nowhere else, so no shell in any body can touch the outside at all. The realm's
only egress is the `web_fetch` tool (Warrior-only, gated, SSRF-guarded), which
runs in the opus process, not in a body. DNA (lineage + relations) is written to
disk and mounted read-only: superposition a face's own code can read. Bodies die
at dusk; the harvest keeps the record.

Everything degrades gracefully: no container runtime → `embodied` is False and the
realm runs disembodied (faces use a local workspace, no shell-in-body), exactly as
before. The dome is a body for the faces, never a requirement to speak.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import time
from pathlib import Path

IMAGE = "python:3.12-slim"


def _sh(cmd: str, timeout: int = 60):
    """Run a local shell command; return (rc, stdout, stderr)."""
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           errors="replace", timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    except FileNotFoundError:
        return 127, "", "runtime not found"


def probe_runtime() -> str:
    """docker or podman if one is present and usable locally; '' otherwise."""
    for rt in ("docker", "podman"):
        rc, _, _ = _sh(f"{rt} version", timeout=15)
        if rc == 0:
            return rt
    return ""


class Dome:
    """The realm's bodies for one space. `up()` raises nothing — if there's no
    runtime it just stays disembodied."""

    def __init__(self, space, *, log=lambda *_: None):
        self.space = space
        self.log = log
        self.runtime = ""
        self.embodied = False
        self.bodies: dict[str, str] = {}  # role -> container name

    # -- names ----------------------------------------------------------
    def _slug(self, s: str) -> str:
        import re
        return re.sub(r"[^a-z0-9-]", "-", (s or "").lower()).strip("-") or "x"

    def network(self) -> str:
        return f"mor-{self._slug(self.space.name)}-dome"

    def body_name(self, role: str) -> str:
        return f"mor-{self._slug(self.space.name)}-{self._slug(role)}"

    # -- DNA (superposition on disk) ------------------------------------
    def _write_dna(self, role: str, roles: list) -> str:
        dna = self.space.root / "population" / role / "dna"
        dna.mkdir(parents=True, exist_ok=True)
        siblings = [r for r in roles if r != role]
        (dna / "lineage.json").write_text(json.dumps({
            "name": role, "space": self.space.name, "body": self.body_name(role),
            "can_egress": role == "warrior", "birth": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, indent=2) + "\n")
        (dna / "relations.json").write_text(json.dumps({
            "master": "the Master of the Realm (above the dome; speaks to the General)",
            "siblings": siblings,
            "addressable": [self.body_name(r) for r in siblings],
        }, indent=2) + "\n")
        return str(dna)

    # -- lifecycle ------------------------------------------------------
    def up(self, roles: list) -> bool:
        self.runtime = probe_runtime()
        if not self.runtime:
            self.log("  (no container runtime — the realm runs disembodied)")
            self.embodied = False
            return False
        rt, net = self.runtime, self.network()
        # The dome: internal, so nothing on it can reach the internet.
        _sh(f"{rt} network create --internal {shlex.quote(net)} 2>/dev/null || true")
        for role in roles:
            name = self.body_name(role)
            if _sh(f"{rt} ps --filter name=^{shlex.quote(name)}$ "
                   f"--format '{{{{.Names}}}}'")[1].strip() == name:
                self.bodies[role] = name
                continue  # already up (ps lists the living, not every husk)
            # A stopped namesake is a husk from a day that never saw dusk —
            # clear it so the fresh body can take the name.
            _sh(f"{rt} rm -f {shlex.quote(name)} 2>/dev/null || true")
            ws = self.space.root / "population" / role / "workspace"
            ws.mkdir(parents=True, exist_ok=True)
            dna = self._write_dna(role, roles)
            cmd = (f"{rt} run -d --name {shlex.quote(name)} "
                   f"--network {shlex.quote(net)} "
                   # A body is a leash, not a free hand: no capabilities, no
                   # privilege escalation, bounded memory/CPU/PIDs — so a shell
                   # driven sideways in a body can't starve the host it serves.
                   f"--cap-drop ALL --security-opt no-new-privileges "
                   f"--memory 512m --cpus 1 --pids-limit 256 "
                   f"--label mor.role={shlex.quote(role)} "
                   f"--label mor.space={shlex.quote(self.space.name)} "
                   f"-v {shlex.quote(str(ws))}:/work -w /work "
                   f"-v {shlex.quote(dna)}:/dna:ro "
                   f"{shlex.quote(IMAGE)} sleep infinity")
            rc, _, err = _sh(cmd, timeout=600)
            if rc != 0:
                # Never record a body that didn't rise — `bodies` must hold only
                # containers that truly exist, or the realm believes itself
                # embodied while `exec` speaks to phantoms.
                self.log(f"  body for {role} failed to rise: {err.strip()[-120:]}")
                continue
            # EVERY body stays on the internal dome — no container gets a route out,
            # so `run_shell` in any body (the Warrior's included) is kernel-air-gapped
            # and cannot reach the internet. The realm's ONLY egress is the web_fetch
            # tool (Warrior only, gated per-domain, SSRF-guarded, tainted). One gate,
            # one chokepoint — the run_shell back door is closed by construction.
            self.bodies[role] = name
            self.log(f"  {role}'s body rose on the dome as {name}")
        self.embodied = bool(self.bodies)
        return self.embodied

    def exec(self, role: str, cmd: str, timeout: int = 120):
        """Run a shell command inside a face's body. (rc, out, err)."""
        if not self.embodied or role not in self.bodies:
            return 127, "", "no body"
        rt = self.runtime
        return _sh(f"{rt} exec -w /work {shlex.quote(self.bodies[role])} "
                   f"sh -lc {shlex.quote(cmd)}", timeout=timeout)

    # -- the Frontier: colonies, a sacrificial land on the internal dome ------
    # A colony is where FETCHED things run — code carried home through the one
    # gate. It lives on the same internal network as the bodies: NO egress,
    # ever. The land is fed through the gate, never around it.

    def colony_name(self, name: str) -> str:
        return f"mor-{self._slug(self.space.name)}-frontier-{self._slug(name)}"

    def colony_dir(self, name: str) -> Path:
        return self.space.root / "colonies" / self._slug(name)

    def colonize(self, name: str, timeout: int = 600):
        """Raise a colony. Returns (ok, container_name, message)."""
        if not self.runtime:
            self.runtime = probe_runtime()
        if not self.runtime:
            return False, "", "no container runtime — the frontier cannot be raised"
        rt, net = self.runtime, self.network()
        cname = self.colony_name(name)
        _sh(f"{rt} network create --internal {shlex.quote(net)} 2>/dev/null || true")
        if _sh(f"{rt} ps --filter name=^{shlex.quote(cname)}$ "
               f"--format '{{{{.Names}}}}'")[1].strip() == cname:
            return True, cname, "the colony already stands"
        # A stopped namesake is a husk — clear it so the colony can take the name.
        _sh(f"{rt} rm -f {shlex.quote(cname)} 2>/dev/null || true")
        ws = self.colony_dir(name)
        ws.mkdir(parents=True, exist_ok=True)
        cmd = (f"{rt} run -d --name {shlex.quote(cname)} "
               f"--network {shlex.quote(net)} "
               # The same leash as a body: no caps, no escalation, bounded
               # memory/CPU/PIDs — the land serves the host, never starves it.
               f"--cap-drop ALL --security-opt no-new-privileges "
               f"--memory 512m --cpus 1 --pids-limit 256 "
               f"--label mor.colony={shlex.quote(self._slug(name))} "
               f"--label mor.space={shlex.quote(self.space.name)} "
               f"-v {shlex.quote(str(ws))}:/work -w /work "
               f"{shlex.quote(IMAGE)} sleep infinity")
        rc, _, err = _sh(cmd, timeout=timeout)
        if rc != 0:
            return False, "", f"the colony failed to rise: {err.strip()[-120:]}"
        return True, cname, f"the colony stands as {cname}"

    def colonies(self) -> list:
        """Slugs of the living colonies."""
        if not self.runtime:
            return []
        rc, out, _ = _sh(
            f"{self.runtime} ps --filter label=mor.space={shlex.quote(self.space.name)} "
            f"--filter label=mor.colony --format '{{{{.Names}}}}'")
        if rc != 0:
            return []
        return sorted(n.rsplit("-frontier-", 1)[-1] for n in out.split()
                      if "-frontier-" in n)

    def frontier_exec(self, name: str, cmd: str, timeout: int = 120):
        """Run a command in a standing colony. Returns (rc, out, err) and logs
        every operation to the colony's ops.jsonl — the territory remembers."""
        if not self.runtime:
            self.runtime = probe_runtime()
        if not self.runtime:
            return 127, "", "no container runtime"
        cname = self.colony_name(name)
        living = _sh(f"{self.runtime} ps --filter name=^{shlex.quote(cname)}$ "
                     f"--format '{{{{.Names}}}}'")[1].strip()
        if living != cname:
            return 127, "", f"no standing colony '{name}'"
        rc, out, err = _sh(f"{self.runtime} exec -w /work {shlex.quote(cname)} "
                           f"sh -lc {shlex.quote(cmd)}", timeout=timeout)
        try:
            ops = self.colony_dir(name) / "ops.jsonl"
            ops.parent.mkdir(parents=True, exist_ok=True)
            with ops.open("a") as f:
                f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                    "cmd": cmd, "rc": rc,
                                    "out": (out or err or "")[-2000:]}) + "\n")
        except OSError:
            pass  # logging never breaks the operation
        return rc, out, err

    def raze(self, name: str):
        """Pull the colony's container down. The ground (the colony dir) and its
        record (the territory module) stay — raze is never erase."""
        if not self.runtime:
            self.runtime = probe_runtime()
        if not self.runtime:
            return False, "no container runtime"
        _sh(f"{self.runtime} rm -f {shlex.quote(self.colony_name(name))} 2>/dev/null || true")
        return True, f"the colony '{self._slug(name)}' is razed — its ground and record stay"

    def down(self, roles: list | None = None) -> None:
        """Harvest then remove the bodies (bodies die nightly, the record stays)."""
        if not self.embodied:
            return
        rt = self.runtime
        for role, name in list(self.bodies.items()):
            pop = self.space.root / "population" / role
            pop.mkdir(parents=True, exist_ok=True)
            rc, out, _ = _sh(f"{rt} logs {shlex.quote(name)} 2>&1", timeout=30)
            if rc == 0 and out:
                (pop / "body.log").write_text(out[-20000:])
            _sh(f"{rt} rm -f {shlex.quote(name)} 2>/dev/null || true")
        self.bodies.clear()
        self.embodied = False
