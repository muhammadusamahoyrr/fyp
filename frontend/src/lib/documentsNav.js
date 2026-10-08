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
// No "analyzer": the Document Analyzer is a lawyer's tool (2026-10-03), on the
// lawyer dashboard only. A request for it is ignored here.
export const DOCUMENTS_VIEWS = ["new", "mine", "drafts", "vault"];

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

/* THE OPEN DOCUMENT IN THE ADDRESS (2026-10-08): `/documents?doc=<id>`.
 *
 * A hard refresh used to lose the open document: the module's screen and the
 * open document lived only in component state, and the one resume path is
 * deliberately off on a reload. The document's id now rides in the address --
 * the same way the review-request deep link already does -- so a refresh
 * reopens THAT document, read fresh from the server: its latest version, its
 * status with the lawyer. Nothing else is kept: panels, drafts of a note and
 * other passing UI state are not persisted.
 *
 * `view=preview` marks the Vault's read-only preview; without it the document
 * opens in the drafting workspace. Written with replaceState, keeping the
 * router's own history state, so it adds no history entry. */
const DOC_ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

export function readOpenDocumentLink(search) {
    const params = new URLSearchParams(typeof search === "string" ? search : "");
    const id = params.get("doc");
    if (!id || !DOC_ID_RE.test(id)) return null;
    return { id, preview: params.get("view") === "preview" };
}

function writeDocParams(update) {
    if (typeof window === "undefined" || !window.history?.replaceState) return;
    try {
        const url = new URL(window.location.href);
        update(url.searchParams);
        const next = `${url.pathname}${url.searchParams.toString() ? `?${url.searchParams}` : ""}${url.hash}`;
        if (next !== `${window.location.pathname}${window.location.search}${window.location.hash}`) {
            window.history.replaceState(window.history.state, "", next);
        }
    } catch { /* the address is a convenience; the screen does not depend on it */ }
}

export function linkOpenDocument(id, { preview = false } = {}) {
    if (!id || !DOC_ID_RE.test(String(id))) return;
    writeDocParams(params => {
        params.set("doc", String(id));
        if (preview) params.set("view", "preview"); else params.delete("view");
    });
}

export function unlinkOpenDocument() {
    writeDocParams(params => { params.delete("doc"); params.delete("view"); });
}

/* Open ONE document (2026-10-08): a notification about a lawyer's decision
 * opens that document in the drafting workspace. Same two cases as a view: the
 * module may be mounted (the event) or not yet (the pending id). */
export const DOCUMENT_OPEN_EVENT = "attorney:documents-open";
let pendingDocument = null;

export function requestOpenDocument(id) {
    if (!id) return;
    pendingDocument = String(id);
    if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent(DOCUMENT_OPEN_EVENT, { detail: { id: pendingDocument } }));
    }
}

/* The document waiting to be opened, or null. Reading it clears it. */
export function takePendingDocument() {
    const id = pendingDocument;
    pendingDocument = null;
    return id;
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
