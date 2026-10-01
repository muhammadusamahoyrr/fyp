"""Document Analyzer, P2A: the playbook engine, the general pack and approvals.

Pure tests for loading and running packs; Mongo for approvals (any Mongo --
no transaction is involved). Legal packs here are TEST fixtures written into
a temporary directory: the repository ships no legal pack in P2A.
"""
from __future__ import annotations

import textwrap

import pytest

from app.services.analyzer import playbook_engine as engine
from app.services.analyzer import segmentation as seg
from app.services.analyzer.playbook_dsl import PlaybookError

LEASE = """TENANCY AGREEMENT
This agreement is made at Lahore on 1 October 2026 between the Landlord and the Tenant.
1. The term is eleven (11) months.
2. Rent is Rs. 85,000 per month.
3. Either party may terminate on one month's notice.
Signed in the presence of two witnesses.
"""

LEGAL = textwrap.dedent("""\
    id: test_legal
    version: 1
    scope: legal_playbook
    requires_approval: true
    required_qualification: pk.punjab.tenancy
    title: Test legal pack
    applies_if: {all: [{eq: [{field: document_type}, {value: tenancy}]},
                       {eq: [{field: jurisdiction}, {value: punjab}]}]}
    checks:
      - id: registrar_reminder
        kind: reminder
        title: Presentation to the Rent Registrar
        why: A reminder; it cannot be seen from the text.
        authority: {statute: Punjab Rented Premises Act 2009, section: "5(2)"}
      - id: long_lease
        kind: legal_check
        title: Long-lease limb
        why: Applies only to long leases.
        applies_if: {gt: [{field: terms.term_months}, {value: 12}]}
        locate: {any_of: ['registered']}
        authority: {statute: Registration Act 1908, section: "17(1)(d)"}
      - id: year_to_year
        kind: legal_check
        title: Year-to-year limb
        why: Depends on a term the person may not have stated.
        applies_if: {eq: [{field: terms.tenancy_year_to_year}, {value: true}]}
        locate: {any_of: ['registered']}
        authority: {statute: Registration Act 1908, section: "17(1)(d)"}
""")

TENANCY = {"document_type": "tenancy", "jurisdiction": "punjab",
           "terms": {"term_months": 11, "rent_period": "monthly", "tenancy_year_to_year": None}}


def sentences_of(text):
    _, sentences = seg.segment(text, [])
    return [{"sentence_id": s.sentence_id, "start": s.start, "end": s.end} for s in sentences]


# ── loading ──────────────────────────────────────────────────────────────────

def test_the_shipped_packs_load():
    packs = {p.id: p for p in engine.load_packs()}
    assert set(packs) == {"general", "tenancy_punjab", "nda", "employment"}
    assert packs["general"].scope == "general_review" and packs["general"].requires_approval is False
    assert all(p.requires_approval for k, p in packs.items() if k != "general")


def test_the_hash_ignores_line_endings_and_nothing_else():
    lf = LEGAL
    assert engine.content_hash(lf) == engine.content_hash(lf.replace("\n", "\r\n"))
    assert engine.content_hash(lf) != engine.content_hash(lf + "# a comment\n")


@pytest.mark.parametrize("edit,message", [
    (("requires_approval: true", "requires_approval: false"), "always requires lawyer approval"),
    (('    authority: {statute: Registration Act 1908, section: "17(1)(d)"}\n  - id: year_to_year',
      '  - id: year_to_year'), "must cite its authority"),
    (("kind: reminder", "kind: general_check"), "not allowed in a legal_playbook pack"),
    (("locate: {any_of: ['registered']}\n    authority: {statute: Registration Act 1908, section: \"17(1)(d)\"}\n  - id: year_to_year",
      "locate: {any_of: ['(unclosed']}\n    authority: {statute: Registration Act 1908, section: \"17(1)(d)\"}\n  - id: year_to_year"), "invalid pattern"),
    (("id: year_to_year", "id: long_lease"), "unique"),
    (("applies_if: {all:", "applies_if_typo: {all:"), "unknown keys"),
    (("{value: 12}", "{value: '12'}"), "compares int with str"),
])
def test_malformed_packs_never_load(edit, message):
    old, new = edit
    assert old in LEGAL, old
    with pytest.raises(PlaybookError, match=message):
        engine.parse_pack(LEGAL.replace(old, new, 1))


def test_a_general_pack_may_not_cite_law():
    general = (engine.PLAYBOOK_DIR / "general.yaml").read_text(encoding="utf-8")
    bad = general.replace("    title: The parties are named\n",
                          "    title: The parties are named\n    authority: {statute: X, section: '1'}\n", 1)
    with pytest.raises(PlaybookError, match="cites no law"):
        engine.parse_pack(bad)


# ── running the general pack ─────────────────────────────────────────────────

def test_the_general_pack_finds_what_is_there_and_says_not_located_otherwise():
    general = next(p for p in engine.load_packs() if p.id == "general")
    findings = engine.run_pack(general, TENANCY, LEASE, sentences_of(LEASE))
    by_id = {f["check_id"]: f for f in findings}
    for present in ("parties_named", "date_stated", "signature_block", "duration_stated",
                    "payment_terms", "termination"):
        assert by_id[present]["check_result"] == "present", present
        assert by_id[present]["sentence_ids"], present
    for absent in ("disputes", "governing_law"):
        assert by_id[absent]["check_result"] == "not_located"
    assert all(f["labels"] == ["General document review"] for f in findings)
    assert not any("missing" in str(f).lower() for f in findings)


def test_locators_match_whole_words_only():
    text = "The determination of the price is final."      # 'terminat' inside a word
    general = next(p for p in engine.load_packs() if p.id == "general")
    by_id = {f["check_id"]: f for f in engine.run_pack(general, TENANCY, text, sentences_of(text))}
    assert by_id["termination"]["check_result"] == "not_located"


# ── legal packs: applicability, three-valued checks, approval ────────────────

@pytest.fixture
def legal_dir(tmp_path, monkeypatch):
    (tmp_path / "general.yaml").write_text(
        (engine.PLAYBOOK_DIR / "general.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "test_legal.yaml").write_text(LEGAL, encoding="utf-8")
    monkeypatch.setattr(engine, "PLAYBOOK_DIR", tmp_path)
    return tmp_path


async def test_an_unapproved_legal_pack_is_reported_and_never_run(legal_dir, mongo):
    findings, summary = await engine.analyse(TENANCY, LEASE, sentences_of(LEASE))
    status = {p["pack_id"]: p["status"] for p in summary}
    assert status == {"general": "applied", "test_legal": "awaiting_approval"}
    assert not any(f["pack_id"] == "test_legal" for f in findings)


async def test_an_approved_pack_runs_with_three_valued_checks(legal_dir, mongo):
    pack = next(p for p in engine.load_packs() if p.id == "test_legal")
    await mongo["analysis_playbook_approvals"].insert_one(
        {"pack_id": pack.id, "content_hash": pack.content_hash, "version": 1,
         "authorities_hash": pack.authorities_hash,
         "reviewer_user_id": "lawyer-x", "reviewer_role": "test", "active": True})
    try:
        findings, summary = await engine.analyse(TENANCY, LEASE, sentences_of(LEASE))
        legal = {f["check_id"]: f for f in findings if f["pack_id"] == "test_legal"}
        assert {p["pack_id"]: p["status"] for p in summary}["test_legal"] == "applied"
        assert legal["registrar_reminder"]["check_result"] is None          # a statement
        assert legal["long_lease"]["check_result"] == "not_applicable"      # 11 <= 12
        assert legal["year_to_year"]["check_result"] == "unable_to_determine"
        assert "not stated" in legal["year_to_year"]["reason"]
        assert legal["long_lease"]["labels"] == ["Legal playbook applied",
                                                 "Applicability requires lawyer review"]

        # Edit one character: the approval no longer matches, the pack stops running.
        (legal_dir / "test_legal.yaml").write_text(LEGAL + "# edited\n", encoding="utf-8")
        _, summary = await engine.analyse(TENANCY, LEASE, sentences_of(LEASE))
        assert {p["pack_id"]: p["status"] for p in summary}["test_legal"] == "awaiting_approval"
    finally:
        await mongo["analysis_playbook_approvals"].delete_many({"pack_id": "test_legal"})


async def test_pack_applicability_on_other_and_unknown_contexts(legal_dir, mongo):
    _, summary = await engine.analyse({**TENANCY, "jurisdiction": "other"}, LEASE, sentences_of(LEASE))
    assert {p["pack_id"]: p["status"] for p in summary}["test_legal"] == "not_applicable"
    _, summary = await engine.analyse({**TENANCY, "jurisdiction": None}, LEASE, sentences_of(LEASE))
    assert {p["pack_id"]: p["status"] for p in summary}["test_legal"] == "unable_to_determine"


def test_an_amount_alone_is_located_despite_the_word_guards():
    # Regression: '\d' followed by another digit failed the whole-word guard,
    # so "Rs. 85,000" was never matched by the amount pattern itself.
    text = "The total is Rs. 85,000 only."
    general = next(p for p in engine.load_packs() if p.id == "general")
    by_id = {f["check_id"]: f for f in engine.run_pack(general, TENANCY, text, sentences_of(text))}
    assert by_id["payment_terms"]["check_result"] == "present"
