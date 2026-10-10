'use client';
// Lawyer Documents Page — paste your code here
import { useState, useEffect, useRef } from "react";
import { useTheme } from "./theme.js";
import { useCase } from "./theme.js";
import { Btn, Input } from "./components.jsx";
import RevisionHistory from "./RevisionHistory.jsx";
import { Icon, I } from "./icons.jsx";
import { DRAFTING_TOKENS_CSS, draftingMode } from "./draftingTheme.js";
import {
    listReviewQueue, reviewDocument, downloadDocumentFile,
    fetchRevisionPreview, reviewDocumentV2, reviewQueueV2,
    idempotencyKey, errorCode,
} from "@/lib/api.js";
import { useAuth } from "@/context/AuthContext.jsx";
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

const STEPS = [
    { id: "inbox", label: "Document Inbox", icon: "📥" },
    { id: "review", label: "Review & Validate", icon: "✏️" },
    { id: "decision", label: "Decision & Notify", icon: "⚖️" },
    { id: "final", label: "Final & Export", icon: "📤" },
];
const STEP_IDX = { inbox: 0, review: 1, decision: 2, final: 3 };

const STATUS_COLOR = {
    "Pending Review": { dot: "#FFC857", badge: "rgba(255,200,87,0.15)", text: "#FFC857", border: "rgba(255,200,87,0.3)" },
    "Under Review": { dot: "#5AB3FF", badge: "rgba(90,179,255,0.15)", text: "#5AB3FF", border: "rgba(90,179,255,0.3)" },
    "Approved": { dot: "#4DD4A3", badge: "rgba(77,212,163,0.15)", text: "#4DD4A3", border: "rgba(77,212,163,0.3)" },
    "Returned": { dot: "#FFC857", badge: "rgba(255,200,87,0.15)", text: "#FFC857", border: "rgba(255,200,87,0.3)" },
    "Rejected": { dot: "#FF6B7A", badge: "rgba(255,107,122,0.15)", text: "#FF6B7A", border: "rgba(255,107,122,0.3)" },
    "Final": { dot: "#40F0DC", badge: "rgba(64,240,220,0.15)", text: "#40F0DC", border: "rgba(64,240,220,0.3)" },
};
const URGENCY_COLOR = { Normal: "#9A9A94", Priority: "#FFC857", Urgent: "#FF6B7A" };

// ─── SMALL HELPERS ────────────────────────────────────────────
const Avatar = ({ name, size = 34, t }) => {
    const initials = name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
    return (
        <div style={{
            width: size, height: size, borderRadius: "50%", background: `${t.primary}25`,
            border: `1.5px solid ${t.primary}50`, display: "flex", alignItems: "center",
            justifyContent: "center", fontSize: size * 0.35, fontWeight: 700, color: t.primary,
            flexShrink: 0, fontFamily: "DM Sans,system-ui"
        }}>
            {initials}
        </div>
    );
};

const StatusPill = ({ status, t }) => {
    const s = STATUS_COLOR[status] || STATUS_COLOR["Under Review"];
    return (
        <span style={{
            display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 10px",
            borderRadius: 20, background: s.badge, color: s.text, border: `1px solid ${s.border}`,
            fontSize: 11, fontWeight: 700, whiteSpace: "nowrap"
        }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: s.dot, flexShrink: 0 }} />
            {status}
        </span>
    );
};

const UrgencyBadge = ({ urgency }) => (
    <span style={{
        fontSize: 10, padding: "2px 7px", borderRadius: 6, fontWeight: 700,
        background: `${URGENCY_COLOR[urgency]}18`, color: URGENCY_COLOR[urgency],
        border: `1px solid ${URGENCY_COLOR[urgency]}35`, whiteSpace: "nowrap"
    }}>
        {urgency === "Urgent" ? "🔴" : urgency === "Priority" ? "🟡" : "🟢"} {urgency}
    </span>
);



// ─── TOP STEPPER ──────────────────────────────────────────────
function Stepper({ step, t }) {
    const active = STEP_IDX[step];
    return (
        <div style={{
            display: "flex", alignItems: "center", padding: "12px 28px",
            background: "transparent", flexShrink: 0
        }}>
            {STEPS.map((s, i) => {
                const done = i < active, cur = i === active;
                return (
                    <div key={s.id} style={{
                        display: "flex", alignItems: "center",
                        flex: i < STEPS.length - 1 ? 1 : undefined
                    }}>
                        {/* Step node: icon circle + label inline when active */}
                        <div style={{ display: "flex", alignItems: "center", gap: cur ? 8 : 0, flexShrink: 0 }}>
                            <div style={{
                                width: 34, height: 34, borderRadius: "50%",
                                display: "flex", alignItems: "center", justifyContent: "center",
                                border: `2px solid ${done || cur ? t.primary : t.border}`,
                                background: done ? t.primary : cur ? t.primaryGlow2 : "transparent",
                                color: done ? (t.mode === "dark" ? "#111E24" : "#fff") : cur ? t.primary : t.textFaint,
                                fontSize: 14, transition: "all .22s", flexShrink: 0,
                                boxShadow: cur ? `0 0 0 3px ${t.primary}25` : "none"
                            }}>
                                {done ? "✓" : s.icon}
                            </div>
                            {cur && (
                                <span style={{
                                    fontSize: 12, fontWeight: 700, color: t.primary,
                                    whiteSpace: "nowrap", letterSpacing: "0.01em"
                                }}>
                                    {s.label}
                                </span>
                            )}
                        </div>
                        {i < STEPS.length - 1 && (
                            <div style={{
                                flex: 1, height: 1.5, margin: "0 10px",
                                background: done ? t.primary : t.border,
                                transition: "background .22s", borderRadius: 2
                            }} />
                        )}
                    </div>
                );
            })}
        </div>
    );
}

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

function ScreenInbox({
    t, onOpen, docs, loading, hasMore, loadingMore, onLoadMore,
    statusF, onStatusChange, counts, serverFiltered,
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
                                            <span className="ri-sub" style={{ display: "block" }}>{doc.caseId && doc.caseId !== "—" ? <span className="ri-mono">{doc.caseId}</span> : "No case linked"}</span>
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
function DownloadPdfButton({ doc, t, style }) {
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
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
            <button onClick={download} disabled={busy} style={style}>{busy ? "Downloading…" : "⬇ Download PDF"}</button>
            {issue && <div role="alert" style={{ fontSize: 11, color: t.danger }}>{issue}</div>}
        </div>
    );
}

/* The document's case, as a way to it (2026-10-09): review used to be a dead
 * end with only a shortened reference. A standalone document says so plainly. */
function CaseLink({ doc, t }) {
    const { setPage, setOpenCaseId } = useCase();
    if (!doc.caseRawId) return <span data-case-link="none" style={{ color: t.textMuted }}>No case — standalone document</span>;
    return (
        <button type="button" data-case-link={doc.caseRawId} title="Open this case"
            onClick={() => { setOpenCaseId?.(doc.caseRawId); setPage?.("cases"); }}
            style={{ background: "none", border: 0, padding: 0, cursor: "pointer", fontFamily: "monospace", fontSize: 10.5, color: t.primary, textDecoration: "underline", textUnderlineOffset: 2 }}>
            Case {doc.caseId} ↗
        </button>
    );
}

function ScreenReview({ doc, t, onBack, onContinue }) {
    // The REAL generated PDF, rendered inline. This replaced DOC_CONTENT — a
    // hardcoded employment-dispute plaint the lawyer used to review and approve
    // regardless of the actual document.
    const [previewUrl, setPreviewUrl] = useState(null);
    // An OLDER revision the lawyer chose to look at. Null means "the submitted
    // one", which is what this screen exists to decide on.
    //
    // The decision is never taken from this. `handleDecide` sends the SUBMITTED
    // version and hash whatever is on screen, because approving is a statement
    // about the artifact the client submitted, and a reviewer who could approve
    // while reading v1 would be signing off on a document nobody filed. Browsing
    // the history is context for that decision, not the subject of it.
    const [viewRev, setViewRev] = useState(null);
    // PINNED TO THE REVISION UNDER REVIEW, not to "the current file".
    //
    // The legacy path fetched whatever the document currently was, so a client
    // who regenerated after submitting would have the lawyer reading the NEW
    // bytes while deciding on the submitted ones — and the decision guard would
    // then refuse, with no explanation of what they had actually been looking
    // at. Naming the submitted revision keeps the page and the decision on the
    // same object.
    //
    // The old cleanup also leaked: it revoked `url`, a local still null when
    // the fetch resolved after unmount, while the object URL had already been
    // created inside the helper. A late arrival is revoked on arrival now.
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
    // These two come from the document itself, computed when it was generated
    // and frozen on the record. They replace four hardcoded rows that read
    // "Legal Compliance ✓ Verified / Case Details ✓ Verified / Factual Info
    // ⚠ Review / Format ✓ Passed" on EVERY document regardless of content —
    // nothing was ever checked. Telling the lawyer who signs and files that a
    // draft is verified, when no check ran, is the most expensive lie this
    // screen could tell.
    const compliance = doc?.compliance || null;
    const verification = doc?.verification || null;
    // Answers the client gave that the template has no field for. They are not
    // in the document, and the client believes they are.
    const fieldShape = doc?.fieldShape || null;

    return (
        <div className="rgrid" style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 300px", gap: 0, overflow: "hidden" }}>
            {/* Left — document */}
            <div style={{ display: "flex", flexDirection: "column", padding: "20px 24px", overflowY: "auto", borderRight: `1px solid ${t.border}` }}>
                {/* Doc header */}
                <div style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14,
                    padding: "12px 16px", background: t.card, borderRadius: 12, border: `1px solid ${t.border}`
                }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div style={{
                            width: 34, height: 34, borderRadius: 9, background: t.primaryGlow,
                            display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18
                        }}>📄</div>
                        <div>
                            <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>{doc.title}</div>
                            <div style={{ fontSize: 11, color: t.textMuted, marginTop: 1 }}>
                                {doc.type}{doc.textEdited ? " (wording edited by client)" : ""} · <CaseLink doc={doc} t={t} /> · {doc.client}
                            </div>
                        </div>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <StatusPill status={doc.status} t={t} />
                    </div>
                </div>

                {/* Document — the REAL generated PDF, rendered inline. */}
                {viewRev && (
                    <div style={{ marginBottom: 10, padding: "9px 13px", borderRadius: 10, background: "rgba(255,200,87,0.10)", border: "1px solid rgba(255,200,87,0.35)", fontSize: 11.5, color: t.textDim, display: "flex", alignItems: "center", gap: 10 }}>
                        <span style={{ flex: 1 }}>
                            Reading an earlier draft (v{viewRev.version}). Your decision still
                            applies to the version the client submitted.
                        </span>
                        <button onClick={() => setViewRev(null)}
                            style={{ background: "transparent", border: `1px solid ${t.border}`, borderRadius: 8, padding: "5px 11px", fontSize: 11, fontWeight: 700, color: t.text, cursor: "pointer", whiteSpace: "nowrap", fontFamily: "inherit" }}>
                            Back to submitted
                        </button>
                    </div>
                )}

                <div style={{
                    background: "#fff", borderRadius: 12, border: `1px solid ${t.border}`,
                    overflow: "hidden", flex: 1, minHeight: 460
                }}>
                    {previewUrl ? (
                        <iframe title="Document under review" src={previewUrl}
                            style={{ width: "100%", height: 520, border: "none", display: "block" }} />
                    ) : (
                        <div style={{ padding: 40, textAlign: "center", color: t.textMuted, fontSize: 13, minHeight: 460, display: "flex", alignItems: "center", justifyContent: "center" }}>
                            Loading the submitted document…
                        </div>
                    )}
                </div>

                {/* Export bar */}
                <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                    <DownloadPdfButton doc={doc} t={t} style={{
                        padding: "9px 0", borderRadius: 9,
                        border: `1px solid ${t.primary}50`, background: t.card, color: t.primary,
                        fontSize: 11, cursor: "pointer", fontFamily: "inherit", fontWeight: 600
                    }} />
                </div>
            </div>

            {/* Right — compliance + client note */}
            <div style={{ display: "flex", flexDirection: "column", gap: 14, padding: "20px 18px", overflowY: "auto" }}>

                <RevisionHistory
                    docId={doc.id} t={t} reloadKey={doc.viewRevisionId}
                    currentRevisionId={viewRev?.revision_id || doc.viewRevisionId}
                    onPreview={rev => setViewRev(
                        rev.revision_id === doc.viewRevisionId ? null : rev)} />

                {/* Client note */}
                {doc.note && (
                    <div style={{
                        background: `rgba(255,200,87,0.08)`, border: `1px solid rgba(255,200,87,0.3)`,
                        borderRadius: 12, padding: "12px 14px"
                    }}>
                        <div style={{ fontSize: 11, fontWeight: 700, color: "#FFC857", marginBottom: 4 }}>📝 Client Note</div>
                        <div style={{ fontSize: 12, color: t.textDim, lineHeight: 1.6 }}>{doc.note}</div>
                    </div>
                )}

                {doc?.textEdited && (
                    <div data-wording-edited-notice style={{ background: t.card, border: "1px solid rgba(255,200,87,0.45)", borderRadius: 12, padding: "14px 16px" }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 3 }}>
                            Wording edited by the client
                        </div>
                        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 6, lineHeight: 1.6 }}>
                            This document began as a {doc.type} template, but the client edited
                            its text. It is not the template's reviewed wording. Required
                            particulars were not checked on it; read the whole text.
                        </div>
                    </div>
                )}

                {fieldShape?.unknown?.length > 0 && (
                    <div style={{ background: t.card, border: "1px solid rgba(255,200,87,0.45)", borderRadius: 12, padding: "14px 16px" }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 3 }}>
                            Answers not in this document
                        </div>
                        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 6, lineHeight: 1.6 }}>
                            The client supplied {fieldShape.unknown.join(", ")}, which this
                            template has no field for. Those values are NOT in the draft you
                            are reading, and the client has no reason to know that.
                        </div>
                    </div>
                )}

                {/* Statutory completeness — real, from pleading_rules at generation */}
                <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 12, padding: "14px 16px" }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 3 }}>
                        Required particulars
                    </div>
                    {!compliance?.checked ? (
                        // Not "all clear" — the check genuinely does not cover this
                        // template. Saying so beats an empty panel that reads as a pass.
                        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 6 }}>
                            No completeness rules apply to this document type. Nothing was checked.
                        </div>
                    ) : (
                        <>
                            <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 9 }}>
                                Checked against {compliance.basis}
                            </div>
                            <div style={{
                                fontSize: 12, fontWeight: 700, marginBottom: 8,
                                color: compliance.complete ? "#4DD4A3" : "#FFC857"
                            }}>
                                {compliance.complete
                                    ? "Contains every particular the Code requires"
                                    : `${compliance.missing} required particular${compliance.missing === 1 ? "" : "s"} missing`}
                            </div>
                            {(compliance.items || []).filter(i => i.status === "missing").map(i => (
                                <div key={i.clause} style={{ marginBottom: 7, paddingLeft: 9, borderLeft: "2px solid rgba(255,200,87,0.35)" }}>
                                    <div style={{ fontSize: 11.5, fontWeight: 600, color: t.textDim }}>
                                        {i.clause} — {i.requirement}
                                    </div>
                                    <div style={{ fontSize: 10.5, color: t.textMuted, marginTop: 2 }}>{i.hint}</div>
                                </div>
                            ))}
                        </>
                    )}
                </div>

                {/* Citation verification. The lawyer signing this is the one who
                    carries the cost of a bad citation, so the panel leads with what
                    could NOT be confirmed rather than with a count of successes.
                    No tick: this checks existence only, never whether an authority
                    supports the proposition it is cited for. */}
                <div style={{
                    background: t.card, borderRadius: 12, padding: "14px 16px",
                    border: `1px solid ${(verification?.counts?.not_in_corpus > 0 || verification?.counts?.omitted > 0) ? "rgba(217,54,84,0.45)" : t.border}`
                }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 3 }}>
                        Authorities cited
                    </div>

                    {/* Shown OUTSIDE the ran/total branches below: the reviewer needs the
                        scope statement whether or not the checker ran, and whether or not
                        the draft cites anything. Shipped from backend/app/core/claims.py so
                        this panel and the client's cannot promise different things. */}
                    {verification?.scope && (
                        <div style={{ fontSize: 10, color: t.textMuted, marginBottom: 9,
                            paddingBottom: 8, borderBottom: `1px solid ${t.border}`, lineHeight: 1.5 }}>
                            {verification.scope}
                        </div>
                    )}

                    {!verification ? (
                        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 6 }}>
                            This document predates citation checking. Its authorities were
                            never verified — check each one before filing.
                        </div>
                    ) : verification.ran === false ? (
                        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 6 }}>
                            {verification.summary}
                        </div>
                    ) : verification.counts?.total === 0 ? (
                        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 6 }}>
                            No authority is cited anywhere in this draft.
                        </div>
                    ) : (
                        <>
                            <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 9 }}>
                                {verification.counts.verified} found in the corpus ·{" "}
                                {verification.counts.omitted > 0 && (
                                    <>{verification.counts.omitted} REPEALED · </>
                                )}
                                {verification.counts.unverifiable} cannot be checked here
                            </div>
                            {(verification.checks || [])
                                .filter(c => c.status !== "VERIFIED")
                                .map((c, i) => (
                                    <div key={`${c.canonical}-${i}`} style={{
                                        marginBottom: 8, paddingLeft: 9,
                                        borderLeft: `2px solid ${(c.status === "NOT_IN_CORPUS" || c.status === "OMITTED") ? "rgba(217,54,84,0.5)" : "rgba(150,150,150,0.35)"}`
                                    }}>
                                        <div style={{
                                            fontSize: 11.5, fontWeight: 600,
                                            color: (c.status === "NOT_IN_CORPUS" || c.status === "OMITTED") ? "#FF6B7A" : t.textDim
                                        }}>
                                            {c.canonical}
                                            <span style={{ fontWeight: 500, color: t.textMuted }}>
                                                {c.status === "OMITTED" ? " — REPEALED"
                                                    : c.status === "NOT_IN_CORPUS" ? " — not found"
                                                        : " — cannot verify"}
                                            </span>
                                        </div>
                                        <div style={{ fontSize: 10.5, color: t.textMuted, marginTop: 2 }}>{c.detail}</div>
                                    </div>
                                ))}
                            <div style={{ fontSize: 10, color: t.textMuted, marginTop: 6, fontStyle: "italic" }}>
                                Existence only — a real provision cited for something it does
                                not say still shows as found.
                            </div>
                        </>
                    )}
                </div>

                {/* Document meta */}
                <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 12, padding: "14px 16px" }}>
                    <div style={{
                        fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase",
                        letterSpacing: "0.07em", marginBottom: 10
                    }}>Document Info</div>
                    {[
                        ["Type", doc.type],
                        ["Case Ref", doc.caseRawId ? doc.caseId : "None — standalone document"],
                        ["Client", doc.client],
                        ["Category", doc.caseCategory],
                        ["Submitted", doc.submitted],
                        ["Urgency", doc.urgency],
                    ].map(([k, v]) => (
                        <div key={k} style={{
                            display: "flex", justifyContent: "space-between", padding: "5px 0",
                            borderBottom: `1px solid ${t.border}25`
                        }}>
                            <span style={{ fontSize: 11, color: t.textFaint }}>{k}</span>
                            <span style={{ fontSize: 11, fontWeight: 600, color: k === "Urgency" ? URGENCY_COLOR[v] : t.textDim }}>{v}</span>
                        </div>
                    ))}
                </div>

                {/* Notes for the client are written on the decision screen, where
                    approve / return / reject send them. A notes box here was never
                    read or sent, so it is gone. */}

                {/* Continue to decision — only documents awaiting review can be decided */}
                {doc.status === "Pending Review" ? (
                    <Btn full onClick={onContinue}>⚖️ Proceed to Decision →</Btn>
                ) : (
                    <div style={{ padding: "10px 14px", borderRadius: 10, background: t.card, border: `1px solid ${t.border}`, fontSize: 12, color: t.textMuted, textAlign: "center" }}>
                        Decision recorded: <span style={{ fontWeight: 700, color: t.text }}>{doc.status}</span>
                        {doc.lawyerNote ? <div style={{ marginTop: 6, fontStyle: "italic" }}>“{doc.lawyerNote}”</div> : null}
                    </div>
                )}
                <Btn full variant="secondary" onClick={onBack}>← Back to Inbox</Btn>
            </div>
        </div>
    );
}

// ═══════════════════════════════════════════════════════════════
// SCREEN 3 — APPROVE / EDIT / REJECT
// Lawyer makes final decision — mirrors client "Submit to Lawyer"
// but reversed: lawyer is the one deciding
// ═══════════════════════════════════════════════════════════════
function ScreenDecision({ doc, t, onBack, onDecide, busy }) {
    const [decision, setDecision] = useState(null); // null | "approve" | "edit" | "reject"
    const [editNotes, setEditNotes] = useState("");
    const [rejectReason, setRejectReason] = useState("");
    const [returnNote, setReturnNote] = useState("");

    return (
        <div className="rgrid" style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 320px", gap: 0, overflow: "hidden" }}>

            {/* Left — decision actions */}
            <div style={{ padding: "22px 26px", overflowY: "auto", borderRight: `1px solid ${t.border}` }}>

                {/* Doc reference banner */}
                <div style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "12px 16px", background: t.card, borderRadius: 12, border: `1px solid ${t.border}`, marginBottom: 20
                }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <span style={{ fontSize: 20 }}>📄</span>
                        <div>
                            <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>{doc.title}</div>
                            <div style={{ fontSize: 11, color: t.textMuted }}>{doc.client} · <CaseLink doc={doc} t={t} /></div>
                        </div>
                    </div>
                    <span style={{
                        fontSize: 11, padding: "3px 10px", borderRadius: 20,
                        background: "rgba(90,179,255,0.15)", color: "#5AB3FF", border: "1px solid rgba(90,179,255,0.3)",
                        fontWeight: 700
                    }}>{doc.status}</span>
                </div>

                <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 4 }}>⚖️ Your Decision</div>
                <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 18 }}>Select an action for this document</div>

                {/* Decision cards */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16, marginBottom: 28 }}>
                    {[
                        { id: "approve", icon: "✅", label: "Approve & Sign", desc: "Document is legally sound", color: "#4DD4A3", bg: "rgba(77,212,163,0.1)", border: "rgba(77,212,163,0.3)" },
                        { id: "edit", icon: "✏️", label: "Edit & Return", desc: "Return with corrections", color: "#FFC857", bg: "rgba(255,200,87,0.1)", border: "rgba(255,200,87,0.3)" },
                        { id: "reject", icon: "❌", label: "Reject", desc: "Document cannot proceed", color: "#FF6B7A", bg: "rgba(255,107,122,0.1)", border: "rgba(255,107,122,0.3)" },
                    ].map(opt => (
                        <div key={opt.id} onClick={() => setDecision(opt.id)}
                            style={{
                                padding: "20px 16px", borderRadius: 12, cursor: "pointer",
                                border: `2px solid ${decision === opt.id ? opt.color : t.border}`,
                                background: decision === opt.id ? opt.bg : t.card,
                                transition: "all .18s", textAlign: "center",
                                minHeight: 140, display: "flex", flexDirection: "column", justifyContent: "center"
                            }}>
                            <div style={{ fontSize: 28, marginBottom: 10 }}>{opt.icon}</div>
                            <div style={{ fontSize: 13, fontWeight: 700, color: decision === opt.id ? opt.color : t.text, marginBottom: 6 }}>{opt.label}</div>
                            <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.4 }}>{opt.desc}</div>
                        </div>
                    ))}
                </div>

                {/* Conditional forms */}
                {decision === "approve" && (
                    <div style={{ background: t.card, border: `1px solid rgba(77,212,163,0.3)`, borderRadius: 12, padding: "20px" }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: "#4DD4A3", marginBottom: 16 }}>✅ Approval Details</div>
                        <div style={{ marginBottom: 16 }}>
                            <div style={{ fontSize: 10, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>Approval Note to Client (optional)</div>
                            <Input type="textarea" rows={3} value={editNotes} onChange={e => setEditNotes(e.target.value)}
                                placeholder="e.g. Document approved. Please file within 7 working days..." />
                        </div>
                        <Btn full variant="success" disabled={busy} onClick={() => onDecide("approve", editNotes.trim() || null)}>
                            {busy ? "Sending…" : "✅ Confirm Approval & Notify Client"}
                        </Btn>
                    </div>
                )}

                {decision === "edit" && (
                    <div style={{ background: t.card, border: `1px solid rgba(255,200,87,0.3)`, borderRadius: 12, padding: "20px" }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: "#FFC857", marginBottom: 16 }}>✏️ Edit Instructions</div>
                        <div style={{ marginBottom: 16 }}>
                            <div style={{ fontSize: 10, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>Required Changes</div>
                            <Input type="textarea" rows={4} value={returnNote} onChange={e => setReturnNote(e.target.value)}
                                placeholder="e.g. Please update para 2 with correct termination date, add CNIC number in plaintiff details..." />
                        </div>
                        <Btn full variant="warn" disabled={busy} onClick={() => onDecide("return", returnNote.trim() || null)}>
                            {busy ? "Sending…" : "↩ Return to Client with Notes"}
                        </Btn>
                    </div>
                )}

                {decision === "reject" && (
                    <div style={{ background: t.card, border: `1px solid rgba(255,107,122,0.3)`, borderRadius: 12, padding: "20px" }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: "#FF6B7A", marginBottom: 16 }}>❌ Rejection Reason</div>
                        <div style={{ marginBottom: 16 }}>
                            <div style={{ fontSize: 10, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>Reason (required)</div>
                            <Input type="textarea" rows={4} value={rejectReason} onChange={e => setRejectReason(e.target.value)}
                                placeholder="e.g. Document contains factual inaccuracies and cannot proceed in current state..." />
                        </div>
                        <Btn full variant="danger" disabled={busy || !rejectReason.trim()} onClick={() => onDecide("reject", rejectReason.trim())}>
                            {busy ? "Sending…" : "❌ Confirm Rejection"}
                        </Btn>
                    </div>
                )}
            </div>

            {/* Right — document summary + actions */}
            <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: "22px 18px", overflowY: "auto" }}>

                {/* Client & urgency */}
                <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 12, padding: "16px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
                        <Avatar name={doc.client} size={40} t={t} />
                        <div>
                            <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>{doc.client}</div>
                            <div style={{ fontSize: 11, color: t.textMuted }}>{doc.caseCategory} · {doc.type}</div>
                        </div>
                    </div>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                        <UrgencyBadge urgency={doc.urgency} />
                        <StatusPill status={doc.status} t={t} />
                    </div>
                </div>

                {/* Client note */}
                {doc.note && (
                    <div style={{ background: `rgba(255,200,87,0.08)`, border: `1px solid rgba(255,200,87,0.3)`, borderRadius: 12, padding: "12px 14px" }}>
                        <div style={{ fontSize: 11, fontWeight: 700, color: "#FFC857", marginBottom: 4 }}>📝 Client Note</div>
                        <div style={{ fontSize: 12, color: t.textDim, lineHeight: 1.6 }}>{doc.note}</div>
                    </div>
                )}

                {/* Response timeline */}
                <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 12, padding: "16px" }}>
                    <div style={{
                        fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase",
                        letterSpacing: "0.07em", marginBottom: 12
                    }}>⏱ Response SLA</div>
                    {[
                        { l: "Normal", t2: "No rush", extra: "", sel: doc.urgency === "Normal" },
                        { l: "Priority", t2: "Needed soon", extra: "", sel: doc.urgency === "Priority" },
                        { l: "Urgent", t2: "Time-critical", extra: "", sel: doc.urgency === "Urgent" },
                    ].map(s => (
                        <div key={s.l} style={{
                            display: "flex", justifyContent: "space-between", alignItems: "center",
                            padding: "8px 12px", borderRadius: 8, marginBottom: 6,
                            border: `1px solid ${s.sel ? t.primary : t.border}`,
                            background: s.sel ? t.primaryGlow : "transparent"
                        }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <div style={{
                                    width: 7, height: 7, borderRadius: "50%",
                                    background: s.sel ? t.primary : t.textFaint
                                }} />
                                <span style={{ fontSize: 12, color: s.sel ? t.primary : t.textDim, fontWeight: s.sel ? 700 : 400 }}>{s.l}</span>
                            </div>
                            <div style={{ textAlign: "right" }}>
                                <div style={{ fontSize: 10, color: t.textFaint }}>{s.t2}</div>
                                {s.extra && <div style={{ fontSize: 9, color: t.warn }}>{s.extra}</div>}
                            </div>
                        </div>
                    ))}
                </div>

                <Btn full variant="secondary" onClick={onBack}>← Back</Btn>
            </div>
        </div>
    );
}

// ═══════════════════════════════════════════════════════════════
// SCREEN 5 — FINAL & EXPORT
// Mirrors client Screen 4 exactly — final document view
// ═══════════════════════════════════════════════════════════════
// complianceSummary tone → colour. Neutral is not green: "not checked" is not a pass.
const _PARTICULARS_COLOR = (t) => ({ success: t.success, warn: "#FFC857", neutral: t.textMuted });

function ScreenFinal({ doc, t, onBack }) {
    const { user } = useAuth();
    const lawyerName = user?.full_name || "Advocate";
    const particulars = complianceSummary(doc?.compliance);
    const approvedOn = doc?.reviewedAt
        ? new Date(doc.reviewedAt).toLocaleDateString("en-GB") : null;
    const [previewUrl, setPreviewUrl] = useState(null);
    // PINNED TO THE REVISION UNDER REVIEW, not to "the current file".
    //
    // The legacy path fetched whatever the document currently was, so a client
    // who regenerated after submitting would have the lawyer reading the NEW
    // bytes while deciding on the submitted ones — and the decision guard would
    // then refuse, with no explanation of what they had actually been looking
    // at. Naming the submitted revision keeps the page and the decision on the
    // same object.
    //
    // The old cleanup also leaked: it revoked `url`, a local still null when
    // the fetch resolved after unmount, while the object URL had already been
    // created inside the helper. A late arrival is revoked on arrival now.
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
    return (
        <div className="rgrid" style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 300px", gap: 0, overflow: "hidden" }}>

            {/* Left — final document */}
            <div style={{ padding: "22px 26px", overflowY: "auto", borderRight: `1px solid ${t.border}` }}>
                {/* Doc header */}
                <div style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "12px 16px", background: t.card, borderRadius: 12, border: `1px solid ${t.border}`, marginBottom: 16
                }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div style={{
                            width: 34, height: 34, borderRadius: 9, background: "rgba(64,240,220,0.15)",
                            display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18
                        }}>📜</div>
                        <div>
                            <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Final Legal Document</div>
                            <div style={{ fontSize: 11, color: t.textMuted }}>{doc.caseCategory} Dispute</div>
                        </div>
                    </div>
                    <span style={{
                        fontSize: 11, padding: "3px 10px", borderRadius: 20,
                        background: t.primaryGlow, color: t.primary, border: `1px solid ${t.primary}40`, fontWeight: 700
                    }}>
                        ✦ Final
                    </span>
                </div>

                {/* Document — the REAL approved PDF, rendered inline. */}
                <div style={{
                    background: "#fff", borderRadius: 12, border: `1px solid ${t.border}`,
                    overflow: "hidden", marginBottom: 16, minHeight: 420
                }}>
                    {previewUrl ? (
                        <iframe title="Approved document" src={previewUrl}
                            style={{ width: "100%", height: 460, border: "none", display: "block" }} />
                    ) : (
                        <div style={{ padding: 40, textAlign: "center", color: t.textMuted, fontSize: 13, minHeight: 420, display: "flex", alignItems: "center", justifyContent: "center" }}>Loading the approved document…</div>
                    )}
                    {/* Footer */}
                    <div style={{
                        padding: "12px 24px", borderTop: `1px solid ${t.border}`,
                        display: "flex", justifyContent: "space-between", alignItems: "center"
                    }}>
                        <span style={{ fontSize: 11, color: t.textFaint }}>🖊 Approved by Lawyer · {lawyerName}</span>
                        {/* When the decision was RECORDED — not today's date,
                            which is what this used to print. */}
                        <span style={{ fontSize: 11, color: t.textFaint }}>📅 {approvedOn || "Date not recorded"}</span>
                    </div>
                </div>

                {/* Export. PDF / Email / Print had no handlers and did nothing;
                    only the revision-bound download is real, so only it is shown. */}
                <div style={{ display: "flex", gap: 8 }}>
                    <DownloadPdfButton doc={doc} t={t} style={{
                        padding: "10px 0", borderRadius: 10,
                        border: `1px solid ${t.primary}50`, background: t.card, color: t.primary,
                        fontSize: 11, cursor: "pointer", fontFamily: "inherit", fontWeight: 600
                    }} />
                </div>
            </div>

            {/* Right — summary */}
            <div style={{ display: "flex", flexDirection: "column", gap: 12, padding: "22px 18px", overflowY: "auto" }}>

                {/* Complete card */}
                <div style={{
                    background: "linear-gradient(135deg,rgba(64,240,220,0.12),rgba(77,212,163,0.1))",
                    border: `1px solid ${t.primary}30`, borderRadius: 12, padding: "18px 16px", textAlign: "center"
                }}>
                    <div style={{ fontSize: 32, marginBottom: 8 }}>🎉</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: t.primary, marginBottom: 4 }}>Document Complete</div>
                    <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 10 }}>Reviewed and approved by you</div>
                    <span style={{
                        fontSize: 11, padding: "3px 10px", borderRadius: 20,
                        background: t.primaryGlow, color: t.primary, border: `1px solid ${t.primary}40`, fontWeight: 700
                    }}>
                        ✦ Final Version
                    </span>
                </div>

                {/* Summary */}
                <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 12, padding: "14px 16px" }}>
                    <div style={{
                        fontSize: 10, fontWeight: 700, color: t.textFaint, textTransform: "uppercase",
                        letterSpacing: "0.07em", marginBottom: 10
                    }}>Document Summary</div>
                    {[
                        ["Type", doc.type],
                        ["Template", doc.title.split(" — ")[0]],
                        ["Case Ref", doc.caseRawId ? doc.caseId : "None — standalone document"],
                        ["Client", doc.client],
                        ["Reviewer", `${lawyerName}, Advocate`],
                        ["Status", "Final"],
                        // What pleading_rules found, frozen at generation. Your
                        // approval is not a statutory check and is not shown as one.
                        ["Required particulars", particulars.label],
                    ].map(([k, v]) => (
                        <div key={k} style={{
                            display: "flex", justifyContent: "space-between", padding: "5px 0",
                            borderBottom: `1px solid ${t.border}20`
                        }}>
                            <span style={{ fontSize: 11, color: t.textFaint }}>{k}</span>
                            <span style={{
                                fontSize: 11, fontWeight: 600,
                                color: k === "Status" ? t.primary
                                    : k === "Required particulars" ? _PARTICULARS_COLOR(t)[particulars.tone]
                                    : t.textDim
                            }}>{v}</span>
                        </div>
                    ))}
                </div>

                {/* Workflow complete */}
                <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 12, padding: "14px 16px" }}>
                    <div style={{
                        fontSize: 10, fontWeight: 700, color: t.textFaint, textTransform: "uppercase",
                        letterSpacing: "0.07em", marginBottom: 10
                    }}>Workflow Complete</div>
                    {[
                        "Document Received",
                        "AI Draft Generated",
                        "Lawyer Review",
                        "Decision: Approved",
                        "Client Notified",
                        "Final Export Ready",
                    ].map((item, i) => (
                        <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 0" }}>
                            <div style={{
                                width: 18, height: 18, borderRadius: "50%",
                                background: `${t.primary}20`, border: `1.5px solid ${t.primary}60`,
                                display: "flex", alignItems: "center", justifyContent: "center",
                                fontSize: 9, color: t.primary, flexShrink: 0
                            }}>✓</div>
                            <span style={{ fontSize: 11, color: t.textDim }}>{item}</span>
                        </div>
                    ))}
                </div>

                <Btn full variant="secondary" onClick={onBack}>← Back to Inbox</Btn>
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

    const openDoc = (doc) => { setActiveDoc(doc); setScreen(doc.status === "Approved" ? "final" : "review"); };
    const reset = () => { setScreen("inbox"); setActiveDoc(null); };

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
    // The latest load, for listeners registered once.
    const loadRef = useRef(load);
    loadRef.current = load;
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
    const handleDecide = async (action, note, key = null) => {
        const idemKey = key || idempotencyKey();
        setBusy(true);

        const canUseV2 = activeDoc.submittedVersion != null
            && !!activeDoc.submittedPdfSha256;
        const { data, error, status } = canUseV2
            ? await reviewDocumentV2(activeDoc.id, {
                action,
                expectedVersion: activeDoc.submittedVersion,
                expectedPdfSha256: activeDoc.submittedPdfSha256,
                note,
            }, idemKey)
            : await reviewDocument(activeDoc.id, { action, note });
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
            if (status === 409 || code === "conflict" || code === "stale_revision") {
                setStaleWarning(
                    "This document changed after you opened it. Reload the queue "
                    + "and review the latest version before deciding.");
                return;
            }
            if (status === 503) {
                // The work may or may not have been recorded, which is exactly
                // what the key is for — the retry reuses it.
                setRetry({ action, note, key: idemKey });
                showToast("⏳ The service is busy. Retry when ready.");
                return;
            }
            // 422 and everything else: the server's own words. It sends a
            // machine-readable message precisely so this does not have to
            // invent one.
            showToast("❌ " + (error.message || "Failed to record decision"));
            return;
        }

        const newLabel = _REVIEW_STATUS_LABEL[data?.review_status] ||
            (action === "approve" ? "Approved" : action === "return" ? "Returned" : "Rejected");
        setDocs(prev => prev.map(d => d.id === activeDoc.id ? { ...d, status: newLabel, lawyerNote: note || "" } : d));
        showToast(`✅ ${newLabel} — the client has been notified`);
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

            {screen !== "inbox" && <Stepper step={screen} t={t} />}

            {screen === "inbox" && <ScreenInbox t={t} onOpen={openDoc} docs={docs}
                loading={loading} hasMore={!!queueCursor} loadingMore={loadingMore}
                onLoadMore={() => load(queueCursor)}
                statusF={statusF} onStatusChange={changeTab}
                counts={queueCounts} serverFiltered={serverFiltered} />}
            {screen === "review" && activeDoc && (
                <ScreenReview doc={activeDoc} t={t}
                    onBack={() => setScreen("inbox")}
                    onContinue={() => setScreen("decision")} />
            )}
            {screen === "decision" && activeDoc && (
                <ScreenDecision doc={activeDoc} t={t} busy={busy}
                    onBack={() => setScreen("review")}
                    onDecide={handleDecide} />
            )}
            {screen === "final" && activeDoc && (
                <ScreenFinal doc={activeDoc} t={t} onBack={reset} />
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
                        onClick={() => handleDecide(retry.action, retry.note, retry.key)}
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
