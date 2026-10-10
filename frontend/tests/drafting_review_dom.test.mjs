/* The INTERNAL drafting-question review (DraftingReview), mounted in a real
 * DOM against the API stub. Pins the owner's conditions of 2026-10-04: the
 * server's evaluation banner is always shown and the screen fails closed
 * without it; fixed scanner labels, "Not located automatically" neutral,
 * "Missing" only as the reviewer's internal outcome; the AI signal separate;
 * decisions append-only and sent with the status the screen showed;
 * evidence clickable, withheld evidence marked; nothing on the client side. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node",
                    "Event", "KeyboardEvent", "CustomEvent", "MutationObserver",
                    "getComputedStyle", "DOMParser", "File"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { ToastCtx } = await import("../src/components/lawyer/Toast.jsx");
const review = await import("../src/components/analyzer/DraftingReview.jsx");
const live = await import("../src/components/analyzer/AnalyzerLive.jsx");

const T = { text: "#111", textMuted: "#666", border: "#ccc", inputBg: "#fff", card: "#fff" };
const TEXT = "TENANCY AGREEMENT\nRent is Rs. 85,000 per month.\nSigned by the parties.";
const s1 = { sentence_id: "s1", clause_id: "c1", start: 18, end: 47 };
const s2 = { sentence_id: "s2", clause_id: "c2", start: 48, end: 70 };
const DOC = { text: TEXT, clauses: [], sentences: [s1, s2], text_version: {} };
const EVALUATION = {
    engine: "ai-hypothesis.1", status: "not_passed", passed: false, production_approved: false,
    mode: "internal_review_only", banner: "Evaluation not passed — internal review only.",
    dataset: { name: "validation-2", role: "validation", documents: 70 },
    attention_precision: 0.861, attention_recall: 0.941, weak_questions: ["leave", "rent_due"],
};
const AI_NONE = { label: "AI review (separate from the automatic check)", signal: null,
    signal_label: "AI review unavailable", explanation: null, unavailable_reason: "not_requested" };
function q(id, status, extra = {}) {
    return { question_id: id, question: `Question ${id}?`, scope: "tenancy", polarity: "attention_if_absent",
        status, status_label: review.SCANNER_LABEL[status], reason_code: null, evidence: [],
        evidence_withheld: null, ai_review: AI_NONE, decisions: [], lawyer_outcome: null, ...extra };
}
function body(questions, extra = {}) {
    return { run_id: "r1", evaluation: EVALUATION, mode: "internal_review_only",
        engine_labels: ["Automatic drafting check — no AI", "No law applied", "Not lawyer reviewed"],
        dismiss_reasons: ["scanner_status_wrong", "evidence_wrong", "question_not_applicable", "other"],
        text_intact: true, questions, ...extra };
}
const FOUND = q("rent_amount", "present", {
    evidence: [{ clause_id: "c1", sentences: [{ ...s1, text: TEXT.slice(18, 47), withheld: null }] }],
    ai_review: { ...AI_NONE, signal: "does_not_support", signal_label: "AI review: may not support" },
});
const NOT_LOCATED = q("security_deposit", "not_located");
const UNCLEAR = q("rent_due", "ambiguous");
const FLAGGED = q("term_duration", "unable_to_determine", { reason_code: "evidence_flagged",
    evidence_withheld: "flagged_as_embedded_instructions" });
const STANDARD = body([FOUND, NOT_LOCATED, UNCLEAR, FLAGGED]);

async function settle(ms = 15) { await act(async () => { await new Promise(r => setTimeout(r, ms)); }); }
async function mount(Component, props) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(React.createElement(ToastCtx.Provider, { value: { show: () => {} } },
            React.createElement(Component, props)));
    });
    await settle();
    return { container, unmount: () => act(async () => root.unmount()).then(() => container.remove()) };
}
async function click(el) {
    assert.ok(el, "nothing to click");
    await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
    await settle();
}
async function choose(select, value) {
    await act(async () => {
        Object.getOwnPropertyDescriptor(dom.window.HTMLSelectElement.prototype, "value").set.call(select, value);
        select.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
    await settle();
}
async function screen(data = STANDARD) {
    api.__respond("getDraftingReview", { data, error: null, status: 200 });
    api.__respond("getAnalysisText", { data: DOC, error: null, status: 200 });
    return mount(review.default, { t: T, runId: "r1" });
}
const card = (c, id) => c.querySelector(`[data-question="${id}"]`);

test.beforeEach(() => { api.__reset(); });
test.after(() => dom.window.close());

// ── the server's evaluation status ──────────────────────────────────────────

test("the server's banner is shown prominently with its numbers", async () => {
    const { container, unmount } = await screen();
    const banner = container.querySelector("[data-evaluation-banner]");
    assert.equal(banner.getAttribute("role"), "alert");
    assert.equal(banner.getAttribute("data-evaluation-status"), "not_passed");
    assert.match(banner.textContent, /Evaluation not passed — internal review only\./);
    assert.match(banner.textContent, /precision 0\.861, recall 0\.941/);
    assert.match(banner.textContent, /Not production approved\. Synthetic test documents only/);
    assert.equal(container.querySelector("[data-engine-labels]").textContent,
        "Automatic drafting check — no AI · No law applied · Not lawyer reviewed");
    await unmount();
});

test("without an evaluation status from the server nothing is shown", async () => {
    for (const evaluation of [undefined, null, {}, { status: "not_passed" }]) {
        const { container, unmount } = await screen({ ...STANDARD, evaluation });
        assert.ok(container.querySelector("[data-drafting-review-error]"));
        assert.equal(container.querySelectorAll("[data-question]").length, 0);
        await unmount();
    }
});

test("a refused review says why and shows no findings", async () => {
    for (const [code, text] of [["evaluation_record_unavailable", /evaluation status could not be read/],
                                ["feature_disabled", /switched off/], ["synthetic_only", /synthetic test documents only/]]) {
        api.__reset();
        api.__respond("getDraftingReview", { data: null, error: { code, message: "x" }, status: 503 });
        api.__respond("getAnalysisText", { data: DOC, error: null, status: 200 });
        const { container, unmount } = await mount(review.default, { t: T, runId: "r1" });
        assert.match(container.querySelector("[data-drafting-review-error]").textContent, text);
        assert.equal(container.querySelectorAll("[data-question]").length, 0);
        await unmount();
    }
});

// ── labels ──────────────────────────────────────────────────────────────────

test("scanner labels are fixed, not-located is neutral and nothing says missing", async () => {
    const { container, unmount } = await screen();
    const label = id => card(container, id).querySelector("[data-status-label]");
    assert.equal(label("rent_amount").textContent, "Found");
    assert.equal(label("security_deposit").textContent, "Not located automatically");
    assert.equal(label("rent_due").textContent, "Unclear");
    assert.equal(label("term_duration").textContent, "Could not check");
    const style = label("security_deposit").getAttribute("style");
    assert.doesNotMatch(style, /red|c0392b|danger|#e[0-9a-f]{2}[0-9a-f]{3}/i);
    assert.doesNotMatch(container.textContent, /missing|absent/i);
    await unmount();
});

test("Missing appears only as the reviewer's internal outcome", async () => {
    const confirmed = { ...NOT_LOCATED, lawyer_outcome: "Reviewer marked as missing — internal review only",
        decisions: [{ id: "d1", question_id: "security_deposit", decision: "confirm", reason_code: null,
            sentence_ids: [], scanner_status: "not_located", at: "2026-10-04T10:00:00Z", evaluation_status: "not_passed" }] };
    const { container, unmount } = await screen(body([confirmed]));
    const c = card(container, "security_deposit");
    assert.equal(c.querySelector("[data-status-label]").textContent, "Not located automatically");
    assert.equal(c.querySelector("[data-lawyer-outcome]").textContent, "Reviewer marked as missing — internal review only");
    await unmount();
});

test("the AI signal is its own line and never changes the scanner label", async () => {
    const { container, unmount } = await screen();
    const c = card(container, "rent_amount");
    assert.equal(c.querySelector("[data-status-label]").textContent, "Found");
    const ai = c.querySelector("[data-ai-signal]");
    assert.equal(ai.getAttribute("data-ai-signal"), "does_not_support");
    assert.match(ai.textContent, /AI review \(separate from the automatic check\): AI review: may not support/);
    assert.equal(card(container, "security_deposit").querySelector("[data-ai-signal]").getAttribute("data-ai-signal"), "unavailable");
    await unmount();
});

// ── evidence ────────────────────────────────────────────────────────────────

test("evidence is clickable and shows the exact sentence in the document", async () => {
    const { container, unmount } = await screen();
    const link = card(container, "rent_amount").querySelector('[data-evidence-link="s1"]');
    assert.equal(link.textContent, "Rent is Rs. 85,000 per month.");
    assert.equal(container.querySelector('[data-sentence="s1"]').getAttribute("aria-current"), null);
    await click(link);
    assert.equal(container.querySelector('[data-sentence="s1"]').getAttribute("aria-current"), "true");
    assert.equal(container.querySelector('[data-sentence="s1"]').textContent, TEXT.slice(18, 47));
    await unmount();
});

test("withheld evidence is marked, never shown", async () => {
    const mismatch = { ...FOUND, evidence_withheld: "text_mismatch",
        evidence: [{ clause_id: "c1", sentences: [{ ...s1, text: null, withheld: "text_mismatch" }] }] };
    const { container, unmount } = await screen(body([mismatch, FLAGGED]));
    const m = card(container, "rent_amount");
    assert.equal(m.querySelector("[data-evidence-link]"), null);
    assert.match(m.querySelector('[data-evidence-withheld="text_mismatch"]').textContent, /no longer matches/);
    assert.match(card(container, "term_duration").querySelector('[data-evidence-withheld="flagged_as_embedded_instructions"]').textContent,
        /flagged as possible instructions/);
    await unmount();
});

// ── decisions ───────────────────────────────────────────────────────────────

test("a decision is sent with the evaluation status the screen showed", async () => {
    const { container, unmount } = await screen();
    api.__respond("recordDraftingDecision", { data: { id: "d1" }, error: null, status: 201 });
    await click(card(container, "security_deposit").querySelector('[data-decide="confirm"]'));
    const [runId, args, key] = api.__calls("recordDraftingDecision")[0].args;
    assert.equal(runId, "r1");
    assert.deepEqual(args, { questionId: "security_deposit", decision: "confirm", reasonCode: null,
        sentenceIds: [], evaluationAck: "not_passed" });
    assert.ok(key);
    assert.equal(api.__calls("getDraftingReview").length, 2);          // reloaded to show the appended decision
    await unmount();
});

test("dismissing needs a reason", async () => {
    const { container, unmount } = await screen();
    api.__respond("recordDraftingDecision", { data: { id: "d2" }, error: null, status: 201 });
    const c = card(container, "rent_due");
    assert.equal(c.querySelector('[data-decide="dismiss"]').disabled, true);
    await choose(c.querySelector("[data-dismiss-reason]"), "evidence_wrong");
    await click(card(container, "rent_due").querySelector('[data-decide="dismiss"]'));
    const [, args] = api.__calls("recordDraftingDecision")[0].args;
    assert.equal(args.decision, "dismiss");
    assert.equal(args.reasonCode, "evidence_wrong");
    await unmount();
});

test("pointing to evidence selects sentences in the document", async () => {
    const { container, unmount } = await screen();
    api.__respond("recordDraftingDecision", { data: { id: "d3" }, error: null, status: 201 });
    await click(card(container, "security_deposit").querySelector('[data-decide="point"]'));
    assert.equal(container.querySelector("[data-picking]").getAttribute("data-picking"), "security_deposit");
    assert.equal(container.querySelector("[data-save-evidence]").disabled, true);
    await click(container.querySelector('[data-sentence="s2"]'));
    assert.equal(container.querySelector('[data-sentence="s2"]').getAttribute("aria-pressed"), "true");
    await click(container.querySelector("[data-save-evidence]"));
    const [, args] = api.__calls("recordDraftingDecision")[0].args;
    assert.deepEqual([args.decision, args.sentenceIds], ["point_to_evidence", ["s2"]]);
    assert.equal(container.querySelector("[data-picking]"), null);
    await unmount();
});

test("the history is shown in order and nothing can be edited or deleted", async () => {
    const at = "2026-10-04T10:00:00Z";
    const decisions = [
        { id: "d1", decision: "confirm", reason_code: null, sentence_ids: [], at },
        { id: "d2", decision: "dismiss", reason_code: "scanner_status_wrong", sentence_ids: [], at },
        { id: "d3", decision: "point_to_evidence", reason_code: null, sentence_ids: ["s1", "s2"], at },
    ];
    const { container, unmount } = await screen(body([{ ...NOT_LOCATED, decisions }]));
    const items = [...container.querySelectorAll("[data-decision-history] [data-decision]")];
    assert.deepEqual(items.map(i => i.getAttribute("data-decision")), ["confirm", "dismiss", "point_to_evidence"]);
    assert.match(items[1].textContent, /The automatic answer is wrong/);
    assert.match(items[2].textContent, /2 sentences/);
    const labels = [...container.querySelectorAll("button")].map(b => b.textContent);
    assert.ok(!labels.some(l => /edit|delete|undo|remove/i.test(l)), labels.join(","));
    await unmount();
});

// ── placement ───────────────────────────────────────────────────────────────

test("a drafting-question run opens the review, not the AI report", async () => {
    api.__respond("getAnalysisRun", { data: { id: "r1", status: "done", engine: "ai-hypothesis.1", state_version: 9 },
        error: null, status: 200 });
    api.__respond("getDraftingReview", { data: STANDARD, error: null, status: 200 });
    api.__respond("getAnalysisText", { data: DOC, error: null, status: 200 });
    api.__respond("analyzerAttestation", { data: { version: "synthetic-v1", text: "x" }, error: null, status: 200 });
    api.__respond("listAnalyses", { data: { items: [{ id: "r1", run_id: "r1", status: "done", filename: "a.pdf",
        created_at: "2026-10-04T10:00:00Z" }], next: null } });
    assert.equal(live.STAGE_LABEL.hypothesis_scanning, "Running the drafting questions");
    assert.ok(live.shouldPoll("queued_hypothesis_review"));
    assert.equal(live.HYPOTHESIS_ENGINE, "ai-hypothesis.1");
    const src = readFileSync(new URL("../src/components/analyzer/AnalyzerLive.jsx", import.meta.url), "utf8");
    assert.match(src, /run\.engine === HYPOTHESIS_ENGINE && <DraftingReview/);
    assert.match(src, /run\.engine !== HYPOTHESIS_ENGINE && \(/);
});

function files(dir) {
    return readdirSync(dir).flatMap(n => {
        const p = join(dir, n);
        return statSync(p).isDirectory() ? files(p) : [p];
    });
}

test("nothing on the client side can reach the review", () => {
    const root = fileURLToPath(new URL("../src/", import.meta.url));
    const users = files(root).filter(p => /\.(jsx?|mjs)$/.test(p))
        .filter(p => /DraftingReview|getDraftingReview|recordDraftingDecision|drafting-review/.test(readFileSync(p, "utf8")))
        .map(p => p.replace(/\\/g, "/").split("/src/")[1]).sort();
    assert.deepEqual(users, ["components/analyzer/AnalyzerLive.jsx", "components/analyzer/DraftingReview.jsx", "lib/api.js"]);
});

test("a refused PII masking is explained, never shown as an AI result", () => {
    assert.match(live.AI_UNAVAILABLE_TEXT.pii_confirmation_required, /could not be masked with confidence, so nothing was sent/);
});

test("masked input is disclosed without claiming all personal data was removed", async () => {
    const masking = await import("../src/components/analyzer/MaskingNote.jsx");
    const PII = { masking_version: "pii-mask.1", policy_sha256: "a".repeat(64), map_blob_id: "b1", counts: { NAME: 2 } };
    const data = body([FOUND], { ai_review_summary: { status: "complete", pii: PII,
        evaluation: { masked_input: "not_yet_evaluated", note: "x" } } });
    const { container, unmount } = await screen(data);
    const note = container.querySelector("[data-pii-masking]");
    assert.equal(note.getAttribute("data-pii-masking"), "pii-mask.1");
    assert.match(note.textContent, /may not have been detected/);
    assert.equal(container.querySelector("[data-masked-not-evaluated]").textContent, masking.MASKED_NOT_EVALUATED);
    for (const text of [masking.MASKING_TEXT, masking.MASKED_NOT_EVALUATED, container.textContent]) {
        assert.doesNotMatch(text, /all personal|fully anonymi|completely remov|no personal data|personal data removed/i);
    }
    await unmount();
    const plain = await screen(body([FOUND]));                    // no masking recorded: no note
    assert.equal(plain.container.querySelector("[data-pii-masking]"), null);
    await plain.unmount();
});
