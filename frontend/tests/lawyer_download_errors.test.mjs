/* Phase 2.6b: a failed PDF download says why.
 *
 * WHAT WAS WRONG. downloadDocumentFile resolves with { error: <string> } rather
 * than throwing. The Documents review and final screens and the Draft
 * Generator ignored the result, so a failed download did nothing at all; My
 * Documents read `.message` off the string and always lost the server's reason.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node", "Event",
                    "CustomEvent", "MouseEvent", "KeyboardEvent", "MutationObserver",
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
const { default: MyDocuments } = await import("../src/components/lawyer/MyDocuments.jsx");
const { DARK } = await import("../src/components/lawyer/theme.js");
const h = React.createElement;

const settle = (ms = 40) => act(async () => { await new Promise(r => setTimeout(r, ms)); });
const REASON = "The stored file does not match its recorded hash.";

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

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer" }, error: null });
    api.__respond("downloadDocumentFile", { error: REASON });
});

test("Documents review screen: a failed download shows its reason", async () => {
    api.__respond("reviewQueueV2", {
        data: { items: [{ id: "d1", title: "Plaint", client_name: "Ayesha", case_id: "c1",
                          review_status: "submitted", submitted_revision_id: "r1" }],
                next_cursor: null, status: "all",
                counts: { all: 1, submitted: 1, approved: 0, returned: 0, rejected: 0 } },
        error: null, status: 200,
    });
    const view = await mount(h(AuthProvider, null, h(DocWorkflowApp)));
    await settle(200);   // auth, then the queue
    // The row's action button opens the review screen.
    await click(button(view.container, b => b.textContent.includes("Review Now")));
    await click(button(view.container, b => b.textContent.includes("Download PDF")));
    const alert = [...view.container.querySelectorAll('[role="alert"]')].find(a => a.textContent.includes(REASON));
    assert.ok(alert, "the download failure was not shown");
    await view.unmount();
});

test("My Documents: the server's reason is shown, not a generic message", async () => {
    api.__respond("myDocumentsV2", {
        data: { items: [{ id: "d1", title: "Plaint", status: "generated", downloadable: true, revision_id: "r1", pdf_sha256: "x" }],
                next_cursor: null },
        error: null, status: 200,
    });
    const view = await mount(h(MyDocuments, { t: DARK }));
    await click(button(view.container, b => b.textContent.trim() === "Download"));
    assert.match(view.container.textContent, /does not match its recorded hash/);
    await view.unmount();
});

test("Draft Generator: every PDF download checks its result", () => {
    // The editor is contentEditable and jsdom has no innerText, so the publish
    // step cannot be driven here; the guard is on the source instead.
    const src = readFileSync(new URL("../src/components/lawyer/DocAutomationPage.jsx", import.meta.url), "utf8");
    const calls = src.split("downloadDocumentFile(").length - 1;
    const checked = (src.match(/const saved = await downloadDocumentFile\(/g) || []).length;
    assert.ok(calls >= 3, "expected the three download sites");
    assert.equal(checked, calls, "a downloadDocumentFile result is ignored");
    assert.equal((src.match(/if \(saved\?\.error\)/g) || []).length, calls);
});
