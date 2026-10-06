"""Who a client may send a document to. Decision D1 (2026-10-03).

Creating, drafting, storing and analysing a document needs no case and no
engagement. SHARING it with a lawyer does: every client-to-lawyer document
submission needs an ACCEPTED engagement between that client and that lawyer.

  * A document on a case goes only through an accepted engagement on that
    same case.
  * A document with no case may go to the lawyer of any of the client's
    accepted engagements -- choosing that engagement is the act of sharing.
  * `requested` / `terms_proposed` (still negotiating), `completed` /
    `terminated` (ended) and `declined` / `cancelled` (never began) authorise
    nothing new.

Before this, both submit paths (legacy `document_service.submit_for_review`
and DOCUMENTS_V2 `document_transitions.submit`) let a client send a document
with no case to ANY lawyer flagged KYC-verified, with no relationship at all.
Both now call `require_accepted_engagement`, so the rule lives in one place
and cannot drift between them.
"""
from __future__ import annotations

from app.core.exceptions import ForbiddenError
from app.repositories.engagement_repo import EngagementRepository

NOT_ENGAGED = ("You can send a document only to a lawyer you have an accepted engagement with. "
               "Hire the lawyer first, or choose one you have already engaged.")
NOT_ENGAGED_ON_CASE = ("You can send a case's document only to the lawyer of an accepted engagement "
                       "on that case.")


async def require_accepted_engagement(*, client_id: str, lawyer_id: str,
                                      case_id: str | None) -> dict:
    """The accepted engagement that authorises this submission, or 403."""
    engagement = await EngagementRepository().find_accepted_between(
        client_id, lawyer_id, case_id or None)
    if engagement is None:
        raise ForbiddenError(NOT_ENGAGED_ON_CASE if case_id else NOT_ENGAGED)
    return engagement
