"""Who may approve which legal playbook, and the record of every approval.

QUALIFICATION, NOT JUST VERIFICATION. A legal pack names the qualification
it needs (`required_qualification`, e.g. `pk.punjab.tenancy`). An approval is
accepted only from a user who is
  * a lawyer whose KYC was approved, AND
  * holds an ACTIVE grant of exactly that qualification
    (analysis_reviewer_qualifications), granted by an admin with a stated
    basis (enrolment, practice area, ...).

WHAT IS APPROVED IS ONE EXACT TEXT. The approval binds the pack id to the
SHA-256 of the pack's text as it is in the repository NOW, and to the hash
of the official provisions it cites (authorities.py). An edit to either
changes a hash and the pack stops running until it is approved again; the
re-approval supersedes the stale one, audited, in the same transaction.

EVERY CHANGE IS AUDITED. Granting or revoking a qualification, approving a
pack and revoking an approval each write an append-only audit row in the
SAME transaction as the change. Revoking a qualification also deactivates
the approvals its holder made under it: a pack must not keep running on the
word of someone no longer authorised to give it.

Deciding that a person IS qualified (checking an enrolment, a practice
history) is a human judgement made before `grant_qualification` is called;
the `basis` records what it rested on.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.constants import KycStatus
from app.db.collections import (
    get_analysis_approval_audit_col,
    get_analysis_playbook_approvals_col,
    get_analysis_reviewer_qualifications_col,
    get_users_col,
)
from app.services.analyzer.errors import AnalyzerConflict, AnalyzerNotFound, UploadRejected
from app.services.analyzer.playbook_engine import QUALIFICATION, load_packs
from app.services.analyzer.txn import run_in_transaction

APPROVED_KYC = KycStatus.APPROVED.value


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _audit(session, *, actor: dict, action: str, **details) -> None:
    await get_analysis_approval_audit_col().insert_one({
        "_id": uuid.uuid4().hex, "at": _now(), "actor_user_id": str(actor["_id"]),
        "actor_role": actor.get("role"), "action": action, **details}, session=session)


def _clean_text(value, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise UploadRejected(f"invalid_{name}", f"{name.replace('_', ' ').capitalize()} is required "
                                                f"(at most {limit} characters).")
    return value.strip()


# ── qualifications (admin) ───────────────────────────────────────────────────

async def grant_qualification(*, admin: dict, user_id: str, qualification: str, basis: str) -> dict:
    if not isinstance(qualification, str) or not QUALIFICATION.match(qualification):
        raise UploadRejected("invalid_qualification", "Use a code like pk.punjab.tenancy.")
    basis = _clean_text(basis, "basis", 500)
    user = await get_users_col().find_one({"_id": user_id})
    if (user is None or user.get("role") != "lawyer"
            or (user.get("lawyer_profile") or {}).get("kyc_status") != APPROVED_KYC):
        raise UploadRejected("reviewer_not_verified", "Only a verified lawyer can be given a reviewer qualification.")
    grant = {"_id": uuid.uuid4().hex, "user_id": user_id, "qualification": qualification,
             "basis": basis, "granted_by": str(admin["_id"]), "granted_at": _now(), "active": True}

    async def op(session):
        await get_analysis_reviewer_qualifications_col().insert_one(grant, session=session)
        await _audit(session, actor=admin, action="grant_qualification", target_user_id=user_id,
                     qualification=qualification, grant_id=grant["_id"], basis=basis)

    try:
        await run_in_transaction(op)
    except DuplicateKeyError:
        raise AnalyzerConflict("already_qualified", "This reviewer already holds that qualification.") from None
    return grant


async def revoke_qualification(*, admin: dict, grant_id: str, reason: str) -> dict:
    reason = _clean_text(reason, "reason", 500)
    now = _now()
    outcome = {}

    async def op(session):
        grant = await get_analysis_reviewer_qualifications_col().find_one_and_update(
            {"_id": grant_id, "active": True},
            {"$set": {"active": False, "revoked_by": str(admin["_id"]), "revoked_at": now,
                      "revoke_reason": reason}},
            session=session, return_document=ReturnDocument.AFTER)
        if grant is None:
            raise AnalyzerNotFound("No such active qualification.")
        # Approvals this person gave under this qualification stop counting.
        affected = [a["_id"] async for a in get_analysis_playbook_approvals_col().find(
            {"reviewer_user_id": grant["user_id"], "qualification": grant["qualification"],
             "active": True}, {"_id": 1}, session=session)]
        if affected:
            await get_analysis_playbook_approvals_col().update_many(
                {"_id": {"$in": affected}},
                {"$set": {"active": False, "revoked_at": now, "revoked_by": str(admin["_id"]),
                          "revoke_reason": f"qualification revoked: {reason}"}}, session=session)
        await _audit(session, actor=admin, action="revoke_qualification", grant_id=grant_id,
                     target_user_id=grant["user_id"], qualification=grant["qualification"],
                     reason=reason, approvals_deactivated=affected)
        outcome.update(grant_id=grant_id, approvals_deactivated=affected)

    await run_in_transaction(op)
    return outcome


# ── approvals (lawyer) ───────────────────────────────────────────────────────

def _legal_pack(pack_id: str):
    pack = next((p for p in load_packs() if p.id == pack_id), None)
    if pack is None:
        raise AnalyzerNotFound("No such playbook.")
    if not pack.requires_approval:
        raise UploadRejected("approval_not_applicable",
                             "This playbook makes no legal claim; it is not approved.")
    return pack


async def record_approval(*, reviewer: dict, pack_id: str, content_hash: str,
                          authorities_hash: str, reviewer_role: str) -> dict:
    """The CALLER approves, as themselves. Never on someone else's behalf."""
    pack = _legal_pack(pack_id)
    if pack.content_hash != content_hash or pack.authorities_hash != authorities_hash:
        # The reviewer read a different text from the one that would run.
        raise AnalyzerConflict("hash_mismatch", "The playbook, or the official text it cites, "
                                                "has changed since it was reviewed.")
    reviewer_role = _clean_text(reviewer_role, "reviewer_role", 200)
    user = await get_users_col().find_one({"_id": reviewer["_id"]})
    if (user is None or user.get("role") != "lawyer"
            or (user.get("lawyer_profile") or {}).get("kyc_status") != APPROVED_KYC):
        raise UploadRejected("reviewer_not_verified", "Only a verified lawyer can approve a legal playbook.")
    grant = await get_analysis_reviewer_qualifications_col().find_one(
        {"user_id": user["_id"], "qualification": pack.required_qualification, "active": True})
    if grant is None:
        raise UploadRejected("reviewer_not_qualified",
                             f"Approving this playbook needs the qualification {pack.required_qualification}.")
    record = {"_id": uuid.uuid4().hex, "pack_id": pack.id, "version": pack.version,
              "content_hash": pack.content_hash, "authorities_hash": pack.authorities_hash,
              "authority_library_hash": pack.authority_library_hash,
              "qualification": pack.required_qualification,
              "qualification_grant_id": grant["_id"], "reviewer_user_id": user["_id"],
              "reviewer_role": reviewer_role, "approved_at": _now(), "active": True}

    async def op(session):
        # The same pack text approved against OLDER official text: that
        # approval no longer counts (its authorities hash is stale), and is
        # superseded here rather than left to block this one.
        stale = [a["_id"] async for a in get_analysis_playbook_approvals_col().find(
            {"pack_id": pack.id, "content_hash": pack.content_hash, "active": True,
             "authorities_hash": {"$ne": pack.authorities_hash}}, {"_id": 1}, session=session)]
        if stale:
            await get_analysis_playbook_approvals_col().update_many(
                {"_id": {"$in": stale}, "active": True},
                {"$set": {"active": False, "revoked_at": record["approved_at"],
                          "revoked_by": user["_id"], "revoke_reason": "superseded: cited text changed"}},
                session=session)
        await get_analysis_playbook_approvals_col().insert_one(record, session=session)
        await _audit(session, actor=user, action="approve_playbook", pack_id=pack.id,
                     version=pack.version, content_hash=pack.content_hash,
                     authorities_hash=pack.authorities_hash, superseded=stale,
                     approval_id=record["_id"], qualification=pack.required_qualification)

    try:
        await run_in_transaction(op)
    except DuplicateKeyError:
        raise AnalyzerConflict("already_approved", "This exact playbook text is already approved.") from None
    return record


async def revoke_approval(*, actor: dict, approval_id: str, reason: str) -> dict:
    """An admin, or the lawyer who gave it, can withdraw an approval."""
    reason = _clean_text(reason, "reason", 500)
    now = _now()
    outcome = {}

    async def op(session):
        approval = await get_analysis_playbook_approvals_col().find_one(
            {"_id": approval_id, "active": True}, session=session)
        if approval is None:
            raise AnalyzerNotFound("No such active approval.")
        if actor.get("role") != "admin" and approval["reviewer_user_id"] != str(actor["_id"]):
            raise AnalyzerNotFound("No such active approval.")      # do not reveal others'
        await get_analysis_playbook_approvals_col().update_one(
            {"_id": approval_id, "active": True},
            {"$set": {"active": False, "revoked_at": now, "revoked_by": str(actor["_id"]),
                      "revoke_reason": reason}}, session=session)
        await _audit(session, actor=actor, action="revoke_approval", approval_id=approval_id,
                     pack_id=approval["pack_id"], content_hash=approval["content_hash"], reason=reason)
        outcome.update(approval_id=approval_id, pack_id=approval["pack_id"])

    await run_in_transaction(op)
    return outcome


# ── what reviewers read ──────────────────────────────────────────────────────

async def list_playbooks() -> list[dict]:
    packs = load_packs()
    active = {}
    async for a in get_analysis_playbook_approvals_col().find({"active": True}):
        active.setdefault((a["pack_id"], a["content_hash"], a.get("authorities_hash")), []).append(
            {"approval_id": a["_id"], "reviewer_user_id": a["reviewer_user_id"],
             "reviewer_role": a["reviewer_role"], "approved_at": a["approved_at"]})
    return [{"id": p.id, "version": p.version, "title": p.title, "scope": p.scope,
             "requires_approval": p.requires_approval,
             "required_qualification": p.required_qualification,
             "content_hash": p.content_hash, "authorities_hash": p.authorities_hash,
             "approvals": active.get((p.id, p.content_hash, p.authorities_hash), [])} for p in packs]


def playbook_text(pack_id: str) -> dict:
    """The exact text a reviewer reads -- the pack AND the official text of
    every provision it cites -- and the two hashes an approval must quote."""
    pack = next((p for p in load_packs() if p.id == pack_id), None)
    if pack is None:
        raise AnalyzerNotFound("No such playbook.")
    from app.services.analyzer import playbook_engine as engine

    for path in sorted(engine.PLAYBOOK_DIR.glob("*.yaml")):
        raw = path.read_text(encoding="utf-8")
        if engine.content_hash(raw) == pack.content_hash:
            return {"id": pack.id, "version": pack.version, "content_hash": pack.content_hash,
                    "authorities_hash": pack.authorities_hash,
                    "required_qualification": pack.required_qualification, "text": raw,
                    "cited_provisions": _cited_provisions(pack)}
    raise AnalyzerNotFound("No such playbook.")


def _cited_provisions(pack) -> list[dict]:
    from app.services.analyzer import authorities

    library, seen, out = authorities.load_library(), set(), []
    for check in pack.checks:
        for a in check.authority:
            provision = library.resolve(a["statute"], a["section"])
            key = (provision.statute, provision.section)
            if key in seen:
                continue
            seen.add(key)
            out.append({"statute": provision.statute, "section": provision.section,
                        "heading": provision.heading, "pages": list(provision.pages),
                        "text": provision.text, "text_sha256": provision.text_sha256,
                        "source": {k: provision.source[k] for k in (
                            "publisher", "url", "listing_url", "sha256", "retrieved")}})
    return out


async def audit_trail(*, limit: int = 100) -> list[dict]:
    return [a async for a in get_analysis_approval_audit_col().find({}, {"_id": 0})
            .sort("at", -1).limit(max(1, min(limit, 500)))]
