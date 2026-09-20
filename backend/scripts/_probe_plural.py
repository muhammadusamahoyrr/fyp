import asyncio, os, sys
from pathlib import Path
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

PROBES = [
    "under section 302 of the PPC 1860",
    "under sections 302 of the PPC 1860",
    "under sections 302 and 324 of the PPC 1860",
    "under section 302 and section 324 of the PPC 1860",
    "under sections 302, 324 and 337 of the PPC 1860",
    "u/s 302 PPC",
    "u/s 302 and 324 PPC",
    "section 302 PPC 1860",
]

async def main():
    from app.core.config import settings
    settings.mongodb_url = Path(os.environ["TEMP"], "v2s.txt").read_text(encoding="utf-8")
    from app.db.mongodb import connect_db
    await connect_db()
    import app.db.chroma as cm
    cm._CHROMA_PATH = Path(os.environ["SCRATCH"]) / "chroma_copy"
    cm.connect_chroma()
    from app.ai.citation_verification import parse_statute_citations
    from app.ai.corpus_index import get_index
    idx = get_index()
    for text in PROBES:
        got = parse_statute_citations(text, idx)
        print(f"{len(got):>2}  {text:48} -> {[(c.statute, c.section) for c in got]}")
    return 0

raise SystemExit(asyncio.run(main()))
