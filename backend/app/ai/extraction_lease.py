"""What an extraction result is allowed to claim, and for how long.

An extraction result is not a fact about a file_id. It is a fact about *these
bytes*, read by *this extractor*, on behalf of *this owner*. Store it against
the file_id alone and three things go wrong the moment anything moves:

  * the client replaces the file and the old text keeps describing the new one;
  * the extractor is fixed and yesterday's partial result still looks current;
  * a slow extraction finishes after the file it read has been deleted, and
    publishes text for a document that no longer exists.

So a claim carries the owner, the content hash and both versions, and anything
that compares a stored result against the world compares all of them.

THE LEASE

Double-clicking Convert, refreshing mid-conversion, or a client retrying a
dropped request all arrive as concurrent work on the same evidence — none of
which requires a retry feature to exist, which is why this is here in Milestone 1
rather than deferred with the queue. A lease makes the second arrival wait for
or skip the first rather than starting a second extraction of the same bytes.

Leases EXPIRE. A holder that dies mid-extraction must not lock its evidence
until the process restarts, so the lease is a deadline and not a lock: once it
passes, another caller may take it. The cost of that choice is the stale
completion — the original holder waking up afterwards and trying to publish —
which `is_stale` exists to refuse.

SCOPE, STATED PLAINLY: this registry is per-process, in memory. It bounds
duplicate work within one API worker, which is where double-clicks land. Across
workers it does nothing, and making it global needs the shared store already in
this stack (Redis). That is deliberately not built here.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

from app.ai.extraction import CONFIG_VERSION, EXTRACTOR_VERSION

#: Comfortably longer than the runner's batch ceiling, so a lease cannot expire
#: under an extraction that is still legitimately running.
DEFAULT_LEASE_SECONDS = 180.0

_HASH_CHUNK = 1024 * 1024


def content_hash(path: str | Path) -> str | None:
    """SHA-256 of the file's bytes, or None if it cannot be read.

    Read in blocks: evidence is capped at 10 MB today, but a hash helper that
    slurps is a memory bug waiting for the cap to be raised.
    """
    try:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            while chunk := handle.read(_HASH_CHUNK):
                digest.update(chunk)
        return digest.hexdigest()
    except (OSError, ValueError):
        return None


@dataclass(frozen=True)
class ExtractionClaim:
    """The identity an extraction result is scoped to."""

    owner_id: str
    file_id: str
    content_sha256: str
    extractor_version: str = EXTRACTOR_VERSION
    config_version: str = CONFIG_VERSION

    @property
    def key(self) -> tuple[str, str, str]:
        # Owner is part of the key. Two clients cannot hold evidence with the
        # same file_id today, but a key that would silently merge them if they
        # ever could is not a key worth having.
        return (self.owner_id, self.file_id, self.content_sha256)

    def as_dict(self) -> dict:
        return {
            "owner_id": self.owner_id,
            "file_id": self.file_id,
            "content_sha256": self.content_sha256,
            "extractor_version": self.extractor_version,
            "config_version": self.config_version,
        }


def claim_for(owner_id: str, file_id: str, path: str | Path) -> ExtractionClaim | None:
    """Build a claim by hashing the file as it is right now."""
    digest = content_hash(path)
    if digest is None:
        return None
    return ExtractionClaim(owner_id=owner_id, file_id=file_id,
                           content_sha256=digest)


def is_stale(claim: ExtractionClaim, *, current_sha: str | None,
             now: float | None = None, lease_expires_at: float | None = None) -> bool:
    """Must this result be refused rather than published?

    Three independent reasons, and any one of them is enough:

      * the bytes changed or vanished — the result describes a file that is no
        longer there;
      * the extractor or its configuration moved on — the result was produced by
        code that no longer exists, so it cannot be compared with current output;
      * the lease expired — someone else may already have re-extracted and
        published, and a late arrival would overwrite a newer answer with an
        older one.
    """
    if current_sha is None or current_sha != claim.content_sha256:
        return True
    if claim.extractor_version != EXTRACTOR_VERSION:
        return True
    if claim.config_version != CONFIG_VERSION:
        return True
    if lease_expires_at is not None:
        return (now if now is not None else time.monotonic()) >= lease_expires_at
    return False


@dataclass
class _Lease:
    claim: ExtractionClaim
    expires_at: float


class LeaseRegistry:
    """In-process leases keyed by (owner, file, content hash)."""

    def __init__(self, lease_seconds: float = DEFAULT_LEASE_SECONDS):
        self._lease_seconds = lease_seconds
        self._live: dict[tuple[str, str, str], _Lease] = {}
        self._guard = asyncio.Lock()

    async def acquire(self, claim: ExtractionClaim,
                      now: float | None = None) -> float | None:
        """Take the lease, or None if a live one is already held.

        Returns the expiry so the caller can pass it back to `is_stale` when its
        work finishes. Expired leases are taken over rather than cleaned up on a
        timer: the check has to happen on this path anyway, and a sweeper would
        be a second place for the same rule to live.
        """
        moment = time.monotonic() if now is None else now
        async with self._guard:
            existing = self._live.get(claim.key)
            if existing is not None and existing.expires_at > moment:
                return None
            expires = moment + self._lease_seconds
            self._live[claim.key] = _Lease(claim=claim, expires_at=expires)
            return expires

    async def release(self, claim: ExtractionClaim, expires_at: float) -> bool:
        """Give the lease back — only if it is still the one we took.

        The expiry is the fencing token. Without it a holder whose lease lapsed,
        and was then taken by someone else, would release a lease it no longer
        owns and hand the evidence to a third caller while the second is still
        working on it.
        """
        async with self._guard:
            existing = self._live.get(claim.key)
            if existing is None or existing.expires_at != expires_at:
                return False
            del self._live[claim.key]
            return True

    async def held(self, claim: ExtractionClaim, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        async with self._guard:
            existing = self._live.get(claim.key)
            return existing is not None and existing.expires_at > moment


#: Shared per-process registry.
registry = LeaseRegistry()
