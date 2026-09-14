"""Immutable OCR revisions.

WHY IMMUTABLE

An OCR result is a claim about what a document says, made by a specific engine
version under a specific configuration at a specific time. If a later run could
overwrite it, there would be no way to answer "what did we show the client, and
what produced it" -- which is the only question that matters when a fine or a
date turns out to have been misread. So rows are inserted and never updated.
Superseding happens by inserting a NEW revision and marking the old one
superseded by source hash, not by editing anything.

IDEMPOTENCY IS BY CONTENT, NOT BY REQUEST

The key is (owner, file, page, SOURCE HASH, engine identity, config version).
Two consequences fall out of that, both wanted:

  * Retrying the same page with the same engine returns the existing row rather
    than paying for a second read and storing a second answer.
  * REPLACING the source file changes its hash, so the old revision no longer
    matches and cannot be mistaken for a reading of the new bytes. That is the
    invalidation rule: it is structural, not a cleanup job that might not run.

OWNER SCOPING IS IN THE QUERY, NOT THE CALLER

Every read and write takes `owner_id` and puts it in the filter. A repository
that trusts its callers to remember is one forgotten parameter away from
handing one client another client's documents.

WHAT IS NEVER STORED IN A LOG

Nothing here logs text, filenames or paths. The TEXT is stored in the row --
that is the point of the row -- but it never reaches a log line.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from app.db.collections import get_ocr_revisions_col
from app.repositories.base import BaseRepository

#: Rows carry their shape so a reader can tell an old row from a new one
#: without guessing from which fields happen to be present.
OCR_REVISION_SCHEMA = "ocr_revision/1"

#: The review state every row is born in, and the only one this milestone can
#: write. It is SEPARATE from the OCR outcome status: `ocr_completed_unconfirmed`
#: says the engine finished, `pending_confirmation` says no human has agreed the
#: characters are what the document says. A later milestone adds the confirmed
#: state; nothing here may set it.
PENDING_CONFIRMATION = "pending_confirmation"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def idempotency_key(*, owner_id: str, file_id: str, page_number: int,
                    source_sha256: str, engine_identity: str,
                    config_version: str, language: str) -> str:
    """The identity of a READING, not of a request.

    Every component changes the answer: different bytes, a different engine
    build, a different configuration or a different language all produce
    genuinely different output and must not collide.
    """
    return "|".join([
        str(owner_id), str(file_id), str(int(page_number)),
        str(source_sha256), str(engine_identity), str(config_version),
        str(language),
    ])


class OcrRevisionRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_ocr_revisions_col)

    async def create_if_absent(
        self,
        *,
        owner_id: str,
        session_id: str,
        file_id: str,
        page_number: int,
        source_sha256: str,
        text: str,
        text_sha256: str,
        engine: str,
        engine_version: str,
        language: str,
        config_version: str,
        status: str,
        error_code: str | None = None,
        duration_ms: int = 0,
        limitations: list[str] | None = None,
    ) -> tuple[dict, bool]:
        """Insert one revision, or return the one already there.

        Returns `(row, created)`. `created is False` means an identical reading
        already existed -- the retry case -- and no second row was written.

        The uniqueness is enforced by an INDEX, not by a read-then-write: two
        concurrent retries of the same page would both see "absent" and both
        insert. The duplicate-key error is the real serialisation point, so it
        is caught and turned into the existing row.
        """
        key = idempotency_key(
            owner_id=owner_id, file_id=file_id, page_number=page_number,
            source_sha256=source_sha256,
            engine_identity=f"{engine}/{engine_version}",
            config_version=config_version, language=language,
        )
        now = _now()
        row = {
            "_id": secrets.token_urlsafe(16),
            "schema": OCR_REVISION_SCHEMA,
            "idempotency_key": key,
            "owner_id": str(owner_id),
            "session_id": str(session_id),
            "file_id": str(file_id),
            "page_number": int(page_number),
            "source_sha256": str(source_sha256),
            "text": text,
            "text_sha256": str(text_sha256),
            "engine": str(engine),
            "engine_version": str(engine_version),
            "engine_identity": f"{engine}/{engine_version}",
            "language": str(language),
            "config_version": str(config_version),
            "status": str(status),
            # Born pending. There is no code path in 3A that writes anything
            # else, which is what keeps unconfirmed text out of analysis.
            "review_state": PENDING_CONFIRMATION,
            "error_code": error_code,
            "duration_ms": int(duration_ms),
            "limitations": list(limitations or []),
            # Confirmation is a SEPARATE, later, server-side act. Nothing in
            # this milestone may set these.
            "confirmed": False,
            "confirmed_at": None,
            "confirmed_by": None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            await self.insert(row)
            return row, True
        except DuplicateKeyError:
            existing = await self.find_one(
                {"owner_id": str(owner_id), "idempotency_key": key})
            # A duplicate that cannot then be read back means the row belongs
            # to a different owner. Returning the new row unwritten would be a
            # lie; raising is the honest outcome.
            if existing is None:
                raise
            return existing, False

    async def find_for_file(self, *, owner_id: str, file_id: str,
                            source_sha256: str | None = None) -> list[dict]:
        """Revisions for one file, newest first. Owner-scoped.

        Passing `source_sha256` returns only readings OF THOSE BYTES, which is
        how a caller avoids showing a reading of a file that has since been
        replaced.
        """
        query = {"owner_id": str(owner_id), "file_id": str(file_id)}
        if source_sha256:
            query["source_sha256"] = str(source_sha256)
        return await self.find_many(query, sort=[("created_at", DESCENDING)])

    async def find_page(self, *, owner_id: str, file_id: str, page_number: int,
                        source_sha256: str) -> dict | None:
        return await self.find_one({
            "owner_id": str(owner_id), "file_id": str(file_id),
            "page_number": int(page_number),
            "source_sha256": str(source_sha256),
        })

    async def stale_for_file(self, *, owner_id: str, file_id: str,
                             current_sha256: str) -> list[dict]:
        """Revisions that read bytes this file no longer has.

        Not deleted. They are the record of what was read and shown at the
        time; they are simply no longer ABOUT this file's current content.
        """
        return await self.find_many({
            "owner_id": str(owner_id), "file_id": str(file_id),
            "source_sha256": {"$ne": str(current_sha256)},
        }, sort=[("created_at", DESCENDING)])


_repo: OcrRevisionRepository | None = None


def ocr_revision_repo() -> OcrRevisionRepository:
    global _repo
    if _repo is None:
        _repo = OcrRevisionRepository()
    return _repo


#: Index definitions, applied by `app.db.indexes`.
def index_models():
    from pymongo import IndexModel
    return [
        # THE IDEMPOTENCY GUARANTEE. Unique, so a concurrent retry fails at the
        # database rather than storing a second reading of the same bytes.
        IndexModel([("owner_id", ASCENDING), ("idempotency_key", ASCENDING)],
                   unique=True, name="uniq_ocr_revision_identity"),
        IndexModel([("owner_id", ASCENDING), ("file_id", ASCENDING),
                    ("created_at", DESCENDING)], name="ocr_by_owner_file"),
        IndexModel([("owner_id", ASCENDING), ("session_id", ASCENDING)],
                   name="ocr_by_owner_session"),
        IndexModel([("source_sha256", ASCENDING)], name="ocr_by_source"),
        IndexModel([("status", ASCENDING)], name="ocr_by_status"),
    ]
