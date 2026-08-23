"""baseline_label.py — a machine-authored reference pass over the label pool.

Usage
-----
  # Write the pending turns out for judging (oldest first, top-5 pooled)
  python scripts/baseline_label.py --dump batch1.json --limit 25 --top-k 5

  # Record the judgements
  python scripts/baseline_label.py --apply batch1_judged.json

  # Compare the baseline against the human labels, once humans exist
  python scripts/baseline_label.py --compare

What this is NOT
----------------
It is not the evaluation set and it cannot become one. Every label written here
carries is_baseline=True, which excludes it from inter-annotator agreement, from
adjudication, from the authoritative set, and therefore from both exports, the
calibration fit and the conformal threshold. See _HUMAN_ONLY in agreement.py.

ANNOTATION_PROTOCOL.md section 2 requires an annotator who did not build the
system; a judgement authored by the system under evaluation fails that on its
face. What a baseline is good for is narrower and still worth having: it
exercises the whole labelling path before two people spend seventeen hours on
it, it gives a machine-versus-human comparison to report, and it surfaces turns
where the retrieved law is obviously off before an annotator meets them.

The dump is deliberately a file rather than an interactive prompt. Judging is
the slow part, it wants the statute text in front of you, and a file can be
re-read, diffed and re-applied without touching the database twice.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.db.chroma import connect_chroma  # noqa: E402
from app.db.mongodb import close_db, connect_db  # noqa: E402
from app.services import labeling_service as ls  # noqa: E402

# Reuse the human tool's chunk-text lookup and preview width rather than
# reimplementing them: if the two drifted, the baseline would be judging
# different text than the annotators see, and the comparison would be void.
from scripts.label_provenance import (  # noqa: E402
    _PREVIEW_CHARS,
    _chunk_texts,
)

DEFAULT_LABELER = "claude-baseline"


# ── Dump ─────────────────────────────────────────────────────────────────────

async def cmd_dump(path: Path, limit: int, top_k: int, labeler: str) -> None:
    records = await ls.unlabeled_records(limit=limit, labeler=labeler)
    if not records:
        print(f"\n  Nothing left for {labeler!r} to judge.\n")
        return

    out = []
    unjudgeable: list[str] = []
    for prov in records:
        chunks = prov.get("statute_chunks") or []
        pooled = chunks[:top_k] if top_k else chunks
        texts  = _chunk_texts(
            prov.get("case_type", ""), [c["chunk_id"] for c in pooled]
        )

        # Chunks whose text no longer resolves are unjudgeable — the corpus was
        # re-ingested after these turns were recorded and chunk ids changed
        # scheme. A record where nothing resolves is dropped from the batch
        # rather than dumped with blank bodies; judging blind would manufacture
        # irrelevance judgements. Records that retrieved NOTHING are kept: they
        # carry a verdict (the abstention split) and have no chunks to judge.
        if pooled and not any(texts.get(c["chunk_id"]) for c in pooled):
            unjudgeable.append(prov.get("request_id", ""))
            continue

        arb = prov.get("arbitration", {}) or {}
        sig = prov.get("signals", {}) or {}
        out.append({
            "request_id":     prov.get("request_id", ""),
            "question":       prov.get("query", ""),
            "case_type":      prov.get("case_type", ""),
            "province":       prov.get("province", ""),
            "system_verdict": arb.get("output", ""),
            "system_source":  arb.get("source", ""),
            "confidence":     round(float(arb.get("confidence", 0) or 0), 3),
            "signals": {
                "relevance": round(float(sig.get("relevance_score", 0) or 0), 3),
                "variance":  round(float(sig.get("signal_variance", 0) or 0), 3),
                "lexical":   round(float(sig.get("bm25_confidence", 0) or 0), 3),
            },
            "answer_preview": prov.get("answer_preview", ""),
            "retrieved_total": len(chunks),
            "pooled_depth":    len(pooled),
            "unresolved_in_pool": sum(
                1 for c in pooled if not texts.get(c["chunk_id"])
            ),
            # Only chunks whose text resolves. An unresolved rank is missing
            # data; --apply requires every listed chunk to be judged, so
            # listing one with a blank body would force a blind verdict.
            "chunks": [
                {
                    "rank":      i,
                    "chunk_id":  c["chunk_id"],
                    "statute":   c.get("statute", ""),
                    "section":   c.get("section_number", ""),
                    "text":      (texts.get(c["chunk_id"], "") or "")[:_PREVIEW_CHARS],
                }
                for i, c in enumerate(pooled, 1)
                if texts.get(c["chunk_id"])
            ],
            # To be filled in by the judge.
            "chunk_labels":   {},
            "answer_verdict": "",
            "notes":          "",
        })

    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    n_chunks = sum(len(r["chunks"]) for r in out)
    if unjudgeable:
        print(f"\n  ⚠ {len(unjudgeable)} of {len(records)} turns dropped: no "
              "retrieved chunk resolves in the current corpus")
    print(f"\n  Wrote {len(out)} turns ({n_chunks} chunk judgements) to {path}")
    print(f"  Fill in chunk_labels / answer_verdict, then --apply {path}\n")


# ── Apply ────────────────────────────────────────────────────────────────────

async def cmd_apply(path: Path, labeler: str) -> None:
    items = json.loads(path.read_text(encoding="utf-8"))
    saved = skipped = 0
    errors: list[str] = []

    for item in items:
        verdict = (item.get("answer_verdict") or "").strip()
        if not verdict:
            skipped += 1
            continue
        if verdict not in ls.VERDICTS:
            errors.append(f"{item.get('request_id', '?')[:8]}: bad verdict {verdict!r}")
            continue

        raw = item.get("chunk_labels") or {}
        # Judgements must cover the pooled depth exactly. A partially filled
        # record would be stored with labeled_depth claiming more was judged
        # than was, and ranks nobody looked at would count as irrelevant.
        pooled = [c["chunk_id"] for c in (item.get("chunks") or [])]
        missing = [c for c in pooled if c not in raw]
        if missing:
            errors.append(
                f"{item.get('request_id', '?')[:8]}: {len(missing)} of "
                f"{len(pooled)} chunks unjudged"
            )
            continue

        try:
            await ls.save_label(
                request_id     = item["request_id"],
                chunk_labels   = {k: bool(v) for k, v in raw.items()},
                answer_verdict = verdict,
                labeler        = labeler,
                notes          = item.get("notes", ""),
                labeled_depth  = len(pooled),
                is_baseline    = True,
            )
            saved += 1
        except Exception as exc:
            errors.append(f"{item.get('request_id', '?')[:8]}: {exc}")

    print(f"\n  saved {saved}, skipped (unjudged) {skipped}, errors {len(errors)}")
    for e in errors:
        print(f"    ! {e}")

    s = await ls.stats()
    print(f"\n  human coverage   : {s['labeled']}/{s['labelable']} "
          f"({s['coverage'] * 100:.1f}%)  <- unchanged by a baseline, by design")
    print(f"  baseline labels  : {s.get('baseline_labeled', 0)}\n")


# ── Compare ──────────────────────────────────────────────────────────────────

async def cmd_compare() -> None:
    """Baseline against human labels on turns both have judged.

    Reported as plain counts, not as an agreement coefficient. Krippendorff's
    alpha over a machine and a human would look like an inter-annotator number
    and would be quoted as one.
    """
    from app.db.collections import get_retrieval_labels_col

    by_request: dict[str, dict] = {}
    async for d in get_retrieval_labels_col().find({}, {"_id": 0}):
        by_request.setdefault(d["request_id"], {})[
            "baseline" if d.get("is_baseline") else "human"
        ] = d

    both = {k: v for k, v in by_request.items() if len(v) == 2}
    if not both:
        print("\n  No turn carries both a human and a baseline label yet.\n")
        return

    verdict_match = 0
    chunk_total = chunk_match = 0
    for v in both.values():
        h, b = v["human"], v["baseline"]
        if h.get("answer_verdict") == b.get("answer_verdict"):
            verdict_match += 1
        hl, bl = h.get("chunk_labels") or {}, b.get("chunk_labels") or {}
        for cid in set(hl) & set(bl):
            chunk_total += 1
            chunk_match += bool(hl[cid]) == bool(bl[cid])

    print(f"\n  turns judged by both : {len(both)}")
    print(f"  verdict match        : {verdict_match}/{len(both)} "
          f"({verdict_match / len(both) * 100:.0f}%)")
    if chunk_total:
        print(f"  chunk relevance match: {chunk_match}/{chunk_total} "
              f"({chunk_match / chunk_total * 100:.0f}%)")
    print()


async def _main(args) -> None:
    await connect_db()
    connect_chroma()
    try:
        await _dispatch(args)
    finally:
        await close_db()


async def _dispatch(args) -> None:
    if args.dump:
        await cmd_dump(Path(args.dump), args.limit, args.top_k, args.labeler)
    elif args.apply:
        await cmd_apply(Path(args.apply), args.labeler)
    else:
        await cmd_compare()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dump",    metavar="PATH", help="write pending turns for judging")
    mode.add_argument("--apply",   metavar="PATH", help="record judged turns")
    mode.add_argument("--compare", action="store_true",
                      help="baseline vs human on turns both judged")
    parser.add_argument("--limit",   type=int, default=25)
    parser.add_argument("--top-k",   type=int, default=5,
                        help="pooling depth (0 = every retrieved chunk)")
    parser.add_argument("--labeler", default=DEFAULT_LABELER)
    asyncio.run(_main(parser.parse_args()))
