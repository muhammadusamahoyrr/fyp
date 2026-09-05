/* ModDocuments — the actual component, mounted.
 *
 * This is the file the refresh-restoration bug lived in, and the one every
 * previous attempt to test it stopped short of. The hook tests prove the
 * lifecycle logic is right; they cannot prove the component passes it the right
 * case id, or that it saves under the value it just resolved rather than the
 * state it has not yet re-rendered with. Those were the two actual defects.
 *
 * So this mounts the real thing. `next build` proving the file parses is not
 * the same as knowing the effect fires.
 *
 * The component reaches for a lot of context, so the providers it needs are
 * stubbed here — but the component under test is unmodified.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>",
                      { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, {
        value, writable: true, configurable: true,
    });
}
for (const name of ["window", "document", "navigator", "HTMLElement",
                    "Element", "Node", "Event", "CustomEvent",
                    "MutationObserver", "getComputedStyle", "localStorage",
                    "requestAnimationFrame", "cancelAnimationFrame"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

/* ModDocuments polls the review status on a setInterval. Component code uses
 * the GLOBAL timers (Node's), not jsdom's, so `window.close()` does not release
 * them and the process stays alive past the runner's timeout — every test
 * passing while the file reports failure. Tracked here and cleared at the end. */
const liveTimers = new Set();
const realSetInterval = globalThis.setInterval;
const realClearInterval = globalThis.clearInterval;
const realSetTimeout = globalThis.setTimeout;
const realClearTimeout = globalThis.clearTimeout;
define("setInterval", (...args) => {
    const id = realSetInterval(...args);
    liveTimers.add(id);
    return id;
});
define("clearInterval", id => { liveTimers.delete(id); return realClearInterval(id); });
define("setTimeout", (...args) => {
    const id = realSetTimeout(...args);
    liveTimers.add(id);
    return id;
});
define("clearTimeout", id => { liveTimers.delete(id); return realClearTimeout(id); });

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { rememberDraft, DRAFT_KEY_PREFIX } =
    await import("../src/lib/documentResume.js");

const { createElement: h } = React;

/* jsdom gives a real localStorage; clear it between tests so one test's
   remembered draft cannot satisfy another's assertion. */
function clearDrafts() {
    for (const key of Object.keys(dom.window.localStorage)) {
        if (key.startsWith(DRAFT_KEY_PREFIX)) dom.window.localStorage.removeItem(key);
    }
}

const CASES = [{ _id: "case-1", title: "A matter" },
               { _id: "case-2", title: "Another matter" }];

async function mountDocuments() {
    const { default: ModDocuments } =
        await import("../src/components/client/ModDocuments.jsx");
    const { CaseProvider } = await import("../src/components/shared/CaseContext.jsx");
    const { AuthProvider } = await import("../src/context/AuthContext.jsx");
    const { ToastContainer } = await import("../src/components/shared/Toast.jsx");
    const { DARK } = await import("../src/components/admin/themes.js");
    const { ThemeCtx, HeaderActionsCtx } =
        await import("../src/components/client/theme.js");

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    // The REAL providers, not fakes: a stubbed context can satisfy a component
    // that would break against the real one, which is the failure this whole
    // file exists to stop happening again.
    await act(async () => {
        root.render(h(
            AuthProvider, null,
            h(ThemeCtx.Provider, { value: DARK },
              h(HeaderActionsCtx.Provider,
                { value: { setHeaderActions: () => {} } },
                h(ToastContainer, { theme: DARK },
                  h(CaseProvider, null, h(ModDocuments)))))));
    });
    // Effects that fetch settle on a later tick.
    await act(async () => { await new Promise(r => setTimeout(r, 20)); });
    return {
        container,
        text: () => container.textContent,
        unmount: async () => { await act(async () => root.unmount()); },
    };
}



test.beforeEach(() => { api.__reset(); clearDrafts(); });

test.after(() => {
    for (const id of liveTimers) { realClearInterval(id); realClearTimeout(id); }
    liveTimers.clear();
    dom.window.close();
});

/* ── the defect: restoration never ran ────────────────────────────────────── */

test("a remembered document is fetched on mount", async () => {
    // THE BUG. Restoration keyed off `genCaseId`, which only a generation ever
    // sets. After a refresh it was null, the effect returned early, and
    // `getDocumentV2` was never called — while a source test asserting the
    // string "getDocumentV2" appeared in this file passed the whole time.
    api.__respond("listCases", { data: CASES });
    api.__respond("getCases", { data: CASES });
    rememberDraft("case-1", "doc-remembered", dom.window.localStorage);

    api.__respond("getDocumentV2", {
        data: {
            id: "doc-remembered", title: "A restored notice",
            review_status: "returned", current_version: 2,
            current_revision: { revision_id: "rev-2", pdf_sha256: "a".repeat(64) },
        },
    });

    const p = await mountDocuments();
    const asked = api.__calls("getDocumentV2");
    assert.equal(asked.length, 1, "the remembered document was never requested");
    assert.equal(asked[0].args[0], "doc-remembered");
    await p.unmount();
});

test("nothing is fetched when nothing was remembered", async () => {
    api.__respond("listCases", { data: CASES });
    api.__respond("getCases", { data: CASES });

    const p = await mountDocuments();
    assert.equal(api.__calls("getDocumentV2").length, 0);
    await p.unmount();
});

test("a remembered document for another case is not fetched", async () => {
    // The draft belongs to case-2; the resolved case is case-1 (the first).
    api.__respond("listCases", { data: CASES });
    api.__respond("getCases", { data: CASES });
    rememberDraft("case-2", "doc-other-case", dom.window.localStorage);

    const p = await mountDocuments();
    const asked = api.__calls("getDocumentV2").map(c => c.args[0]);
    assert.ok(!asked.includes("doc-other-case"),
              "restored a document belonging to a case that is not open");
    await p.unmount();
});

test("a restored document's title reaches the screen", async () => {
    api.__respond("listCases", { data: CASES });
    api.__respond("getCases", { data: CASES });
    rememberDraft("case-1", "doc-remembered", dom.window.localStorage);
    api.__respond("getDocumentV2", {
        data: {
            id: "doc-remembered", title: "Restored Legal Notice",
            review_status: "none", current_version: 1,
            current_revision: { revision_id: "rev-1", pdf_sha256: "b".repeat(64) },
        },
    });

    const p = await mountDocuments();
    assert.match(p.text(), /Restored Legal Notice/,
                 "the restored document is not shown anywhere");
    await p.unmount();
});

/* ── the client's own history is on the page ──────────────────────────────── */

test("the document dashboard lists documents the client owns", async () => {
    api.__respond("listCases", { data: CASES });
    api.__respond("getCases", { data: CASES });
    api.__respond("myDocumentsV2", {
        data: {
            items: [{ id: "own-1", title: "An earlier notice",
                      review_status: "approved", revision_id: "rev-own-1",
                      pdf_sha256: "c".repeat(64), version: 1,
                      downloadable: true }],
            has_more: false,
        },
    });

    const p = await mountDocuments();
    assert.ok(api.__calls("myDocumentsV2").length >= 1,
              "the client's own documents were never requested");
    assert.match(p.text(), /My Documents/);
    assert.match(p.text(), /An earlier notice/);
    await p.unmount();
});
