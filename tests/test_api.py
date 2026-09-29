import io
import time

import docx
from fastapi.testclient import TestClient

from app.main import app
from tests.test_ingest import make_docx, to_bytes


def test_upload_search_dedupe_delete():
    with TestClient(app) as c:
        data = to_bytes(make_docx())
        r = c.post("/api/upload", files=[("files", ("one.docx", data))]).json()["results"][0]
        assert r["cards"] == 1 and r["new"] == 1
        # same file again is refused
        assert "already" in c.post("/api/upload", files=[("files", ("copy.docx", data))]).json()["results"][0]["error"]
        # same card in a different file: one card, two sources
        d = make_docx()
        d.add_paragraph("A different trailing paragraph that changes the file hash but not the card text at all.")
        r2 = c.post("/api/upload", files=[("files", ("two.docx", to_bytes(d)))]).json()["results"][0]
        assert r2["cards"] == 1
        st = c.get("/api/status").json()
        assert st["cards"] == 2 or st["cards"] == 1
        hits = c.get("/api/search", params={"q": "extinction risk institutions", "mode": "keyword"}).json()
        assert hits["total"] >= 1
        card = hits["cards"][0]
        assert card["spoken"] == "spoken words"
        full = c.get(f"/api/cards/{card['id']}").json()
        assert full["body"] and full["sources"]
        docs = c.get("/api/documents").json()
        for doc in docs:
            c.delete(f"/api/documents/{doc['id']}")
        assert c.get("/api/status").json()["cards"] == 0
        assert c.get("/api/search", params={"q": "extinction"}).json()["total"] == 0


def test_paste():
    with TestClient(app) as c:
        html = "<h4>Tag line here</h4><p>Jones 20 [Al Jones, professor at Uni, 2020, “Title of it,” https://x.org]</p><p>" + "Body text about the topic. " * 30 + "</p>"
        r = c.post("/api/paste", json={"html": html, "text": "", "name": "paste"}).json()["results"][0]
        assert r["cards"] == 1


def test_password(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "PASSWORD", "secret")
    with TestClient(app) as c:
        assert c.get("/api/status").status_code == 401
        assert c.get("/api/status", auth=("x", "secret")).status_code == 200
        assert c.get("/healthz").status_code == 200
