"""A stated statute is binding on a bail lookup.

`_find` ran a section-only pass unconditionally and ignored `law` entirely, so
it answered from whatever statute happened to carry that section number:

    check("PPC", "20")  ->  PECA 2016 s.20, bailable=True,
                            "This offence is BAILABLE - bail is a matter of right."

with `found: True` and no echo of what was asked, so no caller could detect the
substitution. Telling someone bail is a matter of right, from the wrong Act, is
the most directly harmful output this service produces.

WHY THE OBVIOUS FIX WOULD HAVE BROKEN THINGS
--------------------------------------------
The table stores "CNSA 1997", "ATA 1997", "PECA 2016", but the LLM tool
docstring tells the model to pass bare "CNSA", "ATA", "PECA". Exact-matching on
`law` therefore missed every non-PPC offence -- and the broken fallback was
silently catching those misses and returning the right answer for the wrong
reason. Simply restricting the fallback would have turned three legitimate
query shapes into "not found".

So the fix is two-part, and both halves are pinned here: normalise the statute
name, THEN make it binding.
"""
import pytest

from app.services import bail_checker as b
from app.services.bail_checker import _norm_law


# ── the defect ────────────────────────────────────────────────────────────────

def test_a_penal_code_query_is_not_answered_from_peca():
    """THE regression test. This returned bailable=True from PECA 2016 s.20."""
    r = b.check("PPC", "20", arrested=True)

    assert r["found"] is False
    assert "offence" not in r


def test_the_wrong_statute_never_yields_a_bail_determination():
    """The harmful part was not the miss, it was the confident answer."""
    r = b.check("PPC", "20", arrested=True)

    assert "BAILABLE" not in r["guidance"]["summary"].upper()
    assert "matter of right" not in r["guidance"]["summary"].lower()


@pytest.mark.parametrize("law,section,wrong_law", [
    ("PPC", "20", "PECA 2016"),      # would have said bailable=True
    ("PPC", "7", "ATA 1997"),        # would have said terrorism
    ("PECA 2016", "302", "PPC"),     # would have said murder + prohibitory
    ("ATA 1997", "379", "PPC"),      # would have said theft
])
def test_no_cross_statute_substitution(law, section, wrong_law):
    r = b.check(law, section, arrested=True)

    assert r["found"] is False, f"{law} s.{section} was answered from {wrong_law}"


def test_the_query_is_echoed_so_a_caller_can_see_what_was_asked():
    r = b.check("PPC", "20", arrested=True)

    assert r["query"] == {"law": "PPC", "section": "20"}


# ── the half that keeps legitimate queries working ───────────────────────────

@pytest.mark.parametrize("law,section,expect_law", [
    ("CNSA", "9(c)", "CNSA 1997"),
    ("ATA", "7", "ATA 1997"),
    ("PECA", "20", "PECA 2016"),
    ("CNSA 1997", "9(c)", "CNSA 1997"),
    ("cnsa, 1997", "9(c)", "CNSA 1997"),
    ("Pakistan Penal Code", "302", "PPC"),
    ("PPC", "302", "PPC"),
])
def test_statute_names_the_callers_actually_send_still_resolve(law, section, expect_law):
    """The LLM tool docstring tells the model to pass bare "CNSA"/"ATA"/"PECA".
    Every one of these went through the broken fallback before."""
    r = b.check(law, section, arrested=True)

    assert r["found"] is True, f"{law} s.{section} regressed to not-found"
    assert r["offence"]["law"] == expect_law


def test_a_bare_section_with_no_statute_still_resolves():
    """The case the fallback was actually for, and which test_bail.py relies on."""
    r = b.check("", "302", arrested=True)

    assert r["found"] is True
    assert r["offence"]["section"] == "302"


def test_law_normalisation_is_year_insensitive():
    assert _norm_law("CNSA") == _norm_law("CNSA 1997") == "CNSA 1997"
    assert _norm_law("ATA") == _norm_law("ATA 1997") == "ATA 1997"
    assert _norm_law("") == ""


def test_every_stored_law_normalises_to_itself():
    """Otherwise an offence becomes unreachable by its own recorded name."""
    for o in b.OFFENCES:
        assert _norm_law(o["law"]) == o["law"], f"{o['law']!r} does not round-trip"


# ── the correction, instead of a dead end ────────────────────────────────────

def test_a_mismatch_names_the_statute_that_does_carry_the_section():
    """A flat "not found" would imply the section does not exist. It usually
    does -- under another Act, which is the confusion that caused the bug."""
    r = b.check("PPC", "20", arrested=True)

    assert r["section_found_under"] == [
        {"law": "PECA 2016", "section": "20",
         "title": "Offences against the dignity of a person (online)"}
    ]
    assert "PECA 2016" in r["guidance"]["summary"]


def test_the_pointer_carries_no_bail_classification():
    """It must not become a determination by the back door."""
    r = b.check("PPC", "20", arrested=True)

    for entry in r["section_found_under"]:
        assert set(entry) == {"law", "section", "title"}
        assert "bailable" not in entry


def test_a_section_in_no_statute_has_no_pointer():
    r = b.check("PPC", "999-Z", arrested=True)

    assert r["found"] is False
    assert r["section_found_under"] == []


def test_a_bare_section_lookup_does_not_produce_a_pointer():
    """No statute was stated, so there is no mismatch to correct."""
    r = b.check("", "999-Z", arrested=True)

    assert r["section_found_under"] == []


def test_the_refusal_still_carries_the_standard_disclosure():
    r = b.check("PPC", "20", arrested=True)

    for key in ("general_rule", "legal_basis", "effective_as_of", "verify", "disclaimer"):
        assert key in r
