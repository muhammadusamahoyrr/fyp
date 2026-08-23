"""
label_provenance.py — Turn recorded answers into a labeled evaluation set.

Every answered turn already stored its query, the chunk ids retrieved for it and
the Decision Engine's verdict. This walks those records and asks a human the one
thing the system cannot decide for itself: was each retrieved chunk actually
relevant, and was the outcome right?

Usage
-----
  # How much is left to do
  python scripts/label_provenance.py --stats

  # Label interactively (resumable — already-labeled records are skipped)
  python scripts/label_provenance.py --label --limit 25 --labeler usama

  # Export once you have enough
  python scripts/label_provenance.py --export data/legal_uqa.json
  python scripts/label_provenance.py --export-calibration data/calibration.json

Then feed the retrieval set straight into the existing harness:
  python scripts/evaluate_retrieval.py --dataset data/legal_uqa.json --k 1 3 5

Keys while labeling
-------------------
  y / n    chunk is relevant / not relevant
  s        skip this record entirely (no label written)
  q        stop and save what is already done

Answer verdict (asked once per record):
  1 correct          answered, and the answer was right
  2 incorrect        answered, and the answer was wrong
  3 correct refusal  refused, and refusing was right
  4 wrong refusal    refused, but it had enough to answer

All four verdicts matter: without separating a correct refusal from a wrong one
you cannot draw a risk-coverage curve, which is the point of the exercise.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.ai.threshold_manager import WARMUP_QUERY_COUNT       # noqa: E402
from app.db.chroma import connect_chroma, get_chroma          # noqa: E402
from app.db.mongodb import close_db, connect_db               # noqa: E402
from app.services import labeling_service as ls               # noqa: E402

# Labels needed for a defensible evaluation set and for fitting calibration.
# Platt scaling has two parameters and standard IR test collections run to a few
# hundred topics, so a few hundred pairs is the realistic bar — not the 1000
# that WARMUP_QUERY_COUNT refers to, which counts unlabeled queries.
_TARGET_LABELS = 200

_CASE_TYPE_TO_COLLECTION = {
    "civil":          "civil_collection",
    "criminal":       "criminal_collection",
    "family":         "family_collection",
    "constitutional": "constitutional_collection",
}

_PREVIEW_CHARS = 420


# ── Chunk text lookup ─────────────────────────────────────────────────────────

def _chunk_texts(case_type: str, chunk_ids: list[str]) -> dict[str, str]:
    """
    Fetch chunk bodies from Chroma. A chunk_id alone is unjudgeable — the whole
    point is that a human reads the statute text before calling it relevant.

    Degrades to empty strings rather than failing the session: a missing chunk
    (re-ingested corpus, renamed collection) should cost one judgement, not the
    whole labeling run.
    """
    if not chunk_ids:
        return {}
    name = _CASE_TYPE_TO_COLLECTION.get(case_type, "civil_collection")
    try:
        col = get_chroma().get_collection(name)
        got = col.get(ids=chunk_ids, include=["documents"])
        return {
            cid: (doc or "")
            for cid, doc in zip(got.get("ids", []), got.get("documents", []))
        }
    except Exception as exc:
        print(f"  ⚠ could not read chunk text from '{name}': {exc}")
        return {}


# ── Rendering ─────────────────────────────────────────────────────────────────

def _rule(char: str = "─", width: int = 78) -> str:
    return char * width


def _show_record(prov: dict, index: int, total: int) -> None:
    print("\n" + _rule("="))
    print(f"  [{index}/{total}]  {prov.get('case_type', '?')} / "
          f"{prov.get('province', '?')}   request_id={prov.get('request_id', '')[:8]}…")
    print(_rule("="))
    print(f"\nQ: {prov.get('query', '')}\n")

    arb = prov.get("arbitration", {}) or {}
    sig = prov.get("signals", {}) or {}
    print(f"system verdict : {arb.get('output', '?')} "
          f"(source={arb.get('source', '?')} conf={arb.get('confidence', 0):.2f})")
    print(f"signals        : relevance={sig.get('relevance_score', 0):.2f} "
          f"variance={sig.get('signal_variance', 0):.2f} "
          f"lexical={sig.get('bm25_confidence', 0):.2f}")

    tools = prov.get("tool_calls") or []
    if tools:
        print("engines        : " + ", ".join(
            f"{t['tool']}{'' if t.get('ok') else ' (failed)'}" for t in tools
        ))

    print(f"\nA: {prov.get('answer_preview', '')}\n")


def _prompt_chunks(prov: dict, top_k: int) -> dict[str, bool] | None:
    """
    Ask relevance for the top `top_k` retrieved chunks (0 = all).

    Pooling to a fixed depth is standard IR practice and it is what makes this
    dataset achievable: retrieval returns up to 20 chunks, and judging every one
    works out at ~12 per record — about 50 hours for 1000 records. Ranks below 5
    contribute nothing to Hit@K / MRR / nDCG at k<=5, so they are not worth the
    time. The depth is stored with the label so metrics above it can be refused.
    """
    chunks = prov.get("statute_chunks") or []
    if not chunks:
        print("  (no statute chunks were retrieved for this query)")
        return {}

    total  = len(chunks)
    chunks = chunks[:top_k] if top_k else chunks
    if total > len(chunks):
        print(f"  judging top {len(chunks)} of {total} retrieved "
              f"(ranks {len(chunks) + 1}-{total} left unjudged)")

    texts  = _chunk_texts(prov.get("case_type", ""), [c["chunk_id"] for c in chunks])

    # A chunk whose text cannot be recovered is UNJUDGEABLE, and inviting a
    # judgement anyway is worse than skipping it. The corpus was re-ingested
    # after the earliest turns were recorded and chunk ids changed scheme
    # (hash-suffixed -> statutes_<slug>_<NNNN>), so some recorded ids now
    # resolve to nothing. Shown a blank body, protocol section 4 tells the
    # annotator to answer "not relevant" — which would fill the set with
    # confident irrelevance judgements nobody actually made.
    if not any(texts.get(c["chunk_id"]) for c in chunks):
        print("  ⚠ none of the retrieved chunks resolve in the current corpus "
              "— skipping.")
        print("    (recorded ids predate the re-ingest; see --stats for how "
              "many turns this affects)")
        return None

    labels: dict[str, bool] = {}

    for i, chunk in enumerate(chunks, 1):
        cid  = chunk["chunk_id"]
        body = texts.get(cid, "")
        print(_rule())
        head = " ".join(filter(None, [
            chunk.get("statute", ""),
            f"s.{chunk['section_number']}" if chunk.get("section_number") else "",
        ]))
        if not body:
            # Left out of `labels` entirely rather than defaulted: an unjudged
            # rank is missing data, and recording it as irrelevant would
            # understate every retrieval metric computed from this set.
            print(_rule())
            print(f"  chunk {i}/{len(chunks)}  {head or cid}")
            print("  ⚠ text unavailable — left UNJUDGED, not marked irrelevant")
            continue
        print(f"  chunk {i}/{len(chunks)}  {head or cid}")
        print(_rule())
        print(f"  {body[:_PREVIEW_CHARS] or '(text unavailable)'}")

        while True:
            choice = input("  relevant? [y/n/s/q] ").strip().lower()
            if choice in ("y", "n"):
                labels[cid] = (choice == "y")
                break
            if choice == "s":
                return None
            if choice == "q":
                raise KeyboardInterrupt
            print("  please answer y, n, s (skip) or q (quit)")

    return labels


_VERDICT_KEYS = {
    "1": ls.VERDICT_CORRECT,
    "2": ls.VERDICT_INCORRECT,
    "3": ls.VERDICT_CORRECT_REFUSAL,
    "4": ls.VERDICT_WRONG_REFUSAL,
}


def _prompt_verdict(prov: dict) -> str | None:
    refused = (prov.get("arbitration", {}) or {}).get("output") == "refuse"
    hint    = "(system REFUSED — 3 or 4)" if refused else "(system answered — 1 or 2)"
    print(_rule())
    print(f"  verdict {hint}")
    print("    1 correct   2 incorrect   3 correct refusal   4 wrong refusal   s skip")
    while True:
        choice = input("  verdict? [1/2/3/4/s/q] ").strip().lower()
        if choice in _VERDICT_KEYS:
            return _VERDICT_KEYS[choice]
        if choice == "s":
            return None
        if choice == "q":
            raise KeyboardInterrupt
        print("  please answer 1, 2, 3, 4, s (skip) or q (quit)")


# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_stats() -> None:
    s = await ls.stats()
    print("\n" + _rule("="))
    print("  LABELING PROGRESS")
    print(_rule("="))
    print(f"  provenance records : {s['provenance_records']}")
    print(f"  labelable (answers): {s['labelable']}")
    print(f"  labeled (human)    : {s['labeled']}")
    print(f"  remaining          : {s['remaining']}")
    print(f"  coverage           : {s['coverage'] * 100:.1f}%")
    if s.get("baseline_labeled"):
        print(f"  machine baseline   : {s['baseline_labeled']} "
              "(excluded from the eval set — see agreement.py)")

    print("\n  by turn type (all audited, only answers are labelable):")
    for turn, count in s["by_turn_type"].items():
        print(f"    {turn:<16} {count}")
    print("\n  by verdict:")
    for verdict, count in s["by_verdict"].items():
        print(f"    {verdict:<16} {count}")

    if s["labeled"]:
        lo, hi = s["min_labeled_depth"], s["max_labeled_depth"]
        span   = f"{lo}" if lo == hi else f"{lo}-{hi}"
        print(f"\n  pooling depth      : {span}")
        print(f"  metrics valid up to: k={lo}  "
              f"(ranks below that were never judged)")

    # Two DIFFERENT targets, previously conflated into a single "1000 labels"
    # figure that overstated the work by roughly 5x:
    #   - labels are needed for the eval set and for fitting calibration
    #   - threshold warmup counts QUERIES, not labels (record_query runs on
    #     every RAG turn with is_labeled=False), so it is driven by traffic and
    #     needs no human at all
    print(f"\n  targets")
    if s["labeled"] < _TARGET_LABELS:
        print(f"    eval set + calibration : {s['labeled']}/{_TARGET_LABELS} labels "
              f"({_TARGET_LABELS - s['labeled']} to go)")
    else:
        print(f"    eval set + calibration : {s['labeled']}/{_TARGET_LABELS} labels — met")
    print(f"    threshold warmup       : needs {WARMUP_QUERY_COUNT} QUERIES, not labels "
          f"- generate traffic, no labelling required")
    print()


async def cmd_label(limit: int, labeler: str, top_k: int) -> None:
    if not labeler:
        raise SystemExit(
            "--labeler is required. An unattributed label cannot be checked "
            "for inter-annotator agreement, and agreement is what makes the "
            "evaluation set credible. See ANNOTATION_PROTOCOL.md."
        )
    # Scoped to this annotator: unscoped, the second labeller is told there is
    # nothing left the moment the first finishes, and the set can never be
    # double-labelled.
    records = await ls.unlabeled_records(limit=limit, labeler=labeler)
    if not records:
        print(f"\n  Nothing left for {labeler!r} to label. "
              "Run with --stats to confirm.\n")
        return

    depth = f"top {top_k}" if top_k else "all"
    print(f"\n  {len(records)} unlabeled records, judging {depth} chunks each. "
          f"y/n per chunk, s to skip, q to stop.\n")
    saved = skipped = 0

    try:
        for i, prov in enumerate(records, 1):
            _show_record(prov, i, len(records))

            chunk_labels = _prompt_chunks(prov, top_k)
            if chunk_labels is None:
                skipped += 1
                print("  → skipped")
                continue

            verdict = _prompt_verdict(prov)
            if verdict is None:
                skipped += 1
                print("  → skipped")
                continue

            await ls.save_label(
                request_id     = prov["request_id"],
                chunk_labels   = chunk_labels,
                answer_verdict = verdict,
                labeler        = labeler,
                # What was ACTUALLY judged, not what was pooled: chunks whose
                # text could not be recovered are skipped above, and claiming
                # depth 5 when three were judged would treat two unjudged
                # ranks as irrelevant.
                labeled_depth  = len(chunk_labels),
            )
            saved += 1
            n_rel = sum(1 for ok in chunk_labels.values() if ok)
            print(f"  → saved ({n_rel} relevant, verdict={verdict})")

    except KeyboardInterrupt:
        print("\n\n  Stopped. Everything already confirmed is saved.")

    print(f"\n  saved={saved}  skipped={skipped}\n")


async def cmd_export(path: Path) -> None:
    answerable, unanswerable = await ls.export_retrieval_dataset()
    if not answerable and not unanswerable:
        print("\n  Nothing labeled yet — nothing to export.\n")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(answerable, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  {len(answerable)} answerable items → {path}")

    if unanswerable:
        # Kept as its own file: evaluate_retrieval.py skips zero-relevant items,
        # but these ARE the abstention split — the queries where refusing is the
        # correct behaviour.
        abstain = path.with_name(path.stem + "_unanswerable.json")
        abstain.write_text(
            json.dumps(unanswerable, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  {len(unanswerable)} unanswerable items → {abstain}")

    # The pooling depth decides which k values the exported labels can support.
    # Suggesting --k 1 3 5 unconditionally would invite an nDCG@5 computed from
    # depth-3 labels, where ranks 4-5 are unjudged rather than irrelevant.
    s     = await ls.stats()
    depth = s["min_labeled_depth"]
    ks    = [k for k in (1, 3, 5, 10) if k <= depth] or [1]
    print(f"\n  pooling depth {depth} → metrics valid for k in {ks}")
    if depth < 5:
        print("  (labels were pooled shallower than 5; k=5 would treat unjudged "
              "ranks as irrelevant)")
    print(f"\n  Next: python scripts/evaluate_retrieval.py --dataset {path} "
          f"--k {' '.join(str(k) for k in ks)}\n")


async def cmd_export_calibration(path: Path) -> None:
    pairs = await ls.export_calibration_pairs()
    if not pairs:
        print("\n  Nothing labeled yet — nothing to export.\n")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pairs, indent=2, ensure_ascii=False), encoding="utf-8")

    correct = sum(1 for p in pairs if p["correct"])
    print(f"\n  {len(pairs)} calibration pairs → {path}")
    print(f"  {correct} good outcomes / {len(pairs) - correct} bad "
          f"({correct / len(pairs) * 100:.1f}% base rate)")
    print("  Fit with calibration.fit_platt(...) / fit_bm25_isotonic(...)\n")


# ── Entry point ───────────────────────────────────────────────────────────────

async def _main(args: argparse.Namespace) -> None:
    await connect_db()
    connect_chroma()
    try:
        if args.stats:
            await cmd_stats()
        elif args.label:
            await cmd_label(args.limit, args.labeler, args.top_k)
        elif args.export:
            await cmd_export(Path(args.export))
        elif args.export_calibration:
            await cmd_export_calibration(Path(args.export_calibration))
    finally:
        await close_db()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Label recorded answers into an evaluation set."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--stats",   action="store_true", help="show labeling progress")
    mode.add_argument("--label",   action="store_true", help="label interactively")
    mode.add_argument("--export",  metavar="PATH", help="write the retrieval eval set")
    mode.add_argument("--export-calibration", metavar="PATH",
                      help="write (score, correct) pairs for calibration fitting")

    parser.add_argument("--limit",   type=int, default=25, help="records per session")
    parser.add_argument("--labeler", default="", help="name recorded with each label")
    parser.add_argument("--top-k",   type=int, default=5,
                        help="judge only the top K retrieved chunks (0 = all). "
                             "Default 5: enough for Hit@K/MRR/nDCG at k<=5, and "
                             "roughly a third of the effort of judging all 20.")

    asyncio.run(_main(parser.parse_args()))
