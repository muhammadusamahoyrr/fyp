# Appointment Flow — Remediation Plan

Status: approved for implementation. Written 2026-09-15.
Scope: the client↔lawyer appointment flow (book / confirm / cancel / complete /
no-show / availability).

Phases 1–3 are correctness defects. Nothing in Phase 4 starts until they land,
with two exceptions promoted into **Phase 2** because they are security issues
(admin authorization, meeting-link validation).

Implement **Phase 1 only** as the next change, with separate backend and
frontend verification. Do not begin CAS, slot indexes, backfill, or production
operations in the same commit.

---

## What is already correct

Do not re-litigate these; they work and are tested.

- Lawyer KYC + active-account gate (`_get_verified_lawyer`).
- Optional case-ownership and draft-case gates on booking.
- Sequential lawyer overlap detection (`has_conflict`) — correct interval logic.
- Booking persistence, and the four transition endpoints.
- Lawyer no-show UI and the `no_show` ≠ `cancelled` distinction.
- Both parties notified on booking.
- 67 backend tests green across the appointment-related suites.

---

## Phase 0 — Preserve the checkpoint ✅ DONE

`79068a0 feat(intake): gate OCR text behind client review before analysis`
— 27 OCR/intake paths. Verified green first: backend OCR/intake 170 passed,
frontend 640 passed.

`backend/ocr_eval/fixtures/pilot_2026_09_14/README.md` is **deliberately
excluded and left modified in the working tree**. It is an unrelated
documentation-honesty fix about dataset durability ("A HASH MAKES AN ARTEFACT
VERIFIABLE, NOT RECOVERABLE"). Preserve it; commit it on its own.

---

## Phase 1 — Timezone compatibility ✅ DONE

`9a62b8a fix(appointments): make stored instants timezone-correct end to end`
— 13 files. Gates all four green: backend 5381 passed, frontend 661 passed,
focused booking-time tests 21 passed, `next build` clean.

One item was added that the plan had not listed: `tzdata` is now declared in
`requirements.txt`. Windows ships no system tz database and `BOOKING_TZ` is
built at module level, so its absence is an import failure that takes the
application down. It was present only via an undeclared transitive pandas.

### Original scope, for the record

Land this alone, before any CAS, slot or UI work.

### The root cause

`AsyncIOMotorClient` in `app/db/mongodb.py:10` is constructed **without
`tz_aware=True`**, so every datetime read back from Mongo is naive even though
it was written aware. Proven against local Mongo:

    wrote tzinfo: UTC
    read  tzinfo: None
    compare aware>=read: TypeError

This is not a new discovery in this codebase. `tests/test_auth_flow.py:247`
documents the identical bug, already found and fixed *locally* in
`auth_service`: *"the endpoint 500'd instead of resetting anything."* Fourteen
guards across twelve files now hand-patch the same thing, one of them commented
`# motor reads BSON dates naive`. The appointment module got the patch on the
availability path only. Patch #15 is not the fix.

### Steps

1. **Normalize `record_version()`** (`app/ai/case_context.py:200`) — it reads
   `updated_at` straight off the Mongo doc and is genuinely timezone-sensitive.
   Also normalize `context_fingerprint()` (`:186`) **defensively**.

   Record the reason accurately: `_approved_case_context()`
   (`app/api/v1/routes/ai.py:135`) builds a six-field whitelist through
   `str(value).strip()` plus `next_hearing() -> Optional[str]`, so **no datetime
   reaches `context_fingerprint` on the production AI route today**. And
   `case_record_version` is written to provenance and displayed
   (`provenance_view.py:193`) but **never compared**. So this is a
   representation change in the audit surface, not a cache-invalidation wave.
   Normalizing first keeps the Phase-1 flip representation-stable; that is the
   only reason it goes first.

   Be accurate about the cost: normalization **itself** may produce a one-time
   format change when *it* deploys. That is harmless here precisely because the
   value is never compared — but it is a change on deploy day, not a free move.

2. **Set `tz_aware=True`** in `app/db/mongodb.py:10`. One constructor;
   `tests/conftest.py:209` calls production `connect_db()` and inherits it.
   There is no second Motor constructor in tests.

3. **Schema contract** (`app/schemas/appointment.py:16`) — two rules, not one:
   - **Reject** timestamps with no offset → controlled 422.
     Today a naive input raises `TypeError`, which Pydantic v2 does **not**
     wrap, so it escapes as a **500**.
   - **Convert** valid offset-aware timestamps to UTC.

4. **Fix the cancel cutoff comparison** (`appointment_service.py:176`) — a
   guaranteed 500 today.

5. **Availability timezone contract.** `Asia/Karachi`, **server-owned** — do not
   trust a client-supplied zone in this release. Construct selected appointment
   times as Pakistan time, not the browser's local zone. Store the zone on the
   appointment, convert local slot boundaries → UTC for storage and conflict
   checks, and compute local-day availability windows in that zone.

   Safe because Pakistan abolished DST in 2009 and PKT is UTC+5 year-round, so
   the ambiguous/nonexistent-time class is *empty*, not merely rare. Treat the
   restriction as temporary by design: the Overseas Desk implies non-PK clients
   eventually, and DST policy must be defined before a second zone is accepted.

   **Existing rows carry no timezone. Read them as `Asia/Karachi`** — a default
   at the read boundary, not a production backfill. Requiring a data migration
   merely to *read* existing appointments would turn a code fix into an
   operations event.

6. **Fix Pakistan-date construction.** `new Date().toISOString().split("T")[0]`
   computes the **UTC** calendar date, so between 00:00 and 05:00 PKT it returns
   *yesterday*. Two live sites:
   - `ModLawyers.jsx:571` — the booking modal defaults to yesterday.
   - `ModLawyers.jsx:902` — the picker's `min` is yesterday, so a past date is
     selectable.

   Construct the date in `Asia/Karachi`, not the browser's zone.

7. **Format appointment notifications in PKT.** Three sites
   (`appointment_service.py:107, 141, 192`) emit `"%d %b %Y at %H:%M UTC"`. For
   a Pakistan product every notification is five hours off what the user typed.
   Render in PKT rather than continuing to label and display UTC.

### Serialization audit — complete

| Site | Verdict |
|---|---|
| `v2_capture_contract._stable()` | **Safe.** Normalizes naive→UTC before serializing; fingerprints byte-identical across the flip. |
| Conversation cursor (`conversation_service.py:731`) | **Safe.** Already accepts both naive and aware. |
| `context_fingerprint()` | **Not reached** by datetimes in production (whitelist stringifies). Normalize defensively. |
| `record_version()` | **Real**, but stored/displayed only, never compared. Normalize. |
| `provenance_view._plain()` | Will begin emitting `+00:00`. **Not** a display regression — `AILegalPage.jsx:123` prints provenance timestamps as strings and never parses them as JS dates. |

### The real browser regression — appointments

This one is user-visible and must have its own test:

- Client sends aware UTC via `toISOString()` (`ModLawyers.jsx:616`).
- Mongo returns it **naive** today.
- `AppointmentsPage.jsx:362` does `new Date(a.scheduled_at)`, and JS parses a
  naive ISO string as **browser-local**.

So an appointment can display correctly when created and **five hours early
after a refresh**. Add an explicit **create → reload → same displayed PKT time**
test.

### Phase gate — backend AND frontend

Phase 1 changes `ModLawyers.jsx`, so a backend-only gate is not sufficient.
All four must pass:

1. **Full backend suite** — not just the appointment suites.
2. **Focused frontend tests** for PKT date construction and the reload
   lifecycle.
3. **Full frontend suite.**
4. **`next build`** — a passing test run does not prove the app still builds.

Add compatibility tests for `record_version` / `provenance_view` output shape
before flipping. Note `test_research_case_context.py:543` and
`test_trust_surface.py:140` hard-code the naive representation (they pass
strings, so they will not break, but they pin the audit surface).

**Lifecycle test — the one that matters:** create an appointment → reload it
through Mongo → assert an **identical Pakistan date and time**. Not a unit test
on a formatter; the real round trip, because the defect only appears after the
value has been through the driver.

---

## Phase 2 — Correct, then atomic, transitions ✅ IMPLEMENTED

All six items landed together, as the phase requires: fixing atomicity
without fixing the rules would only have made a wrong rule reliably wrong.

  * §6 transition table → `app/services/appointment_transitions.py`, pure and
    exhaustively tested over all 25 ordered status pairs.
  * §7 CAS → `appointment_repo.compare_and_set` via `find_one_and_update`,
    expected source status and actor predicate both in the filter.
    `update_status` is DELETED, not deprecated — a filter-by-_id helper left
    in place is one a future caller reaches for.
  * §8 denial → single generic 403 (`_APPT_DENIED`), stale state → 409.
  * §9 notifications → `_notify`, best-effort, logs exception CLASS only.
  * admin policy → `_actor_filter`, stated per role.
  * meeting links → HTTPS-only with a host, validated in the schema.

### Three things the plan did not anticipate

1. **`list_appointments` was a third implicit-admin site.** An admin fell
   into the `else` branch and was served the LAWYER query against their own
   id, so they got an empty page — an empty success, which looks like data.
   Now refused explicitly.

2. **Admin cancellation notified one party of two.** "The other party" was
   picked from a client/lawyer binary, so an admin cancellation left the
   lawyer holding a slot for a meeting that no longer existed.

3. **The timing rules made two lawyer-side buttons always-fail.** A note at
   `AppointmentsPage.jsx` had reasoned that no client-side clock rule should
   be invented because *the server did not have one*. It does now, so Done
   and No Show are gated and `Btn` forwards `title` to explain the disabled
   state. That reverses an earlier decision on its stated grounds.

### Contract changes — deliberate, and they moved existing tests

  * A status conflict is **409**, was 422. Three tests updated.
  * `complete` no longer accepts PENDING. It used to, so a lawyer could
    complete a consultation nobody had confirmed, while `no_show` — the
    other outcome of the same meeting — required CONFIRMED.
  * A missing appointment is **403**, was 404.
  * No-show requires the appointment to have STARTED; completion requires it
    to have ENDED; a past appointment cannot be confirmed.

### Original scope, for the record

Fixing atomicity without fixing the rules just makes a wrong rule reliably wrong.

### 6. Write the transition table first

    pending    → confirmed | cancelled
    confirmed  → cancelled | completed | no_show
    completed, cancelled, no_show  → terminal

Plus: completion only after the scheduled **end**; no-show only after the
appointment **time**; a past pending appointment cannot be confirmed.

### 7. CAS

`update_status` currently filters on `{"_id": appt_id}` alone with no expected
status, and **every caller discards its `bool` return**. Two concurrent confirms
both read PENDING, both validate, both write, both notify.

Replace with `find_one_and_update(..., return_document=AFTER)` whose filter
carries the **expected source status** and an **actor-scoped predicate**.

"Owner filter" cannot literally apply to an admin, who owns nothing. The
predicate is chosen by actor:

    client                → {"client_id": user_id}
    lawyer                → {"lawyer_id": user_id}
    explicitly authorized admin → no owner predicate at all

### 8. No status leakage on CAS failure

A CAS miss is ambiguous. Re-read under the **same actor-scoped predicate**:

    CAS fails
      → actor-scoped lookup ABSENT  → denial response (see below)
      → actor-scoped lookup PRESENT → clean status conflict (409)

Never fetch by `_id` alone and report what you found.

**Denial response — use 403, not 404.** This repo already made this decision and
documented the reasoning at `app/api/v1/routes/ai.py:161-169`: *"the 404/403
split IS the leak."* Both responses collapse to a single **403** with a generic
message (`_CASE_DENIED = "Case not available"`), with the distinction preserved
in the server log. Either convention is non-leaking; consistency with the
existing boundary decides it.

### 9. Notifications — best-effort, sanitized

`create_notification` can raise from the insert or the WebSocket fan-out, and
the appointment service has no try/except. Today the caller gets an error for
work that already committed.

`logical_event_id` is **not** a fix on its own — `event_outbox.py:9-11` says it
is the *dedup* half of a two-part design, and the durable half is a relay that
is **flag-gated off** (`_documents_v2_relay` → `sweep()` returns immediately
while `DOCUMENTS_V2=False`). So:

- Wrap notification calls; **a committed transition returns success** regardless
  of delivery.
- Log **appointment ID, transition code, exception class only**. Never raw
  driver errors — they carry URIs and credentials. House style, per
  `indexes.py:249-252`.
- Document notifications as best-effort. Durable intents are deferred until a
  relay exists that does not depend on the DOCUMENTS_V2 flag.

### Promoted into this phase — security, not polish

**Explicit admin policy.** An admin currently falls through the client/lawyer
conditions *implicitly* in `get_appointment()` (`:262`) and
`cancel_appointment()` (`:157`). Copy the case module's shape: `case_service
._assert_access()` (`:610`) is one explicit rule — `admin | owning client |
assigned lawyer` — with admin allowed by a deliberate early return. Give
appointments the equivalent rather than inventing a second rule that can drift.

**Meeting-link validation.** `meeting_link` is `max_length`-only and is rendered
as a clickable link at `ModTracking.jsx:1718`. Accept **validated HTTPS URLs
only**. (Separately, in Phase 4, move collection to confirm-time — a video
consultation's join link is useless if it only exists after completion.)

---

## Phase 3 — Overlap and booking integrity ✅ IMPLEMENTED

Code only. NOTHING HAS BEEN ACTIVATED: no production database was touched, no
index was created against production, no backfill was run. The rollout below is
still entirely ahead.

  * §10/§11 slot model → `app/services/appointment_slots.py`, pure. Alignment
    and 30-minute divisibility are enforced at the schema boundary because they
    are the PRECONDITION that makes the index mean anything, not formatting.
  * §11 indexes → `app/db/appointment_index_spec.py`, one declaration consumed
    by production creation, the enforcer, the preflight and the test fixture.
  * §12 enforcement → `validate_appointment_indexes` +
    `enforce_appointment_correctness_indexes` (unconditional, raises). NOT
    wired into startup yet — see the ordering below.
  * §13 preflight → `app/db/appointment_slot_preflight.py`. Writes nothing,
    proven by a test that intercepts every write method on the collection.
    `backfill_occupied_slots` defaults to dry run and is called by nothing.
  * §14 idempotency → client-generated key, server-computed fingerprint.
  * §15 rate limit → `_LIMIT_BOOK = "10/minute"` on POST /appointments.

### Four things the plan did not anticipate

1. **`uniq_pending_slot` actively breaks idempotent retries.** Two retries of
   one booking are by definition the same lawyer at the same start time, which
   is exactly what that index rejects. It is no longer created, and dropping it
   is now a REQUIRED rollout step rather than tidy-up.

2. **A concurrent retry does not collide on the idempotency index.** Both
   attempts carry the same client and the same slots, so whichever unique index
   Mongo evaluates first reports the duplicate — in practice the client-slot
   one. Branching on the constraint name told the client "you already have an
   appointment during this time" about their own booking. The replay check now
   runs before the constraint is interpreted.

3. **The friendly `has_conflict` pre-check defeats idempotency on its own.**
   The second of two concurrent retries passes the replay lookup (nothing
   written yet), then reaches `has_conflict` after the first commits and is
   told the slot is taken — by itself. It needed the same replay check.

4. **A compound sparse index would not have worked for idempotency.** Sparse on
   a compound index still indexes a document when ANY key is present, and
   `client_id` always is — so every keyless booking would carry a null and the
   second would collide with the first. The index is partial on
   `{"idempotency_key": {"$type": "string"}}` instead.

### Contract change

An index-level slot clash is now **409**, was 422. Nothing the caller sent is
invalid; the world moved under them. One existing test updated.

### Activation — ENFORCED, not merely documented

Startup is fail-closed: `assert_appointment_booking_ready()` runs in
`main.lifespan` and refuses to boot unless the WHOLE contract holds — not just
the indexes. An index can be valid over rows that carry no `occupied_slots` at
all; those rows are simply absent from it, so every guarantee reads as enforced
while the appointments predating the backfill claim nothing and can be
double-booked freely.

Normal startup NO LONGER CREATES the correctness indexes.
`create_appointment_correctness_indexes()` is an explicit operator/test call.
The reason is not cost: a startup that builds them repairs correctness state as
a side effect of being restarted, and then nobody can tell from outside whether
the guarantee held yesterday. Startup repairs nothing, by design.

    1.  keep the OLD app running                (it is what still serves)
    2.  freeze booking writes
    3.  python -m app.db.appointment_slot_preflight
    4.  repair the rows it reports
    5.  backfill_occupied_slots(dry_run=True)   review the plan
    6.  backfill_occupied_slots(dry_run=False)  once approved
    7.  create_appointment_correctness_indexes()
    8.  validate_appointment_indexes()          must be empty
    9.  drop uniq_pending_slot
    10. preflight again: safe_to_activate must be true
    11. deploy the NEW app
    12. reopen booking

**The obsolete drop is step 9, not step 4.** An earlier version of this plan had
it early. `uniq_pending_slot` is weak, but while it is the only guard present it
is the only thing preventing an identical double booking — dropping it first
leaves a window with NO overlap protection, inside a window that exists to add
some.

**Correction to an earlier claim.** This plan said `uniq_pending_slot` breaks
every idempotent retry. It does not: a retry carrying a key is replayed BEFORE
the duplicate-key error is interpreted, so it succeeds whichever index raised
it. That was measured against a revision of the service in which the replay was
gated behind the constraint name, and was not re-checked after the ordering was
fixed. It remains a blocking gate because it is narrower than its replacement
and still refuses writes the new rules allow — a keyless retry among them.

### Original scope, for the record

### 10. Why a transaction is not enough

MongoDB transactions give snapshot isolation with **no predicate locking**. Two
transactions that both observe "no conflicting appointment" and insert
*different* documents never conflict. That is write skew, and it does not
prevent overlap.

`uniq_pending_slot` is also narrower than the check it backs: unique on
`(lawyer_id, scheduled_at)` — **exact start only** — and scoped to PENDING. So
10:00/60min and 10:30/60min both survive, and confirming an appointment frees
its slot.

### 11. Slot generation — precise

- `scheduled_at`: UTC, minute ∈ {00, 30}, seconds and microseconds zero.
- `duration_minutes`: 30–180 **and divisible by 30**. Drop the `45 min` option
  at `AppointmentsPage.jsx:297` and tighten the schema (`ge=30, le=180` accepts
  45 today).
- `occupied_slots`: every UTC half-hour instant in `[start, end)`.

Two unique **multikey partial** indexes, both scoped to **pending AND
confirmed** so cancellation releases the claim by leaving the active scope:

    (lawyer_id, occupied_slots)   — closes lawyer double-booking
    (client_id, occupied_slots)   — closes client self-double-booking

### 12. Enforcement is mandatory — do not use `_try_unique_partial`

That helper ends in a bare `except Exception → logger.warning → return`
(`indexes.py:143-148`), so a duplicate leaves the index **silently absent** while
everyone believes the guarantee holds. `indexes.py:151-165` already states this
principle for V2.

And appointment enforcement **cannot inherit V2's flag behaviour**:
`enforce_v2_correctness_indexes()` (`:241-247`) reports and returns when
`DOCUMENTS_V2=False`. Appointments are **already live** and have no flag.

So: a **separate appointment index specification and an unconditional
enforcer**, following the V2 pattern — one declaration
(`v2_index_spec`-equivalent), separate validation, readiness-probe runnable, and
a read-only preflight modelled on `app/db/v2_index_preflight.py` ("IT WRITES
NOTHING... printed as commands for a person to read, decide on, and run").

### 13. Rollout — requires a write freeze

This sequence is **unsafe** while appointments are live:

    backfill → create indexes → deploy slot-writing code   ✗

A booking created between backfill and deploy would carry no `occupied_slots`
and escape overlap protection entirely. For this FYP the simplest safe rollout:

    maintenance / booking write freeze
      → preflight
      → resolve malformed active records
      → backfill occupied_slots on active appointments
      → create indexes
      → validate
      → deploy slot-writing code
      → reopen booking

**Preflight must report:** existing overlaps; non-30-minute start times;
durations not divisible by 30; active rows missing `scheduled_at` / `end_at`.

### 14. Booking idempotency

Best-effort notifications stop a committed booking returning 500, but a network
retry can still look like a **new** booking — or hit the client's own
appointment and be told "already booked". Define it precisely:

- Client-generated `idempotency_key`.
- Unique constraint on `(client_id, idempotency_key)`.
- Normalized payload fingerprint stored alongside.
- **Same key + same payload** → replay the original creation receipt.
- **Same key + different payload** → **409**.

**Ordering matters: the idempotency lookup runs BEFORE the conflict check.**
Reversed, a retry finds *its own* appointment already occupying the slot and
reports "slot already booked" — telling the client their booking failed when it
in fact succeeded, which is the exact failure idempotency exists to prevent.

Booking notifications take a `logical_event_id` so an idempotent replay cannot
notify twice. Delivery stays best-effort; the id is for dedup, not durability
(see Phase 2 §9).

### 15. Rate limit

`POST /appointments` has no SlowAPI decorator. One client can carpet-book a
lawyer's diary with PENDING requests — and with no expiry (Phase 4) nothing
clears them.

---

## Phase 4 — Product gaps

In order:

1. Client cancel UI — `PageAppointments` (`ModTracking.jsx:1647`) is read-only,
   so `cancelled_by: "client"` can never occur. Phase 1 is what makes the
   backend path actually work.
2. Remove or wire the fake lawyer scheduling controls. `confirmSchedule`
   (`AppointmentsPage.jsx:458`) only mutates React state: a new appointment gets
   `id: Date.now()` and vanishes on refresh; reschedule rewrites display strings
   but never `at`. Wired in five places. Shipping fake buttons is worse than
   having none.
3. `PATCH /{id}/reschedule` — the unused `exclude_id` in
   `appointment_repo.py:64` is the vestige of the one that was never built.
4. No-show notification — the client is never told, though it gates their
   reviews via `exists_completed`.
5. Client display of cancellation reason and actor; lawyer notes.
6. Stale-pending expiry and past-confirmed handling. `APPOINTMENT_REMINDER`
   (`constants.py:276`) is declared and **never emitted** anywhere.
7. Appointment reminders — use the existing `acquire_period_lock` scheduler
   harness.
8. Real lawyer availability schedule. The endpoint returns only *booked* slots,
   never *bookable* ones; six times are hardcoded at `ModLawyers.jsx:910`.
   Sunday 09:00 is bookable today.
9. Move `meeting_link` collection to confirm-time.
10. Pagination — every consumer requests `page_size: 50` with no paging.
11. N+1 removal in `_names()` — two user lookups per row, ~100 queries for a
    50-row list. Batch with `$in`.
12. Remove debug `console.log` from `submitBooking` and `handleAccept`.
13. Fee / payment integration — **deferred**. When built, snapshot the rate onto
    the appointment at booking; never read it live at settlement.

---

### 16. Test fixture must build from the canonical spec

`tests/conftest.py:384 ensure_app_indexes` already calls production
`create_all_indexes()` rather than restating a list, and already **promotes
`_try_unique_partial`'s log-and-continue to a hard failure in tests**. So the
slot indexes will be built from production code automatically, and a silent
skip already fails the suite.

The remaining gap is validation, not creation: once the separate appointment
index specification and enforcer exist, the fixture must also run that
**validator** against the same canonical spec — so a malformed index is caught,
not merely an uncreated one.

---

## Correctness test matrix (real local Mongo)

- Missing / malformed index detection (both slot indexes), validated against the
  canonical appointment index specification.
- Lawyer overlap; client overlap.
- Cancellation releasing slots.
- Concurrent booking; concurrent confirm; cancel-vs-complete.
- Cancel cutoff, both sides of the boundary.
- Naive-timestamp booking → 422 (not 500).
- Create → Mongo reload → identical Pakistan date and time.
- PKT date construction across the 00:00–05:00 PKT window (the `toISOString`
  boundary), for both the modal default and the picker `min`.
- Notification bodies rendered in PKT, not UTC.
- Idempotent replay: same key + same payload returns the original receipt and
  does **not** report "slot already booked"; same key + different payload → 409.
- Idempotent replay notifies exactly once.
- Explicit admin policy, per endpoint.
- Meeting-link URL validation (reject non-HTTPS and non-URL).
- `confirm_appointment` full contract — currently only smoke-exercised as
  no-show setup; cancel, the cutoff, and the availability endpoint have **no**
  coverage at all.
