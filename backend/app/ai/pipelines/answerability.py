"""Can a statutory corpus answer this question AT ALL?

This is not topicality, and it is the gap that made abstention fail. The
pipeline had two query-side filters and neither covers it:

  * gatekeeper_node  — is this an attack on the assistant?
  * triage_node      — is this about law at all?

Both pass "What is the current stamp duty rate for property transfer in
Gilgit-Baltistan?" and "How many cases were pending in the Lahore High Court in
2019?", because both ARE legal questions. Retrieval then returns real statutes
that share their vocabulary, every similarity signal reads as moderate, and the
system answers confidently from law that does not contain the answer.

No confidence threshold can fix that. Measured on this corpus after the scoring
signals were repaired, the unanswerable queries score 0.273-0.412 and the
answerable ones 0.309-0.662 — overlapping ranges, so any single cut trades false
refusals for false answers. The distinction is not one of degree. It is that
these questions ask for a KIND of fact statutes never state:

  a periodically-notified rate   statutes delegate it to a schedule or SRO
  a court statistic             nothing in the corpus is a case count
  a personal or case-specific    the corpus has no per-user data at all
  a prediction of outcome        no statute states how a case will end

Deciding this from the query is deterministic, costs nothing, and is testable —
all three properties the LLM grader lacks on the fast tier available here.

Deliberately narrow. A false positive refuses a question the system COULD have
answered, which is worse for a legal assistant than an unhelpful answer is,
because the user has no signal that the refusal was a mistake. Every pattern
below requires an explicit marker of the unanswerable fact type, not merely a
topic word: "the rate of interest under section X" stays answerable, while "the
CURRENT rate" does not.
"""
from __future__ import annotations

import re
from typing import NamedTuple, Optional


class Unanswerable(NamedTuple):
    """Why the corpus cannot answer, and what to tell the user instead."""
    kind:     str   # stable identifier for logging and evaluation
    reason:   str   # one line, shown to the user
    redirect: str   # where the answer actually lives


# Markers that a question asks for the value in force TODAY, which a statute
# cannot state: rates and fees are set by schedules, finance acts and SROs that
# are amended far more often than the parent act.
_CURRENCY_MARKER = r"(current|latest|today'?s?|present|now|up[- ]to[- ]date|this year|20[2-9]\d)"
_MONEY_NOUN      = r"(rate|rates|fee|fees|charge|charges|duty|tariff|tax|stamp duty|price|cost|amount payable)"

_RULES: list[tuple[re.Pattern, Unanswerable]] = [
    (
        re.compile(rf"\b{_CURRENCY_MARKER}\b[^.?]{{0,40}}\b{_MONEY_NOUN}\b", re.IGNORECASE),
        Unanswerable(
            kind="live_rate",
            reason=("Rates, fees and duties are fixed by schedules and government "
                    "notifications that change more often than the Act itself, so "
                    "I can't give you a current figure from the statute text."),
            redirect=("the relevant provincial Board of Revenue or the current "
                      "Finance Act schedule"),
        ),
    ),
    (
        re.compile(rf"\b{_MONEY_NOUN}\b[^.?]{{0,40}}\b{_CURRENCY_MARKER}\b", re.IGNORECASE),
        Unanswerable(
            kind="live_rate",
            reason=("Rates, fees and duties are fixed by schedules and government "
                    "notifications that change more often than the Act itself, so "
                    "I can't give you a current figure from the statute text."),
            redirect=("the relevant provincial Board of Revenue or the current "
                      "Finance Act schedule"),
        ),
    ),
    (
        # The lookahead is load-bearing. Without a caseload verb this fired on
        # "How many days do I have to file an appeal?" — a limitation-period
        # question the corpus answers well. "How many <legal noun>" alone is not
        # a statistic; "how many cases were PENDING" is.
        re.compile(r"\bhow many\b"
                   r"(?=[^.?]*\b(pending|filed|registered|disposed|decided|"
                   r"instituted|adjudicated|convicted)\b)"
                   r"[^.?]{0,60}\b(cases?|petitions?|appeals?|suits?|"
                   r"convictions?|acquittals?|FIRs?|complaints?)\b",
                   re.IGNORECASE),
        Unanswerable(
            kind="court_statistic",
            reason=("That's a court statistic. My sources are statutes and reported "
                    "judgments, which don't include case counts or pendency figures."),
            redirect="the Law and Justice Commission of Pakistan's judicial statistics",
        ),
    ),
    (
        re.compile(r"\b(pendency|backlog|disposal rate|clearance rate|conviction rate)\b",
                   re.IGNORECASE),
        Unanswerable(
            kind="court_statistic",
            reason=("That's a court statistic. My sources are statutes and reported "
                    "judgments, which don't include case counts or pendency figures."),
            redirect="the Law and Justice Commission of Pakistan's judicial statistics",
        ),
    ),
    (
        # Contact details only. "fee" was here and caught "the procedure to
        # recover my lawyer's fee", which is a question about the law of costs.
        re.compile(r"\bmy\s+(lawyer|advocate|counsel|attorney)'?s?\s+"
                   r"(phone|mobile|number|contact|address|email)", re.IGNORECASE),
        Unanswerable(
            kind="personal_record",
            reason=("I don't have access to your personal records or your lawyer's "
                    "contact details."),
            redirect="your case file, or the Directory tab if you engaged them here",
        ),
    ),
    (
        re.compile(r"\b(status|next date|hearing date|result)\s+of\s+my\s+(case|suit|"
                   r"petition|appeal|FIR)\b", re.IGNORECASE),
        Unanswerable(
            kind="personal_record",
            reason=("I can't look up an individual case's status — I work from "
                    "statutes and reported judgments, not court cause lists."),
            redirect="the Case Tracking tab, or the relevant court's own cause list",
        ),
    ),
    (
        re.compile(r"\b(will i (win|lose)|are my chances|what are my odds|"
                   r"chances of (winning|success)|guarantee)\b", re.IGNORECASE),
        Unanswerable(
            kind="outcome_prediction",
            reason=("No statute or judgment states how a particular case will be "
                    "decided, so predicting the outcome isn't something I can ground "
                    "in law."),
            redirect="what the law requires you to prove, which I can explain",
        ),
    ),
]


def check(query: str) -> Optional[Unanswerable]:
    """Return why the corpus cannot answer this question, or None if it might.

    None is not a promise that an answer exists — it means this check found no
    reason to rule one out, and the confidence signals decide from there.
    """
    text = (query or "").strip()
    if not text:
        return None
    for pattern, verdict in _RULES:
        if pattern.search(text):
            return verdict
    return None
