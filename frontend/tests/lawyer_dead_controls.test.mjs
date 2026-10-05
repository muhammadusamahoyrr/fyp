/* Phase 3: controls on the lawyer dashboard either work or are not shown.
 *
 * Each test here names a control that used to render with no handler, or with
 * a handler that faked its result, and asserts the page no longer offers it
 * (or that it now does what it says). Approved rule: unsupported controls are
 * hidden or removed, never labelled "coming soon".
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
                    "getComputedStyle", "localStorage", "sessionStorage", "requestAnimationFrame",
                    "cancelAnimationFrame"]) {
    if (dom.window[name] !== undefined) define(name, dom.window[name]);
}
if (!dom.window.HTMLElement.prototype.scrollIntoView) dom.window.HTMLElement.prototype.scrollIntoView = () => {};
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { AuthProvider } = await import("../src/context/AuthContext.jsx");
const { ToastCtx } = await import("../src/components/shared/Toast.jsx");
const { CaseCtx, NotifCtx } = await import("../src/components/lawyer/theme.js");
const h = React.createElement;

const settle = (ms = 40) => act(async () => { await new Promise(r => setTimeout(r, ms)); });

// Every lawyer page mounts inside the same providers the dashboard shell gives it.
export async function mountPage(Page, { caseCtx = {}, notif = () => {} } = {}) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(AuthProvider, null,
            h(ToastCtx.Provider, { value: { show: () => {} } },
                h(NotifCtx.Provider, { value: { addNotif: notif } },
                    h(CaseCtx.Provider, { value: { setOpenCaseId: () => {}, setActiveCase: () => {},
                                                   setPage: () => {}, docs: {}, setDocs: () => {}, ...caseCtx } },
                        h(Page))))));
    });
    await settle(120);
    return { container, unmount: async () => { await act(async () => root.unmount()); container.remove(); } };
}
const buttonTexts = (root) => [...root.querySelectorAll("button")].map(b => b.textContent.trim());

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer", full_name: "Asad Ali", lawyer_profile: {} }, error: null });
});

/* ── 3.2 Settings ─────────────────────────────────────────────────────── */

test("3.2 Settings shows no notification preferences it cannot store", async () => {
    const { SettingsPage } = await import("../src/components/lawyer/SettingsPage.jsx");
    const view = await mountPage(SettingsPage);
    assert.equal(view.container.querySelectorAll('input[type="checkbox"]').length, 0);
    assert.doesNotMatch(view.container.textContent, /Email for new appointments|Hearing date reminders/);
    await view.unmount();
});

/* ── 3.3 Documents ────────────────────────────────────────────────────── */

function serveQueue() {
    api.__respond("reviewQueueV2", {
        data: { items: [{ id: "d1", title: "Plaint", client_name: "Ayesha", case_id: "c1",
                          review_status: "submitted", submitted_revision_id: "r1" }],
                next_cursor: null, status: "all",
                counts: { all: 1, submitted: 1, approved: 0, returned: 0, rejected: 0 } },
        error: null, status: 200,
    });
}

test("3.3 Documents: no Upload button; AI Generate opens the Draft Generator", async () => {
    serveQueue();
    const { DocWorkflowApp } = await import("../src/components/lawyer/DocumentsPage.jsx");
    const pages = [];
    const view = await mountPage(DocWorkflowApp, { caseCtx: { setPage: p => pages.push(p) } });
    assert.ok(!buttonTexts(view.container).some(t => /Upload Document/.test(t)));
    const gen = [...view.container.querySelectorAll("button")].find(b => b.textContent.includes("AI Generate"));
    await act(async () => { gen.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    assert.deepEqual(pages, ["doc-automation"]);
    await view.unmount();
});

test("3.3 Documents review screen: no inert Request-changes toggle or unsent notes box", async () => {
    serveQueue();
    const { DocWorkflowApp } = await import("../src/components/lawyer/DocumentsPage.jsx");
    const view = await mountPage(DocWorkflowApp);
    const open = [...view.container.querySelectorAll("button")].find(b => b.textContent.includes("Review Now"));
    await act(async () => { open.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
    assert.ok(!buttonTexts(view.container).some(t => /Request changes/.test(t)));
    assert.equal(view.container.querySelector('textarea[placeholder="Add internal notes for this review..."]'), null);
    // The decision screen's notes, which ARE sent, are still reachable.
    assert.ok(buttonTexts(view.container).some(t => /Proceed to Decision/.test(t)));
    await view.unmount();
});

/* ── 3.4 Appointments ─────────────────────────────────────────────────── */

test("3.4 Appointments: no View Details button that does nothing", async () => {
    const when = new Date(Date.now() + 72 * 36e5);
    when.setUTCMinutes(0, 0, 0);
    const inPerson = { id: "a1", scheduled_at: when.toISOString(),
        end_at: new Date(when.getTime() + 36e5).toISOString(), duration_minutes: 60,
        status: "confirmed", mode: "in_person", client_name: "Client A", purpose: "Consultation",
        notes: null, case_id: null, schedule_version: 1 };
    api.__respond("listAppointments", { data: { items: [inPerson], total: 1, page: 1, page_size: 25, pages: 1 },
                                        error: null, status: 200 });
    api.__respond("listPendingOutcomes", { data: { items: [], next_cursor: null, cutoff: "2026-10-01T00:00:00Z" },
                                           error: null, status: 200 });
    api.__respond("getMyWorkingHours", { data: { lawyer_id: "l1", configured: false, enforced: false,
        timezone: "Asia/Karachi", working_hours: [], exceptions: [], updated_at: null }, error: null, status: 200 });
    const { AppointmentsPage } = await import("../src/components/lawyer/AppointmentsPage.jsx");
    const view = await mountPage(AppointmentsPage);
    assert.match(view.container.textContent, /Client A/, "the appointment did not render");
    assert.ok(!buttonTexts(view.container).some(t => /View Details/.test(t)));
    await view.unmount();
});

/* ── 3.5 AI Assistant ─────────────────────────────────────────────────── */

test("3.5 AI Assistant: the clock reopens history; inert globe, mic, Pro and Upgrade are gone", async () => {
    api.__respond("listCases", { data: { items: [] }, error: null });
    api.__respond("listResearchConversations", { data: { conversations: [], next_cursor: null }, error: null });
    api.__respond("createResearchConversation", { data: { session_id: "s1" }, error: null });
    const { AILegalPage } = await import("../src/components/lawyer/AILegalPage.jsx");
    const view = await mountPage(AILegalPage, { caseCtx: { activeCase: null } });
    const texts = buttonTexts(view.container);
    assert.ok(!texts.includes("Upgrade Plan"));
    assert.ok(!texts.includes("Search"), "the inert Search globe is still offered");
    assert.doesNotMatch(view.container.textContent, /\bPro\b/);

    const sidebar = () => view.container.querySelector('input[placeholder="Search research"]').closest('div[style*="width"]');
    const collapse = [...view.container.querySelectorAll("button")].find(b => b.textContent.trim() === "Collapse");
    await act(async () => { collapse.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
    assert.equal(sidebar().style.width, "0px");
    const clock = view.container.querySelector('button[aria-label="Conversation history"]');
    assert.ok(clock, "no history button");
    await act(async () => { clock.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
    assert.equal(sidebar().style.width, "200px");
    await view.unmount();
});

/* ── 3.6 Draft Generator ──────────────────────────────────────────────── */

test("3.6 Draft Generator: no Insert Link button wired to nothing", async () => {
    // Its toolbar renders inside the editor, behind a template choice; the
    // guard is on the source, which is where the no-op handler lived.
    const { readFileSync } = await import("node:fs");
    const src = readFileSync(new URL("../src/components/lawyer/DocAutomationPage.jsx", import.meta.url), "utf8");
    assert.doesNotMatch(src, /label="Insert Link"/);
    assert.doesNotMatch(src, /onClick=\{\(\) => \{ \}\}/, "a toolbar button with an empty handler remains");
});
