"""Document Analyzer, P1 slice 1 / commit 3: upload -> source + blob + run.

Two kinds of test:

  * GATES, which must refuse and store NOTHING (no source row, no blob row, no
    file on disk). These run on any Mongo.
  * CREATION, which is one transaction and so needs a replica set
    (`mongo_transactional` skips on a standalone; run against
    scripts/dev_mongo_replset.py). One test runs only on a standalone and
    proves creation there fails closed, leaving no file behind.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.db.collections import (
    get_analysis_blobs_col,
    get_analysis_runs_col,
    get_analysis_sources_col,
)
from app.services.analyzer import blob_store, readiness

from tests._analyzer_support import (  # noqa: F401 -- `http`, `form_calls` are fixtures
    ATTESTED,
    PDF,
    assert_nothing_stored,
    files_on_disk,
    form_calls,
    http,
    stored_for,
    upload,
)


# ── gates: refuse, and store nothing ─────────────────────────────────────────

async def test_off_means_not_found_everywhere(http, monkeypatch):
    client, actor = http
    monkeypatch.setattr(settings, "doc_analyzer", False)
    # The bare list path included: the generic GET /documents/{doc_id} must
    # never answer it (router order in main.py).
    for response in (await upload(client), await client.get("/documents/analyses/attestation"),
                     await client.get("/documents/analyses/whatever"),
                     await client.get("/documents/analyses")):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "feature_disabled"
    await assert_nothing_stored(actor["_id"])


async def test_not_ready_means_503_and_nothing_stored(http):
    client, actor = http
    readiness._STATE.problems = (readiness.TRANSACTIONS_UNAVAILABLE,)
    response = await upload(client)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "analyzer_unavailable"
    assert "replica" not in response.text, "an internal readiness detail reached the client"
    await assert_nothing_stored(actor["_id"])


async def test_lawyers_cannot_upload(http):
    client, actor = http
    actor["role"] = "lawyer"
    assert (await upload(client)).status_code == 403


# An old-Word (.doc) header: refused by content, so it proves where a
# request was stopped.
OLE2 = bytes.fromhex("d0cf11e0a1b11ae1") + bytes(64)


@pytest.mark.parametrize("attest", [
    {},
    {"X-Synthetic-Data-Attested": "false", "X-Synthetic-Attestation-Version": "synthetic-v1"},
    {"X-Synthetic-Data-Attested": "True", "X-Synthetic-Attestation-Version": "synthetic-v1"},
    {"X-Synthetic-Data-Attested": "true"},                                          # no version
    {"X-Synthetic-Data-Attested": "true", "X-Synthetic-Attestation-Version": "synthetic-v0"},  # stale
])
async def test_no_attestation_no_upload_and_the_body_is_never_parsed(http, form_calls, attest):
    client, actor = http
    response = await upload(client, attest=attest)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "synthetic_attestation_required"
    assert form_calls == [], "the multipart body was parsed for an unattested upload"
    await assert_nothing_stored(actor["_id"])


async def test_the_attestation_in_the_form_does_not_count(http, form_calls):
    # The old transport. Fields in the body cannot attest: they would have to
    # be parsed first, which is exactly what must not happen.
    client, actor = http
    response = await upload(client, attest={}, synthetic_data_attested="true",
                            attestation_version="synthetic-v1")
    assert response.json()["error"]["code"] == "synthetic_attestation_required"
    assert form_calls == []
    await assert_nothing_stored(actor["_id"])


async def test_the_attestation_is_checked_before_anything_else(http, form_calls):
    # Missing key AND a .doc file AND no attestation: the attestation answers.
    client, actor = http
    response = await upload(client, attest={}, key=None, content=OLE2)
    assert response.json()["error"]["code"] == "synthetic_attestation_required"
    assert form_calls == []


@pytest.mark.parametrize("key", [None, "", "short", "x" * 201, "has space-1234", "semi;colon-1234"])
async def test_a_malformed_idempotency_key_is_refused_before_the_body(http, form_calls, key):
    client, actor = http
    response = await upload(client, key=key)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_idempotency_key"
    assert form_calls == [], "the multipart body was parsed for an invalid key"
    await assert_nothing_stored(actor["_id"])


@pytest.mark.parametrize("key", ["0f8fad5b-d9cb-469f-a165-70867728950e", "k-1790000000000-a1b2c3d4e5", "x" * 200])
async def test_well_formed_keys_pass_the_gate(http, form_calls, key):
    client, _ = http
    # A .doc fails AFTER the gate: proof the key was accepted and the body parsed.
    response = await upload(client, key=key, content=OLE2)
    assert response.json()["error"]["code"] == "doc_not_supported"
    assert len(form_calls) == 1


async def test_an_oversized_body_is_refused_before_parsing(http, form_calls):
    client, actor = http
    response = await upload(client, content=b"%PDF-" + b"0" * (11 * 1024 * 1024))
    assert response.status_code == 413
    assert form_calls == []
    await assert_nothing_stored(actor["_id"])


async def test_a_refused_file_type_stores_nothing(http):
    client, actor = http
    response = await upload(client, content=b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64, name="lease.doc")
    assert response.status_code == 422 and response.json()["error"]["code"] == "doc_not_supported"
    response = await upload(client, side="buyer")
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_side"
    await assert_nothing_stored(actor["_id"])


async def test_a_body_without_a_declared_length_is_refused(http):
    client, actor = http

    async def chunks():
        yield b"--x\r\n"

    response = await client.post("/documents/analyses", content=chunks(),
                                 headers={"Content-Type": "multipart/form-data; boundary=x",
                                          "Idempotency-Key": uuid.uuid4().hex, **ATTESTED})
    assert response.status_code == 411
    await assert_nothing_stored(actor["_id"])


async def test_the_attestation_wording_is_served(http):
    client, _ = http
    body = (await client.get("/documents/analyses/attestation")).json()
    assert body["version"] == "synthetic-v1"
    assert "do not upload real client or confidential documents" in body["text"]


async def test_on_a_standalone_creation_fails_closed_and_leaves_no_file(http, mongo):
    hello = await mongo.client.admin.command("hello")
    if hello.get("setName"):
        pytest.skip("this proves the standalone refusal; the replica set is covered below")
    client, actor = http
    response = await upload(client)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "analyzer_unavailable"
    await assert_nothing_stored(actor["_id"])


# ── creation: one transaction (replica set) ──────────────────────────────────

async def test_an_upload_creates_source_blob_and_run_together(http, mongo_transactional):
    client, actor = http
    response = await upload(client, side="landlord", depth="deep")
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued_extract" and body["replayed"] is False

    source = await get_analysis_sources_col().find_one({"_id": body["source_id"]})
    run = await get_analysis_runs_col().find_one({"_id": body["run_id"]})
    assert source["owner_id"] == actor["_id"] and source["deleted_at"] is None
    assert source["generation"] == 0 and source["initial_run_id"] == body["run_id"]
    assert source["attestation"]["synthetic"] is True
    assert source["attestation"]["ui_text_version"] == "synthetic-v1"
    assert source["attestation"]["attested_by"] == actor["_id"]
    assert source["expires_at"] - source["created_at"] == timedelta(days=7)
    assert source["file"]["kind"] == "pdf" and source["file"]["display_name"] == "lease.pdf"
    assert run["status"] == "queued_extract" and run["is_open"] is True
    assert run["fence"] == 0 and run["state_version"] == 0 and run["lease_owner"] is None
    assert run["options"] == {"side": "landlord", "depth": "deep"}

    # The file is encrypted at rest and reads back exactly.
    [path] = files_on_disk()
    assert b"TENANCY AGREEMENT" not in path.read_bytes()
    assert await blob_store.read(source["file"]["blob_id"], source_id=source["_id"],
                                 purpose="original") == PDF


async def test_a_replay_returns_the_original_and_creates_nothing(http, mongo_transactional):
    client, actor = http
    first = (await upload(client, key="same-intent")).json()
    again = await upload(client, key="same-intent")
    assert again.status_code == 202
    assert again.json()["source_id"] == first["source_id"]
    assert again.json()["run_id"] == first["run_id"] and again.json()["replayed"] is True
    assert await stored_for(actor["_id"]) == (1, 1, 1)
    assert len(files_on_disk()) == 1, "a replay wrote a second file"


@pytest.mark.parametrize("change", [{"content": PDF + b"% edited\n"}, {"side": "landlord"}])
async def test_a_different_request_under_a_used_key_is_a_conflict(http, mongo_transactional, change):
    client, actor = http
    await upload(client, key="one-intent")
    response = await upload(client, key="one-intent", **change)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_mismatch"
    assert await stored_for(actor["_id"]) == (1, 1, 1)
    assert len(files_on_disk()) == 1, "a refused request left its file behind"


async def test_concurrent_first_attempts_create_exactly_one(http, mongo_transactional):
    client, actor = http
    responses = await asyncio.gather(*(upload(client, key="racing-intent") for _ in range(4)))
    assert {r.status_code for r in responses} == {202}
    assert len({r.json()["source_id"] for r in responses}) == 1
    assert await stored_for(actor["_id"]) == (1, 1, 1)
    assert len(files_on_disk()) == 1, "a loser's encrypted file was left behind"


async def test_a_failure_mid_transaction_leaves_nothing(http, mongo_transactional, monkeypatch):
    client, actor = http
    runs = get_analysis_runs_col()

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated failure after source and blob were inserted")

    monkeypatch.setattr(type(runs), "insert_one", boom)
    with pytest.raises(RuntimeError):
        await upload(client)
    monkeypatch.undo()
    await assert_nothing_stored(actor["_id"])


async def test_reading_is_owner_scoped_and_tombstone_aware(http, mongo_transactional):
    client, actor = http
    created = (await upload(client)).json()
    mine = await client.get(f"/documents/analyses/{created['source_id']}")
    assert mine.status_code == 200
    body = mine.json()
    assert [r["id"] for r in body["runs"]] == [created["run_id"]]
    for internal in ("request_fingerprint", "create_idempotency_key", "owner_id", "blob_id"):
        assert internal not in mine.text, f"{internal} leaked"

    actor["_id"] = f"client-{uuid.uuid4().hex[:10]}"        # someone else
    assert (await client.get(f"/documents/analyses/{created['source_id']}")).status_code == 404

    await get_analysis_sources_col().update_one({"_id": created["source_id"]},
                                                {"$set": {"deleted_at": datetime.now(timezone.utc)}})
    actor["_id"] = (await get_analysis_sources_col().find_one({"_id": created["source_id"]}))["owner_id"]
    assert (await client.get(f"/documents/analyses/{created['source_id']}")).status_code == 404
