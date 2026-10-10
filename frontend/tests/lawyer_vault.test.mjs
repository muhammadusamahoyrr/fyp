/* The lawyer's Document Vault (2026-10-09): the client Vault's design, in the
 * lawyer's own files, with real folders.
 *
 * Guards: the list is the lawyer's own documents with their folder; folders are
 * created, renamed, opened, deleted (never deleting a document) and documents
 * filed through the real API; delete and restore use the recoverable delete;
 * the preview offers Download and no dead "Open"; Upload has no backend and is
 * disabled and labelled; the page's CSS is scoped to it. */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node",
                    "Event", "CustomEvent", "KeyboardEvent", "MutationObserver", "getComputedStyle",
                    "localStorage", "requestAnimationFrame", "cancelAnimationFrame"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { VaultPage, LAWYER_VAULT_CSS } = await import("../src/components/lawyer/VaultPage.jsx");
const { ToastCtx } = await import("../src/components/lawyer/Toast.jsx");

const settle = () => act(async () => { await new Promise(r => setTimeout(r, 20)); });
async function click(el) {
    assert.ok(el, "element not found");
    await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
    await settle();
}
async function type(input, value) {
    const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set;
    await act(async () => { setter.call(input, value); input.dispatchEvent(new dom.window.Event("input", { bubbles: true })); });
    await settle();
}
async function submit(form) {
    await act(async () => { form.dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true })); });
    await settle();
}
const byText = (root, re) => [...root.querySelectorAll("button")].find(b => re.test(b.textContent));

const ROWS = [
    { id: "d1", title: "Bail application — Imran", template_type: "lawyer_draft", folder_id: "f1", review_status: "none",
      version: 1, revision_id: "r1", pdf_sha256: "a".repeat(64), downloadable: true, created_at: "2026-10-08T10:00:00Z" },
    { id: "d2", title: "Plaint — Raza", template_type: "lawyer_draft", folder_id: null, review_status: "none",
      version: 2, revision_id: "r2", pdf_sha256: "b".repeat(64), downloadable: true, created_at: "2026-10-07T10:00:00Z" },
];
const FOLDERS = [{ id: "f1", name: "Bail matters", document_count: 1 }];

const toasts = [];
async function mount() {
    api.__respond("myDocumentsV2", { data: { items: ROWS, has_more: false } });
    api.__respond("listDocumentFoldersV2", { data: { items: FOLDERS } });
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(React.createElement(ToastCtx.Provider, { value: { show: m => toasts.push(m) } },
            React.createElement(VaultPage)));
    });
    await settle();
    return { container, unmount: async () => { await act(async () => root.unmount()); container.remove(); } };
}

test.beforeEach(() => { api.__reset(); toasts.length = 0; document.body.innerHTML = ""; });

test("lists the lawyer's own documents with their folder, and counts the folders", async () => {
    const p = await mount();
    const rows = [...p.container.querySelectorAll("[data-vault-row]")];
    assert.deepEqual(rows.map(r => r.dataset.vaultRow), ["d1", "d2"]);
    assert.match(rows[0].textContent, /Bail matters/);
    assert.match(rows[1].textContent, /—/);
    assert.match(p.container.querySelector('[data-vault-stat="Folders Created"]').textContent, /1/);
    const upload = p.container.querySelector('[data-vault-soon="Upload File"]');
    assert.equal(upload.disabled, true, "Upload has no backend and must not look like a working action");
    assert.match(upload.textContent, /Soon/);
    await p.unmount();
});

test("Create Folder creates a real folder, and a refused name says why", async () => {
    const p = await mount();
    await click(p.container.querySelector("[data-create-folder]"));
    const dialog = document.querySelector("[data-folder-dialog]");
    assert.ok(dialog);
    api.__respond("createDocumentFolderV2", { data: null, error: { code: "folder_exists", message: "You already have a folder named “Bail matters”." } });
    await type(dialog.querySelector("#lvf-name"), "bail matters");
    await submit(dialog.querySelector("form"));
    assert.match(document.querySelector("[data-folder-problem]").textContent, /already have a folder/);
    api.__respond("createDocumentFolderV2", { data: { id: "f2", name: "Family", document_count: 0 } });
    await type(dialog.querySelector("#lvf-name"), "Family");
    await submit(dialog.querySelector("form"));
    assert.deepEqual(api.__calls("createDocumentFolderV2").map(c => c.args[0]), ["bail matters", "Family"]);
    assert.equal(document.querySelector("[data-folder-dialog]"), null, "the dialog stayed open");
    await p.unmount();
});

test("the Folders tab lists folders; opening one narrows the list to it through the server", async () => {
    const p = await mount();
    await click(byText(p.container, /^Folders/));
    const card = p.container.querySelector('[data-folder="f1"]');
    assert.match(card.textContent, /Bail matters/);
    assert.match(card.textContent, /1 document\b/);
    api.__respond("myDocumentsV2", { data: { items: [ROWS[0]], has_more: false } });
    await click(card.querySelector("button"));
    const last = api.__calls("myDocumentsV2").at(-1);
    assert.equal(last.args[0].folder, "f1", "the folder was not asked of the server");
    assert.match(p.container.querySelector("[data-folder-filter]").textContent, /Bail matters/);
    assert.deepEqual([...p.container.querySelectorAll("[data-vault-row]")].map(r => r.dataset.vaultRow), ["d1"]);
    await p.unmount();
});

test("a document is moved into a folder through the real API", async () => {
    const p = await mount();
    await click(p.container.querySelector('[data-move-document="d2"]'));
    const dialog = document.querySelector("[data-move-dialog]");
    const radio = [...dialog.querySelectorAll('input[type="radio"]')].find(r => r.value === "f1");
    await click(radio);
    api.__respond("moveDocumentToFolderV2", { data: { id: "d2", folder_id: "f1" } });
    await submit(dialog.querySelector("form"));
    assert.deepEqual(api.__calls("moveDocumentToFolderV2").map(c => c.args), [["d2", "f1"]]);
    await p.unmount();
});

test("renaming and deleting a folder; deleting says no document is deleted", async () => {
    const p = await mount();
    await click(byText(p.container, /^Folders/));
    await click(p.container.querySelector('[data-rename-folder="f1"]'));
    let dialog = document.querySelector("[data-folder-dialog]");
    api.__respond("renameDocumentFolderV2", { data: { id: "f1", name: "Bail" } });
    await type(dialog.querySelector("#lvf-name"), "Bail");
    await submit(dialog.querySelector("form"));
    assert.deepEqual(api.__calls("renameDocumentFolderV2").map(c => c.args), [["f1", "Bail"]]);

    await click(p.container.querySelector('[data-delete-folder="f1"]'));
    dialog = document.querySelector("[data-folder-delete-dialog]");
    assert.match(dialog.textContent, /No document is deleted/);
    api.__respond("deleteDocumentFolderV2", { data: { id: "f1", deleted: true, documents_unfiled: 1 } });
    await click(byText(dialog, /Delete folder/));
    assert.deepEqual(api.__calls("deleteDocumentFolderV2").map(c => c.args), [["f1"]]);
    await p.unmount();
});

test("a document is deleted to Recently deleted and restored", async () => {
    const p = await mount();
    api.__respond("getDocumentDeletionPreview", { data: { id: "d2", recoverable_days: 30, purge_after: "2026-11-08T00:00:00Z", blocked: null, open_review_requests: 0, accepted_reviews: [] } });
    await click(p.container.querySelector('[data-delete-document="d2"]'));
    const dialog = document.querySelector("[data-delete-dialog]");
    assert.match(dialog.textContent, /Recently deleted/);
    api.__respond("deleteDocumentV2", { data: { id: "d2" } });
    await click(byText(dialog, /^Delete$/));
    assert.deepEqual(api.__calls("deleteDocumentV2").map(c => c.args), [["d2"]]);

    api.__respond("listDeletedDocumentsV2", { data: { items: [{ id: "d2", title: "Plaint — Raza", deleted_at: "2026-10-09T10:00:00Z", purge_after: "2026-11-08T10:00:00Z", restorable: true }] } });
    await click(byText(p.container, /Recently deleted/));
    const row = p.container.querySelector('[data-trash-row="d2"]');
    api.__respond("restoreDocumentV2", { data: { id: "d2", restored: true } });
    await click(byText(row, /Restore/));
    assert.deepEqual(api.__calls("restoreDocumentV2").map(c => c.args), [["d2"]]);
    await p.unmount();
});

test("the preview shows the file with Download, and no dead Open", async () => {
    api.__respond("previewRevisionV2", { data: null, error: { message: "x" } });
    const p = await mount();
    await click(p.container.querySelector('[data-vault-row="d1"] button'));
    const preview = p.container.querySelector("[data-vault-preview]");
    assert.ok(preview, "the preview did not open");
    assert.ok(preview.querySelector("[data-preview-download]"));
    assert.equal(preview.querySelector("[data-preview-open]"), null);
    assert.match(preview.querySelector("[data-preview-meta]").textContent, /Folder: Bail matters/);
    await p.unmount();
});

test("the page's CSS is scoped to the lawyer Vault", () => {
    for (const part of LAWYER_VAULT_CSS.split("{")[0].split(",")) {
        assert.match(part.trim(), /^\[data-lawyer-vault\]/);
    }
});
