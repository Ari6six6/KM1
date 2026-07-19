"""The Cathedral — a mind you can watch think.

The realm renders itself as one self-contained page, by its own hand: no network,
no dependency, the stdlib promise kept. Two windows the Master flips between —

  the MIND window — the knowledge graph laid out as a **constellation** (a
    force-directed pass computed in pure Python; every star a thing the realm
    knows, every line a bond it drew), the night's dream, the Chant that crossed
    the dark, the day in the Hall;
  the OPERATION window — orders in flight, the JUICE curve, the burn rate.

A static render (positions baked in) so it opens on a phone with zero installs.
``mor cathedral`` writes it; the daemon serves it live at ``/cathedral``.
"""

from __future__ import annotations

import html
import math
import random


def _layout(nodes, edges, w=760, h=430, iters=220, seed=7):
    rng = random.Random(seed)
    pos = {n: [rng.uniform(0.25, 0.75) * w, rng.uniform(0.25, 0.75) * h] for n in nodes}
    if len(nodes) < 2:
        return pos
    k = math.sqrt((w * h) / len(nodes))
    nlist = list(nodes)
    for it in range(iters):
        disp = {n: [0.0, 0.0] for n in nodes}
        for i in range(len(nlist)):
            for j in range(i + 1, len(nlist)):
                a, b = nlist[i], nlist[j]
                dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
                d = math.hypot(dx, dy) or 0.01
                f = k * k / d
                disp[a][0] += dx / d * f; disp[a][1] += dy / d * f
                disp[b][0] -= dx / d * f; disp[b][1] -= dy / d * f
        for a, b in edges:
            if a == b or a not in pos or b not in pos:
                continue
            dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
            d = math.hypot(dx, dy) or 0.01
            f = d * d / k
            disp[a][0] -= dx / d * f; disp[a][1] -= dy / d * f
            disp[b][0] += dx / d * f; disp[b][1] += dy / d * f
        t = max(1.0, 9 * (1 - it / iters))
        for n in nodes:
            dx, dy = disp[n]
            d = math.hypot(dx, dy) or 0.01
            step = min(d, t)
            pos[n][0] = min(w - 24, max(24, pos[n][0] + dx / d * step))
            pos[n][1] = min(h - 20, max(20, pos[n][1] + dy / d * step))
    return pos


def _constellation_svg(edges) -> str:
    nodes = []
    for e in edges:
        for x in (e["subject"], e["object"]):
            if x not in nodes:
                nodes.append(x)
    nodes = nodes[:40]
    node_set = set(nodes)
    pairs = [(e["subject"], e["object"]) for e in edges
             if e["subject"] in node_set and e["object"] in node_set]
    if not nodes:
        return "<p class='empty'>the graph is dark — no bonds drawn yet. run a day, then <code>mor dark</code>.</p>"
    pos = _layout(node_set, pairs)
    parts = ["<svg viewBox='0 0 760 430' class='sky' role='img' aria-label='knowledge constellation'>"]
    for e in edges:
        a, b = e["subject"], e["object"]
        if a in pos and b in pos:
            cls = "edge contra" if e["relation"] == "contradicts" else "edge"
            parts.append(f"<line class='{cls}' x1='{pos[a][0]:.0f}' y1='{pos[a][1]:.0f}' "
                         f"x2='{pos[b][0]:.0f}' y2='{pos[b][1]:.0f}'></line>")
    for n in nodes:
        x, y = pos[n]
        parts.append(f"<circle class='star' cx='{x:.0f}' cy='{y:.0f}' r='4'></circle>"
                     f"<text class='label' x='{x + 7:.0f}' y='{y + 3:.0f}'>{html.escape(n)}</text>")
    parts.append("</svg>")
    return "".join(parts)


def _juice_svg(verdicts) -> str:
    pts = [v.get("juice") for v in verdicts if isinstance(v.get("juice"), (int, float))]
    if len(pts) < 2:
        return "<p class='empty'>no forge cycles yet — the curve begins with the first kept gain.</p>"
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    w, h = 320, 90
    coords = []
    for i, p in enumerate(pts):
        x = 6 + i * (w - 12) / (len(pts) - 1)
        y = h - 8 - (p - lo) / span * (h - 20)
        coords.append(f"{x:.0f},{y:.0f}")
    return (f"<svg viewBox='0 0 {w} {h}' class='spark' role='img' aria-label='JUICE curve'>"
            f"<polyline points='{' '.join(coords)}'></polyline>"
            f"<text class='sparkval' x='{w - 4}' y='14'>{pts[-1]:.1f}</text></svg>")


def render(project) -> str:
    from mor.day import last_chant, todays_hall
    from mor.dream import extract, dream_questions
    from mor.order import OrderStore
    from mor.ledger import events
    from mor.field import Field
    from mor import mind

    hall = todays_hall(project)
    reports = []
    for o in OrderStore(project).list()[:20]:
        for p in o.artifacts():
            if p.name == "report.md":
                reports.append(p.read_text())
    edges = extract(hall, reports)
    questions = dream_questions(project)
    chant = last_chant(project)
    orders = OrderStore(project).list()[:8]
    verdicts = events(project, "forge.verdict")
    field = Field(project).summary()
    boxes = mind.serving(project)

    def esc(s):
        return html.escape(str(s))

    hall_rows = "".join(
        f"<div class='say'><b>{esc(e.get('speaker', '?'))}</b>"
        f"<span class='to'>{('→ ' + esc(e['addressee'])) if e.get('addressee') else ''}</span> "
        f"{esc((e.get('text') or '')[:160])}</div>" for e in hall[-14:])
    q_rows = "".join(f"<li>{esc(q['text'])}</li>" for q in questions[:8]) or \
        "<li class='empty'>no questions yet — the night has not dreamt.</li>"
    order_rows = "".join(
        f"<tr><td class='mono'>{esc(o.id[-12:])}</td><td>{esc(o.kind)}</td>"
        f"<td class='st-{esc(o.state)}'>{esc(o.state)}</td><td>{esc(o.brief[:46])}</td></tr>"
        for o in orders) or "<tr><td colspan='4' class='empty'>no orders yet.</td></tr>"
    last_v = verdicts[-1] if verdicts else None
    forge_line = (f"{esc(last_v['verdict'])} · JUICE {last_v.get('juice')} "
                  f"(Δ{last_v.get('delta', 0):+.2f})") if last_v else "no cycles yet"
    burn = (f"${field['cost']:.2f} spent · ${field['rate_per_hour']:.2f}/hr"
            if field.get("instance") else "field cold")
    minds = ", ".join(b["label"] for b in boxes) or "offline stand-in (DEMO)"
    chant_html = "<br>".join(esc(l) for l in chant.splitlines()) if chant else \
        "<span class='empty'>no chant yet — the first day has no yesterday.</span>"

    return _PAGE.format(
        constellation=_constellation_svg(edges), questions=q_rows, chant=chant_html,
        hall=hall_rows or "<div class='empty say'>the hall is quiet.</div>",
        orders=order_rows, juice=_juice_svg(verdicts), forge=esc(forge_line),
        burn=esc(burn), minds=esc(minds), project=esc(project.name),
        edges_n=len(edges))


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MoRE — the Cathedral</title><style>
:root{{--bg:#0f1020;--panel:#181a30;--ink:#e8e8f2;--dim:#9a9ab8;--line:#2b2d4a;
--star:#8be9fd;--edge:#3a3d63;--contra:#ff6b8a;--accent:#c4b5fd;--ok:#6ee7a8}}
@media (prefers-color-scheme:light){{:root{{--bg:#f4f4fb;--panel:#fff;--ink:#1a1a2e;
--dim:#5b5b7a;--line:#e2e2ee;--star:#2563eb;--edge:#cdd0e6;--contra:#d6336c;
--accent:#6d28d9;--ok:#0f9d58}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}}
header{{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;
justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px}}
h1{{margin:0;font-size:17px;letter-spacing:.02em}}h1 span{{color:var(--accent)}}
.sub{{color:var(--dim);font-size:12px}}
.wrap{{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px;max-width:1200px;margin:0 auto}}
@media (max-width:820px){{.wrap{{grid-template-columns:1fr}}}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
.panel h2{{margin:0 0 10px;font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim)}}
.sky{{width:100%;height:auto;background:radial-gradient(circle at 50% 40%,rgba(139,233,253,.06),transparent 70%);border-radius:8px}}
.edge{{stroke:var(--edge);stroke-width:1}}.edge.contra{{stroke:var(--contra);stroke-dasharray:3 3}}
.star{{fill:var(--star)}}.label{{fill:var(--ink);font-size:10px;opacity:.85}}
.q{{list-style:none;padding:0;margin:0}}.q li{{padding:6px 10px;margin:6px 0;border-left:2px solid var(--accent);
background:rgba(196,181,253,.07);border-radius:0 6px 6px 0}}
.chant{{font-style:italic;color:var(--ink);white-space:normal;padding:8px 10px;border-left:2px solid var(--star);background:rgba(139,233,253,.06);border-radius:0 6px 6px 0}}
.hall{{max-height:220px;overflow:auto}}.say{{padding:3px 0;border-bottom:1px solid var(--line);font-size:13px}}
.say b{{color:var(--accent)}}.to{{color:var(--dim)}}
table{{width:100%;border-collapse:collapse;font-size:13px}}td{{padding:5px 6px;border-bottom:1px solid var(--line)}}
.mono{{font-family:ui-monospace,Menlo,monospace;color:var(--dim)}}
.st-delivered{{color:var(--ok)}}.st-failed{{color:var(--contra)}}.st-executing,.st-verifying{{color:var(--star)}}
.stat{{display:flex;gap:18px;flex-wrap:wrap;margin-top:8px}}.stat div span{{display:block;color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.06em}}
.stat div b{{font-size:15px}}.spark polyline{{fill:none;stroke:var(--ok);stroke-width:2}}.sparkval{{fill:var(--dim);font-size:11px;text-anchor:end}}
.empty{{color:var(--dim);font-style:italic}}.foot{{text-align:center;color:var(--dim);font-size:11px;padding:0 0 20px}}
code{{font-family:ui-monospace,monospace;color:var(--accent)}}
</style></head><body>
<header><h1><span>&#9651;</span> MoRE &mdash; the Cathedral</h1>
<span class="sub">project {project} &middot; a mind you can watch think</span></header>
<div class="wrap">
 <section class="panel">
  <h2>the mind &mdash; the constellation ({edges_n} bonds)</h2>
  {constellation}
  <h2 style="margin-top:14px">the night dreamt</h2><ul class="q">{questions}</ul>
  <h2 style="margin-top:14px">the chant that crossed the dark</h2><div class="chant">{chant}</div>
 </section>
 <section class="panel">
  <h2>the operation &mdash; orders</h2>
  <table><thead><tr><td class="mono">id</td><td>kind</td><td>state</td><td>brief</td></tr></thead>
  <tbody>{orders}</tbody></table>
  <div class="stat">
   <div><span>forge</span><b>{forge}</b></div>
   <div><span>burn</span><b>{burn}</b></div>
   <div><span>minds</span><b>{minds}</b></div>
  </div>
  <h2 style="margin-top:14px">JUICE</h2>{juice}
  <h2 style="margin-top:14px">the day in the hall</h2><div class="hall">{hall}</div>
 </section>
</div>
<div class="foot">rendered by the realm's own hand &middot; self-contained, no network, no dependency</div>
</body></html>"""
