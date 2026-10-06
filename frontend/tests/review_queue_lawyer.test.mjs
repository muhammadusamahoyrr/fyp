/* The lawyer's Review Queue (DOCUMENT_REVIEW_REQUEST_PLAN.md §5, Phase 2).
 *
 * Mounted in a real DOM against the generated API stub. What is pinned here:
 * reading never marks a request viewed; decisions are explicit, double-click
 * safe and reload on a stale state; the original downloads only through the
 * server's verified route; the deep link opens exactly one request or says
 * "not found"; and nothing sends a client's document to the Analyzer. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/lawyer/documents/review-queue" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node", "Event", "CustomEvent",
                    "KeyboardEvent", "MutationObserver", "getComputedStyle", "localStorage", "DOMParser"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const rr = await import("../src/lib/reviewRequests.js");
const { ReviewQueuePage } = await import("../src/components/lawyer/ReviewQueuePage.jsx");
const { default: LawyerLink } = await import("../src/app/lawyer/review-requests/[id]/page.jsx");
const { Sidebar } = await import("../src/components/lawyer/layout.jsx");
const { ThemeCtx, CaseCtx, NotifCtx } = await import("../src/components/lawyer/theme.js");
const { DARK } = await import("../src/components/admin/themes.js");
const { ToastCtx } = await import("../src/components/shared/Toast.jsx");
const { AuthProvider } = await import("../src/context/AuthContext.jsx");
const h = React.createElement;

const ID = "0123456789abcdef0123456789abcdef";
const SHA = "c".repeat(64);
const ROW = { id: ID, state_version: 2, status: "submitted", client_id: "c1", client_name: "Ayesha Khan",
              engagement_id: "e1", revision_id: "r2", version: 2, pdf_sha256: SHA,
              document_title: "Shop rent agreement", note: "Please check clause 7.", focus: ["deposit", "notice period"],
              submitted_at: "2026-10-02T10:00:00Z", document_available: true, analysis: null };
const OTHER = { ...ROW, id: "f".repeat(32), status: "accepted", state_version: 3, document_title: "Affidavit",
                client_name: "Bilal Raza", submitted_at: "2026-09-30T10:00:00Z" };

const mounted = new Set();
const pages = [];
const toasts = [];
async function mount(tree) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(tree); });
    await settle(30);
    const unmount = async () => {
        if (!mounted.has(unmount)) return;
        mounted.delete(unmount);
        await act(async () => root.unmount());
        container.remove();
    };
    mounted.add(unmount);
    return { container, unmount };
}
const settle = (ms = 15) => act(async () => { await new Promise(r => setTimeout(r, ms)); });
const queue = () => mount(h(ThemeCtx.Provider, { value: DARK },
    h(CaseCtx.Provider, { value: { setPage: p => pages.push(p) } },
        h(ToastCtx.Provider, { value: { show: m => toasts.push(m) } }, h(ReviewQueuePage)))));
const btn = (el, text) => [...el.querySelectorAll("button")].find(b => b.textContent.trim() === text);
async function click(el) {
    assert.ok(el, "nothing to click");
    await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
    await settle();
}
async function type(input, value) {
    const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype, "value").set;
    await act(async () => { setter.call(input, value); input.dispatchEvent(new dom.window.Event("input", { bubbles: true })); });
}

test.beforeEach(() => {
    api.__reset();
    pages.length = 0;
    toasts.length = 0;
    globalThis.__nav && (globalThis.__nav.redirected = []);
    dom.reconfigure({ url: "http://localhost/lawyer/documents/review-queue" });
    api.__respond("listReviewInbox", { data: { items: [ROW, OTHER], next_cursor: null } });
    api.__respond("listEngagements", { data: [{ id: "e1", case_title: "Shop dispute" }] });
    api.__respond("getReviewRequest", { data: ROW });
});
test.afterEach(async () => {
    for (const unmount of [...mounted]) await unmount();
    document.body.innerHTML = "";
});

// ── the link and the rules ──────────────────────────────────────────────────

test("the lawyer deep link goes only to the Review Queue, with a validated id", async () => {
    assert.equal(rr.lawyerReviewRequestDeepLink(ID), `/lawyer/documents/review-queue?request=${ID}`);
    for (const bad of ["//evil.example", "https://evil.example", "../x", ID.toUpperCase(), "", null]) {
        assert.equal(rr.lawyerReviewRequestDeepLink(bad), "/lawyer/documents/review-queue?missing=1", String(bad));
    }
    await LawyerLink({ params: Promise.resolve({ id: ID }) });
    assert.deepEqual(globalThis.__nav.redirected, [`/lawyer/documents/review-queue?request=${ID}`]);
    assert.deepEqual(rr.readLawyerReviewLink(`?request=${ID}`), { requestId: ID, invalid: false });
    assert.deepEqual(rr.readLawyerReviewLink("?request=%2F%2Fevil"), { requestId: null, invalid: true });
});

test("actions follow the state; download follows the server's own answer", () => {
    assert.deepEqual(rr.lawyerActions({ status: "submitted", document_available: true }),
                     { markViewed: true, accept: true, decline: true, download: true });
    assert.deepEqual(rr.lawyerActions({ status: "viewed", document_available: true }),
                     { markViewed: false, accept: true, decline: true, download: true });
    assert.deepEqual(rr.lawyerActions({ status: "accepted", document_available: false }),
                     { markViewed: false, accept: false, decline: false, download: false });
    assert.deepEqual(rr.lawyerActions({ status: "cancelled", document_available: false }),
                     { markViewed: false, accept: false, decline: false, download: false });
});

test("nothing here hands a client's document to the Analyzer", async () => {
    assert.equal(rr.ANALYZER_HANDOFF_ENABLED, false);
    const source = (await readFile(new URL("../src/components/lawyer/ReviewQueuePage.jsx", import.meta.url), "utf8"))
        .replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
    assert.doesNotMatch(source, /AnalyzerWorkspace|Open in Analyzer|createAnalysis|startAnalysis|uploadAnalysis|analyzer\//i);
});

// ── the list ────────────────────────────────────────────────────────────────

test("the queue lists client, document, case and date, newest first as the server sent them", async () => {
    const p = await queue();
    const rows = [...p.container.querySelectorAll("[data-rq-row]")];
    assert.deepEqual(rows.map(r => r.dataset.rqRow), [ID, OTHER.id]);
    assert.match(rows[0].textContent, /Shop rent agreement · v2/);
    assert.match(rows[0].textContent, /Ayesha Khan · Shop dispute · sent/);
    assert.match(rows[0].textContent, /New/);
    assert.match(rows[1].textContent, /Accepted/);
});

test("loading, empty, error-with-retry and feature-off are distinct", async () => {
    api.__respond("listReviewInbox", { data: { items: [], next_cursor: null } });
    let p = await queue();
    assert.match(p.container.querySelector("[data-rq-empty]").textContent, /No review requests yet/);
    await p.unmount();

    api.__respond("listReviewInbox", { data: null, status: 503, error: { code: "transactions_unavailable", message: "x" } });
    p = await queue();
    assert.ok(p.container.querySelector('[role="alert"]'));
    api.__respond("listReviewInbox", { data: { items: [ROW], next_cursor: null } });
    await click(btn(p.container, "Try again"));
    assert.equal(p.container.querySelectorAll("[data-rq-row]").length, 1);
    await p.unmount();

    api.__respond("listReviewInbox", { data: null, status: 404, error: { code: "feature_disabled", message: "Not found." } });
    p = await queue();
    assert.deepEqual(pages, ["documents"], "feature off sends the lawyer back to Documents");
});

test("paging follows the server's cursor; a filter asks the server", async () => {
    api.__respond("listReviewInbox", ({ cursor, status }) => ({ data: {
        items: cursor ? [OTHER] : [ROW], next_cursor: cursor ? null : "cur-2", status } }));
    const p = await queue();
    await click(btn(p.container, "Load more"));
    assert.equal(api.__calls("listReviewInbox").at(-1).args[0].cursor, "cur-2");
    assert.deepEqual([...p.container.querySelectorAll("[data-rq-row]")].map(r => r.dataset.rqRow), [ID, OTHER.id]);
    await click(btn(p.container, "Accepted"));
    assert.equal(api.__calls("listReviewInbox").at(-1).args[0].status, "accepted");
});

// ── the detail ──────────────────────────────────────────────────────────────

test("opening a request shows note, focus and the frozen version, and marks nothing viewed", async () => {
    const p = await queue();
    await click(p.container.querySelector(`[data-rq-row="${ID}"]`));
    const detail = p.container.querySelector(`[data-rq-detail="${ID}"]`);
    assert.equal(detail.querySelector("[data-rq-note]").textContent, "Please check clause 7.");
    assert.deepEqual([...detail.querySelectorAll("[data-rq-focus] li")].map(li => li.textContent), ["deposit", "notice period"]);
    assert.match(detail.querySelector("[data-rq-version]").textContent, /Version 2 · sent .*Frozen when sent/);
    assert.match(detail.textContent, /Document Analyzer is not available for client documents/);
    assert.equal(btn(detail, "Open in Analyzer"), undefined);
    assert.equal(api.__calls("markReviewRequestViewed").length, 0, "reading must not mark viewed");

    api.__respond("markReviewRequestViewed", { data: { ...ROW, status: "viewed", state_version: 3 } });
    await click(btn(detail, "Mark as viewed"));
    assert.equal(api.__calls("markReviewRequestViewed").length, 1);
    assert.equal(btn(p.container.querySelector(`[data-rq-detail="${ID}"]`), "Mark as viewed"), undefined);
});

test("accept asks first, sends the version read, and a double click accepts once", async () => {
    let release;
    api.__respond("acceptReviewRequest", () => new Promise(r => { release = () => r(
        { data: { ...ROW, status: "accepted", state_version: 3, document_available: true } }); }));
    const p = await queue();
    await click(p.container.querySelector(`[data-rq-row="${ID}"]`));
    await click(btn(p.container, "Accept"));
    const yes = btn(p.container, "Yes, accept");
    await act(async () => {
        yes.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
        yes.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    });
    await act(async () => { release(); });
    await settle();
    const calls = api.__calls("acceptReviewRequest");
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0].args.slice(0, 2), [ID, { expectedStateVersion: 2 }]);
    assert.ok(calls[0].args[2], "an Idempotency-Key is sent");
    assert.match(p.container.querySelector(`[data-rq-row="${ID}"]`).textContent, /Accepted/);
});

test("a stale state (the client cancelled meanwhile) reloads the request and the queue", async () => {
    api.__respond("acceptReviewRequest", { data: null, status: 409, error: { code: "stale_state", message: "moved" } });
    const p = await queue();
    await click(p.container.querySelector(`[data-rq-row="${ID}"]`));
    api.__respond("getReviewRequest", { data: { ...ROW, status: "cancelled", state_version: 3,
                                                cancel_reason: "client_cancelled", document_available: false } });
    const listsBefore = api.__calls("listReviewInbox").length;
    await click(btn(p.container, "Accept"));
    await click(btn(p.container, "Yes, accept"));
    const detail = p.container.querySelector(`[data-rq-detail="${ID}"]`);
    assert.match(detail.querySelector("[data-rq-problem]").textContent, /changed while you were looking/);
    assert.match(detail.textContent, /The client cancelled this request/);
    assert.equal(btn(detail, "Accept"), undefined);
    assert.equal(btn(detail, "Download original"), undefined, "a cancelled request offers no file");
    assert.ok(api.__calls("listReviewInbox").length > listsBefore, "the queue reloads too");
});

test("decline: an optional reason, counted to 500, never more", async () => {
    api.__respond("declineReviewRequest", { data: { ...ROW, status: "declined", state_version: 3, document_available: false } });
    const p = await queue();
    await click(p.container.querySelector(`[data-rq-row="${ID}"]`));
    await click(btn(p.container, "Decline"));
    const area = p.container.querySelector('textarea[aria-label="Reason for declining"]');
    await type(area, "x".repeat(501));
    assert.equal(p.container.querySelector("[data-rq-counter]").textContent, "501 / 500");
    assert.ok(btn(p.container, "Decline request").disabled);
    await type(area, "  Outside my practice area.  ");
    await click(btn(p.container, "Decline request"));
    const [call] = api.__calls("declineReviewRequest");
    assert.deepEqual(call.args.slice(0, 2), [ID, { expectedStateVersion: 2, reason: "Outside my practice area." }]);
});

test("the original downloads through the verified route; an integrity refusal is said plainly", async () => {
    api.__respond("downloadReviewRequestDocument", { error: "x", code: "integrity", status: 409 });
    const p = await queue();
    await click(p.container.querySelector(`[data-rq-row="${ID}"]`));
    await click(btn(p.container, "Download original"));
    const [call] = api.__calls("downloadReviewRequestDocument");
    assert.equal(call.args[0], ID);
    assert.match(call.args[1], /Shop rent agreement v2\.pdf/);
    assert.match(p.container.querySelector("[data-rq-problem]").textContent, /does not match the version the client sent/);
});

// ── the deep link on the page ───────────────────────────────────────────────

test("a deep link opens exactly that request, then leaves the address clean", async () => {
    dom.reconfigure({ url: `http://localhost/lawyer/documents/review-queue?request=${ID}` });
    const p = await queue();
    assert.equal(api.__calls("getReviewRequest")[0]?.args[0], ID);
    assert.ok(p.container.querySelector(`[data-rq-detail="${ID}"]`));
    assert.equal(dom.window.location.search, "");
});

test("a request not sent to this lawyer, or a malformed id, is a calm 'not found'", async () => {
    dom.reconfigure({ url: `http://localhost/lawyer/documents/review-queue?request=${ID}` });
    api.__respond("getReviewRequest", { data: null, status: 404, error: { code: "not_found", message: "Not found." } });
    let p = await queue();
    assert.equal(p.container.querySelector("[data-rq-not-found]").textContent, rr.LAWYER_REQUEST_NOT_FOUND);
    assert.equal(p.container.querySelector("[data-rq-detail]"), null);
    await p.unmount();

    api.__reset();
    api.__respond("listReviewInbox", { data: { items: [], next_cursor: null } });
    dom.reconfigure({ url: "http://localhost/lawyer/documents/review-queue?request=%2F%2Fevil.example" });
    p = await queue();
    assert.equal(api.__calls("getReviewRequest").length, 0, "a malformed id never reaches the server");
    assert.equal(p.container.querySelector("[data-rq-not-found]").textContent, rr.LAWYER_REQUEST_NOT_FOUND);
});

test("the deep link survives the dashboard remounting the queue (onboarding check)", async () => {
    // Found in the 2026-10-03 browser smoke: a lawyer arriving from a
    // notification without the onboarding cache saw the queue mount, unmount
    // for the onboarding check, and mount again -- and the request never
    // opened, because the first mount had already stripped the address.
    dom.reconfigure({ url: `http://localhost/lawyer/documents/review-queue?request=${ID}` });
    // Every lookup waits until the test releases it: no timing, no race.
    const pending = [];
    api.__respond("getReviewRequest", () => new Promise(r => pending.push(() => r({ data: ROW }))));
    const first = await queue();                                    // the first answer is still in flight
    assert.equal(pending.length, 1);
    await first.unmount();                                          // ...the onboarding swap
    assert.equal(dom.window.location.search, "", "the address was cleaned on the first read");
    await act(async () => { pending[0](); });                       // the late answer reaches an unmounted detail
    await settle();
    const second = await queue();
    assert.equal(pending.length, 2, "the remounted queue looks the request up again");
    await act(async () => { pending[1](); });
    await settle();
    assert.ok(second.container.querySelector(`[data-rq-detail="${ID}"]`), "the request opens after the remount");
    await second.unmount();
    // Settled now: a later visit to the queue does not reopen it.
    const third = await queue();
    assert.equal(third.container.querySelector("[data-rq-detail]"), null);
});

// ── the sidebar ─────────────────────────────────────────────────────────────

test("the sidebar lists Review Queue only while the feature is on", async () => {
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer", full_name: "Adv. Bilal" } });
    const sidebar = on => mount(h(AuthProvider, null, h(ThemeCtx.Provider, { value: DARK },
        h(NotifCtx.Provider, { value: { notifs: [], clearNotif: () => {}, clearAll: () => {} } },
            h(Sidebar, { page: "documents", setPage: () => {}, collapsed: false, setCollapsed: () => {},
                         unreadMsgs: 0, reviewQueueOn: on })))));
    let p = await sidebar(false);
    assert.doesNotMatch(p.container.textContent, /Review Queue/);
    assert.match(p.container.textContent, /Document Analyzer/);
    await p.unmount();
    p = await sidebar(true);
    assert.match(p.container.textContent, /Review Queue/);
});
