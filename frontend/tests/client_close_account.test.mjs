/* Client profile: closing the account.
 *
 * WHAT WAS WRONG.
 *   * ConfirmDialog never rendered its children, so the password field the
 *     close-account dialog passes in was invisible: the password was always
 *     empty and the client could never close their account.
 *   * A refusal was shown from `error.detail`, which the error envelope does
 *     not carry (and which is an array on a 422), so the server's reason —
 *     e.g. live engagements that must end first — was lost.
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
                    "getComputedStyle", "localStorage", "sessionStorage", "FileReader"]) {
    if (dom.window[name] !== undefined) define(name, dom.window[name]);
}
if (!dom.window.matchMedia) {
    dom.window.matchMedia = (q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {},
                                       addListener() {}, removeListener() {} });
}
define("matchMedia", dom.window.matchMedia);
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { AuthProvider } = await import("../src/context/AuthContext.jsx");
const { ToastCtx } = await import("../src/components/shared/Toast.jsx");
const { default: ModProfile } = await import("../src/components/client/ModProfile.jsx");
const h = React.createElement;

const settle = (ms = 40) => act(async () => { await new Promise(r => setTimeout(r, ms)); });

test("a refused closure shows the server's structured reason", async () => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "c1", role: "client", full_name: "Ayesha Khan", email: "a@x.pk" }, error: null });
    api.__respond("closeAccount", { data: null, status: 400,
        error: { error: { code: "open_obligations", message: "You have 1 active engagement. End it before closing your account." },
                 code: "open_obligations",
                 message: "You have 1 active engagement. End it before closing your account." } });

    const toasts = [];
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(AuthProvider, null,
            h(ToastCtx.Provider, { value: { show: (m) => toasts.push(m) } }, h(ModProfile))));
    });
    await settle(120);

    const security = [...container.querySelectorAll("button")].find(b => b.textContent.trim() === "Security");
    await act(async () => { security.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
    // The Delete Account row's own button opens the confirmation dialog.
    const label = [...container.querySelectorAll("div")].find(el => el.children.length === 0
        && el.textContent.trim() === "Delete Account");
    assert.ok(label, "no Delete Account row");
    const open = label.parentElement.parentElement.querySelector("button");
    await act(async () => { open.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();

    const pw = container.querySelector('input[placeholder="Your password"]');
    assert.ok(pw, "the password field is not rendered in the confirmation dialog");
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    await act(async () => { setter.call(pw, "s3cret"); pw.dispatchEvent(new Event("input", { bubbles: true })); });
    // The dialog's own confirm button (the row's opener is also labelled "Delete").
    const dialog = pw.closest('div[style*="position: fixed"]');
    const del = [...dialog.querySelectorAll("button")].find(b => b.textContent.trim() === "Delete");
    await act(async () => { del.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();

    assert.deepEqual(api.__calls("closeAccount").map(c => c.args[0]), ["s3cret"]);
    assert.ok(toasts.includes("You have 1 active engagement. End it before closing your account."),
        `the server's reason was not shown: ${JSON.stringify(toasts)}`);
    await act(async () => root.unmount());
    container.remove();
});
