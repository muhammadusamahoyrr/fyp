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
                    "getComputedStyle", "FileReader", "DOMParser"]) {
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
const { __respond, __reset, __calls } = await import("./support/api-stub.mjs");
const ModAgreements = (await import("../src/components/client/ModAgreements.jsx")).default;
// Page navigation is the client sidebar's since 2026-10-11 (lib/agreementsNav.js).
const agreementsNav = await import("../src/lib/agreementsNav.js");
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
        /* The builder is opened from the client sidebar's "Agreements > Create",
           which asks the module through lib/agreementsNav.js. */
        /* The drafting bar's buttons are icons; each is named by its title. */
        async clickTitle(title) {
            const el = host.querySelector(`button[title="${title}"]`);
            assert.ok(el, `no button titled ${JSON.stringify(title)}`);
            await act(async () => {
                el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
            });
            await act(async () => {});
        },
        async openPage(view) {
            await act(async () => { agreementsNav.requestAgreementsView(view); });
            await act(async () => {});
        },
        /* Opens the builder and writes a line into the rich editor, because
           the first step will not move on without words. */
        async openCreate(html = "<p>Fees are 40% of recovery.</p>") {
            await act(async () => { agreementsNav.requestAgreementsView("create"); });
            await act(async () => {});
            const paper = host.querySelector("[data-ag-paper]");
            if (paper && html) {
                await act(async () => {
                    paper.innerHTML = html;
                    paper.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
                });
            }
        },
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
    await ui.openCreate();
    assert.ok(ui.text().includes("Edit Agreement"),
              "the builder's first step did not render");
});

test("every step of the wizard paints", async () => {
    const ui = await mount();
    await ui.openCreate();

    // Step 1 -> 2. The title defaults, so Next is allowed.
    await ui.clickText("Next");
    assert.ok(ui.text().includes("Signers"), "the Add Signers step did not render");

    // A signer is required before the signature step.
    await ui.clickText("+ Add");
    await ui.clickText("Next");
    assert.ok(ui.text().includes("Your Signature") || ui.text().includes("Draw"),
              "the signature step did not render");
});

test("the review step renders, which is where the send button lives", async () => {
    // This is the exact screen that threw: it reads `sendError`, `sentLinks`
    // and `submitting`, all of which a refactor had deleted.
    const ui = await mount();
    await ui.openCreate();
    await ui.clickText("Next");
    await ui.clickText("+ Add");
    await ui.clickText("Next");

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

    await ui.clickText("Next");
    assert.ok(ui.text().includes("Signing Order"),
              "the review step did not render");
    assert.ok(ui.text().includes("Sign & Send"),
              "the send button is missing from the review step");
});

test("the signature pad offers all three methods inside the builder", async () => {
    const ui = await mount();
    await ui.openCreate();
    await ui.clickText("Next");
    await ui.clickText("+ Add");
    await ui.clickText("Next");

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
    await ui.openPage("all");

    for (const h of ["DOCUMENT", "PARTIES", "STATUS", "PROGRESS", "ACTIONS"]) {
        assert.ok(ui.text().includes(h), `the ${h} column header is missing`);
    }
});

test("a row shows its title, progress and party labels", async () => {
    listWith([row()]);
    const ui = await mount();
    await ui.openPage("all");

    const text = ui.text();
    assert.ok(text.includes("NDA"), "the document title is missing");
    // Three parties, one signed -- the count comes from the server's own
    // signed_count/total_parties, not from counting the rows client-side.
    assert.ok(text.includes("1/3"), "the progress count is missing or wrong");
    assert.ok(text.includes("Sender"), "the sender label is missing");
    assert.ok(/Recipients \(2\)/.test(text),
              "a three-party agreement must not be shown as one recipient");
});

test("an agreement waiting on you reads as Needs you", async () => {
    // Derived from needsMySig, not a stored status: pending AND unsigned by me.
    listWith([row({
        parties: [
            { user_id: ME, full_name: "Test Client", signed: false },
            { user_id: "U2", full_name: "Adv Khan", signed: true },
        ],
        signed_count: 1, total_parties: 2,
    })]);
    const ui = await mount();
    await ui.openPage("all");

    assert.ok(ui.text().includes("Needs you"),
              "an agreement awaiting my signature should say so");
    assert.ok(ui.text().includes("Sign"), "it should offer the sign action");
});

test("an executed agreement is not marked as needing you", async () => {
    listWith([row({
        status: "executed", signed_count: 2, total_parties: 2,
        parties: [
            { user_id: ME, full_name: "Test Client", signed: true },
            { user_id: "U2", full_name: "Adv Khan", signed: true },
        ],
    })]);
    const ui = await mount();
    await ui.openPage("all");

    assert.ok(ui.text().includes("Signed"));
    assert.ok(!ui.text().includes("Needs you"));
    assert.ok(ui.text().includes("2/2"));
});

test("the total is stated, so a full page does not look like the whole list", async () => {
    __respond("listAgreements", () => ({
        data: { items: [row()], total: 25, page: 1, page_size: 20, pages: 2 },
        error: null, status: 200,
    }));
    const ui = await mount();
    await ui.openPage("all");

    assert.ok(/Showing 1 of 25/.test(ui.text()),
              "the row count must name the total, not just what is loaded");
});

// ── the row action menu ────────────────────────────────────────────────────

test("the menu opens and offers open + remove", async () => {
    listWith([row()]);
    const ui = await mount();
    await ui.openPage("all");

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
    await ui.openPage("all");
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
    await ui.openPage("all");
    await ui.clickText("⋮");
    assert.ok(!ui.text().includes("Download PDF"),
              "a pending agreement must not offer a download");

    __reset(); signedIn();
    listWith([row({ status: "executed", signed_count: 2, total_parties: 2 })]);
    ui = await mount();
    await ui.openPage("all");
    await ui.clickText("⋮");
    assert.ok(ui.text().includes("Download PDF"),
              "an executed agreement should offer its PDF");
});

test("removing calls archive, not any delete endpoint", async () => {
    listWith([row()]);
    let archived = null;
    __respond("archiveAgreement", (id) => { archived = id; return ok(fullRow()); });

    const ui = await mount();
    await ui.openPage("all");
    await ui.clickText("⋮");
    await ui.clickText("Remove from my list");

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
    await ui.openPage("all");
    await ui.clickText("Archived");

    assert.ok(seen.some(a => a.archived === true),
              "switching to Archived must request archived rows");
    // And it must not also send a status, or it would show only one of them.
    const archivedCall = seen.find(a => a.archived === true);
    assert.ok(!archivedCall.status,
              "Archived is a view across all statuses, not a status itself");
});

// ── the rich editor (2026-10-11) ────────────────────────────────────────────
//
// The body is `body_format: "html"`. The plain-text line tools that were
// tested here (case, duplicate, move, find and replace) went with the plain
// text editor; formatting is the browser's editing commands, which jsdom does
// not implement, so these tests pin the parts that are ours: the controls, the
// template's arrival, Insert, the sticky bar, and that Review sends exactly the
// server's canonical text, as html.

const paperOf = (ui) => ui.host.querySelector("[data-ag-paper]");

test("the editor is a rich, editable page", async () => {
    listWith([]);
    const ui = await mount();
    await ui.openCreate("");
    const paper = paperOf(ui);
    assert.ok(paper, "the editable page is missing");
    assert.equal(paper.getAttribute("contenteditable"), "true");
    assert.ok(!ui.host.querySelector("textarea"), "the plain-text box should be gone");
});

test("every formatting control is there and named", async () => {
    listWith([]);
    const ui = await mount();
    await ui.openCreate("");
    const titles = new Set([...ui.host.querySelectorAll("[data-ag-tb] button[title]")].map(b => b.title));
    for (const t of ["Undo", "Redo", "Bold", "Italic", "Underline", "Subscript", "Superscript",
                     "Strikethrough", "Align left", "Centre", "Align right", "Justify",
                     "Bulleted list", "Numbered list", "Heading 1", "Heading 2", "Heading 3",
                     "Quote", "Link", "Divider", "Clear formatting"]) {
        assert.ok(titles.has(t), `the toolbar is missing ${t}`);
    }
    assert.ok(ui.host.querySelector('button[aria-label="Font"]'), "no font picker");
    assert.ok(ui.host.querySelector('button[aria-label="Text size"]'), "no size picker");
    assert.ok(ui.host.querySelector('input[type="color"]'), "no colour picker");
    assert.ok(/300,000/.test(ui.text()), "the size limit is not shown");
});

test("the toolbar sticks while the page scrolls", async () => {
    listWith([]);
    const ui = await mount();
    await ui.openCreate("");
    const css = [...ui.host.querySelectorAll("style")].map(x => x.textContent).join("");
    assert.match(css, /\[data-ag-tb\]\{position:sticky;top:0/);
});

test("a template's text arrives as escaped paragraphs", async () => {
    listWith([]);
    const ui = await mount();
    await ui.openPage("templates");
    await ui.clickText("Employment Contract");
    const html = paperOf(ui).innerHTML;
    assert.ok(html.startsWith("<p>[UNREVIEWED SAMPLE - NOT LEGAL CONTENT]</p>"),
              "each line of the template should be its own paragraph");
});

test("Insert puts a placeholder into the text", async () => {
    listWith([]);
    const ui = await mount();
    await ui.openCreate("<p>Between</p>");
    await ui.clickText("Insert");
    await ui.clickText("[PARTY NAME]");
    assert.ok(paperOf(ui).textContent.includes("[PARTY NAME]"));
});

test("the font picker offers its families, each in its own face", async () => {
    listWith([]);
    const ui = await mount();
    await ui.openCreate("");
    const picker = ui.host.querySelector('button[aria-label="Font"]');
    await act(async () => { picker.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
    const opts = [...dom.window.document.querySelectorAll('[role="listbox"][aria-label="Font"] [role="option"]')];
    assert.ok(opts.length >= 9, `only ${opts.length} fonts offered`);
    assert.ok(opts.some(o => o.textContent.includes("Verdana") && /Verdana/.test(o.getAttribute("style") || "")));
});

test("the title is edited in the header, not in a separate box", async () => {
    listWith([]);
    const ui = await mount();
    await ui.openCreate("");
    const field = ui.host.querySelector('input[aria-label="Agreement title"]');
    assert.ok(field, "the header title field is missing");
    assert.ok(!ui.text().includes("Agreement Title"), "the old title box is still there");
});

test("the first step will not move on without words", async () => {
    listWith([]);
    const ui = await mount();
    await ui.openCreate("<p><br></p>");
    await ui.clickText("Next");
    assert.ok(!ui.text().includes("Search verified lawyers"), "it moved on with an empty agreement");
});

async function toReview(ui) {
    await ui.clickText("Next");
    await ui.clickText("+ Add");
    await ui.clickText("Next");
    await ui.clickText("Type");
    const input = [...dom.window.document.querySelectorAll("input")]
        .find(i => (i.placeholder || "").startsWith("Type your name"));
    const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set;
    await act(async () => {
        setter.call(input, "Test Client");
        input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
    await ui.clickText("Next");
    await act(async () => {});
}

test("Review shows the server's canonical text and sends exactly that, as html", async () => {
    listWith([]);
    __respond("previewAgreementBody", () => ok({ body_html: "<p>CANONICAL <b>TEXT</b></p>", has_text: true }));
    __respond("createAgreement", () => ({ data: null, error: { message: "stop here" }, status: 400 }));
    const ui = await mount();
    await ui.openCreate('<p onclick="x()">raw</p>');
    await toReview(ui);

    assert.equal(__calls("previewAgreementBody").at(-1).args[0], '<p onclick="x()">raw</p>',
                 "Review must ask the server for the canonical form of what was written");
    assert.ok(ui.text().includes("CANONICAL TEXT"), "Review must show the server's form");

    await ui.clickText("Sign & Send");
    const sent = __calls("createAgreement").at(-1)?.args[0];
    assert.ok(sent, "nothing was sent");
    assert.equal(sent.body_html, "<p>CANONICAL <b>TEXT</b></p>");
    assert.equal(sent.body_format, "html");
});

test("a body the server could not check is not sent", async () => {
    listWith([]);
    __respond("previewAgreementBody", () => ({ data: null, error: { message: "Could not check" }, status: 500 }));
    const ui = await mount();
    await ui.openCreate();
    await toReview(ui);
    assert.ok(ui.text().includes("Could not check"));
    await ui.clickText("Sign & Send");
    assert.equal(__calls("createAgreement").length, 0, "an unchecked body was sent");
});
