"""A "grounded" verdict must agree with the claim assessment behind it.

The grounding judge returns two things in one call: a single `is_grounded`
boolean and a per-claim support string. `hallucination_node` used the boolean
and discarded the claims — so an answer could be published as grounded while
its own assessment recorded that the cited section does not support what the
sentence claims. Both halves came from the same model, and the one the user was
shown was the one nobody checked against the other.

The veto is deterministic and one-directional: it can withdraw a claim of
groundedness, never grant one. That matters because it runs on legal answers —
a check that can only make the system more cautious cannot itself become a way
for an unsupported answer to be published.

Pure. No model is called in this file.
"""
import pytest

from app.ai.answer_citations import grounding_veto


def claim(support, *, status="matched", index=1):
    return {"index": index, "citation_status": status, "support": support,
            "text": f"claim {index}", "source_ids": ["1"]}


# ══════════════════════════════════════════════════════════════════════════════
# Rule 1 — a claim the judge said is unsupported
# ══════════════════════════════════════════════════════════════════════════════

def test_one_unsupported_claim_vetoes_the_answer():
    """There is no reading of "grounded" that survives the judge having read
    the cited section and said it does not carry the claim."""
    veto = grounding_veto([claim("supported", index=1),
                           claim("unsupported", index=2)])
    assert veto is not None
    assert "1 of 2" in veto


def test_the_veto_names_how_many_claims_failed():
    veto = grounding_veto([claim("unsupported", index=1),
                           claim("unsupported", index=2),
                           claim("supported", index=3)])
    assert "2 of 3" in veto


# ══════════════════════════════════════════════════════════════════════════════
# Rule 2 — a verdict that cannot name a single supported claim
# ══════════════════════════════════════════════════════════════════════════════

def test_an_all_partial_assessment_vetoes():
    """Grounded, with not one claim the judge would positively stand behind, is
    a default rather than a judgement."""
    assert grounding_veto([claim("partial"), claim("partial", index=2)])


def test_an_all_unassessed_assessment_vetoes():
    """This is also what an unparseable verdict string looks like. A missing
    verdict is not evidence of support."""
    assert grounding_veto([claim("unassessed"), claim("unassessed", index=2)])


def test_one_supported_claim_among_partials_is_allowed():
    """`partial` alone must NOT veto. A sentence the cited section carries in
    part is ordinary legal writing, and marking those answers ungrounded would
    train users to ignore the caution — a warning nobody reads protects
    nobody."""
    assert grounding_veto([claim("supported"), claim("partial", index=2)]) is None


# ══════════════════════════════════════════════════════════════════════════════
# Only claims that were actually checked can veto
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("status", ["unresolved", "retrieved", ""])
def test_an_unmatched_claim_cannot_trigger_the_unsupported_rule(status):
    """Rule 1 counts only claims that were CHECKED.

    A claim whose citation never resolved was never read against a source, so
    however the judge labelled it, that label is not evidence the source
    contradicts it. Vetoing on rule 1 here would mark an answer ungrounded
    because of a verdict on something nobody looked at.

    It can still fall to rule 3 — see the section below — but that is a
    different statement: not "the source disagrees" but "there is no source"."""
    assessment = [claim("unsupported", status=status),
                  claim("supported", index=2)]
    assert grounding_veto(assessment) is None


def test_an_answer_with_no_matched_claims_is_left_alone():
    """Nothing was checked, so this function has nothing to say. The judge's
    own verdict stands or falls on its own."""
    assert grounding_veto([]) is None
    assert grounding_veto(None) is None


def test_unmatched_claims_are_excluded_from_the_count():
    """The denominator is what was CHECKED, not what was written — otherwise
    the message understates how much of the checked material failed."""
    veto = grounding_veto([
        claim("unsupported", index=1),
        claim("supported", index=2),
        claim("unsupported", status="unresolved", index=3),
    ])
    assert "1 of 2" in veto


# ══════════════════════════════════════════════════════════════════════════════
# The direction of the check
# ══════════════════════════════════════════════════════════════════════════════

def test_a_fully_supported_assessment_does_not_veto():
    assert grounding_veto([claim("supported"), claim("supported", index=2)]) is None


def test_the_veto_is_deterministic():
    """It is an internal-consistency check on a verdict already given, not a
    second opinion about the law. The same assessment must always produce the
    same result."""
    assessment = [claim("supported"), claim("partial", index=2),
                  claim("unsupported", index=3)]
    results = {grounding_veto([dict(c) for c in assessment]) for _ in range(20)}
    assert len(results) == 1


def test_the_node_withdraws_a_grounded_verdict_the_claims_contradict():
    """The wiring, not just the rule. Asserted on the source because reaching
    this branch for real needs a model call, and the property — that the
    boolean is no longer used alone — is what regresses silently."""
    import inspect

    import app.ai.nodes.hallucination_node as node

    source = inspect.getsource(node.hallucination_node)
    assert "grounding_veto(assessed)" in source, (
        "the node no longer consults the claim assessment")
    assert "if result.is_grounded and veto is None:" in source, (
        "the grounded branch was taken on the judge's boolean alone")


# ══════════════════════════════════════════════════════════════════════════════
# Rule 3 — an answer that cited only things that do not exist
# ══════════════════════════════════════════════════════════════════════════════
#
# THE POLICY, STATED SO IT CAN BE ARGUED WITH
#
# An answer may be published as grounded with NO claims at all — it asserted
# nothing on a source's authority, so there was nothing to check and the judge's
# own verdict is the only thing available.
#
# An answer may NOT be published as grounded when it made citation-bearing
# claims and not one citation resolved. It named chapter and verse; none of it
# corresponds to anything in the evidence the model was handed. "Grounded"
# asserts that a check succeeded, and no check could have happened. This is the
# fabricated-citation failure, and it is the one that reads most authoritative
# to a user who cannot verify it.

def unresolved(index=1):
    return {"index": index, "citation_status": "unresolved",
            "support": "unassessed", "text": f"claim {index}", "source_ids": []}


def test_an_answer_whose_every_citation_is_unresolved_cannot_be_grounded():
    veto = grounding_veto([unresolved(1), unresolved(2), unresolved(3)])
    assert veto is not None, (
        "an answer citing three sources, none of which exist, was publishable "
        "as grounded")
    assert "none of the 3" in veto


def test_one_resolved_citation_is_enough_to_leave_the_verdict_alone():
    """The rule is "not one resolved", not "most resolved". An answer that
    cites four sections and gets three wrong is a different problem, and it is
    the judge's to weigh — vetoing it here would be this function deciding how
    much wrongness is too much, which it has no basis for."""
    assert grounding_veto([unresolved(1), unresolved(2),
                           claim("supported", index=3)]) is None


def test_an_answer_with_no_claims_at_all_is_left_to_the_judge():
    """The deliberate exception, and the reason rule 3 is phrased as it is.

    No claims means the answer made no assertion on a source's authority —
    "you should consult a lawyer", a refusal, a clarifying reply. There is
    nothing to verify because nothing was claimed, and vetoing every such answer
    would mark the system's most cautious outputs as ungrounded."""
    assert grounding_veto([]) is None
    assert grounding_veto(None) is None


def test_high_confidence_cannot_survive_wholly_unverifiable_evidence():
    """The property the policy exists for, checked end to end through the node's
    own logic: veto set means the ungrounded branch, which halves confidence and
    appends the caution. A grounded verdict at 0.9 over nothing checkable is the
    exact failure this system has already shipped once."""
    import inspect

    import app.ai.nodes.hallucination_node as node

    source = inspect.getsource(node.hallucination_node)
    # The veto is consulted, and a set veto forces the degraded path.
    assert "veto = grounding_veto(assessed)" in source
    assert "if result.is_grounded and veto is None:" in source
    assert "degraded_conf" in source.split("if result.is_grounded and veto is None:")[1]
