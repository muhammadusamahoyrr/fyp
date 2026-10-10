'use client';
/* Preview a lawyer Vault document (2026-10-09): the file, read-only, with its
 * name, type, folder and size, and Download. Same design as the client Vault's
 * preview, in the lawyer's own files.
 *
 * WHAT IS SHOWN IS THE REAL FILE: the exact revision the row names, fetched by
 * its id and hash, drawn by the browser's own PDF viewer. There is no "Open" --
 * a document saved to the Vault is a fixed, hashed copy, and the lawyer's
 * drafter edits drafts, not these. */
import React, { useEffect, useState } from "react";
import { previewRevisionV2 } from "@/lib/api.js";
import { rowActions } from "@/lib/useMyDocuments.js";
import { documentStatusView } from "@/lib/documentStatus.js";
import { humanise } from "@/lib/fieldReview.js";
import { useT } from "@/components/shared/ui/theme.js";
import { Pill } from "./ui.jsx";
import { Icon, I } from "./icons.jsx";

const TONE = { info: "info", ok: "low", warn: "medium", danger: "high", muted: "muted" };

export function formatSize(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return null;
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export default function VaultPreview({ row, folderName = null, onBack, onDownload }) {
    const t = useT();
    const [url, setUrl] = useState(null);
    const [size, setSize] = useState(null);
    const [issue, setIssue] = useState(null);
    const actions = rowActions(row);
    const status = documentStatusView(row);
    const isDraft = /^draft$/i.test(status.label || "");

    useEffect(() => {
        let live = true;
        let made = null;
        setUrl(null); setSize(null); setIssue(null);
        if (!actions.canDownload) { setIssue(actions.reason || "This document has no file yet."); return undefined; }
        previewRevisionV2(row.id, actions.revisionId, { expectedPdfSha256: actions.pdfSha256 }).then(async res => {
            if (!live) { if (res?.data?.url) URL.revokeObjectURL(res.data.url); return; }
            if (!res?.data?.url) {
                setIssue(res?.status === 409
                    ? "This document changed since the list was loaded. Go back and open it again."
                    : (res?.error?.message || "The file could not be loaded."));
                return;
            }
            made = res.data.url;
            setUrl(made);
            try {
                const blob = await (await fetch(made)).blob();
                if (live) setSize(blob.size);
            } catch { /* the size is a nicety; the preview stands without it */ }
        });
        return () => { live = false; if (made) URL.revokeObjectURL(made); };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [row.id, actions.revisionId, actions.pdfSha256]);

    useEffect(() => {
        const esc = e => { if (e.key === "Escape") onBack?.(); };
        document.addEventListener("keydown", esc);
        return () => document.removeEventListener("keydown", esc);
    }, [onBack]);

    const meta = [row.template_type ? humanise(row.template_type) : "Document", folderName ? `Folder: ${folderName}` : null,
        formatSize(size), "PDF", row.version ? `Version ${row.version}` : null].filter(Boolean);

    return (
        <section data-vault-preview aria-label={`Preview of ${row.title || "document"}`}
            style={{ display: "flex", flexDirection: "column", gap: 18, minHeight: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
                <button type="button" onClick={onBack} aria-label="Back to the Vault" title="Back to the Vault"
                    style={{ width: 40, height: 40, borderRadius: 10, border: "none", background: "transparent", color: t.textMuted, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <Icon d={I.chevronLeft} size={22} />
                </button>
                <span aria-hidden="true" style={{ width: 56, height: 56, flexShrink: 0, borderRadius: 14, display: "flex", alignItems: "center", justifyContent: "center", background: t.mode === "dark" ? "#3a1f24" : "#fdecec", color: "#e5484d" }}>
                    <Icon d={I.fileText} size={26} />
                </span>
                <div style={{ flex: 1, minWidth: 200 }}>
                    <h1 data-preview-title style={{ margin: 0, fontSize: 21, fontWeight: 700, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.title || "Untitled document"}</h1>
                    <div data-preview-meta style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 4, fontSize: 14, color: t.textMuted }}>
                        {meta.map((m, i) => <React.Fragment key={m}>{i > 0 && <span aria-hidden="true">·</span>}<span>{m}</span></React.Fragment>)}
                        {!isDraft && <Pill tone={TONE[status.tone] || "muted"}>{status.label}</Pill>}
                    </div>
                </div>
                <button type="button" data-preview-download onClick={() => onDownload?.(row)} disabled={!actions.canDownload} title={actions.canDownload ? undefined : actions.reason}
                    style={{ display: "inline-flex", alignItems: "center", gap: 9, minHeight: 46, padding: "0 22px", borderRadius: 12, border: "none", background: "linear-gradient(90deg, #1f8a5b, #127a70)", color: "#e8fff9", fontSize: 15.5, fontWeight: 700, cursor: actions.canDownload ? "pointer" : "not-allowed", opacity: actions.canDownload ? 1 : 0.5, boxShadow: "0 4px 14px rgba(15,127,115,.25)" }}>
                    <Icon d={I.download} size={18} />Download
                </button>
            </div>

            <div style={{ height: "max(520px, calc(100vh - 250px))", borderRadius: 18, overflow: "hidden", border: `1px solid ${t.border}`, background: "#2a2a2e", display: "flex", alignItems: "center", justifyContent: "center" }}>
                {url
                    ? <iframe data-preview-frame title={`${row.title || "Document"} (PDF)`} src={`${url}#view=FitH`} style={{ width: "100%", height: "100%", border: "none", display: "block" }} />
                    : <div role={issue ? "alert" : "status"} style={{ color: issue ? "#f2b84b" : "#b9c4c7", fontSize: 14, padding: 24, textAlign: "center" }}>{issue || "Loading the document…"}</div>}
            </div>
        </section>
    );
}
