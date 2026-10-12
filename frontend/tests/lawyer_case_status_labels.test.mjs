/* Phase 2.1: lawyer case status labels come from the backend's real statuses.
 *
 * WHAT WAS WRONG. Cases and Dashboard mapped only open/active/closed/dismissed
 * (`active` is not a CaseStatus), so in_progress and pending_lawyer showed as
 * "Filed", and the "Under Hearing"/"Adjourned" filters and cards could never
 * match anything.
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
const { CasesPage } = await import("../src/components/lawyer/CasesPage.jsx");
const { DashboardPage } = await import("../src/components/lawyer/DashboardPage.jsx");
const h = React.createElement;

const settle = (ms = 40) => act(async () => { await new Promise(r => setTimeout(r, ms)); });

const kase = (n, status) => ({ _id: `665f0000000000000000000${n}`, case_number: `CIV-2026-00${n}`,
    title: `Matter ${n}`, client_id: `cl${n}`, client_name: `Client ${n}`, province: "punjab",
    case_type: "civil", status, hearing_dates: [], created_at: "2026-09-01T00:00:00Z" });
const CASES = [kase(1, "in_progress"), kase(2, "in_progress"), kase(3, "pending_lawyer"),
               kase(4, "open"), kase(5, "closed")];

async function mount(Page) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(AuthProvider, null,
            h(NotifCtx.Provider, { value: { addNotif: () => {} } },
                h(CaseCtx.Provider, { value: { setOpenCaseId: () => {}, setActiveCase: () => {}, setPage: () => {} } },
                    h(Page)))));
    });
    await settle();
    return { container, unmount: async () => { await act(async () => root.unmount()); container.remove(); } };
}

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer" }, error: null });
    api.__respond("listCases", { data: { items: CASES, total: CASES.length }, error: null });
    api.__respond("listEngagements", { data: [], error: null });
    api.__respond("listAppointments", { data: { items: [], total: 0, pages: 0 }, error: null });
});

test("Cases shows each backend status by name, and closed cases under History", async () => {
    const view = await mount(CasesPage);
    const text = view.container.textContent;
    assert.doesNotMatch(text, /Under Hearing|Filed/, "a label with no backend status is still shown");

    const pills = () => [...view.container.querySelectorAll("span")].map(s => s.textContent.trim());
    for (const label of ["In Progress", "Awaiting Lawyer", "Open"]) {
        assert.ok(pills().includes(label), `no "${label}" status shown`);
    }
    assert.equal(pills().filter(l => l === "In Progress").length, 2, "both in_progress cases are not shown");

    // Closed cases are not mixed into the live list; History shows them.
    assert.ok(!pills().includes("Closed"), "a closed case is listed with the live ones");
    const history = [...view.container.querySelectorAll("button")].find(b => b.getAttribute("role") === "tab" && b.textContent.trim().startsWith("Closed"));  // the Closed view (was "History · Closed")
    assert.match(history.textContent, /Closeds*1/);
    await act(async () => { history.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    assert.ok(pills().includes("Closed"), "History does not show the closed case");
    await view.unmount();
});

test("Dashboard rows use the same labels", async () => {
    const view = await mount(DashboardPage);
    const text = view.container.textContent;
    assert.match(text, /In Progress/);
    assert.match(text, /Awaiting Lawyer/);
    assert.doesNotMatch(text, /Filed/);
    await view.unmount();
});
