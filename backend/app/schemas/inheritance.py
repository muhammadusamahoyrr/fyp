from typing import Any

from pydantic import BaseModel, ConfigDict


# The Faraid / estate computations are wide, nested, dynamically-structured
# dicts (per-heir `breakdown`, `faraid`, `residue`, totals, notes, warnings).
# Per the audit method, wide computed shapes stay `dict`/pass-through rather
# than a strict nested model that could silently drop a computed sub-field.
# Nothing sensitive is returned — CNIC/testator details are inputs that go
# only into the generated PDF, never echoed back in these JSON responses.

class InheritanceCalculation(BaseModel):
    """Raw Faraid computation (POST /calculate). extra="allow" so the whole
    computed structure passes through untouched; only safe echoed inputs are
    declared (computed numbers pass through unchanged, no int→float coercion)."""
    model_config = ConfigDict(extra="allow")

    estate_value: int | None = None
    school: str | None = None
    disclaimer: str | None = None


class WasiyyatComputation(BaseModel):
    """Raw estate-waterfall computation (POST /wasiyyat)."""
    model_config = ConfigDict(extra="allow")

    gross_estate: int | None = None
    funeral_expenses: int | None = None
    debts: int | None = None
    disclaimer: str | None = None


class SettlementPdfResult(BaseModel):
    doc_id: str
    title: str
    calculation: dict[str, Any]   # wide Faraid computation — kept as dict


class DemandLetterResult(BaseModel):
    doc_id: str
    title: str


class WasiyyatPdfResult(BaseModel):
    doc_id: str
    title: str
    computation: dict[str, Any]   # wide estate waterfall — kept as dict
