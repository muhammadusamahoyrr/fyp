/* Appointments: the month calendar, and no search box.
 *
 * WHAT WAS WRONG. The Calendar view was a fixed week from 9:00 to 18:00 that
 * nothing in could be clicked: no way to another week, an evening appointment
 * silently missing, and it drew from the LIST's rows, so it showed only the
 * current tab's first page. Now it is a month grid with previous / next /
 * today, every appointment from every page and status that takes place, and a
 * day click opens that day's agenda. A lawyer cannot create appointments
 * (POST /appointments is client-only), so a day click never offers to.
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

const { pktToday } = await import("../src/lib/bookingTime.js");
const TODAY = pktToday();
const MONTH = TODAY.slice(0, 7);

function row(id, hhmm, status = "pending", over = {}) {
    return {
        id, scheduled_at: `${TODAY}T${hhmm}:00+05:00`, duration_minutes: 60,
        status, mode: "video", client_name: `Client ${id}`, notes: `Matter ${id}`,
        ...over,
    };
}

async function settle(ms = 50) {
    await act(async () => { await new Promise(r => realSetTimeout(r, ms)); });
}
function dayLabel(key) {
    return new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" })
        .format(new Date(`${key}T12:00:00Z`));
}
function monthLabel(m) {
    return new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric", timeZone: "UTC" })
        .format(new Date(`${m}-01T12:00:00Z`));
}

async function mountCalendar() {
    const { AppointmentsPage } = await import("../src/components/lawyer/AppointmentsPage.jsx");
    const { NotifCtx } = await import("../src/components/lawyer/theme.js");
    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(NotifCtx.Provider, { value: { addNotif: () => {} } }, h(AppointmentsPage)));
    });
    await settle();
    return {
        container,
        text: () => container.textContent,
        button: (pred) => [...container.querySelectorAll("button")].find(pred),
        day: (key) => container.querySelector(`button[aria-label^="${dayLabel(key)},"]`),
        press: async (el) => {
            assert.ok(el, "control not found");
            await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true })); });
            await settle();
        },
        unmount: async () => { await act(async () => root.unmount()); container.remove(); },
    };
}
async function openCalendar(ui) {
    await ui.press(ui.button(b => b.textContent.trim().startsWith("Calendar")));
    await settle(80);
}

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer" } });
    api.__respond("listAppointments", ok({ items: [], total: 0, pages: 1 }));
    api.__respond("listPendingOutcomes", ok({ items: [], next_cursor: null, cutoff: "2026-10-01T00:00:00Z" }));
    api.__respond("getMyWorkingHours", ok({ configured: false, enforced: false, working_hours: [], exceptions: [] }));
    api.__respond("listLawyerEvents", ok([]));
});

test.after(() => {
    for (const id of liveTimers) { realClearInterval(id); realClearTimeout(id); }
    liveTimers.clear();
    dom.window.close();
});

test("there is no search box; the only input is the go-to-date picker", async () => {
    const ui = await mountCalendar();
    const inputs = [...ui.container.querySelectorAll("input")];
    assert.deepEqual(inputs.map(i => i.getAttribute("aria-label")), ["Go to date"]);
    await ui.unmount();
});

test("the calendar reads every page of every status, not the list's page", async () => {
    api.__respond("listAppointments", (args = {}) => {
        if (args.page_size !== 50) return ok({ items: [], total: 0, pages: 1 });
        return args.page === 1
            ? ok({ items: [row("a", "11:00")], total: 2, pages: 2 })
            : ok({ items: [row("b", "18:00", "confirmed")], total: 2, pages: 2 });
    });
    const ui = await mountCalendar();
    await openCalendar(ui);
    const calls = api.__calls("listAppointments").map(c => c.args[0] || {}).filter(a => a.page_size === 50);
    // Read on mount (for the overview) and again on opening the calendar;
    // each read covers every page and every status.
    assert.ok(calls.length >= 2 && calls.length % 2 === 0, JSON.stringify(calls));
    assert.deepEqual(calls.slice(-2).map(a => [a.page, a.status]), [[1, undefined], [2, undefined]]);
    // Both land on today, including the 18:00 one the old 9-18 grid dropped.
    assert.match(ui.day(TODAY).getAttribute("aria-label"), /, 2 entries$/);
    assert.match(ui.day(TODAY).textContent, /6:00 PM/);
    await ui.unmount();
});

test("appointments that did not take place are left off the calendar", async () => {
    api.__respond("listAppointments", ok({ items: [
        row("c", "10:00", "cancelled"), row("n", "12:00", "no_show"),
        row("e", "13:00", "expired"), row("k", "14:00", "confirmed"),
    ], total: 4, pages: 1 }));
    const ui = await mountCalendar();
    await openCalendar(ui);
    assert.match(ui.day(TODAY).getAttribute("aria-label"), /, 1 entry$/);
    await ui.unmount();
});

test("clicking a day shows its agenda; it never offers to create one", async (t) => {
    // "Now" is pinned to 10:30 PKT today: an appointment that has ended no
    // longer offers Join, so with the real clock this test failed every
    // afternoon. The calendar's day (TODAY) is unaffected.
    const pinned = new Date(`${TODAY}T10:30:00+05:00`).getTime();
    t.mock.method(Date, "now", () => pinned);
    api.__respond("listAppointments", ok({ items: [row("a", "11:00", "confirmed")], total: 1, pages: 1 }));
    const ui = await mountCalendar();
    await openCalendar(ui);
    // Today is selected to begin with.
    assert.match(ui.text(), new RegExp(dayLabel(TODAY)));
    assert.match(ui.text(), /Client a/);
    assert.match(ui.text(), /Matter a/);
    assert.ok(ui.button(b => b.textContent.trim() === "Join call"),
              "a confirmed video call can be joined from the agenda");

    const other = `${MONTH}-${TODAY.endsWith("-15") ? "16" : "15"}`;
    await ui.press(ui.day(other));
    assert.equal(ui.day(other).getAttribute("aria-pressed"), "true");
    assert.match(ui.text(), new RegExp(dayLabel(other)));
    assert.match(ui.text(), /Nothing on this day\./);
    assert.doesNotMatch(ui.text(), /New appointment|Book appointment/i);
    await ui.unmount();
});

test("previous, next and today move the month", async () => {
    const { shiftMonth } = await import("../src/lib/bookingTime.js");
    const ui = await mountCalendar();
    await openCalendar(ui);
    assert.match(ui.text(), new RegExp(monthLabel(MONTH)));
    await ui.press(ui.container.querySelector('button[aria-label="Next month"]'));
    assert.match(ui.text(), new RegExp(monthLabel(shiftMonth(MONTH, 1))));
    await ui.press(ui.container.querySelector('button[aria-label="Previous month"]'));
    await ui.press(ui.container.querySelector('button[aria-label="Previous month"]'));
    assert.match(ui.text(), new RegExp(monthLabel(shiftMonth(MONTH, -1))));
    await ui.press(ui.button(b => b.textContent.trim() === "Today"));
    assert.match(ui.text(), new RegExp(monthLabel(MONTH)));
    await ui.unmount();
});

test("a failed calendar read says so and can be retried", async () => {
    let fail = true;
    api.__respond("listAppointments", (args = {}) => (args.page_size === 50 && fail)
        ? { data: null, error: { message: "down" }, status: 0 }
        : ok({ items: [row("a", "11:00")], total: 1, pages: 1 }));
    const ui = await mountCalendar();
    await openCalendar(ui);
    assert.match(ui.text(), /Could not load appointments for the calendar/);
    fail = false;
    await ui.press(ui.button(b => b.textContent.trim() === "Retry"));
    await settle(80);
    assert.doesNotMatch(ui.text(), /Could not load appointments for the calendar/);
    assert.match(ui.day(TODAY).getAttribute("aria-label"), /, 1 entry$/);
    await ui.unmount();
});

/* ── the lawyer's own meetings and events ─────────────────────────────────── */

function diary(id, hhmm, over = {}) {
    const starts = new Date(`${TODAY}T${hhmm}:00+05:00`);
    return {
        id, kind: "meeting", title: `Diary ${id}`, starts_at: starts.toISOString(),
        ends_at: new Date(starts.getTime() + 3600000).toISOString(), duration_minutes: 60,
        client_name: "Mr. Khan", location: "Chambers", priority: "high", notes: "Bring the deed",
        created_at: starts.toISOString(), ...over,
    };
}

async function type(el, value) {
    const proto = el.tagName === "TEXTAREA" ? dom.window.HTMLTextAreaElement.prototype
        : el.tagName === "SELECT" ? dom.window.HTMLSelectElement.prototype
        : dom.window.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    await act(async () => {
        el.dispatchEvent(new dom.window.Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
    });
}

test("diary entries show beside appointments, for the days on the grid", async () => {
    api.__respond("listAppointments", ok({ items: [row("a", "11:00", "confirmed")], total: 1, pages: 1 }));
    api.__respond("listLawyerEvents", ok([diary("m", "16:30")]));
    const ui = await mountCalendar();
    await openCalendar(ui);
    const { start, end } = api.__calls("listLawyerEvents").at(-1).args[0];
    assert.match(start, /T00:00:00\+05:00$/);
    assert.ok(new Date(end) - new Date(start) <= 62 * 86400000, "asked for more than the server allows");
    assert.match(ui.day(TODAY).getAttribute("aria-label"), /, 2 entries$/);
    assert.match(ui.text(), /Diary m/);
    assert.match(ui.text(), /With Mr\. Khan/);
    assert.match(ui.text(), /High priority/);
    await ui.unmount();
});

test("Create > Meeting saves a private diary entry and shows it", async () => {
    let saved = null;
    api.__respond("createLawyerEvent", (body) => { saved = body; return ok(diary("new", "10:00", { title: body.title })); });
    const ui = await mountCalendar();
    await ui.press(ui.button(b => b.getAttribute("aria-haspopup") === "menu"));
    await ui.press(ui.button(b => b.getAttribute("role") === "menuitem" && b.textContent.startsWith("Meeting")));
    const dialog = dom.window.document.querySelector('[role="dialog"][aria-label="New meeting"]');
    assert.ok(dialog, "the meeting form did not open");

    // Nothing is sent without a title.
    await ui.press([...dialog.querySelectorAll("button")].find(b => b.textContent === "Create meeting"));
    assert.equal(api.__calls("createLawyerEvent").length, 0);
    assert.match(dialog.textContent, /Give it a title/);

    await type(dialog.querySelector("#de-title"), "  Case discussion  ");
    await type(dialog.querySelector("#de-with"), "Mr. Khan");
    await type(dialog.querySelector("#de-date"), TODAY);
    await type(dialog.querySelector("#de-time"), "15:30");
    await type(dialog.querySelector("#de-dur"), "90");
    await ui.press([...dialog.querySelectorAll('[role="radio"]')].find(b => b.textContent === "High"));
    await ui.press([...dialog.querySelectorAll("button")].find(b => b.textContent === "Create meeting"));

    assert.deepEqual(saved, {
        kind: "meeting", title: "Case discussion", starts_at: new Date(`${TODAY}T15:30:00+05:00`).toISOString(),
        duration_minutes: 90, client_name: "Mr. Khan", location: null, priority: "high", notes: null,
    });
    assert.equal(dom.window.document.querySelector('[role="dialog"][aria-label="New meeting"]'), null, "the form stayed open");
    // Saved, so the calendar opens on that day and re-reads the diary.
    assert.ok(ui.day(TODAY), "the calendar did not open");
    assert.ok(api.__calls("listLawyerEvents").length >= 1);
    await ui.unmount();
});

test("a refused save keeps the form open and says why", async () => {
    api.__respond("createLawyerEvent", { data: null, error: { message: "Ask for at most 62 days" }, status: 422 });
    const ui = await mountCalendar();
    await ui.press(ui.button(b => b.getAttribute("aria-haspopup") === "menu"));
    await ui.press(ui.button(b => b.getAttribute("role") === "menuitem" && b.textContent.startsWith("Event")));
    const dialog = dom.window.document.querySelector('[role="dialog"][aria-label="New event"]');
    await type(dialog.querySelector("#de-title"), "Bar council seminar");
    await ui.press([...dialog.querySelectorAll("button")].find(b => b.textContent === "Create event"));
    assert.equal(api.__calls("createLawyerEvent")[0].args[0].kind, "event");
    assert.ok(dom.window.document.querySelector('[role="dialog"][aria-label="New event"]'), "the form closed on a failure");
    assert.match(dialog.textContent, /Ask for at most 62 days/);
    await ui.unmount();
});

test("a diary entry is deleted only after confirming", async () => {
    api.__respond("listLawyerEvents", ok([diary("m", "16:30")]));
    api.__respond("deleteLawyerEvent", ok({ success: true }));
    const ui = await mountCalendar();
    await openCalendar(ui);
    await ui.press(ui.button(b => b.getAttribute("aria-label") === "Delete Diary m"));
    assert.equal(api.__calls("deleteLawyerEvent").length, 0, "deleted without confirming");
    await ui.press(ui.button(b => b.textContent === "Confirm delete"));
    assert.deepEqual(api.__calls("deleteLawyerEvent").map(c => c.args[0]), ["m"]);
    assert.doesNotMatch(ui.text(), /Diary m/);
    await ui.unmount();
});

test("the date picker jumps the calendar to that day", async () => {
    const { shiftMonth } = await import("../src/lib/bookingTime.js");
    const target = `${shiftMonth(MONTH, 2)}-10`;
    const ui = await mountCalendar();
    await type(ui.container.querySelector('input[aria-label="Go to date"]'), target);
    await settle(80);
    assert.equal(ui.day(target)?.getAttribute("aria-pressed"), "true", "the picked day is not selected");
    assert.match(ui.text(), new RegExp(monthLabel(shiftMonth(MONTH, 2))));
    await ui.unmount();
});

test("Export writes the month as CSV, formula-safe, with appointments and diary", async () => {
    api.__respond("listAppointments", ok({ items: [row("a", "11:00", "confirmed", { client_name: "=HYPERLINK(1)" })], total: 1, pages: 1 }));
    api.__respond("listLawyerEvents", ok([diary("m", "16:30", { title: 'Say "hi"' })]));
    let blob = null;
    const realCreate = URL.createObjectURL;
    const realRevoke = URL.revokeObjectURL;
    URL.createObjectURL = (b) => { blob = b; return "blob:test"; };
    URL.revokeObjectURL = () => {};
    try {
        const ui = await mountCalendar();
        await ui.press(ui.button(b => b.textContent.includes("Export Excel")));
        await settle(80);
        assert.ok(blob, "nothing was downloaded");
        const csv = await blob.text();
        const lines = csv.replace(/^﻿/, "").trim().split("\r\n");
        assert.match(lines[0], /^"Date","Start \(PKT\)"/);
        assert.equal(lines.length, 3, csv);
        assert.match(lines[1], /"Appointment"/);
        assert.match(lines[1], /"'=HYPERLINK\(1\)"/, "a formula was not neutralised");
        assert.match(lines[2], /"Meeting","Say ""hi"""/);
        await ui.unmount();
    } finally {
        URL.createObjectURL = realCreate;
        URL.revokeObjectURL = realRevoke;
    }
});

/* ── review fixes ─────────────────────────────────────────────────────────── */

test("a half-typed year in the date picker does nothing", async () => {
    const ui = await mountCalendar();
    const before = api.__calls("listLawyerEvents").length;
    // The browser reports these as complete dates while "2026" is typed.
    for (const partial of ["0002-10-06", "0020-10-06", "0202-10-06"]) {
        await type(ui.container.querySelector('input[aria-label="Go to date"]'), partial);
    }
    await settle(60);
    assert.equal(api.__calls("listLawyerEvents").length, before, "a nonsense month was requested");
    assert.equal(ui.day(TODAY), null, "the view switched to the calendar on a half-typed year");
    await ui.unmount();
});

test("+ Add on a past day keeps that day", async () => {
    const { shiftMonth } = await import("../src/lib/bookingTime.js");
    const past = `${shiftMonth(MONTH, -1)}-10`;
    const ui = await mountCalendar();
    await type(ui.container.querySelector('input[aria-label="Go to date"]'), past);
    await settle(60);
    await ui.press(ui.button(b => (b.getAttribute("aria-label") || "").startsWith("Add to ")));
    const dialog = dom.window.document.querySelector('[role="dialog"][aria-label="New meeting"]');
    assert.equal(dialog.querySelector("#de-date").value, past);
    await ui.unmount();
});

test("an entry that crosses midnight says the end is the next day", async () => {
    api.__respond("listLawyerEvents", ok([diary("late", "23:00", {
        ends_at: new Date(new Date(`${TODAY}T23:00:00+05:00`).getTime() + 2 * 3600000).toISOString(),
        duration_minutes: 120,
    })]));
    const ui = await mountCalendar();
    await openCalendar(ui);
    assert.match(ui.text(), /11:00 PM – 1:00 AM \(next day\)/);
    await ui.unmount();
});

test("saving an entry re-reads the diary, not every appointment", async () => {
    api.__respond("createLawyerEvent", (body) => ok(diary("new", "10:00", { title: body.title })));
    const ui = await mountCalendar();
    await openCalendar(ui);
    const fullReads = () => api.__calls("listAppointments").filter(c => (c.args[0] || {}).page_size === 50).length;
    const before = fullReads();
    const diaryBefore = api.__calls("listLawyerEvents").length;
    await ui.press(ui.button(b => (b.getAttribute("aria-label") || "").startsWith("Add to ")));
    const dialog = dom.window.document.querySelector('[role="dialog"][aria-label="New meeting"]');
    await type(dialog.querySelector("#de-title"), "Call back");
    await ui.press([...dialog.querySelectorAll("button")].find(b => b.textContent === "Create meeting"));
    await settle(60);
    assert.equal(fullReads(), before, "all appointments were downloaded again");
    assert.ok(api.__calls("listLawyerEvents").length > diaryBefore, "the diary was not re-read");
    await ui.unmount();
});

test("the form takes keyboard focus and gives it back on close", async () => {
    const ui = await mountCalendar();
    const opener = ui.button(b => b.getAttribute("aria-haspopup") === "menu");
    opener.focus();
    await ui.press(opener);
    const item = ui.button(b => b.getAttribute("role") === "menuitem" && b.textContent.startsWith("Meeting"));
    item.focus();
    await ui.press(item);
    const dialog = dom.window.document.querySelector('[role="dialog"][aria-label="New meeting"]');
    assert.ok(dialog.contains(dom.window.document.activeElement), "focus stayed behind the dialog");
    await ui.press([...dialog.querySelectorAll("button")].find(b => b.textContent === "Cancel"));
    const back = dom.window.document.activeElement;
    // Booleans, not the elements: a failing deepEqual on jsdom nodes prints the whole DOM.
    assert.ok(back === opener, `focus was not given back to + Create (it is on <${back?.tagName}> ${back?.textContent?.slice(0, 30)})`);
    await ui.unmount();
});

/* ── overview cards ───────────────────────────────────────────────────────── */

function future(daysAhead, hhmm) {
    const d = new Date(`${TODAY}T12:00:00Z`);
    d.setUTCDate(d.getUTCDate() + daysAhead);
    return `${d.toISOString().slice(0, 10)}T${hhmm}:00+05:00`;
}

test("the pending card shows the server's total, the next requests and who sent them", async () => {
    api.__respond("listAppointments", (args = {}) => {
        if (args.status === "pending" && args.page_size === 1) return ok({ items: [], total: 4, pages: 4 });
        return ok({ items: [
            row("p1", "10:00", "pending", { scheduled_at: future(2, "11:00"), notes: "Tenancy dispute", client_name: "Ali Raza", schedule_version: 1 }),
            row("p2", "10:00", "pending", { scheduled_at: future(3, "15:00"), notes: "Bail advice", client_name: "Sara Khan", schedule_version: 1 }),
            row("p3", "10:00", "pending", { scheduled_at: future(4, "09:00"), notes: "Will drafting", client_name: "Usman Ali", schedule_version: 1 }),
            row("p4", "10:00", "pending", { scheduled_at: future(5, "09:00"), notes: "Family settlement", client_name: "Hina Shah", schedule_version: 1 }),
        ], total: 4, pages: 1 });
    });
    const ui = await mountCalendar();
    const card = ui.container.querySelector('[data-stat="pending"]');
    assert.equal(card.querySelector("[data-value]").textContent, "4");
    assert.match(card.textContent, /requests waiting/);
    assert.match(card.textContent, /Tenancy dispute/);
    assert.match(card.textContent, /Bail advice/);
    assert.match(card.textContent, /Will drafting/);
    assert.match(card.textContent, /Ali Raza · Video Call/, "the client and call type are not shown");
    assert.doesNotMatch(card.textContent, /Family settlement/, "more than three requests were listed");
    assert.match(card.textContent, /AR.*SK.*\+2/);
    await ui.unmount();
});

test("Accept all asks first, then confirms only requests whose time has not passed", async () => {
    api.__respond("listAppointments", ok({ items: [
        row("ok1", "10:00", "pending", { scheduled_at: future(2, "11:00"), schedule_version: 4 }),
        row("ok2", "10:00", "pending", { scheduled_at: future(3, "11:00"), schedule_version: 7 }),
        row("gone", "10:00", "pending", { scheduled_at: future(-2, "11:00"), schedule_version: 1 }),
    ], total: 3, pages: 1 }));
    api.__respond("confirmAppointment", ok({ status: "confirmed" }));
    const ui = await mountCalendar();
    const card = () => ui.container.querySelector('[data-stat="pending"]');
    await ui.press([...card().querySelectorAll("button")].find(b => b.textContent === "Accept all"));
    assert.equal(api.__calls("confirmAppointment").length, 0, "accepted without asking");
    assert.match(card().textContent, /Accept 2 requests \(1 already passed\)\?/);
    await ui.press([...card().querySelectorAll("button")].find(b => b.textContent === "Confirm"));
    await settle(80);
    assert.deepEqual(api.__calls("confirmAppointment").map(c => [c.args[0], c.args[1].schedule_version]),
                     [["ok1", 4], ["ok2", 7]]);
    await ui.unmount();
});

test("Review requests opens the list on the Pending tab", async () => {
    const ui = await mountCalendar();
    await openCalendar(ui);
    await ui.press(ui.button(b => b.textContent === "Review requests"));
    const tab = ui.container.querySelector('[role="tab"][aria-selected="true"]');
    assert.equal(tab?.textContent.trim().startsWith("Pending"), true);
    await ui.unmount();
});

test("the working-hours card says when none are set and opens the editor", async () => {
    const ui = await mountCalendar();
    const card = ui.container.querySelector('section[aria-label="Working hours"]');
    assert.match(card.textContent, /Set your working hours/);
    assert.match(card.textContent, /clients are told your availability is not set/);
    await ui.press([...card.querySelectorAll("button")].find(b => b.textContent.startsWith("Set up")));
    assert.ok(dom.window.document.querySelector('[role="dialog"][aria-label="Working hours"]'), "the editor did not open");
    await ui.unmount();
});

test("the week chart counts requests and confirmed appointments per day", async () => {
    api.__respond("listAppointments", ok({ items: [
        row("r", "11:00", "pending"), row("c1", "12:00", "confirmed"), row("c2", "13:00", "confirmed"),
        row("x", "14:00", "cancelled"),
    ], total: 4, pages: 1 }));
    const ui = await mountCalendar();
    const week = ui.container.querySelector('section[aria-label="This week"]');
    assert.match(week.textContent, /2 confirmed/);
    assert.ok(week.querySelector('[title="1 request, 2 confirmed"]'), "today's bar does not show 1 request and 2 confirmed");
    await ui.unmount();
});

test("an agenda appointment opens its details; actions are the list's own; ✕ returns to the agenda (2026-10-09)", async (t) => {
    const pinned = new Date(`${TODAY}T10:30:00+05:00`).getTime();
    t.mock.method(Date, "now", () => pinned);
    api.__respond("listAppointments", ok({ items: [row("a", "11:00", "confirmed")], total: 1, pages: 1 }));
    const ui = await mountCalendar();
    await openCalendar(ui);
    const opener = dom.window.document.querySelector('[aria-label^="Open appointment with"]');
    assert.ok(opener, "the agenda appointment cannot be opened");
    await ui.press(opener);
    const panel = dom.window.document.querySelector("[data-appointment-detail]");
    assert.ok(panel, "no detail panel");
    assert.match(panel.textContent, /Confirmed/);
    assert.match(panel.textContent, /Client a/);
    assert.match(panel.textContent, /Matter a/, "the client's note is not shown");
    const labels = [...panel.querySelectorAll("button")].map(b => b.textContent.trim());
    // Not started yet: completion and no-show are offered but held back.
    const done = [...panel.querySelectorAll("button")].find(b => b.textContent.trim() === "Mark completed");
    assert.ok(done && done.disabled, "Mark completed is offered before the meeting");
    assert.ok(labels.includes("Cancel"));
    assert.ok(!labels.includes("Reschedule"), "no reschedule action exists for a lawyer here");
    assert.doesNotMatch(panel.textContent, /Fee|Rs\./, "a fee was invented");
    await ui.press(panel.querySelector('[aria-label="Close appointment details"]'));
    assert.equal(dom.window.document.querySelector("[data-appointment-detail]"), null);
    assert.match(ui.text(), /Agenda/);
    await ui.unmount();
});

test("the range menu shows a week or a day; an appointment opens from either (2026-10-09)", async (t) => {
    const pinned = new Date(`${TODAY}T10:30:00+05:00`).getTime();
    t.mock.method(Date, "now", () => pinned);
    api.__respond("listAppointments", ok({ items: [row("a", "11:00", "confirmed")], total: 1, pages: 1 }));
    const ui = await mountCalendar();
    await openCalendar(ui);
    const doc = dom.window.document;
    const trigger = () => doc.querySelector('[aria-label^="Calendar range:"]');
    assert.match(trigger().getAttribute("aria-label"), /Monthly$/, "Monthly is not the default");
    assert.ok(!ui.button(b => b.textContent.trim().endsWith("Set working hours")), "the toolbar still has Set working hours");

    await ui.press(trigger());
    await ui.press([...doc.querySelectorAll('[role="option"]')].find(o => o.textContent === "Weekly"));
    const week = doc.querySelector("[data-week-board]");
    assert.ok(week, "no week board");
    assert.equal(week.querySelectorAll(".rb-col").length, 7);
    const chip = [...week.querySelectorAll(".rb-chip")].find(c => /Client a/.test(c.textContent));
    assert.ok(chip, "today's appointment is not on the week board");
    await ui.press(chip);
    assert.ok(doc.querySelector("[data-appointment-detail]"), "the appointment did not open from the week");

    await ui.press(trigger());
    await ui.press([...doc.querySelectorAll('[role="option"]')].find(o => o.textContent === "Daily"));
    const day = doc.querySelector("[data-day-board]");
    assert.ok(day, "no day board");
    assert.match(day.textContent, /Client a/);
    await ui.press(doc.querySelector('button[aria-label="Next day"]'));
    assert.match(doc.querySelector("[data-day-board]").textContent, /Nothing on this day\./);
    await ui.unmount();
});

test("an empty half hour on the week grid opens New meeting on that day and time (2026-10-09)", async (t) => {
    const pinned = new Date(`${TODAY}T10:30:00+05:00`).getTime();
    t.mock.method(Date, "now", () => pinned);
    api.__respond("listAppointments", ok({ items: [], total: 0, pages: 0 }));
    const ui = await mountCalendar();
    await openCalendar(ui);
    const doc = dom.window.document;
    await ui.press(doc.querySelector('[aria-label^="Calendar range:"]'));
    await ui.press([...doc.querySelectorAll('[role="option"]')].find(o => o.textContent === "Weekly"));
    const column = doc.querySelector(`[data-slot-column="${TODAY}"]`);
    assert.ok(column, "today's column is not on the week grid");
    // The grid starts at 8 AM, 60px an hour: 95px down is the 9:30 half hour.
    await act(async () => { column.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, clientY: 95 })); });
    await act(async () => { await new Promise(r => realSetTimeout(r, 30)); });
    const dialog = doc.querySelector('[role="dialog"][aria-label="New meeting"]');
    assert.ok(dialog, "the slot did not open New meeting");
    assert.equal(dialog.querySelector("#de-date").value, TODAY);
    assert.equal(dialog.querySelector("#de-time").value, "09:30");
    await ui.unmount();
});

test("the week grid shows court hearings, shades hours off, and marks requests as tentative (2026-10-09)", async (t) => {
    const pinned = new Date(`${TODAY}T10:30:00+05:00`).getTime();
    t.mock.method(Date, "now", () => pinned);
    api.__respond("listAppointments", ok({ items: [row("p", "16:00", "pending")], total: 1, pages: 1 }));
    api.__respond("listCases", ok({ items: [{ _id: "c1", title: "Rent arrears: Gulberg flat",
        hearing_dates: [{ _id: "h1", date: `${TODAY}T00:00:00Z`, time: "12:00", court: "Rent Tribunal Lahore", purpose: "Arguments" }] }], pages: 1, total: 1 }));
    // Every day 09:00-17:00, Monday (0) to Sunday (6).
    api.__respond("getMyWorkingHours", ok({ configured: true, enforced: true,
        working_hours: [0, 1, 2, 3, 4, 5, 6].map(weekday => ({ weekday, start: "09:00", end: "17:00" })), exceptions: [] }));
    const ui = await mountCalendar();
    await openCalendar(ui);
    const doc = dom.window.document;
    await ui.press(doc.querySelector('[aria-label^="Calendar range:"]'));
    await ui.press([...doc.querySelectorAll('[role="option"]')].find(o => o.textContent === "Weekly"));
    const column = doc.querySelector(`[data-slot-column="${TODAY}"]`);
    const chips = [...column.querySelectorAll(".rb-chip")];
    assert.ok(chips.some(c => /Rent arrears/.test(c.textContent)), "the hearing is not on the grid");
    assert.ok(chips.some(c => c.classList.contains("tentative")), "the pending request is not marked tentative");
    assert.ok(column.querySelectorAll(".tg-off").length >= 1, "hours outside 9-5 are not shaded");
    await ui.unmount();
});

/* ── clashes, drag, days off, the remembered range (2026-10-09) ──────────── */
const RANGE_KEY = "attorney:lawyer-appts-range";
async function toWeek(ui) {
    const doc = dom.window.document;
    await ui.press(doc.querySelector('[aria-label^="Calendar range:"]'));
    await ui.press([...doc.querySelectorAll('[role="option"]')].find(o => o.textContent === "Weekly"));
}
const mouse = (el, type, clientY) => act(async () => { el.dispatchEvent(new dom.window.MouseEvent(type, { bubbles: true, clientY, button: 0 })); });
const HEARING_AT_NOON = ok({ items: [{ _id: "c1", title: "Rent arrears: Gulberg flat",
    hearing_dates: [{ _id: "h1", date: `${TODAY}T00:00:00Z`, time: "12:00", court: "Rent Tribunal Lahore", purpose: "Arguments" }] }], pages: 1, total: 1 });

test("a meeting at a hearing's time warns of the clash, and still saves", async (t) => {
    t.mock.method(Date, "now", () => new Date(`${TODAY}T10:30:00+05:00`).getTime());
    api.__respond("listAppointments", ok({ items: [], total: 0, pages: 0 }));
    api.__respond("listCases", HEARING_AT_NOON);
    const ui = await mountCalendar();
    await openCalendar(ui);
    await toWeek(ui);
    const doc = dom.window.document;
    const column = doc.querySelector(`[data-slot-column="${TODAY}"]`);
    await mouse(column, "click", 245);   // 8 AM + 4h = noon
    const dialog = doc.querySelector('[role="dialog"][aria-label="New meeting"]');
    assert.equal(dialog.querySelector("#de-time").value, "12:00");
    const clash = dialog.querySelector("[data-clash]");
    assert.ok(clash, "no clash warning");
    assert.match(clash.textContent, /Rent arrears.*Court hearing/);
    assert.match(clash.textContent, /You can still save it/);
    assert.ok(!dialog.querySelector("button.de-save").disabled, "a clash blocked saving");
    try { localStorage.removeItem(RANGE_KEY); } catch {}
    await ui.unmount();
});

test("pressing and pulling down picks a start and a length", async (t) => {
    t.mock.method(Date, "now", () => new Date(`${TODAY}T10:30:00+05:00`).getTime());
    api.__respond("listAppointments", ok({ items: [], total: 0, pages: 0 }));
    const ui = await mountCalendar();
    await openCalendar(ui);
    await toWeek(ui);
    const doc = dom.window.document;
    const column = doc.querySelector(`[data-slot-column="${TODAY}"]`);
    await mouse(column, "mousedown", 95);    // 9:30
    await mouse(column, "mousemove", 185);   // the 11:00 half hour
    await act(async () => { dom.window.dispatchEvent(new dom.window.MouseEvent("mouseup", { bubbles: true })); });
    await mouse(column, "click", 185);       // the click that ends the drag adds nothing more
    const dialogs = doc.querySelectorAll('[role="dialog"][aria-label="New meeting"]');
    assert.equal(dialogs.length, 1);
    assert.equal(dialogs[0].querySelector("#de-time").value, "09:30");
    assert.equal(dialogs[0].querySelector("#de-dur").value, "120", "9:30 to 11:30 is two hours");
    try { localStorage.removeItem(RANGE_KEY); } catch {}
    await ui.unmount();
});

test("a day off is closed on the grid and says so; the chosen range is remembered", async (t) => {
    t.mock.method(Date, "now", () => new Date(`${TODAY}T10:30:00+05:00`).getTime());
    api.__respond("listAppointments", ok({ items: [], total: 0, pages: 0 }));
    api.__respond("getMyWorkingHours", ok({ configured: false, enforced: false, working_hours: [],
        exceptions: [{ date: TODAY, reason: "private" }] }));
    let ui = await mountCalendar();
    await openCalendar(ui);
    await toWeek(ui);
    const doc = dom.window.document;
    const column = doc.querySelector(`[data-slot-column="${TODAY}"]`);
    assert.equal(column.querySelectorAll(".tg-off").length, 1, "the day off is not shaded");
    assert.match(doc.querySelector(".tg-allday").textContent, /Day off/);
    assert.doesNotMatch(doc.body.textContent, /private/, "the reason for a day off was shown");
    await ui.unmount();
    ui = await mountCalendar();
    await openCalendar(ui);
    assert.match(doc.querySelector('[aria-label^="Calendar range:"]').getAttribute("aria-label"), /Weekly$/, "the range was not remembered");
    try { localStorage.removeItem(RANGE_KEY); } catch {}
    await ui.unmount();
});
