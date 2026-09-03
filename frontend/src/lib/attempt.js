/* One in-flight attempt: an identity, a generation, and a way to abandon it.
 *
 * WHY ONE ABSTRACTION AND NOT THREE FIXES
 * ---------------------------------------
 * Three separate-looking bugs were the same missing concept — the client had no
 * notion of "the attempt currently in progress":
 *
 *   * a retry after an ambiguous network failure minted a NEW message id, so
 *     the server saw a new turn and ran the provider again. The whole
 *     turn-idempotency mechanism was unreachable from the UI, because replay
 *     needs the SAME id;
 *   * selecting conversation A then B let A's slower response call setMsgs
 *     last, so B's socket was live while A's history was on screen;
 *   * the socket guard checked only OPEN, so a reconnect timer and a
 *     conversation switch could each start a connection.
 *
 * All three are "which attempt is this, and is it still the current one?".
 * Answering that once is less code than answering it three times, and it also
 * gives cancellation and timeouts almost free.
 */

/* A send, with an identity that survives retries.
 *
 * The id is minted ONCE per attempt, not per transmission. That is the whole
 * point: the server deduplicates on it, so a retry of the same attempt replays
 * the first answer instead of paying for a second one. A new id means a new
 * question. */
export function newAttempt(id) {
    return {
        id: id || generateId(),
        tries: 0,
        controller: typeof AbortController !== "undefined" ? new AbortController() : null,
    };
}

/* Marks a retry of the SAME attempt. Keeps the id; a fresh AbortController,
 * because the previous one may already be aborted. */
export function retryAttempt(attempt) {
    return {
        id: attempt.id,
        tries: (attempt.tries || 0) + 1,
        controller: typeof AbortController !== "undefined" ? new AbortController() : null,
    };
}

export function generateId() {
    try {
        if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
    } catch {
        /* fall through */
    }
    return `m-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/* A monotonic counter for "is this response still wanted?".
 *
 * Held in a ref by the component. Every operation that will later write to
 * state takes a ticket before it starts and checks it before it writes; a
 * ticket that is no longer the latest means the user moved on, and the result
 * is dropped rather than racing the newer one onto the screen.
 *
 * Deliberately not an AbortController on its own: aborting stops the request,
 * but a request that already returned still has to be prevented from writing.
 * The counter covers both. */
export function createGeneration() {
    let current = 0;
    return {
        /* Start a new operation. Everything older is now stale. */
        next() {
            current += 1;
            return current;
        },
        /* The ticket in charge right now, WITHOUT claiming it.
         *
         * For an operation that must be cancelled when the user moves on but
         * must not itself cancel anything — loading older messages into the
         * conversation already open, say. Calling `next()` for that would
         * invalidate the very open it is meant to be protected by. */
        current() {
            return current;
        },
        /* Is this ticket still the one in charge? */
        isCurrent(ticket) {
            return ticket === current;
        },
    };
}

/* Should a failed send be retried with the SAME id?
 *
 * Only for failures where the server may or may not have processed the request
 * — a dropped connection, a timeout, a gateway error. Those are exactly the
 * cases where retrying with a NEW id risks a second provider run for one
 * question.
 *
 * A 4xx is a decision the server made and repeating it changes nothing; a 409
 * in particular means the id was already used, which a retry cannot fix. */
export function isAmbiguousFailure(status) {
    if (!status || status === 0) return true;          // network / no response
    return status === 408 || status === 502 || status === 503 || status === 504;
}
