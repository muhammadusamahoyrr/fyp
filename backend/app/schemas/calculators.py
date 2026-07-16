from typing import Any

from pydantic import BaseModel, ConfigDict


# Stateless legal-fee/dues computations — wide computed dicts (nested
# `computation` / `breakdown`, assumptions, legal_basis). Per the audit method,
# these stay pass-through (extra="allow") rather than a strict nested model that
# could drop a computed sub-field. Only safe echoed inputs are declared, so the
# computed numbers pass through unchanged (no int→float coercion). Worker /
# employer details are inputs that go only into the generated PDF — never echoed.

class CourtFeeResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    claim_value: int | None = None
    suit_type: str | None = None
    province: str | None = None
    court_level: str | None = None
    disclaimer: str | None = None


class LabourDuesResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    monthly_wage: int | None = None
    completed_years: int | None = None
    disclaimer: str | None = None


class LabourDemandPdfResult(BaseModel):
    doc_id: str
    title: str
    calculation: dict[str, Any]   # wide labour-dues computation — kept as dict
