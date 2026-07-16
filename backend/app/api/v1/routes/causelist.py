from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.dependencies import require_lawyer
from app.schemas.causelist import (
    CheckResult,
    DeleteResult,
    EntryOut,
    MatchHit,
    WatchOut,
)
from app.services import causelist_service

router = APIRouter(prefix="/causelist", tags=["causelist"])


class WatchCreate(BaseModel):
    case_no: str = Field(..., min_length=3, max_length=40)
    title_hint: str | None = Field(default=None, max_length=200)
    case_id: str | None = None
    court: str = "lhc"


class PasteMatch(BaseModel):
    text: str = Field(..., min_length=1, max_length=200_000)


@router.post("/watches", response_model=WatchOut)
async def create_watch(body: WatchCreate, current_user: dict = Depends(require_lawyer)):
    """Watch a court case number — we check the cause list for it daily."""
    watch = await causelist_service.create_watch(
        lawyer_id=current_user["_id"],
        case_no=body.case_no,
        title_hint=body.title_hint,
        case_id=body.case_id,
        court=body.court,
    )
    watch = dict(watch)
    watch["id"] = watch.pop("_id")
    return watch


@router.get("/watches", response_model=list[WatchOut])
async def list_watches(current_user: dict = Depends(require_lawyer)):
    out = []
    for w in await causelist_service.list_watches(current_user["_id"]):
        w = dict(w)
        w["id"] = w.pop("_id")
        out.append(w)
    return out


@router.delete("/watches/{watch_id}", response_model=DeleteResult)
async def delete_watch(watch_id: str, current_user: dict = Depends(require_lawyer)):
    return await causelist_service.delete_watch(watch_id, current_user["_id"])


@router.post("/check", response_model=CheckResult)
async def check_now(current_user: dict = Depends(require_lawyer)):
    """Query the court's cause list for all my watches right now."""
    result = await causelist_service.check_lawyer_watches(current_user["_id"])
    for e in result["new_entries"]:
        e["id"] = e.pop("_id")
    return result


@router.get("/entries", response_model=list[EntryOut])
async def list_entries(
    upcoming: bool = True,
    current_user: dict = Depends(require_lawyer),
):
    """My matched cause-list entries (upcoming hearings first)."""
    return await causelist_service.list_entries(current_user["_id"], upcoming_only=upcoming)


@router.post("/match-text", response_model=list[MatchHit])
async def match_text(body: PasteMatch, current_user: dict = Depends(require_lawyer)):
    """Paste any cause list (district courts etc.) — find my watched cases in it."""
    return await causelist_service.match_pasted_list(current_user["_id"], body.text)
