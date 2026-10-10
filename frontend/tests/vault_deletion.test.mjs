/* Recoverable Vault deletion, client UI.
 *
 * The warnings are the server's (deletion preview) in the client's words; the
 * Delete button waits for them and refuses a document under review; Delete
 * and Restore send once however often they are clicked; "Recently deleted"
 * restores until the recovery period ends and says so after. */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/documents" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node", "Event", "CustomEvent",
                    "KeyboardEvent", "MutationObserver", "getComputedStyle", "DOMParser"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const vd = await import("../src/lib/vaultDeletion.js");
const { DeleteDocumentDialog } = await import("../src/components/client/documents/VaultTrash.jsx");
const { default: DocsVault } = await import("../src/components/client/documents/DocsVault.jsx");
const { ToastCtx } = await import("../src/components/shared/Toast.jsx");
const h = React.createElement;

const PREVIEW = { id: "d1", title: "Shop rent agreement", recoverable_days: 30, purge_after: "2026-11-02T10:00:00Z",
                  blocked: null, open_review_requests: 0, accepted_reviews: [] };
const ROW = { id: "d1", title: "Shop rent agreement", revision_id: "r1", pdf_sha256: "a".repeat(64), downloadable: true, version: 1 };

const mounted = new Set();
const toasts = [];
async function mount(el) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(h(ToastCtx.Provider, { value: { show: m => toasts.push(m) } }, el)); });
    await settle();
    const unmount = async () => {
        if (!mounted.has(unmount)) return;
        mounted.delete(unmount);
        await act(async () => root.unmount());
        container.remove();
    };
    mounted.add(unmount);
    return { container, unmount };
}
const settle = (ms = 20) => act(async () => { await new Promise(r => setTimeout(r, ms)); });
const btn = (root, text) => [...root.querySelectorAll("button")].find(b => b.textContent.trim() === text);
const dialog = () => document.body.querySelector("[data-delete-dialog]");
async function click(el) {
    assert.ok(el, "nothing to click");
    await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
    await settle();
}

test.beforeEach(() => { api.__reset(); toasts.length = 0; });
test.afterEach(async () => {
    for (const u of [...mounted]) await u();
    document.body.innerHTML = "";
});

test("the warnings say what deleting does, in order", () => {
    assert.deepEqual(vd.deletionWarnings({ ...PREVIEW, blocked: "Withdraw it first." }), ["Withdraw it first."]);
    const [first] = vd.deletionWarnings(PREVIEW);
    assert.match(first, /Recently deleted.*restore it for 30 days \(until 2 Nov 2026\)/);
    const busy = vd.deletionWarnings({ ...PREVIEW, open_review_requests: 2, accepted_reviews: [
        { lawyer_name: "Adv. Bilal", version: 3, read_only_until: "2026-11-02T10:00:00Z" }] });
    assert.match(busy[1], /Your 2 open review requests .* will be cancelled, and your lawyer will be told/);
    assert.match(busy[1], /does not reopen them/);
    assert.match(busy[2], /Adv\. Bilal accepted a review of version 3 and keeps read-only access .* until 2 Nov 2026/);
    assert.match(vd.deletionWarnings({ ...PREVIEW, open_review_requests: 1 })[1], /Your open review request .* reopen it\./);
});

test("Delete waits for the preview, shows its warnings, and sends once", async () => {
    let release;
    api.__respond("getDocumentDeletionPreview", { data: { ...PREVIEW, open_review_requests: 1 } });
    api.__respond("deleteDocumentV2", () => new Promise(r => { release = () => r({ data: { id: "d1" } }); }));
    const done = [];
    await mount(h(DeleteDocumentDialog, { row: ROW, onClose: () => {}, onDeleted: d => done.push(d) }));
    const items = [...dialog().querySelectorAll("[data-delete-warnings] li")].map(li => li.textContent);
    assert.equal(items.length, 2);
    const del = btn(dialog(), "Delete");
    await act(async () => {
        del.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
        del.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    });
    await act(async () => { release(); });
    await settle();
    assert.equal(api.__calls("deleteDocumentV2").length, 1);
    assert.deepEqual(done, [{ id: "d1" }]);
});

test("a document under review cannot be deleted from here", async () => {
    api.__respond("getDocumentDeletionPreview", { data: { ...PREVIEW, blocked: "This document is with a lawyer for review." } });
    await mount(h(DeleteDocumentDialog, { row: ROW, onClose: () => {}, onDeleted: () => {} }));
    assert.ok(btn(dialog(), "Delete").disabled);
    assert.match(dialog().textContent, /with a lawyer for review/);
});

test("from the Vault: delete moves it to Recently deleted, and Restore brings it back", async () => {
    api.__respond("myDocumentsV2", { data: { items: [ROW], has_more: false } });
    api.__respond("listReviewRequests", { data: null, status: 404, error: { code: "feature_disabled" } });
    api.__respond("getDocumentDeletionPreview", { data: PREVIEW });
    api.__respond("deleteDocumentV2", { data: { id: "d1" } });
    api.__respond("listDeletedDocumentsV2", { data: { items: [
        { id: "d1", title: "Shop rent agreement", deleted_at: "2026-10-03T10:00:00Z", purge_after: "2026-11-02T10:00:00Z", restorable: true },
        { id: "d9", title: "Old notice", deleted_at: "2026-09-01T10:00:00Z", purge_after: "2026-10-01T10:00:00Z", restorable: false },
    ], recoverable_days: 30 } });
    api.__respond("restoreDocumentV2", { data: { id: "d1", restored: true } });
    const p = await mount(h(DocsVault, { onBack: () => {}, onOpen: () => {} }));
    await click(p.container.querySelector('[data-delete-document="d1"]'));
    await click(btn(dialog(), "Delete"));
    assert.equal(dialog(), null, "the dialog closes");
    assert.match(toasts.join(" "), /Moved to Recently deleted/);
    assert.ok(api.__calls("myDocumentsV2").length >= 2, "the Vault list reloads");

    await click([...p.container.querySelectorAll('[role="tab"]')].find(t => t.textContent === "Recently deleted"));
    const restorable = p.container.querySelector('[data-trash-row="d1"]');
    assert.match(restorable.textContent, /Restorable until 2 Nov 2026/);
    const gone = p.container.querySelector('[data-trash-row="d9"]');
    assert.match(gone.textContent, /can no longer be restored/);
    assert.equal(btn(gone, "Restore"), undefined);
    const restore = btn(restorable, "Restore");
    await act(async () => {
        restore.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
        restore.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    });
    await settle();
    assert.deepEqual(api.__calls("restoreDocumentV2").map(c => c.args[0]), ["d1"]);
    assert.match(toasts.join(" "), /is back in your Vault/);
});

test("Create Folder and Upload File have no backend: disabled and labelled, never a working action", async () => {
    api.__respond("myDocumentsV2", { data: { items: [ROW], has_more: false } });
    api.__respond("listReviewRequests", { data: null, status: 404, error: { code: "feature_disabled" } });
    const p = await mount(h(DocsVault, { onBack: () => {}, onOpen: () => {} }));
    for (const label of ["Create Folder", "Upload File"]) {
        const b = p.container.querySelector(`[data-vault-soon="${label}"]`);
        assert.ok(b, `${label} is missing`);
        assert.equal(b.disabled, true, `${label} looks clickable`);
        assert.match(b.textContent, /Soon/);
    }
    assert.equal(p.container.querySelector("#vault-folder"), null, "the folder form led nowhere");
});
