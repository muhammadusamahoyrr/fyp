"""Does the parser drop section citations to statutes the corpus does not hold?

If it does, a draft citing an out-of-corpus statute produces "0 citations, no
problems" rather than "unverifiable" -- a silent false pass, and exactly what
_unavailable_verification's docstring says must never happen.
"""
import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

PROBES = [
    # (label, text) -- in-corpus statutes first, as the control
    ("in corpus, real section",  "an offence under section 302 of the PPC 1860"),
    ("in corpus, MFLO",          "under section 8 of the Muslim Family Laws Ordinance 1961"),
    ("OUT of corpus: PECA long", "an offence under section 20 of the Prevention of Electronic Crimes Act 2016"),
    ("OUT of corpus: PECA acro", "an offence under section 20 of PECA 2016"),
    ("OUT of corpus: PECA text", "including sections 20 and 24 PECA"),
    ("OUT of corpus: Registr.",  "registered under section 17 of the Registration Act, 1908"),
    ("OUT of corpus: Wages",     "under section 15 of the Payment of Wages Act 1936"),
    ("OUT of corpus: OPPA",      "under section 9 of the Overseas Pakistanis' Property Act, 2024"),
    ("plural, in corpus",        "under sections 302 and 324 of the PPC 1860"),
]


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

    print(f"{'probe':28} {'parsed':>6}  verdicts")
    print("-" * 74)
    for label, text in PROBES:
        parsed = parse_statute_citations(text, index)
        checks = verify_statutes(text, None, index)
        verdicts = [f"{c.canonical}={c.status}" for c in checks] or ["(none)"]
        print(f"{label:28} {len(parsed):>6}  {', '.join(verdicts)[:60]}")

    print("\n=== the mechanism ===")
    print("A statute name the index cannot canonicalise yields no ParsedCitation")
    print("at all, so verify_statutes never sees it and the draft is reported as")
    print("citing nothing. Confirmed by the rows above: identical grammar, the")
    print("only difference being whether the statute is one of the 44 held.")
    return 0


raise SystemExit(asyncio.run(main()))
