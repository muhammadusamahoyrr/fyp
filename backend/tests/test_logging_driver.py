"""Logging never carries document content (ANALYZER_PII_MASKING.md).

The MongoDB driver's DEBUG command log prints whole documents -- analyzer
text, names, CNICs. setup_logging pins it to WARNING whatever LOG_LEVEL says.
"""
from __future__ import annotations

import logging

from app.core.config import settings


def test_the_database_driver_never_logs_documents(monkeypatch):
    """pymongo's DEBUG command log prints whole documents (text, names,
    CNICs). It stays at WARNING even when LOG_LEVEL is DEBUG."""
    from app.core import logging as app_logging

    original = settings.log_level
    try:
        monkeypatch.setattr(settings, "log_level", "DEBUG")
        app_logging.setup_logging()
        assert logging.getLogger().level == logging.DEBUG
        for name in ("pymongo", "pymongo.command", "motor"):
            assert logging.getLogger(name).getEffectiveLevel() == logging.WARNING, name
    finally:
        monkeypatch.setattr(settings, "log_level", original)
        app_logging.setup_logging()
