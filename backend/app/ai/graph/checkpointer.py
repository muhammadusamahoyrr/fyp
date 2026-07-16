"""MongoDB checkpointer for the LangGraph chat graph.

Why hand-written instead of `langgraph-checkpoint-mongodb`
----------------------------------------------------------
The official package requires langgraph >= 1.2 / langchain 1.x. This project is
pinned to langchain 0.3.30, and langchain 1.x removed `langchain.retrievers`,
which `app/ai/pipelines/retriever.py` imports for EnsembleRetriever. Installing
the official saver therefore breaks retrieval. This implements the same
BaseCheckpointSaver contract directly on the motor client the app already has —
no new dependency, no stack migration.

What it replaces
----------------
MemorySaver kept conversation state in process RAM: a restart or a second uvicorn
worker dropped every in-flight conversation, including a clarification_node
interrupt() that was waiting on the user's reply. Checkpoints now live in Mongo,
so state survives both.

Storage
-------
lg_checkpoints        one doc per checkpoint, keyed (thread_id, ns, checkpoint_id)
lg_checkpoint_writes  pending writes for a checkpoint, keyed (.., task_id, idx)

Checkpoint ids are UUIDv6-style and monotonically increasing, so "latest" is just
a descending sort on checkpoint_id.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

from bson import Binary
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
)
from pymongo import ASCENDING, DESCENDING, UpdateOne

from app.db.collections import get_checkpoint_writes_col, get_checkpoints_col

logger = logging.getLogger(__name__)


def _scalar_metadata(metadata: CheckpointMetadata) -> dict:
    """Flat, queryable copy of metadata for alist(filter=...).

    The authoritative metadata is the serialized blob; this is only an index for
    filtering, so non-scalar values (e.g. `writes`) are simply skipped.
    """
    return {
        k: v for k, v in (metadata or {}).items()
        if isinstance(v, (str, int, float, bool)) or v is None
    }


class MongoDBSaver(BaseCheckpointSaver):
    """Async BaseCheckpointSaver backed by MongoDB.

    Only the async methods are implemented — every graph invocation in this app
    goes through ainvoke/aget_state. The sync methods inherited from the base
    class raise NotImplementedError, which is the honest behaviour: a silent sync
    fallback that dropped state would be far worse than a loud error.
    """

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _keys(config: RunnableConfig) -> tuple[str, str]:
        cfg = config.get("configurable", {})
        return cfg["thread_id"], cfg.get("checkpoint_ns", "")

    def _dump(self, obj: Any) -> tuple[str, Binary]:
        type_, payload = self.serde.dumps_typed(obj)
        return type_, Binary(payload)

    def _load(self, type_: str, payload: Any) -> Any:
        return self.serde.loads_typed((type_, bytes(payload)))

    async def _pending_writes(self, thread_id: str, ns: str, checkpoint_id: str) -> list:
        cursor = get_checkpoint_writes_col().find(
            {"thread_id": thread_id, "checkpoint_ns": ns, "checkpoint_id": checkpoint_id},
        ).sort([("task_id", ASCENDING), ("idx", ASCENDING)])
        return [
            (doc["task_id"], doc["channel"], self._load(doc["type"], doc["value"]))
            async for doc in cursor
        ]

    def _to_tuple(self, doc: dict, pending: list) -> CheckpointTuple:
        thread_id, ns = doc["thread_id"], doc["checkpoint_ns"]
        parent_id = doc.get("parent_checkpoint_id")
        return CheckpointTuple(
            config={"configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": ns,
                "checkpoint_id": doc["checkpoint_id"],
            }},
            checkpoint=self._load(doc["type"], doc["checkpoint"]),
            metadata=self._load(doc["metadata_type"], doc["metadata"]),
            parent_config=(
                {"configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": ns,
                    "checkpoint_id": parent_id,
                }} if parent_id else None
            ),
            pending_writes=pending,
        )

    # ── read ─────────────────────────────────────────────────────────────────

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id, ns = self._keys(config)
        checkpoint_id = get_checkpoint_id(config)

        query: dict = {"thread_id": thread_id, "checkpoint_ns": ns}
        if checkpoint_id:
            query["checkpoint_id"] = checkpoint_id
            doc = await get_checkpoints_col().find_one(query)
        else:
            # No id pinned → the latest checkpoint for this thread.
            doc = await get_checkpoints_col().find_one(
                query, sort=[("checkpoint_id", DESCENDING)]
            )

        if doc is None:
            return None

        pending = await self._pending_writes(thread_id, ns, doc["checkpoint_id"])
        return self._to_tuple(doc, pending)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        query: dict = {}
        if config:
            cfg = config.get("configurable", {})
            if "thread_id" in cfg:
                query["thread_id"] = cfg["thread_id"]
            if "checkpoint_ns" in cfg:
                query["checkpoint_ns"] = cfg["checkpoint_ns"]
        if filter:
            for key, value in filter.items():
                query[f"metadata_q.{key}"] = value
        if before:
            before_id = get_checkpoint_id(before)
            if before_id:
                query["checkpoint_id"] = {"$lt": before_id}

        cursor = get_checkpoints_col().find(query).sort("checkpoint_id", DESCENDING)
        if limit:
            cursor = cursor.limit(limit)

        async for doc in cursor:
            pending = await self._pending_writes(
                doc["thread_id"], doc["checkpoint_ns"], doc["checkpoint_id"]
            )
            yield self._to_tuple(doc, pending)

    # ── write ────────────────────────────────────────────────────────────────

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id, ns = self._keys(config)
        checkpoint_id = checkpoint["id"]
        parent_id = config.get("configurable", {}).get("checkpoint_id")

        c_type, c_blob = self._dump(checkpoint)
        m_type, m_blob = self._dump(metadata)

        await get_checkpoints_col().update_one(
            {"thread_id": thread_id, "checkpoint_ns": ns, "checkpoint_id": checkpoint_id},
            {"$set": {
                "parent_checkpoint_id": parent_id,
                "type":          c_type,
                "checkpoint":    c_blob,
                "metadata_type": m_type,
                "metadata":      m_blob,
                "metadata_q":    _scalar_metadata(metadata),
            }},
            upsert=True,
        )

        return {"configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": ns,
            "checkpoint_id": checkpoint_id,
        }}

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id, ns = self._keys(config)
        checkpoint_id = get_checkpoint_id(config)
        if not writes:
            return

        ops: list[UpdateOne] = []
        for i, (channel, value) in enumerate(writes):
            # Special channels (ERROR/INTERRUPT/RESUME/SCHEDULED) have reserved
            # negative slots and must OVERWRITE any earlier write in that slot;
            # ordinary channel writes are positional and append-only. This is what
            # makes a resumed interrupt() replace its pending RESUME rather than
            # accumulate duplicates.
            idx = WRITES_IDX_MAP.get(channel, i)
            t_type, t_blob = self._dump(value)
            ops.append(UpdateOne(
                {
                    "thread_id":     thread_id,
                    "checkpoint_ns": ns,
                    "checkpoint_id": checkpoint_id,
                    "task_id":       task_id,
                    "idx":           idx,
                },
                {"$set": {
                    "channel":   channel,
                    "type":      t_type,
                    "value":     t_blob,
                    "task_path": task_path,
                }},
                upsert=True,
            ))

        await get_checkpoint_writes_col().bulk_write(ops, ordered=False)

    async def adelete_thread(self, thread_id: str) -> None:
        await get_checkpoints_col().delete_many({"thread_id": thread_id})
        await get_checkpoint_writes_col().delete_many({"thread_id": thread_id})
