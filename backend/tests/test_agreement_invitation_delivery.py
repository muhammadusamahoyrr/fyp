"""Does the second signer actually get something they can act on?

THE QUESTION THIS FILE ANSWERS. An agreement with two other signers has two
completely different delivery paths, and only one of them is a notification:

  * a REGISTERED signer is notified in-app and opens the agreement from their
    own Agreements page -- no link, because they have an account;
  * an INVITED signer has no account and no inbox this product controls, so the
    only thing that can ever reach them is the raw invitation token, and that
    token exists in readable form exactly once: in this response.

`test_agreement_external_signers.py` proves the SERVICE returns that token.
What it cannot prove is that the token survives the route -- and the route is
where a token is most easily lost, because `response_model` silently drops any
field the model does not declare. That is exactly what happened before
`AgreementCreated` existed: the route declared `AgreementOut`, which has no
token field, so the service minted an invitation, stored its hash, and FastAPI
dropped the only copy of the token on the way out. The invitation was real,
recorded in the audit log, and impossible for anyone to use.

So these go over HTTP, through the real dependency graph and the real response
model.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.constants import CaseStatus

pytestmark = pytest.mark.integration

GUEST_EMAIL = "second.signer@example.pk"


@pytest.fixture
async def world(mongo_transactional, monkeypatch):
    """A lawyer, their client on a live case, and a third registered user."""
    from app.core.config import settings
    from app.db.collections import (
        get_agreements_col, get_cases_col, get_event_outbox_col, get_users_col,
    )

    monkeypatch.setattr(settings, "agreements_diy_builder_enabled", True)

    tag = secrets.token_hex(4)
    lawyer, client, third = f"IV-L-{tag}", f"IV-C-{tag}", f"IV-T-{tag}"
    now = datetime.now(timezone.utc)

    await get_users_col().insert_many([
        {"_id": lawyer, "full_name": "Adv Sender", "role": "lawyer",
         "email": f"l-{tag}@iv.pk", "is_active": True,
         "lawyer_profile": {"kyc_verified": True, "specializations": ["civil"]}},
        {"_id": client, "full_name": "The Client", "role": "client",
         "email": f"c-{tag}@iv.pk", "is_active": True},
        {"_id": third, "full_name": "Third Signer", "role": "client",
         "email": f"t-{tag}@iv.pk", "is_active": True},
    ])

    case_id = f"IV-CASE-{tag}"
    await get_cases_col().insert_one({
        "_id": case_id, "client_id": client, "lawyer_id": lawyer,
        "title": "A matter", "case_number": f"IV-{tag}",
        "status": CaseStatus.IN_PROGRESS.value,
        "milestones": [], "created_at": now, "updated_at": now})

    yield {"lawyer": lawyer, "client": client, "third": third,
           "case_id": case_id, "tag": tag}

    ids = [lawyer, client, third]
    await get_users_col().delete_many({"_id": {"$in": ids}})
    await get_cases_col().delete_many({"_id": case_id})
    await get_agreements_col().delete_many({"created_by": {"$in": ids}})
    await get_event_outbox_col().delete_many(
        {"payload.recipient_id": {"$in": ids}})


@pytest.fixture(autouse=True)
def _clear_overrides():
    from app.main import app
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _no_send_throttle():
    """The send limit is 10/hour and every test here sends.

    Left on, the eleventh request in the file gets a 429 and the failure looks
    like a delivery bug rather than the limiter doing its job -- which is how
    the first run of this file read. The limit itself is a property of the
    route decorator (D6, checklist P10); what these tests are about is what the
    response carries, so the throttle is off for the duration and restored
    after.
    """
    from app.core.rate_limit import limiter

    was = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = was


def _as(user_id: str, role: str = "lawyer"):
    from app.dependencies import get_current_user, require_lawyer
    from app.main import app

    who = {"_id": user_id, "role": role}
    app.dependency_overrides[get_current_user] = lambda: who
    app.dependency_overrides[require_lawyer] = lambda: who
    return AsyncClient(transport=ASGITransport(app=app),
                       base_url="http://test/api/v1")


def _anon():
    """No signed-in user at all — an invited signer has no account.

    THE OVERRIDES ARE CLEARED FIRST. `_send` signs in as the lawyer to create
    the agreement, and those overrides live on the app until the autouse
    fixture tears them down after the test -- so without this, "anonymous"
    requests were still arriving authenticated as the sender. That is what
    turned the shadowed `/invitation/sign` route into a plausible-looking 404
    instead of the 401 it would otherwise have been.
    """
    from app.main import app

    app.dependency_overrides.clear()
    return AsyncClient(transport=ASGITransport(app=app),
                       base_url="http://test/api/v1")


async def _send(world, parties):
    """Create-sign-send over HTTP, returning the parsed response body.

    The id comes back as `_id`, not `id`: FastAPI serialises a response model
    with `by_alias=True`, and `AgreementOut.id` is aliased from `_id`. The
    frontend reads `a.id || a._id` for exactly this reason.
    """
    async with _as(world["lawyer"]) as http:
        r = await http.post("/agreements",
                            headers={"Idempotency-Key": secrets.token_urlsafe(12)},
                            json={"title": "Retainer",
                                  "body_html": "Fees are 40% of recovery.",
                                  "party_ids": parties,
                                  "case_id": world["case_id"],
                                  "method": "typed",
                                  "signature_data": "Adv Sender",
                                  "consent": True})
    assert r.status_code == 200, r.text
    return r.json()


# ── the invited signer ──────────────────────────────────────────────────────

async def test_the_response_carries_a_token_for_the_invited_signer(world):
    body = await _send(world, [{"user_id": world["client"]},
                               {"email": GUEST_EMAIL, "full_name": "A Guest"}])

    tokens = body.get("invitation_tokens_do_not_store")
    assert tokens, (
        "the route returned no invitation token, so nothing can ever reach "
        "the invited signer — this is the response_model dropping it")
    assert len(tokens) == 1


async def test_the_token_is_keyed_to_a_party_in_the_same_response(world):
    """The sender has to know WHICH signer each link belongs to.

    The builder joins these two on `party_id`; if the key did not appear in
    `parties`, every link would be labelled "Invited signer" with no address.
    """
    body = await _send(world, [{"user_id": world["client"]},
                               {"email": GUEST_EMAIL, "full_name": "A Guest"}])

    (party_id, _token), = body["invitation_tokens_do_not_store"].items()
    match = [p for p in body["parties"] if p.get("party_id") == party_id]

    assert len(match) == 1
    assert match[0]["email"] == GUEST_EMAIL
    assert match[0]["external"] is True
    assert match[0]["identity_verified"] is False


async def test_the_token_actually_opens_the_agreement(world):
    """The whole point: the thing handed to the sender has to WORK."""
    body = await _send(world, [{"user_id": world["client"]},
                               {"email": GUEST_EMAIL, "full_name": "A Guest"}])
    (_pid, token), = body["invitation_tokens_do_not_store"].items()

    async with _anon() as http:
        r = await http.post("/agreements/invitation/view", json={"token": token})

    assert r.status_code == 200, r.text
    view = r.json()
    assert view["title"] == "Retainer"
    assert view["body_html"] == "Fees are 40% of recovery."
    assert view["you"]["email"] == GUEST_EMAIL
    assert view["you"]["identity_verified"] is False


async def test_the_invited_signer_can_sign_with_it(world):
    body = await _send(world, [{"user_id": world["client"]},
                               {"email": GUEST_EMAIL, "full_name": "A Guest"}])
    (_pid, token), = body["invitation_tokens_do_not_store"].items()

    async with _anon() as http:
        r = await http.post("/agreements/invitation/sign",
                            json={"token": token, "method": "typed",
                                  "signature_data": "A Guest", "consent": True})

    assert r.status_code == 200, r.text
    assert r.json()["you"]["signed"] is True


async def test_the_token_is_not_stored_on_the_row(world):
    """It is shown once because it cannot be recovered — check that is true."""
    from app.db.collections import get_agreements_col

    body = await _send(world, [{"user_id": world["client"]},
                               {"email": GUEST_EMAIL, "full_name": "A Guest"}])
    (_pid, token), = body["invitation_tokens_do_not_store"].items()

    row = await get_agreements_col().find_one({"_id": body["_id"]})

    assert "invitation_tokens_do_not_store" not in row
    external = [p for p in row["parties"] if p.get("external")][0]
    assert external["invite"]["token_hash"] != token
    assert token not in repr(row)


async def test_a_later_read_of_the_agreement_never_returns_the_token(world):
    """Once only. A GET that re-issued it would undo the point of hashing."""
    body = await _send(world, [{"user_id": world["client"]},
                               {"email": GUEST_EMAIL, "full_name": "A Guest"}])
    (_pid, token), = body["invitation_tokens_do_not_store"].items()

    async with _as(world["lawyer"]) as http:
        r = await http.get(f"/agreements/{body['_id']}")

    assert r.status_code == 200, r.text
    assert token not in r.text


# ── the registered signer takes the other path ──────────────────────────────

async def test_a_registered_signer_is_notified_instead(world):
    """No link for them — they have an account, so they get a notification."""
    from app.db.collections import get_event_outbox_col

    body = await _send(world, [{"user_id": world["client"]},
                               {"email": GUEST_EMAIL, "full_name": "A Guest"}])

    parked = await get_event_outbox_col().find(
        {"payload.data.agreement_id": body["_id"]}).to_list(None)
    recipients = {e["payload"]["recipient_id"] for e in parked}

    assert recipients == {world["client"]}, (
        "the registered signer must be notified, the creator must not be, and "
        f"the invited signer has no account to notify; got {recipients}")


async def test_the_invited_signer_gets_no_notification_row(world):
    """There is no account to address one to. It must not be faked."""
    from app.db.collections import get_event_outbox_col

    body = await _send(world, [{"user_id": world["client"]},
                               {"email": GUEST_EMAIL, "full_name": "A Guest"}])

    parked = await get_event_outbox_col().find(
        {"payload.data.agreement_id": body["_id"]}).to_list(None)

    assert all(e["payload"]["recipient_id"] is not None for e in parked)
    assert not any(e["payload"]["recipient_id"] == GUEST_EMAIL for e in parked)


async def test_two_registered_signers_produce_no_tokens_at_all(world):
    """Nothing to deliver by hand when everybody has an account."""
    body = await _send(world, [{"user_id": world["client"]},
                               {"user_id": world["third"]}])

    assert not body.get("invitation_tokens_do_not_store")
    assert body["total_parties"] == 3
    assert all(not p["external"] for p in body["parties"])


async def test_a_second_invited_signer_needs_a_slot_the_client_does_not_hold(world):
    """Two invited addresses INSTEAD of the client is refused, and rightly.

    MAX_PARTIES is three, so two invitees would fill both non-creator slots and
    leave the case's own client off their own agreement. D2 rule 2 (revised)
    allows a party to be ADDED, never swapped out, and that is what this
    refusal is -- not a limitation of invitations.
    """
    async with _as(world["lawyer"]) as http:
        r = await http.post("/agreements",
                            headers={"Idempotency-Key": secrets.token_urlsafe(12)},
                            json={"title": "Retainer",
                                  "body_html": "Fees are 40% of recovery.",
                                  "party_ids": [
                                      {"email": "a@example.pk", "full_name": "A"},
                                      {"email": "b@example.pk", "full_name": "B"}],
                                  "case_id": world["case_id"],
                                  "method": "typed",
                                  "signature_data": "Adv Sender",
                                  "consent": True})

    assert r.status_code == 403, r.text
    assert "not replace them" in r.text


async def test_the_progress_fields_are_populated_on_the_create_response(world):
    """`AgreementCreated` declares them, so this response must carry them.

    It used to return the raw inserted row, so the one response announcing a
    brand-new agreement reported `null` for its own progress while a GET of the
    same agreement answered properly.
    """
    body = await _send(world, [{"user_id": world["client"]},
                               {"email": GUEST_EMAIL, "full_name": "A Guest"}])

    assert body["total_parties"] == 3
    assert body["signed_count"] == 1          # the creator, signed in the same call
    assert body["partially_signed"] is True
