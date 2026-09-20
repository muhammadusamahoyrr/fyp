"""When a lawyer works, and what follows from not having said.

THE GAP THIS CLOSES

Nothing could answer "does this lawyer work then?". Booking accepted any
aligned future half-hour, and the client's picker offered six hardcoded times —
09:00, 10:00, 11:00, 14:00, 15:00, 16:00 — identical for every lawyer and every
day of the week, so Sunday 09:00 was as bookable as Tuesday 10:00. Those six
times were not a schedule anybody had agreed to.

THE RULE THAT SHAPES EVERY TEST BELOW

A lawyer who has not saved a schedule has NO working hours — not default ones.
The tempting fallback, Monday to Saturday nine to five, would be this system
telling clients that a real person is available at times that person never
agreed to. So an unconfigured lawyer yields `configured: false` and no slots,
and the tests treat any invented hour as a failure.

ENFORCEMENT IS A SWITCH, OFF BY DEFAULT. Every lawyer on the system today
signed up before schedules existed; enforcing against an absent one would make
all of them unbookable the moment this deployed. Both sides of that switch are
exercised here, because a flag only one branch of which is tested is a flag
with an untested branch.
"""
import secrets
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.constants import AppointmentMode
from app.core.exceptions import (
    AppValidationError,
    ForbiddenError,
    NotFoundError,
)
from app.services import lawyer_availability as policy
from app.services import lawyer_availability_service as svc

pytestmark = pytest.mark.integration

# A Tuesday and a Sunday, chosen once so every test reads the same calendar.
TUESDAY = date(2026, 10, 6)
WEDNESDAY = date(2026, 10, 7)
SUNDAY = date(2026, 10, 11)
LONG_AGO = datetime(2020, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
async def parties(app_indexes):
    from app.db.collections import (
        get_appointments_col,
        get_lawyer_availability_col,
        get_users_col,
    )

    tag = secrets.token_hex(4)
    lawyer_id, lawyer2_id = f"AV-L-{tag}", f"AV-L2-{tag}"
    client_id, admin_id = f"AV-C-{tag}", f"AV-A-{tag}"
    now = datetime.now(timezone.utc)

    def _lawyer(_id, name):
        return {"_id": _id, "role": "lawyer", "is_active": True,
                "email": f"{_id}@test.invalid", "full_name": name,
                "province": "punjab", "created_at": now,
                "lawyer_profile": {"specializations": ["criminal"],
                                   "kyc_verified": True, "rating": 4.0,
                                   "total_reviews": 0, "availability": True,
                                   "experience_years": 5}}

    await get_users_col().insert_many([
        _lawyer(lawyer_id, "Adv One"), _lawyer(lawyer2_id, "Adv Two"),
        {"_id": client_id, "role": "client", "is_active": True,
         "email": f"{client_id}@test.invalid", "full_name": "Client One",
         "created_at": now},
        {"_id": admin_id, "role": "admin", "is_active": True,
         "email": f"{admin_id}@test.invalid", "full_name": "The Admin",
         "created_at": now},
    ])
    yield {"lawyer_id": lawyer_id, "lawyer2_id": lawyer2_id,
           "client_id": client_id, "admin_id": admin_id}
    await get_users_col().delete_many(
        {"_id": {"$in": [lawyer_id, lawyer2_id, client_id, admin_id]}})
    await get_lawyer_availability_col().delete_many(
        {"_id": {"$in": [lawyer_id, lawyer2_id]}})
    await get_appointments_col().delete_many(
        {"lawyer_id": {"$in": [lawyer_id, lawyer2_id]}})


@pytest.fixture
def enforcement():
    """Turn booking enforcement on or off, and always put it back."""
    from app.core.config import settings

    original = settings.appointment_working_hours_enforced

    def _set(value: bool):
        settings.appointment_working_hours_enforced = value

    yield _set
    settings.appointment_working_hours_enforced = original


def hours(*intervals):
    """`hours((1, "09:00", "17:00"))` — weekday, start, end."""
    return [{"weekday": w, "start": s, "end": e} for w, s, e in intervals]


async def _save(parties, intervals, exceptions=(), lawyer_id=None):
    lawyer_id = lawyer_id or parties["lawyer_id"]
    return await svc.replace_own(
        actor_id=lawyer_id, actor_role="lawyer", lawyer_id=lawyer_id,
        working_hours=intervals, exceptions=list(exceptions))


def _times(day_result):
    return [s["local_time"] for s in day_result["slots"]]


# ── 1. The policy, pure ──────────────────────────────────────────────────────

def test_a_normal_interval_is_accepted():
    assert policy.validate_intervals(hours((1, "09:00", "17:00"))) == [
        {"weekday": 1, "start": "09:00", "end": "17:00"}]


@pytest.mark.parametrize("bad", ["09:15", "9:00", "09:00:00", "0900", "25:00",
                                 "09:60", "", "nine"])
def test_a_start_off_the_half_hour_grid_is_refused(bad):
    """The overlap guarantee is an index over discrete half-hours, and it only
    works because every start lands on the grid. Hours beginning at 09:15 would
    advertise starts the booking path must then refuse."""
    with pytest.raises(policy.ScheduleError):
        policy.validate_intervals(hours((1, bad, "17:00")))


@pytest.mark.parametrize("start,end", [("09:00", "09:00"), ("17:00", "09:00"),
                                       ("12:30", "12:00")])
def test_end_must_be_strictly_after_start(start, end):
    with pytest.raises(policy.ScheduleError, match="after start"):
        policy.validate_intervals(hours((1, start, end)))


def test_a_thirty_minute_interval_is_the_shortest_legal_one():
    """The boundary of "end after start": exactly one slot long."""
    assert policy.validate_intervals(hours((1, "09:00", "09:30")))


@pytest.mark.parametrize("bad_weekday", [-1, 7, 99, "monday", 1.5, True, None])
def test_a_weekday_outside_monday_to_sunday_is_refused(bad_weekday):
    with pytest.raises(policy.ScheduleError):
        policy.validate_intervals(
            [{"weekday": bad_weekday, "start": "09:00", "end": "17:00"}])


def test_overlapping_intervals_on_one_weekday_are_refused():
    """Two intervals covering the same hour do not make it doubly available;
    they make the stored schedule ambiguous. Merging them quietly would accept
    input the lawyer did not write."""
    with pytest.raises(policy.ScheduleError, match="overlaps"):
        policy.validate_intervals(
            hours((1, "09:00", "12:00"), (1, "11:00", "13:00")))


def test_intervals_that_merely_touch_are_allowed():
    """09:00–12:00 and 12:00–17:00 share only the boundary instant, and the
    slot model is half-open, so they claim no half-hour in common."""
    assert len(policy.validate_intervals(
        hours((1, "09:00", "12:00"), (1, "12:00", "17:00")))) == 2


def test_identical_hours_on_different_weekdays_are_not_an_overlap():
    assert len(policy.validate_intervals(
        hours((1, "09:00", "17:00"), (2, "09:00", "17:00")))) == 2


def test_intervals_are_stored_in_a_stable_order():
    """Two saves of the same schedule are byte-identical, so a diff of the
    stored document means something."""
    a = policy.validate_intervals(
        hours((3, "14:00", "16:00"), (1, "09:00", "12:00"), (1, "13:00", "14:00")))
    b = policy.validate_intervals(
        hours((1, "13:00", "14:00"), (3, "14:00", "16:00"), (1, "09:00", "12:00")))
    assert a == b
    assert [i["weekday"] for i in a] == [1, 1, 3]


@pytest.mark.parametrize("bad", ["not-a-date", "2026-13-01", "2026-02-30",
                                 "06/10/2026", "", 20261006])
def test_a_malformed_exception_date_is_refused(bad):
    with pytest.raises(policy.ScheduleError):
        policy.validate_exceptions([{"date": bad}])


def test_a_duplicate_exception_date_is_refused():
    with pytest.raises(policy.ScheduleError, match="more than once"):
        policy.validate_exceptions(
            [{"date": "2026-10-06"}, {"date": "2026-10-06", "reason": "leave"}])


@pytest.mark.parametrize("malformed", ["not a list", 42, None])
def test_a_schedule_that_is_not_a_list_is_refused(malformed):
    with pytest.raises(policy.ScheduleError):
        policy.validate_intervals(malformed)
    with pytest.raises(policy.ScheduleError):
        policy.validate_exceptions(malformed)


def test_an_interval_that_is_not_an_object_is_refused():
    with pytest.raises(policy.ScheduleError):
        policy.validate_intervals(["09:00-17:00"])


# ── 2. Weekdays and PKT calendar days ────────────────────────────────────────

def test_the_weekday_numbering_matches_pythons():
    """Stored values need no translation, so they cannot be read off by one."""
    assert TUESDAY.weekday() == 1
    assert SUNDAY.weekday() == 6
    assert policy.WEEKDAY_NAMES[TUESDAY.weekday()] == "Tuesday"


def test_slots_appear_only_on_the_configured_weekday():
    schedule = policy.validate_schedule(hours((1, "09:00", "11:00")), [])

    assert policy.candidate_starts(schedule, TUESDAY, 60)
    assert policy.candidate_starts(schedule, WEDNESDAY, 60) == []
    assert policy.candidate_starts(schedule, SUNDAY, 60) == []


def test_a_slot_is_the_pkt_wall_clock_time_the_lawyer_wrote():
    """PKT is UTC+5, so 09:00 in Pakistan is 04:00 UTC. A schedule read in the
    server's zone would move every appointment five hours."""
    schedule = policy.validate_schedule(hours((1, "09:00", "10:00")), [])

    start = policy.candidate_starts(schedule, TUESDAY, 60)[0]

    assert start == datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc)
    assert policy.local_label(start) == "09:00"


def test_a_pkt_day_is_not_a_utc_day():
    """00:30 PKT on Wednesday is 19:30 UTC on TUESDAY. Grouping by UTC date
    would file that slot under the wrong day, and a client asking about
    Wednesday would not be shown it."""
    schedule = policy.validate_schedule(hours((2, "00:00", "02:00")), [])

    starts = policy.candidate_starts(schedule, WEDNESDAY, 60)

    assert [policy.local_label(s) for s in starts] == ["00:00", "00:30", "01:00"]
    assert starts[0].astimezone(timezone.utc).date() == TUESDAY
    assert starts[0].astimezone(policy.SCHEDULE_TZ).date() == WEDNESDAY


def test_a_consultation_must_fit_entirely_inside_the_interval():
    """A 90-minute consultation starting at 16:30 of a 09:00–17:00 day runs an
    hour past the end. Offering it would advertise a time the lawyer has not
    agreed to work."""
    schedule = policy.validate_schedule(hours((1, "09:00", "12:00")), [])

    sixty = [policy.local_label(s)
             for s in policy.candidate_starts(schedule, TUESDAY, 60)]
    ninety = [policy.local_label(s)
              for s in policy.candidate_starts(schedule, TUESDAY, 90)]

    assert sixty[-1] == "11:00"
    assert ninety[-1] == "10:30"


def test_an_exception_day_removes_every_slot():
    schedule = policy.validate_schedule(
        hours((1, "09:00", "17:00")), [{"date": TUESDAY.isoformat()}])

    assert policy.candidate_starts(schedule, TUESDAY, 60) == []
    assert policy.candidate_starts(schedule, TUESDAY + timedelta(days=7), 60)


def test_an_exception_on_another_day_changes_nothing():
    schedule = policy.validate_schedule(
        hours((1, "09:00", "11:00")), [{"date": WEDNESDAY.isoformat()}])

    assert policy.candidate_starts(schedule, TUESDAY, 60)


# ── 3. Subtraction: booked, past, terminal ───────────────────────────────────

def _slot_at(day, hh, mm=0):
    return datetime(day.year, day.month, day.day, hh, mm,
                    tzinfo=policy.SCHEDULE_TZ).astimezone(timezone.utc)


def test_a_booked_hour_is_removed():
    schedule = policy.validate_schedule(hours((1, "09:00", "12:00")), [])
    taken = {_slot_at(TUESDAY, 10, 0), _slot_at(TUESDAY, 10, 30)}

    free = policy.bookable_slots(schedule, TUESDAY, 60, taken, LONG_AGO)

    assert [policy.local_label(s) for s in free] == ["09:00", "11:00"]


def test_a_slot_overlapping_a_booking_by_one_half_hour_is_removed():
    """The same overlap test the unique index enforces, asked in advance: a
    candidate goes if ANY half-hour it would occupy is taken."""
    schedule = policy.validate_schedule(hours((1, "09:00", "12:00")), [])
    taken = {_slot_at(TUESDAY, 10, 30)}

    free = [policy.local_label(s) for s in
            policy.bookable_slots(schedule, TUESDAY, 60, taken, LONG_AGO)]

    assert "10:00" not in free      # would occupy 10:00 and 10:30
    assert "10:30" not in free
    # 09:30 SURVIVES: it occupies 09:30 and 10:00, neither taken. The test is
    # about which half-hours a candidate claims, not how close it sits.
    assert free == ["09:00", "09:30", "11:00"]


def test_a_time_that_has_passed_is_not_offered():
    schedule = policy.validate_schedule(hours((1, "09:00", "12:00")), [])
    now = _slot_at(TUESDAY, 10, 0)

    free = [policy.local_label(s) for s in
            policy.bookable_slots(schedule, TUESDAY, 60, set(), now)]

    assert free == ["10:30", "11:00"], "a slot at or before now was offered"


def test_a_malformed_duration_is_refused_rather_than_guessed():
    schedule = policy.validate_schedule(hours((1, "09:00", "12:00")), [])

    for bad in (45, 0, -30, 200, "60"):
        with pytest.raises(policy.ScheduleError):
            policy.bookable_slots(schedule, TUESDAY, bad, set(), LONG_AGO)


# ── 4. Unconfigured lawyers ──────────────────────────────────────────────────

def test_an_unconfigured_schedule_yields_no_slots():
    for schedule in (None, {}, {"working_hours": []}):
        assert policy.is_configured(schedule) is False
        assert policy.candidate_starts(schedule, TUESDAY, 60) == []
        assert policy.bookable_slots(schedule, TUESDAY, 60, set(), LONG_AGO) == []


def test_no_default_working_hours_exist_anywhere():
    """THE INVENTION THIS MODULE REFUSES TO MAKE.

    Monday-to-Saturday nine-to-five is the plausible fallback, and it would be
    this system telling clients a real person is available at times they never
    agreed to. Asserted against the source so it cannot creep back as a
    "sensible default" in a later change.
    """
    import ast
    import inspect

    for module in (policy, svc):
        source = inspect.getsource(module)
        # Comments AND docstrings are stripped: both modules explain at length
        # why they refuse to invent Monday-to-Saturday nine-to-five, so a naive
        # text scan fails on the very reasoning it exists to protect.
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
                # `clean=False`: the cleaned form has its indentation and
                # blank lines normalised, so it no longer matches the raw
                # source text and the replace silently does nothing.
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    source = source.replace(doc, "")
        code = "\n".join(
            line for line in source.splitlines()
            if not line.lstrip().startswith("#"))
        for invented in ("09:00", "17:00", "DEFAULT_HOURS",
                         "DEFAULT_WORKING"):
            assert invented not in code, (
                f"{module.__name__} contains a hardcoded hour: {invented!r}")


async def test_an_unconfigured_lawyer_is_reported_honestly(parties):
    view = await svc.public_availability(parties["lawyer_id"])

    assert view["configured"] is False
    assert view["working_hours"] == []
    assert "not set their working hours" in view["message"]


async def test_the_public_view_carries_no_private_reasons(parties):
    """ASSERTED ON THE SERVICE, NOT THE RESPONSE MODEL.

    `PublicAvailabilityResponse` drops undeclared keys, so adding `exceptions`
    to what this function returns is invisible over HTTP — verified by doing
    exactly that and watching every wire test still pass. The schema would keep
    the secret while the service gave it away to any direct caller, which is
    the same trap `AppointmentOut` set for `lawyer_notes`: a response model is
    not a privacy boundary.
    """
    await _save(parties, hours((1, "09:00", "12:00")),
                [{"date": SUNDAY.isoformat(), "reason": "bereavement"}])

    view = await svc.public_availability(parties["lawyer_id"])

    assert view["unavailable_dates"] == [SUNDAY.isoformat()]
    assert "exceptions" not in view
    assert "bereavement" not in repr(view)


async def test_an_unconfigured_lawyer_offers_no_bookable_slots(parties):
    result = await svc.bookable_slots(
        parties["lawyer_id"], from_date=TUESDAY, to_date=SUNDAY)

    assert result["configured"] is False
    assert len(result["days"]) == 6
    assert all(day["slots"] == [] for day in result["days"])


async def test_saving_an_empty_schedule_is_not_a_configuration(parties):
    """A document with no intervals says the lawyer works no hours, which is
    indistinguishable in effect from never having answered."""
    await _save(parties, [])

    view = await svc.public_availability(parties["lawyer_id"])

    assert view["configured"] is False


# ── 5. Round trips, authorisation and ownership ──────────────────────────────

async def test_a_lawyer_can_save_and_read_back_their_schedule(parties):
    saved = await _save(
        parties, hours((1, "09:00", "12:00"), (3, "14:00", "16:00")),
        [{"date": SUNDAY.isoformat(), "reason": "family"}])

    assert saved["configured"] is True
    assert saved["timezone"] == "Asia/Karachi"

    read = await svc.read_own(
        parties["lawyer_id"], "lawyer", parties["lawyer_id"])

    assert read["working_hours"] == saved["working_hours"]
    assert read["exceptions"] == [{"date": SUNDAY.isoformat(),
                                   "reason": "family"}]
    assert read["updated_at"] is not None


async def test_saving_replaces_rather_than_merges(parties):
    await _save(parties, hours((1, "09:00", "12:00"), (2, "09:00", "12:00")))
    await _save(parties, hours((4, "10:00", "11:00")))

    read = await svc.read_own(
        parties["lawyer_id"], "lawyer", parties["lawyer_id"])

    assert read["working_hours"] == [
        {"weekday": 4, "start": "10:00", "end": "11:00"}]


async def test_a_lawyer_cannot_write_another_lawyers_schedule(parties):
    with pytest.raises(ForbiddenError):
        await svc.replace_own(
            actor_id=parties["lawyer_id"], actor_role="lawyer",
            lawyer_id=parties["lawyer2_id"],
            working_hours=hours((1, "09:00", "12:00")), exceptions=[])


async def test_a_lawyer_cannot_read_another_lawyers_private_schedule(parties):
    await _save(parties, hours((1, "09:00", "12:00")),
                [{"date": SUNDAY.isoformat(), "reason": "surgery"}],
                lawyer_id=parties["lawyer2_id"])

    with pytest.raises(ForbiddenError):
        await svc.read_own(
            parties["lawyer_id"], "lawyer", parties["lawyer2_id"])


async def test_a_client_cannot_manage_a_schedule(parties):
    with pytest.raises(ForbiddenError):
        await svc.replace_own(
            actor_id=parties["client_id"], actor_role="client",
            lawyer_id=parties["lawyer_id"],
            working_hours=hours((1, "09:00", "12:00")), exceptions=[])


async def test_an_admin_may_manage_by_the_repositorys_explicit_policy(parties):
    """Admin access is granted BY NAME here, the way `case_service`
    `_assert_access` and `appointment_service._actor_filter` grant it.

    Appointments learned this the hard way: admin access there was the ABSENCE
    of a rule — the role failed both ownership tests and fell through into full
    access — so an unknown future role inherited the same silent power.
    """
    await svc.replace_own(
        actor_id=parties["admin_id"], actor_role="admin",
        lawyer_id=parties["lawyer_id"],
        working_hours=hours((1, "09:00", "12:00")), exceptions=[])

    read = await svc.read_own(
        parties["admin_id"], "admin", parties["lawyer_id"])
    assert read["configured"] is True


@pytest.mark.parametrize("role", ["client", "paralegal", "", None, "Lawyer"])
async def test_no_other_role_may_manage_a_schedule(parties, role):
    """Unknown roles are refused rather than falling through."""
    with pytest.raises(ForbiddenError):
        await svc.read_own(parties["lawyer_id"], role, parties["lawyer_id"])


async def test_a_schedule_cannot_be_saved_for_someone_who_is_not_a_lawyer(parties):
    with pytest.raises(NotFoundError):
        await svc.replace_own(
            actor_id=parties["admin_id"], actor_role="admin",
            lawyer_id=parties["client_id"],
            working_hours=hours((1, "09:00", "12:00")), exceptions=[])


async def test_an_invalid_schedule_is_refused_with_the_reason(parties):
    """The message names the offending interval, because it is written for the
    lawyer who has to fix it."""
    with pytest.raises(AppValidationError, match="overlaps"):
        await _save(parties, hours((1, "09:00", "12:00"), (1, "11:00", "13:00")))

    view = await svc.public_availability(parties["lawyer_id"])
    assert view["configured"] is False, "a refused save was stored anyway"


# ── 6. Bookable slots through the service, with real appointments ────────────

async def _book(parties, when, duration=60, status=None):
    from app.db.collections import get_appointments_col
    from app.services import appointment_service

    made = await appointment_service.book_appointment(
        client_id=parties["client_id"], lawyer_id=parties["lawyer_id"],
        case_id=None, scheduled_at=when, duration_minutes=duration,
        mode=AppointmentMode.VIDEO, notes=None)
    if status:
        await get_appointments_col().update_one(
            {"_id": made["id"]}, {"$set": {"status": status}})
    return made["id"]


def _future_tuesday() -> date:
    """A Tuesday far enough ahead that nothing in it has passed."""
    day = (datetime.now(policy.SCHEDULE_TZ) + timedelta(days=14)).date()
    return day + timedelta(days=(1 - day.weekday()) % 7)


async def test_the_service_returns_the_configured_times(parties):
    day = _future_tuesday()
    await _save(parties, hours((1, "09:00", "12:00")))

    result = await svc.bookable_slots(parties["lawyer_id"], from_date=day)

    assert result["configured"] is True
    assert _times(result["days"][0]) == ["09:00", "09:30", "10:00", "10:30",
                                         "11:00"]


async def test_a_pending_appointment_blocks_its_slots(parties):
    """PENDING holds its hours — that is what the partial unique indexes are
    scoped to, and offering the hour to somebody else would produce a booking
    the index then refuses."""
    day = _future_tuesday()
    await _save(parties, hours((1, "09:00", "12:00")))
    await _book(parties, _slot_at(day, 10, 0))

    result = await svc.bookable_slots(parties["lawyer_id"], from_date=day)

    assert _times(result["days"][0]) == ["09:00", "11:00"]


async def test_a_confirmed_appointment_blocks_its_slots(parties):
    day = _future_tuesday()
    await _save(parties, hours((1, "09:00", "12:00")))
    await _book(parties, _slot_at(day, 9, 0), status="confirmed")

    result = await svc.bookable_slots(parties["lawyer_id"], from_date=day)

    assert "09:00" not in _times(result["days"][0])


@pytest.mark.parametrize("terminal", ["cancelled", "completed", "no_show",
                                      "expired"])
async def test_a_terminal_appointment_releases_its_slots(parties, terminal):
    """The mirror of the index's partial filter: a cancelled or expired
    consultation stops holding its hours, and the advice must agree with the
    guarantee."""
    day = _future_tuesday()
    await _save(parties, hours((1, "09:00", "12:00")))
    await _book(parties, _slot_at(day, 10, 0), status=terminal)

    result = await svc.bookable_slots(parties["lawyer_id"], from_date=day)

    assert "10:00" in _times(result["days"][0])


async def test_another_lawyers_appointments_do_not_block_these_slots(parties):
    day = _future_tuesday()
    await _save(parties, hours((1, "09:00", "12:00")))
    await _save(parties, hours((1, "09:00", "12:00")),
                lawyer_id=parties["lawyer2_id"])

    from app.services import appointment_service
    await appointment_service.book_appointment(
        client_id=parties["client_id"], lawyer_id=parties["lawyer2_id"],
        case_id=None, scheduled_at=_slot_at(day, 10, 0), duration_minutes=60,
        mode=AppointmentMode.VIDEO, notes=None)

    result = await svc.bookable_slots(parties["lawyer_id"], from_date=day)

    assert "10:00" in _times(result["days"][0])


async def test_an_exception_day_is_empty_through_the_service(parties):
    day = _future_tuesday()
    await _save(parties, hours((1, "09:00", "12:00")),
                [{"date": day.isoformat(), "reason": "leave"}])

    result = await svc.bookable_slots(parties["lawyer_id"], from_date=day)

    assert result["days"][0]["slots"] == []


async def test_a_range_returns_every_day_including_empty_ones(parties):
    day = _future_tuesday()
    await _save(parties, hours((1, "09:00", "11:00")))

    result = await svc.bookable_slots(
        parties["lawyer_id"], from_date=day, to_date=day + timedelta(days=3))

    assert [d["date"] for d in result["days"]] == [
        (day + timedelta(days=n)).isoformat() for n in range(4)]
    # 09:00-11:00 fits three hour-long starts: 09:00, 09:30 and 10:00, the
    # last ending exactly at 11:00.
    assert _times(result["days"][0]) == ["09:00", "09:30", "10:00"]
    assert all(d["slots"] == [] for d in result["days"][1:])


async def test_an_unbounded_range_is_refused(parties):
    """A weekly schedule repeats for ever, so "give me the slots" without a
    bound has no answer."""
    day = _future_tuesday()
    with pytest.raises(AppValidationError):
        await svc.bookable_slots(
            parties["lawyer_id"], from_date=day,
            to_date=day + timedelta(days=400))


async def test_a_backwards_range_is_refused(parties):
    day = _future_tuesday()
    with pytest.raises(AppValidationError):
        await svc.bookable_slots(
            parties["lawyer_id"], from_date=day,
            to_date=day - timedelta(days=2))


async def test_slots_for_an_unknown_lawyer_are_refused(parties):
    with pytest.raises(NotFoundError):
        await svc.bookable_slots("AV-NOBODY", from_date=_future_tuesday())


# ── 7. Enforcement: off, then on ─────────────────────────────────────────────

async def test_with_enforcement_off_an_unconfigured_lawyer_is_still_bookable(
        parties, enforcement):
    """THE ROLLOUT GUARANTEE. Every lawyer on the system today signed up before
    schedules existed; enforcing against an absent one would make all of them
    unbookable the moment this deployed."""
    enforcement(False)
    day = _future_tuesday()

    appt = await _book(parties, _slot_at(day, 10, 0))

    assert appt


async def test_with_enforcement_off_a_time_outside_the_schedule_is_accepted(
        parties, enforcement):
    """The contract is unchanged while the switch is off — but the availability
    lookup says so rather than calling the time available."""
    enforcement(False)
    day = _future_tuesday()
    await _save(parties, hours((1, "09:00", "10:00")))

    appt = await _book(parties, _slot_at(day, 15, 0))
    assert appt

    view = await svc.public_availability(parties["lawyer_id"])
    assert view["enforced"] is False
    assert "not yet enforced" in view["message"]


async def test_with_enforcement_on_an_unconfigured_lawyer_cannot_be_booked(
        parties, enforcement):
    enforcement(True)
    day = _future_tuesday()

    with pytest.raises(AppValidationError, match="has not set their working hours"):
        await _book(parties, _slot_at(day, 10, 0))


async def test_with_enforcement_on_a_time_outside_the_schedule_is_refused(
        parties, enforcement):
    enforcement(True)
    day = _future_tuesday()
    await _save(parties, hours((1, "09:00", "12:00")))

    with pytest.raises(AppValidationError, match="outside this lawyer's working hours"):
        await _book(parties, _slot_at(day, 15, 0))


async def test_with_enforcement_on_a_time_inside_the_schedule_is_accepted(
        parties, enforcement):
    enforcement(True)
    day = _future_tuesday()
    await _save(parties, hours((1, "09:00", "12:00")))

    assert await _book(parties, _slot_at(day, 10, 0))


async def test_with_enforcement_on_the_wrong_weekday_is_refused(
        parties, enforcement):
    enforcement(True)
    day = _future_tuesday()
    await _save(parties, hours((1, "09:00", "12:00")))

    with pytest.raises(AppValidationError):
        await _book(parties, _slot_at(day + timedelta(days=1), 10, 0))


async def test_with_enforcement_on_an_exception_day_is_refused(
        parties, enforcement):
    enforcement(True)
    day = _future_tuesday()
    await _save(parties, hours((1, "09:00", "12:00")),
                [{"date": day.isoformat()}])

    with pytest.raises(AppValidationError):
        await _book(parties, _slot_at(day, 10, 0))


async def test_with_enforcement_on_a_consultation_overrunning_the_day_is_refused(
        parties, enforcement):
    """A 90-minute appointment at 11:00 in a 09:00–12:00 day ends at 12:30."""
    enforcement(True)
    day = _future_tuesday()
    await _save(parties, hours((1, "09:00", "12:00")))

    with pytest.raises(AppValidationError):
        await _book(parties, _slot_at(day, 11, 0), duration=90)

    assert await _book(parties, _slot_at(day, 9, 0), duration=90)


async def test_enforcement_is_read_at_call_time(parties, enforcement):
    """A module-level snapshot of the flag could not be turned on without a
    restart, and tests could never exercise both branches."""
    enforcement(False)
    assert svc.enforcement_enabled() is False
    enforcement(True)
    assert svc.enforcement_enabled() is True


async def test_the_flag_defaults_to_off():
    from app.core.config import Settings

    assert Settings().appointment_working_hours_enforced is False


async def test_enforcement_does_not_weaken_the_overlap_guarantee(
        parties, enforcement):
    """Whatever the flag says, two clients cannot hold one hour. The advice is
    computed ahead of the index; it never replaces it."""
    from app.core.exceptions import ConflictError
    from app.services import appointment_service

    enforcement(True)
    day = _future_tuesday()
    await _save(parties, hours((1, "09:00", "12:00")))
    await _book(parties, _slot_at(day, 10, 0))

    with pytest.raises((ConflictError, AppValidationError)):
        await appointment_service.book_appointment(
            client_id=parties["admin_id"], lawyer_id=parties["lawyer_id"],
            case_id=None, scheduled_at=_slot_at(day, 10, 0),
            duration_minutes=60, mode=AppointmentMode.VIDEO, notes=None)


# ── 8. The HTTP boundary ─────────────────────────────────────────────────────
#
# The service is tested directly above, deliberately: a rule that only holds
# because a Pydantic model rejected the input is a rule that vanishes the
# moment anything calls the service another way. These tests are about who may
# reach each endpoint and what the wire carries — not about the rules again.


@pytest.fixture
async def http(parties):
    import httpx
    from httpx import ASGITransport

    from app.dependencies import get_current_user, require_lawyer
    from app.main import app

    state = {"user": None}

    async def _current():
        user = state["user"]
        if user is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="not authenticated")
        return user

    async def _lawyer():
        user = await _current()
        if user.get("role") != "lawyer":
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="lawyers only")
        return user

    app.dependency_overrides[get_current_user] = _current
    app.dependency_overrides[require_lawyer] = _lawyer
    async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test/api/v1") as client:
        client.act_as = lambda user: state.__setitem__("user", user)
        yield client
    app.dependency_overrides.clear()


def _as(role, user_id):
    return {"_id": user_id, "role": role, "is_active": True}


SCHEDULE_BODY = {
    "working_hours": [{"weekday": 1, "start": "09:00", "end": "12:00"}],
    "exceptions": [{"date": "2026-10-11", "reason": "family"}],
}


async def test_a_lawyer_saves_and_reads_back_over_http(http, parties):
    http.act_as(_as("lawyer", parties["lawyer_id"]))

    saved = await http.put("/lawyers/me/availability", json=SCHEDULE_BODY)
    assert saved.status_code == 200, saved.text

    read = await http.get("/lawyers/me/availability")

    assert read.status_code == 200
    body = read.json()
    assert body["working_hours"] == SCHEDULE_BODY["working_hours"]
    assert body["exceptions"] == SCHEDULE_BODY["exceptions"]
    assert body["configured"] is True
    assert body["timezone"] == "Asia/Karachi"


async def test_the_write_path_takes_the_lawyer_from_the_token(http, parties):
    """There is deliberately no route that accepts a lawyer id to write to. A
    write that names its own subject is an authorisation bug waiting for a
    caller to notice it."""
    from app.main import app

    writable = [r.path for r in app.routes
                if "availability" in getattr(r, "path", "")
                and "PUT" in getattr(r, "methods", set())]

    assert writable == ["/api/v1/lawyers/me/availability"]


async def test_a_client_cannot_write_working_hours(http, parties):
    http.act_as(_as("client", parties["client_id"]))

    r = await http.put("/lawyers/me/availability", json=SCHEDULE_BODY)

    assert r.status_code == 403


async def test_an_anonymous_caller_cannot_write_working_hours(http, parties):
    http.act_as(None)

    r = await http.put("/lawyers/me/availability", json=SCHEDULE_BODY)

    assert r.status_code == 401


async def test_me_is_not_treated_as_a_lawyer_id(http, parties):
    """`/me/availability` is declared before `/{lawyer_id}/availability`. Were
    it not, a lawyer reading "their own" schedule would silently be asking for
    the schedule of a lawyer whose id is the literal string "me"."""
    http.act_as(_as("lawyer", parties["lawyer_id"]))
    await http.put("/lawyers/me/availability", json=SCHEDULE_BODY)

    r = await http.get("/lawyers/me/availability")

    assert r.status_code == 200
    assert r.json()["lawyer_id"] == parties["lawyer_id"]


async def test_the_public_view_hides_the_reason_for_a_day_off(http, parties):
    """"Surgery", "bereavement" — a fact about a person's life that happens to
    live next to a calendar. Availability is not a reason to disclose it."""
    http.act_as(_as("lawyer", parties["lawyer_id"]))
    await http.put("/lawyers/me/availability", json={
        "working_hours": SCHEDULE_BODY["working_hours"],
        "exceptions": [{"date": "2026-10-11", "reason": "surgery"}],
    })

    http.act_as(_as("client", parties["client_id"]))
    r = await http.get(f"/lawyers/{parties['lawyer_id']}/availability")

    assert r.status_code == 200
    body = r.json()
    assert body["unavailable_dates"] == ["2026-10-11"]
    assert "surgery" not in r.text
    assert "exceptions" not in body


async def test_a_client_cannot_read_a_lawyers_private_schedule(http, parties):
    http.act_as(_as("lawyer", parties["lawyer_id"]))
    await http.put("/lawyers/me/availability", json=SCHEDULE_BODY)

    http.act_as(_as("client", parties["client_id"]))
    r = await http.get("/lawyers/me/availability")

    assert r.status_code == 403


async def test_an_unconfigured_lawyer_reads_as_unconfigured_over_http(
        http, parties):
    http.act_as(_as("client", parties["client_id"]))

    r = await http.get(f"/lawyers/{parties['lawyer_id']}/availability")

    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["working_hours"] == []
    assert "not set their working hours" in body["message"]


async def test_bookable_slots_over_http(http, parties):
    day = _future_tuesday()
    http.act_as(_as("lawyer", parties["lawyer_id"]))
    await http.put("/lawyers/me/availability", json={
        "working_hours": [{"weekday": 1, "start": "09:00", "end": "11:00"}],
        "exceptions": [],
    })

    http.act_as(_as("client", parties["client_id"]))
    r = await http.get(f"/lawyers/{parties['lawyer_id']}/bookable-slots",
                       params={"from": day.isoformat()})

    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert [s["local_time"] for s in body["days"][0]["slots"]] == [
        "09:00", "09:30", "10:00"]
    assert body["days"][0]["slots"][0]["start"].endswith("Z")


async def test_bookable_slots_needs_a_date(http, parties):
    http.act_as(_as("client", parties["client_id"]))

    r = await http.get(f"/lawyers/{parties['lawyer_id']}/bookable-slots")

    assert r.status_code == 422


async def test_bookable_slots_refuses_an_off_grid_duration(http, parties):
    http.act_as(_as("client", parties["client_id"]))

    r = await http.get(f"/lawyers/{parties['lawyer_id']}/bookable-slots",
                       params={"from": _future_tuesday().isoformat(),
                               "duration_minutes": 45})

    assert r.status_code in (400, 422)


async def test_an_anonymous_caller_cannot_read_availability(http, parties):
    http.act_as(None)

    assert (await http.get(
        f"/lawyers/{parties['lawyer_id']}/availability")).status_code == 401
    assert (await http.get(
        f"/lawyers/{parties['lawyer_id']}/bookable-slots",
        params={"from": _future_tuesday().isoformat()})).status_code == 401


async def test_an_invalid_schedule_is_refused_over_http_with_its_reason(
        http, parties):
    http.act_as(_as("lawyer", parties["lawyer_id"]))

    r = await http.put("/lawyers/me/availability", json={
        "working_hours": [
            {"weekday": 1, "start": "09:00", "end": "12:00"},
            {"weekday": 1, "start": "11:00", "end": "13:00"},
        ],
        "exceptions": [],
    })

    assert r.status_code in (400, 422)
    assert "overlap" in r.text.lower()


async def test_an_off_grid_interval_is_refused_over_http(http, parties):
    http.act_as(_as("lawyer", parties["lawyer_id"]))

    r = await http.put("/lawyers/me/availability", json={
        "working_hours": [{"weekday": 1, "start": "09:15", "end": "12:00"}],
        "exceptions": [],
    })

    assert r.status_code in (400, 422)


async def test_clearing_the_schedule_is_allowed_and_reads_unconfigured(
        http, parties):
    """A lawyer may withdraw their hours. It is then honestly reported as
    unconfigured rather than as "available at no times", which would read to a
    client as a schedule somebody meant."""
    http.act_as(_as("lawyer", parties["lawyer_id"]))
    await http.put("/lawyers/me/availability", json=SCHEDULE_BODY)

    r = await http.put("/lawyers/me/availability",
                       json={"working_hours": [], "exceptions": []})

    assert r.status_code == 200
    assert r.json()["configured"] is False
