"""Drive the real V2 read path over the 19 MIGRATED rows, in a test database.

WHY THIS EXISTS. Every V2 test runs against synthetic fixtures. The migrated
rows have a shape no fixture reproduces: legacy fields carried forward, plus
`migration_id`, `migration_outcome`, `rollback_token`, `rev_seq`, `event_seq`
and `pending_events` written by apply(). Nothing has ever confirmed the
application can actually serve THOSE rows. If a serializer trips on one, the
place to find out is here, not at activation in front of a client.

SAFETY, in order of importance:

  * Production is read with a `read`-only credential, asserted before the first
    query. It is never written to and never connected with a writable user.
  * Every write goes to a database whose name must end `_test`, checked before
    anything is inserted.
  * `DOCUMENTS_V2` is turned on IN THIS PROCESS ONLY, by setting the attribute
    on the loaded settings object. Nothing touches `.env`; the deployed flag is
    unaffected and is still False when this exits.
  * `upload_root` is repointed at a temporary directory and the 19 artifacts are
    COPIED into it, so no production file is opened by the code under test.
  * The rows this seeds are removed at the end, pass or fail.

The route handlers are called directly, as the existing V2 tests do — the
question is whether the handlers can serve migrated rows, not whether FastAPI
can route to them.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from pymongo import MongoClient  # noqa: E402

problems: list = []
notes: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}"
          f"{('  -- ' + detail) if detail and not ok else ''}")
    if not ok:
        problems.append(f"{label}: {detail}")


async def main() -> int:
    # ── 1. read production, read-only ────────────────────────────────────────
    uri = Path(os.environ["TEMP"], "v2s.txt").read_text(encoding="utf-8")
    src = MongoClient(uri, serverSelectionTimeoutMS=30000)["attorney_ai"]
    roles = sorted({r["role"] for r in src.command(
        {"connectionStatus": 1, "showPrivileges": True}
    )["authInfo"]["authenticatedUserRoles"]})
    print(f"source credential : {roles}")
    if roles != ["read"]:
        raise SystemExit("ABORT: production must be read read-only")

    documents = list(src["documents"].find({}))
    revisions = list(src["document_revisions"].find({}))
    print(f"read from production: {len(documents)} documents, "
          f"{len(revisions)} revisions")
    if len(documents) != 19 or len(revisions) != 19:
        raise SystemExit("ABORT: expected the 19-document estate")
    src.client.close()

    # ── 2. redirect everything away from production ──────────────────────────
    from app.core.config import settings

    tmp_root = Path(tempfile.mkdtemp(prefix="v2-rehearsal-"))
    real_upload_root = Path(settings.upload_root)
    settings.upload_root = str(tmp_root)
    settings.documents_v2 = True                     # in this process only
    if not settings.db_name.endswith("_test"):
        settings.db_name = f"{settings.db_name}_test"
    print(f"\ntest database     : {settings.db_name}")
    print(f"upload root       : temporary, {tmp_root.name}")
    print(f"DOCUMENTS_V2      : {settings.documents_v2} (in-process only)")
    if not settings.db_name.endswith("_test"):
        raise SystemExit("ABORT: refusing to write outside a _test database")

    from app.db.mongodb import connect_db, get_database
    await connect_db()
    db = get_database()
    if not db.name.endswith("_test"):
        raise SystemExit(f"ABORT: connected to {db.name}")

    # Copy the artifacts the revisions reference, so the code under test never
    # opens a production file.
    from app.services import artifact_store as store
    store.ensure_dirs()
    copied = 0
    for revision in revisions:
        key = revision.get("artifact_key")
        if not key:
            continue
        source = real_upload_root / "v2" / key
        target = tmp_root / "v2" / key
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            shutil.copy2(source, target)
            copied += 1
    print(f"artifacts copied  : {copied} of {len(revisions)}")

    doc_ids = [d["_id"] for d in documents]
    rev_ids = [r["_id"] for r in revisions]
    try:
        # ── 3. seed and index ────────────────────────────────────────────────
        await db["documents"].delete_many({"_id": {"$in": doc_ids}})
        await db["document_revisions"].delete_many({"_id": {"$in": rev_ids}})
        await db["documents"].insert_many(documents)
        await db["document_revisions"].insert_many(revisions)
        from app.db.indexes import create_all_indexes
        await create_all_indexes()
        print(f"seeded            : {await db['documents'].count_documents({})} "
              f"documents, {await db['document_revisions'].count_documents({})} "
              f"revisions (test database)\n")

        import app.api.v1.routes.documents_v2 as v2api

        owners = {}
        for document in documents:
            owners.setdefault(document.get("client_id"), []).append(document)
        print(f"owners in the estate: {len(owners)}")

        # ── 4. /documents/v2/mine, every owner, fully paged ──────────────────
        print("\n=== GET /documents/v2/mine ===")
        seen_total = 0
        for owner_id, owned in sorted(owners.items(), key=lambda kv: -len(kv[1])):
            user = {"_id": owner_id, "role": "client"}
            collected, cursor, pages = [], None, 0
            while True:
                page = await v2api.my_documents_v2(cursor=cursor, limit=2,
                                                   current_user=user)
                collected.extend(page["items"])
                pages += 1
                cursor = page.get("next_cursor")
                if not cursor or pages > 50:
                    break
            seen_total += len(collected)
            ids = [i["id"] for i in collected]
            check(f"owner {owner_id[:10]}… sees all {len(owned)} of their documents "
                  f"across {pages} pages",
                  sorted(ids) == sorted(d["_id"] for d in owned),
                  f"got {len(ids)}, expected {len(owned)}")
            check(f"owner {owner_id[:10]}… no duplicates across page boundaries",
                  len(ids) == len(set(ids)))
        check("every document is visible to exactly one owner",
              seen_total == 19, f"{seen_total} of 19")

        # ── 5. the fields a client actually renders ─────────────────────────
        print("\n=== the shape the client renders ===")
        by_id = {d["_id"]: d for d in documents}
        rev_by_id = {r["_id"]: r for r in revisions}
        sample_user = {"_id": documents[0]["client_id"], "role": "client"}
        page = await v2api.my_documents_v2(cursor=None, limit=100,
                                           current_user=sample_user)
        row = page["items"][0]
        print(f"  keys returned: {sorted(row)}")
        check("each row carries the revision hash a download needs",
              all(i.get("pdf_sha256") for i in page["items"]))
        check("the hash matches the stored revision",
              all(i["pdf_sha256"]
                  == rev_by_id[by_id[i["id"]]["current_revision_id"]]["pdf_sha256"]
                  for i in page["items"] if by_id[i["id"]].get("current_revision_id")))
        check("every row is marked downloadable (all 19 revisions generated)",
              all(i.get("downloadable") for i in page["items"]),
              str([i["id"][:8] for i in page["items"] if not i.get("downloadable")]))
        check("each row carries the revision id a preview needs",
              all(i.get("revision_id") for i in page["items"]))
        check("each row reports a migration recovery hint",
              all("recovery" in i for i in page["items"]))
        leaked = [k for k in row if k in ("pending_events", "receipts",
                                          "rollback_token", "migration_id",
                                          "file_path", "fields")]
        check("no migration or replay-token field leaks into the listing",
              not leaked, f"leaked {leaked}")

        # ── 6. every document individually, and its revisions ────────────────
        print("\n=== GET /documents/v2/{id} and /revisions ===")
        detail_fail, revlist_fail = [], []
        for document in documents:
            user = {"_id": document["client_id"], "role": "client"}
            try:
                detail = await v2api.get_document_v2(document["_id"],
                                                     current_user=user)
                if detail.get("id") != document["_id"]:
                    detail_fail.append(document["_id"])
            except Exception as exc:
                detail_fail.append(f"{document['_id'][:10]}: {type(exc).__name__}")
            try:
                listing = await v2api.list_revisions_v2(document["_id"], limit=50,
                                                        current_user=user)
                items = listing.get("items", listing) if isinstance(listing, dict) else listing
                if len(items) != 1:
                    revlist_fail.append(f"{document['_id'][:10]}: {len(items)} revisions")
            except Exception as exc:
                revlist_fail.append(f"{document['_id'][:10]}: {type(exc).__name__}")
        check("all 19 documents fetch individually", not detail_fail,
              f"{detail_fail[:4]}")
        check("all 19 list exactly one revision", not revlist_fail,
              f"{revlist_fail[:4]}")

        # ── 7. preview: the bytes, and the guard that protects them ─────────
        print("\n=== GET /revisions/{id}/preview ===")
        preview_fail, guard_fail = [], []
        for document in documents:
            user = {"_id": document["client_id"], "role": "client"}
            rev_id = document.get("current_revision_id")
            revision = rev_by_id.get(rev_id)
            if not revision:
                continue
            try:
                await v2api.preview_revision_v2(
                    document["_id"], rev_id,
                    expected_pdf_sha256=revision["pdf_sha256"], current_user=user)
            except Exception as exc:
                preview_fail.append(f"{document['_id'][:10]}: {type(exc).__name__}: {exc}")
            # A wrong hash must be refused — that guard is what stops a client
            # downloading different bytes than the row described.
            try:
                await v2api.preview_revision_v2(
                    document["_id"], rev_id,
                    expected_pdf_sha256="0" * 64, current_user=user)
                guard_fail.append(document["_id"][:10])
            except Exception:
                pass
        check("all 19 previews resolve with the correct hash", not preview_fail,
              f"{preview_fail[:3]}")
        check("a WRONG hash is refused on all 19", not guard_fail,
              f"served anyway: {guard_fail[:4]}")

        # ── 8. ownership: another client must not see them ───────────────────
        print("\n=== ownership ===")
        stranger = {"_id": "rehearsal-stranger", "role": "client"}
        stranger_page = await v2api.my_documents_v2(cursor=None, limit=100,
                                                    current_user=stranger)
        check("a stranger's listing is empty", not stranger_page["items"],
              f"{len(stranger_page['items'])} rows")
        denied = 0
        for document in documents[:5]:
            try:
                await v2api.get_document_v2(document["_id"], current_user=stranger)
            except Exception:
                denied += 1
        check("a stranger is refused each document", denied == 5, f"{denied}/5")

        # ── 9. the lawyer queue, for the two submitted documents ─────────────
        print("\n=== GET /documents/v2/review/queue ===")
        submitted = [d for d in documents if d.get("review_status") == "submitted"]
        reviewers = {d.get("submitted_to") for d in submitted if d.get("submitted_to")}
        print(f"  submitted documents: {len(submitted)}, reviewers: {len(reviewers)}")
        for reviewer in reviewers:
            queue = await v2api.review_queue_v2(
                status="submitted", cursor=None, limit=25,
                current_user={"_id": reviewer, "role": "lawyer"})
            expected = [d["_id"] for d in submitted if d.get("submitted_to") == reviewer]
            got = [i["id"] for i in queue["items"]]
            check(f"reviewer {str(reviewer)[:10]}… sees their "
                  f"{len(expected)} submitted document(s)",
                  sorted(got) == sorted(expected), f"got {len(got)}")

    finally:
        # ── 10. leave the test database as we found it ───────────────────────
        removed_d = (await db["documents"].delete_many({"_id": {"$in": doc_ids}})).deleted_count
        removed_r = (await db["document_revisions"]
                     .delete_many({"_id": {"$in": rev_ids}})).deleted_count
        shutil.rmtree(tmp_root, ignore_errors=True)
        settings.documents_v2 = False
        settings.upload_root = str(real_upload_root)
        print(f"\ncleanup: removed {removed_d} documents and {removed_r} "
              f"revisions from {db.name}; temp upload root deleted")
        print(f"DOCUMENTS_V2 back to {settings.documents_v2}")

    print("\n" + "=" * 68)
    if problems:
        print(f"REHEARSAL FAILED -- {len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print("REHEARSAL PASSED -- the V2 read path serves the migrated rows.")
    return 1 if problems else 0


raise SystemExit(asyncio.run(main()))
