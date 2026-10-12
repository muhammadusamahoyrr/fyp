/* The sidebar → Documents request, and the sidebar that carries it. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>");
globalThis.window = dom.window;
globalThis.CustomEvent = dom.window.CustomEvent;

const nav = await import("../src/lib/documentsNav.js");

test("a request is pending until taken, and taken once", () => {
    nav.requestDocumentsView("mine");
    assert.equal(nav.peekPendingDocumentsView(), "mine");
    assert.equal(nav.peekPendingDocumentsView(), "mine", "peeking consumed it");
    assert.equal(nav.takePendingDocumentsView(), "mine");
    assert.equal(nav.takePendingDocumentsView(), null);
});

test("a mounted listener hears the request", () => {
    const heard = [];
    const on = e => heard.push(e.detail.view);
    window.addEventListener(nav.DOCUMENTS_VIEW_EVENT, on);
    nav.requestDocumentsView("new");
    window.removeEventListener(nav.DOCUMENTS_VIEW_EVENT, on);
    nav.takePendingDocumentsView();
    assert.deepEqual(heard, ["new"]);
});

test("an unknown view is ignored", () => {
    nav.requestDocumentsView("not-a-view");
    assert.equal(nav.peekPendingDocumentsView(), null);
});

test("the client sidebar nav can scroll", () => {
    const src = readFileSync(new URL("../src/components/client/Dashboard.jsx", import.meta.url), "utf8");
    const navTag = src.match(/<nav data-lenis-prevent className="thin-scrollbar" style=\{\{([^}]*)\}\}>/);
    assert.ok(navTag, "the sidebar <nav> is missing, or lost data-lenis-prevent (the wheel stops working)");
    assert.match(navTag[1], /minHeight:\s*0/, "without min-height 0 the flex child never scrolls");
    assert.match(navTag[1], /overflowY:\s*"auto"/);
});

test("workspace rows never wrap — a wrapping row cannot scroll", async () => {
    // flex-wrap sizes the row to its content, so the columns' own scrolling
    // never engaged and the page could not be scrolled at all.
    const { splitLayout } = await import("../src/components/client/documents/ui.jsx");
    for (const mobile of [false, true]) {
        const L = splitLayout(mobile);
        assert.notEqual(L.row.flexWrap, "wrap");
        assert.ok(mobile ? L.root.overflowY === "auto" : L.row.minHeight === 0,
            mobile ? "a phone must scroll the whole page" : "desktop columns must be height-bounded");
    }
    for (const file of ["client/documents/DocsDrafts.jsx", "analyzer/AnalyzerWorkspace.jsx"]) {
        const src = readFileSync(new URL(`../src/components/${file}`, import.meta.url), "utf8");
        assert.doesNotMatch(src, /flex: 1, minHeight: 0, display: "flex", flexWrap: "wrap"/, `${file} has a wrapping workspace row`);
    }
});

test("the draft form asks only for what generation actually uses", () => {
    // Case reference, jurisdiction, language and "special instructions" were
    // collected and never sent anywhere — a user would believe the AI followed
    // instructions it never received.
    const src = readFileSync(new URL("../src/components/client/ModDocuments.jsx", import.meta.url), "utf8");
    for (const dead of ["Special Instructions", "Case Reference No.", "setJurisdiction", "setLanguage("]) {
        assert.ok(!src.includes(dead), `dead input is back: ${dead}`);
    }
    // And the old five-circle stepper stays gone.
    assert.ok(!src.includes("<Stepper />"));
});

test("dark Documents screens use the approved mockup palette; light mode is untouched", async () => {
    const { docsTheme, MOCKUP_DARK } = await import("../src/components/client/documents/ui.jsx");
    const dark = docsTheme({ mode: "dark", bg: "#1A2E35", primary: "#40F0DC", badgeInfo: { bg: "x" } });
    assert.equal(dark.bg, "#0f2228");
    assert.equal(dark.primary, "#3fd6c6");
    assert.equal(dark.card, MOCKUP_DARK.card);
    assert.deepEqual(dark.badgeInfo, { bg: "x" }, "app-only tokens must survive");
    const light = { mode: "light", bg: "#F2F5F4" };
    assert.equal(docsTheme(light), light);
});

test("the module tells the sidebar which Documents screen is open", () => {
    const seen = [];
    const on = e => seen.push(e.detail.view);
    window.addEventListener(nav.DOCUMENTS_SHOWN_EVENT, on);
    nav.announceDocumentsView("vault");
    nav.announceDocumentsView("bogus");
    window.removeEventListener(nav.DOCUMENTS_SHOWN_EVENT, on);
    assert.deepEqual(seen, ["vault"]);
});

test("the Documents item toggles its menu and always lands on the home", () => {
    const src = readFileSync(new URL("../src/components/client/Dashboard.jsx", import.meta.url), "utf8");
    assert.match(src, /aria-expanded=\{hasMenu \? menuOpen : undefined\}/, "no expandable state on the item");
    assert.match(src, /if \(tab === "documents"\) \{ setDocMenuOpen\(o => !o\); return; \}/,
        "clicking Documents while there must only toggle the menu");
    assert.match(src, /requestDocumentsView\("new"\);\s*setDocSection\("new"\);\s*setDocMenuOpen\(true\);/,
        "arriving at Documents must open the home, not the last draft");
    assert.match(src, /rotate\(180deg\)/, "the arrow does not flip when the menu opens");
});

test("requestOpenDocument leaves the id pending until taken, once", async () => {
    const nav = await import("../src/lib/documentsNav.js");
    nav.requestOpenDocument("doc-9");
    assert.equal(nav.takePendingDocument(), "doc-9");
    assert.equal(nav.takePendingDocument(), null);
    nav.requestOpenDocument("");
    assert.equal(nav.takePendingDocument(), null, "an empty id is no request");
});

test("the open document rides in the address and leaves it cleanly (refresh reopen)", async () => {
    const nav = await import("../src/lib/documentsNav.js");
    assert.deepEqual(nav.readOpenDocumentLink("?doc=abc_12-X"), { id: "abc_12-X", preview: false });
    assert.deepEqual(nav.readOpenDocumentLink("?doc=abc&view=preview"), { id: "abc", preview: true });
    assert.equal(nav.readOpenDocumentLink("?doc=../../etc"), null, "an id that is not an id is ignored");
    assert.equal(nav.readOpenDocumentLink("?tab=review-requests"), null);
    assert.equal(nav.readOpenDocumentLink(""), null);
});
