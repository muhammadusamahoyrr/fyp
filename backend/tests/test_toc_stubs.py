"""Contents-page stubs must not reach the index.

Every statute PDF opens with a CONTENTS page whose lines read
"12. Power to arrest .... 7". Section-aware splitting treats each as a section
start and emits a ~50-character chunk, duplicating a section whose real text is
indexed separately. Measured on the live corpus: 1,303 such stubs.

They are not merely wasteful. A stub is almost entirely heading words, so for a
query about that heading its keyword overlap is as high as the provision's, and
it is short enough to sit close to a short query in embedding space. It competes
with, and can outrank, the law it names.

Detection is by normalised HEAD match, not by length. Two earlier attempts
failed on real data and both failures are pinned below:
  * a length threshold ("sibling over 400 chars") misjudged QSO s.16, whose real
    provision is only 254 characters;
  * exact prefix matching missed OCR variants — the contents page says
    "communications" where the body reads "communicat ions".
"""
import importlib.util
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture(scope="module")
def ingest():
    spec = importlib.util.spec_from_file_location(
        "ingest_statutes", _SCRIPTS / "ingest_statutes.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _chunk(section: str, text: str) -> dict:
    return {"id": f"x_{section}_{len(text)}", "content": text,
            "meta": {"section_number": section, "statute": "Test Act 1900"}}


# ── the real cases, taken from the live corpus ───────────────────────────────

def test_the_qso_section_1_stub_is_dropped(ingest):
    stub = _chunk("1", "1. Short title, extent and commencement 1")
    real = _chunk("1", "1. Short title, extent and commencement: (1) This order "
                       "may be called the Qanun-e-Shahadat Order 1984. " + "x" * 350)
    kept = ingest._drop_toc_stubs([stub, real])
    assert [c["content"][:20] for c in kept] == ["1. Short title, exte"]
    assert len(kept) == 1


def test_a_short_provision_is_still_recognised_as_the_target(ingest):
    """QSO s.16's real text is 254 chars. A length threshold of 400 wrongly
    treated the stub as the only copy and kept both."""
    stub = _chunk("16", "16. Accomplice 7")
    real = _chunk("16", "16. Accomplice; An accomplice shall be a competent "
                        "witness against an accused person, except in the case "
                        "of an offence punishable with hadd." + " " * 0 + "y" * 100)
    assert len(ingest._drop_toc_stubs([stub, real])) == 1


def test_ocr_spacing_variants_still_match(ingest):
    """Contents says "communications"; the body reads "communicat ions"."""
    stub = _chunk("12", "12. Confidential communications with legal advisers 6")
    real = _chunk("12", "12. Confidential communicat ions with legal advisers: "
                        "no one shall be compelled to disclose " + "z" * 300)
    assert len(ingest._drop_toc_stubs([stub, real])) == 1


def test_hyphenation_variants_still_match(ingest):
    stub = _chunk("18", "18. Evidence may be given of facts-in-issue 8")
    real = _chunk("18", "18. Evidence may be given of f acts in issue and "
                        "relevant facts: evidence may be given " + "w" * 300)
    assert len(ingest._drop_toc_stubs([stub, real])) == 1


# ── what must never be dropped ───────────────────────────────────────────────

def test_a_short_section_that_is_its_only_copy_is_kept(ingest):
    """809 chunks in the corpus are like this. Dropping them would lose law."""
    lone = _chunk("7", "7. Repeal. The 1861 Act is hereby repealed.")
    assert ingest._drop_toc_stubs([lone]) == [lone]


def test_substantial_chunks_are_never_dropped(ingest):
    a = _chunk("12", "12. Power to arrest without warrant. " + "y" * 500)
    b = _chunk("12", "continuation of section 12 " + "z" * 500)
    assert len(ingest._drop_toc_stubs([a, b])) == 2


def test_a_different_heading_is_not_treated_as_a_stub(ingest):
    """Same section number, genuinely different opening — not a contents line."""
    a = _chunk("5", "5. Wholly unrelated marginal note here")
    b = _chunk("5", "5. Communications during marriage: no person who is or "
                    "has been married shall " + "q" * 300)
    assert len(ingest._drop_toc_stubs([a, b])) == 2


def test_sections_do_not_interfere_with_each_other(ingest):
    stub = _chunk("1", "1. Short title and commencement 1")
    other = _chunk("2", "2. Definitions. " + "q" * 600)
    kept = ingest._drop_toc_stubs([stub, other])
    assert sorted(c["meta"]["section_number"] for c in kept) == ["1", "2"]


def test_a_head_too_short_to_be_distinctive_is_never_matched(ingest):
    """Under 12 normalised characters a head would match almost anything."""
    a = _chunk("9", "9. Cost")
    b = _chunk("9", "9. Costs of the suit shall follow the event " + "r" * 300)
    assert len(ingest._drop_toc_stubs([a, b])) == 2


def test_empty_input_is_handled(ingest):
    assert ingest._drop_toc_stubs([]) == []


# ── the two implementations must agree ───────────────────────────────────────

def test_ingest_and_prune_use_the_same_rule(ingest):
    """prune_toc_stubs.py cleans the live corpus; ingest_statutes.py stops the
    stubs recurring. If the constants drift, the two disagree about what a stub
    is and pruned chunks come straight back on the next ingest."""
    src = (_SCRIPTS / "prune_toc_stubs.py").read_text(encoding="utf-8")
    assert f"MIN_CHARS = {ingest._STUB_MAX_CHARS}" in src
    assert f"_STUB_HEAD_CHARS = {ingest._STUB_HEAD_CHARS}" in src
