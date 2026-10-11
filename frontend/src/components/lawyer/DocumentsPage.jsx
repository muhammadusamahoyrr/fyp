'use client';
// Lawyer Documents Page — paste your code here
import { useState, useEffect, useRef } from "react";
import { useTheme } from "./theme.js";
import { useCase } from "./theme.js";
import RevisionHistory from "./RevisionHistory.jsx";
import ReviewPdfView, { REVIEW_PDF_CSS, ViewToolsButton } from "./ReviewPdfView.jsx";
import ReviewEditor, { REVIEW_EDITOR_CSS } from "./ReviewEditor.jsx";
import { Icon, I } from "./icons.jsx";
import { DRAFTING_TOKENS_CSS, draftingMode } from "./draftingTheme.js";
import {
    listReviewQueue, reviewDocument, downloadDocumentFile,
    fetchRevisionPreview, reviewDocumentV2, reviewQueueV2, getReviewTextV2, returnWithEditsV2,
    idempotencyKey, errorCode,
    quickReviewInbox, acceptQuickReview, declineQuickReview,
} from "@/lib/api.js";
import { createGeneration } from "@/lib/attempt.js";
import { onNotification } from "@/lib/notificationTarget.js";
import { complianceSummary } from "@/lib/complianceSummary.js";

// ─── THEME ────────────────────────────────────────────────────


// ─── MAPPING HELPERS ──────────────────────────────────────────
const _TMPL_MAP = {
    plaint_civil: "Plaint", written_statement: "Written Statement",
    legal_notice: "Legal Notice", nda: "NDA", rental_agreement: "Rental Agreement",
};
const _CASE_TYPE_MAP = { civil: "Civil", criminal: "Criminal", family: "Family", constitutional: "Constitutional" };
// (The DOC_CONTENT placeholder plaint was removed: the review and final screens
// render the REAL generated PDF inline, pinned to the submitted revision via
// fetchRevisionPreview so the page and the decision are about the same bytes.)

// ═══════════════════════════════════════════════════════════════
// SCREEN 1 — DOCUMENT INBOX
// Lawyer receives submitted documents, sees urgency, client notes
// ═══════════════════════════════════════════════════════════════
// ═══════════════════════════════════════════════════════════════
// SCREEN 1 — DOCUMENT INBOX
// ═══════════════════════════════════════════════════════════════

/* The tabs, and the server status each one asks for.
 *
 * ONE TABLE, so a label and the query behind it cannot drift apart. They did:
 * the queue was fetched with the default status ("submitted") and the tabs then
 * filtered client-side over that one page, so Approved / Returned / Rejected
 * were permanently empty and their counts read 0 while the work existed.
 */
const QUEUE_STATUS_OF = {
    "All": "all",
    "Pending Review": "submitted",
    "Approved": "approved",
    "Returned": "returned",
    "Rejected": "rejected",
};

const QUEUE_TABS = [
    ["All", "all"],
    ["Pending Review", "submitted"],
    ["Approved", "approved"],
    ["Returned", "returned"],
    ["Rejected", "rejected"],
];

/* The review inbox's look (2026-10-09): the Legal Drafting palette
 * (draftingTheme.js). Scoped by [data-review-inbox]. */
export const INBOX_CSS = `[data-review-inbox]{flex:1;min-height:0;overflow-y:auto;background:radial-gradient(900px 360px at 25% -80px,var(--glow),transparent 70%) no-repeat,var(--bg);color:var(--ink);font:15px/1.5 "Hanken Grotesk",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
[data-review-inbox] *{box-sizing:border-box}
[data-review-inbox] button,[data-review-inbox] input{font:inherit;color:inherit}
[data-review-inbox] :focus-visible{outline:2px solid var(--focus);outline-offset:2px}
[data-review-inbox] .ri-wrap{max-width:1240px;margin:0 auto;padding:22px clamp(16px,3.2vw,40px) 64px;display:grid;gap:22px}
[data-review-inbox] .ri-crumbs{font-size:13px;color:var(--muted)}
[data-review-inbox] .ri-crumbs b{color:var(--ink);font-weight:600}
[data-review-inbox] .ri-head{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;flex-wrap:wrap}
[data-review-inbox] .ri-head h1{margin:0;font:600 clamp(28px,3.4vw,38px)/1.1 "Literata",Georgia,serif;letter-spacing:-.01em}
[data-review-inbox] .ri-accent{background:linear-gradient(90deg,var(--brand-text),var(--teal-ink));-webkit-background-clip:text;background-clip:text;color:transparent}
[data-review-inbox] .ri-head p{margin:8px 0 0;color:var(--muted);max-width:66ch}
[data-review-inbox] .ri-btn{display:inline-flex;align-items:center;gap:8px;height:40px;padding:0 16px;border-radius:10px;border:1px solid var(--line-strong);background:var(--surface);font-weight:600;font-size:14px;white-space:nowrap;cursor:pointer}
[data-review-inbox] .ri-btn:hover:not(:disabled){border-color:var(--hover-line);background:var(--hover-tint);color:var(--hover-ink)}
[data-review-inbox] .ri-btn:disabled{opacity:.55;cursor:default}
[data-review-inbox] .ri-btn.primary{background:var(--brand-solid);border-color:transparent;color:var(--on-brand)}
[data-review-inbox] .ri-btn.primary:hover:not(:disabled){background:var(--brand-solid-hover);color:var(--on-brand)}
[data-review-inbox] .ri-cta{display:inline-flex;align-items:center;gap:10px;height:48px;padding:0 24px;border-radius:14px;border:0;background:var(--brand-solid);color:var(--on-brand);font-weight:700;font-size:15.5px;cursor:pointer;box-shadow:0 10px 24px -12px rgba(46,196,214,.8);transition:transform .15s,box-shadow .15s}
[data-review-inbox] .ri-cta:hover{background:var(--brand-solid-hover);transform:translateY(-1px);box-shadow:0 14px 28px -12px rgba(46,196,214,.9)}
[data-review-inbox] .ri-filters{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px}
[data-review-inbox] .ri-f{position:relative;display:grid;grid-template-columns:auto 1fr;grid-template-areas:"ic l" "v v" "s s";column-gap:12px;align-items:center;text-align:left;padding:18px 18px 16px;border-radius:20px;border:1px solid color-mix(in srgb,var(--c) 14%,var(--line));background:radial-gradient(120% 90% at 100% 0%,color-mix(in srgb,var(--c) 13%,transparent) 0%,transparent 55%),linear-gradient(180deg,color-mix(in srgb,var(--surface) 92%,#fff 8%),var(--surface));box-shadow:0 1px 0 rgba(255,255,255,.05) inset,0 10px 24px -18px rgba(0,0,0,.65);cursor:pointer;overflow:hidden;transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease,background .18s ease}
[data-review-inbox] .ri-f:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--c) 45%,var(--line));box-shadow:0 1px 0 rgba(255,255,255,.06) inset,0 18px 32px -20px color-mix(in srgb,var(--c) 70%,#000)}
[data-review-inbox] .ri-f[aria-selected="true"]{border-color:color-mix(in srgb,var(--c) 70%,transparent);background:radial-gradient(130% 100% at 100% 0%,color-mix(in srgb,var(--c) 26%,transparent) 0%,transparent 60%),linear-gradient(180deg,color-mix(in srgb,var(--c) 12%,var(--surface)),var(--surface));box-shadow:0 0 0 3px color-mix(in srgb,var(--c) 18%,transparent),0 18px 32px -20px color-mix(in srgb,var(--c) 70%,#000)}
[data-review-inbox] .ri-f .ic{grid-area:ic;width:38px;height:38px;border-radius:12px;display:grid;place-items:center;color:var(--c);background:color-mix(in srgb,var(--c) 16%,transparent);box-shadow:0 0 0 1px color-mix(in srgb,var(--c) 22%,transparent) inset}
[data-review-inbox] .ri-f[aria-selected="true"] .ic{background:var(--c);color:var(--surface-2)}
[data-review-inbox] .ri-f .l{grid-area:l;display:block;font-size:13.5px;font-weight:600;color:var(--muted);line-height:1.25}
[data-review-inbox] .ri-f[aria-selected="true"] .l{color:var(--ink)}
[data-review-inbox] .ri-f .v{grid-area:v;display:block;font:600 34px/1 "Literata",Georgia,serif;margin:16px 0 6px;letter-spacing:-.01em}
[data-review-inbox] .ri-f .s{grid-area:s;display:block;font-size:12.5px;color:var(--muted)}
[data-review-inbox] .ri-f .tick{position:absolute;top:14px;right:14px;width:20px;height:20px;border-radius:50%;display:grid;place-items:center;background:var(--c);color:var(--surface-2);opacity:0;transform:scale(.6);transition:opacity .18s,transform .18s}
[data-review-inbox] .ri-f[aria-selected="true"] .tick{opacity:1;transform:none}
[data-review-inbox] .ri-card{border-radius:16px;border:1px solid var(--line);background:var(--surface);box-shadow:var(--shadow-rest);overflow:hidden}
[data-review-inbox] .ri-bar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:14px 20px;border-bottom:1px solid var(--line)}
[data-review-inbox] .ri-bar h2{margin:0;font:600 19px/1.2 "Literata",Georgia,serif}
[data-review-inbox] .ri-bar small{display:block;font-size:12.5px;color:var(--muted);margin-top:2px}
[data-review-inbox] .ri-tools{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
[data-review-inbox] .ri-search{flex:1 1 420px;display:flex;align-items:center;gap:10px;height:48px;padding:0 14px;border-radius:12px;background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow-rest)}
[data-review-inbox] .ri-search:hover{border-color:var(--hover-line)}
[data-review-inbox] .ri-search svg{color:var(--faint)}
[data-review-inbox] .ri-kbd{font-family:"JetBrains Mono",monospace;font-size:11px;color:var(--faint);border:1px solid var(--line-strong);border-bottom-width:2px;border-radius:5px;padding:0 6px;line-height:18px}
[data-review-inbox] .ri-filter{position:relative;display:flex;align-items:center;height:48px;border-radius:12px;background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow-rest);min-width:230px}
[data-review-inbox] .ri-filter:hover{border-color:var(--hover-line)}
[data-review-inbox] .ri-filter:focus-within{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-review-inbox] .ri-filter > svg{position:absolute;left:14px;color:var(--muted);pointer-events:none}
[data-review-inbox] .ri-filter select{appearance:none;-webkit-appearance:none;width:100%;height:100%;border:0;outline:none;background:transparent;padding:0 38px 0 42px;font-weight:600;font-size:14.5px;cursor:pointer}
[data-review-inbox] .ri-filter select option{background:var(--surface);color:var(--ink)}
[data-review-inbox] .ri-filter .chev{position:absolute;left:auto;right:14px;color:var(--muted);pointer-events:none}
[data-review-inbox] .ri-filter.on{border-color:var(--brand-text)}
[data-review-inbox] .ri-search:focus-within{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-review-inbox] .ri-search input{flex:1;min-width:0;border:0;outline:none;background:transparent;font-size:15px}
[data-review-inbox] .ri-search input::placeholder{color:var(--faint)}
[data-review-inbox] .ri-grid{display:grid;gap:14px;align-items:center;padding:14px 22px;position:relative}
[data-review-inbox] .ri-th{font-size:12px;font-weight:600;letter-spacing:.04em;color:var(--muted);background:var(--surface-2);border-bottom:1px solid var(--line);padding-block:10px}
[data-review-inbox] .ri-th span{display:flex;align-items:center;gap:6px}
[data-review-inbox] .ri-th span:last-child{justify-content:flex-end}
[data-review-inbox] .ri-row{border-bottom:1px solid var(--line);transition:background .15s,box-shadow .15s;cursor:pointer}
[data-review-inbox] .ri-row:last-child{border-bottom:0}
[data-review-inbox] .ri-row:hover{background:var(--hover-tint);box-shadow:inset 0 0 0 1px var(--hover-line)}
[data-review-inbox] .ri-row:hover .ri-title{color:var(--hover-ink)}
[data-review-inbox] .ri-row:hover .ri-av{background:var(--brand-solid);color:var(--on-brand)}
[data-review-inbox] .ri-row::before{content:"";position:absolute;left:0;top:10px;bottom:10px;width:3px;border-radius:0 3px 3px 0;background:var(--stripe,transparent)}
[data-review-inbox] .ri-title{font:600 16.5px/1.3 "Literata",Georgia,serif}
[data-review-inbox] .ri-quick{border-color:color-mix(in srgb,var(--gold) 45%,var(--line))}
[data-review-inbox] .ri-quick .ri-grid{border-bottom:1px solid var(--line)}
[data-review-inbox] .ri-quick .ri-grid:last-child{border-bottom:0}
[data-review-inbox] .ri-qr{background:color-mix(in srgb,var(--gold) 16%,transparent);color:var(--gold)}
[data-review-inbox] .ri-sub{font-size:12.5px;color:var(--muted);margin-top:3px}
[data-review-inbox] .ri-note{margin-top:5px;font-size:13px;font-style:italic;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:50ch}
[data-review-inbox] .ri-client{display:flex;align-items:center;gap:10px;min-width:0}
[data-review-inbox] .ri-av{width:34px;height:34px;flex:none;border-radius:50%;display:grid;place-items:center;font-size:12px;font-weight:700;background:var(--teal-soft);color:var(--teal-ink)}
[data-review-inbox] .ri-pill{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:700;padding:3px 10px;border-radius:999px;white-space:nowrap}
[data-review-inbox] .ri-pill i{width:6px;height:6px;border-radius:50%;background:currentColor}
[data-review-inbox] .ri-edited{background:rgba(242,195,94,.14);color:var(--gold);border:1px solid rgba(242,195,94,.4)}
[data-review-inbox] .ri-mono{font-family:"JetBrains Mono",monospace;font-size:12.5px}
[data-review-inbox] .ri-wait{font-size:13.5px;font-weight:600}
[data-review-inbox] .ri-wait.late{color:var(--gold)}
[data-review-inbox] .ri-empty{padding:52px 20px;text-align:center;color:var(--muted)}
[data-review-inbox] .ri-f .ic svg{transition:transform .35s cubic-bezier(.34,1.56,.64,1)}
[data-review-inbox] .ri-f:hover .ic.k-all svg{animation:riDrop .6s ease}
[data-review-inbox] .ri-f .hand,[data-review-inbox] .ri-f .cross{transform-box:view-box;transform-origin:12px 12px;transition:transform .6s cubic-bezier(.34,1.56,.64,1)}
[data-review-inbox] .ri-f:hover .hand{transform:rotate(360deg)}
[data-review-inbox] .ri-f:hover .cross{transform:rotate(90deg)}
[data-review-inbox] .ri-f .draw{stroke-dasharray:14;stroke-dashoffset:0}
[data-review-inbox] .ri-f:hover .draw{animation:riDraw .55s ease}
[data-review-inbox] .ri-f:hover .ic.k-returned svg{animation:riSwing .6s ease}
[data-review-inbox] .ri-cta{position:relative;overflow:hidden}
[data-review-inbox] .ri-cta::after{content:"";position:absolute;top:0;bottom:0;left:0;width:40%;pointer-events:none;background:linear-gradient(90deg,transparent,rgba(255,255,255,.45),transparent);transform:translateX(-130%) skewX(-20deg)}
[data-review-inbox] .ri-cta:hover::after{animation:riShine .8s ease}
[data-review-inbox] .ri-cta:hover svg{animation:riTwinkle 1s ease-in-out infinite}
[data-review-inbox] .ri-row:hover .ri-btn.primary svg{animation:riBlink 1.4s ease infinite}
[data-review-inbox] .ri-row .ri-btn:not(.primary) svg{transition:transform .3s cubic-bezier(.34,1.56,.64,1)}
[data-review-inbox] .ri-row:hover .ri-btn:not(.primary) svg{transform:translateY(-2px) rotate(-8deg)}
@keyframes riDrop{0%,100%{transform:translateY(0)}40%{transform:translateY(3px)}70%{transform:translateY(-1px)}}
@keyframes riDraw{from{stroke-dashoffset:14}to{stroke-dashoffset:0}}
@keyframes riSwing{0%,100%{transform:translateX(0) rotate(0)}40%{transform:translateX(-4px) rotate(-10deg)}}
@keyframes riShine{to{transform:translateX(360%) skewX(-20deg)}}
@keyframes riTwinkle{0%,100%{transform:scale(1) rotate(0)}50%{transform:scale(1.2) rotate(20deg)}}
@keyframes riBlink{0%,42%,52%,100%{transform:scaleY(1)}47%{transform:scaleY(.1)}}
@media (prefers-reduced-motion:reduce){[data-review-inbox] *,[data-review-inbox] *::after{transition:none!important;animation:none!important}}
[data-review-inbox] .ri-empty b{display:block;font:600 19px "Literata",Georgia,serif;color:var(--ink);margin-bottom:6px}`;

// Status and priority, in the palette's own colours (each readable on its tint).
const STATUS_TONE = {
    "Pending Review": "var(--gold)", "Under Review": "var(--teal-ink)", "Approved": "var(--brand-text)",
    "Returned": "var(--teal-ink)", "Rejected": "var(--danger)", "Final": "var(--teal-ink)",
};
const PRIORITY_TONE = { Urgent: "var(--danger)", Priority: "var(--gold)", Normal: "var(--muted)" };
const PRIORITY_RANK = { Urgent: 0, Priority: 1, Normal: 2 };
const tint = colour => ({ color: colour, background: `color-mix(in srgb, ${colour} 14%, transparent)` });

/* How long ago, in a lawyer's words: "2 h", "3 days". */
export function sinceWords(iso, now = Date.now()) {
    const at = iso ? new Date(iso).getTime() : NaN;
    if (Number.isNaN(at)) return null;
    const mins = Math.max(0, Math.round((now - at) / 60000));
    if (mins < 60) return mins < 2 ? "just now" : `${mins} min`;
    const hours = Math.round(mins / 60);
    if (hours < 24) return `${hours} h`;
    const days = Math.round(hours / 24);
    return `${days} day${days === 1 ? "" : "s"}`;
}

/* The order a reviewer works in: what still needs a decision first; among it
 * the urgent, then the priority, and the longest-waiting first. Decided rows
 * keep the server's order (most recent first). Only the loaded rows are
 * ordered -- the screen says so when more are still to load. */
export function workOrder(rows) {
    const pending = d => d.status === "Pending Review";
    const time = d => (d.submittedAt ? new Date(d.submittedAt).getTime() : Infinity) || Infinity;
    return rows.map((d, i) => [d, i]).sort(([a, ia], [b, ib]) => {
        if (pending(a) !== pending(b)) return pending(a) ? -1 : 1;
        if (!pending(a)) return ia - ib;
        return (PRIORITY_RANK[a.urgency] ?? 2) - (PRIORITY_RANK[b.urgency] ?? 2) || time(a) - time(b) || ia - ib;
    }).map(([d]) => d);
}

const FILTER_CARDS = [
    // Each icon's moving part carries a class the hover animates (INBOX_CSS).
    ["All", "Everything sent to you", "var(--teal-ink)", <><path d="M4 13h4l2 3h4l2-3h4" /><path d="M5.5 5h13L21 13v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5z" /></>, "k-all"],
    ["Pending Review", "Awaiting your decision", "var(--gold)", <><circle cx="12" cy="12" r="8.5" /><path className="hand" d="M12 7.5V12l3 2" /></>, "k-pending"],
    ["Approved", "Approved by you", "var(--brand-text)", <><circle cx="12" cy="12" r="8.5" /><path className="draw" d="m8.5 12.2 2.4 2.4 4.6-5" /></>, "k-approved"],
    ["Returned", "Sent back with changes", "var(--teal-ink)", <><path d="M9 14 4 9l5-5" /><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" /></>, "k-returned"],
    ["Rejected", "Declined by you", "var(--danger)", <><circle cx="12" cy="12" r="8.5" /><path className="cross" d="m9.2 9.2 5.6 5.6M14.8 9.2l-5.6 5.6" /></>, "k-rejected"],
];
const cardIcon = d => <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>;
const LATE_DAYS = 2;
// The filter beside the search: narrows the loaded rows of the chosen tab.
const ROW_FILTERS = {
    all: { label: "All priorities", test: () => true },
    urgent: { label: "Urgent only", test: d => d.urgency === "Urgent" },
    priority: { label: "Priority only", test: d => d.urgency === "Priority" },
    normal: { label: "Normal only", test: d => d.urgency === "Normal" },
    edited: { label: "Wording edited", test: d => Boolean(d.textEdited) },
};
// What an empty tab says: about THAT tab, not the inbox in general.
const EMPTY = {
    "All": ["Nothing here yet", "Documents your clients send you for review appear here."],
    "Pending Review": ["You're all caught up", "No document is waiting for your decision."],
    "Approved": ["Nothing approved yet", "Documents you approve are listed here, with the version you approved."],
    "Returned": ["Nothing returned", "Documents you send back to a client with changes are listed here."],
    "Rejected": ["Nothing rejected", "Documents you decline are listed here."],
};

const _rupees = n => (n == null ? "—" : `Rs ${Number(n).toLocaleString("en-PK")}`);
const _hoursLeft = iso => Math.max(0, Math.ceil((new Date(iso).getTime() - Date.now()) / 3600000));

/* QUICK REVIEW REQUESTS (2026-10-11): clients who have not hired this lawyer,
 * asking for one document to be checked. Only the title, the client and their
 * note are shown -- the document opens once the lawyer accepts, and then it is
 * an ordinary Pending Review row. */
function QuickRequests({ items, busyId, onAccept, onDecline }) {
    if (!items?.length) return null;
    return (
        <section className="ri-card ri-quick" data-quick-requests aria-label="New review requests">
            <div className="ri-bar">
                <div>
                    <h2>New review requests <span className="ri-mono" style={{ color: "var(--muted)", fontSize: 14 }}>· {items.length}</span></h2>
                    <small>Clients who haven't hired you, asking for one document to be checked. You see the document once you accept.</small>
                </div>
            </div>
            {items.map(r => {
                const initials = (r.client_name || "?").split(/\s+/).filter(Boolean).map(w => w[0]).join("").slice(0, 2).toUpperCase();
                const left = _hoursLeft(r.expires_at);
                return (
                    <div key={r.id} className="ri-grid" data-quick-request={r.id} style={{ gridTemplateColumns: "minmax(0,2.2fr) minmax(0,1.3fr) 170px 250px" }}>
                        <div style={{ minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                                <span className="ri-title">{r.doc_title}</span>
                                <span className="ri-pill ri-qr">Quick review</span>
                            </div>
                            <div className="ri-sub">{_TMPL_MAP[r.template_type] || r.template_type || "Document"} · v{r.version}</div>
                            {r.note && <div className="ri-note" title={r.note}>“{r.note}”</div>}
                        </div>
                        <div className="ri-client">
                            <span className="ri-av" aria-hidden="true">{initials}</span>
                            <span style={{ minWidth: 0 }}>
                                <span style={{ display: "block", fontWeight: 600, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.client_name}</span>
                                <span className={`ri-wait${left <= 3 ? " late" : ""}`} style={{ display: "block" }}>Accept within {left}h</span>
                            </span>
                        </div>
                        <div>
                            <div style={{ fontWeight: 700 }}>{_rupees(r.fee_pkr)}</div>
                            <div className="ri-sub">Due {r.turnaround_hours}h after accepting</div>
                        </div>
                        <span style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                            <button type="button" className="ri-btn" style={{ height: 36 }} disabled={busyId === r.id}
                                data-quick-decline onClick={() => onDecline(r)}>Decline</button>
                            <button type="button" className="ri-btn primary" style={{ height: 36 }} disabled={busyId === r.id}
                                data-quick-accept onClick={() => onAccept(r)}>
                                <Icon d={I.eye} size={15} />{busyId === r.id ? "Opening…" : "Accept & open"}</button>
                        </span>
                    </div>
                );
            })}
        </section>
    );
}

function ScreenInbox({
    t, onOpen, docs, loading, hasMore, loadingMore, onLoadMore,
    statusF, onStatusChange, counts, serverFiltered,
    quick = null, quickBusy = null, onAcceptQuick, onDeclineQuick,
}) {
    const [search, setSearch] = useState("");
    const [filter, setFilter] = useState("all");
    const searchRef = useRef(null);
    const { setPage } = useCase();
    const q = search.trim().toLowerCase();
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

    // The status filter is applied BY THE SERVER when V2 is live: `docs` already
    // contains only the selected tab, and re-filtering here would be a no-op at
    // best and would hide rows at worst. The legacy queue has no status
    // parameter — it returns everything, unpaginated — so with the flag off the
    // filtering has to happen here, and `serverFiltered` says which world we are
    // in rather than leaving it to be guessed from the data.
    const filtered = workOrder(docs.filter(d =>
        (serverFiltered || statusF === "All" || d.status === statusF) &&
        (!q || d.title.toLowerCase().includes(q) || d.client.toLowerCase().includes(q) || d.caseId.toLowerCase().includes(q)) &&
        (ROW_FILTERS[filter] || ROW_FILTERS.all).test(d)));
    const showStatus = statusF === "All";
    const columns = `minmax(0,2.4fr) minmax(0,1.4fr) minmax(0,.95fr) 64px 100px${showStatus ? " 136px" : ""} 140px`;
    const heading = statusF === "All" ? "All documents" : statusF;
    const count = _tabCount(counts, statusF, docs, serverFiltered);

    return (
        <div data-review-inbox data-drafting-theme data-mode={draftingMode(t)}>
            <style>{`${DRAFTING_TOKENS_CSS}\n${INBOX_CSS}`}</style>
            <div className="ri-wrap">
                <nav className="ri-crumbs" aria-label="Breadcrumb">Documents <span aria-hidden="true">/</span> <b>Document review</b></nav>

                <div className="ri-head">
                    <div>
                        <h1>Document <span className="ri-accent">review</span></h1>
                        <p>Documents your clients sent you. Each is frozen at the version they sent — your decision binds to that exact version.</p>
                    </div>
                    {/* AI Generate opens the Draft Generator, where a lawyer's own
                        AI drafting lives; a review inbox has no upload. */}
                    <button type="button" className="ri-cta" onClick={() => setPage?.("doc-automation")}>
                        <Icon d={I.sparkles} size={18} /> AI Generate
                    </button>
                </div>

                <QuickRequests items={quick} busyId={quickBusy} onAccept={onAcceptQuick} onDecline={onDeclineQuick} />

                {/* THE FILTERS ARE THE COUNTS: one control, each number shown once.
                    Values go through _tabCount, like everything else here: `counts`
                    is null until the first page answers (and always on the legacy
                    queue), and its keys are server statuses, not these labels. */}
                <div className="ri-filters" role="tablist" aria-label="Review status">
                    {FILTER_CARDS.map(([tab, sub, colour, icon, motion]) => (
                        <button key={tab} type="button" role="tab" className="ri-f" aria-selected={statusF === tab}
                            onClick={() => onStatusChange(tab)} style={{ "--c": colour }}
                            {...(tab === "All" ? { "data-inbox-all": "" } : { "data-inbox-stat": tab })}>
                            <span className={`ic ${motion}`}>{cardIcon(icon)}</span>
                            <span className="tick" aria-hidden="true"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5" /></svg></span>
                            <span className="l">{tab === "All" ? "All documents" : tab}</span>
                            <span className="v" data-stat-value={tab === "All" ? undefined : ""}>{_tabCount(counts, tab, docs, serverFiltered)}</span>
                            <span className="s">{sub}</span>
                        </button>
                    ))}
                </div>

                <div className="ri-tools">
                    <label className="ri-search">
                        <Icon d={I.search} size={18} />
                        <span style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>Search documents</span>
                        <input ref={searchRef} type="search" value={search} onChange={e => setSearch(e.target.value)}
                            placeholder="Search by document, client or case" />
                        <span className="ri-kbd" aria-hidden="true">/</span>
                    </label>
                    <label className={`ri-filter${filter !== "all" ? " on" : ""}`}>
                        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" aria-hidden="true"><path d="M4 6h16M7 12h10M10 18h4" /></svg>
                        <span style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>Filter documents</span>
                        <select value={filter} onChange={e => setFilter(e.target.value)} data-inbox-filter>
                            {Object.entries(ROW_FILTERS).map(([k, f]) => <option key={k} value={k}>{f.label}</option>)}
                        </select>
                        <svg className="chev" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
                    </label>
                </div>

                <section className="ri-card" aria-label={heading}>
                    <div className="ri-bar">
                        <div>
                            <h2>{heading} <span className="ri-mono" style={{ color: "var(--muted)", fontSize: 14 }}>· {count}</span></h2>
                            <small>
                                {statusF === "Pending Review" || statusF === "All"
                                    ? `Most urgent first, then the longest waiting${hasMore ? " (among the documents loaded)" : ""}.`
                                    : "Most recent decision first."}
                            </small>
                        </div>
                        {(q || filter !== "all") && (
                            <button type="button" className="ri-btn" style={{ height: 36 }} onClick={() => { setSearch(""); setFilter("all"); }}>
                                Clear search and filter
                            </button>
                        )}
                    </div>

                    <div>
                        {filtered.length > 0 && (
                            <div className="ri-grid ri-th" style={{ gridTemplateColumns: columns }}>
                                <span>Document</span><span>Client · Case</span><span>{statusF === "Pending Review" ? "Waiting" : "When"}</span>
                                <span>Version</span><span>Priority</span>{showStatus && <span>Status</span>}<span>Action</span>
                            </div>
                        )}
                        {filtered.map(doc => {
                            const pending = doc.status === "Pending Review";
                            const waited = pending ? sinceWords(doc.submittedAt) : null;
                            const late = pending && doc.submittedAt && (Date.now() - new Date(doc.submittedAt).getTime()) > LATE_DAYS * 86400000;
                            const decided = !pending && doc.reviewedAt ? sinceWords(doc.reviewedAt) : null;
                            const initials = (doc.client || "?").split(/\s+/).filter(Boolean).map(w => w[0]).join("").slice(0, 2).toUpperCase();
                            return (
                                <div key={doc.id} className="ri-grid ri-row" data-inbox-row={doc.id} onClick={() => onOpen(doc)}
                                    style={{ gridTemplateColumns: columns, "--stripe": pending ? (PRIORITY_TONE[doc.urgency] === "var(--muted)" ? "transparent" : PRIORITY_TONE[doc.urgency]) : "transparent" }}>
                                    <div style={{ minWidth: 0 }}>
                                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                                            <span className="ri-title">{doc.title}</span>
                                            {doc.quickReview && <span data-quick-row className="ri-pill ri-qr" title="A one-off review: this client has not hired you">Quick review</span>}
                                            {doc.textEdited && <span data-wording-edited className="ri-pill ri-edited" title="The client edited this document's wording">
                                                <Icon d={I.edit} size={12} />Wording edited</span>}
                                        </div>
                                        <div className="ri-sub">{doc.type}</div>
                                        {/* The client's note to the lawyer, as they wrote it. */}
                                        {doc.note && <div className="ri-note" data-client-note title={doc.note}>“{doc.note}”</div>}
                                    </div>
                                    <div className="ri-client">
                                        <span className="ri-av" aria-hidden="true">{initials}</span>
                                        <span style={{ minWidth: 0 }}>
                                            <span style={{ display: "block", fontWeight: 600, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{doc.client}</span>
                                            <span className="ri-sub" style={{ display: "block" }}>{doc.caseId && doc.caseId !== "—" ? <span className="ri-mono">{doc.caseId}</span> : doc.quickReview ? "Review only · no case" : "No case linked"}</span>
                                        </span>
                                    </div>
                                    <div>
                                        {pending
                                            ? <span className={`ri-wait${late ? " late" : ""}`} title={doc.submitted ? `Sent ${doc.submitted}` : undefined}>{waited ? (waited === "just now" ? "Sent just now" : `Waiting ${waited}`) : "—"}</span>
                                            : <span className="ri-wait" title={doc.submitted ? `Sent ${doc.submitted}` : undefined}>{decided ? `Decided ${decided === "just now" ? "just now" : `${decided} ago`}` : (doc.submitted || "—")}</span>}
                                        {pending && <div className="ri-sub">{doc.submitted ? `since ${doc.submitted}` : ""}</div>}
                                    </div>
                                    <span className="ri-mono">{doc.submittedVersion ? `v${doc.submittedVersion}` : "—"}</span>
                                    <span><span className="ri-pill" style={tint(PRIORITY_TONE[doc.urgency] || PRIORITY_TONE.Normal)}><i />{doc.urgency}</span></span>
                                    {showStatus && <span><span className="ri-pill" style={tint(STATUS_TONE[doc.status] || STATUS_TONE["Under Review"])}><i />{doc.status}</span></span>}
                                    <span style={{ textAlign: "right" }}>
                                        <button type="button" className={`ri-btn${pending ? " primary" : ""}`} style={{ height: 36 }}
                                            onClick={e => { e.stopPropagation(); onOpen(doc); }}>
                                            <Icon d={pending ? I.eye : I.folder} size={15} />{pending ? "Review Now" : "Open"}
                                        </button>
                                    </span>
                                </div>
                            );
                        })}
                    </div>

                    {/* MORE OF THE INBOX. Follows the cursor, not "did this page
                        return rows". A button rather than infinite scroll: this is a
                        work queue, and a lawyer deciding when to take on more is the
                        correct interaction. */}
                    {!loading && hasMore && (
                        <div style={{ display: "flex", justifyContent: "center", padding: "14px 0", borderTop: "1px solid var(--line)" }}>
                            <button type="button" className="ri-btn" onClick={onLoadMore} disabled={loadingMore}>
                                {loadingMore ? "Loading…" : "Load more"}
                            </button>
                        </div>
                    )}

                    {loading ? (
                        <div className="ri-empty" aria-busy="true">Loading documents…</div>
                    ) : !filtered.length && (
                        <div className="ri-empty">
                            <b>{docs.length ? "No document matches" : (EMPTY[statusF] || EMPTY.All)[0]}</b>
                            {docs.length ? `Nothing matches${q ? ` “${search}”` : ""}${filter !== "all" ? ` with “${ROW_FILTERS[filter].label}”` : ""}.` : (EMPTY[statusF] || EMPTY.All)[1]}
                        </div>
                    )}
                </section>
            </div>
        </div>
    );
}

// ═══════════════════════════════════════════════════════════════
// SCREEN 2 — REVIEW & VALIDATE
// Lawyer reads the full document, runs compliance checks
// Mirrors client Screen 2 (Review & Edit) — but lawyer perspective
// ═══════════════════════════════════════════════════════════════
/* The revision-bound PDF download, with its failure said out loud.
   downloadDocumentFile resolves with { error: <string> } instead of throwing,
   and both screens ignored it: a failed download did nothing at all. */
/* THE REVIEW WORKSPACE (2026-10-11), in the drafting theme the inbox uses.
 *
 * Review and decision are ONE screen now. The decision used to be a second
 * step that took the document off the screen, so a lawyer chose Approve,
 * Return or Reject without the text in front of them. The document stays
 * on the left; the decision lives at the foot of the right-hand column.
 * Scoped by [data-review-ws]; the tokens are DRAFTING_TOKENS_CSS. */
const REVIEW_CSS = `[data-review-ws]{flex:1;min-height:0;overflow-y:auto;background:radial-gradient(900px 360px at 25% -80px,var(--glow),transparent 70%) no-repeat,var(--bg);color:var(--ink);font:15px/1.5 "Hanken Grotesk",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
[data-review-ws] *{box-sizing:border-box}
[data-review-ws] button,[data-review-ws] textarea{font:inherit;color:inherit}
[data-review-ws] :focus-visible{outline:2px solid var(--focus);outline-offset:2px}
[data-review-ws] .rw-wrap{max-width:1440px;margin:0 auto;padding:20px clamp(16px,2.6vw,32px) 36px;display:flex;flex-direction:column;gap:16px}
[data-review-ws] .rw-crumbs{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--muted)}
[data-review-ws] .rw-back{width:42px;height:42px;flex:none;margin-top:2px;display:grid;place-items:center;border-radius:50%;border:1px solid var(--line-strong);background:var(--surface);color:var(--ink);cursor:pointer;transition:background .2s,border-color .2s,color .2s,transform .12s}
[data-review-ws] .rw-back svg{transition:transform .2s}
[data-review-ws] .rw-back:hover{background:var(--brand-solid);border-color:transparent;color:var(--on-brand)}
[data-review-ws] .rw-back:hover svg{transform:translateX(-3px)}
[data-review-ws] .rw-back:active{transform:scale(.93)}
[data-review-ws] .rw-pop{position:absolute;top:calc(100% + 8px);right:0;z-index:60;width:min(380px,90vw);max-height:70vh;overflow-y:auto;padding:14px 16px;border-radius:16px;border:1px solid var(--line-strong);background:var(--surface);box-shadow:0 24px 48px -18px rgba(0,0,0,.8);text-align:left}
[data-review-ws] .rw-crumbs button{border:0;background:none;padding:0;color:var(--muted);cursor:pointer}
[data-review-ws] .rw-crumbs button:hover{color:var(--hover-ink)}
[data-review-ws] .rw-crumbs b{color:var(--ink);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:40ch}
[data-review-ws] .rw-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}
[data-review-ws] .rw-head > :first-child{flex:1 1 auto}
[data-review-ws] .rw-head-right{display:flex;align-items:flex-start;gap:10px;flex:none;padding-top:4px}
[data-review-ws] .rw-btn.rw-icon-btn{width:40px;padding:0}
[data-review-ws] .rw-btn.rw-dl{border:0;background:var(--brand-solid);color:var(--on-brand);box-shadow:0 8px 18px -10px rgba(46,196,214,.8)}
[data-review-ws] .rw-btn.rw-dl:hover:not(:disabled){background:var(--brand-solid-hover);color:var(--on-brand);transform:translateY(-1px)}
[data-review-ws] .rw-btn.rw-dl:hover svg{animation:rw-drop .6s ease}
@keyframes rw-drop{0%,100%{transform:none}45%{transform:translateY(3px)}}
[data-review-ws] .rw-btn.rw-next{gap:0;padding:0 10px 0 12px;transition:background .2s,border-color .2s,color .2s,padding .25s}
[data-review-ws] .rw-next-label{max-width:0;overflow:hidden;opacity:0;white-space:nowrap;transition:max-width .3s ease,opacity .2s,margin .3s}
[data-review-ws] .rw-next-count{min-width:20px;height:20px;padding:0 6px;display:grid;place-items:center;border-radius:999px;background:color-mix(in srgb,var(--gold) 22%,transparent);color:var(--gold);font-size:12px;font-weight:700}
[data-review-ws] .rw-next-arrow{display:grid;place-items:center;margin-left:8px}
[data-review-ws] .rw-prev .rw-next-arrow{margin:0 0 0 -2px}
[data-review-ws] .rw-prev:hover .rw-next-label,[data-review-ws] .rw-prev:focus-visible .rw-next-label{margin:0 0 0 10px}
[data-review-ws] .rw-prev:hover .rw-next-arrow{animation-name:rw-nudge-back}
@keyframes rw-nudge-back{0%,100%{transform:translateX(0)}50%{transform:translateX(-4px)}}
[data-review-ws] .rw-btn.rw-next:hover:not(:disabled),[data-review-ws] .rw-btn.rw-next:focus-visible{padding:0 14px 0 16px;border-color:transparent;background:var(--brand-solid);color:var(--on-brand)}
[data-review-ws] .rw-next:hover .rw-next-label,[data-review-ws] .rw-next:focus-visible .rw-next-label{max-width:140px;opacity:1;margin-right:10px}
[data-review-ws] .rw-next:hover .rw-next-count,[data-review-ws] .rw-next:focus-visible .rw-next-count{background:rgba(4,33,42,.18);color:var(--on-brand)}
[data-review-ws] .rw-next:hover .rw-next-arrow{animation:rw-nudge .9s ease-in-out infinite}
@keyframes rw-nudge{0%,100%{transform:translateX(0)}50%{transform:translateX(4px)}}
@media (prefers-reduced-motion:reduce){[data-review-ws] .rw-next-arrow,[data-review-ws] .rw-dl svg{animation:none!important}}
[data-review-ws] .rw-icon-btn svg{flex:none}
[data-review-ws] .rw-icon-btn:disabled{opacity:.55;cursor:default}
[data-review-ws] .rw-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
[data-review-ws] .rw-head h1{margin:6px 0 0;font:600 clamp(22px,2.4vw,28px)/1.15 "Literata",Georgia,serif;letter-spacing:-.01em}
[data-review-ws] .rw-meta{display:flex;flex-wrap:nowrap;align-items:center;gap:6px 9px;margin-top:8px;font-size:13.5px;color:var(--muted);white-space:nowrap;min-width:0}
[data-review-ws] .rw-meta > span:not(.rw-pill){overflow:hidden;text-overflow:ellipsis;min-width:0}
[data-review-ws] .rw-head > :first-child, [data-review-ws] .rw-head > :first-child > div{min-width:0}
[data-review-ws] .rw-pill{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:700;padding:3px 10px;border-radius:999px;white-space:nowrap}
[data-review-ws] .rw-pill i{width:6px;height:6px;border-radius:50%;background:currentColor}
[data-review-ws] .rw-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;height:40px;padding:0 16px;border-radius:10px;border:1px solid var(--line-strong);background:var(--surface);font-weight:600;font-size:14px;white-space:nowrap;cursor:pointer;transition:border-color .15s,background .15s,color .15s}
[data-review-ws] .rw-btn:hover:not(:disabled){border-color:var(--hover-line);background:var(--hover-tint);color:var(--hover-ink)}
[data-review-ws] .rw-btn:disabled{opacity:.55;cursor:default}
[data-review-ws] .rw-cta{display:inline-flex;align-items:center;justify-content:center;gap:10px;height:48px;padding:0 22px;border-radius:14px;border:0;background:var(--brand-solid);color:var(--on-brand);font-weight:700;font-size:15px;cursor:pointer;box-shadow:0 10px 24px -12px rgba(46,196,214,.8);transition:transform .15s,box-shadow .15s}
[data-review-ws] .rw-cta:hover:not(:disabled){background:var(--brand-solid-hover);transform:translateY(-1px)}
[data-review-ws] .rw-cta:disabled{opacity:.55;cursor:default;transform:none}
[data-review-ws] .rw-cta.gold{background:var(--gold);color:#2a1d00;box-shadow:0 10px 24px -12px rgba(242,195,94,.7)}
[data-review-ws] .rw-cta.danger{background:var(--danger);color:#2a0c08;box-shadow:none}
[data-review-ws] .rw-grid{display:grid;grid-template-columns:minmax(0,1fr) 400px;gap:18px;align-items:start}
@media (max-width:1100px){[data-review-ws] .rw-grid{grid-template-columns:1fr}}
[data-review-ws] .rw-card{border-radius:16px;border:1px solid var(--line);background:var(--surface);box-shadow:var(--shadow-rest)}
[data-review-ws] .rw-doc{overflow:hidden}
[data-review-ws] .rw-doc-bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:10px 16px;border-bottom:1px solid var(--line);font-size:13px;color:var(--muted)}
[data-review-ws] .rw-mono{font-family:"JetBrains Mono",monospace;font-size:12.5px}
[data-review-ws] .rw-side{display:flex;flex-direction:column;gap:14px}
[data-review-ws] .rw-sec{padding:14px 16px}
[data-review-ws] .rw-h{margin:0;font:600 16.5px/1.25 "Literata",Georgia,serif}
[data-review-ws] .rw-kv{display:flex;justify-content:space-between;gap:12px;padding:8px 0;font-size:13.5px;border-top:1px solid var(--line)}
[data-review-ws] .rw-kv span{color:var(--muted)}
[data-review-ws] .rw-kv b{font-weight:600;text-align:right}
[data-review-ws] .rw-asked{border-color:color-mix(in srgb,var(--gold) 38%,transparent);background:linear-gradient(180deg,color-mix(in srgb,var(--gold) 9%,var(--surface)),var(--surface))}
[data-review-ws] .rw-asked small{display:block;font-size:11.5px;font-weight:700;letter-spacing:.06em;color:var(--gold)}
[data-review-ws] .rw-asked p{margin:6px 0 0;font-size:13.5px;font-style:italic;color:var(--ink);line-height:1.55}
[data-review-ws] .rw-flag{border-color:color-mix(in srgb,var(--gold) 45%,transparent)}
[data-review-ws] .rw-flag b{display:block;font-size:13.5px;margin-bottom:4px}
[data-review-ws] .rw-flag p{margin:0;font-size:12.5px;color:var(--muted);line-height:1.55}
[data-review-ws] details{border-top:1px solid var(--line);padding:9px 0}
[data-review-ws] details summary{display:flex;align-items:center;justify-content:space-between;gap:10px;list-style:none;cursor:pointer;font-size:13.5px}
[data-review-ws] details summary::-webkit-details-marker{display:none}
[data-review-ws] details summary span:first-child{color:var(--muted)}
[data-review-ws] details[open] summary{margin-bottom:8px}
[data-review-ws] .rw-detail{font-size:12.5px;color:var(--muted);line-height:1.55}
[data-review-ws] .rw-detail .item{margin:0 0 8px;padding-left:9px;border-left:2px solid var(--line-strong)}
[data-review-ws] .rw-detail .item.bad{border-left-color:color-mix(in srgb,var(--danger) 55%,transparent)}
[data-review-ws] .rw-detail .item.warn{border-left-color:color-mix(in srgb,var(--gold) 55%,transparent)}
[data-review-ws] .rw-detail .item b{display:block;color:var(--ink);font-weight:600}
[data-review-ws] .rw-opts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:12px}
[data-review-ws] .rw-opt{display:flex;flex-direction:column;align-items:flex-start;gap:7px;padding:12px;border-radius:14px;text-align:left;cursor:pointer;border:1px solid color-mix(in srgb,var(--c) 18%,var(--line));background:radial-gradient(120% 90% at 100% 0%,color-mix(in srgb,var(--c) 13%,transparent) 0%,transparent 55%),linear-gradient(180deg,color-mix(in srgb,var(--surface) 92%,#fff 8%),var(--surface));transition:transform .18s,border-color .18s,box-shadow .18s}
[data-review-ws] .rw-opt:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--c) 45%,var(--line))}
[data-review-ws] .rw-opt[aria-pressed="true"]{border-color:color-mix(in srgb,var(--c) 75%,transparent);box-shadow:0 0 0 3px color-mix(in srgb,var(--c) 18%,transparent)}
[data-review-ws] .rw-opt .ic{width:32px;height:32px;border-radius:10px;display:grid;place-items:center;color:var(--c);background:color-mix(in srgb,var(--c) 16%,transparent)}
[data-review-ws] .rw-opt[aria-pressed="true"] .ic{background:var(--c);color:var(--surface-2)}
[data-review-ws] .rw-opt b{font-size:13.5px}
[data-review-ws] .rw-opt small{font-size:11.5px;color:var(--muted);line-height:1.3}
[data-review-ws] .rw-form{display:flex;flex-direction:column;gap:12px;margin-top:14px}
[data-review-ws] .rw-form label{display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:600}
[data-review-ws] .rw-form label em{font-style:normal;font-weight:500;color:var(--faint)}
[data-review-ws] .rw-ta{width:100%;min-height:110px;resize:vertical;padding:11px 13px;border-radius:12px;border:1px solid var(--line-strong);background:var(--input);color:var(--ink);font-size:14px;font-weight:400;line-height:1.5;outline:none}
[data-review-ws] .rw-ta:focus{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-review-ws] .rw-info{display:flex;gap:10px;padding:10px 12px;border-radius:12px;font-size:12.5px;line-height:1.5;color:var(--muted);background:var(--brand-soft);border:1px solid color-mix(in srgb,var(--brand-text) 25%,transparent)}
[data-review-ws] .rw-done{padding:12px 14px;border-radius:12px;background:var(--surface-2);border:1px solid var(--line);font-size:13px;color:var(--muted)}
[data-review-ws] .rw-banner{display:flex;align-items:center;gap:14px;padding:14px 18px;border-color:color-mix(in srgb,var(--brand-text) 35%,transparent);background:linear-gradient(90deg,var(--brand-soft),var(--surface) 65%)}
[data-review-ws] .rw-banner .tick{width:40px;height:40px;flex:none;border-radius:50%;display:grid;place-items:center;background:var(--brand-solid);color:var(--on-brand)}
[data-review-ws] .rw-backdrop{position:fixed;inset:0;z-index:300;display:grid;place-items:center;padding:20px;background:rgba(6,16,19,.62)}
[data-review-ws] .rw-dialog{width:min(540px,100%);padding:24px;border-radius:20px;background:var(--surface);border:1px solid var(--line-strong);box-shadow:0 30px 60px -20px rgba(0,0,0,.85);display:flex;flex-direction:column;gap:16px}
[data-review-ws] .rw-reason{display:flex;align-items:center;gap:10px;width:100%;padding:11px 14px;border-radius:12px;border:1px solid var(--line-strong);background:var(--input);text-align:left;font-size:14px;cursor:pointer}
[data-review-ws] .rw-reason i{width:16px;height:16px;flex:none;border-radius:50%;border:1.5px solid var(--faint)}
[data-review-ws] .rw-reason[aria-checked="true"]{border-color:var(--danger);background:var(--danger-soft)}
[data-review-ws] .rw-reason[aria-checked="true"] i{border:5px solid var(--danger)}
@media (prefers-reduced-motion:reduce){[data-review-ws] *{transition:none!important}}`;

const RwIcon = ({ d, s = 18, w = 2 }) => (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={w}
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
);
const RW = {
    back: "M19 12H5M12 19l-7-7 7-7",
    // Lucide "arrow-down-to-line"
    download: "M12 17V3M6 11l6 6 6-6M19 21H5",
    check: "M5 12l4 4 10-10",
    ret: "M9 14L4 9l5-5M4 9h10.5a5.5 5.5 0 0 1 0 11H11",
    x: "M6 6l12 12M18 6L6 18",
    warn: "M12 3l10 18H2zM12 10v5M12 18h.01",
    info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 8v4M12 16h.01",
};

// The pill colour of each recorded status, in the theme's own tokens.
const RW_STATUS = {
    "Pending Review": "var(--gold)", "Approved": "var(--brand-text)", "Returned": "var(--gold)",
    "Rejected": "var(--danger)", "Final": "var(--teal-ink)", "Under Review": "var(--teal-ink)",
};
const RW_URGENCY = { Urgent: "var(--danger)", Priority: "var(--gold)", Normal: "var(--faint)" };
const rwTint = c => ({ color: c, background: `color-mix(in srgb, ${c} 14%, transparent)` });

function DownloadPdfButton({ doc, t, style, className }) {
    const [issue, setIssue] = useState(null);
    const [busy, setBusy] = useState(false);
    const download = async () => {
        setIssue(null);
        setBusy(true);
        const result = await downloadDocumentFile(doc.id, `${doc.title || "document"}.pdf`, {
            revisionId: doc.viewRevisionId,
            expectedPdfSha256: doc.viewPdfSha256,
        });
        setBusy(false);
        if (result?.error) setIssue(typeof result.error === "string" ? result.error : (result.error.message || "Download failed"));
    };
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
            <button type="button" className={`${className} rw-icon-btn rw-dl`} onClick={download} disabled={busy} style={style}
                title={busy ? "Downloading…" : "Download PDF"} aria-busy={busy}>
                <RwIcon d={RW.download} s={18} />
                <span className="rw-sr">{busy ? "Downloading…" : "Download PDF"}</span>
            </button>
            {issue && <div role="alert" style={{ fontSize: 12, color: "var(--danger)", maxWidth: 320 }}>{issue}</div>}
        </div>
    );
}

/* The document's case, as a way to it (2026-10-09): review used to be a dead
 * end with only a shortened reference. A standalone document says so plainly. */
function CaseLink({ doc, t }) {
    const { setPage, setOpenCaseId } = useCase();
    if (!doc.caseRawId) return <span data-case-link="none">No case — standalone document</span>;
    return (
        <button type="button" data-case-link={doc.caseRawId} title="Open this case" className="rw-mono"
            onClick={() => { setOpenCaseId?.(doc.caseRawId); setPage?.("cases"); }}
            style={{ background: "none", border: 0, padding: 0, cursor: "pointer", color: "var(--teal-ink)", textDecoration: "underline", textUnderlineOffset: 2 }}>
            Case {doc.caseId}
        </button>
    );
}

/* "Waiting 2 days", from the instant it was sent. */
function _waited(iso) {
    if (!iso) return "";
    const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
    return days <= 0 ? "sent today" : `waiting ${days} day${days === 1 ? "" : "s"}`;
}

/* The page header both screens share: breadcrumb back to the inbox, the
 * title, who and what it is, and where it stands. */
function ReviewHeader({ doc, t, onBack, right, extra }) {
    const statusColour = RW_STATUS[doc.status] || "var(--teal-ink)";
    return (
        <header className="rw-head">
            <div style={{ display: "flex", alignItems: "flex-start", gap: 14, minWidth: 0 }}>
                <button type="button" className="rw-back" onClick={onBack}
                    aria-label="Back to document review" title="Back to document review">
                    <RwIcon d={RW.back} s={18} w={2.2} />
                </button>
                <div style={{ minWidth: 0 }}>
                    <nav className="rw-crumbs" aria-label="Breadcrumb">
                        <span>Documents</span><span aria-hidden="true">/</span>
                        <button type="button" onClick={onBack}>Document review</button>
                    </nav>
                    <h1>{doc.title}</h1>
                    <div className="rw-meta">
                        <span>{doc.client}</span><span aria-hidden="true">·</span>
                        <span>{doc.type}{doc.textEdited ? " (wording edited by client)" : ""}</span><span aria-hidden="true">·</span>
                        <CaseLink doc={doc} t={t} />
                        {doc.submitted && <><span aria-hidden="true">·</span><span>Sent {doc.submitted}{doc.status === "Pending Review" && doc.submittedAt ? ` · ${_waited(doc.submittedAt)}` : ""}</span></>}
                        {doc.urgency && doc.urgency !== "Normal" && (
                            <span className="rw-pill" style={rwTint(RW_URGENCY[doc.urgency])}><i />{doc.urgency}</span>
                        )}
                        {extra}
                        <span className="rw-pill" style={rwTint(statusColour)}><i />{doc.status}</span>
                    </div>
                </div>
            </div>
            {right && <div className="rw-head-right">{right}</div>}
        </header>
    );
}

/* "Next document": the next one waiting in the queue, in the inbox's own
 * work order, so a lawyer can go through them without returning each time. */
/* "Previous document": back to the one the lawyer moved on from with Next. */
function PrevDocButton({ prev }) {
    if (!prev) return null;
    return (
        <button type="button" className="rw-btn rw-next rw-prev" onClick={prev.open}
            title={`Back to: ${prev.title}`} aria-label={`Previous document, ${prev.title}`}>
            <span className="rw-next-arrow"><RwIcon d="M19 12H5M12 19l-7-7 7-7" s={16} w={2.2} /></span>
            <span className="rw-next-label">Previous</span>
        </button>
    );
}

function NextDocButton({ next }) {
    if (!next) return null;
    return (
        <button type="button" className="rw-btn rw-next" onClick={next.open}
            title={`Next waiting: ${next.title}`} aria-label={`Next document, ${next.position}`}>
            <span className="rw-next-label">Next document</span>
            {next.count > 0 && <span className="rw-next-count">{next.count}</span>}
            <span className="rw-next-arrow"><RwIcon d="M5 12h14M12 5l7 7-7 7" s={16} w={2.2} /></span>
        </button>
    );
}

/* Reject: a reason is required and said to the client. Three common ones
 * to pick from; the choice and any note go out as the one note the server
 * already records. */
const REJECT_REASONS = [
    "This is not the right document for this matter.",
    "This is outside what I agreed to review.",
];

function RejectDialog({ busy, onCancel, onConfirm }) {
    const [reason, setReason] = useState(REJECT_REASONS[0]);
    const [other, setOther] = useState(false);
    const [note, setNote] = useState("");
    const text = (other ? note.trim() : [reason, note.trim()].filter(Boolean).join("\n\n"));
    useEffect(() => {
        const onKey = e => { if (e.key === "Escape") onCancel(); };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [onCancel]);
    return (
        <div className="rw-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onCancel(); }}>
            <section className="rw-dialog" role="dialog" aria-modal="true" aria-label="Reject this document">
                <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
                    <span style={{ width: 46, height: 46, flex: "none", borderRadius: 14, display: "grid", placeItems: "center", color: "var(--danger)", background: "var(--danger-soft)" }}>
                        <RwIcon d={RW.warn} s={22} w={2.2} />
                    </span>
                    <div>
                        <h2 className="rw-h" style={{ fontSize: 20 }}>Reject this document?</h2>
                        <p style={{ margin: "6px 0 0", fontSize: 14, color: "var(--muted)", lineHeight: 1.5 }}>
                            The client is told it was rejected and why. If it only needs changes, return it instead.
                        </p>
                    </div>
                </div>
                <div role="radiogroup" aria-label="Reason" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <span style={{ fontSize: 13, fontWeight: 600 }}>Reason <span style={{ color: "var(--danger)" }}>*</span></span>
                    {REJECT_REASONS.map(r => (
                        <button key={r} type="button" role="radio" className="rw-reason" aria-checked={!other && reason === r}
                            onClick={() => { setOther(false); setReason(r); }}><i />{r.replace(/\.$/, "")}</button>
                    ))}
                    <button type="button" role="radio" className="rw-reason" aria-checked={other}
                        onClick={() => setOther(true)}><i />Something else</button>
                </div>
                <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, fontWeight: 600 }}>
                    <span>{other ? <>Reason for the client <span style={{ color: "var(--danger)" }}>*</span></> : <>Note to the client <em style={{ fontStyle: "normal", fontWeight: 500, color: "var(--faint)" }}>(optional)</em></>}</span>
                    <textarea className="rw-ta" style={{ minHeight: 90 }} value={note} onChange={e => setNote(e.target.value)}
                        placeholder={other ? "Why it cannot go ahead" : "What they should do instead"} />
                </label>
                <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                    <button type="button" className="rw-btn" onClick={onCancel}>Cancel</button>
                    <button type="button" className="rw-cta danger" disabled={busy || !text} onClick={() => onConfirm(text)}>
                        {busy ? "Sending…" : "Reject document"}
                    </button>
                </div>
            </section>
        </div>
    );
}

/* The decision, at the foot of the review column. Approve, Return and Reject
 * call the same `onDecide` the old decision screen did. */
function DecisionPanel({ doc, busy, onDecide }) {
    const [decision, setDecision] = useState(null); // null | "approve" | "edit" | "reject"
    const [editNotes, setEditNotes] = useState("");
    const [returnNote, setReturnNote] = useState("");

    if (doc.status !== "Pending Review") {
        return (
            <section className="rw-card rw-sec" aria-label="Decision">
                <h2 className="rw-h">Decision recorded</h2>
                <div className="rw-done" style={{ marginTop: 10 }}>
                    <b style={{ color: "var(--ink)" }}>{doc.status}</b>
                    {doc.lawyerNote ? <div style={{ marginTop: 6, fontStyle: "italic" }}>“{doc.lawyerNote}”</div> : null}
                </div>
            </section>
        );
    }

    const options = [
        { id: "approve", c: "var(--brand-text)", d: RW.check, w: 2.4, label: "Approve", sub: "Legally sound" },
        { id: "edit", c: "var(--gold)", d: RW.ret, w: 2.2, label: "Return", sub: "Needs changes" },
        { id: "reject", c: "var(--danger)", d: RW.x, w: 2.4, label: "Reject", sub: "Cannot go ahead" },
    ];
    return (
        <section className="rw-card rw-sec" aria-label="Your decision"
            style={decision === "approve" ? { borderColor: "color-mix(in srgb, var(--brand-text) 45%, transparent)" }
                : decision === "edit" ? { borderColor: "color-mix(in srgb, var(--gold) 50%, transparent)" } : undefined}>
            <h2 className="rw-h">Your decision</h2>
            <div className="rw-opts" role="group" aria-label="Decision">
                {options.map(o => (
                    <button key={o.id} type="button" className="rw-opt" style={{ "--c": o.c }}
                        aria-pressed={decision === o.id} onClick={() => setDecision(o.id)}>
                        <span className="ic"><RwIcon d={o.d} s={17} w={o.w} /></span>
                        <b>{o.label}</b><small>{o.sub}</small>
                    </button>
                ))}
            </div>

            {decision === null && (
                <p style={{ margin: "12px 0 0", fontSize: 12.5, color: "var(--faint)" }}>
                    Pick one. The document stays on screen while you write your note.
                </p>
            )}

            {decision === "approve" && (
                <div className="rw-form">
                    <label>
                        <span>Note to the client <em>(optional)</em></span>
                        <textarea className="rw-ta" value={editNotes} onChange={e => setEditNotes(e.target.value)}
                            placeholder="e.g. Approved. Please file within 7 working days." />
                    </label>
                    <div className="rw-info">
                        <span style={{ color: "var(--brand-text)", display: "flex" }}><RwIcon d={RW.info} s={17} /></span>
                        <span>The client is notified, and this exact version becomes the final one.</span>
                    </div>
                    <button type="button" className="rw-cta" disabled={busy} onClick={() => onDecide("approve", editNotes.trim() || null)}>
                        {busy ? "Sending…" : "Approve & notify client"}
                    </button>
                    <button type="button" className="rw-btn" onClick={() => setDecision(null)}>Cancel</button>
                </div>
            )}

            {decision === "edit" && (
                <div className="rw-form">
                    <label>
                        <span>Required Changes <span style={{ color: "var(--danger)" }}>*</span></span>
                        <textarea className="rw-ta" style={{ minHeight: 130 }} value={returnNote} onChange={e => setReturnNote(e.target.value)}
                            placeholder="e.g. Update para 2 with the correct termination date, and add the CNIC number in the plaintiff's details." />
                        <span style={{ fontSize: 12, fontWeight: 500, color: "var(--faint)" }}>The client sees this with the returned document, and can send it back.</span>
                    </label>
                    {doc.note && (
                        <div className="rw-done"><b style={{ color: "var(--gold)" }}>They asked:</b> “{doc.note}”</div>
                    )}
                    <button type="button" className="rw-cta gold" disabled={busy || !returnNote.trim()}
                        onClick={() => onDecide("return", returnNote.trim() || null)}>
                        {busy ? "Sending…" : "Return to client"}
                    </button>
                    <button type="button" className="rw-btn" onClick={() => setDecision(null)}>Cancel</button>
                </div>
            )}

            {decision === "reject" && (
                <RejectDialog busy={busy} onCancel={() => setDecision(null)}
                    onConfirm={text => onDecide("reject", text)} />
            )}
        </section>
    );
}

/* What was checked when the draft was generated, frozen on the record. A
 * summary line each, with the detail one click away. Nothing here claims a
 * check that did not run: "not checked" is said as such, never as a pass. */
/* A header button that opens a small panel beneath it. For information a
 * lawyer looks at now and then -- checks, the record -- so it does not take
 * a column of the screen. A dot marks one that needs attention. */
function InfoPopover({ label, icon, alert = false, children }) {
    const [open, setOpen] = useState(false);
    const boxRef = useRef(null);
    useEffect(() => {
        if (!open) return undefined;
        const onDown = e => { if (!boxRef.current?.contains(e.target)) setOpen(false); };
        const onKey = e => { if (e.key === "Escape") setOpen(false); };
        document.addEventListener("mousedown", onDown);
        window.addEventListener("keydown", onKey);
        return () => { document.removeEventListener("mousedown", onDown); window.removeEventListener("keydown", onKey); };
    }, [open]);
    return (
        <div ref={boxRef} style={{ position: "relative" }}>
            <button type="button" className="rw-btn" aria-haspopup="dialog" aria-expanded={open}
                onClick={() => setOpen(o => !o)}>
                <RwIcon d={icon} s={16} />{label}
                {alert && <i aria-label="needs attention" style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--gold)" }} />}
                <RwIcon d="M6 9l6 6 6-6" s={14} />
            </button>
            {open && (
                <div role="dialog" aria-label={label} className="rw-pop">{children}</div>
            )}
        </div>
    );
}

/* Whether the checks have something the lawyer should look at. */
function checksNeedAttention(doc) {
    const c = doc?.compliance, v = doc?.verification;
    return Boolean((c?.checked && !c.complete) || !v
        || (v?.counts?.not_in_corpus || 0) + (v?.counts?.omitted || 0) > 0);
}

function ChecksCard({ doc, bare = false }) {
    const compliance = doc?.compliance || null;
    const verification = doc?.verification || null;
    const pillOf = (c, text) => <span className="rw-pill" style={rwTint(c)}>{text}</span>;

    const partSummary = !compliance?.checked ? pillOf("var(--faint)", "Not checked")
        : compliance.complete ? pillOf("var(--brand-text)", "Complete")
            : pillOf("var(--gold)", `${compliance.missing} missing`);
    const bad = (verification?.counts?.not_in_corpus || 0) + (verification?.counts?.omitted || 0);
    const citeSummary = !verification ? pillOf("var(--gold)", "Never verified")
        : verification.ran === false ? pillOf("var(--faint)", "Not run")
            : verification.counts?.total === 0 ? pillOf("var(--faint)", "None cited")
                : bad > 0 ? pillOf("var(--danger)", `${bad} to check`)
                    : pillOf("var(--brand-text)", `${verification.counts.verified} found`);

    return (
        <section className={bare ? "" : "rw-card rw-sec"} aria-label="Checks"
            style={!bare && bad > 0 ? { borderColor: "color-mix(in srgb, var(--danger) 45%, transparent)" } : undefined}>
            <h2 className="rw-h" style={{ marginBottom: 8 }}>Checks</h2>

            <details>
                <summary><span>Required particulars</span>{partSummary}</summary>
                <div className="rw-detail">
                    {!compliance?.checked ? (
                        // Not "all clear" — the check genuinely does not cover this
                        // template. Saying so beats an empty panel that reads as a pass.
                        <p style={{ margin: 0 }}>No completeness rules apply to this document type. Nothing was checked.</p>
                    ) : (
                        <>
                            <p style={{ margin: "0 0 8px" }}>Checked against {compliance.basis}.{" "}
                                {compliance.complete ? "Contains every particular the Code requires." : ""}</p>
                            {(compliance.items || []).filter(i => i.status === "missing").map(i => (
                                <div key={i.clause} className="item warn"><b>{i.clause} — {i.requirement}</b>{i.hint}</div>
                            ))}
                        </>
                    )}
                </div>
            </details>

            {/* Existence only, never whether an authority supports what it is
                cited for. Leads with what could NOT be confirmed. */}
            <details>
                <summary><span>Authorities cited</span>{citeSummary}</summary>
                <div className="rw-detail">
                    {verification?.scope && <p style={{ margin: "0 0 8px", fontSize: 11.5 }}>{verification.scope}</p>}
                    {!verification ? (
                        <p style={{ margin: 0 }}>This document predates citation checking. Its authorities were never verified — check each one before filing.</p>
                    ) : verification.ran === false ? (
                        <p style={{ margin: 0 }}>{verification.summary}</p>
                    ) : verification.counts?.total === 0 ? (
                        <p style={{ margin: 0 }}>No authority is cited anywhere in this draft.</p>
                    ) : (
                        <>
                            <p style={{ margin: "0 0 8px" }}>
                                {verification.counts.verified} found in the corpus ·{" "}
                                {verification.counts.omitted > 0 && <>{verification.counts.omitted} REPEALED · </>}
                                {verification.counts.unverifiable} cannot be checked here
                            </p>
                            {(verification.checks || []).filter(c => c.status !== "VERIFIED").map((c, i) => (
                                <div key={`${c.canonical}-${i}`} className={`item ${(c.status === "NOT_IN_CORPUS" || c.status === "OMITTED") ? "bad" : ""}`}>
                                    <b>{c.canonical}{c.status === "OMITTED" ? " — repealed" : c.status === "NOT_IN_CORPUS" ? " — not found" : " — cannot verify"}</b>
                                    {c.detail}
                                </div>
                            ))}
                            <p style={{ margin: 0, fontStyle: "italic" }}>Existence only — a real provision cited for something it does not say still shows as found.</p>
                        </>
                    )}
                </div>
            </details>

            <div className="rw-kv"><span>Category</span><b>{doc.caseCategory}</b></div>
        </section>
    );
}

function ScreenReview({ doc, t, onBack, onDecide, busy, next, prev }) {
    // EDITING (2026-10-11). The lawyer may change the wording and send it back
    // as their proposal -- a RETURN with edits, never an approval. Only while
    // the document waits for their decision, and only on the V2 record whose
    // submitted bytes the return is bound to.
    const canEdit = doc.status === "Pending Review" && doc.submittedVersion != null && !!doc.submittedPdfSha256;
    const [edit, setEdit] = useState(null);          // null | { html } while editing
    const [editErr, setEditErr] = useState("");
    const [loadingEdit, setLoadingEdit] = useState(false);
    const [dirty, setDirty] = useState(false);
    const [editNote, setEditNote] = useState("");
    const editorRef = useRef(null);
    const startEdit = async () => {
        setEditErr(""); setLoadingEdit(true);
        const { data, error } = await getReviewTextV2(doc.id);
        setLoadingEdit(false);
        if (error || !data?.body_html) {
            setEditErr(error?.message || "This document's text could not be opened for editing.");
            return;
        }
        setDirty(false); setEditNote("");
        setEdit({ html: data.body_html });
    };
    const cancelEdit = () => {
        if (dirty && typeof window !== "undefined"
            && !window.confirm("Discard your edits to this document?")) return;
        setEdit(null); setDirty(false); setEditErr("");
    };
    const sendEdits = () => {
        const html = editorRef.current?.innerHTML || "";
        if (!html.trim()) return;
        onDecide("return", editNote.trim() || null, null, html);
    };
    // The REAL generated PDF, rendered inline. This replaced DOC_CONTENT — a
    // hardcoded employment-dispute plaint the lawyer used to review and approve
    // regardless of the actual document.
    const [previewUrl, setPreviewUrl] = useState(null);
    // An OLDER revision the lawyer chose to look at. Null means "the submitted
    // one", which is what this screen exists to decide on.
    //
    // The decision is never taken from this. `handleDecide` sends the SUBMITTED
    // version and hash whatever is on screen, because approving is a statement
    // about the artifact the client submitted. Browsing the history is context
    // for that decision, not the subject of it.
    const [viewRev, setViewRev] = useState(null);
    const [tools, setTools] = useState(false);
    // PINNED TO THE REVISION UNDER REVIEW, not to "the current file". A late
    // arrival after unmount is revoked on arrival.
    useEffect(() => {
        let live = true, url = null;
        if (!doc?.id) return;
        fetchRevisionPreview(doc.id, {
            revisionId: viewRev?.revision_id || doc.viewRevisionId,
            expectedPdfSha256: viewRev?.pdf_sha256 || doc.viewPdfSha256,
        }).then((res) => {
            if (!live) {
                if (res?.data?.url) URL.revokeObjectURL(res.data.url);
                return;
            }
            if (res?.data?.url) { url = res.data.url; setPreviewUrl(res.data.url); }
            else setPreviewUrl(null);
        });
        return () => { live = false; if (url) URL.revokeObjectURL(url); };
    }, [doc?.id, doc?.viewRevisionId, doc?.viewPdfSha256, viewRev]);
    // Answers the client gave that the template has no field for. They are not
    // in the document, and the client believes they are.
    const fieldShape = doc?.fieldShape || null;

    return (
        <div data-review-ws data-drafting-theme data-mode={draftingMode(t)}>
            <style>{`${DRAFTING_TOKENS_CSS}\n${REVIEW_CSS}\n${REVIEW_PDF_CSS}\n${REVIEW_EDITOR_CSS}`}</style>
            <div className="rw-wrap">
                <ReviewHeader doc={doc} t={t} onBack={onBack}
                    right={edit ? <>
                        <button type="button" className="rw-btn" onClick={cancelEdit} disabled={busy}>Cancel</button>
                        <button type="button" className="rw-cta gold" style={{ height: 40, borderRadius: 10, fontSize: 14 }}
                            disabled={busy || !dirty} onClick={sendEdits}
                            title={dirty ? "Return the document to the client with your edits" : "Change the text first"}>
                            <RwIcon d="M9 14 4 9l5-5M4 9h10.5a5.5 5.5 0 0 1 0 11H11" s={16} />
                            {busy ? "Sending…" : "Send back with my edits"}
                        </button>
                    </> : <>
                        <PrevDocButton prev={prev} />
                        <ViewToolsButton on={tools} onToggle={() => setTools(v => !v)} />
                        {canEdit && (
                            <button type="button" className="rw-btn" onClick={startEdit} disabled={loadingEdit || busy}
                                title="Edit the wording and send it back to the client">
                                <RwIcon d="M12 20h9M16.38 3.62a1 1 0 0 1 3 3L7.37 18.64a2 2 0 0 1-.86.5l-2.87.84a.5.5 0 0 1-.62-.62l.84-2.87a2 2 0 0 1 .5-.86z" s={16} />
                                {loadingEdit ? "Opening…" : "Edit"}
                            </button>
                        )}
                        <DownloadPdfButton doc={doc} t={t} className="rw-btn" />
                        <NextDocButton next={next} />
                        <InfoPopover label="Checks" icon="M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" alert={checksNeedAttention(doc)}>
                            <ChecksCard doc={doc} bare />
                        </InfoPopover>
                    </>} />

                {editErr && <div role="alert" className="rw-card rw-sec" style={{ color: "var(--danger)", fontSize: 13.5 }}>{editErr}</div>}

                {edit ? (
                    <div aria-label="Edit document" style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
                        <label className="rw-card" style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", fontSize: 13, color: "var(--muted)" }}>
                            <span style={{ flex: "none", fontWeight: 600, color: "var(--ink)" }}>Note to the client</span>
                            <input value={editNote} onChange={e => setEditNote(e.target.value)} maxLength={2000}
                                placeholder="Optional — e.g. I changed clause 2 and the demand amount."
                                style={{ flex: 1, minWidth: 0, height: 34, padding: "0 12px", borderRadius: 9, border: "1px solid var(--line)", background: "var(--surface-2)", color: "var(--ink)", font: "inherit" }} />
                        </label>
                        <ReviewEditor html={edit.html} editorRef={editorRef} onDirty={() => setDirty(true)} />
                    </div>
                ) : (
                <div className="rw-grid">
                    <div aria-label="Document" style={{ minWidth: 0 }}>
                        {/* The saved bytes drawn in the review theme -- not Chrome's grey viewer. */}
                        <ReviewPdfView url={previewUrl} tools={tools} onTools={setTools}
                            label={<>
                                {viewRev ? `Reading an earlier draft (v${viewRev.version})` : "The version the client sent"}
                                {doc.submittedVersion != null && !viewRev && <> · <span className="rw-mono">v{doc.submittedVersion}</span></>}
                            </>}
                            notice={viewRev && (
                                <div className="rw-doc-bar" style={{ paddingRight: 150 }}>
                                    <span style={{ color: "var(--gold)" }}>Reading an earlier draft (v{viewRev.version}). Your decision still applies to the version the client submitted.</span>
                                    <button type="button" className="rw-btn" style={{ height: 32 }} onClick={() => setViewRev(null)}>Back to submitted</button>
                                </div>
                            )} />
                    </div>

                    <aside className="rw-side">
                        {doc.note && (
                            <section className="rw-card rw-sec rw-asked" aria-label="Client note">
                                <small>THE CLIENT ASKED</small>
                                <p>“{doc.note}”</p>
                            </section>
                        )}

                        {doc?.textEdited && (
                            <section data-wording-edited-notice className="rw-card rw-sec rw-flag">
                                <b>Wording edited by the client</b>
                                <p>This document began as a {doc.type} template, but the client edited its text.
                                    It is not the template's reviewed wording. Required particulars were not
                                    checked on it; read the whole text.</p>
                            </section>
                        )}

                        {fieldShape?.unknown?.length > 0 && (
                            <section className="rw-card rw-sec rw-flag">
                                <b>Answers not in this document</b>
                                <p>The client supplied {fieldShape.unknown.join(", ")}, which this template has no
                                    field for. Those values are NOT in the draft you are reading, and the client has
                                    no reason to know that.</p>
                            </section>
                        )}

                        {/* Statutory completeness and citations: in the header's
                            "Checks" button now, not a column of their own. */}

                        {/* Its own card, and nothing at all when there is only the one
                            version -- a wrapper here showed as an empty bar. */}
                        <RevisionHistory
                            docId={doc.id} t={t} reloadKey={doc.viewRevisionId}
                            currentRevisionId={viewRev?.revision_id || doc.viewRevisionId}
                            onPreview={rev => setViewRev(
                                rev.revision_id === doc.viewRevisionId ? null : rev)} />

                        <DecisionPanel doc={doc} busy={busy} onDecide={onDecide} />
                    </aside>
                </div>
                )}
            </div>
        </div>
    );
}

// ═══════════════════════════════════════════════════════════════
// FINAL — the approved document
// ═══════════════════════════════════════════════════════════════
// complianceSummary tone → colour. Neutral is not green: "not checked" is not a pass.
const _PARTICULARS_COLOR = { success: "var(--brand-text)", warn: "var(--gold)", neutral: "var(--faint)" };

function ScreenFinal({ doc, t, onBack, next, prev }) {
    const [tools, setTools] = useState(false);
    const particulars = complianceSummary(doc?.compliance);
    const approvedOn = doc?.reviewedAt
        ? new Date(doc.reviewedAt).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : null;
    const [previewUrl, setPreviewUrl] = useState(null);
    // PINNED TO THE REVISION THAT WAS DECIDED; a late arrival is revoked.
    useEffect(() => {
        let live = true, url = null;
        if (!doc?.id) return;
        fetchRevisionPreview(doc.id, {
            revisionId: doc.viewRevisionId,
            expectedPdfSha256: doc.viewPdfSha256,
        }).then((res) => {
            if (!live) {
                if (res?.data?.url) URL.revokeObjectURL(res.data.url);
                return;
            }
            if (res?.data?.url) { url = res.data.url; setPreviewUrl(res.data.url); }
            else setPreviewUrl(null);
        });
        return () => { live = false; if (url) URL.revokeObjectURL(url); };
    }, [doc?.id, doc?.viewRevisionId, doc?.viewPdfSha256]);

    // Only what was recorded, said once. The fixed "Workflow complete" list
    // that used to sit here ticked "AI Draft Generated" on every document,
    // drafted by AI or not; the type, client and case are in the header.
    return (
        <div data-review-ws data-drafting-theme data-mode={draftingMode(t)}>
            <style>{`${DRAFTING_TOKENS_CSS}\n${REVIEW_CSS}\n${REVIEW_PDF_CSS}`}</style>
            <div className="rw-wrap">
                <ReviewHeader doc={{ ...doc, status: "Final" }} t={t} onBack={onBack}
                    extra={<>
                        {/* When the decision was RECORDED — not today's date. */}
                        <span aria-hidden="true">·</span><span>Approved {approvedOn || "— date not recorded"}</span>
                        {/* What pleading_rules found, frozen at generation; shown
                            only when it found something missing. */}
                        {particulars.tone === "warn" && (
                            <span className="rw-pill" style={rwTint(_PARTICULARS_COLOR.warn)}><i />{particulars.label}</span>
                        )}
                    </>}
                    right={<>
                        {/* Export: only the revision-bound download is real, so only it is shown. */}
                        <PrevDocButton prev={prev} />
                        <ViewToolsButton on={tools} onToggle={() => setTools(v => !v)} />
                        <DownloadPdfButton doc={doc} t={t} className="rw-btn" />
                        <NextDocButton next={next} />
                    </>} />

                <div aria-label="Approved document">
                    <ReviewPdfView url={previewUrl} label="The approved version" tools={tools} onTools={setTools} />
                </div>
            </div>
        </div>
    );
}

// ═══════════════════════════════════════════════════════════════
// ROOT APP
// ═══════════════════════════════════════════════════════════════
// review_status (backend) → display status
const _REVIEW_STATUS_LABEL = {
    submitted: "Pending Review",
    approved: "Approved",
    returned: "Returned",
    rejected: "Rejected",
};
const _URGENCY_LABEL = { normal: "Normal", priority: "Priority", urgent: "Urgent" };

/* What to put in a tab's badge.
 *
 * The server's number when there is one, because counting the rows a client
 * happens to have loaded is wrong the moment the queue is paginated — and wrong
 * in the direction that HIDES work: a lawyer with three pages of pending
 * reviews would see a badge reading 25.
 *
 * An em dash rather than 0 while the counts are unknown. They arrive with the
 * first page only, so a continuation carries `counts: null` meaning
 * "unchanged"; rendering that as a number would announce an empty queue on
 * every "load more". Zero is a claim, and it must be made only when the server
 * has made it.
 */
function _tabCount(counts, tab, docs, serverFiltered) {
    const status = Object.fromEntries(QUEUE_TABS)[tab];
    if (counts && counts[status] != null) return counts[status];
    // Legacy queue: unpaginated, so what is loaded IS everything, and counting
    // it here is accurate.
    if (!serverFiltered) {
        return tab === "All" ? docs.length
            : docs.filter(d => d.status === tab).length;
    }
    return "—";
}

function _mapQueueDoc(d) {
    return {
        id: d.id,
        client: d.client_name || "Client",
        caseId: (d.case_number || d.case_id || "—").slice(-8).toUpperCase(),
        // The full id, to open the case. Null for a standalone document: a case
        // is optional, and "no case" is a normal state, not an error.
        caseRawId: d.case_id || null,
        caseCategory: _CASE_TYPE_MAP[d.case_type] || "General",
        title: d.title || "Legal Document",
        type: _TMPL_MAP[d.template_type] || d.template_type || "Document",
        status: _REVIEW_STATUS_LABEL[d.review_status] || "Pending Review",
        urgency: _URGENCY_LABEL[d.urgency] || "Normal",
        submitted: d.submitted_at ? new Date(d.submitted_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "",
        // The raw instant, for "waiting 2 days" and for working in order.
        submittedAt: d.submitted_at || null,
        // The CLIENT's note and the LAWYER's are separate fields on v2: the
        // queue sends client_note, and review_note only on a decided row (the
        // lawyer's own note for that cycle). The legacy queue has no queue_role
        // and still carries the client's note in review_note.
        note: d.client_note || (d.queue_role ? "" : d.review_note) || "",
        lawyerNote: d.lawyer_note || (d.queue_role === "decided" ? d.review_note : "") || "",
        // Carried through verbatim: the review screen shows what was actually
        // checked when the draft was generated. Dropping them here would leave
        // the panels blank, which reads as "nothing to report".
        compliance: d.compliance || null,
        verification: d.verification || null,
        // THE EXACT REVISION UNDER REVIEW.
        //
        // `review` guards its atomic update on (submitted_version,
        // submitted_pdf_sha256), so these are not decoration — they are what
        // makes a decision valid. Null on the legacy queue, which is how the
        // screen knows which backend it is talking to without a probe.
        submittedVersion: d.submitted_version ?? null,
        fieldShape: d.field_shape ?? null,
        // The client edited the wording: read it as text, not as the template.
        textEdited: Boolean(d.text_edited),
        // Came from a quick review request: the client has not hired this lawyer.
        quickReview: Boolean(d.quick_review),
        submittedRevisionId: d.submitted_revision_id ?? null,
        submittedPdfSha256: d.submitted_pdf_sha256 ?? null,

        // THE REVISION THIS LAWYER MAY ACTUALLY READ.
        //
        // A decided row has no `submitted_*` at all — the decision cleared
        // them, and the server deliberately does not substitute the document's
        // live pointers, because after a return-and-resubmit those describe
        // somebody else's review. What it sends instead is the revision THIS
        // lawyer decided on.
        //
        // So preview and download read `viewRevisionId`, which is whichever of
        // the two applies. Without it, opening anything from the Approved,
        // Returned or Rejected tabs asked for a null revision and fell through
        // to the legacy download route, which 404s on every V2 document.
        //
        // The DECISION still reads `submittedVersion`/`submittedPdfSha256` and
        // must keep doing so: they are null on a decided row precisely because
        // a decided document cannot be decided again.
        reviewedRevisionId: d.reviewed_revision_id ?? null,
        reviewedPdfSha256: d.reviewed_pdf_sha256 ?? null,
        reviewedAction: d.reviewed_action ?? null,
        reviewedAt: d.reviewed_at ?? null,
        queueRole: d.queue_role ?? null,
        viewRevisionId: d.submitted_revision_id ?? d.reviewed_revision_id ?? null,
        viewPdfSha256: d.submitted_pdf_sha256 ?? d.reviewed_pdf_sha256 ?? null,
    };
}

// How many inbox rows one page holds. Bounded so the response size does not
// grow with how long a lawyer has been using the product.
const QUEUE_PAGE = 25;

function DocWorkflowApp() {
    const { t } = useTheme();
    const [screen, setScreen] = useState("inbox");
    const [activeDoc, setActiveDoc] = useState(null);
    const [docs, setDocs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [toast, setToast] = useState(null);
    // A decision refused because the document moved. Held separately from the
    // toast because it must not time out — the lawyer has to act on it, and a
    // message about the wrong document being approved should not vanish after
    // three seconds.
    const [staleWarning, setStaleWarning] = useState(null);
    // How far through the inbox we are. Null means there is no next page —
    // either the end, or the legacy queue, which has no cursor at all.
    const [queueCursor, setQueueCursor] = useState(null);
    const [loadingMore, setLoadingMore] = useState(false);
    // WHICH TAB, held here rather than in the inbox, because it now decides
    // what gets FETCHED. While it lived in the child it could only filter what
    // had already been loaded — which was one page of pending documents, so
    // three of the five tabs could never show anything at all.
    const [statusF, setStatusF] = useState("All");
    // The server's per-tab totals. Null until the first page answers, and null
    // again is not zero: see _tabCount.
    const [queueCounts, setQueueCounts] = useState(null);
    // Is the server doing the filtering? False on the legacy queue, which has
    // no status parameter and returns everything unpaginated.
    const [serverFiltered, setServerFiltered] = useState(true);
    // "Is this page still wanted?" A decision reloads the queue, and a page
    // request already in flight when that happens must not land afterwards.
    const queueGeneration = useRef(createGeneration()).current;
    // A decision the server could not record right now, with the SAME key it
    // was first attempted under.
    const [retry, setRetry] = useState(null);
    const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(null), 3200); };

    // The inbox, ONE PAGE AT A TIME.
    //
    // The queue it replaces returned every document ever submitted to this
    // lawyer in a single response — no cursor, no bound. That is fine on a demo
    // account and a cliff on a real one: the response grows without limit, and
    // the lawyer waits for all of it to draw the first row.
    //
    // `after` continues from a cursor; omitting it reloads from the start,
    // which is what a decision, a tab change or a stale-document reload wants.
    //
    // `tab` is passed explicitly rather than read from state, because a tab
    // change has to fetch the NEW tab in the same tick it is selected in —
    // reading `statusF` here would fetch the one being left.
    const load = async (after = null, tab = statusF) => {
        if (after) setLoadingMore(true); else setLoading(true);
        const ticket = queueGeneration.next();
        const wanted = QUEUE_STATUS_OF[tab] || "all";

        const v2 = await reviewQueueV2({ status: wanted, cursor: after,
                                        limit: QUEUE_PAGE });
        let rows, cursor, counts, filteredByServer = true;

        if (v2.error && v2.status === 404
            && errorCode(v2.error) === "feature_disabled") {
            // The flag is off. The legacy queue is unpaginated by nature and
            // takes no status, so there is nothing to continue from and the
            // filtering falls back to the client.
            const legacy = await listReviewQueue();
            rows = Array.isArray(legacy.data) ? legacy.data : [];
            cursor = null;
            counts = null;
            filteredByServer = false;
        } else if (v2.error) {
            if (!queueGeneration.isCurrent(ticket)) return;
            setLoading(false); setLoadingMore(false);
            showToast("❌ " + (v2.error.message || "Could not load the queue"));
            return;
        } else {
            rows = v2.data?.items || [];
            cursor = v2.data?.next_cursor || null;
            // Counts come with the first page only; on a continuation this is
            // null, meaning "unchanged", and the previous value is kept.
            counts = v2.data?.counts ?? null;

            // THE TAB THIS RESPONSE ANSWERS. A generation ticket catches a
            // response overtaken by a newer request, but not one that is still
            // "current" by ticket while being about a tab the user has since
            // left — two rapid tab clicks can resolve in either order. The
            // server echoes the status it filtered on, so the check is on the
            // response's own claim rather than on timing.
            const answered = v2.data?.status;
            if (answered && answered !== wanted) return;
        }

        // The user moved on — switched screens, or a decision triggered a
        // reload that this response is now behind. Dropping it is the point:
        // otherwise a slow first page lands on top of a fresher one.
        if (!queueGeneration.isCurrent(ticket)) return;

        const mapped = rows.map(_mapQueueDoc);
        setServerFiltered(filteredByServer);
        if (counts) setQueueCounts(counts);
        setDocs(prev => {
            const merged = after ? [...prev, ...mapped] : mapped;
            // A document that moved between pages can legitimately appear
            // twice; rendering it twice looks like data corruption.
            const seen = new Set();
            return merged.filter(d => {
                if (seen.has(d.id)) return false;
                seen.add(d.id);
                return true;
            });
        });
        setQueueCursor(cursor);
        setLoading(false); setLoadingMore(false);
    };
    useEffect(() => { load().catch(() => setLoading(false)); }, []);

    // Quick review requests waiting for this lawyer's answer.
    const [quick, setQuick] = useState(null);
    const [quickBusy, setQuickBusy] = useState(null);
    const loadQuick = async () => {
        const r = await Promise.resolve(quickReviewInbox()).catch(() => null);
        if (!r || r.error) { setQuick([]); return; }
        setQuick(Array.isArray(r.data) ? r.data : (r.data?.items || []));
    };
    useEffect(() => { loadQuick(); }, []);

    /* Switching tabs is a NEW query, not a filter over the old one.
     *
     * The cursor is reset because it names a position in the tab being left and
     * means nothing in the one being entered. The rows are cleared for the same
     * reason: leaving them on screen under a new heading shows a lawyer
     * documents that are not in the tab they just chose.
     */
    const changeTab = (tab) => {
        if (tab === statusF) return;
        setStatusF(tab);
        setQueueCursor(null);
        setDocs([]);
        // Bumps the generation, so a page still in flight for the previous tab
        // is dropped when it lands.
        load(null, tab).catch(() => setLoading(false));
    };

    const openDoc = (doc, keepTrail = false) => {
        setActiveDoc(doc); setScreen(doc.status === "Approved" ? "final" : "review");
        if (!keepTrail) setTrail([]);
    };
    // The documents left with "Next", newest last, so "Previous" can go back.
    const [trail, setTrail] = useState([]);
    // "Next document": the next one still waiting for a decision, in the
    // inbox's work order. It never leads onto a finished document -- that read
    // as the open document's own next page. Hidden when nothing else waits.
    const others = activeDoc ? docs.filter(d => d.id !== activeDoc.id) : [];
    const waitingOthers = workOrder(others.filter(d => d.status === "Pending Review"));
    const nextUp = waitingOthers[0] || null;
    const next = nextUp ? {
        title: nextUp.title,
        count: waitingOthers.length,
        position: `${waitingOthers.length} waiting`,
        open: () => { setTrail(tr => [...tr, activeDoc.id]); openDoc(nextUp, true); },
    } : null;
    const prevDoc = trail.length ? docs.find(d => d.id === trail[trail.length - 1]) : null;
    const prev = prevDoc ? {
        title: prevDoc.title,
        open: () => { setTrail(tr => tr.slice(0, -1)); openDoc(prevDoc, true); },
    } : null;
    const reset = () => { setScreen("inbox"); setActiveDoc(null); setTrail([]); };

    // FROM A NOTIFICATION, STRAIGHT TO THE DOCUMENT (2026-10-09). The bell used
    // to land on the inbox and leave the lawyer to find the row. App.jsx leaves
    // the id in sessionStorage (this page not open yet) or announces it (open).
    const [wantDoc, setWantDoc] = useState(() => {
        try {
            const id = sessionStorage.getItem("attorney:lawyer-open-doc");
            if (id) sessionStorage.removeItem("attorney:lawyer-open-doc");
            return id || null;
        } catch { return null; }
    });
    // Accepting submits the document to this lawyer; it then opens like any
    // pending document, from a fresh read of the queue.
    const acceptQuick = async r => {
        setQuickBusy(r.id);
        const { error } = await acceptQuickReview(r.id) || {};
        setQuickBusy(null);
        loadQuick();
        if (error) { showToast("❌ " + (error.message || "Could not accept the request")); return; }
        showToast("✅ Accepted — the client has been notified");
        setWantDoc(r.doc_id);
        if (statusF === "All" || statusF === "Pending Review") load().catch(() => {});
        else changeTab("All");
    };
    const declineQuick = async r => {
        setQuickBusy(r.id);
        const { error } = await declineQuickReview(r.id) || {};
        setQuickBusy(null);
        loadQuick();
        showToast(error ? "❌ " + (error.message || "Could not decline the request") : "Declined — the client has been told");
    };
    // The latest load, for listeners registered once.
    const loadRef = useRef(load);
    loadRef.current = load;
    const loadQuickRef = useRef(loadQuick);
    loadQuickRef.current = loadQuick;
    useEffect(() => {
        const onOpen = e => {
            try { sessionStorage.removeItem("attorney:lawyer-open-doc"); } catch { /* storage off */ }
            if (e.detail) { setWantDoc(e.detail); loadRef.current().catch(() => {}); }
        };
        window.addEventListener("attorney:open-review-doc", onOpen);
        // A new submission, a withdrawal: re-read the queue while the lawyer is
        // on it, instead of only when they navigate away and back.
        const off = onNotification(n => {
            if (String(n?.type || "").startsWith("document_")) loadRef.current().catch(() => {});
            if (String(n?.type || "").startsWith("quick_review_")) loadQuickRef.current();
        });
        return () => { window.removeEventListener("attorney:open-review-doc", onOpen); off(); };
    }, []);
    useEffect(() => {
        if (!wantDoc || loading) return;
        const row = docs.find(d => d.id === wantDoc);
        setWantDoc(null);
        if (row) openDoc(row);
        else showToast("That document is not in this list any more. It may have been withdrawn.");
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [wantDoc, loading, docs]);

    // The real decision: persists the status and notifies the client.
    //
    // ON V2 IT IS GUARDED AGAINST A STALE REVISION. The server matches the
    // decision against (submitted_version, submitted_pdf_sha256) inside the
    // same atomic update that applies it, so a lawyer who has been looking at a
    // document the client regenerated underneath them matches nothing and is
    // told so — rather than approving bytes they never read. That is the whole
    // point of sending the expected pair, and approving the wrong revision is
    // the most expensive mistake this screen can make: the approval is what
    // gets filed.
    //
    // The key is minted ONCE per decision and reused by the retry, so pressing
    // Approve twice — or a retry after a dropped response — records one
    // transition. A fresh key per attempt would make the receipt machinery
    // unreachable from here.
    const handleDecide = async (action, note, key = null, edits = null) => {
        const idemKey = key || idempotencyKey();
        setBusy(true);

        const canUseV2 = activeDoc.submittedVersion != null
            && !!activeDoc.submittedPdfSha256;
        const sent = edits && canUseV2
            ? await returnWithEditsV2(activeDoc.id, {
                bodyHtml: edits,
                note,
                expectedVersion: activeDoc.submittedVersion,
                expectedPdfSha256: activeDoc.submittedPdfSha256,
            }, idemKey)
            : null;
        const { data, error, status } = sent || (canUseV2
            ? await reviewDocumentV2(activeDoc.id, {
                action,
                expectedVersion: activeDoc.submittedVersion,
                expectedPdfSha256: activeDoc.submittedPdfSha256,
                note,
            }, idemKey)
            : await reviewDocument(activeDoc.id, { action, note }));
        setBusy(false);

        if (error) {
            const code = errorCode(error);
            // The document moved. NEVER report this as a generic failure and
            // never let the decision through: the lawyer must look at what is
            // actually there now before deciding on it.
            if (code === "review_limit_reached") {
                // A 409, but not the usual one. Every other conflict here means
                // "reload and try again"; this document has been reviewed as
                // many times as it can be, and reloading cannot help. Told as a
                // blocking banner rather than a toast, because the lawyer has
                // to stop and tell the client rather than keep pressing.
                setStaleWarning(
                    (error?.message
                        || "This document has reached its review limit.")
                    + " Ask the client to start a new document — reloading "
                    + "will not change this.");
                return;
            }
            if (edits && status === 409 && error?.message) {
                // Edits refused for a stated reason (the client changed it, the
                // text can't be edited): the server's words, not a generic one.
                setStaleWarning(error.message);
                return;
            }
            if (status === 409 || code === "conflict" || code === "stale_revision") {
                setStaleWarning(
                    "This document changed after you opened it. Reload the queue "
                    + "and review the latest version before deciding.");
                return;
            }
            if (status === 503) {
                // The work may or may not have been recorded, which is exactly
                // what the key is for — the retry reuses it.
                setRetry({ action, note, key: idemKey, edits });
                showToast("⏳ The service is busy. Retry when ready.");
                return;
            }
            // 422 and everything else: the server's own words. It sends a
            // machine-readable message precisely so this does not have to
            // invent one.
            showToast("❌ " + (error.message || "Failed to record decision"));
            return;
        }

        const newLabel = _REVIEW_STATUS_LABEL[(edits ? data?.review : data)?.review_status] ||
            (action === "approve" ? "Approved" : action === "return" ? "Returned" : "Rejected");
        setDocs(prev => prev.map(d => d.id === activeDoc.id ? { ...d, status: newLabel, lawyerNote: note || "" } : d));
        showToast(edits ? "✅ Returned with your edits — the client has been notified"
            : `✅ ${newLabel} — the client has been notified`);
        setRetry(null);
        reset();
        // The decision moved the document between tabs and changed the counts:
        // re-read the current tab from the server (the row patched above only
        // bridges the round trip), and tell the shell its sidebar badge is stale.
        load().catch(() => {});
        if (typeof window !== "undefined") window.dispatchEvent(new Event("attorney:review-decided"));
    };

    return (
        // Exactly the app's <main> (which does not scroll for this page): each
        // screen scrolls inside it. With minHeight:100vh a long inbox grew past
        // <main> and its lower rows were clipped.
        <div style={{
            flex: 1, minHeight: 0, display: "flex", flexDirection: "column",
            background: t.bg, fontFamily: "DM Sans,system-ui,sans-serif", color: t.text
        }}>

            {screen === "inbox" && <ScreenInbox t={t} onOpen={openDoc} docs={docs}
                loading={loading} hasMore={!!queueCursor} loadingMore={loadingMore}
                onLoadMore={() => load(queueCursor)}
                statusF={statusF} onStatusChange={changeTab}
                counts={queueCounts} serverFiltered={serverFiltered}
                quick={quick} quickBusy={quickBusy} onAcceptQuick={acceptQuick} onDeclineQuick={declineQuick} />}
            {/* Review and decision are one screen (2026-10-11): the document
                stays in view while the lawyer decides. */}
            {screen === "review" && activeDoc && (
                <ScreenReview key={activeDoc.id} doc={activeDoc} t={t} busy={busy}
                    onBack={reset} next={next} prev={prev}
                    onDecide={handleDecide} />
            )}
            {screen === "final" && activeDoc && (
                <ScreenFinal key={activeDoc.id} doc={activeDoc} t={t} onBack={reset} next={next} prev={prev} />
            )}

            {/* THE DOCUMENT MOVED.
                A blocking banner, not a toast: the lawyer has to act on this,
                and a message saying they were about to approve the wrong
                revision must not disappear after three seconds. Reloading is
                the only way out, by design — the point is that they look at
                what is actually there before deciding on it. */}
            {staleWarning && (
                <div style={{
                    position: "fixed", top: 16, left: "50%", transform: "translateX(-50%)",
                    zIndex: 10000, maxWidth: 560,
                    background: "#7c2d12", border: "1px solid #f59e0b",
                    borderRadius: 10, padding: "12px 18px", fontSize: 13,
                    color: "#fff", boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
                    display: "flex", alignItems: "center", gap: 14,
                }}>
                    <span style={{ flex: 1 }}>⚠ {staleWarning}</span>
                    <button
                        onClick={async () => { setStaleWarning(null); reset(); await load(); }}
                        style={{
                            background: "#fff", color: "#7c2d12", border: "none",
                            borderRadius: 8, padding: "6px 14px", fontSize: 12,
                            fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap",
                        }}>
                        Reload queue
                    </button>
                </div>
            )}

            {/* A decision the server could not record. Retried with the SAME
                key it was first attempted under, so a request that did land
                before the connection dropped is replayed rather than repeated. */}
            {retry && (
                <div style={{
                    position: "fixed", top: 16, left: "50%", transform: "translateX(-50%)",
                    zIndex: 9999, background: t.card, border: `1px solid ${t.border}`,
                    borderRadius: 10, padding: "10px 16px", fontSize: 13,
                    color: t.text, display: "flex", alignItems: "center", gap: 12,
                }}>
                    <span>The service was busy and your decision was not recorded.</span>
                    <button
                        onClick={() => handleDecide(retry.action, retry.note, retry.key, retry.edits)}
                        disabled={busy}
                        style={{
                            background: t.primary, color: "#fff", border: "none",
                            borderRadius: 8, padding: "6px 14px", fontSize: 12,
                            fontWeight: 700, cursor: busy ? "default" : "pointer",
                        }}>
                        {busy ? "Retrying…" : "Retry"}
                    </button>
                </div>
            )}

            {toast && (
                <div style={{
                    position: "fixed", bottom: 28, left: "50%", transform: "translateX(-50%)", zIndex: 9999,
                    background: t.card, border: `1px solid ${t.border}`, borderRadius: 10,
                    padding: "10px 20px", fontSize: 13, color: t.text, boxShadow: "0 8px 32px rgba(0,0,0,0.3)"
                }}>{toast}</div>
            )}
        </div>
    );
}
export { DocWorkflowApp };
