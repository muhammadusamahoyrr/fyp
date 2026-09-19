# Appointment slot rollout — operator checklist

Status: **NO-GO.** Two prerequisites are unverified. Nothing in this document
has been executed; no production system has been contacted.

The sequence and its reasoning live in
`backend/app/db/appointment_slot_preflight.py`. This is the operator-facing
short form, plus the three things that decide whether a window may open at all.

---

## Blocking prerequisites

### 1. Verified backup and a restore REHEARSAL — ❌ UNVERIFIED

Not "a backup exists". A backup nobody has restored is a hypothesis.

Required before step 6:

- [ ] A backup of the `appointments` collection taken **after** the write
      freeze and **before** the backfill, so its contents match what the
      backfill will operate on.
- [ ] That backup **restored into a scratch database** and spot-checked:
      document count matches, and a handful of known `_id`s come back with
      their `scheduled_at`, `status` and `occupied_slots` intact.
- [ ] The restore command written down, with its measured duration.

Why a rehearsal and not a checkbox: the backfill's `$set` on `occupied_slots`
is **irreversible in place**. Restore is the only rollback, so an untested
restore means the rollback plan for step 6 is untested.

### 2. Write-freeze METHOD — ❌ UNVERIFIED

**There is no freeze mechanism in the code.** No maintenance flag, no read-only
mode, no booking kill-switch exists in `app/core/config.py`, `app/main.py` or
`app/api/v1/routes/appointments.py`. The freeze must be achieved
operationally, and the method must be chosen and rehearsed before a window.

Candidate methods, each needing a decision:

- Stop / scale the application to zero (total outage, simplest to verify).
- Block `POST /appointments` and `PATCH /appointments/*` at the ingress.
- Revoke the application's write role on the `appointments` collection.

> **`--booking-writes-frozen` IS AN ACKNOWLEDGEMENT, NOT PROOF.** The flag
> records that a human asserted the freeze. It verifies nothing, and the CLI
> cannot. A booking created between the backfill and the deploy carries no
> `occupied_slots`, so it is invisible to the indexes being built and escapes
> overlap protection **permanently, not briefly**. Treat the flag as a
> signature on a decision, not as a check that passed.

Required before step 6:

- [ ] Method chosen and written down.
- [ ] Rehearsed in staging, with a **positive test**: attempt a booking and
      confirm it is refused.
- [ ] The un-freeze step confirmed to restore service.

---

## Before anything else: the read-only audit

```
export AAI_AUDIT_MONGO_URL='mongodb://.../'
python -m app.db.appointment_activation_audit \
    --database <NAME> --confirm-database <NAME> \
    --confirm-endpoint <scheme://host[:port]>     # once per host
```

One pass, one report, covering everything in this document: booking
correctness, the query indexes **per feature**, the pending-expiry population,
the outcome backlog, the reminder windows, working-hours configuration, open
disputes, and the state of every flag. Add `--json` for a machine-readable
form.

It changes nothing, and that is enforced rather than promised: the database
handle it gives the production services it reuses forwards an allowlist of read
operations and refuses everything else, including `$out` and `$merge`, which
are writes reached through `aggregate`. There is no apply mode, no `--uri`, and
nothing in `app/` imports it.

**Its output carries no identifiers.** No appointment ids, names, emails,
CNICs, notes, meeting links, client statements or support notes - counts, named
gate results and sanitized problem codes only, so the report can go into a
ticket as it stands. The endpoint is echoed as scheme, host and port; the
credentials never are.

It confirms the target before connecting, exactly as the backfill does, even
though it only reads. A report is a claim about **one named environment**, and a
claim about the wrong one is worse than no claim.

### Reading the verdicts

| Verdict | Means |
|---|---|
| `READY` | every machine-verifiable check for that feature passed |
| `NOT_READY` | a machine-verifiable check failed - the only value that means something is wrong |
| `UNVERIFIED_EXTERNAL` | the checks passed and a human decision is still outstanding |
| `NOT_EVALUATED` | no conclusion - usually a scan that hit its page bound, so the counts are real but partial. **Not a pass.** |

Exit codes: `0` every machine-verifiable check passed - `2` machine-verifiable
NO-GO - `3` the audit did not run or could not finish.

> **Exit 0 is not a GO, and the report says so on its last line.** It means
> nothing the tool can check says no. `overall_production_go` can never come
> back `READY` - the write freeze and a proven backup restore are invisible to
> every query, since an idle database and a frozen one are indistinguishable,
> and an untested backup looks exactly like a good one until the restore. Those
> two remain `UNVERIFIED_EXTERNAL` until a person supplies the evidence, and
> **no argument to the command marks any gate satisfied.**

A missing **QUERY** index blocks only the one feature whose read it serves and
never booking - refusing to serve bookings over a missing performance index
would be an outage for a reason that is not the reason.

One coupling is worth expecting rather than being surprised by: a missing
**correctness** index on `appointment_disputes` turns `booking_rollout` red
too. That is not a classification error. `assert_appointment_booking_ready()`
refuses to start the service while any correctness index is missing across
either collection, so booking genuinely cannot roll out until it is rebuilt.
The verdict names the index that tripped it.

Recommended: run it against a **restored clone** first, alongside step 4.

---

## Sequence

Steps 1–5 are reversible. Step 6 is the first irreversible one.

| # | Step | Command | Reversible |
|---|---|---|---|
| 1 | Keep the OLD app serving | — | n/a |
| 2 | **Freeze booking writes** | operator-defined (above) | yes |
| 3 | Take the verified backup | operator-defined (above) | n/a |
| 4 | Preflight — inspect | `python -m app.db.appointment_slot_preflight` | read-only |
| 5 | Resolve every reported row, then dry run | `python -m app.db.appointment_backfill_cli --database <NAME>` | read-only |
| 6 | **Backfill — apply** | `python -m app.db.appointment_backfill_cli --database <NAME> --apply --confirm-database <NAME> --confirm-endpoint <scheme://host[:port]> --booking-writes-frozen` | **NO — restore only** |
| 7 | Create the four indexes | `createIndex` × 4 (below) | yes — drop them |
| 8 | Validate | `validate_appointment_indexes()` must return `[]` | read-only |
| 9 | **Drop the obsolete index** | `db.appointments.dropIndex("uniq_pending_slot")` | **NO — rebuild only** |
| 10 | Preflight again | `safe_to_activate` must be `true` | read-only |
| 11 | Deploy the NEW app | startup runs `assert_appointment_booking_ready()` | yes — redeploy old |
| 12 | Reopen booking | reverse of step 2 | yes |

`AAI_BACKFILL_MONGO_URL` must be exported for steps 5 and 6. The CLI reads the
connection string from that variable only — there is no `--uri` flag, because
an argument reaches shell history, `ps` output and CI logs.

**Confirming the database name is not enough.** Environments routinely carry
the same database name on different servers, so the name alone proves only that
you know the name.

`--confirm-endpoint` identifies the server, and **an endpoint is scheme + host
+ port**. Two Mongo instances on one host differing only by port is exactly how
a staging and a production database end up side by side, and a confirmation
that dropped the port would confirm both. Give it once per host for a replica
set, in any order.

Both the endpoint set and the database name must match before anything is
written. A mismatch, an unsupported scheme, or a connection string that cannot
be parsed all refuse **before connecting**, and the refusal does not echo the
real endpoint back. **A dry run prints the exact `--confirm-endpoint` arguments
to copy** — do not retype them.

### If step 6 reports PARTIAL/UNKNOWN

The apply exits non-zero and does **not** print `APPLIED` when it cannot say
the result is complete:

- a row that vanished mid-run (Mongo matched nothing),
- a written count that disagrees with the plan,
- an exception part-way through the write,
- a post-apply pass that still finds work,
- **a post-apply verification that could not be read at all.**

The last one matters most and is the least obvious: the writes already
happened, so a verification that fails does not mean they were fine — it means
nobody knows. Only the exception class is printed, never the driver message,
which carries the connection string.

Some rows then carry new slots and some do not, which no single count
describes.

- [ ] **Keep booking writes frozen.** Do not proceed to step 7.
- [ ] Do not re-run the apply blindly; it is not a retry.
- [ ] Inspect: `python -m app.db.appointment_slot_preflight`.
- [ ] If the state cannot be explained, **restore from the step-3 backup**.

A "vanished row" in particular may mean a second writer was active — which
would mean the freeze was not actually in force.

### Step 7, verbatim

```
db.appointments.createIndex({"lawyer_id": 1, "occupied_slots": 1}, {name: "uniq_appointment_lawyer_slot", unique: true, partialFilterExpression: {"status": {"$in": ["pending", "confirmed"]}}})
db.appointments.createIndex({"client_id": 1, "occupied_slots": 1}, {name: "uniq_appointment_client_slot", unique: true, partialFilterExpression: {"status": {"$in": ["pending", "confirmed"]}}})
db.appointments.createIndex({"client_id": 1, "idempotency_key": 1}, {name: "uniq_appointment_idempotency", unique: true, partialFilterExpression: {"idempotency_key": {"$type": "string"}}})
db.appointments.createIndex({"status": 1, "expires_at": 1}, {name: "appointment_pending_expiry", partialFilterExpression: {"status": "pending"}})
```

The fourth is a **QUERY** index, not a correctness one. Nothing is wrong
without it and no guarantee depends on it — it exists so the pending-expiry
sweep is a range read rather than a collection scan. It is listed here because
`indexes_valid` (step 8, and gate one at step 10) checks every DECLARED index,
so leaving it out fails that gate. It is not unique, so unlike the three above
it cannot fail the build on existing data.

**The expiry sweep itself is dormant and is NOT part of this rollout.** Nothing
calls `services/appointment_expiry_sweep.py`; it is not registered in
`main.py`. Turning it on is a separate, later decision with its own
prerequisites, listed below. The mechanism is **not activation-ready**, and
this index existing does not make it so.

---

## Prerequisites before the expiry sweep may be enabled

Separate from, and later than, everything above. **All are unmet. NO-GO.**

| # | Prerequisite | Why it blocks | State |
|---|---|---|---|
| E1 | The four indexes above exist and `safe_to_activate` is true | Until then a lapsed request is the only thing holding its slots, and releasing one under the old `uniq_pending_slot` frees an hour the replacement guarantee is not in place to re-protect | **unmet** |
| E2 | **Deadline-guarded confirmation** | `confirm` does not check the deadline today, and that is correct while nothing expires. Once a sweep runs, the two race: a lawyer can confirm a request the next sweep was about to retire, and which one wins is a matter of timing rather than policy. Both CAS filters pin `status: pending`, so one loses cleanly — but the outcome is arbitrary | **unmet — not implemented** |
| E3 | **Explicit approval for rows that already exist** | Appointments booked before `expires_at` existed are out of the sweep's scope by construction. Deciding what happens to them is a separate decision about real people's requests, and it must be taken against real numbers from `survey_legacy_pending()` — which counts and writes nothing | **unmet — approval not sought** |
| E4 | A decision on cadence and burst size | The first applying run against an existing deployment meets the whole history of unanswered requests at once. `DEFAULT_LIMIT` bounds one run; nobody has chosen how often it runs | **unmet** |

**E2 is not a defect to fix now.** Adding a deadline filter to `confirm` while
the sweep is dormant would leave a lapsed request neither confirmable nor
expired — stuck, slots still held, with no explanation for either party. The
current behaviour is right for the current state; it is the ORDER of the two
changes that matters, and E2 must land with or before activation, never after.

**What is safe to run now:** `survey_legacy_pending()` and
`expire_lapsed_requests()` without `apply=True`. Both read and count only. A
bare `expire_lapsed_requests()` writes nothing and notifies nobody by design —
expiring requires `apply=True` spelled out at the call site.

**Step 6 must precede step 7, and not only for tidiness.** Rows with no
`occupied_slots` all index as `occupied_slots: null`, so two slotless active
rows sharing a lawyer — or a client — collide on the unique index and the build
fails outright. Observed while testing the CLI, not deduced.

---

## Rollback points

| If it fails at | Do this | Cost |
|---|---|---|
| 1–5 | Un-freeze. Nothing was written. | A closed booking window |
| 6 | **Restore from the step-3 backup.** No in-place undo exists. | Whatever the rehearsal measured |
| 7–8 | Drop the four new indexes; the old app ignores them. | An index build's worth of IO |
| **After 9** | `uniq_pending_slot` is gone. Rolling back to the old app leaves **weaker** overlap protection than before the window, until it is rebuilt. | See below |
| 11 | Redeploy the previous app. | A deploy cycle |

**Step 9 is the point of no easy return.** Before it, the old app can be left
running unchanged. After it, the old app runs with its only overlap guard
removed and the new guards unused, so a rollback past step 9 should rebuild
`uniq_pending_slot` rather than simply redeploying:

```
db.appointments.createIndex({"lawyer_id": 1, "scheduled_at": 1}, {name: "uniq_pending_slot", unique: true, partialFilterExpression: {"status": "pending"}})
```

**The new app refuses to boot while the contract does not hold.** Deploying it
before step 7 takes the service down rather than bringing it up — which is the
intended fail-closed behaviour, not a fault.

---

## Gates at step 10

All six must be true, and `safe_to_activate` is their conjunction:

`indexes_valid` · `no_overlapping_active_rows` · `all_active_rows_usable` ·
`all_active_rows_slotted` · `no_idempotency_collisions` ·
`obsolete_indexes_absent`

---

## Still requiring explicit approval

1. The write-freeze method (blocking, above).
2. Backup taken and **restore rehearsed** (blocking, above).
3. Authorisation for step 6 — irreversible write.
4. Authorisation for step 9 — irreversible drop.
5. Capacity sign-off: three unique index builds on a live collection,
   plus one non-unique query index.
6. **Enabling the pending-expiry sweep** — a separate decision with its own
   four prerequisites (E1–E4 above), all currently unmet. Creating the query
   index in step 7 does NOT enable anything.
7. Acknowledgement that **`PATCH /appointments/{id}/confirm` now requires a
   versioned body**; any non-UI client receives 422 until updated.
8. **Activation instants, cadence and caps** for reminders and outcome nudges.
   The nudge activation instant decides how much history gets notified, and the
   scheduler refuses to enable nudges without one; the batch caps decide how
   many people hear from us at once. The audit reports whether an instant is
   configured, never its value.

Recommended before scheduling: run step 4 against a **restored clone** of
production to see real findings and real row counts, with no window open and
nothing at risk.
