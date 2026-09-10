"""Guards for the intake defects found in the 2026-09-10 audit.

Each test here failed before its fix and names the defect it protects, because
every one of these survived by being invisible: a missing import that the
surrounding `except Exception` reported as a provider outage, five validation
models imported by nothing, and three screens of collected answers that the
analysis never read.

The clarification tests assert on WHETHER THE MODEL WAS REACHED, not on what it
said. That is the property that broke — the call site raised NameError while
evaluating its own argument, so the provider was never contacted and the code
logged nothing and returned "no questions needed".
"""
from __future__ import annotations

import asyncio

import pytest

from app.core.exceptions import AppValidationError
from app.services import intake_service


TOKEN = "tok-guard"
CLIENT = "client-guard"


class FakeIntakeRepo:
    def __init__(self, doc):
        self.doc = doc
        self.saved_qa = None

    async def find_by_token(self, token):
        return dict(self.doc)

    async def save_clarification_qa(self, token, qa_list):
        self.saved_qa = qa_list
        return True

    async def update_step(self, token, step, data):
        self.doc[f"step{step}"] = data
        return True


def _doc(**over):
    d = {
        "_id": "i-guard",
        "session_token": TOKEN,
        "client_id": CLIENT,
        "completed": False,
        "case_id": None,
        "step1": {"province": "punjab"},
        "step2": {"case_type": "civil", "urgency": "medium"},
        "step3": {"incident_description": "My landlord locked my shop in Lahore."},
        "clarification_qa": [],
    }
    d.update(over)
    return d


# ── 1. the clarification LLM is actually reached ────────────────────────────

@pytest.fixture
def spy_llms(monkeypatch):
    """Replace both LLM factories with counters that refuse to do any work.

    Raising means no network, no provider key and no tokens are needed, while
    still proving the call site got far enough to ask for a model.
    """
    calls = {"llm": 0, "fast": 0}

    import app.ai.llm as llm_mod

    def spy(kind):
        def _f(*a, **k):
            calls[kind] += 1
            raise RuntimeError("spy: no provider in tests")
        return _f

    monkeypatch.setattr(llm_mod, "get_llm", spy("llm"))
    monkeypatch.setattr(llm_mod, "get_fast_llm", spy("fast"))
    return calls


async def test_clarification_reaches_the_model(spy_llms, monkeypatch):
    repo = FakeIntakeRepo(_doc())
    monkeypatch.setattr(intake_service, "intake_repo", repo)

    await intake_service.get_clarification(TOKEN, CLIENT, None)

    assert spy_llms["llm"] == 1, (
        "get_clarification returned without ever asking for a model — "
        "the PURPOSE_INTAKE_EXTRACTION NameError is back"
    )


async def test_low_confidence_classification_reaches_the_fast_model(spy_llms):
    # A description with no legal keywords scores 0.0, which is what sends the
    # decision to the LLM. Asserted rather than assumed, so this test cannot
    # quietly stop exercising the branch it exists for.
    from app.ai.nodes.classifier_node import _score_query

    description = "ambiguous zzz qqq nothing legal here"
    _, (best_score, _) = max(_score_query(description).items(), key=lambda x: x[1][0])
    assert best_score < 0.30, "fixture no longer exercises the low-confidence branch"

    await intake_service._ai_classify_case_type(description, "civil")

    assert spy_llms["fast"] == 1


async def test_a_provider_failure_still_lets_the_client_through(spy_llms, monkeypatch):
    """The fallback is correct behaviour and must survive the fix."""
    repo = FakeIntakeRepo(_doc())
    monkeypatch.setattr(intake_service, "intake_repo", repo)

    result = await intake_service.get_clarification(TOKEN, CLIENT, None)

    assert result["done"] is True
    assert result["question"] is None


async def test_a_provider_failure_is_logged_not_swallowed(spy_llms, monkeypatch, caplog):
    """A silent `except Exception` is how the NameError hid for so long."""
    repo = FakeIntakeRepo(_doc())
    monkeypatch.setattr(intake_service, "intake_repo", repo)

    with caplog.at_level("ERROR"):
        await intake_service.get_clarification(TOKEN, CLIENT, None)

    assert any("clarification" in r.message.lower() for r in caplog.records)


async def test_classification_failure_is_logged_not_swallowed(spy_llms, caplog):
    with caplog.at_level("ERROR"):
        await intake_service._ai_classify_case_type("ambiguous zzz qqq", "civil")

    assert any("classification" in r.message.lower() for r in caplog.records)


# ── 7. the step schemas are the contract ────────────────────────────────────

@pytest.mark.parametrize("step,data,bad_field", [
    (1, {"province": "Atlantis"}, "province"),
    (2, {"case_type": "banana", "urgency": "medium"}, "case_type"),
    (2, {"case_type": "civil", "urgency": "apocalyptic"}, "urgency"),
    (3, {"incident_description": "x" * 20_001}, "incident_description"),
    (4, {"has_evidence": True, "evidence_description": "y" * 5_001}, "evidence_description"),
    (5, {"desired_outcome": "z" * 5_001}, "desired_outcome"),
])
def test_invalid_step_data_is_rejected(step, data, bad_field):
    with pytest.raises(AppValidationError) as exc:
        intake_service._validate_step(step, data)
    assert bad_field in str(exc.value.detail)


def test_unknown_fields_are_rejected_not_stored():
    with pytest.raises(AppValidationError):
        intake_service._validate_step(1, {"province": "punjab", "smuggled": "x"})


def test_every_step_has_a_schema():
    assert set(intake_service.STEP_SCHEMAS) == {1, 2, 3, 4, 5}


@pytest.mark.parametrize("step,data", [
    (1, {"province": "punjab", "party_role": "plaintiff"}),
    (2, {"case_type": "civil", "urgency": "urgent"}),
    (3, {"incident_description": "A tenancy dispute.", "incident_date": None}),
    (4, {"has_evidence": True, "evidence_description": "Two receipts.", "opposing_party": None}),
    (5, {"desired_outcome": "Recover arrears", "additional_notes": None}),
])
def test_what_the_ui_actually_sends_is_accepted(step, data):
    """The schemas describe the real client, not an imagined one.

    They were written for a step 1 that collected a full name and a step 2
    whose urgency could be "emergency" — neither of which the intake UI has
    ever sent. Turning them on without this test would have rejected every
    real submission.
    """
    assert intake_service._validate_step(step, data)


def test_enums_are_stored_as_plain_strings():
    cleaned = intake_service._validate_step(1, {"province": "punjab"})
    assert cleaned["province"] == "punjab"
    assert type(cleaned["province"]) is str


def test_the_party_role_is_normalised():
    """The UI labels its cards "Plaintiff"/"Defendant" and sends them as shown."""
    cleaned = intake_service._validate_step(1, {"province": "punjab", "party_role": "Plaintiff"})
    assert cleaned["party_role"] == "plaintiff"


def test_saving_one_step_does_not_backfill_defaults():
    cleaned = intake_service._validate_step(4, {"has_evidence": True})
    assert cleaned == {"has_evidence": True}


# ── 5. collected answers reach the case and the analysis ────────────────────

@pytest.fixture
def converted(monkeypatch):
    """Run a full conversion over fakes and hand back what each layer saw."""
    seen = {}
    doc = _doc(
        step1={"province": "punjab", "party_role": "defendant"},
        step2={"case_type": "civil", "urgency": "high"},
        step4={"has_evidence": True, "evidence_description": "Two rent receipts.",
               "opposing_party": "Mr Ahmed Khan"},
        step5={"desired_outcome": "Recover the arrears", "additional_notes": "Urdu preferred."},
        evidence_files=[{"file_id": "f1"}, {"file_id": "f2"}],
    )

    class Repo(FakeIntakeRepo):
        async def claim_conversion(self, token, ttl): return True
        async def release_conversion(self, token): return True
        async def attach_case(self, token, case_id): self.doc["case_id"] = case_id; return True
        async def mark_completed(self, token, case_id, **kw): self.doc["completed"] = True; return True
        async def save_ai_structured_case(self, token, data): return True

    class CaseRepo:
        async def find_by_id(self, cid): return None
        async def update_one(self, f, u): return True

    async def fake_create_case(client_id, data):
        seen["case_data"] = data
        return {"_id": "case-x"}

    async def fake_classify(desc, user_sel):
        seen["classified_on"] = desc
        return user_sel, False

    async def fake_run_ai(**kw):
        seen["ai_query"] = kw["query"]
        seen["ai_urgency"] = kw["urgency"]
        return {"summary": "ok"}

    async def fake_match(cid): pass

    monkeypatch.setattr(intake_service, "intake_repo", Repo(doc))
    monkeypatch.setattr(intake_service, "case_repo", CaseRepo())
    monkeypatch.setattr(intake_service, "create_case", fake_create_case)
    monkeypatch.setattr(intake_service, "_ai_classify_case_type", fake_classify)
    monkeypatch.setattr(intake_service, "_run_intake_ai", fake_run_ai)
    monkeypatch.setattr(intake_service, "_auto_match_lawyers", fake_match)
    return seen


async def test_the_desired_outcome_reaches_the_analysis(converted):
    await intake_service.convert_to_case(TOKEN, CLIENT)
    await asyncio.sleep(0)
    assert "Recover the arrears" in converted["ai_query"]


async def test_the_evidence_reaches_the_analysis(converted):
    await intake_service.convert_to_case(TOKEN, CLIENT)
    await asyncio.sleep(0)
    assert "Two rent receipts." in converted["ai_query"]
    assert "2 file(s)" in converted["ai_query"]


async def test_the_party_role_reaches_the_analysis(converted):
    await intake_service.convert_to_case(TOKEN, CLIENT)
    await asyncio.sleep(0)
    assert "defendant" in converted["ai_query"]


async def test_the_opposing_party_reaches_the_analysis(converted):
    await intake_service.convert_to_case(TOKEN, CLIENT)
    await asyncio.sleep(0)
    assert "Mr Ahmed Khan" in converted["ai_query"]


async def test_the_case_carries_the_collected_answers(converted):
    await intake_service.convert_to_case(TOKEN, CLIENT)
    await asyncio.sleep(0)
    data = converted["case_data"]
    assert data["party_role"] == "defendant"
    assert data["desired_outcome"] == "Recover the arrears"
    assert data["evidence_count"] == 2
    assert data["has_evidence"] is True
    assert data["urgency"] == "high"


async def test_classification_still_runs_on_the_bare_description(converted):
    """The enrichment must not leak into the classifier's input.

    Steps 4 and 5 are full of domain words — "arrears", "receipts" — and the
    keyword classifier scores exactly those. Feeding it the enriched text would
    let the client's wish list decide the case type.
    """
    await intake_service.convert_to_case(TOKEN, CLIENT)
    await asyncio.sleep(0)
    assert converted["classified_on"] == "My landlord locked my shop in Lahore."


async def test_the_case_title_stays_the_clients_own_words(converted):
    await intake_service.convert_to_case(TOKEN, CLIENT)
    await asyncio.sleep(0)
    assert converted["case_data"]["title"].startswith("My landlord locked my shop")
