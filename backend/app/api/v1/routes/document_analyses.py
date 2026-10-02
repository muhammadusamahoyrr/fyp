"""Document Analyzer HTTP surface (DOC_ANALYZER_PLAN.md §8). Client-only.

Gates, in order. Gates 1-5 read only HEADERS: a request refused by any of
them is answered before `request.form()` is called, so its multipart body is
never parsed, received into memory or spooled to a temporary file.

  1. DOC_ANALYZER off                      -> 404 feature_disabled
  2. readiness failed (no transactions, bad indexes or keys) -> 503
  3. X-Synthetic-Data-Attested != "true" or an unknown
     X-Synthetic-Attestation-Version       -> 422 synthetic_attestation_required
  4. Idempotency-Key missing or malformed  -> 422 invalid_idempotency_key
  5. no Content-Length / body over the cap -> 411 / 413
     (Starlette 0.41 has no per-file size limit of its own)
  ---- only now is the multipart body parsed ----
  6. options invalid                       -> 422
  7. content rules (upload_rules.validate) -> 422 / 413
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile

from app.core.config import settings
from app.core.constants import UserRole
from app.dependencies import require_admin, require_client, require_lawyer, role_required
from app.services.analyzer import (
    approvals,
    confirmation,
    deletion,
    lifecycle,
    readiness,
    upload_rules,
)
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
    attested: str | None = Header(default=None, alias="X-Synthetic-Data-Attested"),
    attestation_version: str | None = Header(default=None, alias="X-Synthetic-Attestation-Version"),
    current_user: dict = Depends(require_client),
):
    _require_available()
    try:
        # Headers only, all before the body: see the module docstring.
        attestation = upload_rules.check_attestation(attested, attestation_version)
        lifecycle.check_idempotency_key(idempotency_key)
    except AnalyzerError as exc:
        _fail(exc.status, exc.code, exc.message)
    _body_within_cap(request)

    form = await request.form(max_files=1, max_fields=8)
    try:
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


class OcrTextBody(BaseModel):
    expected_state_version: int = Field(ge=0)
    #: Omit to confirm the proposed text as it is; send the full corrected
    #: text to replace it (a new version either way).
    text: str | None = Field(default=None, max_length=400_000)


@router.get("/runs/{run_id}")
async def get_analysis_run(run_id: str, current_user: dict = Depends(require_client)):
    """Poll a run. While it waits for OCR confirmation, includes the text to check."""
    _require_available()
    return await _run(confirmation.get_run(owner_id=str(current_user["_id"]), run_id=run_id))


@router.post("/runs/{run_id}/ocr-text")
async def confirm_ocr_text(run_id: str, body: OcrTextBody = Body(...),
                           current_user: dict = Depends(require_client)):
    _require_available()
    return await _run(confirmation.confirm_ocr_text(
        owner_id=str(current_user["_id"]), run_id=run_id,
        expected_state_version=body.expected_state_version, corrected_text=body.text))


class DocumentBody(BaseModel):
    expected_state_version: int = Field(ge=0)
    document_type: str = Field(max_length=32)
    jurisdiction: str = Field(max_length=32)


class TermsBody(BaseModel):
    expected_state_version: int = Field(ge=0)
    #: {term: {"value": ..., "sentence_ids": [...]}}; null value = "not stated".
    terms: dict


@router.post("/runs/{run_id}/document")
async def confirm_document(run_id: str, body: DocumentBody = Body(...),
                           current_user: dict = Depends(require_client)):
    _require_available()
    return await _run(confirmation.confirm_document(
        owner_id=str(current_user["_id"]), run_id=run_id,
        expected_state_version=body.expected_state_version,
        document_type=body.document_type, jurisdiction=body.jurisdiction))


@router.post("/runs/{run_id}/terms")
async def confirm_terms(run_id: str, body: TermsBody = Body(...),
                        current_user: dict = Depends(require_client)):
    _require_available()
    return await _run(confirmation.confirm_terms(
        owner_id=str(current_user["_id"]), run_id=run_id,
        expected_state_version=body.expected_state_version, confirmed=body.terms))


@router.post("/runs/{run_id}/cancel")
async def cancel_analysis_run(run_id: str, current_user: dict = Depends(require_client)):
    _require_available()
    return await _run(confirmation.cancel_run(owner_id=str(current_user["_id"]), run_id=run_id))


@router.get("")
@router.get("/", include_in_schema=False)
async def list_document_analyses(limit: int = 20, before: str | None = None,
                                 current_user: dict = Depends(require_client)):
    """History: the caller's live analyses, newest first."""
    _require_available()
    return await _run(lifecycle.list_analyses(owner_id=str(current_user["_id"]),
                                              limit=limit, before=before))


@router.get("/runs/{run_id}/text")
async def get_analysis_text(run_id: str, current_user: dict = Depends(require_client)):
    """Text, clauses and sentences with offsets, for the text viewer."""
    _require_available()
    return await _run(confirmation.get_text(owner_id=str(current_user["_id"]), run_id=run_id))


@router.get("/runs/{run_id}/graph")
async def get_analysis_graph(run_id: str, current_user: dict = Depends(require_client)):
    """Definitions and cross-references, anchored by offsets and stable ids."""
    _require_available()
    return await _run(confirmation.get_graph(owner_id=str(current_user["_id"]), run_id=run_id))


@router.get("/runs/{run_id}/report")
async def get_analysis_report(run_id: str, current_user: dict = Depends(require_client)):
    """Findings with scope labels and server-cut evidence. 409 until done."""
    _require_available()
    return await _run(confirmation.get_report(owner_id=str(current_user["_id"]), run_id=run_id))


# ── legal playbook review (P2B) ──────────────────────────────────────────────
#
# Literal paths, registered BEFORE the generic /{source_id} routes below, which
# would otherwise capture "playbooks" or "approval-audit" as a source id.

require_reviewer = role_required(UserRole.LAWYER, UserRole.ADMIN)


class ApprovalBody(BaseModel):
    #: The hash of the text the reviewer READ (from GET /playbooks/{id}).
    content_hash: str = Field(min_length=64, max_length=64)
    #: The hash of the official text it cites, from the same response.
    authorities_hash: str = Field(min_length=64, max_length=64)
    #: The capacity in which they approve, e.g. "Advocate High Court, Punjab".
    reviewer_role: str = Field(min_length=1, max_length=200)


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class QualificationBody(BaseModel):
    user_id: str = Field(min_length=1, max_length=200)
    qualification: str = Field(min_length=4, max_length=100)
    #: What the grant rests on: enrolment, bar, practice area.
    basis: str = Field(min_length=1, max_length=500)


@router.get("/playbooks")
async def list_playbooks(current_user: dict = Depends(require_reviewer)):
    """Every pack with its hash, required qualification and active approvals."""
    _require_available()
    return await approvals.list_playbooks()


@router.get("/playbooks/{pack_id}")
async def get_playbook(pack_id: str, current_user: dict = Depends(require_reviewer)):
    """The exact text to review, and the hash an approval must quote."""
    _require_available()
    try:
        return approvals.playbook_text(pack_id)
    except AnalyzerError as exc:
        _fail(exc.status, exc.code, exc.message)


@router.post("/playbooks/{pack_id}/approvals", status_code=201)
async def approve_playbook(pack_id: str, body: ApprovalBody = Body(...),
                           current_user: dict = Depends(require_lawyer)):
    """The caller approves this exact text, as themselves."""
    _require_available()
    record = await _run(approvals.record_approval(
        reviewer=current_user, pack_id=pack_id, content_hash=body.content_hash,
        authorities_hash=body.authorities_hash, reviewer_role=body.reviewer_role))
    return {"approval_id": record["_id"], "pack_id": record["pack_id"],
            "content_hash": record["content_hash"], "authorities_hash": record["authorities_hash"],
            "approved_at": record["approved_at"]}


@router.post("/playbook-approvals/{approval_id}/revoke")
async def revoke_playbook_approval(approval_id: str, body: ReasonBody = Body(...),
                                   current_user: dict = Depends(require_reviewer)):
    _require_available()
    return await _run(approvals.revoke_approval(actor=current_user, approval_id=approval_id,
                                                reason=body.reason))


@router.post("/reviewer-qualifications", status_code=201)
async def grant_reviewer_qualification(body: QualificationBody = Body(...),
                                       current_user: dict = Depends(require_admin)):
    _require_available()
    grant = await _run(approvals.grant_qualification(
        admin=current_user, user_id=body.user_id, qualification=body.qualification,
        basis=body.basis))
    return {"grant_id": grant["_id"], "user_id": grant["user_id"],
            "qualification": grant["qualification"]}


@router.post("/reviewer-qualifications/{grant_id}/revoke")
async def revoke_reviewer_qualification(grant_id: str, body: ReasonBody = Body(...),
                                        current_user: dict = Depends(require_admin)):
    _require_available()
    return await _run(approvals.revoke_qualification(admin=current_user, grant_id=grant_id,
                                                     reason=body.reason))


@router.get("/approval-audit")
async def approval_audit(limit: int = 100, current_user: dict = Depends(require_admin)):
    _require_available()
    return await approvals.audit_trail(limit=limit)


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
    """Tombstone + purge job in one transaction; every NEW read 404s from the commit on.

    Not found, not the owner and already deleted all answer 404, so the route
    reveals nothing about analyses that are not the caller's.
    """
    _require_available()
    await _run(deletion.delete_analysis(owner_id=str(current_user["_id"]), source_id=source_id))
    return Response(status_code=204)
