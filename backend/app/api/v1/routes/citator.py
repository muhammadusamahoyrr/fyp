from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_user
from app.schemas.citator import CitedByResult, CorpusStats, JudgmentOut
from app.services import citator_service

router = APIRouter(prefix="/citator", tags=["citator"])


@router.get("/search", response_model=list[JudgmentOut])
async def search_judgments(
    q: str = Query(..., min_length=3, max_length=500),
    n: int = Query(default=8, ge=1, le=20),
    current_user: dict = Depends(get_current_user),
):
    """Semantic search over the judgment corpus."""
    return await citator_service.search(q, n)


@router.get("/cited-by", response_model=CitedByResult)
async def cited_by(
    cite: str = Query(..., min_length=5, max_length=60),
    current_user: dict = Depends(get_current_user),
):
    """Judgments in the corpus citing the given reporter citation
    (e.g. `1996 SCMR 1544`, `PLD 2019 SC 675`)."""
    return await citator_service.cited_by(cite)


@router.get("/stats", response_model=CorpusStats)
async def stats(current_user: dict = Depends(get_current_user)):
    return await citator_service.corpus_stats()


@router.get("/judgment/{neutral_id}", response_model=JudgmentOut)
async def judgment(neutral_id: str, current_user: dict = Depends(get_current_user)):
    return await citator_service.get_judgment(neutral_id)
