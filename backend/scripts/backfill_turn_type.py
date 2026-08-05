"""
backfill_turn_type.py — Stamp turn_type onto provenance rows that predate it.

Context
-------
`turn_type` (answer / clarification / blocked) was added to answer_provenance
after some records had already been written. Rows without it are treated as
answer turns for back-compat, which is right for genuine answers but wrong for
the gatekeeper-blocked ones: those would be offered to the labeler as if a
canned refusal were an answer to judge.

Scope — deliberately narrow
---------------------------
Only rows that BOTH lack turn_type AND were blocked by the gatekeeper
(arbitration.source == "gatekeeper:heuristic"). Genuine answer rows are left
alone: the missing-field fallback already classifies them correctly, and the
less this touches an audit collection the better.

This adds a missing schema field. It does not alter any recorded judgement —
no query, answer digest, evidence, verdict or signal is modified.

Idempotent: the filter requires the field to be absent, so a second run matches
nothing.

Usage
-----
  python scripts/backfill_turn_type.py            # dry run, shows what would change
  python scripts/backfill_turn_type.py --apply    # perform the update
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.collections import get_answer_provenance_col      # noqa: E402
from app.db.mongodb import close_db, connect_db               # noqa: E402
from app.services.provenance_service import TURN_BLOCKED      # noqa: E402

# Rows that predate the field AND were stopped by the gatekeeper.
_FILTER = {
    "turn_type": {"$exists": False},
    "arbitration.source": "gatekeeper:heuristic",
}


async def main(apply: bool) -> None:
    await connect_db()
    try:
        col = get_answer_provenance_col()
        candidates = await col.find(
            _FILTER, {"_id": 0, "request_id": 1, "query": 1}
        ).to_list(length=None)

        if not candidates:
            print("\n  Nothing to backfill — every blocked row already has turn_type.\n")
            return

        print(f"\n  {len(candidates)} row(s) would be stamped turn_type={TURN_BLOCKED!r}:")
        for d in candidates:
            print(f"    {d['request_id'][:8]}  {d.get('query', '')[:64]}")

        if not apply:
            print("\n  Dry run — nothing written. Re-run with --apply to perform it.\n")
            return

        result = await col.update_many(_FILTER, {"$set": {"turn_type": TURN_BLOCKED}})
        print(f"\n  updated {result.modified_count} row(s)")

        remaining = await col.count_documents(_FILTER)
        print(f"  remaining unstamped blocked rows: {remaining}\n")
    finally:
        await close_db()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="perform the update (default is a dry run)")
    asyncio.run(main(parser.parse_args().apply))
