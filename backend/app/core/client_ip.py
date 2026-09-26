"""Whose IP address this request actually came from — decision D8.

An evidence document must not assert a fact it cannot support. That makes the
question here narrower than "what IP shall we log?": it is "can we say, and
stand behind, where this request came from?" When the answer is no, the honest
output is NOTHING, not a best guess with a caveat attached.

Two ways to get it wrong, and this module refuses both:

  TRUSTING THE HEADER BLINDLY. `X-Forwarded-For` is caller-supplied text. Any
  client can send one, so reading it without checking who connected lets a
  signer write their own IP into the signature record -- a forgery the document
  would then present as evidence.

  IGNORING THE PROXY. Behind a reverse proxy every request appears to come from
  the proxy's own address. Recording that as "the IP the signer used" is a
  false statement about a real person, repeated on every row.

So the header is read ONLY when the immediate peer is a configured trusted
proxy, and otherwise the socket address is used. If neither can be established,
the result is None and the caller omits the field.
"""
from __future__ import annotations

import ipaddress

from app.core.config import settings


def trusted_proxies() -> set[str]:
    """Configured proxy peer addresses. Empty means "no proxy in front"."""
    raw = settings.trusted_proxies or ""
    return {part.strip() for part in raw.split(",") if part.strip()}


def _valid(candidate: str | None) -> str | None:
    """A syntactically real IP, or None.

    `X-Forwarded-For` is text from the network. A malformed or absurd value
    ("unknown", an empty element, a hostname, 900.1.2.3) must not reach an
    evidence document merely because a trusted proxy passed it along -- the
    proxy vouches for the chain, not for the contents.
    """
    if not candidate:
        return None
    candidate = candidate.strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def client_ip(request) -> str | None:
    """The requesting client's IP, or None when it cannot be established.

    NONE IS A REAL ANSWER and callers must handle it rather than substituting a
    placeholder. "We do not know" is a true statement; "0.0.0.0" is not.
    """
    peer = getattr(request, "client", None)
    peer_host = getattr(peer, "host", None) if peer else None

    proxies = trusted_proxies()
    if proxies and peer_host in proxies:
        # The LEFTMOST entry is the original client. Everything to its right
        # was appended by intermediaries; everything to its left, if the chain
        # is longer than we trust, could have been sent by the client itself.
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0] if forwarded else ""
        return _valid(first)

    # No proxy configured, or the peer is not one of ours: the header is
    # untrustworthy, so the socket address is the only thing we can stand
    # behind. Behind an UNCONFIGURED proxy this is the proxy's address, which
    # is why `ip_is_verifiable` exists -- an evidence document asks that
    # question before printing anything.
    return _valid(peer_host)


def ip_is_verifiable(request) -> bool:
    """Whether the address from `client_ip` is safe to present AS THE CLIENT'S.

    True when there is no proxy in front (the socket address is the client's),
    or when the immediate peer is a configured trusted proxy (the header is
    vouched for). False when a forwarding header is present but its sender is
    not trusted -- that is precisely the unconfigured-proxy case, where the
    address we hold belongs to the proxy and printing it would misattribute a
    request to the wrong machine.
    """
    if client_ip(request) is None:
        return False

    proxies = trusted_proxies()
    peer = getattr(request, "client", None)
    peer_host = getattr(peer, "host", None) if peer else None
    if proxies:
        return peer_host in proxies

    # Nothing configured. A forwarding header means something IS in front of
    # us that we were not told about, so the socket address is that thing's,
    # not the client's.
    return not request.headers.get("x-forwarded-for")
