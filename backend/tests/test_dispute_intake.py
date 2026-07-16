"""Phase 5a dispute-intake tests.

The load-bearing rule is the confidence gate: an unconfirmed OR ambiguous grievance
classification must NEVER reach drafting — it holds for a lawyer. That decision is
pure (needs_triage / _decide_state), so it is tested directly and exhaustively. The
LLM call itself is exercised live, not unit-tested.
"""
import pytest
from pydantic import ValidationError

from app.services import dispute_intake as di
from app.services import special_court as sc


# ── eligibility (deterministic) ──────────────────────────────────────────────

@pytest.mark.parametrize("id_type", ["passport", "CNIC", "nicop", "POC", "opf"])
def test_valid_id_with_enough_days_is_eligible(id_type):
    r = di.check_eligibility(id_type, 200)
    assert r["eligible"] is True


def test_wrong_id_type_is_ineligible():
    r = di.check_eligibility("driving_licence", 300)
    assert r["eligible"] is False
    assert r["id_ok"] is False
    assert any("passport" in reason.lower() for reason in r["reasons"])


def test_too_few_days_is_ineligible():
    r = di.check_eligibility("nicop", 100)
    assert r["eligible"] is False
    assert r["days_ok"] is False
    assert any("182" in reason for reason in r["reasons"])


def test_exactly_182_days_qualifies():
    assert di.check_eligibility("nicop", 182)["eligible"] is True


def test_non_numeric_days_is_ineligible_not_a_crash():
    assert di.check_eligibility("nicop", "lots")["eligible"] is False


# ── the confidence hold-rule (pure) ──────────────────────────────────────────

def test_clean_established_classification_proceeds():
    c = {"category": "illegal_occupation", "confidence": "established", "alternatives": []}
    assert di.needs_triage(c) is False


def test_single_source_with_no_alternatives_proceeds():
    c = {"category": "poa_misuse", "confidence": "single_source", "alternatives": []}
    assert di.needs_triage(c) is False


def test_unconfirmed_always_holds():
    c = {"category": "illegal_occupation", "confidence": "unconfirmed", "alternatives": []}
    assert di.needs_triage(c) is True


def test_ambiguous_with_alternatives_holds_even_when_confident():
    """The model named another plausible category → ambiguous → hold, regardless of
    the stated confidence."""
    c = {"category": "fraudulent_transfer", "confidence": "established",
         "alternatives": ["poa_misuse"]}
    assert di.needs_triage(c) is True


def test_unknown_category_holds():
    c = {"category": "not_a_category", "confidence": "established", "alternatives": []}
    assert di.needs_triage(c) is True


# ── guided intake: fixed fields only ─────────────────────────────────────────

def _valid_intake(**over):
    base = dict(property_description="House 5 DHA", province="punjab",
                opposing_party="Cousin Ahmed", timeline="since Jan 2026",
                documents_held=["title_deed_fard"], relief_wanted="restore_possession")
    base.update(over)
    return di.DisputeIntake(**base)


def test_valid_intake_accepts_fixed_fields():
    m = _valid_intake()
    assert m.province == "punjab"
    assert m.relief_wanted == "restore_possession"


def test_relief_must_be_from_the_fixed_set():
    with pytest.raises(ValidationError):
        _valid_intake(relief_wanted="make_them_pay")


def test_documents_must_be_from_the_fixed_set():
    with pytest.raises(ValidationError):
        _valid_intake(documents_held=["title_deed_fard", "random_doc"])


def test_required_fields_are_enforced():
    with pytest.raises(ValidationError):
        di.DisputeIntake(province="punjab", opposing_party="X", timeline="Y",
                         relief_wanted="injunction")  # missing property_description


# ── state decision (pure) — the whole 5a outcome ─────────────────────────────

_OK_ELIG = {"eligible": True}
_OK_GRIEV = {"needs_triage": False}
_OPERATIONAL = {"province": "ICT", "court_status": sc.OPERATIONAL}


def test_all_green_is_ready_for_drafting():
    d = di._decide_state(_OK_ELIG, _OK_GRIEV, _OPERATIONAL)
    assert d["state"] == di.STATE_READY
    assert d["hold_reasons"] == []


def test_ineligible_holds():
    d = di._decide_state({"eligible": False}, _OK_GRIEV, _OPERATIONAL)
    assert d["state"] == di.STATE_HELD
    assert any("eligibility" in r.lower() for r in d["hold_reasons"])


def test_grievance_needing_triage_holds():
    d = di._decide_state(_OK_ELIG, {"needs_triage": True}, _OPERATIONAL)
    assert d["state"] == di.STATE_HELD
    assert any("classified" in r.lower() for r in d["hold_reasons"])


def test_unconfirmed_court_holds_and_mentions_federal():
    pending = {"province": "Punjab", "court_status": sc.ENACTED_PENDING}
    d = di._decide_state(_OK_ELIG, _OK_GRIEV, pending)
    assert d["state"] == di.STATE_HELD
    assert any("federal" in r.lower() for r in d["hold_reasons"])


def test_multiple_problems_list_all_hold_reasons():
    d = di._decide_state({"eligible": False}, {"needs_triage": True},
                         {"province": "Sindh", "court_status": sc.NONE_YET})
    assert d["state"] == di.STATE_HELD
    assert len(d["hold_reasons"]) == 3


# ── 5c: triage notification message (pure) ───────────────────────────────────

def test_join_or_reads_naturally():
    assert di._join_or(["a"]) == "a"
    assert di._join_or(["a", "b"]) == "a or b"
    assert di._join_or(["a", "b", "c"]) == "a, b or c"


def test_triage_message_names_the_ambiguous_categories_in_plain_language():
    rec = {
        "grievance": {"needs_triage": True, "category": "fraudulent_transfer",
                      "alternatives": ["poa_misuse"]},
        "eligibility": {"eligible": True},
        "jurisdiction": {"court_status": sc.OPERATIONAL, "province": "ICT"},
    }
    title, body = di._triage_message(rec)
    assert title
    # plain-language labels, not category codes
    assert "fraudulent sale or transfer" in body
    assert "misuse of a power of attorney" in body
    assert "fraudulent_transfer" not in body and "poa_misuse" not in body


def test_triage_message_avoids_jargon_and_gives_a_next_step():
    rec = {"grievance": {"needs_triage": True, "category": None, "alternatives": []},
           "eligibility": {"eligible": True},
           "jurisdiction": {"court_status": sc.OPERATIONAL, "province": "ICT"}}
    _, body = di._triage_message(rec)
    assert "unconfirmed" not in body.lower()   # never show the internal tier name
    assert "Lawyers" in body                    # a clear CTA into the marketplace


def test_triage_message_explains_ineligibility_and_pending_court():
    rec = {"grievance": {"needs_triage": False},
           "eligibility": {"eligible": False},
           "jurisdiction": {"court_status": sc.ENACTED_PENDING, "province": "Punjab"}}
    _, body = di._triage_message(rec)
    assert "overseas-Pakistani status" in body
    assert "Punjab" in body and "not confirmed running" in body


# ── case-brief packaging (pure — the lawyer-handoff view) ────────────────────

def _dispute_doc(**over):
    """A persisted dispute record, ready state, with a drafted+shared petition."""
    base = {
        "_id": "disp1",
        "client_id": "client1",
        "state": di.STATE_READY,
        "hold_reasons": [],
        "eligibility": {"eligible": True, "id_ok": True, "days_ok": True, "reasons": []},
        "grievance": {"category": "illegal_occupation", "category_label": "someone took possession",
                      "confidence": "established", "alternatives": [], "reasoning": "clear",
                      "needs_triage": False},
        "intake": {"property_description": "House 12, F-8/3", "province": "ICT",
                   "opposing_party": "Kamran", "timeline": "March 2026",
                   "documents_held": ["title_deed_fard"], "relief_wanted": "restore_possession"},
        "jurisdiction": {"province": "Islamabad Capital Territory / federal",
                         "court_status": sc.OPERATIONAL, "appeal_days": 15, "disposal_days": 90},
        "petition_document_id": "doc99",
        "petition_drafted_at": "2026-07-15T00:00:00+00:00",
        "petition_shared": True,
        "assigned_lawyer_id": "law1",
        "assigned_lawyer": {"id": "law1", "name": "Adv. Ayesha", "kyc_verified": True},
        "sent_to_lawyer_at": "2026-07-15T01:00:00+00:00",
        "created_at": "2026-07-15T00:00:00+00:00",
        "updated_at": "2026-07-15T01:00:00+00:00",
    }
    base.update(over)
    return base


def test_case_brief_packages_every_section():
    """The brief is the single handoff surface — it must carry all five packaged
    parts plus the petition link, or a lawyer sees a hole instead of the case."""
    b = di._case_brief(_dispute_doc(), {"full_name": "Bilal Overseas"})
    for section in ("eligibility", "grievance", "intake", "jurisdiction", "petition", "assignment"):
        assert b.get(section) is not None, f"brief dropped {section}"
    assert b["client"]["name"] == "Bilal Overseas"
    assert b["grievance"]["category"] == "illegal_occupation"
    assert b["grievance"]["confidence"] == "established"
    assert b["grievance"]["alternatives"] == []
    assert b["jurisdiction"]["appeal_days"] == 15


def test_case_brief_builds_the_petition_download_link():
    b = di._case_brief(_dispute_doc(), None)
    assert b["petition"]["document_id"] == "doc99"
    assert b["petition"]["download_url"] == "/api/v1/documents/doc99/download"
    assert b["petition"]["shared_with_lawyer"] is True


def test_case_brief_petition_is_null_when_none_drafted():
    """A held dispute with no petition still produces a full brief — petition just null,
    never a missing key (the silent-drop class this whole module guards against)."""
    doc = _dispute_doc(state=di.STATE_HELD, petition_document_id=None,
                       hold_reasons=["a lawyer should confirm the forum"])
    b = di._case_brief(doc, None)
    assert "petition" in b and b["petition"] is None
    assert b["hold_reasons"] == ["a lawyer should confirm the forum"]


def test_case_brief_assignment_is_null_before_send():
    doc = _dispute_doc(assigned_lawyer_id=None, assigned_lawyer=None)
    b = di._case_brief(doc, None)
    assert "assignment" in b and b["assignment"] is None


def test_lawyer_card_strips_to_non_sensitive_identity():
    lawyer = {"_id": "law1", "full_name": "Adv. Ayesha", "province": "punjab",
              "password_hash": "SECRET", "cnic_encrypted": "SECRET",
              "lawyer_profile": {"kyc_verified": True, "rating": 4.8,
                                 "specializations": ["property"]}}
    card = di._lawyer_card(lawyer)
    assert card == {"id": "law1", "name": "Adv. Ayesha", "province": "punjab",
                    "specializations": ["property"], "rating": 4.8, "kyc_verified": True}
    assert "password_hash" not in card and "cnic_encrypted" not in card
