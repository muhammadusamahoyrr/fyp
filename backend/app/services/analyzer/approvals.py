"""Recording a lawyer's approval of one exact legal playbook text.

An approval binds THREE things: the pack id, the SHA-256 of the pack's text
as it is in the repository right now, and an authenticated reviewer -- a
user with the lawyer role whose KYC was approved. The engine runs a legal
pack only if its current hash has such a record, so editing the pack (one
character, a comment included) withdraws the approval automatically.

What this deliberately does NOT do: decide that the reviewer is qualified in
the area the pack covers (Punjab tenancy, NDAs, employment). That is a
human judgement made before this is called; `reviewer_role` records the
capacity in which they approved, for the audit trail.

P2A ships the service. An authenticated endpoint for reviewers is P2B.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.core.constants import KycStatus
from app.db.collections import get_analysis_playbook_approvals_col, get_users_col
from app.services.analyzer.errors import AnalyzerConflict, AnalyzerNotFound, UploadRejected
from app.services.analyzer.playbook_engine import load_packs

APPROVED_KYC = KycStatus.APPROVED.value


async def record_approval(*, pack_id: str, content_hash: str, reviewer_user_id: str,
                          reviewer_role: str) -> dict:
    pack = next((p for p in load_packs() if p.id == pack_id), None)
    if pack is None:
        raise AnalyzerNotFound("No such playbook.")
    if not pack.requires_approval:
        raise UploadRejected("approval_not_applicable", "This playbook makes no legal claim; it is not approved.")
    if pack.content_hash != content_hash:
        # The reviewer read a different text from the one that would run.
        raise AnalyzerConflict("hash_mismatch", "The playbook has changed since it was reviewed.")
    if not reviewer_role or not reviewer_role.strip():
        raise UploadRejected("reviewer_role_required", "State the capacity in which this is approved.")
    reviewer = await get_users_col().find_one({"_id": reviewer_user_id})
    if (reviewer is None or reviewer.get("role") != "lawyer"
            or (reviewer.get("lawyer_profile") or {}).get("kyc_status") != APPROVED_KYC):
        raise UploadRejected("reviewer_not_verified", "Only a verified lawyer can approve a legal playbook.")
    record = {"pack_id": pack.id, "version": pack.version, "content_hash": pack.content_hash,
              "reviewer_user_id": reviewer_user_id, "reviewer_role": reviewer_role.strip(),
              "approved_at": datetime.now(timezone.utc)}
    try:
        await get_analysis_playbook_approvals_col().insert_one(record)
    except DuplicateKeyError:
        raise AnalyzerConflict("already_approved", "This exact playbook text is already approved.") from None
    return record
