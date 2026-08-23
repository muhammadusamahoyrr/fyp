"""retag_legal_uqa.py — stop generated QA pairs claiming to be the Constitution.

The LEGAL-UQA ingestion wrote 619 GPT-4-generated question/answer pairs into
constitutional_collection tagged `statute: "Constitution of Pakistan 1973"`,
alongside 305 genuine article extracts. Three things followed:

  * the system cited model output as the Constitution, and the grounding
    verifier confirmed answers against it;
  * those pairs dominated retrieval (81-100% of returned chunks);
  * the false tag made the ingest pipeline believe the Constitution was already
    present, which is why the primary source had never been ingested.

Retrieval already excludes them (see retrieval_node._is_synthetic). This fixes
the metadata so the exclusion is not the only thing standing between a user and
a fabricated citation, and so the ingest idempotency check tells the truth.

The chunks are retagged, not deleted: they carry a known gold article and are
the basis of an independent retrieval evaluation set. What they must not do is
claim to be statute.

Usage
-----
  python scripts/retag_legal_uqa.py            # report only
  python scripts/retag_legal_uqa.py --apply
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
QA_PREFIX = "legal_uqa_qa_"

# What a generated pair is, said plainly. Anything that reads this metadata —
# a citation, an audit record, a reviewer — now sees the truth without needing
# to know the id convention.
SYNTHETIC_STATUTE = "LEGAL-UQA generated Q&A (not statutory text)"
SYNTHETIC_LAW_TYPE = "synthetic_qa"


def main(apply: bool) -> int:
    connect_chroma()
    col = get_chroma().get_collection(COLLECTION)
    got = col.get(include=["metadatas"])
    ids, metas = got["ids"], got["metadatas"]

    targets = [(i, m) for i, m in zip(ids, metas) if i.startswith(QA_PREFIX)]
    already = [1 for _, m in targets if (m or {}).get("law_type") == SYNTHETIC_LAW_TYPE]

    print(f"\n  {COLLECTION}: {len(ids)} chunks")
    print(f"  generated QA pairs      : {len(targets)}")
    print(f"  already retagged        : {len(already)}")
    print(f"  mislabelled as statute  : {len(targets) - len(already)}")

    if not targets or len(already) == len(targets):
        print("\n  Nothing to do.\n")
        return 0

    if not apply:
        print("\n  Dry run. Re-run with --apply to retag.\n")
        return 0

    new_metas = []
    for _, m in targets:
        m = dict(m or {})
        m["statute"] = SYNTHETIC_STATUTE
        m["law_type"] = SYNTHETIC_LAW_TYPE
        m["synthetic"] = True
        # Keep the article it was generated from: it is the gold label for
        # retrieval evaluation, and losing it would waste the one thing these
        # chunks are still good for.
        new_metas.append(m)

    col.update(ids=[i for i, _ in targets], metadatas=new_metas)
    print(f"\n  retagged {len(targets)} chunk(s) -> statute={SYNTHETIC_STATUTE!r}\n")

    check = col.get(include=["metadatas"])
    still = sum(
        1 for i, m in zip(check["ids"], check["metadatas"])
        if i.startswith(QA_PREFIX)
        and (m or {}).get("statute") == "Constitution of Pakistan 1973"
    )
    print(f"  verification: {still} generated chunk(s) still claim to be the "
          f"Constitution\n")
    return 0 if still == 0 else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Retag generated LEGAL-UQA chunks.")
    p.add_argument("--apply", action="store_true")
    raise SystemExit(main(p.parse_args().apply))
