/* Coming back to a document you were part-way through.
 *
 * `docId` lived only in React state. A refresh, a phone locking, a tab restored
 * the next morning — any of them dropped it, and the user was returned to an
 * empty Step 1.
 *
 * The document was never lost. It was on the server the whole time with its
 * revision, its hash and its review status; the client just had no way to say
 * which one it had been looking at. `getDocumentV2` existed, was exported, and
 * was called from nowhere.
 *
 * Regenerating instead is not a neutral fallback: it is a second render, a
 * second version number, and — for a document already sent for review — a
 * second thing in a lawyer's queue that the client cannot tell apart from the
 * first.
 *
 * TWO PURE HALVES, so both can be tested without a DOM: remembering WHICH
 * document, and turning the server's answer back into where the user was. */

export const DRAFT_KEY_PREFIX = "attorneyai.draft.";

/* localStorage is passed in rather than reached for. Three of the four states
 * this has to survive — absent (server render), throwing (private windows,
 * blocked site data), and empty (cleared storage) — are otherwise only
 * reachable by mocking a global. */
function storage(given) {
    if (given !== undefined) return given;
    try {
        return typeof localStorage === "undefined" ? null : localStorage;
    } catch {
        return null;
    }
}

function keyFor(caseId) {
    return `${DRAFT_KEY_PREFIX}${caseId || "no-case"}`;
}

/** Remember the document in progress for a case. Never throws. */
export function rememberDraft(caseId, docId, given) {
    const s = storage(given);
    if (!s || !docId) return;
    try {
        s.setItem(keyFor(caseId), docId);
    } catch {
        // A page that white-screens because it could not save a convenience is
        // a worse failure than not saving it.
    }
}

/** The remembered document for a case, or null. Never throws. */
export function recallDraft(caseId, given) {
    const s = storage(given);
    if (!s) return null;
    try {
        return s.getItem(keyFor(caseId)) || null;
    } catch {
        return null;
    }
}

/** Forget it — the document was finished, or deliberately started again. */
export function forgetDraft(caseId, given) {
    const s = storage(given);
    if (!s) return;
    try {
        s.removeItem(keyFor(caseId));
    } catch {
        /* see rememberDraft */
    }
}

/* Statuses that mean the document has been sent to somebody. The recovery
 * states count: the review is over, unsuccessfully, and the user has to be
 * shown WHY before being asked to do anything. */
const SENT = new Set([
    "submitted", "approved", "returned", "rejected",
    "needs_reapproval", "migration_unrecoverable",
]);

/**
 * Where the user was, from what the server says the document is.
 *
 * Returns null for "nothing to restore" — distinct from a restored document
 * with empty fields, because a caller that cannot tell those apart clears state
 * it should have kept.
 *
 * @param {object|null} detail  a /documents/v2/{id} response
 */
export function restoreStateFromDocument(detail) {
    if (!detail || !detail.id) return null;

    const revision = detail.current_revision || null;
    const status = detail.review_status || "none";
    const sent = SENT.has(status);

    // THE PAIR, TOGETHER OR NOT AT ALL. These two are what `submit` is guarded
    // by; restoring one without the other produces a submission that fails a
    // staleness check with nothing the user can do about it.
    const revisionId = revision ? revision.revision_id || null : null;
    const pdfSha256 = revisionId ? revision.pdf_sha256 || null : null;

    return {
        docId: detail.id,
        docTitle: detail.title || "",
        docRevisionId: revisionId,
        docPdfSha256: pdfSha256,
        docVersion: detail.current_version || 0,
        genDone: Boolean(revisionId),
        reviewSent: sent,
        reviewStatus: sent ? status : null,
        reviewRecovery: detail.recovery || null,
        // 3 = the review panel, where a decision or a recovery explanation is
        // shown; 2 = the generated preview; 1 = the form.
        step: sent ? 3 : revisionId ? 2 : 1,
    };
}
