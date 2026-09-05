/* Restoring a part-finished document after a refresh — the lifecycle half.
 *
 * `documentResume.js` holds the pure pieces: which document was remembered, and
 * how a server response maps back to where the user was. This is the part that
 * has to happen at the right MOMENT, and getting that wrong is what made the
 * first attempt inert:
 *
 *   * THE CASE ID ARRIVED LATE. Restoration keyed off `genCaseId`, which is set
 *     during generation and starts null. After a refresh there is no generation,
 *     so it stayed null, the effect returned early every time, and nothing was
 *     ever restored. The feature existed and never ran.
 *
 *   * THE SAVE USED STATE INSTEAD OF THE VALUE. `rememberDraft(genCaseId, …)`
 *     called just after `setGenCaseId(caseId)` reads the state from the render
 *     that is still on screen, not the value just resolved — so the first
 *     generation for a case saved under the PREVIOUS case, or under null.
 *
 *   * A ONE-SHOT GUARD BLOCKED CASE SWITCHES. A single `resumedRef` meant the
 *     first restoration attempt disabled every later one, so moving to another
 *     matter showed the first matter's document, or nothing.
 *
 *   * A LATE RESPONSE COULD LAND ON THE WRONG CASE. Two switches in quick
 *     succession leave two requests in flight; without a guard the slower one
 *     wins and the user is looking at a document from a case they have left.
 *
 * The last one is the reason this is a hook and not a function. Getting it right
 * needs the render lifecycle — a token captured per attempt and checked after
 * every await — and that is exactly what a source-level test cannot observe. */

import { useEffect, useRef } from "react";

import { recallDraft, forgetDraft, restoreStateFromDocument } from "./documentResume.js";

/* The document is not coming back — as opposed to not arriving right now.
 *
 * Only a definitive answer from the server counts. A 404 means it is deleted; a
 * 403 means it is no longer ours. Both are facts about the document, and the
 * saved pointer should go.
 *
 * A timeout, a 5xx, a refused connection, an unparseable body: those are facts
 * about the attempt. Erasing a pointer because one request failed destroys the
 * user's only route back to work that is sitting safely on the server.
 */
export function isDefinitivelyGone(error) {
    if (!error) return false;
    if (error.status === 404 || error.status === 403) return true;
    return error.code === "not_found" || error.code === "forbidden";
}

/**
 * The case whose documents are on screen.
 *
 * After a refresh there is no "case the document was generated for" yet, so the
 * active case has to be derived from what actually loaded. An explicit
 * selection wins; otherwise the first case is the one being looked at.
 */
export function resolveCaseId(activeCaseId, cases) {
    if (activeCaseId) return activeCaseId;
    if (Array.isArray(cases) && cases.length > 0) {
        const first = cases[0];
        return (first && (first._id || first.id)) || null;
    }
    return null;
}

/**
 * Restore the remembered document for `caseId`, once per case.
 *
 * @param {object}   opts
 * @param {string?}  opts.caseId        resolved case; null until cases load
 * @param {string?}  opts.loadedCaseId  the case the OPEN document belongs to
 * @param {Function} opts.getDocument   async (docId) => ({data, error})
 * @param {Function} opts.onRestore     (restoredState | null, caseId) => void
 * @param {object=}  opts.storage       injected for tests
 */
export function useDocumentResume({
    caseId, loadedCaseId, getDocument, onRestore, storage,
}) {
    // PER CASE, not once ever. A single boolean would let the first attempt
    // disable every later one, so switching matters would show the previous
    // matter's document or nothing at all.
    const attempted = useRef(new Set());
    // Bumped on every attempt and on unmount. A response whose token is stale
    // belongs to a case the user has already left, and applying it would put
    // another case's document on their screen.
    const token = useRef(0);

    useEffect(() => {
        if (!caseId) return;
        // WHICH case is loaded, not WHETHER one is.
        //
        // This was `hasDocument`, a boolean, so the moment any document was on
        // screen the hook refused to run for ANY case — including one the user
        // had just switched to. The first case's draft followed them around and
        // the second case's own draft was unreachable. A document already open
        // is only a reason to skip when it belongs to the case being asked for.
        if (loadedCaseId && loadedCaseId === caseId) return;
        if (attempted.current.has(caseId)) return;
        attempted.current.add(caseId);

        const mine = ++token.current;
        let cancelled = false;

        const saved = recallDraft(caseId, storage);
        if (!saved) {
            // TOLD, not silently skipped. Without this the previous case's
            // document stays on screen under the new case's heading — the same
            // wrong-matter confusion reached from the other direction.
            onRestore(null, caseId);
            return;
        }

        (async () => {
            const { data, error } = await getDocument(saved);
            if (cancelled || token.current !== mine) return;

            if (error || !data) {
                // A FAILURE TO ASK IS NOT AN ANSWER.
                //
                // This forgot the draft on ANY error, so a dropped connection
                // was treated exactly like a deleted document: one bad response
                // on a train and the in-progress draft became unreachable,
                // permanently, because the only pointer to it had been erased.
                //
                // 404 and 403 ARE answers — the document is gone or is no
                // longer ours, and retrying forever against it is the opposite
                // mistake. Everything else is the network or the server having
                // a bad moment, and the pointer survives for the next mount.
                if (isDefinitivelyGone(error)) forgetDraft(caseId, storage);
                onRestore(null, caseId);
                return;
            }
            const restored = restoreStateFromDocument(data);
            if (!restored) {
                forgetDraft(caseId, storage);
                onRestore(null, caseId);
                return;
            }
            onRestore(restored, caseId);
        })();

        return () => {
            cancelled = true;
            // Invalidate anything still in flight for this case.
            token.current++;
        };
        // `onRestore` and `getDocument` are deliberately not dependencies: they
        // are recreated on every render of the parent, and including them would
        // re-run this effect continuously.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [caseId, loadedCaseId]);
}
