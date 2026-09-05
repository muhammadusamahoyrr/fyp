/* MyDocumentsPanel — the real component, rendered into a real DOM.
 *
 * Everything else in this suite tests hooks. That was a genuine limitation:
 * the hook can be perfect while the component wires it up wrongly, and the only
 * thing standing between those two was `next build`, which checks that the file
 * parses.
 *
 * The obstacles were JSX and the `@/` alias, both of which are build concerns
 * rather than reasons to stop testing what ships. `tests/support/jsx-loader.mjs`
 * removes them, and the API client is stubbed so a mounted component cannot
 * reach the network.
 *
 * These assert on TEXT AND ELEMENTS the user would see — not on internal state.
 * The specific failure being guarded against is a list that renders "no
 * documents" while documents are still loading, or after a request failed,
 * which tells a client their work is gone.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>",
                      { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, {
        value, writable: true, configurable: true,
    });
}
for (const name of ["window", "document", "navigator", "HTMLElement",
                    "Element", "Node", "Event", "CustomEvent",
                    "MutationObserver", "getComputedStyle"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const MyDocumentsPanel = (await import(
    "../src/components/client/MyDocumentsPanel.jsx")).default;

const { createElement: h } = React;

/* A theme object with the keys the panel reads. */
const T = {
    cardBg: "#fff", border: "#ddd", text: "#111", textMuted: "#666",
    textFaint: "#999", primary: "#06f", warn: "#b60", danger: "#c00",
};

function row(id, extra = {}) {
    return {
        id, title: `Notice ${id}`, review_status: "none",
        revision_id: `rev-${id}`, pdf_sha256: "a".repeat(64),
        version: 1, downloadable: true, ...extra,
    };
}

async function mount(props = {}) {
    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(MyDocumentsPanel, { t: T, ...props }));
    });
    return {
        container,
        text: () => container.textContent,
        buttons: () => [...container.querySelectorAll("button")]
            .map(b => b.textContent),
        click: async label => {
            const btn = [...container.querySelectorAll("button")]
                .find(b => b.textContent.includes(label));
            assert.ok(btn, `no button matching ${label!== undefined ? label : ""}`);
            await act(async () => { btn.dispatchEvent(
                new dom.window.MouseEvent("click", { bubbles: true })); });
        },
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

test.beforeEach(() => api.__reset());

/* ── the three states, as the user sees them ──────────────────────────────── */

test("an empty account says so, and does not imply loss", async () => {
    api.__respond("myDocumentsV2", { data: { items: [], has_more: false } });
    const p = await mount();

    assert.match(p.text(), /have not generated any documents yet/i);
    await p.unmount();
});

test("a failed load says the documents are not gone", async () => {
    // The wording matters here more than the mechanism. "No documents" after a
    // network error tells a client their work has been lost.
    api.__respond("myDocumentsV2", { error: { message: "Network unreachable" } });
    const p = await mount();

    const text = p.text();
    assert.match(text, /could not load/i);
    assert.match(text, /does not mean they\s+are gone/i);
    assert.match(text, /Network unreachable/);
    assert.doesNotMatch(text, /have not generated any documents yet/i);
    await p.unmount();
});

test("a failed load offers a retry that actually re-requests", async () => {
    api.__respond("myDocumentsV2", { error: { message: "Network" } });
    const p = await mount();
    assert.equal(api.__calls("myDocumentsV2").length, 1);

    api.__respond("myDocumentsV2", { data: { items: [row("a")], has_more: false } });
    await p.click("Try again");

    assert.equal(api.__calls("myDocumentsV2").length, 2);
    assert.match(p.text(), /Notice a/);
    await p.unmount();
});

test("documents render with their title and status", async () => {
    api.__respond("myDocumentsV2", {
        data: { items: [row("a"), row("b", { review_status: "submitted" })],
                has_more: false },
    });
    const p = await mount();

    assert.match(p.text(), /Notice a/);
    assert.match(p.text(), /Notice b/);
    assert.match(p.text(), /Under Review/);
    await p.unmount();
});

/* ── a migration recovery state is explained, not just labelled ───────────── */

test("a recovery document shows the server's explanation", async () => {
    api.__respond("myDocumentsV2", {
        data: {
            items: [row("a", {
                review_status: "migration_unrecoverable",
                recovery: {
                    state: "migration_unrecoverable",
                    headline: "Needs to be sent again",
                    explanation: "The version that was sent could not be recovered.",
                    next_action: "regenerate_and_resubmit", blocks_use: true,
                },
            })],
            has_more: false,
        },
    });
    const p = await mount();

    assert.match(p.text(), /Needs to be sent again/);
    assert.match(p.text(), /could not be recovered/);
    // And never dressed up as progress.
    assert.doesNotMatch(p.text(), /Under Review/);
    await p.unmount();
});

/* ── what a row offers ────────────────────────────────────────────────────── */

test("an ungenerated row offers no download and says why", async () => {
    api.__respond("myDocumentsV2", {
        data: { items: [row("a", { revision_id: null, pdf_sha256: null,
                                   downloadable: false })], has_more: false },
    });
    const p = await mount();

    assert.ok(!p.buttons().some(b => b.includes("Download")),
              "offered a download that would 409");
    assert.match(p.text(), /not been generated yet/);
    await p.unmount();
});

test("a download sends the exact revision and its hash", async () => {
    // They are the pair the endpoint compares. Sending one without the other
    // produces a failure the user can do nothing about.
    api.__respond("myDocumentsV2", {
        data: { items: [row("a")], has_more: false },
    });
    const p = await mount();
    await p.click("Download");

    const [call] = api.__calls("downloadDocumentFile");
    assert.ok(call, "no download was attempted");
    assert.equal(call.args[0], "a");
    assert.equal(call.args[2].revisionId, "rev-a");
    assert.equal(call.args[2].expectedPdfSha256, "a".repeat(64));
    await p.unmount();
});

/* ── pagination ───────────────────────────────────────────────────────────── */

test("older documents load and append", async () => {
    api.__respond("myDocumentsV2", {
        data: { items: [row("a")], has_more: true, next_cursor: "CURSOR-1" },
    });
    const p = await mount();
    assert.ok(p.buttons().some(b => b.includes("Show older")));

    api.__respond("myDocumentsV2", {
        data: { items: [row("b")], has_more: false },
    });
    await p.click("Show older");

    assert.match(p.text(), /Notice a/);
    assert.match(p.text(), /Notice b/);
    assert.equal(api.__calls("myDocumentsV2")[1].args[0].cursor, "CURSOR-1");
    await p.unmount();
});

test("no pagination control when there is nothing more", async () => {
    api.__respond("myDocumentsV2", {
        data: { items: [row("a")], has_more: false },
    });
    const p = await mount();
    assert.ok(!p.buttons().some(b => b.includes("Show older")));
    await p.unmount();
});

/* ── opening a document ───────────────────────────────────────────────────── */

test("opening restores revision, hash, status and recovery", async () => {
    api.__respond("myDocumentsV2", {
        data: { items: [row("a")], has_more: false },
    });
    api.__respond("getDocumentV2", {
        data: {
            id: "a", title: "Notice a", review_status: "returned",
            current_version: 3,
            current_revision: { revision_id: "rev-a3", pdf_sha256: "c".repeat(64) },
            recovery: null,
        },
    });

    const opened = [];
    const p = await mount({ onOpen: state => opened.push(state) });
    await p.click("Open");

    assert.equal(opened.length, 1);
    assert.equal(opened[0].docId, "a");
    assert.equal(opened[0].docRevisionId, "rev-a3");
    assert.equal(opened[0].docPdfSha256, "c".repeat(64));
    assert.equal(opened[0].reviewStatus, "returned");
    assert.equal(opened[0].step, 3);
    await p.unmount();
});

test("opening a document that has gone does not call back", async () => {
    api.__respond("myDocumentsV2", {
        data: { items: [row("a")], has_more: false },
    });
    api.__respond("getDocumentV2", { error: { code: "not_found" } });

    const opened = [];
    const p = await mount({ onOpen: state => opened.push(state) });
    await p.click("Open");

    assert.deepEqual(opened, [], "restored from a document that does not exist");
    await p.unmount();
});

/* ── the panel never scopes by owner itself ───────────────────────────────── */

test("the component sends no owner id", async () => {
    api.__respond("myDocumentsV2", { data: { items: [], has_more: false } });
    const p = await mount();

    for (const call of api.__calls("myDocumentsV2")) {
        const [args] = call.args;
        assert.ok(!("client_id" in args), "the component scoped the query itself");
        assert.ok(!("owner_id" in args));
    }
    await p.unmount();
});
