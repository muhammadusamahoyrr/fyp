"""Shared pytest fixtures.

Test tiers (see pytest.ini markers):
  * default      — pure, offline, deterministic. No DB, no network, no LLM.
                   These are the ones CI runs on every push.
  * integration  — needs MongoDB.  `pytest -m "not integration"` to skip.
                   Runs against a throwaway database, never the real one; see
                   _isolate_test_database below.
  * llm          — calls a real provider. Non-deterministic and costs tokens,
                   so it is never part of the default run.
"""
from __future__ import annotations

import base64
import importlib
import sys
from pathlib import Path

import os

import pytest

# Allow `import app...` when pytest is invoked from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


TEST_DB_SUFFIX = "_test"

#: A throwaway AES-256 key for the suite. NOT a secret and not a fallback: the
#: application refuses to store a signature when `SIGNATURE_ENCRYPTION_KEY` is
#: unset, which is the behaviour we want in production and an obstacle in a test
#: run that signs hundreds of agreements. Fixed rather than random so a failure
#: is reproducible, and obviously disposable so nobody mistakes it for a real
#: one. Set here, session-wide, because a per-test key would make a ciphertext
#: written by one test undecryptable in the next.
TEST_SIGNATURE_KEY = base64.b64encode(b"attorney-ai test signature key!!").decode()


@pytest.fixture(scope="session", autouse=True)
def _signature_encryption_key():
    """Give the suite a signature key without touching the developer's `.env`."""
    from app.core.config import settings

    previous = getattr(settings, "signature_encryption_key", "")
    settings.signature_encryption_key = TEST_SIGNATURE_KEY
    yield
    settings.signature_encryption_key = previous


@pytest.fixture(autouse=True)
def _no_background_embeds(monkeypatch):
    """Stop KYC approvals and profile edits from embedding for real.

    `schedule_embed` puts a task on the running loop. Under pytest each test
    gets its own loop, which is torn down the moment the test returns, so a
    real embed is destroyed mid-flight ("Task was destroyed but it is
    pending!") — after having loaded a 26-second CPU model and written to the
    developer's ChromaDB directory, which no test asked it to do.

    Autouse for the same reason as the database override above: an opt-in
    guard only protects the tests that remember to opt in. Tests that want to
    assert on indexing patch this again themselves, and win by fixture order.
    """
    try:
        from app.ai import lawyer_embeddings
    except Exception:  # pragma: no cover - AI extras not installed
        return
    monkeypatch.setattr(lawyer_embeddings, "schedule_embed", lambda _id: False)
    monkeypatch.setattr(lawyer_embeddings, "forget_lawyers", lambda ids: 0)


def _looks_like_the_configured_uri(candidate: str | None, configured: str) -> bool:
    """Is this candidate the application's own database?

    Compared on HOST, not on the whole string. The configured URI carries
    credentials and options that a hand-written test URI would not repeat, so an
    exact-string check would wave through `mongodb+srv://user:pw@prod-host/?x=1`
    against a candidate naming the same host. The host is the part that decides
    which server is written to.
    """
    if not candidate:
        return False

    def host_of(uri: str) -> str:
        without_scheme = uri.split("://", 1)[-1]
        authority = without_scheme.split("/", 1)[0]
        return authority.split("@")[-1].split("?")[0].lower()

    configured_host = host_of(configured or "")
    # A configured URI that is itself localhost is not a production target, and
    # refusing it would make the suite unrunnable for a local-only developer.
    if not configured_host or configured_host.startswith(("localhost", "127.0.0.1")):
        return False
    return host_of(candidate) == configured_host


@pytest.fixture(scope="session", autouse=True)
def _isolate_test_database():
    """Point every database read and write at a throwaway database.

    This suite used to connect to whatever `settings.db_name` names, which in a
    developer checkout is the live application database. Nothing enforced that
    a test touched only its own documents -- one broad delete_many, or a
    teardown that quietly stops being reached, and real data is gone with no
    backup step anywhere in between.

    get_database() resolves settings.db_name on every call, so overriding it
    here redirects the application code under test as well as the fixtures.
    While this is in force there is no path left that reaches production.

    Autouse and session-scoped on purpose: an opt-in guard protects only the
    tests that remember to opt in, which is the property that failed here.
    """
    from app.core.config import settings

    original = settings.db_name
    if not original.endswith(TEST_DB_SUFFIX):
        settings.db_name = f"{original}{TEST_DB_SUFFIX}"
    try:
        yield settings.db_name
    finally:
        settings.db_name = original


@pytest.fixture(scope="session", autouse=True)
def _isolate_upload_root(tmp_path_factory):
    """Point every file the suite generates at a throwaway directory.

    The same failure as `_isolate_test_database`, one layer down. Tests call the
    real `generate_pdf`, which writes to `{upload_root}/docs` -- in a developer
    checkout that is the live upload directory. One run of the V2 suites left
    320 files there: 302 `legacy-<hex>.pdf` fixtures plus the wakalatnama and
    guardianship samples, indistinguishable by name from real client documents
    and growing on every run. Found while verifying the DOCUMENTS_V2 migration,
    where a directory that should have been static had gained 305 files.

    Nothing was corrupted -- the writes are all new filenames, never overwrites
    -- but a test suite has no business writing into the directory the
    application serves, and a census of that directory cannot be trusted while
    it does.

    THREE MODULES SNAPSHOT THE SETTING AT IMPORT, so repointing `settings`
    alone would miss them: `pdf_generator.UPLOADS_DIR`,
    `intake_service._EVIDENCE_DIR` and `file_handler.UPLOADS_ROOT` are all
    module-level constants evaluated once. `artifact_store` resolves it per
    call and needs only the setting. Each is patched to match.

    Autouse and session-scoped for the reason given above: an opt-in guard
    protects only the tests that remember to opt in, which is the property that
    failed here.
    """
    from app.core.config import settings

    root = tmp_path_factory.mktemp("upload_root")
    original = settings.upload_root
    settings.upload_root = str(root)

    # (module path, attribute, value) -- patched only if the module imports.
    patched: list[tuple[object, str, object]] = []
    for module_path, attribute, value in (
        ("app.services.pdf_generator", "UPLOADS_DIR", root / "docs"),
        ("app.services.intake_service", "_EVIDENCE_DIR", root / "evidence"),
        ("app.utils.file_handler", "UPLOADS_ROOT", root),
    ):
        try:
            module = importlib.import_module(module_path)
        except Exception:                   # optional extras may not install
            continue
        patched.append((module, attribute, getattr(module, attribute)))
        setattr(module, attribute, value)

    try:
        yield root
    finally:
        settings.upload_root = original
        for module, attribute, value in patched:
            setattr(module, attribute, value)


@pytest.fixture
async def mongo():
    """Connect Mongo for an integration test, or skip it if unreachable.

    Function-scoped on purpose. A motor client is bound to the event loop it was
    created on, and pytest-asyncio gives each test a fresh loop — a session-scoped
    client would be reused across loops and hang.

    Skipping (not failing) is also deliberate: a developer without a local Mongo
    should still get a green unit run rather than a wall of red that hides real
    failures.
    """
    from app.core.config import settings
    from app.db.mongodb import connect_db, get_database

    # NEVER the configured URI.
    #
    # This used to fall back to `settings.mongodb_url` when a local Mongo was
    # unreachable, and that URI points at the hosted cluster. Two things went
    # wrong with it, and the second is the serious one.
    #
    # It was slow and non-deterministic: runs across the internet took 15+
    # minutes with tests silently skipped on a DNS blip, so a green run stopped
    # meaning the guarantees held.
    #
    # And it was WRONG ABOUT WHAT IT WAS TESTING. The hosted cluster does not
    # carry the V2 unique indexes, and those indexes ARE the guarantee that
    # concurrent generation is idempotent — the application code races and the
    # index is what resolves the race. So the concurrency test passed locally
    # and failed on the fallback, for a reason that had nothing to do with the
    # code under test. A suite that quietly reaches for production to answer a
    # question about correctness gives the wrong answer twice: it can pass when
    # the code is broken, and fail when it is fine.
    #
    # So: an explicit test URI, or a local Mongo, or skip. Never the configured
    # one, even if it is reachable and everything else has failed.
    original_url = settings.mongodb_url
    explicit = os.environ.get("AAI_TEST_MONGO_URL")
    candidates = [explicit] if explicit else ["mongodb://localhost:27017"]

    connected = False
    last_error = "no candidate URI"
    for url in candidates:
        if _looks_like_the_configured_uri(url, original_url):
            last_error = (
                "refusing to run integration tests against the configured "
                "database URI — set AAI_TEST_MONGO_URL to a throwaway instance")
            continue
        settings.mongodb_url = url
        try:
            await connect_db()
            await get_database().command("ping")
            connected = True
            break
        except Exception as exc:  # noqa: BLE001
            last_error = f"{url.split('@')[-1][:40]}: {exc}"

    if not connected:
        settings.mongodb_url = original_url
        pytest.skip(
            "MongoDB unavailable — start a local instance or set "
            f"AAI_TEST_MONGO_URL ({last_error})")

    db = get_database()
    # Tripwire, not decoration. If the override above is ever removed or
    # shadowed, an integration test must refuse to run rather than discover the
    # problem by writing to the real corpus.
    assert db.name.endswith(TEST_DB_SUFFIX), (
        f"refusing to run an integration test against {db.name!r}: "
        "the test-database override is not in force"
    )

    await ensure_v2_indexes(db)
    await ensure_ocr_indexes(db)

    try:
        yield db
    finally:
        settings.mongodb_url = original_url


# Indexes that are not an optimisation but a CORRECTNESS PRIMITIVE.
#
# `(document_id, idempotency_key)` unique is what makes concurrent generation
# idempotent. The application code genuinely races — two requests carrying one
# key both read "no revision yet" and both try to insert — and the index is what
# resolves the race, by making the second insert fail so its caller falls back to
# reading the winner.
#
# Nothing in the application creates them at test time: `create_all_indexes()`
# runs on startup, which a test never performs. So whether the concurrency test
# passed came down to whether somebody had happened to run index creation
# against the test database earlier. It passed on a machine where they had, and
# failed on a fresh one, for a reason with nothing to do with the code.
#
# Creating them here makes the guarantee the test asserts actually present.
# The test database builds its V2 indexes from THE SAME MANIFEST production
# uses. It used to keep its own two lists, and they had already drifted: the
# review-events index was created here under a name production never uses, which
# only appeared to work because Mongo refused the duplicate and this fixture
# swallowed "already exists". A test database that differs from production tests
# a different system.


async def ensure_v2_indexes(db) -> None:
    """Create every V2 index on the TEST database, idempotently.

    EXACTLY AS PRODUCTION CREATES THEM — same keys, same options, same names —
    because they come from the same `IndexSpec` objects. An index here that were
    laxer than production would let a test pass on a constraint production does
    not have; one that were stricter would fail on data production accepts.

    The consequence is that a fixture inserting two revisions with a null
    idempotency key collides, which is the index doing its job and is how the
    real system behaves.
    """
    from pymongo.errors import OperationFailure

    from app.db.v2_index_spec import V2_INDEX_REQUIREMENTS, evaluate

    # Mongo error codes, not message text. Matching on `"already exists" in
    # str(exc)` reads a human-facing string that varies by server version and
    # driver, and it swallows anything else that happens to contain the phrase.
    INDEX_OPTIONS_CONFLICT = 85    # same name, different options
    INDEX_KEY_SPECS_CONFLICT = 86  # same keys, different name

    for spec in V2_INDEX_REQUIREMENTS:
        info = await db[spec.collection].index_information()

        if spec.name in info:
            # VALIDATED, not skipped. A same-name index left over from an
            # earlier shape — say the pre-`_id` queue index — would otherwise be
            # accepted silently, and every plan test would then measure an index
            # production no longer declares.
            problem = evaluate(spec, info)
            if problem is None:
                continue
            await db[spec.collection].drop_index(spec.name)

        try:
            await db[spec.collection].create_indexes([spec.model()])
        except OperationFailure as exc:
            # An equivalent index under a different name is fine — validation
            # accepts those on an exact match of keys AND options, so re-check
            # rather than assume. Anything else must NOT be swallowed: the tests
            # that depend on this index would then pass for the wrong reason.
            if exc.code not in (INDEX_OPTIONS_CONFLICT, INDEX_KEY_SPECS_CONFLICT):
                raise
            info = await db[spec.collection].index_information()
            if evaluate(spec, info) is not None:
                raise


async def ensure_ocr_indexes(db) -> None:
    """Install OCR correctness indexes from the production declaration.

    The OCR repository handles a duplicate-key race as the idempotent retry
    path. Without the unique index that path is never exercised: two identical
    readings are both stored successfully. Building the test index from the
    same ``index_models`` function as application startup prevents the fixture
    from drifting into a different contract.
    """
    from app.repositories.ocr_revision_repo import index_models

    await db["ocr_revisions"].create_indexes(index_models())


@pytest.fixture
def stub_grader_llm():
    """Stub retrieval_grader_node's LLM at its real seam: get_fast_llm().

    The grader calls `get_fast_llm().invoke(...)` and parses `response.content`
    as a JSON array that must contain exactly one grade per graded chunk — a
    wrong-length reply is rejected and the node degrades to neutral grades. That
    degradation path is why patching a nonexistent name still produced a green
    test: the real provider call failed, the except branch caught it, and the
    node carried on. So this stub returns a correctly sized array AND records
    that it was called, so a test can assert the seam was genuinely exercised
    rather than bypassed.

    Also neutralises the two Redis writers reached via _record_observation, so a
    unit test touches no external state.

    Returns a dict; read `["calls"]` after the node runs.
    """
    def _install(grader_module, monkeypatch, n_grades: int, grade: float = 1.0):
        state = {"calls": 0, "messages": None}

        class _Response:
            def __init__(self, content):
                self.content = content

        class _LLM:
            def invoke(self, messages):
                state["calls"] += 1
                state["messages"] = messages
                import json as _json
                return _Response(_json.dumps([grade] * n_grades))

        monkeypatch.setattr(grader_module, "get_fast_llm", lambda **_kw: _LLM())

        async def _no_redis(*a, **k):
            return None

        monkeypatch.setattr(grader_module, "record_query", _no_redis)
        monkeypatch.setattr(grader_module, "record_score_for_drift", _no_redis)
        return state

    return _install


# ── Application indexes on the test database ─────────────────────────────────
#
# `ensure_v2_indexes` above covers the DOCUMENTS_V2 collections only. Everything
# else `create_all_indexes()` declares — the unique constraints on payment
# events, case numbers, pending appointments, pending engagements, reviews,
# emails, bar numbers — was absent from the test database entirely, because
# `create_all_indexes()` runs at application startup and a test never performs
# one. So a guarantee enforced in production by an index was enforced in tests
# by nothing, and a test asserting a duplicate is refused would let the
# duplicate through and pass.

_APP_INDEXES_BUILT: set[str] = set()


async def ensure_app_indexes(db) -> None:
    """Create every application index on the TEST database, from production.

    Calls `create_all_indexes()` itself rather than restating what it builds.
    A second list would be a copy of production that nothing keeps in step, and
    the moment the two drifted the tests would be proving a constraint the
    application does not actually have — which is the failure this exists to
    remove, reintroduced one layer up.

    `_try_unique_partial` LOGS AND CONTINUES when a unique index cannot be
    created, which is right for a production deployment carrying legacy
    duplicates: refusing to start would be worse than running unenforced. In a
    test it is the exact hazard being fixed — a silently absent constraint that
    every later assertion then passes without. So the warning is captured and
    promoted to a hard failure here, and nowhere else.

    Built once per database per session: the operation is idempotent but not
    free, and the test database persists across tests within a run.
    """
    if db.name in _APP_INDEXES_BUILT:
        return

    import logging

    from app.db import indexes as _indexes

    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    handler = _Capture()
    _indexes.logger.addHandler(handler)
    try:
        await _indexes.create_all_indexes()
    finally:
        _indexes.logger.removeHandler(handler)

    skipped = [r.getMessage() for r in captured
               if "Could not create" in r.getMessage()]
    if skipped:
        raise RuntimeError(
            "index creation was skipped on the test database, so the "
            "constraints below are NOT in force and any test relying on them "
            "would pass without them:\n  " + "\n  ".join(skipped)
        )

    # Superseded appointment indexes, dropped ON THE TEST DATABASE ONLY.
    #
    # `_appointments_indexes` no longer CREATES `uniq_pending_slot`, but a test
    # database built by an earlier run still carries it — and it is not inert.
    # Being unique on (lawyer_id, scheduled_at) and scoped to PENDING, it
    # refuses writes the new indexes allow: a second PENDING booking at the
    # same lawyer and instant. Tests would then be measuring a database
    # enforcing a rule the code no longer has.
    #
    # Production does this through the operator-run preflight command, inside
    # the write freeze, never automatically: dropping an index is irreversible
    # without another build. Here the drop is safe and necessary, and it is the
    # test-side equivalent of the rollout step.
    from app.db.appointment_index_spec import OBSOLETE_INDEXES

    for collection, index_name, _why in OBSOLETE_INDEXES:
        try:
            await db[collection].drop_index(index_name)
        except Exception:  # noqa: BLE001 - absent is the expected state
            pass

    # The appointment correctness indexes are created EXPLICITLY, because
    # production no longer creates them at startup.
    #
    # That is the point of the split: a deploy that builds these would repair
    # correctness state as a side effect of restarting, and nobody could then
    # tell whether the guarantee held yesterday. Tests need the same indexes
    # production will have, so they ask for them by name — the way an operator
    # does, on a database they own.
    await _indexes.create_appointment_correctness_indexes()

    # CREATION IS NOT THE SAME CHECK AS VALIDATION.
    #
    # The block above catches an index that was not created. It cannot catch
    # one that WAS created and is wrong — the classic case being an index left
    # over from an earlier definition, which Mongo keeps in place while
    # refusing the new options. The appointment overlap guards are now the
    # mechanism preventing double-booking rather than a nicety, so the fixture
    # asks the canonical specification whether what exists is what was
    # specified, instead of assuming a silent create means a correct index.
    problems = await _indexes.validate_appointment_indexes()
    if problems:
        raise RuntimeError(
            "appointment correctness indexes are not valid on the test "
            "database, so overlap and idempotency are NOT enforced and any "
            "test relying on them would pass without them:\n  "
            + "\n  ".join(str(p) for p in problems)
        )

    _APP_INDEXES_BUILT.add(db.name)


@pytest.fixture
async def app_indexes(mongo):
    """Opt in to the real application indexes for this test.

    Opt-in rather than autouse, deliberately and for now: switching the whole
    suite onto production constraints at once changes what every existing
    integration test is allowed to write, and that belongs in its own change
    with its own measurement — not smuggled in beside new tests.
    """
    await ensure_app_indexes(mongo)
    return mongo


@pytest.fixture
async def mongo_transactional(mongo):
    """A database that genuinely supports multi-document transactions, or a skip.

    WHY THIS EXISTS

    Agreement sign and decline run inside `session.with_transaction` and FAIL
    CLOSED when transactions are unavailable -- they refuse rather than fall
    back to the four separate writes whose interleaving they exist to prevent.

    Production is Atlas, which is a replica set, so transactions are available
    there. `mongo` above connects to a local `mongodb://localhost:27017`, which
    is ordinarily a STANDALONE, where transactions raise. A test asserting
    atomic behaviour against a standalone would test the refusal path and prove
    nothing about the transactional one.

    SKIPS, LOUDLY, AND DOES NOT PRETEND. The alternative -- mocking the session
    so the body runs without a transaction -- would assert the code's happy path
    while removing the only property under test. A skip with a reason is honest
    about the gap; a green test that verified nothing would not be.

    To run these locally, point AAI_TEST_MONGO_URL at a single-node replica set:

        mongod --replSet rs0 --dbpath <dir> --port 27018
        mongosh --port 27018 --eval 'rs.initiate()'
        AAI_TEST_MONGO_URL=mongodb://localhost:27018/?replicaSet=rs0 pytest ...
    """
    hello = await mongo.client.admin.command("hello")
    if not (hello.get("setName") or hello.get("msg") == "isdbgrid"):
        pytest.skip(
            "multi-document transactions need a replica set or mongos; this "
            "connection is a standalone. Set AAI_TEST_MONGO_URL to a "
            "replica-set URI to run the agreement transaction tests."
        )
    return mongo
