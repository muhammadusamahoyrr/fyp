'use client';
/* Document vault — every document this client has generated, in one table.
 *
 * The rows are REAL: `GET /documents/v2/mine`, the same source as My
 * Documents, with Open and Download wired to the same calls. Uploading files
 * and folders have no backend yet; those controls exist and say so instead of
 * accepting a file that would go nowhere. Figures the server does not know
 * (file size, storage used) show "—" rather than a guess. */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useT } from "../theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import { myDocumentsV2, downloadDocumentFile, getDocumentV2, listReviewRequests } from "@/lib/api.js";
import { useMyDocuments, rowActions } from "@/lib/useMyDocuments.js";
import { documentStatusView } from "@/lib/documentStatus.js";
import { restoreStateFromDocument } from "@/lib/documentResume.js";
import { humanise } from "@/lib/fieldReview.js";
import { useIsMobile } from "@/lib/i18n.jsx";
import { Btn, IconBtn, Pill, Card, Icon, fieldStyle } from "./ui.jsx";
import ReviewRequestDialog from "./ReviewRequestDialog.jsx";
import ReviewRequestsPanel from "./ReviewRequestsPanel.jsx";

const TONE = { info: "info", ok: "low", warn: "medium", danger: "high", muted: "muted" };
// Same face as the analyzer: Nunito Sans, a free near-match for Avenir.
const VAULT_FONT = "'Nunito Sans', 'Avenir Next', Avenir, system-ui, sans-serif";

export function formatWhen(value, now = new Date()) {
    if (!value) return "—";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return "—";
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) return "Today";
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/* Is the review-request feature switched on? Asked once, by the cheapest real
 * call: every review-request route answers 404 `feature_disabled` while
 * DOCUMENT_REVIEW_REQUESTS is off, and then the Vault shows nothing of it.
 * Any other failure also hides it -- an action that cannot work is not shown. */
export function reviewRequestsAvailable(res) {
    return Boolean(res && !res.error && res.data);
}

/* Who can see a document right now, in the vault's words. */
export function accessOf(row) {
    return row?.review_status === "submitted" ? "With lawyer" : "Private";
}

/* How many documents were created in the last seven days. */
export function addedThisWeek(items, now = new Date()) {
    const since = now.getTime() - 7 * 86400000;
    return (items || []).filter(r => {
        const d = new Date(r.created_at || r.updated_at || 0).getTime();
        return !Number.isNaN(d) && d >= since && d <= now.getTime();
    }).length;
}

const SORTS = [
    ["newest", "Newest first"],
    ["oldest", "Oldest first"],
    ["name", "Name (A–Z)"],
];
export function sortRows(rows, how) {
    const when = r => new Date(r.updated_at || r.created_at || 0).getTime() || 0;
    const copy = [...rows];
    if (how === "oldest") return copy.sort((a, b) => when(a) - when(b));
    if (how === "name") return copy.sort((a, b) => (a.title || "").localeCompare(b.title || ""));
    return copy.sort((a, b) => when(b) - when(a));
}

const GRID = "minmax(220px, 2.6fr) minmax(110px, 1fr) 70px minmax(110px, .9fr) 110px 120px 140px";

const svg = (d, s = 20) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>;
const I = {
    folder: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />,
    cloud: <><path d="M7 18a5 5 0 0 1-.6-9.96A6 6 0 0 1 18 9a4.5 4.5 0 0 1-.5 9" /><path d="M12 12v7M9 15l3-3 3 3" /></>,
    books: <><path d="M4 4h4v16H4zM10 4h4v16h-4z" /><path d="M16.5 4.5l3.5 1-3.5 14-3.5-1z" /></>,
    search: <><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></>,
    filter: <path d="M4 7h16M7 12h10M10 17h4" />,
    send: <><path d="M22 2L11 13" /><path d="M22 2l-7 20-4-9-9-4z" /></>,
};

export default function DocsVault({ onBack, onOpen, reviewLink = null }) {
    const t = useT();
    const toast = useToast();
    const isMobile = useIsMobile();
    const [tab, setTab] = useState("all");
    const [query, setQuery] = useState("");
    const [newFolder, setNewFolder] = useState(false);
    const [busyId, setBusyId] = useState(null);
    // null = the server's own order (newest created first); a choice from
    // the sort menu replaces it.
    const [sort, setSort] = useState(null);
    const [sortOpen, setSortOpen] = useState(false);
    // Document review requests: hidden entirely unless the server has them on.
    const [rrEnabled, setRrEnabled] = useState(null);         // null = not asked yet
    const [requesting, setRequesting] = useState(null);      // the row being shared
    const [rrReload, setRrReload] = useState(0);
    // The deep link is honoured ONCE the server has said whether the feature is
    // on. Off: the ordinary Vault, nothing of review requests. Either way the
    // query is then dropped from the address (a fixed path, never user input),
    // so a refresh does not replay it.
    const [linkFocus, setLinkFocus] = useState(null);
    useEffect(() => {
        if (!reviewLink?.open || rrEnabled === null) return;
        if (rrEnabled) {
            setTab("requests");
            setLinkFocus({ id: reviewLink.requestId, invalid: reviewLink.invalid });
        }
        try { window.history.replaceState(window.history.state, "", "/documents"); } catch { /* not fatal */ }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [rrEnabled]);
    useEffect(() => {
        let alive = true;
        (async () => {
            const res = await listReviewRequests({ limit: 1 });
            if (alive) setRrEnabled(reviewRequestsAvailable(res));
        })();
        return () => { alive = false; };
    }, []);
    const sortRef = useRef(null);
    const fetchPage = useCallback(({ cursor, limit }) => myDocumentsV2({ cursor, limit }), []);
    const docs = useMyDocuments({ fetchPage, pageSize: 25 });
    const notYet = what => () => toast.show(`${what} isn't connected yet — coming soon.`, "warn", 3000);

    useEffect(() => {
        if (!sortOpen) return;
        const close = e => { if (sortRef.current && !sortRef.current.contains(e.target)) setSortOpen(false); };
        const esc = e => { if (e.key === "Escape") setSortOpen(false); };
        document.addEventListener("mousedown", close);
        document.addEventListener("keydown", esc);
        return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
    }, [sortOpen]);

    const rows = useMemo(() => {
        const q = query.trim().toLowerCase();
        const hits = docs.items.filter(r => !q || (r.title || "").toLowerCase().includes(q)
            || (r.template_type || "").toLowerCase().includes(q));
        return sort ? sortRows(hits, sort) : hits;
    }, [docs.items, query, sort]);
    const week = addedThisWeek(docs.items);

    const open = async row => {
        setBusyId(row.id);
        const { data, error } = await getDocumentV2(row.id);
        setBusyId(null);
        const restored = !error && data ? restoreStateFromDocument(data) : null;
        if (!restored) { toast.show("Could not open that document. Try again.", "danger", 3500); return; }
        onOpen(restored);
    };
    const download = async row => {
        const a = rowActions(row);
        const res = await downloadDocumentFile(row.id, `${row.title || "document"}.pdf`,
            { revisionId: a.revisionId, expectedPdfSha256: a.pdfSha256 });
        if (res?.error) toast.show(`Download failed: ${res.error}`, "danger", 4000);
    };

    const th = { fontSize: 11.5, fontWeight: 700, letterSpacing: ".07em", color: t.textMuted, textTransform: "uppercase" };
    const panel = t.mode === "dark" ? "#1c2a3a" : t.card;          // the reference's navy panels
    const panelBorder = t.mode === "dark" ? "#27384b" : t.border;
    const stats = [
        ["Total Documents", String(docs.items.length) + (docs.hasMore ? "+" : ""), docs.loaded ? `+${week} this week` : "Loading…", I.books],
        ["Folders Created", "0", "organized vaults", I.folder],
        ["Storage Used", "—", "tracked once uploads are connected", I.cloud],
    ];

    return (
        <div data-lenis-prevent style={{ flex: 1, minHeight: 0, overflowY: "auto", fontFamily: VAULT_FONT, boxSizing: "border-box" }}>
            {/* Slogan strip */}
            <div style={{ display: "flex", alignItems: "center", gap: 14, padding: isMobile ? "60px 14px 8px" : "18px 30px 4px" }}>
                <span style={{ color: "#f2b84b", display: "flex" }}>{svg(I.folder, 22)}</span>
                <span style={{ fontSize: isMobile ? 17 : 20, fontWeight: 600, color: t.text, letterSpacing: "-0.3px" }}>Upload, organize, done.</span>
            </div>

            <div style={{ padding: isMobile ? "8px 14px 24px" : "18px 30px 30px", display: "flex", flexDirection: "column", gap: 20 }}>
                {/* Breadcrumb, heading, actions */}
                <div style={{ display: "flex", alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
                    <div style={{ flex: 1, minWidth: 260 }}>
                        <nav aria-label="Breadcrumb" style={{ fontSize: 13.5, color: t.textMuted, marginBottom: 10 }}>
                            <button type="button" onClick={onBack} style={{ background: "none", border: "none", padding: 0, color: t.textMuted, cursor: "pointer", fontSize: 13.5, fontFamily: VAULT_FONT }}>Library</button>
                            <span style={{ margin: "0 10px" }}>/</span>
                            <span style={{ color: t.text, fontWeight: 500 }}>Document Vault</span>
                        </nav>
                        <h1 style={{ margin: 0, fontSize: isMobile ? 24 : 30, fontWeight: 700, color: t.text, letterSpacing: "-0.4px" }}>Manage Your Documents</h1>
                        <p style={{ margin: "8px 0 0", fontSize: isMobile ? 13.5 : 14.5, lineHeight: 1.6, color: t.textMuted, maxWidth: 720 }}>
                            Securely upload, organize, and manage your legal files. Use specialized vaults to keep your contracts and signed documents easily accessible.
                        </p>
                    </div>
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                        <button type="button" onClick={() => { setNewFolder(true); setTab("folders"); }}
                            style={{ display: "inline-flex", alignItems: "center", gap: 10, minHeight: 40, padding: "0 16px", borderRadius: 11, border: `1px solid ${panelBorder}`, background: panel, color: t.text, fontSize: 14, fontWeight: 700, cursor: "pointer", fontFamily: VAULT_FONT }}>
                            {svg(I.folder, 16)} Create Folder
                        </button>
                        <button type="button" onClick={notYet("Uploading files")}
                            style={{ display: "inline-flex", alignItems: "center", gap: 10, minHeight: 40, padding: "0 16px", borderRadius: 11, border: "1px solid #2fa36b", background: "linear-gradient(135deg, #1f8a5b, #0f7f73)", color: "#fff", fontSize: 14, fontWeight: 700, cursor: "pointer", fontFamily: VAULT_FONT }}>
                            {svg(I.cloud, 17)} Upload File
                        </button>
                    </div>
                </div>

                {newFolder && (
                    <Card style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", padding: "12px 14px", borderColor: t.primary }}>
                        <label htmlFor="vault-folder" style={{ fontSize: 14, color: t.text }}>New folder</label>
                        <input id="vault-folder" placeholder="e.g. Property papers" style={fieldStyle(t, { flex: 1, width: "auto", minWidth: 180 })} />
                        <Btn kind="primary" onClick={() => { setNewFolder(false); notYet("Folders")(); }}>Create</Btn>
                        <Btn onClick={() => setNewFolder(false)}>Cancel</Btn>
                    </Card>
                )}

                {/* Search */}
                <div style={{ display: "flex", alignItems: "center", gap: 10, maxWidth: 1000, padding: "0 18px", minHeight: 50, borderRadius: 14, background: panel, border: `1px solid ${query ? t.primary : panelBorder}` }}>
                    <span style={{ color: t.textMuted, display: "flex" }}>{svg(I.search, 18)}</span>
                    <label htmlFor="vault-search" style={{ position: "absolute", left: -9999 }}>Search documents</label>
                    <input id="vault-search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search legal documents…"
                        style={{ flex: 1, minHeight: 44, background: "transparent", border: "none", color: t.text, fontSize: 14.5, outline: "none", fontFamily: VAULT_FONT }} />
                    {query && <button type="button" onClick={() => setQuery("")} aria-label="Clear search" style={{ background: "none", border: "none", color: t.textMuted, cursor: "pointer", fontSize: 20 }}>×</button>}
                </div>

                {/* Stats */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 18 }}>
                    {stats.map(([label, value, sub, icon]) => (
                        <div key={label} data-vault-stat={label} style={{ position: "relative", padding: "20px 22px", borderRadius: 16, background: panel, border: `1px solid ${panelBorder}` }}>
                            <span aria-hidden="true" style={{ position: "absolute", right: 22, top: 20, color: t.primary, opacity: 0.35 }}>{svg(icon, 26)}</span>
                            <div style={{ fontSize: 14.5, fontWeight: 500, color: t.textDim || t.text }}>{label}</div>
                            <div style={{ fontSize: 26, fontWeight: 700, color: t.text, margin: "10px 0 8px", lineHeight: 1 }}>{value}</div>
                            <div style={{ fontSize: 13, color: t.textMuted }}>{sub}</div>
                        </div>
                    ))}
                </div>

                {/* Table card */}
                <section style={{ display: "flex", flexDirection: "column", borderRadius: 18, background: t.mode === "dark" ? "#141d2c" : t.surface, border: `1px solid ${panelBorder}`, overflow: "visible", minHeight: 300 }}>
                    <div style={{ display: "flex", alignItems: "center", padding: "6px 24px 0", borderBottom: `1px solid ${panelBorder}` }}>
                        <div role="tablist" style={{ display: "flex", gap: 30 }}>
                            {[["all", "All Documents"], ["folders", "Folder"], ...(rrEnabled ? [["requests", "Review requests"]] : [])].map(([id, name]) => (
                                <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
                                    style={{ minHeight: 48, padding: 0, background: "transparent", border: "none", borderBottom: `3px solid ${tab === id ? "#1f8a5b" : "transparent"}`, color: tab === id ? "#1f8a5b" : t.text, fontSize: 15, fontWeight: 700, cursor: "pointer", fontFamily: VAULT_FONT }}>
                                    {name}
                                </button>
                            ))}
                        </div>
                        <span style={{ flex: 1 }} />
                        <div ref={sortRef} style={{ position: "relative" }}>
                            <button type="button" onClick={() => setSortOpen(o => !o)} aria-label="Sort documents" title="Sort documents"
                                aria-haspopup="menu" aria-expanded={sortOpen}
                                style={{ width: 36, height: 36, borderRadius: 9, border: "none", background: sortOpen ? t.inputBg : "transparent", color: t.text, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
                                {svg(I.filter, 19)}
                            </button>
                            {sortOpen && (
                                <div role="menu" aria-label="Sort documents"
                                    style={{ position: "absolute", right: 0, top: 40, zIndex: 5, width: "max-content", padding: 4, borderRadius: 10, background: t.card, border: `1px solid ${t.border}`, boxShadow: "0 8px 24px rgba(0,0,0,.35)" }}>
                                    {SORTS.map(([k, name]) => (
                                        <button key={k} type="button" role="menuitemradio" aria-checked={sort === k}
                                            onClick={() => { setSort(k); setSortOpen(false); }}
                                            style={{ display: "block", width: "100%", textAlign: "left", padding: "7px 12px", borderRadius: 7, border: "none", background: sort === k ? t.primaryGlow2 : "transparent", color: sort === k ? t.primary : t.text, fontSize: 13.5, fontWeight: sort === k ? 700 : 500, cursor: "pointer", fontFamily: VAULT_FONT, whiteSpace: "nowrap" }}>
                                            {name}
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>

                    {tab === "requests" && rrEnabled ? (
                        <ReviewRequestsPanel reloadSignal={rrReload}
                            focusId={linkFocus?.id || null} focusInvalid={Boolean(linkFocus?.invalid)} />
                    ) : tab === "folders" ? (
                        <div style={{ padding: 28, textAlign: "center", color: t.textMuted, fontSize: 13.5 }}>
                            Folders arrive with file uploads. Your generated documents are all under “All Documents”.
                        </div>
                    ) : docs.error ? (
                        <div role="alert" style={{ padding: 28, display: "flex", alignItems: "center", gap: 12, color: t.text, fontSize: 15 }}>
                            Could not load your documents. <Btn onClick={docs.reload}>Try again</Btn>
                        </div>
                    ) : !docs.loaded ? (
                        <div aria-busy="true" style={{ padding: 34, textAlign: "center", color: t.textMuted, fontSize: 15 }}>Loading your documents…</div>
                    ) : docs.isEmpty ? (
                        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, padding: 40, textAlign: "center" }}>
                            <div style={{ width: 64, height: 64, borderRadius: 18, background: t.primaryGlow2, color: t.primary, display: "flex", alignItems: "center", justifyContent: "center" }}>{svg(I.folder, 28)}</div>
                            <div style={{ fontSize: 22, fontWeight: 700, color: t.text }}>Your vault is empty</div>
                            <div style={{ fontSize: 15, color: t.textMuted, maxWidth: 440, lineHeight: 1.6 }}>Documents you generate appear here. Uploading your own papers is coming soon.</div>
                            <Btn kind="primary" onClick={onBack}>Draft a document</Btn>
                        </div>
                    ) : (
                        <div style={{ overflowX: "auto", padding: "4px 18px" }}>
                            <div style={{ minWidth: 880 }}>
                                <div style={{ display: "grid", gridTemplateColumns: GRID, gap: 12, alignItems: "center", padding: "14px 18px", borderBottom: `1px solid ${panelBorder}`, ...th }}>
                                    <span>Name</span><span>Type</span><span>Size</span><span>Access</span><span>Status</span><span>Last modified</span><span style={{ textAlign: "right" }}>Actions</span>
                                </div>
                                {rows.length === 0 && <div style={{ padding: 20, color: t.textMuted, fontSize: 14 }}>No document matches “{query}”.</div>}
                                {rows.map(row => {
                                    const a = rowActions(row);
                                    const status = documentStatusView(row);
                                    return (
                                        <div key={row.id} data-vault-row={row.id} style={{ display: "grid", gridTemplateColumns: GRID, gap: 12, alignItems: "center", padding: "11px 16px", borderBottom: `1px solid ${panelBorder}`, fontSize: 13.5, color: t.text }}>
                                            <span style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                                                <span style={{ width: 30, height: 36, borderRadius: 6, background: "#fdecec", color: "#b3261e", fontSize: 9, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>PDF</span>
                                                <span style={{ fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{row.title || "Untitled document"}</span>
                                                {row.version ? <span style={{ fontSize: 12, color: t.textMuted }}>v{row.version}</span> : null}
                                            </span>
                                            <span style={{ color: t.textMuted, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{row.template_type ? humanise(row.template_type) : "—"}</span>
                                            <span style={{ color: t.textMuted }}>—</span>
                                            <span><Pill tone={accessOf(row) === "With lawyer" ? "info" : "muted"}>{accessOf(row)}</Pill></span>
                                            <span><Pill tone={TONE[status.tone] || "muted"}>{status.label}</Pill></span>
                                            <span style={{ color: t.textMuted }}>{formatWhen(row.updated_at || row.created_at)}</span>
                                            <span style={{ display: "flex", justifyContent: "flex-end", gap: 2 }}>
                                                <IconBtn label={`Open ${row.title || "document"}`} onClick={() => open(row)} disabled={busyId === row.id} style={{ border: "none" }}>{Icon.eye}</IconBtn>
                                                <IconBtn label={a.canDownload ? `Download ${row.title || "document"}` : a.reason} onClick={() => a.canDownload && download(row)} disabled={!a.canDownload} style={{ border: "none", opacity: a.canDownload ? 1 : 0.4 }}>{Icon.download}</IconBtn>
                                                {rrEnabled && (
                                                    <IconBtn label={a.canDownload ? `Request lawyer review of ${row.title || "document"}` : a.reason}
                                                        data-request-review={row.id}
                                                        onClick={() => a.canDownload && setRequesting(row)} disabled={!a.canDownload}
                                                        style={{ border: "none", opacity: a.canDownload ? 1 : 0.4 }}>{svg(I.send, 17)}</IconBtn>
                                                )}
                                            </span>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                    {tab === "all" && docs.loaded && !docs.isEmpty && !docs.error && (
                        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 24px 14px", fontSize: 13, color: t.textMuted }}>
                            <span style={{ flex: 1 }}>Showing {rows.length} of {docs.items.length}{docs.hasMore ? "+" : ""} documents</span>
                            {docs.hasMore && <Btn onClick={docs.loadMore} disabled={docs.loading} style={{ minHeight: 34 }}>{docs.loading ? "Loading…" : "Load more"}</Btn>}
                        </div>
                    )}
                </section>
            </div>
            {requesting && (
                <ReviewRequestDialog row={requesting}
                    onClose={() => setRequesting(null)}
                    onOpenExisting={() => { setRequesting(null); setTab("requests"); }}
                    onDone={() => {
                        setRequesting(null);
                        toast.show("Sent to your lawyer.", "success", 3000);
                        setRrReload(n => n + 1);
                        setTab("requests");
                    }} />
            )}
        </div>
    );
}
