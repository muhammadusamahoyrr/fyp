/* The lawyer's review of the exact AI request (PiiConfirmation), mounted in a
 * real DOM against the API stub. Pins: each sent sentence is shown ORIGINAL
 * beside MASKED; flagged spans are highlighted and must all be decided; a
 * missed detail can be marked by selecting it; the preview is the server's
 * exact request; nothing can be submitted until the preview is fresh, ready
 * and attested; the submission carries the previewed hash and the
 * attestation; a stale preview, a leak-check hit or a changed text blocks
 * it; nothing claims all personal data was removed. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node",
                    "Event", "KeyboardEvent", "CustomEvent", "MutationObserver", "getComputedStyle", "DOMParser"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { default: PiiConfirmation, DECISION_LABEL, PII_REVIEW_REASONS } =
    await import("../src/components/analyzer/PiiConfirmation.jsx");

const T = { text: "#111", textMuted: "#666", border: "#ccc", inputBg: "#fff", card: "#fff" };
const S0 = "TENANCY AGREEMENT made at Lahore between Kashif Raza and Hira Batool.";
const TEXT = `${S0}\nRent is Rs. 85,000.`;
const at = word => [TEXT.indexOf(word), TEXT.indexOf(word) + word.length];
const cand = word => { const [start, end] = at(word);
    return { id: `${start}-${end}`, sentence_id: "s0", kind: "NAME", reason: "party_name_not_recognised", start, end }; };
const SENTENCES = [
    { sentence_id: "s0", start: 0, end: S0.length, masked: S0 },
    { sentence_id: "s1", start: S0.length + 1, end: TEXT.length, masked: "Rent is Rs. 85,000." },
];
const VIEW = {
    run_id: "r1", stage: "ai_report", state_version: 7, reason: "pii_confirmation_required",
    text_sha256: "a".repeat(64), policy_sha256: "b".repeat(64), masking_version: "pii-mask.2",
    decisions_made: [], previous_confirmation_outdated: false,
    decisions: ["personal_name", "address", "not_personal", "same_person"],
    added_decisions: ["personal_name", "address", "same_person", "cnic", "phone", "email", "account"],
    notice: "Your review covers this exact request. It does not mean all personal information was removed, and it is not an accuracy approval.",
    attestation: "I reviewed the original text beside this exact masked request, marked every personal detail I found, and approve sending exactly this request.",
    sentences: SENTENCES, candidates: [cand("Kashif Raza"), cand("Hira Batool")], tokens: [],
    request: null, request_sha256: null, leak_guard: [], ready: false, request_error: null,
};
const READY = {
    decisions_made: [], candidates: [], leak_guard: [], ready: true, request_error: null,
    sentences: [{ ...SENTENCES[0], masked: "TENANCY AGREEMENT made at Lahore between [NAME_1] and [NAME_2]." }, SENTENCES[1]],
    tokens: [{ token: "[NAME_1]", kind: "NAME", ...Object.fromEntries([["start", at("Kashif Raza")[0]], ["end", at("Kashif Raza")[1]]]) }],
    request: [{ role: "system", content: "You review a contract." },
              { role: "user", content: "[s0|c0] TENANCY AGREEMENT made at Lahore between [NAME_1] and [NAME_2]." }],
    request_sha256: "c".repeat(64),
};

async function settle(ms = 15) { await act(async () => { await new Promise(r => setTimeout(r, ms)); }); }
async function mount(props) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(React.createElement(PiiConfirmation, { t: T, runId: "r1", ...props })); });
    await settle();
    return { container, unmount: () => act(async () => root.unmount()).then(() => container.remove()) };
}
async function click(el) {
    assert.ok(el, "nothing to click");
    await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
    await settle();
}
async function screen(view = VIEW, preview = READY) {
    api.__respond("getPiiConfirmation", { data: view, error: null, status: 200 });
    api.__respond("getAnalysisText", { data: { text: TEXT, clauses: [], sentences: [], text_version: {} }, error: null, status: 200 });
    api.__respond("previewPii", (_runId, { decisions }) => ({ data: { ...preview, decisions_made: decisions }, error: null, status: 200 }));
    let queued = 0;
    const m = await mount({ onQueued: () => { queued += 1; } });
    return { ...m, queued: () => queued };
}
const $ = (c, sel) => c.querySelector(sel);
async function decideAll(container, decision = "personal_name") {
    for (const row of container.querySelectorAll("[data-pii-row]")) await click(row.querySelector(`[data-pii-decision="${decision}"]`));
}

test.beforeEach(() => { api.__reset(); });
test.after(() => dom.window.close());

test("each sent sentence is shown original beside masked, with flagged spans highlighted", async () => {
    const { container, unmount } = await screen();
    assert.equal(container.querySelectorAll("[data-pii-pair]").length, 2);
    assert.equal($(container, '[data-pii-original="s0"]').textContent, S0);
    assert.equal($(container, '[data-pii-masked="s1"]').textContent, "Rent is Rs. 85,000.");
    const marks = [...container.querySelectorAll("[data-pii-candidate]")];
    assert.deepEqual(marks.map(m => m.textContent), ["Kashif Raza", "Hira Batool"]);
    assert.ok($(container, "[data-pii-remaining]"), "the request is not shown while something is uncertain");
    assert.equal($(container, "[data-pii-request-body]"), null);
    await unmount();
});

test("nothing is submitted until the preview is fresh, ready and attested; the hash travels with it", async () => {
    const { container, unmount, queued } = await screen();
    api.__respond("confirmPii", { data: { status: "queued_ai_report" }, error: null, status: 201 });
    assert.equal($(container, "[data-pii-submit]").disabled, true);
    await decideAll(container);
    assert.equal($(container, "[data-pii-submit]").disabled, true);              // not previewed yet
    await click($(container, "[data-pii-preview]"));
    const [, sent] = api.__calls("previewPii")[0].args;
    assert.equal(sent.decisions.length, 2);
    assert.match($(container, "[data-pii-request-body]").textContent, /\[NAME_1\]/);
    assert.match($(container, '[data-pii-masked="s0"]').textContent, /\[NAME_1\]/);
    assert.equal($(container, "[data-pii-submit]").disabled, true);              // not attested yet
    await click($(container, "[data-pii-attest]"));
    assert.equal($(container, "[data-pii-submit]").disabled, false);
    await click($(container, "[data-pii-submit]"));
    const [runId, args, key] = api.__calls("confirmPii")[0].args;
    assert.equal(runId, "r1");
    assert.equal(args.previewSha256, READY.request_sha256);
    assert.equal(args.attested, true);
    assert.equal(args.expectedStateVersion, 7);
    assert.deepEqual(args.decisions.map(d => d.decision), ["personal_name", "personal_name"]);
    assert.ok(key);
    assert.equal(queued(), 1);
    await unmount();
});

test("a change after the preview makes it stale: the attestation clears and submit is disabled", async () => {
    const { container, unmount } = await screen();
    await decideAll(container);
    await click($(container, "[data-pii-preview]"));
    await click($(container, "[data-pii-attest]"));
    const row = container.querySelector("[data-pii-row]");
    await click(row.querySelector('[data-pii-decision="address"]'));
    assert.equal($(container, "[data-pii-submit]").disabled, true);
    assert.equal($(container, "[data-pii-attest]").disabled, true);
    assert.ok($(container, "[data-pii-preview]").disabled === false);
    await unmount();
});

test("a missed detail is marked by selecting it in the original text", async () => {
    const { container, unmount } = await screen();
    const original = $(container, '[data-pii-original="s0"]');
    const node = original.firstChild.firstChild;                              // "TENANCY AGREEMENT made at Lahore between "
    const start = node.textContent.indexOf("Lahore");
    const range = document.createRange();
    range.setStart(node, start);
    range.setEnd(node, start + "Lahore".length);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    await act(async () => { $(container, "[data-pii-panes]").dispatchEvent(new dom.window.MouseEvent("mouseup", { bubbles: true })); });
    await settle();
    assert.deepEqual([...container.querySelectorAll("[data-pii-mark]")].map(b => b.dataset.piiMark),
                     ["personal_name", "address", "cnic", "phone", "email", "account"]);
    await click($(container, '[data-pii-mark="address"]'));
    assert.equal($(container, "[data-pii-added]").textContent, "Lahore");
    await decideAll(container);
    await click($(container, "[data-pii-preview]"));
    const [, sent] = api.__calls("previewPii")[0].args;
    const lahore = sent.decisions.find(d => d.decision === "address");
    assert.deepEqual([lahore.start, lahore.end], at("Lahore"));
    await unmount();
});

test("a leak-check hit is shown and the request cannot be attested", async () => {
    const { container, unmount } = await screen(VIEW, { ...READY, ready: false, leak_guard: ["email"] });
    await decideAll(container);
    await click($(container, "[data-pii-preview]"));
    assert.match($(container, "[data-pii-leak]").textContent, /email address/);
    assert.equal($(container, "[data-pii-attest]").disabled, true);
    assert.equal($(container, "[data-pii-submit]").disabled, true);
    await unmount();
});

test("a changed text or masking policy reloads the review instead of sending", async () => {
    const { container, unmount, queued } = await screen();
    api.__respond("confirmPii", { data: null, error: { code: "confirmation_outdated", message: "x" }, status: 409 });
    await decideAll(container);
    await click($(container, "[data-pii-preview]"));
    await click($(container, "[data-pii-attest]"));
    await click($(container, "[data-pii-submit]"));
    assert.equal(queued(), 0);
    assert.equal(api.__calls("getPiiConfirmation").length, 2);
    await unmount();
});

test("the server's notice is shown and nothing claims all personal data was removed", async () => {
    const { container, unmount } = await screen({ ...VIEW, previous_confirmation_outdated: true });
    assert.match($(container, "[data-pii-notice]").textContent, /not an accuracy approval/);
    assert.ok($(container, "[data-pii-outdated]"));
    assert.deepEqual(Object.values(DECISION_LABEL), ["Personal name", "Address", "Not personal information", "Same person as…"]);
    const own = container.textContent.replace(VIEW.notice, "").replace(VIEW.attestation, "");
    assert.doesNotMatch(own, /all personal data|fully anonymi|completely remov|personal data removed/i);
    await unmount();
});

test("every waiting reason opens the review in the report and the drafting review", () => {
    assert.deepEqual([...PII_REVIEW_REASONS].sort(), ["pii_confirmation_required", "pii_review_outdated", "pii_review_required"]);
    const live = readFileSync(new URL("../src/components/analyzer/AnalyzerLive.jsx", import.meta.url), "utf8");
    const draft = readFileSync(new URL("../src/components/analyzer/DraftingReview.jsx", import.meta.url), "utf8");
    assert.match(live, /PII_REVIEW_REASONS\.has\(report\.ai\?\.reason\) && \(\s*<PiiConfirmation/);
    assert.match(draft, /PII_REVIEW_REASONS\.has\(data\.ai_review_summary\?\.reason\) && \(\s*<PiiConfirmation/);
    assert.match(live, /<ReportView t=\{t\} runId=\{runId\} onChanged=\{reload\} \/>/);
});
