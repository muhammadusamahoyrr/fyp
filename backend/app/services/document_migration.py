"""DOCUMENTS_V2 migration — backfill legacy documents into the revision model.

Contract (remediation plan v5 §8, v5.1 §10):

  * DRY-RUN writes nothing. It emits a manifest: per legacy document, the
    preconditions apply() must re-check (metadata hash, file byte-SHA/size/mtime),
    the current review state, and a DETERMINISTIC planned revision id
    (uuid5(NAMESPACE, "<document_id>:1")) so apply is an idempotent upsert.

  * APPLY is idempotent and NEVER fabricates. If any precondition drifted since
    the dry-run, that document is SKIPPED and reported. A present file becomes a
    generated v1 revision (bytes hashed, copied into the store, text extracted
    and — where the corpus can — verified). A MISSING file becomes a `failed`
    revision with `verification.ran == false` and no body — never a placeholder
    and never a green check. Legacy approvals are labelled `legacy_unverified`
    (a hash computed today does not prove it is the artifact the lawyer reviewed
    then); an approved document whose file is gone becomes `needs_reapproval`.
    Legacy fields on the document row are LEFT INTACT, so legacy reads keep
    working and rollback stays possible.

  * ROLLBACK restores the legacy pointer/status from the rollback manifest with
    precondition checks and PRESERVES the revision rows and review events — they
    are audit records and are never dropped.

This module performs no flip. Turning DOCUMENTS_V2 on is a separate operational
step, gated additionally on the preview work (Stage 2).
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass

from pymongo.errors import DuplicateKeyError
from datetime import datetime, timezone
from pathlib import Path

from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store
from app.services import extraction_profile

logger = logging.getLogger(__name__)

# Fixed namespace so the planned revision id is stable across dry-run and apply
# and across re-runs — the property that makes apply an idempotent upsert.
_NAMESPACE = uuid.UUID("6f1b0c9e-2a3d-5e7f-8b1c-0d2e4f6a8c00")

# EVERY LEGACY FIELD `apply` READS to build its output. Audited, not assumed.
#
# This list grew from the fields the REVISION needs and stopped there, while
# `apply` went on reading five more to build the review cycle and the revision's
# compliance. Those five were in neither the manifest hash nor the CAS, so a
# change to any of them anywhere across the width of a record — read the
# document, extract text, verify citations, write the artifact, insert the row —
# was invisible.
#
# The result was not a corrupt row that something later rejects. It was a
# plausible, well-formed review cycle: a decision attributed to a lawyer, with a
# date, carrying a note written about a different state of the document. An
# audit record about a legal document, silently wrong, with nothing downstream
# able to tell.
#
# A field belongs here if its value REACHES THE OUTPUT. `compliance` is here
# because it is copied when present; it may also be recomputed from `fields`,
# which is itself guarded, so the recomputation is deterministic from guarded
# inputs.
_CONSUMED_LEGACY_FIELDS = frozenset({
    "client_id", "case_id", "template_type", "title", "fields", "created_at",
    "compliance",       # copied onto the revision when present
    "submitted_at",     # the review cycle's submitted_at
    "reviewed_at",      # the review cycle's decided_at
    "lawyer_note",      # the review cycle's note
    "review_note",      # the same, as a fallback when lawyer_note is absent
})

# Material fields whose change between dry-run and apply must abort that record.
# Sorted so the manifest hash is stable across builds.
_META_FIELDS = tuple(sorted(_CONSUMED_LEGACY_FIELDS))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def planned_revision_id(document_id: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{document_id}:1"))


def _meta_hash(doc: dict) -> str:
    material = {k: doc.get(k) for k in _META_FIELDS}
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _file_stat(path: str | None) -> dict:
    """Byte-SHA, size and mtime for a legacy file, or a 'not present' record."""
    if not path:
        return {"file_present": False, "byte_sha256": None, "size": None, "mtime": None}
    p = Path(path)
    if not p.exists():
        return {"file_present": False, "byte_sha256": None, "size": None, "mtime": None}
    data = p.read_bytes()
    stat = p.stat()
    return {"file_present": True,
            "byte_sha256": hashlib.sha256(data).hexdigest(),
            "size": stat.st_size,
            "mtime": stat.st_mtime}


def _is_legacy(doc: dict) -> bool:
    """A document not yet in the V2 revision model."""
    return doc.get("schema_version") != 2


# ── THE DECISION MATRIX ───────────────────────────────────────────────────────
#
# Five legacy statuses x file present/absent x reviewer known/unknown. Every
# combination gets a NAMED outcome, because a migration that answers a few cases
# and improvises the rest produces documents that exist, validate, and cannot be
# used — with nothing anywhere saying which ones they are.
#
# WHAT THE LEGACY DATA CAN AND CANNOT PROVE
#
# A legacy row carries `review_status` and sometimes `submitted_to`. It does NOT
# record which bytes were reviewed: there was one file per document and it was
# overwritten in place. So a migration can bind a decision to the artifact that
# exists TODAY, and it cannot prove that is the artifact anybody looked at.
#
# Recording that as a verified binding would put a false provenance claim into an
# audit trail — the one place a false claim is worst. So every migrated decision
# is marked `legacy_unverified`, and the outcomes below never invent a reviewer,
# never invent an approval, and never carry an approval forward over bytes that
# no longer exist.

STATUS_NEEDS_REAPPROVAL = "needs_reapproval"
STATUS_UNRECOVERABLE = "migration_unrecoverable"

# WHAT EACH RECOVERY STATE MEANS, AND HOW THE OWNER GETS OUT OF IT.
#
# Declared here, beside the matrix that produces them, and consumed by the API
# and both client surfaces — so the wording a client reads is the wording the
# migration decided, not something a component author guessed at later. A test
# asserts this covers every `new_review_status` the matrix can produce, because
# a state with no description is a state no surface can render.
#
# The explanations say what happened and whose fault it is not. A client did
# nothing wrong here and cannot be expected to know what "unrecoverable" means;
# left to infer, they will assume they lost their work.
RECOVERY_STATES = {
    STATUS_NEEDS_REAPPROVAL: {
        "state": STATUS_NEEDS_REAPPROVAL,
        "headline": "Needs approval again",
        "explanation": (
            "This document was approved before, but we could not carry that "
            "approval forward: either the approved file is no longer available "
            "or no record survives of who approved it. Nothing you wrote has "
            "been lost. Generate the document again and send it for review, "
            "and a lawyer will approve it."),
        "next_action": "regenerate_and_resubmit",
        "blocks_use": True,
    },
    STATUS_UNRECOVERABLE: {
        "state": STATUS_UNRECOVERABLE,
        "headline": "Needs to be sent again",
        "explanation": (
            "This document was waiting for a lawyer, but the version that was "
            "sent could not be recovered — either the file is no longer "
            "available or no lawyer was recorded as receiving it. It is not in "
            "anyone's queue, so nobody is working on it. Generate the document "
            "again and send it for review."),
        "next_action": "regenerate_and_resubmit",
        "blocks_use": True,
    },
}


def recovery_for(review_status) -> dict | None:
    """The recovery description for a status, or None for a healthy document."""
    return RECOVERY_STATES.get(review_status)

BINDING_LEGACY_UNVERIFIED = "legacy_unverified"

OUTCOME_DRAFT_WITH_FILE = "draft_with_file"
OUTCOME_DRAFT_NO_FILE = "draft_no_file"
OUTCOME_SUBMITTED_REVIEWABLE = "submitted_reviewable"
OUTCOME_SUBMITTED_NO_REVIEWER = "submitted_no_reviewer"
OUTCOME_SUBMITTED_NO_FILE = "submitted_no_file"
OUTCOME_DECIDED_BOUND_UNVERIFIED = "decided_bound_unverified"
OUTCOME_DECIDED_NO_REVIEWER = "approved_no_reviewer"
OUTCOME_DECIDED_NO_FILE = "approved_no_file"
OUTCOME_NEGATIVE_DECIDED_NO_REVIEWER = "negative_decision_no_reviewer"
OUTCOME_NEGATIVE_DECIDED_NO_FILE = "negative_decision_no_file"

_DRAFT_STATUSES = frozenset({None, "", "none", "draft", "pending"})
_DECIDED_ACTION = {"approved": "approve", "returned": "return",
                   "rejected": "reject"}

# THE ALLOWLIST. Every legacy status this migration knows how to reason about.
#
# An unrecognised value used to be migrated as a draft. That is a guess about a
# legal document's review state, made silently, at scale — and the guess is
# wrong in the worst direction for anything that was further along than a draft.
# A case-variant like "APPROVED" is the clearest example: it would demote an
# approved document to a draft and nothing would report it.
SUPPORTED_LEGACY_STATUSES = frozenset(_DRAFT_STATUSES | {"submitted"}
                                      | set(_DECIDED_ACTION))


class UnsupportedLegacyStatus(ValueError):
    """A `review_status` outside the allowlist reached the classifier.

    Loud rather than accommodating. Planning blocks these into the manifest
    before `classify` is ever called, so reaching here means a document changed
    under a running migration — and inventing an outcome for it is exactly the
    behaviour being removed.
    """


def is_supported_status(status) -> bool:
    return status in SUPPORTED_LEGACY_STATUSES


@dataclass(frozen=True)
class Outcome:
    """What the migration will do to one document, and why.

    `requires_owner_approval` marks the outcomes that CHANGE A USER-VISIBLE
    STATE rather than merely representing it differently. Relabelling an
    approval is a policy decision about someone's legal document; it is not the
    migration's to make quietly, so a dry run counts these and an apply refuses
    to run without an approved decision set.
    """

    code: str
    why: str
    make_revision: bool          # render a revision row from the legacy file
    point_current: bool          # document.current_revision_id -> that revision
    reviewable: bool             # populate submitted_* so a lawyer can act
    cycle_action: str | None     # append a review_cycle with this action
    new_review_status: str | None = None    # None = leave the legacy status
    requires_owner_approval: bool = False


ALL_OUTCOMES = (
    OUTCOME_DRAFT_WITH_FILE, OUTCOME_DRAFT_NO_FILE,
    OUTCOME_SUBMITTED_REVIEWABLE, OUTCOME_SUBMITTED_NO_REVIEWER,
    OUTCOME_SUBMITTED_NO_FILE, OUTCOME_DECIDED_BOUND_UNVERIFIED,
    OUTCOME_DECIDED_NO_REVIEWER, OUTCOME_DECIDED_NO_FILE,
    OUTCOME_NEGATIVE_DECIDED_NO_REVIEWER, OUTCOME_NEGATIVE_DECIDED_NO_FILE,
)


def classify(doc: dict, file_present: bool | None = None) -> Outcome:
    """The declared outcome for one legacy document. Total over the matrix.

    `file_present` may be passed in when the caller has already stat-ed the
    file — the apply path reads each source exactly once and must not re-stat.
    """
    if file_present is None:
        file_present = _file_stat(doc.get("file_path"))["file_present"]

    status = doc.get("review_status")
    reviewer = doc.get("submitted_to")

    # ── not under review ─────────────────────────────────────────────────────
    if status in _DRAFT_STATUSES:
        if file_present:
            return Outcome(
                OUTCOME_DRAFT_WITH_FILE,
                "A draft with its file. Becomes revision 1 and the document's "
                "current revision. Nobody is waiting on it, so nothing else "
                "changes.",
                make_revision=True, point_current=True, reviewable=False,
                cycle_action=None)
        return Outcome(
            OUTCOME_DRAFT_NO_FILE,
            "A draft whose file is gone. Recorded as a failed revision so the "
            "gap is visible in the history rather than looking like a document "
            "that was never generated. The client can regenerate it.",
            make_revision=True, point_current=False, reviewable=False,
            cycle_action=None)

    # ── waiting on a lawyer ──────────────────────────────────────────────────
    if status == "submitted":
        if not file_present:
            return Outcome(
                OUTCOME_SUBMITTED_NO_FILE,
                "Submitted, but the bytes are gone. A lawyer cannot review "
                "what cannot be shown, and a Pending row that can never be "
                "opened is worse than an explicit refusal — it is work that "
                "can never be cleared. The submission is dropped and the "
                "document is marked unrecoverable for the client to redo.",
                make_revision=True, point_current=False, reviewable=False,
                cycle_action=None, new_review_status=STATUS_UNRECOVERABLE,
                requires_owner_approval=True)
        if not reviewer:
            return Outcome(
                OUTCOME_SUBMITTED_NO_REVIEWER,
                "Submitted to nobody. It cannot appear in any queue, so it "
                "would sit forever. Choosing a lawyer for it would assign real "
                "work to someone the client did not pick.",
                make_revision=True, point_current=True, reviewable=False,
                cycle_action=None, new_review_status=STATUS_UNRECOVERABLE,
                requires_owner_approval=True)
        return Outcome(
            OUTCOME_SUBMITTED_REVIEWABLE,
            "Submitted, with its file and its reviewer. Becomes revision 1, "
            "and the submission pointers are set to it so the assigned lawyer "
            "can preview, download and decide exactly those bytes.",
            make_revision=True, point_current=True, reviewable=True,
            cycle_action=None)

    # ── already decided ──────────────────────────────────────────────────────
    action = _DECIDED_ACTION.get(status)
    if action is None:
        raise UnsupportedLegacyStatus(
            f"unsupported legacy review_status {status!r}; planning must block "
            "this document rather than assign it an outcome")

    positive = status == "approved"

    if not file_present:
        if positive:
            return Outcome(
                OUTCOME_DECIDED_NO_FILE,
                "Approved, but the approved bytes are gone. Carrying the "
                "approval forward would state that a document nobody can "
                "produce was signed off — the strongest claim the system "
                "makes, resting on nothing. It is returned for re-approval.",
                make_revision=True, point_current=False, reviewable=False,
                cycle_action=None, new_review_status=STATUS_NEEDS_REAPPROVAL,
                requires_owner_approval=True)
        return Outcome(
            OUTCOME_NEGATIVE_DECIDED_NO_FILE,
            "Returned or rejected, with the file gone. The status is KEPT: a "
            "negative decision blocks nobody and needs nothing re-earned, and "
            "reopening it would put dead work back in a queue. No review cycle "
            "is written, because there is no artifact to bind one to.",
            make_revision=True, point_current=False, reviewable=False,
            cycle_action=None)

    if not reviewer:
        if positive:
            return Outcome(
                OUTCOME_DECIDED_NO_REVIEWER,
                "Approved by nobody recorded. `submitted_to` is the only "
                "evidence of who reviewed it, and naming someone would put a "
                "real person against a decision they may never have made. The "
                "approval is not attributable, so it is returned for "
                "re-approval.",
                make_revision=True, point_current=True, reviewable=False,
                cycle_action=None, new_review_status=STATUS_NEEDS_REAPPROVAL,
                requires_owner_approval=True)
        return Outcome(
            OUTCOME_NEGATIVE_DECIDED_NO_REVIEWER,
            "Returned or rejected by nobody recorded. The status is kept — it "
            "blocks nobody — but no review cycle is written, so it appears in "
            "no lawyer's history rather than in the wrong one.",
            make_revision=True, point_current=True, reviewable=False,
            cycle_action=None)

    return Outcome(
        OUTCOME_DECIDED_BOUND_UNVERIFIED,
        "Decided, with a file and a reviewer. A review cycle is written so the "
        "deciding lawyer keeps their history and their revision-scoped access. "
        "The binding is marked legacy_unverified: the artifact that exists "
        "today is the only candidate, and nothing in the legacy data proves it "
        "is the one that was reviewed.",
        make_revision=True, point_current=True, reviewable=False,
        cycle_action=action)


# Every state a document may legitimately be in AFTER migration: the legacy
# statuses that survive unchanged, plus the two recovery states the matrix can
# move a document into. Anything else is a dead end — no surface renders it and
# no transition accepts it, so a document holding one is invisible work.
POST_MIGRATION_STATUSES = frozenset(
    SUPPORTED_LEGACY_STATUSES | {STATUS_NEEDS_REAPPROVAL, STATUS_UNRECOVERABLE})


def _outcomes_by_code() -> dict:
    """Every declared Outcome, keyed by code, for checking a document against
    the migration's own account of what it did to it."""
    seen: dict = {}
    for status in ("none", "draft", "submitted", "approved", "returned",
                   "rejected"):
        for file_present in (True, False):
            for reviewer in ("someone", None):
                o = classify({"review_status": status,
                              "submitted_to": reviewer},
                             file_present=file_present)
                seen.setdefault(o.code, o)
    return seen


def outcome_catalogue() -> dict:
    """Every declared outcome, for a report an owner reads before approving."""
    seen: dict[str, Outcome] = {}
    for status in ("none", "draft", "submitted", "approved", "returned",
                   "rejected"):
        for file_present in (True, False):
            for reviewer in ("someone", None):
                outcome = classify(
                    {"review_status": status, "submitted_to": reviewer},
                    file_present=file_present)
                seen.setdefault(outcome.code, outcome)
    return {code: {"why": o.why,
                   "requires_owner_approval": o.requires_owner_approval,
                   "new_review_status": o.new_review_status,
                   "writes_review_cycle": o.cycle_action is not None,
                   "reviewable_after": o.reviewable}
            for code, o in sorted(seen.items())}


_OUTCOME_BY_CODE = _outcomes_by_code()


# ── DRY-RUN ───────────────────────────────────────────────────────────────────
#
# WHY EVERY BLOCKED RECORD CARRIES A CODE
#
# A migration is approved or refused by a person reading this manifest, and
# "37 documents could not be migrated" is not a fact anyone can act on. A code
# per record is: it says which documents, why, and whether the answer is to fix
# data, fix code, or accept the outcome. Prose in a log line cannot be counted,
# grouped or diffed between two runs.
#
# The codes are derived from what `apply` ACTUALLY does — every one of them
# corresponds to a branch below in this file — rather than from what a migration
# might plausibly reject. A code with no matching branch would be a warning
# nobody could resolve.

# Refusals: apply would skip the record, or would write something wrong.
BLOCK_ALREADY_MIGRATED   = "already_migrated"      # schema_version == 2
BLOCK_NO_TEMPLATE_TYPE   = "missing_template_type"  # profile + compliance need it
BLOCK_NO_CLIENT          = "missing_client_id"      # a document with no owner
BLOCK_ID_COLLISION       = "planned_revision_id_collision"
BLOCK_DUPLICATE_PLAN     = "duplicate_planned_revision_id"
# The source exists as far as anyone knows; this process could not READ it.
# Blocked rather than treated as missing, because "missing" withdraws approvals.
BLOCK_UNREADABLE_FILE    = "source_file_unreadable"
# A review_status outside SUPPORTED_LEGACY_STATUSES. Held for a human instead of
# being guessed into a draft.
BLOCK_UNSUPPORTED_STATUS = "unsupported_legacy_review_status"

# Not refusals: apply proceeds, with an outcome the approver must see BEFORE
# agreeing to it, because it is not reversible by re-running.
FLAG_FILE_MISSING        = "file_missing_becomes_failed_revision"
FLAG_APPROVED_UNVERIFIED = "approval_relabelled_legacy_unverified"
FLAG_NEEDS_REAPPROVAL    = "approved_but_file_missing_needs_reapproval"
FLAG_ALREADY_PLANNED     = "revision_already_exists_apply_is_a_no_op"
FLAG_NO_CREATED_AT       = "missing_created_at"

BLOCKING_CODES = frozenset({
    BLOCK_ALREADY_MIGRATED, BLOCK_NO_TEMPLATE_TYPE, BLOCK_NO_CLIENT,
    BLOCK_ID_COLLISION, BLOCK_DUPLICATE_PLAN,
    BLOCK_UNREADABLE_FILE, BLOCK_UNSUPPORTED_STATUS,
})


MANIFEST_SCHEMA_VERSION = 2
MIGRATION_POLICY_VERSION = "2026-09-04.decision-matrix-v1"

# How many documents one traversal batch fetches. NOT a cap on the manifest:
# the traversal continues until the collection is exhausted, and a manifest
# says so explicitly. The previous `limit=10_000` silently produced a manifest
# that LOOKED complete on a larger collection, and an apply run from it would
# have migrated a prefix and left the rest behind with nothing recording that.
DRY_RUN_BATCH = 500


class ManifestRejected(RuntimeError):
    """A manifest that must not be applied, and why."""


async def dry_run(max_documents: int | None = None) -> dict:
    """Produce a migration manifest. WRITES NOTHING.

    READ-ONLY BY CONSTRUCTION, not by discipline. Every database call here is a
    `find`, and a test asserts the source of this path contains no mutating
    call. That matters more than usual: a dry run is what an operator uses to
    decide whether the real thing is safe, so one that wrote would corrupt the
    evidence used to approve it.

    COMPLETE BY DEFAULT. Traversal is cursor-based over `_id` and runs to
    exhaustion; `max_documents` exists only for tests and, when it stops the
    traversal early, the manifest is marked `truncated` and `apply` refuses it.
    There is no configuration under which a partial manifest can look whole.

    DETERMINISTIC. Sorted by `_id`, so two runs over unchanged data produce
    byte-identical manifests and a diff between them means the DATA moved.
    Nothing here is time-stamped, for the same reason — except `migration_id`,
    which identifies this plan and is deliberately unique.
    """
    records: list[dict] = []
    blocked: list[dict] = []
    outcome_counts: dict[str, int] = {}
    seen_plan: dict[str, str] = {}

    cursor_id: str | None = None
    examined = 0
    truncated = False

    while True:
        query: dict = {"schema_version": {"$ne": 2}}
        if cursor_id is not None:
            query["_id"] = {"$gt": cursor_id}
        batch = await (get_documents_col()
                       .find(query)
                       .sort("_id", 1)
                       .limit(DRY_RUN_BATCH)
                       .to_list(length=DRY_RUN_BATCH))
        if not batch:
            break

        for doc in batch:
            if max_documents is not None and examined >= max_documents:
                truncated = True
                break
            examined += 1
            record, blocker = await _plan_one(doc, seen_plan)
            if blocker:
                blocked.append(record)
            else:
                records.append(record)
                outcome_counts[record["outcome"]] = \
                    outcome_counts.get(record["outcome"], 0) + 1

        if truncated:
            break
        cursor_id = batch[-1]["_id"]
        if len(batch) < DRY_RUN_BATCH:
            break

    already = await get_documents_col().count_documents({"schema_version": 2})
    catalogue = outcome_catalogue()

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "migration_id": f"mig-{uuid.uuid4()}",
        "policy_version": MIGRATION_POLICY_VERSION,
        # An apply refuses to run until an owner has approved the outcomes that
        # change a user-visible state. Filled in by `approve`.
        "approved_decision_set": None,
        "complete": not truncated,
        "truncated": truncated,
        "summary": _manifest_summary(records, blocked, already, examined),
        "by_outcome": {
            code: {"count": count, **catalogue[code]}
            for code, count in sorted(outcome_counts.items())
        },
        "requires_owner_approval": sorted(
            code for code in outcome_counts
            if catalogue[code]["requires_owner_approval"]),
        "blocked_by_reason": _group_by_reason(blocked),
        "would_create": _projected_writes(records),
        # WHAT THE LEGACY ESTATE LOOKED LIKE WHEN THIS WAS PLANNED. See
        # `_estate_check`: a document created between planning and applying
        # belongs to no record, so no per-record check can ever mention it.
        "estate": _estate_fingerprint(records, blocked),
        "records": records,
        "blocked": blocked,
    }
    manifest["fingerprint"] = manifest_fingerprint(manifest)
    return manifest


def _estate_fingerprint(records: list[dict], blocked: list[dict]) -> dict:
    """Every legacy document this plan knows about, hashed.

    Ids only, not their contents: a document whose CONTENTS changed is already
    caught per-record as drift, with a counter naming it. What no per-record
    check can catch is a document that appears after planning — it belongs to no
    record, so nothing iterates over it and nothing counts it.
    """
    ids = sorted([r["document_id"] for r in records]
                 + [r["document_id"] for r in blocked])
    return {
        "eligible_count": len(ids),
        "eligible_ids_sha256": hashlib.sha256(
            "\n".join(ids).encode("utf-8")).hexdigest(),
    }


async def _estate_check(manifest: dict) -> None:
    """Refuse an apply whose estate has grown since the manifest was approved.

    ONLY GROWTH IS A REFUSAL, and the asymmetry is deliberate.

    A document that has DISAPPEARED from the legacy estate is either already
    migrated (a resumed run — the normal case after a crash) or deleted, and
    both are reported per-record as `already_applied` or `document_gone`.
    Treating a shrinking estate as a mismatch would mean an interrupted
    migration could never be resumed, only re-planned against an estate it had
    already half-changed — which is the failure mode that gets safety checks
    switched off by whoever is on call at the time.

    A document that has APPEARED is in no record at all. Nothing would examine
    it, nothing would count it, and the run would report complete success over a
    collection that is not fully converted.
    """
    planned = {r["document_id"] for r in manifest.get("records", [])}
    planned |= {r["document_id"] for r in manifest.get("blocked", [])}

    unknown: list[str] = []
    cursor_id = None
    while True:
        query: dict = {"schema_version": {"$ne": 2}}
        if cursor_id is not None:
            query["_id"] = {"$gt": cursor_id}
        batch = await (get_documents_col()
                       .find(query, {"_id": 1})
                       .sort("_id", 1)
                       .limit(DRY_RUN_BATCH)
                       .to_list(length=DRY_RUN_BATCH))
        if not batch:
            break
        unknown.extend(d["_id"] for d in batch if d["_id"] not in planned)
        cursor_id = batch[-1]["_id"]
        if len(batch) < DRY_RUN_BATCH:
            break

    if unknown:
        raise ManifestRejected(
            f"the legacy estate has changed since this manifest was planned: "
            f"{len(unknown)} document(s) exist that no record covers "
            f"(e.g. {', '.join(sorted(unknown)[:3])}). Re-plan and re-approve.")


async def _plan_one(doc: dict, seen_plan: dict[str, str]) -> tuple[dict, bool]:
    """Plan one document. Returns (record, is_blocked)."""
    doc_id = doc["_id"]
    plan_id = planned_revision_id(doc_id)
    codes: list[str] = []

    if not doc.get("template_type"):
        codes.append(BLOCK_NO_TEMPLATE_TYPE)
    if not doc.get("client_id"):
        codes.append(BLOCK_NO_CLIENT)
    if not doc.get("created_at"):
        codes.append(FLAG_NO_CREATED_AT)

    existing = await get_document_revisions_col().find_one(
        {"_id": plan_id}, {"document_id": 1})
    if existing is not None and existing.get("document_id") != doc_id:
        codes.append(BLOCK_ID_COLLISION)
    elif existing is not None:
        codes.append(FLAG_ALREADY_PLANNED)

    if plan_id in seen_plan:
        codes.append(BLOCK_DUPLICATE_PLAN)
    seen_plan[plan_id] = doc_id

    source = read_source(doc.get("file_path"))
    status = doc.get("review_status")

    # Both of these BLOCK, and both are checked before `classify` is consulted.
    # An unreadable file and an unrecognised status have the same shape of
    # danger: the migration knows less than it would need to know to act, and
    # acting anyway changes user-visible state that re-running cannot restore.
    if source.unreadable:
        codes.append(BLOCK_UNREADABLE_FILE)
    if not is_supported_status(status):
        codes.append(BLOCK_UNSUPPORTED_STATUS)

    blocking = [c for c in codes if c in BLOCKING_CODES]
    if blocking:
        # No outcome is recorded. A blocked document has not been given a fate,
        # and naming one here would put a plan in the manifest that nobody
        # intends to run — the exact thing an approver would then skim past.
        outcome_code = None
        requires_approval = False
    else:
        outcome = classify(doc, file_present=source.present)
        outcome_code = outcome.code
        requires_approval = outcome.requires_owner_approval
        if not source.present:
            codes.append(FLAG_FILE_MISSING)
        if status == "approved":
            codes.append(FLAG_APPROVED_UNVERIFIED)
            if not source.present:
                codes.append(FLAG_NEEDS_REAPPROVAL)

    record = {
        "document_id": doc_id,
        "meta_hash": _meta_hash(doc),
        "file_path": doc.get("file_path"),
        "file_present": source.present,
        "byte_sha256": source.sha256,
        "size": source.size,
        "prev_review_status": status,
        "observed_status": status,
        "reviewer": doc.get("submitted_to"),
        "was_approved": status == "approved",
        "planned_revision_id": plan_id,
        "template_type": doc.get("template_type"),
        "outcome": outcome_code,
        "requires_owner_approval": requires_approval,
        "source_unreadable": source.unreadable,
        "source_error_class": source.error_class,
        "codes": sorted(codes),
        # THE reason, singular, for a reader who needs one thing to act on.
        # `codes` stays because a record can carry several; `reason` is the
        # first blocking one in a stable order, so grouping and diffing two
        # runs does not depend on set iteration.
        "reason": sorted(blocking)[0] if blocking else None,
    }
    return record, bool(blocking)


def approve(manifest: dict, decision_set_id: str) -> dict:
    """Record an owner's approval of this exact plan.

    The identifier is bound to the FINGERPRINT, so approving one manifest does
    not approve a different one that happens to arrive later. Re-planning after
    approval produces a new fingerprint and needs approving again — which is the
    point: the thing that runs must be the thing that was read.
    """
    approved = dict(manifest)
    approved["approved_decision_set"] = {
        "id": decision_set_id,
        "manifest_fingerprint": manifest["fingerprint"],
        "policy_version": manifest["policy_version"],
        "outcomes_approved": list(manifest.get("requires_owner_approval", [])),
    }
    return approved


def _require_applicable(manifest: dict) -> None:
    """Everything that must hold before a single document is touched.

    Each of these has a failure mode that is silent if unchecked: an incomplete
    manifest migrates a prefix, an altered one migrates something nobody read, a
    subset one reports success for work it never planned, and an unapproved one
    relabels approvals on somebody's legal documents without being asked.
    """
    if manifest.get("manifest_schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ManifestRejected(
            "manifest_schema_version mismatch: this build applies "
            f"{MANIFEST_SCHEMA_VERSION}")
    if manifest.get("policy_version") != MIGRATION_POLICY_VERSION:
        raise ManifestRejected(
            "policy_version mismatch: the manifest was planned under different "
            "migration rules and must be re-planned")
    if not manifest.get("migration_id"):
        raise ManifestRejected("manifest has no migration_id")
    if not manifest.get("complete") or manifest.get("truncated"):
        raise ManifestRejected(
            "manifest is truncated — it describes a prefix of the collection, "
            "and applying it would migrate part of the estate with nothing "
            "recording which part")
    if manifest.get("blocked"):
        raise ManifestRejected(
            f"manifest has {len(manifest['blocked'])} blocked record(s); "
            "resolve them and re-plan")

    if manifest.get("fingerprint") != manifest_fingerprint(manifest):
        raise ManifestRejected(
            "manifest fingerprint does not match its contents — it was altered "
            "after planning")

    approval = manifest.get("approved_decision_set")
    needed = manifest.get("requires_owner_approval") or []
    if needed:
        if not approval:
            raise ManifestRejected(
                "this plan changes user-visible state for outcomes "
                f"{needed} and has not been approved")
        if approval.get("manifest_fingerprint") != manifest["fingerprint"]:
            raise ManifestRejected(
                "the approval belongs to a different manifest")
        if sorted(approval.get("outcomes_approved") or []) != sorted(needed):
            raise ManifestRejected(
                "the approved outcome set does not match this plan")


def _manifest_summary(records: list[dict], blocked: list[dict],
                      already: int, examined: int) -> dict:
    return {
        "legacy_documents_examined": examined,
        "eligible": len(records),
        "blocked": len(blocked),
        "already_migrated_not_examined": already,
        "eligible_with_file": sum(1 for r in records if r["file_present"]),
        "eligible_missing_file": sum(1 for r in records if not r["file_present"]),
        "eligible_approved": sum(1 for r in records if r["was_approved"]),
        # Counts, not ids. `blocked_by_reason` already carries the ids; an
        # approver deciding whether to proceed needs the size of each problem
        # before they need its membership.
        "blocked_by_reason_counts": _count_by_reason(blocked),
    }


def _count_by_reason(blocked: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in blocked:
        for code in record["codes"]:
            if code in BLOCKING_CODES:
                counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _group_by_reason(blocked: list[dict]) -> dict[str, list[str]]:
    """Document ids per reason code, so a reader can act on a group at a time.

    Ids rather than counts: "eleven documents have no template type" prompts
    the question "which?", and a report that cannot answer it sends someone
    back to the database to re-derive what this pass already knew.
    """
    grouped: dict[str, list[str]] = {}
    for record in blocked:
        for code in record["codes"]:
            if code in BLOCKING_CODES:
                grouped.setdefault(code, []).append(record["document_id"])
    return {code: sorted(ids) for code, ids in sorted(grouped.items())}


def _projected_writes(records: list[dict]) -> dict:
    """What an apply would create, counted from what apply actually writes.

    REVIEW EVENTS AND TRANSITION RECEIPTS ARE ZERO, and that is not an omission.
    `apply` backfills a v1 revision and repoints the document; it records no
    transition, because no transition happened — nobody submitted, reviewed or
    withdrew anything during a migration. Reporting a projected count here would
    invent history, which is the one thing a migration into an audit trail must
    never do.
    """
    with_file = sum(1 for r in records if r["file_present"])
    return {
        "document_revisions": len(records),
        "revisions_generated": with_file,
        "revisions_failed_no_file": len(records) - with_file,
        "documents_updated": len(records),
        "artifact_files_copied": with_file,
        "review_events": 0,
        "transition_receipts": 0,
        "notifications": 0,
    }


# ── THE MIGRATION ORDERING RULE ───────────────────────────────────────────────
#
# MIGRATE FIRST. FLIP THE FLAG SECOND. In that order, always.
#
# The V2 review queue selects on `schema_version: 2`, because a V2 row is the
# only kind whose submitted revision and hash it can return — a legacy document
# has neither, and a queue row without them cannot be previewed or decided on.
#
# The consequence is that a legacy document submitted to a lawyer is INVISIBLE
# to the V2 queue. Flip the flag before migrating and every such document
# silently leaves that lawyer's inbox: no error, no empty state, no notification
# — the work simply is not listed any more, and the client waits for a review
# that nobody can see they were asked for.
#
# Reversing the order costs nothing: a migrated document is served by the V2
# queue with the flag on and by the legacy queue with it off, so the window
# between migrating and flipping is safe in both directions.
#
# `queue_visibility_gap()` is that rule made checkable. It is READ-ONLY and is
# meant to be run immediately before the flip: a non-empty result is a refusal,
# not a warning.

QUEUE_VISIBLE_STATUSES = ("submitted", "approved", "returned", "rejected")


async def queue_visibility_gap(limit: int = 10_000) -> dict:
    """Documents that would vanish from a lawyer's queue if the flag flipped now.

    A document counts when it is BOTH in some lawyer's queue (it has a review
    relationship and a live review status) AND still legacy (`schema_version`
    is not 2). Those are exactly the rows the V2 queue cannot select and the
    legacy queue will stop being asked for.

    Grouped by lawyer, because the question an operator actually has is "who
    loses work", not "how many rows". Writes nothing.
    """
    from app.db.collections import get_documents_col

    query = {
        "schema_version": {"$ne": 2},
        "review_status": {"$in": list(QUEUE_VISIBLE_STATUSES)},
        # Either half of the review relationship. `submitted_to` is the current
        # assignment; `reviewer_id` is the historical stamp that survives a
        # return or a reject. A legacy row will normally have only the first,
        # but checking both means this cannot under-report after a partial
        # migration.
        "$or": [{"submitted_to": {"$ne": None}},
                {"reviewer_id": {"$ne": None}}],
    }
    projection = {"_id": 1, "submitted_to": 1, "reviewer_id": 1,
                  "review_status": 1, "title": 1}
    rows = await (get_documents_col()
                  .find(query, projection)
                  .sort("_id", 1).limit(limit)
                  .to_list(length=limit))

    by_lawyer: dict[str, list[str]] = {}
    by_status: dict[str, int] = {s: 0 for s in QUEUE_VISIBLE_STATUSES}
    for row in rows:
        lawyer = row.get("submitted_to") or row.get("reviewer_id")
        by_lawyer.setdefault(str(lawyer), []).append(row["_id"])
        status = row.get("review_status")
        if status in by_status:
            by_status[status] += 1

    return {
        # RENAMED from `safe_to_enable`, which claimed more than this check can
        # know. It inspects ONE gate — the documents that would drop out of a
        # lawyer's queue — and says nothing about whether the indexes exist or
        # whether the migration has run at all. A key called `safe_to_enable` is
        # the line an operator reads at the moment of the decision, and a green
        # one grants permission it never checked for.
        #
        # `activation_readiness()` is the composed signal. Use that to decide.
        "queue_gap_empty": not rows,
        "at_risk": len(rows),
        "by_lawyer": {k: sorted(v) for k, v in sorted(by_lawyer.items())},
        "by_status": by_status,
        "document_ids": sorted(r["_id"] for r in rows),
    }


# How many problem documents are listed in the report. NOT a limit on the scan.
DEFAULT_READINESS_SAMPLE = 200
# Documents per cursor batch. Bounds memory, not coverage.
DEFAULT_READINESS_BATCH = 500


async def activation_readiness(sample: int = DEFAULT_READINESS_SAMPLE,
                               batch: int = DEFAULT_READINESS_BATCH) -> dict:
    """May DOCUMENTS_V2 be turned on? The whole question, in one answer.

    READ-ONLY, because it is run against production at the decision point.

    WHY IT IS COMPOSED RATHER THAN ANOTHER PARTIAL CHECK
    ----------------------------------------------------
    There were three partial answers and no whole one. The index preflight knew
    about indexes, `queue_visibility_gap` knew about the queue, and nothing knew
    whether the migration had actually finished. Both of the first two once
    returned a key called `safe_to_enable`, and an operator reading either at
    the moment of the flip would have been told "safe" by a check that had not
    looked at the thing that was wrong.

    THE GATES, and what each one stops:

      indexes                  — the unique indexes ARE the correctness
                                 guarantees. Flipping without them does not
                                 degrade the system, it removes the constraints
                                 the code assumes are enforced.
      migration_complete       — a legacy document after the flip is served by
                                 nothing: the V2 queue cannot select it and the
                                 legacy queue stops being asked. The work does
                                 not error, it silently ceases to be listed.
      queue_visibility         — the same failure, narrowed to the documents a
                                 lawyer is actually waiting on, so the report
                                 can say who loses work.
      migrated_documents_valid — `inspect_migrated` already knew what a broken
                                 document looks like and nothing consulted it
                                 before a flip. A migration can complete and
                                 still produce documents that validate and
                                 cannot be opened.

    The inspection gate examines EVERY migrated document, in bounded cursor
    batches. It once sampled, and this line once said so long after the code
    had changed — which is worse than either behaviour on its own, because a
    reader would distrust a verdict that is actually sound, and the whole value
    of this gate is that somebody believes it at the moment of the flip.

    `sample` bounds the problem DETAIL in the report; `batch` bounds memory.
    Neither bounds the verdict.
    """
    from app.db import v2_index_preflight

    # REFUSED, not coerced. `sample=-1` slices `problems[:-1]` and silently
    # drops the last failure; `batch=0` is NO limit in Mongo, so the argument
    # that exists to bound memory would remove the bound. Both look like they
    # worked.
    if sample < 0:
        raise ValueError("sample must be zero or greater")
    if batch < 1:
        raise ValueError("batch must be at least 1")

    gates: dict[str, dict] = {}
    blockers: list[str] = []

    try:
        index_result = await v2_index_preflight.preflight()
    except Exception as exc:                       # noqa: BLE001 — fail closed
        logger.exception("activation_readiness: index preflight failed")
        gates["indexes"] = {"passed": False,
                            "error": f"{type(exc).__name__}: {exc}"}
        blockers.append("could not establish that the indexes are ready")
        index_result = None
    if index_result is not None:
        gates["indexes"] = {
        "passed": bool(index_result["indexes_ready"]),
            "problems": len(index_result.get("problems", [])),
            "correctness_problems": index_result.get("correctness_problems", 0),
        }
        if not gates["indexes"]["passed"]:
            blockers.append(
                f"{gates['indexes']['problems']} index problem(s): the unique "
                "indexes are the correctness guarantees, not an optimisation")

    try:
        legacy_remaining = await get_documents_col().count_documents(
            {"schema_version": {"$ne": 2}})
        gates["migration_complete"] = {
            "passed": legacy_remaining == 0,
            "legacy_remaining": legacy_remaining,
        }
        if legacy_remaining:
            blockers.append(
                f"{legacy_remaining} document(s) have not been migrated; after "
                "the flip they are served by neither queue and simply stop "
                "being listed")
    except Exception as exc:                       # noqa: BLE001 — fail closed
        logger.exception("activation_readiness: legacy count failed")
        gates["migration_complete"] = {"passed": False,
                                       "error": f"{type(exc).__name__}: {exc}"}
        blockers.append("could not establish whether the migration is complete")

    try:
        gap = await queue_visibility_gap()
        gates["queue_visibility"] = {
            "passed": bool(gap["queue_gap_empty"]),
            "at_risk": gap["at_risk"],
            "by_lawyer": gap["by_lawyer"],
        }
        if not gates["queue_visibility"]["passed"]:
            blockers.append(
                f"{gap['at_risk']} document(s) would drop out of a lawyer's "
                f"queue, affecting {len(gap['by_lawyer'])} lawyer(s)")
    except Exception as exc:                       # noqa: BLE001 — fail closed
        logger.exception("activation_readiness: queue-visibility scan failed")
        gates["queue_visibility"] = {"passed": False,
                                     "error": f"{type(exc).__name__}: {exc}"}
        blockers.append("could not establish the queue-visibility gap")

    gates["migrated_documents_valid"] = await _inspect_all_migrated(
        sample=sample, batch=batch)
    if not gates["migrated_documents_valid"]["passed"]:
        blockers.append(gates["migrated_documents_valid"]["blocker"])

    return {
        "ready": not blockers,
        "blockers": blockers,
        "gates": gates,
        "sample": sample,
    }


# The problem LIST is capped; the problem COUNT never is. A report nobody can
# read is not a report, and a count that stops at the cap is worse than none.
READINESS_PROBLEM_CAP = 20


async def _inspect_all_migrated(*, sample: int, batch: int) -> dict:
    """Inspect EVERY migrated document, in bounded cursor batches.

    THE DEFECT THIS REPLACES. This gate used to look at 200 documents and hand
    that back as a global `ready`. On an estate of any real size that is a
    verdict about the first 200 rows presented as a verdict about all of them —
    and the flip it authorises affects every one. A migration failure
    concentrated past row 200 is exactly the kind least likely to be noticed by
    hand, so the sample was blindest where it most needed to see.

    `sample` now bounds the DETAIL, not the scan: it is the most problem records
    the report will list. `examined` says how many documents actually decided the
    verdict, and `unusable` is the full count regardless of how many are listed.
    `sample=0` lists nothing and changes the verdict not at all — a caller who
    passes 0 to skip the detail must not thereby receive an unconditional green.

    An earlier version reported a `sampled` figure of `min(sample, examined)`,
    which corresponded to no sampling that had actually happened. A number that
    describes nothing has no place in a go/no-go report.

    Batched by `_id` keyset so memory stays flat on a large collection; the
    whole point is that this can be run against production.

    FAILS CLOSED. Any error scanning is reported as "could not establish", never
    as ready. An exception escaping here would reach an operator as a traceback
    at the moment of a go/no-go decision; a default of True would be worse.
    """
    problems: list[dict] = []
    unusable = 0
    examined = 0
    batches = 0
    cursor_id = None

    try:
        total = await get_documents_col().count_documents({"schema_version": 2})
        while True:
            query: dict = {"schema_version": 2}
            if cursor_id is not None:
                query["_id"] = {"$gt": cursor_id}
            rows = await (get_documents_col()
                          .find(query, {"_id": 1})
                          .sort("_id", 1).limit(batch)
                          .to_list(length=batch))
            if not rows:
                break
            batches += 1
            for row in rows:
                found = await inspect_migrated(row["_id"])
                examined += 1
                if found:
                    unusable += 1
                    # CAPPED HERE, not on the way out. Appending every failure
                    # and truncating at the end holds one record per document
                    # on an estate where everything is broken — the case where
                    # the machine can least spare it. The COUNT is kept
                    # separately and stays truthful.
                    if len(problems) < READINESS_PROBLEM_CAP:
                        problems.append({"document_id": row["_id"],
                                         "problems": found})
            cursor_id = rows[-1]["_id"]
            if len(rows) < batch:
                break
    except Exception as exc:                       # noqa: BLE001 — fail closed
        logger.exception("activation_readiness: migrated-document scan failed")
        return {
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
            "examined": examined,
            "total": None,
            # The FULL count, not the length of the capped detail list. Capping
            # the detail during the scan was right; reusing that length as the
            # count afterwards understated the damage — a scan that found forty
            # broken documents and then died would have reported twenty, in the
            # one report whose job is to describe how bad it is.
            "unusable": unusable,
            "problems": problems[:min(sample, READINESS_PROBLEM_CAP)],
            "problems_listed": len(problems[:min(sample, READINESS_PROBLEM_CAP)]),
            "batches": batches,
            "blocker": ("could not establish that the migrated documents are "
                        f"usable: the scan failed after {examined} document(s)"),
        }

    listed = problems[:min(sample, READINESS_PROBLEM_CAP)]

    # THE SCAN MUST HAVE SEEN EVERYTHING IT SET OUT TO SEE.
    #
    # `examined` and `total` were both computed and never compared. A cursor cut
    # short — a stepdown, a timeout, a batch that came back empty early — reads
    # fewer documents than the collection holds, and every one it managed to
    # read is fine. So the gate passed on a partial scan and reported a clean
    # estate, which is the single most dangerous thing this function can say.
    incomplete = total is not None and examined != total

    if incomplete:
        blocker = (f"the scan examined {examined} of {total} migrated "
                   "document(s); it did not finish, so the estate cannot be "
                   "called usable")
    elif problems:
        blocker = (f"{unusable} of {examined} migrated document(s) are not "
                   "usable — see inspect_migrated")
    else:
        blocker = None

    return {
        "passed": not problems and not incomplete,
        "error": None,
        # `examined` is what decided the verdict. `problems_listed` is only how
        # many are shown in detail, and it decides nothing.
        "examined": examined,
        "total": total,
        "complete": not incomplete,
        # The full count, not the length of the capped list.
        "unusable": unusable,
        "problems": listed,
        "problems_listed": len(listed),
        "batches": batches,
        "blocker": blocker,
    }


def render_activation_readiness(result: dict) -> str:
    """The report an operator reads before deciding. Names every gate.

    Passing gates are listed too: a signal that shows only failures cannot be
    told apart from one that forgot to check anything.
    """
    lines = ["DOCUMENTS_V2 activation readiness", ""]
    lines.append("  READY: every gate passed." if result["ready"]
                 else f"  NOT READY: {len(result['blockers'])} blocker(s).")
    lines.append("")
    for name, gate in result["gates"].items():
        mark = "ok  " if gate["passed"] else "FAIL"
        detail = ", ".join(f"{k}={v}" for k, v in gate.items()
                           if k != "passed" and not isinstance(v, (list, dict)))
        lines.append(f"  [{mark}] {name}" + (f"  ({detail})" if detail else ""))
    if result["blockers"]:
        lines += ["", "  Blockers:"]
        lines += [f"    - {b}" for b in result["blockers"]]
    lines += ["", "  This check writes nothing. It does not flip the flag."]
    return "\n".join(lines)


def manifest_fingerprint(manifest: dict) -> str:
    """A stable hash of the planning content of a manifest.

    Excludes the summary, which is derivable, so two manifests with the same
    fingerprint plan exactly the same work. This is what an approver signs off
    and what apply should be checked against — approving a manifest is only
    meaningful if the thing that runs later is provably the same one.
    """
    # EVERY authoritative field, not just the record lists. The previous
    # fingerprint covered records and blocked only, so a manifest could be
    # marked complete, have its policy version rewritten, or gain an approval
    # for outcomes it does not contain, and still fingerprint identically.
    material = {
        "manifest_schema_version": manifest.get("manifest_schema_version"),
        # `migration_id` is DELIBERATELY ABSENT. It identifies the RUN and is
        # unique by construction; the fingerprint identifies the PLAN, and two
        # dry runs over unchanged data must produce the same one — that is what
        # makes a diff between manifests mean the data moved, and what lets an
        # approval be checked against a re-plan. Rollback uses the migration_id;
        # approval uses the fingerprint. They answer different questions.
        "policy_version": manifest.get("policy_version"),
        "complete": manifest.get("complete"),
        "truncated": manifest.get("truncated"),
        "requires_owner_approval": sorted(
            manifest.get("requires_owner_approval") or []),
        "by_outcome": {k: v.get("count")
                       for k, v in (manifest.get("by_outcome") or {}).items()},
        "records": manifest.get("records", []),
        "blocked": manifest.get("blocked", []),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


# ── APPLY ─────────────────────────────────────────────────────────────────────

# ── THE SOURCE SNAPSHOT ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class SourceSnapshot:
    """One legacy PDF, read ONCE.

    The previous apply read each file three times — `_file_stat` for the hash
    and size, `read_bytes()` for the artifact, and `extract_pdf_text` for the
    text — and used the results together as if they described one thing. They
    describe three moments. A file rewritten between the first and the third
    produces an artifact whose bytes do not match the hash recorded beside it,
    and a verification verdict computed from text that is in neither.

    Everything downstream is derived from `data`, so it cannot disagree with
    itself.
    """

    present: bool
    data: bytes | None
    sha256: str | None
    size: int | None
    # A READ THAT FAILED IS NOT A FILE THAT IS GONE.
    #
    # These two used to collapse into `present=False`, and "gone" is what drives
    # needs_reapproval and migration_unrecoverable. So a locked file, a stale
    # mount, an exhausted file-handle table or an NFS blip during the migration
    # window would silently withdraw a lawyer's approval on a document that was
    # never damaged — and re-running would not undo it, because by then the
    # legacy status has been overwritten.
    #
    # Absence is a fact about the estate. Unreadability is a fact about the
    # attempt, and the right response to it is a human, not a status change.
    unreadable: bool = False
    error_class: str | None = None


def read_source(path: str | None) -> SourceSnapshot:
    """Read a legacy file once and derive everything from that byte string."""
    if not path:
        return SourceSnapshot(False, None, None, None)
    p = Path(path)
    try:
        data = p.read_bytes()
    except FileNotFoundError:
        # The only error that means what it says: nothing is at this path.
        return SourceSnapshot(False, None, None, None,
                              error_class="FileNotFoundError")
    except OSError as exc:
        # PermissionError, IsADirectoryError, NotADirectoryError, TimeoutError
        # and every other IO failure are all OSError subclasses. None of them
        # says the document is gone.
        return SourceSnapshot(False, None, None, None, unreadable=True,
                              error_class=type(exc).__name__)
    return SourceSnapshot(True, data, hashlib.sha256(data).hexdigest(), len(data))


def _cas_filter(doc: dict) -> dict:
    """The legacy state this migration was planned against.

    The update used to be `{"_id": doc_id}`, which overwrites whatever is there
    now. Between the manifest and the apply a client can regenerate, submit or
    withdraw — and a document half-described by an old plan and half by a new
    reality is the worst outcome available, because nothing detects it later.

    EVERY FIELD THE MANIFEST VERIFIES IS GUARDED HERE, and that identity is
    asserted by a test. `_meta_hash` compares the material fields when the
    document is read; the CAS re-checks them at the instant of the write. Only
    the second one closes the window, because everything expensive — citation
    verification, extraction, the artifact write, the revision insert — happens
    between the two, and a client editing their document in that stretch was
    previously invisible.

    It is also no WIDER than that. Guarding fields the migration does not depend
    on would turn any unrelated background write into a spurious drift, and a
    migration that skips half its records for no reason gets its safety checks
    removed by whoever has to run it.
    """
    guard = {k: doc.get(k) for k in _META_FIELDS}
    guard.update({
        "_id": doc["_id"],
        "schema_version": {"$ne": 2},
        "review_status": doc.get("review_status"),
        "submitted_to": doc.get("submitted_to"),
        "file_path": doc.get("file_path"),
    })
    return guard


async def apply(manifest: dict) -> dict:
    """Backfill from an APPROVED, COMPLETE manifest.

    Idempotent, and every record is applied under a compare-and-set on the
    legacy state it was planned against — so a document edited since the dry run
    is skipped whole rather than migrated half-way.
    """
    from app.services.document_service import _unavailable_verification, _verification_record
    from app.services.document_v2_service import _build_verification_inputs
    from app.services.pdf_generator import extract_pdf_text_bytes
    from app.services import pleading_rules

    _require_applicable(manifest)
    # Immediately before the first write, not at planning time: the point is to
    # measure the gap between approval and application, which is where a human
    # was reading and no check was running.
    await _estate_check(manifest)
    migration_id = manifest["migration_id"]

    # EVERY RECORD LANDS IN EXACTLY ONE TERMINAL BUCKET.
    #
    # The previous counters incremented `generated` and `missing` while building
    # the revision — before the document CAS that decides whether any of it
    # counts. A record that lost the CAS was reported as generated, so the
    # summary overstated the work done and the totals reconciled with nothing.
    #
    # `orphan_detected` is deliberately NOT terminal: it is a property of some
    # cas_lost records (the revision row was inserted, then no document came to
    # point at it), so it overlaps `drifted` and is excluded from the sum.
    n = dict.fromkeys(
        ("applied", "already_applied", "drifted", "blocked",
         "revision_collision", "document_gone", "failed"), 0)
    detail = dict.fromkeys(("generated", "missing", "orphan_detected"), 0)
    outcomes: dict[str, int] = {}
    rollback_manifest: list[dict] = []
    failures: list[dict] = []

    for rec in manifest.get("records", []):
        # PER-RECORD ISOLATION.
        #
        # Without this an unexpected error ends the run wherever it happened
        # to be. The documents already migrated stay migrated, the rest are
        # untouched, and the caller gets a traceback instead of a summary —
        # so nobody can tell which half is which. The reconciliation check
        # never runs either, because the function never returns.
        #
        # Nothing is rolled back here: every write below is already
        # individually guarded (the revision insert is idempotent, the
        # document CAS is all-or-nothing), so a record that dies part-way
        # leaves at worst an inert revision row a rerun will re-validate.
        try:
            doc = await get_documents_col().find_one({"_id": rec["document_id"]})
            if not doc:
                n["document_gone"] += 1
                logger.warning("migration_skip reason=document_gone document=%s",
                               rec["document_id"])
                continue
            if not _is_legacy(doc):
                n["already_applied"] += 1
                continue

            if _meta_hash(doc) != rec["meta_hash"]:
                n["drifted"] += 1
                logger.warning("migration_skip reason=metadata_drift document=%s",
                               rec["document_id"])
                continue

            # ONE READ. Hash, size, artifact bytes and extracted text all come from
            # this snapshot; see SourceSnapshot.
            source = read_source(doc.get("file_path"))

            if source.unreadable:
                # Planning saw a readable file; this process cannot read it. That is
                # a fact about now, not about the document, so nothing is written
                # and nothing is relabelled — the record is simply left for a rerun.
                n["blocked"] += 1
                logger.warning("migration_skip reason=%s document=%s error=%s",
                               BLOCK_UNREADABLE_FILE, rec["document_id"],
                               source.error_class)
                continue

            if not is_supported_status(doc.get("review_status")):
                # The status changed to something unrecognised after planning.
                n["blocked"] += 1
                logger.warning("migration_skip reason=%s document=%s",
                               BLOCK_UNSUPPORTED_STATUS, rec["document_id"])
                continue

            if (source.present != rec["file_present"]
                    or source.sha256 != rec["byte_sha256"]
                    or source.size != rec["size"]):
                n["drifted"] += 1
                logger.warning("migration_skip reason=file_drift document=%s",
                               rec["document_id"])
                continue

            outcome = classify(doc, file_present=source.present)
            if outcome.code != rec["outcome"]:
                n["drifted"] += 1
                logger.warning("migration_skip reason=outcome_drift document=%s",
                               rec["document_id"])
                continue

            template_type = doc.get("template_type")
            revision_id = rec["planned_revision_id"]
            now = _now()

            if source.present:
                # The key is DERIVED, not written yet. Nothing reaches the artifact
                # store until the revision row is known to be insertable — otherwise
                # a failed collision check leaves a file behind for a revision that
                # never existed, and the store accumulates artifacts no row names.
                artifact_key = store.final_key(revision_id, 0)
                # FROM THE SNAPSHOT. Never `extract_pdf_text(Path(...))` here: a
                # second read of the path is a second moment in time, and the
                # revision would then hold bytes, a hash and a body that need not
                # describe the same document.
                text, raw_status = extract_pdf_text_bytes(source.data)
                xstatus, profile, body_text, unavail = _build_verification_inputs(
                    template_type, text, raw_status)
                if xstatus == "ok":
                    verification = await _verification_record({"document": body_text})
                    text_sha256 = hashlib.sha256(body_text.encode("utf-8")).hexdigest()
                else:
                    verification = _unavailable_verification(unavail)
                    text_sha256 = None
                rev_status = "generated"
            else:
                artifact_key = text_sha256 = body_text = None
                xstatus, profile = "failed", extraction_profile.profile_for(template_type)
                verification = _unavailable_verification("legacy_file_missing")
                rev_status = "failed"

            compliance = doc.get("compliance") or pleading_rules.check_pleading(
                template_type, doc.get("fields") or {})

            revision = {
                "_id": revision_id, "document_id": doc["_id"], "version": 1,
                "status": rev_status, "template_type": template_type,
                "idempotency_key": f"migration:{revision_id}",
                "fields": doc.get("fields") or {}, "artifact_key": artifact_key,
                "pdf_sha256": source.sha256, "text_sha256": text_sha256,
                "body_text": body_text, "extraction_status": xstatus,
                "extraction_profile": profile, "compliance": compliance,
                "verification": verification, "fence": 0,
                "migrated": True, "migration_id": migration_id, "created_at": now,
            }

            conflict, inserted = await _upsert_revision(
                revision, artifact_bytes=source.data)
            if conflict is not None:
                n["revision_collision"] += 1
                logger.warning("migration_skip reason=%s document=%s revision=%s",
                               conflict, rec["document_id"], revision_id)
                continue

            set_fields = _document_fields(doc, outcome, revision_id, source,
                                          migration_id, now)

            # THE ROLLBACK ENTRY IS BUILT BEFORE THE WRITE, and its token goes
            # into the same `$set`.
            #
            # It was briefly a second `update_one` after the CAS, which is a
            # gap: a process dying between the two leaves a document that is
            # migrated and carries no token, and the rollback verifier would
            # then read that as a tampered plan and refuse to undo it. A crash
            # would have made the migration permanent.
            #
            # Everything the token covers is already known here — `set_fields`
            # holds the post-migration pointers, `doc` holds the previous ones —
            # so one atomic write does both.
            entry = {
                "document_id": doc["_id"],
                "migration_id": migration_id,
                "applied_revision_id": revision_id,
                "applied_at": now,
                "source_fingerprint": rec["meta_hash"],
                "prev_review_status": doc.get("review_status"),
                "prev_schema_version": doc.get("schema_version"),
                "added_fields": sorted(set_fields.keys()),
                "post_review_status": set_fields.get(
                    "review_status", doc.get("review_status")),
                "post_current_revision_id": set_fields.get("current_revision_id"),
            }
            entry["rollback_token"] = rollback_entry_token(entry)
            set_fields["rollback_token"] = entry["rollback_token"]

            updated = await get_documents_col().find_one_and_update(
                _cas_filter(doc), {"$set": set_fields})
            if updated is None:
                # The document changed between the read above and this write.
                # Nothing partial was left behind: the revision row is inert until
                # a document points at it, and the reconciler sweeps orphans.
                n["drifted"] += 1
                if inserted:
                    detail["orphan_detected"] += 1
                logger.warning("migration_skip reason=cas_lost document=%s orphan=%s",
                               rec["document_id"], inserted)
                continue

            # ONLY NOW. Everything above this line could still have come to nothing.
            detail["generated" if source.present else "missing"] += 1
            outcomes[outcome.code] = outcomes.get(outcome.code, 0) + 1
            # `post_*` record THE STATE THIS MIGRATION LEFT THE DOCUMENT IN, so
            # rollback can compare-and-set on it — including the outcomes that
            # legitimately leave `current_revision_id` null, which cannot
            # otherwise be told apart from somebody having unset it.
            #
            # The token's other copy is now on the document itself (written in
            # the same `$set` above), which is what makes an edited plan
            # detectable: a plan can re-sign its own fingerprint, but it cannot
            # reach into the database and change what was recorded there.
            rollback_manifest.append(entry)
            n["applied"] += 1

        except Exception as exc:
            n["failed"] += 1
            failures.append({
                "document_id": rec["document_id"],
                "error_class": type(exc).__name__,
                # The message, NOT the traceback: this dict is returned to a
                # caller and logged, and a traceback can carry file paths and
                # query fragments. The traceback goes to the log only.
                "error": str(exc)[:300],
            })
            logger.exception("migration_record_failed document=%s",
                             rec["document_id"])
    total = len(manifest.get("records", []))
    reconciled = sum(n.values())
    if reconciled != total:
        # Not an assertion in a test: a run whose outcomes do not account for
        # every planned record has lost track of documents, and the report is
        # the only place anyone would ever see that.
        logger.error("migration_accounting_mismatch planned=%s accounted=%s "
                     "migration=%s", total, reconciled, migration_id)

    return {
        "migration_id": migration_id,
        "summary": {
            **n,
            **detail,
            "planned_records": total,
            "accounted_records": reconciled,
            "reconciles": reconciled == total,
            # `skipped_drift` was the old name and some callers still read it.
            "skipped_drift": n["drifted"],
        },
        # WHICH ones, not just how many. "1 failed" over an estate of thousands
        # is not something an operator can act on.
        "failures": failures,
        "by_outcome": outcomes,
        # A STRUCTURE, not a bare list. The header carries the schema version
        # and the fingerprint that make the entries checkable later; see
        # `_validate_rollback_plan`.
        "rollback_plan": _rollback_plan(migration_id, rollback_manifest),
    }


async def _upsert_revision(revision: dict,
                           artifact_bytes: bytes | None = None
                           ) -> tuple[str | None, bool]:
    """Insert the revision, or accept a SEMANTICALLY IDENTICAL existing one.

    Returns `(reason, inserted)` — reason is None on success, or a code when an
    existing row is NOT the one this migration would have written. `inserted`
    says whether this call created the row, which is what makes a later CAS loss
    distinguishable as an orphan rather than a harmless retry.

    `$setOnInsert` alone silently accepted whatever was already there, so a
    crashed half-run or a hand-edited row would be adopted as if this migration
    had produced it.
    """
    col = get_document_revisions_col()
    existing = await col.find_one({"_id": revision["_id"]})
    if existing is None:
        # Write the artifact FIRST, then the row. This order can leave an
        # unreferenced artifact if the process dies between the two, which the
        # reconciler sweeps; the other order can leave a row pointing at bytes
        # that do not exist, which reads as a corrupt document.
        if artifact_bytes is not None:
            store.write_final(revision["_id"], 0, artifact_bytes)
        try:
            await col.insert_one(revision)
            return None, True
        except DuplicateKeyError:
            existing = await col.find_one({"_id": revision["_id"]})
            if existing is None:
                return "revision_insert_failed", False

    mismatch = _revision_mismatch(existing, revision)
    if mismatch:
        # NOTHING NEW IS LEFT BEHIND. The artifact was not written on this path,
        # so a rejected collision changes no state at all — the run can be
        # re-planned after a human has looked at the existing row.
        return f"revision_mismatch_{mismatch}", False

    # The row matches, but a matching row is not a readable document: the bytes
    # it names must actually be there and be the bytes it claims.
    if existing.get("artifact_key"):
        if not store.final_exists(existing["artifact_key"]):
            return "revision_mismatch_artifact_absent", False
        stored = store.open_final(existing["artifact_key"])
        if hashlib.sha256(stored).hexdigest() != existing.get("pdf_sha256"):
            return "revision_mismatch_artifact_bytes", False
    return None, False


# Volatile keys NESTED INSIDE otherwise-semantic fields.
#
# `verification` is substantive — whether the check ran, what it found, the
# scope statement — and it also carries `checked_at`, stamped at the moment the
# check happened. Comparing the field wholesale therefore compares a timestamp,
# and no rerun can ever match one. Dropping the whole field instead would stop
# the migration noticing that a planted row claims a clean verification it never
# performed. So the volatile key is removed and the substance is compared.
_VOLATILE_SUBKEYS = {
    "verification": ("checked_at",),
}


def _canonical(value, field: str | None = None):
    """Order-independent, type-stable form for comparing nested structures.

    `fields`, `compliance` and `verification` are nested documents that BSON may
    hand back with different key order or with datetimes rather than strings.
    Comparing them raw produces mismatches that are real differences in Python
    and no difference at all in meaning — which would make the collision check
    reject rows it should accept, i.e. block a rerun after a crash.
    """
    volatile = _VOLATILE_SUBKEYS.get(field or "")
    if volatile and isinstance(value, dict):
        value = {k: v for k, v in value.items() if k not in volatile}
    return json.dumps(value, sort_keys=True, default=str)


# Every semantic field of a migrated revision. A pre-existing row must match ALL
# of them: a row with the right id and a different hash is a different artifact
# wearing the right name.
#
# `created_at` and `migration_id` are ABSENT on purpose. They are volatile by
# construction — a rerun after a crash necessarily has a new run id and a new
# timestamp — and requiring them to match would reject the very row the previous
# attempt correctly wrote.
_REVISION_SEMANTIC = (
    "document_id", "version", "status", "template_type", "artifact_key",
    "pdf_sha256", "text_sha256", "body_text", "fields", "extraction_status",
    "extraction_profile", "compliance", "verification", "fence",
    "idempotency_key", "migrated",
)


def _revision_mismatch(existing: dict, planned: dict) -> str | None:
    """The first semantic field on which an existing row differs, or None."""
    for field in _REVISION_SEMANTIC:
        if _canonical(existing.get(field), field) != \
                _canonical(planned.get(field), field):
            return field
    return None


def _document_fields(doc: dict, outcome, revision_id: str,
                     source: SourceSnapshot, migration_id: str, now) -> dict:
    """The V2 fields this outcome puts on the document. Legacy fields intact."""
    fields: dict = {
        "schema_version": 2, "rev_seq": 1, "event_seq": 0, "pending_events": [],
        "migrated_at": now, "migration_id": migration_id,
        "migration_outcome": outcome.code,
        # Overwritten with the real value immediately after the CAS, once the
        # rollback entry exists to hash. Declared here so it is among
        # `added_fields` and therefore removable by a rollback.
        "rollback_token": None,
    }

    if outcome.point_current:
        fields["current_revision_id"] = revision_id
        fields["current_version"] = 1
    else:
        fields["current_revision_id"] = None
        fields["current_version"] = 0

    if outcome.reviewable:
        # WHAT MAKES A MIGRATED SUBMISSION USABLE. Without these three the
        # lawyer sees a Pending row with nothing to preview and no (version,
        # hash) pair for `review` to guard on — work they can neither do nor
        # clear.
        fields["submitted_revision_id"] = revision_id
        fields["submitted_version"] = 1
        fields["submitted_pdf_sha256"] = source.sha256
    else:
        fields["submitted_revision_id"] = None
        fields["submitted_version"] = None
        fields["submitted_pdf_sha256"] = None
        if doc.get("review_status") == "submitted":
            # The submission is being dropped; the assignment goes with it, or
            # the document sits in a queue nobody can act on.
            fields["submitted_to"] = None

    if outcome.cycle_action:
        fields["reviewer_id"] = doc.get("submitted_to")
        fields["reviewed_revision_id"] = revision_id
        fields["reviewed_pdf_sha256"] = source.sha256
        fields["reviewed_version"] = 1
        fields["review_cycles"] = [{
            "lawyer_id": doc.get("submitted_to"),
            "action": outcome.cycle_action,
            "review_status": doc.get("review_status"),
            "revision_id": revision_id,
            "pdf_sha256": source.sha256,
            "version": 1,
            "submitted_at": doc.get("submitted_at"),
            "decided_at": doc.get("reviewed_at"),
            "note": doc.get("lawyer_note") or doc.get("review_note"),
            # NOT a verified binding. The artifact that exists today is the only
            # candidate; nothing in the legacy data proves it is the one that
            # was reviewed.
            "binding": BINDING_LEGACY_UNVERIFIED,
            "logical_event_id": None,
        }]
        # APPROVALS ONLY.
        #
        # `approval_binding` qualifies an approval — it says "this document is
        # approved, and the link between the approval and these bytes is not
        # verified". On a returned or rejected document there is no approval for
        # it to qualify, so the field asserts the existence of something that
        # does not exist. Any reader checking `approval_binding` for presence,
        # rather than for value, would count rejections as approvals.
        #
        # The CYCLE keeps its `binding`: that describes the review event, which
        # did happen, and is unverified for exactly the same reason.
        if outcome.cycle_action == "approve":
            fields["approval_binding"] = BINDING_LEGACY_UNVERIFIED
    else:
        fields["review_cycles"] = []

    if outcome.new_review_status:
        fields["review_status"] = outcome.new_review_status

    return fields


# ── POST-MIGRATION INVARIANTS ────────────────────────────────────────────────

async def inspect_migrated(document_id: str) -> list[str]:
    """Everything wrong with one migrated document. Empty means usable.

    Checks the invariants a V2 document must satisfy for the SURFACES to work,
    not merely for the record to parse — a document can be perfectly
    well-formed and still show a lawyer a row they cannot open.
    """
    doc = await get_documents_col().find_one({"_id": document_id})
    if doc is None:
        return ["document not found"]
    if doc.get("schema_version") != 2:
        return ["not migrated"]

    problems: list[str] = []
    outcome_code = doc.get("migration_outcome")
    if outcome_code not in ALL_OUTCOMES:
        problems.append(f"migration_outcome {outcome_code!r} is not declared")

    if not doc.get("client_id"):
        problems.append("client_id is missing — the document has no owner and "
                        "can appear in nobody's list")

    # THE STATE MUST BE ONE THE SYSTEM CAN ACT ON. A status outside this set is
    # a dead end: no surface renders it and no transition accepts it.
    if doc.get("review_status") not in POST_MIGRATION_STATUSES:
        problems.append(
            f"review_status {doc.get('review_status')!r} is not a state this "
            "system can act on")

    # THE OUTCOME IS THE MIGRATION'S OWN ACCOUNT OF WHAT IT DID, and it is what
    # an owner approved. A document whose status contradicts it means the
    # approval covered a different action from the one that happened.
    declared = _OUTCOME_BY_CODE.get(outcome_code)
    if declared is not None and declared.new_review_status:
        if doc.get("review_status") != declared.new_review_status:
            problems.append(
                f"migration_outcome {outcome_code!r} declares review_status "
                f"{declared.new_review_status!r}, but the document is "
                f"{doc.get('review_status')!r}")

    async def revision(rev_id):
        if not rev_id:
            return None
        return await get_document_revisions_col().find_one({"_id": rev_id})

    def check_artifact(rev, where: str) -> None:
        """The bytes must exist AND be the bytes the row claims.

        A revision row that names an artifact nobody can open is a document that
        validates and cannot be read — the failure that looks like success
        everywhere except in front of the person who needs the file.
        """
        key = rev.get("artifact_key")
        if not key:
            return
        if not store.final_exists(key):
            problems.append(f"{where}: artifact {key} does not exist")
            return
        actual = hashlib.sha256(store.open_final(key)).hexdigest()
        if actual != rev.get("pdf_sha256"):
            problems.append(
                f"{where}: artifact bytes do not match the recorded "
                "pdf_sha256")

    # Every pointer resolves, belongs to this document, and its version and hash
    # agree with the revision it names.
    _PAIRED = {"current_revision_id": ("current_version", None),
               "submitted_revision_id": ("submitted_version",
                                         "submitted_pdf_sha256"),
               "reviewed_revision_id": ("reviewed_version",
                                        "reviewed_pdf_sha256")}
    for field, (version_field, hash_field) in _PAIRED.items():
        rev_id = doc.get(field)
        if not rev_id:
            continue
        rev = await revision(rev_id)
        if rev is None:
            problems.append(f"{field} points at a revision that does not exist")
            continue
        if rev.get("document_id") != document_id:
            problems.append(f"{field} points at another document's revision")
            continue

        check_artifact(rev, field)

        # THE PAIR THE REVIEW GUARD COMPARES. `review` checks the (version,
        # hash) a lawyer decided against the pair on the document; a pointer and
        # a hash describing different revisions makes every decision on this
        # document fail a check with no explicable cause.
        if doc.get(version_field) != rev.get("version"):
            problems.append(
                f"{version_field} is {doc.get(version_field)!r} but "
                f"{field} names version {rev.get('version')!r}")
        if hash_field and doc.get(hash_field) != rev.get("pdf_sha256"):
            problems.append(
                f"{hash_field} does not match the pdf_sha256 of the revision "
                f"named by {field}")

    # A submitted document must be REVIEWABLE: a lawyer, a revision, a version
    # and a hash. Any one missing and the queue row cannot be opened or decided.
    if doc.get("review_status") == "submitted":
        for field in ("submitted_to", "submitted_revision_id",
                      "submitted_version", "submitted_pdf_sha256"):
            if not doc.get(field):
                problems.append(
                    f"submitted document is missing {field} — the assigned "
                    "lawyer cannot act on it")

    # A decided document either carries an attributable cycle or explicitly
    # carries none; it must never carry a cycle with no lawyer.
    for cycle in doc.get("review_cycles") or []:
        if not cycle.get("lawyer_id"):
            problems.append("a review cycle names no lawyer")
        if cycle.get("binding") != BINDING_LEGACY_UNVERIFIED:
            problems.append(
                "a migrated review cycle claims a binding it cannot prove")
        if cycle.get("action") not in set(_DECIDED_ACTION.values()):
            problems.append(
                f"a review cycle records an undeclared action "
                f"{cycle.get('action')!r}")

        cycle_rev_id = cycle.get("revision_id")
        if not cycle_rev_id:
            problems.append("a review cycle names no revision")
            continue
        cycle_rev = await revision(cycle_rev_id)
        if cycle_rev is None:
            problems.append(
                "a review cycle points at a revision that does not exist")
            continue
        if cycle_rev.get("document_id") != document_id:
            problems.append(
                "a review cycle points at another document's revision")
            continue
        # THE LAWYER'S REVISION-SCOPED ACCESS DEPENDS ON THIS PAIR. A historical
        # reviewer may open exactly the revision they decided; if the hash on
        # the cycle names different bytes, they are either locked out of their
        # own decision or shown bytes they never saw.
        if cycle.get("pdf_sha256") != cycle_rev.get("pdf_sha256"):
            problems.append(
                "a review cycle records a pdf_sha256 that does not match the "
                "revision it names")
        if cycle.get("version") != cycle_rev.get("version"):
            problems.append(
                "a review cycle records a version that does not match the "
                "revision it names")

    if doc.get("current_revision_id") and not doc.get("current_version"):
        problems.append("current_revision_id set with no current_version")

    return problems


# ── ROLLBACK ──────────────────────────────────────────────────────────────────

ROLLBACK_SCHEMA_VERSION = 1


class RollbackRejected(RuntimeError):
    """The plan is not usable. Raised BEFORE any document is touched."""


# EVERY FIELD THE MIGRATION OWNS, and therefore the only fields a rollback may
# remove. `review_status` is here because rollback RESTORES it rather than
# unsetting it; the rest are marks migration made and can take back.
#
# WHY AN ALLOWLIST AND NOT THE MANIFEST'S OWN LIST. `added_fields` is data. It
# arrives from a file an operator kept from an earlier run, through whatever
# moved it between machines, and it used to become `$unset` unchallenged — so
# any name in it (`client_id`, `fields`, `_id`) was removable from a production
# document. The CAS guarded WHICH document was touched and left WHAT was done to
# it entirely to the input.
#
# A test asserts this set covers everything `_document_fields` writes: a field
# migration starts writing that rollback cannot remove would survive an undo,
# leaving V2 marks on an otherwise-legacy document — a state nothing else in
# this module can interpret.
ROLLBACK_OWNED_FIELDS = frozenset({
    "schema_version", "rev_seq", "event_seq", "pending_events",
    "migrated_at", "migration_id", "migration_outcome",
    "current_revision_id", "current_version",
    "submitted_revision_id", "submitted_version", "submitted_pdf_sha256",
    "submitted_to",
    "reviewer_id", "reviewed_revision_id", "reviewed_pdf_sha256",
    "reviewed_version", "review_cycles", "approval_binding",
    "review_status", "rollback_token",
})

# Every key an entry must carry. A missing one is not a field to shrug at: each
# is either part of the CAS or part of what gets written back.
_ROLLBACK_ENTRY_KEYS = frozenset({
    "document_id", "migration_id", "applied_revision_id", "applied_at",
    "source_fingerprint", "prev_review_status", "prev_schema_version",
    "added_fields", "post_review_status", "post_current_revision_id",
})


# The entry fields the token covers: everything material to what rollback would
# do. `rollback_token` itself is excluded, obviously.
_ROLLBACK_TOKEN_KEYS = tuple(sorted(_ROLLBACK_ENTRY_KEYS))


def rollback_entry_token(entry: dict) -> str:
    """A hash of one entry, recomputable from the entry alone.

    THE POINT IS WHERE THE OTHER COPY LIVES. This same token is written onto the
    DOCUMENT during migration, where a plan file cannot reach it. Re-signing the
    plan's own fingerprint after an edit is easy — it is computed from the plan;
    matching a token the database already holds is not.

    So a plan whose `prev_review_status` was changed from "returned" to
    "approved" — manufacturing an approval by editing JSON — recomputes to a
    token the document does not carry, and is refused before anything is
    written.
    """
    material = {k: entry.get(k) for k in _ROLLBACK_TOKEN_KEYS}
    material["added_fields"] = sorted(material.get("added_fields") or [])
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


async def _verify_entries_against_documents(plan: dict) -> None:
    """Check every entry against the document it names, before any write.

    Distinguishes TAMPERING from a document that has simply moved on:

      * the document still carries this migration's id but a different token —
        the entry has been edited. That is a rejection: nothing in the plan can
        be trusted, and the run stops before touching anything.
      * the document has advanced, been rolled back already, or vanished — that
        is ordinary, and the per-entry CAS reports it as a skip.
    """
    entries = plan["entries"]
    by_id = {e["document_id"]: e for e in entries}
    ids = list(by_id)

    for start in range(0, len(ids), DRY_RUN_BATCH):
        chunk = ids[start:start + DRY_RUN_BATCH]
        cursor = get_documents_col().find(
            {"_id": {"$in": chunk}},
            {"migration_id": 1, "rollback_token": 1})
        async for doc in cursor:
            entry = by_id[doc["_id"]]
            if doc.get("migration_id") != entry["migration_id"]:
                continue          # moved on; the CAS will skip it
            expected = rollback_entry_token(entry)
            if doc.get("rollback_token") != expected:
                raise RollbackRejected(
                    f"rollback entry for {doc['_id']!r} does not match the "
                    "token recorded on the document at migration time: the "
                    "plan has been altered")


def _rollback_plan(migration_id: str, entries: list[dict]) -> dict:
    """Wrap the entries in the header that makes them verifiable later."""
    plan = {
        "rollback_schema_version": ROLLBACK_SCHEMA_VERSION,
        "migration_id": migration_id,
        "policy_version": MIGRATION_POLICY_VERSION,
        "entries": entries,
    }
    plan["fingerprint"] = rollback_fingerprint(plan)
    return plan


def rollback_fingerprint(plan: dict) -> str:
    """A deterministic hash over the WHOLE plan — every entry, every field.

    Canonical JSON, so key order is not a difference in meaning while a byte of
    content is. Covers the entries AND the header: a plan whose schema version
    or migration id was edited is a different plan.
    """
    material = {
        "rollback_schema_version": plan.get("rollback_schema_version"),
        "migration_id": plan.get("migration_id"),
        "policy_version": plan.get("policy_version"),
        "entries": plan.get("entries", []),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _validate_rollback_plan(plan: dict) -> None:
    """Everything that must hold before the FIRST document is touched.

    All of it up front, deliberately. Validating entry-by-entry as the run
    proceeds would leave an estate that is neither migrated nor rolled back,
    with nothing recording where it stopped — and rollback runs when something
    has already gone wrong, which is the worst moment to invent a third state.
    """
    if not isinstance(plan, dict):
        raise RollbackRejected(
            "rollback expects the plan object returned by apply(), not a bare "
            "list of entries")

    if plan.get("rollback_schema_version") != ROLLBACK_SCHEMA_VERSION:
        raise RollbackRejected(
            f"rollback_schema_version {plan.get('rollback_schema_version')!r} "
            f"is not {ROLLBACK_SCHEMA_VERSION}: this plan was written by a "
            "different build and its entries may not mean what this one thinks")

    expected = rollback_fingerprint(plan)
    if plan.get("fingerprint") != expected:
        raise RollbackRejected(
            "rollback plan fingerprint mismatch: the plan has been altered "
            "since it was produced")

    entries = plan.get("entries")
    if not isinstance(entries, list):
        raise RollbackRejected("rollback plan has no entries list")

    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise RollbackRejected("a rollback entry is not an object")

        missing = _ROLLBACK_ENTRY_KEYS - set(entry)
        if missing:
            raise RollbackRejected(
                f"rollback entry for {entry.get('document_id')!r} is missing "
                f"{sorted(missing)}")

        doc_id = entry["document_id"]
        if doc_id in seen:
            # Two entries for one document cannot both be right: the second
            # runs against a document the first already changed, fails its CAS,
            # and is reported as a skip — a silent, confusing half-result.
            raise RollbackRejected(
                f"duplicate rollback entry for document {doc_id!r}")
        seen.add(doc_id)

        if entry["migration_id"] != plan["migration_id"]:
            raise RollbackRejected(
                f"rollback entry for {doc_id!r} names a different migration")

        unknown = set(entry["added_fields"]) - ROLLBACK_OWNED_FIELDS
        if unknown:
            raise RollbackRejected(
                f"rollback entry for {doc_id!r} would unset "
                f"{sorted(unknown)}, which the migration does not own")

        if entry["prev_review_status"] is not None and \
                not is_supported_status(entry["prev_review_status"]):
            raise RollbackRejected(
                f"rollback entry for {doc_id!r} would restore review_status "
                f"{entry['prev_review_status']!r}, which is not a supported "
                "legacy status")


async def rollback(rollback_manifest: dict) -> dict:
    """Return migrated documents to legacy shape. Preserves revisions + events.

    Restores the previous review_status (precondition-checked against the applied
    revision) and unsets the V2 pointer fields this migration added. Revision
    rows and review_events are NEVER dropped — they are audit records; a rolled
    back document simply stops pointing at them.
    """
    _validate_rollback_plan(rollback_manifest)
    await _verify_entries_against_documents(rollback_manifest)
    entries = rollback_manifest["entries"]

    restored = 0
    skipped_documents: list[dict] = []

    for entry in entries:
        # Intersected with the allowlist as well as validated against it. The
        # validation above already refused anything outside it; this is the
        # belt to that braces, so no future edit can route an unchecked name
        # into a `$unset`.
        unset = {f: "" for f in entry["added_fields"]
                 if f in ROLLBACK_OWNED_FIELDS and f != "review_status"}
        update: dict = {"$unset": unset}
        # Restore the prior review_status if the migration changed it.
        if "review_status" in entry["added_fields"]:
            update["$set"] = {"review_status": entry["prev_review_status"]}

        # ONE GUARDED WRITE. No read first: a read-then-write cannot see a
        # change that lands between the two, and this function's whole job is to
        # remove fields.
        result = await get_documents_col().update_one(
            _rollback_filter(entry), update)
        if result.matched_count:
            restored += 1
            continue

        skipped_documents.append({
            "document_id": entry["document_id"],
            "reason": await _rollback_refusal(entry),
        })
        logger.warning("rollback_skip document=%s reason=%s",
                       entry["document_id"], skipped_documents[-1]["reason"])

    return {
        "migration_id": rollback_manifest["migration_id"],
        "restored": restored,
        "skipped": len(skipped_documents),
        # WHICH ones, and why. "3 skipped" is not something an operator
        # mid-incident can act on, and mid-incident is the only time this runs.
        "skipped_documents": skipped_documents,
        "planned": len(entries),
        "reconciles": restored + len(skipped_documents) == len(entries),
    }


def _rollback_filter(entry: dict) -> dict:
    """The exact post-migration state this undo is allowed to act on.

    WHAT EACH CLAUSE STOPS, because every one of them is an ordinary thing that
    happens while a migration is being investigated:

      migration_id      — a document migrated by a DIFFERENT run. Replaying a
                          stale rollback list would strip fields a later, still
                          wanted migration wrote, and report success.
      schema_version    — a document already rolled back, or never migrated.
      current_revision_id / review_status
                        — the document has moved on. The previous guard accepted
                          `current_revision_id in (applied, None)`, and that
                          `None` was actively wrong: None does not mean
                          "unchanged", it means somebody unset it.
      event_seq         — A REVIEW HAS HAPPENED SINCE. This is the one that
                          matters most. `review_cycles` is among the fields
                          rollback unsets, so undoing a migration on a document
                          a lawyer has since acted on deletes a decision
                          somebody really made, on a legal document, leaving
                          nothing to say it existed. Migration writes
                          `event_seq: 0`; any transition raises it.
    """
    return {
        "_id": entry["document_id"],
        "migration_id": entry["migration_id"],
        "schema_version": 2,
        "current_revision_id": entry.get("post_current_revision_id"),
        "review_status": entry.get("post_review_status"),
        "event_seq": 0,
    }


async def _rollback_refusal(entry: dict) -> str:
    """Why the guard did not match. Diagnostic only — read after the fact."""
    doc = await get_documents_col().find_one({"_id": entry["document_id"]})
    if doc is None:
        return "document_gone"
    if doc.get("schema_version") != 2:
        return "not_migrated"
    if doc.get("migration_id") != entry["migration_id"]:
        return "migrated_by_another_run"
    if doc.get("event_seq"):
        return "reviewed_since_migration"
    if doc.get("current_revision_id") != entry.get("post_current_revision_id"):
        return "regenerated_since_migration"
    if doc.get("review_status") != entry.get("post_review_status"):
        return "status_changed_since_migration"
    return "changed_since_migration"
