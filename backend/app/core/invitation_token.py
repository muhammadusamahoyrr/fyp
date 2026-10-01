"""Signing invitations for people who have no account.

WHAT A TOKEN PROVES, AND WHAT IT DOES NOT
-----------------------------------------
It proves that whoever holds it received the invitation that was sent to a
particular email address, for one particular slot on one particular agreement.
That is all. It is NOT evidence of who the person is: nobody checked a document,
nobody authenticated against an account, and an email address can be forwarded,
shared or read by someone it was not meant for.

Everything downstream has to keep that distinction. The audit record says the
invitation was sent to an address and that the holder of the token signed. It
must not say the signer's identity was verified, because the product did not
verify it — the same discipline that removed the cipher and ETO-classification
claims from the UI.

ONLY THE HASH IS STORED
-----------------------
The database holds SHA-256 of the token, never the token. A leaked backup is
then a list of useless digests rather than a set of working signing
credentials. This is the same reason a password is not stored, and it is worth
saying plainly: if the stored value can be replayed, storing it "securely" is
not a mitigation.

No salt and no KDF, deliberately, and the reason is the opposite of the
password case. A token is 256 bits from `secrets`, so there is no dictionary to
attack and nothing to slow down; a per-row salt would only stop us looking the
token up, which is the one operation this has to support.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

#: 32 bytes = 256 bits. `token_urlsafe` gives ~43 characters, safe in a JSON
#: body and in an email, and far beyond guessing.
_TOKEN_BYTES = 32

#: How long an invitation stays usable.
#:
#: SHORTENED 30 -> 7 ON 2026-09-24, when invitations started going out by email.
#: While the creator passed the link on by hand, its exposure was whatever they
#: chose; an emailed link sits in an inbox, in that inbox's backups, and on
#: every mail server in between, and it is bearer authority to sign. Seven days
#: is long enough for a signer who reads email a few times a week and short
#: enough that a stale message is not a live credential months later.
#:
#: The cost is real and accepted: a signer who is away for two weeks comes back
#: to a dead link and needs a fresh invitation. That is the safer failure.
DEFAULT_TTL_DAYS = 7


def new_token() -> str:
    """A fresh invitation token. Returned to the caller ONCE and never stored."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def token_hash(token: str) -> str:
    """What goes in the database."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def matches(token: str, stored_hash: str) -> bool:
    """Constant-time comparison.

    `==` on a digest leaks, through timing, how many leading characters were
    right. That is a slow oracle but a real one, and `compare_digest` costs
    nothing to use.
    """
    return hmac.compare_digest(token_hash(token), stored_hash or "")


def expires_at(ttl_days: int = DEFAULT_TTL_DAYS) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=ttl_days)


def invitation_state(invite: dict | None, *, now: datetime | None = None) -> str:
    """Why this invitation cannot be used, or ``"usable"``.

    Returns a REASON rather than a boolean so the caller can say which of the
    three it is. They are genuinely different situations to the person holding
    the link, and collapsing them into "invalid" is how a revoked invitation and
    an expired one become indistinguishable to support.
    """
    if not invite:
        return "no_invitation"
    if invite.get("revoked_at"):
        return "revoked"
    expiry = invite.get("expires_at")
    if isinstance(expiry, datetime):
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= (now or datetime.now(timezone.utc)):
            return "expired"
    return "usable"
