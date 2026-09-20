/* The client half of booking idempotency.
 *
 * The server replays a booking when it sees the same `(client_id,
 * idempotency_key)` and the same payload fingerprint. That only helps if the
 * CLIENT sends the same key when it retries — a key minted per request is
 * indistinguishable from a new booking, and turns a double-submit into two
 * appointments, which is the outcome the mechanism exists to prevent.
 *
 * So the key belongs to the intent, not the request. These pin both halves:
 * it survives a retry, and it does NOT survive a change of intent or a
 * completed booking — because reusing it then would make the server replay the
 * previous appointment instead of creating the new one.
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
    createBookingKeyHolder,
    bookingIntentFingerprint,
    mintKey,
} from "../src/lib/bookingIdempotency.js";

const INTENT = {
    lawyer_id: "lawyer-1",
    case_id: "case-9",
    scheduled_at: "2026-09-20T10:00:00.000Z",
    duration_minutes: 60,
    mode: "video",
    notes: "Bail matter",
};

/** A deterministic mint, so identity is asserted rather than inferred. */
function counter() {
    let n = 0;
    return () => `key-${++n}`;
}

test("a retry of the same booking intent reuses the key", () => {
    const holder = createBookingKeyHolder(counter());

    const first = holder.keyFor(INTENT);
    const retry = holder.keyFor(INTENT);

    assert.equal(first, "key-1");
    assert.equal(retry, "key-1", "a retry minted a new key and became a second booking");
});

test("many retries of one intent still share one key", () => {
    const holder = createBookingKeyHolder(counter());
    const keys = new Set([
        holder.keyFor(INTENT), holder.keyFor(INTENT),
        holder.keyFor(INTENT), holder.keyFor(INTENT),
    ]);
    assert.equal(keys.size, 1);
});

/* Each field is checked on its own. A fingerprint that ignored one of them
 * would let a genuinely different booking reuse a key, and the server would
 * answer 409 idempotency_mismatch on what the user experiences as a normal
 * booking. */
const CHANGES = {
    "a different lawyer": { lawyer_id: "lawyer-2" },
    "a different case": { case_id: "case-10" },
    "a different time": { scheduled_at: "2026-09-20T11:00:00.000Z" },
    "a different duration": { duration_minutes: 30 },
    "a different mode": { mode: "phone" },
    "a different note": { notes: "Property matter" },
};

for (const [what, patch] of Object.entries(CHANGES)) {
    test(`${what} gets a new key`, () => {
        const holder = createBookingKeyHolder(counter());
        const first = holder.keyFor(INTENT);

        const second = holder.keyFor({ ...INTENT, ...patch });

        assert.equal(first, "key-1");
        assert.equal(second, "key-2", `${what} reused the previous key`);
    });
}

test("a completed booking retires its key", () => {
    // The next submission is a NEW booking. Reusing the key would make the
    // server replay the appointment that was just made.
    const holder = createBookingKeyHolder(counter());
    const first = holder.keyFor(INTENT);

    holder.complete();
    const next = holder.keyFor(INTENT);

    assert.equal(first, "key-1");
    assert.equal(next, "key-2", "an identical booking after completion replayed the old one");
});

test("going back to a previous intent does not resurrect its key", () => {
    // The holder tracks ONE intent. A client that edits the time and changes
    // its mind is making a new booking attempt, and the earlier key may
    // already have created an appointment.
    const holder = createBookingKeyHolder(counter());
    const first = holder.keyFor(INTENT);
    holder.keyFor({ ...INTENT, scheduled_at: "2026-09-20T11:00:00.000Z" });

    const back = holder.keyFor(INTENT);

    assert.equal(first, "key-1");
    assert.equal(back, "key-3");
});

test("whitespace and null shape do not count as a changed intent", () => {
    // The server normalises the same way. If the two disagreed, a client that
    // reformats its own payload would be told 409 idempotency_mismatch.
    const holder = createBookingKeyHolder(counter());
    const first = holder.keyFor({ ...INTENT, notes: "Bail  matter" });
    const same = holder.keyFor({ ...INTENT, notes: " Bail matter " });

    assert.equal(first, same);
});

test("a missing case_id and an empty one are the same intent", () => {
    const holder = createBookingKeyHolder(counter());
    const { case_id, ...withoutCase } = INTENT;
    const first = holder.keyFor({ ...withoutCase, case_id: null });
    const same = holder.keyFor(withoutCase);

    assert.equal(first, same);
});

test("the fingerprint distinguishes every booking field", () => {
    const base = bookingIntentFingerprint(INTENT);
    for (const [what, patch] of Object.entries(CHANGES)) {
        assert.notEqual(bookingIntentFingerprint({ ...INTENT, ...patch }), base,
                        `${what} did not change the fingerprint`);
    }
});

test("a real key is unique, non-empty and long enough for the server", () => {
    // The schema requires 8..128 characters, so a mint that produced something
    // shorter would be rejected as a validation error rather than honoured.
    const keys = new Set(Array.from({ length: 200 }, () => mintKey()));
    assert.equal(keys.size, 200, "mintKey collided");
    for (const key of keys) {
        assert.ok(key.length >= 8 && key.length <= 128, `bad key length: ${key}`);
    }
});
