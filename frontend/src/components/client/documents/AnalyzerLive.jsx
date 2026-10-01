'use client';
/* Document analyzer — the REAL flow, shown only when the server offers it.
 *
 * DocsAnalyzer asks GET /documents/analyses/attestation first; only a 200
 * renders this screen. Off (404) or unsafe (503) keeps the fictional
 * demonstration, unchanged.
 *
 * What this version does, and says so: it READS and MAPS a document --
 * extraction, scanned-text check, clauses and sentences, document type,
 * key terms. It does not review risks yet; nothing here claims it does.
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
    createAnalysis, deleteAnalysis, getAnalysisRun, getAnalysisText, idempotencyKey, listAnalyses,
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
    queued_analysis: "Read and mapped",
    done: "Done",
    failed: "Could not be read",
    cancelled: "Cancelled",
    superseded: "Replaced by a newer version",
};

/* Statuses where the server is working and the screen should keep asking. */
const WORKING = new Set(["queued_extract", "extracting", "queued_segmentation", "segmenting",
    "queued_terms", "extracting_terms"]);
const OPEN = new Set([...WORKING, "needs_ocr_confirmation", "needs_document_confirmation",
    "needs_terms_confirmation", "queued_analysis"]);
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
};
export const errorText = code => ERROR_TEXT[code] || "The document could not be read.";

const TERM_LABEL = {
    term_months: "Length of the tenancy (months)",
    rent_period: "Rent is paid",
    tenancy_year_to_year: "Continues from year to year",
    rent_amount: "Rent amount (PKR)",
    security_deposit: "Security deposit (PKR)",
    landlord_notice_days: "Landlord's notice (days)",
};
const DECISIVE = ["term_months", "rent_period", "tenancy_year_to_year"];

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
    const [docType, setDocType] = useState(review.document_type.value === "tenancy" ? "tenancy" : "other");
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
                    <option value="tenancy">Tenancy / rent agreement</option>
                    <option value="other">Something else</option>
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
            if (term === "tenancy_year_to_year") return { value: raw === "yes" ? true : raw === "no" ? false : null, sentence_ids: [] };
            return { value: raw === "" ? null : Number(raw), sentence_ids: [] };
        }
        const c = review.candidates[term][Number(a.choice)];
        return { value: c.value, sentence_ids: c.evidence.map(e => e.sentence_id) };
    };
    const submit = async () => {
        setBusy(true); setIssue(null);
        const payload = Object.fromEntries(terms.filter(term => DECISIVE.includes(term) || answers[term].choice !== "none")
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
                    <legend style={{ fontSize: 13.5, fontWeight: 600 }}>{TERM_LABEL[term] || term}{DECISIVE.includes(term) ? " *" : ""}</legend>
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
            {status === "queued_analysis" && (
                <>
                    <Card style={{ padding: 14, fontSize: 13.5 }} data-no-review-yet>
                        The document has been read and mapped. Reviewing its risks is not available yet — nothing here is a legal assessment.
                    </Card>
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
                <div style={{ marginTop: 6, color: t.textMuted }}>This version reads and maps a document. It does not review risks yet.</div>
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
