"""How long the system keeps things, and what it would delete if asked.

APPROVED PERIODS (2026-09-03)

    All user-visible data          12 months
      conversation_messages, chat_sessions, research_sessions,
      conversation_turns, LangGraph checkpoints

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

from app.db.collections import (
    get_answer_provenance_col,
    get_chat_sessions_col,
    get_conversation_messages_col,
    get_conversation_turns_col,
    get_research_sessions_col,
)
from app.services import legal_holds

logger = logging.getLogger(__name__)

DAY = 24 * 3600

# Everything a user can see in their account.
USER_DATA_SECONDS = 365 * DAY

# The accountability record, and the evidence that a piece of it is missing.
ACCOUNTABILITY_SECONDS = 7 * 365 * DAY

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
        "stores": {name: seconds // DAY for name, seconds in PERIODS.items()},
        "clock": "last activity",
        "holds": "a legal hold suspends every period above",
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
        "accountability": await _plan_accountability(moment),
        "deletion_enabled": False,
        "note": ("Dry run. Nothing was deleted and nothing in this module can "
                 "delete anything."),
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
