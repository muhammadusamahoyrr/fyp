"""How much of what this system cites was actually in front of it?

    python scripts/citation_grounding_report.py
    python scripts/citation_grounding_report.py --examples 15

Reads recorded answers from provenance and reports, for each, whether the
statutes it cited appear in the evidence it retrieved.

READ THE OUTPUT AS A MEASUREMENT, NOT AN ERROR RATE. Ungrounded means the
citation was not in the retrieved set; it does not mean the law is wrong.
Correct law recalled from the model's parametric memory lands in the same
bucket — observed here: an FIR question answered with CrPC s.154, which is
exactly the right provision and was never retrieved.

What a high rate DOES evidence is that retrieval is not load-bearing: the
pipeline is answering from parametric memory rather than from its corpus. That
is worth knowing, and it is measurable without annotators, without a provider,
and without calibration — unlike everything else currently blocking this
project.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.ai.citation_grounding import grounding_report  # noqa: E402
from app.db.mongodb import connect_db, get_database  # noqa: E402


async def main(n_examples: int, include_synthetic: bool) -> None:
    await connect_db()
    q = {"turn_type": "answer"}
    if not include_synthetic:
        q["is_synthetic"] = {"$ne": True}

    total = measurable = fully = partly = none_grounded = 0
    truncated = capped = 0
    ratios: list[float] = []
    ungrounded_counter: Counter[str] = Counter()
    examples: list[tuple] = []

    cur = get_database()["answer_provenance"].find(
        q, {"answer_preview": 1, "statute_chunks": 1, "query": 1, "signals": 1})
    async for rec in cur:
        total += 1
        preview = rec.get("answer_preview") or ""
        chunks = rec.get("statute_chunks") or []
        # Both stored fields are capped, and both bias this measurement.
        if len(preview) >= 498 or preview.rstrip().endswith("…"):
            truncated += 1
        if len(chunks) >= 20:
            capped += 1
        r = grounding_report(preview, chunks)
        if not r["measurable"]:
            continue
        measurable += 1
        ratios.append(r["grounded_ratio"])
        if r["grounded_ratio"] == 1.0:
            fully += 1
        elif r["grounded_ratio"] == 0.0:
            none_grounded += 1
        else:
            partly += 1
        for c in r["ungrounded"]:
            ungrounded_counter[c] += 1
        if r["ungrounded"] and len(examples) < n_examples:
            bm25 = (rec.get("signals") or {}).get("bm25_confidence")
            examples.append((str(rec.get("query") or "")[:58], r["cited"],
                             r["ungrounded"], bm25))

    print("=" * 78)
    print("  CITATION GROUNDING — are cited statutes present in retrieved evidence?")
    print("=" * 78)
    print(f"  answer turns examined            : {total}")
    print(f"  with a parseable citation        : {measurable}"
          f"   ({100 * measurable / max(total, 1):.0f}%)")
    if not measurable:
        print("\n  Nothing to measure. A parseable citation needs an explicit section "
              "marker\n  (\"PPC Section 379\"), which is deliberate — see the module "
              "docstring.\n")
        return

    print()
    print(f"  every citation grounded          : {fully}"
          f"   ({100 * fully / measurable:.0f}%)")
    print(f"  some grounded, some not          : {partly}"
          f"   ({100 * partly / measurable:.0f}%)")
    print(f"  none grounded                    : {none_grounded}"
          f"   ({100 * none_grounded / measurable:.0f}%)")
    print(f"  mean grounded ratio              : {sum(ratios) / len(ratios):.3f}")
    flagged = measurable - fully
    print(f"  at least one ungrounded citation : {flagged}"
          f"   ({100 * flagged / measurable:.0f}%)")

    print()
    print("  This rate is NOT an error rate. Correct law recalled from parametric")
    print("  memory is counted here too. What it evidences is how much of the")
    print("  answer came from retrieval rather than from the model.")

    # Historical records cannot support a precise figure, and saying so is the
    # difference between a measurement and a number that merely looks like one.
    print()
    print("  " + "-" * 74)
    print("  MEASUREMENT LIMITS ON STORED RECORDS — read before quoting a figure")
    print("  " + "-" * 74)
    print(f"  answers whose preview was TRUNCATED at 500 chars : {truncated}"
          f"  ({100 * truncated / max(total, 1):.0f}%)")
    print("      The full answer is never stored — only a hash and this preview —")
    print("      so citations past 500 characters are invisible here.")
    print(f"  answers whose evidence hit the 20-chunk cap      : {capped}")
    print("      Their true retrieved set was larger, so a citation can look")
    print("      ungrounded when it was in a chunk that was never stored.")
    print()
    print("  Both biases run the SAME way: they OVERSTATE ungroundedness. Treat the")
    print("  ratio above as a LOWER BOUND on how grounded this system's citations")
    print("  really are.")
    print()
    print("  Records written from now on carry `citation_grounding` computed at")
    print("  write time against the FULL answer and the FULL reranked set, so they")
    print("  do not suffer either bias. Prefer those for any published figure.")

    if ungrounded_counter:
        print("\n  most frequently ungrounded citations:")
        for cit, n in ungrounded_counter.most_common(8):
            print(f"    {n:3d}x  {cit}")

    if examples:
        print(f"\n  examples ({len(examples)}):")
        for query, cited, ungrounded, bm25 in examples:
            print(f"\n    q     : {query}")
            print(f"    cited : {cited}")
            print(f"    UNGR. : {ungrounded}")
            # bm25 == 0.0 alongside an ungrounded citation is the compound
            # signal worth testing once labels exist: nothing lexical matched
            # the question AND the citation was not in evidence.
            if bm25 == 0.0:
                print("    note  : bm25_confidence 0.0 — no lexical overlap either")

    print()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--examples", type=int, default=6)
    p.add_argument("--include-synthetic", action="store_true",
                   help="include warmup/replay traffic (excluded by default)")
    a = p.parse_args()
    asyncio.run(main(a.examples, a.include_synthetic))
