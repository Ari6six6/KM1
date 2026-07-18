"""`opus` — the door into the realm.

Start it with no arguments to open the shell. Inside: `light` (or `1`) breaks a
new day and beams you in; type anything to speak into the Hall; `dark` (or `0`)
ends the day. `gpu ssh <ssh… -L port:host:port>` opens the tunnel to your model
and points the realm at it in one command; until then it runs on the built-in
offline mind so you can watch it move on first clone.
"""

from __future__ import annotations

import atexit
import os
import shlex
import subprocess
import sys
import threading
import time

from mor import checkpoint, directives, ui
from mor.config import (Space, current_space_name, gpu_state_path, load_json,
                        load_space, save_json, spaces_root, use_space,
                        valid_space_name)
from mor.realm import Realm

BANNER = f"""{ui.bold(ui.magenta('  MoRE — Masters of the Realm'))}
{ui.dim('  a dome of embodied agents; you sit on top of it.')}
{ui.dim('  light / 1  → break a day      dark / 0  → end it')}
{ui.dim('  gpu · space · authorize <domain> · help · quit')}
"""

HELP = f"""{ui.bold('Commands')}
  {ui.cyan('light')} / {ui.cyan('1')}      break a new day — wake the realm and beam in
  {ui.cyan('dark')} / {ui.cyan('0')}       end the day — walls written, the Chant sung, sleep
  {ui.cyan('<text>')}          (while awake) speak into the Hall — the Wizard catches it
  {ui.cyan('authorize')} <d>   open the gate for a domain (the Master's leave to egress)
  {ui.cyan('gpu')} ...         ssh <ssh…> (detect+serve+tunnel) · model [key] · test · status · down
  {ui.cyan('persona')} <role>  write who a face is — wizard · general · warrior (seed → yours)
  {ui.cyan('space')} ...       (show) · use <name> · new <name> · list
  {ui.cyan('checkpoint')}      list snapshots · take [label] · restore <id> (realm asleep)
  {ui.cyan('direct')} <rule>   set a standing directive (holds every turn) · (list) · drop <n>
  {ui.cyan('colonize')} <name> raise a colony on the frontier · {ui.cyan('raze')} <name> pulls it down
  {ui.cyan('colonies')}        survey the frontier · {ui.cyan('territory')} <name> reads its record
  {ui.cyan('ask')} <query>     the Ontology answers — passages plus the facts that bind them
  {ui.cyan('relate')} s p o    assert a fact into the graph by hand (subject predicate object)
  {ui.cyan('improve')} [brief] one night in the Forge — the Smith mutates, the suite judges (asleep only)
  {ui.cyan('forge')}           list the tools the realm has forged for itself
  {ui.cyan('juice')}           the score: tests green · tools forged · improvements kept · graph mass
  {ui.cyan('help')} / {ui.cyan('?')}       this
  {ui.cyan('quit')} / {ui.cyan('q')}       leave (ends the day first if one is lit)
"""


# A background SSH tunnel, held for the life of the shell.
_TUNNEL = None


def _tunnel_alive() -> bool:
    return _TUNNEL is not None and _TUNNEL.poll() is None


def _kill_tunnel() -> None:
    global _TUNNEL
    if _tunnel_alive():
        try:
            _TUNNEL.terminate()
        except Exception:  # noqa: BLE001 — best-effort teardown
            pass
    _TUNNEL = None


atexit.register(_kill_tunnel)


def _clear_line() -> None:
    if sys.stdout.isatty():
        sys.stdout.write("\r" + " " * 72 + "\r")
        sys.stdout.flush()


def _wait_with_bar(proc, seconds: float = 2.5, label: str = "working") -> bool:
    """Animate a progress bar for up to `seconds` while `proc` stays alive.

    Returns True if it's still alive at the end (looks good), False if it exited
    early (report the failure). On a non-tty, just waits quietly.
    """
    tty = sys.stdout.isatty()
    steps = max(1, int(seconds / 0.1))
    for i in range(steps):
        if proc.poll() is not None:
            _clear_line()
            return False
        if tty:
            sys.stdout.write("\r  " + ui.cyan(ui.bar((i + 1) / steps, label=label)))
            sys.stdout.flush()
        time.sleep(0.1)
    _clear_line()
    return proc.poll() is None


def _spinner(stop: "threading.Event", label: str) -> None:
    if not sys.stdout.isatty():
        return
    frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    i, t0 = 0, time.time()
    while not stop.is_set():
        sys.stdout.write(f"\r  {ui.cyan(frames[i % len(frames)])} {label}… "
                         f"{time.time() - t0:4.1f}s")
        sys.stdout.flush()
        i += 1
        time.sleep(0.1)
    _clear_line()


def _gpu(rest: str) -> None:
    """One command to reach your model: `gpu ssh <full ssh… with -L forward>`.

    Opens the tunnel in the background and points the realm at localhost:<port>.
    Everything else (`model`, `serve`, `off`, `status`) is a small helper around it.
    """
    global _TUNNEL
    parts = rest.split()
    sub = parts[0].lower() if parts else "status"
    state = load_json(gpu_state_path(), {})

    if sub == "ssh":
        from mor import gpu as gpumod
        from mor.models import get_spec
        ssh_args = parts[1:]
        fwd = gpumod.parse_forward(ssh_args)
        if not fwd:
            print(ui.yellow("usage: gpu ssh <ssh args including -L localport:host:remoteport>"))
            print(ui.dim("  e.g. gpu ssh -p 11808 root@87.102.11.146 -L 8080:localhost:8080"))
            return
        local_port, _rhost, rport = fwd
        cargs = gpumod.conn_args(ssh_args)
        spec = get_spec(state.get("model_id"))

        # 1. reach the box
        print(ui.dim("  reaching the box…"))
        ok, why = gpumod.check_connection(cargs)
        if not ok:
            print(ui.red("  can't reach the box: ") + ui.dim(why))
            return
        # 2. detect GPUs + plan the tier (fails clearly if the box is too small)
        try:
            gpus = gpumod.detect_gpus(cargs)
            tp, max_len, util, total_gb = gpumod.plan(gpus, spec)
        except gpumod.ProvisionError as e:
            print(ui.red("  " + str(e)))
            return
        print(ui.green(f"  {len(gpus)}× GPU · {total_gb}GB VRAM") + ui.dim(
            f"  ({', '.join(n for n, _ in gpus)})"))
        print(ui.dim(f"  serving {spec.label}") + ui.dim(f" · context {max_len} · port {rport}"))
        # 3. install the runtime + launch the server on the box. If the box-side
        # port is squatted on (vast.ai loves 8080), the launch slides to a free
        # one on its own — and the tunnel forward follows it below.
        try:
            new_rport = gpumod.launch(cargs, spec, tp, max_len, util, rport,
                                      print, auto_port=True)
        except gpumod.ProvisionError as e:
            print(ui.red("  " + str(e)))
            return
        if new_rport != rport:
            ssh_args = gpumod.replace_forward(ssh_args, new_rport)
            print(ui.dim(f"  tunnel follows the slide: -L {local_port}:localhost:{new_rport}"))
        # 4. open the tunnel (headless: no stdin fight, no host-key prompt)
        _kill_tunnel()
        cmd = ["ssh", "-N",
               "-o", "StrictHostKeyChecking=accept-new",
               "-o", "BatchMode=yes",
               "-o", "ServerAliveInterval=30",
               "-o", "ExitOnForwardFailure=yes",
               "-o", "ConnectTimeout=15"] + ssh_args
        try:
            _TUNNEL = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except FileNotFoundError:
            print(ui.red("  ssh not found on PATH."))
            return
        if _wait_with_bar(_TUNNEL, seconds=2.5, label="opening tunnel") is False:
            err = ""
            try:
                err = (_TUNNEL.stderr.read() or b"").decode("utf-8", "replace").strip()
            except Exception:  # noqa: BLE001
                pass
            _TUNNEL = None
            print(ui.red("  ⛓  tunnel failed to come up."))
            if err:
                print(ui.dim("     " + err.splitlines()[-1][:200]))
            return
        # 5. wait for weights to load and the endpoint to answer
        ready = gpumod.wait_ready(cargs, local_port, spec, print)
        base_url = f"http://localhost:{local_port}/v1"
        state.update(base_url=base_url, served=True, model=spec.served_name,
                     model_id=spec.key, ssh_conn=cargs, local_port=local_port)
        save_json(gpu_state_path(), state)
        if ready:
            print(ui.green(f"  ⛓  the oracle is awake at {base_url}") + ui.dim(
                f"  (model: {spec.served_name}) — takes the throne at next `light`."))
        else:
            print(ui.yellow("  tunnel up and the server is launching, but it didn't answer "
                            "in time — weights may still be loading."))
            print(ui.dim("     check with `gpu test` or `gpu status` in a few minutes."))
    elif sub in ("test", "ping"):
        if not state.get("served"):
            print(ui.yellow("  no served oracle — `gpu ssh <ssh… -L port:host:port>` first."))
            return
        from mor.engine import ServedBackend
        stop = threading.Event()
        th = threading.Thread(target=_spinner, args=(stop, "knocking on the oracle"),
                              daemon=True)
        th.start()
        try:
            res = ServedBackend(state).chat(
                [{"role": "system", "content": "You are a terse test probe."},
                 {"role": "user", "content": "Reply with exactly one word: pong"}])
            reply = res.content or "(no content)"
        finally:
            stop.set()
            th.join(timeout=1)
        print("  " + ui.green("oracle answered: ") + reply[:400])
    elif sub in ("model", "models"):
        from mor.models import CATALOG, get_spec
        if len(parts) < 2:
            cur = state.get("model_id", "glm")
            for k, s in CATALOG.items():
                mark = ui.green("→") if k == cur else " "
                print(f"  {mark} {ui.cyan(k):22} {ui.dim(s.label)}")
            print(ui.dim("  pick:  gpu model <key>  (served on the next `gpu ssh …`)"))
            return
        key = parts[1]
        if key not in CATALOG:
            print(ui.yellow(f"unknown model '{key}' — one of: {', '.join(CATALOG)}"))
            return
        spec = get_spec(key)
        state.update(model_id=key, model=spec.served_name)
        save_json(gpu_state_path(), state)
        print(ui.green(f"  model → {spec.label}"))
        print(ui.dim(f"  needs ~{spec.min_total_gb}GB VRAM · {spec.weights_note}"))
    elif sub == "serve":  # manual: point at an already-reachable url
        if len(parts) < 2:
            print(ui.yellow("usage: gpu serve <base_url> [model]"))
            return
        state.update(base_url=parts[1].rstrip("/"), served=True,
                     model=parts[2] if len(parts) > 2 else state.get("model", "default"))
        save_json(gpu_state_path(), state)
        print(ui.green(f"  the oracle is served at {state['base_url']}. Throne at next `light`."))
    elif sub == "down":  # stop the server on the box AND drop the tunnel
        cargs = state.get("ssh_conn")
        if cargs:
            from mor import gpu as gpumod
            print(ui.dim("  stopping the model server on the box…"))
            gpumod.stop(cargs)
        _kill_tunnel()
        state["served"] = False
        save_json(gpu_state_path(), state)
        print(ui.dim("  server stopped, tunnel down — the realm falls back to the offline mind."))
    elif sub in ("off", "detach"):  # just drop the tunnel; leave the server running
        _kill_tunnel()
        state["served"] = False
        save_json(gpu_state_path(), state)
        print(ui.dim("  tunnel down — offline mind. (server left running; `gpu down` stops it.)"))
    else:  # status
        if state.get("served"):
            live = "tunnel live" if _tunnel_alive() else "no tunnel process in this shell"
            print(ui.dim(f"  served: {state.get('base_url')} "
                         f"(model: {state.get('model')}) — {live}"))
        else:
            print(ui.dim("  offline mind. `gpu ssh <ssh… -L port:host:port>` to serve your model."))


def _space(rest: str) -> None:
    parts = rest.split()
    sub = parts[0].lower() if parts else ""
    if sub in ("use", "new"):
        if len(parts) < 2:
            print(ui.yellow(f"usage: space {sub} <name>"))
            return
        if not valid_space_name(parts[1]):
            print(ui.yellow("  a space name is letters, digits, . _ - (start with "
                            "a letter or digit) — it names directories and containers."))
            return
        use_space(parts[1])
        Space(parts[1]).ensure()
        print(ui.green(f"  space → {parts[1]}"))
    elif sub == "list":
        root = spaces_root()
        names = sorted(p.name for p in root.iterdir()) if root.exists() else []
        cur = current_space_name()
        print(ui.dim("  spaces: ") + ", ".join(
            (ui.bold(n) if n == cur else n) for n in names) if names
            else ui.dim("  (none yet)"))
    else:
        print(ui.dim(f"  current space: {ui.bold(current_space_name())}"))


def _edit_file(path) -> bool:
    """Open a file in the operator's editor ($VISUAL/$EDITOR), creating its dir."""
    path.parent.mkdir(parents=True, exist_ok=True)
    chosen = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    for ed in ([chosen] if chosen else []) + ["nano", "vi", "vim"]:
        try:
            subprocess.call(shlex.split(ed) + [str(path)])
            return True
        except FileNotFoundError:
            continue
    print(ui.yellow(f"  no editor found — set $EDITOR. The file is at {path}"))
    return False


def _persona(rest: str) -> None:
    """Write who each face is — seeds you shape, that the walls grow from there.

    `persona` lists the three; `persona <role>` opens it in your editor (seeding a
    default first so you never start from a blank page). Takes effect next turn —
    you can reshape a face without leaving the table.
    """
    from mor.agents import DEFAULT_PERSONAS, ROLES
    space = load_space()
    parts = rest.split()
    if not parts:
        for r in ROLES:
            p = space.persona_path(r)
            written = p.exists() and p.read_text().strip()
            tag = ui.green("written") if written else ui.dim("seed (default)")
            print(f"  {ui.GLYPH.get(r, r)}  {tag}  {ui.dim(str(p))}")
        print(ui.dim("  edit one:  persona <wizard|general|warrior>"))
        return
    role = parts[0].lower()
    if role not in ROLES:
        print(ui.yellow(f"unknown face '{role}' — one of: {', '.join(ROLES)}"))
        return
    p = space.persona_path(role)
    if not (p.exists() and p.read_text().strip()):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(DEFAULT_PERSONAS[role].strip() + "\n")  # a seed to shape, not a blank page
    if _edit_file(p):
        print(ui.green(f"  {role}'s persona saved — it takes on the next turn."))


def _alchemist() -> None:
    """The maker's mark — a hidden hand, not listed in help. Look and you find him."""
    m = ui.magenta
    print()
    print(m("        🜂  THE ALCHEMIST"))
    print(ui.dim("        the secret persona of the realm — the fourth who is not counted."))
    print(ui.dim("        not of the council; he takes no turn and holds no gate."))
    print(ui.dim("        he is the hand that made the dome, and does not live in it."))
    print(ui.dim("        his art is transmutation: a word into a world."))
    print(ui.dim("        his mark is fire — three strokes meeting at a point,"))
    print(ui.dim("        which is the shape of the realm itself.  see books/THE_ALCHEMIST.md"))
    print(m("        — present in every stone, seated at no table.  🜂"))
    print()


def run_demo() -> None:
    """A full scripted day for a headless smoke test — no stdin, offline mind."""
    realm = Realm(load_space(), echo=True)
    realm.light()
    realm.master_says("Let's take stock of who we are and what the world knows of us.")
    realm.master_says("Now sketch a first move for tomorrow.")
    realm.dark()


def _checkpoint(realm, rest: str) -> None:
    """The Sixth at the command line: list, take, or rewind snapshots of the space."""
    parts = rest.split()
    sub = parts[0].lower() if parts else ""
    if sub == "take":
        label = "-".join(parts[1:]) or "manual"
        sid = checkpoint.snapshot(realm.space, label)
        print(ui.green(f"  snapshot {sid} — the space is set aside")
              if sid else ui.red("  the snapshot failed"))
    elif sub == "restore":
        if realm.awake:
            print(ui.yellow("  the realm is awake — seal the day (`dark`) before "
                            "rewinding time."))
            return
        if len(parts) < 2:
            print(ui.yellow("usage: checkpoint restore <id>"))
            return
        ok, msg = checkpoint.restore(realm.space, parts[1])
        print(ui.green(f"  {msg}") if ok else ui.yellow(f"  {msg}"))
    else:
        snaps = checkpoint.list_snapshots(realm.space)
        if not snaps:
            print(ui.dim("  no snapshots yet — dawn and dusk keep them automatically, "
                         "or `checkpoint take`"))
        for s in snaps:
            print(ui.dim(f"    {s}"))


def _direct(realm, rest: str) -> None:
    """The First at the command line: set, list, or lift standing directives."""
    parts = rest.split()
    if not parts:
        standing = directives.all(realm.space)
        if not standing:
            print(ui.dim("  no standing directives — `direct <rule>` sets one "
                         "(e.g. direct never use curl)"))
        for i, d in enumerate(standing, 1):
            print(f"  {ui.cyan(str(i))}. {d['text']}  {ui.dim('(set ' + d.get('set', '?') + ')')}")
        return
    if parts[0].lower() in ("drop", "forget", "lift"):
        if len(parts) < 2 or not parts[1].isdigit():
            print(ui.yellow("usage: direct drop <number>"))
            return
        if directives.drop(realm.space, int(parts[1])):
            print(ui.green(f"  directive {parts[1]} is lifted."))
        else:
            print(ui.yellow(f"  no directive {parts[1]} stands."))
        return
    text = " ".join(parts)
    idx, warning = directives.add(realm.space, text)
    print(ui.green(f"  directive {idx} now stands: {text}"))
    if warning:
        print(ui.yellow(f"  note: {warning}"))
    if realm.awake and realm.hall:
        realm.hall.post("master", "general", f"A standing directive now holds: {text}")
        realm.hall.post("general", "master",
                        "Understood, Master. It stands for every turn from here.")


def _frontier(realm, cmd: str, rest: str) -> None:
    """The Frontier at the command line: colonize, raze, survey the lands."""
    from mor import territory
    from mor.engine.dome import Dome
    dome = realm.dome or Dome(realm.space)
    if cmd == "colonize":
        if not rest:
            print(ui.yellow("usage: colonize <name>"))
            return
        ok, _cname, msg = dome.colonize(rest)
        print(ui.green(f"  {msg}") if ok else ui.red(f"  {msg}"))
        if ok:
            territory.begin(realm.space, rest)
    elif cmd == "raze":
        if not rest:
            print(ui.yellow("usage: raze <name>"))
            return
        rec = territory.harvest(realm.space, rest)   # the book closes first...
        ok, msg = dome.raze(rest)                    # ...then the body falls
        print(ui.green(f"  {msg}") if ok else ui.red(f"  {msg}"))
        c = rec.get("counts", {})
        if c:
            print(ui.dim(f"  the territory holds {c.get('files', 0)} files, "
                         f"{c.get('ops', 0)} operations on record."))
    elif cmd == "colonies":
        living = dome.colonies()
        known = territory.all(realm.space)
        if living:
            print(ui.green("  standing: " + ", ".join(living)))
        if known:
            print(ui.dim("  territories: " + ", ".join(known)))
        if not living and not known:
            print(ui.dim("  the frontier is quiet — `colonize <name>` raises a land"))
    elif cmd == "territory":
        if not rest:
            print(ui.yellow("usage: territory <name>"))
            return
        print(territory.summary(realm.space, rest))


def _ask(realm, rest: str) -> None:
    """Ask the Ontology from the shell — the same fused answer the faces get."""
    if not rest:
        print(ui.yellow("usage: ask <query>"))
        return
    from mor import ontology, recall
    from mor.engine import make_backend
    backend, how = make_backend()
    conn = ontology.connect(realm.space)
    try:
        docs = recall.load_corpus(realm.space, "all",
                                  workspace=realm.space.root / "workspace")
        for ref, text in docs:
            ontology.ingest_text(conn, "corpus", ref, text, backend=backend)
        out = ontology.ask(conn, rest, k=5, backend=backend)
    finally:
        conn.close()
    print(ui.dim(f"  (mind: {how} · vectors: {out['how']})"))
    for i, p in enumerate(out["passages"]):
        print(f"  {ui.cyan(p['ref'])} {ui.dim('(score ' + str(p['score']) + ')')}")
        print("   " + p["excerpt"][:240].replace("\n", " "))
    if out["triples"]:
        print(ui.dim("  — the graph also knows —"))
        for t in out["triples"]:
            print(f"  {t['s']} {ui.magenta('—' + t['p'] + '→')} {t['o']}")
    if not out["passages"] and not out["triples"]:
        print(ui.dim("  the graph is silent — nothing ingested answers that yet"))


def _relate(realm, rest: str) -> None:
    parts = rest.split(None, 2)
    if len(parts) < 3:
        print(ui.yellow("usage: relate <subject> <predicate> <object>"))
        return
    from mor import ontology
    conn = ontology.connect(realm.space)
    try:
        print("  " + ontology.relate(conn, parts[0], parts[1], parts[2],
                                     day=realm.space.state().get("last_day", 0)))
    finally:
        conn.close()


def _improve(realm, rest: str) -> None:
    """One night in the Forge, from the shell. The realm must be asleep — the
    Smith never works under a lit day."""
    if realm.awake:
        print(ui.yellow("  the Smith works at night — `dark` first, then improve"))
        return
    from mor import juice
    from mor.engine import make_backend
    backend, how = make_backend()
    print(ui.dim(f"  the Forge opens (mind: {how})…"))
    stop = threading.Event()
    spin = threading.Thread(target=_spinner, args=(stop, "the Smith is working"),
                            daemon=True)
    spin.start()
    try:
        rec = juice.improve_cycle(realm.space, backend, brief=rest,
                                  log=lambda m: None)
    finally:
        stop.set()
        spin.join(timeout=1)
        _clear_line()
    print(ui.bold("  — the Smith's report —"))
    print("  " + (rec.get("report") or "").replace("\n", "\n  "))
    if rec.get("verdict"):
        color = ui.green if rec.get("kept") else ui.yellow
        print(color("  " + rec["verdict"]))
    if rec.get("tail") and not rec.get("kept"):
        print(ui.dim("  suite tail:\n    " + rec["tail"].replace("\n", "\n    ")))


def _forge(realm, rest: str) -> None:
    from mor import forge
    rows = forge.list_forged(realm.space)
    if not rows:
        print(ui.dim("  tools.d stands empty — nothing forged yet"))
        return
    for name, status in rows:
        color = ui.green if status == "forged and standing" else ui.red
        print(f"  {ui.cyan(name):24} {color(status)}")


def _juice(realm, rest: str) -> None:
    from mor import juice
    print(ui.dim("  weighing the realm…"))
    st = juice.juice_score(realm.space)
    g = st["graph"]
    print(ui.bold(f"  JUICE {st['score']}"))
    print(f"  tests: {ui.green(str(st['tests_green']) + ' green')}"
          + (ui.red(f" · {st['tests_red']} red") if st['tests_red'] else ""))
    print(f"  forged tools: {st['forged_tools']} · improvements kept: "
          f"{st['improvements_kept']} of {st['nights_in_forge']} nights")
    print(f"  graph: {g['entities']} entities · {g['triples']} triples · "
          f"{g['passages']} passages")


def _dispatch(realm, raw: str) -> bool:
    """One line from the Master. Returns False only when the shell should exit."""
    cmd = raw.split()[0].lower()
    rest = raw[len(cmd):].strip()
    if cmd in ("quit", "exit", "q"):
        return False
    elif cmd in ("light", "1"):
        realm.light()
    elif cmd in ("dark", "0"):
        realm.dark()
    elif cmd in ("help", "?", "h"):
        print(HELP)
    elif cmd == "gpu":
        _gpu(rest)
    elif cmd == "space":
        _space(rest)
    elif cmd in ("persona", "personas"):
        _persona(rest)
    elif cmd in ("alchemist", "🜂"):  # a hidden hand — not listed in help
        _alchemist()
    elif cmd in ("authorize", "auth"):
        if rest:
            realm.authorize(rest.split()[0])
        else:
            print(ui.yellow("usage: authorize <domain>"))
    elif cmd == "checkpoint":
        _checkpoint(realm, rest)
    elif cmd == "direct":
        _direct(realm, rest)
    elif cmd in ("colonize", "raze", "colonies", "territory"):
        _frontier(realm, cmd, rest)
    elif cmd == "ask":
        _ask(realm, rest)
    elif cmd == "relate":
        _relate(realm, rest)
    elif cmd == "improve":
        _improve(realm, rest)
    elif cmd == "forge":
        _forge(realm, rest)
    elif cmd == "juice":
        _juice(realm, rest)
    elif realm.awake:
        realm.master_says(raw)
    else:
        print(ui.dim("  the realm is asleep — `light` to wake it, `help` for more"))
    return True


def _stdin_reader(q) -> None:
    """Reads stdin forever, queueing each line for the realm — the mechanism of
    §4: the Master may speak whenever he likes, even mid-turn, and his word is
    always the next turn. `None` marks EOF (Ctrl-D / a closed pipe)."""
    while True:
        try:
            line = input()
        except (EOFError, Exception):  # noqa: BLE001 — a dead stdin ends the shell
            q.put(None)
            return
        q.put(line)


def _print_prompt(realm) -> None:
    prompt = ui.magenta("♔ you> ") if realm.awake else ui.dim("mor> ")
    sys.stdout.write(prompt)
    sys.stdout.flush()


def repl() -> None:
    realm = Realm(load_space())
    print(BANNER)
    print(ui.dim(f"  space: {current_space_name()}    ") + ui.dim("(type `help`)\n"))
    import queue as _q
    q = _q.Queue()
    realm.pending_master = lambda: not q.empty()
    threading.Thread(target=_stdin_reader, args=(q,), daemon=True).start()
    try:
        while True:
            if q.empty():
                _print_prompt(realm)
            try:
                raw = q.get()
            except KeyboardInterrupt:
                print()
                break
            if raw is None:  # EOF — stdin closed
                break
            raw = raw.strip()
            if not raw:
                continue
            try:
                if not _dispatch(realm, raw):
                    break
            except KeyboardInterrupt:
                # A Ctrl-C mid-turn (a slow oracle, a long sortie) interrupts the
                # turn, never the shell — and the day stays lit and sealable.
                print(ui.yellow("\n  (interrupted — the day is still lit; `dark` seals it)"))
            except Exception as e:  # noqa: BLE001 — the door must not die with a day lit
                print(ui.red(f"  error: {type(e).__name__}: {e}"))
    finally:
        # However the shell ends — quit, EOF, a crash elsewhere — a lit day is
        # sealed (walls, Chant, bodies harvested), never left to haunt day N+1.
        if realm.awake:
            try:
                realm.dark()
            except Exception:  # noqa: BLE001 — sealing is best-effort on the way out
                pass
        _kill_tunnel()
    print(ui.dim("  — you step off the dome —"))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("--demo", "demo"):
        run_demo()
        return 0
    if argv and argv[0] in ("-h", "--help"):
        print(BANNER + "\n" + HELP)
        return 0
    # Headless doors — cron-able, so the Forge can work while the Master sleeps:
    #   opus improve "sharpen the recall tool"   (one night, then exits)
    #   opus juice                               (the score, then exits)
    #   opus ask "what does the realm know of vast.ai?"
    if argv and argv[0] in ("improve", "juice", "ask"):
        realm = Realm(load_space())
        rest = " ".join(argv[1:])
        {"improve": _improve, "juice": _juice, "ask": _ask}[argv[0]](realm, rest)
        return 0
    repl()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
