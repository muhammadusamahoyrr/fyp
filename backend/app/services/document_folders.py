"""A lawyer's Vault folders (2026-10-09).

A folder is a name a lawyer gives to a group of their OWN documents. It is
organisation only: a document records its `folder_id`, nothing about the
document itself changes, and deleting a folder moves its documents back to
"no folder" -- it never deletes one. Ownership is the document's owner field
(`client_id`, whoever owns it -- see documents_v2.my_documents_v2), so a
lawyer can file only what they own, never a client's document they reviewed.

Names are unique per owner, ignoring case and surrounding spaces, so "Bail"
and " bail " cannot both exist and a retried create answers with a conflict
rather than a second folder.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.db.collections import get_deleted_documents_col, get_document_folders_col, get_documents_col

MAX_NAME = 60
MAX_FOLDERS = 100


class FolderError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _not_found() -> FolderError:
    return FolderError(404, "not_found", "Not found.")


def _now() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


def _iso(value) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return None


def clean_name(raw) -> tuple[str, str]:
    """The name as shown, and its comparison key. Refuses an empty or overlong one."""
    name = " ".join(str(raw or "").split())
    if not name:
        raise FolderError(422, "name_required", "Give the folder a name.")
    if len(name) > MAX_NAME:
        raise FolderError(422, "name_too_long", f"A folder name can be at most {MAX_NAME} characters.")
    return name, name.casefold()


def view(row: dict, count: int = 0) -> dict:
    return {"id": row["_id"], "name": row["name"], "document_count": count,
            "created_at": _iso(row.get("created_at")), "updated_at": _iso(row.get("updated_at"))}


async def _owned_folder(owner_id: str, folder_id: str) -> dict:
    row = await get_document_folders_col().find_one({"_id": folder_id, "owner_id": owner_id})
    if row is None:
        raise _not_found()
    return row


async def list_folders(*, owner_id: str) -> dict:
    rows = await get_document_folders_col().find({"owner_id": owner_id}).sort(
        [("name_key", 1)]).to_list(MAX_FOLDERS)
    counts = {}
    if rows:
        pipeline = [{"$match": {"client_id": owner_id, "schema_version": 2,
                                "folder_id": {"$in": [r["_id"] for r in rows]}}},
                    {"$group": {"_id": "$folder_id", "n": {"$sum": 1}}}]
        async for c in get_documents_col().aggregate(pipeline):
            counts[c["_id"]] = c["n"]
    return {"items": [view(r, counts.get(r["_id"], 0)) for r in rows], "limit": MAX_FOLDERS}


async def create_folder(*, owner_id: str, name) -> dict:
    name, key = clean_name(name)
    folders = get_document_folders_col()
    if await folders.count_documents({"owner_id": owner_id}) >= MAX_FOLDERS:
        raise FolderError(409, "folder_limit", f"You can have at most {MAX_FOLDERS} folders.")
    now = _now()
    row = {"_id": secrets.token_urlsafe(12), "owner_id": owner_id, "name": name, "name_key": key,
           "created_at": now, "updated_at": now}
    try:
        await folders.insert_one(row)
    except DuplicateKeyError:
        raise FolderError(409, "folder_exists", f"You already have a folder named “{name}”.") from None
    return view(row)


async def rename_folder(*, owner_id: str, folder_id: str, name) -> dict:
    name, key = clean_name(name)
    row = await _owned_folder(owner_id, folder_id)
    if row["name_key"] == key and row["name"] == name:
        return view(row)
    try:
        await get_document_folders_col().update_one(
            {"_id": folder_id, "owner_id": owner_id},
            {"$set": {"name": name, "name_key": key, "updated_at": _now()}})
    except DuplicateKeyError:
        raise FolderError(409, "folder_exists", f"You already have a folder named “{name}”.") from None
    return view({**row, "name": name, "name_key": key})


async def delete_folder(*, owner_id: str, folder_id: str) -> dict:
    """Remove the folder; its documents (and any in Recently deleted) go back to
    no folder. Idempotent: an already-removed folder is the same 404 as any
    folder that is not the caller's."""
    await _owned_folder(owner_id, folder_id)
    unfiled = {"$unset": {"folder_id": ""}}
    moved = await get_documents_col().update_many({"client_id": owner_id, "folder_id": folder_id}, unfiled)
    await get_deleted_documents_col().update_many({"client_id": owner_id, "folder_id": folder_id}, unfiled)
    await get_document_folders_col().delete_one({"_id": folder_id, "owner_id": owner_id})
    return {"id": folder_id, "deleted": True, "documents_unfiled": moved.modified_count}


async def move_document(*, owner_id: str, document_id: str, folder_id: str | None) -> dict:
    """Put one of the caller's own documents into a folder, or (None) out of every folder."""
    documents = get_documents_col()
    doc = await documents.find_one({"_id": document_id, "client_id": owner_id, "schema_version": 2},
                                   {"_id": 1, "folder_id": 1})
    if doc is None:
        raise _not_found()
    if folder_id:
        await _owned_folder(owner_id, folder_id)
        change = {"$set": {"folder_id": folder_id}}
    else:
        change = {"$unset": {"folder_id": ""}}
    await documents.update_one({"_id": document_id, "client_id": owner_id}, change)
    return {"id": document_id, "folder_id": folder_id or None}
