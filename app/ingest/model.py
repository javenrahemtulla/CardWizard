"""Intermediate representation shared by every file-type reader.

A reader turns a file into a list of Para. structure.extract_cards turns
Paras into Cards.  Runs are (text, tier, bold).  tier 2 = highlighted (the words actually
spoken aloud), tier 1 = underlined or bold (context around the spoken words,
not read), tier 0 = rest of the article.
"""
from dataclasses import dataclass, field


@dataclass
class Para:
    runs: list  # list of (text, read, bold)
    level: int = 0  # heading level 1-9, 0 = body text

    @property
    def text(self):
        return "".join(r[0] for r in self.runs)


@dataclass
class Card:
    tag: str
    cite_runs: list  # (text, bold)
    body: list  # paragraphs, each a list of (text, read)
    method: str  # "formatted" (tag was Heading 4) or "heuristic"
    cite_ok: bool = True
    cite_text: str = field(default="")


def merge_runs(runs, key=lambda r: r[1:]):
    """Merge adjacent runs that share formatting."""
    out = []
    for r in runs:
        if not r[0]:
            continue
        if out and key(out[-1]) == key(r):
            out[-1] = (out[-1][0] + r[0],) + tuple(out[-1][1:])
        else:
            out.append(tuple(r))
    return out


def fill_read_gaps(runs):
    """Whitespace/punctuation-only unread gap between two read runs becomes read.

    Word often leaves the space between two underlined words unmarked.
    """
    runs = list(runs)
    for i in range(1, len(runs) - 1):
        t, read = runs[i][0], runs[i][1]
        if not read and runs[i - 1][1] and runs[i + 1][1] and not t.strip("  ,;:-"):
            runs[i] = (t, True) + tuple(runs[i][2:])
    return runs


def split_runs(runs, offset):
    """Split a run list at a character offset."""
    a, b, pos = [], [], 0
    for r in runs:
        n = len(r[0])
        if pos + n <= offset:
            a.append(r)
        elif pos >= offset:
            b.append(r)
        else:
            k = offset - pos
            a.append((r[0][:k],) + tuple(r[1:]))
            b.append((r[0][k:],) + tuple(r[1:]))
        pos += n
    return a, b
