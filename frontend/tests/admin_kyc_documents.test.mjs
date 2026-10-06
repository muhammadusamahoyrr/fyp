/* Admin KYC review shows the documents a lawyer actually uploaded.
 *
 * WHAT WAS WRONG. Every pending lawyer was listed with the hardcoded documents
 * "Bar License" and "ID Proof" — a claim about files that did not exist, since
 * nothing could be uploaded. The list now comes from
 * lawyer_profile.kyc_documents, and each entry opens the real file.
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
                    "getComputedStyle", "localStorage", "sessionStorage", "requestAnimationFrame",
                    "cancelAnimationFrame", "ResizeObserver"]) {
    if (dom.window[name] !== undefined) define(name, dom.window[name]);
}
if (!globalThis.ResizeObserver) define("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
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
const { DARK } = await import("../src/components/admin/themes.js");
const { KYCVerification } = await import("../src/components/admin/AdminKYCVerification.jsx");
const h = React.createElement;

const settle = (ms = 60) => act(async () => { await new Promise(r => setTimeout(r, ms)); });

const lawyer = (id, name, docs) => ({ _id: id, full_name: name, email: `${id}@x.pk`, created_at: "2026-10-01T00:00:00Z",
    lawyer_profile: { bar_number: `PBC/${id}`, kyc_documents: docs } });

test("pending lawyers show their real uploads, and each one opens the file", async () => {
    api.__reset();
    api.__respond("adminListPendingKYC", { data: [
        lawyer("l1", "Adv With Docs", { bar_certificate: { file_id: "a", filename: "bar.pdf" },
                                        photo: { file_id: "b", filename: "me.png" } }),
        lawyer("l2", "Adv Without", {}),
    ], error: null });
    api.__respond("adminOpenKycDocument", { error: null });

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(h(KYCVerification, { T: DARK })); });
    await settle();

    const text = container.textContent;
    assert.doesNotMatch(text, /ID Proof|Bar License(?! No)/, "hardcoded document names are still shown");
    assert.match(text, /Bar Council Certificate ↗/);
    assert.match(text, /No documents uploaded/);

    const open = [...container.querySelectorAll("button")].find(b => b.textContent.includes("Bar Council Certificate"));
    await act(async () => { open.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
    assert.deepEqual(api.__calls("adminOpenKycDocument").map(c => c.args), [["l1", "bar_certificate"]]);
    await act(async () => root.unmount());
    container.remove();
});

test("a failed queue load is an error with a working retry, not an empty queue", async () => {
    api.__reset();
    let attempt = 0;
    api.__respond("adminListPendingKYC", () => (++attempt === 1
        ? { data: null, status: 503, error: { message: "Service temporarily unavailable" } }
        : { data: [lawyer("l3", "Adv Retried", {})], error: null }));

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(h(KYCVerification, { T: DARK })); });
    await settle();

    assert.doesNotMatch(container.textContent, /No pending KYC submissions/, "an outage was shown as an empty queue");
    const alert = container.querySelector('[role="alert"]');
    assert.ok(alert && /Could not load KYC submissions/.test(alert.textContent));
    assert.match(alert.textContent, /Service temporarily unavailable/);

    const retry = [...alert.querySelectorAll("button")].find(b => b.textContent.trim() === "Retry");
    await act(async () => { retry.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
    assert.match(container.textContent, /Adv Retried/, "retry did not reload the queue");
    assert.equal(container.querySelector('[role="alert"]'), null);
    await act(async () => root.unmount());
    container.remove();
});
