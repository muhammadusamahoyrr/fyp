/* Gate 3D — the lawyer's draft editor, mounted and driven.
 *
 * The component is rendered for real; the API client it imports is the loader's
 * spy stub (see tests/support/jsx-loader.mjs), so what these tests read is the
 * ARGUMENTS the component passed. That is the right seam here: the questions
 * worth asking are about which numbers and which text the editor chooses to
 * send, not about URL construction, which agreement_draft_api.test.mjs covers
 * against the real client.
 *
 * The three things worth breaking:
 *
 *   expected_version       must come from the server's last response. A local
 *                          counter is right until a second writer exists, and
 *                          then it is silently wrong.
 *   expected_body_sha256   must be the digest of the SAVED body. Hashing the
 *                          textarea would attest to text the server does not
 *                          hold, and would differ on Windows, where the box
 *                          holds \r\n and the stored copy holds \n.
 *   Idempotency-Key        must be the SAME across retries of one send. A fresh
 *                          key on a retry is a second agreement.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>",
                      { url: "http://localhost/" });

function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element",
                    "Node", "Event", "CustomEvent", "MutationObserver",
                    "getComputedStyle", "requestAnimationFrame",
                    "cancelAnimationFrame"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);
define("localStorage", {
    _v: {},
    getItem(k) { return this._v[k] ?? null; },
    setItem(k, v) { this._v[k] = String(v); },
    removeItem(k) { delete this._v[k]; },
});
define("BroadcastChannel", class {
    constructor() { this.onmessage = null; }
    postMessage() {}
    close() {}
});

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const { DraftComposer } = await import("../src/components/lawyer/DraftComposer.jsx");
// The digest lives outside lib/api.js precisely so the component gets the REAL
// one here rather than a spy. Importing it the same way the component does.
const { bodyDigestHex } = await import("../src/lib/agreementBody.js");
const { __calls, __respond, __reset } = await import("./support/api-stub.mjs");
const { createElement: h } = React;

const DRAFT = (over = {}) => ({
    _id: "D1", id: "D1", title: "Retainer", body_html: "Agreed terms.",
    status: "draft", created_by: "L1", version: 1,
    parties: [{ user_id: "L1", full_name: "Adv Khan", signed: false },
              { user_id: "C1", full_name: "A Client", signed: false }],
    ...over,
});

const ok = (body) => ({ data: body, error: null, status: 200 });

/* What `getAgreement` should return for the draft being opened.
 *
 * THE COMPOSER NOW FETCHES. Its `draft` prop is a LIST ROW -- and since Gate
 * 3F list rows carry no `body_html`, seeding the editor from one opened it
 * blank and a save would have replaced the real wording. So the prop is a
 * pointer and the document is fetched by id.
 *
 * Tests that care about the fetched document set this; the rest get the same
 * object they passed as `draft`, which is what they were previously asserting
 * against directly. */
let fetchedDraft = null;

async function mount(props) {
    __respond("getAgreement", () => ({
        data: fetchedDraft ?? props.draft, error: null, status: 200,
    }));

    const host = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => { root.render(h(DraftComposer, props)); });
    // A second flush: the case list and the draft are both fetched in effects,
    // and their state updates land a microtask after the first render settles.
    await act(async () => {});
    await act(async () => {});
    return {
        host,
        text: () => host.textContent,
        buttons: () => [...host.querySelectorAll("button")],
        find(label) {
            return this.buttons().find(
                b => b.textContent.replace(/\s+/g, " ").includes(label));
        },
        async click(label) {
            const el = this.find(label);
            assert.ok(el, `no button matching ${JSON.stringify(label)} — saw: ` +
                this.buttons().map(b => JSON.stringify(b.textContent)).join(" | "));
            await act(async () => {
                el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
            });
            return el;
        },
        async type(placeholder, value) {
            const el = host.querySelector(`[placeholder="${placeholder}"]`);
            assert.ok(el, `no field with placeholder ${JSON.stringify(placeholder)}`);
            const proto = el.tagName === "TEXTAREA"
                ? dom.window.HTMLTextAreaElement.prototype
                : dom.window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
            await act(async () => {
                setter.call(el, value);
                el.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
            });
        },
        async consent() {
            const el = host.querySelector('input[type="checkbox"]');
            assert.ok(el, "no consent checkbox");
            const setter = Object.getOwnPropertyDescriptor(
                dom.window.HTMLInputElement.prototype, "checked").set;
            await act(async () => {
                setter.call(el, true);
                el.dispatchEvent(new dom.window.Event("click", { bubbles: true }));
                el.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
            });
        },
    };
}

test.beforeEach(() => { __reset(); fetchedDraft = null; });

const argsOf = (name) => __calls(name).map(c => c.args);
const BODY_FIELD = "Write the terms of this agreement…";
const NAME_FIELD = "Type your full legal name";

// ── the digest agrees with the server ────────────────────────────────────────

test("bodyDigestHex reproduces the server's body_digest", async () => {
    // Vectors computed with the backend's own `body_digest(normalise_body(x))`.
    // If this drifts, every send is refused as a phantom conflict — or worse,
    // a signature is recorded against a digest describing text nobody read.
    const vectors = [
        ["Simple terms.", "b3377caf55ba03daf063605dabde5177c478c791819d24824e6cbc6f0a2bd913"],
        ["Line one\nLine two\n", "ac98c501f944c7948e6d3b004c195429c1c560027d9f96284ec2d6028d72381b"],
        ["Unicode: حقوق الموكل — fees ₨ 50,000",
         "612f43ba98f8a4a37a6db6c7c55420c4c55ea857a07b2092ea5e5bb87ebf4c3f"],
        ["", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],
    ];
    for (const [body, expected] of vectors) {
        assert.equal(await bodyDigestHex(body), expected,
            `digest drifted for ${JSON.stringify(body)}`);
    }
});

test("a CRLF body hashes differently, which is why the textarea is never hashed", async () => {
    // The server normalises \r\n to \n before storing and hashing; a Windows
    // textarea holds \r\n. This pins that the two really are different digests,
    // so the rule the component follows is load-bearing, not decorative.
    assert.notEqual(await bodyDigestHex("a\r\nb"), await bodyDigestHex("a\nb"));
});

// ── what the editor sends ────────────────────────────────────────────────────

test("an edit sends the version the server last reported, not a local count", async () => {
    // The server answers 9, not 5: something else wrote in between.
    __respond("updateDraft", () => ok(DRAFT({ version: 9, body_html: "Edited." })));

    const ui = await mount({ draft: DRAFT({ version: 4 }), onClose() {}, onSaved() {} });
    await ui.type(BODY_FIELD, "Edited.");
    await ui.click("Save changes");

    assert.deepEqual(argsOf("updateDraft")[0], ["D1", {
        expected_version: 4, title: "Retainer", body_html: "Edited.",
    }]);

    // The NEXT save must carry 9 — what the server returned — not 5, which is
    // what counting our own saves would have produced.
    await ui.type(BODY_FIELD, "Edited twice.");
    await ui.click("Save changes");
    assert.equal(argsOf("updateDraft")[1][1].expected_version, 9);
});

test("the send attests to the body the server returned, after a normalising save", async () => {
    // The server stores \n where the textarea held \r\n, so the saved copy is
    // NOT the string that was typed. What is signed must be the saved copy.
    const typed = "Clause one.\r\nClause two.";
    const stored = "Clause one.\nClause two.";
    __respond("updateDraft", () => ok(DRAFT({ version: 4, body_html: stored })));
    __respond("sendDraft", () => ok(DRAFT({ status: "pending" })));

    const ui = await mount({ draft: DRAFT({ version: 3 }), onClose() {}, onSaved() {} });
    await ui.type(BODY_FIELD, typed);
    await ui.click("Save changes");
    await ui.click("Sign & send…");
    await ui.consent();
    await ui.type(NAME_FIELD, "Adv Khan");
    await ui.click("Confirm — sign & send");

    const [id, payload] = argsOf("sendDraft")[0];
    assert.equal(id, "D1");
    assert.equal(payload.expected_body_sha256, await bodyDigestHex(stored),
        "the digest must describe the stored wording, not the typed keystrokes");
    assert.notEqual(payload.expected_body_sha256, await bodyDigestHex(typed));
    assert.equal(payload.expected_version, 4, "the version the save returned");
    assert.equal(payload.consent, true);
    assert.equal(payload.signature_data, "Adv Khan");
    assert.equal(payload.method, "typed");
});

test("the digest is read from the server's copy, not from editor state", () => {
    // A BEHAVIOURAL test cannot separate these two. `dirty` blocks the send
    // whenever they differ, and a successful save copies the server's body back
    // into the box, so at the moment of sending the two strings are always
    // equal — swapping one for the other changes no observable outcome today.
    //
    // It is still the correct source, and cheap to keep correct: it is what
    // stays right if the dirty guard is ever loosened, and the failure it
    // prevents is a signature recorded against text nobody read. So the source
    // is pinned here, and the guard that makes them equal is pinned by "a draft
    // with unsaved edits cannot be sent" above. Neither test is sufficient
    // alone; this comment is why there are two.
    const src = readFileSync(
        new URL("../src/components/lawyer/DraftComposer.jsx", import.meta.url), "utf8");
    assert.match(src, /bodyDigestHex\(server\.body_html \|\| ""\)/,
        "the digest must be taken over the server's copy");
});

test("the send carries an idempotency key, and a retry reuses the same one", async () => {
    let attempt = 0;
    __respond("sendDraft", () => {
        attempt += 1;
        // The first attempt fails the way a lost response does.
        return attempt === 1
            ? { data: null, error: { message: "Temporarily unavailable" }, status: 503 }
            : ok(DRAFT({ status: "pending" }));
    });

    const ui = await mount({ draft: DRAFT(), onClose() {}, onSaved() {} });
    await ui.click("Sign & send…");
    await ui.consent();
    await ui.type(NAME_FIELD, "Adv Khan");
    await ui.click("Confirm — sign & send");
    await ui.click("Confirm — sign & send");

    const sends = argsOf("sendDraft");
    assert.equal(sends.length, 2, "expected a retry");
    const keys = sends.map(a => a[2]);
    assert.ok(keys[0], "the send must carry an idempotency key");
    assert.equal(keys[0], keys[1],
        "the retry minted a NEW key — that is a second agreement, which is " +
        "precisely what the key exists to prevent");
});

test("a draft with unsaved edits cannot be sent", async () => {
    const ui = await mount({ draft: DRAFT(), onClose() {}, onSaved() {} });
    await ui.type(BODY_FIELD, "Changed but not saved.");

    const btn = ui.find("Sign & send");
    assert.ok(btn, "the sign button vanished");
    assert.equal(btn.disabled, true,
        "sending unsaved text would let a lawyer sign wording the server does not hold");
    assert.match(ui.text(), /Unsaved changes/);
    assert.equal(argsOf("sendDraft").length, 0);
});

test("a new draft is created against the chosen case, with the client read off it", async () => {
    __respond("listCases", () => ok({ items: [
        { _id: "CASE9", title: "Property dispute", client_id: "C1",
          client_name: "A Client", case_type: "property" },
    ] }));
    __respond("createDraft", () => ok(DRAFT({ case_id: "CASE9" })));

    const ui = await mount({ draft: null, onClose() {}, onSaved() {} });
    await ui.click("Property dispute");
    await ui.type("Retainer agreement", "Retainer");
    await ui.type(BODY_FIELD, "Agreed terms.");
    await ui.click("Save draft");

    assert.deepEqual(argsOf("createDraft")[0], [{
        title: "Retainer", body_html: "Agreed terms.",
        client_id: "C1", case_id: "CASE9",
    }], "the client must be read off the case, never typed");
});

test("a conflict on send is reported and nothing is resent automatically", async () => {
    __respond("sendDraft", () => ({
        data: null, status: 409,
        error: { code: "conflict", message: "This draft changed since you reviewed it." },
    }));

    const ui = await mount({ draft: DRAFT(), onClose() {}, onSaved() {} });
    await ui.click("Sign & send…");
    await ui.consent();
    await ui.type(NAME_FIELD, "Adv Khan");
    await ui.click("Confirm — sign & send");

    assert.equal(argsOf("sendDraft").length, 1,
        "a conflict must not be retried: the wording really did change");
    assert.match(ui.text(), /changed since you reviewed it/i);
});

test("consent is required before anything is sent", async () => {
    const ui = await mount({ draft: DRAFT(), onClose() {}, onSaved() {} });
    await ui.click("Sign & send…");
    await ui.type(NAME_FIELD, "Adv Khan");
    await ui.click("Confirm — sign & send");

    assert.equal(argsOf("sendDraft").length, 0);
    assert.match(ui.text(), /Confirm you intend to sign/i);
});

test("an empty response body does not take the editor down with it", async () => {
    // A 2xx carrying nothing should not happen. The editor holding a lawyer's
    // unsaved text is the worst place to discover it: this used to throw inside
    // the click handler and blank the screen.
    __respond("updateDraft", () => ({ data: null, error: null, status: 200 }));

    const ui = await mount({ draft: DRAFT(), onClose() {}, onSaved() {} });
    await ui.type(BODY_FIELD, "Work in progress.");
    await ui.click("Save changes");

    assert.match(ui.text(), /did not return the saved agreement/i);
    assert.equal(ui.host.querySelector("textarea").value, "Work in progress.",
        "the lawyer's text must survive");
});

// ── the page routes drafts to the editor, not to signing ─────────────────────

test("a draft row opens the editor instead of the signing modal", () => {
    const page = readFileSync(
        new URL("../src/components/lawyer/AgreementsPage.jsx", import.meta.url), "utf8");
    assert.match(page, /if \(a\.isDraft\) \{ setComposing\(a\.raw\); return; \}/,
        "a draft has nothing to sign yet — the only way to sign it is to send it");
    assert.match(page, /raw: a,/,
        "the editor needs the untouched server object; the mapped row is for display");
});

test("no button renders an HTML entity as literal text", () => {
    // `&amp;` inside a JSX text node is decoded; inside a JS string literal it
    // is not. The confirm button read "Confirm — sign &amp; send" on screen.
    const src = readFileSync(
        new URL("../src/components/lawyer/DraftComposer.jsx", import.meta.url), "utf8");
    for (const m of src.matchAll(/"([^"\n]*&[a-z]+;[^"\n]*)"/g)) {
        assert.fail(`HTML entity inside a JS string renders literally: ${m[1]}`);
    }
});
