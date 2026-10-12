"""A lawyer's Vault (2026-10-09): folders for their own documents, and the
recoverable delete a client already had.

Folders are organisation only: filing moves nothing but `folder_id`, deleting
a folder returns its documents to "no folder" and deletes none, and a lawyer
can file or delete only what they OWN -- never a client's document they
reviewed, which is the same 404 as a missing one.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from httpx import ASGITransport

from app.core.config import settings
from app.db.collections import (
    get_deleted_documents_col,
    get_document_folders_col,
    get_document_revisions_col,
    get_documents_col,
)
from app.services import document_folders as df
from app.services import vault_deletion as vd
from app.services.document_folders import FolderError

pytestmark = pytest.mark.integration

TAG = uuid.uuid4().hex[:8]
LAWYER = f"lvf-l-{TAG}"
OTHER_LAWYER = f"lvf-o-{TAG}"
CLIENT = f"lvf-c-{TAG}"


async def _wipe():
    owners = [LAWYER, OTHER_LAWYER, CLIENT]
    for col in (get_documents_col(), get_deleted_documents_col()):
        await col.delete_many({"client_id": {"$in": owners}})
    await get_document_folders_col().delete_many({"owner_id": {"$in": owners}})
    await get_document_revisions_col().delete_many({"_id": {"$regex": f"^{TAG}-"}})


@pytest.fixture
async def db(mongo, app_indexes, monkeypatch):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "document_review_requests", False)
    await _wipe()
    yield mongo
    await _wipe()


_clock = [datetime(2026, 10, 1, tzinfo=timezone.utc)]


async def seed(owner: str = LAWYER, title: str = "Plaint — Civil Suit", **extra) -> str:
    doc_id = f"{TAG}-d-{uuid.uuid4().hex[:8]}"
    _clock[0] += timedelta(minutes=1)
    await get_documents_col().insert_one({
        "_id": doc_id, "client_id": owner, "schema_version": 2, "case_id": None, "title": title,
        "template_type": "lawyer_draft", "review_status": "none", "current_revision_id": None,
        "current_version": 1, "created_at": _clock[0], **extra})
    return doc_id


async def refused(coro, status, code):
    with pytest.raises(FolderError) as caught:
        await coro
    assert (caught.value.status, caught.value.code) == (status, code), caught.value.message


# ── the service ─────────────────────────────────────────────────────────────

async def test_create_rename_and_list_folders_with_their_counts(db):
    bail = await df.create_folder(owner_id=LAWYER, name="  Bail   matters ")
    assert bail["name"] == "Bail matters" and bail["document_count"] == 0
    family = await df.create_folder(owner_id=LAWYER, name="Family")
    doc = await seed()
    await df.move_document(owner_id=LAWYER, document_id=doc, folder_id=bail["id"])
    listed = (await df.list_folders(owner_id=LAWYER))["items"]
    assert [(f["name"], f["document_count"]) for f in listed] == [("Bail matters", 1), ("Family", 0)]
    renamed = await df.rename_folder(owner_id=LAWYER, folder_id=family["id"], name="Family court")
    assert renamed["name"] == "Family court"


async def test_names_are_unique_per_owner_ignoring_case_and_spaces(db):
    await df.create_folder(owner_id=LAWYER, name="Bail")
    await refused(df.create_folder(owner_id=LAWYER, name=" bail "), 409, "folder_exists")
    other = await df.create_folder(owner_id=LAWYER, name="Civil")
    await refused(df.rename_folder(owner_id=LAWYER, folder_id=other["id"], name="BAIL"), 409, "folder_exists")
    # Another lawyer may use the same name.
    assert (await df.create_folder(owner_id=OTHER_LAWYER, name="Bail"))["name"] == "Bail"


async def test_a_name_is_required_and_bounded(db):
    await refused(df.create_folder(owner_id=LAWYER, name="   "), 422, "name_required")
    await refused(df.create_folder(owner_id=LAWYER, name="x" * (df.MAX_NAME + 1)), 422, "name_too_long")


async def test_deleting_a_folder_unfiles_its_documents_and_deletes_none(db):
    folder = await df.create_folder(owner_id=LAWYER, name="Bail")
    kept, trashed = await seed(), await seed()
    for doc in (kept, trashed):
        await df.move_document(owner_id=LAWYER, document_id=doc, folder_id=folder["id"])
    await vd.delete_document(client_id=LAWYER, document_id=trashed)
    out = await df.delete_folder(owner_id=LAWYER, folder_id=folder["id"])
    assert out["deleted"] and out["documents_unfiled"] == 1
    row = await get_documents_col().find_one({"_id": kept})
    assert row is not None and "folder_id" not in row
    # A document in Recently deleted comes back to no folder, not a missing one.
    assert "folder_id" not in await get_deleted_documents_col().find_one({"_id": trashed})
    restored = await vd.restore_document(client_id=LAWYER, document_id=trashed)
    assert restored["restored"] and "folder_id" not in await get_documents_col().find_one({"_id": trashed})
    await refused(df.delete_folder(owner_id=LAWYER, folder_id=folder["id"]), 404, "not_found")


async def test_a_lawyer_files_only_their_own_documents_into_their_own_folders(db):
    mine = await df.create_folder(owner_id=LAWYER, name="Mine")
    theirs = await df.create_folder(owner_id=OTHER_LAWYER, name="Theirs")
    my_doc, client_doc = await seed(), await seed(CLIENT, title="Client's rent agreement")
    await refused(df.move_document(owner_id=LAWYER, document_id=client_doc, folder_id=mine["id"]), 404, "not_found")
    await refused(df.move_document(owner_id=LAWYER, document_id=my_doc, folder_id=theirs["id"]), 404, "not_found")
    await refused(df.rename_folder(owner_id=LAWYER, folder_id=theirs["id"], name="x"), 404, "not_found")
    await refused(df.delete_folder(owner_id=LAWYER, folder_id=theirs["id"]), 404, "not_found")
    assert "folder_id" not in await get_documents_col().find_one({"_id": client_doc})
    moved = await df.move_document(owner_id=LAWYER, document_id=my_doc, folder_id=mine["id"])
    assert moved == {"id": my_doc, "folder_id": mine["id"]}
    out = await df.move_document(owner_id=LAWYER, document_id=my_doc, folder_id=None)
    assert out["folder_id"] is None and "folder_id" not in await get_documents_col().find_one({"_id": my_doc})


async def test_a_lawyer_can_never_delete_a_clients_document(db):
    client_doc = await seed(CLIENT, title="Client's rent agreement")
    with pytest.raises(vd.VaultDeletionError) as caught:
        await vd.delete_document(client_id=LAWYER, document_id=client_doc)
    assert caught.value.status == 404
    assert await get_documents_col().find_one({"_id": client_doc}) is not None


# ── the routes ──────────────────────────────────────────────────────────────

@pytest.fixture
async def http(db):
    from app.dependencies import get_current_user
    from app.main import app

    actor = {"_id": LAWYER, "role": "lawyer", "is_active": True}

    async def current():
        return actor

    app.dependency_overrides[get_current_user] = current
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api/v1") as client:
            yield client, actor
    finally:
        app.dependency_overrides.clear()


async def test_folder_routes_end_to_end_and_folders_is_never_a_document_id(http):
    client, _ = http
    a, b = await seed(title="First"), await seed(title="Second")
    made = await client.post("/documents/v2/folders", json={"name": "Bail"})
    assert made.status_code == 201
    folder = made.json()["id"]
    assert (await client.post("/documents/v2/folders", json={"name": "bail"})).json()["error"]["code"] == "folder_exists"
    assert (await client.put(f"/documents/v2/{a}/folder", json={"folder_id": folder})).status_code == 200

    def ids(res):
        return [d["id"] for d in res.json()["items"]]

    assert ids(await client.get(f"/documents/v2/mine?folder={folder}")) == [a]
    assert ids(await client.get("/documents/v2/mine?folder=none")) == [b]
    every = (await client.get("/documents/v2/mine")).json()["items"]
    assert {d["id"]: d["folder_id"] for d in every} == {a: folder, b: None}
    listed = (await client.get("/documents/v2/folders")).json()["items"]
    assert [(f["name"], f["document_count"]) for f in listed] == [("Bail", 1)]
    assert (await client.patch(f"/documents/v2/folders/{folder}", json={"name": "Bail matters"})).json()["name"] == "Bail matters"
    assert (await client.delete(f"/documents/v2/folders/{folder}")).json()["documents_unfiled"] == 1
    # Newest first, and both back in no folder.
    assert ids(await client.get("/documents/v2/mine?folder=none")) == [b, a]
    assert (await client.get("/documents/v2/folders")).json()["items"] == []


async def test_a_lawyer_deletes_and_restores_their_own_document_through_the_routes(http):
    client, _ = http
    doc = await seed()
    assert (await client.delete(f"/documents/v2/{doc}")).status_code == 200
    assert [r["id"] for r in (await client.get("/documents/v2/trash")).json()["items"]] == [doc]
    assert (await client.post(f"/documents/v2/{doc}/restore")).status_code == 200
    assert doc in [d["id"] for d in (await client.get("/documents/v2/mine")).json()["items"]]


async def test_a_client_has_the_same_folders_over_their_own_documents(http):
    """2026-10-10: the client Vault has folders too. Ownership, not role, is the
    guard: a client files only their own documents, into their own folders."""
    client, actor = http
    actor.update({"_id": CLIENT, "role": "client"})
    mine = await seed(CLIENT, title="Rent agreement")
    made = await client.post("/documents/v2/folders", json={"name": "Tenancy"})
    assert made.status_code == 201
    folder = made.json()["id"]
    assert (await client.put(f"/documents/v2/{mine}/folder", json={"folder_id": folder})).status_code == 200
    assert [d["id"] for d in (await client.get(f"/documents/v2/mine?folder={folder}")).json()["items"]] == [mine]
    assert [(f["name"], f["document_count"]) for f in (await client.get("/documents/v2/folders")).json()["items"]] == [("Tenancy", 1)]
    assert (await client.delete(f"/documents/v2/folders/{folder}")).json()["documents_unfiled"] == 1


async def test_a_client_never_reaches_a_lawyers_folder_or_document(http):
    client, actor = http
    lawyer_doc = await seed(LAWYER, title="Lawyer's own draft")
    lawyer_folder = (await df.create_folder(owner_id=LAWYER, name="Bail"))["id"]
    actor.update({"_id": CLIENT, "role": "client"})
    assert (await client.get("/documents/v2/folders")).json()["items"] == []
    for res in [await client.patch(f"/documents/v2/folders/{lawyer_folder}", json={"name": "Mine now"}),
                await client.delete(f"/documents/v2/folders/{lawyer_folder}"),
                await client.put(f"/documents/v2/{lawyer_doc}/folder", json={"folder_id": None})]:
        assert res.status_code == 404 and res.json()["error"]["code"] == "not_found"
    own = (await client.post("/documents/v2/folders", json={"name": "Mine"})).json()["id"]
    res = await client.put(f"/documents/v2/{lawyer_doc}/folder", json={"folder_id": own})
    assert res.status_code == 404
    assert (await get_document_folders_col().find_one({"_id": lawyer_folder}))["name"] == "Bail"
    assert "folder_id" not in await get_documents_col().find_one({"_id": lawyer_doc})


async def test_folder_routes_refuse_other_roles_and_are_off_with_the_feature(http, monkeypatch):
    client, actor = http
    actor["role"] = "admin"
    assert (await client.get("/documents/v2/folders")).status_code == 403
    monkeypatch.setattr(settings, "documents_v2", False)
    for method, path in [("GET", "/documents/v2/folders"), ("POST", "/documents/v2/folders"),
                         ("PATCH", "/documents/v2/folders/x"), ("DELETE", "/documents/v2/folders/x"),
                         ("PUT", "/documents/v2/x/folder")]:
        res = await client.request(method, path)
        assert res.status_code == 404 and res.json()["error"]["code"] == "feature_disabled", (method, path)
