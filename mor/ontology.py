"""The Ontology — the realm's knowledge graph with a vector memory underneath.

Recall (the old BM25 ground) answers with *passages*. The Ontology answers with
*passages plus what the realm knows about the things in them*: entities, the
claims that bind them (subject–predicate–object triples), and semantic
nearness over embedded chunks. Three signals fused:

  vector  — cosine over embeddings (the served mind's /v1/embeddings when an
            oracle is attached; an honest hashed lexical vector when offline —
            labelled, deterministic, zero-dependency),
  lexical — term overlap, so exact names never drown in vibes,
  graph   — a passage that mentions an entity pulls that entity's one-hop
            triples into the answer, and passages touching *those* entities
            get a boost. The ground now answers with context, not just quotes.

Everything lives in one sqlite file inside the space (stdlib sqlite3 — the
realm still installs with pip install nothing). Ingest is incremental and
idempotent: re-ingesting the same (source, ref, chunk) changes nothing.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time

_DIM = 1024            # hashed-vector width (offline path)
_CHUNK_WORDS = 110     # passage size fed to the graph
_OVERLAP_WORDS = 25

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    name TEXT PRIMARY KEY,
    kind TEXT DEFAULT 'thing',
    mentions INTEGER DEFAULT 1,
    first_seen REAL
);
CREATE TABLE IF NOT EXISTS triples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT, predicate TEXT, object TEXT,
    weight REAL DEFAULT 1.0, day INTEGER DEFAULT 0,
    UNIQUE(subject, predicate, object)
);
CREATE TABLE IF NOT EXISTS passages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT, ref TEXT, chunk TEXT, vec TEXT,
    UNIQUE(source, ref, chunk)
);
CREATE INDEX IF NOT EXISTS idx_triples_s ON triples(subject);
CREATE INDEX IF NOT EXISTS idx_triples_o ON triples(object);
"""

_TOKEN = re.compile(r"[A-Za-z0-9_']+")
# Entities may carry dots — Vast.ai, example.com are things the realm speaks of.
_NAME_BIT = r"[A-Z][a-zA-Z0-9]*(?:\.[a-zA-Z0-9]+)*"
_ENTITY = re.compile(r"\b(" + _NAME_BIT + r"(?:\s+(?:of\s+the\s+|" + _NAME_BIT + r"))*)")
_REL_PATTERNS = [
    (re.compile(r"\b([A-Z][\w. ]{1,40}?)\s+is\s+(?:a|an|the)\s+([\w][\w. -]{1,40})"), "is_a"),
    (re.compile(r"\b([A-Z][\w. ]{1,40}?)\s+(?:uses|use)\s+([\w][\w. -]{1,40})"), "uses"),
    (re.compile(r"\b([A-Z][\w. ]{1,40}?)\s+(?:owns|own)\s+([\w][\w. -]{1,40})"), "owns"),
    (re.compile(r"\b([A-Z][\w. ]{1,40}?)\s+(?:writes|wrote)\s+([\w][\w. -]{1,40})"), "writes"),
]
_ENTITY_STOP = {"The", "This", "That", "It", "He", "She", "We", "They", "You",
                "I", "A", "An", "In", "On", "At", "To", "For", "And", "But",
                "If", "When", "What", "Master", "Hall"}


def db_path(space):
    return space.root / "ontology.db"


def connect(space) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path(space)))
    conn.executescript(_SCHEMA)
    return conn


# ---------------------------------------------------------------- embeddings
def _hashed_vec(text: str) -> list:
    """Deterministic lexical vector: token → signed bucket via md5, L2-normal.
    Not a mind — but cosine over it tracks real topical nearness well enough
    to keep hybrid retrieval honest with no oracle and no dependencies."""
    v = [0.0] * _DIM
    for tok in _TOKEN.findall(text.lower()):
        h = hashlib.md5(tok.encode()).digest()
        bucket = int.from_bytes(h[:2], "little") % _DIM
        sign = 1.0 if h[2] & 1 else -1.0
        v[bucket] += sign
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def embed(texts: list, backend=None) -> tuple:
    """(vectors, how) — 'mind' if the attached oracle served embeddings,
    'hashed' for the offline lexical fallback. Never fails: offline always works."""
    if backend is not None:
        try:
            vecs = backend.embed(texts)
            if vecs and len(vecs) == len(texts) and vecs[0]:
                return vecs, "mind"
        except Exception:  # noqa: BLE001 — embeddings must never break a turn
            pass
    return [_hashed_vec(t) for t in texts], "hashed"


def _cos(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


# ------------------------------------------------------------------ graph IO
def _norm_name(name: str) -> str:
    return " ".join((name or "").split()).strip().strip(".")


def note_entity(conn, name: str, kind: str = "thing") -> None:
    name = _norm_name(name)
    if not name or len(name) < 3 or name in _ENTITY_STOP or len(name) > 80:
        return
    conn.execute(
        "INSERT INTO entities(name, kind, first_seen) VALUES(?,?,?) "
        "ON CONFLICT(name) DO UPDATE SET mentions = mentions + 1",
        (name, kind, time.time()))


def relate(conn, subject: str, predicate: str, obj: str, day: int = 0,
           weight: float = 1.0) -> str:
    """Assert one triple (idempotent: re-asserting strengthens the weight)."""
    s, p, o = _norm_name(subject), _norm_name(predicate).lower().replace(" ", "_"), _norm_name(obj)
    if not (s and p and o):
        return "ERROR: a triple needs subject, predicate and object"
    conn.execute(
        "INSERT INTO triples(subject, predicate, object, weight, day) VALUES(?,?,?,?,?) "
        "ON CONFLICT(subject, predicate, object) DO UPDATE SET weight = weight + 0.5",
        (s, p, o, float(weight), int(day)))
    note_entity(conn, s)
    note_entity(conn, o)
    conn.commit()
    return f"{s} —{p}→ {o}"


def extract_and_relate(conn, text: str, day: int = 0) -> int:
    """The offline auto-extractor: capitalized entities + a few honest relation
    patterns. Deliberately shallow — faces assert the deep semantics themselves
    with the relate tool; this just keeps the graph warm."""
    n = 0
    for m in _ENTITY.finditer(text):
        note_entity(conn, m.group(1))
        n += 1
    for rx, pred in _REL_PATTERNS:
        for m in rx.finditer(text):
            relate(conn, m.group(1), pred, m.group(2), day=day, weight=0.5)
            n += 1
    conn.commit()
    return n


def _chunks(text: str):
    words = text.split()
    if not words:
        return
    step = _CHUNK_WORDS - _OVERLAP_WORDS
    for i in range(0, len(words), step):
        piece = " ".join(words[i:i + _CHUNK_WORDS])
        if piece:
            yield piece


def ingest_text(conn, source: str, ref: str, text: str, backend=None,
                day: int = 0) -> int:
    """Chunk a document, embed the chunks, store passages, warm the graph.
    Idempotent per (source, ref, chunk). Returns chunks newly ingested."""
    new = 0
    pieces = [c for c in _chunks(text or "")
              if not conn.execute(
                  "SELECT 1 FROM passages WHERE source=? AND ref=? AND chunk=?",
                  (source, ref, c)).fetchone()]
    if not pieces:
        return 0
    vecs, _how = embed(pieces, backend)
    for chunk, vec in zip(pieces, vecs):
        conn.execute(
            "INSERT OR IGNORE INTO passages(source, ref, chunk, vec) VALUES(?,?,?,?)",
            (source, ref, chunk, json.dumps(vec)))
        new += 1
    extract_and_relate(conn, text, day=day)
    conn.commit()
    return new


def _lexical(query: str, chunk: str) -> float:
    q = {t for t in _TOKEN.findall(query.lower())}
    if not q:
        return 0.0
    c = {t for t in _TOKEN.findall(chunk.lower())}
    return len(q & c) / math.sqrt(len(q) * max(len(c), 1))


def subgraph(conn, names, hops: int = 1) -> list:
    """The one-hop neighbourhood of the given entities: [(s, p, o, w)]."""
    out, seen = [], set()
    frontier = [ _norm_name(n) for n in names if _norm_name(n) ]
    for _ in range(max(1, hops)):
        nxt = []
        for name in frontier:
            rows = conn.execute(
                "SELECT subject, predicate, object, weight FROM triples "
                "WHERE subject=? OR object=?", (name, name)).fetchall()
            for s, p, o, w in rows:
                key = (s, p, o)
                if key in seen:
                    continue
                seen.add(key)
                out.append((s, p, o, w))
                nxt.extend([s, o])
        frontier = [n for n in nxt if n]
    return out


def entities_in(conn, text: str) -> list:
    names = {r[0] for r in conn.execute("SELECT name FROM entities").fetchall()}
    found = [n for n in names if n and re.search(
        r"\b" + re.escape(n) + r"\b", text or "", re.IGNORECASE)]
    return found


def ask(conn, query: str, k: int = 5, backend=None) -> dict:
    """The fused answer: top passages (vector+lexical+graph) plus the triple
    neighbourhood of everything they mention."""
    qvec, how = embed([query], backend)
    qvec = qvec[0]
    rows = conn.execute("SELECT id, source, ref, chunk, vec FROM passages").fetchall()
    scored = []
    q_ents = entities_in(conn, query)
    for pid, source, ref, chunk, vec_json in rows:
        try:
            vec = json.loads(vec_json)
        except (json.JSONDecodeError, TypeError):
            vec = []
        base = 0.6 * _cos(qvec, vec) + 0.4 * _lexical(query, chunk)
        chunk_ents = entities_in(conn, chunk)
        graph_hits = len(set(q_ents) & set(chunk_ents))
        score = base + 0.25 * graph_hits
        scored.append((score, source, ref, chunk, chunk_ents))
    scored.sort(key=lambda t: t[0], reverse=True)
    top = scored[:max(1, k)]
    ent_names = set(q_ents)
    for _s, _src, _r, _c, cents in top:
        ent_names.update(cents)
    triples = subgraph(conn, list(ent_names)[:12]) if ent_names else []
    return {
        "how": how,
        "passages": [{"score": round(s, 3), "source": src, "ref": ref,
                      "excerpt": chunk[:400]} for s, src, ref, chunk, _e in top],
        "triples": [{"s": s, "p": p, "o": o, "w": w} for s, p, o, w in triples[:20]],
    }


def stats(conn) -> dict:
    def _n(q):
        return conn.execute(q).fetchone()[0]
    return {"entities": _n("SELECT COUNT(*) FROM entities"),
            "triples": _n("SELECT COUNT(*) FROM triples"),
            "passages": _n("SELECT COUNT(*) FROM passages")}
