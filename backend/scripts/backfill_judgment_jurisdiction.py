"""
backfill_judgment_jurisdiction.py — Add province and authority to judgment chunks.

The problem
-----------
Every chunk in judgments_collection carries title/year/court/judge/judgment_id
and NOTHING about jurisdiction. Meanwhile every statute chunk is province
"federal". The retriever admits province IN (query_province, "federal"), so the
province filter currently excludes nothing anywhere — it is a no-op, and case
law cannot be scoped to the province whose courts actually bind the user.

What this writes
----------------
province  — the province whose courts the judgment governs. Supreme Court
            judgments are marked "federal" deliberately: under the province
            filter, "federal" is admitted for every query, which is the correct
            behaviour for a court that binds the whole country.

authority — binding_national   Supreme Court, binds every court in Pakistan
            binding_provincial High Court, binds courts within its own province
            The distinction is what a precedent-aware ranker needs: another
            province's High Court is persuasive, not binding, and ranking it
            equally with binding authority is legally wrong.

VERIFY the constitutional basis for Supreme Court bindingness (believed to be
Article 189) before relying on this in writing.

Metadata is updated in place; embeddings and documents are untouched.
Idempotent — a second run finds nothing missing.

Usage
-----
  python scripts/backfill_judgment_jurisdiction.py            # dry run
  python scripts/backfill_judgment_jurisdiction.py --apply
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.chroma import connect_chroma, get_chroma  # noqa: E402

COLLECTION = "judgments_collection"

# court token (as found in metadata, case-insensitive) -> (province, authority)
COURT_MAP: dict[str, tuple[str, str]] = {
    "sc":          ("federal",     "binding_national"),
    "supreme":     ("federal",     "binding_national"),
    "lhc":         ("punjab",      "binding_provincial"),
    "lahore":      ("punjab",      "binding_provincial"),
    "shc":         ("sindh",       "binding_provincial"),
    "sindh":       ("sindh",       "binding_provincial"),
    "phc":         ("kpk",         "binding_provincial"),
    "peshawar":    ("kpk",         "binding_provincial"),
    "bhc":         ("balochistan", "binding_provincial"),
    "balochistan": ("balochistan", "binding_provincial"),
    "ihc":         ("federal",     "binding_provincial"),   # ICT
    "islamabad":   ("federal",     "binding_provincial"),
    "fsc":         ("federal",     "binding_national"),     # Federal Shariat Court
}


def resolve(court: str) -> tuple[str, str] | None:
    low = (court or "").strip().lower()
    if not low:
        return None
    for token, val in COURT_MAP.items():
        if token in low:
            return val
    return None


def main(apply: bool) -> None:
    connect_chroma()
    col = get_chroma().get_collection(COLLECTION)
    got = col.get(include=["metadatas"], limit=50000)
    ids = got.get("ids") or []
    metas = got.get("metadatas") or []

    print(f"\n  {COLLECTION}: {len(ids)} chunks")

    courts = collections.Counter(str((m or {}).get("court", "<none>")) for m in metas)
    print(f"  courts present: {dict(courts)}")

    have_prov = sum(1 for m in metas if (m or {}).get("province"))
    have_auth = sum(1 for m in metas if (m or {}).get("authority"))
    print(f"  already have province : {have_prov}")
    print(f"  already have authority: {have_auth}")

    todo_ids, todo_metas = [], []
    unresolved = collections.Counter()
    plan = collections.Counter()

    for cid, meta in zip(ids, metas):
        meta = dict(meta or {})
        if meta.get("province") and meta.get("authority"):
            continue
        hit = resolve(str(meta.get("court", "")))
        if hit is None:
            unresolved[str(meta.get("court", "<none>"))] += 1
            continue
        province, authority = hit
        meta["province"] = province
        meta["authority"] = authority
        todo_ids.append(cid)
        todo_metas.append(meta)
        plan[(province, authority)] += 1

    print(f"\n  would update {len(todo_ids)} chunks:")
    for (prov, auth), n in plan.most_common():
        print(f"    {n:>6}  province={prov:<12} authority={auth}")
    if unresolved:
        print(f"\n  UNRESOLVED courts (left untouched — add them to COURT_MAP):")
        for court, n in unresolved.most_common():
            print(f"    {n:>6}  {court!r}")

    if not todo_ids:
        print("\n  Nothing to do.\n")
        return

    if not apply:
        print("\n  Dry run — nothing written. Re-run with --apply.\n")
        return

    BATCH = 500
    for i in range(0, len(todo_ids), BATCH):
        col.update(ids=todo_ids[i:i + BATCH], metadatas=todo_metas[i:i + BATCH])
        print(f"    updated {min(i + BATCH, len(todo_ids))}/{len(todo_ids)}")

    print(f"\n  Done. {len(todo_ids)} judgment chunks now carry province + authority.\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true", help="write the changes")
    main(p.parse_args().apply)
