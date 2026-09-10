"""Apply the approved DOCUMENTS_V2 migration. Uses ONLY the authorised manifest.

Nothing is re-planned. The manifest is loaded from disk and every identifier the
owner authorised is checked before a client is even constructed; any mismatch
aborts before the first write.

The rollback plan is written to disk IMMEDIATELY after apply() returns, before
anything is printed or summarised. If this process dies between the write and
the report, the thing needed to undo the migration is already safe on disk.
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

MANIFEST = Path.home() / "v2-approved-20260906T031427Z.json"
MIGRATION_ID = "mig-349ef601-6b65-447a-ba58-42dd8d1c6823"
FINGERPRINT = "e8cab67fdf03264f6a3bdaac99d00a1f71c8c6a5ba8b7821ddc49c2f0a766bf5"
DECISION_SET = "ds-20260906T031709Z-19docs-0-approval-outcomes"


async def main() -> int:
    from app.core.config import settings

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    print("=== pre-flight: is this the authorised plan? ===")
    checks = {
        "manifest file": MANIFEST.name,
        "migration_id": manifest["migration_id"] == MIGRATION_ID,
        "fingerprint": manifest["fingerprint"] == FINGERPRINT,
        "decision_set_id": manifest["approved_decision_set"]["id"] == DECISION_SET,
        "records == 19": len(manifest["records"]) == 19,
        "approval outcomes == 0": manifest["requires_owner_approval"] == [],
        "blocked == 0": manifest["summary"]["blocked"] == 0,
        "DOCUMENTS_V2 is False": settings.documents_v2 is False,
    }
    for name, value in checks.items():
        print(f"  {name:24} {value}")
    if not all(v for k, v in checks.items() if k != "manifest file"):
        raise SystemExit("ABORT: this is not the authorised plan, or the flag is on")

    from app.db.mongodb import connect_db, get_database
    from app.services.document_migration import apply

    await connect_db()
    db = get_database()
    info = await db.command({"connectionStatus": 1, "showPrivileges": True})
    roles = sorted({r["role"] for r in info["authInfo"]["authenticatedUserRoles"]})
    print(f"  credential               {roles} (writes required)")
    print()

    before = {name: await db[name].count_documents({})
              for name in ("documents", "document_revisions", "review_events")}
    before["v2_documents"] = await db["documents"].count_documents(
        {"schema_version": 2})
    print(f"pre-apply counts  {before}")
    print()
    print("=== applying ===")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        result = await apply(manifest)
    except Exception as exc:
        print(f"APPLY FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        after = {name: await db[name].count_documents({})
                 for name in ("documents", "document_revisions", "review_events")}
        after["v2_documents"] = await db["documents"].count_documents(
            {"schema_version": 2})
        print(f"post-failure counts {after}", file=sys.stderr)
        return 2

    # The rollback plan goes to disk before anything else happens with it.
    rollback_path = Path.home() / f"v2-rollback-{stamp}.json"
    rollback_path.write_text(
        json.dumps(result["rollback_plan"], indent=2, sort_keys=True, default=str),
        encoding="utf-8")
    result_path = Path.home() / f"v2-apply-result-{stamp}.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str),
        encoding="utf-8")

    summary = result["summary"]
    print()
    print("=== summary ===")
    for key, value in sorted(summary.items()):
        print(f"  {key:26} {value}")
    print()
    print(f"=== failures: {len(result['failures'])} ===")
    for failure in result["failures"]:
        print(f"  {failure}")
    print()
    print("=== by outcome ===")
    for code, count in sorted(result["by_outcome"].items()):
        print(f"  {code:26} {count}")

    after = {name: await db[name].count_documents({})
             for name in ("documents", "document_revisions", "review_events")}
    after["v2_documents"] = await db["documents"].count_documents(
        {"schema_version": 2})
    print()
    print("=== direct post-apply counts ===")
    for key in ("documents", "v2_documents", "document_revisions", "review_events"):
        print(f"  {key:22} {before[key]:>4}  ->  {after[key]:>4}")

    plan = result["rollback_plan"]
    print()
    print("=== rollback ===")
    header = {k: v for k, v in plan.items() if k != "entries"}
    for key, value in sorted(header.items()):
        print(f"  {key:26} {value}")
    print(f"  entries                    {len(plan.get('entries', []))}")
    print(f"  saved to                   {rollback_path.name}")
    print(f"  apply result saved to      {result_path.name}")
    print()
    print(f"reconciles: {summary['reconciles']} "
          f"({summary['accounted_records']}/{summary['planned_records']})")
    return 0 if (summary["reconciles"] and not result["failures"]) else 1


raise SystemExit(asyncio.run(main()))
