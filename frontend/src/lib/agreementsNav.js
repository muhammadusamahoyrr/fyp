/* The sidebar asking the Agreements module to show one of its pages, and the
 * module saying which page it is on. The same two-way mechanism as
 * lib/documentsNav.js: a request is left PENDING for a module that is not
 * mounted yet, and consumed once.
 *
 * The page list lived in the module's own inner sidebar until 2026-10-11; it
 * now sits under "Agreements" in the client sidebar, as Documents' does. */
export const AGREEMENTS_VIEW_EVENT = "attorney:agreements-view";
export const AGREEMENTS_SHOWN_EVENT = "attorney:agreements-shown";

/* The DIY builder (Templates, Create) is parked behind this flag -- see the
 * note at its use in ModAgreements.jsx. Here so the sidebar and the module
 * read the same switch. */
export const AGREEMENTS_DIY_ENABLED =
    (typeof process !== "undefined" &&
        process.env?.NEXT_PUBLIC_AGREEMENTS_DIY_ENABLED === "true") || false;

export const AGREEMENTS_VIEWS = ["dashboard", "templates", "create", "all"];

let pending = null;

export function requestAgreementsView(view) {
    if (!AGREEMENTS_VIEWS.includes(view)) return;
    pending = view;
    if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent(AGREEMENTS_VIEW_EVENT, { detail: { view } }));
    }
}

export function takePendingAgreementsView() {
    const view = pending;
    pending = null;
    return view;
}

export function announceAgreementsView(view) {
    if (typeof window === "undefined" || !AGREEMENTS_VIEWS.includes(view)) return;
    window.dispatchEvent(new CustomEvent(AGREEMENTS_SHOWN_EVENT, { detail: { view } }));
}
