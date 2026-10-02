"""Document Analyzer: the AI layer's provider contract and readiness.

The settings live in app/core/config.py; ai_config only validates them. One
provider, one pinned allowlisted model, a policy id and an honest ZDR record
-- or the analyzer stays closed. Offline: no provider is called here.
"""
from __future__ import annotations

import base64
from datetime import date

import pytest

from app.core.config import settings
from app.services.analyzer import ai_config, readiness

TODAY = date(2026, 10, 2)
GOOD = {"analyzer_ai": True, "analyzer_ai_provider": "groq",
        "analyzer_ai_model": "openai/gpt-oss-120b",
        "analyzer_ai_model_allowlist": "openai/gpt-oss-120b,openai/gpt-oss-20b",
        "analyzer_ai_policy_id": "AAI-AI-DP-001", "analyzer_ai_zdr_status": "unverified",
        "analyzer_ai_zdr_verified_on": "", "analyzer_ai_zdr_evidence": "",
        "analyzer_ai_synthetic_only": True, "groq_api_key": "test-key-not-real"}


def config(**changes):
    return settings.model_copy(update={**GOOD, **changes})


def test_the_defaults_keep_the_ai_layer_off_and_unclaimed():
    from app.core.config import Settings
    defaults = {name: f.default for name, f in Settings.model_fields.items()
                if name.startswith("analyzer_ai")}
    assert defaults["analyzer_ai"] is False and defaults["analyzer_ai_provider"] == "groq"
    assert defaults["analyzer_ai_model"] == "" and defaults["analyzer_ai_zdr_status"] == "unverified"
    assert defaults["analyzer_ai_synthetic_only"] is True


def test_a_consistent_configuration_has_no_problems_and_states_its_contract():
    good = config()
    assert ai_config.problems(good, TODAY) == []
    assert ai_config.contract(good, TODAY) == {
        "provider": "groq", "model": "openai/gpt-oss-120b", "fallback": None,
        "policy_id": "AAI-AI-DP-001", "zdr": {"status": "unverified", "verified_on": None},
        "synthetic_only": True}


@pytest.mark.parametrize("changes, problem", [
    ({"analyzer_ai_provider": "openrouter"}, ai_config.AI_PROVIDER_UNSUPPORTED),
    ({"analyzer_ai_model": ""}, ai_config.AI_MODEL_NOT_PINNED),
    ({"analyzer_ai_model": "llama-3.1-8b-instant"}, ai_config.AI_MODEL_NOT_ALLOWLISTED),
    ({"analyzer_ai_model_allowlist": " , "}, ai_config.AI_ALLOWLIST_EMPTY),
    ({"groq_api_key": ""}, ai_config.AI_KEY_MISSING),
    ({"analyzer_ai_policy_id": ""}, ai_config.AI_POLICY_ID_MISSING),
    ({"analyzer_ai_policy_id": "checklist one"}, ai_config.AI_POLICY_ID_MISSING),
    ({"analyzer_ai_zdr_status": "yes"}, ai_config.AI_ZDR_STATUS_INVALID),
    ({"analyzer_ai_zdr_status": "verified"}, ai_config.AI_ZDR_CLAIM_UNSUPPORTED),
    ({"analyzer_ai_zdr_status": "verified", "analyzer_ai_zdr_verified_on": "2026-09-01"},
     ai_config.AI_ZDR_CLAIM_UNSUPPORTED),                                  # no evidence
    ({"analyzer_ai_zdr_status": "verified", "analyzer_ai_zdr_verified_on": "2027-01-01",
      "analyzer_ai_zdr_evidence": "Groq data controls screenshot, ticket 12"},
     ai_config.AI_ZDR_CLAIM_UNSUPPORTED),                                  # a future date
    ({"analyzer_ai_synthetic_only": False}, ai_config.AI_REAL_DOCUMENTS_NEED_ZDR),
])
def test_each_inconsistency_is_named(changes, problem):
    assert problem in ai_config.problems(config(**changes), TODAY)


def test_problems_never_echo_keys_models_or_evidence():
    bad = config(groq_api_key="", analyzer_ai_model="secret-model-x",
                 analyzer_ai_zdr_status="verified", analyzer_ai_zdr_evidence="private note")
    text = " ".join(ai_config.problems(bad, TODAY))
    assert "secret-model-x" not in text and "private note" not in text


def test_zdr_is_said_only_when_a_person_verified_it():
    claimed = config(analyzer_ai_zdr_status="verified")
    assert ai_config.contract(claimed, TODAY)["zdr"] == {"status": "unverified", "verified_on": None}
    verified = config(analyzer_ai_zdr_status="verified", analyzer_ai_zdr_verified_on="2026-09-30",
                      analyzer_ai_zdr_evidence="Groq data controls export, kept in ops/zdr/2026-09-30",
                      analyzer_ai_synthetic_only=False)
    assert ai_config.problems(verified, TODAY) == []
    assert ai_config.contract(verified, TODAY)["zdr"] == {"status": "verified",
                                                          "verified_on": "2026-09-30"}


# ── readiness reads the central configuration ────────────────────────────────

@pytest.fixture
def ready_otherwise(monkeypatch):
    monkeypatch.setattr(settings, "analyzer_keks", "k1:" + base64.b64encode(b"\x01" * 32).decode())
    monkeypatch.setattr(settings, "analyzer_kek_active", "k1")

    async def replica():
        return True
    monkeypatch.setattr(readiness, "transactions_supported", replica)
    readiness._reset_for_tests()
    yield monkeypatch
    readiness._reset_for_tests()


async def test_ai_off_is_not_checked(app_indexes, ready_otherwise):
    ready_otherwise.setattr(settings, "analyzer_ai", False)
    ready_otherwise.setattr(settings, "analyzer_ai_model", "")
    assert await readiness.refresh() == []
    assert readiness.is_ready() is True


async def test_an_inconsistent_ai_contract_closes_the_analyzer(app_indexes, ready_otherwise):
    for name, value in {**GOOD, "analyzer_ai_model": "llama-3.1-8b-instant"}.items():
        ready_otherwise.setattr(settings, name, value)
    assert await readiness.refresh() == [ai_config.AI_MODEL_NOT_ALLOWLISTED]
    assert readiness.is_ready() is False


async def test_a_consistent_ai_contract_is_ready(app_indexes, ready_otherwise):
    for name, value in GOOD.items():
        ready_otherwise.setattr(settings, name, value)
    assert await readiness.refresh() == []
    assert readiness.is_ready() is True
