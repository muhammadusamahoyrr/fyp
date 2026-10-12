'use client';
/* The client's Document Vault (2026-10-10): every document this client has
 * generated, organised into folders.
 *
 * THE LAWYER VAULT'S DESIGN AND CODE (lawyer/VaultPage.jsx), as the client's
 * OWN copy: the CSS verbatim in documents/vaultTheme.js, the screen below with
 * only what the client side needs on top -- sending a document to a lawyer for
 * review (the "Review requests" tab), editing in the drafting workspace, and a
 * preview opened from the address. Copies, not imports, so a change on either
 * side never reaches the other (tests/role_boundaries, tests/docs_isolation).
 *
 * WHAT IS REAL
 *   - the list: the client's OWN documents (GET /documents/v2/mine);
 *   - folders: create, rename, delete, file a document (services/document_folders.py,
 *     ownership-scoped, open to clients since 2026-10-10); deleting a folder never
 *     deletes a document -- they go back to "no folder";
 *   - delete with "Recently deleted" and restore;
 *   - preview and download of the exact revision a row names.
 * "Upload file" has no backend yet: shown disabled and labelled. */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
    myDocumentsV2, downloadDocumentFile, listDocumentFoldersV2, createDocumentFolderV2,
    renameDocumentFolderV2, deleteDocumentFolderV2, moveDocumentToFolderV2,
    listReviewRequests, getDocumentV2,
} from "@/lib/api.js";
import { linkOpenDocument, unlinkOpenDocument } from "@/lib/documentsNav.js";
import { useMyDocuments, rowActions, DOCUMENTS_UNAVAILABLE } from "@/lib/useMyDocuments.js";
import { documentStatusView } from "@/lib/documentStatus.js";
import { humanise } from "@/lib/fieldReview.js";
import { useIsMobile } from "@/lib/i18n.jsx";
import { useToast } from "@/components/shared/Toast.jsx";
import { ModalPortal } from "./ui.jsx";
import { CLIENT_VAULT_CSS } from "./vaultTheme.js";
import { tiltHandlers } from "./tilt.js";
import ReviewRequestDialog from "./ReviewRequestDialog.jsx";
import ReviewRequestsPanel from "./ReviewRequestsPanel.jsx";
import { DeleteDocumentDialog, RecentlyDeleted } from "./VaultTrash.jsx";
import VaultPreview from "./VaultPreview.jsx";

// Kept as an export of this screen for its client callers; defined, role-neutral,
// in features/documents so the lawyer Review Queue need not import this screen.
import { formatWhen } from "@/features/documents/formatWhen.js";
export { formatWhen };

// Status colours in the palette's own terms.
const STATUS_TONE = { info: "var(--teal-ink)", ok: "var(--brand-text)", warn: "var(--gold)", danger: "var(--danger)", muted: "var(--muted)" };

/* Is the review-request feature switched on? Asked once, by the cheapest real
 * call: every review-request route answers 404 `feature_disabled` while
 * DOCUMENT_REVIEW_REQUESTS is off, and then the Vault shows nothing of it.
 * Any other failure also hides it -- an action that cannot work is not shown. */
export function reviewRequestsAvailable(res) {
    return Boolean(res && !res.error && res.data);
}

/* Who can see a document right now, in the vault's words.
 *
 * "Private" was wrong once a lawyer had decided: the reviewer keeps read access
 * to the version they reviewed (documents_v2._readable_scoped). So a decided
 * document says a lawyer has seen it; only a never-shared one is private. */
const REVIEWED = new Set(["approved", "returned", "rejected", "needs_reapproval"]);
export function accessOf(row) {
    const status = row?.review_status;
    if (status === "submitted") return "With lawyer";
    return REVIEWED.has(status) ? "Lawyer reviewed" : "Private";
}

/* A preview opened from the address: the document's detail, as a list row. */
export function rowFromDetail(detail) {
    const rev = detail?.current_revision || null;
    return {
        id: detail.id, title: detail.title, template_type: detail.template_type,
        review_status: detail.review_status, version: detail.current_version || 0,
        revision_id: rev?.revision_id || null, pdf_sha256: rev?.pdf_sha256 || null,
        downloadable: Boolean(rev?.revision_id && rev?.pdf_sha256 && (rev.status ?? "generated") === "generated"),
        updated_at: detail.updated_at, created_at: detail.created_at, folder_id: detail.folder_id ?? null,
    };
}

const SORTS = [["newest", "Newest first"], ["oldest", "Oldest first"], ["name", "Name (A–Z)"]];
export function sortRows(rows, how) {
    const when = r => new Date(r.updated_at || r.created_at || 0).getTime() || 0;
    const copy = [...rows];
    if (how === "oldest") return copy.sort((a, b) => when(a) - when(b));
    if (how === "name") return copy.sort((a, b) => (a.title || "").localeCompare(b.title || ""));
    return copy.sort((a, b) => when(b) - when(a));
}
export function addedThisWeek(items, now = new Date()) {
    const since = now.getTime() - 7 * 86400000;
    return (items || []).filter(r => {
        const d = new Date(r.created_at || r.updated_at || 0).getTime();
        return !Number.isNaN(d) && d >= since && d <= now.getTime();
    }).length;
}

const svg = (d, s = 18) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>;
const G = {
    folder: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />,
    folderPlus: <><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M12 10.5v5M9.5 13h5" /></>,
    folderMove: <><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M10 13h6M13.5 10.5 16 13l-2.5 2.5" /></>,
    cloud: <><path d="M7 18a5 5 0 0 1-.6-9.96A6 6 0 0 1 18 9a4.5 4.5 0 0 1-.5 9" /><path d="M12 12v7M9 15l3-3 3 3" /></>,
    stack: <><path d="M12 3 3 8l9 5 9-5z" /><path d="m3 13 9 5 9-5" /></>,
    search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>,
    sort: <path d="M4 7h16M7 12h10M10 17h4" />,
    chev: <path d="m6 9 6 6 6-6" />,
    eye: <><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></>,
    down: <><path d="M12 4v11M7 10l5 5 5-5" /><path d="M5 20h14" /></>,
    trash: <><path d="M4 7h16M10 11v6M14 11v6" /><path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3" /></>,
    pencil: <><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></>,
    plus: <path d="M12 5v14M5 12h14" />,
    send: <><path d="M22 2L11 13" /><path d="M22 2l-7 20-4-9-9-4z" /></>,
};
const hidden = { position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" };

/* A dialog in the Vault's theme (it renders in a portal, so it carries the scope itself). */
function VaultDialog({ busy, onClose, labelledBy, children, ...rest }) {
    return (
        <ModalPortal>
            <div data-client-vault className="cv-backdrop"
                onMouseDown={e => { if (e.target === e.currentTarget && !busy) onClose(); }}>
                <div role="dialog" aria-modal="true" aria-labelledby={labelledBy} className="cv-dialog" {...rest}>{children}</div>
            </div>
        </ModalPortal>
    );
}

function FolderNameDialog({ title, initial = "", submitLabel, onSubmit, onClose }) {
    const [name, setName] = useState(initial);
    const [problem, setProblem] = useState(null);
    const [busy, setBusy] = useState(false);
    const submit = async e => {
        e.preventDefault();
        if (busy) return;
        setBusy(true);
        const issue = await onSubmit(name);
        setBusy(false);
        if (issue) setProblem(issue);
    };
    return (
        <VaultDialog busy={busy} onClose={onClose} labelledBy="lvf-title" data-folder-dialog>
            <form onSubmit={submit}>
                <h2 id="lvf-title">{title}</h2>
                <label className="f" htmlFor="lvf-name">Folder name</label>
                <input id="lvf-name" type="text" autoFocus value={name} maxLength={60}
                    onChange={e => { setName(e.target.value); setProblem(null); }} placeholder="e.g. Bail matters" />
                {problem && <div role="alert" data-folder-problem className="cv-problem">{problem}</div>}
                <div className="row">
                    <button type="button" className="cv-btn" onClick={onClose} disabled={busy}>Cancel</button>
                    <button type="submit" className="cv-cta" style={{ height: 42 }} disabled={busy || !name.trim()}>{busy ? "Saving…" : submitLabel}</button>
                </div>
            </form>
        </VaultDialog>
    );
}

function ConfirmFolderDelete({ folder, onConfirm, onClose }) {
    const [busy, setBusy] = useState(false);
    const [problem, setProblem] = useState(null);
    const go = async () => {
        if (busy) return;
        setBusy(true);
        const issue = await onConfirm();
        setBusy(false);
        if (issue) setProblem(issue);
    };
    const n = folder.document_count || 0;
    return (
        <VaultDialog busy={busy} onClose={onClose} labelledBy="lvfd-title" data-folder-delete-dialog>
            <h2 id="lvfd-title">Delete the folder “{folder.name}”?</h2>
            <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.6, color: "var(--muted)" }}>
                {n ? `Its ${n} document${n === 1 ? "" : "s"} stay${n === 1 ? "s" : ""} in your Vault, in no folder. ` : ""}
                No document is deleted.
            </p>
            {problem && <div role="alert" className="cv-problem">{problem}</div>}
            <div className="row">
                <button type="button" className="cv-btn" onClick={onClose} disabled={busy}>Keep it</button>
                <button type="button" className="cv-btn danger" onClick={go} disabled={busy}>{busy ? "Deleting…" : "Delete folder"}</button>
            </div>
        </VaultDialog>
    );
}

/* Move one document. "New folder…" (client, 2026-10-10) creates the folder and
 * files the document into it in one step, so a client with no folder yet is not
 * sent back out of the dialog to make one first. */
function MoveDialog({ row, folders, onMove, onCreate, onClose }) {
    const [choice, setChoice] = useState(row.folder_id || "");
    const [busy, setBusy] = useState(false);
    const [problem, setProblem] = useState(null);
    const [newName, setNewName] = useState(null);           // null: not making a folder
    const submit = async e => {
        e.preventDefault();
        if (busy) return;
        setBusy(true);
        let target = choice || null;
        if (newName !== null) {
            const made = await onCreate(newName);
            if (made.error) { setBusy(false); setProblem(made.error); return; }
            target = made.folder.id;
        }
        const issue = await onMove(target);
        setBusy(false);
        if (issue) setProblem(issue);
    };
    const making = newName !== null;
    return (
        <VaultDialog busy={busy} onClose={onClose} labelledBy="lvm-title" data-move-dialog>
            <form onSubmit={submit}>
                <h2 id="lvm-title">Move “{row.title || "Untitled document"}”</h2>
                <fieldset style={{ border: "none", margin: 0, padding: 0, display: "grid", gap: 8, maxHeight: 300, overflowY: "auto" }}>
                    <legend className="cv-sub" style={{ marginBottom: 8 }}>Choose a folder</legend>
                    {[{ id: "", name: "No folder" }, ...folders].map(f => (
                        <label key={f.id || "none"} className={`cv-opt${!making && choice === f.id ? " on" : ""}`}>
                            <input type="radio" name="lvm-folder" value={f.id} checked={!making && choice === f.id} onChange={() => { setChoice(f.id); setNewName(null); setProblem(null); }} style={{ accentColor: "#3EE0A1" }} />
                            <span style={{ display: "flex", color: f.id ? "var(--gold)" : "var(--faint)" }}>{svg(G.folder, 17)}</span>
                            {f.name}
                        </label>
                    ))}
                    {making ? (
                        <label className="cv-opt on" data-move-new-folder>
                            <span style={{ display: "flex", color: "var(--brand-text)" }}>{svg(G.folderPlus, 17)}</span>
                            <span style={hidden}>New folder name</span>
                            <input type="text" autoFocus value={newName} maxLength={60} placeholder="New folder name, e.g. Tenancy dispute"
                                onChange={e => { setNewName(e.target.value); setProblem(null); }}
                                style={{ flex: 1, height: 36, border: 0, background: "transparent", boxShadow: "none", padding: 0 }} />
                        </label>
                    ) : (
                        <button type="button" className="cv-opt" data-move-new-folder-start onClick={() => { setNewName(""); setProblem(null); }}
                            style={{ background: "transparent", color: "var(--brand-text)", fontWeight: 600, width: "100%", textAlign: "left" }}>
                            {svg(G.plus, 17)} New folder…
                        </button>
                    )}
                </fieldset>
                {problem && <div role="alert" className="cv-problem">{problem}</div>}
                <div className="row">
                    <button type="button" className="cv-btn" onClick={onClose} disabled={busy}>Cancel</button>
                    <button type="submit" className="cv-cta" style={{ height: 42 }}
                        disabled={busy || (making ? !newName.trim() : choice === (row.folder_id || ""))}>
                        {busy ? "Moving…" : making ? "Create & move" : "Move"}
                    </button>
                </div>
            </form>
        </VaultDialog>
    );
}

/* ADD DOCUMENTS TO A FOLDER (client, 2026-10-10). A matter has several papers
 * (a plaint, an affidavit, a notice): filing them one row at a time from "All
 * documents" took a dialog per document. This lists every one of the client's
 * documents not already in the folder -- with where each is now -- to pick
 * several at once. Filing only moves `folder_id` (PUT /documents/v2/{id}/folder):
 * nothing is copied or deleted, and a document is in one folder at a time.
 * Moves run one after another; any that fail are named and stay selected. */
const PICK_PAGES = 4;                  // up to 4 × 50 documents, the newest first
async function loadAllDocuments() {
    const out = [];
    let cursor = null;
    for (let i = 0; i < PICK_PAGES; i += 1) {
        const res = await myDocumentsV2({ cursor, limit: 50 });
        if (res?.error) return { error: res.error.message || "Could not load your documents." };
        out.push(...(res.data?.items || []));
        cursor = res.data?.has_more ? res.data.next_cursor : null;
        if (!cursor) return { items: out, more: false };
    }
    return { items: out, more: true };
}

function AddDocumentsDialog({ folder, folderName, fresh = false, onDone, onClose }) {
    const [list, setList] = useState(null);                 // null: loading
    const [more, setMore] = useState(false);
    const [problem, setProblem] = useState(null);
    const [q, setQ] = useState("");
    const [picked, setPicked] = useState(() => new Set());
    const [busy, setBusy] = useState(false);
    const [progress, setProgress] = useState(0);
    useEffect(() => {
        let live = true;
        loadAllDocuments().then(res => {
            if (!live) return;
            if (res.error) { setProblem(res.error); setList([]); return; }
            setList(res.items.filter(d => d.folder_id !== folder.id));
            setMore(res.more);
        });
        return () => { live = false; };
    }, [folder.id]);
    const shown = useMemo(() => {
        const s = q.trim().toLowerCase();
        return (list || []).filter(d => !s || (d.title || "").toLowerCase().includes(s)
            || (d.template_type || "").toLowerCase().includes(s) || (folderName[d.folder_id] || "").toLowerCase().includes(s));
    }, [list, q, folderName]);
    const allShown = shown.length > 0 && shown.every(d => picked.has(d.id));
    const toggle = id => setPicked(p => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
    const toggleAll = () => setPicked(p => {
        const n = new Set(p);
        shown.forEach(d => (allShown ? n.delete(d.id) : n.add(d.id)));
        return n;
    });
    const submit = async e => {
        e.preventDefault();
        if (busy || picked.size === 0) return;
        setBusy(true);
        setProblem(null);
        const ids = [...picked];
        const failed = [];
        for (let i = 0; i < ids.length; i += 1) {
            setProgress(i + 1);
            const res = await moveDocumentToFolderV2(ids[i], folder.id);
            if (res?.error) failed.push(ids[i]);
        }
        setBusy(false);
        const moved = ids.length - failed.length;
        if (failed.length) {
            // The ones that worked leave the list; the failures stay selected to retry.
            const title = id => (list.find(d => d.id === id)?.title || "Untitled document");
            setList(l => l.filter(d => !ids.includes(d.id) || failed.includes(d.id)));
            setPicked(new Set(failed));
            setProblem(`${failed.length} could not be added: ${failed.map(title).join(", ")}. Try again.`);
            if (moved) onDone(moved, false);
            return;
        }
        onDone(moved, true);
    };
    const n = picked.size;
    return (
        <VaultDialog busy={busy} onClose={onClose} labelledBy="cva-title" data-add-documents-dialog style={{ width: "min(560px, calc(100vw - 32px))" }}>
            <form onSubmit={submit}>
                <h2 id="cva-title" style={{ marginBottom: 6 }}>{fresh ? `“${folder.name}” is ready. Add documents?` : `Add documents to “${folder.name}”`}</h2>
                <p className="cv-sub" style={{ margin: "0 0 14px", fontSize: 13.5, lineHeight: 1.55 }}>
                    Pick the papers that belong to this matter. Each one moves here from where it is now — nothing is copied or deleted.
                </p>
                {list === null ? (
                    <div aria-busy="true" className="cv-empty" style={{ padding: 28 }}>Loading your documents…</div>
                ) : list.length === 0 && !problem ? (
                    <div className="cv-empty" style={{ padding: 28 }}>
                        <b>{fresh ? "No documents to add yet" : "Nothing left to add"}</b>
                        {fresh ? "Documents you draft appear in your Vault; file them here from there." : "Every one of your documents is already in this folder."}
                    </div>
                ) : (<>
                    <label className="cv-search" style={{ height: 42, marginBottom: 10, boxShadow: "none" }}>
                        {svg(G.search, 16)}
                        <span style={hidden}>Search your documents</span>
                        <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Search by name, type or folder" style={{ fontSize: 14 }} />
                    </label>
                    {shown.length > 0 && (
                        <label className="cv-opt" style={{ minHeight: 38, marginBottom: 8, borderStyle: "dashed" }}>
                            <input type="checkbox" checked={allShown} onChange={toggleAll} style={{ accentColor: "#3EE0A1" }} data-add-all />
                            <span style={{ fontWeight: 600 }}>{allShown ? "Clear the ones shown" : `Select all shown (${shown.length})`}</span>
                        </label>
                    )}
                    <div role="group" aria-label="Your documents" style={{ display: "grid", gap: 8, maxHeight: 300, overflowY: "auto", paddingRight: 2 }} data-lenis-prevent>
                        {shown.map(d => (
                            <label key={d.id} className={`cv-opt${picked.has(d.id) ? " on" : ""}`} data-add-doc={d.id} style={{ minHeight: 54 }}>
                                <input type="checkbox" checked={picked.has(d.id)} onChange={() => toggle(d.id)} style={{ accentColor: "#3EE0A1" }} />
                                <span className="cv-pdf" aria-hidden="true" style={{ width: 26, height: 32, fontSize: 8 }}>PDF</span>
                                <span style={{ minWidth: 0, flex: 1 }}>
                                    <span style={{ display: "block", fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{d.title || "Untitled document"}</span>
                                    <span className="cv-sub">
                                        {d.template_type ? humanise(d.template_type) : "Document"} · {folderName[d.folder_id] ? `now in “${folderName[d.folder_id]}”` : "no folder"}
                                    </span>
                                </span>
                            </label>
                        ))}
                        {shown.length === 0 && <div className="cv-sub" style={{ padding: 12 }}>No document matches “{q}”.</div>}
                    </div>
                    {more && <div className="cv-sub" style={{ marginTop: 8 }}>Showing your {list.length} newest documents.</div>}
                </>)}
                {problem && <div role="alert" className="cv-problem">{problem}</div>}
                <div className="row">
                    <button type="button" className="cv-btn" onClick={onClose} disabled={busy}>{fresh ? "Skip for now" : "Cancel"}</button>
                    <button type="submit" className="cv-cta" style={{ height: 42 }} disabled={busy || n === 0} data-add-submit>
                        {busy ? `Adding ${progress} of ${n}…` : n ? `Add ${n} document${n === 1 ? "" : "s"}` : "Add documents"}
                    </button>
                </div>
            </form>
        </VaultDialog>
    );
}

/* `onEdit(documentId)` opens a document for editing in the AI drafting
 * workspace -- the one place a document is edited. `previewId`, when given,
 * opens that document's preview at once (a refresh of an open preview).
 * `reviewLink` opens the Review requests tab from a notification. */
export default function DocsVault({ onBack, onEdit, reviewLink = null, previewId = null }) {
    const toast = useToast();
    const isMobile = useIsMobile();
    const [tab, setTab] = useState("all");
    const [query, setQuery] = useState("");
    const [sort, setSort] = useState(null);
    const searchRef = useRef(null);
    // The folder the list is narrowed to (null: every document).
    const [folder, setFolder] = useState(null);
    const [folders, setFolders] = useState([]);
    const [foldersError, setFoldersError] = useState(null);
    const [naming, setNaming] = useState(null);          // { mode: "create" } | { mode: "rename", folder }
    const [removingFolder, setRemovingFolder] = useState(null);
    const [moving, setMoving] = useState(null);
    const [deleting, setDeleting] = useState(null);
    const [trashReload, setTrashReload] = useState(0);
    const [viewing, setViewing] = useState(null);
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
    // A preview keeps its place in the address, so a refresh reopens it.
    const open = row => { setViewing(row); linkOpenDocument(row.id, { preview: true }); };
    const closePreview = () => { setViewing(null); unlinkOpenDocument(); };
    useEffect(() => {
        if (!previewId) return undefined;
        let live = true;
        getDocumentV2(previewId).then(({ data, error }) => {
            if (!live) return;
            if (error || !data?.id) { unlinkOpenDocument(); return; }
            setViewing(rowFromDetail(data));
        });
        return () => { live = false; };
    }, [previewId]);
    // The row whose Download was just pressed, for its burst (a new key replays it).
    const [hit, setHit] = useState(null);

    const loadFolders = useCallback(async () => {
        const res = await listDocumentFoldersV2();
        if (res?.error) { setFoldersError(res.error.message || "Could not load your folders."); return; }
        setFoldersError(null);
        setFolders(res.data?.items || []);
    }, []);
    useEffect(() => { loadFolders(); }, [loadFolders]);

    const folderRef = useRef(folder);
    folderRef.current = folder;
    const fetchPage = useCallback(({ cursor, limit }) => myDocumentsV2({ cursor, limit, folder: folderRef.current?.id || null }), []);
    const docs = useMyDocuments({ fetchPage, pageSize: 25 });
    const firstFolderRun = useRef(true);
    useEffect(() => {
        if (firstFolderRun.current) { firstFolderRun.current = false; return; }
        docs.reload();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [folder?.id]);

    // "/" jumps to the search, as the hint in it says (not while typing elsewhere).
    useEffect(() => {
        const onKey = e => {
            if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
            const el = e.target;
            if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
            e.preventDefault();
            searchRef.current?.focus();
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, []);

    const folderName = useMemo(() => Object.fromEntries(folders.map(f => [f.id, f.name])), [folders]);
    const rows = useMemo(() => {
        const q = query.trim().toLowerCase();
        const hits = docs.items.filter(r => !q || (r.title || "").toLowerCase().includes(q)
            || (r.template_type || "").toLowerCase().includes(q)
            || (folderName[r.folder_id] || "").toLowerCase().includes(q));
        return sort ? sortRows(hits, sort) : hits;
    }, [docs.items, query, sort, folderName]);
    const week = addedThisWeek(docs.items);

    const download = async row => {
        const a = rowActions(row);
        const res = await downloadDocumentFile(row.id, `${row.title || "document"}.pdf`,
            { revisionId: a.revisionId, expectedPdfSha256: a.pdfSha256 });
        if (res?.error) toast.show(`Download failed: ${res.error}`, "danger", 4000);
    };
    const openFolder = f => { setFolder(f); setTab("all"); };

    // A new folder opens at once, with the picker to fill it: a folder is made
    // to hold a matter's papers, so that is the next step, not a hunt for rows.
    const createFolder = async name => {
        const res = await createDocumentFolderV2(name);
        if (res?.error) return res.error.message || "Could not create the folder.";
        setNaming(null);
        await loadFolders();
        openFolder(res.data);
        setAdding({ folder: res.data, fresh: true });
        return null;
    };
    // "New folder…" inside the Move dialog: make it, then the dialog files into it.
    const createForMove = async name => {
        const res = await createDocumentFolderV2(name);
        if (res?.error) return { error: res.error.message || "Could not create the folder." };
        justMade.current[res.data.id] = res.data.name;      // named in the toast before the list re-reads
        setFolders(fs => [...fs, res.data]);
        return { folder: res.data };
    };
    const [adding, setAdding] = useState(null);             // { folder, fresh } while the picker is open
    const justMade = useRef({});
    const added = (folderFor, n, close) => {
        toast.show(`Added ${n} document${n === 1 ? "" : "s"} to “${folderFor.name}”.`, "success", 3000);
        if (close) setAdding(null);
        docs.reload();
        loadFolders();
    };
    const renameFolder = async (f, name) => {
        const res = await renameDocumentFolderV2(f.id, name);
        if (res?.error) return res.error.message || "Could not rename the folder.";
        setNaming(null);
        if (folder?.id === f.id) setFolder({ ...folder, name: res.data.name });
        await loadFolders();
        return null;
    };
    const deleteFolder = async f => {
        const res = await deleteDocumentFolderV2(f.id);
        if (res?.error) return res.error.message || "Could not delete the folder.";
        setRemovingFolder(null);
        if (folder?.id === f.id) setFolder(null); else docs.reload();
        toast.show(`Folder “${f.name}” deleted. Its documents are still in your Vault.`, "success", 3500);
        await loadFolders();
        return null;
    };
    const moveRow = async (row, folderId) => {
        const res = await moveDocumentToFolderV2(row.id, folderId);
        if (res?.error) return res.error.message || "Could not move the document.";
        setMoving(null);
        toast.show(folderId ? `Moved to “${folderName[folderId] || justMade.current[folderId] || "the folder"}”.` : "Moved out of its folder.", "success", 2500);
        docs.reload();
        await loadFolders();
        return null;
    };

    const stats = [
        ["Total Documents", String(docs.items.length) + (docs.hasMore ? "+" : ""), !docs.loaded ? "Loading…" : folder ? `in “${folder.name}”` : `+${week} this week`, G.stack, "var(--brand-text)"],
        ["Folders Created", String(folders.length), "to organize by matter or client", G.folder, "var(--gold)"],
        ["Storage Used", "—", "tracked once uploads are connected", G.cloud, "var(--teal-ink)"],
    ];
    const tabs = [["all", "All documents", folder ? null : docs.items.length + (docs.hasMore ? "+" : "")], ["folders", "Folders", folders.length],
        ...(rrEnabled ? [["requests", "Review requests", null]] : []), ["trash", "Recently deleted", null]];

    return (
        <div data-client-vault className="cv-page" data-lenis-prevent>
            <style>{CLIENT_VAULT_CSS}</style>
            <div className="cv-wrap" style={isMobile ? { paddingTop: 60 } : undefined}>
                {viewing ? (
                    <VaultPreview row={viewing} onBack={closePreview} onEdit={onEdit} onDownload={download} />
                ) : (<>
                <nav className="cv-crumbs" aria-label="Breadcrumb">
                    <button type="button" onClick={onBack}>Documents</button> <span aria-hidden="true">/</span>{" "}
                    {folder
                        ? <><button type="button" onClick={() => setFolder(null)}>Vault</button> <span aria-hidden="true">/</span> <b>{folder.name}</b></>
                        : <b>Vault</b>}
                </nav>

                <div className="cv-head">
                    <div>
                        <h1>Document <span className="cv-accent">vault</span></h1>
                        <p>Keep the documents you draft in one place, and organize them into folders by matter, court or client.</p>
                    </div>
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                        {/* No upload backend yet: shown disabled and labelled, never as a working action. */}
                        <button type="button" className="cv-btn" disabled data-vault-soon="Upload File" title="Uploading files isn't connected yet — coming soon." style={{ height: 48 }}>
                            {svg(G.cloud, 18)} Upload File <span className="cv-soon">Soon</span>
                        </button>
                        <button type="button" className="cv-cta k3d" data-create-folder onClick={() => setNaming({ mode: "create" })}>
                            {svg(G.folderPlus, 19)} Create Folder
                        </button>
                    </div>
                </div>

                <div className="cv-stats">
                    {stats.map(([label, value, sub, icon, colour]) => (
                        <div key={label} className="cv-stat d3" {...tiltHandlers()} data-vault-stat={label} style={{ "--c": colour }}>
                            <span className="cv-ic">{svg(icon, 19)}</span>
                            <span className="l">{label}</span>
                            <span className="v">{value}</span>
                            <span className="s">{sub}</span>
                        </div>
                    ))}
                </div>

                <div className="cv-tools">
                    <label className="cv-search">
                        {svg(G.search, 18)}
                        <span style={hidden}>Search documents</span>
                        <input id="vault-search" ref={searchRef} value={query} onChange={e => setQuery(e.target.value)} placeholder="Search your documents and folders" />
                        {query
                            ? <button type="button" onClick={() => setQuery("")} aria-label="Clear search" style={{ background: "none", border: 0, color: "var(--muted)", cursor: "pointer", fontSize: 20, lineHeight: 1 }}>×</button>
                            : <span className="cv-kbd" aria-hidden="true">/</span>}
                    </label>
                    <label className="cv-sort">
                        {svg(G.sort, 17)}
                        <span style={hidden}>Sort documents</span>
                        <select value={sort || ""} onChange={e => setSort(e.target.value || null)} data-vault-sort>
                            <option value="">Newest saved first</option>
                            {SORTS.filter(([k]) => k !== "newest").map(([k, name]) => <option key={k} value={k}>{name}</option>)}
                        </select>
                        <svg className="chev" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">{G.chev}</svg>
                    </label>
                </div>

                <section className="cv-card">
                    <div className="cv-bar">
                        <div role="tablist" aria-label="Vault" className="cv-tabs">
                            {tabs.map(([id, name, n]) => (
                                <button key={id} type="button" role="tab" className="cv-tab" aria-selected={tab === id} onClick={() => setTab(id)}>
                                    {name}{n !== null && n !== undefined && <span className="cv-n">{n}</span>}
                                </button>
                            ))}
                        </div>
                        {tab === "all" && folder && (
                            <div data-folder-filter className="cv-filter">
                                <span style={{ color: "var(--gold)", display: "flex" }}>{svg(G.folder, 16)}</span>
                                Showing the folder <b>{folder.name}</b>
                                <button type="button" className="cv-cta" style={{ height: 32, padding: "0 12px", fontSize: 13, borderRadius: 10 }} data-add-documents
                                    onClick={() => setAdding({ folder, fresh: false })}>{svg(G.plus, 15)} Add documents</button>
                                <button type="button" className="cv-btn" style={{ height: 32, fontSize: 13 }} onClick={() => setFolder(null)}>Show all</button>
                            </div>
                        )}
                    </div>

                    {tab === "trash" ? (
                        <RecentlyDeleted reloadSignal={trashReload}
                            onRestored={item => { toast.show(`“${item.title || "Document"}” is back in your Vault.`, "success", 3000); docs.reload(); loadFolders(); }} />
                    ) : tab === "requests" && rrEnabled ? (
                        <ReviewRequestsPanel reloadSignal={rrReload}
                            focusId={linkFocus?.id || null} focusInvalid={Boolean(linkFocus?.invalid)} />
                    ) : tab === "folders" ? (
                        foldersError ? (
                            <div role="alert" className="cv-empty">{foldersError} <button type="button" className="cv-btn" onClick={loadFolders}>Try again</button></div>
                        ) : (
                            <div data-folder-grid className="cv-folders">
                                {folders.map(f => (
                                    <div key={f.id} data-folder={f.id} className="cv-folder d3" {...tiltHandlers()} style={{ "--c": "var(--gold)" }}>
                                        <button type="button" className="open" onClick={() => openFolder(f)} aria-label={`Open folder ${f.name}`}>
                                            <span className="cv-f3d" aria-hidden="true"><i className="bk" /><i className="pg b" /><i className="pg" /><i className="fr" /></span>
                                            <span style={{ minWidth: 0 }}>
                                                <span className="nm">{f.name}</span>
                                                <span className="cv-sub">{f.document_count} document{f.document_count === 1 ? "" : "s"}</span>
                                            </span>
                                        </button>
                                        <div className="cv-acts">
                                            <button type="button" className="cv-ib k-move" aria-label={`Add documents to ${f.name}`} title="Add documents" data-add-to-folder={f.id} onClick={() => setAdding({ folder: f, fresh: false })}>{svg(G.plus, 16)}</button>
                                            <button type="button" className="cv-ib k-pen" aria-label={`Rename folder ${f.name}`} title="Rename" data-rename-folder={f.id} onClick={() => setNaming({ mode: "rename", folder: f })}>{svg(G.pencil, 16)}</button>
                                            <button type="button" className="cv-ib danger k-trash" aria-label={`Delete folder ${f.name}`} title="Delete folder" data-delete-folder={f.id} onClick={() => setRemovingFolder(f)}>{svg(G.trash, 16)}</button>
                                        </div>
                                    </div>
                                ))}
                                <button type="button" className="cv-new" onClick={() => setNaming({ mode: "create" })}>
                                    <span>{svg(G.plus, 18)}</span> New folder
                                </button>
                                {folders.length === 0 && (
                                    <div style={{ gridColumn: "1 / -1", color: "var(--muted)", fontSize: 13.5 }}>No folders yet. Make one for each matter — a case, a property, a court — and add its documents in one go.</div>
                                )}
                            </div>
                        )
                    ) : docs.error ? (
                        <div role="alert" className="cv-empty">{docs.unavailable ? DOCUMENTS_UNAVAILABLE : <>Could not load your documents. <button type="button" className="cv-btn" onClick={docs.reload}>Try again</button></>}</div>
                    ) : !docs.loaded ? (
                        <div aria-busy="true" className="cv-empty">Loading your documents…</div>
                    ) : docs.isEmpty ? (
                        <div className="cv-empty">
                            <span className="cv-ic" style={{ "--c": "var(--brand-text)", width: 56, height: 56, margin: "0 auto", borderRadius: 16 }}>{svg(G.folder, 26)}</span>
                            <b>{folder ? `“${folder.name}” is empty` : "Your vault is empty"}</b>
                            {folder ? "Add the documents that belong to this matter. They move here; nothing is copied." : "Documents you generate appear here. Uploading your own papers is coming soon."}
                            {folder && (
                                <div style={{ marginTop: 14, display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
                                    <button type="button" className="cv-cta" style={{ height: 42 }} data-add-documents-empty onClick={() => setAdding({ folder, fresh: false })}>{svg(G.plus, 17)} Add documents</button>
                                    <button type="button" className="cv-btn" onClick={() => setFolder(null)}>Show all documents</button>
                                </div>
                            )}
                        </div>
                    ) : (
                        <div>
                            <div className="cv-grid cv-th">
                                <span>Document</span><span>Type</span><span>Folder</span><span>Status</span><span>Last modified</span><span>Actions</span>
                            </div>
                            {rows.length === 0 && <div className="cv-empty">No document matches “{query}”.</div>}
                            {rows.map(row => {
                                const a = rowActions(row);
                                const status = documentStatusView(row);
                                const tone = STATUS_TONE[status.tone] || STATUS_TONE.muted;
                                const inFolder = folderName[row.folder_id];
                                const title = row.title || "document";
                                return (
                                    <div key={row.id} data-vault-row={row.id} className="cv-grid cv-row">
                                        <span style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                                            <span className="cv-pdf" aria-hidden="true">PDF</span>
                                            <span style={{ minWidth: 0 }}>
                                                <span className="cv-name" style={{ display: "block" }}>{row.title || "Untitled document"}</span>
                                                {/* Who can see it (accessOf): said only once a lawyer is involved. */}
                                                {(row.version || accessOf(row) !== "Private") ? (
                                                    <span className="cv-sub" title={accessOf(row) === "Lawyer reviewed" ? "The lawyer who reviewed it can still read the version they reviewed." : undefined}>
                                                        {[row.version ? `Version ${row.version}` : null, accessOf(row) !== "Private" ? accessOf(row) : null].filter(Boolean).join(" · ")}
                                                    </span>
                                                ) : null}
                                            </span>
                                        </span>
                                        <span className="cv-sub" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{row.template_type ? humanise(row.template_type) : "—"}</span>
                                        <span style={{ minWidth: 0 }}>
                                            {inFolder ? <span className="cv-chip">{svg(G.folder, 13)}{inFolder}</span> : <span className="cv-sub">No folder</span>}
                                        </span>
                                        <span><span className="cv-pill" style={{ color: tone, background: `color-mix(in srgb, ${tone} 14%, transparent)` }}><i />{status.label}</span></span>
                                        <span className="cv-sub">{formatWhen(row.updated_at || row.created_at)}</span>
                                        <span className="cv-acts">
                                            <button type="button" className="cv-ib k-eye" aria-label={`Preview ${title}`} title="Preview" onClick={() => open(row)}>{svg(G.eye, 17)}</button>
                                            <button type="button" className={`cv-ib k-down${hit?.id === row.id ? " hit" : ""}`} aria-label={a.canDownload ? `Download ${title}` : a.reason} title={a.canDownload ? "Download" : a.reason}
                                                onClick={() => { if (!a.canDownload) return; setHit({ id: row.id, n: (hit?.n || 0) + 1 }); download(row); }} disabled={!a.canDownload}>
                                                <span key={hit?.id === row.id ? hit.n : 0} style={{ display: "grid" }}>{svg(G.down, 17)}</span>
                                                {hit?.id === row.id && <span key={`b${hit.n}`} className="cv-burst" aria-hidden="true">{[0, 45, 90, 135, 180, 225, 270, 315].map(d => <i key={d} style={{ "--a": `${d}deg` }} />)}</span>}
                                            </button>
                                            {rrEnabled && (
                                                <button type="button" className="cv-ib k-move" aria-label={a.canDownload ? `Request lawyer review of ${title}` : a.reason}
                                                    title={a.canDownload ? "Send to your lawyer for review" : a.reason} data-request-review={row.id}
                                                    onClick={() => a.canDownload && setRequesting(row)} disabled={!a.canDownload}>{svg(G.send, 17)}</button>
                                            )}
                                            <button type="button" className="cv-ib k-move" aria-label={`Move ${title} to a folder`} title="Move to a folder" data-move-document={row.id} onClick={() => setMoving(row)}>{svg(G.folderMove, 17)}</button>
                                            <button type="button" className="cv-ib danger k-trash" aria-label={`Delete ${title}`} title="Delete" data-delete-document={row.id} onClick={() => setDeleting(row)}>{svg(G.trash, 17)}</button>
                                        </span>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                    {tab === "all" && docs.loaded && !docs.isEmpty && !docs.error && (
                        <div className="cv-foot">
                            <span style={{ flex: 1 }}>Showing {rows.length} of {docs.items.length}{docs.hasMore ? "+" : ""} documents</span>
                            {docs.hasMore && <button type="button" className="cv-btn" onClick={docs.loadMore} disabled={docs.loading} style={{ height: 34 }}>{docs.loading ? "Loading…" : "Load more"}</button>}
                        </div>
                    )}
                </section>
                </>)}
            </div>

            {naming?.mode === "create" && (
                <FolderNameDialog title="Create a folder" submitLabel="Create" onSubmit={createFolder} onClose={() => setNaming(null)} />
            )}
            {naming?.mode === "rename" && (
                <FolderNameDialog title="Rename the folder" initial={naming.folder.name} submitLabel="Rename"
                    onSubmit={name => renameFolder(naming.folder, name)} onClose={() => setNaming(null)} />
            )}
            {removingFolder && (
                <ConfirmFolderDelete folder={removingFolder} onConfirm={() => deleteFolder(removingFolder)} onClose={() => setRemovingFolder(null)} />
            )}
            {moving && <MoveDialog row={moving} folders={folders} onMove={id => moveRow(moving, id)} onCreate={createForMove} onClose={() => setMoving(null)} />}
            {adding && (
                <AddDocumentsDialog folder={adding.folder} fresh={adding.fresh} folderName={folderName}
                    onDone={(n, close) => added(adding.folder, n, close)} onClose={() => setAdding(null)} />
            )}
            {deleting && (
                <DeleteDocumentDialog row={deleting} onClose={() => setDeleting(null)}
                    onDeleted={() => {
                        setDeleting(null);
                        toast.show("Moved to Recently deleted. You can restore it from there.", "success", 3500);
                        docs.reload();
                        loadFolders();
                        setTrashReload(n => n + 1);
                        setRrReload(n => n + 1);
                    }} />
            )}
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
