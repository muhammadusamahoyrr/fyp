/* The client notification deep link for document review requests.
 *
 *   /client/review-requests/{id}  →  /documents?tab=review-requests&request={id}
 *
 * Followed end to end: the redirect route, the real Documents module reading
 * the address, the Vault opening its Review requests tab, and the panel
 * loading and highlighting that request -- or saying "not found" without
 * detail. With the feature off, the link lands on the ordinary Vault. */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node", "Event",
                    "CustomEvent", "KeyboardEvent", "MutationObserver", "getComputedStyle", "localStorage",
                    "requestAnimationFrame", "cancelAnimationFrame", "DOMParser"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

// Component timers are Node's; track them so the file can exit (see mod_documents_dom).
const liveTimers = new Set();
const realSetInterval = globalThis.setInterval, realClearInterval = globalThis.clearInterval;
const realSetTimeout = globalThis.setTimeout, realClearTimeout = globalThis.clearTimeout;
define("setInterval", (...a) => { const id = realSetInterval(...a); liveTimers.add(id); return id; });
define("clearInterval", id => { liveTimers.delete(id); return realClearInterval(id); });
define("setTimeout", (...a) => { const id = realSetTimeout(...a); liveTimers.add(id); return id; });
define("clearTimeout", id => { liveTimers.delete(id); return realClearTimeout(id); });

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const rr = await import("../src/lib/reviewRequests.js");
const { default: ReviewRequestLink } = await import("../src/app/client/review-requests/[id]/page.jsx");
const { default: ReviewRequestsPanel } =
    await import("../src/components/client/documents/ReviewRequestsPanel.jsx");
const { ToastCtx } = await import("../src/components/shared/Toast.jsx");
const h = React.createElement;

const ID = "0123456789abcdef0123456789abcdef";
const SHA = "a".repeat(64);
const FOCUSED = { id: ID, status: "viewed", state_version: 3, engagement_id: "e1",
                  document_title: "Shop rent agreement", version: 2, created_at: "2026-09-01T10:00:00Z" };
const OTHER = { id: "f".repeat(32), status: "draft", state_version: 1, engagement_id: "e1",
                document_title: "Another", version: 1, created_at: "2026-10-02T10:00:00Z" };

const mounted = new Set();
async function mountTree(tree) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(tree); });
    await settle(40);
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

async function mountDocuments(url) {
    dom.reconfigure({ url });
    const { default: ModDocuments } = await import("../src/components/client/ModDocuments.jsx");
    const { CaseProvider } = await import("../src/components/shared/CaseContext.jsx");
    const { AuthProvider } = await import("../src/context/AuthContext.jsx");
    const { ToastContainer } = await import("../src/components/shared/Toast.jsx");
    const { DARK } = await import("../src/components/admin/themes.js");
    const { ThemeCtx, HeaderActionsCtx } = await import("../src/components/client/theme.js");
    const p = await mountTree(h(AuthProvider, null,
        h(ThemeCtx.Provider, { value: DARK },
            h(HeaderActionsCtx.Provider, { value: { setHeaderActions: () => {} } },
                h(ToastContainer, { theme: DARK }, h(CaseProvider, null, h(ModDocuments)))))));
    await settle(60);
    return p;
}

test.beforeEach(() => {
    api.__reset();
    // The stub holds a reference to this object from import time: reset it, never replace it.
    globalThis.__nav.redirected = [];
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "u1", role: "client" } });
    api.__respond("listCases", { data: [] });
    api.__respond("getCases", { data: [] });
    api.__respond("listTemplates", { data: [] });
    api.__respond("myDocumentsV2", { data: { items: [{ id: "d1", title: "Shop rent agreement", revision_id: "r2",
                                                       pdf_sha256: SHA, downloadable: true, version: 2 }],
                                             has_more: false } });
    api.__respond("listEngagements", { data: [{ id: "e1", lawyer_name: "Adv. Bilal Ahmed", case_title: "Shop dispute" }] });
});
test.afterEach(async () => {
    for (const unmount of [...mounted]) await unmount();
    document.body.innerHTML = "";
});
test.after(() => {
    for (const id of liveTimers) { realClearInterval(id); realClearTimeout(id); }
    dom.window.close();
});

// ── the link itself ─────────────────────────────────────────────────────────

test("the redirect goes only to /documents, with a well-formed id as a query value", async () => {
    assert.equal(rr.reviewRequestDeepLink(ID), `/documents?tab=review-requests&request=${ID}`);
    for (const bad of ["../../evil", "https://evil.example/x", "//evil.example", ID.toUpperCase(),
                       `${ID}?x=1`, "", null, undefined, "a".repeat(33), "<script>"]) {
        const link = rr.reviewRequestDeepLink(bad);
        assert.equal(link, "/documents?tab=review-requests&missing=1", String(bad));
    }
    await ReviewRequestLink({ params: Promise.resolve({ id: ID }) });
    await ReviewRequestLink({ params: Promise.resolve({ id: "https://evil.example" }) });
    assert.deepEqual(globalThis.__nav.redirected, [
        `/documents?tab=review-requests&request=${ID}`, "/documents?tab=review-requests&missing=1"]);
});

test("the Documents page reads the link strictly", () => {
    assert.deepEqual(rr.readReviewRequestLink(`?tab=review-requests&request=${ID}`),
                     { open: true, requestId: ID, invalid: false });
    assert.deepEqual(rr.readReviewRequestLink("?tab=review-requests&request=../x"),
                     { open: true, requestId: null, invalid: true });
    assert.deepEqual(rr.readReviewRequestLink("?tab=review-requests&missing=1"),
                     { open: true, requestId: null, invalid: true });
    assert.deepEqual(rr.readReviewRequestLink(`?tab=analyzer&request=${ID}`),
                     { open: false, requestId: null, invalid: false });
    assert.equal(rr.readReviewRequestLink("").open, false);
});

// ── end to end through the real Documents module ────────────────────────────

test("a notification link opens the Review requests tab on exactly that request", async () => {
    api.__respond("listReviewRequests", { data: { items: [OTHER], next_cursor: null } });
    api.__respond("getReviewRequest", { data: FOCUSED });
    const p = await mountDocuments(`http://localhost/documents?tab=review-requests&request=${ID}`);
    const tab = [...p.container.querySelectorAll('[role="tab"]')].find(t => t.textContent === "Review requests");
    assert.ok(tab, "the Review requests tab exists");
    assert.equal(tab.getAttribute("aria-selected"), "true");
    assert.equal(api.__calls("getReviewRequest")[0]?.args[0], ID);
    const focused = p.container.querySelector("[data-rr-focused]");
    assert.equal(focused?.dataset.reviewRequest, ID, "the linked request is shown and highlighted");
    assert.ok(p.container.querySelector(`[data-review-request="${OTHER.id}"]`), "the rest of the list is still there");
    assert.equal(dom.window.location.pathname + dom.window.location.search, "/documents",
                 "the link is consumed: a refresh does not replay it");
});

test("an unavailable or another client's request is a calm 'not found', nothing more", async () => {
    api.__respond("listReviewRequests", { data: { items: [OTHER], next_cursor: null } });
    // The server answers a missing id and another client's id with the same 404.
    api.__respond("getReviewRequest", { data: null, status: 404, error: { code: "not_found", message: "Not found." } });
    const p = await mountDocuments(`http://localhost/documents?tab=review-requests&request=${ID}`);
    const alert = p.container.querySelector("[data-rr-not-found]");
    assert.equal(alert?.textContent, rr.REQUEST_NOT_FOUND);
    assert.equal(p.container.querySelector("[data-rr-focused]"), null);
    assert.ok(p.container.querySelector(`[data-review-request="${OTHER.id}"]`), "the client's own list still shows");
});

test("a malformed id never reaches the server", async () => {
    api.__respond("listReviewRequests", { data: { items: [], next_cursor: null } });
    const p = await mountDocuments("http://localhost/documents?tab=review-requests&request=%2F%2Fevil.example");
    assert.equal(api.__calls("getReviewRequest").length, 0);
    assert.equal(p.container.querySelector("[data-rr-not-found]")?.textContent, rr.REQUEST_NOT_FOUND);
});

test("feature off: the link lands on the ordinary Vault, with no review or Analyzer UI", async () => {
    api.__respond("listReviewRequests", { data: null, status: 404,
                                          error: { code: "feature_disabled", message: "Not found." } });
    const p = await mountDocuments(`http://localhost/documents?tab=review-requests&request=${ID}`);
    assert.ok(p.container.querySelector('[data-vault-row="d1"]'), "the ordinary Vault is shown");
    const tabs = [...p.container.querySelectorAll('[role="tab"]')].map(t => t.textContent);
    assert.ok(!tabs.includes("Review requests"));
    assert.equal(tabs.find((_, i) => p.container.querySelectorAll('[role="tab"]')[i]
        .getAttribute("aria-selected") === "true"), "All Documents");
    assert.equal(p.container.querySelectorAll("[data-request-review]").length, 0);
    assert.equal(p.container.querySelector("[data-rr-not-found]"), null);
    assert.equal(api.__calls("getReviewRequest").length, 0);
    assert.doesNotMatch(p.container.textContent, /Analy[sz]er/);
    assert.equal(document.body.querySelector("[data-review-request-dialog]"), null);
    assert.equal(dom.window.location.search, "");
});

// ── the panel on its own ────────────────────────────────────────────────────

test("a linked request that is not on the first page is still shown first", async () => {
    api.__respond("listReviewRequests", { data: { items: [OTHER], next_cursor: "c2" } });
    api.__respond("getReviewRequest", { data: FOCUSED });
    const p = await mountTree(h(ToastCtx.Provider, { value: { show: () => {} } },
        h(ReviewRequestsPanel, { focusId: ID })));
    const rows = [...p.container.querySelectorAll("[data-review-request]")].map(r => r.dataset.reviewRequest);
    assert.deepEqual(rows, [ID, OTHER.id]);
    assert.equal(p.container.querySelector("[data-rr-focused]").getAttribute("aria-current"), "true");
});
