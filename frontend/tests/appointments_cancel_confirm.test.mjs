/* Declining a request or cancelling an appointment asks first, and says
 * which it was.
 *
 * WHAT WAS WRONG. Reject (pending) and the X (confirmed) cancelled on one
 * click, with no way back and no reason for the client, although the server
 * puts a reason into the client's notice. And cancelling a CONFIRMED
 * appointment was announced as "Appointment rejected".
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
            const btn = [...container.querySelectorAll('button:not([role="tab"])')]
                .find(b => b.textContent.trim() === label);
            assert.ok(btn, `no button labelled ${label!== undefined ? JSON.stringify(label) : label}`);
            await act(async () => {
                btn.dispatchEvent(new dom.window.MouseEvent(
                    "click", { bubbles: true, cancelable: true }));
            });
            await act(async () => { await new Promise(r => setTimeout(r, 30)); });
        },
        tab: async (label) => {
            const tab = [...container.querySelectorAll('[role="tab"]')].find(b => b.textContent.trim().startsWith(label));
            assert.ok(tab, `no ${label} tab`);
            await act(async () => { tab.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
            await act(async () => { await new Promise(r => setTimeout(r, 40)); });
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



function row(over = {}) {
    return { id: "apt-1", scheduled_at: new Date(Date.now() + 3 * 864e5).toISOString(), client_name: "Ayesha Bibi",
        duration_minutes: 30, mode: "video", notes: "Consultation", status: "pending", schedule_version: 1,
        case_id: null, ...over };
}
const dialog = (ui) => ui.container.querySelector('[role="dialog"]');
const dialogButton = (ui, label) => [...dialog(ui).querySelectorAll("button")].find(b => b.textContent.trim() === label);
async function press(ui, el) {
    assert.ok(el, "control missing");
    await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true })); });
    await ui.settle(40);
}
async function type(el, value) {
    const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype, "value").set;
    await act(async () => { setter.call(el, value); el.dispatchEvent(new dom.window.Event("input", { bubbles: true })); });
}

test("Reject asks first; nothing is cancelled until the lawyer confirms", async () => {
    api.__respond("cancelAppointment", { data: { success: true }, error: null });
    const ui = await mountAppointments([row()]);
    await ui.click("Reject");
    assert.ok(dialog(ui), "no confirmation dialog");
    assert.match(dialog(ui).textContent, /Decline this request\?/);
    assert.equal(api.__calls("cancelAppointment").length, 0, "cancelled before confirming");
    await type(dialog(ui).querySelector("#cx-reason"), "In court that morning.");
    await press(ui, dialogButton(ui, "Decline request"));
    assert.deepEqual(api.__calls("cancelAppointment").map(c => c.args), [["apt-1", "In court that morning."]]);
    assert.equal(dialog(ui), null, "the dialog stayed open after success");
    assert.deepEqual(ui.badges(), ["Cancelled"]);
    await ui.unmount();
});

test("Keep closes the dialog and changes nothing", async () => {
    const ui = await mountAppointments([row()]);
    await ui.click("Reject");
    await press(ui, dialogButton(ui, "Keep request"));
    assert.equal(dialog(ui), null);
    assert.equal(api.__calls("cancelAppointment").length, 0);
    assert.deepEqual(ui.badges(), ["Pending"]);
    await ui.unmount();
});

test("cancelling a confirmed appointment is called a cancellation, not a rejection", async () => {
    api.__respond("cancelAppointment", { data: { success: true }, error: null });
    const ui = await mountAppointments([row({ status: "confirmed" })]);
    await press(ui, ui.container.querySelector('button[aria-label="Cancel appointment"]'));
    assert.match(dialog(ui).textContent, /Cancel this appointment\?/);
    await press(ui, dialogButton(ui, "Cancel appointment"));
    assert.deepEqual(api.__calls("cancelAppointment").map(c => c.args), [["apt-1", null]]);
    assert.doesNotMatch(ui.text(), /rejected/i);
    await ui.unmount();
});

test("a refused cancellation keeps the dialog open with the server's reason", async () => {
    api.__respond("cancelAppointment", { data: null, error: { message: "This appointment has already ended." }, status: 409 });
    const ui = await mountAppointments([row()]);
    await ui.click("Reject");
    await press(ui, dialogButton(ui, "Decline request"));
    assert.ok(dialog(ui), "the dialog closed on failure");
    assert.match(dialog(ui).textContent, /already ended/);
    assert.deepEqual(ui.badges(), ["Pending"]);
    await ui.unmount();
});
