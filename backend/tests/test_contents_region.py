"""Contents-region removal, the fix applied BEFORE chunking.

Pruning stubs after the fact cannot reach every case: a contents entry whose
body text was never extracted has no sibling to be matched against, so it
survives dedup and masquerades as the section itself. Removing the region up
front does reach those.

Two approaches were measured on the 21 real statutes and rejected, so they are
pinned here as comments rather than reinstated:
  * dotted-leader density per page fired on only 2 of 21 — Punjab contents lines
    carry neither a leader nor a page number;
  * right-aligned page numbers do not discriminate, because the text block is
    narrow and body lines share the same right edge.

The marker anchor works on 16 of 21.
"""
import importlib.util
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

# Real statutes run to hundreds or thousands of lines, so a contents block is a
# small fraction of the whole. Toy documents a few lines long would trip the
# safety cap that refuses to cut an oversized region, so tests pad the body to a
# realistic size.
_BODY_FILLER = "\n".join(
    f"and it is further provided that clause {i} shall have effect accordingly."
    for i in range(60)
)


@pytest.fixture(scope="module")
def ingest():
    spec = importlib.util.spec_from_file_location(
        "ingest_statutes", _SCRIPTS / "ingest_statutes.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── the two real formats ─────────────────────────────────────────────────────

def test_punjab_style_contents_without_leaders_is_removed(ingest):
    """Punjab contents entries are bare headings — textually identical in form
    to a real section heading, which is why per-line rules failed."""
    text = "\n".join([
        "THE PUNJAB RENTED PREMISES ACT 2009",
        "CONTENTS",
        "1. Short title, extent and commencement.",
        "2. Definitions.",
        "3. Rent agreement.",
        "4. Termination of tenancy.",
        "WHEREAS it is expedient to regulate the relationship between landlord "
        "and tenant and to provide for matters connected therewith;",
        "1. Short title, extent and commencement. (1) This Act may be called "
        "the Punjab Rented Premises Act 2009 and extends to the whole Punjab.",
        _BODY_FILLER,
    ])
    cleaned, removed = ingest._strip_contents(text)
    assert removed >= 4
    assert "CONTENTS" not in cleaned
    assert "2. Definitions." not in cleaned          # the stub is gone
    assert "WHEREAS it is expedient" in cleaned      # the law is intact
    assert "(1) This Act may be called" in cleaned


def test_dotted_leader_style_contents_is_removed(ingest):
    text = "\n".join([
        "QANUN-E-SHAHADAT ORDER, 1984",
        "CONTENTS",
        "Preamble",
        "1. Short title, extent and commencement 1",
        "16. Accomplice 7",
        "17. Competence and number of witnesses ... 7",
        "1. Short title, extent and commencement: (1) This Order may be called "
        "the Qanun-e-Shahadat Order, 1984 and shall come into force at once.",
        _BODY_FILLER,
    ])
    cleaned, removed = ingest._strip_contents(text)
    assert removed >= 4
    assert "16. Accomplice 7" not in cleaned
    assert "This Order may be called" in cleaned


def test_preamble_alone_does_not_terminate_the_scan(ingest):
    """Contents pages list "Preamble" as an entry. Treating it as the body
    stopped the scan immediately and made the Qanun-e-Shahadat — one of the two
    worst offenders — come back completely unchanged."""
    text = "\n".join([
        "SOME ACT 1900", "CONTENTS", "Preamble",
        "1. Short title 1", "2. Definitions 2", "3. Application 3",
        "WHEREAS it is expedient to enact this law for the purposes stated;",
        _BODY_FILLER,
    ])
    _cleaned, removed = ingest._strip_contents(text)
    assert removed >= 4


# ── safety: never eat the statute ────────────────────────────────────────────

def test_no_marker_means_no_removal(ingest):
    """5 of 21 statutes have no marker. They must pass through untouched and be
    handled by the stub prune instead."""
    text = "\n".join([
        "PAKISTAN PENAL CODE",
        "1. Title and extent of operation of the Code. This Act shall be called "
        "the Pakistan Penal Code, and shall extend to the whole of Pakistan.",
    ])
    cleaned, removed = ingest._strip_contents(text)
    assert removed == 0
    assert cleaned == text


def test_a_tiny_block_after_the_marker_is_not_removed(ingest):
    """Too few entries to be a real contents block — safer to keep them."""
    text = "\n".join(["AN ACT", "CONTENTS", "1. Only entry.",
                      "WHEREAS this is the body of the law and continues at length;"])
    _cleaned, removed = ingest._strip_contents(text)
    assert removed == 0


def test_an_oversized_region_is_refused_not_clamped(ingest):
    """A document that looks like contents throughout must be left ALONE.
    Clamping the cut to the cap would slice at an arbitrary line, leaving part
    of the contents behind and a meaningless boundary — worse than not cutting."""
    lines = ["AN ACT", "CONTENTS"] + [f"{i}. Section heading {i}." for i in range(1, 60)]
    text = "\n".join(lines)
    cleaned, removed = ingest._strip_contents(text)
    assert removed == 0
    assert cleaned == text


def test_body_prose_terminates_the_contents_region(ingest):
    """A long line is prose, not a contents entry — everything after it stays."""
    body = ("5. Powers of the Court. The Court may, on the application of any "
            "party and after recording reasons in writing, pass such order as "
            "it deems fit in the circumstances of the case.")
    text = "\n".join(["AN ACT", "CONTENTS", "1. A.", "2. B.", "3. C.", "4. D.", body])
    cleaned, _removed = ingest._strip_contents(text)
    assert body in cleaned


def test_empty_input_is_handled(ingest):
    assert ingest._strip_contents("") == ("", 0)
