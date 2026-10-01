"""What the analyzer accepts, decided from the file's CONTENT (plan §4.8).

Never the filename, never the client's Content-Type. Checks here are the cheap
ones that need no parser a hostile file could stall: size, magic bytes, the
DOCX zip's DECLARED structure, and an image's header dimensions.

WHAT IS DELIBERATELY LEFT TO EXTRACTION (slice 2, in the killable child
process): the PDF page count (40), the actual -- not declared -- decompressed
DOCX size, table count and nesting, and the 300,000-character canonical text
cap. A zip's central directory can lie about sizes; only reading it under a
limit proves them, and that belongs where a runaway read can be killed.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass

from app.services.analyzer.errors import UploadRejected
from app.utils.file_handler import detect_mime

MAX_BYTES = 10 * 1024 * 1024

# DOCX (declared sizes from the central directory; see module docstring)
DOCX_MAX_ENTRIES = 1000
DOCX_MAX_TOTAL_UNCOMPRESSED = 50 * 1024 * 1024
DOCX_MAX_ENTRY_UNCOMPRESSED = 20 * 1024 * 1024
DOCX_MAX_RATIO = 100
DOCX_RATIO_MIN_ENTRY = 1024 * 1024          # tiny XML parts legitimately compress far
DOCX_MAX_DOCUMENT_XML = 5_000_000
DOCX_REQUIRED = ("[Content_Types].xml", "word/document.xml")

# Images (OCR path only)
IMAGE_MAX_PIXELS = 25_000_000

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
JPEG = "image/jpeg"
PNG = "image/png"
ACCEPTED = {PDF: "pdf", DOCX: "docx", JPEG: "image", PNG: "image"}

SIDES = ("tenant", "landlord", "neutral")
DEPTHS = ("quick", "medium", "deep")

#: The exact warning each attestation version refers to. The UI shows this
#: text; the source records which version the user confirmed (plan §7).
ATTESTATION_VERSIONS: dict[str, str] = {
    "synthetic-v1": (
        "Demo only — do not upload real client or confidential documents. "
        "I confirm this document is synthetic (made up for testing)."),
}


@dataclass(frozen=True)
class ValidatedFile:
    mime: str
    kind: str          # pdf | docx | image
    size: int
    sha256: str


def validate(content: bytes) -> ValidatedFile:
    if not content:
        raise UploadRejected("empty_file", "The file is empty.")
    if len(content) > MAX_BYTES:
        raise UploadRejected("file_too_large", "The file is larger than 10 MB.", status=413)
    mime = detect_mime(content[:16])
    if mime == "application/msword":
        raise UploadRejected(
            "doc_not_supported",
            "Old Word (.doc) files are not supported. Save it as .docx or PDF and try again.")
    if mime not in ACCEPTED:
        raise UploadRejected("unsupported_type", "Only PDF, DOCX, JPG and PNG files are accepted.")
    if mime == DOCX:
        _check_docx(content)
    elif ACCEPTED[mime] == "image":
        _check_image(content)
    return ValidatedFile(mime=mime, kind=ACCEPTED[mime], size=len(content),
                         sha256=hashlib.sha256(content).hexdigest())


def _check_docx(content: bytes) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
        entries = archive.infolist()
    except (zipfile.BadZipFile, ValueError, OSError):
        raise UploadRejected("invalid_docx", "The file is not a readable .docx document.") from None
    names = {e.filename for e in entries}
    if not all(name in names for name in DOCX_REQUIRED):
        # PK magic alone means "a zip", not "a Word document".
        raise UploadRejected("invalid_docx", "The file is not a readable .docx document.")
    if len(entries) > DOCX_MAX_ENTRIES:
        raise UploadRejected("docx_too_complex", "The .docx file has too many parts.")
    total_in = total_out = 0
    for entry in entries:
        if entry.flag_bits & 0x1:
            raise UploadRejected("encrypted_docx", "Password-protected .docx files are not supported.")
        if entry.file_size > DOCX_MAX_ENTRY_UNCOMPRESSED:
            raise UploadRejected("docx_too_large", "The .docx file expands beyond the allowed size.")
        if (entry.file_size >= DOCX_RATIO_MIN_ENTRY and entry.compress_size > 0
                and entry.file_size / entry.compress_size > DOCX_MAX_RATIO):
            raise UploadRejected("docx_too_large", "The .docx file expands beyond the allowed size.")
        if entry.filename == "word/document.xml" and entry.file_size > DOCX_MAX_DOCUMENT_XML:
            raise UploadRejected("docx_too_large", "The document text is longer than this version accepts.")
        total_out += entry.file_size
        total_in += entry.compress_size
    if total_out > DOCX_MAX_TOTAL_UNCOMPRESSED or (
            total_in > 0 and total_out >= DOCX_RATIO_MIN_ENTRY and total_out / total_in > DOCX_MAX_RATIO):
        raise UploadRejected("docx_too_large", "The .docx file expands beyond the allowed size.")


def _check_image(content: bytes) -> None:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(content)) as img:     # reads the header only
            width, height = img.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise UploadRejected("invalid_image", "The image could not be read.") from None
    if width * height > IMAGE_MAX_PIXELS:
        raise UploadRejected("image_too_large", "The image is larger than 25 megapixels.")


def normalise_options(side: str | None, depth: str | None) -> dict:
    side = (side or "tenant").strip().lower()
    depth = (depth or "medium").strip().lower()
    if side not in SIDES:
        raise UploadRejected("invalid_side", "Choose tenant, landlord or neutral.")
    if depth not in DEPTHS:
        raise UploadRejected("invalid_depth", "Choose quick, medium or deep.")
    return {"side": side, "depth": depth}


def check_attestation(attested: str | None, version: str | None) -> dict:
    """The synthetic-data attestation, or a refusal.

    Arrives as headers (X-Synthetic-Data-Attested / X-Synthetic-Attestation-
    Version) and is checked BEFORE the multipart body is parsed.
    """
    if attested != "true":
        raise UploadRejected(
            "synthetic_attestation_required",
            "Confirm that this document is synthetic. Real client or confidential "
            "documents must not be uploaded to the demo.")
    if version not in ATTESTATION_VERSIONS:
        raise UploadRejected("synthetic_attestation_required",
                             "The confirmation wording is out of date. Reload and confirm again.")
    return {"synthetic": True, "ui_text_version": version}


def request_fingerprint(file_sha256: str, options: dict, attestation: dict) -> str:
    """What makes two uploads under one Idempotency-Key "the same request"."""
    material = json.dumps({"file": file_sha256, "options": options,
                           "attestation": attestation}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
