"""One read-only report on what the appointment module is actually ready for.

    python -m app.db.appointment_activation_audit
        --database attorney_ai
        --confirm-database attorney_ai
        --confirm-endpoint mongodb://db.example.net:27017

WHAT THIS ANSWERS, AND WHAT IT REFUSES TO ANSWER

Six appointment mechanisms exist and none of them is switched on: expiry,
outcome nudges, reminders, working-hours enforcement, the dispute workflow and
the booking indexes themselves. Deciding to switch any of them on has needed
somebody to open a shell, run five different surveys, and hold the answers in
their head next to a config file. This runs all of it once and prints the
result in one shape.

IT IS NOT A GO BUTTON. It reports separate verdicts per feature, and
`overall_production_go` can never come back READY - see MANUAL_GATES.

IT CHANGES NOTHING, AND THAT IS ENFORCED RATHER THAN INTENDED

The services this calls are the real ones, several of which can write: the
repositories underneath them carry write methods, and a survey that grew an
`apply` argument later would inherit it here silently. So the database handle
every one of them receives is wrapped, and the wrapper forwards an ALLOWLIST of
read operations and refuses everything else by name.

An allowlist, not a list of banned methods, for two reasons. A banned list is
wrong the first time the driver gains a write method nobody here has heard of.
And naming those methods would put the very strings this module must not
contain into the module itself, which is what a reader - and one of the tests -
checks for.

The cost is real and accepted: a reused service that starts calling a read
operation not on the list fails the audit loudly instead of silently working.
That is the correct direction for the failure, and adding the operation is a
one-line, deliberate change.

WHY CONFIRMATION IS REQUIRED FOR A READ-ONLY TOOL

Reading the wrong database is not harmless. This prints counts of pending
requests, unreported outcomes, open complaints and lawyers without schedules;
run against production by somebody who believed they were on staging, those
numbers go into a ticket and a decision gets made about the other environment.
The whole output is a claim about one named target, and a claim about the wrong
target is worse than no claim. So the endpoint and the database are confirmed
before the driver is constructed, exactly as the backfill command requires them
before a write.

The endpoint rules are IMPORTED from `appointment_backfill_cli`, not restated.
Two parsers for "which server is this" drift, and the drift is discovered by
confirming the wrong one.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from app.core.constants import AppointmentStatus
from app.db.appointment_backfill_cli import (
    UnparseableTarget,
    normalise_endpoint,
    parsed_endpoints,
)
from app.db.appointment_index_spec import (
    ACTIVE_STATUSES,
    APPOINTMENT_DISPUTES,
    APPOINTMENTS,
)
from app.db.v2_index_spec import CORRECTNESS

# ITS OWN VARIABLE, not the backfill command's.
#
# `AAI_BACKFILL_MONGO_URL` is set in a shell where somebody is about to write
# to production. Inheriting it would mean this tool runs against that target by
# default, on a machine prepared for a different job - and its output is a
# report somebody then acts on.
URI_ENV_VAR = "AAI_AUDIT_MONGO_URL"

EXIT_OK = 0            # it ran; machine-verifiable checks passed
EXIT_NO_GO = 2         # it ran; something machine-verifiable says no
EXIT_FAILURE = 3       # it did not run, or could not finish

# Deliberately NOT the backfill command's numbering, where 2 is a usage error
# and 3 a refusal. Here the caller most likely to read the code is a pipeline
# asking "may we proceed", and that question has exactly three answers: yes so
# far, no, and "the audit itself did not happen" - which must never be
# indistinguishable from yes.

READY = "READY"
NOT_READY = "NOT_READY"
UNVERIFIED_EXTERNAL = "UNVERIFIED_EXTERNAL"
NOT_EVALUATED = "NOT_EVALUATED"


class AuditWriteAttempted(RuntimeError):
    """A read-only audit reached for an operation that is not a read."""


# ---------------------------------------------------------------------------
# The read-only handle
# ---------------------------------------------------------------------------

# Every operation a collection may serve during an audit. Each entry is here
# because a service this module calls genuinely needs it.
_COLLECTION_READS = frozenset({
    "find",                      # the preflight's row pass, repo find_many
    "find_one",                  # repo find_one
    "aggregate",                 # overlap and idempotency detection
    "count_documents",           # every count in every survey
    "estimated_document_count",
    "distinct",
    "index_information",         # index validation, the preflight
    "list_indexes",
})

# Attributes that describe the handle rather than operate on it.
_COLLECTION_ATTRS = frozenset({"name", "full_name", "codec_options"})

_DATABASE_READS = frozenset({"list_collection_names", "list_collections"})
_DATABASE_ATTRS = frozenset({"name", "codec_options"})

# Aggregation stages that write. These are the reason `aggregate` cannot simply
# be forwarded: they are writes reached through a read API, and a pipeline is
# data - it can be assembled anywhere and arrive here looking like a query.
_WRITING_STAGES = frozenset({"$out", "$merge"})


class _ReadOnlyCollection:
    """One collection, readable and nothing else."""

    def __init__(self, inner, label: str):
        self._inner = inner
        self._label = label

    def __getattr__(self, item):
        if item in _COLLECTION_ATTRS:
            return getattr(self._inner, item)
        if item not in _COLLECTION_READS:
            raise AuditWriteAttempted(
                f"the audit is read-only: {self._label}.{item} is not a "
                "permitted read operation")
        return getattr(self._inner, item)

    def __getitem__(self, item):
        # Sub-collection access, kept guarded rather than blocked: refusing it
        # would be a surprise, and forwarding it unwrapped would be a hole
        # straight through this class.
        return _ReadOnlyCollection(self._inner[item], f"{self._label}.{item}")

    def aggregate(self, pipeline, *args, **kwargs):
        stages = {stage for step in (pipeline or []) if isinstance(step, dict)
                  for stage in step}
        writing = sorted(stages & _WRITING_STAGES)
        if writing:
            raise AuditWriteAttempted(
                f"the audit is read-only: an aggregation on {self._label} "
                f"names a writing stage ({', '.join(writing)})")
        return self._inner.aggregate(pipeline, *args, **kwargs)


class _ReadOnlyDatabase:
    """One database, handing out only read-only collections."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, item):
        if item in _DATABASE_ATTRS or item in _DATABASE_READS:
            return getattr(self._inner, item)
        # Anything else is either a write, a command channel that can carry
        # one, or an unknown - and an unknown is a write until somebody says
        # otherwise.
        raise AuditWriteAttempted(
            f"the audit is read-only: database.{item} is not a permitted "
            "read operation")

    def __getitem__(self, name):
        return _ReadOnlyDatabase._wrap(self._inner, name)

    def get_collection(self, name, *args, **kwargs):
        return _ReadOnlyCollection(
            self._inner.get_collection(name, *args, **kwargs), name)

    @staticmethod
    def _wrap(inner, name):
        return _ReadOnlyCollection(inner[name], name)


class _ReadOnlyClient:
    """The handle `get_database()` reads out of, guarded at the root.

    Bound in place of the application's client so that every service reached
    from here - including the ones that take no database argument and simply
    call `get_database()` - receives the guarded handle. There is no path
    around it short of importing the driver directly, which this does not do.
    """

    def __init__(self, inner):
        self._inner = inner

    def __getitem__(self, name):
        return _ReadOnlyDatabase(self._inner[name])

    @property
    def raw(self):
        """The underlying client, so the caller can close it. Not for reading."""
        return self._inner


# ---------------------------------------------------------------------------
# The manual gates
# ---------------------------------------------------------------------------

# WHAT THIS TOOL CANNOT SEE, LISTED SO THAT ITS SILENCE IS NOT MISTAKEN FOR
# APPROVAL.
#
# Every entry is something no query can establish. A booking freeze is a state
# of the deployment, not of the data; a restore is only proven by a restore
# that happened; an authorisation is a person's decision. They are reported at
# UNVERIFIED_EXTERNAL always, and there is deliberately NO command-line flag
# that marks any of them satisfied.
#
# The backfill command does take such a flag, and it is right to: there, the
# acknowledgement is attached to the operator who is about to write, in the
# same command, and it is labelled an acknowledgement rather than a check. Here
# the output is a REPORT - it outlives the shell it was produced in, gets
# pasted into a ticket, and is read later by somebody who was not there. A flag
# would turn "I typed the argument" into "the gate passed" at exactly the
# moment the evidence is gone.
MANUAL_GATES: tuple[tuple[str, str], ...] = (
    ("booking_write_freeze_rehearsed",
     "a booking written during the backfill carries no occupied_slots, so it "
     "is invisible to the indexes and escapes overlap protection permanently; "
     "the freeze must be rehearsed, not assumed"),
    ("backup_and_restore_rehearsed",
     "a backup nobody has restored is a file, not a backup; the activation "
     "sequence has irreversible steps and this is what makes them survivable"),
    ("irreversible_backfill_authorised",
     "writing occupied_slots onto existing rows changes live legal "
     "engagements and has no undo"),
    ("obsolete_index_removal_authorised",
     "dropping uniq_pending_slot is irreversible without another index build, "
     "and while it stands it is the only overlap guard in place"),
    ("legacy_expiry_policy_approved",
     "expiring requests that predate expires_at terminates client requests "
     "nobody answered; which rows, and from when, is a decision"),
    ("activation_timestamps_and_caps_approved",
     "the nudge activation instant decides how much history gets notified, "
     "and the batch caps decide how many people hear from us at once"),
)

# What each machine-verifiable verdict is allowed to talk about. Named here so
# a section that stops reporting a gate cannot quietly leave a verdict READY.
_FEATURE_VERDICTS = (
    "booking_rollout",
    "expiry_activation",
    "outcome_nudges_activation",
    "reminders_activation",
    "working_hours_enforcement",
    "dispute_workflow",
)

# Which declared QUERY index each feature's read depends on.
#
# BY FEATURE, so a missing performance index is reported against the one thing
# it slows down. Rolling them together produces "query indexes: NOT READY",
# which reads like a reason not to activate any of them and is a reason not to
# activate exactly one.
QUERY_INDEX_BY_FEATURE: tuple[tuple[str, str], ...] = (
    ("pending_expiry", "appointment_pending_expiry"),
    ("outcome_queue", "appointment_confirmed_outcome"),
    ("reminder_scheduling", "appointment_confirmed_reminder"),
    ("disputes", "appointment_dispute_queue"),
)

# The working-hours read is `find_one({"_id": lawyer_id})` on
# `lawyer_availability`, which the primary key already serves. There is no
# declared index for it and there should not be one: adding a spec so this
# report has something to tick would create an index the system does not need
# and a second place where the schedule lookup is described.
WORKING_HOURS_LOOKUP = "served_by_primary_key"

# Disjoint, unlike the outcome survey's cumulative horizons. Both shapes are
# useful and mixing them up is how a report gets summed into a number twice the
# size of the population, so each carries `cumulative` explicitly.
AGE_BUCKETS: tuple[tuple[str, timedelta | None], ...] = (
    ("under_24h", timedelta(hours=24)),
    ("under_7d", timedelta(days=7)),
    ("under_30d", timedelta(days=30)),
    ("over_30d", None),
)

# Bounds on every scan this tool performs. An audit that walks an unbounded
# collection on a live database is itself a capacity event; each section
# reports `complete` so a truncated count is never read as a total.
PAGE_SIZE = 500
MAX_PAGES = 40


def _bucket(age: timedelta) -> str:
    for name, limit in AGE_BUCKETS:
        if limit is None or age < limit:
            return name
    return AGE_BUCKETS[-1][0]


def _empty_buckets() -> dict:
    return {name: 0 for name, _ in AGE_BUCKETS}


def _as_utc(value):
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Binding the guarded handle
# ---------------------------------------------------------------------------

class _Bound:
    """Point the application's database accessor at the confirmed target.

    The services this reuses do not take a database argument - they call
    `get_database()`, which reads a module global and `settings.db_name`. That
    is exactly what makes them the real services rather than a re-implementation
    of them, so the binding happens here and is undone in `finally`.

    What gets bound is the GUARDED client, never the driver's. A service reached
    through this sees a handle that cannot write, and the audit has no second
    handle that can.
    """

    def __init__(self, client, database: str):
        self._client = client
        self._database = database
        self._previous_client = None
        self._previous_name = None

    def __enter__(self):
        from app.core.config import settings
        from app.db import mongodb

        self._previous_client = mongodb._client
        self._previous_name = settings.db_name
        mongodb._client = _ReadOnlyClient(self._client)
        settings.db_name = self._database
        return mongodb._client[self._database]

    def __exit__(self, *exc):
        from app.core.config import settings
        from app.db import mongodb

        mongodb._client = self._previous_client
        settings.db_name = self._previous_name
        return False


# ---------------------------------------------------------------------------
# 1 and 2. Booking correctness, and the query indexes by feature
# ---------------------------------------------------------------------------

def _problem_view(problem: dict) -> dict:
    """An index problem, reduced to what may be printed.

    The `message` is dropped. It is a fixed string from the specification
    today, and for the unreadable-metadata case it already carries an exception
    class - so it is the field most likely to start carrying a driver's words
    about a host it could not reach. The code and the index name say what to
    do.
    """
    return {"code": problem["code"], "collection": problem["collection"],
            "name": problem["name"], "kind": problem["kind"]}


async def audit_booking(now: datetime) -> tuple[dict, dict]:
    """Sections 1 and 2, from one pass of the existing preflight.

    The preflight already answers every booking-correctness question and
    already splits CORRECTNESS from QUERY. Re-deriving any of it here would
    create a second opinion about whether booking is safe, and the two would
    disagree on the day it mattered.

    Its findings are re-shaped rather than forwarded: it lists offending
    APPOINTMENT IDS, deliberately, because an operator repairing rows needs to
    find them. This report has a different reader and a longer life, so the
    counts survive the trip and the ids do not.
    """
    from app.db.appointment_slot_preflight import preflight

    result = await preflight()
    gates = result["gates"]

    booking = {
        "correctness_indexes_valid": bool(gates["indexes_valid"]),
        "active_rows_usable": bool(gates["all_active_rows_usable"]),
        "active_rows_slotted": bool(gates["all_active_rows_slotted"]),
        "no_lawyer_or_client_overlap": bool(gates["no_overlapping_active_rows"]),
        "no_idempotency_collision": bool(gates["no_idempotency_collisions"]),
        "obsolete_index_absent": bool(gates["obsolete_indexes_absent"]),
        "preflight_safe_to_activate": bool(result["safe_to_activate"]),
        "failed_gates": list(result["failed_gates"]),
        "rows_needing_backfill": int(result["rows_needing_backfill"]),
        "build_blocking_rows": int(result["build_blocking_rows"]),
        # COUNTS ONLY. See the docstring.
        "problem_counts": {f["code"]: int(f["count"])
                           for f in result["findings"] if f["count"]},
        "correctness_problems": [
            _problem_view(p) for p in result["problems"]
            if p["kind"] == CORRECTNESS],
    }

    by_name = {p["name"]: p for p in result["problems"]}
    features: dict = {}
    for feature, index_name in QUERY_INDEX_BY_FEATURE:
        problem = by_name.get(index_name)
        features[feature] = {
            "index": index_name,
            "present": problem is None,
            "problem": _problem_view(problem) if problem else None,
        }
    # Reported, not silently omitted: a reader scanning this section for
    # "working hours" and finding nothing would reasonably conclude the check
    # was forgotten.
    features["working_hours_lookup"] = {
        "index": WORKING_HOURS_LOOKUP,
        "present": True,
        "problem": None,
    }

    query_indexes = {
        "by_feature": features,
        "missing": sorted(name for name, state in features.items()
                          if not state["present"]),
        # Named so nobody reads a missing performance index as a booking
        # defect. These block a feature's activation; they do not make an
        # accepted booking wrong.
        "blocks_booking": False,
    }
    return booking, query_indexes


# ---------------------------------------------------------------------------
# 3. Pending expiry
# ---------------------------------------------------------------------------

async def audit_expiry(db, now: datetime) -> dict:
    """How large the unanswered-request population is, and how overdue.

    EXPIRES NOTHING. There is no apply path into this module and there is not
    meant to be one: terminating a client's request is the one appointment
    action with no undo from their side.

    The legacy population - rows booked before `expires_at` existed - is
    counted by the sweep's own survey rather than re-derived, because judging
    whether one of those has lapsed means applying the deadline policy, and a
    second implementation of that policy is a second answer to "was this
    request still open".
    """
    from app.services import appointment_expiry_sweep

    pending = AppointmentStatus.PENDING.value
    col = db[APPOINTMENTS]

    total = await col.count_documents({"status": pending})
    dated_lapsed = await col.count_documents(
        {"status": pending, "expires_at": {"$lte": now}})
    past_start = await col.count_documents(
        {"status": pending, "scheduled_at": {"$lt": now}})

    legacy = await appointment_expiry_sweep.survey_legacy_pending(now=now)

    buckets = _empty_buckets()
    scanned = 0
    truncated = False
    after_id = None
    for _ in range(MAX_PAGES):
        query: dict = {"status": pending}
        if after_id is not None:
            # Keyset on `_id`, the same cursor the sweep's own survey uses: it
            # is unique and always present, so a page boundary cannot repeat or
            # skip a row, and every page advances past everything just read.
            query["_id"] = {"$gt": after_id}
        page = await col.find(
            query,
            # The projection is part of the sanitisation: the parties, the
            # notes and the meeting link are never read, so no later change to
            # how this prints can leak them.
            {"_id": 1, "created_at": 1},
        ).sort("_id", 1).limit(PAGE_SIZE).to_list(length=PAGE_SIZE)
        if not page:
            break
        for row in page:
            scanned += 1
            created = _as_utc(row.get("created_at"))
            if created is None:
                buckets["over_30d"] += 1
                continue
            buckets[_bucket(now - created)] += 1
        after_id = page[-1]["_id"]
        if len(page) < PAGE_SIZE:
            break
    else:
        truncated = True

    return {
        "pending_total": int(total),
        # The two populations are NOT added together. One is overdue against a
        # deadline the row carries; the other against a deadline derived from
        # its own timestamps because the row predates the field. Summing them
        # would double-count nothing and imply they can be treated alike, which
        # is the decision this section exists to inform rather than make.
        "missing_expires_at": int(legacy["scanned"]),
        "missing_expires_at_complete": bool(legacy["complete"]),
        "currently_expired_dated": int(dated_lapsed),
        "currently_expired_legacy": int(legacy["lapsed"]),
        "legacy_not_lapsed": int(legacy["not_lapsed"]),
        "legacy_unassessable": int(legacy["unassessable"]),
        "already_past_scheduled_start": int(past_start),
        "age_buckets": buckets,
        "age_buckets_cumulative": False,
        "age_scanned": scanned,
        "age_truncated": truncated,
        # Not a measurement. The tool cannot know whether anybody has decided
        # what to do with these rows, so it reports the question as open
        # whenever the population is non-empty and defers to the manual gate.
        "legacy_treatment_undecided": bool(legacy["scanned"]),
    }


# ---------------------------------------------------------------------------
# 4. Outcome nudges
# ---------------------------------------------------------------------------

async def audit_outcome_nudges(now: datetime) -> dict:
    """The unreported-outcome backlog, and whether nudging it is configured.

    NOTIFIES NOBODY. The survey it calls has no apply path; the notifier that
    does is not imported here.
    """
    from app.core.config import settings
    from app.services import appointment_outcomes

    survey = await appointment_outcomes.survey_outstanding_outcomes(now=now)
    activated_at = getattr(
        settings, "appointment_outcome_nudges_activated_at", None)

    return {
        # CUMULATIVE, from the survey: over_7d is a subset of over_24h, which
        # is a subset of over_2h. Carried through with the flag the survey sets
        # rather than silently re-shaped into buckets.
        "outstanding": {key: int(survey[key])
                        for key in ("over_2h", "over_24h", "over_7d")},
        "cumulative": True,
        "enabled": bool(
            getattr(settings, "appointment_outcome_nudges_enabled", False)),
        # WHETHER, not what. The instant itself decides how much history gets
        # notified, and printing it into a report would be printing a decision
        # about real people's consultations that the report is only asked to
        # confirm exists.
        "activation_instant_configured": isinstance(activated_at, datetime),
        "batch_size": int(
            getattr(settings, "appointment_outcome_nudge_batch", 0)),
    }


# ---------------------------------------------------------------------------
# 5. Reminders
# ---------------------------------------------------------------------------

async def audit_reminders(now: datetime) -> dict:
    """How many consultations are inside a reminder window right now.

    DISPATCHES NOTHING. `survey_due_reminders` has no apply path, and the
    sender is not imported here.
    """
    from app.core.config import settings
    from app.services import appointment_reminders

    survey = await appointment_reminders.survey_due_reminders(now=now)

    # The strict lock is what stops every worker dispatching the same batch. It
    # cannot be exercised without taking a lock, which would suppress a real
    # cycle for its whole TTL - so what is checked is that the scheduler is
    # wired to the fail-closed acquirer at all, which is inspectable and is the
    # thing most likely to be got wrong by a later edit.
    from app.core import redis_client
    from app.services import appointment_scheduler

    strict_available = hasattr(redis_client, "acquire_period_lock_strict")
    strict_wired = (
        strict_available
        and getattr(appointment_scheduler, "acquire_period_lock_strict", None)
        is getattr(redis_client, "acquire_period_lock_strict", None))

    return {
        "due": {window: int(count) for window, count in survey["due"].items()},
        "due_total": int(survey["total"]),
        "enabled": bool(
            getattr(settings, "appointment_reminders_enabled", False)),
        "interval_minutes": int(
            getattr(settings, "appointment_scheduler_interval_minutes", 0)),
        "batch_size": int(getattr(settings, "appointment_reminder_batch", 0)),
        "strict_lock_available": bool(strict_available),
        "strict_lock_wired": bool(strict_wired),
    }


# ---------------------------------------------------------------------------
# 6. Working hours
# ---------------------------------------------------------------------------

LAWYER_AVAILABILITY = "lawyer_availability"


async def audit_working_hours(db, now: datetime) -> dict:
    """Who has declared when they work, and what is booked outside it.

    NEVER INFERS A DEFAULT. A lawyer who has saved nothing is counted as
    unconfigured, not as working office hours somebody guessed. The whole point
    of the enforcement flag being off is that this system does not know when
    these people work, and a report that filled the gap with Monday-to-Saturday
    would make the enforcement decision look safe by assuming the answer.

    `is_configured` and `covers` are the policy module's, unchanged. Enforcement
    at booking asks exactly `covers`; asking anything else here would report a
    readiness the enforcement path does not share.
    """
    from app.core.config import settings
    from app.repositories.user_repo import UserRepository
    from app.services import lawyer_availability as policy

    # Who is eligible, through `find_lawyers`, so the predicate - verified,
    # active, role lawyer - is the directory's own and cannot drift from it.
    # The repository is constructed here rather than imported as a singleton
    # because it resolves its collection lazily, through `get_database()`, and
    # must therefore be built inside the binding rather than at import time.
    lawyers = UserRepository()
    first = await lawyers.find_lawyers(page=1, page_size=1)
    eligible_total = int(first.total)

    eligible_ids: set[str] = set()
    wanted_pages = max((eligible_total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    eligible_complete = wanted_pages <= MAX_PAGES
    for page_no in range(1, min(wanted_pages, MAX_PAGES) + 1):
        page = await lawyers.find_lawyers(page=page_no, page_size=PAGE_SIZE)
        if not page.items:
            break
        eligible_ids.update(str(row["_id"]) for row in page.items
                            if row.get("_id") is not None)

    # Who has said when they work.
    schedules: dict[str, dict] = {}
    col = db[LAWYER_AVAILABILITY]
    after_id = None
    schedules_complete = False
    for _ in range(MAX_PAGES):
        query: dict = {} if after_id is None else {"_id": {"$gt": after_id}}
        page_rows = await col.find(query).sort("_id", 1).limit(
            PAGE_SIZE).to_list(length=PAGE_SIZE)
        if not page_rows:
            schedules_complete = True
            break
        for row in page_rows:
            schedules[str(row["_id"])] = row
        after_id = page_rows[-1]["_id"]
        if len(page_rows) < PAGE_SIZE:
            schedules_complete = True
            break

    configured_ids = {lawyer_id for lawyer_id, row in schedules.items()
                      if policy.is_configured(row)}
    configured_eligible = len(eligible_ids & configured_ids)

    # What is booked.
    outside = 0
    unconfigured_bookings = 0
    unassessable = 0
    upcoming = 0
    appts = db[APPOINTMENTS]
    after_id = None
    bookings_complete = False
    for _ in range(MAX_PAGES):
        query = {"status": {"$in": list(ACTIVE_STATUSES)},
                 "scheduled_at": {"$gte": now}}
        if after_id is not None:
            query["_id"] = {"$gt": after_id}
        page_rows = await appts.find(
            query,
            # The projection is the sanitisation: no parties, no notes, no
            # meeting link is ever read.
            {"_id": 1, "lawyer_id": 1, "scheduled_at": 1,
             "duration_minutes": 1},
        ).sort("_id", 1).limit(PAGE_SIZE).to_list(length=PAGE_SIZE)
        if not page_rows:
            bookings_complete = True
            break
        for row in page_rows:
            upcoming += 1
            lawyer_id = str(row.get("lawyer_id"))
            start = _as_utc(row.get("scheduled_at"))
            duration = row.get("duration_minutes")
            if start is None or not isinstance(duration, int):
                unassessable += 1
                continue
            if lawyer_id not in configured_ids:
                # NOT counted as outside a schedule. There is no schedule to be
                # outside of, and rolling the two together would report a
                # lawyer who never answered the question as one being booked
                # against their own stated hours.
                unconfigured_bookings += 1
                continue
            if not policy.covers(schedules.get(lawyer_id), start, duration):
                outside += 1
        after_id = page_rows[-1]["_id"]
        if len(page_rows) < PAGE_SIZE:
            bookings_complete = True
            break

    return {
        "eligible_lawyers": eligible_total,
        "eligible_scanned": len(eligible_ids),
        "eligible_complete": bool(eligible_complete),
        "configured": configured_eligible,
        "unconfigured": max(eligible_total - configured_eligible, 0),
        "schedules_complete": bool(schedules_complete),
        # Schedules saved by somebody who is not currently an eligible lawyer -
        # deactivated, or no longer verified. Reported rather than dropped: it
        # is the difference between "nobody configured" and "the directory
        # moved on".
        "schedules_outside_directory": len(configured_ids - eligible_ids),
        "upcoming_active_bookings": upcoming,
        "upcoming_outside_schedule": outside,
        "upcoming_for_unconfigured_lawyer": unconfigured_bookings,
        "upcoming_unassessable": unassessable,
        "bookings_complete": bool(bookings_complete),
        "enforced": bool(
            getattr(settings, "appointment_working_hours_enforced", False)),
    }


# ---------------------------------------------------------------------------
# 7. Disputes
# ---------------------------------------------------------------------------

async def audit_disputes(db, now: datetime, index_problems: list[dict]) -> dict:
    """How many complaints are open, and how long they have been open.

    NO IDS, NO CLIENT STATEMENTS, NO SUPPORT NOTES. A dispute document holds a
    client's account of what went wrong and support's private reasoning about
    it; this reads `created_at` and nothing else, so there is nothing for a
    later change to the printing to expose.
    """
    from app.repositories.appointment_dispute_repo import (
        AppointmentDisputeRepository,
    )

    # The total comes from the repository's own open-dispute query, so "open"
    # here means what the support queue means by it - keyed on `active_key`,
    # which is what the unique index enforces, rather than on `status`. The
    # page size is 1 because only the total is wanted; the row is discarded
    # immediately and never read, so no statement or note is even loaded.
    _row, total = await AppointmentDisputeRepository().page_open(
        page=1, page_size=1)

    col = db[APPOINTMENT_DISPUTES]
    buckets = _empty_buckets()
    scanned = 0
    complete = False
    after_id = None
    for _ in range(MAX_PAGES):
        query: dict = {"active_key": {"$exists": True}}
        if after_id is not None:
            query["_id"] = {"$gt": after_id}
        page_rows = await col.find(
            query, {"_id": 1, "created_at": 1},
        ).sort("_id", 1).limit(PAGE_SIZE).to_list(length=PAGE_SIZE)
        if not page_rows:
            complete = True
            break
        for row in page_rows:
            scanned += 1
            created = _as_utc(row.get("created_at"))
            if created is None:
                buckets["over_30d"] += 1
                continue
            buckets[_bucket(now - created)] += 1
        after_id = page_rows[-1]["_id"]
        if len(page_rows) < PAGE_SIZE:
            complete = True
            break

    dispute_problems = [p for p in index_problems
                        if p["collection"] == APPOINTMENT_DISPUTES]
    correctness_problems = [p for p in dispute_problems
                            if p["kind"] == CORRECTNESS]

    return {
        "open_total": int(total),
        "age_buckets": buckets,
        "age_buckets_cumulative": False,
        "age_scanned": scanned,
        "age_complete": bool(complete),
        # A disagreement between the queue's total and what this scan reached
        # means the two are not asking the same question any more. Reported
        # rather than resolved: guessing which number is right is how a report
        # stops being evidence.
        "count_agrees_with_queue": bool(complete and scanned == int(total)),
        "correctness_indexes_valid": not correctness_problems,
        "problems": [_problem_view(p) for p in dispute_problems],
    }


# ---------------------------------------------------------------------------
# The verdicts
# ---------------------------------------------------------------------------

# WHAT EACH VALUE MEANS, since three of the four are ways of not saying yes:
#
#   READY                every machine-verifiable check for this feature
#                        passed, and no human decision is still outstanding
#                        for it specifically.
#   NOT_READY            a machine-verifiable check failed. This is the only
#                        value that means "something is wrong".
#   UNVERIFIED_EXTERNAL  the checks passed and a decision nobody can query
#                        still stands between here and activation.
#   NOT_EVALUATED        no conclusion was reached - most often a scan that hit
#                        its page bound, so the counts are real but partial.
#                        It is NOT a pass, and the exit code treats it as such.
#
# A verdict is never READY on a truncated scan. A partial count that happens to
# contain no problems is not evidence that there are none, and the only place
# that distinction can be lost is here.

SCHEMA_VERSION = 1


def _verdict(ok: bool, *, complete: bool, reasons: list[str],
             external: bool = False) -> dict:
    if not complete:
        return {"verdict": NOT_EVALUATED, "reasons": sorted(set(reasons)
                                                            | {"scan_incomplete"})}
    if not ok:
        return {"verdict": NOT_READY, "reasons": sorted(set(reasons))}
    if external:
        return {"verdict": UNVERIFIED_EXTERNAL, "reasons": sorted(set(reasons))}
    return {"verdict": READY, "reasons": []}


def build_verdicts(sections: dict) -> dict:
    """One verdict per feature, plus the overall one that can never say yes."""
    booking = sections["booking_correctness"]
    queries = sections["query_indexes"]["by_feature"]
    expiry = sections["pending_expiry"]
    nudges = sections["outcome_nudges"]
    reminders = sections["reminders"]
    hours = sections["working_hours"]
    disputes = sections["disputes"]

    out: dict = {}

    # Booking. The preflight's own gate, unmodified. When it is true the
    # backfill and the index work have ALREADY happened, so the authorisations
    # they needed are spent rather than outstanding - which is why this one can
    # reach READY while the others in its neighbourhood cannot.
    #
    # THAT GATE IS WIDER THAN THE APPOINTMENTS COLLECTION, and deliberately so
    # upstream: `assert_appointment_booking_ready` refuses to START THE SERVICE
    # whenever any CORRECTNESS index is missing, and the one-live-complaint
    # constraint on `appointment_disputes` is a correctness index. So a missing
    # dispute guard blocks booking as well as disputes. That coupling is real -
    # booking genuinely cannot roll out while the application would refuse to
    # boot - and narrowing it here would mean this report said READY about a
    # deployment that will not start. The index names are named instead, so the
    # reason is visible rather than surprising.
    out["booking_rollout"] = _verdict(
        booking["preflight_safe_to_activate"], complete=True,
        reasons=([f"failed_gate:{g}" for g in booking["failed_gates"]]
                 + [f"missing_correctness_index:{p['name']}"
                    for p in booking["correctness_problems"]]))

    # Expiry.
    expiry_reasons = []
    if not queries["pending_expiry"]["present"]:
        expiry_reasons.append("missing_query_index:appointment_pending_expiry")
    undecided = expiry["legacy_treatment_undecided"]
    if undecided:
        expiry_reasons.append("legacy_rows_awaiting_policy")
    out["expiry_activation"] = _verdict(
        not [r for r in expiry_reasons if r.startswith("missing_query_index")],
        complete=expiry["missing_expires_at_complete"] and not expiry["age_truncated"],
        reasons=expiry_reasons,
        external=undecided)

    # Outcome nudges.
    nudge_reasons = []
    if not queries["outcome_queue"]["present"]:
        nudge_reasons.append("missing_query_index:appointment_confirmed_outcome")
    if not nudges["activation_instant_configured"]:
        nudge_reasons.append("activation_instant_not_configured")
    out["outcome_nudges_activation"] = _verdict(
        not [r for r in nudge_reasons
             if r.startswith("missing_query_index")],
        complete=True,
        reasons=nudge_reasons,
        external=not nudges["activation_instant_configured"])

    # Reminders.
    reminder_reasons = []
    if not queries["reminder_scheduling"]["present"]:
        reminder_reasons.append(
            "missing_query_index:appointment_confirmed_reminder")
    if not reminders["strict_lock_wired"]:
        # A fail-open lock here means every worker dispatches the same batch to
        # the same people at the same moment. It is a machine-verifiable NO.
        reminder_reasons.append("scheduler_not_using_fail_closed_lock")
    out["reminders_activation"] = _verdict(
        not reminder_reasons, complete=True, reasons=reminder_reasons)

    # Working hours. Enforcement rejects a booking outside a stored schedule,
    # so a lawyer with no schedule becomes unbookable the moment it is on.
    hours_reasons = []
    if hours["unconfigured"]:
        hours_reasons.append("lawyers_without_a_schedule")
    if hours["upcoming_for_unconfigured_lawyer"]:
        hours_reasons.append("upcoming_bookings_for_unconfigured_lawyers")
    if hours["upcoming_outside_schedule"]:
        hours_reasons.append("upcoming_bookings_outside_stored_schedule")
    if hours["upcoming_unassessable"]:
        hours_reasons.append("upcoming_bookings_cannot_be_assessed")
    out["working_hours_enforcement"] = _verdict(
        not hours_reasons,
        complete=(hours["eligible_complete"] and hours["schedules_complete"]
                  and hours["bookings_complete"]),
        reasons=hours_reasons)

    # Disputes.
    dispute_reasons = []
    if not disputes["correctness_indexes_valid"]:
        dispute_reasons.append(
            "missing_correctness_index:uniq_active_appointment_dispute")
    if not queries["disputes"]["present"]:
        dispute_reasons.append("missing_query_index:appointment_dispute_queue")
    if not disputes["count_agrees_with_queue"]:
        dispute_reasons.append("open_dispute_counts_disagree")
    out["dispute_workflow"] = _verdict(
        not dispute_reasons, complete=disputes["age_complete"],
        reasons=dispute_reasons)

    # Overall. NEVER READY.
    #
    # The freeze and the restore are the two gates whose absence is invisible
    # in the data: a database with no booking traffic and a database that is
    # frozen look identical, and an untested backup and a good one look
    # identical until the restore. So the best this can report is that nothing
    # it CAN see says no - which is a different sentence from "go", and is
    # written as a different sentence everywhere it appears.
    blocking = sorted(name for name in _FEATURE_VERDICTS
                      if out[name]["verdict"] not in (READY, UNVERIFIED_EXTERNAL))
    out["overall_production_go"] = {
        "verdict": NOT_READY if blocking else UNVERIFIED_EXTERNAL,
        "reasons": (blocking or
                    ["awaiting_external_evidence:booking_write_freeze_rehearsed",
                     "awaiting_external_evidence:backup_and_restore_rehearsed"]),
    }
    return out


def manual_gates() -> dict:
    """The gates, always unverified. There is no argument that changes this."""
    return {name: {"verdict": UNVERIFIED_EXTERNAL, "why": why}
            for name, why in MANUAL_GATES}


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------

async def audit(db, endpoints: list[str], database: str,
                now: datetime | None = None) -> dict:
    """Every section, once, against one pinned instant.

    Pinned so the sections agree with each other: a reminder window measured
    three seconds after the expiry deadlines were counted describes a slightly
    different system, and the reader has no way to see that it did.
    """
    now = now or datetime.now(timezone.utc)

    booking, query_indexes = await audit_booking(now)
    index_problems = booking["correctness_problems"] + [
        state["problem"] for state in query_indexes["by_feature"].values()
        if state["problem"]]

    sections = {
        "booking_correctness": booking,
        "query_indexes": query_indexes,
        "pending_expiry": await audit_expiry(db, now),
        "outcome_nudges": await audit_outcome_nudges(now),
        "reminders": await audit_reminders(now),
        "working_hours": await audit_working_hours(db, now),
        "disputes": await audit_disputes(db, now, index_problems),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        # The target, as identity and nothing else. These come from
        # `parsed_endpoints`, which raises on a string it cannot parse, so an
        # unparseable URI is refused before connecting rather than echoed -
        # a malformed URI being exactly what a naive redactor leaks on.
        "endpoints": list(endpoints),
        "database": database,
        "measured_at": now.isoformat(),
        "sections": sections,
        "verdicts": build_verdicts(sections),
        "manual_gates": manual_gates(),
    }


def exit_code_for(report: dict) -> int:
    """0 only when every machine-verifiable verdict is a pass.

    UNVERIFIED_EXTERNAL passes here and NOT_EVALUATED does not, which is the
    whole distinction: one is a decision somebody still has to take, the other
    is a question this run did not answer. Treating the second as a pass would
    make a truncated scan look like a clean one.
    """
    for name in _FEATURE_VERDICTS:
        if report["verdicts"][name]["verdict"] not in (
                READY, UNVERIFIED_EXTERNAL):
            return EXIT_NO_GO
    return EXIT_OK


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render(report: dict) -> str:
    """The human-readable report.

    THE HEADLINE IS THE VERDICT, NOT THE EXIT CODE. A reader who sees a wall of
    zeroes and a process that exited 0 will conclude they may proceed; the exit
    code means "nothing I can check says no", and the two sentences are not the
    same. So the last thing printed always says which one this is.
    """
    lines: list[str] = []
    add = lines.append

    add("APPOINTMENT ACTIVATION AUDIT (read-only)")
    add(f"  endpoints   : {', '.join(report['endpoints'])}")
    add(f"  database    : {report['database']}")
    add(f"  measured at : {report['measured_at']}")
    add("")

    s = report["sections"]

    b = s["booking_correctness"]
    add("1. BOOKING CORRECTNESS")
    for key in ("correctness_indexes_valid", "active_rows_usable",
                "active_rows_slotted", "no_lawyer_or_client_overlap",
                "no_idempotency_collision", "obsolete_index_absent",
                "preflight_safe_to_activate"):
        add(f"   {'PASS' if b[key] else 'FAIL'}  {key}")
    add(f"   rows needing backfill : {b['rows_needing_backfill']}")
    add(f"   rows blocking a build : {b['build_blocking_rows']}")
    for code, count in sorted(b["problem_counts"].items()):
        add(f"   problem: {code} = {count}")
    add("")

    add("2. QUERY INDEXES (performance only - none of these makes a booking wrong)")
    for feature, state in s["query_indexes"]["by_feature"].items():
        mark = "PRESENT" if state["present"] else "MISSING"
        add(f"   {mark:8} {feature} -> {state['index']}")
    add("")

    e = s["pending_expiry"]
    add("3. PENDING EXPIRY (nothing was expired)")
    add(f"   pending total                : {e['pending_total']}")
    add(f"   missing expires_at           : {e['missing_expires_at']}"
        f"{'' if e['missing_expires_at_complete'] else ' (PARTIAL SCAN)'}")
    add(f"   past a stored deadline       : {e['currently_expired_dated']}")
    add(f"   past a derived deadline      : {e['currently_expired_legacy']}")
    add(f"   unassessable legacy rows     : {e['legacy_unassessable']}")
    add(f"   already past their start     : {e['already_past_scheduled_start']}")
    add(f"   age (disjoint buckets)       : {e['age_buckets']}")
    if e["legacy_treatment_undecided"]:
        add("   legacy-row treatment is UNDECIDED - see the manual gates")
    add("")

    n = s["outcome_nudges"]
    add("4. OUTCOME NUDGES (nobody was notified)")
    add(f"   outstanding (CUMULATIVE)     : {n['outstanding']}")
    add(f"   scheduler flag               : "
        f"{'ENABLED' if n['enabled'] else 'disabled'}")
    add(f"   fixed activation instant     : "
        f"{'configured' if n['activation_instant_configured'] else 'MISSING'}")
    add(f"   batch size                   : {n['batch_size']}")
    add("")

    r = s["reminders"]
    add("5. REMINDERS (nothing was dispatched)")
    add(f"   due now                      : {r['due']}")
    add(f"   scheduler flag               : "
        f"{'ENABLED' if r['enabled'] else 'disabled'}")
    add(f"   interval / batch             : {r['interval_minutes']}m / "
        f"{r['batch_size']}")
    add(f"   fail-closed lock wired       : "
        f"{'yes' if r['strict_lock_wired'] else 'NO'}")
    add("")

    w = s["working_hours"]
    add("6. WORKING HOURS (no default schedule was assumed for anybody)")
    add(f"   eligible lawyers             : {w['eligible_lawyers']}")
    add(f"   with an explicit schedule    : {w['configured']}")
    add(f"   without one                  : {w['unconfigured']}")
    add(f"   upcoming active bookings     : {w['upcoming_active_bookings']}")
    add(f"   outside a stored schedule    : {w['upcoming_outside_schedule']}")
    add(f"   for an unconfigured lawyer   : "
        f"{w['upcoming_for_unconfigured_lawyer']}")
    add(f"   enforcement flag             : "
        f"{'ENABLED' if w['enforced'] else 'disabled'}")
    add("")

    d = s["disputes"]
    add("7. DISPUTES (no ids, statements or support notes are read)")
    add(f"   open                         : {d['open_total']}")
    add(f"   age (disjoint buckets)       : {d['age_buckets']}")
    add(f"   correctness index valid      : "
        f"{'yes' if d['correctness_indexes_valid'] else 'NO'}")
    add("")

    add("8. MANUAL GATES - NOT CHECKED BY THIS TOOL AND NOT CHECKABLE BY IT")
    for name, gate in report["manual_gates"].items():
        add(f"   {gate['verdict']}  {name}")
    add("   No argument to this command marks any of these satisfied.")
    add("")

    add("VERDICTS")
    for name, value in report["verdicts"].items():
        add(f"   {value['verdict']:20} {name}")
        for reason in value["reasons"]:
            add(f"        - {reason}")
    add("")

    overall = report["verdicts"]["overall_production_go"]["verdict"]
    if overall == NOT_READY:
        add("THIS IS NOT A GO. A machine-verifiable check failed; see above.")
    else:
        add("THIS IS NOT A GO. Every check this tool can perform passed, and "
            "the booking-write freeze and a proven backup restore remain "
            "unverified by anything here. Production readiness needs that "
            "evidence from outside this tool.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.db.appointment_activation_audit",
        description=("Read-only appointment activation audit. Changes "
                     "nothing, activates nothing, notifies nobody."),
    )
    p.add_argument(
        "--database", required=True,
        help="EXACT database name to audit. Named explicitly rather than "
             "taken from application settings, so this cannot inherit "
             "whichever database a stray environment happens to point at.")
    p.add_argument(
        "--confirm-database", required=True,
        help="Repeat the database name exactly. Required even though this "
             "writes nothing: its OUTPUT is a claim about one named target, "
             "and a claim about the wrong one is worse than no claim.")
    p.add_argument(
        "--confirm-endpoint", action="append", required=True,
        metavar="scheme://host[:port]",
        help="Repeat each endpoint the connection string points at, once per "
             "host for a replica set. SCHEME, HOST AND PORT ALL COUNT: two "
             "instances on one host differing only by port is how staging and "
             "production end up side by side.")
    p.add_argument(
        "--json", action="store_true",
        help="Emit the report as JSON instead of text.")
    return p

# There is deliberately no --uri, because arguments reach shell history and
# process listings. There is no write-mode argument of any kind, because there
# is nothing here to apply. And there is NO FLAG FOR ANY MANUAL GATE: a flag
# that marked the freeze rehearsed would let this report claim, in writing and
# after the fact, that somebody had verified something nothing here can see.
#
# The absence of those option strings is asserted against this parser rather
# than against the file, because a comment that merely mentions one would fail
# a text search while changing nothing about what the command accepts.


def _authorise(args, uri, out) -> tuple[int | None, list[str]]:
    """Every reason to refuse, checked BEFORE the driver is constructed.

    Returns (exit code to stop on or None, the endpoints). Ordered so the
    operator is told the first thing wrong rather than the last.
    """
    if args.confirm_database != args.database:
        out("REFUSED: --confirm-database does not match --database. Nothing "
            "was read.")
        return EXIT_FAILURE, []

    try:
        actual = parsed_endpoints(uri)
    except UnparseableTarget:
        out(f"REFUSED: the {URI_ENV_VAR} connection string does not name a "
            "host that can be confirmed. Nothing was read.")
        return EXIT_FAILURE, []

    try:
        claimed = sorted({normalise_endpoint(e) for e in args.confirm_endpoint
                          if e.strip()})
    except UnparseableTarget:
        # The reason is not echoed. It is derived from operator input, and the
        # one input most likely to be malformed is a URI pasted by mistake into
        # the wrong argument - which would carry a password.
        out("REFUSED: --confirm-endpoint is not a usable endpoint. Expected "
            "scheme://host[:port]. Nothing was read.")
        return EXIT_FAILURE, []

    if claimed != actual:
        # The real endpoints are NOT echoed back. Naming them in the refusal
        # would turn a wrong guess into a way to read the target out of the
        # error message.
        out("REFUSED: --confirm-endpoint does not match the endpoints in "
            f"{URI_ENV_VAR}. Check which environment that variable points at, "
            "and remember that the port is part of the endpoint. Nothing was "
            "read.")
        return EXIT_FAILURE, []

    return None, actual


async def _default_connect(uri: str, database: str):
    """(client, database name) for the named target. Replaced in tests."""
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(
        uri, tz_aware=True, tzinfo=timezone.utc, serverSelectionTimeoutMS=5000)
    return client, database


async def run(argv, env, connect=_default_connect, out=print) -> int:
    """The command, as a function, so it can be tested without a subprocess."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit:
        # argparse has already printed why. A missing or malformed argument is
        # the audit not running, which is EXIT_FAILURE and never EXIT_NO_GO:
        # "you typed it wrong" must not be reported as "the database is bad".
        return EXIT_FAILURE

    uri = (env or {}).get(URI_ENV_VAR)
    if not uri:
        out(f"REFUSED: {URI_ENV_VAR} is not set. The connection string is read "
            "from that variable and is deliberately not accepted as an "
            "argument, because arguments reach shell history and process "
            "listings.")
        return EXIT_FAILURE

    refusal, endpoints = _authorise(args, uri, out)
    if refusal is not None:
        return refusal

    try:
        client, database = await connect(uri, args.database)
    except Exception as exc:
        # The class only. A driver error's message carries the URI and
        # sometimes the credentials, and this output goes into tickets.
        out(f"FAILED: could not connect (error_class={type(exc).__name__}).")
        return EXIT_FAILURE

    try:
        with _Bound(client, database) as db:
            report = await audit(db, endpoints, database)
    except AuditWriteAttempted as exc:
        # Loud, and its own exit code. This means a service reached for
        # something that is not a read - the audit did not complete, and its
        # partial numbers are not a result.
        out(f"FAILED: the audit attempted a non-read operation. {exc}")
        return EXIT_FAILURE
    except Exception as exc:
        out(f"FAILED: the audit could not complete "
            f"(error_class={type(exc).__name__}).")
        return EXIT_FAILURE
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            maybe = close()
            if asyncio.iscoroutine(maybe):
                await maybe

    if args.json:
        out(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        out(render(report))
    return exit_code_for(report)


def main(argv=None) -> int:
    return asyncio.run(
        run(argv if argv is not None else sys.argv[1:], os.environ))


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
