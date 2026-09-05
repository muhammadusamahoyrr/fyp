/* Restoration, MOUNTED — real React, real effects, real async ordering.
 *
 * The previous version of this feature was "verified" by a source test that
 * checked `getDocumentV2` appeared somewhere in the component. It did appear.
 * It also never ran: restoration keyed off `genCaseId`, which is set during
 * generation and starts null, so after a refresh — the only situation the
 * feature exists for — the effect returned early every single time.
 *
 * A regex cannot see that. Nothing can, short of mounting the thing and letting
 * the effects fire. So these mount a real component tree in jsdom, drive it
 * through remounts and prop changes with `act`, and assert on what the
 * component was actually told.
 *
 * The hook is tested rather than ModDocuments itself because the component is
 * ~1700 lines of JSX behind a bundler alias, and node runs neither. The hook is
 * the part with the lifecycle, which is the part that was broken.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

/* jsdom must exist before react-dom/client is imported. */
const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "http://localhost/",
});
function define(name, value) {
    // `navigator` is a getter-only property on modern Node globals, so a plain
    // assignment throws. defineProperty works for both kinds.
    Object.defineProperty(globalThis, name, {
        value, writable: true, configurable: true,
    });
}
for (const name of ["window", "document", "navigator", "HTMLElement",
                    "Element", "Node", "Event", "CustomEvent",
                    "MutationObserver", "getComputedStyle"]) {
    define(name, dom.window[name] ?? dom.window[name.toLowerCase()]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const { useDocumentResume, resolveCaseId } =
    await import("../src/lib/useDocumentResume.js");
const { rememberDraft } = await import("../src/lib/documentResume.js");

const { createElement: h } = React;

function fakeStorage() {
    const map = new Map();
    return {
        getItem: k => (map.has(k) ? map.get(k) : null),
        setItem: (k, v) => map.set(k, String(v)),
        removeItem: k => map.delete(k),
    };
}

function documentFor(id, extra = {}) {
    return {
        id,
        title: `Document ${id}`,
        review_status: "none",
        current_version: 1,
        current_revision: { revision_id: `rev-${id}`, pdf_sha256: "a".repeat(64) },
        ...extra,
    };
}

/* A deferred async getDocument, so response ORDER can be controlled. */
function deferredGetter() {
    const pending = new Map();
    const calls = [];
    const getDocument = docId => {
        calls.push(docId);
        return new Promise(resolve => pending.set(docId, resolve));
    };
    return {
        getDocument,
        calls,
        resolve: (docId, value) => pending.get(docId)(value),
        settled: docId => pending.has(docId),
    };
}

/* Mount a probe that just reports what the hook hands it. */
function mountProbe({ caseId, hasDocument = false, getDocument, storage }) {
    const restores = [];
    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);

    function Probe(props) {
        useDocumentResume({
            caseId: props.caseId,
            hasDocument: props.hasDocument,
            getDocument,
            storage,
            onRestore: (state, forCase) => restores.push({ state, forCase }),
        });
        return null;
    }

    const render = props => act(() => {
        root.render(h(Probe, props));
    });

    return {
        restores,
        render,
        rerender: props => render(props),
        unmount: () => act(() => root.unmount()),
        initial: () => render({ caseId, hasDocument }),
    };
}

/* ── resolving the active case ────────────────────────────────────────────── */

test("the active case is resolved once cases load", () => {
    // THE DEFECT. Restoration keyed off a value only generation ever set, so
    // after a refresh it was null forever and nothing was restored.
    assert.equal(resolveCaseId(null, []), null);
    assert.equal(resolveCaseId(null, [{ _id: "case-1" }]), "case-1");
    assert.equal(resolveCaseId("case-2", [{ _id: "case-1" }]), "case-2");
    assert.equal(resolveCaseId(null, [{ id: "case-3" }]), "case-3");
    assert.equal(resolveCaseId(null, undefined), null);
});

/* ── restoring after a remount ────────────────────────────────────────────── */

test("a remembered document is restored after a real remount", async () => {
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-abc", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument, storage });
    probe.initial();

    assert.deepEqual(g.calls, ["doc-abc"], "the document was never requested");

    await act(async () => { g.resolve("doc-abc", { data: documentFor("doc-abc") }); });

    assert.equal(probe.restores.length, 1);
    assert.equal(probe.restores[0].state.docId, "doc-abc");
    assert.equal(probe.restores[0].state.docRevisionId, "rev-doc-abc");
    probe.unmount();
});

test("nothing happens until the case id arrives", async () => {
    // The refresh sequence: mount with no case, cases load, THEN restore.
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-abc", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: null, getDocument: g.getDocument, storage });
    probe.render({ caseId: null, hasDocument: false });
    assert.deepEqual(g.calls, [], "asked before the case was known");

    probe.rerender({ caseId: "case-1", hasDocument: false });
    assert.deepEqual(g.calls, ["doc-abc"], "did not restore once the case arrived");

    await act(async () => { g.resolve("doc-abc", { data: documentFor("doc-abc") }); });
    assert.equal(probe.restores[0].state.docId, "doc-abc");
    probe.unmount();
});

test("a document already open is not overwritten", async () => {
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-abc", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument, storage });
    probe.render({ caseId: "case-1", hasDocument: true });

    assert.deepEqual(g.calls, [], "clobbered a document already on screen");
    probe.unmount();
});

test("a case with nothing remembered asks for nothing", async () => {
    const g = deferredGetter();
    const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument,
                               storage: fakeStorage() });
    probe.initial();
    assert.deepEqual(g.calls, []);
    assert.deepEqual(probe.restores, []);
    probe.unmount();
});

/* ── switching cases ──────────────────────────────────────────────────────── */

test("switching cases restores that case's own draft", async () => {
    // A single one-shot guard made the first attempt disable every later one.
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-one", storage);
    rememberDraft("case-2", "doc-two", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument, storage });
    probe.render({ caseId: "case-1", hasDocument: false });
    await act(async () => { g.resolve("doc-one", { data: documentFor("doc-one") }); });

    probe.rerender({ caseId: "case-2", hasDocument: false });
    await act(async () => { g.resolve("doc-two", { data: documentFor("doc-two") }); });

    assert.deepEqual(g.calls, ["doc-one", "doc-two"]);
    assert.equal(probe.restores.length, 2);
    assert.equal(probe.restores[0].forCase, "case-1");
    assert.equal(probe.restores[1].forCase, "case-2");
    assert.equal(probe.restores[1].state.docId, "doc-two");
    probe.unmount();
});

test("one case is asked about only once", async () => {
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-abc", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument, storage });
    probe.render({ caseId: "case-1", hasDocument: false });
    probe.rerender({ caseId: "case-1", hasDocument: false });
    probe.rerender({ caseId: "case-1", hasDocument: false });

    assert.deepEqual(g.calls, ["doc-abc"], "re-requested on every render");
    probe.unmount();
});

/* ── the stale-response race ──────────────────────────────────────────────── */

test("a late response from a case the user has left is discarded", async () => {
    // Two switches in quick succession leave two requests in flight. Without a
    // per-attempt token the slower one wins and the user is looking at a
    // document belonging to a case they are no longer in.
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-one", storage);
    rememberDraft("case-2", "doc-two", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument, storage });
    probe.render({ caseId: "case-1", hasDocument: false });
    probe.rerender({ caseId: "case-2", hasDocument: false });

    // case-2 answers first; case-1's response arrives afterwards, too late.
    await act(async () => { g.resolve("doc-two", { data: documentFor("doc-two") }); });
    await act(async () => { g.resolve("doc-one", { data: documentFor("doc-one") }); });

    const applied = probe.restores.filter(r => r.state);
    assert.equal(applied.length, 1, "a stale response was applied");
    assert.equal(applied[0].state.docId, "doc-two");
    probe.unmount();
});

test("a response arriving after unmount is discarded", async () => {
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-abc", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument, storage });
    probe.render({ caseId: "case-1", hasDocument: false });
    probe.unmount();

    await act(async () => { g.resolve("doc-abc", { data: documentFor("doc-abc") }); });
    assert.deepEqual(probe.restores, [], "restored into an unmounted tree");
});

/* ── documents that are gone ──────────────────────────────────────────────── */

test("a document that no longer exists is forgotten", async () => {
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-gone", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument, storage });
    probe.render({ caseId: "case-1", hasDocument: false });
    await act(async () => {
        g.resolve("doc-gone", { error: { code: "not_found" } });
    });

    assert.equal(probe.restores[0].state, null);
    assert.equal(storage.getItem("attorneyai.draft.case-1"), null,
                 "a dead document is still remembered");
    probe.unmount();
});

/* ── review states survive the round trip ─────────────────────────────────── */

test("a document under review restores its status", async () => {
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-abc", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument, storage });
    probe.render({ caseId: "case-1", hasDocument: false });
    await act(async () => {
        g.resolve("doc-abc", {
            data: documentFor("doc-abc", { review_status: "submitted" }),
        });
    });

    assert.equal(probe.restores[0].state.reviewStatus, "submitted");
    assert.equal(probe.restores[0].state.step, 3);
    probe.unmount();
});

test("a recovery state restores its explanation", async () => {
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-abc", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument, storage });
    probe.render({ caseId: "case-1", hasDocument: false });
    await act(async () => {
        g.resolve("doc-abc", {
            data: documentFor("doc-abc", {
                review_status: "migration_unrecoverable",
                recovery: {
                    state: "migration_unrecoverable",
                    headline: "Needs to be sent again",
                    explanation: "…",
                    next_action: "regenerate_and_resubmit",
                    blocks_use: true,
                },
            }),
        });
    });

    assert.equal(probe.restores[0].state.reviewRecovery.state,
                 "migration_unrecoverable");
    probe.unmount();
});
