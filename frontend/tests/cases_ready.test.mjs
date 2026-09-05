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
                    "WebSocket"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");

const { createElement: h } = React;

async function mountProvider() {
    const { CaseProvider, useCase } =
        await import("../src/components/shared/CaseContext.jsx");
    const { AuthProvider } = await import("../src/context/AuthContext.jsx");

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
    api.__reset();
    // Signed in, so CaseProvider's effect actually runs.
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "u1", role: "client" } });
});
test.after(() => { dom.window.close(); });

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

    const { CaseProvider, useCase } =
        await import("../src/components/shared/CaseContext.jsx");
    const { AuthProvider } = await import("../src/context/AuthContext.jsx");

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
