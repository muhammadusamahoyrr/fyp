/* One Idempotency-Key per user intent, for the one-click document tools.
 *
 * The backend replays a request it has already fulfilled when the SAME key
 * arrives with the SAME request, and refuses (409) the same key with a
 * different one. Without a key it mints its own, so a retry after a lost
 * response — a slow render, a dropped connection, a second click — made a
 * second document.
 *
 * The intent here is "this request": the key is kept while the request is
 * unchanged, so a retry or a double click reuses it and gets the same document
 * back, and a new key is minted the moment anything in the request changes,
 * because that is a different document. Held in a React ref so a re-render
 * between a failure and its retry cannot lose it.
 *
 * Self-contained (no import of the API client) so a component test that stubs
 * the client is not handed a second, real one through this module.
 */

function mint() {
    try {
        if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
    } catch {
        /* fall through */
    }
    return `k-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

function signature(payload) {
    try {
        return JSON.stringify(payload ?? null);
    } catch {
        return null;   // unserialisable: never treat two of these as the same request
    }
}

export function keyForIntent(ref, payload) {
    const sig = signature(payload);
    if (!ref.current || sig === null || ref.current.sig !== sig) {
        ref.current = { sig, key: mint() };
    }
    return ref.current.key;
}
