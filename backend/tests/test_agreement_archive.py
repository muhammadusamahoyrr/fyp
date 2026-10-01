"""Archiving removes an agreement from ONE person's list.

WHY THIS IS NOT A DELETE. `delete_draft` removes an unsent draft and refuses
anything else, with the reason stated in its own docstring: "a sent agreement is
somebody else's record too, and deleting one would erase an instrument a
counterparty has seen". A request arriving from a list screen does not change
that -- a signed agreement is evidence, and the other parties hold their own view
of it.

So archiving writes the caller's id into `archived_by` and nothing else. These
tests pin the three properties that make that safe: the row survives, the other
party's list is unaffected, and the person who archived it can get it back.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest

from app.core.constants import AgreementStatus, CaseStatus

pytestmark = pytest.mark.integration


@pytest.fixture
async def world(mongo_transactional, monkeypatch):
    from app.core.config import settings
    from app.db.collections import (
        get_agreements_col, get_cases_col, get_event_outbox_col, get_users_col,
    )

    monkeypatch.setattr(settings, "agreements_diy_builder_enabled", True)
    # Nothing here is about mail; keep the suite off the network.
    monkeypatch.setattr(settings, "smtp_user", "")

    tag = secrets.token_hex(4)
    lawyer, client, stranger = f"AR-L-{tag}", f"AR-C-{tag}", f"AR-S-{tag}"
    now = datetime.now(timezone.utc)

    await get_users_col().insert_many([
        {"_id": lawyer, "full_name": "Adv Sender", "role": "lawyer",
         "email": f"l-{tag}@ar.pk", "is_active": True,
         "lawyer_profile": {"kyc_verified": True, "specializations": ["civil"]}},
        {"_id": client, "full_name": "The Client", "role": "client",
         "email": f"c-{tag}@ar.pk", "is_active": True},
        {"_id": stranger, "full_name": "A Stranger", "role": "client",
         "email": f"s-{tag}@ar.pk", "is_active": True},
    ])
    case_id = f"AR-CASE-{tag}"
    await get_cases_col().insert_one({
        "_id": case_id, "client_id": client, "lawyer_id": lawyer,
        "title": "A matter", "case_number": f"AR-{tag}",
        "status": CaseStatus.IN_PROGRESS.value,
        "milestones": [], "created_at": now, "updated_at": now})

    yield {"lawyer": lawyer, "client": client, "stranger": stranger,
           "case_id": case_id}

    ids = [lawyer, client, stranger]
    await get_users_col().delete_many({"_id": {"$in": ids}})
    await get_cases_col().delete_many({"_id": case_id})
    await get_agreements_col().delete_many({"created_by": {"$in": ids}})
    await get_event_outbox_col().delete_many({"payload.recipient_id": {"$in": ids}})


async def _sent(world):
    from app.services import agreement_service
    return await agreement_service.create_and_send_agreement(
        title="Retainer", body_html="Fees are 40% of recovery.",
        parties=[{"user_id": world["client"]}], creator_id=world["lawyer"],
        method="typed", signature_data="Adv Sender", consent=True,
        idempotency_key=secrets.token_urlsafe(12), case_id=world["case_id"])


def _ids(page):
    return {r["id"] for r in page["items"]}


# ── it hides, for one person ────────────────────────────────────────────────

async def test_archiving_removes_it_from_my_list(world):
    from app.services import agreement_service

    doc = await _sent(world)
    assert doc["_id"] in _ids(await agreement_service.list_agreements(world["lawyer"]))

    await agreement_service.set_archived(
        agreement_id=doc["_id"], user_id=world["lawyer"], archived=True)

    assert doc["_id"] not in _ids(
        await agreement_service.list_agreements(world["lawyer"]))


async def test_the_other_party_still_sees_it(world):
    """The property that makes this safe: it is MY list, not the record."""
    from app.services import agreement_service

    doc = await _sent(world)
    await agreement_service.set_archived(
        agreement_id=doc["_id"], user_id=world["lawyer"], archived=True)

    assert doc["_id"] in _ids(
        await agreement_service.list_agreements(world["client"])), \
        "archiving must not hide the agreement from the counterparty"


async def test_the_row_and_its_signatures_survive(world):
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    doc = await _sent(world)
    await agreement_service.set_archived(
        agreement_id=doc["_id"], user_id=world["lawyer"], archived=True)

    row = await get_agreements_col().find_one({"_id": doc["_id"]})
    assert row is not None, "archiving must not delete the agreement"
    assert row["status"] == AgreementStatus.PENDING.value
    assert any(p.get("signed") for p in row["parties"]), "a signature was lost"
    assert row["audit_log"], "the audit log was lost"


async def test_it_is_still_readable_by_id(world):
    """Archived means "not in my list", never "gone"."""
    from app.services import agreement_service

    doc = await _sent(world)
    await agreement_service.set_archived(
        agreement_id=doc["_id"], user_id=world["lawyer"], archived=True)

    view = await agreement_service.get_agreement(doc["_id"], world["lawyer"])
    assert view["_id"] == doc["_id"]


# ── and it is reversible ────────────────────────────────────────────────────

async def test_the_archived_filter_finds_it(world):
    from app.services import agreement_service

    doc = await _sent(world)
    await agreement_service.set_archived(
        agreement_id=doc["_id"], user_id=world["lawyer"], archived=True)

    page = await agreement_service.list_agreements(world["lawyer"], archived=True)
    assert doc["_id"] in _ids(page)


async def test_unarchiving_puts_it_back(world):
    from app.services import agreement_service

    doc = await _sent(world)
    await agreement_service.set_archived(
        agreement_id=doc["_id"], user_id=world["lawyer"], archived=True)
    await agreement_service.set_archived(
        agreement_id=doc["_id"], user_id=world["lawyer"], archived=False)

    assert doc["_id"] in _ids(
        await agreement_service.list_agreements(world["lawyer"]))
    assert doc["_id"] not in _ids(
        await agreement_service.list_agreements(world["lawyer"], archived=True))


async def test_archiving_twice_is_harmless(world):
    """$addToSet, not $push: a double click must not record two entries."""
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    doc = await _sent(world)
    for _ in range(3):
        await agreement_service.set_archived(
            agreement_id=doc["_id"], user_id=world["lawyer"], archived=True)

    row = await get_agreements_col().find_one({"_id": doc["_id"]})
    assert row["archived_by"] == [world["lawyer"]]


# ── who may do it ───────────────────────────────────────────────────────────

async def test_a_stranger_cannot_archive(world):
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    doc = await _sent(world)
    with pytest.raises(ForbiddenError):
        await agreement_service.set_archived(
            agreement_id=doc["_id"], user_id=world["stranger"], archived=True)


async def test_archiving_an_unknown_agreement_is_not_found(world):
    from app.core.exceptions import NotFoundError
    from app.services import agreement_service

    with pytest.raises(NotFoundError):
        await agreement_service.set_archived(
            agreement_id="no-such-agreement", user_id=world["lawyer"],
            archived=True)


async def test_a_status_filter_still_applies_to_the_archived_view(world):
    """The two filters narrow together rather than replacing each other."""
    from app.services import agreement_service

    doc = await _sent(world)
    await agreement_service.set_archived(
        agreement_id=doc["_id"], user_id=world["lawyer"], archived=True)

    pending = await agreement_service.list_agreements(
        world["lawyer"], status=AgreementStatus.PENDING.value, archived=True)
    executed = await agreement_service.list_agreements(
        world["lawyer"], status=AgreementStatus.EXECUTED.value, archived=True)

    assert doc["_id"] in _ids(pending)
    assert doc["_id"] not in _ids(executed)
