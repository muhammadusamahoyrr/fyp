from fastapi import APIRouter, Body, Depends, File, Path, Request, UploadFile

from app.core.rate_limit import limiter
from app.dependencies import require_client
from app.schemas.intake import (
    IntakeClarifyRequest,
    IntakeClarifyResponse,
    IntakeConvertRequest,
    IntakeDetailResponse,
    IntakeResponse,
    IntakeStartResponse,
    IntakeStepData,
)
from app.services import intake_service

router = APIRouter(prefix="/intake", tags=["intake"])

# RATE LIMITS, AND WHY THESE NUMBERS.
#
# None of these routes had one. Three of them are expensive in ways a client
# cannot see: `/clarify` and `/convert` each spend LLM calls, and `/evidence`
# writes 10 MB to disk with no cap on how many times. `/start` writes a document
# per call, so a loop leaves thousands of abandoned intake sessions behind.
#
# Sized for a human filling in a form, with enough headroom for a retry after a
# dropped connection. They are deliberately not generous: the limiter keys on the
# caller, so a legitimate client never approaches these while a script hits them
# immediately.
_LIMIT_START    = "10/minute"    # one per intake; a handful of restarts is normal
_LIMIT_STEP     = "60/minute"    # five steps, edited and re-saved freely
_LIMIT_CLARIFY  = "12/minute"    # LLM call each; 4 rounds plus retries
_LIMIT_CONVERT  = "6/minute"     # LLM pipeline each; idempotent, so retries are cheap
_LIMIT_EVIDENCE = "20/minute"    # 10 MB per file


@router.post("/start", response_model=IntakeStartResponse)
@limiter.limit(_LIMIT_START)
async def start_intake(request: Request, current_user: dict = Depends(require_client)):
    return await intake_service.start_intake(current_user["_id"])


@router.get("/resumable", response_model=IntakeDetailResponse | None)
@limiter.limit(_LIMIT_STEP)
async def resumable_intake(
    request: Request,
    current_user: dict = Depends(require_client),
):
    """The intake this client should be put back into, or null.

    DECLARED BEFORE `/{token}` ON PURPOSE. FastAPI matches routes in the order
    they are added, so a `/resumable` declared after the token route would never
    be reached — the literal would be captured as a session token and answered
    with 404 for an intake called "resumable".

    Resuming used to depend on a token in one browser's localStorage, which
    sign-out clears. After conversion that token is the only route to a draft
    case awaiting confirmation, so signing out in between left a case its owner
    could never confirm. The server knows which intakes are unfinished; this is
    it saying so.
    """
    return await intake_service.get_resumable_intake(current_user["_id"])


@router.get("/{token}", response_model=IntakeDetailResponse)
async def get_intake(
    token: str,
    current_user: dict = Depends(require_client),
):
    return await intake_service.get_intake(token, current_user["_id"])


@router.patch("/{token}/step/{step}", response_model=IntakeResponse)
@limiter.limit(_LIMIT_STEP)
async def save_step(
    request: Request,
    token: str,
    step: int = Path(ge=1, le=5),
    body: IntakeStepData = ...,
    current_user: dict = Depends(require_client),
):
    return await intake_service.save_step(
        token, step, body.data, current_user["_id"]
    )


@router.post("/{token}/clarify", response_model=IntakeClarifyResponse)
@limiter.limit(_LIMIT_CLARIFY)
async def clarify_intake(
    request: Request,
    token: str,
    body: IntakeClarifyRequest,
    current_user: dict = Depends(require_client),
):
    """
    Multi-round AI clarification (up to _MAX_CLARIFY_ROUNDS, currently 4).
    Call 1: body.answer = null        → returns Q1
    Call N: body.answer = <previous>   → returns the next question, or done=true

    Idempotent: calling with no answer while a question is outstanding returns
    that same question rather than generating another one.
    """
    return await intake_service.get_clarification(token, current_user["_id"], body.answer)


@router.post("/{token}/evidence")
@limiter.limit(_LIMIT_EVIDENCE)
async def upload_evidence(
    request: Request,
    token: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(require_client),
):
    return await intake_service.upload_evidence(token, current_user["_id"], file)


@router.get("/{token}/evidence/{file_id}")
@limiter.limit(_LIMIT_STEP)
async def download_evidence(
    request: Request,
    token: str,
    file_id: str,
    current_user: dict = Depends(require_client),
):
    """Read back a file the client uploaded.

    There was no way to do this: evidence could be attached and never seen
    again. Served through the API rather than a static path so the ownership
    check cannot be bypassed by guessing a filename.
    """
    from fastapi.responses import FileResponse

    path, filename, mime = await intake_service.get_evidence_file(
        token, current_user["_id"], file_id
    )
    return FileResponse(path, media_type=mime, filename=filename)


@router.delete("/{token}/evidence/{file_id}")
@limiter.limit(_LIMIT_STEP)
async def delete_evidence(
    request: Request,
    token: str,
    file_id: str,
    current_user: dict = Depends(require_client),
):
    """Remove an uploaded file — the record and the bytes.

    The UI's ✕ removed a row from a React array and nothing else, so the file
    stayed on disk and on the intake for ever.
    """
    return await intake_service.delete_evidence_file(
        token, current_user["_id"], file_id
    )


@router.post("/{token}/convert", response_model=IntakeResponse)
@limiter.limit(_LIMIT_CONVERT)
async def convert_to_case(
    request: Request,
    token: str,
    body: IntakeConvertRequest | None = Body(default=None),
    current_user: dict = Depends(require_client),
):
    language = body.language if body else "en"
    urgency  = body.urgency  if body else None
    return await intake_service.convert_to_case(
        token, current_user["_id"],
        language=language,
        urgency=urgency,
    )
