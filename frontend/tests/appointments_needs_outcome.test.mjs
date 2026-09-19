/* The lawyer's "Needs outcome" queue.
 *
 * A CONFIRMED appointment goes nowhere on its own: only the lawyer can move it
 * to Completed or No Show, and if they never do it stays `confirmed` for ever.
 * That withholds something real — a completed consultation is what gates the
 * client's right to review the lawyer — so the absence of an action quietly
 * removes a right from somebody who is not in the room.
 *
 * TWO THINGS THIS COMPONENT MUST NOT DO, and both are tested here rather than
 * reasoned about:
 *
 *   * It must not filter the page above. The appointment list fetches fifty
 *     rows and never asks for a second page, so a local filter would show a
 *     backlog that stops exactly where that page ends — and the rows worth
 *     surfacing are the ones that fell off it. This reads its own endpoint.
 *
 *   * It must not turn a failed read into an empty queue. `apiFetch` RESOLVES
 *     on failure with `{data: null, error}` rather than throwing, so an
 *     unchecked `data?.items || []` renders a confident "nothing to do" out of
 *     a network error — telling a lawyer their record is clear when nobody
 *     managed to ask.
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
                    "Element", "Node", "Event", "CustomEvent", "MouseEvent",
                    "KeyboardEvent", "MutationObserver", "getComputedStyle",
                    "localStorage", "requestAnimationFrame",
                    "cancelAnimationFrame"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

if (!dom.window.matchMedia) {
    dom.window.matchMedia = (query) => ({
        matches: false, media: query, onchange: null,
        addEventListener() {}, removeEventListener() {},
        addListener() {}, removeListener() {},
        dispatchEvent() { return false; },
    });
}

const liveTimers = new Set();
const realSetInterval = globalThis.setInterval;
const realClearInterval = globalThis.clearInterval;
const realSetTimeout = globalThis.setTimeout;
const realClearTimeout = globalThis.clearTimeout;
define("setInterval", (...a) => { const id = realSetInterval(...a); liveTimers.add(id); return id; });
define("clearInterval", id => { liveTimers.delete(id); return realClearInterval(id); });
define("setTimeout", (...a) => { const id = realSetTimeout(...a); liveTimers.add(id); return id; });
define("clearTimeout", id => { liveTimers.delete(id); return realClearTimeout(id); });

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");

const { createElement: h } = React;

/** A queue row as the endpoint returns one. */
function pending(over = {}) {
    const ended = new Date(Date.now() - 5 * 36e5);
    return {
        id: "apt-1",
        client_name: "Ayesha Bibi",
        scheduled_at: new Date(ended.getTime() - 36e5).toISOString(),
        end_at: ended.toISOString(),
        duration_minutes: 60,
        status: "confirmed",
        mode: "video",
        schedule_version: 0,
        ...over,
    };
}

function page(items, next_cursor = null) {
    return {
        data: {
            items,
            next_cursor,
            cutoff: new Date(Date.now() - 2 * 36e5).toISOString(),
        },
        error: null,
        status: 200,
    };
}

async function mount() {
    const { AppointmentsPage } =
        await import("../src/components/lawyer/AppointmentsPage.jsx");
    const { NotifCtx } = await import("../src/components/lawyer/theme.js");

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(NotifCtx.Provider, { value: { addNotif: () => {} } },
                      h(AppointmentsPage)));
    });
    await act(async () => { await new Promise(r => realSetTimeout(r, 40)); });

    const buttons = () => [...container.querySelectorAll("button")];
    const byText = (label) => buttons().find(b => b.textContent.trim() === label);

    return {
        container,
        text: () => container.textContent,
        buttons,
        byText,
        click: async (label) => {
            const btn = byText(label);
            assert.ok(btn, `no control labelled ${label}`);
            await act(async () => {
                btn.dispatchEvent(new dom.window.MouseEvent(
                    "click", { bubbles: true, cancelable: true }));
            });
            await act(async () => { await new Promise(r => realSetTimeout(r, 30)); });
        },
        settle: async (ms = 40) => {
            await act(async () => { await new Promise(r => realSetTimeout(r, ms)); });
        },
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer" } });
    api.__respond("listAppointments", { data: { items: [] } });
    api.__respond("listCases", { data: { items: [] } });
    api.__respond("getNotifications", { data: { items: [] } });
});

test.after(() => {
    for (const id of liveTimers) { realClearInterval(id); realClearTimeout(id); }
    liveTimers.clear();
    dom.window.close();
});

/* ── the three states, kept apart ─────────────────────────────────────────── */

test("a genuine empty queue says so", async () => {
    api.__respond("listPendingOutcomes", page([]));
    const ui = await mount();

    assert.match(ui.text(), /No consultations are waiting on an outcome/);
    await ui.unmount();
});

test("a failed read is NOT reported as an empty queue", async () => {
    // THE DEFECT THIS GUARDS. `apiFetch` resolves with `{data: null, error}` on
    // failure, so an unchecked `data?.items || []` would render "nothing to do"
    // out of a network error — and a lawyer would believe their record is
    // clear because nobody managed to ask.
    api.__respond("listPendingOutcomes",
                  { data: null, error: { message: "network down" }, status: 0 });
    const ui = await mount();

    assert.ok(!ui.text().includes("No consultations are waiting on an outcome"),
              "a failed read was shown as an empty queue");
    assert.match(ui.text(), /Could not load outstanding outcomes/);
    await ui.unmount();
});

test("a failed read says it does not know, rather than guessing", async () => {
    api.__respond("listPendingOutcomes",
                  { data: null, error: { message: "boom" }, status: 500 });
    const ui = await mount();

    assert.match(ui.text(), /we do not know/i);
    assert.ok(ui.byText("Try again"), "no way to retry a failed read");
    await ui.unmount();
});

test("a failed read can be retried and then succeeds", async () => {
    let call = 0;
    api.__respond("listPendingOutcomes", () => {
        call += 1;
        return call === 1
            ? { data: null, error: { message: "down" }, status: 0 }
            : page([pending()]);
    });
    const ui = await mount();
    assert.match(ui.text(), /Could not load outstanding outcomes/);

    await ui.click("Try again");

    assert.match(ui.text(), /Ayesha Bibi/);
    await ui.unmount();
});

test("the queue is read from its own endpoint, not filtered from the list",
     async () => {
    // The appointment list fetches 50 rows and never pages. A filter over it
    // would stop exactly where that page ends — which is where this backlog
    // begins.
    api.__respond("listPendingOutcomes", page([pending()]));
    const ui = await mount();

    assert.equal(api.__calls("listPendingOutcomes").length, 1);
    assert.match(ui.text(), /Ayesha Bibi/);
    await ui.unmount();
});

/* ── recording an outcome ─────────────────────────────────────────────────── */

test("Completed goes through the guarded endpoint", async () => {
    api.__respond("listPendingOutcomes", page([pending()]));
    api.__respond("completeAppointment", { data: { status: "completed" } });
    const ui = await mount();

    await ui.click("Completed");

    const calls = api.__calls("completeAppointment");
    assert.equal(calls.length, 1, "the existing complete endpoint was not used");
    assert.equal(calls[0].args[0], "apt-1");
    await ui.unmount();
});

test("No Show goes through the guarded endpoint", async () => {
    api.__respond("listPendingOutcomes", page([pending()]));
    api.__respond("markNoShow", { data: { status: "no_show" } });
    const ui = await mount();

    await ui.click("No Show");

    const calls = api.__calls("markNoShow");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].args[0], "apt-1");
    await ui.unmount();
});

test("the queue is re-read from the server after an outcome is recorded",
     async () => {
    // Not patched locally. The server decides whether the transition happened,
    // and re-reading is the only way to see the queue it now has — including a
    // row promoted from a page this client never reached.
    let call = 0;
    api.__respond("listPendingOutcomes", () => {
        call += 1;
        return call === 1 ? page([pending()]) : page([]);
    });
    api.__respond("completeAppointment", { data: { status: "completed" } });
    const ui = await mount();

    await ui.click("Completed");

    assert.ok(api.__calls("listPendingOutcomes").length >= 2,
              "the queue was not re-read from the server");
    assert.match(ui.text(), /No consultations are waiting on an outcome/);
    await ui.unmount();
});

test("a refused outcome leaves the row in the queue", async () => {
    // The server refuses a stale row — one already dealt with in another tab.
    // Removing it locally would hide a consultation that may still need an
    // outcome.
    api.__respond("listPendingOutcomes", page([pending()]));
    api.__respond("completeAppointment",
                  { data: null, error: { message: "already completed" }, status: 409 });
    const ui = await mount();

    await ui.click("Completed");

    assert.match(ui.text(), /Ayesha Bibi/,
                 "a refused outcome removed the row anyway");
    await ui.unmount();
});

test("nothing is auto-completed by merely opening the queue", async () => {
    api.__respond("listPendingOutcomes", page([pending()]));
    const ui = await mount();

    assert.equal(api.__calls("completeAppointment").length, 0);
    assert.equal(api.__calls("markNoShow").length, 0);
    await ui.unmount();
});

/* ── paging ───────────────────────────────────────────────────────────────── */

test("more rows are reachable than one page holds", async () => {
    const cursor = {
        after_end_at: new Date(Date.now() - 4 * 36e5).toISOString(),
        after_id: "apt-25",
        cutoff: new Date(Date.now() - 2 * 36e5).toISOString(),
    };
    let call = 0;
    api.__respond("listPendingOutcomes", () => {
        call += 1;
        return call === 1
            ? page([pending({ id: "apt-1", client_name: "First Client" })], cursor)
            : page([pending({ id: "apt-2", client_name: "Second Client" })]);
    });
    const ui = await mount();

    assert.match(ui.text(), /First Client/);
    assert.ok(!ui.text().includes("Second Client"));

    await ui.click("Load more");

    assert.match(ui.text(), /Second Client/);
    assert.match(ui.text(), /First Client/, "the first page was discarded");
    await ui.unmount();
});

test("the whole cursor is sent back, not half of it", async () => {
    // The server refuses a partial cursor rather than silently restarting, so
    // sending half would turn paging into an error — or, worse, a loop over
    // page one if the server ever stopped refusing.
    const cursor = {
        after_end_at: new Date(Date.now() - 4 * 36e5).toISOString(),
        after_id: "apt-25",
        cutoff: new Date(Date.now() - 2 * 36e5).toISOString(),
    };
    let call = 0;
    api.__respond("listPendingOutcomes", () => {
        call += 1;
        return call === 1 ? page([pending()], cursor) : page([]);
    });
    const ui = await mount();

    await ui.click("Load more");

    const second = api.__calls("listPendingOutcomes")[1].args[0];
    assert.deepEqual(second.cursor, cursor);
    await ui.unmount();
});

test("no Load more control when the server says there is no next page",
     async () => {
    api.__respond("listPendingOutcomes", page([pending()]));
    const ui = await mount();

    assert.equal(ui.byText("Load more"), undefined);
    await ui.unmount();
});

test("a failed Load more keeps the rows already shown", async () => {
    const cursor = {
        after_end_at: new Date(Date.now() - 4 * 36e5).toISOString(),
        after_id: "apt-25",
        cutoff: new Date(Date.now() - 2 * 36e5).toISOString(),
    };
    let call = 0;
    api.__respond("listPendingOutcomes", () => {
        call += 1;
        return call === 1
            ? page([pending({ client_name: "Kept Client" })], cursor)
            : { data: null, error: { message: "down" }, status: 0 };
    });
    const ui = await mount();

    await ui.click("Load more");

    assert.match(ui.text(), /Kept Client/,
                 "a failed second page discarded the first");
    await ui.unmount();
});
