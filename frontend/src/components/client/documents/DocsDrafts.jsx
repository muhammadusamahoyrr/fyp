'use client';
/* Client AI drafting: prompt -> reviewed plan -> immutable V2 workspace.
 *
 * The client drafting layout has a recent-documents column, a real PDF (or
 * pre-generation outline) in the centre, and an always-visible completion
 * panel for the current detail and the remaining ones.
 *
 * BEHAVIOUR is the real backend, unchanged: no sample legal instrument is
 * rendered here. Every preview, editable field and check comes from the
 * server for the user's own document.
 *   Placeholders      the workspace's structured fields; an empty one is unfilled
 *   Fill Placeholders edits them; "Save as new revision" regenerates the same
 *                     template as a new immutable revision (stale-revision
 *                     checked, idempotent)
 *   Choices I made    the plan's AI-extracted details, each changeable before
 *                     anything is generated
 *   Checks            the revision's own particulars and citation results
 *   Ask for changes   AI Assist: a PROPOSAL, applied locally, saved only on save
 *   PDF / Send to     the real download and the accepted-engagement review flow
 *   Versions / Saved  the left column's two tabs: this document's real
 *                     revisions, and the client's saved documents
 * Controls with no backend (risk score, Copy, analysis) are not shown. DOCX is
 * shown DISABLED and labelled "Soon" -- never as a working export. */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import RevisionHistory from "@/components/shared/RevisionHistory.jsx";
import { useT } from "../theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import { humanise } from "@/lib/fieldReview.js";
import { complianceSummary } from "@/lib/complianceSummary.js";
import { verificationView } from "@/lib/draftVerification.js";
import { documentStatusView } from "@/lib/documentStatus.js";
import { useMyDocuments, rowActions, DOCUMENTS_UNAVAILABLE } from "@/lib/useMyDocuments.js";
import { DeleteDocumentDialog } from "./VaultTrash.jsx";
import { useIsMobile } from "@/lib/i18n.jsx";
import { PromptCard } from "../DocumentsHome.jsx";
import { linkOpenDocument, unlinkOpenDocument } from "@/lib/documentsNav.js";
import {
    answerDraftPlanV2, assistDocumentWorkspaceV2, confirmDraftPlanV2,
    createDraftPlanV2, downloadDocumentFile, generateDraftPlanV2,
    getDocumentV2, getDocumentWorkspaceV2, getDraftPlanV2, idempotencyKey,
    myDocumentsV2, previewDocumentTextV2, previewRevisionV2, saveDocumentWorkspaceV2,
    listEngagements, submitDocumentV2, withdrawDocumentV2, errorCode, isRetryable,
    listQuickReviewers, requestQuickReview, myQuickReviews, cancelQuickReview,
} from "@/lib/api.js";
import { Btn, Icon, Paper, SEVERITY, TOKEN_STYLE, VALUE_STYLE, fieldStyle, onPrimary, splitLayout, SERIF, DOCS_FONT } from "./ui.jsx";
import { LIcon } from "./icons.jsx";
import PdfDocumentView from "./PdfDocumentView.jsx";

export function placeholderCounts(values = {}, applied = {}, keys = Object.keys(values)) {
    const filled = keys.filter(k => String(values[k] ?? "").trim()).length;
    const done = keys.filter(k => applied[k]).length;
    return { total: keys.length, filled, applied: done, remaining: keys.length - done };
}

/* The editable placeholders of a structured workspace: its plain-text fields.
 * A nested value is a calculation, changed in its own calculator. */
export function placeholderFields(fields = {}) {
    return Object.entries(fields || {}).filter(([, v]) => v === null || typeof v !== "object").map(([k]) => k);
}

const messageOf = (error, fallback) => error?.message || fallback;

/* Where an in-progress plan survives a reload.
 *
 * The plan id and the generation retry key live only in this tab's
 * sessionStorage. The key is minted HERE and never comes from the server; a
 * reload used to lose it, leaving the plan stranded in `generating`. With it
 * kept, the same key resumes the same attempt. (If storage is unavailable the
 * server's generation lease still frees the plan after a few minutes.) */
const PLAN_KEY = "attorney.draftPlan.current";
const GEN_KEY_PREFIX = "attorney.draftPlan.genKey.";
export const planStore = {
    get(name) { try { return window.sessionStorage.getItem(name); } catch { return null; } },
    set(name, value) { try { window.sessionStorage.setItem(name, value); } catch { /* storage blocked */ } },
    drop(name) { try { window.sessionStorage.removeItem(name); } catch { /* storage blocked */ } },
};

/* The only types the prompt planner accepts: the catalogue's AI-assisted
 * templates, which the server derives from the same extractor registry. */
export function promptTemplateOptions(templates) {
    return (templates || []).filter(s => s.drafting_mode === "ai");
}

const NOTE_WORDS = { joined: "combined from a list", dropped: "left out (not plain text)", truncated: "shortened" };
const STATUS_TONE = { info: "info", ok: "low", warn: "medium", danger: "high", muted: "muted" };
/* "just now", "2 hours ago", "1 day ago", then a date — for the Recent list. */
export function editedLabel(value, now = Date.now()) {
    const date = value ? new Date(value) : null;
    if (!date || Number.isNaN(date.getTime())) return "—";
    const mins = Math.floor((now - date.getTime()) / 60000);
    if (mins < 2) return "just now";
    if (mins < 60) return `${mins} minutes ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
    const days = Math.floor(hours / 24);
    if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;
    return date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}
const tokenOf = name => `[[${String(name).toUpperCase()}]]`;

/* The real checks of one revision, and the toolbar badge for them.
 *
 * The badge never counts a check that did not run as a failure: "Not checked"
 * and "No citations found to check" are neutral. So it shows the number of
 * issues if there are any, otherwise passed/ran over the checks that ran, and
 * "—" when none ran (a fresh revision showed an alarming amber "0/2"). */
export function revisionChecks(revision) {
    const particulars = complianceSummary(revision?.compliance);
    const citations = verificationView(revision?.verification) || { headline: "Not checked", detail: "", tone: "neutral" };
    const rows = [
        { label: "Required particulars", value: particulars.label, tone: particulars.tone, detail: "" },
        { label: "Citation check", value: citations.headline, tone: citations.tone, detail: citations.detail },
    ];
    const passed = rows.filter(r => ["success", "ok"].includes(r.tone)).length;
    const issues = rows.filter(r => ["warn", "danger"].includes(r.tone)).length;
    const ran = passed + issues;
    const badge = issues ? { text: `${issues} issue${issues === 1 ? "" : "s"}`, tone: "medium" }
        : ran ? { text: `${passed}/${ran}`, tone: "low" }
        : { text: "—", tone: "neutral", title: "No check has run on this revision" };
    return { rows, passed, issues, ran, total: rows.length, badge };
}

const toneColour = (t, tone) => (["success", "ok"].includes(tone) ? t.success : tone === "warn" ? t.warn : tone === "danger" ? t.danger : t.textMuted);

/* The editor of a free-text (lawyer) draft, with the formatting bar shown
 * only while editing -- after the approved screenshot, but lighter: grouped
 * line icons, one paragraph-style menu, and Save beside them.
 *
 * Uncontrolled on purpose: the HTML is written into the editable area only
 * when it differs from what is already there, so typing never resets the
 * caret (re-setting innerHTML on every keystroke jumped it to the start). */
/* `[[FIELD_NAME]]` -- a detail the text still needs. */
const PLACEHOLDER_RE = /\[\[([A-Z0-9_]+)\]\]/g;
export function placeholderTokens(html) {
    return [...new Set([...String(html || "").matchAll(PLACEHOLDER_RE)].map(m => m[1]))];
}
const escapeText = value => String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
/* Every `[[NAME]]` in the text replaced by a value, as text (never markup). */
export function fillPlaceholder(html, name, value) {
    return String(html || "").split(`[[${name}]]`).join(escapeText(value));
}
// While reading, a placeholder is marked so it stands out and can be clicked.
// Only while reading: the editor's own HTML never carries the marks.
const markPlaceholders = html => String(html || "").replace(PLACEHOLDER_RE, '<mark data-ph="$1">[[$1]]</mark>');
// The drafting screens' typeface (2026-10-08): Figtree, a light geometric
// sans, for the whole workspace and the document page. Scoped to these
// screens only; the rest of the app keeps its own fonts.
const DRAFTS_FONT = DOCS_FONT;   // the module's typeface (ui.jsx); was Figtree
// `data-keep-font` opts an element out: the start screen's serif headings and
// its monospace law references are part of that design.
// The history column (2026-10-10) is the lawyer AI sidebar's design and keeps
// its type (Hanken Grotesk, SIDE_ROW_CSS), so it is left out of this rule.
const DRAFTS_FONT_CSS = `[data-drafts-font], [data-drafts-font] *:not([data-keep-font]):not([data-drafts-side]):not([data-drafts-side] *) { font-family: ${DRAFTS_FONT} !important; }`;
const draftsFont = <style>{DRAFTS_FONT_CSS}</style>;

// The page's own typography: a document, not a web page.
const PAGE_CSS = `[data-rte] h1{font-size:1.2em;letter-spacing:.06em;margin:0 0 16px}
[data-rte] h2{font-size:1em;margin:18px 0 6px}
[data-rte] p{margin:0 0 10px}
[data-rte] hr{border:0;border-top:1px solid #d9dfe0;margin:14px 0}
[data-rte] table{border-collapse:collapse;width:100%;margin:8px 0 14px}
[data-rte] td,[data-rte] th{border:1px solid #d9dfe0;padding:6px 8px;vertical-align:top}
[data-rte] mark[data-ph]{background:#fdf0cf;color:#7a5200;border:1px solid #e9c46a;border-radius:4px;padding:0 4px;font:600 .78em 'Inter',sans-serif;cursor:pointer}`;

function RichTextEditor({ t, html, onChange, disabled, editing = false, saving = false, onSave = null, onDone = null, onPlaceholder = null }) {
    const ref = useRef(null);
    const shown = disabled ? markPlaceholders(html) : (html || "");
    useEffect(() => {
        if (ref.current && ref.current.innerHTML !== shown) ref.current.innerHTML = shown;
    }, [shown]);
    const run = (name, value = null) => {
        ref.current?.focus();
        if (document.execCommand) document.execCommand(name, false, value);
        if (ref.current) onChange(ref.current.innerHTML);
    };
    const btn = { width: 34, height: 34, display: "inline-flex", alignItems: "center", justifyContent: "center", border: "none", borderRadius: 8, background: "transparent", color: t.text, cursor: "pointer" };
    const sep = <span aria-hidden="true" style={{ width: 1, height: 22, background: t.border, margin: "0 4px" }} />;
    const groups = [
        [["undo", "undo", "Undo"], ["redo", "redo", "Redo"]],
        [["bold", "bold", "Bold"], ["italic", "italic", "Italic"], ["underline", "underline", "Underline"], ["strikeThrough", "strike", "Strikethrough"]],
        [["justifyLeft", "alignLeft", "Align left"], ["justifyCenter", "alignCenter", "Centre"], ["justifyRight", "alignRight", "Align right"], ["justifyFull", "alignJustify", "Justify"]],
        [["insertUnorderedList", "list", "Bulleted list"], ["insertOrderedList", "listOrdered", "Numbered list"], ["formatBlock:<blockquote>", "quote", "Quote"], ["insertHorizontalRule", "minus", "Divider"]],
    ];
    return <section aria-label="Rich text document editor" style={{ width: "min(900px,100%)", border: 0, alignSelf: "center" }}>
        {editing && (
            <div role="toolbar" aria-label="Text formatting" style={{ position: "sticky", top: 0, zIndex: 1, display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap", padding: "8px 10px", marginBottom: 10, borderRadius: 10, background: t.card, color: t.text }}>
                {groups.map((group, i) => <React.Fragment key={i}>
                    {i === 1 && <>
                        <select aria-label="Paragraph style" defaultValue="" onChange={e => { if (e.target.value) run("formatBlock", e.target.value); e.target.value = ""; }}
                            style={{ height: 34, borderRadius: 8, border: `1px solid ${t.border}`, background: t.inputBg, color: t.text, fontSize: 13, padding: "0 8px", marginRight: 4 }}>
                            <option value="" disabled>Style</option>
                            <option value="<p>">Normal text</option>
                            <option value="<h1>">Heading 1</option>
                            <option value="<h2>">Heading 2</option>
                            <option value="<h3>">Heading 3</option>
                        </select>
                    </>}
                    {group.map(([command, icon, label]) => (
                        <button key={command} type="button" aria-label={label} title={label} disabled={disabled}
                            onMouseDown={e => { e.preventDefault(); const [c, v] = command.split(":"); run(c, v || null); }} style={btn}>
                            <LIcon name={icon} size={17} />
                        </button>
                    ))}
                    {i < groups.length - 1 && sep}
                </React.Fragment>)}
                <span style={{ flex: 1 }} />
                {onDone && <button type="button" onClick={onDone} style={{ minHeight: 34, padding: "0 12px", borderRadius: 8, border: `1px solid ${t.border}`, background: t.card, color: t.text, fontSize: 13, cursor: "pointer" }}>Done</button>}
                {onSave && <button type="button" onClick={onSave} disabled={disabled || saving}
                    style={{ minHeight: 34, padding: "0 14px", marginLeft: 6, borderRadius: 8, border: "none", background: t.primary, color: onPrimary(t), fontSize: 13, fontWeight: 600, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <LIcon name="save" size={15} />{saving ? "Saving…" : "Save"}
                </button>}
            </div>
        )}
        <style>{PAGE_CSS}</style>
        <div ref={ref} data-rte contentEditable={!disabled} suppressContentEditableWarning onInput={e => onChange(e.currentTarget.innerHTML)}
            onClick={e => { const mark = disabled && e.target.closest?.("mark[data-ph]"); if (mark && onPlaceholder) onPlaceholder(mark.dataset.ph); }}
            style={{ minHeight: 600, padding: "44px 56px", outline: "none", borderRadius: 6, background: "#fff", color: "#202a2f", fontFamily: "'Source Serif 4',Georgia,serif", fontSize: 16, lineHeight: 1.8, boxShadow: "0 8px 24px rgba(0,0,0,0.12)" }} />
    </section>;
}

/* Quick requests offered in the Ask AI composer, by what the document began
 * as. They only fill the box: nothing is sent until the user sends it, and the
 * result is a proposal that is saved only on Save. */
const ASK_SUGGESTIONS = {
    nda: ["Add a return-of-materials clause", "Change term to 1 year"],
    legal_notice: ["Give 30 days to respond", "Make the demand firmer"],
    rental_agreement: ["Add a 2-month notice period", "Tenant pays the utility bills"],
    power_of_attorney: ["Limit the powers to property matters", "Add an expiry date"],
    plaint_civil: ["Make the facts more concise", "Add interest to the relief"],
};
const ASK_DEFAULT = ["Make the wording more formal", "Fix grammar and spelling"];
export function askSuggestions(templateType) {
    return ASK_SUGGESTIONS[templateType] || ASK_DEFAULT;
}

/* Documents by the day they were last worked on, newest group first. */
const DAY = 86400000;
export function groupByDate(items, now = new Date()) {
    const dayStart = d => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const today = dayStart(now);
    const order = ["Today", "Yesterday", "Previous 7 days", "Earlier"];
    const buckets = new Map(order.map(name => [name, []]));
    for (const row of items || []) {
        const when = new Date(row.updated_at || row.created_at || 0);
        const start = Number.isNaN(when.getTime()) ? 0 : dayStart(when);
        const name = start >= today ? "Today" : start >= today - DAY ? "Yesterday"
            : start >= today - 7 * DAY ? "Previous 7 days" : "Earlier";
        buckets.get(name).push(row);
    }
    return order.map(name => [name, buckets.get(name)]).filter(([, rows]) => rows.length);
}

/* The ⋮ menu of one sidebar row. `items` are { label, icon, onSelect,
 * disabled?, title?, danger? }. Closes on choice, outside click or Escape. */
function RowMenu({ t, label, items, icon = "moreHorizontal", trigger = "ds-more" }) {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    useEffect(() => {
        if (!open) return undefined;
        const out = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
        const esc = e => { if (e.key === "Escape") setOpen(false); };
        document.addEventListener("mousedown", out);
        document.addEventListener("keydown", esc);
        return () => { document.removeEventListener("mousedown", out); document.removeEventListener("keydown", esc); };
    }, [open]);
    return (
        <div ref={ref} data-row-menu data-open={open ? "true" : undefined} style={{ position: "relative", flexShrink: 0 }}>
            <button type="button" className={trigger} aria-label={label} title="More actions" aria-haspopup="menu" aria-expanded={open}
                onClick={e => { e.stopPropagation(); setOpen(o => !o); }}>
                <LIcon name={icon} size={trigger === "ds-icon" ? 17 : 15} stroke={2.6} />
            </button>
            {open && (
                <div role="menu" aria-label={label} className="ds-menu">
                    {items.map(item => (
                        <button key={item.label} type="button" role="menuitem" disabled={item.disabled} title={item.title}
                            className={item.danger ? "danger" : undefined}
                            onClick={() => { setOpen(false); item.onSelect(); }}>
                            <LIcon name={item.icon} size={15} />{item.label}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}

/* One row of the drafting sidebar: no card around it, a divider below. The
 * open row is shown by its title in the accent colour -- no box (removed at
 * the user's request, 2026-10-08). The time (`hint`) is small and shows only
 * while the row is hovered or focused; a `note` that matters (Under review, a
 * failed version) is always shown. The ⋮ beside the row holds the rest. */
/* 2026-10-10: the column takes the lawyer AI Assistant's history sidebar look
 * (lawyer/AILegalPage.jsx .ai-convs), as the client's own copy, scoped by
 * [data-drafts-side]: the gradient pill on top, History with its fold and ⋯,
 * uppercase day labels, soft rows with a ⋯ on hover, a footer count and the
 * small round edge button. Colours are the client tokens (client/clientTheme.js). */
const SIDE_ROW_CSS = `[data-side-row] [data-row-hint]{display:none}
[data-side-row]:hover [data-row-hint],[data-side-row]:focus-within [data-row-hint]{display:block}
[data-side-row] [data-row-menu]{opacity:0}
[data-side-row]:hover [data-row-menu],[data-side-row]:focus-within [data-row-menu],[data-row-menu][data-open],[data-side-row][data-selected] [data-row-menu]{opacity:1}
[data-drafts-side]{background:var(--surface)!important;border-right:1px solid var(--line)!important;font-family:"Hanken Grotesk",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
[data-drafts-side] button{font-family:inherit}
[data-drafts-side] .ds-top{padding:14px 12px 12px;border-bottom:1px solid var(--line)}
[data-drafts-side] .ds-new{width:100%;height:38px;display:flex;align-items:center;justify-content:center;gap:7px;border-radius:999px;border:0;background:var(--brand-solid);color:var(--on-brand);font-size:13.5px;font-weight:700;cursor:pointer;box-shadow:0 8px 18px -10px rgba(46,196,214,.6);transition:filter .15s,transform .15s}
[data-drafts-side] .ds-new:hover{filter:brightness(1.08);transform:translateY(-1px)}
[data-drafts-side] .ds-tab{flex:1;min-width:0;height:34px;padding:0 8px;border-radius:999px;border:1px solid color-mix(in srgb,var(--brand-text) 26%,transparent);background:color-mix(in srgb,var(--brand-text) 7%,transparent);color:var(--muted);font-size:12.5px;font-weight:700;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:6px;transition:color .15s,background .15s}
[data-drafts-side] .ds-tab:hover{color:var(--hover-ink);background:var(--hover-tint)}
[data-drafts-side] .ds-tab[aria-selected="true"]{background:var(--brand-solid);color:var(--on-brand);border-color:transparent;box-shadow:0 8px 18px -10px rgba(46,196,214,.6)}
[data-drafts-side] .ds-head{display:flex;align-items:center;gap:4px;padding:12px 8px 6px 14px}
[data-drafts-side] .ds-head [data-side-heading]{flex:1;font-size:16px;font-weight:700;color:var(--ink)}
[data-drafts-side] .ds-icon{width:30px;height:30px;display:grid;place-items:center;border:0;border-radius:8px;background:none;color:var(--ink);cursor:pointer}
[data-drafts-side] .ds-icon:hover,[data-drafts-side] .ds-icon[aria-expanded="true"][aria-haspopup]{color:var(--hover-ink);background:var(--hover-tint)}
[data-drafts-side] .ds-list{flex:1;min-height:0;overflow:auto;padding:6px 8px 64px;scrollbar-width:none;-ms-overflow-style:none}
[data-drafts-side] .ds-list::-webkit-scrollbar{display:none}
[data-drafts-side] .ds-g{display:flex;align-items:center;gap:6px;width:100%;padding:12px 8px 6px;border:0;background:none;text-align:left;font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--faint);font-weight:600;cursor:pointer}
[data-drafts-side] .ds-g svg{opacity:0;transition:opacity .15s,transform .2s}
[data-drafts-side] .ds-g:hover svg,[data-drafts-side] .ds-g[aria-expanded="false"] svg{opacity:1}
[data-drafts-side] [data-side-row]{display:flex;align-items:center;gap:4px;padding:0 4px 0 0;margin-bottom:2px;border-radius:10px;border:1px solid transparent;color:var(--muted);transition:background .15s,color .15s}
[data-drafts-side] [data-side-row]:hover{background:var(--hover-tint);color:var(--ink)}
[data-drafts-side] [data-side-row][data-selected]{background:color-mix(in srgb,var(--brand-text) 10%,transparent);border-color:color-mix(in srgb,var(--brand-text) 30%,transparent);color:var(--ink)}
[data-drafts-side] [data-side-row] > button{flex:1;min-width:0;padding:8px 4px 8px 9px;border:0;background:transparent;color:inherit;text-align:left;cursor:pointer}
[data-drafts-side] [data-side-row] > button:disabled{cursor:default}
[data-drafts-side] [data-side-row] .ds-title{font-size:13px;font-weight:600;color:inherit;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-drafts-side] [data-side-row] .ds-sub{font-size:11.5px;color:var(--faint);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-drafts-side] .ds-more{width:24px;height:24px;display:grid;place-items:center;border:0;border-radius:7px;background:none;color:var(--faint);cursor:pointer}
[data-drafts-side] .ds-more:hover,[data-drafts-side] .ds-more[aria-expanded="true"]{background:color-mix(in srgb,var(--brand-text) 16%,transparent);color:var(--ink)}
[data-drafts-side] .ds-menu{position:absolute;right:0;top:calc(100% + 6px);z-index:30;min-width:176px;padding:4px;display:flex;flex-direction:column;border-radius:10px;border:1px solid var(--line-strong);background:var(--surface);box-shadow:0 18px 36px -12px rgba(0,0,0,.6)}
[data-drafts-side] .ds-menu button{display:flex;align-items:center;gap:9px;width:100%;padding:8px 10px;border:0;border-radius:7px;background:none;color:var(--ink);font-size:13px;text-align:left;white-space:nowrap;cursor:pointer}
[data-drafts-side] .ds-menu button:hover:not(:disabled){background:var(--surface-2)}
[data-drafts-side] .ds-menu button:disabled{opacity:.45;cursor:not-allowed}
[data-drafts-side] .ds-menu button.danger{color:var(--danger)}
[data-drafts-side] .ds-foot{padding:10px 30px 10px 12px;font-size:11.5px;border-top:1px solid var(--line);color:var(--faint);display:flex;justify-content:space-between;gap:8px;white-space:nowrap}
[data-drafts-edge] .ds-edge,[data-drafts-side] .ds-edge{position:absolute;bottom:14px;z-index:20;width:32px;height:32px;display:grid;place-items:center;border:0;border-radius:50%;background:var(--brand-solid);color:var(--on-brand);cursor:pointer;box-shadow:0 0 0 3px var(--bg),0 8px 18px -10px rgba(46,196,214,.6);transition:filter .15s}
[data-drafts-edge] .ds-edge:hover,[data-drafts-side] .ds-edge:hover{filter:brightness(1.1)}`;

/* The document workspace's header and toolbar (2026-10-10): the two ways onward
 * are pills, not boxes, and on hover only their icon moves (the store hops, the
 * plane flies off and back); the toolbar is one compact line whose icons nudge.
 * Scoped by [data-document-workspace]. */
// No fill behind the header or the tool row (2026-10-11): they sit on the page itself, divided by a line.
const WORKSPACE_CSS = `[data-document-workspace] .qr-list{container-type:inline-size}
[data-document-workspace] .rq-veil{position:absolute;inset:0;z-index:6;display:grid;place-items:center;padding:24px;background:rgba(6,12,14,.66);backdrop-filter:blur(3px);animation:rqFade .16s ease}
[data-document-workspace] .rq-card{width:min(500px,100%);border-radius:20px;background:var(--qs);border:1px solid var(--qb);box-shadow:0 40px 90px -30px rgba(0,0,0,.9);animation:rqRise .2s ease}
[data-document-workspace] .rq-head{display:flex;gap:12px;align-items:center;padding:16px 18px 14px;border-bottom:1px solid var(--qb)}
[data-document-workspace] .rq-av{width:42px;height:42px;flex-shrink:0;border-radius:50%;display:grid;place-items:center;font-weight:800;font-size:15px;color:#fff;background:linear-gradient(135deg,#12897f,#1c9c66)}
[data-document-workspace] .rq-eyebrow{font-size:11.5px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--qm)}
[data-document-workspace] .rq-name{margin:1px 0 0;font-size:18px;font-weight:800;line-height:1.25;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-document-workspace] .rq-meta{margin-top:2px;font-size:12.5px;color:var(--qm)}
[data-document-workspace] .rq-x{width:34px;height:34px;flex-shrink:0;align-self:flex-start;border-radius:10px;border:0;background:transparent;color:var(--qm);cursor:pointer;display:grid;place-items:center}
[data-document-workspace] .rq-x:hover{background:color-mix(in srgb,currentColor 10%,transparent);color:inherit}
[data-document-workspace] .rq-body{padding:14px 18px 4px;display:flex;flex-direction:column;gap:12px}
[data-document-workspace] .rq-sum{margin:0;border:1px solid var(--qb);border-radius:12px;overflow:hidden;font-size:12.5px}
[data-document-workspace] .rq-sum div{display:grid;grid-template-columns:96px minmax(0,1fr);gap:10px;align-items:center;padding:6px 12px}
[data-document-workspace] .rq-sum div + div{border-top:1px solid var(--qb)}
[data-document-workspace] .rq-sum dt{font-size:12px;color:var(--qm)}
[data-document-workspace] .rq-sum dd{margin:0;display:flex;align-items:baseline;gap:6px;flex-wrap:wrap;font-size:12.5px;min-width:0}
[data-document-workspace] .rq-sum dd svg{width:13px;height:13px;align-self:center;color:var(--qa);flex-shrink:0}
[data-document-workspace] .rq-sum dd b{font-size:13px;font-weight:800}
[data-document-workspace] .rq-sum dd span{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
[data-document-workspace] .rq-sum dd em{font-style:normal;font-size:11.5px;color:var(--qm)}
[data-document-workspace] .rq-field textarea{width:100%;box-sizing:border-box;margin-top:6px;resize:none;padding:9px 12px;border-radius:12px;border:1px solid var(--qb);background:var(--qi);color:inherit;font:inherit;font-size:14px;line-height:1.5;outline:none;transition:border-color .15s,box-shadow .15s}
[data-document-workspace] .rq-field textarea:focus{border-color:var(--qa);box-shadow:0 0 0 3px color-mix(in srgb,var(--qa) 18%,transparent)}
[data-document-workspace] .rq-label{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
[data-document-workspace] .rq-label label{font-size:13.5px;font-weight:800}
[data-document-workspace] .rq-label span{font-size:12px;color:var(--qm)}
[data-document-workspace] .rq-confirm{position:relative;display:flex;gap:10px;align-items:center;padding:10px 12px;border-radius:12px;border:1px solid var(--qb);font-size:13.5px;font-weight:600;cursor:pointer;transition:border-color .15s,background .15s}
[data-document-workspace] .rq-confirm:hover{border-color:color-mix(in srgb,var(--qa) 45%,transparent)}
[data-document-workspace] .rq-confirm.on{border-color:color-mix(in srgb,var(--qa) 60%,transparent);background:color-mix(in srgb,var(--qa) 8%,transparent)}
[data-document-workspace] .rq-confirm input{position:absolute;opacity:0;width:1px;height:1px}
[data-document-workspace] .rq-tick{width:20px;height:20px;flex-shrink:0;border-radius:6px;border:1.5px solid var(--qm);display:grid;place-items:center;color:transparent;transition:background .15s,border-color .15s,color .15s}
[data-document-workspace] .rq-confirm.on .rq-tick{background:linear-gradient(135deg,#12897f,#1c9c66);border-color:transparent;color:#fff}
[data-document-workspace] .rq-confirm input:focus-visible + .rq-tick{box-shadow:0 0 0 3px color-mix(in srgb,var(--qa) 30%,transparent)}
[data-document-workspace] .rq-issue{font-size:13px;color:#F2C35E}
[data-document-workspace] .rq-foot{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:14px 18px 16px}
[data-document-workspace] .rq-cancel{height:42px;padding:0 18px;border-radius:12px;border:1px solid var(--qb);background:transparent;color:inherit;font:inherit;font-size:14px;font-weight:700;cursor:pointer;transition:background .15s,border-color .15s}
[data-document-workspace] .rq-cancel:hover{background:color-mix(in srgb,currentColor 7%,transparent);border-color:color-mix(in srgb,currentColor 30%,transparent)}
[data-document-workspace] .rq-send{height:42px;padding:0 18px;border-radius:12px;border:0;display:inline-flex;align-items:center;justify-content:center;gap:9px;font:inherit;font-size:14px;font-weight:800;color:#fff;background:linear-gradient(135deg,#12897f,#1c9c66);box-shadow:0 10px 22px -12px rgba(28,156,102,.9);cursor:pointer;transition:filter .15s,transform .12s,box-shadow .15s}
[data-document-workspace] .rq-send:hover:not(:disabled){filter:brightness(1.08)}
[data-document-workspace] .rq-send:active:not(:disabled){transform:scale(.97)}
[data-document-workspace] .rq-send:disabled{background:color-mix(in srgb,currentColor 10%,transparent);color:var(--qm);box-shadow:none;cursor:not-allowed}
@keyframes rqFade{from{opacity:0}}
@keyframes rqRise{from{opacity:0;transform:translateY(10px) scale(.98)}}
[data-document-workspace] .qr-row{display:grid;grid-template-columns:52px minmax(0,1fr) auto auto;grid-template-areas:"av info terms act";gap:10px 22px;align-items:center;background:var(--qs);border:1px solid var(--qb);cursor:pointer;transition:transform .18s ease,background .18s ease,border-color .18s ease,box-shadow .18s ease}
[data-document-workspace] .qr-row:hover,[data-document-workspace] .qr-row:focus-within{transform:translateY(-3px);background:color-mix(in srgb,var(--qa) 7%,var(--qs));border-color:color-mix(in srgb,var(--qa) 40%,transparent);box-shadow:0 16px 30px -22px color-mix(in srgb,var(--qa) 60%,#000)}
[data-document-workspace] .qr-row:active,[data-document-workspace] .qr-row[data-selected]{transform:translateY(-1px);background:color-mix(in srgb,var(--qa) 12%,var(--qs));border-color:var(--qa)}
[data-document-workspace] .qr-av{grid-area:av;transition:background .18s,color .18s}
[data-document-workspace] .qr-row:hover .qr-av,[data-document-workspace] .qr-row[data-selected] .qr-av{background:linear-gradient(135deg,#12897f,#1c9c66) !important;color:#fff !important;box-shadow:none !important}
[data-document-workspace] .qr-info{grid-area:info}
[data-document-workspace] .qr-chip{padding:2px 9px;border-radius:999px;background:color-mix(in srgb,currentColor 10%,transparent);font-size:12px;font-weight:700}
[data-document-workspace] .qr-terms{grid-area:terms;display:flex;align-items:center;gap:18px}
[data-document-workspace] .qr-terms div{display:flex;flex-direction:column;line-height:1.2}
[data-document-workspace] .qr-terms b{font-size:16px;font-weight:800;white-space:nowrap}
[data-document-workspace] .qr-terms span{font-size:12px;opacity:.65;margin-top:3px;white-space:nowrap}
[data-document-workspace] .qr-terms i{width:1px;height:30px;background:var(--qb)}
[data-document-workspace] .qr-ask{grid-area:act;height:40px;padding:0 16px 0 18px;border-radius:999px;border:1px solid color-mix(in srgb,var(--qa) 50%,transparent);background:transparent;color:var(--qa);font:inherit;font-size:13.5px;font-weight:800;cursor:pointer;white-space:nowrap;display:inline-flex;align-items:center;gap:8px;transition:background .18s,color .18s,border-color .18s,box-shadow .18s}
[data-document-workspace] .qr-ask svg{transition:transform .2s}
[data-document-workspace] .qr-ask:hover:not(:disabled),[data-document-workspace] .qr-row[data-selected] .qr-ask{background:linear-gradient(135deg,#12897f,#1c9c66);border-color:transparent;color:#fff;box-shadow:0 8px 18px -10px rgba(28,156,102,.9)}
[data-document-workspace] .qr-ask:hover:not(:disabled) svg{transform:translateX(3px)}
[data-document-workspace] .qr-ask:active:not(:disabled){transform:scale(.97)}
[data-document-workspace] .qr-ask:disabled{opacity:.5;cursor:not-allowed}
@container (max-width:760px){[data-document-workspace] .qr-row{grid-template-columns:52px minmax(0,1fr) auto;grid-template-areas:"av info info" "av terms act";align-items:start}[data-document-workspace] .qr-ask{align-self:center}[data-document-workspace] .qr-terms{margin-top:4px}}
[data-document-workspace] .ws-header{background:transparent;border-bottom:1px solid var(--line)}
[data-document-workspace] .ws-tools{background:transparent;border-bottom:1px solid var(--line)}
[data-document-workspace] .ws-main{background:radial-gradient(1000px 420px at 50% -140px,color-mix(in srgb,var(--brand-text) 8%,transparent),transparent 70%) no-repeat,var(--bg)}
[data-document-workspace] .ws-back{width:36px;height:36px;flex:none;border-radius:50%;border:0;background:transparent;color:var(--ink);display:grid;place-items:center;cursor:pointer}
[data-document-workspace] .ws-back svg{transition:transform .2s ease}
[data-document-workspace] .ws-back:hover svg{transform:translateX(-3px)}
[data-document-workspace] .ws-pill{display:inline-flex;align-items:center;gap:8px;height:36px;padding:0 15px 0 5px;border-radius:999px;font-family:inherit;font-size:13px;font-weight:700;white-space:nowrap;cursor:pointer;flex-shrink:0}
[data-document-workspace] .ws-pill .ic{width:26px;height:26px;border-radius:50%;display:grid;place-items:center;overflow:hidden}
[data-document-workspace] .ws-market{border:1px solid color-mix(in srgb,var(--teal) 38%,transparent);background:color-mix(in srgb,var(--teal) 11%,transparent);color:var(--ink)}
[data-document-workspace] .ws-market .ic{background:var(--teal);color:var(--on-teal)}
[data-document-workspace] .ws-tools-row{display:flex;align-items:center;justify-content:space-between;gap:8px;width:100%;max-width:1080px;margin:0 auto}
[data-document-workspace] .ws-divider{width:1px;height:18px;flex:none;background:var(--line-strong)}
[data-document-workspace] .ws-tools-row > button{--c:var(--brand-text);position:relative;overflow:hidden;height:32px;min-height:32px!important;padding:0 11px!important;gap:5px!important;font-size:12.5px!important;border-radius:999px!important;border:1px solid color-mix(in srgb,var(--c) 26%,transparent)!important;background:color-mix(in srgb,var(--c) 8%,transparent)!important;box-shadow:none;transition:background .18s,color .18s,border-color .18s,box-shadow .18s,transform .15s ease}
[data-document-workspace] .ws-tools-row > [data-placeholders-toggle]{--c:var(--gold)}
[data-document-workspace] .ws-tools-row > [data-placeholders-toggle]:not(:hover):not([aria-pressed="true"]){background:transparent!important}
[data-document-workspace] .ws-tools-row > [data-checks-toggle]{--c:var(--teal-ink)}
[data-document-workspace] .ws-tools-row > [data-pdf]{--c:var(--c-contract)}
[data-document-workspace] .ws-tools-row > [data-undo]{--c:var(--teal-ink)}
[data-document-workspace] .ws-tools-row > button svg{color:var(--c);flex:none;width:15px;height:15px;transition:transform .2s ease}
[data-document-workspace] .ws-tools-row > button:disabled{--c:var(--faint);background:transparent!important;border-color:color-mix(in srgb,var(--faint) 30%,transparent)!important;border-style:dashed!important}
[data-document-workspace] .ws-tools-row > button:hover:not(:disabled){transform:translateY(-1px);background:color-mix(in srgb,var(--c) 16%,transparent)!important;border-color:color-mix(in srgb,var(--c) 55%,transparent)!important;color:var(--ink)!important;box-shadow:0 8px 18px -12px var(--c)}
[data-document-workspace] .ws-tools-row > button:active:not(:disabled){transform:translateY(0) scale(.94)}
[data-document-workspace] .ws-tools-row > button[aria-pressed="true"]{background:color-mix(in srgb,var(--c) 20%,transparent)!important;border-color:color-mix(in srgb,var(--c) 60%,transparent)!important;color:var(--ink)!important;box-shadow:0 0 0 3px color-mix(in srgb,var(--c) 14%,transparent)}
[data-document-workspace] .ws-tools-row > button[aria-pressed="true"]::before{content:"";position:absolute;left:30%;right:30%;bottom:3px;height:2px;border-radius:2px;background:var(--c);box-shadow:0 0 8px var(--c);animation:wsGrow .25s ease}
[data-document-workspace] .ws-tools-row > button::after{content:"";position:absolute;inset:0;pointer-events:none;border-radius:inherit;background:radial-gradient(circle,color-mix(in srgb,var(--c) 50%,transparent) 0%,transparent 62%);opacity:0;transform:scale(2.2);transition:transform .5s ease,opacity .6s ease}
[data-document-workspace] .ws-tools-row > button:active:not(:disabled)::after{opacity:1;transform:scale(0);transition:0s}
[data-document-workspace] .ws-tools-row > [data-edit-toggle]:hover:not(:disabled) svg{animation:wsWrite .6s ease}
[data-document-workspace] .ws-tools-row > [data-placeholders-toggle]:hover:not(:disabled) svg{animation:wsSlide .6s ease}
[data-document-workspace] .ws-tools-row > [data-checks-toggle]:hover:not(:disabled) svg{animation:wsPop .45s cubic-bezier(.34,1.56,.64,1)}
[data-document-workspace] .ws-tools-row > [data-save]:hover:not(:disabled) svg{animation:wsPress .45s ease}
[data-document-workspace] .ws-tools-row > [data-pdf]:hover svg{animation:wsDrop .55s cubic-bezier(.34,1.56,.64,1)}
[data-document-workspace] .ws-tools-row > [data-undo]:hover:not(:disabled) svg{animation:wsTurn .5s ease}
@keyframes wsWrite{0%,100%{transform:none}25%{transform:translate(-1px,1px) rotate(-12deg)}50%{transform:translate(1px,-1px) rotate(6deg)}75%{transform:translate(-1px,1px) rotate(-8deg)}}
@keyframes wsSlide{0%,100%{transform:none}35%{transform:translateX(2px) scaleX(.9)}70%{transform:translateX(-2px)}}
@keyframes wsPop{0%{transform:scale(1)}50%{transform:scale(1.25)}100%{transform:scale(1)}}
@keyframes wsPress{0%,100%{transform:none}45%{transform:translateY(2px) scale(.88)}}
@keyframes wsDrop{0%{transform:translateY(-6px);opacity:0}60%{transform:translateY(1px);opacity:1}100%{transform:none}}
@keyframes wsTurn{0%,100%{transform:none}50%{transform:rotate(-40deg)}}
@keyframes wsGrow{from{left:50%;right:50%}to{left:30%;right:30%}}
[data-document-workspace] .ws-send{border:0;background:var(--brand-solid);color:var(--on-brand);box-shadow:0 8px 18px -10px rgba(46,196,214,.6)}
[data-document-workspace] .ws-send .ic{background:rgba(0,0,0,.14)}
[data-document-workspace] .ws-send:disabled{opacity:.5;cursor:not-allowed;box-shadow:none}
[data-document-workspace] .ws-market:hover .ic svg{animation:wsHop .55s ease}
[data-document-workspace] .ws-send:hover:not(:disabled) .ic svg{animation:wsFly .7s ease}
[data-document-workspace] .ws-tools{scrollbar-width:none;-ms-overflow-style:none}
[data-document-workspace] .ws-tools::-webkit-scrollbar{display:none}
@keyframes wsHop{0%,100%{transform:translateY(0)}40%{transform:translateY(-3px)}70%{transform:translateY(1px)}}
@keyframes wsFly{0%{transform:translate(0,0);opacity:1}45%{transform:translate(9px,-9px);opacity:0}46%{transform:translate(-9px,9px);opacity:0}100%{transform:translate(0,0);opacity:1}}
@keyframes wsNudge{0%,100%{transform:none}40%{transform:translateY(-2px) rotate(-6deg)}}
@media (prefers-reduced-motion:reduce){[data-document-workspace] .ws-pill .ic svg,[data-document-workspace] .ws-tools svg,[data-document-workspace] .ws-back svg{animation:none!important;transition:none!important}}`;

// Styled by SIDE_ROW_CSS ([data-drafts-side]): a soft row, the open one on the well.
function SideRow({ selected, title, note = null, hint = null, onOpen, disabled = false, menu, dataAttrs = {} }) {
    return (
        <div data-side-row data-selected={selected ? "true" : undefined}>
            <button type="button" onClick={onOpen} disabled={disabled} aria-current={selected ? "true" : undefined} {...dataAttrs}>
                <div className="ds-title">{title}</div>
                {note && <div data-row-note className="ds-sub">{note}</div>}
                {hint && <div data-row-hint className="ds-sub">{hint}</div>}
            </button>
            {menu}
        </div>
    );
}

/* The workspace's checks: the revision's own two, plus whether every detail
 * is filled (from the details as they are now). Same badge rules. */
export function workspaceChecks(revision, { unfilled = 0, structured = false, edited = false } = {}) {
    const base = revisionChecks(revision);
    // Edited text no longer follows the template's fields, so its particulars
    // are not checked -- said as such, never as a pass or a failure.
    if (edited) base.rows[0] = { ...base.rows[0], value: "Not checked — wording edited", tone: "neutral" };
    const rows = [
        ...(structured ? [{ key: "details", label: "All details filled", fix: true,
            value: unfilled ? `${unfilled} detail${unfilled === 1 ? "" : "s"} still blank` : "Every detail is filled",
            tone: unfilled ? "warn" : "ok", detail: "" }] : []),
        // Edited wording has no particulars to fill in: no "Fill in" there.
        { ...base.rows[0], key: "particulars", fix: !edited },
        { ...base.rows[1], key: "citations" },
    ];
    const passed = rows.filter(r => ["success", "ok"].includes(r.tone)).length;
    const issues = rows.filter(r => ["warn", "danger"].includes(r.tone)).length;
    const ran = passed + issues;
    const badge = issues ? { text: `${issues} issue${issues === 1 ? "" : "s"}`, tone: "medium" }
        : ran ? { text: `${passed}/${ran}`, tone: "low" }
        : { text: "—", tone: "neutral", title: "No check has run on this revision" };
    return { rows, passed, issues, ran, total: rows.length, badge };
}

/* Before a PDF exists, the same editor shell shows the plan's outline and
 * its real, editable details. Save & next records answers on the plan.
 *
 * Everything here is the real plan: Save & next sends the details you typed or
 * changed (answerDraftPlanV2 accepts any non-empty subset); the count is the
 * plan's own fields against its `remaining_detail_count`; "Skip for now" is the
 * server's skip-missing confirmation -- the blanks are filled later in the
 * document's Fill Placeholders. Before generation there is no PDF, so the
 * middle is an OUTLINE and says so; the document itself comes after Confirm. */
function DraftPlan({ plan, spec, answers, setAnswers, busy, issue, onAnswer, onConfirm, onGenerate, onBack, typeOptions, onChangeType, L }) {
    const t = useT();
    const [savedAt, setSavedAt] = useState(null);    // a real save in this visit
    const [focus, setFocus] = useState(null);
    const [activePlanField, setActivePlanField] = useState(null);
    const [showAllPlanFields, setShowAllPlanFields] = useState(false);
    const questions = plan.questions || [];
    const asked = new Map(questions.map(q => [q.field, q]));
    const editable = ["needs_template", "needs_details", "ready"].includes(plan.status);
    const done = ["confirmed", "generating", "generated", "generation_failed"].includes(plan.status);
    const notes = plan.extraction_notes || [];
    const known = plan.fields || {};
    const filledKeys = Object.keys(known).filter(k => String(known[k] ?? "").trim());
    const remaining = Math.max(Number(plan.remaining_detail_count ?? questions.length) || 0, questions.length);
    const total = filledKeys.length + remaining;
    // The details to show: what is asked first, then what is already known.
    const fields = [...new Set([...questions.map(q => q.field), ...Object.keys(known)])];
    // The outline: the template's own fields when known, else the plan's.
    const outlineFields = [...new Set([...(spec?.fields || []).filter(f => !(spec?.structured_fields || []).includes(f)), ...fields])];
    const valueOf = f => answers[f] ?? String(known[f] ?? "");
    const active = fields.includes(activePlanField) ? activePlanField : (questions[0]?.field || fields[0] || null);
    const activeQuestion = asked.get(active);
    const activeValue = active ? valueOf(active) : "";
    const remainingFields = fields.filter(f => f !== active && !String(valueOf(f)).trim());
    const listedFields = showAllPlanFields ? fields.filter(f => f !== active) : remainingFields;
    const activeIndex = fields.indexOf(active);
    const nextField = fields.slice(activeIndex + 1).find(f => !String(valueOf(f)).trim())
        || fields.find(f => f !== active && !String(valueOf(f)).trim())
        || fields[(activeIndex + 1) % fields.length] || null;
    const previousField = fields[(activeIndex - 1 + fields.length) % fields.length] || null;
    const pending = Object.fromEntries(Object.entries(answers)
        .map(([k, v]) => [k, String(v ?? "").trim()])
        .filter(([k, v]) => v !== String(known[k] ?? "").trim()));
    const hasPending = Object.keys(pending).length > 0;
    const applyAll = async () => { if (hasPending && await onAnswer(pending)) { setSavedAt(Date.now()); if (nextField) setActivePlanField(nextField); } };
    const filledNow = Math.min(total, fields.filter(f => String(valueOf(f)).trim()).length);
    const typeLabel = spec?.label || (plan.template_type ? humanise(plan.template_type) : "Document");
    const tokenOfField = f => `[[${String(f).toUpperCase()}]]`;
    const chipStyle = (bg, fg) => ({ fontSize: 12.5, fontWeight: 600, padding: "3px 10px", borderRadius: 999, background: bg, color: fg });
    const scroll = { scrollbarWidth: "thin", scrollbarColor: `${t.border} transparent` };

    return <section data-draft-plan aria-label="Draft plan" style={{ ...L.col("1 1 600px"), display: "flex", flexDirection: "column", minHeight: 0 }}>
        <div role="toolbar" aria-label="Plan actions" style={{ minHeight: 64, flexShrink: 0, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", padding: "9px 18px", borderBottom: `1px solid ${t.border}` }}>
            <button type="button" onClick={onBack} aria-label="Back to drafts" title="Back to drafts"
                style={{ minHeight: 40, padding: "0 5px", borderRadius: 9, border: "none", background: "transparent", color: t.textMuted, cursor: "pointer" }}>Drafts</button>
            <span aria-hidden="true" style={{ color: t.textMuted }}>/</span>
            <span style={{ fontSize: 14.5, fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "min(320px, 30vw)" }}>{plan.title || typeLabel}</span>
            <span style={{ flex: 1 }} />
            {busy ? <span style={{ fontSize: 13, color: t.textMuted }}>Saving…</span>
                : hasPending ? <span style={{ fontSize: 13, color: t.warn }}>Unsaved details</span>
                    : savedAt ? <span data-plan-saved style={{ fontSize: 13, color: t.success }}>✓ Saved just now</span> : null}
        </div>
        <div style={{ ...L.row, minHeight: 0 }}>
            {/* The outline, not the document: nothing is generated yet. */}
            <div data-lenis-prevent style={{ ...L.col("1 1 420px"), overflowY: "auto", ...scroll, padding: "18px 18px 28px", display: "flex", flexDirection: "column", alignItems: "center", gap: 10, background: t.mode === "dark" ? "rgba(0,0,0,0.22)" : "rgba(26,46,53,0.05)" }}>
                <div style={{ fontSize: 12, color: t.textMuted }}>Outline — it fills in as you type. The full document is generated after you confirm.</div>
                <Paper title={typeLabel.toUpperCase()} width={760} titleSize={24} style={{ fontSize: 16.5, lineHeight: 1.9 }}>
                    {plan.prompt && <p style={{ margin: "0 0 18px", fontStyle: "italic", color: "#4a5a5f" }}>{plan.prompt}</p>}
                    {outlineFields.map((f, i) => {
                        const v = String(valueOf(f)).trim();
                        return <p key={f} data-outline-field={f} style={{ margin: "0 0 12px", display: "flex", gap: 14 }}>
                            <span style={{ minWidth: 24 }}>{i + 1}.</span>
                            <span><b>{humanise(f)}.</b>{" "}
                                {v ? <span style={VALUE_STYLE}>{v}</span>
                                    : <span style={{ ...TOKEN_STYLE, outline: focus === f ? `2px solid ${t.primary}` : "none", outlineOffset: 2 }}>{tokenOfField(f)}</span>}
                            </span>
                        </p>;
                    })}
                </Paper>
            </div>

            <aside aria-label="Complete document" style={{ ...L.col("0 1 360px"), borderLeft: `1px solid ${t.border}`, background: t.surface, display: "flex", flexDirection: "column", minHeight: 0 }}>
                <div style={{ padding: "18px 18px 10px", fontSize: 18, fontWeight: 700 }}>Complete document</div>
                <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "0 18px 14px" }}>
                    <div style={{ width: 68, height: 68, flexShrink: 0, borderRadius: "50%", background: `conic-gradient(${t.primary} ${total ? (filledNow / total) * 100 : 100}%, ${t.border} 0)`, display: "grid", placeItems: "center" }}>
                        <span data-plan-progress style={{ width: 55, height: 55, borderRadius: "50%", background: t.surface, display: "grid", placeItems: "center", fontSize: 12, fontWeight: 700 }}>{filledNow}/{total}</span>
                    </div>
                    <div><strong style={{ fontSize: 18 }}>{total ? Math.round((filledNow / total) * 100) : 100}%</strong><span style={{ color: t.textMuted, marginLeft: 5, fontSize: 13 }}>complete</span></div>
                </div>
                <div role="group" aria-label="Plan detail filter" style={{ display: "flex", margin: "0 18px 12px", padding: 3, border: `1px solid ${t.border}`, borderRadius: 10 }}>
                    {[[false, "Required"], [true, "All"]].map(([all, label]) => <button key={label} type="button" aria-pressed={showAllPlanFields === all} onClick={() => setShowAllPlanFields(all)}
                        style={{ flex: 1, minHeight: 34, border: "none", borderRadius: 7, background: showAllPlanFields === all ? `${t.primary}25` : "transparent", color: t.text, fontWeight: 650, cursor: "pointer" }}>{label}</button>)}
                </div>
                <div data-lenis-prevent style={{ flex: 1, overflowY: "auto", ...scroll, padding: "12px 16px", display: "flex", flexDirection: "column", gap: 14 }}>
                    {/* A wrongly inferred type is corrected here, before anything is generated. */}
                    {editable && plan.template_type && typeOptions.length > 0 && (
                        <label style={{ display: "flex", flexDirection: "column", gap: 5, color: t.text, fontSize: 13.5 }}>
                            <span style={{ fontWeight: 600 }}>Document type</span>
                            <select data-plan-type value={plan.template_type} disabled={busy}
                                onChange={e => { if (e.target.value && e.target.value !== plan.template_type) onChangeType(e.target.value); }} style={fieldStyle(t)}>
                                {!typeOptions.some(o => o.template_type === plan.template_type) && <option value={plan.template_type}>{humanise(plan.template_type)}</option>}
                                {typeOptions.map(o => <option key={o.template_type} value={o.template_type}>{o.label}</option>)}
                            </select>
                            <small style={{ color: t.textMuted }}>Changing the type re-reads your description for that document.</small>
                        </label>
                    )}
                    {plan.extraction_status && plan.extraction_status !== "ok" && (
                        <div data-extraction-status style={{ fontSize: 12.5, color: t.textMuted, lineHeight: 1.5 }}>AI could not read these details from your description — fill them in below.</div>
                    )}
                    {notes.length > 0 && (
                        <div role="note" data-extraction-notes style={{ padding: "10px 12px", borderRadius: 9, background: t.inputBg, border: `1px solid ${t.border}`, color: t.text, fontSize: 12.5 }}>
                            Please check: {notes.map(n => `${humanise(n.field)} was ${NOTE_WORDS[n.action] || n.action}`).join("; ")}.
                        </div>
                    )}
                    <section data-plan-choices aria-label="Details" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                        {active ? <div data-plan-field={active} style={{ display: "flex", flexDirection: "column", gap: 8, padding: 16, border: `1px solid ${t.border}`, borderRadius: 14, background: t.card }}>
                            <div style={{ display: "flex", gap: 8, alignItems: "center" }}><strong style={{ flex: 1, fontSize: 15 }}>{activeQuestion?.label || humanise(active)}</strong><span style={chipStyle(activeValue.trim() ? `${t.success}2b` : `${t.warn}2b`, activeValue.trim() ? t.success : t.warn)}>{activeValue.trim() ? "Filled" : "Required"}</span></div>
                            <label htmlFor={`plan_${active}`} style={{ fontSize: 12.5, color: t.textMuted }}>{activeQuestion?.question || "Check this detail before generating the document."}</label>
                            {activeQuestion?.options?.length
                                ? <select id={`plan_${active}`} value={activeValue} disabled={!editable || busy} onFocus={() => setFocus(active)}
                                    onChange={e => setAnswers(a => ({ ...a, [active]: e.target.value }))} style={fieldStyle(t)}>
                                    <option value="">Choose…</option>{activeQuestion.options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                                </select>
                                : <input id={`plan_${active}`} value={activeValue} disabled={!editable || busy} onFocus={() => setFocus(active)}
                                    placeholder={`Enter ${humanise(active).toLowerCase()}…`}
                                    onChange={e => setAnswers(a => ({ ...a, [active]: e.target.value }))}
                                    style={fieldStyle(t, { minHeight: 44, border: `1px solid ${focus === active ? t.primary : t.inputBorder || t.border}` })} />}
                            <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                                <Btn onClick={() => setActivePlanField(previousField)} disabled={!previousField || fields.length < 2} style={{ flex: 1 }}>Back</Btn>
                                <Btn kind="primary" disabled={busy || !hasPending} onClick={applyAll} style={{ flex: 1.4 }}>{busy ? "Saving…" : "Save & next"} <LIcon name="arrowRight" size={15} /></Btn>
                            </div>
                        </div> : <div style={{ color: t.textMuted, fontSize: 13 }}>{done ? "The plan is confirmed. Generate the document to open it." : "Every detail is in. Confirm the plan to generate the document."}</div>}
                        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 13 }}><strong>{showAllPlanFields ? "All details" : "Remaining details"}</strong><span data-plan-remaining style={{ color: t.textMuted }}>{remaining} remaining</span></div>
                        {listedFields.map(f => <button key={f} type="button" onClick={() => setActivePlanField(f)} style={{ minHeight: 34, display: "flex", alignItems: "center", gap: 10, padding: "3px 2px", border: "none", background: "transparent", color: t.text, cursor: "pointer", textAlign: "left" }}>
                            <span aria-hidden="true" style={{ width: 15, height: 15, borderRadius: "50%", border: `2px solid ${String(valueOf(f)).trim() ? t.success : t.warn}` }} />
                            <span style={{ flex: 1, fontSize: 13 }}>{asked.get(f)?.label || humanise(f)}</span><span aria-hidden="true">›</span>
                        </button>)}
                        {remaining > questions.length && <div style={{ fontSize: 12, color: t.textMuted }}>More details may be asked after these.</div>}
                    </section>
                    {issue && <div role="alert" style={{ color: t.warn, fontSize: 13 }}>{issue}</div>}
                </div>

                <div style={{ padding: "12px 16px", borderTop: `1px solid ${t.border}`, display: "flex", flexDirection: "column", gap: 8 }}>
                    {editable && fields.length > 1 && <Btn onClick={() => setActivePlanField(nextField)} disabled={busy} style={{ minHeight: 40 }}>Skip for now</Btn>}
                    {questions.length > 0 && plan.template_type && (
                        <Btn disabled={busy || hasPending} onClick={() => onConfirm(true)} title="Confirm the plan and leave the rest blank — fill them in the document later" style={{ minHeight: 40 }}>Continue with missing details</Btn>
                    )}
                    {questions.length === 0 && !done && <Btn kind="primary" disabled={busy || hasPending} onClick={() => onConfirm(false)} style={{ minHeight: 44 }}>Confirm plan</Btn>}
                    {plan.status === "confirmed" && <Btn kind="primary" disabled={busy} onClick={() => onGenerate(false)} style={{ minHeight: 44 }}>{busy ? "Generating…" : "Generate document"}</Btn>}
                    {plan.status === "generating" && <Btn kind="primary" disabled={busy} onClick={() => onGenerate(false)} style={{ minHeight: 44 }}>{busy ? "Checking…" : "Retry generation"}</Btn>}
                    {plan.status === "generation_failed" && <Btn kind="primary" disabled={busy} onClick={() => onGenerate(true)} style={{ minHeight: 44 }}>{busy ? "Retrying…" : "Retry generation"}</Btn>}
                    <div style={{ fontSize: 12, color: t.textMuted, textAlign: "center" }}>{questions.length > 0 ? "Save & next records your details. The document is generated after confirmation." : "The document is generated after you confirm this plan."}</div>
                </div>
            </aside>
        </div>
    </section>;
}

export default function DocsDrafts({ seed, templates, cases, onBack, onOpenView, openDocument = null }) {
    const t = useT();
    const toast = useToast();
    const [plan, setPlan] = useState(null), [answers, setAnswers] = useState({});
    const [workspace, setWorkspace] = useState(null), [detail, setDetail] = useState(null), [content, setContent] = useState(null);
    const [previewUrl, setPreviewUrl] = useState(null), [busy, setBusy] = useState(false), [issue, setIssue] = useState(null);
    const [instruction, setInstruction] = useState(""), [proposal, setProposal] = useState(null), [openingId, setOpeningId] = useState(null);
    const [typeNeeded, setTypeNeeded] = useState(false);   // the type could not be detected
    const [editMode, setEditMode] = useState(false);        // free-text editor's formatting bar
    const [activeField, setActiveField] = useState(null);
    const [showAllFields, setShowAllFields] = useState(true);   // the form opens complete
    const [savedAt, setSavedAt] = useState(null);
    // The left column's tab while a document is open: its versions, or the
    // client's saved documents. Without a document only the list exists.
    // With a document open, the column's two options: its versions, or the
    // saved documents. Without one, it is the History list.
    const [sideTab, setSideTab] = useState("saved");
    const [historyOpen, setHistoryOpen] = useState(true);    // the History list
    const [closedGroups, setClosedGroups] = useState({});     // day groups folded away
    const [sideCollapsed, setSideCollapsed] = useState(false); // the whole column
    // An older revision on screen: { revision_id, version, url }. Editing and
    // saving always build on the CURRENT revision; this is for reading only.
    const [viewRev, setViewRev] = useState(null);
    // A named template's TEXT being edited (Edit on a text-editable template).
    // Saving then stores the text, as an edited document, from that version on.
    const [textEdit, setTextEdit] = useState(false);
    // The template's wording for details typed but not yet saved.
    const [liveText, setLiveText] = useState(null);
    // Values typed against `[[NAME]]` placeholders in a text, before inserting.
    const [tokenDraft, setTokenDraft] = useState({});
    // The floating Ask AI composer over the document.
    const [askOpen, setAskOpen] = useState(false);
    // Sending to a lawyer happens here, in the workspace (2026-10-08): the
    // send panel, then the status banner. One screen for one document.
    const [sendForm, setSendForm] = useState({ lawyerId: null, urgency: "normal", note: "", confirmed: false });
    const [lawyers, setLawyers] = useState(null);             // null = not loaded
    // QUICK REVIEW (2026-10-11): lawyers who check one document without being
    // hired -- no consultation, no engagement. Hiring them for a whole case is
    // the Lawyers page's job. null = not loaded.
    const [reviewers, setReviewers] = useState(null);
    // This document's quick-review requests, newest first: { docId, items }.
    const [quickReqs, setQuickReqs] = useState(null);
    // The lawyer a review is being requested from (the confirm dialog).
    const [qrAsk, setQrAsk] = useState(null);
    const [qrForm, setQrForm] = useState({ note: "", confirmed: false });
    const [qrBusy, setQrBusy] = useState(false);
    const [qrIssue, setQrIssue] = useState(null);
    const [lawyerQuery, setLawyerQuery] = useState("");
    const [sending, setSending] = useState(false);
    const [sendIssue, setSendIssue] = useState(null);         // { message, retryable }
    // After a send: what was sent, to whom -- the "Sent" screen (2026-10-11).
    const [sentInfo, setSentInfo] = useState(null);
    const submitKey = useRef(null), withdrawKey = useRef(null);
    // The saved document being deleted from its ⋮ menu (the Vault's own dialog).
    const [deleting, setDeleting] = useState(null);
    const router = useRouter();
    const loadToken = useRef(0);
    const undoStack = useRef({ items: [], last: null });    // local undo of detail edits
    const [panel, setPanel] = useState(null), [focus, setFocus] = useState(null);
    const createIntent = useRef(null), generationKey = useRef(null), saveIntent = useRef(null), seeded = useRef(false), restored = useRef(false);
    const fetchPage = useCallback(({ cursor, limit }) => myDocumentsV2({ cursor, limit }), []);
    const docs = useMyDocuments({ fetchPage, pageSize: 25 });
    const revision = detail?.current_revision || null, locked = detail?.review_status === "submitted";
    // Text (a free draft, or a template whose text is being edited) or details.
    const isText = workspace?.source === "freeform_html" || textEdit;
    const editingPayload = isText ? { bodyHtml: content?.body_html || "", fields: null } : { bodyHtml: null, fields: content?.fields || {} };
    const titleByType = useMemo(() => Object.fromEntries((templates || []).map(x => [x.template_type, x.label])), [templates]);
    // Columns side by side that each scroll on a desktop; one page-scrolling
    // column on a phone. Never a wrapping row: it sizes to its content and
    // then nothing can scroll (see splitLayout).
    const L = splitLayout(useIsMobile());

    useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);
    useEffect(() => () => { if (viewRev?.url) URL.revokeObjectURL(viewRev.url); }, [viewRev]);
    useEffect(() => () => { loadToken.current += 1; }, []);

    const loadWorkspace = useCallback(async docId => {
        const request = ++loadToken.current;
        setBusy(true); setIssue(null); setProposal(null); setPreviewUrl(null); setSavedAt(null); setViewRev(null);
        const [wsRes, docRes] = await Promise.all([getDocumentWorkspaceV2(docId), getDocumentV2(docId)]);
        if (request !== loadToken.current) return null;
        if (wsRes.error || docRes.error) {
            // Not this account's, deleted, or unreachable: the address must not
            // keep asking for it on every refresh.
            unlinkOpenDocument();
            setBusy(false); setIssue(messageOf(wsRes.error || docRes.error, "Could not open the document workspace.")); return false;
        }
        const ws = wsRes.data, doc = docRes.data, rev = doc?.current_revision;
        // A refresh reopens THIS document (see lib/documentsNav.js).
        linkOpenDocument(docId);
        setWorkspace(ws); setDetail(doc); setContent(ws.source === "freeform_html" ? { body_html: ws.body_html } : { fields: { ...(ws.fields || {}) } });
        // The side panel opens on request (Placeholders / Checks), so the
        // document gets the full width when it is first opened.
        setPanel(null);
        setActiveField(placeholderFields(ws.fields || {}).find(k => !String(ws.fields?.[k] ?? "").trim())
            || placeholderFields(ws.fields || {})[0] || null);
        setShowAllFields(true); setEditMode(false); setTextEdit(false); setLiveText(null); undoStack.current = { items: [], last: null };
        // A document read as text needs no PDF to open -- the PDF is for
        // export and review. Only a template without a text view shows it.
        if (rev?.revision_id && ws.source !== "freeform_html" && !ws.text_editable) {
            const shown = await previewRevisionV2(docId, rev.revision_id, { expectedPdfSha256: rev.pdf_sha256 });
            if (request !== loadToken.current) { if (shown.data?.url) URL.revokeObjectURL(shown.data.url); return null; }
            if (shown.data) setPreviewUrl(shown.data.url);
            else setIssue(messageOf(shown.error, "The PDF preview could not be loaded."));
        }
        setBusy(false); return true;
    }, []);

    const startPlan = useCallback(async input => {
        const payload = { prompt: String(input?.prompt || "").trim(), templateType: input?.templateType || null, caseId: input?.caseId || null };
        if (!payload.prompt || busy) return;
        const fingerprint = JSON.stringify(payload);
        if (createIntent.current?.fingerprint !== fingerprint) createIntent.current = { fingerprint, key: idempotencyKey() };
        setBusy(true); setIssue(null); setTypeNeeded(false); setWorkspace(null); setDetail(null);
        const result = await createDraftPlanV2(payload, createIntent.current.key);
        setBusy(false);
        if (result.error) { setIssue(messageOf(result.error, "Could not create the draft plan.")); return; }
        createIntent.current = null; generationKey.current = null;
        // No separate page for "which document is this?" (removed at the user's
        // request, 2026-10-08): the type is chosen on the start card instead.
        if (result.data.status === "needs_template") {
            setTypeNeeded(true);   // the card says why, under the Document type field
            return;
        }
        setPlan(result.data); setAnswers({});
        planStore.set(PLAN_KEY, result.data.id);
    }, [busy]);

    // After a reload: bring back the plan this tab was working on, and the
    // generation key it was using, so a half-finished generation resumes.
    useEffect(() => {
        if (restored.current || seed?.prompt) return;
        restored.current = true;
        const planId = planStore.get(PLAN_KEY);
        if (!planId) return;
        getDraftPlanV2(planId).then(r => {
            if (r.error || !r.data) { planStore.drop(PLAN_KEY); planStore.drop(GEN_KEY_PREFIX + planId); return; }
            if (r.data.status === "generated") { planStore.drop(PLAN_KEY); planStore.drop(GEN_KEY_PREFIX + planId); return; }
            // A plan still waiting for its type is not reopened: that page is gone.
            if (r.data.status === "needs_template") { planStore.drop(PLAN_KEY); return; }
            generationKey.current = planStore.get(GEN_KEY_PREFIX + planId);
            setPlan(r.data);
        });
    }, [seed]);
    useEffect(() => { if (seed?.prompt && !seeded.current) { seeded.current = true; startPlan(seed); } }, [seed, startPlan]);
    // Back from "Send for lawyer review": the same document, in the workspace.
    useEffect(() => { if (openDocument?.id) loadWorkspace(openDocument.id); }, [openDocument?.id, openDocument?.at, loadWorkspace]);

    const changeType = async templateType => { setBusy(true); setIssue(null); const r = await answerDraftPlanV2(plan.id, { expectedVersion: plan.version, answers: { template_type: templateType } }); if (r.error) { const latest = await getDraftPlanV2(plan.id); if (latest.data) setPlan(latest.data); setBusy(false); return setIssue(messageOf(r.error, "Could not change the document type.")); } setBusy(false); setPlan(r.data); setAnswers({}); };
    // `given` is one detail ("Save & next") or all typed answers; only what was
    // sent is cleared, so a detail typed elsewhere is not lost.
    const answerPlan = async (given = answers) => { setBusy(true); setIssue(null); const r = await answerDraftPlanV2(plan.id, { expectedVersion: plan.version, answers: given }); if (r.error) { const latest = await getDraftPlanV2(plan.id); if (latest.data) setPlan(latest.data); setBusy(false); setIssue(messageOf(r.error, "Could not save those answers.")); return false; } setBusy(false); setPlan(r.data); setAnswers(a => Object.fromEntries(Object.entries(a).filter(([k]) => !(k in given)))); return true; };
    const confirmPlan = async skipMissing => { setBusy(true); setIssue(null); const r = await confirmDraftPlanV2(plan.id, { expectedVersion: plan.version, skipMissing }); if (r.error) { const latest = await getDraftPlanV2(plan.id); if (latest.data) setPlan(latest.data); setBusy(false); return setIssue(messageOf(r.error, "Could not confirm the plan.")); } setBusy(false); setPlan(r.data); };
    const generatePlan = async freshKey => {
        if (freshKey || !generationKey.current) generationKey.current = idempotencyKey();
        // Kept before the request: a reload mid-generation resumes this key.
        planStore.set(GEN_KEY_PREFIX + plan.id, generationKey.current);
        setBusy(true); setIssue(null);
        const r = await generateDraftPlanV2(plan.id, { expectedVersion: plan.version }, generationKey.current);
        if (r.error) {
            const latest = await getDraftPlanV2(plan.id); if (latest.data) setPlan(latest.data);
            setBusy(false);
            setIssue(r.error?.code === "generation_in_progress"
                ? "This document is still being generated from another attempt. Try again in a few minutes."
                : messageOf(r.error, "Document generation failed."));
            return;
        }
        planStore.drop(GEN_KEY_PREFIX + plan.id); planStore.drop(PLAN_KEY);
        generationKey.current = null; setPlan(r.data); await loadWorkspace(r.data.generation.document_id); docs.reload();
    };
    const openDoc = async row => { setOpeningId(row.id); const ok = await loadWorkspace(row.id); setOpeningId(null); if (ok === false) toast.show("Could not open that document.", "danger", 3000); };
    const save = async (nextField = null) => {
        if (!workspace || locked || busy) return false;
        const payload = { ...editingPayload, title: workspace.title, expectedRevisionId: workspace.base_revision_id, expectedVersion: workspace.base_version, expectedContentEpoch: workspace.content_epoch };
        const fingerprint = JSON.stringify(payload); if (saveIntent.current?.fingerprint !== fingerprint) saveIntent.current = { fingerprint, key: idempotencyKey() };
        setBusy(true); setIssue(null); const r = await saveDocumentWorkspaceV2(workspace.document_id, payload, saveIntent.current.key);
        if (r.error) {
            // A failed render is final under its key; replaying it fails again.
            if (r.error?.code === "generation_failed") saveIntent.current = null;
            setBusy(false); setIssue(messageOf(r.error, "Could not save this revision.")); return false;
        }
        saveIntent.current = null;
        const loaded = await loadWorkspace(workspace.document_id);
        if (loaded) {
            if (nextField) setActiveField(nextField);
            setSavedAt(Date.now()); docs.reload(); toast.show("A new document revision was saved.", "success", 3000);
        }
        return loaded;
    };
    const askAi = async () => {
        if (!instruction.trim() || !workspace || locked) return;
        setBusy(true); setIssue(null); setProposal(null);
        const r = await assistDocumentWorkspaceV2(workspace.document_id, { ...editingPayload, instruction: instruction.trim(), expectedRevisionId: workspace.base_revision_id, expectedVersion: workspace.base_version, expectedContentEpoch: workspace.content_epoch });
        setBusy(false); if (r.error) { setIssue(messageOf(r.error, "AI Assist could not prepare a proposal.")); return false; }
        setProposal(r.data); return true;
    };
    const applyProposal = () => { if (!proposal) return; setContent(isText ? { body_html: proposal.body_html } : { fields: { ...(proposal.fields || {}) } }); setProposal(null); setInstruction(""); saveIntent.current = null; };

    // While the document is with the lawyer, look for their decision now and
    // then, so the banner changes when they answer -- no reload needed.
    useEffect(() => {
        if (!workspace || detail?.review_status !== "submitted") return undefined;
        const docId = workspace.document_id;
        const timer = setInterval(async () => {
            const r = await getDocumentV2(docId);
            if (r?.data && r.data.review_status !== "submitted") setDetail(r.data);
        }, 15000);
        return () => clearInterval(timer);
    }, [workspace, detail?.review_status]);

    // The text view follows the details as they are typed: the server composes
    // the template's own wording for them. Nothing is saved by this.
    useEffect(() => {
        const fields = content?.fields;
        if (!workspace?.text_editable || textEdit || !fields
            || JSON.stringify(fields) === JSON.stringify(workspace.fields || {})) { setLiveText(null); return undefined; }
        let live = true;
        const timer = setTimeout(async () => {
            const r = await previewDocumentTextV2(workspace.document_id, fields);
            if (live && r?.data?.text_html) setLiveText(r.data.text_html);
        }, 400);
        return () => { live = false; clearTimeout(timer); };
    }, [content, workspace, textEdit]);
    // "Send to lawyer" opens the send panel beside the document.
    const sendForReview = () => { setSendIssue(null); setSentInfo(null); setPanel("send"); };
    // Another document opened: its own screen, not the last one's "Sent".
    useEffect(() => { setSentInfo(null); }, [workspace?.document_id]);
    useEffect(() => {
        if (panel !== "send" || lawyers !== null) return undefined;
        let live = true;
        // A document goes to a lawyer only through an ACCEPTED engagement
        // (D1): the choice is the client's engaged lawyers, never the directory.
        listEngagements({ status: "accepted" }).then(({ data }) => {
            if (!live) return;
            const items = Array.isArray(data) ? data : (data?.items || []);
            const byLawyer = new Map();
            for (const e of items) {
                if (!e?.lawyer_id) continue;
                if (!byLawyer.has(e.lawyer_id)) {
                    byLawyer.set(e.lawyer_id, { id: e.lawyer_id, name: e.lawyer_name || "Your lawyer", sub: e.case_title ? `Engaged on: ${e.case_title}` : "Engaged lawyer", caseIds: [] });
                }
                // The cases each lawyer is engaged on (see shownLawyers).
                if (e.case_id) byLawyer.get(e.lawyer_id).caseIds.push(e.case_id);
            }
            setLawyers([...byLawyer.values()]);
        }).catch(() => { if (live) setLawyers([]); });
        return () => { live = false; };
    }, [panel, lawyers]);
    useEffect(() => {
        if (panel !== "send" || reviewers !== null) return undefined;
        let live = true;
        Promise.resolve(listQuickReviewers()).then(({ data } = {}) => {
            if (!live) return;
            const items = Array.isArray(data) ? data : (data?.items || []);
            setReviewers(items.filter(r => r?.id).map(r => {
                const specs = (r.specializations || []).map(x => x.charAt(0).toUpperCase() + x.slice(1).replace(/_/g, " "));
                const prov = String(r.province || "");
                return { id: r.id, name: r.full_name || "Lawyer", spec: specs.slice(0, 2).join(", ") || "General practice",
                    place: prov === "kpk" ? "KPK" : prov ? prov.charAt(0).toUpperCase() + prov.slice(1) : "", exp: r.experience_years || 0,
                    rating: r.rating || 0, reviews: r.total_reviews || 0, fee: r.fee_pkr, hours: r.turnaround_hours || 24 };
            }));
        }).catch(() => { if (live) setReviewers([]); });
        return () => { live = false; };
    }, [panel, reviewers]);
    // This document's quick-review requests: when it opens, and on the send page.
    const loadQuickReqs = useCallback(async docId => {
        const r = await Promise.resolve(myQuickReviews(docId)).catch(() => null);
        if (!r || r.error) return null;
        const items = Array.isArray(r.data) ? r.data : (r.data?.items || []);
        setQuickReqs({ docId, items });
        return items;
    }, []);
    useEffect(() => { setQrAsk(null); if (workspace?.document_id) loadQuickReqs(workspace.document_id); }, [workspace?.document_id, loadQuickReqs]);
    useEffect(() => { if (panel === "send" && workspace?.document_id) loadQuickReqs(workspace.document_id); }, [panel]); // eslint-disable-line react-hooks/exhaustive-deps
    // While a request waits, look for the lawyer's answer now and then. Once it
    // is accepted the document is with them: back to it, showing that.
    useEffect(() => {
        const docId = workspace?.document_id;
        const items = quickReqs && quickReqs.docId === docId ? quickReqs.items : null;
        if (!docId || !(items || []).some(r => r.status === "requested")) return undefined;
        const timer = setInterval(async () => {
            const now = await loadQuickReqs(docId);
            if (now && !now.some(r => r.status === "requested") && now[0]?.status === "accepted") {
                setPanel(null); loadWorkspace(docId);
            }
        }, 20000);
        return () => clearInterval(timer);
    }, [workspace?.document_id, quickReqs, loadQuickReqs, loadWorkspace]);
    // Preselect only a lawyer the server will accept: the one lawyer engaged on
    // this document's case. A case's `lawyer_id` alone is not that (it can be
    // missing or stale), and a caseless document leaves the choice to the client.
    useEffect(() => {
        const docCase = detail?.case_id || null;
        if (!docCase || !Array.isArray(lawyers)) return;
        const onCase = lawyers.filter(l => l.caseIds.includes(docCase));
        if (onCase.length === 1) setSendForm(f => ({ ...f, lawyerId: onCase[0].id }));
    }, [detail?.case_id, lawyers]);
    const submitForReview = async (retry = false) => {
        const rev = detail?.current_revision;
        if (!workspace || !rev?.revision_id || !sendForm.lawyerId || !sendForm.confirmed || sending) return;
        const body = { expectedVersion: detail.current_version, expectedPdfSha256: rev.pdf_sha256,
            lawyerId: sendForm.lawyerId, urgency: sendForm.urgency, note: sendForm.note.trim() || null };
        // One key per intent: a retry of THIS send reuses it; a changed send is new.
        const fingerprint = JSON.stringify(body);
        if (!retry || submitKey.current?.fingerprint !== fingerprint) submitKey.current = { fingerprint, key: idempotencyKey() };
        setSending(true); setSendIssue(null);
        const { error, status } = await submitDocumentV2(workspace.document_id, body, submitKey.current.key);
        setSending(false);
        if (error) {
            // The document moved under the user (a save in another tab): never
            // reported as sent -- they would wait for a reply nobody is writing.
            if (status === 409) return setSendIssue({ message: "This document changed after you opened it. Reload it, check it, then send again.", retryable: false });
            return setSendIssue({ message: messageOf(error, "The document could not be sent."), retryable: isRetryable(status, error) });
        }
        submitKey.current = null;
        const to = (lawyers || []).find(l => l.id === sendForm.lawyerId);
        setSentInfo({ lawyer: to?.name || "your lawyer", version: detail.current_version, urgency: sendForm.urgency });
        setPanel(null); setSendForm(f => ({ ...f, note: "", confirmed: false }));
        toast.show("Sent. Your lawyer has been notified.", "success", 3500);
        await loadWorkspace(workspace.document_id); docs.reload();
    };
    const requestReview = async () => {
        const rev = detail?.current_revision, to = qrAsk;
        if (!workspace || !to || !rev?.revision_id || !qrForm.confirmed || qrBusy || locked) return;
        setQrBusy(true); setQrIssue(null);
        const { data, error } = await requestQuickReview({ doc_id: workspace.document_id, lawyer_id: to.id,
            expected_version: detail.current_version, expected_pdf_sha256: rev.pdf_sha256, note: qrForm.note.trim() || null }) || {};
        setQrBusy(false);
        if (error || !data) return setQrIssue(messageOf(error, "The request could not be sent."));
        setQrAsk(null); setQrForm({ note: "", confirmed: false });
        setQuickReqs(cur => ({ docId: workspace.document_id, items: [data, ...(cur?.docId === workspace.document_id ? cur.items : [])] }));
        toast.show(`Request sent to ${to.name}.`, "success", 3500);
    };
    // Withdraw a waiting request; the list comes back to choose someone else.
    const cancelRequest = async req => {
        const { error } = await cancelQuickReview(req.id) || {};
        if (error) toast.show(messageOf(error, "The request could not be withdrawn."), "danger", 4000);
        else toast.show("Request withdrawn — nothing was shared.", "success", 3000);
        await loadQuickReqs(workspace.document_id);
    };
    const withdrawFromReview = async () => {
        if (!workspace || detail?.review_status !== "submitted") return;
        if (!withdrawKey.current) withdrawKey.current = idempotencyKey();
        setBusy(true);
        const { error, status } = await withdrawDocumentV2(workspace.document_id, withdrawKey.current);
        setBusy(false);
        if (error) {
            if (status === 404 && errorCode(error) === "feature_disabled") return toast.show("This document was sent the old way and cannot be withdrawn — ask your lawyer to return it.", "warn", 5000);
            if (status === 409) { withdrawKey.current = null; toast.show("Your lawyer has already responded — it can no longer be withdrawn.", "warn", 4500); return loadWorkspace(workspace.document_id); }
            return toast.show(messageOf(error, "The document could not be withdrawn."), "danger", 4000);
        }
        withdrawKey.current = null;
        toast.show("Withdrawn — the document is yours to edit again.", "success", 3500);
        await loadWorkspace(workspace.document_id); docs.reload();
    };
    /* Show one revision from the Versions tab. The current one returns to the
     * live preview; an older one is fetched by its own id and hash, so the bytes
     * on screen are exactly that version's. */
    const showVersion = async rev => {
        if (!workspace || rev.revision_id === revision?.revision_id) { setViewRev(null); return; }
        const token = loadToken.current;
        const shown = await previewRevisionV2(workspace.document_id, rev.revision_id, { expectedPdfSha256: rev.pdf_sha256 });
        // Another document was opened meanwhile: this URL is no one's to show.
        if (token !== loadToken.current) { if (shown.data?.url) URL.revokeObjectURL(shown.data.url); return; }
        if (!shown.data) { setIssue(messageOf(shown.error, "That version could not be shown.")); return; }
        setViewRev({ revision_id: rev.revision_id, version: rev.version, url: shown.data.url });
    };
    // From a row's ⋮ menu: a saved document's current PDF, or one version's.
    const downloadRow = async row => {
        const a = rowActions(row);
        const done = await downloadDocumentFile(row.id, `${row.title || "document"}.pdf`, { revisionId: a.revisionId, expectedPdfSha256: a.pdfSha256 });
        if (done?.error) toast.show(`Download failed: ${done.error}`, "danger", 4000);
    };
    const downloadVersion = async rev => {
        const done = await downloadDocumentFile(workspace.document_id, `${workspace.title || "document"} v${rev.version}.pdf`,
            { revisionId: rev.revision_id, expectedPdfSha256: rev.pdf_sha256 });
        if (done?.error) toast.show(`Download failed: ${done.error}`, "danger", 4000);
    };
    const download = async () => { const r = detail?.current_revision; const done = await downloadDocumentFile(workspace.document_id, `${workspace.title || "document"}.pdf`, { revisionId: r?.revision_id, expectedPdfSha256: r?.pdf_sha256 }); if (done?.error) setIssue(done.error); };
    const reset = () => { loadToken.current += 1; unlinkOpenDocument(); if (plan?.id) { planStore.drop(PLAN_KEY); planStore.drop(GEN_KEY_PREFIX + plan.id); } setPlan(null); setWorkspace(null); setDetail(null); setContent(null); setIssue(null); setProposal(null); setPreviewUrl(null); setSavedAt(null); setViewRev(null); setSideTab("saved"); createIntent.current = null; generationKey.current = null; saveIntent.current = null; };

    // ── styles shared by the screens ─────────────────────────────────────────
    const darker = t.mode === "dark" ? "rgba(0,0,0,0.22)" : "rgba(26,46,53,0.05)";
    // The app-wide scrollbar is a thick teal bar; inside these panes it read as
    // a stray stripe through the design. Thin and quiet here only.
    const thinScroll = { scrollbarWidth: "thin", scrollbarColor: `${t.border} transparent` };
    // LawBot-style history cards: the open draft is a tinted, outlined card.
    const hist = selected => ({
        display: "block", width: "100%", textAlign: "left", padding: "12px 14px", borderRadius: 12, cursor: "pointer",
        color: t.text, background: selected ? `${t.primary}1f` : "transparent",
        border: `1px solid ${selected ? `${t.primary}66` : "transparent"}`,
    });

    // ── the history column (start screen and workspace alike) ────────────────
    //
    // The Document Analyzer's sidebar, for drafting (2026-10-08): an "AI Draft"
    // button that starts a new draft, then History -- collapsible, with a ⋯
    // menu -- grouped by day. With a document open the heading becomes its two
    // options, Versions | Saved, in the same style.
    // A round button on the column's edge hides and shows the whole column.
    const groups = groupByDate(docs.items);
    const chevron = (open, closedTurn) => (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
            style={{ transform: open ? "none" : closedTurn, transition: "transform .2s" }}><path d="M6 9l6 6 6-6" /></svg>
    );
    const versionsOf = () => (
        <div data-versions>
            <RevisionHistory docId={workspace.document_id} t={t} alwaysShow
                reloadKey={revision?.revision_id} currentRevisionId={viewRev?.revision_id || revision?.revision_id}
                onPreview={showVersion}
                renderRow={(rev, { isCurrent, failed, verdict }) => {
                    const latest = rev.revision_id === revision?.revision_id;
                    return <SideRow key={rev.revision_id} t={t} selected={isCurrent} disabled={failed}
                        dataAttrs={{ "data-version": rev.version }}
                        title={`Version ${rev.version}${latest ? " · Current" : ""}`}
                        note={failed ? verdict : null}
                        hint={failed ? null : `Saved ${editedLabel(rev.created_at)}`}
                        onOpen={() => showVersion(rev)}
                        menu={<RowMenu t={t} label={`More actions for version ${rev.version}`} items={[
                            { label: "View", icon: "eye", onSelect: () => showVersion(rev), disabled: failed },
                            { label: "Download PDF", icon: "download", disabled: failed, onSelect: () => downloadVersion(rev) },
                        ]} />} />;
                }} />
        </div>
    );
    const showVersions = Boolean(workspace) && sideTab === "versions";
    // The two options as pills, in the AI Draft button's place and style:
    // the chosen one green, the other an outline.
    const sideTabBtn = (id, icon, label) => (
        <button key={id} type="button" role="tab" className="ds-tab" data-side-tab={id} aria-selected={sideTab === id} onClick={() => setSideTab(id)}>
            <LIcon name={icon} size={13} />{label}
        </button>
    );
    const docRow = row => {
        const status = documentStatusView(row);
        const tone = SEVERITY[STATUS_TONE[status.tone] || "muted"];
        const isDraft = /^draft$/i.test(status.label || "");
        const can = rowActions(row);
        const open = workspace?.document_id === row.id;
        return (
            <React.Fragment key={row.id}>
                <SideRow t={t} selected={open} disabled={openingId === row.id}
                    dataAttrs={{ "data-doc": row.id, title: titleByType[row.template_type] || (row.template_type ? humanise(row.template_type) : undefined) }}
                    title={row.title || "Untitled document"}
                    // Only a status that matters is shown; SEVERITY.fg suits dark backgrounds only.
                    note={openingId === row.id ? "Opening…"
                        : !isDraft ? <span data-doc-status style={{ color: t.mode === "dark" ? tone.fg : t.text, fontWeight: 600 }}>{status.label}</span> : null}
                    hint={`Edited ${editedLabel(row.updated_at || row.created_at)}`}
                    onOpen={() => openDoc(row)}
                    menu={<RowMenu t={t} label={`More actions for ${row.title || "document"}`} items={[
                        { label: "Open", icon: "eye", onSelect: () => openDoc(row) },
                        { label: "Download PDF", icon: "download", disabled: !can.canDownload, title: can.canDownload ? undefined : can.reason,
                          onSelect: () => downloadRow(row) },
                        { label: "Delete", icon: "trash", danger: true, onSelect: () => setDeleting(row) },
                    ]} />} />
            </React.Fragment>
        );
    };
    // The small round edge button (lawyer AI's .ai-edge): it sits on the column's
    // border while open, and at the screen's left edge while the column is hidden.
    const edgeIcon = d => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>;
    const historyColumn = sideCollapsed ? (
        <div data-drafts-edge style={{ position: "relative", flex: "0 0 0px" }}>
            <style>{SIDE_ROW_CSS}</style>
            <button type="button" className="ds-edge" onClick={() => setSideCollapsed(false)} aria-label="Show history" title="Show history"
                style={{ left: 10 }}>{edgeIcon("M9 6l6 6-6 6")}</button>
        </div>
    ) : (
        <aside data-drafts-side aria-label="Draft history" style={{ ...L.col("0 0 206px"), position: "relative", display: "flex", flexDirection: "column", minHeight: 0 }}>
            <style>{SIDE_ROW_CSS}</style>
            <div className="ds-top">
                {workspace ? (
                    <div role="tablist" aria-label="Document sidebar" style={{ display: "flex", gap: 6 }}>
                        {sideTabBtn("versions", "history", "Versions")}
                        {sideTabBtn("saved", "bookmark", "Saved")}
                    </div>
                ) : (
                <button type="button" className="ds-new" data-ai-draft onClick={reset} title="Start a new AI draft">
                    <LIcon name="fileText" size={15} /> AI Draft
                </button>
                )}
            </div>
            <div className="ds-head">
                <span data-side-heading>{!workspace ? "History" : showVersions ? "Versions" : "Saved"}</span>
                <button type="button" className="ds-icon" onClick={() => setHistoryOpen(o => !o)} aria-expanded={historyOpen} aria-label={historyOpen ? "Collapse list" : "Expand list"}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
                        style={{ transform: historyOpen ? "none" : "rotate(180deg)", transition: "transform .2s" }}><path d="M6 15l6-6 6 6" /></svg>
                </button>
                {/* The ⋯ menu: the full list lives in the Vault. (Nothing here
                    deletes documents in bulk -- they are records, not a cache.) */}
                <RowMenu t={t} label="History options" icon="moreHorizontal" trigger="ds-icon" items={[
                    { label: "Open Vault", icon: "fileText", onSelect: () => onOpenView?.("vault") },
                    { label: "Refresh", icon: "history", onSelect: () => docs.reload() },
                ]} />
            </div>
            <div data-lenis-prevent className="ds-list">
                {historyOpen && showVersions && <>
                    {versionsOf()}
                    <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.5, margin: "12px 8px 0" }}>
                        Every save makes a new version. Editing always continues from the current one.
                    </div>
                </>}
                {historyOpen && !showVersions && <>
                    {groups.map(([name, rows]) => {
                        const closed = closedGroups[name];
                        return (
                            <div key={name} data-history-group={name}>
                                <button type="button" className="ds-g" onClick={() => setClosedGroups(g => ({ ...g, [name]: !g[name] }))} aria-expanded={!closed}>
                                    {name}{chevron(!closed, "rotate(-90deg)")}
                                </button>
                                {!closed && rows.map(docRow)}
                            </div>
                        );
                    })}
                    {docs.error && <div style={{ fontSize: 12.5, color: t.warn, padding: 8 }}>{docs.unavailable ? DOCUMENTS_UNAVAILABLE : <>Could not load your documents. <button type="button" onClick={docs.reload} style={{ background: "none", border: "none", color: t.primary, cursor: "pointer", padding: 0, fontSize: 12.5 }}>Try again</button></>}</div>}
                    {!docs.loaded && !docs.error && <div style={{ fontSize: 12.5, color: t.textMuted, padding: 8 }}>Loading your documents…</div>}
                    {docs.isEmpty && <div style={{ fontSize: 13, color: t.textMuted, padding: 8 }}>No documents yet. Describe one to start.</div>}
                    {docs.hasMore && <button type="button" onClick={docs.loadMore} style={{ ...hist(false), textAlign: "center", color: t.primary, fontSize: 13 }}>Load more</button>}
                </>}
            </div>
            {/* The footer, as the lawyer AI's: who sees these, and how many. */}
            <div className="ds-foot" data-side-foot>
                <span>Drafts are private to you</span>
                {docs.loaded && <span>{docs.items.length}{docs.hasMore ? "+" : ""} draft{docs.items.length === 1 && !docs.hasMore ? "" : "s"}</span>}
            </div>
            <button type="button" className="ds-edge" onClick={() => setSideCollapsed(true)} aria-label="Hide history" title="Hide history"
                style={{ right: -16 }}>{edgeIcon("M15 6l-6 6 6 6")}</button>
            {deleting && <DeleteDocumentDialog row={deleting} onClose={() => setDeleting(null)}
                onDeleted={() => {
                    const wasOpen = workspace?.document_id === deleting.id;
                    setDeleting(null);
                    if (wasOpen) reset();
                    docs.reload();
                    toast.show("Moved to Recently deleted in your Vault. You can restore it from there.", "success", 3500);
                }} />}
        </aside>
    );

    // No "← Drafts" top bar (removed at the user's request, 2026-10-07): in the
    // workspace the way back and the document's title sit in the toolbar.

    // ── the draft plan, in the editor layout ─────────────────────────────────
    if (plan && !workspace) {
        return <div data-drafts-font style={{ ...L.root, background: t.bg, color: t.text }}>
            {draftsFont}
            <div style={L.row}>
                {historyColumn}
                <DraftPlan plan={plan} spec={(templates || []).find(s => s.template_type === plan.template_type)} L={L}
                    answers={answers} setAnswers={setAnswers} busy={busy} issue={issue} onAnswer={answerPlan}
                    onConfirm={confirmPlan} onGenerate={generatePlan} onBack={reset}
                    typeOptions={promptTemplateOptions(templates)} onChangeType={changeType} />
            </div>
        </div>;
    }

    // ── the document workspace ───────────────────────────────────────────────
    if (workspace) {
        const fields = content?.fields || {};
        const structured = workspace.source === "structured_fields";
        // Read as text: a free draft, or a template that has a text view.
        const textView = !structured || Boolean(workspace.text_editable);
        // Details are filled through the template's fields until its text is edited.
        const fieldsMode = structured && !textEdit;
        // A detail never answered is not among the stored fields at all, but the
        // template's text still shows it as `[[FIELD]]`: it is a blank too.
        const textBlanks = fieldsMode && textView
            ? placeholderTokens(liveText || workspace.text_html).map(name => name.toLowerCase()) : [];
        const keys = [...new Set([...placeholderFields(fields), ...textBlanks])];
        const counts = placeholderCounts(fields, {}, keys);
        const unfilled = counts.total - counts.filled;
        const tokens = isText ? placeholderTokens(content?.body_html) : [];
        const blanks = fieldsMode ? unfilled : tokens.length;
        const checks = workspaceChecks(revision, { unfilled: blanks, structured: structured || tokens.length > 0,
            edited: revision?.template_type === "edited_document" });
        // Light, LawBot-like toolbar buttons: line icon + label, no heavy boxes.
        // Compact (2026-10-10) so the whole set fits on one line.
        const tb = (on = false) => ({
            display: "inline-flex", alignItems: "center", gap: 6, minHeight: 34, padding: "0 9px", borderRadius: 9, flexShrink: 0,
            // Pill, hover, pressed (aria-pressed) and the click ripple: WORKSPACE_CSS .ws-tools-row.
            border: "1px solid transparent", background: "transparent",
            color: t.text, fontSize: 13, fontWeight: on ? 650 : 500, cursor: "pointer", whiteSpace: "nowrap", fontFamily: "inherit",
        });
        const soon = <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".03em", padding: "1px 6px", borderRadius: 999, background: t.chipBg || t.inputBg, color: t.textMuted }}>Soon</span>;
        const count = tone => ({ fontSize: 11.5, fontWeight: 600, padding: "1px 7px", borderRadius: 999,
            background: tone === "warn" ? `${t.warn}2b` : tone === "ok" ? `${t.success}26` : t.chipBg || t.inputBg,
            color: tone === "warn" ? t.warn : tone === "ok" ? t.success : t.textMuted });
        const openFill = (field = null) => {
            setPanel("fill");
            if (!fieldsMode) { if (field) setActiveField(field); return; }
            setEditMode(true);
            setActiveField(field || activeField || keys.find(k => !String(fields[k] ?? "").trim()) || keys[0] || null);
        };
        // Edit on a template with a text view: edit its WORDS. The text starts
        // as the template composes it for the details as they stand.
        const startTextEdit = () => {
            setContent({ body_html: liveText || workspace.text_html || "" });
            setTextEdit(true); setEditMode(true); setTokenDraft({});
            undoStack.current = { items: [], last: null }; saveIntent.current = null; setSavedAt(null);
        };
        const fillToken = name => {
            const value = String(tokenDraft[name] ?? "").trim();
            if (!value) return;
            setContent({ body_html: fillPlaceholder(content?.body_html, name, value) });
            setTokenDraft(d => { const next = { ...d }; delete next[name]; return next; });
            setSavedAt(null); saveIntent.current = null;
        };
        const currentField = keys.includes(activeField) ? activeField : (keys.find(k => !String(fields[k] ?? "").trim()) || keys[0]);
        const dirty = textEdit
            ? (content?.body_html || "") !== (workspace.text_html || "")
            : structured
            ? JSON.stringify(fields) !== JSON.stringify(workspace.fields || {})
            : (content?.body_html || "") !== (workspace.body_html || "");
        const editField = (name, value) => {
            if (undoStack.current.last !== name) { undoStack.current.items.push(content); undoStack.current.last = name; }
            setContent({ fields: { ...fields, [name]: value } }); setSavedAt(null); saveIntent.current = null;
        };
        const undo = () => {
            const prev = undoStack.current.items.pop();
            undoStack.current.last = null;
            if (prev) { setContent(prev); setSavedAt(null); saveIntent.current = null; }
        };

        // Where the document stands with the lawyer, in words, with their note.
        const reviewBanner = doc => {
            const status = doc?.review_status;
            const view = documentStatusView(doc || {});
            // review_note is the LAWYER's note, once they decide. Before that a
            // document submitted before client_note existed still holds the
            // client's own note there, which must not read as the lawyer's reply.
            const note = ["returned", "rejected", "approved"].includes(status) ? String(doc?.review_note || "").trim() : "";
            const B = {
                submitted: { tone: t.info, icon: "lock", title: "With your lawyer for review",
                    text: `Frozen for lawyer review — editing is off until the lawyer responds.${doc?.submitted_at ? ` Sent ${editedLabel(doc.submitted_at)}.` : ""}` },
                returned: { tone: t.warn, icon: "undo", title: "Your lawyer requested changes",
                    text: "Make the changes, save, then send it again." },
                rejected: { tone: t.danger, icon: "x", title: "Your lawyer rejected this document",
                    text: "You can still edit it and send it again, or start a new draft." },
                approved: { tone: t.success, icon: "checkCircle", title: "Approved by your lawyer",
                    text: "Any edit makes a new version, which would need a new approval." },
            }[status] || (view.isRecovery ? { tone: t.warn, icon: "alertCircle", title: view.headline, text: view.explanation } : null);
            if (!B) return null;
            return (
                <div data-review-banner={status} role="note" style={{ margin: "10px 18px 0", padding: "10px 14px", borderRadius: 12, display: "flex", gap: 11, alignItems: "flex-start",
                    background: `${B.tone}14`, border: `1px solid ${B.tone}55`, color: t.text, fontSize: 13, lineHeight: 1.5 }}>
                    <span style={{ color: B.tone, marginTop: 1 }}><LIcon name={B.icon} size={17} /></span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <strong style={{ display: "block", color: B.tone, fontSize: 13.5 }}>{B.title}</strong>
                        {note && <div data-review-note style={{ margin: "4px 0", padding: "6px 10px", borderLeft: `3px solid ${B.tone}`, background: t.card, borderRadius: 6, whiteSpace: "pre-wrap" }}>“{note}”</div>}
                        <span style={{ color: t.textMuted }}>{B.text}</span>
                    </div>
                    {status === "submitted" && <Btn onClick={withdrawFromReview} disabled={busy} data-withdraw style={{ minHeight: 32, fontSize: 12.5, flexShrink: 0 }}>Withdraw</Btn>}
                </div>
            );
        };
        const togglePanel = name => {
            if (panel === name) { setPanel(null); if (name === "fill" && fieldsMode) setEditMode(false); return; }
            if (name === "fill") openFill(); else { setPanel(name); if (fieldsMode) setEditMode(false); }
        };
        const onEdit = () => {
            if (!textView) return togglePanel("fill");
            if (structured && !textEdit) return startTextEdit();
            return setEditMode(m => !m);
        };
        const closeBtn = <button type="button" aria-label="Close panel" title="Close" onClick={() => { setPanel(null); setEditMode(false); }}
            style={{ width: 30, height: 30, borderRadius: 8, border: "none", background: "transparent", color: t.textMuted, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}><LIcon name="x" size={16} /></button>;
        const panelHead = (icon, title, sub) => (
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 10px 10px 14px", borderBottom: `1px solid ${t.border}` }}>
                <span aria-hidden="true" style={{ width: 28, height: 28, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", background: `${t.primary}1f`, color: t.primary }}><LIcon name={icon} size={15} /></span>
                <div style={{ flex: 1, minWidth: 0 }}><strong style={{ display: "block", fontSize: 14, lineHeight: 1.3 }}>{title}</strong><span style={{ fontSize: 12, color: t.textMuted }}>{sub}</span></div>
                {closeBtn}
            </div>
        );

        // The details as ONE complete form, in a full-height side panel:
        // every placeholder visible at once, the document still in view beside it.
        // On the RIGHT, from the top of the page to the bottom.
        const fillOpen = panel === "fill" && (structured || isText);
        // The forms' compact controls: a panel beside the page, not a page.
        const compactField = extra => fieldStyle(t, { padding: "6px 10px", fontSize: 13.5, borderRadius: 8, lineHeight: 1.45, ...extra });
        const rowStyle = active => ({ padding: "6px 8px 8px", borderRadius: 10, border: `1px solid ${active ? `${t.primary}66` : "transparent"}`, background: active ? t.card : "transparent" });
        const labelStyle = { display: "flex", alignItems: "center", gap: 7, marginBottom: 4, fontSize: 12.5, fontWeight: 600, color: t.text };
        const dot = filled => <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: "50%", flexShrink: 0, border: `2px solid ${filled ? t.success : t.warn}`, background: filled ? t.success : "transparent" }} />;
        const listStyle = { flex: 1, overflowY: "auto", ...thinScroll, padding: "6px 8px 12px", display: "flex", flexDirection: "column", gap: 2 };
        const footStyle = { padding: "10px 14px", borderTop: `1px solid ${t.border}`, display: "flex", flexDirection: "column", gap: 6 };
        const formFields = showAllFields ? keys : keys.filter(k => !String(fields[k] ?? "").trim() || k === currentField);
        const tokenPanel = fillOpen && !fieldsMode && (
            <aside data-completion-panel data-fill-panel aria-label="Complete document"
                style={{ ...L.col("0 0 340px"), borderLeft: `1px solid ${t.border}`, background: t.surface, display: "flex", flexDirection: "column", minHeight: 0 }}>
                {panelHead("sliders", "Fill placeholders", tokens.length ? `${tokens.length} left in the text` : "None left in the text")}
                <div data-lenis-prevent style={listStyle}>
                    {!tokens.length && <div style={{ color: t.success, fontSize: 13, padding: 8 }}>Every placeholder in the text is filled.</div>}
                    {tokens.map(name => {
                        const active = name === activeField;
                        return (
                            <div key={name} data-token-row={name} data-active={active ? "true" : undefined} style={rowStyle(active)}>
                                <label htmlFor={`tok_${name}`} style={labelStyle}>
                                    {dot(false)}
                                    {humanise(name.toLowerCase())}
                                </label>
                                <div style={{ display: "flex", gap: 6 }}>
                                    <input id={`tok_${name}`} value={tokenDraft[name] ?? ""} disabled={locked} placeholder={`[[${name}]]`} autoFocus={active}
                                        onFocus={() => setActiveField(name)} onChange={e => setTokenDraft(d => ({ ...d, [name]: e.target.value }))}
                                        onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); fillToken(name); } }}
                                        style={compactField({ minHeight: 32 })} />
                                    <Btn kind="primary" onClick={() => fillToken(name)} disabled={locked || !String(tokenDraft[name] ?? "").trim()} style={{ minHeight: 32, padding: "0 12px", fontSize: 12.5, borderRadius: 8 }}>Fill</Btn>
                                </div>
                            </div>
                        );
                    })}
                </div>
                <div style={footStyle}>
                    <Btn kind="primary" onClick={() => save()} disabled={locked || busy || !dirty} style={{ width: "100%", minHeight: 36, fontSize: 13, borderRadius: 9 }}><LIcon name="save" size={15} />{busy && dirty ? "Saving…" : "Save all changes"}</Btn>
                    <div style={{ color: dirty ? t.warn : t.textMuted, fontSize: 11.5, textAlign: "center" }}>{dirty ? "Unsaved changes. Saving makes a new version." : "A placeholder left blank prints as it is shown."}</div>
                </div>
            </aside>
        );
        const fillPanel = fillOpen && fieldsMode ? (
            <aside data-completion-panel data-fill-panel aria-label="Complete document"
                style={{ ...L.col("0 0 340px"), borderLeft: `1px solid ${t.border}`, background: t.surface, display: "flex", flexDirection: "column", minHeight: 0 }}>
                {panelHead("sliders", "Fill placeholders", `${counts.filled} of ${counts.total} filled`)}
                <div style={{ padding: "8px 14px", display: "flex", flexDirection: "column", gap: 7, borderBottom: `1px solid ${t.border}` }}>
                    <div role="img" aria-label={`${counts.filled} of ${counts.total} details filled`} style={{ height: 4, borderRadius: 4, background: t.border, overflow: "hidden" }}>
                        <div style={{ height: "100%", width: `${counts.total ? (counts.filled / counts.total) * 100 : 100}%`, background: t.primary, borderRadius: 6, transition: "width .3s" }} />
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <div role="group" aria-label="Detail filter" style={{ display: "flex", padding: 2, border: `1px solid ${t.border}`, borderRadius: 8 }}>
                            {[[true, "All"], [false, "Empty"]].map(([all, label]) => <button key={label} type="button" aria-pressed={showAllFields === all} onClick={() => setShowAllFields(all)}
                                style={{ minHeight: 24, padding: "0 11px", border: "none", borderRadius: 6, background: showAllFields === all ? `${t.primary}25` : "transparent", color: t.text, fontSize: 12.5, fontWeight: 650, cursor: "pointer" }}>{label}</button>)}
                        </div>
                        <span style={{ marginLeft: "auto", fontSize: 12, color: unfilled ? t.warn : t.success }}><span data-placeholder-count>{unfilled}</span> empty</span>
                    </div>
                </div>
                <div data-lenis-prevent style={listStyle}>
                    {!keys.length && <div style={{ color: t.textMuted, fontSize: 13, padding: 8 }}>This document has no editable details.</div>}
                    {keys.length > 0 && !formFields.length && <div style={{ color: t.success, fontSize: 13, padding: 8 }}>Every detail is filled.</div>}
                    {formFields.map(name => {
                        const value = String(fields[name] ?? "");
                        const filled = Boolean(value.trim());
                        const active = name === currentField;
                        return (
                            <div key={name} data-field-row={name} data-active={active ? "true" : undefined} style={rowStyle(active)}>
                                <label htmlFor={`ph_${name}`} style={labelStyle}>
                                    {dot(filled)}
                                    {humanise(name)}
                                    {!filled && <span style={{ marginLeft: "auto", fontSize: 11, fontWeight: 600, color: t.warn }}>Empty</span>}
                                </label>
                                <textarea id={`ph_${name}`} value={value} disabled={locked} rows={value.length > 120 ? 4 : value.length > 45 ? 2 : 1}
                                    placeholder={tokenOf(name)} autoFocus={active && !filled}
                                    onFocus={() => { setFocus(name); setActiveField(name); }} onChange={e => editField(name, e.target.value)}
                                    style={compactField({ resize: "vertical", minHeight: 32, display: "block", border: `1px solid ${focus === name ? t.primary : t.inputBorder || t.border}` })} />
                            </div>
                        );
                    })}
                </div>
                <div style={footStyle}>
                    <Btn kind="primary" onClick={() => save()} disabled={locked || busy || !dirty} style={{ width: "100%", minHeight: 36, fontSize: 13, borderRadius: 9 }}><LIcon name="save" size={15} />{busy && dirty ? "Saving…" : "Save all changes"}</Btn>
                    <div style={{ color: dirty ? t.warn : t.textMuted, fontSize: 11.5, textAlign: "center" }}>{dirty ? (textView ? "Unsaved changes. The text shows them; saving makes a new version." : "Unsaved changes. The PDF updates after you save.") : "Empty details stay blank in the PDF. Saving makes a new version."}</div>
                </div>
            </aside>
        ) : tokenPanel;

        // The send panel: ready to send?, to whom, how soon, a note, and the
        // owner's confirmation that this is the version they mean.
        const toneMark = tone => (["success", "ok"].includes(tone) ? ["✓", t.success] : ["warn", "danger"].includes(tone) ? ["!", t.warn] : ["–", t.textMuted]);
        // The server's rule (document_sharing.py), and a case is OPTIONAL: no
        // case, any engaged lawyer; a case, only a lawyer engaged on that case.
        const docCaseId = detail?.case_id || null;
        const shownLawyers = docCaseId ? (lawyers || []).filter(l => l.caseIds.includes(docCaseId)) : (lawyers || []);
        const canSend = Boolean(revision?.revision_id && sendForm.lawyerId && sendForm.confirmed && !dirty && !locked && !sending);
        const sectionLabel = text => <div style={{ fontSize: 11.5, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: t.textMuted, margin: "4px 2px 8px" }}>{text}</div>;
        /* SEND FOR REVIEW, A PAGE OF ITS OWN (2026-10-11). It replaced a narrow
         * side panel. Laid out like a checkout: three steps on the left -- is it
         * ready, to whom, what you need -- and a summary on the right that holds
         * the confirmation and the Send button, so what is about to happen is
         * always in view. Same rules as before: only an engaged lawyer (a case's
         * document, only the lawyer on that case), the owner confirms the exact
         * version, and the guarded submit. */
        const URGENCIES = [["normal", "Normal", t.success], ["priority", "Priority", t.warn], ["urgent", "Urgent", t.danger]];
        const chosen = shownLawyers.find(l => l.id === sendForm.lawyerId) || null;
        const urg = URGENCIES.find(([v]) => v === sendForm.urgency) || URGENCIES[0];
        const readyRows = [{ key: "saved", label: `Saved as version ${workspace.base_version}`, value: dirty ? "Save your changes first" : "This is the version that is sent", tone: dirty ? "warn" : "ok" }, ...checks.rows];
        const attention = readyRows.filter(r => ["warn", "danger"].includes(r.tone));
        const initials = name => name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
        const blankRow = readyRows.find(r => r.key === "details" && ["warn", "danger"].includes(r.tone));
        const hasLawyer = shownLawyers.length > 0;
        const engagedIds = new Set((lawyers || []).map(l => l.id));
        const q = lawyerQuery.trim().toLowerCase();
        // An engaged lawyer is sent to directly, so is not offered a quick review.
        const others = (reviewers || []).filter(l => !engagedIds.has(l.id))
            .filter(l => !q || `${l.name} ${l.spec} ${l.place}`.toLowerCase().includes(q));
        const label = { fontSize: 12, fontWeight: 800, letterSpacing: ".08em", color: t.textMuted };
        const stat = { fontSize: 11, fontWeight: 800, letterSpacing: ".05em", color: t.textMuted };
        const pill = { height: 40, borderRadius: 999, fontFamily: "inherit", cursor: "pointer", fontSize: 13.5 };
        const clip = { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" };
        const rupees = n => (n == null ? "—" : `Rs ${Number(n).toLocaleString("en-PK")}`);
        const qrItems = quickReqs && quickReqs.docId === workspace.document_id ? quickReqs.items : null;
        const openReq = (qrItems || []).find(r => r.status === "requested") || null;
        // The newest request that ended without a review, said once above the list.
        const lastClosed = !openReq && ["declined", "expired", "stale"].includes(qrItems?.[0]?.status) ? qrItems[0] : null;
        const closedText = r => r.status === "declined"
            ? `${r.lawyer_name} could not take your last request. Nothing was shared or charged — choose another lawyer.`
            : r.status === "expired"
                ? `${r.lawyer_name} did not answer in time. Nothing was shared or charged — choose another lawyer.`
                : `You changed the document after asking ${r.lawyer_name}, so nothing was sent. Request a review of this version.`;
        const openRequestDialog = l => { setQrIssue(null); setQrForm({ note: "", confirmed: false }); setQrAsk(l); };
        /* A lawyer who reviews documents: one row, the terms in view, one action.
         * No hiring: the request is for this document only. */
        const reviewerRow = l => (
            <article key={l.id} data-reviewer={l.id} className="qr-row" data-selected={qrAsk?.id === l.id ? "" : undefined}
                onClick={() => { if (!dirty) openRequestDialog(l); }}
                style={{ "--qa": t.primary, "--qs": t.surface, "--qb": t.border, padding: "14px 18px", borderRadius: 18 }}>
                <span aria-hidden="true" className="qr-av" style={{ width: 52, height: 52, borderRadius: "50%", display: "grid", placeItems: "center", fontWeight: 800, fontSize: 16, background: `${t.primary}1f`, color: t.primary, boxShadow: `inset 0 0 0 1px ${t.primary}33` }}>{initials(l.name)}</span>
                <div className="qr-info" style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 3 }}>
                    <div style={{ fontSize: 16, fontWeight: 800, lineHeight: 1.25, ...clip }} title={l.name}>{l.name}</div>
                    <div style={{ fontSize: 13, color: t.textMuted, ...clip }}>{[l.spec, l.place].filter(Boolean).join(" · ")}</div>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 3 }}>
                        {l.exp > 0 && <span className="qr-chip">{l.exp} yrs experience</span>}
                        <span className="qr-chip">
                            {l.reviews ? <><span style={{ color: "#F2C35E" }}>★</span> {Number(l.rating).toFixed(1)} · {l.reviews} reviews</> : "New on AttorneyAI"}
                        </span>
                    </div>
                </div>
                <div className="qr-terms">
                    <div><b>{rupees(l.fee)}</b><span>review fee</span></div>
                    <i aria-hidden="true" />
                    <div><b>{l.hours} hrs</b><span>back in</span></div>
                </div>
                <button type="button" data-ask-review className="qr-ask" onClick={e => { e.stopPropagation(); openRequestDialog(l); }} disabled={dirty}
                    title={dirty ? "Save your changes first" : undefined}>
                    Request review<LIcon name="arrowRight" size={15} />
                </button>
            </article>
        );
        const reviewersSection = (
            <section aria-label="Lawyers who review documents" data-reviewers style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                    {hasLawyer && <div style={{ ...label, flex: 1 }}>OR GET A QUICK REVIEW FROM ANOTHER LAWYER</div>}
                    <label style={{ position: "relative", width: 280, maxWidth: "100%", height: 40, display: "flex", alignItems: "center", gap: 8, padding: "0 14px", borderRadius: 999, border: `1px solid ${t.border}`, background: t.surface }}>
                        <LIcon name="search" size={15} />
                        <span style={{ position: "absolute", left: -9999 }}>Search lawyers</span>
                        <input type="search" value={lawyerQuery} onChange={e => setLawyerQuery(e.target.value)} placeholder="Search by name, city or practice"
                            style={{ flex: 1, minWidth: 0, border: "none", outline: "none", background: "transparent", color: t.text, fontSize: 13.5, fontFamily: "inherit" }} />
                    </label>
                    {!hasLawyer && <span style={{ flex: 1 }} />}
                    {reviewers && reviewers.length > 0 && <span style={{ fontSize: 13, color: t.textMuted }}><b style={{ color: t.text }}>{others.length}</b> {others.length === 1 ? "lawyer reviews" : "lawyers review"} documents</span>}
                </div>
                {lastClosed && <div role="note" data-request-closed style={{ padding: "12px 16px", borderRadius: 14, border: `1px dashed ${t.danger}66`, fontSize: 13.5, color: t.text, lineHeight: 1.5 }}>{closedText(lastClosed)}</div>}
                {reviewers === null && <div style={{ fontSize: 13, color: t.textMuted }}>Finding lawyers…</div>}
                {reviewers && others.length === 0 && <div style={{ fontSize: 13.5, color: t.textMuted }}>{q ? "No lawyer matches that search." : "No lawyer is offering quick reviews right now. Book a consultation to hire one for your case."}</div>}
                {others.length > 0 && <div className="qr-list" style={{ display: "flex", flexDirection: "column", gap: 10 }}>{others.slice(0, 12).map(reviewerRow)}</div>}
            </section>
        );
        /* No lawyer yet: the document and how a quick review works on the left. */
        const docAside = (
            <aside data-send-doc-card style={{ position: "sticky", top: 0, display: "flex", flexDirection: "column", gap: 16, padding: 18, borderRadius: 20, border: `1px solid ${t.border}`, background: t.surface }}>
                <div aria-hidden="true" style={{ height: 200, borderRadius: 12, background: t.bg, display: "grid", placeItems: "center" }}>
                    <div style={{ width: 136, height: 176, borderRadius: 4, background: "#F2F4F3", padding: "16px 14px", boxSizing: "border-box", display: "flex", flexDirection: "column", gap: 6, boxShadow: "0 14px 30px -12px rgba(0,0,0,.7)" }}>
                        <span style={{ height: 7, width: "70%", alignSelf: "center", background: "#2b3a3e", borderRadius: 2, marginBottom: 6 }} />
                        {[100, 100, 60, 100, 85, 100, 45, 100, 75].map((w, i) => <span key={i} style={{ height: 4, width: `${w}%`, borderRadius: 2, background: blankRow && (i === 2 || i === 6) ? "#F2C35E" : "#c4cccd" }} />)}
                    </div>
                </div>
                <div>
                    <div style={{ fontSize: 17, fontWeight: 800, ...clip }}>{workspace.title || "Untitled document"}</div>
                    <div style={{ fontSize: 13, color: t.textMuted }}>Version {workspace.base_version}</div>
                </div>
                {blankRow && <button type="button" data-ready="details" onClick={() => { setPanel(null); openFill(); }}
                    style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: 12, border: "none", background: `${t.warn}1f`, color: t.warn, fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}>
                    <b style={{ fontSize: 15 }}>!</b><span style={{ flex: 1 }}>{blankRow.value}</span><span style={{ textDecoration: "underline" }}>Fill now</span></button>}
                {dirty && <div style={{ fontSize: 13, fontWeight: 800, color: t.warn }}>Save your changes first</div>}
                <div style={{ height: 1, background: t.border }} />
                <div data-no-engaged-lawyer role="note" style={{ fontSize: 13, color: t.textMuted, lineHeight: 1.5 }}>
                    {docCaseId && (lawyers || []).length ? "No lawyer is engaged on this document's case yet — ask one for a quick review." : "You have no lawyer engaged yet — ask one for a quick review, no meeting needed."}
                </div>
                <div style={label}>HOW IT WORKS</div>
                <ol aria-label="How it works" style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 12 }}>
                    {[["1", "Request a review", "They see only the title and your note."],
                      ["2", "They accept within 24 hours", "Otherwise it closes — nothing is shared or charged."],
                      ["3", "Approved, or back with edits", "You see every change they made."]].map(([n, title, sub], i) => (
                        <li key={n} style={{ display: "flex", gap: 10 }}>
                            <b style={{ width: 24, height: 24, flexShrink: 0, borderRadius: "50%", display: "grid", placeItems: "center", fontSize: 12, background: i === 0 ? t.primary : "transparent", color: i === 0 ? onPrimary(t) : t.textMuted, border: i === 0 ? "none" : `1.5px solid ${t.border}` }}>{n}</b>
                            <span><span style={{ display: "block", fontSize: 13.5, fontWeight: 800 }}>{title}</span><span style={{ display: "block", fontSize: 12.5, color: t.textMuted, lineHeight: 1.45 }}>{sub}</span></span>
                        </li>
                    ))}
                </ol>
                <div style={{ fontSize: 12.5, color: t.textMuted }}>Your draft stays saved — leave any time.</div>
            </aside>
        );
        /* A request is waiting: where it stands, and the ways out. */
        const askedLawyer = openReq ? (reviewers || []).find(l => l.id === openReq.lawyer_id) : null;
        const hoursLeft = openReq ? Math.max(0, Math.ceil((new Date(openReq.expires_at).getTime() - Date.now()) / 3600000)) : 0;
        const pendingView = openReq && (
            <div data-request-pending style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(300px,380px)", gap: 20, alignItems: "stretch" }}>
                <section aria-label="Progress" style={{ borderRadius: 20, border: `1px solid ${t.border}`, background: t.surface, padding: "24px 26px", display: "flex", flexDirection: "column", gap: 22 }}>
                    <div style={label}>WHAT HAPPENS NEXT</div>
                    <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 24 }}>
                        {[["✓", "Request sent", `${workspace.title || "Your document"}, version ${openReq.version}`, "done"],
                          ["2", `${openReq.lawyer_name} accepts`, `${hoursLeft} ${hoursLeft === 1 ? "hour" : "hours"} left. Until then they see only the title and your note.`, "now"],
                          ["3", "They review it", `Within ${openReq.turnaround_hours} hours of accepting.`, "later"],
                          ["4", "You get it back", "Approved — or returned with their edits, every change shown.", "later"]].map(([mark, title, sub, state]) => (
                            <li key={mark} style={{ display: "flex", gap: 14 }}>
                                <span aria-hidden="true" style={{ width: 30, height: 30, flexShrink: 0, borderRadius: "50%", display: "grid", placeItems: "center", fontSize: 13, fontWeight: 900,
                                    background: state === "done" ? t.primary : state === "now" ? t.warn : "transparent", color: state === "later" ? t.textMuted : "#06211a",
                                    border: state === "later" ? `1.5px solid ${t.border}` : "none" }}>{mark}</span>
                                <div><b style={{ fontSize: 15, color: state === "now" ? t.warn : state === "later" ? t.textMuted : t.text }}>{title}</b><div style={{ fontSize: 13, color: t.textMuted }}>{sub}</div></div>
                            </li>
                        ))}
                    </ol>
                    <span style={{ flex: 1 }} />
                    <div style={{ padding: "12px 16px", borderRadius: 14, border: `1px dashed ${t.danger}66`, fontSize: 13, color: t.textMuted, lineHeight: 1.5 }}>
                        <b style={{ color: t.danger }}>If they decline or don't answer in time</b> — nothing is shared or charged, and you can choose another lawyer.
                    </div>
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                        <Btn onClick={() => setPanel(null)} style={{ minHeight: 44, borderRadius: 999 }}>Back to the document</Btn>
                        <span style={{ flex: 1 }} />
                        <button type="button" data-request-cancel onClick={() => cancelRequest(openReq)}
                            style={{ height: 44, padding: "0 14px", border: "none", background: "transparent", color: t.danger, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>Cancel request</button>
                    </div>
                </section>
                <aside style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    <div style={{ borderRadius: 20, border: `1px solid ${t.border}`, background: t.surface, padding: 18, display: "flex", flexDirection: "column", gap: 14 }}>
                        <div style={label}>SENT TO</div>
                        <div style={{ display: "flex", gap: 12, alignItems: "center", minWidth: 0 }}>
                            <span aria-hidden="true" style={{ width: 52, height: 52, flexShrink: 0, borderRadius: "50%", display: "grid", placeItems: "center", fontWeight: 800, fontSize: 16, background: `${t.primary}22`, color: t.primary }}>{initials(openReq.lawyer_name || "L")}</span>
                            <div style={{ minWidth: 0 }}><b style={{ fontSize: 16 }}>{openReq.lawyer_name}</b>
                                {askedLawyer && <div style={{ fontSize: 12.5, color: t.textMuted, ...clip }}>{[askedLawyer.spec, askedLawyer.place, askedLawyer.exp ? `${askedLawyer.exp} yrs` : ""].filter(Boolean).join(" · ")}</div>}</div>
                        </div>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                            <div style={{ padding: "10px 12px", borderRadius: 12, background: t.bg }}><div style={stat}>FEE</div><b>{rupees(openReq.fee_pkr)}</b></div>
                            <div style={{ padding: "10px 12px", borderRadius: 12, background: t.bg }}><div style={stat}>BACK WITHIN</div><b>{openReq.turnaround_hours} hrs</b></div>
                        </div>
                        <button type="button" onClick={() => cancelRequest(openReq)}
                            style={{ ...pill, height: 42, border: `1px solid ${t.primary}`, background: `${t.primary}1a`, color: t.primary, fontWeight: 800 }}>Choose someone else instead</button>
                    </div>
                    <div style={{ flex: 1, borderRadius: 20, border: `1px solid ${t.border}`, background: t.surface, padding: 18, display: "flex", flexDirection: "column", gap: 12 }}>
                        <div style={label}>WHAT YOU SENT</div>
                        <div><b>{workspace.title || "Untitled document"}</b><div style={{ fontSize: 12.5, color: t.textMuted }}>Version {openReq.version}</div></div>
                        {openReq.note && <div style={{ padding: "12px 14px", borderRadius: 12, background: t.bg, fontSize: 13.5, lineHeight: 1.5 }}>“{openReq.note}”</div>}
                        <span style={{ flex: 1 }} />
                        {workspace.base_version !== openReq.version
                            ? <div role="alert" data-request-stale style={{ fontSize: 13, color: t.warn, lineHeight: 1.5 }}>You saved version {workspace.base_version} after asking. This request is for version {openReq.version} and will close if accepted — cancel it and ask again to send the new one.</div>
                            : <div style={{ fontSize: 12.5, color: t.textMuted, lineHeight: 1.5 }}>Saving changes makes a new version and closes this request — ask again after.</div>}
                    </div>
                </aside>
            </div>
        );
        /* Confirm a request: who, the exact version, the terms, a note. */
        const askDialog = qrAsk && (
            <div data-request-dialog role="dialog" aria-modal="true" aria-label={`Request a review from ${qrAsk.name}`}
                className="rq-veil" onClick={e => { if (e.target === e.currentTarget) setQrAsk(null); }}
                onKeyDown={e => { if (e.key === "Escape") setQrAsk(null); }}
                style={{ "--qa": t.primary, "--qs": t.surface, "--qb": t.border, "--qm": t.textMuted, "--qi": t.inputBg || t.bg }}>
                <div className="rq-card">
                    <header className="rq-head">
                        <span className="rq-av" aria-hidden="true">{initials(qrAsk.name)}</span>
                        <div style={{ minWidth: 0, flex: 1 }}>
                            <div className="rq-eyebrow">Request a document review</div>
                            <h2 className="rq-name">{qrAsk.name}</h2>
                            <div className="rq-meta">
                                {[qrAsk.spec, qrAsk.place, qrAsk.exp ? `${qrAsk.exp} yrs` : ""].filter(Boolean).join(" · ")}
                                {qrAsk.reviews > 0 && <> · <span style={{ color: "#F2C35E" }}>★</span> {Number(qrAsk.rating).toFixed(1)}</>}
                            </div>
                        </div>
                        <button type="button" className="rq-x" aria-label="Close" onClick={() => setQrAsk(null)}><LIcon name="x" size={17} /></button>
                    </header>

                    <div className="rq-body">
                        <dl className="rq-sum">
                            <div><dt>Document</dt><dd><LIcon name="fileText" size={15} /><span>{workspace.title || "Untitled document"}</span><em>Version {workspace.base_version}</em></dd></div>
                            <div><dt>Review fee</dt><dd><b>{rupees(qrAsk.fee)}</b><em>due only if they accept</em></dd></div>
                            <div><dt>Turnaround</dt><dd><b>{qrAsk.hours} hours</b><em>after they accept</em></dd></div>
                            <div><dt>Reply window</dt><dd><span>24 hours to accept or decline</span></dd></div>
                        </dl>

                        <div className="rq-field">
                            <div className="rq-label"><label htmlFor="qr-note">Note for the lawyer</label><span>Optional · {qrForm.note.length}/1000</span></div>
                            <textarea id="qr-note" rows={2} maxLength={1000} value={qrForm.note} onChange={e => setQrForm(f => ({ ...f, note: e.target.value }))}
                                placeholder="e.g. Please check the amount and the 15-day deadline." />
                        </div>

                        <label data-request-confirm className={`rq-confirm${qrForm.confirmed ? " on" : ""}`}>
                            <input type="checkbox" checked={qrForm.confirmed} onChange={e => setQrForm(f => ({ ...f, confirmed: e.target.checked }))} />
                            <span className="rq-tick" aria-hidden="true"><LIcon name="check" size={13} /></span>
                            <span>I have read version {workspace.base_version} and it says what I mean.</span>
                        </label>

                        {qrIssue && <div role="alert" data-request-issue className="rq-issue">{qrIssue}</div>}
                    </div>

                    <footer className="rq-foot">
                        <button type="button" className="rq-cancel" onClick={() => setQrAsk(null)}>Cancel</button>
                        <button type="button" className="rq-send" data-request-submit onClick={requestReview} disabled={!qrForm.confirmed || qrBusy || dirty}>
                            {qrBusy ? "Sending…" : <>Send request<LIcon name="send" size={15} /></>}
                        </button>
                    </footer>
                </div>
            </div>
        );
        const sendPage = (
            <section data-send-panel aria-label="Send for review" data-lenis-prevent
                style={{ position: "absolute", inset: 0, zIndex: 5, overflowY: "auto", ...thinScroll, background: t.bg, padding: "20px clamp(16px,2.4vw,32px) 28px" }}>
                <div style={{ width: "min(1240px,100%)", minHeight: "100%", margin: "0 auto", display: "flex", flexDirection: "column", gap: 18 }}>
                    <header style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
                        <button type="button" className="ws-back" onClick={() => setPanel(null)} aria-label="Back to the document" title="Back to the document"><LIcon name="back" size={19} /></button>
                        <div style={{ flex: 1, minWidth: 260 }}>
                            <h1 style={{ margin: 0, fontFamily: SERIF, fontSize: 25, fontWeight: 600, lineHeight: 1.2 }}>
                                {openReq ? "Review requested" : hasLawyer ? "Who should review your document?" : "Get this document reviewed"}
                            </h1>
                            {!hasLawyer && !openReq && <div style={{ fontSize: 13.5, color: t.textMuted }}>No meeting needed — a lawyer reads it and sends it back approved or with changes.</div>}
                            {openReq && <div style={{ fontSize: 13.5, color: t.textMuted }}>We'll notify you as soon as {openReq.lawyer_name} answers.</div>}
                        </div>
                        {hasLawyer && !openReq && (
                            <div data-send-doc style={{ display: "flex", alignItems: "center", gap: 10, minHeight: 46, padding: "0 8px 0 10px", borderRadius: 999, border: `1px solid ${t.border}`, background: t.surface, maxWidth: "100%" }}>
                                <span aria-hidden="true" style={{ width: 26, height: 32, flexShrink: 0, borderRadius: 4, background: "#F2F4F3" }} />
                                <span style={{ fontSize: 13.5, fontWeight: 700, ...clip }}>
                                    {workspace.title || "Untitled document"} <span style={{ color: t.textMuted, fontWeight: 600 }}>· v{workspace.base_version}</span>
                                </span>
                                {/* The one finding worth stopping for: blank details. The
                                    other checks stay on the document's Checks panel. */}
                                {blankRow && <button type="button" data-ready="details" onClick={() => { setPanel(null); openFill(); }}
                                    style={{ height: 30, padding: "0 10px", borderRadius: 999, border: "none", background: `${t.warn}29`, color: t.warn, fontSize: 12.5, fontWeight: 800, cursor: "pointer", fontFamily: "inherit", whiteSpace: "nowrap" }}>
                                    ! {blankRow.value} · Fill</button>}
                                {dirty && <span style={{ fontSize: 12.5, fontWeight: 800, color: t.warn, whiteSpace: "nowrap" }}>Save your changes first</span>}
                            </div>
                        )}
                        {openReq && <span style={{ height: 34, display: "inline-flex", alignItems: "center", padding: "0 14px", borderRadius: 999, background: `${t.warn}24`, color: t.warn, fontSize: 13, fontWeight: 800 }}>● Waiting to accept · {hoursLeft}h left</span>}
                        {!hasLawyer && !openReq && <button type="button" data-book-consultation onClick={() => router.push("/lawyers")}
                            style={{ border: "none", background: "transparent", color: t.textMuted, fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                            Need a lawyer for the whole case? <b style={{ color: t.primary }}>Book a consultation →</b></button>}
                    </header>

                    {openReq ? pendingView : (<>
                    {lawyers === null && <div style={{ fontSize: 14, color: t.textMuted }}>Loading your lawyers…</div>}

                    {hasLawyer && (
                        <section aria-label="Your lawyer">
                            <div style={{ ...label, marginBottom: 10 }}>{shownLawyers.length > 1 ? "YOUR LAWYERS" : "YOUR LAWYER"}</div>
                            <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(320px,420px)", borderRadius: 20, border: `2px solid ${t.primary}88`, background: t.surface, overflow: "hidden" }}>
                                <div role="radiogroup" aria-label="Reviewing lawyer" style={{ padding: "18px 20px", display: "flex", flexDirection: "column", gap: 10, justifyContent: "center" }}>
                                    {shownLawyers.map(l => {
                                        const on = sendForm.lawyerId === l.id;
                                        return (
                                            <button key={l.id} type="button" role="radio" aria-checked={on} onClick={() => setSendForm(f => ({ ...f, lawyerId: l.id }))}
                                                style={{ display: "flex", alignItems: "center", gap: 16, padding: shownLawyers.length > 1 ? 12 : 4, borderRadius: 16, textAlign: "left", cursor: "pointer", color: t.text, fontFamily: "inherit",
                                                    border: shownLawyers.length > 1 ? `${on ? 2 : 1}px solid ${on ? t.primary : t.border}` : "none", background: shownLawyers.length > 1 && on ? `${t.primary}12` : "transparent" }}>
                                                <span aria-hidden="true" style={{ width: 72, height: 72, flexShrink: 0, borderRadius: "50%", display: "grid", placeItems: "center", fontSize: 22, fontWeight: 800, background: on ? t.primary : `${t.primary}22`, color: on ? onPrimary(t) : t.primary }}>{initials(l.name)}</span>
                                                <span style={{ minWidth: 0, flex: 1 }}>
                                                    <span style={{ display: "block", fontSize: 21, fontWeight: 800 }}>{l.name}</span>
                                                    <span style={{ display: "inline-block", marginTop: 8, padding: "6px 12px", borderRadius: 999, background: `${t.primary}1c`, color: t.primary, fontSize: 13, fontWeight: 700 }}>{l.sub.replace(/^Engaged on:/, "Your lawyer on:")}</span>
                                                </span>
                                                {on && shownLawyers.length > 1 && <span aria-hidden="true" style={{ width: 24, height: 24, borderRadius: "50%", background: t.primary, color: onPrimary(t), display: "grid", placeItems: "center", fontWeight: 900, fontSize: 13 }}>✓</span>}
                                            </button>
                                        );
                                    })}
                                </div>
                                <div style={{ padding: "18px 20px", background: t.card, borderLeft: `1px solid ${t.border}`, display: "flex", flexDirection: "column", gap: 12 }}>
                                    <div role="radiogroup" aria-label="Urgency" style={{ display: "flex", gap: 4, padding: 3, borderRadius: 12, background: t.inputBg }}>
                                        {URGENCIES.map(([value, text, colour]) => {
                                            const on = sendForm.urgency === value;
                                            return <button key={value} type="button" role="radio" aria-checked={on} onClick={() => setSendForm(f => ({ ...f, urgency: value }))}
                                                style={{ flex: 1, height: 34, borderRadius: 9, border: "none", cursor: "pointer", fontFamily: "inherit", fontSize: 13, fontWeight: 800, background: on ? colour : "transparent", color: on ? "#06211a" : colour }}>{text}</button>;
                                        })}
                                    </div>
                                    <label htmlFor="send-note" style={{ position: "absolute", left: -9999 }}>Message for your lawyer</label>
                                    <textarea id="send-note" rows={2} value={sendForm.note} onChange={e => setSendForm(f => ({ ...f, note: e.target.value }))}
                                        placeholder="Message (optional) — what should they check?" style={fieldStyle(t, { resize: "vertical", fontSize: 13.5, padding: "10px 12px" })} />
                                    <label data-send-confirm style={{ display: "flex", gap: 9, alignItems: "flex-start", fontSize: 13, lineHeight: 1.45, cursor: "pointer" }}>
                                        <input type="checkbox" checked={sendForm.confirmed} onChange={e => setSendForm(f => ({ ...f, confirmed: e.target.checked }))} style={{ width: 17, height: 17, marginTop: 1 }} />
                                        I have read version {workspace.base_version} and it says what I mean
                                    </label>
                                    {sendIssue && <div role="alert" data-send-issue style={{ fontSize: 13, color: t.warn, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                                        {sendIssue.message}{sendIssue.retryable && <Btn onClick={() => submitForReview(true)} style={{ minHeight: 30 }}>Try again</Btn>}
                                    </div>}
                                    <Btn kind="primary" data-send-submit onClick={() => submitForReview(false)} disabled={!canSend} style={{ width: "100%", minHeight: 46, borderRadius: 999, fontSize: 15 }}>
                                        <LIcon name="send" size={15} />{sending ? "Sending…" : chosen ? `Send to ${chosen.name} →` : "Choose a lawyer"}
                                    </Btn>
                                    <div style={{ fontSize: 12, color: t.textMuted, textAlign: "center" }}>
                                        You can withdraw it until they decide · <button type="button" onClick={download} style={{ border: "none", background: "transparent", padding: 0, color: t.primary, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", fontSize: 12 }}>Download the PDF instead</button>
                                    </div>
                                </div>
                            </div>
                        </section>
                    )}

                    {lawyers !== null && (hasLawyer ? reviewersSection : (
                        <div style={{ display: "grid", gridTemplateColumns: "minmax(260px,320px) minmax(0,1fr)", gap: 20, alignItems: "start" }}>
                            {docAside}
                            {reviewersSection}
                        </div>
                    ))}
                    </>)}
                </div>
            </section>
        );
        // After a send: what was sent, what happens next, where to follow it.
        const sentPage = sentInfo && (
            <section data-send-sent aria-label="Sent for review" data-lenis-prevent
                style={{ position: "absolute", inset: 0, zIndex: 5, overflowY: "auto", ...thinScroll, background: t.bg, display: "grid", placeItems: "center", padding: 32 }}>
                <div style={{ width: "min(640px,100%)", borderRadius: 22, border: `1px solid ${t.border}`, background: t.surface, padding: "34px 38px", display: "flex", flexDirection: "column", gap: 22 }}>
                    <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                        <span aria-hidden="true" style={{ width: 54, height: 54, flexShrink: 0, borderRadius: "50%", background: t.primary, color: onPrimary(t), display: "grid", placeItems: "center" }}><LIcon name="check" size={26} /></span>
                        <div>
                            <h1 style={{ margin: 0, fontFamily: SERIF, fontSize: 26, fontWeight: 600 }}>Sent to {sentInfo.lawyer}</h1>
                            <p style={{ margin: "4px 0 0", fontSize: 14, color: t.textMuted }}>{workspace.title || "Your document"} · version {sentInfo.version} · {(URGENCIES.find(([v]) => v === sentInfo.urgency) || URGENCIES[0])[1]}</p>
                        </div>
                    </div>
                    <ol aria-label="What happens next" style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 14 }}>
                        {[["✓", "Sent", "This version is frozen. You can still edit — as a new version.", "done"],
                          ["2", "Your lawyer reviews it", "You are notified when they decide.", "now"],
                          ["3", "Approved, or sent back with changes", "If they edit the wording, you read their changes and send it again.", "later"]].map(([mark, title, sub, state]) => (
                            <li key={title} style={{ display: "flex", gap: 12 }}>
                                <span aria-hidden="true" style={{ width: 26, height: 26, flexShrink: 0, borderRadius: "50%", display: "grid", placeItems: "center", fontSize: 13, fontWeight: 900,
                                    background: state === "done" ? t.primary : "transparent", color: state === "done" ? onPrimary(t) : state === "now" ? t.primary : t.textMuted,
                                    border: state === "done" ? "none" : `${state === "now" ? 2 : 1.5}px solid ${state === "now" ? t.primary : t.border}` }}>{mark}</span>
                                <div><b style={{ fontSize: 14.5 }}>{title}</b><div style={{ fontSize: 13, color: t.textMuted }}>{sub}</div></div>
                            </li>
                        ))}
                    </ol>
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
                        <Btn kind="primary" onClick={() => router.push("/tracking")} style={{ minHeight: 44, borderRadius: 999 }}>Track it in Tracking</Btn>
                        <Btn data-sent-back onClick={() => setSentInfo(null)} style={{ minHeight: 44, borderRadius: 999 }}>Back to the document</Btn>
                        <span style={{ flex: 1 }} />
                        <button type="button" onClick={async () => { await withdrawFromReview(); setSentInfo(null); }}
                            style={{ height: 44, padding: "0 14px", border: "none", background: "transparent", color: t.textMuted, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>Withdraw</button>
                    </div>
                </div>
            </section>
        );

        // Ask AI: a pill over the page; clicked, a composer with quick requests.
        // It asks AI Assist for a PROPOSAL -- nothing is saved until Save.
        const sendAsk = async () => { if (await askAi()) { setAskOpen(false); setInstruction(""); } };
        const suggestions = askSuggestions(workspace.source_template || workspace.template_type);
        const askUi = viewRev ? null : !askOpen ? (
            <button type="button" data-ask-ai onClick={() => setAskOpen(true)} disabled={locked}
                title={locked ? "Frozen while a lawyer reviews it" : "Ask AI to change this document"}
                style={{ position: "absolute", right: 24, bottom: 22, zIndex: 3, display: "inline-flex", alignItems: "center", gap: 10, minHeight: 52, padding: "0 24px", borderRadius: 999, border: "none", background: t.primary, color: onPrimary(t), fontSize: 16, fontWeight: 700, cursor: locked ? "not-allowed" : "pointer", opacity: locked ? 0.55 : 1, boxShadow: "0 10px 28px rgba(0,0,0,.35)" }}>
                <LIcon name="sparkles" size={19} />Ask AI
            </button>
        ) : (
            <div data-ask-composer role="dialog" aria-label="Ask AI"
                onKeyDown={e => { if (e.key === "Escape") setAskOpen(false); }}
                style={{ position: "absolute", left: "clamp(12px, 3vw, 28px)", right: "clamp(12px, 3vw, 28px)", bottom: 16, zIndex: 3, maxWidth: 1000, margin: "0 auto", padding: 14, borderRadius: 18, background: t.card, border: `1px solid ${t.primary}40`, boxShadow: "0 18px 48px rgba(0,0,0,.45)", display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
                    {suggestions.map(text => (
                        <button key={text} type="button" data-ask-suggestion onClick={() => setInstruction(text)}
                            style={{ padding: "6px 16px", borderRadius: 999, border: `1px solid ${t.primary}55`, background: "transparent", color: t.primary, fontSize: 13.5, cursor: "pointer" }}>{text}</button>
                    ))}
                    <span style={{ flex: 1 }} />
                    <button type="button" aria-label="Close Ask AI" title="Close" onClick={() => setAskOpen(false)}
                        style={{ width: 30, height: 30, borderRadius: 8, border: "none", background: "transparent", color: t.textMuted, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}><LIcon name="x" size={16} /></button>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <span aria-hidden="true" style={{ width: 44, height: 44, flexShrink: 0, borderRadius: 12, display: "flex", alignItems: "center", justifyContent: "center", background: `${t.primary}1f`, color: t.primary }}><LIcon name="sparkles" size={20} /></span>
                    <label htmlFor="drafts-ask" style={{ position: "absolute", left: -9999 }}>Ask AI to change this document</label>
                    <textarea id="drafts-ask" rows={1} autoFocus value={instruction} disabled={locked || busy} onChange={e => setInstruction(e.target.value)}
                        onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendAsk(); } }}
                        placeholder="Ask AI to change this document…"
                        style={{ flex: 1, resize: "none", background: "transparent", border: "none", color: t.text, fontSize: 15, lineHeight: 1.5, outline: "none", padding: "8px 0" }} />
                    <button type="button" aria-label="Prepare proposal" onClick={sendAsk} disabled={locked || busy || !instruction.trim()}
                        style={{ width: 44, height: 44, flexShrink: 0, borderRadius: 12, border: "none", background: instruction.trim() ? t.primary : `${t.primary}33`, color: instruction.trim() ? onPrimary(t) : t.textMuted, cursor: instruction.trim() ? "pointer" : "not-allowed", display: "flex", alignItems: "center", justifyContent: "center" }}>
                        {busy ? "…" : <LIcon name="arrowUp" size={18} />}
                    </button>
                </div>
            </div>
        );

        return <div data-document-workspace data-drafts-font style={{ ...L.root, background: t.bg, color: t.text }}>
          {draftsFont}
          <style>{WORKSPACE_CSS}</style>
          <div style={L.row}>
            {/* The history column runs the full height (2026-10-10), as the lawyer
                AI's does; the header starts beside it. The send page and the Sent
                screen take the whole width instead (2026-10-11). */}
            {panel !== "send" && !sentInfo && historyColumn}
            <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column", position: "relative" }}>
            {panel === "send" && sendPage}
            {panel === "send" && askDialog}
            {panel !== "send" && sentPage}
            {/* The page header: the way back and the document on the left, the
                two ways onward (find a lawyer, send to yours) on the right. */}
            <header aria-label="Document header" className="ws-header" style={{ minHeight: 61, flexShrink: 0, display: "flex", alignItems: "center", gap: 10, padding: "8px 22px 8px 28px" }}>
                <button type="button" className="ws-back" onClick={reset} aria-label="Back to drafts" title="Back to drafts"><LIcon name="back" size={19} /></button>
                <div style={{ minWidth: 0, display: "flex", alignItems: "baseline", gap: 12 }}>
                    <h1 data-document-title style={{ margin: 0, fontFamily: SERIF, fontSize: 22, fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "min(460px, 34vw)" }}>{workspace.title || "Untitled document"}</h1>
                    <span data-save-state role="status" style={{ color: dirty ? t.warn : t.success, fontSize: 12.5, whiteSpace: "nowrap" }}>
                        {dirty ? "Unsaved changes" : savedAt ? "✓ Saved just now" : `✓ Version ${workspace.base_version} saved`}
                    </span>
                </div>
                <span style={{ flex: 1 }} />
                {/* Pills, no boxes (2026-10-10): the icon moves on hover, the button does not. */}
                <button type="button" className="ws-pill ws-market" data-visit-marketplace onClick={() => router.push("/lawyers")}>
                    <span className="ic"><LIcon name="store" size={15} /></span>Visit Marketplace
                </button>
                <button type="button" className="ws-pill ws-send" onClick={sendForReview} disabled={locked || busy || dirty} title={dirty ? "Save your changes before sending" : locked ? "Already with your lawyer" : undefined}>
                    <span className="ic"><LIcon name="send" size={14} /></span>{openReq ? "Review requested" : "Send to lawyer"}
                </button>
            </header>
            <div style={L.row}>
                <section style={{ ...L.col("1 1 420px"), display: "flex", flexDirection: "column", minWidth: 0 }}>
                    <div role="toolbar" aria-label="Document actions" className="ws-tools" style={{ minHeight: 48, flexShrink: 0, display: "flex", alignItems: "center", overflowX: "auto", padding: "7px 16px" }}>
                        {/* Standalone pills spread evenly over a centred line (max 1080px),
                            so the bar stays balanced with the history column open or closed. */}
                        <div className="ws-tools-row">
                        {/* Edit: the document's TEXT where it has one; a template
                            without a text view edits through its details panel. */}
                        <button type="button" data-edit-toggle aria-pressed={textView ? isText && editMode : panel === "fill"} disabled={locked}
                            onClick={onEdit}
                            style={{ ...tb(textView ? isText && editMode : panel === "fill"), opacity: locked ? 0.5 : 1 }}><LIcon name="pencil" size={16} />Edit</button>
                        {(structured || isText) && <button type="button" data-placeholders-toggle aria-pressed={panel === "fill"} disabled={locked}
                            onClick={() => togglePanel("fill")} style={{ ...tb(panel === "fill"), opacity: locked ? 0.5 : 1 }}>
                            <LIcon name="sliders" size={16} />Placeholders <span data-placeholders-badge style={count(blanks ? "warn" : "ok")}>{blanks || "✓"}</span></button>}
                        <button type="button" data-checks-toggle aria-pressed={panel === "checks"} onClick={() => togglePanel("checks")} style={tb(panel === "checks")}>
                            <LIcon name="listChecks" size={16} />Checks <span data-checks-badge title={checks.badge.title} style={count(checks.badge.tone === "medium" ? "warn" : checks.badge.tone === "low" ? "ok" : "neutral")}>{checks.badge.text}</span></button>
                        <span className="ws-divider" aria-hidden="true" />
                        {fieldsMode && panel === "fill" && <button type="button" data-undo onClick={undo} disabled={locked || !undoStack.current.items.length} title="Undo the last detail change"
                            style={{ ...tb(), color: undoStack.current.items.length ? t.text : t.textMuted }}><LIcon name="undo" size={16} />Undo</button>}
                        <button type="button" data-save onClick={() => save()} disabled={locked || busy || !dirty} title="Save your changes as a new version"
                            style={{ ...tb(), color: dirty ? t.primary : t.textMuted, fontWeight: dirty ? 650 : 500 }}><LIcon name="save" size={16} />{busy && dirty ? "Saving…" : "Save"}</button>
                        <button type="button" data-pdf onClick={download} title={dirty ? "Downloads the last saved version" : "Download the current version"} style={tb()}><LIcon name="download" size={16} />PDF</button>
                        <button type="button" disabled data-docx-soon title="Word export isn't connected yet — coming soon." style={{ ...tb(), color: t.textMuted, cursor: "not-allowed" }}>
                            <LIcon name="fileText" size={16} />DOCX {soon}</button>
                        {/* No endpoint emails a document yet: shown, labelled, not clickable. */}
                        <button type="button" disabled data-email-soon title="Emailing a document isn't connected yet — coming soon." style={{ ...tb(), color: t.textMuted, cursor: "not-allowed" }}>
                            <LIcon name="mail" size={16} />Email {soon}</button>
                        </div>
                    </div>
                    {reviewBanner(detail)}
                    {issue && <div role="alert" style={{ margin: "10px 18px 0", color: t.warn, fontSize: 13.5 }}>{issue}</div>}
                    {textEdit && structured && <div data-text-edit-note role="note" style={{ margin: "10px 18px 0", padding: "8px 12px", borderRadius: 10, background: `${t.primary}14`, border: `1px solid ${t.primary}45`, fontSize: 13, lineHeight: 1.5 }}>
                        You are editing the text. From the next save it is kept as edited text: the required-particulars check will not run on it, the citation check still will. Earlier versions stay under Versions.
                    </div>}
                    {viewRev && <div data-viewing-version role="note" style={{ margin: "10px 18px 0", padding: "8px 12px", borderRadius: 10, background: `${t.warn}14`, border: `1px solid ${t.warn}45`, display: "flex", alignItems: "center", gap: 10, fontSize: 13 }}>
                        <span style={{ flex: 1 }}>Showing version {viewRev.version}, an older version. Editing and sending use the current one.</span>
                        <Btn onClick={() => setViewRev(null)} style={{ minHeight: 32 }}>Back to current</Btn>
                    </div>}
                    {proposal && <div data-ai-proposal role="note" style={{ margin: "10px 18px 0", padding: "10px 14px", borderRadius: 12, border: `1px solid ${t.primary}66`, background: t.card, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                        <span style={{ flex: 1, minWidth: 200, fontSize: 13.5 }}>{proposal.summary}</span>
                        <Btn onClick={() => setProposal(null)}>Discard</Btn><Btn kind="primary" onClick={applyProposal}>Apply proposal locally</Btn>
                    </div>}
                    <div style={{ ...L.row, minHeight: 0, flex: 1 }}>
                        <div style={{ ...L.col("1 1 540px"), position: "relative", display: "flex", minWidth: 0, minHeight: 0 }}>
                        <main data-lenis-prevent className="ws-main" style={{ flex: 1, minWidth: 0, minHeight: 0, overflowY: "auto", ...thinScroll, padding: "16px clamp(12px,2vw,28px) 104px", display: "flex", flexDirection: "column", alignItems: "center" }}>
                            {viewRev
                                ? <PdfDocumentView url={viewRev.url} t={t} />
                                : textView
                                ? <RichTextEditor t={t} html={isText ? content?.body_html || "" : liveText || workspace.text_html || ""}
                                    disabled={locked || !isText || !editMode} editing={isText && editMode && !locked}
                                    saving={busy} onSave={() => save()} onDone={() => setEditMode(false)}
                                    onPlaceholder={name => openFill(fieldsMode ? name.toLowerCase() : name)}
                                    onChange={body_html => { setContent({ body_html }); setSavedAt(null); saveIntent.current = null; }} />
                                : previewUrl
                                    ? <PdfDocumentView url={previewUrl} t={t} />
                                    : <div style={{ width: "min(900px,100%)", minHeight: 560, boxSizing: "border-box", padding: 30, background: t.card, fontSize: 14 }}>{busy ? "Loading the current PDF…" : "The PDF preview is not available. Download the saved version or try saving again."}</div>}
                            {dirty && !viewRev && !textView && <div style={{ alignSelf: "center", padding: 10, color: t.warn, fontSize: 12.5 }}>The preview shows the last saved version. Save to update it.</div>}
                        </main>
                        {askUi}
                        </div>

                        {panel === "checks" && (
                            <aside data-completion-panel aria-label="Review document"
                                style={{ ...L.col("0 1 360px"), minWidth: 300, borderLeft: `1px solid ${t.border}`, background: t.surface, display: "flex", flexDirection: "column", minHeight: 0 }}>
                                {panelHead("listChecks", "Checks", "From the saved version")}
                                <div data-lenis-prevent style={{ flex: 1, overflowY: "auto", ...thinScroll, padding: 18, display: "flex", flexDirection: "column", gap: 10 }}>
                                    {checks.rows.map(c => <div key={c.label} data-check={c.key} style={{ padding: 14, border: `1px solid ${t.border}`, borderRadius: 12, background: t.card }}>
                                        <div style={{ display: "flex", gap: 8, alignItems: "center", color: toneColour(t, c.tone) }}><LIcon name={["success", "ok"].includes(c.tone) ? "checkCircle" : ["warn", "danger"].includes(c.tone) ? "alertCircle" : "minusCircle"} size={17} /><strong style={{ color: t.text, fontSize: 13.5 }}>{c.label}</strong></div>
                                        <div style={{ marginTop: 5, color: t.textMuted, fontSize: 12.5 }}>{c.value}{c.detail ? ` — ${c.detail}` : ""}</div>
                                        {c.fix && blanks > 0 && <button type="button" data-fill-in onClick={() => openFill()} style={{ marginTop: 8, border: "none", background: "transparent", color: t.primary, cursor: "pointer" }}>Fill in</button>}
                                    </div>)}
                                </div>
                            </aside>
                        )}
                    </div>
                </section>
            </div>
            </div>
            {fillPanel}
          </div>
        </div>;
    }

    // ── the start screen ─────────────────────────────────────────────────────
    return <div data-drafts-font style={{ ...L.root, background: t.bg }}>
        {draftsFont}
        <div style={L.row}>
            {historyColumn}
            <main data-lenis-prevent style={{ ...L.col("1 1 520px"), padding: "clamp(24px,4vw,48px)", overflowY: "auto", ...thinScroll }}>
                <PromptCard t={t} templates={templates} cases={cases} onPlan={startPlan} workspace onViewTemplates={onBack} typeRequired={typeNeeded} />
                {busy && <div role="status" style={{ textAlign: "center", color: t.textMuted, marginTop: 14 }}>Creating a reviewable draft plan…</div>}
                {issue && <div role="alert" style={{ maxWidth: 760, margin: "14px auto", color: t.warn }}>{issue}</div>}
            </main>
        </div>
    </div>;
}
