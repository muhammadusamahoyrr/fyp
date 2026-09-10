"""Binding an intake analysis to its evidence. Pure, offline, no model.

THE DISTINCTION THIS FILE EXISTS FOR

The chat path can only say `unresolved` when a citation does not tie to a
source, and that one label covers two completely different events:

    the model cited something it was never shown   → a hallucination
    the parser did not understand the phrasing     → a tooling gap

For a legal product those must not share a name. Intake's output is structured,
so the model can name the evidence id it used and the two become separable with
certainty — `phantom` and `mismatched` are findings, `textual` is a fallback.

Everything here is deterministic. That is the point: on a CPU-only deployment
an offline test is the only kind that can be run often enough to be worth
having, and citation verification is exactly the part that should never have
needed a model.
"""
from __future__ import annotations

import pytest

from app.ai.intake_evidence import (
    BIND_ID,
    BIND_NONE,
    BIND_TEXTUAL,
    STATUS_BOUND,
    STATUS_MISMATCHED,
    STATUS_PHANTOM,
    STATUS_TEXTUAL,
    STATUS_UNBOUND,
    bind_intake_citations,
    bind_textually,
    build_intake_claims,
    render_applicable_laws,
    render_recommended_actions,
    summarise_binding,
)


def _evidence() -> list[dict]:
    """Two statute entries, shaped exactly as build_generation_evidence emits."""
    return [
        {"id": "1", "kind": "statute", "statute": "PPC", "section": "302",
         "chunk_id": "chunk-a", "source": "ppc.pdf", "province": "federal",
         "content": "Punishment for qatl-i-amd."},
        {"id": "2", "kind": "statute", "statute": "CrPC", "section": "154",
         "chunk_id": "chunk-b", "source": "crpc.pdf", "province": "federal",
         "content": "Information in cognizable cases."},
        {"id": "3", "kind": "judgment", "statute": "2019 SCMR 1", "section": "",
         "chunk_id": "j-1", "source": "http://x/j.pdf", "content": "…"},
    ]


# ── the three outcomes that used to be one ──────────────────────────────────

def test_a_real_id_with_a_matching_section_binds():
    citations, mode = bind_intake_citations(
        [{"evidence_id": "1", "statute": "PPC", "section": "302", "note": "murder"}],
        _evidence(),
    )
    assert mode == BIND_ID
    assert citations[0]["status"] == STATUS_BOUND
    assert citations[0]["chunk_id"] == "chunk-a"


def test_an_id_that_was_never_in_the_evidence_is_a_phantom():
    """A hallucinated citation, caught with certainty.

    The old free-text field could not express this at all: the string was
    parsed, failed to resolve, and looked exactly like a phrasing the regex did
    not know.
    """
    citations, mode = bind_intake_citations(
        [{"evidence_id": "9", "statute": "PPC", "section": "302"}],
        _evidence(),
    )
    assert citations[0]["status"] == STATUS_PHANTOM
    assert mode == BIND_ID


def test_a_real_id_quoting_the_wrong_section_is_mismatched():
    """Distinct from a phantom because the fix is different.

    The model had this chunk in front of it and misread which section it was.
    That is a different failure from inventing a source, and collapsing them
    would hide which one happened.
    """
    citations, _ = bind_intake_citations(
        [{"evidence_id": "1", "statute": "PPC", "section": "420"}],
        _evidence(),
    )
    assert citations[0]["status"] == STATUS_MISMATCHED


def test_phantom_and_mismatched_are_not_the_same_label():
    ev = _evidence()
    phantom, _ = bind_intake_citations([{"evidence_id": "9", "section": "302"}], ev)
    mismatch, _ = bind_intake_citations(
        [{"evidence_id": "1", "section": "420"}], ev)
    assert phantom[0]["status"] != mismatch[0]["status"]


def test_a_citation_with_no_id_at_all_is_unbound():
    citations, mode = bind_intake_citations(
        [{"statute": "PPC", "section": "302"}], _evidence())
    assert citations[0]["status"] == STATUS_UNBOUND
    assert mode == BIND_NONE


def test_section_comparison_ignores_spacing_and_case():
    citations, _ = bind_intake_citations(
        [{"evidence_id": "2", "statute": "CrPC", "section": " 154 "}], _evidence())
    assert citations[0]["status"] == STATUS_BOUND


def test_a_citation_naming_no_section_binds_on_the_id_alone():
    citations, _ = bind_intake_citations(
        [{"evidence_id": "1", "statute": "PPC", "section": ""}], _evidence())
    assert citations[0]["status"] == STATUS_BOUND


def test_judgments_are_not_offered_as_statute_evidence():
    """`id: 3` is a judgment. Binding a statute citation to it is a phantom."""
    citations, _ = bind_intake_citations(
        [{"evidence_id": "3", "statute": "PPC", "section": "302"}], _evidence())
    assert citations[0]["status"] == STATUS_PHANTOM


def test_no_citations_at_all():
    citations, mode = bind_intake_citations([], _evidence())
    assert citations == []
    assert mode == BIND_NONE


def test_empty_evidence_makes_every_id_a_phantom():
    citations, _ = bind_intake_citations(
        [{"evidence_id": "1", "statute": "PPC", "section": "302"}], [])
    assert citations[0]["status"] == STATUS_PHANTOM


# ── the textual fallback ────────────────────────────────────────────────────

def test_textual_binding_resolves_against_the_same_evidence():
    """A provider that ignored the id contract degrades to today's behaviour.

    Not to a wall of phantoms — that would report a tooling gap as a
    hallucination, which is the exact confusion this design removes.
    """
    citations, mode = bind_textually(
        "PPC Section 302 — punishment for murder", _evidence())
    assert mode == BIND_TEXTUAL
    assert citations[0]["status"] == STATUS_TEXTUAL
    assert citations[0]["chunk_id"] == "chunk-a"


def test_textual_binding_marks_what_it_could_not_resolve():
    citations, _ = bind_textually("PPC Section 999", _evidence())
    assert citations[0]["status"] == STATUS_UNBOUND


def test_textual_binding_never_claims_id_level_binding():
    citations, _ = bind_textually("PPC Section 302", _evidence())
    assert all(c["binding"] == BIND_TEXTUAL for c in citations)


# ── claims are built from STRUCTURE, not from sentence splitting ────────────

def test_each_action_becomes_one_claim():
    citations, _ = bind_intake_citations(
        [{"evidence_id": "1", "statute": "PPC", "section": "302"}], _evidence())
    claims = build_intake_claims(
        "A murder case.",
        [{"text": "File an FIR", "evidence_ids": ["1"]},
         {"text": "Engage counsel", "evidence_ids": []}],
        citations,
        _evidence(),
    )
    assert [c["kind"] for c in claims] == ["summary", "action", "action"]
    assert [c["index"] for c in claims] == [1, 2, 3]


def test_the_summary_is_judged_too():
    """It asserts the client's legal position and used to go unchecked.

    The verdict covered recommended_actions alone and was then stamped on the
    whole analysis, summary included.
    """
    citations, _ = bind_intake_citations(
        [{"evidence_id": "1", "statute": "PPC", "section": "302"}], _evidence())
    claims = build_intake_claims("A murder case.", [], citations, _evidence())
    assert claims[0]["kind"] == "summary"
    assert claims[0]["citation_status"] == "matched"


def test_an_action_naming_an_id_that_does_not_exist_is_not_checkable():
    citations, _ = bind_intake_citations(
        [{"evidence_id": "9", "statute": "PPC", "section": "302"}], _evidence())
    claims = build_intake_claims(
        "…", [{"text": "File an FIR", "evidence_ids": ["9"]}], citations, _evidence())
    action = [c for c in claims if c["kind"] == "action"][0]
    assert action["citation_status"] == "unresolved"


def test_an_action_citing_nothing_is_not_checkable():
    citations, _ = bind_intake_citations(
        [{"evidence_id": "1", "statute": "PPC", "section": "302"}], _evidence())
    claims = build_intake_claims(
        "…", [{"text": "Keep records", "evidence_ids": []}], citations, _evidence())
    action = [c for c in claims if c["kind"] == "action"][0]
    assert action["citation_status"] == "unresolved"


def test_claims_are_shaped_for_the_reused_helpers():
    """`parse_claim_support` and `grounding_veto` are reused UNCHANGED."""
    from app.ai.answer_citations import grounding_veto, parse_claim_support

    citations, _ = bind_intake_citations(
        [{"evidence_id": "1", "statute": "PPC", "section": "302"}], _evidence())
    claims = build_intake_claims(
        "A murder case.", [{"text": "File an FIR", "evidence_ids": ["1"]}],
        citations, _evidence())

    assessed = parse_claim_support("1:supported,2:supported", claims)
    assert [c["support"] for c in assessed] == ["supported", "supported"]
    assert grounding_veto(assessed) is None


def test_the_veto_fires_when_a_bound_claim_is_unsupported():
    from app.ai.answer_citations import grounding_veto, parse_claim_support

    citations, _ = bind_intake_citations(
        [{"evidence_id": "1", "statute": "PPC", "section": "302"}], _evidence())
    claims = build_intake_claims(
        "A murder case.", [{"text": "File an FIR", "evidence_ids": ["1"]}],
        citations, _evidence())

    assessed = parse_claim_support("1:supported,2:unsupported", claims)
    assert grounding_veto(assessed) is not None


def test_an_unparseable_verdict_leaves_claims_unassessed_and_vetoes():
    """A missing verdict is not evidence of support."""
    from app.ai.answer_citations import grounding_veto, parse_claim_support

    citations, _ = bind_intake_citations(
        [{"evidence_id": "1", "statute": "PPC", "section": "302"}], _evidence())
    claims = build_intake_claims("A murder case.", [], citations, _evidence())
    assessed = parse_claim_support("garbage", claims)
    assert all(c["support"] == "unassessed" for c in assessed)
    assert grounding_veto(assessed) is not None


# ── display-string compatibility ────────────────────────────────────────────

def test_applicable_laws_renders_the_familiar_shape():
    """The print view and text export read this field directly and unchanged."""
    citations, _ = bind_intake_citations(
        [{"evidence_id": "1", "statute": "PPC", "section": "302",
          "note": "Punishment for murder"}],
        _evidence(),
    )
    assert render_applicable_laws(citations) == [
        "PPC Section 302 — Punishment for murder"]


def test_an_unverified_citation_is_marked_not_dropped():
    """Silently removing it would leave a shorter list and no reason to doubt
    what remains — and the entries most worth doubting are the ones that would
    disappear."""
    citations, _ = bind_intake_citations(
        [{"evidence_id": "9", "statute": "PPC", "section": "302", "note": "murder"}],
        _evidence(),
    )
    rendered = render_applicable_laws(citations)
    assert len(rendered) == 1
    assert "[unverified citation]" in rendered[0]


def test_display_strings_are_plain_strings():
    citations, _ = bind_intake_citations(
        [{"evidence_id": "1", "statute": "PPC", "section": "302"}], _evidence())
    assert all(isinstance(x, str) for x in render_applicable_laws(citations))


def test_recommended_actions_render_as_before():
    assert render_recommended_actions(
        [{"text": "File an FIR", "evidence_ids": ["1"]}, {"text": "Engage counsel"}]
    ) == ["File an FIR", "Engage counsel"]


def test_recommended_actions_tolerate_legacy_plain_strings():
    """An older record, or a provider that returned bare strings."""
    assert render_recommended_actions(["File an FIR"]) == ["File an FIR"]


def test_empty_entries_are_skipped_not_rendered_blank():
    assert render_recommended_actions([{"text": "  "}, {"text": "Real"}]) == ["Real"]
    assert render_applicable_laws([{"statute": "", "section": ""}]) == []


# ── the summary counters ────────────────────────────────────────────────────

def test_binding_summary_counts_each_outcome():
    citations, _ = bind_intake_citations(
        [{"evidence_id": "1", "section": "302"},
         {"evidence_id": "9", "section": "302"},
         {"evidence_id": "2", "section": "999"}],
        _evidence(),
    )
    summary = summarise_binding(citations)
    assert summary[STATUS_BOUND] == 1
    assert summary[STATUS_PHANTOM] == 1
    assert summary[STATUS_MISMATCHED] == 1
    assert summary["untrustworthy"] == 2
    assert summary["total"] == 3


def test_a_clean_set_reports_nothing_untrustworthy():
    citations, _ = bind_intake_citations(
        [{"evidence_id": "1", "section": "302"}], _evidence())
    assert summarise_binding(citations)["untrustworthy"] == 0


@pytest.mark.parametrize("bad", [None, [], [{}]])
def test_binding_never_raises_on_junk(bad):
    citations, mode = bind_intake_citations(bad, _evidence())
    assert isinstance(citations, list)
    assert mode in {BIND_ID, BIND_NONE, BIND_TEXTUAL}
