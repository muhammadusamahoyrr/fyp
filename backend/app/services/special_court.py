"""Special-Court jurisdiction engine — Protection of Overseas Pakistanis' Property.

A live legal development almost nobody has tooling for. The federal Protection of
Overseas Pakistanis' Property Act 2024 created a special-court regime for property
disputes of overseas Pakistanis (special court in Islamabad, e-filing, video-link
hearings supervised by missions, a statutory disposal deadline). Provinces are now
enacting their OWN versions on a rolling basis, and the procedures DIFFER by
jurisdiction (disposal/appeal windows, whether a court is actually operational yet).

Why this is a jurisdiction engine and not a paragraph of static text:
  * The remedy that applies depends on WHERE the property is (province), and each
    province is at a different stage — federal/ICT operational, some provinces
    enacted-but-not-yet-operational, others with nothing yet.
  * Timelines are not uniform (e.g. 90-day federal disposal vs a reported 120-day
    provincial one). Stating one number everywhere would be wrong.
  * "Which court, is it running, how long, can I file by video" is precisely the
    per-jurisdiction lookup a static list gets wrong the moment a province moves.

FAIL-SAFE, the same principle the removed apostille table used:
  When a province's special court is not confirmed OPERATIONAL, the engine does NOT
  tell the user to e-file into it. Sending someone to file in a court that isn't
  hearing cases yet wastes the one thing they're short on — time and trust. Instead
  it routes them to the federal Act framework and a lawyer, and flags "verify". The
  high-value job here is telling the user this remedy EXISTS at all (most don't
  know) and giving the province-specific path where it's known.

SOURCE OF TRUTH — reconcile before relying on any of this in production:
  The federal Act's text + each province's gazette notification and the relevant
  High Court's notification of the designated special court. Court operational
  status and timelines change week to week right now. This file is a dated SEED
  with the same `verify` duty as the court-fee table.
"""
from __future__ import annotations

# Last reconciled against the federal Act, provincial gazettes / HC notifications,
# and press reporting of the February 2026 Punjab Ordinances. Bump this ONLY when the facts
# below are actually re-checked -- it previously read 2026-07 while missing the
# 18 Feb 2026 Punjab Ordinances, which is worse than no date at all: it asserted
# a currency the file did not have.
EFFECTIVE_AS_OF = "2026-08"

# Court status vocabulary.
OPERATIONAL = "operational"          # a designated court is hearing cases now
ENACTED_PENDING = "enacted_pending"  # law passed; court not confirmed operational
NONE_YET = "none_yet"                # no dedicated special-court regime yet

# The federal remedy that exists regardless of province — the safe fallback.
_FEDERAL_ACT = "Protection of Overseas Pakistanis' Property Act, 2024 (federal)"

# Per-jurisdiction record. Keyed by province/territory code.
#   act            — the statute that applies there.
#   court_status   — OPERATIONAL | ENACTED_PENDING | NONE_YET.
#   disposal_days  — statutory deadline to decide, MEASURED FROM THE GRANT OF LEAVE
#                    TO DEFEND, not from filing. The filing -> leave-to-defend gap is
#                    NOT inside this clock, so "resolved in 90 days" without that
#                    caveat sets a wrong expectation. Surfaced with the hedge below.
#   appeal_days    — window to appeal to the High Court, if known (else None). Like
#                    the disposal figure, this varies by jurisdiction — it is a dated,
#                    per-province fact, not one national number.
#   efiling / video_link — supported filing modes where known.
#   confidence     — "established" | "reported" | "single_source" | "unconfirmed" —
#                    how sure the facts below are. "reported" means corroborated
#                    across press sources but not yet read against the gazette.
#                    Anything not "established" MUST be verified.
#   note           — jurisdiction-specific caveat surfaced to the user.
JURISDICTIONS: dict[str, dict] = {
    # ICT: a special court is sitting in Islamabad -- two District & Sessions
    # judges designated, plus a nominated IHC judge and a special IHC bench.
    "ICT": {
        "name": "Islamabad Capital Territory / federal",
        "act": _FEDERAL_ACT,
        "court_status": OPERATIONAL,
        "disposal_days": 90,     # s.9(1): decided within 90 days of grant of leave to defend
        "appeal_days": 15,       # s.10(1): appeal to the IHC within 15 days
        "appeal_disposal_days": 90,  # s.10(3): IHC decides the appeal within 90 days
        "efiling": True,
        "video_link": True,
        "confidence": "established",
        # Confirmed against the PRIMARY source, not inferred from Punjab.
        "source": "Establishment of Special Court (Overseas Pakistanis Property) Act, 2024 "
                  "(Act No. XXVIII of 2024, Gazette of Pakistan, 2 Nov 2024): s.10(1) appeal "
                  "within 15 days to the Islamabad High Court; s.10(3) IHC decides within 90 "
                  "days; s.9(1) disposal within 90 days of grant of leave to defend.",
        "note": "The federal special court in Islamabad is operational, with e-filing "
                "and video-link hearings supervised by Pakistan missions.",
    },
    "PB": {
        "name": "Punjab",
        "act": "Punjab Establishment of Special Courts (Overseas Pakistanis Property) "
               "Act 2025",
        "court_status": ENACTED_PENDING,
        "disposal_days": None,
        "appeal_days": 15,         # single-source; verify against the Punjab gazette
        "efiling": None,
        "video_link": None,
        "confidence": "reported",
        "note": "The Punjab Act is PASSED; designation of judges was still under way as "
                "of August 2026, so the special court is not confirmed to be hearing "
                "cases. Two separate Ordinances promulgated on 18 February 2026 also "
                "bear on Punjab property disputes and are NOT this Act: the Punjab Land "
                "Revenue (Amendment) Ordinance 2026 (e-registration; mutation requires a "
                "registered deed; patwaris limited to inheritance transfers) and the "
                "Punjab Protection of Ownership of Immovable Property (Amendment) "
                "Ordinance 2026 (see POIP_TRIBUNAL below -- 30-day tribunal decisions, "
                "5-10 years for illegal possession, Rs 500,000 and up to five years for "
                "a FALSE complaint). Confirm with the Lahore High Court whether a "
                "designated special court is sitting, and the exact windows.",
        "source": "Punjab Establishment of Special Courts (Overseas Pakistanis Property) "
                  "Act 2025 (press-reported; verify against the Punjab Gazette).",
    },
    "KP": {
        "name": "Khyber Pakhtunkhwa",
        "act": "KP's provincial Overseas Pakistanis' Property Act (passed 2026)",
        "court_status": ENACTED_PENDING,
        "disposal_days": 120,      # single-source; verify against the KP gazette
        "appeal_days": 15,         # single-source; verify
        "efiling": None,
        "video_link": None,
        "confidence": "single_source",
        "note": "KP passed its Act recently, reportedly with a 120-day disposal and "
                "15-day appeal window — confirm these against the KP gazette and the "
                "Peshawar High Court notification before relying on them.",
    },
    "SD": {
        "name": "Sindh",
        "act": None,
        "court_status": NONE_YET,
        "disposal_days": None,
        "appeal_days": None,
        "efiling": None,
        "video_link": None,
        "confidence": "unconfirmed",
        "note": "No confirmed provincial special-court regime for Sindh yet; the "
                "federal Act framework and the ordinary courts apply.",
    },
    "BL": {
        "name": "Balochistan",
        "act": None,
        "court_status": NONE_YET,
        "disposal_days": None,
        "appeal_days": None,
        "efiling": None,
        "video_link": None,
        "confidence": "unconfirmed",
        "note": "No confirmed provincial special-court regime for Balochistan yet; the "
                "federal Act framework and the ordinary courts apply.",
    },
}

# OPPPA — the registration/verification authority the 2024 law creates. Registering
# a property in its database is a cheap, protective step against double-ownership and
# fraudulent transfer, and it's exactly the bureaucratic task people skip. Surfaced on
# every result as a recommended action.
OPPPA_ACTION = {
    "title": "Register the property with OPPPA",
    "detail": "The Act establishes the Overseas Pakistanis' Property Protection Authority "
              "with an online registration/verification database. Registering your property "
              "there guards against double-ownership and fraudulent transfer. Confirm the "
              "current registration portal and requirements.",
}

_VERIFY = (
    "This is a live, fast-moving regime — provinces are enacting and standing up courts "
    "on a rolling basis, and timelines differ. Confirm the current position with the "
    "relevant High Court and a lawyer before filing."
)

_REMEDY_SUMMARY = (
    "You may have a dedicated remedy: the Protection of Overseas Pakistanis' Property "
    "Act 2024 (and provincial versions) sets up special courts for overseas Pakistanis' "
    "property disputes, with e-filing, video-link hearings supervised by Pakistan "
    "missions, and a statutory deadline to decide the case. Most overseas Pakistanis "
    "do not know this exists."
)

_PROVINCE_ALIASES = {
    "islamabad": "ICT", "ict": "ICT", "federal": "ICT", "capital": "ICT",
    "punjab": "PB", "lahore": "PB",
    "kpk": "KP", "kp": "KP", "khyber": "KP", "khyber pakhtunkhwa": "KP", "peshawar": "KP",
    "sindh": "SD", "karachi": "SD",
    "balochistan": "BL", "baluchistan": "BL", "quetta": "BL",
}


def _code(province: str) -> str | None:
    p = (province or "").strip().lower()
    if not p:
        return None
    if p.upper() in JURISDICTIONS:
        return p.upper()
    return _PROVINCE_ALIASES.get(p)


# ── The other forum: provincial anti-dispossession tribunals ─────────────────
#
# The special-court regime above is not the only route, and for the commonest
# grievance it is not the fastest. Punjab's Protection of Ownership of Immovable
# Property (Amendment) Ordinance 2026 (promulgated 18 Feb 2026) tightened an
# existing tribunal regime aimed squarely at illegal possession:
#
#   * tribunal decision within 30 days (previously 90)
#   * scrutiny report within 30 days (previously extendable to 90)
#   * a Scrutiny Committee replaces the Dispute Resolution Committee
#   * SERVING judges hear complaints, not retired ones
#   * illegal possession now carries 5-10 years and a fine up to Rs 10,000,000
#   * tribunals, not District Coordinators, authorise preventive action
#
# This matters because Punjab's SPECIAL court is still ENACTED_PENDING. Routing a
# Punjab dispossession case only to a court that is not yet sitting, while a
# tribunal with a 30-day clock exists, is the wrong answer given confidently.
# The tribunal is offered as an ALTERNATIVE, never as a replacement: which forum
# is right depends on facts this system does not have, so it names both and says
# a lawyer chooses.

POIP_TRIBUNAL: dict[str, dict] = {
    "PB": {
        "name": "Punjab Protection of Ownership of Immovable Property tribunal",
        "act": "Punjab Protection of Ownership of Immovable Property (Amendment) "
               "Ordinance 2026 (promulgated 18 February 2026), amending the "
               "principal Punjab enactment",
        # Only the grievances this forum is actually for. An inheritance dispute
        # or a sale-agreement quarrel does not belong in an anti-dispossession
        # tribunal, and offering it there would be worse than saying nothing.
        "applies_to": ("illegal_occupation", "encroachment"),
        "decision_days": 30,
        "scrutiny_report_days": 30,
        "bench": "Serving judges (the Ordinance replaced retired-judge benches).",
        "penalties": "Illegal possession: 5-10 years and a fine up to Rs 10,000,000.",
        "confidence": "reported",   # press-reported; verify against the gazette
        "verify": "Confirm against the Punjab Gazette text of the 2026 Ordinance "
                  "before relying on the 30-day timelines or the penalty range.",
    },
}


def poip_tribunal(province: str, category: str = "") -> dict | None:
    """The anti-dispossession tribunal route for `province`, if one applies.

    Returns None when the province has no such regime recorded, or when the
    grievance is not the kind this forum handles. Category-aware on purpose: a
    tribunal for illegal possession is the fast route for a land grab and the
    wrong route for an inheritance quarrel.
    """
    code = _code(province)
    rec = POIP_TRIBUNAL.get(code) if code else None
    if rec is None:
        return None
    if category and category not in rec["applies_to"]:
        return None
    return dict(rec)


def resolve(province: str) -> dict:
    """Return the special-court guidance for a property located in `province`.

    Always returns the remedy summary and the OPPPA registration action. The
    per-jurisdiction filing route is only asserted when the province's court is
    confirmed OPERATIONAL; otherwise it fails safe to the federal framework plus a
    lawyer, and flags the uncertainty.
    """
    code = _code(province)
    rec = JURISDICTIONS.get(code) if code else None

    base = {
        "province": (rec["name"] if rec else (province or "unknown")),
        "province_code": code,
        "remedy_summary": _REMEDY_SUMMARY,
        "recommended_registration": OPPPA_ACTION,
        "effective_as_of": EFFECTIVE_AS_OF,
        "verify": _VERIFY,
    }

    # Unknown province → surface the remedy exists, but do not invent a court.
    if rec is None:
        base.update({
            "court_status": "unknown",
            "can_efile_now": False,
            "steps": [
                "Confirm which province your property is in.",
                f"The federal framework — {_FEDERAL_ACT} — may still give you a route; "
                "check whether your matter is federally cognizable.",
                "Engage a lawyer to identify the correct forum and prepare the complaint.",
            ],
            "note": "We could not match this to a known jurisdiction, so we default to "
                    "the federal framework and a lawyer rather than naming a court.",
        })
        return base

    operational = rec["court_status"] == OPERATIONAL

    if operational:
        steps = [
            f"Your dispute may be filed in the special court under {rec['act']}.",
        ]
        if rec.get("efiling"):
            steps.append("File online (e-filing) — you do not need to travel to Pakistan to lodge it.")
        if rec.get("video_link"):
            steps.append("Give evidence by video link, supervised by your nearest Pakistan mission.")
        if rec.get("disposal_days"):
            steps.append(
                f"Once the respondent is granted leave to defend, the court must decide the case "
                f"within about {rec['disposal_days']} days. Note: the {rec['disposal_days']}-day clock "
                f"starts at leave to defend, NOT at filing — the gap before that is not inside it."
            )
        if rec.get("appeal_days"):
            steps.append(f"An appeal to the High Court must be filed within about {rec['appeal_days']} days.")
        steps.append("Engage a lawyer to prepare and file the complaint on your behalf.")
    else:
        # Enacted-but-pending or none-yet → do NOT send them to file. Fail safe.
        steps = [
            f"{rec['act'] or 'A dedicated provincial regime'} is not confirmed operational "
            f"for {rec['name']} yet — do not assume you can e-file there today.",
            f"The federal framework — {_FEDERAL_ACT} — may still give you a route; check "
            "whether your matter is federally cognizable.",
            "Engage a lawyer to confirm the correct forum and prepare the complaint.",
        ]

    base.update({
        "court_status": rec["court_status"],
        "act": rec["act"],
        "disposal_days": rec.get("disposal_days"),
        "appeal_days": rec.get("appeal_days"),
        "appeal_disposal_days": rec.get("appeal_disposal_days"),
        "efiling": rec.get("efiling"),
        "video_link": rec.get("video_link"),
        "confidence": rec["confidence"],
        "can_efile_now": bool(operational and rec.get("efiling")),
        "steps": steps,
        "note": rec.get("note", ""),
        "source": rec.get("source", ""),
    })
    return base


def supported_provinces() -> list[dict]:
    """Provinces offered in the picker, plus an 'Other' catch-all (fail-safe)."""
    order = ["ICT", "PB", "KP", "SD", "BL"]
    out = [{"code": c, "name": JURISDICTIONS[c]["name"],
            "court_status": JURISDICTIONS[c]["court_status"]} for c in order]
    out.append({"code": "OTHER", "name": "Other / not sure", "court_status": "unknown"})
    return out
