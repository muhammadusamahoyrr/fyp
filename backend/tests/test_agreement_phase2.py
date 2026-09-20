"""Phase 2: declining an engagement letter reverses its engagement.

THE DEFECT
----------
`decline_agreement` read `engagement_id` nowhere. The field was written at
creation and acted on by nothing, so declining an engagement letter cancelled
the agreement and left the engagement `accepted` with the case still assigned.
The lawyer could not invoice -- the fee gate refuses a non-executed letter --
and was told the letter "must be signed by both you and the client", which
`submit_signature` refuses permanently for a cancelled agreement. The
instruction was impossible to follow.

THE APPROVED RULES (plan Phase 2, R1-R8)
----------------------------------------
Reuse `declined`; no new status. Record `declined_by`, `declined_at`,
`decline_source`, the human `decline_reason` and `declined_agreement_id`. Keep
the accept-terms case claim. Reverse in ONE transaction. Release the case only
when it is still held by that engagement's lawyer. Review eligibility requires
an EXECUTED letter. Never tell the user to terminate -- the reversal already
ended the engagement.

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


# ── 1 & 2: either party can decline, and the reversal is symmetric ───────────

@pytest.mark.integration
@pytest.mark.parametrize("decliner,expected", [(CLIENT, "client"), (LAWYER, "lawyer")])
async def test_declining_a_linked_letter_reverses_everything(world, decliner, expected):
    from app.services import agreement_service

    w = await _engaged()
    await agreement_service.decline_agreement(
        agreement_id=w["agreement_id"], user_id=decliner,
        reason="The fee is higher than we discussed.", ip_address=None)

    agreement, eng, case = await _rows(w)

    assert agreement["status"] == AgreementStatus.CANCELLED.value
    assert eng["status"] == EngagementStatus.DECLINED.value
    assert eng["declined_by"] == expected
    assert eng["decline_source"] == "engagement_letter"
    assert eng["declined_agreement_id"] == w["agreement_id"]
    assert eng["declined_at"] is not None
    # The case is released so the client can engage somebody else.
    assert case["lawyer_id"] is None
    assert case["status"] == CaseStatus.OPEN.value


# ── 3: the human reason is not a machine sentinel ────────────────────────────

@pytest.mark.integration
async def test_the_human_reason_is_kept_apart_from_the_machine_discriminator(world):
    """`decline_reason` is shown to the counterparty.

    Writing the sentinel into it would render "engagement_letter" to a person,
    or force every reader to know which values are prose and which are codes.
    """
    from app.services import agreement_service

    w = await _engaged()
    await agreement_service.decline_agreement(
        agreement_id=w["agreement_id"], user_id=CLIENT,
        reason="I have decided to handle this myself.", ip_address=None)

    _, eng, _ = await _rows(w)
    assert eng["decline_reason"] == "I have decided to handle this myself."
    assert eng["decline_source"] == "engagement_letter"
    assert eng["decline_reason"] != eng["decline_source"]


@pytest.mark.integration
async def test_no_reason_leaves_the_field_null_not_a_sentinel(world):
    from app.services import agreement_service

    w = await _engaged()
    await agreement_service.decline_agreement(
        agreement_id=w["agreement_id"], user_id=CLIENT,
        reason=None, ip_address=None)

    _, eng, _ = await _rows(w)
    assert eng["decline_reason"] is None
    assert eng["decline_source"] == "engagement_letter"


# ── 4: everything moves together ─────────────────────────────────────────────

@pytest.mark.integration
async def test_agreement_engagement_case_audit_and_outbox_all_change(world):
    """The atomic unit, asserted across all five artifacts."""
    from app.db.collections import get_event_outbox_col
    from app.services import agreement_service

    w = await _engaged()
    await agreement_service.decline_agreement(
        agreement_id=w["agreement_id"], user_id=CLIENT,
        reason="No thanks", ip_address="198.51.100.4")

    agreement, eng, case = await _rows(w)

    assert agreement["status"] == AgreementStatus.CANCELLED.value
    entry = next(a for a in agreement["audit_log"] if a["action"] == "declined")
    assert entry["body_sha256"] == agreement["body_sha256"]
    assert entry["reason"] == "No thanks"
    assert entry["ip_address"] == "198.51.100.4"

    assert eng["status"] == EngagementStatus.DECLINED.value
    assert case["lawyer_id"] is None

    milestones = case.get("milestones") or []
    assert len(milestones) == 1
    assert "letter declined" in milestones[0]["title"].lower()

    parked = await get_event_outbox_col().find_one(
        {"_id": f"agreement:{w['agreement_id']}:declined:{CLIENT}:{LAWYER}"})
    assert parked is not None
    assert parked["destination"] == "notifications"


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


# ── 8: a case reassigned since is never cleared ──────────────────────────────

@pytest.mark.integration
async def test_a_case_now_held_by_another_lawyer_is_not_released(world):
    """The conditional filter's whole purpose.

    A late decline of a superseded letter must not take a live matter away from
    a lawyer who has nothing to do with it.
    """
    from app.db.collections import get_cases_col
    from app.services import agreement_service

    w = await _engaged()
    # The case moves on to somebody else before the decline lands.
    await get_cases_col().update_one(
        {"_id": w["case_id"]}, {"$set": {"lawyer_id": OTHER_LAWYER}})

    before = await get_cases_col().find_one({"_id": w["case_id"]})

    await agreement_service.decline_agreement(
        agreement_id=w["agreement_id"], user_id=CLIENT,
        reason="Too slow", ip_address=None)

    agreement, eng, case = await _rows(w)
    # The letter and its own engagement still end -- those are this decline's
    # business. The case is not, and must be left alone ENTIRELY.
    assert agreement["status"] == AgreementStatus.CANCELLED.value
    assert eng["status"] == EngagementStatus.DECLINED.value
    assert case == before, "a reassigned case was modified in some field"


@pytest.mark.integration
async def test_a_reassigned_case_gains_no_milestone_and_is_not_called_open(world):
    """Two claims that must not be made about somebody else's case.

    A milestone about an engagement that is no longer the case's own would put
    a stranger's history on their timeline. And telling the counterparty their
    case is "open again" when another lawyer holds it is a false statement
    about their own matter, which invites them to act on it.
    """
    from app.db.collections import get_cases_col, get_event_outbox_col
    from app.services import agreement_service

    w = await _engaged()
    await get_cases_col().update_one(
        {"_id": w["case_id"]}, {"$set": {"lawyer_id": OTHER_LAWYER}})

    await agreement_service.decline_agreement(
        agreement_id=w["agreement_id"], user_id=CLIENT,
        reason="Too slow", ip_address=None)

    case = await get_cases_col().find_one({"_id": w["case_id"]})
    assert not (case.get("milestones") or []), "a milestone landed on another lawyer's case"
    assert case["status"] == CaseStatus.IN_PROGRESS.value, "status was changed"

    parked = await get_event_outbox_col().find_one(
        {"_id": f"agreement:{w['agreement_id']}:declined:{CLIENT}:{LAWYER}"})
    body = parked["payload"]["body"].lower()
    assert "open again" not in body, "claimed a reassigned case was reopened"
    assert "assignment was not changed" in body
    assert "engagement has ended" in body
    assert "no fees can be raised" in body


@pytest.mark.integration
async def test_a_superseded_letter_cannot_reverse_its_engagement(world):
    """The engagement points at a DIFFERENT letter, so this one is stale."""
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    w = await _engaged(link_back=False)

    with pytest.raises(AppValidationError) as exc:
        await agreement_service.decline_agreement(
            agreement_id=w["agreement_id"], user_id=CLIENT,
            reason="No", ip_address=None)
    assert "superseded" in str(exc.value).lower()

    agreement, eng, case = await _rows(w)
    assert agreement["status"] == AgreementStatus.PENDING.value, "nothing written"
    assert eng["status"] == EngagementStatus.ACCEPTED.value
    assert case["lawyer_id"] == LAWYER


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

    async def sign():
        try:
            return await agreement_service.submit_signature(
                agreement_id=w["agreement_id"], user_id=LAWYER,
                method="typed", signature_data="Lawyer One", ip_address=None)
        except Exception as exc:
            return exc

    async def decline():
        try:
            return await agreement_service.decline_agreement(
                agreement_id=w["agreement_id"], user_id=CLIENT,
                reason="No", ip_address=None)
        except Exception as exc:
            return exc

    await asyncio.gather(sign(), decline())

    agreement, eng, case = await _rows(w)
    actions = [a["action"] for a in agreement["audit_log"]]

    if agreement["status"] == AgreementStatus.CANCELLED.value:
        assert actions[-1] == "declined", "nothing may follow the decline"
        assert eng["status"] == EngagementStatus.DECLINED.value
        assert case["lawyer_id"] is None
    else:
        # The signature won; the letter is still pending its second signature,
        # so the engagement must be exactly as it was.
        assert agreement["status"] == AgreementStatus.PENDING.value
        assert "declined" not in actions
        assert eng["status"] == EngagementStatus.ACCEPTED.value
        assert case["lawyer_id"] == LAWYER


# ── 10: idempotent retry ─────────────────────────────────────────────────────

@pytest.mark.integration
async def test_a_genuine_full_callback_retry_duplicates_nothing(world):
    """A REAL retry: the whole callback runs twice, across two transactions.

    The previous version of this test re-invoked `_reverse_engagement` twice
    inside ONE transaction, which is not what `with_transaction` does and
    proved the wrong property. `with_transaction` ABORTS a failed attempt --
    rolling back every write it made -- and then runs the callback again in a
    fresh transaction.

    So this drives that exact shape: attempt one executes fully and is aborted,
    attempt two executes and commits. Everything the first attempt wrote must
    have vanished, and the committed result must be single: one audit entry,
    one milestone, one engagement transition, one outbox row.
    """
    from app.db.collections import get_event_outbox_col
    from app.db.mongodb import get_client
    from app.services import agreement_service

    w = await _engaged()

    # Build the callback the service would build, then drive it by hand so the
    # abort/retry boundary is explicit rather than simulated.
    attempts = {"n": 0}

    async def run_once(session):
        attempts["n"] += 1
        return await agreement_service._decline_in_transaction(
            session,
            agreement_id=w["agreement_id"], user_id=CLIENT,
            reason="Changed my mind", ip_address=None,
        )

    client = get_client()
    async with await client.start_session() as session:
        # ATTEMPT 1 — runs the full body, then aborts. Nothing may survive.
        session.start_transaction()
        await run_once(session)
        await session.abort_transaction()

    agreement, eng, case = await _rows(w)
    assert agreement["status"] == AgreementStatus.PENDING.value
    assert agreement["audit_log"] == []
    assert eng["status"] == EngagementStatus.ACCEPTED.value
    assert not (case.get("milestones") or [])
    assert await get_event_outbox_col().count_documents(
        {"_id": f"agreement:{w['agreement_id']}:declined:{CLIENT}:{LAWYER}"}) == 0, (
        "an aborted attempt left an outbox row behind")

    async with await client.start_session() as session:
        # ATTEMPT 2 — the retry. Commits.
        session.start_transaction()
        await run_once(session)
        await session.commit_transaction()

    assert attempts["n"] == 2

    agreement, eng, case = await _rows(w)
    assert len([a for a in agreement["audit_log"] if a["action"] == "declined"]) == 1
    assert len(case.get("milestones") or []) == 1, "milestone duplicated across retry"
    assert eng["status"] == EngagementStatus.DECLINED.value
    assert eng["decline_source"] == "engagement_letter"
    assert await get_event_outbox_col().count_documents(
        {"_id": f"agreement:{w['agreement_id']}:declined:{CLIENT}:{LAWYER}"}) == 1


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


# ── item 4: linkage regressions, all decided INSIDE the transaction ──────────

@pytest.mark.integration
async def test_a_backlink_changed_after_preflight_aborts_everything(world, monkeypatch):
    """THE time-of-check/time-of-use gap.

    Preflight validates the chain on a stale read. If the engagement is
    re-pointed at a DIFFERENT letter between that check and the writes, the old
    code would have reversed on a letter the engagement no longer recognised.

    The engagement is moved to letter B after preflight passes but before the
    transaction body runs. Letter A must stay pending, and nothing else may
    move.
    """
    from app.db.collections import get_engagements_col
    from app.services import agreement_service

    w = await _engaged()
    real_preflight = agreement_service._linked_engagement
    flipped = {"done": False}

    async def flip_after_preflight(agreement, user_id, session=None):
        result = await real_preflight(agreement, user_id, session=session)
        # Only the preflight call (no session) triggers the flip, so the
        # in-transaction check sees the CHANGED world.
        if session is None and not flipped["done"]:
            flipped["done"] = True
            await get_engagements_col().update_one(
                {"_id": w["engagement_id"]},
                {"$set": {"agreement_id": "LETTER-B"}})
        return result

    monkeypatch.setattr(agreement_service, "_linked_engagement",
                        flip_after_preflight)

    from app.core.exceptions import AppValidationError
    with pytest.raises(AppValidationError) as exc:
        await agreement_service.decline_agreement(
            agreement_id=w["agreement_id"], user_id=CLIENT,
            reason="No", ip_address=None)
    assert "superseded" in str(exc.value).lower()

    agreement, eng, case = await _rows(w)
    assert agreement["status"] == AgreementStatus.PENDING.value, "letter A moved"
    assert agreement["audit_log"] == [], "an audit entry survived"
    assert eng["status"] == EngagementStatus.ACCEPTED.value
    assert eng["agreement_id"] == "LETTER-B", "the flip itself was rolled back"
    assert case["lawyer_id"] == LAWYER

    from app.db.collections import get_event_outbox_col
    assert await get_event_outbox_col().count_documents(
        {"_id": f"agreement:{w['agreement_id']}:declined:{CLIENT}:{LAWYER}"}) == 0


@pytest.mark.integration
async def test_a_missing_engagement_aborts_the_whole_decline(world):
    from app.core.exceptions import AppValidationError
    from app.db.collections import get_engagements_col
    from app.services import agreement_service

    w = await _engaged()
    await get_engagements_col().delete_one({"_id": w["engagement_id"]})

    with pytest.raises(AppValidationError):
        await agreement_service.decline_agreement(
            agreement_id=w["agreement_id"], user_id=CLIENT,
            reason="No", ip_address=None)

    agreement, _, case = await _rows(w)
    assert agreement["status"] == AgreementStatus.PENDING.value
    assert agreement["audit_log"] == []
    assert case["lawyer_id"] == LAWYER


@pytest.mark.integration
async def test_a_missing_case_aborts_the_whole_decline(world):
    """A missing case is broken linkage, not merely an unreleasable case."""
    from app.core.exceptions import AppValidationError
    from app.db.collections import get_cases_col
    from app.services import agreement_service

    w = await _engaged()
    await get_cases_col().delete_one({"_id": w["case_id"]})

    with pytest.raises(AppValidationError) as exc:
        await agreement_service.decline_agreement(
            agreement_id=w["agreement_id"], user_id=CLIENT,
            reason="No", ip_address=None)
    assert "case" in str(exc.value).lower()

    agreement, eng, _ = await _rows(w)
    assert agreement["status"] == AgreementStatus.PENDING.value
    assert agreement["audit_log"] == []
    assert eng["status"] == EngagementStatus.ACCEPTED.value


@pytest.mark.integration
async def test_an_agreement_party_who_is_not_an_engagement_party_is_refused(world):
    """The two documents disagree about who is involved.

    That is not a decline this code can reason about, so it refuses rather than
    guessing which document is right.
    """
    from app.core.exceptions import AppValidationError
    from app.db.collections import get_agreements_col, get_engagements_col
    from app.services import agreement_service

    w = await _engaged()
    # A third party is added to the LETTER but is nobody on the engagement.
    await get_agreements_col().update_one(
        {"_id": w["agreement_id"]},
        {"$push": {"parties": {
            "user_id": OTHER_LAWYER, "full_name": "Lawyer Two", "signed": False,
            "signed_at": None, "signature_method": None, "signature_data": None}}})

    with pytest.raises(AppValidationError) as exc:
        await agreement_service.decline_agreement(
            agreement_id=w["agreement_id"], user_id=OTHER_LAWYER,
            reason="Not mine", ip_address=None)
    assert "not a party to the engagement" in str(exc.value).lower()

    agreement, eng, case = await _rows(w)
    assert agreement["status"] == AgreementStatus.PENDING.value
    assert agreement["audit_log"] == []
    assert eng["status"] == EngagementStatus.ACCEPTED.value
    assert case["lawyer_id"] == LAWYER
    assert await get_engagements_col().count_documents(
        {"_id": w["engagement_id"], "decline_source": {"$exists": True}}) == 0


# ── the counterparty notice ──────────────────────────────────────────────────

@pytest.mark.integration
async def test_the_counterparty_notice_carries_every_fact_they_need(world):
    """Four facts, because the reader's next action depends on all of them."""
    from app.db.collections import get_event_outbox_col
    from app.services import agreement_service

    w = await _engaged()
    await agreement_service.decline_agreement(
        agreement_id=w["agreement_id"], user_id=CLIENT,
        reason="Fee too high", ip_address=None)

    parked = await get_event_outbox_col().find_one(
        {"_id": f"agreement:{w['agreement_id']}:declined:{CLIENT}:{LAWYER}"})
    body = parked["payload"]["body"].lower()

    assert "client one" in body, "who declined"
    assert "fee too high" in body, "why"
    assert "engagement has ended" in body
    assert "case is open again" in body
    assert "no fees can be raised" in body
    assert "new engagement" in body and "new letter" in body
    # R6: the reversal already ended it, so there is nothing to terminate.
    assert "terminate" not in body


# ── item 5: the reversal metadata is exposed, not internal ──────────────────

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
    be able to end the instrument.
    """
    from app.core.exceptions import ForbiddenError
    from app.db.collections import get_agreements_col, get_event_outbox_col
    from app.services import agreement_service

    w = await _engaged()
    real_preflight = agreement_service._linked_engagement
    pulled = {"done": False}

    async def pull_after_preflight(agreement, user_id, session=None):
        result = await real_preflight(agreement, user_id, session=session)
        if session is None and not pulled["done"]:
            pulled["done"] = True
            await get_agreements_col().update_one(
                {"_id": w["agreement_id"]},
                {"$pull": {"parties": {"user_id": CLIENT}}})
        return result

    monkeypatch.setattr(agreement_service, "_linked_engagement",
                        pull_after_preflight)

    with pytest.raises(ForbiddenError):
        await agreement_service.decline_agreement(
            agreement_id=w["agreement_id"], user_id=CLIENT,
            reason="No", ip_address=None)

    agreement, eng, case = await _rows(w)
    assert agreement["status"] == AgreementStatus.PENDING.value
    assert agreement["audit_log"] == []
    assert eng["status"] == EngagementStatus.ACCEPTED.value
    assert case["lawyer_id"] == LAWYER
    assert await get_event_outbox_col().count_documents(
        {"_id": f"agreement:{w['agreement_id']}:declined:{CLIENT}:{LAWYER}"}) == 0


@pytest.mark.integration
@pytest.mark.parametrize("ended", [EngagementStatus.COMPLETED.value,
                                   EngagementStatus.TERMINATED.value])
async def test_engagement_party_mismatch_is_refused_even_when_ended(world, ended):
    """Authorization does not lapse because the engagement did.

    The ended-engagement early return used to come BEFORE the identity check,
    so a requester who was a party to the LETTER but a stranger to the
    ENGAGEMENT was never checked -- they could cancel the letter of a
    relationship they had nothing to do with, purely because it had finished.
    """
    from app.core.exceptions import AppValidationError
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    w = await _engaged(eng_status=ended)
    await get_agreements_col().update_one(
        {"_id": w["agreement_id"]},
        {"$push": {"parties": {
            "user_id": OTHER_LAWYER, "full_name": "Lawyer Two", "signed": False}}})

    with pytest.raises(AppValidationError) as exc:
        await agreement_service.decline_agreement(
            agreement_id=w["agreement_id"], user_id=OTHER_LAWYER,
            reason="Not mine", ip_address=None)
    assert "not a party to the engagement" in str(exc.value).lower()

    agreement, eng, _ = await _rows(w)
    assert agreement["status"] == AgreementStatus.PENDING.value
    assert agreement["audit_log"] == []
    assert eng["status"] == ended


# -- final pass: the non-released notice tells the truth ---------------------

@pytest.mark.integration
async def test_an_already_unassigned_case_is_not_called_reassigned(world):
    """A zero-match release does NOT mean somebody else took the case.

    The previous copy inferred "assigned elsewhere" from `modified_count == 0`,
    which is also what an already-unassigned case produces -- telling a client a
    stranger had taken their matter when in fact nobody had.
    """
    from app.db.collections import get_cases_col, get_event_outbox_col
    from app.services import agreement_service

    w = await _engaged()
    await get_cases_col().update_one(
        {"_id": w["case_id"]}, {"$set": {"lawyer_id": None}})

    await agreement_service.decline_agreement(
        agreement_id=w["agreement_id"], user_id=CLIENT,
        reason="No", ip_address=None)

    parked = await get_event_outbox_col().find_one(
        {"_id": f"agreement:{w['agreement_id']}:declined:{CLIENT}:{LAWYER}"})
    body = parked["payload"]["body"].lower()

    assert "assigned elsewhere" not in body, "claimed a stranger took the case"
    assert "open again" not in body
    assert "assignment was not changed" in body
    assert "no fees can be raised" in body


@pytest.mark.integration
@pytest.mark.parametrize("scenario", ["reassigned", "already_unassigned"])
async def test_a_non_released_case_never_instructs_an_impossible_new_engagement(world, scenario):
    """While another lawyer holds the case, `request_engagement` refuses.

    So a notice telling the client to start a new engagement fails the moment
    they follow it. Only the released branch may say that.
    """
    from app.db.collections import get_cases_col, get_event_outbox_col
    from app.services import agreement_service

    w = await _engaged()
    await get_cases_col().update_one(
        {"_id": w["case_id"]},
        {"$set": {"lawyer_id":
                  OTHER_LAWYER if scenario == "reassigned" else None}})

    await agreement_service.decline_agreement(
        agreement_id=w["agreement_id"], user_id=CLIENT,
        reason="No", ip_address=None)

    parked = await get_event_outbox_col().find_one(
        {"_id": f"agreement:{w['agreement_id']}:declined:{CLIENT}:{LAWYER}"})
    body = parked["payload"]["body"].lower()

    assert "open again" not in body
    assert "start a new engagement" not in body
    assert "engage another lawyer" not in body
    assert "engagement has ended" in body


@pytest.mark.integration
async def test_only_the_released_branch_promises_a_new_engagement(world):
    """The released case genuinely can be re-engaged, so it alone says so."""
    from app.db.collections import get_event_outbox_col
    from app.services import agreement_service

    w = await _engaged()
    await agreement_service.decline_agreement(
        agreement_id=w["agreement_id"], user_id=CLIENT,
        reason="No", ip_address=None)

    parked = await get_event_outbox_col().find_one(
        {"_id": f"agreement:{w['agreement_id']}:declined:{CLIENT}:{LAWYER}"})
    body = parked["payload"]["body"].lower()

    assert "open again" in body
    assert "start a new engagement" in body
