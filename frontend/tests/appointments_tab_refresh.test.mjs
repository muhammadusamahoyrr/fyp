/* A status change leaves a tab that no longer fits it; the totals follow.
 *
 * WHAT WAS WRONG. After marking a no-show (or cancelling, or completing) on a
 * filtered tab, the row stayed in that tab with its new status: a "No Show"
 * listed under Upcoming. And the per-status totals behind the overview cards
 * were read once when the page opened, so Pending kept counting requests the
 * lawyer had already answered.
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
                    "MutationObserver", "getComputedStyle", "localStorage",
                    "requestAnimationFrame", "cancelAnimationFrame"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

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

/* An appointment as the API returns one. `status` is the BACKEND value; the
 * page maps it to a display label, and that mapping is what is under test. */
function appointment(over = {}) {
    const when = new Date(Date.now() + 36e5).toISOString();
    return {
        id: "apt-1",
        scheduled_at: when,
        client_name: "Ayesha Bibi",
        duration_minutes: 30,
        mode: "video",
        notes: "Consultation",
        status: "confirmed",
        case_id: null,
        ...over,
    };
}

async function mountAppointments(items) {
    api.__respond("listAppointments", { data: { items } });
    // Named export, not default.
    const { AppointmentsPage } =
        await import("../src/components/lawyer/AppointmentsPage.jsx");

    const { NotifCtx } = await import("../src/components/lawyer/theme.js");

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    // NotifCtx is required, not optional: `useNotif()` falls back to `{}` when
    // unprovided, so `addNotif` would be undefined and EVERY action handler on
    // this page — confirm, cancel, complete, no-show — would throw on use.
    await act(async () => {
        root.render(h(NotifCtx.Provider, { value: { addNotif: () => {} } },
                      h(AppointmentsPage)));
    });
    await act(async () => { await new Promise(r => setTimeout(r, 30)); });

    return {
        container,
        text: () => container.textContent,
        settle: async (ms = 40) => {
            await act(async () => { await new Promise(r => setTimeout(r, ms)); });
        },
        // Status badges only, and identified structurally.
        //
        // Two other things on this page render the same words: the tab strip
        // ("Cancelled", "No Show" as filters) and the stat cards ("Upcoming",
        // "Pending", "Completed" as counters). A whole-page text scan, or a
        // scan of every <span>, matches those too and would report a badge that
        // is not there — so this selects on what makes a StatusBadge unique:
        // it is the only one of the three that wraps a nested dot <span>.
        badges: () => [...container.querySelectorAll("span")]
            .filter(el => el.querySelector("span"))
            .map(el => el.textContent.trim())
            .filter(txt => ["Upcoming", "Pending", "Completed",
                            "Cancelled", "No Show"].includes(txt)),
        click: async (label) => {
            const btn = [...container.querySelectorAll('button:not([role="tab"])')]
                .find(b => b.textContent.trim() === label);
            assert.ok(btn, `no button labelled ${label!== undefined ? JSON.stringify(label) : label}`);
            await act(async () => {
                btn.dispatchEvent(new dom.window.MouseEvent(
                    "click", { bubbles: true, cancelable: true }));
            });
            await act(async () => { await new Promise(r => setTimeout(r, 30)); });
        },
        tab: async (label) => {
            const tab = [...container.querySelectorAll('[role="tab"]')].find(b => b.textContent.trim().startsWith(label));
            assert.ok(tab, `no ${label} tab`);
            await act(async () => { tab.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
            await act(async () => { await new Promise(r => setTimeout(r, 40)); });
        },
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer" } });
});

test.after(() => {
    for (const id of liveTimers) { realClearInterval(id); realClearTimeout(id); }
    liveTimers.clear();
    dom.window.close();
});


function started(over = {}) {
    return { id: "apt-1", scheduled_at: new Date(Date.now() - 10 * 60e3).toISOString(), client_name: "Ayesha Bibi",
        duration_minutes: 30, mode: "video", notes: "Consultation", status: "confirmed", case_id: null, ...over };
}

test("a row marked No Show leaves the Upcoming tab", async () => {
    api.__respond("markNoShow", { data: { success: true } });
    const ui = await mountAppointments([started()]);
    await ui.tab("Upcoming");
    assert.deepEqual(ui.badges(), ["Upcoming"]);
    await ui.click("No Show");
    assert.deepEqual(ui.badges(), [], "the no-show is still listed under Upcoming");
    await ui.unmount();
});

test("on All, the row stays and shows its new status", async () => {
    api.__respond("markNoShow", { data: { success: true } });
    const ui = await mountAppointments([started()]);
    await ui.click("No Show");
    assert.deepEqual(ui.badges(), ["No Show"]);
    await ui.unmount();
});

test("the per-status totals are re-read after a change", async () => {
    api.__respond("markNoShow", { data: { success: true } });
    const ui = await mountAppointments([started()]);
    const totalsReads = () => api.__calls("listAppointments").filter(c => c.args[0]?.page_size === 1).length;
    const before = totalsReads();
    await ui.click("No Show");
    await ui.settle(60);
    assert.ok(totalsReads() > before, "the totals were not re-read");
    await ui.unmount();
});

test("an ended video consultation offers no Join Call", async () => {
    const ended = started({ scheduled_at: new Date(Date.now() - 3 * 36e5).toISOString(), meeting_link: "https://meet.example/x" });
    const live = started({ id: "apt-2", meeting_link: "https://meet.example/y" });
    const ui = await mountAppointments([ended, live]);
    const joins = [...ui.container.querySelectorAll("button")].filter(b => b.textContent.includes("Join Call"));
    assert.equal(joins.length, 1, "only the consultation still running can be joined");
    await ui.unmount();
});
