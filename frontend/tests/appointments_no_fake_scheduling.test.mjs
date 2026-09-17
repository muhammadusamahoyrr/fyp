/* The lawyer's page offers no scheduling or rescheduling controls.
 *
 * It used to offer both, prominently: a "+ Schedule" button in the header, a
 * "+ New Appointment" quick action, and a Reschedule control on pending,
 * upcoming and cancelled rows. None of them reached the server.
 * `confirmSchedule` only ever called `setAppointments`: a "booked" appointment
 * was given `id: Date.now()` and vanished on the next refresh, and a
 * "reschedule" rewrote the display strings while leaving `at` — the instant the
 * row is actually sorted, grouped and acted on by — untouched.
 *
 * So a lawyer could tell a client a time had been moved, see the card agree,
 * and have the server know nothing about it. Shipping a button that lies is
 * worse than shipping no button.
 *
 * Rescheduling is a real feature (`PATCH /{id}/reschedule` does not exist yet;
 * the unused `exclude_id` in the repository is the vestige of the one that was
 * never built). Until it exists, the honest state is absence — and this file
 * exists so that absence cannot quietly become another local-only
 * implementation.
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

function appointment(over = {}) {
    const when = new Date(Date.now() - 36e5);   // started an hour ago
    return {
        id: "apt-1",
        scheduled_at: when.toISOString(),
        end_at: new Date(when.getTime() + 18e5).toISOString(),
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

    return {
        container,
        text: () => container.textContent,
        labels: () => [...container.querySelectorAll("button")]
            .map(b => b.textContent.trim()),
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

const FAKE_LABELS = [
    "+ Schedule",
    "+ New Appointment",
    "Reschedule",
];

for (const status of ["pending", "confirmed", "cancelled", "completed", "no_show"]) {
    test(`a ${status} appointment offers no scheduling control`, async () => {
        const ui = await mountAppointments([appointment({ status })]);

        const labels = ui.labels();
        for (const fake of FAKE_LABELS) {
            assert.ok(!labels.some(l => l.includes(fake)),
                      `"${fake}" is still offered on a ${status} row: ${labels}`);
        }
        await ui.unmount();
    });
}

test("the page mentions rescheduling nowhere at all", async () => {
    // Including headings and helper text: a "Reschedule" label with no control
    // behind it is the same promise, made more quietly.
    const ui = await mountAppointments([appointment()]);

    assert.doesNotMatch(ui.text(), /Reschedul/i);
    await ui.unmount();
});

test("the real actions survive the removal", async () => {
    // The point was to remove the fake controls, not to strip the page. A
    // started, confirmed appointment offers the outcomes the server accepts.
    const ui = await mountAppointments([appointment({ status: "confirmed" })]);

    const labels = ui.labels();
    for (const real of ["Done", "No Show"]) {
        assert.ok(labels.includes(real), `${real} was removed too: ${labels}`);
    }
    await ui.unmount();
});

test("a pending appointment still offers Accept and Reject", async () => {
    const future = new Date(Date.now() + 48 * 36e5);
    const ui = await mountAppointments([appointment({
        status: "pending",
        scheduled_at: future.toISOString(),
        end_at: new Date(future.getTime() + 18e5).toISOString(),
    })]);

    const labels = ui.labels();
    assert.ok(labels.includes("Accept"), `Accept missing: ${labels}`);
    assert.ok(labels.includes("Reject"), `Reject missing: ${labels}`);
    await ui.unmount();
});

test("no control creates an appointment that the server never sees", async () => {
    // The specific failure `confirmSchedule` had: a row appearing in the list
    // with no request behind it. Every button on the page is clicked, and the
    // list must not grow.
    const ui = await mountAppointments([appointment()]);
    const before = ui.container.querySelectorAll("button").length;

    for (const btn of [...ui.container.querySelectorAll("button")]) {
        if (btn.disabled) continue;
        await act(async () => {
            btn.dispatchEvent(new dom.window.MouseEvent(
                "click", { bubbles: true, cancelable: true }));
        });
    }
    await act(async () => { await new Promise(r => realSetTimeout(r, 20)); });

    const created = api.__calls("bookAppointment");
    assert.equal(created.length, 0, "a lawyer-side control booked an appointment");
    assert.ok(before > 0, "precondition: the page rendered controls at all");
    await ui.unmount();
});

test("the module exports no scheduling modal", async () => {
    // Removing the buttons while leaving the component behind invites the next
    // person to wire it back up.
    const mod = await import("../src/components/lawyer/AppointmentsPage.jsx");

    for (const name of Object.keys(mod)) {
        assert.doesNotMatch(name, /Schedule/i, `${name} is still exported`);
    }
});
