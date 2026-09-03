"""The key rename between a retrieval chunk and a generation-evidence item.

A retrieval chunk carries `section_number`. build_generation_evidence renames it
to `section` when the chunk becomes an evidence item. Nothing documented that,
and the affinity acceptance harness read the chunk-side name against evidence
items: every lookup returned None, and the run reported "PPC 379 in generation
evidence: 0/10" while the chunk_id-based rank simultaneously found it at rank
1-6 in all ten trials. A false failure verdict on a passing system.

These tests pin the contract from both directions so the rename is a stated
property rather than something each new consumer rediscovers by being wrong:
evidence items expose `section` and NOT `section_number`, and a caller matching
on the chunk-side name finds nothing.
"""
import pytest

from app.ai.answer_citations import build_generation_evidence


def _chunk(statute="PPC 1860", section_number="379", chunk_id="statutes_ppc_1860_0598"):
    return {
        "statute": statute,
        "section_number": section_number,
        "chunk_id": chunk_id,
        "source_file": "PAKISTAN PENAL CODE.pdf",
        "province": "federal",
        "content": "379. Punishment for theft: Whoever commits theft shall be punished "
                   "with imprisonment of either description for a term which may extend "
                   "to three years, or with fine, or with both.",
    }


def test_evidence_item_exposes_section_not_section_number():
    ev = build_generation_evidence([_chunk()], [], [])
    assert ev, "a statute chunk must produce an evidence item"
    item = ev[0]
    assert item["section"] == "379"
    assert "section_number" not in item, (
        "evidence items use `section`; a consumer reading `section_number` "
        "silently matches nothing"
    )


def test_matching_on_the_chunk_side_name_finds_nothing():
    """Reproduces the harness bug exactly, so the rename cannot regress unnoticed."""
    ev = build_generation_evidence([_chunk()], [], [])
    wrong = [e for e in ev if str(e.get("section_number")) == "379"]
    right = [e for e in ev if str(e.get("section")) == "379"]
    assert wrong == [], "this is the buggy predicate — it must find nothing"
    assert len(right) == 1, "the correct predicate must find the provision"


def test_evidence_item_keeps_chunk_id_so_rank_measurement_is_valid():
    """The chunk_id-based rank is what proved the 0/10 report wrong."""
    ev = build_generation_evidence([_chunk()], [], [])
    assert ev[0]["chunk_id"] == "statutes_ppc_1860_0598"


def test_statute_and_section_together_identify_the_provision():
    ev = build_generation_evidence(
        [_chunk(), _chunk(statute="CrPC 1898", section_number="221", chunk_id="c1")], [], [])
    found = [e for e in ev
             if str(e.get("section")) == "379" and "PPC" in str(e.get("statute", ""))]
    assert len(found) == 1
    assert found[0]["chunk_id"] == "statutes_ppc_1860_0598"


@pytest.mark.parametrize("field", ["id", "kind", "statute", "section", "chunk_id", "content"])
def test_evidence_item_shape_is_stable(field):
    """Any consumer may rely on these; renaming one is a breaking change."""
    ev = build_generation_evidence([_chunk()], [], [])
    assert field in ev[0]
