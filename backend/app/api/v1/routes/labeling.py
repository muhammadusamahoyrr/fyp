"""HTTP surface for the retrieval-labelling pipeline.

`labeling_service` and `agreement` were complete — save_label, the annotator
queue, Krippendorff's alpha, adjudication, and both exports — and had no way to
be reached. There was no route, so no human could label anything, so
`export_retrieval_dataset()` returned ([], []) and every downstream measurement
that depends on it was blocked: evaluate_retrieval.py, the calibration fit, and
any honest comparison of the fine-tuned retriever against the deployed one.

This module adds the door and nothing else. Every endpoint is a thin call into
the existing service; no labelling logic lives here.

TWO THINGS ARE DELIBERATELY NOT ACCEPTED FROM THE CLIENT
--------------------------------------------------------
`labeler` is taken from the authenticated user, never from the request body.
The whole design keys labels on (request_id, labeler) so that a second
annotator's judgement sits alongside the first rather than overwriting it —
that pairing is what inter-annotator agreement is computed from. If a caller
could name themselves, one annotator could overwrite another's verdict, or
submit two labels under different names and manufacture agreement out of a
single opinion.

`is_baseline` is not exposed at all. It marks a MACHINE-authored label, and
agreement.py excludes those from agreement, adjudication, the authoritative set
and every export. A human able to set it could silently keep their own label out
of the evaluation set; a human able to clear it could promote a machine label
into one. It stays settable only from a script.

Admin-gated: this is annotation and research tooling, not a user feature, and
the labels it writes become published evaluation data.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.exceptions import AppValidationError
from app.dependencies import require_admin
from app.services import agreement as agreement_service
from app.services import labeling_service

router = APIRouter(prefix="/labeling", tags=["labeling"])


def _labeler_of(user: dict) -> str:
    """Stable annotator identity from the authenticated user.

    Falls back through email then id so the name is always non-empty —
    save_label rejects an unattributed label, and rightly so.
    """
    return str(user.get("email") or user.get("_id") or "").strip()


class LabelSubmission(BaseModel):
    """One annotator's judgement of one recorded turn."""

    request_id: str = Field(..., description="Provenance record being labelled.")
    chunk_labels: dict[str, bool] = Field(
        ...,
        description="chunk_id -> was this chunk relevant to the question. "
                    "Include every chunk you actually looked at.",
    )
    answer_verdict: str = Field(
        ...,
        description="One of: correct, incorrect, correct_refusal, wrong_refusal.",
    )
    labeled_depth: int = Field(
        0,
        ge=0,
        description="How far down the ranked list you looked. 0 means every "
                    "retrieved chunk. Chunks below this depth are treated as "
                    "UNJUDGED, not irrelevant.",
    )
    notes: str = Field("", max_length=2000)
    is_adjudication: bool = Field(
        False,
        description="Tie-breaking judgement that supersedes the annotators it "
                    "resolves.",
    )


@router.get("/queue")
async def labeling_queue(
    limit: int = Query(25, ge=1, le=200),
    include_all_turns: bool = Query(
        False,
        description="Include clarification and blocked turns, which are audited "
                    "but excluded from the evaluation set by default.",
    ),
    current_user: dict = Depends(require_admin),
):
    """Records this annotator has not yet labelled, oldest first.

    Scoped to the caller: unscoped, a second annotator is told there is nothing
    left the moment the first finishes, and no turn can ever be double-labelled.
    """
    return await labeling_service.unlabeled_records(
        limit=limit,
        include_all_turns=include_all_turns,
        labeler=_labeler_of(current_user),
    )


@router.post("/label")
async def submit_label(
    body: LabelSubmission,
    current_user: dict = Depends(require_admin),
):
    """Record one judgement. Re-submitting replaces this annotator's own verdict."""
    try:
        return await labeling_service.save_label(
            request_id=body.request_id,
            chunk_labels=body.chunk_labels,
            answer_verdict=body.answer_verdict,
            labeler=_labeler_of(current_user),
            notes=body.notes,
            labeled_depth=body.labeled_depth,
            is_adjudication=body.is_adjudication,
            # is_baseline is intentionally not settable over HTTP — see module
            # docstring.
        )
    except labeling_service.LabelError as exc:
        raise AppValidationError(str(exc)) from exc


@router.get("/stats")
async def labeling_stats(current_user: dict = Depends(require_admin)):
    """Coverage against LABELABLE turns, not every audited turn."""
    return await labeling_service.stats()


@router.get("/agreement")
async def labeling_agreement(current_user: dict = Depends(require_admin)):
    """Krippendorff's alpha over chunk relevance and answer verdicts.

    Reported rather than assumed: unmeasured agreement is the usual reason a
    legal-NLP evaluation set is not believed.
    """
    return await agreement_service.agreement_report()


@router.get("/disagreements")
async def labeling_disagreements(current_user: dict = Depends(require_admin)):
    """Turns where annotators disagree — the adjudication queue."""
    return await agreement_service.disagreements()


@router.get("/export/retrieval")
async def export_retrieval(current_user: dict = Depends(require_admin)):
    """The evaluation set, shaped for evaluate_retrieval.py.

    `unanswerable` is not an empty result — it is the abstention split, the
    cases where refusing was the correct behaviour.
    """
    answerable, unanswerable = await labeling_service.export_retrieval_dataset()
    return {
        "answerable": answerable,
        "unanswerable": unanswerable,
        "counts": {
            "answerable": len(answerable),
            "unanswerable": len(unanswerable),
        },
    }


@router.get("/export/calibration")
async def export_calibration(current_user: dict = Depends(require_admin)):
    """(confidence, was_correct) pairs for Platt / isotonic fitting."""
    pairs = await labeling_service.export_calibration_pairs()
    return {"pairs": pairs, "count": len(pairs)}
