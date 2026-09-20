"""The operator CLI for the appointment slot backfill.

This command exists because steps 5 and 6 of the activation sequence otherwise
needed an interactive Python shell pointed at production — the single worst
place to type `dry_run=False` by accident. So the things worth testing are not
the slot arithmetic (which lives in the preflight and is tested there) but the
REFUSALS: every path that stops a write, and the output an operator reads
before deciding.

Nothing here connects to production. The argument and authorisation tests use a
fake connector that fails loudly if it is ever asked to connect; the behavioural
tests use the local `_test` database like every other integration test.
"""
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.db import appointment_backfill_cli as cli

URI = "mongodb+srv://backfill_user:hunter2@cluster0.example.net/?retryWrites=true"
ENV = {cli.URI_ENV_VAR: URI}


class Recorder:
    """Captures the lines an operator would see."""

    def __init__(self):
        self.lines: list[str] = []

    def __call__(self, line=""):
        self.lines.append(str(line))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


async def _never_connect(uri, database):
    raise AssertionError(
        f"the command connected to {database!r} when it should have refused first")


# ── 1. The target must be named, and the URI must not be an argument ─────────

async def test_the_database_must_be_named_explicitly():
    """Not taken from application settings: this command must not inherit
    whichever database a stray environment happens to point at."""
    out = Recorder()

    code = await cli.run([], ENV, connect=_never_connect, out=out)

    assert code != cli.EXIT_OK


async def test_a_missing_uri_variable_refuses_before_connecting():
    out = Recorder()

    code = await cli.run(["--database", "attorney_ai"], {},
                         connect=_never_connect, out=out)

    assert code == cli.EXIT_USAGE
    assert cli.URI_ENV_VAR in out.text
    assert "not accepted as an argument" in out.text


async def test_there_is_no_uri_argument_to_fall_back_to():
    """An argument reaches shell history, `ps` output and CI logs."""
    out = Recorder()

    code = await cli.run(["--database", "attorney_ai", "--uri", URI], {},
                         connect=_never_connect, out=out)

    assert code != cli.EXIT_OK


# ── 2. Applying requires every acknowledgement ───────────────────────────────

@pytest.mark.parametrize("argv,expected", [
    (["--database", "attorney_ai", "--apply"], "--confirm-database"),
    (["--database", "attorney_ai", "--apply",
      "--confirm-database", "attorney_ai"], "--confirm-endpoint"),
    (["--database", "attorney_ai", "--apply",
      "--confirm-database", "attorney_ai",
      "--confirm-endpoint", "mongodb+srv://cluster0.example.net"],
     "--booking-writes-frozen"),
    (["--database", "attorney_ai", "--apply",
      "--confirm-database", "attorney_ai_staging",
      "--confirm-endpoint", "mongodb+srv://cluster0.example.net",
      "--booking-writes-frozen"], "does not match"),
])
async def test_apply_is_refused_without_the_acknowledgements(argv, expected):
    out = Recorder()

    code = await cli.run(argv, ENV, connect=_never_connect, out=out)

    assert code == cli.EXIT_REFUSED
    assert expected in out.text
    # And it refused BEFORE opening a connection — `_never_connect` proves it.


async def test_a_mismatched_confirmation_is_the_wrong_environment_guard():
    """Typing the name twice is easy when it is the database you meant and
    jarring when it is not."""
    out = Recorder()

    code = await cli.run(
        ["--database", "attorney_ai_staging", "--apply",
         "--confirm-database", "attorney_ai",
         "--confirm-endpoint", "mongodb+srv://cluster0.example.net",
         "--booking-writes-frozen"],
        ENV, connect=_never_connect, out=out)

    assert code == cli.EXIT_REFUSED
    assert "Nothing was written" in out.text


# ── 4. Against the real local _test database ─────────────────────────────────

@pytest.fixture
async def seeded(app_indexes):
    """A legacy row needing slots, and a healthy one that does not."""
    from app.db.collections import get_appointments_col, get_users_col

    tag = secrets.token_hex(4)
    client_id, lawyer_id = f"BF-C-{tag}", f"BF-L-{tag}"
    now = datetime.now(timezone.utc)
    await get_users_col().insert_many([
        {"_id": lawyer_id, "role": "lawyer", "is_active": True,
         "email": f"{lawyer_id}@test.invalid", "full_name": "Adv Backfill",
         "province": "punjab", "created_at": now,
         "lawyer_profile": {"specializations": ["criminal"], "kyc_verified": True,
                            "rating": 4.0, "total_reviews": 0,
                            "availability": True, "experience_years": 5}},
        {"_id": client_id, "role": "client", "is_active": True,
         "email": f"{client_id}@test.invalid", "full_name": "Client Backfill",
         "created_at": now},
    ])
    col = get_appointments_col()
    await col.delete_many({})

    when = (now + timedelta(hours=48)).replace(minute=0, second=0, microsecond=0)

    async def _add(_id, **over):
        doc = {"_id": _id, "client_id": client_id, "lawyer_id": lawyer_id,
               "status": "pending", "scheduled_at": when,
               "end_at": when + timedelta(minutes=60), "duration_minutes": 60}
        doc.update(over)
        await col.insert_one(doc)

    yield {"client_id": client_id, "lawyer_id": lawyer_id,
           "when": when, "add": _add, "col": col, "tag": tag}

    await get_users_col().delete_many({"_id": {"$in": [client_id, lawyer_id]}})
    await col.delete_many({})


async def _connector(db):
    class _Client:
        def close(self):
            return None

    async def _connect(uri, database):
        return _Client(), db
    return _connect


async def test_a_dry_run_writes_nothing(seeded):
    from app.db.mongodb import get_database

    await seeded["add"](f"legacy-{seeded['tag']}")           # no occupied_slots
    out = Recorder()

    code = await cli.run(["--database", get_database().name], ENV,
                         connect=await _connector(get_database()), out=out)

    assert code == cli.EXIT_OK
    assert "DRY RUN" in out.text
    assert "planned  : 1" in out.text
    assert "written  : 0" in out.text
    stored = await seeded["col"].find_one({"_id": f"legacy-{seeded['tag']}"})
    assert "occupied_slots" not in stored, "the dry run wrote to the database"


async def test_the_output_names_the_target_without_credentials(seeded):
    from app.db.mongodb import get_database

    await seeded["add"](f"legacy-{seeded['tag']}")
    out = Recorder()

    await cli.run(["--database", get_database().name], ENV,
                  connect=await _connector(get_database()), out=out)

    assert get_database().name in out.text
    assert "cluster0.example.net" in out.text
    assert "hunter2" not in out.text


async def test_the_output_carries_no_appointment_details(seeded):
    """It goes into tickets and change records. Counts only — not ids, not
    parties, and not notes."""
    from app.db.mongodb import get_database

    await seeded["add"](f"legacy-{seeded['tag']}",
                        notes="Confidential bail instructions",
                        meeting_link="https://secret.example.com/room")
    out = Recorder()

    await cli.run(["--database", get_database().name], ENV,
                  connect=await _connector(get_database()), out=out)

    for leak in ("Confidential bail", "secret.example.com",
                 seeded["client_id"], seeded["lawyer_id"],
                 f"legacy-{seeded['tag']}"):
        assert leak not in out.text, f"{leak!r} reached the operator output"


async def test_apply_writes_the_slots_the_row_implies(seeded):
    from app.db.mongodb import get_database
    from app.services.appointment_slots import occupied_slots

    appt_id = f"legacy-{seeded['tag']}"
    await seeded["add"](appt_id)
    out = Recorder()

    code = await _apply(seeded, out, get_database())

    assert code == cli.EXIT_OK
    assert "APPLIED" in out.text
    assert "written  : 1" in out.text
    stored = await seeded["col"].find_one({"_id": appt_id})
    assert sorted(s.replace(tzinfo=timezone.utc) for s in stored["occupied_slots"]) ==         occupied_slots(seeded["when"], 60)


async def test_apply_is_refused_while_unfixable_rows_exist(seeded):
    """A row with no usable time has no correct slots. Repairing everything
    around it produces a collection that looks finished and is not."""
    from app.db.mongodb import get_database

    good = f"legacy-{seeded['tag']}"
    await seeded["add"](good)
    # Misaligned: no correct slot set exists for it.
    #
    # A DIFFERENT lawyer and client, deliberately. Two slotless active rows for
    # one party both index as `occupied_slots: null` and collide on the unique
    # index — which is not a quirk of this test but the reason the rollout
    # backfills (step 6) BEFORE creating indexes (step 7). Here the indexes
    # already exist, so the fixture avoids a collision the real sequence avoids
    # by ordering.
    await seeded["add"](f"broken-{seeded['tag']}",
                        lawyer_id=f"BF-L2-{seeded['tag']}",
                        client_id=f"BF-C2-{seeded['tag']}",
                        scheduled_at=seeded["when"] + timedelta(minutes=15))
    out = Recorder()

    code = await _apply(seeded, out, get_database())

    assert code == cli.EXIT_REFUSED
    assert "cannot fix" in out.text
    assert "Nothing was written" in out.text
    assert "appointment_slot_preflight" in out.text, "the operator needs the list"

    untouched = await seeded["col"].find_one({"_id": good})
    assert "occupied_slots" not in untouched, (
        "the fixable row was repaired despite the refusal")


async def test_a_malformed_slot_array_is_repaired_not_skipped(seeded):
    """Reuses the preflight's strict judgement: an unreadable entry makes the
    row malformed rather than being filtered out before the comparison."""
    from app.db.mongodb import get_database
    from app.services.appointment_slots import occupied_slots

    appt_id = f"legacy-{seeded['tag']}"
    good = occupied_slots(seeded["when"], 60)
    await seeded["add"](appt_id, occupied_slots=[*good, "not-a-datetime"])
    out = Recorder()

    code = await _apply(seeded, out, get_database())

    assert code == cli.EXIT_OK
    assert "written  : 1" in out.text
    stored = await seeded["col"].find_one({"_id": appt_id})
    assert all(isinstance(s, datetime) for s in stored["occupied_slots"])


async def test_a_clean_database_applies_nothing(seeded):
    from app.db.mongodb import get_database
    from app.services.appointment_slots import occupied_slots

    await seeded["add"](f"healthy-{seeded['tag']}",
                        occupied_slots=occupied_slots(seeded["when"], 60))
    out = Recorder()

    code = await _apply(seeded, out, get_database())

    assert code == cli.EXIT_OK
    assert "Nothing to do" in out.text


async def test_the_command_never_touches_an_index(seeded):
    """Bundling an index build into a data-repair command is how one starts
    without anyone deciding to start it."""
    from app.db.mongodb import get_database

    await seeded["add"](f"legacy-{seeded['tag']}")
    before = sorted((await seeded["col"].index_information()).keys())
    touched: list[str] = []

    class _Guard:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, item):
            attr = getattr(self._inner, item)
            if item in ("create_index", "create_indexes", "drop_index",
                        "drop_indexes", "drop"):
                def _refuse(*a, **kw):
                    touched.append(item)
                    raise AssertionError(f"the backfill called {item}")
                return _refuse
            return attr

    db = get_database()
    real_getitem = type(db).__getitem__
    type(db).__getitem__ = lambda self, key: _Guard(real_getitem(self, key))
    try:
        await _apply(seeded, Recorder(), db)
    finally:
        type(db).__getitem__ = real_getitem

    assert touched == []
    assert sorted((await seeded["col"].index_information()).keys()) == before


def test_the_cli_reuses_the_backfill_rather_than_reimplementing_it():
    """A second slot implementation would drift from the preflight's, and the
    two disagreeing about which rows need repair is silent."""
    import inspect

    source = inspect.getsource(cli)
    assert "backfill_occupied_slots" in source
    for reimplemented in ("occupied_slots(", "timedelta(", "SLOT_MINUTES"):
        assert reimplemented not in source.replace(
            "backfill_occupied_slots", ""), (
            f"{reimplemented} suggests the slot logic was copied here")


# ── 5. The target is an ENDPOINT and a database ──────────────────────────────
#
# An endpoint is scheme + host + PORT. The first version of this parser dropped
# the port on the grounds that it distinguishes nothing an operator gets wrong,
# which is false in the one case that matters: two Mongo instances on the same
# host differing only by port is exactly how a staging and a production
# database end up side by side on one box.

PROD_URI = "mongodb+srv://u:hunter2@prod-cluster.example.net/?retryWrites=true"
STAGING_URI = "mongodb+srv://u:hunter2@staging-cluster.example.net/?retryWrites=true"
REPLICA_URI = "mongodb://u:p@b.example.net:27017,a.example.net:27017/?replicaSet=rs0"
# The same host and the same database name, on two ports.
PROD_PORT_URI = "mongodb://u:hunter2@db.example.net:27017/attorney_ai"
STAGING_PORT_URI = "mongodb://u:hunter2@db.example.net:27018/attorney_ai"


def test_an_endpoint_carries_scheme_host_and_port():
    assert cli.parsed_endpoints(PROD_URI) == ["mongodb+srv://prod-cluster.example.net"]
    assert cli.parsed_endpoints(PROD_PORT_URI) == ["mongodb://db.example.net:27017"]
    assert cli.parsed_endpoints(STAGING_PORT_URI) == ["mongodb://db.example.net:27018"]


def test_an_omitted_port_normalises_to_the_default():
    """So an operator may confirm the endpoint as written or spelled out."""
    assert cli.parsed_endpoints("mongodb://db.example.net/db") == \
        cli.parsed_endpoints("mongodb://db.example.net:27017/db")


def test_replica_set_hosts_are_order_independent():
    """The confirmation must not depend on the order they happen to appear in."""
    forward = cli.parsed_endpoints(REPLICA_URI)
    reversed_uri = "mongodb://u:p@a.example.net:27017,b.example.net:27017/?replicaSet=rs0"

    assert forward == cli.parsed_endpoints(reversed_uri)
    assert forward == ["mongodb://a.example.net:27017", "mongodb://b.example.net:27017"]


def test_a_password_containing_an_at_sign_does_not_become_a_host():
    """Splitting on the FIRST '@' would treat part of the password as a host."""
    assert cli.parsed_endpoints(
        "mongodb://user:p@ss@real-host.example.net:27017/db") == [
            "mongodb://real-host.example.net:27017"]


@pytest.mark.parametrize("bad", [
    "", "::::nonsense::::", "mongodb://", "no-scheme-at-all", "://host",
    "redis://host/",                       # not a Mongo scheme
    "mongodb+srv://host:27017/",           # SRV carries no port
    "mongodb://host:notaport/",
    "mongodb://host:99999/",
])
def test_an_unconfirmable_target_is_rejected_by_the_parser(bad):
    with pytest.raises(cli.UnparseableTarget):
        cli.parsed_endpoints(bad)


async def test_the_same_database_on_the_wrong_port_is_refused_before_connecting():
    """THE CASE THE DROPPED PORT LET THROUGH.

    Same scheme, same host, same database name — a different instance. Every
    check an operator would make by name passes.
    """
    out = Recorder()

    code = await cli.run(
        ["--database", "attorney_ai", "--apply",
         "--confirm-database", "attorney_ai",
         # The operator believes they are on the staging instance, :27018.
         "--confirm-endpoint", "mongodb://db.example.net:27018",
         "--booking-writes-frozen"],
        {cli.URI_ENV_VAR: PROD_PORT_URI}, connect=_never_connect, out=out)

    assert code == cli.EXIT_REFUSED
    assert "--confirm-endpoint does not match" in out.text
    assert "port is part of the endpoint" in out.text
    # `_never_connect` proves it refused before opening a connection.


async def test_the_same_database_on_the_wrong_host_is_refused_before_connecting():
    out = Recorder()

    code = await cli.run(
        ["--database", "attorney_ai", "--apply",
         "--confirm-database", "attorney_ai",
         "--confirm-endpoint", "mongodb+srv://staging-cluster.example.net",
         "--booking-writes-frozen"],
        {cli.URI_ENV_VAR: PROD_URI}, connect=_never_connect, out=out)

    assert code == cli.EXIT_REFUSED
    assert "Nothing was written" in out.text


async def test_the_refusal_does_not_reveal_the_real_endpoint():
    """Otherwise a wrong guess becomes a way to read the target out of the
    error message."""
    out = Recorder()

    await cli.run(
        ["--database", "attorney_ai", "--apply",
         "--confirm-database", "attorney_ai",
         "--confirm-endpoint", "mongodb+srv://staging-cluster.example.net",
         "--booking-writes-frozen"],
        {cli.URI_ENV_VAR: PROD_URI}, connect=_never_connect, out=out)

    assert "prod-cluster" not in out.text
    assert "hunter2" not in out.text


async def test_apply_without_any_endpoint_confirmation_is_refused():
    out = Recorder()

    code = await cli.run(
        ["--database", "attorney_ai", "--apply",
         "--confirm-database", "attorney_ai", "--booking-writes-frozen"],
        {cli.URI_ENV_VAR: PROD_URI}, connect=_never_connect, out=out)

    assert code == cli.EXIT_REFUSED
    assert "--confirm-endpoint" in out.text


async def test_a_replica_set_needs_every_endpoint_confirmed():
    out = Recorder()

    code = await cli.run(
        ["--database", "attorney_ai", "--apply",
         "--confirm-database", "attorney_ai",
         "--confirm-endpoint", "mongodb://a.example.net:27017",
         "--booking-writes-frozen"],
        {cli.URI_ENV_VAR: REPLICA_URI}, connect=_never_connect, out=out)

    assert code == cli.EXIT_REFUSED


async def test_a_replica_set_confirms_in_any_order():
    """The control: confirming both, reversed, is accepted — so the refusal
    above is about completeness, not ordering.

    Reaching `_never_connect` IS the pass condition: authorisation let it
    through and it went to open a connection.
    """
    out = Recorder()

    with pytest.raises(AssertionError, match="connected to"):
        await cli.run(
            ["--database", "attorney_ai", "--apply",
             "--confirm-database", "attorney_ai",
             "--confirm-endpoint", "mongodb://b.example.net:27017",
             "--confirm-endpoint", "mongodb://a.example.net:27017",
             "--booking-writes-frozen"],
            {cli.URI_ENV_VAR: REPLICA_URI}, connect=_never_connect, out=out)

    assert "does not match" not in out.text


async def test_a_malformed_confirmation_is_refused_not_compared():
    out = Recorder()

    code = await cli.run(
        ["--database", "attorney_ai", "--apply",
         "--confirm-database", "attorney_ai",
         "--confirm-endpoint", "just-a-hostname",
         "--booking-writes-frozen"],
        {cli.URI_ENV_VAR: PROD_URI}, connect=_never_connect, out=out)

    assert code == cli.EXIT_REFUSED
    assert "not a usable endpoint" in out.text


async def test_an_unparseable_target_is_refused_before_connecting():
    out = Recorder()

    code = await cli.run(
        ["--database", "attorney_ai", "--apply",
         "--confirm-database", "attorney_ai",
         "--confirm-endpoint", "mongodb://anything:27017",
         "--booking-writes-frozen"],
        {cli.URI_ENV_VAR: "::::nonsense::::"}, connect=_never_connect, out=out)

    assert code == cli.EXIT_REFUSED
    assert "does not name" in out.text


def test_redaction_keeps_the_endpoint_and_drops_the_password():
    # The endpoint is kept deliberately: echoing the target is the point.
    shown = cli.redact(PROD_PORT_URI)

    assert shown == "mongodb://db.example.net:27017"
    assert "hunter2" not in shown
    assert "u:" not in shown


def test_an_unparseable_uri_degrades_rather_than_leaking():
    """A malformed URI is exactly when a naive redactor falls back to the raw
    value."""
    assert "hunter2" not in cli.redact("::::not-a-uri::::hunter2")


async def test_a_dry_run_prints_the_endpoints_to_confirm(seeded):
    """So the operator copies them rather than guessing the spelling."""
    from app.db.mongodb import get_database

    await seeded["add"](f"legacy-{seeded['tag']}")
    out = Recorder()

    await cli.run(["--database", get_database().name], ENV,
                  connect=await _connector(get_database()), out=out)

    assert "--confirm-endpoint mongodb+srv://cluster0.example.net" in out.text


async def test_the_matching_endpoint_and_database_are_accepted(seeded):
    """The control: the guard refuses the wrong target, not every target."""
    from app.db.mongodb import get_database

    await seeded["add"](f"legacy-{seeded['tag']}")
    out = Recorder()

    code = await _apply(seeded, out, get_database())

    assert code == cli.EXIT_OK
    assert "APPLIED" in out.text


# ── 6. An apply that cannot be called complete ───────────────────────────────
#
# `written` used to be incremented unconditionally, so it equalled `planned` by
# construction and could never report that anything had gone wrong. These pin
# every way the count can now disagree — and that none of them prints APPLIED.

async def _apply(seeded, out, db=None):
    from app.db.mongodb import get_database

    database = db if db is not None else get_database()
    name = getattr(database, "name", "attorney_ai_test")
    return await cli.run(
        ["--database", name, "--apply", "--confirm-database", name,
         "--confirm-endpoint", "mongodb+srv://cluster0.example.net",
         "--booking-writes-frozen"],
        ENV, connect=await _connector(database), out=out)


class _DeletingUpdate:
    """A collection whose `update_one` races a delete, for real.

    The row is removed immediately BEFORE the update is issued, so Mongo itself
    returns `matched_count == 0` — which is what a row cancelled between the
    cursor reading it and the update reaching it produces. The counts are not
    manufactured: `backfill_occupied_slots` runs unmodified and observes the
    real result.
    """

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, item):
        return getattr(self._inner, item)

    async def update_one(self, filt, update, *a, **kw):
        await self._inner.delete_one({"_id": filt["_id"]})
        return await self._inner.update_one(filt, update, *a, **kw)


async def test_the_backfill_reports_a_genuinely_unmatched_update(seeded):
    """At the source, with a real `matched_count == 0` from Mongo."""
    from app.db.appointment_slot_preflight import APPOINTMENTS, backfill_occupied_slots
    from app.db.mongodb import get_database

    await seeded["add"](f"legacy-{seeded['tag']}")
    db = get_database()
    real_getitem = type(db).__getitem__

    def _wrapped(self, key):
        inner = real_getitem(self, key)
        return _DeletingUpdate(inner) if key == APPOINTMENTS else inner

    type(db).__getitem__ = _wrapped
    try:
        result = await backfill_occupied_slots(db, dry_run=False)
    finally:
        type(db).__getitem__ = real_getitem

    assert result["written"] == 0, "an unmatched update was counted as written"
    assert result["vanished"] == 1


async def test_a_vanished_row_is_partial_not_applied(seeded):
    """The same real race, through the CLI."""
    from app.db.appointment_slot_preflight import APPOINTMENTS
    from app.db.mongodb import get_database

    await seeded["add"](f"legacy-{seeded['tag']}")
    db = get_database()
    real_getitem = type(db).__getitem__

    def _wrapped(self, key):
        inner = real_getitem(self, key)
        return _DeletingUpdate(inner) if key == APPOINTMENTS else inner

    out = Recorder()
    type(db).__getitem__ = _wrapped
    try:
        code = await _apply(seeded, out, db)
    finally:
        type(db).__getitem__ = real_getitem

    assert code == cli.EXIT_PARTIAL
    assert "PARTIAL/UNKNOWN" in out.text
    assert "APPLIED" not in out.text
    assert "KEEP BOOKING WRITES FROZEN" in out.text
    assert "freeze was not in force" in out.text


async def test_a_short_write_count_is_partial(seeded, monkeypatch):
    from app.db import appointment_slot_preflight as pf
    from app.db.mongodb import get_database

    await seeded["add"](f"legacy-{seeded['tag']}")
    real = pf.backfill_occupied_slots

    async def _short(db, *, dry_run=True):
        result = await real(db, dry_run=dry_run)
        if not dry_run:
            return {**result, "written": max(result["written"] - 1, 0)}
        return result

    monkeypatch.setattr(pf, "backfill_occupied_slots", _short)
    out = Recorder()

    code = await _apply(seeded, out, get_database())

    assert code == cli.EXIT_PARTIAL
    assert "APPLIED" not in out.text
    assert "the plan had" in out.text


async def test_an_exception_mid_apply_is_partial_and_leaks_nothing(seeded, monkeypatch):
    from app.db import appointment_slot_preflight as pf
    from app.db.mongodb import get_database

    await seeded["add"](f"legacy-{seeded['tag']}")
    real = pf.backfill_occupied_slots

    async def _explodes(db, *, dry_run=True):
        if dry_run:
            return await real(db, dry_run=True)
        raise RuntimeError(f"mongodb://user:hunter2@{seeded['client_id']} lost")

    monkeypatch.setattr(pf, "backfill_occupied_slots", _explodes)
    out = Recorder()

    code = await _apply(seeded, out, get_database())

    assert code == cli.EXIT_PARTIAL
    assert "APPLIED" not in out.text
    assert "RuntimeError" in out.text, "the exception class is the useful part"
    assert "hunter2" not in out.text
    assert seeded["client_id"] not in out.text
    assert "restore from the backup" in out.text.lower()


async def test_a_failed_post_apply_verification_is_partial(seeded, monkeypatch):
    """THE WRITES ALREADY HAPPENED.

    A verification that cannot run does not mean they were fine — it means
    nobody knows, which is the same position as a failed apply. Failing
    specifically on the SECOND dry-run pass, so the plan and the write both
    succeed and only the confirmation is missing.
    """
    from app.db import appointment_slot_preflight as pf
    from app.db.mongodb import get_database

    await seeded["add"](f"legacy-{seeded['tag']}")
    real = pf.backfill_occupied_slots
    dry_runs = {"n": 0}

    async def _verify_explodes(db, *, dry_run=True):
        if dry_run:
            dry_runs["n"] += 1
            if dry_runs["n"] == 2:        # the post-apply pass
                raise RuntimeError(
                    f"mongodb://user:hunter2@host lost {seeded['client_id']}")
        return await real(db, dry_run=dry_run)

    monkeypatch.setattr(pf, "backfill_occupied_slots", _verify_explodes)
    out = Recorder()

    code = await _apply(seeded, out, get_database())

    assert code == cli.EXIT_PARTIAL
    assert "APPLIED" not in out.text
    assert "post-apply verification" in out.text
    assert "RuntimeError" in out.text
    assert "hunter2" not in out.text
    assert seeded["client_id"] not in out.text
    assert "KEEP BOOKING WRITES FROZEN" in out.text
    # The write really did happen — this is not a failure to apply.
    stored = await seeded["col"].find_one({"_id": f"legacy-{seeded['tag']}"})
    assert stored["occupied_slots"], "the rows were not actually written"


async def test_rows_still_needing_slots_after_the_apply_is_partial(seeded, monkeypatch):
    """The only check that reads the collection AFTER the write rather than
    trusting the counters the write returned."""
    from app.db import appointment_slot_preflight as pf
    from app.db.mongodb import get_database

    await seeded["add"](f"legacy-{seeded['tag']}")
    real = pf.backfill_occupied_slots
    calls = {"n": 0}

    async def _lies_on_verify(db, *, dry_run=True):
        result = await real(db, dry_run=dry_run)
        if dry_run:
            calls["n"] += 1
            if calls["n"] > 1:            # the post-apply pass
                return {**result, "planned": 1}
        return result

    monkeypatch.setattr(pf, "backfill_occupied_slots", _lies_on_verify)
    out = Recorder()

    code = await _apply(seeded, out, get_database())

    assert code == cli.EXIT_PARTIAL
    assert "APPLIED" not in out.text
    assert "still need slots" in out.text


async def test_a_clean_apply_reports_applied_and_exits_zero(seeded):
    """The control, so the partial paths are not passing because everything
    fails."""
    from app.db.mongodb import get_database

    await seeded["add"](f"legacy-{seeded['tag']}")
    out = Recorder()

    code = await _apply(seeded, out, get_database())

    assert code == cli.EXIT_OK
    assert "APPLIED" in out.text
    assert "PARTIAL" not in out.text
    assert "written  : 1" in out.text
    assert "vanished : 0" in out.text
