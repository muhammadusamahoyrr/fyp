"""When an unanswered booking request stops holding its slot. Pure.

WHY A DEADLINE EXISTS AT ALL

A PENDING request claims its `occupied_slots` under the unique indexes and
nothing releases them. A client can book an hour, never be answered, and that
hour stays unavailable to everyone for ever. The booking rate limit bounds how
fast requests arrive; it does nothing about the ones that accumulate.

THE SHAPE OF THE RULE

    deadline = min( start,  max( start - 24h,  created + 2h ),  created + 7d )

Three terms, each answering a different failure:

  * `start - 24h` is the useful case. A request still unanswered a day out is
    one the client should be free to take elsewhere, and the slot is released
    while it is still worth something to somebody.

  * `created + 2h` is a FLOOR, and it exists because booking permits any future
    time. A request made ninety minutes before its start is otherwise born past
    its own deadline and would be expired by the first sweep, possibly before
    the lawyer ever saw it.

  * `created + 7d` is an IMMOVABLE CAP. The first term is recomputed whenever
    the client reschedules, so without this a request could be pushed forward
    indefinitely and never lapse. This term is anchored to creation and never
    moves, which bounds the total life of a request no matter how it is moved.

And the whole thing is capped at `start`, because a deadline after the
appointment itself is meaningless — by then the time has passed.

THE TWO-HOUR TERM IS A FLOOR, NOT A CEILING, and an earlier version of this
docstring had it backwards — it said the floor gave the lawyer "at most two
hours", which is wrong in both directions and worth correcting explicitly.

What it actually does: it raises the deadline to at least `created + 2h` WHERE
THE START PERMITS IT. The whole expression is capped at `start`, so a request
made ninety minutes before its appointment gets ninety minutes, not two hours —
the floor cannot buy time that is on the far side of the appointment itself.

And it is not a description of the usual response window, which is normally far
longer. An ordinary booking two days out lapses 24 hours before its start, so
the lawyer has a day to answer. Two hours is the MINIMUM the rule reaches for,
not the allowance it hands out.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Released a day before the appointment, when the slot is still rebookable.
LEAD_RELEASE = timedelta(hours=24)

# The minimum a lawyer gets to answer. Deliberately the number the product
# already uses for the confirmed-cancellation cutoff, rather than a second
# unrelated constant a reader has to reconcile.
MIN_RESPONSE = timedelta(hours=2)

# The absolute life of a request, anchored to creation and never extended by a
# reschedule.
MAX_LIFE = timedelta(days=7)


def _as_utc(value: datetime) -> datetime:
    """Aware UTC. Rows written before `tz_aware=True` decode naive, and they
    were always UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def deadline_for(created_at: datetime, scheduled_at: datetime) -> datetime:
    """When this request stops holding its slot.

    Both arguments are instants, not wall-clock times, so no zone conversion
    happens here — the caller's values are already UTC by the time they reach
    storage.
    """
    created = _as_utc(created_at)
    start = _as_utc(scheduled_at)
    return min(
        start,
        max(start - LEAD_RELEASE, created + MIN_RESPONSE),
        created + MAX_LIFE,
    )


def deadline_of(appt: dict) -> datetime | None:
    """The deadline of a stored row, stored or derived.

    A row written before this field existed carries none. It is DERIVED at the
    read boundary rather than backfilled — the same treatment `timezone` and
    `schedule_version` already get — so no migration is needed to reason about
    an old request.

    Returns None only when the row cannot be assessed at all: no usable
    `scheduled_at`, or no `created_at` to anchor the floor and the cap. Such a
    row is left alone rather than guessed at, because a guessed deadline
    expires somebody's appointment on invented evidence.
    """
    stored = appt.get("expires_at")
    if isinstance(stored, datetime):
        return _as_utc(stored)

    created = appt.get("created_at")
    start = appt.get("scheduled_at")
    if not isinstance(created, datetime) or not isinstance(start, datetime):
        return None
    return deadline_for(created, start)


def has_lapsed(appt: dict, now: datetime | None = None) -> bool:
    """Is this request past its deadline?

    A row with no assessable deadline is NOT lapsed. "Cannot tell" must not
    read as "expire it" — that is the direction of the mistake that terminates
    a real appointment.
    """
    deadline = deadline_of(appt)
    if deadline is None:
        return False
    return (now or datetime.now(timezone.utc)) >= deadline
