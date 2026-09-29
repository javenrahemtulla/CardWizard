"""HTML reader: Google Docs exports, pasted clipboard HTML, saved web pages.

Highlight / underline detection handles <u>, <mark>, inline styles and
class-based styles (Google Docs puts everything in a <style> block).
"""
import re

from lxml import html as lhtml

from .model import Para, fill_read_gaps, merge_runs

BLOCKS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote", "pre", "section", "article", "br"}
HEADING = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
NO_BG = {"", "transparent", "none", "inherit", "initial", "#ffffff", "white", "rgb(255, 255, 255)", "rgb(255,255,255)", "#fff"}


def _css_classes(doc):
    out = {}
    for st in doc.iter("style"):
        css = st.text or ""
        for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
            for s in sel.split(","):
                s = s.strip()
                if s.startswith(".") and re.fullmatch(r"\.[\w-]+", s):
                    out.setdefault(s[1:], "")
                    out[s[1:]] += ";" + body
    return out


def _style_flags(style):
    style = (style or "").lower().replace(" ", "")
    flags = {}
    m = re.search(r"background(?:-color)?:([^;]+)", style)
    if m and m.group(1) not in {x.replace(" ", "") for x in NO_BG}:
        flags["hl"] = True
    if re.search(r"text-decoration(?:-line)?:[^;]*underline", style):
        flags["u"] = True
    m = re.search(r"font-weight:(\w+)", style)
    if m and (m.group(1) in ("bold", "bolder") or (m.group(1).isdigit() and int(m.group(1)) >= 600)):
        flags["b"] = True
    return flags


def read_html(data, is_fragment=False):
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError:
            data = data.decode("latin-1")
    doc = lhtml.fromstring("<div>" + data + "</div>") if is_fragment else lhtml.fromstring(data)
    classes = _css_classes(doc)
    for bad in doc.xpath("//script|//style|//head"):
        bad.getparent().remove(bad)

    paras, cur = [], {"runs": [], "level": 0}

    def flush():
        runs = fill_read_gaps(merge_runs(cur["runs"]))
        if "".join(r[0] for r in runs).strip():
            paras.append(Para(runs, cur["level"]))
        cur["runs"], cur["level"] = [], 0

    def flags_for(el, inherited):
        f = dict(inherited)
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag == "u":
            f["u"] = True
        if tag == "mark":
            f["hl"] = True
        if tag in ("b", "strong"):
            f["b"] = True
        if tag == "font" and el.get("style") is None and (el.get("bgcolor")):
            f["hl"] = True
        for c in (el.get("class") or "").split():
            f.update(_style_flags(classes.get(c)))
        f.update(_style_flags(el.get("style")))
        return f

    def walk(el, inherited):
        if not isinstance(el.tag, str):
            return
        tag = el.tag
        f = flags_for(el, inherited)
        block = tag in BLOCKS
        if block:
            flush()
            if tag in HEADING:
                cur["level"] = HEADING[tag]
        if el.text:
            add(el.text, f)
        for ch in el:
            walk(ch, f)
            if ch.tail:
                add(ch.tail, f)
        if block:
            flush()

    def add(text, f):
        text = re.sub(r"[ \t\r\n ]+", " ", text)
        if text:
            tier = 2 if f.get("hl") else 1 if (f.get("u") or f.get("b")) else 0
            cur["runs"].append((text, tier, bool(f.get("b"))))

    walk(doc, {})
    flush()
    return paras
