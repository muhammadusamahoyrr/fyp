"""audit_triage_invariant.py — find turns where triage broke its own contract.

    python scripts/audit_triage_invariant.py            # report only
    python scripts/audit_triage_invariant.py --fix      # also flag the records

The invariant
-------------
triage_node's prompt states: "If language is 'en': return the original query
unchanged." Nothing enforced it until 2026-08-23. A violation is not cosmetic --
`normalized_query` is what retrieval searches AND what the answer cache is keyed
on (`sha256(normalized_query|case_type:province)`), so a corrupted value sends
retrieval after the wrong concept and can poison cache lookups for later,
healthy turns asking the same thing.

See FAILURE_CASE_001.md for the instance that motivated this: an English query
about the punishment for theft was rewritten into corrupted Urdu, retrieval
returned 18 chunks with no PPC 379 among them, and the answer cited the wrong
section at confidence 0.85.

What --fix does
---------------
Sets `invariant_violation: "triage_en_normalization"` on affected records. That
field is excluded by the labelling pool filter, so a flagged turn never reaches
an annotator: grading it would measure the bug, not the system. It does NOT
rewrite `normalized_query` -- the record is an audit trail of what actually
happened, and editing history to look correct is the opposite of its purpose.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.db.mongodb import connect_db, get_database  # noqa: E402

VIOLATION = "triage_en_normalization"
_URDU = re.compile(r"[؀-ۿ]")


def violates(rec: dict) -> bool:
    """`en` turns must carry normalized_query == query.

    Compared stripped: trailing whitespace is not corruption. An empty
    normalized_query is not a violation either -- triage falls back to the raw
    query, which is the correct value.
    """
    if (rec.get("language") or "") != "en":
        return False
    q = (rec.get("query") or "").strip()
    n = (rec.get("normalized_query") or "").strip()
    return bool(n) and n != q


async def main(fix: bool) -> None:
    await connect_db()
    col = get_database()["answer_provenance"]

    total = by_lang = 0
    hits: list[dict] = []
    async for rec in col.find({}, {"_id": 0}):
        total += 1
        if (rec.get("language") or "") == "en":
            by_lang += 1
        if violates(rec):
            hits.append(rec)

    print("=" * 74)
    print("  TRIAGE INVARIANT AUDIT — language=='en' => normalized_query == query")
    print("=" * 74)
    print(f"  provenance records        : {total}")
    print(f"  en-language turns         : {by_lang}")
    print(f"  VIOLATIONS                : {len(hits)}")

    if not hits:
        print("\n  No turn broke the invariant. Nothing to flag.\n")
        return

    already = sum(1 for r in hits if r.get("invariant_violation"))
    print(f"  already flagged           : {already}")
    print(f"  in the labelling pool     : "
          f"{sum(1 for r in hits if not r.get('is_synthetic'))} "
          f"(synthetic turns were already excluded)")
    print()

    for r in hits:
        print(f"  [{(r.get('request_id') or '')[:8]}] "
              f"synthetic={bool(r.get('is_synthetic'))} "
              f"urdu_script={bool(_URDU.search(r.get('normalized_query') or ''))}")
        print(f"     query      : {(r.get('query') or '')[:70]}")
        print(f"     normalized : {(r.get('normalized_query') or '')[:70]}")

    if not fix:
        print(f"\n  Report only. Re-run with --fix to flag {len(hits)} record(s).\n")
        return

    flagged = 0
    for r in hits:
        if r.get("invariant_violation"):
            continue
        res = await col.update_one(
            {"request_id": r["request_id"]},
            {"$set": {"invariant_violation": VIOLATION}},
        )
        flagged += res.modified_count

    print(f"\n  flagged {flagged} record(s) as {VIOLATION!r}.")
    print("  They are now excluded from the labelling pool. normalized_query is "
          "left as recorded —\n  the record is an audit trail, not a place to "
          "tidy away what happened.\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Audit the triage 'en' invariant.")
    p.add_argument("--fix", action="store_true",
                   help="flag affected records so annotators never see them")
    asyncio.run(main(p.parse_args().fix))
