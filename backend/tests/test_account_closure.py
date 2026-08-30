"""Closing an account must actually do something, and must refuse when it shouldn't.

The UI previously showed "Your account has been deleted" after a two-second
timer and called nothing. Name, email, phone, case details and payment records
all remained. A user exercising their right to erasure was told it had happened.

Hard deletion is not the fix. Payments are financial records, provenance is an
audit trail, and a lawyer's case history evidences obligations to clients who did
not ask for anything to be erased. So: revoke access, erase the personal data,
keep the skeleton — and refuse while obligations are live.
"""
import pytest

from app.core.exceptions import AppValidationError, ForbiddenError
from app.services import user_service as us


class _Col:
    def __init__(self, n=0): self.n = n
    async def count_documents(self, *a, **k): return self.n
    async def insert_one(self, *a, **k): return None


@pytest.fixture
def acct(monkeypatch):
    """A live client account with a known password and no obligations."""
    state = {"user": {"_id": "U1", "role": "client", "password_hash": "H",
                      "full_name": "Ali Khan", "email": "ali@real.com",
                      "phone": "+92300", "cnic_encrypted": "ENC"},
             "update": None, "engagements": 0, "payments": 0, "blocked": False}

    async def _find(uid): return dict(state["user"])
    async def _update(q, u):
        state["update"] = u["$set"]
        state["unset"] = u.get("$unset", {})
        return True

    monkeypatch.setattr(us.user_repo, "find_by_id", _find)
    monkeypatch.setattr(us.user_repo, "update_one", _update)
    monkeypatch.setattr(us, "verify_password", lambda p, h: p == "correct")

    import app.db.collections as dbc
    monkeypatch.setattr(dbc, "get_engagements_col", lambda: _Col(state["engagements"]))
    monkeypatch.setattr(dbc, "get_payments_col", lambda: _Col(state["payments"]))

    class _BL:
        async def insert_one(self, doc): state["blocked"] = True
    monkeypatch.setattr(dbc, "get_refresh_blocklist_col", lambda: _BL())
    return state


class TestItRefusesWhenItShould:
    async def test_a_wrong_password_is_rejected(self, acct):
        with pytest.raises(ForbiddenError):
            await us.close_account("U1", "guess")
        assert acct["update"] is None, "nothing may change on a failed auth"

    async def test_an_open_engagement_blocks_closure(self, acct):
        """Closing a client's account mid-case strands their lawyer."""
        acct["engagements"] = 2
        with pytest.raises(AppValidationError) as exc:
            await us.close_account("U1", "correct")
        assert "2 open engagement" in str(exc.value)
        assert acct["update"] is None

    async def test_an_unsettled_payment_blocks_closure(self, acct):
        """A client cannot walk away from a fee request by closing the account."""
        acct["payments"] = 1
        with pytest.raises(AppValidationError) as exc:
            await us.close_account("U1", "correct")
        assert "unsettled payment" in str(exc.value)

    async def test_the_refusal_names_every_blocker(self, acct):
        acct["engagements"] = 1; acct["payments"] = 3
        with pytest.raises(AppValidationError) as exc:
            await us.close_account("U1", "correct")
        msg = str(exc.value)
        assert "engagement" in msg and "payment" in msg


class TestItActuallyErases:
    async def test_personal_data_is_overwritten(self, acct):
        await us.close_account("U1", "correct")
        u = acct["update"]
        assert u["full_name"] == "Closed account"
        assert "@deleted.invalid" in u["email"]
        assert u["phone"] is None
        assert u["avatar_url"] is None

    async def test_the_cnic_is_unset_not_nulled(self, acct):
        """cnic_encrypted carries a unique+sparse index. Sparse skips only
        MISSING fields, so an explicit null IS indexed — the second account ever
        closed collided with the first on
        "E11000 duplicate key ... cnic_encrypted: null" and the entire write
        failed, leaving that account fully intact. Verified live."""
        await us.close_account("U1", "correct")
        assert "cnic_encrypted" in acct["unset"]
        assert "cnic_encrypted" not in acct["update"]

    async def test_the_closure_email_is_unique_per_account(self, acct):
        """email is unique too. A shared placeholder would collide the same way."""
        await us.close_account("U1", "correct")
        assert "U1" in acct["update"]["email"]

    async def test_the_login_is_made_unusable(self, acct):
        """A null hash would break verify_password rather than simply refuse it."""
        await us.close_account("U1", "correct")
        assert acct["update"]["password_hash"] == "!closed"

    async def test_it_is_marked_closed_not_merely_inactive(self, acct):
        """is_active alone is ambiguous — admins deactivate accounts too."""
        await us.close_account("U1", "correct")
        assert acct["update"]["is_closed"] is True
        assert acct["update"]["is_active"] is False
        assert acct["update"]["closed_at"]

    async def test_existing_sessions_are_revoked(self, acct):
        """Refresh tokens outlive the closure otherwise — a closed account would
        stay reachable from any device already signed in.

        This used to assert that a row was inserted into refresh_blocklist. That
        insert never revoked anything: it stored {user_id, reason}, and
        auth_service.refresh looks tokens up BY TOKEN VALUE, so the row matched
        nothing. The account was only unreachable because is_active went False —
        the blocklist write was dead weight that read like a protection, and
        this test was pinning it.

        The assertion now names the mechanism that works, and which also covers
        access tokens rather than refresh alone.
        """
        from app.core.security import TOKENS_VALID_FROM

        await us.close_account("U1", "correct")
        assert acct["update"][TOKENS_VALID_FROM] is not None

    async def test_a_lawyer_is_delisted(self, acct):
        acct["user"]["role"] = "lawyer"
        acct["user"]["lawyer_profile"] = {"kyc_verified": True, "availability": True}
        await us.close_account("U1", "correct")
        assert acct["update"]["lawyer_profile.kyc_verified"] is False
        assert acct["update"]["lawyer_profile.availability"] is False

    async def test_a_client_gets_no_lawyer_profile_writes(self, acct):
        """A client's lawyer_profile is null. Mongo refuses to create a field
        inside null — "Cannot create field 'availability' in element
        {lawyer_profile: null}" — which failed the entire write and left the
        account completely intact. Verified live before this guard."""
        acct["user"]["lawyer_profile"] = None
        await us.close_account("U1", "correct")
        assert not any(k.startswith("lawyer_profile") for k in acct["update"])

    async def test_a_missing_lawyer_profile_is_also_safe(self, acct):
        acct["user"].pop("lawyer_profile", None)
        await us.close_account("U1", "correct")
        assert not any(k.startswith("lawyer_profile") for k in acct["update"])

    async def test_the_id_survives_so_references_are_not_orphaned(self, acct):
        """Payments, cases and provenance point at this id. Removing the row
        would break every one of them."""
        await us.close_account("U1", "correct")
        assert "_id" not in acct["update"]

    async def test_the_response_is_honest_about_what_is_kept(self, acct):
        out = await us.close_account("U1", "correct")
        assert out["closed"] is True
        assert "retained" in out["detail"]


class TestLawyerObligations:
    async def test_a_lawyer_with_open_engagements_is_blocked(self, acct):
        acct["user"]["role"] = "lawyer"; acct["engagements"] = 4
        with pytest.raises(AppValidationError) as exc:
            await us.close_account("U1", "correct")
        assert "4 client engagement" in str(exc.value)
