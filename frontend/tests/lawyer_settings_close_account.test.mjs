/* Phase 3.1: Settings -> Delete Account closes the account, behind a password.
 *
 * WHAT WAS WRONG. The Danger Zone's "Delete Account" button had no handler,
 * although `POST /users/me/close` and `closeAccount()` exist (the client side
 * already uses them). The server re-checks the password and refuses while
 * engagements or payments are live; the lawyer must see that reason.
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
                    "getComputedStyle", "localStorage", "sessionStorage", "BroadcastChannel"]) {
    if (dom.window[name] !== undefined) define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { AuthProvider } = await import("../src/context/AuthContext.jsx");
const { ToastCtx } = await import("../src/components/lawyer/Toast.jsx");
const { SettingsPage } = await import("../src/components/lawyer/SettingsPage.jsx");
const h = React.createElement;

const settle = (ms = 40) => act(async () => { await new Promise(r => setTimeout(r, ms)); });

async function mount() {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(AuthProvider, null,
            h(ToastCtx.Provider, { value: { show: () => {} } }, h(SettingsPage))));
    });
    await settle(80);
    return { container, unmount: async () => { await act(async () => root.unmount()); container.remove(); } };
}
const button = (root, text) => [...root.querySelectorAll("button")].find(b => b.textContent.trim() === text);
async function click(el) {
    assert.ok(el, "button not found");
    await act(async () => { el.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
}
async function typePassword(root, value) {
    const input = root.querySelector('input[placeholder="Current password"]');
    assert.ok(input, "no password field");
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    await act(async () => { setter.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
}

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer" }, error: null });
});

test("Delete Account asks for the password and sends nothing without it", async () => {
    const view = await mount();
    await click(button(view.container, "Delete Account"));
    await click(button(view.container, "Permanently close account"));
    assert.equal(api.__calls("closeAccount").length, 0);
    assert.match(view.container.textContent, /Enter your password to confirm/);
    await view.unmount();
});

test("the server's refusal is shown verbatim and the lawyer stays signed in", async () => {
    api.__respond("closeAccount", { data: null, status: 400,
        error: { message: "You still have 2 active engagements. End them before closing your account." } });
    const view = await mount();
    await click(button(view.container, "Delete Account"));
    await typePassword(view.container, "s3cret");
    await click(button(view.container, "Permanently close account"));
    assert.deepEqual(api.__calls("closeAccount").map(c => c.args[0]), ["s3cret"]);
    assert.match(view.container.textContent, /2 active engagements/);
    assert.equal(api.__calls("authLogout").length, 0);
    await view.unmount();
});

test("a confirmed closure signs the lawyer out", async () => {
    api.__respond("closeAccount", { data: { closed: true }, error: null, status: 200 });
    const view = await mount();
    await click(button(view.container, "Delete Account"));
    await typePassword(view.container, "s3cret");
    await click(button(view.container, "Permanently close account"));
    assert.equal(api.__calls("authLogout").length, 1, "the lawyer was not signed out");
    await view.unmount();
});
