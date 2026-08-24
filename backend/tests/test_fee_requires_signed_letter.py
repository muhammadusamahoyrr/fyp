"""A lawyer cannot bill a client who has not signed the engagement letter.

The letter records the fee the lawyer set and the scope they agreed to. It is
the ONLY place in this system where the client agrees to a price: the lawyer
sets fee_amount unilaterally when accepting, and `accepted` is a terminal state
the client cannot leave.

Verified live before this guard existed: a lawyer accepted an engagement, set a
fee of Rs 500,000 the client had never seen, and raised a fee request against it
with the letter still unsigned — HTTP 200. The client could not cancel or
decline (422). The only party who had agreed to that number was the one being
paid.
"""
import pytest

from app.core.constants import AgreementStatus, EngagementStatus
from app.core.exceptions import AppValidationError
from app.services import payment_service as ps


def _eng(agreement_id="a1"):
    return {"_id": "e1", "case_id": "c1", "lawyer_id": "L1",
            "status": EngagementStatus.ACCEPTED.value, "agreement_id": agreement_id}


class _Col:
    def __init__(self, doc): self._doc = doc
    async def find_one(self, *a, **k): return self._doc


def _patch(monkeypatch, eng, agreement):
    monkeypatch.setattr(ps, "get_engagements_col", lambda: _Col(eng))
    monkeypatch.setattr(ps, "get_agreements_col", lambda: _Col(agreement))


class TestTheGate:
    async def test_an_executed_letter_allows_billing(self, monkeypatch):
        _patch(monkeypatch, _eng(), {"_id": "a1", "status": AgreementStatus.EXECUTED.value})
        await ps._require_executed_engagement_letter("c1", "L1")   # must not raise

    async def test_a_pending_letter_blocks_billing(self, monkeypatch):
        """The exact live-proven hole."""
        _patch(monkeypatch, _eng(), {"_id": "a1", "status": AgreementStatus.PENDING.value})
        with pytest.raises(AppValidationError) as exc:
            await ps._require_executed_engagement_letter("c1", "L1")
        assert "pending" in str(exc.value)
        assert "agree to the fee in writing" in str(exc.value)

    async def test_a_missing_letter_blocks_billing(self, monkeypatch):
        """engagement_service wraps letter generation in `except Exception: pass`,
        so an engagement can stand with no letter at all. That silent gap must
        not become a billing loophole — no letter is no consent."""
        _patch(monkeypatch, _eng(agreement_id=None), None)
        with pytest.raises(AppValidationError) as exc:
            await ps._require_executed_engagement_letter("c1", "L1")
        assert "not been generated" in str(exc.value)

    async def test_a_dangling_agreement_id_blocks_billing(self, monkeypatch):
        """An id pointing at nothing is not consent either."""
        _patch(monkeypatch, _eng("gone"), None)
        with pytest.raises(AppValidationError):
            await ps._require_executed_engagement_letter("c1", "L1")

    async def test_no_accepted_engagement_blocks_billing(self, monkeypatch):
        _patch(monkeypatch, None, None)
        with pytest.raises(AppValidationError) as exc:
            await ps._require_executed_engagement_letter("c1", "L1")
        assert "No accepted engagement" in str(exc.value)

    async def test_the_two_failure_modes_say_different_things(self, monkeypatch):
        """'not signed yet' and 'never generated' need different actions from
        the lawyer. One vague error would send them chasing the wrong one."""
        _patch(monkeypatch, _eng(), {"_id": "a1", "status": AgreementStatus.PENDING.value})
        with pytest.raises(AppValidationError) as unsigned:
            await ps._require_executed_engagement_letter("c1", "L1")
        _patch(monkeypatch, _eng(agreement_id=None), None)
        with pytest.raises(AppValidationError) as missing:
            await ps._require_executed_engagement_letter("c1", "L1")
        assert str(unsigned.value) != str(missing.value)


def test_the_gate_runs_before_any_write():
    """A refused request must leave no half-made payment record behind."""
    import inspect
    src = inspect.getsource(ps.create_fee_request)
    assert src.index("_require_executed_engagement_letter") < src.index("insert_one")
