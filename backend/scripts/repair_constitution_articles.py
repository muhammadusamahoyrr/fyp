"""
repair_constitution_articles.py — Fix wrong article numbers in the Constitution.

The problem
-----------
ingest_legal_uqa.py derived the article number with a regex that required the
literal word "Article". LEGAL-UQA context text opens with the number itself —
"25A. Equality of citizens ..." — so the match almost always failed, and the
code then fell back to `str(ctx_index)`, the dataset ROW INDEX, storing it as
though it were an article number.

Two kinds of damage, the second worse than the first:

  * Impossible citations. 83 chunks carry a section number above 280, and the
    Constitution of Pakistan has 280 articles. Sequential values 281, 282, 283
    are plainly indices.
  * Plausible but WRONG citations. Row 27 holds the text of Article 25A and was
    labelled article 27. Article 27 exists, so nothing looks amiss — the system
    would cite a real article that says something else entirely. For a legal
    assistant that is a false statement of law delivered with confidence.

What this does
--------------
Re-derives the article number from each chunk's own text and writes it back.
Where it cannot be determined the field is CLEARED rather than guessed: an
empty section number is honest, a wrong one is a fabricated citation.

Metadata only — documents and embeddings are untouched, so no re-download and
no re-embedding. Idempotent. Dry run by default.

Usage
-----
  python scripts/repair_constitution_articles.py
  python scripts/repair_constitution_articles.py --apply
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.chroma import connect_chroma, get_chroma  # noqa: E402

COLLECTION = "constitutional_collection"
STATUTE = "Constitution of Pakistan 1973"
MAX_ARTICLE = 280           # the Constitution of Pakistan runs to 280 articles

_LEADING = re.compile(r"^\s*(\d{1,3}[A-Z]?)\s*[\.\)\:]")
_NAMED = re.compile(r"\bArticle\s+(\d{1,3}[A-Z]?)", re.IGNORECASE)


def derive_article(text: str) -> str:
    """Article number from the chunk's own text, or "" when undeterminable."""
    text = (text or "").strip()
    # QA chunks read "Q: ...\nA: ...". The article is stated in the answer.
    if text.startswith("Q:") and "\nA:" in text:
        text = text.split("\nA:", 1)[1].strip()
    m = _LEADING.match(text) or _NAMED.search(text)
    if not m:
        return ""
    num = m.group(1)
    digits = int(re.sub(r"[A-Z]", "", num) or 0)
    return num if 1 <= digits <= MAX_ARTICLE else ""


def main(apply: bool) -> None:
    connect_chroma()
    col = get_chroma().get_collection(COLLECTION)
    got = col.get(include=["documents", "metadatas"], limit=100000)
    ids = got.get("ids") or []
    docs = got.get("documents") or []
    metas = got.get("metadatas") or []

    print(f"\n  {COLLECTION}: {len(ids)} chunks")

    changed_ids, changed_metas = [], []
    stats = collections.Counter()
    examples = []

    for cid, doc, meta in zip(ids, docs, metas):
        meta = dict(meta or {})
        if str(meta.get("statute", "")) != STATUTE:
            continue
        old = str(meta.get("section_number", "") or "")
        new = derive_article(doc)

        if old == new:
            stats["unchanged"] += 1
            continue

        old_digits = int(re.sub(r"[^0-9]", "", old) or 0)
        if not new:
            stats["cleared"] += 1
        elif old_digits > MAX_ARTICLE:
            stats["fixed_impossible"] += 1
        else:
            stats["fixed_plausible_but_wrong"] += 1
            if len(examples) < 6:
                examples.append((old, new, " ".join((doc or "").split())[:56]))

        meta["section_number"] = new
        changed_ids.append(cid)
        changed_metas.append(meta)

    print(f"    already correct                : {stats['unchanged']}")
    print(f"    impossible number -> corrected  : {stats['fixed_impossible']}")
    print(f"    plausible but WRONG -> corrected: {stats['fixed_plausible_but_wrong']}")
    print(f"    undeterminable -> cleared       : {stats['cleared']}")

    if examples:
        print("\n  the dangerous class — a real article number, wrong text:")
        for old, new, snippet in examples:
            print(f"    was s.{old:<6} now s.{new:<6} | {snippet}")

    if not changed_ids:
        print("\n  Nothing to repair.\n")
        return
    if not apply:
        print(f"\n  Dry run — {len(changed_ids)} chunks would be updated. "
              f"Re-run with --apply.\n")
        return

    B = 500
    for i in range(0, len(changed_ids), B):
        col.update(ids=changed_ids[i:i + B], metadatas=changed_metas[i:i + B])
    print(f"\n  Repaired {len(changed_ids)} chunks.")
    print("  Re-run scripts/build_law_graph.py — article numbers feed the graph.\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    main(p.parse_args().apply)
