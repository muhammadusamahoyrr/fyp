/* LD-01: the lawyer Documents inbox, mounted for real.
 *
 * WHAT WAS WRONG. The four stat cards read `counts["Pending Review"]` and
 * friends. `counts` is null until the first queue page answers (and always on
 * the legacy queue), so the inbox threw on its very first render, before any
 * request could return. Even with counts present the keys were display labels,
 * while the server sends statuses (`submitted`, `approved`, ...), so every
 * card would have been blank.
 *
 * The existing Documents tests read this file as text, so nothing ever mounted
 * it. These do.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node",
                    "Event", "CustomEvent", "MouseEvent", "KeyboardEvent", "MutationObserver",
                    "getComputedStyle", "localStorage", "sessionStorage"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { AuthProvider } = await import("../src/context/AuthContext.jsx");
const { DocWorkflowApp } = await import("../src/components/lawyer/DocumentsPage.jsx");
const h = React.createElement;

const settle = (ms = 30) => act(async () => { await new Promise(r => setTimeout(r, ms)); });

async function mount() {
    const errors = [];
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container, {
        onUncaughtError: e => errors.push(e),
        onCaughtError: e => errors.push(e),
    });
    await act(async () => { root.render(h(AuthProvider, null, h(DocWorkflowApp))); });
    await settle();
    return {
        container, errors,
        unmount: async () => { await act(async () => root.unmount()); container.remove(); },
    };
}

// The stat cards' numbers, in order: Pending Review, Approved, Returned, Rejected.
function cardValues(container) {
    return [...container.querySelectorAll("div")]
        .filter(d => d.style.fontSize === "32px")
        .map(d => d.textContent.trim());
}

const row = (id, review_status) => ({
    id, title: `Doc ${id}`, client_name: "Client", case_id: `case${id}`,
    template_type: "plaint_civil", review_status,
});

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer", full_name: "Lawyer" } });
});

test("the inbox renders while the queue is still loading, with unknown counts as —", async () => {
    // The queue never answers during this test: the first render is the one that crashed.
    api.__respond("reviewQueueV2", () => new Promise(() => {}));
    const view = await mount();
    assert.deepEqual(view.errors, [], `the inbox threw: ${view.errors[0]}`);
    assert.deepEqual(cardValues(view.container), ["—", "—", "—", "—"]);
    await view.unmount();
});

test("V2: the cards show the server's per-status totals", async () => {
    api.__respond("reviewQueueV2", {
        data: { items: [row("a", "submitted")], next_cursor: null, status: "all",
                counts: { all: 9, submitted: 4, approved: 3, returned: 1, rejected: 0 } },
        error: null, status: 200,
    });
    const view = await mount();
    assert.deepEqual(view.errors, []);
    // A real zero is shown as 0, not as "unknown".
    assert.deepEqual(cardValues(view.container), ["4", "3", "1", "0"]);
    await view.unmount();
});

test("legacy queue (V2 off): the cards count the loaded documents", async () => {
    api.__respond("reviewQueueV2", {
        data: null, status: 404,
        error: { code: "feature_disabled", message: "not enabled" },
    });
    api.__respond("listReviewQueue", {
        data: [row("a", "submitted"), row("b", "submitted"), row("c", "approved"), row("d", "rejected")],
        error: null, status: 200,
    });
    const view = await mount();
    assert.deepEqual(view.errors, []);
    assert.deepEqual(cardValues(view.container), ["2", "1", "0", "1"]);
    await view.unmount();
});
