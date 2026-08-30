"""Bail eligibility checker — Pakistani offences → bail classification.

Deterministic lookup against the classification in the Second Schedule of the
Code of Criminal Procedure, 1898, for the most common offences, plus general
bail-type guidance (pre-arrest s.498 vs post-arrest s.497 CrPC).

IMPORTANT — this is INFORMATIONAL, not legal advice and NOT an outcome
prediction. The actual sections in the FIR and the court govern; bail is always
at the court's discretion. Every result carries a strong disclaimer and each
offence carries a `source` + `confidence` flag.
"""
from __future__ import annotations

import re

# The year this classification table is intended to reflect, following
# court_fee._EFFECTIVE. Bail classification is NOT static: the Second Schedule
# has been amended repeatedly, provinces have made their own amendments, and the
# table already carries a per-offence `confidence` of "verify" for seven entries
# whose classification is known to have moved. A reader could see that an
# individual entry was uncertain but not how old the table as a whole was.
_EFFECTIVE = "2024"

_VERIFY = (
    "Classification under the Second Schedule of the CrPC 1898, which has been "
    "amended federally and provincially. The sections actually written on the FIR "
    "govern, later additions change the position, and bail remains at the court's "
    "discretion — confirm with a criminal lawyer."
)

_DISCLAIMER = (
    "This is general information based on the Second Schedule of the CrPC 1898 — NOT legal advice and "
    "NOT a prediction of the outcome. The exact sections in the FIR, later additions, and the court's "
    "discretion govern the actual position. Bail is always decided by the court. If someone is arrested, "
    "consult a criminal lawyer immediately."
)

_SS = "CrPC 1898, Second Schedule"

# Each offence: law, section, title, punishment, cognizable, bailable, compoundable,
# court, note, confidence ('established'|'verify'), source.
# `prohibitory` marks offences punishable with death/life (s.497(1) prohibitory clause).
#
# `aliases` — how a real user actually names the offence: transliteration variants
# (people write "qatl-e-amd" far more often than the title's "qatl-i-amd"), Urdu
# and Roman-Urdu words, and everyday English. Titles alone do not match these, so
# without aliases a search for the commonest spelling of murder returned nothing.
#
# DELIBERATE: a colloquial word that maps to more than one offence is listed on
# EVERY offence it could be. "fraud" is not a section — depending on the facts it
# is s.420 (cheating), s.406 (breach of trust) or s.468 (forgery). Listing it on
# all three makes the lookup return all three, so the ambiguity reaches the user
# instead of being silently resolved into one confidently-wrong section. Aliases
# are a SEARCH aid; they never decide bailability, which is read from the entry.
OFFENCES: list[dict] = [
    {"law": "PPC", "section": "302", "title": "Qatl-i-amd (murder)", "punishment": "Death or life imprisonment",
     "cognizable": True, "bailable": False, "compoundable": True, "court": "Court of Session",
     "prohibitory": True, "confidence": "established", "note": "Compoundable by the legal heirs (Qisas/Diyat).",
     "aliases": ["qatl-e-amd", "qatl e amd", "qatle amad", "qatal-e-amad", "qatl", "murder",
                 "homicide", "killing", "killed someone", "قتل عمد"]},
    {"law": "PPC", "section": "324", "title": "Attempt to commit qatl-i-amd", "punishment": "Up to 10 years + fine",
     "cognizable": True, "bailable": False, "compoundable": True, "court": "Court of Session",
     "confidence": "established",
     "aliases": ["attempt to murder", "attempted murder", "attempt of murder", "iqdam-e-qatl",
                 "iqdam e qatl", "qatl ki koshish", "firing on someone"]},
    {"law": "PPC", "section": "337-A(i)", "title": "Shajjah-i-khafifah (hurt, no fracture)", "punishment": "Daman + up to 2 years",
     "cognizable": True, "bailable": True, "compoundable": True, "court": "Magistrate", "confidence": "established",
     "aliases": ["shajjah", "shajjah-i-khafifah", "hurt", "simple hurt", "injury", "beating",
                 "marpeet", "zakhmi", "chot"]},
    {"law": "PPC", "section": "354", "title": "Assault to outrage a woman's modesty", "punishment": "Up to 2 years or fine",
     "cognizable": True, "bailable": False, "compoundable": False, "court": "Magistrate", "confidence": "verify",
     "note": "Classification has varied by amendment/province — verify.",
     "aliases": ["outraging modesty", "outrage of modesty", "molestation", "assault on a woman",
                 "bad tameezi", "chheir chaar"]},
    {"law": "PPC", "section": "376", "title": "Rape", "punishment": "10–25 years or death (gang rape)",
     "cognizable": True, "bailable": False, "compoundable": False, "court": "Court of Session",
     "prohibitory": True, "confidence": "established",
     "aliases": ["rape", "zina bil jabr", "zina-bil-jabr", "gang rape", "sexual assault", "zyadti", "ziadti"]},
    {"law": "PPC", "section": "379", "title": "Theft", "punishment": "Up to 3 years or fine",
     "cognizable": True, "bailable": False, "compoundable": True, "court": "Magistrate", "confidence": "established",
     "aliases": ["theft", "chori", "stealing", "stole", "stolen", "pickpocket", "چوری"]},
    {"law": "PPC", "section": "380", "title": "Theft in a dwelling house", "punishment": "Up to 7 years + fine",
     "cognizable": True, "bailable": False, "compoundable": True, "court": "Magistrate", "confidence": "established",
     "aliases": ["theft in a dwelling house", "house theft", "theft from house", "ghar se chori",
                 "burglary", "household theft"]},
    {"law": "PPC", "section": "392", "title": "Robbery", "punishment": "Up to 10 years + fine",
     "cognizable": True, "bailable": False, "compoundable": False, "court": "Court of Session", "confidence": "established",
     "aliases": ["robbery", "robbed", "mugging", "street crime", "loot", "lut", "rahzani", "ڈکیتی"]},
    {"law": "PPC", "section": "396", "title": "Dacoity with murder", "punishment": "Death or life imprisonment",
     "cognizable": True, "bailable": False, "compoundable": False, "court": "Court of Session",
     "prohibitory": True, "confidence": "established",
     "aliases": ["dacoity with murder", "dacoity", "daka", "daka zani", "gang robbery with murder"]},
    {"law": "PPC", "section": "406", "title": "Criminal breach of trust", "punishment": "Up to 7 years + fine",
     "cognizable": True, "bailable": False, "compoundable": True, "court": "Magistrate", "confidence": "established",
     # "fraud" is intentionally shared with s.420 and s.468 — see the note above.
     "aliases": ["criminal breach of trust", "breach of trust", "khayanat", "amanat mein khayanat",
                 "embezzlement", "misappropriation", "fraud"]},
    {"law": "PPC", "section": "411", "title": "Dishonestly receiving stolen property", "punishment": "Up to 3 years or fine",
     "cognizable": True, "bailable": False, "compoundable": True, "court": "Magistrate", "confidence": "established",
     "aliases": ["receiving stolen property", "stolen property", "stolen goods", "chori ka maal",
                 "possession of stolen goods"]},
    {"law": "PPC", "section": "420", "title": "Cheating and dishonestly inducing delivery of property",
     "punishment": "Up to 7 years + fine", "cognizable": True, "bailable": False, "compoundable": True,
     "court": "Magistrate", "confidence": "established",
     "aliases": ["cheating", "cheated", "fraud", "dhoka", "dhoka dahi", "dhokadhari", "scam",
                 "swindling", "conned", "420 case", "دھوکہ"]},
    {"law": "PPC", "section": "468", "title": "Forgery for the purpose of cheating", "punishment": "Up to 7 years + fine",
     "cognizable": True, "bailable": False, "compoundable": False, "court": "Magistrate", "confidence": "established",
     "aliases": ["forgery", "forged", "jaali kaghzat", "jaal sazi", "jaalsazi", "fake documents",
                 "document forgery", "fraud"]},
    {"law": "PPC", "section": "471", "title": "Using a forged document as genuine", "punishment": "As for forgery of that document",
     "cognizable": True, "bailable": False, "compoundable": False, "court": "Magistrate", "confidence": "verify",
     "aliases": ["using a forged document", "used fake documents", "submitted forged papers",
                 "jaali dastavez"]},
    {"law": "PPC", "section": "489-F", "title": "Dishonestly issuing a cheque that is dishonoured",
     "punishment": "Up to 3 years or fine or both", "cognizable": True, "bailable": False, "compoundable": False,
     "court": "Magistrate", "confidence": "established",
     "aliases": ["cheque bounce", "cheque bounced", "bounced cheque", "dishonoured cheque",
                 "check bounce", "cheque dishonour", "489f", "489-f case"]},
    {"law": "PPC", "section": "506", "title": "Criminal intimidation", "punishment": "Part I: up to 2 years; Part II: up to 7 years",
     "cognizable": False, "bailable": True, "compoundable": True, "court": "Magistrate", "confidence": "verify",
     "note": "s.506 Part II (threat to cause death/grievous hurt) may be non-bailable — check the exact charge.",
     "aliases": ["criminal intimidation", "threat", "threatened", "threatening", "dhamki",
                 "death threat", "intimidation"]},
    {"law": "PPC", "section": "509", "title": "Insulting the modesty of a woman / sexual harassment",
     "punishment": "Up to 3 years + fine", "cognizable": True, "bailable": False, "compoundable": False,
     "court": "Magistrate", "confidence": "verify",
     "aliases": ["sexual harassment", "harassment", "insulting modesty", "eve teasing",
                 "harassed at work", "catcalling"]},
    {"law": "PPC", "section": "148", "title": "Rioting, armed with a deadly weapon", "punishment": "Up to 3 years + fine",
     "cognizable": True, "bailable": False, "compoundable": False, "court": "Magistrate", "confidence": "established",
     "aliases": ["rioting", "riot", "armed rioting", "fasad", "hangama", "mob violence"]},
    {"law": "PPC", "section": "452", "title": "House-trespass after preparation for hurt/assault", "punishment": "Up to 7 years + fine",
     "cognizable": True, "bailable": False, "compoundable": False, "court": "Magistrate", "confidence": "established",
     "aliases": ["house trespass", "trespass", "criminal trespass", "ghar mein ghusna",
                 "forced entry", "broke into house"]},
    {"law": "PPC", "section": "186", "title": "Obstructing a public servant in duty", "punishment": "Up to 3 months or fine",
     "cognizable": False, "bailable": True, "compoundable": False, "court": "Magistrate", "confidence": "established",
     "aliases": ["obstructing a public servant", "obstruction of duty", "resisting police",
                 "sarkari mulazim ko rokna"]},
    {"law": "PPC", "section": "34", "title": "Acts done by several persons in furtherance of common intention",
     "punishment": "As for the substantive offence", "cognizable": None, "bailable": None, "compoundable": False,
     "court": "As per the main offence", "confidence": "established",
     "note": "Not a separate offence — bail follows the substantive offence charged with it.",
     "aliases": ["common intention", "acted together", "along with others"]},
    # ── Special laws ──
    {"law": "CNSA 1997", "section": "9(b)", "title": "Narcotics — intermediate quantity", "punishment": "Up to 7 years",
     "cognizable": True, "bailable": False, "compoundable": False, "court": "Special Court (CNSA)", "confidence": "verify",
     "note": "Quantity-based; thresholds were revised by the CNS (Amendment) Act 2022 — verify the applicable slab.",
     "aliases": ["narcotics", "drugs", "drug possession", "charas", "hashish", "heroin", "ice",
                 "nasha", "cnsa", "control of narcotic substances"]},
    {"law": "CNSA 1997", "section": "9(c)", "title": "Narcotics — large quantity", "punishment": "Death / life / up to 14 years",
     "cognizable": True, "bailable": False, "compoundable": False, "court": "Special Court (CNSA)",
     "prohibitory": True, "confidence": "established", "note": "s.51 CNSA restricts bail for the higher slab.",
     "aliases": ["narcotics large quantity", "drug trafficking", "drug smuggling", "bulk narcotics",
                 "heroin trafficking", "charas trafficking"]},
    {"law": "PECA 2016", "section": "20", "title": "Offences against the dignity of a person (online)", "punishment": "Up to 3 years or fine",
     "cognizable": False, "bailable": True, "compoundable": True, "court": "Magistrate / Sessions", "confidence": "verify",
     "aliases": ["online defamation", "cyber defamation", "defamation online", "peca",
                 "dignity of a person", "posted about me online"]},
    {"law": "PECA 2016", "section": "21", "title": "Offences against the modesty of a person / minor (online)",
     "punishment": "Up to 7 years + fine", "cognizable": True, "bailable": False, "compoundable": False,
     "court": "Sessions", "confidence": "verify",
     "aliases": ["online harassment", "cyber harassment", "revenge porn", "obscene pictures online",
                 "leaked photos", "blackmail with photos", "morphed pictures"]},
    {"law": "PECA 2016", "section": "10", "title": "Cyber terrorism", "punishment": "Up to 14 years or fine or both",
     "cognizable": True, "bailable": False, "compoundable": False, "court": "Sessions", "confidence": "established",
     "aliases": ["cyber terrorism", "cyberterrorism", "hacking critical infrastructure"]},
    {"law": "ATA 1997", "section": "7", "title": "Act of terrorism", "punishment": "Death / life / long imprisonment",
     "cognizable": True, "bailable": False, "compoundable": False, "court": "Anti-Terrorism Court",
     "prohibitory": True, "confidence": "established", "note": "s.21-D ATA restricts bail.",
     "aliases": ["terrorism", "act of terrorism", "ata", "anti terrorism", "dehshat gardi",
                 "terrorist act", "atc case"]},
]


def _norm(sec: str) -> str:
    """Fold a section reference to a comparison key.

    Hyphens are stripped as well as whitespace, so the three ways a lettered
    section is written all collide: "489-F", "489 F" and "489F" become 489F.
    Before this, lookup was exact-string on a table that stores the HYPHENATED
    form ("489-F", "337-A(i)"), so check("PPC", "489F") returned found=False for
    an offence the table plainly holds — and the corpus stores lettered sections
    COMPACTLY ("365B", "496A"), so a section read off a retrieved chunk missed
    every time.

    Applied to both sides of every comparison (_find and search both normalise
    the stored value too), so the fold cannot create a false match: it only
    removes a distinction that was never meaningful.

    En and em dashes are included because a section pasted from a PDF or a
    court order frequently carries one instead of a hyphen.

    NOT stripped: parentheses. "9(b)" and "9(c)" are different provisions of the
    CNSA and must not collide, so a user writing "9b" still misses. That is a
    known remaining gap, deliberately left rather than over-folded.
    """
    return "".join((sec or "").upper().split()).replace("-", "").replace(
        "–", "").replace("—", "")


def _slug(text: str) -> str:
    """Fold punctuation and spacing so transliteration variants compare equal.

    'qatl-e-amd', 'Qatl e Amd' and 'qatl  e  amd' all become 'qatl e amd'. This
    is why the alias lists do not need to enumerate every hyphenation. \\w keeps
    Urdu script intact rather than stripping it to nothing.
    """
    return " ".join(re.sub(r"[^\w]+", " ", (text or "").lower(), flags=re.UNICODE).split())


# Word-overlap matching ignores tokens shorter than this. Without the floor,
# "an" matches inside "wom(an)'s modesty" and "Cheating (an)d ...", so ANY
# sentence containing a stopword dragged in unrelated offences — which made
# find_offence_sections return junk candidates instead of honestly reporting
# "no match", and a junk candidate is one the model can then act on.
_MIN_WORD_LEN = 4


def search(query: str, limit: int = 12) -> list[dict]:
    q = (query or "").strip().lower()
    if not q:
        return []
    qn = _norm(query).lower()
    qs = _slug(query)
    # Only tokens long enough to be meaningful; "chori", "daka", "theft" survive.
    q_words = {w for w in qs.split() if len(w) >= _MIN_WORD_LEN}

    scored: list[tuple[int, dict]] = []
    for o in OFFENCES:
        secn = _norm(o["section"]).lower()
        title_words = set(_slug(o["title"]).split())
        alias_s = [_slug(a) for a in o.get("aliases", [])]

        # Highest first — an explicit section number always beats a word match,
        # so someone who types "302" still gets 302 and not every alias of murder.
        if qn and (qn == secn or secn.startswith(qn) or qn in secn):
            score = 100 - abs(len(secn) - len(qn))
        elif qs and any(qs == a for a in alias_s):
            score = 70                      # exact alias: "qatl e amd", "cheque bounce"
        elif len(qs) >= _MIN_WORD_LEN and (qs in _slug(o["title"]) or qs in o["law"].lower()):
            score = 50
        elif len(qs) >= _MIN_WORD_LEN and any(a and (a in qs or qs in a) for a in alias_s):
            # Alias inside a longer phrase. Length-guarded for the same reason as
            # above: without it "an" matches inside the alias "assault on a woman".
            # Short aliases ("lut", "ata") are unaffected — they hit the exact-alias
            # branch above, which compares whole strings.
            score = 40
        elif q_words & title_words:
            score = 30                      # whole-word overlap with the title
        elif q_words and any(w in set(a.split()) for a in alias_s for w in q_words):
            score = 25                      # single alias word, e.g. "chori"
        else:
            score = 0

        if score:
            scored.append((score, o))

    scored.sort(key=lambda x: -x[0])
    # `relevance` is exposed so callers can tell a decisive hit from a genuine
    # tie: "qatl e amd" scores 70 on s.302 and only 25 on the s.324 token overlap
    # (decisive), whereas "fraud" scores 70 on s.406, s.420 AND s.468 (a real
    # ambiguity the user has to resolve).
    return [_public(o) | {"relevance": score} for score, o in scored[:limit]]


def _public(o: dict) -> dict:
    # `aliases` is a search aid, not part of the legal record — keep it out of the
    # payload so it never reaches an LLM prompt or the API as if it were content.
    return {k: v for k, v in o.items() if k != "aliases"} | {"id": f"{o['law']}:{o['section']}"}


# How a caller names a statute, folded to how the table stores it.
#
# The table stores "CNSA 1997", "ATA 1997", "PECA 2016" but the LLM tool
# docstring tells the model to pass bare "CNSA", "ATA", "PECA" — so an exact
# comparison missed every non-PPC offence. That miss was invisible because the
# section-only fallback below caught it and returned the right answer for the
# wrong reason, which is also how the fallback came to return the WRONG answer
# for a mismatched statute. Normalising here is what makes it safe to restrict
# the fallback.
_LAW_ALIASES = {
    "PPC":  "PPC",
    "PAKISTAN PENAL CODE": "PPC",
    "PENAL CODE": "PPC",
    "CNSA": "CNSA 1997",
    "CONTROL OF NARCOTIC SUBSTANCES ACT": "CNSA 1997",
    "PECA": "PECA 2016",
    "PREVENTION OF ELECTRONIC CRIMES ACT": "PECA 2016",
    "ATA":  "ATA 1997",
    "ANTI-TERRORISM ACT": "ATA 1997",
    "ANTI TERRORISM ACT": "ATA 1997",
}

_YEAR_SUFFIX = re.compile(r"[,\s]+(1[89]|20)\d{2}$")


def _norm_law(law: str) -> str:
    """Fold a statute name to the table's canonical form. "" when unspecified.

    Year-insensitive: "CNSA", "CNSA 1997" and "cnsa, 1997" are one statute. The
    year is dropped and then re-attached from the alias table, so the canonical
    value always matches what OFFENCES stores.
    """
    name = " ".join((law or "").upper().split())
    if not name:
        return ""
    if name in _LAW_ALIASES:
        return _LAW_ALIASES[name]
    bare = _YEAR_SUFFIX.sub("", name).strip()
    return _LAW_ALIASES.get(bare, bare)


def sections_matching(section: str) -> list[dict]:
    """Every offence carrying this section number, whatever the statute.

    Used to turn a wrong-statute lookup into a useful correction rather than a
    flat "not found": the section usually DOES exist, under another Act.
    """
    sn = _norm(section)
    return [o for o in OFFENCES if _norm(o["section"]) == sn]


def _find(law: str, section: str) -> dict | None:
    """Look up one offence. A stated statute is BINDING.

    The section-only pass used to run unconditionally and ignored `law`
    entirely, so it answered from whatever statute happened to carry that
    number. check("PPC", "20") returned PECA 2016 s.20 — bailable, "a matter of
    right" — for a query about the Penal Code, with found=True and no echo of
    what was asked. A wrong-statute bail answer is the most directly harmful
    output this service can produce.

    The fallback is kept for the case it was actually for: no statute given at
    all, where a bare section number is all the caller has.
    """
    ln, sn = _norm_law(law), _norm(section)
    for o in OFFENCES:
        if _norm_law(o["law"]) == ln and _norm(o["section"]) == sn:
            return o
    if ln:
        # A statute was named and it does not carry this section. Saying so is
        # the correct answer; substituting a different Act's offence is not.
        return None
    for o in OFFENCES:
        if _norm(o["section"]) == sn:
            return o
    return None


def bail_guidance(bailable, arrested: bool, prohibitory: bool = False) -> dict:
    if bailable is None:
        return {"summary": "Bail follows the substantive offence charged alongside this section.",
                "sections": [], "steps": ["Identify the main offence in the FIR and check that."]}
    if bailable:
        return {
            "summary": "This offence is BAILABLE — bail is a matter of right.",
            "sections": ["CrPC s.496"],
            "steps": [
                "Bail can be granted by the officer-in-charge of the police station or by the court.",
                "The accused furnishes bail bonds with surety; the court cannot refuse bail in a bailable offence.",
            ],
        }
    # non-bailable
    if not arrested:
        steps = [
            "Apply for PRE-ARREST (anticipatory) bail under s.498 CrPC before the Sessions Court or High Court BEFORE arrest.",
            "Interim (ad-interim) pre-arrest bail may be granted first, then confirmed after notice to the prosecution.",
        ]
        secs = ["CrPC s.498"]
        summary = "This offence is NON-BAILABLE. As the person is not yet arrested, seek PRE-ARREST bail (s.498 CrPC)."
    else:
        steps = [
            "Apply for POST-ARREST bail under s.497 CrPC before the competent court (usually the Sessions Court).",
            "Grounds commonly include no reasonable ground for guilt, further inquiry (s.497(2)), delay in trial, sickness, first offender, or false implication.",
        ]
        secs = ["CrPC s.497"]
        summary = "This offence is NON-BAILABLE. As the person is arrested, seek POST-ARREST bail (s.497 CrPC)."
    if prohibitory:
        steps.append(
            "This offence carries the s.497(1) PROHIBITORY CLAUSE (punishable with death/life): the court will not "
            "ordinarily grant bail, but it retains discretion (e.g. further inquiry, delay, sickness, tender age). "
            "Bail is discretionary, NOT barred."
        )
    return {"summary": summary, "sections": secs, "steps": steps}


def check(law: str, section: str, arrested: bool = True) -> dict:
    o = _find(law, section)
    if not o:
        # The section usually DOES exist, under a different Act — which is
        # exactly the confusion that used to be resolved by silently answering
        # from that other Act. Name the alternatives instead, and let the user
        # confirm which statute the FIR actually cites. This never asserts
        # bailability for the mismatched offence.
        elsewhere = sections_matching(section) if _norm_law(law) else []
        steps = ["Confirm the exact section against the Second Schedule of the CrPC 1898, or consult a lawyer."]
        summary = "This offence is not in the reference list."
        if elsewhere:
            others = ", ".join(f"{x['law']} s.{x['section']}" for x in elsewhere)
            summary = (
                f"Section {section} is not in the reference list under "
                f"{_norm_law(law)}. It does appear under {others}."
            )
            steps.insert(0, (
                "Check which statute the FIR actually cites — the sections written on "
                "the FIR govern, and this section number belongs to a different Act here."
            ))
        return {
            "found": False,
            "query": {"law": law, "section": section},
            # Named so a caller cannot mistake it for a determination about the
            # queried offence. It is a pointer, not a classification.
            "section_found_under": [
                {"law": x["law"], "section": x["section"], "title": x["title"]}
                for x in elsewhere
            ],
            "guidance": {
                "summary": summary,
                "steps": steps,
            },
            "general_rule": general_rule(None),
            "legal_basis": _SS,
            "effective_as_of": _EFFECTIVE,
            "verify": _VERIFY,
            "disclaimer": _DISCLAIMER,
        }
    return {
        "found": True,
        "offence": _public(o),
        "guidance": bail_guidance(o.get("bailable"), arrested, o.get("prohibitory", False)),
        "legal_basis": f"{_SS}; punishment under {o['law']} s.{o['section']}",
        "confidence": o.get("confidence", "verify"),
        "effective_as_of": _EFFECTIVE,
        "verify": _VERIFY,
        "disclaimer": _DISCLAIMER,
    }


def general_rule(max_punishment_years: int | None) -> dict:
    if max_punishment_years is None:
        text = ("General rule: offences punishable with death, life imprisonment, or imprisonment exceeding 3 years "
                "are generally cognizable and non-bailable; those punishable with 3 years or less, or with fine only, "
                "are often bailable. This is a rough guide only.")
    elif max_punishment_years > 3:
        text = (f"An offence punishable with about {max_punishment_years} years is generally cognizable and "
                f"NON-BAILABLE under the usual rule — but confirm against the Second Schedule.")
    else:
        text = (f"An offence punishable with about {max_punishment_years} years or less is often BAILABLE — "
                f"but confirm against the Second Schedule.")
    return {"text": text, "confidence": "verify", "source": _SS}
