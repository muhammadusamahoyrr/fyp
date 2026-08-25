"""Succession forum routing — NADRA or the District Judge.

The whole feature turns on one clause. s.5(b) of the Punjab Act 2021 sends a
case to court "in case of any factual controversy amongst the legal heirs" — and
on nothing else. Not the size of the estate, not the number of heirs. Most of
these tests exist to stop a plausible-sounding second trigger being added later,
because any such rule would be invented rather than read.
"""
from __future__ import annotations

import pytest

from app.services.succession_route import (
    CIVIL_COURT,
    NADRA,
    OUT_OF_SCOPE,
    advise,
)

PUNJAB = {"province": "Punjab"}


# ── the referral trigger ──────────────────────────────────────────────────────

def test_an_undisputed_punjab_case_goes_to_nadra():
    r = advise(heirs_dispute=False, **PUNJAB)
    assert r.forum == NADRA
    cited = {c.section for c in r.citations}
    assert {"3", "6", "7"} <= cited


def test_a_disputed_punjab_case_goes_to_the_district_judge():
    r = advise(heirs_dispute=True, **PUNJAB)
    assert r.forum == CIVIL_COURT
    refs = {c.reference for c in r.citations}
    assert any("s.5" in x for x in refs), "s.5(b) is the referral trigger"
    assert "Succession Act 1925 s.372" in refs


def test_dispute_is_the_only_thing_that_moves_an_in_punjab_case():
    """s.5(b) turns on factual controversy, not value or complexity. A rule
    keyed to estate size would be one this system invented."""
    assert advise(heirs_dispute=False, **PUNJAB).forum == NADRA
    assert advise(heirs_dispute=True, **PUNJAB).forum == CIVIL_COURT


def test_the_nadra_route_warns_that_a_later_dispute_reroutes_it():
    """The Unit declines when controversy appears — including after filing. A
    user told 'go to NADRA' without that is told half the rule."""
    r = advise(heirs_dispute=False, **PUNJAB)
    joined = " ".join(r.caveats).lower()
    assert "controversy" in joined
    assert "1925" in joined


def test_the_court_route_says_the_dispute_can_be_settled():
    r = advise(heirs_dispute=True, **PUNJAB)
    assert any("reopens" in c.lower() or "settled" in c.lower() for c in r.caveats)


# ── s.370 bites before the choice of forum ────────────────────────────────────

def test_a_case_needing_probate_is_not_a_certificate_case_at_all():
    """s.370 bars a certificate where the right must be established by letters
    of administration or probate. Answering 'NADRA' there would send someone to
    the right counter for the wrong instrument."""
    r = advise(heirs_dispute=False, needs_probate_or_administration=True, **PUNJAB)
    assert r.forum == CIVIL_COURT
    assert "Succession Act 1925 s.370" in {c.reference for c in r.citations}
    assert "not the right instrument" in r.headline


def test_the_probate_bar_outranks_the_dispute_question():
    """It applies whether or not the heirs agree — so it is checked first."""
    for dispute in (True, False):
        r = advise(heirs_dispute=dispute,
                   needs_probate_or_administration=True, **PUNJAB)
        assert "s.370" in " ".join(c.reference for c in r.citations)


# ── provincial scope ──────────────────────────────────────────────────────────

def test_a_case_outside_punjab_is_marked_out_of_scope_not_routed_to_nadra():
    """The 2021 Act is provincial. Offering the NADRA route for a Sindh death
    would be asserting a law that does not reach there."""
    r = advise(heirs_dispute=False, province="Sindh")
    assert r.forum == OUT_OF_SCOPE
    assert "Succession Act 1925 s.372" in {c.reference for c in r.citations}
    assert any("provincial" in c.lower() or "province" in c.lower()
               for c in r.caveats)


def test_punjab_property_brings_a_case_back_into_scope():
    """s.6(2) gives venue where the deceased resided OR where property is, so
    property in Punjab is enough."""
    r = advise(heirs_dispute=False, province="Sindh", property_in_punjab=True)
    assert r.forum == NADRA


@pytest.mark.parametrize("name", ["Punjab", "punjab", " PUNJAB ", "Lahore"])
def test_province_is_matched_leniently(name):
    assert advise(heirs_dispute=False, province=name).forum == NADRA


# ── what this is, and is not ──────────────────────────────────────────────────

def test_the_output_is_guidance_not_a_filing():
    """s.7 leaves the form to NADRA. Producing our own PDF would be inventing
    paperwork the statute does not ask for."""
    d = advise(heirs_dispute=False, **PUNJAB).to_dict()
    assert d["is_guidance_not_a_filing"] is True
    assert "file_path" not in d and "doc_id" not in d


def test_the_nadra_route_says_the_form_belongs_to_nadra():
    r = advise(heirs_dispute=False, **PUNJAB)
    assert any("prescribed form" in s or "prescribed" in s for s in r.steps)
    assert "7" in {c.section for c in r.citations}


def test_it_does_not_claim_to_decide_shares_or_heirship():
    r = advise(heirs_dispute=False, **PUNJAB)
    assert any("does not assess" in c.lower() for c in r.caveats)


def test_every_route_cites_at_least_one_provision():
    for kw in ({"heirs_dispute": False, **PUNJAB},
               {"heirs_dispute": True, **PUNJAB},
               {"heirs_dispute": False, "province": "Sindh"},
               {"heirs_dispute": False, "needs_probate_or_administration": True,
                **PUNJAB}):
        r = advise(**kw)
        assert r.citations, kw
        assert r.citation_text().strip()


# ── verification ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_guidance_is_citation_checked_like_a_document():
    """A route that cites a repealed section is as wrong as a pleading that
    does."""
    from app.services.succession_route import advise_verified

    out = await advise_verified(heirs_dispute=True, **PUNJAB)
    v = out["verification"]
    if not v["ran"]:
        pytest.skip("corpus unavailable in this environment")
    assert v["counts"]["not_in_corpus"] == 0
    assert v["counts"]["omitted"] == 0
    checked = {c["canonical"] for c in v["checks"]}
    assert "Succession Act 1925 s.372" in checked


@pytest.mark.asyncio
async def test_advice_still_returns_when_the_checker_is_down(monkeypatch):
    """Fail-open, and visibly: `ran: False` must not read as a pass."""
    from app.services import succession_route

    async def boom(*a, **k):
        raise RuntimeError("chroma down")

    monkeypatch.setattr("app.ai.citation_verification.verify_text", boom)
    out = await succession_route.advise_verified(heirs_dispute=False, **PUNJAB)

    assert out["forum"] == NADRA           # advice survives
    assert out["verification"]["ran"] is False
    assert out["verification"]["needs_human_check"] is True
    assert "NOT" in out["verification"]["summary"]
