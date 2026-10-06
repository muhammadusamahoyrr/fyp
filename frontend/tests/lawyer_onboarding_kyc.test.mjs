/* Onboarding Step 2 (Credentials & Photo) uploads for real.
 *
 * WHAT WAS WRONG. Every control on the step was inert: the credential
 * "Upload" buttons had no handler, the photo stayed in the browser, "Take
 * Photo" did nothing, the avatar read "AK" for everyone and a banner claimed
 * "2 items pending verification" whatever had been sent.
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
                    "getComputedStyle", "localStorage", "sessionStorage", "File"]) {
    define(name, dom.window[name]);
}
// Node's own URL.createObjectURL rejects jsdom's File; a browser's accepts it.
URL.createObjectURL = () => "blob:test";
URL.revokeObjectURL = () => {};
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { OnboardingPage } = await import("../src/components/lawyer/OnboardingPage.jsx");
const h = React.createElement;

const settle = (ms = 40) => act(async () => { await new Promise(r => setTimeout(r, ms)); });

async function toStepTwo() {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(h(OnboardingPage, { onComplete: () => {} })); });
    await settle();
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    const type = async (sel, v) => {
        const el = container.querySelector(sel);
        await act(async () => { setter.call(el, v); el.dispatchEvent(new Event("input", { bubbles: true })); });
    };
    await type('input[placeholder="Adv. Ahmad Khan"]', "Sana Mir");
    await type('input[placeholder="e.g. PBC/12345/2019"]', "PBC/12345/2019");
    const civil = [...container.querySelectorAll("span")].find(x => x.textContent.trim() === "Civil Litigation");
    await act(async () => { civil.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    const cont = [...container.querySelectorAll("button")].find(b => b.textContent.includes("Continue"));
    await act(async () => { cont.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
    assert.match(container.textContent, /Bar Council Certificate/, "did not reach Step 2");
    return { container, unmount: async () => { await act(async () => root.unmount()); container.remove(); } };
}

async function choose(container, kind, file) {
    const input = container.querySelector(`input[type="file"][data-kind="${kind}"]`);
    assert.ok(input, `no file input for ${kind}`);
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    await act(async () => { input.dispatchEvent(new Event("change", { bubbles: true })); });
    await settle();
}

const pdf = (name) => new File(["%PDF-1.4"], name, { type: "application/pdf" });
const meta = (filename) => ({ file_id: "f1", filename, content_type: "application/pdf", size: 8 });

test.beforeEach(() => {
    api.__reset();
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer" }, error: null });
    api.__respond("listMyKycDocuments", { data: {}, error: null });
});

test("choosing a credential uploads it and the card shows what the server stored", async () => {
    api.__respond("uploadKycDocument", (kind, file) => ({ data: { [kind]: meta(file.name) }, error: null }));
    const view = await toStepTwo();
    assert.match(view.container.textContent, /No credentials uploaded yet/);
    await choose(view.container, "bar_certificate", pdf("bar.pdf"));
    const calls = api.__calls("uploadKycDocument");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].args[0], "bar_certificate");
    assert.equal(calls[0].args[1].name, "bar.pdf");
    assert.match(view.container.textContent, /Uploaded · bar\.pdf/);
    assert.match(view.container.textContent, /1 of 3 credentials uploaded/);
    await view.unmount();
});

test("a refused upload shows the server's reason on that card", async () => {
    api.__respond("uploadKycDocument", { data: null, status: 422,
        error: { message: "Educational Credentials: file type not allowed. Accepted: PDF, JPEG or PNG." } });
    const view = await toStepTwo();
    await choose(view.container, "education", pdf("degree.docx"));
    const alert = [...view.container.querySelectorAll('[role="alert"]')].map(a => a.textContent);
    assert.ok(alert.some(t => /file type not allowed/.test(t)), "the refusal was not shown");
    assert.doesNotMatch(view.container.textContent, /Uploaded · degree/);
    await view.unmount();
});

test("the photo uploads, and the avatar uses the lawyer's own initials", async () => {
    api.__respond("uploadKycDocument", (kind, file) => ({ data: { [kind]: meta(file.name) }, error: null }));
    const view = await toStepTwo();
    const leaf = (t) => [...view.container.querySelectorAll("span")].some(x => x.textContent.trim() === t);
    assert.ok(leaf("SM"), "the avatar does not show the lawyer's initials");
    assert.ok(!leaf("AK"), "the avatar still shows hardcoded initials");
    assert.ok(view.container.querySelector('input[data-kind="photo-camera"][capture="user"]'), "Take Photo has no camera input");
    await choose(view.container, "photo", new File(["\x89PNG"], "me.png", { type: "image/png" }));
    assert.equal(api.__calls("uploadKycDocument")[0].args[0], "photo");
    assert.match(view.container.textContent, /Photo uploaded/);
    await view.unmount();
});

test("documents uploaded earlier are shown when the step opens", async () => {
    api.__respond("listMyKycDocuments", { data: { education: meta("llb.pdf") }, error: null });
    const view = await toStepTwo();
    assert.match(view.container.textContent, /Uploaded · llb\.pdf/);
    assert.match(view.container.textContent, /1 of 3 credentials uploaded/);
    await view.unmount();
});

test("a failed read of earlier uploads is not shown as 'nothing uploaded'", async () => {
    let attempt = 0;
    api.__respond("listMyKycDocuments", () => (++attempt === 1
        ? { data: null, status: 503, error: { message: "Service temporarily unavailable" } }
        : { data: { education: meta("llb.pdf") }, error: null }));
    const view = await toStepTwo();
    assert.doesNotMatch(view.container.textContent, /No credentials uploaded yet/);
    const alert = [...view.container.querySelectorAll('[role="alert"]')].find(a => /Couldn't load your uploads/.test(a.textContent));
    assert.ok(alert, "the failed read was not reported");
    const retry = [...alert.querySelectorAll("button")].find(b => b.textContent.trim() === "Retry");
    await act(async () => { retry.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
    assert.match(view.container.textContent, /Uploaded · llb\.pdf/);
    await view.unmount();
});
