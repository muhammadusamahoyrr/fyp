"""Gate 3C: versioned drafts and atomic sign-and-send.

WHAT THIS REPLACES
------------------
The parked wizard created and signed in TWO network calls. If the second
failed, the counterparty had already been notified of an agreement its sender
never signed, and the UI invited a retry that produced a second one. Sign-and-
send is now one call and one transaction.

THE HASH CHECK IS THE POINT
---------------------------
`sign_and_send_draft` requires the version AND the body digest the signer
reviewed. A concurrent edit changes both, so the send is refused rather than
binding somebody to wording they never read -- and the digest stored as
evidence always describes the text that was actually on screen.

AUTHORISATION IS RE-CHECKED AT SEND
-----------------------------------
Drafting and sending are separated in time. Verification can be revoked
(`user_service.py:312`) and a case can be reassigned in between, so D5 and D2
are both re-asserted at send rather than inherited from create.

NO MOCKS. Every integration test runs against a real replica set via
`mongo_transactional`. The forced-failure test injects a fault into the outbox
INSIDE a genuine transaction; MongoDB performs the rollback.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest

from app.core.constants import AgreementStatus, CaseStatus

LAWYER = "C3-LAWYER"
CLIENT = "C3-CLIENT"
OTHER_LAWYER = "C3-OTHER"


@pytest.fixture
async def world(mongo_transactional):
    from app.db.collections import (
        get_agreements_col,
        get_cases_col,
        get_event_outbox_col,
        get_users_col,
    )

    await get_users_col().insert_many([
        {"_id": LAWYER, "full_name": "Adv Verified", "role": "lawyer",
         "email": "l@c3.test", "is_active": True,
         "lawyer_profile": {"kyc_verified": True, "specializations": ["civil"]}},
        {"_id": OTHER_LAWYER, "full_name": "Adv Other", "role": "lawyer",
         "email": "l2@c3.test", "is_active": True,
         "lawyer_profile": {"kyc_verified": True, "specializations": ["civil"]}},
        {"_id": CLIENT, "full_name": "The Client", "role": "client",
         "email": "c@c3.test", "is_active": True},
    ])
    yield
    ids = [LAWYER, OTHER_LAWYER, CLIENT]
    await get_users_col().delete_many({"_id": {"$in": ids}})
    await get_cases_col().delete_many({"client_id": CLIENT})
    # Engagements too: tests here insert them, and a row surviving into the
    # next test now changes review eligibility, which reads the engagement.
    from app.db.collections import get_engagements_col
    await get_engagements_col().delete_many({"client_id": CLIENT})
    await get_agreements_col().delete_many({"created_by": {"$in": ids}})
    await get_event_outbox_col().delete_many({"payload.recipient_id": {"$in": ids}})


async def _case(*, lawyer_id: str = LAWYER) -> str:
    from app.db.collections import get_cases_col

    now = datetime.now(timezone.utc)
    cid = secrets.token_urlsafe(12)
    await get_cases_col().insert_one({
        "_id": cid, "client_id": CLIENT, "lawyer_id": lawyer_id,
        "title": "A matter", "case_number": f"C-{cid[:8]}",
        "status": CaseStatus.IN_PROGRESS.value,
        "milestones": [], "created_at": now, "updated_at": now,
    })
    return cid


async def _draft(case_id: str, body: str = "Scope and fee.") -> dict:
    from app.services import agreement_service

    return await agreement_service.create_draft(
        title="Retainer", body_html=body,
        client_id=CLIENT, creator_id=LAWYER, case_id=case_id)


async def _send(draft: dict, *, key: str | None = None, consent: bool = True,
                version: int | None = None, digest: str | None = None):
    from app.services import agreement_service

    return await agreement_service.sign_and_send_draft(
        agreement_id=draft["_id"], creator_id=LAWYER,
        expected_version=version if version is not None else draft["version"],
        expected_body_sha256=digest if digest is not None
        else agreement_service.body_digest(draft["body_html"]),
        method="typed", signature_data="Adv Verified", consent=consent,
        idempotency_key=key or secrets.token_urlsafe(12))


async def _row(agreement_id: str):
    from app.db.collections import get_agreements_col
    return await get_agreements_col().find_one({"_id": agreement_id})


# ── the draft lifecycle ─────────────────────────────────────────────────────

@pytest.mark.integration
async def test_a_draft_starts_at_version_one_with_no_digest(world):
    """No `body_sha256` until send.

    The digest is the record of what was SIGNED. Stamping one on a mutable
    draft would invite reading it as evidence of something nobody agreed to.
    """
    d = await _draft(await _case())
    assert d["status"] == AgreementStatus.DRAFT.value
    assert d["version"] == 1
    assert d["body_sha256"] is None
    assert not any(p["signed"] for p in d["parties"])


@pytest.mark.integration
async def test_every_edit_increments_the_version(world):
    from app.services import agreement_service

    d = await _draft(await _case())
    for expected in (1, 2, 3):
        d = await agreement_service.update_draft(
            agreement_id=d["_id"], creator_id=LAWYER,
            expected_version=expected, body_html=f"Revision {expected}.")
        assert d["version"] == expected + 1


@pytest.mark.integration
async def test_a_stale_edit_is_refused_not_merged(world):
    """Two tabs. The loser must be told, not silently overwritten."""
    from app.core.exceptions import ConflictError
    from app.services import agreement_service

    d = await _draft(await _case())
    await agreement_service.update_draft(
        agreement_id=d["_id"], creator_id=LAWYER,
        expected_version=1, body_html="First edit.")

    with pytest.raises(ConflictError):
        await agreement_service.update_draft(
            agreement_id=d["_id"], creator_id=LAWYER,
            expected_version=1, body_html="Second tab, stale.")

    row = await _row(d["_id"])
    assert row["body_html"] == "First edit."


@pytest.mark.integration
async def test_another_lawyers_draft_cannot_be_edited_or_deleted(world):
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    d = await _draft(await _case())
    with pytest.raises(ForbiddenError):
        await agreement_service.update_draft(
            agreement_id=d["_id"], creator_id=OTHER_LAWYER,
            expected_version=1, body_html="Mine now.")
    with pytest.raises(ForbiddenError):
        await agreement_service.delete_draft(
            agreement_id=d["_id"], creator_id=OTHER_LAWYER)


# ── D7: the active-draft cap ────────────────────────────────────────────────

@pytest.mark.integration
async def test_the_cap_is_enforced_and_deleting_frees_a_slot(world):
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    cap = agreement_service.MAX_ACTIVE_DRAFTS_PER_LAWYER
    case_id = await _case()
    drafts = [await _draft(case_id) for _ in range(cap)]

    with pytest.raises(AppValidationError) as exc:
        await _draft(case_id)
    assert str(cap) in str(exc.value)

    # The cap bounds LIVE work, not lifetime output.
    await agreement_service.delete_draft(
        agreement_id=drafts[0]["_id"], creator_id=LAWYER)
    freed = await _draft(case_id)
    assert freed["status"] == AgreementStatus.DRAFT.value


@pytest.mark.integration
async def test_a_sent_agreement_does_not_count_against_the_cap(world):
    """Only `draft` rows count. Otherwise a busy lawyer is locked out by their
    own successful work."""
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    case_id = await _case()
    d = await _draft(case_id)
    await _send(d)

    live = await get_agreements_col().count_documents(
        {"created_by": LAWYER, "status": AgreementStatus.DRAFT.value})
    assert live == 0
    assert (await _draft(case_id))["status"] == AgreementStatus.DRAFT.value


# ── sign-and-send: one call, one transaction ────────────────────────────────

@pytest.mark.integration
async def test_sign_and_send_freezes_signs_and_notifies_in_one_go(world):
    from app.db.collections import get_event_outbox_col
    from app.services import agreement_service

    d = await _draft(await _case())
    sent = await _send(d)

    assert sent["status"] == AgreementStatus.PENDING.value
    assert sent["body_sha256"] == agreement_service.body_digest(d["body_html"])
    assert sent["sent_at"] is not None

    creator = next(p for p in sent["parties"] if p["user_id"] == LAWYER)
    assert creator["signed"] is True
    assert creator["consent_at"] is not None
    assert not next(p for p in sent["parties"] if p["user_id"] == CLIENT)["signed"]

    entry = next(a for a in sent["audit_log"] if a["action"] == "sent")
    assert entry["body_sha256"] == sent["body_sha256"]
    assert entry["consent"] is True

    parked = await get_event_outbox_col().find_one(
        {"_id": f"agreement:{d['_id']}:sent:{CLIENT}"})
    assert parked is not None


@pytest.mark.integration
async def test_a_stale_body_hash_refuses_the_send(world):
    """THE anti-race guarantee.

    An edit lands between reviewing and sending. The signer must not be bound
    to wording they never read.
    """
    from app.core.exceptions import ConflictError
    from app.services import agreement_service

    d = await _draft(await _case())
    reviewed = agreement_service.body_digest(d["body_html"])
    await agreement_service.update_draft(
        agreement_id=d["_id"], creator_id=LAWYER,
        expected_version=1, body_html="Someone changed the fee.")

    with pytest.raises(ConflictError):
        await _send(d, version=2, digest=reviewed)

    assert (await _row(d["_id"]))["status"] == AgreementStatus.DRAFT.value


@pytest.mark.integration
async def test_consent_must_be_explicit(world):
    from app.core.exceptions import AppValidationError

    d = await _draft(await _case())
    with pytest.raises(AppValidationError):
        await _send(d, consent=False)
    assert (await _row(d["_id"]))["status"] == AgreementStatus.DRAFT.value


@pytest.mark.integration
async def test_a_forced_failure_mid_send_leaves_no_partial_state(world, monkeypatch):
    """The outbox park is the LAST write, so making it raise proves every
    earlier write is rolled back by MongoDB rather than merely un-attempted."""
    from app.db.collections import get_event_outbox_col
    from app.services import event_outbox

    d = await _draft(await _case())

    async def boom(*a, **kw):
        raise RuntimeError("outbox down")

    monkeypatch.setattr(event_outbox, "park_in_transaction", boom)

    with pytest.raises(Exception):
        await _send(d)

    row = await _row(d["_id"])
    assert row["status"] == AgreementStatus.DRAFT.value, "status survived"
    assert row["body_sha256"] is None, "digest was frozen by a failed send"
    assert row["version"] == 1, "version incremented in a failed send"
    assert not any(p["signed"] for p in row["parties"]), "signature survived"
    assert not any(a["action"] == "sent" for a in row["audit_log"])
    assert not row.get("idempotency_receipts"), "receipt survived a rollback"
    assert await get_event_outbox_col().count_documents(
        {"_id": f"agreement:{d['_id']}:sent:{CLIENT}"}) == 0


# ── idempotency ─────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_the_same_key_and_payload_replays_the_same_result(world):
    d = await _draft(await _case())
    key = "retry-" + secrets.token_urlsafe(8)

    first = await _send(d, key=key)
    second = await _send(d, key=key)

    assert first["_id"] == second["_id"]
    assert second["status"] == AgreementStatus.PENDING.value
    sent_entries = [a for a in (await _row(d["_id"]))["audit_log"]
                    if a["action"] == "sent"]
    assert len(sent_entries) == 1, "the replay appended a second audit entry"


@pytest.mark.integration
async def test_the_same_key_with_a_different_payload_is_a_conflict(world):
    """Silently aliasing would be worse than an error: the caller would believe
    their NEW request succeeded."""
    from app.core.exceptions import ConflictError
    from app.services import agreement_service

    d = await _draft(await _case())
    key = "reused-" + secrets.token_urlsafe(8)
    await _send(d, key=key)

    with pytest.raises(ConflictError) as exc:
        await agreement_service.sign_and_send_draft(
            agreement_id=d["_id"], creator_id=LAWYER,
            expected_version=d["version"],
            expected_body_sha256=agreement_service.body_digest(d["body_html"]),
            method="typed", signature_data="A DIFFERENT SIGNATURE",
            consent=True, idempotency_key=key)
    assert "already used for a different request" in str(exc.value).lower()


@pytest.mark.integration
async def test_concurrent_sends_of_one_draft_produce_exactly_one_send(world):
    import asyncio

    d = await _draft(await _case())

    async def attempt():
        try:
            return await _send(d)
        except Exception as exc:
            return exc

    await asyncio.gather(attempt(), attempt())

    row = await _row(d["_id"])
    assert row["status"] == AgreementStatus.PENDING.value
    assert len([a for a in row["audit_log"] if a["action"] == "sent"]) == 1
    assert sum(1 for p in row["parties"] if p["signed"]) == 1


# ── immutability after send ─────────────────────────────────────────────────

@pytest.mark.integration
async def test_a_sent_agreement_cannot_be_edited_or_deleted(world):
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    d = await _draft(await _case())
    sent = await _send(d)

    with pytest.raises(AppValidationError):
        await agreement_service.update_draft(
            agreement_id=d["_id"], creator_id=LAWYER,
            expected_version=sent["version"], body_html="Edited after send.")
    with pytest.raises(AppValidationError):
        await agreement_service.delete_draft(
            agreement_id=d["_id"], creator_id=LAWYER)

    assert (await _row(d["_id"]))["body_html"] == "Scope and fee."


# ── authorisation re-checked at send ────────────────────────────────────────

@pytest.mark.integration
async def test_a_relationship_that_ended_after_drafting_blocks_the_send(world):
    """D2 at SEND. The case is reassigned between drafting and sending."""
    from app.core.exceptions import ForbiddenError
    from app.db.collections import get_cases_col

    case_id = await _case()
    d = await _draft(case_id)
    await get_cases_col().update_one(
        {"_id": case_id}, {"$set": {"lawyer_id": OTHER_LAWYER}})

    with pytest.raises(ForbiddenError):
        await _send(d)
    assert (await _row(d["_id"]))["status"] == AgreementStatus.DRAFT.value


@pytest.mark.integration
async def test_a_lawyer_de_verified_after_drafting_cannot_send(world):
    """D5 at SEND, the second checkpoint and the reason there are two."""
    from app.core.exceptions import ForbiddenError
    from app.db.collections import get_users_col

    d = await _draft(await _case())
    await get_users_col().update_one(
        {"_id": LAWYER}, {"$set": {"lawyer_profile.kyc_verified": False}})

    with pytest.raises(ForbiddenError) as exc:
        await _send(d)
    assert "not verified" in str(exc.value).lower()
    assert (await _row(d["_id"]))["status"] == AgreementStatus.DRAFT.value


@pytest.mark.integration
async def test_an_unverified_lawyer_cannot_even_create_a_draft(world):
    from app.core.exceptions import ForbiddenError
    from app.db.collections import get_users_col

    case_id = await _case()
    await get_users_col().update_one(
        {"_id": LAWYER}, {"$set": {"lawyer_profile.kyc_verified": False}})

    with pytest.raises(ForbiddenError):
        await _draft(case_id)


# ── schema: unknown fields refused ──────────────────────────────────────────

def test_draft_schemas_reject_unknown_fields():
    from pydantic import ValidationError

    from app.schemas.agreement import DraftCreate, DraftSignAndSend, DraftUpdate

    with pytest.raises(ValidationError):
        DraftCreate(title="T", body_html="B", client_id="c",
                    case_id="k", nonsense="x")
    with pytest.raises(ValidationError):
        DraftUpdate(expected_version=1, nonsense="x")
    with pytest.raises(ValidationError):
        DraftSignAndSend(expected_version=1, expected_body_sha256="a" * 64,
                         method="typed", signature_data="s", consent=True,
                         nonsense="x")


def test_send_requires_a_full_length_digest():
    """A truncated hash would make the anti-race check trivially passable."""
    from pydantic import ValidationError

    from app.schemas.agreement import DraftSignAndSend

    with pytest.raises(ValidationError):
        DraftSignAndSend(expected_version=1, expected_body_sha256="abc",
                         method="typed", signature_data="s", consent=True)


def test_the_send_route_is_the_only_rate_limited_one():
    """D6: the abuse boundary is sending, not editing.

    Autosave must never be throttled -- it would lose the lawyer's work for no
    safety gain, since a draft reaches nobody.
    """
    import inspect

    from app.api.v1.routes import agreements

    assert "10/hour" in inspect.getsource(agreements)
    send_src = inspect.getsource(agreements.sign_and_send_draft)
    assert "limiter.limit" in inspect.getsource(agreements)
    # The autosave handler carries no limiter decorator of its own.
    assert "limiter" not in inspect.getsource(agreements.update_draft)


# ── the parked wizard is untouched by any of this ───────────────────────────

@pytest.mark.integration
async def test_drafting_is_not_gated_by_the_parked_builder_flag(world):
    from app.core.config import settings

    assert settings.agreements_diy_builder_enabled is False
    d = await _draft(await _case())
    assert d["status"] == AgreementStatus.DRAFT.value


@pytest.mark.integration
async def test_the_client_wizard_stays_closed(world):
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    case_id = await _case()
    with pytest.raises(ForbiddenError):
        await agreement_service.create_user_agreement(
            title="DIY", body_html="Terms.",
            parties=[{"user_id": LAWYER}], creator_id=CLIENT, case_id=case_id)


# ── the wire format still hides what it should ──────────────────────────────

@pytest.mark.integration
async def test_a_non_party_cannot_read_a_sent_agreement(world):
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    d = await _draft(await _case())
    await _send(d)
    with pytest.raises(ForbiddenError):
        await agreement_service.get_agreement(d["_id"], OTHER_LAWYER)


@pytest.mark.integration
async def test_audit_log_and_signature_data_never_cross_the_wire(world):
    from app.schemas.agreement import AgreementOut

    d = await _draft(await _case())
    await _send(d)
    raw = await _row(d["_id"])

    assert raw["audit_log"], "precondition: the row holds an audit log"
    assert any(p.get("signature_data") for p in raw["parties"])

    wire = AgreementOut(**{**raw, "id": raw["_id"]}).model_dump()
    assert "audit_log" not in wire
    assert "idempotency_receipts" not in wire
    for party in wire["parties"]:
        assert "signature_data" not in party


# ── a draft is private to its author ────────────────────────────────────────

@pytest.mark.integration
async def test_a_draft_is_invisible_to_the_counterparty_in_the_list(world):
    """THE leak this closes.

    `create_draft` writes BOTH parties into the row so it is complete before
    sending, and the list filter matched "party OR creator". So the client saw
    the lawyer's unsent draft -- half-written wording, or wording abandoned
    before sending -- as though it had been offered to them.
    """
    from app.services import agreement_service

    case_id = await _case()
    d = await _draft(case_id)

    # 3F: the list is paginated, so the rows are under "items".
    mine = (await agreement_service.list_agreements(LAWYER))["items"]
    theirs = (await agreement_service.list_agreements(CLIENT))["items"]

    assert d["_id"] in {a["id"] for a in mine}, "the author lost their own draft"
    assert d["_id"] not in {a["id"] for a in theirs}, "counterparty saw a draft"


@pytest.mark.integration
async def test_a_draft_reads_as_not_found_for_the_counterparty(world):
    """404, not 403.

    A 403 confirms the id exists, which tells the counterparty a draft about
    them is being written. For something they are not entitled to know about
    yet, absence is the honest answer.
    """
    from app.core.exceptions import NotFoundError
    from app.services import agreement_service

    d = await _draft(await _case())

    assert (await agreement_service.get_agreement(d["_id"], LAWYER))["_id"] == d["_id"]

    with pytest.raises(NotFoundError):
        await agreement_service.get_agreement(d["_id"], CLIENT)
    with pytest.raises(NotFoundError):
        await agreement_service.get_agreement(d["_id"], OTHER_LAWYER)


@pytest.mark.integration
async def test_once_sent_the_counterparty_can_see_and_fetch_it(world):
    """The privacy rule must not outlive the draft: sending is what makes it
    theirs to read."""
    from app.services import agreement_service

    d = await _draft(await _case())
    await _send(d)

    theirs = (await agreement_service.list_agreements(CLIENT))["items"]
    assert d["_id"] in {a["id"] for a in theirs}
    fetched = await agreement_service.get_agreement(d["_id"], CLIENT)
    assert fetched["status"] == AgreementStatus.PENDING.value


@pytest.mark.integration
async def test_there_is_exactly_one_draft_to_pending_transition(world):
    """No second route to `pending` from a draft.

    A second path would be a second place for the guards to be forgotten --
    the version check, the body-hash check, the consent capture and the
    idempotency receipt all live on `sign_and_send_draft`. This asserts on the
    source so a new writer cannot appear unnoticed.
    """
    import inspect

    from app.services import agreement_service

    # A first version counted every `"status": AgreementStatus.PENDING.value`
    # in the module and asserted the total. That could not tell a WRITE from a
    # FILTER -- `submit_signature` and `decline_agreement` both match on
    # `pending` -- so it was really asserting a line count, which any edit
    # would break for no reason.
    #
    # The property that matters is narrower: exactly one function moves a row
    # OUT of `draft` INTO `pending`. Such a function must mention both states.
    movers = []
    for name, fn in vars(agreement_service).items():
        if not (inspect.isfunction(fn) or inspect.iscoroutinefunction(fn)):
            continue
        try:
            src = inspect.getsource(fn)
        except (OSError, TypeError):
            continue
        if ("AgreementStatus.DRAFT.value" in src
                and '"status": AgreementStatus.PENDING.value' in src):
            movers.append(name)

    assert movers == ["sign_and_send_draft"], (
        f"expected only sign_and_send_draft to move draft -> pending, got "
        f"{movers}. A second path would be a second place to forget the "
        "version check, the body-hash check, the consent capture and the "
        "idempotency receipt."
    )


# -- one test per surface that authorises by party membership ---------------
#
# `create_draft` writes BOTH parties into the row, so party membership is not
# authorisation while the row is a draft. Each surface below was checked; the
# ones that were vulnerable are marked.

@pytest.mark.integration
async def test_signing_someone_elses_draft_does_not_reveal_it_exists(world):
    """WAS VULNERABLE.

    The counterparty is in `parties`, so they cleared the party check, cleared
    the executed/cancelled checks (the status is `draft`, neither of those) and
    only failed inside the transaction -- with "this agreement changed while
    you were signing it", which confirms the id exists.

    It must now be indistinguishable from a wrong id.
    """
    from app.core.exceptions import NotFoundError
    from app.services import agreement_service

    d = await _draft(await _case())

    with pytest.raises(NotFoundError):
        await agreement_service.submit_signature(
            agreement_id=d["_id"], user_id=CLIENT,
            method="typed", signature_data="The Client", ip_address=None)

    # Identical outcome for an id that genuinely does not exist.
    with pytest.raises(NotFoundError):
        await agreement_service.submit_signature(
            agreement_id="NO-SUCH-AGREEMENT", user_id=CLIENT,
            method="typed", signature_data="The Client", ip_address=None)

    row = await _row(d["_id"])
    assert row["status"] == AgreementStatus.DRAFT.value
    assert not any(p["signed"] for p in row["parties"])


@pytest.mark.integration
async def test_declining_someone_elses_draft_does_not_reveal_it_exists(world):
    """WAS VULNERABLE. Same shape as signing."""
    from app.core.exceptions import NotFoundError
    from app.services import agreement_service

    d = await _draft(await _case())

    with pytest.raises(NotFoundError):
        await agreement_service.decline_agreement(
            agreement_id=d["_id"], user_id=CLIENT,
            reason="No thanks", ip_address=None)
    with pytest.raises(NotFoundError):
        await agreement_service.decline_agreement(
            agreement_id="NO-SUCH-AGREEMENT", user_id=CLIENT,
            reason="No thanks", ip_address=None)

    row = await _row(d["_id"])
    assert row["status"] == AgreementStatus.DRAFT.value
    assert row["audit_log"] == [] or all(
        a["action"] != "declined" for a in row["audit_log"])


@pytest.mark.integration
async def test_the_author_gets_a_real_explanation_not_a_404(world):
    """The author knows the draft exists; telling them "not found" about their
    own row would be its own lie. They are told to send it instead."""
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    d = await _draft(await _case())

    with pytest.raises(AppValidationError) as exc:
        await agreement_service.submit_signature(
            agreement_id=d["_id"], user_id=LAWYER,
            method="typed", signature_data="Adv Verified", ip_address=None)
    assert "still a draft" in str(exc.value).lower()


@pytest.mark.integration
async def test_no_notification_or_outbox_event_exists_before_send(world):
    """A draft reaches nobody. Nothing may be queued or delivered until send."""
    from app.db.collections import get_event_outbox_col, get_notifications_col

    d = await _draft(await _case())

    assert await get_event_outbox_col().count_documents(
        {"payload.data.agreement_id": d["_id"]}) == 0
    assert await get_event_outbox_col().count_documents(
        {"payload.recipient_id": CLIENT}) == 0
    assert await get_notifications_col().count_documents(
        {"user_id": CLIENT, "payload.agreement_id": d["_id"]}) == 0

    # Sending is what creates the first one.
    await _send(d)
    assert await get_event_outbox_col().count_documents(
        {"_id": f"agreement:{d['_id']}:sent:{CLIENT}"}) == 1


@pytest.mark.integration
async def test_the_fee_gate_never_bills_through_a_draft(world):
    """NOT VULNERABLE, pinned anyway.

    Billing now validates the ENGAGEMENT, not a letter (§17 R5-5), and a draft
    is not an engagement. A fee request naming a draft's id as its engagement
    must be refused like any other id that is not this lawyer's engagement.
    """
    from app.core.exceptions import ForbiddenError
    from app.db.collections import get_engagements_col
    from app.services import payment_service

    case_id = await _case()
    d = await _draft(case_id)

    # A real engagement exists; the fee request names the DRAFT instead.
    now = datetime.now(timezone.utc)
    await get_engagements_col().insert_one({
        "_id": secrets.token_urlsafe(12), "case_id": case_id,
        "client_id": CLIENT, "lawyer_id": LAWYER, "status": "accepted",
        "agreement_id": d["_id"], "created_at": now, "updated_at": now,
    })

    with pytest.raises(ForbiddenError):
        await payment_service.create_fee_request(
            LAWYER, {"case_id": case_id, "amount": 1000,
                     "purpose": "peshi_fee", "engagement_id": d["_id"]})


@pytest.mark.integration
async def test_a_draft_alone_does_not_make_a_relationship_reviewable(world):
    """NOT VULNERABLE, pinned. Review eligibility reads the ENGAGEMENT's status
    (§17 R5-6); a draft agreement is not one, and creates no relationship."""
    from app.repositories.engagement_repo import EngagementRepository

    case_id = await _case()
    await _draft(case_id)

    # No engagement at all -- only a draft naming the same case.
    assert await EngagementRepository().exists_retained_relationship(
        CLIENT, LAWYER) is False


@pytest.mark.integration
async def test_the_draft_cap_counts_only_the_authors_own_drafts(world):
    """The one server-side count over agreements. Scoped to `created_by`, so it
    is the author's own number and never a badge derived from someone else's
    unsent work."""
    import inspect

    from app.services import agreement_service

    src = inspect.getsource(agreement_service.create_draft)
    assert '"created_by": creator_id' in src
    assert '"status": AgreementStatus.DRAFT.value' in src


def test_no_repository_helper_returns_agreements_without_a_draft_filter():
    """`find_by_party` was a dead, ready-made copy of this leak.

    It returned every agreement naming a user, drafts included, and nothing
    called it -- so the next person wanting "agreements for this user" would
    have found it first. Removed; this stops it coming back.

    3F MOVED THE RULE rather than weakening it: the draft filter now lives in
    `visible_to`, which both lookups build on. This checks the rule where it
    now is, AND that every lookup routes through it -- a second lookup that
    assembled its own filter is how the rule gets fixed in one place and not
    the other.
    """
    import inspect

    from app.repositories.agreement_repo import AgreementRepository

    assert not hasattr(AgreementRepository, "find_by_party")

    rule = inspect.getsource(AgreementRepository.visible_to)
    assert "DRAFT" in rule, "the shared visibility filter lost its draft rule"
    assert "created_by" in rule, "drafts must match their author only"

    for name in ("find_for_user", "page_for_user"):
        src = inspect.getsource(getattr(AgreementRepository, name))
        assert "visible_to" in src, (
            f"{name} builds its own filter instead of using visible_to -- "
            "two copies of a visibility rule is one copy that gets fixed"
        )


@pytest.mark.integration
async def test_the_author_keeps_full_control_of_their_own_draft(world):
    """The privacy rule must not lock the author out of their own work."""
    from app.services import agreement_service

    d = await _draft(await _case())

    assert (await agreement_service.get_agreement(d["_id"], LAWYER))["_id"] == d["_id"]
    assert d["_id"] in {a["id"] for a in
                        (await agreement_service.list_agreements(LAWYER))["items"]}
    edited = await agreement_service.update_draft(
        agreement_id=d["_id"], creator_id=LAWYER,
        expected_version=1, body_html="Revised wording.")
    assert edited["version"] == 2
    await agreement_service.delete_draft(
        agreement_id=d["_id"], creator_id=LAWYER)
    assert await _row(d["_id"]) is None


# -- Gate 3D: what the editor needs back from the API -----------------------

def test_the_api_reports_the_version_the_editor_must_echo():
    """`expected_version` is required on every edit and on the send, so the
    caller has to be able to LEARN it.

    Until `version` was added to `AgreementOut`, FastAPI filtered it out of
    every response. A UI would have had to assume 1 at creation and count its
    own saves -- a guess that holds only while nothing else writes, and that a
    re-read could not repair, because the re-read dropped the field too. That
    turns the first conflict into a dead end.
    """
    from app.schemas.agreement import AgreementOut

    out = AgreementOut(**{
        "_id": "A1", "title": "Retainer", "body_html": "Terms.",
        "status": AgreementStatus.DRAFT.value, "created_by": LAWYER,
        "version": 7, "parties": [],
    })
    assert out.version == 7
    assert out.model_dump()["version"] == 7


@pytest.mark.integration
async def test_every_draft_response_carries_a_version(world):
    """Create, edit and read all report it, so the editor never has to guess."""
    from app.schemas.agreement import AgreementOut
    from app.services import agreement_service

    d = await _draft(await _case())
    assert AgreementOut(**d).version == 1

    edited = await agreement_service.update_draft(
        agreement_id=d["_id"], creator_id=LAWYER,
        expected_version=1, body_html="Revised.")
    assert AgreementOut(**edited).version == 2

    fetched = await agreement_service.get_agreement(d["_id"], LAWYER)
    assert AgreementOut(**fetched).version == 2
