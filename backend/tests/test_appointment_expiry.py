"""Pending requests that nobody answered, and the sweep that retires them.

A PENDING request holds its `occupied_slots` under the unique indexes and
nothing releases them. Booked, ignored, and that hour is gone for everyone,
permanently. This is the mechanism that ends such a request — and, just as
importantly, the set of cases in which it must NOT.

Three groups:

  * THE POLICY, pure. `deadline_for` is three terms and a cap, and every term
    exists because of a specific failure, so each is tested against the failure
    it prevents rather than against a number.

  * THE WRITE PATHS. The deadline is stored at booking and must move WITH the
    time it describes — and must not be extendable without limit by moving it.

  * THE SWEEP. It is the only thing that expires anything, it is bounded, it is
    version-pinned, and it is dormant. The tests that matter most here are the
    ones asserting what it leaves alone.
"""
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.core.constants import (
    AppointmentMode,
    AppointmentStatus,
    NotificationType,
)
from app.core.exceptions import AppValidationError, ConflictError
from app.services import appointment_expiry as expiry

pytestmark = pytest.mark.integration


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
async def parties(app_indexes):
    from app.db.collections import get_appointments_col, get_users_col

    tag = secrets.token_hex(4)
    lawyer_id = f"EX-L-{tag}"
    client_id, client2_id = f"EX-C-{tag}", f"EX-C2-{tag}"
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
        {"_id": client2_id, "role": "client", "is_active": True,
         "email": f"{client2_id}@test.invalid", "full_name": "Client Two",
         "created_at": now},
    ])
    yield {"lawyer_id": lawyer_id, "client_id": client_id,
           "client2_id": client2_id}
    await get_users_col().delete_many(
        {"_id": {"$in": [lawyer_id, client_id, client2_id]}})
    await get_appointments_col().delete_many(
        {"client_id": {"$in": [client_id, client2_id]}})


def _slot(hours_ahead: int = 48, minute: int = 0) -> datetime:
    base = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    return base.replace(minute=minute, second=0, microsecond=0)


async def _book(parties, when=None, **over):
    from app.services import appointment_service
    kwargs = {"client_id": parties["client_id"],
              "lawyer_id": parties["lawyer_id"], "case_id": None,
              "scheduled_at": when or _slot(), "duration_minutes": 60,
              "mode": AppointmentMode.VIDEO, "notes": None}
    kwargs.update(over)
    return await appointment_service.book_appointment(**kwargs)


async def _row(appt_id: str) -> dict:
    from app.db.collections import get_appointments_col
    return await get_appointments_col().find_one({"_id": appt_id})


async def _patch(appt_id: str, **fields) -> None:
    """Rewrite stored fields directly.

    Booking refuses past times, so a lapsed row cannot be produced through the
    API. Editing the row is the only way to reach the state the sweep exists
    for, and it is done here rather than by freezing the clock so the queries
    under test run against real stored values.
    """
    from app.db.collections import get_appointments_col
    await get_appointments_col().update_one({"_id": appt_id}, {"$set": fields})


async def _unset(appt_id: str, *fields) -> None:
    from app.db.collections import get_appointments_col
    await get_appointments_col().update_one(
        {"_id": appt_id}, {"$unset": {f: "" for f in fields}})


async def _apply_sweep(**kw):
    """An APPLYING sweep. `apply=True` is never defaulted in here either — a
    test helper that hid it would be hiding the thing under test."""
    from app.services import appointment_expiry_sweep
    return await appointment_expiry_sweep.expire_lapsed_requests(
        apply=True, **kw)


async def _survey(**kw):
    from app.services import appointment_expiry_sweep
    return await appointment_expiry_sweep.survey_legacy_pending(**kw)


async def _status(appt_id: str) -> str:
    return (await _row(appt_id))["status"]


async def _clear_notifications(appt_id: str) -> None:
    from app.db.collections import get_notifications_col
    await get_notifications_col().delete_many(
        {"payload.appointment_id": appt_id})


async def _notifications(appt_id: str) -> list[dict]:
    from app.db.collections import get_notifications_col
    return await get_notifications_col().find(
        {"payload.appointment_id": appt_id}).to_list(length=20)


# ── 1. The policy, pure ──────────────────────────────────────────────────────

def test_the_ordinary_case_releases_the_slot_a_day_before():
    """A request booked well in advance lapses 24h before its start, while the
    hour is still worth something to somebody else."""
    created = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    start = datetime(2026, 9, 4, 15, 0, tzinfo=timezone.utc)

    assert expiry.deadline_for(created, start) == start - timedelta(hours=24)


def test_a_short_notice_request_is_not_born_already_expired():
    """THE FLOOR, against the failure that makes it necessary.

    Booking permits any future time. A request made 90 minutes before its start
    has `start - 24h` in the past, so without the floor the very first sweep
    would retire it — possibly before the lawyer's page had even refreshed.
    """
    created = datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)
    start = created + timedelta(minutes=90)

    deadline = expiry.deadline_for(created, start)

    assert deadline > created, "the request was born past its own deadline"
    assert not expiry.has_lapsed(
        {"created_at": created, "scheduled_at": start}, now=created)


def test_the_deadline_never_outlives_the_appointment_itself():
    """And the floor does not buy a window longer than the wait.

    Ninety minutes' notice gives ninety minutes, not two hours: a deadline
    after the start is meaningless, because by then the time has passed. This
    is why the response window is documented as a CAP and not a guarantee.
    """
    created = datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)
    start = created + timedelta(minutes=90)

    assert expiry.deadline_for(created, start) == start


def test_a_distant_booking_still_lapses_within_a_week():
    """THE CAP. `start - 24h` for a booking three months out is three months of
    a held slot; the life of a REQUEST is bounded by when it was made."""
    created = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    start = created + timedelta(days=90)

    assert expiry.deadline_for(created, start) == created + timedelta(days=7)


def test_the_three_terms_are_ordered_as_documented():
    """Which term wins, across the whole range, in one place.

    Asserting the three cases separately leaves the boundaries between them
    untested — and the boundaries are where a `min`/`max` gets written the
    wrong way round.
    """
    created = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    for hours, expected in [
        (1, "start"),          # sooner than the floor
        (2, "start"),          # exactly the floor's reach
        (5, "floor"),          # floor beats start-24h
        (26, "floor"),         # still inside the floor's shadow
        (48, "lead"),          # the ordinary case
        (24 * 7, "lead"),      # just inside the cap
        (24 * 30, "cap"),      # the cap wins
    ]:
        start = created + timedelta(hours=hours)
        got = expiry.deadline_for(created, start)
        want = {"start": start,
                "floor": created + timedelta(hours=2),
                "lead": start - timedelta(hours=24),
                "cap": created + timedelta(days=7)}[expected]
        assert got == want, f"+{hours}h: expected the {expected} term"
        assert got <= start, f"+{hours}h: deadline is after the appointment"


def test_a_stored_deadline_is_preferred_to_a_derived_one():
    """The row's own value governs. Recomputing it on read would mean a change
    to this policy silently rewrote the deadline of every request already
    waiting under the old one."""
    created = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    start = created + timedelta(days=5)
    stored = created + timedelta(hours=3)

    assert expiry.deadline_of({
        "created_at": created, "scheduled_at": start, "expires_at": stored,
    }) == stored


def test_a_legacy_row_is_assessed_without_a_backfill():
    created = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    start = created + timedelta(days=5)

    assert expiry.deadline_of({"created_at": created, "scheduled_at": start}) \
        == start - timedelta(hours=24)


@pytest.mark.parametrize("row", [
    {},
    {"created_at": datetime(2026, 9, 1, tzinfo=timezone.utc)},
    {"scheduled_at": datetime(2026, 9, 5, tzinfo=timezone.utc)},
    {"created_at": None, "scheduled_at": None},
    {"created_at": "2026-09-01", "scheduled_at": "2026-09-05"},
])
def test_a_row_that_cannot_be_assessed_is_never_lapsed(row):
    """"CANNOT TELL" MUST NOT READ AS "EXPIRE IT".

    That is the direction in which the mistake terminates somebody's real
    appointment, so the unassessable row is left alone in every shape.
    """
    assert expiry.deadline_of(row) is None
    assert expiry.has_lapsed(row) is False


def test_naive_stored_instants_are_read_as_utc():
    """Rows written before `tz_aware=True` decode naive, and comparing one
    against an aware `now` raises. They were always UTC."""
    created = datetime(2026, 9, 1, 9, 0)
    start = datetime(2026, 9, 4, 15, 0)

    deadline = expiry.deadline_of({"created_at": created, "scheduled_at": start})

    assert deadline.tzinfo is not None
    assert deadline == datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)


def test_the_deadline_is_the_instant_it_lapses():
    row = {"created_at": datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
           "scheduled_at": datetime(2026, 9, 4, 15, 0, tzinfo=timezone.utc)}
    deadline = expiry.deadline_of(row)

    assert expiry.has_lapsed(row, deadline - timedelta(seconds=1)) is False
    assert expiry.has_lapsed(row, deadline) is True, (
        "the query selects on $lte; the policy must agree or a selected row "
        "would be refused by the check that selected it")


# ── 2. The write paths ───────────────────────────────────────────────────────

async def test_booking_stores_the_deadline(parties):
    when = _slot(hours_ahead=72)
    appt = await _book(parties, when)

    row = await _row(appt["id"])
    assert row["expires_at"] == expiry.deadline_for(row["created_at"], when)


async def test_the_deadline_is_not_exposed_to_the_client(parties):
    """STORED, BUT NOT PUBLISHED — while the sweep is dormant.

    A field in a response is a promise. Showing a client "expires at 14:00"
    when nothing runs at 14:00 tells them something false, and a client who
    stops waiting on the strength of it has been misled by a mechanism that is
    switched off. `AppointmentOut` is `extra="allow"`, so `_sanitize` is the
    only thing that can withhold it.
    """
    from app.services import appointment_service

    appt = await _book(parties)
    assert (await _row(appt["id"]))["expires_at"] is not None, "stored"
    assert "expires_at" not in appt, "returned by book_appointment"

    fetched = await appointment_service.get_appointment(
        appt["id"], parties["client_id"], "client")
    assert "expires_at" not in fetched

    as_lawyer = await appointment_service.get_appointment(
        appt["id"], parties["lawyer_id"], "lawyer")
    assert "expires_at" not in as_lawyer

    page = await appointment_service.list_appointments(
        user_id=parties["client_id"], user_role="client",
        status=None, page=1, page_size=50)
    assert all("expires_at" not in i for i in page["items"])


async def test_rescheduling_moves_the_deadline_with_the_time(parties):
    from app.services import appointment_service

    appt = await _book(parties, _slot(hours_ahead=48))
    before = (await _row(appt["id"]))["expires_at"]

    later = _slot(hours_ahead=120)
    await appointment_service.reschedule_appointment(
        appt_id=appt["id"], client_id=parties["client_id"],
        scheduled_at=later, expected_version=0)

    row = await _row(appt["id"])
    assert row["expires_at"] != before
    assert row["expires_at"] == expiry.deadline_for(row["created_at"], later)


async def test_the_deadline_always_matches_the_stored_time(parties):
    """The invariant behind the previous test: a row whose deadline belongs to
    a start it no longer has would be swept over a time nobody is waiting for.
    """
    from app.services import appointment_service

    appt = await _book(parties, _slot(hours_ahead=48))
    for i, hours in enumerate([96, 60, 150]):
        await appointment_service.reschedule_appointment(
            appt_id=appt["id"], client_id=parties["client_id"],
            scheduled_at=_slot(hours_ahead=hours), expected_version=i)
        row = await _row(appt["id"])
        assert row["expires_at"] == expiry.deadline_for(
            row["created_at"], row["scheduled_at"]), f"after move {i + 1}"


async def test_rescheduling_cannot_extend_a_request_indefinitely(parties):
    """THE CAP, on the path it exists to close.

    The lead term is recomputed on every move, so without an anchor to
    creation a client could hold a lawyer's hour for ever by nudging the
    request forward once a week.
    """
    from app.services import appointment_service

    appt = await _book(parties, _slot(hours_ahead=48))
    created = (await _row(appt["id"]))["created_at"]

    await appointment_service.reschedule_appointment(
        appt_id=appt["id"], client_id=parties["client_id"],
        scheduled_at=_slot(hours_ahead=24 * 45), expected_version=0)

    row = await _row(appt["id"])
    assert row["expires_at"] == expiry._as_utc(created) + timedelta(days=7)


async def test_repeated_moves_do_not_each_buy_another_week(parties):
    from app.services import appointment_service

    appt = await _book(parties, _slot(hours_ahead=48))
    created = (await _row(appt["id"]))["created_at"]
    cap = expiry._as_utc(created) + timedelta(days=7)

    for i, days in enumerate([30, 60, 90]):
        await appointment_service.reschedule_appointment(
            appt_id=appt["id"], client_id=parties["client_id"],
            scheduled_at=_slot(hours_ahead=24 * days), expected_version=i)
        assert (await _row(appt["id"]))["expires_at"] == cap, (
            f"move {i + 1} pushed the cap")


async def test_a_reschedule_that_cannot_date_the_row_removes_the_field(parties):
    """A row with no usable `created_at` cannot be given a new deadline, and
    keeping the old one is the only way `expires_at` could end up describing a
    time the row no longer has. It is dropped onto the derived path instead,
    which declines to assess it at all."""
    from app.services import appointment_service

    appt = await _book(parties, _slot(hours_ahead=48))
    await _unset(appt["id"], "created_at")

    await appointment_service.reschedule_appointment(
        appt_id=appt["id"], client_id=parties["client_id"],
        scheduled_at=_slot(hours_ahead=96), expected_version=0)

    row = await _row(appt["id"])
    assert "expires_at" not in row
    assert expiry.deadline_of(row) is None


# ── 3. The sweep: what it retires ────────────────────────────────────────────

async def test_a_lapsed_request_is_expired(parties):
    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))

    report = await _apply_sweep()

    assert report["expired"] >= 1
    assert await _status(appt["id"]) == AppointmentStatus.EXPIRED.value


async def test_a_legacy_row_is_never_expired_by_the_sweep(parties):
    """ROWS THAT ALREADY EXIST ARE OUT OF SCOPE, even when overdue.

    Changing the status of appointments booked before this mechanism existed
    is a separate decision with its own approval; the sweep must not make it
    incidentally. Note that `apply=True` is passed here — this is not the
    fail-closed default doing the work, it is the population boundary.
    """
    appt = await _book(parties, _slot(hours_ahead=48))
    await _unset(appt["id"], "expires_at")
    await _patch(appt["id"],
                 created_at=datetime.now(timezone.utc) - timedelta(days=9))

    report = await _apply_sweep()

    assert await _status(appt["id"]) == AppointmentStatus.PENDING.value
    assert report["examined"] == 0, (
        "the sweep read a row with no stored deadline")


async def test_expiring_releases_the_slot(parties):
    """THE POINT OF ALL OF THIS. EXPIRED is outside `ACTIVE_STATUSES`, so the
    partial unique indexes stop covering the row and its hours are bookable.

    Without this assertion the whole mechanism could pass its other tests while
    changing a word in a column and freeing nothing.
    """
    from app.services import appointment_service

    when = _slot(hours_ahead=48)
    appt = await _book(parties, when)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))

    # The friendly pre-check, which is a 422 rather than the index's conflict.
    # Either way the hour is unavailable while the request holds it, which is
    # the precondition this test needs.
    with pytest.raises(AppValidationError):
        await appointment_service.book_appointment(
            client_id=parties["client2_id"], lawyer_id=parties["lawyer_id"],
            case_id=None, scheduled_at=when, duration_minutes=60,
            mode=AppointmentMode.VIDEO, notes=None)

    await _apply_sweep()

    other = await appointment_service.book_appointment(
        client_id=parties["client2_id"], lawyer_id=parties["lawyer_id"],
        case_id=None, scheduled_at=when, duration_minutes=60,
        mode=AppointmentMode.VIDEO, notes=None)
    assert other["status"] == AppointmentStatus.PENDING.value


async def test_the_run_is_bounded(parties):
    appts = []
    for i in range(4):
        made = await _book(parties, _slot(hours_ahead=48 + i * 4))
        await _patch(made["id"],
                     expires_at=datetime.now(timezone.utc) - timedelta(minutes=10 - i))
        appts.append(made["id"])

    report = await _apply_sweep(limit=2)

    assert report["expired"] == 2, report
    remaining = [a for a in appts
                 if await _status(a) == AppointmentStatus.PENDING.value]
    assert len(remaining) == 2, "a bounded run took more than its limit"


async def test_the_backlog_is_cleared_oldest_first(parties):
    ids = []
    now = datetime.now(timezone.utc)
    for i in range(3):
        made = await _book(parties, _slot(hours_ahead=48 + i * 4))
        await _patch(made["id"], expires_at=now - timedelta(hours=3 - i))
        ids.append(made["id"])

    await _apply_sweep(limit=1)

    assert await _status(ids[0]) == AppointmentStatus.EXPIRED.value
    assert await _status(ids[1]) == AppointmentStatus.PENDING.value


# ── 4. The sweep: what it leaves alone ───────────────────────────────────────

async def test_a_request_still_inside_its_deadline_is_untouched(parties):
    appt = await _book(parties, _slot(hours_ahead=96))

    report = await _apply_sweep()

    assert await _status(appt["id"]) == AppointmentStatus.PENDING.value
    assert report["expired"] == 0


async def test_a_confirmed_appointment_does_not_expire(parties):
    """Both parties have agreed. It does not lapse because nobody looked at it
    again — that is what cancellation is for."""
    from app.services import appointment_service

    appt = await _book(parties)
    await appointment_service.confirm_appointment(
        appt["id"], parties["lawyer_id"], expected_version=0,
        meeting_link="https://meet.example.com/abc-def")
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(days=2))

    await _apply_sweep()

    assert await _status(appt["id"]) == AppointmentStatus.CONFIRMED.value


async def test_an_unassessable_row_is_reported_not_expired(parties, monkeypatch):
    """The in-code deadline check is DEFENCE IN DEPTH, and is tested as such.

    It cannot currently be reached through the query: Mongo's comparison
    operators only compare within a BSON type, so a row whose `expires_at` is
    not a date never matches `{$lte: <date>}` in the first place. That is a
    property of the query, not of this guard — and the guard is what holds if
    the query is ever widened, or if a row arrives with a date in `expires_at`
    that the policy later declines to accept.

    So the row is handed to the sweep directly. Anything else would be
    asserting the query's behaviour twice and this guard's not at all.
    """
    from app.services import appointment_expiry_sweep

    appt = await _book(parties)
    row = await _row(appt["id"])
    row["expires_at"] = "not-a-datetime"
    row.pop("created_at", None)

    async def _one_bad_row(now, limit):
        return [row]

    monkeypatch.setattr(
        appointment_expiry_sweep.appt_repo, "find_lapsed_pending", _one_bad_row)

    report = await _apply_sweep()

    assert report["examined"] == 1
    assert report["unassessable"] == 1
    assert report["expired"] == 0
    assert await _status(appt["id"]) == AppointmentStatus.PENDING.value


async def test_a_bare_call_writes_nothing_and_tells_nobody(parties):
    """THE FAIL-CLOSED REGRESSION.

    `expire_lapsed_requests()` with no arguments is the call a future
    scheduler, a console session or a half-finished wiring change would most
    plausibly make. It must inspect and nothing more: this function terminates
    other people's appointments, so the difference between looking and acting
    cannot be a keyword somebody remembered to pass.
    """
    from app.services import appointment_expiry_sweep

    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    await _clear_notifications(appt["id"])

    report = await appointment_expiry_sweep.expire_lapsed_requests()

    assert report["applied"] is False
    assert report["expired"] >= 1, (
        "a bare call must still report what an applying one would do")
    assert await _status(appt["id"]) == AppointmentStatus.PENDING.value
    assert await _notifications(appt["id"]) == []


def test_applying_is_keyword_only_and_off_by_default():
    """Not reachable positionally, so `expire_lapsed_requests(True)` — which
    reads like a plausible "run it" — cannot silently become an apply."""
    import inspect

    from app.services import appointment_expiry_sweep

    sig = inspect.signature(appointment_expiry_sweep.expire_lapsed_requests)
    apply_param = sig.parameters["apply"]

    assert apply_param.default is False
    assert apply_param.kind is inspect.Parameter.KEYWORD_ONLY
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY
               for p in sig.parameters.values())


@pytest.mark.parametrize("kwargs", [
    {"apply": "false"}, {"apply": "true"}, {"apply": 1},
    {"apply": None}, {"limit": 0}, {"limit": -1},
    {"limit": True}, {"limit": "200"}, {"limit": 201},
    {"limit": 1.5},
])
async def test_invalid_sweep_controls_refuse_before_reading_or_writing(
    monkeypatch, kwargs,
):
    from app.services import appointment_expiry_sweep

    async def forbidden(*_args, **_kwargs):
        pytest.fail("an invalid sweep control reached the database or notifier")

    monkeypatch.setattr(
        appointment_expiry_sweep.appt_repo, "find_lapsed_pending", forbidden)
    monkeypatch.setattr(
        appointment_expiry_sweep.appt_repo, "expire_pending", forbidden)
    monkeypatch.setattr(appointment_expiry_sweep, "_announce", forbidden)

    with pytest.raises(ValueError):
        await appointment_expiry_sweep.expire_lapsed_requests(**kwargs)


async def test_direct_booking_refuses_past_time_before_any_lookup(monkeypatch):
    from app.services import appointment_service

    async def forbidden(*_args, **_kwargs):
        pytest.fail("past booking reached a repository")

    # The lawyer lookup is the first repository read after time validation.
    # Patch that boundary, rather than mutating a shared repository instance
    # that later integration tests also use.
    monkeypatch.setattr(appointment_service, "_get_verified_lawyer", forbidden)
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(
        minute=0, second=0, microsecond=0)

    with pytest.raises(AppValidationError, match="future"):
        await appointment_service.book_appointment(
            client_id="client", lawyer_id="lawyer", case_id=None,
            scheduled_at=past, duration_minutes=60,
            mode=AppointmentMode.VIDEO, notes=None)


async def test_booking_survives_a_name_lookup_failure_after_insert(
    parties, monkeypatch, caplog,
):
    from app.services import appointment_service

    committed = False
    real_insert = appointment_service.appt_repo.insert
    real_find = appointment_service.user_repo.find_by_id

    async def insert_then_fail_names(doc):
        nonlocal committed
        await real_insert(doc)
        committed = True

    async def find_user(user_id):
        if committed:
            raise RuntimeError("mongodb://user:password@host failed for CNIC")
        return await real_find(user_id)

    monkeypatch.setattr(appointment_service.appt_repo, "insert", insert_then_fail_names)
    monkeypatch.setattr(appointment_service.user_repo, "find_by_id", find_user)

    appt = await _book(parties)

    assert committed
    assert await _status(appt["id"]) == AppointmentStatus.PENDING.value
    assert len(await _notifications(appt["id"])) == 2
    assert "appointment_notification_context_failed" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "mongodb://" not in caplog.text
    assert "CNIC" not in caplog.text


async def test_confirmation_survives_a_name_lookup_failure_after_cas(
    parties, monkeypatch,
):
    from app.services import appointment_service

    appt = await _book(parties)
    real_transition = appointment_service._transition
    real_find = appointment_service.user_repo.find_by_id
    committed = False

    async def transition_then_fail_names(*args, **kwargs):
        nonlocal committed
        result = await real_transition(*args, **kwargs)
        committed = True
        return result

    async def find_user(user_id):
        if committed:
            raise RuntimeError("notification context read failed")
        return await real_find(user_id)

    monkeypatch.setattr(appointment_service, "_transition", transition_then_fail_names)
    monkeypatch.setattr(appointment_service.user_repo, "find_by_id", find_user)

    out = await appointment_service.confirm_appointment(
        appt["id"], parties["lawyer_id"], expected_version=0)

    assert committed
    assert out["status"] == AppointmentStatus.CONFIRMED.value
    assert await _status(appt["id"]) == AppointmentStatus.CONFIRMED.value


async def test_expiry_continues_notifying_when_name_lookup_fails(
    parties, monkeypatch,
):
    from app.services import appointment_service

    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    await _clear_notifications(appt["id"])

    async def failed_name_lookup(_user_id):
        raise RuntimeError("notification context read failed")

    monkeypatch.setattr(
        appointment_service.user_repo, "find_by_id", failed_name_lookup)

    report = await _apply_sweep()

    assert report["expired"] >= 1
    assert await _status(appt["id"]) == AppointmentStatus.EXPIRED.value
    notices = await _notifications(appt["id"])
    assert {n["user_id"] for n in notices} == {
        parties["client_id"], parties["lawyer_id"]}


async def test_an_applying_call_still_requires_the_lapse(parties):
    """`apply=True` is permission to act on what the policy selected, not an
    instruction to expire whatever the query returned."""
    appt = await _book(parties, _slot(hours_ahead=96))

    report = await _apply_sweep()

    assert report["applied"] is True
    assert await _status(appt["id"]) == AppointmentStatus.PENDING.value


async def test_a_reschedule_during_the_sweep_beats_it(parties):
    """THE RACE THE VERSION PIN EXISTS FOR.

    The rows are read, then written one at a time. A client who moves their
    request into next week in between has answered the only question the sweep
    was asking, and a stale expiry would retire a request that is no longer
    lapsed at all.
    """
    from app.services import appointment_service
    from app.services import appointment_expiry_sweep

    appt = await _book(parties, _slot(hours_ahead=48))
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))

    stale = await _row(appt["id"])

    # Exactly what a concurrent client does between the read and the write.
    await appointment_service.reschedule_appointment(
        appt_id=appt["id"], client_id=parties["client_id"],
        scheduled_at=_slot(hours_ahead=120), expected_version=0)

    moved = await appointment_expiry_sweep.appt_repo.expire_pending(
        stale["_id"], stale.get("schedule_version", 0))

    assert moved is None, "a stale expiry matched a row that had moved"
    assert await _status(appt["id"]) == AppointmentStatus.PENDING.value


async def test_a_confirmation_during_the_sweep_beats_it(parties):
    from app.services import appointment_service
    from app.services import appointment_expiry_sweep

    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    stale = await _row(appt["id"])

    await appointment_service.confirm_appointment(
        appt["id"], parties["lawyer_id"], expected_version=0,
        meeting_link="https://meet.example.com/abc-def")

    moved = await appointment_expiry_sweep.appt_repo.expire_pending(
        stale["_id"], stale.get("schedule_version", 0))

    assert moved is None
    assert await _status(appt["id"]) == AppointmentStatus.CONFIRMED.value


async def test_a_row_with_no_version_can_still_be_expired(parties):
    """Version 0 has to match a row that carries no `schedule_version` at all.

    Not every unversioned row is a legacy one: `schedule_version` can be absent
    for other reasons, and a sweep that silently skipped them would fail
    quietly rather than loudly.
    """
    appt = await _book(parties, _slot(hours_ahead=48))
    await _unset(appt["id"], "schedule_version")
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))

    await _apply_sweep()

    assert await _status(appt["id"]) == AppointmentStatus.EXPIRED.value


# ── 4b. The legacy survey: counts, and only counts ───────────────────────────
#
# Rows booked before `expires_at` existed are NOT expired by anything here.
# They are counted, so the decision about what to do with them can be taken
# against real numbers — and that decision needs its own approval.

async def _legacy(parties, *, days_old, hours_ahead=48, broken=False):
    """One pending row with no stored deadline."""
    appt = await _book(parties, _slot(hours_ahead=hours_ahead))
    await _unset(appt["id"], "expires_at")
    if broken:
        await _unset(appt["id"], "created_at")
    else:
        await _patch(appt["id"],
                     created_at=datetime.now(timezone.utc) - timedelta(days=days_old))
    return appt["id"]


async def test_the_survey_counts_without_writing(parties):
    overdue = await _legacy(parties, days_old=9)

    report = await _survey()

    assert report["lapsed"] >= 1
    assert await _status(overdue) == AppointmentStatus.PENDING.value


async def test_the_survey_cannot_be_made_to_write(parties):
    """There is no `apply` here, and adding one is the change this asserts
    against. Retiring rows that predate the mechanism is a separate decision,
    not a flag on a counting function."""
    import inspect

    from app.services import appointment_expiry_sweep

    sig = inspect.signature(appointment_expiry_sweep.survey_legacy_pending)

    assert "apply" not in sig.parameters
    assert "dry_run" not in sig.parameters
    source = inspect.getsource(appointment_expiry_sweep.survey_legacy_pending)
    for writer in ("expire_pending", "update_one", "_announce", "_notify"):
        assert writer not in source, f"the survey calls {writer}"


async def test_the_survey_returns_counts_and_no_identities(parties):
    """"How many, and how overdue" does not require naming anybody's
    consultation."""
    await _legacy(parties, days_old=9)

    report = await _survey()

    assert set(report) == {"scanned", "lapsed", "not_lapsed", "unassessable",
                           "pages", "complete"}
    assert all(isinstance(v, (int, bool)) for v in report.values())


async def test_the_survey_separates_overdue_from_merely_old(parties):
    overdue = await _legacy(parties, days_old=9, hours_ahead=48)
    waiting = await _legacy(parties, days_old=0, hours_ahead=96)

    report = await _survey()

    assert report["scanned"] >= 2
    assert report["lapsed"] >= 1
    assert report["not_lapsed"] >= 1
    assert await _status(overdue) == AppointmentStatus.PENDING.value
    assert await _status(waiting) == AppointmentStatus.PENDING.value


async def test_the_survey_pages_past_rows_it_can_do_nothing_with(parties):
    """THE STARVATION REGRESSION.

    The removed legacy pass re-read the FIRST page every time. Rows it could
    not act on — unassessable, or not yet due — stay at the front of that page
    for ever, so an overdue row behind them was never reached at all: the pass
    starved on exactly the population it existed to find.

    Here the first page is filled entirely with such rows and the overdue one
    is placed behind them, then the page size is set to make that ordering
    bite. A non-advancing read counts zero lapsed rows.
    """
    from app.db.collections import get_appointments_col

    blockers = [await _legacy(parties, days_old=0, hours_ahead=96 + i * 4,
                              broken=(i % 2 == 0))
                for i in range(4)]
    overdue = await _legacy(parties, days_old=9, hours_ahead=48)

    # The survey pages on `_id`, so the ordering under test is `_id` ordering.
    # Rewriting the ids is how the overdue row is put demonstrably LAST.
    col = get_appointments_col()
    ordered = []
    for i, old_id in enumerate(blockers + [overdue]):
        doc = await col.find_one({"_id": old_id})
        doc["_id"] = f"EX-ORDER-{i:02d}-{old_id}"
        # DELETE FIRST. Inserting the copy while the original still exists is
        # two active rows claiming one lawyer's hour, and the unique slot index
        # rejects it — correctly.
        await col.delete_one({"_id": old_id})
        await col.insert_one(doc)
        ordered.append(doc["_id"])

    report = await _survey(page_size=2, max_pages=10)

    assert report["pages"] >= 3, (
        f"the scan did not advance past the first pages: {report}")
    assert report["lapsed"] >= 1, (
        f"the overdue row behind the unactionable ones was never reached: "
        f"{report}")
    assert report["complete"] is True
    assert await _status(ordered[-1]) == AppointmentStatus.PENDING.value


async def test_the_survey_is_bounded(parties):
    """Read-only is not the same as free. An unbounded scan of a growing
    collection is how a counting tool becomes an outage."""
    for i in range(4):
        await _legacy(parties, days_old=0, hours_ahead=96 + i * 4)

    report = await _survey(page_size=1, max_pages=2)

    assert report["pages"] == 2
    assert report["scanned"] == 2
    assert report["complete"] is False, (
        "a truncated scan must not report itself as complete")


async def test_the_survey_ignores_rows_that_have_a_deadline(parties):
    """The two populations do not overlap, so the numbers can be added."""
    modern = await _book(parties, _slot(hours_ahead=48))
    await _patch(modern["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))

    report = await _survey()
    swept = await _apply_sweep()

    assert report["scanned"] == 0
    assert swept["expired"] >= 1


# ── 5. Expiry is terminal ────────────────────────────────────────────────────

async def test_an_expired_request_cannot_be_confirmed(parties):
    from app.services import appointment_service

    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    await _apply_sweep()

    with pytest.raises(ConflictError):
        await appointment_service.confirm_appointment(
            appt["id"], parties["lawyer_id"], expected_version=0,
            meeting_link="https://meet.example.com/abc-def")


async def test_an_expired_request_cannot_be_cancelled_or_completed(parties):
    from app.services import appointment_service

    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    await _apply_sweep()

    with pytest.raises(ConflictError):
        await appointment_service.cancel_appointment(
            appt["id"], parties["client_id"], "client", reason="changed my mind")
    with pytest.raises(ConflictError):
        await appointment_service.complete_appointment(
            appt["id"], parties["lawyer_id"],
            lawyer_notes=None, meeting_link=None)


def test_the_state_machine_admits_expiry_only_from_pending():
    from app.services import appointment_transitions as t

    assert t.sources_for(AppointmentStatus.EXPIRED) == frozenset(
        {AppointmentStatus.PENDING})
    assert AppointmentStatus.EXPIRED in t.TERMINAL
    assert t.allowed_from(AppointmentStatus.EXPIRED) == frozenset()


def test_expired_holds_no_slot():
    """The index scope is the release mechanism. If EXPIRED ever appeared in
    `ACTIVE_STATUSES` the sweep would rename a row and free nothing."""
    from app.db.appointment_index_spec import ACTIVE_STATUSES

    assert AppointmentStatus.EXPIRED.value not in ACTIVE_STATUSES


# ── 6. Both parties are told ─────────────────────────────────────────────────

async def test_both_parties_are_notified(parties):
    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    await _clear_notifications(appt["id"])

    await _apply_sweep()

    told = {n["user_id"] for n in await _notifications(appt["id"])}
    assert told == {parties["client_id"], parties["lawyer_id"]}, told


async def test_the_two_notifications_do_not_cancel_each_other_out(parties):
    """`logical_event_id` is unique GLOBALLY, on that field alone. One id for
    the appointment would let whichever party was written first claim it, and
    the second notification would be swallowed as an already-delivered
    duplicate — dedup silently eating a real delivery."""
    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    await _clear_notifications(appt["id"])

    await _apply_sweep()

    ids = [n.get("logical_event_id") for n in await _notifications(appt["id"])]
    assert len(ids) == 2
    assert len(set(ids)) == 2, f"both notifications shared an id: {ids}"
    assert all(i and i.startswith(f"appointment:{appt['id']}:expired:")
               for i in ids), ids


async def test_the_notifications_use_the_expiry_type_and_blame_nobody(parties):
    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    await _clear_notifications(appt["id"])

    await _apply_sweep()

    notes = await _notifications(appt["id"])
    assert {n["type"] for n in notes} == {
        NotificationType.APPOINTMENT_EXPIRED.value}
    for note in notes:
        text = f"{note['title']} {note['body']}".lower()
        assert "cancel" not in text, (
            "an expired request must not read as a cancellation — nobody "
            "cancelled it")
        for word in ("failed", "ignored", "did not respond"):
            assert word not in text, f"the wording blames somebody: {word!r}"


async def test_a_slot_that_has_already_passed_is_not_offered_back(parties):
    """THE DEADLINE CAN BE THE START ITSELF.

    `min(start, ...)` means a short-notice request lapses at the moment of the
    appointment, and a sweep run after that expires a row whose time is gone.
    Telling that client "the time is free again — book it" invites them to book
    an hour in the past. What is true is that the request is closed.
    """
    appt = await _book(parties)
    past = datetime.now(timezone.utc) - timedelta(hours=3)
    await _patch(appt["id"], scheduled_at=past, end_at=past + timedelta(hours=1),
                 expires_at=past)
    await _clear_notifications(appt["id"])

    await _apply_sweep()

    notes = {n["user_id"]: n["body"] for n in await _notifications(appt["id"])}
    client_body = notes[parties["client_id"]]
    lawyer_body = notes[parties["lawyer_id"]]

    assert "free again" not in client_body, client_body
    assert "released" not in lawyer_body, lawyer_body
    assert "has now passed" in client_body
    assert "new request" in client_body, (
        "the client is left with no idea what they can do next")


async def test_a_future_slot_is_still_offered_back(parties):
    """The ordinary case, so the wording above cannot have been made vague for
    everyone in order to be accurate for one case."""
    appt = await _book(parties, _slot(hours_ahead=96))
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    await _clear_notifications(appt["id"])

    await _apply_sweep()

    notes = {n["user_id"]: n["body"] for n in await _notifications(appt["id"])}

    assert "free again" in notes[parties["client_id"]]
    assert "released" in notes[parties["lawyer_id"]]


async def test_the_private_note_never_reaches_a_notification(parties):
    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                 lawyer_notes="INTERNAL: client sounded unreliable")
    await _clear_notifications(appt["id"])

    await _apply_sweep()

    for note in await _notifications(appt["id"]):
        blob = f"{note['title']} {note['body']} {note.get('payload')}"
        assert "INTERNAL" not in blob
        assert "unreliable" not in blob


async def test_a_lost_notification_does_not_undo_the_expiry(parties, monkeypatch):
    """Notifications are best-effort by declaration. The transition is already
    committed when they are sent, so a delivery failure must not be reported as
    a failure to expire."""
    from app.services import notification_service

    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))

    async def _boom(**kwargs):
        raise RuntimeError("notification backend down")

    monkeypatch.setattr(notification_service, "create_notification", _boom)

    report = await _apply_sweep()

    assert report["expired"] >= 1
    assert await _status(appt["id"]) == AppointmentStatus.EXPIRED.value


# ── 7. Dormancy, and the index that makes it affordable ──────────────────────

def test_the_sweep_is_not_scheduled():
    """DORMANT ON PURPOSE, asserted rather than commented.

    Turning it on must be a visible change to `main.py` — where the other
    schedulers are — and not something a later edit does by accident while the
    Phase 3 indexes are still unbuilt.
    """
    from pathlib import Path

    import app.main as main

    source = Path(main.__file__).read_text(encoding="utf-8")
    assert "appointment_expiry_sweep" not in source, (
        "the expiry sweep has been wired into startup; that is a deliberate "
        "rollout step, so update this test and the rollout checklist with it")


def test_the_sweeps_query_has_an_index_declared():
    from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS
    from app.db.v2_index_spec import QUERY

    spec = next(s for s in APPOINTMENT_INDEX_REQUIREMENTS
                if s.name == "appointment_pending_expiry")

    assert spec.kind == QUERY, "nothing is WRONG without it; it is not a guard"
    assert [k[0] for k in spec.keys] == ["status", "expires_at"], (
        "equality first, then the range and sort key")
    assert spec.unique is False
    assert spec.partial_filter == {"status": AppointmentStatus.PENDING.value}


async def test_the_sweeps_query_actually_uses_that_index(parties):
    """The declared index and the query the sweep issues must match. They are
    written in two files and nothing but this checks that they agree."""
    from app.db.collections import get_appointments_col

    plan = await get_appointments_col().find({
        "status": AppointmentStatus.PENDING.value,
        "expires_at": {"$lte": datetime.now(timezone.utc)},
    }).sort("expires_at", 1).explain()

    stage = plan["queryPlanner"]["winningPlan"]
    flat = str(stage)
    assert "COLLSCAN" not in flat, f"the sweep's read is a collection scan: {flat}"
    assert "appointment_pending_expiry" in flat, flat


async def test_a_missing_query_index_does_not_stop_the_service(parties, monkeypatch):
    """SLOWNESS IS NOT INCORRECTNESS.

    `assert_appointment_booking_ready` refuses to start the service when
    `safe_to_activate` is false, so anything inside that gate is a reason to
    take booking down. Declaring `appointment_pending_expiry` put a
    PERFORMANCE index inside a CORRECTNESS gate — a missing one would have
    refused every booking rather than made a dormant sweep slow.
    """
    from app.db import indexes as indexes_module
    from app.db.appointment_slot_preflight import preflight
    from app.db.v2_index_spec import CORRECTNESS, QUERY, IndexProblem

    async def _query_problem():
        return [IndexProblem("missing", "appointments",
                             "appointment_pending_expiry",
                             "index missing", kind=QUERY)]

    monkeypatch.setattr(
        indexes_module, "validate_appointment_indexes", _query_problem)
    result = await preflight()

    assert result["gates"]["indexes_valid"] is True
    assert result["safe_to_activate"] is True
    assert result["indexes_ready"] is False, (
        "it is still missing, and the report must still say so")
    assert [p["name"] for p in result["query_index_problems"]] == [
        "appointment_pending_expiry"]


async def test_a_missing_correctness_index_still_stops_the_service(parties, monkeypatch):
    """The other direction, so the split above cannot have opened the gate."""
    from app.db import indexes as indexes_module
    from app.db.appointment_slot_preflight import preflight
    from app.db.v2_index_spec import CORRECTNESS, IndexProblem

    async def _correctness_problem():
        return [IndexProblem("missing", "appointments",
                             "uniq_appointment_lawyer_slot",
                             "index missing", kind=CORRECTNESS)]

    monkeypatch.setattr(
        indexes_module, "validate_appointment_indexes", _correctness_problem)
    result = await preflight()

    assert result["gates"]["indexes_valid"] is False
    assert result["safe_to_activate"] is False
    assert "indexes_valid" in result["failed_gates"]
    assert result["query_index_problems"] == []


def test_the_report_says_when_only_query_indexes_are_missing():
    """An operator reading "INDEXES NOT READY" stops the rollout. When the only
    thing missing costs speed, the line has to say so."""
    from app.db.appointment_slot_preflight import render

    text = render({
        "database": "x", "indexes_ready": False,
        "problems": [{"code": "missing", "collection": "appointments",
                      "name": "appointment_pending_expiry", "kind": "query",
                      "message": "index missing"}],
        "query_index_problems": [{"code": "missing", "collection": "appointments",
                                  "name": "appointment_pending_expiry",
                                  "kind": "query", "message": "index missing"}],
        "safe_to_activate": True, "gates": {}, "failed_gates": [],
        "findings": [], "build_blocking_rows": 0, "rows_needing_backfill": 0,
        "obsolete_present": [], "recommended_create": [], "recommended_drop": [],
    })

    assert "does not block activation" in text
    assert "SAFE TO ACTIVATE" in text
