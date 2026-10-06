'use client';
/* "Request lawyer review" — the client's four steps (DOCUMENT_REVIEW_REQUEST_PLAN.md §10).
 *
 *   1. Pick a version      (generated versions only; the current one first)
 *   2. Pick an engagement  (only the accepted engagements this document may go to)
 *   3. Note and focus      (both optional, counted to their limits)
 *   4. Review and submit   (exactly what will be shared, and the D4 notice)
 *
 * Opened with `draft`, it continues an existing draft at step 3: the version
 * and the lawyer are shown, not re-chosen.
 *
 * RETRIES ARE SAFE. Every call carries an Idempotency-Key that is reused for
 * the same body (a network failure retried, a double click) and replaced only
 * when the body changes -- so a retry never creates a second request, and an
 * edit is never mistaken for a retry. The Submit button is disabled while a
 * call is in flight.
 *
 * No fee, price, urgency or reply-time element: by decision (§10). */
import React, { useEffect, useRef, useState } from "react";
import { useT } from "../theme.js";
import {
    cancelReviewRequest, createReviewRequest, editReviewRequest, idempotencyKey,
    listRevisionsV2, reviewRequestEligibleEngagements, submitReviewRequest,
} from "@/lib/api.js";
import {
    CANCEL_LIMIT_NOTICE, DRAFT_LOCKED_NOTICE, FOCUS_ITEM_MAX, FOCUS_MAX_ITEMS, NOTE_MAX, NO_ENGAGEMENT_NOTICE,
    counterText, isSafeRetry, normaliseFocus, requestErrorMessage, shareableVersions,
} from "@/lib/reviewRequests.js";
import { formatWhen } from "./DocsVault.jsx";
import { BACKDROP, Btn, Card, Label, ModalPortal, Pill, fieldStyle } from "./ui.jsx";

const STEPS = ["Version", "Lawyer", "Note", "Review"];

/* The same key for the same body; a new one when the body changes. */
export function useKeyFor() {
    const memo = useRef(new Map());
    return body => {
        const fp = JSON.stringify(body);
        if (!memo.current.has(fp)) memo.current.set(fp, idempotencyKey());
        return memo.current.get(fp);
    };
}

export default function ReviewRequestDialog({ row, draft = null, onClose, onDone, onOpenExisting }) {
    const t = useT();
    const keyFor = useKeyFor();
    const editing = Boolean(draft);
    const [step, setStep] = useState(editing ? 2 : 0);
    const [versions, setVersions] = useState(null);
    const [engagements, setEngagements] = useState(null);
    const [loadError, setLoadError] = useState(null);
    const [revisionId, setRevisionId] = useState(draft?.revision_id || row?.revision_id || null);
    const [engagementId, setEngagementId] = useState(draft?.engagement_id || null);
    const [note, setNote] = useState(draft?.note || "");
    const [focus, setFocus] = useState(draft?.focus?.length ? [...draft.focus] : [""]);
    const [busy, setBusy] = useState(false);
    // The REAL in-flight guard. `busy` is state: two clicks delivered before
    // React re-renders both read it as false, and both would send. A ref is
    // read and set synchronously, so the second click sees the first.
    const inFlight = useRef(false);
    const [problem, setProblem] = useState(null);        // { message, existingId, retry }
    const created = useRef(draft);                        // the draft once it exists
    // Once a draft exists its version and lawyer are fixed: going back to
    // steps 1-2 would only build a body the existing draft cannot take.
    const [hasDraft, setHasDraft] = useState(Boolean(draft));

    useEffect(() => {
        if (editing) return undefined;
        let alive = true;
        (async () => {
            const [revs, engs] = await Promise.all([
                listRevisionsV2(row.id),
                reviewRequestEligibleEngagements(row.id),
            ]);
            if (!alive) return;
            if (revs?.error || engs?.error) {
                setLoadError(requestErrorMessage(null, "Could not load this document's versions and lawyers."));
                return;
            }
            const list = shareableVersions(revs?.data?.items, row.revision_id);
            setVersions(list);
            setEngagements(engs?.data?.items || []);
            if (!list.some(v => v.revision_id === revisionId)) setRevisionId(list[0]?.revision_id || null);
            const firstFree = (engs?.data?.items || []).find(e => !e.open_request_id);
            if (firstFree && !engagementId) setEngagementId(firstFree.engagement_id);
        })();
        return () => { alive = false; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [row?.id, editing]);

    useEffect(() => {
        const esc = e => { if (e.key === "Escape" && !busy) onClose?.(); };
        document.addEventListener("keydown", esc);
        return () => document.removeEventListener("keydown", esc);
    }, [busy, onClose]);

    const version = editing
        ? { revision_id: draft.revision_id, version: draft.version, pdf_sha256: draft.pdf_sha256 }
        : (versions || []).find(v => v.revision_id === revisionId) || null;
    const engagement = editing
        ? { engagement_id: draft.engagement_id, lawyer_name: draft.lawyer_name, case_title: draft.case_title }
        : (engagements || []).find(e => e.engagement_id === engagementId) || null;
    const focusState = normaliseFocus(focus);
    const noteTooLong = note.length > NOTE_MAX;

    const canNext = [
        Boolean(version),
        Boolean(engagement) && !engagement?.open_request_id,
        !noteTooLong && !focusState.problem,
        true,
    ][step];

    const fail = (res, retry) => {
        const code = res?.error?.code || null;
        setProblem({
            message: isSafeRetry(res?.status)
                ? "Network problem — nothing was sent twice. Try again."
                : requestErrorMessage(code, res?.error?.message),
            existingId: code === "open_request_exists" ? res?.error?.error?.existing_request_id || null : null,
            retry: isSafeRetry(res?.status) ? retry : null,
        });
    };

    const send = async () => {
        if (inFlight.current) return;
        inFlight.current = true;
        setBusy(true);
        setProblem(null);
        const noteValue = note.trim() || null;
        let current = created.current;
        try {
            if (!current) {
                const body = { documentId: row.id, revisionId: version.revision_id,
                               expectedPdfSha256: version.pdf_sha256, engagementId: engagement.engagement_id,
                               note: noteValue, focus: focusState.items };
                const res = await createReviewRequest(body, keyFor({ op: "create", ...body }));
                if (res?.error) { fail(res, send); return; }
                current = created.current = res.data;
                setHasDraft(true);
            } else if (((current.note || null) !== noteValue
                                   || JSON.stringify(current.focus || []) !== JSON.stringify(focusState.items))) {
                const body = { expectedStateVersion: current.state_version, note: noteValue, focus: focusState.items };
                const res = await editReviewRequest(current.id, body, keyFor({ op: "edit", id: current.id, ...body }));
                if (res?.error) { fail(res, send); return; }
                current = created.current = res.data;
            }
            const body = { expectedStateVersion: current.state_version, expectedPdfSha256: current.pdf_sha256 };
            const res = await submitReviewRequest(current.id, body, keyFor({ op: "submit", id: current.id, ...body }));
            if (res?.error) { fail(res, send); return; }
            onDone?.(res.data);
        } finally {
            inFlight.current = false;
            setBusy(false);
        }
    };

    const saveDraft = async () => {
        if (inFlight.current || !editing) return;
        inFlight.current = true;
        setBusy(true);
        setProblem(null);
        const current = created.current;
        const body = { expectedStateVersion: current.state_version, note: note.trim() || null, focus: focusState.items };
        const res = await editReviewRequest(current.id, body, keyFor({ op: "edit", id: current.id, ...body }));
        inFlight.current = false;
        setBusy(false);
        if (res?.error) { fail(res, saveDraft); return; }
        created.current = res.data;
        onDone?.(res.data);
    };

    const box = { width: "min(620px, calc(100vw - 32px))", maxHeight: "calc(100vh - 48px)", overflowY: "auto",
                  margin: "24px auto", padding: 24, boxSizing: "border-box" };

    return (
        <ModalPortal>
            <div style={{ ...BACKDROP, overflowY: "auto" }} onMouseDown={e => { if (e.target === e.currentTarget && !busy) onClose?.(); }}>
                <Card role="dialog" aria-modal="true" aria-labelledby="rr-title" data-review-request-dialog style={box}>
                    <h2 id="rr-title" style={{ margin: 0, fontSize: 20, color: t.text }}>Request lawyer review</h2>
                    <p style={{ margin: "6px 0 16px", fontSize: 13.5, color: t.textMuted }}>
                        {row?.title || "Untitled document"}
                    </p>
                    <ol aria-label="Steps" style={{ display: "flex", gap: 8, padding: 0, margin: "0 0 18px", listStyle: "none", flexWrap: "wrap" }}>
                        {STEPS.map((name, i) => (
                            <li key={name} aria-current={i === step ? "step" : undefined}>
                                <Pill tone={i === step ? "info" : "muted"}>{i + 1}. {name}</Pill>
                            </li>
                        ))}
                    </ol>

                    {loadError && <div role="alert" style={{ color: t.danger, fontSize: 14, marginBottom: 12 }}>{loadError}</div>}

                    {step === 0 && (
                        <section aria-label="Pick a version">
                            <Label>Which version</Label>
                            {versions === null && !loadError && <p aria-busy="true" style={{ color: t.textMuted }}>Loading versions…</p>}
                            {versions && versions.length === 0 && (
                                <p style={{ color: t.textMuted }}>This document has no finished version to share yet.</p>
                            )}
                            {(versions || []).map(v => (
                                <label key={v.revision_id} style={{ display: "flex", gap: 10, alignItems: "center", padding: "8px 0", color: t.text, fontSize: 14 }}>
                                    <input type="radio" name="rr-version" checked={revisionId === v.revision_id}
                                        onChange={() => setRevisionId(v.revision_id)} />
                                    Version {v.version}
                                    {v.revision_id === row?.revision_id ? <Pill tone="low">Current</Pill> : null}
                                    <span style={{ color: t.textMuted }}>{formatWhen(v.created_at)}</span>
                                </label>
                            ))}
                        </section>
                    )}

                    {step === 1 && (
                        <section aria-label="Pick a lawyer">
                            <Label>Send to</Label>
                            {engagements === null && !loadError && <p aria-busy="true" style={{ color: t.textMuted }}>Loading your lawyers…</p>}
                            {engagements && engagements.length === 0 && (
                                <div data-rr-empty style={{ padding: "10px 0", color: t.text, fontSize: 14, lineHeight: 1.6 }}>
                                    {NO_ENGAGEMENT_NOTICE} <a href="/lawyers" style={{ color: t.primary }}>Find a lawyer</a>
                                </div>
                            )}
                            {(engagements || []).map(e => (
                                <label key={e.engagement_id} style={{ display: "flex", gap: 10, alignItems: "center", padding: "8px 0", color: t.text, fontSize: 14 }}>
                                    <input type="radio" name="rr-engagement" checked={engagementId === e.engagement_id}
                                        disabled={Boolean(e.open_request_id)} onChange={() => setEngagementId(e.engagement_id)} />
                                    <span style={{ fontWeight: 600 }}>{e.lawyer_name || "Your lawyer"}</span>
                                    {e.case_title ? <span style={{ color: t.textMuted }}>· {e.case_title}</span> : null}
                                    {e.open_request_id ? (
                                        <Btn kind="quiet" onClick={() => onOpenExisting?.(e.open_request_id)} style={{ minHeight: 30 }}>
                                            Already requested — open it
                                        </Btn>
                                    ) : null}
                                </label>
                            ))}
                        </section>
                    )}

                    {step === 2 && (
                        <section aria-label="Note and focus">
                            {editing && (
                                <>
                                    <p style={{ margin: "0 0 6px", fontSize: 13.5, color: t.textMuted }}>
                                        Version {draft.version} · to {draft.lawyer_name || "your lawyer"}
                                    </p>
                                    <p data-rr-draft-locked style={{ margin: "0 0 12px", fontSize: 13, color: t.textMuted, lineHeight: 1.5 }}>
                                        {DRAFT_LOCKED_NOTICE}
                                    </p>
                                </>
                            )}
                            <Label>Note for your lawyer (optional)</Label>
                            <textarea id="rr-note" aria-label="Note for your lawyer" value={note} onChange={e => setNote(e.target.value)}
                                rows={5} style={fieldStyle(t, { marginTop: 8, resize: "vertical" })} />
                            <div data-rr-counter style={{ textAlign: "right", fontSize: 12, color: noteTooLong ? t.danger : t.textMuted }}>
                                {counterText(note.length, NOTE_MAX)}
                            </div>
                            <Label style={{ marginTop: 14 }}>What should they look at? (optional)</Label>
                            {focus.map((f, i) => (
                                <div key={i} style={{ display: "flex", gap: 8, marginTop: 8 }}>
                                    <input aria-label={`Focus point ${i + 1}`} value={f} maxLength={FOCUS_ITEM_MAX + 20}
                                        onChange={e => setFocus(list => list.map((x, j) => (j === i ? e.target.value : x)))}
                                        placeholder="e.g. the rent clause" style={fieldStyle(t)} />
                                    <span style={{ fontSize: 12, color: f.trim().length > FOCUS_ITEM_MAX ? t.danger : t.textMuted, alignSelf: "center", whiteSpace: "nowrap" }}>
                                        {counterText(f.trim().length, FOCUS_ITEM_MAX)}
                                    </span>
                                </div>
                            ))}
                            {focus.length < FOCUS_MAX_ITEMS && (
                                <Btn kind="quiet" onClick={() => setFocus(list => [...list, ""])} style={{ marginTop: 6 }}>+ Add a focus point</Btn>
                            )}
                            {focusState.problem && <div role="alert" style={{ color: t.danger, fontSize: 13 }}>{focusState.problem}</div>}
                        </section>
                    )}

                    {step === 3 && (
                        <section aria-label="Review and submit" data-rr-review>
                            <Label>What will be shared</Label>
                            <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 14px", margin: "10px 0 14px", fontSize: 14, color: t.text }}>
                                <dt style={{ color: t.textMuted }}>Document</dt><dd style={{ margin: 0 }}>{row?.title || "Untitled document"}</dd>
                                <dt style={{ color: t.textMuted }}>Version</dt><dd style={{ margin: 0 }}>Version {version?.version}{version?.created_at ? ` · ${formatWhen(version.created_at)}` : ""}</dd>
                                <dt style={{ color: t.textMuted }}>Lawyer</dt><dd style={{ margin: 0 }}>{engagement?.lawyer_name || "Your lawyer"}{engagement?.case_title ? ` · ${engagement.case_title}` : ""}</dd>
                                <dt style={{ color: t.textMuted }}>Note</dt><dd style={{ margin: 0, whiteSpace: "pre-wrap" }}>{note.trim() || "—"}</dd>
                                <dt style={{ color: t.textMuted }}>Focus</dt><dd style={{ margin: 0 }}>{focusState.items.length ? focusState.items.join(", ") : "—"}</dd>
                            </dl>
                            <p data-rr-d4 style={{ margin: 0, padding: "10px 12px", borderRadius: 10, background: t.inputBg, color: t.text, fontSize: 13.5, lineHeight: 1.5 }}>
                                {CANCEL_LIMIT_NOTICE}
                            </p>
                        </section>
                    )}

                    {problem && (
                        <div role="alert" data-rr-problem style={{ marginTop: 14, color: t.danger, fontSize: 14, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                            {problem.message}
                            {problem.existingId && <Btn kind="ghost" onClick={() => onOpenExisting?.(problem.existingId)}>Open it</Btn>}
                            {problem.retry && <Btn kind="ghost" onClick={problem.retry} disabled={busy}>Try again</Btn>}
                        </div>
                    )}

                    <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 20, flexWrap: "wrap" }}>
                        <Btn kind="quiet" onClick={onClose} disabled={busy}>Close</Btn>
                        {step > (hasDraft ? 2 : 0) && <Btn onClick={() => { setProblem(null); setStep(s => s - 1); }} disabled={busy}>Back</Btn>}
                        {editing && step === 2 && (
                            <Btn onClick={saveDraft} disabled={busy || !canNext}>Save draft</Btn>
                        )}
                        {step < 3
                            ? <Btn kind="primary" onClick={() => setStep(s => s + 1)} disabled={!canNext}>Next</Btn>
                            : <Btn kind="primary" onClick={send} disabled={busy} aria-busy={busy}>{busy ? "Sending…" : "Send for review"}</Btn>}
                    </div>
                </Card>
            </div>
        </ModalPortal>
    );
}

/* Cancel a sent request (§10: sent or opened → cancel). Kept here so the key
 * discipline matches the dialog's. */
export async function cancelRequest(request, keyFor) {
    const body = { expectedStateVersion: request.state_version };
    return cancelReviewRequest(request.id, body, keyFor({ op: "cancel", id: request.id, ...body }));
}
