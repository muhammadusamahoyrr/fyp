/* LD-02: the case workspace's hearing forms, driven through the real UI.
 *
 * WHAT WAS WRONG. The Schedule Hearing and Record Outcome forms called the
 * shared `Input` as if `onChange` handed back the typed value. It hands back
 * the DOM event, and it has no `label` prop. So the form state held an event
 * object, `new Date(event).toISOString()` threw, and nothing was saved; the
 * outcome modal threw after `setOBusy(true)` and stuck on "Saving…"; and the
 * field labels never rendered.
 *
 * These tests open a case, go to its hearings, type into the fields the way a
 * user does, and check what reaches the API.
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
const h = React.createElement;

const settle = (ms = 30) => act(async () => { await new Promise(r => setTimeout(r, ms)); });

function Host() {
    const [openCaseId, setOpenCaseId] = useState(null);
    const [docs, setDocs] = useState({});
    return h(CaseCtx.Provider, {
        value: { openCaseId, setOpenCaseId, activeCase: null, setActiveCase: () => {},
                 docs, setDocs, setPage: () => {} },
    }, h(CasesPage));
}

async function mount() {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(h(Host)); });
    await settle();
    // Queries run from <body>: the page's dialogs render there (a portal), not
    // inside the page's own container.
    return { container: document.body, unmount: async () => { await act(async () => root.unmount()); container.remove(); } };
}

const buttonWith = (root, text) => [...root.querySelectorAll("button")]
    .find(b => b.textContent.includes(text));

async function click(el) {
    assert.ok(el, "element to click was not found");
    await act(async () => { el.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
}

// The input that belongs to a visible label: proves the label renders, too.
function fieldFor(root, labelText) {
    const label = [...root.querySelectorAll("label")].find(l => l.textContent.trim() === labelText);
    assert.ok(label, `label "${labelText}" is not rendered`);
    return label.parentElement.querySelector("input");
}

async function type(input, value) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    await act(async () => {
        setter.call(input, value);
        input.dispatchEvent(new Event("input", { bubbles: true }));
    });
}

const CASE = {
    _id: "665f00000000000000000001", case_number: "CIV-2026-001", title: "Rent dispute",
    client_name: "Ayesha", province: "punjab", case_type: "civil", status: "in_progress",
    hearing_dates: [{ _id: "h1", date: "2026-10-20T00:00:00Z", time: "10:00",
                      court: "Civil Court Lahore", judge: "", purpose: "Framing of issues" }],
};

async function openHearings() {
    const view = await mount();
    await click(view.container.querySelector('button[aria-label="Open case"]'));
    // Hearings live on the workspace's Schedule tab.
    await click([...view.container.querySelectorAll('[role="tab"]')].find(b => b.textContent.startsWith("Schedule")));
    assert.ok(buttonWith(view.container, "Schedule Hearing"), "the hearings view did not open");
    return view;
}

test.beforeEach(() => {
    api.__reset();
    api.__respond("listCases", { data: { items: [CASE] }, error: null });
    api.__respond("listEngagements", { data: [], error: null });
});

test("Schedule Hearing sends the typed date, court and purpose", async () => {
    api.__respond("addHearing", { data: CASE, error: null });
    const view = await openHearings();
    // The schedule form sits in the Schedule tab itself (2026-10-09).

    await type(fieldFor(view.container, "Date *"), "2026-11-20");
    await type(fieldFor(view.container, "Court *"), "Lahore High Court");
    await type(fieldFor(view.container, "Purpose / Agenda *"), "Evidence");
    await click([...view.container.querySelectorAll("button")]
        .find(b => b.textContent.trim() === "Schedule Hearing"));

    const calls = api.__calls("addHearing");
    assert.equal(calls.length, 1, "the hearing was not sent to the server");
    const [caseId, body] = calls[0].args;
    assert.equal(caseId, CASE._id);
    assert.equal(body.date, new Date("2026-11-20").toISOString());
    assert.equal(body.court, "Lahore High Court");
    assert.equal(body.purpose, "Evidence");
    await view.unmount();
});

test("Record Outcome with a next date is sent and the button does not stick on Saving…", async () => {
    api.__respond("recordHearingOutcome", { data: CASE, error: null });
    const view = await openHearings();
    await click(buttonWith(view.container, "Record outcome"));

    assert.ok(fieldFor(view.container, "Time"), "the Time label is not rendered");
    await type(fieldFor(view.container, "Next hearing date (auto-schedules)"), "2026-12-01");
    await click(buttonWith(view.container, "Record & Notify Client"));

    const calls = api.__calls("recordHearingOutcome");
    assert.equal(calls.length, 1, "the outcome was not sent to the server");
    const [caseId, hearingId, body] = calls[0].args;
    assert.equal(caseId, CASE._id);
    assert.equal(hearingId, "h1");
    assert.equal(body.next_date, new Date("2026-12-01").toISOString());
    assert.equal(buttonWith(view.container, "Saving…"), undefined, "the outcome modal stuck on Saving…");
    await view.unmount();
});
