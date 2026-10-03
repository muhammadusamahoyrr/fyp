/* Document review requests, client UI (DOCUMENT_REVIEW_REQUEST_PLAN.md §10).
 *
 * The wording and rules are pure functions (lib/reviewRequests.js) and are
 * tested as such; the dialog, the requests panel and the Vault entry points
 * are mounted in a real DOM against the generated API stub, so no test can
 * reach the network. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
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
const rr = await import("../src/lib/reviewRequests.js");
const { default: ReviewRequestDialog } =
    await import("../src/components/client/documents/ReviewRequestDialog.jsx");
const { default: ReviewRequestsPanel } =
    await import("../src/components/client/documents/ReviewRequestsPanel.jsx");
const { default: DocsVault, reviewRequestsAvailable } =
    await import("../src/components/client/documents/DocsVault.jsx");
const { ToastCtx } = await import("../src/components/shared/Toast.jsx");
const toasts = [];

const SHA = "a".repeat(64);
const ROW = { id: "d1", title: "Shop rent agreement", revision_id: "r2", pdf_sha256: SHA, downloadable: true, version: 2 };
const REVISIONS = { data: { items: [
    { revision_id: "r2", version: 2, status: "generated", pdf_sha256: SHA, created_at: "2026-10-02T10:00:00Z" },
    { revision_id: "r3", version: 3, status: "pending", pdf_sha256: null, created_at: "2026-10-03T10:00:00Z" },
    { revision_id: "r1", version: 1, status: "generated", pdf_sha256: "b".repeat(64), created_at: "2026-09-01T10:00:00Z" },
] } };
const ENGAGEMENTS = { data: { items: [
    { engagement_id: "e1", lawyer_id: "l1", lawyer_name: "Adv. Bilal Ahmed", case_id: "c1", case_title: "Shop dispute", open_request_id: null },
] } };

async function mount(Component, props) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(React.createElement(ToastCtx.Provider, { value: { show: m => toasts.push(m) } },
            React.createElement(Component, props)));
    });
    await settle();
    let done = false;
    const unmount = async () => {
        if (done) return;
        done = true;
        mounted.delete(unmount);
        await act(async () => root.unmount());
        container.remove();
    };
    mounted.add(unmount);
    return { container, unmount };
}
const settle = () => act(async () => { await new Promise(r => setTimeout(r, 10)); });
const buttons = (el, text) => [...el.querySelectorAll("button")].filter(b => b.textContent.trim() === text);
const button = (el, text) => buttons(el, text)[0];
async function click(el) {
    assert.ok(el, "nothing to click");
    await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
    await settle();
}
async function type(input, value) {
    const proto = input.tagName === "TEXTAREA" ? dom.window.HTMLTextAreaElement.prototype
        : dom.window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    await act(async () => {
        setter.call(input, value);
        input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
}
const dialog = () => document.body.querySelector("[data-review-request-dialog]");

// Every mounted tree, so a test that fails part-way still unmounts: the dialog
// is a portal in <body>, and a leftover one would be found by the next test.
const mounted = new Set();
test.beforeEach(() => { api.__reset(); toasts.length = 0; });
test.afterEach(async () => {
    for (const unmount of mounted) await unmount();
    mounted.clear();
    document.body.innerHTML = "";
});

// ── wording and rules ───────────────────────────────────────────────────────

test("every state reads in the client's words", () => {
    assert.deepEqual(rr.requestStatusView({ status: "draft" }),
        { label: "Draft", tone: "muted", detail: "Only you can see this." });
    assert.equal(rr.requestStatusView({ status: "submitted" }).label, "Sent");
    assert.equal(rr.requestStatusView({ status: "viewed" }).label, "Opened by the lawyer");
    assert.equal(rr.requestStatusView({ status: "accepted" }).label, "Accepted");
    assert.match(rr.requestStatusView({ status: "declined", decline_reason: "Outside my area." }).detail,
        /Outside my area\./);
    assert.match(rr.requestStatusView({ status: "cancelled", cancel_reason: "engagement_ended" }).detail,
        /engagement .* ended/);
    assert.match(rr.requestStatusView({ status: "cancelled", cancel_reason: "client_cancelled" }).detail, /You cancelled/);
});

test("actions follow the state: draft edits, sent cancels, finished does nothing", () => {
    assert.deepEqual(rr.requestActions({ status: "draft" }), { edit: true, delete: true, submit: true, cancel: false });
    for (const s of ["submitted", "viewed"]) {
        assert.deepEqual(rr.requestActions({ status: s }), { edit: false, delete: false, submit: false, cancel: true });
    }
    for (const s of ["accepted", "declined", "cancelled"]) {
        assert.deepEqual(rr.requestActions({ status: s }), { edit: false, delete: false, submit: false, cancel: false });
    }
});

test("each server refusal has its own wording", () => {
    for (const code of ["revision_changed", "engagement_not_active", "open_request_exists", "case_mismatch",
                        "stale_state", "request_accepted"]) {
        assert.notEqual(rr.requestErrorMessage(code), rr.requestErrorMessage("something_else"), code);
    }
    assert.equal(rr.isSafeRetry(0), true);
    assert.equal(rr.isSafeRetry(503), true);
    assert.equal(rr.isSafeRetry(409), false);
});

test("focus points are trimmed and bounded; versions are generated ones, current first", () => {
    assert.deepEqual(rr.normaliseFocus([" rent ", "", "  "]), { items: ["rent"], problem: null });
    assert.match(rr.normaliseFocus(["a", "b", "c", "d", "e", "f"]).problem, /At most 5/);
    assert.match(rr.normaliseFocus(["x".repeat(121)]).problem, /120 characters/);
    const versions = rr.shareableVersions(REVISIONS.data.items, "r1");
    assert.deepEqual(versions.map(v => v.revision_id), ["r1", "r2"]);
});

test("no fee, price, urgency or reply-time element anywhere in the feature", async () => {
    const files = ["src/lib/reviewRequests.js",
                   "src/components/client/documents/ReviewRequestDialog.jsx",
                   "src/components/client/documents/ReviewRequestsPanel.jsx"];
    for (const f of files) {
        const text = (await readFile(new URL(`../${f}`, import.meta.url), "utf8"))
            .replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");         // code, not comments
        assert.doesNotMatch(text, /\b(fee|price|urgency|urgent|reply time|PKR|Rs\.?\s?\d)/i, f);
    }
});

// ── the dialog ──────────────────────────────────────────────────────────────

function respondHappy() {
    api.__respond("listRevisionsV2", REVISIONS);
    api.__respond("reviewRequestEligibleEngagements", ENGAGEMENTS);
    api.__respond("createReviewRequest", { data: { id: "rq1", state_version: 1, status: "draft", pdf_sha256: SHA,
                                                   note: "Check clause 7.", focus: ["deposit"] } });
    api.__respond("submitReviewRequest", { data: { id: "rq1", state_version: 2, status: "submitted" } });
}

async function walkToReview(p) {
    await click(button(dialog(), "Next"));                       // version
    await click(button(dialog(), "Next"));                       // lawyer
    await type(dialog().querySelector("#rr-note"), "Check clause 7.");
    await type(dialog().querySelector('[aria-label="Focus point 1"]'), "deposit");
    await click(button(dialog(), "Next"));                       // note → review
}

test("four steps, then exactly what is shared, the D4 notice, and one create + one submit", async () => {
    respondHappy();
    const done = [];
    const p = await mount(ReviewRequestDialog, { row: ROW, onClose: () => {}, onDone: r => done.push(r) });
    const radios = [...dialog().querySelectorAll('input[name="rr-version"]')];
    assert.equal(radios.length, 2, "only generated versions are offered");
    assert.ok(radios[0].checked, "the current version is the default");
    await walkToReview(p);
    const review = dialog().querySelector("[data-rr-review]").textContent;
    for (const part of ["Shop rent agreement", "Version 2", "Adv. Bilal Ahmed", "Shop dispute", "Check clause 7.", "deposit"]) {
        assert.match(review, new RegExp(part), part);
    }
    assert.equal(dialog().querySelector("[data-rr-d4]").textContent, rr.CANCEL_LIMIT_NOTICE);

    await click(button(dialog(), "Send for review"));
    const [create] = api.__calls("createReviewRequest");
    assert.deepEqual(create.args[0], { documentId: "d1", revisionId: "r2", expectedPdfSha256: SHA,
                                       engagementId: "e1", note: "Check clause 7.", focus: ["deposit"] });
    const [submit] = api.__calls("submitReviewRequest");
    assert.deepEqual(submit.args.slice(0, 2), ["rq1", { expectedStateVersion: 1, expectedPdfSha256: SHA }]);
    assert.equal(done[0]?.status, "submitted");
    await p.unmount();
});

test("a network failure is retried with the SAME key; nothing is created twice", async () => {
    respondHappy();
    let attempt = 0;
    api.__respond("createReviewRequest", () => (++attempt === 1
        ? { data: null, error: { message: "Network error." }, status: 0 }
        : { data: { id: "rq1", state_version: 1, status: "draft", pdf_sha256: SHA, note: "Check clause 7.", focus: ["deposit"] } }));
    const p = await mount(ReviewRequestDialog, { row: ROW, onClose: () => {}, onDone: () => {} });
    await walkToReview(p);
    await click(button(dialog(), "Send for review"));
    assert.match(dialog().querySelector("[data-rr-problem]").textContent, /nothing was sent twice/);
    await click(button(dialog(), "Try again"));
    const keys = api.__calls("createReviewRequest").map(c => c.args[1]);
    assert.equal(keys.length, 2);
    assert.equal(keys[0], keys[1], "a retry must reuse its key");
    assert.equal(api.__calls("submitReviewRequest").length, 1);
    await p.unmount();
});

test("Send is disabled while a call is in flight: a double click sends once", async () => {
    respondHappy();
    let release;
    api.__respond("createReviewRequest", () => new Promise(r => { release = () => r(
        { data: { id: "rq1", state_version: 1, status: "draft", pdf_sha256: SHA, note: "Check clause 7.", focus: ["deposit"] } }); }));
    const p = await mount(ReviewRequestDialog, { row: ROW, onClose: () => {}, onDone: () => {} });
    await walkToReview(p);
    const send = button(dialog(), "Send for review");
    await act(async () => {
        send.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
        send.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    });
    assert.ok(button(dialog(), "Sending…")?.disabled, "the button is disabled in flight");
    await act(async () => { release(); });
    await settle();
    assert.equal(api.__calls("createReviewRequest").length, 1);
    await p.unmount();
});

test("no engagement: the plan's empty state with a way to hire a lawyer, and no way forward", async () => {
    api.__respond("listRevisionsV2", REVISIONS);
    api.__respond("reviewRequestEligibleEngagements", { data: { items: [] } });
    const p = await mount(ReviewRequestDialog, { row: ROW, onClose: () => {}, onDone: () => {} });
    await click(button(dialog(), "Next"));
    const empty = dialog().querySelector("[data-rr-empty]");
    assert.match(empty.textContent, new RegExp(rr.NO_ENGAGEMENT_NOTICE.replace(/[.]/g, "\\.")));
    assert.equal(empty.querySelector("a").getAttribute("href"), "/lawyers");
    assert.ok(button(dialog(), "Next").disabled);
    await p.unmount();
});

test("an open request already exists: say so, and offer to open it", async () => {
    respondHappy();
    api.__respond("createReviewRequest", { data: null, status: 409, error: {
        code: "open_request_exists", message: "exists", error: { existing_request_id: "rq-old" } } });
    const opened = [];
    const p = await mount(ReviewRequestDialog, { row: ROW, onClose: () => {}, onDone: () => {},
                                                 onOpenExisting: id => opened.push(id) });
    await walkToReview(p);
    await click(button(dialog(), "Send for review"));
    assert.match(dialog().querySelector("[data-rr-problem]").textContent, /already an open request/);
    assert.equal(button(dialog(), "Try again"), undefined, "a 409 is a decision, not a retry");
    await click(button(dialog(), "Open it"));
    assert.deepEqual(opened, ["rq-old"]);
    await p.unmount();
});

test("the note counts to its limit", async () => {
    respondHappy();
    const p = await mount(ReviewRequestDialog, { row: ROW, onClose: () => {}, onDone: () => {} });
    await click(button(dialog(), "Next"));
    await click(button(dialog(), "Next"));
    await type(dialog().querySelector("#rr-note"), "x".repeat(2001));
    assert.equal(dialog().querySelector("[data-rr-counter]").textContent, "2,001 / 2,000");
    assert.ok(button(dialog(), "Next").disabled, "an over-long note cannot go forward");
    await p.unmount();
});

// ── the requests panel ──────────────────────────────────────────────────────

const REQUESTS = { data: { next_cursor: null, items: [
    { id: "q-draft", status: "draft", state_version: 1, engagement_id: "e1", document_title: "Shop rent agreement", version: 2, created_at: "2026-10-02T10:00:00Z" },
    { id: "q-sent", status: "submitted", state_version: 2, engagement_id: "e1", document_title: "Affidavit", version: 1, created_at: "2026-10-01T10:00:00Z", submitted_at: "2026-10-01T11:00:00Z" },
    { id: "q-acc", status: "accepted", state_version: 3, engagement_id: "e1", document_title: "Notice", version: 4, created_at: "2026-09-01T10:00:00Z" },
    { id: "q-dec", status: "declined", state_version: 3, engagement_id: "e1", document_title: "Deed", version: 1, decline_reason: "Not my area.", created_at: "2026-09-01T10:00:00Z" },
] } };

test("the panel shows each state and only the actions it allows", async () => {
    api.__respond("listReviewRequests", REQUESTS);
    api.__respond("listEngagements", { data: [{ id: "e1", lawyer_name: "Adv. Bilal Ahmed", case_title: "Shop dispute" }] });
    const p = await mount(ReviewRequestsPanel, {});
    const row = id => p.container.querySelector(`[data-review-request="${id}"]`);
    assert.match(row("q-draft").textContent, /Only you can see this/);
    assert.ok(button(row("q-draft"), "Continue") && button(row("q-draft"), "Delete"));
    assert.ok(button(row("q-sent"), "Cancel request"));
    assert.equal(row("q-acc").querySelectorAll("button").length, 0, "an accepted request has no actions");
    assert.match(row("q-dec").textContent, /Not my area\./);
    assert.match(row("q-sent").textContent, /To Adv\. Bilal Ahmed · Shop dispute/);
    await p.unmount();
});

test("cancel asks first, sends the version it read, and reloads on a stale state", async () => {
    api.__respond("listReviewRequests", REQUESTS);
    api.__respond("listEngagements", { data: [] });
    api.__respond("cancelReviewRequest", { data: null, status: 409, error: { code: "stale_state", message: "moved" } });
    const p = await mount(ReviewRequestsPanel, {});
    const sent = p.container.querySelector('[data-review-request="q-sent"]');
    await click(button(sent, "Cancel request"));
    assert.equal(api.__calls("cancelReviewRequest").length, 0, "nothing is sent before the confirmation");
    await click(button(sent, "Yes, cancel it"));
    const [call] = api.__calls("cancelReviewRequest");
    assert.deepEqual(call.args.slice(0, 2), ["q-sent", { expectedStateVersion: 2 }]);
    assert.ok(typeof call.args[2] === "string" && call.args[2].length > 0, "an Idempotency-Key is sent");
    assert.equal(api.__calls("listReviewRequests").length, 2, "a stale state reloads the list");
    await p.unmount();
});

// ── the Vault ───────────────────────────────────────────────────────────────

const VAULT_ROWS = [ROW, { id: "d2", title: "Unfinished", revision_id: null, downloadable: false, version: 0 }];

test("feature off: the Vault shows nothing of review requests", async () => {
    assert.equal(reviewRequestsAvailable({ data: null, error: { code: "feature_disabled" }, status: 404 }), false);
    api.__respond("myDocumentsV2", { data: { items: VAULT_ROWS, has_more: false } });
    api.__respond("listReviewRequests", { data: null, status: 404, error: { code: "feature_disabled", message: "Not found." } });
    const p = await mount(DocsVault, { onBack: () => {}, onOpen: () => {} });
    assert.equal(p.container.querySelectorAll("[data-request-review]").length, 0);
    assert.doesNotMatch(p.container.textContent, /Review requests/);
    await p.unmount();
});

test("feature on: a generated document can be shared, an unfinished one cannot", async () => {
    api.__respond("myDocumentsV2", { data: { items: VAULT_ROWS, has_more: false } });
    api.__respond("listReviewRequests", { data: { items: [], next_cursor: null } });
    respondHappy();
    const p = await mount(DocsVault, { onBack: () => {}, onOpen: () => {} });
    const share = id => p.container.querySelector(`[data-request-review="${id}"]`);
    assert.equal(share("d1").disabled, false);
    assert.equal(share("d2").disabled, true);
    assert.ok([...p.container.querySelectorAll('[role="tab"]')].some(t => t.textContent === "Review requests"));
    await click(share("d1"));
    assert.ok(dialog(), "the request dialog opens");
    assert.deepEqual(api.__calls("listRevisionsV2")[0].args[0], "d1");
    await click(button(dialog(), "Close"));
    assert.equal(dialog(), null);
    await p.unmount();
});

test("continuing a draft says plainly that its version and lawyer are fixed", async () => {
    const draft = { id: "q-draft", status: "draft", state_version: 1, revision_id: "r2", version: 2,
                    pdf_sha256: SHA, engagement_id: "e1", lawyer_name: "Adv. Bilal Ahmed", note: null, focus: [] };
    const p = await mount(ReviewRequestDialog, { row: ROW, draft, onClose: () => {}, onDone: () => {} });
    assert.equal(dialog().querySelector("[data-rr-draft-locked]")?.textContent, rr.DRAFT_LOCKED_NOTICE);
    assert.equal(dialog().querySelectorAll('input[name="rr-version"], input[name="rr-engagement"]').length, 0,
                 "a draft offers no version or lawyer choice");
    await p.unmount();
});
