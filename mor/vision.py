"""The Cathedral — the realm, rendered by its own hand.

Everything the realm holds is data on disk: the Ontology's graph of what-is, the
grimoire's claims, the map of the outside, the day's Hall, the night's dream, the
Chant, the JUICE. This module folds all of it into ONE self-contained page — no
network, no dependency, stdlib only (the whole realm's promise) — so the Master,
and anyone the Master shows it to, can *see* the mind's interior at a glance:

  the Constellation — the knowledge graph as a star-chart, laid out by a
                      force-directed pass computed here in pure Python,
  the Dream        — the questions the realm asked itself in the night,
  the Hall         — the day's conversation, illuminated,
  the Grimoire     — the ledger of what it believes and how it knows it,
  the Chant        — the one song that crossed the night.

`opus cathedral` writes the standalone page; the renderer also yields just the
inner markup so it can be published as a hosted artifact. It is a mirror, not a
mind: it never invents — a blank realm renders as an honest, near-empty page.
"""

from __future__ import annotations

import html
import math
import random
import time

from mor import dream, grimoire, world
from mor.config import load_json


# ------------------------------------------------------------------ gathering
def _gather(space) -> dict:
    from mor import ontology
    conn = ontology.connect(space)
    try:
        ents = [dict(name=r[0], mentions=r[1]) for r in conn.execute(
            "SELECT name, mentions FROM entities").fetchall()]
        triples = [dict(s=r[0], p=r[1], o=r[2], w=r[3]) for r in conn.execute(
            "SELECT subject, predicate, object, weight FROM triples").fetchall()]
        gstats = ontology.stats(conn)
    finally:
        conn.close()

    st = space.state()
    day = int(st.get("last_day", 0))

    # the freshest sealed Hall
    hall_entries = []
    for d in range(day, 0, -1):
        p = space.hall_path(d)
        if p.exists():
            hall_entries = [load_json_line(ln) for ln in p.read_text().splitlines()]
            hall_entries = [e for e in hall_entries if e]
            break

    chant = ""
    for d in range(day, 0, -1):
        cp = space.chant_path(d)
        if cp.exists():
            chant = cp.read_text().strip()
            break

    return {
        "name": space.name,
        "day": day,
        "entities": ents,
        "triples": triples,
        "graph_stats": gstats,
        "grimoire": grimoire.load(space).get("subjects", {}),
        "places": world.load(space).get("places", {}),
        "hall": hall_entries,
        "chant": chant,
        "dream": dream.latest(space, day) or dream.latest(space),
        "juice": load_json(space.root / "juice.json", {}),
    }


def load_json_line(ln: str):
    import json
    try:
        return json.loads(ln)
    except Exception:  # noqa: BLE001
        return None


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


# ------------------------------------------------- force-directed graph layout
def _layout(names: list, edges: list, width: float, height: float,
            iters: int = 240, seed: int = 7) -> dict:
    """A small Fruchterman–Reingold pass — pure stdlib, deterministic. Returns
    {name: (x, y)}. The constellation lays itself out the way the realm's own
    connections pull it."""
    rnd = random.Random(seed)
    pos = {n: [rnd.uniform(0.15, 0.85) * width, rnd.uniform(0.15, 0.85) * height]
           for n in names}
    if len(names) < 2:
        return {n: (width / 2, height / 2) for n in names}
    k = math.sqrt((width * height) / len(names)) * 0.62
    temp = width / 8.0
    idx = {n: i for i, n in enumerate(names)}
    adj = [(a, b) for a, b in edges if a in idx and b in idx and a != b]
    for _ in range(iters):
        disp = {n: [0.0, 0.0] for n in names}
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
                dist = math.hypot(dx, dy) or 0.01
                f = k * k / dist
                ux, uy = dx / dist, dy / dist
                disp[a][0] += ux * f; disp[a][1] += uy * f
                disp[b][0] -= ux * f; disp[b][1] -= uy * f
        for a, b in adj:
            dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
            dist = math.hypot(dx, dy) or 0.01
            f = dist * dist / k
            ux, uy = dx / dist, dy / dist
            disp[a][0] -= ux * f; disp[a][1] -= uy * f
            disp[b][0] += ux * f; disp[b][1] += uy * f
        for n in names:
            d = math.hypot(*disp[n]) or 0.01
            pos[n][0] += disp[n][0] / d * min(d, temp)
            pos[n][1] += disp[n][1] / d * min(d, temp)
            pos[n][0] = min(width - 46, max(46, pos[n][0]))
            pos[n][1] = min(height - 40, max(40, pos[n][1]))
        temp *= 0.965
    return {n: (round(pos[n][0], 1), round(pos[n][1], 1)) for n in names}


_CLEAN_ENTITY = __import__("re").compile(
    r"^[A-Z][A-Za-z0-9.]*(?:[ \-][A-Z][A-Za-z0-9.]*)?$")


def _clean_entity(name: str) -> bool:
    """A constellation is made of bonds between *things* the realm names — not of
    the sentence fragments the offline extractor sometimes over-captures from
    prose. Keep proper-noun-shaped names (one or two Capitalized tokens, dots
    allowed for domains like Vast.ai), short enough to label a star."""
    return bool(_CLEAN_ENTITY.match(name or "")) and len(name) <= 22


def _constellation_svg(entities: list, triples: list, cap: int = 30) -> str:
    W, H = 1000.0, 620.0
    # degree from triples
    deg: dict = {}
    for t in triples:
        deg[t["s"]] = deg.get(t["s"], 0) + 1
        deg[t["o"]] = deg.get(t["o"], 0) + 1
    # only clean, connected things earn a star — ranked by how bound-in they are
    connected = {t["s"] for t in triples} | {t["o"] for t in triples}
    cand = [e for e in entities
            if e["name"] in connected and _clean_entity(e["name"])]
    ranked = sorted(cand, key=lambda e: (deg.get(e["name"], 0), e["mentions"],
                                         e["name"]), reverse=True)[:cap]
    keep = {e["name"] for e in ranked}
    edges = [(t["s"], t["o"], t["p"], t["w"]) for t in triples
             if t["s"] in keep and t["o"] in keep and t["s"] != t["o"]]
    # every star shown must carry at least one visible bond
    names = sorted({a for a, _b, _p, _w in edges} | {b for _a, b, _p, _w in edges})
    if not names:
        return ('<div class="empty">The constellation is dark — the realm has '
                'bound nothing yet. Let it <code>relate</code> a few facts, or '
                '<code>ask</code> it a question, and the stars will kindle.</div>')
    pos = _layout(names, [(a, b) for a, b, _p, _w in edges], W, H)
    # size a star by the bonds actually drawn to it, not the polluted global count
    vdeg: dict = {}
    for a, b, _p, _w in edges:
        vdeg[a] = vdeg.get(a, 0) + 1
        vdeg[b] = vdeg.get(b, 0) + 1
    deg = vdeg
    maxdeg = max(deg.get(n, 0) for n in names) or 1

    # faint background starfield (deterministic)
    rnd = random.Random(11)
    stars = "".join(
        f'<circle cx="{round(rnd.uniform(0, W),1)}" cy="{round(rnd.uniform(0, H),1)}" '
        f'r="{round(rnd.uniform(0.3, 1.2),2)}" fill="#cbb8ff" '
        f'opacity="{round(rnd.uniform(0.05, 0.28),2)}"/>'
        for _ in range(140))

    line_svg = []
    for a, b, p, w in edges:
        (x1, y1), (x2, y2) = pos[a], pos[b]
        op = min(0.5, 0.14 + 0.06 * (w or 1))
        line_svg.append(
            f'<line class="edge" data-a="{_esc(a)}" data-b="{_esc(b)}" '
            f'x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="#7c6bb0" stroke-opacity="{round(op,2)}" stroke-width="1">'
            f'<title>{_esc(a)} —{_esc(p)}→ {_esc(b)}</title></line>')

    node_svg = []
    for n in names:
        x, y = pos[n]
        d = deg.get(n, 0)
        r = 4.2 + 7.5 * (d / maxdeg)
        tier = "hub" if d >= maxdeg * 0.66 else ("mid" if d >= maxdeg * 0.33 else "leaf")
        label = n if len(n) <= 18 else n[:17] + "…"
        node_svg.append(
            f'<g class="node {tier}" data-name="{_esc(n)}">'
            f'<circle cx="{x}" cy="{y}" r="{round(r,1)}"/>'
            f'<text x="{x}" y="{round(y - r - 5,1)}">{_esc(label)}</text></g>')

    return (
        f'<svg class="constellation" viewBox="0 0 {int(W)} {int(H)}" '
        f'preserveAspectRatio="xMidYMid meet" role="img" '
        f'aria-label="The realm\'s knowledge graph as a constellation">'
        f'<defs><radialGradient id="halo" cx="50%" cy="50%" r="50%">'
        f'<stop offset="0%" stop-color="#1b1630"/>'
        f'<stop offset="100%" stop-color="#0c0a14"/></radialGradient></defs>'
        f'<rect x="0" y="0" width="{int(W)}" height="{int(H)}" fill="url(#halo)"/>'
        f'<g class="stars">{stars}</g>'
        f'<g class="edges">{"".join(line_svg)}</g>'
        f'<g class="nodes">{"".join(node_svg)}</g></svg>')


# ---------------------------------------------------------------- the sections
def _sigil() -> str:
    # three strokes meeting at a point — the alchemical fire, "the shape of the
    # realm itself" (books/THE_ALCHEMIST.md), drawn, not pasted.
    return (
        '<svg class="sigil" viewBox="0 0 80 80" aria-hidden="true">'
        '<g fill="none" stroke="#e9b866" stroke-width="1.5" stroke-linecap="round">'
        '<path d="M40 10 L40 62" opacity="0.9"/>'
        '<path d="M40 10 L14 60" opacity="0.75"/>'
        '<path d="M40 10 L66 60" opacity="0.75"/>'
        '<path d="M14 60 L66 60" opacity="0.55"/>'
        '<circle cx="40" cy="10" r="2.4" fill="#e9b866" stroke="none"/></g></svg>')


def _tiles(data: dict) -> str:
    j = data["juice"]
    gs = data["graph_stats"]
    score = j.get("score")
    green = j.get("tests_green")
    tiles = [
        ("JUICE", f"{score:g}" if score is not None else "—", "the score that compounds"),
        ("Day", str(data["day"]) if data["day"] else "—", "days the realm has lived"),
        ("Green", str(green) if green is not None else "—", "tests holding the rails"),
        ("Entities", str(gs.get("entities", 0)), "things the realm knows"),
        ("Triples", str(gs.get("triples", 0)), "facts that bind them"),
        ("Passages", str(gs.get("passages", 0)), "ground it can recall"),
    ]
    return '<div class="tiles">' + "".join(
        f'<div class="tile"><span class="tval">{_esc(v)}</span>'
        f'<span class="tkey">{_esc(k)}</span>'
        f'<span class="tsub">{_esc(sub)}</span></div>'
        for k, v, sub in tiles) + '</div>'


def _dream_section(data: dict) -> str:
    rec = data["dream"]
    if not rec or not rec.get("visions"):
        return ""
    kind_glyph = {"bridge": "⤳", "negation": "⚚", "synthesis": "✶", "quiet": "·"}
    cards = []
    for v in rec["visions"]:
        g = kind_glyph.get(v.get("kind"), "✵")
        cards.append(
            f'<li class="vision {_esc(v.get("kind",""))}">'
            f'<span class="vkind">{g} {_esc(v.get("kind",""))}</span>'
            f'<p class="vtext">{_esc(v.get("text",""))}</p>'
            f'<p class="vwhy">{_esc(v.get("why",""))}</p></li>')
    how = "voiced by the oracle" if rec.get("how") == "mind" else "spun from the graph"
    return (
        '<section class="panel dream">'
        '<div class="eyebrow">The Thirteenth · the Dreaming</div>'
        '<h2>The Dream of the Night</h2>'
        f'<p class="weave">{_esc(rec.get("woven",""))}</p>'
        f'<ul class="visions">{"".join(cards)}</ul>'
        f'<p class="attribution">— {how}; seeded into the dawn\'s grimoire, '
        'for the Warrior to chase</p></section>')


def _hall_section(data: dict) -> str:
    entries = data["hall"]
    if not entries:
        return ""
    glyph = {"master": "♔", "wizard": "✷", "general": "✦", "warrior": "⚔",
             "chant": "♪", "dream": "✵"}
    rows = []
    for e in entries[-16:]:
        sp = e.get("speaker", "")
        to = e.get("addressee")
        arrow = f'<span class="to">→ {_esc(to)}</span>' if to else ""
        rows.append(
            f'<li class="say {_esc(sp)}"><span class="who">{glyph.get(sp,"·")} '
            f'{_esc(sp.capitalize())}</span>{arrow}'
            f'<p class="line">{_esc(e.get("text",""))}</p></li>')
    return (
        '<section class="panel hall">'
        f'<div class="eyebrow">Day {data["day"]} · the shared channel</div>'
        '<h2>The Hall</h2>'
        f'<ul class="thread">{"".join(rows)}</ul></section>')


def _grimoire_section(data: dict) -> str:
    subjects = data["grimoire"]
    if not subjects:
        return ""
    rows = []
    for name, subj in subjects.items():
        for cid, c in subj.get("claims", {}).items():
            status = c.get("status", "unchecked")
            rung = c.get("rung", "inferred")
            rows.append(
                f'<tr><td class="mono cid">{_esc(cid)}</td>'
                f'<td class="subj">{_esc(name)}</td>'
                f'<td class="claim">{_esc(c.get("text",""))}</td>'
                f'<td><span class="chip rung">{_esc(rung)}</span></td>'
                f'<td><span class="chip st-{_esc(status)}">{_esc(status)}</span></td></tr>')
    if not rows:
        return ""
    return (
        '<section class="panel grimoire">'
        '<div class="eyebrow">the book of claims — belief, and how it is known</div>'
        '<h2>The Grimoire</h2>'
        '<div class="tablewrap"><table><thead><tr>'
        '<th>id</th><th>subject</th><th>claim</th><th>rung</th><th>status</th>'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>')


def _map_section(data: dict) -> str:
    places = data["places"]
    if not places:
        return ""
    ranked = sorted(places.values(), key=lambda p: p.get("visits", 0), reverse=True)
    rows = []
    for p in ranked[:10]:
        ip = p.get("ips", [""])[0] if p.get("ips") else ""
        rows.append(
            f'<li><span class="dom">{_esc(p.get("domain",""))}</span>'
            f'<span class="ip mono">{_esc(ip)}</span>'
            f'<span class="seen">seen {p.get("visits",0)}×</span></li>')
    return (
        '<section class="panel outside">'
        '<div class="eyebrow">the one egress, and where it reached</div>'
        '<h2>The Map of the Outside</h2>'
        f'<ul class="places">{"".join(rows)}</ul></section>')


def _chant_section(data: dict) -> str:
    if not data["chant"]:
        return ""
    lines = "".join(f'<span class="cl">{_esc(x.strip())}</span>'
                    for x in data["chant"].replace(" / ", "\n").splitlines() if x.strip())
    return (
        '<section class="panel chant">'
        '<div class="eyebrow">the one memory that crosses the night</div>'
        f'<div class="poem">{lines}</div></section>')


# ------------------------------------------------------------------ the page
def _inner(data: dict) -> str:
    parts = [
        '<div class="cathedral">',
        '<header class="hero">',
        _sigil(),
        '<div class="titleblock">',
        '<div class="eyebrow gold">Masters of the Realm</div>',
        '<h1>The Cathedral of <span class="rname">' + _esc(data["name"]) + '</span></h1>',
        '<p class="sub">One mind, three faces, a day from light to dark — '
        'and the questions it dreams in the night. Rendered by the realm\'s own hand.</p>',
        '</div></header>',
        _tiles(data),
        '<section class="panel constel">',
        '<div class="eyebrow">the knowledge graph — hover a star to trace its bonds</div>',
        '<h2>The Constellation</h2>',
        _constellation_svg(data["entities"], data["triples"]),
        '</section>',
        _dream_section(data),
        _hall_section(data),
        _grimoire_section(data),
        _map_section(data),
        _chant_section(data),
        '<footer class="foot"><span class="mark">🜂</span>'
        '<span>rendered by the realm\'s own hand · '
        + _esc(time.strftime("%Y-%m-%d %H:%M")) + '</span>'
        '<span class="mark">🜂</span></footer>',
        '</div>',
        _SCRIPT,
    ]
    return _STYLE + "\n" + "\n".join(p for p in parts if p)


def render(space, *, standalone: bool = True) -> str:
    data = _gather(space)
    inner = _inner(data)
    if not standalone:
        return inner
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>The Cathedral of {_esc(data['name'])}</title></head>"
            f"<body>{inner}</body></html>")


def write(space, path=None):
    from pathlib import Path
    p = Path(path) if path else (space.root / "cathedral.html")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render(space, standalone=True), "utf-8")
    return p


# ------------------------------------------------------------------- style/js
_STYLE = """<style>
html,body{background:#0c0a14 !important;margin:0}
.cathedral{
  --ink:#0c0a14; --panel:#14111f; --panel2:#191527; --line:#2a2440;
  --parchment:#e8e2d4; --faint:#9a94a8;
  --gold:#e9b866; --violet:#a88be6; --ember:#e0705a; --verdigris:#6fce9f;
  --rose:#d98fb0; --cyan:#7fd4d0;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,"Times New Roman",serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  background:var(--ink); color:var(--parchment);
  font-family:var(--serif); line-height:1.6; letter-spacing:.1px;
  max-width:1080px; margin:0 auto; padding:clamp(18px,4vw,54px);
  background-image:
    radial-gradient(1200px 600px at 15% -10%, rgba(168,139,230,.10), transparent 60%),
    radial-gradient(1000px 500px at 100% 0%, rgba(233,184,102,.07), transparent 55%);
}
.cathedral *{box-sizing:border-box}
.cathedral h1,.cathedral h2{text-wrap:balance;font-weight:600;letter-spacing:.3px}
.eyebrow{font-family:var(--mono);font-size:.7rem;text-transform:uppercase;
  letter-spacing:.22em;color:var(--faint);margin-bottom:.5rem}
.eyebrow.gold{color:var(--gold)}
.hero{display:flex;gap:22px;align-items:center;padding:8px 0 26px;
  border-bottom:1px solid var(--line);margin-bottom:28px}
.sigil{width:76px;height:76px;flex:0 0 auto;
  filter:drop-shadow(0 0 10px rgba(233,184,102,.35))}
.hero h1{font-size:clamp(1.7rem,4.5vw,2.9rem);margin:.1rem 0 .35rem;line-height:1.1}
.rname{color:var(--gold);font-style:italic}
.sub{color:var(--faint);max-width:60ch;margin:0;font-size:1.02rem}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
  gap:12px;margin:0 0 30px}
.tile{background:linear-gradient(180deg,var(--panel2),var(--panel));
  border:1px solid var(--line);border-radius:12px;padding:16px 16px 14px;
  display:flex;flex-direction:column;gap:2px}
.tval{font-family:var(--mono);font-size:1.9rem;color:var(--gold);
  font-variant-numeric:tabular-nums;line-height:1}
.tkey{font-family:var(--mono);font-size:.72rem;text-transform:uppercase;
  letter-spacing:.16em;color:var(--parchment);margin-top:6px}
.tsub{font-size:.8rem;color:var(--faint)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;
  padding:clamp(18px,3vw,32px);margin:0 0 24px}
.panel h2{font-size:clamp(1.3rem,3vw,1.9rem);margin:.1rem 0 1rem;color:var(--parchment)}
.constel{background:linear-gradient(180deg,#0f0c1a,#0c0a14)}
.constellation{width:100%;height:auto;display:block;border-radius:12px;
  border:1px solid var(--line);background:var(--ink)}
.constellation .node text{font-family:var(--mono);font-size:11px;fill:var(--faint);
  text-anchor:middle;pointer-events:none;transition:fill .2s}
.constellation .node circle{stroke:#0c0a14;stroke-width:1.2;transition:r .2s,filter .2s}
.constellation .node.hub circle{fill:var(--gold);filter:drop-shadow(0 0 6px rgba(233,184,102,.9))}
.constellation .node.mid circle{fill:var(--violet);filter:drop-shadow(0 0 5px rgba(168,139,230,.8))}
.constellation .node.leaf circle{fill:var(--cyan);filter:drop-shadow(0 0 4px rgba(127,212,208,.7))}
.constellation .node:hover circle{filter:drop-shadow(0 0 12px currentColor)}
.constellation .node:hover text{fill:var(--parchment)}
.constellation .stars circle{animation:tw 4s ease-in-out infinite}
.constellation.dim .edge{stroke-opacity:.04!important}
.constellation.dim .node:not(.lit){opacity:.28}
.constellation .edge.lit{stroke:var(--gold)!important;stroke-opacity:.8!important;stroke-width:1.6}
@keyframes tw{50%{opacity:.15}}
.empty{color:var(--faint);font-family:var(--mono);font-size:.9rem;
  padding:40px;text-align:center}
.dream{background:linear-gradient(180deg,#171130,#120f22);border-color:#33285c}
.dream h2{color:var(--violet)}
.weave{font-size:1.18rem;font-style:italic;color:var(--parchment);max-width:66ch;
  margin:.2rem 0 1.2rem;line-height:1.55}
.visions{list-style:none;padding:0;margin:0;display:grid;gap:12px}
.vision{border-left:2px solid var(--violet);padding:2px 0 2px 16px}
.vkind{font-family:var(--mono);font-size:.68rem;text-transform:uppercase;
  letter-spacing:.16em;color:var(--violet)}
.vtext{margin:.25rem 0 .15rem;font-size:1.05rem;color:var(--parchment)}
.vwhy{margin:0;font-family:var(--mono);font-size:.78rem;color:var(--faint)}
.attribution{margin:1.1rem 0 0;font-size:.82rem;color:var(--faint);font-style:italic}
.thread{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:14px}
.say{border-left:2px solid var(--line);padding-left:16px}
.say .who{font-family:var(--mono);font-size:.82rem;letter-spacing:.04em}
.say .to{font-family:var(--mono);font-size:.74rem;color:var(--faint);margin-left:8px}
.say .line{margin:.3rem 0 0;color:var(--parchment)}
.say.master{border-color:var(--rose)} .say.master .who{color:var(--rose)}
.say.wizard{border-color:var(--cyan)} .say.wizard .who{color:var(--cyan)}
.say.general{border-color:var(--gold)} .say.general .who{color:var(--gold)}
.say.warrior{border-color:var(--ember)} .say.warrior .who{color:var(--ember)}
.say.chant{border-color:var(--verdigris)} .say.chant .who{color:var(--verdigris)}
.say.dream{border-color:var(--violet)} .say.dream .who{color:var(--violet)}
.tablewrap{overflow-x:auto}
.grimoire table{width:100%;border-collapse:collapse;font-size:.92rem}
.grimoire th{font-family:var(--mono);font-size:.68rem;text-transform:uppercase;
  letter-spacing:.14em;color:var(--faint);text-align:left;padding:8px 12px;
  border-bottom:1px solid var(--line)}
.grimoire td{padding:10px 12px;border-bottom:1px solid rgba(42,36,64,.5);
  vertical-align:top}
.grimoire .cid{color:var(--gold)} .grimoire .subj{color:var(--faint)}
.grimoire .claim{color:var(--parchment);min-width:260px}
.mono{font-family:var(--mono)}
.chip{font-family:var(--mono);font-size:.7rem;padding:2px 9px;border-radius:999px;
  border:1px solid var(--line);white-space:nowrap}
.chip.rung{color:var(--faint)}
.chip.st-held{color:var(--verdigris);border-color:rgba(111,206,159,.4)}
.chip.st-unchecked{color:var(--faint)}
.chip.st-broken{color:var(--ember);border-color:rgba(224,112,90,.4)}
.places{list-style:none;padding:0;margin:0;display:grid;gap:10px}
.places li{display:flex;gap:14px;align-items:baseline;flex-wrap:wrap;
  padding-bottom:8px;border-bottom:1px solid rgba(42,36,64,.5)}
.places .dom{color:var(--parchment)} .places .ip{color:var(--faint);font-size:.82rem}
.places .seen{color:var(--faint);font-size:.82rem;margin-left:auto}
.chant{text-align:center;background:linear-gradient(180deg,#101a15,#0d130f);
  border-color:#243b2e}
.poem{display:flex;flex-direction:column;gap:.35rem;font-style:italic;
  font-size:1.2rem;color:var(--verdigris);padding:8px 0}
.foot{display:flex;justify-content:center;align-items:center;gap:14px;
  color:var(--faint);font-family:var(--mono);font-size:.76rem;
  padding:22px 0 4px;letter-spacing:.05em}
.foot .mark{color:var(--gold);font-size:1rem}
@media (prefers-reduced-motion:reduce){.constellation .stars circle{animation:none}}
@media (max-width:560px){.hero{flex-direction:column;text-align:center}
  .places .seen{margin-left:0}}
</style>"""

_SCRIPT = """<script>
(function(){
  var svg=document.querySelector('.constellation'); if(!svg) return;
  var nodes=svg.querySelectorAll('.node'), edges=svg.querySelectorAll('.edge');
  nodes.forEach(function(n){
    n.addEventListener('mouseenter',function(){
      var name=n.getAttribute('data-name'); svg.classList.add('dim');
      var lit={}; lit[name]=1;
      edges.forEach(function(e){
        if(e.getAttribute('data-a')===name||e.getAttribute('data-b')===name){
          e.classList.add('lit'); lit[e.getAttribute('data-a')]=1; lit[e.getAttribute('data-b')]=1;}
      });
      nodes.forEach(function(m){ if(lit[m.getAttribute('data-name')]) m.classList.add('lit'); });
    });
    n.addEventListener('mouseleave',function(){
      svg.classList.remove('dim');
      edges.forEach(function(e){e.classList.remove('lit');});
      nodes.forEach(function(m){m.classList.remove('lit');});
    });
  });
})();
</script>"""
