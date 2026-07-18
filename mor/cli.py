"""``mor`` — the command line into the harness.

Run ``mor`` with no arguments for the interactive shell: type a task and the crew
works on it; slash-commands configure things. Or run one task headless:

    mor run "summarize the files in the workspace"

Configure the model endpoint once (or via MOR_BASE_URL / MOR_MODEL env vars):

    mor config --base-url http://localhost:8080/v1 --model my-model
"""

from __future__ import annotations

import sys

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
  {ui.cyan('/agents')}           list the crew and who can reach the web
  {ui.cyan('/allow')} <domain>   open web access for a domain (or {ui.cyan('*')} for all public sites)
  {ui.cyan('/allow')}            show the current allowlist
  {ui.cyan('/deny')} <domain>    close a domain again
  {ui.cyan('/note')} <text>      add a durable project note (memory across sessions)
  {ui.cyan('/notes')}            show the project notes
  {ui.cyan('/model')}            show how MoRE reaches the model
  {ui.cyan('/project')} [name]   show, switch, or create the current project
  {ui.cyan('/crew')} init        write an editable crew.json you can customize
  {ui.cyan('/help')}             this
  {ui.cyan('/quit')}             leave
"""


def _cmd_allow(project, rest: str) -> None:
    if not rest:
        al = project.allowlist()
        print(ui.dim("  allowed: " + (", ".join(al) if al else "(nothing — the web is closed)")))
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


def _cmd_model() -> None:
    cfg = endpoint()
    if cfg["base_url"]:
        print(ui.dim(f"  model: {cfg['model']} @ {cfg['base_url']}  "
                     f"(shell {'on' if cfg['allow_shell'] else 'off'})"))
    else:
        print(ui.dim("  offline stand-in — no endpoint set. Point at a model with:"))
        print(ui.dim("    mor config --base-url http://localhost:8080/v1 --model <name>"))
        print(ui.dim("  or export MOR_BASE_URL / MOR_MODEL for one run."))


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


def _config_from_args(argv: list) -> int:
    """`mor config [--base-url U] [--model M] [--api-key K] [--allow-shell|--no-shell]`"""
    if not argv:
        _cmd_model()
        return 0
    updates, i = {}, 0
    flags = {"--base-url": "base_url", "--model": "model", "--api-key": "api_key",
             "--max-tokens": "max_tokens", "--temperature": "temperature"}
    while i < len(argv):
        a = argv[i]
        if a in flags and i + 1 < len(argv):
            val = argv[i + 1]
            if a == "--max-tokens":
                val = int(val)
            elif a == "--temperature":
                val = float(val)
            updates[flags[a]] = val
            i += 2
        elif a == "--allow-shell":
            updates["allow_shell"] = True
            i += 1
        elif a == "--no-shell":
            updates["allow_shell"] = False
            i += 1
        else:
            print(ui.yellow(f"  unknown option: {a}"))
            return 2
    set_config(**updates)
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
    elif cmd == "agents":
        _cmd_agents(project)
    elif cmd == "allow":
        _cmd_allow(project, rest)
    elif cmd == "deny":
        _cmd_deny(project, rest)
    elif cmd == "model":
        _cmd_model()
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


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(BANNER + "\n" + HELP)
        return 0
    if argv and argv[0] == "config":
        return _config_from_args(argv[1:])
    if argv and argv[0] == "run":
        task = " ".join(argv[1:]).strip()
        if not task:
            print(ui.yellow("usage: mor run \"<task>\""))
            return 2
        Session(load_project()).run_task(task)
        return 0
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
