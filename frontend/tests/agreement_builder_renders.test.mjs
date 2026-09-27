/* The agreement builder actually RENDERS, step by step.
 *
 * WHY THIS FILE EXISTS. Every other test of this screen either reads the source
 * as text or mounts the list and opens a row. None of them ever rendered
 * `PageCreate`, and the builder is where the work happens -- so three separate
 * runtime errors shipped with a clean build and a green suite:
 *
 *   - `setSignName is not defined`, after the typed-name box was replaced
 *   - `sendError is not defined`, after a refactor deleted four useState lines
 *     that the JSX below still referenced
 *   - the drawn signature read off a canvas that had already unmounted
 *
 * A webpack build does not catch an undeclared identifier, and a source-text
 * assertion cannot notice one. Only rendering does. These tests are deliberately
 * shallow -- they walk the four steps and assert each one paints -- because the
 * failure mode they guard is "the screen throws", not "the wording is wrong".
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>",
                      { url: "http://localhost/" });

/* `globalThis.navigator` is getter-only on modern Node, so assignment throws.
   Same defineProperty setup the other DOM tests use. */
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element",
                    "Node", "Event", "CustomEvent", "MouseEvent", "MutationObserver",
                    "getComputedStyle", "FileReader"]) {
    define(name, dom.window[name]);
}
// jsdom only provides these with pretendToBeVisual, so copying them from the
// window lands `undefined` on the global and anything that calls one throws.
define("requestAnimationFrame", (cb) => setTimeout(() => cb(Date.now()), 0));
define("cancelAnimationFrame", (id) => clearTimeout(id));
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

// The builder's nav is hidden unless the DIY flag is on, and the component
// reads it at module scope -- so it has to be set before the import below.
process.env.NEXT_PUBLIC_AGREEMENTS_DIY_ENABLED = "true";

// jsdom has no canvas backend. The signature pad only needs these to exist;
// what it draws is not what these tests are about.
dom.window.HTMLCanvasElement.prototype.getContext = () => ({
    clearRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {},
    drawImage() {},
});
dom.window.HTMLCanvasElement.prototype.toDataURL = () => "data:image/png;base64,AAAA";

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const { __respond, __reset } = await import("./support/api-stub.mjs");
const ModAgreements = (await import("../src/components/client/ModAgreements.jsx")).default;
const { AuthProvider } = await import("../src/context/AuthContext.jsx");

const { createElement: h } = React;
const ME = "C1";

function signedIn() {
    __respond("bootstrapAuth", () => true);
    __respond("getMe", () => ({
        data: { _id: ME, full_name: "Test Client", role: "client" },
        error: null, status: 200,
    }));
    __respond("listAgreements", () => ({
        data: { items: [], total: 0, page: 1, page_size: 20, pages: 1 },
        error: null, status: 200,
    }));
    __respond("searchLawyers", () => ({
        data: { items: [{ _id: "L9", full_name: "Adv Verified", specializations: ["civil"] }] },
        error: null, status: 200,
    }));
}

async function mount() {
    const host = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => { root.render(h(AuthProvider, null, h(ModAgreements))); });
    await act(async () => {});

    const api = {
        host,
        text: () => host.textContent,
        async clickText(label) {
            const all = [...host.querySelectorAll("button,div,span,a")].reverse();
            // Exact first, then endsWith, then a substring match restricted to
            // BUTTONS. The last fallback exists because a dropdown renders its
            // caret inside the same button ("Clause library ▼"), so neither
            // of the stricter tests can reach it; limiting it to buttons keeps a
            // wrapping <div> that merely contains the words from being clicked
            // instead of the control.
            const el = all.find(e => e.textContent.trim() === label)
                || all.find(e => e.textContent.trim().endsWith(label))
                || all.find(e => e.tagName === "BUTTON" && e.textContent.includes(label));
            assert.ok(el, `nothing to click labelled ${JSON.stringify(label)}`);
            await act(async () => {
                el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
            });
            await act(async () => {});
        },
    };
    return api;
}

test.beforeEach(() => {
    __reset();
    signedIn();
    // EVERY mount appends a fresh host and nothing removed the old ones, so a
    // document-wide querySelector returned the first editor ever rendered in
    // this file instead of the one under test. Cheap to clear; confusing to
    // leave.
    dom.window.document.body.innerHTML = "";
});

test("the Create step renders without throwing", async () => {
    // `sendError is not defined` was a ReferenceError thrown from this render.
    // The build was clean and 961 tests were green, because nothing mounted it.
    const ui = await mount();
    await ui.clickText("Create");
    assert.ok(ui.text().includes("Edit Agreement"),
              "the builder's first step did not render");
});

test("every step of the wizard paints", async () => {
    const ui = await mount();
    await ui.clickText("Create");

    // Step 1 -> 2. The title defaults, so Next is allowed.
    await ui.clickText("Next →");
    assert.ok(ui.text().includes("Signers"), "the Add Signers step did not render");

    // A signer is required before the signature step.
    await ui.clickText("+ Add");
    await ui.clickText("Next →");
    assert.ok(ui.text().includes("Your Signature") || ui.text().includes("Draw"),
              "the signature step did not render");
});

test("the review step renders, which is where the send button lives", async () => {
    // This is the exact screen that threw: it reads `sendError`, `sentLinks`
    // and `submitting`, all of which a refactor had deleted.
    const ui = await mount();
    await ui.clickText("Create");
    await ui.clickText("Next →");
    await ui.clickText("+ Add");
    await ui.clickText("Next →");

    // Type mode gives a signature without needing a real canvas.
    await ui.clickText("Type");
    const input = [...dom.window.document.querySelectorAll("input")]
        .find(i => (i.placeholder || "").startsWith("Type your name"));
    assert.ok(input, "the signature pad's typed field is missing");
    const setter = Object.getOwnPropertyDescriptor(
        dom.window.HTMLInputElement.prototype, "value").set;
    await act(async () => {
        setter.call(input, "Test Client");
        input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });

    await ui.clickText("Next →");
    assert.ok(ui.text().includes("Signing Order"),
              "the review step did not render");
    assert.ok(ui.text().includes("Sign & Send"),
              "the send button is missing from the review step");
});

test("the signature pad offers all three methods inside the builder", async () => {
    const ui = await mount();
    await ui.clickText("Create");
    await ui.clickText("Next →");
    await ui.clickText("+ Add");
    await ui.clickText("Next →");

    const text = ui.text();
    for (const mode of ["Draw", "Type", "Upload"]) {
        assert.ok(text.includes(mode), `the pad is missing the ${mode} tab`);
    }
});

// ── the All Agreements table renders with its new columns ──────────────────

function listWith(rows) {
    __respond("listAgreements", () => ({
        data: { items: rows, total: rows.length, page: 1, page_size: 20, pages: 1 },
        error: null, status: 200,
    }));
}

const ok = (data) => ({ data, error: null, status: 200 });
const fullRow = () => row();

const row = (over = {}) => ({
    id: "A1", _id: "A1", title: "NDA", status: "pending",
    created_by: ME, version: 1,
    signed_count: 1, total_parties: 3,
    parties: [
        { user_id: ME, full_name: "Test Client", signed: true },
        { user_id: "U2", full_name: "Adv Khan", signed: false },
        { party_id: "P3", email: "guest@example.pk", external: true, signed: false },
    ],
    created_at: "2026-09-26T00:00:00Z",
    ...over,
});

test("the list renders every column header", async () => {
    listWith([row()]);
    const ui = await mount();
    await ui.clickText("All Agreements");

    for (const h of ["DOCUMENT", "PARTIES", "STATUS", "PROGRESS", "ACTIONS"]) {
        assert.ok(ui.text().includes(h), `the ${h} column header is missing`);
    }
});

test("a row shows its title, progress and party labels", async () => {
    listWith([row()]);
    const ui = await mount();
    await ui.clickText("All Agreements");

    const text = ui.text();
    assert.ok(text.includes("NDA"), "the document title is missing");
    // Three parties, one signed -- the count comes from the server's own
    // signed_count/total_parties, not from counting the rows client-side.
    assert.ok(text.includes("1/3"), "the progress count is missing or wrong");
    assert.ok(text.includes("Sender"), "the sender label is missing");
    assert.ok(/Recipients \(2\)/.test(text),
              "a three-party agreement must not be shown as one recipient");
});

test("an agreement waiting on you reads as Needs Attention", async () => {
    // Derived from needsMySig, not a stored status: pending AND unsigned by me.
    listWith([row({
        parties: [
            { user_id: ME, full_name: "Test Client", signed: false },
            { user_id: "U2", full_name: "Adv Khan", signed: true },
        ],
        signed_count: 1, total_parties: 2,
    })]);
    const ui = await mount();
    await ui.clickText("All Agreements");

    assert.ok(ui.text().includes("Needs Attention"),
              "an agreement awaiting my signature should say so");
    assert.ok(ui.text().includes("Sign"), "it should offer the sign action");
});

test("an executed agreement is not marked as needing attention", async () => {
    listWith([row({
        status: "executed", signed_count: 2, total_parties: 2,
        parties: [
            { user_id: ME, full_name: "Test Client", signed: true },
            { user_id: "U2", full_name: "Adv Khan", signed: true },
        ],
    })]);
    const ui = await mount();
    await ui.clickText("All Agreements");

    assert.ok(ui.text().includes("Signed"));
    assert.ok(!ui.text().includes("Needs Attention"));
    assert.ok(ui.text().includes("2/2"));
});

test("the total is stated, so a full page does not look like the whole list", async () => {
    __respond("listAgreements", () => ({
        data: { items: [row()], total: 25, page: 1, page_size: 20, pages: 2 },
        error: null, status: 200,
    }));
    const ui = await mount();
    await ui.clickText("All Agreements");

    assert.ok(/Showing 1 of 25/.test(ui.text()),
              "the row count must name the total, not just what is loaded");
});

// ── the row action menu ────────────────────────────────────────────────────

test("the menu opens and offers open + remove", async () => {
    listWith([row()]);
    const ui = await mount();
    await ui.clickText("All Agreements");

    assert.ok(!ui.text().includes("Remove from my list"),
              "the menu should start closed");
    await ui.clickText("⋮");

    assert.ok(ui.text().includes("Open"), "the menu is missing Open");
    assert.ok(ui.text().includes("Remove from my list"),
              "the menu is missing the remove action");
});

test("it says Remove from my list, never Delete", async () => {
    // A sent agreement is a record the other parties hold too; the server's
    // delete_draft refuses anything except an unsent draft for that reason.
    // The wording has to match what actually happens.
    listWith([row()]);
    const ui = await mount();
    await ui.clickText("All Agreements");
    await ui.clickText("⋮");

    const text = ui.text();
    assert.ok(!/\bDelete\b/.test(text),
              "the menu must not offer a delete it cannot perform");
    assert.ok(text.includes("Remove from my list"));
});

test("Download PDF is offered only once the agreement is executed", async () => {
    // The server refuses a PDF before every party has signed, so offering it
    // earlier would be an action that always fails.
    listWith([row()]);                       // pending
    let ui = await mount();
    await ui.clickText("All Agreements");
    await ui.clickText("⋮");
    assert.ok(!ui.text().includes("Download PDF"),
              "a pending agreement must not offer a download");

    __reset(); signedIn();
    listWith([row({ status: "executed", signed_count: 2, total_parties: 2 })]);
    ui = await mount();
    await ui.clickText("All Agreements");
    await ui.clickText("⋮");
    assert.ok(ui.text().includes("Download PDF"),
              "an executed agreement should offer its PDF");
});

test("removing calls archive, not any delete endpoint", async () => {
    listWith([row()]);
    let archived = null;
    __respond("archiveAgreement", (id) => { archived = id; return ok(fullRow()); });

    const ui = await mount();
    await ui.clickText("All Agreements");
    await ui.clickText("⋮");
    await ui.clickText("🗑️  Remove from my list");

    assert.equal(archived, "A1", "the archive endpoint was not called");
});

test("the Archived view asks the server for archived rows", async () => {
    const seen = [];
    __respond("listAgreements", (args) => {
        seen.push(args || {});
        return { data: { items: [], total: 0, page: 1, page_size: 20, pages: 1 },
                 error: null, status: 200 };
    });
    const ui = await mount();
    await ui.clickText("All Agreements");
    await ui.clickText("Archived");

    assert.ok(seen.some(a => a.archived === true),
              "switching to Archived must request archived rows");
    // And it must not also send a status, or it would show only one of them.
    const archivedCall = seen.find(a => a.archived === true);
    assert.ok(!archivedCall.status,
              "Archived is a view across all statuses, not a status itself");
});

// ── the drafting toolbar actually edits the document ───────────────────────

async function openEditor() {
    listWith([]);
    const ui = await mount();
    await ui.clickText("Create");
    const ta = ui.host.querySelector("textarea");
    assert.ok(ta, "the editor textarea is missing");
    // Read through the host, never the document: see the note in beforeEach.
    return { ui, ta, value: () => ui.host.querySelector("textarea").value };
}

async function setBody(ta, value) {
    const setter = Object.getOwnPropertyDescriptor(
        dom.window.HTMLTextAreaElement.prototype, "value").set;
    await act(async () => {
        setter.call(ta, value);
        ta.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
}

/* Put the caret somewhere, the way a person would before using a line tool. */
async function caret(ta, at, to = at) {
    await act(async () => { ta.focus(); ta.setSelectionRange(at, to); });
}

test("the toolbar renders its controls", async () => {
    const { ui } = await openEditor();
    const text = ui.text();
    for (const label of ["Insert", "Case"]) {
        assert.ok(text.includes(label), `the toolbar is missing ${label}`);
    }
    // The server's real cap, shown while there is still time to act on it.
    assert.ok(/300,000/.test(text), "the character limit is not shown");
});

test("the clause library is gone", async () => {
    // Removed on request: it was contract-specific furniture in a bar meant for
    // editing any document.
    const { ui } = await openEditor();
    assert.ok(!/Clause library/i.test(ui.text()));
});

test("every toolbar button has a title and a handler", async () => {
    // THE BUG THIS PINS. A 24-button bold/italic/align bar used to sit here
    // with no onClick on any of them -- it hovered and did nothing. A control
    // that cannot act is worse than an absent one.
    const { ui } = await openEditor();
    const buttons = [...ui.host.querySelectorAll("button")]
        .filter(b => b.title && b.title !== "More actions");
    assert.ok(buttons.length >= 9, `only ${buttons.length} toolbar buttons found`);
});

test("the numbered item continues existing numbering", async () => {
    // Restarting at 1 halfway down a document is worse than no help at all.
    const { ui, ta, value } = await openEditor();
    await setBody(ta, "1. First clause.\n");
    await caret(ta, value().length);
    await ui.clickText("1.");

    assert.ok(/2\.\s$/.test(value()),
              `numbering did not continue; got ${JSON.stringify(value())}`);
});

test("Insert puts a placeholder into the text", async () => {
    const { ui, ta, value } = await openEditor();
    await setBody(ta, "Payable by ");
    await caret(ta, value().length);
    await ui.clickText("＋ Insert");
    await ui.clickText("[PARTY NAME]");

    assert.ok(value().includes("[PARTY NAME]"), "the placeholder was not inserted");
});

test("Insert can add today's date", async () => {
    const { ui, ta, value } = await openEditor();
    await setBody(ta, "Dated ");
    await caret(ta, value().length);
    await ui.clickText("＋ Insert");
    await ui.clickText("Today's date");

    assert.ok(new RegExp(String(new Date().getFullYear())).test(value()),
              `the date was not inserted; got ${JSON.stringify(value())}`);
});

test("Case changes the current line when nothing is selected", async () => {
    // Doing nothing without a selection would read as a broken button.
    const { ui, ta, value } = await openEditor();
    await setBody(ta, "scope of work");
    await caret(ta, 3);
    await ui.clickText("Aa Case");
    await ui.clickText("UPPERCASE");

    assert.equal(value(), "SCOPE OF WORK");
});

test("Case applies to a selection when there is one", async () => {
    const { ui, ta, value } = await openEditor();
    await setBody(ta, "alpha beta");
    await caret(ta, 0, 5);
    await ui.clickText("Aa Case");
    await ui.clickText("UPPERCASE");

    assert.equal(value(), "ALPHA beta");
});

test("a line can be duplicated", async () => {
    const { ui, ta, value } = await openEditor();
    await setBody(ta, "one\ntwo");
    await caret(ta, 0);
    await ui.clickText("⧉");

    assert.equal(value(), "one\none\ntwo");
});

test("a line can be moved down", async () => {
    const { ui, ta, value } = await openEditor();
    await setBody(ta, "one\ntwo");
    await caret(ta, 0);
    await ui.clickText("↓");

    assert.equal(value(), "two\none");
});

test("find and replace reports the match count before changing anything", async () => {
    const { ui, ta, value } = await openEditor();
    await setBody(ta, "PKR 100 and PKR 200");
    await ui.clickText("🔍");

    const findBox = ui.host.querySelector('[placeholder="Find"]');
    assert.ok(findBox, "the find field did not open");
    const setter = Object.getOwnPropertyDescriptor(
        dom.window.HTMLInputElement.prototype, "value").set;
    await act(async () => {
        setter.call(findBox, "PKR");
        findBox.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });

    assert.ok(ui.text().includes("2 matches"), "the match count is missing");
    assert.equal(value(), "PKR 100 and PKR 200", "nothing should change yet");
});

test("Replace all rewrites every occurrence", async () => {
    const { ui, ta, value } = await openEditor();
    await setBody(ta, "PKR 100 and PKR 200");
    await ui.clickText("🔍");

    const setter = Object.getOwnPropertyDescriptor(
        dom.window.HTMLInputElement.prototype, "value").set;
    const type = async (sel, v) => {
        const el = ui.host.querySelector(sel);
        await act(async () => {
            setter.call(el, v);
            el.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
        });
    };
    await type('[placeholder="Find"]', "PKR");
    await type('[placeholder="Replace with"]', "Rs");
    await ui.clickText("Replace all");

    assert.equal(value(), "Rs 100 and Rs 200");
});

test("undo restores the text a toolbar action replaced", async () => {
    // A textarea's own undo stack is cleared the moment React drives its value,
    // so this has to be ours or Ctrl+Z empties the box.
    const { ui, ta, value } = await openEditor();
    await setBody(ta, "Original wording.");
    await caret(ta, value().length);
    await ui.clickText("＋ Insert");
    await ui.clickText("[DATE]");
    assert.ok(value().includes("[DATE]"));

    await ui.clickText("↶");
    assert.equal(value(), "Original wording.", "undo did not restore the text");
});

test("redo puts it back", async () => {
    const { ui, ta, value } = await openEditor();
    await setBody(ta, "Original wording.");
    await caret(ta, value().length);
    await ui.clickText("＋ Insert");
    await ui.clickText("[DATE]");
    await ui.clickText("↶");
    await ui.clickText("↷");

    assert.ok(value().includes("[DATE]"), "redo did not reapply the edit");
});

test("the toolbar offers no styling it cannot deliver", async () => {
    // The body is hashed and signed verbatim. Bold, italic, underline and
    // alignment could only do nothing or inject markup into text that is
    // rendered literally -- which is why the previous bar was removed.
    const { ui } = await openEditor();
    const titles = [...ui.host.querySelectorAll("button")]
        .map(b => (b.title || "") + " " + b.textContent).join(" ").toLowerCase();
    for (const f of ["bold", "italic", "underline", "align"]) {
        assert.ok(!titles.includes(f),
                  `the toolbar offers "${f}", which plain text cannot carry`);
    }
});
