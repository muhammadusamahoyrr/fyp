# Overseas Desk — Feature Overview

**The POA lifecycle-safety and property-enforcement layer for the Pakistani diaspora.**

Overseas Pakistanis lose property to POA misuse, land-grabbing, and fraudulent
transfers — often without knowing a remedy exists. The Overseas Desk is a single
place to draft the *right* Power of Attorney, get it attested correctly, register
the property, and — when something goes wrong — route the dispute to the fast-track
Special Court created by the **Protection of Overseas Pakistanis' Property Act 2024**.

It is organised into four tabs.

---

## 1. My Powers of Attorney

A full POA lifecycle manager built around one fact: **a court reads the written
authority, not what was intended** — so choosing the wrong *type* of POA is the
single biggest cause of misuse and fraud.

| Feature | What it does |
|---|---|
| **Plain-English POA advisor** | You type an intent ("let my brother sell my flat"); an LLM maps it to a POA type + power codes, then a **pure rule engine** enforces the non-negotiable safety rules. The model can suggest, but it *cannot* forget that disposing of property requires a Special (registered) POA — that rule lives in code, not the prompt. |
| **Deterministic fraud-risk score** | Flags the known fraud-prone shapes of a drafted POA: a General POA carrying disposal powers, no expiry, vague scope, an over-broad grant. |
| **POA generation (Special / General)** | Produces the POA as a PDF with a **non-removable DRAFT-FOR-LEGAL-REVIEW banner**. |
| **Disposal-power guard** | Property-disposition powers (sell, transfer, gift, mortgage) are **barred from a General POA** at the data layer. |
| **Registry + expiry alerts + one-click revocation** | Tracks all your POAs, warns before expiry, and generates a **Deed of Revocation** on demand. |
| **Attestation lifecycle** | Tracks the execution workflow: drafted → notarised → mission attested → MOFA attested → registered. |
| **Tamper-evidence** | Each PDF's **SHA-256 hash** is stored so tampering can be detected later. |
| **Attorney acknowledgement** | Records that the attorney has acknowledged the POA. |
| **Point-of-use verify link + QR** | A public, no-login verification link (the token *is* the capability). A counterparty — a buyer's lawyer, a sub-registrar — scans the QR and sees the POA's **live status, exact authorised scope, and tamper-hash**. This is what stops a revoked or forged POA from being honoured because nobody checked. |
| **Attested-document verify** | Upload the returned, attested POA; the system reports the attestation markers it found and whether they match the POA on record — answering "did they attest the *right* thing?" |
| **OPPPA registration status** | Track whether the property is registered with the Overseas Pakistanis' Property Protection Authority. |

---

## 2. Attestation Navigator

**Objection-aware routing** between the apostille and the legacy consular chain.

Pakistan joined the Hague Apostille Convention (in force 9 March 2023, made permanent
by the Apostille Act 2024). For a document flowing between two member states in good
standing, a **single apostille replaces** the old Notary → Pakistan Mission → MOFA
legalisation chain.

But it is **not** "use apostille everywhere":

- **Bilateral objections cannot be inferred from membership.** Several states objected
  to Pakistan's accession under Art. 12, so the Convention does not operate between
  them and Pakistan — the legacy consular chain is still correct for those.
- **India is a separate case** (political non-recognition, not an Art. 12 objection)
  with the same practical result.
- **Unknown countries fail safe** to the longer legacy chain, never the shorter
  apostille path.

You pick the country where the POA is executed and get the correct route.

---

## 3. Special Courts

A **jurisdiction engine** for the remedy most overseas Pakistanis don't know exists.

The Protection of Overseas Pakistanis' Property Act 2024 created special courts for
diaspora property disputes — with e-filing, video-link hearings supervised by Pakistan
missions, and statutory deadlines. Provinces are enacting their own versions on a
**rolling basis**, and the procedures differ by jurisdiction.

- **Per-province resolution** — federal/ICT is operational; some provinces are
  *enacted-but-pending*; others have nothing yet.
- **Real timelines** — disposal window (measured from the *grant of leave to defend*,
  not from filing) and appeal window, where known.
- **Fail-safe** — a court that isn't confirmed operational does **not** get "e-file
  here today." The engine routes to the federal framework and a lawyer, and flags
  "verify" — because sending someone to file in a court that isn't hearing cases yet
  wastes the time and trust they can least afford.
- **Dated + sourced** — every figure carries an `effective_as_of` date, a confidence
  tier (established / single-source / unconfirmed), and a source citation.
- **OPPPA registration** is recommended on every result as a cheap protective step.

---

## 4. Property Dispute  ⭐ *(fast-track enforcement flow)*

The "route it right" pipeline: from "my property was grabbed" to either a drafted
petition or a lawyer's desk — **never a guess**. Four guided steps.

1. **Eligibility** — a deterministic (no-LLM) check of overseas-Pakistani status:
   a valid ID (passport / CNIC / NICOP / POC / OPF) plus 182+ days abroad in a tax year.

2. **Classify the grievance** — a grounded LLM sorts the free-text complaint into one
   of six categories (illegal occupation, POA misuse, fraudulent transfer, inheritance
   dispute, encroachment, sale-agreement dispute) with a **confidence gate**. This is
   the one place AI output heads toward a real court filing, so an **unconfirmed or
   ambiguous** classification *never* proceeds to drafting — it holds for a lawyer.
   The hold decision is enforced in pure code, not the prompt.

3. **Guided intake** — fixed fields only (property, province, opposing party, timeline,
   documents held, relief sought) — no open-ended conversational intake.

4. **Outcome** — the pipeline ends in exactly one of two states:
   - **Ready to draft** → generates a Special-Court petition PDF. Assembly is
     deterministic (heading, parties, jurisdiction, relief, the leave-to-defend timing
     note, and the confirmed **15-day appeal window** from the Act); the LLM writes
     *only* the statement of facts and cause of action, grounded strictly in the intake
     — it writes "[to be provided]" rather than invent a name, date or amount. A missing
     field refuses the draft; nothing is auto-filed.
   - **Held for lawyer triage** → the client gets a plain-language notification
     explaining *why* it's held, with a route into the verified-lawyer directory.

### Case-brief handoff to a lawyer *(read / handoff only — no fees or payments)*

- **Send to lawyer** — from either state, packages the whole case (eligibility,
  classification + confidence, the entered facts, the jurisdiction resolution, and the
  draft petition if one exists) and sends it to one verified lawyer. Idempotent — once
  sent, it can't be re-sent.
- **Lawyer inbox** — a simple page listing every case brief sent to that lawyer, with
  state and "petition ready" badges.
- **Case brief view** — the lawyer opens the full brief in one place and **downloads
  the draft petition** where present (access granted through the existing document
  review pipeline). No fee negotiation, engagement letter, or payment — that is the
  separate hiring flow.
- **Deep-link notification** — the lawyer's "new case brief" notification opens the
  inbox directly.

---

## Design principles that run through every feature

- **Fail-safe / fail-closed.** Uncertainty routes to a human, never a confident guess.
- **AI suggests, pure code enforces.** Every safety-critical rule (disposal → Special
  POA, the triage hold, grounding) lives in deterministic code, not a prompt.
- **Dated and sourced.** Fast-moving legal facts carry an `effective_as_of` date, a
  confidence tier, a source citation, and a standing "verify with a lawyer" duty.
- **Grounded generation.** Drafted documents use only the facts provided; a gap becomes
  "[to be provided]", never an invention.
- **Nothing is filed or paid automatically.** Every generated document is a DRAFT for a
  qualified lawyer to review, complete and file.

---

*Attorney.AI — Overseas Desk. This tool provides guidance and drafts, not legal advice;
confirm the current legal position with a qualified Pakistani lawyer before acting.*
