"""engagement_letter_reconcile.py — audit LEGACY engagement letters.

WHAT THIS IS FOR, NOW
---------------------
Engagement letters are historical data. Since AGREEMENTS_PRODUCT_PLAN.md §17
R5-3 a new engagement generates no letter, billing reads the validated
engagement (R5-5) and reviews read its status (R5-6), so no letter gates
anything. What remains is the rows written before that — including the six
orphaned letters whose engagement and case were both deleted — and this script
is how a human looks at them. It is read-only.

WHY IT EXISTED
--------------
Historical, and the reason the orphans are still here. `decline_agreement` read
`engagement_id` nowhere, so declining an engagement letter cancelled the
agreement and left the engagement `accepted` with the case assigned:

  1. Client accepts terms -> engagement `accepted`, case assigned, letter
     `pending`.
  2. Either party declines the letter -> agreement `cancelled`.
  3. The engagement stays `accepted`. The lawyer stays on the matter.
  4. The lawyer raises a fee request and `payment_service` refuses with
     "the engagement letter is still 'cancelled' -- it must be signed by both
     you and the client".

Gate 2 of the remediation plan fixed that by reversing the engagement when its
letter was declined. §17 C-A has since removed the reversal as well: a decline
now ends the LETTER and nothing else, because the engagement — not the letter —
is the hire. Both the defect and its first fix are history; the rows they left
behind are not.

NEW-FLOW ENGAGEMENTS ARE NOT ANOMALIES
--------------------------------------
An engagement carrying an `appointment_id` was created by the new flow, which
writes no letter. Having none is its NORMAL state and the census says so
(`new_flow_no_letter`, reported as OK). Only an engagement from before that —
no `appointment_id` and no letter — is the `legacy_never_generated` case the
older wording called `never_generated`. Without that split every future hire
would be listed as a defect by a tool written for the opposite situation.

CENSUS FIRST, AND IT IS THE DEFAULT
-----------------------------------
`--apply` is opt-in because reconciliation releases a case and cancels an
engagement -- both visible to two real people. The default run reads and counts
and writes nothing.

Report the census number whichever way it comes out. Zero affected rows means
the defect is real but has not been triggered in practice, which is a result
worth stating rather than a reason to say nothing.

WHAT IS NEVER TOUCHED
---------------------
An EXECUTED letter. It is a historical record of something two parties actually
agreed, and whatever later happens to the engagement does not unmake it. Only
`cancelled` and missing letters are in scope; `pending` is counted and reported
but NOT reconciled, because a pending letter may simply be awaiting a signature
that is still coming.

Usage
-----
  python scripts/engagement_letter_reconcile.py            # census, read-only
  python scripts/engagement_letter_reconcile.py --json     # census as JSON
  python scripts/engagement_letter_reconcile.py --apply    # repair `cancelled`
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.core.constants import (  # noqa: E402
    ENGAGEMENT_RETAINED_STATUSES,
    AgreementStatus,
    CaseStatus,
    EngagementStatus,
)
from app.db.collections import (  # noqa: E402
    get_agreements_col,
    get_cases_col,
    get_engagements_col,
)
from app.db.mongodb import close_db, connect_db  # noqa: E402

# Letter states that mean the engagement can never become billable. `pending`
# is deliberately absent: it is not yet a failure, only an unfinished one.
_STRANDED_LETTER_STATES = (AgreementStatus.CANCELLED.value,)


def _is_new_flow(eng: dict) -> bool:
    """True when this engagement was created by the appointment -> hire flow.

    `appointment_id` is the marker, and it is only ever written by
    `request_engagement` since §17 R5-1. A legacy row does not carry it — the
    field did not exist — so its absence is what distinguishes "this hire never
    had a letter because none is written any more" from "this hire should have
    had one and it is gone".
    """
    return isinstance(eng.get("appointment_id"), str) and bool(eng["appointment_id"])


async def census() -> dict:
    """Read-only. Retained engagements, classified by the state of their letter.

    A new-flow engagement with no letter is EXPECTED (`new_flow_no_letter`) and
    is not reported as affected; see the module docstring.
    """
    engagements = get_engagements_col()
    agreements = get_agreements_col()

    rows = await engagements.find(
        {"status": {"$in": list(ENGAGEMENT_RETAINED_STATUSES)}}
    ).to_list(length=None)

    # One $in rather than a lookup per engagement. A stranded-row census that
    # is itself an N+1 is a bad first impression of the fix.
    letter_ids = [e["agreement_id"] for e in rows if e.get("agreement_id")]
    letters = await agreements.find(
        {"_id": {"$in": letter_ids}}, {"_id": 1, "status": 1}
    ).to_list(length=None) if letter_ids else []
    status_by_id = {a["_id"]: a.get("status") for a in letters}

    buckets: Counter[str] = Counter()
    affected: list[dict] = []

    for eng in rows:
        aid = eng.get("agreement_id")
        if not aid:
            # THE SPLIT (§17 R5-3). A new-flow engagement has no letter by
            # design; a legacy one with none lost it.
            letter_state = ("new_flow_no_letter" if _is_new_flow(eng)
                            else "legacy_never_generated")
        elif aid not in status_by_id:
            # An agreement_id that resolves to nothing. Distinct from never
            # having one: it means a row was deleted out from under the
            # engagement, which is a different repair.
            letter_state = "letter_row_missing"
        else:
            letter_state = status_by_id[aid] or "unknown"

        if letter_state == AgreementStatus.EXECUTED.value:
            buckets["executed_ok"] += 1
            continue
        if letter_state == "new_flow_no_letter":
            # Correct, not a finding: a new-flow hire writes no letter. Counted
            # under its own name so the report can say so out loud.
            buckets["new_flow_no_letter"] += 1
            continue

        buckets[letter_state] += 1
        affected.append({
            "engagement_id": eng["_id"],
            "engagement_status": eng.get("status"),
            "case_id": eng.get("case_id"),
            "lawyer_id": eng.get("lawyer_id"),
            "client_id": eng.get("client_id"),
            "agreement_id": aid,
            "letter_state": letter_state,
            "reconcilable": letter_state in _STRANDED_LETTER_STATES,
        })

    return {
        "retained_engagements": len(rows),
        "retained_statuses": list(ENGAGEMENT_RETAINED_STATUSES),
        "buckets": dict(buckets),
        "affected": affected,
        "stranded": [a for a in affected if a["reconcilable"]],
        "orphans": await _orphan_letters(),
        "engagement_totals": await status_breakdown(),
        "letter_anomalies": await _letter_anomalies(),
        "downloads": await download_rates(),
    }


async def _letter_anomalies() -> list[dict]:
    """Engagements terminated with a broken letter link (gate 3A).

    WHY THIS IS HERE. `terminate_engagement` records `letter_anomaly` when it
    ends an engagement whose letter is absent, missing or superseded --
    deliberately completing the termination rather than trapping somebody in a
    representation they want out of.

    Before this function, NOTHING read that field back. It was written and never
    surfaced anywhere, which is precisely the "durable but unread" failure the
    event outbox had before it got a drainer (plan section 1.1g). A field that
    records an anomaly nobody can see is not a record, it is a comment.

    Read-only, like the rest of this script. Each row is a pointer for a human,
    not work for a machine.
    """
    rows = await get_engagements_col().find(
        {"letter_anomaly": {"$exists": True, "$ne": None}},
        {"_id": 1, "letter_anomaly": 1, "letter_anomaly_at": 1, "status": 1,
         "agreement_id": 1, "case_id": 1, "lawyer_id": 1, "terminated_at": 1},
    ).to_list(length=None)
    return [
        {"engagement_id": r["_id"], "anomaly": r["letter_anomaly"],
         "recorded_at": r.get("letter_anomaly_at"),
         "engagement_status": r.get("status"),
         "agreement_id": r.get("agreement_id"), "case_id": r.get("case_id")}
        for r in rows
    ]


async def _orphan_letters() -> list[dict]:
    """Engagement letters whose engagement no longer exists.

    THE CENSUS ABOVE CANNOT SEE THESE. It walks engagements -> agreements, so a
    letter whose engagement row was deleted is invisible to it: there is no
    engagement left to scan. The first real run of this script found six such
    letters and zero stranded engagements, which would have been reported as
    "clean" by the forward scan alone.

    This is a DIFFERENT defect from the one this script exists for. Nothing
    deletes an agreement when its engagement or case is deleted, so agreement
    rows outlive the things they describe -- including one in `executed`, which
    is a signed instrument referring to a case that no longer exists.

    Reported, never repaired. Deleting a signed agreement is not a decision a
    reconciliation script gets to make on its own, and an orphaned `pending`
    letter may still be evidence of what someone was asked to sign.
    """
    agreements = get_agreements_col()
    engagements = get_engagements_col()

    letters = await agreements.find(
        {"engagement_id": {"$ne": None}},
        {"_id": 1, "status": 1, "engagement_id": 1, "case_id": 1,
         "created_by": 1, "created_at": 1, "updated_at": 1},
    ).to_list(length=None)
    if not letters:
        return []

    live = await engagements.find(
        {"_id": {"$in": [a["engagement_id"] for a in letters]}}, {"_id": 1}
    ).to_list(length=None)
    live_ids = {e["_id"] for e in live}

    orphans = [a for a in letters if a["engagement_id"] not in live_ids]
    if not orphans:
        return []

    # The case is looked up EXPLICITLY. An earlier version of this script
    # checked only the engagement, and the run report nevertheless said "their
    # cases are gone too" -- a claim from a separate ad-hoc query that the
    # checked-in script did not make. Either the script proves it or the report
    # does not say it.
    case_ids = [a["case_id"] for a in orphans if a.get("case_id")]
    live_cases = await get_cases_col().find(
        {"_id": {"$in": case_ids}}, {"_id": 1}
    ).to_list(length=None) if case_ids else []
    live_case_ids = {c["_id"] for c in live_cases}

    return [
        {
            "agreement_id": a["_id"],
            "status": a.get("status"),
            "engagement_id": a.get("engagement_id"),
            "case_id": a.get("case_id"),
            # Explicit tri-state: a letter with no case_id at all is a
            # different record from one whose case was deleted.
            "case_exists": (
                None if not a.get("case_id") else a["case_id"] in live_case_ids
            ),
            # Classification aids: fixture residue and a real retained record
            # look identical without them.
            "created_by": a.get("created_by"),
            "created_at": a.get("created_at"),
            "updated_at": a.get("updated_at"),
        }
        for a in orphans
    ]


async def status_breakdown() -> dict:
    """Engagements by status, ALL statuses -- not just the retained ones.

    The forward census queries only `accepted`, `completed` and `terminated`, so
    its "scanned: 0" line says nothing about whether the collection is empty.
    Reporting "zero engagements of any status" off that number was a claim the
    script did not measure.
    """
    engagements = get_engagements_col()
    rows = await engagements.aggregate(
        [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    ).to_list(length=None)
    return {
        "total": sum(r["n"] for r in rows),
        "by_status": {(r["_id"] or "<unset>"): r["n"] for r in rows},
    }


async def download_rates() -> dict:
    """How many executed agreements have ever been downloaded (Gate 3E).

    READ-ONLY, like everything else in this script.

    The point is not the number. An executed agreement nobody ever opens
    is one neither party holds a copy of, which is the state the PDF gate
    exists to end -- so a low share says the feature is not reaching
    people, not that people do not want it.

    COUNTS AGREEMENTS, NOT DOWNLOADS. One party downloading eight times is
    one agreement with a copy in somebody's hands, not eight. Counting
    distinct agreement ids is what makes the percentage mean "has a copy"
    rather than "was clicked".
    """
    from app.db.collections import get_agreement_downloads_col

    agreements = get_agreements_col()
    downloads = get_agreement_downloads_col()

    executed = await agreements.count_documents({"status": "executed"})

    # Restricted to rows that really are executed: a download whose
    # agreement was later removed must not push the numerator above the
    # denominator.
    downloaded_ids = await downloads.distinct("agreement_id")
    downloaded = await agreements.count_documents(
        {"status": "executed", "_id": {"$in": downloaded_ids}}
    ) if downloaded_ids else 0

    return {
        "executed": executed,
        "downloaded": downloaded,
        "download_rows": await downloads.count_documents({}),
        "percent": round(100.0 * downloaded / executed, 1) if executed else None,
    }


# ── --apply is DISABLED until Phase 2 ────────────────────────────────────────
#
# A mutating path was drafted here and has been REMOVED rather than left behind
# a flag, because a checked-in `--apply` is a loaded gun regardless of whether
# this run used it. It did not meet the requirements the remediation plan sets
# for exactly this script:
#
#   - NOT tombstone-first. The plan requires it, following `intake_deletion.py`
#     and `document_deletion.py`.
#   - NO notifications. It cancelled a client's engagement and released their
#     case while telling neither party.
#   - NOT transactional. The engagement update and the case update were separate
#     writes, so a crash between them produced exactly the split state this
#     whole exercise exists to eliminate -- a new one, created by the repair.
#   - NO revalidation of the agreement. It trusted the census's letter state
#     rather than re-reading it under the write.
#   - A MISCOUNT: `released` was incremented on the engagement update alone, so
#     a case update that matched nothing still reported a released case.
#   - INCONSISTENT SCOPE: the module docstring said missing letters were
#     repairable, while `_STRANDED_LETTER_STATES` held only `cancelled`.
#
# Phase 2 implements repair transactionally, in the service layer, where the
# transition rule lives and can be tested. This script stays read-only until
# then: the census is the part that is finished, and it is the part that was
# needed first.

_APPLY_DISABLED = (
    "--apply is disabled.\n\n"
    "Repair must be tombstone-first, transactional, notify both parties and\n"
    "revalidate the letter state under the write. None of that is implemented\n"
    "yet; it lands with Phase 2 of AGREEMENTS_REMEDIATION_PLAN.md.\n\n"
    "This script is census-only. The census is complete and safe to re-run."
)


def _print_orphans(report: dict) -> None:
    orphans = report.get("orphans") or []
    print(f"\nORPHANED LETTERS (engagement row gone) : {len(orphans)}")
    if not orphans:
        return
    for row in orphans:
        # case_exists is a tri-state and each value is printed distinctly:
        # gone / still present / the letter never carried a case_id.
        case = ("case gone" if row["case_exists"] is False
                else "case present" if row["case_exists"] is True
                else "no case_id")
        when = row.get("created_at")
        print(f"  - agreement {row['agreement_id']} [{row['status']}] "
              f"-> engagement {row['engagement_id']} missing, {case}")
        print(f"      created_by={row.get('created_by')} created_at={when}")

    gone = sum(1 for r in orphans if r["case_exists"] is False)
    present = sum(1 for r in orphans if r["case_exists"] is True)
    print(f"\n  of which: {gone} with a deleted case, {present} with a live case")
    print("\n  A SEPARATE DEFECT from the stranded-engagement one above:")
    print("  nothing deletes an agreement when its engagement or case is")
    print("  deleted, so letters outlive what they describe. Reported, not")
    print("  repaired -- deleting a signed instrument is not this script's")
    print("  decision to make. Track as its own item.")
    print("  created_by/created_at are printed so these can be classified as")
    print("  real retained records vs historical fixture residue.")


def _print_anomalies(report: dict) -> None:
    """Surface `letter_anomaly`, which nothing else reads."""
    rows = report.get("letter_anomalies") or []
    print("")
    print(f"TERMINATION LETTER ANOMALIES : {len(rows)}")
    if not rows:
        print("  None. Every terminated engagement had a sound letter link.")
        return

    counts = Counter(r["anomaly"] for r in rows)
    for kind, n in sorted(counts.items()):
        print(f"    {kind:<20} {n}")
    for r in rows:
        print(f"  - engagement {r['engagement_id']} [{r['engagement_status']}] "
              f"{r['anomaly']}")
        print(f"      letter={r['agreement_id']} case={r['case_id']} "
              f"recorded={r['recorded_at']}")

    print("")
    print("  These terminations COMPLETED BY DESIGN. Termination is a safety")
    print("  exit and is never blocked by the agreement side -- a client who")
    print("  wants out of a representation cannot be held there because a")
    print("  letter row is missing. The anomaly is recorded so the broken link")
    print("  is discoverable rather than silent. Reported, not repaired.")


def _print_totals(report: dict) -> None:
    totals = report.get("engagement_totals") or {}
    print(f"\nEngagements in the collection, ALL statuses : {totals.get('total', 0)}")
    for status, n in sorted((totals.get("by_status") or {}).items()):
        print(f"    {status:<18} {n}")


def _print_downloads(report: dict) -> None:
    d = report.get("downloads") or {}
    print("\nExecuted agreements and signed copies (Gate 3E):")
    print(f"    executed                   {d.get('executed', 0)}")
    print(f"    downloaded at least once   {d.get('downloaded', 0)}")
    print(f"    download events recorded   {d.get('download_rows', 0)}")
    pct = d.get("percent")
    print("    share downloaded           "
          + ("n/a (nothing executed yet)" if pct is None else f"{pct}%"))
    if d.get("executed") and not d.get("downloaded"):
        print("    -- nobody holds a copy of a signed agreement. Either the")
        print("       download is not reachable, or these rows predate the")
        print("       evidence the certificate needs and are refused.")


def _print_census(report: dict) -> None:
    print("\n=== ENGAGEMENT LETTER CENSUS ===")
    print(f"Retained statuses scanned    : {', '.join(report['retained_statuses'])}")
    print(f"Retained engagements scanned : {report['retained_engagements']}")
    _print_totals(report)
    _print_downloads(report)

    if not report["retained_engagements"]:
        print("\nNo engagements in a retained status -- no lawyer is stranded")
        print("BY THIS MEASURE. Read that against the all-status count above:")
        print("if it is also zero, the forward scan had nothing to scan and")
        print("could not have found the defect even if it were occurring.")
        print("'Clean' would then mean UNEXERCISED, not verified safe.")
        _print_orphans(report)
        _print_anomalies(report)
        return

    print("\nLetter state breakdown:")
    for state, n in sorted(report["buckets"].items(), key=lambda kv: -kv[1]):
        mark = "OK " if state in ("executed_ok", "new_flow_no_letter") else "!! "
        print(f"  {mark}{state:<20} {n}")

    new_flow = report["buckets"].get("new_flow_no_letter", 0)
    if new_flow:
        print(f"\n  of which {new_flow} are NEW-FLOW engagements with no letter,")
        print("  which is their normal state since §17 R5-3 -- not a finding.")

    stranded = report["stranded"]
    print(f"\nSTRANDED (reconcilable) : {len(stranded)}")
    print(f"Affected, not reconcilable : {len(report['affected']) - len(stranded)}"
          "  (pending letters -- may still be signed)")

    for row in stranded:
        print(f"  - engagement {row['engagement_id']} "
              f"[{row['engagement_status']}] case {row['case_id']} "
              f"letter {row['letter_state']}")

    if stranded:
        print("\nEach row above is a lawyer who cannot invoice and is not told why.")
        print("Re-run with --apply to release the case and cancel the engagement.")
    else:
        print("\nNo stranded engagements. The defect is real but has not been")
        print("triggered in practice -- report this, do not omit it.")

    _print_orphans(report)
    _print_anomalies(report)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="DISABLED until Phase 2 -- see the note in this file")
    ap.add_argument("--json", action="store_true", help="emit the census as JSON")
    args = ap.parse_args()

    # Refused before the database is even opened. A disabled mutating flag
    # should not get as far as holding a connection.
    if args.apply:
        print(_APPLY_DISABLED, file=sys.stderr)
        return 2

    await connect_db()
    try:
        report = await census()
        if args.json:
            print(json.dumps({k: v for k, v in report.items() if k != "affected"},
                             indent=2, default=str))
        else:
            _print_census(report)
    finally:
        await close_db()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
