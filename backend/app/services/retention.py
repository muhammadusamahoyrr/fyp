"""How long the system keeps things, and what it would delete if asked.

APPROVED PERIODS (2026-09-03)

    All user-visible data          12 months
      conversation_messages, chat_sessions, research_sessions,
      conversation_turns, LangGraph checkpoints, intake sessions and
      their evidence uploads

    Accountability records         7 years
      answer_provenance, undelivered provenance_outbox entries,
      tombstoned conversations (session id only)

The 12-month figure is one number rather than four because a privacy policy has
to state it, and a policy that needs a table is a policy nobody reads. It is
shorter than the 24 months first proposed for messages and longer than the 90
days first proposed for turns and checkpoints; the reasoning for both is kept in
RETENTION_DESIGN.md so a future change starts from the argument.

THE CLOCK IS LAST ACTIVITY, NOT CREATION

A conversation someone still uses must never be truncated from underneath them.
`updated_at` moves with every message, so an active thread is never eligible
however old its first question is.

NOTHING HERE DELETES ANYTHING YET

`plan()` reports what WOULD go. Deletion is a separate, deliberate step, and it
is deliberately not one line away: the first observable effect of a wrong
retention number is that the data is gone.

WHY NOT A TTL INDEX — the short version; RETENTION_DESIGN.md §5 has the rest.

  * A TTL index cannot see a legal hold. It deletes on a date field with no
    conditions, so exempting a held record means keeping its date null, and the
    rule stops being a rule and becomes a side effect of another field.
  * A TTL index cannot delete across collections. Expiring a conversation means
    removing its messages AND its turns AND its checkpoint; independent TTLs
    produce a conversation whose messages are gone but whose turn records still
    replay the answers.
  * A TTL index cannot be dry-run.

TTLs remain right for `ws_tickets` and `refresh_blocklist`, which have no holds
and no cross-collection story. Those already have them.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.constants import TERMINAL_CASE_STATUSES, CaseStatus
from app.db.collections import (
    get_answer_provenance_col,
    get_cases_col,
    get_chat_sessions_col,
    get_conversation_messages_col,
    get_conversation_turns_col,
    get_intakes_col,
    get_research_sessions_col,
)
from app.services import legal_holds

logger = logging.getLogger(__name__)

DAY = 24 * 3600

# Everything a user can see in their account.
USER_DATA_SECONDS = 365 * DAY

# The accountability record, and the evidence that a piece of it is missing.
ACCOUNTABILITY_SECONDS = 7 * 365 * DAY

# A closed matter, and the intake evidence behind it.
#
# INDEPENDENT ON PURPOSE. It equals no other period here and must not be
# expressed in terms of one: this is the only figure chosen against a limitation
# period rather than against a privacy promise, and aliasing it would mean a
# future change to accountability silently moving case evidence with it.
#
# Twelve years covers the Limitation Act 1908's twelve-year window for executing
# a decree, which is the longest thing that can still be asked of a closed case.
#
# NOTE THE ASYMMETRY THIS CREATES: it outlives ACCOUNTABILITY_SECONDS by five
# years, so between years seven and twelve a case keeps its evidence while the
# provenance record of the advice given on it has expired.
CASE_DATA_SECONDS = 12 * 365 * DAY

# One sweep may not remove more than this. A mistake is then a small mistake,
# and a runaway is visible in the report before it is visible in the data.
MAX_PER_RUN = 500

PERIODS: dict[str, int] = {
    "conversation_messages": USER_DATA_SECONDS,
    "conversation_turns":    USER_DATA_SECONDS,
    "chat_sessions":         USER_DATA_SECONDS,
    "research_sessions":     USER_DATA_SECONDS,
    "langgraph_checkpoints": USER_DATA_SECONDS,
    "answer_provenance":     ACCOUNTABILITY_SECONDS,
    "provenance_outbox":     ACCOUNTABILITY_SECONDS,
    "tombstones":            ACCOUNTABILITY_SECONDS,
    # An intake NEVER BOUND TO A CASE is user-visible case-preparation data and
    # follows the approved 12-month inactivity period. Once it has a case, this
    # period stops applying to it — see `cases` below.
    "intakes":               USER_DATA_SECONDS,
    # A closed case, and with it the converted intake evidence behind it.
    # Eligibility is `closed_at`, not `updated_at`: a dormant but OPEN case is
    # still live, and an inactivity clock would expire a matter nobody finished.
    "cases":                 CASE_DATA_SECONDS,
    # ── DOCUMENTS_V2 stores (report-only this release; no sweep wired yet) ────
    # A generated revision carries the user's document content → user-data
    # period. A review event is an accountability record of who decided what →
    # accountability period, matching answer_provenance. These register the
    # periods so retention.describe()/plan() can account for them; the actual
    # deletion path ships behind a separate, independently approved switch.
    "document_revisions":    USER_DATA_SECONDS,
    "review_events":         ACCOUNTABILITY_SECONDS,
    "deletion_tombstones":   ACCOUNTABILITY_SECONDS,
}


# WHAT EACH PERIOD COUNTS FROM.
#
# There used to be one clock and one sentence describing it. Cases broke that:
# everywhere else the clock is last activity, because data someone still uses
# must never be truncated from underneath them — but an OPEN case can be dormant
# for years and still be live, so an inactivity clock would destroy the evidence
# behind a matter nobody had finished.
#
# Stated per store rather than in prose, so the policy page cannot describe one
# rule while the sweep enforces another. Every key in PERIODS must appear here.
CLOCKS: dict[str, str] = {
    "conversation_messages": "last activity",
    "conversation_turns":    "last activity",
    "chat_sessions":         "last activity",
    "research_sessions":     "last activity",
    "langgraph_checkpoints": "last activity",
    "answer_provenance":     "record creation",
    "provenance_outbox":     "record creation",
    "tombstones":            "record creation",
    "intakes":               "last activity",
    "cases":                 "case closure (closed_at); never while open",
    "document_revisions":    "record creation",
    "review_events":         "record creation",
    "deletion_tombstones":   "record creation",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def cutoff(store: str, now: Optional[datetime] = None) -> datetime:
    """Anything untouched since this instant is eligible, absent a hold."""
    seconds = PERIODS.get(store)
    if seconds is None:
        raise KeyError(f"no retention period defined for {store!r}")
    return (now or _now()) - timedelta(seconds=seconds)


def describe() -> dict[str, Any]:
    """The policy, as an operator or a privacy page would state it."""
    return {
        "user_data_days": USER_DATA_SECONDS // DAY,
        "accountability_days": ACCOUNTABILITY_SECONDS // DAY,
        "case_data_days": CASE_DATA_SECONDS // DAY,
        "stores": {name: seconds // DAY for name, seconds in PERIODS.items()},
        # Per store. There is no single clock any more, and a summary that
        # claimed one would be describing a rule nothing enforces.
        "clocks": {name: CLOCKS.get(name, "unspecified") for name in PERIODS},
        "holds": "a legal hold suspends every period above",
        # This module still deletes nothing. Intake/case deletion lives in
        # services/intake_deletion behind its own switch, and reports its own
        # state; V2 revisions likewise. Kept false here so the guarantee this
        # module makes about ITSELF stays readable and testable.
        "deletion_enabled": False,
    }


# ── the dry run ─────────────────────────────────────────────────────────────

async def plan(now: Optional[datetime] = None) -> dict:
    """What a sweep WOULD remove, and what a hold is protecting.

    Reports COUNTS ONLY — no session ids, no user ids, no content. A retention
    report is read on a dashboard and pasted into tickets, and the one thing it
    must not become is a listing of whose data is about to expire.

    Runs no deletions. `deletion_enabled` is false everywhere and there is no
    flag here that changes that; turning deletion on is a code change made
    deliberately, after a report over real data has been read.
    """
    moment = now or _now()
    held = await legal_holds.active()

    conversations = await _plan_conversations(moment, held)
    return {
        "generated_at": moment,
        "policy": describe(),
        "active_holds": {"users": len(held.get(legal_holds.SCOPE_USER, ())),
                         "cases": len(held.get(legal_holds.SCOPE_CASE, ()))},
        "conversations": conversations,
        "intakes": await _plan_intakes(moment, held),
        "cases": await _plan_cases(moment, held),
        "accountability": await _plan_accountability(moment),
        "deletion_enabled": False,
        "note": ("Dry run. Nothing was deleted and nothing in this module can "
                 "delete anything."),
    }


async def _plan_intakes(moment: datetime, held: dict) -> dict:
    """Expired UNCONVERTED intakes and their evidence files; never deleted here.

    Only intakes with no case. Once an intake is bound to a case the case's own
    period governs it — reporting it here too would double-count it and, worse,
    would describe converted evidence as expiring on the 365-day clock when it
    does not.

    UNCONVERTED is "no case id", not "not completed". `attach_case` writes the
    case id before the analysis finishes, so a half-converted intake already has
    one and belongs to the case.
    """
    eligible = protected = evidence_files = 0
    limit = MAX_PER_RUN * 4
    query = {
        "case_id": {"$not": {"$type": "string"}},
        "updated_at": {"$type": "date", "$lt": cutoff("intakes", moment)},
    }
    projection = {"client_id": 1, "case_id": 1, "evidence_files.file_id": 1}
    async for row in get_intakes_col().find(query, projection).limit(limit):
        if legal_holds.covers(
            held, owner_id=row.get("client_id"), case_id=row.get("case_id")
        ):
            protected += 1
            continue
        eligible += 1
        evidence_files += len(row.get("evidence_files") or [])
    return {
        "intakes_eligible": eligible,
        "intakes_held": protected,
        "evidence_files_that_would_go": evidence_files,
        "capped_at": limit if eligible + protected >= limit else None,
        "scope": "unconverted only — converted intakes follow their case",
        "deletion_implemented": False,
    }


async def _plan_cases(moment: datetime, held: dict) -> dict:
    """Closed cases past the case period, and abandoned drafts.

    Counts the intake evidence that would go WITH them, because that is the
    consequence an operator is actually reading this report to understand: the
    case row is not touched by the current deletion stage, its intake is.

    Cases with no recorded closure are reported separately rather than omitted.
    They are protected — and an operator seeing a large number here is seeing
    the backfill that has not happened yet, not a policy that is working.
    """
    limit = MAX_PER_RUN * 4
    col = get_cases_col()
    terminal = sorted(TERMINAL_CASE_STATUSES)

    async def _walk(query: dict) -> tuple[int, int, int]:
        ok = protected_ = files = 0
        projection = {"client_id": 1, "intake_id": 1}
        async for row in col.find(query, projection).limit(limit):
            if legal_holds.covers(held, owner_id=row.get("client_id"),
                                  case_id=row.get("_id")):
                protected_ += 1
                continue
            ok += 1
            intake_id = row.get("intake_id")
            if intake_id:
                intake = await get_intakes_col().find_one(
                    {"_id": intake_id}, {"evidence_files.file_id": 1})
                files += len((intake or {}).get("evidence_files") or [])
        return ok, protected_, files

    closed_ok, closed_held, closed_files = await _walk({
        "status": {"$in": terminal},
        "closed_at": {"$type": "date", "$lt": cutoff("cases", moment)},
    })
    draft_ok, draft_held, draft_files = await _walk({
        "status": CaseStatus.DRAFT.value,
        "created_at": {"$type": "date",
                       "$lt": moment - timedelta(seconds=USER_DATA_SECONDS)},
    })

    unknown_closure = await col.count_documents(
        {"status": {"$in": terminal}, "closed_at": {"$not": {"$type": "date"}}})

    return {
        "closed_cases": {
            "cases_eligible": closed_ok,
            "cases_held": closed_held,
            "evidence_files_that_would_go": closed_files,
        },
        "abandoned_drafts": {
            "cases_eligible": draft_ok,
            "cases_held": draft_held,
            "evidence_files_that_would_go": draft_files,
        },
        "terminal_without_closed_at": unknown_closure,
        "note": ("A case with no recorded closure is never eligible. No "
                 "historical closure date is guessed."),
        "deletion_implemented": False,
    }


async def _plan_conversations(moment: datetime, held: dict) -> dict:
    """Conversations past their period, split by whether a hold protects them.

    Walked rather than counted, because eligibility depends on a hold and a
    hold is not a field on the row. The walk is bounded by `MAX_PER_RUN * 4` so
    a report can never become the most expensive query in the system — it is
    diagnostics, and a diagnostic that needs its own capacity plan is a
    liability.
    """
    surfaces = (
        ("chat_sessions", get_chat_sessions_col(), "client_id"),
        ("research_sessions", get_research_sessions_col(), "owner_id"),
    )
    limit = MAX_PER_RUN * 4
    summary: dict[str, Any] = {}

    for name, col, owner_field in surfaces:
        eligible = protected = 0
        messages = turns = 0
        query = {"updated_at": {"$lt": cutoff(name, moment)},
                 "deleted_at": None}
        async for row in col.find(query, {owner_field: 1, "case_id": 1,
                                          "session_id": 1}).limit(limit):
            if legal_holds.covers(held, owner_id=row.get(owner_field),
                                  case_id=row.get("case_id")):
                protected += 1
                continue
            eligible += 1
            key = f"{'client' if name == 'chat_sessions' else 'research'}:{row['_id']}"
            messages += await get_conversation_messages_col().count_documents(
                {"conversation_id": key})
            turns += await get_conversation_turns_col().count_documents(
                {"conversation_id": key})

        summary[name] = {
            "conversations_eligible": eligible,
            "conversations_held": protected,
            "messages_that_would_go": messages,
            "turn_records_that_would_go": turns,
            "capped_at": limit if eligible + protected >= limit else None,
        }
    return summary


async def _plan_accountability(moment: datetime) -> dict:
    """Provenance and undelivered outbox entries past seven years.

    Counted rather than walked: nothing here is protected by a hold in a way
    that changes the count — a hold suspends deletion, and deletion of these is
    not implemented at all.
    """
    from app.services.provenance_outbox import (
        STATUS_FAILED,
        get_provenance_outbox_col,
    )

    return {
        "answer_provenance": {
            "records_past_period": await get_answer_provenance_col()
            .count_documents({"created_at": {"$lt": cutoff("answer_provenance", moment)}}),
        },
        "provenance_outbox_failed": {
            "records_past_period": await get_provenance_outbox_col()
            .count_documents({"status": STATUS_FAILED,
                              "created_at": {"$lt": cutoff("provenance_outbox", moment)}}),
        },
    }
