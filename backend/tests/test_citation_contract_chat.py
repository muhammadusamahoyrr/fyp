"""AI Chat reads the same shared-number data as the drafting verifier.

A chat answer citing "CPC Section 3" used to get a green "matched" chip
whenever a chunk labelled CPC 3 was in its evidence -- even though the corpus
files Order rules under that number. See test_citation_contract.py.
"""
from __future__ import annotations

import pytest

from app.ai.answer_citations import annotate_citations
from app.ai.corpus_index import CorpusIndex, StatuteCoverage


def cov(statute: str, n: int, provisions: dict | None = None) -> StatuteCoverage:
    sections = frozenset(str(i) for i in range(1, n + 1))
    return StatuteCoverage(statute=statute, sections=sections,
                           numbered=frozenset(range(1, n + 1)), highest=n,
                           artifacts=0, provisions=provisions or {})


@pytest.fixture
def index() -> CorpusIndex:
    return CorpusIndex({
        "CPC 1908": cov("CPC 1908", 158, {
            "3": ("Subordination of Courts", "Materials from which issue may be framed"),
            "9": ("Courts to try all civil suits unless barred",),
        }),
    })


def test_chat_does_not_show_an_ambiguous_number_as_a_matched_source(index):
    """AI Chat reads the same index: no green tick for the shared number."""
    chunk = {"statute": "CPC 1908", "section_number": "3", "chunk_id": "cpc_1672",
             "source_file": "cpc.pdf"}
    entries = annotate_citations("Under CPC Section 3 the agreement may be filed.",
                                 [chunk], index=index)
    cited = [e for e in entries if e["section"] == "3" and e["status"] != "retrieved"]
    assert cited == [{"statute": cited[0]["statute"], "section": "3", "source": "",
                      "status": "unresolved", "reason": "section_not_checkable"}]
    # Still disclosed as consulted evidence -- just not as what the answer cited.
    assert any(e["status"] == "retrieved" and e.get("chunk_id") == "cpc_1672" for e in entries)


def test_chat_still_matches_an_unambiguous_number(index):
    chunk = {"statute": "CPC 1908", "section_number": "9", "chunk_id": "cpc_9"}
    [entry] = [e for e in annotate_citations("Jurisdiction lies under CPC Section 9.",
                                             [chunk], index=index) if e["section"] == "9"]
    assert entry["status"] == "matched" and entry["chunk_id"] == "cpc_9"


def test_chat_fails_open_when_the_index_is_unavailable():
    class Broken:
        def coverage(self, statute):
            raise RuntimeError("chroma down")

    chunk = {"statute": "CPC 1908", "section_number": "3", "chunk_id": "c"}
    [entry] = [e for e in annotate_citations("See CPC Section 3.", [chunk], index=Broken())
               if e["section"] == "3"]
    assert entry["status"] == "matched"            # exactly the previous behaviour
