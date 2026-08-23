"""build_uqa_evalset.py — an evaluation set nobody on this project wrote.

The problem this addresses
--------------------------
Every evaluation query used so far was authored by the system's own developer,
and evaluate_retrieval.py falls back to a five-word content-overlap heuristic
when explicit chunk ids are absent — which labeling_service's own docstring
concedes "no reviewer will accept as ground truth".

LEGAL-UQA supplies both missing pieces: 619 question/answer pairs generated from
the Constitution of Pakistan, each shipped with the article text it was derived
from. The questions were authored without reference to this system, and the
context is an exact gold label, so no annotation is required.

The contamination that had to be fixed first
--------------------------------------------
Those same 619 pairs were indexed as retrievable chunks containing the question
verbatim, and tagged as the Constitution. Evaluating on them beforehand would
have retrieved each question's own answer at rank 1 and produced near-perfect
scores for entirely the wrong reason. They are now retagged synthetic and
excluded from retrieval; this script asserts that before writing anything.

How gold is resolved
--------------------
Each context's BODY text is matched, as verbatim word 8-grams, against the
AUTHENTICATED National Assembly text. Chunks containing a shingle become gold.

Matching on the body rather than the heading was forced by a bug worth
recording. LEGAL-UQA contexts open with the article heading, so the heading
looked like the natural join key — but the National Assembly PDF carries
marginal notes that OCR interleaves, producing heading-only stub chunks. The
heading "Equality of citizens" matched the stub "25A. Equality of citizens"
rather than the chunk holding Article 25's actual text. Every gold label came
out one chunk early, retrieval was returning the RIGHT chunk, and the evaluation
scored it as a miss: Hit@1 of exactly 0.000 across 568 questions, which is the
number that gave the bug away.

Gold candidates are therefore restricted to chunks with a real body (>= 200
characters). A heading stub cannot be the answer to anything, so it cannot be
gold. Verbatim 8-gram match rather than word overlap is also deliberate: an
exact span is checkable, whereas a five-word overlap threshold is a guess
dressed as ground truth.

Questions whose heading matches nothing, or suspiciously many chunks, are
DROPPED. A wrong gold label is worse than a smaller set.

Honest limits, which belong in the paper rather than a footnote:
  * the questions are GPT-4-generated, not practitioner-authored. This fixes
    independence from the authors, not expert authorship.
  * coverage is constitutional law only; civil, criminal and family still need
    the human annotation pipeline.
  * gold is one article, so this is closer to known-item retrieval than graded
    relevance, and nDCG over it degenerates towards MRR.

Usage
-----
  python scripts/build_uqa_evalset.py --out data/uqa_eval.json
  python scripts/evaluate_retrieval.py --dataset data/uqa_eval.json --k 1 3 5
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
from huggingface_hub import hf_hub_download  # noqa: E402

from app.db.chroma import connect_chroma, get_chroma  # noqa: E402

DATASET = "nlp-anonymous-researcher/LEGAL-UQA"
FILES = ("data/train-00000-of-00001.parquet",
         "data/validation-00000-of-00001.parquet")

COLLECTION = "constitutional_collection"
PRIMARY_PREFIX = "statutes_constitution_of_pakistan_1973_"

# Word length of the verbatim spans used to join. Eight words is long enough to
# be unique in a 400k-character document and short enough to survive the
# whitespace and line-break differences between the two renderings.
_SHINGLE_WORDS = 8
_SHINGLE_STRIDE = 4
_MAX_SHINGLES = 12

# A chunk shorter than this is a heading or a marginal note, not article text.
# Allowing them as gold is what produced the off-by-one described above.
_MIN_BODY_CHARS = 200

# A span matching more chunks than this is boilerplate, not an article.
_MAX_GOLD_CHUNKS = 12


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _shingles(context: str) -> list[str]:
    """Verbatim word n-grams from the article BODY, skipping the heading line.

    The heading is skipped deliberately — matching on it produced a systematic
    off-by-one against OCR'd marginal notes. See the module docstring.
    """
    lines = (context or "").split("\n")
    body = _norm(" ".join(lines[1:])) or _norm(context)
    words = body.split()
    if len(words) < _SHINGLE_WORDS:
        return []
    return [
        " ".join(words[i:i + _SHINGLE_WORDS])
        for i in range(0, len(words) - _SHINGLE_WORDS, _SHINGLE_STRIDE)
    ][:_MAX_SHINGLES]


def _load_rows() -> list[dict]:
    table = pa.concat_tables([
        pq.read_table(hf_hub_download(DATASET, f, repo_type="dataset"))
        for f in FILES
    ])
    cols = {c: table.column(c).to_pylist() for c in
            ("question_eng", "question_urdu", "context_eng", "context_index")}
    return [
        {k: cols[k][i] for k in cols}
        for i in range(table.num_rows)
    ]


def _assert_not_contaminated(col) -> None:
    from app.ai.nodes.retrieval_node import _is_synthetic

    got = col.get(include=["metadatas"], limit=5,
                  where={"law_type": {"$eq": "synthetic_qa"}})
    if not got.get("ids"):
        raise SystemExit(
            "the generated QA pairs are not tagged synthetic_qa — run "
            "scripts/retag_legal_uqa.py --apply first, or this evaluation set "
            "will score the system against its own answers"
        )
    for cid in got["ids"]:
        if not _is_synthetic({"chunk_id": cid}):
            raise SystemExit(
                f"{cid} is tagged synthetic but retrieval would not exclude it"
            )


def main(out: Path, limit: int) -> int:
    connect_chroma()
    col = get_chroma().get_collection(COLLECTION)
    _assert_not_contaminated(col)

    got = col.get(include=["documents", "metadatas"])
    primary = [
        (cid, _norm(doc), (meta or {}))
        for cid, doc, meta in zip(got["ids"], got["documents"], got["metadatas"])
        if cid.startswith(PRIMARY_PREFIX)
    ]
    if not primary:
        raise SystemExit(
            "no authenticated Constitution chunks found — run "
            "scripts/fetch_constitution.py --download then ingest_statutes.py"
        )
    print(f"\n  authenticated Constitution chunks : {len(primary)}")

    rows = _load_rows()
    print(f"  LEGAL-UQA questions               : {len(rows)}")

    body_bearing = [(cid, doc) for cid, doc, _ in primary
                    if len(doc) >= _MIN_BODY_CHARS]
    print(f"  of which body-bearing             : {len(body_bearing)}")

    items, no_shingle, no_match, too_many = [], 0, 0, 0
    for r in rows:
        spans = _shingles(r.get("context_eng") or "")
        if not spans:
            no_shingle += 1
            continue
        gold: list[str] = []
        for span in spans:
            gold = [cid for cid, doc in body_bearing if span in doc]
            if gold:
                break
        if not gold:
            no_match += 1
            continue
        if len(gold) > _MAX_GOLD_CHUNKS:
            too_many += 1
            continue

        question = (r.get("question_eng") or "").strip()
        if not question:
            continue
        items.append({
            "question":        question,
            "question_urdu":   (r.get("question_urdu") or "").strip(),
            "answer":          "",
            "case_type":       "constitutional",
            "province":        "federal",
            "relevant_chunks": sorted(gold),
            "gold_span":       spans[0],
            "source":          "LEGAL-UQA",
        })
        if limit and len(items) >= limit:
            break

    print(f"\n  resolved to gold chunks           : {len(items)}")
    print(f"  dropped, context too short        : {no_shingle}")
    print(f"  dropped, no span matched          : {no_match}")
    print(f"  dropped, span too common          : {too_many}")

    if not items:
        print("\n  Nothing resolvable — not writing a file.\n")
        return 1

    per_q = sum(len(i["relevant_chunks"]) for i in items) / len(items)
    with_urdu = sum(1 for i in items if i["question_urdu"])
    print(f"  mean gold chunks per question     : {per_q:.1f}")
    print(f"  questions with an Urdu parallel   : {with_urdu}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  wrote {len(items)} items -> {out}")
    print(f"\n  Next:\n    python scripts/evaluate_retrieval.py "
          f"--dataset {out} --k 1 3 5\n")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build the LEGAL-UQA evaluation set.")
    p.add_argument("--out", default="data/uqa_eval.json", type=Path)
    p.add_argument("--limit", type=int, default=0)
    a = p.parse_args()
    raise SystemExit(main(a.out, a.limit))
