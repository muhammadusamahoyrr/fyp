"""The four first-page layouts a case title can arrive in.

WHY THIS FILE EXISTS
--------------------
73 judgments reached the corpus with no title. Nothing failed: they were
retrieved and ranked correctly, and simply displayed as a bare neutral id with
no indication of who the parties were. The parser recognised only one layout --
"Versus" alone on a line -- which is what reported-judgment PDFs use. Order
sheets and judgment sheets use three others.

_parse_title now tries all four in order, and order is load-bearing: the
stacked branch must stay first and must keep returning exactly what it always
returned, or re-ingesting a judgment silently rewrites a title that was never
wrong. Nothing but these tests holds that in place.

The fixtures are trimmed from real documents in the corpus; the id in each
docstring is the judgment the layout was found on.
"""
from __future__ import annotations

from app.services.citator_service import _parse_title, parse_metadata


def test_versus_alone_on_a_line_is_unchanged():
    """The original layout, and the one every existing title came from.

    The trailing period is retained deliberately. This branch predates the
    others and its output is byte-for-byte what it always produced -- the
    cleanup applied to the newer layouts must not reach back into it.
    """
    head = (
        "IN THE LAHORE HIGH COURT\n"
        "Writ Petition No. 100 of 2026\n"
        "\n"
        "Ahmad Ali\n"
        "Versus\n"
        "The State.\n"
        "JUDGMENT\n"
    )
    assert _parse_title(head) == "Ahmad Ali vs The State."


def test_both_parties_on_one_line():
    """Order sheets, e.g. 2026LHC17 — separated by wide runs of spaces."""
    head = (
        "Order Sheet\n"
        "Crl. Misc. No. 500 of 2026\n"
        "Sheikh Muhammad Awais          vs            The State, etc. \n"
    )
    assert _parse_title(head) == "Sheikh Muhammad Awais vs The State, etc"


def test_vs_opens_the_line_with_the_first_party_above():
    """2026LHC1 — the appellant runs over two lines above a leading "Vs.".

    The case-number line sits directly above and must not be swept into the
    title; without the noise filter this reads "C.R.No. 10 of 2026 ... vs ...".
    """
    head = (
        "FORM  No. HCJD/C-121 \n"
        "Order Sheet \n"
        "IN THE LAHORE HIGH COURT \n"
        "C.R.No. 10 of 2026 \n"
        " \n"
        "Mst. Naseem Mai (deceased) \n"
        "through L.Rs.  \n"
        "Vs. Muhammad Saleem Anjum. \n"
    )
    title = _parse_title(head)
    assert title == "Mst. Naseem Mai (deceased) through L.Rs vs Muhammad Saleem Anjum"
    assert "C.R.No" not in title


def test_parenthesised_parties_with_a_bare_v():
    """2026LHC2576 — judgment sheets abbreviate to "v.", not "vs"."""
    head = (
        "Judgment Sheet \n"
        "Criminal Revision No. 20366 of 2026 \n"
        "(Abdul Basit v. Senior Special Judge, Anti-Corruption Court, Lahore, etc.) \n"
        "ORDER \n"
    )
    assert _parse_title(head) == (
        "Abdul Basit vs Senior Special Judge, Anti-Corruption Court, Lahore, etc")


def test_connected_appeals_take_the_lead_case():
    """2026LHC3668 lists several appeals; the first is the one being decided."""
    head = (
        "Judgment Sheet \n"
        "Criminal Appeal No.63502 of 2025 \n"
        "(Jaffar alias Zafar v. The State etc.) \n"
        "and \n"
        "Criminal Appeal No.66013 of 2025 \n"
        "(Ghulam Rasool v. The State etc.) \n"
    )
    assert _parse_title(head) == "Jaffar alias Zafar vs The State etc"


def test_slashed_v_s_separator():
    """2026LHC3047 — "V/S" is as common in these registries as "vs".

    The respondent wraps onto the next line and is captured only as far as the
    line ends. That is deliberate: several correct titles end without
    punctuation, so joining the continuation would corrupt them to rescue this.
    """
    head = (
        "Income Tax Reference No.06 of 2026 \n"
        "Khairullah Khan V/S Appellate Tribunal Inland \n"
        "Revenue etc. \n"
    )
    assert _parse_title(head) == "Khairullah Khan vs Appellate Tribunal Inland"


def test_the_stacked_layout_wins_when_more_than_one_matches():
    """Order is the contract, not an accident of which pattern is listed first.

    A page can contain an inline "X vs Y" in a recital and the real parties in
    the stacked block. The stacked block is the authoritative one.
    """
    head = (
        "Order Sheet\n"
        "Some Recital Party          vs            Another Recital Party \n"
        "\n"
        "Real Appellant\n"
        "Versus\n"
        "Real Respondent\n"
    )
    assert _parse_title(head) == "Real Appellant vs Real Respondent"


def test_a_bare_v_in_prose_is_not_a_title():
    """The bare "v." branch is confined to a whole parenthesised line.

    Unparenthesised it would match ordinary sentences and produce a confident,
    wrong case name -- worse than the missing title it replaces.
    """
    head = (
        "Judgment Sheet \n"
        "the petitioner v. the respondent were heard at length today \n"
    )
    assert _parse_title(head) is None


def test_no_versus_anywhere_yields_no_title():
    """A missing title is correct output. Guessing one is not."""
    head = "IN THE LAHORE HIGH COURT \nJUDICIAL DEPARTMENT \nORDER \n"
    assert _parse_title(head) is None


def test_parse_metadata_uses_the_new_layouts():
    """The layouts have to reach the ingest path, not just the helper."""
    text = (
        "Order Sheet \n"
        "Crl. Misc. No. 500 of 2026 \n"
        "Sheikh Muhammad Awais          vs            The State, etc. \n"
    ) + "x" * 200
    assert parse_metadata(text)["title"] == "Sheikh Muhammad Awais vs The State, etc"
