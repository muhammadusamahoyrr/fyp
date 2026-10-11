/* Cases module integrity (Phase 1): states the workspace can be stuck in,
 * and writes that must not repeat.
 *
 * WHAT WAS WRONG.
 *   * The workspace rendered "Loading case…" whenever its case was not in the
 *     list, for ever: after the lawyer ended the engagement (the case leaves
 *     their list), from a stale link, or when the list read failed. There was
 *     no way back but the sidebar.
 *   * List reads could land out of order: an older, slower response replaced
 *     a newer one.
 *   * Schedule hearing had no busy guard and no request id: a double click
 *     created two hearings and two client notices.
 *   * A second "Record outcome" was not refused (now 409 from the server): the
 *     page must say so and re-read, not create follow-up tasks again.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "HTMLInputElement", "Element",
                    "Node", "Event", "CustomEvent", "MouseEvent", "KeyboardEvent", "MutationObserver",
                    "getComputedStyle", "localStorage", "sessionStorage"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act, useState } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { CaseCtx } = await import("../src/components/lawyer/theme.js");
const { CasesPage } = await import("../src/components/lawyer/CasesPage.jsx");
const { pktToday } = await import("../src/lib/bookingTime.js");
const h = React.createElement;

const settle = (ms = 40) => act(async () => { await new Promise(r => setTimeout(r, ms)); });

function addDays(n) {
    const d = new Date(`${pktToday()}T12:00:00Z`);
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
}
const hearing = (id, date, purpose, extra = {}) =>
    ({ _id: id, date: `${date}T00:00:00Z`, time: "10:00", court: "Civil Court Lahore", judge: "", purpose, ...extra });
const kase = (n, status, hearings = []) => ({
    _id: `665f0000000000000000000${n}`, case_number: `CIV-2026-00${n}`, title: `Matter ${n}`,
    client_name: `Client ${n}`, province: "punjab", case_type: "civil", status, hearing_dates: hearings,
});
const SOON = kase(1, "in_progress", [hearing("h1", addDays(5), "Framing of issues")]);
const LATER = kase(2, "in_progress", [hearing("h2", addDays(40), "Evidence")]);
const NONE = kase(3, "open");
const SHUT = kase(4, "closed");
const REQUEST = { id: "e1", status: "requested", case_id: "c9", case_title: "Inheritance claim",
                  case_number: "CIV-2026-009", case_type: "family", client_name: "Sara Khan",
                  message: "Please take my case", created_at: `${addDays(-2)}T09:00:00Z` };

function Host({ openAt = null, pages = [] }) {
    const [openCaseId, setOpenCaseId] = useState(openAt);
    return h(CaseCtx.Provider, {
        value: { openCaseId, setOpenCaseId, activeCase: null, setActiveCase: () => {}, docs: {}, setDocs: () => {},
                 setPage: p => pages.push(p) },
    }, h(CasesPage));
}
async function mount(props = {}) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(h(Host, props)); });
    await settle();
    return { container, unmount: async () => { await act(async () => root.unmount()); container.remove(); } };
}
const allButtons = (root) => [...root.querySelectorAll("button")];
const buttonText = (root, text) => allButtons(root).find(b => b.textContent.trim() === text);
const tab = (root, name) => [...root.querySelectorAll('[role="tab"]')].find(b => b.textContent.startsWith(name));
async function click(el) {
    assert.ok(el, "element to click was not found");
    await act(async () => { el.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
}
async function type(el, value) {
    const proto = el.tagName === "TEXTAREA" ? dom.window.HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    await act(async () => { el.dispatchEvent(new Event("input", { bubbles: true })); });
}
const sectionTitles = (root) => [...root.querySelectorAll("span")]
    .map(s => s.textContent.trim()).filter(t => ["New requests", "No hearing yet", "Active", "History"].includes(t));


test.beforeEach(() => {
    api.__reset();
    api.__respond("listCases", { data: { items: [LATER, SOON, NONE, SHUT] }, error: null });
    api.__respond("listEngagements", { data: [], error: null });
    api.__respond("listTasks", { data: [], error: null });
    api.__respond("listMessages", { data: [], error: null });
    api.__respond("listDocuments", { data: [], error: null });
});

const text = (view) => view.container.textContent;
const button = (view, label) => allButtons(view.container).find(b => b.textContent.trim() === label);
const bodyButton = (label) => allButtons(document.body).find(b => b.textContent.trim() === label);

/* ── 1. never stuck on "Loading case…" ─────────────────────────────────── */

test("ending the engagement while the case is open leads back, not to a permanent Loading", async () => {
    api.__respond("listEngagements", { data: [{ id: "e7", case_id: SOON._id, status: "accepted", client_name: "Client 1" }], error: null });
    let ended = false;
    api.__respond("terminateEngagement", () => { ended = true; return { data: { status: "terminated" }, error: null }; });
    api.__respond("listCases", () => ({ data: { items: ended ? [LATER, NONE, SHUT] : [LATER, SOON, NONE, SHUT] }, error: null }));
    const realPrompt = globalThis.prompt;
    globalThis.prompt = () => "Client stopped responding";
    dom.window.prompt = globalThis.prompt;
    try {
        const view = await mount({ openAt: SOON.case_number });
        await click(button(view, "End engagement"));
        await settle(80);
        assert.ok(ended, "the engagement was not ended");
        assert.doesNotMatch(text(view), /Loading case…/, "stuck on Loading after the case left the list");
        assert.match(text(view), /no longer in your list/);
        await click(button(view, "← Back to cases"));
        assert.match(text(view), /CIV-2026-002/, "Back did not return to the list");
        await view.unmount();
    } finally {
        globalThis.prompt = realPrompt;
    }
});

test("a stale or inaccessible case link says so, with a way back", async () => {
    const view = await mount({ openAt: "ATT-2020-GONE0000" });
    await settle(40);
    assert.doesNotMatch(text(view), /Loading case…/);
    assert.match(text(view), /no longer in your list/);
    assert.ok(button(view, "← Back to cases"));
    await view.unmount();
});

test("a failed list load shows the error and Retry; Retry then opens the case", async () => {
    let calls = 0;
    api.__respond("listCases", () => {
        calls += 1;
        return calls === 1
            ? { data: null, error: { message: "Server unavailable" }, status: 503 }
            : { data: { items: [LATER, SOON, NONE, SHUT] }, error: null };
    });
    const view = await mount({ openAt: SOON.case_number });
    await settle(40);
    assert.doesNotMatch(text(view), /Loading case…/);
    assert.match(text(view), /Server unavailable/);
    await click(button(view, "Retry"));
    await settle(40);
    assert.ok(view.container.querySelector('[aria-label="Case sections"]'), "Retry did not open the case");
    await view.unmount();
});

test("an older list response that lands last does not replace the newer one", async () => {
    const { broadcastNotification } = await import("../src/lib/notificationTarget.js");
    const renamed = { ...SOON, title: "Renamed matter" };
    // Ordered explicitly: the first read is held open, the second lands, then
    // the first is released with OLDER data.
    let releaseFirst;
    let calls = 0;
    api.__respond("listCases", () => {
        calls += 1;
        if (calls === 1) return new Promise(r => { releaseFirst = () => r({ data: { items: [LATER, SOON, NONE, SHUT] }, error: null }); });
        return { data: { items: [LATER, renamed, NONE, SHUT] }, error: null };
    });
    const view = await mount();
    await act(async () => { broadcastNotification({ type: "case_update", payload: {} }); });
    await settle(40);
    await act(async () => { releaseFirst(); });
    await settle(40);
    assert.match(text(view), /Renamed matter/, "the older response, landing last, overwrote the newer one");
    await view.unmount();
});

/* ── 2. one hearing per submission ─────────────────────────────────────── */

async function fillScheduleForm(date, purpose) {
    await click(bodyButton("Add hearing"));
    const q = (sel) => document.body.querySelector(sel);
    await type(q('input[type="date"]'), date);
    await type(q('input[placeholder="e.g. Evidence hearing — witness examination"]'), purpose);
}
const saveButton = () => allButtons(document.body).find(b => /^(Schedule Hearing|Scheduling…)$/.test(b.textContent.trim()));

test("a double click on Schedule Hearing sends one hearing, with a request id", async () => {
    let release;
    api.__respond("addHearing", () => new Promise(r => { release = () => r({ data: { ...SOON }, error: null }); }));
    const view = await mount({ openAt: SOON.case_number });
    await fillScheduleForm(addDays(12), "Arguments");
    const save = saveButton();
    assert.ok(save, "no Schedule Hearing button");
    await act(async () => {
        save.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        save.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle(20);
    assert.equal(api.__calls("addHearing").length, 1, "the second click sent a second hearing");
    assert.match(api.__calls("addHearing")[0].args[1].request_id || "", /^[A-Za-z0-9_-]{16,64}$/, "no request id sent");
    release();
    await settle(40);
    await view.unmount();
});

test("a retry after an uncertain failure reuses the request id; a new hearing gets a new one", async () => {
    let n = 0;
    api.__respond("addHearing", () => (++n === 1
        ? { data: null, error: { message: "Network error. Please check your connection." }, status: 0 }
        : { data: { ...SOON }, error: null }));
    const view = await mount({ openAt: SOON.case_number });
    await fillScheduleForm(addDays(12), "Arguments");
    await click(saveButton());
    await settle(30);
    await click(saveButton());              // the same form, retried
    await settle(30);
    const ids = api.__calls("addHearing").map(c => c.args[1].request_id);
    assert.equal(ids.length, 2);
    assert.equal(ids[0], ids[1], "the retry of the same form used a different request id");

    await fillScheduleForm(addDays(20), "Evidence");
    await click(saveButton());
    await settle(30);
    assert.notEqual(api.__calls("addHearing")[2].args[1].request_id, ids[0], "a new hearing reused the old request id");
    await view.unmount();
});

/* ── 3. an outcome already recorded ────────────────────────────────────── */

test("a 409 'already recorded' outcome is reported, the case re-read, no follow-up tasks created", async () => {
    const PAST = kase(6, "in_progress", [hearing("h6", addDays(-1), "Arguments")]);
    api.__respond("listCases", { data: { items: [PAST] }, error: null });
    api.__respond("recordHearingOutcome", { data: null, error: { message: "An outcome is already recorded for this hearing." }, status: 409 });
    const view = await mount({ openAt: PAST.case_number });
    await click(tab(view.container, "Schedule"));
    await click(allButtons(view.container).find(b => b.textContent.trim() === "Record outcome"));
    const before = api.__calls("listCases").length;
    await click(allButtons(document.body).find(b => /Record & Notify Client/.test(b.textContent)));
    await settle(40);
    assert.match(text(view), /already recorded/);
    assert.equal(api.__calls("addTask").length, 0, "follow-up tasks were created for an outcome that was not recorded");
    assert.ok(api.__calls("listCases").length > before, "the case was not re-read after the conflict");
    await view.unmount();
});

/* ── 5. a reschedule the server refuses as stale (409) ─────────────────── */

test("a 409 reschedule closes the dialog, says why, re-reads the case, and claims no move", async () => {
    let reads = 0;
    api.__respond("listCases", () => { reads += 1; return { data: { items: [LATER, SOON, NONE, SHUT] }, error: null }; });
    api.__respond("rescheduleHearing", { data: null, error: { message: "This hearing was changed meanwhile. Reload the case and try again." }, status: 409 });
    const view = await mount({ openAt: SOON.case_number });
    await click(tab(view.container, "Schedule"));
    await click(allButtons(view.container).find(b => b.textContent.trim() === "Reschedule"));
    const dialogOpen = () => allButtons(document.body).some(b => b.textContent.trim() === "Reschedule & notify client");
    assert.ok(dialogOpen(), "the reschedule dialog did not open");
    await type(document.body.querySelector('[role="dialog"] input[type="date"]'), addDays(9));
    const before = reads;
    await click(allButtons(document.body).find(b => b.textContent.trim() === "Reschedule & notify client"));
    await settle(40);
    assert.equal(dialogOpen(), false, "the dialog stayed open after the conflict");
    assert.match(text(view), /changed meanwhile/);
    assert.ok(reads > before, "the case was not re-read after the conflict");
    assert.doesNotMatch(text(view), /Hearing moved to/, "a success message was shown for a refused move");
    assert.doesNotMatch(text(view), /Rescheduled/, "the hearing was marked rescheduled locally");
    await view.unmount();
});

/* ── B1. chip counts agree with the rows shown ─────────────────────────── */

const TERMS = { id: "e2", status: "terms_proposed", case_id: "c8", case_title: "Partition suit", case_number: "CIV-2026-008",
                case_type: "civil", client_name: "Omar", fee_amount: 50000, created_at: `${addDays(-1)}T09:00:00Z` };
const ASKED = { id: "e1", status: "requested", case_id: "c9", case_title: "Inheritance claim", case_number: "CIV-2026-009",
                case_type: "family", client_name: "Sara Khan", created_at: `${addDays(-2)}T09:00:00Z` };
const chipN = (view, name) => Number((tab(view.container, name)?.textContent.match(/(\d+)$/) || [])[1]);

test("New requests and Needs me do not count requests waiting on the client; All does not count closed cases", async () => {
    api.__respond("listEngagements", { data: [ASKED, TERMS], error: null });
    const view = await mount();
    assert.equal(chipN(view, "New requests"), 1, "terms already sent were counted as a new request");
    // Needs me: 1 request to answer + 1 case with no date (NONE).
    assert.equal(chipN(view, "Needs me"), 2, "Needs me counted a request waiting on the client");
    // All: 2 requests (one to answer, one awaiting the client) + 3 live cases; the closed one is History.
    assert.equal(chipN(view, "All"), 5, "All counted a closed case its view hides");
    await view.unmount();
});

test("every chip's count equals the rows its view renders", async () => {
    const OVERDUE = kase(5, "in_progress", [hearing("h5", addDays(-2), "Arguments")]);
    api.__respond("listCases", { data: { items: [LATER, SOON, NONE, SHUT, OVERDUE] }, error: null });
    api.__respond("listEngagements", { data: [ASKED, TERMS], error: null });
    const view = await mount();
    for (const name of ["All", "Needs me", "New requests", "Not filed yet", "Active"]) {
        await click(tab(view.container, name));
        const rows = view.container.querySelectorAll("[data-row]").length;
        assert.equal(chipN(view, name), rows, `${name}: chip says ${chipN(view, name)}, ${rows} rows shown`);
    }
    await click(allButtons(view.container).find(b => b.getAttribute("role") === "tab" && b.textContent.trim().startsWith("Closed")));
    assert.equal(view.container.querySelectorAll("[data-row]").length, 1);
    await view.unmount();
});

test("the Filter preview counts the selected chip's rows, without closed cases", async () => {
    api.__respond("listEngagements", { data: [ASKED], error: null });
    const view = await mount();
    await click(tab(view.container, "Active"));
    await click(allButtons(view.container).find(b => b.textContent.trim().startsWith("Filter")));
    const panel = () => view.container.querySelector("[data-filter-panel]");
    assert.match(panel().textContent, /Showing 2 of 2 results/, "the preview did not follow the Active chip");
    await click(panel().querySelector('[data-option="family"]'));
    assert.match(panel().textContent, /Showing 0 of 2 results/);
    await view.unmount();
});

/* ── B2. a failed read is never shown as an empty list ─────────────────── */

test("a failed first load shows the error and Retry, not 'No cases yet'", async () => {
    let n = 0;
    api.__respond("listCases", () => (++n === 1
        ? { data: null, error: { message: "Server unavailable" }, status: 503 }
        : { data: { items: [SOON] }, error: null }));
    const view = await mount();
    assert.doesNotMatch(text(view), /No cases yet/, "a failed read was shown as an empty list");
    assert.match(text(view), /Server unavailable/);
    await click(button(view, "Retry"));
    assert.match(text(view), /CIV-2026-001/);
    assert.doesNotMatch(text(view), /Server unavailable/, "the error stayed after a successful retry");
    await view.unmount();
});

test("a successful empty answer is the only thing that says 'No cases yet'", async () => {
    api.__respond("listCases", { data: { items: [] }, error: null });
    const view = await mount();
    assert.match(text(view), /No cases yet/);
    await view.unmount();
});

test("a failed refresh keeps the cases shown and says the list may be out of date", async () => {
    const { broadcastNotification } = await import("../src/lib/notificationTarget.js");
    let n = 0;
    api.__respond("listCases", () => (++n === 1
        ? { data: { items: [SOON, LATER] }, error: null }
        : { data: null, error: { message: "Timed out" }, status: 504 }));
    const view = await mount();
    await act(async () => { broadcastNotification({ type: "case_update", payload: {} }); });
    await settle(40);
    assert.match(text(view), /CIV-2026-001/, "the cases already shown were dropped");
    assert.match(text(view), /could not refresh/i);
    assert.ok(button(view, "Retry"), "no Retry on the stale notice");
    await view.unmount();
});

test("a failed request-list read is reported with Retry, not shown as no requests", async () => {
    let n = 0;
    api.__respond("listEngagements", () => (++n === 1
        ? { data: null, error: { message: "Requests unavailable" }, status: 503 }
        : { data: [{ id: "e1", status: "requested", case_id: "c9", case_title: "Inheritance claim", case_number: "CIV-2026-009",
                     case_type: "family", client_name: "Sara Khan", created_at: `${addDays(-2)}T09:00:00Z` }], error: null }));
    const view = await mount();
    assert.match(text(view), /Requests unavailable/, "the request-list failure was swallowed");
    await click(button(view, "Retry"));
    assert.match(text(view), /Inheritance claim/);
    assert.doesNotMatch(text(view), /Requests unavailable/);
    await view.unmount();
});

/* ── B3. hearings follow the server; the court prefill is never stale ──── */

const withExtraHearing = (k, h) => ({ ...k, hearing_dates: [...(k.hearing_dates || []), h] });

test("a live case update shows the open case's new hearing without leaving it", async () => {
    const { broadcastNotification } = await import("../src/lib/notificationTarget.js");
    let changed = false;
    const ADDED = hearing("h9", addDays(25), "Final arguments", { court: "Sessions Court Lahore" });
    api.__respond("listCases", () => ({ data: { items: [LATER, changed ? withExtraHearing(SOON, ADDED) : SOON, NONE, SHUT] }, error: null }));
    const view = await mount({ openAt: SOON.case_number });
    await click(tab(view.container, "Schedule"));
    assert.doesNotMatch(text(view), /Final arguments/);
    changed = true;
    await act(async () => { broadcastNotification({ type: "case_update", payload: { case_id: SOON._id } }); });
    await settle(60);
    assert.match(text(view), /Final arguments/, "the open case kept its old hearings");
    await view.unmount();
});

test("reopening a case shows its current hearings, not the first ones cached", async () => {
    const { broadcastNotification } = await import("../src/lib/notificationTarget.js");
    let changed = false;
    const ADDED = hearing("h9", addDays(25), "Final arguments");
    api.__respond("listCases", () => ({ data: { items: [LATER, changed ? withExtraHearing(SOON, ADDED) : SOON, NONE, SHUT] }, error: null }));
    const view = await mount({ openAt: SOON.case_number });
    await click(view.container.querySelector('nav[aria-label="Breadcrumb"] button'));
    changed = true;
    await act(async () => { broadcastNotification({ type: "case_update", payload: {} }); });
    await settle(60);
    await click([...view.container.querySelectorAll('[data-row="case"]')].find(r => r.textContent.includes("CIV-2026-001")));
    await click(tab(view.container, "Schedule"));
    assert.match(text(view), /Final arguments/, "the reopened case showed the hearings cached the first time");
    await view.unmount();
});

test("switching cases never shows another case's hearings", async () => {
    const view = await mount({ openAt: SOON.case_number });
    await click(tab(view.container, "Schedule"));
    assert.match(text(view), /Framing of issues/);
    await click(view.container.querySelector('nav[aria-label="Breadcrumb"] button'));
    await click([...view.container.querySelectorAll('[data-row="case"]')].find(r => r.textContent.includes("CIV-2026-002")));
    await click(tab(view.container, "Schedule"));
    assert.match(text(view), /Evidence/);
    assert.doesNotMatch(text(view), /Framing of issues/, "case 1's hearing showed under case 2");
    await view.unmount();
});

const quickCourt = (view) => view.container.querySelector('input[placeholder="e.g. Civil Court Lahore"]');

test("the quick form's court is filled when a court becomes known after it opened", async () => {
    const { broadcastNotification } = await import("../src/lib/notificationTarget.js");
    let changed = false;
    const HELD = hearing("h7", addDays(-30), "Admission", { court: "Sessions Court Lahore", outcome: "adjourned" });
    api.__respond("listCases", () => ({ data: { items: [changed ? withExtraHearing(NONE, HELD) : NONE] }, error: null }));
    const view = await mount({ openAt: NONE.case_number });
    assert.ok(quickCourt(view), "no quick hearing form");
    assert.equal(quickCourt(view).value, "");
    changed = true;
    await act(async () => { broadcastNotification({ type: "case_update", payload: { case_id: NONE._id } }); });
    await settle(60);
    assert.equal(quickCourt(view).value, "Sessions Court Lahore", "the court was not prefilled once known");
    await view.unmount();
});

test("a court the lawyer typed is never overwritten by data arriving later", async () => {
    const { broadcastNotification } = await import("../src/lib/notificationTarget.js");
    let changed = false;
    const HELD = hearing("h7", addDays(-30), "Admission", { court: "Sessions Court Lahore", outcome: "adjourned" });
    api.__respond("listCases", () => ({ data: { items: [changed ? withExtraHearing(NONE, HELD) : NONE] }, error: null }));
    const view = await mount({ openAt: NONE.case_number });
    await type(quickCourt(view), "Family Court Rawalpindi");
    changed = true;
    await act(async () => { broadcastNotification({ type: "case_update", payload: { case_id: NONE._id } }); });
    await settle(60);
    assert.equal(quickCourt(view).value, "Family Court Rawalpindi", "the typed court was overwritten");
    await view.unmount();
});

/* ── B4. the form limits mirror the server's ───────────────────────────── */

test("hearing, outcome, reschedule, message and task inputs carry the server's limits", async () => {
    const PAST = kase(6, "in_progress", [hearing("h6", addDays(-1), "Arguments"), hearing("h7", addDays(9), "Evidence")]);
    api.__respond("listCases", { data: { items: [PAST] }, error: null });
    const view = await mount({ openAt: PAST.case_number });
    const maxOf = (sel) => Number(document.body.querySelector(sel)?.getAttribute("maxlength"));

    await click(bodyButton("Add hearing"));
    assert.equal(maxOf('input[placeholder="e.g. Lahore High Court"]'), 200, "court");
    assert.equal(maxOf('input[placeholder="e.g. Hon. Justice Mehta"]'), 120, "judge");
    assert.equal(maxOf('input[placeholder="e.g. Evidence hearing — witness examination"]'), 300, "purpose");
    assert.equal(document.body.querySelector('input[type="time"]').type, "time", "the time is a 24-hour time input");
    await click(bodyButton("Cancel"));

    await click(tab(view.container, "Schedule"));
    await click(allButtons(view.container).find(b => b.textContent.trim() === "Record outcome"));
    assert.equal(maxOf("textarea"), 2000, "outcome note");
    await click(bodyButton("Cancel"));

    await click(allButtons(view.container).find(b => b.textContent.trim() === "Reschedule"));
    const reason = document.body.querySelector("textarea");      // the dialog's only text area
    assert.equal(Number(reason?.getAttribute("maxlength")), 300, "reschedule reason");
    await click(bodyButton("Cancel"));

    await click(tab(view.container, "Messages"));
    assert.equal(maxOf('input[placeholder^="Write to"]'), 4000, "message");
    await click(tab(view.container, "Tasks"));
    const taskInput = [...view.container.querySelectorAll("input")].find(el => /task/i.test(el.placeholder || ""));
    assert.equal(Number(taskInput?.getAttribute("maxlength")), 200, "task title");
    await view.unmount();
});

/* ── B6. Recent & upcoming keeps the nearest things ────────────────────── */

test("Coming up shows tomorrow's hearing first, not tasks due next month", async () => {
    const TOMORROW = kase(7, "in_progress", [hearing("h7", addDays(1), "Framing of issues")]);
    api.__respond("listCases", { data: { items: [TOMORROW] }, error: null });
    api.__respond("listTasks", { data: [1, 2, 3, 4, 5, 6].map(n => ({ _id: `t${n}`, title: `Brief ${n}`, done: false, due: `${addDays(30 + n)}T00:00:00Z` })), error: null });
    const view = await mount({ openAt: TOMORROW.case_number });
    await settle(40);
    const feed = view.container.querySelector("[data-feed]");
    assert.ok(feed, "no Coming up feed");
    const rows = [...feed.querySelectorAll("[data-feed-item]")].map(r => r.textContent);
    assert.equal(rows.length, 5);
    assert.match(rows[0], /Framing of issues.*Hearing/, "the hearing tomorrow was not first (or not shown)");
    assert.match(rows[1], /Brief 1/, "the nearest task should follow");
    await view.unmount();
});

/* ── C1. request age in Pakistan days ──────────────────────────────────── */

test("a request sent at 00:30 PKT today reads 'sent today', whatever the UTC date", async () => {
    // 00:30 PKT today, expressed in UTC (the previous UTC day, 19:30).
    const sentAt = new Date(`${pktToday()}T00:30:00+05:00`).toISOString();
    api.__respond("listEngagements", { data: [{ id: "e5", status: "requested", case_id: "c5", case_title: "Night request",
        case_number: "CIV-2026-055", case_type: "civil", client_name: "Bilal", created_at: sentAt }], error: null });
    const view = await mount();
    const row = [...view.container.querySelectorAll('[data-row="request"]')].find(r => r.textContent.includes("Night request"));
    assert.ok(row, "the request is not listed");
    assert.match(row.textContent, /sent today/, `read: ${row.textContent}`);
    await view.unmount();
});

/* ── C2. no older response replaces a newer one ────────────────────────── */

test("an older request-list response that lands last does not replace the newer one", async () => {
    const { broadcastNotification } = await import("../src/lib/notificationTarget.js");
    const req = (title) => ({ id: "e1", status: "requested", case_id: "c9", case_title: title, case_number: "CIV-2026-009",
                              case_type: "family", client_name: "Sara Khan", created_at: `${addDays(-2)}T09:00:00Z` });
    // The order is controlled, not timed: the first read is held open until
    // the second has landed, then released with OLDER data.
    let releaseFirst;
    let calls = 0;
    api.__respond("listEngagements", () => {
        calls += 1;
        if (calls === 1) return new Promise(r => { releaseFirst = () => r({ data: [req("Old title")], error: null }); });
        return { data: [req("New title")], error: null };
    });
    const view = await mount();
    await act(async () => { broadcastNotification({ type: "engagement_terms_proposed", payload: {} }); });
    await settle(40);
    assert.equal(calls, 2);
    await act(async () => { releaseFirst(); });
    await settle(40);
    assert.match(text(view), /New title/, "the older request list, landing last, overwrote the newer one");
    assert.doesNotMatch(text(view), /Old title/);
    await view.unmount();
});

test("an older message-thread re-read that lands last does not replace the newer one", async () => {
    const { broadcastNotification } = await import("../src/lib/notificationTarget.js");
    let releaseOlder;
    let calls = 0;
    api.__respond("listMessages", () => {
        calls += 1;
        if (calls === 2) {          // the first live re-read: held open, then OLDER
            return new Promise(r => { releaseOlder = () => r({ data: [{ _id: "m1", sender_role: "client", text: "older thread" }], error: null }); });
        }
        if (calls === 3) return { data: [{ _id: "m1", sender_role: "client", text: "older thread" },
                                          { _id: "m2", sender_role: "client", text: "newest message" }], error: null };
        return { data: [], error: null };
    });
    const view = await mount({ openAt: SOON.case_number });
    await click(tab(view.container, "Messages"));
    await act(async () => { broadcastNotification({ type: "case_message", payload: { case_id: SOON._id } }); });
    await act(async () => { broadcastNotification({ type: "case_message", payload: { case_id: SOON._id } }); });
    await settle(40);
    await act(async () => { releaseOlder(); });
    await settle(40);
    assert.match(text(view), /newest message/, "the older thread re-read, landing last, overwrote the newer one");
    await view.unmount();
});

/* ── C3. dialogs and keyboard ──────────────────────────────────────────── */

const key = async (el, k, opts = {}) => {
    await act(async () => { el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...opts })); });
    await settle(10);
};
const dialog = () => document.body.querySelector('[role="dialog"]');
// A real outside click: the press starts on the backdrop, then the click.
const outsideClick = async (backdrop) => {
    await act(async () => {
        backdrop.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
        backdrop.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle(10);
};

test("a dialog is announced as one, takes focus, keeps Tab inside, closes on Escape, and returns focus", async () => {
    const view = await mount({ openAt: SOON.case_number });
    const opener = button(view, "Add hearing");
    opener.focus();
    await click(opener);
    const d = dialog();
    assert.ok(d, "no role=dialog");
    assert.equal(d.getAttribute("aria-modal"), "true");
    const labelled = document.getElementById(d.getAttribute("aria-labelledby") || "");
    assert.match(labelled?.textContent || "", /Schedule New Hearing/, "the dialog has no accessible name");
    assert.ok(d.contains(document.activeElement), "focus did not move into the dialog");

    const focusables = [...d.querySelectorAll("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])")];
    focusables.at(-1).focus();
    await key(focusables.at(-1), "Tab");
    assert.equal(document.activeElement, focusables[0], "Tab from the last control left the dialog");
    await key(focusables[0], "Tab", { shiftKey: true });
    assert.equal(document.activeElement, focusables.at(-1), "Shift+Tab from the first control left the dialog");

    await key(document.activeElement, "Escape");
    assert.equal(dialog(), null, "Escape did not close the dialog");
    assert.equal(document.activeElement, opener, "focus did not return to the button that opened it");
    await view.unmount();
});

function CountingHost({ opens }) {
    const [openCaseId, setOpenCaseId] = useState(null);
    return h(CaseCtx.Provider, {
        value: { openCaseId, setOpenCaseId, activeCase: null, docs: {}, setDocs: () => {}, setPage: () => {},
                 setActiveCase: (id) => opens.push(id) },
    }, h(CasesPage));
}

test("a case row opens on Enter and on Space, exactly once", async () => {
    for (const k of ["Enter", " "]) {
        const opens = [];
        const container = document.createElement("div");
        document.body.appendChild(container);
        const root = createRoot(container);
        await act(async () => { root.render(h(CountingHost, { opens })); });
        await settle();
        const row = [...container.querySelectorAll('[data-row="case"]')].find(r => r.textContent.includes("CIV-2026-001"));
        await key(row, k);
        assert.deepEqual(opens, [SOON.case_number], `${JSON.stringify(k)} opened ${opens.length} time(s)`);
        await act(async () => root.unmount());
        container.remove();
    }
});

test("Enter on a row's open button opens the case once, not twice", async () => {
    const opens = [];
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(h(CountingHost, { opens })); });
    await settle();
    const row = [...container.querySelectorAll('[data-row="case"]')].find(r => r.textContent.includes("CIV-2026-001"));
    const chevron = row.querySelector('button[aria-label="Open case"]');
    // A browser fires keydown and then the button's click for one Enter press,
    // before React re-renders: both in one step.
    await act(async () => {
        chevron.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
        chevron.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();
    assert.equal(opens.length, 1, `opened ${opens.length} times`);
    await act(async () => root.unmount());
    container.remove();
});

test("the New case form is not discarded by an outside click once something is typed", async () => {
    const realConfirm = globalThis.confirm;
    let asked = 0;
    globalThis.confirm = dom.window.confirm = () => { asked += 1; return false; };
    try {
        const view = await mount();
        await click(button(view, "New case"));
        const backdrop = dialog().parentElement;
        // Clean form: an outside click closes it.
        await outsideClick(backdrop);
        assert.equal(dialog(), null, "a clean form should close on an outside click");

        await click(button(view, "New case"));
        await type(document.body.querySelector('input[placeholder="Full name"]'), "Muhammad Aslam");
        await outsideClick(dialog().parentElement);
        assert.ok(dialog(), "typed input was discarded by an outside click");
        await key(document.activeElement || document.body, "Escape");
        assert.equal(asked, 1, "Escape on a typed form did not ask before discarding");
        assert.ok(dialog(), "the form closed although discarding was declined");
        globalThis.confirm = dom.window.confirm = () => true;
        await click(bodyButton("Cancel"));
        assert.equal(dialog(), null, "Cancel with confirmation did not close");
        await view.unmount();
    } finally {
        globalThis.confirm = dom.window.confirm = realConfirm;
    }
});

/* ── C4. an older toast's timer never clears a newer toast ─────────────── */

test("a second toast stays for its own time, not until the first toast's timer", async () => {
    api.__respond("listTasks", { data: [{ _id: "t1", title: "File reply", done: false }], error: null });
    api.__respond("toggleTask", { data: null, error: { message: "Task not found" }, status: 404 });
    const view = await mount({ openAt: SOON.case_number });
    // Toast A: saving an empty hearing form (shown for 2.8 s).
    await click(bodyButton("Add hearing"));
    await click(saveButton());
    assert.match(text(view), /Date, court and purpose are required/);
    await click(bodyButton("Cancel"));
    await settle(2000);
    // Toast B, 2 s later: a task that cannot be ticked.
    await click(tab(view.container, "Tasks"));
    await click(view.container.querySelector('[role="checkbox"][aria-label="File reply"]'));
    assert.match(text(view), /Task not found/);
    // Past A's timer (2.8 s), well inside B's own 2.8 s.
    await settle(1100);
    assert.match(text(view), /Task not found/, "the first toast's timer cleared the second toast early");
    await view.unmount();
});

/* ── a closed case's overview offers nothing that would write ──────────── */

test("a closed case's overview has no Add shortcuts and no 'set the first date' prompt", async () => {
    const view = await mount({ openAt: SHUT.case_number });
    assert.match(text(view), /kept as a record/);
    const adds = [...view.container.querySelectorAll("button")].filter(b => b.textContent.trim() === "Add");
    assert.equal(adds.length, 0, `a closed case offers ${adds.length} Add shortcut(s)`);
    assert.doesNotMatch(text(view), /Set the first date/, "a closed case is prompted for its first hearing");
    assert.equal(dialog(), null);
    await view.unmount();
});

/* ── a dialog covers the whole app, not only the page area ──────────────── */

test("dialogs render at the top of the document, outside the page's stacking context", async () => {
    // Inside the page the backdrop sat in the content column's z-index 1
    // stacking context, below the sticky sidebar (z-index 10): the sidebar
    // stayed clickable behind an open dialog and one click navigated away,
    // discarding a typed New case form.
    const view = await mount();
    await click(button(view, "New case"));
    const d = dialog();
    assert.ok(d, "the New case dialog did not open");
    assert.equal(view.container.contains(d), false, "the dialog rendered inside the page area");
    assert.equal(d.parentElement.parentElement, document.body, "the backdrop is not a direct child of <body>");
    await click(bodyButton("Cancel"));
    assert.equal(dialog(), null);
    await view.unmount();
});
