"""Per-template extraction PROFILE — determined by MEASUREMENT, never by name.

The citation verifier reads text recovered from a generated PDF. Some templates
render right-to-left Urdu, whose extracted glyphs cannot be matched against an
English-keyed statute corpus; for those, verification must record `ran:false`
rather than a misleading zero-citation "pass". But the classification of WHICH
templates are Urdu is an empirical fact about their rendered output, not a guess
from the template's name.

Measured 2026-09-03 on a filled sample (backend/venv, pypdf), Arabic-script vs
Latin character counts in the extracted text:

    wasiyyat_nama    1170 chars, 872 Latin, 0 Arabic   -> latin  (English will)
    urdu_pleading      85 chars,   0 Latin, 66 Arabic  -> urdu
    (18 other drafting builders)          latin-dominant -> latin

The naive assumption "wasiyyat is Islamic, therefore Urdu" is WRONG and would
have silently disabled citation checking for an English document that cites
statute. Hence this map is data, and `measure_profile()` recomputes it from real
output so adding a template forces a measurement, not a guess.

DORMANT until DOCUMENTS_V2; consumed by the generation pipeline in a later stage.
"""
from __future__ import annotations

import re

# script → profile. A profile of "urdu" means: PDF-byte hashing and preview
# still work, but text extraction is not verifiable against this corpus, so the
# pipeline records extraction_status="unsupported" and verification.ran=false.
PROFILE_LATIN = "latin"
PROFILE_URDU = "urdu"
PROFILE_MIXED = "mixed"
PROFILE_NONE = "none"

# The measured classification. Only templates whose rendered output is
# Arabic-script-dominant are listed; everything else defaults to latin.
_MEASURED: dict[str, str] = {
    "urdu_pleading": PROFILE_URDU,
    # wasiyyat_nama is deliberately NOT here: measured latin (0 Arabic-script).
}

_ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_LATIN = re.compile(r"[A-Za-z]")


def profile_for(template_type: str) -> str:
    """The recorded profile for a template. Defaults to latin."""
    return _MEASURED.get(template_type, PROFILE_LATIN)


def verifiable(template_type: str) -> bool:
    """Can extracted text from this template be checked against the corpus?"""
    return profile_for(template_type) in (PROFILE_LATIN, PROFILE_MIXED)


def measure_profile(text: str) -> str:
    """Classify a profile from actual extracted text (the fixture's method).

    A test drives every generator through this so the static map above can never
    silently drift from reality.
    """
    arabic = len(_ARABIC.findall(text or ""))
    latin = len(_LATIN.findall(text or ""))
    if arabic == 0 and latin == 0:
        return PROFILE_NONE
    if arabic > latin:
        return PROFILE_URDU
    if arabic > 0:
        return PROFILE_MIXED
    return PROFILE_LATIN
