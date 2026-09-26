"""Phase 1: the parked builder, plain-text bodies, and transactional transitions.

Three separate guarantees, all introduced together because they share a call
path. See AGREEMENTS_REMEDIATION_PLAN.md Phase 1.

  * PARKING. `create_user_agreement` is refused while
    `agreements_diy_builder_enabled` is off, and the refusal lives in the
    SERVICE, not only the route -- a guard a future caller cannot route around.
    `create_pending_engagement_letter` is deliberately NOT gated: engagement
    letters gate all billing and must keep working while the builder is parked.

  * PLAIN TEXT. The body is normalised, never sanitised. Sanitising plain text
    as HTML would rewrite an agreement containing angle brackets, and the
    rewritten text is what gets hashed -- so the evidentiary record would be of
    something the signer never read.

  * ATOMICITY. Sign and decline run in one transaction and fail closed where
    transactions are unavailable. The tests that need a real transaction take
    `mongo_transactional`, which skips on a standalone rather than failing.
"""
from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timezone

import pytest

from app.core.constants import AgreementStatus


# ── parking ──────────────────────────────────────────────────────────────────

async def test_the_user_builder_is_refused_while_parked(monkeypatch):
    """The whole point of the flag, asserted at the service layer.

    The route is not involved. A guard that only exists in the HTTP handler is
    one an internal caller can walk straight past.
    """
    from app.core.config import settings
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    monkeypatch.setattr(settings, "agreements_diy_builder_enabled", False)

    with pytest.raises(ForbiddenError) as exc:
        await agreement_service.create_user_agreement(
            title="NDA", body_html="Some terms.",
            parties=[{"user_id": "X"}], creator_id="Y")

    message = str(exc.value).lower()
    assert "withdrawn" in message or "unavailable" in message
    # It must say what still works, or a client reads it as "agreements are
    # broken" when the ones already shared with them are fine.
    #
    # The copy named "engagement letters" until 2026-09-23. New engagements
    # generate none (AGREEMENTS_PRODUCT_PLAN.md §17 R5-3), so it now names the
    # agreements a client actually has. The REQUIREMENT is unchanged: the
    # refusal has to say what is unaffected.
    assert "unaffected" in message
    assert "read, sign and decline" in message


async def test_parking_refuses_before_touching_the_database(monkeypatch):
    """No party lookup, no insert, nothing -- the refusal is the first thing.

    Both party ids below are unregistered. If the guard ran after resolution
    the error would be about the parties, not about parking, and the user would
    be told to fix something irrelevant.
    """
    from app.core.config import settings
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    monkeypatch.setattr(settings, "agreements_diy_builder_enabled", False)

    with pytest.raises(ForbiddenError):
        await agreement_service.create_user_agreement(
            title="NDA", body_html="Some terms.",
            parties=[{"user_id": "NOBODY-1"}, {"user_id": "NOBODY-2"}],
            creator_id="NOBODY-3")


def test_the_engagement_letter_path_is_not_behind_the_flag():
    """Engagement letters gate billing; parking the builder must not touch them.

    Asserted on the source rather than by running it, because running it needs a
    lawyer, a client, a case and an engagement -- none of which bear on the
    question, which is whether the gate is in this function at all.
    """
    import inspect

    from app.services import agreement_service

    source = inspect.getsource(agreement_service.create_pending_engagement_letter)
    assert "agreements_diy_builder_enabled" not in source

    gated = inspect.getsource(agreement_service.create_user_agreement)
    assert "agreements_diy_builder_enabled" in gated


# ── plain-text bodies ────────────────────────────────────────────────────────

def test_windows_and_unix_line_endings_hash_identically():
    """THE reason normalisation exists.

    Without it `body_sha256` records the submitter's operating system as much as
    their agreement: the same wording typed on Windows and on Linux produces two
    different digests, and a re-upload of identical text looks like tampering.
    """
    from app.services.agreement_service import body_digest, normalise_body

    windows = "Clause 1.\r\nClause 2.\r\n"
    unix = "Clause 1.\nClause 2.\n"

    assert normalise_body(windows) == normalise_body(unix)
    assert body_digest(normalise_body(windows)) == body_digest(normalise_body(unix))


def test_a_lone_carriage_return_is_normalised_too():
    from app.services.agreement_service import normalise_body

    assert normalise_body("a\rb") == "a\nb"


def test_angle_brackets_survive_untouched():
    """The nh3 decision, pinned.

    Sanitising this as HTML would drop or rewrite `<see Schedule A>`, and the
    rewritten text is what would be hashed and signed.
    """
    from app.services.agreement_service import normalise_body

    text = "If X < Y then <see Schedule A> applies & the fee is halved."
    assert normalise_body(text) == text


@pytest.mark.parametrize("bad", ["\x00", "\x07", "\x1b", "\x7f"])
def test_unsafe_control_characters_are_refused_not_stripped(bad):
    """Refused, because stripping would change the text after review.

    A signer bound to text the system silently edited is the same failure as
    sanitising, arriving by a quieter route.
    """
    from app.core.exceptions import AppValidationError
    from app.services.agreement_service import normalise_body

    with pytest.raises(AppValidationError) as exc:
        normalise_body(f"Clause 1.{bad}Clause 2.")
    assert "nothing has been saved" in str(exc.value).lower()


@pytest.mark.parametrize("ok", ["\t", "\n"])
def test_tab_and_newline_are_allowed(ok):
    from app.services.agreement_service import normalise_body

    assert normalise_body(f"a{ok}b") == f"a{ok}b"


def test_an_empty_body_normalises_rather_than_raising():
    from app.services.agreement_service import normalise_body

    assert normalise_body(None) == ""
    assert normalise_body("") == ""


# ── transactional transitions ────────────────────────────────────────────────

@pytest.fixture
async def agreement_parties(mongo_transactional):
    from app.db.collections import get_agreements_col, get_users_col

    users = [
        {"_id": "P1-ALICE", "full_name": "Alice", "role": "client", "email": "a@x.test"},
        {"_id": "P1-BOB", "full_name": "Bob", "role": "client", "email": "b@x.test"},
    ]
    await get_users_col().insert_many(users)
    yield ["P1-ALICE", "P1-BOB"]
    await get_users_col().delete_many({"_id": {"$in": [u["_id"] for u in users]}})
    await get_agreements_col().delete_many({"created_by": "P1-ALICE"})


async def _pending(parties: list[str]) -> str:
    """A pending agreement, inserted directly so the builder flag is irrelevant."""
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    body = "Alice and Bob agree to the attached terms."
    agreement_id = secrets.token_urlsafe(16)
    now = datetime.now(timezone.utc)
    await get_agreements_col().insert_one({
        "_id": agreement_id,
        "title": "Phase 1 Agreement",
        "body_html": body,
        "body_format": agreement_service.BODY_FORMAT_PLAIN_TEXT,
        "body_sha256": agreement_service.body_digest(body),
        "status": AgreementStatus.PENDING.value,
        "parties": [
            {"user_id": u, "full_name": u, "signed": False, "signed_at": None,
             "signature_method": None, "signature_data": None} for u in parties
        ],
        "audit_log": [], "created_by": "P1-ALICE",
        "created_at": now, "updated_at": now,
    })
    return agreement_id


@pytest.mark.integration
async def test_signing_parks_its_notification_in_the_same_transaction(agreement_parties):
    """The commit-gap fix, asserted by its artifact.

    A notification enqueued AFTER commit can be lost to a crash in between: the
    agreement is signed and nobody is ever told. Parked inside the transaction,
    the event and the state change share one fate -- so a committed signature
    always has its event on disk.
    """
    from app.db.collections import get_event_outbox_col
    from app.services import agreement_service

    agreement_id = await _pending(agreement_parties)
    await agreement_service.submit_signature(
        agreement_id=agreement_id, user_id="P1-ALICE",
        method="typed", signature_data="Alice", ip_address=None)

    parked = await get_event_outbox_col().find_one(
        {"_id": f"agreement:{agreement_id}:signed:P1-ALICE:P1-BOB"})
    assert parked is not None, "the counterparty's event was not parked"
    assert parked["destination"] == "notifications"
    assert parked["payload"]["recipient_id"] == "P1-BOB"


@pytest.mark.integration
async def test_the_signer_is_not_notified_of_their_own_signature(agreement_parties):
    from app.db.collections import get_event_outbox_col
    from app.services import agreement_service

    agreement_id = await _pending(agreement_parties)
    await agreement_service.submit_signature(
        agreement_id=agreement_id, user_id="P1-ALICE",
        method="typed", signature_data="Alice", ip_address=None)

    assert await get_event_outbox_col().find_one(
        {"_id": f"agreement:{agreement_id}:signed:P1-ALICE:P1-ALICE"}) is None


@pytest.mark.integration
async def test_concurrent_signatures_execute_the_agreement_exactly_once(agreement_parties):
    """Both parties sign at the same instant.

    Under the previous four-write version this could produce two 'executed'
    notices per party, or an executed status whose classification still
    described one signer. Exactly one executed event per party is the property.
    """
    from app.db.collections import get_agreements_col, get_event_outbox_col
    from app.services import agreement_service

    agreement_id = await _pending(agreement_parties)

    async def sign(uid: str):
        try:
            return await agreement_service.submit_signature(
                agreement_id=agreement_id, user_id=uid,
                method="typed", signature_data=uid, ip_address=None)
        except Exception as exc:  # a lost race is a legitimate outcome
            return exc

    await asyncio.gather(sign("P1-ALICE"), sign("P1-BOB"))

    final = await get_agreements_col().find_one({"_id": agreement_id})
    assert final["status"] == AgreementStatus.EXECUTED.value
    assert all(p["signed"] for p in final["parties"])

    signed_entries = [a for a in final["audit_log"] if a["action"] == "signed"]
    assert len(signed_entries) == 2, "one audit entry per signature, no more"

    for uid in agreement_parties:
        events = await get_event_outbox_col().count_documents(
            {"_id": f"agreement:{agreement_id}:executed:{uid}"})
        assert events == 1, f"{uid} must be told exactly once"


@pytest.mark.integration
async def test_a_concurrent_sign_and_decline_resolve_to_one_terminal_state(agreement_parties):
    """The contradiction the transaction exists to prevent.

    Previously these could interleave into a row carrying a 'signed' entry after
    a 'declined' one -- a record nobody could read. Exactly one wins.
    """
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    agreement_id = await _pending(agreement_parties)

    async def sign():
        try:
            return await agreement_service.submit_signature(
                agreement_id=agreement_id, user_id="P1-ALICE",
                method="typed", signature_data="Alice", ip_address=None)
        except Exception as exc:
            return exc

    async def decline():
        try:
            return await agreement_service.decline_agreement(
                agreement_id=agreement_id, user_id="P1-BOB",
                reason="No", ip_address=None)
        except Exception as exc:
            return exc

    await asyncio.gather(sign(), decline())

    final = await get_agreements_col().find_one({"_id": agreement_id})
    actions = [a["action"] for a in final["audit_log"]]

    # A decline is terminal; a first signature leaves it pending. Both are
    # coherent outcomes -- an incoherent one is a decline followed by a
    # signature, or a cancelled row with no declined entry.
    if final["status"] == AgreementStatus.CANCELLED.value:
        assert "declined" in actions
        assert actions.index("declined") == len(actions) - 1, (
            "nothing may be recorded after the decline that ended it")
    else:
        assert final["status"] == AgreementStatus.PENDING.value
        assert "declined" not in actions


@pytest.mark.integration
async def test_declining_parks_the_counterparty_notice(agreement_parties):
    from app.db.collections import get_event_outbox_col
    from app.services import agreement_service

    agreement_id = await _pending(agreement_parties)
    await agreement_service.decline_agreement(
        agreement_id=agreement_id, user_id="P1-BOB",
        reason="Fee too high", ip_address=None)

    parked = await get_event_outbox_col().find_one(
        {"_id": f"agreement:{agreement_id}:declined:P1-BOB:P1-ALICE"})
    assert parked is not None
    assert "Fee too high" in parked["payload"]["body"]


@pytest.mark.integration
async def test_a_second_decline_is_refused_and_records_nothing(agreement_parties):
    from app.core.exceptions import AppValidationError
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    agreement_id = await _pending(agreement_parties)
    await agreement_service.decline_agreement(
        agreement_id=agreement_id, user_id="P1-BOB", reason=None, ip_address=None)

    with pytest.raises(AppValidationError):
        await agreement_service.decline_agreement(
            agreement_id=agreement_id, user_id="P1-ALICE", reason=None, ip_address=None)

    final = await get_agreements_col().find_one({"_id": agreement_id})
    declines = [a for a in final["audit_log"] if a["action"] == "declined"]
    assert len(declines) == 1, "a refused decline must not append an entry"


@pytest.mark.integration
async def test_the_body_digest_is_stamped_into_every_audit_entry(agreement_parties):
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    agreement_id = await _pending(agreement_parties)
    await agreement_service.submit_signature(
        agreement_id=agreement_id, user_id="P1-ALICE",
        method="typed", signature_data="Alice", ip_address="203.0.113.7",
        # D8: an address is stored only when it can be stood behind. This test
        # is about the DIGEST reaching every entry, so the origin is supplied
        # as verifiable rather than left to the fail-closed default.
        ip_verifiable=True)

    row = await get_agreements_col().find_one({"_id": agreement_id})
    entry = next(a for a in row["audit_log"] if a["action"] == "signed")
    assert entry["body_sha256"] == row["body_sha256"]
    assert entry["ip_address"] == "203.0.113.7"
