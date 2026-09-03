"""Named-statute affinity — detection, stable preference, and both choke points.

These call the production functions. Where a test needs a grader result it drives
the real `retrieval_grader_node` with the LLM and embedding calls monkeypatched,
rather than re-implementing the ordering rule and asserting against itself — a
test that copies the implementation passes when the implementation is wrong.

Context: "punishment for theft under the Pakistan Penal Code" put PPC 379 at
ensemble rank 15-16 while grading and generation see only the first eight, and
seven of that eight were CrPC procedural provisions that quote penal section
numbers without stating an offence.
"""
import pytest

from app.ai.pipelines.statute_affinity import (
    apply_affinity,
    detect_named_statute,
    prefer_statute,
)


def chunk(statute, section="", content="x"):
    return {"statute": statute, "section_number": section, "content": content,
            "chunk_id": f"{statute}:{section}"}


# ── detection ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("query,expected", [
    ("What is the punishment for theft under the PPC?",        "PPC 1860"),
    ("punishment for theft under the Pakistan Penal Code",     "PPC 1860"),
    ("Pakistan Penal Code 1860 — theft",                       "PPC 1860"),
    ("under the pakistan penal code",                          "PPC 1860"),
    ("P.P.C. section 302",                                     "PPC 1860"),
    ("PAKISTAN PENAL CODE",                                    "PPC 1860"),
    ("Cr.P.C. 154 FIR",                                        "CrPC 1898"),
    ("Code of Criminal Procedure section 154",                 "CrPC 1898"),
    ("CPC order 7 rule 11",                                    "CPC 1908"),
    ("Qanun-e-Shahadat article 17",                            "Qanun-e-Shahadat Order 1984"),
    ("PECA 2016 cybercrime",                                   "PECA 2016"),
    ("MFLO section 7 divorce",                                 "Muslim Family Laws Ordinance 1961"),
    ("Constitution of Pakistan article 199",                   "Constitution of Pakistan 1973"),
])
def test_single_named_statute_is_detected(query, expected):
    assert detect_named_statute(query) == expected


def test_repeated_aliases_for_one_statute_resolve_to_one():
    """"PPC" and "Pakistan Penal Code" are the same statute, not two."""
    assert detect_named_statute(
        "Under the PPC — that is, the Pakistan Penal Code — what is theft?") == "PPC 1860"


@pytest.mark.parametrize("query", [
    "Compare PPC and CrPC on theft",
    "Does the Pakistan Penal Code or the Code of Criminal Procedure govern this?",
    "CPC versus CrPC jurisdiction",
])
def test_two_distinct_statutes_yield_no_preference(query):
    """Comparison questions must keep both sides. No preference is correct."""
    assert detect_named_statute(query) is None


@pytest.mark.parametrize("query", [
    "What does section 379 say?",
    "punishment for theft",
    "bail after arrest",
    "rules of evidence in a criminal trial",
    "cybercrime complaint procedure",
    "Can a tenant be evicted without notice in Punjab?",
    "",
])
def test_subject_words_and_bare_sections_name_no_statute(query):
    """Inferring intent from topic words would make this a global reranker."""
    assert detect_named_statute(query) is None


def test_cpc_does_not_match_inside_crpc():
    """A substring collision registers two families and silently kills preference."""
    assert detect_named_statute("CrPC 154") == "CrPC 1898"
    assert detect_named_statute("Cr.P.C. 154") == "CrPC 1898"


@pytest.mark.parametrize("query", [
    "What does the constitution of a partnership firm require?",
    "the constitution of the board of directors",
    "the constitution of a company limited by shares",
])
def test_constitution_as_an_ordinary_noun_is_not_a_statute(query):
    """"Constitution" is the one short form that is also a common English noun.

    Legal prose uses it constantly in the ordinary sense, and each of these
    matched before the guard — preferring the Constitution of Pakistan over
    whatever statute the question was actually about.
    """
    assert detect_named_statute(query) is None


@pytest.mark.parametrize("query", [
    "Constitution of Pakistan article 199",
    "under the Constitution, Article 199",
    "the Constitution's Article 8",
    "rights under the Constitution of Pakistan 1973",
])
def test_genuine_constitution_references_still_detected(query):
    assert detect_named_statute(query) == "Constitution of Pakistan 1973"


# ── the two detectors must be UNIONED, not chained ───────────────────────────
# A registry statute and a corpus-only statute named together is the case an
# `or` chain gets wrong: the registry detector alone sees one statute, returns
# it, and the corpus-only name is never looked for. The comparison silently
# tilts toward whichever side happens to have an acronym.

def test_registry_statute_plus_corpus_statute_yields_no_preference():
    chunks = [chunk("PPC 1860", "379"), chunk("Punjab Tenancy Act 1887", "1")]
    q = "Compare the PPC and the Punjab Tenancy Act on possession"
    out, named = apply_affinity(list(chunks), q)
    assert named is None, "a two-statute comparison must not be tilted"
    assert [c["chunk_id"] for c in out] == [c["chunk_id"] for c in chunks]


def test_crpc_plus_succession_act_yields_no_preference():
    chunks = [chunk("CrPC 1898", "154"), chunk("Succession Act 1925", "372")]
    q = "How do the CrPC and the Succession Act differ on procedure?"
    _, named = apply_affinity(list(chunks), q)
    assert named is None


def test_reversed_candidate_order_gives_the_same_verdict():
    """Detection must not depend on the order chunks arrive in."""
    a = [chunk("PPC 1860", "379"), chunk("Punjab Tenancy Act 1887", "1")]
    q = "Compare the PPC and the Punjab Tenancy Act"
    assert apply_affinity(list(a), q)[1] is None
    assert apply_affinity(list(reversed(a)), q)[1] is None

    single = "theft under the PPC"
    assert apply_affinity(list(a), single)[1] == "PPC 1860"
    assert apply_affinity(list(reversed(a)), single)[1] == "PPC 1860"


def test_repeated_aliases_across_both_detectors_are_one_statute():
    """"PPC" (registry) and "PPC 1860" (corpus name) must not count as two."""
    chunks = [chunk("PPC 1860", "379"), chunk("CrPC 1898", "221")]
    out, named = apply_affinity(
        list(chunks), "Under the PPC — the Pakistan Penal Code, PPC 1860 — what is theft?")
    assert named == "PPC 1860"
    assert out[0]["statute"] == "PPC 1860"


# ── stable preference, never exclusion ───────────────────────────────────────

def test_preference_moves_named_statute_first_without_dropping_anything():
    chunks = [chunk("CrPC 1898", "221"), chunk("CrPC 1898", "260"),
              chunk("PPC 1860", "379"), chunk("CrPC 1898", "234"),
              chunk("PPC 1860", "380")]
    out = prefer_statute(chunks, "PPC 1860")
    assert [c["statute"] for c in out] == ["PPC 1860", "PPC 1860",
                                           "CrPC 1898", "CrPC 1898", "CrPC 1898"]
    assert len(out) == len(chunks), "preference must never drop a chunk"
    assert {c["chunk_id"] for c in out} == {c["chunk_id"] for c in chunks}


def test_crpc_s221_survives_ppc_preference():
    """s.221 is legitimate material and must remain retrievable, just later."""
    chunks = [chunk("CrPC 1898", "221"), chunk("PPC 1860", "379")]
    out = prefer_statute(chunks, "PPC 1860")
    assert any(c["statute"] == "CrPC 1898" and c["section_number"] == "221" for c in out)


def test_internal_order_is_preserved_in_both_groups():
    chunks = [chunk("CrPC 1898", "1"), chunk("PPC 1860", "a"), chunk("CrPC 1898", "2"),
              chunk("PPC 1860", "b"), chunk("CrPC 1898", "3"), chunk("PPC 1860", "c")]
    out = prefer_statute(chunks, "PPC 1860")
    assert [c["section_number"] for c in out] == ["a", "b", "c", "1", "2", "3"]


def test_no_preference_leaves_order_literally_unchanged():
    chunks = [chunk("CrPC 1898", "221"), chunk("PPC 1860", "379")]
    assert prefer_statute(chunks, None) is chunks
    assert apply_affinity(chunks, "punishment for theft")[0] is chunks


def test_preference_is_a_noop_when_all_or_none_match():
    only_ppc = [chunk("PPC 1860", "379"), chunk("PPC 1860", "380")]
    assert prefer_statute(only_ppc, "PPC 1860") is only_ppc
    no_ppc = [chunk("CrPC 1898", "221")]
    assert prefer_statute(no_ppc, "PPC 1860") is no_ppc


def test_preference_places_target_inside_the_first_eight():
    """The whole point: the grader scores chunks[:8] and PPC 379 sat at 15."""
    from app.ai.nodes.retrieval_grader_node import _MAX_TO_GRADE
    chunks = [chunk("CrPC 1898", str(i)) for i in range(14)] + [chunk("PPC 1860", "379")]
    assert next(i for i, c in enumerate(chunks) if c["statute"] == "PPC 1860") >= _MAX_TO_GRADE
    out = prefer_statute(chunks, "PPC 1860")
    idx = next(i for i, c in enumerate(out) if c["statute"] == "PPC 1860")
    assert idx < _MAX_TO_GRADE, f"PPC 379 at {idx}, outside the graded window"


# ── interaction with the generic topic rules ─────────────────────────────────

def test_unnamed_urban_tenancy_behaviour_is_unchanged():
    """No statute named -> the generic topic rule still governs, untouched."""
    from app.ai.nodes.retrieval_node import _apply_topic_rules
    q = "Can a tenant be evicted without notice in Punjab?"
    chunks = [chunk("Punjab Tenancy Act 1887", "1"),
              chunk("Punjab Rented Premises Act 2009", "2")]
    topic_only = _apply_topic_rules(list(chunks), q)
    after_affinity, named = apply_affinity(list(topic_only), q)
    assert named is None
    assert [c["chunk_id"] for c in after_affinity] == [c["chunk_id"] for c in topic_only]


def test_explicit_statute_overrides_the_generic_topic_rule():
    """Naming the Punjab Tenancy Act must beat the urban-tenancy rule."""
    from app.ai.nodes.retrieval_node import _apply_topic_rules
    q = "Under the Punjab Tenancy Act 1887, can a tenant be evicted without notice?"
    chunks = [chunk("Punjab Rented Premises Act 2009", "2"),
              chunk("Punjab Tenancy Act 1887", "1")]
    ordered = _apply_topic_rules(list(chunks), q)
    ordered, _ = apply_affinity(ordered, q)
    assert ordered[0]["statute"] == "Punjab Tenancy Act 1887"


# ── the grader choke point, driven for real ──────────────────────────────────

@pytest.mark.asyncio
async def test_affinity_survives_grader_reordering(monkeypatch, stub_grader_llm):
    """Grading re-sorts by relevance; without re-application the order is lost.

    The real node runs. The LLM is stubbed at its actual seam — get_fast_llm —
    and the embedding scorer is made deliberately hostile: every CrPC chunk
    scores higher than PPC 379, so a pass cannot come from the scorer agreeing.

    An earlier version of this test patched a name (`_llm_grades`) that does not
    exist, with raising=False, so it patched nothing: the grader's own except
    branch caught the real provider failure and degraded to neutral grades. The
    test passed for a reason unrelated to what it claimed to check. Asserting
    the stub was actually called is what stops that recurring.
    """
    import app.ai.nodes.retrieval_grader_node as g

    chunks = [chunk("CrPC 1898", str(i)) for i in range(10)] + [chunk("PPC 1860", "379")]
    stub = stub_grader_llm(g, monkeypatch, n_grades=g._MAX_TO_GRADE)
    monkeypatch.setattr(
        g, "similarity_scores",
        lambda q, items, ct: [0.0 if c.get("statute") == "PPC 1860" else 0.9 for c in items])

    state = {"query": "punishment for theft under the Pakistan Penal Code",
             "normalized_query": "theft punishment PPC",
             "retrieved_chunks": chunks, "case_type": "criminal", "province": "punjab"}
    out = await g.retrieval_grader_node(state)

    assert stub["calls"] == 1, "grader LLM seam was never exercised"
    ordered = out["reranked_chunks"]
    idx = next(i for i, c in enumerate(ordered) if c.get("statute") == "PPC 1860")
    assert idx == 0, f"PPC 379 landed at {idx} after grading; affinity did not survive"
    assert len(ordered) == len(chunks), "grading must not drop chunks"


# ── D2 invariants must be unaffected ─────────────────────────────────────────

def test_reference_only_still_excluded_and_tables_still_non_citable():
    """Affinity must not resurrect forms or restore a borrowed section number."""
    from langchain_core.documents import Document
    from app.ai.nodes.retrieval_node import _docs_to_chunks
    docs = [
        Document(page_content="warrant form", metadata={
            "chunk_id": "f1", "statute": "CrPC 1898", "section_number": "15",
            "text_kind": "forms", "attribution_status": "misattributed",
            "retrieval_scope": "reference_only"}),
        Document(page_content="schedule row", metadata={
            "chunk_id": "t1", "statute": "CrPC 1898", "section_number": "381",
            "text_kind": "table", "attribution_status": "misattributed",
            "retrieval_scope": "default"}),
        Document(page_content="theft", metadata={
            "chunk_id": "p1", "statute": "PPC 1860", "section_number": "379"}),
    ]
    out, _ = apply_affinity(_docs_to_chunks(docs), "theft under the Pakistan Penal Code")
    ids = [c["chunk_id"] for c in out]
    assert "f1" not in ids, "reference_only leaked back in"
    assert "t1" in ids, "operative table must stay retrievable"
    assert next(c for c in out if c["chunk_id"] == "t1")["section_number"] == ""
    assert ids[0] == "p1", "named statute should lead"
