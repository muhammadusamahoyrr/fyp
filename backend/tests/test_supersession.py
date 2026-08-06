"""Jurisdiction-scoped supersession.

Ingesting the Punjab Code put Police Order 2002 (punjab) alongside the Police
Act 1861 (federal). The Order supersedes the 1861 Act IN PUNJAB — but the 1861
Act is federal, so the province filter shows it to Punjab users as well.

This cannot be a global "repealed" flag: the same statute may be superseded in
one province and fully in force in another, and a global flag would hide law
that still governs everyone else.
"""
import pytest
from langchain_core.documents import Document

from app.ai.nodes.retrieval_node import _docs_to_chunks, _is_superseded_for


def _doc(statute, province="federal", superseded_in=None):
    meta = {"statute": statute, "province": province, "chunk_id": statute}
    if superseded_in:
        meta["superseded_in"] = superseded_in
    return Document(page_content=f"text of {statute}", metadata=meta)


# ── the predicate ─────────────────────────────────────────────────────────────

def test_superseded_in_the_querying_province():
    assert _is_superseded_for({"superseded_in": "punjab"}, "punjab") is True


def test_still_in_force_elsewhere():
    """The whole point: a statute superseded in Punjab still governs Sindh."""
    for province in ("sindh", "kpk", "balochistan", "federal"):
        assert _is_superseded_for({"superseded_in": "punjab"}, province) is False


def test_multiple_provinces_are_parsed():
    meta = {"superseded_in": "punjab,sindh"}
    assert _is_superseded_for(meta, "punjab") is True
    assert _is_superseded_for(meta, "sindh") is True
    assert _is_superseded_for(meta, "kpk") is False


@pytest.mark.parametrize("province", ["PUNJAB", "Punjab", " punjab "])
def test_matching_is_case_and_space_insensitive(province):
    assert _is_superseded_for({"superseded_in": "punjab"}, province) is True


def test_unmarked_statutes_are_never_dropped():
    """Almost every chunk has no supersession metadata; none may be hidden."""
    assert _is_superseded_for({}, "punjab") is False
    assert _is_superseded_for({"superseded_in": ""}, "punjab") is False
    assert _is_superseded_for({"superseded_in": None}, "punjab") is False


def test_unknown_province_drops_nothing():
    """A query with no resolved province must not silently lose statutes."""
    assert _is_superseded_for({"superseded_in": "punjab"}, "") is False


# ── the retrieval filter ──────────────────────────────────────────────────────

def test_punjab_query_drops_the_superseded_police_act():
    docs = [
        _doc("Police Act 1861", "federal", superseded_in="punjab"),
        _doc("Police Order 2002", "punjab"),
        _doc("PPC 1860", "federal"),
    ]
    statutes = [c["statute"] for c in _docs_to_chunks(docs, "punjab")]
    assert "Police Act 1861" not in statutes
    assert "Police Order 2002" in statutes
    assert "PPC 1860" in statutes


def test_sindh_query_keeps_the_police_act():
    """Sindh has not adopted the Punjab replacement, so the 1861 Act stands."""
    docs = [_doc("Police Act 1861", "federal", superseded_in="punjab")]
    statutes = [c["statute"] for c in _docs_to_chunks(docs, "sindh")]
    assert statutes == ["Police Act 1861"]


def test_no_province_supplied_keeps_everything():
    docs = [_doc("Police Act 1861", "federal", superseded_in="punjab")]
    assert len(_docs_to_chunks(docs, "")) == 1


def test_filtering_preserves_the_chunk_shape():
    """Downstream code reads these keys; the filter must not change the shape."""
    chunks = _docs_to_chunks([_doc("PPC 1860")], "punjab")
    assert set(chunks[0]) == {
        "content", "statute", "section_number", "source_file",
        "chunk_id", "province", "law_type",
    }
