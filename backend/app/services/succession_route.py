"""Which forum grants a succession certificate — NADRA or the civil court?

GUIDANCE, NOT A FILING. This deliberately produces no PDF and no document
record. The reason is in the statute: s.7 of the Punjab Act says Letters of
Administration and Succession Certificates "shall be issued... in the forms
prescribed by the Authority", so the form belongs to NADRA and drafting our own
would be inventing paperwork the law does not ask for. What a person in Punjab
actually needs is to be sent to the right counter.

THE CLAUSE CHAIN
----------------
Punjab Letters of Administration and Succession Certificates Act 2021

  s.3   "Notwithstanding anything contained in any other law for the time being
        in force, the Authority [or a civil court] may issue Letters of
        Administration or Succession Certificates ... to the legal heirs of a
        deceased". Both doors are open; the Act does not close the court.

  s.6(1) The application "shall be made to the Authority by the legal heirs",
        with a proviso letting the heirs authorise one of their number to act
        for all in the prescribed form.

  s.6(2) Venue: the notified office "within whose jurisdiction the deceased
        ordinarily resided at the time of his death, or within whose
        jurisdiction any property or asset of the deceased is located."

  s.5(b) THE REFERRAL TRIGGER. The Succession Facilitation Unit processes by
        "summary enquiry", and "in case of any factual controversy amongst the
        legal heirs" must "decline to assess the applications for filing afresh
        before the appropriate forum in accordance with the provisions of the
        Succession Act, 1925 (XXXIX of 1925)".

  s.7   Forms are prescribed by the Authority — see the note above.

Succession Act 1925

  s.372 The contested path. Application to the DISTRICT JUDGE by petition
        "signed and verified ... in the manner prescribed by the Code of Civil
        Procedure, 1908 ... for a plaint", stating the particulars in clauses
        (a) to (f).

  s.370 A certificate cannot be granted for a debt or security where the right
        must be established by letters of administration or probate. This bites
        before either route and is why "undisputed" alone is not the whole test.

WHY THE TRIGGER IS DISPUTE, NOT VALUE
-------------------------------------
s.5(b) turns on "factual controversy amongst the legal heirs" — not on how much
the estate is worth, and not on how many heirs there are. A large undisputed
estate stays with NADRA; a small contested one goes to court. Encoding a value
threshold here would be inventing a rule the Act does not contain.

LIMITS THIS STATES RATHER THAN HIDES
------------------------------------
Punjab only. The 2021 Act is provincial, and a death outside Punjab with no
Punjab property is outside it entirely — that case is routed to the 1925 Act
without pretending the NADRA route exists elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Forums
NADRA = "nadra"
CIVIL_COURT = "civil_court"
OUT_OF_SCOPE = "out_of_scope"

_PUNJAB = {"punjab", "pb", "lahore", "punjab province"}


@dataclass(frozen=True)
class Citation:
    """One provision the advice rests on, quoted so it can be checked."""

    statute: str
    section: str
    point: str

    @property
    def reference(self) -> str:
        return f"{self.statute} s.{self.section}"


@dataclass
class Route:
    """Where to go, why, and what the advice does not decide."""

    forum: str
    headline: str
    steps: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def citation_text(self) -> str:
        """The advice as prose, for the citation verifier to check.

        Every provision named in the output goes through the same check as a
        drafted document. Guidance that cites a repealed or non-existent section
        is exactly as wrong as a pleading that does.
        """
        return " ".join(
            f"Section {c.section} of the {c.statute}: {c.point}"
            for c in self.citations
        )

    def to_dict(self) -> dict:
        return {
            "forum": self.forum,
            "headline": self.headline,
            "steps": self.steps,
            "citations": [{"statute": c.statute, "section": c.section,
                           "reference": c.reference, "point": c.point}
                          for c in self.citations],
            "caveats": self.caveats,
            "is_guidance_not_a_filing": True,
        }


_S3 = Citation(
    "Punjab Letters of Administration and Succession Certificates Act 2021", "3",
    "the Authority or a civil court may issue Letters of Administration or "
    "Succession Certificates to the legal heirs of a deceased")
_S5B = Citation(
    "Punjab Letters of Administration and Succession Certificates Act 2021", "5",
    "the Succession Facilitation Unit processes applications by summary enquiry "
    "and, in case of any factual controversy amongst the legal heirs, must "
    "decline to assess them for filing afresh before the appropriate forum "
    "under the Succession Act 1925")
_S6 = Citation(
    "Punjab Letters of Administration and Succession Certificates Act 2021", "6",
    "the application is made to the Authority by the legal heirs, in the office "
    "where the deceased ordinarily resided at the time of death or where any "
    "property or asset is located")
_S7 = Citation(
    "Punjab Letters of Administration and Succession Certificates Act 2021", "7",
    "Letters of Administration and Succession Certificates are issued in the "
    "forms prescribed by the Authority")
_S372 = Citation(
    "Succession Act 1925", "372",
    "application for a succession certificate is made to the District Judge by "
    "petition signed and verified as a plaint under the Code of Civil Procedure "
    "1908, stating the particulars in clauses (a) to (f)")
_S370 = Citation(
    "Succession Act 1925", "370",
    "a succession certificate shall not be granted for a debt or security where "
    "the right must be established by letters of administration or probate")


def _in_punjab(province: str, property_in_punjab: bool) -> bool:
    p = (province or "").strip().lower()
    return p in _PUNJAB or property_in_punjab


def advise(*, heirs_dispute: bool,
           province: str = "",
           property_in_punjab: bool = False,
           needs_probate_or_administration: bool = False) -> Route:
    """Route one succession scenario to its forum.

    `heirs_dispute` is the only fact that moves an in-Punjab case from NADRA to
    the court, because s.5(b) is the only provision that moves it.
    """
    # s.370 bites before the choice of forum: if the right has to be established
    # by probate or letters of administration, a succession certificate is the
    # wrong instrument and neither route grants one.
    if needs_probate_or_administration:
        return Route(
            forum=CIVIL_COURT,
            headline=("A succession certificate is not the right instrument here "
                      "— letters of administration or probate are needed first."),
            steps=[
                "Establish the right by letters of administration or probate.",
                "A succession certificate cannot be granted for that debt or "
                "security while s.370 applies.",
            ],
            citations=[_S370, _S3],
            caveats=["This is the one case where the answer is neither counter "
                     "as asked — the instrument itself is wrong."],
        )

    if not _in_punjab(province, property_in_punjab):
        return Route(
            forum=OUT_OF_SCOPE,
            headline=("The Punjab NADRA route does not apply — this appears to "
                      "fall outside Punjab."),
            steps=[
                "The Punjab Act 2021 is provincial. Where neither the deceased's "
                "residence nor any property is in Punjab, it does not apply.",
                "Apply to the District Judge under the Succession Act 1925.",
            ],
            citations=[_S372],
            caveats=["Check the equivalent provincial law for the province "
                     "concerned; this system holds the Punjab Act only."],
        )

    if heirs_dispute:
        return Route(
            forum=CIVIL_COURT,
            headline=("Because the heirs are in dispute, this goes to the "
                      "District Judge, not NADRA."),
            steps=[
                "NADRA's Succession Facilitation Unit will decline to assess a "
                "case with a factual controversy amongst the legal heirs.",
                "File afresh before the District Judge under the Succession Act "
                "1925.",
                "The petition must be signed and verified as a plaint under the "
                "CPC 1908 and state the particulars in s.372(a)-(f).",
            ],
            citations=[_S5B, _S372, _S3],
            caveats=[
                "The trigger is a factual controversy between heirs, not the "
                "value of the estate — a large undisputed estate still goes to "
                "NADRA.",
                "If the dispute is settled, the NADRA route reopens.",
            ],
        )

    return Route(
        forum=NADRA,
        headline=("Apply to NADRA's Succession Facilitation Unit — this does "
                  "not need a court."),
        steps=[
            "Apply to the Authority as legal heirs. The heirs may authorise one "
            "of their number, in the prescribed form, to act for all.",
            "File at the notified office where the deceased ordinarily resided "
            "at the time of death, or where any property or asset is located.",
            "Use NADRA's own prescribed form — the Act leaves the form to the "
            "Authority, so there is no court format to draft.",
        ],
        citations=[_S3, _S6, _S7],
        caveats=[
            "If a factual controversy arises between the heirs at any point, "
            "the Unit must decline and the matter goes to the District Judge "
            "under the Succession Act 1925.",
            "This is guidance on forum only. It does not assess who the legal "
            "heirs are or what shares they take.",
        ],
    )


async def advise_verified(**kwargs) -> dict:
    """Route the scenario, then verify every provision the advice cites.

    Guidance is held to the same standard as a drafted document. A route that
    cites a repealed or non-existent section is as wrong as a pleading that
    does, and it is cheaper to catch here than in front of a registrar.

    Fails OPEN: if the checker is unavailable the advice still returns, marked
    as unchecked. `verification.ran is False` is not a pass.
    """
    route = advise(**kwargs)
    out = route.to_dict()
    try:
        from app.ai.citation_verification import verify_text
        result = await verify_text(route.citation_text())
        out["verification"] = result.to_dict()
        out["verification"]["ran"] = True
    except Exception as exc:                        # never withhold the advice
        out["verification"] = {
            "ran": False,
            "reason": f"Citation verification did not run: {exc}",
            "summary": ("The provisions cited in this guidance were NOT "
                        "checked. This is not a finding that they are sound."),
            "needs_human_check": True,
            "checks": [],
        }
    return out
