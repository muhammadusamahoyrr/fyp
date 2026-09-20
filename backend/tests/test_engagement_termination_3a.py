"""Gate 3A: engagement termination is atomic and cancels its pending letter.

THE DEFECT
----------
`terminate_engagement` ran four independent writes -- engagement status, case
release, milestone, notify. A crash between them left an engagement
`terminated` with its case still assigned: a client still holding a lawyer who
believed they had withdrawn. That is the Gate 2 defect's mirror, in the code
Gate 2 did not touch. It was also the only one of the pair that was LIVE, since
unauthorized create is masked by the parked builder flag.

It also never touched the engagement's letter, so terminating left a `pending`
letter behind forever.

THE RULE THAT INVERTS GATE 2
----------------------------
Declining is an action ABOUT a letter, so Gate 2 aborts when the letter link is
broken. Terminating is an action about the ENGAGEMENT, and termination is a
SAFETY EXIT: a client who wants out of a representation cannot be held there
because a letter row is missing, superseded or corrupt. A broken link records an
anomaly and the termination completes.

NO MOCKS. Every test in this file runs against a real replica set via
`mongo_transactional`, which skips with an explicit reason on a standalone. The
forced-failure test monkeypatches the OUTBOX to raise -- that is an injected
fault inside a genuine transaction, not a mocked transaction boundary; the
rollback it asserts is performed by MongoDB.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest

from app.core.constants import AgreementStatus, CaseStatus, EngagementStatus

CLIENT = "T3A-CLIENT"
LAWYER = "T3A-LAWYER"
OTHER_LAWYER = "T3A-OTHER"


@pytest.fixture
async def world(mongo_transactional):
    from app.db.collections import (
        get_agreements_col,
        get_cases_col,
        get_engagements_col,
        get_event_outbox_col,
        get_users_col,
    )

    await get_users_col().insert_many([
        {"_id": CLIENT, "full_name": "Client One", "role": "client", "email": "c@t3a.test"},
        {"_id": LAWYER, "full_name": "Lawyer One", "role": "lawyer", "email": "l@t3a.test"},
        {"_id": OTHER_LAWYER, "full_name": "Lawyer Two", "role": "lawyer", "email": "l2@t3a.test"},
    ])
    yield
    ids = [CLIENT, LAWYER, OTHER_LAWYER]
    await get_users_col().delete_many({"_id": {"$in": ids}})
    await get_cases_col().delete_many({"client_id": CLIENT})
    await get_engagements_col().delete_many({"client_id": CLIENT})
    await get_agreements_col().delete_many({"created_by": {"$in": ids}})
    await get_event_outbox_col().delete_many({"payload.recipient_id": {"$in": ids}})


async def _accepted(*, letter: str | None = AgreementStatus.PENDING.value,
                    link_back: bool = True, drop_letter: bool = False) -> dict:
    """An accepted engagement, its claimed case, and (usually) its letter.

    `letter=None` builds an engagement with no `agreement_id` at all.
    `drop_letter` writes the id but no row, which is the orphan shape.
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
    agr_id = secrets.token_urlsafe(12) if letter or drop_letter else None
    body = "Engagement letter terms."

    await get_cases_col().insert_one({
        "_id": case_id, "client_id": CLIENT, "lawyer_id": LAWYER,
        "title": "Property matter", "case_number": f"C-{case_id[:8]}",
        "status": CaseStatus.IN_PROGRESS.value,
        "milestones": [], "created_at": now, "updated_at": now,
    })
    await get_engagements_col().insert_one({
        "_id": eng_id, "case_id": case_id, "client_id": CLIENT,
        "lawyer_id": LAWYER, "status": EngagementStatus.ACCEPTED.value,
        "agreement_id": agr_id, "fee_amount": 50000, "fee_type": "fixed",
        "created_at": now, "updated_at": now,
    })
    if letter and not drop_letter:
        await get_agreements_col().insert_one({
            "_id": agr_id, "title": "Engagement Letter", "body_html": body,
            "body_sha256": agreement_service.body_digest(body),
            "status": letter, "case_id": case_id,
            "engagement_id": eng_id if link_back else "SOME-OTHER-ENGAGEMENT",
            "parties": [
                {"user_id": LAWYER, "full_name": "Lawyer One", "signed": False},
                {"user_id": CLIENT, "full_name": "Client One", "signed": False},
            ],
            "audit_log": [], "created_by": LAWYER,
            "created_at": now, "updated_at": now,
        })
    return {"case_id": case_id, "engagement_id": eng_id, "agreement_id": agr_id}


async def _rows(w: dict):
    from app.db.collections import (
        get_agreements_col,
        get_cases_col,
        get_engagements_col,
    )
    return (
        await get_engagements_col().find_one({"_id": w["engagement_id"]}),
        await get_cases_col().find_one({"_id": w["case_id"]}),
        await get_agreements_col().find_one({"_id": w["agreement_id"]})
        if w["agreement_id"] else None,
    )


# ── the happy path, both parties ────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("actor,party", [(CLIENT, "client"), (LAWYER, "lawyer")])
async def test_termination_ends_everything_in_one_go(world, actor, party):
    from app.services import engagement_service

    w = await _accepted()
    await engagement_service.terminate_engagement(
        w["engagement_id"], actor, "Communication broke down.")

    eng, case, letter = await _rows(w)

    assert eng["status"] == EngagementStatus.TERMINATED.value
    assert eng["terminated_by"] == party
    assert eng["termination_reason"] == "Communication broke down."
    assert "letter_anomaly" not in eng

    assert case["lawyer_id"] is None
    assert case["status"] == CaseStatus.OPEN.value
    assert len(case["milestones"]) == 1

    # The pending letter is cancelled under the one cancellation model.
    assert letter["status"] == AgreementStatus.CANCELLED.value
    assert letter["cancellation_source"] == "engagement_terminated"
    assert letter["cancellation_reason"] == "Communication broke down."
    assert letter["cancelled_at"] is not None
    entry = next(a for a in letter["audit_log"] if a["action"] == "cancelled")
    assert entry["body_sha256"] == letter["body_sha256"]


# ── 5.1 forced failure leaves nothing partial ───────────────────────────────

@pytest.mark.integration
async def test_a_failure_on_the_last_write_rolls_back_every_earlier_one(world, monkeypatch):
    """THE atomicity proof, and the defect's direct regression test.

    The outbox park is the LAST write in the transaction, so making it raise
    proves the three earlier writes -- engagement, case, letter -- are rolled
    back by MongoDB rather than merely un-attempted. Under the old four-write
    version each of those had already committed independently.
    """
    from app.db.collections import get_event_outbox_col
    from app.services import engagement_service, event_outbox

    w = await _accepted()

    async def boom(*a, **kw):
        raise RuntimeError("outbox down")

    monkeypatch.setattr(event_outbox, "park_in_transaction", boom)

    with pytest.raises(Exception):
        await engagement_service.terminate_engagement(
            w["engagement_id"], CLIENT, "No longer needed.")

    eng, case, letter = await _rows(w)

    assert eng["status"] == EngagementStatus.ACCEPTED.value, "engagement not rolled back"
    assert "terminated_at" not in eng
    assert case["lawyer_id"] == LAWYER, "case release survived a failed txn"
    assert case["status"] == CaseStatus.IN_PROGRESS.value
    assert not case["milestones"], "milestone survived a failed txn"
    assert letter["status"] == AgreementStatus.PENDING.value, "letter cancellation survived"
    assert letter["audit_log"] == []

    assert await get_event_outbox_col().count_documents(
        {"_id": f"engagement:{w['engagement_id']}:terminated:{LAWYER}"}) == 0


# ── 5.2 exactly one notification per party ──────────────────────────────────

@pytest.mark.integration
async def test_exactly_one_notification_and_only_to_the_other_party(world):
    """The direct `_notify` was REPLACED by the outbox park, not supplemented.

    Keeping both would double-send: one row written directly and one delivered
    by the relay.
    """
    from app.db.collections import get_event_outbox_col, get_notifications_col
    from app.services import engagement_service

    w = await _accepted()
    await engagement_service.terminate_engagement(
        w["engagement_id"], CLIENT, "Done here.")

    outbox = get_event_outbox_col()
    # One event, addressed to the lawyer (the party who did NOT terminate).
    assert await outbox.count_documents(
        {"_id": f"engagement:{w['engagement_id']}:terminated:{LAWYER}"}) == 1
    assert await outbox.count_documents(
        {"_id": f"engagement:{w['engagement_id']}:terminated:{CLIENT}"}) == 0

    # And after the drain, exactly one notification row per party -- not two
    # for the recipient, which is what a surviving direct call would produce.
    notifs = get_notifications_col()
    assert await notifs.count_documents(
        {"user_id": LAWYER, "type": "engagement_terminated",
         "payload.engagement_id": w["engagement_id"]}) == 1
    assert await notifs.count_documents(
        {"user_id": CLIENT, "type": "engagement_terminated",
         "payload.engagement_id": w["engagement_id"]}) == 0


# ── 5.3 a broken letter link never blocks the exit ──────────────────────────

@pytest.mark.integration
async def test_termination_succeeds_with_no_letter_and_records_the_anomaly(world):
    from app.services import engagement_service

    w = await _accepted(letter=None)
    await engagement_service.terminate_engagement(
        w["engagement_id"], CLIENT, "Never got started.")

    eng, case, _ = await _rows(w)
    assert eng["status"] == EngagementStatus.TERMINATED.value, "exit was blocked"
    assert eng["letter_anomaly"] == "no_letter"
    assert case["lawyer_id"] is None


@pytest.mark.integration
async def test_termination_succeeds_when_the_letter_row_is_gone(world):
    """The orphan shape the census found six of. Still not a reason to trap
    somebody in a representation."""
    from app.services import engagement_service

    w = await _accepted(drop_letter=True)
    await engagement_service.terminate_engagement(
        w["engagement_id"], LAWYER, "Withdrawing.")

    eng, case, _ = await _rows(w)
    assert eng["status"] == EngagementStatus.TERMINATED.value
    assert eng["letter_anomaly"] == "letter_missing"
    assert case["lawyer_id"] is None


@pytest.mark.integration
async def test_termination_succeeds_when_the_letter_is_superseded(world):
    """The letter points at a different engagement; cancelling it would end
    somebody else's instrument."""
    from app.services import engagement_service

    w = await _accepted(link_back=False)
    await engagement_service.terminate_engagement(
        w["engagement_id"], CLIENT, "Moving on.")

    eng, _, letter = await _rows(w)
    assert eng["status"] == EngagementStatus.TERMINATED.value
    assert eng["letter_anomaly"] == "letter_superseded"
    assert letter["status"] == AgreementStatus.PENDING.value, "someone else's letter was cancelled"


@pytest.mark.integration
async def test_an_executed_letter_survives_termination_untouched(world):
    """A properly formed instrument is not unmade by the relationship ending."""
    from app.services import engagement_service

    w = await _accepted(letter=AgreementStatus.EXECUTED.value)
    await engagement_service.terminate_engagement(
        w["engagement_id"], CLIENT, "Work is finished.")

    eng, case, letter = await _rows(w)
    assert eng["status"] == EngagementStatus.TERMINATED.value
    assert "letter_anomaly" not in eng, "an executed letter is not an anomaly"
    assert letter["status"] == AgreementStatus.EXECUTED.value
    assert letter["audit_log"] == [], "an executed letter was written to"
    assert "cancellation_source" not in letter
    assert case["lawyer_id"] is None


@pytest.mark.integration
async def test_an_already_cancelled_letter_gains_no_second_audit_entry(world):
    from app.services import engagement_service

    w = await _accepted(letter=AgreementStatus.CANCELLED.value)
    await engagement_service.terminate_engagement(
        w["engagement_id"], CLIENT, "Ending it.")

    eng, _, letter = await _rows(w)
    assert eng["status"] == EngagementStatus.TERMINATED.value
    assert "letter_anomaly" not in eng, "already-cancelled is not an anomaly"
    assert letter["audit_log"] == [], "a second cancellation entry was appended"


# ── case disposition, reusing Gate 2's structure ────────────────────────────

@pytest.mark.integration
async def test_a_reassigned_case_is_not_touched_and_not_called_open(world):
    from app.db.collections import get_cases_col, get_event_outbox_col
    from app.services import engagement_service

    w = await _accepted()
    await get_cases_col().update_one(
        {"_id": w["case_id"]}, {"$set": {"lawyer_id": OTHER_LAWYER}})
    before = await get_cases_col().find_one({"_id": w["case_id"]})

    await engagement_service.terminate_engagement(
        w["engagement_id"], LAWYER, "Handing back.")

    eng, case, _ = await _rows(w)
    assert eng["status"] == EngagementStatus.TERMINATED.value
    assert case == before, "another lawyer's case was modified"

    parked = await get_event_outbox_col().find_one(
        {"_id": f"engagement:{w['engagement_id']}:terminated:{CLIENT}"})
    assert "open again" not in parked["payload"]["body"].lower()


@pytest.mark.integration
async def test_a_second_termination_is_refused(world):
    from app.core.exceptions import AppValidationError
    from app.services import engagement_service

    w = await _accepted()
    await engagement_service.terminate_engagement(
        w["engagement_id"], CLIENT, "First.")

    with pytest.raises(AppValidationError):
        await engagement_service.terminate_engagement(
            w["engagement_id"], LAWYER, "Second.")

    eng, case, _ = await _rows(w)
    assert eng["termination_reason"] == "First."
    assert len(case["milestones"]) == 1, "a second milestone was appended"


# -- review additions: races, replay, and end-to-end delivery ----------------

@pytest.mark.integration
async def test_termination_racing_a_letter_decline_yields_one_terminal_state(world):
    """Two exits, same engagement, at the same instant.

    Both paths end the engagement and both touch the letter, by different
    routes: terminate cancels a pending letter as a side effect; decline
    cancels the letter and reverses the engagement. Exactly one may win, and
    whichever does must leave a record that agrees with itself -- the
    engagement's terminal state and the letter's cancellation cause must
    describe the same event.
    """
    import asyncio

    from app.services import agreement_service, engagement_service

    w = await _accepted()

    async def terminate():
        try:
            return await engagement_service.terminate_engagement(
                w["engagement_id"], LAWYER, "Withdrawing.")
        except Exception as exc:
            return exc

    async def decline():
        try:
            return await agreement_service.decline_agreement(
                agreement_id=w["agreement_id"], user_id=CLIENT,
                reason="Not signing.", ip_address=None)
        except Exception as exc:
            return exc

    await asyncio.gather(terminate(), decline())

    eng, case, letter = await _rows(w)

    # The engagement reached exactly one terminal state.
    assert eng["status"] in (EngagementStatus.TERMINATED.value,
                             EngagementStatus.DECLINED.value)
    # The letter is cancelled either way -- both routes cancel a pending one.
    assert letter["status"] == AgreementStatus.CANCELLED.value

    # THE CONSISTENCY CHECK: the two records must tell the same story.
    if eng["status"] == EngagementStatus.TERMINATED.value:
        assert "declined_at" not in eng, "terminated engagement carries decline metadata"
        assert letter.get("cancellation_source") == "engagement_terminated"
    else:
        assert eng["decline_source"] == "engagement_letter"
        assert "terminated_at" not in eng, "declined engagement carries termination metadata"

    # And the case is released exactly once, by whichever won.
    assert case["lawyer_id"] is None
    assert len(case.get("milestones") or []) == 1


@pytest.mark.integration
async def test_termination_racing_a_signature_leaves_no_contradiction(world):
    """Termination against the letter being signed.

    If the signature lands first the letter may still be pending (one of two
    signatures), so the termination cancels it -- fine. What must never happen
    is a letter that is EXECUTED and also cancelled, or an executed letter
    carrying a termination cancellation cause.
    """
    import asyncio

    from app.services import agreement_service, engagement_service

    w = await _accepted()

    async def terminate():
        try:
            return await engagement_service.terminate_engagement(
                w["engagement_id"], CLIENT, "Changed my mind.")
        except Exception as exc:
            return exc

    async def sign():
        try:
            return await agreement_service.submit_signature(
                agreement_id=w["agreement_id"], user_id=LAWYER,
                method="typed", signature_data="Lawyer One", ip_address=None)
        except Exception as exc:
            return exc

    await asyncio.gather(terminate(), sign())

    eng, _, letter = await _rows(w)

    assert letter["status"] in (AgreementStatus.PENDING.value,
                                AgreementStatus.CANCELLED.value)
    if letter["status"] == AgreementStatus.CANCELLED.value:
        # A cancelled letter must not also claim to be signed by everyone.
        assert not all(p.get("signed") for p in letter["parties"])
    assert eng["status"] in (EngagementStatus.ACCEPTED.value,
                             EngagementStatus.TERMINATED.value)


@pytest.mark.integration
async def test_terminating_an_already_terminated_engagement_sends_nothing_new(world):
    """A clean refusal, and critically NO second notification.

    The engagement filter already makes the second attempt a no-op. What this
    pins is that the outbox park -- which sits after it in the same transaction
    -- cannot fire on its own, which would notify the counterparty twice about
    one ending.
    """
    from app.core.exceptions import AppValidationError
    from app.db.collections import get_event_outbox_col, get_notifications_col
    from app.services import engagement_service

    w = await _accepted()
    await engagement_service.terminate_engagement(
        w["engagement_id"], CLIENT, "First and only.")

    before_outbox = await get_event_outbox_col().count_documents(
        {"payload.data.engagement_id": w["engagement_id"]})
    before_notifs = await get_notifications_col().count_documents(
        {"payload.engagement_id": w["engagement_id"]})

    with pytest.raises(AppValidationError):
        await engagement_service.terminate_engagement(
            w["engagement_id"], LAWYER, "Second attempt.")

    assert await get_event_outbox_col().count_documents(
        {"payload.data.engagement_id": w["engagement_id"]}) == before_outbox
    assert await get_notifications_col().count_documents(
        {"payload.engagement_id": w["engagement_id"]}) == before_notifs

    eng, _, _ = await _rows(w)
    assert eng["termination_reason"] == "First and only."


@pytest.mark.integration
async def test_the_drainer_actually_delivers_the_parked_event(world):
    """END TO END, not just "a row was written".

    Parking an event durably is worthless if nothing reads it back out -- the
    lesson from Phase 1 §1.1g, where the outbox had no drainer at all. This
    drives `drain_once` and asserts the notification the counterparty will
    actually see, then asserts the event is marked delivered so a second sweep
    cannot send it again.
    """
    from app.db.collections import get_event_outbox_col, get_notifications_col
    from app.services import engagement_service, event_outbox

    w = await _accepted()
    await engagement_service.terminate_engagement(
        w["engagement_id"], CLIENT, "Ending the engagement.")

    logical = f"engagement:{w['engagement_id']}:terminated:{LAWYER}"

    # `terminate_engagement` nudges the drain post-commit, so by here the event
    # should already be delivered. Drain again to prove it is idempotent.
    row = await get_event_outbox_col().find_one({"_id": logical})
    assert row is not None, "no event was parked"
    assert row["status"] == "delivered", f"event not delivered: {row['status']}"

    delivered = await get_notifications_col().find_one(
        {"user_id": LAWYER, "payload.engagement_id": w["engagement_id"]})
    assert delivered is not None, "the drainer wrote no notification"
    assert delivered["type"] == "engagement_terminated"
    assert "Ending the engagement." in delivered["body"]

    # A second sweep must not resend: the row is already `delivered`, so it is
    # no longer claimable.
    result = await event_outbox.drain_once()
    assert result["delivered"] == 0
    assert await get_notifications_col().count_documents(
        {"user_id": LAWYER, "payload.engagement_id": w["engagement_id"]}) == 1


# -- the property `ENGAGEMENT_RETAINED_STATUSES` exists to protect -----------

@pytest.mark.integration
async def test_a_terminated_engagement_with_an_executed_letter_is_still_billable(world):
    """END TO END: really terminate, then really try to bill.

    `payment_service._require_executed_engagement_letter` deliberately accepts
    ENDED engagements -- its comment at lines 100-105 explains why: the letter's
    own terms say fees for work already performed remain payable, so scoping the
    gate to `accepted` would make terminating a way to escape a bill for work
    that was actually done, and would equally strand a lawyer who finished a
    matter before invoicing.

    3A gave termination a new power -- it now writes to the letter -- so that
    property needs re-proving against the REAL termination path rather than a
    hand-built `terminated` row. The executed letter must survive untouched and
    the gate must still pass.
    """
    from app.services import engagement_service, payment_service

    w = await _accepted(letter=AgreementStatus.EXECUTED.value)

    # Before: billable.
    await payment_service._require_executed_engagement_letter(w["case_id"], LAWYER)

    await engagement_service.terminate_engagement(
        w["engagement_id"], CLIENT, "Work is complete, ending the engagement.")

    eng, case, letter = await _rows(w)
    assert eng["status"] == EngagementStatus.TERMINATED.value
    assert letter["status"] == AgreementStatus.EXECUTED.value, "3A touched an executed letter"
    assert "cancellation_source" not in letter
    assert case["lawyer_id"] is None, "the case was not released"

    # After: STILL billable. This is the assertion that matters.
    await payment_service._require_executed_engagement_letter(w["case_id"], LAWYER)


@pytest.mark.integration
async def test_a_terminated_engagement_whose_letter_3a_cancelled_is_not_billable(world):
    """The other half, so the rule above is not mistaken for "always billable".

    A PENDING letter cancelled by 3A means nobody ever agreed the fee in
    writing, so the gate must refuse -- and must say why in the cancelled-letter
    wording, not the awaiting-signatures wording.
    """
    from app.core.exceptions import AppValidationError
    from app.services import engagement_service, payment_service

    w = await _accepted()  # pending letter
    await engagement_service.terminate_engagement(
        w["engagement_id"], CLIENT, "Ending before signature.")

    _, _, letter = await _rows(w)
    assert letter["status"] == AgreementStatus.CANCELLED.value

    with pytest.raises(AppValidationError) as exc:
        await payment_service._require_executed_engagement_letter(
            w["case_id"], LAWYER)
    message = str(exc.value).lower()
    assert "was declined" in message or "not executed" in message
    assert "terminate" not in message
