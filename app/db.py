import hashlib
import json
import os
import re
import sqlite3
import threading
import time

DATA_DIR = os.environ.get("CARDWIZARD_DATA", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
DB_PATH = os.path.join(DATA_DIR, "cards.db")
FILES_DIR = os.path.join(DATA_DIR, "files")

_write_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY, filename TEXT, kind TEXT, sha256 TEXT UNIQUE,
  uploaded_at REAL, n_cards INTEGER DEFAULT 0, stored_as TEXT);
CREATE TABLE IF NOT EXISTS cards(
  id INTEGER PRIMARY KEY, tag TEXT, cite TEXT, cite_json TEXT, cite_author TEXT, cite_year INTEGER,
  url TEXT, body_json TEXT, spoken TEXT, context TEXT, full_text TEXT,
  method TEXT, cite_ok INTEGER, key TEXT UNIQUE, embedding BLOB, created_at REAL);
CREATE TABLE IF NOT EXISTS sources(
  card_id INTEGER, doc_id INTEGER, tag TEXT, PRIMARY KEY(card_id, doc_id));
CREATE INDEX IF NOT EXISTS sources_doc ON sources(doc_id);
CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
  tag, cite, spoken, context, full_text, tokenize='porter unicode61 remove_diacritics 2');
"""


def connect():
    os.makedirs(FILES_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init():
    c = connect()
    c.executescript(SCHEMA)
    c.commit()
    c.close()


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def card_texts(card):
    spoken = " ".join(t for p in card.body for t, tier in p if tier == 2)
    context = " ".join(t for p in card.body for t, tier in p if tier == 1)
    full = "\n".join("".join(t for t, _ in p) for p in card.body)
    return re.sub(r"\s+", " ", spoken).strip(), re.sub(r"\s+", " ", context).strip(), full


def card_key(card):
    spoken, _ctx, full = card_texts(card)
    return hashlib.sha1((_norm(full) + "|" + _norm(spoken)).encode()).hexdigest()


def add_document(conn, filename, kind, sha, stored_as):
    from .ingest.structure import parse_cite  # noqa
    with _write_lock:
        cur = conn.execute(
            "INSERT INTO documents(filename, kind, sha256, uploaded_at, stored_as) VALUES(?,?,?,?,?)",
            (filename, kind, sha, time.time(), stored_as),
        )
        conn.commit()
        return cur.lastrowid


def _refresh_fts(conn, card_id):
    r = conn.execute("SELECT cite, spoken, context, full_text FROM cards WHERE id=?", (card_id,)).fetchone()
    tags = " | ".join(x["tag"] for x in conn.execute("SELECT DISTINCT tag FROM sources WHERE card_id=?", (card_id,)))
    conn.execute("DELETE FROM cards_fts WHERE rowid=?", (card_id,))
    conn.execute(
        "INSERT INTO cards_fts(rowid, tag, cite, spoken, context, full_text) VALUES(?,?,?,?,?,?)",
        (card_id, tags, r["cite"], r["spoken"], r["context"], r["full_text"]),
    )


def add_cards(conn, doc_id, cards):
    """Insert cards; a card whose text and highlighting match an existing one
    only adds a source.  Returns (new, duplicate)."""
    from .ingest.structure import parse_cite

    new = dup = 0
    with _write_lock:
        for c in cards:
            key = card_key(c)
            row = conn.execute("SELECT id FROM cards WHERE key=?", (key,)).fetchone()
            if row:
                cid = row["id"]
                dup += 1
            else:
                spoken, context, full = card_texts(c)
                author, year, url = parse_cite(c.cite_text)
                cur = conn.execute(
                    "INSERT INTO cards(tag, cite, cite_json, cite_author, cite_year, url, body_json, spoken, context,"
                    " full_text, method, cite_ok, key, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (c.tag, c.cite_text, json.dumps(c.cite_runs), author, year, url, json.dumps(c.body),
                     spoken, context, full, c.method, int(c.cite_ok), key, time.time()),
                )
                cid = cur.lastrowid
                new += 1
            conn.execute("INSERT OR IGNORE INTO sources(card_id, doc_id, tag) VALUES(?,?,?)", (cid, doc_id, c.tag))
            _refresh_fts(conn, cid)
        conn.execute("UPDATE documents SET n_cards=? WHERE id=?", (len(cards), doc_id))
        conn.commit()
    return new, dup


def delete_document(conn, doc_id):
    with _write_lock:
        card_ids = [r["card_id"] for r in conn.execute("SELECT card_id FROM sources WHERE doc_id=?", (doc_id,))]
        conn.execute("DELETE FROM sources WHERE doc_id=?", (doc_id,))
        for cid in card_ids:
            if conn.execute("SELECT 1 FROM sources WHERE card_id=?", (cid,)).fetchone():
                _refresh_fts(conn, cid)
            else:
                conn.execute("DELETE FROM cards WHERE id=?", (cid,))
                conn.execute("DELETE FROM cards_fts WHERE rowid=?", (cid,))
        row = conn.execute("SELECT stored_as FROM documents WHERE id=?", (doc_id,)).fetchone()
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        conn.commit()
    if row and row["stored_as"]:
        try:
            os.remove(os.path.join(FILES_DIR, row["stored_as"]))
        except OSError:
            pass
