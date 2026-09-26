/* The lawyer's dispute brief offers the petition only when it was SHARED.
 *
 * Sharing the petition with the assigned lawyer is what grants them access to
 * it. When that share fails, the handoff still completes with
 * `petition_shared: false` — and the brief used to show a working-looking
 * "Download draft petition" button anyway, which then failed. The server
 * reports the share as `petition.shared_with_lawyer`; the button is shown only
 * when that is exactly `true`.
 *
 * The real component is mounted against the API stub.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node",
                    "Event", "CustomEvent", "MutationObserver", "getComputedStyle"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { DisputesInboxPage } = await import("../src/components/lawyer/DisputesInboxPage.jsx");
const { createElement: h } = React;

const ROW = { dispute_id: "d1", state: "ready_for_drafting", category_label: "Illegal possession",
              province: "Punjab", sent_at: "2026-09-20T10:00:00Z", has_petition: true };

function brief(petition) {
    return {
        dispute_id: "d1", state: "ready_for_drafting", client: { name: "A client" },
        assignment: { sent_at: "2026-09-20T10:00:00Z" },
        grievance: {}, jurisdiction: {}, intake: {}, eligibility: {}, hold_reasons: [],
        petition,
    };
}

const PETITION = { document_id: "doc-1", drafted_at: "2026-09-19T10:00:00Z",
                   revision_id: "rev-1", pdf_sha256: "a".repeat(64) };

async function openBrief(petition) {
    api.__reset();
    api.__respond("disputeLawyerInbox", { data: [ROW] });
    api.__respond("disputeBrief", { data: brief(petition) });
    api.__respond("downloadDocumentFile", {});

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    const settle = () => act(async () => { await new Promise(r => setTimeout(r, 20)); });
    await act(async () => { root.render(h(DisputesInboxPage)); });
    await settle();

    const row = [...container.querySelectorAll("*")].find(
        el => el.textContent.trim() === "Open →");
    assert.ok(row, "inbox row not rendered");
    await act(async () => { row.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
    await settle();

    const download = () => [...container.querySelectorAll("button")]
        .find(b => /Download draft petition/.test(b.textContent));
    const page = {
        container, download,
        text: () => container.textContent,
        unmount: async () => { await act(async () => root.unmount()); container.remove(); },
    };
    mounted.add(page);
    return page;
}

const mounted = new Set();
test.afterEach(async () => {
    for (const p of mounted) await p.unmount();
    mounted.clear();
});
test.after(() => { dom.window.close(); });

test("a shared petition gives the lawyer the download action", async () => {
    const p = await openBrief({ ...PETITION, shared_with_lawyer: true });
    const btn = p.download();
    assert.ok(btn, "no download action for a shared petition");

    await act(async () => { btn.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
    const calls = api.__calls("downloadDocumentFile");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].args[0], "doc-1");
    assert.equal(calls[0].args[2].revisionId, "rev-1");
});

for (const [label, value] of [
    ["false (the share failed)", false],
    ["missing", undefined],
    ["the string \"true\"", "true"],
    ["1", 1],
    ["null", null],
]) {
    test(`shared_with_lawyer ${label} → no download action`, async () => {
        const petition = { ...PETITION };
        if (value !== undefined) petition.shared_with_lawyer = value;
        const p = await openBrief(petition);
        assert.equal(p.download(), undefined, "a download was offered for an unshared petition");
        // Said plainly, and not confused with "no petition at all".
        assert.ok(p.container.querySelector('[data-petition-state="not-shared"]'));
        assert.doesNotMatch(p.text(), /No petition drafted/);
        assert.equal(api.__calls("downloadDocumentFile").length, 0);
        });
}

test("no petition drafted is still reported as such, with no action", async () => {
    const p = await openBrief(null);
    assert.equal(p.download(), undefined);
    assert.match(p.text(), /No petition drafted/);
    assert.equal(p.container.querySelector('[data-petition-state="not-shared"]'), null);
});
