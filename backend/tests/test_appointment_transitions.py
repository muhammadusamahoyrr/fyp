"""The appointment state machine: which transitions, by whom, and under what race.

Phase 2 of the appointment remediation. Four defects are pinned here, and each
was reachable through the live API:

  1. `update_status` filtered on `{"_id": appt_id}` alone, carried no expected
     status, and every caller discarded the bool it returned. Two lawyers
     confirming the same request both read PENDING, both validated, both wrote,
     and both notified the client.

  2. Admin authorisation was the ABSENCE of a rule. `get_appointment` and
     `cancel_appointment` tested for client and for lawyer; an admin failed
     both tests and fell past them into full access nobody had written down.

  3. A notification failure turned a COMMITTED transition into an API error,
     so the caller was told their cancellation failed after it had succeeded —
     and retrying then met a stale-state conflict.

  4. `meeting_link` was validated by `max_length` only, and is rendered into an
     `href`. A `javascript:` link is stored by one party and clicked by the
     other.

The concurrency tests run real concurrent coroutines against real Mongo. A test
that serialises the two calls cannot see the defect, because the defect IS the
interleaving.
"""
import asyncio
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.core.constants import AppointmentMode, AppointmentStatus
from app.core.exceptions import AppValidationError, ConflictError, ForbiddenError
from app.services import appointment_transitions as transitions

pytestmark = pytest.mark.integration

PENDING = AppointmentStatus.PENDING
CONFIRMED = AppointmentStatus.CONFIRMED
CANCELLED = AppointmentStatus.CANCELLED
COMPLETED = AppointmentStatus.COMPLETED
NO_SHOW = AppointmentStatus.NO_SHOW


@pytest.fixture
async def parties(app_indexes):
    from app.db.collections import get_appointments_col, get_users_col

    tag = secrets.token_hex(4)
    lawyer_id, client_id = f"TR-L-{tag}", f"TR-C-{tag}"
    other_id, admin_id = f"TR-X-{tag}", f"TR-A-{tag}"
    now = datetime.now(timezone.utc)
    await get_users_col().insert_many([
        {"_id": lawyer_id, "role": "lawyer", "is_active": True,
         "email": f"tr-l-{tag}@test.invalid", "full_name": "Adv Transition",
         "province": "punjab", "created_at": now,
         "lawyer_profile": {"specializations": ["criminal"], "kyc_verified": True,
                            "rating": 4.0, "total_reviews": 0,
                            "availability": True, "experience_years": 5}},
        {"_id": client_id, "role": "client", "is_active": True,
         "email": f"tr-c-{tag}@test.invalid", "full_name": "Client Transition",
         "created_at": now},
        {"_id": other_id, "role": "client", "is_active": True,
         "email": f"tr-x-{tag}@test.invalid", "full_name": "Unrelated Client",
         "created_at": now},
        {"_id": admin_id, "role": "admin", "is_active": True,
         "email": f"tr-a-{tag}@test.invalid", "full_name": "The Admin",
         "created_at": now},
    ])
    yield {"lawyer_id": lawyer_id, "client_id": client_id,
           "other_id": other_id, "admin_id": admin_id}
    await get_users_col().delete_many(
        {"_id": {"$in": [lawyer_id, client_id, other_id, admin_id]}})
    await get_appointments_col().delete_many({"client_id": client_id})


def _slot(hours_ahead: int = 48) -> datetime:
    base = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    return base.replace(minute=0, second=0, microsecond=0)


async def _book(parties, when=None, **over):
    from app.services import appointment_service
    kwargs = {"client_id": parties["client_id"], "lawyer_id": parties["lawyer_id"],
              "case_id": None, "scheduled_at": when or _slot(),
              "duration_minutes": 30, "mode": AppointmentMode.VIDEO, "notes": None}
    kwargs.update(over)
    return await appointment_service.book_appointment(**kwargs)


async def _elapse(appt_id: str, *, started_minutes_ago: int = 45,
                  duration_minutes: int = 30) -> None:
    """Move an appointment's window into the past.

    Booking refuses a past `scheduled_at`, so no API call can produce this
    state — only the clock can, and a test cannot wait for it.
    """
    from app.db.collections import get_appointments_col

    start = datetime.now(timezone.utc) - timedelta(minutes=started_minutes_ago)
    await get_appointments_col().update_one(
        {"_id": appt_id},
        {"$set": {"scheduled_at": start,
                  "end_at": start + timedelta(minutes=duration_minutes)}},
    )


async def _observed_version(appt_id: str) -> int:
    """The schedule version a caller would have READ before acting.

    Exactly what the lawyer's page does: load the row, then accept the version
    it displayed. Read explicitly here because the service refuses to guess one
    — a default inside `confirm_appointment` would pin every write to whatever
    the row says on arrival, which is the unconditional write the version
    exists to prevent.
    """
    from app.db.collections import get_appointments_col

    row = await get_appointments_col().find_one({"_id": appt_id})
    return (row or {}).get("schedule_version", 0)


async def _confirm(appt_id: str, lawyer_id: str, version=None):
    """Confirm at the observed version, or at one the test names deliberately."""
    from app.services import appointment_service

    if version is None:
        version = await _observed_version(appt_id)
    return await appointment_service.confirm_appointment(
        appt_id, lawyer_id, expected_version=version)


async def _status(appt_id: str) -> str:
    from app.db.collections import get_appointments_col
    return (await get_appointments_col().find_one({"_id": appt_id}))["status"]


# ── 1. The table itself ──────────────────────────────────────────────────────
#
# Pure, so it is exhaustive. Every one of the 25 ordered pairs is decided here,
# which is what makes the table a specification rather than a summary of
# whatever the four service functions happen to do.

def test_every_pair_of_statuses_is_decided_one_way_or_the_other():
    allowed = {
        (PENDING, CONFIRMED), (PENDING, CANCELLED),
        (CONFIRMED, CANCELLED), (CONFIRMED, COMPLETED), (CONFIRMED, NO_SHOW),
    }
    for source in AppointmentStatus:
        for target in AppointmentStatus:
            assert transitions.is_allowed(source, target) is ((source, target) in allowed), (
                f"{source.value} -> {target.value} is not what the table says")


def test_an_ended_appointment_has_nowhere_left_to_go():
    """What happened at a consultation is not revised through this API.

    A completed appointment gates the client's right to review the lawyer
    (`exists_completed`), so a reversible outcome would make that gate
    reversible too.
    """
    assert transitions.TERMINAL == frozenset({COMPLETED, CANCELLED, NO_SHOW})
    for status in transitions.TERMINAL:
        assert transitions.allowed_from(status) == frozenset()


def test_a_status_cannot_transition_to_itself():
    """Confirming an already-confirmed appointment is a conflict, not a no-op.

    Treating it as success would hide exactly the double-submit this phase
    exists to catch, and would notify the client twice.
    """
    for status in AppointmentStatus:
        assert not transitions.is_allowed(status, status)


def test_sources_for_reports_the_legal_sources_of_a_target():
    """A query over the table. This test used to be named for a claim that was
    false — that `sources_for` is what the CAS filter is built from. It is not,
    and `test_the_cas_pins_the_observed_status_not_the_legal_set` below is the
    test for what the CAS actually does."""
    assert transitions.sources_for(CONFIRMED) == frozenset({PENDING})
    assert transitions.sources_for(COMPLETED) == frozenset({CONFIRMED})
    assert transitions.sources_for(NO_SHOW) == frozenset({CONFIRMED})
    assert transitions.sources_for(CANCELLED) == frozenset({PENDING, CONFIRMED})


async def test_the_cas_pins_the_observed_status_not_the_legal_set(parties):
    """The predicate must be the world the caller SAW, not the set of worlds
    that would have been acceptable.

    CANCELLED is reachable from both PENDING and CONFIRMED, so
    `sources_for(CANCELLED)` is `{pending, confirmed}`. A CAS built from that
    set would let a caller who read PENDING write a cancellation over an
    appointment that had since been CONFIRMED by someone else — matching on a
    status it never observed. Pinning `[source]` is what makes the loser lose.
    """
    from app.repositories.appointment_repo import AppointmentRepository
    from app.services import appointment_service

    repo = AppointmentRepository()
    appt = await _book(parties)
    actor = {"lawyer_id": parties["lawyer_id"]}

    # What the caller observed: PENDING. Then the world moves underneath it.
    observed = PENDING
    await _confirm(appt["id"], parties["lawyer_id"])

    pinned = await repo.compare_and_set(appt["id"], [observed], CANCELLED, actor)
    assert pinned is None, (
        "a write pinned to the observed status must not match a row that moved")
    assert await _status(appt["id"]) == CONFIRMED.value

    # And the widened predicate is exactly what would have gone wrong.
    widened = await repo.compare_and_set(
        appt["id"], transitions.sources_for(CANCELLED), CANCELLED, actor)
    assert widened is not None, (
        "demonstrating the hazard: the legal-set filter matches a status the "
        "caller never saw — which is why production does not use it")


def test_timing_rules_are_about_the_clock_not_the_status():
    now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    hour_ago, hour_ahead = now - timedelta(hours=1), now + timedelta(hours=1)

    # Confirming needs a future slot; the other two need a past one.
    assert transitions.timing_error(CONFIRMED, hour_ahead, hour_ahead, now) is None
    assert transitions.timing_error(CONFIRMED, hour_ago, hour_ago, now) is not None

    assert transitions.timing_error(COMPLETED, hour_ago, hour_ago, now) is None
    assert transitions.timing_error(COMPLETED, hour_ago, hour_ahead, now) is not None, (
        "an appointment that started but has not ended is not complete")

    assert transitions.timing_error(NO_SHOW, hour_ago, hour_ahead, now) is None, (
        "a client who has not arrived is a no-show from the START, not the end")
    assert transitions.timing_error(NO_SHOW, hour_ahead, hour_ahead, now) is not None

    # Cancelling is never premature. A client cancelling too LATE is a separate,
    # role-specific rule that lives in the service.
    assert transitions.timing_error(CANCELLED, hour_ahead, hour_ahead, now) is None
    assert transitions.timing_error(CANCELLED, hour_ago, hour_ago, now) is None


# ── 2. Atomicity ─────────────────────────────────────────────────────────────

async def test_two_simultaneous_confirms_produce_one_confirmation(parties):
    """The race the old `update_status` could not lose.

    Both callers read PENDING, both validated against it, both wrote. Here the
    expected status rides in the filter, so the second write matches nothing.
    """
    from app.services import appointment_service

    appt = await _book(parties)

    results = await asyncio.gather(
        _confirm(appt["id"], parties["lawyer_id"]),
        _confirm(appt["id"], parties["lawyer_id"]),
        return_exceptions=True,
    )

    winners = [r for r in results if not isinstance(r, Exception)]
    losers = [r for r in results if isinstance(r, Exception)]
    assert len(winners) == 1, "exactly one confirm may succeed"
    assert len(losers) == 1
    assert isinstance(losers[0], ConflictError), (
        f"the loser must be told it lost, not silently succeed: {losers[0]!r}")
    assert await _status(appt["id"]) == CONFIRMED.value


async def test_the_compare_and_set_itself_is_exclusive(parties):
    """The guarantee, tested without relying on the scheduler interleaving.

    `asyncio.gather` MAY serialise two coroutines, and if it does, the loser is
    stopped by the pre-check and the atomic write is never the thing under
    test. Here both writes are issued from the same known-PENDING view, which
    is precisely the state the old code could reach twice — so exactly one of
    them has to match.
    """
    from app.repositories.appointment_repo import AppointmentRepository

    repo = AppointmentRepository()
    appt = await _book(parties)
    actor = {"lawyer_id": parties["lawyer_id"]}

    first = await repo.compare_and_set(appt["id"], [PENDING], CONFIRMED, actor)
    second = await repo.compare_and_set(appt["id"], [PENDING], CONFIRMED, actor)

    assert first is not None, "the first write must land"
    assert second is None, "the second must match nothing, not overwrite the first"
    assert first["status"] == CONFIRMED.value


async def test_a_compare_and_set_refuses_an_actor_who_is_not_a_party(parties):
    """The actor predicate is in the FILTER, so it cannot be skipped by a caller
    that forgot to check first."""
    from app.repositories.appointment_repo import AppointmentRepository

    repo = AppointmentRepository()
    appt = await _book(parties)

    result = await repo.compare_and_set(
        appt["id"], [PENDING], CONFIRMED, {"lawyer_id": "some-other-lawyer"})

    assert result is None
    assert await _status(appt["id"]) == PENDING.value


async def test_a_cancel_and_a_complete_cannot_both_win(parties):
    """Two different terminal states competing for one confirmed appointment.

    Whichever lands first, the other must fail — and the stored status must be
    the one that was reported as successful, not a blend of the two.
    """
    from app.services import appointment_service

    appt = await _book(parties)
    await _confirm(appt["id"], parties["lawyer_id"])
    await _elapse(appt["id"])  # so completion is not premature

    results = await asyncio.gather(
        appointment_service.cancel_appointment(
            appt_id=appt["id"], user_id=parties["lawyer_id"],
            user_role="lawyer", reason="conflict"),
        appointment_service.complete_appointment(
            appt_id=appt["id"], lawyer_id=parties["lawyer_id"],
            lawyer_notes=None, meeting_link=None),
        return_exceptions=True,
    )

    winners = [r for r in results if not isinstance(r, Exception)]
    assert len(winners) == 1, f"both transitions applied: {results!r}"
    assert await _status(appt["id"]) == winners[0]["status"], (
        "the caller was told one thing and the database recorded another")


async def test_the_returned_document_is_the_stored_one(parties):
    """The service used to hand-patch the dict it had READ and return that.

    So the response described what the request intended rather than what is in
    the database — the precise discrepancy a concurrent transition produces.
    """
    from app.services import appointment_service

    appt = await _book(parties)
    out = await _confirm(appt["id"], parties["lawyer_id"])

    assert out["status"] == await _status(appt["id"])
    assert out["updated_at"] is not None


# ── 3. Denial does not leak ──────────────────────────────────────────────────

async def test_an_unrelated_client_cannot_tell_a_real_appointment_from_a_fake_one(parties):
    """The 404/403 split IS the leak. Both collapse to one 403.

    Without this, anyone can walk appointment ids and learn which exist — and
    with a lawyer id in hand, when that lawyer is busy.
    """
    from app.services import appointment_service

    appt = await _book(parties)

    with pytest.raises(ForbiddenError) as real:
        await appointment_service.get_appointment(
            appt_id=appt["id"], user_id=parties["other_id"], user_role="client")
    with pytest.raises(ForbiddenError) as imaginary:
        await appointment_service.get_appointment(
            appt_id="no-such-appointment-id", user_id=parties["other_id"],
            user_role="client")

    assert real.value.status_code == imaginary.value.status_code == 403
    assert real.value.detail == imaginary.value.detail, (
        "the two responses must be indistinguishable to the caller")


async def test_a_stale_view_is_a_conflict_not_a_denial(parties):
    """409 and 403 answer different questions, and the caller's next move differs.

    A party to the appointment who is merely out of date must be told to
    re-read. Answering 403 would tell them they are not on their own
    appointment.
    """
    from app.services import appointment_service

    appt = await _book(parties)
    await appointment_service.cancel_appointment(
        appt_id=appt["id"], user_id=parties["client_id"],
        user_role="client", reason=None)

    with pytest.raises(ConflictError) as exc:
        await _confirm(appt["id"], parties["lawyer_id"])

    assert exc.value.status_code == 409
    assert "cancelled" in exc.value.detail


async def test_another_lawyer_transitioning_is_refused_without_a_status_hint(parties):
    """A lawyer who is not on the appointment learns nothing about its state."""
    from app.services import appointment_service

    appt = await _book(parties)

    with pytest.raises(ForbiddenError) as exc:
        await _confirm(appt["id"], "some-other-lawyer")

    assert exc.value.status_code == 403
    for status in AppointmentStatus:
        assert status.value not in exc.value.detail.lower()
    assert await _status(appt["id"]) == PENDING.value


# ── 4. Admin is a rule, not a gap ────────────────────────────────────────────

async def test_an_admin_can_read_any_appointment_by_stated_rule(parties):
    """Unchanged behaviour, now on purpose.

    The point of the test is not that admins have access — it is that the
    access is written down, so removing it is a decision someone makes rather
    than a side effect of adding a role.
    """
    from app.services import appointment_service

    appt = await _book(parties)

    out = await appointment_service.get_appointment(
        appt_id=appt["id"], user_id=parties["admin_id"], user_role="admin")

    assert out["id"] == appt["id"]


async def test_an_admin_cancellation_tells_both_parties(parties):
    """An admin has two counterparties, not one.

    The old code picked "the other party" from a client/lawyer binary, so an
    admin cancellation notified the client and left the lawyer holding a slot
    for a meeting that no longer existed.
    """
    from app.db.collections import get_notifications_col
    from app.services import appointment_service

    appt = await _book(parties)
    await appointment_service.cancel_appointment(
        appt_id=appt["id"], user_id=parties["admin_id"],
        user_role="admin", reason="policy")

    told = await get_notifications_col().find(
        {"payload.appointment_id": appt["id"]}).to_list(length=20)
    recipients = {n["user_id"] for n in told}

    assert parties["client_id"] in recipients
    assert parties["lawyer_id"] in recipients


async def test_an_unknown_role_is_refused_rather_than_inheriting_admin_access(parties):
    """The failure mode the implicit rule had.

    Any role that was neither "client" nor "lawyer" fell through both checks
    into full access. A role added later would have inherited it silently.
    """
    from app.services import appointment_service

    appt = await _book(parties)

    with pytest.raises(ForbiddenError):
        await appointment_service.get_appointment(
            appt_id=appt["id"], user_id=parties["admin_id"], user_role="auditor")


async def test_an_admin_listing_is_refused_rather_than_answered_empty(parties):
    """An empty success is the worst answer, because it looks like data.

    An admin used to be routed through the LAWYER query against their own id,
    so they were shown an empty page as though there were no appointments.
    """
    from app.services import appointment_service

    await _book(parties)

    with pytest.raises(ForbiddenError):
        await appointment_service.list_appointments(
            user_id=parties["admin_id"], user_role="admin",
            status=None, page=1, page_size=10)


# ── 5. A delivery failure is not a transition failure ────────────────────────

async def test_a_notification_failure_does_not_undo_a_committed_transition(parties, monkeypatch):
    """The transition is already in the database by the time delivery runs.

    Answering the caller with an error for work that succeeded is worse than
    losing the notification: the caller's sensible response is to retry, and
    the retry is then refused as a stale-state conflict.
    """
    from app.services import appointment_service, notification_service

    appt = await _book(parties)

    async def _explode(**kwargs):
        raise RuntimeError("mongodb://user:password@host/db is unreachable")

    monkeypatch.setattr(notification_service, "create_notification", _explode)

    out = await _confirm(appt["id"], parties["lawyer_id"])

    assert out["status"] == CONFIRMED.value
    assert await _status(appt["id"]) == CONFIRMED.value


async def test_a_notification_failure_is_logged_without_the_driver_message(parties, monkeypatch, caplog):
    """Driver errors carry URIs and credentials. Only the class is recorded."""
    import logging

    from app.services import appointment_service, notification_service

    appt = await _book(parties)
    secret = "mongodb://user:hunter2@cluster.example.net/db"

    async def _explode(**kwargs):
        raise RuntimeError(f"{secret} is unreachable")

    monkeypatch.setattr(notification_service, "create_notification", _explode)

    with caplog.at_level(logging.WARNING, logger="app.services.appointment_service"):
        await _confirm(appt["id"], parties["lawyer_id"])

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "appointment_notification_failed" in logged
    assert "RuntimeError" in logged, "the exception class is the useful part"
    assert secret not in logged
    assert "hunter2" not in logged


# ── 6. The meeting link is executable input ──────────────────────────────────

@pytest.mark.parametrize("link", [
    "javascript:alert(document.cookie)",
    "JavaScript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "http://meet.example.com/room",   # credential-bearing URL in clear text
    "https:no-host",
    "not a url at all",
])
def test_a_meeting_link_that_is_not_an_https_url_is_refused(link):
    """`ModTracking.jsx` renders this into an `href`, so it is clicked, not read.

    An allowlist of one scheme, so a scheme nobody thought of is refused by
    default rather than admitted by default.
    """
    from pydantic import ValidationError

    from app.schemas.appointment import CompleteAppointmentRequest

    with pytest.raises(ValidationError):
        CompleteAppointmentRequest(meeting_link=link)


@pytest.mark.parametrize("link", [
    "https://meet.example.com/abc-def",
    "https://zoom.us/j/123456789?pwd=x",
])
def test_a_real_https_link_is_accepted(link):
    from app.schemas.appointment import CompleteAppointmentRequest

    assert CompleteAppointmentRequest(meeting_link=link).meeting_link == link


def test_a_cleared_meeting_link_is_absence_not_a_validation_error():
    """Otherwise the field can be set but never unset."""
    from app.schemas.appointment import CompleteAppointmentRequest

    assert CompleteAppointmentRequest(meeting_link=None).meeting_link is None
    assert CompleteAppointmentRequest(meeting_link="   ").meeting_link is None


# ── 7. The transitions that had no coverage at all ───────────────────────────

async def test_confirming_a_slot_that_has_already_passed_is_refused(parties):
    """It commits nobody to anything — it only produces a confirmed row for a
    meeting that cannot happen, which then has to be cancelled to clear it."""
    from app.services import appointment_service

    appt = await _book(parties)
    await _elapse(appt["id"])

    with pytest.raises(AppValidationError, match="already passed"):
        await _confirm(appt["id"], parties["lawyer_id"])


async def test_a_consultation_cannot_be_completed_before_it_ends(parties):
    from app.services import appointment_service

    appt = await _book(parties)
    await _confirm(appt["id"], parties["lawyer_id"])

    with pytest.raises(AppValidationError, match="has not finished"):
        await appointment_service.complete_appointment(
            appt_id=appt["id"], lawyer_id=parties["lawyer_id"],
            lawyer_notes=None, meeting_link=None)


async def test_a_pending_appointment_can_no_longer_be_completed(parties):
    """A tightening. `complete` used to accept PENDING, so a lawyer could
    complete a consultation nobody had ever confirmed — while `no_show`, the
    other outcome of the same meeting, required CONFIRMED. The two ends of one
    question disagreed."""
    from app.services import appointment_service

    appt = await _book(parties)
    await _elapse(appt["id"])

    with pytest.raises(ConflictError, match="pending"):
        await appointment_service.complete_appointment(
            appt_id=appt["id"], lawyer_id=parties["lawyer_id"],
            lawyer_notes=None, meeting_link=None)


async def test_a_confirmed_consultation_completes_after_it_ends(parties):
    from app.services import appointment_service

    appt = await _book(parties)
    await _confirm(appt["id"], parties["lawyer_id"])
    await _elapse(appt["id"])

    out = await appointment_service.complete_appointment(
        appt_id=appt["id"], lawyer_id=parties["lawyer_id"],
        lawyer_notes="Advised on filing", meeting_link="https://meet.example.com/x")

    assert out["status"] == COMPLETED.value
    assert out["lawyer_notes"] == "Advised on filing"
    assert out["meeting_link"] == "https://meet.example.com/x"


async def test_a_lawyer_may_cancel_inside_the_window_a_client_may_not(parties):
    """The cutoff is the CLIENT's rule. It had no test on either side."""
    from app.services import appointment_service

    # Aligned, because the service now refuses sub-minute precision on a
    # direct call — an unaligned row is invisible to the overlap guard. Still
    # comfortably inside the two-hour cutoff, which is what this pins.
    soon = (datetime.now(timezone.utc) + timedelta(minutes=90)).replace(
        minute=0, second=0, microsecond=0)
    appt = await _book(parties, soon)

    with pytest.raises(AppValidationError, match="hours before"):
        await appointment_service.cancel_appointment(
            appt_id=appt["id"], user_id=parties["client_id"],
            user_role="client", reason=None)

    out = await appointment_service.cancel_appointment(
        appt_id=appt["id"], user_id=parties["lawyer_id"],
        user_role="lawyer", reason="court ran over")

    assert out["status"] == CANCELLED.value
    assert out["cancelled_by"] == "lawyer"


async def test_a_cancelled_appointment_cannot_be_cancelled_again(parties):
    from app.services import appointment_service

    appt = await _book(parties)
    await appointment_service.cancel_appointment(
        appt_id=appt["id"], user_id=parties["client_id"],
        user_role="client", reason=None)

    with pytest.raises(ConflictError, match="already cancelled"):
        await appointment_service.cancel_appointment(
            appt_id=appt["id"], user_id=parties["client_id"],
            user_role="client", reason=None)
