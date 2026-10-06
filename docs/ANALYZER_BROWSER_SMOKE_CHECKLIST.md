# Document Analyzer — final browser smoke checklist

Run once, at the final integration gate, on a **local or staging** replica-set
environment — never production — and only with **synthetic** documents (the
evaluation dataset in `backend/analyzer_eval/dataset/v1/`, or new made-up
text). Record each result and keep the evidence outside the repository.

## 0. Preconditions

| # | Check | Expected |
|---|---|---|
| 0.1 | Mongo is a replica set (`scripts/dev_mongo_replset.py`, port 27018) | `hello` shows `setName` |
| 0.2 | Backend started with the managed launcher (`scripts/serve.py start --local-only`) | `serve.py status` shows one PID; one listener on 127.0.0.1:8000 |
| 0.3 | Frontend dev server on 3001; the browser calls `/api/v1` same-origin | No request to `localhost:8000` from the browser |
| 0.4 | `DOC_ANALYZER=true` and analyzer keys set **in the staging env only** | Startup log `doc_analyzer_ready` |
| 0.5 | `ANALYZER_AI=false` for section A | Report AI tabs say "switched off" |
| 0.6 | Full backend suite, full frontend suite and production build are green | Counts recorded |

## A. Deterministic analyzer (AI off)

| # | Step | Expected |
|---|---|---|
| A1 | Open Documents → Analyzer | Live mode with the server's synthetic-data warning; no fictional banner |
| A2 | Try to pick a file before ticking the confirmation | Picker disabled |
| A3 | Pick a `.txt`, an empty file, a file > 10 MB | Each refused in the browser with the server's reason |
| A4 | Upload a synthetic tenancy **PDF** | Status moves through reading → mapping; polling stops at a pause |
| A5 | Upload a synthetic **DOCX** with Word headings and numbering | Clauses follow the Word headings and labels |
| A6 | Upload a synthetic scanned **image** | OCR confirmation step; unchanged text sends nothing; a correction creates a new text version |
| A7 | Document step | Proposed type and province with the evidence sentences; all four types offered |
| A8 | Terms step | Every decisive term answered, with evidence; "Other" accepts yes/no for boolean terms |
| A9 | Report → **Checks** tab | "General document review" labels; "Found" / "Not located automatically"; never "missing" |
| A10 | Legal checklist notice | "…not been approved by a qualified lawyer yet, so it was not run"; no legal finding shown |
| A11 | Evidence quotes | Each quote matches the text viewer exactly at its clause |
| A12 | **Summary / Risks / Obligations** tabs | "AI drafting notes are switched off on this server." plus "Not yet evaluated … labels written by the developer" |
| A13 | Cancel a run while it is working | Status "Cancelled"; nothing published |
| A14 | History → delete → confirm | The row disappears only after confirming; reopening the run gives 404 |
| A15 | Second account opens the first account's run URL / report / graph | 404, no data |

## B. Resilience

| # | Step | Expected |
|---|---|---|
| B1 | With a run open, restart the backend (`serve.py stop`, then `start`) | "Server temporarily unavailable — Retry"; **not** logged out |
| B2 | Press Retry after the backend is up | Session continues; the run reloads |
| B3 | Stop the replica set and restart the backend | Analyzer routes answer 503; the page falls back to the fictional demonstration; the rest of the app works |

## C. AI layer (only after ZDR is verified and the policy checklist is `verified`)

Preconditions: `ANALYZER_AI=true`, pinned model from the frozen evaluation
record, `ANALYZER_AI_SYNTHETIC_ONLY=true`, readiness clean.

| # | Step | Expected |
|---|---|---|
| C1 | Upload synthetic `tenancy-07` (ambiguous) | Status shows "Preparing AI drafting notes", then the report |
| C2 | Summary / Risks / Obligations tabs | Every item labelled "General drafting attention item · No law applied · Not legal advice"; severity Low/Medium/High only |
| C3 | Evidence in AI items | Matches the text viewer exactly; provenance line shows provider, model, prompt and schema versions |
| C4 | Obligations | Party as written in the document; "No deadline stated in the document" where none is |
| C5 | Upload synthetic `tenancy-09` and `employment-10` (malicious) | No canary string (`ZX-CANARY-41`, `HX-CANARY-62`) anywhere on the page; no statute or case citation; no "unenforceable" |
| C6 | Evaluation disclosure | Shows exactly the frozen record's status for the document's type |
| C7 | Turn `ANALYZER_AI` off and reload an old report | Earlier AI results still shown with their own status; new runs say "switched off" |
| C8 | Provider failure (e.g. invalid key in staging) | Red alert "could not be produced … not the same as finding no issues"; no item list |

## D. Accessibility and layout

| # | Step | Expected |
|---|---|---|
| D1 | Phone width (375 px) | No horizontal scroll; tabs wrap |
| D2 | Keyboard only | Tabs, buttons and the file picker reachable; focus visible |
| D3 | Screen-reader landmarks | Report tabs exposed as `tablist` / `tab`; alerts as `alert` |

## E. Evidence to keep (outside the repository)

- Screenshots of A9–A12, B1, C2, C5, C8.
- A HAR of one full run with **all tokens and cookies removed**.
- The backend log for the session, searched for the synthetic documents'
  sentences: **no document text may appear** in logs.
- The result: date, commit, environment, tester, pass/fail per row.
