"""repair_constitution_schedules.py — stop Schedules being cited as Articles.

The defect
----------
The Constitution of Pakistan has 280 Articles, then several Schedules and an
Annex. The Schedules carry their OWN paragraph numbering that restarts at 1, so
the section splitter — which keys on a leading "N." — recorded schedule
paragraphs as Articles. Measured on the indexed corpus:

    Article  9  claimed by 6 chunks: 2 real, 4 schedule paragraphs
    Article 42  claimed by 3 chunks: 2 real, 1 schedule paragraph

Article 9 is "Security of person", a fundamental right. A user asking about it
could be served Second Schedule text about a candidate dying after nomination,
cited as Article 9. That is a fabricated citation of constitutional law, emitted
with the system's normal confidence.

Why repair_constitution_articles.py cannot catch it
---------------------------------------------------
That script re-derives the article number from the chunk's own text. A schedule
paragraph genuinely begins "9." — so re-deriving confirms the wrong answer. The
error is positional, not textual: it can only be found by knowing that the
Articles end and the Schedules begin.

What this does
--------------
Finds the last chunk carrying Article 280 (the final Article) and clears
section_number for every chunk after it, marking them `part: "schedule"`. The
text is KEPT and stays retrievable — Schedules are law, the Third Schedule holds
the oaths of office — it simply stops claiming to be a numbered Article.

Metadata only. Documents and embeddings are untouched. Idempotent. Dry run by
default.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.db.chroma import connect_chroma, get_chroma  # noqa: E402

COLLECTION = "constitutional_collection"
PREFIX = "statutes_constitution_of_pakistan_1973_"
LAST_ARTICLE = "280"


def main(apply: bool) -> int:
    connect_chroma()
    col = get_chroma().get_collection(COLLECTION)
    got = col.get(include=["documents", "metadatas"])

    items = sorted(
        ((cid, doc, meta or {}) for cid, doc, meta in
         zip(got["ids"], got["documents"], got["metadatas"])
         if cid.startswith(PREFIX)),
        key=lambda x: x[0],
    )
    print(f"\n  {COLLECTION}: {len(items)} Constitution chunks")

    last_idx = max((i for i, (_, _, m) in enumerate(items)
                    if str(m.get("section_number") or "") == LAST_ARTICLE),
                   default=None)
    if last_idx is None:
        raise SystemExit(f"no chunk carries Article {LAST_ARTICLE} — cannot "
                         "locate the Articles/Schedules boundary")
    print(f"  last Article {LAST_ARTICLE} chunk: index {last_idx} "
          f"({items[last_idx][0].rsplit('_', 1)[1]})")

    tail = items[last_idx + 1:]
    targets = [(cid, m) for cid, _, m in tail
               if str(m.get("section_number") or "").strip()
               or m.get("part") != "schedule"]
    numbered = [cid for cid, _, m in tail if str(m.get("section_number") or "").strip()]

    print(f"  chunks after the last Article : {len(tail)}")
    print(f"  of those, falsely numbered    : {len(numbered)}")

    if not targets:
        print("\n  Nothing to do.\n")
        return 0

    # Which Articles were being impersonated, and how badly.
    import collections
    stolen = collections.Counter(
        str(m.get("section_number")) for _, _, m in tail
        if str(m.get("section_number") or "").strip()
    )
    print("\n  most-impersonated Article numbers:")
    for art, n in stolen.most_common(8):
        print(f"    Article {art:<5} claimed by {n} schedule chunk(s)")

    if not apply:
        print(f"\n  Dry run — {len(targets)} chunk(s) would be corrected. "
              "Re-run with --apply.\n")
        return 0

    ids, metas = [], []
    for cid, m in targets:
        m = dict(m)
        m["section_number"] = ""
        m["part"] = "schedule"
        ids.append(cid)
        metas.append(m)
    col.update(ids=ids, metadatas=metas)
    print(f"\n  corrected {len(ids)} chunk(s): section_number cleared, "
          "part='schedule'")

    check = col.get(include=["metadatas"])
    for art in ("9", "42"):
        n = sum(1 for cid, m in zip(check["ids"], check["metadatas"])
                if cid.startswith(PREFIX)
                and str((m or {}).get("section_number", "")) == art)
        print(f"    Article {art} now claimed by {n} chunk(s)")
    print()
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Stop Constitution Schedules being cited as Articles.")
    p.add_argument("--apply", action="store_true")
    raise SystemExit(main(p.parse_args().apply))
