from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JudgmentOut(BaseModel):
    """A judgment record (search / cited-by / get). The service `_public`
    already strips the full `text` (only a bounded `text_preview` is returned
    on the single-judgment view) and renames `_id` → `id`. Embeddings live in
    ChromaDB, never on this doc — nothing to strip here. extra="allow" so the
    scraped metadata (which varies per judgment) passes through untouched."""
    model_config = ConfigDict(extra="allow")

    id: str
    court: str | None = None
    year: int | None = None
    seq: int | None = None
    pdf_url: str | None = None
    case_no: str | None = None
    title: str | None = None
    judge: str | None = None
    hearing_date: str | None = None
    tag_line: str | None = None
    uploaded_date: str | None = None
    citations_out: list[str] = []
    text_chars: int | None = None
    ingested_at: datetime | None = None
    # Endpoint-specific extras:
    score: float | None = None        # search: semantic score
    snippet: str | None = None        # search: matched chunk
    text_preview: str | None = None   # get_judgment: first 3000 chars


class CitedByResult(BaseModel):
    citation: str
    cited_by: list[JudgmentOut] = []
    count: int


class CorpusStats(BaseModel):
    judgments: int
    with_citations: int
    citation_edges: int
