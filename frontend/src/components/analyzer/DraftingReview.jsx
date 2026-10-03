'use client';
/* Drafting-question review — INTERNAL, SYNTHETIC DOCUMENTS ONLY.
 *
 * The drafting-question scanner has NOT passed its engineering evaluation.
 * This screen lets a lawyer review its findings on synthetic test documents
 * and leave decisions (confirm / dismiss / point to evidence) that become
 * labels and correction events. It is not a client feature and not a report.
 *
 * Rules this screen keeps (owner's conditions, 2026-10-04):
 *  - The evaluation status and banner come from the SERVER's response. If
 *    the response has no evaluation status, nothing is shown (fail closed);
 *    a decision sends the status it showed back, and the server refuses a
 *    mismatch.
 *  - Scanner labels: Found / Not located automatically / Unclear / Could not
 *    check. "Not located automatically" is neutral -- never red, never a
 *    risk. "Missing" appears only as the reviewer's outcome, worded
 *    "Reviewer marked as missing — internal review only": the reviewer's
 *    legal qualification is not verified, and a decision approves nothing.
 *  - The AI signal is its own line with its own label; it never replaces or
 *    recolours the scanner status.
 *  - Evidence is the server's exact cut of the text; clicking it shows the
 *    sentence in the document. Withheld evidence says so.
 *  - Decisions are append-only: the history is shown, nothing is edited.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Btn, Card } from "@/components/client/documents/ui.jsx";
import { getAnalysisText, getDraftingReview, idempotencyKey, recordDraftingDecision } from "@/lib/api.js";

export const SCANNER_LABEL = {
    present: "Found",
    not_located: "Not located automatically",
    ambiguous: "Unclear",
    unable_to_determine: "Could not check",
};
export const DISMISS_REASON_TEXT = {
    scanner_status_wrong: "The automatic answer is wrong",
    evidence_wrong: "The evidence shown is wrong",
    question_not_applicable: "The question does not apply to this document",
    other: "Other",
};
export const DECISION_TEXT = { confirm: "Confirmed", dismiss: "Dismissed", point_to_evidence: "Pointed to evidence" };
export const WITHHELD_TEXT = {
    text_mismatch: "Evidence withheld: the document text no longer matches what was scanned.",
    flagged_as_embedded_instructions: "Evidence withheld: the wording was flagged as possible instructions embedded in the document.",
};
const REVIEW_ERROR_TEXT = {
    feature_disabled: "The drafting review is switched off on this server.",
    evaluation_record_unavailable: "The drafting review is unavailable: its evaluation status could not be read, so nothing is shown.",
    synthetic_only: "The drafting review is for synthetic test documents only.",
    not_drafting_review: "This analysis did not run the drafting questions.",
    not_ready: "This analysis has not finished.",
};

/* Status chip colours: Found is calm green, the other three are neutral.
 * "Not located automatically" is deliberately NOT a warning colour. */
function chipStyle(t, status) {
    const found = status === "present";
    return {
        display: "inline-block", padding: "2px 10px", borderRadius: 999, fontSize: 12.5, fontWeight: 700,
        border: `1px solid ${found ? "#1f8a5b" : t.border}`,
        color: found ? "#1f8a5b" : t.text, background: "transparent",
    };
}

function errorCode(error) {
    return error?.code || error?.detail?.code || null;
}

/* ── the document text, one span per sentence ───────────────────────────── */

function DocumentText({ t, doc, focus, picking, picked, onPick }) {
    const parts = useMemo(() => {
        if (!doc) return [];
        const out = [];
        let at = 0;
        [...doc.sentences].sort((a, b) => a.start - b.start).forEach(s => {
            if (s.start > at) out.push({ gap: doc.text.slice(at, s.start), key: `g${at}` });
            out.push({ sentence: s, text: doc.text.slice(s.start, s.end), key: s.sentence_id });
            at = Math.max(at, s.end);
        });
        if (at < doc.text.length) out.push({ gap: doc.text.slice(at), key: `g${at}` });
        return out;
    }, [doc]);
    if (!doc) return <div style={{ color: t.textMuted }}>Loading the text…</div>;
    return (
        <div data-review-text data-lenis-prevent style={{ maxHeight: 460, overflowY: "auto", padding: 14, borderRadius: 10,
            background: t.inputBg, border: `1px solid ${t.border}`, whiteSpace: "pre-wrap", fontSize: 14, lineHeight: 1.7 }}>
            {parts.map(p => p.gap !== undefined ? <span key={p.key}>{p.gap}</span> : (
                <span key={p.key} id={`review-s-${p.sentence.sentence_id}`} data-sentence={p.sentence.sentence_id}
                    aria-current={focus === p.sentence.sentence_id ? "true" : undefined}
                    role={picking ? "button" : undefined} tabIndex={picking ? 0 : undefined}
                    aria-pressed={picking ? picked.has(p.sentence.sentence_id) : undefined}
                    onClick={picking ? () => onPick(p.sentence.sentence_id) : undefined}
                    onKeyDown={picking ? e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(p.sentence.sentence_id); } } : undefined}
                    style={{
                        background: focus === p.sentence.sentence_id ? "rgba(31,138,91,.18)"
                            : picked.has(p.sentence.sentence_id) ? "rgba(31,138,91,.10)" : "transparent",
                        outline: picking ? `1px dashed ${t.border}` : "none", cursor: picking ? "pointer" : "auto",
                        borderRadius: 4,
                    }}>{p.text}</span>
            ))}
        </div>
    );
}

/* ── one question ─────────────────────────────────────────────────────────── */

function Evidence({ t, q, onFocus }) {
    if (q.evidence_withheld === "flagged_as_embedded_instructions") {
        return <div data-evidence-withheld="flagged_as_embedded_instructions" style={{ fontSize: 13, color: t.textMuted }}>
            {WITHHELD_TEXT.flagged_as_embedded_instructions}</div>;
    }
    const sentences = q.evidence.flatMap(g => g.sentences);
    if (!sentences.length) return null;
    return (
        <ul style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 13 }}>
            {sentences.map(s => (
                <li key={s.sentence_id}>
                    {s.text !== null && s.text !== undefined && !s.withheld
                        ? <button type="button" data-evidence-link={s.sentence_id} onClick={() => onFocus(s.sentence_id)}
                            style={{ background: "none", border: "none", padding: 0, cursor: "pointer", color: t.text,
                                textAlign: "left", textDecoration: "underline dotted", font: "inherit" }}>
                            <q data-evidence>{s.text}</q></button>
                        : <span data-evidence-withheld={s.withheld || "text_mismatch"} style={{ color: t.textMuted }}>
                            {WITHHELD_TEXT[s.withheld] || WITHHELD_TEXT.text_mismatch}</span>}
                </li>
            ))}
        </ul>
    );
}

function Question({ t, q, reasons, onFocus, onDecide, busy, picking, onStartPicking }) {
    const [reason, setReason] = useState("");
    return (
        <Card data-question={q.question_id} data-status={q.status} style={{ padding: 14, display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ fontWeight: 700, fontSize: 14.5 }}>{q.question}</div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <span data-status-label style={chipStyle(t, q.status)}>{SCANNER_LABEL[q.status] || q.status_label}</span>
                {q.lawyer_outcome && <span data-lawyer-outcome style={{ fontSize: 12.5, fontWeight: 700 }}>{q.lawyer_outcome}</span>}
                {q.reason_code && <span style={{ fontSize: 12, color: t.textMuted }}>({q.reason_code})</span>}
            </div>
            <Evidence t={t} q={q} onFocus={onFocus} />
            <div data-ai-signal={q.ai_review.signal || "unavailable"} style={{ fontSize: 12.5, color: t.textMuted, borderTop: `1px dashed ${t.border}`, paddingTop: 6 }}>
                <span data-ai-signal-label>{q.ai_review.label}</span>: {q.ai_review.signal_label}
                {q.ai_review.explanation && <> — {q.ai_review.explanation}</>}
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <Btn data-decide="confirm" disabled={busy} onClick={() => onDecide(q, { decision: "confirm" })}>Confirm</Btn>
                <label style={{ display: "inline-flex", gap: 6, alignItems: "center", fontSize: 13 }}>
                    <select data-dismiss-reason value={reason} onChange={e => setReason(e.target.value)} aria-label="Why dismiss">
                        <option value="">Why dismiss?</option>
                        {reasons.map(r => <option key={r} value={r}>{DISMISS_REASON_TEXT[r] || r}</option>)}
                    </select>
                </label>
                <Btn data-decide="dismiss" disabled={busy || !reason}
                    onClick={() => onDecide(q, { decision: "dismiss", reasonCode: reason })}>Dismiss</Btn>
                <Btn data-decide="point" disabled={busy || picking} onClick={() => onStartPicking(q)}>Point to evidence</Btn>
            </div>
            {q.decisions.length > 0 && (
                <ol data-decision-history style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: t.textMuted }}>
                    {q.decisions.map(d => (
                        <li key={d.id} data-decision={d.decision}>
                            {DECISION_TEXT[d.decision]}{d.reason_code ? ` — ${DISMISS_REASON_TEXT[d.reason_code] || d.reason_code}` : ""}
                            {d.sentence_ids?.length ? ` (${d.sentence_ids.length} sentence${d.sentence_ids.length > 1 ? "s" : ""})` : ""}
                            {" · "}{new Date(d.at).toLocaleString()}
                        </li>
                    ))}
                </ol>
            )}
        </Card>
    );
}

/* ── the screen ───────────────────────────────────────────────────────────── */

export default function DraftingReview({ t, runId }) {
    const [data, setData] = useState(null);
    const [issue, setIssue] = useState(null);
    const [doc, setDoc] = useState(null);
    const [focus, setFocus] = useState(null);
    const [busy, setBusy] = useState(false);
    const [notice, setNotice] = useState(null);
    const [picking, setPicking] = useState(null);           // the question being pointed for
    const [picked, setPicked] = useState(() => new Set());
    const [tick, setTick] = useState(0);

    useEffect(() => {
        let live = true;
        getDraftingReview(runId).then(r => {
            if (!live) return;
            if (r.error) {
                setData(null);
                setIssue(REVIEW_ERROR_TEXT[errorCode(r.error)] || r.error.message || "The drafting review could not be loaded.");
            } else { setIssue(null); setData(r.data); }
        });
        return () => { live = false; };
    }, [runId, tick]);
    useEffect(() => {
        let live = true;
        getAnalysisText(runId).then(r => { if (live && !r.error) setDoc(r.data); });
        return () => { live = false; };
    }, [runId]);

    const showSentence = useCallback(id => {
        setFocus(id);
        const el = typeof document !== "undefined" ? document.getElementById(`review-s-${id}`) : null;
        if (el && typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "center", behavior: "smooth" });
    }, []);

    const decide = async (q, { decision, reasonCode = null, sentenceIds = [] }) => {
        setBusy(true); setNotice(null);
        const r = await recordDraftingDecision(runId, {
            questionId: q.question_id, decision, reasonCode, sentenceIds,
            evaluationAck: data.evaluation.status,             // the status this screen showed
        }, idempotencyKey());
        setBusy(false);
        if (r.error) { setNotice(r.error.message || "The decision was not recorded."); return false; }
        setTick(n => n + 1);
        return true;
    };
    const pick = id => setPicked(prev => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id); else next.add(id);
        return next;
    });
    const savePicked = async () => {
        if (await decide(picking, { decision: "point_to_evidence", sentenceIds: [...picked] })) {
            setPicking(null); setPicked(new Set());
        }
    };

    if (issue) return <Card role="alert" data-drafting-review-error style={{ padding: 14 }}>{issue}</Card>;
    if (!data) return <div style={{ color: t.textMuted }}>Loading the drafting review…</div>;
    const ev = data.evaluation;
    if (!ev || !ev.status || !ev.banner) {
        // Fail closed: no status from the server, no findings on screen.
        return <Card role="alert" data-drafting-review-error style={{ padding: 14 }}>
            {REVIEW_ERROR_TEXT.evaluation_record_unavailable}</Card>;
    }
    return (
        <section data-drafting-review aria-label="Drafting questions — internal review" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <Card role="alert" data-evaluation-banner data-evaluation-status={ev.status}
                style={{ padding: 14, borderWidth: 2, borderColor: "#b7791f" }}>
                <div style={{ fontSize: 16, fontWeight: 800 }}>{ev.banner}</div>
                <div style={{ fontSize: 13, marginTop: 4 }}>
                    Measured on {ev.dataset?.name} ({ev.dataset?.documents} synthetic documents, developer-labelled):
                    precision {ev.attention_precision}, recall {ev.attention_recall}
                    {ev.weak_questions?.length ? `; ${ev.weak_questions.length} questions below the per-question gate` : ""}.
                    Not production approved. Synthetic test documents only — never a client document.
                </div>
            </Card>
            <div data-engine-labels style={{ fontSize: 12.5, color: "inherit" }}>{data.engine_labels.join(" · ")}</div>
            {notice && <div role="alert" style={{ fontSize: 13 }}>{notice}</div>}
            {picking && (
                <Card role="status" data-picking={picking.question_id} style={{ padding: 12, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                    <span style={{ flex: 1, fontSize: 13.5 }}>Select the sentences in the document that answer: <b>{picking.question}</b> ({picked.size} selected)</span>
                    <Btn kind="primary" data-save-evidence disabled={busy || picked.size === 0} onClick={savePicked}>Save evidence</Btn>
                    <Btn onClick={() => { setPicking(null); setPicked(new Set()); }}>Cancel</Btn>
                </Card>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 12 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {data.questions.map(q => (
                        <Question key={q.question_id} t={t} q={q} reasons={data.dismiss_reasons}
                            onFocus={showSentence} onDecide={decide} busy={busy} picking={Boolean(picking)}
                            onStartPicking={qq => { setPicking(qq); setPicked(new Set()); }} />
                    ))}
                </div>
                <DocumentText t={t} doc={doc} focus={focus} picking={Boolean(picking)} picked={picked} onPick={pick} />
            </div>
        </section>
    );
}
