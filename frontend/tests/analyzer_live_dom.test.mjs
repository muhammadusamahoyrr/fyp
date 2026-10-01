/* The real Document Analyzer flow (AnalyzerLive), mounted in a real DOM
 * against the API stub. Live mode appears only when the server answers the
 * attestation request; otherwise the fictional demonstration stays. */
import test from "node:test";
import assert from "node:assert/strict";
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
const { ToastCtx } = await import("../src/components/shared/Toast.jsx");
const { default: DocsAnalyzer } = await import("../src/components/client/documents/DocsAnalyzer.jsx");
const live = await import("../src/components/client/documents/AnalyzerLive.jsx");

const ATTESTATION = { version: "synthetic-v1",
    text: "Demo only — do not upload real client or confidential documents. I confirm this document is synthetic (made up for testing)." };

async function settle(ms = 15) { await act(async () => { await new Promise(r => setTimeout(r, ms)); }); }
async function mount(Component = DocsAnalyzer, props = {}) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(React.createElement(ToastCtx.Provider, { value: { show: () => {} } },
            React.createElement(Component, { onBack: () => {}, ...props })));
    });
    await settle();
    return { container, unmount: () => act(async () => root.unmount()).then(() => container.remove()) };
}
const buttons = (el, text) => [...el.querySelectorAll("button")].filter(b => b.textContent.includes(text));
async function click(el) {
    assert.ok(el, "nothing to click");
    await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
    await settle();
}
async function change(el, value, prop = "value") {
    const proto = el.tagName === "SELECT" ? dom.window.HTMLSelectElement.prototype
        : el.tagName === "TEXTAREA" ? dom.window.HTMLTextAreaElement.prototype : dom.window.HTMLInputElement.prototype;
    await act(async () => {
        Object.getOwnPropertyDescriptor(proto, prop).set.call(el, value);
        el.dispatchEvent(new dom.window.Event(el.tagName === "SELECT" || prop === "checked" ? "change" : "input", { bubbles: true }));
    });
    await settle();
}
async function tick(box) {
    await act(async () => { box.click(); });
    await settle();
}
async function chooseFile(container, file) {
    const input = container.querySelector('input[type="file"]');
    await act(async () => {
        Object.defineProperty(input, "files", { value: [file], configurable: true });
        input.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
    await settle();
}
const pdf = (name = "lease.pdf", size = 2048) => new dom.window.File([new Uint8Array(size)], name, { type: "application/pdf" });

async function liveScreen() {
    api.__respond("analyzerAttestation", { data: ATTESTATION, error: null, status: 200 });
    api.__respond("listAnalyses", { data: { items: [], next: null } });
    return mount();
}

test.beforeEach(() => { api.__reset(); });
test.after(() => dom.window.close());

// ── live or demo ────────────────────────────────────────────────────────────

test("without the server's go-ahead the fictional demonstration stays", async () => {
    api.__respond("analyzerAttestation", { data: null, error: { code: "feature_disabled" }, status: 404 });
    const p = await mount();
    assert.ok(p.container.querySelector("[data-fictional-banner]"), "the demo is not shown when the analyzer is off");
    assert.equal(p.container.querySelector("[data-analyzer-live]"), null);
    assert.equal(p.container.querySelector('input[type="file"]'), null);
    await p.unmount();
});

test("live mode shows the server's warning and no fictional banner", async () => {
    const p = await liveScreen();
    assert.ok(p.container.querySelector("[data-analyzer-live]"));
    assert.match(p.container.querySelector("[data-synthetic-warning]").textContent, /do not upload real client or confidential documents/);
    assert.match(p.container.textContent, /general drafting checks\. Legal checklists run only after a qualified lawyer has approved them/);
    assert.equal(p.container.querySelector("[data-fictional-banner]"), null);
    await p.unmount();
});

test("the file picker is disabled until the synthetic confirmation is ticked", async () => {
    const p = await liveScreen();
    const input = p.container.querySelector('input[type="file"]');
    assert.equal(input.disabled, true);
    assert.equal(input.accept, ".pdf,.docx,.jpg,.jpeg,.png");
    await tick(p.container.querySelector("[data-attest]"));
    assert.equal(p.container.querySelector('input[type="file"]').disabled, false);
    await p.unmount();
});

test("files the server would refuse are refused here with the same reason", async () => {
    assert.match(live.checkFile(pdf("lease.doc")), /Only PDF, DOCX, JPG and PNG/);
    assert.match(live.checkFile(pdf("lease.pdf", live.MAX_UPLOAD_BYTES + 1)), /larger than 10 MB/);
    assert.equal(live.checkFile(pdf()), null);
    const p = await liveScreen();
    await tick(p.container.querySelector("[data-attest]"));
    await chooseFile(p.container, pdf("lease.doc"));
    assert.match(p.container.textContent, /Only PDF, DOCX, JPG and PNG files are accepted/);
    assert.equal(buttons(p.container, "Read this document")[0].disabled, true);
    await p.unmount();
});

// ── upload ──────────────────────────────────────────────────────────────────

test("an upload sends the attestation version and reuses its key on retry", async () => {
    const p = await liveScreen();
    await tick(p.container.querySelector("[data-attest]"));
    await chooseFile(p.container, pdf());
    api.__respond("createAnalysis", { data: null, error: { message: "Network error." }, status: 0 });
    await click(buttons(p.container, "Read this document")[0]);
    assert.match(p.container.textContent, /Network error/);
    api.__respond("createAnalysis", { data: { source_id: "s1", run_id: "r1", status: "queued_extract" } });
    api.__respond("getAnalysisRun", { data: { id: "r1", status: "needs_document_confirmation", state_version: 2,
        document_review: { document_type: { value: "tenancy", evidence: [] }, jurisdiction: { value: "unknown", evidence: [] } } } });
    await click(buttons(p.container, "Read this document")[0]);
    const calls = api.__calls("createAnalysis");
    assert.equal(calls.length, 2);
    assert.equal(calls[0].args[0].name, "lease.pdf");
    assert.deepEqual(calls[0].args[1], { side: "tenant" });
    assert.equal(calls[0].args[2], "synthetic-v1");
    assert.equal(calls[0].args[3], calls[1].args[3], "a retry minted a new key");
    assert.ok(p.container.querySelector("[data-run-view]"), "the run did not open after upload");
    await p.unmount();
});

// ── the run ─────────────────────────────────────────────────────────────────

async function openRun(run) {
    api.__respond("analyzerAttestation", { data: ATTESTATION });
    api.__respond("listAnalyses", { data: { items: [{ id: "s1", file: { display_name: "lease.pdf", kind: "pdf" },
        latest_run: { id: "r1", status: run.status, state_version: run.state_version } }] } });
    api.__respond("getAnalysisRun", { data: run });
    const p = await mount();
    await click(buttons(p.container, "Open")[0]);
    return p;
}

test("a working run is polled until it pauses", async () => {
    let n = 0;
    api.__respond("analyzerAttestation", { data: ATTESTATION });
    api.__respond("listAnalyses", { data: { items: [{ id: "s1", file: { display_name: "x.pdf" },
        latest_run: { id: "r1", status: "extracting", state_version: 1 } }] } });
    api.__respond("getAnalysisRun", () => {
        n += 1;
        return n === 1 ? { data: { id: "r1", status: "extracting", state_version: 1 } }
            : { data: { id: "r1", status: "failed", state_version: 2, error_code: "too_many_pages" } };
    });
    const p = await mount();
    await click(buttons(p.container, "Open")[0]);
    assert.match(p.container.textContent, /Reading the document/);
    await settle(live.POLL_MS + 200);
    assert.match(p.container.textContent, /more than 40 pages/);
    const after = api.__calls("getAnalysisRun").length;
    await settle(live.POLL_MS + 200);
    assert.equal(api.__calls("getAnalysisRun").length, after, "a finished run kept being polled");
    await p.unmount();
});

test("the document step shows the evidence and sends what the person chose", async () => {
    const p = await openRun({ id: "r1", status: "needs_document_confirmation", state_version: 4,
        document_review: {
            document_type: { value: "tenancy", evidence: [{ sentence_id: "s0", text: "TENANCY AGREEMENT made at Lahore." }] },
            jurisdiction: { value: "punjab", evidence: [{ sentence_id: "s0", text: "TENANCY AGREEMENT made at Lahore." }] } } });
    assert.equal(p.container.querySelector("[data-evidence]").textContent, "TENANCY AGREEMENT made at Lahore.");
    await change(p.container.querySelector('select[aria-label="Province"]'), "other");
    api.__respond("confirmAnalysisDocument", { data: { status: "queued_terms" } });
    await click(buttons(p.container, "Confirm")[0]);
    assert.deepEqual(api.__calls("confirmAnalysisDocument")[0].args, ["r1", 4, "tenancy", "other"]);
    await p.unmount();
});

test("the OCR step sends nothing when unchanged and the full text when corrected", async () => {
    const run = { id: "r1", status: "needs_ocr_confirmation", state_version: 3,
        ocr_review: { text: "Rent PKR 85,OOO.", notice: "Check names, amounts and dates.",
                      pages: [{ page: 1, origin: "ocr" }] } };
    let p = await openRun(run);
    assert.match(p.container.textContent, /Read from an image: page 1/);
    api.__respond("confirmAnalysisOcr", { data: { status: "queued_segmentation" } });
    await click(buttons(p.container, "The text is correct")[0]);
    assert.deepEqual(api.__calls("confirmAnalysisOcr")[0].args, ["r1", 3, null]);
    await p.unmount();

    api.__reset();
    p = await openRun(run);
    await change(p.container.querySelector("#an-ocr"), "Rent PKR 85,000.");
    api.__respond("confirmAnalysisOcr", { data: { status: "queued_segmentation" } });
    await click(buttons(p.container, "Save corrected text")[0]);
    assert.deepEqual(api.__calls("confirmAnalysisOcr")[0].args, ["r1", 3, "Rent PKR 85,000."]);
    await p.unmount();
});

test("the terms step answers every decisive term with its evidence", async () => {
    const ev = text => [{ sentence_id: "s1", text }];
    const p = await openRun({ id: "r1", status: "needs_terms_confirmation", state_version: 6,
        terms_review: { decisive: ["term_months", "rent_period", "tenancy_year_to_year"], candidates: {
            term_months: [{ value: 11, raw: "eleven (11) months", evidence: ev("... eleven (11) months.") }],
            rent_period: [{ value: "monthly", raw: "per month", evidence: ev("Rent is Rs. 85,000 per month.") }],
            tenancy_year_to_year: [],
            rent_amount: [], security_deposit: [], landlord_notice_days: [] } } });
    api.__respond("confirmAnalysisTerms", { data: { status: "queued_analysis" } });
    await click(buttons(p.container, "Confirm the terms")[0]);
    const [runId, version, terms] = api.__calls("confirmAnalysisTerms")[0].args;
    assert.equal(runId, "r1"); assert.equal(version, 6);
    assert.deepEqual(terms, {
        term_months: { value: 11, sentence_ids: ["s1"] },
        rent_period: { value: "monthly", sentence_ids: ["s1"] },
        tenancy_year_to_year: { value: null, sentence_ids: [] },
    }, "decisive terms must all be answered; unanswered supporting terms are left out");
    await p.unmount();
});

const REPORT = {
    id: "r1",
    packs: [{ pack_id: "general", title: "General document review", status: "applied" },
            { pack_id: "tenancy_punjab", title: "Punjab tenancy checklist", status: "awaiting_approval" }],
    scope_notice: { general_review: "General document review: drafting-completeness checks. None is a legal requirement.",
                    legal_playbook: "Legal playbook applied to the terms you confirmed. Applicability requires lawyer review." },
    findings: [
        { pack_id: "general", scope: "general_review", labels: ["General document review"], check_id: "parties_named",
          kind: "general_check", title: "The parties are named", why: "Most agreements say who is bound.",
          check_result: "present", evidence: [{ sentence_id: "s0", text: "Between the Landlord and the Tenant." }] },
        { pack_id: "general", scope: "general_review", labels: ["General document review"], check_id: "governing_law",
          kind: "general_check", title: "The governing law is named", why: "Many agreements name it.",
          check_result: "not_located", evidence: [] },
        { pack_id: "general", scope: "general_review", labels: ["General document review"], check_id: "skipped_one",
          kind: "general_check", title: "Hidden check", why: "x", check_result: "not_applicable", evidence: [] },
    ],
};

test("a checked document shows its report, worded honestly, and its text", async () => {
    api.__respond("getAnalysisReport", { data: REPORT });
    api.__respond("getAnalysisText", { data: { text: "1. One.\n2. Two.", clauses: [
        { clause_id: "c0", start: 0, end: 7 }, { clause_id: "c1", start: 8, end: 15 }],
        sentences: [], text_version: { page_map_available: true, corrected: false } } });
    const p = await openRun({ id: "r1", status: "done", state_version: 9 });
    const report = p.container.querySelector("[data-report]");
    assert.ok(report, "the report is not shown");
    assert.match(report.textContent, /None is a legal requirement/);
    const result = id => report.querySelector(`[data-finding="${id}"] [data-result]`).textContent;
    assert.equal(result("parties_named"), "Found");
    assert.equal(result("governing_law"), "Not located automatically");
    assert.equal(report.querySelector('[data-finding="skipped_one"]'), null, "a not-applicable check was shown");
    assert.match(report.querySelector('[data-finding="parties_named"]').textContent, /Between the Landlord and the Tenant\./);
    assert.match(report.querySelector('[data-finding="parties_named"]').textContent, /General document review/);
    assert.doesNotMatch(report.textContent, /missing/i);
    const notice = report.querySelector('[data-pack-status="awaiting_approval"]');
    assert.match(notice.textContent, /not been approved by a qualified lawyer yet, so it was not run/);
    assert.equal(report.querySelector('[data-scope="legal_playbook"]'), null, "an unapproved legal pack's results were shown");
    const clauses = [...p.container.querySelectorAll("[data-clause]")].map(c => c.textContent);
    assert.deepEqual(clauses, ["1. One.", "2. Two."]);
    await p.unmount();
});

test("an approved legal finding shows its labels and citations", async () => {
    api.__respond("getAnalysisReport", { data: { ...REPORT,
        packs: [{ pack_id: "tenancy_punjab", title: "Punjab tenancy checklist", status: "applied" }],
        findings: [{ pack_id: "tenancy_punjab", scope: "legal_playbook",
            labels: ["Legal playbook applied", "Applicability requires lawyer review"],
            check_id: "registration_term_over_one_year", kind: "reminder", title: "Registration -- term exceeding one year",
            why: "The confirmed term exceeds one year.", check_result: null, evidence: [],
            authority: [{ statute: "Registration Act 1908", section: "17(1)(d)", located: true, pages: [10],
                          source: { publisher: "Pakistan Code, Ministry of Law and Justice",
                                    url: "https://pakistancode.gov.pk/pdffiles/reg.pdf", retrieved: "2026-10-01" } },
                        { statute: "Transfer of Property Act 1882", section: "107" }] }] } });
    api.__respond("getAnalysisText", { data: { text: "x", clauses: [], sentences: [],
        text_version: { page_map_available: false, corrected: false } } });
    const p = await openRun({ id: "r1", status: "done", state_version: 9 });
    const card = p.container.querySelector('[data-finding="registration_term_over_one_year"]');
    assert.match(card.textContent, /Legal playbook applied · Applicability requires lawyer review/);
    assert.equal(card.querySelector("[data-result]").textContent, "Reminder");
    assert.equal(card.querySelector("[data-authority]").textContent,
                 "Cites: Registration Act 1908, s.17(1)(d); Transfer of Property Act 1882, s.107");
    // Only a citation located in the authority library gets a source link.
    const sources = [...card.querySelectorAll("[data-source]")];
    assert.equal(sources.length, 1);
    assert.equal(sources[0].textContent,
                 "Official text of s.17(1)(d): Pakistan Code, Ministry of Law and Justice, p.10 (read 2026-10-01)");
    const link = sources[0].querySelector("a");
    assert.equal(link.getAttribute("href"), "https://pakistancode.gov.pk/pdffiles/reg.pdf");
    assert.equal(link.getAttribute("rel"), "noopener noreferrer");
    assert.match(p.container.textContent, /Applicability requires lawyer review\./);
    await p.unmount();
});

// ── history ─────────────────────────────────────────────────────────────────

test("history deletes only after confirming", async () => {
    api.__respond("analyzerAttestation", { data: ATTESTATION });
    api.__respond("listAnalyses", { data: { items: [{ id: "s1", file: { display_name: "lease.pdf" },
        latest_run: { id: "r1", status: "queued_analysis", state_version: 8 } }] } });
    const p = await mount();
    assert.equal(p.container.querySelectorAll("[data-history-item]").length, 1);
    const realConfirm = dom.window.confirm;
    try {
        dom.window.confirm = () => false;
        await click(buttons(p.container, "Delete")[0]);
        assert.equal(api.__calls("deleteAnalysis").length, 0);
        dom.window.confirm = () => true;
        api.__respond("deleteAnalysis", { data: {} });
        api.__respond("listAnalyses", { data: { items: [] } });
        await click(buttons(p.container, "Delete")[0]);
        assert.deepEqual(api.__calls("deleteAnalysis")[0].args, ["s1"]);
        assert.ok(p.container.querySelector("[data-history-empty]"), "the list did not refresh");
    } finally {
        dom.window.confirm = realConfirm;
    }
    await p.unmount();
});

test("the fictional sample stays one click away", async () => {
    const p = await liveScreen();
    await click(buttons(p.container, "View the fictional sample instead")[0]);
    assert.ok(p.container.querySelector("[data-fictional-banner]"));
    await p.unmount();
});

// ── NDA and employment (P2B) ────────────────────────────────────────────────

test("the document step offers every supported type and preselects the proposal", async () => {
    const p = await openRun({ id: "r1", status: "needs_document_confirmation", state_version: 4,
        document_review: { document_type: { value: "nda", evidence: [] }, jurisdiction: { value: "unknown", evidence: [] } } });
    const select = p.container.querySelector('select[aria-label="Document type"]');
    assert.deepEqual([...select.options].map(o => o.value), ["tenancy", "nda", "employment", "other"]);
    assert.equal(select.value, "nda");
    await p.unmount();
});

test("an NDA's terms follow the server's decisive list and yes/no answers", async () => {
    const p = await openRun({ id: "r1", status: "needs_terms_confirmation", state_version: 6,
        terms_review: { decisive: ["nda_mutual", "confidentiality_years", "non_compete"], candidates: {
            nda_mutual: [{ value: true, raw: "mutual", evidence: [{ sentence_id: "s0", text: "MUTUAL NDA" }] }],
            confidentiality_years: [], non_compete: [], non_compete_months: [] } } });
    assert.match(p.container.textContent, /Confidentiality lasts \(years\) \*/);
    assert.doesNotMatch(p.container.textContent, /Length of the tenancy/);
    const fieldset = p.container.querySelector('[data-term="non_compete"]');
    await change(fieldset.querySelector('input[aria-label$="other value"]'), "no");
    api.__respond("confirmAnalysisTerms", { data: { status: "queued_analysis" } });
    await click(buttons(p.container, "Confirm the terms")[0]);
    const terms = api.__calls("confirmAnalysisTerms")[0].args[2];
    assert.deepEqual(terms, {
        nda_mutual: { value: true, sentence_ids: ["s0"] },
        confidentiality_years: { value: null, sentence_ids: [] },
        non_compete: { value: false, sentence_ids: [] },
    });
    await p.unmount();
});
