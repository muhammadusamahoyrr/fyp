/* The approved AI drafting design, restored on the real backend (2026-10-07).
 *
 * The layout came back from the recovered 30 Sept build (history column,
 * toolbar, status chips, Fill Placeholders and Checks panels, "Choices I
 * made"); these tests pin that every visible control does what it says on
 * the user's REAL document, and that the old sample-only controls (risk
 * score, Copy, document analysis) do not come back.
 *
 * 2026-10-08 layout: a page header (back, title, Visit Marketplace, Send to
 * lawyer), a Versions | Saved left column -- both real -- and the
 * Placeholders / Checks panels opening on the right on request. DOCX is
 * shown disabled ("Soon"), never as a working export. */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node", "Event",
                    "KeyboardEvent", "CustomEvent", "MutationObserver", "getComputedStyle", "DOMParser"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { default: DocsDrafts, placeholderFields, revisionChecks, workspaceChecks } =
    await import("../src/components/client/documents/DocsDrafts.jsx");
const { ToastCtx } = await import("../src/components/shared/Toast.jsx");

const TEMPLATES = [
    { template_type: "legal_notice", label: "Legal Notice", category: "Civil", description: "A formal demand.",
      fields: ["sender_name", "demand"], structured_fields: [], drafting_mode: "ai" },
];
const ROWS = [
    { id: "d1", title: "Rent notice", template_type: "legal_notice", review_status: "none",
      updated_at: "2026-09-20T10:00:00Z", revision_id: "r1", pdf_sha256: "a".repeat(64), downloadable: true, version: 1 },
    { id: "d2", title: "Employment letter", template_type: "legal_notice", review_status: "none",
      updated_at: "2026-09-21T10:00:00Z", revision_id: "r2", pdf_sha256: "b".repeat(64), downloadable: true, version: 1 },
];
const WORKSPACE = {
    document_id: "d1", title: "Rent notice", source: "structured_fields", template_type: "legal_notice",
    fields: { sender_name: "Ayesha", demand: "", schedule: { rows: 2 } }, body_html: null,
    base_revision_id: "r1", base_version: 1, content_epoch: 3, review_status: "none",
};
const DETAIL = (review_status = "none") => ({
    id: "d1", title: "Rent notice", review_status, current_version: 1,
    current_revision: { revision_id: "r1", pdf_sha256: "a".repeat(64), created_at: "2026-10-01T09:00:00Z",
        compliance: { checked: true, missing: [] }, verification: { ran: false } },
});

async function mount(props) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(React.createElement(ToastCtx.Provider, { value: { show: () => {} } },
            React.createElement(DocsDrafts, { seed: null, templates: TEMPLATES, cases: [], onBack: () => {},
                onOpenView: () => {}, onOpenDocument: () => {}, ...props })));
    });
    await settle();
    return { container, unmount: () => act(async () => root.unmount()).then(() => container.remove()) };
}
const settle = () => act(async () => { await new Promise(r => setTimeout(r, 10)); });
const buttons = (el, text) => [...el.querySelectorAll("button")].filter(b => b.textContent.includes(text));
async function click(el) {
    assert.ok(el, "nothing to click");
    await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
    await settle();
}
async function type(input, value) {
    const proto = input.tagName === "TEXTAREA" ? dom.window.HTMLTextAreaElement.prototype : dom.window.HTMLInputElement.prototype;
    await act(async () => {
        Object.getOwnPropertyDescriptor(proto, "value").set.call(input, value);
        input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
}
async function openWorkspace(review = "none") {
    api.__respond("myDocumentsV2", { data: { items: ROWS, has_more: false } });
    api.__respond("getDocumentWorkspaceV2", { data: { ...WORKSPACE, review_status: review } });
    api.__respond("getDocumentV2", { data: DETAIL(review) });
    api.__respond("previewRevisionV2", { data: null, error: { message: "preview unavailable in test" } });
    const p = await mount({});
    await click(p.container.querySelector('[data-doc="d1"]'));
    return p;
}

test.beforeEach(() => api.__reset());
test.after(() => dom.window.close());

/* The placeholders panel opens on request, from the toolbar. */
const openPlaceholders = c => click(c.querySelector("[data-placeholders-toggle]"));

test("the workspace: a page header, the History column on the left, panels on the right on request", async () => {
    const p = await openWorkspace();
    const c = p.container;
    assert.ok(c.querySelector("[data-document-workspace]"));
    // Header: back, the document, and the two ways onward.
    const header = c.querySelector('header[aria-label="Document header"]');
    assert.ok(header, "the page header is missing");
    assert.equal(header.querySelector("[data-document-title]").textContent, "Rent notice");
    assert.ok(header.querySelector('[aria-label="Back to drafts"]'));
    assert.ok(buttons(header, "Visit Marketplace")[0]);
    assert.ok(buttons(header, "Send to lawyer")[0]);
    // Left column, after the analyzer's (2026-10-08): AI Draft, then -- with a
    // document open -- its two options, Versions | Saved; Saved by day.
    const side = c.querySelector('[aria-label="Draft history"]');
    assert.ok(side, "the left column is missing");
    assert.equal(side.style.flex, "0 0 206px", "narrower, with the smaller option pills");
    // With a document open, Versions | Saved take the AI Draft button's place.
    assert.equal(side.querySelector("[data-ai-draft]"), null);
    assert.equal(side.querySelector("[data-side-heading]").textContent.trim(), "Saved");
    assert.ok(side.querySelector('[data-side-tab="versions"]') && side.querySelector('[data-side-tab="saved"]'));
    assert.ok(side.querySelector("[data-history-group]"), "saved documents are grouped by day");
    assert.equal(c.querySelector('[data-doc="d1"]').getAttribute("aria-current"), "true");
    assert.equal(side.querySelector("[data-versions]"), null, "versions are their own option, not nested");
    // Toolbar, and the document at full width until a panel is asked for.
    assert.ok(c.querySelector('[aria-label="Document actions"]'), "the toolbar is missing");
    assert.equal(c.querySelector('[aria-label="Complete document"]'), null, "the placeholders panel opens on request");
    assert.equal(c.querySelector("[data-undo]"), null, "Undo belongs to the open placeholders panel");
    await openPlaceholders(c);
    const form = c.querySelector('[aria-label="Complete document"]');
    assert.ok(form);
    // A COMPLETE form, full height on the RIGHT: every detail at once, the first
    // empty one selected, the Versions/Saved column still on the left.
    assert.deepEqual([...form.querySelectorAll("[data-field-row]")].map(r => r.dataset.fieldRow), ["sender_name", "demand"]);
    assert.equal(form.querySelector('[data-field-row="demand"]').dataset.active, "true");
    assert.ok(c.querySelector('[aria-label="Draft history"]'), "the left column stays");
    assert.ok(form.compareDocumentPosition(header) & dom.window.Node.DOCUMENT_POSITION_PRECEDING, "the form is on the right");
    assert.equal(header.parentElement.contains(form), false, "the form runs top to bottom beside the header, not under it");
    assert.ok(c.querySelector("[data-undo]"));
    await openPlaceholders(c);
    assert.equal(c.querySelector('[aria-label="Complete document"]'), null, "a second click closes it");
    await click(c.querySelector("[data-checks-toggle]"));
    assert.ok(c.querySelector('[aria-label="Review document"]'));
    await click(c.querySelector('[aria-label="Close panel"]'));
    assert.equal(c.querySelector('[aria-label="Review document"]'), null);
    await p.unmount();
});

test("a saved row has no card around it, and its ⋮ menu opens, downloads and deletes for real", async () => {
    const p = await openWorkspace();
    const c = p.container;
    const menuBtn = c.querySelector('[aria-label="More actions for Employment letter"]');
    assert.ok(menuBtn, "each saved row has a ⋮ menu");
    await click(menuBtn);
    const menu = c.querySelector('[role="menu"]');
    assert.deepEqual([...menu.querySelectorAll('[role="menuitem"]')].map(b => b.textContent), ["Open", "Download PDF", "Delete"]);
    await click(buttons(menu, "Download PDF")[0]);
    const [dl] = api.__calls("downloadDocumentFile").slice(-1);
    assert.deepEqual([dl.args[0], dl.args[2].revisionId], ["d2", "r2"]);
    // Delete goes through the Vault's own dialog, which asks the server first.
    api.__respond("getDocumentDeletionPreview", { data: { blocked: false } });
    await click(c.querySelector('[aria-label="More actions for Employment letter"]'));
    await click(buttons(c.querySelector('[role="menu"]'), "Delete")[0]);
    assert.ok(document.querySelector("[data-delete-dialog]"), "the delete dialog did not open");
    assert.equal(api.__calls("deleteDocumentV2").length, 0, "nothing is deleted before confirming");
    await click(buttons(document.querySelector("[data-delete-dialog]"), "Keep it")[0]);
    await p.unmount();
});

test("Visit Marketplace goes to the lawyers marketplace", async () => {
    const p = await openWorkspace();
    const before = globalThis.__nav.pushed.length;   // the router stub's own record
    await click(p.container.querySelector("[data-visit-marketplace]"));
    assert.deepEqual(globalThis.__nav.pushed.slice(before), ["/lawyers"]);
    await p.unmount();
});

test("the Versions option lists the real revisions and previews an older one by its own id and hash", async () => {
    api.__respond("listRevisionsV2", { data: { items: [
        { revision_id: "r1", version: 2, status: "generated", pdf_sha256: "a".repeat(64) },
        { revision_id: "r0", version: 1, status: "generated", pdf_sha256: "c".repeat(64) },
    ] } });
    const p = await openWorkspace();
    const c = p.container;
    await click(c.querySelector('[data-side-tab="versions"]'));
    assert.equal(c.querySelector("[data-side-heading]").textContent.trim(), "Versions");
    assert.ok(c.querySelector("[data-versions]"), "the versions list is missing");
    assert.equal(c.querySelector('[data-doc="d1"]'), null, "the saved list is hidden on Versions");
    assert.match(c.querySelector("[data-versions]").textContent, /Version 2 · Current.*Version 1/s);
    // ⋮ on a version: Download fetches THAT version, by its own id and hash.
    await click(c.querySelector('[aria-label="More actions for version 1"]'));
    await click(buttons(c.querySelector('[role="menu"]'), "Download PDF")[0]);
    const [dl] = api.__calls("downloadDocumentFile").slice(-1);
    assert.equal(dl.args[2].revisionId, "r0");
    assert.equal(dl.args[2].expectedPdfSha256, "c".repeat(64));
    api.__respond("previewRevisionV2", { data: { url: "blob:v1" } });
    await click(c.querySelector('[data-version="1"]'));
    const [call] = api.__calls("previewRevisionV2").slice(-1);
    assert.deepEqual(call.args.slice(0, 2), ["d1", "r0"]);
    assert.equal(call.args[2].expectedPdfSha256, "c".repeat(64));
    assert.match(c.querySelector("[data-viewing-version]").textContent, /version 1/);
    await click(buttons(c, "Back to current")[0]);
    assert.equal(c.querySelector("[data-viewing-version]"), null);
    await click(c.querySelector('[data-side-tab="saved"]'));
    assert.ok(c.querySelector('[data-doc="d1"]'), "Saved is the document list");
    await p.unmount();
});

test("a saved PDF uses a white page canvas, not the browser's grey iframe viewer", async () => {
    api.__respond("myDocumentsV2", { data: { items: ROWS, has_more: false } });
    api.__respond("getDocumentWorkspaceV2", { data: WORKSPACE });
    api.__respond("getDocumentV2", { data: DETAIL() });
    api.__respond("previewRevisionV2", { data: { url: "blob:mock-pdf" } });
    const p = await mount({});
    await click(p.container.querySelector('[data-doc="d1"]'));
    assert.ok(p.container.querySelector('[aria-label="PDF document pages"]'));
    assert.ok(p.container.querySelector('canvas[aria-label="PDF page 1"]'));
    assert.equal(p.container.querySelector("iframe"), null, "the native grey PDF viewer must not be embedded");
    await p.unmount();
});

test("placeholders are the document's real empty fields, and editing them saves a new revision", async () => {
    const p = await openWorkspace();
    const c = p.container;
    assert.equal(c.querySelector("[data-placeholders-badge]").textContent, "1", "the toolbar counts the empty detail");
    await openPlaceholders(c);
    assert.equal(c.querySelector("[data-placeholder-count]").textContent, "1", "only `demand` is empty");
    const d = c.querySelector('[aria-label="Complete document"]');
    assert.match(d.textContent, /1 of 2/);
    assert.equal(document.querySelector("#ph_demand").placeholder, "[[DEMAND]]");
    assert.equal(document.querySelector("#ph_schedule"), null, "a calculation must not be editable");
    await type(document.querySelector("#ph_demand"), "Pay Rs 50,000 within 15 days");
    assert.equal(c.querySelector("[data-placeholder-count]").textContent, "0");
    api.__respond("saveDocumentWorkspaceV2", { data: { document_id: "d1" } });
    await click(buttons(d, "Save all changes")[0]);
    const [call] = api.__calls("saveDocumentWorkspaceV2");
    assert.equal(call.args[0], "d1");
    assert.equal(call.args[1].fields.demand, "Pay Rs 50,000 within 15 days");
    assert.equal(call.args[1].expectedRevisionId, "r1", "the stale-revision guard was not sent");
    assert.equal(call.args[1].expectedContentEpoch, 3);
    assert.ok(call.args[2], "no idempotency key");
    await p.unmount();
});

test("unsaved details cannot be sent as though the PDF already contained them", async () => {
    const p = await openWorkspace();
    const send = buttons(p.container, "Send to lawyer")[0];
    assert.equal(send.disabled, false);
    assert.equal(p.container.querySelector("[data-save]").disabled, true, "nothing to save yet");
    await openPlaceholders(p.container);
    await type(p.container.querySelector("#ph_demand"), "Pay within 15 days");
    assert.equal(send.disabled, true);
    assert.equal(p.container.querySelector("[data-save]").disabled, false);
    assert.match(p.container.querySelector("[data-save-state]").textContent, /Unsaved changes/);
    assert.match(p.container.querySelector('[title="Downloads the last saved version"]').textContent, /PDF/);
    await p.unmount();
});

test("checks come from the revision, and the toolbar counts them", async () => {
    const p = await openWorkspace();
    await click(p.container.querySelector("[data-checks-toggle]"));
    const panel = p.container.querySelector('[aria-label="Review document"]');
    assert.ok(panel, "review panel did not open");
    assert.match(panel.textContent, /All details filled.*1 detail still blank/);
    assert.match(panel.textContent, /Required particulars/);
    assert.match(panel.textContent, /Citation check/);
    const { badge } = workspaceChecks(DETAIL().current_revision, { unfilled: 1, structured: true });
    assert.equal(p.container.querySelector("[data-checks-badge]").textContent, badge.text);
    // "Fill in" returns to the completion panel.
    await click(panel.querySelector("[data-fill-in]"));
    assert.ok(p.container.querySelector('[aria-label="Complete document"]'), "Fill in did not open details");
    await p.unmount();
});

test("the checks badge never counts a check that did not run as a failure", () => {
    // A fresh revision: nothing checked, no citations -- neutral, not "0/2".
    const fresh = revisionChecks({ compliance: null, verification: { ran: true, total: 0 } });
    assert.equal(fresh.badge.text, "—");
    assert.equal(fresh.issues, 0);
    // An incomplete compliance check is an issue.
    assert.equal(revisionChecks({ compliance: { checked: true, missing: 2 } }).badge.text, "1 issue");
    // A complete check that ran passes; the citation check that did not run is not counted.
    const ok = revisionChecks({ compliance: { checked: true, complete: true } });
    assert.equal(ok.badge.text, "1/1");
});

test("no sample-only control comes back, and DOCX is never a working export", async () => {
    const p = await openWorkspace();
    const text = p.container.textContent;
    for (const fake of [/Medium risk/, /Sample draft/, /\bCopy\b/, /Analyze a document/,
                        /Required clauses present/, /Citations verified/, /Preview · not connected/]) {
        assert.doesNotMatch(text, fake, `${fake} is back`);
    }
    // DOCX has no backend: shown disabled and labelled, never clickable.
    for (const sel of ["[data-docx-soon]", "[data-email-soon]"]) {
        const btn = p.container.querySelector(sel);
        assert.equal(btn.disabled, true, `${sel} must not be clickable`);
        assert.match(btn.textContent, /Soon/);
    }
    // Edit on a template opens its details panel.
    await click(p.container.querySelector("[data-edit-toggle]"));
    assert.ok(p.container.querySelector('[aria-label="Complete document"]'));
    await p.unmount();
});

test("Send to lawyer opens the workspace's send panel, and is off while frozen", async () => {
    const p = await openWorkspace();
    await click(buttons(p.container.querySelector('header[aria-label="Document header"]'), "Send to lawyer")[0]);
    assert.ok(p.container.querySelector("[data-send-panel]"), "the send panel did not open");
    await p.unmount();
    const frozen = await openWorkspace("submitted");
    assert.equal(buttons(frozen.container, "Send to lawyer")[0].disabled, true);
    assert.equal(frozen.container.querySelector("[data-placeholders-toggle]").disabled, true, "details cannot be edited while frozen");
    assert.equal(frozen.container.querySelector("[data-save]").disabled, true);
    assert.match(frozen.container.textContent, /Frozen for lawyer review/);
    await frozen.unmount();
});

test("Ask for changes is AI Assist: a proposal, applied locally, never saved by itself", async () => {
    const p = await openWorkspace();
    api.__respond("assistDocumentWorkspaceV2", { data: { summary: "Adds a 15-day deadline.", fields: { ...WORKSPACE.fields, demand: "Pay within 15 days" } } });
    await click(p.container.querySelector("[data-ask-ai]"));
    await type(p.container.querySelector("#drafts-ask"), "Add a 15 day deadline");
    await click(p.container.querySelector('[aria-label="Prepare proposal"]'));
    assert.equal(p.container.querySelector("[data-ask-composer]"), null, "the composer closes once a proposal is ready");
    assert.match(p.container.querySelector("[data-ai-proposal]").textContent, /Adds a 15-day deadline/);
    await click(buttons(p.container, "Apply proposal locally")[0]);
    await openPlaceholders(p.container);
    assert.equal(document.querySelector("#ph_demand").value, "Pay within 15 days");
    assert.equal(api.__calls("saveDocumentWorkspaceV2").length, 0, "applying a proposal saved it");
    await p.unmount();
});

test("History: every document, folding by list and by day, the column hidden by its round edge button", async () => {
    api.__respond("myDocumentsV2", { data: { items: ROWS, has_more: false } });
    const p = await mount({});
    const c = p.container;
    let side = c.querySelector('[aria-label="Draft history"]');
    assert.equal(side.querySelector('[aria-label="Search drafts"]'), null, "no search");
    assert.ok(side.querySelector('[data-doc="d1"]') && side.querySelector('[data-doc="d2"]'));
    // ^ folds the whole list; a day heading folds its group.
    assert.match(side.textContent, /History/, "without an open document the heading is History");
    await click(side.querySelector('[aria-label="Collapse list"]'));
    assert.equal(side.querySelector('[data-doc="d1"]'), null);
    await click(side.querySelector('[aria-label="Expand list"]'));
    const group = side.querySelector("[data-history-group]");
    await click(group.querySelector("button[aria-expanded]"));
    assert.equal(group.querySelector("[data-doc]"), null, "the day group did not fold");
    await click(group.querySelector("button[aria-expanded]"));
    // ⋯ offers the Vault -- never a bulk delete of real documents.
    await click(side.querySelector('[aria-label="History options"]'));
    const items = [...side.querySelectorAll('[role="menu"] [role="menuitem"]')].map(b => b.textContent);
    assert.deepEqual(items, ["Open Vault", "Refresh"]);
    // The round button on the edge hides the column, and brings it back.
    await click(side.querySelector('[aria-label="Hide history"]'));
    assert.equal(c.querySelector('[aria-label="Draft history"]'), null);
    await click(c.querySelector('[aria-label="Show history"]'));
    side = c.querySelector('[aria-label="Draft history"]');
    assert.ok(side);
    // AI Draft returns to the start screen.
    assert.ok(side.querySelector("[data-ai-draft]"));
    await p.unmount();
});

test("groupByDate puts each document under its day", async () => {
    const { groupByDate } = await import("../src/components/client/documents/DocsDrafts.jsx");
    const now = new Date("2026-10-08T12:00:00");
    const rows = [
        { id: "a", updated_at: "2026-10-08T09:00:00" },
        { id: "b", updated_at: "2026-10-07T20:00:00" },
        { id: "c", updated_at: "2026-10-03T10:00:00" },
        { id: "d", updated_at: "2026-08-01T10:00:00" },
    ];
    assert.deepEqual(groupByDate(rows, now).map(([name, r]) => [name, r.map(x => x.id)]),
        [["Today", ["a"]], ["Yesterday", ["b"]], ["Previous 7 days", ["c"]], ["Earlier", ["d"]]]);
});

test("the start screen has no tips panel, and a working link back to the templates", async () => {
    let back = 0;
    api.__respond("myDocumentsV2", { data: { items: [], has_more: false } });
    const p = await mount({ onBack: () => { back += 1; } });
    // Removed at the user's request (2026-10-07).
    assert.equal(p.container.querySelector('[aria-label="Drafting tips"]'), null);
    // The "← Drafts" top bar is gone too.
    assert.equal(p.container.querySelector("header"), null);
    assert.equal(p.container.querySelector('[aria-label="Back to documents"]'), null);
    assert.doesNotMatch(p.container.textContent, /Drafting tips|A draft stays yours until you send it/);
    // The mockup's "Add files" / "Use AI to refine" had no backend: plain guidance only.
    assert.doesNotMatch(p.container.textContent, /Add files|Use AI to refine/);
    // The approved start screen (2026-10-08): breadcrumb and privacy line, a
    // serif heading above the composer, "Try" examples while the box is empty,
    // one toolbar of pill choices, and the popular documents below.
    assert.match(p.container.textContent, /Documents\s*\/\s*New draft/);
    assert.match(p.container.textContent, /Private to your workspace/);
    assert.equal(p.container.querySelector("h1").textContent, "What do you need to draft?");
    const card = p.container.querySelector("[data-prompt-card]");
    assert.equal(card.querySelector("#docs-dtype").options[0].textContent, "Detect from description");
    assert.equal(card.querySelector("#docs-dcase").options[0].textContent, "Standalone");
    assert.equal(card.querySelector("#docs-dlang"), null, "the language control was removed");
    assert.equal(card.querySelector("[data-attach-soon]").disabled, true, "Attach has no upload behind it yet");
    assert.ok(buttons(card, "Plan my draft")[0]);
    // The examples are a moving strip under the heading, outside the box, in
    // place of the old guidance line; clicking one fills the box.
    assert.doesNotMatch(p.container.textContent, /the way you'd brief a junior/);
    const strip = p.container.querySelector("[data-try-strip]");
    assert.ok(strip && !card.contains(strip), "the examples sit outside the box");
    const chips = [...strip.querySelectorAll("button")];
    assert.equal(chips.filter(b => b.tabIndex === 0).length, chips.length / 2, "the loop copy is not a second tab stop");
    await click(buttons(strip, "Notice to a tenant for unpaid rent")[0]);
    assert.equal(card.querySelector("#docs-need").value, "Notice to a tenant for unpaid rent");
    assert.match(p.container.querySelector('[aria-label="Popular documents"]').textContent, /Rent agreement.*Punjab Rented Premises Act 2009/s);
    assert.doesNotMatch(p.container.textContent, /What would you like to draft\?/, "the duplicate heading is gone");
    await click(buttons(p.container, "View all")[0]);
    assert.equal(back, 1);
    await p.unmount();
});

test("placeholderFields keeps plain-text fields and leaves calculations out", () => {
    assert.deepEqual(placeholderFields({ a: "", b: "x", c: { n: 1 }, d: null }), ["a", "b", "d"]);
});

test("openDocument reopens that document in the workspace", async () => {
    api.__respond("myDocumentsV2", { data: { items: ROWS, has_more: false } });
    api.__respond("getDocumentWorkspaceV2", { data: WORKSPACE });
    api.__respond("getDocumentV2", { data: DETAIL() });
    api.__respond("previewRevisionV2", { data: null, error: { message: "preview unavailable in test" } });
    const p = await mount({ openDocument: { id: "d1", at: 1 } });
    assert.ok(p.container.querySelector("[data-document-workspace]"));
    assert.equal(api.__calls("getDocumentWorkspaceV2")[0].args[0], "d1");
    await p.unmount();
});

test("the workspace back button returns to the start screen", async () => {
    const p = await openWorkspace();
    await click(p.container.querySelector('[aria-label="Back to drafts"]'));
    assert.equal(p.container.querySelector("[data-document-workspace]"), null);
    assert.ok(p.container.querySelector("#docs-need"), "the prompt is back");
    await p.unmount();
});

test("an undetected type never opens a page: it is chosen on the start card", async () => {
    api.__respond("myDocumentsV2", { data: { items: [], has_more: false } });
    let call = 0;
    api.__respond("createDraftPlanV2", ({ templateType }) => {
        call += 1;
        return { data: templateType
            ? { id: "p2", version: 0, status: "needs_details", title: "Legal Notice draft", prompt: "Notice to a tenant for unpaid rent",
                template_type: templateType, extraction_status: "ok", fields: {}, remaining_detail_count: 1,
                questions: [{ field: "sender_name", label: "Sender name", question: "Please provide the sender name.", options: [] }] }
            : { id: "p1", version: 0, status: "needs_template", title: "Untitled legal draft", prompt: "Notice to a tenant for unpaid rent",
                template_type: null, extraction_status: "failed", fields: {}, remaining_detail_count: 1,
                questions: [{ field: "template_type", label: "Document type", question: "What type of document do you want to draft?", options: [] }] } };
    });
    const p = await mount({});
    await type(p.container.querySelector("#docs-need"), "Notice to a tenant for unpaid rent");
    await click(buttons(p.container, "Plan my draft")[0]);
    assert.equal(p.container.querySelector("[data-draft-plan]"), null, "the 'which document?' page came back");
    assert.match(p.container.textContent, /couldn't tell which document this is/);
    const select = p.container.querySelector("#docs-dtype");
    assert.equal(select.getAttribute("data-type-required"), "true");
    assert.equal(p.container.querySelector("#docs-need").value, "Notice to a tenant for unpaid rent", "the description was kept");
    await act(async () => {
        Object.getOwnPropertyDescriptor(dom.window.HTMLSelectElement.prototype, "value").set.call(select, "legal_notice");
        select.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
    await click(buttons(p.container, "Plan my draft")[0]);
    assert.equal(call, 2);
    assert.equal(api.__calls("createDraftPlanV2")[1].args[0].templateType, "legal_notice");
    assert.ok(p.container.querySelector("[data-draft-plan]"), "the plan opens once the type is known");
    await p.unmount();
});

test("the prompt plan uses the completion panel and saves the selected details", async () => {
    api.__respond("myDocumentsV2", { data: { items: [], has_more: false } });
    const Q = [{ field: "sender_name", label: "Sender name", question: "Please provide the sender name.", options: [] },
               { field: "recipient_name", label: "Recipient name", question: "Please provide the recipient name.", options: [] }];
    api.__respond("createDraftPlanV2", { data: { id: "p9", version: 0, status: "needs_details", title: "Legal Notice draft",
        prompt: "Draft a legal notice", template_type: "legal_notice", extraction_status: "failed", fields: {},
        questions: Q, remaining_detail_count: 4 } });
    api.__respond("answerDraftPlanV2", { data: { id: "p9", version: 1, status: "needs_details", title: "Legal Notice draft",
        prompt: "Draft a legal notice", template_type: "legal_notice", extraction_status: "failed",
        fields: { sender_name: "Ayesha", recipient_name: "Bilal" }, questions: [], remaining_detail_count: 2 } });
    const p = await mount({ seed: { prompt: "Draft a legal notice", templateType: "legal_notice" } });
    const c = p.container;
    assert.ok(c.querySelector('[aria-label="Complete document"]'));
    assert.equal(c.querySelector("[data-plan-progress-rail]"), null, "the extra progress rail should be gone");
    assert.match(c.querySelector("[data-plan-progress]").textContent, /0\/4/);
    assert.match(c.querySelector("[data-plan-remaining]").textContent, /4/);
    assert.ok(c.querySelector("#plan_sender_name"), "the first detail is selected");
    const apply = () => buttons(c, "Save & next")[0];
    assert.equal(apply().disabled, true, "nothing typed yet");
    await type(c.querySelector("#plan_sender_name"), "Ayesha");
    await click(buttons(c, "Recipient name")[0]);
    await type(c.querySelector("#plan_recipient_name"), "Bilal");
    assert.match(c.querySelector('[data-outline-field="sender_name"]').textContent, /Ayesha/, "the outline fills in as you type");
    await click(apply());
    const [call] = api.__calls("answerDraftPlanV2");
    assert.deepEqual(call.args[1], { expectedVersion: 0, answers: { sender_name: "Ayesha", recipient_name: "Bilal" } });
    assert.match(c.querySelector("[data-plan-progress]").textContent, /2\/4/);
    assert.ok(c.querySelector("[data-plan-saved]"), "Saved just now after a real save");
    await p.unmount();
});

test("a known detail is changed through the real plan answers, and Confirm waits for it", async () => {
    api.__respond("myDocumentsV2", { data: { items: [], has_more: false } });
    api.__respond("createDraftPlanV2", { data: {
        id: "p1", version: 0, status: "ready", title: "Legal notice draft", prompt: "Demand rent",
        template_type: "legal_notice", extraction_status: "ok", fields: { sender_name: "Ayesha" }, questions: [] } });
    api.__respond("answerDraftPlanV2", { data: {
        id: "p1", version: 1, status: "ready", title: "Legal notice draft", prompt: "Demand rent",
        template_type: "legal_notice", extraction_status: "ok", fields: { sender_name: "Ayesha Khan" }, questions: [] } });
    const p = await mount({ seed: { prompt: "Demand rent", templateType: "legal_notice" } });
    const input = p.container.querySelector("#plan_sender_name");
    assert.equal(input.value, "Ayesha", "what the AI read is shown and editable");
    await type(input, "Ayesha Khan");
    assert.equal(buttons(p.container, "Confirm plan")[0].disabled, true, "confirming would drop the change");
    await click(buttons(p.container, "Save & next")[0]);
    const [call] = api.__calls("answerDraftPlanV2");
    assert.deepEqual(call.args[1], { expectedVersion: 0, answers: { sender_name: "Ayesha Khan" } });
    assert.equal(buttons(p.container, "Confirm plan")[0].disabled, false);
    await p.unmount();
});

test("clearing an inferred plan detail is saved as a missing detail", async () => {
    api.__respond("myDocumentsV2", { data: { items: [], has_more: false } });
    const original = { id: "p-clear", version: 0, status: "ready", title: "Legal notice draft", prompt: "Demand rent",
        template_type: "legal_notice", extraction_status: "ok", fields: { sender_name: "Ayesha" }, questions: [] };
    api.__respond("createDraftPlanV2", { data: original });
    api.__respond("answerDraftPlanV2", { data: { ...original, version: 1, status: "needs_details", fields: { sender_name: "" },
        questions: [{ field: "sender_name", label: "Sender name", question: "Please provide the sender name.", options: [] }] } });
    const p = await mount({ seed: { prompt: "Demand rent", templateType: "legal_notice" } });
    await type(p.container.querySelector("#plan_sender_name"), "");
    assert.equal(buttons(p.container, "Confirm plan")[0].disabled, true);
    await click(buttons(p.container, "Save & next")[0]);
    assert.equal(api.__calls("answerDraftPlanV2")[0].args[1].answers.sender_name, "");
    assert.match(p.container.querySelector("[data-plan-remaining]").textContent, /1 remaining/);
    await p.unmount();
});

test("Undo takes back the last change to a detail, locally", async () => {
    const p = await openWorkspace();
    const c = p.container;
    const undo = () => c.querySelector("[data-undo]");
    assert.equal(undo(), null, "Undo is hidden until the placeholders panel is open");
    await click(c.querySelector("[data-edit-toggle]"));
    assert.equal(undo().disabled, true, "nothing to undo yet");
    await type(document.querySelector("#ph_demand"), "Pay now");
    assert.equal(c.querySelector("[data-placeholder-count]").textContent, "0");
    assert.equal(undo().disabled, false);
    await click(undo());
    assert.equal(document.querySelector("#ph_demand").value, "", "the change was not undone");
    assert.equal(c.querySelector("[data-placeholder-count]").textContent, "1");
    assert.equal(api.__calls("saveDocumentWorkspaceV2").length, 0, "Undo must not save");
    await p.unmount();
});

test("Edit on a template document opens its details; the free-text editor shows its bar only while editing", async () => {
    const p = await openWorkspace();
    await click(p.container.querySelector("[data-edit-toggle]"));
    assert.ok(p.container.querySelector('[aria-label="Complete document"]'), "Edit should show the details of a template document");
    await p.unmount();

    api.__respond("myDocumentsV2", { data: { items: ROWS, has_more: false } });
    api.__respond("getDocumentWorkspaceV2", { data: { ...WORKSPACE, source: "freeform_html", fields: null, body_html: "<p>Dear tenant</p>" } });
    api.__respond("getDocumentV2", { data: DETAIL() });
    api.__respond("previewRevisionV2", { data: null, error: { message: "x" } });
    const q = await mount({});
    await click(q.container.querySelector('[data-doc="d1"]'));
    assert.equal(q.container.querySelector('[aria-label="Text formatting"]'), null, "the formatting bar shows only while editing");
    await click(q.container.querySelector("[data-edit-toggle]"));
    const bar = q.container.querySelector('[aria-label="Text formatting"]');
    assert.ok(bar, "Edit did not open the formatting bar");
    for (const label of ["Bold", "Italic", "Underline", "Numbered list", "Quote", "Undo"]) assert.ok(bar.querySelector(`[aria-label="${label}"]`), `${label} is missing`);
    assert.ok(bar.querySelector('[aria-label="Paragraph style"]'));
    assert.ok(buttons(bar, "Save")[0]);
    await q.unmount();
});

/* ── Templates read and edited as TEXT (2026-10-08) ─────────────────────────
 * A text-editable template opens as its own wording on a page, not a PDF. Its
 * details still fill through the panel (and the text follows them, live);
 * Edit edits the words themselves, which saves the document as edited text. */
const TEXT_HTML = '<h1 style="text-align:center">LEGAL NOTICE</h1><p>From Ayesha</p><h2>DEMAND</h2><p>[[DEMAND]]</p><p>Within <b>15 days</b>.</p>';
async function openTextWorkspace({ revision = {} } = {}) {
    api.__respond("myDocumentsV2", { data: { items: ROWS, has_more: false } });
    api.__respond("getDocumentWorkspaceV2", { data: { ...WORKSPACE, text_html: TEXT_HTML, text_editable: true, source_template: "legal_notice" } });
    api.__respond("getDocumentV2", { data: { ...DETAIL(), current_revision: { ...DETAIL().current_revision, ...revision } } });
    const p = await mount({});
    await click(p.container.querySelector('[data-doc="d1"]'));
    return p;
}
const page = c => c.querySelector("[data-rte]");
const waitPreview = () => act(async () => { await new Promise(r => setTimeout(r, 480)); });

test("a text-editable template opens as text on a page, with no PDF fetched", async () => {
    const p = await openTextWorkspace();
    const c = p.container;
    assert.equal(api.__calls("previewRevisionV2").length, 0, "the text view needs no PDF");
    assert.equal(c.querySelector('[aria-label="PDF document pages"]'), null);
    assert.match(page(c).textContent, /LEGAL NOTICE.*From Ayesha.*15 days/s);
    assert.equal(page(c).getAttribute("contenteditable"), "false", "reading, not editing, until Edit");
    // A blank detail is a marked placeholder; clicking it opens that detail.
    const mark = page(c).querySelector('mark[data-ph="DEMAND"]');
    assert.ok(mark, "the placeholder is not marked");
    await click(mark);
    const form = c.querySelector('[aria-label="Complete document"]');
    assert.ok(form, "clicking a placeholder did not open the details");
    assert.equal(form.querySelector('[data-field-row="demand"]').dataset.active, "true");
    await p.unmount();
});

test("typing a detail updates the text live, and Save still saves the details", async () => {
    const p = await openTextWorkspace();
    const c = p.container;
    api.__respond("previewDocumentTextV2", { data: { text_html: TEXT_HTML.replace("[[DEMAND]]", "Pay Rs 50,000") } });
    await openPlaceholders(c);
    await type(document.querySelector("#ph_demand"), "Pay Rs 50,000");
    await waitPreview();
    const [preview] = api.__calls("previewDocumentTextV2");
    assert.deepEqual([preview.args[0], preview.args[1].demand], ["d1", "Pay Rs 50,000"]);
    assert.match(page(c).textContent, /Pay Rs 50,000/, "the text did not follow the detail");
    assert.equal(api.__calls("saveDocumentWorkspaceV2").length, 0, "the preview saved something");
    api.__respond("saveDocumentWorkspaceV2", { data: { document_id: "d1" } });
    await click(c.querySelector("[data-save]"));
    const [save] = api.__calls("saveDocumentWorkspaceV2");
    assert.equal(save.args[1].fields.demand, "Pay Rs 50,000");
    assert.equal(save.args[1].bodyHtml, null, "filling details must not turn the document into edited text");
    await p.unmount();
});

test("Edit edits the words: the formatting bar, a plain warning, placeholders filled in the text, saved as text", async () => {
    const p = await openTextWorkspace();
    const c = p.container;
    assert.equal(c.querySelector('[aria-label="Text formatting"]'), null);
    await click(c.querySelector("[data-edit-toggle]"));
    assert.ok(c.querySelector('[aria-label="Text formatting"]'), "Edit did not open the editor");
    assert.equal(page(c).getAttribute("contenteditable"), "true");
    assert.match(c.querySelector("[data-text-edit-note]").textContent, /required-particulars check will not run/);
    // The placeholders panel now fills the [[NAME]]s in the text itself.
    await openPlaceholders(c);
    const row = c.querySelector('[data-token-row="DEMAND"]');
    assert.ok(row, "the placeholder is not listed");
    await type(document.querySelector("#tok_DEMAND"), "Pay <now> & vacate");
    await click(buttons(row, "Fill")[0]);
    assert.equal(c.querySelector('[data-token-row="DEMAND"]'), null, "a filled placeholder is still listed");
    assert.match(page(c).innerHTML, /Pay &lt;now&gt; &amp; vacate/, "the value must go in as text");
    api.__respond("saveDocumentWorkspaceV2", { data: { document_id: "d1" } });
    await click(c.querySelector("[data-save]"));
    const [save] = api.__calls("saveDocumentWorkspaceV2");
    assert.equal(save.args[1].fields, null);
    assert.match(save.args[1].bodyHtml, /LEGAL NOTICE.*Pay &lt;now&gt; &amp; vacate.*15 days/s);
    assert.equal(save.args[1].expectedRevisionId, "r1", "the stale-revision guard was not sent");
    await p.unmount();
});

test("a detail never answered is still a blank: counted, listed, and saved when filled (QA 2026-10-08)", async () => {
    // The stored fields have no sender_address at all; the text still asks for it.
    api.__respond("myDocumentsV2", { data: { items: ROWS, has_more: false } });
    api.__respond("getDocumentWorkspaceV2", { data: { ...WORKSPACE, text_html: TEXT_HTML.replace("From Ayesha", "From Ayesha, [[SENDER_ADDRESS]]"), text_editable: true, source_template: "legal_notice" } });
    api.__respond("getDocumentV2", { data: DETAIL() });
    const q = await mount({});
    await click(q.container.querySelector('[data-doc="d1"]'));
    const qc = q.container;
    assert.equal(qc.querySelector("[data-placeholders-badge]").textContent, "2", "the unanswered detail was not counted");
    await openPlaceholders(qc);
    const input = document.querySelector("#ph_sender_address");
    assert.ok(input, "the unanswered detail is not listed");
    await type(input, "House 1, Lahore");
    api.__respond("saveDocumentWorkspaceV2", { data: { document_id: "d1" } });
    await click(qc.querySelector("[data-save]"));
    const [save] = api.__calls("saveDocumentWorkspaceV2");
    assert.equal(save.args[1].fields.sender_address, "House 1, Lahore");
    await q.unmount();
});

test("an edited revision's particulars read 'not checked — wording edited', never a pass or a fail", async () => {
    const edited = workspaceChecks({ template_type: "edited_document", compliance: { checked: false } }, { edited: true });
    assert.equal(edited.rows.find(r => r.key === "particulars").value, "Not checked — wording edited");
    assert.equal(edited.rows.find(r => r.key === "particulars").fix, false, "edited wording has nothing to fill in");
    assert.equal(edited.issues, 0);
});

test("placeholder helpers: tokens found once, filled as text", async () => {
    const { placeholderTokens, fillPlaceholder } = await import("../src/components/client/documents/DocsDrafts.jsx");
    assert.deepEqual(placeholderTokens("<p>[[A_B]] and [[A_B]] and [[C]]</p>"), ["A_B", "C"]);
    assert.equal(fillPlaceholder("<p>[[A]] [[A]]</p>", "A", "<b>&"), "<p>&lt;b&gt;&amp; &lt;b&gt;&amp;</p>");
});

test("the left column has no New draft button (removed 2026-10-08)", async () => {
    const p = await openWorkspace();
    assert.equal(p.container.querySelector("[data-new-draft]"), null);
    assert.equal(buttons(p.container.querySelector('[aria-label="Draft history"]'), "New draft").length, 0);
    await p.unmount();
});

test("Ask AI: a pill over the page opens a composer with quick requests; the sidebar has no Ask box", async () => {
    const p = await openWorkspace();
    const c = p.container;
    const side = c.querySelector('[aria-label="Draft history"]');
    assert.equal(side.querySelector("#drafts-ask"), null, "the sidebar Ask box is gone");
    assert.doesNotMatch(side.textContent, /Get changes to this document/);
    assert.equal(c.querySelector("[data-ask-composer]"), null, "closed until asked");
    await click(c.querySelector("[data-ask-ai]"));
    const composer = c.querySelector("[data-ask-composer]");
    assert.ok(composer, "Ask AI did not open the composer");
    assert.equal(c.querySelector("[data-ask-ai]"), null, "the pill gives way to the composer");
    // A quick request only fills the box; nothing is sent until Send.
    const chip = composer.querySelector("[data-ask-suggestion]");
    await click(chip);
    assert.equal(document.querySelector("#drafts-ask").value, chip.textContent);
    assert.equal(api.__calls("assistDocumentWorkspaceV2").length, 0);
    await click(c.querySelector('[aria-label="Close Ask AI"]'));
    assert.ok(c.querySelector("[data-ask-ai]"), "closing brings the pill back");
    await p.unmount();
});

test("Ask AI is off while a lawyer reviews the document", async () => {
    const p = await openWorkspace("submitted");
    assert.equal(p.container.querySelector("[data-ask-ai]").disabled, true);
    await p.unmount();
});

test("quick requests follow what the document is", async () => {
    const { askSuggestions } = await import("../src/components/client/documents/DocsDrafts.jsx");
    assert.match(askSuggestions("nda").join(" "), /return-of-materials/);
    assert.ok(askSuggestions("something_else").length > 0);
});

test("sidebar rows: no box on the open row, and the time shows only on hover", async () => {
    const p = await openWorkspace();
    const side = p.container.querySelector('[aria-label="Draft history"]');
    const open = side.querySelector('[data-doc="d1"]').closest("[data-side-row]");
    assert.equal(open.dataset.selected, "true");
    assert.equal(open.style.background, "", "the open row has no tinted box");
    assert.ok(!open.style.borderLeft && !open.style.borderRadius, "no accent edge or rounded box");
    const hint = open.querySelector("[data-row-hint]");
    assert.match(hint.textContent, /^Edited /);
    assert.equal(hint.style.fontSize, "11px", "the time is small");
    // Hidden unless the row is hovered or focused -- a stylesheet rule, as :hover needs.
    const css = [...side.querySelectorAll("style")].map(s => s.textContent).join("");
    assert.match(css, /\[data-side-row\] \[data-row-hint\]\{display:none\}/);
    assert.match(css, /\[data-side-row\]:hover \[data-row-hint\]/);
    await p.unmount();
});

/* Where the document stands with the lawyer, in the workspace (2026-10-08). */
async function openWithReview(review, extra = {}) {
    api.__respond("myDocumentsV2", { data: { items: ROWS, has_more: false } });
    api.__respond("getDocumentWorkspaceV2", { data: { ...WORKSPACE, review_status: review } });
    api.__respond("getDocumentV2", { data: { ...DETAIL(review), ...extra } });
    api.__respond("previewRevisionV2", { data: null, error: { message: "preview unavailable in test" } });
    const p = await mount({});
    await click(p.container.querySelector('[data-doc="d1"]'));
    return p;
}

test("the workspace shows the lawyer's decision and note", async () => {
    let p = await openWithReview("returned", { review_note: "Add the tenant's CNIC number." });
    let banner = p.container.querySelector('[data-review-banner="returned"]');
    assert.ok(banner, "no banner for a returned document");
    assert.match(banner.textContent, /Your lawyer requested changes/);
    assert.match(banner.querySelector("[data-review-note]").textContent, /Add the tenant's CNIC number\./);
    assert.equal(p.container.querySelector("[data-placeholders-toggle]").disabled, false, "a returned document can be edited");
    await p.unmount();

    p = await openWithReview("approved", { review_note: "" });
    banner = p.container.querySelector('[data-review-banner="approved"]');
    assert.match(banner.textContent, /Approved by your lawyer.*new approval/s);
    assert.equal(banner.querySelector("[data-review-note]"), null, "no empty note");
    await p.unmount();

    p = await openWithReview("submitted");
    banner = p.container.querySelector('[data-review-banner="submitted"]');
    assert.match(banner.textContent, /With your lawyer for review.*Frozen for lawyer review/s);
    await p.unmount();

    p = await openWithReview("none");
    assert.equal(p.container.querySelector("[data-review-banner]"), null, "a private draft has no banner");
    await p.unmount();
});
