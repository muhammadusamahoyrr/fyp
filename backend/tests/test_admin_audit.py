"""Every admin mutation records who performed it, and no admin can lock the
system out of its own administration.

The gap was structural rather than a slip: all 12 admin routes resolved
`current_user` and forwarded it to the service exactly ZERO times. So nothing
recorded which admin approved a KYC verification, promoted a user, reset a
password or deactivated an account — while agreement_service keeps an actor and
IP audit log for considerably less consequential actions.

Recording the actor is also what makes the self-lockout and last-admin guards
possible: without it the service could not tell who was acting.
"""
import pytest

from app.core.exceptions import AppValidationError
from app.core.security import hash_password


@pytest.fixture
async def admin_and_users(mongo):
    from app.db.collections import get_users_col

    await get_users_col().insert_many([
        {"_id": "AUD-ADM", "role": "admin", "email": "aud-adm@x.test",
         "password_hash": hash_password("Str0ngPass1"), "full_name": "Admin",
         "is_active": True},
        {"_id": "AUD-CLIENT", "role": "client", "email": "aud-c@x.test",
         "password_hash": hash_password("Str0ngPass1"), "full_name": "Client",
         "is_active": True},
        {"_id": "AUD-LAWYER", "role": "lawyer", "email": "aud-l@x.test",
         "password_hash": hash_password("Str0ngPass1"), "full_name": "Lawyer",
         "is_active": True,
         "lawyer_profile": {"bar_number": "BAR-9", "kyc_verified": False,
                            "kyc_rejection_reason": None, "specializations": []}},
    ])
    yield {"admin": "AUD-ADM", "client": "AUD-CLIENT", "lawyer": "AUD-LAWYER"}
    await get_users_col().delete_many(
        {"_id": {"$in": ["AUD-ADM", "AUD-CLIENT", "AUD-LAWYER", "AUD-ADM2"]}})


@pytest.fixture
async def audit(mongo):
    from app.db.collections import get_admin_audit_col

    col = get_admin_audit_col()
    await col.delete_many({})
    yield col
    await col.delete_many({})


def _actor(uid="AUD-ADM", email="aud-adm@x.test"):
    return {"_id": uid, "email": email}


async def _entries(col, target=None):
    query = {"target_id": target} if target else {}
    return [doc async for doc in col.find(query)]


# ── who decided ──────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_kyc_approval_records_the_deciding_admin(admin_and_users, audit):
    """Verification is what lets a lawyer receive real clients."""
    from app.services import admin_service

    await admin_service.process_kyc(admin_and_users["lawyer"], True, None, actor=_actor())

    (entry,) = await _entries(audit, admin_and_users["lawyer"])
    assert entry["action"] == "kyc.approved"
    assert entry["actor_id"] == "AUD-ADM"
    assert entry["actor_email"] == "aud-adm@x.test"
    assert entry["timestamp"]


@pytest.mark.integration
async def test_kyc_rejection_records_the_reason_given(admin_and_users, audit):
    from app.services import admin_service

    await admin_service.process_kyc(
        admin_and_users["lawyer"], False, "Bar number could not be verified",
        actor=_actor())

    (entry,) = await _entries(audit, admin_and_users["lawyer"])
    assert entry["action"] == "kyc.rejected"
    assert entry["detail"]["reason"] == "Bar number could not be verified"


@pytest.mark.integration
async def test_a_password_reset_is_audited_without_recording_the_password(
        admin_and_users, audit):
    from app.services import admin_service

    await admin_service.reset_user_password(
        admin_and_users["client"], "BrandNewPass1", actor=_actor())

    (entry,) = await _entries(audit, admin_and_users["client"])
    assert entry["action"] == "user.password_reset"
    assert "BrandNewPass1" not in str(entry), "the new password must not reach the audit"


@pytest.mark.integration
async def test_creation_and_deletion_are_both_audited(admin_and_users, audit):
    from app.db.collections import get_users_col
    from app.services import admin_service

    created = await admin_service.create_user(
        "New Person", "aud-new@x.test", "client", "Str0ngPass1", actor=_actor())
    try:
        await admin_service.delete_user(created["_id"], actor=_actor())
        actions = {e["action"] for e in await _entries(audit, created["_id"])}
        assert actions == {"user.created", "user.deleted"}
    finally:
        await get_users_col().delete_one({"_id": created["_id"]})


@pytest.mark.integration
async def test_a_role_change_records_the_new_role(admin_and_users, audit):
    from app.services import admin_service

    await admin_service.update_user(
        admin_and_users["client"], {"role": "lawyer"}, actor=_actor())

    (entry,) = await _entries(audit, admin_and_users["client"])
    assert entry["action"] == "user.updated"
    assert entry["detail"]["role"] == "lawyer"


@pytest.mark.integration
async def test_an_audit_write_failure_does_not_fail_the_action(admin_and_users, monkeypatch):
    """A failed audit insert must not turn a successful KYC approval into a 500,
    leaving the lawyer verified while the admin believes it did not work."""
    from app.db.collections import get_admin_audit_col, get_users_col
    from app.services import admin_service

    async def insert_boom(*args, **kwargs):
        raise RuntimeError("audit store unreachable")

    monkeypatch.setattr(get_admin_audit_col(), "insert_one", insert_boom, raising=False)

    await admin_service.process_kyc(admin_and_users["lawyer"], True, None, actor=_actor())

    lawyer = await get_users_col().find_one({"_id": admin_and_users["lawyer"]})
    assert lawyer["lawyer_profile"]["kyc_verified"] is True


# ── self-lockout and last-admin ──────────────────────────────────────────────

@pytest.mark.integration
async def test_an_admin_cannot_deactivate_themselves(admin_and_users, audit):
    from app.services import admin_service

    with pytest.raises(AppValidationError):
        await admin_service.update_user("AUD-ADM", {"is_active": False}, actor=_actor())
    with pytest.raises(AppValidationError):
        await admin_service.delete_user("AUD-ADM", actor=_actor())


@pytest.mark.integration
async def test_an_admin_cannot_demote_themselves(admin_and_users, audit):
    from app.services import admin_service

    with pytest.raises(AppValidationError):
        await admin_service.update_user("AUD-ADM", {"role": "client"}, actor=_actor())


@pytest.mark.integration
async def test_the_last_admin_cannot_be_removed_even_by_another_admin(
        admin_and_users, audit):
    """The self-guard alone is not enough: admin A could lock everyone out by
    removing admin B. auth_service.register refuses the admin role, so there is
    no way back in short of editing the database by hand."""
    from app.db.collections import get_users_col
    from app.services import admin_service

    await get_users_col().insert_one(
        {"_id": "AUD-ADM2", "role": "admin", "email": "aud-adm2@x.test",
         "password_hash": hash_password("Str0ngPass1"), "is_active": True})

    second = _actor("AUD-ADM2", "aud-adm2@x.test")
    # while two admins are active, removing one is allowed
    await admin_service.delete_user("AUD-ADM", actor=second)

    # AUD-ADM2 is now the only active admin, and cannot be removed
    with pytest.raises(AppValidationError):
        await admin_service.delete_user("AUD-ADM2", actor=_actor())


@pytest.mark.integration
async def test_removing_a_non_admin_is_never_blocked(admin_and_users, audit):
    """The guard keys on the TARGET being an admin. It must not fire on clients
    and lawyers, or ordinary moderation stops working."""
    from app.services import admin_service

    await admin_service.delete_user(admin_and_users["client"], actor=_actor())
    await admin_service.update_user(
        admin_and_users["lawyer"], {"is_active": False}, actor=_actor())


# ── the structural gap that caused this ──────────────────────────────────────

def test_every_mutating_route_forwards_the_acting_user():
    """The defect was not one missed call — it was 12 routes resolving
    current_user and forwarding it zero times. This fails if a new mutating
    route repeats the pattern."""
    import inspect

    from app.api.v1.routes import admin as admin_routes

    source = inspect.getsource(admin_routes)
    for call in ("process_kyc", "create_user", "update_user",
                 "reset_user_password", "delete_user", "update_case_status"):
        start = source.index(f"admin_service.{call}(")
        assert "actor=current_user" in source[start:start + 280], (
            f"{call} does not record which admin performed it")


def test_the_audit_helper_swallows_everything():
    """Relied on by test_an_audit_write_failure_does_not_fail_the_action."""
    import inspect

    from app.services import admin_service

    src = inspect.getsource(admin_service._audit)
    assert "except Exception" in src
    assert "logger.exception" in src
