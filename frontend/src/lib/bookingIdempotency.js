/**
 * The client half of booking idempotency.
 *
 * The server recognises a retry by `(client_id, idempotency_key)` and replays
 * the original appointment instead of creating a second one. That only works if
 * the client sends THE SAME KEY when it retries — a key minted per request is
 * indistinguishable from a new booking, and turns a double-submit into two
 * appointments, which is the exact outcome the mechanism exists to prevent.
 *
 * So the key belongs to the INTENT, not to the request. It survives a failed
 * attempt, a network error and an impatient second click. It is replaced when
 * the intent changes (a different lawyer, time, duration, mode or note) or when
 * the booking completes, because at that point the next submission genuinely is
 * a new booking and reusing the key would make the server replay the old one.
 *
 * Kept pure and separate from the component so the rule can be tested directly
 * rather than inferred from rendering a modal.
 */

/** A stable description of what is being booked.
 *
 * Mirrors the fields the SERVER fingerprints, so the two agree about what
 * counts as "the same booking". If they disagree, the client reuses a key for
 * something the server considers different and the retry is refused as an
 * idempotency mismatch instead of replaying.
 */
export function bookingIntentFingerprint(intent) {
    if (!intent) return "";
    const norm = (s) => String(s ?? "").trim().replace(/\s+/g, " ");
    return JSON.stringify([
        norm(intent.lawyer_id),
        norm(intent.case_id),
        norm(intent.scheduled_at),
        Number(intent.duration_minutes) || 0,
        norm(intent.mode),
        norm(intent.notes),
    ]);
}

/** A fresh key. UUID where available, random hex otherwise. */
export function mintKey() {
    const c = typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
    if (c && typeof c.randomUUID === "function") return `bk_${c.randomUUID()}`;
    if (c && typeof c.getRandomValues === "function") {
        const bytes = c.getRandomValues(new Uint8Array(16));
        return `bk_${[...bytes].map(b => b.toString(16).padStart(2, "0")).join("")}`;
    }
    // Last resort. Only reached in an environment with no Web Crypto at all;
    // a collision here costs a refused retry, not a wrong appointment, because
    // the server still checks the payload fingerprint before replaying.
    return `bk_${Date.now().toString(16)}${Math.random().toString(16).slice(2, 10)}`;
}

/**
 * Holds one key for one intent.
 *
 * `keyFor(intent)` returns the SAME key for as long as the intent is unchanged
 * and unfinished, and a new one as soon as it changes. `complete()` retires the
 * current key so the next booking starts a new one.
 */
export function createBookingKeyHolder(mint = mintKey) {
    let fingerprint = null;
    let key = null;

    return {
        keyFor(intent) {
            const next = bookingIntentFingerprint(intent);
            if (key === null || next !== fingerprint) {
                fingerprint = next;
                key = mint();
            }
            return key;
        },
        /** The booking succeeded — the next one is a different booking. */
        complete() {
            fingerprint = null;
            key = null;
        },
        /** For assertions and debugging; not part of the booking flow. */
        current() {
            return key;
        },
    };
}
