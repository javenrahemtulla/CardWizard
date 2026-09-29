"""PDF reader (PyMuPDF).

Highlight (tier 2) comes from highlight annotations and filled rectangles
behind text.  Underline / bold (tier 1) comes from thin lines just under a
character, underline annotations, and bold fonts.

PDF has no paragraphs, only positioned lines, so paragraphs are rebuilt: a line
ends its paragraph when the first word of the next line would have fitted on
it (a normal wrapped line never leaves room for that word).  A large bold line
followed by smaller text also starts a new paragraph (tag -> cite).
"""
import unicodedata

import pymupdf

from .model import Para, fill_read_gaps, merge_runs


def _is_bg(color):
    """A filled rect counts as highlight unless it is white/near-white/black."""
    if not color:
        return False
    r, g, b = color[:3]
    return not (min(r, g, b) > 0.93 or max(r, g, b) < 0.15)


def _page_marks(page):
    hl, ul = [], []
    for a in page.annots() or []:
        if a.type[0] == 8:  # highlight annotation
            try:
                for i in range(0, len(a.vertices), 4):
                    hl.append(pymupdf.Quad(a.vertices[i:i + 4]).rect)
            except Exception:
                hl.append(a.rect)
        elif a.type[0] == 9:  # underline annotation
            ul.append(a.rect)
    try:
        drawings = page.get_drawings()
    except Exception:
        drawings = []
    for d in drawings:
        rect = d["rect"]
        if d.get("fill") and _is_bg(d["fill"]) and 2 < rect.height < 30 and rect.width > 2 and d.get("type") in ("f", "fs"):
            hl.append(rect)
        elif rect.height < 2.5 and rect.width > 2:
            ul.append(rect)
    return hl, ul


def _in_rect(cb, rect):
    """Character centre lies inside the rectangle (horizontally) and the two overlap vertically by at least half."""
    cx = (cb[0] + cb[2]) / 2
    if not (rect.x0 - 0.5 <= cx <= rect.x1 + 0.5):
        return False
    overlap = min(cb[3], rect.y1) - max(cb[1], rect.y0)
    return overlap >= 0.5 * min(cb[3] - cb[1], rect.height)


def _underlined(cb, ul):
    cx = (cb[0] + cb[2]) / 2
    for r in ul:
        if r.x0 - 1 <= cx <= r.x1 + 1 and -3.5 <= r.y0 - cb[3] <= 3.5:
            return True
    return False


def _page_lines(page):
    hl, ul = _page_marks(page)
    out = []
    for block in page.get_text("rawdict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            chars = []  # (c, bbox, tier, bold, size)
            for span in line["spans"]:
                bold = bool(span["flags"] & 16) or "bold" in span["font"].lower()
                for ch in span["chars"]:
                    c, cb = ch["c"], ch["bbox"]
                    if "\ufb00" <= c <= "\ufb06":  # ligatures: ﬁ ﬂ ﬀ ...
                        c = unicodedata.normalize("NFKC", c)
                    tier = 0
                    if c.strip():
                        if any(_in_rect(cb, r) for r in hl):
                            tier = 2
                        elif _underlined(cb, ul) or bold:
                            tier = 1
                    chars.append((c, cb, tier, bold, span["size"]))
            visible = [c for c in chars if c[0].strip()]
            if not visible:
                continue
            x0, y0, x1, y1 = line["bbox"]
            # width of the first word on the line
            fw_end = None
            for k, c in enumerate(chars):
                if c[0].strip():
                    fw_end = k
                elif fw_end is not None:
                    break
            first = [c for c in chars[: (fw_end or 0) + 1] if c[0].strip()]
            first_w = (first[-1][1][2] - first[0][1][0]) if first else 0
            out.append({
                "chars": chars, "x0": x0, "x1": x1, "y0": y0, "y1": y1, "first_w": first_w,
                "x1v": max(c[1][2] for c in visible), "space": 0.3 * max(c[4] for c in visible),
                "size": max(c[4] for c in visible), "bold": sum(1 for c in visible if c[3]) / len(visible),
            })
    return _merge_rows(out)


def _merge_rows(frags):
    """Some producers emit every font change on a row as a separate 'line'.
    Merge fragments that sit on the same row and move left to right."""
    rows = []
    for f in frags:
        if rows:
            r = rows[-1]
            same_row = abs(f["y0"] - r["y0"]) < 0.4 * (r["y1"] - r["y0"]) and f["x0"] >= r["last_x0"] - 1
            if same_row:
                r["chars"] += f["chars"]
                r["x1"] = max(r["x1"], f["x1"])
                r["x1v"] = max(r["x1v"], f["x1v"])
                r["size"] = max(r["size"], f["size"])
                r["y1"] = max(r["y1"], f["y1"])
                r["space"] = max(r["space"], f["space"])
                r["last_x0"] = f["x0"]
                vis = [c for c in r["chars"] if c[0].strip()]
                r["bold"] = sum(1 for c in vis if c[3]) / len(vis) if vis else 0
                continue
        f["last_x0"] = f["x0"]
        rows.append(f)
    return rows


def read_pdf(data: bytes):
    doc = pymupdf.open(stream=data, filetype="pdf")
    paras = []
    cur = []  # runs

    sizes = []  # (size, highlighted) of visible characters in the current paragraph

    def flush():
        nonlocal cur, sizes
        runs = fill_read_gaps(merge_runs(cur))
        if "".join(r[0] for r in runs).strip():
            plain = sorted(s for s, hl in sizes if not hl) or sorted(s for s, _ in sizes)
            paras.append(Para(runs, 0, plain[len(plain) // 2] if plain else None))
        cur, sizes = [], []

    pages = [_page_lines(page) for page in doc]
    ends = sorted(l["x1v"] for ls in pages for l in ls if l["x1v"] - l["x0"] > 100)
    margin = ends[int(len(ends) * 0.98)] if ends else 0

    prev = None
    for pno, lines in enumerate(pages):
        for ln in lines:
            if prev is not None:
                # next word would clearly have fitted on the previous line: paragraph ended there
                gap_fits = prev["x1v"] + prev["space"] + ln["first_w"] + 4 <= margin
                gap_v = prev["page"] == pno and ln["y0"] - prev["y1"] > 0.9 * (prev["y1"] - prev["y0"])
                style_break = prev["bold"] > 0.9 and prev["size"] >= 12 and (ln["bold"] < 0.9 or ln["size"] <= prev["size"] - 1.5)
                if gap_fits or gap_v or style_break:
                    flush()
            runs = [(c[0], c[2], c[3]) for c in ln["chars"]]
            # drop end-of-line hyphenation, otherwise join lines with a space
            if runs and runs[-1][0] == "-":
                runs.pop()
            else:
                last = runs[-1] if runs else ("", 0, False)
                if not last[0].isspace():
                    runs.append((" ", last[1], False))
            cur.extend(runs)
            sizes.extend((c[4], c[2] == 2) for c in ln["chars"] if c[0].strip())
            ln["page"] = pno
            prev = ln
    flush()
    return paras
