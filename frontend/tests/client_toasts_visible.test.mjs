/* The live client app shows its toasts.
 *
 * WHAT WAS WRONG. Every client route renders ClientApp, which mounted no
 * ToastContainer — the only one lived in the unused legacy client/App.jsx — so
 * useToast() fell back to a no-op and every client toast was dropped. Found in
 * the demo smoke test: the close-account refusal reached the server and
 * nothing was shown.
 *
 * This mounts the real ClientApp (not a test provider) and checks the message
 * is actually rendered, in the current theme's palette.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><head></head><body></body></html>", { url: "http://localhost/profile" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "HTMLInputElement", "Element",
                    "Node", "Event", "CustomEvent", "MouseEvent", "KeyboardEvent", "MutationObserver",
                    "getComputedStyle", "localStorage", "sessionStorage", "FileReader",
                    "requestAnimationFrame", "cancelAnimationFrame"]) {
    if (dom.window[name] !== undefined) define(name, dom.window[name]);
}
if (!dom.window.matchMedia) {
    dom.window.matchMedia = (q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {},
                                       addListener() {}, removeListener() {} });
}
define("matchMedia", dom.window.matchMedia);
if (!globalThis.ResizeObserver) define("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
if (!globalThis.IntersectionObserver) define("IntersectionObserver", class { observe() {} unobserve() {} disconnect() {} });
if (!dom.window.HTMLElement.prototype.scrollIntoView) dom.window.HTMLElement.prototype.scrollIntoView = () => {};
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { AuthProvider } = await import("../src/context/AuthContext.jsx");
const { LIGHT } = await import("../src/components/admin/themes.js");
const { default: ClientApp } = await import("../src/components/client/ClientApp.jsx");
const h = React.createElement;

const settle = (ms = 60) => act(async () => { await new Promise(r => setTimeout(r, ms)); });
const REASON = "You have 1 active engagement. End it before closing your account.";

test("a refused account closure shows its reason in a visible danger toast, in the current theme", async () => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "c1", role: "client", full_name: "Ayesha Khan", email: "a@x.pk" }, error: null });
    api.__respond("closeAccount", { data: null, status: 400,
        error: { code: "open_obligations", message: REASON } });
    localStorage.setItem("aai-theme", "light");

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(h(AuthProvider, null, h(ClientApp, { initialTab: "profile" }))); });
    await settle(250);

    const security = [...container.querySelectorAll("button")].find(b => b.textContent.trim() === "Security");
    assert.ok(security, "the profile's Security tab did not render");
    await act(async () => { security.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
    const label = [...container.querySelectorAll("div")].find(d => d.children.length === 0 && d.textContent.trim() === "Delete Account");
    await act(async () => { label.parentElement.parentElement.querySelector("button").dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
    const pw = container.querySelector('input[placeholder="Your password"]');
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    await act(async () => { setter.call(pw, "s3cret"); pw.dispatchEvent(new Event("input", { bubbles: true })); });
    const dialog = pw.closest('div[style*="position: fixed"]');
    const confirm = [...dialog.querySelectorAll("button")].find(b => b.textContent.trim() === "Delete");
    await act(async () => { confirm.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();

    const toast = [...container.querySelectorAll("span")].find(s => s.textContent.trim() === REASON);
    assert.ok(toast, "the refusal reached the server but no toast was rendered");
    // Danger palette of the CURRENT (light) theme: the theme is passed through.
    const rgb = (hex) => `rgb(${parseInt(hex.slice(1, 3), 16)}, ${parseInt(hex.slice(3, 5), 16)}, ${parseInt(hex.slice(5, 7), 16)})`;
    assert.equal(toast.style.color, rgb(LIGHT.badgeDanger.color));

    // Exactly one container: one fixed toast stack.
    const stacks = [...container.querySelectorAll('div[style*="position: fixed"]')]
        .filter(d => d.style.bottom === "24px" && d.style.right === "24px");
    assert.equal(stacks.length, 1);

    await act(async () => root.unmount());
    container.remove();
    localStorage.removeItem("aai-theme");
});
