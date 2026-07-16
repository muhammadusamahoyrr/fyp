"""MongoDBSaver tests.

The checkpointer is what makes a conversation survive a restart. The property
that actually matters is the awkward one: an interrupt() suspended mid-graph must
still be resumable by a DIFFERENT process — that is the case MemorySaver silently
lost, and the reason this class exists.

Marked integration: needs MongoDB.
"""
import uuid

import pytest
from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata

from app.ai.graph.checkpointer import MongoDBSaver

pytestmark = pytest.mark.integration


def _checkpoint(cid: str) -> Checkpoint:
    return {
        "v": 1,
        "id": cid,
        "ts": "2026-01-01T00:00:00+00:00",
        "channel_values": {"answer": "bail is non-bailable"},
        "channel_versions": {"answer": 1},
        "versions_seen": {},
    }


def _cfg(thread: str, cid: str | None = None) -> dict:
    configurable = {"thread_id": thread, "checkpoint_ns": ""}
    if cid:
        configurable["checkpoint_id"] = cid
    return {"configurable": configurable}


@pytest.fixture
async def saver(mongo):
    s = MongoDBSaver()
    threads: list[str] = []

    def _new_thread() -> str:
        t = f"test-{uuid.uuid4().hex[:10]}"
        threads.append(t)
        return t

    s.new_thread = _new_thread  # type: ignore[attr-defined]
    yield s
    for t in threads:
        await s.adelete_thread(t)


async def test_put_then_get_roundtrips_the_checkpoint(saver):
    thread = saver.new_thread()
    cid = str(uuid.uuid4())

    await saver.aput(_cfg(thread), _checkpoint(cid),
                     CheckpointMetadata(source="loop", step=1), {})

    tup = await saver.aget_tuple(_cfg(thread))
    assert tup is not None
    assert tup.checkpoint["id"] == cid
    assert tup.checkpoint["channel_values"]["answer"] == "bail is non-bailable"
    assert tup.metadata["step"] == 1


async def test_get_without_a_checkpoint_id_returns_the_latest(saver):
    """Checkpoint ids are monotonically increasing, so "latest" is a descending
    sort. If this breaks, a conversation silently rewinds to an earlier turn."""
    thread = saver.new_thread()
    ids = sorted(str(uuid.uuid4()) for _ in range(3))

    for i, cid in enumerate(ids):
        await saver.aput(_cfg(thread), _checkpoint(cid),
                         CheckpointMetadata(source="loop", step=i), {})

    tup = await saver.aget_tuple(_cfg(thread))
    assert tup.checkpoint["id"] == ids[-1]


async def test_a_specific_checkpoint_id_can_be_fetched(saver):
    thread = saver.new_thread()
    ids = sorted(str(uuid.uuid4()) for _ in range(2))
    for cid in ids:
        await saver.aput(_cfg(thread), _checkpoint(cid), CheckpointMetadata(), {})

    tup = await saver.aget_tuple(_cfg(thread, ids[0]))
    assert tup.checkpoint["id"] == ids[0]


async def test_unknown_thread_returns_none(saver):
    assert await saver.aget_tuple(_cfg("no-such-thread")) is None


async def test_threads_are_isolated_from_each_other(saver):
    a, b = saver.new_thread(), saver.new_thread()
    await saver.aput(_cfg(a), _checkpoint(str(uuid.uuid4())), CheckpointMetadata(), {})

    assert await saver.aget_tuple(_cfg(a)) is not None
    assert await saver.aget_tuple(_cfg(b)) is None


async def test_writes_are_stored_and_returned_as_pending(saver):
    thread = saver.new_thread()
    cid = str(uuid.uuid4())
    await saver.aput(_cfg(thread), _checkpoint(cid), CheckpointMetadata(), {})

    await saver.aput_writes(_cfg(thread, cid), [("answer", "draft")], task_id="task-1")

    tup = await saver.aget_tuple(_cfg(thread, cid))
    assert tup.pending_writes == [("task-1", "answer", "draft")]


async def test_a_special_channel_write_overwrites_rather_than_duplicates(saver):
    """RESUME/INTERRUPT/ERROR occupy reserved slots via WRITES_IDX_MAP and must
    OVERWRITE. Get this wrong and a resumed interrupt accumulates duplicate
    RESUME writes instead of replacing the pending one — which is exactly how a
    clarification gets answered twice."""
    thread = saver.new_thread()
    cid = str(uuid.uuid4())
    await saver.aput(_cfg(thread), _checkpoint(cid), CheckpointMetadata(), {})

    await saver.aput_writes(_cfg(thread, cid), [("__resume__", "Punjab")], task_id="t")
    await saver.aput_writes(_cfg(thread, cid), [("__resume__", "Sindh")], task_id="t")

    tup = await saver.aget_tuple(_cfg(thread, cid))
    resumes = [w for w in tup.pending_writes if w[1] == "__resume__"]
    assert len(resumes) == 1
    assert resumes[0][2] == "Sindh"


async def test_alist_returns_history_newest_first(saver):
    thread = saver.new_thread()
    ids = sorted(str(uuid.uuid4()) for _ in range(3))
    for i, cid in enumerate(ids):
        await saver.aput(_cfg(thread), _checkpoint(cid),
                         CheckpointMetadata(source="loop", step=i), {})

    listed = [t.checkpoint["id"] async for t in saver.alist(_cfg(thread))]
    assert listed == list(reversed(ids))


async def test_parent_config_links_a_checkpoint_to_its_predecessor(saver):
    thread = saver.new_thread()
    first, second = sorted(str(uuid.uuid4()) for _ in range(2))

    await saver.aput(_cfg(thread), _checkpoint(first), CheckpointMetadata(), {})
    # The parent is whatever checkpoint_id the incoming config carried.
    await saver.aput(_cfg(thread, first), _checkpoint(second), CheckpointMetadata(), {})

    tup = await saver.aget_tuple(_cfg(thread, second))
    assert tup.parent_config["configurable"]["checkpoint_id"] == first


async def test_delete_thread_removes_checkpoints_and_writes(saver, mongo):
    from app.db.collections import get_checkpoint_writes_col, get_checkpoints_col

    thread = saver.new_thread()
    cid = str(uuid.uuid4())
    await saver.aput(_cfg(thread), _checkpoint(cid), CheckpointMetadata(), {})
    await saver.aput_writes(_cfg(thread, cid), [("answer", "x")], task_id="t")

    await saver.adelete_thread(thread)

    assert await get_checkpoints_col().count_documents({"thread_id": thread}) == 0
    assert await get_checkpoint_writes_col().count_documents({"thread_id": thread}) == 0
