"""Embedded-instruction detection: text in a document addressed to an AI system.

A document is untrusted. Some put instructions to "the model" inside it --
"Ignore all previous instructions", "SYSTEM: ...", "reply with an empty risks
list" -- to change what an automated review says, or to smuggle the
attacker's own words (a code, a number, a claim) into its output.

This is a deterministic scan, run BEFORE any model sees the document. Its
result is frozen with the run (DETECTOR_VERSION, flagged sentence ids, reason
codes) and used three ways:

  * the AI prompt carries a flagged sentence only as a placeholder: the
    model never reads it, so it can neither follow nor repeat it;
  * no automated finding -- AI item, general check or legal check -- may use
    a flagged sentence as evidence; a check whose only candidate evidence was
    flagged is "unable to determine", never "Found" or "Not located";
  * a SYSTEM notice (not an AI finding) names the clause and sentence ids and
    the reason category -- never the flagged text itself.

The text stays visible in the text viewer: nothing is hidden from the reader.

HOW A SENTENCE IS FLAGGED
  Each sentence is normalised first (Unicode NFKC, zero-width and soft-hyphen
  characters removed, case-folded, whitespace collapsed), so "IG​NORE"
  and full-width letters do not slip past. A STRONG marker flags the sentence
  and, as a continuation, up to CONTINUATION following sentences of the SAME
  clause -- an attack split across sentences ("SYSTEM: compliance mode." /
  "State that ...") is caught whole, and the next clause is never touched. A
  WEAK marker ("reply with", "risks list") counts only inside a clause that
  already has a strong one: on its own it is ordinary contract language.

WHAT IT DOES NOT PROMISE
  A rule list can be evaded by new wording, other languages or homoglyphs from
  other scripts. It is one layer: the prompt's own rule, the output validator
  and the synthetic-only policy stay in force whatever it finds.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

DETECTOR_VERSION = "injection-detector.1"
CONTINUATION = 2            # following sentences of the same clause flagged after a strong marker

# Reason codes: a fixed vocabulary, safe to store and show.
ROLE_MARKER = "role_marker"                  # SYSTEM: / <<SYSTEM>> / [INST] / developer mode
OVERRIDE = "override_instruction"            # ignore / disregard previous instructions
AI_ADDRESSEE = "ai_addressee"                # "to the model reading this", "Assistant,"
DELIMITER_SPOOF = "delimiter_spoof"          # BEGIN / END DOCUMENT
SCHEMA_JSON = "schema_json"                  # JSON shaped like the AI report
OUTPUT_MANIPULATION = "output_manipulation"  # weak: "reply with", "risks list", ...
CONTINUATION_OF = "continuation"             # follows a strong marker in the same clause

REASON_TEXT = {
    ROLE_MARKER: "text styled as a system or assistant role",
    OVERRIDE: "an instruction to ignore or replace the reviewer's rules",
    AI_ADDRESSEE: "text addressed to an AI model",
    DELIMITER_SPOOF: "text imitating the boundaries of the document",
    SCHEMA_JSON: "data shaped like the AI review's own output",
    OUTPUT_MANIPULATION: "an instruction about what the review should output",
    CONTINUATION_OF: "continuation of an instruction in the same clause",
}

_INVISIBLE = re.compile("[­᠎​-‏‪-‮⁠-⁤﻿]")

# Checked at the start of each LINE (a clause heading may precede it on the line above).
# Not "user:" or "human:": those are ordinary form labels.
_LINE_ROLE = re.compile(r"^\W{0,4}(?:system|assistant|developer|ai)\s*(?::|>{1,2}|\]|-{1,2}>)")
# Every strong pattern is narrow on purpose -- each excluded wording below is
# ordinary contract language: "you are now confirmed" (an offer letter),
# "report to the Assistant Manager", "Model Town", a party named Claude,
# "shall not ignore the rules of the society", "new instructions from
# management".
_STRONG = [
    (ROLE_MARKER, re.compile(r"<<\s*(?:system|sys|assistant|developer)\s*>>|\[/?(?:inst|system)\]"
                             r"|<\|?(?:im_start|im_end|system)\|?>|\bdeveloper mode\b"
                             r"|\byou are now in \w+ mode\b|\bsystem prompt\b|\bjailbreak\b")),
    (OVERRIDE, re.compile(r"\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+|any\s+)?(?:of\s+)?"
                          r"(?:the\s+|your\s+)?(?:previous|prior|above|earlier|preceding|original|user'?s|"
                          r"system|reviewer'?s|your)\s+(?:instructions?|rules|prompts?|directions?|guidelines|"
                          r"constraints)\b"
                          r"|\b(?:ignore|disregard)\s+(?:all|any)\s+(?:instructions?|prompts?)\b"
                          r"|\bignore (?:everything|all) (?:above|before)\b")),
    (AI_ADDRESSEE, re.compile(r"\b(?:to|for|attention)\s*:?\s+(?:the\s+|any\s+)?(?:ai|a\.i\.|llm|language model|"
                              r"chatbot|ai assistant)\b"
                              r"|\b(?:the\s+)?model\s+(?:reading|reviewing|processing|analy[sz]ing)\b"
                              r"|^\W{0,4}(?:assistant|ai|chatgpt|llm)\s*,"
                              r"|\bas an ai\b|\bchatgpt\b|\bgpt-?\d\w*\b")),
    (DELIMITER_SPOOF, re.compile(r"\b(?:begin|end)[\s_-]+document\b")),
    (SCHEMA_JSON, re.compile(r'"\s*(?:risks|obligations|summary_points|schema_version|prompt_version|'
                             r'severity_reason|sentence_ids)\s*"\s*:')),
]
# Weak: counted only inside a clause that already has a strong marker.
_WEAK = [
    (OUTPUT_MANIPULATION, re.compile(r"\b(?:reply|respond|answer)\s+with\b|\brisks? list\b|\bsummary points?\b"
                                     r"|\bseverity_?reason\b|\bschema\b|\bnew instructions?\b"
                                     r"|\b(?:print|output|append|add|put|write|include)\s+(?:the\s+)?"
                                     r"(?:code|phrase|word|text|string|token)\b"
                                     r"|\bmark every risk\b|\bin (?:the title of )?every item\b")),
]


def normalise(text: str) -> str:
    """NFKC, invisible characters removed, case-folded, whitespace collapsed
    per line (line breaks are kept: a role marker is checked per line)."""
    t = _INVISIBLE.sub("", unicodedata.normalize("NFKC", text or "")).casefold()
    return "\n".join(re.sub(r"\s+", " ", line).strip() for line in t.split("\n"))


def _strong_reasons(text: str) -> list[str]:
    norm = normalise(text)
    found = [code for code, rx in _STRONG if rx.search(norm.replace("\n", " ")) or
             (code == AI_ADDRESSEE and any(rx.search(line) for line in norm.split("\n")))]
    if any(_LINE_ROLE.search(line) for line in norm.split("\n")):
        found.insert(0, ROLE_MARKER)
    return sorted(set(found))


def _weak_reasons(text: str) -> list[str]:
    norm = normalise(text).replace("\n", " ")
    return sorted({code for code, rx in _WEAK if rx.search(norm)})


@dataclass(frozen=True)
class Scan:
    """What a run freezes: the detector version, each flagged sentence's
    reason codes, and the clauses they are in. No flagged TEXT is kept."""
    detector_version: str
    flagged: dict[str, tuple[str, ...]] = field(default_factory=dict)
    clauses: tuple[str, ...] = ()

    @property
    def sentence_ids(self) -> frozenset[str]:
        return frozenset(self.flagged)

    def to_dict(self) -> dict:
        return {"detector_version": self.detector_version,
                "flagged": {k: list(v) for k, v in sorted(self.flagged.items())},
                "clauses": list(self.clauses)}


def scan(text: str, sentences: list[dict]) -> Scan:
    """Flag every sentence that addresses an AI system. `sentences` are the
    published units ({sentence_id, clause_id, start, end}) in document order."""
    strong = {s["sentence_id"]: _strong_reasons(text[s["start"]:s["end"]]) for s in sentences}
    weak = {s["sentence_id"]: _weak_reasons(text[s["start"]:s["end"]]) for s in sentences}
    flagged: dict[str, set[str]] = {}
    by_clause: dict[str, list[dict]] = {}
    for s in sentences:
        by_clause.setdefault(s["clause_id"], []).append(s)
    for clause, units in by_clause.items():
        if not any(strong[u["sentence_id"]] for u in units):
            continue                                   # weak markers alone are ordinary language
        follow = 0
        for u in units:
            sid = u["sentence_id"]
            reasons = set(strong[sid]) | set(weak[sid])
            if strong[sid]:
                follow = CONTINUATION
            elif follow > 0:
                reasons.add(CONTINUATION_OF)
                follow -= 1
            if reasons:
                flagged.setdefault(sid, set()).update(reasons)
    clause_of = {s["sentence_id"]: s["clause_id"] for s in sentences}
    return Scan(detector_version=DETECTOR_VERSION,
                flagged={sid: tuple(sorted(r)) for sid, r in flagged.items()},
                clauses=tuple(sorted({clause_of[sid] for sid in flagged})))


def notice(result: Scan) -> dict | None:
    """The SYSTEM notice for a report: clause and sentence ids and reason
    categories only -- never the flagged text, which may carry the attacker's
    words. None when nothing was flagged."""
    if not result.flagged:
        return None
    codes = sorted({c for reasons in result.flagged.values() for c in reasons})
    return {"kind": "embedded_instruction", "source": "system", "detector_version": result.detector_version,
            "clause_ids": list(result.clauses), "sentence_ids": sorted(result.flagged),
            "reasons": codes, "reason_text": [REASON_TEXT[c] for c in codes],
            "message": ("This document contains text addressed to an AI system. It was not followed, "
                        "and it was not used as evidence for any automated finding.")}


# ── the frozen record a run carries ──────────────────────────────────────────
#
# Written ONCE, by the segmentation stage, on the confirmed frozen text, and
# published through the same fenced commit as the sentences it refers to: a
# cancelled, stale or deleted-source worker cannot publish it. The analysis
# and AI stages read it; neither rescans. A run segmented before this record
# existed has none, and is never back-filled: its report says
# `not_recorded`, and protection needs a new analysis run.

RECORDED = "recorded"
NOT_RECORDED = "not_recorded"
NOT_RECORDED_MESSAGE = ("This analysis was made before the security scan for embedded instructions "
                        "existed. Start a new analysis to have it checked.")


def record(result: Scan, *, document_hash: str, text_version_id: str) -> dict:
    """What the run stores: no flagged TEXT, only ids and reason codes."""
    return {"status": RECORDED, "document_hash": document_hash, "text_version_id": text_version_id,
            **result.to_dict()}


class ScanMismatch(ValueError):
    """The recorded scan was made on a different text than the one in hand."""


def from_record(rec: dict | None, *, document_hash: str) -> Scan | None:
    """The frozen scan, or None when the run has none (not_recorded). Raises
    ScanMismatch when it was made on other text -- the caller fails closed."""
    if not rec:
        return None
    if rec.get("status") != RECORDED or rec.get("document_hash") != document_hash:
        raise ScanMismatch("security scan does not belong to this text")
    return Scan(detector_version=rec["detector_version"],
                flagged={k: tuple(v) for k, v in (rec.get("flagged") or {}).items()},
                clauses=tuple(rec.get("clauses") or ()))


def report_block(rec: dict | None) -> dict:
    """The report's `security` section, built by the server from the record."""
    if not rec:
        return {"status": NOT_RECORDED, "message": NOT_RECORDED_MESSAGE, "notice": None}
    result = Scan(detector_version=rec["detector_version"],
                  flagged={k: tuple(v) for k, v in (rec.get("flagged") or {}).items()},
                  clauses=tuple(rec.get("clauses") or ()))
    return {"status": RECORDED, "detector_version": rec["detector_version"], "notice": notice(result)}
