"""PII scrubbing for anything that leaves the request or is written to storage.

Extracted from finalizer_node so the audit trail can reuse exactly the same
patterns. A provenance record that stored a raw CNIC would turn an
accountability feature into a data-protection liability, and it must never
drift from what the user-facing answer already redacts.
"""
from __future__ import annotations

import re

# Pakistani CNIC: 12345-1234567-1
_CNIC_RE = re.compile(r'\b\d{5}-\d{7}-\d\b')
# Same shape in Urdu/Extended Arabic-Indic digits (U+0660-U+0669, U+06F0-U+06F9)
_CNIC_URDU_RE = re.compile(r'[٠-٩۰-۹]{5}-[٠-٩۰-۹]{7}-[٠-٩۰-۹]')
# Pakistani mobile/landline, with or without country code
_PHONE_RE = re.compile(r'\b(\+92|0092|0)[\s\-]?\d{3}[\s\-]?\d{7}\b')

_CNIC_MASK  = 'XXXXX-XXXXXXX-X'
_PHONE_MASK = '[PHONE REDACTED]'


def scrub_pii(text: str) -> str:
    """Mask CNICs (Latin and Urdu digits) and phone numbers."""
    if not text:
        return text
    text = _CNIC_RE.sub(_CNIC_MASK, text)
    text = _CNIC_URDU_RE.sub(_CNIC_MASK, text)
    text = _PHONE_RE.sub(_PHONE_MASK, text)
    return text
