"""
scoring.py — Additive three-signal confidence scoring for retrieval chunks.

Weights (legal domain — statute exact match is highest priority):
  keyword   0.40
  embedding 0.35
  llm       0.25

All signals mapped to calibrated probability space before weighting.
Variance penalty applied when signals disagree above adaptive threshold.

The lexical signal used to be INVERTED
--------------------------------------
It matched the query against a fixed 30-word list of generic legal terms and
scored a chunk by the fraction of those terms it contained. Most questions
contain exactly one such term, so the signal collapsed to "does this chunk
mention that word", which nearly every chunk does — and it carried the heaviest
weight. Measured on this corpus:

    query                                    answerable   old lexical
    stamp duty rate in Gilgit-Baltistan          no          0.789
    pending LHC cases in 2019                    no          0.733
    grounds for khula                            yes         0.444
    share in Islamic inheritance                 yes         0.000

The two questions the corpus CANNOT answer scored highest, because "property"
appears in every Transfer of Property Act chunk and "court" appears in almost
every statute — while the words that actually decide answerability ("stamp
duty", "Gilgit-Baltistan", "2019") were invisible to the scorer. It got worse
as the corpus grew, since more chunks containing the generic word were
retrieved. Mean answerable minus mean unanswerable was -0.343: confidence was
anti-correlated with the system's ability to answer.

The signal now measures rarity-weighted coverage of the query's own distinctive
terms (see _term_weights), which restores the ordering to +0.090.
"""
from __future__ import annotations

import math
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


# Function words carry no retrieval signal. Kept deliberately small: this is a
# stoplist, not a substitute for the term weighting below, which is what
# actually suppresses uninformative words. "pakistan"/"pakistani" and "current"
# are here because every query in a Pakistani legal assistant contains them.
_STOPWORDS = frozenset("""
a an the is are was were be been being am of in on at to for from by with within
without what which who whom whose when where why how do does did doing done can
could shall should will would may might must and or but if then than as about
into over under after before between during my me i you your yours he she it we
they them his her its their this that these those any all some no not only also
there here more most other such own same so very just each both few own case
current pakistan pakistani law legal please tell explain
""".split())

# Words of three or more letters, any script. Digits are excluded: a bare year
# ("2019") is matched by the numeric branch below so it can be weighted as the
# distinguishing term it usually is.
_WORD_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
_NUM_RE  = re.compile(r"\b\d{2,}\b")

# Floor on a term's weight so that a word present in every candidate still
# counts for something rather than dropping out of the denominator entirely.
_MIN_TERM_WEIGHT = 0.05


def _query_terms(query_text: str) -> list[str]:
    """Distinctive content terms of the query, order-preserving and deduplicated."""
    words = [m.group(0).lower() for m in _WORD_RE.finditer(query_text)]
    words += [m.group(0) for m in _NUM_RE.finditer(query_text)]
    return list(dict.fromkeys(w for w in words if w not in _STOPWORDS))


def _term_weights(query_text: str, chunk_texts: list[str]) -> dict[str, float]:
    """Weight each query term by how much it discriminates within this candidate set.

    This is local IDF, computed over the retrieved pool rather than the whole
    corpus, and it is what fixes the inverted signal described in the module
    docstring:

      * a term in EVERY candidate ("property" among Transfer of Property Act
        chunks) tells us nothing about which chunk is better, so it is weighted
        near zero instead of saturating the score at 1.0;
      * a term in NO candidate ("stamp", "Gilgit") is an unmet requirement of
        the question. It gets the highest weight and can never be matched, so it
        holds the score down permanently — which is exactly the behaviour an
        unanswerable question should produce.

    Computing it over the pool rather than the corpus also means it adapts as
    the corpus grows, instead of degrading the way the fixed word list did.
    """
    terms = _query_terms(query_text)
    if not terms:
        return {}
    n = max(len(chunk_texts), 1)
    lowered = [c.lower() for c in chunk_texts]
    weights: dict[str, float] = {}
    for term in terms:
        df = sum(1 for c in lowered if term in c)
        weights[term] = max(math.log(1 + n / (1 + df)), _MIN_TERM_WEIGHT)
    return weights


def _keyword_score(
    query_text: str,
    chunk_text: str,
    term_weights: Optional[dict[str, float]] = None,
) -> float:
    """Share of the query's weighted distinctive terms present in this chunk.

    term_weights should come from _term_weights over the whole candidate set.
    When it is omitted the weights are derived from this chunk alone, which
    still measures query coverage but cannot tell a common term from a rare one.
    """
    if term_weights is None:
        term_weights = _term_weights(query_text, [chunk_text])
    if not term_weights:
        return 0.0
    chunk_lower = chunk_text.lower()
    matched = sum(w for term, w in term_weights.items() if term in chunk_lower)
    return min(matched / sum(term_weights.values()), 1.0)


def score_chunk_with_variance(
    query_text:      str,
    chunk_text:      str,
    embedding_score: float,
    llm_grade:       float,
    term_weights:    Optional[dict[str, float]] = None,
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
    kw  = _keyword_score(query_text, chunk_text, term_weights)
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

    texts = [chunk.get("content", "") for chunk in chunks]
    # One weighting for the whole batch: a term's discriminating power is a
    # property of the candidate set, not of an individual chunk.
    weights = _term_weights(query_text, texts)

    scored: list[tuple[float, dict]] = []
    variances: list[float] = []
    lexicals:  list[float] = []
    for chunk, text, emb, grade in zip(chunks, texts, emb_list, grade_list):
        s, var = score_chunk_with_variance(
            query_text=query_text,
            chunk_text=text,
            embedding_score=float(emb),
            llm_grade=float(grade),
            term_weights=weights,
        )
        scored.append((s, chunk))
        variances.append(var)
        lexicals.append(_keyword_score(query_text, text, weights))

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
