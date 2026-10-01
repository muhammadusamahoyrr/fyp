"""Document Analyzer HTTP surface (DOC_ANALYZER_PLAN.md §8). Client-only.

Gates, in order, before any byte of the file is used:

  1. DOC_ANALYZER off                      -> 404 feature_disabled
  2. readiness failed (no transactions, bad indexes or keys) -> 503
  3. no Content-Length / body over the cap -> 411 / 413, BEFORE the multipart
     body is parsed (Starlette 0.41 has no per-file size limit of its own)
  4. synthetic_data_attested != "true"     -> 422 synthetic_attestation_required
  5. Idempotency-Key missing / too long    -> 422
  6. options invalid                       -> 422
  7. content rules (upload_rules.validate) -> 422 / 413
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from starlette.datastructures import UploadFile

from app.core.config import settings
from app.dependencies import require_client
from app.services.analyzer import deletion, lifecycle, readiness, upload_rules
from app.services.analyzer.errors import AnalyzerError

router = APIRouter(prefix="/documents/analyses", tags=["document-analyses"])

#: Multipart framing and the few small form fields ride on top of the file.
FORM_OVERHEAD = 64 * 1024


def _fail(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def _require_available() -> None:
    if not settings.doc_analyzer:
        _fail(404, "feature_disabled", "Not found.")
    if not readiness.is_ready():
        _fail(503, "analyzer_unavailable",
              "Document analysis is temporarily unavailable. Nothing was saved.")


async def _run(coro):
    try:
        return await coro
    except AnalyzerError as exc:
        _fail(exc.status, exc.code, exc.message)


def _body_within_cap(request: Request) -> None:
    raw = request.headers.get("content-length")
    if raw is None:
        _fail(411, "length_required", "The upload must declare its size.")
    try:
        declared = int(raw)
    except ValueError:
        _fail(400, "bad_content_length", "The upload declared an invalid size.")
    if declared > upload_rules.MAX_BYTES + FORM_OVERHEAD:
        _fail(413, "file_too_large", "The file is larger than 10 MB.")


async def _read_capped(file: UploadFile) -> bytes:
    content = await file.read(upload_rules.MAX_BYTES + 1)
    if len(content) > upload_rules.MAX_BYTES:
        _fail(413, "file_too_large", "The file is larger than 10 MB.")
    return content


@router.post("", status_code=202)
@router.post("/", status_code=202, include_in_schema=False)
async def create_document_analysis(
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: dict = Depends(require_client),
):
    _require_available()
    _body_within_cap(request)

    form = await request.form(max_files=1, max_fields=8)
    try:
        # The attestation comes first: without it nothing else is looked at.
        attestation = upload_rules.check_attestation(
            form.get("synthetic_data_attested"), form.get("attestation_version"))
        if not idempotency_key or len(idempotency_key) > lifecycle.MAX_KEY_LENGTH:
            _fail(422, "missing_idempotency_key",
                  "The Idempotency-Key header is required (at most 200 characters).")
        options = upload_rules.normalise_options(form.get("side"), form.get("depth"))
        file = form.get("file")
        if not isinstance(file, UploadFile):
            _fail(422, "file_required", "Attach the document to analyse.")
        content = await _read_capped(file)
        validated = upload_rules.validate(content)
        result = await lifecycle.create_analysis(
            owner_id=str(current_user["_id"]), idempotency_key=idempotency_key,
            content=content, validated=validated, options=options,
            attestation=attestation, filename=file.filename)
    except AnalyzerError as exc:
        _fail(exc.status, exc.code, exc.message)
    finally:
        await form.close()
    return {**result, "status": "queued_extract"}


@router.get("/attestation")
async def attestation_text(current_user: dict = Depends(require_client)):
    """The wording the UI must show, and the version to send back."""
    _require_available()
    version = max(upload_rules.ATTESTATION_VERSIONS)
    return {"version": version, "text": upload_rules.ATTESTATION_VERSIONS[version]}


@router.get("/{source_id}")
async def get_document_analysis(source_id: str, current_user: dict = Depends(require_client)):
    _require_available()
    return await _run(lifecycle.get_analysis(owner_id=str(current_user["_id"]),
                                             source_id=source_id))


@router.delete("/{source_id}", status_code=204)
async def delete_document_analysis(source_id: str, current_user: dict = Depends(require_client)):
    """Tombstone + purge job in one transaction; hidden from every read at once.

    Not found, not the owner and already deleted all answer 404, so the route
    reveals nothing about analyses that are not the caller's.
    """
    _require_available()
    await _run(deletion.delete_analysis(owner_id=str(current_user["_id"]), source_id=source_id))
    return Response(status_code=204)
