/* Quick document review, the lawyer's side (2026-10-11).
 *
 * Requests from clients who have not hired the lawyer sit at the top of the
 * Documents inbox -- title, client, note and terms only. Accepting opens the
 * document in the ordinary review screen; declining just answers. The lawyer
 * sets the offer itself in Settings.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node", "Event",
                    "CustomEvent", "MouseEvent", "KeyboardEvent", "InputEvent", "MutationObserver",
                    "getComputedStyle", "localStorage", "sessionStorage"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { AuthProvider } = await import("../src/context/AuthContext.jsx");
const { DocWorkflowApp } = await import("../src/components/lawyer/DocumentsPage.jsx");
const h = React.createElement;

const settle = (ms = 40) => act(async () => { await new Promise(r => setTimeout(r, ms)); });
async function mount(el) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(el); });
    await settle();
    return { container, unmount: async () => { await act(async () => root.unmount()); container.remove(); } };
}
async function click(el) {
    assert.ok(el, "button not found");
    await act(async () => { el.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
}

const REQ = { id: "q1", doc_id: "d9", status: "requested", doc_title: "Rent notice", template_type: "legal_notice",
    version: 3, client_name: "Usman Ali", note: "Is the deadline right?", fee_pkr: 2500, turnaround_hours: 24,
    expires_at: new Date(Date.now() + 10 * 3600000).toISOString() };
const empty = { data: { items: [], next_cursor: null, status: "all",
    counts: { all: 0, submitted: 0, approved: 0, returned: 0, rejected: 0 } }, error: null, status: 200 };
const withDoc = { data: { items: [{ id: "d9", title: "Rent notice", client_name: "Usman Ali", case_id: null,
    review_status: "submitted", quick_review: true, submitted_revision_id: "r3", submitted_version: 3,
    submitted_pdf_sha256: "h3", client_note: "Is the deadline right?" }], next_cursor: null, status: "all",
    counts: { all: 1, submitted: 1, approved: 0, returned: 0, rejected: 0 } }, error: null, status: 200 };

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer" }, error: null });
});

test("waiting requests head the inbox: title, client, note and terms -- not the document", async () => {
    api.__respond("reviewQueueV2", empty);
    api.__respond("quickReviewInbox", { data: { items: [REQ] }, error: null });
    const view = await mount(h(AuthProvider, null, h(DocWorkflowApp)));
    await settle(150);
    const row = view.container.querySelector('[data-quick-request="q1"]');
    assert.ok(row, "the request is not shown");
    assert.match(row.textContent, /Rent notice.*Quick review.*Legal Notice · v3.*Is the deadline right\?.*Usman Ali.*Accept within 10h.*Rs 2,500.*Due 24h after accepting/s);
    assert.equal(api.__calls("fetchRevisionPreview").length, 0, "nothing of the document is fetched before accepting");
    await view.unmount();
});

test("accepting opens the document in the normal review screen, marked as a quick review", async () => {
    api.__respond("reviewQueueV2", empty);
    api.__respond("quickReviewInbox", { data: { items: [REQ] }, error: null });
    api.__respond("acceptQuickReview", { data: { ...REQ, status: "accepted" }, error: null });
    const view = await mount(h(AuthProvider, null, h(DocWorkflowApp)));
    await settle(150);
    api.__respond("reviewQueueV2", withDoc);
    api.__respond("quickReviewInbox", { data: { items: [] }, error: null });
    await click(view.container.querySelector('[data-quick-request="q1"] [data-quick-accept]'));
    await settle(150);
    assert.equal(api.__calls("acceptQuickReview")[0].args[0], "q1");
    assert.ok(view.container.querySelector("[data-review-ws]"), "the review screen did not open");
    assert.match(view.container.textContent, /Rent notice/);
    await view.unmount();
});

test("a pending row from a quick review says so, and that it has no case", async () => {
    api.__respond("reviewQueueV2", withDoc);
    api.__respond("quickReviewInbox", { data: { items: [] }, error: null });
    const view = await mount(h(AuthProvider, null, h(DocWorkflowApp)));
    await settle(150);
    const row = view.container.querySelector('[data-inbox-row="d9"]');
    assert.ok(row.querySelector("[data-quick-row]"));
    assert.match(row.textContent, /Review only · no case/);
    assert.equal(view.container.querySelector("[data-quick-requests]"), null, "no empty requests card");
    await view.unmount();
});

test("declining answers the request and removes it", async () => {
    api.__respond("reviewQueueV2", empty);
    api.__respond("quickReviewInbox", { data: { items: [REQ] }, error: null });
    api.__respond("declineQuickReview", { data: { ...REQ, status: "declined" }, error: null });
    const view = await mount(h(AuthProvider, null, h(DocWorkflowApp)));
    await settle(150);
    api.__respond("quickReviewInbox", { data: { items: [] }, error: null });
    await click(view.container.querySelector('[data-quick-request="q1"] [data-quick-decline]'));
    await settle(80);
    assert.equal(api.__calls("declineQuickReview")[0].args[0], "q1");
    assert.equal(view.container.querySelector('[data-quick-request="q1"]'), null);
    await view.unmount();
});
