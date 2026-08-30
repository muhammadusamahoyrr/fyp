"""KYC state and account deletion — the two semantic decisions.

KYC. `kyc_verified: bool` could not express where a lawyer actually stood. A
REJECTED lawyer has kyc_verified False and therefore matched the pending-queue
filter exactly as an unreviewed one did, so rejections looped back into the
queue forever and were re-reviewed with no record that a decision had been made.
`kyc_status` now says pending | approved | rejected, rejection is terminal, and
the ONLY way back to pending is an explicit resubmit by the lawyer — not a side
effect of editing the profile, which would let an unrelated bio change silently
re-open a verification an admin had refused.

DELETION. There were two incompatible semantics for the same act.
`user_service.close_account` refused while engagements or payments were open and
anonymised the record; `admin_service.delete_user` flipped `is_active` to False
and nothing else, so an admin could strand a client's lawyer mid-engagement and
a route named DELETE reported success while every personal detail stayed. Both
now take one path.
"""
import pytest

from app.core.constants import KycStatus
from app.core.exceptions import AppValidationError, ForbiddenError
from app.core.security import hash_password


@pytest.fixture
async def people(mongo):
    from app.db.collections import get_users_col

    await get_users_col().insert_many([
        {"_id": "SEM-ADM", "role": "admin", "email": "sem-adm@x.test",
         "password_hash": hash_password("Str0ngPass1"), "is_active": True},
        {"_id": "SEM-ADM2", "role": "admin", "email": "sem-adm2@x.test",
         "password_hash": hash_password("Str0ngPass1"), "is_active": True},
        {"_id": "SEM-CLIENT", "role": "client", "email": "sem-c@x.test",
         "full_name": "Real Name", "phone": "03001234567",
         "password_hash": hash_password("Str0ngPass1"), "is_active": True},
        {"_id": "SEM-PENDING", "role": "lawyer", "email": "sem-p@x.test",
         "password_hash": hash_password("Str0ngPass1"), "is_active": True,
         "lawyer_profile": {"bar_number": "BAR-P", "kyc_verified": False,
                            "kyc_status": KycStatus.PENDING.value,
                            "kyc_rejection_reason": None}},
        {"_id": "SEM-LEGACY", "role": "lawyer", "email": "sem-lg@x.test",
         "password_hash": hash_password("Str0ngPass1"), "is_active": True,
         # written before kyc_status existed — no such key
         "lawyer_profile": {"bar_number": "BAR-L", "kyc_verified": False,
                            "kyc_rejection_reason": None}},
    ])
    yield
    await get_users_col().delete_many({"_id": {"$regex": "^SEM-"}})


def _actor():
    return {"_id": "SEM-ADM", "email": "sem-adm@x.test"}


async def _queue_ids():
    from app.services import admin_service
    return {row["_id"] for row in await admin_service.list_pending_kyc()}


# ── rejection is terminal ────────────────────────────────────────────────────

@pytest.mark.integration
async def test_a_rejected_lawyer_leaves_the_pending_queue(people):
    """The defect: nothing distinguished rejected from unreviewed, so a
    rejection reappeared on every load."""
    from app.services import admin_service

    assert "SEM-PENDING" in await _queue_ids()

    await admin_service.process_kyc("SEM-PENDING", False, "Bar number unverifiable",
                                    actor=_actor())

    assert "SEM-PENDING" not in await _queue_ids()


@pytest.mark.integration
async def test_an_approved_lawyer_leaves_the_pending_queue(people):
    from app.services import admin_service

    await admin_service.process_kyc("SEM-PENDING", True, None, actor=_actor())

    assert "SEM-PENDING" not in await _queue_ids()


@pytest.mark.integration
async def test_a_lawyer_with_no_status_field_is_still_treated_as_pending(people):
    """Documents written before kyc_status existed are genuinely awaiting
    review. Excluding them would have silently emptied the queue on deploy."""
    assert "SEM-LEGACY" in await _queue_ids()


@pytest.mark.integration
async def test_the_dashboard_count_matches_the_queue(people):
    """pending_kyc counted kyc_verified alone, so it included rejected lawyers
    and disagreed with the list an admin actually sees."""
    from app.services import admin_service

    await admin_service.process_kyc("SEM-PENDING", False, "no", actor=_actor())

    analytics = await admin_service.get_analytics()
    queue = await admin_service.list_pending_kyc()
    assert analytics["pending_kyc"] == len(queue)


@pytest.mark.integration
async def test_the_decision_is_recorded_on_the_profile(people):
    from app.db.collections import get_users_col
    from app.services import admin_service

    await admin_service.process_kyc("SEM-PENDING", False, "Documents unclear",
                                    actor=_actor())

    lawyer = await get_users_col().find_one({"_id": "SEM-PENDING"})
    assert lawyer["lawyer_profile"]["kyc_status"] == KycStatus.REJECTED.value
    assert lawyer["lawyer_profile"]["kyc_rejection_reason"] == "Documents unclear"
    assert lawyer["lawyer_profile"]["kyc_verified"] is False


# ── resubmission is the only way back ────────────────────────────────────────

@pytest.mark.integration
async def test_a_rejected_lawyer_can_resubmit_and_returns_to_the_queue(people):
    from app.services import admin_service, user_service

    await admin_service.process_kyc("SEM-PENDING", False, "Documents unclear",
                                    actor=_actor())
    assert "SEM-PENDING" not in await _queue_ids()

    await user_service.resubmit_kyc("SEM-PENDING")

    assert "SEM-PENDING" in await _queue_ids()


@pytest.mark.integration
async def test_resubmitting_clears_the_stale_rejection_reason(people):
    from app.db.collections import get_users_col
    from app.services import admin_service, user_service

    await admin_service.process_kyc("SEM-PENDING", False, "Documents unclear",
                                    actor=_actor())
    await user_service.resubmit_kyc("SEM-PENDING")

    lawyer = await get_users_col().find_one({"_id": "SEM-PENDING"})
    assert lawyer["lawyer_profile"]["kyc_rejection_reason"] is None


@pytest.mark.integration
async def test_a_pending_lawyer_cannot_resubmit(people):
    """There is nothing to resubmit, and allowing it would let a lawyer refresh
    their position in the queue."""
    from app.services import user_service

    with pytest.raises(AppValidationError):
        await user_service.resubmit_kyc("SEM-PENDING")


@pytest.mark.integration
async def test_an_approved_lawyer_cannot_resubmit(people):
    from app.services import admin_service, user_service

    await admin_service.process_kyc("SEM-PENDING", True, None, actor=_actor())

    with pytest.raises(AppValidationError):
        await user_service.resubmit_kyc("SEM-PENDING")


@pytest.mark.integration
async def test_a_client_cannot_resubmit_kyc(people):
    from app.services import user_service

    with pytest.raises(ForbiddenError):
        await user_service.resubmit_kyc("SEM-CLIENT")


@pytest.mark.integration
async def test_editing_the_profile_does_not_silently_reopen_a_rejection(people):
    """Resubmission is deliberately an explicit action. An unrelated bio change
    must not re-open a verification an admin already refused."""
    from app.services import admin_service, user_service

    await admin_service.process_kyc("SEM-PENDING", False, "Documents unclear",
                                    actor=_actor())
    await user_service.update_lawyer_profile("SEM-PENDING", {"bio": "Updated bio"})

    assert "SEM-PENDING" not in await _queue_ids()


# ── one deletion semantic ────────────────────────────────────────────────────

@pytest.mark.integration
async def test_an_admin_delete_anonymises_rather_than_flipping_a_flag(people):
    """It set is_active False and left name, email and phone intact, while
    reporting success from a route named DELETE."""
    from app.db.collections import get_users_col
    from app.services import admin_service

    await admin_service.delete_user("SEM-CLIENT", actor=_actor())

    user = await get_users_col().find_one({"_id": "SEM-CLIENT"})
    assert user["is_active"] is False
    assert user["is_closed"] is True
    assert user["full_name"] == "Closed account"
    assert "Real Name" not in str(user)
    assert user["phone"] is None
    assert user["closed_reason"] == "closed_by_admin"


@pytest.mark.integration
async def test_an_admin_delete_refuses_while_obligations_are_open(people):
    """close_account has always refused this. delete_user did not, so an admin
    could strand a client's lawyer mid-engagement."""
    from app.core.constants import EngagementStatus
    from app.db.collections import get_engagements_col, get_users_col
    from app.services import admin_service

    await get_engagements_col().insert_one(
        {"_id": "SEM-ENG", "client_id": "SEM-CLIENT", "lawyer_id": "SEM-PENDING",
         "status": EngagementStatus.ACCEPTED.value})
    try:
        with pytest.raises(AppValidationError) as exc:
            await admin_service.delete_user("SEM-CLIENT", actor=_actor())
        assert "engagement" in str(exc.value).lower()

        # and nothing was changed
        user = await get_users_col().find_one({"_id": "SEM-CLIENT"})
        assert user["is_active"] is True
        assert user["full_name"] == "Real Name"
    finally:
        await get_engagements_col().delete_one({"_id": "SEM-ENG"})


@pytest.mark.integration
async def test_both_deletion_paths_produce_the_same_shape(people):
    """One semantic, reached two ways. The only difference is who ended it."""
    from app.db.collections import get_users_col
    from app.services import admin_service, user_service

    await admin_service.delete_user("SEM-CLIENT", actor=_actor())
    await user_service.close_account("SEM-PENDING", "Str0ngPass1")

    by_admin = await get_users_col().find_one({"_id": "SEM-CLIENT"})
    by_self = await get_users_col().find_one({"_id": "SEM-PENDING"})

    for doc in (by_admin, by_self):
        assert doc["is_closed"] is True
        assert doc["password_hash"] == "!closed"
        assert doc["full_name"] == "Closed account"
    assert by_admin["closed_reason"] == "closed_by_admin"
    assert by_self["closed_reason"] == "self_service"


@pytest.mark.integration
async def test_closing_an_account_revokes_its_sessions(people):
    """The old code inserted {user_id, reason} into refresh_blocklist, which
    refresh() never matched — it looks up BY TOKEN VALUE. The row was dead
    weight that read like a protection."""
    from app.core.security import TOKENS_VALID_FROM
    from app.db.collections import get_users_col
    from app.services import admin_service

    await admin_service.delete_user("SEM-CLIENT", actor=_actor())

    user = await get_users_col().find_one({"_id": "SEM-CLIENT"})
    assert user.get(TOKENS_VALID_FROM) is not None
