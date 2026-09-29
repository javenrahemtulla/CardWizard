"""Plain text / markdown: no formatting survives, so only structure is found."""
import re

from .model import Para


def read_text(data):
    if isinstance(data, bytes):
        if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
            data = data.decode("utf-16")
        else:
            try:
                data = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                data = data.decode("cp1252", errors="replace")
    data = data.replace("\r\n", "\n").replace("\r", "\n")
    lines = [l for l in data.split("\n")]
    # if the file uses blank lines between paragraphs, split on those; otherwise one line = one paragraph
    if any(not l.strip() for l in lines) and sum(1 for l in lines if l.strip()) < len(lines) * 0.75:
        blocks = re.split(r"\n\s*\n", data)
        blocks = [" ".join(b.split("\n")) for b in blocks]
    else:
        blocks = lines
    paras = []
    for b in blocks:
        b = b.strip()
        if not b:
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", b)
        if m:
            paras.append(Para([(m.group(2), 0, False)], len(m.group(1))))
        else:
            paras.append(Para([(b, 0, False)], 0))
    return paras
