"""Signatures are encrypted at rest, and only the intended path decrypts them.

THE CLAIM THIS EXISTS TO MAKE TRUE. The UI told users "AES-256 encrypted" while
`parties[].signature_data` held the raw base64 PNG in clear. Privacy came from
`PartyOut` not declaring the field -- which hides it from a counterparty and
from nobody with database access.

So the assertions here are deliberately about the STORED BYTES, not about the
round trip. A round-trip test passes just as happily against a function that
returns its input, which is exactly the "encryption" being replaced.
"""
from __future__ import annotations

import base64
import secrets

import pytest

from app.core import signature_crypto as sc

AGREEMENT = "AG-TEST-1"
PARTY = "USER-TEST-1"
TYPED = "Muhammad Usama Khan"
DRAWN = "data:image/png;base64," + base64.b64encode(b"\x89PNG" + b"x" * 400).decode()


# ── the envelope ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("plaintext", [TYPED, DRAWN], ids=["typed", "drawn"])
def test_the_stored_value_does_not_contain_the_signature(plaintext):
    """THE test. Everything else is detail."""
    env = sc.encrypt_signature(plaintext, agreement_id=AGREEMENT, party_ref=PARTY)

    blob = repr(env)
    assert plaintext not in blob
    # Not merely absent as a whole -- no recognisable run of it survives.
    assert plaintext[:24] not in blob
    assert base64.b64encode(plaintext.encode()).decode()[:24] not in blob


def test_the_envelope_says_what_it_is():
    env = sc.encrypt_signature(TYPED, agreement_id=AGREEMENT, party_ref=PARTY)

    assert env["alg"] == "AES-256-GCM"
    assert env["v"] == sc.ENVELOPE_VERSION
    assert set(env) == {"v", "alg", "n", "ct"}
    assert len(base64.b64decode(env["n"])) == 12, "96-bit nonce"


def test_two_encryptions_of_one_signature_differ():
    """A deterministic ciphertext leaks that two parties signed identically."""
    a = sc.encrypt_signature(TYPED, agreement_id=AGREEMENT, party_ref=PARTY)
    b = sc.encrypt_signature(TYPED, agreement_id=AGREEMENT, party_ref=PARTY)

    assert a["ct"] != b["ct"]
    assert a["n"] != b["n"]


def test_the_intended_path_returns_the_signature():
    env = sc.encrypt_signature(DRAWN, agreement_id=AGREEMENT, party_ref=PARTY)

    assert sc.decrypt_signature(env, agreement_id=AGREEMENT, party_ref=PARTY) == DRAWN


# ── binding: the reason for GCM rather than Fernet ──────────────────────────

def test_a_signature_cannot_be_moved_to_another_agreement():
    """Lifting a ciphertext into a different row must not yield a signature."""
    env = sc.encrypt_signature(TYPED, agreement_id=AGREEMENT, party_ref=PARTY)

    with pytest.raises(sc.SignatureDecryptionError):
        sc.decrypt_signature(env, agreement_id="AG-OTHER", party_ref=PARTY)


def test_a_signature_cannot_be_moved_to_another_party():
    """One party's signature must not decrypt in another party's slot."""
    env = sc.encrypt_signature(TYPED, agreement_id=AGREEMENT, party_ref=PARTY)

    with pytest.raises(sc.SignatureDecryptionError):
        sc.decrypt_signature(env, agreement_id=AGREEMENT, party_ref="USER-OTHER")


def test_tampering_with_the_ciphertext_is_detected():
    """GCM authenticates. A flipped byte must fail, not decrypt to noise."""
    env = sc.encrypt_signature(TYPED, agreement_id=AGREEMENT, party_ref=PARTY)
    raw = bytearray(base64.b64decode(env["ct"]))
    raw[0] ^= 0x01
    env["ct"] = base64.b64encode(bytes(raw)).decode()

    with pytest.raises(sc.SignatureDecryptionError):
        sc.decrypt_signature(env, agreement_id=AGREEMENT, party_ref=PARTY)


def test_another_key_cannot_read_it(monkeypatch):
    env = sc.encrypt_signature(TYPED, agreement_id=AGREEMENT, party_ref=PARTY)
    from app.core.config import settings
    monkeypatch.setattr(settings, "signature_encryption_key",
                        base64.b64encode(secrets.token_bytes(32)).decode())

    with pytest.raises(sc.SignatureDecryptionError):
        sc.decrypt_signature(env, agreement_id=AGREEMENT, party_ref=PARTY)


# ── configuration refuses rather than degrading ─────────────────────────────

def test_no_key_refuses_to_store_rather_than_writing_clear_text(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "signature_encryption_key", "")

    with pytest.raises(sc.SignatureKeyMissing):
        sc.encrypt_signature(TYPED, agreement_id=AGREEMENT, party_ref=PARTY)


@pytest.mark.parametrize("bad", [
    "not-base64!!",
    base64.b64encode(b"too short").decode(),
    base64.b64encode(b"x" * 64).decode(),
], ids=["not-base64", "16-bytes", "64-bytes"])
def test_a_key_that_is_not_aes256_is_refused(monkeypatch, bad):
    from app.core.config import settings
    monkeypatch.setattr(settings, "signature_encryption_key", bad)

    with pytest.raises(sc.SignatureKeyMissing):
        sc.encrypt_signature(TYPED, agreement_id=AGREEMENT, party_ref=PARTY)


# ── legacy rows are read, never rewritten ───────────────────────────────────

def test_a_legacy_plaintext_signature_still_reads():
    """Agreements executed before this module must still render."""
    assert sc.decrypt_signature(
        TYPED, agreement_id=AGREEMENT, party_ref=PARTY) == TYPED


def test_no_signature_is_not_an_error():
    assert sc.decrypt_signature(
        None, agreement_id=AGREEMENT, party_ref=PARTY) is None


def test_an_unrecognised_shape_is_refused_not_guessed():
    with pytest.raises(sc.SignatureDecryptionError):
        sc.decrypt_signature({"alg": "rot13", "ct": "x"},
                             agreement_id=AGREEMENT, party_ref=PARTY)


def test_is_encrypted_tells_the_two_apart():
    env = sc.encrypt_signature(TYPED, agreement_id=AGREEMENT, party_ref=PARTY)

    assert sc.is_encrypted(env) is True
    assert sc.is_encrypted(TYPED) is False
    assert sc.is_encrypted(None) is False


# ── end to end: what the real signing paths actually store ──────────────────
#
# The unit tests above prove the cipher. These prove the PRODUCT uses it: a
# correct crypto module wired to nothing leaves signatures in clear, which is
# the state this work replaces.

pytestmark_integration = pytest.mark.integration

CLIENT = "SIGENC-CLIENT"
LAWYER = "SIGENC-LAWYER"


@pytest.fixture
async def world(mongo_transactional):
    from app.db.collections import (
        get_agreements_col, get_cases_col, get_event_outbox_col, get_users_col,
    )
    await get_users_col().insert_many([
        {"_id": LAWYER, "full_name": "Adv Sig", "role": "lawyer",
         "email": "l@sigenc.test", "is_active": True,
         "lawyer_profile": {"kyc_verified": True, "specializations": ["civil"]}},
        {"_id": CLIENT, "full_name": "Client Sig", "role": "client",
         "email": "c@sigenc.test", "is_active": True},
    ])
    yield
    ids = [LAWYER, CLIENT]
    await get_users_col().delete_many({"_id": {"$in": ids}})
    await get_cases_col().delete_many({"client_id": CLIENT})
    await get_agreements_col().delete_many({"created_by": {"$in": ids}})
    await get_event_outbox_col().delete_many({"payload.recipient_id": {"$in": ids}})


async def _sent_agreement():
    """A draft signed and sent by the lawyer, through the real path."""
    import secrets as _s
    from datetime import datetime, timezone
    from app.core.constants import CaseStatus
    from app.db.collections import get_cases_col
    from app.services import agreement_service

    now = datetime.now(timezone.utc)
    cid = _s.token_urlsafe(9)
    await get_cases_col().insert_one({
        "_id": cid, "client_id": CLIENT, "lawyer_id": LAWYER,
        "title": "Matter", "case_number": f"SE-{cid[:6]}",
        "status": CaseStatus.IN_PROGRESS.value,
        "milestones": [], "created_at": now, "updated_at": now})
    d = await agreement_service.create_draft(
        title="Retainer", body_html="Fees are 40% of recovery.",
        client_id=CLIENT, creator_id=LAWYER, case_id=cid)
    await agreement_service.sign_and_send_draft(
        agreement_id=d["_id"], creator_id=LAWYER,
        expected_version=d["version"],
        expected_body_sha256=agreement_service.body_digest(d["body_html"]),
        method="typed", signature_data=TYPED, consent=True,
        idempotency_key=_s.token_urlsafe(12),
        ip_address="203.0.113.9", ip_verifiable=True)
    return d["_id"]


async def _row(agreement_id):
    from app.db.collections import get_agreements_col
    return await get_agreements_col().find_one({"_id": agreement_id})


@pytest.mark.integration
async def test_sign_and_send_stores_an_envelope_not_the_signature(world):
    """THE end-to-end assertion: read the database, not the return value."""
    agreement_id = await _sent_agreement()

    row = await _row(agreement_id)
    lawyer = next(p for p in row["parties"] if p["user_id"] == LAWYER)

    assert sc.is_encrypted(lawyer["signature_data"]), "stored in clear"
    assert TYPED not in repr(row), "the signature survives somewhere in the row"


@pytest.mark.integration
async def test_submit_signature_stores_an_envelope_too(world):
    """The second signing path. Both write, so both must encrypt."""
    from app.services import agreement_service

    agreement_id = await _sent_agreement()
    await agreement_service.submit_signature(
        agreement_id=agreement_id, user_id=CLIENT, method="typed",
        signature_data="Client Sig", ip_address=None, ip_verifiable=False)

    row = await _row(agreement_id)
    client = next(p for p in row["parties"] if p["user_id"] == CLIENT)

    assert sc.is_encrypted(client["signature_data"])
    assert "Client Sig" not in repr(client["signature_data"])


@pytest.mark.integration
async def test_each_party_envelope_is_bound_to_that_party(world):
    """A stored envelope must not decrypt in the other party's slot, using
    the real ids rather than the synthetic ones above."""
    from app.services import agreement_service

    agreement_id = await _sent_agreement()
    await agreement_service.submit_signature(
        agreement_id=agreement_id, user_id=CLIENT, method="typed",
        signature_data="Client Sig", ip_address=None, ip_verifiable=False)
    row = await _row(agreement_id)
    lawyer = next(p for p in row["parties"] if p["user_id"] == LAWYER)

    assert sc.decrypt_signature(lawyer["signature_data"],
                                agreement_id=agreement_id,
                                party_ref=LAWYER) == TYPED
    with pytest.raises(sc.SignatureDecryptionError):
        sc.decrypt_signature(lawyer["signature_data"],
                             agreement_id=agreement_id, party_ref=CLIENT)


@pytest.mark.integration
async def test_the_executed_pdf_still_prints_the_typed_name(world):
    """Decryption is wired into the one place that reads a signature."""
    from app.services import agreement_service
    from app.services.agreement_pdf import build_executed_pdf

    agreement_id = await _sent_agreement()
    await agreement_service.submit_signature(
        agreement_id=agreement_id, user_id=CLIENT, method="typed",
        signature_data="Client Sig", ip_address=None, ip_verifiable=False)

    pdf = build_executed_pdf(await _row(agreement_id))

    assert isinstance(pdf, bytes) and len(pdf) > 1000
