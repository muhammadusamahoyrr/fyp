/* Phase 2.6c: Profile and the hearing-outcome modal show the server's reason.
 *
 * WHAT WAS WRONG. Both read `error.detail`. On the error envelope that is
 * undefined ("Save failed" every time), and on a 422 it is the raw array of
 * objects, which a toast renders as "[object Object]". `error.message` is the
 * string formatResponseError builds for exactly this.
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
const { ToastCtx } = await import("../src/components/lawyer/Toast.jsx");
const { CaseCtx } = await import("../src/components/lawyer/theme.js");
const { ProfilePage } = await import("../src/components/lawyer/ProfilePage.jsx");
const { CasesPage } = await import("../src/components/lawyer/CasesPage.jsx");
const h = React.createElement;

const settle = (ms = 40) => act(async () => { await new Promise(r => setTimeout(r, ms)); });
const detail = [{ loc: ["body", "bar_number"], msg: "String should match pattern", type: "string_pattern_mismatch" }];
const unprocessable = { data: null, status: 422, error: { detail, message: "Bar_number: String should match pattern" } };

async function mount(el) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(el); });
    await settle();
    return { container, unmount: async () => { await act(async () => root.unmount()); container.remove(); } };
}
const button = (root, text) => [...root.querySelectorAll("button")].find(b => b.textContent.includes(text));
async function click(el) {
    assert.ok(el, "button not found");
    await act(async () => { el.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
}

test.beforeEach(() => api.__reset());

test("Profile: a 422 on save shows the server's message, not [object Object]", async () => {
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer", full_name: "Asad Ali", lawyer_profile: {} }, error: null });
    api.__respond("updateMe", { data: {}, error: null, status: 200 });
    api.__respond("updateLawyerProfile", unprocessable);
    const toasts = [];
    const view = await mount(h(ToastCtx.Provider, { value: { show: (m) => toasts.push(m) } }, h(ProfilePage)));
    await click(button(view.container, "Save Changes"));
    assert.deepEqual(toasts, ["❌ Bar_number: String should match pattern"]);
    await view.unmount();
});

test("Cases: a failed outcome shows the server's message", async () => {
    const CASE = { _id: "665f00000000000000000001", case_number: "CIV-2026-001", title: "Rent dispute",
                   client_name: "Ayesha", province: "punjab", case_type: "civil", status: "in_progress",
                   hearing_dates: [{ _id: "h1", date: "2026-10-20T00:00:00Z", time: "10:00", court: "Civil Court", purpose: "Issues" }] };
    api.__respond("listCases", { data: { items: [CASE] }, error: null });
    api.__respond("listEngagements", { data: [], error: null });
    api.__respond("recordHearingOutcome", { data: null, status: 422,
        error: { detail: [{ loc: ["body", "outcome"], msg: "bad", type: "x" }], message: "Outcome: not a recognised outcome" } });
    function Host() {
        const [openCaseId, setOpenCaseId] = useState(CASE.case_number);
        return h(CaseCtx.Provider, { value: { openCaseId, setOpenCaseId, activeCase: null, setActiveCase: () => {},
                                             docs: {}, setDocs: () => {}, setPage: () => {} } }, h(CasesPage));
    }
    const view = await mount(h(Host));
    await click(button(view.container, "Manage →"));
    await click(button(view.container, "Add Outcome"));
    await click(button(view.container, "Record & Notify Client"));
    assert.match(view.container.textContent, /Outcome: not a recognised outcome/);
    assert.doesNotMatch(view.container.textContent, /\[object Object\]/);
    await view.unmount();
});
