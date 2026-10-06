# Document Analyzer — demo runbook

The Document Analyzer runs inside the **normal application**: the same backend, frontend, login and lawyer dashboard as every other module. There is no separate server or port.

For the FYP presentation, its AI step uses the **simulated provider**. It is labelled as simulated on every screen and in the receipt, and it calls no external AI service. Every document is **synthetic**. Nothing is deployed, and `.env` / `.env.local` are not edited.

Background for questions: [DEMO_PRESENTATION_NOTES.md](DEMO_PRESENTATION_NOTES.md).

---

## 1. Prerequisites (once)

| Need | Check |
|---|---|
| Windows 10/11 with PowerShell 5.1+ | `$PSVersionTable.PSVersion` |
| MongoDB Server installed (`mongod`), on PATH or in `C:\Program Files\MongoDB\Server\<ver>\bin` | `mongod --version` |
| Backend venv with dependencies | `backend\venv\Scripts\python.exe` exists |
| Node.js and frontend dependencies | `node --version`; `frontend\node_modules` exists |
| Free ports 8000 (backend) and 3001 (frontend), the app's normal ports | `serve.py start` refuses a busy port and names the holder |

**Why a local database.** The analyzer needs a database with transactions. The simulated provider also runs only against a database **on this machine**; a hosted cluster is refused, so a demo can never write into the hosted data. Your `.env` points at the hosted cluster. So for the demo, the backend runs against a local replica set, using settings that apply to that one process. While it runs, the **whole app** uses that local database, not only the analyzer.

One-time setup, in PowerShell, from `backend\`:

```powershell
venv\Scripts\python scripts\dev_mongo_replset.py                                  # local replica set on 127.0.0.1:27018 (start or reuse)
venv\Scripts\python scripts\prepare_local_database.py --db attorney_ai_local      # creates the appointment indexes startup requires; local only, creates nothing else
Copy-Item .env.analyzer-demo.example .env.analyzer-demo.local                     # git-ignored copy for your settings
venv\Scripts\python -c "import base64,os;print('k1:'+base64.b64encode(os.urandom(32)).decode())"
# paste that output after ANALYZER_KEKS= in .env.analyzer-demo.local, and keep it
```

The overlay `.env.analyzer-demo.local` holds only these settings: local `MONGODB_URL` / `DB_NAME`, `REDIS_URL` empty, `DOC_ANALYZER=true`, `ANALYZER_KEKS`, `ANALYZER_AI=true`, `ANALYZER_AI_PROVIDER=simulated`, `ANALYZER_AI_SYNTHETIC_ONLY=true`, the hypotheses engine off, and SMTP blank. Everything else (JWT secret, other modules) still comes from `.env`.

*Alternative:* put the same lines into `.env` yourself and start without `--env-overlay`. That changes your real configuration, so it's your call.

## 2. Start and stop: the normal commands

```powershell
# backend (from backend\): the normal managed launcher, plus this run's settings
.\start.ps1 --env-overlay .env.analyzer-demo.local
#   same as: venv\Scripts\python scripts\serve.py start --env-overlay .env.analyzer-demo.local

# frontend (from frontend\): the normal dev server
npm run dev
```

Open **http://127.0.0.1:3001/login**. The frontend reaches the backend through its normal `/api/v1` proxy on port 8000.

**Readiness.** `backend\serve.log` must show:

```
app.services.analyzer.readiness: doc_analyzer_ready ai=simulated
```

If it shows `doc_analyzer_unavailable … detail=<reason>` instead, the analyzer alone answers 503 and the rest of the app runs normally. Reasons:

| Reason in the log | Fix |
|---|---|
| `transactions_unavailable` | The database is a standalone mongod. Run `scripts\dev_mongo_replset.py` and point `MONGODB_URL` at `127.0.0.1:27018/?replicaSet=rs0` |
| `ai_simulated_needs_local_database` | `MONGODB_URL` is hosted (e.g. `mongodb+srv://`). The simulated provider refuses it; use the overlay |
| `ai_synthetic_only_required` | Set `ANALYZER_AI_SYNTHETIC_ONLY=true` |
| keyring / `ANALYZER_KEKS` problem | `ANALYZER_KEKS` is empty or malformed. Generate one (section 1) |
| an index problem | Restart once; startup creates the analyzer's indexes. For the appointment preflight, run `prepare_local_database.py` |

**Without the overlay** (plain `.\start.ps1` on your current `.env`), the analyzer is simply off: `DOC_ANALYZER` isn't set, and its pages answer "not found". Every other module behaves as before.

**Stop:** `venv\Scripts\python scripts\serve.py stop` (backend; graceful), and Ctrl+C in the `npm run dev` window.

## 3. Accounts

The local database starts **empty**. Nothing is seeded:
1. Open **Sign Up** → **Lawyer**, and register with a fictional name and an `@example.com` address.
2. Complete onboarding (bar number such as `DEMO/0001/2026`, one specialization, a fictional office) → **Submit for Verification**.
3. Reload the page. The lawyer dashboard shows **Document Analyzer** in the sidebar. The menu needs only the saved bar number and specialization. The analyzer is restricted to registered lawyers; it does **not** mean the qualification has been verified.

To show the access rules, register a second lawyer (they see none of the first lawyer's analyses) and a client (no analyzer at all; its API answers 403).

## 3a. Optional backup: the isolated launcher

If the normal setup can't be used on the day, the separate launcher still works:

```powershell
.\demo\analyzer-demo.ps1 start | status | stop | reset [--yes]
```

It runs the same app code, with the same simulated provider, on a fresh throwaway `aai_demo_<hex>` database. It uses ports 8765/3765 and serves a production frontend build.

It seeds three fictional accounts. Their passwords are regenerated on every start, in `%TEMP%\attorney-ai-analyzer-demo\accounts.json`:
- `demo.lawyer@example.com`
- `demo.lawyer2@example.com`
- `demo.client@example.com`

`stop` only stops the processes it started. `reset` only deletes databases it recorded (local, `aai_demo_*`), and only with `--yes`.

It's a backup, not the normal path.

## 4. Demo documents

Write them with `venv\Scripts\python scripts\analyzer_demo_fixtures.py --out <folder>` (from `backend\`); the bytes come out identical every time. Each page carries a **SYNTHETIC DEMONSTRATION DOCUMENT** banner. All names are invented, and the CNICs use the `999xx` prefix, which no real CNIC uses.

| File | Type | Blank field | Masked automatically | Scanner misses (mark by hand) | Alias to link | Amount + deadline kept |
|---|---|---|---|---|---|---|
| `demo_tenancy.pdf` (**use this one live**) | Tenancy | security deposit `Rs. ______` | CNIC, "Khan" / "Mr. Khan", house name | **Nargis Akhtar** (landlord), **Chacha Bashir** (caretaker) | **Fasi** → the tenant's `[NAME_…]` token ("Khan") | Rs. 45,000 · within 7 days |
| `demo_nda.pdf` | NDA | permitted purpose `______` | CNIC, "Malik" / "Mr. Malik" | **Pappu** (sales clerk) | **H.R.M.** → the `[NAME_…]` token for Hamid Raza | Rs. 250,000 · within 14 days |
| `demo_employment.pdf` | Employment letter | reporting manager `______` | CNIC, "Siddiqui" / "Ms. Siddiqui" | **Guddu Bhai** (supervisor) | **Ashi** → the `[NAME_…]` token for Ayesha | Rs. 120,000 · within 5 days |

In all three, *Disputes* and *Governing law* are deliberately missing, so they read **"Not located automatically"**. The type-specific legal checklist reads **"Pending qualified lawyer validation"** and is not run.

## 5. Script (5–7 minutes): `demo_tenancy.pdf`

| Time | Screen | Do | Say |
|---|---|---|---|
| 0:00 | Login (`http://127.0.0.1:3001/login`) | Sign in as the demo lawyer you registered (section 3) | "This is the normal application. The analyzer is one module in the lawyer dashboard. Synthetic documents only; the AI step is simulated and says so." |
| 0:30 | Lawyer dashboard → **Document Analyzer** | Point at the *Demo version* note. Tick the synthetic-document box. **Choose a synthetic document** → `demo_tenancy.pdf` → **Read this document** | "The analyzer is a registered-lawyer tool. Uploads must be attested synthetic, and the server rejects them otherwise." |
| 1:00 | Confirm what this document is | Type is pre-selected: *Tenancy*, with the sentence it came from. Set **Province: Punjab** → **Confirm** | "Every proposal shows its evidence sentence. Nothing is decided without the lawyer." |
| 1:30 | Confirm the key terms | Pick the proposed values (11 months, monthly, *Not stated* where nothing is stated) → **Confirm the terms** | "Only confirmed terms decide which checks apply." |
| 2:00 | Checks (lower half of the page) | Scroll to **Checks**: *Found* items with their sentences; **Disputes / Governing law: Not located automatically**; **Punjab tenancy checklist: Pending qualified lawyer validation** | "These are local drafting-completeness checks, not law. 'Not located' means the reader didn't find it, not that it's missing. The legal checklist exists but no qualified lawyer has approved it, so it doesn't run." |
| 2:45 | **Review what will be sent to the AI** | Read the masking note. Original on the left, *Would be sent* on the right. CNIC → `[CNIC_1]`, Khan → `[NAME_1]`, the house name → `[ADDRESS_1]` | "Nothing is sent until I approve this exact request." |
| 3:15 | same | 1) The highlighted **"Faisal Mehmood"** → choose **Personal name**. 2) Select **Nargis Akhtar** in the original text → **Personal name**. 3) Select **Chacha Bashir** → **Personal name** | "The scanner missed the landlord's name, which is exactly why a human review is required." |
| 3:50 | same | Select **Fasi** → **Personal name**, then in its row choose **Same person as [NAME_1] — Khan** → **Update the preview** | "'Fasi' is the tenant's nickname, so I link it to the tenant. The AI then sees one person, not two." |
| 4:20 | People + exact request | Tick each **person** checkbox. Show the exact request: every name masked, **"Rs. 45,000 … within 7 days"** still readable, the **request fingerprint** | "This is the exact text that will be sent. Amounts and deadlines survive masking." |
| 4:50 | same | Tick **I reviewed …** → **Approve and send this request** | "Approval binds to this fingerprint. Any edit after previewing invalidates it." |
| 5:10 | Obligations / Risks / Summary tabs | Show the **"Simulated AI response — demo mode"** banner, the per-item **"Simulated — demo mode"** badges, the provenance line *simulated · demo-simulated-1*, the evaluation line *Not applicable: this is a simulated demo response*, and the evidence quoted from the **original** text | "No model produced these items. They are placeholders from an offline simulation that went through the real validators. Evidence is quoted from the original, never from the masked text." |
| 6:00 | **Processing receipt** → **Show the receipt** | *Demo mode — simulated provider*, *Integrity check passed … hash chain intact*, fingerprint, masking `pii-mask.10`, sentences sent, the earlier *not sent (pii_confirmation_required)* entry | "The receipt holds ids, hashes and versions only. The fingerprint identifies the request; it isn't proof of deletion or delivery." |
| 6:40 | (optional) | Log out, then log in as the demo client (no analyzer) or the second demo lawyer (*Your analyses* is empty) | "Lawyer-only and owner-only, in demo mode too." |

**Don't link "Faisal Mehmood" to "Khan".** It's the same person and the link is allowed, but the request then reads `[NAME_n] [NAME_n] (the Tenant)`. That's correct but looks odd on screen. The "Fasi" link is enough to show identity linking.

## 6. Failures and recovery

| Symptom | Cause | Recovery |
|---|---|---|
| `REFUSING TO START: 127.0.0.1:8000 is already held by pid N` | A backend is already running | `venv\Scripts\python scripts\serve.py stop`, or close that program |
| `REFUSING TO START: env overlay unreadable: …:N: expected KEY=VALUE` | A malformed line in `.env.analyzer-demo.local` | Fix that line |
| The backend exits at startup, and `serve.log` names the appointment indexes | The local database wasn't prepared | `venv\Scripts\python scripts\prepare_local_database.py --db attorney_ai_local` |
| `doc_analyzer_unavailable … detail=…` in `serve.log`; the analyzer page says it's unavailable | An analyzer prerequisite is missing | See the readiness table in section 2 |
| The analyzer page says "not found" | Started without the overlay (`DOC_ANALYZER` off) | Restart with `--env-overlay .env.analyzer-demo.local` |
| No **Document Analyzer** in the sidebar | Onboarding not saved yet | Finish onboarding, then reload |
| `dev_mongo_replset.py` can't find `mongod` | MongoDB isn't installed or not on PATH | Install MongoDB Server, or pass `--mongod <path to mongod.exe>` |
| Login fails after switching databases | That account lives in the other database | Register on the local database (section 3) |
| The exact request stays hidden ("1 highlighted detail still to decide") | A highlighted detail hasn't been decided | Decide every highlighted item, then **Update the preview** |
| The request is blocked by a leak guard (e.g. `signature_name`) | A line like `Signed …: ______ Name` looks like an unmasked signer, and the guard fails closed | Mark the name, or use the supplied fixtures (built to avoid it) |
| **Approve** refuses ("preview changed") | The review was edited after the preview | **Update the preview**, re-tick, approve |
| A name in the original wraps across a line and can't be selected in one piece | The PDF line breaks inside it | Drag the selection across the break, or mark each part |
| Anything else mid-presentation | — | Use the backup launcher (section 3a) or the recording (section 7) |

## 7. Backup checklist (the day before)

- [ ] Run the whole script once on the presentation laptop, from `start` to `stop`.
- [ ] Record a screen video of sections 5.0:30–6:40 (with the offline banner and receipt visible).
- [ ] Take screenshots of:
  - the Checks list showing "Not located automatically" and "Pending qualified lawyer validation";
  - the review screen with the missed names marked;
  - the exact masked request with the fingerprint;
  - the Simulated banner and badges;
  - the receipt.
- [ ] Keep the recording and screenshots **outside the repository**. Don't commit screenshots or `accounts.json`.
- [ ] Check that `.\start.ps1 --env-overlay .env.analyzer-demo.local` shows `doc_analyzer_ready ai=simulated`, and that the backup `.\demo\analyzer-demo.ps1 start` → `stop` runs once.
- [ ] Note that the analyzer needs no network, but other modules can: the onboarding office address is looked up with OpenStreetMap, and the AI assistant uses its configured provider. Finish onboarding before going offline.

## 8. Where things are

| What | Where |
|---|---|
| Normal backend launcher | `backend/start.ps1` → `backend/scripts/serve.py` (`--env-overlay`) |
| Demo settings template | `backend/.env.analyzer-demo.example` (your copy: `.env.analyzer-demo.local`, git-ignored) |
| Local database preparation | `backend/scripts/prepare_local_database.py` |
| Simulated provider | `backend/app/services/analyzer/simulated_provider.py` (selected by `ANALYZER_AI_PROVIDER=simulated`) |
| Fixture generator | `backend/scripts/analyzer_demo_fixtures.py` |
| Backup launcher | `backend/scripts/analyzer_demo.py` (+ `_analyzer_demo_server.py`; wrapper `demo/analyzer-demo.ps1`); state in `%TEMP%\attorney-ai-analyzer-demo\` |
