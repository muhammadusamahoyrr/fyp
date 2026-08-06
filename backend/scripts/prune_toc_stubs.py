"""
prune_toc_stubs.py — Remove contents-page stubs from the statute collections.

The problem
-----------
Every statute PDF opens with a CONTENTS page whose lines read like
"12. Power to arrest without warrant .... 7". Section-aware chunking treats each
of those as the start of a section and emits a ~50-character chunk. The real
section 12 is indexed separately, so the stub is a duplicate that carries no law.

Measured: 1,350 such stubs, about 12% of the statute corpus.

Why they are worse than merely useless
--------------------------------------
A stub is almost entirely heading words, so for a query about that heading its
keyword overlap is as high as the real provision's — and it is short enough to
sit close to a short query in embedding space. It therefore competes with, and
can outrank, the provision it names, while containing none of the rule.

    QSO section 1:
      [ 54 chars]  "1. Short title, extent and commencement 1"        <- stub
      [428 chars]  "1. Short title, extent and commencement: (1) ..."  <- the law

What is removed
---------------
Only a chunk under MIN_CHARS that is a PREFIX of a longer chunk for the same
(statute, section), once the trailing page reference is stripped. A short chunk
with no longer sibling it prefixes is always kept — plenty of provisions
genuinely are one line, and dropping them would lose law.

Idempotent. Dry run by default.

Usage
-----
  python scripts/prune_toc_stubs.py
  python scripts/prune_toc_stubs.py --apply
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

COLLECTIONS = ("criminal_collection", "civil_collection",
               "family_collection", "constitutional_collection")

MIN_CHARS = 120          # below this a "section" is a heading, not a provision

# A stub is recognised by being a PREFIX of the provision it names, not by any
# length threshold. Strip the trailing page reference and:
#     "16. Accomplice 7"                                    <- stub
#     "16. Accomplice; An accomplice shall be a competent"  <- the provision
# An earlier length rule ("sibling must exceed 400 chars") misjudged this exact
# section, because the real provision is only 254 characters long. Kept in sync
# with _drop_toc_stubs() in ingest_statutes.py.
# Compare on the opening only, alphanumeric-only. Statute PDFs are OCR'd and the
# same heading differs between contents and body ("communicat ions" vs
# "communications", "facts-in-issue" vs "f acts in issue"); contents lines also
# carry trailing junk (page numbers, the next chapter heading). Matching the
# normalised HEAD is robust to both where exact matching is not.
_STUB_HEAD_CHARS = 25
_ALNUM = re.compile(r"[^a-z0-9]+")
# Trailing page reference must be stripped BEFORE alphanumeric folding, or it
# lands inside the head and blocks the match: "16. Accomplice 7" folds to
# "16accomplice7", which never prefixes "16accompliceanaccomplice...".
_TRAILING_PAGENO = re.compile(r"[\.\s]*\d{1,3}\s*$")


def _normalise(text: str) -> str:
    return _ALNUM.sub("", _TRAILING_PAGENO.sub("", (text or "")).lower())


def main(apply: bool) -> None:
    connect_chroma()
    client = get_chroma()

    grand_drop = 0
    grand_keep = 0

    for name in COLLECTIONS:
        try:
            col = client.get_collection(name)
        except Exception:
            continue
        got = col.get(include=["documents", "metadatas"], limit=100000)
        ids = got.get("ids") or []
        docs = got.get("documents") or []
        metas = got.get("metadatas") or []

        # group chunks by (statute, section) so a stub can be compared with the
        # provision it names
        groups: dict[tuple[str, str], list[tuple[str, str]]] = collections.defaultdict(list)
        for cid, d, m in zip(ids, docs, metas):
            m = m or {}
            key = (str(m.get("statute", "")), str(m.get("section_number", "")))
            groups[key].append((cid, d or ""))

        drop_ids, kept_short = [], 0
        by_statute = collections.Counter()
        for (statute, _sec), members in groups.items():
            for cid, text in members:
                if len(text) >= MIN_CHARS:
                    continue
                head = _normalise(text)[:_STUB_HEAD_CHARS]
                is_stub = len(head) >= 12 and any(
                    len(other) > len(text) and _normalise(other).startswith(head)
                    for ocid, other in members if ocid != cid
                )
                if is_stub:
                    drop_ids.append(cid)
                    by_statute[statute] += 1
                else:
                    kept_short += 1

        grand_drop += len(drop_ids)
        grand_keep += kept_short
        print(f"\n  {name}: {len(ids)} chunks")
        print(f"    stubs to remove          : {len(drop_ids)}")
        print(f"    short-but-only-copy kept : {kept_short}")
        for statute, n in by_statute.most_common(5):
            print(f"        {n:>5}  {statute}")

        if apply and drop_ids:
            B = 500
            for i in range(0, len(drop_ids), B):
                col.delete(ids=drop_ids[i:i + B])
            print(f"    removed. collection now {col.count()} chunks")

    print(f"\n  total stubs {'removed' if apply else 'to remove'}: {grand_drop}")
    print(f"  total short-but-only-copy kept: {grand_keep}")
    if not apply:
        print("\n  Dry run — nothing written. Re-run with --apply.\n")
    else:
        print("\n  Re-run scripts/build_law_graph.py: chunk ids changed.\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    main(p.parse_args().apply)
