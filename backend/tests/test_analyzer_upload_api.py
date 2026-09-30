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
import base64
import io
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from httpx import ASGITransport

from app.core.config import settings
from app.db.collections import (
    get_analysis_blobs_col,
    get_analysis_runs_col,
    get_analysis_sources_col,
)
from app.services.analyzer import blob_store, readiness

PDF = b"%PDF-1.4\nTENANCY AGREEMENT (synthetic)\n1. The Landlord lets the shop.\n%%EOF\n"
KEY = "k1:" + base64.b64encode(b"\x33" * 32).decode()
ATTESTED = {"synthetic_data_attested": "true", "attestation_version": "synthetic-v1"}


@pytest.fixture
async def http(mongo, app_indexes, monkeypatch, tmp_path):
    from app.dependencies import get_current_user
    from app.main import app

    owner = f"client-{uuid.uuid4().hex[:10]}"
    actor = {"_id": owner, "role": "client", "is_active": True}
    monkeypatch.setattr(settings, "doc_analyzer", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    monkeypatch.setattr(settings, "analyzer_keks", KEY)
    monkeypatch.setattr(settings, "analyzer_kek_active", "k1")
    readiness._reset_for_tests()
    readiness._STATE.checked = True          # as if the startup check passed

    async def current():
        return actor

    app.dependency_overrides[get_current_user] = current
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                     base_url="http://test/api/v1") as client:
            yield client, actor
    finally:
        app.dependency_overrides.clear()
        readiness._reset_for_tests()
        for col in (get_analysis_sources_col(), get_analysis_runs_col()):
            await col.delete_many({"owner_id": owner})


def files_on_disk() -> list:
    root = blob_store._root()
    return list(root.iterdir()) if root.exists() else []


async def stored_for(owner: str) -> tuple[int, int, int]:
    sources = await get_analysis_sources_col().count_documents({"owner_id": owner})
    runs = await get_analysis_runs_col().count_documents({"owner_id": owner})
    ids = [s["_id"] async for s in get_analysis_sources_col().find({"owner_id": owner}, {"_id": 1})]
    blobs = await get_analysis_blobs_col().count_documents({"source_id": {"$in": ids}})
    return sources, runs, blobs


async def upload(client, *, content=PDF, name="lease.pdf", fields=None, key="auto", **kw):
    data = dict(ATTESTED if fields is None else fields)
    data.update(kw)
    headers = {} if key is None else {"Idempotency-Key": uuid.uuid4().hex if key == "auto" else key}
    return await client.post("/documents/analyses", data=data, headers=headers,
                             files={"file": (name, content, "application/octet-stream")})


async def assert_nothing_stored(owner: str):
    assert await stored_for(owner) == (0, 0, 0)
    assert files_on_disk() == [], "a refused upload left a file on disk"


# ── gates: refuse, and store nothing ─────────────────────────────────────────

async def test_off_means_not_found_everywhere(http, monkeypatch):
    client, actor = http
    monkeypatch.setattr(settings, "doc_analyzer", False)
    for response in (await upload(client), await client.get("/documents/analyses/attestation"),
                     await client.get("/documents/analyses/whatever")):
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


@pytest.mark.parametrize("fields", [
    {},
    {"synthetic_data_attested": "false", "attestation_version": "synthetic-v1"},
    {"synthetic_data_attested": "True", "attestation_version": "synthetic-v1"},
    {"synthetic_data_attested": "true"},
    {"synthetic_data_attested": "true", "attestation_version": "synthetic-v0"},
])
async def test_no_attestation_no_upload(http, fields):
    client, actor = http
    response = await upload(client, fields=fields)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "synthetic_attestation_required"
    await assert_nothing_stored(actor["_id"])


async def test_the_attestation_is_checked_before_anything_else(http):
    # Missing key AND a .doc file AND no attestation: the attestation answers.
    client, actor = http
    response = await upload(client, fields={}, key=None, content=b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64)
    assert response.json()["error"]["code"] == "synthetic_attestation_required"


async def test_an_idempotency_key_is_required(http):
    client, actor = http
    for key in (None, "x" * 201):
        response = await upload(client, key=key)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "missing_idempotency_key"
    await assert_nothing_stored(actor["_id"])


async def test_a_refused_file_type_stores_nothing(http):
    client, actor = http
    response = await upload(client, content=b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64, name="lease.doc")
    assert response.status_code == 422 and response.json()["error"]["code"] == "doc_not_supported"
    response = await upload(client, side="buyer")
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_side"
    await assert_nothing_stored(actor["_id"])


async def test_an_oversized_body_is_refused_before_the_form_is_parsed(http):
    client, actor = http
    response = await upload(client, content=b"%PDF-" + b"0" * (11 * 1024 * 1024))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    await assert_nothing_stored(actor["_id"])


async def test_a_body_without_a_declared_length_is_refused(http):
    client, actor = http

    async def chunks():
        yield b"--x\r\n"

    response = await client.post("/documents/analyses", content=chunks(),
                                 headers={"Content-Type": "multipart/form-data; boundary=x",
                                          "Idempotency-Key": uuid.uuid4().hex})
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
    responses = await asyncio.gather(*(upload(client, key="racing") for _ in range(4)))
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
