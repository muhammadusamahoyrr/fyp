"""Attestation-path resolver for POAs executed abroad (Overseas Desk).

Pakistan acceded to the Hague Apostille Convention (in force 9 March 2023),
made permanent by the Apostille Act 2024. For a document flowing between two
member states in good standing, a SINGLE apostille replaces the old
Notary -> Pakistan Mission -> MOFA legalisation chain. But two things stop this
from being a blanket "use apostille everywhere":

  1. OBJECTIONS ARE BILATERAL AND CANNOT BE INFERRED FROM MEMBERSHIP.
     Several states objected to Pakistan's accession under Art. 12, so the
     Convention does NOT operate between them and Pakistan even though BOTH are
     members. For those, the legacy consular chain is still the correct answer.
     India is a separate case — not an Art. 12 objection but a political
     non-recognition — with the same practical result. This is why the block
     list is a SEPARATE lookup, not a function of `hague_member`.

  2. DIRECTION DECIDES WHICH AUTHORITY ISSUES THE APOSTILLE.
     For a POA the document ORIGINATES ABROAD and is USED IN PAKISTAN (inbound).
     The apostille on an abroad-executed document is issued by THAT COUNTRY's
     designated authority (the UK's, the UAE's, ...), NOT by MOFA. MOFA is the
     Pakistan-side authority — it only appears in the legacy chain's attestation
     step, or when a Pakistani-origin document goes outbound. Hence
     `apostille_authority` is per country and is never MOFA.

SOURCE OF TRUTH — reconcile before relying on any path in production:
  HCCH status table for the Apostille Convention (Convention No. 12), which lists
  members, accession/in-force dates AND the Art. 12 objections:
    https://www.hcch.net/en/instruments/conventions/status-table/?cid=41
  The lists below are a dated SEED, not verified live state. Membership dates and
  objections change — objections can be withdrawn and new ones filed — so this
  file carries the same `verify` duty as the court-fee rate table.
"""
from __future__ import annotations

# Last time COUNTRIES / PK_APOSTILLE_BLOCKED were reconciled against HCCH.
EFFECTIVE_AS_OF = "2026-07"

_HCCH_STATUS_URL = "https://www.hcch.net/en/instruments/conventions/status-table/?cid=41"

# Pakistan-side authority. Used for the legacy chain's MOFA step and for OUTBOUND
# Pakistani documents — never as the issuer for an abroad-executed POA.
PAKISTAN_MOFA = (
    "Ministry of Foreign Affairs (MOFA), Pakistan — the competent authority under "
    "the Apostille Act 2024 (liaison offices: Islamabad, Karachi, Lahore, Quetta, "
    "Peshawar, Gujrat)"
)

# Per-country record.
#   hague_member         — is the country an Apostille Convention member?
#   apostille_authority  — the body IN THAT COUNTRY that issues an apostille on a
#                          document originating there (the inbound direction for a
#                          POA). NOT MOFA.
#   pakistan_mission     — Pakistan's embassy/consulate there, for the legacy chain.
#   note                 — country-specific caveat (recently acceded, etc.).
COUNTRIES: dict[str, dict] = {
    "GB": {
        "name": "United Kingdom",
        "hague_member": True,
        "apostille_authority": "The FCDO Legalisation Office (UK)",
        "pakistan_mission": "Pakistan High Commission, London (or consulates in Bradford, Birmingham, Manchester, Glasgow)",
    },
    "US": {
        "name": "United States",
        "hague_member": True,
        "apostille_authority": "the Secretary of State of the US state where the document was notarised (or the US Department of State for federal documents)",
        "pakistan_mission": "Embassy of Pakistan, Washington DC (or consulates in New York, Los Angeles, Houston, Chicago)",
    },
    "AU": {
        "name": "Australia",
        "hague_member": True,
        "apostille_authority": "the Department of Foreign Affairs and Trade (DFAT), Australia",
        "pakistan_mission": "High Commission for Pakistan, Canberra (or Consulate General, Sydney)",
    },
    "CA": {
        "name": "Canada",
        "hague_member": True,
        "apostille_authority": "Global Affairs Canada, or the designated provincial authority (e.g. Ontario, Quebec, BC, Alberta)",
        "pakistan_mission": "High Commission for Pakistan, Ottawa (or consulates in Toronto, Montreal, Vancouver)",
        "note": "Canada acceded only recently (in force Jan 2024) — confirm the issuing authority for your province.",
    },
    "AE": {
        "name": "UAE",
        "hague_member": True,
        "apostille_authority": "the UAE Ministry of Foreign Affairs (MoFAIC)",
        "pakistan_mission": "Embassy of Pakistan, Abu Dhabi (or Consulate General, Dubai)",
        "note": "UAE acceded recently — confirm the apostille is in force and being accepted by the receiving office in Pakistan.",
    },
    "SA": {
        "name": "Saudi Arabia",
        "hague_member": True,
        "apostille_authority": "the Saudi Ministry of Foreign Affairs",
        "pakistan_mission": "Embassy of Pakistan, Riyadh (or Consulate General, Jeddah)",
        "note": "Saudi Arabia acceded recently (in force Dec 2022) — confirm current practice.",
    },
    # ── Objecting member states: Apostille does NOT operate with Pakistan. ──
    # Present here so the resolver can name the Pakistan mission for the legacy
    # chain. apostille_authority is intentionally omitted — it must never be used.
    "DE": {"name": "Germany", "hague_member": True,
           "pakistan_mission": "Embassy of Pakistan, Berlin (or Consulate General, Frankfurt)"},
    "PL": {"name": "Poland", "hague_member": True,
           "pakistan_mission": "Embassy of Pakistan, Warsaw"},
    "CZ": {"name": "Czech Republic", "hague_member": True,
           "pakistan_mission": "Embassy of Pakistan, Prague"},
    "DK": {"name": "Denmark", "hague_member": True,
           "pakistan_mission": "Embassy of Pakistan, Copenhagen"},
    "AT": {"name": "Austria", "hague_member": True,
           "pakistan_mission": "Embassy of Pakistan, Vienna"},
    "FI": {"name": "Finland", "hague_member": True,
           "pakistan_mission": "Embassy of Pakistan, Helsinki (or the nearest accredited mission)"},
    "GR": {"name": "Greece", "hague_member": True,
           "pakistan_mission": "Embassy of Pakistan, Athens"},
    "NL": {"name": "Netherlands", "hague_member": True,
           "pakistan_mission": "Embassy of Pakistan, The Hague"},
    "IN": {"name": "India", "hague_member": True,
           "pakistan_mission": "the Pakistan High Commission (subject to current diplomatic status)"},
}

# Bilateral block: Apostille does NOT operate between Pakistan and these, DESPITE
# Hague membership. This CANNOT be derived from `hague_member` — it is a separate
# fact from HCCH's Art. 12 objection notifications. The reason distinguishes the
# mechanism (it changes the explanation shown to the user and the conditions under
# which it could change), even though the engine outcome is identical: no apostille.
#   article_12_objection     — the state objected to Pakistan's accession (Art. 12).
#   political_non_recognition — outside the Convention machinery (India).
# SEED from HCCH Art. 12 notifications; verify at _HCCH_STATUS_URL before production.
PK_APOSTILLE_BLOCKED: dict[str, str] = {
    "DE": "article_12_objection",
    "PL": "article_12_objection",
    "CZ": "article_12_objection",
    "DK": "article_12_objection",
    "AT": "article_12_objection",
    "FI": "article_12_objection",
    "GR": "article_12_objection",
    "NL": "article_12_objection",
    "IN": "political_non_recognition",
}

_OBJECTION_EXPLANATION = {
    "article_12_objection": (
        "This country formally objected to Pakistan's accession, so an apostille is "
        "NOT accepted between it and Pakistan even though both are Convention members. "
        "The older consular legalisation chain is required."
    ),
    "political_non_recognition": (
        "Pakistan does not accept apostilles from this country for reasons outside the "
        "Convention. The older consular legalisation chain is required."
    ),
}

_VERIFY_NOTE = (
    "Attestation rules are dated and change (membership, objections and offices are "
    "updated by the authorities). Confirm the exact steps with the receiving office "
    "in Pakistan and your nearest Pakistan mission before relying on this."
)

_REGISTRATION_STEP = (
    "In Pakistan, your attorney pays the stamp duty and registers the POA before the "
    "Sub-Registrar (mandatory for any property dealing; biometric verification and "
    "photographs apply post-2021). Only after registration can the attorney act on "
    "the property."
)


def resolve(country_code: str, *, for_property: bool = True) -> dict:
    """Return the correct attestation path for a POA executed in `country_code`
    and used in Pakistan.

    Fail-safe: an unknown, non-member, objecting or otherwise uncertain country
    falls back to the LEGACY consular chain — never the shorter apostille path.
    Over-attesting only costs the user time; under-attesting gets the document
    REJECTED in Pakistan, which is the exact harm this feature exists to prevent.
    """
    code = (country_code or "").strip().upper()
    rec = COUNTRIES.get(code)
    blocked_reason = PK_APOSTILLE_BLOCKED.get(code)

    country_name = rec["name"] if rec else (country_code or "your country")
    mission = (rec or {}).get("pakistan_mission") or "your nearest Pakistan Embassy or Consulate"
    is_member = bool(rec and rec.get("hague_member"))

    common_tail: list[str] = []
    if for_property:
        common_tail.append(_REGISTRATION_STEP)

    # Apostille path — member, in good standing with Pakistan, and we actually
    # know its issuing authority (the inbound-direction authority, not MOFA).
    if is_member and not blocked_reason and rec.get("apostille_authority"):
        steps = [
            f"Sign the POA before a Notary Public or solicitor in {country_name}.",
            f"Obtain an APOSTILLE on it from {rec['apostille_authority']}. "
            f"This single apostille replaces Pakistan-mission and MOFA attestation.",
            *common_tail,
        ]
        return {
            "route": "apostille",
            "country": country_name,
            "country_code": code,
            "issuing_authority": rec["apostille_authority"],
            "steps": steps,
            "legal_basis": "Hague Apostille Convention; Pakistan Apostille Act 2024.",
            "effective_as_of": EFFECTIVE_AS_OF,
            "note": rec.get("note", ""),
            "verify": _VERIFY_NOTE,
            "source": _HCCH_STATUS_URL,
        }

    # Legacy consular chain — objecting, non-recognised, non-member, or unknown.
    steps = [
        f"Sign the POA before a Notary Public or solicitor in {country_name}.",
        f"Get it attested by {mission}.",
        f"On its arrival in Pakistan, get it attested by {PAKISTAN_MOFA}.",
        *common_tail,
    ]
    result = {
        "route": "legacy",
        "country": country_name,
        "country_code": code,
        "issuing_authority": None,
        "steps": steps,
        "legal_basis": "Consular legalisation (the pre-Apostille chain still applies here).",
        "effective_as_of": EFFECTIVE_AS_OF,
        "verify": _VERIFY_NOTE,
        "source": _HCCH_STATUS_URL,
    }
    if blocked_reason:
        result["reason"] = blocked_reason
        result["note"] = _OBJECTION_EXPLANATION.get(blocked_reason, "")
    elif not rec:
        result["note"] = (
            "This country is not in our verified list, so we default to the fuller "
            "consular chain to be safe. Confirm whether an apostille is accepted."
        )
    elif not is_member:
        result["note"] = "This country is not an Apostille Convention member; the consular chain applies."
    return result


def supported_countries() -> list[dict]:
    """Countries offered in the picker, plus an 'Other' catch-all handled by the
    fail-safe default. Sorted by display name."""
    out = [{"code": c, "name": r["name"]} for c, r in COUNTRIES.items()]
    out.sort(key=lambda x: x["name"])
    out.append({"code": "OTHER", "name": "Other / not listed"})
    return out
