"""Run the pre-filing citation verifier over this system's own recorded answers.

    python scripts/citation_verification_report.py
    python scripts/citation_verification_report.py --examples 15

The number that decides whether this feature ships is NOT the catch rate. It is
the FLAG rate on real traffic. `citation_grounding` was built, measured at an 83%
flag rate, and deliberately left unwired, because a warning that fires on five
answers in six trains users to click through it. Verification is only worth
shipping if it is quiet on ordinary answers and loud on fabrications.

Every flag printed below is a claim that a section does not exist in a statute
this corpus holds in full. Read them. If any is a real provision, the coverage
model is wrong and the threshold in corpus_index must move before this is shown
to a lawyer.
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

from app.ai.citation_verification import (  # noqa: E402
    NOT_IN_CORPUS,
    OMITTED,
    UNVERIFIABLE,
    VERIFIED,
    verify_statutes,
)
from app.ai.corpus_index import get_index  # noqa: E402
from app.db.chroma import connect_chroma  # noqa: E402
from app.db.mongodb import connect_db, get_database  # noqa: E402


async def main(n_examples: int, include_synthetic: bool) -> None:
    connect_chroma()
    await connect_db()
    idx = get_index()

    print("=" * 78)
    print("  PRE-FILING CITATION VERIFICATION — measured on recorded answers")
    print("=" * 78)
    dense = [s for s in idx.statutes if idx.coverage(s).dense]
    print(f"  statutes in corpus               : {len(idx)}")
    print(f"  held densely enough to flag      : {len(dense)}")
    print(f"  distinct sections indexed        : {idx.total_sections()}")
    print(f"  extraction artifacts dropped     : {idx.total_artifacts()}")

    q = {"turn_type": "answer"}
    if not include_synthetic:
        q["is_synthetic"] = {"$ne": True}

    total = with_citation = answers_flagged = 0
    status_counts: Counter[str] = Counter()
    flagged_citations: Counter[str] = Counter()
    examples: list[tuple] = []

    cur = get_database()["answer_provenance"].find(
        q, {"answer_preview": 1, "statute_chunks": 1, "query": 1})
    async for rec in cur:
        total += 1
        preview = rec.get("answer_preview") or ""
        checks = verify_statutes(preview, rec.get("statute_chunks") or [], idx)
        if not checks:
            continue
        with_citation += 1
        for c in checks:
            status_counts[c.status] += 1
        flags = [c for c in checks if c.is_flag]
        if flags:
            answers_flagged += 1
            for c in flags:
                flagged_citations[c.canonical] += 1
            if len(examples) < n_examples:
                examples.append((str(rec.get("query") or "")[:60], flags))

    print()
    print(f"  answer turns examined            : {total}")
    print(f"  containing a parseable citation  : {with_citation}"
          f"   ({100 * with_citation / max(total, 1):.0f}%)")
    if not with_citation:
        print("\n  Nothing to verify.\n")
        return

    n_cit = sum(status_counts.values())
    print()
    print("  per CITATION:")
    for st in (VERIFIED, NOT_IN_CORPUS, OMITTED, UNVERIFIABLE):
        n = status_counts[st]
        print(f"    {st:16s} : {n:5d}   ({100 * n / max(n_cit, 1):.1f}%)")

    rate = 100 * answers_flagged / with_citation
    print()
    print("  per ANSWER — this is the number that decides shipping:")
    print(f"    answers raising at least one flag : {answers_flagged}"
          f" / {with_citation}   ({rate:.1f}%)")
    print()
    if rate <= 10:
        print(f"    {rate:.1f}% is quiet enough that a flag still means something.")
        print("    Compare citation_grounding at 83%, which was never wired in.")
    else:
        print(f"    {rate:.1f}% is high. Before shipping, confirm every flag below is")
        print("    a genuine fabrication and not a coverage gap.")

    if flagged_citations:
        print()
        print("  EVERY FLAGGED CITATION — each asserts this section does not exist:")
        for cit, n in flagged_citations.most_common():
            print(f"    {n:3d}x  {cit}")

    if examples:
        print(f"\n  examples ({len(examples)}):")
        for query, flags in examples:
            print(f"\n    q     : {query}")
            for c in flags:
                print(f"    FLAG  : {c.canonical}")
                print(f"            {c.detail}")

    # A 0% flag rate is only good news next to evidence the detector still
    # fires. Reported together so neither number can be quoted without the
    # other: quiet on real traffic, loud on invented sections.
    print()
    print("  " + "-" * 74)
    print("  POSITIVE CONTROL — does it still catch anything?")
    print("  " + "-" * 74)
    controls = [
        ("liable under PPC Section 302", VERIFIED),
        ("bail under Section 497 of the Code of Criminal Procedure", VERIFIED),
        ("a writ under Article 199 of the Constitution", VERIFIED),
        ("Article 120 of the Limitation Act 1908", UNVERIFIABLE),
        ("under Section 12 of the Companies Act 2017", UNVERIFIABLE),
        ("punishable under PPC Section 999", NOT_IN_CORPUS),
        ("relief under Article 991 of the Constitution", NOT_IN_CORPUS),
        ("under Section 640 of the Qanun-e-Shahadat Order 1984", NOT_IN_CORPUS),
        ("see Section 900 of the Punjab Land Revenue Act 1967", NOT_IN_CORPUS),
        # Repealed, not fabricated — the verdict a lawyer cannot reach by
        # reading, since the number and its history are both real.
        ("triable under CrPC Section 300", OMITTED),
        ("under CrPC Section 270", OMITTED),
        ("Section 154 CrPC", VERIFIED),
    ]
    bad = 0
    for text, expected in controls:
        checks = verify_statutes(text, None, idx)
        got = checks[0].status if checks else "NOT PARSED"
        ok = got == expected
        bad += not ok
        print(f"    {'ok ' if ok else 'FAIL'} {got:14s} (want {expected:14s}) {text[:44]}")
    print()
    print(f"    {len(controls) - bad}/{len(controls)} controls behaved as intended.")
    if bad:
        print("    A control regressed — do NOT trust the flag rate above.")

    print()
    print("  " + "-" * 74)
    print("  WHAT THIS DOES NOT CHECK")
    print("  " + "-" * 74)
    print("  Existence only. A real section cited for a proposition it does not")
    print("  support reads as VERIFIED here — recorded in this project's own data:")
    print("  PPC 302 (murder) was cited for a stamp-duty question and for a tenancy")
    print("  question. Both sections exist. Both citations were nonsense.")
    print()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--examples", type=int, default=8)
    p.add_argument("--include-synthetic", action="store_true")
    a = p.parse_args()
    asyncio.run(main(a.examples, a.include_synthetic))
