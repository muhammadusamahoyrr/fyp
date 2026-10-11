"""Vault folders (DOCUMENTS_V2) -- for a lawyer or a client, each over their OWN.

  GET    /documents/v2/folders                 the caller's folders, with counts
  POST   /documents/v2/folders                 create {name}
  PATCH  /documents/v2/folders/{folder_id}     rename {name}
  DELETE /documents/v2/folders/{folder_id}     remove; its documents go to no folder
  PUT    /documents/v2/{doc_id}/folder         file a document {folder_id | null}

Registered BEFORE the documents_v2 router so `/folders` is never read as a
document id. Inert while DOCUMENTS_V2 is off (404 feature_disabled, before
authentication). Lawyers and clients (2026-10-10: the client Vault has the
same folders); OWNERSHIP is the guard -- every query is scoped to the caller's
`owner_id` / `client_id`, so a folder or document not the caller's is the same
404 as a missing one. See services/document_folders.py.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.dependencies import require_client_or_lawyer
from app.services import document_folders as svc
from app.services.document_folders import FolderError


def _require_enabled() -> None:
    if not settings.documents_v2:
        raise HTTPException(status_code=404, detail={"code": "feature_disabled", "message": "Not found."})


router = APIRouter(prefix="/documents/v2", tags=["documents-v2"], dependencies=[Depends(_require_enabled)])


class FolderName(BaseModel):
    name: str


class FolderChoice(BaseModel):
    folder_id: str | None = None


async def _run(coro):
    try:
        return await coro
    except FolderError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


@router.get("/folders")
async def list_folders(current_user: dict = Depends(require_client_or_lawyer)):
    return await _run(svc.list_folders(owner_id=str(current_user["_id"])))


@router.post("/folders", status_code=201)
async def create_folder(body: FolderName, current_user: dict = Depends(require_client_or_lawyer)):
    return await _run(svc.create_folder(owner_id=str(current_user["_id"]), name=body.name))


@router.patch("/folders/{folder_id}")
async def rename_folder(folder_id: str, body: FolderName, current_user: dict = Depends(require_client_or_lawyer)):
    return await _run(svc.rename_folder(owner_id=str(current_user["_id"]), folder_id=folder_id, name=body.name))


@router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str, current_user: dict = Depends(require_client_or_lawyer)):
    return await _run(svc.delete_folder(owner_id=str(current_user["_id"]), folder_id=folder_id))


@router.put("/{doc_id}/folder")
async def move_document(doc_id: str, body: FolderChoice, current_user: dict = Depends(require_client_or_lawyer)):
    return await _run(svc.move_document(owner_id=str(current_user["_id"]), document_id=doc_id,
                                        folder_id=body.folder_id))
