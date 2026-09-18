"""
Demo appointments — curated seed data so the appointment screens are not blank.

WHY THIS EXISTS
---------------
The appointments collection was empty (0 rows against 52 cases), so the client
Overview tile, the tracking Appointments page and the lawyer calendar all
rendered nothing during a demo. This fills them with a realistic spread —
past and future, across statuses and modes — against the demo lawyer roster.

Like seed_demo_lawyers.py, every row carries `is_demo_seed: True`, so demo data
is one query away from being listed or removed and can never be mistaken for a
real booking or for a leftover test fixture:

    demo seed    is_demo_seed: True — curated, intentional
    test fixture @example.com / null email — deleted by purge_test_fixtures.py
    real booking neither marker

BEFORE ANY PUBLIC DEPLOYMENT remove these: `--remove`. A fictional consultation
on a real lawyer's calendar is worse than an empty one.

WHAT CHANGED, AND WHY IT MATTERED
---------------------------------
This script predated the slot contract and had drifted into writing rows the
application can no longer produce:

  * 45-MINUTE DURATIONS. Three plan entries used them. A part-slot appointment
    occupies {10:00, 10:30} while one at 10:45 occupies {10:45, 11:15} — they
    overlap for a real quarter of an hour and share no indexed instant, so the
    unique index silently stops catching the clash.
  * NO `occupied_slots`. The unique indexes compare that field, so a row
    without it is invisible to them: it neither claims its hours nor collides
    with anyone who takes them. Seeding one after activation puts a permanent
    hole in the overlap guarantee.
  * NO `schedule_version`. Rescheduling and confirming both pin it.
  * NO TARGET CONFIRMATION. It read `MONGODB_URL` and defaulted `DB_NAME` to
    `attorney_ai` — the production name — then wrote. Nothing asked which
    server that was.

WHAT IT REFUSES NOW
-------------------
`--apply` REFUSES ONCE THE APPOINTMENT CORRECTNESS INDEXES EXIST. These are
fictional consultations; once the overlap guarantee is live, a database holding
them is one where a real lawyer's calendar contains invented bookings and the
index is enforcing them. Demo seeding belongs to a pre-activation database, and
the check is the presence of the indexes rather than a database name, because
a name identifies nothing on its own.

`--apply` and `--remove` require the endpoint AND the database to be confirmed
before connecting. An endpoint is scheme + host + port: two Mongo instances on
one host differing only by port is how staging and production end up side by
side. The confirmation uses the same parser as the backfill CLI, so the two
cannot disagree about what a target is.

`--list` and the dry run read only, and need no confirmation.

USAGE
-----
    cd backend
    ./venv/Scripts/python.exe scripts/seed_demo_appointments.py            # dry run
    ./venv/Scripts/python.exe scripts/seed_demo_appointments.py --list

    ./venv/Scripts/python.exe scripts/seed_demo_appointments.py --apply \\
        --confirm-database attorney_ai_dev \\
        --confirm-endpoint mongodb://localhost:27017

    ./venv/Scripts/python.exe scripts/seed_demo_appointments.py --remove \\
        --confirm-database attorney_ai_dev \\
        --confirm-endpoint mongodb://localhost:27017

    ... --client someone@example.com     # default: the non-fixture client with
                                         # the most cases
"""
import argparse
import asyncio
import os
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# Reused, never reimplemented. The slot arithmetic, the duration rule and the
# endpoint parser all live where the application keeps them, so this script
# cannot drift into seeding rows the application would reject.
from app.db.appointment_backfill_cli import (  # noqa: E402
    UnparseableTarget,
    normalise_endpoint,
    parsed_endpoints,
    redact,
)
from app.db.appointment_index_spec import (  # noqa: E402
    APPOINTMENT_INDEX_REQUIREMENTS,
    CORRECTNESS,
)
from app.services.appointment_slots import (  # noqa: E402
    alignment_error,
    duration_error,
    occupied_slots,
)

DEMO_MARKER = "is_demo_seed"
FIXTURE_EMAIL = re.compile(r"@example\.(com|org|net)$", re.I)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3

# (days from now, hour UTC, duration, status, mode, note)
# Past rows are completed, the near future is confirmed, the far future pending
# — so the calendar shows history, a settled booking and an open request.
#
# EVERY DURATION IS A WHOLE NUMBER OF HALF-HOURS. Three entries used 45 minutes,
# which the application refuses and which defeats the overlap index outright.
PLAN = [
    (-21, 10, 60, "completed", "in_person",
     "Initial consultation — reviewed the FIR and advised on bail options."),
    (-14,  14, 30, "completed", "video",
     "Follow-up on documents required for the next hearing."),
    (-6,   11, 60, "completed", "in_person",
     "Went through the draft petition line by line."),
    (-2,   15, 30, "cancelled", "phone",
     "Client asked to move this; rescheduled to the following week."),
    (2,     9, 60, "confirmed", "video",
     "Pre-hearing briefing. Bring the original agreement."),
    (5,    16, 30, "confirmed", "phone",
     "Quick call to confirm the witness list."),
    (9,    11, 60, "pending", "in_person",
     "Requested: full case review ahead of the trial date."),
    (16,   13, 90, "pending", "video",
     "Requested: discuss settlement options with the other party."),
]

# Statuses that hold a slot claim, matching the partial filter on the unique
# indexes.
ACTIVE = ("pending", "confirmed")


def validate_plan() -> list[str]:
    """Every plan entry the application would refuse. Pure.

    Checked here rather than trusted, so a future edit that reintroduces a
    45-minute consultation fails before it reaches a database.
    """
    problems = []
    for index, (_days, hour, mins, status, _mode, _note) in enumerate(PLAN):
        bad = duration_error(mins)
        if bad:
            problems.append(f"PLAN[{index}] duration {mins}: {bad}")
        if not 0 <= hour <= 23:
            problems.append(f"PLAN[{index}] hour {hour} is not a valid hour")
        if status not in ("pending", "confirmed", "completed", "cancelled", "no_show"):
            problems.append(f"PLAN[{index}] unknown status {status!r}")
    return problems


async def active_correctness_indexes(appts) -> list[str]:
    """Which appointment correctness indexes already exist on this collection.

    THE ACTIVATION TEST, and it is deliberately not a database name. A name
    identifies nothing — environments share them — whereas the presence of
    these indexes means the overlap guarantee is live on this data, and
    fictional consultations in it would be enforced as though real.
    """
    info = await appts.index_information()
    # CORRECTNESS only. The declared set also carries QUERY indexes, which
    # enforce nothing — `appointment_pending_expiry` just keeps the expiry
    # sweep off a collection scan. Refusing to seed because a performance
    # index exists would be refusing for a reason that is not the reason.
    return sorted(spec.name for spec in APPOINTMENT_INDEX_REQUIREMENTS
                  if spec.kind == CORRECTNESS and spec.name in info)


def _confirm_target(args, uri, database, out) -> int | None:
    """Endpoint AND database, confirmed before connecting.

    Returns an exit code to stop on, or None to continue. Uses the backfill
    CLI's parser so the two commands cannot disagree about what an endpoint is.
    """
    if args.confirm_database is None or not args.confirm_endpoint:
        out("REFUSED: a mutating run requires --confirm-database and "
            "--confirm-endpoint. A database name alone does not identify a "
            "target — environments routinely share one, and two instances on "
            "a single host can differ only by port.")
        return EXIT_REFUSED

    if args.confirm_database != database:
        out("REFUSED: --confirm-database does not match the database this "
            "would act on. Nothing was written.")
        return EXIT_REFUSED

    try:
        actual = parsed_endpoints(uri)
    except UnparseableTarget:
        out("REFUSED: the connection string does not name an endpoint that "
            "can be confirmed. Nothing was written.")
        return EXIT_REFUSED

    try:
        claimed = sorted({normalise_endpoint(e) for e in args.confirm_endpoint
                          if e.strip()})
    except UnparseableTarget as exc:
        out(f"REFUSED: --confirm-endpoint is not a usable endpoint ({exc}). "
            "Expected scheme://host[:port]. Nothing was written.")
        return EXIT_REFUSED

    if claimed != actual:
        # The real endpoints are not echoed back: a wrong guess must not become
        # a way to read the target out of the error message.
        out("REFUSED: --confirm-endpoint does not match the connection string. "
            "Check which environment it points at, and remember the port is "
            "part of the endpoint. Nothing was written.")
        return EXIT_REFUSED

    return None


def _as_utc(value: datetime) -> datetime:
    """A stored instant as aware UTC. Rows written before `tz_aware=True`
    decode naive, and they were always UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def derive_slots(row: dict) -> tuple[list[datetime] | None, str | None]:
    """The half-hours an existing active row occupies — `(slots, problem)`.

    STORED SLOTS ARE NOT THE ONLY SOURCE, and assuming they were is what made
    the clash scan wrong. Before activation an active appointment may carry no
    `occupied_slots` at all: the field arrived with the slot contract, and every
    row written before it has none. Such a row holds a real hour in a real
    lawyer's calendar and was invisible to a scan that only read the field — so
    the seeder would plan a demo consultation straight on top of it.

    Order matters. A row's own stored slots win where they exist, because they
    are what the unique indexes actually compare; only when they are absent are
    slots derived from `scheduled_at` and `duration_minutes`.

    A row that can be assessed neither way returns a problem instead of an
    empty list. Treating "cannot tell" as "free" is the assumption this exists
    to remove: it would let the seeder book over an appointment precisely when
    it understands that appointment least.
    """
    stored = row.get("occupied_slots")
    if (isinstance(stored, (list, tuple)) and stored
            and all(isinstance(s, datetime) for s in stored)):
        return [_as_utc(s) for s in stored], None
    if stored:
        # Present but not a list of datetimes — malformed, not absent.
        return None, "occupied_slots is present but unreadable"

    start = row.get("scheduled_at")
    duration = row.get("duration_minutes")
    if not isinstance(start, datetime):
        return None, "no usable scheduled_at"
    start = _as_utc(start)
    misaligned = alignment_error(start)
    if misaligned:
        return None, f"start is not on a slot boundary ({misaligned})"
    bad_duration = duration_error(duration)
    if bad_duration:
        return None, f"duration cannot be used ({bad_duration})"
    return occupied_slots(start, duration), None


async def scan_claimed_slots(appts, lawyer_ids, client_id):
    """Slots already held by active rows, for these lawyers or this client.

    Returns `(by_lawyer, by_client, unassessable)`. Both parties are scanned
    because both are constrained: the unique indexes cover `lawyer_id` AND
    `client_id`, so a demo row can clash with the client's own diary as easily
    as with a lawyer's.
    """
    by_lawyer: set[tuple[str, datetime]] = set()
    by_client: set[tuple[str, datetime]] = set()
    unassessable: list[tuple[str, str]] = []

    cursor = appts.find(
        {"status": {"$in": list(ACTIVE)},
         "$or": [{"lawyer_id": {"$in": list(lawyer_ids)}},
                 {"client_id": client_id}]},
        {"_id": 1, "lawyer_id": 1, "client_id": 1, "scheduled_at": 1,
         "duration_minutes": 1, "occupied_slots": 1},
    )
    lawyers = set(lawyer_ids)
    async for row in cursor:
        slots, problem = derive_slots(row)
        if problem:
            unassessable.append((str(row.get("_id")), problem))
            continue
        for slot in slots:
            if row.get("lawyer_id") in lawyers:
                by_lawyer.add((row["lawyer_id"], slot))
            if row.get("client_id") == client_id:
                by_client.add((client_id, slot))
    return by_lawyer, by_client, unassessable


def build_rows(who, lawyers, cases, taken_lawyer, taken_client, now):
    """The demo rows, in the shape the application writes today.

    `taken_lawyer` and `taken_client` are the slots already claimed by existing
    active rows. BOTH are needed: the unique indexes constrain `lawyer_id` and
    `client_id` alike, so a demo row can clash with the client's own diary as
    easily as with a lawyer's — and every row here belongs to one client, which
    makes the client axis the one most likely to collide.

    Both sets are extended as rows are planned, so the plan cannot collide with
    ITSELF — two entries an hour apart with 90-minute durations overlap, and
    nothing outside this function would have noticed.
    """
    planned, notes = [], []
    claimed_lawyer = set(taken_lawyer)
    claimed_client = set(taken_client)

    for i, (days, hour, mins, status, mode, note) in enumerate(PLAN):
        lawyer = lawyers[i % len(lawyers)]
        when = (now + timedelta(days=days)).replace(
            hour=hour, minute=0, second=0, microsecond=0)

        misaligned = alignment_error(when)
        if misaligned:                      # unreachable via PLAN; a guard
            notes.append(f"skip {when:%Y-%m-%d %H:%M} {misaligned}")
            continue

        slots = occupied_slots(when, mins)
        is_active = status in ACTIVE
        if is_active:
            lawyer_clash = any((lawyer["_id"], s) in claimed_lawyer for s in slots)
            client_clash = any((who["_id"], s) in claimed_client for s in slots)
            if lawyer_clash or client_clash:
                whose = "lawyer" if lawyer_clash else "client"
                notes.append(
                    f"skip     {when:%Y-%m-%d %H:%M}  {lawyer['email']:34} "
                    f"{whose} slot already taken")
                continue
            claimed_lawyer.update((lawyer["_id"], s) for s in slots)
            claimed_client.update((who["_id"], s) for s in slots)

        planned.append({
            "_id": secrets.token_urlsafe(16),
            "client_id": who["_id"],
            "lawyer_id": lawyer["_id"],
            "case_id": cases[i]["_id"] if i < len(cases) else None,
            "scheduled_at": when,
            "end_at": when + timedelta(minutes=mins),
            "duration_minutes": mins,
            "status": status,
            "mode": mode,
            # The fields the contract now requires. `occupied_slots` is what
            # the unique indexes compare — a row without it is invisible to
            # them — and `schedule_version` is what reschedule and confirm pin.
            "occupied_slots": slots,
            "schedule_version": 0,
            "timezone": "Asia/Karachi",
            "notes": note,
            "lawyer_notes": None,
            "cancel_reason": "Client requested a different time." if status == "cancelled" else None,
            # The ROLE, as `cancel_appointment` writes it — not the client's id,
            # which is what this used to store and which no reader expects.
            "cancelled_by": "client" if status == "cancelled" else None,
            "meeting_link": "https://meet.example.invalid/demo" if mode == "video" else None,
            DEMO_MARKER: True,
            "created_at": now - timedelta(days=abs(days) + 2),
            "updated_at": now,
        })
        notes.append(f"{when:%Y-%m-%d %H:%M}  {status:10} {mode:10} {lawyer['email']}")

    return planned, notes


async def _pick_client(db, email: str | None) -> dict:
    if email:
        u = await db["users"].find_one({"email": email, "role": "client"})
        if not u:
            raise SystemExit(f"no client found with email {email!r}")
        return u
    # Otherwise the non-fixture client with the most cases — the account a demo
    # is most likely to be driven from.
    best, best_n = None, -1
    async for u in db["users"].find({"role": "client", "is_active": True}):
        e = u.get("email") or ""
        if not e or FIXTURE_EMAIL.search(e) or e.startswith("closed+"):
            continue
        n = await db["cases"].count_documents({"client_id": u["_id"]})
        if n > best_n:
            best, best_n = u, n
    if not best:
        raise SystemExit("no non-fixture client account to attach appointments to")
    return best


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Seed demo appointments.")
    ap.add_argument("--apply", action="store_true", help="insert the appointments")
    ap.add_argument("--list", action="store_true", help="list demo appointments")
    ap.add_argument("--remove", action="store_true",
                    help=f"delete every appointment marked {DEMO_MARKER}")
    ap.add_argument("--client", help="client email to attach them to")
    ap.add_argument("--confirm-database", default=None,
                    help="Repeat the database name exactly. Required to mutate.")
    ap.add_argument("--confirm-endpoint", action="append", default=None,
                    metavar="scheme://host[:port]",
                    help="Repeat each endpoint the connection string points at. "
                         "Required to mutate. Scheme, host AND port all count.")
    return ap


async def _default_connect(uri: str, database: str):
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(uri, tz_aware=True, serverSelectionTimeoutMS=15000)
    return client, client[database]


async def run(argv, env, connect=_default_connect, out=print) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or EXIT_USAGE)

    # NOTE: the plan is validated in the SEEDING path only, not here.
    #
    # Gating every mode on it meant a broken PLAN also disabled `--list` and
    # `--remove` — the two modes that do not read the plan at all, and the two
    # an operator needs most when something is wrong. Cleanup must never be
    # blocked by the thing that made cleanup necessary.
    uri = (env or {}).get("MONGODB_URL")
    database = (env or {}).get("DB_NAME", "attorney_ai")
    if not uri:
        out("REFUSED: MONGODB_URL is not set.")
        return EXIT_USAGE

    mutating = args.apply or args.remove
    if mutating:
        refusal = _confirm_target(args, uri, database, out)
        if refusal is not None:
            return refusal

    out(f"target : {database} on {redact(uri)}")

    client, db = await connect(uri, database)
    appts = db["appointments"]
    try:
        if args.list:
            n = 0
            async for a in appts.find({DEMO_MARKER: True}).sort("scheduled_at", 1):
                out(f"  {str(a['scheduled_at'])[:16]}  {a['status']:10} {a['mode']:10} "
                    f"lawyer={a['lawyer_id'][:12]} case={str(a.get('case_id'))[:12]}")
                n += 1
            out(f"\n{n} demo appointment(s)")
            return EXIT_OK

        if args.remove:
            # TIGHTLY SCOPED. Only rows carrying the marker, and the count is
            # reported before and after so a filter that matched more than
            # intended is visible rather than silent.
            doomed = await appts.count_documents({DEMO_MARKER: True})
            out(f"{doomed} demo appointment(s) to delete")
            if doomed:
                res = await appts.delete_many({DEMO_MARKER: True})
                out(f"deleted {res.deleted_count}")
            return EXIT_OK

        # ── seeding ──────────────────────────────────────────────────────────
        #
        # The plan is validated HERE, so it gates the dry run and --apply and
        # nothing else. A plan the application would refuse must not reach a
        # database even in a dry run, because the dry run is what an operator
        # reads before applying.
        problems = validate_plan()
        if problems:
            for problem in problems:
                out(f"INVALID PLAN: {problem}")
            out("Nothing was written. `--list` and `--remove` still work.")
            return EXIT_USAGE

        active = await active_correctness_indexes(appts)
        if active and args.apply:
            out("REFUSED: the appointment correctness indexes are present on "
                f"this database ({', '.join(active)}), so the overlap "
                "guarantee is live. These are FICTIONAL consultations — "
                "seeding them here puts invented bookings on a real lawyer's "
                "calendar and has the index enforce them. Seed a "
                "pre-activation database instead. Nothing was written.")
            return EXIT_REFUSED
        if active:
            out(f"note   : correctness indexes present ({', '.join(active)}); "
                "--apply would be refused on this database.")

        who = await _pick_client(db, args.client)
        out(f"client : {who.get('email')}  ({who['_id']})")

        lawyers = [u async for u in db["users"].find(
            {"role": "lawyer", DEMO_MARKER: True, "is_active": True}
        ).sort("province", 1)]
        if not lawyers:
            out("no demo lawyers found — run scripts/seed_demo_lawyers.py first")
            return EXIT_USAGE
        out(f"lawyers: {len(lawyers)} demo lawyer(s) available")

        cases = [c async for c in db["cases"].find(
            {"client_id": who["_id"]}).limit(len(PLAN))]
        out(f"cases  : {len(cases)} belonging to this client\n")

        # Slots already claimed by active rows — for these lawyers AND for this
        # client. Legacy rows carrying no `occupied_slots` have theirs derived;
        # see `derive_slots`.
        lawyer_ids = [lw["_id"] for lw in lawyers]
        taken_lawyer, taken_client, unassessable = await scan_claimed_slots(
            appts, lawyer_ids, who["_id"])

        if unassessable:
            # "Cannot tell" is not "free". An active row whose time or duration
            # cannot be read may hold any hour, so planning around it would be
            # a guess — made at the moment the data is least understood.
            out("")
            out(f"{len(unassessable)} active appointment(s) cannot be "
                "assessed for conflicts:")
            for appt_id, problem in unassessable[:10]:
                out(f"  {appt_id}: {problem}")
            if len(unassessable) > 10:
                out(f"  ... and {len(unassessable) - 10} more")
            if args.apply:
                out("REFUSED: seeding would have to assume those hours are "
                    "free. Resolve them first — "
                    "`python -m app.db.appointment_slot_preflight` lists them. "
                    "Nothing was written.")
                return EXIT_REFUSED
            out("note   : --apply would be refused while these exist.")

        now = datetime.now(timezone.utc).replace(
            minute=0, second=0, microsecond=0)
        planned, notes = build_rows(
            who, lawyers, cases, taken_lawyer, taken_client, now)
        for note in notes:
            out(f"  {'would add' if not args.apply else 'add      '} {note}"
                if not note.startswith("skip") else f"  {note}")

        skipped = len(PLAN) - len(planned)
        if not args.apply:
            out(f"\n{len(planned)} would be inserted, {skipped} skipped")
            out("DRY RUN - nothing written. Re-run with --apply, "
                "--confirm-database and --confirm-endpoint.")
            return EXIT_OK

        if planned:
            await appts.insert_many(planned)
        total = await appts.count_documents({})
        out(f"\ninserted {len(planned)}, skipped {skipped}")
        out(f"appointments in the database now: {total}")
        return EXIT_OK
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            maybe = close()
            if asyncio.iscoroutine(maybe):
                await maybe


def main(argv=None) -> int:
    from dotenv import load_dotenv

    load_dotenv(BACKEND / ".env")
    return asyncio.run(run(argv if argv is not None else sys.argv[1:], os.environ))


if __name__ == "__main__":
    sys.exit(main())
