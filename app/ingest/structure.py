"""Turn a flat list of paragraphs into cards.

Works with or without heading styles.  The anchor is the cite line
("Author 19 [credentials, date, "Title," url]"), which is the most reliable
signal in any format.  The tag is the paragraph above the cite; the body runs
until the next tag or the next heading (levels 1-4).  Heading 4 is used as
extra evidence, never as a requirement.
"""
import re

from .model import Card, Para, fill_read_gaps, merge_runs, split_runs

NAME = r"(?:[A-Z][\w'’.\-]*|[A-Z]\.)"
PART = r"(?:van|von|de|del|der|den|la|le|da|di|al|el|bin|ibn|dos|du)"
ONE = rf"{NAME}(?:\s+(?:{PART}\s+)?{NAME}){{0,3}}"
AUTHOR = rf"{ONE}(?:\s+et\s+al\.?)?(?:\s*(?:,|and|&)\s*{ONE}(?:\s+et\s+al\.?)?){{0,3}}"
LEAD = re.compile(rf"^\s*(?P<auth>{AUTHOR})[,\s]+(?P<yr>['’‘]?\d{{2}}|(?:19|20)\d{{2}})(?!\d)")

NOT_AUTHORS = {
    "in", "on", "the", "by", "since", "during", "after", "before", "as", "at", "from", "for",
    "between", "over", "under", "until", "through", "of", "when", "while", "according", "across",
    "around", "within", "following", "about", "also", "table", "figure", "chapter", "section",
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "if", "but", "and", "or", "to", "with", "this", "that",
    "these", "those", "there", "here", "it", "its", "we", "they", "he", "she", "i", "a", "an",
    "our", "their", "his", "her", "my", "your", "one", "two", "three", "four", "five", "vote",
    "item", "page", "article", "exhibit", "appendix", "part", "note", "step", "phase", "version", "volume",
    "number", "week", "day", "year", "quarter", "case", "example", "answer", "warrant", "impact", "link",
}
CRED = re.compile(
    r"professor|director|fellow|editor|senior|researcher|associate|ph\.?d|university|institute|"
    r"analyst|journalist|author|chair|dean|scholar|lecturer|correspondent|writer|reporter|"
    r"economist|historian|philosopher|policy|center|centre|department|college|school|"
    r"foundation|council|staff|candidate|consultant|adviser|advisor|expert|founder|activist|columnist|"
    r"commentator|contributor|president|ceo|attorney|lawyer|physician|translated|interviewed|producer|"
    r"anchor|senator|agency|organization|company|newspaper|magazine|think tank",
    re.I,
)
DATE = (r"(?:(?:\d{1,2}|xx)[-/.](?:\d{1,2}|xx)[-/.](?:\d{2}|\d{4})|"
        r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?(?:19|20)\d{2}|"
        r"(?:19|20)\d{2})")
MONTH = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b|"
    r"\b(?:\d{1,2}|xx)[-/](?:\d{1,2}|xx)[-/]\d{2,4}\b|"
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(?:19|20)\d{2}\b",
    re.I,
)
URL = re.compile(r"https?://|www\.|doi\.org|\.(com|org|edu|gov|net)\b", re.I)

# other ways a cite can open besides "Author YY"
BY = re.compile(r"^\s*(?:By|From)\s+(?:the\s+)?[A-Z]")
BIO = re.compile(rf"^\s*{ONE}\s+(?:is|was|are|has been|serves as|works as)\s+(?:a|an|the)\b")
AUTHOR_DATE = re.compile(rf"^\s*{AUTHOR}(?:\s*,\s*[^,\d\[]{{0,40}})?\s*,\s*{DATE}", re.I)


def norm_year(s):
    s = s.strip("'’‘")
    y = int(s)
    if y < 100:
        y += 2000 if y <= 40 else 1900
    return y


def lead_match(text):
    m = LEAD.match(text)
    if not m:
        return None
    first = re.split(r"\W+", m.group("auth").strip())[0].lower()
    if first in NOT_AUTHORS:
        return None
    auth = m.group("auth").strip()
    if auth.endswith(("’s", "'s")):  # "Microsoft's 2025 report noted..." is a sentence, not a cite
        return None
    after = text[m.end():m.end() + 4].lstrip()
    if after[:1].islower():  # "... 2025 environmental report ..."
        return None
    return m


def lead_kind(text):
    """How this paragraph opens, if it opens like a cite; else None."""
    if lead_match(text):
        return "author-year"
    if BY.match(text):
        return "by"
    first = re.split(r"\W+", text.strip())[0].lower() if text.strip() else ""
    if first in NOT_AUTHORS or not text[:1].isupper():
        return None
    if BIO.match(text):
        return "bio"
    if AUTHOR_DATE.match(text):
        return "author-date"
    return None


def _features(text, tag_before, next_len):
    s = 0
    head = text[:250]
    if "[" in head:
        s += 2
    if URL.search(text[:1200]):
        s += 1
    if CRED.search(text[:600]):
        s += 1
    if MONTH.search(text[:700]):
        s += 1
    if re.search(r"[“\"][^”\"]{6,}[”\"]", text[:900]):
        s += 1
    if re.search(r"accessed|retrieved|\bdoa\b|\bpp?\.\s*\d", text[:900], re.I):
        s += 1
    if tag_before:
        s += 2
    if next_len > 300:
        s += 1
    return s


def has_hard_cue(text):
    """A bracket, URL, quoted title, or access note.  Dates and job titles alone are not enough
    (a numbered docket entry has both)."""
    return bool(
        "[" in text[:250] or URL.search(text[:1200])
        or re.search(r"[“\"][^”\"]{6,}[”\"]", text[:900])
        or re.search(r"accessed|retrieved|\bdoa\b|\bpp?\.\s*\d", text[:900], re.I)
    )


def cite_score(text, tag_before, next_len):
    """Confidence (roughly 0-9) that a paragraph is a cite line."""
    kind = lead_kind(text)
    if kind:
        if not has_hard_cue(text):
            return 0
        s = _features(text, tag_before, next_len)
        if len(text) > 2500 and "[" not in text[:250] and not URL.search(text[:700]):
            s -= 3
        if len(text) < 25:
            s -= 2
        return s
    # No recognisable opening (e.g. "Franco Berardi Bifo, translated by X, 2007, ..."):
    # accept only with a year near the front, a long paragraph after, and several other cues.
    first = re.split(r"\W+", text.strip())[0].lower() if text.strip() else ""
    if (
        text[:1].isupper() and first not in NOT_AUTHORS and 40 < len(text) < 900 and next_len > 300
        and re.search(r"\b(19|20)\d{2}\b", text[:250])
    ):
        return _features(text, tag_before, next_len) if _features(text, False, next_len) >= 4 else 0
    return 0


CITE_TAIL = re.compile(
    r"^[\s,.;:\])]*(?:(?:DOA|doa|accessed|retrieved)[:\s]*\S{0,12}?\d[\d/\-]{4,10})?(?:\s*//\s*\S+)*(?:\s*elimafia\S*)?",
    re.I,
)


def _split_cite_and_body(runs):
    """Cite and first body paragraph sometimes share one paragraph.  Split at the closing bracket of
    the credentials block, or, for cites without brackets, after the URL and access note."""
    text = "".join(r[0] for r in runs)
    lb = text.find("[")
    if lb != -1 and lb <= 250:
        depth = 0
        for i in range(lb, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    rest = text[i + 1:]
                    # keep any trailing title/url that directly follows the bracket
                    m = re.match(r"^[\s,.;:]*(?:[“\"][^”\"]{3,300}[”\"][^\n]{0,300}?(?:https?://\S+)?)?", rest)
                    cut = i + 1 + (m.end() if m else 0)
                    if len(text) - cut > 300:
                        return split_runs(runs, cut)
                    return runs, None
    um = URL.search(text[:900])
    if um and um.group(0).startswith(("http", "www")):
        end = re.compile(r"\S+").match(text, um.start())
        cut = end.end() if end else um.end()
        cut += CITE_TAIL.match(text[cut:]).end()
        if len(text) - cut > 150:
            return split_runs(runs, cut)
    return runs, None


def _to_body_para(p):
    return [(t, r) for t, r, *_ in fill_read_gaps(merge_runs(p.runs))]


# ---- tag / heading evidence -------------------------------------------------

INLINE_A = re.compile(rf"(?<=[a-z.,!?”\"’)])(?={AUTHOR}[,\s]+(?:['’‘]?\d{{2}}|(?:19|20)\d{{2}})(?!\d))")
INLINE_BY = re.compile(r"(?<=[a-z.,!?”\"’)])(?=(?:By|From)\s+[A-Z])")


def split_inline_tag(p):
    """A bold tag and its cite can share one line ("...majority of Americans, withBy Jeffrey M. Jones [bio]").
    Split where a bold prefix ends and a cite opening begins."""
    text = p.text
    if p.level or len(text) < 80:
        return [p]
    for rx in (INLINE_BY, INLINE_A):
        for m in rx.finditer(text):
            k = m.start()
            if k < 20 or "[" not in text[k:k + 300]:
                continue
            a, b = split_runs(p.runs, k)
            pa = Para(a, 0, p.size)
            if pa.bold_frac >= 0.7 and lead_kind(text[k:]):
                return [pa, Para(b, 0, p.size)]
    return [p]


def tag_evidence(p, med_size):
    ev = 0
    if p.level == 4:
        ev += 4
    elif 1 <= p.level <= 3:
        ev += 2
    if p.bold_frac >= 0.85 and p.hl_frac < 0.3:
        ev += 2
    if p.size and med_size and p.size >= med_size + 1.5 and p.hl_frac < 0.1:
        ev += 2
    return ev


def guess_level(p, med_size):
    """PDFs have no heading styles.  A short, large, bold, unhighlighted line is a heading."""
    if p.level or not p.size:
        return p.level
    text = p.text.strip()
    if len(text) < 160 and p.size >= 16 and p.bold_frac >= 0.8 and p.hl_frac < 0.2:
        return 3 if p.size < 24 else 1
    return 0


TERMINATOR = re.compile(r"[.!?”\"’)\]:;]\s*$")


def extract_cards(paras, min_cite_score=3):
    paras = [p for p in paras if p.text.strip()]
    paras = [q for p in paras for q in split_inline_tag(p)]
    sizes = sorted(p.size for p in paras if p.size for _ in range(max(1, len(p.text) // 200)))
    med = sizes[len(sizes) // 2] if sizes else None
    paras = [Para(p.runs, guess_level(p, med), p.size) if not p.level else p for p in paras]
    n = len(paras)
    lens = [len(p.text) for p in paras]
    ev = [tag_evidence(p, med) for p in paras]
    format_available = any(
        (e >= 2 and l < 600) for e, l in zip(ev, lens)
    )

    def tag_like(i):
        """Is paragraph i plausibly a tag, given what this document's formatting looks like?"""
        if lens[i] < 4:
            return False
        if format_available:
            return lens[i] <= 700 and ev[i] >= 2
        return lens[i] <= 1200  # no formatting anywhere: the line above a cite is the tag

    cite_idx = []
    for i, p in enumerate(paras):
        if p.level in (1, 2, 3, 4):
            continue
        nxt = sum(lens[i + 1:i + 4])  # a short subtitle may sit between the cite and the body
        if cite_score(p.text, i > 0 and tag_like(i - 1) and ev[i - 1] >= 2, nxt) >= min_cite_score:
            cite_idx.append(i)
    cite_set = set(cite_idx)

    # fallback: Heading 4 + short line + long body, when the cite is in a format we do not recognise
    fallback = set()
    for i, p in enumerate(paras[:-2]):
        if p.level == 4 and (i + 1) not in cite_set and paras[i + 1].level == 0 and (i + 2) not in cite_set:
            if lens[i + 1] < 700 and lens[i + 2] > 500 and paras[i + 2].level == 0:
                fallback.add(i + 1)
    all_cites = sorted(cite_set | fallback)
    all_set = set(all_cites)

    # tag paragraphs for each cite: the paragraph above, plus stacked continuation lines of a split tag
    tag_of = {}
    for c in all_cites:
        i = c - 1
        if i < 0 or i in all_set or not tag_like(i):
            tag_of[c] = []
            continue
        idx = [i]
        while (
            format_available and idx[0] - 1 >= 0 and paras[idx[0]].level == 0 and paras[idx[0] - 1].level == 0
            and idx[0] - 1 not in all_set and tag_like(idx[0] - 1) and not TERMINATOR.search(paras[idx[0] - 1].text)
            and len(paras[idx[0] - 1].text) >= 50 and not re.match(r"[A-Z0-9(\[“\"‘'\-—•]", paras[idx[0]].text.strip())
            and len(idx) < 3
        ):
            idx.insert(0, idx[0] - 1)
        tag_of[c] = idx
    tag_para_idx = {i for v in tag_of.values() for i in v}

    cards, stats = [], {"cites": len(cite_set), "fallback_cites": len(fallback), "skipped": 0, "no_tag": 0}
    for c in all_cites:
        tag_ps = [paras[i] for i in tag_of[c]]
        cite_runs = [(t, b) for t, _r, b in paras[c].runs]
        body_paras = []
        a, b = _split_cite_and_body(paras[c].runs)
        if b:
            cite_runs = [(t, bo) for t, _r, bo in a]
            body_paras.append([(t, r) for t, r, *_ in fill_read_gaps(merge_runs(b))])
        j = c + 1
        while j < n:
            pj = paras[j]
            if 1 <= pj.level <= 4 or j in tag_para_idx or j in all_set:
                break
            body_paras.append(_to_body_para(pj))
            j += 1
        if not body_paras or sum(len(t) for para in body_paras for t, _ in para) < 40:
            stats["skipped"] += 1
            continue
        if not tag_ps:
            stats["no_tag"] += 1
        cards.append(
            Card(
                tag=re.sub(r"\s+", " ", " ".join(p.text for p in tag_ps)).strip(),
                cite_runs=merge_runs(cite_runs),
                body=body_paras,
                method="formatted" if any(p.level == 4 for p in tag_ps) else "heuristic",
                cite_ok=c in cite_set,
                cite_text=re.sub(r"\s+", " ", "".join(t for t, _ in cite_runs)).strip(),
            )
        )
    return cards, stats


def parse_cite(cite_text):
    """(author, year, url) from a cite string; best effort."""
    m = lead_match(cite_text)
    author = m.group("auth").strip() if m else None
    year = norm_year(m.group("yr")) if m else None
    if year is None:
        ym = re.search(r"\b(19|20)\d{2}\b", cite_text)
        year = int(ym.group(0)) if ym else None
    if author is None:
        am = re.match(rf"^\s*(?:(?:By|From)\s+)?({ONE})", cite_text)
        author = am.group(1) if am else None
    um = re.search(r"https?://[^\s\]>)”\"]+", cite_text)
    return author, year, um.group(0) if um else None
