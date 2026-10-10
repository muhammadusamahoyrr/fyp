/* The client's notifications stay live, and pages follow them.
 *
 * WHAT WAS WRONG. The client's socket was opened once; when it closed nothing
 * arrived until a reload. A notification did not refresh anything: a lawyer
 * confirming a booking left it "Pending" on the client's screen. And notices
 * made in the browser had made-up ids that were sent to the server as read.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/client" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node", "Event",
                    "CustomEvent", "EventTarget", "MouseEvent", "MutationObserver",
                    "getComputedStyle", "localStorage", "sessionStorage"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { AuthProvider } = await import("../src/context/AuthContext.jsx");
const { CaseProvider, useCase } = await import("../src/components/shared/CaseContext.jsx");
const h = React.createElement;
const settle = (ms = 60) => act(async () => { await new Promise(r => setTimeout(r, ms)); });

let sockets;
function serve() {
    api.__reset();
    sockets = [];
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "c1", role: "client", full_name: "Bilal" }, error: null });
    api.__respond("getNotifications", { data: [], error: null });
    api.__respond("listCases", { data: { items: [], total: 0 }, error: null });
    api.__respond("listAppointments", { data: { items: [], total: 0, pages: 1 }, error: null });
    api.__respond("markNotificationRead", { data: {}, error: null });
    api.__respond("openNotificationSocket", (onMessage) => {
        const s = new dom.window.EventTarget();
        s.close = () => {};
        s.onMessage = onMessage;
        sockets.push(s);
        return s;
    });
}

async function mount() {
    let ctx;
    const Probe = () => { ctx = useCase(); return null; };
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(h(AuthProvider, null, h(CaseProvider, null, h(Probe)))); });
    await settle(120);
    return { ctx: () => ctx, unmount: () => act(async () => root.unmount()).then(() => container.remove()) };
}

test.after(() => dom.window.close());

test("a closed socket reconnects and re-reads what was missed", async () => {
    serve();
    const ui = await mount();
    assert.equal(sockets.length, 1);
    const reads = api.__calls("getNotifications").length;
    await act(async () => { sockets[0].dispatchEvent(new dom.window.Event("close")); });
    await settle(1200);
    assert.equal(sockets.length, 2, "no reconnect");
    await act(async () => { sockets[1].dispatchEvent(new dom.window.Event("open")); });
    await settle();
    assert.ok(api.__calls("getNotifications").length > reads);
    await ui.unmount();
});

test("an appointment notification re-reads the client's appointments", async () => {
    serve();
    const ui = await mount();
    const before = api.__calls("listAppointments").length;
    api.__respond("listAppointments", { data: { items: [{ id: "a1", status: "confirmed" }], total: 1, pages: 1 }, error: null });
    await act(async () => {
        sockets[0].onMessage({ type: "notification", notification: { _id: "n1", type: "appointment_confirmed",
            title: "Confirmed", body: "", payload: { appointment_id: "a1" }, read: false, created_at: new Date().toISOString() } });
    });
    await settle();
    assert.ok(api.__calls("listAppointments").length > before);
    assert.equal(ui.ctx().appointments[0].status, "confirmed");
    await ui.unmount();
});

test("a notice made in the browser is never sent to the server as read", async () => {
    serve();
    const ui = await mount();
    await act(async () => { ui.ctx().addNotification({ title: "Saved", desc: "" }); });
    const local = ui.ctx().notifications.find(n => n.title === "Saved");
    assert.ok(local?.local);
    await act(async () => { await ui.ctx().markNotificationDone(local.id); });
    assert.equal(api.__calls("markNotificationRead").length, 0);
    assert.ok(ui.ctx().notifications.find(n => n.id === local.id).done);
    await ui.unmount();
});
