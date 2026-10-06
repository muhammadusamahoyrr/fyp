"""The SIMULATED AI provider for the Document Analyzer (FYP demo; never deployed).

Selected only by explicit configuration -- `ANALYZER_AI=true` together with
`ANALYZER_AI_PROVIDER=simulated` (default: groq). Nothing switches to it at
runtime, so it can never be a fallback for a Groq failure, and a Groq
configuration never reaches it.

While selected:
  * an in-process transport answers instead of a model: no network, no key.
    The client refuses any other transport (ai_client.py);
  * every output and receipt names it honestly: provider `simulated`, model
    `demo-simulated-1`, label "Simulated AI response — demo mode". No Groq
    identity is claimed;
  * everything else is the normal pipeline: synthetic-only sources,
    lawyer-only owner-scoped access, evidence selection, masking, the
    lawyer's preview approval and its fingerprint, the response validators,
    fenced persistence and the processing receipt;
  * readiness (ai_config.problems) still requires synthetic-only, and keeps
    the demo's database rule: the database must be on this machine (never a
    hosted cluster). Changing that rule is an owner decision, not a default.

The answers are built only from the request actually sent: they cite its own
sentence/clause ids (or question ids), quote nothing that is not in it, and
still pass the engine's validators. They are placeholders, not analysis.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx

PROVIDER = "simulated"
MODEL = "demo-simulated-1"
POLICY_ID = "DEMO-SIMULATION"
LABEL = "Simulated AI response — demo mode"
#: Where the client "posts" while simulated. `.invalid` can never resolve
#: (RFC 2606), so logs never name a real provider and nothing could reach one.
URL = "http://simulated.invalid/v1/chat/completions"
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def local_database(mongodb_url: str) -> bool:
    """True only for a plain mongodb:// URL whose every host is this machine
    (never mongodb+srv, which is always a hosted cluster)."""
    try:
        parsed = urlparse(mongodb_url or "")
    except ValueError:
        return False
    if parsed.scheme != "mongodb":
        return False
    hosts = [h.rsplit(":", 1)[0].strip("[]").lower() for h in parsed.netloc.split("@")[-1].split(",")]
    return bool(hosts) and all(h in _LOOPBACK or h.startswith("127.") for h in hosts)


class SimulatedTransport(httpx.MockTransport):
    """The only transport the client accepts while the simulated provider is
    selected, and one it refuses for any other provider."""


def transport(handler=None) -> SimulatedTransport:
    """`handler` lets a test observe the request; it still gets the simulated answer."""
    return SimulatedTransport(handler or simulated_response)


def contract() -> dict:
    """What every AI output and receipt records while the simulation is selected."""
    return {"provider": PROVIDER, "model": MODEL, "fallback": None, "policy_id": POLICY_ID,
            "zdr": {"status": "not_applicable", "verified_on": None}, "synthetic_only": True,
            "simulated": True, "label": LABEL}


# ── the simulated answers ───────────────────────────────────────────────────

_LINE = re.compile(r"^\[(?P<sid>s\d+)\|(?P<cid>c\d+)\] (?P<body>.*)$")
_TOKEN = re.compile(r"\[NAME_\d{1,4}\]")
_DEADLINE = re.compile(r"\b(?:within|before|by|no later than)\s+[^.,;]{1,40}?\b(?:days?|weeks?|months?|years?)\b",
                       re.I)
_BLANK = re.compile(r"_{3,}|\[\s*\]|\bTBD\b", re.I)
_ROLE = re.compile(r"\b[Tt]he (?P<party>[A-Z][a-z]+(?: [A-Z][a-z]+)?) (?=shall|must|will)")
_DUTY = re.compile(r"\b(?:shall|must|will|agrees? to|is to)\b", re.I)


def _report(prompt: str) -> dict:
    from app.services.analyzer import ai_report
    lines = []
    for raw in prompt.split("\n"):
        m = _LINE.match(raw)
        if m and not m.group("body").startswith(("(heading)", "[withheld")):
            lines.append(m)
    obligations, risks, points = [], [], []
    # Sentences stating a deadline first, so the demo shows one surviving masking.
    for m in sorted(lines, key=lambda m: _DEADLINE.search(m.group("body")) is None):
        party = _TOKEN.search(m.group("body")) or _ROLE.search(m.group("body"))
        if party and _DUTY.search(m.group("body")) and len(obligations) < 2:
            deadline = _DEADLINE.search(m.group("body"))
            obligations.append({
                "party": party.group("party") if party.re is _ROLE else party.group(0),
                "action": "Simulated item: perform what this sentence requires (demo mode).",
                "deadline_status": "stated" if deadline else "not_stated",
                "deadline": deadline.group(0) if deadline else None, "condition": None,
                "sentence_ids": [m.group("sid")], "clause_id": m.group("cid")})
    for m in lines:
        if _BLANK.search(m.group("body")) and len(risks) < 1:
            risks.append({"category": "missing_detail", "title": "Simulated item: a value is left blank",
                          "explanation": "Demo mode: this sentence has a blank to be filled in.",
                          "severity": "medium", "severity_reason": "Simulated demo severity.",
                          "sentence_ids": [m.group("sid")], "clause_id": m.group("cid")})
    if lines:
        first = lines[0]
        points.append({"point": "Simulated summary point (demo mode): the document opens here.",
                       "sentence_ids": [first.group("sid")], "clause_id": first.group("cid")})
    return {"schema_version": ai_report.SCHEMA_VERSION, "prompt_version": ai_report.PROMPT_VERSION,
            "risks": risks, "summary_points": points, "obligations": obligations}


def _hypothesis(prompt: str) -> dict:
    from app.services.analyzer.hypotheses import review
    return {"schema_version": review.SCHEMA_VERSION, "prompt_version": review.PROMPT_VERSION,
            "reviews": [{"question_id": q, "signal": "supports",
                         "explanation": "Simulated review signal (demo mode)."}
                        for q in re.findall(r"^## item (\w+)$", prompt, re.M)]}


def simulated_response(request: httpx.Request) -> httpx.Response:
    """The in-process 'provider': answers only from the request it received."""
    body = json.loads(request.content)
    prompt = next((m["content"] for m in body["messages"] if m.get("role") == "user"), "")
    answer = _hypothesis(prompt) if "## item " in prompt else _report(prompt)
    return httpx.Response(200, headers={"x-request-id": "demo-simulated"},
                          json={"model": MODEL, "id": "demo-simulated", "usage": {"total_tokens": 0},
                                "choices": [{"finish_reason": "stop",
                                             "message": {"content": json.dumps(answer)}}]})
