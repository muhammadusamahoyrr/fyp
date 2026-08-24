"""Property-dispute intake under the Overseas Pakistanis Property Protection Act.

Split out of routes/overseas.py on 2026-08-23 when the POA/attestation desk was
removed. The two shared a prefix because both derive from the same statute, but
they are different features: the POA desk had 11 endpoints and no recorded usage,
while this flow has 38 tests and real records behind it. Keeping them together
meant deleting one to remove the other.

The endpoints are unchanged apart from the prefix (/overseas/dispute -> /disputes,
/overseas/lawyer/disputes -> /disputes/lawyer).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import get_current_user, require_lawyer
from app.services import special_court
from app.services.dispute_intake import DisputeIntake

router = APIRouter(prefix="/disputes", tags=["disputes"])

# NOTE: these endpoints deliberately return plain dicts with NO response_model.
# The dispute record has nested, evolving sub-documents (eligibility / grievance /
# jurisdiction), each a wide dict whose shape is still moving as 5a→5b lands. A
# strict Pydantic response_model is an ALLOWLIST — any field not declared is
# silently dropped from the response (the POAOut bug: verify_url / opppa_status
# vanished from the UI until the schema was patched). Returning the dict as-is is
# the safe choice while the shape is unstable.
#   Future (do NOT implement now): once the shape settles, a response_model is worth
#   adding for OpenAPI docs + output validation. A TypedDict does NOT solve the drop
#   (FastAPI still filters to declared keys), and BaseModel with extra="allow" only
#   keeps extras on INPUT, not on serialized output — so the real fix later is an
#   explicit, complete BaseModel (with nested models for eligibility/grievance/
#   jurisdiction) plus a test asserting no field is dropped, mirroring the POAOut fix.
from app.services import dispute_intake  # noqa: E402

class EligibilityBody(BaseModel):
    id_type: str
    days_abroad: int


@router.post("/eligibility")
async def dispute_eligibility(body: EligibilityBody, current_user: dict = Depends(get_current_user)):
    """Deterministic overseas-Pakistani eligibility check (no LLM)."""
    return dispute_intake.check_eligibility(body.id_type, body.days_abroad)


class ClassifyBody(BaseModel):
    text: str = Field(..., min_length=1)


@router.post("/classify")
async def dispute_classify(body: ClassifyBody, current_user: dict = Depends(get_current_user)):
    """Classify a free-text grievance into one of six categories, with a confidence
    tier. An unconfirmed or ambiguous result carries needs_triage=true and must not
    proceed to drafting."""
    return await dispute_intake.classify_grievance(body.text)


class DisputeCreateBody(BaseModel):
    id_type: str
    days_abroad: int
    grievance_text: str = Field(..., min_length=1)
    intake: DisputeIntake
    # Not optional in practice: the service refuses to file without it. Declared
    # with a False default so a caller that omits it gets a clear 422 naming the
    # penalty, rather than a schema error that says nothing about why.
    acknowledged_filing_risk: bool = False


@router.post("")
async def create_dispute(body: DisputeCreateBody, current_user: dict = Depends(get_current_user)):
    """Run the full 5a pipeline: eligibility → classify → intake → jurisdiction →
    state (ready_for_drafting | held_for_lawyer_triage). No petition text (that is 5b)."""
    try:
        return await dispute_intake.create_dispute(
            current_user["_id"], body.id_type, body.days_abroad, body.grievance_text,
            body.intake.model_dump(),
            acknowledged_filing_risk=body.acknowledged_filing_risk,
        )
    except dispute_intake.FilingRiskNotAcknowledged as exc:
        # 422, not 400: the request is well-formed, but a precondition the law
        # imposes on the user has not been met.
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
async def list_disputes(current_user: dict = Depends(get_current_user)):
    return await dispute_intake.list_disputes(current_user["_id"])


# MUST be declared before /{dispute_id}: FastAPI matches in registration order,
# so a static single-segment path registered after the parameterised one is
# swallowed by it — "filing-risk" arrives as a dispute id and 404s. The
# /special-court/* routes escape this only because they are two segments deep.
@router.get("/filing-risk")
async def filing_risk(province: str, current_user: dict = Depends(get_current_user)):
    """What the complainant must be shown before filing, by province.

    In Punjab a false complaint carries Rs 500,000 and up to five years under the
    Protection of Ownership of Immovable Property (Amendment) Ordinance 2026. The
    wizard calls this before its submit step; create_dispute independently refuses
    to file unless the acknowledgement comes back, so this endpoint being skipped
    cannot result in a silent filing.
    """
    return dispute_intake.false_complaint_risk(province)


@router.get("/{dispute_id}")
async def get_dispute(dispute_id: str, current_user: dict = Depends(get_current_user)):
    return await dispute_intake.get_dispute(dispute_id, current_user["_id"])


@router.post("/{dispute_id}/petition")
async def draft_petition(dispute_id: str, current_user: dict = Depends(get_current_user)):
    """Draft a Special-Court petition PDF for a READY_FOR_DRAFTING dispute (Phase 5b).
    Refuses a held dispute and fails on a missing field — no gap-filling, no e-filing,
    no auto-submission. Returns a plain dict (no response_model, same no-silent-drop
    choice as the other dispute endpoints)."""
    from app.services import petition_drafter
    return await petition_drafter.draft_petition(dispute_id, current_user["_id"])


@router.post("/{dispute_id}/send-to-lawyer")
async def send_dispute_to_lawyer(dispute_id: str, current_user: dict = Depends(get_current_user)):
    """Send a dispute's case brief to one verified lawyer (either state). No smart
    matching, no payment — picks the first available verified lawyer, grants them
    access to the brief (and the petition PDF if one exists), and notifies them.
    Idempotent: returns the existing assignment if already sent."""
    return await dispute_intake.send_to_lawyer(dispute_id, current_user["_id"])


@router.get("/{dispute_id}/brief")
async def dispute_case_brief(dispute_id: str, current_user: dict = Depends(get_current_user)):
    """The single case brief: eligibility, grievance classification (+confidence+alts),
    guided intake facts, jurisdiction resolution, and the petition link if one exists.
    Visible to the owning client OR the assigned lawyer. Plain dict (no response_model,
    no silent-drop)."""
    return await dispute_intake.get_case_brief(
        dispute_id, current_user["_id"], current_user.get("role", "client"))


@router.get("/lawyer/inbox")
async def lawyer_disputes(current_user: dict = Depends(require_lawyer)):
    """A lawyer's inbox of property-dispute case briefs sent to them (summaries)."""
    return await dispute_intake.list_disputes_for_lawyer(current_user["_id"])



# ── Special-Court forum lookup ────────────────────────────────────────────────
# Kept with the dispute flow rather than deleted alongside the POA desk: the
# intake wizard asks which province, and dispute_intake.py resolves the forum
# through this same module. Removing the endpoint left the wizard calling a 404.

@router.get("/special-court/provinces")
async def special_court_provinces(current_user: dict = Depends(get_current_user)):
    """Provinces offered in the Special-Court picker."""
    return {"provinces": special_court.supported_provinces()}


@router.get("/special-court/path")
async def special_court_path(province: str, current_user: dict = Depends(get_current_user)):
    """Resolve the special-court remedy for a property dispute, by province.

    Encodes the Protection of Overseas Pakistanis' Property Act 2024 regime, which
    differs by province and is standing up on a rolling basis. Fails safe: a
    province whose court is not confirmed operational is routed to the federal
    framework and a lawyer rather than told to e-file into a court that may not
    exist yet.
    """
    return special_court.resolve(province)

