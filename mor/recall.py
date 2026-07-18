"""Recall — the realm's retrieval muscle. Zero-dependency RAG.

Any structured ground the realm holds — territory records and their colony
files, the walls, the chants, the shelf, workspace code — is chunked and
ranked against a query with BM25-style scoring (term frequency × inverse
document frequency, stdlib math only). No vector database, no embedding
service, no network: honest lexical retrieval that works with any mind
attached, or none. A face asks; the ground answers with its most relevant
passages and where they live.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from mor import skills, territory

_CHUNK = 800       # chars per window
_OVERLAP = 120     # shared edge between windows
_MAX_FILE = 1_000_000  # bigger files are not read for a corpus


def _tokens(text: str) -> list:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _chunks(text: str) -> list:
    """Sliding windows over the text, aligned to line starts where they fall."""
    if not text:
        return []
    out, i, n = [], 0, len(text)
    while i < n:
        end = min(i + _CHUNK, n)
        out.append(text[i:end])
        if end >= n:
            break
        nxt = text.find("\n", i + _CHUNK - _OVERLAP)
        i = (nxt + 1) if 0 < nxt < end else end - _OVERLAP
    return out


def retrieve(query: str, docs: list, k: int = 5) -> list:
    """Rank `docs` — [(ref, text)] — against `query`. Returns up to k hits as
    (ref, excerpt, score), best first, score > 0 only."""
    q = _tokens(query)
    if not q:
        return []
    windows = []  # (ref, text)
    for ref, text in docs:
        for w in _chunks(text):
            windows.append((ref, w))
    if not windows:
        return []
    tokenized = [_tokens(w) for _, w in windows]
    n = len(windows)
    df: dict = {}
    for toks in tokenized:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    avg_len = sum(len(t) for t in tokenized) / n or 1.0

    def _score(toks: list) -> float:
        tf: dict = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        length = len(toks) or 1
        s = 0.0
        for t in q:
            if t not in df:
                continue
            idf = math.log(1.0 + (n - df[t] + 0.5) / (df[t] + 0.5))
            f = tf.get(t, 0)
            s += idf * (f * 2.2) / (f + 1.2 * (0.25 + 0.75 * length / avg_len))
        return s

    scored = sorted(((s, ref, w) for (ref, w), toks in zip(windows, tokenized)
                     if (s := _score(toks)) > 0),
                    key=lambda h: -h[0])
    # one window per ref at a time — the best window of a ref outranks its own neighbors
    hits, seen_refs_count = [], {}
    for s, ref, w in scored:
        if seen_refs_count.get(ref, 0) >= 2:
            continue
        seen_refs_count[ref] = seen_refs_count.get(ref, 0) + 1
        hits.append((ref, w.strip(), s))
        if len(hits) >= k:
            break
    return hits


def _text_file(p: Path) -> str:
    try:
        if p.stat().st_size > _MAX_FILE:
            return ""
        head = p.read_bytes()[:2048]
        if b"\0" in head:
            return ""
        return p.read_text("utf-8", "replace")
    except OSError:
        return ""


def load_corpus(space, source: str = "all", workspace: Path | None = None) -> list:
    """Gather (ref, text) pairs for a source: workspace · territories · walls ·
    chants · skills · all."""
    docs = []
    source = (source or "all").lower()

    if source in ("workspace", "all") and workspace and Path(workspace).is_dir():
        for p in sorted(Path(workspace).rglob("*")):
            if p.is_file() and ".git" not in p.parts:
                text = _text_file(p)
                if text:
                    docs.append((f"workspace/{p.name}", text))

    if source in ("territories", "all"):
        for name in territory.all(space):
            rec = territory.load(space, name)
            docs.append((f"territory/{name}.json", json.dumps(rec, indent=1)))
            cdir = territory.colony_dir(space, name)
            if cdir.is_dir():
                for p in sorted(cdir.rglob("*")):
                    if p.is_file() and p.name != "ops.jsonl":
                        text = _text_file(p)
                        if text:
                            docs.append((f"territory/{name}/{p.relative_to(cdir)}", text))

    if source in ("walls", "all"):
        pop = space.root / "population"
        if pop.is_dir():
            for p in sorted(pop.glob("*/**/*_wall.md")):
                text = _text_file(p)
                if text:
                    docs.append((f"walls/{p.parent.name}/{p.name}", text))

    if source in ("chants", "all"):
        ch = space.root / "chants"
        if ch.is_dir():
            for p in sorted(ch.glob("*.md")):
                text = _text_file(p)
                if text:
                    docs.append((f"chants/{p.name}", text))

    if source in ("skills", "all"):
        for line in skills.index(space, limit=100).split("; "):
            name = line.split(" — ", 1)[0]
            body = skills.load(space, name)
            if body:
                docs.append((f"skills/{name}.md", body))

    return docs
