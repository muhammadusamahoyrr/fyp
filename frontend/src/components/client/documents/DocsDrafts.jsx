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
import { useMyDocuments, rowActions } from "@/lib/useMyDocuments.js";
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
const DRAFTS_FONT_CSS = `[data-drafts-font], [data-drafts-font] *:not([data-keep-font]) { font-family: ${DRAFTS_FONT} !important; }`;
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
function RowMenu({ t, label, items, icon = "moreVertical" }) {
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
            <button type="button" aria-label={label} title="More actions" aria-haspopup="menu" aria-expanded={open}
                onClick={e => { e.stopPropagation(); setOpen(o => !o); }}
                style={{ width: 30, height: 30, borderRadius: 8, border: "none", background: open ? t.inputBg : "transparent", color: t.text, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <LIcon name={icon} size={18} stroke={3} />
            </button>
            {open && (
                <div role="menu" aria-label={label}
                    style={{ position: "absolute", right: 0, top: 34, zIndex: 20, minWidth: 176, padding: 4, borderRadius: 10, background: t.card, border: `1px solid ${t.border}`, boxShadow: "0 10px 28px rgba(0,0,0,.35)" }}>
                    {items.map(item => (
                        <button key={item.label} type="button" role="menuitem" disabled={item.disabled} title={item.title}
                            onClick={() => { setOpen(false); item.onSelect(); }}
                            style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "8px 10px", borderRadius: 7, border: "none", background: "transparent", textAlign: "left", fontSize: 13.5, whiteSpace: "nowrap",
                                color: item.danger ? t.danger : t.text, cursor: item.disabled ? "not-allowed" : "pointer", opacity: item.disabled ? 0.45 : 1 }}>
                            <LIcon name={item.icon} size={16} />{item.label}
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
const SIDE_ROW_CSS = `[data-side-row] [data-row-hint]{display:none}
[data-side-row]:hover [data-row-hint],[data-side-row]:focus-within [data-row-hint]{display:block}
[data-side-row] [data-row-menu]{opacity:0}
[data-side-row]:hover [data-row-menu],[data-side-row]:focus-within [data-row-menu],[data-row-menu][data-open]{opacity:1}`;

function SideRow({ t, selected, title, note = null, hint = null, onOpen, disabled = false, menu, dataAttrs = {}, small = false }) {
    return (
        <div data-side-row data-selected={selected ? "true" : undefined}
            style={{ display: "flex", alignItems: "center", gap: 2, padding: "0 2px 0 0" }}>
            <button type="button" onClick={onOpen} disabled={disabled} aria-current={selected ? "true" : undefined} {...dataAttrs}
                style={{ flex: 1, minWidth: 0, padding: small ? "6px 6px 6px 8px" : "8px 6px 8px 14px", border: "none", background: "transparent", color: t.text, textAlign: "left", cursor: disabled ? "default" : "pointer" }}>
                <div style={{ fontSize: small ? 12.5 : 13.5, fontWeight: selected ? 700 : 500, color: selected ? t.primary : t.text, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{title}</div>
                {note && <div data-row-note style={{ fontSize: 11.5, color: t.textMuted, marginTop: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{note}</div>}
                {hint && <div data-row-hint style={{ fontSize: 11, color: t.textMuted, marginTop: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{hint}</div>}
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
    const [sending, setSending] = useState(false);
    const [sendIssue, setSendIssue] = useState(null);         // { message, retryable }
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
    const sendForReview = () => { setSendIssue(null); setPanel("send"); };
    // The case's own lawyer, when the document belongs to a case that has one:
    // its documents are reviewed by that lawyer.
    const caseLawyerId = (cases || []).find(c => (c._id || c.id) === detail?.case_id)?.lawyer_id || null;
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
                if (e?.lawyer_id && !byLawyer.has(e.lawyer_id)) {
                    byLawyer.set(e.lawyer_id, { id: e.lawyer_id, name: e.lawyer_name || "Your lawyer", sub: e.case_title ? `Engaged on: ${e.case_title}` : "Engaged lawyer" });
                }
            }
            setLawyers([...byLawyer.values()]);
        }).catch(() => { if (live) setLawyers([]); });
        return () => { live = false; };
    }, [panel, lawyers]);
    useEffect(() => { if (caseLawyerId) setSendForm(f => ({ ...f, lawyerId: caseLawyerId })); }, [caseLawyerId]);
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
        setPanel(null); setSendForm(f => ({ ...f, note: "", confirmed: false }));
        toast.show("Sent. Your lawyer has been notified.", "success", 3500);
        await loadWorkspace(workspace.document_id); docs.reload();
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
    const roundEdge = { width: 44, height: 44, borderRadius: "50%", border: "none", background: "linear-gradient(135deg, #1f8a5b, #0f7f73)", color: "#fff", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 6px 18px rgba(0,0,0,.3)" };
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
    const sideTabBtn = (id, icon, label) => {
        const on = sideTab === id;
        return (
            <button key={id} type="button" role="tab" data-side-tab={id} aria-selected={on} onClick={() => setSideTab(id)}
                style={{ flex: 1, minWidth: 0, minHeight: 32, padding: "0 8px", borderRadius: 999, cursor: "pointer", fontSize: 12.5, fontWeight: 600,
                    display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
                    border: on ? "1px solid rgba(255,255,255,.25)" : `1px solid ${t.border}`,
                    background: on ? "linear-gradient(90deg, #1f8a5b, #127a70)" : "transparent",
                    color: on ? "#e8fff9" : t.text, boxShadow: on ? "0 3px 10px rgba(15,127,115,.22)" : "none" }}>
                <LIcon name={icon} size={13} />{label}
            </button>
        );
    };
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
    const historyColumn = sideCollapsed ? (
        <div style={{ position: "relative", flex: "0 0 0px" }}>
            <button type="button" onClick={() => setSideCollapsed(false)} aria-label="Show history" title="Show history"
                style={{ ...roundEdge, position: "absolute", left: 12, bottom: 24, zIndex: 4 }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
            </button>
        </div>
    ) : (
        <aside aria-label="Draft history" style={{ ...L.col("0 0 206px"), position: "relative", borderRight: `1px solid ${t.border}`, background: t.surface, display: "flex", flexDirection: "column", minHeight: 0 }}>
            <style>{SIDE_ROW_CSS}</style>
            <div style={{ padding: "14px 10px 12px" }}>
                {workspace ? (
                    <div role="tablist" aria-label="Document sidebar" style={{ display: "flex", gap: 6 }}>
                        {sideTabBtn("versions", "history", "Versions")}
                        {sideTabBtn("saved", "bookmark", "Saved")}
                    </div>
                ) : (
                <button type="button" data-ai-draft onClick={reset} title="Start a new AI draft"
                    style={{ width: "100%", minHeight: 38, borderRadius: 999, border: "1px solid rgba(255,255,255,.25)", background: "linear-gradient(90deg, #1f8a5b, #127a70)", color: "#e8fff9", fontSize: 13.5, fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 8, boxShadow: "0 3px 10px rgba(15,127,115,.22)" }}>
                    <LIcon name="fileText" size={15} /> AI Draft
                </button>
                )}
            </div>
            <div style={{ height: 1, background: t.border }} />
            <div data-lenis-prevent style={{ flex: 1, minHeight: 0, overflowY: "auto", ...thinScroll, padding: "16px 8px 90px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "0 4px 12px" }}>
                    <span data-side-heading style={{ flex: 1, fontSize: 16, fontWeight: 700, color: t.text }}>
                        {!workspace ? "History" : showVersions ? "Versions" : "Saved"}
                    </span>
                    <button type="button" onClick={() => setHistoryOpen(o => !o)} aria-expanded={historyOpen} aria-label={historyOpen ? "Collapse list" : "Expand list"}
                        style={{ width: 32, height: 32, borderRadius: 8, border: "none", background: "transparent", color: t.text, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
                        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
                            style={{ transform: historyOpen ? "none" : "rotate(180deg)", transition: "transform .2s" }}><path d="M6 15l6-6 6 6" /></svg>
                    </button>
                    {/* The ⋯ menu: the full list lives in the Vault. (Nothing here
                        deletes documents in bulk -- they are records, not a cache.) */}
                    <RowMenu t={t} label="History options" icon="moreHorizontal" items={[
                        { label: "Open Vault", icon: "fileText", onSelect: () => onOpenView?.("vault") },
                        { label: "Refresh", icon: "history", onSelect: () => docs.reload() },
                    ]} />
                </div>
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
                            <div key={name} data-history-group={name} style={{ marginBottom: 6 }}>
                                <button type="button" onClick={() => setClosedGroups(g => ({ ...g, [name]: !g[name] }))} aria-expanded={!closed}
                                    style={{ display: "flex", alignItems: "center", gap: 8, width: "100%", padding: "4px 6px 6px", background: "none", border: "none", color: t.text, fontSize: 13, fontWeight: 700, cursor: "pointer" }}>
                                    {chevron(!closed, "rotate(-90deg)")}{name}
                                </button>
                                {!closed && rows.map(docRow)}
                            </div>
                        );
                    })}
                    {docs.error && <div style={{ fontSize: 12.5, color: t.warn, padding: 8 }}>Could not load your documents. <button type="button" onClick={docs.reload} style={{ background: "none", border: "none", color: t.primary, cursor: "pointer", padding: 0, fontSize: 12.5 }}>Try again</button></div>}
                    {!docs.loaded && !docs.error && <div style={{ fontSize: 12.5, color: t.textMuted, padding: 8 }}>Loading your documents…</div>}
                    {docs.isEmpty && <div style={{ fontSize: 13, color: t.textMuted, padding: 8 }}>No documents yet. Describe one to start.</div>}
                    {docs.hasMore && <button type="button" onClick={docs.loadMore} style={{ ...hist(false), textAlign: "center", color: t.primary, fontSize: 13 }}>Load more</button>}
                </>}
            </div>
            <button type="button" onClick={() => setSideCollapsed(true)} aria-label="Hide history" title="Hide history"
                style={{ ...roundEdge, position: "absolute", right: -22, bottom: 24, zIndex: 4 }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
            </button>
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
        const tb = (on = false) => ({
            display: "inline-flex", alignItems: "center", gap: 7, minHeight: 38, padding: "0 11px", borderRadius: 9,
            border: `1px solid ${on ? `${t.primary}66` : "transparent"}`, background: on ? `${t.primary}1a` : "transparent",
            color: t.text, fontSize: 13.5, fontWeight: 500, cursor: "pointer", whiteSpace: "nowrap",
        });
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
            const note = String(doc?.review_note || "").trim();
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
        const sep = <span aria-hidden="true" style={{ width: 1, height: 22, background: t.border, margin: "0 4px" }} />;
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
        const shownLawyers = caseLawyerId ? (lawyers || []).filter(l => l.id === caseLawyerId) : (lawyers || []);
        const canSend = Boolean(revision?.revision_id && sendForm.lawyerId && sendForm.confirmed && !dirty && !locked && !sending);
        const sectionLabel = text => <div style={{ fontSize: 11.5, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: t.textMuted, margin: "4px 2px 8px" }}>{text}</div>;
        const sendPanel = (
            <aside data-completion-panel data-send-panel aria-label="Send for review"
                style={{ ...L.col("0 1 360px"), minWidth: 300, borderLeft: `1px solid ${t.border}`, background: t.surface, display: "flex", flexDirection: "column", minHeight: 0 }}>
                {panelHead("send", "Send for review", `Version ${workspace.base_version} · frozen while your lawyer reviews it`)}
                <div data-lenis-prevent style={{ flex: 1, overflowY: "auto", ...thinScroll, padding: "14px 16px", display: "flex", flexDirection: "column", gap: 16 }}>
                    <section aria-label="Ready to send?">
                        {sectionLabel("Ready to send?")}
                        {[{ key: "saved", label: `Saved as version ${workspace.base_version}`, value: dirty ? "Save your changes first" : "This is the version that is sent", tone: dirty ? "warn" : "ok" }, ...checks.rows].map(r => {
                            const [mark, colour] = toneMark(r.tone);
                            return (
                                <div key={r.key} data-ready={r.key} style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "7px 2px" }}>
                                    <span aria-hidden="true" style={{ width: 20, height: 20, flexShrink: 0, borderRadius: "50%", display: "grid", placeItems: "center", fontSize: 11, fontWeight: 800, color: colour, background: `${colour}22` }}>{mark}</span>
                                    <div style={{ minWidth: 0 }}><div style={{ fontSize: 13, fontWeight: 600 }}>{r.label}</div><div style={{ fontSize: 12, color: t.textMuted }}>{r.value}</div></div>
                                </div>
                            );
                        })}
                    </section>
                    <section aria-label="Your lawyer">
                        {sectionLabel(caseLawyerId ? "Your case lawyer" : "Send to")}
                        {lawyers === null && <div style={{ fontSize: 12.5, color: t.textMuted }}>Loading your lawyers…</div>}
                        {lawyers !== null && !shownLawyers.length && (
                            <div data-no-engaged-lawyer role="note" style={{ fontSize: 12.5, color: t.textMuted, lineHeight: 1.55 }}>
                                {caseLawyerId ? "This case's lawyer is not among your engaged lawyers." : "You have no lawyer engaged yet. A document can be sent only to a lawyer you have hired."}{" "}
                                <button type="button" onClick={() => router.push("/lawyers")} style={{ background: "none", border: "none", padding: 0, color: t.primary, fontWeight: 700, cursor: "pointer", fontSize: 12.5 }}>Find a lawyer</button>
                            </div>
                        )}
                        <div role="radiogroup" aria-label="Reviewing lawyer" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                            {shownLawyers.map(l => {
                                const on = sendForm.lawyerId === l.id;
                                return (
                                    <button key={l.id} type="button" role="radio" aria-checked={on} onClick={() => setSendForm(f => ({ ...f, lawyerId: l.id }))}
                                        style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 11px", borderRadius: 11, textAlign: "left", cursor: "pointer", color: t.text,
                                            border: `1.5px solid ${on ? t.primary : t.border}`, background: on ? `${t.primary}14` : "transparent" }}>
                                        <span aria-hidden="true" style={{ width: 32, height: 32, borderRadius: "50%", flexShrink: 0, display: "grid", placeItems: "center", fontSize: 12, fontWeight: 800, background: on ? t.primary : `${t.primary}22`, color: on ? onPrimary(t) : t.primary }}>
                                            {l.name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase()}
                                        </span>
                                        <span style={{ minWidth: 0 }}><span style={{ display: "block", fontSize: 13.5, fontWeight: 700 }}>{l.name}</span><span style={{ display: "block", fontSize: 11.5, color: t.textMuted }}>{l.sub}</span></span>
                                    </button>
                                );
                            })}
                        </div>
                    </section>
                    <section aria-label="How soon?">
                        {sectionLabel("How soon?")}
                        <div role="radiogroup" aria-label="Urgency" style={{ display: "flex", gap: 6 }}>
                            {[["normal", "Normal", t.success], ["priority", "Priority", t.warn], ["urgent", "Urgent", t.danger]].map(([value, label, colour]) => {
                                const on = sendForm.urgency === value;
                                return <button key={value} type="button" role="radio" aria-checked={on} onClick={() => setSendForm(f => ({ ...f, urgency: value }))}
                                    style={{ flex: 1, minHeight: 34, borderRadius: 9, cursor: "pointer", fontSize: 12.5, fontWeight: 700, border: `1.5px solid ${on ? colour : t.border}`, background: on ? `${colour}18` : "transparent", color: on ? colour : t.text }}>{label}</button>;
                            })}
                        </div>
                    </section>
                    <section aria-label="Note for your lawyer">
                        {sectionLabel("Anything they should look at?")}
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
                            {["Check the amounts", "Check the dates", "Is this enforceable?"].map(n => (
                                <button key={n} type="button" onClick={() => setSendForm(f => ({ ...f, note: f.note.trim() ? `${f.note.trim()}\n${n}` : n }))}
                                    style={{ padding: "4px 10px", borderRadius: 999, border: `1px solid ${t.border}`, background: "transparent", color: t.text, fontSize: 12, cursor: "pointer" }}>+ {n}</button>
                            ))}
                        </div>
                        <label htmlFor="send-note" style={{ position: "absolute", left: -9999 }}>Note for your lawyer</label>
                        <textarea id="send-note" rows={3} value={sendForm.note} onChange={e => setSendForm(f => ({ ...f, note: e.target.value }))}
                            placeholder="Optional — what should your lawyer pay attention to?" style={fieldStyle(t, { resize: "vertical", fontSize: 13.5, padding: "8px 10px" })} />
                    </section>
                    {/* The owner's word that this is the version they mean -- asked
                        at the moment of sending, not stored as a separate state. */}
                    <label data-send-confirm style={{ display: "flex", gap: 9, alignItems: "flex-start", fontSize: 13, lineHeight: 1.5, cursor: "pointer" }}>
                        <input type="checkbox" checked={sendForm.confirmed} onChange={e => setSendForm(f => ({ ...f, confirmed: e.target.checked }))} style={{ marginTop: 3 }} />
                        I have read version {workspace.base_version} and it says what I mean.
                    </label>
                    {sendIssue && <div role="alert" data-send-issue style={{ fontSize: 13, color: t.warn, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                        {sendIssue.message}{sendIssue.retryable && <Btn onClick={() => submitForReview(true)} style={{ minHeight: 30 }}>Try again</Btn>}
                    </div>}
                </div>
                <div style={{ padding: "12px 16px", borderTop: `1px solid ${t.border}`, display: "flex", flexDirection: "column", gap: 6 }}>
                    <Btn kind="primary" data-send-submit onClick={() => submitForReview(false)} disabled={!canSend} style={{ width: "100%", minHeight: 40 }}>
                        <LIcon name="send" size={15} />{sending ? "Sending…" : "Send for review"}
                    </Btn>
                    <div style={{ fontSize: 11.5, color: t.textMuted, textAlign: "center" }}>Don't need a lawyer? Use PDF in the toolbar — it stays marked as not reviewed.</div>
                </div>
            </aside>
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
          <div style={L.row}>
            <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column" }}>
            {/* The page header: the way back and the document on the left, the
                two ways onward (find a lawyer, send to yours) on the right. */}
            <header aria-label="Document header" style={{ minHeight: 68, flexShrink: 0, display: "flex", alignItems: "center", gap: 12, padding: "10px 22px", borderBottom: `1px solid ${t.border}`, background: t.bg }}>
                <button type="button" onClick={reset} aria-label="Back to drafts" title="Back to drafts"
                    style={{ width: 38, height: 38, borderRadius: 10, border: "none", background: "transparent", color: t.text, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}><LIcon name="back" size={20} /></button>
                <div style={{ minWidth: 0, display: "flex", alignItems: "baseline", gap: 12 }}>
                    <h1 data-document-title style={{ margin: 0, fontFamily: SERIF, fontSize: 22, fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "min(460px, 34vw)" }}>{workspace.title || "Untitled document"}</h1>
                    <span data-save-state role="status" style={{ color: dirty ? t.warn : t.success, fontSize: 12.5, whiteSpace: "nowrap" }}>
                        {dirty ? "Unsaved changes" : savedAt ? "✓ Saved just now" : `✓ Version ${workspace.base_version} saved`}
                    </span>
                </div>
                <span style={{ flex: 1 }} />
                <button type="button" data-visit-marketplace onClick={() => router.push("/lawyers")}
                    style={{ display: "inline-flex", alignItems: "center", gap: 8, minHeight: 42, padding: "0 18px", borderRadius: 12, border: `1px solid ${t.border}`, background: t.card, color: t.text, fontSize: 14, fontWeight: 650, cursor: "pointer" }}>
                    <LIcon name="store" size={17} />Visit Marketplace
                </button>
                <button type="button" onClick={sendForReview} disabled={locked || busy || dirty} title={dirty ? "Save your changes before sending" : locked ? "Already with your lawyer" : undefined}
                    style={{ display: "inline-flex", alignItems: "center", gap: 8, minHeight: 42, padding: "0 18px", borderRadius: 12, border: "none", background: t.primary, color: onPrimary(t), fontSize: 14, fontWeight: 700, cursor: locked || dirty ? "not-allowed" : "pointer", opacity: locked || dirty ? 0.55 : 1 }}>
                    <LIcon name="send" size={16} />Send to lawyer
                </button>
            </header>
            <div style={L.row}>
                {historyColumn}
                <section style={{ ...L.col("1 1 420px"), display: "flex", flexDirection: "column", minWidth: 0 }}>
                    <div role="toolbar" aria-label="Document actions" style={{ minHeight: 54, flexShrink: 0, display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap", padding: "7px 14px", borderBottom: `1px solid ${t.border}`, background: t.bg }}>
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
                        {sep}
                        {fieldsMode && panel === "fill" && <button type="button" data-undo onClick={undo} disabled={locked || !undoStack.current.items.length} title="Undo the last detail change"
                            style={{ ...tb(), color: undoStack.current.items.length ? t.text : t.textMuted }}><LIcon name="undo" size={16} />Undo</button>}
                        <button type="button" data-save onClick={() => save()} disabled={locked || busy || !dirty} title="Save your changes as a new version"
                            style={{ ...tb(), color: dirty ? t.primary : t.textMuted, fontWeight: dirty ? 650 : 500 }}><LIcon name="save" size={16} />{busy && dirty ? "Saving…" : "Save"}</button>
                        <button type="button" onClick={download} title={dirty ? "Downloads the last saved version" : "Download the current version"} style={tb()}><LIcon name="download" size={16} />PDF</button>
                        <button type="button" disabled data-docx-soon title="Word export isn't connected yet — coming soon." style={{ ...tb(), color: t.textMuted, cursor: "not-allowed" }}>
                            <LIcon name="fileText" size={16} />DOCX <span style={{ fontSize: 10.5, fontWeight: 700, padding: "1px 6px", borderRadius: 999, border: `1px solid ${t.border}` }}>Soon</span></button>
                        {/* No endpoint emails a document yet: shown, labelled, not clickable. */}
                        <button type="button" disabled data-email-soon title="Emailing a document isn't connected yet — coming soon." style={{ ...tb(), color: t.textMuted, cursor: "not-allowed" }}>
                            <LIcon name="mail" size={16} />Email <span style={{ fontSize: 10.5, fontWeight: 700, padding: "1px 6px", borderRadius: 999, border: `1px solid ${t.border}` }}>Soon</span></button>
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
                        <main data-lenis-prevent style={{ flex: 1, minWidth: 0, minHeight: 0, overflowY: "auto", ...thinScroll, padding: "16px clamp(12px,2vw,28px) 104px", background: darker, display: "flex", flexDirection: "column", alignItems: "center" }}>
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

                        {panel === "send" && sendPanel}
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
