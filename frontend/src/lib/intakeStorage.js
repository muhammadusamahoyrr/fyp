/* What the browser remembers about an intake in progress.
 *
 * WHY THIS IS SCOPED BY USER
 * --------------------------
 * The intake token and the converted case id were stored under two fixed keys,
 * `aai-intake-token` and `aai-case-id`, shared by every account that ever used
 * the browser. Sign-out cleared neither.
 *
 * That is not a stale-value annoyance, it is a dead end. ModIntake calls
 * `intakeStart()` ONLY when it finds no saved token. So the next person to sign
 * in on the same machine inherited the previous user's token, skipped session
 * creation, and then had every intake call rejected — the server checks
 * `client_id` on the session and correctly refuses. The new user could not
 * start an intake at all, and nothing in the UI explained why.
 *
 * The user id is part of the key rather than something verified after reading,
 * for the same reason it is in `conversations.js`: a check is one forgotten
 * branch away from the bug it prevents. A different account reads a different
 * key and finds nothing, which is the correct outcome by construction.
 *
 * Every access is wrapped. Storage throws outright in some privacy modes, and
 * an intake that cannot be resumed is a much smaller problem than an intake
 * page that will not render.
 */

const KEY_PREFIX = "aai-intake";

/* The unscoped keys this module replaced. Cleared on sign-out so an existing
 * browser does not keep carrying one around after the upgrade — and, more to
 * the point, so anyone already stuck behind a foreign token gets out of it. */
const LEGACY_KEYS = ["aai-intake-token", "aai-case-id"];

function store() {
    try {
        if (typeof localStorage !== "undefined" && localStorage) return localStorage;
    } catch {
        /* blocked entirely */
    }
    return null;
}

/* localStorage, not sessionStorage — unlike an active conversation, an intake
 * in progress should survive closing the tab. It is a form someone is part way
 * through, not a view state. */
function scopedKey(name, userId) {
    if (!name || !userId) return null;
    return `${KEY_PREFIX}:${userId}:${name}`;
}

export function readIntakeValue(name, userId) {
    const key = scopedKey(name, userId);
    if (!key) return null;
    try {
        return store()?.getItem(key) || null;
    } catch {
        return null;
    }
}

export function writeIntakeValue(name, userId, value) {
    const key = scopedKey(name, userId);
    if (!key) return;
    try {
        const s = store();
        if (!s) return;
        if (value) s.setItem(key, value);
        else s.removeItem(key);
    } catch {
        /* the value is still good for this page's lifetime */
    }
}

export function clearIntakeValue(name, userId) {
    writeIntakeValue(name, userId, null);
}

/* Drop every remembered intake, for every user, plus the legacy unscoped keys.
 *
 * Called on sign-out. Scoping already stops the next account from READING the
 * previous one's token, but an abandoned intake token on a shared machine is
 * still a pointer to someone's unfinished legal problem, and it costs nothing
 * to clear on the way out. */
export function clearAllIntakeValues() {
    const s = store();
    if (!s) return;
    try {
        const doomed = [];
        for (let i = 0; i < s.length; i += 1) {
            const key = s.key(i);
            if (key && key.startsWith(`${KEY_PREFIX}:`)) doomed.push(key);
        }
        doomed.forEach(k => s.removeItem(k));
        LEGACY_KEYS.forEach(k => s.removeItem(k));
    } catch {
        /* storage blocked; nothing to clear */
    }
}
