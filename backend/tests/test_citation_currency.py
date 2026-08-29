"""A cited section can be real, retrieved, and on point — and still be dead law.

`matched` says the answer cited something we can point at. `supported` says the
source establishes the claim. Neither says the provision still exists. CrPC s.10
is real, its chunk is in the corpus, and it will read as matched+supported for a
provision the Executive Magistracy ordinance abolished in 2001.

The rule under test throughout: there are exactly two currency values reaching a
user, `repealed` and `unknown`, and `unknown` is never a statement that anything
is current. Repeal data covers 4 of 43 statutes and is a self-declared lower
bound; amendment is not modelled; no statute carries an as-of date. Inferring
currency from silence is the one claim this system must never make.

Deterministic: a hand-built index is injected, so nothing here touches Chroma.
"""
from __future__ import annotations

import pytest

from app.ai.answer_citations import (
    CURRENCY_REPEALED,
    CURRENCY_UNKNOWN,
    apply_currency,
    currency_for,
)
from app.ai.corpus_index import CorpusIndex, StatuteCoverage
from app.ai.statute_omissions import OmissionRecord


def _rec(section, instrument="", date="", jurisdiction="federal", status="omitted"):
    return OmissionRecord(section, status, instrument, date, jurisdiction, "")


def _coverage(statute: str, sections, omitted=(), records=None) -> StatuteCoverage:
    return StatuteCoverage(
        statute=statute,
        sections=frozenset(str(s) for s in sections),
        numbered=frozenset(int(s) for s in sections),
        highest=max((int(s) for s in sections), default=0),
        artifacts=frozenset(),
        ceiling_outliers=frozenset(),
        omitted=frozenset(int(s) for s in omitted),
        omission_records=dict(records or {}),
    )


@pytest.fixture
def index() -> CorpusIndex:
    """CrPC with three dead sections; PPC with none recorded at all."""
    crpc = _coverage(
        "CrPC 1898", range(1, 412),
        omitted=(10, 562, 407),
        records={
            10:  _rec(10, "Ordinance XXXVII of 2001", "2001-08-13", "federal"),
            562: _rec(562, "Probation of Offenders Ordinance XLV of 1960, s.16",
                      "1960-11-01", "federal"),
            # Punjab-scoped repeal: real in Punjab, not in Sindh.
            407: _rec(407, "Punjab Notification SO(J-II) 1-8/75", "1996-03-21",
                      "punjab"),
        })
    ppc = _coverage("PPC 1860", range(1, 512))
    return CorpusIndex({"CrPC 1898": crpc, "PPC 1860": ppc})


# ── repealed ──────────────────────────────────────────────────────────────────

def test_a_repealed_section_reports_repealed(index):
    assert currency_for("CrPC 1898", "10", "", index)["currency"] == CURRENCY_REPEALED


def test_the_instrument_and_date_are_preserved(index):
    """"Repealed" alone asks a lawyer to take our word for it. The instrument
    can be looked up, argued with, and — if we are wrong — disproved."""
    result = currency_for("CrPC 1898", "10", "", index)
    assert result["instrument"] == "Ordinance XXXVII of 2001"
    assert result["date"] == "2001-08-13"
    assert result["jurisdiction"] == "federal"


def test_a_repeal_with_no_traced_instrument_is_still_repealed(index):
    """Most omissions are declared by the statute text without naming the
    amending act. Untraced is not a demotion."""
    cov = _coverage("Test Act 1900", range(1, 50), omitted=(7,))
    idx = CorpusIndex({"Test Act 1900": cov})
    result = currency_for("Test Act 1900", "7", "", idx)
    assert result["currency"] == CURRENCY_REPEALED
    assert result["instrument"] == ""


# ── unknown, and what it does not mean ────────────────────────────────────────

def test_a_live_section_reports_unknown_not_in_force(index):
    """The honest verdict for a section with no repeal record is that we have
    not checked, not that it is current."""
    assert currency_for("CrPC 1898", "154", "", index)["currency"] == CURRENCY_UNKNOWN


def test_ppc_sections_are_unknown_because_ppc_has_no_omission_data(index):
    """PPC is dense and heavily cited, and its footnote-style omissions are not
    parsed at all. Every PPC section must therefore read `unknown` — treating
    that silence as currency would be confident and wrong on the most-cited
    statute in the corpus."""
    for section in ("302", "379", "420", "511"):
        assert currency_for("PPC 1860", section, "", index)["currency"] == CURRENCY_UNKNOWN


def test_in_force_is_never_produced(index):
    """No input may yield a positive currency claim — the vocabulary does not
    contain one."""
    seen = {currency_for(st, sec, prov, index)["currency"]
            for st in ("CrPC 1898", "PPC 1860", "Nonexistent Act 1999")
            for sec in ("10", "154", "302", "9999", "")
            for prov in ("", "punjab", "sindh")}
    assert seen <= {CURRENCY_REPEALED, CURRENCY_UNKNOWN}
    assert not any("force" in v for v in seen)


def test_a_statute_outside_the_corpus_is_unknown(index):
    assert currency_for("Companies Act 2017", "12", "", index)["currency"] == CURRENCY_UNKNOWN


def test_held_pending_sections_are_not_reported_repealed():
    """CrPC 407 and 438 are claimed omitted by one source and confirmed by none.
    statute_omissions holds them out of the omitted set entirely, so they must
    read `unknown` — neither asserted dead nor asserted alive."""
    from app.ai.statute_omissions import get_omissions

    held_out = get_omissions().get("CrPC 1898", frozenset())
    assert 407 not in held_out
    assert 438 not in held_out


# ── jurisdiction scoping ──────────────────────────────────────────────────────

def test_a_province_scoped_repeal_applies_in_its_own_province(index):
    assert currency_for("CrPC 1898", "407", "punjab", index)["currency"] == CURRENCY_REPEALED


@pytest.mark.parametrize("province", ["sindh", "kpk", "balochistan", "federal"])
def test_a_province_scoped_repeal_is_not_applied_elsewhere(index, province):
    """A section killed by a Punjab notification is alive in Sindh. Asserting it
    dead nationally would be a false statement of law in three provinces."""
    assert currency_for("CrPC 1898", "407", province, index)["currency"] == CURRENCY_UNKNOWN


def test_a_province_scoped_repeal_is_not_asserted_when_province_is_unknown(index):
    """With no province we cannot place the user, so we do not assert the
    repeal. Under-claiming is the safe direction."""
    assert currency_for("CrPC 1898", "407", "", index)["currency"] == CURRENCY_UNKNOWN


@pytest.mark.parametrize("province", ["", "punjab", "sindh"])
def test_a_federal_repeal_binds_in_every_province(index, province):
    assert currency_for("CrPC 1898", "10", province, index)["currency"] == CURRENCY_REPEALED


# ── override: repeal outranks matched/supported ───────────────────────────────

def test_repealed_overrides_a_supported_claim(index):
    """The sharp case. The source really does say what the claim says, the judge
    really did mark it supported, and the provision was abolished in 2001."""
    citations = [{"statute": "CrPC 1898", "section": "10", "status": "matched"}]
    claims = [{"index": 1, "text": "A District Magistrate may act under CrPC s.10.",
               "sources": [{"id": "1", "statute": "CrPC 1898", "section": "10"}],
               "citation_status": "matched", "support": "supported"}]

    apply_currency(citations, claims, province="", index=index)

    assert citations[0]["currency"] == CURRENCY_REPEALED
    assert claims[0]["currency"] == CURRENCY_REPEALED
    # The support verdict is preserved, not rewritten — it was correct about the
    # question it answered. The UI is what must let currency win.
    assert claims[0]["support"] == "supported"
    assert citations[0]["status"] == "matched"


def test_one_dead_source_contaminates_a_multi_source_claim(index):
    claims = [{"index": 1, "text": "x", "support": "supported",
               "citation_status": "matched",
               "sources": [{"id": "1", "statute": "PPC 1860", "section": "302"},
                           {"id": "2", "statute": "CrPC 1898", "section": "10"}]}]
    apply_currency([], claims, province="", index=index)
    assert claims[0]["currency"] == CURRENCY_REPEALED


def test_a_live_claim_is_marked_unknown_not_current(index):
    claims = [{"index": 1, "text": "x", "support": "supported",
               "citation_status": "matched",
               "sources": [{"id": "1", "statute": "PPC 1860", "section": "302"}]}]
    apply_currency([], claims, province="", index=index)
    assert claims[0]["currency"] == CURRENCY_UNKNOWN


def test_instrument_reaches_the_claim_source(index):
    """The UI shows "repealed by <instrument>, <date>" beside the claim, so the
    record has to survive onto the source entry."""
    claims = [{"index": 1, "text": "x", "support": "supported",
               "citation_status": "matched",
               "sources": [{"id": "1", "statute": "CrPC 1898", "section": "10"}]}]
    apply_currency([], claims, province="", index=index)
    assert claims[0]["sources"][0]["instrument"] == "Ordinance XXXVII of 2001"
    assert claims[0]["sources"][0]["date"] == "2001-08-13"


def test_judgments_are_left_unknown(index):
    """The omission map is statutory. A judgment is not repealed by an amending
    Act — it is overruled, which this system does not track."""
    citations = [{"statute": "PLD 2021 Lahore 55", "section": "",
                  "type": "judgment", "status": "matched"}]
    apply_currency(citations, [], province="", index=index)
    assert citations[0]["currency"] == CURRENCY_UNKNOWN


# ── fail-open ─────────────────────────────────────────────────────────────────

def test_a_broken_index_yields_unknown_not_an_exception():
    """A currency check must never be the reason an answer fails."""
    class Exploding:
        def coverage(self, _statute):
            raise RuntimeError("chroma down")

    assert currency_for("CrPC 1898", "10", "", Exploding())["currency"] == CURRENCY_UNKNOWN


def test_apply_currency_never_raises_on_junk(index):
    citations = [{}, {"statute": None, "section": None}]
    claims = [{"index": 1}, {"index": 2, "sources": None}]
    apply_currency(citations, claims, province="", index=index)
    assert all(c.get("currency") == CURRENCY_UNKNOWN for c in claims)


@pytest.mark.parametrize("statute,section", [("", "10"), ("CrPC 1898", ""), ("", "")])
def test_empty_inputs_are_unknown(index, statute, section):
    assert currency_for(statute, section, "", index)["currency"] == CURRENCY_UNKNOWN


# ── describe() must not claim currency from corpus presence ───────────────────

def test_describe_never_claims_a_section_is_in_force(index):
    """This string is embedded in the VERIFIED detail a lawyer reads. Saying
    "509 of 511 sections in force" for a statute with zero omission records
    turned an existence check into a currency claim it cannot support."""
    for statute in ("CrPC 1898", "PPC 1860"):
        text = index.coverage(statute).describe()
        assert "in force" not in text
        assert "held in corpus" in text


def test_describe_still_reports_repealed_exclusions(index):
    """The repeal count must survive the wording change — "410 of 411" without
    it reads as if we simply lost the others."""
    assert "repealed and excluded" in index.coverage("CrPC 1898").describe()
