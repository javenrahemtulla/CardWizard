import base64
import hashlib
import json
import os
import secrets
import threading
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, embed, search
from .ingest import parse_file, parse_html_string

MAX_BYTES = int(os.environ.get("CARDWIZARD_MAX_MB", "100")) * 1024 * 1024
PASSWORD = os.environ.get("SITE_PASSWORD")

_stop = threading.Event()


@asynccontextmanager
async def lifespan(_app):
    db.init()
    _stop.clear()
    threading.Thread(target=embed.worker, args=(db.connect, _stop), daemon=True).start()
    yield
    _stop.set()


app = FastAPI(title="Card Wizard", lifespan=lifespan)


@app.middleware("http")
async def shared_password(request: Request, call_next):
    """Optional single shared password (HTTP Basic, any username)."""
    if PASSWORD and request.url.path != "/healthz":
        ok = False
        h = request.headers.get("authorization", "")
        if h.lower().startswith("basic "):
            try:
                given = base64.b64decode(h[6:]).decode().split(":", 1)[-1]
                ok = secrets.compare_digest(given, PASSWORD)
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Card Wizard"'})
    return await call_next(request)


@app.get("/healthz")
def healthz():
    return {"ok": True}


def _sources(conn, ids):
    out = {i: [] for i in ids}
    if not ids:
        return out
    q = ",".join("?" * len(ids))
    for r in conn.execute(
        f"SELECT s.card_id, d.id AS doc_id, d.filename FROM sources s JOIN documents d ON d.id=s.doc_id WHERE s.card_id IN ({q})",
        ids,
    ):
        out[r["card_id"]].append({"doc_id": r["doc_id"], "filename": r["filename"]})
    return out


def _card_row(r, src, full=False):
    d = {
        "id": r["id"], "tag": r["tag"], "cite": r["cite"], "cite_runs": json.loads(r["cite_json"]),
        "author": r["cite_author"], "year": r["cite_year"], "url": r["url"], "spoken": r["spoken"],
        "method": r["method"], "cite_ok": bool(r["cite_ok"]), "sources": src,
    }
    if full:
        d["body"] = json.loads(r["body_json"])
    return d


@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1), mode: str = "best", limit: int = 30, offset: int = 0):
    conn = db.connect()
    try:
        ids, total = search.search(conn, q, mode, min(limit, 100), offset)
        if not ids:
            return {"total": total, "cards": [], "semantic": embed.EMB.state}
        marks = ",".join("?" * len(ids))
        rows = {r["id"]: r for r in conn.execute(f"SELECT * FROM cards WHERE id IN ({marks})", ids)}
        srcs = _sources(conn, ids)
        return {"total": total, "semantic": embed.EMB.state,
                "cards": [_card_row(rows[i], srcs[i]) for i in ids if i in rows]}
    finally:
        conn.close()


@app.get("/api/cards/{card_id}")
def api_card(card_id: int):
    conn = db.connect()
    try:
        r = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        if not r:
            raise HTTPException(404)
        return _card_row(r, _sources(conn, [card_id])[card_id], full=True)
    finally:
        conn.close()


def _ingest(conn, filename, kind, sha, stored_as, result):
    doc_id = db.add_document(conn, filename, kind, sha, stored_as)
    new, dup = db.add_cards(conn, doc_id, result.cards)
    return {"filename": filename, "cards": len(result.cards), "new": new, "duplicates": dup,
            "warnings": result.warnings, "stats": result.stats}


@app.post("/api/upload")
def api_upload(files: list[UploadFile] = File(...)):
    conn = db.connect()
    results = []
    try:
        for f in files:
            data = f.file.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                results.append({"filename": f.filename, "error": f"larger than {MAX_BYTES // 1024 // 1024} MB"})
                continue
            sha = hashlib.sha256(data).hexdigest()
            if conn.execute("SELECT 1 FROM documents WHERE sha256=?", (sha,)).fetchone():
                results.append({"filename": f.filename, "error": "this exact file is already uploaded"})
                continue
            try:
                result = parse_file(f.filename or "file", data)
            except Exception as e:
                results.append({"filename": f.filename, "error": f"could not read file: {e}"})
                continue
            stored = sha + os.path.splitext(f.filename or "")[1].lower()
            with open(os.path.join(db.FILES_DIR, stored), "wb") as fh:
                fh.write(data)
            results.append(_ingest(conn, f.filename, result.kind, sha, stored, result))
    finally:
        conn.close()
    return {"results": results}


@app.post("/api/paste")
def api_paste(payload: dict = Body(...)):
    html, text = payload.get("html") or "", payload.get("text") or ""
    name = (payload.get("name") or "").strip() or "Pasted text"
    if not (html.strip() or text.strip()):
        raise HTTPException(400, "nothing to import")
    sha = hashlib.sha256((html + "\0" + text).encode()).hexdigest()
    conn = db.connect()
    try:
        if conn.execute("SELECT 1 FROM documents WHERE sha256=?", (sha,)).fetchone():
            return {"results": [{"filename": name, "error": "this exact text is already uploaded"}]}
        result = parse_html_string(html, text)
        stored = sha + ".html"
        with open(os.path.join(db.FILES_DIR, stored), "w", encoding="utf-8") as fh:
            fh.write(html or text)
        return {"results": [_ingest(conn, name, result.kind, sha, stored, result)]}
    finally:
        conn.close()


@app.get("/api/documents")
def api_documents():
    conn = db.connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, filename, kind, uploaded_at, n_cards FROM documents ORDER BY uploaded_at DESC")]
    finally:
        conn.close()


@app.delete("/api/documents/{doc_id}")
def api_delete_document(doc_id: int):
    conn = db.connect()
    try:
        db.delete_document(conn, doc_id)
    finally:
        conn.close()
    return {"ok": True}


@app.get("/api/documents/{doc_id}/file")
def api_document_file(doc_id: int):
    conn = db.connect()
    try:
        r = conn.execute("SELECT filename, stored_as FROM documents WHERE id=?", (doc_id,)).fetchone()
    finally:
        conn.close()
    if not r or not r["stored_as"]:
        raise HTTPException(404)
    return FileResponse(os.path.join(db.FILES_DIR, r["stored_as"]), filename=r["filename"])


@app.get("/api/status")
def api_status():
    conn = db.connect()
    try:
        cards = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM cards WHERE embedding IS NULL").fetchone()[0]
        docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    finally:
        conn.close()
    return {"cards": cards, "documents": docs, "embedding_pending": pending,
            "semantic": embed.EMB.state, "semantic_error": embed.EMB.error}


app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"), html=True), name="static")
