"""Confirmed consultations nobody reported an outcome for.

A CONFIRMED appointment goes nowhere on its own: only the lawyer can move it to
COMPLETED or NO_SHOW, and if they never do it stays `confirmed` for ever. That
withholds something real — `exists_completed` gates the client's right to
review the lawyer — so the absence of an action quietly removes a right.

This is the READ-ONLY half: a queue and a survey. Nothing here completes an
appointment, notifies anyone, or runs on a schedule.

Three properties carry most of the weight, and each is tested against the
failure it prevents rather than against a number:

  * OWNERSHIP is in the query, not checked afterwards. This is a list of other
    people's consultations.

  * THE PAGINATION IS KEYSET, because rows LEAVE this queue as outcomes are
    recorded. With an offset, every departure shifts the rows behind it and the
    next page steps over one nobody has looked at — the queue would hide
    exactly what it exists to surface.

  * THE SURVEY COUNTS AND NOTHING MORE. No ids, no names, no notes. It exists so
    the decision about notifying people can be taken against real numbers, and
    a survey naming who was at fault would be doing part of that job before the
    decision was made.
"""
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.core.constants import (
    AppointmentMode,
    AppointmentStatus,
    NotificationType,
)
from app.core.exceptions import AppValidationError
from app.services import appointment_outcomes as outcomes

pytestmark = pytest.mark.integration


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
async def parties(app_indexes):
    from app.db.collections import get_appointments_col, get_users_col

    tag = secrets.token_hex(4)
    lawyer_id, lawyer2_id = f"OC-L-{tag}", f"OC-L2-{tag}"
    client_id = f"OC-C-{tag}"
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
    ])
    yield {"lawyer_id": lawyer_id, "lawyer2_id": lawyer2_id,
           "client_id": client_id}
    await get_users_col().delete_many(
        {"_id": {"$in": [lawyer_id, lawyer2_id, client_id]}})
    await get_appointments_col().delete_many(
        {"$or": [{"client_id": client_id},
                 {"lawyer_id": {"$in": [lawyer_id, lawyer2_id]}}]})
    # Notices too: `logical_event_id` is globally unique, so a notice left
    # behind by one test would make the next one's send look like a duplicate
    # that had already been delivered.
    from app.db.collections import get_notifications_col
    await get_notifications_col().delete_many(
        {"user_id": {"$in": [lawyer_id, lawyer2_id, client_id]}})


# A counter giving every fixture row its own `occupied_slots` value.
#
# WHY THESE ROWS STAND OUTSIDE THE SLOT GUARANTEE, DELIBERATELY.
#
# The unique indexes reject two ACTIVE rows for one lawyer — or one client —
# sharing any half-hour, and CONFIRMED is active. Several tests below need two
# confirmed consultations for ONE lawyer ending at the same instant, or a
# microsecond apart, and that state is unreachable through honest slots: any
# two intervals that end together overlap, so real `occupied_slots` for them
# would always collide. Omitting the field is no better — every row then
# indexes as `occupied_slots: null` and the second insert collides too.
#
# It is not a contrived state. The unique indexes are not yet built on any
# deployment (the Phase 3 rollout is NO-GO), so rows exactly like these exist
# today, and they are the first population this queue will meet.
#
# The queue never reads `occupied_slots`. A unique sentinel per row keeps an
# unrelated guarantee out of the way of the one under test, rather than
# weakening it.
_slot_counter = iter(range(1, 10_000))
_SLOT_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


async def _row(parties, *, ended_hours_ago=None, end_at=None, appt_id=None,
               status="confirmed", lawyer_id=None, **over):
    """A stored appointment, written directly.

    Booking refuses past times and confirmation refuses a passed slot, so a
    consultation that has already ENDED cannot be produced through the API at
    all. These rows are the state the queue exists for, so they are written as
    the database holds them.
    """
    from app.db.collections import get_appointments_col

    if end_at is None:
        end_at = datetime.now(timezone.utc) - timedelta(hours=ended_hours_ago)
    start = end_at - timedelta(hours=1)
    doc = {
        "_id": appt_id or f"OC-A-{secrets.token_hex(6)}",
        "client_id": parties["client_id"],
        "lawyer_id": lawyer_id or parties["lawyer_id"],
        "case_id": None,
        "scheduled_at": start,
        "end_at": end_at,
        "duration_minutes": 60,
        "status": status,
        "mode": AppointmentMode.VIDEO.value,
        "timezone": "Asia/Karachi",
        "schedule_version": 0,
        "notes": None,
        "lawyer_notes": None,
        "cancel_reason": None,
        "cancelled_by": None,
        "meeting_link": None,
        "created_at": start - timedelta(days=1),
        "updated_at": start,
        # See `_slot_counter` above: unique per row, so an unrelated index
        # cannot reject the states these tests are about.
        "occupied_slots": [
            _SLOT_EPOCH + timedelta(minutes=30 * next(_slot_counter))],
    }
    doc.update(over)
    await get_appointments_col().insert_one(doc)
    return doc["_id"]


async def _queue(parties, lawyer_id=None, **kw):
    return await outcomes.outstanding_outcomes(
        lawyer_id=lawyer_id or parties["lawyer_id"], **kw)


def _ids(page):
    return [row["_id"] for row in page["items"]]


# ── 1. Which rows are outstanding ────────────────────────────────────────────

async def test_a_finished_consultation_with_no_outcome_is_listed(parties):
    appt = await _row(parties, ended_hours_ago=5)

    page = await _queue(parties)

    assert _ids(page) == [appt]


@pytest.mark.parametrize("status", ["completed", "no_show", "cancelled",
                                    "expired", "pending"])
async def test_only_confirmed_appointments_can_be_outstanding(parties, status):
    """COMPLETED and NO_SHOW are the outcomes themselves — a recorded outcome
    is the exit from this queue. CANCELLED and EXPIRED never happened.

    PENDING is here for a different reason: an unanswered request is the expiry
    mechanism's business, and a row appearing in both queues would be chased by
    two systems with different remedies.
    """
    await _row(parties, ended_hours_ago=5, status=status)

    page = await _queue(parties)

    assert page["items"] == []


async def test_a_consultation_that_has_not_finished_is_not_outstanding(parties):
    from app.db.collections import get_appointments_col

    future_end = datetime.now(timezone.utc) + timedelta(hours=3)
    await get_appointments_col().insert_one({
        "_id": f"OC-A-{secrets.token_hex(6)}",
        "client_id": parties["client_id"], "lawyer_id": parties["lawyer_id"],
        "status": "confirmed", "scheduled_at": future_end - timedelta(hours=1),
        "end_at": future_end, "duration_minutes": 60,
        "occupied_slots": [
            _SLOT_EPOCH + timedelta(minutes=30 * next(_slot_counter))],
    })

    page = await _queue(parties)

    assert page["items"] == []


# ── 2. The grace period, at its boundary ─────────────────────────────────────

async def test_the_grace_period_is_two_hours(parties):
    """A consultation that ran late, or a lawyer who files nothing before
    closing their laptop, is not neglected work minutes after the end."""
    assert outcomes.DEFAULT_GRACE == timedelta(hours=2)


async def test_a_row_inside_the_grace_period_is_not_yet_outstanding(parties):
    await _row(parties, ended_hours_ago=1)

    page = await _queue(parties)

    assert page["items"] == []


async def test_the_boundary_is_exclusive_at_the_cutoff_instant(parties):
    """`$lt`, so a row ending exactly at the cutoff is not yet overdue.

    Asserted from both sides: a boundary tested from one side only is a
    boundary half tested.

    ONE MILLISECOND, NOT ONE MICROSECOND, and `now` is pinned to a whole
    millisecond. BSON dates carry milliseconds, so a microsecond offset is not
    representable — it truncates onto the cutoff itself, and the "just before"
    row silently becomes the "exactly at" row. The first version of this test
    did that and failed for a reason that had nothing to do with `$lt`.
    """
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cutoff = outcomes.cutoff_for(now)

    at_cutoff = await _row(parties, end_at=cutoff)
    just_before = await _row(parties, end_at=cutoff - timedelta(milliseconds=1))
    just_after = await _row(parties, end_at=cutoff + timedelta(milliseconds=1))

    listed = _ids(await _queue(parties, now=now))

    assert just_before in listed
    assert at_cutoff not in listed, "a row exactly at the cutoff was overdue"
    assert just_after not in listed


async def test_the_grace_period_can_be_varied_by_the_caller(parties):
    """The rule lives in the service, not in the query, so a caller can ask a
    different question without a different repository method."""
    appt = await _row(parties, ended_hours_ago=1)

    assert _ids(await _queue(parties)) == []
    assert _ids(await _queue(parties, grace=timedelta(minutes=30))) == [appt]


# ── 3. Ownership ─────────────────────────────────────────────────────────────

async def test_a_lawyer_sees_only_their_own(parties):
    mine = await _row(parties, ended_hours_ago=5)
    theirs = await _row(parties, ended_hours_ago=5,
                        lawyer_id=parties["lawyer2_id"])

    assert _ids(await _queue(parties)) == [mine]
    assert _ids(await _queue(parties, lawyer_id=parties["lawyer2_id"])) == [theirs]


async def test_ownership_is_a_query_term_not_a_later_check(parties):
    """A filter applied after the read is a filter that can be forgotten, and
    this is a list of other people's consultations. Asserted structurally so
    the guarantee cannot be quietly moved out of the query."""
    from app.repositories.appointment_repo import AppointmentRepository

    seen: dict = {}
    real = AppointmentRepository.find_outstanding_outcomes

    async def _capture(self, **kwargs):
        seen.update(kwargs)
        return await real(self, **kwargs)

    AppointmentRepository.find_outstanding_outcomes = _capture
    try:
        await _queue(parties)
    finally:
        AppointmentRepository.find_outstanding_outcomes = real

    assert seen["lawyer_id"] == parties["lawyer_id"]


async def test_an_unknown_lawyer_sees_an_empty_queue(parties):
    await _row(parties, ended_hours_ago=5)

    page = await _queue(parties, lawyer_id="OC-NOBODY")

    assert page["items"] == []


# ── 4. Ordering and keyset pagination ────────────────────────────────────────

async def test_the_oldest_unreported_consultation_comes_first(parties):
    recent = await _row(parties, ended_hours_ago=3)
    oldest = await _row(parties, ended_hours_ago=200)
    middle = await _row(parties, ended_hours_ago=50)

    assert _ids(await _queue(parties)) == [oldest, middle, recent]


async def test_equal_end_times_are_ordered_by_id(parties):
    """`end_at` alone is not unique — two consultations ending at the same
    instant is ordinary on a half-hour grid, not exotic — and a cursor on a
    non-unique key repeats or skips rows at every page boundary."""
    same = datetime.now(timezone.utc) - timedelta(hours=6)
    b = await _row(parties, end_at=same, appt_id="OC-SAME-B")
    a = await _row(parties, end_at=same, appt_id="OC-SAME-A")
    c = await _row(parties, end_at=same, appt_id="OC-SAME-C")

    assert _ids(await _queue(parties)) == [a, b, c]


async def test_the_query_sorts_on_both_keys(parties):
    """THE SORT IS PINNED STRUCTURALLY, and that is not belt-and-braces.

    Asserting the resulting ORDER cannot catch a missing `_id` tiebreak here:
    `appointment_confirmed_outcome` carries `_id` as its third key, so an index
    scan returns rows in `_id` order within an `end_at` group whether or not
    the query asked for it. The behavioural test passes either way — verified
    by removing the tiebreak and watching nothing fail.

    What that means is that the ordering the cursor depends on would be resting
    on the plan the optimiser happened to choose. A different plan — a
    collection scan on a database where the index has not been built, which is
    every deployment today — has no such guarantee, and the keyset would then
    repeat or skip rows at page boundaries.

    So the sort is asserted where it is actually specified.
    """
    from app.repositories.appointment_repo import AppointmentRepository

    seen: list = []
    repo = AppointmentRepository()
    real_col = repo.col

    class _RecordingCursor:
        def __init__(self, inner):
            self._inner = inner

        def sort(self, spec, *a, **kw):
            seen.append(spec)
            return _RecordingCursor(self._inner.sort(spec, *a, **kw))

        def limit(self, *a, **kw):
            return _RecordingCursor(self._inner.limit(*a, **kw))

        async def to_list(self, *a, **kw):
            return await self._inner.to_list(*a, **kw)

    class _RecordingCol:
        def find(self, *a, **kw):
            return _RecordingCursor(real_col.find(*a, **kw))

    await _row(parties, ended_hours_ago=5)
    original = AppointmentRepository.col
    AppointmentRepository.col = property(lambda self: _RecordingCol())
    try:
        await _queue(parties)
    finally:
        AppointmentRepository.col = original

    assert seen == [[("end_at", 1), ("_id", 1)]], (
        f"the queue did not sort on the full keyset key: {seen}")


async def test_paging_walks_every_row_exactly_once(parties):
    made = [await _row(parties, ended_hours_ago=100 - i) for i in range(7)]

    walked, cursor, pages = [], None, 0
    while True:
        page = await _queue(parties, page_size=2,
                            **(cursor or {}))
        walked += _ids(page)
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert pages < 20, "the cursor did not advance"

    assert walked == sorted(made, key=lambda _id: made.index(_id))
    assert len(walked) == len(set(walked)) == 7
    assert pages == 4


async def test_paging_across_equal_end_times_skips_nothing(parties):
    """The page boundary falls INSIDE a group sharing one `end_at`, which is
    where a cursor on `end_at` alone loses rows or repeats them."""
    same = datetime.now(timezone.utc) - timedelta(hours=6)
    made = [await _row(parties, end_at=same, appt_id=f"OC-EQ-{i}")
            for i in range(5)]

    first = await _queue(parties, page_size=2)
    second = await _queue(parties, page_size=2, **first["next_cursor"])
    third = await _queue(parties, page_size=2, **second["next_cursor"])

    walked = _ids(first) + _ids(second) + _ids(third)
    assert walked == sorted(made)
    assert len(set(walked)) == 5
    assert third["next_cursor"] is None


async def test_a_row_leaving_the_queue_does_not_skip_the_row_behind_it(parties):
    """THE REASON THIS IS KEYSET AND NOT SKIP.

    Rows leave this queue — that is the queue working. With `skip`, every
    departure shifts the rows behind it up by one and the next page steps over
    a row nobody has seen. The rows it would hide are precisely the unreported
    consultations the queue exists to surface.

    Here the lawyer records an outcome on a row from the FIRST page, between
    the two reads, and the second page must still be complete.
    """
    from app.db.collections import get_appointments_col

    made = [await _row(parties, ended_hours_ago=100 - i) for i in range(6)]

    first = await _queue(parties, page_size=3)
    assert _ids(first) == made[:3]

    # The lawyer completes one of the rows already seen.
    await get_appointments_col().update_one(
        {"_id": made[0]}, {"$set": {"status": "completed"}})

    second = await _queue(parties, page_size=3, **first["next_cursor"])

    assert _ids(second) == made[3:], (
        "a row was skipped after an earlier one left the queue")


async def test_the_cursor_is_the_whole_sort_key(parties):
    await _row(parties, ended_hours_ago=10)
    await _row(parties, ended_hours_ago=9)

    page = await _queue(parties, page_size=1)

    assert set(page["next_cursor"]) == {"after_end_at", "after_id", "cutoff"}
    assert isinstance(page["next_cursor"]["after_end_at"], datetime)


async def test_the_last_page_reports_no_cursor(parties):
    await _row(parties, ended_hours_ago=5)

    page = await _queue(parties, page_size=50)

    assert page["next_cursor"] is None


async def test_an_empty_queue_reports_no_cursor(parties):
    page = await _queue(parties)

    assert page["items"] == []
    assert page["next_cursor"] is None


async def test_half_a_cursor_is_refused(parties):
    """NOT A FRESH START — AN ERROR.

    Returning page one for a broken cursor is the worst option available: the
    caller believes it is continuing a scan, re-reads rows it has already
    handled, and never reaches the ones it was walking towards. A caller that
    has lost half its cursor has lost its position and needs to be told.
    """
    made = [await _row(parties, ended_hours_ago=10 - i) for i in range(3)]

    with pytest.raises(AppValidationError):
        await _queue(parties,
                     after_end_at=datetime.now(timezone.utc) - timedelta(hours=9))
    with pytest.raises(AppValidationError):
        await _queue(parties, after_id=made[0])


async def test_continuing_without_the_pinned_cutoff_is_refused(parties):
    """The cutoff is part of the cursor. A continuation without it would be
    rebased onto a later instant, so the scan would cover a moving edge and
    could not be said to have covered anything in particular."""
    await _row(parties, ended_hours_ago=10)
    await _row(parties, ended_hours_ago=9)

    page = await _queue(parties, page_size=1)
    partial = dict(page["next_cursor"])
    partial.pop("cutoff")

    with pytest.raises(AppValidationError):
        await _queue(parties, **partial)


async def test_the_cutoff_stays_fixed_across_a_scan(parties):
    """A consultation becoming due mid-scan must not join the walk. Otherwise
    a page boundary moves under the cursor and the frontier never settles."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    first_two = [await _row(parties, ended_hours_ago=10 - i) for i in range(2)]

    # Not yet due at `now`: it ended an hour ago, so it becomes due in an
    # hour's time. It must not appear in a scan pinned to `now`, however long
    # that scan takes to walk.
    await _row(parties, end_at=now - timedelta(hours=1))

    page = await _queue(parties, page_size=1, now=now)
    assert page["cutoff"] == outcomes.cutoff_for(now)
    assert _ids(page) == [first_two[0]]

    # Time passes between the pages — enough that the third row is now due.
    # The cursor carries the cutoff, so the scan stays the scan it started as.
    later = now + timedelta(hours=2)
    second = await _queue(parties, page_size=1, now=later,
                          **page["next_cursor"])

    assert _ids(second) == [first_two[1]]
    assert second["cutoff"] == page["cutoff"], "the scan was rebased"
    assert second["next_cursor"] is None, (
        "a row that became due mid-scan joined the walk")

    # And a fresh scan at the later time does see it, so the exclusion above
    # was the pinning rather than the row being invisible.
    fresh = await _queue(parties, page_size=10, now=later)
    assert len(fresh["items"]) == 3


@pytest.mark.parametrize("bad", [0, -1, 201, 1.5, "10", None, True])
async def test_an_unusable_page_size_is_refused(parties, bad):
    """`True` is in the list deliberately: it is an int as far as `isinstance`
    is concerned, and `page_size=True` would otherwise mean one row."""
    with pytest.raises(AppValidationError):
        await _queue(parties, page_size=bad)


# ── 5. The queue writes nothing ──────────────────────────────────────────────

async def test_listing_changes_no_appointment(parties):
    from app.db.collections import get_appointments_col

    appt = await _row(parties, ended_hours_ago=5)
    before = await get_appointments_col().find_one({"_id": appt})

    await _queue(parties)

    assert await get_appointments_col().find_one({"_id": appt}) == before


def test_the_queue_and_survey_call_no_writer():
    """Scoped to the READING half, deliberately.

    Step 4 added a nudge, so the module as a whole is no longer write-free — it
    records progress markers. The queue and the survey must stay so: a lawyer
    opening a list, or an operator asking how big the backlog is, must not
    change anything by looking.
    """
    import inspect

    for fn in (outcomes.outstanding_outcomes,
               outcomes.survey_outstanding_outcomes,
               outcomes.cutoff_for):
        source = inspect.getsource(fn)
        for writer in ("update_one", "update_many", "insert_one", "delete_one",
                       "find_one_and_update", "compare_and_set", "_transition",
                       "create_notification", "mark_outcome_notice_sent",
                       "record_outcome_notice_attempt"):
            assert writer not in source, f"{fn.__name__} calls {writer}"


def test_there_is_no_way_to_ask_it_to_act():
    import inspect

    for fn in (outcomes.outstanding_outcomes,
               outcomes.survey_outstanding_outcomes):
        params = inspect.signature(fn).parameters
        for forbidden in ("apply", "complete", "notify", "dry_run"):
            assert forbidden not in params, f"{fn.__name__} takes {forbidden}"


# ── 6. The survey ────────────────────────────────────────────────────────────

async def test_the_survey_counts_each_horizon(parties):
    await _row(parties, ended_hours_ago=3)        # over 2h only
    await _row(parties, ended_hours_ago=30)       # over 2h and 24h
    await _row(parties, ended_hours_ago=24 * 9)   # over all three

    report = await outcomes.survey_outstanding_outcomes()

    assert report["over_2h"] == 3
    assert report["over_24h"] == 2
    assert report["over_7d"] == 1


async def test_the_survey_counts_are_cumulative_and_say_so(parties):
    """`over_7d` is a subset of `over_24h`, not a bucket beside it. Reporting
    them without saying so invites adding them up."""
    await _row(parties, ended_hours_ago=24 * 9)

    report = await outcomes.survey_outstanding_outcomes()

    assert report["cumulative"] is True
    assert report["over_2h"] == report["over_24h"] == report["over_7d"] == 1


async def test_the_survey_exposes_no_identities(parties):
    """Three integers and the instant they were measured at. The question is
    "how big, and how old" — answering it does not require naming anybody's
    consultation, or which lawyer let it sit."""
    appt = await _row(parties, ended_hours_ago=30,
                      lawyer_notes="INTERNAL: client was difficult")

    report = await outcomes.survey_outstanding_outcomes()

    assert set(report) == {"measured_at", "cumulative",
                           "over_2h", "over_24h", "over_7d"}
    blob = repr(report)
    for secret in (appt, parties["lawyer_id"], parties["client_id"],
                   "INTERNAL", "difficult", "Adv One", "Client One"):
        assert secret not in blob, f"the survey leaked {secret!r}"


async def test_the_survey_spans_every_lawyer(parties):
    """Unlike the queue. The queue is one lawyer's work; the survey is the size
    of the problem, which is not any one lawyer's."""
    await _row(parties, ended_hours_ago=30)
    await _row(parties, ended_hours_ago=30, lawyer_id=parties["lawyer2_id"])

    report = await outcomes.survey_outstanding_outcomes()

    assert report["over_24h"] == 2


async def test_the_survey_ignores_recorded_outcomes(parties):
    await _row(parties, ended_hours_ago=30, status="completed")
    await _row(parties, ended_hours_ago=30, status="no_show")
    await _row(parties, ended_hours_ago=30, status="cancelled")

    report = await outcomes.survey_outstanding_outcomes()

    assert report["over_2h"] == 0


async def test_the_survey_writes_nothing(parties):
    """Proven by comparing the whole collection, not by reading the source."""
    from app.db.collections import get_appointments_col

    await _row(parties, ended_hours_ago=30)
    await _row(parties, ended_hours_ago=3)
    col = get_appointments_col()
    before = await col.find().sort("_id", 1).to_list(length=500)

    await outcomes.survey_outstanding_outcomes()

    assert await col.find().sort("_id", 1).to_list(length=500) == before


async def test_the_survey_counts_rather_than_fetching(parties):
    """A survey that pulled documents back to count them would read the very
    records it is careful not to report."""
    from app.repositories.appointment_repo import AppointmentRepository

    fetched = []
    real_find = AppointmentRepository.find_many

    async def _watch(self, *a, **kw):
        fetched.append(kw)
        return await real_find(self, *a, **kw)

    AppointmentRepository.find_many = _watch
    try:
        await outcomes.survey_outstanding_outcomes()
    finally:
        AppointmentRepository.find_many = real_find

    assert fetched == []


# ── 7. The index it needs, and what its absence costs ────────────────────────

def test_the_queues_index_is_declared():
    from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS
    from app.db.v2_index_spec import QUERY

    spec = next(s for s in APPOINTMENT_INDEX_REQUIREMENTS
                if s.name == "appointment_confirmed_outcome")

    assert spec.kind == QUERY
    assert [k[0] for k in spec.keys] == ["status", "end_at", "_id"], (
        "equality, then the range key, then the keyset tiebreak")
    assert spec.unique is False
    assert spec.partial_filter == {"status": AppointmentStatus.CONFIRMED.value}


async def test_the_queues_query_actually_uses_that_index(parties):
    """The declared index and the query the service issues are written in two
    files, and nothing but this checks that they agree."""
    from app.db.collections import get_appointments_col

    plan = await get_appointments_col().find({
        "lawyer_id": parties["lawyer_id"],
        "status": AppointmentStatus.CONFIRMED.value,
        "end_at": {"$lt": datetime.now(timezone.utc)},
    }).sort([("end_at", 1), ("_id", 1)]).explain()

    flat = str(plan["queryPlanner"]["winningPlan"])
    assert "COLLSCAN" not in flat, f"the queue's read is a collection scan: {flat}"


async def test_a_missing_outcome_index_does_not_stop_the_service(parties, monkeypatch):
    """SLOWNESS IS NOT INCORRECTNESS.

    `assert_appointment_booking_ready` refuses to start the service when
    `safe_to_activate` is false, so anything inside that gate is a reason to
    take booking down. A missing performance index must be reported, not be
    grounds for refusing every booking.
    """
    from app.db import indexes as indexes_module
    from app.db.appointment_slot_preflight import preflight
    from app.db.v2_index_spec import QUERY, IndexProblem

    async def _missing():
        return [IndexProblem("missing", "appointments",
                             "appointment_confirmed_outcome",
                             "index missing", kind=QUERY)]

    monkeypatch.setattr(
        indexes_module, "validate_appointment_indexes", _missing)
    result = await preflight()

    assert result["gates"]["indexes_valid"] is True
    assert result["safe_to_activate"] is True
    assert result["indexes_ready"] is False, "it is missing and must be said"
    assert [p["name"] for p in result["query_index_problems"]] == [
        "appointment_confirmed_outcome"]


async def test_a_missing_correctness_index_still_stops_the_service(parties, monkeypatch):
    """The other direction, so the reporting above cannot have opened the gate."""
    from app.db import indexes as indexes_module
    from app.db.appointment_slot_preflight import preflight
    from app.db.v2_index_spec import CORRECTNESS, IndexProblem

    async def _missing():
        return [IndexProblem("missing", "appointments",
                             "uniq_appointment_client_slot",
                             "index missing", kind=CORRECTNESS)]

    monkeypatch.setattr(
        indexes_module, "validate_appointment_indexes", _missing)
    result = await preflight()

    assert result["gates"]["indexes_valid"] is False
    assert result["safe_to_activate"] is False


# ── 8. Nothing has been switched on ──────────────────────────────────────────

def test_no_scheduler_runs_this():
    """Steps 4 and 5 — notifying anyone, and showing this to a lawyer — are
    separate decisions that need the survey's numbers first."""
    from pathlib import Path

    import app.main as main

    source = Path(main.__file__).read_text(encoding="utf-8")
    assert "appointment_outcomes" not in source, (
        "the outcome queue has been wired into startup; that is a later, "
        "deliberate step")


def test_nothing_completes_an_appointment_automatically():
    """Completion is a claim that a consultation took place, and only a person
    who was there can make it. Inferring it from a clock would write a fact
    nobody asserted into the record of a legal engagement — and would hand out
    review rights, which `exists_completed` gates, on a guess."""
    import inspect

    source = inspect.getsource(outcomes)

    # THE ONLY WRITERS THIS MODULE MAY REACH are the two notice markers. Both
    # record whether a NUDGE was sent; neither touches `status`. Naming them
    # exhaustively is what makes a status write added later fail here.
    import re

    called = set(re.findall(r"appt_repo\.(\w+)", source))
    writers = {name for name in called
               if name.startswith(("mark_", "record_", "expire_", "update",
                                   "insert", "delete"))}
    assert writers == {"mark_outcome_notice_sent",
                       "record_outcome_notice_attempt"}, writers

    # `AppointmentStatus` is READ, to check a row is still confirmed. It must
    # never be written, and the terminal outcomes must not appear at all.
    assert "AppointmentStatus.COMPLETED" not in source
    assert "AppointmentStatus.NO_SHOW" not in source
    assert '"status":' not in source, "the module assigns a status"


# ── 9. Step 4: the nudge, report-only by default ─────────────────────────────
#
# Nothing in this section is switched on. The point of the section is that it
# stays that way until somebody decides otherwise, and that when it is turned
# on it cannot do more than a nudge.

ACTIVATION = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _notify(parties, **kw):
    kw.setdefault("activated_at", ACTIVATION)
    return await outcomes.notify_outstanding_outcomes(**kw)


async def _notices(appt_id=None, user_id=None):
    from app.db.collections import get_notifications_col

    query = {}
    if appt_id:
        query["payload.appointment_id"] = appt_id
    if user_id:
        query["user_id"] = user_id
    return await get_notifications_col().find(query).to_list(length=100)


async def _clear_notices():
    from app.db.collections import get_notifications_col
    await get_notifications_col().delete_many(
        {"type": NotificationType.APPOINTMENT_OUTCOME_NUDGE.value})


# --- report-only is the default --------------------------------------------

async def test_a_bare_run_sends_nothing_and_writes_nothing(parties):
    """THE FAIL-CLOSED REGRESSION.

    Report-only is what an operator, a console session, or a half-finished
    wiring change gets by default. This function puts messages in front of real
    people; the difference between looking and sending cannot be a keyword
    somebody remembered.
    """
    from app.db.collections import get_appointments_col

    appt = await _row(parties, ended_hours_ago=5)
    before = await get_appointments_col().find_one({"_id": appt})

    report = await _notify(parties)

    assert report["applied"] is False
    assert report["sent"] == 1, "a report-only run must still say what it would do"
    assert await _notices(appt) == []
    assert await get_appointments_col().find_one({"_id": appt}) == before


def test_sending_is_keyword_only_and_off_by_default():
    import inspect

    sig = inspect.signature(outcomes.notify_outstanding_outcomes)
    assert sig.parameters["apply"].default is False
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY
               for p in sig.parameters.values())


async def test_activation_has_no_default(parties):
    """Without it a first run would notify about every unreported consultation
    in the product's history, and the blast radius would be whatever the clock
    happened to say."""
    with pytest.raises(TypeError):
        await outcomes.notify_outstanding_outcomes()


@pytest.mark.parametrize("bad", [None, "2026-01-01", 0])
async def test_an_unusable_activation_time_is_refused(parties, bad):
    with pytest.raises(AppValidationError):
        await outcomes.notify_outstanding_outcomes(activated_at=bad)


# --- what makes a consultation eligible ------------------------------------

async def test_a_finished_confirmed_consultation_is_nudged(parties):
    appt = await _row(parties, ended_hours_ago=5)

    report = await _notify(parties, apply=True)

    assert report["sent"] == 1
    notices = await _notices(appt)
    assert [n["user_id"] for n in notices] == [parties["lawyer_id"]]


async def test_the_nudge_has_its_own_notification_type(parties):
    """NOT `appointment_reminder`, which stays RESERVED for the T-24h / T-1h
    reminders before a consultation.

    The two say opposite things — one is "this is about to happen", the other
    "this already happened and nobody recorded what came of it". Sharing a type
    would make them indistinguishable for ever once rows carrying it exist, and
    a lawyer muting reminders would thereby mute their own outstanding work.
    """
    appt = await _row(parties, ended_hours_ago=5)

    await _notify(parties, apply=True)

    notice = (await _notices(appt))[0]
    assert notice["type"] == NotificationType.APPOINTMENT_OUTCOME_NUDGE.value
    assert notice["type"] == "appointment_outcome_nudge"
    assert notice["type"] != NotificationType.APPOINTMENT_REMINDER.value


def test_the_reminder_type_is_still_unused():
    """Reserved means reserved. If a reminder is built later it takes this
    type; until then nothing emits it, and this test says so out loud rather
    than leaving a reader to grep for it."""
    from pathlib import Path

    import app.services.appointment_outcomes as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "APPOINTMENT_REMINDER" not in source


async def test_the_new_type_still_deduplicates(parties):
    """Changing the type must not change the identity. Dedup is on
    `logical_event_id` — globally unique, and independent of type — so a
    second run still produces one notice."""
    appt = await _row(parties, ended_hours_ago=5)

    first = await _notify(parties, apply=True)
    second = await _notify(parties, apply=True)

    assert first["sent"] == 1
    assert second["sent"] == 0
    notices = await _notices(appt)
    assert len(notices) == 1
    assert notices[0]["type"] == "appointment_outcome_nudge"
    assert notices[0]["logical_event_id"] == (
        f"appointment:{appt}:outcome_due:{parties['lawyer_id']}")


async def test_two_workers_still_produce_one_notice_of_the_new_type(parties):
    import asyncio

    appt = await _row(parties, ended_hours_ago=5)

    await asyncio.gather(
        _notify(parties, apply=True), _notify(parties, apply=True))

    notices = await _notices(appt)
    assert len(notices) == 1
    assert notices[0]["type"] == "appointment_outcome_nudge"


async def test_the_client_is_never_told(parties):
    """A deliberate omission. Telling a client their lawyer has filed nothing
    invites them to act on a process they have no part in, and the dispute
    route that would give them somewhere to go does not exist yet."""
    appt = await _row(parties, ended_hours_ago=5)

    await _notify(parties, apply=True)

    assert await _notices(appt, user_id=parties["client_id"]) == []


async def test_a_consultation_inside_the_grace_period_is_not_nudged(parties):
    await _row(parties, ended_hours_ago=1)

    report = await _notify(parties, apply=True)

    assert report["sent"] == 0


@pytest.mark.parametrize("status", ["completed", "no_show", "cancelled",
                                    "expired", "pending"])
async def test_only_confirmed_consultations_are_nudged(parties, status):
    await _row(parties, ended_hours_ago=5, status=status)

    report = await _notify(parties, apply=True)

    assert report["sent"] == 0


# --- the activation boundary excludes history ------------------------------

async def test_the_historical_backlog_is_excluded(parties):
    """THE REASON ACTIVATION EXISTS.

    Every unreported consultation since the product started is sitting in the
    database. A first run that notified about all of them would be an incident,
    and no cap makes that acceptable — the rows simply are not this feature's
    business until somebody says so.
    """
    old = await _row(parties, ended_hours_ago=24 * 200)
    recent = await _row(parties, ended_hours_ago=5)

    report = await _notify(parties, apply=True,
                           activated_at=datetime.now(timezone.utc) - timedelta(days=1))

    assert report["sent"] == 1
    assert await _notices(old) == []
    assert await _notices(recent) != []


async def test_the_activation_boundary_is_about_when_a_row_became_due(parties):
    """Due is `end_at + grace`, not `end_at`. A consultation that ended just
    before activation but became DUE just after is inside the boundary, and
    getting that wrong by the grace period would silently drop a band of rows.
    """
    now = datetime.now(timezone.utc).replace(microsecond=0)
    activation = now - timedelta(hours=1)

    # Ended 2h30 ago: due 30 minutes ago, which is after activation.
    just_inside = await _row(parties, end_at=now - timedelta(hours=2, minutes=30))
    # Ended 4h ago: due 2h ago, before activation.
    just_outside = await _row(parties, end_at=now - timedelta(hours=4))

    report = await _notify(parties, apply=True, now=now, activated_at=activation)

    assert report["sent"] == 1
    assert await _notices(just_inside) != []
    assert await _notices(just_outside) == []


# --- one notice, ever ------------------------------------------------------

async def test_a_second_run_does_not_nudge_twice(parties):
    appt = await _row(parties, ended_hours_ago=5)

    first = await _notify(parties, apply=True)
    second = await _notify(parties, apply=True)

    assert first["sent"] == 1
    assert second["sent"] == 0, "the lawyer was nudged about the same row twice"
    assert len(await _notices(appt)) == 1


async def test_two_workers_racing_produce_one_notice(parties):
    """DUPLICATE WORKERS. The progress marker is a local optimisation; the real
    dedup is `uniq_notification_logical_event`, which is unique GLOBALLY. Two
    runs that both read the row before either marked it must still produce one
    notice."""
    import asyncio

    appt = await _row(parties, ended_hours_ago=5)

    results = await asyncio.gather(
        _notify(parties, apply=True), _notify(parties, apply=True))

    assert sum(r["sent"] for r in results) >= 1
    assert len(await _notices(appt)) == 1, "the same lawyer was told twice"


async def test_the_event_id_names_the_recipient(parties):
    appt = await _row(parties, ended_hours_ago=5)

    await _notify(parties, apply=True)

    notice = (await _notices(appt))[0]
    assert notice["logical_event_id"] == (
        f"appointment:{appt}:outcome_due:{parties['lawyer_id']}")


# --- races against the lawyer actually doing the work ----------------------

async def test_a_consultation_completed_before_the_send_is_not_nudged(parties):
    """The row was eligible when it was read and is not when it is sent. The
    re-check in code is what catches it — chasing somebody for work they have
    just done is exactly the failure a nudge must not produce."""
    from app.db.collections import get_appointments_col

    appt = await _row(parties, ended_hours_ago=5)

    real = outcomes._is_eligible
    seen: list = []

    def _complete_then_check(row, cutoff, floor):
        if not seen:
            seen.append(row["_id"])
            import asyncio
            asyncio.get_event_loop()
        return real(row, cutoff, floor)

    # Simulate the completion landing between the read and the check by
    # rewriting the row the check will see.
    await get_appointments_col().update_one(
        {"_id": appt}, {"$set": {"status": "completed"}})
    stale = {"_id": appt, "lawyer_id": parties["lawyer_id"],
             "status": "completed",
             "end_at": datetime.now(timezone.utc) - timedelta(hours=5)}

    assert outcomes._is_eligible(
        stale, outcomes.cutoff_for(), ACTIVATION) is False

    report = await _notify(parties, apply=True)
    assert report["sent"] == 0
    assert await _notices(appt) == []


async def test_a_row_that_changed_after_it_was_read_is_not_nudged(parties):
    """THE IN-CODE RE-CHECK, tested where it can actually be observed.

    The query already filters on status and the time window, so removing the
    re-check changes nothing that goes through the normal path — verified by
    removing it and watching every test still pass. It only bites on a row that
    was eligible when READ and is not when it is about to be SENT, which is
    precisely the lawyer finishing the work while the batch is in flight.

    So the row is handed to the run directly, in the state the read would have
    returned a moment before the lawyer acted. Chasing somebody for work they
    have just done is the failure a nudge must never produce.
    """
    from app.db.collections import get_appointments_col
    from app.repositories.appointment_repo import AppointmentRepository

    appt = await _row(parties, ended_hours_ago=5)
    stale = await get_appointments_col().find_one({"_id": appt})

    # The lawyer records the outcome, after the read and before the send.
    await get_appointments_col().update_one(
        {"_id": appt}, {"$set": {"status": "completed"}})

    real = AppointmentRepository.find_outcome_notice_candidates

    async def _hand_back_the_stale_row(self, **kwargs):
        return [] if kwargs.get("retries") else [stale]

    AppointmentRepository.find_outcome_notice_candidates = _hand_back_the_stale_row
    try:
        report = await _notify(parties, apply=True)
    finally:
        AppointmentRepository.find_outcome_notice_candidates = real

    assert report["scanned"] == 1, "precondition: the stale row was examined"
    assert report["eligible"] == 1, (
        "the row was eligible WHEN READ — that is the premise of the race")
    assert report["stale"] == 1, "the re-read did not catch the completion"
    assert report["sent"] == 0
    assert await _notices(appt) == [], (
        "the lawyer was chased for work they had already done")


async def test_a_row_outside_the_window_is_refused_even_if_handed_over(parties):
    """The other half of the same guard: a row whose time no longer qualifies.
    A widened query must not become a wider policy."""
    from app.db.collections import get_appointments_col
    from app.repositories.appointment_repo import AppointmentRepository

    appt = await _row(parties, ended_hours_ago=1)   # inside the grace period
    row = await get_appointments_col().find_one({"_id": appt})

    real = AppointmentRepository.find_outcome_notice_candidates

    async def _hand_back(self, **kwargs):
        return [] if kwargs.get("retries") else [row]

    AppointmentRepository.find_outcome_notice_candidates = _hand_back
    try:
        report = await _notify(parties, apply=True)
    finally:
        AppointmentRepository.find_outcome_notice_candidates = real

    assert report["scanned"] == 1
    assert report["eligible"] == 0
    assert await _notices(appt) == []


async def test_a_cancelled_consultation_is_not_nudged(parties):
    appt = await _row(parties, ended_hours_ago=5, status="cancelled")

    report = await _notify(parties, apply=True)

    assert report["sent"] == 0
    assert await _notices(appt) == []


async def test_recording_an_outcome_stops_future_nudges(parties):
    from app.db.collections import get_appointments_col

    appt = await _row(parties, ended_hours_ago=5)
    await get_appointments_col().update_one(
        {"_id": appt}, {"$set": {"status": "no_show"}})

    report = await _notify(parties, apply=True)

    assert report["sent"] == 0


# --- failure is retryable --------------------------------------------------

async def test_a_failed_send_is_retried_on_the_next_run(parties, monkeypatch):
    """A FAILURE MUST NOT LOOK LIKE A DELIVERY.

    The progress marker is written only after a successful send, so a row whose
    notice failed comes back. Marking first would permanently silence a
    consultation nobody was ever told about.
    """
    from app.services import notification_service

    appt = await _row(parties, ended_hours_ago=5)

    async def _boom(**kwargs):
        raise RuntimeError("notification backend down")

    monkeypatch.setattr(notification_service, "create_notification", _boom)
    failed = await _notify(parties, apply=True)

    assert failed["sent"] == 0
    assert failed["failed"] == 1

    monkeypatch.undo()

    # NOT IMMEDIATELY. A failed notice now waits before the next attempt, so
    # an unreachable recipient is not tried on every run for ever. The run that
    # follows straight away must therefore find nothing.
    assert (await _notify(parties, apply=True))["sent"] == 0

    later = datetime.now(timezone.utc) + outcomes.RETRY_BACKOFF[0]
    recovered = await _notify(parties, apply=True, now=later)

    assert recovered["sent"] == 1
    assert recovered["retry_sent"] == 1, "a retry spent the fresh budget"
    assert len(await _notices(appt)) == 1


async def test_a_failed_send_leaves_no_progress_marker(parties, monkeypatch):
    from app.db.collections import get_appointments_col
    from app.services import notification_service

    appt = await _row(parties, ended_hours_ago=5)

    async def _boom(**kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(notification_service, "create_notification", _boom)
    await _notify(parties, apply=True)

    row = await get_appointments_col().find_one({"_id": appt})
    assert "outcome_notice_sent_at" not in row
    assert row["outcome_notice_attempts"] == 1


async def test_a_failure_never_changes_the_appointments_status(parties, monkeypatch):
    from app.db.collections import get_appointments_col
    from app.services import notification_service

    appt = await _row(parties, ended_hours_ago=5)

    async def _boom(**kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(notification_service, "create_notification", _boom)
    await _notify(parties, apply=True)

    row = await get_appointments_col().find_one({"_id": appt})
    assert row["status"] == "confirmed"


# --- old rows cannot starve new ones ---------------------------------------

async def test_repeated_failures_do_not_block_fresh_rows(parties, monkeypatch):
    """THE STARVATION PROPERTY.

    An unmarked failure stays at the front of an `end_at`-ordered queue for
    ever. With one queue, a handful of permanently failing rows would consume
    every run's budget and a consultation that finished this morning would
    never be reached. Fresh rows and retries are therefore drained separately.
    """
    from app.services import notification_service

    old_failures = [await _row(parties, ended_hours_ago=100 - i)
                    for i in range(3)]

    async def _boom(**kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(notification_service, "create_notification", _boom)
    await _notify(parties, apply=True)
    monkeypatch.undo()

    fresh = await _row(parties, ended_hours_ago=3)

    report = await _notify(parties, apply=True, limit=1)

    assert report["sent"] == 1
    assert await _notices(fresh) != [], (
        "a new consultation waited behind old failures")


async def test_notified_rows_do_not_consume_a_later_runs_budget(parties):
    done = [await _row(parties, ended_hours_ago=100 - i) for i in range(3)]
    first = await _notify(parties, apply=True)
    assert first["sent"] == 3

    fresh = await _row(parties, ended_hours_ago=3)
    second = await _notify(parties, apply=True, limit=1)

    assert second["sent"] == 1
    assert await _notices(fresh) != []
    for appt in done:
        assert len(await _notices(appt)) == 1


# --- the cap ---------------------------------------------------------------

async def test_a_run_sends_no_more_than_its_cap(parties):
    for i in range(5):
        await _row(parties, ended_hours_ago=50 - i)

    # `limit` is the WHOLE run's cap, and part of it is reserved for retries.
    # With nothing to retry, a run sends only its fresh share — deliberately:
    # the reserve exists for the runs that have plenty of fresh work, which is
    # exactly this one.
    report = await _notify(parties, apply=True, limit=4)

    assert report["sent"] == 3, report
    assert report["fresh_sent"] == 3
    assert report["retry_sent"] == 0
    # Scoped to THIS fixture's lawyer. An unscoped count passes alone and fails
    # in the suite, where other tests have written notifications of their own —
    # which is how these two tests failed for the first time in a full run.
    assert len(await _notices(user_id=parties["lawyer_id"])) == 3


async def test_the_default_cap_is_twenty_five(parties):
    assert outcomes.NOTICE_CAP == 25


@pytest.mark.parametrize("bad", [0, -1, 26, 1.5, "5", None, True])
async def test_an_unusable_cap_is_refused(parties, bad):
    with pytest.raises(AppValidationError):
        await _notify(parties, apply=True, limit=bad)


async def test_the_remainder_is_picked_up_next_run(parties):
    for i in range(4):
        await _row(parties, ended_hours_ago=50 - i)

    first = await _notify(parties, apply=True, limit=3)
    second = await _notify(parties, apply=True, limit=3)

    assert first["sent"] == second["sent"] == 2, (first, second)
    assert len(await _notices(user_id=parties["lawyer_id"])) == 4


# --- it does not do more than nudge ----------------------------------------

async def test_no_appointment_is_ever_completed(parties):
    """Completion is a claim that a consultation took place, and it grants the
    client's right to review the lawyer through `exists_completed`. A clock
    must not grant it."""
    from app.db.collections import get_appointments_col

    appt = await _row(parties, ended_hours_ago=5)

    await _notify(parties, apply=True)

    row = await get_appointments_col().find_one({"_id": appt})
    assert row["status"] == "confirmed"


async def test_no_review_right_is_granted(parties):
    from app.repositories.appointment_repo import AppointmentRepository

    await _row(parties, ended_hours_ago=5)
    await _notify(parties, apply=True)

    assert await AppointmentRepository().exists_completed(
        parties["client_id"], parties["lawyer_id"]) is False


async def test_the_progress_markers_never_reach_a_response(parties):
    """`_sanitize` is an allowlist, so a field added to the collection is
    withheld unless someone names it. Asserted rather than assumed."""
    from app.db.collections import get_appointments_col
    from app.services.appointment_service import _sanitize

    appt = await _row(parties, ended_hours_ago=5)
    await _notify(parties, apply=True)
    row = await get_appointments_col().find_one({"_id": appt})

    assert "outcome_notice_sent_at" in row
    for viewer in (True, False):
        out = _sanitize(row, for_lawyer=viewer)
        for field in ("outcome_notice_sent_at", "outcome_notice_attempts",
                      "outcome_notice_last_attempt_at"):
            assert field not in out


async def test_the_notice_carries_no_private_note(parties):
    appt = await _row(parties, ended_hours_ago=5,
                      lawyer_notes="INTERNAL: client was difficult")

    await _notify(parties, apply=True)

    blob = repr(await _notices(appt))
    assert "INTERNAL" not in blob
    assert "difficult" not in blob


# --- still dormant ---------------------------------------------------------

def test_no_scheduler_runs_the_nudge():
    from pathlib import Path

    import app.main as main

    source = Path(main.__file__).read_text(encoding="utf-8")
    assert "notify_outstanding_outcomes" not in source
    assert "appointment_outcomes" not in source


# ── 10. Retry fairness ───────────────────────────────────────────────────────
#
# Two failures are possible here and they pull in opposite directions.
#
# Drain retries first and a handful of unreachable recipients consume every
# run, so a consultation that finished this morning is never mentioned.
#
# Drain fresh work first and a steady trickle of new consultations means the
# retry queue is never reached, so a lawyer whose notice failed once is never
# told at all — quietly, for ever, because nothing reports a queue that is
# simply never read.
#
# A reserved share bounds both. These tests are written against the second
# failure, because it is the one an ordering fix creates.


class _FailFor:
    """Fail sends for chosen appointments, deliver the rest."""

    def __init__(self, monkeypatch, failing: set):
        from app.services import notification_service

        self.failing = failing
        self.sent: list[str] = []
        real = notification_service.create_notification

        async def _maybe(**kwargs):
            appt_id = (kwargs.get("payload") or {}).get("appointment_id")
            if appt_id in self.failing:
                raise RuntimeError("recipient unreachable")
            self.sent.append(appt_id)
            return await real(**kwargs)

        monkeypatch.setattr(
            notification_service, "create_notification", _maybe)


async def test_the_cap_is_split_between_fresh_work_and_retries():
    assert outcomes.NOTICE_CAP == 25
    assert outcomes.FRESH_CAP + outcomes.RETRY_CAP == outcomes.NOTICE_CAP
    assert outcomes._split_budget(25) == {"fresh": 20, "retry": 5}


async def test_a_small_cap_keeps_a_reserve_rather_than_rounding_it_away():
    """A reserve that rounds to zero is not a reserve, and a cautious first run
    with a small cap is exactly when the ordering matters most."""
    for limit in range(2, 26):
        split = outcomes._split_budget(limit)
        assert split["fresh"] + split["retry"] == limit
        assert split["retry"] >= 1, f"no reserve at limit={limit}"
        assert split["fresh"] >= 1


async def test_one_notice_cannot_be_shared():
    """At a cap of one, fresh work takes it: a consultation nobody has been
    told about at all is the worse silence."""
    assert outcomes._split_budget(1) == {"fresh": 1, "retry": 0}


async def test_sustained_fresh_traffic_does_not_starve_retries(parties, monkeypatch):
    """THE STARVATION THIS RESERVE EXISTS FOR.

    A failed notice, and then more new consultations than a run can carry, on
    every run. With fresh-first ordering and one shared budget the retry is
    never reached — not delayed, never — because there is always newer work in
    front of it.
    """
    stuck = await _row(parties, ended_hours_ago=90)
    failing = _FailFor(monkeypatch, {stuck})

    # It fails once, and is now a retry.
    await _notify(parties, apply=True, limit=4)
    assert failing.sent == []

    # From here it would deliver, but every run is swamped with fresh work.
    failing.failing = set()
    now = datetime.now(timezone.utc)

    for run in range(3):
        for i in range(10):
            await _row(parties, ended_hours_ago=50 - run * 10 - i * 0.1)
        report = await _notify(
            parties, apply=True, limit=4,
            now=now + outcomes.RETRY_BACKOFF[0] + timedelta(minutes=run))
        if stuck in failing.sent:
            break

    assert stuck in failing.sent, (
        "a failed notice was never retried while fresh work kept arriving")
    assert report["retry_sent"] >= 1


async def test_the_reserve_is_not_lent_back_to_fresh_work(parties):
    """Unused retry budget stays unused. Lending it out would mean the reserve
    only exists on the runs that do not need it."""
    for i in range(10):
        await _row(parties, ended_hours_ago=60 - i)

    report = await _notify(parties, apply=True, limit=5)

    assert report["fresh_sent"] == 4
    assert report["retry_sent"] == 0
    assert report["sent"] == 4, "the retry reserve was spent on fresh work"


async def test_retries_do_not_consume_the_fresh_share(parties, monkeypatch):
    """The mirror: a backlog of retries must not crowd out new consultations."""
    stuck = [await _row(parties, ended_hours_ago=90 - i) for i in range(6)]
    failing = _FailFor(monkeypatch, set(stuck))
    await _notify(parties, apply=True, limit=25)
    assert failing.sent == []

    failing.failing = set()
    fresh = [await _row(parties, ended_hours_ago=5 - i * 0.1) for i in range(3)]
    later = datetime.now(timezone.utc) + outcomes.RETRY_BACKOFF[0]

    report = await _notify(parties, apply=True, limit=5, now=later)

    assert report["fresh_sent"] == 3, report
    assert all(appt in failing.sent for appt in fresh), (
        "new consultations waited behind a backlog of retries")


# --- backoff ---------------------------------------------------------------

async def test_a_failed_recipient_is_not_attempted_every_run(parties, monkeypatch):
    """THE POINT OF BACKOFF. Without it an unreachable address is written to on
    every run for ever, and each run spends part of its reserve on it."""
    appt = await _row(parties, ended_hours_ago=50)
    _FailFor(monkeypatch, {appt})

    first = await _notify(parties, apply=True, limit=5)
    assert first["failed"] == 1

    immediate = await _notify(parties, apply=True, limit=5)

    assert immediate["scanned"] == 0, "the failing row was tried again at once"
    assert immediate["failed"] == 0


async def test_the_wait_grows_with_each_failure(parties, monkeypatch):
    from app.db.collections import get_appointments_col

    appt = await _row(parties, ended_hours_ago=50)
    _FailFor(monkeypatch, {appt})

    now = datetime.now(timezone.utc)
    waits = []
    for attempt in range(3):
        await _notify(parties, apply=True, limit=5, now=now)
        row = await get_appointments_col().find_one({"_id": appt})
        waits.append(row["outcome_notice_retry_after"] - now)
        now = row["outcome_notice_retry_after"]

    assert waits == sorted(waits), f"the wait did not grow: {waits}"
    assert waits[0] < waits[-1]


async def test_the_wait_stops_growing_rather_than_abandoning_the_row():
    """The last step repeats. A consultation whose notice is hard to deliver is
    still a consultation nobody has reported an outcome for, so nothing here
    ever gives up on it."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    longest = outcomes.RETRY_BACKOFF[-1]

    for attempts in (len(outcomes.RETRY_BACKOFF), 50, 5000):
        assert outcomes._retry_after(attempts, now) == now + longest


async def test_a_recovered_recipient_is_notified_and_the_backoff_cleared(
        parties, monkeypatch):
    from app.db.collections import get_appointments_col

    appt = await _row(parties, ended_hours_ago=50)
    failing = _FailFor(monkeypatch, {appt})
    await _notify(parties, apply=True, limit=5)

    failing.failing = set()
    later = datetime.now(timezone.utc) + outcomes.RETRY_BACKOFF[0]
    report = await _notify(parties, apply=True, limit=5, now=later)

    assert report["sent"] == 1
    row = await get_appointments_col().find_one({"_id": appt})
    assert "outcome_notice_retry_after" not in row
    assert "outcome_notice_attempts" not in row
    assert row["outcome_notice_sent_at"] is not None


async def test_backoff_never_marks_a_row_as_notified(parties, monkeypatch):
    """A wait is not a delivery. The row must still be outstanding."""
    from app.db.collections import get_appointments_col

    appt = await _row(parties, ended_hours_ago=50)
    _FailFor(monkeypatch, {appt})
    await _notify(parties, apply=True, limit=5)

    row = await get_appointments_col().find_one({"_id": appt})
    assert "outcome_notice_sent_at" not in row
    assert row["status"] == "confirmed"
    assert await _notices(appt) == []


# --- the guarantees that must survive all of the above ---------------------

async def test_report_only_still_writes_nothing_with_retries_present(
        parties, monkeypatch):
    from app.db.collections import get_appointments_col

    appt = await _row(parties, ended_hours_ago=50)
    _FailFor(monkeypatch, {appt})
    await _notify(parties, apply=True, limit=5)

    monkeypatch.undo()
    later = datetime.now(timezone.utc) + outcomes.RETRY_BACKOFF[0]
    before = await get_appointments_col().find_one({"_id": appt})

    report = await _notify(parties, limit=5, now=later)

    assert report["applied"] is False
    assert report["sent"] >= 1, "a report-only run must still say what it would do"
    assert await get_appointments_col().find_one({"_id": appt}) == before
    assert await _notices(appt) == []


async def test_duplicate_workers_still_produce_one_notice_on_a_retry(
        parties, monkeypatch):
    """The reserve and the backoff are scheduling. The dedup is still the
    database's, and it still holds when two runs race on the same retry."""
    import asyncio

    appt = await _row(parties, ended_hours_ago=50)
    failing = _FailFor(monkeypatch, {appt})
    await _notify(parties, apply=True, limit=5)

    failing.failing = set()
    later = datetime.now(timezone.utc) + outcomes.RETRY_BACKOFF[0]

    results = await asyncio.gather(
        _notify(parties, apply=True, limit=5, now=later),
        _notify(parties, apply=True, limit=5, now=later))

    assert sum(r["sent"] for r in results) >= 1
    assert len(await _notices(appt)) == 1


async def test_a_retry_that_fails_again_stays_retryable(parties, monkeypatch):
    from app.db.collections import get_appointments_col

    appt = await _row(parties, ended_hours_ago=50)
    _FailFor(monkeypatch, {appt})

    now = datetime.now(timezone.utc)
    await _notify(parties, apply=True, limit=5, now=now)
    row = await get_appointments_col().find_one({"_id": appt})
    await _notify(parties, apply=True, limit=5,
                  now=row["outcome_notice_retry_after"])

    row = await get_appointments_col().find_one({"_id": appt})
    assert row["outcome_notice_attempts"] == 2
    assert "outcome_notice_sent_at" not in row
    assert row["status"] == "confirmed"


# ── 11. The HTTP boundary ────────────────────────────────────────────────────
#
# The queue lists OTHER PEOPLE'S consultations, so the interesting tests here
# are about who may read it and what leaves the server — not about whether the
# rows are the right ones, which section 1 already settled.


@pytest.fixture
async def http(parties):
    """The real app, with authentication overridden per-request.

    The route's own `require_lawyer` dependency is left in place — overriding
    that would remove the thing most worth testing.
    """
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
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
            transport=transport, base_url="http://test/api/v1") as client:
        client.act_as = lambda user: state.__setitem__("user", user)
        yield client
    app.dependency_overrides.clear()


def _as(role, user_id):
    return {"_id": user_id, "role": role, "is_active": True}


async def test_a_lawyer_reads_their_own_queue(http, parties):
    appt = await _row(parties, ended_hours_ago=5)
    http.act_as(_as("lawyer", parties["lawyer_id"]))

    r = await http.get("/appointments/outcomes/pending")

    assert r.status_code == 200
    assert [i["id"] for i in r.json()["items"]] == [appt]


async def test_another_lawyer_sees_nothing_of_it(http, parties):
    """Not 403 — an empty queue. The other lawyer is entitled to ask about
    their own work; there simply is none of it."""
    await _row(parties, ended_hours_ago=5)
    http.act_as(_as("lawyer", parties["lawyer2_id"]))

    r = await http.get("/appointments/outcomes/pending")

    assert r.status_code == 200
    assert r.json()["items"] == []


async def test_a_client_is_refused(http, parties):
    await _row(parties, ended_hours_ago=5)
    http.act_as(_as("client", parties["client_id"]))

    r = await http.get("/appointments/outcomes/pending")

    assert r.status_code == 403


async def test_an_admin_is_refused(http, parties):
    await _row(parties, ended_hours_ago=5)
    http.act_as(_as("admin", "OC-ADMIN"))

    r = await http.get("/appointments/outcomes/pending")

    assert r.status_code == 403


async def test_an_anonymous_caller_is_refused(http, parties):
    await _row(parties, ended_hours_ago=5)
    http.act_as(None)

    r = await http.get("/appointments/outcomes/pending")

    assert r.status_code == 401


async def test_the_queue_cannot_be_asked_for_somebody_elses(http, parties):
    """THE AUTHORISATION BUG THIS ROUTE MUST NOT HAVE.

    The lawyer comes from the token. A `lawyer_id` parameter would let any
    lawyer read any other lawyer's unreported consultations, and a filter that
    accepts a caller-supplied identity is not a filter.
    """
    appt = await _row(parties, ended_hours_ago=5)
    http.act_as(_as("lawyer", parties["lawyer2_id"]))

    r = await http.get("/appointments/outcomes/pending",
                       params={"lawyer_id": parties["lawyer_id"]})

    assert r.status_code == 200
    assert r.json()["items"] == [], "a query parameter overrode the token"
    assert appt not in str(r.json())


async def test_the_response_carries_no_internal_fields(http, parties):
    appt = await _row(parties, ended_hours_ago=5)
    http.act_as(_as("lawyer", parties["lawyer_id"]))

    body = (await http.get("/appointments/outcomes/pending")).json()

    item = body["items"][0]
    assert item["id"] == appt
    for field in ("occupied_slots", "idempotency_key", "payload_fingerprint",
                  "expires_at", "outcome_notice_sent_at",
                  "outcome_notice_attempts", "outcome_notice_retry_after"):
        assert field not in item, f"{field} reached the response"


async def test_the_lawyer_sees_their_own_note(http, parties):
    """`lawyer_notes` is the lawyer's own record of their own consultation, and
    the queue is scoped to them in the query, so every row in it is theirs."""
    await _row(parties, ended_hours_ago=5, lawyer_notes="my own note")
    http.act_as(_as("lawyer", parties["lawyer_id"]))

    body = (await http.get("/appointments/outcomes/pending")).json()

    assert body["items"][0]["lawyer_notes"] == "my own note"


async def test_the_response_names_the_client(http, parties):
    await _row(parties, ended_hours_ago=5)
    http.act_as(_as("lawyer", parties["lawyer_id"]))

    body = (await http.get("/appointments/outcomes/pending")).json()

    assert body["items"][0]["client_name"] == "Client One"


# --- pagination over the wire ----------------------------------------------

async def test_the_whole_backlog_is_reachable_beyond_fifty_rows(http, parties):
    """MORE THAN ONE PAGE, AND MORE THAN THE FIFTY THE LISTS ELSEWHERE FETCH.

    The existing appointment lists request 50 rows and never ask for a second
    page, which is exactly why this queue could not be built as a filter over
    them: the backlog it exists to surface starts where that page ends.
    """
    made = [await _row(parties, ended_hours_ago=200 - i) for i in range(57)]
    http.act_as(_as("lawyer", parties["lawyer_id"]))

    walked, cursor, pages = [], None, 0
    while True:
        params = {"page_size": 25}
        if cursor:
            params.update(cursor)
        r = await http.get("/appointments/outcomes/pending", params=params)
        assert r.status_code == 200
        body = r.json()
        walked += [i["id"] for i in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
        assert pages < 20, "the cursor did not advance"

    assert len(walked) == 57
    assert len(set(walked)) == 57, "a row was returned twice"
    assert set(walked) == set(made)
    assert pages == 3


async def test_the_cutoff_is_carried_across_pages(http, parties):
    for i in range(4):
        await _row(parties, ended_hours_ago=100 - i)
    http.act_as(_as("lawyer", parties["lawyer_id"]))

    first = (await http.get("/appointments/outcomes/pending",
                            params={"page_size": 2})).json()
    second = (await http.get("/appointments/outcomes/pending",
                             params={"page_size": 2,
                                     **first["next_cursor"]})).json()

    assert first["cutoff"] == second["cutoff"]
    assert first["next_cursor"]["cutoff"] == first["cutoff"]


async def test_a_partial_cursor_is_refused_over_http(http, parties):
    """Not a silent restart. A caller that has lost half its cursor has lost
    its position, and a page that looks like progress is worse than an error."""
    await _row(parties, ended_hours_ago=5)
    http.act_as(_as("lawyer", parties["lawyer_id"]))

    r = await http.get(
        "/appointments/outcomes/pending",
        params={"after_id": "OC-A-whatever"})

    assert r.status_code == 422


async def test_an_absurd_page_size_is_refused(http, parties):
    http.act_as(_as("lawyer", parties["lawyer_id"]))

    assert (await http.get("/appointments/outcomes/pending",
                           params={"page_size": 5000})).status_code == 422
    assert (await http.get("/appointments/outcomes/pending",
                           params={"page_size": 0})).status_code == 422


async def test_an_empty_queue_is_a_genuine_empty_response(http, parties):
    """Distinguishable from a failed read by the status code alone, which is
    what lets the UI tell "nothing to do" from "we could not ask"."""
    http.act_as(_as("lawyer", parties["lawyer_id"]))

    r = await http.get("/appointments/outcomes/pending")

    assert r.status_code == 200
    assert r.json()["items"] == []
    assert r.json()["next_cursor"] is None


async def test_reading_the_queue_changes_nothing(http, parties):
    from app.db.collections import get_appointments_col

    appt = await _row(parties, ended_hours_ago=5)
    before = await get_appointments_col().find_one({"_id": appt})
    http.act_as(_as("lawyer", parties["lawyer_id"]))

    await http.get("/appointments/outcomes/pending")

    assert await get_appointments_col().find_one({"_id": appt}) == before
