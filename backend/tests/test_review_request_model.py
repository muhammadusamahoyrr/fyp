"""Document review requests, slice 1: the stored shape and the settings.

DOCUMENT_REVIEW_REQUEST_PLAN.md §3-§4, D3, D4. No I/O: the model states the
invariants every stored row must satisfy, and the settings their defaults.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.models import review_request as rr

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
SHA = "a" * 64
KEY = "b" * 64


def row(**changes) -> dict:
    base = {"_id": "req1", "state_version": 1, "event_seq": 1, "status": "draft", "is_open": True,
            "client_id": "c1", "lawyer_id": "l1", "engagement_id": "e1", "case_id": None,
            "document_id": "d1", "revision_id": "r1", "version": 2, "pdf_sha256": SHA,
            "created_at": NOW, "updated_at": NOW, "create_idempotency_key_hash": KEY}
    return {**base, **changes}


def make(**changes):
    return rr.DocumentReviewRequest(**row(**changes))


# ── settings ────────────────────────────────────────────────────────────────

def test_the_flag_ships_off_and_retention_ships_at_30_days():
    fields = Settings.model_fields
    assert fields["document_review_requests"].default is False
    assert fields["review_request_retention_days"].default == 30


@pytest.mark.parametrize("days", [0, -1, 3651])
def test_retention_days_out_of_range_are_refused(days):
    with pytest.raises(ValidationError, match="review_request_retention_days"):
        Settings(review_request_retention_days=days)


def test_retention_days_is_configurable():
    assert Settings(review_request_retention_days=45).review_request_retention_days == 45


# ── statuses and transitions ────────────────────────────────────────────────

def test_the_lifecycle_is_exactly_the_plans():
    assert rr.OPEN_STATUSES == ("draft", "submitted", "viewed")
    assert rr.TERMINAL_STATUSES == ("accepted", "declined", "cancelled")
    assert set(rr.TRANSITIONS) == {s.value for s in rr.ReviewRequestStatus}
    assert rr.TRANSITIONS["draft"] == {"submitted", "cancelled"}
    assert rr.TRANSITIONS["submitted"] == {"viewed", "accepted", "declined", "cancelled"}
    assert rr.TRANSITIONS["viewed"] == {"accepted", "declined", "cancelled"}


@pytest.mark.parametrize("terminal", ["accepted", "declined", "cancelled"])
def test_a_terminal_request_never_changes_status_again(terminal):
    assert rr.TRANSITIONS[terminal] == frozenset()
    for to in rr.TRANSITIONS:
        assert not rr.can_transition(terminal, to)


def test_d4_an_accepted_request_cannot_be_cancelled():
    assert not rr.can_transition("accepted", "cancelled")


@pytest.mark.parametrize("from_, to", [("draft", "viewed"), ("draft", "accepted"), ("viewed", "submitted"),
                                       ("submitted", "draft"), ("viewed", "viewed")])
def test_transitions_the_plan_does_not_have_are_refused(from_, to):
    assert not rr.can_transition(from_, to)


def test_a_draft_is_never_visible_to_the_lawyer():
    assert "draft" not in rr.LAWYER_VISIBLE_STATUSES


def test_is_open_follows_the_status_and_rejects_unknown_ones():
    assert rr.is_open("viewed") and not rr.is_open("accepted")
    with pytest.raises(ValueError):
        rr.is_open("pending")


def test_the_frozen_version_is_revision_version_and_hash():
    assert rr.FROZEN_VERSION_FIELDS == ("revision_id", "version", "pdf_sha256")


# ── the stored request: invariants ──────────────────────────────────────────

def test_a_valid_draft_and_a_valid_submitted_request():
    assert make().status == rr.ReviewRequestStatus.DRAFT
    sub = make(status="submitted", submitted_at=NOW, note="Please check clause 3.", focus=["rent clause"])
    assert sub.is_open and sub.focus == ["rent clause"]


@pytest.mark.parametrize("changes, message", [
    ({"is_open": False}, "is_open"),
    ({"status": "accepted", "is_open": True, "submitted_at": NOW, "decided_at": NOW}, "is_open"),
    ({"pdf_sha256": "XYZ"}, "64 lowercase hex"),
    ({"create_idempotency_key_hash": "raw-idempotency-key"}, "64 lowercase hex"),
    ({"submitted_at": NOW}, "a draft has not been submitted"),
    ({"status": "submitted"}, "submitted_at"),
    ({"status": "accepted", "is_open": False, "submitted_at": NOW}, "decided_at"),
    ({"decline_reason": "busy"}, "decline_reason belongs"),
    ({"status": "cancelled", "is_open": False, "cancelled_at": NOW}, "cancel_reason"),
    ({"cancel_reason": "client_cancelled"}, "cancel fields belong"),
    ({"focus": ["x" * 121]}, "focus item"),
    ({"focus": ["  "]}, "focus item"),
    ({"focus": ["a", "b", "c", "d", "e", "f"]}, "at most 5"),
    ({"note": "n" * 2001}, "at most 2000"),
    ({"version": 0}, "greater than or equal to 1"),
    ({"surprise": 1}, "Extra inputs"),
])
def test_a_row_that_breaks_an_invariant_is_refused(changes, message):
    with pytest.raises(ValidationError, match=message):
        make(**changes)


def test_d3_retention_fields_go_together_and_only_on_an_accepted_request():
    accepted = dict(status="accepted", is_open=False, submitted_at=NOW, decided_at=NOW)
    ok = make(**accepted, retention_started_at=NOW, retention_until=NOW + timedelta(days=30),
              retention_reason="engagement_ended")
    assert ok.retention_reason == rr.RetentionReason.ENGAGEMENT_ENDED
    with pytest.raises(ValidationError, match="go together"):
        make(**accepted, retention_started_at=NOW)
    with pytest.raises(ValidationError, match="after retention_started_at"):
        make(**accepted, retention_started_at=NOW, retention_until=NOW, retention_reason="document_deleted")
    with pytest.raises(ValidationError, match="only to an accepted"):
        make(status="declined", is_open=False, submitted_at=NOW, decided_at=NOW,
             retention_started_at=NOW, retention_until=NOW + timedelta(days=30),
             retention_reason="engagement_ended")


def test_a_draft_the_system_cancelled_needs_no_submission_time():
    cancelled = make(status="cancelled", is_open=False, cancelled_at=NOW, cancel_reason="engagement_ended")
    assert cancelled.submitted_at is None


# ── audit events ────────────────────────────────────────────────────────────

def event(**changes):
    base = {"_id": "ev1", "request_id": "req1", "seq": 1, "type": "submitted", "actor_id": "c1",
            "actor_role": "client", "at": NOW, "from_status": "draft", "to_status": "submitted",
            "detail": {"revision_id": "r1", "pdf_sha256": SHA}}
    return rr.ReviewRequestEvent(**{**base, **changes})


def test_an_event_holds_ids_hashes_and_codes_only():
    assert event().detail["revision_id"] == "r1"
    for leaky in ({"note": "please check"}, {"decline_reason": "I am busy"}, {"text": "clause 3"}):
        with pytest.raises(ValidationError, match="ids, hashes and codes"):
            event(detail=leaky)


def test_only_a_system_event_has_no_actor():
    assert event(actor_id=None, actor_role="system", type="cancelled", from_status="submitted",
                 to_status="cancelled", detail={"cancel_reason": "engagement_ended"}).actor_id is None
    with pytest.raises(ValidationError, match="system"):
        event(actor_id=None)
    with pytest.raises(ValidationError, match="system"):
        event(actor_role="system")


def test_an_event_cannot_record_a_transition_that_does_not_exist():
    with pytest.raises(ValidationError, match="does not exist"):
        event(from_status="accepted", to_status="cancelled", type="cancelled")
