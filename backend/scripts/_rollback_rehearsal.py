"""Rehearse the DOCUMENTS_V2 rollback end to end, in a TEST database.

WHY. There is a 19-entry rollback plan for a migration that has already been
applied to production, and it has never been executed against anything but
synthetic fixtures. A rollback you have not run is worth nothing until the
moment you need it, at which point it is the only thing that matters.

THE SEQUENCE
    1. restore the PRE-MIGRATION backup into attorney_ai_test
    2. apply() the approved manifest there -- should reproduce 19/19
    3. rollback() with the preserved plan
    4. compare the result, field by field, against the backup
    5. remove everything this created

SAFETY
  * Every write is name-checked to a database ending `_test`, before the first
    insert, and again after connecting.
  * Production is never connected. The pre-migration state comes from the
    BACKUP FILE on disk, not from a live read.
  * `upload_root` is a temp directory, so artifact writes never touch the real
    store. Legacy PDFs are READ from their recorded paths -- reads only.
  * `DOCUMENTS_V2` is never set.
  * Cleanup runs in `finally`, pass or fail.

ONE EXPECTATION THAT IS WRONG, AND THE CODE IS RIGHT
`rollback()` does NOT delete revision rows -- "Revision rows and review_events
are NEVER dropped -- they are audit records; a rolled back document simply stops
pointing at them." So a correct rollback leaves 19 ORPHANED revisions behind.
This script checks that they are orphaned rather than expecting them gone.
"""
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import bson  # noqa: E402

problems: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}"
          f"{('  -- ' + detail) if detail and not ok else ''}")
    if not ok:
        problems.append(f"{label}: {detail}")


async def main() -> int:
    from app.core.config import settings

    if settings.documents_v2:
        raise SystemExit("ABORT: DOCUMENTS_V2 is on")

    backup_dir = sorted(Path.home().glob("v2-backup-*"))[-1]
    manifest = json.loads(
        (sorted(Path.home().glob("v2-approved-*.json"))[-1]).read_text(encoding="utf-8"))
    rollback_plan = json.loads(
        (sorted(Path.home().glob("v2-rollback-*.json"))[-1]).read_text(encoding="utf-8"))

    pre_docs = bson.decode_all((backup_dir / "mongo" / "documents.bson").read_bytes())
    pre_revs = bson.decode_all(
        (backup_dir / "mongo" / "document_revisions.bson").read_bytes())
    print(f"backup        : {backup_dir.name}")
    print(f"  pre-migration documents : {len(pre_docs)}")
    print(f"  pre-migration revisions : {len(pre_revs)}")
    print(f"manifest      : {manifest['migration_id']} ({len(manifest['records'])} records)")
    print(f"rollback plan : {len(rollback_plan['entries'])} entries")
    if len(pre_docs) != 19 or pre_revs or len(rollback_plan["entries"]) != 19:
        raise SystemExit("ABORT: unexpected backup or plan shape")

    tmp_root = Path(tempfile.mkdtemp(prefix="rollback-rehearsal-"))
    settings.upload_root = str(tmp_root)
    if not settings.db_name.endswith("_test"):
        settings.db_name = f"{settings.db_name}_test"
    if not settings.db_name.endswith("_test"):
        raise SystemExit("ABORT: refusing to write outside a _test database")

    from app.db.mongodb import connect_db, get_database
    await connect_db()
    db = get_database()
    print(f"\ntarget        : {db.name}   (upload root: temporary)")
    if not db.name.endswith("_test"):
        raise SystemExit(f"ABORT: connected to {db.name}")

    doc_ids = [d["_id"] for d in pre_docs]
    rev_ids = [r["planned_revision_id"] for r in manifest["records"]]
    try:
        from app.services import artifact_store as store
        store.ensure_dirs()

        # ── 1. restore the pre-migration estate ──────────────────────────────
        await db["documents"].delete_many({"_id": {"$in": doc_ids}})
        await db["document_revisions"].delete_many({"_id": {"$in": rev_ids}})
        await db["documents"].insert_many([dict(d) for d in pre_docs])
        from app.db.indexes import create_all_indexes
        await create_all_indexes()
        print(f"\n=== 1. restored ===")
        check("19 legacy documents restored",
              await db["documents"].count_documents({"_id": {"$in": doc_ids}}) == 19)
        check("no document carries schema_version 2",
              await db["documents"].count_documents(
                  {"_id": {"$in": doc_ids}, "schema_version": 2}) == 0)
        check("document_revisions holds none of the planned ids",
              await db["document_revisions"].count_documents(
                  {"_id": {"$in": rev_ids}}) == 0)

        # ── 2. apply ─────────────────────────────────────────────────────────
        print("\n=== 2. apply ===")
        from app.services.document_migration import apply, rollback
        result = await apply(manifest)
        summary = result["summary"]
        print(f"  {dict(sorted(summary.items()))}")
        check("19 applied", summary.get("applied") == 19, str(summary.get("applied")))
        check("0 failed", not result["failures"], str(result["failures"][:2]))
        check("reconciles", summary.get("reconciles") is True)
        check("all 19 now schema_version 2",
              await db["documents"].count_documents(
                  {"_id": {"$in": doc_ids}, "schema_version": 2}) == 19)
        check("19 revisions written",
              await db["document_revisions"].count_documents(
                  {"_id": {"$in": rev_ids}}) == 19)

        # ── 3a. the PRODUCTION plan must be refused here ─────────────────────
        #
        # Found by running this rehearsal: every entry carries a `rollback_token`
        # minted by the apply() that wrote the document. A fresh apply() in the
        # test database mints new ones, so the production plan no longer matches
        # and `_verify_entries_against_documents` rejects it.
        #
        # That is the guard doing its job -- a rollback plan cannot be replayed
        # against rows it did not migrate. It also means the SAVED PRODUCTION
        # PLAN CANNOT BE REHEARSED ANYWHERE BUT PRODUCTION. What is rehearsable
        # is the mechanism, using the plan this apply() produced.
        print("\n=== 3a. the production plan, against foreign rows ===")
        from app.services.document_migration import RollbackRejected
        try:
            await rollback(rollback_plan)
            check("the production plan is refused against rows it did not migrate",
                  False, "it was ACCEPTED — the token guard did not fire")
        except RollbackRejected as exc:
            check("the production plan is refused against rows it did not migrate",
                  True)
            print(f"         refused with: {str(exc)[:88]}")

        # ── 3b. roll back with THIS run's plan ───────────────────────────────
        print("\n=== 3b. rollback with the plan this apply() produced ===")
        out = await rollback(result["rollback_plan"])
        print(f"  {dict(sorted((k, v) for k, v in out.items() if k != 'skipped_documents'))}")
        check("19 documents restored by rollback", out.get("restored") == 19,
              str(out.get("restored")))
        check("nothing skipped", not out.get("skipped_documents"),
              str(out.get("skipped_documents", [])[:2]))

        # ── 4. compare to the pre-migration state ────────────────────────────
        print("\n=== 4. does the estate match the backup, field for field? ===")
        after = {d["_id"]: d for d in
                 await db["documents"].find({"_id": {"$in": doc_ids}}).to_list(None)}
        before = {d["_id"]: d for d in pre_docs}
        check("19 documents present", len(after) == 19, str(len(after)))

        differing: dict = {}
        for _id, original in before.items():
            now = after.get(_id, {})
            for key in set(original) | set(now):
                if original.get(key) != now.get(key):
                    differing.setdefault(key, []).append(_id)
        check("every document byte-identical to the backup", not differing,
              f"fields differing: { {k: len(v) for k, v in differing.items()} }")

        v2_residue = {}
        for field in ("schema_version", "current_revision_id", "current_version",
                      "migration_id", "migration_outcome", "migrated_at",
                      "rollback_token", "rev_seq", "event_seq", "pending_events",
                      "review_cycles", "submitted_revision_id", "submitted_version",
                      "submitted_pdf_sha256"):
            n = await db["documents"].count_documents(
                {"_id": {"$in": doc_ids}, field: {"$exists": True}})
            pre_n = sum(1 for d in pre_docs if field in d)
            if n != pre_n:
                v2_residue[field] = f"{n} now vs {pre_n} before"
        check("no V2 field residue on any document", not v2_residue, str(v2_residue))

        submitted = [d for d in pre_docs if d.get("review_status") == "submitted"]
        check(f"the {len(submitted)} submitted documents have review_status restored",
              all(after[d["_id"]].get("review_status") == "submitted"
                  for d in submitted))
        check("submitted_to preserved on those",
              all(after[d["_id"]].get("submitted_to") == d.get("submitted_to")
                  for d in submitted))

        # Revisions: kept ON PURPOSE, and must be orphaned.
        print("\n=== 5. revisions: preserved as audit records, by design ===")
        left = await db["document_revisions"].find(
            {"_id": {"$in": rev_ids}}).to_list(None)
        print(f"  revision rows remaining : {len(left)}  (rollback never drops them)")
        pointers = await db["documents"].count_documents(
            {"_id": {"$in": doc_ids}, "current_revision_id": {"$exists": True}})
        check("no document still points at a revision", pointers == 0, str(pointers))
        check("the preserved revisions are therefore orphaned",
              len(left) == 19 and pointers == 0,
              f"{len(left)} rows, {pointers} pointers")

    finally:
        removed_d = (await db["documents"]
                     .delete_many({"_id": {"$in": doc_ids}})).deleted_count
        removed_r = (await db["document_revisions"]
                     .delete_many({"_id": {"$in": rev_ids}})).deleted_count
        shutil.rmtree(tmp_root, ignore_errors=True)
        print(f"\n=== 6. cleanup ===")
        print(f"  removed {removed_d} documents and {removed_r} revisions from {db.name}")
        print(f"  temp upload root deleted; DOCUMENTS_V2 still {settings.documents_v2}")

    print("\n" + "=" * 70)
    if problems:
        print(f"REHEARSAL FAILED -- {len(problems)} mismatch(es):")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print("REHEARSAL PASSED -- apply and rollback both behave as documented.")
    return 1 if problems else 0


raise SystemExit(asyncio.run(main()))
