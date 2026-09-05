"""A document must be labelled as the document it actually produces.

Both bugs this pins were live. A tile labelled "Contract" generated a
Non-Disclosure Agreement, and one labelled "Settlement Draft" generated a Rental
Agreement. Neither failed, errored, or warned — the user received a real,
correctly formatted PDF of an instrument they had not asked for, which is worse
than an error because nothing prompts them to check.

WHERE THIS CONTRACT NOW LIVES

It used to be checked against two hardcoded lists in ModDocuments.jsx, because
that is where the labels were. They are gone: the catalogue is served from
`template_registry`, built from the builder map itself, so a label without a
builder can no longer be written down at all.

So these tests moved with the labels. The mislabelling check is now made against
the registry — a stronger position, since it covers all twenty-one templates
rather than the seven that screen happened to list — and what is still asserted
about the JSX is that it holds no competing list of its own.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.constants import DocumentTemplate
from app.services import template_registry as reg
from app.services.document_service import TEMPLATE_TITLES

JSX = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "components"
       / "client" / "ModDocuments.jsx")


@pytest.fixture(scope="module")
def source() -> str:
    if not JSX.exists():                      # frontend absent in some checkouts
        pytest.skip(f"{JSX} not present")
    return JSX.read_text(encoding="utf-8")


# ── the contract between label and builder ────────────────────────────────────

def test_each_entry_is_labelled_as_the_document_it_generates():
    """THE TEST THAT WOULD HAVE CAUGHT BOTH BUGS.

    The backend already names every template in TEMPLATE_TITLES. If the
    catalogue's label does not correspond to that name, the user is being shown
    one document and handed another:

        "Contract"         -> nda              -> "Non-Disclosure Agreement"
        "Settlement Draft" -> rental_agreement -> "Rental Agreement"

    Comparison is on significant words rather than exact strings, so "Plaint"
    may legitimately label "Civil Plaint" — but nothing entirely unrelated can.
    """
    titles = {t.value: TEMPLATE_TITLES[t] for t in DocumentTemplate
              if t in TEMPLATE_TITLES}
    noise = {"the", "of", "a", "an", "and", "application", "agreement",
             "document", "draft", "notice", "statement", "to", "s", "crpc",
             "cpc", "rule", "order", "iii", "act"}

    def words(text: str) -> set[str]:
        return {w for w in re.findall(r"[a-z]+", text.lower())} - noise

    for item in reg.listing(include_system=True):
        backend_name = titles.get(item["template_type"])
        if not backend_name:
            continue
        shared = words(item["label"]) & words(backend_name)
        assert shared, (
            f'the catalogue calls {item["template_type"]} "{item["label"]}" '
            f'while the backend calls it "{backend_name}" — the two share no '
            f'significant word, so the user is shown one instrument and handed '
            f'another')


def test_the_agreements_the_backend_can_build_are_reachable():
    """Renaming the vague "Contract" tile must not strip access to the two
    agreement builders that do exist."""
    offered = {i["template_type"] for i in reg.listing()}
    assert "nda" in offered
    assert "rental_agreement" in offered


def test_nothing_unbuildable_can_be_offered():
    """The honest pattern used to be: an unbuildable type maps to null and the
    UI disables it. Substituting the nearest available template is how
    "Settlement Draft" came to generate a tenancy agreement.

    That pattern is now structural rather than maintained. The catalogue is
    built FROM the builder map, so an entry for a document nothing can render
    cannot be written down — there is no null case left to get wrong.
    """
    from app.services.pdf_generator import _GENERATORS
    for item in reg.listing(include_system=True):
        assert item["template_type"] in _GENERATORS


# ── the frontend keeps no competing list ─────────────────────────────────────

def test_the_client_holds_no_template_list_of_its_own(source):
    """Two lists, each claiming to know what exists, is the shape of the bug.

    Whichever one a screen reads, the other is free to drift — and the one that
    drifted offered documents nothing could build.
    """
    for ghost in ("DOC_TYPES_DATA", "DOC_TYPE_MAP"):
        assert ghost not in source, (
            f"{ghost} is back — the client is deciding again what the backend "
            f"can build")


def test_the_client_reads_the_catalogue(source):
    # Deleting the hardcoded lists without reading the real one leaves a picker
    # with nothing in it.
    assert "listTemplates()" in source
    assert "selectedType?.template_type" in source


# ── no fabricated data ────────────────────────────────────────────────────────

def test_no_mock_evidence_files_remain(source):
    """EVIDENCE_FILES held four invented filenames with sizes, dates and
    "Processed"/"Pending" statuses, and was never rendered anywhere. Dead mock
    data is one careless JSX edit away from being displayed as real. Same class
    as the lawyer review panel that showed four hardcoded green ticks."""
    for ghost in ("EVIDENCE_FILES", "Employment_Contract.pdf",
                  "Pay_Stubs_Dec25.pdf", "Termination_Letter.pdf",
                  "Offer_Letter_2022.pdf"):
        assert ghost not in source, f"{ghost} is fabricated placeholder data"
