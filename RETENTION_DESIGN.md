# Retention & deletion — design for approval

**Status: periods and hold policy APPROVED 2026-09-03. Implementation in progress, deletion still disabled.**

Approved by the user:
* **All user-visible data — 12 months.** Messages, sessions, turn records and
  LangGraph checkpoints. This is shorter than the 24 months proposed below for
  messages and longer than the 90 days proposed for turns and checkpoints; the
  gain is one number a privacy policy can state without qualification.
* **Provenance and undelivered outbox entries — 7 years**, unchanged.
* **Legal holds: admins only.**

What is built so far: the hold model, the policy module and a DRY-RUN report.
Nothing deletes anything yet. Enabling deletion is a separate, deliberate step —
see §5, which is why this was never a TTL index.
Dated 2026-09-03, revised the same day with the decisions above. Audited against the code as it stands.

---

## 1. What the system holds today

Seven stores contain something a client said or was told. Only three collections
in the entire database currently expire anything, and none of them is one of
these.

| Store | Contains | Removed on “Delete conversation”? | Expires today |
|---|---|---|---|
| `chat_sessions` / `research_sessions` | Title, the first question (`title_question`), any pending clarification, case binding, jurisdiction | Tombstoned — title and first question **cleared**, session id kept | No |
| `conversation_messages` | Every question and answer, with citations, claims and confidence | **Removed** | No |
| `conversation_turns` | The complete response frame per turn, kept for replay — a second copy of every answer | **Removed** | No |
| `answer_provenance` | Question, answer, evidence, model attribution, timings | **Retained**, and said so | No |
| `provenance_outbox` (`failed` only) | A full provenance record that could not be delivered | Not touched | No |
| LangGraph checkpoints | Graph state per thread, including question text and case context | **Retained**, and said so | No |
| Corpus / Chroma | No user content | n/a | n/a |

The session id survives a delete deliberately: it is the LangGraph thread key,
and reusing it would let a new conversation inherit an old thread’s state.

**Two things follow that are worth stating plainly.** First, `conversation_turns`
holds a complete second copy of every answer — it exists so a retried request
replays byte-identically, not as history — so any retention rule that covers
messages but not turns leaves the answers behind. Second, “Delete conversation”
already tells the user that provenance and checkpoints are retained
(`DELETION_EFFECTS`); the promise is honest today, but it is also open-ended,
which is the thing to fix.

---

## 2. What the periods have to serve

Four pressures, and they pull in different directions:

- **Professional obligation.** Advice given to a client is the kind of record a
  regulator or a court may ask about, and the party asking is usually not the
  one who deleted the conversation. This argues for keeping provenance far
  longer than chat history.
- **Data minimisation.** A legal question is among the most sensitive things a
  person types. Keeping it after it stops being useful is pure exposure.
- **Being able to answer “why did it say that?”** — the entire point of the
  provenance trail, and the reason a failure case can be diagnosed months later.
- **Cost.** Real but not decisive at this scale; it should not drive the numbers.

The tension is between the first two, and it resolves the same way in most
jurisdictions: **keep the accountability record, shorten the readable one.**
A user deleting a conversation is asking for it to stop being *visible to them*;
they are not, and cannot be, asking the firm to forget it gave advice.

---

## 3. Periods

Approved values, with the reasoning that produced them. Where the approved
number differs from what was proposed, both are shown — the reasoning for the
original is kept so a future change starts from the argument rather than from
the number.

| Store | Proposed | Why this number |
|---|---|---|
| `conversation_messages` | **12 months** from last activity (approved) | Long enough that a client returning about the same matter next year still has the thread; short enough to bound exposure. Keyed on *last activity*, not creation, so an active conversation is never truncated mid-thread. |
| `chat_sessions` / `research_sessions` | **12 months**, same clock (approved) | Must match messages exactly. A surviving session whose messages expired is an empty conversation in the sidebar; the reverse is orphaned messages. |
| `conversation_turns` | **12 months** (approved; 90 days was proposed) | This is a replay cache, not history. Its only job is making a retried request idempotent, and no client retries a request from three months ago. Expiring it early removes the duplicate copy of every answer and is the single largest minimisation win available. |
| `answer_provenance` | **7 years** | The accountability record. Aligned to the longest ordinary limitation period for professional negligence claims in Pakistan; **this is the number most needing a lawyer’s confirmation.** |
| `provenance_outbox` (`failed`) | **7 years**, same as provenance | It *is* a provenance record that never arrived. Any shorter period silently discards the evidence that the audit trail has a hole — the exact records most worth keeping. |
| LangGraph checkpoints | **12 months** (approved; 90 days was proposed) | Working state for resuming an interrupted turn. Nothing needs a six-month-old checkpoint, and it holds question text and case context. |
| Tombstoned conversations | **7 years**, id only | Already stripped of title and question text. Only the session id survives, and it must, so the thread key is never reused. |

**Deliberate consequence, stated so nobody is surprised:** after 12 months a
client's conversation disappears from their sidebar while the provenance record
of the same advice remains for another six years. That is the correct outcome
and it must be what the privacy policy says, or the system is quietly doing
something its users were not told about.

---

## 4. Legal holds

**A hold must beat every period above.** Without one, the retention job becomes
a mechanism for destroying evidence precisely when a dispute makes it valuable —
and it does so automatically, which is worse than doing it deliberately.

Proposed rule:

- A hold is placed on a **user** or a **case**, never on one message. Disputes
  are about matters, not individual turns.
- While a hold is active, **nothing** within its scope expires: not messages,
  not turns, not checkpoints. Enforced by the deletion job, not by a TTL index —
  *see §5, this is the reason TTL indexes cannot be used for most of these.*
- A hold **overrides user deletion too.** “Delete conversation” under a hold
  should stop hiding rather than removing, and should say so. Anything else
  means a user can destroy evidence about themselves by pressing a button.
- Placing and lifting a hold is itself an audited action, with who and why.

**Decided: admins only.** One privileged action, logged with who and why. A
lawyer needing a hold asks an admin. The narrower surface also avoids the case
where a lawyer freezes data about their own conduct.

---

## 5. Why a TTL index is the wrong mechanism for most of this

MongoDB TTL indexes are attractive and mostly unusable here, for three reasons:

1. **They cannot see a hold.** A TTL index deletes on a date field with no
   conditions. The only way to exempt a held record is to keep its date field
   null, which means the retention rule stops being expressed as a rule and
   starts being a side effect of another field's nullness.
2. **They cannot delete across collections.** Expiring a conversation means
   removing its messages *and* its turns *and* its checkpoint. A TTL on each
   collection independently produces partial deletions — a conversation whose
   messages are gone but whose turns still replay the answers.
3. **They cannot be dry-run.** The first observable effect of a wrong number is
   that the data is gone.

**Proposal:** a scheduled job, the same lease-based pattern the provenance relay
uses, with:

- a mandatory **dry-run mode** reporting what *would* be deleted, by count and
  age, with no request ids and no content;
- a **rate cap** per run, so a mistake is a small mistake;
- deletion **ordered within a conversation** (turns → messages → checkpoint →
  session) so a partial failure leaves less rather than an inconsistent mix;
- every run recorded, with counts, in the same audit trail as everything else.

TTL indexes remain appropriate for `ws_tickets` and `refresh_blocklist`, which
have no holds and no cross-collection story. They already have them.

---

## 6. What “Delete conversation” should promise

Current wording is accurate but incomplete — it names what is retained without
saying for how long. Proposed:

> Deleting removes this conversation and its messages from your history right
> away. A record that this advice was given — the question, the answer and the
> sources used — is kept in our audit trail for **7 years**, as professional
> records rules require. It is not visible in your account and is not used to
> answer anyone else's questions.

The last clause matters and is now true by construction: the result cache
refuses any turn carrying conversation history, private-document tools, or a
case binding.

---

## 7. Decisions needed before any code

1. ~~Approve or change the periods~~ — **done**: 12 months for all
   user-visible data, 7 years for provenance and undelivered outbox entries.
2. ~~Approve the legal-hold rule~~ — **done**: admins only.
3. **STILL OPEN — the privacy policy.** After 12 months a client's conversation
   disappears from their account while the provenance record of the same advice
   remains for another six years. That has to be what the policy says, or the
   system is doing something its users were not told about. §6 has proposed
   wording.
4. **STILL OPEN — a lawyer's confirmation of the 7-year provenance figure.** It
   is aligned to the longest ordinary limitation period for professional
   negligence claims in Pakistan, but that is my reading and not advice.
5. **STILL OPEN — enabling deletion.** The job exists in DRY-RUN only. Turning
   it on is a separate decision, to be taken after a dry-run report over real
   data looks right.

Nothing expires today. That remains the safe failure: data still present can be
deleted later, and data deleted on a wrong number cannot be recovered.
