"""Memory — what the realm remembers, wired into every prompt.

The Chant carries identity across the night; this carries *facts* across sessions.
When a face takes a turn, the realm recalls the most relevant passages from its own
past work — delivered order reports and the project notes — and lays them in the
face's context, so it answers from what it learned before **without being told
where to look**.

The leg is lexical (BM25, stdlib only) — honest, fast, no model required. Model-
assisted extraction and embeddings are a later layer; the retrieval *seam* is here
now. It reads only the realm's own memory (reports, notes), never arbitrary
workspace files, so nothing private leaks in through the back door.
"""

from __future__ import annotations

import math
import re

_WORD = re.compile(r"[a-z0-9]+")
_K1, _B = 1.5, 0.75


def _tok(text: str) -> list:
    return _WORD.findall((text or "").lower())


def documents(project, limit: int = 200) -> list:
    """The realm's own memory corpus: the project notes and past order reports.
    Newest reports first, bounded so recall stays cheap."""
    docs = []
    notes = project.notes_path
    if notes.exists():
        body = notes.read_text().strip()
        if body:
            docs.append({"source": "notes.md", "text": body})
    orders = project.root / "orders"
    if orders.exists():
        for report in sorted(orders.glob("*/report.md"), reverse=True)[:limit]:
            try:
                docs.append({"source": f"order {report.parent.name}",
                             "text": report.read_text()})
            except OSError:
                continue
    return docs


def _snippet(text: str, terms: list, max_chars: int) -> str:
    low = text.lower()
    pos = min((low.find(t) for t in terms if low.find(t) >= 0), default=0)
    start = max(0, pos - 80)
    return " ".join(text[start:start + max_chars].split())


def recall(project, query: str, k: int = 3, max_chars: int = 360) -> list:
    """Top-k (source, snippet) from the realm's memory, most relevant first —
    BM25 over the corpus. Empty if there's no corpus or no term overlap."""
    docs = documents(project)
    q = [t for t in _tok(query) if len(t) > 2]
    if not docs or not q:
        return []
    tokenized = [_tok(d["text"]) for d in docs]
    n = len(docs)
    avgdl = (sum(len(td) for td in tokenized) / n) or 1.0
    df: dict = {}
    for td in tokenized:
        for t in set(td):
            df[t] = df.get(t, 0) + 1

    scored = []
    for doc, td in zip(docs, tokenized):
        if not td:
            continue
        tf: dict = {}
        for t in td:
            tf[t] = tf.get(t, 0) + 1
        score = 0.0
        for t in set(q):
            if t in tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * (tf[t] * (_K1 + 1)) / (tf[t] + _K1 * (1 - _B + _B * len(td) / avgdl))
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda x: -x[0])
    return [(doc["source"], _snippet(doc["text"], q, max_chars)) for _, doc in scored[:k]]


def memory_block(project, query: str, k: int = 3) -> str:
    """The recalled passages formatted for a prompt, or '' if nothing is relevant."""
    hits = recall(project, query, k=k)
    if not hits:
        return ""
    lines = ["WHAT THE REALM REMEMBERS (from earlier work — cite it if it helps, "
             "and say it's from memory):"]
    for source, snippet in hits:
        lines.append(f"- ({source}) {snippet}")
    return "\n".join(lines)
