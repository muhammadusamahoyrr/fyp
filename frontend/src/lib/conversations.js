/* Turning a stored conversation back into what the user was looking at.
 *
 * WHY THIS IS SHARED AND PURE
 * ---------------------------
 * A reloaded answer has to be qualified exactly as it was when it was first
 * given. The server keeps every trust signal — citation status, claim support,
 * calibrated band, jurisdiction, request id — but the two chat surfaces hold
 * answers in slightly different shapes (`text`/`refs` on the client,
 * `content`/`citations` on the lawyer page), so the rehydration is the place
 * where a signal quietly fails to come back. Keeping it here, with no React in
 * it, means it can be tested directly rather than inferred from a screenshot.
 *
 * WHAT "RESTORED" HAS TO MEAN
 * ---------------------------
 * An answer that reloads WITHOUT its repeal warning, or with its claim support
 * missing, looks more trustworthy than the one that was originally shown. That
 * is the failure mode worth guarding: losing a qualification is not a cosmetic
 * regression, it is the answer changing its mind about how sure it was.
 */

import { normaliseCitations } from "./trust.js";

/* The session id survives a refresh here.
 *
 * The browser used to mint a fresh id on every mount, so a reload started a new
 * conversation and the previous one became unreachable — it was still in the
 * database, with no id anywhere that pointed at it. The id is now a server
 * fact, and this is only where the tab remembers which one it was looking at. */
const SURFACES = ["client", "research"];
const KEY_PREFIX = "aai-active";

/* Scoped by USER and by SURFACE.
 *
 * A single shared key had two failures that both end with someone looking at
 * the wrong conversation. Signing out and signing in as a different user left
 * the previous user's session id in storage, and the next page load tried to
 * open it — refused by the server, but the UI still asked. And a lawyer with
 * both surfaces open had each overwrite the other's remembered thread.
 *
 * The user id is part of the key rather than something checked after reading,
 * because a check is one forgotten branch away from the bug it prevents. A
 * different user simply reads a different key and finds nothing. */
function activeKey(surface, userId) {
    if (!SURFACES.includes(surface) || !userId) return null;
    return `${KEY_PREFIX}:${userId}:${surface}`;
}

/* sessionStorage, not localStorage.
 *
 * Two tabs must keep their OWN active conversation while sharing the same
 * server history — that is what "open this thread in another tab" means. It is
 * per-tab in every browser, and survives a reload, which is exactly the scope
 * "which conversation is this tab looking at" has. localStorage would make the
 * two tabs fight over one value, and a reload in either would land on whichever
 * wrote last.
 *
 * Falls back to localStorage only where sessionStorage is missing; a remembered
 * conversation is a convenience, and the fallback is better than losing it. */
function store() {
    try {
        if (typeof sessionStorage !== "undefined" && sessionStorage) return sessionStorage;
    } catch {
        /* blocked; try the fallback */
    }
    try {
        if (typeof localStorage !== "undefined" && localStorage) return localStorage;
    } catch {
        /* blocked entirely */
    }
    return null;
}

export function readActiveSession(surface, userId) {
    const key = activeKey(surface, userId);
    if (!key) return null;
    try {
        return store()?.getItem(key) || null;
    } catch {
        // Private mode, or storage disabled. A conversation that cannot be
        // remembered is not an error — the user gets a new one.
        return null;
    }
}

export function writeActiveSession(surface, userId, sessionId) {
    const key = activeKey(surface, userId);
    if (!key) return;
    try {
        const s = store();
        if (!s) return;
        if (sessionId) s.setItem(key, sessionId);
        else s.removeItem(key);
    } catch {
        /* nothing to do — the id is still valid for this tab's lifetime */
    }
}

/* Drop every remembered conversation, for every user and both surfaces.
 *
 * Called on sign-out and on an account change. Scoping by user id already means
 * the next user cannot read the previous one's key, but leaving the value
 * behind keeps a record of which conversation someone was reading on a shared
 * machine, and that is worth clearing on the way out. */
export function clearActiveSessions() {
    for (const s of [(() => { try { return sessionStorage; } catch { return null; } })(),
                     (() => { try { return localStorage; } catch { return null; } })()]) {
        if (!s) continue;
        try {
            const doomed = [];
            for (let i = 0; i < s.length; i += 1) {
                const key = s.key(i);
                if (key && key.startsWith(`${KEY_PREFIX}:`)) doomed.push(key);
            }
            doomed.forEach(k => s.removeItem(k));
            // The pre-scoping keys, so an existing session does not keep a
            // stale value forever after an upgrade.
            s.removeItem("aai-active-conversation");
            s.removeItem("aai-active-research");
        } catch {
            /* storage blocked; nothing to clear */
        }
    }
}

/* A stored message, as the CLIENT chatbot renders it. */
export function toClientMessage(stored) {
    const m = stored || {};
    const isUser = m.role === "user";
    return {
        role: isUser ? "user" : "ai",
        text: m.content || "",
        time: formatTime(m.created_at),
        // `refs` is the client's name for citations. Normalised through the
        // same function a live answer goes through, so a restored chip carries
        // the same status, repeal currency and source link a live one does.
        refs: isUser ? [] : normaliseCitations(m.citations),
        claims: isUser ? [] : (m.claims || []),
        confidence: m.confidence,
        confidenceBand: m.confidence_band,
        status: m.convergence_status,
        jurisdiction: m.jurisdiction,
        jurisdictionBasis: m.jurisdiction_basis,
        historySaved: true,
        // Restored from what was STORED, not assumed. Unlike `historySaved`,
        // this cannot be inferred from the message existing: the message and
        // its provenance record are two writes that fail independently, so a
        // message sitting in the conversation says nothing about whether its
        // audit record was ever written. Absent on messages stored before this
        // was recorded — treated as saved, because the alternative is warning
        // about every old answer on a suspicion the data cannot support.
        auditSaved: m.audit_saved !== false,
        auditPending: m.audit_pending === true,
        requestId: m.request_id || "",
        // The immutable server id and its position in the conversation. Both
        // are needed to reconcile a reload against what the tab already shows.
        id: m.id || null,
        seq: typeof m.seq === "number" ? m.seq : null,
        // Restored history is not re-rated: the rating was already given, or
        // the moment for it has passed.
        restored: true,
    };
}

/* A stored message, as the LAWYER research page renders it. */
export function toResearchMessage(stored) {
    const m = stored || {};
    const isUser = m.role === "user";
    return {
        role: isUser ? "user" : "assistant",
        content: m.content || "",
        time: formatTime(m.created_at),
        citations: isUser ? [] : normaliseCitations(m.citations),
        claims: isUser ? [] : (m.claims || []),
        confidence: m.confidence,
        confidenceBand: m.confidence_band,
        modelConfidence: m.model_confidence,
        arbitrationSource: m.arbitration_source,
        // Kept for the same reason the client keeps them: an answer that
        // reloads without the jurisdiction it assumed is quietly claiming less
        // than it did when it was given. The backend stores all three.
        jurisdiction: m.jurisdiction,
        jurisdictionBasis: m.jurisdiction_basis,
        convergenceStatus: m.convergence_status,
        // False when the turn ran but the answer was never filed. A restored
        // message is by definition filed, so it is true here — the flag matters
        // on a LIVE answer, where it warns that a refresh will lose it.
        historySaved: true,
        // Restored from what was STORED, not assumed. Unlike `historySaved`,
        // this cannot be inferred from the message existing: the message and
        // its provenance record are two writes that fail independently, so a
        // message sitting in the conversation says nothing about whether its
        // audit record was ever written. Absent on messages stored before this
        // was recorded — treated as saved, because the alternative is warning
        // about every old answer on a suspicion the data cannot support.
        auditSaved: m.audit_saved !== false,
        auditPending: m.audit_pending === true,
        requestId: m.request_id || "",
        id: m.id || null,
        seq: typeof m.seq === "number" ? m.seq : null,
        restored: true,
    };
}

export function toClientMessages(stored) {
    return (stored || []).map(toClientMessage);
}

export function toResearchMessages(stored) {
    return (stored || []).map(toResearchMessage);
}

export function formatTime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/* Sidebar grouping. The old list was two hardcoded strings under "Last Week"
 * that opened nothing; these are real conversations with real timestamps. */
export function groupConversations(rows, now = new Date()) {
    const today = [];
    const week = [];
    const earlier = [];
    const startOfToday = new Date(now);
    startOfToday.setHours(0, 0, 0, 0);
    const weekAgo = new Date(startOfToday);
    weekAgo.setDate(weekAgo.getDate() - 7);

    for (const row of rows || []) {
        const when = new Date(row.updated_at || row.created_at || 0);
        if (Number.isNaN(when.getTime())) earlier.push(row);
        else if (when >= startOfToday) today.push(row);
        else if (when >= weekAgo) week.push(row);
        else earlier.push(row);
    }
    return [
        { group: "Today", items: today },
        { group: "Previous 7 days", items: week },
        { group: "Earlier", items: earlier },
    ].filter(g => g.items.length > 0);
}

/* Merge a page of restored history into what the tab already shows.
 *
 * Reconciled on the immutable server message id, NOT on position or content.
 * A live answer and the same answer arriving from a reload are one message, and
 * two different questions with identical text are two — position gets both of
 * those wrong, and content gets the second one wrong.
 *
 * Messages with no id (an optimistic local echo that has not been stored yet)
 * are kept as they are: they are the only copy of themselves. */
export function mergeMessages(existing, incoming) {
    const seen = new Map();
    const out = [];
    for (const message of [...(existing || []), ...(incoming || [])]) {
        const id = message?.id;
        if (!id) { out.push(message); continue; }
        if (seen.has(id)) {
            // The later copy wins: a restored message carries the stored
            // metadata, which is at least as complete as the live one.
            out[seen.get(id)] = message;
            continue;
        }
        seen.set(id, out.length);
        out.push(message);
    }
    // Stable chronological order. `seq` is server-allocated and unique per
    // conversation; anything without one is a local echo and belongs last.
    return out.sort((a, b) => {
        const sa = typeof a?.seq === "number" ? a.seq : Number.MAX_SAFE_INTEGER;
        const sb = typeof b?.seq === "number" ? b.seq : Number.MAX_SAFE_INTEGER;
        return sa - sb;
    });
}

/* An id for one send, so a retry cannot duplicate the message.
 *
 * The server deduplicates on this: appending is `$ne` on the id inside the
 * update filter, so a resent frame or a double-clicked button matches nothing
 * and writes nothing. */
export function newMessageId() {
    try {
        if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
    } catch {
        /* fall through */
    }
    return `m-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
