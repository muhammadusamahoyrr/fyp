"""Agreement generation — the module's first tests.

Nothing under tests/ referenced `agreement_service` before this file. A name
collision hid that: tests/test_agreement.py passes 16 tests against
app/services/AGREEMENT.py, the Krippendorff alpha module for inter-annotator
agreement. Different file, different subject. This one is named for the service
so the collision cannot recur.

What is covered, and why each one exists:

  * the ETO classification race — it was last-writer-wins while its own comment
    claimed "first signature method", so a canvas signer plus a typed signer
    produced a legal characterisation that depended on signing ORDER;
  * the body digest — the audit log proved that someone signed and from which
    IP, but never WHAT, so a later edit to body_html would be undetectable;
  * declining — AgreementStatus.CANCELLED and the UI's "Rejected" label both
    existed with no route that could ever write that value;
  * input bounds — signature_data is base64 image data written straight into a
    Mongo subdocument and had no max_length at all.

The pure-logic tests run everywhere. The ones that touch Mongo are marked
integration and skip cleanly when it is unreachable (see tests/conftest.py).
"""
import pytest

from app.core.constants import AgreementStatus, SignatureMethod
from app.services.agreement_service import (
    ETO_CLASSIFICATION,
    _derive_eto,
    body_digest,
)


def _party(uid: str, method: str | None = None, signed: bool = True) -> dict:
    return {"user_id": uid, "full_name": uid.title(), "signed": signed,
            "signature_method": method}


# ── ETO classification: the race (fix 15) ────────────────────────────────────

def test_mixed_methods_classify_the_same_in_either_signing_order():
    """THE regression test. Under last-writer-wins these two disagreed."""
    canvas_then_typed = _derive_eto([
        _party("alice", SignatureMethod.CANVAS.value),
        _party("bob", SignatureMethod.TYPED.value),
    ])
    typed_then_canvas = _derive_eto([
        _party("bob", SignatureMethod.TYPED.value),
        _party("alice", SignatureMethod.CANVAS.value),
    ])

    assert canvas_then_typed == typed_then_canvas


def test_mixed_methods_take_the_weakest_signature():
    """An agreement is only as strong as its weakest signature."""
    result = _derive_eto([
        _party("alice", SignatureMethod.CANVAS.value),
        _party("bob", SignatureMethod.TYPED.value),
    ])

    assert result == ETO_CLASSIFICATION[SignatureMethod.TYPED]


def test_all_canvas_stays_advanced():
    result = _derive_eto([
        _party("alice", SignatureMethod.CANVAS.value),
        _party("bob", SignatureMethod.CANVAS.value),
    ])

    assert result == ETO_CLASSIFICATION[SignatureMethod.CANVAS]


def test_unsigned_parties_do_not_count_toward_the_classification():
    """A pending counterparty must not drag the classification anywhere."""
    result = _derive_eto([
        _party("alice", SignatureMethod.CANVAS.value, signed=True),
        _party("bob", None, signed=False),
    ])

    assert result == ETO_CLASSIFICATION[SignatureMethod.CANVAS]


def test_no_signatures_yet_has_no_classification():
    assert _derive_eto([_party("alice", None, signed=False)]) is None


def test_an_unknown_method_degrades_instead_of_ranking_as_advanced():
    """A raw dict index would KeyError here; ranking it high would silently
    overstate the signature's legal weight. It must rank below every known
    method and label itself unclassified."""
    result = _derive_eto([
        _party("alice", SignatureMethod.CANVAS.value),
        _party("mystery", "some_future_method"),
    ])

    assert result is not None
    assert "Unclassified" in result


def test_a_missing_method_does_not_raise():
    assert _derive_eto([_party("alice", None, signed=True)]) is not None


# ── body digest: what was signed (fix 14) ────────────────────────────────────

def test_digest_is_stable_for_the_same_body():
    assert body_digest("<p>Terms</p>") == body_digest("<p>Terms</p>")


def test_digest_changes_when_a_single_character_changes():
    """The whole point: an edit after signing must be detectable."""
    assert body_digest("Pay PKR 100,000") != body_digest("Pay PKR 900,000")


def test_digest_handles_an_empty_body():
    assert body_digest("") == body_digest(None or "")


# ── input bounds (fix 17) ────────────────────────────────────────────────────

def test_signature_data_is_bounded():
    from pydantic import ValidationError

    from app.schemas.agreement import _MAX_SIGNATURE, SignatureSubmit

    with pytest.raises(ValidationError):
        SignatureSubmit(method=SignatureMethod.CANVAS,
                        signature_data="A" * (_MAX_SIGNATURE + 1))


def test_a_realistic_signature_still_fits():
    from app.schemas.agreement import SignatureSubmit

    # ~60 KB base64 PNG — a comfortably large drawn signature
    assert SignatureSubmit(method=SignatureMethod.CANVAS, signature_data="A" * 60_000)


def test_empty_signature_is_rejected():
    from pydantic import ValidationError

    from app.schemas.agreement import SignatureSubmit

    with pytest.raises(ValidationError):
        SignatureSubmit(method=SignatureMethod.TYPED, signature_data="")


def test_title_and_body_are_bounded():
    from pydantic import ValidationError

    from app.schemas.agreement import _MAX_BODY, _MAX_TITLE, AgreementCreate

    with pytest.raises(ValidationError):
        AgreementCreate(title="T" * (_MAX_TITLE + 1), body_html="x", party_ids=[])
    with pytest.raises(ValidationError):
        AgreementCreate(title="T", body_html="x" * (_MAX_BODY + 1), party_ids=[])


def test_decline_reason_is_optional_but_bounded():
    from pydantic import ValidationError

    from app.schemas.agreement import AgreementDecline

    assert AgreementDecline().reason is None
    assert AgreementDecline(reason="Terms are unacceptable").reason
    with pytest.raises(ValidationError):
        AgreementDecline(reason="x" * 2001)


# ── the signature payload never leaks (pre-existing property, pinned) ────────

def test_party_out_drops_the_raw_signature_blob():
    from app.schemas.agreement import PartyOut

    out = PartyOut(user_id="u1", full_name="Ali", signed=True,
                   signed_at=None, signature_method="canvas")

    assert "signature_data" not in out.model_dump()


# ── service behaviour (needs Mongo) ──────────────────────────────────────────

@pytest.fixture
async def two_users(mongo):
    from app.db.collections import get_users_col

    users = [
        {"_id": "AG-ALICE", "full_name": "Alice", "role": "client", "email": "a@x.test"},
        {"_id": "AG-BOB", "full_name": "Bob", "role": "client", "email": "b@x.test"},
    ]
    await get_users_col().insert_many(users)
    yield ["AG-ALICE", "AG-BOB"]
    await get_users_col().delete_many({"_id": {"$in": ["AG-ALICE", "AG-BOB"]}})


async def _make(parties, creator="AG-ALICE", body="<p>Original terms</p>"):
    from app.services import agreement_service

    return await agreement_service.create_agreement(
        title="Test Agreement", body_html=body,
        parties=[{"user_id": p} for p in parties], creator_id=creator)


@pytest.mark.integration
async def test_creation_stores_the_body_digest(two_users):
    doc = await _make(two_users)

    assert doc["body_sha256"] == body_digest("<p>Original terms</p>")


@pytest.mark.integration
async def test_creation_stamps_the_digest_into_the_audit_log(two_users):
    doc = await _make(two_users)

    assert doc["audit_log"][0]["body_sha256"] == doc["body_sha256"]


@pytest.mark.integration
async def test_signing_stamps_the_digest_into_the_audit_entry(two_users):
    from app.services import agreement_service

    doc = await _make(two_users)
    signed = await agreement_service.submit_signature(
        agreement_id=doc["_id"], user_id="AG-ALICE",
        method="canvas", signature_data="sig", ip_address="1.2.3.4")

    entry = [e for e in signed["audit_log"] if e["action"] == "signed"][0]
    assert entry["body_sha256"] == doc["body_sha256"]


@pytest.mark.integration
async def test_a_single_party_agreement_is_rejected(two_users):
    from app.core.exceptions import AppValidationError

    with pytest.raises(AppValidationError):
        await _make(["AG-ALICE"])


@pytest.mark.integration
async def test_an_unregistered_party_is_rejected(two_users):
    from app.core.exceptions import AppValidationError

    with pytest.raises(AppValidationError):
        await _make(["AG-ALICE", "NOBODY-AT-ALL"])


@pytest.mark.integration
async def test_a_party_cannot_sign_twice(two_users):
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    doc = await _make(two_users)
    await agreement_service.submit_signature(
        agreement_id=doc["_id"], user_id="AG-ALICE",
        method="typed", signature_data="Alice", ip_address=None)

    with pytest.raises(AppValidationError):
        await agreement_service.submit_signature(
            agreement_id=doc["_id"], user_id="AG-ALICE",
            method="typed", signature_data="Alice", ip_address=None)


@pytest.mark.integration
async def test_a_non_party_cannot_sign(two_users):
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    doc = await _make(two_users)

    with pytest.raises(ForbiddenError):
        await agreement_service.submit_signature(
            agreement_id=doc["_id"], user_id="AG-BOB-IMPOSTER",
            method="typed", signature_data="x", ip_address=None)


@pytest.mark.integration
async def test_mixed_methods_persist_the_weakest_classification(two_users):
    """End-to-end version of the race test, through the real signing path."""
    from app.services import agreement_service

    doc = await _make(two_users)
    await agreement_service.submit_signature(
        agreement_id=doc["_id"], user_id="AG-ALICE",
        method="canvas", signature_data="drawn", ip_address=None)
    final = await agreement_service.submit_signature(
        agreement_id=doc["_id"], user_id="AG-BOB",
        method="typed", signature_data="Bob", ip_address=None)

    assert final["eto_classification"] == ETO_CLASSIFICATION[SignatureMethod.TYPED]
    assert final["status"] == AgreementStatus.EXECUTED.value


# ── declining (fix 16) ────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_declining_cancels_the_agreement(two_users):
    from app.services import agreement_service

    doc = await _make(two_users)
    out = await agreement_service.decline_agreement(
        agreement_id=doc["_id"], user_id="AG-BOB",
        reason="Terms are unacceptable", ip_address="9.9.9.9")

    assert out["status"] == AgreementStatus.CANCELLED.value


@pytest.mark.integration
async def test_declining_records_who_what_and_why(two_users):
    from app.services import agreement_service

    doc = await _make(two_users)
    out = await agreement_service.decline_agreement(
        agreement_id=doc["_id"], user_id="AG-BOB",
        reason="Terms are unacceptable", ip_address="9.9.9.9")

    entry = [e for e in out["audit_log"] if e["action"] == "declined"][0]
    assert entry["actor_id"] == "AG-BOB"
    assert entry["reason"] == "Terms are unacceptable"
    assert entry["ip_address"] == "9.9.9.9"
    assert entry["body_sha256"] == doc["body_sha256"]


@pytest.mark.integration
async def test_declining_without_a_reason_is_allowed(two_users):
    from app.services import agreement_service

    doc = await _make(two_users)
    out = await agreement_service.decline_agreement(
        agreement_id=doc["_id"], user_id="AG-BOB", reason=None, ip_address=None)

    entry = [e for e in out["audit_log"] if e["action"] == "declined"][0]
    assert entry["reason"] is None


@pytest.mark.integration
async def test_a_non_party_cannot_decline(two_users):
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    doc = await _make(two_users)

    with pytest.raises(ForbiddenError):
        await agreement_service.decline_agreement(
            agreement_id=doc["_id"], user_id="SOMEONE-ELSE",
            reason=None, ip_address=None)


@pytest.mark.integration
async def test_an_executed_agreement_cannot_be_declined(two_users):
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    doc = await _make(two_users)
    for uid in two_users:
        await agreement_service.submit_signature(
            agreement_id=doc["_id"], user_id=uid,
            method="typed", signature_data=uid, ip_address=None)

    with pytest.raises(AppValidationError):
        await agreement_service.decline_agreement(
            agreement_id=doc["_id"], user_id="AG-BOB", reason=None, ip_address=None)


@pytest.mark.integration
async def test_declining_twice_is_refused(two_users):
    """Not idempotent housekeeping: a second decline would append another audit
    entry and re-notify every party about a deal that was already off."""
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    doc = await _make(two_users)
    await agreement_service.decline_agreement(
        agreement_id=doc["_id"], user_id="AG-BOB", reason=None, ip_address=None)

    with pytest.raises(AppValidationError):
        await agreement_service.decline_agreement(
            agreement_id=doc["_id"], user_id="AG-BOB", reason=None, ip_address=None)


@pytest.mark.integration
async def test_a_declined_agreement_cannot_then_be_signed(two_users):
    """Introducing a second terminal state means the signing path has to learn
    about it. Signing after a decline would push the agreement back toward
    executed and leave a 'signed' audit entry after a 'declined' one."""
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    doc = await _make(two_users)
    await agreement_service.decline_agreement(
        agreement_id=doc["_id"], user_id="AG-BOB", reason=None, ip_address=None)

    with pytest.raises(AppValidationError):
        await agreement_service.submit_signature(
            agreement_id=doc["_id"], user_id="AG-ALICE",
            method="typed", signature_data="Alice", ip_address=None)

    after = await agreement_service.get_agreement(doc["_id"], "AG-ALICE")
    assert after["status"] == AgreementStatus.CANCELLED.value
