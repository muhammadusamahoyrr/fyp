/* Hiring a lawyer starts from a COMPLETED consultation.
 *
 * AGREEMENTS_PRODUCT_PLAN.md §17 R5-1, R5-11 step 7. The server refuses a hire
 * request that does not name a completed consultation with that lawyer, and
 * only the lawyer can mark one completed. So the client needs the offer at the
 * one place it can succeed -- their finished consultation -- and it must not
 * appear anywhere it cannot.
 *
 * Two halves, both here because they are one journey:
 *   1. the appointment card offers it, and only when completed;
 *   2. the lawyers page opens the hire form on that consultation.
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

function nav() {
    return (globalThis.__nav ||= { pushed: [], replaced: [], params: new Map() });
}

async function settle(ms = 40) {
    await act(async () => { await new Promise(r => realSetTimeout(r, ms)); });
}

/* ── half 1: the appointment card ────────────────────────────────────────── */

function appointment(over = {}) {
    const when = new Date(Date.now() - 48 * 36e5);
    when.setUTCMinutes(0, 0, 0);
    return {
        id: "apt-1",
        scheduled_at: when.toISOString(),
        end_at: new Date(when.getTime() + 36e5).toISOString(),
        duration_minutes: 60,
        status: "completed",
        mode: "video",
        lawyer_id: "L1",
        lawyer_name: "Adv Ayesha Khan",
        client_name: "Test Client",
        notes: null,
        case_id: null,
        timezone: "Asia/Karachi",
        ...over,
    };
}

async function mountTracking(appts) {
    api.__respond("listAppointments", { data: { items: appts }, error: null, status: 200 });
    const ModTracking = (await import("../src/components/client/ModTracking.jsx")).default;
    const { CaseCtx } = await import("../src/components/shared/CaseContext.jsx");

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    const ctx = {
        notifications: [],
        markNotificationDone: () => {},
        markAllNotificationsDone: () => {},
        appointmentMilestones: [],
    };
    await act(async () => {
        root.render(h(CaseCtx.Provider, { value: ctx }, h(ModTracking, { isDark: true })));
    });
    await settle();

    // Open the Appointments page through the real navigation. The sidebar
    // entries are `<div onClick>`, a pre-existing gap this test does not touch.
    const navTo = [...container.querySelectorAll("div")]
        .find(el => el.textContent.trim() === "Appointments");
    assert.ok(navTo, "no Appointments nav control");
    await act(async () => {
        navTo.dispatchEvent(new dom.window.MouseEvent(
            "click", { bubbles: true, cancelable: true }));
    });
    await settle();

    return {
        container,
        hireLink: () => [...container.querySelectorAll("a")]
            .find(a => a.textContent.includes("Hire this lawyer")),
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

test.beforeEach(() => {
    api.__reset();
    nav().params = new Map();
    api.__respond("listCases", { data: { items: [] } });
    api.__respond("listPayments", { data: [] });
    api.__respond("listAppointmentDisputes", { data: [] });
    api.__respond("listEngagements", { data: [] });
});

test.after(() => {
    for (const id of liveTimers) { realClearInterval(id); realClearTimeout(id); }
    liveTimers.clear();
    dom.window.close();
});

test("a completed consultation offers the hire, carrying the lawyer and itself",
     async () => {
    const ui = await mountTracking([appointment()]);
    const link = ui.hireLink();

    assert.ok(link, "no hire entry on a completed consultation");
    assert.match(link.getAttribute("href"), /^\/lawyers\?/);
    const q = new dom.window.URLSearchParams(
        link.getAttribute("href").split("?")[1]);
    assert.equal(q.get("hire"), "L1");
    assert.equal(q.get("appointment"), "apt-1");
    assert.equal(q.get("hire_name"), "Adv Ayesha Khan");
    await ui.unmount();
});

test("a consultation that has not completed offers nothing", async () => {
    for (const status of ["pending", "confirmed", "cancelled", "no_show", "expired"]) {
        const ui = await mountTracking([appointment({ status })]);
        assert.equal(ui.hireLink(), undefined,
                     `the hire entry appeared on a ${status} consultation`);
        await ui.unmount();
    }
});

/* ── half 2: the lawyers page opens on that consultation ─────────────────── */

function consult(id, over = {}) {
    return { id, lawyer_id: "L1", client_id: "u1", case_id: null,
             status: "completed", scheduled_at: "2026-09-01T10:00:00Z", ...over };
}

function hireableCase(id) {
    return { _id: id, title: `Case ${id}`, case_number: `ATT-${id}`,
             status: "open", lawyer_id: null };
}

async function mountLawyersFromLink(consults, params) {
    for (const [k, v] of Object.entries(params)) nav().params.set(k, v);
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "u1", role: "client" } });
    api.__respond("searchLawyers", { data: { items: [] } });
    api.__respond("listCases", { data: { items: [hireableCase("C1"), hireableCase("C2")] } });
    api.__respond("listHireConsultations", { data: consults });
    api.__respond("requestEngagement", { data: { id: "E1" } });

    const { default: ModLawyers } =
        await import("../src/components/client/ModLawyers.jsx");
    const { CaseProvider } = await import("../src/components/client/CaseContext.jsx");
    const { AuthProvider } = await import("../src/context/AuthContext.jsx");
    const { ToastContainer } = await import("../src/components/shared/Toast.jsx");
    const { DARK } = await import("../src/components/admin/themes.js");
    const { ThemeCtx, HeaderActionsCtx } =
        await import("../src/components/client/theme.js");

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(
            AuthProvider, null,
            h(ThemeCtx.Provider, { value: DARK },
              h(HeaderActionsCtx.Provider, { value: { setHeaderActions: () => {} } },
                h(ToastContainer, { theme: DARK },
                  h(CaseProvider, null, h(ModLawyers)))))));
    });
    await settle(60);

    const field = (label) => {
        const el = [...dom.window.document.querySelectorAll("label")]
            .find(l => l.textContent.trim() === label);
        return el ? el.parentElement.querySelector("select") : null;
    };
    const click = async (label) => {
        const btn = [...dom.window.document.querySelectorAll("button")]
            .find(b => b.textContent.trim().startsWith(label));
        assert.ok(btn, `no "${label}" button`);
        await act(async () => {
            btn.dispatchEvent(new dom.window.MouseEvent(
                "click", { bubbles: true, cancelable: true }));
        });
        await settle(30);
    };
    return {
        text: () => dom.window.document.body.textContent,
        field, click,
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

test("arriving from a consultation opens the hire form on that consultation",
     async () => {
    const ui = await mountLawyersFromLink(
        [consult("A-old", { scheduled_at: "2026-08-01T10:00:00Z" }),
         consult("A-new", { scheduled_at: "2026-09-10T10:00:00Z" })],
        { hire: "L1", hire_name: "Adv Ayesha Khan", appointment: "A-old" });

    assert.match(ui.text(), /Request to Hire/);
    // Several exist, so nothing would be chosen -- except that the client
    // arrived from one, and THAT one is selected.
    assert.equal(ui.field("Consultation *").value, "A-old");

    await ui.click("Send Hire Request");
    const calls = api.__calls("requestEngagement");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].args[0].appointment_id, "A-old");
    assert.equal(calls[0].args[0].lawyer_id, "L1");
    await ui.unmount();
});

test("the lawyer need not be on the current directory page", async () => {
    // `searchLawyers` returns nobody, so the form can only have opened from
    // the link itself.
    const ui = await mountLawyersFromLink(
        [consult("A1")], { hire: "L1", hire_name: "Adv Ayesha Khan", appointment: "A1" });

    assert.match(ui.text(), /Adv Ayesha Khan/);
    await ui.click("Send Hire Request");
    assert.equal(api.__calls("requestEngagement")[0].args[0].appointment_id, "A1");
    await ui.unmount();
});

test("a consultation the server no longer lists is not sent", async () => {
    // The link names A-gone; the server lists two others. The client chooses.
    const ui = await mountLawyersFromLink(
        [consult("A1"), consult("A2")],
        { hire: "L1", hire_name: "Adv Ayesha Khan", appointment: "A-gone" });

    assert.equal(ui.field("Consultation *").value, "",
                 "a consultation the server did not list was pre-selected");
    await ui.click("Send Hire Request");
    assert.equal(api.__calls("requestEngagement").length, 0);
    await ui.unmount();
});

test("no hire link, no hire form", async () => {
    const ui = await mountLawyersFromLink([consult("A1")], {});
    assert.ok(!/Send Hire Request/.test(ui.text()));
    assert.equal(api.__calls("listHireConsultations").length, 0);
    await ui.unmount();
});
