/* The reviewing lawyer edits the wording and sends it back (2026-10-11).
 *
 * The edit is a RETURN with the lawyer's text, bound to the version and hash
 * the client submitted -- never an approval. Only a document waiting for the
 * lawyer's decision offers it.
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
document.execCommand = () => true;   // jsdom has no editing commands

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
const button = (root, pred) => [...root.querySelectorAll("button")].find(pred);
async function click(el) {
    assert.ok(el, "button not found");
    await act(async () => { el.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
}

function queue(status) {
    return {
        data: { items: [{ id: "d1", title: "Legal notice", client_name: "Ayesha", case_id: null,
                          review_status: status, submitted_revision_id: "r1",
                          submitted_version: 2, submitted_pdf_sha256: "hash-r1" }],
                next_cursor: null, status: "all",
                counts: { all: 1, submitted: status === "submitted" ? 1 : 0,
                          approved: status === "approved" ? 1 : 0, returned: 0, rejected: 0 } },
        error: null, status: 200,
    };
}

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer" }, error: null });
});

test("edit, then send back: a return with the lawyer's text, bound to the submitted version", async () => {
    api.__respond("reviewQueueV2", queue("submitted"));
    api.__respond("getReviewTextV2", { data: { body_html: "<p>Pay Rs 100,000.</p>" }, error: null });
    api.__respond("returnWithEditsV2", { data: { review: { review_status: "returned" } }, error: null, status: 200 });
    const view = await mount(h(AuthProvider, null, h(DocWorkflowApp)));
    await settle(200);
    await click(button(view.container, b => b.textContent.includes("Review Now")));
    await click(button(view.container, b => b.textContent.trim() === "Edit"));

    assert.equal(api.__calls("getReviewTextV2").length, 1);
    const paper = view.container.querySelector(".re-paper");
    assert.ok(paper, "the editor did not open");
    assert.match(paper.innerHTML, /Pay Rs 100,000/);

    const send = button(view.container, b => b.textContent.includes("Send back with my edits"));
    assert.ok(send.disabled, "sending is offered before anything was changed");

    await act(async () => {
        paper.innerHTML = "<p>Pay Rs 250,000 within 30 days.</p>";
        paper.dispatchEvent(new InputEvent("input", { bubbles: true }));
    });
    await settle();
    await click(button(view.container, b => b.textContent.includes("Send back with my edits")));

    const [call] = api.__calls("returnWithEditsV2");
    assert.ok(call, "the edits were not sent");
    const [docId, body] = call.args;
    assert.equal(docId, "d1");
    assert.match(body.bodyHtml, /Rs 250,000 within 30 days/);
    assert.equal(body.expectedVersion, 2);
    assert.equal(body.expectedPdfSha256, "hash-r1");
    assert.equal(api.__calls("reviewDocumentV2").length, 0, "an edit must never be recorded as a plain decision");
    await view.unmount();
});

test("the text typed survives a re-render of the screen", async () => {
    api.__respond("reviewQueueV2", queue("submitted"));
    api.__respond("getReviewTextV2", { data: { body_html: "<p>Original.</p>" }, error: null });
    const view = await mount(h(AuthProvider, null, h(DocWorkflowApp)));
    await settle(200);
    await click(button(view.container, b => b.textContent.includes("Review Now")));
    await click(button(view.container, b => b.textContent.trim() === "Edit"));
    const paper = view.container.querySelector(".re-paper");
    await act(async () => {
        paper.innerHTML = "<p>Typed by the lawyer.</p>";
        paper.dispatchEvent(new InputEvent("input", { bubbles: true }));   // re-renders the screen
    });
    await settle();
    const input = view.container.querySelector('input[placeholder^="Optional"]');
    await act(async () => {
        const set = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set;
        set.call(input, "a note");
        input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await settle();
    assert.match(view.container.querySelector(".re-paper").innerHTML, /Typed by the lawyer/,
        "a re-render wrote the original text back over the lawyer's");
    await view.unmount();
});

test("a decided document offers no Edit", async () => {
    api.__respond("reviewQueueV2", queue("approved"));
    const view = await mount(h(AuthProvider, null, h(DocWorkflowApp)));
    await settle(200);
    const open = button(view.container, b => /Open|Review Now/.test(b.textContent));
    await click(open);
    assert.equal(button(view.container, b => b.textContent.trim() === "Edit"), undefined);
    await view.unmount();
});
