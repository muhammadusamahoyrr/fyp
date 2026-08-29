"""Amendment footnotes must not be retrieved as the statute they annotate.

Pakistani statute PDFs carry amendment history as numbered footnotes at the page
foot. Extraction flattens the page, so a footnote block can become a chunk of
its own and inherit the section heading above it. Chunk
`statutes_ppc_1860_0834` is labelled PPC s.376 and contains no law at all:

    376. Punishment of rape:  152 Inserted by Protection of Women (Criminal
    Laws Amendment) Act, 2006, S. 5.  153 Inserted by Criminal Law (Amemdment)
    Act, I of 1996.  ...  158 Substituted by Unknown.

Retrieved, that hands the model a list of amending instruments labelled "the law
on punishment for rape" — the LEGAL-UQA failure from a different direction.

The rule under test: at least two numbered footnote entries AND under 10% of the
chunk preceding the first one. Both halves matter, and the second is what keeps
a real section that merely carries footnotes.

Offline: plain strings and LangChain Documents. No Chroma, no model.
"""
from __future__ import annotations

import pytest
from langchain_core.documents import Document

from app.ai.nodes.retrieval_node import _docs_to_chunks, is_footnote_dominated

# ── Real text, verbatim shapes from the corpus ────────────────────────────────

# statutes_ppc_1860_0834 — labelled s.376, entirely apparatus.
PPC_FOOTNOTE_WALL = (
    "376. Punishment of rape:       152   Inserted by Protection of Women "
    "(Criminal Laws Amendment) Act, 2006, S. 5.    153   Inserted by Criminal "
    "Law (Amemdment) Act, I of 1996.    154   Inserted by Pakistan Penal Code "
    "(Amendment) Act, XVI of 1996.    155   Substituted by Criminal Laws "
    "(Amendment) Ordinance, III of 1980.    156   The following was omitted by "
    "Criminal Law (Amendment) Act, VII of 1993 : \"\".    157   Substituted by "
    "Criminal Laws (Amendment) Ordinance, III of 1980.    158   Substituted by "
    "Unknown."
)

# statutes_limitation_act_1908_0041 — operative text FIRST, footnotes trailing.
LIMITATION_S5_MIXED = (
    "5. Extension of period in certain cases .— Any appeal or application "
    "for \n4\n[a revision or] a review of judgment or for leave to appeal or any "
    "other application to \n \n1\nSubstituted for the words “British "
    "India” by the Adaptation of Central Acts and Ordinances Order, 1949 "
    "(G.G.O. No. 4 of 1949), published in the Gazette of Pakistan "
    "(Extraordinary), dated: 28 March 1949, pp. 223-283, Article 3 read with "
    "Article 4. \n2\nThe expression “, but includes an Acceding S tate” "
    "was omitted by the Federal Laws (Revision and Declaration) Ordinance, 1981 "
    "(XXVII of 1981), published in the Gazette of Pakistan (Extraordinary) dated: "
    "8 July 1981, pp. 345 -475, s. 3 read with the Second Schedule."
)

# statutes_ppc_1860_0587 — the actual law, no apparatus at all.
PPC_S375_REAL = (
    "375. Rape:-  A man is said to commit rape who has sexual intercourse with a "
    "woman under circumstances falling  under any of the five following "
    "descriptions,  (i) against her will.     (ii) without her consent     "
    "(iii) with her consent, when the consent has been obtained by putting her "
    "in fear of death or of hurt."
)

# A real section carrying exactly one footnote — must always survive.
SINGLE_FOOTNOTE = (
    "21. Agent of person under disability .— (1) The expression “agent "
    "duly authorized in this behalf,” in sections 19 and 20, shall, in the "
    "case of a person under disability, include his lawful guardian, committee "
    "or manager, or an agent duly authorized by such guardian.  "
    "1 Substituted by the Limitation (Amendment) Ordinance, 1962 (XLIII of 1962)."
)


def _doc(text: str, **meta) -> Document:
    base = {"statute": "PPC 1860", "section_number": "376",
            "chunk_id": "c1", "source_file": "ppc.txt", "province": "federal"}
    base.update(meta)
    return Document(page_content=text, metadata=base)


# ── The detector ──────────────────────────────────────────────────────────────

def test_a_footnote_wall_is_detected():
    assert is_footnote_dominated(PPC_FOOTNOTE_WALL) is True


def test_real_statutory_text_is_not_detected():
    assert is_footnote_dominated(PPC_S375_REAL) is False


def test_a_section_whose_footnotes_trail_its_text_is_preserved():
    """The whole reason entry-count alone is the wrong rule. s.5 of the
    Limitation Act opens with its operative text and trails two entries; it is a
    section with footnotes attached, not a page of footnotes."""
    assert is_footnote_dominated(LIMITATION_S5_MIXED) is False


def test_one_footnote_is_never_enough():
    assert is_footnote_dominated(SINGLE_FOOTNOTE) is False


@pytest.mark.parametrize("text", ["", "   ", None])
def test_empty_input_is_safe(text):
    assert is_footnote_dominated(text) is False


def test_ordinary_prose_mentioning_an_amendment_is_not_apparatus():
    """A section that talks about amendment in its own words has no numbered
    entries, so it cannot trip the detector."""
    text = ("12. Any instrument substituted by the parties, or added by consent, "
            "shall be read as amended by this section for all purposes, and the "
            "court may treat it as inserted by agreement.")
    assert is_footnote_dominated(text) is False


def test_detection_does_not_depend_on_chunk_length():
    """A short chunk that is nothing but two entries is still apparatus."""
    assert is_footnote_dominated(
        "3 Ibid. 4 Substituted by the Repealing and Amending Act, 1919.") is True


# ── The retrieval filter ──────────────────────────────────────────────────────

def test_a_footnote_wall_is_excluded_from_retrieval():
    chunks = _docs_to_chunks([_doc(PPC_FOOTNOTE_WALL, chunk_id="statutes_ppc_1860_0834")])
    assert chunks == []


def test_normal_statutory_chunks_remain_retrievable():
    chunks = _docs_to_chunks([_doc(PPC_S375_REAL, section_number="375",
                                   chunk_id="statutes_ppc_1860_0587")])
    assert len(chunks) == 1
    assert chunks[0]["section_number"] == "375"
    assert "commit rape" in chunks[0]["content"]


def test_a_mixed_chunk_is_not_incorrectly_removed():
    """Statutory text plus trailing footnotes is still evidence."""
    chunks = _docs_to_chunks([_doc(LIMITATION_S5_MIXED, statute="Limitation Act 1908",
                                   section_number="5")])
    assert len(chunks) == 1
    assert "Extension of period" in chunks[0]["content"]


def test_only_the_apparatus_is_dropped_from_a_mixed_batch():
    docs = [
        _doc(PPC_S375_REAL, section_number="375", chunk_id="real_375"),
        _doc(PPC_FOOTNOTE_WALL, section_number="376", chunk_id="wall_376"),
        _doc(SINGLE_FOOTNOTE, statute="Limitation Act 1908", section_number="21",
             chunk_id="real_21"),
    ]
    kept = {c["chunk_id"] for c in _docs_to_chunks(docs)}
    assert kept == {"real_375", "real_21"}


def test_the_filter_can_be_disabled_for_evaluation():
    """Excluded from retrieval, not deleted — the chunks stay reachable for
    anyone measuring extraction quality, exactly like allow_synthetic."""
    chunks = _docs_to_chunks([_doc(PPC_FOOTNOTE_WALL)], allow_footnotes=True)
    assert len(chunks) == 1


def test_the_existing_synthetic_and_supersession_filters_still_apply():
    docs = [
        _doc(PPC_S375_REAL, chunk_id="legal_uqa_qa_0001"),
        _doc(PPC_S375_REAL, statute="Police Act 1861", chunk_id="sup_1",
             superseded_in="punjab"),
        _doc(PPC_S375_REAL, chunk_id="keep_me"),
    ]
    kept = {c["chunk_id"] for c in _docs_to_chunks(docs, province="punjab")}
    assert kept == {"keep_me"}


# ── Citation verification is untouched ────────────────────────────────────────

def test_citation_verification_semantics_are_unchanged():
    """The filter sits in the retrieval path only. corpus_index reads Chroma
    metadata directly, so a section whose only chunk is apparatus is still held
    — and saying otherwise would turn a retrieval decision into a fabrication
    accusation."""
    from app.ai.citation_verification import VERIFIED, verify_statutes
    from app.ai.corpus_index import CorpusIndex, StatuteCoverage

    cov = StatuteCoverage(
        statute="PPC 1860",
        sections=frozenset(str(n) for n in range(1, 512)),
        numbered=frozenset(range(1, 512)), highest=511,
        artifacts=frozenset(), ceiling_outliers=frozenset(),
        omitted=frozenset(), omission_records={})
    index = CorpusIndex({"PPC 1860": cov})

    checks = verify_statutes("charged under PPC Section 376", None, index)
    assert checks[0].status == VERIFIED


def test_lettered_sections_are_unaffected_by_the_filter():
    """A lettered provision's chunk is ordinary text and must survive."""
    text = ("496-A. Enticing or taking away or detaining with criminal intent a "
            "woman: Whoever takes away or entices any woman with intent that she "
            "may have illicit intercourse shall be punished.")
    assert is_footnote_dominated(text) is False
    chunks = _docs_to_chunks([_doc(text, section_number="496A")])
    assert len(chunks) == 1 and chunks[0]["section_number"] == "496A"
