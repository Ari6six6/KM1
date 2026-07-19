"""``mor`` — the command line into the harness.

Run ``mor`` with no arguments for the interactive shell: type a task and the crew
works on it; slash-commands configure things. Or run one task headless:

    mor run "summarize the files in the workspace"

Configure the model endpoint once (or via MOR_BASE_URL / MOR_MODEL env vars):

    mor config --base-url http://localhost:8080/v1 --model my-model
"""

from __future__ import annotations

import sys
from pathlib import Path

from mor import ui
from mor.agent import load_crew, write_default_crew
from mor.config import (Project, current_project_name, endpoint, load_project,
                        projects_root, set_config, use_project, valid_project_name)
from mor.session import Session

BANNER = f"""{ui.bold(ui.cyan('  MoRE'))} {ui.dim('— a small multi-agent harness for local models')}
{ui.dim('  type a task and the crew works on it · /help for commands · /quit to leave')}
"""

HELP = f"""{ui.bold('Commands')}
  {ui.cyan('<text>')}            give the crew a task
  {ui.cyan('/order')} <kind> <brief>   run a work order (research · build · fetch) → an artifact
  {ui.cyan('/orders')}           list orders, their state, and their artifacts
  {ui.cyan('/pull')} <id>        print an order's artifact paths (scp-ready)
  {ui.cyan('/watch')} <brief> <every>   a recurring order (e.g. 6h) · {ui.cyan('/watches')} · {ui.cyan('/unwatch')} <id>
  {ui.cyan('/status')}           is a headless daemon alive? (start one: `mor daemon`)
  {ui.cyan('/up')}               rent + serve a box (the Field) · {ui.cyan('/down')} destroy it + bill
  {ui.cyan('/field')}            the box, its state, and cost so far
  {ui.cyan('/agents')}           list the crew and who can reach the web
  {ui.dim('(the web is open by default — the crew can browse any public site freely)')}
  {ui.cyan('/allow')} <domain>   (only if you ran `config --web gated`) allowlist a domain
  {ui.cyan('/deny')} <domain>    remove a domain from the allowlist
  {ui.cyan('/note')} <text>      add a durable project note (memory across sessions)
  {ui.cyan('/notes')}            show the project notes
  {ui.cyan('/model')}            show how MoRE reaches the model
  {ui.cyan('/gpu')} ssh <ssh…>   provision + serve a model on a GPU box, in one command
  {ui.cyan('/gpu')} reconnect    reopen a dropped tunnel to the same box
  {ui.cyan('/gpu')} watch        keep the tunnel alive automatically (self-healing)
  {ui.cyan('/gpu')} model/status/off/down   pick a model · check · drop tunnel · stop box
  {ui.cyan('/ping')}             check that the model endpoint actually answers
  {ui.cyan('/project')} [name]   show, switch, or create the current project
  {ui.cyan('/crew')} init        write an editable crew.json you can customize
  {ui.cyan('/help')}             this
  {ui.cyan('/quit')}             leave
"""


def _cmd_allow(project, rest: str) -> None:
    from mor.config import web_open
    if web_open():
        print(ui.dim("  the web is open — the crew can already fetch any public site, "
                     "no allow needed."))
        print(ui.dim("  (want a whitelist instead? `mor config --web gated`, then "
                     "`mor allow <domain>`.)"))
        if not rest:
            return
    if not rest:
        al = project.allowlist()
        print(ui.dim("  allowed: " + (", ".join(al) if al else "(nothing yet)")))
        return
    opened = project.allow(rest.split()[0])
    if opened == "*":
        print(ui.yellow("  ⚠ the whole public web is now open to the crew."))
    elif opened:
        print(ui.green(f"  web is open for {opened}."))
    else:
        print(ui.yellow(f"  '{rest}' names no host — nothing opened."))


def _cmd_deny(project, rest: str) -> None:
    if not rest:
        print(ui.yellow("usage: /deny <domain>"))
        return
    if project.disallow(rest.split()[0]):
        print(ui.dim(f"  closed {rest.split()[0]}."))
    else:
        print(ui.dim(f"  {rest.split()[0]} was not open."))


def _cmd_agents(project) -> None:
    for a in load_crew(project):
        web = ui.green(" web") if a.can_egress else ""
        print(f"  {ui.cyan(a.name):16}{web} {ui.dim(a.role)}")
        print(ui.dim(f"      tools: {', '.join(a.tools)}"))


def _shell_label(cfg: dict) -> str:
    mode = cfg.get("shell", "off")
    if mode == "container":
        return f"shell: sandboxed (net {cfg.get('shell_net', 'none')})"
    if mode == "host":
        return "shell: HOST (unsandboxed)"
    return "shell: off"


def _web_label() -> str:
    from mor.config import web_open
    return "web: open (any public site)" if web_open() else "web: gated (allowlist only)"


def _cmd_model() -> None:
    cfg = endpoint()
    if cfg["base_url"]:
        print(ui.dim(f"  model: {cfg['model']} @ {cfg['base_url']}"))
        print(ui.dim(f"  {_shell_label(cfg)} · {_web_label()}"))
    else:
        print(ui.dim("  offline stand-in — no endpoint set. Reach a model with one of:"))
        print(ui.dim("    mor gpu ssh -p <port> root@<ip> -L 8080:localhost:8080   # rent+serve"))
        print(ui.dim("    mor config --base-url http://localhost:8080/v1 --model <name>"))
        print(ui.dim("  or export MOR_BASE_URL / MOR_MODEL for one run."))


def _cmd_ping() -> int:
    """Verify the model endpoint actually answers — the first thing to run after
    pointing MoRE at a remote GPU box."""
    cfg = endpoint()
    if not cfg["base_url"]:
        print(ui.yellow("  no endpoint set — nothing to ping. `mor config --base-url …` first."))
        return 1
    import time
    from mor.llm import OpenAIClient
    print(ui.dim(f"  pinging {cfg['model']} @ {cfg['base_url']} …"))
    t0 = time.time()
    res = OpenAIClient(cfg).chat(
        [{"role": "system", "content": "Reply with exactly one word: pong."},
         {"role": "user", "content": "ping"}])
    dt = time.time() - t0
    reply = (res.content or "").strip()
    if reply.startswith("(the model did not answer"):
        print(ui.red("  ✗ no answer.  ") + ui.dim(reply))
        return 1
    print(ui.green(f"  ✓ answered in {dt:.1f}s: ") + reply[:200])
    return 0


def _cmd_project(rest: str):
    parts = rest.split()
    if not parts:
        print(ui.dim(f"  current project: {ui.bold(current_project_name())}"))
        root = projects_root()
        if root.exists():
            names = sorted(p.name for p in root.iterdir() if p.is_dir())
            if names:
                print(ui.dim("  projects: " + ", ".join(names)))
        return None
    name = parts[0]
    if not valid_project_name(name):
        print(ui.yellow("  a project name is letters, digits, . _ - (start with a letter/digit)."))
        return None
    use_project(name)
    Project(name).ensure()
    print(ui.green(f"  project → {name}"))
    return load_project()


def _cmd_notes(project) -> None:
    notes = project.notes()
    print(notes if notes else ui.dim("  no notes yet — add one with /note <text>"))


def _cmd_note(project, rest: str) -> None:
    if not rest:
        print(ui.yellow("usage: /note <text>"))
        return
    import time
    p = project.notes_path
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(f"- ({time.strftime('%Y-%m-%d')}) {rest}\n")
    print(ui.dim("  noted."))


def _cmd_order(project, rest: str) -> int:
    """`order <kind> <brief>` — run a work order end to end and deliver an artifact.
    If the first word isn't a known kind (research · build · fetch), the whole line
    is taken as a research brief."""
    from mor.order import KINDS as _ORDER_KINDS
    from mor.order import run_order
    rest = rest.strip()
    if not rest:
        print(ui.yellow("usage: /order <kind> <brief>   e.g. order research \"top 3 "
                        "python http libraries, with sources\""))
        return 2
    head, _, tail = rest.partition(" ")
    if head.lower() in _ORDER_KINDS and tail.strip():
        kind, brief = head.lower(), tail.strip()
    else:
        kind, brief = "research", rest
    print(ui.dim(f"  order ({kind}): {brief}"))
    order = run_order(project, kind, brief)
    arts = order.artifacts()
    if order.state == "delivered" and arts:
        print(ui.green(f"  ✓ delivered · order {order.id}"))
        for p in arts:
            print(ui.dim(f"    {p}"))
    else:
        reason = next((e.get("reason", "") for e in reversed(order.events)
                       if e["kind"] == "failed"), "")
        print(ui.yellow(f"  ✗ {order.state} · order {order.id}  {reason}"))
    return 0


def _cmd_orders(project) -> None:
    from mor.order import OrderStore
    orders = OrderStore(project).list()
    if not orders:
        print(ui.dim("  no orders yet — run one with /order research \"…\""))
        return
    for o in orders:
        mark = ui.green(o.state) if o.state == "delivered" else (
            ui.yellow(o.state) if o.state == "failed" else ui.dim(o.state))
        brief = (o.brief[:56] + "…") if len(o.brief) > 57 else o.brief
        print(f"  {ui.cyan(o.id)}  {mark}  {ui.dim(o.kind)}  {brief}")


def _daemon_url() -> str:
    import os
    from mor.daemon import DEFAULT_HOST, DEFAULT_PORT
    return os.environ.get("MOR_DAEMON_URL", f"http://{DEFAULT_HOST}:{DEFAULT_PORT}")


def _cmd_daemon(argv: list) -> int:
    """`mor daemon [--host H] [--port N]` — run the headless daemon in the
    foreground. For the night shift: `nohup mor daemon &` (or a container)."""
    from mor.daemon import serve, DEFAULT_HOST, DEFAULT_PORT
    host, port, i = DEFAULT_HOST, DEFAULT_PORT, 0
    while i < len(argv):
        if argv[i] == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1]); i += 2
        elif argv[i] == "--host" and i + 1 < len(argv):
            host = argv[i + 1]; i += 2
        else:
            i += 1
    serve(host=host, port=port)
    return 0


def _cmd_status() -> int:
    """Is a daemon alive, and what's it holding?"""
    from mor.config import daemon_token
    from mor.daemon import DaemonClient
    url = _daemon_url()
    try:
        h = DaemonClient(url, daemon_token(), timeout=5).health()
    except Exception:  # noqa: BLE001 — unreachable daemon is a normal state, not an error
        print(ui.dim(f"  no daemon at {url} — start one with `mor daemon` "
                     "(headless: `nohup mor daemon &`)"))
        return 1
    print(ui.green(f"  ● mored up · {url}"))
    print(ui.dim(f"  project {h.get('project')} · {h.get('orders')} orders on disk"))
    return 0


def _cmd_watch(project, rest: str) -> int:
    """`watch [kind] <brief> <every>` — a recurring order the daemon runs on a
    schedule. The last token is the interval (90s · 30m · 6h · 1d); an optional
    first token is the kind (research · build · fetch)."""
    from mor.order import KINDS
    from mor.watch import WatchStore, parse_interval
    toks = rest.split()
    if len(toks) < 2:
        print(ui.yellow("usage: /watch [kind] <brief> <every>   e.g. watch "
                        "\"that repo's issues, what changed\" 6h"))
        return 2
    try:
        every = parse_interval(toks[-1])
    except ValueError as e:
        print(ui.yellow(f"  {e}"))
        return 2
    body = toks[:-1]
    if body and body[0].lower() in KINDS:
        kind, brief = body[0].lower(), " ".join(body[1:])
    else:
        kind, brief = "research", " ".join(body)
    if not brief:
        print(ui.yellow("  a watch needs a brief."))
        return 2
    w = WatchStore(project).add(kind, brief, every)
    print(ui.green(f"  watching every {toks[-1]} · {w.id}"))
    print(ui.dim("  the daemon fires it on schedule — start one with `mor daemon`."))
    return 0


def _cmd_watches(project) -> None:
    import time
    from mor.watch import WatchStore
    watches = WatchStore(project).list()
    if not watches:
        print(ui.dim("  no watches — set one with /watch <brief> <every>"))
        return
    for w in watches:
        last = "never" if not w.last_run else time.strftime("%H:%M:%S", time.localtime(w.last_run))
        brief = (w.brief[:48] + "…") if len(w.brief) > 49 else w.brief
        print(f"  {ui.cyan(w.id)}  every {w.every}s  {ui.dim(w.kind)}  last {last}  {brief}")


def _cmd_unwatch(project, rest: str) -> int:
    from mor.watch import WatchStore
    wid = rest.split()[0] if rest.strip() else ""
    if not wid:
        print(ui.yellow("usage: /unwatch <id>   (see /watches)"))
        return 2
    print(ui.dim("  removed.") if WatchStore(project).remove(wid)
          else ui.yellow(f"  no such watch: {wid}"))
    return 0


def _cmd_up(project) -> int:
    """Acquire and serve a box (the Field). Reconciles first, so a rent a crash
    left half-done is healed to exactly one box rather than doubled."""
    from mor.field import Field
    field = Field(project)
    healed = field.reconcile()
    if healed:
        print(ui.dim(f"  reconciled {len(healed)} half-rented box(es) from a prior crash"))
    if field.state == "serving":
        s = field.summary()
        print(ui.dim(f"  already up · box {s['instance']} · spent ${s['cost']:.2f}"))
        return 0
    field.up()
    s = field.summary()
    tag = ui.yellow("  (DEMO — simulated box, no real GPU)") if s["mode"] == "demo" else ""
    print(ui.green(f"  ● up · {s['state']} · box {s['instance']} · "
                   f"${s['rate_per_hour']:.2f}/hr") + tag)
    if s["mode"] == "demo":
        print(ui.dim("  set a vast.ai key (MOR_VAST_KEY or config vast_api_key) for a real box."))
    return 0


def _cmd_down(project) -> int:
    from mor.field import Field
    field = Field(project)
    if field.current_instance() is None:
        print(ui.dim("  nothing to bring down — the field is cold."))
        return 0
    bill = field.down()
    print(ui.green(f"  ● down · box destroyed · bill ${bill:.2f}"))
    return 0


def _cmd_field(project) -> int:
    from mor.field import Field
    field = Field(project)
    field.reconcile()
    s = field.summary()
    dot = ui.green("●") if s["state"] == "serving" else ui.dim("○")
    print(f"  {dot} field: {ui.bold(s['state'])} · mode {s['mode']}")
    if s["instance"]:
        print(ui.dim(f"    box {s['instance']} · ${s['rate_per_hour']:.2f}/hr · "
                     f"spent ${s['cost']:.2f} so far"))
    return 0


def _cmd_pull(project, rest: str) -> int:
    from mor.order import OrderStore
    oid = rest.split()[0] if rest.strip() else ""
    if not oid:
        print(ui.yellow("usage: /pull <order-id>   (see /orders for ids)"))
        return 2
    order = OrderStore(project).load(oid)
    if order is None:
        print(ui.yellow(f"  no such order: {oid}"))
        return 1
    arts = order.artifacts()
    if not arts:
        print(ui.dim(f"  order {oid} is {order.state} — no artifact yet."))
        return 1
    for p in arts:
        print(str(p))
    return 0


def _config_from_args(argv: list) -> int:
    """`mor config [--base-url U] [--model M] [--api-key K] [--allow-shell|--no-shell]`"""
    if not argv:
        _cmd_model()
        return 0
    updates, i = {}, 0
    flags = {"--base-url": "base_url", "--model": "model", "--api-key": "api_key",
             "--max-tokens": "max_tokens", "--temperature": "temperature",
             "--shell": "shell", "--shell-net": "shell_net", "--web": "web"}
    while i < len(argv):
        a = argv[i]
        if a in flags and i + 1 < len(argv):
            val = argv[i + 1]
            if a == "--max-tokens":
                val = int(val)
            elif a == "--temperature":
                val = float(val)
            elif a == "--shell" and val not in ("off", "container", "host"):
                print(ui.yellow("  --shell must be off, container, or host"))
                return 2
            elif a == "--shell-net" and val not in ("none", "bridge"):
                print(ui.yellow("  --shell-net must be none or bridge"))
                return 2
            elif a == "--web" and val not in ("open", "gated"):
                print(ui.yellow("  --web must be open or gated"))
                return 2
            updates[flags[a]] = val
            i += 2
        else:
            print(ui.yellow(f"  unknown option: {a}"))
            return 2
    set_config(**updates)
    if updates.get("shell") == "host":
        print(ui.yellow("  ⚠ host shell runs the model's commands directly on this "
                        "machine, unsandboxed. Prefer `--shell container`."))
    _cmd_model()
    return 0


def _dispatch(session: Session, raw: str) -> bool:
    """One line from the operator. Returns False to exit. Mutates session in place
    when the project changes."""
    if not raw.startswith("/"):
        session.run_task(raw)
        return True
    cmd, _, rest = raw[1:].partition(" ")
    cmd, rest = cmd.lower(), rest.strip()
    project = session.project
    if cmd in ("quit", "exit", "q"):
        return False
    elif cmd in ("help", "h", "?"):
        print(HELP)
    elif cmd == "order":
        _cmd_order(project, rest)
    elif cmd == "orders":
        _cmd_orders(project)
    elif cmd == "pull":
        _cmd_pull(project, rest)
    elif cmd == "watch":
        _cmd_watch(project, rest)
    elif cmd == "watches":
        _cmd_watches(project)
    elif cmd == "unwatch":
        _cmd_unwatch(project, rest)
    elif cmd == "status":
        _cmd_status()
    elif cmd == "up":
        _cmd_up(project)
    elif cmd == "down":
        _cmd_down(project)
    elif cmd == "field":
        _cmd_field(project)
    elif cmd == "agents":
        _cmd_agents(project)
    elif cmd == "allow":
        _cmd_allow(project, rest)
    elif cmd == "deny":
        _cmd_deny(project, rest)
    elif cmd == "model":
        _cmd_model()
    elif cmd == "gpu":
        from mor.gpucmd import handle
        handle(rest)
    elif cmd in ("ping", "test"):
        _cmd_ping()
    elif cmd == "notes":
        _cmd_notes(project)
    elif cmd == "note":
        _cmd_note(project, rest)
    elif cmd == "project":
        newp = _cmd_project(rest)
        if newp is not None:
            session.__init__(newp, echo=True)
    elif cmd == "crew":
        if rest == "init":
            write_default_crew(project)
            print(ui.green(f"  wrote {project.root / 'crew.json'} — edit it and it "
                           "loads next task."))
        else:
            _cmd_agents(project)
    else:
        print(ui.yellow(f"  unknown command: /{cmd}  (/help for the list)"))
    return True


def repl() -> None:
    session = Session(load_project())
    print(BANNER)
    print(ui.dim(f"  project: {current_project_name()}"))
    _cmd_model()
    print()
    while True:
        try:
            raw = input(ui.magenta("you> ") if sys.stdin.isatty() else "")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        raw = raw.strip()
        if not raw:
            continue
        try:
            if not _dispatch(session, raw):
                break
        except KeyboardInterrupt:
            print(ui.yellow("\n  (interrupted)"))
        except Exception as e:  # noqa: BLE001 — the shell must survive one bad turn
            print(ui.red(f"  error: {type(e).__name__}: {e}"))
    print(ui.dim("  — bye —"))


def _pop_workspace(argv: list) -> list:
    """Pull a leading ``-C DIR`` / ``--workspace DIR`` off the args and apply it
    as the workspace override for this process."""
    import os
    out, i = [], 0
    while i < len(argv):
        if argv[i] in ("-C", "--workspace") and i + 1 < len(argv):
            os.environ["MOR_WORKSPACE"] = str(Path(argv[i + 1]).expanduser().resolve())
            i += 2
        else:
            out.append(argv[i])
            i += 1
    return out


def main(argv=None) -> int:
    from mor import __version__
    argv = _pop_workspace(list(sys.argv[1:] if argv is None else argv))
    if argv and argv[0] in ("-h", "--help"):
        print(BANNER + "\n" + HELP)
        return 0
    if argv and argv[0] in ("-V", "--version", "version"):
        print(f"mor {__version__}")
        return 0
    if argv and argv[0] == "config":
        return _config_from_args(argv[1:])
    if argv and argv[0] == "gpu":
        from mor.gpucmd import handle
        handle(" ".join(argv[1:]))
        return 0
    if argv and argv[0] in ("ping", "test"):
        return _cmd_ping()
    if argv and argv[0] == "run":
        task = " ".join(argv[1:]).strip()
        if not task:
            print(ui.yellow("usage: mor run \"<task>\""))
            return 2
        Session(load_project()).run_task(task)
        return 0
    if argv and argv[0] == "order":
        return _cmd_order(load_project(), " ".join(argv[1:]).strip())
    if argv and argv[0] == "orders":
        _cmd_orders(load_project())
        return 0
    if argv and argv[0] == "pull":
        return _cmd_pull(load_project(), " ".join(argv[1:]).strip())
    if argv and argv[0] == "watch":
        return _cmd_watch(load_project(), " ".join(argv[1:]).strip())
    if argv and argv[0] == "watches":
        _cmd_watches(load_project())
        return 0
    if argv and argv[0] == "unwatch":
        return _cmd_unwatch(load_project(), " ".join(argv[1:]).strip())
    if argv and argv[0] in ("daemon", "mored"):
        return _cmd_daemon(argv[1:])
    if argv and argv[0] == "status":
        return _cmd_status()
    if argv and argv[0] == "up":
        return _cmd_up(load_project())
    if argv and argv[0] == "down":
        return _cmd_down(load_project())
    if argv and argv[0] == "field":
        return _cmd_field(load_project())
    if argv and argv[0] == "allow":
        _cmd_allow(load_project(), " ".join(argv[1:]).strip())
        return 0
    if argv and argv[0] == "deny":
        _cmd_deny(load_project(), " ".join(argv[1:]).strip())
        return 0
    if argv and argv[0] == "agents":
        _cmd_agents(load_project())
        return 0
    repl()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
