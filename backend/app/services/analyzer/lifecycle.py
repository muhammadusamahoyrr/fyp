"""Creating an analysis: one source, its encrypted original, its first run.

ORDER OF WRITES

  1. The encrypted FILE is written first (blob_store.write).
  2. Then ONE transaction inserts the source, the blob's header record and the
     first run. Either all three exist or none do.
  3. If the transaction fails, the file is removed; if the process dies before
     that, the file is unreferenced and `blob_store.sweep_orphans` removes it.

A record never points at a file that was not written, and nothing in Mongo is
ever half-created.

IDEMPOTENCY

`(owner_id, create_idempotency_key)` is unique. A request carries a
fingerprint of (file sha256, options, attestation). A replay with the same
fingerprint returns the ORIGINAL source and run; a different request under a
used key is `409 idempotency_mismatch`. Two concurrent first attempts both
see "nothing yet"; the unique index fails one, which then reads the winner and
applies the same comparison. A key whose source was deleted stays used.

READS are owner-scoped and tombstone-aware: a deleted source is `not_found`,
exactly like one that never existed or belongs to someone else.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from app.db.collections import (
    get_analysis_blobs_col,
    get_analysis_runs_col,
    get_analysis_sources_col,
)
from app.services.analyzer import blob_store, states
from app.services.analyzer.errors import AnalyzerConflict, AnalyzerNotFound, UploadRejected
from app.services.analyzer.txn import run_in_transaction
from app.services.analyzer.upload_rules import ValidatedFile, request_fingerprint

RETENTION = timedelta(days=7)
MAX_KEY_LENGTH = 200
MIN_KEY_LENGTH = 8
_KEY = re.compile(r"^[A-Za-z0-9._:-]+$")


def check_idempotency_key(key: str | None) -> str:
    """8-200 characters of [A-Za-z0-9._:-] -- a UUID or the client's k-<ts>-<rand>.

    Validated from the header alone, before the request body is parsed.
    """
    if (not key or not MIN_KEY_LENGTH <= len(key) <= MAX_KEY_LENGTH
            or not _KEY.match(key)):
        raise UploadRejected(
            "invalid_idempotency_key",
            "The Idempotency-Key header is required: 8-200 letters, digits or . _ : -")
    return key


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _created(source: dict, run_id: str, *, replayed: bool) -> dict:
    return {"source_id": source["_id"], "run_id": run_id, "replayed": replayed}


def _replay(existing: dict, fingerprint: str) -> dict:
    if existing.get("deleted_at") is not None:
        raise AnalyzerConflict(
            "idempotency_key_used",
            "This request was already used for an analysis that has since been deleted.")
    if existing.get("request_fingerprint") != fingerprint:
        raise AnalyzerConflict(
            "idempotency_mismatch",
            "This Idempotency-Key was already used for a different upload.")
    return _created(existing, existing["initial_run_id"], replayed=True)


async def create_analysis(*, owner_id: str, idempotency_key: str, content: bytes,
                          validated: ValidatedFile, options: dict, attestation: dict,
                          filename: str | None = None) -> dict:
    fingerprint = request_fingerprint(validated.sha256, options, attestation)
    sources = get_analysis_sources_col()

    existing = await sources.find_one({"owner_id": owner_id,
                                       "create_idempotency_key": idempotency_key})
    if existing:
        return _replay(existing, fingerprint)

    now = _now()
    source_id = uuid.uuid4().hex
    run_id = uuid.uuid4().hex
    header = await blob_store.write(content, source_id=source_id, purpose="original",
                                    mime=validated.mime)
    source = {
        "_id": source_id,
        "owner_id": owner_id,
        "create_idempotency_key": idempotency_key,
        "request_fingerprint": fingerprint,
        "file": {"blob_id": header["_id"], "sha256": validated.sha256, "mime": validated.mime,
                 "kind": validated.kind, "size": validated.size,
                 # Display only: never used to build a path or decide a type.
                 "display_name": (filename or "")[:200] or None},
        "attestation": {**attestation, "attested_by": owner_id, "attested_at": now},
        "initial_run_id": run_id,
        "generation": 0,
        "deleted_at": None,
        "created_at": now,
        "expires_at": now + RETENTION,
    }
    run = {
        "_id": run_id,
        "source_id": source_id,
        "owner_id": owner_id,
        "status": states.INITIAL_STATE,
        "is_open": True,
        "state_version": 0,
        "fence": 0,
        "lease_owner": None,
        "lease_expires_at": None,
        "cancel_requested": False,
        "options": options,
        "created_at": now,
        "updated_at": now,
    }

    async def insert_all(session):
        await sources.insert_one(source, session=session)
        await get_analysis_blobs_col().insert_one(header, session=session)
        await get_analysis_runs_col().insert_one(run, session=session)

    try:
        await run_in_transaction(insert_all)
    except DuplicateKeyError:
        # Lost the race on (owner, key): the winner's source exists now.
        await blob_store.remove_file(header["_id"])
        winner = await sources.find_one({"owner_id": owner_id,
                                         "create_idempotency_key": idempotency_key})
        if winner is None:
            raise
        return _replay(winner, fingerprint)
    except BaseException:
        await blob_store.remove_file(header["_id"])
        raise
    return _created(source, run_id, replayed=False)


def _public_source(source: dict, runs: list[dict]) -> dict:
    return {
        "id": source["_id"],
        "file": {k: source["file"].get(k) for k in ("display_name", "mime", "kind", "size")},
        "attestation": {"synthetic": source["attestation"]["synthetic"],
                        "ui_text_version": source["attestation"]["ui_text_version"],
                        "attested_at": source["attestation"]["attested_at"]},
        "created_at": source["created_at"],
        "expires_at": source["expires_at"],
        "runs": [{"id": r["_id"], "status": r["status"], "state_version": r["state_version"],
                  "options": r["options"], "created_at": r["created_at"]} for r in runs],
    }


async def get_analysis(*, owner_id: str, source_id: str) -> dict:
    source = await get_analysis_sources_col().find_one(
        {"_id": source_id, "owner_id": owner_id, "deleted_at": None})
    if source is None:
        raise AnalyzerNotFound()
    runs = [r async for r in get_analysis_runs_col()
            .find({"source_id": source_id}).sort("created_at", -1).limit(50)]
    return _public_source(source, runs)
