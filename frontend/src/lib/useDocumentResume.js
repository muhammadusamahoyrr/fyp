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
    // An EXPLICIT choice of "no case", distinct from "nothing chosen yet".
    // Without it a standalone document sets the selector to "" and the first
    // case is silently adopted, which drags the document back into a matter it
    // does not belong to.
    if (activeCaseId === NO_CASE) return null;
    if (activeCaseId) return activeCaseId;
    if (Array.isArray(cases) && cases.length > 0) {
        const first = cases[0];
        return (first && (first._id || first.id)) || null;
    }
    return null;
}

/* The selector value meaning "this document belongs to no case".
 *
 * `null` was doing two jobs — "no case" and "we do not know yet" — and code
 * cannot tell them apart, so a standalone draft was either never restored or
 * restored before the case list had arrived. */
export const NO_CASE = "__no_case__";

/**
 * Restore the remembered document for `caseId`, once per case.
 *
 * @param {object}   opts
 * @param {string?}  opts.caseId      the case to restore; `null` means NO case
 * @param {boolean}  opts.ready       the case list has loaded — see below
 * @param {object}   opts.loaded      {hasDocument, caseId} of what is on screen
 * @param {Function} opts.getDocument async (docId) => ({data, error})
 * @param {Function} opts.onRestore   (restoredState | null, caseId) => void
 * @param {object=}  opts.storage     injected for tests
 */
export function useDocumentResume({
    caseId, ready, loaded, getDocument, onRestore, storage,
}) {
    // THE LAST CASE TRIED, not the set of every case ever tried.
    //
    // A permanent Set meant each case was attempted once per session and never
    // again: going A → B → A found A already recorded and returned early, so
    // B's document stayed on screen under A's heading. Remembering only the
    // most recent attempt still stops a re-render refetching, and lets a
    // genuine return to a case restore it.
    //
    // `undefined` rather than null as the initial value, because `null` is a
    // real case id here — it is the standalone bucket.
    const lastAttempted = useRef(undefined);
    // Bumped on every attempt and on unmount. A response whose token is stale
    // belongs to a case the user has already left, and applying it would put
    // another case's document on their screen.
    const token = useRef(0);

    useEffect(() => {
        // NOT BEFORE THE CASE LIST HAS ARRIVED. `caseId` of null means "no
        // case", and on the very first render it would otherwise be
        // indistinguishable from "we have not been told yet" — restoring a
        // standalone draft a moment before the user's real case loads and
        // replaces it.
        if (!ready) return;

        const open = loaded || { hasDocument: false, caseId: null };
        // WHICH case is on screen, not WHETHER anything is. A boolean meant the
        // first loaded document blocked restoration for every case after it, so
        // switching matters kept showing the first matter's draft. A document
        // already open is a reason to skip only when it belongs to the case
        // being asked for.
        if (open.hasDocument && open.caseId === caseId) return;
        if (lastAttempted.current === caseId) return;
        lastAttempted.current = caseId;

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
    }, [caseId, ready, loaded && loaded.hasDocument, loaded && loaded.caseId]);
}
