#!/usr/bin/env python3
"""Build the static Card Wizard site data from a folder of debate files.

    python tools/build_site.py sync incoming        # make docs/data mirror the folder

The folder is the library: new files are parsed and added, files that were deleted
have their cards removed (a card stays if another file still contains it).
Idempotent, so it is safe to run on every push.

Outputs, all under docs/data/:
    index.json        searchable fields of every card (tag, cite, spoken and context text)
    c/<id>.json       full body of one card, fetched when a card is opened
    files.json        which files are in the library
    embeddings.bin    int8 vectors for meaning search, rows in the order of embeddings.ids.json
"""
import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db  # noqa: E402  (only its pure helpers are used, no database is opened)
from app.ingest import parse_file  # noqa: E402
from app.ingest.structure import parse_cite  # noqa: E402

SKIP = {"README.md", ".gitkeep", ".DS_Store"}
CONTEXT_LIMIT = 3000  # chars of underlined/bold context kept in the search index
DIM = 384


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def list_files(folder):
    out = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for n in sorted(names):
            if n in SKIP or n.startswith("."):
                continue
            out.append(os.path.join(root, n))
    return sorted(out)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def get_embedder(disabled):
    if disabled:
        return None
    from app import embed

    try:
        return embed.HashEmbedder() if os.environ.get("CARDWIZARD_EMBEDDER") == "hash" else embed.FastEmbedder()
    except Exception as e:  # model could not be downloaded
        print(f"warning: meaning search disabled, embedding model unavailable ({str(e)[:120]})")
        return None


def sync(folder, out, no_embeddings=False):
    import numpy as np

    from app import embed

    data_dir = os.path.join(out, "data")
    index = load_json(os.path.join(data_dir, "index.json"), {"version": 1, "next_id": 1, "cards": []})
    files = load_json(os.path.join(data_dir, "files.json"), {})
    cards = {c["id"]: c for c in index["cards"]}
    by_key = {c["key"]: c for c in cards.values()}

    present = {}
    for path in list_files(folder):
        present[sha256_of(path)] = os.path.relpath(path, folder).replace(os.sep, "/")

    # remove files that are gone
    removed = [sha for sha in files if sha not in present]
    for sha in removed:
        for c in list(cards.values()):
            if sha in c["src"]:
                c["src"].remove(sha)
                if not c["src"]:
                    del cards[c["id"]]
                    by_key.pop(c["key"], None)
                    try:
                        os.remove(os.path.join(data_dir, "c", f"{c['id']}.json"))
                    except OSError:
                        pass
        del files[sha]

    # add new files
    added = 0
    for sha, name in present.items():
        if sha in files:
            files[sha]["name"] = name  # a rename keeps the same content
            continue
        try:
            with open(os.path.join(folder, name), "rb") as f:
                result = parse_file(name, f.read())
        except Exception as e:
            print(f"skipped {name}: {e}")
            files[sha] = {"name": name, "n_cards": 0, "error": str(e)[:200]}
            continue
        new = 0
        for card in result.cards:
            key = db.card_key(card)
            spoken, context, full = db.card_texts(card)
            if key in by_key:
                if sha not in by_key[key]["src"]:
                    by_key[key]["src"].append(sha)
                continue
            author, year, url = parse_cite(card.cite_text)
            cid = index["next_id"]
            index["next_id"] += 1
            rec = {
                "id": cid, "key": key, "tag": card.tag, "cite": card.cite_text, "author": author, "year": year,
                "spoken": spoken, "context": context[:CONTEXT_LIMIT], "method": card.method,
                "cite_ok": card.cite_ok, "src": [sha],
            }
            cards[cid] = rec
            by_key[key] = rec
            save_json(os.path.join(data_dir, "c", f"{cid}.json"),
                      {"cite_runs": card.cite_runs, "body": card.body, "url": url})
            new += 1
        files[sha] = {"name": name, "n_cards": len(result.cards)}
        added += 1
        print(f"{name}: {len(result.cards)} cards found, {new} new")
        for w in result.warnings:
            print(f"  note: {w}")

    index["cards"] = sorted(cards.values(), key=lambda c: c["id"])
    save_json(os.path.join(data_dir, "index.json"), index)
    save_json(os.path.join(data_dir, "files.json"), files)

    # embeddings for meaning search
    ids_path = os.path.join(data_dir, "embeddings.ids.json")
    bin_path = os.path.join(data_dir, "embeddings.bin")
    vecs = {}
    old_ids = load_json(ids_path, [])
    if old_ids and os.path.exists(bin_path):
        raw = np.fromfile(bin_path, dtype=np.int8)
        if raw.size == len(old_ids) * DIM:
            raw = raw.reshape(len(old_ids), DIM)
            vecs = {i: raw[k] for k, i in enumerate(old_ids)}
    missing = [c for c in index["cards"] if c["id"] not in vecs]
    embedder = get_embedder(no_embeddings) if missing else None
    if missing and embedder is not None:
        for start in range(0, len(missing), 64):
            batch = missing[start:start + 64]
            texts = [embed.doc_text(c["tag"], c["spoken"], c["context"], "") for c in batch]
            arr = embedder.embed_docs(texts)
            for c, v in zip(batch, arr):
                v = v / (np.linalg.norm(v) or 1.0)
                vecs[c["id"]] = np.clip(np.round(v * 127), -127, 127).astype(np.int8)
    have = [c["id"] for c in index["cards"] if c["id"] in vecs]
    if have:
        np.stack([vecs[i] for i in have]).astype(np.int8).tofile(bin_path)
        save_json(ids_path, have)
    else:
        for p in (bin_path, ids_path):
            if os.path.exists(p):
                os.remove(p)
    print(f"library: {len(files)} files, {len(index['cards'])} cards ({added} files added, {len(removed)} removed), "
          f"{len(have)} with meaning-search vectors")
    return {"files": len(files), "cards": len(index["cards"]), "added": added, "removed": len(removed), "vectors": len(have)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="make the site data mirror a folder of files")
    s.add_argument("folder", nargs="?", default="incoming")
    s.add_argument("--out", default="docs", help="site folder (default: docs)")
    s.add_argument("--no-embeddings", action="store_true", help="skip meaning-search vectors")
    args = ap.parse_args()
    if args.cmd == "sync":
        os.makedirs(args.folder, exist_ok=True)
        sync(args.folder, args.out, args.no_embeddings)


if __name__ == "__main__":
    main()
