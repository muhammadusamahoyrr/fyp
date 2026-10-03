'use client';
/* Document analyzer — the REAL flow, shown only when the server offers it.
 *
 * DocsAnalyzer asks GET /documents/analyses/attestation first; only a 200
 * renders this screen. Off (404) or unsafe (503) keeps the fictional
 * demonstration, unchanged.
 *
 * What this version does, and says so: it reads and maps a document, then
 * runs GENERAL drafting checks (labelled "General document review" -- none
 * is a legal requirement). A legal checklist runs only once a qualified
 * lawyer has approved its exact text; until then the report says it exists
 * and was not run. AI drafting notes, when the server produced them, sit in
 * their own Summary / Risks / Obligations tabs, labelled as general drafting
 * attention items (no law applied, not legal advice), with their state --
 * complete, partial, failed or unavailable -- always said.
 *
 * Demo data only: the server's own warning is shown, the file picker stays
 * disabled until the user ticks the confirmation, and the confirmation is
 * sent as headers the server checks before it accepts the file.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useT } from "../theme.js";
import { Btn, Card, Label } from "./ui.jsx";
import {
    cancelAnalysisRun, confirmAnalysisDocument, confirmAnalysisOcr, confirmAnalysisTerms,
    createAnalysis, deleteAnalysis, getAnalysisReport, getAnalysisRun, getAnalysisText,
    idempotencyKey, listAnalyses,
} from "@/lib/api.js";

export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
export const ACCEPT = ".pdf,.docx,.jpg,.jpeg,.png";
const ACCEPTED_EXT = /\.(pdf|docx|jpe?g|png)$/i;
export const POLL_MS = 2000;

export const STAGE_LABEL = {
    queued_extract: "Waiting to read the document",
    extracting: "Reading the document",
    needs_ocr_confirmation: "Check the scanned text",
    queued_segmentation: "Waiting to map the document",
    segmenting: "Mapping clauses and sentences",
    needs_document_confirmation: "Confirm what this document is",
    queued_terms: "Waiting to find key terms",
    extracting_terms: "Finding key terms",
    needs_terms_confirmation: "Confirm the key terms",
    queued_analysis: "Waiting to check the document",
    analyzing: "Checking the document",
    queued_ai_report: "Waiting to prepare AI drafting notes",
    ai_reporting: "Preparing AI drafting notes",
    done: "Checked",
    failed: "Could not be read",
    cancelled: "Cancelled",
    superseded: "Replaced by a newer version",
};

/* Statuses where the server is working and the screen should keep asking. */
const WORKING = new Set(["queued_extract", "extracting", "queued_segmentation", "segmenting",
    "queued_terms", "extracting_terms", "queued_analysis", "analyzing", "queued_ai_report", "ai_reporting"]);
const OPEN = new Set([...WORKING, "needs_ocr_confirmation", "needs_document_confirmation",
    "needs_terms_confirmation"]);
export const shouldPoll = status => WORKING.has(status);

export const ERROR_TEXT = {
    too_many_pages: "The document has more than 40 pages, which this version cannot read.",
    text_too_long: "The document's text is longer than this version can read.",
    no_readable_text: "No readable text was found. Scanned pages need OCR, and Urdu is not supported yet.",
    timeout: "Reading the document took too long and was stopped.",
    encrypted: "The PDF is password-protected.",
    page_map_unavailable: "The pages of this document could not be mapped reliably.",
    text_not_confirmed: "The scanned text was not confirmed.",
    internal_error: "Something went wrong while reading the document.",
    playbook_invalid: "A checklist could not be loaded, so the document was not checked.",
    security_scan_mismatch: "The security check did not match this document's text, so it was not checked.",
};

/* How each result is worded. Never "missing": a check that found nothing
 * says the reader did not locate it, not that the document lacks it. */
export const RESULT_TEXT = {
    present: "Found",
    not_located: "Not located automatically",
    unable_to_determine: "Could not check",
    not_applicable: "Does not apply",
};
const PACK_STATUS_TEXT = {
    awaiting_approval: "Pending qualified lawyer validation. A legal checklist for this kind of document exists but has not been approved by a qualified lawyer yet, so it was not run.",
    unable_to_determine: "Whether a legal checklist applies could not be decided from what you confirmed.",
};
export const errorText = code => ERROR_TEXT[code] || "The document could not be read.";

const TERM_LABEL = {
    term_months: "Length of the tenancy (months)",
    rent_period: "Rent is paid",
    tenancy_year_to_year: "Continues from year to year",
    rent_amount: "Rent amount (PKR)",
    security_deposit: "Security deposit (PKR)",
    landlord_notice_days: "Landlord's notice (days)",
    nda_mutual: "Both parties share confidential information (mutual)",
    confidentiality_years: "Confidentiality lasts (years)",
    non_compete: "Contains a non-compete",
    non_compete_months: "Non-compete lasts (months)",
    probation_months: "Probation (months)",
    notice_days: "Notice to end employment (days)",
    salary_amount: "Salary (PKR)",
};
/* True/false terms: "Other" accepts yes / no. */
const BOOLEAN_TERMS = new Set(["tenancy_year_to_year", "nda_mutual", "non_compete"]);
const DOCUMENT_TYPE_OPTIONS = [
    ["tenancy", "Tenancy / rent agreement"],
    ["nda", "Non-disclosure agreement (NDA)"],
    ["employment", "Employment agreement / offer letter"],
    ["other", "Something else"],
];

/* A file the server would refuse anyway is refused here first, with the same reason. */
export function checkFile(file) {
    if (!file) return "Choose a file.";
    if (!ACCEPTED_EXT.test(file.name || "")) return "Only PDF, DOCX, JPG and PNG files are accepted.";
    if (file.size > MAX_UPLOAD_BYTES) return "The file is larger than 10 MB.";
    if (file.size === 0) return "The file is empty.";
    return null;
}

const msgOf = (error, fallback) => error?.message || fallback;

function Evidence({ t, items }) {
    if (!items?.length) return <div style={{ fontSize: 12.5, color: t.textMuted }}>No sentence states this.</div>;
    return (
        <ul style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 13, color: t.textMuted }}>
            {items.map(e => <li key={e.sentence_id}><q data-evidence>{e.text}</q></li>)}
        </ul>
    );
}

/* ── the canonical-text viewer ───────────────────────────────────────────── */

function TextViewer({ t, runId }) {
    const [doc, setDoc] = useState(null);
    const [issue, setIssue] = useState(null);
    useEffect(() => {
        let live = true;
        getAnalysisText(runId).then(r => {
            if (!live) return;
            if (r.error) setIssue(msgOf(r.error, "The text could not be loaded."));
            else setDoc(r.data);
        });
        return () => { live = false; };
    }, [runId]);
    if (issue) return <div role="alert" style={{ color: t.danger || "#c0392b" }}>{issue}</div>;
    if (!doc) return <div style={{ color: t.textMuted }}>Loading the text…</div>;
    return (
        <section data-text-viewer aria-label="Document text">
            <div style={{ fontSize: 12.5, color: t.textMuted, marginBottom: 8 }}>
                {doc.clauses.length} clauses · {doc.sentences.length} sentences ·
                {doc.text_version.page_map_available ? " page numbers available" : " no page numbers"}
                {doc.text_version.corrected ? " · includes your corrections" : ""}
            </div>
            <div data-lenis-prevent style={{ maxHeight: 420, overflowY: "auto", padding: 14, borderRadius: 10,
                background: t.inputBg, border: `1px solid ${t.border}`, whiteSpace: "pre-wrap", fontSize: 14, lineHeight: 1.7 }}>
                {doc.clauses.map(c => (
                    <div key={c.clause_id} data-clause={c.clause_id} style={{ marginBottom: 8 }}>
                        {doc.text.slice(c.start, c.end)}
                    </div>
                ))}
            </div>
        </section>
    );
}

/* ── the AI drafting notes ───────────────────────────────────────────────── */
/* The model's items are a separate layer from the checks: labelled as such,
 * never law, and their state is always said -- a failure must never look
 * like "no risks found". Evidence is the server's cut of the frozen text. */

export const AI_LABELS = ["General drafting attention item", "No law applied", "Not legal advice"];
export const AI_UNAVAILABLE_TEXT = {
    ai_disabled: "AI drafting notes are switched off on this server.",
    ai_not_ready: "AI drafting notes are not configured safely on this server, so they were not run.",
    not_synthetic: "AI drafting notes run only on documents confirmed as synthetic.",
    not_recorded: "This analysis was made before AI drafting notes existed.",
    no_confirmed_text: "AI drafting notes need the confirmed text, which was not available.",
    text_integrity: "The stored text did not match its fingerprint, so it was not sent to the AI.",
    security_scan_not_recorded: "This analysis was made before the security check for embedded instructions "
        + "existed, so it was not sent to the AI. Start a new analysis to have it checked.",
    security_scan_mismatch: "The security check did not match this document's text, so it was not sent to the AI.",
};
const SEVERITY_TEXT = { low: "Low", medium: "Medium", high: "High" };
const TAB_EMPTY = {
    summary_points: "The AI returned no summary points for this document.",
    model_risks: "The AI returned no drafting attention items for this document.",
    obligations: "The AI returned no obligations for this document.",
};

function AiEvidence({ t, items }) {
    return (
        <ul style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 13, color: t.textMuted }}>
            {items.map(e => (
                <li key={e.sentence_id}>
                    {e.integrity === "ok"
                        ? <q data-evidence>{e.text}</q>
                        : <span data-evidence-withheld>Evidence withheld: the document text no longer matches what was analysed.</span>}
                </li>
            ))}
        </ul>
    );
}

function AiNotice({ t, ai }) {
    if (ai.status === "failed") {
        return (
            <Card role="alert" data-ai-status="failed" style={{ padding: 12, fontSize: 13.5 }}>
                <b>AI drafting notes could not be produced</b> ({ai.error_code}). This is not the same as
                finding no issues: nothing was checked by the AI.
            </Card>
        );
    }
    if (ai.status === "unavailable") {
        return (
            <Card role="note" data-ai-status="unavailable" style={{ padding: 12, fontSize: 13.5 }}>
                {AI_UNAVAILABLE_TEXT[ai.reason] || "AI drafting notes are not available for this document."}
            </Card>
        );
    }
    return (
        <Card role="note" data-ai-status={ai.status} style={{ padding: 12, fontSize: 13 }}>
            <div data-ai-labels style={{ fontSize: 12, color: t.textMuted }}>{AI_LABELS.join(" · ")}</div>
            <div style={{ marginTop: 4 }}>{ai.notice}</div>
            {ai.status === "partial" && (
                <div data-ai-partial style={{ marginTop: 4 }}>
                    {ai.dropped?.count} AI item(s) were removed because they could not be checked against the document.
                </div>
            )}
            <div data-ai-provenance style={{ fontSize: 12, color: t.textMuted, marginTop: 4 }}>
                {ai.provider} · {ai.model} · prompt {ai.prompt_version} · schema {ai.schema_version}
            </div>
        </Card>
    );
}

/* The SERVER's embedded-instruction notice. It names clauses, sentences and
 * reason categories only -- never the flagged text, which may carry an
 * attacker's words. Shown to everyone who sees the report. */
export function SecurityNotice({ t, security }) {
    if (!security) return null;
    if (security.status === "not_recorded") {
        return (
            <Card role="note" data-security="not_recorded" style={{ padding: 12, fontSize: 13.5 }}>
                {security.message}
            </Card>
        );
    }
    const n = security.notice;
    if (!n) return null;
    return (
        <Card role="alert" data-security="embedded_instruction" aria-label="Security notice"
            style={{ padding: 12, fontSize: 14, borderColor: t.danger || "#c0392b" }}>
            <div style={{ fontWeight: 700 }}>Security notice (system check, not AI)</div>
            <p style={{ margin: "4px 0" }}>{n.message}</p>
            <div data-security-where style={{ fontSize: 13 }}>
                Where: clause {n.clause_ids.join(", ")} · sentence {n.sentence_ids.join(", ")}
            </div>
            <ul data-security-reasons style={{ margin: "4px 0 0", paddingLeft: 18, fontSize: 13 }}>
                {n.reason_text.map(r => <li key={r}>{r}</li>)}
            </ul>
        </Card>
    );
}

function AiItem({ t, kind, item }) {
    return (
        <Card data-ai-item={kind} style={{ padding: 12, marginBottom: 8 }}>
            {kind === "model_risks" && (
                <>
                    <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                        <b style={{ flex: 1 }}>{item.title}</b>
                        <span data-severity={item.severity}>{SEVERITY_TEXT[item.severity]}</span>
                    </div>
                    <div style={{ fontSize: 13 }}>{item.explanation}</div>
                    <div style={{ fontSize: 12.5, color: t.textMuted }}>Why {SEVERITY_TEXT[item.severity]?.toLowerCase()}: {item.severity_reason}</div>
                </>
            )}
            {kind === "obligations" && (
                <>
                    <div><b data-party>{item.party}</b>: {item.action}</div>
                    <div data-deadline style={{ fontSize: 12.5, color: t.textMuted }}>
                        {item.deadline_status === "stated" ? `Deadline: ${item.deadline}` : "No deadline stated in the document"}
                    </div>
                    {item.condition && <div style={{ fontSize: 12.5, color: t.textMuted }}>Condition: {item.condition}</div>}
                </>
            )}
            {kind === "summary_points" && <div style={{ fontSize: 13.5 }}>{item.point}</div>}
            <div style={{ fontSize: 12, color: t.textMuted, margin: "4px 0" }}>{AI_LABELS.join(" · ")}</div>
            <AiEvidence t={t} items={item.evidence} />
        </Card>
    );
}

const TYPE_NAME = { tenancy: "tenancy", nda: "non-disclosure", employment: "employment" };

/* How the AI layer was evaluated for this document's type -- from the
 * server's frozen record, never assumed. */
export function evaluationText(evaluation) {
    const e = evaluation || { status: "record_unavailable" };
    const kind = TYPE_NAME[e.document_type] || "this kind of";
    const status = {
        not_yet_evaluated: `Not yet evaluated: AI drafting notes for ${kind} documents have not been measured on the evaluation set.`,
        evaluated: `Evaluated on ${e.evaluated_at} with ${e.model}.`,
        not_in_evaluation_dataset: "Not evaluated: this kind of document is not in the evaluation set.",
        record_unavailable: "The evaluation record could not be read, so how well these notes work is unknown.",
    }[e.status] || "How well these notes work is unknown.";
    const labels = {
        developer_only: "Evaluation labels were written by the developer and have not been reviewed by a lawyer.",
        lawyer_reviewed: "Evaluation labels were reviewed by a qualified lawyer.",
    }[e.label_review];
    return labels ? `${status} ${labels}` : status;
}

function AiTab({ t, report, kind }) {
    const ai = report.ai || { status: "unavailable", reason: "not_recorded" };
    const items = report[kind] || [];
    const usable = ai.status === "complete" || ai.status === "partial";
    return (
        <div data-ai-tab={kind} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div role="note" data-ai-evaluation={ai.evaluation?.status || "record_unavailable"}
                style={{ fontSize: 12.5, color: t.textMuted }}>
                {evaluationText(ai.evaluation)}
            </div>
            <AiNotice t={t} ai={ai} />
            {usable && items.map(item => <AiItem key={item.fingerprint} t={t} kind={kind} item={item} />)}
            {usable && items.length === 0 && <div data-ai-empty style={{ fontSize: 13, color: t.textMuted }}>{TAB_EMPTY[kind]}</div>}
        </div>
    );
}

const REPORT_TABS = [["checks", "Checks"], ["summary_points", "Summary"], ["model_risks", "Risks"],
    ["obligations", "Obligations"]];

/* ── the report ──────────────────────────────────────────────────────────── */

function ReportView({ t, runId }) {
    const [report, setReport] = useState(null);
    const [issue, setIssue] = useState(null);
    const [tab, setTab] = useState("checks");
    useEffect(() => {
        let live = true;
        getAnalysisReport(runId).then(r => {
            if (!live) return;
            if (r.error) setIssue(msgOf(r.error, "The report could not be loaded."));
            else setReport(r.data);
        });
        return () => { live = false; };
    }, [runId]);
    if (issue) return <div role="alert">{issue}</div>;
    if (!report) return <div style={{ color: t.textMuted }}>Loading the report…</div>;
    const shown = report.legal_checks.filter(f => f.check_result !== "not_applicable");
    const groups = ["general_review", "legal_playbook"]
        .map(scope => [scope, shown.filter(f => f.scope === scope)])
        .filter(([, items]) => items.length);
    const notices = report.packs.filter(p => PACK_STATUS_TEXT[p.status]);
    return (
        <section data-report aria-label="Report" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <SecurityNotice t={t} security={report.security} />
            <div role="tablist" aria-label="Report sections" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {REPORT_TABS.map(([key, label]) => (
                    <button key={key} type="button" role="tab" data-tab={key} aria-selected={tab === key}
                        onClick={() => setTab(key)} style={{ padding: "6px 12px", borderRadius: 8, cursor: "pointer",
                            border: `1px solid ${t.border}`, background: tab === key ? t.inputBg : "transparent",
                            color: "inherit", fontWeight: tab === key ? 700 : 400 }}>
                        {label}
                    </button>
                ))}
            </div>
            {tab !== "checks" && <AiTab t={t} report={report} kind={tab} />}
            {tab === "checks" && notices.map(p => (
                <Card key={p.pack_id} role="note" data-pack-status={p.status} style={{ padding: 12, fontSize: 13.5 }}>
                    <b>{p.title}:</b> {PACK_STATUS_TEXT[p.status]}
                </Card>
            ))}
            {tab === "checks" && groups.map(([scope, items]) => (
                <div key={scope} data-scope={scope}>
                    <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 6 }}>{report.scope_notice[scope]}</div>
                    {items.map(f => (
                        <Card key={`${f.pack_id}.${f.check_id}`} data-finding={f.check_id} style={{ padding: 12, marginBottom: 8 }}>
                            <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                                <b style={{ flex: 1 }}>{f.title}</b>
                                <span data-result>{f.kind === "reminder" ? "Reminder" : RESULT_TEXT[f.check_result]}</span>
                            </div>
                            <div style={{ fontSize: 12, color: t.textMuted, margin: "4px 0" }}>{f.labels.join(" · ")}</div>
                            <div style={{ fontSize: 13 }}>{f.why}</div>
                            {f.reason && <div style={{ fontSize: 12.5, color: t.textMuted }}>{f.reason}</div>}
                            {f.authority?.length > 0 && (
                                <div data-authority style={{ fontSize: 12.5, color: t.textMuted }}>
                                    Cites: {f.authority.map(x => `${x.statute}, s.${x.section}`).join("; ")}
                                </div>
                            )}
                            {f.authority?.some(x => x.located && x.source?.url) && (
                                <div style={{ fontSize: 12, color: t.textMuted }}>
                                    {f.authority.filter(x => x.located && x.source?.url).map(x => (
                                        <div key={`${x.statute}.${x.section}`} data-source>
                                            Official text of s.{x.section}:{" "}
                                            <a href={x.source.url} target="_blank" rel="noopener noreferrer">
                                                {x.source.publisher}, p.{x.pages.join(", ")}
                                            </a>{" "}(read {x.source.retrieved})
                                        </div>
                                    ))}
                                </div>
                            )}
                            {f.evidence.length > 0 && <Evidence t={t} items={f.evidence} />}
                        </Card>
                    ))}
                </div>
            ))}
        </section>
    );
}

/* ── one run ─────────────────────────────────────────────────────────────── */

function OcrStep({ t, run, onDone }) {
    const review = run.ocr_review;
    const [text, setText] = useState(review.text);
    const [busy, setBusy] = useState(false);
    const [issue, setIssue] = useState(null);
    const submit = async corrected => {
        setBusy(true); setIssue(null);
        const r = await confirmAnalysisOcr(run.id, run.state_version, corrected ? text : null);
        setBusy(false);
        if (r.error) setIssue(msgOf(r.error, "Could not save the text."));
        else onDone();
    };
    const ocrPages = review.pages.filter(p => p.origin === "ocr").map(p => p.page);
    return (
        <Card style={{ padding: 16, display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>{review.notice}</div>
            {ocrPages.length > 0 && <div style={{ fontSize: 13, color: t.textMuted }}>Read from an image: page {ocrPages.join(", ")}.</div>}
            <label htmlFor="an-ocr" style={{ position: "absolute", left: -9999 }}>Document text</label>
            <textarea id="an-ocr" data-lenis-prevent rows={12} value={text} onChange={e => setText(e.target.value)}
                style={{ width: "100%", boxSizing: "border-box", borderRadius: 10, padding: 12, fontSize: 14,
                    border: `1px solid ${t.border}`, background: t.inputBg, color: t.text }} />
            {issue && <div role="alert" style={{ color: t.danger || "#c0392b", fontSize: 13 }}>{issue}</div>}
            <div style={{ display: "flex", gap: 8 }}>
                <Btn kind="primary" disabled={busy || text === review.text} onClick={() => submit(true)}>Save corrected text</Btn>
                <Btn disabled={busy} onClick={() => submit(false)}>The text is correct</Btn>
            </div>
        </Card>
    );
}

function DocumentStep({ t, run, onDone }) {
    const review = run.document_review;
    const proposed = review.document_type.value;
    const [docType, setDocType] = useState(DOCUMENT_TYPE_OPTIONS.some(([v]) => v === proposed) ? proposed : "other");
    const [province, setProvince] = useState(review.jurisdiction.value === "punjab" ? "punjab" : "other");
    const [busy, setBusy] = useState(false);
    const [issue, setIssue] = useState(null);
    const submit = async () => {
        setBusy(true); setIssue(null);
        const r = await confirmAnalysisDocument(run.id, run.state_version, docType, province);
        setBusy(false);
        if (r.error) setIssue(msgOf(r.error, "Could not save."));
        else onDone();
    };
    const select = { height: 38, borderRadius: 9, padding: "0 8px", border: `1px solid ${t.border}`, background: t.inputBg, color: t.text };
    return (
        <Card style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
                <Label>Document type</Label>
                <select aria-label="Document type" value={docType} onChange={e => setDocType(e.target.value)} style={select}>
                    {DOCUMENT_TYPE_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
                <Evidence t={t} items={review.document_type.evidence} />
            </div>
            <div>
                <Label>Province</Label>
                <select aria-label="Province" value={province} onChange={e => setProvince(e.target.value)} style={select}>
                    <option value="punjab">Punjab</option>
                    <option value="other">Elsewhere / not sure</option>
                </select>
                <Evidence t={t} items={review.jurisdiction.evidence} />
            </div>
            {issue && <div role="alert" style={{ color: t.danger || "#c0392b", fontSize: 13 }}>{issue}</div>}
            <Btn kind="primary" disabled={busy} onClick={submit}>Confirm</Btn>
        </Card>
    );
}

function TermsStep({ t, run, onDone }) {
    const review = run.terms_review;
    const terms = Object.keys(review.candidates);
    const decisive = review.decisive || [];        // the server says which terms must be answered
    const [answers, setAnswers] = useState(() => Object.fromEntries(terms.map(term => {
        const first = review.candidates[term][0];
        return [term, first ? { choice: "0" } : { choice: "none" }];
    })));
    const [busy, setBusy] = useState(false);
    const [issue, setIssue] = useState(null);
    const set = (term, patch) => setAnswers(a => ({ ...a, [term]: { ...a[term], ...patch } }));
    const valueOf = term => {
        const a = answers[term];
        if (a.choice === "none") return { value: null, sentence_ids: [] };
        if (a.choice === "own") {
            const raw = (a.own || "").trim();
            if (term === "rent_period") return { value: raw || null, sentence_ids: [] };
            if (BOOLEAN_TERMS.has(term)) return { value: raw === "yes" ? true : raw === "no" ? false : null, sentence_ids: [] };
            return { value: raw === "" ? null : Number(raw), sentence_ids: [] };
        }
        const c = review.candidates[term][Number(a.choice)];
        return { value: c.value, sentence_ids: c.evidence.map(e => e.sentence_id) };
    };
    const submit = async () => {
        setBusy(true); setIssue(null);
        const payload = Object.fromEntries(terms.filter(term => decisive.includes(term) || answers[term].choice !== "none")
            .map(term => [term, valueOf(term)]));
        const r = await confirmAnalysisTerms(run.id, run.state_version, payload);
        setBusy(false);
        if (r.error) setIssue(msgOf(r.error, "Could not save the terms."));
        else onDone();
    };
    return (
        <Card style={{ padding: 16, display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ fontSize: 13, color: t.textMuted }}>These decide which checks apply later. Pick what the document says, or "Not stated".</div>
            {terms.map(term => (
                <fieldset key={term} data-term={term} style={{ border: `1px solid ${t.border}`, borderRadius: 10, padding: 12 }}>
                    <legend style={{ fontSize: 13.5, fontWeight: 600 }}>{TERM_LABEL[term] || term}{decisive.includes(term) ? " *" : ""}</legend>
                    {review.candidates[term].map((c, i) => (
                        <label key={i} style={{ display: "block", fontSize: 13.5, margin: "4px 0" }}>
                            <input type="radio" name={term} checked={answers[term].choice === String(i)} onChange={() => set(term, { choice: String(i) })} />
                            {" "}{String(c.value)}
                            <Evidence t={t} items={c.evidence} />
                        </label>
                    ))}
                    <label style={{ display: "block", fontSize: 13.5 }}>
                        <input type="radio" name={term} checked={answers[term].choice === "none"} onChange={() => set(term, { choice: "none" })} /> Not stated
                    </label>
                    <label style={{ display: "block", fontSize: 13.5 }}>
                        <input type="radio" name={term} checked={answers[term].choice === "own"} onChange={() => set(term, { choice: "own" })} /> Other:{" "}
                        <input aria-label={`${TERM_LABEL[term] || term}: other value`} value={answers[term].own || ""}
                            onChange={e => set(term, { choice: "own", own: e.target.value })} style={{ width: 140 }} />
                    </label>
                </fieldset>
            ))}
            {issue && <div role="alert" style={{ color: t.danger || "#c0392b", fontSize: 13 }}>{issue}</div>}
            <Btn kind="primary" disabled={busy} onClick={submit}>Confirm the terms</Btn>
        </Card>
    );
}

function RunView({ t, runId, onBack }) {
    const [run, setRun] = useState(null);
    const [issue, setIssue] = useState(null);
    const [tick, setTick] = useState(0);
    const reload = useCallback(() => setTick(n => n + 1), []);

    useEffect(() => {
        let live = true;
        let timer = null;
        const poll = async () => {
            const r = await getAnalysisRun(runId);
            if (!live) return;
            if (r.error) { setIssue(msgOf(r.error, "This analysis could not be loaded.")); return; }
            setIssue(null);
            setRun(r.data);
            if (shouldPoll(r.data.status)) timer = setTimeout(poll, POLL_MS);
        };
        poll();
        return () => { live = false; if (timer) clearTimeout(timer); };
    }, [runId, tick]);

    const cancel = async () => {
        const r = await cancelAnalysisRun(runId);
        if (r.error) setIssue(msgOf(r.error, "Could not cancel."));
        reload();
    };

    if (issue && !run) return <div role="alert">{issue}</div>;
    if (!run) return <div style={{ color: t.textMuted }}>Loading…</div>;
    const status = run.status;
    return (
        <div data-run-view data-status={status} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <Btn onClick={onBack}>← All analyses</Btn>
                <div role="status" aria-live="polite" style={{ fontSize: 16, fontWeight: 700, flex: 1 }}>{STAGE_LABEL[status] || status}</div>
                {OPEN.has(status) && status !== "queued_analysis" && <Btn onClick={cancel}>Cancel</Btn>}
            </div>
            {issue && <div role="alert" style={{ color: t.danger || "#c0392b", fontSize: 13 }}>{issue}</div>}
            {shouldPoll(status) && <div style={{ fontSize: 13, color: t.textMuted }}>This page updates by itself.</div>}
            {status === "needs_ocr_confirmation" && <OcrStep t={t} run={run} onDone={reload} />}
            {status === "needs_document_confirmation" && <DocumentStep t={t} run={run} onDone={reload} />}
            {status === "needs_terms_confirmation" && <TermsStep t={t} run={run} onDone={reload} />}
            {status === "done" && (
                <>
                    <ReportView t={t} runId={runId} />
                    <TextViewer t={t} runId={runId} />
                </>
            )}
            {status === "failed" && <Card role="alert" style={{ padding: 14 }}>{errorText(run.error_code)}</Card>}
        </div>
    );
}

/* ── home: warning, upload, history ──────────────────────────────────────── */

export default function AnalyzerLive({ attestation, onShowDemo }) {
    const t = useT();
    const fileRef = useRef(null);
    const [attested, setAttested] = useState(false);
    const [file, setFile] = useState(null);
    const [side, setSide] = useState("tenant");
    const [issue, setIssue] = useState(null);
    const [busy, setBusy] = useState(false);
    const [history, setHistory] = useState(null);
    const [openRun, setOpenRun] = useState(null);
    const keyRef = useRef(null);          // one key per chosen file: a retry reuses it

    const loadHistory = useCallback(async () => {
        const r = await listAnalyses();
        setHistory(r.error ? [] : (r.data?.items || []));
    }, []);
    useEffect(() => { loadHistory(); }, [loadHistory]);

    const choose = e => {
        const chosen = e.target.files?.[0] || null;
        const problem = checkFile(chosen);
        setIssue(problem);
        setFile(problem ? null : chosen);
        keyRef.current = problem ? null : idempotencyKey();
    };

    const upload = async () => {
        if (!attested || !file) return;
        setBusy(true); setIssue(null);
        const r = await createAnalysis(file, { side }, attestation.version, keyRef.current);
        setBusy(false);
        if (r.error) { setIssue(msgOf(r.error, "The upload failed.")); return; }
        setFile(null); keyRef.current = null;
        if (fileRef.current) fileRef.current.value = "";
        setOpenRun(r.data.run_id);
        loadHistory();
    };

    const remove = async item => {
        if (!window.confirm("Delete this analysis and its file? This cannot be undone.")) return;
        const r = await deleteAnalysis(item.id);
        if (r.error) { setIssue(msgOf(r.error, "Could not delete.")); return; }
        loadHistory();
    };

    if (openRun) {
        return <div style={{ padding: 20 }}><RunView t={t} runId={openRun} onBack={() => { setOpenRun(null); loadHistory(); }} /></div>;
    }
    return (
        <div data-analyzer-live style={{ padding: 20, display: "flex", flexDirection: "column", gap: 16, maxWidth: 900 }}>
            <h1 style={{ margin: 0, fontSize: 26 }}>Document analyzer</h1>
            <Card role="note" data-synthetic-warning style={{ padding: 14, fontSize: 13.5, borderColor: "#e0a100" }}>
                <div style={{ fontWeight: 700, marginBottom: 6 }}>Demo version</div>
                <div>{attestation.text}</div>
                <div style={{ marginTop: 6, color: t.textMuted }}>This version runs general drafting checks. Legal checklists run only after a qualified lawyer has approved them.</div>
            </Card>
            <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13.5 }}>
                <input type="checkbox" checked={attested} onChange={e => setAttested(e.target.checked)} data-attest />
                <span>I confirm this document is synthetic (made up for testing) and contains no real client or confidential information.</span>
            </label>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
                <input ref={fileRef} type="file" accept={ACCEPT} disabled={!attested} onChange={choose}
                    aria-label="Choose a synthetic document" />
                <select aria-label="Your side" value={side} onChange={e => setSide(e.target.value)}>
                    <option value="tenant">Tenant</option>
                    <option value="landlord">Landlord</option>
                    <option value="neutral">Neutral</option>
                </select>
                <Btn kind="primary" disabled={!attested || !file || busy} onClick={upload}>{busy ? "Uploading…" : "Read this document"}</Btn>
            </div>
            <div style={{ fontSize: 12, color: t.textMuted }}>PDF, DOCX, JPG or PNG · up to 10 MB · up to 40 pages · English only</div>
            {issue && <div role="alert" style={{ color: t.danger || "#c0392b", fontSize: 13 }}>{issue}</div>}

            <section aria-label="Your analyses">
                <h2 style={{ fontSize: 17 }}>Your analyses</h2>
                {history === null ? <div style={{ color: t.textMuted }}>Loading…</div>
                    : history.length === 0 ? <div style={{ color: t.textMuted }} data-history-empty>Nothing yet. Analyses are kept for 7 days.</div>
                    : history.map(item => (
                        <div key={item.id} data-history-item style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderBottom: `1px solid ${t.border}` }}>
                            <div style={{ flex: 1 }}>
                                <div style={{ fontWeight: 600 }}>{item.file.display_name || "Document"}</div>
                                <div style={{ fontSize: 12.5, color: t.textMuted }}>{STAGE_LABEL[item.latest_run?.status] || "—"}</div>
                            </div>
                            {item.latest_run && <Btn onClick={() => setOpenRun(item.latest_run.id)}>Open</Btn>}
                            <Btn onClick={() => remove(item)} aria-label={`Delete ${item.file.display_name || "document"}`}>Delete</Btn>
                        </div>
                    ))}
            </section>
            <button type="button" onClick={onShowDemo} style={{ alignSelf: "flex-start", background: "none", border: "none", color: t.primary, cursor: "pointer", padding: 0 }}>
                View the fictional sample instead
            </button>
        </div>
    );
}
