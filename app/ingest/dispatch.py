import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

from .docx_reader import read_docx
from .html_reader import read_html
from .pdf_reader import read_pdf
from .structure import extract_cards
from .text_reader import read_text

OFFICE = {".doc", ".rtf", ".odt", ".dotx", ".docm", ".dot", ".wpd", ".wps", ".pages", ".fodt", ".sxw"}


@dataclass
class ParseResult:
    cards: list
    stats: dict
    kind: str
    warnings: list = field(default_factory=list)


def _convert_to_docx(data: bytes, ext: str) -> bytes:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise ValueError(f"{ext} files need LibreOffice on the server; save the file as .docx and upload that")
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "in" + ext)
        open(src, "wb").write(data)
        subprocess.run(
            [soffice, "--headless", "--convert-to", "docx", "--outdir", d, src],
            check=True, capture_output=True, timeout=180,
            env={**os.environ, "HOME": d},
        )
        out = os.path.join(d, "in.docx")
        if not os.path.exists(out):
            raise ValueError(f"could not convert {ext} file")
        return open(out, "rb").read()


def parse_file(filename: str, data: bytes) -> ParseResult:
    ext = os.path.splitext(filename)[1].lower()
    if ext in OFFICE:
        data, ext = _convert_to_docx(data, ext), ".docx"
    if data[:2] == b"PK" and ext not in (".docx",):
        ext = ".docx"
    if data[:5] == b"%PDF-":
        ext = ".pdf"

    if ext == ".docx":
        paras, kind = read_docx(data), "docx"
    elif ext == ".pdf":
        paras, kind = read_pdf(data), "pdf"
    elif ext in (".html", ".htm", ".xhtml"):
        paras, kind = read_html(data), "html"
    else:
        paras, kind = read_text(data), "text"
    return _finish(paras, kind)


def parse_html_string(html: str, text: str = "") -> ParseResult:
    """Pasted clipboard content (Google Docs, Word, web page)."""
    if html and html.strip():
        return _finish(read_html(html, is_fragment=True), "paste-html")
    return _finish(read_text(text), "paste-text")


def _finish(paras, kind):
    cards, stats = extract_cards(paras)
    warnings = []
    if paras and not cards:
        warnings.append("No cards found. Cards need a tag line, then a cite line like 'Smith 19 [credentials...]', then the text.")
    if kind in ("text", "paste-text"):
        warnings.append("Plain text has no highlighting, so the highlighted (spoken) text could not be recovered.")
    if kind == "pdf" and cards and not any(t == 2 for c in cards for p in c.body for _, t in p):
        warnings.append("No highlighting was detected in this PDF.")
    stats["paragraphs"] = len(paras)
    return ParseResult(cards, stats, kind, warnings)
