'use client';
/* Every document this client owns, and a way back into any of them.
 *
 * `/documents/v2/mine` existed and only the lawyer UI called it. A client could
 * reach a document only while it was still on screen — close the tab and the
 * work was on the server and unreachable through the product. This is the list
 * that fixes that.
 *
 * Deliberately thin. Everything with a sequence to it — paging, the difference
 * between loading and empty, keeping a visible list when a later page fails,
 * discarding a stale response — lives in `useMyDocuments`, where it is mounted
 * and tested. What is left here is presentation.
 *
 * OWNERSHIP IS THE BACKEND'S. Nothing here sends or filters by an owner id; the
 * endpoint scopes every query to the caller. A second, client-side check would
 * be a weaker answer to a question already answered properly, and the first
 * thing to drift.
 */
import { useCallback } from "react";

import { myDocumentsV2, downloadDocumentFile, getDocumentV2 } from "@/lib/api.js";
import { useMyDocuments, rowActions } from "@/lib/useMyDocuments.js";
import { documentStatusView } from "@/lib/documentStatus.js";
import { restoreStateFromDocument } from "@/lib/documentResume.js";

export default function MyDocumentsPanel({ t, onOpen, onPreview }) {
    const fetchPage = useCallback(
        ({ cursor, limit }) => myDocumentsV2({ cursor, limit }), []);

    const { items, loading, error, hasMore, isEmpty, loadMore, reload } =
        useMyDocuments({ fetchPage, pageSize: 20 });

    /* Opening restores the whole document, not just its id: the revision, its
       hash, the review status and any recovery explanation. Restoring a subset
       produces a screen that looks ready and fails the moment it is used. */
    const open = async (row) => {
        const { data, error: err } = await getDocumentV2(row.id);
        if (err || !data) return;
        const restored = restoreStateFromDocument(data);
        if (restored && onOpen) onOpen(restored);
    };

    const card = {
        background: t.cardBg, border: `1px solid ${t.border}`,
        borderRadius: 14, padding: 16,
    };

    return (
        <div style={card}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>
                    My Documents
                </div>
                <button onClick={reload} disabled={loading}
                    style={{ background: "transparent", border: `1px solid ${t.border}`, color: t.textMuted, borderRadius: 9, padding: "5px 11px", fontSize: 11, cursor: loading ? "default" : "pointer", fontFamily: "'Inter',sans-serif" }}>
                    {loading ? "Loading…" : "↻ Refresh"}
                </button>
            </div>

            {/* THREE DISTINCT STATES. Rendering all of them as "no documents"
                tells a client their work is gone. */}
            {loading && items.length === 0 && (
                <div style={{ fontSize: 12, color: t.textMuted, padding: "10px 0" }}>
                    Loading your documents…
                </div>
            )}

            {error && (
                <div style={{ padding: "11px 13px", borderRadius: 11, background: `${t.danger}10`, border: `1px solid ${t.danger}30`, marginBottom: 10 }}>
                    <div style={{ fontSize: 11.5, color: t.text, lineHeight: 1.6 }}>
                        We could not load your documents. This does not mean they
                        are gone — only that we could not reach them just now.
                        {error.message ? ` (${error.message})` : ""}
                    </div>
                    <button onClick={reload}
                        style={{ marginTop: 8, background: "transparent", border: `1px solid ${t.border}`, color: t.text, borderRadius: 9, padding: "5px 11px", fontSize: 11, cursor: "pointer", fontFamily: "'Inter',sans-serif" }}>
                        Try again
                    </button>
                </div>
            )}

            {isEmpty && (
                <div style={{ fontSize: 12, color: t.textMuted, padding: "10px 0", lineHeight: 1.6 }}>
                    You have not generated any documents yet. When you do, they
                    will be listed here and you can come back to them at any time.
                </div>
            )}

            {items.map(row => {
                const actions = rowActions(row);
                const status = documentStatusView(row);
                return (
                    <div key={row.id}
                        style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "10px 0", borderTop: `1px solid ${t.border}` }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: 12.5, fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {row.title || "Untitled"}
                            </div>
                            <div style={{ fontSize: 10.5, color: t.textMuted, marginTop: 2 }}>
                                v{row.version} · {status.label}
                            </div>
                            {status.isRecovery && (
                                <div style={{ fontSize: 10.5, color: t.warn, marginTop: 3, lineHeight: 1.5 }}>
                                    ⚠️ {status.explanation}
                                </div>
                            )}
                            {!actions.canDownload && (
                                <div style={{ fontSize: 10.5, color: t.textFaint, marginTop: 3 }}>
                                    {actions.reason}
                                </div>
                            )}
                        </div>

                        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                            <button onClick={() => open(row)}
                                style={{ padding: "5px 10px", borderRadius: 8, border: `1px solid ${t.border}`, background: "transparent", color: t.text, fontSize: 11, cursor: "pointer", fontFamily: "'Inter',sans-serif" }}>
                                Open
                            </button>
                            {actions.canPreview && onPreview && (
                                <button onClick={() => onPreview(row.id, actions)}
                                    style={{ padding: "5px 10px", borderRadius: 8, border: `1px solid ${t.border}`, background: "transparent", color: t.text, fontSize: 11, cursor: "pointer", fontFamily: "'Inter',sans-serif" }}>
                                    Preview
                                </button>
                            )}
                            {/* The EXACT revision, with its hash: the download
                                refuses to serve different bytes than the row
                                described. */}
                            {actions.canDownload && (
                                <button onClick={() => downloadDocumentFile(
                                    row.id, row.title || "document",
                                    { revisionId: actions.revisionId,
                                      expectedPdfSha256: actions.pdfSha256 })}
                                    style={{ padding: "5px 10px", borderRadius: 8, border: "none", background: t.primary, color: "#fff", fontSize: 11, cursor: "pointer", fontFamily: "'Inter',sans-serif" }}>
                                    Download
                                </button>
                            )}
                        </div>
                    </div>
                );
            })}

            {hasMore && (
                <button onClick={loadMore} disabled={loading}
                    style={{ width: "100%", marginTop: 10, padding: "9px", borderRadius: 10, border: `1px solid ${t.border}`, background: "transparent", color: t.textMuted, fontSize: 11.5, fontWeight: 600, cursor: loading ? "default" : "pointer", fontFamily: "'Inter',sans-serif" }}>
                    {loading ? "Loading…" : "Show older documents"}
                </button>
            )}
        </div>
    );
}
