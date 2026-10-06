'use client';
/* Client AI drafting: prompt -> reviewed plan -> immutable V2 workspace.
 * No sample legal instrument is rendered here. Every preview, editable field
 * and check comes from the server for the user's own document. */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useT } from "../theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import { humanise } from "@/lib/fieldReview.js";
import { complianceSummary } from "@/lib/complianceSummary.js";
import { verificationView } from "@/lib/draftVerification.js";
import { documentStatusView } from "@/lib/documentStatus.js";
import { restoreStateFromDocument } from "@/lib/documentResume.js";
import { useMyDocuments } from "@/lib/useMyDocuments.js";
import { PromptCard } from "../DocumentsHome.jsx";
import {
    answerDraftPlanV2, assistDocumentWorkspaceV2, confirmDraftPlanV2,
    createDraftPlanV2, downloadDocumentFile, generateDraftPlanV2,
    getDocumentV2, getDocumentWorkspaceV2, getDraftPlanV2, idempotencyKey,
    myDocumentsV2, previewRevisionV2, saveDocumentWorkspaceV2,
} from "@/lib/api.js";
import { Btn, Card, Pill, fieldStyle, SERIF } from "./ui.jsx";

export function placeholderCounts(values = {}, applied = {}, keys = Object.keys(values)) {
    const filled = keys.filter(k => String(values[k] ?? "").trim()).length;
    const done = keys.filter(k => applied[k]).length;
    return { total: keys.length, filled, applied: done, remaining: keys.length - done };
}

const messageOf = (error, fallback) => error?.message || fallback;

/* Where an in-progress plan survives a reload.
 *
 * The plan id and the generation retry key live only in this tab's
 * sessionStorage. The key is minted HERE and never comes from the server; a
 * reload used to lose it, leaving the plan stranded in `generating`. With it
 * kept, the same key resumes the same attempt. (If storage is unavailable the
 * server's generation lease still frees the plan after a few minutes.) */
const PLAN_KEY = "attorney.draftPlan.current";
const GEN_KEY_PREFIX = "attorney.draftPlan.genKey.";
export const planStore = {
    get(name) { try { return window.sessionStorage.getItem(name); } catch { return null; } },
    set(name, value) { try { window.sessionStorage.setItem(name, value); } catch { /* storage blocked */ } },
    drop(name) { try { window.sessionStorage.removeItem(name); } catch { /* storage blocked */ } },
};

/* The only types the prompt planner accepts: the catalogue's AI-assisted
 * templates, which the server derives from the same extractor registry. */
export function promptTemplateOptions(templates) {
    return (templates || []).filter(s => s.drafting_mode === "ai");
}

const NOTE_WORDS = { joined: "combined from a list", dropped: "left out (not plain text)", truncated: "shortened" };
const whenLabel = value => {
    const date = value ? new Date(value) : null;
    if (!date || Number.isNaN(date.getTime())) return "";
    if (date.toDateString() === new Date().toDateString()) return "Today";
    return date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
};

function RichTextEditor({ html, onChange, disabled }) {
    const ref = useRef(null);
    const run = name => {
        ref.current?.focus();
        if (document.execCommand) document.execCommand(name, false, null);
    };
    return <section aria-label="Rich text document editor" style={{ width: "min(820px,100%)", background: "#fff", borderRadius: 12, overflow: "hidden", border: "1px solid #ccd5dd" }}>
        <div role="toolbar" aria-label="Text formatting" style={{ display: "flex", gap: 4, padding: 10, background: "#f7f9fb", borderBottom: "1px solid #dce3e8" }}>
            {[['bold', 'B'], ['italic', 'I'], ['underline', 'U'], ['insertUnorderedList', '• List'], ['insertOrderedList', '1. List']].map(([name, label]) =>
                <button key={name} type="button" disabled={disabled} onMouseDown={e => { e.preventDefault(); run(name); }} style={{ minHeight: 34, padding: "0 10px", border: "1px solid #d2d9df", borderRadius: 7, background: "#fff", color: "#17212f" }}>{label}</button>)}
        </div>
        <div ref={ref} contentEditable={!disabled} suppressContentEditableWarning onInput={e => onChange(e.currentTarget.innerHTML)}
            dangerouslySetInnerHTML={{ __html: html || "" }} style={{ minHeight: 560, padding: "44px 52px", outline: "none", color: "#202a2f", fontFamily: "'Source Serif 4',Georgia,serif", fontSize: 16, lineHeight: 1.8 }} />
    </section>;
}

function DraftPlan({ plan, answers, setAnswers, busy, issue, onAnswer, onConfirm, onGenerate, onBack, typeOptions, onChangeType }) {
    const t = useT();
    const questions = plan.questions || [];
    const editable = ["needs_template", "needs_details", "ready"].includes(plan.status);
    const notes = plan.extraction_notes || [];
    const canAnswer = questions.every(q => String(answers[q.field] ?? "").trim());
    return <div data-draft-plan style={{ width: "min(820px,100%)", margin: "0 auto", padding: "clamp(22px,4vw,48px)" }}>
        <button type="button" onClick={onBack} style={{ border: 0, background: "none", color: t.primary }}>← New draft</button>
        <h1 style={{ fontFamily: SERIF, color: t.text, fontSize: 34, margin: "18px 0 8px" }}>Review the draft plan</h1>
        <p style={{ color: t.textMuted, margin: "0 0 22px" }}>Check AI-extracted details before the legal document is generated.</p>
        <Card style={{ padding: 20, display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <Pill tone="info">{plan.template_type ? humanise(plan.template_type) : "Type needed"}</Pill>
                <Pill tone={plan.extraction_status === "ok" ? "low" : "medium"}>Extraction: {humanise(plan.extraction_status || "not run")}</Pill>
                <Pill tone="muted">Plan v{plan.version}</Pill>
            </div>
            <div><b style={{ color: t.text }}>{plan.title}</b><div style={{ color: t.textMuted, marginTop: 5 }}>{plan.prompt}</div></div>
            {/* A wrongly inferred type is corrected here, before anything is
                generated -- not abandoned by starting over. */}
            {editable && plan.template_type && typeOptions.length > 0 && (
                <label style={{ display: "flex", flexDirection: "column", gap: 6, color: t.text }}>
                    <span style={{ fontWeight: 650 }}>Document type</span>
                    <select data-plan-type value={plan.template_type} disabled={busy}
                        onChange={e => { if (e.target.value && e.target.value !== plan.template_type) onChangeType(e.target.value); }}
                        style={fieldStyle(t)}>
                        {!typeOptions.some(o => o.template_type === plan.template_type) && <option value={plan.template_type}>{humanise(plan.template_type)}</option>}
                        {typeOptions.map(o => <option key={o.template_type} value={o.template_type}>{o.label}</option>)}
                    </select>
                    <small style={{ color: t.textMuted }}>Changing the type re-reads your description for that document.</small>
                </label>
            )}
            {notes.length > 0 && (
                <div role="note" data-extraction-notes style={{ padding: "10px 12px", borderRadius: 9, background: t.inputBg, border: `1px solid ${t.border}`, color: t.text, fontSize: 13 }}>
                    Please check: {notes.map(n => `${humanise(n.field)} was ${NOTE_WORDS[n.action] || n.action}`).join("; ")}.
                </div>
            )}
            {Object.keys(plan.fields || {}).length > 0 && <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(210px,1fr))", gap: 10 }}>
                {Object.entries(plan.fields).map(([name, value]) => <div key={name} style={{ padding: 10, borderRadius: 9, background: t.inputBg, border: `1px solid ${t.border}` }}>
                    <div style={{ color: t.textMuted, fontSize: 11.5 }}>{humanise(name)}</div><div style={{ color: t.text, marginTop: 3 }}>{String(value || "—")}</div>
                </div>)}
            </div>}
            {questions.map(q => <label key={q.field} style={{ display: "flex", flexDirection: "column", gap: 6, color: t.text }}>
                <span style={{ fontWeight: 650 }}>{q.question}</span>
                {q.options?.length ? <select value={answers[q.field] || ""} onChange={e => setAnswers(a => ({ ...a, [q.field]: e.target.value }))} style={fieldStyle(t)}><option value="">Choose…</option>{q.options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
                    : <input value={answers[q.field] || ""} onChange={e => setAnswers(a => ({ ...a, [q.field]: e.target.value }))} style={fieldStyle(t)} />}
            </label>)}
            {issue && <div role="alert" style={{ color: t.warn }}>{issue}</div>}
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {questions.length > 0 && <Btn kind="primary" disabled={busy || !canAnswer} onClick={onAnswer}>{busy ? "Saving…" : "Save answers"}</Btn>}
                {questions.length > 0 && plan.template_type && <Btn disabled={busy} onClick={() => onConfirm(true)}>Skip missing details</Btn>}
                {questions.length === 0 && !["confirmed", "generating", "generated", "generation_failed"].includes(plan.status) && <Btn kind="primary" disabled={busy} onClick={() => onConfirm(false)}>Confirm plan</Btn>}
                {plan.status === "confirmed" && <Btn kind="primary" disabled={busy} onClick={() => onGenerate(false)}>{busy ? "Generating…" : "Generate document"}</Btn>}
                {plan.status === "generating" && <Btn kind="primary" disabled={busy} onClick={() => onGenerate(false)}>{busy ? "Checking…" : "Retry generation"}</Btn>}
                {plan.status === "generation_failed" && <Btn kind="primary" disabled={busy} onClick={() => onGenerate(true)}>{busy ? "Retrying…" : "Retry generation"}</Btn>}
            </div>
        </Card>
    </div>;
}

function Checks({ revision, t }) {
    const particulars = complianceSummary(revision?.compliance);
    const citations = verificationView(revision?.verification) || { headline: "Not checked", detail: "", tone: "neutral" };
    const color = tone => ['success', 'ok'].includes(tone) ? "#4fd18b" : tone === "warn" ? "#f2b84b" : tone === "danger" ? "#ef6b73" : t.textMuted;
    return <aside aria-label="Checks" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <h2 style={{ color: t.text, fontSize: 18, margin: 0 }}>Checks for this revision</h2>
        {[["Required particulars", particulars.label, particulars.tone, ""], ["Citation check", citations.headline, citations.tone, citations.detail]].map(([label, value, tone, detail]) => <Card key={label} style={{ padding: 14 }}>
            <div style={{ fontSize: 12, color: t.textMuted }}>{label}</div><div style={{ color: color(tone), fontWeight: 700, marginTop: 4 }}>{value}</div>{detail && <div style={{ color: t.textMuted, fontSize: 12, marginTop: 4 }}>{detail}</div>}
        </Card>)}
    </aside>;
}

export default function DocsDrafts({ seed, templates, cases, onBack, onOpenView, onOpenDocument }) {
    const t = useT();
    const toast = useToast();
    const [plan, setPlan] = useState(null), [answers, setAnswers] = useState({});
    const [workspace, setWorkspace] = useState(null), [detail, setDetail] = useState(null), [content, setContent] = useState(null);
    const [previewUrl, setPreviewUrl] = useState(null), [busy, setBusy] = useState(false), [issue, setIssue] = useState(null);
    const [instruction, setInstruction] = useState(""), [proposal, setProposal] = useState(null), [openingId, setOpeningId] = useState(null);
    const [historyCollapsed, setHistoryCollapsed] = useState(false);
    const createIntent = useRef(null), generationKey = useRef(null), saveIntent = useRef(null), seeded = useRef(false), restored = useRef(false);
    const fetchPage = useCallback(({ cursor, limit }) => myDocumentsV2({ cursor, limit }), []);
    const docs = useMyDocuments({ fetchPage, pageSize: 25 });
    const revision = detail?.current_revision || null, locked = detail?.review_status === "submitted";
    const editingPayload = workspace?.source === "freeform_html" ? { bodyHtml: content?.body_html || "", fields: null } : { bodyHtml: null, fields: content?.fields || {} };
    const titleByType = useMemo(() => Object.fromEntries((templates || []).map(x => [x.template_type, x.label])), [templates]);

    useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);

    const loadWorkspace = useCallback(async docId => {
        setBusy(true); setIssue(null); setProposal(null); setPreviewUrl(null);
        const [wsRes, docRes] = await Promise.all([getDocumentWorkspaceV2(docId), getDocumentV2(docId)]);
        if (wsRes.error || docRes.error) { setBusy(false); setIssue(messageOf(wsRes.error || docRes.error, "Could not open the document workspace.")); return false; }
        const ws = wsRes.data, doc = docRes.data, rev = doc?.current_revision;
        setWorkspace(ws); setDetail(doc); setContent(ws.source === "freeform_html" ? { body_html: ws.body_html } : { fields: { ...(ws.fields || {}) } });
        if (rev?.revision_id) {
            const shown = await previewRevisionV2(docId, rev.revision_id, { expectedPdfSha256: rev.pdf_sha256 });
            if (shown.data) setPreviewUrl(shown.data.url);
            else setIssue(messageOf(shown.error, "The PDF preview could not be loaded."));
        }
        setBusy(false); return true;
    }, []);

    const startPlan = useCallback(async input => {
        const payload = { prompt: String(input?.prompt || "").trim(), templateType: input?.templateType || null, caseId: input?.caseId || null };
        if (!payload.prompt || busy) return;
        const fingerprint = JSON.stringify(payload);
        if (createIntent.current?.fingerprint !== fingerprint) createIntent.current = { fingerprint, key: idempotencyKey() };
        setBusy(true); setIssue(null); setWorkspace(null); setDetail(null);
        const result = await createDraftPlanV2(payload, createIntent.current.key);
        setBusy(false);
        if (result.error) { setIssue(messageOf(result.error, "Could not create the draft plan.")); return; }
        createIntent.current = null; generationKey.current = null; setPlan(result.data); setAnswers({});
        planStore.set(PLAN_KEY, result.data.id);
    }, [busy]);

    // After a reload: bring back the plan this tab was working on, and the
    // generation key it was using, so a half-finished generation resumes.
    useEffect(() => {
        if (restored.current || seed?.prompt) return;
        restored.current = true;
        const planId = planStore.get(PLAN_KEY);
        if (!planId) return;
        getDraftPlanV2(planId).then(r => {
            if (r.error || !r.data) { planStore.drop(PLAN_KEY); planStore.drop(GEN_KEY_PREFIX + planId); return; }
            if (r.data.status === "generated") { planStore.drop(PLAN_KEY); planStore.drop(GEN_KEY_PREFIX + planId); return; }
            generationKey.current = planStore.get(GEN_KEY_PREFIX + planId);
            setPlan(r.data);
        });
    }, [seed]);
    useEffect(() => { if (seed?.prompt && !seeded.current) { seeded.current = true; startPlan(seed); } }, [seed, startPlan]);

    const changeType = async templateType => { setBusy(true); setIssue(null); const r = await answerDraftPlanV2(plan.id, { expectedVersion: plan.version, answers: { template_type: templateType } }); if (r.error) { const latest = await getDraftPlanV2(plan.id); if (latest.data) setPlan(latest.data); setBusy(false); return setIssue(messageOf(r.error, "Could not change the document type.")); } setBusy(false); setPlan(r.data); setAnswers({}); };
    const answerPlan = async () => { setBusy(true); setIssue(null); const r = await answerDraftPlanV2(plan.id, { expectedVersion: plan.version, answers }); if (r.error) { const latest = await getDraftPlanV2(plan.id); if (latest.data) setPlan(latest.data); setBusy(false); return setIssue(messageOf(r.error, "Could not save those answers.")); } setBusy(false); setPlan(r.data); setAnswers({}); };
    const confirmPlan = async skipMissing => { setBusy(true); setIssue(null); const r = await confirmDraftPlanV2(plan.id, { expectedVersion: plan.version, skipMissing }); if (r.error) { const latest = await getDraftPlanV2(plan.id); if (latest.data) setPlan(latest.data); setBusy(false); return setIssue(messageOf(r.error, "Could not confirm the plan.")); } setBusy(false); setPlan(r.data); };
    const generatePlan = async freshKey => {
        if (freshKey || !generationKey.current) generationKey.current = idempotencyKey();
        // Kept before the request: a reload mid-generation resumes this key.
        planStore.set(GEN_KEY_PREFIX + plan.id, generationKey.current);
        setBusy(true); setIssue(null);
        const r = await generateDraftPlanV2(plan.id, { expectedVersion: plan.version }, generationKey.current);
        if (r.error) {
            const latest = await getDraftPlanV2(plan.id); if (latest.data) setPlan(latest.data);
            setBusy(false);
            setIssue(r.error?.code === "generation_in_progress"
                ? "This document is still being generated from another attempt. Try again in a few minutes."
                : messageOf(r.error, "Document generation failed."));
            return;
        }
        planStore.drop(GEN_KEY_PREFIX + plan.id); planStore.drop(PLAN_KEY);
        generationKey.current = null; setPlan(r.data); await loadWorkspace(r.data.generation.document_id); docs.reload();
    };
    const openDoc = async row => { setOpeningId(row.id); const ok = await loadWorkspace(row.id); setOpeningId(null); if (!ok) toast.show("Could not open that document.", "danger", 3000); };
    const save = async () => {
        if (!workspace || locked) return;
        const payload = { ...editingPayload, title: workspace.title, expectedRevisionId: workspace.base_revision_id, expectedVersion: workspace.base_version, expectedContentEpoch: workspace.content_epoch };
        const fingerprint = JSON.stringify(payload); if (saveIntent.current?.fingerprint !== fingerprint) saveIntent.current = { fingerprint, key: idempotencyKey() };
        setBusy(true); setIssue(null); const r = await saveDocumentWorkspaceV2(workspace.document_id, payload, saveIntent.current.key);
        if (r.error) {
            // A failed render is final under its key; replaying it fails again.
            if (r.error?.code === "generation_failed") saveIntent.current = null;
            setBusy(false); setIssue(messageOf(r.error, "Could not save this revision.")); return;
        }
        saveIntent.current = null; await loadWorkspace(workspace.document_id); docs.reload(); toast.show("A new document revision was saved.", "success", 3000);
    };
    const askAi = async () => {
        if (!instruction.trim() || !workspace || locked) return;
        setBusy(true); setIssue(null); setProposal(null);
        const r = await assistDocumentWorkspaceV2(workspace.document_id, { ...editingPayload, instruction: instruction.trim(), expectedRevisionId: workspace.base_revision_id, expectedVersion: workspace.base_version, expectedContentEpoch: workspace.content_epoch });
        setBusy(false); if (r.error) return setIssue(messageOf(r.error, "AI Assist could not prepare a proposal.")); setProposal(r.data);
    };
    const applyProposal = () => { if (!proposal) return; setContent(workspace.source === "freeform_html" ? { body_html: proposal.body_html } : { fields: { ...(proposal.fields || {}) } }); setProposal(null); setInstruction(""); saveIntent.current = null; };
    const sendForReview = async () => { const r = await getDocumentV2(workspace.document_id); const restored = !r.error && r.data ? restoreStateFromDocument(r.data) : null; if (!restored) return setIssue("Could not prepare this document for review."); onOpenDocument?.(restored); };
    const download = async () => { const r = detail?.current_revision; const done = await downloadDocumentFile(workspace.document_id, `${workspace.title || "document"}.pdf`, { revisionId: r?.revision_id, expectedPdfSha256: r?.pdf_sha256 }); if (done?.error) setIssue(done.error); };
    const reset = () => { if (plan?.id) { planStore.drop(PLAN_KEY); planStore.drop(GEN_KEY_PREFIX + plan.id); } setPlan(null); setWorkspace(null); setDetail(null); setContent(null); setIssue(null); setProposal(null); setPreviewUrl(null); createIntent.current = null; generationKey.current = null; saveIntent.current = null; };

    if (plan && !workspace) return <DraftPlan plan={plan} answers={answers} setAnswers={setAnswers} busy={busy} issue={issue} onAnswer={answerPlan} onConfirm={confirmPlan} onGenerate={generatePlan} onBack={reset} typeOptions={promptTemplateOptions(templates)} onChangeType={changeType} />;

    if (workspace) {
        const fields = content?.fields || {};
        return <div data-document-workspace style={{ minHeight: "100%", background: t.bg, color: t.text }}>
            <header style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", padding: "14px 20px", borderBottom: `1px solid ${t.border}`, background: t.surface }}>
                <button type="button" onClick={reset} style={{ border: 0, background: "none", color: t.primary }}>← Drafts</button><strong>{workspace.title}</strong><Pill tone="info">Version {workspace.base_version}</Pill>{locked && <Pill tone="medium">Frozen for lawyer review</Pill>}<span style={{ flex: 1 }} /><Btn onClick={download}>Download PDF</Btn><Btn kind="primary" disabled={locked || busy} onClick={sendForReview}>Submit for review</Btn>
            </header>
            {issue && <div role="alert" style={{ margin: "12px 20px 0", color: t.warn }}>{issue}</div>}
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(280px,360px)", gap: 18, padding: 20, alignItems: "start" }}>
                <main style={{ minWidth: 0, display: "flex", justifyContent: "center" }}>{workspace.source === "freeform_html" ? <RichTextEditor html={content?.body_html || ""} disabled={locked} onChange={body_html => { setContent({ body_html }); saveIntent.current = null; }} /> : previewUrl ? <iframe title="Current document preview" src={previewUrl} style={{ width: "min(850px,100%)", height: "calc(100vh - 160px)", minHeight: 560, border: 0, borderRadius: 10, background: "#fff" }} /> : <Card style={{ padding: 30 }}>Loading the current PDF…</Card>}</main>
                <aside style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                    {workspace.source === "structured_fields" && <Card style={{ padding: 16, display: "flex", flexDirection: "column", gap: 10 }}><h2 style={{ margin: 0, fontSize: 18 }}>Draft details</h2><div style={{ color: t.textMuted, fontSize: 12.5 }}>Saving regenerates the same {titleByType[workspace.template_type] || humanise(workspace.template_type)} template.</div>{Object.entries(fields).map(([name, value]) => { const nested = value !== null && typeof value === "object"; return <label key={name} style={{ display: "flex", flexDirection: "column", gap: 5, fontSize: 12.5 }}><span>{humanise(name)}</span><textarea disabled={locked || nested} rows={nested || String(value || "").length > 100 ? 4 : 2} value={nested ? JSON.stringify(value, null, 2) : String(value ?? "")} onChange={e => { setContent({ fields: { ...fields, [name]: e.target.value } }); saveIntent.current = null; }} style={fieldStyle(t)} />{nested && <small style={{ color: t.textMuted }}>This calculation is read-only here. Change it in its dedicated calculator.</small>}</label>; })}</Card>}
                    <Card style={{ padding: 16, display: "flex", flexDirection: "column", gap: 9 }}><h2 style={{ margin: 0, fontSize: 18 }}>AI Assist</h2><textarea disabled={locked || busy} rows={3} value={instruction} onChange={e => setInstruction(e.target.value)} placeholder="Describe one change. It will be proposed, not saved." style={fieldStyle(t)} /><Btn disabled={locked || busy || !instruction.trim()} onClick={askAi}>{busy ? "Working…" : "Prepare proposal"}</Btn>{proposal && <div style={{ padding: 10, background: t.inputBg }}><div>{proposal.summary}</div><Btn kind="primary" onClick={applyProposal} style={{ marginTop: 9 }}>Apply proposal locally</Btn></div>}</Card>
                    <Checks revision={revision} t={t} /><Btn kind="primary" disabled={locked || busy} onClick={save}>{busy ? "Saving…" : "Save as new revision"}</Btn><div style={{ color: t.textMuted, fontSize: 11.5 }}>Nothing replaces the current revision until you save.</div>
                </aside>
            </div>
        </div>;
    }

    return <div style={{ minHeight: "100%", display: "flex", background: t.bg }}>
        {!historyCollapsed ? <aside aria-label="Draft history" style={{ flex: "0 0 240px", padding: 14, borderRight: `1px solid ${t.border}`, background: t.surface, overflowY: "auto" }}>
            <div style={{ display: "flex", marginBottom: 12 }}><strong style={{ flex: 1 }}>My documents</strong><button type="button" aria-label="Hide draft history" onClick={() => setHistoryCollapsed(true)}>‹</button></div>
            {docs.items.map(row => { const status = documentStatusView(row); return <button key={row.id} type="button" data-doc={row.id} disabled={openingId === row.id} onClick={() => openDoc(row)} style={{ width: "100%", textAlign: "left", padding: 10, marginBottom: 7, borderRadius: 9, border: `1px solid ${t.border}`, background: t.card, color: t.text }}><div style={{ fontWeight: 650 }}>{row.title || "Untitled document"}</div><div style={{ color: t.textMuted, fontSize: 12 }}>{openingId === row.id ? "Opening…" : status.label} · {whenLabel(row.updated_at || row.created_at)}</div></button>; })}
            {docs.error && <div style={{ color: t.warn }}>Could not load your documents. <button onClick={docs.reload}>Try again</button></div>}{!docs.loaded && !docs.error && <div>Loading…</div>}{docs.isEmpty && <div style={{ color: t.textMuted }}>No documents yet.</div>}{docs.hasMore && <button onClick={docs.loadMore}>Load more</button>}
        </aside> : <button type="button" aria-label="Show draft history" onClick={() => setHistoryCollapsed(false)} style={{ alignSelf: "flex-start", margin: 12 }}>›</button>}
        <main style={{ flex: 1, padding: "clamp(24px,5vw,60px)", overflowY: "auto" }}><PromptCard t={t} templates={templates} cases={cases} onPlan={startPlan} workspace />{busy && <div role="status" style={{ textAlign: "center", color: t.textMuted, marginTop: 14 }}>Creating a reviewable draft plan…</div>}{issue && <div role="alert" style={{ maxWidth: 760, margin: "14px auto", color: t.warn }}>{issue}</div>}<div style={{ textAlign: "center" }}><button onClick={onBack}>Back to Documents</button></div></main>
    </div>;
}
