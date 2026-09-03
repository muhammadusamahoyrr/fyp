# Remediation Plan — Intake, Drafting, Analysis, Agreements

**Scope:** legal intake · document drafting · document analysis · agreement generation
**Branch:** `feat/selective-abstention-and-audit-trail` @ `2b8186b` (baseline) → **merged to `master` @ `430791a`**
**Shipped:** 2026-08-29. 10 commits, pushed to `github.com/muhammadusamahoyrr/fyp`, master fast-forwarded
`977bad5..430791a`. Remote default branch is **`master`**, not `main`.
**Baseline suite:** 1274 passed / 1 failed / 1300 collected (`pytest tests/ -m "not integration and not llm"`)
**Status:** 18 of 19 fixes **APPLIED** (1–9, 11–19). Fix 6′ decided: flag only, no code change.
**ONE ITEM REMAINS OPEN: [Fix 10](#fix-10--encode-rules-for-the-types-that-reach-a-court), waiting on
legal review.** Nothing in the code is blocked on engineering.
**After batch 2 + fix 18:** 1414 passed / 0 failed / 44 deselected · 1458 collected. Baseline was
1274 passed / 1 failed / 25 deselected · 1300 collected.

Every defect below was **reproduced by running the code**, not inferred from reading it. Reproduction
commands are in [Appendix A](#appendix-a--reproduction-commands). Every "shared / isolated" claim comes
from grepping the callers, listed inline.

---

## START HERE NEXT SESSION

**This work is done and merged.** Do not re-audit these four modules or re-apply these fixes.

| | |
|---|---|
| **Open, blocked on a lawyer** | [Fix 10](#fix-10--encode-rules-for-the-types-that-reach-a-court) — statutory particulars for `dispute_petition`, `bail_application`, `petition_22a`, `fir_application`, `complaint_154_3`. Code shape settled; the content is legal drafting. **Do not draft it in code.** |
| **Open, blocked on a lawyer** | [Fix 18](#fix-18--stop-shipping-us-contract-templates) full step — real Pakistani agreement template bodies. The interim withdrawal IS shipped and enforced; only the replacement wording is missing. |
| **Known, deliberately out of scope** | `agreement_repo.set_status` is an unconditional `$set` — every guard lives in the service, so a future caller bypasses them. |
| **Known, deliberately out of scope** | Simultaneous final signatures can both observe `all_signed=True` → duplicate `AGREEMENT_EXECUTED` in-app notifications (append-only, new `_id` each time). DB state is idempotent; the notification is not. No email/webhook/document-generation fires on that transition. |
| **Not fixed, still latent** | `test_rate_limit_fails_open::test_healthy_storage_still_limits` passes now only because adding test files changed collection order. It was order-dependent before and still is. |
| **Open, deliberately deferred** | **99 test-fixture accounts remain in the production database** — 8 of 9 admin accounts and 91 of 103 client accounts. Lawyer fixtures are at 0 (`purge_test_fixtures.py` cleared 24 on 2026-09-01, but it queries `role: "lawyer"` only). Extending it needs the cascade rules rethought: a fixture *client* has cases and engagements pointing at real lawyers, so the counterparty check that made the lawyer purge safe does not transfer unchanged. Deferred until after the FYP demo. |
| **Deferred to pre-launch (decided 2026-09-01)** | **No rate limit or quota on any AI endpoint.** All 8 routes in `api/v1/routes/ai.py` authenticate but never limit; there is no usage counter anywhere in `app/`; the free tier advertises "5 AI chat queries / month" (`subscription_service.py:30`) and nothing enforces it. `ai_query` also caps neither input nor history length, and the `chat_socket.py` WebSocket loop needs an application-level check since slowapi decorators do not cover WS. Not urgent while the app is unlaunched and only run locally for demos — the exposure requires a reachable deployment. **Must be fixed before the API is exposed to anyone.** Scaffolding is ready: `limiter` (`core/rate_limit.py:52`) is already wired in `main.py:164` and used in `auth.py`/`voice.py`, and `subscription_service.get_tier()` / `.is_paid()` already exist. |
| **Deferred to pre-launch (decided 2026-09-01)** | **Rotate the 20 KYC-verified lawyer passwords.** Deferred because the demo needs working logins and nothing is public-facing. See the row below for detail. |
| **Open, lower severity** | **20 KYC-verified lawyer accounts still use a password that was public on GitHub** (the 8 original seeds and the 12 demo-roster accounts). The admin credentials were rotated on 2026-09-01; these were not, because the demo needs working logins. Rotate before any public deployment — anyone could otherwise sign in as a verified advocate. ~80 fixture client accounts share the same problem and are covered by the row above. |
| **Known, self-correcting** | `kyc_status` (`6fb3d30`) treats a missing value as pending, so lawyers rejected **before** that commit reappear in the KYC queue once — nothing had recorded the rejection. It self-corrects the next time an admin rejects them, and a one-off backfill setting `kyc_status: "rejected"` where `kyc_rejection_reason` is non-null would close it if it is ever worth doing. Not written. |

**Environment:** `nh3==0.3.7` is a new backend dependency — reinstall `backend/requirements.txt` or the
backend will not import. No new env vars, no config changes, no frontend dependencies.

**Test counts:** `-m "not integration and not llm"` → 1414 passed / 44 deselected. With Mongo running,
`-m "not llm"` → all 1458. 29 of the 44 integration tests were added by this work and skip cleanly
without Mongo, so a green default run does **not** mean the Mongo-only guarantees were exercised.

**Moved files:** `backend/test_{chat_ws,full_e2e,intake_e2e,lawyer_matching,pipeline_nodes}.py` are now
`backend/scripts/manual_smoke/smoke_*.py`. They were never collected and contain no `test_*` functions.

---

## How to read this

| Label | Meaning |
|---|---|
| **BROKEN** | Verified wrong or unsafe output today |
| **INCOMPLETE** | Feature exists, a path or edge case is unhandled |
| **RISKY** | Works today, rests on an undocumented or unguarded assumption |
| **Isolated** | No other module shares the file or function — safe to batch |
| **Shared** | Other callers depend on it — needs sign-off before it ships |

Sizes are relative: **S** = under an hour, **M** = half a day, **L** = multi-day or needs a lawyer.

---

## What changed since the previous pass

Three findings this round that earlier passes missed. The first is the most serious thing found in the
whole engagement.

**1. PDF field text is parsed as ReportLab markup — local file read + guaranteed generation failure.**
`pdf_generator.P()` hands field values straight to `Paragraph()` with no escaping. ReportLab's
`Paragraph` implements a mini-markup language including `<img src="...">`, which opens local paths.
Reproduced: `fields={"facts": '<img src="C:/Windows/win.ini"/>'}` → `UnidentifiedImageError` naming the
file it opened. `DocumentGenerate.fields` is `dict[str, Any]` with no validation, so an authenticated
user supplies these values directly — no LLM in the loop. Now **fix 5**.

**2. Agreement inputs are unbounded.** `SignatureSubmit.signature_data`, `AgreementCreate.title` and
`body_html` carry no `max_length`, while `save_draft` enforces `_MAX_DRAFT_CONTENT = 300_000` and
`QuickNoticeRequest.text` enforces `max_length=3000`. The codebase knows to bound inputs; agreements
were missed. Now **fix 17**.

**3. Agreements cannot be declined.** `AgreementStatus.CANCELLED` exists and the UI already labels it
"Rejected", but nothing in the agreement path ever writes that value. Now **fix 16**.

**Checked and dismissed:** `app/services/document_service.py.backup-20260825-225827` — a 34 KB stale
copy of a security-relevant file inside the package. Gitignored, untracked, not importable through that
extension; the diff shows only the older pre-`as_of` version. Delete it, but it is not a defect.

---

## Module 1 — Legal intake

The grounding gate is a boolean asked to carry three meanings. It defaults to the safest-sounding one,
and the caller discards it either way.

### Fix 1 — Make "could not verify" distinct from "verified grounded"

> **STATUS: DONE — shipped in `6828261`, merged to `master`.** Everything below is the
> reasoning that produced the change, kept as a record. It is NOT a list of work to do.

`BROKEN` · `Isolated` · **S**

`is_grounded` conflates *verified grounded*, *verified ungrounded* and *never checked*, and the
empty-evidence case resolves to the first.

`backend/app/ai/nodes/intake_hallucination_node.py:32-33`

```diff
-    if not answer or not chunks:
-        return {"is_grounded": True}
+    if not answer:
+        return {"is_grounded": False, "grounding_status": "no_answer"}
+
+    # No evidence is not grounding. It is the one case where the judge cannot
+    # run at all, so it must not report the judge's pass verdict.
+    if not chunks:
+        return _unverified(answer, "no_evidence_retrieved")
```

Add one helper that appends `_CAUTION` and returns
`{"is_grounded": False, "grounding_status": …, "answer": …}`, then route the three early returns and
both `except` blocks through it.

Statuses: `grounded`, `ungrounded`, `no_evidence_retrieved`, `no_actions`, `unparseable`, `judge_failed`.

> **Why this cannot loop.** The intake graph does not use `route_after_hallucination` —
> `supervisor.py:180` wires `intake_hallucination_node → END` unconditionally. The chat graph's retry
> loop is a different edge and is untouched.

### Fix 2 — Stop discarding the verdict at the call site

> **STATUS: DONE — shipped in `6828261`, merged to `master`.** Everything below is the
> reasoning that produced the change, kept as a record. It is NOT a list of work to do.

`BROKEN` · `Isolated` · **S**

Fix 1 is inert without this. `backend/app/services/intake_service.py:434`

```diff
     result = await intake_graph.ainvoke(state)
-    return json.loads(result["answer"])
+    analysis = json.loads(result["answer"])
+    analysis["grounded"] = bool(result.get("is_grounded"))
+    analysis["grounding_status"] = result.get("grounding_status", "unverified")
+    return analysis
 except Exception:
     return {
         "summary": "AI structuring unavailable — case created successfully.",
+        "grounded": False,
+        "grounding_status": "pipeline_failed",
         ...
```

**Carrier changes:** add both fields to `AIStructuredCase` (`app/models/intake.py:9`) and the seed dict
(`intake_service.py:97`). `IntakeDetailResponse.ai_structured_case` is already `dict | None`
(`schemas/intake.py:59`), so the API surfaces them with no schema edit.

### Fix 3 — Render the status where the analysis is read

> **STATUS: DONE — shipped in `561dfd9`, merged to `master`.** Everything below is the
> reasoning that produced the change, kept as a record. It is NOT a list of work to do.

`INCOMPLETE` · `Isolated` · **S**

Three render sites: review pane `ModIntake.jsx:1189-1215`, print export `ModIntake.jsx:159-164`,
sidebar `ModIntake.jsx:1292`. Where `grounding_status !== "grounded"`, show the caveat as its own line
rather than letting it hide inside a paragraph of prose.

### Fix 4 — Test the node

> **STATUS: DONE — shipped in `6828261`, merged to `master`.** Everything below is the
> reasoning that produced the change, kept as a record. It is NOT a list of work to do.

`INCOMPLETE` · `Isolated` · **S**

No `tests/` file covers either intake node, and `test_intake_e2e.py` sits at `backend/` root outside
`testpaths`, so it is never collected. Five of six branches return before the LLM call — no model, no
Mongo needed.

New `tests/test_intake_grounding.py` (~8 tests): zero chunks → not grounded + caution present;
unparseable answer → not grounded; empty actions → `no_actions`; caution appended exactly once;
`grounding_status` present on every return path.

---

## Module 2 — Document drafting

Three generation paths with three levels of checking. One parses user text as markup and opens local
files; one emits a court-formatted empty pleading; one streams to a lawyer's editor unchecked.

### Fix 5 — Escape field text before it reaches ReportLab

> **STATUS: DONE — shipped in `0a129e6`, merged to `master`.** Everything below is the
> reasoning that produced the change, kept as a record. It is NOT a list of work to do.

`BROKEN` · **Security** · `Isolated` · **S**

**The most severe item in this plan, and a one-function fix.**

`pdf_generator.P()` (`backend/app/services/pdf_generator.py:97-112`) ends in
`return Paragraph(text, style)`. ReportLab's `Paragraph` parses a mini-markup language. Field values
arrive unescaped.

Two verified symptoms, one root cause:

**a) Local file read.** ReportLab supports `<img src="...">` inside a paragraph and opens the path.

```
fields = {"facts": '<img src="C:/Windows/win.ini" width="10" height="10"/>'}
→ UnidentifiedImageError: fileName='C:/Windows/win.ini' identity=[ImageReader@...]
```

It raised only because `win.ini` is not decodable as an image — **it opened the file first**. Point it
at a real image on the server (another user's evidence upload under `uploads/evidence/`, for instance)
and the image is embedded into the PDF the requester then downloads. Relative paths resolve against the
process CWD.

The route is direct, with no LLM involved: `DocumentGenerate.fields` is `dict[str, Any] = {}`
(`schemas/document.py:19`) and both `/documents/generate` and `/documents/quick-notice` pass the
user-supplied dict straight through.

**b) Denial of generation on ordinary legal text.** An unclosed `<` raises:

```
fields = {"facts": "Damages of Rs 5,00,000 <not a tag"}
→ ValueError: paraparser: syntax error: parse ended with 1 unclosed tags
```

`generate_document` catches it, marks the document failed, and surfaces the raw ReportLab internals to
the user as `"PDF generation failed: paraparser: syntax error…"`. A client writing *"the defendant paid
<50% of what was owed"* cannot generate their document and gets an incomprehensible error.

Markup is also silently **interpreted** rather than printed: `Plaintiff <b>Ali</b> claims <font
color=red>damages</font>` renders as `Plaintiff Ali claims damages`, so field content can inject
formatting into a legal PDF.

**Fix — one choke point, and the Urdu path is preserved:**

```diff
+from xml.sax.saxutils import escape as _xml_escape
+
 def P(text, style):
     text = "" if text is None else str(text)
+    # Paragraph parses a markup language: <img src> opens local files and an
+    # unclosed '<' raises. Field text is data, never markup.
+    text = _xml_escape(text)
     if _ARABIC_RE.search(text) and "<" not in text:
         ...
     return Paragraph(text, style)
```

> **Note the existing hint.** The Urdu branch is already guarded by `and "<" not in text` — someone knew
> markup passes through. Escaping first makes that guard redundant but harmless; keep it.
>
> **Check before shipping:** grep for callers that pass *intentional* markup to `P()` (e.g. `<b>` in a
> heading built by the generator itself). Those need `Paragraph()` directly, or a `raw=True` parameter.
> `pdf_generator.py` is 1,535 lines with ~20 template builders — this is the one part of the fix that
> needs care rather than a blind find-and-replace.

### Fix 6 — Stop generating a pleading the system knows is empty

> **STATUS: DONE — shipped in `27964e1`, merged to `master`.** Everything below is the
> reasoning that produced the change, kept as a record. It is NOT a list of work to do.

`BROKEN` · `Isolated` · **S**

`generate_pdf("plaint_civil", {})` returns a 2,048-byte, one-page PDF:

```
IN THE CIVIL COURT
 SUIT NO. _______ / 2026
PLAINTIFF / DEFENDANT
 PLAINT
FACTS OF THE CASE          ← empty
RELIEF SOUGHT              ← empty
Date: 29 August 2026
______________________
Plaintiff
```

Not a blank file — a structurally complete court document missing exactly its substance. Stored with
`status: "generated"`, which then satisfies the `status != "generated"` gate in `submit_for_review`
(`document_service.py:566`), so it can be sent to a lawyer as a real submission.

**Two paths reach it, and the common one is not the crash:**

1. **Extraction fails.** `extract_fields` swallows the exception and returns `fields = {}`
   (`document_service.py:387-389`). `generate_document`'s `if not fields` re-extracts, fails again,
   proceeds.
2. **Extraction succeeds on a vague description.** `_EXTRACT_SYSTEM` instructs the model to *"use empty
   string for any field you cannot determine"* (`document_service.py:158`), so it correctly returns
   `{"court_name":"", "facts":"", …}` — a **truthy** dict. The `if not fields` guard never fires.

**The check already exists and is already correct.** Passing those fields to `check_pleading` returns
`checked=True, complete=False, satisfied=0, missing=9`. The system computes that all nine CPC
particulars are absent, stores that verdict on the document, and writes the PDF anyway.

```diff
+    # `fields` can be truthy and still say nothing: the extraction prompt tells
+    # the model to return "" for anything it cannot determine.
+    if not any(str(v).strip() for v in fields.values()):
+        raise AppValidationError(
+            "Not enough detail in the case description to fill this document. "
+            "Add more detail, or fill the fields in yourself and resubmit.")
```

This mirrors the guard `/documents/quick-notice` already has (`documents.py:124-126`). Same failure,
guarded on one drafting route and not the other.

**Optional stronger gate (needs a decision):** refuse to mark a document `generated` when
`compliance.satisfied == 0` for the four covered template types. That contradicts `pleading_rules`'
deliberate advisory posture (`pleading_rules.py:520`), so it is a policy call — but "zero of nine
particulars present" is not a lawyer exercising judgement, it is a failed extraction.

### Fix 7 — Sanitise draft content where it is written

> **STATUS: DONE — shipped in `32ed137`, merged to `master`.** Everything below is the
> reasoning that produced the change, kept as a record. It is NOT a list of work to do.

`BROKEN` · **Security** · `Shared` · **M**

`save_draft` validates length and ownership but never content
(`document_service.py:739-763`), and `DocAutomationPage.jsx:721` renders `draft.content` through
`dangerouslySetInnerHTML`. Server-side is the right choke point: one function guards every present and
future consumer.

```diff
 # requirements.txt — bleach is deprecated; nh3 is the maintained successor
+nh3==0.2.18
```

```python
_ALLOWED_TAGS = {"p","br","strong","b","em","i","u","ul","ol","li",
                 "h1","h2","h3","h4","blockquote","table","thead",
                 "tbody","tr","td","th","hr","span","div"}

def _clean_html(raw: str) -> str:
    """Strip scripts/handlers from editor HTML. Applied on write AND read:
    write protects new drafts, read covers rows stored before this landed."""
    return nh3.clean(raw, tags=_ALLOWED_TAGS, attributes={"*": {"style"}})
```

Apply in `save_draft` on both the insert and update branches, and in `_draft_out`
(`document_service.py:733`) so legacy rows are cleaned on the way out without a migration.

> **Needs sign-off:** adds a dependency and is lossy by design — a draft containing a tag outside the
> allowlist loses it. Confirm the allowlist covers what the editor actually emits, or the first lawyer
> to use a table will lose it.

### Fix 8 — Escape case data before it becomes markup

> **STATUS: DONE — shipped in `561dfd9`, merged to `master`.** Everything below is the
> reasoning that produced the change, kept as a record. It is NOT a list of work to do.

`BROKEN` · **Security** · `Isolated` · **S**

Fix 7 covers stored drafts; this covers the other half. `buildContent(tmpl, caseObj)` interpolates
`caseObj.id`, `caseObj.client` and `caseObj.court` into a string later rendered as HTML
(`DocAutomationPage.jsx:42-45, 239`). `client` is a user-supplied display name.

Same for the intake review pane: `ModIntake.jsx:1243` renders `dangerouslySetInnerHTML` over an array
whose "Case Description" entry is raw user text. The "Parties" entry genuinely needs `<strong>` and
`<br/>`, so the correct change is to make that array carry **JSX** rather than HTML strings — which
removes `dangerouslySetInnerHTML` from the file entirely.

### Fix 9 — Record the compliance verdict on the standalone path

> **STATUS: DONE — shipped in `1d2d757`, merged to `master`.** Everything below is the
> reasoning that produced the change, kept as a record. It is NOT a list of work to do.

`INCOMPLETE` · `Shared` · **S**

`check_pleading` has one production call site (`document_service.py:433`). `generate_standalone` has
seven callers and omits the key entirely — so the record is silent, and the checker's own docstring
says silence *"would read as a pass"*.

```diff
+        "compliance":    pleading_rules.check_pleading(template_type, fields),
         "verification":  await _verification_record(fields),
```

Import is already at `document_service.py:12`; `DocumentOut.compliance` already exists
(`schemas/document.py:49`).

**Be clear what this buys.** None of the eleven standalone template types are among the four
`check_pleading` covers, so every one returns `checked: false` today. That is the point — an explicit
"no rules encoded for this type" is a true statement; an absent key is not.

**Also needed to surface it:** `QuickNoticeResult` (`schemas/document.py:120`) and the three inheritance
response models return narrow shapes that would drop the field.

**Callers:** `ai.py:510`, `calculators.py:87`, `documents.py:127`, `inheritance.py:111,123,191`,
`petition_drafter.py:182`.

### Fix 10 — Encode rules for the types that reach a court

> **STATUS: OPEN.** The only unshipped item in this plan. Blocked on legal
> review, not on engineering. Everything below is the brief, not a record of work done.

`INCOMPLETE` · `Isolated` · **L** · **OPEN — THE ONLY REMAINING ITEM. Blocked on legal review.**

> **Not attempted, deliberately.** The code shape is settled — four existing rule sets are the template,
> and the `elif` chain in `check_pleading` is where a new one goes. What is missing is the statutory
> particulars each document must contain, and that is legal drafting. Generating them would be the same
> failure the intake prompt was already hardened against: authoritative-looking legal text nobody
> verified, this time reaching a court.
>
> **What is needed, in priority order** (by whether the document is filed):
>
> | Template | Governing provision to encode | Reaches |
> |---|---|---|
> | `dispute_petition` | Special Court petition particulars (POPPA 2024 + provincial) | a Special Court |
> | `bail_application` | s.497 / s.498 CrPC 1898 | a Sessions Court |
> | `petition_22a` | s.22-A(6) CrPC 1898 | an Ex-Officio Justice of Peace |
> | `fir_application` | s.154 CrPC 1898 | a police station |
> | `complaint_154_3` | s.154(3) CrPC 1898 | an SP |
>
> Until then `check_pleading` returns `checked: False` for each, which fix 9 now records on the document
> and exposes through `GET /documents/{doc_id}` — so the absence is visible rather than silent.

Sixteen of twenty `DocumentTemplate` values have no rules. They are not equally urgent — a private NDA
and a court petition differ in what being incomplete costs.

Priority, by whether the document is filed: `dispute_petition` (the petition_drafter output, filed in a
Special Court) → `bail_application` → `petition_22a` → `fir_application`, `complaint_154_3`. Private
instruments can wait.

Each follows the existing shape: a rules list plus `basis` and a source note, added to the `elif` chain
at `pleading_rules.py:476-492`. The four existing rule sets are the template. **Needs a lawyer's input
on the particulars.**

### Fix 11 — Verify and audit the streaming draft path

> **STATUS: DONE — shipped in `8f2f0cc`, merged to `master`.** Everything below is the
> reasoning that produced the change, kept as a record. It is NOT a list of work to do.

`BROKEN` (no safety net) · `Isolated` · **M**

`/ai/draft/stream` (`ai.py:378-417`) has no grounding node, no citation check, no decision engine and no
provenance row. Retrieval already degrades honestly — an empty result returns an explicit "no sections
retrieved, mark citations as [placeholder]" line — but that is a prompt instruction with nothing
enforcing it.

**Do not block the stream.** Buffer the tokens; after the loop, run the same check the document path
uses and emit it as a final event:

```diff
     async for chunk in llm.astream(messages):
         if chunk.content:
+            buf.append(chunk.content)
             yield f"data: {json.dumps({'content': chunk.content})}\n\n"
+    verdict = await _verification_record({"draft": "".join(buf)})
+    yield f"data: {json.dumps({'verification': verdict})}\n\n"
     finally:
         yield "data: [DONE]\n\n"
```

Reuses `_verification_record` unchanged — already advisory and fail-open, records `ran: False` rather
than a false pass when the corpus is unreachable. Pair with a `provenance_service.record_answer` call so
this path stops being invisible to the audit store.

---

## Module 3 — Document analysis

The implementation here is the most careful of the four modules. The problem is that the tests proving
its central security property never run.

### Fix 12 — Un-gate the IDOR tests

> **STATUS: DONE — shipped in `da7ccb9`, merged to `master`.** Everything below is the
> reasoning that produced the change, kept as a record. It is NOT a list of work to do.

`BROKEN` (0 of 10 run) · `Isolated` · **S**

**Highest value for lowest cost in this plan.** `tests/test_document_tools.py` opens by stating its
purpose is to stop one user's agent reading another user's FIR — then marks the *whole file*
`integration` at line 16, so the standard filter deselects all ten.

Three need nothing but an import:

- `test_no_user_means_no_document_tools_at_all` (`:55`)
- `test_tools_are_built_for_an_authenticated_user` (`:60`)
- `test_read_document_does_not_expose_a_user_id_argument` (`:64`) — the one that stops a future
  refactor turning `user_id` into a tool argument

```diff
-pytestmark = pytest.mark.integration

 # …then mark only the seven that take the `mongo` fixture:
+@pytest.mark.integration
 async def test_user_CANNOT_read_another_users_document(two_users_with_uploads):
```

> **Why removing the marker is safe:** the `mongo` fixture already calls `pytest.skip` when the database
> is unreachable (`tests/conftest.py:72`). The file-level marker is redundant for the seven and actively
> harmful for the three.

### Fix 13 — Collect the five orphaned root-level test files

> **STATUS: DONE — shipped in `da7ccb9`, merged to `master`.** Everything below is the
> reasoning that produced the change, kept as a record. It is NOT a list of work to do.

`INCOMPLETE` · `Isolated` · **S**

`testpaths = tests` excludes `test_chat_ws.py`, `test_full_e2e.py`, `test_intake_e2e.py`,
`test_lawyer_matching.py`, `test_pipeline_nodes.py`, all at `backend/` root. Move them under `tests/`
with appropriate markers, or delete them. Leaving five files that look like coverage and provide none is
the worst of the three options.

### Accepted limitations — no change proposed

- **No OCR.** A photographed FIR cannot be read, and the code says so explicitly rather than returning
  an empty string the model could narrate over (`document_tools.py:67-74`). Adding OCR is new
  architecture, out of scope.
- **12,000-character truncation** (`document_tools.py:31`). Honest — sets `truncated: true` plus a note
  — but a material clause past the cut is invisible to both model and user. Revisit when long contracts
  become a real use case.

---

## Module 4 — Agreement generation

Zero tests, zero downstream checks, and the output is a binding e-signed instrument. Three of the five
defects are integrity problems in the signature record itself, and all three are small.

### Fix 14 — Record what was signed, not just that it was signed

> **STATUS: DONE — shipped in `13e2711`, merged to `master`.** Everything below is the
> reasoning that produced the change, kept as a record. It is NOT a list of work to do.

`BROKEN` (integrity) · `Isolated` · **S**

Nothing in the agreement path hashes the body — `grep -E "sha256|content_hash|immutable"` across the
service, repo and model returns nothing. No route edits `body_html` today, so content is stable by
accident, not by evidence. For an ETO 2002 record, *what was signed* is the part that matters, and a
later edit would be undetectable.

```diff
+import hashlib
+
     doc = {
         "body_html": body_html,
+        "body_sha256": hashlib.sha256(body_html.encode("utf-8")).hexdigest(),

 # …and stamp it into every signature audit entry:
     await agreement_repo.append_audit_log(agreement_id, {
         "action": "signed", "actor_id": user_id,
+        "body_sha256": agreement.get("body_sha256"),
         "timestamp": ..., "ip_address": ip_address, "note": eto,
     })
```

Same principle already applied to money in this codebase: snapshot the thing being agreed to, at the
moment of agreement, immutably.

### Fix 15 — Fix the ETO classification race

> **STATUS: DONE — shipped in `13e2711`, merged to `master`.** Everything below is the
> reasoning that produced the change, kept as a record. It is NOT a list of work to do.

`BROKEN` · `Isolated` · **S**

The comment says *"based on first signature method"*; the code sets it unconditionally on every
signature (`agreement_service.py:172-176`). Two parties signing by different methods produce a
classification that depends on ordering.

Neither reading is quite right. Each party's signature has its **own** ETO character — a drawn signature
and a typed one are not the same instrument — so the honest record is per-party, with the
agreement-level value derived as the **weakest** method used, since that is what a court would be asked
about.

```diff
 # store the classification with the signature, not on the agreement
+    {"method": method, "data": signature_data, "eto": eto}

 # then derive, after re-fetch, instead of last-writer-wins
-    await agreement_repo.update_one(
-        {"_id": agreement_id}, {"$set": {"eto_classification": eto}})
+    signed = [p for p in updated["parties"] if p.get("signed")]
+    weakest = min(signed, key=lambda p: _ETO_RANK[p["signature_method"]])
+    await agreement_repo.update_one(
+        {"_id": agreement_id},
+        {"$set": {"eto_classification": ETO_CLASSIFICATION[weakest…]}})
```

`_ETO_RANK` is a three-entry dict ordering `typed` and `image_upload` (Basic) below `canvas` (Advanced),
matching `ETO_CLASSIFICATION` (`agreement_service.py:12-16`).

### Fix 16 — Let a party decline

> **STATUS: DONE — shipped in `13e2711`, merged to `master`.** Everything below is the
> reasoning that produced the change, kept as a record. It is NOT a list of work to do.

`INCOMPLETE` · `Isolated` · **S**

`AgreementStatus.CANCELLED` is defined (`constants.py:104`) and the UI has a label —
`AG_STATUS_LABEL = {… cancelled: "Rejected" …}` (`ModAgreements.jsx:130`). But grepping every write of
that value across `app/` finds appointments, engagements and subscriptions, and **nothing in the
agreement path**. The four routes are create, list, get, sign.

A party sent an agreement they disagree with cannot decline it — they can sign or leave it `pending`
forever, and the counterparty is never told the deal is off.

Add `POST /agreements/{id}/decline`: assert the caller is a party, reject if already `executed`, set
`CANCELLED`, append a `declined` audit entry carrying `body_sha256` (fix 14), notify the other parties.
The repo needs no new method — `set_status` and `append_audit_log` already exist
(`agreement_repo.py:24,49`).

### Fix 17 — Bound the agreement inputs

> **STATUS: DONE — shipped in `13e2711`, merged to `master`.** Everything below is the
> reasoning that produced the change, kept as a record. It is NOT a list of work to do.

`RISKY` · `Isolated` · **S**

`SignatureSubmit.signature_data: str` has no `max_length` (`schemas/agreement.py:19`); neither do
`AgreementCreate.title` or `body_html`. A canvas signature is base64 image data written straight into
the party subdocument, and Mongo's 16 MB document ceiling is the only limit.

The codebase already knows to do this elsewhere — `_MAX_DRAFT_CONTENT = 300_000`,
`QuickNoticeRequest.text` with `min_length=10, max_length=3000`. Add `Field(max_length=…)` to the three
fields; ~200 KB is generous for a signature image.

### Fix 18 — Stop shipping US contract templates

> **STATUS: INTERIM STEP SHIPPED** in `430791a`; the replacement wording is still open.
> Everything below describes what was done and what remains — see the note inside.

`BROKEN` · `Isolated` · **M** · **INTERIM STEP DONE — full fix awaiting a lawyer**

> **Status.** The six template bodies are **withdrawn**, and the backend refuses to create or sign an
> agreement whose body still carries the marker, so nothing can reach `executed` off that text. Dead
> `AGMT_TEMPLATES` deleted. `tests/test_unreviewed_templates.py` — 11 tests, including one asserting a
> pre-existing boilerplate agreement cannot be signed, and one asserting the JS and Python copies of the
> marker are byte-identical.
>
> **Still open:** the replacement wording. Names, categories and descriptions were kept so the gallery
> still reads sensibly; each body now says what happened and what to do. A qualified Pakistani lawyer
> supplies the real text, at which point the marker comes out and the guard stops firing for that
> template.

The six live templates (`ModAgreements.jsx:96-127`) open with *"a `[State]` corporation"*, quote
`$[Amount]` salaries on a bi-weekly schedule, and include a Non-Compete over a `[Geographic Area]`. They
become the body of a real, e-signed, binding agreement.

> **This is a content fix, not a code fix — and it should not be model-authored.** Writing Pakistani
> contract templates is legal drafting; generating them is the same failure the intake prompt was
> already hardened against. The **engineering** change is to stop presenting unreviewed boilerplate as a
> ready instrument: either remove the bodies until a qualified Pakistani lawyer supplies replacements,
> or label them clearly as unreviewed samples requiring edit before signature.
>
> Pull the restraint-of-trade clause first regardless — enforceability of non-compete terms under the
> Contract Act 1872 is exactly the question that needs a lawyer's answer before it ships in a template.

While in this file, delete `AGMT_TEMPLATES` (`ModAgreements.jsx:14-24`) — nine entries never referenced.
Two competing template arrays in one file is how the wrong one gets edited.

### Fix 19 — Give the module its first tests

> **STATUS: DONE — shipped in `13e2711`, merged to `master`.** Everything below is the
> reasoning that produced the change, kept as a record. It is NOT a list of work to do.

`BROKEN` (zero coverage) · `Isolated` · **M**

Nothing under `tests/` references `agreement_service`. A name collision hides it:
`tests/test_agreement.py` passes 16 tests against `app/services/**agreement**.py`, the Krippendorff
alpha module — a different file.

New `tests/test_agreement_service.py`, named so the collision cannot recur:

- Unregistered party id rejected (`agreement_service.py:47`)
- Single-party agreement rejected (`:50`)
- Non-party cannot sign; party cannot sign twice; executed agreement cannot be re-signed
- **Mixed signature methods classify deterministically** — the regression test for fix 15
- **Body hash stamped into every audit entry** — fix 14
- **Declining sets `cancelled` and notifies** — fix 16
- Oversized `signature_data` rejected — fix 17
- `signature_data` never appears in any response model (`schemas/agreement.py:26`)

---

## Sequencing (as executed)

> All three batches are settled. Batches 1 and 2 shipped; batch 3 is the open work.

### Batch 1 — SHIPPED, no shared surface (12 fixes)

Grepped every caller; none of these share a function with another module. **Fixes 5 and 6 lead** — the
two most severe items, and among the smallest.

| Fix | Change |
|---|---|
| **5** | Escape PDF field text in `P()` — the local-file-read and crash fix |
| **6** | Empty-pleading guard in `generate_document` |
| 1–4 | Intake grounding. Sole caller is `build_intake_graph()` |
| 8 | Escape case data in the two JSX files |
| 12–13 | Test collection. No production code |
| 14–17 | Agreement hash, ETO, decline route, input bounds |
| 19 | New test file |

### Batch 2 — SHIPPED after sign-off (shared surface)

| Fix | Why it needs a decision |
|---|---|
| 7 | Draft sanitisation. Adds `nh3`; lossy against the allowlist. Confirm what the editor emits |
| 9 | Compliance on `generate_standalone`. Seven callers + response-model edits on four routes |
| 11 | Draft-stream verification. Changes the SSE contract; frontend consumer updates in the same change |
| 6′ | The *optional* half of fix 6 — refusing `generated` when `compliance.satisfied == 0`. Contradicts `pleading_rules`' advisory posture, so it is policy |

### Batch 3 — NOT ENGINEERING WORK (open)

| Fix | Who it needs |
|---|---|
| 18 | Pakistani agreement templates — a qualified lawyer. Interim engineering step (pull or label the bodies) can ship in batch 1 |
| 10 | Pleading rules for `dispute_petition`, `bail_application`, `petition_22a`. Code shape is settled by the four existing rule sets; the particulars are not |

---

## Verification

| Fix | Command | Expected after |
|---|---|---|
| 5 | `python -c "from app.services.pdf_generator import generate_pdf; generate_pdf('t','plaint_civil',{'facts':'x <img src=\"win.ini\"/> y'})"` | Renders the literal text; no `ImageReader`, no `paraparser` error |
| 5 | Regenerate an Urdu pleading via `/ai/pleading-urdu/pdf` | Urdu still shaped and right-aligned — the escape must not break `_shape_urdu` |
| 6 | POST `/documents/generate` with all-empty fields | `AppValidationError`, not a stored `generated` doc |
| 1–4 | `pytest tests/test_intake_grounding.py` | New file, ~8 tests passing; zero-chunk case asserts `is_grounded is False` |
| 7–8 | Save a draft containing `<script>`, reopen it | Tag stripped in the stored row and in the editor |
| 9 | `curl` the quick-notice route | `compliance.checked === false` present, not absent |
| 12 | `pytest tests/test_document_tools.py -m "not integration"` | **3 passed** — was `10 deselected` |
| 13 | `pytest --collect-only` | Above 1300 — the five orphaned files counted or gone |
| 14–17, 19 | `pytest tests/test_agreement_service.py` | Mixed-method test passes regardless of signing order; decline sets `cancelled` |
| all | `pytest tests/ -m "not integration and not llm"` | **1414 passed / 0 failed / 44 deselected** (was 1274 / 1 / 25). `test_rate_limit_fails_open::test_healthy_storage_still_limits` now passes, but only because collection order changed — it is still order-dependent, not fixed |

---

## Decisions — all settled

1. ~~**Fix 7** — `nh3` and the tag allowlist.~~ **Approved.** Allowlist derived from the editor's 21
   `execCommand` calls; `style` dropped because nh3 does not filter CSS. The editor now sets
   `styleWithCSS=false` so it emits tags rather than inline CSS, which is what makes that lossless.
2. ~~**Fix 9** — touching `generate_standalone`'s callers.~~ **Approved, and smaller than estimated.**
   All seven routes return hand-built dicts, so no response model changed. A `GET /documents/{doc_id}`
   route was added instead, which also fixes the pre-existing unreadable `verification` record.
3. ~~**Fix 6′** — block or flag at `satisfied == 0`.~~ **Flag only.** `written_statement` has 2 rules
   against `plaint_civil`'s 11, so one threshold means four different things; and fix 6 already blocks
   the real failure mode. No code change.
4. ~~**Fix 18** — remove the bodies or label them.~~ **Removed, with a marker the backend enforces.**
   See fix 18 above.
5. **Fix 10** — who supplies the statutory particulars for the court-bound templates? **STILL OPEN.**
   This is the one remaining item in this plan, and it is not engineering work.

---

## Appendix A — reproduction commands

> **THESE NO LONGER REPRODUCE.** They are kept as the record of how each defect was demonstrated
> *before* the fix, and the outputs shown are the **pre-fix** behaviour. Every one of them now behaves
> differently, which is the point — running them is a way to confirm the fixes are in place, not to
> reproduce a bug. Expected behaviour today:
>
> | Command | Was (pre-fix) | Now |
> |---|---|---|
> | Fix 5a `<img src=…>` | `UnidentifiedImageError`, file opened | renders the tag as literal text |
> | Fix 5b unclosed `<` | `ValueError: paraparser: syntax error` | renders `<50%` as text |
> | Fix 6 empty pleading | court-formatted PDF with empty FACTS | `generate_pdf` still renders it (it is a pure renderer); `generate_document` now raises `AppValidationError` |
> | Fix 6 `check_pleading` | `satisfied=0 missing=9`, ignored | unchanged verdict — but now consumed by the guard |
> | Fix 1 intake grounding | `{'is_grounded': True}` | `{'is_grounded': False, 'grounding_status': 'no_evidence_retrieved', 'answer': …}` |
> | Fix 12 IDOR tests | `10 deselected` | `3 passed, 7 deselected` |

Run from `backend/` with `./venv/Scripts/python.exe`.

```bash
# Fix 5a — local file read via ReportLab markup
python -c "
from app.services.pdf_generator import generate_pdf
generate_pdf('probe','plaint_civil',{'plaintiff_name':'A','defendant_name':'B',
  'court_name':'L','relief_sought':'R',
  'facts':'X <img src=\"C:/Windows/win.ini\" width=\"10\" height=\"10\"/> Y'})"
# → UnidentifiedImageError naming the opened file

# Fix 5b — generation crash on ordinary legal text
python -c "
from app.services.pdf_generator import generate_pdf
generate_pdf('probe','plaint_civil',{'plaintiff_name':'A','defendant_name':'B',
  'court_name':'L','relief_sought':'R',
  'facts':'Damages of Rs 5,00,000 <not a tag'})"
# → ValueError: paraparser: syntax error: parse ended with 1 unclosed tags

# Fix 6 — court-formatted empty pleading
python -c "
from app.services.pdf_generator import generate_pdf
from pypdf import PdfReader
p = generate_pdf('probe','plaint_civil',{})
print(PdfReader(p).pages[0].extract_text())"

# Fix 6 — the check that exists and is ignored
python -c "
from app.services import pleading_rules as pr
vague = {k:'' for k in ('court_name','plaintiff_name','plaintiff_address',
  'defendant_name','defendant_address','facts','relief_sought','applicable_laws','date')}
print(bool(vague))                      # True — 'if not fields' never fires
print(pr.check_pleading('plaint_civil', vague))   # satisfied=0 missing=9"

# Fix 1 — intake grounding defaults open
python -c "
from app.ai.nodes.intake_hallucination_node import intake_hallucination_node as n
import json
a = json.dumps({'summary':'Strong claim.','applicable_laws':[],
  'recommended_actions':['File a suit within 30 days'],'risk_level':'high'})
print(n({'answer':a,'reranked_chunks':[]}))"      # → {'is_grounded': True}

# Fix 12 — the deselected IDOR tests
pytest tests/test_document_tools.py -m "not integration"   # → 10 deselected
```

---

## Appendix B — what was checked and found sound

Recorded so the next pass does not re-audit these.

- **`get_document` / `list_documents` authorization** (`document_service.py:697-726`) — creator, admin,
  assigned lawyer and reviewing lawyer are each handled explicitly; the fallthrough raises. No IDOR.
- **`get_agreement` / `list_agreements` authorization** (`agreement_service.py:103-129`) — party or
  creator only; list strips `signature_data` and `audit_log`.
- **Document review pipeline** (`submit_for_review`, `review_document`) — status transitions guarded,
  KYC verified before submission, rejection requires a reason.
- **`document_tools` ownership model** — identity bound at tool construction, never a tool argument;
  unbound tools are not built when there is no authenticated user.
- **Swallowed exceptions in intake** — clarification failure lets the user proceed, classifier failure
  trusts the user's own case-type pick, lawyer-match failure is `pass` on supplementary data. All
  degrade honestly. `generate_document` was the only outlier (fix 6).
- **`app/services/document_service.py.backup-20260825-225827`** — gitignored, untracked, not importable;
  diff shows only the older pre-`as_of` version. Delete as clutter, not a defect.
