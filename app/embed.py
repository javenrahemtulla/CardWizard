"""Local embeddings (no API).  BGE-small via fastembed (ONNX, CPU).

Set CARDWIZARD_EMBEDDER=hash to use a dummy bag-of-words hashing embedder for
tests.  It is NOT semantic; it only exercises the plumbing.
"""
import os
import re
import threading
import time
import zlib

import numpy as np

MODEL = os.environ.get("CARDWIZARD_MODEL", "BAAI/bge-small-en-v1.5")
DIM = 384


class HashEmbedder:
    def _vec(self, text):
        v = np.zeros(DIM, dtype=np.float32)
        for w in re.findall(r"[a-z0-9]+", text.lower()):
            v[zlib.crc32(w.encode()) % DIM] += 1
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_docs(self, texts):
        return np.stack([self._vec(t) for t in texts])

    def embed_query(self, text):
        return self._vec(text)


class FastEmbedder:
    def __init__(self):
        from fastembed import TextEmbedding

        cache = os.environ.get("CARDWIZARD_MODEL_CACHE")
        self.m = TextEmbedding(MODEL, cache_dir=cache) if cache else TextEmbedding(MODEL)

    def embed_docs(self, texts):
        return np.stack(list(self.m.embed(texts))).astype(np.float32)

    def embed_query(self, text):
        return np.asarray(next(iter(self.m.query_embed([text]))), dtype=np.float32)


class Embedding:
    """Lazy holder; `state` is 'loading' | 'ready' | 'disabled'."""

    def __init__(self):
        self.impl = None
        self.state = "loading"
        self.error = None
        self.lock = threading.Lock()

    def load(self):
        with self.lock:
            if self.impl or self.state == "disabled":
                return self.impl
            try:
                self.impl = HashEmbedder() if os.environ.get("CARDWIZARD_EMBEDDER") == "hash" else FastEmbedder()
                self.state = "ready"
            except Exception as e:  # model missing / no network on first run
                self.state, self.error = "disabled", str(e)[:300]
            return self.impl


EMB = Embedding()


def doc_text(tag, spoken, context, full):
    body = spoken or context or full
    return f"{tag}\n{body[:1500]}"


def worker(connect, stop):
    """Embeds cards that have no vector yet.  Runs in a background thread."""
    while not stop.is_set():
        conn = connect()
        try:
            rows = conn.execute(
                "SELECT id, tag, spoken, context, full_text FROM cards WHERE embedding IS NULL LIMIT 32"
            ).fetchall()
            if rows:
                impl = EMB.load()
                if not impl:
                    time.sleep(30)
                    continue
                vecs = impl.embed_docs([doc_text(r["tag"], r["spoken"], r["context"], r["full_text"]) for r in rows])
                for r, v in zip(rows, vecs):
                    v = v / (np.linalg.norm(v) or 1.0)
                    conn.execute("UPDATE cards SET embedding=? WHERE id=?", (v.astype(np.float32).tobytes(), r["id"]))
                conn.commit()
                continue
        finally:
            conn.close()
        stop.wait(2)
