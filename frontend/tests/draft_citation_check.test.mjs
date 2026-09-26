/* The lawyer drafter shows the server's stored citation check.
 *
 * Saving a draft ran a citation check on the server and returned it; saving to
 * Documents froze one on the artifact. Neither was displayed, and a reopened
 * draft showed nothing. See src/lib/draftVerification.js.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

import { verificationView } from "../src/lib/draftVerification.js";

/* ── environment (all top-level awaits BEFORE any test() is declared) ──── */

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
dom.window.document.execCommand = () => true;
dom.window.document.queryCommandState = () => false;
dom.window.HTMLElement.prototype.scrollIntoView = function () {};
Object.defineProperty(dom.window.HTMLElement.prototype, "innerText", {
    get() { return this.textContent; },
    set(v) { this.textContent = v; },
    configurable: true,
});

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { DocAutomationPage } = await import("../src/components/lawyer/DocAutomationPage.jsx");
const { AuthProvider } = await import("../src/context/AuthContext.jsx");
const { ThemeCtx, DARK } = await import("../src/components/lawyer/theme.js");
const { createElement: h } = React;

/* ── what a check says ─────────────────────────────────────────────────── */

const check = (counts, extra = {}) => ({ ran: true, counts: { total: 0, verified: 0,
    not_in_corpus: 0, omitted: 0, unverifiable: 0, ...counts }, ...extra });

test("a check that did not run is 'not checked', never a pass", () => {
    const v = verificationView({ ran: false, reason: "Corpus offline" });
    assert.equal(v.headline, "Citations not checked");
    assert.equal(v.tone, "warn");
    assert.equal(v.detail, "Corpus offline");
});

test("missing and repealed authorities are the headline", () => {
    const v = verificationView(check({ total: 5, verified: 2, not_in_corpus: 2, omitted: 1 }));
    assert.equal(v.tone, "danger");
    assert.match(v.headline, /2 not found in the corpus/);
    assert.match(v.headline, /1 cite repealed or omitted/);
    assert.match(v.detail, /2 of 5 found/);
});

test("all found is still 'existence only'", () => {
    const v = verificationView(check({ total: 3, verified: 3 }));
    assert.equal(v.tone, "ok");
    assert.equal(v.headline, "3 of 3 found in the corpus");
    assert.match(v.detail, /Existence only/);
});

test("unverifiable citations are not reported as found", () => {
    const v = verificationView(check({ total: 3, verified: 2, unverifiable: 1 }));
    assert.equal(v.tone, "warn");
    assert.match(v.headline, /1 could not be checked/);
});

test("no citations is neutral, and no record is nothing", () => {
    assert.equal(verificationView(check({ total: 0 })).tone, "neutral");
    assert.equal(verificationView(null), null);
});

/* ── the editor, mounted ───────────────────────────────────────────────── */

const FLAGGED = check({ total: 3, verified: 1, not_in_corpus: 2 });
const CLEAN = check({ total: 2, verified: 2 });

async function mountWithDraft(draft) {
    api.__respond("listDocDrafts", { data: [draft] });
    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(AuthProvider, null,
            h(ThemeCtx.Provider, { value: DARK }, h(DocAutomationPage))));
    });
    const settle = async (ms = 30) => act(async () => { await new Promise(r => setTimeout(r, ms)); });
    await settle();
    const byText = (re) => [...container.querySelectorAll("button")].find(b => re.test(b.textContent));
    const click = async (el) => {
        assert.ok(el, "button not found");
        await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
        await settle();
    };
    await click(byText(/My Drafts/));
    await click(byText(/^\s*Open\s*$/));
    const strip = () => container.querySelector("[data-citation-strip]");
    return {
        settle, click, byText, strip,
        draftText: () => strip().querySelector('[data-check="draft"]').textContent,
        isStale: () => Boolean(strip().querySelector("[data-stale]")),
        documentCheck: () => strip().querySelector('[data-check="document"]'),
        publishButton: () => [...container.querySelectorAll("button")]
            .find(b => /hashed copy/.test(b.title || "")),
        async type() {
            const ed = container.querySelector("[contenteditable]");
            await act(async () => {
                ed.textContent += " more";
                ed.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
            });
        },
        unmount: async () => { await act(async () => root.unmount()); container.remove(); },
    };
}

const DRAFT = { id: "draft-1", title: "Plaint", content: "<p>Under section 420 PPC.</p>",
                template_name: "Plaint — Civil Suit", case_id: null, verification: FLAGGED };

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "lawyer-1", role: "lawyer", full_name: "Test Advocate" } });
    api.__respond("listCases", { data: { items: [] } });
});

test.after(() => { dom.window.close(); });

test("a reopened draft shows the check stored with it", async () => {
    const p = await mountWithDraft(DRAFT);
    assert.match(p.draftText(), /2 not found in the corpus/);
    assert.equal(p.isStale(), false);
    await p.unmount();
});

test("editing marks the stored check out of date", async () => {
    const p = await mountWithDraft(DRAFT);
    await p.type();
    assert.equal(p.isStale(), true);
    assert.match(p.draftText(), /out of date/);
    await p.unmount();
});

test("saving replaces the check and clears the stale mark", async () => {
    api.__respond("saveDocDraft", { data: { id: "draft-1", verification: CLEAN } });
    const p = await mountWithDraft(DRAFT);
    await p.type();
    await p.click(p.byText(/Save Draft/));
    assert.equal(p.isStale(), false);
    assert.match(p.draftText(), /2 of 2 found/);
    await p.unmount();
});

test("an edit made while a save is in flight keeps the check stale", async () => {
    let page;
    api.__respond("saveDocDraft", async () => {
        await page.type();   // the lawyer keeps typing before the answer lands
        return { data: { id: "draft-1", verification: CLEAN } };
    });
    page = await mountWithDraft(DRAFT);
    await page.click(page.byText(/Save Draft/));
    assert.equal(page.isStale(), true, "a check of the OLD text was shown as current");
    await page.unmount();
});

test("the copy saved to Documents shows its own frozen check, separately", async () => {
    api.__respond("publishDraftAsDocumentV2", {
        docId: "doc-1", revisionId: "r1", pdfSha256: "h", verification: CLEAN });
    const p = await mountWithDraft(DRAFT);
    assert.equal(p.documentCheck(), null);
    await p.click(p.publishButton());
    assert.match(p.documentCheck().textContent, /frozen/i);
    assert.match(p.documentCheck().textContent, /2 of 2 found/);
    // The draft's own check is untouched by publishing.
    assert.match(p.draftText(), /2 not found in the corpus/);
    await p.unmount();
});

test("a draft saved before checks existed says so instead of showing a pass", async () => {
    const p = await mountWithDraft({ ...DRAFT, verification: undefined });
    assert.match(p.draftText(), /not checked yet/);
    await p.unmount();
});
