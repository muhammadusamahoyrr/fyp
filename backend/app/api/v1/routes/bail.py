from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies import get_current_user
from app.services import bail_checker

router = APIRouter(prefix="/bail", tags=["bail"])


class BailCheckRequest(BaseModel):
    law: str = "PPC"
    section: str = Field(..., min_length=1)
    arrested: bool = True


# Public legal-reference data — nothing sensitive. extra="allow" so the offence
# reference fields pass through; nested offence/guidance kept as dict.

class OffenceItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    law: str | None = None
    section: str | None = None
    title: str | None = None
    punishment: str | None = None
    cognizable: bool | None = None
    bailable: bool | None = None
    compoundable: bool | None = None
    court: str | None = None
    confidence: str | None = None


class BailSearchResult(BaseModel):
    query: str
    results: list[OffenceItem] = []


class BailCheckResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    found: bool
    offence: dict | None = None       # matched offence reference (nested)
    guidance: dict | None = None      # summary / sections / steps
    legal_basis: str | None = None
    disclaimer: str | None = None
    confidence: str | None = None


@router.get("/search", response_model=BailSearchResult)
async def search(q: str = "", limit: int = 12, current_user: dict = Depends(get_current_user)):
    """Free-text / section lookup over the common-offence bail reference list."""
    return {"query": q, "results": bail_checker.search(q, limit)}


@router.post("/check", response_model=BailCheckResult)
async def check(body: BailCheckRequest, current_user: dict = Depends(get_current_user)):
    """Bailable/non-bailable classification + pre/post-arrest bail guidance for an offence."""
    return bail_checker.check(body.law, body.section, body.arrested)
