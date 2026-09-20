/* Lawyer AppointmentsPage — the time-based availability of Accept, No Show and Done.
 *
 * The backend state machine gained clock rules: a past slot cannot be
 * confirmed, a no-show cannot be recorded before the appointment starts, and a
 * consultation cannot be completed before it ends. Three controls on this page
 * map onto those rules, and before this they were offered unconditionally — so
 * each of them was a button that looked available and reliably failed.
 *
 * Two things are under test and they fail differently:
 *
 *   * WHICH side of a boundary a control is on. Pure, so it is checked at the
 *     exact instant as well as either side of it.
 *
 *   * That the control CHANGES when the boundary passes. Nothing else on this
 *     page re-renders when an appointment starts, so a correct predicate
 *     evaluated once at mount still leaves a lawyer looking at a stale button.
 *
 * The clock here is controlled, not waited on. `Date.now` is stubbed and the
 * page's own interval callback is captured and fired by hand, so "the clock
 * crossed a boundary" is an assertion rather than a thirty-second sleep — and
 * the test cannot pass merely because a real timer happened to fire.
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
                    "MutationObserver", "getComputedStyle", "localStorage",
                    "requestAnimationFrame", "cancelAnimationFrame"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

/* ── the controlled clock ─────────────────────────────────────────────────── */

const REAL_NOW = Date.now;
let fakeNow = Date.parse("2026-09-20T10:00:00Z");
/** Move the stubbed wall clock to an absolute instant. */
function setClock(iso) { fakeNow = Date.parse(iso); }
Date.now = () => fakeNow;

/* Every live interval, with its callback, so the page's ticker can be fired
 * deliberately. The existing suites track ids only; the callback is what makes
 * a boundary crossing testable without waiting for one. */
const intervals = new Map();   // id -> { fn, ms }
const clearedIds = [];
const realSetInterval = globalThis.setInterval;
const realClearInterval = globalThis.clearInterval;
const realSetTimeout = globalThis.setTimeout;
const realClearTimeout = globalThis.clearTimeout;
const liveTimeouts = new Set();

define("setInterval", (fn, ms, ...rest) => {
    const id = realSetInterval(fn, ms, ...rest);
    intervals.set(id, { fn, ms });
    return id;
});
define("clearInterval", (id) => {
    if (intervals.has(id)) clearedIds.push(id);
    intervals.delete(id);
    return realClearInterval(id);
});
define("setTimeout", (...a) => { const id = realSetTimeout(...a); liveTimeouts.add(id); return id; });
define("clearTimeout", id => { liveTimeouts.delete(id); return realClearTimeout(id); });

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { CLOCK_TICK_MS, endOf } =
    await import("../src/components/lawyer/AppointmentsPage.jsx");

const { createElement: h } = React;

/** The page's own ticker, identified by its interval period. */
function pageTicker() {
    return [...intervals.entries()].find(([, v]) => v.ms === CLOCK_TICK_MS);
}

/* ── fixtures ─────────────────────────────────────────────────────────────── */

const START = "2026-09-20T12:00:00Z";
const END = "2026-09-20T12:30:00Z";

/* An appointment as the API returns one, including the authoritative `end_at`
 * the server stores and decides completion against. */
function appointment(over = {}) {
    return {
        id: "apt-1",
        scheduled_at: START,
        end_at: END,
        duration_minutes: 30,
        client_name: "Ayesha Bibi",
        mode: "video",
        notes: "Consultation",
        status: "confirmed",
        case_id: null,
        ...over,
    };
}

async function mountAppointments(items) {
    api.__respond("listAppointments", { data: { items } });
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
    await act(async () => { await new Promise(r => realSetTimeout(r, 30)); });

    const find = (label) => [...container.querySelectorAll("button")]
        .find(b => b.textContent.trim() === label);

    return {
        container,
        find,
        /** A control's state, asserted as one object so a missing button is
         *  never mistaken for a disabled one. */
        state: (label) => {
            const btn = find(label);
            assert.ok(btn, `no button labelled ${JSON.stringify(label)}`);
            return { disabled: btn.disabled, title: btn.title };
        },
        /** Advance the clock and let the page notice, the way it will in a
         *  browser: its own interval fires and re-reads `Date.now()`. */
        tick: async (iso) => {
            setClock(iso);
            const ticker = pageTicker();
            assert.ok(ticker, "the page registered no clock interval to fire");
            await act(async () => { ticker[1].fn(); });
        },
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer" } });
    setClock("2026-09-20T10:00:00Z");
});

test.after(() => {
    for (const id of intervals.keys()) realClearInterval(id);
    for (const id of liveTimeouts) realClearTimeout(id);
    intervals.clear();
    liveTimeouts.clear();
    Date.now = REAL_NOW;
    dom.window.close();
});

/* ── Accept: a pending slot that has not passed ───────────────────────────── */

test("a pending appointment in the future can be accepted", async () => {
    setClock("2026-09-20T11:00:00Z");
    const ui = await mountAppointments([appointment({ status: "pending" })]);

    assert.deepEqual(ui.state("Accept"), { disabled: false, title: "" });
    await ui.unmount();
});

test("a pending appointment whose time has passed cannot be accepted", async () => {
    // Confirming it would only produce a confirmed row for a meeting that
    // cannot happen, which then has to be cancelled to clear it.
    setClock("2026-09-20T12:30:00Z");
    const ui = await mountAppointments([appointment({ status: "pending" })]);

    const accept = ui.state("Accept");
    assert.equal(accept.disabled, true);
    assert.match(accept.title, /already passed/);
    await ui.unmount();
});

test("rejecting a stale request stays available when accepting does not", async () => {
    // The lawyer still needs a way to clear it. Disabling both would strand the
    // request on the page permanently.
    setClock("2026-09-20T12:30:00Z");
    const ui = await mountAppointments([appointment({ status: "pending" })]);

    assert.equal(ui.state("Accept").disabled, true);
    assert.equal(ui.state("Reject").disabled, false);
    await ui.unmount();
});

/* ── No Show: from the START of the appointment ───────────────────────────── */

test("No Show is unavailable before the appointment starts", async () => {
    setClock("2026-09-20T11:59:00Z");
    const ui = await mountAppointments([appointment()]);

    const noShow = ui.state("No Show");
    assert.equal(noShow.disabled, true);
    assert.match(noShow.title, /once the appointment has started/);
    await ui.unmount();
});

test("No Show becomes available exactly at the start instant", async () => {
    // The boundary itself, not a second past it. The server's rule is
    // `now >= scheduled_at`, so the instant of the start is INSIDE it.
    setClock(START);
    const ui = await mountAppointments([appointment()]);

    assert.deepEqual(ui.state("No Show"), { disabled: false, title: "" });
    await ui.unmount();
});

test("No Show stays available after the appointment has started", async () => {
    setClock("2026-09-20T12:10:00Z");
    const ui = await mountAppointments([appointment()]);

    assert.equal(ui.state("No Show").disabled, false);
    await ui.unmount();
});

/* ── Done: from the END of the appointment ────────────────────────────────── */

test("Done is unavailable while the consultation is still running", async () => {
    // Started but not finished — the case that separates Done from No Show.
    setClock("2026-09-20T12:15:00Z");
    const ui = await mountAppointments([appointment()]);

    const done = ui.state("Done");
    assert.equal(done.disabled, true);
    assert.match(done.title, /once the consultation has ended/);
    // And the other control is already live at the same instant, which is the
    // point of evaluating them separately.
    assert.equal(ui.state("No Show").disabled, false);
    await ui.unmount();
});

test("Done becomes available exactly at the end instant", async () => {
    setClock(END);
    const ui = await mountAppointments([appointment()]);

    assert.deepEqual(ui.state("Done"), { disabled: false, title: "" });
    await ui.unmount();
});

/* ── the authoritative end ────────────────────────────────────────────────── */

test("the server's end_at decides completion, not the duration", async () => {
    // A two-hour consultation whose `duration_minutes` still says 30. The
    // server stores and enforces `end_at`, so a page that recomputed the end
    // from the duration would enable Done ninety minutes early — and every
    // click would be refused.
    setClock("2026-09-20T13:00:00Z");
    const ui = await mountAppointments([appointment({
        end_at: "2026-09-20T14:00:00Z",
        duration_minutes: 30,
    })]);

    assert.equal(ui.state("Done").disabled, true,
                 "the duration was believed over the server's own end_at");
    await ui.unmount();
});

test("a response with no end_at falls back to the duration", async () => {
    // The documented fallback: a legacy or malformed row. It is a
    // reconstruction, used only when the authoritative value is absent.
    setClock("2026-09-20T12:45:00Z");
    const ui = await mountAppointments([appointment({
        end_at: undefined, duration_minutes: 30,
    })]);

    assert.equal(ui.state("Done").disabled, false);
    await ui.unmount();
});

test("endOf prefers end_at, falls back to duration, and gives up cleanly", () => {
    assert.equal(endOf({ scheduled_at: START, end_at: END, duration_minutes: 999 })
                 .toISOString(), new Date(END).toISOString());
    assert.equal(endOf({ scheduled_at: START, duration_minutes: 30 })
                 .toISOString(), new Date(END).toISOString());
    // An unparseable authoritative value is not trusted over a usable start.
    assert.equal(endOf({ scheduled_at: START, end_at: "nonsense", duration_minutes: 30 })
                 .toISOString(), new Date(END).toISOString());
    assert.equal(endOf({ duration_minutes: 30 }), null);
    assert.equal(endOf(null), null);
});

test("an appointment with no usable time offers no enabled outcome", async () => {
    // A control whose precondition cannot be evaluated is not offered as
    // available. The title has to say why, or the button reads as broken.
    setClock("2026-09-20T13:00:00Z");
    const ui = await mountAppointments([appointment({
        scheduled_at: null, end_at: null,
    })]);

    assert.equal(ui.state("Done").disabled, true);
    assert.match(ui.state("Done").title, /no end time/);
    assert.equal(ui.state("No Show").disabled, true);
    assert.match(ui.state("No Show").title, /no scheduled time/);
    await ui.unmount();
});

/* ── the boundary crossing, without a refresh ─────────────────────────────── */

test("No Show turns on when the clock crosses the start, with no refresh", async () => {
    setClock("2026-09-20T11:59:30Z");
    const ui = await mountAppointments([appointment()]);

    assert.equal(ui.state("No Show").disabled, true, "precondition: still early");

    await ui.tick("2026-09-20T12:00:30Z");

    assert.equal(ui.state("No Show").disabled, false,
                 "the control did not update when the appointment started");
    assert.equal(ui.state("No Show").title, "");
    await ui.unmount();
});

test("Done turns on when the clock crosses the end, with no refresh", async () => {
    setClock("2026-09-20T12:29:30Z");
    const ui = await mountAppointments([appointment()]);

    assert.equal(ui.state("Done").disabled, true, "precondition: still running");

    await ui.tick("2026-09-20T12:30:30Z");

    assert.equal(ui.state("Done").disabled, false,
                 "the control did not update when the consultation ended");
    await ui.unmount();
});

test("Accept turns off when the clock crosses a pending appointment's time", async () => {
    setClock("2026-09-20T11:59:30Z");
    const ui = await mountAppointments([appointment({ status: "pending" })]);

    assert.equal(ui.state("Accept").disabled, false, "precondition: still bookable");

    await ui.tick("2026-09-20T12:00:30Z");

    assert.equal(ui.state("Accept").disabled, true,
                 "a slot that has passed was still offered for confirmation");
    await ui.unmount();
});

test("the tick does not depend on any other state changing", async () => {
    // The whole reason the clock is state: no user action, no refetch, no
    // unrelated re-render — only time passing.
    setClock("2026-09-20T11:00:00Z");
    const ui = await mountAppointments([appointment()]);
    const before = ui.state("No Show").disabled;

    await ui.tick("2026-09-20T12:05:00Z");

    assert.equal(before, true);
    assert.equal(ui.state("No Show").disabled, false);
    await ui.unmount();
});

/* ── cleanup ──────────────────────────────────────────────────────────────── */

test("the clock interval is registered once while mounted", async () => {
    const ui = await mountAppointments([appointment()]);

    const ticking = [...intervals.values()].filter(v => v.ms === CLOCK_TICK_MS);
    assert.equal(ticking.length, 1,
                 "exactly one ticker, or the page re-subscribes on every render");
    await ui.unmount();
});

test("no timer survives unmount", async () => {
    // The interval closes over component state, so one left running sets state
    // on a dead component on every tick for as long as the tab is open.
    const ui = await mountAppointments([appointment()]);
    const ticker = pageTicker();
    assert.ok(ticker, "precondition: the page started a ticker");
    const id = ticker[0];

    await ui.unmount();

    assert.ok(clearedIds.includes(id), "the clock interval was never cleared");
    assert.equal(pageTicker(), undefined, "a ticker is still registered");
});
