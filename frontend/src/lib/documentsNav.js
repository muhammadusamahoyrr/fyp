/* The sidebar asking the Documents module to show a particular view.
 *
 * Two cases, and one mechanism has to serve both:
 *   - the module is already mounted: it hears the event and switches at once;
 *   - it is not mounted yet (another tab is open): the event would fire before
 *     anyone listens, so the request is also left PENDING and the module takes
 *     it on mount — before the refresh-resume would jump to the open draft.
 *
 * A request is consumed once. Leaving it behind would send every later visit
 * to the home screen, which would break resuming a draft after a refresh.
 */
export const DOCUMENTS_VIEW_EVENT = "attorney:documents-view";
export const DOCUMENTS_VIEWS = ["new", "mine", "drafts", "analyzer", "vault"];

let pending = null;

export function requestDocumentsView(view) {
    if (!DOCUMENTS_VIEWS.includes(view)) return;
    pending = view;
    if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent(DOCUMENTS_VIEW_EVENT, { detail: { view } }));
    }
}

/* The other direction: the module saying which screen it is on, so the
 * sidebar highlights the right section even when the user moved inside the
 * module (a "Vault" button, a back link) rather than through the sidebar. */
export const DOCUMENTS_SHOWN_EVENT = "attorney:documents-shown";

export function announceDocumentsView(view) {
    if (typeof window === "undefined" || !DOCUMENTS_VIEWS.includes(view)) return;
    window.dispatchEvent(new CustomEvent(DOCUMENTS_SHOWN_EVENT, { detail: { view } }));
}

/* The request waiting for the module, without consuming it. Safe to call
 * during render (React may run a state initialiser twice). */
export function peekPendingDocumentsView() {
    return pending;
}

/* The request waiting for the module, or null. Reading it clears it. */
export function takePendingDocumentsView() {
    const view = pending;
    pending = null;
    return view;
}
