"""Create, sign and send is ONE operation — or it did not happen.

THE DEFECT. `POST /agreements` inserted an agreement with every party unsigned
and notified the counterparties immediately, outside any transaction. The
creator signed in a SECOND request. Between the two, a counterparty held a
document its sender had not signed; if the second call never came, they held it
forever. The builder UI showed "SIGNED" as soon as the first call returned,
which is a frontend assumption about a state the backend had not reached.

WHAT THESE TESTS PIN. Not that the happy path works -- that is the easy half.
That a FAILURE leaves nothing behind: no row a recipient can see, no
notification, no receipt. A transaction that is only tested when it succeeds is
untested, because success is what the old broken code did too.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest

from app.core import signature_crypto as sc
from app.core.constants import AgreementStatus, CaseStatus

pytestmark = pytest.mark.integration

LAWYER = "CS-LAWYER"
CLIENT = "CS-CLIENT"
THIRD = "CS-THIRD"
TYPED = "Adv Creator"


@pytest.fixture
async def world(mongo_transactional, monkeypatch):
    from app.core.config import settings
    from app.db.collections import (
        get_agreements_col, get_cases_col, get_event_outbox_col, get_users_col,
    )
    # The builder is parked by DG-25. These tests exercise the MECHANISM the
    # flag gates; parking is a product decision about template content, not a
    # statement that the send path may be unsafe.
    monkeypatch.setattr(settings, "agreements_diy_builder_enabled", True)

    await get_users_col().insert_many([
        {"_id": LAWYER, "full_name": "Adv Creator", "role": "lawyer",
         "email": "l@cs.test", "is_active": True,
         "lawyer_profile": {"kyc_verified": True, "specializations": ["civil"]}},
        {"_id": CLIENT, "full_name": "The Client", "role": "client",
         "email": "c@cs.test", "is_active": True},
        {"_id": THIRD, "full_name": "Third Party", "role": "client",
         "email": "t@cs.test", "is_active": True},
    ])
    yield
    ids = [LAWYER, CLIENT, THIRD]
    await get_users_col().delete_many({"_id": {"$in": ids}})
    await get_cases_col().delete_many({"client_id": CLIENT})
    await get_agreements_col().delete_many({"created_by": {"$in": ids}})
    await get_event_outbox_col().delete_many({"payload.recipient_id": {"$in": ids}})


async def _case() -> str:
    from app.db.collections import get_cases_col
    now = datetime.now(timezone.utc)
    cid = secrets.token_urlsafe(9)
    await get_cases_col().insert_one({
        "_id": cid, "client_id": CLIENT, "lawyer_id": LAWYER,
        "title": "A matter", "case_number": f"CS-{cid[:6]}",
        "status": CaseStatus.IN_PROGRESS.value,
        "milestones": [], "created_at": now, "updated_at": now})
    return cid


async def _send(*, parties=None, key=None, title="Retainer",
                body="Fees are 40% of recovery.", case_id=None, consent=True):
    from app.services import agreement_service
    return await agreement_service.create_and_send_agreement(
        title=title, body_html=body,
        parties=parties if parties is not None else [{"user_id": CLIENT}],
        creator_id=LAWYER, method="typed", signature_data=TYPED,
        consent=consent, idempotency_key=key or secrets.token_urlsafe(12),
        case_id=case_id or await _case(),
        ip_address="203.0.113.9", ip_verifiable=True)


async def _row(agreement_id):
    from app.db.collections import get_agreements_col
    return await get_agreements_col().find_one({"_id": agreement_id})


async def _outbox_for(agreement_id):
    from app.db.collections import get_event_outbox_col
    return [e async for e in get_event_outbox_col().find(
        {"payload.data.agreement_id": agreement_id})]


# ── the happy path, stated as the invariant it establishes ──────────────────

async def test_the_creator_is_already_signed_when_recipients_can_see_it(world):
    """THE invariant. There is no moment at which this is false."""
    doc = await _send()

    row = await _row(doc["_id"])
    creator = next(p for p in row["parties"] if p["user_id"] == LAWYER)
    other = next(p for p in row["parties"] if p["user_id"] == CLIENT)

    assert row["status"] == AgreementStatus.PENDING.value
    assert creator["signed"] is True
    assert creator["signed_at"] is not None
    assert other["signed"] is False, "the counterparty must not be pre-signed"


async def test_the_creators_signature_is_encrypted(world):
    doc = await _send()

    row = await _row(doc["_id"])
    creator = next(p for p in row["parties"] if p["user_id"] == LAWYER)

    assert sc.is_encrypted(creator["signature_data"])
    assert TYPED not in repr(creator["signature_data"])


async def test_notifications_are_parked_not_sent_directly(world):
    """The outbox row commits with the agreement or not at all."""
    doc = await _send()

    events = await _outbox_for(doc["_id"])

    assert len(events) == 1, "one recipient, one event"
    assert events[0]["payload"]["recipient_id"] == CLIENT
    assert events[0]["payload"]["recipient_id"] != LAWYER, "creator notified"


async def test_the_body_digest_is_fixed_at_send(world):
    from app.services import agreement_service

    doc = await _send(body="Fees are 50% of recovery.")
    row = await _row(doc["_id"])

    assert row["body_sha256"] == agreement_service.body_digest(
        "Fees are 50% of recovery.")

    # NARROWED 2026-09-25, AND THE PROPERTY IS UNCHANGED. This read
    # `all(e.get("body_sha256") == row["body_sha256"] for e in audit_log)`,
    # which held only while every audit entry happened to be about the
    # document. The log now also records delivery outcomes -- an email that
    # went out, one that failed -- and those have no business carrying the
    # document's digest; demanding one would be asserting the wrong thing to
    # keep a convenient `all()` true.
    #
    # What matters is both halves of the original intent: the entries that DO
    # describe the document carry the right digest, and NO entry carries a
    # different one.
    document_events = [e for e in row["audit_log"]
                       if e.get("action") in {"created", "sent"}]
    assert document_events, "the send must record the document"
    assert all(e.get("body_sha256") == row["body_sha256"]
               for e in document_events)
    assert not [e for e in row["audit_log"]
                if e.get("body_sha256") not in (None, row["body_sha256"])], \
        "an audit entry carries a digest that is not this agreement's body"


async def test_three_parties_are_sent_and_each_gets_one_notification(world):
    doc = await _send(parties=[{"user_id": CLIENT}, {"user_id": THIRD}])

    row = await _row(doc["_id"])
    events = await _outbox_for(doc["_id"])

    assert len(row["parties"]) == 3
    assert {p["user_id"] for p in row["parties"]} == {LAWYER, CLIENT, THIRD}
    assert {e["payload"]["recipient_id"] for e in events} == {CLIENT, THIRD}
    assert sum(1 for p in row["parties"] if p["signed"]) == 1


# ── rollback: the half these tests exist for ────────────────────────────────

async def test_a_failure_parking_the_notification_leaves_no_agreement(world,
                                                                      monkeypatch):
    """If ANY write in the transaction fails, a recipient must never see it."""
    from app.services import agreement_service, event_outbox

    async def boom(*a, **k):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(event_outbox, "park_in_transaction", boom)

    case_id = await _case()
    with pytest.raises(RuntimeError):
        await _send(case_id=case_id)

    from app.db.collections import get_agreements_col, get_event_outbox_col
    assert await get_agreements_col().count_documents(
        {"created_by": LAWYER}) == 0, "an agreement survived a failed send"
    assert await get_event_outbox_col().count_documents(
        {"payload.recipient_id": CLIENT}) == 0


async def test_an_unconsented_signature_is_refused_before_anything_is_written(world):
    from app.core.exceptions import AppValidationError
    from app.db.collections import get_agreements_col

    with pytest.raises(AppValidationError):
        await _send(consent=False)

    assert await get_agreements_col().count_documents({"created_by": LAWYER}) == 0


# ── idempotency and concurrency ─────────────────────────────────────────────

async def test_the_same_key_and_payload_replays_rather_than_duplicating(world):
    from app.db.collections import get_agreements_col

    case_id = await _case()
    key = secrets.token_urlsafe(12)
    first = await _send(key=key, case_id=case_id)
    again = await _send(key=key, case_id=case_id)

    assert again["_id"] == first["_id"]
    assert await get_agreements_col().count_documents({"created_by": LAWYER}) == 1
    row = await _row(first["_id"])
    assert sum(1 for p in row["parties"] if p["signed"]) == 1, "signed twice"


async def test_the_same_key_with_a_different_payload_is_a_conflict(world):
    from app.core.exceptions import ConflictError

    case_id = await _case()
    key = secrets.token_urlsafe(12)
    await _send(key=key, case_id=case_id, title="Retainer")

    with pytest.raises(ConflictError):
        await _send(key=key, case_id=case_id, title="A DIFFERENT agreement")


async def test_two_concurrent_sends_with_one_key_produce_one_agreement(world):
    """Same key, same payload, racing. The database decides, not a read-check."""
    import asyncio
    from app.db.collections import get_agreements_col

    case_id = await _case()
    key = secrets.token_urlsafe(12)

    results = await asyncio.gather(
        _send(key=key, case_id=case_id),
        _send(key=key, case_id=case_id),
        return_exceptions=True,
    )

    made = [r for r in results if isinstance(r, dict)]
    assert made, f"both attempts failed: {results}"
    assert len({r["_id"] for r in made}) == 1
    assert await get_agreements_col().count_documents({"created_by": LAWYER}) == 1


async def test_the_id_is_not_derivable_from_the_key_alone(world):
    """Ids are HMAC'd under the server secret, so knowing a key does not let
    anybody compute the agreement id it produced (id enumeration)."""
    import hashlib
    from app.services import agreement_service

    key = secrets.token_urlsafe(12)
    doc = await _send(key=key)

    naive = hashlib.sha256(key.encode()).hexdigest()[:22]
    assert doc["_id"] != naive
    assert doc["_id"] == agreement_service._idempotent_agreement_id(LAWYER, key)
    # And a different creator with the SAME key gets a different id.
    assert agreement_service._idempotent_agreement_id(CLIENT, key) != doc["_id"]


# ── authorisation is not bypassed by the new path ───────────────────────────

async def test_the_park_flag_still_refuses(world, monkeypatch):
    from app.core.config import settings
    from app.core.exceptions import ForbiddenError

    monkeypatch.setattr(settings, "agreements_diy_builder_enabled", False)

    with pytest.raises(ForbiddenError):
        await _send()


async def test_an_agreement_needs_no_case(world):
    """A case is an OPTIONAL relationship, not a prerequisite.

    REVERSED 2026-09-25 (product decision). This used to assert a refusal, and
    that rule made the builder unusable by construction: it has no case picker,
    so every send it produced was a guaranteed 403. An agreement is an
    independent legal object whose required part is its signers.

    What the reversal gives up -- the cold-outreach defence -- is stated at the
    call site and in AGREEMENTS_PRODUCT_PLAN.md D2 rule 3. The test below
    (`test_a_supplied_case_is_still_fully_enforced`) pins the half that stays.
    """
    from app.core.constants import AgreementStatus
    from app.services import agreement_service

    doc = await agreement_service.create_and_send_agreement(
        title="No case", body_html="Terms.", parties=[{"user_id": CLIENT}],
        creator_id=LAWYER, method="typed", signature_data=TYPED,
        consent=True, idempotency_key=secrets.token_urlsafe(12),
        case_id=None)

    assert doc["status"] == AgreementStatus.PENDING.value
    assert doc["case_id"] is None
    assert {p["user_id"] for p in doc["parties"]} == {LAWYER, CLIENT}


async def test_a_supplied_case_is_still_fully_enforced(world):
    """Optional does not mean unchecked.

    Passing a case you are not a party to is refused exactly as before -- the
    relaxation is only that the field may be absent.
    """
    from app.core.exceptions import ForbiddenError, NotFoundError
    from app.services import agreement_service

    with pytest.raises((ForbiddenError, NotFoundError)):
        await agreement_service.create_and_send_agreement(
            title="Someone else's case", body_html="Terms.",
            parties=[{"user_id": CLIENT}], creator_id=LAWYER, method="typed",
            signature_data=TYPED, consent=True,
            idempotency_key=secrets.token_urlsafe(12),
            case_id="A-CASE-THAT-IS-NOT-THEIRS")


async def test_the_withdrawn_template_marker_is_still_refused(world):
    from app.core.exceptions import AppValidationError
    from app.services.agreement_service import UNREVIEWED_TEMPLATE_MARKER

    with pytest.raises(AppValidationError):
        await _send(body=f"Terms. {UNREVIEWED_TEMPLATE_MARKER}")


async def test_the_counterparty_cannot_be_replaced_by_a_stranger(world):
    """The D2-reversal rule holds on this path too, not only on the old one."""
    from app.core.exceptions import ForbiddenError

    with pytest.raises(ForbiddenError):
        await _send(parties=[{"user_id": THIRD}])    # CLIENT omitted
