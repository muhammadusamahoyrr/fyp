#!/usr/bin/env python3
"""Count the DOCUMENTS_V2 legacy estate. READ-ONLY, and not a dry-run.

WHAT THIS IS FOR
----------------
Four migration policy decisions are waiting on an owner, and the blocked-record
count is unknown. Both were being held behind "we need a verified snapshot
first" -- which was wrong. Deciding "do you accept this behaviour for N
documents?" needs N. It does not need determinism, a frozen boundary, a capture
manifest or a restore, because the answer is about magnitude, not about
byte-for-byte reproducibility.

So this counts. Nothing else.

WHAT A FILESYSTEM CENSUS CANNOT TELL YOU
----------------------------------------
Enumerating UPLOAD_ROOT/docs and finding every file readable does NOT establish
that no Mongo-referenced file is missing. The two sets are different: the census
walks what is ON DISK, while the migration reads the paths RECORDED IN ROWS. A
row can point at a path that was never written, was written under a different
UPLOAD_ROOT, or belongs to a deployment whose files are elsewhere -- and none of
those appear in a directory listing. Only resolving each stored `file_path`,
which is what this tool does, answers that question.

WHAT IT IS NOT
--------------
It is NOT dry_run(). It produces no manifest, no plan, no fingerprint, no
rollback token, and nothing it writes can be approved or applied. Counts taken
from a live database drift while people use it; that is fine for sizing a
decision and useless for planning a migration, and the two must not be
confused. A migration still needs the snapshot, the capture manifest and the
validator.

IT MIRRORS _plan_one()
----------------------
The planner surveys `schema_version != 2` only, and for any document carrying a
BLOCKING code it records NO outcome and NO owner-approval requirement -- a
blocked document has not been given a fate. This reproduces that exactly, using
the migration's own `classify()`, `is_supported_status()`, `planned_revision_id()`
and `BLOCKING_CODES`. A second copy of the decision matrix would drift, and the
owner would then approve behaviour that differs from what the code does.

Exit codes
    0  the survey ran
    2  refused -- the target, the credential or the inputs did not meet the contract
    3  an unexpected error, reported by exception class only
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.v2_capture_contract import (  # noqa: E402
    ContractViolation, SRC_ABSENT_PATH, SRC_MISSING, SRC_READABLE,
    SRC_UNREADABLE, assert_read_only_credential, classify_source,
    classify_target, looks_like_production,
)

Refused = ContractViolation

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_ERROR = 3

# Exactly the planner's selection. A V2 row has already been migrated; giving
# it an outcome would count a decision that has already been taken.
LEGACY_QUERY = {"schema_version": {"$ne": 2}}

PROJECTION = {"_id": 1, "file_path": 1, "review_status": 1, "submitted_to": 1,
              "client_id": 1, "template_type": 1, "schema_version": 1,
              "created_at": 1}


def survey(db, docs_root: Path) -> dict:
    """Classify every LEGACY document. Read-only, and it repairs nothing."""
    from app.services.document_migration import (
        BLOCK_DUPLICATE_PLAN, BLOCK_ID_COLLISION, BLOCK_NO_CLIENT,
        BLOCK_NO_TEMPLATE_TYPE, BLOCK_UNREADABLE_FILE, BLOCK_UNSUPPORTED_STATUS,
        BLOCKING_CODES, SUPPORTED_LEGACY_STATUSES, classify, is_supported_status,
        planned_revision_id)

    # V2 rows are excluded from the survey exactly as the planner excludes them,
    # and reported separately so the number is visible rather than merely absent.
    v2_documents = db["documents"].count_documents({"schema_version": 2})

    # One read instead of a find_one per document: the collision and
    # already-planned checks need the revision id map, and 13k round trips to a
    # hosted cluster is a different tool.
    revision_owner = {r["_id"]: r.get("document_id")
                      for r in db["document_revisions"].find({}, {"_id": 1,
                                                                 "document_id": 1})}

    statuses: Counter = Counter()
    outcomes: Counter = Counter()
    sources: Counter = Counter()
    approval_needed: Counter = Counter()
    condition_occurrences: Counter = Counter()
    path_flags: Counter = Counter()
    seen_plan: dict = {}
    blocked_documents = 0
    scanned = 0

    for doc in db["documents"].find(LEGACY_QUERY, PROJECTION):
        scanned += 1
        doc_id = doc["_id"]
        statuses[str(doc.get("review_status"))] += 1

        observed = classify_source(doc.get("file_path"), docs_root)
        sources[observed["source_state"]] += 1
        for flag in observed["path_flags"]:
            path_flags[flag] += 1

        # Collected in the planner's order, and evaluated the same way.
        codes: list = []
        if not doc.get("template_type"):
            codes.append(BLOCK_NO_TEMPLATE_TYPE)
        if not doc.get("client_id"):
            codes.append(BLOCK_NO_CLIENT)

        plan_id = planned_revision_id(doc_id)
        existing = revision_owner.get(plan_id, ...)
        if existing is not ... and existing != doc_id:
            codes.append(BLOCK_ID_COLLISION)
        if plan_id in seen_plan:
            codes.append(BLOCK_DUPLICATE_PLAN)
        seen_plan[plan_id] = doc_id

        if observed["source_state"] == SRC_UNREADABLE:
            codes.append(BLOCK_UNREADABLE_FILE)
        if not is_supported_status(doc.get("review_status")):
            codes.append(BLOCK_UNSUPPORTED_STATUS)

        blocking = [c for c in codes if c in BLOCKING_CODES]
        for code in blocking:
            condition_occurrences[code] += 1

        if blocking:
            # No outcome, and no owner-approval count. A blocked document has
            # not been given a fate, and counting it under a policy decision
            # would ask the owner to approve something that will not run.
            blocked_documents += 1
            continue

        outcome = classify(doc,
                           file_present=observed["source_state"] == SRC_READABLE)
        outcomes[outcome.code] += 1
        if outcome.requires_owner_approval:
            approval_needed[outcome.code] += 1

    return {
        "legacy_documents_surveyed": scanned,
        "v2_documents_excluded": v2_documents,
        "review_status": dict(statuses),
        "source_states": dict(sources),
        "path_flags": dict(path_flags),
        "outcomes": dict(outcomes),
        "requires_owner_approval": dict(approval_needed),
        "approval_affected_documents": sum(approval_needed.values()),
        # Two different questions, so two different numbers. One document with
        # three blockers is ONE blocked document and THREE occurrences.
        "blocked_documents": blocked_documents,
        "blocking_condition_occurrences": dict(condition_occurrences),
        "unblocked_documents": scanned - blocked_documents,
        "supported_legacy_statuses": sorted(
            str(s) for s in SUPPORTED_LEGACY_STATUSES),
    }


# ── credential input ─────────────────────────────────────────────────────────

def resolve_uri(args) -> tuple:
    """Get the connection string without putting it in the process arguments.

    Anything on argv is visible to every other process on the host and lands in
    shell history. That is tolerable for a throwaway local target and not for a
    production credential, so for a production target `--mongo-uri` is refused
    outright rather than merely discouraged.
    """
    supplied = [bool(args.mongo_uri), bool(args.mongo_uri_env), args.prompt_uri]
    if sum(supplied) != 1:
        raise Refused(
            "give exactly one of --mongo-uri, --mongo-uri-env or --prompt-uri")

    if args.mongo_uri:
        return args.mongo_uri, "argv"
    if args.mongo_uri_env:
        uri = os.environ.get(args.mongo_uri_env)
        if not uri:
            raise Refused(
                f"environment variable {args.mongo_uri_env!r} is unset or empty")
        return uri, f"environment ({args.mongo_uri_env})"
    uri = getpass.getpass("MongoDB connection string (input hidden): ").strip()
    if not uri:
        raise Refused("no connection string was entered")
    return uri, "hidden prompt"


def _build_parser():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mongo-uri", default=None,
                    help="connection string on the command line. REFUSED for a "
                         "production target -- argv is world-readable")
    ap.add_argument("--mongo-uri-env", default=None, metavar="VAR",
                    help="name of an environment variable holding the "
                         "connection string, e.g. V2_SURVEY_URI")
    ap.add_argument("--prompt-uri", action="store_true",
                    help="read the connection string from a hidden prompt")
    ap.add_argument("--db", required=True)
    ap.add_argument("--upload-root", required=True, type=Path,
                    help="UPLOAD_ROOT for this deployment (contains docs/)")
    ap.add_argument("--acknowledge-production-read", action="store_true",
                    help="required before this reads a production target")
    ap.add_argument("--out", type=Path, default=None,
                    help="write the counts as JSON here (aggregates only)")
    return ap


def main(argv=None, client_factory=None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        uri, source = resolve_uri(args)
        target = classify_target(uri, args.db)
        production = looks_like_production(target)

        if production and source == "argv":
            raise Refused(
                "a production connection string was passed on the command "
                "line. Process arguments are readable by other processes and "
                "are kept in shell history; use --mongo-uri-env or --prompt-uri")
        if production and not args.acknowledge_production_read:
            raise Refused(
                "this target looks like production and "
                "--acknowledge-production-read was not given. Counting the "
                "estate is a legitimate reason to read production, but it is "
                "never the default")
        docs_root = args.upload_root / "docs"
        if not docs_root.is_dir():
            raise Refused("no docs/ directory under the given --upload-root")
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    if client_factory is None:
        def client_factory(target_uri):
            from pymongo import MongoClient
            return MongoClient(target_uri, serverSelectionTimeoutMS=10000)

    client = None
    try:
        client = client_factory(uri)
        client.admin.command("ping")
        db = client[args.db]

        # The same rule the validator and the producer enforce. A survey does
        # not need write access, so it does not get to have any.
        credential = assert_read_only_credential(db)

        report = {
            "tool": "v2_estate_survey",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "database": args.db,
            "uri_source": source,
            "read_only_credential": credential,
            "is_a_dry_run": False,
            "caveat": ("counts from a live database drift while people use it. "
                       "Adequate for sizing a policy decision; NOT a migration "
                       "plan, and no substitute for a snapshot and a manifest."),
            **survey(db, docs_root),
        }
        revisions = db["document_revisions"].count_documents({})
        report["document_revisions"] = revisions
        report["document_revisions_empty"] = revisions == 0
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except Exception as exc:
        print(f"ERROR: survey failed ({type(exc).__name__}). Details are "
              "withheld: driver errors embed URIs and filesystem errors embed "
              "paths that carry document titles.", file=sys.stderr)
        return EXIT_ERROR
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    if args.out:
        try:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(report, indent=2, sort_keys=True),
                                encoding="utf-8")
        except OSError as exc:
            print(f"ERROR: could not write the report ({type(exc).__name__})",
                  file=sys.stderr)
            return EXIT_ERROR

    print(f"legacy documents surveyed {report['legacy_documents_surveyed']}")
    print(f"v2 documents excluded     {report['v2_documents_excluded']}")
    print(f"document_revisions        {report['document_revisions']}"
          f"{'  (empty)' if report['document_revisions_empty'] else '  (NOT EMPTY)'}")
    print(f"review_status             {report['review_status']}")
    print(f"source states             {report['source_states']}")
    print(f"path flags                {report['path_flags'] or 'none'}")
    print()
    print(f"blocked documents         {report['blocked_documents']}")
    print(f"  condition occurrences   {report['blocking_condition_occurrences'] or 'none'}")
    print(f"unblocked documents       {report['unblocked_documents']}")
    print(f"outcomes                  {report['outcomes']}")
    print(f"NEEDS OWNER APPROVAL      {report['requires_owner_approval'] or 'none'}")
    print(f"  affected documents      {report['approval_affected_documents']}")
    print()
    print("A COUNT, not a dry-run. It authorises nothing and produces no "
          "manifest. Blocked documents carry no outcome, exactly as the "
          "planner records none.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
