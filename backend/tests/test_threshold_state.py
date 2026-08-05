"""Shared threshold + PSI drift state.

Both stores used to be process-local module globals. Under multiple uvicorn
workers that meant each worker kept private percentiles and a private warmup
counter, so identical queries could be graded against different thresholds, and
a deploy reset warmup progress to zero. These tests pin the Redis-backed
behaviour and the fail-open fallback.
"""
import pytest

from app.ai import calibration, threshold_manager as tm


# ── Minimal in-memory fake of the async Redis surface used by these modules ───

class FakeRedis:
    def __init__(self):
        self.lists: dict[str, list[str]] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.strings: dict[str, str] = {}
        self.commands = 0

    # -- pipeline ------------------------------------------------------------
    def pipeline(self):
        return FakePipeline(self)

    # -- lists ---------------------------------------------------------------
    async def lpush(self, key, *values):
        self.commands += 1
        self.lists.setdefault(key, [])[0:0] = [str(v) for v in reversed(values)]
        return len(self.lists[key])

    async def rpush(self, key, *values):
        self.commands += 1
        self.lists.setdefault(key, []).extend(str(v) for v in values)
        return len(self.lists[key])

    async def ltrim(self, key, start, end):
        self.commands += 1
        items = self.lists.get(key, [])
        self.lists[key] = items[start:] if end == -1 else items[start:end + 1]
        return True

    async def lrange(self, key, start, end):
        self.commands += 1
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start:end + 1]

    async def delete(self, key):
        self.commands += 1
        self.lists.pop(key, None)
        self.hashes.pop(key, None)
        return 1

    # -- hashes --------------------------------------------------------------
    async def hgetall(self, key):
        self.commands += 1
        return dict(self.hashes.get(key, {}))

    async def hset(self, key, mapping=None):
        self.commands += 1
        self.hashes.setdefault(key, {}).update(mapping or {})
        return len(mapping or {})

    async def hincrby(self, key, field, amount):
        self.commands += 1
        h = self.hashes.setdefault(key, {})
        h[field] = str(int(h.get(field, 0)) + amount)
        return int(h[field])

    # -- locks ---------------------------------------------------------------
    async def set(self, key, value, nx=False, ex=None):
        self.commands += 1
        if nx and key in self.strings:
            return None
        self.strings[key] = value
        return True

    async def eval(self, script, numkeys, key, token):
        # Stub of the Redis EVAL *command* (server-side Lua), not Python's eval.
        # redis_lock releases via a compare-and-delete script; `script` is never
        # executed here — we just emulate its documented effect.
        self.commands += 1
        if self.strings.get(key) == token:
            del self.strings[key]
            return 1
        return 0


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.ops = []

    def __getattr__(self, name):
        def queue(*args, **kwargs):
            self.ops.append((name, args, kwargs))
            return self
        return queue

    async def execute(self):
        results = []
        for name, args, kwargs in self.ops:
            results.append(await getattr(self.redis, name)(*args, **kwargs))
        self.ops = []
        return results


def _reset_all() -> None:
    tm._reset_for_tests()
    calibration._psi_pending.clear()
    calibration._psi_window.clear()
    calibration._psi_baseline.clear()


@pytest.fixture
def fake_redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr("app.ai.threshold_manager.get_redis", lambda: r)
    monkeypatch.setattr("app.ai.calibration.get_redis", lambda: r)
    monkeypatch.setattr("app.core.redis_client.get_redis", lambda: r)
    _reset_all()
    yield r
    _reset_all()


@pytest.fixture
def no_redis(monkeypatch):
    monkeypatch.setattr("app.ai.threshold_manager.get_redis", lambda: None)
    monkeypatch.setattr("app.ai.calibration.get_redis", lambda: None)
    _reset_all()
    yield
    _reset_all()


# ── thresholds: seeds and hot path ────────────────────────────────────────────

def test_seed_thresholds_are_active_before_warmup(no_redis):
    assert tm.is_warmed_up() is False
    assert tm.get_generation_floor() == 0.20
    assert tm.get_refusal_ceiling()  == 0.10
    assert tm.get_disagreement_max() == 0.25


@pytest.mark.asyncio
async def test_getters_never_touch_redis(fake_redis):
    """Getters run once per chunk inside scoring — a Redis call there would be a
    per-chunk network round trip on the hot path."""
    await tm.record_query(retrieval_score=0.5, routing_gap=0.1)
    before = fake_redis.commands
    for _ in range(50):
        tm.get_generation_floor()
        tm.get_disagreement_max()
        tm.get_refusal_ceiling()
    assert fake_redis.commands == before


# ── thresholds: batching ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_writes_are_batched_not_per_query(fake_redis):
    """One round trip per _FLUSH_EVERY queries, not one per query — the store is
    metered per command."""
    # First call also performs the once-per-_REFRESH_SECONDS snapshot refresh,
    # so measure sample writes from after it has happened.
    await tm.record_query(retrieval_score=0.5, routing_gap=0.1)
    after_refresh = fake_redis.commands

    for _ in range(tm._FLUSH_EVERY - 2):
        await tm.record_query(retrieval_score=0.5, routing_gap=0.1)

    assert fake_redis.commands == after_refresh, "buffered queries must not write"
    assert tm._K_SCORES not in fake_redis.lists, "no samples before the flush boundary"

    await tm.record_query(retrieval_score=0.5, routing_gap=0.1)
    assert fake_redis.commands > after_refresh, "the flush boundary must write"
    assert len(fake_redis.lists[tm._K_SCORES]) == tm._FLUSH_EVERY


@pytest.mark.asyncio
async def test_flushed_samples_reach_the_shared_store(fake_redis):
    for _ in range(tm._FLUSH_EVERY):
        await tm.record_query(retrieval_score=0.42, routing_gap=0.1)

    assert len(fake_redis.lists[tm._K_SCORES]) == tm._FLUSH_EVERY
    assert fake_redis.hashes[tm._K_COUNTS]["total"] == str(tm._FLUSH_EVERY)


@pytest.mark.asyncio
async def test_labeled_counter_is_tracked_separately(fake_redis):
    for i in range(tm._FLUSH_EVERY):
        await tm.record_query(
            retrieval_score=0.5, routing_gap=0.1, is_labeled=(i % 5 == 0)
        )
    counts = fake_redis.hashes[tm._K_COUNTS]
    assert counts["total"]   == str(tm._FLUSH_EVERY)
    assert counts["labeled"] == str(tm._FLUSH_EVERY // 5)


# ── thresholds: cross-worker sharing ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_second_worker_picks_up_shared_thresholds(fake_redis):
    """The actual bug being fixed: worker B must see worker A's thresholds."""
    fake_redis.hashes[tm._K_VALUES] = {"floor": "0.55", "cosine": "0.88"}
    fake_redis.hashes[tm._K_COUNTS] = {"total": "1500", "labeled": "300"}

    await tm.refresh()

    assert tm.get_generation_floor() == 0.55
    assert tm.get_cosine_threshold() == 0.88
    assert tm.is_warmed_up() is True, "shared counter past warmup must warm this worker"


@pytest.mark.asyncio
async def test_coverage_ratio_uses_the_shared_counters(fake_redis):
    fake_redis.hashes[tm._K_COUNTS] = {"total": "1000", "labeled": "700"}
    await tm.refresh()
    assert tm.coverage_ratio() == 0.7
    assert tm.log_weight()  == 0.20   # ratio >= 0.60
    assert tm.eval_weight() == 0.80


# ── thresholds: fail-open ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_redis_failure_does_not_raise_and_keeps_samples(monkeypatch):
    """A metrics store outage must not fail the legal query that produced it."""
    class Broken(FakeRedis):
        def pipeline(self):
            raise ConnectionError("redis down")

    monkeypatch.setattr("app.ai.threshold_manager.get_redis", lambda: Broken())
    tm._reset_for_tests()
    try:
        for _ in range(tm._FLUSH_EVERY):
            await tm.record_query(retrieval_score=0.5, routing_gap=0.1)
        # Samples are retained for a later attempt rather than silently dropped.
        assert len(tm._buffer) >= tm._FLUSH_EVERY
    finally:
        tm._reset_for_tests()


@pytest.mark.asyncio
async def test_in_process_mode_still_warms_up(no_redis):
    """Redis disabled → previous single-worker behaviour must be preserved."""
    for _ in range(tm.WARMUP_QUERY_COUNT):
        await tm.record_query(retrieval_score=0.5, routing_gap=0.1)
    assert tm.is_warmed_up() is True


# ── PSI drift ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_psi_baseline_is_established_in_the_shared_store(fake_redis):
    for _ in range(calibration._PSI_WINDOW_SIZE):
        await calibration.record_score_for_drift(0.5)

    assert len(fake_redis.lists[calibration._K_PSI_BASELINE]) == calibration._PSI_WINDOW_SIZE
    assert fake_redis.lists.get(calibration._K_PSI_WINDOW, []) == []


@pytest.mark.asyncio
async def test_a_shifted_distribution_replaces_the_baseline(fake_redis, caplog):
    for _ in range(calibration._PSI_WINDOW_SIZE):
        await calibration.record_score_for_drift(0.1)

    with caplog.at_level("WARNING"):
        for _ in range(calibration._PSI_WINDOW_SIZE):
            await calibration.record_score_for_drift(0.9)

    assert "distribution shift detected" in caplog.text


@pytest.mark.asyncio
async def test_a_stable_distribution_does_not_flag_drift(fake_redis, caplog):
    for _ in range(calibration._PSI_WINDOW_SIZE):
        await calibration.record_score_for_drift(0.5)

    with caplog.at_level("WARNING"):
        for _ in range(calibration._PSI_WINDOW_SIZE):
            await calibration.record_score_for_drift(0.5)

    assert "distribution shift detected" not in caplog.text


@pytest.mark.asyncio
async def test_psi_writes_are_batched(fake_redis):
    """One RPUSH per query was the single largest Redis cost in the pipeline."""
    for _ in range(calibration._PSI_FLUSH_EVERY - 1):
        await calibration.record_score_for_drift(0.5)
    assert fake_redis.commands == 0, "buffered scores must not write"

    await calibration.record_score_for_drift(0.5)
    assert len(fake_redis.lists[calibration._K_PSI_WINDOW]) == calibration._PSI_FLUSH_EVERY


@pytest.mark.asyncio
async def test_psi_falls_back_to_local_state_on_redis_error(monkeypatch):
    class Broken(FakeRedis):
        async def rpush(self, key, *values):
            raise ConnectionError("redis down")

    monkeypatch.setattr("app.ai.calibration.get_redis", lambda: Broken())
    _reset_all()
    try:
        # Must survive a full batch boundary, where the write actually happens.
        for _ in range(calibration._PSI_FLUSH_EVERY):
            await calibration.record_score_for_drift(0.5)
    finally:
        _reset_all()
