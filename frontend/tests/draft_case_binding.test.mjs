/* A lawyer's draft stays on its own case.
 *
 * THE BUG. The drafter's editor read its case from the page selector on every
 * render. With Case B selected, opening a draft saved under Case A grounded the
 * AI in B, re-saved the draft under B, and "Save to Documents" filed it with no
 * case at all. Every request was individually authorised — the lawyer may act
 * on both cases — so the server could not catch it. Two matters' facts mixed.
 *
 * The pure rules are tested first; then the REAL page is mounted with two
 * accessible cases and every case-bearing request is inspected.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

import {
    NO_CASE, bindingForNewDocument, pendingBindingForDraft, bindingForDraft,
    caseActionsBlocked, boundCaseId,
} from "../src/lib/draftCaseBinding.js";

/* ── environment (all top-level awaits BEFORE any test() is declared) ─────────────────────────────────────────────────── */

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node",
                    "Event", "CustomEvent", "MutationObserver", "getComputedStyle",
                    "localStorage", "requestAnimationFrame", "cancelAnimationFrame"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);
// jsdom implements neither; the editor calls both.
dom.window.document.execCommand = () => true;
dom.window.document.queryCommandState = () => false;
dom.window.HTMLElement.prototype.scrollIntoView = function () {};
// jsdom has no layout, so no `innerText`; publish refuses an empty draft by it.
Object.defineProperty(dom.window.HTMLElement.prototype, "innerText", {
    get() { return this.textContent; },
    set(v) { this.textContent = v; },
    configurable: true,
});

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { createElement: h } = React;

/* ── the rules ─────────────────────────────────────────────────────────── */

const A = { _id: "case-a", id: "A-001", title: "Matter A" };
const B = { _id: "case-b", id: "B-002", title: "Matter B" };
const ident = (c) => ({ _id: c._id, id: c.case_number || c._id, title: c.title });
const neverFetch = async () => { throw new Error("should not fetch"); };

test("a draft binds to its own case, not the selected one", async () => {
    const b = await bindingForDraft({ case_id: "case-a" }, [B, A], neverFetch, ident);
    assert.equal(b.state, "bound");
    assert.equal(boundCaseId(b), "case-a");
});

test("a caseless draft stays caseless — explicit null is honoured", async () => {
    for (const draft of [{ case_id: null }, {}]) {
        const b = await bindingForDraft(draft, [A, B], neverFetch, ident);
        assert.equal(b, NO_CASE);
        assert.equal(boundCaseId(b), null);
        assert.equal(caseActionsBlocked(b), false);
    }
});

test("a case missing from the list is fetched, not assumed gone", async () => {
    const b = await bindingForDraft({ case_id: "case-z" }, [A],
        async (id) => ({ data: { _id: id, case_number: "Z-9", title: "Page two" } }), ident);
    assert.equal(b.state, "bound");
    assert.equal(b.caseObj.title, "Page two");
});

test("an unloadable case blocks — it never falls back to another case", async () => {
    for (const fetchCase of [
        async () => ({ error: { message: "Forbidden" }, status: 403 }),
        async () => ({ error: { message: "Not found" }, status: 404 }),
        async () => { throw new Error("offline"); },
    ]) {
        const b = await bindingForDraft({ case_id: "case-z" }, [A, B], fetchCase, ident);
        assert.equal(b.state, "unavailable");
        assert.equal(boundCaseId(b), null);
        assert.equal(caseActionsBlocked(b), true);
    }
});

test("a draft is blocked while its case is still loading", () => {
    assert.equal(caseActionsBlocked(pendingBindingForDraft({ case_id: "case-a" })), true);
    assert.equal(caseActionsBlocked(pendingBindingForDraft({ case_id: null })), false);
});

test("a new document binds to the case selected when it opened", () => {
    assert.equal(boundCaseId(bindingForNewDocument(B)), "case-b");
    assert.equal(bindingForNewDocument(null), NO_CASE);
});

/* ── the page, mounted ───────────────────────────────────────────────── */

const RAW_A = { _id: "case-a", case_number: "A-001", title: "Matter A", status: "open" };
const RAW_B = { _id: "case-b", case_number: "B-002", title: "Matter B", status: "open" };

async function mountDrafter({ selected = "B-002" } = {}) {
    const { DocAutomationPage } = await import("../src/components/lawyer/DocAutomationPage.jsx");
    const { AuthProvider } = await import("../src/context/AuthContext.jsx");
    const { ThemeCtx, CaseCtx, DARK } = await import("../src/components/lawyer/theme.js");

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(AuthProvider, null,
            h(ThemeCtx.Provider, { value: DARK },
                h(CaseCtx.Provider, { value: { activeCase: selected } },
                    h(DocAutomationPage)))));
    });
    const settle = async (ms = 30) => act(async () => { await new Promise(r => setTimeout(r, ms)); });
    await settle();

    const buttons = () => [...container.querySelectorAll("button")];
    const byText = (re) => buttons().find(b => re.test(b.textContent));
    const click = async (el) => {
        assert.ok(el, "button not found");
        await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
        await settle();
    };
    return {
        container, settle, click, byText,
        publishButton: () => buttons().find(b => /hashed copy/.test(b.title || "")),
        strip: () => container.querySelector("[data-case-binding]"),
        async openDraft() {
            await click(byText(/My Drafts/));
            await click(byText(/^\s*Open\s*$/));
        },
        async askAI(text) {
            const ta = container.querySelector("textarea");
            const setter = Object.getOwnPropertyDescriptor(
                dom.window.HTMLTextAreaElement.prototype, "value").set;
            await act(async () => {
                setter.call(ta, text);
                ta.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
            });
            await click(byText(/Generate/));
        },
        unmount: async () => { await act(async () => root.unmount()); container.remove(); },
    };
}

function draftUnder(caseId) {
    return { id: "draft-1", title: "My plaint", content: "<p>Facts of the matter.</p>",
             template_name: "Plaint — Civil Suit", case_id: caseId,
             updated_at: "2026-09-20T10:00:00Z" };
}

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "lawyer-1", role: "lawyer", full_name: "Test Advocate" } });
    api.__respond("listCases", { data: { items: [RAW_A, RAW_B] } });
    api.__respond("saveDocDraft", { data: { id: "draft-1" } });
    api.__respond("publishDraftAsDocumentV2", { docId: "doc-1", revisionId: "r1", pdfSha256: "h" });
    api.__respond("aiDraftStream", undefined);
});

test.after(() => { dom.window.close(); });

test("Case B selected, draft from Case A: save, AI and publish all use Case A", async () => {
    api.__respond("listDocDrafts", { data: [draftUnder("case-a")] });
    const page = await mountDrafter({ selected: "B-002" });
    await page.openDraft();

    assert.equal(page.strip().dataset.caseBinding, "bound");
    assert.match(page.strip().textContent, /Matter A/);
    assert.doesNotMatch(page.strip().textContent, /Matter B/);

    await page.click(page.byText(/Save Draft/));
    const saves = api.__calls("saveDocDraft");
    assert.equal(saves.length, 1);
    assert.equal(saves[0].args[0].case_id, "case-a", "draft was re-saved under the selected case");

    await page.askAI("Tighten the prayer clause");
    const ai = api.__calls("aiDraftStream");
    assert.equal(ai.length, 1);
    assert.equal(ai[0].args[0].case_id, "case-a", "AI was grounded in the selected case");

    await page.click(page.publishButton());
    const pubs = api.__calls("publishDraftAsDocumentV2");
    assert.equal(pubs.length, 1);
    assert.equal(pubs[0].args[0].caseId, "case-a", "published document lost its case");

    assert.equal(api.__calls("getCase").length, 0, "a listed case was fetched again");
    await page.unmount();
});

test("a caseless draft is not adopted by the selected case", async () => {
    api.__respond("listDocDrafts", { data: [draftUnder(null)] });
    const page = await mountDrafter({ selected: "B-002" });
    await page.openDraft();

    assert.equal(page.strip().dataset.caseBinding, "none");
    await page.click(page.byText(/Save Draft/));
    assert.equal(api.__calls("saveDocDraft")[0].args[0].case_id, null);
    await page.click(page.publishButton());
    assert.equal(api.__calls("publishDraftAsDocumentV2")[0].args[0].caseId, null);
    await page.unmount();
});

test("a draft whose case cannot be loaded is blocked, not re-pointed", async () => {
    api.__respond("listDocDrafts", { data: [draftUnder("case-gone")] });
    api.__respond("getCase", { error: { message: "Forbidden" }, status: 403 });
    const page = await mountDrafter({ selected: "B-002" });
    await page.openDraft();

    assert.equal(page.strip().dataset.caseBinding, "unavailable");
    assert.match(page.strip().textContent, /paused/);
    assert.equal(page.byText(/Save Draft/).disabled, true);
    assert.equal(page.publishButton().disabled, true);

    await page.click(page.byText(/Save Draft/));
    await page.click(page.publishButton());
    await page.askAI("Anything");
    assert.equal(api.__calls("saveDocDraft").length, 0);
    assert.equal(api.__calls("publishDraftAsDocumentV2").length, 0);
    assert.equal(api.__calls("aiDraftStream").length, 0);
    await page.unmount();
});

test("a draft on a case beyond the first page is fetched and bound", async () => {
    api.__respond("listDocDrafts", { data: [draftUnder("case-z")] });
    api.__respond("getCase", { data: { _id: "case-z", case_number: "Z-9", title: "Matter Z" } });
    const page = await mountDrafter({ selected: "B-002" });
    await page.openDraft();

    assert.equal(page.strip().dataset.caseBinding, "bound");
    await page.click(page.byText(/Save Draft/));
    assert.equal(api.__calls("saveDocDraft")[0].args[0].case_id, "case-z");
    await page.unmount();
});

test("a new document uses the case selected when it was opened", async () => {
    api.__respond("listDocDrafts", { data: [] });
    const page = await mountDrafter({ selected: "B-002" });
    await page.click(page.byText(/Plaint — Civil Suit/));

    assert.equal(page.strip().dataset.caseBinding, "bound");
    await page.click(page.byText(/Save Draft/));
    assert.equal(api.__calls("saveDocDraft")[0].args[0].case_id, "case-b");
    await page.unmount();
});
