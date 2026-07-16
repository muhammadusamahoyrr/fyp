"""Overseas Desk — Power-of-Attorney manager for the Pakistani diaspora.

Generates a POA (Special/General), keeps a registry with expiry alerts and
one-click revocation, and tracks the attestation lifecycle. POA fraud is a
national crisis, so several safeguards are baked in (see plan):
  1. every PDF carries a non-removable DRAFT-FOR-LEGAL-REVIEW banner,
  2. the PDF's SHA256 is stored for tamper-evidence,
  3. attorney acknowledgement is tracked,
  4. property-disposition powers are barred from a General POA,
  5. an execution-status workflow (drafted → … → registered) is tracked.
"""
import asyncio
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.constants import (
    NotificationType,
    POAAckStatus,
    POAExecutionStatus,
    POAStatus,
    PROPERTY_DISPOSITION_POWERS,
)
from app.core.exceptions import AppValidationError, ForbiddenError, NotFoundError
from app.core.security import encrypt_cnic, mask_cnic
from app.db.collections import get_documents_col, get_poas_col
from app.repositories.user_repo import UserRepository
from app.services import document_service

logger = logging.getLogger(__name__)
user_repo = UserRepository()

_EXPIRY_WARN_DAYS = 30

# Power code → clause text for the PDF.
POWER_LABELS = {
    "manage":   "To manage, administer and look after the property/matter described above.",
    "rent":     "To let out or rent the property and to receive and give receipt for the rent.",
    "collect":  "To receive any money due and to give valid receipts and discharges.",
    "litigate": "To represent me before any court, authority or office, and to sign, verify and file pleadings, applications and appeals.",
    "bank":     "To operate bank accounts connected with the matter and to sign related instruments.",
    "register": "To sign, execute and present documents for registration before the Sub-Registrar.",
    "tax":      "To deal with tax, utility and municipal authorities in respect of the property/matter.",
    "sell":     "To sell, convey and transfer the property and to receive the sale consideration.",
    "transfer": "To transfer, alienate or convey title to the property.",
    "gift":     "To gift or make a gratuitous transfer of the property.",
    "mortgage": "To mortgage, pledge or create a charge over the property.",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _sha256(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except Exception:
        logger.exception("POA sha256 failed for %s", path)
        return None


async def _notify(user_id, ntype, title, body, payload):
    try:
        from app.services import notification_service
        await notification_service.create_notification(user_id, ntype, title, body, payload=payload)
    except Exception:
        logger.exception("POA notification failed for %s", user_id)


def _public(doc: dict) -> dict:
    # Never return raw encrypted CNIC blobs to the client — only the masked form.
    out = {k: v for k, v in doc.items() if k != "_id" and not k.endswith("_encrypted")}
    out["id"] = doc["_id"]
    return out


def _cnic_at_rest(cnic: str) -> dict:
    """Encrypted blob (for storage) + masked value (for display). Empty → both empty."""
    cnic = (cnic or "").strip()
    if not cnic:
        return {"masked": "", "encrypted": None}
    return {"masked": mask_cnic(cnic), "encrypted": encrypt_cnic(cnic)}


async def create_poa(principal_id: str, data: dict) -> dict:
    poa_type = (data.get("poa_type") or "special").lower()
    if poa_type not in ("special", "general"):
        raise AppValidationError("poa_type must be 'special' or 'general'")
    if not (data.get("attorney_name") or "").strip():
        raise AppValidationError("Attorney (agent) name is required")

    powers = [p for p in (data.get("powers") or []) if p in POWER_LABELS]
    if not powers:
        raise AppValidationError("Select at least one power to grant")

    subject = (data.get("subject") or "").strip()
    if poa_type == "special" and not subject:
        raise AppValidationError("A Special POA needs the specific property/matter it covers")

    # Safeguard 4: property disposition needs a Special (registered) POA.
    if poa_type == "general" and set(powers) & PROPERTY_DISPOSITION_POWERS:
        raise AppValidationError(
            "Selling, transferring, gifting or mortgaging property cannot be granted through a General "
            "Power of Attorney. Use a Special Power of Attorney for the specific property (and register it)."
        )

    principal = await user_repo.find_by_id(principal_id)
    power_clauses = [POWER_LABELS[p] for p in powers]

    # CNIC is sensitive: the plaintext is used only to render the PDF; what gets
    # persisted is an encrypted blob + a masked display value (see below).
    principal_cnic = (data.get("principal_cnic") or "").strip()
    attorney_cnic = (data.get("attorney_cnic") or "").strip()

    # The verify token is generated BEFORE the PDF so its QR/verify URL can be
    # rendered into the document. The SHA-256 is then taken over the QR-bearing PDF,
    # so the tamper-hash and the printed QR stay consistent.
    verify_token = secrets.token_urlsafe(16)
    verify_url = _verify_url(verify_token)

    fields = {
        "poa_type":             poa_type,
        "principal_name":       data.get("principal_name") or (principal or {}).get("full_name", ""),
        "principal_cnic":       principal_cnic,
        "principal_address":    data.get("principal_address", ""),
        "attorney_name":        data.get("attorney_name", ""),
        "attorney_cnic":        attorney_cnic,
        "attorney_relation":    data.get("attorney_relation", ""),
        "attorney_address":     data.get("attorney_address", ""),
        "subject":              subject,
        "powers":               power_clauses,
        "restrictions":         data.get("restrictions", ""),
        "country_of_execution": data.get("country_of_execution", ""),
        "issue_date":           data.get("issue_date", ""),
        "expiry_date":          data.get("expiry_date", ""),
        "verify_url":           verify_url,
    }
    document = await document_service.generate_standalone(principal_id, "power_of_attorney", fields)
    doc_sha = _sha256(document.get("file_path"))  # safeguard 2

    # The PDF has rendered from the plaintext CNIC; redact it from the persisted
    # document fields so no plaintext CNIC remains at rest (the CNIC survives
    # only inside the access-controlled PDF).
    p_cnic = _cnic_at_rest(principal_cnic)
    a_cnic = _cnic_at_rest(attorney_cnic)
    await get_documents_col().update_one(
        {"_id": document["_id"]},
        {"$set": {"fields.principal_cnic": p_cnic["masked"],
                  "fields.attorney_cnic": a_cnic["masked"]}},
    )

    expiry = _parse_date(data.get("expiry_date"))
    now = _now()
    rec = {
        "_id":                   secrets.token_urlsafe(16),
        "principal_id":          principal_id,
        "principal_snapshot":    {"id": principal_id, "name": (principal or {}).get("full_name", "")},
        "attorney_name":         fields["attorney_name"],
        "principal_cnic_masked":    p_cnic["masked"],
        "principal_cnic_encrypted": p_cnic["encrypted"],
        "attorney_cnic_masked":     a_cnic["masked"],
        "attorney_cnic_encrypted":  a_cnic["encrypted"],
        "attorney_relation":     fields["attorney_relation"],
        "poa_type":              poa_type,
        "subject":               subject,
        "powers":                powers,
        "restrictions":          fields["restrictions"],
        "country_of_execution":  fields["country_of_execution"],
        "issue_date":            fields["issue_date"] or now.strftime("%d %B %Y"),
        "expiry_date":           expiry,
        "status":                POAStatus.ACTIVE.value,
        "execution_status":      POAExecutionStatus.DRAFTED.value,
        "attorney_ack_status":   POAAckStatus.PENDING.value,
        "attorney_ack_at":       None,
        "document_id":           document["_id"],
        "document_sha256":       doc_sha,
        "revocation_document_id": None,
        "revocation_sha256":     None,
        "revoked_at":            None,
        # Capability token for the public point-of-use verify link/QR. A holder of
        # the POA (buyer's lawyer, sub-registrar) can check live status + scope,
        # closing the "a revoked POA keeps working because nobody knows" gap.
        "verify_token":          verify_token,
        "opppa_status":          "not_registered",   # OPPPA property-registration tracker
        "expiry_notified":       False,
        "created_at":            now,
        "updated_at":            now,
    }
    await get_poas_col().insert_one(rec)
    return _public(rec)


def _parse_date(raw):
    """Accept ISO date/datetime or return None."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


async def _owned(poa_id: str, principal_id: str) -> dict:
    poa = await get_poas_col().find_one({"_id": poa_id})
    if not poa:
        raise NotFoundError("Power of Attorney")
    if poa["principal_id"] != principal_id:
        raise ForbiddenError("This Power of Attorney is not yours")
    return poa


def _verify_url(token: str) -> str:
    from app.core.config import settings
    base = (settings.frontend_url or "").rstrip("/")
    return f"{base}/verify/{token}" if token else ""


def verify_qr_svg(token: str) -> str:
    """Public QR (SVG) for a POA's verify link, for on-screen display. reportlab
    renders it — no QR dependency, no raster backend. Encodes the URL only, so it
    needs no DB lookup."""
    from reportlab.graphics import renderSVG

    from app.services.pdf_generator import _qr_flowable
    return renderSVG.drawToString(_qr_flowable(_verify_url(token), size_cm=3.4))


def _decorate(poa: dict) -> dict:
    out = _public(poa)
    exp = _aware(poa.get("expiry_date"))
    out["expiring_soon"] = bool(
        poa["status"] == POAStatus.ACTIVE.value and exp and _now() <= exp <= _now() + timedelta(days=_EXPIRY_WARN_DAYS)
    )
    # The owner prints/shares this so a counterparty can check the POA at point of use.
    out["verify_url"] = _verify_url(poa.get("verify_token", ""))
    return out


def _live_status(poa: dict) -> str:
    """Status as it is RIGHT NOW — an expiry that has passed reads as expired even
    if the nightly sweep has not run yet. Point-of-use verification must never show
    a lapsed POA as active."""
    status = poa.get("status")
    if status == POAStatus.ACTIVE.value:
        exp = _aware(poa.get("expiry_date"))
        if exp and _now() > exp:
            return POAStatus.EXPIRED.value
    return status


async def verify_by_token(token: str) -> dict:
    """PUBLIC point-of-use check. No authentication: the token IS the capability,
    printed on the POA a counterparty is holding.

    Returns only what a verifier needs to confirm authenticity, status and scope —
    names and the property (which are already on the paper in their hand), never the
    CNIC. This is what closes the 'a revoked POA keeps working because nobody at the
    point of use knows it is dead' gap.
    """
    token = (token or "").strip()
    if not token:
        return {"found": False, "message": "No verification code supplied."}

    poa = await get_poas_col().find_one({"verify_token": token})
    if not poa:
        # Deliberately generic — do not confirm or deny a guessed token beyond this.
        return {"found": False, "message": "No Power of Attorney matches this verification code."}

    status = _live_status(poa)
    return {
        "found": True,
        "status": status,                       # active | revoked | expired
        "is_active": status == POAStatus.ACTIVE.value,
        "poa_type": poa.get("poa_type"),
        "principal_name": poa.get("principal_snapshot", {}).get("name", ""),
        "attorney_name": poa.get("attorney_name", ""),
        "attorney_relation": poa.get("attorney_relation", ""),
        "subject": poa.get("subject", ""),      # the exact authorised property/matter
        "powers": [POWER_LABELS.get(p, p) for p in poa.get("powers", [])],
        "issue_date": poa.get("issue_date", ""),
        "expiry_date": poa.get("expiry_date"),
        "revoked_at": poa.get("revoked_at"),
        "document_sha256": poa.get("document_sha256"),   # tamper-check the paper against this
        "verified_note": (
            "This confirms the POA on record and its current status. Always also inspect "
            "the original stamped/attested document and, for property, the Sub-Registrar entry."
        ),
    }


async def list_poas(principal_id: str) -> list[dict]:
    out = []
    async for poa in get_poas_col().find({"principal_id": principal_id}).sort("created_at", -1):
        # lazy expire
        exp = _aware(poa.get("expiry_date"))
        if poa["status"] == POAStatus.ACTIVE.value and exp and _now() > exp:
            await get_poas_col().update_one({"_id": poa["_id"]}, {"$set": {"status": POAStatus.EXPIRED.value}})
            poa["status"] = POAStatus.EXPIRED.value
        out.append(_decorate(poa))
    return out


async def get_poa(poa_id: str, principal_id: str) -> dict:
    return _decorate(await _owned(poa_id, principal_id))


async def set_execution_status(poa_id: str, principal_id: str, status: str) -> dict:
    if status not in {s.value for s in POAExecutionStatus}:
        raise AppValidationError("Invalid execution status")
    await _owned(poa_id, principal_id)
    await get_poas_col().update_one(
        {"_id": poa_id}, {"$set": {"execution_status": status, "updated_at": _now()}}
    )
    return _decorate(await _owned(poa_id, principal_id))


async def acknowledge(poa_id: str, principal_id: str) -> dict:
    await _owned(poa_id, principal_id)
    await get_poas_col().update_one(
        {"_id": poa_id},
        {"$set": {"attorney_ack_status": POAAckStatus.ACKNOWLEDGED.value,
                  "attorney_ack_at": _now(), "updated_at": _now()}},
    )
    return _decorate(await _owned(poa_id, principal_id))


async def revoke_poa(poa_id: str, principal_id: str) -> dict:
    poa = await _owned(poa_id, principal_id)
    if poa["status"] == POAStatus.REVOKED.value:
        return _decorate(poa)  # idempotent

    fields = {
        "principal_name": poa["principal_snapshot"]["name"],
        "attorney_name":  poa["attorney_name"],
        "subject":        poa.get("subject", ""),
        "original_date":  poa.get("issue_date", ""),
        # Same verify link as the original POA — scanning the deed shows REVOKED.
        "verify_url":     _verify_url(poa.get("verify_token", "")),
    }
    rev_doc = await document_service.generate_standalone(principal_id, "poa_revocation", fields)
    rev_sha = _sha256(rev_doc.get("file_path"))

    await get_poas_col().update_one(
        {"_id": poa_id},
        {"$set": {
            "status": POAStatus.REVOKED.value,
            "revocation_document_id": rev_doc["_id"],
            "revocation_sha256": rev_sha,
            "revoked_at": _now(),
            "updated_at": _now(),
        }},
    )
    await _notify(
        principal_id, NotificationType.POA_EXPIRING,
        "Power of Attorney revoked",
        f"Your Power of Attorney to {poa['attorney_name']} has been revoked. "
        f"Serve the revocation deed on the attorney and any registrar/bank that holds the original.",
        {"poa_id": poa_id, "revocation_document_id": rev_doc["_id"]},
    )
    return _decorate(await _owned(poa_id, principal_id))


# Markers that indicate a document has been through the attestation/legalisation
# chain. Presence is a signal, not proof — a human still inspects the original.
_ATTEST_MARKERS = {
    "apostille":        ["apostille"],
    "notarisation":     ["notary", "notarised", "notarized", "notary public"],
    "mission_attestation": ["consulate", "embassy", "high commission", "consular",
                            "pakistan mission"],
    "mofa_attestation": ["ministry of foreign affairs", "mofa"],
    "registration":     ["sub-registrar", "sub registrar", "registered", "registration no"],
}


def _analyse_attested_text(text: str, poa: dict) -> dict:
    """Pure: does an uploaded, supposedly-attested document look like THIS POA, and
    which attestation markers does it carry? Testable without any file I/O.

    Deliberately conservative — it reports what it can and cannot confirm, and never
    declares a document 'valid'. It answers 'did they attest the right thing', which
    the user then confirms against the physical original.
    """
    haystack = (text or "").lower()

    markers = [name for name, kws in _ATTEST_MARKERS.items()
               if any(kw in haystack for kw in kws)]

    principal = (poa.get("principal_snapshot", {}).get("name") or "").strip()
    attorney = (poa.get("attorney_name") or "").strip()
    subject = (poa.get("subject") or "").strip()

    def _present(value: str) -> bool:
        return bool(value) and value.lower() in haystack

    principal_match = _present(principal)
    attorney_match = _present(attorney)
    # Subject match is looser — match on the distinctive words, not the whole phrase.
    subject_words = [w for w in subject.lower().split() if len(w) >= 4]
    subject_match = bool(subject_words) and sum(w in haystack for w in subject_words) >= max(1, len(subject_words) // 2)

    concerns: list[str] = []
    if not markers:
        concerns.append("No attestation or apostille markers were found — this may be an "
                        "un-attested draft, or a scan with no readable text layer.")
    if principal and not principal_match:
        concerns.append("The principal's name on record was not found in the uploaded text.")
    if attorney and not attorney_match:
        concerns.append("The attorney's name on record was not found in the uploaded text.")
    if subject and not subject_match:
        concerns.append("The property/matter this POA covers was not clearly found — check the "
                        "uploaded document is for the right property.")

    matches_record = principal_match and attorney_match and (subject_match or not subject)
    return {
        "attestation_markers": markers,
        "principal_name_match": principal_match,
        "attorney_name_match": attorney_match,
        "subject_match": subject_match,
        "matches_record": matches_record,
        "has_no_text_layer": not haystack.strip(),
        "concerns": concerns,
        "disclaimer": "Automated indicators only — this does NOT confirm the stamps are genuine. "
                      "Inspect the original attested document, and verify any apostille on the "
                      "issuing authority's own checker.",
    }


async def verify_attested_upload(poa_id: str, principal_id: str, file) -> dict:
    """Owner uploads the returned, attested POA; report the attestation markers and
    whether it matches the POA on record. Reuses the document-read text extraction."""
    import tempfile
    from pathlib import Path

    from app.ai.tools.document_tools import _extract_text_sync

    poa = await _owned(poa_id, principal_id)

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise AppValidationError("File too large — maximum size is 10 MB")

    suffix = Path(file.filename or "upload.pdf").suffix.lower() or ".pdf"
    tmp = Path(tempfile.gettempdir()) / f"attest_{secrets.token_hex(8)}{suffix}"
    try:
        tmp.write_bytes(content)
        try:
            text = await asyncio.to_thread(_extract_text_sync, tmp)
        except ValueError as exc:
            raise AppValidationError(str(exc))
        except Exception:
            logger.exception("attested-doc extraction failed for poa %s", poa_id)
            raise AppValidationError("Could not read the uploaded document.")
    finally:
        tmp.unlink(missing_ok=True)

    report = _analyse_attested_text(text, poa)
    report["poa_id"] = poa_id
    return report


async def set_opppa_status(poa_id: str, principal_id: str, status: str) -> dict:
    """Record where the property behind this POA sits in OPPPA registration."""
    from app.services import opppa

    if not opppa.is_valid_status(status):
        raise AppValidationError(f"Status must be one of: {', '.join(sorted(opppa.STATUSES))}")
    await _owned(poa_id, principal_id)
    await get_poas_col().update_one(
        {"_id": poa_id}, {"$set": {"opppa_status": status, "updated_at": _now()}},
    )
    return _decorate(await _owned(poa_id, principal_id))


async def check_expiring() -> dict:
    """Scheduler sweep: warn on POAs expiring within the window; expire past-due ones."""
    col = get_poas_col()
    notified = expired = 0
    async for poa in col.find({"status": POAStatus.ACTIVE.value, "expiry_date": {"$ne": None}}):
        exp = _aware(poa.get("expiry_date"))
        if not exp:
            continue
        if _now() > exp:
            await col.update_one({"_id": poa["_id"]}, {"$set": {"status": POAStatus.EXPIRED.value}})
            expired += 1
        elif exp <= _now() + timedelta(days=_EXPIRY_WARN_DAYS) and not poa.get("expiry_notified"):
            await col.update_one({"_id": poa["_id"]}, {"$set": {"expiry_notified": True}})
            await _notify(
                poa["principal_id"], NotificationType.POA_EXPIRING,
                "Power of Attorney expiring soon",
                f"Your Power of Attorney to {poa['attorney_name']} expires on "
                f"{exp:%d %b %Y}. Renew or revoke it before then.",
                {"poa_id": poa["_id"]},
            )
            notified += 1
    return {"notified": notified, "expired": expired}
