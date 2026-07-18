"""The hands — what a face can actually do, beyond speaking.

A small, real toolset a face acts through inside the loop. Each tool returns a
plain observation string the face reads on its next turn.

Egress is a single chokepoint, and the two rails are enforced here, not asked for:
  - `run_shell` runs inside a face's container body, which sits on the INTERNAL
    dome (no route out) — so a shell, the Warrior's included, is kernel-air-gapped
    and cannot reach the internet at all.
  - `web_fetch` is therefore the realm's ONLY way out. It is Warrior-only, gated
    per-domain (the Master must `authorize` the domain), SSRF-guarded (it opens
    onto the public web, never the host's loopback/LAN or cloud metadata), and it
    taints the turn (the Eighth Evangelism) so the realm can require the Master's
    leave before acting on what came back.

web_fetch runs in the opus process (the host), not in a body — which is exactly
why the SSRF guard matters: without it, an open gate would reach the host's own
network. With it, an open gate reaches only the public internet.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


@dataclass
class ToolContext:
    workspace: Path
    space: object = None          # carries the gate (egress_allowed / allowlist)
    can_egress: bool = False      # only the Warrior's body may reach the outside
    tainted: list = field(default_factory=list)  # domains pulled from outside
    dome: object = None           # the bodies (Dome); None -> disembodied
    role: str = ""                # which face this context belongs to
    grimoire_touched: list = field(default_factory=list)  # (subject, id) claims logged this turn
    changed: list = field(default_factory=list)    # files written this turn (the Seventh watches)
    checked: bool = False         # a real check was run this turn (the Seventh is served)
    depth: int = 0                # 0 = the face itself; a delegated pair of hands is 1 (never deeper)
    backend: object = None        # the mind, lent to delegate (set by agents.line)
    delegations: int = 0          # hands spun up this turn (bounded — see _DELEGATION_LIMIT)
    falsify: bool = False         # the Eleventh: this turn must attack its own
                                  # conclusion once before speaking it (opt-in —
                                  # set for working turns, not ceremonial ones)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: object  # (args: dict, ctx: ToolContext) -> str

    def openai(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": self.parameters}}


def _safe(ctx: ToolContext, rel: str) -> Path:
    ctx.workspace.mkdir(parents=True, exist_ok=True)
    p = (ctx.workspace / (rel or ".")).resolve()
    if ctx.workspace.resolve() not in p.parents and p != ctx.workspace.resolve():
        raise ValueError("path escapes the workspace")
    return p


_READ_WINDOW = 8000  # chars handed back in one read; the rest is paged, never dropped
_READ_MAX_BYTES = 32_000_000  # a read never swallows a file bigger than this whole


def _read_file(args, ctx):
    p = _safe(ctx, args.get("path", ""))
    if not p.exists():
        return f"ERROR: no such file: {args.get('path')}"
    if p.is_dir():
        return f"ERROR: {args.get('path')} is a directory — use list_dir"
    # Guard the host's memory: a giant file (a body can write one into /work)
    # must not be slurped whole into the opus process.
    if p.stat().st_size > _READ_MAX_BYTES:
        return (f"ERROR: {args.get('path')} is {p.stat().st_size:,} bytes — too big "
                "to read whole. Narrow it with search_workspace, or page it with "
                "run_shell (head/tail) if you have a body.")
    try:
        offset = max(0, int(args.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    text = p.read_text("utf-8", "replace")
    chunk = text[offset:offset + _READ_WINDOW]
    remaining = len(text) - (offset + len(chunk))
    if remaining > 0:
        # No silent truncation: the face is told exactly what it hasn't seen and
        # how to page to it — a blind spot it can register, not one it can't.
        chunk += (f"\n\n[TRUNCATED: {remaining:,} characters remain. Call read_file "
                  f"with offset={offset + _READ_WINDOW} to continue.]")
    return chunk


def _looks_binary(raw: bytes) -> bool:
    return b"\x00" in raw[:1024]


def _search_workspace(args, ctx):
    """Grep across the workspace — the primitive that lets a face follow an edge
    (who calls this? where is this set?) without opening every file by hand."""
    pattern = args.get("pattern", "")
    if not pattern:
        return "ERROR: no pattern"
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return f"ERROR: bad regex: {e}"
    root = _safe(ctx, args.get("path", "."))
    if not root.exists():
        return f"ERROR: no such path: {args.get('path')}"
    base = ctx.workspace.resolve()
    results, capped = [], False
    for path in sorted(root.rglob("*") if root.is_dir() else [root]):
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > 1_000_000:
                continue
            raw = path.read_bytes()
            if _looks_binary(raw):
                continue
            text = raw.decode("utf-8", "replace")
        except OSError:
            continue
        rel = path.relative_to(base) if base in path.parents or path == base else path.name
        for i, ln in enumerate(text.splitlines(), 1):
            # Scan a bounded window of each line: a pathological regex on a
            # megabyte-long single line must not hang the realm mid-turn.
            if compiled.search(ln[:4000]):
                results.append(f"{rel}:{i}: {ln.strip()[:200]}")
                if len(results) >= 50:
                    capped = True
                    break
        if capped:
            break
    if not results:
        return "no matches"
    tail = "\n[capped at 50 matches — narrow the pattern]" if capped else ""
    return "\n".join(results) + tail


def _write_file(args, ctx):
    p = _safe(ctx, args.get("path", ""))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(args.get("content", ""))
    ctx.changed.append(args.get("path", "?"))  # the Seventh: a change to answer for
    return f"wrote {len(args.get('content', ''))} chars to {args.get('path')}"


def _list_dir(args, ctx):
    p = _safe(ctx, args.get("path", "."))
    if not p.exists():
        return "(empty)"
    return "\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir())) or "(empty)"


def _resolve_public(host: str):
    """Resolve `host` and judge its addresses. Returns (ips, reason): the
    resolved addresses, and '' if all are public unicast — else the reason the
    SSRF rail refuses (any private/loopback/link-local/reserved/multicast). The
    ips come back so the world map can record where a place actually lives.

    Known limit, accepted deliberately: this is check-then-connect — the fetch
    resolves the name a second time, so a DNS server that rebinds between the two
    lookups can slip an address past the rail. Pinning the resolved address is
    ugly in pure stdlib (connect by IP, hand-set SNI and Host); until that's worth
    its weight, the rail stops honest infrastructure and mistakes, not a hostile
    resolver."""
    import ipaddress
    import socket
    ips = []
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as e:
        return [], f"could not resolve {host} ({type(e).__name__})"
    for info in infos:
        addr = info[4][0].split("%")[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        ips.append(addr)
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return ips, f"{host} resolves to a non-public address ({addr})"
    return ips, ""


def _blocked_ip(host: str) -> str:
    """'' if every address `host` resolves to is public; else the refusal reason
    (the SSRF rail: the gate opens onto the public web, never the host's own
    network or its cloud metadata endpoint at 169.254.169.254)."""
    return _resolve_public(host)[1]


def _open_one_hop(req, timeout: float):
    """Open a request WITHOUT following redirects — the gate takes one hop, never
    a chain. A redirect target is a *different* place: a domain the Master never
    authorized, or (the classic SSRF pivot) the host's own metadata endpoint — and
    both rails only ran against the URL the Warrior asked for. A 3xx surfaces as
    an HTTPError and comes back as an observation instead: the Warrior reports the
    destination, and crossing to it takes the Master's leave like anywhere else."""
    import urllib.request

    class RefuseRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None  # refuse to follow: the 3xx surfaces as an HTTPError

    return urllib.request.build_opener(RefuseRedirect).open(req, timeout=timeout)


def _deliver(status: int, domain: str, raw: bytes, ctx, ips=None, path: str = "") -> str:
    """Hand a response body to the face: tainted, and folded into the world map."""
    body = raw.decode("utf-8", "replace")
    ctx.tainted.append(domain)  # taint: it came from outside
    if ctx.space is not None:  # the Wizard's map grows from real sorties (§9)
        try:
            from mor import world
            world.record_sortie(ctx.space, domain, f"GET {status}, {len(body)} bytes",
                                ips=ips, path=path)
        except Exception:  # noqa: BLE001 — never let bookkeeping break a sortie
            pass
    return f"[{status}] {domain} — {len(body)} bytes (TAINTED):\n{body[:2000]}"


def _web_fetch(args, ctx):
    url = (args.get("url") or "").strip()
    if not url:
        return "ERROR: no url"
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"DENIED: only http(s) may cross the gate, not {parsed.scheme!r}."
    domain = (parsed.hostname or "").lower()
    if not ctx.can_egress:
        return ("DENIED: only the Warrior may leave the dome. Ask the General to "
                "send a sortie.")
    if ctx.space is None or not ctx.space.egress_allowed(domain):
        return (f"DENIED: the gate is shut for {domain}. The General must get the "
                f"Master's leave first (`authorize {domain}`).")
    # The SSRF rail: even with the gate open, the outside is the *public* web —
    # never the host's loopback, LAN, or cloud metadata. Checked before we connect.
    ips, blocked = _resolve_public(domain)
    if blocked:
        return f"DENIED: {blocked} — the gate does not open onto private networks."
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "MoR-Warrior/0.1"})
    try:
        with _open_one_hop(req, timeout=15) as r:
            return _deliver(r.status, domain, r.read(4000), ctx,
                            ips=ips, path=parsed.path or "/")
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            where = e.headers.get("Location", "(no Location given)")
            return (f"DENIED: {domain} answered {e.code} redirecting to {where} — "
                    "the gate does not follow redirects. If the sortie needs that "
                    "destination, report it: its domain needs the Master's leave too.")
        # An HTTP error is still an answer from outside — deliver it, tainted.
        try:
            raw = e.read(4000)
        except Exception:  # noqa: BLE001
            raw = b""
        return _deliver(e.code, domain, raw, ctx, ips=ips, path=parsed.path or "/")
    except Exception as e:  # noqa: BLE001
        return f"ERROR reaching {domain}: {type(e).__name__}"


def _run_shell(args, ctx):
    cmd = (args.get("command") or "").strip()
    if not cmd:
        return "ERROR: no command"
    if ctx.dome is None or not getattr(ctx.dome, "embodied", False):
        return "ERROR: you have no body to run commands in (the dome is not up)."
    ctx.checked = True  # the Seventh: something was actually run (pass or fail)
    rc, out, err = ctx.dome.exec(ctx.role, cmd)
    tail = (out or "") + (("\n" + err) if err and err.strip() else "")
    return f"[exit {rc}]\n{tail[:4000]}" if tail.strip() else f"[exit {rc}] (no output)"


# -- the grimoire: the realm's book of claims (its first subject-matter memory) --
# world.py maps the *places* the realm has touched; the grimoire holds what it has
# come to *believe* — and, unlike a narrative, a claim can be wrong, which is what
# makes a second look worth taking. These three hands write and read that book.

def _grimoire_record(args, ctx):
    if ctx.space is None:
        return "ERROR: no realm to write the grimoire in"
    subject = (args.get("subject") or "").strip()
    text = (args.get("text") or "").strip()
    if not subject or not text:
        return "ERROR: a claim needs both a subject and text"
    rung = (args.get("rung") or "inferred").strip().lower()
    from mor import grimoire
    if rung not in grimoire.RUNGS:
        return f"ERROR: rung must be one of {', '.join(grimoire.RUNGS)}"
    depends_on = args.get("depends_on") or []
    if isinstance(depends_on, str):
        depends_on = [depends_on]
    cid = grimoire.record_claim(ctx.space, subject, text, rung,
                                test=args.get("test", ""), depends_on=depends_on)
    ctx.grimoire_touched.append((subject, cid))
    return f"recorded {cid} in [{subject}] ({rung}): {text}"


def _grimoire_mark(args, ctx):
    if ctx.space is None:
        return "ERROR: no realm to write the grimoire in"
    subject = (args.get("subject") or "").strip()
    cid = (args.get("claim_id") or "").strip()
    status = (args.get("status") or "").strip().lower()
    from mor import grimoire
    if status not in grimoire.STATUSES:
        return f"ERROR: status must be one of {', '.join(grimoire.STATUSES)}"
    rung = args.get("rung")
    escalated = False
    if rung is None and getattr(ctx, "checked", False):
        # A real check ran this turn: a claim marked after it is known at least
        # by computation, whatever the face declares. The rung floors itself —
        # declared provenance can never lag the turn's own evidence.
        rung = "computed"
        escalated = True
    ok = grimoire.mark_claim(ctx.space, subject, cid, status,
                             note=args.get("note", ""), rung=rung)
    if not ok:
        return f"ERROR: no claim {cid} in [{subject}]"
    ctx.grimoire_touched.append((subject, cid))
    tail = " (rung raised to computed — a check ran this turn)" if escalated else ""
    return f"marked {cid} in [{subject}] {status}{tail}"


def _grimoire_read(args, ctx):
    if ctx.space is None:
        return "ERROR: no realm to read the grimoire from"
    from mor import grimoire
    return grimoire.dump(ctx.space, subject=(args.get("subject") or "").strip() or None)


def _map_workspace(args, ctx):
    """Rank the Python modules under a path by import-centrality — where to look
    first, before reading a single file."""
    root = _safe(ctx, args.get("path", "."))
    if not root.exists():
        return f"ERROR: no such path: {args.get('path')}"
    from mor import map_topology
    return map_topology.summary(root)


# -- the shelf: the realm's how-to notes (the Third Evangelism) --
# The grimoire holds what the realm *believes*; the shelf holds what it knows
# *how to do* — pulled whole only when the moment needs it, indexed for a line.

def _skill_load(args, ctx):
    if ctx.space is None:
        return "ERROR: no realm with a shelf"
    from mor import skills
    body = skills.load(ctx.space, args.get("name", ""))
    if body is None:
        return f"the shelf holds no skill '{args.get('name')}' — check the index"
    return body


def _skill_record(args, ctx):
    if ctx.space is None:
        return "ERROR: no realm with a shelf"
    from mor import skills
    err = skills.record(ctx.space, args.get("name", ""), args.get("body", ""))
    if err:
        return "ERROR: " + err
    return f"recorded '{args.get('name')}' on the shelf — the realm keeps the how-to"


# -- the Fourth: a clean pair of hands (subagent delegation) --
# One bounded child with a narrow brief and NO memory of the parent's turn —
# wide sub-tasks fanned out, the report folded back. The child never gets this
# tool itself: hands don't grow hands.

_DELEGATION_LIMIT = 3


def _delegate(args, ctx):
    if ctx.backend is None:
        return "ERROR: no mind to lend a pair of hands (delegate only works mid-turn)."
    if ctx.delegations >= _DELEGATION_LIMIT:
        return ("ERROR: enough hands for one turn — fold what you have, or take the "
                "rest to a later turn.")
    brief = (args.get("task") or "").strip()
    if not brief:
        return "ERROR: a delegation needs a brief"
    ctx.delegations += 1
    child = ToolContext(
        workspace=ctx.workspace, space=ctx.space, can_egress=ctx.can_egress,
        tainted=ctx.tainted, dome=ctx.dome, role=ctx.role,
        grimoire_touched=ctx.grimoire_touched,
        changed=ctx.changed,          # the Seventh counts the child's writes as yours
        depth=ctx.depth + 1, backend=ctx.backend)
    from mor.engine.loop import think_and_act
    system = (f"You are a clean pair of hands for the {ctx.role or 'realm'}. You have "
              "no memory beyond the brief below and no voice in the Hall — do exactly "
              "the brief, then report plainly and briefly what you found or did.")
    report, _ = think_and_act(ctx.backend, role=ctx.role, kind="delegate",
                              heard=brief, system=system, user=brief,
                              tools=default_tools(child), ctx=child, max_steps=5)
    if child.checked:
        ctx.checked = True  # a check the child ran counts for the turn (the Seventh)
    return report


def _frontier_exec(args, ctx):
    """Run a command in a standing colony — the sacrificial land where fetched
    ground is built and poked. A check run here serves the Seventh, as one in
    your own body does."""
    if ctx.dome is None:
        return "ERROR: no dome — the frontier is unreachable."
    name = args.get("colony", "")
    cmd = args.get("command", "")
    if not cmd:
        return "ERROR: no command"
    rc, out, err = ctx.dome.frontier_exec(name, cmd)
    if rc == 127 and err.startswith("no "):
        return f"ERROR: {err}"
    ctx.checked = True  # the Seventh: something was actually run
    return f"[rc={rc}]\n{out}{err}"[:4000]


def _recall(args, ctx):
    """Ask the realm's ground a question — territories, walls, chants, the
    shelf, the workspace — and get back the most relevant passages."""
    if ctx.space is None:
        return "ERROR: no realm to recall from"
    from mor import recall
    query = args.get("query", "")
    source = args.get("source", "all")
    try:
        k = min(max(int(args.get("k", 5)), 1), 10)
    except (TypeError, ValueError):
        k = 5
    docs = recall.load_corpus(ctx.space, source, workspace=ctx.workspace)
    hits = recall.retrieve(query, docs, k)
    if not hits:
        return f"nothing in '{source}' answers that query"
    return "\n\n".join(f"[{i + 1}] {ref} (score {s:.1f})\n{excerpt}"
                       for i, (ref, excerpt, s) in enumerate(hits))


def _ask_graph(args, ctx):
    """Ask the Ontology: hybrid retrieval (vector + lexical + graph) over
    everything the realm holds, answered with passages AND the triples that
    bind the things in them. Lazily ingests the corpus on first call —
    re-ingesting is idempotent, so later calls are cheap."""
    if ctx.space is None:
        return "ERROR: no realm to ask"
    from mor import ontology, recall
    query = args.get("query", "")
    try:
        k = min(max(int(args.get("k", 5)), 1), 10)
    except (TypeError, ValueError):
        k = 5
    conn = ontology.connect(ctx.space)
    try:
        docs = recall.load_corpus(ctx.space, "all", workspace=ctx.workspace)
        for ref, text in docs:
            ontology.ingest_text(conn, "corpus", ref, text,
                                 backend=getattr(ctx, "backend", None))
        out = ontology.ask(conn, query, k=k,
                           backend=getattr(ctx, "backend", None))
    finally:
        conn.close()
    if not out["passages"] and not out["triples"]:
        return "the graph is silent — nothing ingested answers that yet"
    parts = [f"(vectors: {out['how']})"]
    for i, p in enumerate(out["passages"]):
        parts.append(f"[{i + 1}] {p['ref']} (score {p['score']})\n{p['excerpt']}")
    if out["triples"]:
        parts.append("— the graph also knows —")
        parts.extend(f"  {t['s']} —{t['p']}→ {t['o']}" for t in out["triples"])
    return "\n\n".join(parts)


def _relate(args, ctx):
    """Assert one fact into the Ontology, deliberately: subject —predicate→
    object. Re-asserting a fact strengthens it. This is how the realm's map
    of what-is gains depth — by its inhabitants naming what they learned."""
    if ctx.space is None:
        return "ERROR: no realm to hold the fact"
    from mor import ontology
    conn = ontology.connect(ctx.space)
    try:
        return ontology.relate(conn, args.get("subject", ""),
                               args.get("predicate", ""), args.get("object", ""),
                               day=int(args.get("day", 0) or 0))
    finally:
        conn.close()


def default_tools(ctx: ToolContext) -> list:
    ts = [
        Tool("read_file", "Read a file in your workspace. Pass offset to page "
             "past a truncation notice and read further into a long file.",
             {"type": "object", "properties": {"path": {"type": "string"},
                                               "offset": {"type": "integer"}},
              "required": ["path"]}, _read_file),
        Tool("write_file", "Write a file in your workspace.",
             {"type": "object", "properties": {"path": {"type": "string"},
                                               "content": {"type": "string"}},
              "required": ["path", "content"]}, _write_file),
        Tool("list_dir", "List a directory in your workspace.",
             {"type": "object", "properties": {"path": {"type": "string"}}}, _list_dir),
        Tool("search_workspace", "Search your workspace for a regex pattern "
             "(returns path:line: text). Find who calls a function, or where a "
             "name is set, without opening every file.",
             {"type": "object", "properties": {"pattern": {"type": "string"},
                                               "path": {"type": "string"}},
              "required": ["pattern"]}, _search_workspace),
        Tool("grimoire_record", "Record a claim in the grimoire — the realm's book "
             "of beliefs. rung is how you know it: inferred, observed, computed, or "
             "executed. Give a test that would prove it wrong, and depends_on for "
             "claim ids it leans on.",
             {"type": "object", "properties": {
                 "subject": {"type": "string"}, "text": {"type": "string"},
                 "rung": {"type": "string",
                          "enum": ["inferred", "observed", "computed", "executed"]},
                 "test": {"type": "string"},
                 "depends_on": {"type": "array", "items": {"type": "string"}}},
              "required": ["subject", "text", "rung"]}, _grimoire_record),
        Tool("grimoire_mark", "Mark a claim tested: held (it survived), broken (it "
             "failed), or unchecked. Optionally raise its rung and leave a note.",
             {"type": "object", "properties": {
                 "subject": {"type": "string"}, "claim_id": {"type": "string"},
                 "status": {"type": "string",
                            "enum": ["held", "broken", "unchecked"]},
                 "note": {"type": "string"}, "rung": {"type": "string"}},
              "required": ["subject", "claim_id", "status"]}, _grimoire_mark),
        Tool("grimoire_read", "Read the grimoire — one subject's claims, or the "
             "list of subjects if none is named.",
             {"type": "object", "properties": {"subject": {"type": "string"}}},
             _grimoire_read),
        Tool("map_workspace", "Rank the Python modules under a path by import-"
             "centrality (most imported first) — where to look first in an "
             "unfamiliar codebase.",
             {"type": "object", "properties": {"path": {"type": "string"}}},
             _map_workspace),
        Tool("skill_load", "Pull the full body of a how-to note from the shelf "
             "(you carry only its index line; load it when the moment needs it).",
             {"type": "object", "properties": {"name": {"type": "string"}},
              "required": ["name"]}, _skill_load),
        Tool("skill_record", "Write a how-to note onto the shelf — a hard-won "
             "lesson the realm should never have to learn twice. name plus the "
             "markdown body.",
             {"type": "object", "properties": {"name": {"type": "string"},
                                               "body": {"type": "string"}},
              "required": ["name", "body"]}, _skill_record),
    ]
    if ctx.depth == 0:  # hands don't grow hands
        ts.append(Tool(
            "delegate", "Spin up a clean pair of hands with a narrow brief (it "
            "knows nothing of this conversation) for one bounded sub-task; its "
            "final report comes back to you. Up to three per turn.",
            {"type": "object", "properties": {"task": {"type": "string"}},
             "required": ["task"]}, _delegate))
    ts.append(Tool(
        "recall", "Ask the realm's ground a question (territories, walls, "
        "chants, the shelf, your workspace) and get the most relevant passages "
        "back, with where they live. Retrieval, not memory: the ground answers.",
        {"type": "object", "properties": {
            "query": {"type": "string"},
            "source": {"type": "string", "description": "workspace · territories · "
                       "walls · chants · skills · all (default)"},
            "k": {"type": "integer", "description": "how many passages, 1-10 (default 5)"}},
         "required": ["query"]}, _recall))
    ts.append(Tool(
        "frontier_exec", "Run a shell command inside a standing colony — the "
        "sacrificial land where fetched ground is built and poked. colony plus "
        "command.",
        {"type": "object", "properties": {"colony": {"type": "string"},
                                          "command": {"type": "string"}},
         "required": ["colony", "command"]}, _frontier_exec))
    if ctx.dome is not None and getattr(ctx.dome, "embodied", False):
        ts.append(Tool(
            "run_shell", "Run a shell command inside your own body (a container on "
            "the dome). No body can reach the outside — the only way out is the "
            "Warrior's web_fetch, through the gate.",
            {"type": "object", "properties": {"command": {"type": "string"}},
             "required": ["command"]}, _run_shell))
    if ctx.space is not None:
        ts.append(Tool(
            "ask_graph", "Ask the Ontology — the realm's knowledge graph with a "
            "vector memory: the most relevant passages PLUS the facts (subject "
            "—predicate→ object) binding the things in them. Deeper than recall.",
            {"type": "object", "properties": {
                "query": {"type": "string"},
                "k": {"type": "integer", "description": "passages, 1-10 (default 5)"}},
             "required": ["query"]}, _ask_graph))
        ts.append(Tool(
            "relate", "Assert one fact into the Ontology: subject, predicate, "
            "object. Name what you learned so the realm never has to learn it "
            "twice. Re-asserting strengthens.",
            {"type": "object", "properties": {
                "subject": {"type": "string"},
                "predicate": {"type": "string", "description": "short verb phrase, "
                              "e.g. 'uses', 'is_a', 'wrote', 'guards'"},
                "object": {"type": "string"},
                "day": {"type": "integer"}},
             "required": ["subject", "predicate", "object"]}, _relate))
        # The forge's yield: tools the realm wrote for itself stand beside the
        # built-ins, under the same rails (same ToolContext, same guards).
        from mor import forge as _forge_mod
        for t in _forge_mod.load_forged(ctx.space, Tool):
            if all(t.name != b.name for b in ts):
                ts.append(t)
    if ctx.can_egress:
        ts.append(Tool(
            "web_fetch", "Fetch a URL from outside the dome (Warrior only; the "
            "General must have opened the gate for its domain).",
            {"type": "object", "properties": {"url": {"type": "string"}},
             "required": ["url"]}, _web_fetch))
    return ts


def execute(tools: list, call, ctx: ToolContext) -> str:
    by_name = {t.name: t for t in tools}
    t = by_name.get(call.name)
    if t is None:
        return f"ERROR: no such tool '{call.name}'"
    try:
        args = json.loads(call.arguments or "{}")
    except json.JSONDecodeError:
        return "ERROR: arguments were not valid JSON"
    try:
        return t.fn(args, ctx)
    except Exception as e:  # noqa: BLE001
        return f"ERROR in {call.name}: {type(e).__name__}: {e}"
