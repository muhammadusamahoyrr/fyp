'use client';
/* The client's document review requests, in the Vault (DOCUMENT_REVIEW_REQUEST_PLAN.md §10).
 *
 * Each request shows its state in the client's words -- Draft (only you can
 * see this), Sent, Opened by the lawyer, Accepted, Declined (+ reason),
 * Cancelled (+ why) -- and only the actions that state allows: a draft can be
 * continued or deleted, a sent or opened request cancelled, a finished one
 * nothing. Every action names the state version it read; if the request moved
 * meanwhile the server says so (409) and the list reloads. */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useT } from "../theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import { deleteReviewRequest, getReviewRequest, listEngagements, listReviewRequests } from "@/lib/api.js";
import {
    REQUEST_NOT_FOUND, isRequestId, requestActions, requestErrorMessage, requestStatusView,
} from "@/lib/reviewRequests.js";
import ReviewRequestDialog, { cancelRequest, useKeyFor } from "./ReviewRequestDialog.jsx";
import { formatWhen } from "./DocsVault.jsx";
import { Btn, Pill } from "./ui.jsx";

export default function ReviewRequestsPanel({ reloadSignal = 0, focusId = null, focusInvalid = false, onChanged }) {
    const t = useT();
    const toast = useToast();
    const keyFor = useKeyFor();
    const [items, setItems] = useState([]);
    const [cursor, setCursor] = useState(null);
    const [loaded, setLoaded] = useState(false);
    const [error, setError] = useState(null);
    const [names, setNames] = useState({});
    const [busyId, setBusyId] = useState(null);
    const [confirm, setConfirm] = useState(null);        // { kind: "cancel" | "delete", request }
    const [continuing, setContinuing] = useState(null);  // a draft opened in the dialog
    // The request a deep link asked for, fetched on its own so it shows even
    // when it is not on the first page. Any failure -- missing, another
    // client's (the server answers both with the same 404), malformed -- is
    // the same calm "not found", with no detail about why.
    const [focused, setFocused] = useState(null);
    const [focusMissing, setFocusMissing] = useState(false);
    useEffect(() => {
        if (focusInvalid || (focusId && !isRequestId(focusId))) { setFocusMissing(true); return undefined; }
        if (!focusId) return undefined;
        let alive = true;
        (async () => {
            const res = await getReviewRequest(focusId);
            if (!alive) return;
            if (res?.error || !res?.data?.id) { setFocusMissing(true); return; }
            setFocused(res.data);
        })();
        return () => { alive = false; };
    }, [focusId, focusInvalid]);
    useEffect(() => {
        if (!focused || typeof document === "undefined") return;
        document.querySelector(`[data-review-request="${focused.id}"]`)?.scrollIntoView?.({ block: "center" });
    }, [focused, loaded]);

    const load = useCallback(async (more = null) => {
        const res = await listReviewRequests({ cursor: more, limit: 20 });
        if (res?.error) { setError(requestErrorMessage(res.error.code, "Could not load your review requests.")); setLoaded(true); return; }
        setError(null);
        setItems(list => (more ? [...list, ...(res.data?.items || [])] : (res.data?.items || [])));
        setCursor(res.data?.next_cursor || null);
        setLoaded(true);
    }, []);

    useEffect(() => { load(); }, [load, reloadSignal]);
    useEffect(() => {
        (async () => {
            const res = await listEngagements({});
            const map = {};
            for (const e of res?.data || []) map[e.id] = { lawyer_name: e.lawyer_name, case_title: e.case_title };
            setNames(map);
        })();
    }, []);

    const named = useMemo(() => {
        const list = focused && !items.some(r => r.id === focused.id) ? [focused, ...items] : items;
        return list.map(r => ({ ...r, ...(names[r.engagement_id] || {}) }));
    }, [items, names, focused]);
    const notFound = focusMissing
        ? <div role="alert" data-rr-not-found style={{ margin: "14px 18px 0", fontSize: 14, color: t.text }}>{REQUEST_NOT_FOUND}</div>
        : null;

    const act = async (kind, request) => {
        setBusyId(request.id);
        const res = kind === "cancel"
            ? await cancelRequest(request, keyFor)
            : await deleteReviewRequest(request.id, { expectedStateVersion: request.state_version },
                keyFor({ op: "delete", id: request.id, expectedStateVersion: request.state_version }));
        setBusyId(null);
        setConfirm(null);
        if (res?.error) {
            toast.show(requestErrorMessage(res.error.code, res.error.message), "danger", 4500);
            if (res.error.code === "stale_state" || res.error.code === "request_accepted") load();
            return;
        }
        toast.show(kind === "cancel" ? "Request cancelled. Your lawyer can no longer open it." : "Draft deleted.", "success", 3000);
        load();
        onChanged?.();
    };

    if (!loaded) return <div aria-busy="true" style={{ padding: 28, color: t.textMuted }}>Loading your review requests…</div>;
    if (error) {
        return (
            <div role="alert" style={{ padding: 28, display: "flex", gap: 12, alignItems: "center", color: t.text }}>
                {error} <Btn onClick={() => load()}>Try again</Btn>
            </div>
        );
    }
    if (named.length === 0) {
        return (
            <>{notFound}<div data-rr-none style={{ padding: 28, color: t.textMuted, fontSize: 14, lineHeight: 1.6 }}>
                You have not asked a lawyer to review a document yet. Use “Request lawyer review” on a document above.
            </div></>
        );
    }

    return (
        <div style={{ padding: "6px 18px 14px" }}>
            {notFound}
            <ul aria-label="Your review requests" style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {named.map(r => {
                    const view = requestStatusView(r);
                    const can = requestActions(r);
                    return (
                        <li key={r.id} data-review-request={r.id} data-status={r.status}
                            data-rr-focused={focused?.id === r.id ? "true" : undefined}
                            aria-current={focused?.id === r.id ? "true" : undefined}
                            style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap", padding: "14px 6px",
                                     borderBottom: `1px solid ${t.border}`, background: focused?.id === r.id ? t.primaryGlow2 : "transparent" }}>
                            <div style={{ flex: 1, minWidth: 220 }}>
                                <div style={{ fontWeight: 600, color: t.text, fontSize: 14.5 }}>
                                    {r.document_title || "Untitled document"} <span style={{ color: t.textMuted, fontWeight: 400 }}>· v{r.version}</span>
                                </div>
                                <div style={{ fontSize: 13, color: t.textMuted, marginTop: 4 }}>
                                    To {r.lawyer_name || "your lawyer"}{r.case_title ? ` · ${r.case_title}` : ""} · {formatWhen(r.submitted_at || r.created_at)}
                                </div>
                                <div data-rr-detail style={{ fontSize: 13, color: t.text, marginTop: 6 }}>{view.detail}</div>
                            </div>
                            <Pill tone={view.tone}>{view.label}</Pill>
                            <div style={{ display: "flex", gap: 6 }}>
                                {can.edit && <Btn onClick={() => setContinuing(r)} disabled={busyId === r.id}>Continue</Btn>}
                                {can.delete && <Btn kind="danger" onClick={() => setConfirm({ kind: "delete", request: r })} disabled={busyId === r.id}>Delete</Btn>}
                                {can.cancel && <Btn kind="danger" onClick={() => setConfirm({ kind: "cancel", request: r })} disabled={busyId === r.id}>Cancel request</Btn>}
                            </div>
                            {confirm?.request?.id === r.id && (
                                <div role="alertdialog" aria-label="Confirm" data-rr-confirm
                                    style={{ flexBasis: "100%", display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", fontSize: 13.5, color: t.text }}>
                                    {confirm.kind === "cancel"
                                        ? "Cancel this request? Your lawyer will no longer be able to open the document."
                                        : "Delete this draft? It was never sent."}
                                    <Btn kind="danger" onClick={() => act(confirm.kind, r)} disabled={busyId === r.id}>
                                        {confirm.kind === "cancel" ? "Yes, cancel it" : "Yes, delete it"}
                                    </Btn>
                                    <Btn kind="quiet" onClick={() => setConfirm(null)} disabled={busyId === r.id}>Keep it</Btn>
                                </div>
                            )}
                        </li>
                    );
                })}
            </ul>
            {cursor && <Btn onClick={() => load(cursor)} style={{ marginTop: 12 }}>Load more</Btn>}
            {continuing && (
                <ReviewRequestDialog
                    row={{ id: continuing.document_id, title: continuing.document_title, revision_id: continuing.revision_id }}
                    draft={continuing}
                    onClose={() => setContinuing(null)}
                    onDone={req => {
                        setContinuing(null);
                        toast.show(req.status === "draft" ? "Draft saved." : "Sent to your lawyer.", "success", 3000);
                        load();
                        onChanged?.();
                    }} />
            )}
        </div>
    );
}
