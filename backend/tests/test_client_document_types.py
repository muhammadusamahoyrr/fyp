"""The client's document-type tiles must name the document they actually produce.

These assertions live in the backend suite because that is where the test runner
is, and because the thing being checked is a CONTRACT BETWEEN the two: a label in
the frontend and a builder in the backend.

Both bugs this pins were live. A tile labelled "Contract" generated a
Non-Disclosure Agreement, and one labelled "Settlement Draft" generated a
Rental Agreement. Neither failed, errored, or warned — the user received a real,
correctly formatted PDF of an instrument they had not asked for, which is worse
than an error because nothing prompts them to check.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.constants import DocumentTemplate
from app.services.document_service import TEMPLATE_TITLES

JSX = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "components"
       / "client" / "ModDocuments.jsx")


@pytest.fixture(scope="module")
def source() -> str:
    if not JSX.exists():                      # frontend absent in some checkouts
        pytest.skip(f"{JSX} not present")
    return JSX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def tiles(source: str) -> list[str]:
    block = re.search(r"const DOC_TYPES_DATA = \[(.*?)\];", source, re.S)
    assert block, "DOC_TYPES_DATA not found"
    return re.findall(r'key:\s*"([^"]+)"', block.group(1))


@pytest.fixture(scope="module")
def mapping(source: str) -> dict[str, str | None]:
    block = re.search(r"const DOC_TYPE_MAP = \{(.*?)\};", source, re.S)
    assert block, "DOC_TYPE_MAP not found"
    out: dict[str, str | None] = {}
    for key, value in re.findall(r'"([^"]+)":\s*(null|"[a-z0-9_]+")',
                                 block.group(1)):
        out[key] = None if value == "null" else value.strip('"')
    return out


# ── the contract between label and builder ────────────────────────────────────

def test_every_tile_has_an_explicit_mapping(tiles, mapping):
    """`DOC_TYPE_MAP[type] || "plaint_civil"` means an UNMAPPED tile silently
    generates a civil plaint. The null check catches null, not undefined, so a
    tile added without a map entry produces the wrong document with no warning.
    """
    for key in tiles:
        assert key in mapping, (
            f'tile "{key}" has no DOC_TYPE_MAP entry — it would fall through to '
            f'the plaint_civil default and generate a civil plaint')


def test_every_mapped_template_exists_in_the_backend(mapping):
    valid = {t.value for t in DocumentTemplate}
    for key, template in mapping.items():
        if template is None:
            continue
        assert template in valid, f'"{key}" maps to unknown template {template!r}'


@pytest.mark.parametrize("_", [None])
def test_each_tile_is_labelled_as_the_document_it_generates(mapping, _):
    """THE TEST THAT WOULD HAVE CAUGHT BOTH BUGS.

    The backend already names every template in TEMPLATE_TITLES. If a tile's
    label does not correspond to that name, the user is being shown one document
    and handed another:

        "Contract"         -> nda              -> "Non-Disclosure Agreement"
        "Settlement Draft" -> rental_agreement -> "Rental Agreement"

    Comparison is on significant words rather than exact strings, so "Plaint"
    may legitimately label "Civil Plaint" — but nothing entirely unrelated can.
    """
    titles = {t.value: TEMPLATE_TITLES[t] for t in DocumentTemplate
              if t in TEMPLATE_TITLES}
    noise = {"the", "of", "a", "an", "and", "application", "agreement",
             "document", "draft", "notice", "statement"}

    def words(text: str) -> set[str]:
        return {w for w in re.findall(r"[a-z]+", text.lower())} - noise

    for key, template in mapping.items():
        if template is None:
            continue
        backend_name = titles.get(template, "")
        shared = words(key) & words(backend_name)
        assert shared, (
            f'tile "{key}" generates "{backend_name}" ({template}) — the label '
            f'and the document share no significant word, so the user is being '
            f'shown one instrument and handed another')


def test_unsupported_types_are_null_not_a_near_miss(mapping):
    """The honest pattern: an unbuildable type maps to null and the UI disables
    it. Substituting the nearest available template is how "Settlement Draft"
    came to generate a tenancy agreement."""
    assert mapping.get("Stay Application") is None
    assert mapping.get("Settlement Draft") is None, (
        "no settlement builder exists; mapping it to any real template hands "
        "the user the wrong instrument")


def test_the_agreements_the_backend_can_build_are_reachable(mapping):
    """Renaming the vague "Contract" tile must not strip access to the two
    agreement builders that do exist."""
    assert mapping.get("Non-Disclosure Agreement") == "nda"
    assert mapping.get("Rental Agreement") == "rental_agreement"


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
