from pathlib import Path

from fastapi import HTTPException, UploadFile

UPLOADS_ROOT = Path(__file__).parent.parent.parent / "uploads"
MAX_MB = 10
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".docx"}


async def save_upload(file: UploadFile, subfolder: str = "misc") -> str:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed: {ALLOWED_EXTENSIONS}",
        )

    content = await file.read()
    if len(content) > MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File exceeds {MAX_MB} MB limit")

    dest_dir = UPLOADS_ROOT / subfolder
    dest_dir.mkdir(parents=True, exist_ok=True)

    import secrets
    filename = secrets.token_urlsafe(16) + suffix
    dest = dest_dir / filename
    dest.write_bytes(content)
    return str(dest)


def delete_file(path: str) -> None:
    p = Path(path)
    if p.exists():
        p.unlink()
