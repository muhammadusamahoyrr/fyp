from datetime import datetime

from pydantic import BaseModel, ConfigDict


# Cause-list is public court data — nothing sensitive to strip. Models use
# extra="allow" so the many scraped entry fields (and any added later) pass
# through untouched. The route/service already rename `_id` → `id`.

class WatchOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    lawyer_id: str | None = None
    court: str | None = None
    case_no: str | None = None
    title_hint: str | None = None
    case_id: str | None = None
    active: bool | None = None
    last_checked_at: datetime | None = None
    last_listed_date: str | None = None   # ISO date string as the LHC list prints it
    created_at: datetime | None = None


class EntryOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    watch_id: str | None = None
    lawyer_id: str | None = None
    case_id: str | None = None
    hearing_date: str | None = None
    bench: str | None = None
    judge: str | None = None
    court_room: str | None = None
    seq: str | None = None
    connected: bool | None = None
    category: str | None = None
    case_no: str | None = None
    case_no_raw: str | None = None
    title: str | None = None
    lawyer: str | None = None
    remarks: str | None = None
    list_type: str | None = None
    source: str | None = None
    found_at: datetime | None = None


class CheckResult(BaseModel):
    checked: int
    new_entries: list[EntryOut] = []
    source_errors: int = 0


class MatchHit(BaseModel):
    case_no: str
    watch_id: str
    line: str


class DeleteResult(BaseModel):
    success: bool
