"""Declining a legacy engagement letter ends the LETTER, and nothing else.

HISTORY
-------
Phase 2 (remediation plan R1-R8) made declining a linked engagement letter
REVERSE its engagement to `declined` and release the case, in one transaction,
because a letter was then the consent artifact and billing and reviews read it.

NOW -- AGREEMENTS_PRODUCT_PLAN.md §17 R5-12 / C-A (Gate 2 Step 4)
-------------------------------------------------------------------
New engagements generate no letter, and neither billing nor reviews read one.
Letters that exist are historical compatibility data. So a decline:

* cancels the agreement and appends one `declined` audit entry (actor, time,
  IP, reason, body digest) -- in ONE conditional write, filtered on `pending`;
* notifies the counterparty, parked in the same transaction;
* does NOT read or write the engagement it names, and does NOT write
  `case.lawyer_id` (R3-26) -- the reversal is gone;
* works when the engagement or the case no longer exists. The pre-cutover
  census found five pending letters in exactly that state.

`decline_source` values the reversal already wrote stay readable on their
engagement rows (`EngagementOut`); no new decline writes one.

Tests that need a real transaction take `mongo_transactional`, which skips with
a reason on a standalone rather than exercising only the fail-closed path.
"""
from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timezone

import pytest

from app.core.constants import AgreementStatus, CaseStatus, EngagementStatus

CLIENT = "P2-CLIENT"
LAWYER = "P2-LAWYER"
OTHER_LAWYER = "P2-OTHER-LAWYER"


@pytest.fixture
async def world(mongo_transactional):
    """A client, two lawyers, and cleanup across all four collections."""
    from app.db.collections import (
        get_agreements_col,
        get_cases_col,
        get_engagements_col,
        get_event_outbox_col,
        get_users_col,
    )

    await get_users_col().insert_many([
        {"_id": CLIENT, "full_name": "Client One", "role": "client", "email": "c@x.test"},
        {"_id": LAWYER, "full_name": "Lawyer One", "role": "lawyer", "email": "l@x.test"},
        {"_id": OTHER_LAWYER, "full_name": "Lawyer Two", "role": "lawyer", "email": "l2@x.test"},
    ])
    yield
    ids = [CLIENT, LAWYER, OTHER_LAWYER]
    await get_users_col().delete_many({"_id": {"$in": ids}})
    await get_cases_col().delete_many({"client_id": CLIENT})
    await get_engagements_col().delete_many({"client_id": CLIENT})
    await get_agreements_col().delete_many({"created_by": {"$in": ids}})
    await get_event_outbox_col().delete_many({"payload.recipient_id": {"$in": ids}})


async def _engaged(*, lawyer_id: str = LAWYER,
                   letter_status: str = AgreementStatus.PENDING.value,
                   eng_status: str = EngagementStatus.ACCEPTED.value,
                   link_back: bool = True) -> dict:
    """A case claimed by `lawyer_id`, its engagement, and its letter.

    Built directly rather than by driving accept_terms: this file is about what
    DECLINE does to an existing arrangement, and constructing the arrangement
    by hand keeps each test's starting state visible in the test.
    """
    from app.db.collections import (
        get_agreements_col,
        get_cases_col,
        get_engagements_col,
    )
    from app.services import agreement_service

    now = datetime.now(timezone.utc)
    case_id = secrets.token_urlsafe(12)
    eng_id = secrets.token_urlsafe(12)
    agr_id = secrets.token_urlsafe(12)
    body = "Engagement letter terms."

    await get_cases_col().insert_one({
        "_id": case_id, "client_id": CLIENT, "lawyer_id": lawyer_id,
        "title": "Property matter", "case_number": "C-1",
        "status": CaseStatus.IN_PROGRESS.value,
        "milestones": [], "created_at": now, "updated_at": now,
    })
    await get_engagements_col().insert_one({
        "_id": eng_id, "case_id": case_id, "client_id": CLIENT,
        "lawyer_id": lawyer_id, "status": eng_status,
        "agreement_id": agr_id if link_back else "SOME-OTHER-LETTER",
        "fee_amount": 50000, "fee_type": "fixed",
        "created_at": now, "updated_at": now,
    })
    await get_agreements_col().insert_one({
        "_id": agr_id, "title": "Engagement Letter — Property matter",
        "body_html": body,
        "body_format": agreement_service.BODY_FORMAT_PLAIN_TEXT,
        "body_sha256": agreement_service.body_digest(body),
        "status": letter_status,
        "case_id": case_id, "engagement_id": eng_id,
        "parties": [
            {"user_id": LAWYER, "full_name": "Lawyer One", "signed": False,
             "signed_at": None, "signature_method": None, "signature_data": None},
            {"user_id": CLIENT, "full_name": "Client One", "signed": False,
             "signed_at": None, "signature_method": None, "signature_data": None},
        ],
        "audit_log": [], "created_by": LAWYER,
        "created_at": now, "updated_at": now,
    })
    return {"case_id": case_id, "engagement_id": eng_id, "agreement_id": agr_id}


async def _rows(w: dict) -> tuple[dict, dict, dict]:
    from app.db.collections import (
        get_agreements_col,
        get_cases_col,
        get_engagements_col,
    )
    return (
        await get_agreements_col().find_one({"_id": w["agreement_id"]}),
        await get_engagements_col().find_one({"_id": w["engagement_id"]}),
        await get_cases_col().find_one({"_id": w["case_id"]}),
    )


async def _decline(w, user_id=CLIENT, reason="No"):
    from app.services import agreement_service
    return await agreement_service.decline_agreement(
        agreement_id=w["agreement_id"], user_id=user_id,
        reason=reason, ip_address=None)


def _outbox_id(w, decliner=CLIENT, recipient=LAWYER):
    return f"agreement:{w['agreement_id']}:declined:{decliner}:{recipient}"


async def _assert_only_the_letter_moved(w, eng_before, case_before):
    """THE C-A INVARIANT: the engagement and the case are byte-identical."""
    _, eng, case = await _rows(w)
    assert eng == eng_before, "a decline wrote to the engagement"
    assert case == case_before, "a decline wrote to the case"


# ── 1 & 2: either party can decline, and only the letter moves ──────────────

@pytest.mark.integration
@pytest.mark.parametrize("decliner,expected", [(CLIENT, "client"), (LAWYER, "lawyer")])
async def test_declining_a_linked_letter_ends_only_the_letter(world, decliner, expected):
    """FORMERLY: the engagement went `declined` and the case was released.
    Now either party's decline cancels the letter and touches nothing else."""
    w = await _engaged()
    _, eng_before, case_before = await _rows(w)

    await _decline(w, user_id=decliner, reason="Not signing this")

    agreement, _, _ = await _rows(w)
    assert agreement["status"] == AgreementStatus.CANCELLED.value
    entry = agreement["audit_log"][-1]
    assert entry["action"] == "declined" and entry["actor_id"] == decliner
    await _assert_only_the_letter_moved(w, eng_before, case_before)


# ── 3: the human reason is not a machine sentinel ────────────────────────────

@pytest.mark.integration
async def test_the_reason_is_recorded_on_the_letter_and_no_decline_source_is_written(world):
    """The human reason lives in the letter's audit entry. `decline_source` was
    the reversal's machine discriminator on the ENGAGEMENT; no new decline
    writes one."""
    w = await _engaged()
    await _decline(w, reason="The fee is wrong")

    agreement, eng, _ = await _rows(w)
    assert agreement["audit_log"][-1]["reason"] == "The fee is wrong"
    assert "decline_source" not in eng
    assert "declined_agreement_id" not in eng
    assert "declined_at" not in eng


@pytest.mark.integration
async def test_no_reason_leaves_the_field_null_not_a_sentinel(world):
    w = await _engaged()
    await _decline(w, reason="   ")

    agreement, _, _ = await _rows(w)
    assert agreement["audit_log"][-1]["reason"] is None


# ── 4: the agreement, its audit entry and its notice move together ──────────

@pytest.mark.integration
async def test_the_agreement_audit_and_outbox_change_and_nothing_else(world):
    """FORMERLY all five changed together. Now three do: the agreement, its
    audit entry, and one outbox row for the counterparty."""
    from app.db.collections import get_event_outbox_col

    w = await _engaged()
    _, eng_before, case_before = await _rows(w)
    await _decline(w)

    agreement, _, _ = await _rows(w)
    assert agreement["status"] == AgreementStatus.CANCELLED.value
    assert [a["action"] for a in agreement["audit_log"]] == ["declined"]
    assert agreement["audit_log"][0]["body_sha256"] == agreement["body_sha256"]
    assert await get_event_outbox_col().count_documents({"_id": _outbox_id(w)}) == 1
    await _assert_only_the_letter_moved(w, eng_before, case_before)


# ── 5: a forced failure rolls the whole thing back ───────────────────────────

@pytest.mark.integration
async def test_a_failure_inside_the_transaction_rolls_everything_back(world, monkeypatch):
    """THE atomicity proof.

    The outbox park is made to explode after the agreement, engagement and case
    writes have all been issued. Nothing may survive: an agreement cancelled
    with the engagement still accepted is precisely the split state this phase
    exists to remove, and creating it during the repair would be worse than the
    original defect.
    """
    from app.services import agreement_service, event_outbox

    w = await _engaged()

    async def boom(*a, **kw):
        raise RuntimeError("outbox down")

    monkeypatch.setattr(event_outbox, "park_in_transaction", boom)

    with pytest.raises(Exception):
        await agreement_service.decline_agreement(
            agreement_id=w["agreement_id"], user_id=CLIENT,
            reason="No", ip_address=None)

    agreement, eng, case = await _rows(w)
    assert agreement["status"] == AgreementStatus.PENDING.value, "agreement rolled back"
    assert agreement["audit_log"] == [], "no audit entry survived"
    assert eng["status"] == EngagementStatus.ACCEPTED.value, "engagement rolled back"
    assert case["lawyer_id"] == LAWYER, "case still assigned"
    assert case["status"] == CaseStatus.IN_PROGRESS.value
    assert not (case.get("milestones") or []), "no milestone survived"


# ── 6: a generic agreement is untouched by any of this ───────────────────────

@pytest.mark.integration
async def test_a_generic_agreement_decline_touches_no_engagement_or_case(world):
    """Agreements without `engagement_id` keep their pre-Phase-2 behaviour."""
    from app.db.collections import get_agreements_col, get_cases_col
    from app.services import agreement_service

    # A live engagement exists alongside, and must be untouched.
    w = await _engaged()

    now = datetime.now(timezone.utc)
    generic_id = secrets.token_urlsafe(12)
    body = "A plain agreement between two people."
    await get_agreements_col().insert_one({
        "_id": generic_id, "title": "Generic", "body_html": body,
        "body_sha256": agreement_service.body_digest(body),
        "status": AgreementStatus.PENDING.value,
        "case_id": None, "engagement_id": None,
        "parties": [
            {"user_id": CLIENT, "full_name": "Client One", "signed": False,
             "signed_at": None, "signature_method": None, "signature_data": None},
            {"user_id": LAWYER, "full_name": "Lawyer One", "signed": False,
             "signed_at": None, "signature_method": None, "signature_data": None},
        ],
        "audit_log": [], "created_by": CLIENT,
        "created_at": now, "updated_at": now,
    })

    await agreement_service.decline_agreement(
        agreement_id=generic_id, user_id=LAWYER, reason="No", ip_address=None)

    generic = await get_agreements_col().find_one({"_id": generic_id})
    assert generic["status"] == AgreementStatus.CANCELLED.value

    _, eng, _ = await _rows(w)
    assert eng["status"] == EngagementStatus.ACCEPTED.value, "unrelated engagement moved"
    untouched = await get_cases_col().find_one({"_id": w["case_id"]})
    assert untouched["lawyer_id"] == LAWYER, "unrelated case was released"


# ── 7: an executed agreement is immutable ────────────────────────────────────

@pytest.mark.integration
async def test_an_executed_letter_cannot_be_declined_and_nothing_moves(world):
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    w = await _engaged(letter_status=AgreementStatus.EXECUTED.value)

    with pytest.raises(AppValidationError):
        await agreement_service.decline_agreement(
            agreement_id=w["agreement_id"], user_id=CLIENT,
            reason="Changed my mind", ip_address=None)

    agreement, eng, case = await _rows(w)
    assert agreement["status"] == AgreementStatus.EXECUTED.value
    assert agreement["audit_log"] == []
    assert eng["status"] == EngagementStatus.ACCEPTED.value
    assert case["lawyer_id"] == LAWYER


# ── 8: no case is ever written by a decline ─────────────────────────────────

@pytest.mark.integration
async def test_a_case_held_by_another_lawyer_is_left_exactly_as_it_is(world):
    w = await _engaged()
    from app.db.collections import get_cases_col
    await get_cases_col().update_one(
        {"_id": w["case_id"]}, {"$set": {"lawyer_id": OTHER_LAWYER}})
    _, eng_before, case_before = await _rows(w)

    await _decline(w)
    await _assert_only_the_letter_moved(w, eng_before, case_before)


@pytest.mark.integration
async def test_no_case_gains_a_milestone_from_a_decline(world):
    w = await _engaged()
    await _decline(w)
    _, _, case = await _rows(w)
    assert not (case.get("milestones") or [])
    assert case["status"] == CaseStatus.IN_PROGRESS.value


@pytest.mark.integration
async def test_a_superseded_letter_is_declinable_and_moves_nothing_else(world):
    """FORMERLY refused (superseded link). The decline no longer reads the
    engagement, so a letter it no longer points at is simply declined."""
    w = await _engaged(link_back=False)
    _, eng_before, case_before = await _rows(w)

    await _decline(w)

    agreement, _, _ = await _rows(w)
    assert agreement["status"] == AgreementStatus.CANCELLED.value
    await _assert_only_the_letter_moved(w, eng_before, case_before)


@pytest.mark.integration
@pytest.mark.parametrize("ended", [EngagementStatus.COMPLETED.value,
                                   EngagementStatus.TERMINATED.value])
async def test_an_already_ended_engagement_is_not_rewritten(world, ended):
    """History is not re-ended by a late decline of its letter."""
    from app.services import agreement_service

    w = await _engaged(eng_status=ended)
    await agreement_service.decline_agreement(
        agreement_id=w["agreement_id"], user_id=CLIENT,
        reason="Late", ip_address=None)

    agreement, eng, _ = await _rows(w)
    assert agreement["status"] == AgreementStatus.CANCELLED.value
    assert eng["status"] == ended, "a finished engagement was rewritten"
    assert "decline_source" not in eng


# ── 9: concurrency ───────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_concurrent_sign_and_decline_produce_one_terminal_outcome(world):
    from app.services import agreement_service

    w = await _engaged()
    _, eng_before, case_before = await _rows(w)

    async def sign():
        try:
            return await agreement_service.submit_signature(
                agreement_id=w["agreement_id"], user_id=LAWYER,
                method="typed", signature_data="Lawyer One", ip_address=None)
        except Exception as exc:
            return exc

    async def decline():
        try:
            return await _decline(w)
        except Exception as exc:
            return exc

    await asyncio.gather(sign(), decline())

    agreement, _, _ = await _rows(w)
    actions = [a["action"] for a in agreement["audit_log"]]
    if agreement["status"] == AgreementStatus.CANCELLED.value:
        assert actions[-1] == "declined", "nothing may follow the decline"
    else:
        # The signature won; the letter still awaits its second signature.
        assert agreement["status"] == AgreementStatus.PENDING.value
        assert "declined" not in actions
    # Whichever won, the engagement and case never moved.
    await _assert_only_the_letter_moved(w, eng_before, case_before)


# ── 10: idempotent retry ─────────────────────────────────────────────────────

@pytest.mark.integration
async def test_a_genuine_full_callback_retry_duplicates_nothing(world):
    """A REAL retry: the whole callback runs twice, across two transactions.

    `with_transaction` ABORTS a failed attempt -- rolling back every write it
    made -- and runs the callback again in a fresh transaction. Attempt one
    executes fully and is aborted; attempt two commits. The committed result
    must be single: one audit entry, one outbox row, and still no engagement or
    case write.
    """
    from app.db.collections import get_event_outbox_col
    from app.db.mongodb import get_client
    from app.services import agreement_service

    w = await _engaged()
    _, eng_before, case_before = await _rows(w)
    attempts = {"n": 0}

    async def run_once(session):
        attempts["n"] += 1
        return await agreement_service._decline_in_transaction(
            session, agreement_id=w["agreement_id"], user_id=CLIENT,
            reason="Changed my mind", ip_address=None)

    client = get_client()
    async with await client.start_session() as session:
        session.start_transaction()
        await run_once(session)
        await session.abort_transaction()

    agreement, _, _ = await _rows(w)
    assert agreement["status"] == AgreementStatus.PENDING.value
    assert agreement["audit_log"] == []
    assert await get_event_outbox_col().count_documents({"_id": _outbox_id(w)}) == 0, (
        "an aborted attempt left an outbox row behind")

    async with await client.start_session() as session:
        session.start_transaction()
        await run_once(session)
        await session.commit_transaction()

    assert attempts["n"] == 2
    agreement, _, _ = await _rows(w)
    assert len([a for a in agreement["audit_log"] if a["action"] == "declined"]) == 1
    assert await get_event_outbox_col().count_documents({"_id": _outbox_id(w)}) == 1
    await _assert_only_the_letter_moved(w, eng_before, case_before)


@pytest.mark.integration
async def test_parking_a_duplicate_event_inside_a_transaction_fails_closed(world):
    """`park_in_transaction` no longer swallows DuplicateKeyError.

    The old behaviour caught it and continued, on the reasoning that a
    deterministic id makes a re-park harmless. But `with_transaction` rolls back
    before retrying, so a retry never collides with itself -- which means a
    collision can only come from a PREVIOUSLY COMMITTED transaction. Continuing
    past that would commit a transition on top of work already done.

    This pins the fail-closed behaviour against real Mongo rather than assuming
    it: park an id, commit, then park the same id again in a new transaction and
    require the error to surface.
    """
    from pymongo.errors import DuplicateKeyError

    from app.db.collections import get_event_outbox_col
    from app.db.mongodb import get_client
    from app.services import event_outbox

    logical = f"agreement:dupe-test-{secrets.token_urlsafe(6)}:declined:{CLIENT}:{LAWYER}"
    payload = {"logical_event_id": logical, "recipient_id": LAWYER,
               "ntype": "agreement_declined", "title": "t", "body": "b", "data": {}}

    client = get_client()
    async with await client.start_session() as session:
        session.start_transaction()
        await event_outbox.park_in_transaction(
            session, logical, "notifications", payload)
        await session.commit_transaction()

    with pytest.raises(DuplicateKeyError):
        async with await client.start_session() as session:
            session.start_transaction()
            await event_outbox.park_in_transaction(
                session, logical, "notifications", payload)
            await session.commit_transaction()

    assert await get_event_outbox_col().count_documents({"_id": logical}) == 1
    await get_event_outbox_col().delete_one({"_id": logical})


# ── item 4: broken or changed links no longer block a decline (C-A) ─────────

@pytest.mark.integration
async def test_an_engagement_changed_mid_decline_does_not_affect_it(world, monkeypatch):
    """FORMERLY a TOCTOU abort on the engagement backlink. The decline no longer
    reads the engagement, so an engagement re-pointed between preflight and the
    transaction neither blocks the decline nor gets written by it."""
    from app.db.collections import get_engagements_col
    from app.services import agreement_service

    w = await _engaged()
    real_run = agreement_service._run_in_transaction

    async def flip_then_run(txn):
        await get_engagements_col().update_one(
            {"_id": w["engagement_id"]}, {"$set": {"agreement_id": "LETTER-B"}})
        return await real_run(txn)

    monkeypatch.setattr(agreement_service, "_run_in_transaction", flip_then_run)
    await _decline(w)

    agreement, eng, case = await _rows(w)
    assert agreement["status"] == AgreementStatus.CANCELLED.value
    assert eng["agreement_id"] == "LETTER-B"          # only the test wrote it
    assert eng["status"] == EngagementStatus.ACCEPTED.value
    assert case["lawyer_id"] == LAWYER


@pytest.mark.integration
async def test_an_orphaned_legacy_letter_can_be_declined(world):
    """THE CENSUS REGRESSION. The pre-cutover census found five pending letters
    whose engagement row no longer exists. FORMERLY their decline aborted on
    the missing link; now it proceeds like any other agreement's."""
    from app.db.collections import get_engagements_col

    w = await _engaged()
    await get_engagements_col().delete_one({"_id": w["engagement_id"]})

    await _decline(w, reason="This was never mine to sign")

    agreement, eng, _ = await _rows(w)
    assert agreement["status"] == AgreementStatus.CANCELLED.value
    assert agreement["audit_log"][-1]["action"] == "declined"
    assert eng is None, "a decline recreated the missing engagement"


@pytest.mark.integration
async def test_a_letter_whose_case_is_gone_can_be_declined(world):
    """All six census orphans also lost their case. That does not block a
    decline either -- and nothing recreates the case."""
    from app.db.collections import get_cases_col, get_engagements_col

    w = await _engaged()
    await get_engagements_col().delete_one({"_id": w["engagement_id"]})
    await get_cases_col().delete_one({"_id": w["case_id"]})

    await _decline(w)

    agreement, _, case = await _rows(w)
    assert agreement["status"] == AgreementStatus.CANCELLED.value
    assert case is None, "a decline recreated the missing case"


@pytest.mark.integration
async def test_a_party_to_the_letter_may_decline_it_whatever_the_engagement_says(world):
    """FORMERLY refused: the reversal required the decliner to be a party to the
    ENGAGEMENT too, because it was about to change that engagement. The decline
    now ends only the agreement, so the agreement's own parties are the
    authority -- and the engagement it names is left exactly as it was."""
    from app.db.collections import get_engagements_col

    w = await _engaged()
    await get_engagements_col().update_one(
        {"_id": w["engagement_id"]}, {"$set": {"client_id": "SOMEONE-ELSE"}})
    _, eng_before, case_before = await _rows(w)

    await _decline(w, user_id=CLIENT)

    agreement, _, _ = await _rows(w)
    assert agreement["status"] == AgreementStatus.CANCELLED.value
    await _assert_only_the_letter_moved(w, eng_before, case_before)


# ── the counterparty notice ──────────────────────────────────────────────────

@pytest.mark.integration
async def test_the_counterparty_notice_says_who_declined_what_and_why(world):
    """And claims nothing else -- no ended engagement, no reopened case."""
    from app.db.collections import get_event_outbox_col

    w = await _engaged()
    await _decline(w, reason="Scope is too broad")

    row = await get_event_outbox_col().find_one({"_id": _outbox_id(w)})
    body = row["payload"]["body"]
    assert "Client One" in body
    assert "Engagement Letter — Property matter" in body
    assert "Scope is too broad" in body
    assert row["payload"]["title"] == "Agreement declined"
    for claim in ("engagement has ended", "open again", "new engagement"):
        assert claim not in body.lower(), claim


# ── item 5: historical reversal metadata stays readable ─────────────────────

def test_engagement_out_exposes_the_letter_decline_metadata():
    """R2's fields reach the client, deliberately.

    `EngagementOut` uses `extra="ignore"`, so a field absent from the model is
    silently dropped on the way out -- no error, just missing data. Without
    these three, a letter-decline and a pre-acceptance terms-decline look
    identical on the wire, and only one of them ever claimed a case.
    """
    from datetime import datetime, timezone

    from app.schemas.engagement import EngagementOut

    out = EngagementOut(
        id="E1", status="declined",
        declined_by="client",
        declined_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        decline_source="engagement_letter",
        decline_reason="The fee is higher than we discussed.",
        declined_agreement_id="AGR-1",
    )
    dumped = out.model_dump()

    assert dumped["declined_at"] is not None
    assert dumped["decline_source"] == "engagement_letter"
    assert dumped["declined_agreement_id"] == "AGR-1"
    # The human reason and the machine discriminator stay distinct on the wire.
    assert dumped["decline_reason"] == "The fee is higher than we discussed."
    assert dumped["decline_reason"] != dumped["decline_source"]


# -- final pass: the callback's own authorization contract -------------------

@pytest.mark.integration
async def test_a_non_party_cannot_invoke_the_callback_directly(world):
    """The callback must be safe WITHOUT `decline_agreement`'s preflight.

    A callback that is only safe because of what its usual caller checked first
    is one refactor away from being unsafe -- and this one is directly
    invocable. Driving it with a stranger proves the guard lives here.
    """
    from app.core.exceptions import ForbiddenError
    from app.db.collections import get_agreements_col
    from app.db.mongodb import get_client
    from app.services import agreement_service

    now = datetime.now(timezone.utc)
    generic_id = secrets.token_urlsafe(12)
    body = "A plain agreement."
    await get_agreements_col().insert_one({
        "_id": generic_id, "title": "Generic", "body_html": body,
        "body_sha256": agreement_service.body_digest(body),
        "status": AgreementStatus.PENDING.value,
        "case_id": None, "engagement_id": None,
        "parties": [
            {"user_id": CLIENT, "full_name": "Client One", "signed": False},
            {"user_id": LAWYER, "full_name": "Lawyer One", "signed": False},
        ],
        "audit_log": [], "created_by": CLIENT,
        "created_at": now, "updated_at": now,
    })

    client = get_client()
    with pytest.raises(ForbiddenError):
        async with await client.start_session() as session:
            session.start_transaction()
            await agreement_service._decline_in_transaction(
                session, agreement_id=generic_id, user_id=OTHER_LAWYER,
                reason="Not mine", ip_address=None)
            await session.commit_transaction()

    after = await get_agreements_col().find_one({"_id": generic_id})
    assert after["status"] == AgreementStatus.PENDING.value
    assert after["audit_log"] == []
    await get_agreements_col().delete_one({"_id": generic_id})


@pytest.mark.integration
async def test_removing_the_requester_from_parties_after_preflight_aborts(world, monkeypatch):
    """Party membership is re-asserted under the transaction session.

    `decline_agreement` authorises on a stale pre-transaction read. If the
    requester is removed from the agreement between that check and the writes,
    the callback must refuse -- a party who is no longer a party must not still
    be able to end the instrument. (The hook moved from `_linked_engagement`,
    which no longer exists, to the transaction runner itself.)
    """
    from app.core.exceptions import ForbiddenError
    from app.db.collections import get_agreements_col, get_event_outbox_col
    from app.services import agreement_service

    w = await _engaged()
    real_run = agreement_service._run_in_transaction

    async def pull_then_run(txn):
        await get_agreements_col().update_one(
            {"_id": w["agreement_id"]},
            {"$pull": {"parties": {"user_id": CLIENT}}})
        return await real_run(txn)

    monkeypatch.setattr(agreement_service, "_run_in_transaction", pull_then_run)

    with pytest.raises(ForbiddenError):
        await _decline(w)

    agreement, eng, case = await _rows(w)
    assert agreement["status"] == AgreementStatus.PENDING.value
    assert agreement["audit_log"] == []
    assert eng["status"] == EngagementStatus.ACCEPTED.value
    assert case["lawyer_id"] == LAWYER
    assert await get_event_outbox_col().count_documents({"_id": _outbox_id(w)}) == 0


@pytest.mark.integration
@pytest.mark.parametrize("ended", [EngagementStatus.COMPLETED.value,
                                   EngagementStatus.TERMINATED.value])
async def test_a_letter_beside_an_ended_engagement_is_declined_without_touching_it(world, ended):
    """An ended engagement is not re-ended, re-opened or annotated by a late
    decline of its legacy letter."""
    w = await _engaged(eng_status=ended)
    _, eng_before, case_before = await _rows(w)

    await _decline(w)

    agreement, _, _ = await _rows(w)
    assert agreement["status"] == AgreementStatus.CANCELLED.value
    await _assert_only_the_letter_moved(w, eng_before, case_before)


# -- final pass: the notice makes no engagement claims ------------------------

@pytest.mark.integration
async def test_an_unassigned_case_stays_unassigned(world):
    from app.db.collections import get_cases_col

    w = await _engaged()
    await get_cases_col().update_one({"_id": w["case_id"]}, {"$set": {"lawyer_id": None}})
    _, eng_before, case_before = await _rows(w)

    await _decline(w)
    await _assert_only_the_letter_moved(w, eng_before, case_before)


def test_the_decline_notice_makes_no_engagement_claims():
    """The three reversal-shaped notices are gone; one shape remains."""
    from app.services import agreement_service

    said = agreement_service._decline_notice("Client One", "Letter", "Too costly")
    assert said == 'Client One declined "Letter". Reason: Too costly'
    assert agreement_service._decline_notice("A", "T", None) == 'A declined "T".'


def test_the_reversal_machinery_is_gone():
    """C-A, structurally: nothing in the agreement module can reverse an
    engagement or write a case any more."""
    import inspect

    from app.services import agreement_service

    for name in ("_linked_engagement", "_reverse_engagement",
                 "DECLINE_SOURCE_ENGAGEMENT_LETTER"):
        assert not hasattr(agreement_service, name), name
    src = inspect.getsource(agreement_service._decline_in_transaction)
    assert "get_engagements_col" not in src and "get_cases_col" not in src