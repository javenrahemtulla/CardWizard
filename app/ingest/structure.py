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
}
CRED = re.compile(
    r"professor|director|fellow|editor|senior|researcher|associate|ph\.?d|university|institute|"
    r"analyst|journalist|author|chair|dean|scholar|lecturer|correspondent|writer|reporter|"
    r"economist|historian|philosopher|policy|center|centre|department|college|school|"
    r"foundation|council|staff|candidate|consultant|adviser|advisor|expert|founder|activist|columnist|"
    r"commentator|contributor|president|ceo|attorney|lawyer|physician|translated|interviewed",
    re.I,
)
MONTH = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b|\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b",
    re.I,
)
URL = re.compile(r"https?://|www\.|doi\.org|\.(com|org|edu|gov|net)\b", re.I)


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
    return m


def _features(text, prev_level, next_len):
    s = 0
    head = text[:250]
    if "[" in head:
        s += 2
    if URL.search(text[:1200]):
        s += 1
    if CRED.search(text[:600]):
        s += 1
    if MONTH.search(text[:600]):
        s += 1
    if re.search(r"[“\"][^”\"]{6,}[”\"]", text[:800]):
        s += 1
    if re.search(r"accessed|retrieved|\bdoa\b|\bpp?\.\s*\d", text[:800], re.I):
        s += 1
    if prev_level == 4:
        s += 2
    if next_len > 300:
        s += 1
    return s


def cite_score(text, prev_level, next_len):
    """Confidence (roughly 0-9) that a paragraph is a cite line."""
    m = lead_match(text)
    if m:
        s = _features(text, prev_level, next_len)
        if len(text) > 2500 and "[" not in text[:250]:
            s -= 3
        if len(text) < 25:
            s -= 2
        return s
    # No "Author YY" lead (e.g. "Franco Berardi Bifo, translated by X, 2007, ..."):
    # accept only with a year near the front, a long paragraph after, and several other cues.
    first = re.split(r"\W+", text.strip())[0].lower() if text.strip() else ""
    if (
        text[:1].isupper() and first not in NOT_AUTHORS and 40 < len(text) < 900 and next_len > 300
        and re.search(r"\b(19|20)\d{2}\b", text[:250])
    ):
        return _features(text, prev_level, next_len) if _features(text, 0, next_len) >= 4 else 0
    return 0


def _split_cite_and_body(runs):
    """Cite and first body paragraph sometimes share one paragraph.  Split at
    the closing bracket of the credentials block."""
    text = "".join(r[0] for r in runs)
    lb = text.find("[")
    if lb == -1 or lb > 250:
        return runs, None
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
                if len(text) - cut > 400:
                    a, b = split_runs(runs, cut)
                    return a, b
                break
    return runs, None


def _to_body_para(p):
    return [(t, r) for t, r, *_ in fill_read_gaps(merge_runs(p.runs))]


def extract_cards(paras, min_cite_score=3):
    paras = [p for p in paras if p.text.strip()]
    n = len(paras)
    lens = [len(p.text) for p in paras]

    cite_idx = []
    for i, p in enumerate(paras):
        if i == 0:
            continue
        prev = paras[i - 1]
        # a cite cannot directly follow another cite, and a level 1-3 heading is not a tag
        nxt = lens[i + 1] if i + 1 < n else 0
        if cite_score(p.text, prev.level, nxt) >= min_cite_score and p.level not in (1, 2, 3, 4):
            cite_idx.append(i)
    cite_set = set(cite_idx)

    # fallback: Heading 4 + short line + long body, when the cite is in a format
    # we do not recognise
    fallback = set()
    for i, p in enumerate(paras[:-2]):
        if p.level == 4 and (i + 1) not in cite_set and paras[i + 1].level == 0 and (i + 2) not in cite_set:
            if lens[i + 1] < 700 and lens[i + 2] > 500 and paras[i + 2].level == 0:
                fallback.add(i + 1)
    all_cites = sorted(cite_set | fallback)
    all_set = set(all_cites)

    cards, stats = [], {"cites": len(cite_set), "fallback_cites": len(fallback), "skipped": 0}
    for c in all_cites:
        tag_p = paras[c - 1]
        if len(tag_p.text) > 1200 or c - 1 in all_set:
            stats["skipped"] += 1
            continue
        cite_runs = [(t, b) for t, _r, b in paras[c].runs]
        body_paras = []
        cite_p_runs = paras[c].runs
        if len(paras[c].text) > 1200:
            a, b = _split_cite_and_body(cite_p_runs)
            if b:
                cite_runs = [(t, bo) for t, _r, bo in a]
                body_paras.append([(t, r) for t, r, *_ in fill_read_gaps(merge_runs(b))])
        j = c + 1
        while j < n:
            pj = paras[j]
            if 1 <= pj.level <= 4:
                break
            if j + 1 in all_set or j in all_set:
                break
            body_paras.append(_to_body_para(pj))
            j += 1
        if not body_paras or sum(len(t) for para in body_paras for t, _ in para) < 40:
            stats["skipped"] += 1
            continue
        cards.append(
            Card(
                tag=re.sub(r"\s+", " ", tag_p.text).strip(),
                cite_runs=merge_runs(cite_runs),
                body=body_paras,
                method="formatted" if tag_p.level == 4 else "heuristic",
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
    um = re.search(r"https?://[^\s\]>)”\"]+", cite_text)
    return author, year, um.group(0) if um else None
