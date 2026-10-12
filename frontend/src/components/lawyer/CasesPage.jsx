'use client';
// Lawyer Cases — a list sorted by what needs doing, and a workspace per case.
//
// UI ONLY over the existing API: every number and action here is backed by a
// route that already exists (cases, hearings + outcomes, messages, tasks,
// engagements, case documents). Things the design shows that the backend does
// not have yet — a court case number distinct from ours, filing date, fee on
// the case, client-assigned tasks, attachments, lawyer-booked meetings,
// hearing reschedule — are left out rather than drawn as if they worked.
import { Fragment, useState, useRef, useEffect, useId, useMemo } from "react";
import { createPortal } from "react-dom";
import { useTheme, ThemeCtx } from "./theme.js";
import { useCase, useNotif } from "./theme.js";
import { onNotification } from "@/lib/notificationTarget.js";
import { listAllCases } from "@/lib/allCases.js";
import { buildCasesView, selectFeed, requestAgeDays } from "@/lib/casesView.js";
import { Btn, Label } from "./components.jsx";
import { Icon, I } from "./icons.jsx";
import { DRAFTING_TOKENS_CSS, draftingMode } from "./draftingTheme.js";
import { fmtDate, fmtTime } from "./data.js";
import {
    listCases, createWalkInCase, addHearing as apiAddHearing, recordHearingOutcome as apiRecordOutcome,
    listMessages, sendMessage as apiSendMessage, listTasks, addTask as apiAddTask,
    toggleTask as apiToggleTask, listEngagements, proposeEngagementTerms, declineEngagement,
    completeEngagement, terminateEngagement, listDocuments, rescheduleHearing as apiReschedule,
    myDocumentsV2, fetchRevisionPreview, fetchDocumentPreviewUrl, reviewQueueV2,
    listCaseFiles, uploadCaseFile, openCaseFile, deleteCaseFile,
} from "@/lib/api.js";
import { documentStatusView } from "@/lib/documentStatus.js";
import { avatarBg } from "./utils.js";
import { caseStatusLabel } from "@/lib/caseStatus.js";
import { pktToday } from "@/lib/bookingTime.js";

// ─────────────────────────────────────────────
// SMALL HELPERS
// ─────────────────────────────────────────────
const AMBER = "#e8b84b";
const TEAL = "#38d8c4";
const BLUE = "#5ab3ff";
const RED = "#e8526a";
const HISTORY_STATUSES = ["Closed", "Dismissed"];
// Scales of justice: a beam on a post, two pans.
const SCALES = ["M12 3v18", "M7 21h10", "M5 7h14", "M12 5a1 1 0 100-2 1 1 0 000 2", "M5 7l-3 7a3 3 0 006 0z", "M19 7l-3 7a3 3 0 006 0z"];

const initialsOf = (name) => (name || "C").split(" ").filter(Boolean).map(w => w[0]).join("").slice(0, 2).toUpperCase();

/** Whole days from today (Pakistan) to a YYYY-MM-DD date; negative if past. */
function daysUntil(dateStr) {
    if (!dateStr) return null;
    const a = new Date(`${pktToday()}T12:00:00Z`);
    const b = new Date(`${dateStr.slice(0, 10)}T12:00:00Z`);
    if (Number.isNaN(b.getTime())) return null;
    return Math.round((b - a) / 86400000);
}
/** A YYYY-MM-DD shifted by n days. */
function shiftDay(dateStr, n) {
    const d = new Date(`${dateStr.slice(0, 10)}T12:00:00Z`);
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
}
const inDays = (n) => (n === null ? "" : n === 0 ? "today" : n === 1 ? "tomorrow" : n > 0 ? `in ${n} days` : n === -1 ? "yesterday" : `${-n} days ago`);

function Avatar({ name, size = 34 }) {
    const ini = initialsOf(name);
    return (
        <span style={{ width: size, height: size, borderRadius: "50%", flexShrink: 0, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: size * 0.34, fontWeight: 800, color: "#e9fffb", background: avatarBg(ini) }}>{ini}</span>
    );
}

function Pill({ children, color = TEAL, solid = false, style }) {
    return (
        <span style={{
            display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 10px", borderRadius: 999,
            fontSize: 11.5, fontWeight: 700, whiteSpace: "nowrap",
            background: solid ? color : `${color}22`, color: solid ? "#0b1c22" : color,
            border: `1px solid ${color}55`, ...style,
        }}>{children}</span>
    );
}

function SectionHead({ title, hint, count, t }) {
    return (
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, padding: "0 6px" }}>
            <span style={{ fontSize: 12, fontWeight: 800, letterSpacing: "0.14em", textTransform: "uppercase", color: t.textMuted }}>{title}</span>
            {hint && <span style={{ fontSize: 13, color: t.textMuted }}>{hint}</span>}
            <span style={{ marginLeft: "auto", fontSize: 13, fontWeight: 700, color: t.textMuted }}>{count}</span>
        </div>
    );
}

function ScalesTile({ color = TEAL }) {
    return (
        <span style={{ width: 44, height: 44, borderRadius: 12, flexShrink: 0, display: "inline-flex", alignItems: "center", justifyContent: "center", background: `${color}1c`, color }}>
            <Icon d={SCALES} size={20} />
        </span>
    );
}

const ghostBtn = (t, extra = {}) => ({
    display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6,
    height: 38, padding: "0 16px", borderRadius: 10, border: `1px solid ${t.border}`,
    background: "transparent", color: t.text, fontSize: 13, fontWeight: 700, cursor: "pointer",
    fontFamily: "inherit", whiteSpace: "nowrap", ...extra,
});
const solidBtn = (bg, fg = "#0b1c22", extra = {}) => ({
    display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6,
    height: 38, padding: "0 16px", borderRadius: 10, border: "none", background: bg, color: fg,
    fontSize: 13, fontWeight: 800, cursor: "pointer", fontFamily: "inherit", whiteSpace: "nowrap", ...extra,
});

/** One CSV cell, quoted; a leading = + - @ is neutralised so Excel shows it as text. */
function csvCell(value) {
    let s = value == null ? "" : String(value);
    if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
    return `"${s.replace(/"/g, '""')}"`;
}

// ─────────────────────────────────────────────
// SHARED HELPERS: Modal, Input (field), Select, Textarea, Toast
// ─────────────────────────────────────────────
const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';

/** Focus for a modal dialog: moves in on open, Tab cycles inside, and focus
 *  goes back to whatever opened it on close. */
function useDialogFocus(panelRef) {
    useEffect(() => {
        const opener = document.activeElement;
        const node = panelRef.current;
        const items = () => [...(node?.querySelectorAll(FOCUSABLE) || [])];
        (items()[0] || node)?.focus?.();
        const onKey = (e) => {
            if (e.key !== "Tab" || !node) return;
            const list = items();
            if (!list.length) return;
            const first = list[0];
            const last = list[list.length - 1];
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        };
        node?.addEventListener("keydown", onKey);
        return () => {
            node?.removeEventListener("keydown", onKey);
            if (opener && typeof opener.focus === "function" && document.contains(opener)) opener.focus();
        };
    }, [panelRef]);
}

/**
 * A modal dialog: announced as one, focus kept inside, Escape closes it.
 * `busy`: a save is in flight, so Escape and outside clicks are ignored.
 * `backdropClose`: false keeps an outside click from dismissing it (a form
 * with typed input). An outside click counts only when the press also
 * STARTED outside: drag-selecting text and releasing past the edge used to
 * close the form and lose it.
 */
function Modal({ title, subtitle, onClose, children, width = 560, busy = false, backdropClose = true }) {
    const { t } = useTheme();
    const panel = useRef(null);
    const titleId = useId();
    const downOnBackdrop = useRef(false);
    useDialogFocus(panel);
    useEffect(() => {
        const esc = (e) => { if (e.key === "Escape" && !busy) onClose(); };
        window.addEventListener("keydown", esc);
        return () => window.removeEventListener("keydown", esc);
    }, [busy, onClose]);
    // Rendered into <body>. Inside the page, the backdrop sat in the content
    // column's stacking context (z-index 1, below the sticky sidebar's 10) and
    // under <main>'s animation transform: the sidebar stayed clickable behind
    // an open dialog, and one click navigated away and lost a typed form.
    return createPortal(
        <div data-drafting-theme data-cases-modal data-mode={draftingMode(t)}
            style={{ position: "fixed", inset: 0, zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(4,14,17,0.6)", backdropFilter: "blur(5px)", WebkitBackdropFilter: "blur(5px)" }}
            onMouseDown={e => { downOnBackdrop.current = e.target === e.currentTarget; }}
            onClick={e => {
                const fromBackdrop = downOnBackdrop.current && e.target === e.currentTarget;
                downOnBackdrop.current = false;
                if (fromBackdrop && backdropClose && !busy) onClose();
            }}>
            <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
                style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 16, padding: 26, width, maxWidth: "95vw", boxShadow: t.shadowCard, maxHeight: "90vh", overflowY: "auto", outline: "none" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                    <div>
                        <div id={titleId} className="serif" style={{ fontSize: 22, fontWeight: 700, color: t.text }}>{title}</div>
                        {subtitle && <div style={{ fontSize: 12, color: t.textMuted, marginTop: 3 }}>{subtitle}</div>}
                    </div>
                    <button type="button" onClick={() => { if (!busy) onClose(); }} disabled={busy} aria-label="Close" style={{ background: "none", border: "none", color: t.textMuted, cursor: "pointer", padding: 4, borderRadius: 6 }}><Icon d={I.x} size={16} /></button>
                </div>
                {children}
            </div>
        </div>,
        document.body,
    );
}

// Value-based: onChange receives the string. The shared components.jsx `Input`
// passes the DOM event and has no label, so labelled forms here must use this.
function FieldInput({ label, value, onChange, type = "text", placeholder, maxLength }) {
    const { t } = useTheme();
    return (
        <div>
            {label && <Label>{label}</Label>}
            <input type={type} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} maxLength={maxLength}
                style={{ width: "100%", height: 40, border: `1px solid ${t.border}`, borderRadius: 9, background: t.inputBg, color: t.text, fontSize: 14, padding: "0 14px", outline: "none", boxSizing: "border-box", colorScheme: t.mode }} />
        </div>
    );
}

function Select({ label, value, onChange, options = [] }) {
    const { t } = useTheme();
    return (
        <div>
            {label && <Label>{label}</Label>}
            <div style={{ position: "relative" }}>
                <select value={value} onChange={e => onChange(e.target.value)}
                    style={{ width: "100%", height: 40, border: `1px solid ${t.border}`, borderRadius: 9, background: t.inputBg, color: t.text, fontSize: 14, padding: "0 32px 0 14px", outline: "none", appearance: "none", cursor: "pointer", boxSizing: "border-box" }}>
                    {options.map(o => <option key={o.value} value={o.value} style={{ background: t.surface }}>{o.label}</option>)}
                </select>
                <div style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none", color: t.textMuted }}><Icon d={I.chevronDown} size={14} /></div>
            </div>
        </div>
    );
}

function Textarea({ label, value, onChange, rows = 4, placeholder, maxLength }) {
    const { t } = useTheme();
    return (
        <div>
            {label && <Label>{label}</Label>}
            <textarea value={value} onChange={e => onChange(e.target.value)} rows={rows} placeholder={placeholder} maxLength={maxLength}
                style={{ width: "100%", border: `1px solid ${t.border}`, borderRadius: 9, background: t.inputBg, color: t.text, fontSize: 14, padding: "9px 14px", outline: "none", resize: "vertical", lineHeight: 1.6, boxSizing: "border-box", fontFamily: "DM Sans, system-ui" }} />
        </div>
    );
}

function Toast({ msg }) {
    const { t } = useTheme();
    if (!msg) return null;
    return (
        <div style={{ position: "fixed", bottom: 28, left: "50%", transform: "translateX(-50%)", zIndex: 9999, background: t.card, border: `1px solid ${t.border}`, borderRadius: 10, padding: "10px 20px", fontSize: 13, color: t.text, boxShadow: t.shadowCard, animation: "fadeUp .25s ease" }}>
            {msg}
        </div>
    );
}

function useToast() {
    const [toast, setToast] = useState(null);
    // ONE timer. Each toast used to start its own and never cancel the last,
    // so an older toast's timer cleared a newer toast early.
    const timer = useRef(null);
    useEffect(() => () => clearTimeout(timer.current), []);
    const show = (msg, ms = 2800) => {
        clearTimeout(timer.current);
        setToast(msg);
        timer.current = setTimeout(() => setToast(null), ms);
    };
    return [toast, show];
}

const OUTCOME_OPTIONS = [
    ["adjourned", "Adjourned (new date given)"],
    ["arguments_heard", "Arguments heard"],
    ["evidence_recorded", "Evidence / witness recorded"],
    ["order_reserved", "Order / judgment reserved"],
    ["decided", "Decided / order announced"],
    ["judge_on_leave", "Judge on leave / bench not available"],
    ["other", "Other"],
];

// What usually has to happen after each outcome. Each item is [title, days]:
// with a next date, due that many days BEFORE it; without one, that many days
// from today. Every ticked item becomes a real task through the tasks route.
const OUTCOME_TASKS = {
    adjourned: [["Review the other side's latest filing", 5], ["Prepare for the next hearing", 2], ["Update the client before the next date", 1]],
    arguments_heard: [["Prepare a written synopsis of arguments", 3], ["Update the client", 1]],
    evidence_recorded: [["Prepare for the next witness / cross-examination", 3], ["Update the client", 1]],
    order_reserved: [["Follow up on the reserved order", 7]],
    decided: [["Apply for a certified copy of the order", 2], ["Discuss the order and appeal options with the client", 3]],
    judge_on_leave: [["Confirm the new date with the court reader", 1]],
    other: [],
};

const FEE_TYPE_OPTIONS = [
    { value: "fixed", label: "Fixed fee (whole case)" },
    { value: "hourly", label: "Per hour" },
    { value: "per_hearing", label: "Per hearing (peshi)" },
];

// Task checklists: each item becomes a real task through the tasks route.
const TASK_TEMPLATES = [
    { label: "Pre-hearing checklist (civil)", items: ["File vakalatnama", "Collect original documents from client", "Prepare list of witnesses", "Draft written arguments", "Prep meeting with client"] },
    { label: "Evidence stage", items: ["Prepare evidence affidavits", "Arrange witness attendance", "Mark documents for exhibit"] },
    { label: "Final arguments", items: ["Prepare final arguments brief", "Compile case law citations", "Share argument summary with client"] },
];

// ─────────────────────────────────────────────
// ENGAGEMENT ACTIONS — send terms, decline, complete, end
// ─────────────────────────────────────────────
function useEngagementActions(onChanged, showToast) {
    const [accepting, setAccepting] = useState(null);   // request being accepted (opens terms modal)
    const [feeAmount, setFeeAmount] = useState("");
    const [feeType, setFeeType] = useState("fixed");
    const [scopeNote, setScopeNote] = useState("");
    const [busy, setBusy] = useState(false);

    const openAccept = (req) => { setAccepting(req); setFeeAmount(""); setFeeType("fixed"); setScopeNote(""); };

    // Sends TERMS, and takes nothing. The case is not yours until the client
    // accepts these — they have to see the price before they are committed.
    const submitAccept = async () => {
        const amount = feeAmount === "" ? null : Number(feeAmount);
        if (amount === null || !Number.isFinite(amount) || amount < 0) {
            showToast("⚠️ Enter the fee you are proposing — the client has to see a price");
            return;
        }
        setBusy(true);
        const { error } = await proposeEngagementTerms(accepting.id, {
            fee_amount: amount, fee_type: feeType, scope_note: scopeNote.trim() || null,
        });
        setBusy(false);
        if (error) { showToast("❌ " + (error.message || "Failed to send terms")); return; }
        setAccepting(null);
        showToast("✅ Terms sent — the case is yours once the client accepts them");
        onChanged();
    };

    // One endpoint, two acts: declining a request, or withdrawing terms the
    // lawyer already sent. Each is named for what it is.
    const handleDecline = async (req) => {
        const withdrawing = req.status === "terms_proposed";
        const reason = window.prompt(withdrawing
            ? "Optional: tell the client why you're withdrawing your terms (leave blank to skip)"
            : "Optional: tell the client why you're declining (leave blank to skip)");
        if (reason === null) return;
        setBusy(true);
        const { error } = await declineEngagement(req.id, reason.trim() || null);
        setBusy(false);
        if (error) { showToast("❌ " + (error.message || (withdrawing ? "Could not withdraw the terms" : "Failed to decline"))); return; }
        showToast(withdrawing ? "Terms withdrawn — the client has been notified" : "Request declined — the client has been notified");
        onChanged();
    };

    const handleComplete = async (req) => {
        const note = window.prompt("Optional: a note about how the matter concluded");
        if (note === null) return;
        setBusy(true);
        const { data, error } = await completeEngagement(req.id, { note: note.trim() || null });
        setBusy(false);
        if (error) { showToast("❌ " + (error.message || "Could not complete")); return; }
        showToast(data?.status === "completed" ? "✅ Engagement completed" : "Completion proposed — the client needs to confirm");
        onChanged();
    };

    const handleTerminate = async (req) => {
        const reason = window.prompt(
            "Ending this engagement releases the case back to the client.\n\n" +
            "Give a reason (required — it is recorded and shown to them):"
        );
        if (reason === null) return;
        if (!reason.trim()) { showToast("⚠️ A reason is required"); return; }
        setBusy(true);
        const { error } = await terminateEngagement(req.id, reason.trim());
        setBusy(false);
        if (error) { showToast("❌ " + (error.message || "Could not end the engagement")); return; }
        showToast("Engagement ended — the client has been notified");
        onChanged();
    };

    const termsModal = accepting && (
        <Modal title="Send your terms"
            subtitle={`${accepting.case_title || "This case"} — the client reviews these and decides. The case becomes yours when they accept.`}
            onClose={() => setAccepting(null)} width={480}>
            <TermsForm feeAmount={feeAmount} setFeeAmount={setFeeAmount} feeType={feeType} setFeeType={setFeeType}
                scopeNote={scopeNote} setScopeNote={setScopeNote} busy={busy}
                onCancel={() => setAccepting(null)} onSubmit={submitAccept} />
        </Modal>
    );
    return { busy, openAccept, handleDecline, handleComplete, handleTerminate, termsModal };
}

function TermsForm({ feeAmount, setFeeAmount, feeType, setFeeType, scopeNote, setScopeNote, busy, onCancel, onSubmit }) {
    const { t: T } = useTheme();
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ fontSize: 12, color: T.textMuted, background: T.primaryGlow2, border: `1px solid color-mix(in srgb, ${T.primary} 19%, transparent)`, borderRadius: 10, padding: "10px 12px", lineHeight: 1.6 }}>
                Nothing is assigned yet. The client sees this fee before agreeing to it,
                and the case is assigned to you only when they accept these terms.
            </div>
            <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <FieldInput label="Fee (PKR)" type="number" value={feeAmount} onChange={setFeeAmount} placeholder="e.g. 50000" />
                <Select label="Fee Type" value={feeType} onChange={setFeeType} options={FEE_TYPE_OPTIONS} />
            </div>
            <Textarea label="Scope Note (optional)" rows={3} value={scopeNote} onChange={setScopeNote}
                placeholder="What the engagement covers — e.g. representation through trial, drafting, hearings…" />
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
                <Btn variant="ghost" onClick={onCancel}>Cancel</Btn>
                <Btn variant="accent" disabled={busy} onClick={onSubmit}>{busy ? "Sending…" : "Send Terms to Client"}</Btn>
            </div>
        </div>
    );
}

// ─────────────────────────────────────────────
// CASES LIST
// ─────────────────────────────────────────────
const OPEN_REQUEST = ["requested", "terms_proposed"];

// Funnel and sort glyphs (not in the shared icon set).
const FILTER_ICON = "M3 5h18l-7 8.5V19l-4 2v-7.5L3 5z";
const SORT_ICON = "M4 6h16M7 12h10M10 18h4";

const SORTS = [
    ["hearing", "Next hearing"],
    ["newest", "Newest first"],
    ["title", "Title A–Z"],
    ["client", "Client A–Z"],
];
// Sorters: see lib/casesView.js (CASE_SORTERS / REQUEST_SORTERS).

/** A small dropdown anchored under its button; closes on outside click or Escape. */
function BarMenu({ label, icon, badge, children, width = 240 }) {
    const { t: T } = useTheme();
    const [open, setOpen] = useState(false);
    const box = useRef(null);
    useEffect(() => {
        if (!open) return undefined;
        const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
        const esc = (e) => { if (e.key === "Escape") setOpen(false); };
        document.addEventListener("mousedown", away);
        document.addEventListener("keydown", esc);
        return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
    }, [open]);
    return (
        <div ref={box} style={{ position: "relative" }}>
            <button type="button" aria-haspopup="true" aria-expanded={open} onClick={() => setOpen(o => !o)}
                style={ghostBtn(T, { height: 44, padding: "0 16px", borderRadius: 12, gap: 8, background: open ? "rgba(56,216,196,0.08)" : "transparent", borderColor: open || badge ? TEAL + "77" : T.border })}>
                <Icon d={icon} size={15} />
                {label}
                {badge ? <span style={{ minWidth: 20, height: 20, padding: "0 6px", borderRadius: 999, background: TEAL, color: "#0b1c22", fontSize: 11, fontWeight: 800, display: "inline-flex", alignItems: "center", justifyContent: "center" }}>{badge}</span> : null}
                <Icon d={I.chevronDown} size={13} />
            </button>
            {open && (
                <div role="menu" aria-label={label} style={{
                    position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 30, width,
                    padding: 8, borderRadius: 14, border: `1px solid ${T.border}`, background: T.surface,
                    boxShadow: "0 14px 40px rgba(0,0,0,0.35)",
                }}>
                    {typeof children === "function" ? children(() => setOpen(false)) : children}
                </div>
            )}
        </div>
    );
}

const CASE_TYPES = [["civil", "Civil"], ["criminal", "Criminal"], ["family", "Family"], ["constitutional", "Constitutional"]];
const PROVINCES = [["punjab", "Punjab"], ["sindh", "Sindh"], ["kpk", "Khyber Pakhtunkhwa"], ["balochistan", "Balochistan"], ["federal", "Federal / Islamabad"]];

// The Filter panel's order and short labels, two per row. Short names keep
// the tiles one consistent width; the full name is the tile's tooltip.
const FILTER_TYPES = [["civil", "Civil"], ["criminal", "Criminal"], ["constitutional", "Constitutional"], ["family", "Family"]];
const FILTER_PROVINCES = [["punjab", "Punjab"], ["sindh", "Sindh"], ["kpk", "KPK", "Khyber Pakhtunkhwa"],
    ["balochistan", "Balochistan"], ["federal", "Federal / Islamabad"]];

/** An id for one submission: 32 url-safe characters. */
function newRequestId() {
    const c = globalThis.crypto;
    if (c?.randomUUID) return c.randomUUID().replace(/-/g, "");
    const bytes = new Uint8Array(16);
    if (c?.getRandomValues) c.getRandomValues(bytes);
    else for (let i = 0; i < 16; i += 1) bytes[i] = Math.floor(Math.random() * 256);
    return [...bytes].map(b => b.toString(16).padStart(2, "0")).join("");
}

/** A server refusal as one readable line (a 422 carries a list of field errors). */
function refusalText(error, fallback) {
    const d = error?.detail;
    if (Array.isArray(d) && d.length) {
        return d.map(x => `${(x.loc || []).slice(-1)[0] || "field"}: ${String(x.msg || "").replace(/^Value error,\s*/i, "")}`).join("; ");
    }
    return error?.message || (typeof d === "string" ? d : "") || fallback;
}

/** + New case: a case for a client who is not on Attorney.AI (walk-in or
 *  phone client). The lawyer owns it; there is no client account, so it has
 *  no message thread and no client notifications. */
function NewCaseModal({ onClose, onCreated }) {
    const { t: T } = useTheme();
    const [f, setF] = useState({ title: "", case_type: "civil", province: "punjab", client_name: "", client_phone: "", court: "", court_case_number: "", description: "" });
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const set = (k) => (v) => { setF(p => ({ ...p, [k]: v })); setError(null); };
    // Anything typed? Then an outside click does not discard it, and Escape or
    // Cancel ask first.
    const dirty = Object.entries(f).some(([k, v]) => v !== (k === "case_type" ? "civil" : k === "province" ? "punjab" : ""));
    const requestClose = () => {
        if (busy) return;
        if (dirty && !window.confirm("Discard this new case? What you typed will be lost.")) return;
        onClose();
    };

    const submit = async () => {
        if (busy) return;
        if (f.title.trim().length < 3) { setError("Give the case a title (at least 3 characters)."); return; }
        if (f.client_name.trim().length < 2) { setError("Enter the client's name."); return; }
        if (f.client_phone.trim() && !/^\+?[0-9][0-9 -]{6,18}$/.test(f.client_phone.trim())) { setError("Enter the phone number as digits, e.g. +92 300 1234567."); return; }
        setBusy(true);
        const opt = (v) => (v.trim() ? v.trim() : null);
        const { data, error: err } = await createWalkInCase({
            title: f.title.trim(), case_type: f.case_type, province: f.province,
            client_name: f.client_name.trim(), client_phone: opt(f.client_phone),
            court: opt(f.court), court_case_number: opt(f.court_case_number), description: f.description.trim(),
        });
        setBusy(false);
        if (err || !data) { setError(refusalText(err, "Could not create the case. Try again.")); return; }
        onCreated(data);
    };

    return (
        <Modal title="New case" subtitle="For a client who is not on Attorney.AI — walk-in or phone." onClose={requestClose} width={600}
            busy={busy} backdropClose={!dirty}>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <FieldInput label="Case title *" value={f.title} onChange={set("title")} placeholder="e.g. Rent recovery — Mr. Aslam" />
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    <Select label="Case type *" value={f.case_type} onChange={set("case_type")} options={CASE_TYPES.map(([value, label]) => ({ value, label }))} />
                    <Select label="Province *" value={f.province} onChange={set("province")} options={PROVINCES.map(([value, label]) => ({ value, label }))} />
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    <FieldInput label="Client name *" value={f.client_name} onChange={set("client_name")} placeholder="Full name" />
                    <FieldInput label="Client phone" value={f.client_phone} onChange={set("client_phone")} placeholder="+92 300 1234567" />
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    <FieldInput label="Court" value={f.court} onChange={set("court")} placeholder="e.g. Civil Court Lahore" maxLength={200} />
                    <FieldInput label="Court case no." value={f.court_case_number} onChange={set("court_case_number")} placeholder="e.g. 1234/2026" />
                </div>
                <Textarea label="Notes" value={f.description} onChange={set("description")} rows={3} placeholder="What the matter is about (optional)" />
                <div style={{ fontSize: 12, color: T.textMuted, lineHeight: 1.5 }}>
                    The case is yours from the start. Add the first hearing from the case once it is created. There is no client account, so messages and client notifications are not available on it.
                </div>
                {error && <div role="alert" style={{ fontSize: 13, color: RED }}>{error}</div>}
                <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                    <button type="button" onClick={requestClose} disabled={busy} style={ghostBtn(T)}>Cancel</button>
                    <button type="button" onClick={submit} disabled={busy} style={solidBtn(TEAL, "#0b1c22", { opacity: busy ? 0.6 : 1 })}>{busy ? "Creating…" : "Create case"}</button>
                </div>
            </div>
        </Modal>
    );
}

/** The Filter panel. Choices are a DRAFT until Apply: the count previews
 *  what Apply would show, and closing without applying changes nothing. */
function FilterPanel({ groups, initial, countFor, total, onApply }) {
    const { t: T } = useTheme();
    const [draft, setDraft] = useState(initial);      // { types: [], provinces: [] }
    const flip = (field, key) => setDraft(d => ({
        ...d, [field]: d[field].includes(key) ? d[field].filter(x => x !== key) : [...d[field], key],
    }));
    const picked = draft.types.length + draft.provinces.length;
    const shown = countFor(draft);

    return (
        <div data-filter-panel style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 6px 14px", borderBottom: `1px solid ${T.border}` }}>
                <span style={{ fontSize: 16, fontWeight: 800, color: T.text }}>Filters</span>
                <button type="button" disabled={!picked} onClick={() => setDraft({ types: [], provinces: [] })}
                    style={{ background: "none", border: "none", padding: 0, fontSize: 12.5, fontWeight: 700, fontFamily: "inherit",
                             color: picked ? TEAL : T.textFaint, cursor: picked ? "pointer" : "default" }}>Clear all</button>
            </div>
            {groups.map(({ head, field, options }) => {
                const sel = draft[field];
                return (
                    <div key={field} role="group" aria-label={head} style={{ padding: "14px 6px 2px" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 10 }}>
                            <span style={{ fontSize: 11.5, fontWeight: 800, letterSpacing: "0.12em", textTransform: "uppercase", color: T.textMuted }}>{head}</span>
                            {sel.length > 0 && <span style={{ fontSize: 12, color: TEAL, fontWeight: 700 }}>{sel.length} selected</span>}
                        </div>
                        {/* Two equal columns filling a panel that is itself only as wide as
                            its widest row: every tile shares one width, and there is no dead
                            space at the panel's right edge. */}
                        <div data-option-grid style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(max-content, 1fr))", gap: 8 }}>
                            {options.map((o, i) => {
                                const on = sel.includes(o.key);
                                // An odd last tile takes the whole row (Federal / Islamabad).
                                const span = options.length % 2 === 1 && i === options.length - 1;
                                return (
                                    <button key={o.key} type="button" role="checkbox" aria-checked={on} data-option={o.key}
                                        title={o.full || o.label} onClick={() => flip(field, o.key)} style={{
                                            gridColumn: span ? "1 / -1" : undefined,
                                            display: "flex", alignItems: "center", gap: 8, height: 36, padding: "0 8px 0 10px", width: "100%", boxSizing: "border-box",
                                            borderRadius: 10, fontFamily: "inherit", cursor: "pointer", textAlign: "left",
                                            border: `1px solid ${on ? TEAL : T.border}`,
                                            background: on ? "rgba(56,216,196,0.12)" : "rgba(255,255,255,0.02)",
                                            boxShadow: on ? `0 0 0 1px ${TEAL}33 inset` : "none",
                                            transition: "background .12s, border-color .12s",
                                        }}>
                                        <span aria-hidden style={{
                                            width: 15, height: 15, flexShrink: 0, borderRadius: "50%", display: "inline-flex", alignItems: "center", justifyContent: "center",
                                            border: on ? "none" : `1.5px solid ${T.textFaint}`, background: on ? TEAL : "transparent",
                                        }}>{on && <Icon d={I.check} size={9} style={{ color: "#0b1c22" }} />}</span>
                                        <span style={{ fontSize: 13, fontWeight: on ? 700 : 600, color: on ? T.text : o.n ? T.textDim : T.textFaint, whiteSpace: "nowrap" }}>{o.label}</span>
                                        <span style={{ marginLeft: "auto", minWidth: 20, height: 18, padding: "0 5px", borderRadius: 6, flexShrink: 0, display: "inline-flex", alignItems: "center", justifyContent: "center",
                                                       fontSize: 10.5, fontWeight: 800, background: on ? "rgba(56,216,196,0.22)" : "rgba(255,255,255,0.07)", color: on ? TEAL : T.textMuted }}>{o.n}</span>
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                );
            })}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginTop: 14, padding: "12px 6px 4px", borderTop: `1px solid ${T.border}` }}>
                <span aria-live="polite" style={{ fontSize: 13, color: T.textMuted }}>
                    Showing <strong style={{ color: T.text }}>{shown}</strong> of {total} results
                </span>
                <button type="button" onClick={() => onApply(draft)}
                    style={solidBtn(TEAL, "#0b1c22", { height: 38, padding: "0 22px", borderRadius: 10, fontSize: 13.5, boxShadow: `0 4px 14px ${TEAL}33` })}>Apply</button>
            </div>
        </div>
    );
}

/* The Cases list's look (2026-10-09): the lawyer document theme
 * (draftingTheme.js), scoped by [data-cases-home] so it reaches no other
 * screen. Layout after the "Cases Workspace v2" design: a week-in-court strip,
 * ONE search (Ctrl K), the filter bar, then the cases grouped by what to do
 * next, each with its stage and its next date. */
/* The case workspace: the theme's type and ground only; its own layout is unchanged. */
export const CASES_WS_CSS = `[data-cases-ws]{height:100%;color:var(--ink);font-family:"Hanken Grotesk",system-ui,sans-serif;background:radial-gradient(900px 360px at 25% -80px,var(--glow),transparent 70%) no-repeat,var(--bg);-webkit-font-smoothing:antialiased}
[data-cases-ws] > div:not([data-cases-home]){background:transparent!important}
[data-cases-ws] > div:not([data-cases-home]) > *{flex-shrink:0}
[data-cases-modal]{font-family:"Hanken Grotesk",system-ui,sans-serif;color:var(--ink);-webkit-font-smoothing:antialiased}
[data-cases-ws] .serif,[data-cases-modal] .serif{font-family:"Literata",Georgia,serif!important;letter-spacing:-.01em}
[data-cases-ws] input,[data-cases-ws] select,[data-cases-ws] textarea,[data-cases-modal] input,[data-cases-modal] select,[data-cases-modal] textarea{font-family:inherit}
[data-cases-ws] button,[data-cases-modal] button{font-family:inherit}
[data-cases-ws] .cw{--green:#3ec99a;--violet:#9b8cf0}
[data-cases-ws] .cw-crumbs{display:flex;align-items:center;gap:8px;font-size:14px;color:var(--muted)}
[data-cases-ws] .cw-crumbs button{display:inline-flex;align-items:center;gap:4px;background:none;border:0;padding:0;color:var(--muted);font:inherit;cursor:pointer}
[data-cases-ws] .cw-crumbs button:hover{color:var(--hover-ink)}
[data-cases-ws] .cw-crumbs b{font:600 14px "JetBrains Mono",monospace;color:var(--brand-text)}
[data-cases-ws] .cw-head{border-radius:20px;border:1px solid var(--line);background:var(--surface);box-shadow:var(--shadow-rest);padding:22px 24px 18px}
[data-cases-ws] .cw-head-top{display:flex;align-items:flex-start;gap:18px}
[data-cases-ws] .cw-tile{width:56px;height:56px;flex:none;border-radius:16px;display:grid;place-items:center;color:var(--brand-text);background:var(--surface-2);border:1px solid var(--line)}
[data-cases-ws] .cw-head h1{margin:0;font-size:34px;line-height:1.1;font-weight:600}
[data-cases-ws] .cw-meta{display:flex;flex-wrap:wrap;align-items:center;gap:8px 18px;margin-top:10px;font-size:14px;color:var(--muted)}
[data-cases-ws] .cw-m{display:inline-flex;align-items:center;gap:6px;color:var(--ink)}
[data-cases-ws] .cw-m svg{color:var(--muted)}
[data-cases-ws] .cw-pill{display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 11px;border-radius:999px;font-size:13px;font-weight:700;color:var(--brand-text);background:color-mix(in srgb,var(--brand-text) 13%,transparent);border:1px solid color-mix(in srgb,var(--brand-text) 35%,transparent)}
[data-cases-ws] .cw-pill i,[data-cases-ws] .cw-tag i{width:6px;height:6px;border-radius:50%;background:currentColor}
[data-cases-ws] .cw-pill.gold{color:var(--gold);background:color-mix(in srgb,var(--gold) 14%,transparent);border-color:color-mix(in srgb,var(--gold) 40%,transparent)}
[data-cases-ws] .cw-pill.red{color:var(--danger);background:var(--danger-soft);border-color:color-mix(in srgb,var(--danger) 40%,transparent)}
[data-cases-ws] .cw-pill.muted{color:var(--muted);background:var(--chip-n);border-color:var(--line)}
[data-cases-ws] .cw-actions{display:flex;gap:10px;flex:none}
[data-cases-ws] .cw-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;height:42px;padding:0 16px;border-radius:12px;border:1px solid var(--line-strong);background:var(--surface);color:var(--ink);font:inherit;font-size:14px;font-weight:700;cursor:pointer;white-space:nowrap;transition:border-color .15s,background .15s,color .15s}
[data-cases-ws] .cw-btn:hover:not(:disabled){border-color:var(--hover-line);background:var(--hover-tint);color:var(--hover-ink)}
[data-cases-ws] .cw-btn:disabled,[data-cases-ws] .cw-cta:disabled{opacity:.5;cursor:not-allowed}
[data-cases-ws] .cw-btn.danger{color:var(--danger)}
[data-cases-ws] .cw-btn.danger:hover:not(:disabled){background:var(--danger-soft);border-color:var(--danger);color:var(--danger)}
[data-cases-ws] .cw-cta{display:inline-flex;align-items:center;justify-content:center;gap:8px;height:42px;padding:0 18px;border-radius:12px;border:0;background:var(--brand-solid);color:var(--on-brand);font:inherit;font-size:14px;font-weight:700;cursor:pointer;white-space:nowrap;box-shadow:0 10px 22px -12px rgba(46,196,214,.8);transition:transform .15s,background .15s}
[data-cases-ws] .cw-cta:hover:not(:disabled){background:var(--brand-solid-hover);transform:translateY(-1px)}
[data-cases-ws] .cw-cta.gold{background:var(--gold);color:#241a05;box-shadow:none}
[data-cases-ws][data-mode="light"] .cw-cta.gold{color:#fff}
[data-cases-ws] .cw-stages{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-top:20px}
[data-cases-ws] .cw-stages > div{display:flex;flex-direction:column;gap:4px;min-width:0}
[data-cases-ws] .cw-stages i{height:5px;border-radius:3px;background:var(--line-strong);margin-bottom:8px}
[data-cases-ws] .cw-stages .done i{background:var(--green)}
[data-cases-ws] .cw-stages .now i{background:var(--teal-ink);box-shadow:0 0 0 3px color-mix(in srgb,var(--teal-ink) 25%,transparent)}
[data-cases-ws] .cw-stages b{font-size:13.5px;font-weight:500;color:var(--muted)}
[data-cases-ws] .cw-stages .done b{color:var(--ink)}
[data-cases-ws] .cw-stages .now b{color:var(--ink);font-weight:700}
[data-cases-ws] .cw-stages small{font-size:12px;color:var(--muted)}
[data-cases-ws] .cw-note{padding:12px 18px;border-radius:14px;border:1px solid var(--line);background:var(--chip-n);font-size:13.5px;color:var(--muted)}
[data-cases-ws] .cw-note strong{color:var(--ink)}
[data-cases-ws] .cw-tabs{display:flex;gap:6px;border-bottom:1px solid var(--line)}
[data-cases-ws] .cw-tabs button{display:inline-flex;align-items:center;gap:8px;padding:12px 16px;margin-bottom:-1px;border:0;border-bottom:2px solid transparent;background:none;color:var(--muted);font:inherit;font-size:15px;font-weight:600;cursor:pointer}
[data-cases-ws] .cw-tabs button:hover{color:var(--hover-ink)}
[data-cases-ws] .cw-tabs button[aria-selected="true"]{color:var(--ink);font-weight:700;border-bottom-color:var(--brand-text)}
[data-cases-ws] .cw-n{min-width:20px;height:20px;padding:0 6px;border-radius:999px;display:inline-flex;align-items:center;justify-content:center;font:600 11px "JetBrains Mono",monospace;background:var(--chip-n);color:var(--muted)}
[data-cases-ws] .cw-n.hot{background:color-mix(in srgb,var(--gold) 25%,transparent);color:var(--gold)}
[data-cases-ws] .cw-split{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:18px;align-items:start}
[data-cases-ws] .cw-col{display:flex;flex-direction:column;gap:14px;min-width:0}
[data-cases-ws] .cw-card{border-radius:18px;border:1px solid var(--line);background:var(--surface);box-shadow:var(--shadow-rest);padding:18px 20px}
[data-cases-ws] .cw-card.cw-flush{padding:0;overflow:hidden}
[data-cases-ws] .cw-lead{padding:22px}
[data-cases-ws] .cw-lead.red{border-color:color-mix(in srgb,var(--danger) 40%,var(--line))}
[data-cases-ws] .cw-lead.gold{border-color:color-mix(in srgb,var(--gold) 40%,var(--line))}
[data-cases-ws] .cw-lead h2{margin:8px 0 0;font-size:26px;line-height:1.2;font-weight:600}
[data-cases-ws] .cw-label{font-size:11.5px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
[data-cases-ws] .cw-label.brand{color:var(--brand-text)}
[data-cases-ws] .cw-label.gold{color:var(--gold)}
[data-cases-ws] .cw-label.red{color:var(--danger)}
[data-cases-ws] .cw-muted{color:var(--muted);font-size:13.5px;line-height:1.5;margin:6px 0 0}
[data-cases-ws] .cw-row-btns{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap}
[data-cases-ws] .cw-form{display:grid;gap:10px;margin-top:14px;align-items:end}
[data-cases-ws] .cw-form input{background:var(--input)!important}
[data-cases-ws] .cw-next{display:flex;align-items:center;gap:16px;margin-top:16px}
[data-cases-ws] .cw-when{font-size:16px;font-weight:700}
[data-cases-ws] .cap{display:inline-block}
[data-cases-ws] .cap::first-letter{text-transform:uppercase}
[data-cases-ws] .cw-date{width:66px;flex:none;display:flex;flex-direction:column;align-items:center;border-radius:12px;overflow:hidden;border:1px solid var(--line);background:var(--surface-2)}
[data-cases-ws] .cw-date i{display:block;width:100%;text-align:center;font:700 12px/22px "Hanken Grotesk",sans-serif;letter-spacing:.08em;color:var(--on-brand);background:var(--brand-solid)}
[data-cases-ws] .cw-date.green i{background:var(--green);color:#0b1c22}
[data-cases-ws] .cw-date.red i{background:var(--danger);color:#fff}
[data-cases-ws] .cw-date b{font-size:28px;line-height:1.25;font-weight:600;padding-top:4px}
[data-cases-ws] .cw-date small{font-size:11px;font-weight:700;letter-spacing:.08em;color:var(--muted);padding-bottom:6px}
[data-cases-ws] .cw-date:not(:has(small)) b{padding-bottom:6px}
[data-cases-ws] .cw-links{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
[data-cases-ws] .cw-link-card{display:flex;align-items:center;gap:10px;height:52px;padding:0 16px;border-radius:14px;border:1px solid var(--line);background:var(--surface);color:var(--ink);font:inherit;font-size:14.5px;font-weight:600;cursor:pointer;transition:border-color .15s,transform .15s,background .15s}
[data-cases-ws] .cw-link-card svg{color:var(--brand-text);transition:transform .3s cubic-bezier(.34,1.56,.64,1)}
[data-cases-ws] .cw-link-card:hover{border-color:var(--hover-line);background:var(--hover-tint);transform:translateY(-1px)}
[data-cases-ws] .cw-link-card:hover svg{transform:scale(1.15) rotate(-6deg)}
[data-cases-ws] .cw-card-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
[data-cases-ws] .cw-textlink{background:none;border:0;padding:0;color:var(--brand-text);font:inherit;font-size:13px;font-weight:700;cursor:pointer}
[data-cases-ws] .cw-textlink:hover{color:var(--hover-ink);text-decoration:underline;text-underline-offset:3px}
[data-cases-ws] .cw-tl{display:flex;align-items:flex-start;gap:14px;padding:12px 0;border-bottom:1px solid var(--line)}
[data-cases-ws] .cw-tl:last-child{border-bottom:0}
[data-cases-ws] .cw-tl-when{width:74px;flex:none;text-align:right}
[data-cases-ws] .cw-tl-when b{display:block;font-size:14px}
[data-cases-ws] .cw-tl-when span{display:block;font-size:12px;color:var(--muted)}
[data-cases-ws] .cw-tl-when span.late{color:var(--danger)}
[data-cases-ws] .cw-ring{width:11px;height:11px;flex:none;margin-top:5px;border-radius:50%;border:2px solid var(--brand-text)}
[data-cases-ws] .cw-ring.gold{border-color:var(--gold)}
[data-cases-ws] .cw-ring.red{border-color:var(--danger)}
[data-cases-ws] .cw-ring.green{border-color:var(--green)}
[data-cases-ws] .cw-ring.violet{border-color:var(--violet)}
[data-cases-ws] .cw-tl-title{font-size:14.5px;font-weight:600;color:var(--ink)}
[data-cases-ws] .cw-tl-sub{font-size:12.5px;color:var(--muted);margin-top:2px}
[data-cases-ws] .cw-tl-sub.late{color:var(--danger)}
[data-cases-ws] .cw-tag{display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 10px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap;color:var(--brand-text);background:color-mix(in srgb,var(--brand-text) 13%,transparent);border:1px solid color-mix(in srgb,var(--brand-text) 30%,transparent)}
[data-cases-ws] .cw-tag.gold{color:var(--gold);background:color-mix(in srgb,var(--gold) 14%,transparent);border-color:color-mix(in srgb,var(--gold) 35%,transparent)}
[data-cases-ws] .cw-tag.red{color:var(--danger);background:var(--danger-soft);border-color:color-mix(in srgb,var(--danger) 35%,transparent)}
[data-cases-ws] .cw-tag.green{color:var(--green);background:color-mix(in srgb,var(--green) 14%,transparent);border-color:color-mix(in srgb,var(--green) 35%,transparent)}
[data-cases-ws] .cw-file{display:flex;align-items:center;gap:16px;margin:12px 0 8px}
[data-cases-ws] .cw-big{font-size:30px;font-weight:600;line-height:1}
[data-cases-ws] .cw-check{display:flex;align-items:center;gap:10px;padding:7px 0;font-size:14px}
[data-cases-ws] .cw-box{width:20px;height:20px;flex:none;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;border:1.5px dashed var(--faint);background:transparent;color:#0b1c22;padding:0}
[data-cases-ws] .cw-box.on{border:0;background:var(--green)}
[data-cases-ws] .cw-box.big{width:24px;height:24px;border-style:solid;border-color:var(--line-strong);cursor:pointer}
[data-cases-ws] .cw-box.big.on{border:0}
[data-cases-ws] .cw-box.big:disabled{cursor:default}
[data-cases-ws] .cw-client{display:flex;align-items:center;gap:12px;margin-top:12px}
[data-cases-ws] .cw-client b{display:block;font-size:15.5px}
[data-cases-ws] .cw-client span{display:block;font-size:12.5px;color:var(--muted)}
[data-cases-ws] .cw-facts{margin:10px 0 0;display:grid;gap:9px}
[data-cases-ws] .cw-facts > div{display:flex;justify-content:space-between;gap:12px;font-size:13.5px}
[data-cases-ws] .cw-facts dt{color:var(--muted)}
[data-cases-ws] .cw-facts dd{margin:0;text-align:right;color:var(--ink)}
[data-cases-ws] .cw-facts dd.mono{font-family:"JetBrains Mono",monospace;color:var(--brand-text)}
[data-cases-ws] .cw-band{display:flex;justify-content:space-between;padding:12px 20px;font-size:11.5px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);background:var(--surface-2);border-top:1px solid var(--line)}
[data-cases-ws] .cw-flush > .cw-band:first-child{border-top:0}
[data-cases-ws] .cw-band.red{color:var(--danger)}
[data-cases-ws] .cw-empty{padding:22px 20px;font-size:13.5px;color:var(--muted);text-align:center}
[data-cases-ws] .cw-hrow{display:flex;align-items:center;gap:16px;padding:14px 20px;border-top:1px solid var(--line)}
[data-cases-ws] .cw-hrow .cw-date{width:60px}
[data-cases-ws] .cw-chat{display:flex;flex-direction:column;min-height:480px}
[data-cases-ws] .cw-chat-head{display:flex;align-items:center;gap:12px;padding:14px 18px;border-bottom:1px solid var(--line)}
[data-cases-ws] .cw-chat-head b{display:block;font-size:15.5px}
[data-cases-ws] .cw-chat-head span{display:block;font-size:12.5px;color:var(--muted)}
[data-cases-ws] .cw-chat-body{flex:1;display:flex;flex-direction:column;gap:12px;padding:18px;max-height:460px;overflow-y:auto;background:var(--surface-2)}
[data-cases-ws] .cw-msg{display:flex;gap:10px;align-items:flex-start}
[data-cases-ws] .cw-msg.mine{justify-content:flex-end}
[data-cases-ws] .cw-bubble{max-width:70%;padding:10px 14px;border-radius:14px;background:var(--surface);border:1px solid var(--line);font-size:14px;line-height:1.55}
[data-cases-ws] .cw-msg.mine .cw-bubble{background:var(--brand-soft);border-color:color-mix(in srgb,var(--brand-text) 30%,transparent)}
[data-cases-ws] .cw-bubble small{display:block;margin-top:4px;font-size:11.5px;color:var(--muted)}
[data-cases-ws] .cw-chat-foot{padding:12px 18px 16px;border-top:1px solid var(--line)}
[data-cases-ws] .cw-chips{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}
[data-cases-ws] .cw-chips button{height:32px;padding:0 13px;border-radius:999px;border:1px solid var(--line-strong);background:var(--surface);color:var(--ink);font:inherit;font-size:12.5px;font-weight:600;cursor:pointer}
[data-cases-ws] .cw-chips button:hover{border-color:var(--hover-line);background:var(--hover-tint);color:var(--hover-ink)}
[data-cases-ws] .cw-compose{display:flex;gap:10px}
[data-cases-ws] .cw-compose input{flex:1;min-width:0;height:44px;padding:0 14px;border-radius:12px;border:1px solid var(--line-strong);background:var(--input);color:var(--ink);font:inherit;font-size:14px;outline:none}
[data-cases-ws] .cw-compose input:focus{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-cases-ws] .cw-compose input[type="date"]{color-scheme:light dark}
[data-cases-ws] .cw-pin{margin-top:10px;padding:12px 14px;border-radius:12px;border:1px solid var(--line);background:var(--surface-2)}
[data-cases-ws] .cw-pin b{display:block;font-size:14px}
[data-cases-ws] .cw-pin span{display:block;font-size:12.5px;color:var(--muted);margin-top:3px}
[data-cases-ws] .cw-progress{display:flex;align-items:center;gap:20px}
[data-cases-ws] .cw-bar{height:8px;border-radius:6px;background:var(--line-strong);overflow:hidden}
[data-cases-ws] .cw-bar i{display:block;height:100%;border-radius:6px;background:var(--green);transition:width .3s}
[data-cases-ws] .cw-task{display:flex;align-items:center;gap:14px;padding:13px 20px;border-top:1px solid var(--line)}
[data-cases-ws] .cw-task-title{font-size:15px;font-weight:600}
[data-cases-ws] .cw-task-title.done{color:var(--muted);text-decoration:line-through}
[data-cases-ws] .cw-due{font-size:13px;font-weight:600;color:var(--muted);white-space:nowrap}
[data-cases-ws] .cw-due.soon{color:var(--gold)}
[data-cases-ws] .cw-due.late{color:var(--danger)}
[data-cases-ws] .cw-tpl{display:flex;align-items:center;gap:12px;width:100%;margin-top:10px;padding:13px 14px;border-radius:12px;border:1px solid var(--line);background:var(--surface-2);color:var(--ink);font:inherit;text-align:left;cursor:pointer;transition:border-color .15s,background .15s}
[data-cases-ws] .cw-tpl:hover:not(:disabled){border-color:var(--hover-line);background:var(--hover-tint)}
[data-cases-ws] .cw-tpl b{display:block;font-size:14.5px}
[data-cases-ws] .cw-tpl small{display:block;font-size:12.5px;color:var(--muted);margin-top:2px}
[data-cases-ws] .cw-tpl svg{color:var(--brand-text);transition:transform .25s}
[data-cases-ws] .cw-tpl:hover svg{transform:rotate(90deg)}
[data-cases-ws] .cw-doc{display:flex;align-items:center;gap:16px;padding:16px 20px;border-top:1px solid var(--line)}
[data-cases-ws] .cw-flush > .cw-doc:first-child{border-top:0}
[data-cases-ws] .cw-paper{width:40px;height:50px;flex:none;border-radius:4px;background:#FBF8EF;box-shadow:0 2px 6px rgba(0,0,0,.25);display:flex;flex-direction:column;justify-content:center;gap:5px;padding:0 8px}
[data-cases-ws] .cw-paper i{display:block;height:2px;border-radius:1px;background:rgba(40,60,70,.3)}
[data-cases-ws] .cw-paper i:last-child{width:60%}
/* Light mode: the accent teal (#38d8c4) is too pale for TEXT on a light ground; inline text in it reads in the theme's darker brand teal. Teal-filled buttons keep it. */
[data-cases-ws][data-mode="light"] [style*="color: rgb(56, 216, 196)"]:not([style*="background: rgb(56, 216, 196)"]):not([style*="background-color: rgb(56, 216, 196)"]),[data-cases-modal][data-mode="light"] [style*="color: rgb(56, 216, 196)"]:not([style*="background: rgb(56, 216, 196)"]):not([style*="background-color: rgb(56, 216, 196)"]){color:var(--brand-text)!important}`;

export const CASES_HOME_CSS = `[data-cases-home]{color:var(--ink);font:15px/1.5 "Hanken Grotesk",system-ui,sans-serif;-webkit-font-smoothing:antialiased;background:radial-gradient(900px 360px at 25% -80px,var(--glow),transparent 70%) no-repeat,var(--bg)}
[data-cases-home] *{box-sizing:border-box}
[data-cases-home] :focus-visible{outline:2px solid var(--focus);outline-offset:2px}
[data-cases-home] .ch-wrap{max-width:1320px;margin:0 auto;padding:22px clamp(16px,3vw,36px) 56px;display:grid;gap:18px}
[data-cases-home] .ch-crumbs{font-size:13px;color:var(--muted)}
[data-cases-home] .ch-crumbs b{color:var(--ink);font-weight:600}
[data-cases-home] .ch-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px}
[data-cases-home] .ch-head > div:first-child{flex:1;min-width:0}
[data-cases-home] .ch-head h1{margin:0;font:600 clamp(32px,3.6vw,42px)/1.05 "Literata",Georgia,serif;letter-spacing:-.01em}
[data-cases-home] .ch-sum{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:8px;font-size:14px;color:var(--muted)}
[data-cases-home] .ch-sum b{color:var(--ink);font-weight:700}
[data-cases-home] .ch-sum .warn b,[data-cases-home] .ch-sum .warn{color:var(--gold)}
[data-cases-home] .ch-actions{display:flex;align-items:center;gap:10px;flex:none}
[data-cases-home] .ch-search{position:relative;display:flex;align-items:center;gap:10px;width:clamp(240px,26vw,380px);height:44px;padding:0 10px 0 14px;border-radius:12px;background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow-rest);transition:border-color .15s,box-shadow .15s}
[data-cases-home] .ch-search:hover{border-color:var(--hover-line)}
[data-cases-home] .ch-search:focus-within{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-cases-home] .ch-search svg{color:var(--faint);flex:none}
[data-cases-home] .ch-search input{flex:1;min-width:0;border:0;outline:none;background:transparent;color:var(--ink);font:inherit;font-size:14.5px}
[data-cases-home] .ch-search input::placeholder{color:var(--faint)}
[data-cases-home] .ch-kbd{font:500 11px "JetBrains Mono",monospace;color:var(--faint);border:1px solid var(--line-strong);border-bottom-width:2px;border-radius:5px;padding:0 6px;line-height:18px;white-space:nowrap}
[data-cases-home] .ch-clear{background:none;border:0;color:var(--muted);cursor:pointer;font-size:20px;line-height:1;padding:0 4px}
[data-cases-home] .ch-icon{display:inline-flex;align-items:center;justify-content:center;border-radius:12px;border:1px solid var(--line-strong);background:var(--surface);color:var(--ink);cursor:pointer;transition:border-color .15s,background .15s,color .15s}
[data-cases-home] .ch-icon:hover{border-color:var(--hover-line);background:var(--hover-tint);color:var(--hover-ink)}
[data-cases-home] .ch-icon:hover svg{animation:chDrop .5s ease}
[data-cases-home] .ch-cta{position:relative;overflow:hidden;display:inline-flex;align-items:center;gap:8px;padding:0 18px;border-radius:12px;border:0;background:var(--brand-solid);color:var(--on-brand);font:inherit;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 10px 24px -12px rgba(46,196,214,.8);transition:transform .15s,box-shadow .15s}
[data-cases-home] .ch-cta:hover{background:var(--brand-solid-hover);transform:translateY(-1px)}
[data-cases-home] .ch-cta:hover svg{animation:chSpin .5s ease}
[data-cases-home] .ch-card{border-radius:18px;border:1px solid var(--line);background:var(--surface);box-shadow:var(--shadow-rest)}
[data-cases-home] .ch-week{padding:16px 18px 18px}
[data-cases-home] .ch-week-head{display:flex;align-items:center;gap:12px}
[data-cases-home] .ch-week-head h2{margin:0;font:600 19px/1.2 "Literata",Georgia,serif}
[data-cases-home] .ch-week-head .n{font-size:13px;color:var(--muted)}
[data-cases-home] .ch-link{background:none;border:0;padding:0;color:var(--brand-text);font:inherit;font-size:13.5px;font-weight:700;cursor:pointer}
[data-cases-home] .ch-link:hover{color:var(--hover-ink);text-decoration:underline;text-underline-offset:3px}
[data-cases-home] .ch-fold{display:inline-flex;align-items:center;gap:6px;background:none;border:0;color:var(--muted);font:inherit;font-size:13px;font-weight:600;cursor:pointer;padding:4px 6px;border-radius:8px}
[data-cases-home] .ch-fold:hover{color:var(--hover-ink);background:var(--hover-tint)}
[data-cases-home] .ch-fold svg{transition:transform .2s}
[data-cases-home] .ch-fold[aria-expanded="false"] svg{transform:rotate(-90deg)}
[data-cases-home] .ch-days{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:10px;margin-top:14px}
[data-cases-home] .ch-day{min-height:112px;display:flex;flex-direction:column;gap:6px;padding:10px;border-radius:14px;border:1px solid var(--line);background:var(--surface-2)}
[data-cases-home] .ch-day.today{border-color:var(--brand-text);box-shadow:0 0 0 1px var(--brand-text) inset;background:color-mix(in srgb,var(--brand-text) 7%,var(--surface-2))}
[data-cases-home] .ch-day.closed{opacity:.6}
[data-cases-home] .ch-day-top{display:flex;align-items:baseline;justify-content:space-between}
[data-cases-home] .ch-day-top span{font-size:12.5px;font-weight:600;color:var(--muted)}
[data-cases-home] .ch-day.today .ch-day-top span{color:var(--brand-text)}
[data-cases-home] .ch-day-top b{font:600 22px/1 "Literata",Georgia,serif}
[data-cases-home] .ch-day .none{margin-top:auto;font-size:12px;color:var(--faint)}
[data-cases-home] .ch-hear{display:block;width:100%;text-align:left;padding:7px 9px;border-radius:9px;border:1px solid var(--line);border-left:3px solid var(--c,var(--brand-text));background:var(--surface);color:var(--ink);font:inherit;cursor:pointer;transition:border-color .15s,transform .15s}
[data-cases-home] .ch-hear:hover{border-color:var(--hover-line);transform:translateY(-1px)}
[data-cases-home] .ch-hear b{display:block;font-size:12.5px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-cases-home] .ch-hear span{display:block;font-size:11.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-cases-home] .ch-more{font-size:11.5px;color:var(--muted);padding-left:4px}
[data-cases-home] .ch-bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
[data-cases-home] .ch-tabs{display:flex;gap:2px;padding:4px;border-radius:12px;background:var(--surface);border:1px solid var(--line)}
[data-cases-home] .ch-tab{display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 14px;border-radius:10px;border:0;background:transparent;color:var(--muted);font:inherit;font-size:14.5px;font-weight:600;cursor:pointer}
[data-cases-home] .ch-tab:hover{color:var(--hover-ink)}
[data-cases-home] .ch-tab[aria-selected="true"]{background:var(--brand-solid);color:var(--on-brand)}
[data-cases-home] .ch-n{font-size:14px;font-weight:600;opacity:.85}
[data-cases-home] .ch-n.hot{color:var(--gold);opacity:1;font-weight:700}
[data-cases-home] .ch-tab[aria-selected="true"] .ch-n{color:inherit;opacity:1}
[data-cases-home] .ch-hist{margin-left:auto;display:inline-flex;align-items:center;gap:8px;padding:0 14px;border-radius:12px;border:1px dashed var(--line-strong);background:transparent;color:var(--muted);font:inherit;font-size:13.5px;font-weight:600;cursor:pointer}
[data-cases-home] .ch-hist:hover,[data-cases-home] .ch-hist[aria-selected="true"]{border-color:var(--hover-line);color:var(--hover-ink);background:var(--hover-tint)}
[data-cases-home] .ch-list{overflow:hidden}
[data-cases-home] .ch-group{display:flex;align-items:baseline;gap:12px;padding:12px 20px 10px;border-top:1px solid var(--line);background:var(--surface-2)}
[data-cases-home] .ch-list > .ch-group:first-child{border-top:0}
[data-cases-home] .ch-group .t{font-size:11.5px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--gc,var(--muted))}
[data-cases-home] .ch-group .h{font-size:13px;color:var(--muted)}
[data-cases-home] .ch-group .c{margin-left:auto;font:600 12px "JetBrains Mono",monospace;color:var(--muted)}
[data-cases-home] .ch-row{display:grid;grid-template-columns:minmax(0,2.3fr) minmax(0,1.3fr) minmax(0,1.25fr) minmax(170px,1fr) 40px;gap:16px;align-items:center;padding:14px 18px 14px 20px;border-top:1px solid var(--line);box-shadow:inset 3px 0 0 var(--edge,transparent);transition:background .15s}
[data-cases-home] .ch-row[role="button"]{cursor:pointer}
[data-cases-home] .ch-row:hover{background:var(--hover-tint)}
[data-cases-home] .ch-row:hover .ch-title{color:var(--hover-ink)}
[data-cases-home] .ch-row:hover .ch-tile{transform:rotate(-8deg) scale(1.06)}
[data-cases-home] .ch-row:hover .ch-go{color:var(--hover-ink);border-color:var(--hover-line);transform:translateX(2px)}
[data-cases-home] .ch-tile{width:42px;height:42px;flex:none;border-radius:12px;display:grid;place-items:center;color:var(--tc,var(--brand-text));background:color-mix(in srgb,var(--tc,var(--brand-text)) 14%,transparent);box-shadow:0 0 0 1px color-mix(in srgb,var(--tc,var(--brand-text)) 22%,transparent) inset;transition:transform .3s cubic-bezier(.34,1.56,.64,1)}
[data-cases-home] .ch-title{font:600 16px/1.3 "Literata",Georgia,serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:color .15s}
[data-cases-home] .ch-meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:3px;font-size:12.5px;color:var(--muted)}
[data-cases-home] .ch-no{font:600 12px "JetBrains Mono",monospace;color:var(--brand-text)}
[data-cases-home] .ch-dot{width:3px;height:3px;border-radius:50%;background:var(--faint)}
[data-cases-home] .ch-client{display:flex;align-items:center;gap:10px;min-width:0}
[data-cases-home] .ch-client b{display:block;font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-cases-home] .ch-client small{display:block;font-size:12px;color:var(--muted)}
[data-cases-home] .ch-stage{min-width:0}
[data-cases-home] .ch-segs{display:grid;grid-template-columns:repeat(6,1fr);gap:4px}
[data-cases-home] .ch-segs i{height:5px;border-radius:3px;background:var(--line-strong)}
[data-cases-home] .ch-segs i.on{background:var(--brand-text)}
[data-cases-home] .ch-segs i.now{background:var(--teal-ink);box-shadow:0 0 0 2px color-mix(in srgb,var(--teal-ink) 30%,transparent)}
[data-cases-home] .ch-stage span{display:block;margin-top:6px;font-size:12.5px;color:var(--muted)}
[data-cases-home] .ch-when b{display:block;font-size:14px;font-weight:700}
[data-cases-home] .ch-when b::first-letter{text-transform:uppercase}
[data-cases-home] .ch-when span{display:block;font-size:12.5px;color:var(--muted);margin-top:2px}
[data-cases-home] .ch-when .soon{color:var(--gold)}
[data-cases-home] .ch-when .late{color:var(--danger)}
[data-cases-home] .ch-setdate{margin-top:4px;display:inline-flex;align-items:center;height:26px;padding:0 10px;border-radius:999px;border:1px solid color-mix(in srgb,var(--gold) 45%,transparent);background:color-mix(in srgb,var(--gold) 14%,transparent);color:var(--gold);font:inherit;font-size:12px;font-weight:700;cursor:pointer}
[data-cases-home] .ch-setdate:hover{background:color-mix(in srgb,var(--gold) 24%,transparent)}
[data-cases-home] .ch-go{width:36px;height:36px;display:grid;place-items:center;border-radius:10px;border:1px solid var(--line);background:transparent;color:var(--muted);cursor:pointer;transition:transform .15s,color .15s,border-color .15s}
[data-cases-home] .ch-req-acts{display:flex;gap:8px;justify-content:flex-end;grid-column:4 / span 2}
[data-cases-home] .ch-btn{height:36px;padding:0 14px;border-radius:10px;border:1px solid var(--line-strong);background:var(--surface);color:var(--ink);font:inherit;font-size:13px;font-weight:700;cursor:pointer;white-space:nowrap}
[data-cases-home] .ch-btn:hover:not(:disabled){border-color:var(--hover-line);background:var(--hover-tint);color:var(--hover-ink)}
[data-cases-home] .ch-btn.gold{border:0;background:var(--gold);color:#241a05}
[data-cases-home] .ch-btn.gold:hover:not(:disabled){filter:brightness(1.06);color:#241a05;background:var(--gold)}
[data-cases-home] .ch-btn:disabled{opacity:.5;cursor:not-allowed}
[data-cases-home][data-mode="light"] .ch-btn.gold,[data-cases-home][data-mode="light"] .ch-btn.gold:hover:not(:disabled),[data-cases-home][data-mode="light"] .ch-n.hot{color:#fff}
[data-cases-home] .ch-quote{grid-column:1 / -1;font-size:12.5px;color:var(--muted);padding:8px 12px;border-left:3px solid var(--gold);background:color-mix(in srgb,var(--gold) 8%,transparent);border-radius:0 8px 8px 0}
[data-cases-home] .ch-empty{padding:26px 18px;border-top:1px solid var(--line);font-size:13.5px;color:var(--muted);text-align:center}
[data-cases-home] .ch-alert{display:flex;align-items:center;gap:12px;padding:10px 14px;border-radius:12px;border:1px solid color-mix(in srgb,var(--gold) 40%,transparent);background:color-mix(in srgb,var(--gold) 8%,transparent);font-size:13px}
/* DEMO PALETTE (2026-10-09, trial only): the user's page background on the Cases list, dark mode; boxes keep the theme. Delete this block to go back. */
[data-cases-home][data-mode="dark"]{--bg:#39494a}
[data-cases-home][data-mode="dark"] .ch-day{background:#16313A}
[data-cases-home][data-mode="dark"] .ch-day.today{background:color-mix(in srgb,var(--brand-text) 8%,#16313A)}
[data-cases-home][data-mode="dark"] .ch-card,[data-cases-home][data-mode="dark"] .ch-day:not(.today),[data-cases-home][data-mode="dark"] .ch-search{border:1px solid rgba(255,255,255,0.08)}
[data-cases-home][data-mode="dark"] .ch-hear{border-top-color:rgba(255,255,255,0.08);border-right-color:rgba(255,255,255,0.08);border-bottom-color:rgba(255,255,255,0.08)}
@keyframes chDrop{0%,100%{transform:translateY(0)}40%{transform:translateY(3px)}}
@keyframes chSpin{to{transform:rotate(90deg)}}
@media (prefers-reduced-motion:reduce){[data-cases-home] *{transition:none!important;animation:none!important}}`;

const WEEKDAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
// Courts in Pakistan sit Monday to Saturday; Sunday is the weekly holiday.
const COURT_CLOSED_DAY = 0;
const WEEK_FOLD_KEY = "attorney:lawyer-cases-week-open";
const dayOfWeek = (dateStr) => new Date(`${dateStr}T12:00:00Z`).getUTCDay();
const dayOfMonth = (dateStr) => Number(dateStr.slice(8, 10));

/** The next seven days (today first), each with its upcoming hearings. */
export function courtWeek(cases, today) {
    const days = Array.from({ length: 7 }, (_, i) => shiftDay(today, i));
    return days.map(date => ({
        date,
        hearings: cases.flatMap(c => (c._apiHearings || [])
            .filter(h => h.status === "upcoming" && h.date === date)
            .map(h => ({ caseId: c.id, title: c.title, time: h.time, court: h.court || c.court, purpose: h.purpose })))
            .sort((a, b) => (a.time || "").localeCompare(b.time || "")),
    }));
}

function CasesList({ cases, onOpen, requests = [], onRequestsChanged = () => {}, onCaseCreated = () => {},
                     loadError = null, onRetryCases = () => {}, reqError = null, onRetryRequests = () => {} }) {
    const { t: T } = useTheme();
    const { setPage } = useCase();
    const [search, setSearch] = useState("");
    const [filter, setFilter] = useState("all");      // all | needs | requests | nohearing | active | history
    const [newOpen, setNewOpen] = useState(false);
    const [sortBy, setSortBy] = useState("hearing");
    const [types, setTypes] = useState([]);            // case types to keep; empty = all
    const [provinces, setProvinces] = useState([]);    // provinces to keep; empty = all
    const [toast, showToast] = useToast();
    const eng = useEngagementActions(onRequestsChanged, showToast);
    const searchRef = useRef(null);
    // The week strip folds away (remembered per browser) for a lawyer who
    // wants the list first.
    const [weekOpen, setWeekOpen] = useState(() => {
        try { return localStorage.getItem(WEEK_FOLD_KEY) !== "0"; } catch { return true; }
    });
    const toggleWeek = () => setWeekOpen(o => {
        try { localStorage.setItem(WEEK_FOLD_KEY, o ? "0" : "1"); } catch { /* storage off */ }
        return !o;
    });

    const q = search.trim().toLowerCase();
    const today = pktToday();

    // ONE derivation for sections and counts (lib/casesView.js): every chip's
    // number is the length of the rows its view renders.
    const viewArgs = { cases, requests, search, types, provinces, sortBy, today };
    const { sections, counts } = buildCasesView(viewArgs);
    const { newRequests, awaitingClient, notFiled, active, outcomeDue, history } = sections;
    const openReqs = requests.filter(r => r.status === "requested" || r.status === "terms_proposed");

    // Filter options: every case type and province, each with how many of the
    // lawyer's cases (and open requests) it matches.
    const typeOptions = FILTER_TYPES.map(([key, label]) => ({ key, label,
        n: cases.filter(c => c.caseTypeKey === key).length + openReqs.filter(r => r.case_type === key).length }));
    const provinceOptions = FILTER_PROVINCES.map(([key, label, full]) => ({ key, label, full,
        n: cases.filter(c => c.provinceKey === key).length }));
    const newCount = requests.filter(r => r.status === "requested").length;
    const filterCount = types.length + provinces.length;
    // The Filter preview: the SELECTED chip's rows under the draft filters,
    // out of that chip's rows with no filters (search still applies).
    const countFor = ({ types: ty, provinces: pr }) =>
        buildCasesView({ ...viewArgs, types: ty, provinces: pr }).counts[filter];
    const previewTotal = buildCasesView({ ...viewArgs, types: [], provinces: [] }).counts[filter];

    const chips = [
        { id: "all", label: "All", n: counts.all },
        { id: "needs", label: "Needs me", n: counts.needs, hot: true },
        { id: "requests", label: "New requests", n: counts.requests, hot: true },
        { id: "nohearing", label: "Not filed yet", n: counts.nohearing },
        { id: "active", label: "Active", n: counts.active },
    ];
    const needs = filter === "needs";
    const show = (id) => filter === "all" || filter === id || (needs && ["requests", "nohearing", "active"].includes(id));
    // Under Needs me, only the active cases whose hearing has passed.
    const activeRows = needs ? outcomeDue : active;

    // The week in court, and the very next hearing for the header line.
    const week = courtWeek(cases.filter(c => !HISTORY_STATUSES.includes(c.status)), today);
    const weekCount = week.reduce((n, d) => n + d.hearings.length, 0);
    const nextHearing = cases
        .filter(c => !HISTORY_STATUSES.includes(c.status))
        .flatMap(c => (c._apiHearings || []).filter(h => h.status === "upcoming" && h.date >= today).map(h => ({ ...h, title: c.title })))
        .sort((a, b) => (a.date + (a.time || "")).localeCompare(b.date + (b.time || "")))[0] || null;

    // Ctrl/Cmd+K focuses the search from anywhere on the page; Enter in it
    // opens the case when the search leaves exactly one; Escape clears it.
    useEffect(() => {
        const onKey = (e) => {
            if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
                e.preventDefault();
                searchRef.current?.focus();
                searchRef.current?.select();
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, []);
    const liveMatches = [...notFiled, ...active, ...(filter === "history" ? history : [])];
    const onSearchKey = (e) => {
        if (e.key === "Escape") { setSearch(""); return; }
        if (e.key === "Enter" && q && liveMatches.length === 1) onOpen(liveMatches[0].id);
    };

    const exportCsv = () => {
        const head = ["Case no.", "Title", "Client", "Province", "Type", "Status", "Next hearing"];
        const rows = cases.map(c => [c.id, c.title, c.client, c.court, c.type, c.status, c.nextHearing || ""]);
        const csv = "﻿" + [head, ...rows].map(r => r.map(csvCell).join(",")).join("\r\n") + "\r\n";
        const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
        const a = document.createElement("a");
        a.href = url; a.download = `attorney-ai-cases-${pktToday()}.csv`;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    };

    const tile = (tone) => (
        <span className="ch-tile" style={{ "--tc": tone }} aria-hidden="true"><Icon d={SCALES} size={19} /></span>
    );
    const titleBlock = (title, number, bits, tone) => (
        <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
            {tile(tone)}
            <div style={{ minWidth: 0 }}>
                <div className="ch-title">{title}</div>
                <div className="ch-meta">
                    {number && <span className="ch-no">{number}</span>}
                    {bits.filter(Boolean).map((b, i) => (
                        <Fragment key={i}>{(i > 0 || number) && <i className="ch-dot" aria-hidden="true" />}{typeof b === "string" ? <span>{b}</span> : b}</Fragment>
                    ))}
                </div>
            </div>
        </div>
    );
    const clientCell = (name, sub) => (
        <div className="ch-client">
            <Avatar name={name} size={32} />
            <span style={{ minWidth: 0 }}><b>{name || "Client"}</b>{sub && <small>{sub}</small>}</span>
        </div>
    );
    const stageCell = (idx) => (
        <div className="ch-stage" aria-label={`Stage: ${STAGES[idx]}`}>
            <div className="ch-segs" aria-hidden="true">
                {STAGES.map((s, i) => <i key={s} className={i < idx ? "on" : i === idx ? "now" : ""} />)}
            </div>
            <span>{STAGES[idx]}</span>
        </div>
    );
    const goBtn = (onClick, label = "Open case") => (
        <button type="button" className="ch-go" aria-label={label} onClick={e => { e.stopPropagation(); onClick(); }}>
            <Icon d={I.chevronRight} size={16} />
        </button>
    );

    const caseRow = (c, kind) => {
        const d = daysUntil(c.nextHearing);
        const h = (c._apiHearings || []).find(x => x.status === "upcoming" && x.date === c.nextHearing);
        const edge = kind === "history" ? "var(--faint)" : kind === "nohearing" ? "var(--gold)" : d !== null && d < 0 ? "var(--danger)" : "transparent";
        return (
            <div key={c.id} data-row="case" role="button" tabIndex={0} className="ch-row" style={{ "--edge": edge }}
                onClick={() => onOpen(c.id)}
                onKeyDown={e => {
                    // The row's own keys only: Enter on a button inside it is
                    // that button's click, and opening here as well opened the
                    // case twice.
                    if (e.target !== e.currentTarget) return;
                    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(c.id); }
                }}>
                {titleBlock(c.title, c.id, [c.type, c.court, <Pill key="s" color={kind === "history" ? "#94a2af" : TEAL}>{c.status}</Pill>],
                    kind === "history" ? "var(--faint)" : c.caseTypeKey === "criminal" ? "var(--danger)" : "var(--brand-text)")}
                {clientCell(c.client, c.walkIn ? "Walk-in client" : null)}
                {stageCell(stageIndex(c, c._apiHearings || []))}
                <div className="ch-when">
                    {kind === "active" && (<>
                        <b className={d !== null && d < 0 ? "late" : d !== null && d <= 1 ? "soon" : ""}>
                            {d !== null && d < 0 ? `Outcome due · ${inDays(d)}` : inDays(d)}
                        </b>
                        <span>{fmtDate(c.nextHearing)}{h?.time ? ` · ${fmtTime(h.time)}` : ""}</span>
                    </>)}
                    {kind === "nohearing" && (<>
                        <b>No hearing yet</b>
                        <button type="button" className="ch-setdate" onClick={e => { e.stopPropagation(); onOpen(c.id); }}>Set the date</button>
                    </>)}
                    {kind === "history" && <span>{c.status}</span>}
                </div>
                {goBtn(() => onOpen(c.id))}
            </div>
        );
    };

    const requestRow = (r) => {
        const sent = r.status === "terms_proposed";
        // Days since it was sent, counted in PKT days (not by the UTC date).
        const ageDays = requestAgeDays(r.created_at, today);
        return (
            <div key={r.id} data-row="request" className="ch-row" style={{ "--edge": "var(--gold)" }}>
                {titleBlock(r.case_title || "Untitled case", r.case_number,
                    [r.case_type && r.case_type.charAt(0).toUpperCase() + r.case_type.slice(1)], "var(--gold)")}
                {clientCell(r.client_name, sent ? (r.fee_amount ? `PKR ${Number(r.fee_amount).toLocaleString()} proposed` : "Terms sent") : null)}
                <div className="ch-when">
                    <b>{sent ? "Terms sent" : "Not accepted yet"}</b>
                    <span className={sent ? "" : "soon"}>{sent ? "waiting for client" : ageDays === null ? "reply soon" : ageDays === 0 ? "sent today" : `sent ${ageDays} day${ageDays === 1 ? "" : "s"} ago`}</span>
                </div>
                <div className="ch-req-acts">
                    {sent ? (
                        <button type="button" className="ch-btn" disabled={eng.busy} onClick={() => eng.handleDecline(r)}>Withdraw terms</button>
                    ) : (<>
                        <button type="button" className="ch-btn" disabled={eng.busy} onClick={() => eng.handleDecline(r)}>Decline</button>
                        <button type="button" className="ch-btn gold" disabled={eng.busy} onClick={() => eng.openAccept(r)}>Send terms</button>
                    </>)}
                </div>
                {r.message && <div className="ch-quote">“{r.message}”</div>}
            </div>
        );
    };

    const group = (title, hint, count, tone) => (
        <div className="ch-group" style={{ "--gc": tone }}>
            <span className="t">{title}</span>{hint && <span className="h">{hint}</span>}<span className="c">{count}</span>
        </div>
    );
    const empty = (text) => <div className="ch-empty">{text}</div>;

    const sections_ = [];
    if (show("requests") && (newRequests.length > 0 || filter === "requests")) sections_.push(
        <div key="req">{group("New requests", "Waiting for your terms", newRequests.length, "var(--gold)")}
            {newRequests.length ? newRequests.map(requestRow) : empty("No requests waiting.")}</div>);
    if (filter === "all" && awaitingClient.length > 0) sections_.push(
        <div key="await">{group("Waiting for the client", "Terms sent — the client decides", awaitingClient.length, "var(--teal-ink)")}
            {awaitingClient.map(requestRow)}</div>);
    if (show("nohearing") && (notFiled.length > 0 || filter === "nohearing")) sections_.push(
        <div key="nf">{group("Not filed yet", "Set the first hearing date to plan the case", notFiled.length, "var(--gold)")}
            {notFiled.length ? notFiled.map(c => caseRow(c, "nohearing")) : empty("Every case has a hearing date.")}</div>);
    if (show("active") && (activeRows.length > 0 || filter === "active")) sections_.push(
        <div key="act">{group(needs ? "Outcome due" : "Active", needs ? "Hearing date passed — record what happened" : "In court, by next hearing", activeRows.length, needs ? "var(--danger)" : "var(--brand-text)")}
            {activeRows.length ? activeRows.map(c => caseRow(c, "active")) : empty("No upcoming hearings.")}</div>);
    if (filter === "history") sections_.push(
        <div key="hist">{group("History", "Closed and dismissed", history.length)}
            {history.length ? history.map(c => caseRow(c, "history")) : empty("No closed cases.")}</div>);

    return (
        <div data-cases-home data-drafting-theme data-mode={draftingMode(T)} data-lenis-prevent style={{ height: "100%", overflowY: "auto" }}>
            <style>{`${DRAFTING_TOKENS_CSS}\n${CASES_HOME_CSS}`}</style>
            <div className="ch-wrap">
                <div>
                    <div className="ch-crumbs">Practice / <b>Cases</b></div>
                    <div className="ch-head" style={{ marginTop: 6 }}>
                        <div>
                            <h1>Cases</h1>
                            <div className="ch-sum">
                                <span><b>{cases.length} case{cases.length === 1 ? "" : "s"}</b></span>
                                {newCount > 0 && <span className="warn"><b>{newCount} new request{newCount === 1 ? "" : "s"} to accept</b></span>}
                                {counts.needs > 0 && <span className="warn">{counts.needs} need{counts.needs === 1 ? "s" : ""} you</span>}
                                <span>{nextHearing
                                    ? <>Next hearing <b>{inDays(daysUntil(nextHearing.date))}</b> · {fmtDate(nextHearing.date)}{nextHearing.time ? `, ${fmtTime(nextHearing.time)}` : ""}</>
                                    : "No hearing scheduled"}</span>
                            </div>
                        </div>
                        <div className="ch-actions">
                            <label className="ch-search">
                                <Icon d={I.search} size={16} />
                                <input ref={searchRef} value={search} onChange={e => setSearch(e.target.value)} onKeyDown={onSearchKey}
                                    placeholder="Search title, client or case no." aria-label="Search cases" />
                                {search
                                    ? <button type="button" className="ch-clear" aria-label="Clear search" onClick={() => { setSearch(""); searchRef.current?.focus(); }}>×</button>
                                    : <span className="ch-kbd" aria-hidden="true">Ctrl K</span>}
                            </label>
                            <button type="button" className="ch-icon" onClick={exportCsv} title="Export cases as a CSV file that opens in Excel" aria-label="Export cases"
                                style={{ width: 44, height: 44 }}>
                                <Icon d={I.download} size={17} />
                            </button>
                            <button type="button" className="ch-cta" onClick={() => setNewOpen(true)} style={{ height: 44 }}>
                                <Icon d={I.plus} size={15} /> New case
                            </button>
                        </div>
                    </div>
                </div>

                {/* A refresh that failed keeps what is shown, and says so. */}
                {[[loadError, "Could not refresh your cases — showing what was last loaded.", onRetryCases],
                  [reqError, "Could not load case requests.", onRetryRequests]].filter(([e]) => e).map(([e, lead, retry]) => (
                    <div key={lead} role="alert" className="ch-alert">
                        <span style={{ flex: 1 }}>{lead} <span style={{ color: "var(--muted)" }}>{e}</span></span>
                        <button type="button" className="ch-btn" onClick={() => retry()}>Retry</button>
                    </div>
                ))}

                {/* THE WEEK IN COURT: the lawyer's first question, answered at a glance. */}
                <section className="ch-card ch-week" aria-label="This week in court" data-court-week>
                    <div className="ch-week-head">
                        <h2>This week in court</h2>
                        <span className="n">{weekCount ? `${weekCount} hearing${weekCount === 1 ? "" : "s"} in the next 7 days` : "No hearings in the next 7 days"}</span>
                        <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 14 }}>
                            <button type="button" className="ch-link" onClick={() => setPage?.("causelist")}>Open cause list →</button>
                            <button type="button" className="ch-fold" aria-expanded={weekOpen} onClick={toggleWeek}>
                                <Icon d={I.chevronDown} size={14} />{weekOpen ? "Hide" : "Show"}
                            </button>
                        </span>
                    </div>
                    {weekOpen && (
                        <div className="ch-days">
                            {week.map(({ date, hearings }) => {
                                const isToday = date === today;
                                const closed = dayOfWeek(date) === COURT_CLOSED_DAY && hearings.length === 0;
                                return (
                                    <div key={date} data-day={date} className={`ch-day${isToday ? " today" : ""}${closed ? " closed" : ""}`}>
                                        <div className="ch-day-top">
                                            <span>{isToday ? "Today" : date === shiftDay(today, 1) ? "Tomorrow" : WEEKDAY[dayOfWeek(date)]}</span>
                                            <b>{dayOfMonth(date)}</b>
                                        </div>
                                        {hearings.slice(0, 2).map((h, i) => (
                                            <button key={`${h.caseId}-${i}`} type="button" className="ch-hear" onClick={() => onOpen(h.caseId)}
                                                title={`${h.title}${h.purpose ? ` — ${h.purpose}` : ""}`}>
                                                <b>{h.title}</b>
                                                <span>{fmtTime(h.time)}{h.court ? ` · ${h.court}` : ""}</span>
                                            </button>
                                        ))}
                                        {hearings.length > 2 && <span className="ch-more">+{hearings.length - 2} more</span>}
                                        {!hearings.length && <span className="none">{closed ? "Court closed" : "No hearings"}</span>}
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </section>

                {/* The bar: what to show, then Sort and Filter. */}
                {/* One line, no card (2026-10-11): the views -- Closed is one of them,
                    not a separate History box -- and then Sort and Filter on the right. */}
                <div className="ch-bar">
                    <div role="tablist" aria-label="Filter cases" className="ch-tabs">
                        {chips.map(ch => (
                            <button key={ch.id} type="button" role="tab" aria-selected={filter === ch.id} className="ch-tab" onClick={() => setFilter(ch.id)}>
                                {ch.label}<span className={`ch-n${ch.hot && ch.n && filter !== ch.id ? " hot" : ""}`}>{ch.n}</span>
                            </button>
                        ))}
                        <button type="button" role="tab" aria-selected={filter === "history"} className="ch-tab" onClick={() => setFilter("history")}
                            title="Closed and dismissed cases">
                            Closed<span className="ch-n">{history.length}</span>
                        </button>
                    </div>
                    <span style={{ flex: 1 }} />
                    <BarMenu label="Sort" icon={SORT_ICON} width={210}>
                        {(close) => SORTS.map(([id, text]) => (
                            <button key={id} type="button" role="menuitemradio" aria-checked={sortBy === id}
                                onClick={() => { setSortBy(id); close(); }}
                                style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", height: 38, padding: "0 12px", borderRadius: 9, border: "none",
                                    background: sortBy === id ? "rgba(56,216,196,0.10)" : "transparent", color: sortBy === id ? T.text : T.textMuted, fontSize: 13.5, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                                {text}{sortBy === id && <Icon d={I.check} size={14} style={{ color: TEAL }} />}
                            </button>
                        ))}
                    </BarMenu>
                    <BarMenu label="Filter" icon={FILTER_ICON} badge={filterCount} width="max-content">
                        {(close) => (
                            <FilterPanel
                                groups={[
                                    { head: "Case type", field: "types", options: typeOptions },
                                    { head: "Province", field: "provinces", options: provinceOptions },
                                ]}
                                initial={{ types, provinces }}
                                countFor={countFor}
                                total={previewTotal}
                                onApply={(d) => { setTypes(d.types); setProvinces(d.provinces); close(); }} />
                        )}
                    </BarMenu>
                </div>

                {(sections_.length > 0 || (needs && counts.needs === 0) || (filter === "all" && counts.all === 0)) && (
                    <section className="ch-card ch-list" aria-label="Cases">
                        {sections_}
                        {needs && counts.needs === 0 && empty("Nothing is waiting on you.")}
                        {filter === "all" && counts.all === 0 && empty(q || filterCount ? "No cases match your search or filters." : "No cases yet.")}
                    </section>
                )}
            </div>

            {eng.termsModal}
            {newOpen && <NewCaseModal onClose={() => setNewOpen(false)} onCreated={(made) => { setNewOpen(false); onCaseCreated(made); }} />}
            <Toast msg={toast} />
        </div>
    );
}

// ─────────────────────────────────────────────
// CASE WORKSPACE
// ─────────────────────────────────────────────
const STAGES = ["Request", "Accepted", "Hearing set", "In court", "Judgment", "Closed"];

function stageIndex(c, hearings) {
    if (HISTORY_STATUSES.includes(c.status)) return 5;
    if (hearings.some(h => h.outcome === "decided")) return 4;
    if (hearings.some(h => h.status === "past")) return 3;
    if (hearings.length) return 2;
    return 1;
}

function CaseWorkspace({ caseId, cases, setCases, requests = [], onRequestsChanged = () => {}, onBack,
                         hasLoaded = true, loadError = null, onReload = async () => null }) {
    const { t: T } = useTheme();
    const { setPage, setActiveCase } = useCase() || {};
    const [tab, setTab] = useState("overview");
    const [toast, showToast] = useToast();
    const [focusTask, setFocusTask] = useState(0);
    const c = cases.find(x => x.id === caseId);
    const realId = c?._id || caseId;

    // Tasks and messages are read once per case and shared by the header
    // counts and their tabs.
    const [tasks, setTasks] = useState(null);
    const [messages, setMessages] = useState(null);
    useEffect(() => {
        if (!c) return;
        let off = false;
        listTasks(realId).then(({ data, error }) => { if (!off) setTasks(!error && Array.isArray(data) ? data : []); });
        listMessages(realId).then(({ data, error }) => { if (!off) setMessages(!error && Array.isArray(data) ? data : []); });
        return () => { off = true; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [realId, !!c]);

    // THE CASE'S DOCUMENTS: the legacy case listing, plus this lawyer's own
    // V2 documents on the case (the legacy listing leaves V2 rows out).
    const [docs, setDocs] = useState(null);
    const [docsFailed, setDocsFailed] = useState(false);
    useEffect(() => {
        if (!c) return;
        let off = false;
        Promise.all([
            Promise.resolve(listDocuments(realId)).catch(() => ({ error: true })),
            Promise.resolve(myDocumentsV2({ caseId: realId, limit: 50 })).catch(() => null),
            clientDocsForCase(realId).catch(() => null),
        ]).then(([legacy, v2, received]) => {
            if (off) return;
            const v2Rows = Array.isArray(v2?.data?.items) ? v2.data.items.map(d => ({ ...d, _v2: true })) : [];
            const legacyRows = legacy && !legacy.error && Array.isArray(legacy.data) ? legacy.data : null;
            const fromClient = received || [];
            if (!legacyRows && !v2Rows.length && !fromClient.length) { setDocsFailed(true); setDocs([]); return; }
            setDocsFailed(false);
            const seen = new Set([...v2Rows, ...fromClient].map(d => d.id));
            setDocs([...fromClient, ...v2Rows, ...(legacyRows || []).filter(d => !seen.has(d._id || d.id))]);
        });
        return () => { off = true; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [realId, !!c]);

    // A client's message arrives while this case is open: show it. The thread
    // used to stay as first read until the lawyer left and came back.
    // Only the newest re-read may write: two messages arriving close together
    // trigger two reads, and the older answer must not land last. Bumped on
    // unmount, so nothing writes after the case is closed.
    const msgGen = useRef(0);
    useEffect(() => () => { msgGen.current += 1; }, []);
    useEffect(() => onNotification((n) => {
        if (n.type !== "case_message" || n.payload?.case_id !== realId) return;
        const mine = ++msgGen.current;
        listMessages(realId).then(({ data, error }) => {
            if (mine === msgGen.current && !error && Array.isArray(data)) setMessages(data);
        });
    }), [realId]);

    // Reading the thread reads its notifications, so the Cases badge and the
    // bell agree with what the lawyer has actually seen.
    const { notifs = [], clearNotif } = useNotif();
    useEffect(() => {
        if (tab !== "messages" || !clearNotif) return;
        notifs.filter(n => n.unread && !n.local && n.type === "case_message" && n.payload?.case_id === realId)
            .forEach(n => clearNotif(n.id));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [tab, realId, notifs]);

    // ── hearings: schedule + record outcome (server-backed) ──
    const [hModal, setHModal] = useState(false);
    const emptyForm = { date: "", time: "10:00", court: "", judge: "", purpose: "" };
    const [form, setForm] = useState(emptyForm);
    const [outcomeFor, setOutcomeFor] = useState(null);
    const [oForm, setOForm] = useState({ outcome: "adjourned", note: "", next_date: "", next_time: "10:00" });
    const [picked, setPicked] = useState({});   // suggested task title -> ticked?
    const [oBusy, setOBusy] = useState(false);
    const [rsFor, setRsFor] = useState(null);     // hearing being rescheduled
    const [rsForm, setRsForm] = useState({ date: "", time: "10:00", reason: "" });
    const [rsBusy, setRsBusy] = useState(false);
    // One hearing per form. The ref blocks a second submit within the same
    // tick (state would still read false); the id is created per form and kept
    // across retries of that form, so the server can recognise a repeat.
    const [hBusy, setHBusy] = useState(false);
    const hSubmitting = useRef(false);
    const hRequestId = useRef(null);
    const oSubmitting = useRef(false);

    const eng = useEngagementActions(onRequestsChanged, showToast);

    // The case is not in the list. Only "loading" while the first read is
    // still out: after that it is a failed read (say so, offer Retry) or a
    // case this lawyer no longer has (engagement ended, released, or a stale
    // link). It used to say "Loading case…" for ever, with no way back.
    if (!c) {
        const panel = (title, detail, actions) => (
            <div data-case-missing style={{ padding: "40px 30px", display: "flex", justifyContent: "center" }}>
                <div style={{ maxWidth: 460, width: "100%", padding: 24, borderRadius: 16, border: `1px solid ${T.border}`, background: T.card }}>
                    <div style={{ fontSize: 17, fontWeight: 800, color: T.text }}>{title}</div>
                    <div style={{ fontSize: 13.5, color: T.textMuted, marginTop: 8, lineHeight: 1.55 }}>{detail}</div>
                    <div style={{ display: "flex", gap: 10, marginTop: 18 }}>{actions}</div>
                </div>
            </div>
        );
        const back = <button type="button" onClick={onBack} style={ghostBtn(T)}>← Back to cases</button>;
        if (!hasLoaded && !loadError) {
            return <div style={{ padding: 24, fontSize: 14, color: T.textMuted }}>Loading case…</div>;
        }
        if (loadError) {
            return panel("Could not load this case", loadError, <>
                <button type="button" onClick={() => onReload()} style={solidBtn(TEAL)}>Retry</button>{back}
            </>);
        }
        return panel("This case is no longer in your list",
            "The engagement may have ended, the case may have been released, or the link is out of date.", back);
    }

    // Straight from the case record. A separate per-case cache used to be
    // filled once and never refreshed, so a reload, a live update or reopening
    // the case still showed the hearings first seen.
    const cHearings = (c._apiHearings || []).slice().sort((a, b) => new Date(a.date) - new Date(b.date));
    const upcoming = cHearings.filter(h => h.status === "upcoming");
    const past = cHearings.filter(h => h.status === "past").reverse();
    const nextHearing = upcoming[0];
    const lastCourt = [...cHearings].reverse().find(h => h.court)?.court || "";
    const openTasks = (tasks || []).filter(x => !x.done);
    const engagement = requests.find(r => r.case_id === realId && r.status === "accepted");

    // Replace this case and its hearings with the server's returned CaseOut.
    // The hearing routes return the bare case; only the case LIST adds
    // client_name, so keep the name already shown rather than blanking it.
    const applyServerCase = (apiCase) => {
        const mapped = _mapApiCase(apiCase);
        setCases(prev => prev.map(x => x._id === mapped._id
            ? { ...mapped, client: apiCase.client_name ? mapped.client : x.client }
            : x));
    };

    const openAdd = (preset = {}) => {
        setForm({ ...emptyForm, court: lastCourt, ...preset });
        hRequestId.current = newRequestId();      // a new form is a new hearing
        setHModal(true);
    };

    /** After the server refused a stale write (409): re-read this case and
     *  show what it actually holds now. */
    const refreshThisCase = async () => { await onReload(); };
    const openReschedule = (h) => {
        if (!h._id) { showToast("⚠️ This hearing predates tracking — schedule a new hearing instead"); return; }
        setRsForm({ date: "", time: h.time || "10:00", reason: "" });
        setRsFor(h);
    };
    const saveReschedule = async () => {
        if (!rsForm.date) { showToast("⚠️ Pick the new date"); return; }
        if (rsBusy) return;
        setRsBusy(true);
        const { data, error, status } = await apiReschedule(realId, rsFor._id, {
            date: new Date(rsForm.date).toISOString(), time: rsForm.time, reason: rsForm.reason.trim(),
        });
        setRsBusy(false);
        if (error && status === 409) {
            // Changed meanwhile (moved again, or an outcome was recorded).
            showToast("⚠️ " + (error.message || "This hearing changed meanwhile."), 3600);
            setRsFor(null);
            await refreshThisCase();
            return;
        }
        if (error) { showToast("❌ " + (error.message || "Could not reschedule the hearing")); return; }
        if (data) applyServerCase(data);
        setRsFor(null);
        showToast(`✅ Hearing moved to ${fmtDate(rsForm.date)} — the client has been notified`, 3200);
    };

    // "+ Task": open Tasks with the new-task box focused.
    const goTask = () => { setTab("tasks"); setFocusTask(n => n + 1); };

    // Scheduling only: hearing edit and delete have no backend endpoint and
    // are not offered.
    const saveHearing = async (f = form) => {
        if (hSubmitting.current) return false;
        if (!f.date || !f.purpose || !f.court) { showToast("⚠️ Date, court and purpose are required"); return false; }
        if (!hRequestId.current) hRequestId.current = newRequestId();
        hSubmitting.current = true;
        setHBusy(true);
        try {
            const { data, error } = await apiAddHearing(realId, {
                date: new Date(f.date).toISOString(),
                court: f.court, judge: f.judge || null, purpose: f.purpose,
                time: f.time || null, outcome: null, request_id: hRequestId.current,
            });
            // On failure the id is KEPT: a retry of this form is the same hearing.
            if (error) { showToast("❌ " + (error.message || "Failed to save hearing")); return false; }
            hRequestId.current = null;
            // The server's copy, so the new hearing carries its `_id` and
            // "Record outcome" works on it without a reload.
            if (data) applyServerCase(data);
            showToast("✅ Hearing scheduled — the client can see it");
            setHModal(false);
            return true;
        } finally {
            hSubmitting.current = false;
            setHBusy(false);
        }
    };

    const suggestions = (OUTCOME_TASKS[oForm.outcome] || []).map(([title, n]) => {
        const due = oForm.next_date ? shiftDay(oForm.next_date, -n) : shiftDay(pktToday(), n);
        return { title, due: due < pktToday() ? pktToday() : due };
    });

    const markOutcome = (h) => {
        if (!h._id) { showToast("⚠️ This hearing predates outcome tracking — schedule hearings through the app to enable it"); return; }
        setOForm({ outcome: "adjourned", note: "", next_date: "", next_time: "10:00" });
        setPicked({});
        setOutcomeFor(h);
    };

    const saveOutcome = async () => {
        if (oSubmitting.current) return;
        oSubmitting.current = true;
        const h = outcomeFor;
        setOBusy(true);
        const { data, error, status } = await apiRecordOutcome(realId, h._id, {
            outcome: oForm.outcome,
            note: oForm.note || null,
            next_date: oForm.next_date ? new Date(oForm.next_date).toISOString() : null,
            next_time: oForm.next_date ? oForm.next_time : null,
        });
        if (error && status === 409) {
            // Already recorded (another tab, or a retry after a lost reply).
            // Nothing new was saved, so no follow-up tasks either.
            oSubmitting.current = false;
            setOBusy(false);
            setOutcomeFor(null);
            showToast("⚠️ " + (error.message || "An outcome is already recorded for this hearing."), 3600);
            await refreshThisCase();
            return;
        }
        if (error) { oSubmitting.current = false; setOBusy(false); showToast("❌ " + (error.message || "Failed to record outcome")); return; }
        // The server's copy carries the auto-scheduled next hearing WITH its `_id`.
        if (data) applyServerCase(data);
        // Ticked follow-ups become real tasks. The outcome is already saved;
        // a task that fails is reported, not retried behind the lawyer's back.
        const chosen = suggestions.filter(x => picked[x.title] !== false);
        let added = 0;
        for (const x of chosen) {
            const res = await apiAddTask(realId, { title: x.title, due: x.due, priority: "medium", description: `After hearing on ${fmtDate(h.date)}` });
            if (!res.error && res.data) { added += 1; setTasks(prev => [...(prev || []), res.data]); }
        }
        oSubmitting.current = false;
        setOBusy(false);
        setOutcomeFor(null);
        showToast(`✅ Outcome recorded — client notified${added ? ` · ${added} task${added === 1 ? "" : "s"} added` : ""}${added < chosen.length ? ` · ${chosen.length - added} could not be added` : ""}`, 3600);
    };

    const stage = stageIndex(c, cHearings);
    // Closed and dismissed cases are read-only (the server refuses changes too).
    const closed = HISTORY_STATUSES.includes(c.status);
    const dNext = nextHearing ? daysUntil(nextHearing.date) : null;
    // What the header and the tabs say about the case right now.
    const overdueHearing = upcoming.find(h => daysUntil(h.date) < 0);
    const todayKey = pktToday();
    const overdueTasks = openTasks.filter(x => x.due && String(x.due).slice(0, 10) < todayKey);
    // "Needs you": a date to set, an outcome to record, or a task gone overdue.
    const needsYou = !closed && (!!overdueHearing || !nextHearing || overdueTasks.length > 0);
    const court = nextHearing?.court || lastCourt;
    const stageSub = (i) => (i < stage ? "Done"
        : i === stage && closed ? c.status
        : i === stage && nextHearing ? `Next: ${shortDay(nextHearing.date)}` : "");
    // Only what the case record holds. A fee shows only when the engagement
    // carries one; "Opened" is when the case came into Attorney.AI, not a
    // court filing date, which the backend does not have.
    const meta = [
        [I.user, c.client],
        court && [I.gavel, court],
        [I.map, [c.court !== "—" ? c.court : null, c.type].filter(Boolean).join(" · ")],
        engagement?.fee_amount && [I.dollar, `Rs. ${Number(engagement.fee_amount).toLocaleString()}`],
        c.createdAt && [I.calendar, `Opened ${shortDay(c.createdAt)}`],
    ].filter(x => x && x[1]);
    const tabs = [
        { id: "overview", label: "Overview" },
        { id: "schedule", label: "Schedule", n: cHearings.length },
        { id: "messages", label: "Messages", n: messages?.length },
        { id: "tasks", label: "Tasks", n: openTasks.length, hot: overdueTasks.length > 0 },
        { id: "documents", label: "Documents", n: docs?.length },
    ];

    return (
        <div className="cw" style={{ display: "flex", flexDirection: "column", height: "100%", overflowY: "auto", padding: "16px 30px 30px", gap: 18 }}>
            <nav className="cw-crumbs" aria-label="Breadcrumb">
                <button type="button" onClick={onBack}><Icon d={I.chevronLeft} size={15} />Cases</button>
                <span aria-hidden="true">/</span>
                <b>{c.id}</b>
            </nav>

            {/* The case at a glance: who, where, what stage. */}
            <section className="cw-head">
                <div className="cw-head-top">
                    <span className="cw-tile" aria-hidden="true"><Icon d={SCALES} size={24} /></span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <h1 className="serif">{c.title}</h1>
                        <div className="cw-meta">
                            {needsYou && <span className="cw-pill gold"><i />Needs you</span>}
                            <span className={`cw-pill${closed ? " muted" : ""}`}><i />{c.status}</span>
                            {c.urgent && <span className="cw-pill red"><i />Urgent</span>}
                            {meta.map(([icon, text], i) => (
                                <span key={i} className="cw-m"><Icon d={icon} size={15} />{text}</span>
                            ))}
                        </div>
                    </div>
                    <div className="cw-actions">
                        <button type="button" className="cw-btn" onClick={() => setTab("messages")}><Icon d={I.chat} size={16} />Message client</button>
                        {!closed && <button type="button" className="cw-btn" onClick={goTask}><Icon d={I.checkSquare} size={16} />Add task</button>}
                        {!closed && <button type="button" className="cw-cta" onClick={() => openAdd()}><Icon d={I.plus} size={16} />Add hearing</button>}
                    </div>
                </div>
                <div className="cw-stages" aria-label={`Stage: ${STAGES[stage]}`}>
                    {STAGES.map((s, i) => (
                        <div key={s} className={i < stage ? "done" : i === stage ? "now" : ""}>
                            <i aria-hidden="true" />
                            <b>{s}</b>
                            <small>{stageSub(i) || " "}</small>
                        </div>
                    ))}
                </div>
            </section>

            {closed && (
                <div role="status" className="cw-note">
                    <strong>This case is {c.status.toLowerCase()}.</strong> It is kept as a record: hearings, tasks and messages can be read but not changed.
                </div>
            )}

            <div role="tablist" aria-label="Case sections" className="cw-tabs">
                {tabs.map(tb => (
                    <button key={tb.id} type="button" role="tab" aria-selected={tab === tb.id} onClick={() => setTab(tb.id)}>
                        {tb.label}
                        {Number.isInteger(tb.n) && tb.n > 0 && <span className={`cw-n${tb.hot ? " hot" : ""}`}>{tb.n}</span>}
                    </button>
                ))}
            </div>

            {tab === "overview" && (
                <CaseOverview c={c} cases={cases} hearings={cHearings} nextHearing={nextHearing} past={past}
                    tasks={tasks} messages={messages} docs={docs} lastCourt={lastCourt} engagement={engagement} eng={eng}
                    onSaveHearing={saveHearing} onRecord={markOutcome} onReschedule={openReschedule} goTab={setTab} openAdd={openAdd}
                    readOnly={closed} setPage={setPage} />
            )}
            {tab === "schedule" && (
                <CaseSchedule upcoming={upcoming} past={past} lastCourt={lastCourt} busy={hBusy} onSchedule={saveHearing}
                    onRecord={markOutcome} onReschedule={openReschedule} readOnly={closed} />
            )}
            {tab === "messages" && (
                <CaseMessages caseId={realId} c={c} messages={messages || []} setMessages={setMessages}
                    loading={messages === null} nextHearing={nextHearing} readOnly={closed} counsel={engagement?.lawyer_name || null} />
            )}
            {tab === "tasks" && (
                <CaseTasks caseId={realId} tasks={tasks || []} setTasks={setTasks} loading={tasks === null}
                    nextHearing={nextHearing} showToast={showToast} focusSignal={focusTask} readOnly={closed} />
            )}
            {tab === "documents" && (
                <CaseDocuments docs={docs} failed={docsFailed} caseNo={c.id} setPage={setPage} setActiveCase={setActiveCase} />
            )}
            {tab === "documents" && (
                <CaseFiles caseId={realId} readOnly={closed} />
            )}

            {/* Schedule hearing */}
            {hModal && (
                <Modal title="Schedule New Hearing" subtitle={`Case: ${c.id}`} onClose={() => setHModal(false)} busy={hBusy}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                        <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                            <FieldInput label="Date *" type="date" value={form.date} onChange={v => setForm(p => ({ ...p, date: v }))} />
                            <FieldInput label="Time" type="time" value={form.time} onChange={v => setForm(p => ({ ...p, time: v }))} />
                        </div>
                        <FieldInput label="Court *" value={form.court} onChange={v => setForm(p => ({ ...p, court: v }))} placeholder="e.g. Lahore High Court" maxLength={200} />
                        <FieldInput label="Judge / Presiding Officer" value={form.judge} onChange={v => setForm(p => ({ ...p, judge: v }))} placeholder="e.g. Hon. Justice Mehta" maxLength={120} />
                        <FieldInput label="Purpose / Agenda *" value={form.purpose} onChange={v => setForm(p => ({ ...p, purpose: v }))} placeholder="e.g. Evidence hearing — witness examination" maxLength={300} />
                        <div style={{ fontSize: 12, color: T.textMuted }}>The client sees the new date in their app.</div>
                        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 6 }}>
                            <Btn variant="secondary" onClick={() => setHModal(false)}>Cancel</Btn>
                            <Btn onClick={() => saveHearing()} disabled={hBusy}>{hBusy ? "Scheduling…" : "Schedule Hearing"}</Btn>
                        </div>
                    </div>
                </Modal>
            )}
            {/* Reschedule: the court moved the date; nothing was decided */}
            {rsFor && (
                <Modal title="Reschedule hearing" subtitle={`Now ${fmtDate(rsFor.date)} · ${fmtTime(rsFor.time)} · ${rsFor.court}`} onClose={() => setRsFor(null)} width={480} busy={rsBusy}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                        <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                            <FieldInput label="New date *" type="date" value={rsForm.date} onChange={v => setRsForm(p => ({ ...p, date: v }))} />
                            <FieldInput label="Time" type="time" value={rsForm.time} onChange={v => setRsForm(p => ({ ...p, time: v }))} />
                        </div>
                        <Textarea label="Reason (shown to the client)" rows={2} value={rsForm.reason} onChange={v => setRsForm(p => ({ ...p, reason: v }))}
                            placeholder="e.g. Judge on leave; the court reader gave the new date" maxLength={300} />
                        <div style={{ fontSize: 12, color: T.textMuted }}>The client is notified of the new date. The old date stays on the hearing's record.</div>
                        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
                            <Btn variant="secondary" onClick={() => setRsFor(null)}>Cancel</Btn>
                            <Btn onClick={saveReschedule} disabled={rsBusy || !rsForm.date}>{rsBusy ? "Saving…" : "Reschedule & notify client"}</Btn>
                        </div>
                    </div>
                </Modal>
            )}
            {/* Peshi tracker — record outcome, and plan what follows */}
            {outcomeFor && (
                <Modal title="Record Hearing Outcome" subtitle={`${fmtDate(outcomeFor.date)} · ${outcomeFor.purpose || "Hearing"}`} onClose={() => setOutcomeFor(null)} width={760} busy={oBusy}>
                    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.25fr) minmax(0, 1fr)", gap: 18 }}>
                        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                            <div>
                                <div style={{ fontSize: 11, fontWeight: 700, color: T.textMuted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>What happened? *</div>
                                <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 7 }}>
                                    {OUTCOME_OPTIONS.map(([key, label]) => (
                                        <button key={key} type="button" onClick={() => { setOForm(p => ({ ...p, outcome: key })); setPicked({}); }} style={{
                                            padding: "9px 10px", borderRadius: 9, fontSize: 12, fontWeight: 600, cursor: "pointer", textAlign: "left",
                                            border: `1.5px solid ${oForm.outcome === key ? T.primary : T.border}`,
                                            background: oForm.outcome === key ? T.primaryGlow2 : "transparent",
                                            color: oForm.outcome === key ? T.primary : T.textMuted, fontFamily: "inherit",
                                        }}>{label}</button>
                                    ))}
                                </div>
                            </div>
                            <Textarea label="Note for the client (optional)" value={oForm.note} onChange={v => setOForm(p => ({ ...p, note: v }))} rows={2} placeholder="e.g. Opposing counsel sought time to file reply" maxLength={2000} />
                            <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                                <FieldInput label="Next hearing date (auto-schedules)" type="date" value={oForm.next_date} onChange={v => setOForm(p => ({ ...p, next_date: v }))} />
                                <FieldInput label="Time" type="time" value={oForm.next_time} onChange={v => setOForm(p => ({ ...p, next_time: v }))} />
                            </div>
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: 14, borderRadius: 12, background: "rgba(0,0,0,0.14)", border: `1px solid ${T.border}`, alignSelf: "start" }}>
                            <div style={{ fontSize: 11.5, fontWeight: 800, letterSpacing: "0.14em", textTransform: "uppercase", color: TEAL }}>
                                {oForm.next_date ? `Prepare for ${fmtDate(oForm.next_date)}` : "Follow-up tasks"}
                            </div>
                            {suggestions.length === 0 && <div style={{ fontSize: 12.5, color: T.textMuted }}>No follow-up suggested for this outcome.</div>}
                            {suggestions.map(x => {
                                const on = picked[x.title] !== false;
                                return (
                                    <button key={x.title} type="button" role="checkbox" aria-checked={on} onClick={() => setPicked(p => ({ ...p, [x.title]: !on }))} style={{
                                        display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", borderRadius: 9, border: "none",
                                        background: "rgba(0,0,0,0.16)", color: T.text, fontSize: 12.5, textAlign: "left", cursor: "pointer", fontFamily: "inherit",
                                    }}>
                                        <span style={{ width: 16, height: 16, borderRadius: 4, flexShrink: 0, display: "inline-flex", alignItems: "center", justifyContent: "center", background: on ? TEAL : "transparent", border: on ? "none" : `1.5px solid ${T.textFaint}`, color: "#0b1c22" }}>{on && <Icon d={I.check} size={11} />}</span>
                                        <span style={{ flex: 1 }}>{x.title}</span>
                                        <span style={{ color: T.textMuted, whiteSpace: "nowrap" }}>by {fmtDate(x.due)}</span>
                                    </button>
                                );
                            })}
                            <div style={{ fontSize: 11.5, color: T.textMuted, lineHeight: 1.5 }}>
                                Ticked items are added to Tasks. The client is notified of the outcome in English and Urdu.
                            </div>
                        </div>
                    </div>
                    <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 16 }}>
                        <Btn variant="secondary" onClick={() => setOutcomeFor(null)}>Cancel</Btn>
                        <Btn onClick={saveOutcome} disabled={oBusy}>{oBusy ? "Saving…" : "Record & Notify Client"}</Btn>
                    </div>
                </Modal>
            )}
            {eng.termsModal}
            <Toast msg={toast} />
        </div>
    );
}

// ── Shared bits of the case tabs (2026-10-09, "Cases Workspace v2") ─────────
/** "Wed 14 Oct" for a YYYY-MM-DD (or ISO) date, read as a calendar day. */
function shortDay(d) {
    const dt = new Date(`${String(d).slice(0, 10)}T12:00:00Z`);
    if (Number.isNaN(dt.getTime())) return "";
    return new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(dt);
}
/** "14 Oct" for a date. */
function dayMonth(d) {
    const dt = new Date(`${String(d).slice(0, 10)}T12:00:00Z`);
    if (Number.isNaN(dt.getTime())) return "";
    return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }).format(dt);
}
/** A calendar tile: month band over the day number (and the weekday). */
function DateTile({ date, weekday = false, tone = "brand" }) {
    const dt = new Date(`${String(date).slice(0, 10)}T12:00:00Z`);
    const f = (o) => new Intl.DateTimeFormat("en-GB", { ...o, timeZone: "UTC" }).format(dt);
    return (
        <span className={`cw-date ${tone}`} aria-hidden="true">
            <i>{f({ month: "short" }).toUpperCase()}</i>
            <b className="serif">{f({ day: "numeric" })}</b>
            {weekday && <small>{f({ weekday: "short" }).toUpperCase()}</small>}
        </span>
    );
}
const CardLabel = ({ children, tone }) => <div className={`cw-label${tone ? ` ${tone}` : ""}`}>{children}</div>;

// ── Overview ──────────────────────────────────────────────────
function CaseOverview({ c, cases, hearings, nextHearing, past, tasks, messages, docs, lastCourt, engagement, eng, onSaveHearing, onRecord, onReschedule, goTab, openAdd, readOnly, setPage }) {
    const [quick, setQuick] = useState({ date: "", time: "10:00", court: lastCourt });
    // The court is filled from the latest hearing's court when that becomes
    // known after the form opened (a reload, a live update) — but never once
    // the lawyer has typed in it.
    const courtTouched = useRef(false);
    useEffect(() => {
        if (!courtTouched.current && lastCourt) setQuick(q => (q.court ? q : { ...q, court: lastCourt }));
    }, [lastCourt]);
    const [saving, setSaving] = useState(false);
    const today = pktToday();
    const openTasks = (tasks || []).filter(x => !x.done);
    const overdueHearing = hearings.find(h => h.status === "upcoming" && daysUntil(h.date) < 0);

    const fileItems = [
        ["Client details", !!c.client && c.client !== "—", null],
        ["Province", !!c.court && c.court !== "—", null],
        ["Case type", !!c.type, null],
        ["First hearing", hearings.length > 0, () => openAdd()],
        ["Task plan", (tasks || []).length > 0, () => goTab("tasks")],
        ["Client contacted", (messages || []).length > 0, () => goTab("messages")],
    ].map(([name, ok, fix]) => [name, ok, readOnly ? null : fix]);   // a closed case is a record: no shortcuts to add
    const done = fileItems.filter(x => x[1]).length;
    const R = 26, C = 2 * Math.PI * R;

    // COMING UP: what the lawyer must do next, in date order — an overdue task
    // first, then the hearings and tasks ahead. Five at most.
    const coming = [
        ...hearings.filter(h => h.status === "upcoming").map(h => ({ key: h.id, kind: "Hearing", tone: "brand", title: h.purpose || "Hearing", sub: `${fmtTime(h.time)} · ${h.court}`, date: h.date })),
        ...openTasks.filter(x => x.due).map(x => ({ key: x._id, kind: "Task", tone: "gold", title: x.title, sub: String(x.due).slice(0, 10) < today ? "Overdue" : (x.description || "Task due"), date: String(x.due).slice(0, 10), late: String(x.due).slice(0, 10) < today })),
    ].sort((a, b) => a.date.localeCompare(b.date)).slice(0, 5);
    // RECENT ACTIVITY: hearings held and documents drafted, newest first.
    const recent = [
        ...past.map(h => ({ key: h.id, tone: "green", title: `Hearing held — ${h.outcomeLabel || h.outcome || "outcome recorded"}`, sub: h.outcomeNote || h.court, date: h.date })),
        ...(docs || []).filter(d => d.updated_at || d.created_at).map(d => ({ key: d._id || d.id, tone: "violet", title: d.title || "Document", sub: d._v2 ? `Document · v${d.version || 1}` : "Document", date: String(d.updated_at || d.created_at).slice(0, 10) })),
    ].filter(x => x.date <= today).sort((a, b) => b.date.localeCompare(a.date)).slice(0, 5);

    const saveQuick = async () => {
        setSaving(true);
        const ok = await onSaveHearing({ date: quick.date, time: quick.time, court: quick.court, judge: "", purpose: "Hearing" });
        setSaving(false);
        if (ok) setQuick(q => ({ ...q, date: "" }));
    };

    // The single most useful thing to show first, from the case's own data.
    let lead;
    if (readOnly) {
        lead = (<>
            <CardLabel>Case closed</CardLabel>
            <h2 className="serif">This case is {c.status.toLowerCase()}</h2>
            <p className="cw-muted">Nothing more to do here. Its hearings, messages and tasks stay available to read.</p>
        </>);
    } else if (overdueHearing) {
        lead = (<>
            <CardLabel tone="red">Outcome due</CardLabel>
            <h2 className="serif">Record what happened on {fmtDate(overdueHearing.date)}</h2>
            <p className="cw-muted">{overdueHearing.purpose || "Hearing"} at {overdueHearing.court}. Recording the outcome notifies the client and can set the next date.</p>
            <div className="cw-row-btns">
                <button type="button" className="cw-cta gold" onClick={() => onRecord(overdueHearing)}>Record outcome</button>
                <button type="button" className="cw-btn" onClick={() => onReschedule(overdueHearing)}>Reschedule</button>
            </div>
        </>);
    } else if (!nextHearing) {
        lead = (<>
            <CardLabel tone="gold">Next step</CardLabel>
            <h2 className="serif">{hearings.length ? "Set the next hearing date" : "Set the first hearing date"}</h2>
            <p className="cw-muted">Take it from the court summons or today's Cause List. Once saved, the client sees it in their app.</p>
            <div className="cw-form" style={{ gridTemplateColumns: "1.1fr 0.8fr 1.3fr auto" }}>
                <FieldInput label="Date" type="date" value={quick.date} onChange={v => setQuick(q => ({ ...q, date: v }))} />
                <FieldInput label="Time" type="time" value={quick.time} onChange={v => setQuick(q => ({ ...q, time: v }))} />
                <FieldInput label="Court" value={quick.court} onChange={v => { courtTouched.current = true; setQuick(q => ({ ...q, court: v })); }} placeholder="e.g. Civil Court Lahore" maxLength={200} />
                <button type="button" className="cw-cta" disabled={saving || !quick.date || !quick.court} onClick={saveQuick}>{saving ? "Saving…" : "Save hearing"}</button>
            </div>
        </>);
    } else {
        const d = daysUntil(nextHearing.date);
        const before = openTasks.filter(x => !x.due || String(x.due).slice(0, 10) <= nextHearing.date).length;
        lead = (<>
            <CardLabel tone="brand">Next hearing</CardLabel>
            <h2 className="serif">{nextHearing.purpose || "Hearing"}</h2>
            <p className="cw-muted" style={{ marginTop: 2 }}>{nextHearing.court}</p>
            <div className="cw-next">
                <DateTile date={nextHearing.date} />
                <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="cw-when"><span className="cap">{inDays(d)}</span> · {shortDay(nextHearing.date)}, {fmtTime(nextHearing.time)}</div>
                    <div className="cw-muted">Prepare for {fmtDate(nextHearing.date)}: {before ? `${before} open task${before === 1 ? "" : "s"} before this date` : "no open tasks before this date"}</div>
                </div>
                <div className="cw-row-btns" style={{ marginTop: 0 }}>
                    <button type="button" className="cw-btn" onClick={() => onReschedule(nextHearing)}>Reschedule</button>
                    <button type="button" className="cw-btn" onClick={() => onRecord(nextHearing)}>Record outcome</button>
                </div>
            </div>
        </>);
    }

    const links = [
        [I.calendar, "Hearings", "schedule"],
        [I.checkSquare, "Tasks", "tasks"],
        [I.chat, "Messages", "messages"],
        [I.fileText, "Documents", "documents"],
    ];
    const fees = engagement && (FEE_TYPE_OPTIONS.find(o => o.value === engagement.fee_type) || {}).label;
    const facts = [
        ["Case no.", c.id, true],
        ["Court", lastCourt || "—"],
        ["Province", c.court],
        ["Case type", c.type],
        ["Opened", c.createdAt ? fmtDate(c.createdAt) : "—"],
        engagement?.fee_amount ? ["Agreed fee", `Rs. ${Number(engagement.fee_amount).toLocaleString()}${fees ? ` · ${fees}` : ""}`] : null,
    ].filter(Boolean);
    const clientCases = cases.filter(x => x.client === c.client).length;

    return (
        <div className="cw-split">
            <div className="cw-col">
                <div className={`cw-card cw-lead${overdueHearing && !readOnly ? " red" : !nextHearing && !readOnly ? " gold" : ""}`}>{lead}</div>
                <div className="cw-links">
                    {links.map(([icon, text, to]) => (
                        <button key={to} type="button" className="cw-link-card" onClick={() => goTab(to)}>
                            <Icon d={icon} size={18} />{text}
                        </button>
                    ))}
                </div>
                <div className="cw-card" data-feed>
                    <div className="cw-card-head">
                        <CardLabel>Coming up</CardLabel>
                        <button type="button" className="cw-textlink" onClick={() => goTab("schedule")}>Full schedule →</button>
                    </div>
                    {coming.length === 0 && <div className="cw-muted" style={{ padding: "6px 0 2px" }}>Nothing scheduled yet.{readOnly ? "" : " Set the next hearing above."}</div>}
                    {coming.map(f => {
                        const d = daysUntil(f.date);
                        return (
                            <div key={f.key} data-feed-item className="cw-tl">
                                <div className="cw-tl-when"><b>{dayMonth(f.date)}</b><span className={d !== null && d < 0 ? "late" : ""}>{inDays(d)}</span></div>
                                <i className={`cw-ring ${f.late ? "red" : f.tone}`} aria-hidden="true" />
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div className="cw-tl-title">{f.title}</div>
                                    <div className={`cw-tl-sub${f.late ? " late" : ""}`}>{f.sub}</div>
                                </div>
                                <span className={`cw-tag ${f.tone}`}>{f.kind}</span>
                            </div>
                        );
                    })}
                </div>
                <div className="cw-card">
                    <CardLabel>Recent activity</CardLabel>
                    {recent.length === 0 && <div className="cw-muted" style={{ paddingTop: 8 }}>Nothing yet.</div>}
                    {recent.map(f => (
                        <div key={f.key} className="cw-tl">
                            <div className="cw-tl-when"><b>{dayMonth(f.date)}</b></div>
                            <i className={`cw-ring ${f.tone}`} aria-hidden="true" />
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div className="cw-tl-title">{f.title}</div>
                                {f.sub && <div className="cw-tl-sub">{f.sub}</div>}
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            <div className="cw-col">
                <div className="cw-card">
                    <CardLabel>Case file</CardLabel>
                    <div className="cw-file">
                        <svg width="68" height="68" viewBox="0 0 64 64" aria-hidden="true">
                            <circle cx="32" cy="32" r={R} fill="none" stroke="var(--line-strong)" strokeWidth="7" />
                            <circle cx="32" cy="32" r={R} fill="none" stroke="var(--brand-text)" strokeWidth="7" strokeLinecap="round"
                                strokeDasharray={`${C * done / fileItems.length} ${C}`} transform="rotate(-90 32 32)" />
                        </svg>
                        <div>
                            <div className="serif cw-big">{done}/{fileItems.length}</div>
                            <div className="cw-muted">details complete</div>
                        </div>
                    </div>
                    {fileItems.map(([name, ok, fix]) => (
                        <div key={name} className="cw-check">
                            <span className={`cw-box${ok ? " on" : ""}`} aria-hidden="true">{ok && <Icon d={I.check} size={12} />}</span>
                            <span style={{ flex: 1, color: ok ? "var(--ink)" : "var(--muted)" }}>{name}</span>
                            {!ok && fix && <button type="button" className="cw-textlink" onClick={fix}>Add</button>}
                        </div>
                    ))}
                </div>
                <div className="cw-card">
                    <CardLabel>Client</CardLabel>
                    <div className="cw-client">
                        <Avatar name={c.client} size={44} />
                        <div style={{ minWidth: 0 }}>
                            <b>{c.client}</b>
                            <span>{c.walkIn ? (c.clientPhone || "Walk-in client") : `${clientCases} case${clientCases === 1 ? "" : "s"} with you · replies in app`}</span>
                        </div>
                    </div>
                    <div className="cw-row-btns" style={{ gridTemplateColumns: "1fr 1fr", display: "grid" }}>
                        <button type="button" className="cw-btn" onClick={() => goTab("messages")}><Icon d={I.chat} size={15} />Message</button>
                        <button type="button" className="cw-btn" onClick={() => setPage?.("clients")}>Profile</button>
                    </div>
                </div>
                <div className="cw-card">
                    <CardLabel>Key facts</CardLabel>
                    <dl className="cw-facts">
                        {facts.map(([k, v, mono]) => (
                            <div key={k}><dt>{k}</dt><dd className={mono ? "mono" : ""}>{v}</dd></div>
                        ))}
                    </dl>
                </div>
                {engagement && (
                    <div className="cw-card">
                        <CardLabel>Engagement</CardLabel>
                        <div style={{ fontSize: 14, marginTop: 8 }}>
                            {engagement.fee_amount ? `PKR ${Number(engagement.fee_amount).toLocaleString()}` : "Fee agreed"}
                            {engagement.fee_type ? <span className="cw-muted"> · {fees || engagement.fee_type}</span> : null}
                        </div>
                        <div className="cw-row-btns">
                            <button type="button" className="cw-btn" disabled={eng.busy} onClick={() => eng.handleComplete(engagement)}>
                                {engagement.completion_proposed_by === "client" ? "Confirm complete" : "Mark complete"}
                            </button>
                            <button type="button" className="cw-btn danger" disabled={eng.busy} onClick={() => eng.handleTerminate(engagement)}>End engagement</button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

// ── Schedule ──────────────────────────────────────────────────
function CaseSchedule({ upcoming, past, lastCourt, busy, onSchedule, onRecord, onReschedule, readOnly }) {
    // Scheduling is IN the tab: the form sits above the list it adds to. It
    // goes through the same save as the header's Add hearing (one request id
    // per hearing, a busy guard, the server's copy back).
    const empty = { date: "", time: "10:00", court: lastCourt || "", judge: "", purpose: "" };
    const [f, setF] = useState(empty);
    const courtTouched = useRef(false);
    useEffect(() => {
        if (!courtTouched.current && lastCourt) setF(p => (p.court ? p : { ...p, court: lastCourt }));
    }, [lastCourt]);
    const submit = async () => {
        if (await onSchedule(f)) setF({ ...empty, court: f.court });
    };

    const row = (h, i, isPast) => {
        const d = daysUntil(h.date);
        return (
            <div key={h.id} className="cw-hrow">
                <DateTile date={h.date} weekday tone={isPast ? "green" : d !== null && d < 0 ? "red" : "brand"} />
                <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="cw-tl-title" style={{ fontSize: 16 }}>{h.purpose || `Hearing ${i + 1}`}</div>
                    <div className="cw-tl-sub">{fmtTime(h.time)} · {h.court}{h.judge ? ` · ${h.judge}` : ""}</div>
                    {isPast && h.outcome && <div className="cw-tl-sub" style={{ color: "var(--gold)" }}>{h.outcomeLabel || h.outcome}{h.outcomeNote ? ` — ${h.outcomeNote}` : ""}</div>}
                    {h.movedFrom?.length > 0 && <div className="cw-tl-sub">Rescheduled from {h.movedFrom.map(x => fmtDate(x)).join(", then ")}</div>}
                </div>
                {isPast ? <span className="cw-tag green">Held</span> : (<>
                    <span className={`cw-tag ${d !== null && d < 0 ? "red" : "brand"}`}>{d !== null && d < 0 ? "Outcome due" : h.movedFrom?.length ? `Rescheduled · ${inDays(d)}` : inDays(d)}</span>
                    {!readOnly && <button type="button" className="cw-btn" onClick={() => onReschedule(h)}>Reschedule</button>}
                    {!readOnly && <button type="button" className="cw-btn" onClick={() => onRecord(h)}>Record outcome</button>}
                </>)}
            </div>
        );
    };
    const section = (title, list, isPast) => (
        <div className="cw-card cw-flush">
            <div className="cw-band"><span>{title}</span><span>{list.length}</span></div>
            {list.length ? list.map((h, i) => row(h, i, isPast)) : (
                <div className="cw-empty">{isPast ? "No past hearings yet." : "No upcoming hearings."}</div>
            )}
        </div>
    );
    return (
        <div className="cw-col">
            {!readOnly && (
                <div className="cw-card" data-schedule-form>
                    <p style={{ margin: "0 0 10px", fontSize: 14 }}>Schedule a hearing. Recording an outcome later notifies the client and can set the next date.</p>
                    <div className="cw-form" style={{ gridTemplateColumns: "0.9fr 0.7fr 1.2fr 1.2fr auto" }}>
                        <FieldInput label="Date *" type="date" value={f.date} onChange={v => setF(p => ({ ...p, date: v }))} />
                        <FieldInput label="Time" type="time" value={f.time} onChange={v => setF(p => ({ ...p, time: v }))} />
                        <FieldInput label="Court *" value={f.court} onChange={v => { courtTouched.current = true; setF(p => ({ ...p, court: v })); }} placeholder="e.g. Civil Court Lahore, Room 3" maxLength={200} />
                        <FieldInput label="Purpose / Agenda *" value={f.purpose} onChange={v => setF(p => ({ ...p, purpose: v }))} placeholder="e.g. Arguments on bail" maxLength={300} />
                        <button type="button" className="cw-cta" disabled={busy} onClick={submit}><Icon d={I.plus} size={15} />{busy ? "Scheduling…" : "Schedule Hearing"}</button>
                    </div>
                </div>
            )}
            {section("Upcoming", upcoming, false)}
            {section("Past", past, true)}
        </div>
    );
}

// ── Messages ──────────────────────────────────────────────────
function CaseMessages({ caseId, c, messages, setMessages, loading, nextHearing, readOnly, counsel = null }) {
    const [reply, setReply] = useState("");
    const [sending, setSending] = useState(false);
    const [sendError, setSendError] = useState(null);
    const endRef = useRef(null);
    useEffect(() => { endRef.current?.scrollIntoView?.({ behavior: "smooth" }); }, [messages]);

    const send = async () => {
        const text = reply.trim();
        if (!text || sending) return;
        setSending(true);
        setSendError(null);
        setReply("");
        const { data, error } = await apiSendMessage(caseId, text);
        if (!error && data) setMessages(prev => [...(prev || []), data]);
        else {
            // Keep what was typed AND say it did not go: the box refilling
            // with no reason read like a glitch, not a failed send.
            setReply(text);
            setSendError(error?.message || "Your message was not sent. Try again.");
        }
        setSending(false);
    };

    // Quick replies only prefill the box; nothing is sent until Send.
    const quick = [
        ["Request a document", "Please share a copy of the document when you can — you can reply here with the details."],
        nextHearing && ["Share next hearing date", `The next hearing is on ${fmtDate(nextHearing.date)} at ${fmtTime(nextHearing.time)}, ${nextHearing.court}.`],
        ["Ask for an update", "Is there anything new on your side that I should know before the next hearing?"],
    ].filter(Boolean);

    return (
        <div className="cw-split">
            <div className="cw-card cw-flush cw-chat">
                <div className="cw-chat-head">
                    <Avatar name={c.client} size={40} />
                    <div>
                        <b>{c.client}</b>
                        <span>Messages stay inside this case · the client replies in their app</span>
                    </div>
                </div>
                <div className="cw-chat-body">
                    {loading && <div className="cw-muted" style={{ textAlign: "center" }}>Loading messages…</div>}
                    {!loading && messages.length === 0 && (
                        <div className="cw-muted" style={{ textAlign: "center", margin: "auto" }}>No messages yet. Start the conversation, or use a quick message below.</div>
                    )}
                    {messages.map((m, i) => {
                        const mine = m.sender_role === "lawyer";
                        const time = m.created_at ? new Date(m.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
                        return (
                            <div key={m._id || i} className={`cw-msg${mine ? " mine" : ""}`}>
                                {!mine && <Avatar name={m.sender_name || c.client} size={32} />}
                                <div className="cw-bubble">
                                    <div style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{m.text}</div>
                                    <small>{time}</small>
                                </div>
                            </div>
                        );
                    })}
                    <div ref={endRef} />
                </div>
                {c.walkIn ? (
                    <div data-walk-in-note className="cw-chat-foot cw-muted">
                        {c.client} is not on Attorney.AI, so messages cannot be sent here.
                        {c.clientPhone ? <> Call or WhatsApp them on <strong style={{ color: "var(--ink)" }}>{c.clientPhone}</strong>.</> : " Contact them directly."}
                    </div>
                ) : readOnly ? (
                    <div className="cw-chat-foot cw-muted">This case is closed, so no new messages can be sent.</div>
                ) : (<div className="cw-chat-foot">
                    <div className="cw-chips">
                        {quick.map(([label, text]) => (
                            <button key={label} type="button" onClick={() => setReply(text)}>{label}</button>
                        ))}
                    </div>
                    <div className="cw-compose">
                        <input value={reply} onChange={e => { setReply(e.target.value); setSendError(null); }} disabled={sending} maxLength={4000}
                            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                            placeholder={`Write to ${c.client}…`} />
                        <button type="button" className="cw-cta" aria-label="Send message" onClick={send} disabled={sending || !reply.trim()}>
                            <Icon d={I.send} size={15} />Send
                        </button>
                    </div>
                    {sendError && <div role="alert" style={{ marginTop: 8, fontSize: 12.5, color: "var(--danger)" }}>{sendError}</div>}
                </div>)}
            </div>
            <div className="cw-card">
                <CardLabel>Pinned for the client</CardLabel>
                <div className="cw-pin">
                    <b>Next hearing</b>
                    <span>{nextHearing ? `${shortDay(nextHearing.date)}, ${fmtTime(nextHearing.time)} · ${nextHearing.court}` : "Not set yet"}</span>
                </div>
                {counsel && (
                    <div className="cw-pin">
                        <b>Your counsel</b>
                        <span>{counsel}</span>
                    </div>
                )}
                <p className="cw-muted" style={{ margin: "12px 0 0", fontSize: 12.5, lineHeight: 1.55 }}>Files cannot be attached to case messages yet. To share a draft, use the Documents tab.</p>
            </div>
        </div>
    );
}

// ── Tasks ─────────────────────────────────────────────────────
function CaseTasks({ caseId, tasks, setTasks, loading, nextHearing, showToast, focusSignal, readOnly }) {
    const [title, setTitle] = useState("");
    const [due, setDue] = useState("");
    const [busy, setBusy] = useState(false);
    const inputRef = useRef(null);
    useEffect(() => { if (focusSignal) inputRef.current?.focus(); }, [focusSignal]);

    const toggle = async (task) => {
        const newDone = !task.done;
        setTasks(prev => prev.map(x => x._id === task._id ? { ...x, done: newDone } : x));
        const { error } = await apiToggleTask(caseId, task._id, newDone);
        if (error) {
            // Put it back, and say so: it used to flip back with no reason.
            setTasks(prev => prev.map(x => x._id === task._id ? { ...x, done: task.done } : x));
            showToast("❌ " + (error.message || "Could not update the task"));
        }
    };

    const add = async (taskTitle, taskDue = null) => {
        const { data, error } = await apiAddTask(caseId, { title: taskTitle, due: taskDue, priority: "medium", description: null });
        if (!error && data) { setTasks(prev => [...(prev || []), data]); return true; }
        showToast("❌ " + (error?.message || "Could not add the task"));
        return false;
    };
    const addOne = async () => {
        if (!title.trim() || busy) return;
        setBusy(true);
        if (await add(title.trim(), due || null)) { setTitle(""); setDue(""); }
        setBusy(false);
    };
    const addTemplate = async (tpl) => {
        if (busy) return;
        setBusy(true);
        let n = 0;
        for (const item of tpl.items) { if (await add(item)) n += 1; }
        setBusy(false);
        showToast(`✅ ${n} task${n === 1 ? "" : "s"} added from “${tpl.label}”`);
    };

    const today = pktToday();
    const dueOf = (x) => (x.due ? String(x.due).slice(0, 10) : null);
    const total = tasks.length;
    const doneN = tasks.filter(x => x.done).length;
    const open = tasks.filter(x => !x.done);
    const hDate = nextHearing?.date;
    const overdue = open.filter(x => dueOf(x) && dueOf(x) < today);
    const before = open.filter(x => !overdue.includes(x) && (!hDate || !dueOf(x) || dueOf(x) <= hDate));
    const later = open.filter(x => !overdue.includes(x) && hDate && dueOf(x) && dueOf(x) > hDate);
    const finished = tasks.filter(x => x.done);

    const taskRow = (x) => {
        const d = dueOf(x) ? daysUntil(dueOf(x)) : null;
        return (
            <div key={x._id} className="cw-task">
                <button type="button" role="checkbox" aria-checked={!!x.done} aria-label={x.title} disabled={readOnly} onClick={() => toggle(x)}
                    className={`cw-box big${x.done ? " on" : ""}`}>{x.done && <Icon d={I.check} size={14} />}</button>
                <div style={{ flex: 1, minWidth: 0 }}>
                    <div className={`cw-task-title${x.done ? " done" : ""}`}>{x.title}</div>
                    {x.description && <div className="cw-tl-sub">{x.description}</div>}
                </div>
                {x.done ? <span className="cw-tag green">Done</span> : dueOf(x) ? (
                    <span className={`cw-due${d !== null && d < 0 ? " late" : d !== null && d <= 3 ? " soon" : ""}`}>
                        {d !== null && d < 0 ? `${inDays(d)} · ` : "by "}{dayMonth(dueOf(x))}
                    </span>
                ) : null}
            </div>
        );
    };
    const group = (label, list, tone) => list.length > 0 && (
        <Fragment key={label}>
            <div className={`cw-band${tone ? ` ${tone}` : ""}`}><span>{label}</span><span>{list.length}</span></div>
            {list.map(taskRow)}
        </Fragment>
    );

    return (
        <div className="cw-split">
            <div className="cw-col">
                <div className="cw-card cw-progress">
                    <div className="serif cw-big" style={{ fontSize: 38 }}>{doneN}/{total}</div>
                    <div style={{ flex: 1 }}>
                        <div className="cw-bar"><i style={{ width: `${total ? (doneN / total) * 100 : 0}%` }} /></div>
                        <div className="cw-muted" style={{ marginTop: 8 }}>
                            {total - doneN} task{total - doneN === 1 ? "" : "s"} left{nextHearing ? ` before ${fmtDate(nextHearing.date)}` : ""}
                            {overdue.length > 0 && <span style={{ color: "var(--danger)" }}> · {overdue.length} overdue</span>}
                        </div>
                    </div>
                </div>

                <div className="cw-card cw-flush">
                    {loading && <div className="cw-empty">Loading tasks…</div>}
                    {!loading && total === 0 && <div className="cw-empty">No tasks yet. Add one below or start from a checklist.</div>}
                    {group("Overdue", overdue, "red")}
                    {group(nextHearing ? "Before the next hearing" : "Open", before)}
                    {group("Later", later)}
                    {group("Done", finished)}
                    {!readOnly && <div className="cw-compose" style={{ padding: "14px 18px 16px", borderTop: "1px solid var(--line)" }}>
                        <input ref={inputRef} value={title} onChange={e => setTitle(e.target.value)} placeholder="Add a task for this case…" maxLength={200}
                            onKeyDown={e => { if (e.key === "Enter") addOne(); }} />
                        <input type="date" aria-label="Due date" value={due} onChange={e => setDue(e.target.value)} style={{ flex: "0 0 180px" }} />
                        <button type="button" className="cw-cta" onClick={addOne} disabled={busy || !title.trim()}>Add</button>
                    </div>}
                </div>
            </div>

            <div className="cw-card">
                <CardLabel>Checklists</CardLabel>
                <p className="cw-muted" style={{ margin: "6px 0 12px" }}>Add a ready set of tasks for the next stage.</p>
                {readOnly && <div className="cw-muted">Closed case: no new tasks.</div>}
                {!readOnly && TASK_TEMPLATES.map(tpl => (
                    <button key={tpl.label} type="button" className="cw-tpl" disabled={busy} onClick={() => addTemplate(tpl)} title={tpl.items.join(" · ")}>
                        <span style={{ flex: 1, minWidth: 0 }}>
                            <b>{tpl.label}</b>
                            <small>{tpl.items.length} tasks · {tpl.items.slice(0, 2).map(s => s.toLowerCase()).join(", ")}</small>
                        </span>
                        <Icon d={I.plus} size={18} />
                    </button>
                ))}
            </div>
        </div>
    );
}

// ── Documents ─────────────────────────────────────────────────
/** A document row's status, in a word. */
/* WHAT THE CLIENT SENT ON THIS CASE (2026-10-11). The case's Documents tab
 * listed only what the lawyer owns, so a plaint the client sent on this very
 * case was missing from it ("No documents yet") and reachable only from the
 * review inbox. The inbox already returns, per row, the case and the exact
 * revision this lawyer may open -- the one sent to them, or the one they
 * decided on -- so the case's rows are taken from it. Nothing new is exposed:
 * the server scopes every row to this lawyer. A few pages at most. */
async function clientDocsForCase(caseId) {
    const rows = [];
    let cursor = null;
    for (let page = 0; page < 5; page++) {
        const { data, error } = await reviewQueueV2({ status: "all", cursor, limit: 100 });
        if (error || !data) return page ? rows : null;
        for (const r of data.items || []) {
            if (r.case_id !== caseId) continue;
            // The revision this lawyer may open, as the review inbox reads it:
            // the one sent to them, else the one they decided on.
            rows.push({ ...r, _fromClient: true,
                viewRevisionId: r.submitted_revision_id ?? r.reviewed_revision_id ?? null,
                viewPdfSha256: r.submitted_pdf_sha256 ?? r.reviewed_pdf_sha256 ?? null });
        }
        cursor = data.next_cursor;
        if (!cursor) break;
    }
    return rows;
}

const _CLIENT_DOC_STATUS = {
    submitted: "Waiting for you", approved: "Approved", returned: "Returned", rejected: "Rejected",
};

function docStatus(d) {
    if (d._fromClient) return _CLIENT_DOC_STATUS[d.review_status] || "Sent to you";
    if (d._v2) return documentStatusView(d).label;
    const s = d.review_status || d.status || "";
    return s ? s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ") : "Draft";
}

/* THE LAWYER'S OWN FILES ON THE CASE (2026-10-11): a summons, an order, a CNIC
 * copy. Private to the lawyer who uploaded them -- the client is not shown
 * these. PDF, PNG or JPEG up to 10 MB; the server decides the kind from the
 * bytes and says why when it refuses one. */
const _MAX_FILE = 10 * 1024 * 1024;
function _size(n) {
    return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
}

function CaseFiles({ caseId, readOnly }) {
    const [files, setFiles] = useState(null);
    const [failed, setFailed] = useState(false);
    const [busy, setBusy] = useState(null);       // "upload" | file id
    const [issue, setIssue] = useState("");
    const inputRef = useRef(null);

    useEffect(() => {
        let off = false;
        listCaseFiles(caseId).then(({ data, error }) => {
            if (off) return;
            if (error || !data) { setFailed(true); setFiles([]); return; }
            setFailed(false); setFiles(data.items || []);
        });
        return () => { off = true; };
    }, [caseId]);

    const pick = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = "";
        if (!file) return;
        setIssue("");
        if (file.size > _MAX_FILE) { setIssue("That file is larger than 10 MB."); return; }
        setBusy("upload");
        const { data, error } = await uploadCaseFile(caseId, file);
        setBusy(null);
        if (error || !data) { setIssue(error?.message || "The file could not be uploaded."); return; }
        setFiles(prev => [data, ...(prev || [])]);
    };
    const open = async (f) => {
        setIssue(""); setBusy(f.id);
        const { data: url, error } = await openCaseFile(caseId, f.id);
        setBusy(null);
        if (!url) { setIssue(error || "Could not open this file."); return; }
        const win = window.open(url, "_blank");
        if (win) win.opener = null; else setIssue("Your browser blocked the new tab.");
        setTimeout(() => URL.revokeObjectURL?.(url), 60000);
    };
    const remove = async (f) => {
        if (typeof window !== "undefined" && !window.confirm(`Delete "${f.name}" from this case?`)) return;
        setIssue(""); setBusy(f.id);
        const { error } = await deleteCaseFile(caseId, f.id);
        setBusy(null);
        if (error) { setIssue(error.message || "The file could not be deleted."); return; }
        setFiles(prev => (prev || []).filter(x => x.id !== f.id));
    };

    return (
        <div className="cw-col" data-case-files style={{ marginTop: 18 }}>
            <div className="cw-card-head" style={{ alignItems: "center" }}>
                <div>
                    <b style={{ display: "block", fontSize: 15, color: "var(--ink)" }}>Your files</b>
                    <span className="cw-muted" style={{ fontSize: 13 }}>Summons, orders, copies. Only you can see these; the client is not shown them.</span>
                </div>
                {!readOnly && <>
                    <input ref={inputRef} type="file" accept="application/pdf,image/png,image/jpeg" onChange={pick}
                        aria-label="Choose a file to upload" style={{ display: "none" }} />
                    <button type="button" className="cw-btn" onClick={() => inputRef.current?.click()} disabled={busy === "upload"}>
                        <Icon d="M12 15V3M7 8l5-5 5 5M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" size={15} />
                        {busy === "upload" ? "Uploading…" : "Upload file"}
                    </button>
                </>}
            </div>
            {issue && <div role="alert" style={{ fontSize: 13, color: "var(--danger)" }}>{issue}</div>}
            {files === null && <div className="cw-muted">Loading files…</div>}
            {failed && <div role="alert" style={{ fontSize: 13, color: "var(--danger)" }}>Could not load your files for this case.</div>}
            {files && !failed && files.length === 0 && (
                <div className="cw-card cw-empty" style={{ borderStyle: "dashed" }}>
                    {readOnly ? "No files were kept on this case." : "No files yet. Upload a PDF, PNG or JPEG of up to 10 MB."}
                </div>
            )}
            {files && files.length > 0 && (
                <div className="cw-card cw-flush">
                    {files.map(f => (
                        <div key={f.id} className="cw-doc" data-case-file={f.id}>
                            <span className="cw-paper" aria-hidden="true"><i /><i /><i /><i /></span>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div className="cw-tl-title">{f.name}</div>
                                <div className="cw-tl-sub">{f.content_type === "application/pdf" ? "PDF" : "Image"} · {_size(f.size)}{f.created_at ? ` · added ${dayMonth(f.created_at)}` : ""}</div>
                            </div>
                            <span className="cw-tag"><i />Only you</span>
                            <button type="button" className="cw-btn" disabled={busy === f.id} onClick={() => open(f)}>{busy === f.id ? "Opening…" : "Open"}</button>
                            {!readOnly && <button type="button" className="cw-btn" aria-label={`Delete ${f.name}`} title="Delete" disabled={busy === f.id} onClick={() => remove(f)}>
                                <Icon d="M3 6h18M8 6V4h8v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" size={15} />
                            </button>}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

function CaseDocuments({ docs, failed, caseNo, setPage, setActiveCase }) {
    const [busy, setBusy] = useState(null);
    const [issue, setIssue] = useState({});
    // Opens the exact revision a V2 row names; a legacy row, its file.
    const open = async (d) => {
        const id = d.id || d._id;
        setBusy(id);
        setIssue(p => ({ ...p, [id]: null }));
        let url = null, err = null;
        if (d._fromClient) {
            // The revision this lawyer may see -- never "the latest".
            const res = await fetchRevisionPreview(id, { revisionId: d.viewRevisionId, expectedPdfSha256: d.viewPdfSha256 });
            url = res.data?.url || null;
            err = res.error?.message || null;
        } else if (d._v2) {
            const res = await fetchRevisionPreview(id, { revisionId: d.revision_id, expectedPdfSha256: d.pdf_sha256 });
            url = res.data?.url || null;
            err = res.error?.message || null;
        } else {
            const res = await fetchDocumentPreviewUrl(id);
            url = res.data || null;
            err = res.error || null;
        }
        setBusy(null);
        if (!url) { setIssue(p => ({ ...p, [id]: err || "Could not open this document." })); return; }
        const win = window.open(url, "_blank");
        if (win) win.opener = null;
        else setIssue(p => ({ ...p, [id]: "Your browser blocked the new tab." }));
        setTimeout(() => URL.revokeObjectURL?.(url), 60000);
    };
    // Drafting opens on THIS case.
    const draft = () => { setActiveCase?.(caseNo); setPage?.("doc-automation"); };

    return (
        <div className="cw-col">
            <div className="cw-card-head" style={{ alignItems: "center" }}>
                <p className="cw-muted" style={{ margin: 0, fontSize: 14 }}>Documents on this case: sent by the client, or drafted by you.</p>
                {setPage && <button type="button" className="cw-cta" onClick={draft}><Icon d={I.fileText} size={15} />Draft a document</button>}
            </div>
            {docs === null && <div className="cw-muted">Loading documents…</div>}
            {failed && <div role="alert" style={{ fontSize: 13, color: "var(--danger)" }}>Could not load this case's documents.</div>}
            {docs && !failed && docs.length === 0 && (
                <div className="cw-card cw-empty" style={{ borderStyle: "dashed" }}>
                    <b style={{ display: "block", fontSize: 17, color: "var(--ink)" }}>No documents yet</b>
                    The client has sent nothing on this case yet. Draft a plaint, notice or application for it in Legal drafting.
                </div>
            )}
            {docs && docs.length > 0 && (
                <div className="cw-card cw-flush">
                    {docs.map((d, i) => {
                        const id = d.id || d._id || i;
                        const when = d.updated_at || d.created_at;
                        const canOpen = d._fromClient ? !!(d.viewRevisionId && d.viewPdfSha256)
                            : d._v2 ? d.downloadable !== false : true;
                        return (
                            <div key={id} className="cw-doc" data-case-doc={id}>
                                <span className="cw-paper" aria-hidden="true"><i /><i /><i /><i /></span>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div className="cw-tl-title">{d.title || "Document"}</div>
                                    <div className="cw-tl-sub">
                                        {d._fromClient ? `Sent by ${d.client_name || "the client"}${d.submitted_version ? ` · v${d.submitted_version}` : ""}`
                                            : d._v2 ? `v${d.version || 1}` : (d.template_type || "").replace(/_/g, " ")}
                                        {when ? ` · updated ${dayMonth(when)}` : ""}
                                    </div>
                                    {issue[id] && <div role="alert" style={{ fontSize: 12, color: "var(--danger)", marginTop: 4 }}>{issue[id]}</div>}
                                </div>
                                <span className={`cw-tag ${d._fromClient && d.review_status !== "approved" ? "gold" : "brand"}`}><i />{docStatus(d)}</span>
                                <button type="button" className="cw-btn" disabled={!canOpen || busy === id} onClick={() => open(d)}>{busy === id ? "Opening…" : "Open"}</button>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

// ─────────────────────────────────────────────
// CASES PAGE — ties CasesList + CaseWorkspace
// ─────────────────────────────────────────────
function _mapApiCase(c) {
    const hearings = (c.hearing_dates || []).map((h, idx) => ({
        id: `DB-${idx}-${c._id}`,
        _id: h._id || null,          // backend id — required for outcome recording
        date: typeof h.date === "string" ? h.date.split("T")[0] : new Date(h.date).toISOString().split("T")[0],
        time: h.time || "10:00",
        court: h.court || "",
        judge: h.judge || "",
        purpose: h.purpose || h.notes || "",
        outcome: h.outcome || "",
        outcomeLabel: h.outcome_label || "",
        outcomeNote: h.outcome_note || "",
        // Earlier dates this hearing was moved from, oldest first.
        movedFrom: (h.reschedules || []).map(r => (typeof r.from_date === "string" ? r.from_date : new Date(r.from_date).toISOString()).slice(0, 10)),
        status: h.outcome ? "past" : "upcoming",
    }));
    const nextUpcoming = hearings.filter(h => h.status === "upcoming").sort((a, b) => a.date.localeCompare(b.date))[0];
    return {
        id: c.case_number || c._id,
        _id: c._id,
        title: c.title || "Untitled Case",
        client: c.client_name || "—",
        court: c.province ? c.province.charAt(0).toUpperCase() + c.province.slice(1) : "—",
        type: c.case_type ? c.case_type.charAt(0).toUpperCase() + c.case_type.slice(1) : "Other",
        status: caseStatusLabel(c.status),
        createdAt: c.created_at || "",
        // The stored keys, for filtering ("kpk", not the display "Kpk").
        caseTypeKey: c.case_type || "",
        provinceKey: c.province || "",
        // No client account: the lawyer opened it for a walk-in client.
        walkIn: c.walk_in === true,
        clientPhone: c.client_phone || "",
        nextHearing: nextUpcoming?.date || "",
        urgent: c.urgency === "high",
        _apiHearings: hearings,
    };
}

/* THE CASES THEME (2026-10-09). Every screen here -- the list, the case
 * workspace and its tabs, their dialogs -- draws its neutral colours from the
 * lawyer theme object `T`. Pointing those at the document theme's tokens
 * (draftingTheme.js) moves all of them onto the same palette as the rest of
 * the lawyer's document screens, light and dark, without touching a layout.
 * Accent colours stay hex: callers append alpha to them (`${t.success}cc`). */
export function casesTheme(t) {
    return {
        ...t,
        bg: "var(--bg)", surface: "var(--surface)", card: "var(--surface)", cardHi: "var(--surface-2)",
        border: "var(--line)", borderHi: "var(--line-strong)", text: "var(--ink)", textDim: "var(--ink)",
        textMuted: "var(--muted)", textFaint: "var(--faint)", inputBg: "var(--input)",
        shadowCard: "var(--shadow-rest)",
    };
}

function CasesPage() {
    const { t } = useTheme();
    const themed = useMemo(() => casesTheme(t), [t]);
    return (
        <ThemeCtx.Provider value={themed}>
            <div data-cases-ws data-drafting-theme data-mode={draftingMode(t)}>
                <style>{`${DRAFTING_TOKENS_CSS}\n${CASES_WS_CSS}`}</style>
                <CasesScreens />
            </div>
        </ThemeCtx.Provider>
    );
}

function CasesScreens() {
    const { t: T } = useTheme();
    const { setActiveCase, openCaseId, setOpenCaseId } = useCase();
    const [cases, setCases] = useState([]);
    // `hasLoaded`: a list read has succeeded at least once. `loadError`: the
    // last read failed (the cases already shown, if any, are kept). Without
    // these a missing case could only ever be shown as "Loading case…".
    const [hasLoaded, setHasLoaded] = useState(false);
    const [loadError, setLoadError] = useState(null);
    const [requests, setRequests] = useState([]);
    const loading = !hasLoaded && !loadError;

    // Only the NEWEST read may write. A notification and an action can both
    // reload; an older, slower answer must not replace a newer one. Bumped on
    // unmount too, so a read that lands after the page closed writes nothing.
    const loadGen = useRef(0);
    useEffect(() => () => { loadGen.current += 1; }, []);

    /** Re-read every case. Resolves to the mapped list, or null on failure. */
    const loadCases = () => {
        const mine = ++loadGen.current;
        // Every page: the first 50 used to be the whole list.
        return listAllCases(listCases).then(({ data, error }) => {
            if (mine !== loadGen.current) return null;
            if (error || !Array.isArray(data?.items)) {
                setLoadError(error?.message || "Could not load your cases.");
                return null;
            }
            const mapped = data.items.map(_mapApiCase);
            setCases(mapped);
            setLoadError(null);
            setHasLoaded(true);
            return mapped;
        }).catch(() => {
            if (mine === loadGen.current) setLoadError("Could not load your cases.");
            return null;
        });
    };
    // Every engagement, not just `requested`: terms outstanding and engagements
    // to end are actions too. A failed read is REPORTED (it used to be
    // swallowed, so the list simply showed no requests) and keeps what was
    // shown; only the newest read may write.
    const [reqError, setReqError] = useState(null);
    const reqGen = useRef(0);
    useEffect(() => () => { reqGen.current += 1; }, []);
    const loadRequests = () => {
        const mine = ++reqGen.current;
        return listEngagements().then(({ data, error }) => {
            if (mine !== reqGen.current) return;
            if (error || !Array.isArray(data)) {
                setReqError(error?.message || "Could not load case requests.");
                return;
            }
            setRequests(data);
            setReqError(null);
        }).catch(() => { if (mine === reqGen.current) setReqError("Could not load case requests."); });
    };

    useEffect(() => {
        loadCases();
        loadRequests();
    }, []);

    // Engagement and case notices change the request list and the cases (a
    // new request, terms accepted, an engagement ended): re-read both.
    useEffect(() => onNotification((n) => {
        const t = String(n.type || "");
        if (t.startsWith("engagement_") || t === "lawyer_assigned" || t === "case_update") {
            loadRequests();
            loadCases();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }), []);

    // Terms change what the request list shows; acceptance (by the client)
    // is what assigns the case, so both lists still need refreshing.
    const handleRequestsChanged = () => {
        loadRequests();
        loadCases();
    };

    const handleOpenCase = (caseId) => {
        setOpenCaseId(caseId);
        setActiveCase(caseId);
    };

    // A notification names a case by its database id; this page names cases
    // by their case number. Translate, so opening from a notification lands on
    // the case rather than on "not found".
    useEffect(() => {
        if (!openCaseId || cases.some(c => c.id === openCaseId)) return;
        const byDbId = cases.find(c => c._id === openCaseId);
        if (byDbId) setOpenCaseId(byDbId.id);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [openCaseId, cases]);


    if (openCaseId) {
        return (
            <CaseWorkspace
                key={openCaseId}
                caseId={openCaseId}
                cases={cases}
                setCases={setCases}
                requests={requests}
                onRequestsChanged={handleRequestsChanged}
                onBack={() => setOpenCaseId(null)}
                hasLoaded={hasLoaded}
                loadError={loadError}
                onReload={loadCases}
            />
        );
    }

    if (loading) {
        return (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: T.textMuted, fontSize: 14 }}>
                Loading cases…
            </div>
        );
    }

    // The first read failed: say so. "No cases yet" is only for a read that
    // succeeded and was empty.
    if (!hasLoaded) {
        return (
            <div role="alert" style={{ padding: "40px 30px", display: "flex", justifyContent: "center" }}>
                <div style={{ maxWidth: 460, width: "100%", padding: 24, borderRadius: 16, border: `1px solid ${T.border}`, background: T.card }}>
                    <div style={{ fontSize: 17, fontWeight: 800, color: T.text }}>Could not load your cases</div>
                    <div style={{ fontSize: 13.5, color: T.textMuted, marginTop: 8 }}>{loadError}</div>
                    <div style={{ marginTop: 18 }}>
                        <button type="button" onClick={() => { loadCases(); loadRequests(); }} style={solidBtn(TEAL)}>Retry</button>
                    </div>
                </div>
            </div>
        );
    }

    // A new walk-in case: re-read the list, then open the case.
    const handleCaseCreated = (made) => {
        loadCases();
        handleOpenCase(made.case_number || made._id);
    };

    return <CasesList cases={cases} onOpen={handleOpenCase} requests={requests} onRequestsChanged={handleRequestsChanged} onCaseCreated={handleCaseCreated}
        loadError={loadError} onRetryCases={loadCases} reqError={reqError} onRetryRequests={loadRequests} />;
}

export { CasesPage };
