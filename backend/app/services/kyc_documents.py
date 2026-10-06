"""A lawyer's KYC files: a verification photo and up to three credentials.

Onboarding's "Credentials & Photo" step offered upload buttons that sent
nothing, and the admin KYC screen listed hardcoded document names. This is the
storage behind both.

* One file per KIND. Re-uploading a kind replaces it; the old file is removed
  only after the record points at the new one.
* Types are checked from the file's bytes (detect_mime), never from the
  client's Content-Type or filename.
* Files live on local disk under ``{upload_root}/kyc/{user_id}/`` — the same
  model as intake evidence — and are served only through authorised routes,
  never a static path.
* The record (``lawyer_profile.kyc_documents.{kind}``) carries metadata only;
  the on-disk name is derived from it and contained under the lawyer's folder.
* Closing the account erases the files TOMBSTONE-FIRST: the record is cut
  down to file ids (no filenames) and marked ``kyc_erasure_pending`` in the
  closure write, the files are deleted, and only then is the record removed.
  A deletion that fails is logged, recorded on the user and retried by the
  hourly sweep (``retry_pending_erasures``) — sensitive files are never left
  on disk with nothing pointing at them.
"""
from __future__ import annotations

import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import AppValidationError, NotFoundError
from app.repositories.user_repo import UserRepository
from app.utils.file_handler import detect_mime, ext_for_mime

logger = logging.getLogger(__name__)
user_repo = UserRepository()

MAX_BYTES = 5 * 1024 * 1024
_CHUNK = 1024 * 1024
_IMAGES = {"image/jpeg", "image/png"}
_DOCS = _IMAGES | {"application/pdf"}

# kind -> (label, accepted types)
KINDS: dict[str, tuple[str, set[str]]] = {
    "photo": ("Verification photo", _IMAGES),
    "bar_certificate": ("Bar Council Certificate", _DOCS),
    "education": ("Educational Credentials", _DOCS),
    "professional": ("Professional Certificates", _DOCS),
}

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _root() -> Path:
    return Path(settings.upload_root) / "kyc"


def _folder(user_id: str) -> Path:
    if not _SAFE_ID.fullmatch(str(user_id)):
        raise NotFoundError("Lawyer")
    return _root() / str(user_id)


def _path_for(user_id: str, meta: dict) -> Path:
    folder = _folder(user_id).resolve()
    name = f"{meta['file_id']}{ext_for_mime(meta.get('content_type'))}"
    path = (folder / name).resolve()
    if folder not in path.parents:
        raise NotFoundError("Document")
    return path


def _check_kind(kind: str) -> tuple[str, set[str]]:
    if kind not in KINDS:
        raise AppValidationError(f"Unknown document kind. Expected one of: {', '.join(KINDS)}")
    return KINDS[kind]


async def _read_bounded(file) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_BYTES:
            raise AppValidationError("File too large — maximum size is 5 MB.")
        chunks.append(chunk)
    return b"".join(chunks)


def _public(meta: dict) -> dict:
    return {k: meta.get(k) for k in ("file_id", "filename", "content_type", "size", "uploaded_at")}


async def list_documents(user_id: str) -> dict:
    user = await user_repo.find_by_id(user_id)
    docs = ((user or {}).get("lawyer_profile") or {}).get("kyc_documents") or {}
    return {kind: _public(meta) for kind, meta in docs.items() if kind in KINDS and meta}


async def upload(user_id: str, kind: str, file) -> dict:
    import aiofiles

    label, allowed = _check_kind(kind)
    user = await user_repo.find_by_id(user_id)
    if not user or not isinstance(user.get("lawyer_profile"), dict):
        raise NotFoundError("Lawyer profile")

    content = await _read_bounded(file)
    if not content:
        raise AppValidationError("The file is empty.")
    mime = detect_mime(content[:16])
    if mime not in allowed:
        accepted = "JPEG or PNG" if allowed == _IMAGES else "PDF, JPEG or PNG"
        raise AppValidationError(f"{label}: file type not allowed. Accepted: {accepted}.")

    meta = {
        "file_id": uuid.uuid4().hex,
        "filename": (file.filename or label)[:200],
        "content_type": mime,
        "size": len(content),
        "uploaded_at": datetime.now(timezone.utc),
    }
    folder = _folder(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = _path_for(user_id, meta)
    async with aiofiles.open(path, "wb") as f:
        await f.write(content)

    previous = ((user.get("lawyer_profile") or {}).get("kyc_documents") or {}).get(kind)
    try:
        stored = await user_repo.update_one(
            {"_id": user_id, "lawyer_profile": {"$type": "object"}},
            {"$set": {f"lawyer_profile.kyc_documents.{kind}": meta}},
        )
        if not stored:
            raise NotFoundError("Lawyer profile")
    except Exception:
        # The bytes are on disk before the record exists: never leave them
        # orphaned when the record write fails.
        path.unlink(missing_ok=True)
        raise

    if previous and previous.get("file_id"):
        try:
            _path_for(user_id, previous).unlink(missing_ok=True)
        except (OSError, NotFoundError):
            logger.warning("could not remove replaced KYC file for %s/%s", user_id, kind)
    return {kind: _public(meta)}


async def file_for(user_id: str, kind: str) -> tuple[Path, str, str]:
    _check_kind(kind)
    user = await user_repo.find_by_id(user_id)
    meta = (((user or {}).get("lawyer_profile") or {}).get("kyc_documents") or {}).get(kind)
    if not meta:
        raise NotFoundError("Document")
    path = _path_for(user_id, meta)
    if not path.is_file():
        raise NotFoundError("Document")
    return path, meta.get("filename") or kind, meta.get("content_type") or "application/octet-stream"


def closure_tombstone(lawyer_profile: dict) -> dict:
    """$set fields for the closure write: keep only what erasure needs."""
    docs = (lawyer_profile or {}).get("kyc_documents") or {}
    if not docs:
        return {}
    return {
        "lawyer_profile.kyc_documents": {
            kind: {"file_id": meta.get("file_id"), "content_type": meta.get("content_type")}
            for kind, meta in docs.items() if meta
        },
        "lawyer_profile.kyc_erasure_pending": datetime.now(timezone.utc),
    }


async def erase(user_id: str) -> bool:
    """Delete a closed lawyer's KYC files, then clear the tombstone.

    Returns True only when the files are gone AND the tombstone is cleared.
    Never raises: it runs after an account closure has already been committed,
    so a disk, database or logging failure here must leave the tombstone for
    the sweep — not turn a completed closure into a 500.
    """
    try:
        folder = _folder(user_id)
    except NotFoundError:
        return False
    try:
        if folder.exists():
            shutil.rmtree(folder)
    except Exception as exc:  # noqa: BLE001 -- recorded and retried, never raised
        try:
            logger.error("kyc_erasure_failed user=%s: %s", user_id, exc)
            await user_repo.update_one(
                {"_id": user_id},
                {"$set": {"lawyer_profile.kyc_erasure_error": str(exc)[:300],
                          "lawyer_profile.kyc_erasure_last_attempt": datetime.now(timezone.utc)},
                 "$inc": {"lawyer_profile.kyc_erasure_attempts": 1}})
        except Exception:  # noqa: BLE001 -- the tombstone itself is the record
            pass
        return False
    try:
        await user_repo.update_one(
            {"_id": user_id},
            {"$unset": {"lawyer_profile.kyc_documents": "",
                        "lawyer_profile.kyc_erasure_pending": "",
                        "lawyer_profile.kyc_erasure_error": "",
                        "lawyer_profile.kyc_erasure_attempts": "",
                        "lawyer_profile.kyc_erasure_last_attempt": ""}})
    except Exception:  # noqa: BLE001 -- files are gone; the sweep clears the record
        logger.exception("kyc_erasure_record_not_cleared user=%s", user_id)
        return False
    return True


async def retry_pending_erasures(batch: int = 100, max_batches: int = 10) -> int:
    """Retry erasures still pending. Returns how many completed.

    Least-recently-attempted first (``kyc_erasure_last_attempt``, missing
    first), so a user that keeps failing moves to the back instead of starving
    the rest; paged, so a backlog larger than one batch is still reached; and
    each user is isolated, so one unexpected error cannot abort the batch.
    """
    done = 0
    seen: list = []
    for _ in range(max_batches):
        pending = await user_repo.find_many(
            {"lawyer_profile.kyc_erasure_pending": {"$exists": True}, "_id": {"$nin": seen}},
            sort=[("lawyer_profile.kyc_erasure_last_attempt", 1), ("_id", 1)],
            limit=batch)
        if not pending:
            break
        for user in pending:
            seen.append(user["_id"])
            try:
                if await erase(user["_id"]):
                    done += 1
            except Exception:  # noqa: BLE001 -- isolate one user's failure
                logger.exception("kyc_erasure_retry_failed user=%s", user["_id"])
    return done
