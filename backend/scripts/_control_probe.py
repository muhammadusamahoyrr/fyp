"""Find a citation-verification control that genuinely exercises the flag path.

A bogus section must be PLAUSIBLE to reach a verdict -- the parser drops absurd
numbers before verification, so "section 999999" tests nothing. The real control
is a number inside the statute's own range that the corpus does not hold.
"""
import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


async def main() -> int:
    from app.core.config import settings
    settings.mongodb_url = Path(os.environ["TEMP"], "v2s.txt").read_text(
        encoding="utf-8")
    from app.db.mongodb import connect_db
    await connect_db()

    import app.db.chroma as chroma_mod
    chroma_mod._CHROMA_PATH = Path(os.environ["SCRATCH"]) / "chroma_copy"
    chroma_mod.connect_chroma()

    from app.ai.citation_verification import (parse_statute_citations,
                                              verify_statutes)
    from app.ai.corpus_index import get_index

    index = get_index()

    print("=== does the parser reject implausible numbers? ===")
    for section in ("302", "999999", "5000", "600"):
        parsed = parse_statute_citations(
            f"under section {section} of the PPC 1860", index)
        print(f"  PPC 1860 s.{section:<7} parsed: {len(parsed)}")

    print("\n=== negative control: a plausible section the corpus lacks ===")
    found = None
    for statute in [s for s in index.statutes if index.coverage(s).dense]:
        cov = index.coverage(statute)
        gaps = [n for n in range(1, cov.highest or 1) if n not in cov.numbered]
        if not gaps:
            continue
        for gap in gaps[:40]:
            probe = f"under section {gap} of the {statute}"
            checks = verify_statutes(probe, None, index)
            if any(c.is_flag for c in checks):
                print(f"  FLAGS  {statute} s.{gap} -> "
                      f"{[c.status for c in checks]}")
                found = (statute, gap)
                break
        if found:
            break
    if not found:
        print("  none found")

    print("\n=== positive control: a section the corpus definitely holds ===")
    for statute in [s for s in index.statutes if index.coverage(s).dense][:3]:
        cov = index.coverage(statute)
        real = sorted(cov.numbered)[len(cov.numbered) // 2]
        checks = verify_statutes(f"under section {real} of the {statute}",
                                 None, index)
        print(f"  {statute} s.{real} -> {[c.status for c in checks]}")
    return 0


raise SystemExit(asyncio.run(main()))
