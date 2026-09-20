"""The appointment state machine, written as data rather than as `if`s.

Every transition rule used to live inline in whichever service function
happened to perform it, so the rules could only be read by reading four
functions and could only disagree silently. They did disagree: `complete`
accepted a PENDING appointment, so a lawyer could complete a consultation
nobody had ever confirmed, while `no_show` — the other end of the same
"what happened at the meeting" question — required CONFIRMED.

Two kinds of rule live here, and they are deliberately separate:

  * WHICH statuses may follow which. A violation is a CONFLICT: the caller is
    acting on a stale view of an appointment somebody else has already moved,
    and re-reading is the fix. → 409.

  * WHEN a transition is meaningful. A violation is a bad REQUEST: nothing is
    stale, the caller is simply declaring an outcome for a meeting that has not
    happened yet. Re-reading changes nothing; waiting does. → 422.

This module is pure. It touches no database and no clock it was not handed, so
the rules can be tested exhaustively without Mongo.
"""
from datetime import datetime

from app.core.constants import AppointmentStatus

PENDING = AppointmentStatus.PENDING
CONFIRMED = AppointmentStatus.CONFIRMED
CANCELLED = AppointmentStatus.CANCELLED
COMPLETED = AppointmentStatus.COMPLETED
NO_SHOW = AppointmentStatus.NO_SHOW
EXPIRED = AppointmentStatus.EXPIRED


# An appointment that did not happen yet can be confirmed or called off. One
# that is confirmed can be called off, or reported on afterwards. Everything
# else is an ending: what happened at a consultation does not get revised
# through this API, because a completed appointment gates the client's right to
# review the lawyer (`exists_completed`) and a reversible outcome would make
# that gate reversible too.
_ALLOWED: dict[AppointmentStatus, frozenset[AppointmentStatus]] = {
    # EXPIRED is reachable ONLY from PENDING, and only by the sweep. A
    # confirmed appointment has been agreed by both parties and does not lapse
    # because nobody looked at it again.
    PENDING:   frozenset({CONFIRMED, CANCELLED, EXPIRED}),
    CONFIRMED: frozenset({CANCELLED, COMPLETED, NO_SHOW}),
    COMPLETED: frozenset(),
    CANCELLED: frozenset(),
    NO_SHOW:   frozenset(),
    EXPIRED:   frozenset(),
}

TERMINAL: frozenset[AppointmentStatus] = frozenset(
    status for status, onward in _ALLOWED.items() if not onward
)


def allowed_from(source: AppointmentStatus) -> frozenset[AppointmentStatus]:
    """The statuses reachable from `source`."""
    return _ALLOWED.get(source, frozenset())


def sources_for(target: AppointmentStatus) -> frozenset[AppointmentStatus]:
    """Every status a transition to `target` may legally start from.

    NOT the compare-and-set predicate, and deliberately so. An earlier version
    of this docstring said it was, which was wrong in a way worth spelling out
    because the wrong version is the tempting one.

    `_transition` pins the CAS filter to `[source]` — the single status the
    caller actually OBSERVED — not to this whole set. Widening it to
    `sources_for(target)` would re-admit the race the CAS exists to close: a
    cancel landing between another caller's read and its write still leaves
    PENDING inside `sources_for(CONFIRMED)`, so that caller's confirm would
    match and silently overwrite the cancellation. Checking against the world
    the caller saw is the entire point; checking against the set of worlds that
    would have been acceptable is not the same test.

    So this is a query over the table for reasoning and validation — not a
    predicate to build a write from. It currently has no production caller,
    which is the honest status of it: the table is consumed through
    `is_allowed`. Keep it that way, or delete it; do not wire it into a filter.
    """
    return frozenset(
        source for source, onward in _ALLOWED.items() if target in onward
    )


def is_allowed(source: AppointmentStatus, target: AppointmentStatus) -> bool:
    return target in allowed_from(source)


def explain(source: AppointmentStatus, target: AppointmentStatus) -> str:
    """Why a transition was refused, in terms the caller can act on.

    It names the status the appointment is actually in, because that is what
    the caller needs in order to re-render — and it is not a leak: the caller
    has already been shown to be a party to this appointment before any
    message from here is raised.
    """
    if source in TERMINAL:
        return (
            f"This appointment is already {source.value} and cannot be "
            f"changed to {target.value}."
        )
    return (
        f"An appointment in '{source.value}' status cannot be marked "
        f"'{target.value}'."
    )


def timing_error(
    target: AppointmentStatus,
    scheduled_at: datetime,
    end_at: datetime,
    now: datetime,
) -> str | None:
    """Why `target` is premature, or None when the clock permits it.

    All three datetimes must be timezone-aware; the caller normalises stored
    values through `_as_utc` first. Comparing a naive stored instant against an
    aware `now` is the exact defect Phase 1 removed, and silently re-admitting
    it here would put it back on a path with no test.
    """
    if target is CONFIRMED and scheduled_at <= now:
        # Confirming a slot that has already passed commits nobody to anything;
        # it only produces a "confirmed" row for a meeting that cannot occur,
        # which then has to be cancelled to get it off both parties' lists.
        return (
            "This appointment time has already passed and can no longer be "
            "confirmed. Cancel it instead."
        )
    if target is COMPLETED and now < end_at:
        # Completion is a statement about a consultation that finished. Before
        # the scheduled end there is nothing to report on yet.
        return (
            "This appointment has not finished yet, so it cannot be marked "
            "completed."
        )
    if target is EXPIRED:
        # The clock rule for expiry is the DEADLINE, which depends on when the
        # request was created as well as when it is for — so it lives in
        # `appointment_expiry` with the rest of that policy, and the sweep
        # asserts it in its own filter. There is nothing to add here, and a
        # second half-rule in this file would be one more place to disagree.
        return None
    if target is NO_SHOW and now < scheduled_at:
        # And a client cannot have failed to turn up to something that has not
        # started. This was reachable: the lawyer's UI offers no-show on
        # Upcoming rows, so the action sat next to appointments days away.
        return (
            "This appointment has not started yet, so the client cannot be "
            "marked as a no-show."
        )
    return None
