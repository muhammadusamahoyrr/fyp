'use client';
import { useCallback, useEffect, useState } from "react";
import {
    myDocumentsV2, downloadDocumentFile, errorCode, getDocumentV2,
    fetchRevisionPreview,
} from "@/lib/api.js";
import { documentStatusView } from "@/lib/documentStatus.js";
import RevisionHistory from "@/components/shared/RevisionHistory.jsx";

/* Documents this lawyer owns, and can come back to.
 *
 * WHY THIS EXISTS
 *
 * Nothing listed a document by its OWNER. `/documents/case/{id}` is per-case and
 * the review queue is per-reviewer, so a lawyer's own output — a draft saved to
 * Documents, a standalone court-Urdu pleading — was reachable only by its id, in
 * the session that created it. Navigate away and the document was still there,
 * still hashed, still citation-checked, and permanently unfindable. Saving
 * something the system then loses is worse than not offering to save it.
 *
 * DISTINCT FROM "My Drafts" ABOVE IT. A draft is editable prose held in the
 * drafts store; a document is a fixed, hashed artifact with a revision. They are
 * different objects with different guarantees, so they are two lists rather than
 * one merged one that would have to lie about half its rows.
 */
export default function MyDocuments({ t }) {
    const [items, setItems] = useState(null);      // null = not loaded yet
    const [cursor, setCursor] = useState(null);
    const [loading, setLoading] = useState(false);
    const [issue, setIssue] = useState(null);
    const [busyId, setBusyId] = useState(null);
    const [active, setActive] = useState(null);
    const [viewRev, setViewRev] = useState(null);
    const [previewUrl, setPreviewUrl] = useState(null);
    const [actionIssue, setActionIssue] = useState(null);

    const load = useCallback(async (after = null) => {
        setLoading(true);
        const { data, error, status } = await myDocumentsV2({ cursor: after });
        setLoading(false);

        if (error) {
            // The flag is off. Not an error worth showing someone who was never
            // offered the feature — the section simply is not there.
            setItems([]);
            setIssue(status === 404 && errorCode(error) === "feature_disabled"
                ? null
                : (error.message || "Could not load your documents."));
            return;
        }
        const page = data?.items || [];
        setItems(prev => (after ? [...(prev || []), ...page] : page));
        setCursor(data?.next_cursor || null);
        setIssue(null);
    }, []);

    useEffect(() => { load(); }, [load]);

    const download = async (row) => {
        setBusyId(row.id);
        // By revision and hash, not by file path: a V2 document has no
        // file_path, and the legacy download route 404s on every one of them.
        const result = await downloadDocumentFile(
            row.id, `${(row.title || "document").replace(/[^\w\s-]/g, "").trim() || "document"}.pdf`,
            { revisionId: row.revision_id, expectedPdfSha256: row.pdf_sha256 });
        setBusyId(null);
        if (result?.error) setActionIssue(result.error.message || "Could not download that document.");
    };

    const open = async (row) => {
        setBusyId(row.id);
        setActionIssue(null);
        const { data, error } = await getDocumentV2(row.id);
        setBusyId(null);
        if (error || !data) {
            setActionIssue(error?.message || "Could not open that document.");
            return;
        }
        setActive(data);
        setViewRev(null);
    };

    useEffect(() => {
        let live = true;
        let url = null;
        const current = active?.current_revision;
        const revisionId = viewRev?.revision_id || current?.revision_id;
        const pdfSha256 = viewRev?.pdf_sha256 || current?.pdf_sha256;
        if (!active?.id || !revisionId) { setPreviewUrl(null); return; }

        fetchRevisionPreview(active.id, {
            revisionId, expectedPdfSha256: pdfSha256,
        }).then(result => {
            if (!live) {
                if (result?.data?.url) URL.revokeObjectURL(result.data.url);
                return;
            }
            if (result?.data?.url) {
                url = result.data.url;
                setPreviewUrl(url);
                setActionIssue(null);
            } else {
                setPreviewUrl(null);
                setActionIssue(result?.error?.message || "Could not preview that document.");
            }
        });
        return () => { live = false; if (url) URL.revokeObjectURL(url); };
    }, [active, viewRev]);

    // Nothing saved yet, and the feature is on: say nothing rather than show an
    // empty box. A lawyer who has never used it does not need to be told.
    if (!items || (items.length === 0 && !issue)) return null;

    return (
        <div style={{
            border: `1.5px solid ${t.border}`, borderRadius: 14,
            background: t.card, padding: "16px 18px", marginBottom: 20,
        }}>
            <div style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                marginBottom: 12,
            }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>
                    My Documents
                </div>
                <button onClick={() => { setCursor(null); load(); }} disabled={loading}
                    style={{
                        padding: "5px 11px", borderRadius: 8,
                        border: `1px solid ${t.border}`, background: "transparent",
                        color: t.textMuted, fontSize: 11, fontWeight: 600,
                        cursor: loading ? "default" : "pointer", fontFamily: "inherit",
                    }}>
                    {loading ? "Loading…" : "Refresh"}
                </button>
            </div>

            <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 12, lineHeight: 1.6 }}>
                Saved documents keep a fixed copy and its checksum, so the file you
                download later is provably the one that was checked.
            </div>

            {issue && (
                <div style={{ fontSize: 11.5, color: t.danger || "#e5484d", marginBottom: 10 }}>
                    {issue}
                </div>
            )}
            {actionIssue && (
                <div role="alert" style={{ fontSize: 11.5, color: t.danger || "#e5484d", marginBottom: 10 }}>
                    {actionIssue}
                </div>
            )}

            {items.map(row => (
                <div key={row.id}>
                <div style={{
                    display: "flex", alignItems: "center", gap: 10,
                    padding: "9px 0", borderTop: `1px solid ${t.border}`,
                }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{
                            fontSize: 12.5, fontWeight: 600, color: t.text,
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        }}>
                            {row.title || "Untitled"}
                        </div>
                        <div style={{ fontSize: 10.5, color: t.textMuted, marginTop: 2 }}>
                            v{row.version}
                            {row.review_status && row.review_status !== "none"
                                && ` · ${documentStatusView(row).label}`}
                        </div>
                        {/* A document the migration could not fully carry over says so
                            HERE, in the list, because this is where its owner finds it.
                            A raw status string ("migration_unrecoverable") tells the
                            owner nothing and reads as a system error they caused. */}
                        {documentStatusView(row).isRecovery && (
                            <div style={{
                                fontSize: 10.5, color: t.warn, marginTop: 3,
                                lineHeight: 1.5,
                            }}>
                                ⚠️ {documentStatusView(row).explanation}
                            </div>
                        )}
                    </div>

                    <button onClick={() => open(row)} disabled={busyId === row.id}
                        style={{ padding: "5px 12px", borderRadius: 8, border: `1px solid ${t.border}`, background: "transparent", color: t.text, fontSize: 11.5, fontWeight: 700, fontFamily: "inherit", cursor: busyId === row.id ? "default" : "pointer", flexShrink: 0 }}>
                        {busyId === row.id ? "…" : active?.id === row.id ? "Reload" : "Open"}
                    </button>
                    {row.downloadable ? (
                        <button onClick={() => download(row)} disabled={busyId === row.id}
                            style={{
                                padding: "5px 12px", borderRadius: 8,
                                border: `1.5px solid ${t.primary}40`,
                                background: t.primaryGlow2, color: t.primary,
                                fontSize: 11.5, fontWeight: 700, fontFamily: "inherit",
                                cursor: busyId === row.id ? "default" : "pointer",
                                flexShrink: 0,
                            }}>
                            {busyId === row.id ? "…" : "Download"}
                        </button>
                    ) : (
                        // No bytes were ever produced for this one. Said plainly
                        // rather than offering a download that fails: an
                        // unexplained failure reads as the file being lost.
                        <span style={{ fontSize: 10.5, color: t.textFaint, flexShrink: 0 }}>
                            No file
                        </span>
                    )}
                </div>
                {active?.id === row.id && (
                    <div style={{ padding: "12px", marginBottom: 10, borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}` }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                            <div style={{ fontSize: 11.5, fontWeight: 700, color: t.text }}>
                                {viewRev ? `Previewing version ${viewRev.version}` : `Current version ${active.current_version || row.version}`}
                            </div>
                            <button onClick={() => { setActive(null); setViewRev(null); }} style={{ border: 0, background: "transparent", color: t.textMuted, cursor: "pointer", fontSize: 11 }}>Close</button>
                        </div>
                        {previewUrl ? (
                            <iframe title={`${row.title || "Document"} preview`} src={previewUrl} style={{ width: "100%", height: 420, border: `1px solid ${t.border}`, borderRadius: 8, background: "#fff" }} />
                        ) : (
                            <div style={{ padding: 24, textAlign: "center", color: t.textMuted, fontSize: 11.5 }}>Loading preview…</div>
                        )}
                        <RevisionHistory
                            docId={row.id} t={t}
                            reloadKey={active.current_revision?.revision_id}
                            currentRevisionId={viewRev?.revision_id || active.current_revision?.revision_id}
                            onPreview={rev => setViewRev(
                                rev.revision_id === active.current_revision?.revision_id ? null : rev)} />
                    </div>
                )}
                </div>
            ))}

            {cursor && (
                <button onClick={() => load(cursor)} disabled={loading}
                    style={{
                        marginTop: 10, width: "100%", padding: "7px",
                        borderRadius: 8, border: `1px solid ${t.border}`,
                        background: "transparent", color: t.textMuted,
                        fontSize: 11.5, fontWeight: 600, fontFamily: "inherit",
                        cursor: loading ? "default" : "pointer",
                    }}>
                    {loading ? "Loading…" : "Load more"}
                </button>
            )}
        </div>
    );
}
