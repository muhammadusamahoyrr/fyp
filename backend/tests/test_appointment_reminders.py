"""Reminders for confirmed consultations, and the reschedule that breaks naive
idempotency.

`APPOINTMENT_REMINDER` existed in `constants.py` long before this module and
was emitted NOWHERE — a declared notification type nothing ever sent. Nothing
sends it now either: every test below drives the function directly, because no
scheduler runs it and no flag enables it.

THE HARD PART IS NOT THE CLOCK, IT IS THE IDENTITY.

`logical_event_id` is unique GLOBALLY, so a reminder's id must name the
appointment, the window, the RECIPIENT and the SCHEDULE VERSION. Drop the
recipient and whoever is notified first claims the id, silently swallowing the
other party's notice. Drop the version and a client who moves their
consultation from Tuesday to Thursday is never reminded about Thursday: the
Tuesday reminder already holds the id and the system considers the job done.
Both failures are tested here by constructing them.
"""
import asyncio
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.core.constants import AppointmentStatus, NotificationType
from app.core.exceptions import AppValidationError
from app.services import appointment_reminders as reminders

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
async def parties(app_indexes):
    from app.db.collections import (
        get_appointments_col,
        get_notifications_col,
        get_users_col,
    )

    tag = secrets.token_hex(4)
    lawyer_id, client_id = f"RM-L-{tag}", f"RM-C-{tag}"
    now = datetime.now(timezone.utc)

    await get_users_col().insert_many([
        {"_id": lawyer_id, "role": "lawyer", "is_active": True,
         "email": f"{lawyer_id}@test.invalid", "full_name": "Adv One",
         "province": "punjab", "created_at": now,
         "lawyer_profile": {"specializations": ["criminal"],
                            "kyc_verified": True, "rating": 4.0,
                            "total_reviews": 0, "availability": True,
                            "experience_years": 5}},
        {"_id": client_id, "role": "client", "is_active": True,
         "email": f"{client_id}@test.invalid", "full_name": "Client One",
         "created_at": now},
    ])
    yield {"lawyer_id": lawyer_id, "client_id": client_id}
    await get_users_col().delete_many({"_id": {"$in": [lawyer_id, client_id]}})
    await get_appointments_col().delete_many({"lawyer_id": lawyer_id})
    await get_notifications_col().delete_many(
        {"user_id": {"$in": [lawyer_id, client_id]}})


# Each fixture row gets its own slot sentinel: the unique indexes reject two
# ACTIVE rows for one lawyer sharing a half-hour, and several tests below need
# confirmed appointments at the same instant. The reminder path never reads
# `occupied_slots`, so a sentinel keeps an unrelated guarantee out of the way
# of the one under test rather than weakening it.
_slots = iter(range(1, 10_000))
_SLOT_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


async def _appt(parties, *, starts_in=None, at=None, status="confirmed",
                version=0, appt_id=None, **over):
    from app.db.collections import get_appointments_col

    start = at if at is not None else NOW + starts_in
    doc = {
        "_id": appt_id or f"RM-A-{secrets.token_hex(6)}",
        "client_id": parties["client_id"],
        "lawyer_id": parties["lawyer_id"],
        "case_id": None,
        "scheduled_at": start,
        "end_at": start + timedelta(hours=1),
        "duration_minutes": 60,
        "status": status,
        "mode": "video",
        "timezone": "Asia/Karachi",
        "schedule_version": version,
        "notes": None,
        "lawyer_notes": None,
        "cancel_reason": None,
        "cancelled_by": None,
        "meeting_link": None,
        "created_at": start - timedelta(days=2),
        "updated_at": start,
        "occupied_slots": [_SLOT_EPOCH + timedelta(minutes=30 * next(_slots))],
    }
    doc.update(over)
    await get_appointments_col().insert_one(doc)
    return doc["_id"]


async def _run(**kw):
    kw.setdefault("now", NOW)
    return await reminders.send_due_reminders(**kw)


async def _notices(appt_id=None, user_id=None):
    from app.db.collections import get_notifications_col

    query = {"type": NotificationType.APPOINTMENT_REMINDER.value}
    if appt_id:
        query["payload.appointment_id"] = appt_id
    if user_id:
        query["user_id"] = user_id
    return await get_notifications_col().find(query).to_list(length=100)


# ── 1. Window boundaries ─────────────────────────────────────────────────────

@pytest.mark.parametrize("delta,window", [
    (timedelta(hours=24), "24h"),                       # exactly 24h — in
    (timedelta(hours=23, minutes=1), "24h"),            # just inside the near edge
    (timedelta(hours=1), "1h"),                         # exactly 1h — in
    (timedelta(minutes=1), "1h"),                       # just inside
])
async def test_an_appointment_inside_a_window_is_due(parties, delta, window):
    appt = await _appt(parties, starts_in=delta)

    report = await _run(apply=True)

    assert report["sent"] == 2, report
    assert len(await _notices(appt)) == 2


@pytest.mark.parametrize("delta", [
    timedelta(hours=23),            # the near edge of T-24h is EXCLUSIVE
    timedelta(hours=24, seconds=1),  # past the far edge
    timedelta(hours=12),            # between the windows
    timedelta(hours=2),             # between the windows
    timedelta(0),                   # starting exactly now
    timedelta(minutes=-30),         # already started
    timedelta(days=-2),             # long past
])
async def test_an_appointment_outside_both_windows_is_not_due(parties, delta):
    appt = await _appt(parties, starts_in=delta)

    report = await _run(apply=True)

    assert report["sent"] == 0, report
    assert await _notices(appt) == []


async def test_the_two_windows_never_overlap(parties):
    """One hour is nowhere near twenty-three, so no appointment is ever
    selected by both in a single run."""
    for delta in (timedelta(hours=23, minutes=30), timedelta(minutes=30)):
        lo24, hi24 = reminders.window_bounds("24h", NOW)
        lo1, hi1 = reminders.window_bounds("1h", NOW)
        start = NOW + delta
        in24 = lo24 < start <= hi24
        in1 = lo1 < start <= hi1
        assert not (in24 and in1)


async def test_one_now_is_pinned_for_the_whole_run(parties):
    """Every boundary is measured against a single instant, so a row cannot
    fall inside a window for one comparison and outside it for the next."""
    await _appt(parties, starts_in=timedelta(hours=24))

    report = await _run(apply=True)

    assert report["now"] == NOW


async def test_times_are_shown_in_pakistan_time(parties):
    # 04:00 UTC is 09:00 PKT. A reminder rendered in the server's zone would
    # tell both parties an hour five hours from the one they agreed.
    at = datetime(2026, 11, 11, 4, 0, tzinfo=timezone.utc)
    appt = await _appt(parties, at=at)

    await _run(apply=True, now=at - timedelta(hours=24))

    body = (await _notices(appt))[0]["body"]
    assert "09:00 PKT" in body, body


# ── 2. Only confirmed appointments ───────────────────────────────────────────

@pytest.mark.parametrize("status", ["pending", "cancelled", "completed",
                                    "no_show", "expired"])
async def test_only_confirmed_appointments_are_reminded_about(parties, status):
    appt = await _appt(parties, starts_in=timedelta(hours=24), status=status)

    report = await _run(apply=True)

    assert report["sent"] == 0
    assert await _notices(appt) == []


# ── 3. Both parties ──────────────────────────────────────────────────────────

async def test_both_parties_are_reminded(parties):
    appt = await _appt(parties, starts_in=timedelta(hours=1))

    await _run(apply=True)

    told = {n["user_id"] for n in await _notices(appt)}
    assert told == {parties["client_id"], parties["lawyer_id"]}


async def test_the_two_notices_do_not_cancel_each_other_out(parties):
    """`logical_event_id` is unique GLOBALLY, so one id per appointment would
    let whichever party was written first claim it — and the second notice
    would be swallowed as an already-delivered duplicate."""
    appt = await _appt(parties, starts_in=timedelta(hours=1))

    await _run(apply=True)

    ids = [n["logical_event_id"] for n in await _notices(appt)]
    assert len(ids) == 2
    assert len(set(ids)) == 2, ids
    assert all(i.startswith(f"appointment:{appt}:reminder:1h:v0:") for i in ids)


# ── 4. Deduplication, per window and per version ─────────────────────────────

async def test_a_second_run_does_not_remind_twice(parties):
    appt = await _appt(parties, starts_in=timedelta(hours=24))

    first = await _run(apply=True)
    second = await _run(apply=True)

    assert first["sent"] == 2
    assert second["sent"] == 0
    assert second["deduplicated"] == 2
    assert len(await _notices(appt)) == 2


async def test_the_two_windows_are_separate_reminders(parties):
    """Being reminded a day ahead does not use up the reminder an hour ahead:
    the window is part of the identity."""
    appt = await _appt(parties, starts_in=timedelta(hours=24))
    await _run(apply=True)

    # The same appointment, an hour before it starts.
    later = NOW + timedelta(hours=23)
    report = await _run(apply=True, now=later)

    assert report["sent"] == 2, report
    ids = {n["logical_event_id"] for n in await _notices(appt)}
    assert len(ids) == 4
    assert sum(":reminder:24h:" in i for i in ids) == 2
    assert sum(":reminder:1h:" in i for i in ids) == 2


async def test_rescheduling_earns_a_new_reminder(parties):
    """THE FAILURE A NAIVE ID CAUSES.

    Without the schedule version in the identity, a client who moves their
    consultation is never reminded about the new time: the old reminder holds
    the id and the system considers the job done. Here the appointment is
    genuinely rescheduled — new time, bumped version — and both parties must
    hear about it.
    """
    from app.db.collections import get_appointments_col

    appt = await _appt(parties, starts_in=timedelta(hours=24), version=0)
    await _run(apply=True)
    assert len(await _notices(appt)) == 2

    moved = NOW + timedelta(days=3)
    await get_appointments_col().update_one(
        {"_id": appt},
        {"$set": {"scheduled_at": moved, "end_at": moved + timedelta(hours=1),
                  "schedule_version": 1}})

    report = await _run(apply=True, now=moved - timedelta(hours=24))

    assert report["sent"] == 2, report
    ids = {n["logical_event_id"] for n in await _notices(appt)}
    assert sum(":v0:" in i for i in ids) == 2
    assert sum(":v1:" in i for i in ids) == 2


async def test_a_retry_of_the_same_version_does_not_duplicate(parties):
    appt = await _appt(parties, starts_in=timedelta(hours=24), version=7)

    await _run(apply=True)
    await _run(apply=True)
    await _run(apply=True)

    assert len(await _notices(appt)) == 2


async def test_the_event_id_names_all_four_parts(parties):
    assert reminders.reminder_event_id("a1", "24h", 3, "u9") == (
        "appointment:a1:reminder:24h:v3:u9")


# ── 5. The re-read, and the race it closes ───────────────────────────────────

async def test_a_cancellation_between_selection_and_sending_is_caught(parties):
    """The row was due when it was read and is not when it is sent. Reminding
    somebody about a consultation cancelled moments ago is the failure the
    re-read exists to prevent."""
    from app.db.collections import get_appointments_col
    from app.repositories.appointment_repo import AppointmentRepository

    appt = await _appt(parties, starts_in=timedelta(hours=24))
    stale = await get_appointments_col().find_one({"_id": appt})
    await get_appointments_col().update_one(
        {"_id": appt}, {"$set": {"status": "cancelled"}})

    real = AppointmentRepository.find_due_reminders

    async def _hand_back_stale(self, **kwargs):
        return [stale] if kwargs.get("latest") else []

    AppointmentRepository.find_due_reminders = _hand_back_stale
    try:
        report = await _run(apply=True)
    finally:
        AppointmentRepository.find_due_reminders = real

    assert report["stale"] >= 1, report
    assert report["sent"] == 0
    assert await _notices(appt) == []


async def test_a_reschedule_between_selection_and_sending_is_caught(parties):
    from app.db.collections import get_appointments_col
    from app.repositories.appointment_repo import AppointmentRepository

    appt = await _appt(parties, starts_in=timedelta(hours=24), version=0)
    stale = await get_appointments_col().find_one({"_id": appt})
    moved = NOW + timedelta(days=5)
    await get_appointments_col().update_one(
        {"_id": appt},
        {"$set": {"scheduled_at": moved, "schedule_version": 1}})

    real = AppointmentRepository.find_due_reminders

    async def _hand_back_stale(self, **kwargs):
        return [stale] if kwargs.get("latest") else []

    AppointmentRepository.find_due_reminders = _hand_back_stale
    try:
        report = await _run(apply=True)
    finally:
        AppointmentRepository.find_due_reminders = real

    assert report["stale"] >= 1
    assert await _notices(appt) == []


async def test_the_run_never_writes_to_an_appointment(parties):
    """Sending a reminder is not an event in the life of a consultation."""
    from app.db.collections import get_appointments_col

    appt = await _appt(parties, starts_in=timedelta(hours=1))
    before = await get_appointments_col().find_one({"_id": appt})

    await _run(apply=True)

    assert await get_appointments_col().find_one({"_id": appt}) == before


async def test_concurrent_runs_produce_no_duplicate(parties):
    """Two runs can both read "not sent" and both attempt. The unique index on
    `logical_event_id` is what makes the second a no-op — the bulk read is an
    optimisation and a reporting aid, never the guarantee."""
    appt = await _appt(parties, starts_in=timedelta(hours=24))

    await asyncio.gather(_run(apply=True), _run(apply=True))

    assert len(await _notices(appt)) == 2


# ── 6. Report-only ───────────────────────────────────────────────────────────

async def test_a_bare_run_sends_nothing_and_writes_nothing(parties):
    from app.db.collections import get_appointments_col, get_notifications_col

    appt = await _appt(parties, starts_in=timedelta(hours=24))
    before_appt = await get_appointments_col().find_one({"_id": appt})
    before_notices = await get_notifications_col().count_documents({})

    report = await reminders.send_due_reminders(now=NOW)

    assert report["applied"] is False
    assert report["sent"] == 2, "a dry run must still say what it would do"
    assert await _notices(appt) == []
    assert await get_notifications_col().count_documents({}) == before_notices
    assert await get_appointments_col().find_one({"_id": appt}) == before_appt


def test_sending_is_keyword_only_and_off_by_default():
    import inspect

    sig = inspect.signature(reminders.send_due_reminders)
    assert sig.parameters["apply"].default is False
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY
               for p in sig.parameters.values())


@pytest.mark.parametrize("bad", ["true", 1, None])
async def test_a_non_boolean_apply_is_refused(parties, bad):
    """`apply="false"` is truthy and would otherwise take the write path."""
    with pytest.raises(AppValidationError):
        await reminders.send_due_reminders(apply=bad, now=NOW)


# ── 7. The cap ───────────────────────────────────────────────────────────────

async def test_a_run_reminds_about_no_more_than_its_cap(parties):
    for i in range(5):
        await _appt(parties, starts_in=timedelta(hours=24, minutes=-i))

    report = await _run(apply=True, limit=2)

    assert report["selected"] == 2
    assert report["sent"] == 4          # two appointments, two parties each
    assert report["remaining"] >= 3


async def test_the_remainder_is_picked_up_by_the_next_run(parties):
    for i in range(4):
        await _appt(parties, starts_in=timedelta(hours=24, minutes=-i))

    first = await _run(apply=True, limit=2)
    second = await _run(apply=True, limit=2)

    assert first["sent"] == 4
    # THE CAP ADVANCED. The second run reached the two appointments the first
    # could not, rather than spending its budget re-reading handled rows —
    # which is exactly how a capped sweep stalls and never reaches the tail of
    # its window.
    assert second["sent"] == 4
    # And it says so: the four reminders already delivered are reported as
    # skipped on the way past them, not counted as fresh sends.
    assert second["deduplicated"] == 4


@pytest.mark.parametrize("bad", [0, -1, 501, 1.5, "10", None, True])
async def test_an_unusable_cap_is_refused(parties, bad):
    with pytest.raises(AppValidationError):
        await _run(apply=True, limit=bad)


# ── 8. Failure ───────────────────────────────────────────────────────────────

async def test_a_failed_send_is_retried_and_changes_no_state(parties, monkeypatch):
    from app.db.collections import get_appointments_col
    from app.services import notification_service

    appt = await _appt(parties, starts_in=timedelta(hours=24))

    async def _boom(**kwargs):
        raise RuntimeError("notification backend down")

    monkeypatch.setattr(notification_service, "create_notification", _boom)
    failed = await _run(apply=True)

    assert failed["failed"] == 2
    assert failed["sent"] == 0
    row = await get_appointments_col().find_one({"_id": appt})
    assert row["status"] == "confirmed"

    monkeypatch.undo()
    recovered = await _run(apply=True)

    assert recovered["sent"] == 2
    assert len(await _notices(appt)) == 2


async def test_a_failure_does_not_leak_exception_text(parties, monkeypatch, caplog):
    from app.services import notification_service

    await _appt(parties, starts_in=timedelta(hours=24))

    async def _boom(**kwargs):
        raise RuntimeError("mongodb://user:secret@host/db is unreachable")

    monkeypatch.setattr(notification_service, "create_notification", _boom)
    with caplog.at_level("WARNING"):
        report = await _run(apply=True)

    assert "secret" not in caplog.text
    assert "secret" not in repr(report)
    assert "RuntimeError" in caplog.text


# ── 9. Privacy ───────────────────────────────────────────────────────────────

async def test_no_private_field_reaches_a_reminder(parties):
    appt = await _appt(
        parties, starts_in=timedelta(hours=1),
        lawyer_notes="INTERNAL: client seems unreliable",
        cancel_reason="an old reason nobody should see",
        notes="the client's own private note")

    await _run(apply=True)

    blob = repr(await _notices(appt))
    for secret in ("INTERNAL", "unreliable", "old reason", "private note"):
        assert secret not in blob, f"a reminder leaked {secret!r}"


async def test_a_reminder_does_not_invent_a_joining_link(parties):
    appt = await _appt(parties, starts_in=timedelta(hours=1), meeting_link=None)

    await _run(apply=True)

    for notice in await _notices(appt):
        text = f"{notice['title']} {notice['body']}".lower()
        assert "http" not in text
        assert "join" not in text, (
            "a reminder implied a joining link for an appointment that has none")


async def test_the_survey_reports_counts_only(parties):
    await _appt(parties, starts_in=timedelta(hours=24))
    await _appt(parties, starts_in=timedelta(hours=1))

    report = await reminders.survey_due_reminders(now=NOW)

    assert report["due"] == {"24h": 1, "1h": 1}
    assert report["total"] == 2
    blob = repr(report)
    for secret in (parties["client_id"], parties["lawyer_id"], "Client One"):
        assert secret not in blob


async def test_the_survey_writes_nothing(parties):
    from app.db.collections import get_appointments_col, get_notifications_col

    await _appt(parties, starts_in=timedelta(hours=24))
    col = get_appointments_col()
    before = await col.find().sort("_id", 1).to_list(length=500)
    notices_before = await get_notifications_col().count_documents({})

    await reminders.survey_due_reminders(now=NOW)

    assert await col.find().sort("_id", 1).to_list(length=500) == before
    assert await get_notifications_col().count_documents({}) == notices_before


def test_the_survey_cannot_be_made_to_send():
    import inspect

    sig = inspect.signature(reminders.survey_due_reminders)
    assert "apply" not in sig.parameters
    source = inspect.getsource(reminders.survey_due_reminders)
    for writer in ("create_notification", "_deliver", "update_one", "insert_one"):
        assert writer not in source


# ── 10. The index, and what its absence costs ────────────────────────────────

def test_the_reminder_index_is_declared_as_a_query_index():
    from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS
    from app.db.v2_index_spec import QUERY

    spec = next(s for s in APPOINTMENT_INDEX_REQUIREMENTS
                if s.name == "appointment_confirmed_reminder")

    assert spec.kind == QUERY
    assert [k[0] for k in spec.keys] == ["status", "scheduled_at", "_id"]
    assert spec.unique is False
    assert spec.partial_filter == {"status": AppointmentStatus.CONFIRMED.value}


def test_the_correctness_indexes_are_untouched():
    """Scoped to the APPOINTMENTS collection. Other collections in this domain
    declare correctness indexes of their own; this asserts that adding a query
    index for reminders did not disturb the three that enforce booking."""
    from app.db.appointment_index_spec import (
        APPOINTMENTS,
        correctness_requirements,
    )

    names = {s.name for s in correctness_requirements()
             if s.collection == APPOINTMENTS}
    assert names == {"uniq_appointment_lawyer_slot",
                     "uniq_appointment_client_slot",
                     "uniq_appointment_idempotency"}


async def test_a_missing_reminder_index_does_not_block_startup(parties, monkeypatch):
    """SLOWNESS IS NOT INCORRECTNESS. `assert_appointment_booking_ready`
    refuses to start the service when `safe_to_activate` is false, so a missing
    performance index must be reported, never grounds for refusing bookings."""
    from app.db import indexes as indexes_module
    from app.db.appointment_slot_preflight import preflight
    from app.db.v2_index_spec import QUERY, IndexProblem

    async def _missing():
        return [IndexProblem("missing", "appointments",
                             "appointment_confirmed_reminder",
                             "index missing", kind=QUERY)]

    monkeypatch.setattr(indexes_module, "validate_appointment_indexes", _missing)
    result = await preflight()

    assert result["gates"]["indexes_valid"] is True
    assert result["safe_to_activate"] is True
    assert result["indexes_ready"] is False
    assert [p["name"] for p in result["query_index_problems"]] == [
        "appointment_confirmed_reminder"]


async def test_the_reminder_query_uses_the_index(parties):
    from app.db.collections import get_appointments_col

    lo, hi = reminders.window_bounds("24h", NOW)
    plan = await get_appointments_col().find({
        "status": AppointmentStatus.CONFIRMED.value,
        "scheduled_at": {"$gt": lo, "$lte": hi},
    }).sort([("scheduled_at", 1), ("_id", 1)]).explain()

    flat = str(plan["queryPlanner"]["winningPlan"])
    assert "COLLSCAN" not in flat, flat


# ── 11. Still dormant ────────────────────────────────────────────────────────

def test_no_scheduler_runs_reminders():
    from pathlib import Path

    import app.main as main

    source = Path(main.__file__).read_text(encoding="utf-8")
    assert "appointment_reminders" not in source
    assert "send_due_reminders" not in source


def test_the_outcome_nudge_type_is_not_reused():
    """The two say opposite things — "this is about to happen" against "this
    already happened and nobody recorded what came of it"."""
    import inspect

    source = inspect.getsource(reminders)
    assert "APPOINTMENT_OUTCOME_NUDGE" not in source
    assert "APPOINTMENT_REMINDER" in source
