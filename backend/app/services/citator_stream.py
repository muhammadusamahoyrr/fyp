"""Redis-Streams ingest pipeline for the citator corpus.

Splits the LHC judgment ingest — previously one multi-hour in-process sweep of
fetch → parse → embed — into a decoupled, acknowledged, recoverable pipeline:

    fetch (producer, throttled)
        │  XADD judgment.ingest {neutral_id, text, listing_meta}
        ▼
    judgment.ingest  ──group "parse"──▶  build_doc + store to Mongo
        │                                    │  XADD judgment.embed {neutral_id}
        ▼                                    ▼
    (dead consumers reclaimed          judgment.embed  ──group "embed"──▶  chunk + embed → Chroma
     via XAUTOCLAIM)                         │
                                             ▼
    judgment.dead  ◀── poison (delivered > citator_max_deliveries)

Why this shape: the fetch stage is network-bound and deliberately throttled
(polite to the court server); embed is CPU-bound (E5 vectors). Decoupling them
via a stream lets embed workers grind the backlog while the fetcher keeps
pulling PDFs — neither blocks the other, and you can scale embed consumers
independently by starting more workers in the "embed" group.

Consumer-group semantics: XREADGROUP with id ">" hands each new entry to exactly
one consumer in the group (work is split, not broadcast); the entry sits in that
consumer's Pending Entries List (PEL) until XACK. If a consumer dies, its PEL
entries are reclaimed by another via XAUTOCLAIM after `citator_claim_min_idle_ms`.

Requires Redis 5.0+ for Streams; the XAUTOCLAIM recovery path needs Redis 6.2+.

────────────────────────────────────────────────────────────────────────────
Kafka mapping (for the report — this is deliberately "Kafka-lite" to avoid the
ops weight of a broker + Zookeeper/KRaft for a solo project):

  Redis Streams (here)              Kafka at scale
  ──────────────────────            ─────────────────────────────────────────
  stream  judgment.ingest           topic  judgment.ingest
  stream  judgment.embed            topic  judgment.embed
  XADD                              producer.send(topic, record)
  consumer group "parse"/"embed"    consumer group (group.id)
  entries split across consumers    partitions split across group members
  XREADGROUP ">"                    poll() of new records for the group
  XACK (per-message, via PEL)       offset commit (per-partition high-water mark)
  XAUTOCLAIM after idle             partition rebalance on member death
  judgment.dead stream              dead-letter topic
  MAXLEN ~ trimming                 topic retention (size/time) + log compaction

Key semantic differences to note in the write-up: Kafka acks by advancing a
per-partition offset (coarse, ordered), whereas Redis tracks per-message
delivery in the PEL (fine-grained, individually ack/claimable). Kafka reassigns
whole partitions automatically on rebalance; Redis needs an explicit XAUTOCLAIM
to recover a dead consumer's in-flight messages — which is exactly what the
recovery step below does.
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket

from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.redis_client import get_redis
from app.services import citator_service as cs

logger = logging.getLogger(__name__)

# ── Naming conventions (fixed) ────────────────────────────────────────────────
STREAM_INGEST = "judgment.ingest"   # produced by fetch, consumed by parse
STREAM_EMBED  = "judgment.embed"    # produced by parse, consumed by embed
STREAM_DEAD   = "judgment.dead"     # dead-letter (poison messages)
GROUP_PARSE   = "parse"
GROUP_EMBED   = "embed"


def consumer_name(role: str) -> str:
    """Stable-per-process consumer id: role-host-pid. Distinct per worker so the
    group splits work between them and PEL ownership is attributable."""
    return f"{role}-{socket.gethostname()}-{os.getpid()}"


def _require_redis():
    r = get_redis()
    if r is None:
        raise RuntimeError(
            "Streaming ingest requires REDIS_URL (Redis 5.0+). "
            "Set REDIS_URL or use the inline ingest_judgment path."
        )
    return r


async def _ensure_group(stream: str, group: str) -> None:
    """Create the group (and the stream, via MKSTREAM) if absent. Idempotent."""
    r = _require_redis()
    try:
        await r.xgroup_create(stream, group, id="0", mkstream=True)
    except Exception as e:            # redis.exceptions.ResponseError: BUSYGROUP
        if "BUSYGROUP" not in str(e):
            raise


async def ensure_groups() -> None:
    await _ensure_group(STREAM_INGEST, GROUP_PARSE)
    await _ensure_group(STREAM_EMBED, GROUP_EMBED)


# ── Producer (fetch stage) ────────────────────────────────────────────────────

async def produce_fetched(neutral_id: str, text: str, listing_meta: dict | None = None) -> str:
    """Enqueue a freshly fetched judgment for the parse stage. Returns the
    stream entry id. Stream fields must be flat strings, so listing_meta is
    JSON-encoded."""
    r = _require_redis()
    return await r.xadd(
        STREAM_INGEST,
        {
            "neutral_id": neutral_id,
            "text": text,
            "listing_meta": json.dumps(listing_meta or {}),
        },
        maxlen=settings.citator_stream_maxlen,
        approximate=True,
    )


async def _forward_to_embed(neutral_id: str) -> None:
    r = _require_redis()
    await r.xadd(
        STREAM_EMBED,
        {"neutral_id": neutral_id},
        maxlen=settings.citator_stream_maxlen,
        approximate=True,
    )


async def _dead_letter(stream: str, group: str, msg_id: str, fields: dict, reason: str) -> None:
    r = _require_redis()
    await r.xadd(STREAM_DEAD, {
        "src_stream": stream,
        "group": group,
        "orig_id": msg_id,
        "neutral_id": (fields or {}).get("neutral_id", ""),
        "reason": reason[:300],
    })
    logger.error("DLQ %s/%s %s: %s", stream, group, (fields or {}).get("neutral_id"), reason)


# ── Stage handlers ────────────────────────────────────────────────────────────

async def _handle_parse(fields: dict) -> None:
    """parse group: build the doc + store to Mongo, then forward to embed.
    Idempotent — an already-stored id is skipped without re-forwarding (matches
    the inline path, which never re-embeds an existing judgment)."""
    neutral_id = fields["neutral_id"]
    text = fields.get("text") or ""
    if len(text.strip()) < 200:
        return  # nothing worth storing; ack and move on

    if await cs._judgments_col().find_one({"_id": neutral_id}, {"_id": 1}):
        return  # already ingested

    doc = cs.build_doc(neutral_id, text, json.loads(fields.get("listing_meta") or "{}"))
    try:
        await cs.store_judgment(doc)
    except DuplicateKeyError:
        return  # raced another consumer — the winner forwards to embed
    await _forward_to_embed(neutral_id)


async def _handle_embed(fields: dict) -> None:
    """embed group: load the stored text and upsert vectors into Chroma."""
    neutral_id = fields["neutral_id"]
    doc = await cs._judgments_col().find_one({"_id": neutral_id}, {"text": 1})
    if not doc or not doc.get("text"):
        return
    await cs.embed_judgment(neutral_id, doc["text"])


# ── Consumer loop ─────────────────────────────────────────────────────────────

async def _process(stream: str, group: str, msg_id: str, fields, handler, max_deliveries: int) -> None:
    """Run one entry through a handler and XACK on success. On handler failure
    the entry is left un-acked (stays in the PEL → reclaimed later). Poison
    entries (delivered too many times) are dead-lettered and acked."""
    r = _require_redis()
    if fields is None:
        # Entry was trimmed/deleted after being claimed — nothing to do.
        await r.xack(stream, group, msg_id)
        return

    # Poison guard: how many times has this entry been delivered?
    try:
        pend = await r.xpending_range(stream, group, min=msg_id, max=msg_id, count=1)
        times = pend[0]["times_delivered"] if pend else 1
    except Exception:
        times = 1
    if times > max_deliveries:
        await _dead_letter(stream, group, msg_id, fields, f"exceeded {max_deliveries} deliveries")
        await r.xack(stream, group, msg_id)
        return

    try:
        await handler(fields)
    except Exception:
        logger.exception("handler failed for %s (kept pending for retry)", fields.get("neutral_id"))
        return  # no ack → remains in PEL → XAUTOCLAIM picks it up after idle
    await r.xack(stream, group, msg_id)


async def _drain_once(stream: str, group: str, consumer: str, handler) -> int:
    """One recovery + read pass. Returns the number of entries processed.
    Split out from the loop so it is directly testable."""
    r = _require_redis()
    batch = settings.citator_batch
    processed = 0

    # 1) Recover entries stranded by dead consumers (idle beyond the threshold).
    try:
        res = await r.xautoclaim(
            stream, group, consumer,
            min_idle_time=settings.citator_claim_min_idle_ms,
            start_id="0-0", count=batch,
        )
        claimed = res[1] if len(res) >= 2 else []
        for msg_id, fields in claimed:
            await _process(stream, group, msg_id, fields, handler, settings.citator_max_deliveries)
            processed += 1
    except Exception:
        logger.exception("XAUTOCLAIM failed on %s/%s", stream, group)

    # 2) New entries for this group.
    resp = await r.xreadgroup(
        group, consumer, {stream: ">"},
        count=batch, block=settings.citator_block_ms,
    )
    for _stream, entries in (resp or []):
        for msg_id, fields in entries:
            await _process(stream, group, msg_id, fields, handler, settings.citator_max_deliveries)
            processed += 1
    return processed


async def _run_consumer(stream: str, group: str, consumer: str, handler) -> None:
    await _ensure_group(stream, group)
    logger.info("citator consumer '%s' started on %s/%s", consumer, stream, group)
    while True:
        try:
            await _drain_once(stream, group, consumer, handler)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("consumer '%s' loop error; backing off 2s", consumer)
            await asyncio.sleep(2)


async def run_parse_worker() -> None:
    await _run_consumer(STREAM_INGEST, GROUP_PARSE, consumer_name("parse"), _handle_parse)


async def run_embed_worker() -> None:
    await _run_consumer(STREAM_EMBED, GROUP_EMBED, consumer_name("embed"), _handle_embed)


# ── Introspection (for demos / thesis defense) ────────────────────────────────

async def stream_stats() -> dict:
    """Depth + pending counts across the pipeline. Handy to show live during a
    demo: producer fills judgment.ingest, consumers drain it."""
    r = get_redis()
    if r is None:
        return {"enabled": False}

    async def _len(s):
        try:
            return await r.xlen(s)
        except Exception:
            return 0

    async def _pending(s, g):
        try:
            return (await r.xpending(s, g))["pending"]
        except Exception:
            return 0

    return {
        "enabled": True,
        "ingest_len": await _len(STREAM_INGEST),
        "embed_len": await _len(STREAM_EMBED),
        "dead_len": await _len(STREAM_DEAD),
        "parse_pending": await _pending(STREAM_INGEST, GROUP_PARSE),
        "embed_pending": await _pending(STREAM_EMBED, GROUP_EMBED),
    }
