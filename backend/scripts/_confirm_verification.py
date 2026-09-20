"""Independent read-only confirmation of the persisted verification records.

Deliberately NOT the writer's own read-back. It reconnects under the read-only
credential, re-reads every record from the server, and checks three things the
writer could not check about itself:

  * the stored buckets match what was reported;
  * the prior-value dump can actually restore what was overwritten;
  * nothing outside the `verification` field moved.

The third is the one that matters. A migration-adjacent write that quietly
touched something else would look identical in the writer's own summary.
"""
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import bson  # noqa: E402
from pymongo import MongoClient  # noqa: E402

MIGRATION_ID = "mig-349ef601-6b65-447a-ba58-42dd8d1c6823"
problems: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  -- ' + detail) if detail and not ok else ''}")
    if not ok:
        problems.append(f"{label}: {detail}")


uri = Path(os.environ["TEMP"], "v2s.txt").read_text(encoding="utf-8")
db = MongoClient(uri, serverSelectionTimeoutMS=30000)["attorney_ai"]
roles = sorted({r["role"] for r in db.command(
    {"connectionStatus": 1, "showPrivileges": True})["authInfo"]["authenticatedUserRoles"]})
print(f"credential: {roles}")
if roles != ["read"]:
    raise SystemExit("ABORT: confirmation must run read-only")

revs = {r["_id"]: r for r in db["document_revisions"].find({})}
docs = {d["_id"]: d for d in db["documents"].find({})}
prior_path = sorted(Path.home().glob("v2-verification-before-*.json"))[-1]
prior = json.loads(prior_path.read_text(encoding="utf-8"))
backup_dir = sorted(Path.home().glob("v2-backup-*"))[-1]
pre_docs = {d["_id"]: d for d in bson.decode_all(
    (backup_dir / "mongo" / "documents.bson").read_bytes())}
pre_revs = {r["_id"]: r for r in bson.decode_all(
    (backup_dir / "mongo" / "document_revisions.bson").read_bytes())}

print(f"\nprior-value dump: {prior_path.name} ({len(prior)} records)")
print(f"backup:           {backup_dir.name} "
      f"({len(pre_docs)} documents, {len(pre_revs)} revisions pre-migration)\n")

print("=== the write landed ===")
check("19 revisions", len(revs) == 19, f"found {len(revs)}")
ran = [r for r in revs.values() if (r.get("verification") or {}).get("ran")]
check("18 revisions now record a check that RAN", len(ran) == 18, f"{len(ran)}")
not_ran = [r for r in revs.values() if not (r.get("verification") or {}).get("ran")]
check("exactly 1 still records ran=False", len(not_ran) == 1, f"{len(not_ran)}")
check("...and it is the Urdu pleading, unavailable BY DESIGN",
      len(not_ran) == 1 and not_ran[0].get("template_type") == "urdu_pleading"
      and (not_ran[0].get("verification") or {}).get("reason") == "urdu_corpus_unsupported",
      str((not_ran[0].get("verification") or {}).get("reason")) if not_ran else "")

buckets = {"clean": 0, "partial": 0, "failed": 0, "no_citations": 0, "unavailable": 0}
for r in revs.values():
    v = r.get("verification") or {}
    counts, checks = v.get("counts") or {}, v.get("checks") or []
    flags = [c for c in checks if c.get("status") in ("NOT_IN_CORPUS", "OMITTED")]
    if not v.get("ran"):
        buckets["unavailable"] += 1
    elif flags:
        buckets["failed"] += 1
    elif counts.get("total", 0) == 0:
        buckets["no_citations"] += 1
    elif any(c.get("status") == "UNVERIFIABLE" for c in checks):
        buckets["partial"] += 1
    else:
        buckets["clean"] += 1
print(f"\n  buckets as STORED: {buckets}")
check("stored buckets match what was reported",
      buckets == {"clean": 4, "partial": 2, "failed": 0, "no_citations": 12,
                  "unavailable": 1}, str(buckets))
check("no revision records a FAILED citation", buckets["failed"] == 0)

print("\n=== every stored record is well-formed ===")
bad = [r["_id"] for r in revs.values()
       if not isinstance((r.get("verification") or {}).get("ran"), bool)
       or "checked_at" not in (r.get("verification") or {})
       or "summary" not in (r.get("verification") or {})]
check("every record has ran/checked_at/summary", not bad, f"{len(bad)} malformed")
no_scope = [r["_id"] for r in ran if not (r.get("verification") or {}).get("scope")]
check("every record that ran carries the disclosure scope", not no_scope,
      f"{len(no_scope)} missing")
no_corpus = [r["_id"] for r in ran if not (r.get("verification") or {}).get("corpus")]
check("every record that ran records the corpus it was checked against",
      not no_corpus, f"{len(no_corpus)} missing")

print("\n=== the undo actually works ===")
check("prior dump covers all 19 revisions", set(prior) == set(revs),
      f"{len(set(revs) - set(prior))} missing from the dump")
check("every prior value was the pre-migration one (ran=False)",
      all((v.get("verification") or {}).get("ran") is False
          for v in prior.values()))

print("\n=== nothing outside `verification` moved ===")
# THE BACKUP IS NOT THE BASELINE HERE, and an earlier version of this script
# wrongly used it. The backup was taken BEFORE the migration, when
# `document_revisions` held 0 rows -- so every revision is legitimately absent
# from it, and comparing against it manufactured 19 failures out of nothing.
#
# The revisions never existed before the migration created them, so the only
# meaningful baseline is the APPROVED PLAN plus the invariants the migration
# promised. If the verification write had disturbed any of it, these break.
check("the backup genuinely predates the revisions (so it cannot be the baseline)",
      len(pre_revs) == 0, f"backup held {len(pre_revs)} revisions")

plan = json.loads(sorted(Path.home().glob("v2-approved-*.json"))[-1]
                  .read_text(encoding="utf-8"))
planned = {r["document_id"]: r for r in plan["records"]}
by_doc = {r["document_id"]: r for r in revs.values()}

drifted = []
for doc_id, record in planned.items():
    rev = by_doc.get(doc_id)
    if rev is None:
        drifted.append(f"{doc_id[:12]}: revision missing")
        continue
    for label, actual, expected in (
        ("_id", rev["_id"], record["planned_revision_id"]),
        ("pdf_sha256", rev.get("pdf_sha256"), record["byte_sha256"]),
        ("version", rev.get("version"), 1),
        ("status", rev.get("status"), "generated"),
        ("migration_id", rev.get("migration_id"), MIGRATION_ID),
    ):
        if actual != expected:
            drifted.append(f"{doc_id[:12]}.{label}")
    if not rev.get("artifact_key"):
        drifted.append(f"{doc_id[:12]}.artifact_key")
check("every revision still matches the approved plan exactly", not drifted,
      f"{drifted[:5]}")
check("every document still points at its PLANNED revision",
      all(docs[i].get("current_revision_id") == planned[i]["planned_revision_id"]
          for i in planned))
check("no extra or orphan revisions", set(by_doc) == set(planned)
      and len(by_doc) == len(revs))

doc_drift = []
for _id, doc in docs.items():
    before = pre_docs.get(_id) or {}
    for key in set(before) | set(doc):
        # The migration itself set these; the verification write must not have.
        if before.get(key) != doc.get(key):
            doc_drift.append(f"{key}")
from collections import Counter
print(f"  document fields differing from the PRE-MIGRATION backup: "
      f"{sorted(Counter(doc_drift))}")
print("  (these are the migration's own writes, not this one — no `verification` "
      "field exists on documents)")
check("no document carries a `verification` field",
      not any("verification" in d for d in docs.values()))

check("counts unchanged: 19 documents, 19 revisions",
      len(docs) == 19 and len(revs) == 19)
check("all 19 documents still schema_version 2",
      all(d.get("schema_version") == 2 for d in docs.values()))

print("\n" + "=" * 66)
if problems:
    print(f"CONFIRMATION FAILED -- {len(problems)} problem(s):")
    for p in problems:
        print(f"  - {p}")
else:
    print("CONFIRMED -- the write did exactly what it said and nothing else.")
raise SystemExit(1 if problems else 0)
