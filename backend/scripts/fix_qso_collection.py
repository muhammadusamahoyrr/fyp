"""
fix_qso_collection.py — Move Qanun-e-Shahadat out of family_collection.

The problem
-----------
family_collection holds 226 chunks, of which 211 are the Qanun-e-Shahadat Order
1984 — the law of EVIDENCE, not family law — leaving only 15 chunks of actual
family law (MFLO 1961). Evidence law therefore dominates every family retrieval:
a query about the grounds for khula returns mostly rules about admissibility of
documents, which is why that query scored 0.31 relevance and came back
ungrounded.

Why evidence law does not belong in the family collection
---------------------------------------------------------
Beyond the dilution, there is a substantive reason: under the West Pakistan
Family Courts Act 1964, family courts are not bound by the strict rules of
evidence in the Qanun-e-Shahadat. VERIFY the exact section before relying on
this in writing — the point stands practically either way, since 211 chunks of
evidence law drowning out 15 chunks of family law helps no one.

Where it goes instead
---------------------
Evidence law is cross-cutting and is squarely used in criminal and civil
proceedings, so QSO is copied into BOTH of those collections. It currently
exists nowhere else, so a plain delete would remove evidence law from the corpus
entirely.

Embeddings are copied as-is rather than recomputed: the vectors are already
correct for this text, and re-embedding 211 chunks on CPU is slow and would
introduce needless drift.

Idempotent — re-running after a successful pass finds nothing to do.

Usage
-----
  python scripts/fix_qso_collection.py            # dry run
  python scripts/fix_qso_collection.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.chroma import connect_chroma, get_chroma  # noqa: E402

SOURCE_COLLECTION = "family_collection"
TARGETS = ("criminal_collection", "civil_collection")
STATUTE_MATCH = "shahadat"          # matched case-insensitively against `statute`
NEW_LAW_TYPE = "evidence"           # more accurate than the current 'criminal'


def _qso_rows(col):
    """Every QSO chunk in a collection, with embeddings so we can copy losslessly."""
    got = col.get(include=["documents", "metadatas", "embeddings"], limit=20000)
    ids = got.get("ids") or []
    docs = got.get("documents") or []
    metas = got.get("metadatas") or []
    embs = got.get("embeddings")
    embs = list(embs) if embs is not None else [None] * len(ids)

    rows = []
    for i, d, m, e in zip(ids, docs, metas, embs):
        if STATUTE_MATCH in str((m or {}).get("statute", "")).lower():
            rows.append((i, d, m, e))
    return rows


def main(apply: bool) -> None:
    connect_chroma()
    client = get_chroma()

    src = client.get_collection(SOURCE_COLLECTION)
    rows = _qso_rows(src)

    print(f"\n  {SOURCE_COLLECTION}: {src.count()} chunks total")
    print(f"  Qanun-e-Shahadat chunks found: {len(rows)}")

    if not rows:
        print("\n  Nothing to move — QSO is not in family_collection.\n")
        return

    remaining = src.count() - len(rows)
    print(f"  family_collection would be left with: {remaining} chunks "
          f"(actual family law)")

    have_embeddings = all(e is not None for _, _, _, e in rows)
    print(f"  embeddings available for copy: {have_embeddings}")

    for target in TARGETS:
        tcol = client.get_or_create_collection(
            name=target, metadata={"hnsw:space": "cosine"}
        )
        already = len(_qso_rows(tcol))
        print(f"  {target}: {tcol.count()} chunks, {already} QSO already present")

    if not apply:
        print("\n  Dry run — nothing written. Re-run with --apply.\n")
        return

    # ── copy into each target ────────────────────────────────────────────────
    for target in TARGETS:
        tcol = client.get_or_create_collection(
            name=target, metadata={"hnsw:space": "cosine"}
        )
        ids = [r[0] for r in rows]
        docs = [r[1] for r in rows]
        metas = [{**(r[2] or {}), "law_type": NEW_LAW_TYPE} for r in rows]
        embs = [r[3] for r in rows] if have_embeddings else None

        # upsert is idempotent on id, so a partial previous run self-heals
        if embs is not None:
            tcol.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=embs)
        else:
            tcol.upsert(ids=ids, documents=docs, metadatas=metas)
        print(f"  -> upserted {len(ids)} QSO chunks into {target} "
              f"(now {tcol.count()})")

    # ── remove from family only AFTER the copies succeeded ───────────────────
    src.delete(ids=[r[0] for r in rows])
    print(f"  -> removed {len(rows)} QSO chunks from {SOURCE_COLLECTION} "
          f"(now {src.count()})")

    print("\n  Done. family_collection now contains only family law.")
    print("  NOTE: it is now very small — sourcing the Dissolution of Muslim")
    print("  Marriages Act 1939, Family Courts Act 1964 and Guardians and Wards")
    print("  Act 1890 is the next priority.\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true",
                   help="perform the move (default is a dry run)")
    main(p.parse_args().apply)
