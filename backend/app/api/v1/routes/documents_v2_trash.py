"""Recoverable deletion of Vault documents (DOCUMENTS_V2) -- owner routes.

  GET    /documents/v2/trash                       "Recently deleted"
  GET    /documents/v2/{doc_id}/deletion-preview   what deleting will do (warnings)
  DELETE /documents/v2/{doc_id}                    move to the trash
  POST   /documents/v2/{doc_id}/restore            move back, before purge_after

Registered BEFORE the documents_v2 router so `/trash` is never read as a
document id. Inert while DOCUMENTS_V2 is off (404 feature_disabled, before
authentication). The document's OWNER only -- a client, or since 2026-10-09 a
lawyer for the documents they drafted themselves; ownership is the owner field,
so a lawyer can never delete a client's document. Anything not the caller's is
the same 404 as a missing id. Delete and restore are naturally idempotent: repeating either
answers with the state it already produced. See services/vault_deletion.py.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import settings
from app.dependencies import require_client_or_lawyer
from app.services import vault_deletion as svc
from app.services.vault_deletion import VaultDeletionError


def _require_enabled() -> None:
    if not settings.documents_v2:
        raise HTTPException(status_code=404, detail={"code": "feature_disabled", "message": "Not found."})


router = APIRouter(prefix="/documents/v2", tags=["documents-v2"], dependencies=[Depends(_require_enabled)])


async def _run(coro):
    try:
        return await coro
    except VaultDeletionError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


@router.get("/trash")
async def list_trash(current_user: dict = Depends(require_client_or_lawyer)):
    return await _run(svc.list_trash(client_id=current_user["_id"]))


@router.get("/{doc_id}/deletion-preview")
async def deletion_preview(doc_id: str, current_user: dict = Depends(require_client_or_lawyer)):
    return await _run(svc.deletion_preview(client_id=current_user["_id"], document_id=doc_id))


@router.delete("/{doc_id}")
async def delete_document(doc_id: str, current_user: dict = Depends(require_client_or_lawyer)):
    return await _run(svc.delete_document(client_id=current_user["_id"], document_id=doc_id))


@router.post("/{doc_id}/restore")
async def restore_document(doc_id: str, current_user: dict = Depends(require_client_or_lawyer)):
    return await _run(svc.restore_document(client_id=current_user["_id"], document_id=doc_id))
