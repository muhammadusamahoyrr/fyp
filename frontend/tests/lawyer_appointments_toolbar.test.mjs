/* Appointments toolbar and the "Set working hours" drawer.
 *
 * WHAT CHANGED. The toolbar had Search, a Status dropdown (duplicating the
 * status tabs above the list) and the List/Calendar toggle; the working-hours
 * editor sat inline in the middle of the page. Now: the view toggle in
 * the middle, and a "Set working hours" button that opens the editor in a
 * right-hand drawer, laid out per weekday with an Open/Closed toggle.
 * The saved payload is unchanged.
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

function ok(data) { return { data, error: null, status: 200 }; }
function failed(message = "network down") {
    return { data: null, error: { message }, status: 0 };
}

function schedule(over = {}) {
    return {
        lawyer_id: "l1",
        configured: true,
        enforced: false,
        timezone: "Asia/Karachi",
        working_hours: [{ weekday: 1, start: "09:00", end: "12:00" }],
        exceptions: [{ date: "2026-10-11", reason: "family" }],
        updated_at: "2026-10-01T00:00:00Z",
        ...over,
    };
}

async function mountLawyer() {
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

    // The editor lives in the "Set working hours" drawer, not inline on the page.
    const opener = buttons().find(b => b.closest('section[aria-label="Working hours"]') && /^(Edit hours|Set up)/.test(b.textContent.trim()));
    assert.ok(opener, "no Set working hours button");
    await act(async () => {
        opener.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    await act(async () => { await new Promise(r => realSetTimeout(r, 40)); });

    return {
        container,
        text: () => container.textContent,
        byText,
        selects: () => [...container.querySelectorAll("select")],
        click: async (label) => {
            const btn = byText(label);
            assert.ok(btn, `no control labelled ${label}`);
            await act(async () => {
                btn.dispatchEvent(new dom.window.MouseEvent(
                    "click", { bubbles: true, cancelable: true }));
            });
            await act(async () => { await new Promise(r => realSetTimeout(r, 30)); });
        },
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer" } });
    api.__respond("listAppointments", { data: { items: [] } });
    api.__respond("listPendingOutcomes",
                  ok({ items: [], next_cursor: null, cutoff: "2026-10-01T00:00:00Z" }));
    api.__respond("listCases", { data: { items: [] } });
    api.__respond("getNotifications", { data: { items: [] } });
    api.__respond("searchLawyers", { data: { items: [] } });
    api.__respond("listEngagements", { data: { items: [] } });
});

test.after(() => {
    for (const id of liveTimers) { realClearInterval(id); realClearTimeout(id); }
    liveTimers.clear();
    dom.window.close();
});


const opener = (ui) => [...ui.container.querySelectorAll("button")]
    .find(b => b.closest('section[aria-label="Working hours"]') && /^(Edit hours|Set up)/.test(b.textContent.trim()));
const dialog = (ui) => ui.container.querySelector('[role="dialog"][aria-label="Working hours"]');
async function press(el) {
    await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true })); });
    await act(async () => { await new Promise(r => realSetTimeout(r, 40)); });
}
// mountLawyer (shared harness) opens the drawer; close it to see the page itself.
async function mountPageClosed() {
    const ui = await mountLawyer();
    await press([...dialog(ui).querySelectorAll("button")].find(b => b.textContent.trim() === "Done"));
    return ui;
}

test("the toolbar has the view toggle and a working-hours button, and no Status dropdown", async () => {
    api.__respond("getMyWorkingHours", ok(schedule()));
    const ui = await mountPageClosed();
    assert.equal(dialog(ui), null, "the drawer did not close");
    assert.doesNotMatch(ui.text(), /Status:/);
    assert.equal(ui.container.querySelectorAll("select").length, 0, "a dropdown is still on the page");
    const labels = [...ui.container.querySelectorAll("button")].map(b => b.textContent.trim());
    assert.ok(labels.some(l => l.startsWith("List")) && labels.some(l => l.startsWith("Calendar")));
    assert.ok(opener(ui), "no Set working hours button");
    // The editor is not inline any more.
    assert.doesNotMatch(ui.text(), /Weekly hours|Save working hours/);
    await ui.unmount();
});

test("the drawer opens from the button and closes on Escape", async () => {
    api.__respond("getMyWorkingHours", ok(schedule()));
    const ui = await mountPageClosed();
    await press(opener(ui));
    assert.ok(dialog(ui), "the drawer did not open");
    await act(async () => { dom.window.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Escape" })); });
    assert.equal(dialog(ui), null, "Escape did not close the drawer");
    await ui.unmount();
});

test("each weekday has an Open/Closed toggle, and toggling changes what is saved", async () => {
    // Saved: Tuesday 09:00-12:00 only.
    api.__respond("getMyWorkingHours", ok(schedule()));
    api.__respond("saveMyWorkingHours", ok(schedule()));
    const ui = await mountLawyer();
    const d = dialog(ui);
    const toggle = (day) => d.querySelector(`button[aria-label^="${day}:"]`);
    assert.equal(toggle("Tuesday").getAttribute("aria-pressed"), "true");
    assert.equal(toggle("Monday").getAttribute("aria-pressed"), "false");
    // Times read as 12-hour labels; the saved values stay HH:MM.
    const tueStart = d.querySelector('select[aria-label="Tuesday start time 1"]');
    assert.equal(tueStart.value, "09:00");
    assert.equal(tueStart.selectedOptions[0].textContent, "9:00 AM");

    await press(toggle("Monday"));      // open Monday: 09:00-17:00
    await press(toggle("Tuesday"));     // close Tuesday
    await press([...d.querySelectorAll("button")].find(b => b.textContent.trim() === "Save hours"));
    const sent = api.__calls("saveMyWorkingHours")[0].args[0];
    assert.deepEqual(sent.working_hours, [{ weekday: 0, start: "09:00", end: "17:00" }]);
    await ui.unmount();
});

test("a split shift starts after the day's hours instead of overlapping them", async () => {
    // Saved: Tuesday 09:00-12:00. The old default (13:00-17:00) overlapped a
    // 09:00-17:00 day, which the server rejects.
    api.__respond("getMyWorkingHours", ok(schedule({
        working_hours: [{ weekday: 1, start: "09:00", end: "17:00" },
                        { weekday: 2, start: "20:00", end: "23:30" }],
    })));
    api.__respond("saveMyWorkingHours", ok(schedule()));
    const ui = await mountLawyer();
    const d = dialog(ui);
    await press(d.querySelector('button[aria-label="Add more hours on Tuesday"]'));
    assert.equal(d.querySelector('select[aria-label="Tuesday start time 2"]').value, "18:00");
    assert.equal(d.querySelector('select[aria-label="Tuesday end time 2"]').value, "20:00");
    // Wednesday already runs to the last half hour: no room for another shift.
    assert.equal(d.querySelector('button[aria-label="Add more hours on Wednesday"]').disabled, true);

    await press([...d.querySelectorAll("button")].find(b => b.textContent.trim() === "Save hours"));
    const sent = api.__calls("saveMyWorkingHours")[0].args[0];
    assert.deepEqual(sent.working_hours.filter(r => r.weekday === 1), [
        { weekday: 1, start: "09:00", end: "17:00" },
        { weekday: 1, start: "18:00", end: "20:00" },
    ]);
    await ui.unmount();
});
