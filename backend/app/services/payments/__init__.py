"""Pluggable payment providers.

MockProvider handles the full checkout → webhook loop locally so the entire
pay flow is demoable/testable with no merchant credentials. SafepayProvider
talks to Safepay's hosted checkout. `get_provider()` picks based on config —
the rest of the app is provider-agnostic (mirrors the WhatsApp dry-run pattern).
"""
from app.core.config import settings

from app.services.payments.mock import MockProvider
from app.services.payments.safepay import SafepayProvider


def get_provider():
    """Mock unless real Safepay credentials are configured and dry-run is off."""
    if settings.payments_dry_run or not settings.safepay_secret_key:
        return MockProvider()
    return SafepayProvider()


__all__ = ["get_provider", "MockProvider", "SafepayProvider"]
