"""The default test run is held to loopback (tests/conftest.py).

Before this guard, a full run quietly reached smtp.gmail.com, huggingface.co
and the production Upstash Redis through the developer's `.env`. These tests
pin the guard itself: a non-local lookup is refused and recorded, loopback
still resolves. They are skipped in the live tier, where the guard is off.
"""
from __future__ import annotations

import os
import socket
import sys

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("AAI_LIVE_TESTS") == "1",
                                reason="the guard is off in the live tier")


def test_a_non_local_lookup_is_refused_and_recorded():
    with pytest.raises(OSError, match="AAI_LIVE_TESTS=1") as refused:
        socket.getaddrinfo("api.groq.com", 443)
    # The conftest pytest actually loaded (importing `tests.conftest` would
    # give a second, inactive copy of the module).
    guard = sys.modules[refused.type.__module__]
    assert refused.type is guard.ExternalNetworkBlocked
    assert guard.BLOCKED_LOOKUPS[-1] == "api.groq.com"
    guard.BLOCKED_LOOKUPS.pop()                  # keep the end-of-run summary honest


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1", None])
def test_loopback_still_resolves(host):
    assert socket.getaddrinfo(host, 80 if host else "http")
