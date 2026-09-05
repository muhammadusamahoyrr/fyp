"""DOCUMENTS_V2 · the two sweeps, and the one that must never guess.

`sweep_staging` was written and called from nowhere, so abandoned staging files
accumulated forever. On the link-less publication path a crash also leaves a
`.claim` marker, and an uncollected claim BLOCKS republication of that key —
turning a dropped connection into a permanently unpublishable artifact.

Unreferenced finals are the harder half. A final with no revision naming it is
wasted space, but a final whose revision simply has not been written YET is a
document in flight, and deleting it destroys the bytes a client is waiting for.
The store cannot tell those apart on its own — `delete_final` says so — so the
sweep asks Mongo, and refuses to delete anything it cannot prove is unreferenced.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.core.config import settings
from app.db.collections import get_document_revisions_col
from app.services import artifact_store as store
from app.services import document_v2_service as v2

pytestmark = pytest.mark.integration

A = b"%PDF-1.4 an artifact"


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def _clean(mongo):
    await get_document_revisions_col().delete_many({})
    yield
    await get_document_revisions_col().delete_many({})


def _tmp():
    return Path(settings.upload_root) / "v2" / "tmp"


# ── staging is swept on the background loop ──────────────────────────────────

async def test_the_v2_sweep_clears_abandoned_staging(mongo, monkeypatch):
    """It existed and nothing called it."""
    monkeypatch.setattr(settings, "documents_v2", True)
    abandoned = _tmp() / "rev-x.0.deadbeef.staging.pdf"
    abandoned.write_bytes(A[:5])
    # Aged past the TTL. A FRESH staging file is deliberately spared — see the
    # concurrent-writer test below — so an abandoned one has to look abandoned.
    import os
    old_time = time.time() - 7200
    os.utime(abandoned, (old_time, old_time))

    out = await v2.sweep()
    assert out.get("staging_swept", 0) >= 1
    assert not abandoned.exists()


async def test_a_stale_claim_is_collected(mongo, monkeypatch):
    """An uncollected claim blocks republication of that key forever."""
    monkeypatch.setattr(settings, "documents_v2", True)
    claim = _tmp() / "rev-x.0.pdf.claim"
    claim.write_bytes(b"")
    old = time.time() - 7200
    import os
    os.utime(claim, (old, old))

    await v2.sweep()
    assert not claim.exists()


async def test_the_sweep_spares_a_file_still_being_written(mongo, monkeypatch):
    """A concurrent writer's staging file must survive the sweep."""
    monkeypatch.setattr(settings, "documents_v2", True)
    fresh = _tmp() / "someone-elses-render.pdf"
    fresh.write_bytes(b"in progress")

    await v2.sweep()
    assert fresh.exists(), "deleted a file a live writer was filling"


async def test_the_sweep_does_nothing_while_the_flag_is_off(mongo):
    (_tmp() / "rev-x.0.deadbeef.staging.pdf").write_bytes(A[:5])
    out = await v2.sweep()
    assert out == {"skipped": True}
    assert list(_tmp().iterdir()), "swept while the feature was off"


# ── unreferenced finals ──────────────────────────────────────────────────────

async def test_an_unreferenced_final_is_collected(mongo):
    """No revision names it, and it is old enough to be nobody's in-flight render."""
    key = store.write_final("rev-orphan", 0, A)
    path = store._final_path(key)
    old = time.time() - 7200
    import os
    os.utime(path, (old, old))

    out = await store.sweep_unreferenced_finals(
        referenced=await _referenced_keys(), older_than_seconds=3600)
    assert out >= 1
    assert not store.final_exists(key)


async def test_a_referenced_final_is_never_touched(mongo):
    """The bytes a revision names are the document. Deleting them is data loss."""
    key = store.write_final("rev-live", 0, A)
    await get_document_revisions_col().insert_one(
        {"_id": "rev-live", "document_id": "d1", "artifact_key": key})

    import os
    old = time.time() - 7200
    os.utime(store._final_path(key), (old, old))

    await store.sweep_unreferenced_finals(
        referenced=await _referenced_keys(), older_than_seconds=3600)
    assert store.final_exists(key), "deleted an artifact a revision points at"


async def test_a_recent_final_is_spared(mongo):
    """A revision row may not be written yet.

    An artifact published seconds ago with no row naming it is far more likely
    to be a render in flight than an orphan, and deleting it destroys the bytes
    a client is waiting on. Age is the only thing separating the two.
    """
    key = store.write_final("rev-inflight", 0, A)
    await store.sweep_unreferenced_finals(
        referenced=await _referenced_keys(), older_than_seconds=3600)
    assert store.final_exists(key), "deleted a freshly published artifact"


async def test_the_sweep_refuses_an_unknown_reference_set(mongo):
    """`None` is not an empty set.

    A caller whose Mongo query failed must not hand in None and have it read as
    "nothing is referenced" — that deletes the entire store.
    """
    key = store.write_final("rev-live", 0, A)
    with pytest.raises(ValueError):
        await store.sweep_unreferenced_finals(referenced=None)
    assert store.final_exists(key)


async def _referenced_keys():
    keys = set()
    async for row in get_document_revisions_col().find(
            {"artifact_key": {"$ne": None}}, {"artifact_key": 1}):
        keys.add(row["artifact_key"])
    return keys
