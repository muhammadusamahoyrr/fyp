from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.dependencies import get_current_user
from app.schemas.calculators import (
    CourtFeeResult,
    LabourDemandPdfResult,
    LabourDuesResult,
)
from app.services import court_fee as court_fee_service
from app.services import document_service
from app.services import labour_dues as labour_dues_service

router = APIRouter(prefix="/calculators", tags=["calculators"])

# Constrained, not free-form `str`. These were plain strings, so the endpoint
# happily accepted suit_type="not_a_real_suit" and returned a 200 with a fee —
# the engine fell back to a default fixed fee and noted the assumption, but an API
# that answers a question nobody asked is a validation hole, not a feature. The
# same Literals are used by the LLM tool layer, so both entry points now reject
# the same inputs.
SuitType = Literal[
    "money_recovery", "specific_performance", "declaration_with_consequential",
    "declaration_simple", "injunction", "family", "rent", "appeal", "writ",
]
Province = Literal["punjab", "sindh", "kp", "balochistan", "islamabad"]
CourtLevel = Literal["district", "high"]


class CourtFeeRequest(BaseModel):
    claim_value: int = Field(0, ge=0)
    suit_type: SuitType = "money_recovery"
    province: Province = "punjab"
    court_level: CourtLevel = "district"


class LabourDuesRequest(BaseModel):
    monthly_wage: int = Field(..., gt=0)
    years_of_service: int = Field(0, ge=0)
    extra_months: int = Field(0, ge=0, le=11)
    unpaid_months: float = Field(0, ge=0)
    overtime_hours: float = Field(0, ge=0)
    terminated_without_notice: bool = False
    notice_months: int = Field(1, ge=1, le=6)


class LabourDemandRequest(LabourDuesRequest):
    worker_name: str = ""
    worker_address: str = ""
    employer_name: str = ""
    employer_address: str = ""
    designation: str = ""
    employment_period: str = ""
    response_days: int = 15


@router.post("/court-fee", response_model=CourtFeeResult)
async def court_fee(body: CourtFeeRequest, current_user: dict = Depends(get_current_user)):
    """Estimate the court fee for a suit (Court Fees Act 1870 + provincial amendments)."""
    return court_fee_service.calculate(body.claim_value, body.suit_type, body.province, body.court_level)


@router.post("/labour-dues", response_model=LabourDuesResult)
async def labour_dues(body: LabourDuesRequest, current_user: dict = Depends(get_current_user)):
    """Compute gratuity, unpaid wages, overtime and notice pay owed to a worker."""
    return labour_dues_service.calculate(
        body.monthly_wage, body.years_of_service, body.extra_months, body.unpaid_months,
        body.overtime_hours, body.terminated_without_notice, body.notice_months,
    )


@router.post("/labour-demand-pdf", response_model=LabourDemandPdfResult)
async def labour_demand_pdf(body: LabourDemandRequest, current_user: dict = Depends(get_current_user)):
    """Compute the dues and generate a demand notice to the employer."""
    calc = labour_dues_service.calculate(
        body.monthly_wage, body.years_of_service, body.extra_months, body.unpaid_months,
        body.overtime_hours, body.terminated_without_notice, body.notice_months,
    )
    fields = {
        "worker_name": body.worker_name, "worker_address": body.worker_address,
        "employer_name": body.employer_name, "employer_address": body.employer_address,
        "designation": body.designation, "employment_period": body.employment_period,
        "response_days": body.response_days, "calculation": calc,
    }
    doc = await document_service.generate_standalone(current_user["_id"], "labour_demand", fields)
    return {"doc_id": doc["_id"], "title": doc["title"], "calculation": calc}
