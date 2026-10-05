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
    assert.deepEqual([...PII_REVIEW_REASONS].sort(), ["pii_confirmation_required", "pii_leak_guard", "pii_review_outdated", "pii_review_required"]);
    const live = readFileSync(new URL("../src/components/analyzer/AnalyzerLive.jsx", import.meta.url), "utf8");
    const draft = readFileSync(new URL("../src/components/analyzer/DraftingReview.jsx", import.meta.url), "utf8");
    assert.match(live, /PII_REVIEW_REASONS\.has\(report\.ai\?\.reason\) && \(\s*<PiiConfirmation/);
    assert.match(draft, /PII_REVIEW_REASONS\.has\(data\.ai_review_summary\?\.reason\) && \(\s*<PiiConfirmation/);
    assert.match(live, /<ReportView t=\{t\} runId=\{runId\} onChanged=\{reload\} \/>/);
});

test("a marked missed name can be linked to a person already masked", async () => {
    const withName = { ...VIEW, candidates: [], tokens: READY.tokens, ready: false };
    const { container, unmount } = await screen(withName);
    const original = $(container, '[data-pii-original="s1"]');
    const node = original.firstChild.firstChild;                              // "Rent is Rs. 85,000."
    const range = document.createRange();
    range.setStart(node, 0);
    range.setEnd(node, 4);                                                   // "Rent" stands in for a missed name
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    await act(async () => { $(container, "[data-pii-panes]").dispatchEvent(new dom.window.MouseEvent("mouseup", { bubbles: true })); });
    await settle();
    await click($(container, '[data-pii-mark="personal_name"]'));
    const pick = $(container, "[data-pii-added-target]");
    assert.ok(pick, "a marked name offers 'same person as'");
    const [kStart, kEnd] = at("Kashif Raza");
    await act(async () => {
        pick.value = `${kStart}-${kEnd}`;
        pick.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
    await settle();
    await click($(container, "[data-pii-preview]"));
    const [, sent] = api.__calls("previewPii")[0].args;
    const link = sent.decisions.find(d => d.decision === "same_person");
    assert.deepEqual([link.start, link.end, link.target_start, link.target_end], [S0.length + 1, S0.length + 5, kStart, kEnd]);
    await unmount();
});

test("a conflict offers no decision: only changing the mark or link can lift it", async () => {
    const [start, end] = at("Lahore");
    const conflict = { id: `${start}-${end}`, sentence_id: "s0", kind: "CONFLICT", reason: "protected_conflict", start, end };
    const { container, unmount } = await screen({ ...VIEW, candidates: [conflict] });
    const row = $(container, `[data-pii-row="${conflict.id}"]`);
    assert.ok(row.querySelector('[data-pii-conflict="protected_conflict"]'));
    assert.equal(row.querySelectorAll("[data-pii-decision]").length, 0);
    assert.match(row.textContent, /deadline, date or amount/);
    assert.equal($(container, "[data-pii-submit]").disabled, true);
    await unmount();
});

test("every masked person mention can be decided in the People panel, flagged or not", async () => {
    const TXT2 = "Landlord: Usman Farooq.\nTenant: Usman Farooq.";
    const a1 = [10, 22], a2 = [32, 44];
    const people = [{ start: a1[0], end: a1[1], token: "[NAME_1]" }, { start: a2[0], end: a2[1], token: "[NAME_1]" }];
    const view = { ...VIEW, candidates: [], people, sentences: [{ sentence_id: "s0", start: 0, end: 23, masked: "Landlord: [NAME_1]." },
                                                               { sentence_id: "s1", start: 24, end: 45, masked: "Tenant: [NAME_1]." }] };
    api.__respond("getPiiConfirmation", { data: view, error: null, status: 200 });
    api.__respond("getAnalysisText", { data: { text: TXT2, clauses: [], sentences: [], text_version: {} }, error: null, status: 200 });
    api.__respond("previewPii", (_r, { decisions }) => ({ data: { ...READY, people, decisions_made: decisions }, error: null, status: 200 }));
    const { container, unmount } = await mount({});
    const person = $(container, '[data-pii-person="[NAME_1]"]');
    assert.equal(person.querySelectorAll("[data-pii-mention]").length, 2);   // both mentions, neither flagged
    const pick = $(container, `[data-pii-identity="${a2[0]}-${a2[1]}"]`);
    await act(async () => { pick.value = "different"; pick.dispatchEvent(new dom.window.Event("change", { bubbles: true })); });
    await settle();
    await click($(container, "[data-pii-preview]"));
    const [, sent] = api.__calls("previewPii")[0].args;
    assert.deepEqual(sent.decisions, [{ start: a2[0], end: a2[1], decision: "different_person" }]);
    await unmount();
});

test("every person must be confirmed explicitly before approval, and the keys travel with it", async () => {
    const TXT2 = "Landlord: Usman Farooq.\nTenant: Hina Batool.";
    const u = [10, 22], h = [32, 43];
    const people = [{ start: u[0], end: u[1], token: "[NAME_1]" }, { start: h[0], end: h[1], token: "[NAME_2]" }];
    const groups = [{ token: "[NAME_1]", mentions: [u], key: `[NAME_1]@${u[0]}-${u[1]}` },
                    { token: "[NAME_2]", mentions: [h], key: `[NAME_2]@${h[0]}-${h[1]}` }];
    const sentences = [{ sentence_id: "s0", start: 0, end: 23, masked: "Landlord: [NAME_1]." },
                       { sentence_id: "s1", start: 24, end: 44, masked: "Tenant: [NAME_2]." }];
    const ready = { ...READY, sentences, people, people_groups: groups };
    api.__respond("getPiiConfirmation", { data: { ...VIEW, ...ready, candidates: [], decisions_made: [] }, error: null, status: 200 });
    api.__respond("getAnalysisText", { data: { text: TXT2, clauses: [], sentences: [], text_version: {} }, error: null, status: 200 });
    api.__respond("confirmPii", { data: { status: "queued_ai_report" }, error: null, status: 201 });
    const { container, unmount } = await mount({});
    await click($(container, "[data-pii-attest]"));
    assert.equal($(container, "[data-pii-submit]").disabled, true);               // attested, but no person confirmed
    assert.match($(container, "[data-pii-people-progress]").textContent, /0 of 2/);
    await click($(container, `[data-pii-person-confirm="${groups[0].key}"]`));
    assert.equal($(container, "[data-pii-submit]").disabled, true);               // one person still unconfirmed
    await click($(container, `[data-pii-person-confirm="${groups[1].key}"]`));
    assert.equal($(container, "[data-pii-submit]").disabled, false);
    await click($(container, "[data-pii-submit]"));
    const [, args] = api.__calls("confirmPii")[0].args;
    assert.deepEqual(args.peopleConfirmed, groups.map(g => g.key));
    await unmount();
});

test("a person confirmation cannot be given on a stale preview", async () => {
    const TXT2 = "Landlord: Usman Farooq.\nTenant: Usman Farooq.";
    const a1 = [10, 22], a2 = [32, 44];
    const people = [{ start: a1[0], end: a1[1], token: "[NAME_1]" }, { start: a2[0], end: a2[1], token: "[NAME_1]" }];
    const groups = [{ token: "[NAME_1]", mentions: [a1, a2], key: `[NAME_1]@${a1[0]}-${a1[1]},${a2[0]}-${a2[1]}` }];
    const sentences = [{ sentence_id: "s0", start: 0, end: 23, masked: "Landlord: [NAME_1]." },
                       { sentence_id: "s1", start: 24, end: 45, masked: "Tenant: [NAME_1]." }];
    api.__respond("getPiiConfirmation", { data: { ...VIEW, ...READY, sentences, people, people_groups: groups, candidates: [] },
                                          error: null, status: 200 });
    api.__respond("getAnalysisText", { data: { text: TXT2, clauses: [], sentences: [], text_version: {} }, error: null, status: 200 });
    const { container, unmount } = await mount({});
    assert.equal($(container, `[data-pii-person-confirm="${groups[0].key}"]`).disabled, false);
    const pick = $(container, `[data-pii-identity="${a2[0]}-${a2[1]}"]`);
    await act(async () => { pick.value = "different"; pick.dispatchEvent(new dom.window.Event("change", { bubbles: true })); });
    await settle();
    assert.equal($(container, `[data-pii-person-confirm="${groups[0].key}"]`).disabled, true);   // update the preview first
    assert.equal($(container, "[data-pii-submit]").disabled, true);
    await unmount();
});

test("a leak-check stop shows WHERE it is, and the lawyer can select and mask that exact text", async () => {
    const [s, e] = at("85,000");                               // stands in for a located hit
    const guarded = { ...READY, ready: false, leak_guard: ["long_number"],
                      guard_spans: [{ code: "long_number", start: s, end: e, sentence_id: "s1" }] };
    const { container, unmount } = await screen(VIEW, guarded);
    await decideAll(container);
    await click($(container, "[data-pii-preview]"));
    assert.match($(container, "[data-pii-guard-list]").textContent, /85,000/);
    assert.ok($(container, `[data-pii-guard-hit="${s}-${e}"]`), "the hit is highlighted in the original");
    await click($(container, `[data-pii-guard-select="${s}-${e}"]`));
    await click($(container, '[data-pii-mark="account"]'));
    await click($(container, "[data-pii-preview]"));
    const sent = api.__calls("previewPii").at(-1).args[1];
    assert.ok(sent.decisions.some(d => d.start === s && d.end === e && d.decision === "account"));
    await unmount();
});

test("a stop the check cannot place says so instead of pointing nowhere", async () => {
    const { container, unmount } = await screen(VIEW, { ...READY, ready: false, leak_guard: ["email"], guard_spans: [] });
    await decideAll(container);
    await click($(container, "[data-pii-preview]"));
    assert.ok($(container, "[data-pii-guard-unplaced]"));
    await unmount();
});

test("an overlapping-flag region shows every reason, parts can be decided, and the rest stays to decide", async () => {
    const TX = "Landlord: Bilal Malik.\nSigned by Bilal Malik House 12 Butt Road 3.";
    const s0 = { sentence_id: "s0", start: 0, end: 22, masked: "Landlord: [NAME_1]." };
    const s1 = { sentence_id: "s1", start: 23, end: TX.length, masked: "Signed by [NAME_1] [ADDRESS_1]." };
    const pos = w => [TX.indexOf(w), TX.indexOf(w) + w.length];
    const region = (w, reasons) => { const [start, end] = pos(w);
        return { id: `${start}-${end}`, sentence_id: "s1", kind: "NAME", reason: reasons[0], reasons, start, end }; };
    const whole = region("Butt Road 3", ["address_not_delimited", "signer_not_recognised"]);
    const rest = region("Road 3", ["address_not_delimited", "signer_not_recognised"]);
    const view = { ...VIEW, sentences: [s0, s1], candidates: [whole], people: [], people_groups: [] };
    api.__respond("getPiiConfirmation", { data: view, error: null, status: 200 });
    api.__respond("getAnalysisText", { data: { text: TX, clauses: [], sentences: [], text_version: {} }, error: null, status: 200 });
    // The server reports what is left: after "Butt" is decided, "Road 3" still waits.
    api.__respond("previewPii", (_r, { decisions }) => {
        const covered = w => decisions.some(d => d.start <= pos(w)[0] && pos(w)[1] <= d.end);
        const left = covered("Road 3") ? [] : [rest];
        return { data: { ...READY, sentences: [s0, s1], candidates: left, ready: left.length === 0,
                         people: [], people_groups: [], decisions_made: decisions }, error: null, status: 200 };
    });
    const { container, unmount } = await mount({});
    assert.match($(container, `[data-pii-row="${whole.id}"] [data-pii-reasons]`).textContent,
                 /part of an address.*signer's name/);                       // both reasons kept
    await click($(container, `[data-pii-row="${whole.id}"] [data-pii-decision="address"]`));
    // Select "Butt" INSIDE the highlighted region: "Not personal" is offered for a part of a region.
    const mark = $(container, `[data-pii-candidate="${whole.id}"]`);
    const node = mark.firstChild;
    const range = document.createRange();
    range.setStart(node, 0);
    range.setEnd(node, "Butt".length);
    window.getSelection().removeAllRanges();
    window.getSelection().addRange(range);
    await act(async () => { $(container, "[data-pii-panes]").dispatchEvent(new dom.window.MouseEvent("mouseup", { bubbles: true })); });
    await settle();
    await click($(container, '[data-pii-mark="not_personal"]'));
    await click($(container, "[data-pii-preview]"));
    let sent = api.__calls("previewPii").at(-1).args[1].decisions;
    assert.deepEqual(sent, [{ start: pos("Butt")[0], end: pos("Butt")[1], decision: "not_personal" }]);  // the region's own choice gave way
    assert.ok($(container, `[data-pii-row="${rest.id}"]`), "the undecided rest is shown on its own");
    assert.equal($(container, "[data-pii-submit]").disabled, true);
    await click($(container, `[data-pii-row="${rest.id}"] [data-pii-decision="address"]`));
    await click($(container, "[data-pii-preview]"));
    sent = api.__calls("previewPii").at(-1).args[1].decisions;
    assert.deepEqual(sent.map(d => [TX.slice(d.start, d.end), d.decision]), [["Butt", "not_personal"], ["Road 3", "address"]]);
    await unmount();
});

test("the screen says which masking evaluation applies to the rules running now", async () => {
    const view = { ...VIEW, evaluation: { state: "historical_pass_only", masking_version: "pii-mask.9", applicable: null,
                                          historical_passes: [{ dataset: "pii-eval-7", masking_version: "pii-mask.7" }],
                                          authorizes_real_documents: false } };
    const { container, unmount } = await screen(view);
    const note = $(container, '[data-pii-evaluation="historical_pass_only"]');
    assert.ok(note, "the evaluation state is shown");
    assert.match(note.textContent, /historical/);
    assert.match(note.textContent, /pii-mask\.9/);
    assert.doesNotMatch(note.textContent, /passed their synthetic evaluation\./);   // never shown as a current pass
    await unmount();
});
