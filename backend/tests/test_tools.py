"""Tool-layer tests — the skills the chat model can call.

These are the adapters that let the LLM reach the deterministic legal engines, so
the things worth pinning down are: the schemas the model sees, the gate that
decides whether we pay for a tool step at all, and — most importantly — that a
tool FAILS by returning an error rather than raising (a raised exception kills
the graph run; a returned error lets the model recover or ask the user).

No LLM is involved here: tools are invoked directly.
"""
import pytest

from app.ai.tools import LEGAL_TOOLS, TOOLS_BY_NAME, should_offer_tools
from app.ai.tools.legal_tools import (
    calculate_court_fee,
    check_bail_eligibility,
    compute_inheritance_shares,
    find_offence_sections,
)


# ── registry ──────────────────────────────────────────────────────────────────

def test_expected_tools_are_registered():
    assert set(TOOLS_BY_NAME) == {
        "find_offence_sections",
        "check_bail_eligibility",
        "calculate_court_fee",
        "compute_inheritance_shares",
        "search_case_law",
    }


def test_every_tool_has_a_description():
    """The docstring IS the spec the model reads. An undescribed tool is unusable."""
    for tool in LEGAL_TOOLS:
        assert tool.description and len(tool.description) > 40, tool.name


def test_tool_arg_schemas():
    assert set(TOOLS_BY_NAME["check_bail_eligibility"].args) == {"law", "section", "arrested"}
    assert set(TOOLS_BY_NAME["calculate_court_fee"].args) == {
        "claim_value", "suit_type", "province", "court_level"}


# ── the cost gate ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "am I eligible for bail on a theft charge",
    "my father died leaving a wife, 2 sons and a daughter",
    "court fee for a money recovery suit",
    "Fee for a specific performance suit valued at Rs 2000000",
    "any precedent on maintenance of an adult daughter",
])
def test_gate_fires_when_a_tool_could_apply(query):
    assert should_offer_tools(query) is True


@pytest.mark.parametrize("query", [
    "what is khula and how do I apply",
    # Word-boundary regressions. Substring matching used to fire "fir" inside
    # "first"/"confirm" and "share" inside "shareholder", burning a model call on
    # every one of these.
    "the first hearing is tomorrow, what will happen",
    "please confirm my lawyer will attend",
    "I am a shareholder in a company",
])
def test_gate_stays_shut_when_no_tool_applies(query):
    assert should_offer_tools(query) is False


# ── offence lookup ────────────────────────────────────────────────────────────

def test_find_offence_sections_is_decisive_on_a_clear_hit():
    r = find_offence_sections.invoke({"query": "qatl-e-amd"})
    assert r["ambiguous"] is False
    assert r["matches"][0]["section"] == "302"


def test_find_offence_sections_flags_a_genuine_ambiguity():
    r = find_offence_sections.invoke({"query": "fraud"})
    assert r["ambiguous"] is True
    assert {m["section"] for m in r["matches"]} == {"406", "420", "468"}
    assert "FIR" in r["note"]


def test_find_offence_sections_never_leaks_a_bail_verdict():
    """This tool IDENTIFIES an offence; it must not adjudicate bail. If `bailable`
    appears here the model reads it, thinks it is done, and never calls
    check_bail_eligibility — so the user loses the actual guidance."""
    r = find_offence_sections.invoke({"query": "theft"})
    for match in r["matches"]:
        assert "bailable" not in match
        assert "prohibitory" not in match


def test_find_offence_sections_returns_an_error_rather_than_guessing():
    r = find_offence_sections.invoke({"query": "zzz not an offence zzz"})
    assert "error" in r
    assert "matches" not in r


# ── bail ──────────────────────────────────────────────────────────────────────

def test_check_bail_eligibility_known_arrest_status():
    r = check_bail_eligibility.invoke({"law": "PPC", "section": "379", "arrested": True})
    assert r["found"] is True
    assert "CrPC s.497" in r["guidance"]["sections"]


def test_check_bail_eligibility_returns_both_routes_when_arrest_status_unknown():
    """s.497 (post-arrest) vs s.498 (pre-arrest) is the whole practical answer.
    Guessing it produces confidently wrong advice, and refusing to answer is
    unhelpful — so an omitted `arrested` yields BOTH routes."""
    r = check_bail_eligibility.invoke({"law": "PPC", "section": "379"})
    guidance = r["guidance"]
    assert "if_already_arrested" in guidance
    assert "if_not_yet_arrested" in guidance
    assert "CrPC s.497" in guidance["if_already_arrested"]["sections"]
    assert "CrPC s.498" in guidance["if_not_yet_arrested"]["sections"]


def test_check_bail_eligibility_unknown_section_does_not_raise():
    r = check_bail_eligibility.invoke({"law": "PPC", "section": "999-Z", "arrested": True})
    assert r["found"] is False


# ── court fee ─────────────────────────────────────────────────────────────────

def test_calculate_court_fee_matches_the_engine():
    r = calculate_court_fee.invoke({
        "claim_value": 500_000, "suit_type": "money_recovery", "province": "punjab"})
    assert r["court_fee"] == 37_500
    assert r["verify"]


# ── inheritance ───────────────────────────────────────────────────────────────

def test_compute_inheritance_shares_accepts_the_nested_heirs_schema():
    r = compute_inheritance_shares.invoke({
        "estate_value": 10_000_000,
        "heirs": {"wives": 1, "sons": 2, "daughters": 1},
    })
    assert r["estate_value"] == 10_000_000
    assert r["breakdown"]


def test_compute_inheritance_shares_returns_contradiction_as_an_error():
    """A deceased cannot leave both a husband and wives. The engine raises
    ValueError; the tool must convert it into something the model can relay and
    retry, not let it escape and kill the graph run."""
    r = compute_inheritance_shares.invoke({
        "estate_value": 100_000,
        "heirs": {"husband": 1, "wives": 1},
    })
    assert "error" in r
    assert "hint" in r
