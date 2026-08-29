"""How old our copy of a statute is — a fact about our document, not the law.

The distance between the two is large and unknowable from inside the corpus:
PPC's amendment declarations stop at 2006 while the Act has been amended
repeatedly since, and nothing in the text records that gap. So this module may
report what it can SEE and must never round that up into a claim about currency.

Everything here is deterministic — plain strings through `scan_text`, no Chroma.
"""
from __future__ import annotations

import pytest

from app.ai.corpus_as_of import StatuteAsOf, as_of_for, own_year, scan_text

# The shapes the corpus actually contains, verbatim.
CRPC_2001 = ("10. [Omitted by the Ordinance XXXVII of 2001dt. 13-8-2001.] "
             "Substituted by the Criminal Law (Amendment) Act, 1997 (II of 1997).")
LIMITATION_1980 = ("3 Substituted by the Limitation (Amendment) Ordinance, 1980 "
                   "(LXII of 1980), published in the Gazette of Pakistan "
                   "(Extraordinary), dated: 8 July 1981, pp. 345-475.")
ADAPTATION_1949 = ("2 The word “Indian” was omitted by the Adaptation of "
                   "Central Acts and Ordinances Order, 1949 (G.G.O. No. 4 of 1949).")


# ── The two sentences, and only those two ─────────────────────────────────────

def test_a_detected_year_uses_the_fixed_wording():
    record = scan_text("CrPC 1898", [CRPC_2001])
    assert record.describe() == "Latest amendment year detected in our corpus: 2001."


def test_no_year_says_so_plainly():
    record = scan_text("Family Courts Act 1964", ["26. Short title and extent."])
    assert record.latest_year is None
    assert record.describe() == "Amendment date not established from this corpus."


@pytest.mark.parametrize("texts", [
    [CRPC_2001], [LIMITATION_1980], ["nothing here"], [], [""],
])
def test_no_wording_ever_claims_currency(texts):
    """The whole risk in this module is a caller turning "detected" into
    "current". The vocabulary must make that impossible."""
    said = scan_text("CrPC 1898", texts).describe().lower()
    for forbidden in ("current as of", "in force", "up to date", "up-to-date",
                      "currently valid", "valid as of", "as amended up to"):
        assert forbidden not in said


def test_the_dict_carries_its_own_meaning():
    """The value gets copied into document records and API responses, so the
    caveat has to travel with it rather than living only here."""
    payload = scan_text("CrPC 1898", [CRPC_2001]).to_dict()
    assert payload["latest_amendment_year_detected"] == 2001
    assert "not the law" in payload["means"]
    assert "not a statement that the text is in force" in payload["means"]
    for forbidden in ("current as of", "up to date", "currently valid"):
        assert forbidden not in payload["means"].lower()


# ── A year only counts when it follows an amendment declaration ───────────────

def test_a_year_in_ordinary_prose_is_not_an_amendment():
    text = ("5. The court may condone delay where the appeal was filed in 1995 "
            "and the record was lost in 2003 during the floods.")
    assert scan_text("Limitation Act 1908", [text]).latest_year is None


def test_a_year_far_from_the_declaration_is_not_counted():
    """The window is bounded so a declaration cannot reach into the next
    footnote and adopt its year."""
    text = "1 Omitted by the Adaptation Order. " + ("x" * 400) + " 2019"
    assert scan_text("CrPC 1898", [text]).latest_year is None


def test_declarations_are_counted_even_when_no_year_qualifies():
    """`declarations_seen` is what tells a reader the text HAS amendment
    apparatus that simply carried no usable year — different from silence."""
    record = scan_text("CrPC 1898", ["3 Substituted by an unnamed instrument."])
    assert record.declarations == 1
    assert record.latest_year is None


# ── The statute's own year is not an amendment ────────────────────────────────

def test_an_amendment_cannot_predate_the_act():
    """"Limitation Act 1908" citing "Act, 1908" is its own commencement, not a
    later legislature touching it."""
    text = "1 Inserted by the Limitation Act, 1908 (IX of 1908)."
    assert scan_text("Limitation Act 1908", [text]).latest_year is None


def test_an_earlier_year_is_rejected():
    text = "1 Substituted by the Repealing and Amending Act, 1870 (XII of 1870)."
    assert scan_text("Limitation Act 1908", [text]).latest_year is None


def test_a_later_year_is_accepted():
    assert scan_text("Limitation Act 1908", [LIMITATION_1980]).latest_year == 1981


def test_own_year_reads_the_trailing_year_only():
    assert own_year("PPC 1860") == 1860
    assert own_year("Punjab Rented Premises Act 2009") == 2009
    assert own_year("Constitution of Pakistan 1973") == 1973
    assert own_year("Some Act With No Year") is None


def test_a_statute_with_no_year_in_its_name_still_scans():
    """No floor to apply, so every declared year counts."""
    record = scan_text("Some Act", [ADAPTATION_1949])
    assert record.latest_year == 1949


# ── Implausible years are rejected ────────────────────────────────────────────

def test_a_future_year_is_rejected():
    text = "1 Substituted by the Imaginary Act, 2099 (I of 2099)."
    assert scan_text("PPC 1860", [text], today_year=2026).latest_year is None


def test_the_ceiling_is_the_current_year():
    text = "1 Substituted by the Recent Act, 2026 (I of 2026)."
    assert scan_text("PPC 1860", [text], today_year=2026).latest_year == 2026
    assert scan_text("PPC 1860", [text], today_year=2020).latest_year is None


def test_a_page_or_section_number_is_not_a_year():
    text = "1 Substituted by the Act, s. 345, pp. 223-283."
    assert scan_text("PPC 1860", [text]).latest_year is None


# ── Aggregation ───────────────────────────────────────────────────────────────

def test_the_latest_year_wins_across_chunks():
    record = scan_text("CrPC 1898", [ADAPTATION_1949, CRPC_2001, LIMITATION_1980])
    assert record.latest_year == 2001
    assert record.declarations == 4


def test_supporting_count_reports_how_thin_the_evidence_is():
    """A year resting on one mention and a year resting on seventy are both
    reported, and the caller can see which is which."""
    once = scan_text("PPC 1860", ["1 Substituted by the Act, 1999 (I of 1999)."])
    assert once.latest_year == 1999
    assert once.supporting == 2      # "1999" appears twice in that declaration


def test_empty_and_none_inputs_are_safe():
    for texts in ([], [""], [None], None):
        record = scan_text("PPC 1860", texts)
        assert record.latest_year is None
        assert record.describe() == "Amendment date not established from this corpus."


# ── Failure and unknown statutes ──────────────────────────────────────────────

def test_an_unknown_statute_reads_as_not_established(monkeypatch):
    monkeypatch.setattr("app.ai.corpus_as_of.get_as_of_map", lambda: {})
    record = as_of_for("Companies Act 2017")
    assert record.latest_year is None
    assert record.describe() == "Amendment date not established from this corpus."


def test_a_corpus_failure_never_raises_and_never_guesses(monkeypatch):
    def boom():
        raise RuntimeError("chroma down")

    monkeypatch.setattr("app.ai.corpus_as_of.get_as_of_map", boom)
    record = as_of_for("PPC 1860")
    assert record.latest_year is None
    assert record.describe() == "Amendment date not established from this corpus."


# ── Separation from verification and currency ─────────────────────────────────

def test_as_of_does_not_import_verification_or_currency():
    """Structural, not conventional: merging any two of "does it exist",
    "was it repealed" and "how old is our copy" produces a claim none of them
    supports.

    Checked over real IMPORT statements rather than the file text — the module
    discusses those neighbours at length in its docstring, and should.
    """
    import ast
    import pathlib

    src = pathlib.Path(
        __file__).resolve().parents[1] / "app" / "ai" / "corpus_as_of.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    for forbidden in ("app.ai.citation_verification", "app.ai.answer_citations",
                      "app.ai.statute_omissions", "app.ai.corpus_index"):
        assert forbidden not in imported, f"as_of must not depend on {forbidden}"


def test_an_as_of_year_says_nothing_about_a_specific_section():
    """Documented in `means` because it is the most likely misreading: a 2006
    as-of does not mean every section was current in 2006, nor that any
    particular section was amended then."""
    payload = scan_text("PPC 1860", [CRPC_2001]).to_dict()
    assert "later amendments may exist" in payload["means"]


# ── The document surface ──────────────────────────────────────────────────────

def test_the_verification_record_carries_as_of_for_cited_statutes(monkeypatch):
    from app.ai.corpus_as_of import set_as_of_map
    from app.ai.corpus_index import CorpusIndex, StatuteCoverage, set_index
    from app.services import document_service

    cov = StatuteCoverage(
        statute="PPC 1860",
        sections=frozenset(str(n) for n in range(1, 512)),
        numbered=frozenset(range(1, 512)), highest=511,
        artifacts=frozenset(), ceiling_outliers=frozenset(),
        omitted=frozenset(), omission_records={})

    set_index(CorpusIndex({"PPC 1860": cov}))
    set_as_of_map({"PPC 1860": StatuteAsOf("PPC 1860", 2006, 204, 10)})
    try:
        rows = document_service._as_of_for("liable under PPC Section 302")
    finally:
        set_as_of_map(None)
        set_index(None)

    assert len(rows) == 1
    assert rows[0]["statute"] == "PPC 1860"
    assert rows[0]["statement"] == (
        "Latest amendment year detected in our corpus: 2006.")


def test_the_document_surface_never_fails_generation(monkeypatch):
    from app.services import document_service

    def boom(*a, **k):
        raise RuntimeError("index down")

    monkeypatch.setattr("app.ai.citation_verification.parse_statute_citations", boom)
    assert document_service._as_of_for("liable under PPC Section 302") == []


def test_a_draft_citing_nothing_gets_no_as_of_rows():
    from app.ai.corpus_index import CorpusIndex, set_index
    from app.services import document_service

    set_index(CorpusIndex({}))
    try:
        assert document_service._as_of_for("This draft cites no authority.") == []
    finally:
        set_index(None)
