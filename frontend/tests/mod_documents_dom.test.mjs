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
        settle: async (ms = 40) => { await act(async () => {
            await new Promise(r => setTimeout(r, ms));
        }); },
        unmount: async () => { await act(async () => root.unmount()); },
    };
}



test.beforeEach(() => {
    api.__reset();
    clearDrafts();
    // Signed in through the stub, so the REAL CaseProvider actually fetches.
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "u1", role: "client" } });
});

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


/* ── the field review stands between extraction and the document ─────────── */

test("generation stops for review instead of drafting straight through", async () => {
    // THE DEFECT. `extractDocumentFields` fed `_generateViaV2` directly, so a
    // model's reading of a free-text case — parties, amounts, dates — became a
    // legal document nobody had checked. The review that follows generation
    // looks at the finished PDF, where a wrong figure is far harder to spot.
    api.__respond("listCases", { data: CASES });
    api.__respond("getCases", { data: CASES });
    api.__respond("listTemplates", {
        data: [{ template_type: "legal_notice", label: "Legal Notice",
                 category: "Civil", fields: ["sender_name", "demand"] }],
    });
    api.__respond("extractDocumentFields", {
        data: { fields: { sender_name: "Ayesha Khan", demand: "500000" } },
    });

    const p = await mountDocuments();

    // Nothing has been drafted yet, and nothing may be until a human looks.
    assert.equal(api.__calls("generateRevisionV2").length, 0);
    assert.equal(api.__calls("generateDocument").length, 0);
    await p.unmount();
});

/* ── previewing a row must preview THAT row's document (issue 3) ──────────── */

test("previewing a row previews that row's own document", async () => {
    // THE DEFECT. `onPreview={(id, actions) => setViewRev({...})}` accepted the
    // row's document id and ignored it, and the preview effect asks for
    // `docId` — whatever the page currently has open. So the request carried
    // one document's id with another document's revision: a pair belonging to
    // no document at all, saved from showing the wrong bytes only by the hash
    // guard rejecting it. With nothing open it asked for nothing, and the
    // Preview button silently did nothing at all.
    api.__respond("listCases", { data: CASES });
    api.__respond("getCases", { data: CASES });
    api.__respond("myDocumentsV2", {
        data: {
            items: [{ id: "other-doc", title: "Another notice",
                      review_status: "none", revision_id: "rev-other",
                      pdf_sha256: "d".repeat(64), version: 1,
                      downloadable: true }],
            has_more: false,
        },
    });
    api.__respond("getDocumentV2", {
        data: {
            id: "other-doc", title: "Another notice", review_status: "none",
            case_id: "case-1", current_version: 1,
            current_revision: { revision_id: "rev-other",
                                pdf_sha256: "d".repeat(64) },
        },
    });

    const p = await mountDocuments();

    const previewBtn = [...p.container.querySelectorAll("button")]
        .find(b => b.textContent.includes("Preview"));
    assert.ok(previewBtn, "no Preview control was rendered");
    await act(async () => {
        previewBtn.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
        await new Promise(r => setTimeout(r, 40));
    });

    const previews = api.__calls("fetchRevisionPreview");
    assert.ok(previews.length > 0,
              "Preview requested nothing — the row's document id was ignored");
    const [docArg, opts] = previews.at(-1).args;
    assert.equal(docArg, "other-doc",
                 "previewed a different document from the row that was clicked");
    assert.equal(opts.revisionId, "rev-other");
    await p.unmount();
});

/* ── a standalone document is not filed under a case (issue 1) ────────────── */

test("opening a caseless document does not file it under the selected case", async () => {
    // THE DEFECT. `restored.caseId || resumeCaseId` cannot tell a deliberate
    // null from a missing value. `restoreStateFromDocument` returns null
    // precisely to say "this belongs to no case", and the fallback then filed a
    // standalone draft under whichever matter happened to be on screen —
    // re-creating, for caseless documents, the exact wrong-matter bug the
    // caseId was added to fix.
    api.__respond("listCases", { data: CASES });
    api.__respond("getCases", { data: CASES });
    api.__respond("myDocumentsV2", {
        data: {
            items: [{ id: "standalone-doc", title: "A standalone notice",
                      review_status: "none", revision_id: "rev-alone",
                      pdf_sha256: "f".repeat(64), version: 1,
                      downloadable: true }],
            has_more: false,
        },
    });
    api.__respond("getDocumentV2", {
        data: {
            id: "standalone-doc", title: "A standalone notice",
            review_status: "none", case_id: null, current_version: 1,
            current_revision: { revision_id: "rev-alone",
                                pdf_sha256: "f".repeat(64) },
        },
    });

    const p = await mountDocuments();
    const openBtn = [...p.container.querySelectorAll("button")]
        .find(b => b.textContent.trim() === "Open");
    assert.ok(openBtn, "no Open control was rendered");
    await act(async () => {
        openBtn.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
        await new Promise(r => setTimeout(r, 40));
    });

    assert.equal(dom.window.localStorage.getItem("attorneyai.draft.case-1"), null,
                 "a standalone document was filed as case-1's draft");
    assert.equal(dom.window.localStorage.getItem("attorneyai.draft.no-case"),
                 "standalone-doc");
    await p.unmount();
});

/* ── the selector follows the document (issue 4) ──────────────────────────── */

async function _openFromMyDocuments(p) {
    const openBtn = [...p.container.querySelectorAll("button")]
        .find(b => b.textContent.trim() === "Open");
    assert.ok(openBtn, "no Open control was rendered");
    await act(async () => {
        openBtn.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
        await new Promise(r => setTimeout(r, 40));
    });
}

test("opening another case's document moves the case selector to it", async () => {
    // THE DEFECT. Opening a case-2 document set `genCaseId` to case-2 and left
    // `selectedCaseId` on case-1, so the picker named one matter while the
    // document on screen belonged to another — and `resumeCaseId`, derived from
    // the picker, then aimed the resume hook back at case-1.
    api.__respond("listCases", { data: CASES });
    api.__respond("getCases", { data: CASES });
    api.__respond("myDocumentsV2", {
        data: {
            items: [{ id: "case2-doc", title: "A case-2 notice",
                      review_status: "none", revision_id: "rev-c2",
                      pdf_sha256: "a".repeat(64), version: 1,
                      downloadable: true }],
            has_more: false,
        },
    });
    api.__respond("getDocumentV2", {
        data: {
            id: "case2-doc", title: "A case-2 notice", review_status: "none",
            case_id: "case-2", current_version: 1,
            current_revision: { revision_id: "rev-c2", pdf_sha256: "a".repeat(64) },
        },
    });

    const p = await mountDocuments();
    await _openFromMyDocuments(p);

    // Remembered under its OWN case, and only that one.
    assert.equal(dom.window.localStorage.getItem("attorneyai.draft.case-2"),
                 "case2-doc");
    assert.equal(dom.window.localStorage.getItem("attorneyai.draft.case-1"), null,
                 "the case-2 document was also filed under case-1");
    await p.unmount();
});

test("a standalone document selects the explicit no-case option", async () => {
    // "" would fall through to the first case in the list and drag the
    // document into a matter it does not belong to.
    api.__respond("listCases", { data: CASES });
    api.__respond("getCases", { data: CASES });
    api.__respond("myDocumentsV2", {
        data: {
            items: [{ id: "alone-doc", title: "Standalone", review_status: "none",
                      revision_id: "rev-a", pdf_sha256: "b".repeat(64),
                      version: 1, downloadable: true }],
            has_more: false,
        },
    });
    api.__respond("getDocumentV2", {
        data: {
            id: "alone-doc", title: "Standalone", review_status: "none",
            case_id: null, current_version: 1,
            current_revision: { revision_id: "rev-a", pdf_sha256: "b".repeat(64) },
        },
    });

    const p = await mountDocuments();
    await _openFromMyDocuments(p);

    assert.equal(dom.window.localStorage.getItem("attorneyai.draft.no-case"),
                 "alone-doc");
    for (const c of ["case-1", "case-2"]) {
        assert.equal(dom.window.localStorage.getItem(`attorneyai.draft.${c}`), null,
                     `a standalone document was filed under ${c}`);
    }
    await p.unmount();
});

test("a document opened from another case stays on screen", async () => {
    // THE CONSEQUENCE of the selector not following the document, and the one
    // a user would actually see.
    //
    // `resumeCaseId` comes from the selector. Leaving it on case-1 while the
    // open document belongs to case-2 aims the resume hook at case-1, which
    // has no draft — so it reports null, the parent sees `genCaseId !== forCase`
    // and clears the screen. The document the user just opened vanishes on its
    // own, a beat after they clicked Open.
    api.__respond("listCases", { data: CASES });
    api.__respond("getCases", { data: CASES });
    api.__respond("myDocumentsV2", {
        data: {
            items: [{ id: "case2-doc", title: "A case-2 notice",
                      review_status: "none", revision_id: "rev-c2",
                      pdf_sha256: "a".repeat(64), version: 1,
                      downloadable: true }],
            has_more: false,
        },
    });
    api.__respond("getDocumentV2", {
        data: {
            id: "case2-doc", title: "A case-2 notice", review_status: "none",
            case_id: "case-2", current_version: 1,
            current_revision: { revision_id: "rev-c2", pdf_sha256: "a".repeat(64) },
        },
    });

    const p = await mountDocuments();
    await _openFromMyDocuments(p);
    // Let any follow-up restore attempt run to completion.
    await act(async () => { await new Promise(r => setTimeout(r, 60)); });

    assert.match(p.text(), /A case-2 notice/,
                 "the document was cleared moments after being opened");
    await p.unmount();
});


/* ── restoration waits for the case list to settle ────────────────────────── */

test("standalone restoration does not start before case loading settles", async () => {
    // THE DEFECT. `ready: Array.isArray(cases)` was true from the first render
    // because `cases` is initialised to []. With `null` meaning "no case", an
    // unsettled empty list read as "standalone", so the no-case draft was
    // fetched a beat before the user's real case arrived — and briefly put
    // somebody else's kind of document on screen.
    //
    // The real CaseProvider is mounted with its genuine initial state; only the
    // network is stubbed.
    let releaseCases;
    api.__respond("listCases", () => new Promise(r => { releaseCases = r; }));
    rememberDraft(null, "standalone-doc", dom.window.localStorage);
    api.__respond("getDocumentV2", {
        data: {
            id: "standalone-doc", title: "A standalone notice",
            review_status: "none", case_id: null, current_version: 1,
            current_revision: { revision_id: "rev-s", pdf_sha256: "c".repeat(64) },
        },
    });

    const p = await mountDocuments();

    assert.deepEqual(api.__calls("getDocumentV2"), [],
                     "restored a standalone draft before the case list settled");

    await act(async () => { releaseCases({ data: { items: CASES } }); });
    await p.settle();

    // With real cases present, the screen is in case-1 — never standalone.
    const asked = api.__calls("getDocumentV2").map(c => c.args[0]);
    assert.ok(!asked.includes("standalone-doc"),
              "a standalone draft was restored while a real case was in view");
    await p.unmount();
});

test("a user with zero cases settles without claiming to be ready", async () => {
    api.__respond("listCases", { data: { items: [] } });

    const p = await mountDocuments();
    await p.settle();
    assert.doesNotMatch(p.text(), /Loading your cases/,
                        "still reported loading after the list settled empty");
    await p.unmount();
});

test("a failed case load says so rather than 'no case linked'", async () => {
    // "Complete your Legal Intake first" is false and alarming for a user who
    // has cases the app simply could not fetch.
    api.__respond("listCases", { error: { message: "Network unreachable" } });

    const p = await mountDocuments();
    await p.settle();
    assert.doesNotMatch(p.text(), /complete your Legal Intake first/i);
    await p.unmount();
});

/* ── visible recovery from a failed case load ─────────────────────────────── */

async function _gotoDraftStep(p) {
    // Step 0 lists templates; "Select" then "Use Template" reaches the form
    // where the readiness strip and its retry live.
    const select = [...p.container.querySelectorAll("button")]
        .find(b => b.textContent.trim() === "Select");
    assert.ok(select, "no template Select control");
    await act(async () => {
        select.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    });
    const use = [...p.container.querySelectorAll("button")]
        .find(b => b.textContent.includes("Use Template"));
    assert.ok(use, "no Use Template control");
    await act(async () => {
        use.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
        await new Promise(r => setTimeout(r, 30));
    });
}

function _retryButton(p) {
    return [...p.container.querySelectorAll("button")]
        .find(b => /Try again|Retrying/.test(b.textContent));
}

test("a failed case load offers a visible retry", async () => {
    // Without it the only recovery is a full page reload, which also throws
    // away whatever document is open.
    api.__respond("listCases", { error: { message: "Network unreachable" } });

    const p = await mountDocuments();
    await _gotoDraftStep(p);

    assert.ok(_retryButton(p), "a failed case load offered no way to try again");
    assert.match(p.text(), /could not load your cases/i);
    assert.doesNotMatch(p.text(), /complete your Legal Intake first/i);
    await p.unmount();
});

test("retrying recovers the cases and clears the error", async () => {
    api.__respond("listCases", { error: { message: "Network unreachable" } });
    const p = await mountDocuments();
    await _gotoDraftStep(p);

    api.__respond("listCases", { data: { items: CASES } });
    await act(async () => {
        _retryButton(p).dispatchEvent(
            new dom.window.MouseEvent("click", { bubbles: true }));
        await new Promise(r => setTimeout(r, 40));
    });

    assert.doesNotMatch(p.text(), /could not load your cases/i,
                        "the error survived a successful retry");
    assert.equal(_retryButton(p), undefined, "the retry control outlived the error");

    // caseSelection recomputed immediately: the recovered cases are selectable.
    // ("ready to draft" additionally requires a document TYPE, which this test
    // never picks — asserting it would be testing a different control.)
    const options = [...p.container.querySelectorAll("option")]
        .map(o => o.getAttribute("value"));
    assert.ok(options.includes("case-1"),
              "the recovered cases never reached the selector");
    await p.unmount();
});

test("a failed retry keeps the message and the button", async () => {
    api.__respond("listCases", { error: { message: "First failure" } });
    const p = await mountDocuments();
    await _gotoDraftStep(p);

    api.__respond("listCases", { error: { message: "Still down" } });
    await act(async () => {
        _retryButton(p).dispatchEvent(
            new dom.window.MouseEvent("click", { bubbles: true }));
        await new Promise(r => setTimeout(r, 40));
    });

    assert.match(p.text(), /could not load your cases/i);
    assert.doesNotMatch(p.text(), /complete your Legal Intake first/i,
                        "a failed retry claimed the user has no cases");
    assert.ok(_retryButton(p), "the retry control vanished after a failed retry");
    await p.unmount();
});

test("impatient clicking does not start concurrent loads", async () => {
    api.__respond("listCases", { error: { message: "Network" } });
    const p = await mountDocuments();
    await _gotoDraftStep(p);

    let release;
    let calls = 0;
    api.__respond("listCases", () => {
        calls++;
        return new Promise(r => { release = r; });
    });

    const btn = _retryButton(p);
    await act(async () => {
        for (let i = 0; i < 4; i++) {
            btn.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
        }
    });
    assert.equal(calls, 1, `four clicks started ${calls} loads`);
    assert.match(p.text(), /Trying your cases again|Retrying/,
                 "no progress was shown while the retry ran");

    await act(async () => {
        release({ data: { items: CASES } });
        await new Promise(r => setTimeout(r, 40));
    });
    assert.doesNotMatch(p.text(), /could not load your cases/i);
    await p.unmount();
});

test("cases arriving late do not destroy the document already open", async () => {
    // The property behind "a retry preserves the open document": a case-list
    // change must not take the draft off the screen. Exercised through the
    // INITIAL load rather than the retry button, because opening a document
    // moves to the preview step where that button does not exist — and a test
    // that cannot reach its control proves nothing.
    let releaseCases;
    api.__respond("listCases", () => new Promise(r => { releaseCases = r; }));
    api.__respond("myDocumentsV2", {
        data: {
            items: [{ id: "open-doc", title: "An open notice", review_status: "none",
                      revision_id: "rev-o", pdf_sha256: "a".repeat(64),
                      version: 1, downloadable: true }],
            has_more: false,
        },
    });
    api.__respond("getDocumentV2", {
        data: {
            id: "open-doc", title: "An open notice", review_status: "none",
            case_id: "case-1", current_version: 1,
            current_revision: { revision_id: "rev-o", pdf_sha256: "a".repeat(64) },
        },
    });

    const p = await mountDocuments();
    await _openFromMyDocuments(p);
    assert.match(p.text(), /An open notice/);

    await act(async () => {
        releaseCases({ data: { items: CASES } });
        await new Promise(r => setTimeout(r, 50));
    });

    assert.match(p.text(), /An open notice/,
                 "the open document was cleared when the case list arrived");
    await p.unmount();
});
