/* DocsDrafts after the planner review: type correction (H4), extraction notes
 * (H3), generation recovery across a reload (H2) and fresh keys after a
 * finished failure (M2). Mounted in a real DOM against the API stub. */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node",
                    "Event", "KeyboardEvent", "CustomEvent", "MutationObserver",
                    "getComputedStyle", "DOMParser"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { ToastCtx } = await import("../src/components/shared/Toast.jsx");
const { default: DocsDrafts, promptTemplateOptions } =
    await import("../src/components/client/documents/DocsDrafts.jsx");
const realApi = await import("../src/lib/api.js");

const TEMPLATES = [
    { template_type: "nda", label: "Non-Disclosure Agreement", category: "Corporate", fields: ["party_a"], structured_fields: [], drafting_mode: "ai" },
    { template_type: "legal_notice", label: "Legal Notice", category: "Civil", fields: ["sender_name"], structured_fields: [], drafting_mode: "ai" },
    { template_type: "affidavit", label: "Affidavit", category: "Civil", fields: ["deponent_name"], structured_fields: [], drafting_mode: "manual" },
    { template_type: "labour_demand", label: "Labour Demand", category: "Employment", fields: ["dues"], structured_fields: ["dues"], drafting_mode: "dedicated" },
];

function planOf(overrides = {}) {
    return { id: "plan-1", version: 0, status: "ready", title: "Legal notice draft",
        prompt: "Send a legal notice", template_type: "legal_notice", extraction_status: "ok",
        extraction_notes: [], fields: { sender_name: "Ayesha" }, questions: [], ...overrides };
}

async function mount(props = {}) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(React.createElement(ToastCtx.Provider, { value: { show: () => {} } },
            React.createElement(DocsDrafts, { seed: null, templates: TEMPLATES, cases: [],
                onBack: () => {}, onOpenView: () => {}, onOpenDocument: () => {}, ...props })));
    });
    await settle();
    return { container, unmount: () => act(async () => root.unmount()).then(() => container.remove()) };
}
async function settle() { await act(async () => { await new Promise(r => setTimeout(r, 15)); }); }
const buttons = (el, text) => [...el.querySelectorAll("button")].filter(b => b.textContent.includes(text));
async function click(el) {
    assert.ok(el, "nothing to click");
    await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
    await settle();
}
async function type(input, value) {
    const proto = input.tagName === "TEXTAREA" ? dom.window.HTMLTextAreaElement.prototype : dom.window.HTMLInputElement.prototype;
    await act(async () => {
        Object.getOwnPropertyDescriptor(proto, "value").set.call(input, value);
        input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
}
async function choose(select, value) {
    await act(async () => {
        Object.getOwnPropertyDescriptor(dom.window.HTMLSelectElement.prototype, "value").set.call(select, value);
        select.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
    await settle();
}
async function openPlan(planResponse) {
    api.__respond("createDraftPlanV2", { data: planResponse });
    const p = await mount();
    await type(p.container.querySelector("#docs-need"), "Send a legal notice");
    const create = [...p.container.querySelectorAll("button")]
        .find(b => /Create draft plan|Plan my draft/.test(b.textContent));
    await click(create);
    assert.ok(p.container.querySelector("[data-draft-plan]"), "the plan did not open");
    return p;
}
// The type picker sits at the top of the Fill details panel (no tab to open).
async function showAll() {}

test.beforeEach(() => {
    api.__reset();
    dom.window.sessionStorage.clear();
    api.__respond("myDocumentsV2", { data: { items: [], has_more: false } });
});
test.after(() => dom.window.close());

test("only prompt-supported (AI) templates are offered to the planner", () => {
    assert.deepEqual(promptTemplateOptions(TEMPLATES).map(t => t.template_type), ["nda", "legal_notice"]);
    assert.deepEqual(promptTemplateOptions(null), []);
});

test("an inferred type can be corrected before generation", async () => {
    const p = await openPlan(planOf());
    await showAll(p);
    const select = p.container.querySelector("[data-plan-type]");
    assert.ok(select, "no way to change the document type");
    assert.deepEqual([...select.options].map(o => o.value), ["nda", "legal_notice"],
        "the picker offers a type the planner would refuse");
    api.__respond("answerDraftPlanV2", { data: planOf({ version: 1, template_type: "nda", title: "NDA draft" }) });
    await choose(select, "nda");
    const call = api.__calls("answerDraftPlanV2")[0];
    assert.deepEqual(call.args[1], { expectedVersion: 0, answers: { template_type: "nda" } });
    assert.equal(p.container.querySelector("[data-plan-type]").value, "nda");
    await p.unmount();
});

test("the type picker is gone once the plan is confirmed", async () => {
    const p = await openPlan(planOf({ status: "confirmed" }));
    await showAll(p);
    assert.equal(p.container.querySelector("[data-plan-type]"), null);
    await p.unmount();
});

test("adjusted model output is reported for the user to check", async () => {
    const p = await openPlan(planOf({ extraction_notes: [
        { field: "evidence_list", action: "joined" }, { field: "accused_details", action: "dropped" }] }));
    const note = p.container.querySelector("[data-extraction-notes]");
    assert.ok(note, "no extraction note shown");
    assert.match(note.textContent, /Evidence list was combined from a list/);
    assert.match(note.textContent, /Accused details was left out/);
    await p.unmount();
});

test("a reload mid-generation resumes with the same key", async () => {
    const confirmed = planOf({ status: "confirmed", version: 1 });
    const first = await openPlan(confirmed);
    api.__respond("generateDraftPlanV2", { data: null, status: 503, error: { code: "generation_incomplete", message: "Retry with the same key." } });
    api.__respond("getDraftPlanV2", { data: planOf({ status: "generating", version: 2 }) });
    await click(buttons(first.container, "Generate document")[0]);
    const firstKey = api.__calls("generateDraftPlanV2")[0].args[2];
    assert.ok(firstKey);
    assert.equal(dom.window.sessionStorage.getItem("attorney.draftPlan.current"), "plan-1");
    assert.equal(dom.window.sessionStorage.getItem("attorney.draftPlan.genKey.plan-1"), firstKey);
    await first.unmount();

    // "Reload": a fresh mount restores the plan and its key from this tab.
    const again = await mount();
    assert.ok(again.container.querySelector("[data-draft-plan]"), "the in-progress plan was not restored");
    await click(buttons(again.container, "Retry generation")[0]);
    const calls = api.__calls("generateDraftPlanV2");
    assert.equal(calls[calls.length - 1].args[2], firstKey, "a reload minted a new key and stranded the plan");
    await again.unmount();
});

test("a live lease elsewhere is explained, not shown as a failure", async () => {
    const p = await openPlan(planOf({ status: "confirmed", version: 1 }));
    api.__respond("generateDraftPlanV2", { data: null, status: 409, error: { code: "generation_in_progress", message: "already being generated" } });
    api.__respond("getDraftPlanV2", { data: planOf({ status: "generating", version: 2 }) });
    await click(buttons(p.container, "Generate document")[0]);
    assert.match(p.container.textContent, /still being generated .* Try again in a few minutes/);
    await p.unmount();
});

test("a generated plan clears what was kept for recovery", async () => {
    const p = await openPlan(planOf({ status: "confirmed", version: 1 }));
    api.__respond("generateDraftPlanV2", { data: planOf({ status: "generated", version: 2, generation: { document_id: "doc-1" } }) });
    api.__respond("getDocumentWorkspaceV2", { data: { document_id: "doc-1", title: "Notice", source: "structured_fields",
        template_type: "legal_notice", fields: { sender_name: "Ayesha" }, body_html: null,
        base_revision_id: "r1", base_version: 1, content_epoch: 1, review_status: "none" } });
    api.__respond("getDocumentV2", { data: { id: "doc-1", review_status: "none", current_version: 1,
        current_revision: { revision_id: "r1", pdf_sha256: "a".repeat(64) } } });
    api.__respond("previewRevisionV2", { data: null, error: { message: "no preview in test" } });
    await click(buttons(p.container, "Generate document")[0]);
    assert.equal(dom.window.sessionStorage.getItem("attorney.draftPlan.current"), null);
    assert.equal(dom.window.sessionStorage.getItem("attorney.draftPlan.genKey.plan-1"), null);

    // A failed workspace render spends its key: the next save is a new attempt.
    api.__respond("saveDocumentWorkspaceV2", { data: null, status: 503, error: { code: "generation_failed", message: "failed" } });
    await click(p.container.querySelector("[data-placeholders-toggle]"));
    await type(p.container.querySelector("#ph_sender_name"), "Ayesha Khan");
    await click(buttons(p.container, "Save all changes")[0]);
    await click(buttons(p.container, "Save all changes")[0]);
    const saves = api.__calls("saveDocumentWorkspaceV2");
    assert.equal(saves.length, 2);
    assert.notEqual(saves[0].args[2], saves[1].args[2], "a finished failure was replayed under the same key");
    await p.unmount();
});

test("isRetryable never replays a finished generation failure", () => {
    assert.equal(realApi.isRetryable(503, { code: "generation_failed" }), false);
    assert.equal(realApi.isRetryable(503, { code: "generation_incomplete" }), true);
    assert.equal(realApi.isRetryable(503, null), true);
});
