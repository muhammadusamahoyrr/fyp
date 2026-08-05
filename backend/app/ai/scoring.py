"""
scoring.py — Additive three-signal confidence scoring for retrieval chunks.

Weights (legal domain — statute exact match is highest priority):
  keyword   0.40
  embedding 0.35
  llm       0.25

All signals mapped to calibrated probability space before weighting.
Variance penalty applied when signals disagree above adaptive threshold.
"""
from __future__ import annotations

import re
from typing import NamedTuple, Optional

from app.ai.calibration import calibrate_embedding, calibrate_llm
from app.ai.threshold_manager import get_disagreement_max


class RetrievalSignals(NamedTuple):
    """The three numbers the Decision Engine arbitrates over."""
    aggregate: float   # weighted three-signal confidence → relevance_score
    variance:  float   # mean inter-signal disagreement  → signal_variance
    lexical:   float   # mean keyword agreement          → bm25_confidence

# ── Legal term set (alias-normalised; Urdu script included) ──────────────────
_LEGAL_RE = re.compile(
    r'\b(PPC|CrPC|MFLO|QSO|PECA|CPC|FIR|Section|Act|Ordinance|Article|'
    r'criminal|civil|family|murder|theft|fraud|assault|divorce|custody|'
    r'property|contract|bail|arrest|court|lawyer|petition|writ|'
    r'قتل|فراڈ|طلاق|حراست|ملکیت|ضمانت|گرفتاری|عدالت|دفعہ)\b',
    re.IGNORECASE,
)

# Minimum chunks to return even if all score below threshold
_MIN_CHUNKS_RETURNED = 3
# Default keep threshold
_DEFAULT_KEEP_THRESHOLD = 0.30


def _keyword_score(query_text: str, chunk_text: str) -> float:
    """
    Fraction of legal terms from query that appear in the chunk.
    Returns 0.0 when query has no recognisable legal terms.
    """
    query_terms = set(m.lower() for m in _LEGAL_RE.findall(query_text))
    if not query_terms:
        return 0.0
    chunk_lower = chunk_text.lower()
    matched = sum(1 for t in query_terms if t in chunk_lower)
    return min(matched / len(query_terms), 1.0)


def score_chunk_with_variance(
    query_text:      str,
    chunk_text:      str,
    embedding_score: float,
    llm_grade:       float,
) -> tuple[float, float]:
    """
    Weighted additive confidence score for one chunk → ([0, 1], variance).

    Applies variance penalty when the three calibrated signals disagree
    beyond the adaptive disagreement threshold.

    The raw variance is returned alongside the score because the Decision
    Engine needs it: high inter-signal disagreement is what distinguishes
    "defer for more information" from "answer" at the same confidence level.
    Collapsing it into the score alone would throw that signal away.
    """
    kw  = _keyword_score(query_text, chunk_text)
    emb = calibrate_embedding(embedding_score)
    llm = calibrate_llm(llm_grade)

    weighted = 0.40 * kw + 0.35 * emb + 0.25 * llm

    # Variance penalty
    mean = (kw + emb + llm) / 3.0
    var  = ((kw - mean) ** 2 + (emb - mean) ** 2 + (llm - mean) ** 2) / 3.0

    if var > get_disagreement_max():
        weighted = max(0.0, weighted - var)

    return round(min(weighted, 1.0), 4), round(var, 4)


def score_chunk(
    query_text:      str,
    chunk_text:      str,
    embedding_score: float,
    llm_grade:       float,
) -> float:
    """Weighted additive confidence score for one chunk → [0, 1]."""
    score, _ = score_chunk_with_variance(
        query_text, chunk_text, embedding_score, llm_grade
    )
    return score


def score_retrieval_batch(
    query_text:       str,
    chunks:           list[dict],
    embedding_scores: Optional[list[float]] = None,
    llm_grades:       Optional[list[int]]   = None,
    keep_threshold:   float                 = _DEFAULT_KEEP_THRESHOLD,
) -> tuple[list[dict], RetrievalSignals]:
    """
    Score all chunks and filter to those above keep_threshold.

    embedding_scores and llm_grades may be shorter than chunks — they are
    padded with neutral values (0.5 and 1) to avoid silent truncation.

    Returns:
      (kept_chunks, RetrievalSignals)

    aggregate = sum(chunk_scores) / max(total_chunks, 1)
    Guarantees at least _MIN_CHUNKS_RETURNED chunks are returned.
    """
    n = len(chunks)
    if n == 0:
        return [], RetrievalSignals(aggregate=0.0, variance=0.0, lexical=0.0)

    # Pad / truncate to match chunk count — never silently drop
    emb_pad   = (embedding_scores or []) + [0.5] * n
    grade_pad = (llm_grades       or []) + [1]   * n
    emb_list   = emb_pad[:n]
    grade_list = grade_pad[:n]

    scored: list[tuple[float, dict]] = []
    variances: list[float] = []
    lexicals:  list[float] = []
    for chunk, emb, grade in zip(chunks, emb_list, grade_list):
        text = chunk.get("content", "")
        s, var = score_chunk_with_variance(
            query_text=query_text,
            chunk_text=text,
            embedding_score=float(emb),
            llm_grade=float(grade),
        )
        scored.append((s, chunk))
        variances.append(var)
        lexicals.append(_keyword_score(query_text, text))

    kept = [ch for s, ch in scored if s >= keep_threshold]

    # Guarantee minimum return — fall back to top-N by score
    if len(kept) < _MIN_CHUNKS_RETURNED:
        scored.sort(key=lambda x: x[0], reverse=True)
        kept = [ch for _, ch in scored[:_MIN_CHUNKS_RETURNED]]

    total_score = sum(s for s, _ in scored)
    aggregate   = round(min(total_score / max(n, 1), 1.0), 4)

    signals = RetrievalSignals(
        aggregate=aggregate,
        # Mean disagreement across chunks — the Decision Engine defers when the
        # three signals disagree, regardless of how high the mean score is.
        variance=round(sum(variances) / max(len(variances), 1), 4),
        # Lexical (keyword) agreement, used as the BM25-only fallback evidence
        # when the LLM grader is unavailable or returns nothing.
        lexical=round(sum(lexicals) / max(len(lexicals), 1), 4),
    )
    return kept, signals
