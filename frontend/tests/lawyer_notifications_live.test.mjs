/* Lawyer notifications lead somewhere, and open pages hear about them.
 *
 * WHAT WAS WRONG.
 *   * Clicking a notification navigated only when it carried `payload.route`
 *     (two dispute notices). Appointments, hearings, messages and engagements
 *     marked themselves read and went nowhere.
 *   * Icons and the sidebar badge were keyed on types the server never sends
 *     ("message", "hearing"); case messages arrive as "case_message", so the
 *     badge never showed (it was also a constant 0).
 *   * The socket was opened once. Once it closed, nothing arrived until a
 *     manual reload, and open pages never refreshed on a notification.
 *   * Notices made in the browser had made-up ids that were sent to the
 *     server as "read" on click.
 *   * A notification names a case by its database id; the Cases page opened
 *     cases by case number, so it would have shown "Loading case…" for ever.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/lawyer" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "HTMLInputElement", "Element", "Node", "Event",
                    "CustomEvent", "EventTarget", "MouseEvent", "KeyboardEvent", "MutationObserver",
                    "getComputedStyle", "localStorage", "sessionStorage"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);
dom.window.HTMLElement.prototype.scrollIntoView = function () {};
dom.window.matchMedia = dom.window.matchMedia || (() => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }));
define("matchMedia", dom.window.matchMedia);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { AuthProvider } = await import("../src/context/AuthContext.jsx");
const { default: App } = await import("../src/components/lawyer/App.jsx");
const nt = await import("../src/lib/notificationTarget.js");
const h = React.createElement;

const settle = (ms = 60) => act(async () => { await new Promise(r => setTimeout(r, ms)); });

const CASE = { _id: "665f00000000000000000001", case_number: "CIV-2026-001", title: "Rent dispute",
    client_id: "cl1", client_name: "Bilal", province: "punjab", case_type: "civil", status: "in_progress",
    hearing_dates: [] };
const NOTE = (id, type, payload = {}, read = false) => ({ _id: id, type, title: `${type} title ${id}`, body: "", payload, read,
    created_at: new Date().toISOString() });

let sockets;
function fakeSocket() {
    const s = new dom.window.EventTarget();
    s.close = () => {};
    return s;
}

function serve(notes) {
    api.__reset();
    sockets = [];
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer", full_name: "Asad Ali",
        lawyer_profile: { bar_number: "LHR-1234", specializations: ["civil"] } }, error: null });
    api.__respond("getNotifications", { data: notes, error: null });
    api.__respond("markNotificationRead", { data: {}, error: null });
    api.__respond("openNotificationSocket", (onMessage) => {
        const s = fakeSocket();
        s.onMessage = onMessage;
        sockets.push(s);
        return s;
    });
    api.__respond("listCases", { data: { items: [CASE], total: 1, pages: 1 }, error: null });
    api.__respond("listEngagements", { data: [], error: null });
    api.__respond("listAppointments", { data: { items: [], total: 0, pages: 0 }, error: null });
    api.__respond("listMessages", { data: [], error: null });
    api.__respond("listTasks", { data: [], error: null });
}

async function mount(initialPage = "dashboard") {
    try { localStorage.setItem("lawyer_onboarded", "1"); } catch {}
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(h(AuthProvider, null, h(App, { initialPage }))); });
    await settle(120);
    const click = async (el) => { await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); }); await settle(); };
    return {
        container,
        click,
        text: () => container.textContent,
        openBell: async () => click(container.querySelector('button[title="Notifications"]')),
        row: (title) => [...container.querySelectorAll("div")].find(d => d.style.cursor === "pointer" && d.textContent.startsWith(title)),
        navBadge: (label) => {
            const btn = [...container.querySelectorAll("button")].find(b => b.textContent.startsWith(label));
            return btn ? btn.textContent.slice(label.length) : null;
        },
        unmount: () => act(async () => root.unmount()).then(() => container.remove()),
    };
}

test.after(() => dom.window.close());

test("every server type has a destination page and a category", () => {
    assert.deepEqual(nt.lawyerNotificationTarget("case_message", { case_id: "x" }), { page: "cases", caseId: "x" });
    assert.deepEqual(nt.lawyerNotificationTarget("hearing_scheduled", { case_id: "x" }), { page: "cases", caseId: "x" });
    assert.deepEqual(nt.lawyerNotificationTarget("hearing_reminder", { case_id: "x" }), { page: "cases", caseId: "x" });
    assert.equal(nt.notificationCategory("hearing_reminder"), "hearing");
    assert.deepEqual(nt.lawyerNotificationTarget("engagement_requested", { case_id: "x", engagement_id: "e" }), { page: "cases", caseId: "x" });
    assert.equal(nt.lawyerNotificationTarget("appointment_booked", { appointment_id: "a" }).page, "appointments");
    assert.equal(nt.lawyerNotificationTarget("document_submitted").page, "documents");
    assert.equal(nt.lawyerNotificationTarget("review_request_submitted").page, "review-queue");
    assert.equal(nt.lawyerNotificationTarget("dispute_assigned").page, "overseas-disputes");
    assert.equal(nt.lawyerNotificationTarget("something_new"), null);
    assert.equal(nt.notificationCategory("case_message"), "message");
    assert.equal(nt.notificationCategory("appointment_no_show"), "appointment");
    assert.equal(nt.notificationCategory("hearing_scheduled"), "hearing");
    assert.equal(nt.reconnectDelay(0), 1000);
    assert.equal(nt.reconnectDelay(10), 30000);
});

test("clicking a message notification opens that case, found by its database id, and marks it read", async () => {
    serve([NOTE("n1", "case_message", { case_id: CASE._id })]);
    const ui = await mount();
    await ui.openBell();
    await ui.click(ui.row("case_message title n1"));
    await settle(120);
    assert.ok(ui.container.querySelector('[aria-label="Case sections"]'), "the case workspace did not open");
    assert.match(ui.text(), /CIV-2026-001/);
    assert.doesNotMatch(ui.text(), /Loading case…/);
    assert.deepEqual(api.__calls("markNotificationRead").map(c => c.args[0]), ["n1"]);
    await ui.unmount();
});

test("clicking an appointment notification opens Appointments", async () => {
    serve([NOTE("n2", "appointment_booked", { appointment_id: "a1" })]);
    const ui = await mount();
    const before = api.__calls("listAppointments").length;
    await ui.openBell();
    await ui.click(ui.row("appointment_booked title n2"));
    await settle(120);
    assert.ok(api.__calls("listAppointments").length > before, "the Appointments page did not load");
    await ui.unmount();
});

test("the sidebar badges count unread case messages and booking requests", async () => {
    serve([
        NOTE("m1", "case_message", { case_id: CASE._id }), NOTE("m2", "case_message", { case_id: CASE._id }),
        NOTE("m3", "case_message", { case_id: CASE._id }, true), NOTE("a1", "appointment_booked"),
    ]);
    const ui = await mount();
    assert.equal(ui.navBadge("Cases"), "2");
    assert.equal(ui.navBadge("Appointments"), "1");
    await ui.unmount();
});

test("a closed socket reconnects and catches up on what was missed", async () => {
    serve([]);
    const ui = await mount();
    assert.equal(sockets.length, 1);
    const reads = api.__calls("getNotifications").length;
    await act(async () => { sockets[0].dispatchEvent(new dom.window.Event("close")); });
    await settle(1200);
    assert.equal(sockets.length, 2, "no reconnect after the socket closed");
    await act(async () => { sockets[1].dispatchEvent(new dom.window.Event("open")); });
    await settle();
    assert.ok(api.__calls("getNotifications").length > reads, "missed notifications were not re-read");
    await ui.unmount();
});

test("a live booking refreshes the open Appointments page", async () => {
    serve([]);
    const ui = await mount("appointments");
    const before = api.__calls("listAppointments").length;
    await act(async () => { sockets[0].onMessage({ type: "notification", notification: NOTE("live1", "appointment_booked", { appointment_id: "a9" }) }); });
    await settle(120);
    assert.ok(api.__calls("listAppointments").length > before, "the page did not re-read its appointments");
    await ui.unmount();
});

test("a live message for the open case is shown without leaving the case", async () => {
    serve([NOTE("n1", "case_message", { case_id: CASE._id })]);
    const ui = await mount();
    await ui.openBell();
    await ui.click(ui.row("case_message title n1"));
    await settle(120);
    const before = api.__calls("listMessages").length;
    await act(async () => { sockets[0].onMessage({ type: "notification", notification: NOTE("live2", "case_message", { case_id: CASE._id }) }); });
    await settle(80);
    assert.ok(api.__calls("listMessages").length > before, "the open thread was not re-read");
    await ui.unmount();
});

test("a document notification names the document to open, not only the inbox (2026-10-09)", async () => {
    const { lawyerNotificationTarget } = await import("../src/lib/notificationTarget.js");
    assert.deepEqual(lawyerNotificationTarget("document_submitted", { doc_id: "d9" }),
        { page: "documents", caseId: null, docId: "d9" });
    assert.equal(lawyerNotificationTarget("document_withdrawn", {}).docId, null);
});
