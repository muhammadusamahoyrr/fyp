"""Bail-checker tests.

Converted from a hand-rolled PASS/FAIL script to pytest. The script's assertions
are preserved one-for-one; it simply was not collectable, so nothing re-ran it
when bail_checker.py changed.
"""
import pytest

from app.services import bail_checker


# ── search ────────────────────────────────────────────────────────────────────

def test_empty_query_returns_nothing():
    assert bail_checker.search("") == []


def test_section_number_ranks_first():
    hits = bail_checker.search("302")
    assert hits
    assert hits[0]["section"] == "302"
    assert hits[0]["law"] == "PPC"


def test_results_carry_an_id():
    assert all("id" in o for o in bail_checker.search("302"))


def test_title_search_finds_murder():
    assert any(o["section"] == "302" for o in bail_checker.search("murder"))


def test_cheque_finds_489f():
    assert bail_checker.search("cheque")[0]["section"] == "489-F"


def test_limit_is_respected():
    assert len(bail_checker.search("theft", limit=1)) == 1


def test_aliases_are_never_exposed_in_results():
    """`aliases` is a search aid, not part of the legal record — it must not reach
    an API response or an LLM prompt as though it were content."""
    assert all("aliases" not in o for o in bail_checker.search("theft"))


# ── check(): bailable ─────────────────────────────────────────────────────────

def test_bailable_offence_is_a_matter_of_right():
    r = bail_checker.check("PPC", "337-A(i)", arrested=True)
    assert r["found"] is True
    assert r["offence"]["bailable"] is True
    assert "right" in r["guidance"]["summary"].lower()
    assert "CrPC s.496" in r["guidance"]["sections"]


# ── check(): non-bailable, pre vs post arrest ─────────────────────────────────

def test_not_yet_arrested_routes_to_pre_arrest_bail():
    r = bail_checker.check("PPC", "420", arrested=False)
    assert r["found"] is True
    assert "CrPC s.498" in r["guidance"]["sections"]


def test_arrested_routes_to_post_arrest_bail():
    r = bail_checker.check("PPC", "420", arrested=True)
    assert "CrPC s.497" in r["guidance"]["sections"]


# ── check(): prohibitory clause ───────────────────────────────────────────────

def test_murder_is_flagged_prohibitory():
    r = bail_checker.check("PPC", "302", arrested=True)
    assert r["offence"]["prohibitory"] is True
    steps = " ".join(r["guidance"]["steps"]).lower()
    assert "prohibitory" in steps
    # Bail under the prohibitory clause is DISCRETIONARY, not barred. Saying
    # otherwise would tell a user their case is hopeless when it is not.
    assert "discretion" in steps


# ── check(): normalisation ────────────────────────────────────────────────────

def test_section_only_lookup_without_law():
    r = bail_checker.check("", "302", arrested=True)
    assert r["found"] is True
    assert r["offence"]["section"] == "302"


def test_surrounding_whitespace_is_normalised():
    r = bail_checker.check("PPC", "  489-F  ", arrested=True)
    assert r["found"] is True
    assert r["offence"]["section"] == "489-F"


# ── check(): not found ────────────────────────────────────────────────────────

def test_unknown_section_falls_back_to_general_rule():
    r = bail_checker.check("PPC", "999-Z", arrested=True)
    assert r["found"] is False
    assert "general_rule" in r
    assert r["disclaimer"]


def test_check_carries_disclaimer_basis_and_confidence():
    r = bail_checker.check("PPC", "337-A(i)", arrested=True)
    assert r["disclaimer"]
    assert r["legal_basis"]
    assert "confidence" in r


# ── general_rule ──────────────────────────────────────────────────────────────

def test_over_three_years_is_generally_non_bailable():
    assert "NON-BAILABLE" in bail_checker.general_rule(7)["text"]


def test_three_years_or_less_is_often_bailable():
    assert "BAILABLE" in bail_checker.general_rule(2)["text"]


# ── aliases (added when the colloquial-lookup gap was fixed) ──────────────────

@pytest.mark.parametrize(
    ("query", "section"),
    [
        ("qatl-e-amd", "302"),   # the common spelling; the title says "qatl-i-amd"
        ("qatl e amd", "302"),   # punctuation folding
        ("chori", "379"),
        ("dhoka", "420"),
        ("cheque bounce", "489-F"),
        ("daka", "396"),
        ("dhamki", "506"),
        ("marpeet", "337-A(i)"),
    ],
)
def test_colloquial_and_urdu_aliases_resolve(query, section):
    hits = bail_checker.search(query)
    assert hits, f"{query!r} matched nothing"
    assert hits[0]["section"] == section


def test_ambiguous_word_returns_every_candidate_section():
    """'fraud' is not a section. It could be s.420 (cheating), s.406 (breach of
    trust) or s.468 (forgery) — all three must surface so the ambiguity reaches
    the user instead of being silently resolved into one wrong section."""
    sections = {h["section"] for h in bail_checker.search("fraud")}
    assert {"406", "420", "468"} <= sections


def test_ambiguous_candidates_tie_on_relevance():
    """The tie is what the tool layer uses to decide whether to ask the user."""
    hits = bail_checker.search("fraud")
    top = max(h["relevance"] for h in hits)
    tied = {h["section"] for h in hits if h["relevance"] == top}
    assert tied == {"406", "420", "468"}


def test_decisive_hit_does_not_tie():
    """'qatl-e-amd' hits s.302 decisively; s.324 shares the word but scores lower,
    so the tool must NOT hedge on a question it can answer cleanly."""
    hits = bail_checker.search("qatl-e-amd")
    top = max(h["relevance"] for h in hits)
    tied = [h for h in hits if h["relevance"] == top]
    assert len(tied) == 1
    assert tied[0]["section"] == "302"


def test_section_number_still_outranks_word_matches():
    """Regression: aliases must not let a word match beat an explicit section."""
    assert bail_checker.search("302")[0]["section"] == "302"
    assert bail_checker.search("420")[0]["section"] == "420"


def test_non_criminal_terms_still_match_nothing():
    for q in ("khula", "divorce", "court fee"):
        assert bail_checker.search(q) == [], f"{q!r} should not match an offence"


@pytest.mark.parametrize("query", [
    "zzz not an offence zzz",
    "hello there my friend",
    "an",
    "is it ok",
])
def test_stopwords_do_not_produce_phantom_offences(query):
    """Regression. Matching used to be substring-based, so the token "an" hit
    inside "wom(an)'s modesty" and "Cheating (an)d ...". Any sentence containing a
    stopword therefore returned unrelated offences at low relevance — and a junk
    candidate is one the model can go on to act on. Matching is now whole-word
    with a minimum token length."""
    assert bail_checker.search(query) == [], f"{query!r} produced phantom matches"


def test_every_offence_has_aliases_and_required_fields():
    required = ("law", "section", "title", "punishment", "cognizable",
                "bailable", "compoundable", "court", "confidence")
    for o in bail_checker.OFFENCES:
        missing = [k for k in required if k not in o]
        assert not missing, f"s.{o.get('section')} missing {missing}"
        assert o.get("aliases"), f"s.{o.get('section')} has no aliases"
