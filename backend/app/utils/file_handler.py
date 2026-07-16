"""Upload storage helpers. Single source of truth for file-type detection.

Files are validated by their actual CONTENT (magic bytes), never by the
client-supplied filename/extension or Content-Type header. Stored files get a
random name whose extension is derived from the detected type; the original
filename is display-only and never used to build a path.
"""
import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.core.config import settings

UPLOADS_ROOT = Path(settings.upload_root)
MAX_MB = 10

# Detected MIME -> canonical stored extension. Also the default allow-list.
_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png":  ".png",
    "image/gif":  ".gif",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}


def detect_mime(header: bytes) -> str | None:
    """MIME type from magic bytes — never trusts the client Content-Type."""
    if header[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if header[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if header[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if header[:4] == b"%PDF":
        return "application/pdf"
    if header[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "application/msword"
    if header[:4] == b"PK\x03\x04":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return None


def ext_for_mime(mime: str | None) -> str:
    """Canonical file extension for a detected MIME type ('' if unknown)."""
    return _MIME_EXT.get(mime or "", "")


async def save_upload(
    file: UploadFile,
    subfolder: str = "misc",
    allowed_mimes: set[str] | None = None,
) -> str:
    allowed = allowed_mimes or set(_MIME_EXT)
    content = await file.read()
    if len(content) > MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File exceeds {MAX_MB} MB limit")

    mime = detect_mime(content[:16])
    if mime not in allowed:
        raise HTTPException(
            status_code=400,
            detail="File type not allowed. Accepted: PDF, Word, JPEG, PNG, GIF, WebP",
        )

    dest_dir = UPLOADS_ROOT / subfolder
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Random name + extension from the DETECTED type (not the client filename).
    filename = secrets.token_urlsafe(16) + ext_for_mime(mime)
    dest = dest_dir / filename
    dest.write_bytes(content)
    return str(dest)


def delete_file(path: str) -> None:
    p = Path(path)
    if p.exists():
        p.unlink()
