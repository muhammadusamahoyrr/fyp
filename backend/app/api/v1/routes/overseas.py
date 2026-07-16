from fastapi import APIRouter, Depends, File, Response, UploadFile
from pydantic import BaseModel, Field

from app.dependencies import get_current_user, require_lawyer
from app.schemas.overseas import POAOut
from app.services import apostille_status, opppa, overseas_service, poa_advisor, special_court
from app.services.dispute_intake import DisputeIntake

router = APIRouter(prefix="/overseas", tags=["overseas"])


class PoaCreate(BaseModel):
    poa_type: str = "special"          # special | general
    principal_name: str = ""
    principal_cnic: str = ""
    principal_address: str = ""
    attorney_name: str
    attorney_cnic: str = ""
    attorney_relation: str = ""
    attorney_address: str = ""
    subject: str = ""
    powers: list[str] = Field(default_factory=list)
    restrictions: str = ""
    country_of_execution: str = ""
    issue_date: str = ""
    expiry_date: str = ""


class ExecutionUpdate(BaseModel):
    execution_status: str = Field(..., min_length=1)


@router.get("/attestation/countries")
async def attestation_countries(current_user: dict = Depends(get_current_user)):
    """Countries offered in the Attestation Navigator picker."""
    return {"countries": apostille_status.supported_countries()}


@router.get("/attestation/path")
async def attestation_path(
    country: str,
    for_property: bool = True,
    current_user: dict = Depends(get_current_user),
):
    """Resolve the correct attestation route (apostille vs legacy consular chain)
    for a POA executed in `country` and used in Pakistan.

    Apostille-aware and objection-aware: an objecting member (e.g. Germany) or a
    non-recognised state (India) correctly gets the legacy chain, and an unknown
    country fails safe to the legacy chain rather than the shorter apostille path.
    """
    return apostille_status.resolve(country, for_property=for_property)


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


@router.get("/opppa/guidance")
async def opppa_guidance(current_user: dict = Depends(get_current_user)):
    """How and why to register a property with OPPPA (the 2024 Act's authority)."""
    return opppa.guidance()


class OpppaStatusBody(BaseModel):
    status: str = Field(..., min_length=1)


@router.patch("/poa/{poa_id}/opppa", response_model=POAOut)
async def set_opppa(poa_id: str, body: OpppaStatusBody, current_user: dict = Depends(get_current_user)):
    """Record the property's OPPPA registration status (not_registered / in_progress / registered)."""
    return await overseas_service.set_opppa_status(poa_id, current_user["_id"], body.status)


class IntentBody(BaseModel):
    intent: str = Field(..., min_length=1)


@router.post("/poa/suggest")
async def suggest_poa(body: IntentBody, current_user: dict = Depends(get_current_user)):
    """Plain-English intent -> a rule-checked POA structure (type, powers, subject).

    The safety rules (disposal -> Special + registration) are enforced in code, so a
    model slip cannot produce a dangerous structure.
    """
    return await poa_advisor.suggest_structure(body.intent)


class RiskBody(BaseModel):
    poa_type: str = "special"
    powers: list[str] = Field(default_factory=list)
    subject: str = ""
    expiry_date: str = ""
    attorney_relation: str = ""


@router.post("/poa/risk")
async def poa_risk(body: RiskBody, current_user: dict = Depends(get_current_user)):
    """Deterministic fraud-risk score of a drafted POA, with reasons."""
    return poa_advisor.assess_risk(body.model_dump())


# ── Phase 5a — property-dispute intake (Special Courts, 2024 Act) ─────────────
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


@router.post("/dispute/eligibility")
async def dispute_eligibility(body: EligibilityBody, current_user: dict = Depends(get_current_user)):
    """Deterministic overseas-Pakistani eligibility check (no LLM)."""
    return dispute_intake.check_eligibility(body.id_type, body.days_abroad)


class ClassifyBody(BaseModel):
    text: str = Field(..., min_length=1)


@router.post("/dispute/classify")
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


@router.post("/dispute")
async def create_dispute(body: DisputeCreateBody, current_user: dict = Depends(get_current_user)):
    """Run the full 5a pipeline: eligibility → classify → intake → jurisdiction →
    state (ready_for_drafting | held_for_lawyer_triage). No petition text (that is 5b)."""
    return await dispute_intake.create_dispute(
        current_user["_id"], body.id_type, body.days_abroad, body.grievance_text,
        body.intake.model_dump(),
    )


@router.get("/dispute")
async def list_disputes(current_user: dict = Depends(get_current_user)):
    return await dispute_intake.list_disputes(current_user["_id"])


@router.get("/dispute/{dispute_id}")
async def get_dispute(dispute_id: str, current_user: dict = Depends(get_current_user)):
    return await dispute_intake.get_dispute(dispute_id, current_user["_id"])


@router.post("/dispute/{dispute_id}/petition")
async def draft_petition(dispute_id: str, current_user: dict = Depends(get_current_user)):
    """Draft a Special-Court petition PDF for a READY_FOR_DRAFTING dispute (Phase 5b).
    Refuses a held dispute and fails on a missing field — no gap-filling, no e-filing,
    no auto-submission. Returns a plain dict (no response_model, same no-silent-drop
    choice as the other dispute endpoints)."""
    from app.services import petition_drafter
    return await petition_drafter.draft_petition(dispute_id, current_user["_id"])


@router.post("/dispute/{dispute_id}/send-to-lawyer")
async def send_dispute_to_lawyer(dispute_id: str, current_user: dict = Depends(get_current_user)):
    """Send a dispute's case brief to one verified lawyer (either state). No smart
    matching, no payment — picks the first available verified lawyer, grants them
    access to the brief (and the petition PDF if one exists), and notifies them.
    Idempotent: returns the existing assignment if already sent."""
    return await dispute_intake.send_to_lawyer(dispute_id, current_user["_id"])


@router.get("/dispute/{dispute_id}/brief")
async def dispute_case_brief(dispute_id: str, current_user: dict = Depends(get_current_user)):
    """The single case brief: eligibility, grievance classification (+confidence+alts),
    guided intake facts, jurisdiction resolution, and the petition link if one exists.
    Visible to the owning client OR the assigned lawyer. Plain dict (no response_model,
    no silent-drop)."""
    return await dispute_intake.get_case_brief(
        dispute_id, current_user["_id"], current_user.get("role", "client"))


@router.get("/lawyer/disputes")
async def lawyer_disputes(current_user: dict = Depends(require_lawyer)):
    """A lawyer's inbox of property-dispute case briefs sent to them (summaries)."""
    return await dispute_intake.list_disputes_for_lawyer(current_user["_id"])


@router.post("/poa", response_model=POAOut)
async def create_poa(body: PoaCreate, current_user: dict = Depends(get_current_user)):
    """Generate a Power of Attorney PDF and register it."""
    return await overseas_service.create_poa(current_user["_id"], body.model_dump())


@router.get("/poa", response_model=list[POAOut])
async def list_poas(current_user: dict = Depends(get_current_user)):
    return await overseas_service.list_poas(current_user["_id"])


@router.get("/poa/{poa_id}", response_model=POAOut)
async def get_poa(poa_id: str, current_user: dict = Depends(get_current_user)):
    return await overseas_service.get_poa(poa_id, current_user["_id"])


@router.post("/poa/{poa_id}/revoke", response_model=POAOut)
async def revoke_poa(poa_id: str, current_user: dict = Depends(get_current_user)):
    """Revoke a POA and generate the Deed of Revocation."""
    return await overseas_service.revoke_poa(poa_id, current_user["_id"])


@router.patch("/poa/{poa_id}/execution", response_model=POAOut)
async def set_execution(poa_id: str, body: ExecutionUpdate, current_user: dict = Depends(get_current_user)):
    """Advance the attestation lifecycle (drafted → … → registered)."""
    return await overseas_service.set_execution_status(poa_id, current_user["_id"], body.execution_status)


@router.post("/poa/{poa_id}/acknowledge", response_model=POAOut)
async def acknowledge(poa_id: str, current_user: dict = Depends(get_current_user)):
    """Record that the attorney has acknowledged the POA."""
    return await overseas_service.acknowledge(poa_id, current_user["_id"])


@router.post("/poa/{poa_id}/verify-attested")
async def verify_attested(
    poa_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Upload the returned, attested POA; report the attestation markers found and
    whether it matches the POA on record ('did they attest the right thing')."""
    return await overseas_service.verify_attested_upload(poa_id, current_user["_id"], file)


@router.get("/verify/{token}/qr.svg")
async def verify_qr(token: str):
    """PUBLIC QR image for the verify link — for on-screen display. Scanning it
    opens the verification page. No auth (the token is the capability)."""
    return Response(content=overseas_service.verify_qr_svg(token), media_type="image/svg+xml")


@router.get("/verify/{token}")
async def verify_poa(token: str):
    """PUBLIC point-of-use verification — no auth, the token is the capability.

    A counterparty holding the POA (buyer's lawyer, sub-registrar) checks its live
    status, exact authorised scope, and the document SHA-256 tamper-hash. This is
    what stops a revoked or forged POA being honoured because nobody knew.
    """
    return await overseas_service.verify_by_token(token)
