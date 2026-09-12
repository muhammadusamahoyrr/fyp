"""Which past intakes MIGHT have been analysed from partially-read evidence?

WHY THIS EXISTS

Milestone 1 fixes the future. It says nothing about cases already decided on a
bundle whose scanned pages reached the analysis as nothing, recorded as
`readable`. For a legal product that is the more uncomfortable half of the
defect, and it is not answerable by guessing: it needs counting.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------

*   It does not connect to anything by itself. There is no default URI and it
    does not import `app.core.config`, so it cannot pick up production
    credentials by accident. You pass a connection explicitly, or you pass an
    exported JSON file and it touches no database at all.
*   It never writes. No updates, no re-extraction, no notifications.
*   **It reports CANDIDATES, not harm.** Whether a given case was actually
    damaged cannot be known from the stored record: the old extractor did not
    record page counts, so "this intake had a PDF and produced some text" is the
    strongest statement available. Confirming harm would mean re-extracting the
    stored files, which is a separate decision that belongs to the owner.
*   It emits no document text, no filenames and no client identifiers beyond the
    ids needed to find a record again.

WHAT COUNTS AS A CANDIDATE
--------------------------

`unknown_legacy`
    Evidence attached, and NO extraction record at all. These pre-date the
    record being kept, so nothing about them can be ruled in or out. This is
    expected to be the largest group and it is the most uncertain one.

`recorded_readable`
    An extraction record exists and says `readable`, produced by the OLD
    extractor — which called a document readable if any text came out of it.
    Every partially-read bundle in the corpus is in here, and so is every
    genuinely complete one, and the record cannot tell them apart.

`recorded_incomplete`
    Already recorded as partially read or worse. Only the new extractor writes
    these, so they are listed for completeness rather than as a concern.

Usage:

    python -m scripts.evidence_extraction_census --from-json export.json
    python -m scripts.evidence_extraction_census \\
        --mongo-uri "mongodb://..." --database attorney_ai --i-understand-read-only
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

#: Statuses the NEW extractor writes when it saw less than the whole document.
_INCOMPLETE_STATUSES = {
    "partially_read", "unreadable", "missing", "omitted_limit", "invalid_path",
}

#: Extensions whose extraction could silently under-read. Images were always
#: refused outright and `.txt` has no pages, so neither can hide a partial read.
_AT_RISK_SUFFIXES = (".pdf", ".docx")

CATEGORY_UNKNOWN_LEGACY = "unknown_legacy"
CATEGORY_RECORDED_READABLE = "recorded_readable"
CATEGORY_RECORDED_INCOMPLETE = "recorded_incomplete"
CATEGORY_NO_AT_RISK_EVIDENCE = "no_at_risk_evidence"


def _at_risk(files: list[dict] | None) -> int:
    count = 0
    for meta in files or []:
        name = str(meta.get("filename") or "")
        content_type = str(meta.get("content_type") or "")
        if name.lower().endswith(_AT_RISK_SUFFIXES) or content_type in (
                "application/pdf",
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"):
            count += 1
    return count


def classify(intake: dict) -> dict:
    """Categorise ONE intake. Pure, so it can be tested without a database."""
    files = intake.get("evidence_files") or []
    at_risk = _at_risk(files)

    analysis = intake.get("ai_structured_case") or {}
    records = analysis.get("evidence_extraction")

    if not at_risk:
        category = CATEGORY_NO_AT_RISK_EVIDENCE
    elif not records:
        # Either it pre-dates the record, or conversion never ran. Both are
        # unknown, and unknown is not the same as fine.
        category = CATEGORY_UNKNOWN_LEGACY
    elif any(str(r.get("status")) in _INCOMPLETE_STATUSES for r in records):
        category = CATEGORY_RECORDED_INCOMPLETE
    elif any("pages_total" in r for r in records):
        # Written by the new extractor, which only says `readable` when it
        # judged the whole document read.
        category = CATEGORY_RECORDED_INCOMPLETE if any(
            r.get("completeness") not in (None, "complete") for r in records
        ) else CATEGORY_NO_AT_RISK_EVIDENCE
    else:
        category = CATEGORY_RECORDED_READABLE

    return {
        "intake_id": str(intake.get("_id") or ""),
        "case_id": str(intake.get("case_id") or "") or None,
        "category": category,
        "at_risk_files": at_risk,
        "total_files": len(files),
        "has_extraction_record": bool(records),
    }


def summarise(rows: list[dict]) -> dict:
    counts = Counter(r["category"] for r in rows)
    candidates = [
        r for r in rows
        if r["category"] in (CATEGORY_UNKNOWN_LEGACY, CATEGORY_RECORDED_READABLE)
    ]
    return {
        "schema": "evidence_extraction_census/1",
        "intakes_examined": len(rows),
        "counts_by_category": dict(counts),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "uncertainty": (
            "These are CANDIDATES, not confirmed harm. The previous extractor "
            "recorded no page counts, so a stored `readable` cannot be "
            "distinguished from a document that was read down to its cover "
            "sheet. Confirming any individual case requires re-extracting its "
            "stored files, which this tool does not do."
        ),
        "not_examined": (
            "Intakes whose evidence was deleted, and any case created outside "
            "the intake flow, are invisible to this census."
        ),
    }


def _load_json(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        data = data.get("intakes") or []
    return [row for row in data if isinstance(row, dict)]


def _load_mongo(uri: str, database: str, limit: int) -> list[dict]:
    """Read-only query. Projection excludes every text-bearing field."""
    from pymongo import MongoClient

    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        collection = client[database]["intakes"]
        cursor = collection.find(
            {"evidence_files.0": {"$exists": True}},
            {
                "_id": 1,
                "case_id": 1,
                "evidence_files.filename": 1,
                "evidence_files.content_type": 1,
                "ai_structured_case.evidence_extraction": 1,
            },
        ).limit(limit)
        return list(cursor)
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-json", help="an exported intake dump; touches no database")
    source.add_argument("--mongo-uri", help="explicit connection string; there is no default")
    parser.add_argument("--database", help="database name (required with --mongo-uri)")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--out", help="write the report here instead of stdout")
    parser.add_argument(
        "--i-understand-read-only", action="store_true",
        help="required with --mongo-uri: acknowledges this opens a connection")
    args = parser.parse_args(argv)

    if args.mongo_uri:
        if not args.database:
            parser.error("--database is required with --mongo-uri")
        if not args.i_understand_read_only:
            parser.error(
                "--i-understand-read-only is required with --mongo-uri. This "
                "tool only ever reads, but connecting at all is a deliberate act.")
        rows = _load_mongo(args.mongo_uri, args.database, args.limit)
    else:
        rows = _load_json(args.from_json)

    report = summarise([classify(row) for row in rows])
    rendered = json.dumps(report, indent=2, sort_keys=True)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(rendered)
        print(f"wrote {args.out}: {report['candidate_count']} candidate(s) "
              f"of {report['intakes_examined']} intake(s) examined")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
