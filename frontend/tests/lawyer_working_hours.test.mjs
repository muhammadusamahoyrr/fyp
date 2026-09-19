/* Lawyer working hours: the editor, and the client's booking picker.
 *
 * WHAT WAS THERE BEFORE. The client's booking form offered six hardcoded
 * times — 09:00, 10:00, 11:00, 14:00, 15:00, 16:00 — identical for every
 * lawyer and every day of the week. Sunday 09:00 was offered as readily as
 * Tuesday 10:00. Those six times were not a schedule anybody had agreed to,
 * and nothing in the product could say when a lawyer actually worked.
 *
 * THE TWO FAILURES THESE TESTS GUARD.
 *
 *   * Inventing hours. A lawyer who has not published a schedule must be
 *     reported as unconfigured, never rendered as plausible office hours —
 *     that would put a real person in front of a client at a time they never
 *     agreed to.
 *
 *   * Turning a failed request into an empty state. `apiFetch` RESOLVES on
 *     failure with `{data: null, error}` rather than throwing, so an unchecked
 *     `data?.days` renders "no times available" out of a network error, and
 *     the client concludes the lawyer is busy when nobody managed to ask.
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

/* ── the lawyer's editor ──────────────────────────────────────────────────── */

test("the editor states the timezone explicitly", async () => {
    // A weekly schedule is wall-clock. A lawyer travelling, or a browser set
    // to another zone, must not have to guess whose nine o'clock this is.
    api.__respond("getMyWorkingHours", ok(schedule()));
    const ui = await mountLawyer();

    assert.match(ui.text(), /Pakistan Standard\s*Time \(PKT\)/);
    await ui.unmount();
});

test("an unconfigured lawyer is told so, not shown invented hours", async () => {
    api.__respond("getMyWorkingHours", ok(schedule({
        configured: false, working_hours: [], exceptions: [],
    })));
    const ui = await mountLawyer();

    assert.match(ui.text(), /have not set any working hours/i);
    assert.ok(!ui.text().includes("09:00 – 17:00"));
    assert.match(ui.text(), /No weekly hours yet/);
    await ui.unmount();
});

test("a failed read is not rendered as an empty schedule", async () => {
    // Rendering it as empty would invite the lawyer to overwrite hours they
    // cannot currently see.
    api.__respond("getMyWorkingHours", failed());
    const ui = await mountLawyer();

    assert.match(ui.text(), /could not load your working hours/i);
    assert.match(ui.text(), /not the same as\s*having none/i);
    // A DISTINCT label: the outcome queue on this same page has its own retry,
    // and two buttons reading "Try again" are indistinguishable to anyone
    // listening rather than looking.
    assert.ok(ui.byText("Reload working hours"));
    assert.equal(ui.byText("Try again"), undefined);
    await ui.unmount();
});

test("the saved schedule is shown back", async () => {
    api.__respond("getMyWorkingHours", ok(schedule()));
    const ui = await mountLawyer();

    const values = ui.selects().map(s => s.value);
    assert.ok(values.includes("09:00"), `no 09:00 start: ${values}`);
    assert.ok(values.includes("12:00"));
    await ui.unmount();
});

test("saving sends the whole schedule, not a patch", async () => {
    // The rule that matters most — no two intervals on one weekday may overlap
    // — is about the set as a whole.
    api.__respond("getMyWorkingHours", ok(schedule()));
    api.__respond("saveMyWorkingHours", ok(schedule()));
    const ui = await mountLawyer();

    await ui.click("Save working hours");

    const calls = api.__calls("saveMyWorkingHours");
    assert.equal(calls.length, 1);
    const sent = calls[0].args[0];
    assert.deepEqual(sent.working_hours,
                     [{ weekday: 1, start: "09:00", end: "12:00" }]);
    assert.deepEqual(sent.exceptions,
                     [{ date: "2026-10-11", reason: "family" }]);
    await ui.unmount();
});

test("a refused save shows the server's reason", async () => {
    // The message names the offending interval — it is written for the person
    // who has to fix it.
    api.__respond("getMyWorkingHours", ok(schedule()));
    api.__respond("saveMyWorkingHours",
                  { data: null, error: { message: "Tuesday: 09:00–12:00 overlaps 11:00–13:00" }, status: 422 });
    const ui = await mountLawyer();

    await ui.click("Save working hours");

    assert.match(ui.text(), /overlaps/);
    await ui.unmount();
});

test("a day off with no date is not sent as an instruction", async () => {
    api.__respond("getMyWorkingHours", ok(schedule({ exceptions: [] })));
    api.__respond("saveMyWorkingHours", ok(schedule({ exceptions: [] })));
    const ui = await mountLawyer();

    await ui.click("Add day off");
    await ui.click("Save working hours");

    const sent = api.__calls("saveMyWorkingHours")[0].args[0];
    assert.deepEqual(sent.exceptions, [], "an unfinished row was sent");
    await ui.unmount();
});

test("the editor says reasons stay private", async () => {
    api.__respond("getMyWorkingHours", ok(schedule()));
    const ui = await mountLawyer();

    assert.match(ui.text(), /never the reason/i);
    await ui.unmount();
});

test("the controls are labelled for assistive technology", async () => {
    api.__respond("getMyWorkingHours", ok(schedule()));
    const ui = await mountLawyer();

    // Scoped to the schedule editor's own fieldsets. The page carries other
    // controls this change did not add — the status filter among them — and
    // asserting about those would be reporting on somebody else's work.
    const fieldsets = [...ui.container.querySelectorAll("fieldset")];
    assert.ok(fieldsets.length >= 2, "the editor is not grouped in fieldsets");

    const legends = fieldsets.map(f => f.querySelector("legend")?.textContent.trim());
    assert.deepEqual(legends, ["Weekly hours", "Days off"]);

    const controls = fieldsets.flatMap(
        f => [...f.querySelectorAll("select, input, button")]);
    assert.ok(controls.length > 0);
    for (const el of controls) {
        const named = el.getAttribute("aria-label")
            || el.textContent.trim()
            || el.closest("label")?.textContent.trim();
        assert.ok(named, `a schedule control had no accessible name: ${el.tagName}`);
    }
    await ui.unmount();
});

test("an unenforced schedule is not described as enforced", async () => {
    api.__respond("getMyWorkingHours", ok(schedule({ enforced: false })));
    const ui = await mountLawyer();

    assert.match(ui.text(), /booking does not enforce/i);
    await ui.unmount();
});

/* ── the client's booking picker ──────────────────────────────────────────── */

async function mountClient() {
    const ModLawyers = (await import("../src/components/client/ModLawyers.jsx")).default;
    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(h(ModLawyers)); });
    await act(async () => { await new Promise(r => realSetTimeout(r, 40)); });
    return {
        container,
        text: () => container.textContent,
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

test("the hardcoded six times are gone from the source", async () => {
    // The strongest statement available about a list that must never come
    // back: it is not in the file. Every lawyer and every weekday got the same
    // six times, so Sunday 09:00 was as bookable as Tuesday 10:00.
    const { readFileSync } = await import("node:fs");
    const source = readFileSync(
        new URL("../src/components/client/ModLawyers.jsx", import.meta.url),
        "utf8");

    assert.ok(!source.includes('["09:00", "10:00", "11:00", "14:00", "15:00", "16:00"]'),
              "the hardcoded slot array is still in ModLawyers");
    assert.ok(!/const\s+isSlotBooked\s*=/.test(source),
              "the local booked-slot arithmetic is still there; the server " +
              "computes availability now");
});

test("the client picker asks the server for slots", async () => {
    const { readFileSync } = await import("node:fs");
    const source = readFileSync(
        new URL("../src/components/client/ModLawyers.jsx", import.meta.url),
        "utf8");

    assert.match(source, /getBookableSlots\(/,
                 "the booking modal does not request server-computed slots");
    assert.ok(!source.includes("getLawyerAvailability("),
              "the old booked-slots-only lookup is still wired in");
});

test("every one of the five slot states is rendered somewhere", async () => {
    // Collapsing any two of them tells the client something untrue: most of
    // all, a failed lookup shown as "no times available".
    const { readFileSync } = await import("node:fs");
    const source = readFileSync(
        new URL("../src/components/client/ModLawyers.jsx", import.meta.url),
        "utf8");

    for (const state of ["idle", "loading", "error", "unconfigured", "ready"]) {
        assert.ok(source.includes(`slotState === "${state}"`),
                  `the picker has no branch for the ${state} state`);
    }
    assert.match(source, /could not load this lawyer/i);
    assert.match(source, /not the same as having none/i);
    assert.match(source, /has not set their working hours/i);
    assert.match(source, /No times are available on this date/i);
});

test("an unenforced picker calls the time requested, not available", async () => {
    // While enforcement is off the booking path accepts times outside the
    // lawyer's hours, so calling them "available" would describe a guarantee
    // that is not switched on.
    const { readFileSync } = await import("node:fs");
    const source = readFileSync(
        new URL("../src/components/client/ModLawyers.jsx", import.meta.url),
        "utf8");

    assert.match(source, /slotsEnforced \? "Available Times \(PKT\)" : "Requested Time \(PKT\)"/);
});
