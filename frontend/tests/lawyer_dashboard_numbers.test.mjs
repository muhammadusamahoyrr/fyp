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

// `byStatus` is what the server would count per status (its `total` for
// `?status=`); by default it is counted from `cases`.
function serve({ cases, total = cases.length, submitted, byStatus = null }) {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer", full_name: "Asad Ali" }, error: null });
    const counted = (st) => (byStatus ? (byStatus[st] ?? 0) : cases.filter(c => c.status === st).length);
    api.__respond("listCases", (args = {}) => (args.status
        ? { data: { items: [], total: counted(args.status), page: 1, page_size: 1, pages: 1 }, error: null }
        : { data: { items: cases, total }, error: null }));
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

test("active cases are the server's open + in_progress totals; pending docs come from the review queue", async () => {
    serve({ submitted: 4, cases: [
        kase(1, "in_progress", { hearing_dates: [{ date: "2026-11-20T00:00:00Z" }] }),
        kase(2, "pending_lawyer"), kase(3, "closed"),
    ], byStatus: { open: 3, in_progress: 5 } });
    const view = await mount();
    assert.equal(stat(view.container, "Active Cases"), "8");
    const asked = api.__calls("listCases").map(c => c.args[0]?.status).filter(Boolean).sort();
    assert.deepEqual(asked, ["in_progress", "open"], "active must be counted by the server, per status");
    assert.equal(stat(view.container, "Docs to Review"), "4");
    // The dashboard (2026-10-10) counts hearings in the next 7 days; 20 Nov is not one.
    assert.equal(stat(view.container, "Hearings This Week"), "0");
    assert.match(view.container.textContent, /20 Nov 2026/, "the next hearing date is not shown");
    await view.unmount();
});

test("a real zero is shown as 0, not as unknown", async () => {
    serve({ cases: [], submitted: 0 });
    const view = await mount();
    assert.equal(stat(view.container, "Active Cases"), "0");
    assert.equal(stat(view.container, "Docs to Review"), "0");
    await view.unmount();
});

test("active is exact even past the first page; counts from a partial list are a floor", async () => {
    serve({ cases: [kase(1, "in_progress"), kase(2, "open")], total: 120, submitted: 0,
            byStatus: { open: 40, in_progress: 61 } });
    const view = await mount();
    assert.equal(stat(view.container, "Active Cases"), "101");
    // Counted from a partial case list, so shown as a floor.
    assert.equal(stat(view.container, "Hearings This Week"), "0+");
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

test("the agenda asks for TODAY by date, and only then says the day is empty", async () => {
    // It used to read the first 50 appointments, which are the OLDEST (the
    // list is sorted by start time), so a lawyer with a history never saw
    // today. It now asks for one Pakistan day, so "no appointments today" is
    // an answer, not a guess.
    serve({ cases: [], submitted: 0 });
    const view = await mount();
    const agenda = api.__calls("listAppointments").map(c => c.args[0] || {}).find(a => a.starts_from);
    assert.ok(agenda, "today's agenda was not asked for by date");
    assert.match(agenda.starts_from, /T00:00:00\+05:00$/);
    assert.match(agenda.starts_before, /T00:00:00\+05:00$/);
    assert.match(view.container.textContent, /No appointments today/);
    await view.unmount();
});

test("a failed agenda read is not shown as an empty day", async () => {
    serve({ cases: [], submitted: 0 });
    api.__respond("listAppointments", (args = {}) => (args.starts_from
        ? { data: null, error: { message: "down" }, status: 0 }
        : { data: { items: [], total: 0, pages: 0 }, error: null }));
    const view = await mount();
    assert.match(view.container.textContent, /Could not load today/);
    assert.doesNotMatch(view.container.textContent, /No appointments today/);
    await view.unmount();
});

test("a case's next hearing is its soonest upcoming one, not the first one added", async () => {
    const { pktToday } = await import("../src/lib/bookingTime.js");
    const plus = (n) => { const d = new Date(`${pktToday()}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
    const { fmtDate } = await import("../src/components/lawyer/data.js");
    serve({ submitted: 0, cases: [kase(1, "in_progress", { hearing_dates: [
        { _id: "past", date: `${plus(-3)}T00:00:00Z`, outcome: null },     // passed, no outcome
        { _id: "late", date: `${plus(40)}T00:00:00Z`, outcome: null },     // added first
        { _id: "soon", date: `${plus(6)}T00:00:00Z`, outcome: null },      // added later, sooner
    ] })] });
    const view = await mount();
    const text = view.container.textContent;
    assert.ok(text.includes(fmtDate(`${plus(6)}T00:00:00Z`)), "the soonest upcoming hearing is not shown");
    assert.ok(!text.includes(fmtDate(`${plus(40)}T00:00:00Z`)), "the first-added hearing is shown instead");
    await view.unmount();
});
