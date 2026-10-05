/* Phase 2.4: case hearings follow the server, however the case was opened.
 *
 * WHAT WAS WRONG.
 *   * Hearings were seeded only by the Cases list's own Open handler. The
 *     Dashboard and the active-case banner open a case by setting openCaseId
 *     directly, so those workspaces showed no hearings at all (and, while the
 *     case list loaded, a blank page).
 *   * A newly scheduled hearing, and the next hearing an outcome auto-schedules,
 *     were added locally without the server's `_id`, so "Add Outcome" on them
 *     was refused ("predates outcome tracking") until a full reload.
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

const hearing = (id, date, purpose, extra = {}) =>
    ({ _id: id, date: `${date}T00:00:00Z`, time: "10:00", court: "Civil Court Lahore", judge: "", purpose, ...extra });
const CASE = {
    _id: "665f00000000000000000001", case_number: "CIV-2026-001", title: "Rent dispute",
    client_name: "Ayesha", province: "punjab", case_type: "civil", status: "in_progress",
    hearing_dates: [hearing("h1", "2026-10-20", "Framing of issues")],
};

function Host({ openAt = null }) {
    const [openCaseId, setOpenCaseId] = useState(openAt);
    const [docs, setDocs] = useState({});
    return h(CaseCtx.Provider, {
        value: { openCaseId, setOpenCaseId, activeCase: null, setActiveCase: () => {}, docs, setDocs, setPage: () => {} },
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

const buttons = (root, text) => [...root.querySelectorAll("button")].filter(b => b.textContent.includes(text));
async function click(el) {
    assert.ok(el, "element to click was not found");
    await act(async () => { el.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
}
function fieldFor(root, labelText) {
    const label = [...root.querySelectorAll("label")].find(l => l.textContent.trim() === labelText);
    assert.ok(label, `label "${labelText}" is not rendered`);
    return label.parentElement.querySelector("input");
}
async function type(input, value) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    await act(async () => { setter.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
}
const goToHearings = (root) => click(buttons(root, "Manage →")[0]);
// Through the list's own Open button, which seeded hearings even before the
// fix: the id tests below must fail on the missing `_id`, not on seeding.
async function openFromList(root) { await click(buttons(root, "Open →")[0]); await goToHearings(root); }
const outcomeModalOpen = (root) => root.textContent.includes("Record Hearing Outcome");

test.beforeEach(() => {
    api.__reset();
    api.__respond("listCases", { data: { items: [CASE] }, error: null });
    api.__respond("listEngagements", { data: [], error: null });
});

test("a case opened from outside the list (Dashboard, banner) shows its hearings", async () => {
    const view = await mount({ openAt: CASE.case_number });
    await goToHearings(view.container);
    assert.match(view.container.textContent, /Framing of issues/, "the case's hearings were not seeded");
    await view.unmount();
});

test("while the case list loads, an externally opened case says it is loading", async () => {
    api.__respond("listCases", () => new Promise(() => {}));
    const view = await mount({ openAt: CASE.case_number });
    assert.match(view.container.textContent, /Loading case/);
    await view.unmount();
});

test("a newly scheduled hearing carries the server's id, so Add Outcome works at once", async () => {
    api.__respond("addHearing", { data: { ...CASE, hearing_dates: [
        ...CASE.hearing_dates, hearing("h2", "2026-11-20", "Evidence")] }, error: null });
    const view = await mount();
    await openFromList(view.container);
    await click(buttons(view.container, "+ Schedule Hearing")[0]);
    await type(fieldFor(view.container, "Date *"), "2026-11-20");
    await type(fieldFor(view.container, "Purpose / Agenda *"), "Evidence");
    await click(buttons(view.container, "Schedule Hearing").find(b => b.textContent.trim() === "Schedule Hearing"));

    // Hearings are listed newest first, so the new one's button comes first.
    const add = buttons(view.container, "Add Outcome");
    assert.equal(add.length, 2);
    await click(add[0]);
    assert.ok(outcomeModalOpen(view.container), "Add Outcome was refused for the new hearing");
    await view.unmount();
});

test("the next hearing an outcome auto-schedules carries the server's id", async () => {
    api.__respond("recordHearingOutcome", { data: { ...CASE, hearing_dates: [
        hearing("h1", "2026-10-20", "Framing of issues", { outcome: "adjourned" }),
        hearing("h3", "2026-12-01", "Next hearing")] }, error: null });
    const view = await mount();
    await openFromList(view.container);
    await click(buttons(view.container, "Add Outcome")[0]);
    await type(fieldFor(view.container, "Next hearing date (auto-schedules)"), "2026-12-01");
    await click(buttons(view.container, "Record & Notify Client")[0]);

    const add = buttons(view.container, "Add Outcome");
    assert.equal(add.length, 1, "the auto-scheduled hearing is missing");
    await click(add[0]);
    assert.ok(outcomeModalOpen(view.container), "Add Outcome was refused for the auto-scheduled hearing");
    await view.unmount();
});
