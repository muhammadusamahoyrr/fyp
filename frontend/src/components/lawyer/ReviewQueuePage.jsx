'use client';
/* The lawyer's Review Queue (DOCUMENT_REVIEW_REQUEST_PLAN.md §5, Phase 2).
 *
 * Every request a client sent THIS lawyer: newest submission first, filtered by
 * state, paged by the server's stable (submitted_at, _id) cursor. A request
 * opens into a detail with the client's note and focus points, the frozen
 * version, the original file, and the decisions.
 *
 * READING CHANGES NOTHING. Opening a request here does not mark it viewed --
 * a GET can be fired by a prefetch -- so "Mark as viewed" is an explicit
 * button. Accept and Decline name the state version they read; if the client
 * cancelled meanwhile, the server says so (409) and the request is reloaded.
 * Both are double-click safe: a ref guard, and the same Idempotency-Key for
 * the same body.
 *
 * NO ANALYSIS. The client's document may be real, and the Document Analyzer is
 * synthetic-only, so nothing here sends it there and no "Open in Analyzer"
 * control exists (ANALYZER_HANDOFF_ENABLED). The lawyer downloads the original
 * and reviews it themselves.
 *
 * Shown only while DOCUMENT_REVIEW_REQUESTS is on: a 404 `feature_disabled`
 * sends the lawyer back to Documents. */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { ThemeCtx as WorkspaceThemeCtx } from "@/components/client/theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import {
    acceptReviewRequest, declineReviewRequest, downloadReviewRequestDocument, getReviewRequest,
    idempotencyKey, listEngagements, listReviewInbox, markReviewRequestViewed,
} from "@/lib/api.js";
import {
    DECLINE_REASON_MAX, LAWYER_REQUEST_NOT_FOUND, REVIEW_QUEUE_PATH, counterText, lawyerActions,
    lawyerErrorMessage, lawyerStatusView, readLawyerReviewLink,
} from "@/lib/reviewRequests.js";
import { Btn, Card, Label, Pill, fieldStyle } from "@/components/client/documents/ui.jsx";
import { formatWhen } from "@/components/client/documents/DocsVault.jsx";
import { useCase, useTheme } from "./theme.js";

const FILTERS = [
    [null, "All"], ["submitted", "New"], ["viewed", "Opened"],
    ["accepted", "Accepted"], ["declined", "Declined"], ["cancelled", "Cancelled"],
];

function useKeyFor() {
    const memo = useRef(new Map());
    return body => {
        const fp = JSON.stringify(body);
        if (!memo.current.has(fp)) memo.current.set(fp, idempotencyKey());
        return memo.current.get(fp);
    };
}

export function ReviewQueuePage() {
    const { t } = useTheme();
    return (
        <WorkspaceThemeCtx.Provider value={t}>
            <ReviewQueue t={t} />
        </WorkspaceThemeCtx.Provider>
    );
}

function ReviewQueue({ t }) {
    const toast = useToast();
    const { setPage } = useCase();
    const [link] = useState(() => (typeof window === "undefined"
        ? { requestId: null, invalid: false } : readLawyerReviewLink(window.location.search)));
    const [filter, setFilter] = useState(null);
    const [items, setItems] = useState([]);
    const [cursor, setCursor] = useState(null);
    const [state, setState] = useState("loading");        // loading | ready | error
    const [error, setError] = useState(null);
    const [cases, setCases] = useState({});
    const [selectedId, setSelectedId] = useState(link.requestId);
    const [notFound, setNotFound] = useState(link.invalid);

    const load = useCallback(async (more = null) => {
        if (!more) setState("loading");
        const res = await listReviewInbox({ status: filter, cursor: more, limit: 20 });
        if (res?.error) {
            if (res.status === 404 && res.error.code === "feature_disabled") { setPage?.("documents"); return; }
            setError(lawyerErrorMessage(res.error.code, "Could not load your review queue."));
            setState("error");
            return;
        }
        setItems(list => (more ? [...list, ...(res.data?.items || [])] : (res.data?.items || [])));
        setCursor(res.data?.next_cursor || null);
        setState("ready");
    }, [filter, setPage]);

    useEffect(() => { load(); }, [load]);
    useEffect(() => {
        (async () => {
            const res = await listEngagements({});
            const map = {};
            for (const e of Array.isArray(res?.data) ? res.data : []) map[e.id] = e.case_title || "";
            setCases(map);
        })();
    }, []);
    // The deep link is consumed once: the address goes back to the plain queue
    // (a fixed path), so a refresh does not replay it.
    useEffect(() => {
        if (!link.requestId && !link.invalid) return;
        try { window.history.replaceState(window.history.state, "", REVIEW_QUEUE_PATH); } catch { /* not fatal */ }
    }, [link]);

    const replace = updated => setItems(list => list.map(r => (r.id === updated.id ? { ...r, ...updated } : r)));

    return (
        <div data-review-queue style={{ display: "flex", flexDirection: "column", gap: 18, color: t.text }}>
            <header>
                <h1 style={{ margin: 0, fontSize: 26, fontWeight: 700 }}>Review Queue</h1>
                <p style={{ margin: "6px 0 0", fontSize: 14, color: t.textMuted, maxWidth: 760, lineHeight: 1.6 }}>
                    Documents your clients sent you for review. Each request is one exact version, frozen when it was sent.
                </p>
            </header>

            {notFound && (
                <div role="alert" data-rq-not-found style={{ fontSize: 14, color: t.text }}>{LAWYER_REQUEST_NOT_FOUND}</div>
            )}

            <div role="tablist" aria-label="Filter by state" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {FILTERS.map(([value, name]) => (
                    <button key={name} type="button" role="tab" aria-selected={filter === value}
                        onClick={() => { setFilter(value); setCursor(null); }}
                        style={{ minHeight: 34, padding: "0 14px", borderRadius: 999, cursor: "pointer", fontSize: 13,
                                 border: `1px solid ${filter === value ? t.primary : t.border}`,
                                 background: filter === value ? t.primaryGlow2 || t.card : "transparent",
                                 color: filter === value ? t.primary : t.text, fontWeight: filter === value ? 700 : 500 }}>
                        {name}
                    </button>
                ))}
            </div>

            <div style={{ display: "flex", gap: 18, alignItems: "flex-start", flexWrap: "wrap" }}>
                <Card style={{ flex: "1 1 420px", minWidth: 0, padding: 0, overflow: "hidden" }}>
                    {state === "loading" ? (
                        <div aria-busy="true" style={{ padding: 24, color: t.textMuted }}>Loading your review queue…</div>
                    ) : state === "error" ? (
                        <div role="alert" style={{ padding: 24, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                            {error} <Btn onClick={() => load()}>Try again</Btn>
                        </div>
                    ) : items.length === 0 ? (
                        <div data-rq-empty style={{ padding: 24, color: t.textMuted, fontSize: 14, lineHeight: 1.6 }}>
                            {filter ? "No requests in this state." : "No review requests yet. When a client sends you a document, it appears here."}
                        </div>
                    ) : (
                        <ul aria-label="Review requests" style={{ listStyle: "none", margin: 0, padding: 0 }}>
                            {items.map(r => {
                                const view = lawyerStatusView(r);
                                const selected = selectedId === r.id;
                                return (
                                    <li key={r.id}>
                                        <button type="button" data-rq-row={r.id} aria-current={selected ? "true" : undefined}
                                            onClick={() => { setNotFound(false); setSelectedId(r.id); }}
                                            style={{ width: "100%", textAlign: "left", display: "flex", gap: 12, alignItems: "center",
                                                     padding: "14px 18px", border: "none", borderBottom: `1px solid ${t.border}`,
                                                     background: selected ? (t.primaryGlow2 || t.card) : "transparent",
                                                     color: t.text, cursor: "pointer" }}>
                                            <span style={{ flex: 1, minWidth: 0 }}>
                                                <span style={{ display: "block", fontWeight: 600, fontSize: 14.5 }}>
                                                    {r.document_title || "Untitled document"} <span style={{ color: t.textMuted, fontWeight: 400 }}>· v{r.version}</span>
                                                </span>
                                                <span style={{ display: "block", fontSize: 13, color: t.textMuted, marginTop: 4 }}>
                                                    {r.client_name || "Client"}{cases[r.engagement_id] ? ` · ${cases[r.engagement_id]}` : ""} · sent {formatWhen(r.submitted_at)}
                                                </span>
                                            </span>
                                            <Pill tone={view.tone}>{view.label}</Pill>
                                        </button>
                                    </li>
                                );
                            })}
                        </ul>
                    )}
                    {state === "ready" && cursor && (
                        <div style={{ padding: 14 }}><Btn onClick={() => load(cursor)}>Load more</Btn></div>
                    )}
                </Card>

                {selectedId && (
                    <RequestDetail key={selectedId} t={t} requestId={selectedId} cases={cases}
                        onMissing={() => { setSelectedId(null); setNotFound(true); }}
                        onChanged={updated => { replace(updated); }}
                        onStale={() => load()}
                        toast={toast} />
                )}
            </div>
        </div>
    );
}

function RequestDetail({ t, requestId, cases, onMissing, onChanged, onStale, toast }) {
    const keyFor = useKeyFor();
    const [request, setRequest] = useState(null);
    const [busy, setBusy] = useState(false);
    const inFlight = useRef(false);                        // the real double-click guard
    const [confirm, setConfirm] = useState(null);         // "accept" | "decline"
    const [reason, setReason] = useState("");
    const [problem, setProblem] = useState(null);

    // The parent's callbacks are new functions every render; read them through
    // a ref so the load effect depends on the request id alone and runs once.
    const onMissingRef = useRef(onMissing);
    onMissingRef.current = onMissing;
    const reload = useCallback(async () => {
        const res = await getReviewRequest(requestId);
        if (res?.error || !res?.data?.id) { onMissingRef.current?.(); return null; }
        setRequest(res.data);
        return res.data;
    }, [requestId]);
    useEffect(() => { reload(); }, [reload]);

    const run = async (call, success) => {
        if (inFlight.current) return;
        inFlight.current = true;
        setBusy(true);
        setProblem(null);
        try {
            const res = await call();
            if (res?.error) {
                const code = res.error.code || res.code || null;
                setProblem(lawyerErrorMessage(code, res.error.message || res.error));
                if (code === "stale_state" || code === "invalid_transition") {
                    setConfirm(null);
                    const fresh = await reload();
                    if (fresh) onChanged(fresh);
                    onStale();
                }
                return;
            }
            if (res?.data && res.data.id) { setRequest(res.data); onChanged(res.data); }
            setConfirm(null);
            if (success) toast?.show?.(success, "success", 3000);
        } finally {
            inFlight.current = false;
            setBusy(false);
        }
    };

    if (!request) {
        return <Card style={{ flex: "1 1 360px", padding: 22 }}><div aria-busy="true" style={{ color: t.textMuted }}>Loading request…</div></Card>;
    }
    const view = lawyerStatusView(request);
    const can = lawyerActions(request);
    const tooLong = reason.length > DECLINE_REASON_MAX;
    const body = { expectedStateVersion: request.state_version };

    return (
        <Card data-rq-detail={request.id} role="region" aria-label="Review request" style={{ flex: "1 1 360px", minWidth: 0, padding: 22 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <h2 style={{ margin: 0, fontSize: 19, flex: 1, minWidth: 200 }}>{request.document_title || "Untitled document"}</h2>
                <Pill tone={view.tone}>{view.label}</Pill>
            </div>
            <p style={{ margin: "6px 0 14px", fontSize: 13.5, color: t.textMuted }}>{view.detail}</p>

            <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 14px", margin: 0, fontSize: 14 }}>
                <dt style={{ color: t.textMuted }}>Client</dt><dd style={{ margin: 0 }}>{request.client_name || "Client"}</dd>
                <dt style={{ color: t.textMuted }}>Case</dt><dd style={{ margin: 0 }}>{cases[request.engagement_id] || "—"}</dd>
                <dt style={{ color: t.textMuted }}>Version</dt>
                <dd data-rq-version style={{ margin: 0 }}>
                    Version {request.version} · sent {formatWhen(request.submitted_at)}
                    <span style={{ display: "block", fontSize: 12, color: t.textMuted, marginTop: 2 }}>
                        Frozen when sent; later edits by the client do not change it. Fingerprint {String(request.pdf_sha256 || "").slice(0, 12)}…
                    </span>
                </dd>
            </dl>

            <Label style={{ marginTop: 18 }}>Client's note</Label>
            <p data-rq-note style={{ margin: "6px 0 0", whiteSpace: "pre-wrap", fontSize: 14, lineHeight: 1.6 }}>{request.note || "No note."}</p>
            <Label style={{ marginTop: 14 }}>What to look at</Label>
            {request.focus?.length ? (
                <ul data-rq-focus style={{ margin: "6px 0 0", paddingLeft: 20, fontSize: 14 }}>
                    {request.focus.map((f, i) => <li key={i}>{f}</li>)}
                </ul>
            ) : <p style={{ margin: "6px 0 0", fontSize: 14, color: t.textMuted }}>No focus points.</p>}

            <p data-rq-manual style={{ margin: "16px 0 0", fontSize: 12.5, color: t.textMuted, lineHeight: 1.5 }}>
                Review this document yourself. The Document Analyzer is not available for client documents.
            </p>

            {problem && <div role="alert" data-rq-problem style={{ marginTop: 14, color: t.danger || "#f07a7a", fontSize: 14 }}>{problem}</div>}

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 18 }}>
                {can.download && (
                    <Btn onClick={() => run(async () => {
                        const res = await downloadReviewRequestDocument(request.id, `${request.document_title || "document"} v${request.version}.pdf`);
                        return res?.error ? { error: { code: res.code, message: res.error } } : {};
                    })} disabled={busy}>Download original</Btn>
                )}
                {can.markViewed && (
                    <Btn onClick={() => run(() => markReviewRequestViewed(request.id), "Marked as viewed.")} disabled={busy}>
                        Mark as viewed
                    </Btn>
                )}
                {can.accept && !confirm && <Btn kind="primary" onClick={() => setConfirm("accept")} disabled={busy}>Accept</Btn>}
                {can.decline && !confirm && <Btn kind="danger" onClick={() => setConfirm("decline")} disabled={busy}>Decline</Btn>}
            </div>

            {confirm === "accept" && (
                <div data-rq-confirm="accept" role="alertdialog" aria-label="Confirm accept" style={{ marginTop: 14, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", fontSize: 14 }}>
                    Accept this request? The client will be told you will review this version, and can no longer cancel it.
                    <Btn kind="primary" disabled={busy}
                        onClick={() => run(() => acceptReviewRequest(request.id, body, keyFor({ op: "accept", id: request.id, ...body })),
                                           "Request accepted.")}>
                        {busy ? "Accepting…" : "Yes, accept"}
                    </Btn>
                    <Btn kind="quiet" onClick={() => setConfirm(null)} disabled={busy}>Back</Btn>
                </div>
            )}
            {confirm === "decline" && (
                <div data-rq-confirm="decline" style={{ marginTop: 14 }}>
                    <Label>Reason (optional, shown to the client)</Label>
                    <textarea aria-label="Reason for declining" value={reason} onChange={e => setReason(e.target.value)} rows={3}
                        style={fieldStyle(t, { marginTop: 8, resize: "vertical" })} />
                    <div data-rq-counter style={{ textAlign: "right", fontSize: 12, color: tooLong ? (t.danger || "#f07a7a") : t.textMuted }}>
                        {counterText(reason.length, DECLINE_REASON_MAX)}
                    </div>
                    <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
                        <Btn kind="danger" disabled={busy || tooLong}
                            onClick={() => {
                                const decline = { ...body, reason: reason.trim() || null };
                                return run(() => declineReviewRequest(request.id, decline, keyFor({ op: "decline", id: request.id, ...decline })),
                                           "Request declined.");
                            }}>
                            {busy ? "Declining…" : "Decline request"}
                        </Btn>
                        <Btn kind="quiet" onClick={() => setConfirm(null)} disabled={busy}>Back</Btn>
                    </div>
                </div>
            )}
        </Card>
    );
}

export default ReviewQueuePage;
