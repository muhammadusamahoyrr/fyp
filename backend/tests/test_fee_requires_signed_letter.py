"""Billing no longer requires a signed engagement letter -- and the hole the
letter once closed stays closed.

HISTORY. This file used to pin `_require_executed_engagement_letter`. The letter
was then the only place the client agreed to a price: a lawyer accepted an
engagement, set a fee of Rs 500,000 the client had never seen, and raised a fee
request against it with the letter unsigned -- HTTP 200.

NOW (AGREEMENTS_PRODUCT_PLAN.md §17 R5-3, R3-25; Gate 2 Step 4). New
engagements generate no letter, and the letter gate is removed. The client's
consent is recorded by the two-step flow itself: the lawyer PROPOSES a fee, the
client ACCEPTS it, and only an accepted (or completed) engagement bills. So the
live-proven hole is closed by the engagement's status, not by a letter -- which
is what `test_a_fee_the_client_has_not_accepted_is_still_refused` pins.

Unit-level: the engagement collection is stubbed, so these run without Mongo.
The integration coverage of the predicate is test_fee_billing_predicate.py.
"""
import pytest

from app.core.constants import EngagementStatus
from app.core.exceptions import AppValidationError, ForbiddenError
from app.services import payment_service as ps

CASE = {"_id": "c1", "client_id": "C1", "lawyer_id": "L1"}


def _eng(status=EngagementStatus.ACCEPTED.value, agreement_id="a1"):
    return {"_id": "e1", "case_id": "c1", "lawyer_id": "L1", "client_id": "C1",
            "status": status, "agreement_id": agreement_id}


class _Col:
    def __init__(self, doc): self._doc = doc
    async def find_one(self, *a, **k): return self._doc


def _patch(monkeypatch, eng):
    monkeypatch.setattr(ps, "get_engagements_col", lambda: _Col(eng))


class TestNoLetterGate:
    async def test_an_accepted_engagement_bills_whatever_its_letter_says(self, monkeypatch):
        """Formerly: a pending letter blocked billing. The letter is not read."""
        _patch(monkeypatch, _eng())
        assert (await ps._require_billable_engagement("e1", CASE, "L1"))["_id"] == "e1"

    async def test_an_engagement_with_no_letter_at_all_bills(self, monkeypatch):
        """Formerly: a missing letter blocked billing. It is now the NORMAL state."""
        _patch(monkeypatch, _eng(agreement_id=None))
        assert (await ps._require_billable_engagement("e1", CASE, "L1"))["_id"] == "e1"

    async def test_a_dangling_agreement_id_does_not_block_billing(self, monkeypatch):
        """Formerly: an id pointing at nothing blocked billing."""
        _patch(monkeypatch, _eng(agreement_id="gone"))
        assert (await ps._require_billable_engagement("e1", CASE, "L1"))["_id"] == "e1"

    def test_the_letter_gate_is_gone(self):
        assert not hasattr(ps, "_require_executed_engagement_letter")
        # Billing no longer reads the agreements collection at all.
        assert not hasattr(ps, "get_agreements_col")


class TestTheConsentStillRequired:
    async def test_a_fee_the_client_has_not_accepted_is_still_refused(self, monkeypatch):
        """THE LIVE-PROVEN HOLE, restated. Terms the lawyer proposed and the
        client never accepted authorise no fee -- letter or no letter."""
        _patch(monkeypatch, _eng(status=EngagementStatus.TERMS_PROPOSED.value))
        with pytest.raises(AppValidationError, match="not accepted"):
            await ps._require_billable_engagement("e1", CASE, "L1")

    async def test_no_engagement_is_still_refused(self, monkeypatch):
        """Formerly: "no billable engagement with an executed letter"."""
        _patch(monkeypatch, None)
        with pytest.raises(ForbiddenError):
            await ps._require_billable_engagement("e1", CASE, "L1")


def test_the_gate_runs_before_any_write():
    """A refused request must leave no half-made payment record behind."""
    import inspect
    src = inspect.getsource(ps.create_fee_request)
    assert src.index("_require_billable_engagement") < src.index("insert_one")
    assert "_require_executed_engagement_letter" not in src
