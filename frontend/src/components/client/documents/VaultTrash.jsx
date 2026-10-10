'use client';
/* Recoverable deletion in the Vault: the confirm dialog and "Recently deleted".
 *
 * Deleting asks the server first what it will mean (deletion preview) and says
 * it before the button: how long the document can be restored, which open
 * review requests will be cancelled, and which lawyer keeps read-only access
 * to an accepted version until when. Nothing is guessed here. The Delete and
 * Restore buttons are guarded against double clicks; both actions are also
 * idempotent on the server. */
import React, { useEffect, useRef, useState } from "react";
import { useT } from "../theme.js";
import {
    deleteDocumentV2, getDocumentDeletionPreview, listDeletedDocumentsV2, restoreDocumentV2,
} from "@/lib/api.js";
import { deletionErrorMessage, deletionWarnings, purgeDayText } from "@/lib/vaultDeletion.js";
import { formatWhen } from "./DocsVault.jsx";
import { BACKDROP, Btn, Card, ModalPortal } from "./ui.jsx";

export function DeleteDocumentDialog({ row, onClose, onDeleted }) {
    const t = useT();
    const [preview, setPreview] = useState(null);
    const [problem, setProblem] = useState(null);
    const [busy, setBusy] = useState(false);
    const inFlight = useRef(false);

    useEffect(() => {
        let alive = true;
        (async () => {
            const res = await getDocumentDeletionPreview(row.id);
            if (!alive) return;
            if (res?.error) { setProblem(deletionErrorMessage(res.error.code, "Could not check this document.")); return; }
            setPreview(res.data);
        })();
        return () => { alive = false; };
    }, [row.id]);

    const confirm = async () => {
        if (inFlight.current) return;
        inFlight.current = true;
        setBusy(true);
        const res = await deleteDocumentV2(row.id);
        inFlight.current = false;
        setBusy(false);
        if (res?.error) { setProblem(deletionErrorMessage(res.error.code, res.error.message)); return; }
        onDeleted?.(res.data);
    };

    const warnings = deletionWarnings(preview);
    return (
        <ModalPortal>
            <div data-docs-font style={BACKDROP} onMouseDown={e => { if (e.target === e.currentTarget && !busy) onClose?.(); }}>
                <Card role="dialog" aria-modal="true" aria-labelledby="vd-title" data-delete-dialog
                    style={{ width: "min(520px, calc(100vw - 32px))", margin: "12vh auto 0", padding: 24, boxSizing: "border-box" }}>
                    <h2 id="vd-title" style={{ margin: 0, fontSize: 19, color: t.text }}>Delete “{row.title || "Untitled document"}”?</h2>
                    {!preview && !problem && <p aria-busy="true" style={{ color: t.textMuted }}>Checking what this affects…</p>}
                    {warnings.length > 0 && (
                        <ul data-delete-warnings style={{ margin: "14px 0 0", paddingLeft: 20, color: t.text, fontSize: 14, lineHeight: 1.6 }}>
                            {warnings.map((w, i) => <li key={i}>{w}</li>)}
                        </ul>
                    )}
                    {problem && <div role="alert" data-delete-problem style={{ marginTop: 14, color: t.danger, fontSize: 14 }}>{problem}</div>}
                    <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 20 }}>
                        <Btn kind="quiet" onClick={onClose} disabled={busy}>Keep it</Btn>
                        <Btn kind="danger" onClick={confirm} disabled={busy || !preview || Boolean(preview?.blocked)}>
                            {busy ? "Deleting…" : "Delete"}
                        </Btn>
                    </div>
                </Card>
            </div>
        </ModalPortal>
    );
}

/* "Recently deleted": what can still be restored, and until when. */
export function RecentlyDeleted({ reloadSignal = 0, onRestored }) {
    const t = useT();
    const [items, setItems] = useState(null);
    const [error, setError] = useState(null);
    const [busyId, setBusyId] = useState(null);
    const inFlight = useRef(false);

    const load = async () => {
        const res = await listDeletedDocumentsV2();
        if (res?.error) { setError(deletionErrorMessage(res.error.code, "Could not load recently deleted documents.")); return; }
        setError(null);
        setItems(res.data?.items || []);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(() => { load(); }, [reloadSignal]);

    const restore = async item => {
        if (inFlight.current) return;
        inFlight.current = true;
        setBusyId(item.id);
        const res = await restoreDocumentV2(item.id);
        inFlight.current = false;
        setBusyId(null);
        if (res?.error) { setError(deletionErrorMessage(res.error.code, res.error.message)); load(); return; }
        await load();
        onRestored?.(item);
    };

    if (error) return <div role="alert" style={{ padding: 24, color: t.text }}>{error}</div>;
    if (items === null) return <div aria-busy="true" style={{ padding: 24, color: t.textMuted }}>Loading…</div>;
    if (items.length === 0) {
        return <div data-trash-empty style={{ padding: 24, color: t.textMuted, fontSize: 14 }}>Nothing here. Deleted documents stay here for a while so you can restore them.</div>;
    }
    return (
        <ul aria-label="Recently deleted" style={{ listStyle: "none", margin: 0, padding: "6px 18px 14px" }}>
            {items.map(item => (
                <li key={item.id} data-trash-row={item.id}
                    style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", padding: "14px 6px", borderBottom: `1px solid ${t.border}` }}>
                    <div style={{ flex: 1, minWidth: 200 }}>
                        <div style={{ fontWeight: 600, color: t.text }}>{item.title || "Untitled document"}</div>
                        <div style={{ fontSize: 13, color: t.textMuted, marginTop: 4 }}>
                            Deleted {formatWhen(item.deleted_at)} · {purgeDayText(item)}
                        </div>
                    </div>
                    {item.restorable && (
                        <Btn onClick={() => restore(item)} disabled={busyId === item.id}>
                            {busyId === item.id ? "Restoring…" : "Restore"}
                        </Btn>
                    )}
                </li>
            ))}
        </ul>
    );
}
