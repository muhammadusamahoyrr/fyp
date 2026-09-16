"""Read-only pre-activation check for the appointment slot contract.

WHAT THIS IS FOR

The overlap guarantee is two unique multikey indexes over `occupied_slots`.
Building them on a live collection fails outright if the data already violates
them, and it is worth knowing WHICH rows violate them before a maintenance
window rather than during one. This answers that against a running database
without changing anything.

IT WRITES NOTHING. Not the indexes it says are missing, not the obsolete one it
recommends dropping, and not the `occupied_slots` it reports as absent. All of
it is printed as commands for a person to read, decide on, and run — because an
index build on a large collection is a capacity event, a drop is irreversible
without another build, and a preflight that fixed things itself would destroy
the evidence used to approve the fix.

    python -m app.db.appointment_slot_preflight

WHAT IT DOES NOT COVER

Index readiness is a necessary condition, not permission. The activation
sequence is ordered, and each step is where it is for a reason:

    1.  keep the OLD app running                (it is what still serves)
    2.  freeze booking writes
    3.  preflight (this) — inspect
    4.  repair the rows it reports
    5.  backfill_occupied_slots(dry_run=True)   — review the plan
    6.  backfill_occupied_slots(dry_run=False)  — once approved
    7.  create_appointment_correctness_indexes()
    8.  validate_appointment_indexes()          — must be empty
    9.  drop the obsolete uniq_pending_slot
    10. preflight again: safe_to_activate must be true
    11. deploy the NEW app (its startup re-checks and refuses if not)
    12. reopen booking

THE FREEZE IS NOT CAUTION, IT IS THE POINT (2). Backfill first and deploy
later, without a freeze, and any booking created in between carries no
`occupied_slots` at all — so it is invisible to the very indexes being built to
catch it, and escapes overlap protection permanently rather than briefly.

THE OLD APP KEEPS SERVING UNTIL 11 (1). The new app's startup refuses to boot
while the contract does not hold, so deploying it before the indexes exist
takes the service down rather than bringing it up.

THE OBSOLETE DROP COMES AFTER THE NEW INDEXES ARE VALIDATED (9, not earlier).
`uniq_pending_slot` is weak — exact-start-only and PENDING-scoped — but while
it is the only guard present it is the only thing preventing an identical
double booking. Dropping it at step 4, as an earlier version of this sequence
did, leaves a window with NO overlap protection at all, during a window that
exists precisely to add some.

OUTPUT IS SANITISED. Counts and appointment ids only. No client or lawyer
names, notes, meeting links or case descriptions, and no raw driver errors —
this output goes into tickets and chat logs, and an appointment's notes are
privileged. Ids are included because an operator has to be able to find the
rows; everything identifying a PERSON is not.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from app.db.appointment_index_spec import (
    ACTIVE_STATUSES,
    APPOINTMENT_INDEX_REQUIREMENTS,
    APPOINTMENTS,
    OBSOLETE_INDEXES,
)
from app.db.v2_index_spec import IndexSpec
from app.services.appointment_slots import (
    SLOT_MINUTES,
    alignment_error,
    duration_error,
    occupied_slots,
)

# A cap on how many offending ids are listed per category. A preflight that
# prints fifty thousand ids is one nobody reads; the COUNT is always exact.
_MAX_IDS = 25


def _create_command(spec: IndexSpec) -> str:
    options: list[str] = [f'name: "{spec.name}"']
    if spec.unique:
        options.append("unique: true")
    if spec.sparse:
        options.append("sparse: true")
    if spec.partial_filter:
        options.append(
            f"partialFilterExpression: {json.dumps(dict(spec.partial_filter))}")
    keys = ", ".join(f'"{f}": {d}' for f, d in spec.keys)
    return (f'db.{spec.collection}.createIndex({{{keys}}}, '
            f'{{{", ".join(options)}}})')


def _finding(code: str, why: str, ids: list[str], total: int) -> dict:
    return {
        "code": code,
        "why": why,
        "count": total,
        "appointment_ids": ids[:_MAX_IDS],
        "truncated": total > len(ids[:_MAX_IDS]),
    }


def _as_utc(value):
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# How a stored `occupied_slots` compares to the slots its own times imply.
SLOTS_OK = "ok"
SLOTS_MISSING = "missing"
SLOTS_MALFORMED = "malformed"
SLOTS_WRONG = "wrong"


def classify_slots(stored, expected: list[datetime]) -> str:
    """Judge a stored slot array WITHOUT discarding the parts that do not parse.

    The first version of this filtered non-datetime entries out before
    comparing, which made a row like `[10:00, 10:30, "garbage"]` compare EQUAL
    to `[10:00, 10:30]` and pass as correct. That is the wrong direction to be
    wrong in: an unreadable entry is evidence the row was written by something
    that does not agree with this code about what a slot is, and a preflight
    whose job is to find exactly that should not be the thing that hides it.

    So anything that is not a datetime makes the row MALFORMED, and malformed
    is reported rather than silently repaired or ignored.
    """
    if not stored:
        return SLOTS_MISSING
    if not isinstance(stored, (list, tuple)):
        return SLOTS_MALFORMED
    if any(not isinstance(s, datetime) for s in stored):
        return SLOTS_MALFORMED
    observed = sorted(_as_utc(s).replace(tzinfo=None) for s in stored)
    if observed != sorted(e.replace(tzinfo=None) for e in expected):
        return SLOTS_WRONG
    return SLOTS_OK


async def inspect_rows(db) -> list[dict]:
    """Every active appointment that would block or defeat the indexes.

    Reads the active rows once and answers every question from that one pass,
    rather than running a query per category: the categories overlap heavily
    (a row with no `scheduled_at` is also a row with no valid slots) and seven
    scans of a live collection to answer one question is a cost with no benefit.
    """
    col = db[APPOINTMENTS]

    missing_times: list[str] = []
    misaligned: list[str] = []
    bad_duration: list[str] = []
    missing_slots: list[str] = []
    wrong_slots: list[str] = []
    malformed_slots: list[str] = []
    end_mismatch: list[str] = []
    counts = {"missing_times": 0, "misaligned": 0, "bad_duration": 0,
              "missing_slots": 0, "wrong_slots": 0, "malformed_slots": 0,
              "end_at_mismatch": 0}

    cursor = col.find(
        {"status": {"$in": list(ACTIVE_STATUSES)}},
        # PROJECTION IS PART OF THE SANITISATION. The notes, the meeting link
        # and the party names are never read, so they cannot be leaked by a
        # later change to how this is printed.
        {"_id": 1, "scheduled_at": 1, "end_at": 1, "duration_minutes": 1,
         "occupied_slots": 1, "lawyer_id": 1, "client_id": 1, "status": 1},
    )

    async for row in cursor:
        appt_id = str(row.get("_id"))
        start = _as_utc(row.get("scheduled_at"))
        end = _as_utc(row.get("end_at"))
        duration = row.get("duration_minutes")

        if start is None or end is None:
            counts["missing_times"] += 1
            missing_times.append(appt_id)
            continue

        if alignment_error(start) is not None:
            counts["misaligned"] += 1
            misaligned.append(appt_id)

        if not isinstance(duration, int) or duration_error(duration) is not None:
            counts["bad_duration"] += 1
            bad_duration.append(appt_id)
            # Without a usable duration the expected slots cannot be computed,
            # so this row is not also judged against them.
            continue

        # `end_at` is STORED, not derived on read, and it is what the
        # completion rule compares against (`transitions.timing_error`). So a
        # row whose end does not match its own start plus duration is telling
        # two different stories about when it finishes: the slots it claims
        # come from the duration, while whether it may be completed comes from
        # `end_at`. One of them is wrong and this cannot tell which, so the row
        # is reported rather than silently recomputed.
        expected_end = start + timedelta(minutes=duration)
        if end != expected_end:
            counts["end_at_mismatch"] += 1
            end_mismatch.append(appt_id)

        verdict = classify_slots(row.get("occupied_slots"),
                                 occupied_slots(start, duration))
        if verdict == SLOTS_MISSING:
            counts["missing_slots"] += 1
            missing_slots.append(appt_id)
        elif verdict == SLOTS_MALFORMED:
            counts["malformed_slots"] += 1
            malformed_slots.append(appt_id)
        elif verdict == SLOTS_WRONG:
            counts["wrong_slots"] += 1
            wrong_slots.append(appt_id)

    return [
        _finding("active_missing_times",
                 "active appointment with no scheduled_at or no end_at — it "
                 "cannot be given slots, and no index can constrain it",
                 missing_times, counts["missing_times"]),
        _finding("misaligned_start",
                 f"start is not on a {SLOT_MINUTES}-minute UTC boundary — two "
                 "such appointments can overlap in real time while sharing no "
                 "indexed instant, so the guard silently does not apply",
                 misaligned, counts["misaligned"]),
        _finding("duration_not_whole_slots",
                 f"duration is not a multiple of {SLOT_MINUTES} minutes — same "
                 "consequence: real overlap, no shared slot",
                 bad_duration, counts["bad_duration"]),
        _finding("missing_occupied_slots",
                 "active appointment carrying no occupied_slots — invisible to "
                 "the unique indexes, so it neither claims its time nor "
                 "collides with anyone who takes it",
                 missing_slots, counts["missing_slots"]),
        _finding("incorrect_occupied_slots",
                 "stored occupied_slots do not match the slots its own "
                 "scheduled_at and duration imply — it is claiming the wrong "
                 "hours",
                 wrong_slots, counts["wrong_slots"]),
        _finding("end_at_mismatch",
                 "end_at is not scheduled_at plus duration_minutes — the row "
                 "disagrees with itself about when it finishes, and the "
                 "completion rule reads end_at while the slot claim comes from "
                 "the duration",
                 end_mismatch, counts["end_at_mismatch"]),
        _finding("malformed_occupied_slots",
                 "occupied_slots contains an entry that is not a datetime — "
                 "the row was written by something that does not agree with "
                 "this code about what a slot is, and its claim cannot be "
                 "trusted in either direction",
                 malformed_slots, counts["malformed_slots"]),
    ]


async def find_overlaps(db) -> list[dict]:
    """Active appointments that already share a party and a half-hour.

    These are what make the index build FAIL, so they are the rows an operator
    has to resolve first. Computed by aggregation rather than in Python: the
    comparison is over `occupied_slots`, which is exactly what the index will
    compare, so this asks the same question the build will ask.

    A row with no `occupied_slots` cannot appear here — it is reported by
    `inspect_rows` instead. Both matter, and they are different problems: this
    one blocks the build, that one passes it while protecting nothing.
    """
    col = db[APPOINTMENTS]
    out: list[dict] = []

    for party in ("lawyer_id", "client_id"):
        pipeline = [
            {"$match": {"status": {"$in": list(ACTIVE_STATUSES)},
                        "occupied_slots": {"$type": "array", "$ne": []}}},
            {"$unwind": "$occupied_slots"},
            {"$group": {"_id": {"party": f"${party}", "slot": "$occupied_slots"},
                        "ids": {"$addToSet": "$_id"}}},
            # DISTINCT APPOINTMENTS, not unwound entries.
            #
            # `{"$sum": 1}` counted rows produced by `$unwind`, so ONE row whose
            # occupied_slots contained the same instant twice — exactly the
            # malformed shape `classify_slots` now reports — produced a group of
            # size two and was announced as an overlap between an appointment
            # and itself. That is a preflight inventing blocking work during a
            # maintenance window, which is worse than missing something: the
            # operator goes looking for a clash that does not exist.
            #
            # `$addToSet` already dedupes ids, so the size of that set is the
            # number of genuinely distinct appointments sharing the slot.
            {"$match": {"$expr": {"$gt": [{"$size": "$ids"}, 1]}}},
            # Only the ids travel out of the aggregation. The party id is
            # dropped here deliberately: knowing WHICH appointments clash is
            # enough to resolve them, and the appointment ids lead an operator
            # to the parties without this output naming them.
            {"$project": {"_id": 0, "ids": 1}},
        ]
        clashes = [doc async for doc in col.aggregate(pipeline)]
        ids = sorted({str(i) for doc in clashes for i in doc["ids"]})
        out.append(_finding(
            f"overlapping_active_{party}",
            f"two or more ACTIVE appointments share a {party} and a half-hour "
            "slot — the unique index cannot be built until these are resolved",
            ids, len(ids)))

    return out


async def find_idempotency_collisions(db) -> dict:
    """Existing (client_id, idempotency_key) pairs that are already duplicated.

    Nothing writes these before this change, so a non-empty result means the
    field is in use by something unexpected — which is worth knowing before a
    unique index makes it fatal.
    """
    col = db[APPOINTMENTS]
    pipeline = [
        {"$match": {"idempotency_key": {"$type": "string"}}},
        {"$group": {"_id": {"client_id": "$client_id",
                            "idempotency_key": "$idempotency_key"},
                    "ids": {"$addToSet": "$_id"}, "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
        # The KEY ITSELF IS NOT PROJECTED. It is client-generated and may carry
        # anything the client put in it.
        {"$project": {"_id": 0, "ids": 1}},
    ]
    clashes = [doc async for doc in col.aggregate(pipeline)]
    ids = sorted({str(i) for doc in clashes for i in doc["ids"]})
    return _finding(
        "idempotency_key_collisions",
        "the same client already has more than one appointment under one "
        "idempotency_key — the unique index would reject the collection",
        ids, len(ids))


async def preflight() -> dict:
    """Everything an operator needs before the activation window. Read-only."""
    from app.db.indexes import validate_appointment_indexes
    from app.db.mongodb import get_database

    db = get_database()
    problems = await validate_appointment_indexes()

    obsolete: list[dict] = []
    for collection, name, why in OBSOLETE_INDEXES:
        try:
            info = await db[collection].index_information()
        except Exception as exc:  # noqa: BLE001
            obsolete.append({"collection": collection, "name": name,
                             "present": None,
                             "why": ("could not be checked "
                                     f"(error_class={type(exc).__name__})")})
            continue
        if name in info:
            obsolete.append({"collection": collection, "name": name,
                             "present": True, "why": why})

    rows = await inspect_rows(db)
    overlaps = await find_overlaps(db)
    idempotency = await find_idempotency_collisions(db)

    findings = overlaps + rows + [idempotency]
    blocking = [f for f in findings if f["count"] and f["code"].startswith(
        ("overlapping_active_", "idempotency_key_collisions"))]

    by_name = {s.name: s for s in APPOINTMENT_INDEX_REQUIREMENTS}
    fixes = [_create_command(by_name[p.name])
             for p in problems if p.name in by_name]
    drops = [f'db.{o["collection"]}.dropIndex("{o["name"]}")'
             for o in obsolete if o.get("present")]

    # THE GATES, each named, so a red line says which one.
    #
    # Reporting findings and leaving the operator to add them up is how a
    # window gets opened on a database that is not ready: the numbers are all
    # there, and one of them is non-zero halfway down a long report. The
    # judgement is made here instead, and it is made CONSERVATIVELY — every
    # gate must be affirmatively clean, so a check that could not run leaves
    # `safe_to_activate` false rather than absent.
    #
    # `uniq_pending_slot` is a gate rather than a note because it is narrower
    # than the guard that replaces it and still refuses writes the new rules
    # allow: exact-start-only and PENDING-scoped, it rejects a second PENDING
    # booking at the same lawyer and instant even where the new indexes would
    # not, and a keyless retry is one such write.
    #
    # It does NOT necessarily break an idempotent retry — a retry that carries
    # a key is replayed before the duplicate-key error is ever interpreted, so
    # it succeeds regardless of which index raised it. An earlier version of
    # this comment claimed otherwise; that was measured against an earlier
    # revision of the service, before the replay check was moved ahead of the
    # constraint mapping, and it was not re-checked afterwards.
    #
    # It is still a gate because leaving it in place means production is
    # enforcing two overlapping rules, one of which nothing in the code agrees
    # with any more.
    gates = {
        "indexes_valid": not problems,
        "no_overlapping_active_rows": all(
            f["count"] == 0 for f in overlaps),
        "all_active_rows_usable": all(
            f["count"] == 0 for f in rows
            if f["code"] in ("active_missing_times", "misaligned_start",
                             "duration_not_whole_slots",
                             "malformed_occupied_slots",
                             "end_at_mismatch")),
        "all_active_rows_slotted": all(
            f["count"] == 0 for f in rows
            if f["code"] in ("missing_occupied_slots",
                             "incorrect_occupied_slots")),
        "no_idempotency_collisions": idempotency["count"] == 0,
        "obsolete_indexes_absent": not any(
            o.get("present") for o in obsolete),
    }

    return {
        "database": db.name,
        "indexes_ready": not problems,
        # Not a synonym for `indexes_ready`. Indexes being valid is one of six
        # conditions, and it is the one an operator is most likely to check
        # alone and mistake for permission.
        "safe_to_activate": all(gates.values()),
        "gates": gates,
        "failed_gates": sorted(k for k, ok in gates.items() if not ok),
        "problems": [
            {"code": p.code, "collection": p.collection, "name": p.name,
             "kind": p.kind, "message": p.message}
            for p in problems
        ],
        "findings": findings,
        # Named for what it means: these ROWS stop the index build. It is not a
        # claim that activation is otherwise safe.
        "build_blocking_rows": sum(f["count"] for f in blocking),
        "rows_needing_backfill": sum(
            f["count"] for f in findings
            if f["code"] in ("missing_occupied_slots", "incorrect_occupied_slots")),
        "obsolete_present": obsolete,
        # Commands, not actions.
        "recommended_create": fixes,
        "recommended_drop": drops,
    }


def render(result: dict) -> str:
    verdict = ("SAFE TO ACTIVATE" if result.get("safe_to_activate")
               else "NOT SAFE TO ACTIVATE")
    lines = [
        f"Appointment slot preflight — database {result['database']!r}",
        "",
        "  THIS CHECK WRITES NOTHING.",
        "",
        f"  {verdict}",
    ]
    if not result.get("safe_to_activate"):
        for gate in result.get("failed_gates", []):
            lines.append(f"    failed gate: {gate}")
    lines.append("")

    if result["indexes_ready"]:
        lines.append("  INDEXES: every declared index is present and valid.")
    else:
        lines.append(f"  INDEXES NOT READY: {len(result['problems'])} problem(s).")
        for problem in result["problems"]:
            lines.append(f"    [{problem['kind']}/{problem['code']}] "
                         f"{problem['collection']}.{problem['name']}: "
                         f"{problem['message']}")

    lines += ["", "  DATA:"]
    for finding in result["findings"]:
        if not finding["count"]:
            lines.append(f"    ok   {finding['code']}: 0")
            continue
        lines.append(f"    HIT  {finding['code']}: {finding['count']}")
        lines.append(f"           {finding['why']}")
        shown = ", ".join(finding["appointment_ids"])
        suffix = " (truncated)" if finding["truncated"] else ""
        lines.append(f"           appointments: {shown}{suffix}")

    lines += [
        "",
        f"  Rows blocking the index build: {result['build_blocking_rows']}",
        f"  Rows needing backfill:         {result['rows_needing_backfill']}",
    ]

    if result["recommended_create"]:
        lines += ["", "  Create, once the blocking rows are resolved (an index",
                  "  build on a large collection is a capacity event):"]
        lines += [f"    {c}" for c in result["recommended_create"]]

    if result["obsolete_present"]:
        lines += ["", "  Obsolete indexes present. NOT dropped by this check:"]
        for entry in result["obsolete_present"]:
            lines.append(f"    {entry['collection']}.{entry['name']}")
            lines.append(f"        {entry['why']}")
        lines += ["", "  Cleanup, once reviewed:"]
        lines += [f"    {c}" for c in result["recommended_drop"]]

    lines += [
        "",
        "  ACTIVATION ORDER — every step is where it is for a reason:",
        "",
        "      1.  keep the OLD app running",
        "      2.  freeze booking writes",
        "      3.  preflight (this)",
        "      4.  repair the rows above",
        "      5.  backfill_occupied_slots(dry_run=True)   review the plan",
        "      6.  backfill_occupied_slots(dry_run=False)  once approved",
        "      7.  create_appointment_correctness_indexes()",
        "      8.  validate_appointment_indexes()          must be empty",
        "      9.  drop uniq_pending_slot",
        "      10. preflight again: safe_to_activate must be true",
        "      11. deploy the NEW app",
        "      12. reopen booking",
        "",
        "  A booking created between the backfill and the deploy carries no",
        "  occupied_slots, so it is invisible to the indexes and escapes",
        "  overlap protection permanently. That is what the freeze prevents.",
        "",
        "  The obsolete drop is step 9, NOT step 4: while it is the only guard",
        "  present it is the only thing preventing an identical double booking,",
        "  so dropping it early leaves a window with no protection at all.",
        "",
        "  The new app refuses to start while this reports NOT SAFE, so step 11",
        "  before step 7 takes the service down rather than bringing it up.",
    ]
    return "\n".join(lines) + "\n"


class AppointmentBookingNotReady(RuntimeError):
    """The booking path is live code and its guarantees are not in force."""


async def assert_appointment_booking_ready() -> None:
    """Refuse to serve bookings unless the whole contract holds. Reads only.

    WHY THIS IS THE FULL CHECK AND NOT JUST THE INDEXES

    "Do the indexes exist" is the question it is tempting to ask at startup,
    and it is not sufficient. An index can be present and valid over a
    collection whose active rows carry no `occupied_slots` at all — those rows
    are simply absent from it. Every guarantee then reads as enforced while the
    appointments that predate the backfill claim nothing, collide with nobody,
    and can be double-booked freely. The indexes would be telling the truth
    about themselves and nothing about the data.

    WHY FAIL-CLOSED

    The booking path has no feature flag. It writes slots and relies on the
    indexes from the first request after deploy, so there is no state in which
    "not ready yet" is survivable — a booking accepted while the guarantee is
    absent is a booking nobody will discover is wrong until two people arrive
    for it. Refusing to start is loud, immediate, and reversible; accepting the
    booking is none of those.

    IT REPAIRS NOTHING. It does not create the indexes it finds missing, drop
    the obsolete one, or backfill the rows it reports. A startup that fixed any
    of that would make a restart a way to establish correctness state silently,
    which is exactly what makes the current absence of a guarantee so hard to
    notice.

    COST: one pass over the active appointments, on boot. Acceptable because it
    is bounded by the ACTIVE rows rather than the collection, and because the
    alternative is booting into a state nobody has checked.
    """
    result = await preflight()
    if result["safe_to_activate"]:
        return

    failed = ", ".join(result["failed_gates"])
    hits = "; ".join(
        f"{f['code']}={f['count']}" for f in result["findings"] if f["count"])
    raise AppointmentBookingNotReady(
        "Appointment booking cannot be served: the overlap and idempotency "
        f"guarantees are not in force. Failed gates: {failed}."
        + (f" Findings: {hits}." if hits else "")
        + " NOTHING HAS BEEN CHANGED — run "
        "`python -m app.db.appointment_slot_preflight` for the full report and "
        "the operator commands, and follow the activation order it prints. Do "
        "not restart to clear this; a restart repairs nothing by design."
    )


async def backfill_occupied_slots(db, *, dry_run: bool = True) -> dict:
    """Give active appointments the slots their own times imply.

    DEFAULTS TO DRY RUN, and must be called with `dry_run=False` explicitly and
    deliberately, inside the write freeze, after the preflight is clean. It is
    dormant by design: nothing in the application calls it, and this change does
    not run it.

    Rows it will not touch, and why it refuses rather than guessing: an
    appointment with no usable `scheduled_at`, or a duration that is not a whole
    number of slots, has no correct set of slots to write. Inventing one would
    put a wrong claim into the index that then looks authoritative — worse than
    the absence the preflight already reports.
    """
    col = db[APPOINTMENTS]
    planned = 0
    skipped = 0
    written = 0

    cursor = col.find(
        {"status": {"$in": list(ACTIVE_STATUSES)}},
        {"_id": 1, "scheduled_at": 1, "duration_minutes": 1, "occupied_slots": 1},
    )
    async for row in cursor:
        start = _as_utc(row.get("scheduled_at"))
        duration = row.get("duration_minutes")
        if (start is None or not isinstance(duration, int)
                or alignment_error(start) is not None
                or duration_error(duration) is not None):
            skipped += 1
            continue

        expected = occupied_slots(start, duration)
        # The same strict judgement the preflight uses. Filtering unreadable
        # entries out before comparing would make a row carrying one compare
        # EQUAL and be skipped — so the backfill would leave in place exactly
        # the rows it exists to repair.
        if classify_slots(row.get("occupied_slots"), expected) == SLOTS_OK:
            continue

        planned += 1
        if not dry_run:
            await col.update_one({"_id": row["_id"]},
                                 {"$set": {"occupied_slots": expected}})
            written += 1

    return {"dry_run": dry_run, "planned": planned,
            "written": written, "skipped_unfixable": skipped}


async def _main() -> int:
    from app.db.mongodb import close_db, connect_db

    await connect_db()
    try:
        print(render(await preflight()))
    finally:
        await close_db()
    return 0


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(asyncio.run(_main()))
