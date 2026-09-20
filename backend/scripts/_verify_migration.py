"""Post-migration verification. READ-ONLY, and it repairs nothing.

Run under the read-only v2_survey credential so "does not modify production" is
enforced by the database rather than asserted by me. Every mismatch is collected
and reported; nothing is corrected.

Compared against three independent references:
  * the APPROVED dry-run #2 manifest (what was authorised),
  * the pre-migration BACKUP (what the estate looked like before),
  * the artifact bytes on disk (what the files actually contain).
"""
import hashlib
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import bson  # noqa: E402
from pymongo import MongoClient  # noqa: E402

UPLOADS = BACKEND / "uploads"
problems: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  -- ' + detail) if detail and not ok else ''}")
    if not ok:
        problems.append(f"{label}: {detail}")


uri = Path(os.environ["TEMP"], "v2s.txt").read_text(encoding="utf-8")
client = MongoClient(uri, serverSelectionTimeoutMS=30000)
db = client["attorney_ai"]

roles = sorted({r["role"] for r in db.command(
    {"connectionStatus": 1, "showPrivileges": True})["authInfo"]["authenticatedUserRoles"]})
print(f"credential: {roles}")
if roles != ["read"]:
    raise SystemExit("ABORT: verification must run read-only")

plan = json.loads(sorted(Path.home().glob("v2-approved-*.json"))[-1]
                  .read_text(encoding="utf-8"))
planned = {r["document_id"]: r for r in plan["records"]}
backup_dir = sorted(Path.home().glob("v2-backup-*"))[-1]
pre = {d["_id"]: d for d in bson.decode_all(
    (backup_dir / "mongo" / "documents.bson").read_bytes())}

docs = {d["_id"]: d for d in db["documents"].find({})}
revs = {r["_id"]: r for r in db["document_revisions"].find({})}

print(f"\nplan {len(planned)} records | backup {len(pre)} documents | "
      f"live {len(docs)} documents, {len(revs)} revisions\n")

print("=== documents ===")
check("19 documents present", len(docs) == 19, f"found {len(docs)}")
check("document id set matches the plan", set(docs) == set(planned))
check("every document schema_version == 2",
      all(d.get("schema_version") == 2 for d in docs.values()))
check("every document carries the PLANNED current_revision_id",
      all(docs[i].get("current_revision_id") == planned[i]["planned_revision_id"]
          for i in planned))
check("every document carries the migration_id",
      all(d.get("migration_id") == plan["migration_id"] for d in docs.values()))
check("every document carries a rollback_token",
      all(d.get("rollback_token") for d in docs.values()))

print("\n=== revisions ===")
check("exactly 19 revisions", len(revs) == 19, f"found {len(revs)}")
check("revision ids are exactly the planned ids",
      set(revs) == {r["planned_revision_id"] for r in planned.values()})
check("every revision version == 1",
      all(r.get("version") == 1 for r in revs.values()))
check("every revision status == generated",
      all(r.get("status") == "generated" for r in revs.values()))
by_doc = {}
for r in revs.values():
    by_doc.setdefault(r.get("document_id"), []).append(r)
check("exactly one revision per document",
      all(len(v) == 1 for v in by_doc.values()) and set(by_doc) == set(planned))
check("no orphan revisions (every document_id exists)",
      all(d in docs for d in by_doc))
check("every revision document_id matches the plan",
      all(by_doc[i][0]["document_id"] == i for i in planned))
check("every revision pdf_sha256 matches the approved plan",
      all(by_doc[i][0].get("pdf_sha256") == planned[i]["byte_sha256"]
          for i in planned))

print("\n=== V2 artifact files ===")
missing_art, bad_hash = [], []
for i, rec in planned.items():
    rev = by_doc[i][0]
    key = rev.get("artifact_key")
    path = UPLOADS / "v2" / Path(key) if key else None
    if not key or not path.is_file():
        missing_art.append(i)
        continue
    if hashlib.sha256(path.read_bytes()).hexdigest() != rec["byte_sha256"]:
        bad_hash.append(i)
check("all 19 V2 artifacts exist", not missing_art, f"missing {missing_art}")
check("all 19 V2 artifact hashes match the source bytes", not bad_hash,
      f"mismatched {bad_hash}")

print("\n=== legacy artifacts untouched ===")
gone, changed, path_changed = [], [], []
for i, rec in planned.items():
    live_path = docs[i].get("file_path")
    if live_path != pre[i].get("file_path"):
        path_changed.append(i)
    p = Path(live_path) if live_path else None
    if not p or not p.is_file():
        gone.append(i)
    elif hashlib.sha256(p.read_bytes()).hexdigest() != rec["byte_sha256"]:
        changed.append(i)
check("every legacy file_path unchanged since the backup", not path_changed,
      f"changed {path_changed}")
check("every legacy PDF still on disk", not gone, f"missing {gone}")
check("every legacy PDF byte-identical to the plan", not changed,
      f"changed {changed}")
legacy_count = len(list((UPLOADS / "docs").glob("*.pdf")))
check("legacy directory still holds 13,386 PDFs", legacy_count == 13386,
      f"found {legacy_count}")

print("\n=== previously-submitted documents ===")
submitted = [i for i, r in planned.items()
             if r["outcome"] == "submitted_reviewable"]
check("exactly 2 submitted documents", len(submitted) == 2)
for i in submitted:
    d = docs[i]
    check(f"{i[:22]} review_status == submitted",
          d.get("review_status") == "submitted", str(d.get("review_status")))
    check(f"{i[:22]} reviewer preserved",
          d.get("submitted_to") == pre[i].get("submitted_to"))
    check(f"{i[:22]} submitted_revision_id populated",
          bool(d.get("submitted_revision_id")))

print("\n=== no unexpected migration artifacts ===")
for name, expected in (("review_events", 0), ("transition_receipts", 0),
                       ("event_outbox", 0), ("deletion_tombstones", 0)):
    try:
        n = db[name].count_documents({})
    except Exception:
        n = 0
    check(f"{name} == {expected}", n == expected, f"found {n}")
pre_notif = len(bson.decode_all(
    (backup_dir / "mongo" / "notifications.bson").read_bytes()))
now_notif = db["notifications"].count_documents({})
check("notifications unchanged since the backup", now_notif == pre_notif,
      f"{pre_notif} -> {now_notif}")
check("no review_cycles written",
      all(not d.get("review_cycles") for d in docs.values()))

print("\n=== ChromaDB citation verification ===")
ran = sum(1 for r in revs.values() if (r.get("verification") or {}).get("ran"))
print(f"  revisions with verification.ran == True : {ran} of {len(revs)}")
print(f"  revisions with verification.ran == False: {len(revs) - ran}")

client.close()

print("\n" + "=" * 62)
if problems:
    print(f"VERIFICATION FAILED -- {len(problems)} mismatch(es), NOT repaired:")
    for p in problems:
        print(f"  - {p}")
else:
    print("VERIFICATION PASSED -- every check above holds.")
raise SystemExit(1 if problems else 0)
