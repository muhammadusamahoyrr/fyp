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
const NOTHING = { hasDocument: false, caseId: null };

function mountProbe({ caseId, loaded = NOTHING, ready = true, getDocument, storage }) {
    const restores = [];
    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);

    function Probe(props) {
        useDocumentResume({
            caseId: props.caseId,
            loaded: props.loaded,
            ready: props.ready,
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
        initial: () => render({ caseId, loaded, ready }),
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

test("nothing happens until the case list has loaded", async () => {
    // The refresh sequence: mount before the cases arrive, then restore.
    //
    // `ready` carries this now, not a null `caseId`. Null is a real value here
    // — the standalone bucket — so overloading it to mean "not known yet" is
    // what made a caseless draft either unreachable or restored too early.
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-abc", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: null, getDocument: g.getDocument, storage });
    probe.render({ caseId: null, loaded: NOTHING, ready: false });
    assert.deepEqual(g.calls, [], "asked before the case list had loaded");

    probe.rerender({ caseId: "case-1", loaded: NOTHING, ready: true });
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
    probe.render({ caseId: "case-1", loaded: { hasDocument: true, caseId: "case-1" }, ready: true });

    assert.deepEqual(g.calls, [], "clobbered a document already on screen");
    probe.unmount();
});

test("a case with nothing remembered asks for nothing", async () => {
    const g = deferredGetter();
    const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument,
                               storage: fakeStorage() });
    probe.initial();
    assert.deepEqual(g.calls, [], 'asked the server about a draft that does not exist');
    // Reported as null rather than silence: the page needs to know this case
    // has nothing, or the previous case's document stays on screen under it.
    assert.equal(probe.restores.at(-1).state, null);
    assert.equal(probe.restores.at(-1).forCase, 'case-1');
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
    probe.render({ caseId: "case-1", loaded: NOTHING, ready: true });
    await act(async () => { g.resolve("doc-one", { data: documentFor("doc-one") }); });

    probe.rerender({ caseId: "case-2", loaded: NOTHING, ready: true });
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
    probe.render({ caseId: "case-1", loaded: NOTHING, ready: true });
    probe.rerender({ caseId: "case-1", loaded: NOTHING, ready: true });
    probe.rerender({ caseId: "case-1", loaded: NOTHING, ready: true });

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
    probe.render({ caseId: "case-1", loaded: NOTHING, ready: true });
    probe.rerender({ caseId: "case-2", loaded: NOTHING, ready: true });

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
    probe.render({ caseId: "case-1", loaded: NOTHING, ready: true });
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
    probe.render({ caseId: "case-1", loaded: NOTHING, ready: true });
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
    probe.render({ caseId: "case-1", loaded: NOTHING, ready: true });
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
    probe.render({ caseId: "case-1", loaded: NOTHING, ready: true });
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

/* ── a transient failure must not delete the pointer (issue 6) ────────────── */

test("a network failure keeps the saved pointer for the next attempt", async () => {
    // THE DEFECT. `if (error || !data) forgetDraft(...)` treated a dropped
    // connection exactly like a deleted document. One bad response while the
    // user was on a train and their in-progress draft became unreachable —
    // permanently, because the only pointer to it had been erased.
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-abc", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument, storage });
    probe.render({ caseId: "case-1", loaded: NOTHING, ready: true });
    await act(async () => {
        g.resolve("doc-abc", { error: { code: "network_error", message: "Failed to fetch" } });
    });

    assert.equal(storage.getItem("attorneyai.draft.case-1"), "doc-abc",
                 "a transient failure erased the only pointer to the draft");
    probe.unmount();
});

test("a server error keeps the pointer too", async () => {
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-abc", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument, storage });
    probe.render({ caseId: "case-1", loaded: NOTHING, ready: true });
    await act(async () => {
        g.resolve("doc-abc", { error: { status: 500, message: "Server error" } });
    });

    assert.equal(storage.getItem("attorneyai.draft.case-1"), "doc-abc");
    probe.unmount();
});

test("a document confirmed gone is forgotten", async () => {
    // 404 and 403 are answers, not failures: the document is deleted or is no
    // longer ours. Retrying forever against it is the other bad outcome.
    for (const error of [{ code: "not_found", status: 404 },
                         { code: "forbidden", status: 403 }]) {
        const storage = fakeStorage();
        rememberDraft("case-1", "doc-abc", storage);
        const g = deferredGetter();

        const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument, storage });
        probe.render({ caseId: "case-1", loaded: NOTHING, ready: true });
        await act(async () => { g.resolve("doc-abc", { error }); });

        assert.equal(storage.getItem("attorneyai.draft.case-1"), null,
                     `a definitively gone document (${error.code}) was still remembered`);
        probe.unmount();
    }
});

test("a transient failure can be retried on a later mount", async () => {
    // The point of keeping the pointer: the next mount succeeds.
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-abc", storage);

    const first = deferredGetter();
    const p1 = mountProbe({ caseId: "case-1", getDocument: first.getDocument, storage });
    p1.render({ caseId: "case-1", loaded: NOTHING, ready: true });
    await act(async () => { first.resolve("doc-abc", { error: { status: 503 } }); });
    p1.unmount();

    const second = deferredGetter();
    const p2 = mountProbe({ caseId: "case-1", getDocument: second.getDocument, storage });
    p2.render({ caseId: "case-1", loaded: NOTHING, ready: true });
    await act(async () => {
        second.resolve("doc-abc", { data: documentFor("doc-abc") });
    });

    assert.equal(p2.restores.at(-1).state.docId, "doc-abc",
                 "the draft was not recoverable after a transient failure");
    p2.unmount();
});

/* ── a loaded document must not block another case's draft (issue 2) ──────── */

test("switching case restores that case's draft even with one already open", async () => {
    // THE DEFECT MY EARLIER TEST MISSED. The hook was driven with
    // hasDocument=false throughout, so "switching cases" never reproduced the
    // real parent state: in the app a document IS loaded by then, and
    // `if (!caseId || hasDocument) return` refused to run for the new case.
    // The first case's draft stayed on screen and the second case's own draft
    // was unreachable.
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-one", storage);
    rememberDraft("case-2", "doc-two", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument, storage });
    probe.render({ caseId: "case-1", loaded: NOTHING, ready: true });
    await act(async () => { g.resolve("doc-one", { data: documentFor("doc-one") }); });

    // A document is now open, and it belongs to case-1 — the real state.
    probe.rerender({ caseId: "case-2", loaded: { hasDocument: true, caseId: "case-1" }, ready: true });
    assert.deepEqual(g.calls, ["doc-one", "doc-two"],
                     "the new case's draft was never requested");

    await act(async () => { g.resolve("doc-two", { data: documentFor("doc-two") }); });
    assert.equal(probe.restores.at(-1).state.docId, "doc-two");
    probe.unmount();
});

test("staying on the same case with its document open asks nothing", async () => {
    // The other half: once this case's document is on screen, re-rendering
    // must not refetch it.
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-one", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument, storage });
    probe.render({ caseId: "case-1", loaded: { hasDocument: true, caseId: "case-1" }, ready: true });
    probe.rerender({ caseId: "case-1", loaded: { hasDocument: true, caseId: "case-1" }, ready: true });

    assert.deepEqual(g.calls, [], "refetched a document already on screen");
    probe.unmount();
});

test("switching to a case with no draft reports it so the page can clear", async () => {
    // Otherwise case A's document stays on screen while case B is selected —
    // the same wrong-matter confusion, arrived at from the other direction.
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-one", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument, storage });
    probe.render({ caseId: "case-1", loaded: NOTHING, ready: true });
    await act(async () => { g.resolve("doc-one", { data: documentFor("doc-one") }); });

    probe.rerender({ caseId: "case-2", loaded: { hasDocument: true, caseId: "case-1" }, ready: true });

    const last = probe.restores.at(-1);
    assert.equal(last.state, null, "no signal that case-2 has nothing to show");
    assert.equal(last.forCase, "case-2");
    probe.unmount();
});

/* ── returning to a case must restore it again (issue 2) ──────────────────── */

test("A to B and back to A restores A's draft", async () => {
    // THE DEFECT. `attempted` was a permanent Set, so a case was tried once
    // per session and never again. Coming back to A found A already in the
    // set and returned early — leaving B's document on screen under A's
    // heading, which is the wrong-matter confusion this hook exists to stop.
    const storage = fakeStorage();
    rememberDraft("case-1", "doc-one", storage);
    rememberDraft("case-2", "doc-two", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: "case-1", getDocument: g.getDocument, storage });
    probe.render({ caseId: "case-1", ready: true, loaded: NOTHING });
    await act(async () => { g.resolve("doc-one", { data: documentFor("doc-one") }); });

    probe.rerender({ caseId: "case-2", ready: true,
                     loaded: { hasDocument: true, caseId: "case-1" } });
    await act(async () => { g.resolve("doc-two", { data: documentFor("doc-two") }); });

    probe.rerender({ caseId: "case-1", ready: true,
                     loaded: { hasDocument: true, caseId: "case-2" } });
    assert.deepEqual(g.calls, ["doc-one", "doc-two", "doc-one"],
                     "returning to a case did not restore it");

    await act(async () => { g.resolve("doc-one", { data: documentFor("doc-one") }); });
    assert.equal(probe.restores.at(-1).state.docId, "doc-one");
    probe.unmount();
});

/* ── standalone drafts are restorable (issue 1) ───────────────────────────── */

test("a standalone draft is restored when no case is in play", async () => {
    // THE DEFECT. `rememberDraft(null, id)` files under "no-case" and
    // `if (!caseId) return` meant nothing ever read it back. The bucket was
    // write-only: a standalone draft survived the refresh in storage and was
    // unreachable through the product.
    const storage = fakeStorage();
    rememberDraft(null, "doc-standalone", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: null, getDocument: g.getDocument, storage });
    probe.render({ caseId: null, ready: true, loaded: NOTHING });

    assert.deepEqual(g.calls, ["doc-standalone"],
                     "the no-case draft was never read back");
    await act(async () => {
        g.resolve("doc-standalone", { data: documentFor("doc-standalone") });
    });
    assert.equal(probe.restores.at(-1).state.docId, "doc-standalone");
    probe.unmount();
});

test("nothing is restored before the case list has loaded", async () => {
    // `null` meant two different things: "no case" and "we do not know yet".
    // Restoring the no-case draft during the first render would put a
    // standalone document on screen a moment before the user's real case
    // arrives and replaces it.
    const storage = fakeStorage();
    rememberDraft(null, "doc-standalone", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: null, getDocument: g.getDocument, storage });
    probe.render({ caseId: null, ready: false, loaded: NOTHING });

    assert.deepEqual(g.calls, [], "guessed before the case list had loaded");
    probe.unmount();
});

test("an open standalone document is not re-fetched", async () => {
    const storage = fakeStorage();
    rememberDraft(null, "doc-standalone", storage);
    const g = deferredGetter();

    const probe = mountProbe({ caseId: null, getDocument: g.getDocument, storage });
    probe.render({ caseId: null, ready: true,
                   loaded: { hasDocument: true, caseId: null } });

    assert.deepEqual(g.calls, [], "refetched a standalone document already open");
    probe.unmount();
});
