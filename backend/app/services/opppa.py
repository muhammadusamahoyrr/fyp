"""OPPPA registration guidance.

The Protection of Overseas Pakistanis' Property Act 2024 creates the Overseas
Pakistanis' Property Protection Authority (OPPPA) with an online registration and
verification database. Registering a property there guards against double-ownership
and fraudulent transfer — a cheap, protective step people skip because they don't
know it exists or how to do it. This module is the guided-flow content + the status
vocabulary; the actual portal is external and still stabilising, so everything is
dated and flagged, like the other jurisdiction tables.
"""
from __future__ import annotations

EFFECTIVE_AS_OF = "2026-07"

# Self-reported registration status for a property (POA subject).
NOT_REGISTERED = "not_registered"
IN_PROGRESS = "in_progress"
REGISTERED = "registered"
STATUSES = {NOT_REGISTERED, IN_PROGRESS, REGISTERED}


def is_valid_status(status: str) -> bool:
    return status in STATUSES


def guidance() -> dict:
    """What OPPPA registration is, why it matters, and the steps — dated + verify."""
    return {
        "authority": "Overseas Pakistanis' Property Protection Authority (OPPPA)",
        "why": "Registering your property in OPPPA's database creates an authoritative record "
               "tied to your identity, which guards against double-ownership claims and "
               "fraudulent transfers while you are abroad.",
        "steps": [
            "Gather the property's title documents (fard / registry) and your CNIC/NICOP.",
            "Create an account on the OPPPA online registration portal.",
            "Register the property against your identity and upload the title proof.",
            "Record your reference number and keep the confirmation.",
            "Re-check the record periodically for any change you did not authorise.",
        ],
        "statuses": {
            NOT_REGISTERED: "Not yet registered with OPPPA.",
            IN_PROGRESS: "Registration submitted, awaiting confirmation.",
            REGISTERED: "Registered — keep your reference number safe.",
        },
        "legal_basis": "Protection of Overseas Pakistanis' Property Act, 2024.",
        "effective_as_of": EFFECTIVE_AS_OF,
        "verify": "OPPPA and its portal are new and still stabilising — confirm the current "
                  "registration route and requirements before relying on this.",
    }
