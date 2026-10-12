"""Files a lawyer keeps on a case (2026-10-11): a summons, an order, a copy of
the client's CNIC.

PRIVATE TO THE LAWYER WHO UPLOADED THEM. The client is not shown these -- that
was the product decision -- so every read is scoped to the uploader, and every
call also re-checks that the lawyer still has the case: one who is taken off it
loses its files with it.

WHAT IS ACCEPTED is decided from the bytes, never from the name or the browser's
content type: a PDF, PNG or JPEG, at most 10 MB. The stored name is a server id;
the filename the lawyer gave is kept only as a label, cleaned, and sent back
only in a Content-Disposition header the route builds safely.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import AppValidationError, ConflictError, NotFoundError
from app.db.mongodb import get_database

MAX_BYTES = 10 * 1024 * 1024
_CLOSED = {"closed", "dismissed"}

# (magic bytes, content type, extension)
_KINDS = (
    (b"%PDF-", "application/pdf", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
)


def _col():
    return get_database()["case_files"]


def _root() -> Path:
    # Fresh each call, so a test that repoints upload_root is honoured.
    return Path(settings.upload_root).resolve() / "case_files"


def _path_for(file_id: str) -> Path:
    """The file's place on disk -- an id the server minted, contained."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", file_id or ""):
        raise NotFoundError("File")
    root = _root()
    path = (root / file_id).resolve()
    if root not in path.parents:
        raise NotFoundError("File")
    return path


def sniff(data: bytes) -> tuple[str, str]:
    """(content type, extension) from the bytes; refuses anything else."""
    for magic, ctype, ext in _KINDS:
        if data.startswith(magic):
            return ctype, ext
    raise AppValidationError("Only PDF, PNG or JPEG files can be uploaded.")


def clean_name(name: str | None, ext: str) -> str:
    """A label for the file: no path, no control characters, a sane length."""
    base = Path(str(name or "")).name
    base = re.sub(r"[\x00-\x1f\x7f\"\\/:*?<>|]+", " ", base).strip() or "file"
    stem = base.rsplit(".", 1)[0] if "." in base else base
    return f"{stem[:120].strip() or 'file'}.{ext}"


async def _case_for(case_id: str, lawyer_id: str) -> dict:
    """The case, if this lawyer has it -- the one access rule cases use."""
    from app.services import case_service
    return await case_service.get_case(case_id, lawyer_id, "lawyer")   # raises 403/404


def _public(row: dict) -> dict:
    return {
        "id": row["_id"],
        "case_id": row["case_id"],
        "name": row["name"],
        "content_type": row["content_type"],
        "size": row["size"],
        "created_at": row["created_at"],
    }


async def upload(case_id: str, lawyer_id: str, data: bytes, filename: str | None) -> dict:
    case = await _case_for(case_id, lawyer_id)
    if str(case.get("status") or "").lower() in _CLOSED:
        raise ConflictError("This case is closed; files can no longer be added.")
    if not data:
        raise AppValidationError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise AppValidationError("The file is larger than 10 MB.")
    ctype, ext = sniff(data)

    file_id = secrets.token_urlsafe(16)
    path = _path_for(file_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(file_id + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)

    row = {
        "_id": file_id,
        "case_id": case_id,
        "owner_id": lawyer_id,
        "name": clean_name(filename, ext),
        "content_type": ctype,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "created_at": datetime.now(timezone.utc),
    }
    try:
        await _col().insert_one(row)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return _public(row)


async def list_for_case(case_id: str, lawyer_id: str) -> list[dict]:
    await _case_for(case_id, lawyer_id)
    cursor = _col().find({"case_id": case_id, "owner_id": lawyer_id}).sort("created_at", -1).limit(200)
    return [_public(r) async for r in cursor]


async def _own_row(case_id: str, file_id: str, lawyer_id: str) -> dict:
    await _case_for(case_id, lawyer_id)
    row = await _col().find_one({"_id": file_id, "case_id": case_id, "owner_id": lawyer_id})
    if not row:
        # Not found, not forbidden: someone else's id tells the caller nothing.
        raise NotFoundError("File")
    return row


async def read(case_id: str, file_id: str, lawyer_id: str) -> tuple[dict, bytes]:
    row = await _own_row(case_id, file_id, lawyer_id)
    path = _path_for(row["_id"])
    if not path.exists():
        raise NotFoundError("File")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != row.get("sha256"):
        raise ConflictError("The stored file does not match what was uploaded.")
    return row, data


async def delete(case_id: str, file_id: str, lawyer_id: str) -> None:
    row = await _own_row(case_id, file_id, lawyer_id)
    await _col().delete_one({"_id": row["_id"], "owner_id": lawyer_id})
    _path_for(row["_id"]).unlink(missing_ok=True)
