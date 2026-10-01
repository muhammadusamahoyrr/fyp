"""Real-corpus smoke test of the shared citation contract. Read-only. No LLM.

Runs the REAL corpus_index.build_index() over the local corpus, then the
drafting record (document_service._verification_record) and the chat
annotator (answer_citations.annotate_citations) on the examples that mattered:
the CPC "s.3" incident, the mixed section/article list, ordinary citations.
Each example asserts its expected outcome; exit code 1 on any regression.

Chroma is embedded and a running backend holds it open; opening a second
client from another process can corrupt it. So the index is fed from the
Chroma sqlite file opened READ-ONLY (`?mode=ro`). Nothing is written.

Usage (from backend/):  python scripts/citation_contract_smoke.py
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

DB = f"file:{(BACKEND / 'chroma_data' / 'chroma.sqlite3').as_posix()}?mode=ro"


class _ReadOnlyCollection:
    def __init__(self, rows):
        self._rows = rows

    def get(self, include=None):
        return {"metadatas": [m for m, _ in self._rows], "documents": [d for _, d in self._rows]}


class _ReadOnlyClient:
    def __init__(self):
        con = sqlite3.connect(DB, uri=True)
        found = defaultdict(dict)
        for name, eid, key, value in con.execute("""
                select c.name, e.id, m.key, m.string_value from embeddings e
                join segments s on s.id = e.segment_id
                join collections c on c.id = s.collection
                join embedding_metadata m on m.id = e.id"""):
            found[name].setdefault(eid, {})[key] = value
        con.close()
        self._collections = {
            name: _ReadOnlyCollection([({k: v for k, v in md.items() if k != "chroma:document"},
                                        md.get("chroma:document") or "") for md in rows.values()])
            for name, rows in found.items()}

    def get_collection(self, name):
        if name not in self._collections:
            raise RuntimeError(f"no collection {name}")
        return self._collections[name]


# (label, text, {canonical: expected status}, expected outcome)
DRAFTING = [
    ("incident", "Legal Basis: CPC 1908 Section 3 allows an agreement to be filed as a suit.",
     {"CPC 1908 s.3": "SECTION_NOT_CHECKABLE"}, "checked"),
    ("description resolves the number", "Section 3 of the CPC (subordination of courts) applies.",
     {"CPC 1908 s.3": "VERIFIED"}, "checked"),
    ("ordinary citations", "The accused is liable under Section 302 PPC and Section 154 CrPC.",
     {"PPC 1860 s.302": "VERIFIED", "CrPC 1898 s.154": "VERIFIED"}, "checked"),
    ("order/rule", "The plaint is rejected under Order VII Rule 11 CPC.",
     {"CPC 1908 Order VII Rule 11": "UNVERIFIABLE"}, "checked"),
    ("mixed section/article list", "PPC Section 489-F and Article 151 of the Limitation Act",
     {"PPC 1860 s.489-F": "UNVERIFIABLE", "Limitation Act 1908 Art.151": "UNVERIFIABLE"}, "checked"),
    ("no citations", "The parties shall act in good faith.", {}, "no_citations_found"),
]


def main() -> int:
    import app.db.chroma as chroma_mod

    client = _ReadOnlyClient()
    chroma_mod.get_chroma = lambda: client

    from app.ai import corpus_index
    from app.ai.answer_citations import annotate_citations
    from app.services.document_service import _verification_record

    index = corpus_index.build_index()
    corpus_index.set_index(index)
    print(f"real index: {len(index)} statutes, {index.total_sections()} sections")
    failures = 0

    for label, text, expected, outcome in DRAFTING:
        rec = asyncio.run(_verification_record({"body": text}))
        got = {c["canonical"]: c["status"] for c in rec["checks"]}
        ok = got == expected and rec["outcome"] == outcome
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} drafting / {label}: {got} outcome={rec['outcome']}")

    chunks = [{"statute": "CPC 1908", "section_number": "3", "chunk_id": "cpc-3"},
              {"statute": "PPC 1860", "section_number": "302", "chunk_id": "ppc-302"}]
    entries = annotate_citations(
        "Under CPC Section 3 the agreement may be filed; PPC Section 302 punishes murder.", chunks)
    cited = {e["section"]: e["status"] for e in entries if e["status"] != "retrieved"}
    ok = cited == {"3": "unresolved", "302": "matched"}
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} chat / shared number not shown as matched: {cited}")

    print("SMOKE PASSED" if not failures else f"SMOKE FAILED: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
