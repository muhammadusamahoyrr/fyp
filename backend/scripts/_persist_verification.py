"""Persist citation-verification results onto the 19 migrated V2 revisions.

The stored records read `ran: false` because ChromaDB was not connected during
apply(). The check has since been run for real, and the parser defects it
exposed are fixed. This writes the result back.

SCOPE. Exactly one field, `verification`, on exactly the 19 revisions that
carry the migration id. Nothing else is written: not the documents, not
artifacts, not indexes, not the feature flag.

SAFETY.
  * The prior value of every record is dumped to disk BEFORE the first write,
    so this is reversible.
  * Each update is a compare-and-set on (_id, migration_id) — a revision that
    changed underneath us is skipped and reported, never overwritten.
  * The controls that gate the read-only harness gate this too: if the checker
    cannot flag a section it should flag, nothing is written at all. A verdict
    computed by a broken checker is worse than no verdict, because it would be
    stored and believed.
  * A record is written only if it differs from what is already there.

HONESTY. `ran: false` is still written where the check genuinely could not run
(the Urdu revision). This does not launder "unavailable" into "clean" — see
_unavailable_verification. The `checked_at` stamp is TODAY, not the document's
generation date: this is a migration-time check of a legacy PDF, and the record
says so by its timestamp.
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

MIGRATION_ID = "mig-349ef601-6b65-447a-ba58-42dd8d1c6823"


async def main() -> int:
    from app.core.config import settings

    print(f"DOCUMENTS_V2 : {settings.documents_v2}  (must stay False)")
    if settings.documents_v2:
        raise SystemExit("ABORT: the flag is on; this is not the moment")

    from app.db.mongodb import connect_db, get_database
    await connect_db()
    db = get_database()
    print(f"database     : {settings.db_name}")
    if settings.db_name.endswith("_test"):
        raise SystemExit("ABORT: pointed at a test database")

    from app.db.chroma import connect_chroma
    connect_chroma()
    from app.ai.citation_verification import verify_statutes
    from app.ai.corpus_index import get_index

    index = get_index()
    print(f"corpus       : {len(index)} statutes, {index.total_sections()} sections")
    if not len(index):
        raise SystemExit("ABORT: empty corpus; refusing to store a vacuous pass")

    # Same controls as the read-only harness. Nothing is written unless the
    # checker demonstrably works in both directions.
    negative = positive = None
    for statute in [s for s in index.statutes if index.coverage(s).dense]:
        cov = index.coverage(statute)
        for gap in (n for n in range(1, cov.highest or 1) if n not in cov.numbered):
            if any(c.is_flag for c in verify_statutes(
                    f"under section {gap} of the {statute}", None, index)):
                negative = (statute, gap)
                break
        if negative:
            real = sorted(cov.numbered)[len(cov.numbered) // 2]
            checks = verify_statutes(f"under section {real} of the {statute}",
                                     None, index)
            if checks and all(c.status == "VERIFIED" for c in checks):
                positive = (statute, real)
            break
    print(f"control -    : absent section flagged  {bool(negative)}  {negative}")
    print(f"control +    : held section verified   {bool(positive)}  {positive}")
    if not (negative and positive):
        raise SystemExit("ABORT: checker failed its controls; writing nothing")

    revisions = sorted(
        await db["document_revisions"].find({"migration_id": MIGRATION_ID})
        .to_list(length=None), key=lambda r: r["document_id"])
    print(f"\nrevisions carrying the migration id: {len(revisions)}")
    if len(revisions) != 19:
        raise SystemExit(f"ABORT: expected 19, found {len(revisions)}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = Path.home() / f"v2-verification-before-{stamp}.json"
    backup.write_text(json.dumps(
        {r["_id"]: {"document_id": r["document_id"],
                    "verification": r.get("verification")} for r in revisions},
        indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(f"prior values dumped to {backup.name} BEFORE any write\n")

    from app.services.document_service import (_unavailable_verification,
                                               _verification_record)
    from app.services.document_v2_service import _build_verification_inputs

    written = skipped = unchanged = 0
    summary = {"clean": 0, "partial": 0, "failed": 0, "no_citations": 0,
               "unavailable": 0}
    for revision in revisions:
        doc_id, template = revision["document_id"], revision.get("template_type")
        body = revision.get("body_text")
        _s, _p, text, unavailable = _build_verification_inputs(
            template, body, revision.get("extraction_status") or "ok")
        if unavailable:
            record = _unavailable_verification(unavailable)
        elif not (text or "").strip():
            record = _unavailable_verification("extracted_text_empty")
        else:
            record = await _verification_record({"document": text})

        counts = record.get("counts") or {}
        checks = record.get("checks") or []
        flags = [c for c in checks if c.get("status") in ("NOT_IN_CORPUS", "OMITTED")]
        if not record.get("ran"):
            bucket = "unavailable"
        elif flags:
            bucket = "failed"
        elif counts.get("total", 0) == 0:
            bucket = "no_citations"
        elif any(c.get("status") == "UNVERIFIABLE" for c in checks):
            bucket = "partial"
        else:
            bucket = "clean"
        summary[bucket] += 1

        result = await db["document_revisions"].update_one(
            {"_id": revision["_id"], "migration_id": MIGRATION_ID},
            {"$set": {"verification": record}})
        if result.matched_count != 1:
            skipped += 1
            print(f"  SKIPPED {doc_id[:22]} — changed underneath us, not overwritten")
            continue
        if result.modified_count == 1:
            written += 1
        else:
            unchanged += 1
        print(f"  {doc_id[:22]:24} {str(template):22} {bucket}")

    print(f"\nwritten {written} | already identical {unchanged} | skipped {skipped}")
    print(f"buckets {summary}")

    print("\n=== read back from the database ===")
    after = await db["document_revisions"].find(
        {"migration_id": MIGRATION_ID}).to_list(length=None)
    ran = sum(1 for r in after if (r.get("verification") or {}).get("ran"))
    print(f"  verification.ran == True : {ran} of {len(after)}")
    print(f"  verification.ran == False: {len(after) - ran} of {len(after)}")

    docs = await db["documents"].count_documents({})
    v2 = await db["documents"].count_documents({"schema_version": 2})
    revs = await db["document_revisions"].count_documents({})
    print(f"\n  documents {docs} (schema_version 2: {v2}) | revisions {revs}"
          f"  — unchanged counts expected")
    print(f"  DOCUMENTS_V2 still {settings.documents_v2}")
    print(f"\n  to undo: restore `verification` from {backup.name}")
    return 0 if skipped == 0 else 1


raise SystemExit(asyncio.run(main()))
