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
