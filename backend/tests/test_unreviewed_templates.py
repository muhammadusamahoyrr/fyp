"""Withdrawn template boilerplate cannot become a binding agreement.

The six built-in agreement templates shipped United States contract text as the
starting body of a real, e-signed instrument: incorporation in a "[State]",
"$[Amount]" salaries on a bi-weekly schedule, and a non-compete over a
"[Geographic Area]". The bodies are withdrawn pending review by a qualified
Pakistani lawyer.

Withdrawing them in the frontend is not a guarantee on its own -- the API takes
`body_html` from the caller, so anyone could post the old text back. The guard
lives in the service, and is checked twice:

  * at creation, which is also the moment the agreement is sent for signature;
  * at signature, which is the actual guarantee, because it covers agreements
    created BEFORE the templates were withdrawn -- exactly the ones still
    sitting in `pending` with US boilerplate in them.

The marker is deliberately ASCII with no em-dash. It is compared byte-for-byte
across a JS/Python boundary, and this repository has already had one em-dash
mangled by an encoding mismatch.
"""
import pytest

from app.core.constants import AgreementStatus
from app.services.agreement_service import (
    UNREVIEWED_TEMPLATE_MARKER,
    is_unreviewed_template,
)

SAMPLE = f"""{UNREVIEWED_TEMPLATE_MARKER}

Employment Contract

This template has been withdrawn pending review by a qualified Pakistani lawyer.
"""


# ── the predicate ────────────────────────────────────────────────────────────

def test_withdrawn_body_is_detected():
    assert is_unreviewed_template(SAMPLE) is True


def test_the_marker_is_detected_anywhere_in_the_body():
    """A user may type above or below the notice without removing it."""
    assert is_unreviewed_template(f"My terms\n\n{UNREVIEWED_TEMPLATE_MARKER}\n\nmore") is True


def test_a_real_agreement_is_not_flagged():
    assert is_unreviewed_template(
        "This Agreement is made between Ali and Bilal on 1 January 2026.") is False


@pytest.mark.parametrize("value", ["", None])
def test_empty_bodies_are_not_flagged(value):
    assert is_unreviewed_template(value) is False


def test_the_marker_is_pure_ascii():
    """It crosses a JS/Python boundary and is compared byte-for-byte. An
    em-dash here would be a silent mismatch waiting to happen."""
    assert UNREVIEWED_TEMPLATE_MARKER.isascii()


def test_the_frontend_and_backend_markers_are_identical():
    """The only thing tying the two sides together. If someone edits one string,
    the guard silently stops matching and the boilerplate becomes signable."""
    from pathlib import Path

    jsx = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "components"
           / "client" / "ModAgreements.jsx").read_text(encoding="utf-8")

    assert f'const UNREVIEWED_MARKER = "{UNREVIEWED_TEMPLATE_MARKER}";' in jsx


def test_the_us_boilerplate_is_gone_from_the_templates():
    """The specific strings that made the old bodies unsafe."""
    from pathlib import Path

    jsx = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "components"
           / "client" / "ModAgreements.jsx").read_text(encoding="utf-8")

    for phrase in ("[State] corporation", "Bi-weekly", "Non-Compete",
                   "$[Amount] per year"):
        assert phrase not in jsx, f"US boilerplate still present: {phrase!r}"


# ── the guarantee (needs Mongo) ──────────────────────────────────────────────

@pytest.fixture
async def two_users(mongo):
    from app.db.collections import get_users_col

    await get_users_col().insert_many([
        {"_id": "UT-ALICE", "full_name": "Alice", "role": "client", "email": "a@x.test"},
        {"_id": "UT-BOB", "full_name": "Bob", "role": "client", "email": "b@x.test"},
    ])
    yield ["UT-ALICE", "UT-BOB"]
    await get_users_col().delete_many({"_id": {"$in": ["UT-ALICE", "UT-BOB"]}})


@pytest.mark.integration
async def test_an_agreement_cannot_be_created_from_withdrawn_boilerplate(two_users):
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    with pytest.raises(AppValidationError) as exc:
        await agreement_service.create_agreement(
            title="Employment Contract", body_html=SAMPLE,
            parties=[{"user_id": u} for u in two_users], creator_id="UT-ALICE")

    assert "unreviewed" in str(exc.value).lower()


@pytest.mark.integration
async def test_a_preexisting_boilerplate_agreement_cannot_be_signed(two_users):
    """The real guarantee. Agreements created before the templates were withdrawn
    are inserted directly here, because create_agreement now refuses them."""
    import secrets
    from datetime import datetime, timezone

    from app.core.exceptions import AppValidationError
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    agreement_id = secrets.token_urlsafe(16)
    await get_agreements_col().insert_one({
        "_id": agreement_id,
        "title": "Employment Contract",
        "body_html": SAMPLE,
        "body_sha256": agreement_service.body_digest(SAMPLE),
        "status": AgreementStatus.PENDING.value,
        "parties": [
            {"user_id": u, "full_name": u, "signed": False, "signed_at": None,
             "signature_method": None, "signature_data": None} for u in two_users
        ],
        "audit_log": [], "created_by": "UT-ALICE",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    try:
        with pytest.raises(AppValidationError) as exc:
            await agreement_service.submit_signature(
                agreement_id=agreement_id, user_id="UT-ALICE",
                method="typed", signature_data="Alice", ip_address=None)
        assert "unreviewed" in str(exc.value).lower()

        # And it is still not executed.
        after = await get_agreements_col().find_one({"_id": agreement_id})
        assert after["status"] == AgreementStatus.PENDING.value
        assert not any(p.get("signed") for p in after["parties"])
    finally:
        await get_agreements_col().delete_one({"_id": agreement_id})


@pytest.mark.integration
async def test_replacing_the_notice_makes_the_agreement_usable_again(two_users):
    """The guard blocks the boilerplate, not the feature."""
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    doc = await agreement_service.create_agreement(
        title="Employment Contract",
        body_html="This Agreement is made between Alice and Bob on 1 January 2026.",
        parties=[{"user_id": u} for u in two_users], creator_id="UT-ALICE")
    try:
        for uid in two_users:
            result = await agreement_service.submit_signature(
                agreement_id=doc["_id"], user_id=uid,
                method="typed", signature_data=uid, ip_address=None)

        assert result["status"] == AgreementStatus.EXECUTED.value
    finally:
        await get_agreements_col().delete_one({"_id": doc["_id"]})
