/* Lawyer Cases redesign: the list sorted by what needs doing, and a workspace
 * with Overview / Schedule / Messages / Tasks / Documents.
 *
 * UI only over existing routes. What these pin down:
 *   * The list groups cases by what the lawyer must do next and hides closed
 *     ones behind History; new client requests are actionable from the list.
 *   * "Send terms" still goes through the fee step: a request is never
 *     accepted without a price the client sees first.
 *   * The workspace's counts come from the server (tasks, messages), quick
 *     replies only prefill, templates create real tasks, and the Documents
 *     tab lists the case's server documents.
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
    // Queries run from <body>: the page's dialogs render there (a portal), not
    // inside the page's own container.
    return { container: document.body, unmount: async () => { await act(async () => root.unmount()); container.remove(); } };
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
    api.__respond("listEngagements", { data: [REQUEST], error: null });
    api.__respond("listTasks", { data: [], error: null });
    api.__respond("listMessages", { data: [], error: null });
    api.__respond("listDocuments", { data: [], error: null });
});

/* ── list ─────────────────────────────────────────────────────────────── */

test("the list groups by what to do next, sorts by next hearing, and hides closed cases", async () => {
    const view = await mount();
    const text = view.container.textContent;
    assert.match(text, /4 cases/);
    assert.match(text, /1 new request to accept/);
    // Requests first, then cases with no date, then active by next hearing.
    const order = ["Inheritance claim", "CIV-2026-003", "CIV-2026-001", "CIV-2026-002"].map(t => text.indexOf(t));
    assert.ok(order.every(i => i >= 0) && order.every((v, i) => !i || v > order[i - 1]), `wrong order: ${order}`);
    assert.doesNotMatch(text, /CIV-2026-004/, "a closed case is in the live list");
    assert.match(text, /in 5 days/);

    await click(allButtons(view.container).find(b => b.getAttribute("role") === "tab" && b.textContent.trim().startsWith("Closed")));
    assert.match(view.container.textContent, /CIV-2026-004/);
    await view.unmount();
});

test("search filters every group by title, client or case number", async () => {
    const view = await mount();
    await type(view.container.querySelector('input[placeholder^="Search"]'), "client 2");
    const text = view.container.textContent;
    assert.match(text, /CIV-2026-002/);
    assert.doesNotMatch(text, /CIV-2026-001|CIV-2026-003|Inheritance claim/);
    await view.unmount();
});

test("Send terms asks for a fee before anything is sent", async () => {
    api.__respond("proposeEngagementTerms", { data: { status: "terms_proposed" }, error: null });
    const view = await mount();
    await click(buttonText(view.container, "Send terms"));
    assert.match(view.container.textContent, /Send your terms/);
    await click(buttonText(view.container, "Send Terms to Client"));
    assert.equal(api.__calls("proposeEngagementTerms").length, 0, "terms were sent without a fee");

    await type(view.container.querySelector('input[type="number"]'), "50000");
    await click(buttonText(view.container, "Send Terms to Client"));
    const [id, body] = api.__calls("proposeEngagementTerms")[0].args;
    assert.equal(id, "e1");
    assert.equal(body.fee_amount, 50000);
    await view.unmount();
});

test("Export downloads the cases as CSV", async () => {
    let blob = null;
    const realCreate = URL.createObjectURL;
    URL.createObjectURL = (b) => { blob = b; return "blob:x"; };
    URL.revokeObjectURL = () => {};
    try {
        const view = await mount();
        await click(view.container.querySelector('button[aria-label="Export cases"]'));
        const csv = (await blob.text()).replace(/^﻿/, "");
        const lines = csv.trim().split("\r\n");
        assert.match(lines[0], /^"Case no.","Title","Client"/);
        assert.equal(lines.length, 5);
        await view.unmount();
    } finally {
        URL.createObjectURL = realCreate;
    }
});

/* ── workspace ────────────────────────────────────────────────────────── */

test("the header shows the stage; the tabs count what the server holds", async () => {
    api.__respond("listTasks", { data: [{ _id: "t1", title: "Brief", done: true }, { _id: "t2", title: "Witnesses", done: false }], error: null });
    api.__respond("listMessages", { data: [{ _id: "m1", sender_role: "client", text: "Salam", sender_name: "Client 1" }], error: null });
    const view = await mount({ openAt: SOON.case_number });
    const text = view.container.textContent;
    assert.match(text, /Hearing set/);
    // The open-task count rides on the Tasks tab (2026-10-09: the count strip
    // was replaced by tab badges), and the next date leads the Overview.
    assert.match(tab(view.container, "Tasks").textContent, /^Tasks1$/);
    assert.match(tab(view.container, "Messages").textContent, /^Messages1$/);
    assert.match(text, /in 5 days · \w{3} \d{1,2} \w{3}, 10:00 AM/);
    assert.match(text, /Next: \w{3} \d{1,2} \w{3}/, "the current stage does not say when the next step is");
    const header = view.container.querySelector('[aria-label^="Stage:"]');
    assert.equal(header.getAttribute("aria-label"), "Stage: Hearing set");
    await view.unmount();
});

test("with no hearing, the next step saves one from the overview", async () => {
    api.__respond("addHearing", { data: { ...NONE, hearing_dates: [hearing("hx", addDays(10), "Hearing")] }, error: null });
    const view = await mount({ openAt: NONE.case_number });
    assert.match(view.container.textContent, /Set the first hearing date/);
    const labelled = (name) => [...view.container.querySelectorAll("label")].find(l => l.textContent.trim() === name).parentElement.querySelector("input");
    await type(labelled("Date"), addDays(10));
    await type(labelled("Court"), "Civil Court Lahore");
    await click(buttonText(view.container, "Save hearing"));
    const [caseId, body] = api.__calls("addHearing")[0].args;
    assert.equal(caseId, NONE._id);
    assert.equal(body.court, "Civil Court Lahore");
    assert.match(view.container.textContent, /Prepare for/, "the next step did not move on");
    await view.unmount();
});

test("a quick reply only fills the box; Send sends it", async () => {
    api.__respond("sendMessage", { data: { _id: "m9", sender_role: "lawyer", text: "x" }, error: null });
    const view = await mount({ openAt: SOON.case_number });
    await click(tab(view.container, "Messages"));
    await click(buttonText(view.container, "Share next hearing date"));
    assert.equal(api.__calls("sendMessage").length, 0, "a quick reply sent a message by itself");
    const box = view.container.querySelector('input[placeholder^="Write to"]');
    assert.match(box.value, /next hearing is on .* Civil Court Lahore/);
    await click(view.container.querySelector('button[aria-label="Send message"]'));
    assert.equal(api.__calls("sendMessage")[0].args[0], SOON._id);
    await view.unmount();
});

test("a task template creates each task through the server", async () => {
    let n = 0;
    api.__respond("addTask", (caseId, body) => ({ data: { _id: `t${++n}`, title: body.title, done: false }, error: null }));
    const view = await mount({ openAt: SOON.case_number });
    await click(tab(view.container, "Tasks"));
    await click(allButtons(view.container).find(b => b.textContent.includes("Pre-hearing checklist")));
    await settle(60);
    const titles = api.__calls("addTask").map(c => c.args[1].title);
    assert.equal(titles.length, 5);
    assert.equal(titles[0], "File vakalatnama");
    assert.match(view.container.textContent, /0\/5/);
    await view.unmount();
});

test("the Documents tab lists the case's documents from the server", async () => {
    api.__respond("listDocuments", { data: [{ _id: "d1", title: "Plaint draft", template_type: "civil_plaint", status: "draft" }], error: null });
    const pages = [];
    const view = await mount({ openAt: SOON.case_number, pages });
    await click(tab(view.container, "Documents"));
    assert.equal(api.__calls("listDocuments")[0].args[0], SOON._id);
    assert.match(view.container.textContent, /Plaint draft/);
    await click(buttonText(view.container, "Draft a document"));
    assert.deepEqual(pages, ["doc-automation"]);
    await view.unmount();
});

/* ── the filter bar, + Task, follow-up tasks after an outcome ────────── */

test("the bar: chips, History on the right, then search, Sort and Filter", async () => {
    const view = await mount();
    const chips = [...view.container.querySelectorAll('[role="tablist"][aria-label="Filter cases"] [role="tab"]')]
        .map(b => b.textContent.replace(/\d+$/, "").trim());
    // Closed is one of the views since 2026-10-11, not a separate History box.
    assert.deepEqual(chips, ["All", "Needs me", "New requests", "Not filed yet", "Active", "Closed"]);
    assert.ok(allButtons(view.container).some(b => /^Closed\s*1$/.test(b.textContent.trim())));
    assert.ok(view.container.querySelector('input[aria-label="Search cases"]'));
    assert.ok(allButtons(view.container).some(b => b.textContent.trim() === "Sort"));
    assert.ok(allButtons(view.container).some(b => b.textContent.trim().startsWith("Filter")));
    await view.unmount();
});

test("Needs me shows requests, cases with no date and outcomes due, nothing else", async () => {
    const OVERDUE = kase(5, "in_progress", [hearing("h5", addDays(-2), "Arguments")]);
    api.__respond("listCases", { data: { items: [LATER, SOON, NONE, SHUT, OVERDUE] }, error: null });
    const view = await mount();
    const chip = tab(view.container, "Needs me");
    assert.match(chip.textContent, /3$/, "the chip does not count request + no date + outcome due");
    await click(chip);
    const text = view.container.textContent;
    assert.match(text, /Inheritance claim/);
    assert.match(text, /CIV-2026-003/);
    assert.match(text, /CIV-2026-005/);
    assert.match(text, /Outcome due/);
    assert.doesNotMatch(text, /CIV-2026-001|CIV-2026-002/, "a case with an upcoming hearing is in Needs me");
    await view.unmount();
});

test("Sort reorders the cases: by next hearing, then Title A–Z", async () => {
    const zed = { ...kase(6, "in_progress", [hearing("h6", addDays(2), "Arguments")]), title: "Zebra lease" };
    const alpha = { ...kase(7, "in_progress", [hearing("h7", addDays(30), "Evidence")]), title: "Apple contract" };
    api.__respond("listCases", { data: { items: [zed, alpha] }, error: null });
    const view = await mount();
    // The order of the LIST: the week-in-court strip above it also names cases.
    const at = (t) => view.container.querySelector('section[aria-label="Cases"]').textContent.indexOf(t);
    assert.ok(at("Zebra lease") < at("Apple contract"), "by default the sooner hearing comes first");
    await click(allButtons(view.container).find(b => b.textContent.trim() === "Sort"));
    await click([...view.container.querySelectorAll('[role="menuitemradio"]')].find(b => b.textContent.startsWith("Title")));
    assert.ok(at("Apple contract") < at("Zebra lease"), "Title A–Z did not reorder");
    assert.equal(view.container.querySelector('[role="menu"]'), null, "the menu stayed open after choosing");
    await view.unmount();
});

test("Filter: every type and province as tiles with counts; choices apply only on Apply", async () => {
    const fam = { ...kase(8, "open"), title: "Custody matter", case_type: "family" };
    api.__respond("listCases", { data: { items: [SOON, fam] }, error: null });
    const view = await mount();
    const filterBtn = () => allButtons(view.container).find(b => b.textContent.trim().startsWith("Filter"));
    const panel = () => view.container.querySelector("[data-filter-panel]");
    const press = (label) => click([...panel().querySelectorAll("button")].find(b => b.textContent.trim() === label));
    await click(filterBtn());
    const keys = (group) => [...panel().querySelectorAll(`[role="group"][aria-label="${group}"] [data-option]`)].map(b => b.getAttribute("data-option"));
    assert.deepEqual(keys("Case type"), ["civil", "criminal", "constitutional", "family"], "Civil, Criminal, then Constitutional, Family");
    assert.deepEqual(keys("Province"), ["punjab", "sindh", "kpk", "balochistan", "federal"]);
    const tile = (k) => panel().querySelector(`[data-option="${k}"]`);
    assert.match(tile("family").textContent, /Family2$/, "Family counts the request and the case");
    assert.match(tile("sindh").textContent, /Sindh0$/);
    assert.equal(tile("civil").style.height, "36px", "tiles are compact");
    assert.equal(panel().querySelector("[data-option-grid]").style.gridTemplateColumns, "repeat(2, minmax(max-content, 1fr))", "two equal columns");
    assert.match(tile("kpk").textContent, /^KPK\d+$/, "KPK, short");
    assert.equal(tile("kpk").getAttribute("title"), "Khyber Pakhtunkhwa");
    assert.match(tile("federal").textContent, /^Federal \/ Islamabad\d+$/);
    assert.equal(tile("federal").style.gridColumn, "1 / -1", "Federal / Islamabad takes the whole row");
    assert.match(panel().textContent, /Showing 3 of 3 results/);

    await click(tile("family"));
    assert.equal(tile("family").getAttribute("aria-checked"), "true");
    assert.match(panel().textContent, /1 selected/);
    assert.match(panel().textContent, /Showing 2 of 3 results/, "the preview counts the draft");
    assert.match(view.container.textContent, /CIV-2026-001/, "the list changed before Apply");

    await press("Apply");
    assert.equal(panel(), null, "Apply did not close the panel");
    assert.doesNotMatch(view.container.textContent, /CIV-2026-001/);
    assert.match(view.container.textContent, /Custody matter/);
    assert.match(filterBtn().textContent, /1/);

    // A draft closed without Apply changes nothing.
    await click(filterBtn());
    await click(tile("criminal"));
    await click(filterBtn());
    assert.match(view.container.textContent, /Custody matter/, "an unapplied draft was applied");

    await click(filterBtn());
    assert.equal(tile("criminal").getAttribute("aria-checked"), "false", "the discarded draft came back");
    await press("Clear all");
    await press("Apply");
    assert.match(view.container.textContent, /CIV-2026-001/);
    await view.unmount();
});

test("the header buttons match the bar's height", async () => {
    const view = await mount();
    const exportBtn = view.container.querySelector('button[aria-label="Export cases"]');
    const newBtn = allButtons(view.container).find(b => b.textContent.trim() === "New case");
    const sortBtn = allButtons(view.container).find(b => b.textContent.trim() === "Sort");
    assert.equal(exportBtn.style.height, "44px");
    assert.equal(newBtn.style.height, "44px");
    // Sort sits in the one-line filter bar (2026-10-11), at the tab group's height.
    assert.equal(sortBtn.style.height, "44px");
    await view.unmount();
});

test("Add task opens Tasks with the new-task box focused", async () => {
    const view = await mount({ openAt: SOON.case_number });
    await click(buttonText(view.container, "Add task"));
    const input = view.container.querySelector('input[placeholder^="Add a task"]');
    assert.ok(input, "the Tasks tab did not open");
    assert.equal(document.activeElement, input);
    await view.unmount();
});

test("recording an outcome creates the ticked follow-up tasks before the next date", async () => {
    let n = 0;
    api.__respond("recordHearingOutcome", { data: SOON, error: null });
    api.__respond("addTask", (caseId, body) => ({ data: { _id: `t${++n}`, title: body.title, due: body.due, done: false }, error: null }));
    const view = await mount({ openAt: SOON.case_number });
    await click(tab(view.container, "Schedule"));
    await click(buttonText(view.container, "Record outcome"));
    const next = addDays(30);
    const field = [...view.container.querySelectorAll("label")].find(l => l.textContent.trim() === "Next hearing date (auto-schedules)").parentElement.querySelector("input");
    await type(field, next);
    // Untick one suggestion; it must not be created.
    const box = [...view.container.querySelectorAll('[role="checkbox"]')].find(b => b.textContent.includes("Update the client"));
    await click(box);
    await click(buttonText(view.container, "Record & Notify Client"));
    await settle(60);
    const calls = api.__calls("addTask").map(c => c.args[1]);
    assert.deepEqual(calls.map(c => c.title), ["Review the other side's latest filing", "Prepare for the next hearing"]);
    const fiveBefore = (() => { const d = new Date(`${next}T12:00:00Z`); d.setUTCDate(d.getUTCDate() - 5); return d.toISOString().slice(0, 10); })();
    assert.equal(calls[0].due, fiveBefore);
    assert.ok(calls.every(c => c.due < next), "a follow-up is not due before the next date");
    await view.unmount();
});

/* ── reschedule ───────────────────────────────────────────────────────── */

test("Reschedule moves an upcoming hearing and shows where it moved from", async () => {
    const newDate = addDays(12);
    api.__respond("rescheduleHearing", (caseId, hearingId, body) => ({ data: { ...SOON, hearing_dates: [
        hearing("h1", newDate, "Framing of issues", { time: body.time, reschedules: [{ from_date: `${addDays(5)}T00:00:00Z`, from_time: "10:00" }] }),
    ] }, error: null }));
    const view = await mount({ openAt: SOON.case_number });
    await click(tab(view.container, "Schedule"));
    await click(buttonText(view.container, "Reschedule"));
    assert.match(view.container.textContent, /Reschedule hearing/);
    // Nothing is sent without a date.
    assert.equal(buttonText(view.container, "Reschedule & notify client").disabled, true);

    const field = (name) => [...view.container.querySelectorAll('[role="dialog"] label')].find(l => l.textContent.trim() === name).parentElement.querySelector("input, textarea");
    await type(field("New date *"), newDate);
    await type(field("Time"), "11:30");
    await type(field("Reason (shown to the client)"), "Judge on leave");
    await click(buttonText(view.container, "Reschedule & notify client"));

    const [caseId, hearingId, body] = api.__calls("rescheduleHearing")[0].args;
    assert.equal(caseId, SOON._id);
    assert.equal(hearingId, "h1");
    assert.equal(body.date, new Date(newDate).toISOString());
    assert.equal(body.time, "11:30");
    assert.equal(body.reason, "Judge on leave");
    assert.match(view.container.textContent, /Rescheduled from/);
    await view.unmount();
});

test("a refused reschedule keeps the form open and says why", async () => {
    api.__respond("rescheduleHearing", { data: null, status: 422, error: { message: "Pick a date from today onwards" } });
    const view = await mount({ openAt: SOON.case_number });
    await click(tab(view.container, "Schedule"));
    await click(buttonText(view.container, "Reschedule"));
    const date = [...view.container.querySelectorAll("label")].find(l => l.textContent.trim() === "New date *").parentElement.querySelector("input");
    await type(date, addDays(3));
    await click(buttonText(view.container, "Reschedule & notify client"));
    assert.match(view.container.textContent, /Pick a date from today onwards/);
    assert.match(view.container.textContent, /Reschedule hearing/, "the form closed on a failure");
    await view.unmount();
});

/* ── closed cases are read-only ───────────────────────────────────────── */

test("a closed case opens read-only: no hearing, task or message controls", async () => {
    const CLOSED = kase(8, "closed", [hearing("h8", addDays(5), "Arguments")]);
    api.__respond("listCases", { data: { items: [CLOSED] }, error: null });
    const view = await mount({ openAt: CLOSED.case_number });
    const text = () => view.container.textContent;
    assert.match(text(), /This case is closed\./);
    for (const label of ["Add task", "Add hearing"]) {
        assert.equal(buttonText(view.container, label), undefined, `${label} is offered on a closed case`);
    }
    await click(tab(view.container, "Schedule"));
    for (const label of ["Schedule Hearing", "Reschedule", "Record outcome"]) {
        assert.equal(buttonText(view.container, label), undefined, `${label} is offered on a closed case`);
    }
    await click(tab(view.container, "Messages"));
    assert.equal(view.container.querySelector('input[placeholder^="Write to"]'), null, "the composer is shown on a closed case");
    assert.match(text(), /no new messages can be sent/);
    await click(tab(view.container, "Tasks"));
    assert.equal(view.container.querySelector('input[placeholder^="Add a task"]'), null);
    await view.unmount();
});

/* ── failures are said, not swallowed ─────────────────────────────────── */

test("a message that fails to send keeps the text and says why", async () => {
    api.__respond("sendMessage", { data: null, error: { message: "This case is closed, so it can no longer be changed." }, status: 409 });
    const view = await mount({ openAt: SOON.case_number });
    await click(tab(view.container, "Messages"));
    const box = view.container.querySelector('input[placeholder^="Write to"]');
    await type(box, "Please bring the deed.");
    await click(view.container.querySelector('button[aria-label="Send message"]'));
    assert.equal(view.container.querySelector('input[placeholder^="Write to"]').value, "Please bring the deed.");
    assert.match(view.container.querySelector('[role="alert"]')?.textContent || "", /can no longer be changed/);
    await view.unmount();
});

test("a task that cannot be ticked flips back and says why", async () => {
    api.__respond("listTasks", { data: [{ _id: "t1", title: "File reply", done: false }], error: null });
    api.__respond("toggleTask", { data: null, error: { message: "Task not found" }, status: 404 });
    const view = await mount({ openAt: SOON.case_number });
    await click(tab(view.container, "Tasks"));
    const box = view.container.querySelector('[role="checkbox"][aria-label="File reply"]');
    await click(box);
    await settle(40);
    assert.equal(view.container.querySelector('[role="checkbox"][aria-label="File reply"]').getAttribute("aria-checked"), "false");
    assert.match(view.container.textContent, /Task not found/);
    await view.unmount();
});

test("cases past the first page of 50 are listed too", async () => {
    const extra = { ...LATER, _id: "665f00000000000000000099", case_number: "CIV-2026-099", title: "Page two matter" };
    api.__respond("listCases", ({ page } = {}) => (page === 2
        ? { data: { items: [extra], total: 5, pages: 2 }, error: null }
        : { data: { items: [LATER, SOON, NONE, SHUT], total: 5, pages: 2 }, error: null }));
    const view = await mount();
    assert.match(view.container.textContent, /Page two matter/);
    await view.unmount();
});

/* ── + New case: a walk-in client case ────────────────────────────────── */

async function openNewCase(view) {
    await click(allButtons(view.container).find(b => b.textContent.trim() === "New case"));
    const form = (ph) => view.container.querySelector(`input[placeholder="${ph}"]`);
    return form;
}

test("New case validates, creates through the API, then opens the new case", async () => {
    const MADE = { _id: "665f00000000000000000077", case_number: "ATT-2026-ABCD1234", title: "Rent recovery", client_id: null,
        walk_in: true, client_name: "Muhammad Aslam", client_phone: "+92 300 1234567", province: "punjab", case_type: "civil",
        status: "in_progress", hearing_dates: [] };
    let created = false;
    api.__respond("createWalkInCase", (body) => { created = true; return { data: { ...MADE, title: body.title }, error: null }; });
    api.__respond("listCases", () => ({ data: { items: created ? [LATER, SOON, NONE, SHUT, MADE] : [LATER, SOON, NONE, SHUT] }, error: null }));
    const view = await mount();
    const field = await openNewCase(view);
    await click(allButtons(view.container).find(b => b.textContent.trim() === "Create case"));
    assert.match(view.container.querySelector('[role="alert"]')?.textContent || "", /title/i);
    assert.equal(api.__calls("createWalkInCase").length, 0, "an empty form was sent");

    await type(field("e.g. Rent recovery — Mr. Aslam"), "Rent recovery");
    await type(field("Full name"), "Muhammad Aslam");
    await type(field("+92 300 1234567"), "+92 300 1234567");
    await type(field("e.g. Civil Court Lahore"), "Civil Court Lahore");
    await click(allButtons(view.container).find(b => b.textContent.trim() === "Create case"));
    await settle(60);
    assert.deepEqual(api.__calls("createWalkInCase")[0].args[0], {
        title: "Rent recovery", case_type: "civil", province: "punjab", client_name: "Muhammad Aslam",
        client_phone: "+92 300 1234567", court: "Civil Court Lahore", court_case_number: null, description: "",
    });
    assert.ok(view.container.querySelector('[aria-label="Case sections"]'), "the new case did not open");
    assert.match(view.container.textContent, /ATT-2026-ABCD1234/);

    await click(tab(view.container, "Messages"));
    const note = view.container.querySelector("[data-walk-in-note]");
    assert.ok(note, "a walk-in case offered a message box");
    assert.match(note.textContent, /\+92 300 1234567/);
    assert.equal(view.container.querySelector('input[placeholder^="Write to"]'), null);
    await view.unmount();
});

test("a refused New case keeps the form and shows the server's reason", async () => {
    api.__respond("createWalkInCase", { data: null, error: { detail: [{ loc: ["body", "client_phone"], msg: "String should match pattern" }] }, status: 422 });
    const view = await mount();
    const field = await openNewCase(view);
    await type(field("e.g. Rent recovery — Mr. Aslam"), "Rent recovery");
    await type(field("Full name"), "Muhammad Aslam");
    await click(allButtons(view.container).find(b => b.textContent.trim() === "Create case"));
    await settle(40);
    assert.match(view.container.querySelector('[role="alert"]').textContent, /client_phone: String should match pattern/);
    assert.ok(allButtons(view.container).some(b => b.textContent.trim() === "Create case"), "the form closed on failure");
    await view.unmount();
});

/* ── Cases Workspace v2 layout (2026-10-09) ─────────────────────────────── */

test("This week in court: seven days from today, each hearing on its day, and a click opens the case", async () => {
    const pages = [];
    const view = await mount({ pages });
    const week = view.container.querySelector("[data-court-week]");
    assert.ok(week, "no week strip");
    const days = [...week.querySelectorAll("[data-day]")];
    assert.equal(days.length, 7);
    assert.equal(days[0].getAttribute("data-day"), pktToday(), "the week does not start today");
    assert.match(days[0].textContent, /^Today/);
    // SOON's hearing is in 5 days; LATER's (40 days) is not this week.
    assert.match(week.querySelector(`[data-day="${addDays(5)}"]`).textContent, /Matter 1/);
    assert.doesNotMatch(week.textContent, /Matter 2/);
    assert.match(week.textContent, /1 hearing in the next 7 days/);
    await click(buttonText(week, "Open cause list →"));
    assert.deepEqual(pages, ["causelist"]);
    await click([...week.querySelectorAll("button")].find(b => b.textContent.includes("Matter 1")));
    assert.ok(view.container.querySelector('[aria-label="Case sections"]'), "the hearing did not open its case");
    await view.unmount();
});

test("the week strip folds away and stays folded", async () => {
    localStorage.removeItem("attorney:lawyer-cases-week-open");
    let view = await mount();
    await click(buttonText(view.container, "Hide"));
    assert.equal(view.container.querySelectorAll("[data-day]").length, 0);
    await view.unmount();
    view = await mount();
    assert.equal(view.container.querySelectorAll("[data-day]").length, 0, "the fold was not remembered");
    await click(buttonText(view.container, "Show"));
    assert.equal(view.container.querySelectorAll("[data-day]").length, 7);
    await view.unmount();
    localStorage.removeItem("attorney:lawyer-cases-week-open");
});

test("Ctrl K focuses the one search; Enter opens the case when the search leaves exactly one", async () => {
    const view = await mount();
    const input = view.container.querySelector('input[aria-label="Search cases"]');
    await act(async () => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true })); });
    assert.equal(document.activeElement, input, "Ctrl K did not focus the search");
    assert.equal(view.container.querySelectorAll('input[aria-label="Search cases"]').length, 1, "more than one case search");
    await type(input, "client 2");
    await act(async () => { input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
    await settle();
    assert.ok(view.container.querySelector('[aria-label="Case sections"]'), "Enter did not open the only match");
    await view.unmount();
});

test("the Documents tab shows what the client sent on this case, opened at the revision sent", async () => {
    api.__respond("reviewQueueV2", { data: { items: [
        { id: "cd1", title: "Plaint — recovery", case_id: SOON._id, review_status: "returned", client_name: "Ayesha",
          submitted_version: 2, reviewed_revision_id: "rev-2", reviewed_pdf_sha256: "hash-2" },
        { id: "other", title: "Some other case's notice", case_id: "elsewhere", review_status: "submitted" },
        { id: "pend", title: "Notice waiting", case_id: SOON._id, review_status: "submitted", client_name: "Ayesha",
          submitted_version: 1, submitted_revision_id: "rev-p", submitted_pdf_sha256: "hash-p" },
    ], next_cursor: null }, error: null });
    api.__respond("fetchRevisionPreview", { data: { url: "blob:x" }, error: null });
    const view = await mount({ openAt: SOON.case_number });
    await click(tab(view.container, "Documents"));
    const row = view.container.querySelector('[data-case-doc="cd1"]');
    assert.ok(row, "the client's document is not listed on its case");
    assert.match(row.textContent, /Sent by Ayesha · v2/);
    assert.match(row.textContent, /Returned/);
    assert.equal(view.container.querySelector('[data-case-doc="other"]'), null, "another case's document leaked in");
    const pending = view.container.querySelector('[data-case-doc="pend"]');
    assert.match(pending.textContent, /Waiting for you/);
    assert.equal([...pending.querySelectorAll("button")].find(b => b.textContent.trim() === "Open").disabled, false,
        "a document waiting for the lawyer cannot be opened");
    const realOpen = window.open; window.open = () => ({});
    await click([...row.querySelectorAll("button")].find(b => b.textContent.trim() === "Open"));
    window.open = realOpen;
    const [id, opts] = api.__calls("fetchRevisionPreview")[0].args;
    assert.equal(id, "cd1");
    assert.deepEqual(opts, { revisionId: "rev-2", expectedPdfSha256: "hash-2" });
    await view.unmount();
});

test("Your files: listed for this case, uploaded through the API, and marked as private", async () => {
    api.__respond("listCaseFiles", { data: { items: [
        { id: "f1", name: "summons.pdf", content_type: "application/pdf", size: 2048, created_at: "2026-10-11T10:00:00Z" },
    ] }, error: null });
    api.__respond("uploadCaseFile", { data: { id: "f2", name: "order.png", content_type: "image/png", size: 4096 }, error: null, status: 201 });
    const view = await mount({ openAt: SOON.case_number });
    await click(tab(view.container, "Documents"));
    assert.equal(api.__calls("listCaseFiles")[0].args[0], SOON._id);
    const box = view.container.querySelector("[data-case-files]");
    assert.match(box.textContent, /Only you can see these/);
    assert.ok(box.querySelector('[data-case-file="f1"]'));
    const input = box.querySelector('input[type="file"]');
    const file = new File(["\x89PNG"], "order.png", { type: "image/png" });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    await act(async () => { input.dispatchEvent(new Event("change", { bubbles: true })); });
    await new Promise(r => setTimeout(r, 30));
    const [caseId, sent] = api.__calls("uploadCaseFile")[0].args;
    assert.equal(caseId, SOON._id);
    assert.equal(sent.name, "order.png");
    assert.ok(view.container.querySelector('[data-case-file="f2"]'), "the uploaded file is not listed");
    await view.unmount();
});
