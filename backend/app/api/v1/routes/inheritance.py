from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.exceptions import AppValidationError
from app.dependencies import get_current_user
from app.schemas.inheritance import (
    DemandLetterResult,
    InheritanceCalculation,
    SettlementPdfResult,
    WasiyyatComputation,
    WasiyyatPdfResult,
)
from app.services import document_service
from app.services import inheritance as inheritance_service
from app.services import wasiyyat as wasiyyat_service

router = APIRouter(prefix="/inheritance", tags=["inheritance"])


class Heirs(BaseModel):
    husband: int = Field(0, ge=0, le=1)
    wives: int = Field(0, ge=0, le=4)
    sons: int = Field(0, ge=0)
    daughters: int = Field(0, ge=0)
    father: int = Field(0, ge=0, le=1)
    mother: int = Field(0, ge=0, le=1)
    predeceased_sons: int = Field(0, ge=0)
    predeceased_daughters: int = Field(0, ge=0)
    full_brothers: int = Field(0, ge=0)
    full_sisters: int = Field(0, ge=0)


class CalculateRequest(BaseModel):
    estate_value: int = Field(..., gt=0)
    heirs: Heirs


class SettlementRequest(CalculateRequest):
    deceased_name: str = ""
    date_of_death: str = ""
    estate_description: str = ""


class DemandRequest(BaseModel):
    claimant_name: str
    claimant_address: str = ""
    recipient_name: str
    recipient_address: str = ""
    deceased_name: str
    date_of_death: str = ""
    relation: str = "legal heir"
    estate_description: str = ""
    share_fraction: str = ""
    share_amount: int | None = None
    additional_facts: str = ""
    response_days: int = 15


def _calc(body: CalculateRequest) -> dict:
    heirs = body.heirs.model_dump()
    if not any(heirs.values()):
        raise AppValidationError("At least one heir is required")
    try:
        return inheritance_service.calculate(body.estate_value, heirs)
    except ValueError as exc:
        raise AppValidationError(str(exc))


@router.post("/calculate", response_model=InheritanceCalculation)
async def calculate_shares(
    body: CalculateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Deterministic Faraid share computation (Sunni Hanafi + MFLO 1961 s.4)."""
    return _calc(body)


@router.post("/settlement-pdf", response_model=SettlementPdfResult)
async def settlement_pdf(
    body: SettlementRequest,
    current_user: dict = Depends(get_current_user),
):
    """Compute shares and generate the Inheritance Share Statement PDF."""
    calc = _calc(body)
    fields = {
        "deceased_name":      body.deceased_name,
        "date_of_death":      body.date_of_death,
        "estate_description": body.estate_description,
        "calculation":        calc,
    }
    doc = await document_service.generate_standalone(
        current_user["_id"], "inheritance_settlement", fields
    )
    return {"doc_id": doc["_id"], "title": doc["title"], "calculation": calc}


@router.post("/demand-letter", response_model=DemandLetterResult)
async def demand_letter(
    body: DemandRequest,
    current_user: dict = Depends(get_current_user),
):
    """Generate a demand notice for an heir whose share is being withheld."""
    doc = await document_service.generate_standalone(
        current_user["_id"], "inheritance_demand", body.model_dump()
    )
    return {"doc_id": doc["_id"], "title": doc["title"]}


# ── Wasiyyat (Islamic will) + estate waterfall ────────────────────────────────

class Bequest(BaseModel):
    beneficiary: str = ""
    relation: str = ""
    amount: int = Field(0, ge=0)
    is_heir: bool = False


class WasiyyatRequest(BaseModel):
    gross_estate: int = Field(..., gt=0)
    funeral_expenses: int = Field(0, ge=0)
    debts: int = Field(0, ge=0)
    bequests: list[Bequest] = []
    heirs: Heirs


class WasiyyatPdfRequest(WasiyyatRequest):
    testator_name: str = ""
    testator_father_name: str = ""
    testator_cnic: str = ""
    testator_address: str = ""
    executor_name: str = ""
    executor_relation: str = ""
    guardian_name: str = ""
    funeral_instructions: str = ""
    witness1_name: str = ""
    witness2_name: str = ""
    place: str = ""


def _wasiyyat(body: WasiyyatRequest) -> dict:
    heirs = body.heirs.model_dump()
    try:
        return wasiyyat_service.compute_estate(
            body.gross_estate, body.funeral_expenses, body.debts,
            [b.model_dump() for b in body.bequests], heirs,
        )
    except ValueError as exc:
        raise AppValidationError(str(exc))


@router.post("/wasiyyat", response_model=WasiyyatComputation)
async def wasiyyat(
    body: WasiyyatRequest,
    current_user: dict = Depends(get_current_user),
):
    """Estate waterfall: funeral + debts → bequests (capped at 1/3) → Faraid residue."""
    return _wasiyyat(body)


@router.post("/wasiyyat-pdf", response_model=WasiyyatPdfResult)
async def wasiyyat_pdf(
    body: WasiyyatPdfRequest,
    current_user: dict = Depends(get_current_user),
):
    """Compute the waterfall and generate a Wasiyyat Nama (Islamic will) PDF."""
    computation = _wasiyyat(body)
    fields = {
        **body.model_dump(exclude={"heirs", "bequests"}),
        "computation": computation,
    }
    doc = await document_service.generate_standalone(
        current_user["_id"], "wasiyyat_nama", fields
    )
    return {"doc_id": doc["_id"], "title": doc["title"], "computation": computation}
