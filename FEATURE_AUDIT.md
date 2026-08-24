# Attorney.AI — Feature Audit

> **Purpose:** what the repository actually implements, verified by running it — not by
> reading the code and believing it.
> **Method (2026-08-24):** all 132 API operations enumerated from the live OpenAPI schema;
> every GET exercised against a running server; deterministic engines checked against
> known-correct legal results; frontend wiring traced import-by-import; `npm run build`
> and the full `pytest` suite run to completion.
> **Supersedes:** AUDIT.md, BACKEND_AUDIT_FINDINGS.md, NEWBACKEND_ANALYSIS_REPORT.md,
> PRODUCTION_SOLUTIONS.md, STARTUP_ANALYSIS.md, LAWYER_STARTUP_ANALYSIS.md,
> USER_FEATURES.md, LAWYER_FEATURES.md, PROGRESS.md — all removed 2026-08-24.

---

## 0. The headline finding

**Construction is done. Verification is the gap.**

There is no half-built feature in this repository. There are no `TODO`s, no
`NotImplementedError`, no "coming soon" panels, and no mock data standing in for a
backend. 132 endpoints register, 41 frontend routes compile, and every functional page
imports real API functions.

What is *not* uniform is evidence. Some features have been checked against the law and
found correct. Others have never had a single row written to their collection. Both are
"built"; only the first is *verified*, and the difference is the whole point of this
document.

| | |
|---|---|
| Backend API operations | **132** |
| Frontend routes compiling | **41** (build exit 0, no warnings) |
| Backend tests | **784 passing, 0 failing** |
| GET operations exercised live | **58 — zero crashes** |
| `TODO` / `FIXME` / `NotImplementedError` in `app/` | **0** |

---

## 1. Verified correct

These were checked against ground truth, not just for a 200 response.

| Feature | Evidence |
|---|---|
| **Inheritance / faraid** | 3/3 exact, including *Umariyyatan* (mother takes 1/3 of the **remainder**) — the case naive implementations get wrong |
| **Bail checker** | PPC 302 → non-bailable, Qisas/Diyat compoundable, Court of Session. PPC 379 → non-bailable, cognizable, Magistrate |
| **Court-fee calculator** | Rs 1,000,000 money-recovery → 75,000 ad valorem; simple declaration → 500 fixed |
| **Labour dues** | 30k × 5 yrs → gratuity 150,000 + unpaid wages 60,000 |
| **Dispute intake** | 28 tests, live eligibility check correct. Its 11 records are a single-day dev batch, all one category — not organic usage — but the full path did execute: petitions generated, lawyers assigned |
| **Auth** | register → login → refresh → ws-ticket, all 200 |
| **Provenance / audit trail** | 128 records, pool filters verified null-safe |
| **RAG pipeline (mechanics)** | Full 15-node graph completed end-to-end including adaptive re-retrieval |

## 2. Built and wired, not yet exercised

Real code, real UI, real tests in most cases — but no production data has ever passed
through them.

| Feature | Ops | Note |
|---|---|---|
| Cases / tracking | 14 | 39 real cases; not end-to-end verified |
| Documents | 11 | 16 documents |
| Doc automation (drafter) | — | 10 tests, **0 drafts ever created** |
| Cause list | 6 | 3 parser tests, **0 entries, 0 watches** |
| Citator / case law | 4 | 502 judgments indexed; ranking tested, API not |
| Payments | 7 | 5 tests, **0 payments**; see §5 |
| Appointments | 8 | **no tests**, 0 rows — KYC guard verified firing |
| Agreements | 4 | **no tests** |
| Billing / subscriptions | 4 | **no tests**, 0 subscriptions |
| Admin console | 12 | 7 routes; KYC approval is the load-bearing part |
| Lawyers / matching, notifications, voice | 8 | thin or no dedicated tests |

~42 endpoints have no dedicated test. That is a confidence gap, not a functionality gap —
but it is the largest single item of remaining work, and it needs no API key, no credit
and no external party.

## 3. Blocked on external dependencies

| Feature | Blocker |
|---|---|
| AI legal chat (client) | **No working LLM provider.** Groq key invalid (401), Gemini unset, OpenRouter balance exhausted. Local Ollama works but is CPU-only at ~15.7 min/turn |
| AI legal research (lawyer) | same |
| Payments (production) | **Safepay webhook signature unverified** against live docs — see §5 |

## 4. Removed as out of scope (2026-08-24, commit `27416bd`)

- **POA / attestation desk** — 26 endpoints, zero recorded usage. POA lifecycle,
  apostille paths, OPPPA guidance, public verify-token page.
- **WhatsApp Business integration** — 5 endpoints; required Meta Business verification
  that was not going to arrive. The `wa.me` **share links** in cause-list and hearing
  cards are unrelated and remain.

Property-dispute intake was **kept** and moved to `routes/disputes.py`. It shared the
`/overseas` prefix only because both derive from the same statute; it has 38 tests and a
demonstrated end-to-end path behind it. Its legal model was subsequently checked against
the Punjab Gazette and corrected — see §5.5.

## 5. Known defects

1. **Safepay webhook signature is a guess.** HMAC-SHA256 over the raw body with
   `x-sfpy-signature`, `compare_digest`, fails closed on a missing secret — all sound,
   but unverified against live documentation. A wrong scheme either rejects every real
   settlement or accepts forged ones. **This is the only item genuinely blocking
   production.**
2. **The grounding gate does not discriminate.** `is_grounded` returns `True` over
   passages with `bm25_confidence = 0.0` — zero lexical overlap with the question. A
   three-state veto is proposed and tested in `app/ai/grounding.py`, deliberately
   **not wired in**. See [FAILURE_CASE_001.md](FAILURE_CASE_001.md).
3. **Arbitration cannot lower confidence.** `arbitrate()` selects
   `max(candidates, key=confidence)`, so no signal is capable of counting *against* an
   answer. Disagreement is structurally impossible.
4. **~35 open UI issues**, mostly responsive-layout. Both Critical items are fixed.
5. **The client↔lawyer engagement flow has no consent step and no exit.** A lawyer
   sets the fee unilaterally at acceptance; `accepted` is absorbing for both parties
   and only an admin can end the relationship. The money half is closed (`8ef0dca` —
   billing now requires a signed engagement letter), the sequence itself is not. The
   redesign is scoped in [ENGAGEMENT_REDESIGN.md](ENGAGEMENT_REDESIGN.md) and resolves
   this together with the missing close-out and the invisible pricing.
6. **No refund path or platform dispute resolution.** `REFUNDED` is declared and
   unreachable; nothing sets it. Deliberately held until the engagement redesign ships.
7. **Punjab Special Court operational status is unverified**, and the property-dispute
   feature is held from real-user exposure until it resolves. This is an external,
   human-only dependency — the designating instrument is an administrative notification,
   not a gazetted Act, so no amount of code will settle it. See
   [OPEN_DEPENDENCY_001.md](OPEN_DEPENDENCY_001.md). Everything else on that feature was
   verified against the Punjab Gazette and corrected.

## 6. What to do next, in order

1. **Tests for the ~42 untested endpoints.** Closes the largest gap; needs nothing from
   anyone else.
2. **Verify the Safepay signature** against live docs, or cut payments to mock-only.
3. **Get a working LLM provider** — a free Groq key unblocks both AI features.
4. **Recruit two annotators** ([ANNOTATOR_ONBOARDING.md](ANNOTATOR_ONBOARDING.md)) — the
   200-label eval set is what would let the grounding veto in §5.2 be calibrated rather
   than guessed.

## 7. Companion documents

| Document | What it is |
|---|---|
| [README.md](README.md) | Setup and orientation |
| [backend/RUNBOOK.md](backend/RUNBOOK.md) | Operational procedures |
| [DIAGRAMS.md](DIAGRAMS.md) | 16 sequence / state diagrams |
| [LABELLING_PLAN.md](LABELLING_PLAN.md) | What is labellable, and why warmup is parked |
| [ANNOTATION_PROTOCOL.md](ANNOTATION_PROTOCOL.md) | How an annotator judges a turn |
| [ANNOTATOR_ONBOARDING.md](ANNOTATOR_ONBOARDING.md) | Recruiting the two annotators |
| [FAILURE_CASE_001.md](FAILURE_CASE_001.md) | A wrong citation that passed every gate |
| [OPEN_DEPENDENCY_001.md](OPEN_DEPENDENCY_001.md) | Open external ask: is the Punjab Special Court sitting? |
| [ENGAGEMENT_REDESIGN.md](ENGAGEMENT_REDESIGN.md) | Next feature: two-step engagement flow with real exits |
| [UIISSUES.md](UIISSUES.md) | Frontend audit |
| [INTAKE_AI_APPROACH.md](INTAKE_AI_APPROACH.md) | AI pipeline design + viva reference |
| [LAWYER_MATCHING_PLAN.md](LAWYER_MATCHING_PLAN.md) | Matching design |
| [SECURITY.md](SECURITY.md) | Security posture |
