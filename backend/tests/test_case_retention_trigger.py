"""`closed_at` — the instant a matter ended, and the only clock case data expires on.

APPROVED POLICY (Gate 1, resolution #1)

    Unconverted intake + evidence      365 days from `intakes.updated_at`
    Converted intake + evidence         12 years from `cases.closed_at`
    Unconfirmed draft case              365 days from `cases.created_at`

This file covers STAGE 1 ONLY: the lifecycle of the stamp itself. Nothing here
deletes anything, and no deletion machinery exists yet.

WHY NOT `updated_at`, WHICH THE REST OF RETENTION USES

Everywhere else the clock is last activity, because a conversation somebody
still uses must never be truncated from underneath them. Cases invert that. An
OPEN case can sit dormant for years and still be live — a suit waiting on a
cause list is not an abandoned one — so an inactivity clock would delete the
evidence for a matter nobody had finished. `closed_at` only starts once the
matter is genuinely over.

THE PROPERTIES THAT FAIL SILENTLY

  * NULL IS NOT ZERO. A case with no recorded closure is protected for ever,
    not eligible immediately. Every case closed before this field existed has
    no value at all, and none of them may be selected.

    What actually provides that is MongoDB's TYPE BRACKETING: `$lt` against a
    Date operand compares only against Dates, so a missing or null field does
    not match. This was verified by mutation rather than assumed — removing the
    `$type: "date"` clause below changes no result here, so that clause is
    explicitness, not the mechanism. The mechanism is the database's, which is
    precisely why these tests run against a real one.
  * A REOPENED CASE MUST LOSE ITS STAMP. Otherwise it keeps counting down
    while somebody is working it, and expires mid-matter.
  * RE-LABELLING IS NOT RE-CLOSING. closed → dismissed must not restart a
    twelve-year clock, or a status toggle silently extends retention.

Integration, because "which cases would be selected" is a claim about database
semantics — specifically about how a query treats a field that is not there —
and a mocked repository would happily agree with whatever Python thought.
"""
from __future__ import annotations

import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from support.hire_fixtures import (  # noqa: E402
    delete_appointments_for, seed_completed_appointment,
)

from app.core.constants import TERMINAL_CASE_STATUSES, CaseStatus  # noqa: E402
from app.core.exceptions import AppValidationError  # noqa: E402
from app.services import admin_service, engagement_service  # noqa: E402

pytestmark = pytest.mark.integration


ADMIN = {"_id": "ret-trigger-admin", "role": "admin", "email": "a@test.invalid"}

# The approved periods, restated here because stage 1 must not touch
# retention.py. Stage 2 introduces CASE_DATA_SECONDS / USER_DATA_SECONDS and
# MUST match these; the assertion that they agree belongs in that stage.
CASE_DATA_DAYS = 12 * 365
DRAFT_FALLBACK_DAYS = 365


# ── the selectors under test ────────────────────────────────────────────────
#
# Stage 2's `find_expired_closed` / `find_abandoned_drafts` must reuse these
# exactly. They are written here first because the safety of the whole policy
# is a property of the QUERY, not of the calling code — what is or is not
# selected is what stands between "we kept it" and "it is gone".
#
# `$type: "date"` is deliberate redundancy. MongoDB's type bracketing already
# refuses a missing or null field against a Date operand (proven by mutation:
# dropping this clause changes nothing). It is kept so the intent survives a
# future edit that passes a non-Date cutoff, where bracketing would silently
# stop protecting anything.

def _expired_closed(now: datetime) -> dict:
    return {
        "status": {"$in": sorted(TERMINAL_CASE_STATUSES)},
        "closed_at": {"$type": "date",
                      "$lt": now - timedelta(days=CASE_DATA_DAYS)},
    }


def _abandoned_drafts(now: datetime) -> dict:
    return {
        "status": CaseStatus.DRAFT.value,
        "created_at": {"$lt": now - timedelta(days=DRAFT_FALLBACK_DAYS)},
    }


def _cases_col():
    from app.db.collections import get_cases_col
    return get_cases_col()


async def _selected(selector: dict) -> set[str]:
    return {row["_id"] async for row in _cases_col().find(selector, {"_id": 1})}


@pytest.fixture
async def tag(app_indexes):
    """A unique id prefix, with every case it created removed afterwards."""
    t = f"RT-{secrets.token_hex(4)}"
    yield t
    await _cases_col().delete_many({"_id": {"$regex": f"^{t}"}})


async def _case(tag: str, name: str, **fields) -> str:
    """One stored case. `fields` overrides any column, including absent ones."""
    now = datetime.now(timezone.utc)
    case_id = f"{tag}-{name}"
    doc = {
        "_id": case_id,
        "client_id": f"{tag}-client",
        "lawyer_id": None,
        "case_number": f"ATT-2026-{name.upper()}",
        "case_type": "civil",
        "province": "punjab",
        "status": CaseStatus.OPEN.value,
        "title": "A tenancy arrears claim",
        "description": "Arrears since March.",
        "milestones": [],
        "hearing_dates": [],
        "created_at": now,
        "updated_at": now,
    }
    doc.update(fields)
    await _cases_col().insert_one(doc)
    return case_id


async def _stored(case_id: str) -> dict:
    return await _cases_col().find_one({"_id": case_id})


@pytest.fixture(autouse=True)
def _no_embed(monkeypatch):
    """Accepting terms schedules a lawyer re-embed; not this file's subject."""
    try:
        from app.ai import lawyer_embeddings
        monkeypatch.setattr(lawyer_embeddings, "schedule_embed", lambda _id: False)
    except Exception:  # noqa: BLE001 — the guard is the point
        pass


@pytest.fixture
async def engagement_parties(app_indexes):
    """A client, a verified lawyer and an open case, for the completion path.

    Separate from `tag` because the engagement flow needs real users and real
    indexes; the stamp is asserted through the flow that closes most cases
    rather than by writing the status directly.
    """
    from app.db.collections import (
        get_agreements_col,
        get_cases_col,
        get_engagements_col,
        get_users_col,
    )

    t = secrets.token_hex(4)
    client_id, lawyer_id, case_id = f"RTE-C-{t}", f"RTE-L-{t}", f"RTE-CASE-{t}"
    now = datetime.now(timezone.utc)

    await get_users_col().insert_many([
        {"_id": client_id, "role": "client", "is_active": True,
         "email": f"rte-c-{t}@test.invalid", "full_name": "Client Retain",
         "province": "punjab", "created_at": now},
        {"_id": lawyer_id, "role": "lawyer", "is_active": True,
         "email": f"rte-l-{t}@test.invalid", "full_name": "Adv Retain",
         "province": "punjab", "created_at": now,
         "lawyer_profile": {"specializations": ["civil"], "kyc_verified": True,
                            "rating": 4.0, "total_reviews": 3,
                            "availability": True, "experience_years": 6}},
    ])
    await get_cases_col().insert_one({
        "_id": case_id, "client_id": client_id, "lawyer_id": None,
        "case_number": f"ATT-2026-{t.upper()}", "case_type": "civil",
        "province": "punjab", "status": CaseStatus.OPEN.value,
        "title": "A tenancy arrears claim", "description": "Arrears since March.",
        "milestones": [], "hearing_dates": [],
        "created_at": now, "updated_at": now,
    })

    yield {"client_id": client_id, "lawyer_id": lawyer_id, "case_id": case_id}

    await get_users_col().delete_many({"_id": {"$in": [client_id, lawyer_id]}})
    await get_cases_col().delete_many({"_id": case_id})
    await get_engagements_col().delete_many({"case_id": case_id})
    await get_agreements_col().delete_many({"case_id": case_id})
    await delete_appointments_for(client_id)


# ══════════════════════════════════════════════════════════════════════════════
# Both chokepoints stamp the closure instant
# ══════════════════════════════════════════════════════════════════════════════

async def test_an_admin_closing_a_case_stamps_the_closure_instant(tag):
    case_id = await _case(tag, "admin-close")
    before = datetime.now(timezone.utc)

    await admin_service.update_case_status(case_id, CaseStatus.CLOSED.value, ADMIN)

    stored = await _stored(case_id)
    assert stored["status"] == CaseStatus.CLOSED.value
    closed_at = stored["closed_at"]
    assert closed_at is not None, "the matter ended and nothing recorded when"
    assert closed_at.replace(tzinfo=timezone.utc) >= before - timedelta(seconds=5)


async def test_dismissing_a_case_stamps_it_too(tag):
    """`dismissed` is as terminal as `closed`. A dismissed matter that never
    stamped would be protected for ever — the safe failure, but still wrong."""
    case_id = await _case(tag, "admin-dismiss")

    await admin_service.update_case_status(case_id, CaseStatus.DISMISSED.value, ADMIN)

    assert (await _stored(case_id))["closed_at"] is not None


async def test_completing_an_engagement_stamps_the_closure_instant(engagement_parties):
    """The second chokepoint, driven through the real two-step flow rather than
    by writing the status directly — the stamp has to survive the path that
    actually closes most cases."""
    p = engagement_parties
    appt_id = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    eid = await engagement_service.request_engagement(
        p["client_id"], {"case_id": p["case_id"], "lawyer_id": p["lawyer_id"],
                         "appointment_id": appt_id,
                         "message": "Please take this."})
    eid = eid["id"]
    await engagement_service.propose_terms(
        eid, p["lawyer_id"],
        {"fee_amount": 75000, "fee_type": "fixed", "scope_note": "Trial court only."})
    await engagement_service.accept_terms(eid, p["client_id"])

    before = datetime.now(timezone.utc)
    await engagement_service.complete_engagement(eid, p["lawyer_id"], note="Done.")
    await engagement_service.complete_engagement(eid, p["client_id"])

    stored = await _stored(p["case_id"])
    assert stored["status"] == CaseStatus.CLOSED.value
    assert stored["closed_at"] is not None
    assert stored["closed_at"].replace(tzinfo=timezone.utc) >= before - timedelta(seconds=5)


async def test_a_completed_engagement_cannot_also_be_terminated(engagement_parties):
    """The reachability argument that lets the completion path stamp
    UNCONDITIONALLY, pinned as a test.

    `terminate_engagement` releases the case back to `open` with no status
    guard. That is only safe because it cannot run after completion — it
    requires ACCEPTED and completion sets COMPLETED. If this ever starts
    passing, a terminated-after-completion case goes live carrying a stale
    `closed_at`, and the completion path needs the same clearing logic the
    admin path has.
    """
    p = engagement_parties
    appt_id = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    eng = await engagement_service.request_engagement(
        p["client_id"], {"case_id": p["case_id"], "lawyer_id": p["lawyer_id"],
                         "appointment_id": appt_id,
                         "message": "Please take this."})
    eid = eng["id"]
    await engagement_service.propose_terms(
        eid, p["lawyer_id"],
        {"fee_amount": 75000, "fee_type": "fixed", "scope_note": "Trial court only."})
    await engagement_service.accept_terms(eid, p["client_id"])
    await engagement_service.complete_engagement(eid, p["lawyer_id"], note="Done.")
    await engagement_service.complete_engagement(eid, p["client_id"])

    with pytest.raises(AppValidationError):
        await engagement_service.terminate_engagement(
            eid, p["client_id"], "changed my mind")


# ══════════════════════════════════════════════════════════════════════════════
# Reopening clears it
# ══════════════════════════════════════════════════════════════════════════════

async def test_reopening_a_closed_case_clears_the_stamp(tag):
    """The sharpest edge in the change. A reopened case that kept its stamp
    would keep counting down while somebody was actively working it."""
    case_id = await _case(tag, "reopen")
    await admin_service.update_case_status(case_id, CaseStatus.CLOSED.value, ADMIN)
    assert (await _stored(case_id))["closed_at"] is not None

    await admin_service.update_case_status(case_id, CaseStatus.OPEN.value, ADMIN)

    stored = await _stored(case_id)
    assert stored["status"] == CaseStatus.OPEN.value
    assert stored["closed_at"] is None


async def test_a_reopened_case_is_not_selected_even_though_it_was_once_closed(tag):
    """The clearing has to be visible to the SELECTOR, not just to the field.
    Closed long ago, reopened today: it is live, and no age can select it."""
    case_id = await _case(tag, "reopen-aged")
    await admin_service.update_case_status(case_id, CaseStatus.CLOSED.value, ADMIN)
    await _cases_col().update_one(
        {"_id": case_id},
        {"$set": {"closed_at": datetime.now(timezone.utc)
                  - timedelta(days=CASE_DATA_DAYS + 400)}})
    await admin_service.update_case_status(case_id, CaseStatus.OPEN.value, ADMIN)

    assert case_id not in await _selected(_expired_closed(datetime.now(timezone.utc)))


async def test_relabelling_one_terminal_status_as_another_keeps_the_first_instant(tag):
    """closed → dismissed is neither entering nor leaving. The matter ended
    once; re-stamping would let a status toggle restart a twelve-year clock."""
    case_id = await _case(tag, "relabel")
    await admin_service.update_case_status(case_id, CaseStatus.CLOSED.value, ADMIN)
    original = (await _stored(case_id))["closed_at"]

    await admin_service.update_case_status(case_id, CaseStatus.DISMISSED.value, ADMIN)

    stored = await _stored(case_id)
    assert stored["status"] == CaseStatus.DISMISSED.value
    assert stored["closed_at"] == original


# ══════════════════════════════════════════════════════════════════════════════
# Null is never eligible
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_case_closed_before_this_field_existed_is_never_eligible(tag):
    """THE PROPERTY THE WHOLE BACKFILL RULE RESTS ON.

    Every case already closed carries no `closed_at` at all. `{"$lt": cutoff}`
    against a missing field must not match, and in MongoDB that is a fact about
    `$type`, not about the comparison — which is exactly why this is asserted
    against a real database rather than reasoned about.
    """
    ancient = datetime.now(timezone.utc) - timedelta(days=CASE_DATA_DAYS + 5000)
    legacy = await _case(tag, "legacy", status=CaseStatus.CLOSED.value,
                         created_at=ancient, updated_at=ancient)
    assert "closed_at" not in await _stored(legacy)

    assert legacy not in await _selected(_expired_closed(datetime.now(timezone.utc)))


async def test_an_explicitly_null_closure_instant_is_never_eligible(tag):
    """A cleared stamp (reopened, then closed again by some future path that
    forgot to re-stamp) is null rather than missing. Both mean 'we do not know
    when', and both must be protected."""
    ancient = datetime.now(timezone.utc) - timedelta(days=CASE_DATA_DAYS + 5000)
    case_id = await _case(tag, "null-stamp", status=CaseStatus.CLOSED.value,
                          closed_at=None, created_at=ancient, updated_at=ancient)

    assert case_id not in await _selected(_expired_closed(datetime.now(timezone.utc)))


async def test_a_genuinely_expired_closed_case_IS_selected(tag):
    """The counterweight. Without this every test above would pass on a
    selector that simply never matches anything."""
    case_id = await _case(
        tag, "expired", status=CaseStatus.CLOSED.value,
        closed_at=datetime.now(timezone.utc) - timedelta(days=CASE_DATA_DAYS + 1))

    assert case_id in await _selected(_expired_closed(datetime.now(timezone.utc)))


async def test_a_case_closed_one_day_short_of_the_period_is_not_selected(tag):
    """The boundary is where the policy says it is."""
    case_id = await _case(
        tag, "not-yet", status=CaseStatus.CLOSED.value,
        closed_at=datetime.now(timezone.utc) - timedelta(days=CASE_DATA_DAYS - 1))

    assert case_id not in await _selected(_expired_closed(datetime.now(timezone.utc)))


# ══════════════════════════════════════════════════════════════════════════════
# A live case is never eligible, at any age
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("status", [
    CaseStatus.OPEN.value,
    CaseStatus.IN_PROGRESS.value,
    CaseStatus.PENDING_LAWYER.value,
])
async def test_a_live_case_is_never_eligible_however_old(tag, status):
    """Fifty years dormant and still live. This is the case the inactivity
    clock would have destroyed."""
    ancient = datetime.now(timezone.utc) - timedelta(days=365 * 50)
    case_id = await _case(tag, f"live-{status}", status=status,
                          created_at=ancient, updated_at=ancient)

    assert case_id not in await _selected(_expired_closed(datetime.now(timezone.utc)))


async def test_a_live_case_is_not_selected_even_if_it_carries_a_stale_stamp(tag):
    """Belt and braces. If some future path ever leaves a stamp on a live case,
    the STATUS clause still refuses it — the two conditions are independent so
    that one bug cannot delete a live matter on its own."""
    case_id = await _case(
        tag, "stale-stamp", status=CaseStatus.IN_PROGRESS.value,
        closed_at=datetime.now(timezone.utc) - timedelta(days=CASE_DATA_DAYS + 99))

    assert case_id not in await _selected(_expired_closed(datetime.now(timezone.utc)))


async def test_no_live_case_is_left_carrying_a_closure_instant(tag):
    """The invariant the two chokepoints exist to maintain, asserted over the
    collection rather than over one document."""
    case_id = await _case(tag, "invariant")
    await admin_service.update_case_status(case_id, CaseStatus.CLOSED.value, ADMIN)
    await admin_service.update_case_status(case_id, CaseStatus.IN_PROGRESS.value, ADMIN)

    leaked = await _selected({
        "_id": {"$regex": f"^{tag}"},
        "status": {"$nin": sorted(TERMINAL_CASE_STATUSES)},
        "closed_at": {"$type": "date"},
    })
    assert leaked == set()


# ══════════════════════════════════════════════════════════════════════════════
# The abandoned-draft fallback
# ══════════════════════════════════════════════════════════════════════════════

async def test_an_abandoned_draft_becomes_eligible_after_a_year(tag):
    """A draft is a converted intake whose client never pressed Confirm. Its
    intake clock no longer applies and its case clock never starts, so without
    this rule it would be kept for ever."""
    case_id = await _case(
        tag, "draft-old", status=CaseStatus.DRAFT.value,
        created_at=datetime.now(timezone.utc) - timedelta(days=DRAFT_FALLBACK_DAYS + 1))

    assert case_id in await _selected(_abandoned_drafts(datetime.now(timezone.utc)))


async def test_a_recent_draft_is_left_alone(tag):
    """Someone mid-intake. The boundary again, from the other side."""
    case_id = await _case(
        tag, "draft-new", status=CaseStatus.DRAFT.value,
        created_at=datetime.now(timezone.utc) - timedelta(days=DRAFT_FALLBACK_DAYS - 1))

    assert case_id not in await _selected(_abandoned_drafts(datetime.now(timezone.utc)))


async def test_the_draft_clock_is_creation_not_last_activity(tag):
    """`created_at` deliberately, not `updated_at`. An abandoned draft that some
    background write touches — a re-analysis, a migration — must not have its
    abandonment clock reset by activity its owner never performed."""
    case_id = await _case(
        tag, "draft-touched", status=CaseStatus.DRAFT.value,
        created_at=datetime.now(timezone.utc) - timedelta(days=DRAFT_FALLBACK_DAYS + 30),
        updated_at=datetime.now(timezone.utc))

    assert case_id in await _selected(_abandoned_drafts(datetime.now(timezone.utc)))


async def test_a_confirmed_case_is_not_an_abandoned_draft(tag):
    """The draft rule must not reach a case the client actually confirmed,
    however old — that one is governed by the twelve-year case clock."""
    case_id = await _case(
        tag, "confirmed", status=CaseStatus.OPEN.value,
        created_at=datetime.now(timezone.utc) - timedelta(days=DRAFT_FALLBACK_DAYS + 900))

    assert case_id not in await _selected(_abandoned_drafts(datetime.now(timezone.utc)))
