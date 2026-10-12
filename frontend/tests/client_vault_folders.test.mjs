/* The client Vault's folder flow (2026-10-10).
 *
 * Making a folder used to end at a toast: filling it meant finding each
 * document in "All documents" and moving it with a dialog per row, and an
 * empty folder only said to go elsewhere. Now a new folder opens with a picker
 * to add several documents at once (also from inside a folder, its empty state
 * and its card), a partial failure names what did not move, and the Move
 * dialog can make the folder it files into. Filing only moves `folder_id`. */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/documents" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "HTMLInputElement", "Element", "Node", "Event",
                    "CustomEvent", "KeyboardEvent", "MutationObserver", "getComputedStyle", "DOMParser"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { default: DocsVault } = await import("../src/components/client/documents/DocsVault.jsx");
const { ToastCtx } = await import("../src/components/shared/Toast.jsx");
const h = React.createElement;

const DOC = (id, title, folder_id = null) => ({ id, title, template_type: "rent_agreement", folder_id, version: 1,
    revision_id: `r-${id}`, pdf_sha256: "a".repeat(64), downloadable: true, updated_at: "2026-10-09T10:00:00Z" });
const DOCS = [DOC("d1", "Shop rent agreement"), DOC("d2", "Eviction notice"), DOC("d3", "Bail affidavit", "fb")];
const BAIL = { id: "fb", name: "Bail", document_count: 1 };

const mounted = new Set();
const toasts = [];
async function mount() {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(h(ToastCtx.Provider, { value: { show: m => toasts.push(m) } }, h(DocsVault, { onBack: () => {} }))); });
    await settle(40);
    const unmount = async () => { mounted.delete(unmount); await act(async () => root.unmount()); container.remove(); };
    mounted.add(unmount);
    return { container };
}
const settle = (ms = 20) => act(async () => { await new Promise(r => setTimeout(r, ms)); });
async function click(el) {
    assert.ok(el, "nothing to click");
    await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
    await settle(30);
}
async function type(el, value) {
    Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set.call(el, value);
    await act(async () => { el.dispatchEvent(new dom.window.Event("input", { bubbles: true })); });
}
const picker = () => document.body.querySelector("[data-add-documents-dialog]");
const pick = async id => click(picker().querySelector(`[data-add-doc="${id}"] input`));

test.beforeEach(() => {
    api.__reset();
    toasts.length = 0;
    api.__respond("listReviewRequests", { data: null, status: 404, error: { code: "feature_disabled" } });
    api.__respond("listDocumentFoldersV2", { data: { items: [BAIL] }, error: null });
    api.__respond("myDocumentsV2", ({ folder } = {}) => ({
        data: { items: folder ? DOCS.filter(d => d.folder_id === folder) : DOCS, has_more: false }, error: null }));
    api.__respond("moveDocumentToFolderV2", { data: { ok: true }, error: null });
});
test.afterEach(async () => {
    for (const u of [...mounted]) await u();
    document.body.innerHTML = "";
});

test("a new folder opens with the picker; several documents are added at once", async () => {
    api.__respond("createDocumentFolderV2", { data: { id: "ft", name: "Tenancy", document_count: 0 }, error: null });
    const p = await mount();
    await click(p.container.querySelector("[data-create-folder]"));
    await type(document.body.querySelector("#lvf-name"), "Tenancy");
    await click([...document.body.querySelectorAll("[data-folder-dialog] button")].find(b => b.textContent === "Create"));
    await settle(40);
    assert.ok(picker(), "making a folder ended without a way to fill it");
    assert.match(picker().textContent, /“Tenancy” is ready\. Add documents\?/);
    assert.match(p.container.textContent, /Showing the folder Tenancy/, "the new folder did not open");
    // Where each document is now: the one in "Bail" says so.
    assert.match(picker().querySelector('[data-add-doc="d3"]').textContent, /now in “Bail”/);
    await pick("d1");
    await pick("d2");
    assert.match(picker().querySelector("[data-add-submit]").textContent, /Add 2 documents/);
    await click(picker().querySelector("[data-add-submit]"));
    await settle(40);
    assert.deepEqual(api.__calls("moveDocumentToFolderV2").map(c => c.args), [["d1", "ft"], ["d2", "ft"]]);
    assert.ok(toasts.some(m => /Added 2 documents to “Tenancy”/.test(m)), toasts.join(" | "));
    assert.equal(picker(), null, "the picker stayed open after everything was added");
});

test("the picker leaves out what is already in the folder, and select-all follows the search", async () => {
    const p = await mount();
    await click([...p.container.querySelectorAll('[role="tab"]')].find(t => t.textContent.startsWith("Folders")));
    await click(p.container.querySelector('[data-add-to-folder="fb"]'));
    const listed = [...picker().querySelectorAll("[data-add-doc]")].map(el => el.dataset.addDoc);
    assert.deepEqual(listed, ["d1", "d2"], "a document already in the folder was offered again");
    await type(picker().querySelector('input[type="search"]'), "evict");
    assert.deepEqual([...picker().querySelectorAll("[data-add-doc]")].map(el => el.dataset.addDoc), ["d2"]);
    await click(picker().querySelector("[data-add-all]"));
    assert.match(picker().querySelector("[data-add-submit]").textContent, /Add 1 document$/);
});

test("a move that fails is named and stays selected; the rest are added", async () => {
    api.__respond("moveDocumentToFolderV2", id => (id === "d2"
        ? { data: null, error: { message: "Not found." }, status: 404 }
        : { data: { ok: true }, error: null }));
    const p = await mount();
    await click([...p.container.querySelectorAll('[role="tab"]')].find(t => t.textContent.startsWith("Folders")));
    await click(p.container.querySelector('[data-add-to-folder="fb"]'));
    await pick("d1");
    await pick("d2");
    await click(picker().querySelector("[data-add-submit]"));
    await settle(40);
    assert.ok(picker(), "a partial failure closed the picker");
    assert.match(picker().querySelector('[role="alert"]').textContent, /1 could not be added: Eviction notice/);
    assert.deepEqual([...picker().querySelectorAll("[data-add-doc]")].map(el => el.dataset.addDoc), ["d2"], "the added one is still listed");
    assert.equal(picker().querySelector('[data-add-doc="d2"] input').checked, true, "the failure is not kept selected to retry");
    assert.ok(toasts.some(m => /Added 1 document to “Bail”/.test(m)));
});

test("Move can make the folder it files into, in one step", async () => {
    api.__respond("createDocumentFolderV2", { data: { id: "fn", name: "Shop lease", document_count: 0 }, error: null });
    const p = await mount();
    await click(p.container.querySelector('[data-move-document="d1"]'));
    await click(document.body.querySelector("[data-move-new-folder-start]"));
    await type(document.body.querySelector("[data-move-new-folder] input"), "Shop lease");
    await click([...document.body.querySelectorAll("[data-move-dialog] button")].find(b => b.textContent === "Create & move"));
    await settle(40);
    assert.deepEqual(api.__calls("createDocumentFolderV2").map(c => c.args[0]), ["Shop lease"]);
    assert.deepEqual(api.__calls("moveDocumentToFolderV2").map(c => c.args), [["d1", "fn"]]);
    assert.ok(toasts.some(m => /Moved to “Shop lease”/.test(m)), toasts.join(" | "));
});
