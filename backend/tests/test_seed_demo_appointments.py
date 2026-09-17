"""The demo appointment seeder, against the current appointment contract.

This script is an INDEPENDENT WRITER to the appointments collection: it runs
from an operator's machine, reads `MONGODB_URL`, and is unaffected by anything
done to the application. That is why it is audited here rather than trusted.

It had drifted badly from what the application can produce:

  * three plan entries booked 45 MINUTES, which the application refuses and
    which defeats the overlap index outright — 10:00/45 claims {10:00, 10:30}
    and 10:45/45 claims {10:45, 11:15}, so the two overlap for a real quarter
    of an hour and share no indexed instant;
  * inserted rows carried no `occupied_slots`, so they were invisible to the
    unique indexes — claiming no hours and colliding with nobody;
  * no `schedule_version`, which reschedule and confirm both pin;
  * and it wrote with NO target confirmation at all, defaulting `DB_NAME` to
    `attorney_ai` — the production name.

The tests below are about the refusals and the shape of what it writes. They
use the local `_test` database and a fake connector; nothing here connects to
production.
"""
import importlib.util
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.appointment_slots import duration_error, occupied_slots

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "seed_demo_appointments.py"


def _load():
    spec = importlib.util.spec_from_file_location("seed_demo_appointments", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = _load()

URI = "mongodb://localhost:27017"
ENV = {"MONGODB_URL": URI, "DB_NAME": "attorney_ai_test"}


class Recorder:
    def __init__(self):
        self.lines: list[str] = []

    def __call__(self, line=""):
        self.lines.append(str(line))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


async def _never_connect(uri, database):
    raise AssertionError(
        f"the seeder connected to {database!r} when it should have refused first")


async def _connector(db):
    class _Client:
        def close(self):
            return None

    async def _connect(uri, database):
        return _Client(), db
    return _connect


# ── 1. The plan itself ───────────────────────────────────────────────────────

def test_the_plan_contains_no_part_slot_duration():
    """A 45-minute consultation is the value that quietly defeats the overlap
    guard while looking perfectly reasonable in a demo."""
    assert seed.validate_plan() == []
    for index, entry in enumerate(seed.PLAN):
        assert duration_error(entry[2]) is None, f"PLAN[{index}] duration {entry[2]}"


async def test_an_invalid_plan_is_refused(seeded, monkeypatch):
    """The plan is validated in the SEEDING path, so this connects first and
    then refuses. The guarantee is that nothing is WRITTEN — not that nothing
    is read, because `--list` and `--remove` have to keep working."""
    bad = list(seed.PLAN)
    bad[0] = (-21, 10, 45, "completed", "in_person", "note")
    monkeypatch.setattr(seed, "PLAN", bad)
    out = Recorder()

    result = await seed.run([], ENV,
                            connect=await _connector(seeded["db"]), out=out)

    assert result == seed.EXIT_USAGE
    assert "INVALID PLAN" in out.text
    assert "multiple of 30" in out.text
    assert "`--list` and `--remove` still work" in out.text
    assert await seeded["col"].count_documents({}) == 0


# ── 2. Mutating modes must confirm the target ────────────────────────────────

@pytest.mark.parametrize("mode", ["--apply", "--remove"])
async def test_a_mutating_mode_refuses_without_confirmation(mode):
    out = Recorder()

    code = await seed.run([mode], ENV, connect=_never_connect, out=out)

    assert code == seed.EXIT_REFUSED
    assert "--confirm-database" in out.text
    assert "--confirm-endpoint" in out.text
    # `_never_connect` proves it refused BEFORE connecting.


@pytest.mark.parametrize("mode", ["--apply", "--remove"])
async def test_a_wrong_database_is_refused_before_connecting(mode):
    out = Recorder()

    code = await seed.run(
        [mode, "--confirm-database", "attorney_ai",
         "--confirm-endpoint", URI],
        ENV, connect=_never_connect, out=out)

    assert code == seed.EXIT_REFUSED
    assert "Nothing was written" in out.text


@pytest.mark.parametrize("mode", ["--apply", "--remove"])
async def test_a_wrong_endpoint_port_is_refused_before_connecting(mode):
    """Same scheme, same host, same database name — a different instance."""
    out = Recorder()

    code = await seed.run(
        [mode, "--confirm-database", "attorney_ai_test",
         "--confirm-endpoint", "mongodb://localhost:27018"],
        ENV, connect=_never_connect, out=out)

    assert code == seed.EXIT_REFUSED
    assert "port is part of the endpoint" in out.text


async def test_the_refusal_does_not_echo_the_real_endpoint():
    out = Recorder()

    await seed.run(
        ["--apply", "--confirm-database", "attorney_ai_test",
         "--confirm-endpoint", "mongodb://elsewhere.example.net:27017"],
        {"MONGODB_URL": "mongodb://real-host.example.net:27017/",
         "DB_NAME": "attorney_ai_test"},
        connect=_never_connect, out=out)

    assert "real-host" not in out.text


async def test_read_only_modes_need_no_confirmation(seeded):
    """`--list` and the dry run must stay usable — they write nothing."""
    out = Recorder()

    code = await seed.run(["--list"], ENV,
                          connect=await _connector(seeded["db"]), out=out)

    assert code == seed.EXIT_OK


# ── 3. Against the real local _test database ─────────────────────────────────

@pytest.fixture
async def seeded(app_indexes):
    """A demo lawyer and a client, on the local test database."""
    from app.db.collections import get_appointments_col, get_users_col
    from app.db.mongodb import get_database

    tag = secrets.token_hex(4)
    client_id, lawyer_id = f"SD-C-{tag}", f"SD-L-{tag}"
    now = datetime.now(timezone.utc)
    await get_users_col().insert_many([
        {"_id": lawyer_id, "role": "lawyer", "is_active": True,
         "email": f"demo-l-{tag}@demo.invalid", "full_name": "Adv Demo",
         "province": "punjab", "created_at": now, seed.DEMO_MARKER: True,
         "lawyer_profile": {"specializations": ["criminal"], "kyc_verified": True,
                            "rating": 4.0, "total_reviews": 0,
                            "availability": True, "experience_years": 5}},
        {"_id": client_id, "role": "client", "is_active": True,
         "email": f"demo-c-{tag}@realmail.invalid", "full_name": "Client Demo",
         "created_at": now},
    ])
    col = get_appointments_col()
    await col.delete_many({})

    yield {"client_id": client_id, "lawyer_id": lawyer_id,
           "col": col, "db": get_database(), "tag": tag}

    await get_users_col().delete_many({"_id": {"$in": [client_id, lawyer_id]}})
    await col.delete_many({})


async def _drop_correctness_indexes(col):
    from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS

    for spec in APPOINTMENT_INDEX_REQUIREMENTS:
        try:
            await col.drop_index(spec.name)
        except Exception:  # noqa: BLE001 - absent is fine
            pass


async def _restore_correctness_indexes():
    from app.db.indexes import create_appointment_correctness_indexes

    await create_appointment_correctness_indexes()


# ── 4. Activation blocks seeding ─────────────────────────────────────────────

async def test_apply_is_refused_once_the_correctness_indexes_exist(seeded):
    """These are FICTIONAL consultations. Once the overlap guarantee is live, a
    database holding them is one where a real lawyer's calendar contains
    invented bookings and the index is enforcing them."""
    out = Recorder()

    code = await seed.run(
        ["--apply", "--confirm-database", "attorney_ai_test",
         "--confirm-endpoint", URI],
        ENV, connect=await _connector(seeded["db"]), out=out)

    assert code == seed.EXIT_REFUSED
    assert "correctness indexes are present" in out.text
    assert "FICTIONAL" in out.text
    assert await seeded["col"].count_documents({}) == 0, "it seeded anyway"


async def test_the_activation_test_is_the_indexes_not_the_database_name(seeded):
    """A name identifies nothing — environments share them. With the indexes
    dropped, the same database name is seedable."""
    await _drop_correctness_indexes(seeded["col"])
    out = Recorder()
    try:
        code = await seed.run(
            ["--apply", "--confirm-database", "attorney_ai_test",
             "--confirm-endpoint", URI],
            ENV, connect=await _connector(seeded["db"]), out=out)
    finally:
        await _restore_correctness_indexes()

    assert code == seed.EXIT_OK, out.text
    assert await seeded["col"].count_documents({}) > 0


async def test_a_dry_run_warns_that_apply_would_be_refused(seeded):
    out = Recorder()

    code = await seed.run([], ENV,
                          connect=await _connector(seeded["db"]), out=out)

    assert code == seed.EXIT_OK
    assert "would be refused" in out.text


# ── 5. What it writes ────────────────────────────────────────────────────────

async def test_no_slotless_or_part_slot_active_row_is_inserted(seeded):
    await _drop_correctness_indexes(seeded["col"])
    out = Recorder()
    try:
        await seed.run(
            ["--apply", "--confirm-database", "attorney_ai_test",
             "--confirm-endpoint", URI],
            ENV, connect=await _connector(seeded["db"]), out=out)
    finally:
        await _restore_correctness_indexes()

    rows = [r async for r in seeded["col"].find({})]
    assert rows, "nothing was seeded"
    for row in rows:
        assert duration_error(row["duration_minutes"]) is None, row["_id"]
        assert row["schedule_version"] == 0
        if row["status"] in seed.ACTIVE:
            assert row.get("occupied_slots"), (
                f"{row['_id']} is active and claims no slots — invisible to "
                "the unique indexes")
            expected = occupied_slots(
                row["scheduled_at"].replace(tzinfo=timezone.utc),
                row["duration_minutes"])
            assert sorted(s.replace(tzinfo=timezone.utc)
                          for s in row["occupied_slots"]) == expected


async def test_seeded_rows_survive_the_correctness_indexes(seeded):
    """The real proof that the shape is right: build the indexes over the rows
    it just wrote. A slotless or overlapping row fails the build."""
    await _drop_correctness_indexes(seeded["col"])
    try:
        await seed.run(
            ["--apply", "--confirm-database", "attorney_ai_test",
             "--confirm-endpoint", URI],
            ENV, connect=await _connector(seeded["db"]), out=Recorder())
        await _restore_correctness_indexes()
    finally:
        await _restore_correctness_indexes()

    from app.db.indexes import validate_appointment_indexes
    assert await validate_appointment_indexes() == []


async def test_every_seeded_row_is_marked(seeded):
    await _drop_correctness_indexes(seeded["col"])
    try:
        await seed.run(
            ["--apply", "--confirm-database", "attorney_ai_test",
             "--confirm-endpoint", URI],
            ENV, connect=await _connector(seeded["db"]), out=Recorder())
    finally:
        await _restore_correctness_indexes()

    unmarked = await seeded["col"].count_documents(
        {seed.DEMO_MARKER: {"$ne": True}})
    assert unmarked == 0, "a demo row was written without its marker"


# ── 6. The dry run writes nothing ────────────────────────────────────────────

async def test_a_dry_run_writes_nothing(seeded):
    out = Recorder()

    code = await seed.run([], ENV,
                          connect=await _connector(seeded["db"]), out=out)

    assert code == seed.EXIT_OK
    assert "DRY RUN" in out.text
    assert await seeded["col"].count_documents({}) == 0


# ── 7. Removal is tightly scoped ─────────────────────────────────────────────

async def test_removal_touches_only_marked_rows(seeded):
    """A real booking and a test fixture must both survive it."""
    when = (datetime.now(timezone.utc) + timedelta(days=30)).replace(
        minute=0, second=0, microsecond=0)

    async def _add(_id, **over):
        doc = {"_id": _id, "client_id": seeded["client_id"],
               "lawyer_id": seeded["lawyer_id"], "status": "pending",
               "scheduled_at": when, "end_at": when + timedelta(minutes=60),
               "duration_minutes": 60,
               "occupied_slots": occupied_slots(when, 60),
               "schedule_version": 0}
        doc.update(over)
        await seeded["col"].insert_one(doc)

    await _add(f"real-{seeded['tag']}")
    await _add(f"demo-{seeded['tag']}",
               lawyer_id=f"OTHER-{seeded['tag']}",
               scheduled_at=when + timedelta(hours=2),
               end_at=when + timedelta(hours=3),
               occupied_slots=occupied_slots(when + timedelta(hours=2), 60),
               **{seed.DEMO_MARKER: True})

    out = Recorder()
    code = await seed.run(
        ["--remove", "--confirm-database", "attorney_ai_test",
         "--confirm-endpoint", URI],
        ENV, connect=await _connector(seeded["db"]), out=out)

    assert code == seed.EXIT_OK
    assert await seeded["col"].find_one({"_id": f"real-{seeded['tag']}"}) is not None, (
        "an unmarked appointment was deleted")
    assert await seeded["col"].find_one({"_id": f"demo-{seeded['tag']}"}) is None
    assert "deleted 1" in out.text


async def test_removal_is_allowed_while_the_indexes_are_active(seeded):
    """Removal is how demo rows are cleaned up BEFORE a public deployment, so
    activation must not block it — only seeding."""
    when = (datetime.now(timezone.utc) + timedelta(days=30)).replace(
        minute=0, second=0, microsecond=0)
    await seeded["col"].insert_one({
        "_id": f"demo-{seeded['tag']}", "client_id": seeded["client_id"],
        "lawyer_id": seeded["lawyer_id"], "status": "pending",
        "scheduled_at": when, "end_at": when + timedelta(minutes=60),
        "duration_minutes": 60, "occupied_slots": occupied_slots(when, 60),
        "schedule_version": 0, seed.DEMO_MARKER: True})

    code = await seed.run(
        ["--remove", "--confirm-database", "attorney_ai_test",
         "--confirm-endpoint", URI],
        ENV, connect=await _connector(seeded["db"]), out=Recorder())

    assert code == seed.EXIT_OK
    assert await seeded["col"].count_documents({}) == 0


# ── 8. It reuses the application's rules ─────────────────────────────────────

def test_the_seeder_does_not_reimplement_the_slot_rules():
    """A second slot implementation would drift from the application's, and the
    two disagreeing about what a valid appointment is would be silent."""
    source = SCRIPT.read_text(encoding="utf-8")

    assert "from app.services.appointment_slots import" in source
    assert "from app.db.appointment_backfill_cli import" in source
    # No hand-rolled half-hour arithmetic.
    assert "SLOT_MINUTES =" not in source
    assert "def occupied_slots" not in source


# ── 9. A broken plan must not disable cleanup ────────────────────────────────
#
# `validate_plan()` used to gate every mode, so an invalid PLAN also disabled
# `--list` and `--remove` — the two modes that do not read the plan at all, and
# the two an operator needs most when something is wrong. Cleanup must never be
# blocked by the thing that made cleanup necessary.

@pytest.fixture
def broken_plan(monkeypatch):
    """A deliberately invalid 45-minute entry."""
    bad = list(seed.PLAN)
    bad[0] = (-21, 10, 45, "completed", "in_person", "a part-slot consultation")
    monkeypatch.setattr(seed, "PLAN", bad)
    return bad


async def _demo_row(seeded, _id, **over):
    when = (datetime.now(timezone.utc) + timedelta(days=40)).replace(
        minute=0, second=0, microsecond=0)
    doc = {"_id": _id, "client_id": seeded["client_id"],
           "lawyer_id": seeded["lawyer_id"], "status": "pending",
           "scheduled_at": when, "end_at": when + timedelta(minutes=60),
           "duration_minutes": 60, "occupied_slots": occupied_slots(when, 60),
           "schedule_version": 0, "mode": "video", "case_id": None}
    doc.update(over)
    await seeded["col"].insert_one(doc)
    return doc


async def test_a_broken_plan_refuses_to_seed_before_writing(seeded, broken_plan):
    await _drop_correctness_indexes(seeded["col"])
    out = Recorder()
    try:
        code = await seed.run(
            ["--apply", "--confirm-database", "attorney_ai_test",
             "--confirm-endpoint", URI],
            ENV, connect=await _connector(seeded["db"]), out=out)
    finally:
        await _restore_correctness_indexes()

    assert code == seed.EXIT_USAGE
    assert "INVALID PLAN" in out.text
    assert "multiple of 30" in out.text
    assert await seeded["col"].count_documents({}) == 0, "it seeded anyway"


async def test_a_broken_plan_still_allows_listing(seeded, broken_plan):
    """`--list` does not read the plan."""
    await _demo_row(seeded, f"demo-{seeded['tag']}",
                    **{seed.DEMO_MARKER: True})
    out = Recorder()

    code = await seed.run(["--list"], ENV,
                          connect=await _connector(seeded["db"]), out=out)

    assert code == seed.EXIT_OK
    assert "INVALID PLAN" not in out.text
    assert "1 demo appointment(s)" in out.text


async def test_a_broken_plan_still_allows_confirmed_removal(seeded, broken_plan):
    """The mode that undoes the damage must not be blocked by the damage."""
    await _demo_row(seeded, f"real-{seeded['tag']}")
    await _demo_row(seeded, f"demo-{seeded['tag']}",
                    lawyer_id=f"OTHER-{seeded['tag']}",
                    scheduled_at=(datetime.now(timezone.utc) + timedelta(days=41)
                                  ).replace(minute=0, second=0, microsecond=0),
                    end_at=(datetime.now(timezone.utc) + timedelta(days=41, hours=1)
                            ).replace(minute=0, second=0, microsecond=0),
                    occupied_slots=occupied_slots(
                        (datetime.now(timezone.utc) + timedelta(days=41)).replace(
                            minute=0, second=0, microsecond=0), 60),
                    **{seed.DEMO_MARKER: True})
    out = Recorder()

    code = await seed.run(
        ["--remove", "--confirm-database", "attorney_ai_test",
         "--confirm-endpoint", URI],
        ENV, connect=await _connector(seeded["db"]), out=out)

    assert code == seed.EXIT_OK
    assert "INVALID PLAN" not in out.text
    assert "deleted 1" in out.text
    assert await seeded["col"].find_one({"_id": f"real-{seeded['tag']}"}) is not None, (
        "removal touched an unmarked row")
    assert await seeded["col"].find_one({"_id": f"demo-{seeded['tag']}"}) is None


async def test_removal_still_requires_target_confirmation_with_a_broken_plan(
        seeded, broken_plan):
    """Keeping cleanup available must not have loosened the target guard."""
    out = Recorder()

    code = await seed.run(["--remove"], ENV, connect=_never_connect, out=out)

    assert code == seed.EXIT_REFUSED
    assert "--confirm-endpoint" in out.text


# ── 10. Legacy rows without stored slots ─────────────────────────────────────
#
# The clash scan read `occupied_slots` and nothing else. Before activation an
# active appointment may carry none — the field arrived with the slot contract
# — so a real booking in a real lawyer's calendar was invisible to it, and the
# seeder would plan a demo consultation straight on top.

def test_slots_are_derived_when_none_are_stored():
    when = datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc)
    slots, problem = seed.derive_slots(
        {"scheduled_at": when, "duration_minutes": 60})

    assert problem is None
    assert slots == occupied_slots(when, 60)


def test_stored_slots_win_where_they_exist():
    """They are what the unique indexes actually compare."""
    when = datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc)
    stored = occupied_slots(when + timedelta(hours=5), 30)

    slots, problem = seed.derive_slots(
        {"scheduled_at": when, "duration_minutes": 60, "occupied_slots": stored})

    assert problem is None
    assert slots == stored


@pytest.mark.parametrize("row,expected", [
    ({"duration_minutes": 60}, "scheduled_at"),
    ({"scheduled_at": datetime(2026, 12, 1, 10, 15, tzinfo=timezone.utc),
      "duration_minutes": 60}, "slot boundary"),
    ({"scheduled_at": datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc),
      "duration_minutes": 45}, "duration"),
    ({"scheduled_at": datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc),
      "occupied_slots": ["not-a-datetime"]}, "unreadable"),
])
def test_an_unassessable_row_reports_a_problem_rather_than_no_slots(row, expected):
    """"Cannot tell" must not read as "free"."""
    slots, problem = seed.derive_slots(row)

    assert slots is None
    assert expected in problem


async def test_a_slotless_active_row_is_seen_as_a_conflict(seeded):
    """The real defect: a legacy booking with no stored slots, on an hour the
    plan wants."""
    await _drop_correctness_indexes(seeded["col"])
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    # PLAN[6] is +9 days at 11:00 UTC, pending, 60 minutes, first lawyer.
    collides = (now + timedelta(days=9)).replace(hour=11)
    await seeded["col"].insert_one({
        "_id": f"legacy-{seeded['tag']}",
        "client_id": f"SOMEONE-ELSE-{seeded['tag']}",
        "lawyer_id": seeded["lawyer_id"],
        "status": "pending", "scheduled_at": collides,
        "end_at": collides + timedelta(minutes=60), "duration_minutes": 60,
        # NO occupied_slots — exactly a pre-activation row.
    })
    out = Recorder()
    try:
        code = await seed.run(
            ["--apply", "--confirm-database", "attorney_ai_test",
             "--confirm-endpoint", URI],
            ENV, connect=await _connector(seeded["db"]), out=out)
    finally:
        await _restore_correctness_indexes()

    assert code == seed.EXIT_OK
    assert "lawyer slot already taken" in out.text, out.text
    # And nothing was written onto that hour.
    clashing = await seeded["col"].count_documents({
        "lawyer_id": seeded["lawyer_id"], "scheduled_at": collides})
    assert clashing == 1, "a demo row was planned on top of the legacy booking"


async def test_a_client_side_conflict_is_detected(seeded):
    """The unique indexes constrain `client_id` too, and every demo row belongs
    to one client — so the client axis is the likelier collision."""
    await _drop_correctness_indexes(seeded["col"])
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    collides = (now + timedelta(days=9)).replace(hour=11)
    await seeded["col"].insert_one({
        "_id": f"legacy-{seeded['tag']}",
        "client_id": seeded["client_id"],
        "lawyer_id": f"UNRELATED-{seeded['tag']}",
        "status": "pending", "scheduled_at": collides,
        "end_at": collides + timedelta(minutes=60), "duration_minutes": 60,
    })
    out = Recorder()
    try:
        await seed.run(
            ["--apply", "--confirm-database", "attorney_ai_test",
             "--confirm-endpoint", URI],
            ENV, connect=await _connector(seeded["db"]), out=out)
    finally:
        await _restore_correctness_indexes()

    assert "client slot already taken" in out.text, out.text


async def test_an_unassessable_active_row_refuses_apply_before_inserting(seeded):
    """Planning around a row whose hours cannot be read would be a guess made
    exactly when the data is least understood."""
    await _drop_correctness_indexes(seeded["col"])
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    await seeded["col"].insert_one({
        "_id": f"broken-{seeded['tag']}",
        "client_id": seeded["client_id"], "lawyer_id": seeded["lawyer_id"],
        "status": "pending",
        # Misaligned and no slots: no correct set exists for it.
        "scheduled_at": (now + timedelta(days=9)).replace(hour=11, minute=15),
        "duration_minutes": 60,
    })
    out = Recorder()
    try:
        code = await seed.run(
            ["--apply", "--confirm-database", "attorney_ai_test",
             "--confirm-endpoint", URI],
            ENV, connect=await _connector(seeded["db"]), out=out)
    finally:
        await _restore_correctness_indexes()

    assert code == seed.EXIT_REFUSED
    assert "cannot be assessed" in out.text
    assert "Nothing was written" in out.text
    assert await seeded["col"].count_documents({}) == 1, (
        "demo rows were inserted despite the refusal")


async def test_a_dry_run_warns_about_unassessable_rows_without_refusing(seeded):
    await _drop_correctness_indexes(seeded["col"])
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    await seeded["col"].insert_one({
        "_id": f"broken-{seeded['tag']}",
        "client_id": seeded["client_id"], "lawyer_id": seeded["lawyer_id"],
        "status": "pending",
        "scheduled_at": (now + timedelta(days=9)).replace(hour=11, minute=15),
        "duration_minutes": 60,
    })
    out = Recorder()
    try:
        code = await seed.run([], ENV,
                              connect=await _connector(seeded["db"]), out=out)
    finally:
        await _restore_correctness_indexes()

    assert code == seed.EXIT_OK
    assert "cannot be assessed" in out.text
    assert "would be refused" in out.text
    assert await seeded["col"].count_documents({}) == 1, "the dry run wrote"


async def test_a_terminal_row_is_not_treated_as_a_conflict(seeded):
    """Only pending and confirmed hold a claim — a completed appointment does
    not block the hour, matching the partial filter on the indexes."""
    await _drop_correctness_indexes(seeded["col"])
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    collides = (now + timedelta(days=9)).replace(hour=11)
    await seeded["col"].insert_one({
        "_id": f"done-{seeded['tag']}",
        "client_id": seeded["client_id"], "lawyer_id": seeded["lawyer_id"],
        "status": "completed", "scheduled_at": collides,
        "end_at": collides + timedelta(minutes=60), "duration_minutes": 60,
    })
    out = Recorder()
    try:
        await seed.run(
            ["--apply", "--confirm-database", "attorney_ai_test",
             "--confirm-endpoint", URI],
            ENV, connect=await _connector(seeded["db"]), out=out)
    finally:
        await _restore_correctness_indexes()

    assert "slot already taken" not in out.text


def test_the_plan_does_not_collide_with_itself():
    """Two entries an hour apart with 90-minute durations would overlap, and
    nothing outside `build_rows` would notice."""
    who = {"_id": "client-1"}
    lawyers = [{"_id": "lawyer-1", "email": "a@demo.invalid"}]
    now = datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc)

    planned, _notes = seed.build_rows(who, lawyers, [], set(), set(), now)

    seen_lawyer, seen_client = set(), set()
    for row in planned:
        if row["status"] not in seed.ACTIVE:
            continue
        for slot in row["occupied_slots"]:
            assert (row["lawyer_id"], slot) not in seen_lawyer, (
                f"two planned rows claim {slot} for one lawyer")
            assert (row["client_id"], slot) not in seen_client, (
                f"two planned rows claim {slot} for one client")
            seen_lawyer.add((row["lawyer_id"], slot))
            seen_client.add((row["client_id"], slot))
