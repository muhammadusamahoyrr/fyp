/* Lawyer AppointmentsPage — the no-show action and its label.
 *
 * A half-built feature. The endpoint (`PATCH /appointments/{id}/no-show`), the
 * API client function (`markNoShow`), the `NO_SHOW` status and the CLIENT-side
 * rendering ("👻 No Show" in ModTracking) all existed. The lawyer — the only
 * person who can record a no-show — had no control for it, and the lawyer's own
 * status map read:
 *
 *     no_show: "Cancelled"
 *
 * so an appointment the client failed to attend was reported to the lawyer as
 * one that had been called off. That is a different fact, and the only one of
 * the two that is the client's fault. The two sides of a single appointment
 * disagreed with each other.
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

/* An appointment as the API returns one. `status` is the BACKEND value; the
 * page maps it to a display label, and that mapping is what is under test. */
function appointment(over = {}) {
    const when = new Date(Date.now() + 36e5).toISOString();
    return {
        id: "apt-1",
        scheduled_at: when,
        client_name: "Ayesha Bibi",
        duration_minutes: 30,
        mode: "video",
        notes: "Consultation",
        status: "confirmed",
        case_id: null,
        ...over,
    };
}

async function mountAppointments(items) {
    api.__respond("listAppointments", { data: { items } });
    // Named export, not default.
    const { AppointmentsPage } =
        await import("../src/components/lawyer/AppointmentsPage.jsx");

    const { NotifCtx } = await import("../src/components/lawyer/theme.js");

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    // NotifCtx is required, not optional: `useNotif()` falls back to `{}` when
    // unprovided, so `addNotif` would be undefined and EVERY action handler on
    // this page — confirm, cancel, complete, no-show — would throw on use.
    await act(async () => {
        root.render(h(NotifCtx.Provider, { value: { addNotif: () => {} } },
                      h(AppointmentsPage)));
    });
    await act(async () => { await new Promise(r => setTimeout(r, 30)); });

    return {
        container,
        text: () => container.textContent,
        settle: async (ms = 40) => {
            await act(async () => { await new Promise(r => setTimeout(r, ms)); });
        },
        // Status badges only, and identified structurally.
        //
        // Two other things on this page render the same words: the tab strip
        // ("Cancelled", "No Show" as filters) and the stat cards ("Upcoming",
        // "Pending", "Completed" as counters). A whole-page text scan, or a
        // scan of every <span>, matches those too and would report a badge that
        // is not there — so this selects on what makes a StatusBadge unique:
        // it is the only one of the three that wraps a nested dot <span>.
        badges: () => [...container.querySelectorAll("span")]
            .filter(el => el.querySelector("span"))
            .map(el => el.textContent.trim())
            .filter(txt => ["Upcoming", "Pending", "Completed",
                            "Cancelled", "No Show"].includes(txt)),
        click: async (label) => {
            const btn = [...container.querySelectorAll("button")]
                .find(b => b.textContent.trim() === label);
            assert.ok(btn, `no button labelled ${label!== undefined ? JSON.stringify(label) : label}`);
            await act(async () => {
                btn.dispatchEvent(new dom.window.MouseEvent(
                    "click", { bubbles: true, cancelable: true }));
            });
            await act(async () => { await new Promise(r => setTimeout(r, 30)); });
        },
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer" } });
});

test.after(() => {
    for (const id of liveTimers) { realClearInterval(id); realClearTimeout(id); }
    liveTimers.clear();
    dom.window.close();
});

/* ── the label ────────────────────────────────────────────────────────────── */

test("a no-show appointment is labelled No Show, not Cancelled", async () => {
    // THE defect. `no_show` was mapped to "Cancelled" in the lawyer's view.
    const ui = await mountAppointments([appointment({ status: "no_show" })]);

    assert.deepEqual(ui.badges(), ["No Show"],
                     "a no-show was not badged as No Show");
    assert.ok(!ui.badges().includes("Cancelled"),
              "a no-show was still reported to the lawyer as a cancellation");
    await ui.unmount();
});

test("a cancelled appointment is still labelled Cancelled", async () => {
    // The other half: fixing one label must not swallow the other.
    const ui = await mountAppointments([appointment({ status: "cancelled" })]);

    assert.deepEqual(ui.badges(), ["Cancelled"]);
    await ui.unmount();
});

test("the two statuses are distinguishable side by side", async () => {
    const ui = await mountAppointments([
        appointment({ id: "a1", status: "no_show", client_name: "Absent Client" }),
        appointment({ id: "a2", status: "cancelled", client_name: "Called Off" }),
    ]);

    assert.deepEqual(ui.badges().sort(), ["Cancelled", "No Show"]);
    await ui.unmount();
});

/* ── the action ───────────────────────────────────────────────────────────── */

test("a confirmed appointment offers the No Show action", async () => {
    const ui = await mountAppointments([appointment({ status: "confirmed" })]);

    const labels = [...ui.container.querySelectorAll("button")]
        .map(b => b.textContent.trim());
    assert.ok(labels.includes("No Show"),
              `no No Show control on a confirmed appointment; buttons: ${labels}`);
    await ui.unmount();
});

test("marking a no-show calls the existing endpoint and updates the row",
     async () => {
    api.__respond("markNoShow", { data: { success: true } });
    const ui = await mountAppointments([appointment({ status: "confirmed" })]);

    assert.deepEqual(ui.badges(), ["Upcoming"],
                     "the row did not start as a confirmed appointment");

    await ui.click("No Show");

    // The EXISTING API function, with the appointment id — no new endpoint.
    const calls = api.__calls("markNoShow");
    assert.equal(calls.length, 1, "markNoShow was not called exactly once");
    assert.deepEqual(calls[0].args, ["apt-1"]);

    // And the row now reads as a no-show rather than staying Upcoming.
    assert.deepEqual(ui.badges(), ["No Show"]);
    await ui.unmount();
});

test("a refused no-show leaves the appointment unchanged", async () => {
    // The server allows this only on a CONFIRMED appointment, so a stale card
    // is refused. The row must not optimistically flip on a failure.
    api.__respond("markNoShow",
                  { data: null, error: { message: "Only confirmed appointments can be marked as no-show" } });
    const ui = await mountAppointments([appointment({ status: "confirmed" })]);

    await ui.click("No Show");

    assert.equal(api.__calls("markNoShow").length, 1);
    assert.deepEqual(ui.badges(), ["Upcoming"],
                     "the row changed despite the server refusing");
    await ui.unmount();
});

test("a completed appointment offers no No Show action", async () => {
    // The server accepts a no-show only from `confirmed`, so offering it
    // elsewhere would present an action the API would refuse.
    const ui = await mountAppointments([appointment({ status: "completed" })]);

    const labels = [...ui.container.querySelectorAll("button")]
        .map(b => b.textContent.trim());
    assert.ok(!labels.includes("No Show"),
              `No Show offered on a completed appointment; buttons: ${labels}`);
    await ui.unmount();
});
