/* When the case list is KNOWN, as opposed to merely empty.
 *
 * `caseData.cases` is initialised to `[]`, so `Array.isArray(cases)` was true
 * from the very first render — before `listCases` had been called, let alone
 * answered. Anything keyed off it therefore ran against "this user has no
 * cases" during the moment the app was still asking.
 *
 * That is not a hypothetical. The document screen restores a remembered draft
 * for the case in view; with `null` meaning "no case", an unready empty list
 * reads as "standalone", and a caseless draft was restored a beat before the
 * user's real case arrived and replaced it.
 *
 * An empty list and an unknown list are different facts and need different
 * signals. `casesReady` is the second one: false until the request SETTLES —
 * success or failure — because a failed load leaves the list just as unknown
 * as a pending one, and pretending otherwise is how "you have no cases" gets
 * shown to somebody who has several.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

function define(name, value) {
    Object.defineProperty(globalThis, name, {
        value, writable: true, configurable: true,
    });
}

/* A FRESH WINDOW PER TEST, closed when the test ends.
 *
 * A single module-scope JSDOM survives to process exit, and tearing the
 * process down on a live window trips a libuv assertion on Windows —
 * "!(handle->flags & UV_HANDLE_CLOSING)" — which fails the FILE intermittently
 * after every test in it has already passed. A ~40% red suite trains people to
 * ignore red, which is worse than the thing it was reporting.
 *
 * Nothing here needs state to survive between tests, so no window does either.
 */
const DOM_GLOBALS = ["window", "document", "navigator", "HTMLElement",
                     "Element", "Node", "Event", "CustomEvent",
                     "MutationObserver", "getComputedStyle", "localStorage"];

let dom = null;

function openDom() {
    dom = new JSDOM("<!doctype html><html><body></body></html>",
                    { url: "http://localhost/" });
    for (const name of DOM_GLOBALS) define(name, dom.window[name]);
    return dom;
}

function closeDom() {
    if (!dom) return;
    try { dom.window.close(); } catch { /* already gone */ }
    dom = null;
}

define("IS_REACT_ACT_ENVIRONMENT", true);

/* Timers created by the provider outlive the tree, and tearing the process down
 * on top of live handles trips a libuv assertion on Windows —
 * "!(handle->flags & UV_HANDLE_CLOSING)" — which fails the FILE after every
 * test in it has already passed. Tracked and cleared, exactly as
 * mod_documents_dom does. */
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
/* Imported ONCE, at module scope.
 *
 * These were imported inside each test. The JSX/alias loader runs on its own
 * thread, so an import issued from a test body can still be in flight when
 * `--test-force-exit` tears the process down — which trips a libuv assertion
 * ("!(handle->flags & UV_HANDLE_CLOSING)") and fails the FILE after every test
 * in it has passed. Nothing here needs a per-test module instance. */
const { CaseProvider, useCase } =
    await import("../src/components/shared/CaseContext.jsx");
const { AuthProvider } = await import("../src/context/AuthContext.jsx");

const { createElement: h } = React;

async function mountProvider() {
    const seen = [];
    function Probe() {
        const ctx = useCase();
        seen.push({
            casesReady: ctx.casesReady,
            casesError: ctx.casesError,
            count: (ctx.cases || []).length,
        });
        return null;
    }

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        // The REAL AuthProvider, signed in through the stubbed client, so the
        // case provider actually fetches rather than idling unauthenticated.
        root.render(h(AuthProvider, null, h(CaseProvider, null, h(Probe))));
    });
    return {
        seen,
        first: () => seen[0],
        latest: () => seen[seen.length - 1],
        settle: async () => { await act(async () => {
            await new Promise(r => setTimeout(r, 30));
        }); },
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

test.beforeEach(() => {
    openDom();
    api.__reset();
    // Signed in, so CaseProvider's effect actually runs.
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "u1", role: "client" } });
    // Explicitly NO socket. The generated stub would otherwise hand back a
    // plain object that CaseProvider stores as a live connection and attaches
    // an onerror handler to — a connection-shaped thing that never closes.
    api.__respond("openNotificationSocket", null);
});
test.afterEach(() => {
    for (const id of liveTimers) { realClearInterval(id); realClearTimeout(id); }
    liveTimers.clear();
    closeDom();
});

/* No `dom.window.close()` here.
 *
 * CaseProvider opens a notification WebSocket, and closing the jsdom window
 * while that handle is live trips a libuv assertion during teardown —
 * "!(handle->flags & UV_HANDLE_CLOSING)" — which fails the FILE after every
 * test in it has already passed. `--test-force-exit` ends the process anyway;
 * see tests/support/README.md. */

/* ── the first render ─────────────────────────────────────────────────────── */

test("cases are not ready on the very first render", async () => {
    // THE DEFECT. `cases` starts as [] and `Array.isArray([])` is true, so
    // every consumer believed the answer had arrived before the question was
    // asked.
    let resolveCases;
    api.__respond("listCases", () => new Promise(r => { resolveCases = r; }));

    const p = await mountProvider();
    assert.equal(p.first().casesReady, false,
                 "reported ready before listCases had answered");
    assert.equal(p.first().count, 0);

    await act(async () => { resolveCases({ data: { items: [{ _id: "c1" }] } }); });
    await p.settle();
    assert.equal(p.latest().casesReady, true);
    assert.equal(p.latest().count, 1);
    await p.unmount();
});

/* ── settling ─────────────────────────────────────────────────────────────── */

test("an empty list still settles as ready", async () => {
    // A user with no cases is a real, permanent state — not a pending one.
    api.__respond("listCases", { data: { items: [] } });

    const p = await mountProvider();
    await p.settle();
    assert.equal(p.latest().casesReady, true);
    assert.equal(p.latest().count, 0);
    assert.equal(p.latest().casesError, null);
    await p.unmount();
});

test("a failed load settles too, and says so", async () => {
    // Left un-ready forever, every consumer waits for an answer that will never
    // come. Marked ready with no error, the user is told they have no cases
    // when in fact nobody managed to look.
    api.__respond("listCases", { error: { message: "Network unreachable" } });

    const p = await mountProvider();
    await p.settle();
    assert.equal(p.latest().casesReady, true);
    assert.ok(p.latest().casesError, "a failed load left no error to report");
    assert.match(p.latest().casesError.message, /Network/);
    await p.unmount();
});

test("a retry after a failure clears the error and loads", async () => {
    api.__respond("listCases", { error: { message: "Network" } });

    const seen = [];
    let retry;
    function Probe() {
        const ctx = useCase();
        retry = ctx.reloadCases;
        seen.push({ ready: ctx.casesReady, error: ctx.casesError,
                    count: (ctx.cases || []).length });
        return null;
    }
    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(AuthProvider, null, h(CaseProvider, null, h(Probe))));
    });
    await act(async () => { await new Promise(r => setTimeout(r, 30)); });
    assert.ok(seen.at(-1).error, "the first load did not record its failure");

    api.__respond("listCases", { data: { items: [{ _id: "c1" }] } });
    await act(async () => { await retry(); });

    assert.equal(seen.at(-1).error, null, "the error survived a successful retry");
    assert.equal(seen.at(-1).count, 1);
    assert.equal(seen.at(-1).ready, true);
    await act(async () => root.unmount());
});

test("cases and readiness are exposed through useCase", async () => {
    api.__respond("listCases", { data: { items: [] } });
    const p = await mountProvider();
    await p.settle();
    for (const key of ["casesReady", "casesError"]) {
        assert.ok(key in p.latest(), `useCase() does not expose ${key}`);
    }
    await p.unmount();
});

/* ── retry, and not twice at once ─────────────────────────────────────────── */

async function mountWithRetry() {
    const seen = [];
    const api2 = {};
    function Probe() {
        const ctx = useCase();
        api2.reload = ctx.reloadCases;
        seen.push({
            ready: ctx.casesReady,
            error: ctx.casesError,
            reloading: ctx.casesReloading,
            count: (ctx.cases || []).length,
        });
        return null;
    }
    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(AuthProvider, null, h(CaseProvider, null, h(Probe))));
    });
    await act(async () => { await new Promise(r => setTimeout(r, 30)); });
    return {
        seen, api: api2,
        latest: () => seen[seen.length - 1],
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

test("a retry reports progress while it runs", async () => {
    api.__respond("listCases", { error: { message: "Network" } });
    const p = await mountWithRetry();
    assert.equal(p.latest().reloading, false);

    let release;
    api.__respond("listCases", () => new Promise(r => { release = r; }));
    let pending;
    await act(async () => { pending = p.api.reload(); });
    assert.equal(p.latest().reloading, true, "no progress signal during a retry");

    await act(async () => {
        release({ data: { items: [{ _id: "c1" }] } });
        await pending;
    });
    assert.equal(p.latest().reloading, false);
    await p.unmount();
});

test("failure then retry then success clears the error", async () => {
    api.__respond("listCases", { error: { message: "Network unreachable" } });
    const p = await mountWithRetry();
    assert.ok(p.latest().error);
    assert.equal(p.latest().count, 0);

    api.__respond("listCases", { data: { items: [{ _id: "c1" }, { _id: "c2" }] } });
    await act(async () => { await p.api.reload(); });

    assert.equal(p.latest().error, null, "the error survived a successful retry");
    assert.equal(p.latest().count, 2, "the recovered cases were not adopted");
    assert.equal(p.latest().ready, true);
    await p.unmount();
});

test("a failed retry keeps the error and does not claim zero cases", async () => {
    // Clearing the error on a failed retry, or reporting an empty list, tells
    // the user their matters are gone when the app simply could not reach them.
    api.__respond("listCases", { error: { message: "First failure" } });
    const p = await mountWithRetry();

    api.__respond("listCases", { error: { message: "Still down" } });
    await act(async () => { await p.api.reload(); });

    assert.ok(p.latest().error, "a failed retry cleared the error");
    assert.match(p.latest().error.message, /Still down/);
    assert.equal(p.latest().reloading, false);
    await p.unmount();
});

test("a failed retry does not discard cases already loaded", async () => {
    // A later refresh failing must not empty a list the user can see.
    api.__respond("listCases", { data: { items: [{ _id: "c1" }] } });
    const p = await mountWithRetry();
    assert.equal(p.latest().count, 1);

    api.__respond("listCases", { error: { message: "Down" } });
    await act(async () => { await p.api.reload(); });

    assert.equal(p.latest().count, 1, "a failed retry emptied the case list");
    assert.ok(p.latest().error);
    await p.unmount();
});

test("repeated clicks do not start concurrent retries", async () => {
    api.__respond("listCases", { error: { message: "Network" } });
    const p = await mountWithRetry();

    let release;
    let calls = 0;
    api.__respond("listCases", () => {
        calls++;
        return new Promise(r => { release = r; });
    });

    let a, b, c;
    await act(async () => {
        a = p.api.reload();
        b = p.api.reload();
        c = p.api.reload();
    });
    assert.equal(calls, 1, `an impatient user started ${calls} concurrent loads`);

    await act(async () => {
        release({ data: { items: [{ _id: "c1" }] } });
        await Promise.all([a, b, c]);
    });
    assert.equal(p.latest().count, 1);
    assert.equal(p.latest().reloading, false);
    await p.unmount();
});

test("a retry can be run again after the first one settles", async () => {
    // Suppression must be for the duration of a flight, not permanent.
    api.__respond("listCases", { error: { message: "Network" } });
    const p = await mountWithRetry();

    let calls = 0;
    api.__respond("listCases", () => { calls++; return { error: { message: "Down" } }; });
    await act(async () => { await p.api.reload(); });
    await act(async () => { await p.api.reload(); });

    assert.equal(calls, 2, "the retry button stopped working after one use");
    await p.unmount();
});
