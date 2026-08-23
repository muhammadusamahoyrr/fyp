"""build_citation_trainset.py — turn cited QA pairs into verified retrieval labels.

Source: abdullah693/adaption-pakistan-law-qa-pairs, 11,195 rows carrying a
machine-parseable citation ("PPC s.467", "CONST art.203F") and a domain label.
It is the only Pakistani legal dataset found that supplies retrieval SUPERVISION
for criminal, evidence and civil procedure, which currently have none.

The rows are `synthetic_grounded` — LLM-written against statute. That is
acceptable as a training signal, because the citation is the label and a label
can be checked. It is NOT acceptable as corpus, and nothing here is ever
indexed: this project's constitutional collection was 67% generated Q&A tagged
as the Constitution, and undoing that was most of a day's work.

Four filters, in order
----------------------
1. DROP seed_legaluqa rows. They derive from the same LEGAL-UQA that produced
   the only held-out evaluation set this project has. Training on them would
   contaminate the benchmark every other number rests on.
2. RESOLVE the citation to indexed chunks. A citation naming a section that is
   not in the corpus cannot be a training label, whatever else is true of it.
3. VALIDATE that the cited section is actually on the answer's topic. LLM-
   generated citations are wrong sometimes, and a confidently wrong citation
   trains the retriever to make the same mistake.
4. DEDUPLICATE by question.

On the validation method, and a trap avoided
--------------------------------------------
The obvious check is embedding similarity between the answer and the cited
chunk. It is also circular: scoring with the base model and keeping what it
already agrees with would discard precisely the hard examples that have
something to teach, and would flatter the fine-tune that follows.

So validation is LEXICAL and model-independent — rarity-weighted overlap between
the cited section's text and the answer, reusing app.ai.scoring, whose behaviour
is already understood and tested. A section about forgery should share
distinctive vocabulary with an answer about forgery; one about bail should not.

Usage
-----
  python scripts/build_citation_trainset.py --report-only
  python scripts/build_citation_trainset.py --out data/citation_train
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.ai.scoring import _keyword_score, _term_weights  # noqa: E402
from app.db.chroma import connect_chroma, get_chroma  # noqa: E402

REPO = "abdullah693/adaption-pakistan-law-qa-pairs"
DATA_FILE = "data/train_0.jsonl"

COLLECTIONS = ("criminal_collection", "civil_collection",
               "family_collection", "constitutional_collection")

# Citation act codes -> the statute names this corpus actually uses.
ACT_MAP = {
    "PPC": "PPC 1860",
    "CRPC": "CrPC 1898",
    "CPC": "CPC 1908",
    "CONST": "Constitution of Pakistan 1973",
    "CONSTITUTION": "Constitution of Pakistan 1973",
    "QSO": "Qanun-e-Shahadat Order 1984",
    "MFLO": "Muslim Family Laws Ordinance 1961",
    "FCA": "Family Courts Act 1964",
    "DMMA": "Dissolution of Muslim Marriages Act 1939",
    "GWA": "Guardians and Wards Act 1890",
}

_CITE = re.compile(r"^\s*([A-Za-z.\-]+)\s*(?:s\.|art\.|section|article)\s*([0-9]+[A-Z]*)",
                   re.IGNORECASE)

# A chunk shorter than this is a heading stub, not law. Using one as a training
# positive teaches the model to retrieve headings.
MIN_BODY = 200

# Rarity-weighted overlap the cited section must share with the answer.
VALIDATION_FLOOR = 0.12

# Urdu script. 2,296 of 6,806 cited rows are Urdu question AND Urdu answer,
# while the statutes are in English — so scoring an Urdu answer against English
# statute text yields near-zero overlap for reasons that have nothing to do with
# whether the citation is right. A first pass rejected correct citations on
# exactly this basis: an Urdu question about a gang killing during a dacoity,
# cited to PPC s.396 "Dacoity with murder", scored 0.016.
#
# Those rows carry an English `reasoning`/`completion` field, so validation uses
# that instead. The QUERY stays in Urdu — a code-switched query against English
# statute is precisely the retrieval case this system exists to serve, and these
# are the most valuable rows in the dataset rather than the most disposable.
_URDU = re.compile(r"[؀-ۿ]")


def _validation_text(row: dict, answer: str) -> tuple[str, str]:
    """English text to validate the citation against, and which field it came from."""
    if answer and not _URDU.search(answer):
        return answer, "answer"
    for field in ("reasoning", "completion", "enhanced_completion"):
        v = (row.get(field) or "").strip()
        if v and not _URDU.search(v):
            return v, field
    return "", "none"


def _parse_citation(raw) -> tuple[str, str] | None:
    m = _CITE.match(str(raw or ""))
    if not m:
        return None
    act = ACT_MAP.get(m.group(1).upper().replace(".", "").replace("-", ""))
    return (act, m.group(2).upper()) if act else None


def _load_rows():
    from huggingface_hub import hf_hub_download
    p = hf_hub_download(REPO, DATA_FILE, repo_type="dataset")
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def _corpus_index():
    connect_chroma()
    c = get_chroma()
    index: dict[tuple[str, str], list[tuple[str, str]]] = collections.defaultdict(list)
    for coll in COLLECTIONS:
        try:
            g = c.get_collection(coll).get(include=["documents", "metadatas"])
        except Exception:
            continue
        for cid, doc, meta in zip(g["ids"], g["documents"], g["metadatas"]):
            meta = meta or {}
            sec = str(meta.get("section_number") or "").strip().upper()
            statute = meta.get("statute", "")
            if sec and statute and len(doc or "") >= MIN_BODY:
                index[(statute, sec)].append((cid, doc))
    return dict(index)


def main(a) -> int:
    rows = _load_rows()
    index = _corpus_index()
    print(f"\n  source rows        : {len(rows)}")
    print(f"  indexed (statute, section) keys with a body: {len(index)}")

    stats = collections.Counter()
    unmapped_acts = collections.Counter()
    per_domain = collections.defaultdict(collections.Counter)
    scores = []
    kept, rejected_examples = [], []
    script_used = collections.Counter()
    seen_q = set()

    for r in rows:
        domain = r.get("domain") or "unknown"
        per_domain[domain]["input"] += 1

        # 1. seed_legaluqa — benchmark contamination
        if r.get("generation") == "seed_legaluqa":
            stats["dropped_seed_legaluqa"] += 1
            per_domain[domain]["seed"] += 1
            continue

        question = (r.get("prompt") or r.get("enhanced_prompt") or "").strip()
        answer = (r.get("answer") or r.get("completion") or "").strip()
        if not question or not answer:
            stats["dropped_no_text"] += 1
            continue

        cits = r.get("citation")
        cits = cits if isinstance(cits, list) else ([cits] if cits else [])
        if not cits:
            stats["dropped_no_citation"] += 1
            per_domain[domain]["no_citation"] += 1
            continue

        # 2. resolve
        resolved = []
        for c in cits:
            parsed = _parse_citation(c)
            if parsed is None:
                head = re.match(r"^\s*([A-Za-z.\-]+)", str(c or ""))
                if head:
                    unmapped_acts[head.group(1).upper()] += 1
                continue
            hits = index.get(parsed)
            if hits:
                resolved.extend(hits)
        if not resolved:
            stats["dropped_unresolved"] += 1
            per_domain[domain]["unresolved"] += 1
            continue

        # 3. validate — does the cited section share distinctive vocabulary
        #    with the answer? Lexical on purpose; see the module docstring.
        vtext, vfield = _validation_text(r, answer)
        if not vtext:
            stats["dropped_no_english_to_validate"] += 1
            per_domain[domain]["no_english"] += 1
            continue
        script_used[vfield] += 1

        texts = [d for _, d in resolved]
        weights = _term_weights(vtext, texts)
        best_id, best_doc, best = None, None, -1.0
        for cid, doc in resolved:
            sc = _keyword_score(vtext, doc, weights)
            if sc > best:
                best_id, best_doc, best = cid, doc, sc
        scores.append(best)

        if best < VALIDATION_FLOOR:
            stats["dropped_failed_validation"] += 1
            per_domain[domain]["failed_validation"] += 1
            if len(rejected_examples) < 6:
                rejected_examples.append((round(best, 3), question[:70],
                                          cits[0] if cits else "", (best_doc or "")[:80]))
            continue

        # 4. deduplicate
        key = question.lower()
        if key in seen_q:
            stats["dropped_duplicate"] += 1
            continue
        seen_q.add(key)

        kept.append({"query": question, "positive": best_doc,
                     "positive_id": best_id, "domain": domain,
                     "citation": str(cits[0]), "validation": round(best, 4),
                     # Recorded so a later reader can tell a code-switched pair
                     # from an English one, and can see which field the citation
                     # was actually checked against.
                     "urdu_query": bool(_URDU.search(question)),
                     "validated_on": vfield})
        per_domain[domain]["kept"] += 1
        stats["kept"] += 1

    # ── quality report ──────────────────────────────────────────────────────
    print("\n  " + "=" * 66)
    print("  DATASET QUALITY REPORT")
    print("  " + "=" * 66)
    order = ["dropped_seed_legaluqa", "dropped_no_text", "dropped_no_citation",
             "dropped_unresolved", "dropped_no_english_to_validate",
             "dropped_failed_validation", "dropped_duplicate", "kept"]
    for k in order:
        pct = 100 * stats[k] / max(len(rows), 1)
        print(f"    {k:<28} {stats[k]:>6}  ({pct:>4.1f}%)")

    if scores:
        qs = statistics.quantiles(scores, n=10)
        print(f"\n    validation score deciles: "
              f"p10={qs[0]:.3f} p50={statistics.median(scores):.3f} p90={qs[-1]:.3f}")
        print(f"    floor in use: {VALIDATION_FLOOR}  "
              f"(rejects {100*sum(1 for s in scores if s < VALIDATION_FLOOR)/len(scores):.0f}% "
              f"of resolved rows)")

    print("\n    per domain:")
    print(f"      {'domain':<18}{'input':>8}{'seed':>7}{'unres':>7}"
          f"{'failed':>8}{'KEPT':>8}")
    for d, c in sorted(per_domain.items(), key=lambda x: -x[1]["kept"]):
        print(f"      {str(d):<18}{c['input']:>8}{c['seed']:>7}{c['unresolved']:>7}"
              f"{c['failed_validation']:>8}{c['kept']:>8}")

    if unmapped_acts:
        print("\n    citation prefixes with no corpus mapping (top 8):")
        for actcode, n in unmapped_acts.most_common(8):
            print(f"      {actcode:<16} {n}")

    if rejected_examples:
        print("\n    rejected by validation (score, question, citation, cited text):")
        for sc, q, c, doc in rejected_examples:
            print(f"      [{sc}] {q}")
            print(f"            cited {c!r} -> {doc!r}")

    if a.report_only:
        print("\n  report only — nothing written.\n")
        return 0

    if not kept:
        print("\n  nothing survived the filters — not writing.\n")
        return 1

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "verified_pairs.json").write_text(
        json.dumps(kept, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "quality_report.json").write_text(json.dumps({
        "source": REPO, "source_rows": len(rows),
        "filters": dict(stats),
        "per_domain": {d: dict(c) for d, c in per_domain.items()},
        "validation_floor": VALIDATION_FLOOR,
        "validation_median": round(statistics.median(scores), 4) if scores else None,
        "unmapped_citation_prefixes": dict(unmapped_acts.most_common(20)),
    }, indent=2), encoding="utf-8")
    print(f"\n  wrote {len(kept)} verified pairs -> {out}\n")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build a verified citation training set.")
    p.add_argument("--out", default="data/citation_train")
    p.add_argument("--report-only", action="store_true")
    raise SystemExit(main(p.parse_args()))
