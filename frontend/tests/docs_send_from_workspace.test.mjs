/* "Send to lawyer" from the AI drafting workspace (2026-10-07; in the
 * workspace's own send panel since 2026-10-08).
 *
 * It used to land on the old guided flow's review step ("Step 2 of 4",
 * "Approve Draft", Back / Continue) with the sidebar on Templates. It now
 * opens the approved "Send for lawyer review" screen directly, approves in
 * place, downloads for real, sends through the same submitDocumentV2 contract,
 * and its way back returns to the same document in the workspace. */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/documents" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node", "Event",
                    "CustomEvent", "MutationObserver", "getComputedStyle", "localStorage", "sessionStorage",
                    "requestAnimationFrame", "cancelAnimationFrame", "DOMParser"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);
const liveTimers = new Set();
const realSetInterval = globalThis.setInterval, realClearInterval = globalThis.clearInterval;
define("setInterval", (...a) => { const id = realSetInterval(...a); liveTimers.add(id); return id; });
define("clearInterval", id => { liveTimers.delete(id); return realClearInterval(id); });

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { requestDocumentsView, DOCUMENTS_SHOWN_EVENT } = await import("../src/lib/documentsNav.js");
const h = React.createElement;

const SHA = "a".repeat(64);
const ROW = { id: "d1", title: "Rent notice", template_type: "legal_notice", review_status: "none",
    updated_at: "2026-10-07T10:00:00Z", revision_id: "r2", pdf_sha256: SHA, downloadable: true, version: 2 };
const DETAIL = { id: "d1", title: "Rent notice", template_type: "legal_notice", review_status: "none", current_version: 2,
    current_revision: { revision_id: "r2", pdf_sha256: SHA, version: 2, created_at: "2026-10-07T10:00:00Z",
        compliance: null, verification: { ran: true, counts: { total: 0 } } } };
const WORKSPACE = { document_id: "d1", title: "Rent notice", source: "structured_fields", template_type: "legal_notice",
    fields: { sender_name: "Ayesha", demand: "" }, body_html: null,
    base_revision_id: "r2", base_version: 2, content_epoch: 1, review_status: "none" };

const settle = (ms = 30) => act(async () => { await new Promise(r => setTimeout(r, ms)); });
const btn = (el, text) => [...el.querySelectorAll("button")].find(b => b.textContent.trim().startsWith(text));
async function click(el) {
    assert.ok(el, "nothing to click");
    await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
    await settle();
}

async function mount() {
    const { default: ModDocuments } = await import("../src/components/client/ModDocuments.jsx");
    const { CaseProvider } = await import("../src/components/shared/CaseContext.jsx");
    const { AuthProvider } = await import("../src/context/AuthContext.jsx");
    const { ToastContainer } = await import("../src/components/shared/Toast.jsx");
    const { DARK } = await import("../src/components/admin/themes.js");
    const { ThemeCtx, HeaderActionsCtx } = await import("../src/components/client/theme.js");
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(AuthProvider, null, h(ThemeCtx.Provider, { value: DARK },
            h(HeaderActionsCtx.Provider, { value: { setHeaderActions: () => {} } },
                h(ToastContainer, { theme: DARK }, h(CaseProvider, null, h(ModDocuments)))))));
    });
    await settle(40);
    return { container, unmount: async () => { await act(async () => root.unmount()); container.remove(); } };
}

const shown = [];
dom.window.addEventListener(DOCUMENTS_SHOWN_EVENT, e => shown.push(e.detail.view));

test.beforeEach(() => {
    // The open document rides in the address (?doc=); each test starts clean.
    dom.window.history.replaceState(null, "", "/documents");
    api.__reset();
    shown.length = 0;
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "u1", role: "client" } });
    api.__respond("listCases", { data: [] });
    api.__respond("getCases", { data: [] });
    api.__respond("listTemplates", { data: [{ template_type: "legal_notice", label: "Legal Notice", category: "Civil",
        description: "A formal notice.", fields: ["sender_name", "demand"], structured_fields: [], drafting_mode: "ai" }] });
    api.__respond("myDocumentsV2", { data: { items: [ROW], has_more: false } });
    api.__respond("getDocumentWorkspaceV2", { data: WORKSPACE });
    api.__respond("getDocumentV2", { data: DETAIL });
    api.__respond("previewRevisionV2", { data: null, error: { message: "no preview in tests" } });
    api.__respond("listEngagements", { data: [{ lawyer_id: "L1", lawyer_name: "Sara Ahmed", case_title: "Shop dispute" }] });
    api.__respond("submitDocumentV2", { data: { lawyer_name: "Sara Ahmed" } });
    api.__respond("downloadDocumentFile", {});
});
test.after(() => { for (const id of liveTimers) realClearInterval(id); dom.window.close(); });

async function openSendScreen() {
    const p = await mount();
    await act(async () => { requestDocumentsView("drafts"); });
    await settle();
    await click(p.container.querySelector('[data-doc="d1"]'));
    await click(btn(p.container, "Send to lawyer"));
    await settle(40);
    return p;
}
const panel = c => c.querySelector("[data-send-panel]");

/* Sending happens IN the workspace (2026-10-08): a send panel beside the
 * document, then the status banner. The old guided-flow send screen is not
 * entered from the drafting workspace any more. */
test("Send to lawyer opens the send panel in the workspace, not another screen", async () => {
    const p = await openSendScreen();
    assert.ok(panel(p.container), "the send panel did not open");
    assert.ok(p.container.querySelector("[data-document-workspace]"), "the workspace was left");
    assert.equal(p.container.querySelector('[data-flow-header="send"]'), null, "the old send screen came back");
    // Lawyer-first (2026-10-11): the question is who reviews it; the document is a chip.
    assert.match(panel(p.container).textContent, /Who should review your document\?.*· v2/s);
    assert.match(panel(p.container).textContent, /Sara Ahmed/);
    assert.equal(shown.at(-1), "drafts", "the sidebar should stay on AI drafting");
    await p.unmount();
});

test("sending needs a lawyer and the owner's confirmation, then uses the guarded submit", async () => {
    const p = await openSendScreen();
    const send = () => p.container.querySelector("[data-send-submit]");
    assert.equal(send().disabled, true, "nothing chosen yet");
    await click([...panel(p.container).querySelectorAll('[role="radio"]')].find(b => b.textContent.includes("Sara Ahmed")));
    assert.equal(send().disabled, true, "the owner has not confirmed the version");
    await click(panel(p.container).querySelector("[data-send-confirm] input"));
    assert.equal(send().disabled, false);
    // After sending, the document reads as with the lawyer.
    api.__respond("getDocumentV2", { data: { ...DETAIL, review_status: "submitted", submitted_at: "2026-10-08T09:00:00Z" } });
    await click(send());
    await settle(40);
    const calls = api.__calls("submitDocumentV2");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].args[0], "d1");
    assert.equal(calls[0].args[1].expectedVersion, 2);
    assert.equal(calls[0].args[1].expectedPdfSha256, SHA);
    assert.equal(calls[0].args[1].lawyerId, "L1");
    assert.equal(calls[0].args[1].urgency, "normal");
    assert.ok(calls[0].args[2], "no idempotency key");
    assert.equal(panel(p.container), null, "the panel closes once sent");
    assert.ok(p.container.querySelector('[data-review-banner="submitted"]'), "the status banner should show it is with the lawyer");
    await p.unmount();
});

test("a send refused because the document moved is never reported as sent", async () => {
    api.__respond("submitDocumentV2", { data: null, status: 409, error: { code: "stale_version", message: "moved" } });
    const p = await openSendScreen();
    await click([...panel(p.container).querySelectorAll('[role="radio"]')].find(b => b.textContent.includes("Sara Ahmed")));
    await click(panel(p.container).querySelector("[data-send-confirm] input"));
    await click(p.container.querySelector("[data-send-submit]"));
    assert.match(p.container.querySelector("[data-send-issue]").textContent, /changed after you opened it/);
    assert.ok(panel(p.container), "the panel stays open with the reason");
    assert.equal(p.container.querySelector('[data-review-banner="submitted"]'), null);
    await p.unmount();
});

test("with no engaged lawyer, the panel says so and points to the marketplace", async () => {
    api.__respond("listEngagements", { data: [] });
    const p = await openSendScreen();
    assert.match(panel(p.container).querySelector("[data-no-engaged-lawyer]").textContent, /no lawyer engaged/);
    // Nobody to send to, so no Send at all -- only lawyers to hire.
    assert.equal(p.container.querySelector("[data-send-submit]"), null);
    await p.unmount();
});

test("a document with the lawyer can be withdrawn from its banner", async () => {
    api.__respond("getDocumentV2", { data: { ...DETAIL, review_status: "submitted" } });
    api.__respond("getDocumentWorkspaceV2", { data: { ...WORKSPACE, review_status: "submitted" } });
    api.__respond("withdrawDocumentV2", { data: {} });
    const p = await mount();
    await act(async () => { requestDocumentsView("drafts"); });
    await settle();
    await click(p.container.querySelector('[data-doc="d1"]'));
    api.__respond("getDocumentV2", { data: DETAIL });
    await click(p.container.querySelector("[data-withdraw]"));
    await settle(40);
    const [call] = api.__calls("withdrawDocumentV2");
    assert.equal(call.args[0], "d1");
    assert.ok(call.args[1], "no idempotency key");
    assert.equal(p.container.querySelector('[data-review-banner="submitted"]'), null, "the banner should clear");
    await p.unmount();
});

test("an edited document returned by the lawyer is revised in the workspace, never rebuilt from fields", async () => {
    // The guided flow is still reachable from the templates home's "My
    // documents". There, "Revise & Regenerate" used to rebuild an edited
    // document from the template's fields -- the template's words back.
    const edited = { ...DETAIL, review_status: "returned", review_note: "Add the tenant's CNIC.",
        current_revision: { ...DETAIL.current_revision, template_type: "edited_document" } };
    api.__respond("getDocumentV2", { data: edited });
    api.__respond("myDocumentsV2", { data: { items: [{ ...ROW, review_status: "returned" }], has_more: false } });
    const p = await mount();
    const open = [...p.container.querySelectorAll("#my-documents button")].find(b => b.textContent.trim() === "Open");
    await click(open);
    await settle(40);
    const revise = btn(p.container, "✏️ Revise in workspace");
    assert.ok(revise, "the returned screen should offer revising in the workspace");
    assert.equal(btn(p.container, "✏️ Revise & Regenerate"), undefined);
    await click(revise);
    await settle(40);
    assert.ok(p.container.querySelector("[data-document-workspace]"), "Revise did not open the workspace");
    assert.equal(api.__calls("generateRevisionV2").length, 0, "nothing may be rebuilt from fields");
    assert.equal(api.__calls("createDocumentV2").length, 0);
    await p.unmount();
});

test("a notification's document opens straight in the workspace", async () => {
    const { requestOpenDocument } = await import("../src/lib/documentsNav.js");
    requestOpenDocument("d1");                 // asked before Documents was mounted
    const p = await mount();
    await settle(40);
    assert.ok(p.container.querySelector("[data-document-workspace]"), "the document did not open");
    assert.equal(api.__calls("getDocumentWorkspaceV2")[0]?.args[0], "d1");
    assert.equal(shown.at(-1), "drafts");
    await p.unmount();
});

/* ── G: a hard refresh reopens the open document (2026-10-08) ───────────────
 * The open document's id rides in the address (`/documents?doc=<id>`). A
 * refresh mounts the module with that address: it must reopen THAT document,
 * read fresh from the server, and create nothing. */
test("opening a document puts its id in the address; leaving takes it out", async () => {
    const p = await mount();
    await act(async () => { requestDocumentsView("drafts"); });
    await settle();
    await click(p.container.querySelector('[data-doc="d1"]'));
    assert.equal(new URL(dom.window.location.href).searchParams.get("doc"), "d1");
    // Back to the drafts start: the address no longer names it.
    await click(p.container.querySelector('[aria-label="Back to drafts"]'));
    assert.equal(new URL(dom.window.location.href).searchParams.get("doc"), null);
    // A sidebar move away from an open document clears it too.
    await click(p.container.querySelector('[data-doc="d1"]'));
    await act(async () => { requestDocumentsView("new"); });
    await settle();
    assert.equal(new URL(dom.window.location.href).searchParams.get("doc"), null);
    await p.unmount();
});

test("a refresh of an open document reopens the SAME document, its status from the server, creating nothing", async () => {
    // The document was sent to a lawyer before the refresh.
    api.__respond("getDocumentV2", { data: { ...DETAIL, review_status: "submitted", submitted_at: "2026-10-08T09:00:00Z" } });
    api.__respond("getDocumentWorkspaceV2", { data: { ...WORKSPACE, review_status: "submitted" } });
    dom.window.history.replaceState(null, "", "/documents?doc=d1");     // what F5 reloads
    const p = await mount();
    await settle(40);
    assert.ok(p.container.querySelector("[data-document-workspace]"), "the document did not reopen");
    assert.equal(p.container.querySelector("[data-document-title]").textContent, "Rent notice");
    assert.deepEqual([...new Set(api.__calls("getDocumentWorkspaceV2").map(c => c.args[0]))], ["d1"]);
    assert.match(p.container.textContent, /Version 2 saved/, "the latest persisted version");
    assert.ok(p.container.querySelector('[data-review-banner="submitted"]'), "the With your lawyer banner is missing");
    assert.ok(p.container.querySelector("[data-withdraw]"), "Withdraw is missing");
    for (const create of ["createDocumentV2", "createDraftPlanV2", "generateRevisionV2", "saveDocumentWorkspaceV2", "submitDocumentV2"]) {
        assert.equal(api.__calls(create).length, 0, `${create} ran on a refresh`);
    }
    assert.equal(new URL(dom.window.location.href).searchParams.get("doc"), "d1", "the address still names it");
    assert.equal(shown.at(-1), "drafts");
    await p.unmount();
});

test("a refresh naming a document that cannot be opened clears the address and shows why", async () => {
    api.__respond("getDocumentWorkspaceV2", { data: null, status: 404, error: { code: "not_found", message: "Document not found." } });
    dom.window.history.replaceState(null, "", "/documents?doc=gone1");
    const p = await mount();
    await settle(40);
    assert.match(p.container.textContent, /Document not found/);
    assert.equal(new URL(dom.window.location.href).searchParams.get("doc"), null, "a dead id must not be asked for on every refresh");
    await p.unmount();
});

test("a refresh of an open Vault preview reopens that preview", async () => {
    api.__respond("getDocumentV2", { data: { ...DETAIL, current_revision: { ...DETAIL.current_revision, status: "generated" } } });
    api.__respond("previewRevisionV2", { data: { url: "blob:rent" } });
    dom.window.history.replaceState(null, "", "/documents?doc=d1&view=preview");
    const p = await mount();
    await settle(40);
    const preview = p.container.querySelector("[data-vault-preview]");
    assert.ok(preview, "the preview did not reopen");
    assert.equal(preview.querySelector("[data-preview-title]").textContent, "Rent notice");
    const [call] = api.__calls("previewRevisionV2");
    assert.deepEqual([call.args[0], call.args[1], call.args[2].expectedPdfSha256], ["d1", "r2", SHA]);
    await click(p.container.querySelector('[aria-label="Back to the Vault"]'));
    assert.equal(new URL(dom.window.location.href).searchParams.get("doc"), null);
    await p.unmount();
});

/* A case is OPTIONAL (2026-10-09). The server's rule (document_sharing.py): a
 * caseless document may go to any engaged lawyer; a case's document only to a
 * lawyer engaged on THAT case. The picker offered every engaged lawyer for a
 * case document, and the server then refused the send with a 403. */
const TWO = [{ lawyer_id: "L1", lawyer_name: "Sara Ahmed", case_id: "c1", case_title: "Shop dispute" },
             { lawyer_id: "L2", lawyer_name: "Bilal Khan", case_id: "c2", case_title: "Rent" }];

test("a case's document offers only the lawyer engaged on that case, chosen for the client", async () => {
    api.__respond("listEngagements", { data: TWO });
    api.__respond("getDocumentV2", { data: { ...DETAIL, case_id: "c1" } });
    const p = await openSendScreen();
    const names = [...panel(p.container).querySelectorAll('[aria-label="Reviewing lawyer"] [role="radio"]')].map(b => b.textContent);
    assert.equal(names.length, 1, `offered: ${names}`);
    assert.match(names[0], /Sara Ahmed/);
    assert.equal(panel(p.container).querySelector('[aria-label="Reviewing lawyer"] [role="radio"]').getAttribute("aria-checked"), "true");
    await p.unmount();
});

test("a document with no case offers every engaged lawyer", async () => {
    api.__respond("listEngagements", { data: TWO });
    api.__respond("getDocumentV2", { data: { ...DETAIL, case_id: null } });
    const p = await openSendScreen();
    const names = [...panel(p.container).querySelectorAll('[aria-label="Reviewing lawyer"] [role="radio"]')].map(b => b.textContent).join(" | ");
    assert.match(names, /Sara Ahmed/);
    assert.match(names, /Bilal Khan/);
    await p.unmount();
});

test("a case with no lawyer engaged on it says so, instead of offering lawyers the server refuses", async () => {
    api.__respond("listEngagements", { data: TWO });
    api.__respond("getDocumentV2", { data: { ...DETAIL, case_id: "c9" } });
    const p = await openSendScreen();
    assert.equal(panel(p.container).querySelectorAll('[aria-label="Reviewing lawyer"] [role="radio"]').length, 0);
    assert.match(panel(p.container).querySelector("[data-no-engaged-lawyer]").textContent, /engaged on this document's case/);
    await p.unmount();
});

test("after sending, the Sent screen says to whom and what comes next, and leads back", async () => {
    const p = await openSendScreen();
    await click([...panel(p.container).querySelectorAll('[role="radio"]')].find(b => b.textContent.includes("Sara Ahmed")));
    // The button names the lawyer chosen.
    assert.match(p.container.querySelector("[data-send-submit]").textContent, /Send to Sara Ahmed/);
    await click(panel(p.container).querySelector("[data-send-confirm] input"));
    api.__respond("getDocumentV2", { data: { ...DETAIL, review_status: "submitted", submitted_at: "2026-10-08T09:00:00Z" } });
    await click(p.container.querySelector("[data-send-submit]"));
    await settle(40);
    const sent = p.container.querySelector("[data-send-sent]");
    assert.ok(sent, "no Sent screen");
    assert.match(sent.textContent, /Sent to Sara Ahmed/);
    assert.match(sent.textContent, /Your lawyer reviews it/);
    await click(sent.querySelector("[data-sent-back]"));
    assert.equal(p.container.querySelector("[data-send-sent]"), null);
    assert.ok(p.container.querySelector('[data-review-banner="submitted"]'), "back on the document, with it shown as sent");
    await p.unmount();
});

/* QUICK REVIEW (2026-10-11): with nobody hired, the send page lists lawyers
 * who review one document without being hired -- no consultation, no hire. */
const REVIEWER = { id: "LX", full_name: "Hina Malik", province: "punjab", specializations: ["family", "civil"],
    experience_years: 9, rating: 4.6, total_reviews: 12, fee_pkr: 3000, turnaround_hours: 48 };
const OPEN_REQ = { id: "q1", doc_id: "d1", status: "requested", lawyer_id: "LX", lawyer_name: "Hina Malik",
    version: 2, note: "Check the amount", fee_pkr: 3000, turnaround_hours: 48,
    expires_at: new Date(Date.now() + 18 * 3600000).toISOString() };

test("with no lawyer hired, the send page lists lawyers who review documents, with their terms", async () => {
    api.__respond("listEngagements", { data: [] });
    api.__respond("listQuickReviewers", { data: { items: [REVIEWER] } });
    const p = await openSendScreen();
    await settle(40);
    assert.match(panel(p.container).textContent, /Get this document reviewed.*No meeting needed/s);
    const row = p.container.querySelector('[data-reviewer="LX"]');
    assert.ok(row, "no reviewer listed");
    assert.match(row.textContent, /Hina Malik.*Family, Civil · Punjab.*9 yrs experience.*4\.6 · 12 reviews/s);
    assert.match(row.textContent, /Rs 3,000.*48 hrs/s);
    // Nothing to hire, and no direct send: only a request.
    assert.equal(p.container.querySelector("[data-send-submit]"), null);
    assert.equal(/Hire to send/.test(panel(p.container).textContent), false);
    // The whole-case route is still there, as a link.
    await click(p.container.querySelector("[data-book-consultation]"));
    assert.equal(globalThis.__nav.pushed.at(-1), "/lawyers");
    await p.unmount();
});

test("a review request needs the owner's confirmation, sends the exact version, then shows it waiting", async () => {
    api.__respond("listEngagements", { data: [] });
    api.__respond("listQuickReviewers", { data: { items: [REVIEWER] } });
    api.__respond("requestQuickReview", { data: OPEN_REQ });
    const p = await openSendScreen();
    await settle(40);
    await click(p.container.querySelector('[data-reviewer="LX"] [data-ask-review]'));
    const dialog = p.container.querySelector("[data-request-dialog]");
    assert.ok(dialog, "no confirm dialog");
    assert.match(dialog.textContent, /Hina Malik.*Version 2.*Rs 3,000.*48 hours/s);
    const submit = () => p.container.querySelector("[data-request-submit]");
    assert.equal(submit().disabled, true, "not confirmed yet");
    await click(dialog.querySelector("[data-request-confirm] input"));
    assert.equal(submit().disabled, false);
    await click(submit());
    const calls = api.__calls("requestQuickReview");
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0].args[0], { doc_id: "d1", lawyer_id: "LX", expected_version: 2,
        expected_pdf_sha256: SHA, note: null });
    assert.equal(p.container.querySelector("[data-request-dialog]"), null, "the dialog closes once sent");
    const pending = p.container.querySelector("[data-request-pending]");
    assert.ok(pending, "the waiting view did not show");
    assert.match(panel(p.container).textContent, /Review requested/);
    assert.match(pending.textContent, /Hina Malik accepts/);
    await p.unmount();
});

test("a waiting request can be withdrawn, and the list comes back", async () => {
    api.__respond("listEngagements", { data: [] });
    api.__respond("listQuickReviewers", { data: { items: [REVIEWER] } });
    api.__respond("myQuickReviews", { data: { items: [OPEN_REQ] } });
    api.__respond("cancelQuickReview", { data: { ...OPEN_REQ, status: "cancelled" } });
    const p = await mount();
    await act(async () => { requestDocumentsView("drafts"); });
    await settle();
    await click(p.container.querySelector('[data-doc="d1"]'));
    // The header names the waiting request instead of offering another send.
    assert.equal(btn(p.container, "Send to lawyer"), undefined);
    await click(btn(p.container, "Review requested"));
    await settle(40);
    assert.ok(p.container.querySelector("[data-request-pending]"), "an open request should show as waiting");
    api.__respond("myQuickReviews", { data: { items: [{ ...OPEN_REQ, status: "cancelled" }] } });
    await click(p.container.querySelector("[data-request-cancel]"));
    assert.equal(api.__calls("cancelQuickReview")[0].args[0], "q1");
    assert.equal(p.container.querySelector("[data-request-pending]"), null);
    assert.ok(p.container.querySelector('[data-reviewer="LX"]'), "the lawyers should be back");
    await p.unmount();
});

test("a declined request is explained above the list", async () => {
    api.__respond("listEngagements", { data: [] });
    api.__respond("listQuickReviewers", { data: { items: [REVIEWER] } });
    api.__respond("myQuickReviews", { data: { items: [{ ...OPEN_REQ, status: "declined" }] } });
    const p = await openSendScreen();
    await settle(40);
    assert.match(p.container.querySelector("[data-request-closed]").textContent, /Hina Malik could not take your last request.*Nothing was shared or charged/s);
    await p.unmount();
});

test("with a lawyer engaged, quick reviews are offered below them, never the engaged lawyer again", async () => {
    api.__respond("listQuickReviewers", { data: { items: [REVIEWER, { ...REVIEWER, id: "L1", full_name: "Sara Ahmed" }] } });
    const p = await openSendScreen();
    await settle(40);
    assert.match(panel(p.container).textContent, /OR GET A QUICK REVIEW FROM ANOTHER LAWYER/);
    assert.ok(p.container.querySelector('[data-reviewer="LX"]'));
    assert.equal(p.container.querySelector('[data-reviewer="L1"]'), null);
    await p.unmount();
});
