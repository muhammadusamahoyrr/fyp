"""Production settings from `.env` never reach the tests (tests/conftest.py).

Before this, the suite read the developer's `.env` and so pointed at a hosted
Redis, Gmail SMTP and the model providers; only the network guard stopped the
connections. These pin the neutralisation itself.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest

LIVE = os.environ.get("AAI_LIVE_TESTS") == "1"


def test_no_hosted_redis_smtp_or_payment_credentials_are_configured():
    from app.core.config import settings

    host = urlparse(settings.redis_url).hostname if settings.redis_url else None
    assert host in (None, "localhost", "127.0.0.1"), "tests must never see a hosted Redis"
    assert settings.smtp_user == "" and settings.smtp_password == ""
    assert settings.safepay_api_key == "" and settings.safepay_secret_key == ""
    assert settings.safepay_webhook_secret == ""
    assert os.environ["HF_HUB_OFFLINE"] == "1"


@pytest.mark.skipif(LIVE, reason="the live tier keeps the provider keys it exercises")
def test_no_model_provider_key_is_configured():
    from app.core.config import settings

    assert (settings.groq_api_key, settings.groq_api_key_2,
            settings.gemini_api_key, settings.openrouter_api_key) == ("", "", "", "")


async def test_email_is_not_attempted_without_explicit_configuration(monkeypatch):
    import aiosmtplib

    from app.utils import email

    async def must_not_send(*a, **k):
        raise AssertionError("an email was sent from a test")

    monkeypatch.setattr(aiosmtplib, "send", must_not_send)
    assert await email.send_password_reset_email("person@example.com", "token") is False
