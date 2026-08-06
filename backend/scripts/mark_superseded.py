"""
mark_superseded.py — Record where a statute has been superseded.

The problem
-----------
Ingesting the Punjab Code added Police Order 2002 (551 chunks, province=punjab)
alongside the Police Act 1861 (549 chunks, province=federal). The Order
supersedes the 1861 Act in Punjab — but the 1861 Act is labelled federal, so the
province filter shows it to Punjab users too. A Punjab policing query can now
retrieve superseded law and have it cited as though current.

Presenting repealed law as current law is worse than retrieving nothing: the
user acts on a rule that no longer governs them.

Why this is not a simple "repealed" flag
----------------------------------------
Supersession in Pakistan is JURISDICTION-SCOPED. The same statute can be
superseded in one province and fully in force in another — provinces have
adopted, repealed and revived policing legislation at different times. A global
repealed flag would wrongly hide law that still governs other provinces.

So the metadata records WHERE a statute stopped applying, not that it stopped
applying everywhere.

VERIFY BEFORE EXTENDING THIS TABLE. Each entry is a legal claim about which law
governs a jurisdiction, and getting it wrong hides law that is actually in force.
The seed entry below covers only the case this codebase demonstrably created.

Usage
-----
  python scripts/mark_superseded.py            # dry run
  python scripts/mark_superseded.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.chroma import connect_chroma, get_chroma  # noqa: E402

COLLECTIONS = ("criminal_collection", "civil_collection",
               "family_collection", "constitutional_collection")

# (statute superseded, provinces where it no longer governs, superseding statute)
SUPERSESSIONS: list[tuple[str, tuple[str, ...], str]] = [
    ("Police Act 1861", ("punjab",), "Police Order 2002"),
]


def main(apply: bool) -> None:
    connect_chroma()
    client = get_chroma()

    total_planned = 0
    for statute, provinces, superseder in SUPERSESSIONS:
        marker = ",".join(sorted(provinces))
        print(f"\n  {statute}")
        print(f"    superseded in : {marker}")
        print(f"    superseded by : {superseder}")

        for cname in COLLECTIONS:
            try:
                col = client.get_collection(cname)
            except Exception:
                continue
            got = col.get(where={"statute": {"$eq": statute}},
                          include=["metadatas"], limit=60000)
            ids = got.get("ids") or []
            metas = got.get("metadatas") or []
            if not ids:
                continue

            todo_ids, todo_metas = [], []
            for cid, meta in zip(ids, metas):
                meta = dict(meta or {})
                if meta.get("superseded_in") == marker:
                    continue
                meta["superseded_in"] = marker
                meta["superseded_by"] = superseder
                todo_ids.append(cid)
                todo_metas.append(meta)

            if not todo_ids:
                print(f"    {cname:<26} {len(ids)} chunks — already marked")
                continue

            print(f"    {cname:<26} {len(todo_ids)} chunks to mark")
            total_planned += len(todo_ids)

            if apply:
                B = 500
                for i in range(0, len(todo_ids), B):
                    col.update(ids=todo_ids[i:i + B], metadatas=todo_metas[i:i + B])
                print(f"    {'':<26} marked.")

    if total_planned == 0:
        print("\n  Nothing to do — everything already marked.\n")
        return
    if not apply:
        print(f"\n  Dry run — {total_planned} chunks would be marked. "
              f"Re-run with --apply.\n")
    else:
        print(f"\n  Done. {total_planned} chunks marked.")
        print("  Retrieval now drops these for the provinces listed.\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    main(p.parse_args().apply)
