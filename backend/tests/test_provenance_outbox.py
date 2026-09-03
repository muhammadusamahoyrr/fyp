"""A turn is audited, or it says it is not. Never a third thing.

`record_answer` used to catch every exception and return None. The answer went
to the user regardless, so a turn could be answered, billed and displayed with
no audit record — and nothing said so. The claim that every turn is audited was
true only when the database happened to be reachable.

These cover the two halves of the fix: a failed direct write is parked and
delivered later, and the turn reports which of the three things happened
(durable / queued / lost) rather than a boolean that was always true.

Integration where the property IS a database semantic — a conditional update
either matches or it does not, and no fake can settle whether two relays racing
for one entry both win. No provider is called in this file.
"""
import asyncio
import secrets
from datetime import timedelta, timezone

import pytest

from app.services import provenance_outbox as outbox
from app.services import provenance_service


@pytest.fixture
async def clean(mongo):
    """An empty outbox, and no provenance for this file's request ids."""
    from app.db.collections import get_answer_provenance_col

    # Captured now, while the real accessors are still in place. Several tests
    # monkeypatch these to simulate a database failure, and teardown ordering
    # would otherwise hand the cleanup a collection that raises on everything.
    outbox_col = outbox.get_provenance_outbox_col()
    provenance_col = get_answer_provenance_col()

    async def wipe():
        await outbox_col.delete_many({"_id": {"$regex": "^obx-"}})
        await provenance_col.delete_many({"request_id": {"$regex": "^obx-"}})

    outbox._reset_index_cache()
    await wipe()
    yield
    await wipe()


def rid(label="x"):
    return f"obx-{label}-{secrets.token_hex(4)}"


def record_for(request_id):
    """A minimal provenance record. Shape does not matter here — delivery does."""
    return {"request_id": request_id, "session_id": "s1", "user_id": "u1",
            "query": "a question", "answer": "an answer"}


async def provenance_count(request_id):
    from app.db.collections import get_answer_provenance_col
    return await get_answer_provenance_col().count_documents(
        {"request_id": request_id})


class Boom(Exception):
    """A transient database failure."""


# ══════════════════════════════════════════════════════════════════════════════
# The three outcomes
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_healthy_write_is_durable_and_never_touches_the_outbox(clean):
    request_id = rid("ok")
    outcome, returned = await provenance_service.record_outcome(
        state={"query": "q", "answer": "a"}, session_id="s1", user_id="u1",
        request_id=request_id)

    assert outcome == outbox.DURABLE
    assert returned == request_id
    assert await provenance_count(request_id) == 1
    assert await outbox.pending_ids() == [], (
        "the fast path created an outbox entry it did not need")


async def test_a_failed_write_is_queued_not_lost(clean, monkeypatch):
    """The failure the whole module exists for. The record is not in its final
    home yet, but it IS durable, and the turn may honestly say so."""
    request_id = rid("queued")

    class _Failing:
        async def insert_one(self, doc):
            raise Boom("primary stepped down")

    monkeypatch.setattr(provenance_service, "get_answer_provenance_col",
                        lambda: _Failing())

    outcome, returned = await provenance_service.record_outcome(
        state={"query": "q", "answer": "a"}, session_id="s1", user_id="u1",
        request_id=request_id)

    assert outcome == outbox.QUEUED
    assert returned == request_id
    assert request_id in await outbox.pending_ids()


async def test_both_writes_failing_is_reported_as_lost(clean, monkeypatch):
    """The only honest report when there is no record and none is coming. It
    used to be indistinguishable from success."""
    request_id = rid("lost")

    class _Failing:
        async def insert_one(self, doc):
            raise Boom("everything is down")

    monkeypatch.setattr(provenance_service, "get_answer_provenance_col",
                        lambda: _Failing())
    monkeypatch.setattr(outbox, "get_provenance_outbox_col", lambda: _Failing())

    outcome, returned = await provenance_service.record_outcome(
        state={"query": "q", "answer": "a"}, session_id="s1", user_id="u1",
        request_id=request_id)

    assert outcome == outbox.LOST
    assert returned is None


async def test_a_record_that_cannot_be_built_is_lost_not_silently_dropped(
        clean, monkeypatch):
    """There is nothing to park, so this path is LOST by construction — but it
    must still be reported rather than swallowed."""
    def _explode(*a, **k):
        raise Boom("state was not what build_record expected")

    monkeypatch.setattr(provenance_service, "build_record", _explode)

    outcome, _ = await provenance_service.record_outcome(
        state={}, session_id="s1", user_id="u1", request_id=rid("unbuildable"))
    assert outcome == outbox.LOST


async def test_record_answer_keeps_its_original_contract(clean):
    """Three existing call sites depend on the old return type. Queued counts
    as recorded, because the record is durable and will arrive."""
    request_id = rid("compat")
    assert await provenance_service.record_answer(
        state={"query": "q", "answer": "a"}, session_id="s1", user_id="u1",
        request_id=request_id) == request_id


# ══════════════════════════════════════════════════════════════════════════════
# What the caller tells the user
# ══════════════════════════════════════════════════════════════════════════════

def test_queued_counts_as_saved_and_says_it_is_pending():
    """A queued record IS durable — it is just not in its final home yet.
    Reporting it as unsaved would train users to ignore a warning that is
    usually wrong, and a warning nobody reads protects nobody."""
    assert outbox.describe_outcome(outbox.QUEUED) == {
        "audit_saved": True, "audit_pending": True}


def test_durable_is_saved_and_not_pending():
    assert outbox.describe_outcome(outbox.DURABLE) == {
        "audit_saved": True, "audit_pending": False}


def test_only_lost_reports_an_unaudited_turn():
    assert outbox.describe_outcome(outbox.LOST)["audit_saved"] is False
    assert outbox.describe_outcome(None)["audit_saved"] is False


# ══════════════════════════════════════════════════════════════════════════════
# Delivery
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_relay_delivers_a_parked_record_and_removes_it(clean):
    request_id = rid("deliver")
    assert await outbox.park(request_id, record_for(request_id))

    result = await outbox.drain_once()

    assert result["delivered"] == 1
    assert await provenance_count(request_id) == 1
    # Removed on delivery: the record's home is the provenance collection, and
    # keeping a copy here would make the outbox a second retained store of user
    # text with no policy of its own.
    assert await outbox.pending_ids() == []


async def test_draining_an_empty_outbox_is_a_no_op(clean):
    assert await outbox.drain_once() == {"delivered": 0, "deferred": 0}


async def test_a_failed_delivery_is_deferred_not_dropped(clean, monkeypatch):
    request_id = rid("defer")
    await outbox.park(request_id, record_for(request_id))

    class _Failing:
        async def insert_one(self, doc):
            raise Boom("still down")

    monkeypatch.setattr(outbox, "get_answer_provenance_col", lambda: _Failing())
    result = await outbox.drain_once()

    assert result == {"delivered": 0, "deferred": 1}
    entry = await outbox.get_provenance_outbox_col().find_one({"_id": request_id})
    assert entry["status"] == outbox.STATUS_PENDING
    assert entry["attempts"] == 1
    assert entry["lease_owner"] is None, "a deferred entry still holds its lease"


async def test_backoff_pushes_the_next_attempt_into_the_future(clean, monkeypatch):
    """Otherwise every worker retries a database that is down as fast as it
    can, which is the worst possible thing to do to a recovering primary."""
    request_id = rid("backoff")
    await outbox.park(request_id, record_for(request_id))

    class _Failing:
        async def insert_one(self, doc):
            raise Boom("down")

        async def create_indexes(self, models):
            # `ensure_indexes` also ensures the DESTINATION's unique index, and
            # a fake that cannot answer it aborts the whole drain before any
            # delivery is attempted — which would make these tests pass for the
            # wrong reason.
            return []

    monkeypatch.setattr(outbox, "get_answer_provenance_col", lambda: _Failing())
    await outbox.drain_once()

    # A second drain finds nothing claimable: the entry is not due yet.
    assert await outbox.drain_once() == {"delivered": 0, "deferred": 0}


async def test_backoff_grows(clean):
    first = outbox._backoff(1)
    later = outbox._backoff(4)
    assert later > first
    assert outbox._backoff(50).total_seconds() == outbox._BACKOFF_CAP_SECONDS


# ══════════════════════════════════════════════════════════════════════════════
# Idempotency and duplicate delivery
# ══════════════════════════════════════════════════════════════════════════════

async def test_parking_the_same_turn_twice_makes_one_entry(clean):
    """The request id IS the outbox key, so this is a duplicate-key error
    rather than two entries racing to deliver one record."""
    request_id = rid("twice")
    assert await outbox.park(request_id, record_for(request_id))
    assert await outbox.park(request_id, record_for(request_id))

    assert await outbox.get_provenance_outbox_col().count_documents(
        {"_id": request_id}) == 1


async def test_a_redelivery_of_an_already_recorded_turn_counts_as_delivered(clean):
    """The outbox is at-least-once by design, so duplicates must be harmless.

    The common cause is benign: a direct insert that COMMITTED and then timed
    out before acknowledging, so the record was already in the audit trail when
    the apparent failure parked it."""
    from app.db.collections import get_answer_provenance_col

    request_id = rid("dupe")
    await get_answer_provenance_col().insert_one(record_for(request_id))
    await outbox.park(request_id, record_for(request_id))

    result = await outbox.drain_once()

    assert result["delivered"] == 1, (
        "an already-recorded turn was treated as a delivery failure and would "
        "retry forever")
    assert await provenance_count(request_id) == 1, "the record was duplicated"
    assert await outbox.pending_ids() == []


async def test_a_direct_write_that_lost_the_race_is_still_durable(clean):
    """Two workers recording one turn. The unique index decides, and the loser
    must report DURABLE — the record is there, it just did not write it."""
    from app.db.collections import get_answer_provenance_col

    request_id = rid("race")
    await get_answer_provenance_col().insert_one(record_for(request_id))

    outcome, _ = await provenance_service.record_outcome(
        state={"query": "q", "answer": "a"}, session_id="s1", user_id="u1",
        request_id=request_id)

    assert outcome == outbox.DURABLE
    assert await outbox.pending_ids() == [], (
        "a turn already in the audit trail was parked for redelivery")


# ══════════════════════════════════════════════════════════════════════════════
# Crash recovery and concurrency
# ══════════════════════════════════════════════════════════════════════════════

async def test_two_relays_racing_deliver_one_record_once(clean):
    """The claim is a conditional update, so exactly one relay wins. This is
    why the relay needs no Redis lock and no leader election."""
    ids = [rid(f"race{i}") for i in range(6)]
    for request_id in ids:
        await outbox.park(request_id, record_for(request_id))

    results = await asyncio.gather(*(outbox.drain_once() for _ in range(4)))

    assert sum(r["delivered"] for r in results) == len(ids), (
        "an entry was delivered twice, or not at all")
    for request_id in ids:
        assert await provenance_count(request_id) == 1
    assert await outbox.pending_ids() == []


async def test_an_entry_whose_relay_died_is_reclaimed_when_its_lease_expires(
        clean, monkeypatch):
    """A relay that dies mid-delivery holds a lease it will never release.
    Nothing may be stranded behind it."""
    request_id = rid("crash")
    await outbox.park(request_id, record_for(request_id))

    # A relay claims it and then the process disappears.
    claimed = await outbox._claim("dead-worker", outbox._now())
    assert claimed is not None
    assert await outbox.drain_once() == {"delivered": 0, "deferred": 0}, (
        "a leased entry was stolen from a relay that might still be working")

    # The lease lapses.
    from datetime import timedelta
    await outbox.get_provenance_outbox_col().update_one(
        {"_id": request_id},
        {"$set": {"lease_expires_at": outbox._now() - timedelta(seconds=1)}})

    assert (await outbox.drain_once())["delivered"] == 1


async def test_a_drain_is_bounded(clean):
    """One pass must not hold a lease over the whole backlog, which would stall
    every other relay behind a single slow worker."""
    for i in range(5):
        request_id = rid(f"batch{i}")
        await outbox.park(request_id, record_for(request_id))

    assert (await outbox.drain_once(limit=2))["delivered"] == 2
    assert len(await outbox.pending_ids()) == 3


# ══════════════════════════════════════════════════════════════════════════════
# Giving up, and keeping the evidence
# ══════════════════════════════════════════════════════════════════════════════

async def test_an_undeliverable_record_is_kept_not_discarded(clean, monkeypatch):
    """An undeliverable record is the single most interesting document in this
    collection — it is the evidence that the audit trail has a hole. Deleting
    it would destroy exactly that."""
    request_id = rid("giveup")
    await outbox.park(request_id, record_for(request_id))
    await _expire_deadline(request_id)

    class _Failing:
        async def insert_one(self, doc):
            raise Boom("permanently broken")

    monkeypatch.setattr(outbox, "get_answer_provenance_col", lambda: _Failing())
    await outbox.drain_once()

    entry = await outbox.get_provenance_outbox_col().find_one({"_id": request_id})
    assert entry is not None, "the evidence of a lost audit record was deleted"
    assert entry["status"] == outbox.STATUS_FAILED


async def test_a_failed_entry_is_not_retried_forever(clean, monkeypatch):
    request_id = rid("nolonger")
    await outbox.park(request_id, record_for(request_id))
    await outbox.get_provenance_outbox_col().update_one(
        {"_id": request_id}, {"$set": {"status": outbox.STATUS_FAILED}})

    assert await outbox.drain_once() == {"delivered": 0, "deferred": 0}


async def test_the_stored_error_never_carries_a_driver_message(clean, monkeypatch):
    """A driver error names hosts, ports, replica-set members and sometimes
    credentials. This field sits next to user text and is read by operators."""
    request_id = rid("secret")
    await outbox.park(request_id, record_for(request_id))

    class _Failing:
        async def insert_one(self, doc):
            raise Boom("mongodb://admin:hunter2@prod-rs0.internal:27017 refused")

    monkeypatch.setattr(outbox, "get_answer_provenance_col", lambda: _Failing())
    await outbox.drain_once()

    entry = await outbox.get_provenance_outbox_col().find_one({"_id": request_id})
    assert entry["last_error"] == "Boom"
    assert "hunter2" not in str(entry)
    assert "prod-rs0" not in str(entry)


# ══════════════════════════════════════════════════════════════════════════════
# Monitoring
# ══════════════════════════════════════════════════════════════════════════════

async def test_stats_counts_what_is_waiting(clean):
    for i in range(3):
        request_id = rid(f"stat{i}")
        await outbox.park(request_id, record_for(request_id))

    reported = await outbox.stats()
    assert reported["available"] is True
    assert reported["pending"] >= 3
    assert reported["oldest_pending_seconds"] is not None


async def test_stats_never_reports_zero_when_it_cannot_read(clean, monkeypatch):
    """A monitor that cannot reach the collection must not display "nothing
    pending" — that is the one reading an operator would act on by doing
    nothing."""
    class _Failing:
        async def count_documents(self, *a, **k):
            raise Boom("unreachable")

    monkeypatch.setattr(outbox, "get_provenance_outbox_col", lambda: _Failing())
    reported = await outbox.stats()

    assert reported["available"] is False
    assert reported["pending"] is None
    assert reported["failed"] is None


async def test_an_empty_outbox_reports_no_age(clean):
    reported = await outbox.stats()
    assert reported["oldest_pending_seconds"] is None


# ══════════════════════════════════════════════════════════════════════════════
# Retention: nothing here expires by itself
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_outbox_has_no_ttl_index(clean):
    """Deliberate, and asserted so it cannot be added absent-mindedly.

    A TTL here would silently destroy the record of turns whose audit write
    failed — the exact records that matter most — and the retention period is
    not this module's decision to make."""
    await outbox.ensure_indexes()
    indexes = await outbox.get_provenance_outbox_col().index_information()
    for name, spec in indexes.items():
        assert "expireAfterSeconds" not in spec, (
            f"index {name} expires outbox entries on a period nobody chose")


# ══════════════════════════════════════════════════════════════════════════════
# The retry deadline — exactly when pending becomes failed
# ══════════════════════════════════════════════════════════════════════════════
#
# This module used to terminate after seven attempts and document that as
# "roughly two hours". It was five minutes and twenty seconds. The error
# survived review because an attempt count expresses a duration only through an
# arithmetic series, so nobody could see it was wrong by reading it.
#
# These assert the boundary in the units the guarantee is stated in.

async def _set_deadline(request_id, when):
    await outbox.get_provenance_outbox_col().update_one(
        {"_id": request_id},
        {"$set": {"retry_until": when, "next_attempt_at": outbox._now()}})


async def _expire_deadline(request_id):
    await _set_deadline(request_id, outbox._now() - timedelta(seconds=1))


async def _status_of(request_id):
    entry = await outbox.get_provenance_outbox_col().find_one({"_id": request_id})
    return entry["status"] if entry else None


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@pytest.fixture
def broken_destination(monkeypatch):
    """A destination that refuses every insert but is otherwise reachable.

    `create_indexes` must answer: `ensure_indexes` also ensures the
    DESTINATION's unique index, and a fake that cannot answer it aborts the
    whole drain before a single delivery is attempted — which would make every
    test below pass for the wrong reason."""
    class _Failing:
        async def insert_one(self, doc):
            raise Boom("down")

        async def create_indexes(self, models):
            return []

    monkeypatch.setattr(outbox, "get_answer_provenance_col", lambda: _Failing())


def test_the_window_is_stated_in_seconds_not_attempts():
    """The guarantee an operator reads. If this number changes the promise
    changes, which is exactly why it is stated directly."""
    assert outbox._RETRY_WINDOW_SECONDS == 2 * 60 * 60
    assert not hasattr(outbox, "_MAX_ATTEMPTS"), (
        "termination is decided by the clock; an attempt cap would reintroduce "
        "a second, disagreeing answer to 'how long does this survive?'")


async def test_a_deadline_is_stamped_at_park_time(clean):
    request_id = rid("stamp")
    before = outbox._now()
    await outbox.park(request_id, record_for(request_id))

    entry = await outbox.get_provenance_outbox_col().find_one({"_id": request_id})
    window = (_aware(entry["retry_until"]) - before).total_seconds()
    assert abs(window - outbox._RETRY_WINDOW_SECONDS) < 5


async def test_an_entry_inside_the_deadline_stays_pending(
        clean, broken_destination):
    """The boundary, from below."""
    request_id = rid("inside")
    await outbox.park(request_id, record_for(request_id))
    await _set_deadline(request_id, outbox._now() + timedelta(seconds=30))

    assert (await outbox.drain_once())["deferred"] == 1
    assert await _status_of(request_id) == outbox.STATUS_PENDING


async def test_an_entry_past_the_deadline_fails(clean, broken_destination):
    """The boundary, from above. One second either side of `retry_until` is the
    whole difference between "still trying" and "nobody is coming"."""
    request_id = rid("outside")
    await outbox.park(request_id, record_for(request_id))
    await _set_deadline(request_id, outbox._now() - timedelta(seconds=1))

    await outbox.drain_once()
    assert await _status_of(request_id) == outbox.STATUS_FAILED


async def test_attempts_alone_never_fail_an_entry(clean, broken_destination):
    """Twenty failures well inside the window leave the entry pending. Under
    the old policy it was dead after seven, whatever the clock said."""
    request_id = rid("many")
    await outbox.park(request_id, record_for(request_id))

    for _ in range(20):
        # Re-armed each round: the backoff would otherwise make this test wait.
        await _set_deadline(request_id, outbox._now() + timedelta(hours=1))
        await outbox.drain_once()

    entry = await outbox.get_provenance_outbox_col().find_one({"_id": request_id})
    assert entry["status"] == outbox.STATUS_PENDING
    assert entry["attempts"] == 20, "attempts are still counted for observability"


async def test_the_next_attempt_never_lands_past_the_deadline(
        clean, broken_destination):
    """A backoff longer than the remaining window would schedule an attempt
    after `retry_until`, and the entry would then sit pending forever — never
    retried, never failed, invisible to the `failed` alarm.

    The clamp guarantees a FINAL attempt at the deadline, and that attempt is
    the one that fails it."""
    request_id = rid("clamp")
    await outbox.park(request_id, record_for(request_id))
    deadline = outbox._now() + timedelta(seconds=2)
    await _set_deadline(request_id, deadline)
    await outbox.get_provenance_outbox_col().update_one(
        {"_id": request_id}, {"$set": {"attempts": 50}})
    assert outbox._backoff(51).total_seconds() > 2, "the backoff must overshoot"

    await outbox.drain_once()

    entry = await outbox.get_provenance_outbox_col().find_one({"_id": request_id})
    assert _aware(entry["next_attempt_at"]) <= deadline, (
        "an attempt was scheduled past the deadline; the entry would never be "
        "retried and never marked failed")


async def test_an_entry_written_before_deadlines_existed_still_ages_out(
        clean, broken_destination):
    """A record parked by the previous version has no `retry_until`. It must
    neither live forever nor die instantly — the deadline is derived from
    `created_at`, so it ages out on the same policy."""
    request_id = rid("legacy")
    await outbox.park(request_id, record_for(request_id))
    await outbox.get_provenance_outbox_col().update_one(
        {"_id": request_id},
        {"$unset": {"retry_until": ""},
         "$set": {"created_at": outbox._now() - timedelta(
             seconds=outbox._RETRY_WINDOW_SECONDS + 60)}})

    await outbox.drain_once()
    assert await _status_of(request_id) == outbox.STATUS_FAILED


async def test_a_legacy_entry_inside_its_derived_window_stays_pending(
        clean, broken_destination):
    request_id = rid("legacy2")
    await outbox.park(request_id, record_for(request_id))
    await outbox.get_provenance_outbox_col().update_one(
        {"_id": request_id},
        {"$unset": {"retry_until": ""},
         "$set": {"created_at": outbox._now() - timedelta(seconds=60)}})

    await outbox.drain_once()
    assert await _status_of(request_id) == outbox.STATUS_PENDING


async def test_a_delivery_that_succeeds_before_the_deadline_is_unaffected(clean):
    """The deadline bounds failure, not success."""
    request_id = rid("intime")
    await outbox.park(request_id, record_for(request_id))
    await _set_deadline(request_id, outbox._now() + timedelta(seconds=30))

    assert (await outbox.drain_once())["delivered"] == 1
    assert await provenance_count(request_id) == 1


# ══════════════════════════════════════════════════════════════════════════════
# The limit of this design: one failure domain
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_total_mongo_outage_still_produces_lost(clean, monkeypatch):
    """THE HONEST LIMIT OF THIS MODULE, ASSERTED SO IT CANNOT BE FORGOTTEN.

    The outbox makes provenance survive a FAILED WRITE. It cannot make it
    survive an unreachable database, because the outbox lives in the same
    database as the destination — one failure domain, one outage, both writes
    gone.

    So LOST is not a defensive branch kept for tidiness. It is the outcome of
    the single most likely serious incident this system will have, and it is
    reachable in production. That is precisely why the turn reports
    `audit_saved: false` instead of the module claiming a durability it does
    not have.

    Surviving this needs a second store in a DIFFERENT failure domain — a local
    disk queue, or Redis, which this phase deliberately did not use."""
    request_id = rid("outage")

    class _Unreachable:
        async def insert_one(self, doc):
            raise Boom("no primary reachable")

        async def create_indexes(self, models):
            raise Boom("no primary reachable")

    monkeypatch.setattr(provenance_service, "get_answer_provenance_col",
                        lambda: _Unreachable())
    monkeypatch.setattr(outbox, "get_provenance_outbox_col",
                        lambda: _Unreachable())
    monkeypatch.setattr(outbox, "get_answer_provenance_col",
                        lambda: _Unreachable())
    outbox._reset_index_cache()

    outcome, returned = await provenance_service.record_outcome(
        state={"query": "q", "answer": "a"}, session_id="s1", user_id="u1",
        request_id=request_id)

    assert outcome == outbox.LOST
    assert returned is None
    assert outbox.describe_outcome(outcome)["audit_saved"] is False, (
        "a turn with no audit record anywhere must say so")


async def test_the_module_says_out_loud_that_it_shares_mongos_fate():
    """Documented, not just tested. Someone reading this module to decide
    whether the audit trail is safe must find the limit without running it."""
    import inspect

    doc = inspect.getdoc(outbox) or ""
    assert "failure domain" in doc.lower(), (
        "the shared-failure-domain limit is not written down")


# ══════════════════════════════════════════════════════════════════════════════
# The audit status is reported identically everywhere
# ══════════════════════════════════════════════════════════════════════════════
#
# A turn's audit status reaches the user three ways: the live response, a
# replay of the stored turn, and the message restored when the conversation is
# reopened. If those disagree, the disagreement IS the bug — an answer that
# warned about its audit record and then stopped warning after a refresh is
# worse than one that never warned, because the user concludes the first
# warning was noise.

def test_the_audit_status_is_a_stored_field_of_the_message():
    """It cannot be inferred on read, unlike `history_saved`.

    A message sitting in the conversation proves the message write succeeded.
    It says nothing about the provenance write, which is a different write to a
    different collection that fails independently. So it has to be stored."""
    from app.services import conversation_service as conversations

    assert "audit_saved" in conversations._ANSWER_FIELDS
    assert "audit_pending" in conversations._ANSWER_FIELDS
    assert "history_saved" not in conversations._ANSWER_FIELDS, (
        "history_saved is inferable on restore and must not be stored")


def test_the_stored_message_carries_the_audit_status():
    from app.services import conversation_service as conversations

    message = conversations.build_message(
        "assistant", "an answer",
        answer={"audit_saved": False, "audit_pending": False,
                "citations": [], "request_id": "r1"})
    assert message["audit_saved"] is False
    assert message["audit_pending"] is False


def test_the_socket_corrects_the_ledger_before_writing_the_message():
    """ORDERING, asserted because it is invisible and load-bearing.

    `complete_turn` stores the response for replay BEFORE provenance runs, so
    the audit status is seeded false and corrected afterwards. The correction
    has to land on the turn ledger BEFORE the assistant message is built, or
    the stored message keeps the seeded false while the live frame reports the
    truth — and the reopened conversation then contradicts the answer the user
    actually saw.

    `history_saved` is corrected AFTER, and may be: it is not a stored field."""
    import inspect

    import app.websockets.chat_socket as cs

    source = inspect.getsource(cs._emit)
    audit_fix = source.index("audit_fields = provenance_outbox.describe_outcome")
    message_write = source.index("conversations.append_message")
    history_fix = source.index('{"history_saved": True}')

    assert audit_fix < message_write, (
        "the message is built before the audit status is corrected, so the "
        "stored copy keeps the conservative false")
    assert message_write < history_fix


def test_the_research_path_stores_the_corrected_payload_too():
    import inspect

    import app.api.v1.routes.ai as ai_routes

    source = inspect.getsource(ai_routes._run_research_turn)
    audit_fix = source.index("audit_fields = provenance_outbox.describe_outcome")
    message_write = source.index("_record_research_message")
    assert audit_fix < message_write


async def test_a_replay_reports_the_same_audit_status_as_the_live_answer(clean):
    """The turn ledger's stored response is what a duplicate replays. It is
    annotated with the audit status, so the two cannot diverge."""
    from app.services import conversation_turns as turns

    key = f"outbox-test:{secrets.token_hex(4)}"
    token = secrets.token_hex(8)
    _outcome, record = await turns.claim_turn(
        key, "m-1", "fp", owner_token=token)
    stored = {"type": "final", "content": "an answer",
              "audit_saved": False, "audit_pending": False}
    assert await turns.complete_turn(
        record["_id"], token, response=stored, request_id="req-replay")

    # Provenance lands, and both copies are corrected by one annotation.
    assert await turns.annotate_response(
        record["_id"], "req-replay",
        outbox.describe_outcome(outbox.QUEUED))

    replayed = (await turns.get_turn(key, "m-1"))["response"]
    assert replayed["audit_saved"] is True
    assert replayed["audit_pending"] is True

    await turns.delete_turns(key)


# ══════════════════════════════════════════════════════════════════════════════
# The operational metric
# ══════════════════════════════════════════════════════════════════════════════

async def test_health_is_ok_when_nothing_is_waiting(clean):
    reported = await outbox.health()
    assert reported["status"] == "ok"
    assert reported["failed"] == 0


async def test_health_fails_on_any_undeliverable_record(clean, broken_destination):
    """One is enough. Every failed entry is a turn with no audit record, and
    there is no number of those that is acceptable."""
    request_id = rid("alarm")
    await outbox.park(request_id, record_for(request_id))
    await _expire_deadline(request_id)
    await outbox.drain_once()

    reported = await outbox.health()
    assert reported["status"] == "fail"
    assert reported["failed"] >= 1


async def test_health_warns_when_the_backlog_is_older_than_the_relay_explains(
        clean):
    """A relay that is not running looks exactly like one keeping up, except
    for this number growing. It is the only signal that distinguishes them."""
    request_id = rid("stale")
    await outbox.park(request_id, record_for(request_id))
    await outbox.get_provenance_outbox_col().update_one(
        {"_id": request_id},
        {"$set": {"created_at": outbox._now() - timedelta(
            seconds=outbox.PENDING_AGE_ALERT_SECONDS + 60)}})

    reported = await outbox.health()
    assert reported["status"] == "warn"
    assert reported["oldest_pending_seconds"] > outbox.PENDING_AGE_ALERT_SECONDS


async def test_a_fresh_backlog_is_not_alarmed(clean):
    """A record parked seconds ago is the mechanism working, not an incident."""
    request_id = rid("fresh")
    await outbox.park(request_id, record_for(request_id))

    assert (await outbox.health())["status"] == "ok"


async def test_health_reports_unknown_rather_than_ok_when_it_cannot_read(
        clean, monkeypatch):
    """"Unknown" and "ok" must never collapse. A monitor that cannot see the
    collection is not a monitor reporting health, and the difference decides
    whether anyone investigates."""
    class _Failing:
        async def count_documents(self, *a, **k):
            raise Boom("unreachable")

    monkeypatch.setattr(outbox, "get_provenance_outbox_col", lambda: _Failing())

    reported = await outbox.health()
    assert reported["status"] == "unknown"
    assert reported["status"] != "ok"


async def test_health_carries_no_request_ids_and_no_user_content(clean):
    """A provenance record holds the question a client asked and the advice
    they were given. An outbox entry holds the same. A metrics endpoint exists
    to be scraped and dashboarded, and a request id is the key that opens the
    record — so "just the id" is not a safe middle ground."""
    request_id = rid("private")
    await outbox.park(request_id, {
        "request_id": request_id, "session_id": "s1", "user_id": "u1",
        "query": "my landlord evicted me from my Lahore flat",
        "answer": "Under the Punjab Rented Premises Act ..."})

    reported = await outbox.health()
    blob = str(reported)

    assert request_id not in blob
    assert "landlord" not in blob
    assert "Punjab" not in blob
    assert "u1" not in blob and "s1" not in blob
    # Only counts, an age, a threshold, a status and its explanation.
    assert set(reported) <= {"status", "detail", "pending", "failed",
                             "oldest_pending_seconds",
                             "pending_age_threshold_seconds"}


def test_the_admin_endpoint_is_admin_only():
    """The counts are harmless; the endpoint's existence on an open route would
    still tell an anonymous caller when the audit trail is broken."""
    import inspect

    import app.api.v1.routes.admin as admin

    source = inspect.getsource(admin.provenance_health)
    assert "require_admin" in source
