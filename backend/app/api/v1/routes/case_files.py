"""Files a lawyer keeps on a case -- private to that lawyer. See services/case_files."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile

from app.core.exceptions import AppValidationError
from app.dependencies import require_lawyer
from app.services import case_files

# Its own prefix, not /cases/...: the cases router owns that space and a new
# path under it could be shadowed by, or shadow, one of its parameters.
router = APIRouter(prefix="/case-files", tags=["case-files"])

_FORM_OVERHEAD = 64 * 1024


@router.post("/{case_id}", status_code=201)
async def upload_case_file(
    case_id: str,
    request: Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(require_lawyer),
):
    # Refuse an oversized body from its declared length before reading it.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > case_files.MAX_BYTES + _FORM_OVERHEAD:
        raise AppValidationError("The file is larger than 10 MB.")
    data = await file.read(case_files.MAX_BYTES + 1)
    await file.close()
    return await case_files.upload(case_id, str(current_user["_id"]), data, file.filename)


@router.get("/{case_id}")
async def list_case_files(case_id: str, current_user: dict = Depends(require_lawyer)):
    return {"items": await case_files.list_for_case(case_id, str(current_user["_id"]))}


@router.get("/{case_id}/{file_id}/download")
async def download_case_file(case_id: str, file_id: str, current_user: dict = Depends(require_lawyer)):
    row, data = await case_files.read(case_id, file_id, str(current_user["_id"]))
    ascii_name = row["name"].encode("ascii", "ignore").decode() or "file"
    ascii_name = ascii_name.replace('"', "")
    return Response(
        content=data,
        media_type=row["content_type"],
        headers={
            # inline: a PDF or picture opens in the browser's own viewer.
            "Content-Disposition": f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(row['name'])}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.delete("/{case_id}/{file_id}", status_code=204)
async def delete_case_file(case_id: str, file_id: str, current_user: dict = Depends(require_lawyer)):
    await case_files.delete(case_id, file_id, str(current_user["_id"]))
    return Response(status_code=204)
