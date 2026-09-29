import re
import threading

import numpy as np

from . import embed

STOP = set("""a an and are as at be but by for from has have how i if in into is it its of on or our so than that the their
them then there these they this to us was we what when where which who why will with you your about can does do not""".split())

_cache = {"n": -1, "ids": None, "mat": None}
_cache_lock = threading.Lock()


def fts_query(q):
    parts = []
    for phrase in re.findall(r'"([^"]+)"', q):
        toks = re.findall(r"\w+", phrase)
        if toks:
            parts.append('"' + " ".join(toks) + '"')
    rest = re.sub(r'"[^"]*"', " ", q)
    toks = [t for t in re.findall(r"\w+", rest.lower()) if t not in STOP]
    parts += [f'"{t}"' for t in toks]
    return " OR ".join(parts)


def keyword(conn, q, limit=100):
    fq = fts_query(q)
    if not fq:
        return []
    # column order: tag, cite, spoken, context, full_text
    rows = conn.execute(
        "SELECT rowid AS id, bm25(cards_fts, 8.0, 3.0, 6.0, 2.0, 1.0) AS s FROM cards_fts WHERE cards_fts MATCH ? "
        "ORDER BY s LIMIT ?",
        (fq, limit),
    ).fetchall()
    return [r["id"] for r in rows]


def _matrix(conn):
    n = conn.execute("SELECT COUNT(*) FROM cards WHERE embedding IS NOT NULL").fetchone()[0]
    with _cache_lock:
        if _cache["n"] != n:
            rows = conn.execute("SELECT id, embedding FROM cards WHERE embedding IS NOT NULL").fetchall()
            _cache["ids"] = [r["id"] for r in rows]
            _cache["mat"] = (
                np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows]) if rows else None
            )
            _cache["n"] = n
        return _cache["ids"], _cache["mat"]


def semantic(conn, q, limit=100):
    impl = embed.EMB.impl
    if impl is None:
        return []
    ids, mat = _matrix(conn)
    if mat is None:
        return []
    v = impl.embed_query(q)
    v = v / (np.linalg.norm(v) or 1.0)
    sims = mat @ v
    top = np.argsort(-sims)[:limit]
    return [ids[i] for i in top if sims[i] > 0.2]


def hybrid(conn, q, limit=100, k=60):
    scores = {}
    for ranking in (keyword(conn, q, limit), semantic(conn, q, limit)):
        for rank, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda c: -scores[c])[:limit]


def search(conn, q, mode="best", limit=50, offset=0):
    if mode == "keyword":
        ids = keyword(conn, q, 200)
    elif mode == "meaning":
        ids = semantic(conn, q, 200)
    else:
        ids = hybrid(conn, q, 200)
    return ids[offset:offset + limit], len(ids)
