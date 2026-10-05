/* Phase 2.2: the lawyer dashboard's numbers are real.
 *
 * WHAT WAS WRONG. "Active cases" counted `open` and `active` (not a status),
 * so in_progress matters were left out; "Pending Docs" was a hardcoded "—";
 * every card carried a progress bar whose width was `40 + i*13 %`; the date
 * column was always empty; a real zero showed as "—"; and counts drawn from
 * the first 50 cases were presented as totals.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node", "Event",
                    "CustomEvent", "MouseEvent", "KeyboardEvent", "MutationObserver",
                    "getComputedStyle", "localStorage", "sessionStorage"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { AuthProvider } = await import("../src/context/AuthContext.jsx");
const { CaseCtx, NotifCtx } = await import("../src/components/lawyer/theme.js");
const { DashboardPage } = await import("../src/components/lawyer/DashboardPage.jsx");
const h = React.createElement;

const settle = (ms = 40) => act(async () => { await new Promise(r => setTimeout(r, ms)); });

const kase = (n, status, extra = {}) => ({ _id: `665f0000000000000000000${n}`, case_number: `CIV-2026-00${n}`,
    title: `Matter ${n}`, client_id: `cl${n}`, client_name: `Client ${n}`, province: "punjab",
    case_type: "civil", status, hearing_dates: [], ...extra });

function serve({ cases, total = cases.length, submitted }) {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer", full_name: "Asad Ali" }, error: null });
    api.__respond("listCases", { data: { items: cases, total }, error: null });
    api.__respond("listAppointments", { data: { items: [], total: 0, pages: 0 }, error: null });
    api.__respond("reviewQueueV2", { data: { items: [], next_cursor: null, status: "submitted",
        counts: { all: submitted, submitted, approved: 0, returned: 0, rejected: 0 } }, error: null, status: 200 });
}

async function mount() {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(AuthProvider, null,
            h(NotifCtx.Provider, { value: { addNotif: () => {} } },
                h(CaseCtx.Provider, { value: { setOpenCaseId: () => {}, setActiveCase: () => {}, setPage: () => {} } },
                    h(DashboardPage)))));
    });
    await settle();
    return { container, unmount: async () => { await act(async () => root.unmount()); container.remove(); } };
}

// The four stat cards' values, by label.
function stat(container, label) {
    const head = [...container.querySelectorAll("div")]
        .find(d => d.children.length === 0 && d.textContent.trim() === label && d.style.textTransform === "uppercase");
    assert.ok(head, `no "${label}" card`);
    return head.nextElementSibling.textContent.trim();
}

test("active cases include in_progress; pending docs come from the review queue", async () => {
    serve({ submitted: 4, cases: [
        kase(1, "in_progress", { hearing_dates: [{ date: "2026-11-20T00:00:00Z" }] }),
        kase(2, "pending_lawyer"), kase(3, "closed"),
    ] });
    const view = await mount();
    assert.equal(stat(view.container, "Active Cases"), "2");
    assert.equal(stat(view.container, "Pending Docs"), "4");
    assert.equal(stat(view.container, "Total Clients"), "3");
    assert.match(view.container.textContent, /20 Nov 2026/, "the next hearing date is not shown");
    await view.unmount();
});

test("a real zero is shown as 0, not as unknown", async () => {
    serve({ cases: [], submitted: 0 });
    const view = await mount();
    assert.equal(stat(view.container, "Active Cases"), "0");
    assert.equal(stat(view.container, "Pending Docs"), "0");
    await view.unmount();
});

test("counts from a partial case list are marked as a floor", async () => {
    serve({ cases: [kase(1, "in_progress"), kase(2, "open")], total: 120, submitted: 0 });
    const view = await mount();
    assert.equal(stat(view.container, "Active Cases"), "2+");
    await view.unmount();
});

test("no decorative progress bars pretend to measure anything", async () => {
    serve({ cases: [kase(1, "in_progress")], submitted: 1 });
    const view = await mount();
    const bars = [...view.container.querySelectorAll("div")]
        .filter(d => /^\d+%$/.test(d.style.width) && d.parentElement?.style.height === "2px");
    assert.equal(bars.length, 0);
    await view.unmount();
});
