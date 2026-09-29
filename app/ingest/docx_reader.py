"""Read .docx directly from XML so highlight / underline / char styles survive."""
import io
import re
import zipfile
import xml.etree.ElementTree as ET

from .model import Para, merge_runs, fill_read_gaps

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def q(tag):
    return "{%s}%s" % (W, tag)


NAMED_LEVELS = {"pocket": 1, "hat": 2, "block": 3, "tag": 4}
UNDERLINE_STYLE_NAME = re.compile(r"underline|emphasis", re.I)


def _val(el):
    return el.get(q("val")) if el is not None else None


def _rpr_props(rpr):
    """Formatting flags from a w:rPr element."""
    p = {}
    if rpr is None:
        return p
    hl = rpr.find(q("highlight"))
    if hl is not None and _val(hl) not in (None, "none"):
        p["hl"] = True
    u = rpr.find(q("u"))
    if u is not None and _val(u) != "none":
        p["u"] = True
    shd = rpr.find(q("shd"))
    if shd is not None and (shd.get(q("fill")) or "auto").lower() not in ("auto", "ffffff", "fff"):
        p["hl"] = True
    b = rpr.find(q("b"))
    if b is not None and _val(b) not in ("0", "false"):
        p["b"] = True
    return p


class Styles:
    def __init__(self, xml_bytes):
        self.by_id = {}
        if not xml_bytes:
            return
        root = ET.fromstring(xml_bytes)
        for s in root.findall(q("style")):
            sid = s.get(q("styleId"))
            name = _val(s.find(q("name"))) or sid
            ppr = s.find(q("pPr"))
            ol = ppr.find(q("outlineLvl")) if ppr is not None else None
            self.by_id[sid] = {
                "name": name,
                "based": _val(s.find(q("basedOn"))),
                "props": _rpr_props(s.find(q("rPr"))),
                "outline": int(_val(ol)) if ol is not None and (_val(ol) or "").isdigit() else None,
            }

    def _chain(self, sid):
        seen = set()
        while sid in self.by_id and sid not in seen:
            seen.add(sid)
            yield self.by_id[sid]
            sid = self.by_id[sid]["based"]

    def char_props(self, sid):
        props = {}
        for st in self._chain(sid):
            for k, v in st["props"].items():
                props.setdefault(k, v)
            if UNDERLINE_STYLE_NAME.search(st["name"] or ""):
                props["u"] = True
        return props

    def heading_level(self, sid):
        for st in self._chain(sid):
            name = (st["name"] or "").lower().strip()
            m = re.match(r"heading\s*(\d)$", name)
            if m:
                return int(m.group(1))
            if name in NAMED_LEVELS:
                return NAMED_LEVELS[name]
            if st["outline"] is not None and st["outline"] < 9:
                return st["outline"] + 1
        return 0


def _run_text(r):
    parts = []
    for c in r:
        if c.tag == q("t"):
            parts.append(c.text or "")
        elif c.tag in (q("tab"), q("br"), q("cr")):
            parts.append(" ")
        elif c.tag == q("noBreakHyphen"):
            parts.append("-")
    return "".join(parts)


def _paragraph(p, styles):
    ppr = p.find(q("pPr"))
    level = 0
    if ppr is not None:
        sid = _val(ppr.find(q("pStyle")))
        level = styles.heading_level(sid) if sid else 0
        ol = ppr.find(q("outlineLvl"))
        if level == 0 and ol is not None and (_val(ol) or "").isdigit() and int(_val(ol)) < 9:
            level = int(_val(ol)) + 1
    runs = []
    for r in p.iter(q("r")):
        text = _run_text(r)
        if not text:
            continue
        props = {}
        rpr = r.find(q("rPr"))
        if rpr is not None:
            rsid = _val(rpr.find(q("rStyle")))
            if rsid:
                props.update(styles.char_props(rsid))
            props.update(_rpr_props(rpr))
        tier = 2 if props.get("hl") else 1 if (props.get("u") or props.get("b")) else 0
        runs.append((text, tier, bool(props.get("b"))))
    return Para(fill_read_gaps(merge_runs(runs)), level)


def read_docx(data: bytes):
    z = zipfile.ZipFile(io.BytesIO(data))
    styles = Styles(z.read("word/styles.xml") if "word/styles.xml" in z.namelist() else None)
    root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(q("body"))
    paras = []

    def walk(container):
        for el in container:
            if el.tag == q("p"):
                paras.append(_paragraph(el, styles))
            elif el.tag in (q("tbl"), q("tr"), q("tc"), q("sdt"), q("sdtContent")):
                walk(el)

    walk(body)
    return paras
