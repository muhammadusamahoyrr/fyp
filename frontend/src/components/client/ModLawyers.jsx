'use client';
import React, { useState, useEffect, useMemo, useRef } from "react";
import dynamic from "next/dynamic";
import { createPortal } from "react-dom";
import { useSearchParams, useRouter as useNextRouter } from "next/navigation";
import { useT } from "./theme.js";
import { useCase } from "./CaseContext.jsx";
import { useToast } from "@/components/shared/Toast.jsx";
import Ic from "./Ic.jsx";
import { readProblem, PROBLEM_MAX_LENGTH } from "@/lib/problemFilters";
import { DOCS_FONT } from "./documents/ui.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput, Badge } from "@/components/shared/shared.jsx";
import { searchLawyers, matchLawyers, submitReview, getLawyerReviews, bookAppointment, getBookableSlots, listCases, listHireConsultations, listEngagements, requestEngagement, cancelEngagement, acceptEngagementTerms, declineEngagementTerms, completeEngagement, terminateEngagement } from "@/lib/api.js";
import { useAuth } from "@/context/AuthContext.jsx";
import { hireableCases as hireable, isDraftCase } from "@/lib/caseStatus.js";
import { onNotification } from "@/lib/notificationTarget.js";
import { listAllCases } from "@/lib/allCases.js";
import { readIntakeValue } from "@/lib/intakeStorage.js";
import { pktToday, pktSlotToUtcISO, isPktSlotPast } from "@/lib/bookingTime.js";
import { createBookingKeyHolder } from "@/lib/bookingIdempotency.js";

const LeafletMap = dynamic(() => import("./LeafletMap"), {
    ssr: false,
    loading: () => (
        <div style={{ height: 340, display: "flex", alignItems: "center", justifyContent: "center", color: "#6b7280", fontSize: 13 }}>
            Loading map…
        </div>
    ),
});

// Province and case-type mappings for server-side filter requests
const CITY_TO_PROVINCE = {
    lahore: "punjab", rawalpindi: "punjab", multan: "punjab", faisalabad: "punjab",
    karachi: "sindh", hyderabad: "sindh",
    islamabad: "federal",
    peshawar: "kpk",
    quetta: "balochistan",
    punjab: "punjab", sindh: "sindh", kpk: "kpk", balochistan: "balochistan", federal: "federal",
};
// Directory page size.
const PAGE_SIZE = 20;

/* ══════════════════════════════════════════════════════
   MODULE: LAWYER DISCOVERY
══════════════════════════════════════════════════════ */
// Engagements still being negotiated, by case. The server treats both of
// these as open and refuses a second request on the case (ENGAGEMENT_OPEN_
// STATUSES); counting only `requested` offered a case with terms on the table.
const OPEN_ENGAGEMENT = new Set(["requested", "terms_proposed"]);
function openByCase(engagements) {
    const m = {};
    (engagements || []).filter(e => OPEN_ENGAGEMENT.has(e.status)).forEach(e => { m[e.case_id] = e; });
    return m;
}

/* The directory toolbar's look (2026-10-10), scoped by [data-lawyers-tools];
 * colours are the client tokens (clientTheme.js). */
const LAWYERS_TOOLS_CSS = `[data-lawyers-tools] .lt-search{flex:1 1 360px;display:flex;align-items:center;gap:10px;height:48px;padding:0 14px;box-sizing:border-box;border-radius:12px;background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow-rest);transition:border-color .15s,box-shadow .15s}
[data-lawyers-tools] .lt-search:hover{box-shadow:0 10px 24px -14px rgba(0,0,0,.75)}
[data-lawyers-tools] .lt-search svg{transition:color .2s,transform .2s}
[data-lawyers-tools] .lt-search:hover>svg:first-child{color:var(--brand-text);transform:scale(1.1)}
[data-lawyers-tools] .lt-search:focus-within{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-lawyers-tools] .lt-search input{flex:1;min-width:0;border:0;outline:none;background:transparent;color:var(--ink);font:inherit;font-size:15px}
[data-lawyers-tools] .lt-search input::placeholder{color:var(--faint)}
[data-lawyers-tools] .lt-search input::-webkit-search-cancel-button{display:none}
[data-lawyers-tools] .lt-kbd{font:500 11px "JetBrains Mono",monospace;color:var(--faint);border:1px solid var(--line-strong);border-bottom-width:2px;border-radius:5px;padding:0 6px;line-height:18px}
[data-lawyers-tools] .lt-clear{background:none;border:0;color:var(--muted);cursor:pointer;font-size:20px;line-height:1}
[data-lawyers-tools] .lt-pill{display:inline-flex;align-items:center;gap:8px;height:40px;padding:0 15px;border-radius:999px;border:1px solid var(--line-strong);background:transparent;color:var(--ink);font:inherit;font-size:13.5px;font-weight:600;white-space:nowrap;cursor:pointer;transition:background .15s,border-color .15s,box-shadow .2s,transform .15s}
[data-lawyers-tools] .lt-pill:hover{background:var(--hover);transform:translateY(-1px);box-shadow:0 8px 18px -12px rgba(0,0,0,.7)}
[data-lawyers-tools] .lt-pill:active{transform:scale(.97)}
[data-lawyers-tools] .lt-pill[data-open]{border-color:var(--hover-line);background:var(--hover-tint)}
[data-lawyers-tools] .lt-pill>svg:first-child{transition:transform .25s cubic-bezier(.3,1.4,.5,1)}
[data-lawyers-tools] .lt-pill[aria-expanded]:hover>svg:first-child{transform:scaleX(.78)}
[data-lawyers-tools] .lt-sort:not([data-open]) .lt-pill:hover .chev{transform:translateY(2px)}
[data-lawyers-tools] .lt-pill .muted{color:var(--faint);font-weight:500}
[data-lawyers-tools] .lt-accepting{border-color:color-mix(in srgb,var(--brand-text) 30%,transparent);background:color-mix(in srgb,var(--brand-text) 8%,transparent)}
[data-lawyers-tools] .lt-accepting[aria-pressed="true"]{border-color:color-mix(in srgb,var(--brand-text) 60%,transparent);background:color-mix(in srgb,var(--brand-text) 18%,transparent);box-shadow:0 0 0 3px color-mix(in srgb,var(--brand-text) 12%,transparent)}
[data-lawyers-tools] .lt-accepting .dot{width:8px;height:8px;border-radius:50%;background:var(--brand-text);box-shadow:0 0 8px var(--brand-text);opacity:.55;transition:opacity .15s}
[data-lawyers-tools] .lt-accepting[aria-pressed="true"] .dot{opacity:1}
[data-lawyers-tools] .lt-accepting:hover{background:color-mix(in srgb,var(--brand-text) 16%,transparent)}
[data-lawyers-tools] .lt-accepting:hover .dot{opacity:1;animation:ltPulse 1.1s ease-out infinite}
@keyframes ltPulse{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--brand-text) 70%,transparent)}100%{box-shadow:0 0 0 7px transparent}}
[data-lawyers-tools] .lt-count{min-width:20px;height:20px;padding:0 5px;box-sizing:border-box;border-radius:999px;display:grid;place-items:center;background:var(--teal-ink);color:var(--on-teal);font-size:11.5px;font-weight:700}
[data-lawyers-tools] .lt-sort{position:relative}
[data-lawyers-tools] .lt-icon{width:40px;height:40px;flex:none;border-radius:11px;border:1px solid var(--line-strong);background:transparent;color:var(--ink);display:grid;place-items:center;cursor:pointer;transition:background .15s,border-color .15s,color .15s}
[data-lawyers-tools] .lt-icon:hover{background:var(--hover-tint);color:var(--hover-ink)}
[data-lawyers-tools] .lt-icon[data-open],[data-lawyers-tools] .lt-icon[aria-pressed="true"]{border-color:var(--hover-line);background:var(--hover-tint);color:var(--hover-ink)}
[data-lawyers-tools] .lt-sort .chev{transition:transform .15s}
[data-lawyers-tools] .lt-sort[data-open] .chev{transform:rotate(180deg)}
[data-lawyers-tools] .lt-menu{position:absolute;right:0;top:calc(100% + 8px);z-index:30;min-width:220px;padding:4px;border-radius:12px;background:var(--surface);border:1px solid var(--line-strong);box-shadow:0 18px 36px -12px rgba(0,0,0,.6)}
[data-lawyers-tools] .lt-menu button{display:flex;align-items:center;gap:8px;width:100%;padding:8px 10px;border:0;border-radius:8px;background:none;color:var(--ink);font:inherit;font-size:13px;font-weight:500;text-align:left;cursor:pointer}
[data-lawyers-tools] .lt-menu button[data-hot]{background:var(--hover-tint);color:var(--hover-ink)}
[data-lawyers-tools] .lt-menu button[aria-selected="true"]{color:var(--brand-text);font-weight:600}
[data-lawyers-tools].lt-areas{scrollbar-width:none;-ms-overflow-style:none;padding:2px 0}
[data-lawyers-tools].lt-areas::-webkit-scrollbar{display:none}
[data-lawyers-tools] .lt-area{flex:none;display:inline-flex;align-items:center;gap:8px;height:36px;padding:0 13px;border-radius:999px;border:1px solid transparent;background:var(--surface);color:var(--ink);font:inherit;font-size:13.5px;font-weight:600;white-space:nowrap;cursor:pointer;transition:background .15s,border-color .15s,transform .12s}
[data-lawyers-tools] .lt-area:hover{background:color-mix(in srgb,var(--c,var(--brand-text)) 16%,var(--surface))}
[data-lawyers-tools] .lt-area:hover .dot{transform:scale(1.35);box-shadow:0 0 8px var(--c)}
[data-lawyers-tools] .lt-area:active{transform:scale(.96)}
[data-lawyers-tools] .lt-area[aria-pressed="true"]{border-color:color-mix(in srgb,var(--brand-text) 55%,transparent);background:color-mix(in srgb,var(--brand-text) 14%,var(--surface-2))}
[data-lawyers-tools] .lt-area .dot{width:8px;height:8px;border-radius:50%;background:var(--c);transition:transform .2s cubic-bezier(.3,1.4,.5,1),box-shadow .2s}
[data-lawyers-tools] .lt-radio .rd{width:14px;height:14px;flex:none;border-radius:50%;border:2px solid var(--faint);box-sizing:border-box;transition:border-color .15s,box-shadow .15s}
[data-lawyers-tools] .lt-radio[aria-checked="true"] .rd{border-color:var(--brand-text);box-shadow:inset 0 0 0 3px var(--surface-2),inset 0 0 0 7px var(--brand-text)}
[data-lawyers-tools] .lt-area .n{font-size:12px;font-weight:700;color:var(--faint)}`;

/* Every practice area a lawyer can list on their profile (the server's
 * `specialization` filter, backend PRACTICE_AREAS), each with its colour:
 * [label, value, colour]. "Employment" is the profile's `labour`. */
const AREA_CHIPS = [
    ["Family", "family", "#5EE6B0"], ["Criminal", "criminal", "#FF8A80"], ["Civil", "civil", "#8DB4F0"],
    ["Property", "property", "#E0B48A"], ["Corporate", "corporate", "#B9A6F2"], ["Employment", "labour", "#F2C35E"],
    ["Constitutional", "constitutional", "#6ADDEB"],
    // Banking, tax and cyber stay filterable on the server; not offered here (2026-10-10).
];

// What each server sort is called in the menu.
const SORT_LABEL = {
    "Rating: High to Low": "Top rated", "Rating: Low to High": "Lowest rated",
    "Price: Low to High": "Fee: low to high", "Price: High to Low": "Fee: high to low",
    "Experience: High": "Most experienced", "A–Z": "Name: A–Z", "Z–A": "Name: Z–A",
};

/* "Sort: Top rated" with the app's own menu (arrow keys, Enter, Escape). The
 * real <select> stays, visually hidden, as the value's source of truth. */
function LawyerSort({ value, options, onChange, compact = false }) {
    const [open, setOpen] = useState(false);
    const [hot, setHot] = useState(0);
    const boxRef = useRef(null);
    useEffect(() => {
        if (!open) return undefined;
        const out = e => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
        document.addEventListener("mousedown", out);
        return () => document.removeEventListener("mousedown", out);
    }, [open]);
    const show = () => { setHot(Math.max(0, options.indexOf(value))); setOpen(true); };
    const pick = v => { onChange(v); setOpen(false); };
    const onKey = e => {
        if (!open && ["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) { e.preventDefault(); show(); return; }
        if (!open) return;
        if (e.key === "Escape") { e.preventDefault(); setOpen(false); }
        else if (e.key === "ArrowDown") { e.preventDefault(); setHot(h => Math.min(options.length - 1, h + 1)); }
        else if (e.key === "ArrowUp") { e.preventDefault(); setHot(h => Math.max(0, h - 1)); }
        else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(options[hot]); }
        else if (e.key === "Tab") setOpen(false);
    };
    return (
        <div ref={boxRef} className="lt-sort" data-open={open ? "true" : undefined}>
            <button type="button" className={compact ? "lt-icon" : "lt-pill"} data-open={open ? "true" : undefined} aria-haspopup="listbox" aria-expanded={open}
                aria-label={`Sort: ${SORT_LABEL[value] || value}`} title={compact ? `Sort: ${SORT_LABEL[value] || value}` : undefined}
                onClick={() => (open ? setOpen(false) : show())} onKeyDown={onKey}>
                {compact ? (
                    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M7 4v16M3 8l4-4 4 4M17 20V4M13 16l4 4 4-4" /></svg>
                ) : (<>
                    <span className="muted">Sort:</span> {SORT_LABEL[value] || value}
                    <svg className="chev" width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="var(--faint)" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
                </>)}
            </button>
            <select value={value} onChange={e => onChange(e.target.value)} tabIndex={-1} aria-hidden="true"
                style={{ position: "absolute", width: 1, height: 1, opacity: 0, pointerEvents: "none", overflow: "hidden", clip: "rect(0 0 0 0)" }}>
                {options.map(s => <option key={s}>{s}</option>)}
            </select>
            {open && (
                <div role="listbox" aria-label="Sort lawyers" className="lt-menu">
                    {options.map((s, i) => (
                        <button key={s} type="button" role="option" aria-selected={s === value} data-hot={i === hot ? "true" : undefined}
                            onMouseEnter={() => setHot(i)} onMouseDown={e => e.preventDefault()} onClick={() => pick(s)}>
                            {SORT_LABEL[s] || s}
                            {s === value && <svg style={{ marginLeft: "auto" }} width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5" /></svg>}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}

/* The map view (2026-10-10), scoped by [data-lawyers-map]; client tokens. */
const LAWYERS_MAP_CSS = `[data-lawyers-map]{background:var(--surface-2)}
[data-lawyers-map-page] .lm-pagehead{display:flex;align-items:center;gap:12px;margin:0 0 14px}
[data-lawyers-map-page] .lm-pagehead .lm-title{margin:0;font-family:"Nunito Sans",system-ui,sans-serif;font-size:24px;font-weight:700;color:var(--ink);line-height:1.2}
[data-lawyers-map-page] .lm-pagehead .lm-sub{font-size:13px;color:var(--faint);margin-top:2px}
[data-lawyers-map-page] .lm-back{display:inline-flex;align-items:center;gap:9px;height:42px;padding:0 16px 0 5px;flex:none;border-radius:999px;border:1px solid var(--line);background:var(--surface);color:var(--ink);font:inherit;font-size:13.5px;font-weight:600;cursor:pointer;box-shadow:var(--shadow-rest);transition:background .2s,box-shadow .2s,transform .15s}
[data-lawyers-map-page] .lm-back .ic{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;color:var(--brand-text);background:color-mix(in srgb,var(--brand-text) 15%,transparent);transition:background .2s,color .2s}
[data-lawyers-map-page] .lm-back svg{transition:transform .25s cubic-bezier(.3,1.4,.5,1)}
[data-lawyers-map-page] .lm-back:hover{background:var(--hover);box-shadow:0 10px 22px -14px rgba(0,0,0,.75)}
[data-lawyers-map-page] .lm-back:hover .ic{background:var(--brand-solid);color:var(--on-brand)}
[data-lawyers-map-page] .lm-back:hover svg{transform:translateX(-3px)}
[data-lawyers-map-page] .lm-back:active{transform:scale(.97)}
[data-lawyers-map-page] .lm-toggle{display:inline-flex;align-items:center;gap:9px;height:42px;padding:0 16px 0 5px;border-radius:999px;border:1px solid var(--line);background:var(--surface);color:var(--ink);font:inherit;font-size:13.5px;font-weight:600;cursor:pointer;box-shadow:var(--shadow-rest);transition:background .2s,box-shadow .2s,transform .15s}
[data-lawyers-map-page] .lm-toggle .ic{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;color:var(--muted);background:var(--surface-2);transition:background .2s,color .2s}
[data-lawyers-map-page] .lm-toggle[aria-pressed="true"] .ic{color:var(--brand-text);background:color-mix(in srgb,var(--brand-text) 15%,transparent)}
[data-lawyers-map-page] .lm-toggle .ic svg{transition:transform .3s cubic-bezier(.3,1.4,.5,1)}
[data-lawyers-map-page] .lm-toggle:hover{background:var(--hover);box-shadow:0 10px 22px -14px rgba(0,0,0,.75)}
[data-lawyers-map-page] .lm-toggle:hover .ic{background:var(--brand-solid);color:var(--on-brand)}
[data-lawyers-map-page] .lm-toggle[aria-pressed="true"]:hover .ic svg{transform:translateX(-2px) scaleX(.85)}
[data-lawyers-map-page] .lm-toggle[aria-pressed="false"]:hover .ic svg{transform:translateX(2px) scaleX(1.1)}
[data-lawyers-map-page] .lm-toggle:active{transform:scale(.97)}
[data-lawyers-map-page] .lm-toggle .n{min-width:20px;height:20px;padding:0 6px;box-sizing:border-box;border-radius:999px;display:grid;place-items:center;font-size:11.5px;font-weight:700;color:var(--brand-text);background:color-mix(in srgb,var(--brand-text) 14%,transparent)}
[data-lawyers-map] .lm-panel{position:absolute;left:14px;top:14px;bottom:14px;z-index:600;width:min(320px,calc(100% - 28px));display:flex;flex-direction:column;min-height:0;border-radius:18px;background:color-mix(in srgb,var(--surface) 94%,transparent);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border:1px solid var(--line-strong);box-shadow:0 24px 48px -24px rgba(0,0,0,.75);transition:transform .32s cubic-bezier(.4,0,.2,1),opacity .25s ease}
[data-lawyers-map] .lm-panel[data-closed]{transform:translateX(calc(-100% - 24px));opacity:0;pointer-events:none}
[data-lawyers-map] .lm-head{display:flex;align-items:center;gap:10px;padding:14px 14px 12px}
[data-lawyers-map] .lm-fold{width:36px;height:36px;flex:none;border-radius:11px;border:0;background:transparent;color:var(--muted);display:grid;place-items:center;cursor:pointer;transition:background .15s,color .15s}
[data-lawyers-map] .lm-fold:hover{background:var(--hover-tint);color:var(--hover-ink)}
[data-lawyers-map] .lm-tools{display:flex;align-items:center;gap:8px;padding:12px 12px 10px}
[data-lawyers-map] .lm-seg{display:inline-flex;gap:2px;padding:3px;border-radius:11px;background:var(--surface-2);border:1px solid var(--line)}
[data-lawyers-map] .lm-seg button{width:32px;height:32px;border-radius:8px;border:0;background:transparent;color:var(--muted);display:grid;place-items:center;cursor:pointer;transition:background .15s,color .15s}
[data-lawyers-map] .lm-seg button:hover{color:var(--hover-ink)}
[data-lawyers-map] .lm-seg button[aria-pressed="true"]{background:var(--chip-on-bg);color:var(--chip-on-ink)}
[data-lawyers-map] .lm-reopen{position:absolute;left:14px;top:14px;z-index:600;display:inline-flex;align-items:center;gap:8px;height:40px;padding:0 14px 0 11px;border-radius:12px;border:1px solid var(--line-strong);background:color-mix(in srgb,var(--surface) 94%,transparent);backdrop-filter:blur(10px);color:var(--ink);font:inherit;font-size:13.5px;font-weight:600;cursor:pointer;box-shadow:0 12px 24px -14px rgba(0,0,0,.7);animation:lmIn .22s ease}
[data-lawyers-map] .lm-reopen:hover{border-color:var(--hover-line);color:var(--hover-ink)}
[data-lawyers-map] .lm-body{flex:1;min-width:0;display:flex;flex-direction:column;gap:3px}
[data-lawyers-map] .lm-list[data-grid]{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-content:start}
[data-lawyers-map] .lm-list[data-grid] .lm-card{flex-direction:column;gap:8px;padding:10px}
[data-lawyers-map] .lm-list[data-grid] .lm-av{width:100%;height:64px}
[data-lawyers-map] .lm-back{width:36px;height:36px;flex:none;border-radius:11px;border:1px solid var(--line-strong);background:transparent;color:var(--ink);display:grid;place-items:center;cursor:pointer;transition:background .15s,border-color .15s}
[data-lawyers-map] .lm-back:hover{background:var(--hover-tint);color:var(--hover-ink)}
[data-lawyers-map] .lm-back svg{transition:transform .2s}
[data-lawyers-map] .lm-back:hover svg{transform:translateX(-2px)}
[data-lawyers-map] .lm-title{font-size:17px;font-weight:700;color:var(--ink)}
[data-lawyers-map] .lm-sub{font-size:12.5px;color:var(--faint)}
[data-lawyers-map] .lm-search{flex:1;min-width:0;display:flex;align-items:center;gap:8px;height:40px;margin:0;padding:0 12px;border-radius:11px;background:var(--surface-2);border:1px solid var(--line);transition:border-color .15s,box-shadow .15s}
[data-lawyers-map] .lm-search:focus-within{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-lawyers-map] .lm-search input{flex:1;min-width:0;border:0;outline:none;background:transparent;color:var(--ink);font:inherit;font-size:14px}
[data-lawyers-map] .lm-search input::placeholder{color:var(--faint)}
[data-lawyers-map] .lm-list{flex:1;min-height:0;overflow-y:auto;padding:2px 12px 14px;display:flex;flex-direction:column;gap:10px;scrollbar-width:thin}
[data-lawyers-map] .lm-card{display:flex;gap:12px;padding:12px;border-radius:16px;background:var(--surface-2);border:1px solid var(--line);cursor:pointer;outline:none;transition:border-color .15s,background .15s,transform .15s}
[data-lawyers-map] .lm-card:hover,[data-lawyers-map] .lm-card:focus-visible{border-color:var(--hover-line);transform:translateY(-1px)}
[data-lawyers-map] .lm-card[data-on]{border-color:color-mix(in srgb,var(--brand-text) 65%,transparent);background:color-mix(in srgb,var(--brand-text) 9%,var(--surface-2));box-shadow:0 0 0 3px color-mix(in srgb,var(--brand-text) 12%,transparent)}
[data-lawyers-map] .lm-av{width:64px;height:76px;flex:none;border-radius:12px;display:grid;place-items:center;font-size:20px;font-weight:700;color:var(--teal-ink);background:radial-gradient(120% 100% at 100% 0%,color-mix(in srgb,var(--teal-ink) 22%,transparent),transparent 60%),color-mix(in srgb,var(--teal-ink) 12%,var(--surface))}
[data-lawyers-map] .lm-name{font-size:14.5px;font-weight:700;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-lawyers-map] .lm-meta{display:flex;align-items:center;gap:5px;font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-lawyers-map] .lm-rate{color:var(--gold);font-weight:600}
[data-lawyers-map] .lm-rate[data-none]{color:var(--faint);font-weight:500}
[data-lawyers-map] .lm-foot{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:4px;font-size:12px;color:var(--faint)}
[data-lawyers-map] .lm-foot b{font-size:14px;color:var(--ink)}
[data-lawyers-map] .lm-tag{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:999px;color:var(--brand-text);background:color-mix(in srgb,var(--brand-text) 14%,transparent)}
[data-lawyers-map] .lm-tag[data-off]{color:var(--faint);background:var(--chip-n)}
[data-lawyers-map] .lm-pop{position:absolute;top:16px;right:70px;z-index:700;width:min(320px,calc(100% - 96px));border-radius:18px;overflow:hidden;background:var(--surface);border:1px solid var(--line-strong);box-shadow:0 24px 48px -20px rgba(0,0,0,.75);animation:lmIn .22s cubic-bezier(.34,1.56,.64,1)}
[data-lawyers-map] .lm-pop-band{position:relative;height:96px;display:grid;place-items:center;background:radial-gradient(120% 140% at 0% 0%,color-mix(in srgb,var(--brand-text) 30%,transparent),transparent 60%),linear-gradient(135deg,color-mix(in srgb,var(--teal-ink) 35%,var(--surface-2)),var(--surface-2))}
[data-lawyers-map] .lm-pop-av{width:58px;height:58px;border-radius:50%;display:grid;place-items:center;font-size:20px;font-weight:700;color:var(--on-brand);background:var(--brand-solid);box-shadow:0 0 0 4px color-mix(in srgb,var(--surface) 70%,transparent)}
[data-lawyers-map] .lm-close{position:absolute;top:10px;right:10px;width:30px;height:30px;border-radius:50%;border:0;background:rgba(255,255,255,.92);color:#1E1C21;display:grid;place-items:center;cursor:pointer}
[data-lawyers-map] .lm-facts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border-radius:12px;background:var(--surface-2);border:1px solid var(--line)}
[data-lawyers-map] .lm-facts div{display:flex;flex-direction:column;gap:2px;padding:8px 10px;border-right:1px solid var(--line)}
[data-lawyers-map] .lm-facts div:last-child{border-right:0}
[data-lawyers-map] .lm-facts b{font-size:13px;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-lawyers-map] .lm-facts span{font-size:11px;color:var(--faint)}
[data-lawyers-map] .lm-km{color:var(--teal-ink);font-weight:700}
[data-lawyers-map] .lm-addr{display:flex;align-items:flex-start;gap:7px;font-size:12.5px;line-height:1.45;color:var(--muted)}
[data-lawyers-map] .lm-addr svg{flex:none;margin-top:2px;color:var(--teal-ink)}
[data-lawyers-map] .lm-addr b{color:var(--teal-ink)}
[data-lawyers-map] .lm-btn{flex:1;height:38px;display:inline-flex;align-items:center;justify-content:center;gap:7px;text-decoration:none;border-radius:999px;border:0;background:var(--brand-solid);color:var(--on-brand);font:inherit;font-size:13px;font-weight:700;cursor:pointer}
[data-lawyers-map] .lm-btn:disabled{background:var(--chip-n);color:var(--faint);cursor:not-allowed}
[data-lawyers-map] .lm-btn.ghost{background:transparent;color:var(--ink);border:1px solid var(--line-strong)}
[data-lawyers-map] .lm-btn.ghost:hover{background:var(--hover-tint);color:var(--hover-ink)}
@keyframes lmIn{from{opacity:0;transform:translateY(-6px) scale(.97)}to{opacity:1;transform:none}}`;

/* The directory's lawyer cards (2026-10-10), scoped by [data-lawyers-grid]. */
const LAWYERS_CARD_CSS = `[data-lawyers-grid] .lc-card{display:flex;flex-direction:column;gap:11px;padding:16px;border-radius:18px;background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow-rest);cursor:pointer;transition:transform .25s cubic-bezier(.22,1,.36,1),box-shadow .25s,border-color .2s,background .2s}
[data-lawyers-grid] .lc-card:hover{transform:translateY(-4px);background:var(--hover);border-color:color-mix(in srgb,var(--brand-text) 45%,transparent);box-shadow:0 18px 34px -18px color-mix(in srgb,var(--brand-text) 55%,#000)}
[data-lawyers-grid] .lc-head{display:flex;align-items:flex-start;gap:11px}
[data-lawyers-grid] .lc-av{width:52px;height:52px;flex:none;border-radius:50%;display:grid;place-items:center;font-size:17px;font-weight:700;color:var(--teal-ink);background:radial-gradient(120% 100% at 100% 0%,color-mix(in srgb,var(--teal-ink) 24%,transparent),transparent 60%),color-mix(in srgb,var(--teal-ink) 13%,var(--surface-2));transition:transform .3s cubic-bezier(.34,1.56,.64,1)}
[data-lawyers-grid] .lc-card:hover .lc-av{transform:scale(1.08)}
[data-lawyers-grid] .lc-name-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
[data-lawyers-grid] .lc-name{font-size:15px;font-weight:700;color:var(--ink);line-height:1.25}
[data-lawyers-grid] .lc-verified{display:inline-flex;align-items:center;gap:3px;font-size:11px;font-weight:700;color:var(--brand-text)}
[data-lawyers-grid] .lc-bar{margin-top:3px;font:500 11px "JetBrains Mono",monospace;color:var(--faint)}
[data-lawyers-grid] .lc-avail{flex:none;font-size:11px;font-weight:700;padding:3px 9px;border-radius:999px;color:var(--brand-text);background:color-mix(in srgb,var(--brand-text) 13%,transparent)}
[data-lawyers-grid] .lc-avail[data-off]{color:var(--faint);background:var(--chip-n)}
[data-lawyers-grid] .lc-chips{display:flex;gap:6px;flex-wrap:wrap}
[data-lawyers-grid] .lc-chips span{font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;background:var(--chip-n);color:var(--ink)}
[data-lawyers-grid] .lc-rating{font-size:12.5px;font-weight:600;color:var(--gold)}
[data-lawyers-grid] .lc-rating[data-none]{font-weight:500;color:var(--faint)}
[data-lawyers-grid] .lc-facts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border-radius:12px;background:var(--surface-2);border:1px solid var(--line)}
[data-lawyers-grid] .lc-facts div{display:flex;flex-direction:column;gap:2px;padding:8px 10px;border-right:1px solid var(--line);min-width:0}
[data-lawyers-grid] .lc-facts div:last-child{border-right:0}
[data-lawyers-grid] .lc-facts b{font-size:13px;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-lawyers-grid] .lc-facts span{font-size:10.5px;color:var(--faint)}
[data-lawyers-grid] .lc-actions{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:auto}
[data-lawyers-grid] .lc-book{display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 14px;border:0;border-radius:999px;background:var(--brand-solid);color:var(--on-brand);font:inherit;font-size:12.5px;font-weight:700;cursor:pointer;box-shadow:0 8px 18px -10px rgba(46,196,214,.7);transition:filter .15s}
[data-lawyers-grid] .lc-book:hover:not(:disabled){filter:brightness(1.08)}
[data-lawyers-grid] .lc-book:hover:not(:disabled) svg{animation:lcHop .5s ease}
[data-lawyers-grid] .lc-book:disabled{background:var(--chip-n);color:var(--faint);box-shadow:none;cursor:not-allowed}
[data-lawyers-grid] .lc-view{display:inline-flex;align-items:center;gap:5px;height:36px;padding:0 4px;border:0;background:none;color:var(--brand-text);font:inherit;font-size:12.5px;font-weight:600;cursor:pointer}
[data-lawyers-grid] .lc-view svg{transition:transform .2s}
[data-lawyers-grid] .lc-view:hover svg{transform:translateX(3px)}
@keyframes lcHop{0%,100%{transform:none}40%{transform:translateY(-3px)}}
@media (prefers-reduced-motion:reduce){[data-lawyers-grid] .lc-card,[data-lawyers-grid] .lc-av{transition:none}[data-lawyers-grid] .lc-card:hover{transform:none}}`;

/* The directory hero (2026-10-10), scoped by [data-lawyers-hero]. */
const LAWYERS_HERO_CSS = `[data-lawyers-hero]{margin-bottom:22px;border-radius:22px;border:1px solid var(--line);background:radial-gradient(70% 120% at 100% 0%,color-mix(in srgb,var(--brand-text) 10%,transparent) 0%,transparent 60%),var(--surface);box-shadow:var(--shadow-rest);overflow:hidden}
[data-lawyers-hero] .lh-main{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:22px;padding:24px 26px}
[data-lawyers-hero] .lh-tag{display:inline-flex;align-items:center;gap:8px;font-size:11.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--brand-text)}
[data-lawyers-hero] .lh-tag i{width:7px;height:7px;border-radius:50%;background:var(--brand-text);box-shadow:0 0 8px var(--brand-text)}
[data-lawyers-hero] .lh-title{margin:10px 0 0;font-size:24px;font-weight:700;color:var(--ink);letter-spacing:-.2px}
[data-lawyers-hero] .lh-text{margin:6px 0 16px;font-size:14px;color:var(--muted)}
[data-lawyers-hero] .lh-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
[data-lawyers-hero] .lh-stat{display:grid;grid-template-columns:auto 1fr;grid-template-areas:"ic v" "l l" "s s";align-items:center;column-gap:10px;padding:12px 14px;border-radius:16px;text-align:left;cursor:pointer;font:inherit;color:inherit;border:1px solid color-mix(in srgb,var(--c) 18%,var(--line));background:radial-gradient(120% 100% at 100% 0%,color-mix(in srgb,var(--c) 13%,transparent) 0%,transparent 55%),var(--surface-2);transition:transform .2s ease,border-color .2s,box-shadow .2s}
[data-lawyers-hero] .lh-stat:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--c) 50%,var(--line));box-shadow:0 14px 26px -18px color-mix(in srgb,var(--c) 70%,#000)}
[data-lawyers-hero] .lh-stat .ic{grid-area:ic;width:34px;height:34px;border-radius:11px;display:grid;place-items:center;color:var(--c);background:color-mix(in srgb,var(--c) 16%,transparent)}
[data-lawyers-hero] .lh-stat .v{grid-area:v;font:600 28px/1 "Literata",Georgia,serif;color:var(--ink);text-align:right}
[data-lawyers-hero] .lh-stat .l{grid-area:l;margin-top:10px;font-size:13px;font-weight:600;color:var(--ink)}
[data-lawyers-hero] .lh-stat .s{grid-area:s;font-size:11.5px;color:var(--faint);margin-top:2px}
[data-lawyers-hero] .lh-ai{display:flex;flex-direction:column;gap:10px;padding:20px 22px;border-radius:18px;border:1px solid color-mix(in srgb,var(--brand-text) 30%,transparent);background:radial-gradient(120% 120% at 100% 0%,color-mix(in srgb,var(--brand-text) 16%,transparent) 0%,transparent 55%),linear-gradient(180deg,var(--hover),var(--surface))}
[data-lawyers-hero] .lh-ai-tag{display:inline-flex;align-items:center;gap:8px;font-size:11.5px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--brand-text)}
[data-lawyers-hero] .lh-ai-tag span{width:28px;height:28px;border-radius:9px;display:grid;place-items:center;background:color-mix(in srgb,var(--brand-text) 16%,transparent)}
[data-lawyers-hero] .lh-ai-title{margin:0;font-size:20px;font-weight:700;color:var(--ink)}
[data-lawyers-hero] .lh-ai-text{margin:0;font-size:13.5px;line-height:1.55;color:var(--muted)}
[data-lawyers-hero] .lh-ai-row{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:4px}
[data-lawyers-hero] .lh-ai-btn{display:inline-flex;align-items:center;gap:8px;height:42px;padding:0 18px;border:0;border-radius:999px;background:var(--brand-solid);color:var(--on-brand);font:inherit;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 10px 22px -12px rgba(46,196,214,.8);transition:filter .15s,transform .15s}
[data-lawyers-hero] .lh-ai-btn:hover:not(:disabled){filter:brightness(1.08);transform:translateY(-1px)}
[data-lawyers-hero] .lh-ai-btn:hover:not(:disabled) svg{animation:lhTwinkle .6s ease}
[data-lawyers-hero] .lh-ai-btn:disabled{opacity:.7;cursor:wait}
[data-lawyers-hero] .lh-ai-note{font-size:12px;color:var(--faint)}
[data-lawyers-hero] .lh-running{display:flex;align-items:center;gap:12px;margin:0 26px 14px;padding:10px 14px;border-radius:14px;font-size:13.5px;color:var(--ink);background:color-mix(in srgb,var(--teal-ink) 10%,var(--surface-2));border:1px solid color-mix(in srgb,var(--teal-ink) 28%,transparent)}
[data-lawyers-hero] .lh-running .dot{width:8px;height:8px;flex:none;border-radius:50%;background:var(--teal-ink)}
[data-lawyers-hero] .lh-running[data-due]{background:color-mix(in srgb,var(--gold) 12%,var(--surface-2));border-color:color-mix(in srgb,var(--gold) 40%,transparent)}
[data-lawyers-hero] .lh-running[data-due] .dot{background:var(--gold);box-shadow:0 0 8px var(--gold)}
[data-lawyers-hero] .lh-running button{flex:none;height:32px;padding:0 14px;border-radius:999px;border:1px solid var(--line-strong);background:transparent;color:var(--ink);font:inherit;font-size:12.5px;font-weight:700;cursor:pointer}
[data-lawyers-hero] .lh-running button:hover{background:var(--hover-tint);color:var(--hover-ink)}
[data-lawyers-hero] .lh-trust{display:flex;flex-wrap:wrap;gap:8px 22px;padding:12px 26px;border-top:1px solid var(--line);background:color-mix(in srgb,var(--surface-2) 55%,transparent);font-size:12.5px;color:var(--muted)}
[data-lawyers-hero] .lh-trust span{display:inline-flex;align-items:center;gap:6px}
[data-lawyers-hero] .lh-trust svg{color:var(--brand-text)}
@keyframes lhTwinkle{0%,100%{transform:none}50%{transform:scale(1.25) rotate(20deg)}}`;

/* The Filters panel's look (2026-10-10), scoped by [data-lawyers-panel]. */
const LAWYERS_PANEL_CSS = `[data-lawyers-panel]{position:relative;margin:0 0 20px;border-radius:20px;border:1px solid color-mix(in srgb,var(--brand-text) 22%,var(--line));background:radial-gradient(60% 120% at 100% 0%,color-mix(in srgb,var(--brand-text) 9%,transparent) 0%,transparent 60%),var(--surface);box-shadow:0 22px 44px -28px rgba(0,0,0,.75);overflow:hidden;animation:lpIn .22s ease}
[data-lawyers-panel] .lp-head{display:flex;align-items:center;gap:12px;padding:16px 22px;border-bottom:1px solid var(--line)}
[data-lawyers-panel] .lp-ic{width:36px;height:36px;flex:none;border-radius:11px;display:grid;place-items:center;color:var(--brand-text);background:color-mix(in srgb,var(--brand-text) 15%,transparent)}
[data-lawyers-panel] .lp-title{margin:0;font-size:15.5px;font-weight:700;color:var(--ink)}
[data-lawyers-panel] .lp-sub{font-size:12.5px;color:var(--faint);margin-top:1px}
[data-lawyers-panel] .lp-x{margin-left:auto;width:34px;height:34px;border-radius:10px;border:1px solid var(--line-strong);background:transparent;color:var(--muted);display:grid;place-items:center;cursor:pointer;transition:border-color .15s,color .15s,background .15s}
[data-lawyers-panel] .lp-x:hover{border-color:transparent;color:var(--danger);background:var(--danger-soft)}
[data-lawyers-panel] .lp-x svg{transition:transform .25s ease}
[data-lawyers-panel] .lp-x:hover svg{transform:rotate(90deg)}
[data-lawyers-panel] .lp-body{display:grid;grid-template-columns:1fr 1fr;gap:22px 26px;padding:20px 22px 22px}
[data-lawyers-panel] .lp-label{display:flex;align-items:center;gap:7px;margin-bottom:10px;font-size:10.5px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--faint)}
[data-lawyers-panel] .lp-label svg{color:var(--brand-text)}
[data-lawyers-panel] .lp-label .gold{color:var(--gold)}
[data-lawyers-panel] .lp-select{position:relative}
[data-lawyers-panel] .lp-select select{width:100%;height:44px;padding:0 40px 0 14px;border-radius:12px;border:1px solid var(--line-strong);background:var(--input);color:var(--ink);font:inherit;font-size:13.5px;font-weight:500;appearance:none;outline:none;cursor:pointer;transition:border-color .15s,box-shadow .15s,background .15s}
[data-lawyers-panel] .lp-select select:hover{background:color-mix(in srgb,var(--brand-text) 6%,var(--input))}
[data-lawyers-panel] .lp-select:hover .chev{transform:translateY(calc(-50% + 2px))}
[data-lawyers-panel] .lp-select select:focus{border-color:var(--brand-text);box-shadow:0 0 0 3px color-mix(in srgb,var(--brand-text) 22%,transparent)}
[data-lawyers-panel] .lp-select[data-on] select{border-color:color-mix(in srgb,var(--brand-text) 60%,transparent);background:color-mix(in srgb,var(--brand-text) 9%,var(--input));font-weight:700}
[data-lawyers-panel] .lp-select select option{background:var(--surface);color:var(--ink)}
[data-lawyers-panel] .lp-select .chev{position:absolute;right:14px;top:50%;transform:translateY(-50%);pointer-events:none;color:var(--faint);transition:color .15s,transform .2s}
[data-lawyers-panel] .lp-select:hover .chev,[data-lawyers-panel] .lp-select[data-on] .chev{color:var(--brand-text)}
[data-lawyers-panel] .lp-chips{display:flex;gap:8px;flex-wrap:wrap}
[data-lawyers-panel] .lp-chip{display:inline-flex;align-items:center;gap:6px;height:36px;padding:0 14px;border-radius:999px;border:1px solid var(--line-strong);background:transparent;color:var(--muted);font:inherit;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap;transition:background .15s,border-color .15s,color .15s,transform .12s}
[data-lawyers-panel] .lp-chip:hover{background:var(--hover-tint);color:var(--ink)}
[data-lawyers-panel] .lp-chip.star:hover{background:color-mix(in srgb,var(--gold) 10%,transparent)}
[data-lawyers-panel] .lp-chip.star:hover svg{color:var(--gold);transform:rotate(-14deg) scale(1.15)}
[data-lawyers-panel] .lp-chip:hover .dot{transform:scale(1.4)}
[data-lawyers-panel] .lp-chip .dot{transition:transform .2s cubic-bezier(.3,1.4,.5,1)}
[data-lawyers-panel] .lp-chip:active{transform:scale(.96)}
[data-lawyers-panel] .lp-chip svg{color:var(--faint);transition:color .15s,transform .25s cubic-bezier(.3,1.4,.5,1)}
[data-lawyers-panel] .lp-chip .dot{width:8px;height:8px;border-radius:50%;background:var(--c)}
[data-lawyers-panel] .lp-chip[aria-checked="true"]{border-color:color-mix(in srgb,var(--brand-text) 55%,transparent);background:color-mix(in srgb,var(--brand-text) 14%,var(--surface-2));color:var(--ink);font-weight:700}
[data-lawyers-panel] .lp-chip.star[aria-checked="true"]{border-color:color-mix(in srgb,var(--gold) 60%,transparent);background:color-mix(in srgb,var(--gold) 14%,var(--surface-2))}
[data-lawyers-panel] .lp-chip.star[aria-checked="true"] svg{color:var(--gold);fill:var(--gold)}
[data-lawyers-panel] .lp-foot{display:flex;align-items:center;gap:12px;padding:14px 22px;border-top:1px solid var(--line);background:color-mix(in srgb,var(--surface-2) 60%,transparent)}
[data-lawyers-panel] .lp-count{font-size:13px;color:var(--muted)}
[data-lawyers-panel] .lp-count b{color:var(--brand-text);font-weight:800}
[data-lawyers-panel] .lp-reset{margin-left:auto;display:inline-flex;align-items:center;gap:7px;height:40px;padding:0 16px;border-radius:999px;border:1px solid var(--line-strong);background:transparent;color:var(--muted);font:inherit;font-size:13px;font-weight:600;cursor:pointer;transition:border-color .15s,color .15s,background .15s}
[data-lawyers-panel] .lp-reset:hover{color:var(--hover-ink);background:var(--hover-tint)}
[data-lawyers-panel] .lp-reset:hover svg{transform:rotate(-200deg)}
[data-lawyers-panel] .lp-reset svg{transition:transform .45s ease}
[data-lawyers-panel] .lp-show{display:inline-flex;align-items:center;gap:8px;height:40px;padding:0 20px;border-radius:999px;border:0;background:linear-gradient(135deg,#12897f 0%,#1c9c66 100%);color:#fff;font:inherit;font-size:13.5px;font-weight:700;cursor:pointer;box-shadow:0 6px 16px rgba(28,156,102,.3);transition:filter .15s,box-shadow .15s,transform .15s}
[data-lawyers-panel] .lp-show:hover{filter:brightness(1.08);box-shadow:0 8px 20px rgba(28,156,102,.4);transform:translateY(-1px)}
[data-lawyers-panel] .lp-show:hover svg{transform:translateX(3px)}
[data-lawyers-panel] .lp-show svg{transition:transform .2s}
@keyframes lpIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}`;

/* The AI box as a message box (2026-10-10), scoped by [data-ai-ask]. */
const AI_ASK_CSS = `[data-ai-ask]{display:flex;flex-direction:column;gap:10px;margin-bottom:20px;padding:16px;border-radius:16px;border:1.5px dashed color-mix(in srgb,var(--brand-text) 40%,transparent);background:linear-gradient(135deg,color-mix(in srgb,var(--brand-text) 16%,transparent),transparent);transition:border-color .2s}
[data-ai-ask][data-open]{border-color:color-mix(in srgb,var(--brand-text) 70%,transparent)}
[data-ai-ask] .aa-row{display:flex;align-items:center;gap:14px}
[data-ai-ask] .aa-ic{width:42px;height:42px;flex:none;border-radius:13px;display:grid;place-items:center;background:color-mix(in srgb,var(--brand-text) 18%,transparent)}
[data-ai-ask] .aa-field{flex:1;min-width:0;display:flex;align-items:center;gap:10px;height:46px;padding:0 16px;border-radius:999px;border:1px solid var(--brand-text);background:color-mix(in srgb,var(--bg) 70%,transparent);box-shadow:0 0 0 3px color-mix(in srgb,var(--brand-text) 18%,transparent);animation:aaIn .22s ease}
[data-ai-ask] .aa-field input{flex:1;min-width:0;height:40px;border:0;outline:none;background:transparent;color:var(--ink);font:inherit;font-size:14px}
[data-ai-ask] .aa-field input::placeholder{color:var(--faint)}
[data-ai-ask] .aa-hint{flex:none;font-size:11.5px;color:var(--faint)}
[data-ai-ask] .aa-send{display:inline-flex;align-items:center;gap:7px;height:38px;padding:0 16px;border:0;border-radius:999px;flex:none;background:var(--brand-solid);color:var(--on-brand);font:inherit;font-size:13px;font-weight:700;cursor:pointer;transition:filter .15s,transform .15s}
[data-ai-ask] .aa-send:hover:not(:disabled){filter:brightness(1.08)}
[data-ai-ask] .aa-send:hover:not(:disabled) svg{transform:translate(2px,-2px)}
[data-ai-ask] .aa-send svg{transition:transform .2s}
[data-ai-ask] .aa-send:disabled{opacity:.55;cursor:not-allowed}
[data-ai-ask] .aa-x{width:32px;height:32px;flex:none;border-radius:9px;border:1px solid var(--line-strong);background:transparent;color:var(--muted);display:grid;place-items:center;cursor:pointer}
[data-ai-ask] .aa-x:hover{border-color:transparent;color:var(--danger);background:var(--danger-soft)}
[data-ai-ask] .aa-x svg{transition:transform .25s ease}
[data-ai-ask] .aa-x:hover svg{transform:rotate(90deg)}
[data-ai-ask] .aa-out{display:flex;align-items:center;flex-wrap:wrap;gap:8px;padding-left:56px;font-size:13px;color:var(--muted);animation:aaIn .22s ease}
[data-ai-ask] .aa-tag{display:inline-flex;align-items:center;height:26px;padding:0 10px;border-radius:999px;font-weight:700;font-size:12.5px;color:var(--brand-text);background:color-mix(in srgb,var(--brand-text) 15%,transparent)}
[data-ai-ask] .aa-link{border:0;background:none;padding:4px 6px;border-radius:8px;color:var(--brand-text);font:inherit;font-size:13px;font-weight:600;cursor:pointer}
[data-ai-ask] .aa-link:hover{background:var(--hover-tint)}
@keyframes aaIn{from{opacity:0;transform:translateY(-3px)}to{opacity:1;transform:none}}`;

/* The page's Map button (2026-10-10), scoped by [data-map-open]. The map
 * folds open and the pin drops on hover; on click it pops before the map. */
const MAP_OPEN_CSS = `[data-map-open]{position:relative;display:inline-flex;align-items:center;gap:8px;height:46px;padding:0 16px 0 7px;border-radius:999px;border:1px solid color-mix(in srgb,var(--brand-text) 35%,var(--line));background:radial-gradient(120% 140% at 0% 0%,color-mix(in srgb,var(--brand-text) 16%,transparent) 0%,transparent 60%),var(--surface);color:var(--ink);font:inherit;font-size:14px;font-weight:700;cursor:pointer;overflow:hidden;transition:border-color .2s,box-shadow .2s,transform .15s,padding .3s ease,gap .3s ease,color .25s}
[data-map-open]:hover,[data-map-open]:focus-visible,[data-map-open][data-going]{padding:0 18px 0 8px;gap:10px}
[data-map-open]:hover{border-color:color-mix(in srgb,var(--brand-text) 70%,transparent);box-shadow:0 10px 24px -14px color-mix(in srgb,var(--brand-text) 80%,#000)}
[data-map-open]:active{transform:scale(.97)}
[data-map-open]::before{content:"";position:absolute;inset:0;border-radius:inherit;background:linear-gradient(135deg,#12897f 0%,#1c9c66 100%);opacity:0;transition:opacity .3s ease}
[data-map-open]>*{position:relative}
[data-map-open]:hover::before,[data-map-open]:focus-visible::before,[data-map-open][data-going]::before{opacity:1}
[data-map-open]:hover,[data-map-open]:focus-visible,[data-map-open][data-going]{color:#fff;border-color:transparent}
[data-map-open]:hover .mo-ic,[data-map-open]:focus-visible .mo-ic,[data-map-open][data-going] .mo-ic{background:#fff;color:#12897f}
[data-map-open]:hover .mo-sub,[data-map-open]:focus-visible .mo-sub,[data-map-open][data-going] .mo-sub{color:rgba(255,255,255,.8)}
[data-map-open]:hover .mo-arrow,[data-map-open]:focus-visible .mo-arrow,[data-map-open][data-going] .mo-arrow{color:#fff}
[data-map-open] .mo-ic{position:relative;width:32px;height:32px;flex:none;border-radius:50%;display:grid;place-items:center;color:var(--on-brand);background:var(--brand-solid);transition:background .25s,color .25s}
[data-map-open] .mo-pin{transform-box:fill-box;transform-origin:50% 100%}
[data-map-open] .mo-shadow{transform-box:fill-box;transform-origin:50% 50%}
[data-map-open]:hover .mo-pin{animation:moDrop .7s cubic-bezier(.3,1.4,.5,1)}
[data-map-open]:hover .mo-shadow{animation:moShadow .7s ease}
[data-map-open] .mo-ic::after{content:"";position:absolute;inset:0;border-radius:50%;border:2px solid var(--brand-text);opacity:0}
[data-map-open][data-going] .mo-ic::after{animation:moRing .45s ease-out}
[data-map-open][data-going] .mo-ic svg{animation:moSpin .45s ease}
[data-map-open] .mo-sub{display:block;max-width:0;max-height:0;overflow:hidden;white-space:nowrap;opacity:0;font-size:12px;font-weight:500;color:var(--faint);transition:max-width .35s ease,max-height .3s ease,opacity .25s ease,color .25s}
[data-map-open]:hover .mo-sub,[data-map-open]:focus-visible .mo-sub,[data-map-open][data-going] .mo-sub{max-width:180px;max-height:16px;opacity:1}
[data-map-open] .mo-arrow{flex:none;color:var(--brand-text);transition:transform .2s,color .25s}
[data-map-open]:hover .mo-arrow{transform:translateX(3px)}
@keyframes moDrop{0%{transform:translateY(-7px);opacity:.4}55%{transform:translateY(0) scale(1.08,.9)}75%{transform:translateY(-2px)}100%{transform:none;opacity:1}}
@keyframes moShadow{0%{transform:scale(.4);opacity:.1}55%{transform:scale(1.15)}100%{transform:none}}
@keyframes moRing{from{opacity:.9;transform:scale(1)}to{opacity:0;transform:scale(1.8)}}
@keyframes moSpin{0%{transform:none}50%{transform:scale(.8) rotate(-12deg)}100%{transform:scale(1.1)}}
@media (prefers-reduced-motion:reduce){[data-map-open] *{animation:none!important;transition:none!important}}`;

const ModLawyers = () => {
    const t = useT();
    const searchParams = useSearchParams();
    const router = useNextRouter();
    const { selectLawyer, confirmAppointment, caseType } = useCase();
    const toast = useToast();
    const { user } = useAuth();
    const lawyerUserId = user?._id || user?.id || null;
    const [query, setQuery] = useState("");
    const [filter, setFilter] = useState("All");
    const [activeView, setActiveView] = useState("list");
    const [selectedLawyer, setSelectedLawyer] = useState(null);
    const [showFilters, setShowFilters] = useState(false);
    // Fix #5: appointment modal state
    const [showApptModal, setShowApptModal] = useState(false);
    const [apptLawyer, setApptLawyer] = useState(null);
    const [apptDate, setApptDate] = useState("");
    // Empty until the client picks one of the slots the server offered.
    const [apptTime, setApptTime] = useState("");
    const [apptDetails, setApptDetails] = useState("");
    const [apptMode, setApptMode] = useState("video");
    const [apptSubmitting, setApptSubmitting] = useState(false);
    // THE SERVER DECIDES WHICH TIMES EXIST. This used to be a list of
    // *booked* slots subtracted from six hardcoded times — 09:00, 10:00,
    // 11:00, 14:00, 15:00, 16:00 — that were identical for every lawyer and
    // every day of the week, so Sunday 09:00 was offered as readily as Tuesday
    // 10:00. Those six times were not a schedule anybody had agreed to.
    //
    // `slotState` keeps FIVE outcomes apart, because collapsing any two of
    // them tells the client something untrue:
    //   idle         no date chosen yet
    //   loading      we are asking
    //   error        we could not ask — NOT the same as "no times"
    //   unconfigured this lawyer has not published hours at all
    //   ready        `slots` is what the server says is bookable
    const [slotState, setSlotState] = useState("idle");
    const [slots, setSlots] = useState([]);
    const [slotNotice, setSlotNotice] = useState("");
    const [slotsEnforced, setSlotsEnforced] = useState(false);
    const [sortBy, setSortBy] = useState("Rating: High to Low");
    const [filters, setFilters] = useState({
        specialization: "All",
        city: "All",
        rating: 0,
        availability: "All",
    });
    const [reviewSort, setReviewSort] = useState("date");

    const [searchMode, setSearchMode] = useState("name");
    const [apiLawyers, setApiLawyers] = useState([]);
    const [loadingLawyers, setLoadingLawyers] = useState(true);
    const [aiMatch, setAiMatch] = useState(null);
    const [loadingMatch, setLoadingMatch] = useState(false);
    // The AI box as a message box (2026-10-10): the client describes the
    // problem and the list is filtered from it. `askResult` is what was read.
    const [askOpen, setAskOpen] = useState(false);
    const [askText, setAskText] = useState("");
    const [askResult, setAskResult] = useState(null);
    const askRef = useRef(null);
    const [mapGoing, setMapGoing] = useState(false);
    // A general listing is NOT a match. The API says which it returned via
    // result_kind; these two carry that answer so the banner can render a
    // browse list differently instead of dressing it up as a recommendation.
    const [matchKind, setMatchKind] = useState(null);
    const [matchNotice, setMatchNotice] = useState(null);
    const [showReviewForm, setShowReviewForm] = useState(false);
    const [reviewStars, setReviewStars] = useState(5);
    const [reviewComment, setReviewComment] = useState("");
    const [reviewSubmitting, setReviewSubmitting] = useState(false);
    // Engagement (hire a lawyer) state
    const [showHireModal, setShowHireModal] = useState(false);
    const [hireLawyer, setHireLawyer] = useState(null);
    const [hireCaseId, setHireCaseId] = useState("");
    const [hireMessage, setHireMessage] = useState("");
    const [hireSubmitting, setHireSubmitting] = useState(false);
    const [myCases, setMyCases] = useState([]);
    const [casesLoaded, setCasesLoaded] = useState(false);
    const [myEngagements, setMyEngagements] = useState([]);
    // A hire follows a COMPLETED consultation with the same lawyer; the server
    // refuses a request without one. `hireConsults` are the consultations the
    // server says qualify; `hireAppointmentId` is the one the CLIENT chose.
    // With several, nothing is chosen for them.
    const [hireConsults, setHireConsults] = useState([]);
    const [hireAppointmentId, setHireAppointmentId] = useState("");
    const [hireOpening, setHireOpening] = useState(false);

    // Cases AND engagements, read together. Both decide which cases can be
    // sent to a lawyer, and the cases were read once per visit: after terms
    // were accepted (the case gains a lawyer) or an engagement ended (it loses
    // one), the picker still showed the old answer. Resolves to what it read;
    // a failed half keeps what is on screen.
    const refreshHiring = async () => {
        const [casesRes, engRes] = await Promise.all([
            listAllCases(listCases).catch(() => ({})),
            listEngagements().catch(() => ({})),
        ]);
        const cases = casesRes?.data?.items;
        const engs = engRes?.data;
        if (Array.isArray(cases)) setMyCases(cases);
        if (Array.isArray(engs)) setMyEngagements(engs);
        setCasesLoaded(true);
        return { cases: Array.isArray(cases) ? cases : null, engs: Array.isArray(engs) ? engs : null };
    };
    const refreshEngagements = () => { refreshHiring(); };

    useEffect(() => { refreshHiring(); }, []);

    // A lawyer proposing terms, or an engagement ending, arrives live.
    useEffect(() => onNotification((n) => {
        const t = String(n.type || "");
        if (t.startsWith("engagement_") || t === "lawyer_assigned") refreshHiring();
    }), []);

    // Cases you can still hire a lawyer for: CONFIRMED, no lawyer yet, not
    // closed, and no request already pending on them.
    //
    // `draft` is excluded because the server refuses it — a draft is a case the
    // client has not confirmed at the end of intake, and sending one to a
    // lawyer is rejected. Offering it here would put a case in the picker whose
    // only possible outcome is an error the client cannot act on from this
    // screen; the action they actually need is on the intake page.
    const pendingByCase = useMemo(() => openByCase(myEngagements), [myEngagements]);
    const hireableCases = useMemo(
        () => hireable(myCases, pendingByCase),
        [myCases, pendingByCase]);

    // Engagement state for one lawyer: "requested" | "accepted" | null
    const engagementWith = (lawyerId) => {
        if (!lawyerId) return null;
        if (myEngagements.some(e => e.lawyer_id === lawyerId && e.status === "requested")) return "requested";
        if (myEngagements.some(e => e.lawyer_id === lawyerId && e.status === "accepted")) return "accepted";
        return null;
    };

    // Prevent background scrolling when a modal is open
    useEffect(() => {
        if (showApptModal || showHireModal) {
            document.body.style.overflow = "hidden";
        } else {
            document.body.style.overflow = "";
        }
        return () => {
            document.body.style.overflow = "";
        };
    }, [showApptModal, showHireModal]);

    // Map a backend user document to the shape the UI expects
    const mapApiLawyer = (raw, idx) => {
        const lp = raw.lawyer_profile || {};
        const specs = (lp.specializations || []).map(s =>
            s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ")
        );
        const province = raw.province || "";
        const provinceLabel = province.charAt(0).toUpperCase() + province.slice(1);
        return {
            _id: raw._id || `api-${idx}`,
            name: raw.full_name || "Unknown",
            spec: specs.join(", ") || "General Practice",
            city: provinceLabel || "Pakistan",
            exp: lp.experience_years || 0,
            fee: lp.hourly_rate || null,          // null = not set
            rating: lp.rating || 0,
            avail: !!lp.availability,
            reviews: lp.total_reviews || 0,
            // null, never a generated placeholder. This field is displayed as a
            // BAR COUNCIL REGISTRATION NUMBER for a real, KYC-verified advocate,
            // and it used to fall back to `BAR-API-001`, `BAR-API-002`, … —
            // numbered by position in the current page, so the same lawyer got a
            // different "registration number" depending on how the list was
            // sorted. Inventing a professional registration number is not a
            // display placeholder, it is a false credential. The UI shows "Not
            // provided" instead.
            bar: lp.bar_number || null,
            bio: lp.bio || null,
            lat: lp.lat ?? null,
            lng: lp.lng ?? null,
            // "exact" = geocoded from an address the lawyer entered.
            // "approximate" = a province centre plus an offset the backend
            // invented, up to ~44 km out. The two arrive in the SAME lat/lng
            // fields, so without this flag the UI cannot tell an office from a
            // fabricated point — and it was offering turn-by-turn directions to
            // both. Anything that sends a client somewhere must check it.
            precision: lp.location_precision ?? (lp.lat != null ? "exact" : "none"),
            // No `distance` field at all. Nothing in the product collects the
            // client's location, so there is no distance to compute; it used to
            // be a hardcoded null that the UI rendered literally as "null km".
            // Office hours are not collected from lawyers anywhere in the
            // product. This was the constant string "Mon–Fri: 9am–5pm" shown on
            // every profile as though it were that lawyer's own schedule, which
            // a client could rely on to turn up at a closed office.
            hours: lp.office_hours || null,
            address: lp.address || null,
            credentials: specs,
            // No `reviewList` here. Review text comes from its own endpoint
            // (`getLawyerReviews`) into the `reviews` state, which stays null
            // until a response arrives — so the profile can tell "not loaded"
            // apart from "none" instead of showing a lawyer with five reviews
            // as having none.
            match_score: raw.match_score,
            match_reason: raw.match_reason,
        };
    };

    const fmtFee = (fee) => fee ? `₨${fee.toLocaleString()}` : "Consult";
    const fmtFeeK = (fee) => fee ? `₨${(fee / 1000).toFixed(1)}k` : "—";

    const [backendUp, setBackendUp] = useState(false);

    // ── The directory: one fetch, and the SERVER does the narrowing ─────────
    //
    // There were two effects here — a mount load and a filter reload — and both
    // asked for `page_size: 20` and nothing else. Everything a client typed or
    // dragged was then applied in the browser to those 20 rows: the search box,
    // the price and experience sliders, and all seven sort options. Each of
    // them answered a question about one page while appearing to answer it
    // about the directory, and the 21st lawyer was unreachable by any
    // combination of controls.
    //
    // Sorting was the clearest case. Sorting a page is not sorting a list: the
    // cheapest lawyer on the platform is very unlikely to be among the 20 you
    // happen to hold, so "Price: Low to High" showed the cheapest of a
    // rating-ordered sample and called it the cheapest.
    const [page, setPage] = useState(1);
    const [pageInfo, setPageInfo] = useState({ total: 0, pages: 1 });

    // UI sort label -> the server's sort key. The server owns what each key
    // orders by, so the client cannot ask it to sort on an arbitrary field.
    const SORT_KEYS = {
        "Rating: High to Low": "rating_desc",
        "Rating: Low to High": "rating_asc",
        "Price: Low to High": "fee_asc",
        "Price: High to Low": "fee_desc",
        "Experience: High": "experience_desc",
        "A–Z": "name_asc",
        "Z–A": "name_desc",
    };

    // The debounce is for TYPING and slider drags, so it must not delay the
    // first load. Folding the mount fetch into this effect without this made
    // every visitor wait 300 ms for a directory that could have been requested
    // immediately — a regression paid by every user to save requests only a
    // user mid-keystroke generates.
    const hasLoadedOnce = React.useRef(false);

    useEffect(() => {
        let cancelled = false;
        setLoadingLawyers(true);
        const delay = hasLoadedOnce.current ? 300 : 0;
        const timer = setTimeout(async () => {
            hasLoadedOnce.current = true;
            const params = { page, page_size: PAGE_SIZE, sort: SORT_KEYS[sortBy] };

            if (filters.city !== "All") {
                const prov = CITY_TO_PROVINCE[filters.city.toLowerCase()];
                if (prov) params.province = prov;
            }
            // An area chip or Filters → Specialization: the area the lawyer lists.
            if (filters.specialization !== "All") params.specialization = filters.specialization;
            if (filters.rating > 0) params.min_rating = filters.rating;
            if (filters.availability === "Available") params.availability = true;
            else if (filters.availability === "Busy") params.availability = false;

            // "Top Rated" is a rating floor, so it is a server filter too —
            // client-side it only ever promoted the best of the loaded page.
            if (filter === "Available") params.availability = true;
            else if (filter === "Top Rated") params.min_rating = Math.max(params.min_rating ?? 0, 4.8);

            if (query.trim()) {
                if (searchMode === "bar") params.bar_number = query.trim();
                else params.q = query.trim();
            }

            const { data, error } = await searchLawyers(params);
            if (cancelled) return;
            if (!error && data) {
                const items = Array.isArray(data) ? data : (data.items || []);
                setApiLawyers(items.map((l, i) => mapApiLawyer(l, i)));
                setPageInfo({
                    total: data.total ?? items.length,
                    pages: data.pages ?? 1,
                });
                setBackendUp(true);
            }
            setLoadingLawyers(false);
        }, delay);
        return () => { cancelled = true; clearTimeout(timer); };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [page, sortBy, query, searchMode, filter,
        filters.city, filters.specialization, filters.rating, filters.availability]);

    // Any change to what is being asked for returns to page 1. Without this a
    // client on page 3 who then searches sees page 3 of the new result set —
    // usually empty — and concludes there are no matches.
    useEffect(() => {
        setPage(1);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [sortBy, query, searchMode, filter,
        filters.city, filters.specialization, filters.rating, filters.availability]);

    // Reset review form whenever the selected lawyer changes
    useEffect(() => {
        setShowReviewForm(false);
        setReviewComment("");
        setReviewStars(5);
    }, [selectedLawyer]);

    // Load the reviews behind the rating.
    //
    // The rating and the count came back with the profile, so the UI could show
    // "4.6 (5)" with nothing behind it — there was no read endpoint for the
    // review text at all. `reviews` stays null until a response arrives, which
    // is what lets the profile distinguish "not loaded" from "none", rather
    // than telling a client that a lawyer with five reviews has none.
    const [reviews, setReviews] = useState(null);
    useEffect(() => {
        const id = selectedLawyer?._id;
        if (!id) { setReviews(null); return; }
        let cancelled = false;
        setReviews(null);
        getLawyerReviews(id).then(({ data, error }) => {
            if (cancelled) return;
            // On error `reviews` stays null, so the profile says the text is
            // unavailable rather than claiming there are none.
            if (!error && data) {
                setReviews((data.items || []).map(r => ({
                    user: r.reviewer,
                    rating: r.stars,
                    text: r.comment || "",
                    date: r.created_at ? String(r.created_at).slice(0, 10) : "",
                })));
            }
        });
        return () => { cancelled = true; };
    }, [selectedLawyer?._id]);

    // Ask the server what is bookable whenever the date or the lawyer changes.
    useEffect(() => {
        let cancelled = false;
        if (!apptDate || !apptLawyer?._id || apptLawyer._id.startsWith("api-")) {
            setSlotState("idle"); setSlots([]); setSlotNotice("");
            return () => { cancelled = true; };
        }
        // A new day means a new set of times: the old pick is not one of them.
        setSlotState("loading"); setSlots([]); setApptTime("");
        getBookableSlots(apptLawyer._id, { from: apptDate, duration_minutes: 60 })
            .then(({ data, error }) => {
                if (cancelled) return;
                if (error || !data) {
                    // NOT an empty day. `apiFetch` RESOLVES on failure, so an
                    // unchecked `data?.days` here would render "no times
                    // available" out of a network error — telling the client
                    // this lawyer is busy when nobody managed to ask.
                    setSlotState("error");
                    setSlotNotice("");
                    return;
                }
                setSlotsEnforced(Boolean(data.enforced));
                setSlotNotice(data.message || "");
                if (!data.configured) {
                    setSlotState("unconfigured");
                    setSlots([]);
                    return;
                }
                const day = (data.days || [])[0] || { slots: [] };
                setSlots(day.slots || []);
                setSlotState("ready");
            });
        return () => { cancelled = true; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [apptDate, apptLawyer?._id]);

    // `isSlotBooked` and its hour-long overlap arithmetic are gone. It assumed
    // every appointment lasted exactly 60 minutes regardless of what was
    // chosen, and it could only subtract from a hardcoded list. The server now
    // returns what is bookable, computed against the real schedule, the real
    // appointments and the real durations.

    const isSlotPast = (timeStr) => {
        if (!apptDate) return false;
        return isPktSlotPast(apptDate, timeStr);
    };

    // Reads the same user-scoped key ModIntake writes. It used to read a
    // shared `aai-case-id`, which on a browser that had signed in as someone
    // else meant matching lawyers against a case this account cannot open.
    const getCaseId = () =>
        searchParams?.get("case_id") || readIntakeValue("aai-case-id", lawyerUserId) || null;

    const MAX_POLL_ATTEMPTS = 5;
    const POLL_INTERVAL_MS = 3000;

    const handleAiMatch = async () => {
        if (loadingMatch) return; // prevent concurrent calls
        const caseId = getCaseId();
        if (!caseId) {
            toast.show("Complete the intake form first to get AI-matched lawyers.", "info", 3500);
            return;
        }
        setLoadingMatch(true);

        let items = [];
        let lastError = null;
        let kind = null;
        let notice = null;

        for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt++) {
            // Wait 3 s before every retry (not before the first try)
            if (attempt > 0) {
                await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));
            }

            const { data, error, status } = await matchLawyers(caseId);

            if (error) {
                if (status === 0) {
                    // Connection refused — backend is not running, no point retrying
                    lastError = "Cannot reach the server. Please make sure the backend is running.";
                    break;
                }
                if (status === 401 || status === 403) {
                    // Auth failure — no point retrying
                    lastError = status === 401
                        ? "Session expired. Please sign in again."
                        : "Access denied. This case does not belong to your account.";
                    break;
                }
                if (status === 404) {
                    // Case not created yet (race condition) — treat as empty and keep polling
                } else {
                    lastError = error?.error || error?.detail || JSON.stringify(error);
                    break;
                }
            }

            items = Array.isArray(data) ? data : (data?.matches || data?.items || []);
            kind = data?.result_kind ?? null;
            notice = data?.notice ?? null;
            // "none" is a settled answer, not a slow one — there are no
            // verified lawyers to find, so polling again cannot change it.
            if (items.length > 0 || kind === "none") break;
            // else: background task still running, poll again
        }

        setMatchKind(kind);
        setMatchNotice(notice);

        if (lastError) {
            toast.show(lastError, "error", 4000);
        } else if (kind === "matched" && items.length) {
            const top = mapApiLawyer(items[0], 0);
            setAiMatch(top);
            toast.show(`AI matched you with ${top.name}`, "success", 3000);
        } else if (notice) {
            // A listing (or nothing at all). Deliberately does NOT set aiMatch:
            // these lawyers were not ranked against the case and must not be
            // presented as a recommendation.
            setAiMatch(null);
            toast.show(notice, "info", 5000);
        } else {
            toast.show("Lawyer matching is still processing — try again in a moment.", "info", 3500);
        }

        setLoadingMatch(false);
    };

    /* ARRIVING FROM A COMPLETED CONSULTATION (§17 R5-1, step 7).
     *
     * The appointment card links here with the lawyer, their name and the
     * consultation. The lawyer is taken from the DIRECTORY when this page
     * happens to be showing them, and otherwise built from the link itself --
     * the directory is paged, so waiting for them to appear in it would leave
     * the client on a page where nothing happens. `openHire` re-reads the
     * eligible consultations from the server either way, and the request it
     * finally sends is validated there.
     */
    const hireLawyerId = searchParams?.get("hire");
    const hireLawyerName = searchParams?.get("hire_name");
    const hireApptId = searchParams?.get("appointment");
    const hireLinkHandled = useRef(false);

    useEffect(() => {
        // WAIT FOR THE CASES. `openHire` refuses when the client has none,
        // and on a fresh page load that read has not returned yet -- opening
        // before it does would tell somebody with cases to go and create one.
        if (!hireLawyerId || !casesLoaded || hireLinkHandled.current) return;
        hireLinkHandled.current = true;
        const known = apiLawyers.find(l => l._id === hireLawyerId);
        openHire(known || { _id: hireLawyerId, name: hireLawyerName || "this lawyer" },
                 hireApptId || null);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [hireLawyerId, hireApptId, casesLoaded]);

    // Auto-trigger match when arriving from intake, but only once backend is confirmed reachable.
    useEffect(() => {
        if (!backendUp) return;
        const caseId = getCaseId();
        if (caseId && !aiMatch) {
            handleAiMatch();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [backendUp, searchParams]);

    const lawyers = apiLawyers;

    // Accent color palette — one per lawyer slot, cycles if more lawyers added
    const accentPalette = [
        { solid: "#1D9E75", light: "#E1F5EE", text: "#085041" },  // teal
        { solid: "#378ADD", light: "#E6F1FB", text: "#0C447C" },  // blue
        { solid: "#EF9F27", light: "#FAEEDA", light2: "#FAEEDA", text: "#633806" },  // amber
        { solid: "#7F77DD", light: "#EEEDFE", text: "#3C3489" },  // purple
        { solid: "#D85A30", light: "#FAECE7", text: "#712B13" },  // coral
        { solid: "#D4537E", light: "#FBEAF0", text: "#72243E" },  // pink
    ];

    // Fixed option lists, NOT derived from the rows on screen.
    //
    // These were built from `lawyers`, which is now one page of the directory —
    // so the specialization and province a client can filter by would be only
    // those the current page happens to contain, and choosing one could never
    // reveal anyone outside it. They are closed sets on the server (CaseType and
    // Province), so they are closed sets here.
    const cities = ["All", "Punjab", "Sindh", "KPK", "Balochistan", "Federal"];
    // No "Distance: Nearest". Nothing in the product collects the client's
    // location, so there is no distance to sort by — the option compared
    // `null - null` for every pair, silently returned the list untouched, and
    // presented that as a proximity ranking.
    const sortOptions = ["Rating: High to Low", "Rating: Low to High", "Price: Low to High", "Price: High to Low", "Experience: High", "A–Z", "Z–A"];
    // The map view (2026-10-10): the lawyer chosen on the list or the map, and
    // the list row under the pointer (its pin lights up).
    const [mapPick, setMapPick] = useState(null);
    const [mapHover, setMapHover] = useState(null);
    const [mapPanelOpen, setMapPanelOpen] = useState(true);    // the floating list over the map
    const [mapLayout, setMapLayout] = useState("list");        // its rows, or a 2-column grid
    // The client's position, only after they press "My location" on the map.
    // Kept in this page's memory -- never stored, never sent to the server.
    const [myPos, setMyPos] = useState(null);
    // The toolbar: "/" jumps to the search (not while typing elsewhere), and
    // Filters shows how many of its choices are on.
    const searchRef = useRef(null);
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
    // Each area chip's count is the server's total for that area under the
    // other filters (one 1-row read each): the page holds only 20 rows, so
    // counting the rows on screen would be wrong.
    const [areaCounts, setAreaCounts] = useState({});
    useEffect(() => {
        // After the list itself has loaded once: it is the first read, and a
        // server that is down gets no further calls.
        if (!backendUp) return undefined;
        let live = true;
        const base = { page: 1, page_size: 1 };
        if (filters.city !== "All") {
            const prov = CITY_TO_PROVINCE[filters.city.toLowerCase()];
            if (prov) base.province = prov;
        }
        if (filters.rating > 0) base.min_rating = filters.rating;
        if (filters.availability === "Available") base.availability = true;
        else if (filters.availability === "Busy") base.availability = false;
        const ask = extra => Promise.resolve(searchLawyers({ ...base, ...extra }))
            .then(res => (res && !res.error ? (res.data?.total ?? null) : null)).catch(() => null);
        Promise.all(AREA_CHIPS.map(([, area]) => ask({ specialization: area }))).then(each => {
            if (!live) return;
            const next = {};
            AREA_CHIPS.forEach(([, value], i) => { next[value] = each[i]; });
            setAreaCounts(next);
        });
        return () => { live = false; };
    }, [backendUp, filters.city, filters.rating, filters.availability]);
    const [dirTotals, setDirTotals] = useState({ all: null, accepting: null });
    useEffect(() => {
        if (!backendUp) return undefined;
        let live = true;
        const total = extra => Promise.resolve(searchLawyers({ page: 1, page_size: 1, ...extra }))
            .then(res => (res && !res.error ? (res.data?.total ?? null) : null)).catch(() => null);
        Promise.all([total({}), total({ availability: true })]).then(([all, accepting]) => {
            if (live) setDirTotals({ all, accepting });
        });
        return () => { live = false; };
    }, [backendUp]);
    const activeFilterCount = (filters.specialization !== "All" ? 1 : 0) + (filters.city !== "All" ? 1 : 0) + (filters.rating > 0 ? 1 : 0);

    // Shown wherever the backend genuinely has no value for a field. Saying so
    // is the honest option; the alternative is inventing one, which is how a
    // generated `BAR-API-001` came to be displayed as a bar council number.
    const UNAVAILABLE = "Not provided";

    const getAccent = (l) => {
        // Keyed on _id alone. `bar` is null whenever a lawyer has not supplied a
        // registration number, and `null === null` matched the first such lawyer
        // for every other one, giving them all the same accent colour.
        const idx = lawyers.findIndex(x => x._id === l._id);
        return accentPalette[Math.max(idx, 0) % accentPalette.length];
    };

    // The page the SERVER returned, already filtered and already sorted.
    //
    // This used to re-run every filter and the sort over `lawyers` — and while
    // the server now applies all of them, re-applying locally would not be
    // merely redundant, it would be wrong. The rows here are one page of a
    // larger ordered result, so sorting them again reorders within the page
    // (page 2 of a price sort would be re-sorted as though it were the whole
    // list), and filtering them again can only ever remove rows the server has
    // already decided belong — leaving a page that looks short for no visible
    // reason while the count beneath it says otherwise.
    const filtered = lawyers;

    // `list` is null when review text was never loaded (there is no endpoint for
    // it yet) and [] when there genuinely are none. Guarded because the caller
    // used to spread it unconditionally, which throws on null.
    const sortedReviews = (list) => [...(list || [])].sort((a, b) =>
        reviewSort === "date" ? new Date(b.date) - new Date(a.date) : b.rating - a.rating
    );

    // ── REVIEW SUBMISSION ─────────────────────────────────────────
    const submitUserReview = async (lawyerId) => {
        if (!lawyerId || lawyerId.startsWith("api-")) {
            toast.show("Reviews can only be submitted for listed lawyers.", "warn", 3000);
            return;
        }
        setReviewSubmitting(true);
        const { error } = await submitReview(lawyerId, reviewStars, reviewComment.trim() || null);
        setReviewSubmitting(false);
        if (error) {
            toast.show(error.message || "Failed to submit review. Please try again.", "error", 3000);
        } else {
            toast.show("⭐ Review submitted — thank you!", "success", 3000);
            setShowReviewForm(false);
            setReviewComment("");
            setReviewStars(5);
        }
    };

    // ── STAR RENDERER ─────────────────────────────────────────────
    const StarRow = ({ rating, color, size = 12 }) => (
        <div style={{ display: "flex", alignItems: "center", gap: 3 }}>
            {[1, 2, 3, 4, 5].map(s => (
                <svg key={s} width={size} height={size} viewBox="0 0 24 24">
                    <polygon
                        points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"
                        fill={s <= Math.round(rating) ? color : "transparent"}
                        stroke={s <= Math.round(rating) ? color : t.border}
                        strokeWidth="1.5"
                    />
                </svg>
            ))}
        </div>
    );

    // ── BOOKING HELPERS ───────────────────────────────────────────
    // Fix #5: opens the modal and pre-selects the lawyer in CaseContext
    const openBooking = (lawyer) => {
        setApptLawyer(lawyer);
        selectLawyer(lawyer);
        setApptDate(pktToday()); // default to today IN PAKISTAN
        setApptTime("");
        setApptDetails("");
        setApptMode("video");
        setSlotState("idle"); setSlots([]); setSlotNotice("");
        setShowApptModal(true);
    };

    // Survives re-renders, so a retry after a failed attempt carries the same
    // key. A useState would work too; a ref makes it explicit that this is not
    // rendered and must not trigger one.
    const bookingKey = useRef(createBookingKeyHolder());

    const submitBooking = async () => {
        try {
            if (!apptDate) {
                toast.show("Please select an appointment date first.", "warn", 3500);
                return;
            }

            if (slotState === "unconfigured") {
                toast.show("This lawyer has not published working hours yet, so no time can be booked.", "warn", 4000);
                return;
            }
            // Only a time the server offered for this day. A default or a
            // stale pick would book a time the client never chose, possibly
            // outside the lawyer's hours.
            if (!apptTime || slotState !== "ready" || !slots.some(s => s.local_time === apptTime)) {
                toast.show("Please choose one of the available times.", "warn", 3500);
                return;
            }

            // Guard: reject past date+time before hitting the API
            if (isPktSlotPast(apptDate, apptTime)) {
                toast.show("That time slot has already passed. Please select a future time.", "warn", 3500);
                return;
            }

            const isApiLawyer = apptLawyer?._id && !apptLawyer._id.startsWith("api-");
            if (!isApiLawyer) {
                toast.show("This lawyer is a sample profile — only listed lawyers can be booked.", "warn", 4000);
                return;
            }
            let bookingData = null;
            if (isApiLawyer) {
                setApptSubmitting(true);
                const scheduled_at = pktSlotToUtcISO(apptDate, apptTime);

                // One key for this booking INTENT, reused on every retry of it.
                // A key minted per request would make a second click after a
                // dropped response look like a second booking, which is exactly
                // what idempotency is here to stop.
                const intent = {
                    lawyer_id: apptLawyer._id,
                    case_id: getCaseId(),
                    scheduled_at,
                    duration_minutes: 60,
                    mode: apptMode,
                    notes: apptDetails || null,
                };
                const { error, data } = await bookAppointment({
                    ...intent,
                    idempotency_key: bookingKey.current.keyFor(intent),
                });

                setApptSubmitting(false);

                if (error) {
                    // 422 detail is a Pydantic array: [{msg: "...", loc: [...]}]
                    const raw = error.detail;
                    const errMsg = Array.isArray(raw)
                        ? raw.map(e => e.msg?.replace(/^Value error,\s*/i, "")).join("; ")
                        : (raw || error.error || "Booking failed. Please try again.");
                    toast.show(errMsg, "error", 4000);
                    return;
                }
                bookingData = data;
            }

            confirmAppointment({
                date: apptDate,
                time: apptTime,
                details: apptDetails || `Consultation with ${apptLawyer?.name}`,
                appointmentId: bookingData?.id || null,
            });

            // The intent is finished, so its key is retired: the next booking
            // is a NEW booking, and reusing this key would make the server
            // replay this appointment instead of creating that one.
            bookingKey.current.complete();

            // A request, not a booking: the lawyer still has to accept it.
            toast.show("Request sent. The lawyer will confirm or decline it. Redirecting…", "success", 2500);
            setShowApptModal(false);
            setTimeout(() => router.push("/tracking"), 600);

        } catch {
            toast.show("An unexpected error occurred. Please try again.", "error", 4000);
            setApptSubmitting(false);
        }
    };

    // ── HIRE (ENGAGEMENT) HELPERS ─────────────────────────────────
    const openHire = async (lawyer, preferredAppointmentId = null) => {
        if (!lawyer?._id || lawyer._id.startsWith("api-")) {
            toast.show("This lawyer is a sample profile — only listed lawyers can be hired.", "warn", 4000);
            return;
        }
        if (hireOpening) return;
        // Decided on a FRESH read, not on what this page loaded earlier.
        setHireOpening(true);
        const fresh = await refreshHiring();
        setHireOpening(false);
        const casesNow = fresh.cases || myCases;
        const canHire = hireable(casesNow, openByCase(fresh.engs || myEngagements));
        if (!canHire.length) {
            toast.show(
                casesNow.some(isDraftCase)
                    ? "Finish confirming your case at the end of the intake — a draft cannot be sent to a lawyer yet."
                    : casesNow.length
                        ? "All your cases already have a lawyer or a pending request."
                        : "Create a case first (via Intake) — then you can request a lawyer for it.",
                "info", 4500
            );
            return;
        }
        // The consultations this hire may follow, asked of the server for THIS
        // lawyer — not read off a page of the diary, where an eligible one
        // could sit just past the end. Only the lawyer can mark one completed.
        if (hireOpening) return;
        setHireOpening(true);
        const { data, error } = await listHireConsultations(lawyer._id);
        setHireOpening(false);
        if (error) {
            // A failed read is not "you have none": saying so would send the
            // client off to book a consultation they may already have had.
            toast.show(error.message || `Could not check your consultations with ${lawyer.name}. Please try again.`, "error", 4500);
            return;
        }
        const consults = Array.isArray(data) ? data : [];
        if (!consults.length) {
            toast.show(
                `Book a consultation with ${lawyer.name} first. Once they mark it completed, you can ask them to take your case.`,
                "info", 5000
            );
            return;
        }
        setHireLawyer(lawyer);
        setHireConsults(consults);
        setHireMessage("");
        // The consultation the client came FROM, when they arrived from one and
        // the server still lists it as eligible. Otherwise: exactly one is the
        // only possible answer, so it is filled in; several are the client's
        // choice and nothing is picked on their behalf.
        const arrivedFrom = preferredAppointmentId
            ? consults.find(a => a.id === preferredAppointmentId)
            : null;
        chooseConsult(arrivedFrom || (consults.length === 1 ? consults[0] : null));
        setShowHireModal(true);
    };

    // The cases a consultation permits: just its own when it was booked for
    // one, otherwise any case that can still be sent to a lawyer.
    const casesForConsult = (consult) => {
        if (!consult) return [];
        return consult.case_id
            ? hireableCases.filter(c => c._id === consult.case_id)
            : hireableCases;
    };

    const chooseConsult = (consult) => {
        setHireAppointmentId(consult?.id || "");
        const options = casesForConsult(consult);
        const urlCase = getCaseId();
        const preselect = options.find(c => c._id === urlCase) || options[0];
        setHireCaseId(preselect?._id || "");
    };

    const consultLabel = (a) => {
        const when = a.scheduled_at ? new Date(a.scheduled_at).toLocaleString(undefined,
            { dateStyle: "medium", timeStyle: "short" }) : "Unknown date";
        const forCase = a.case_id ? myCases.find(c => c._id === a.case_id) : null;
        return forCase ? `${when} — about ${forCase.title}` : when;
    };

    const submitHire = async () => {
        if (!hireAppointmentId) {
            toast.show("Select the consultation this request follows.", "warn", 3500);
            return;
        }
        if (!hireCaseId) {
            toast.show("Select the case you want this lawyer to handle.", "warn", 3500);
            return;
        }
        setHireSubmitting(true);
        const { error } = await requestEngagement({
            case_id: hireCaseId,
            lawyer_id: hireLawyer._id,
            appointment_id: hireAppointmentId,
            message: hireMessage.trim() || null,
        });
        setHireSubmitting(false);
        if (error) {
            toast.show(error.message || "Could not send the request. Please try again.", "error", 4000);
            return;
        }
        toast.show(`Request sent to ${hireLawyer.name}. You'll be notified when they respond.`, "success", 4000);
        setShowHireModal(false);
        refreshEngagements();
    };

    const withdrawRequest = async (engagementId) => {
        const { error } = await cancelEngagement(engagementId);
        if (error) {
            toast.show(error.message || "Could not withdraw the request.", "error", 3500);
        } else {
            toast.show("Request withdrawn.", "success", 2500);
            refreshEngagements();
        }
    };

    // ── Responding to proposed terms ──────────────────────────────
    // This is the decision the client never used to get: the lawyer set a fee
    // and took the case in the same action, so the price arrived attached to a
    // relationship that had already started and could not be ended.
    const [engBusy, setEngBusy] = useState(null);

    const acceptTerms = async (e) => {
        setEngBusy(e.id);
        const { error } = await acceptEngagementTerms(e.id);
        setEngBusy(null);
        if (error) {
            toast.show(error.message || "Could not accept the terms.", "error", 4000);
            return;
        }
        toast.show(`${e.lawyer_name || "Your lawyer"} is now engaged on your case.`, "success", 5000);
        refreshEngagements();
    };

    const declineTerms = async (e) => {
        const reason = window.prompt("Optional: tell the lawyer why these terms don't work (leave blank to skip)");
        if (reason === null) return;
        setEngBusy(e.id);
        const { error } = await declineEngagementTerms(e.id, reason.trim() || null);
        setEngBusy(null);
        if (error) {
            toast.show(error.message || "Could not decline the terms.", "error", 3500);
            return;
        }
        toast.show("Terms declined. Your case is open again — you can approach another lawyer.", "success", 4000);
        refreshEngagements();
    };

    const endEngagement = async (e) => {
        const reason = window.prompt(
            "Ending this engagement releases your case so you can engage someone else.\n\n" +
            "Give a reason (required — it is recorded and shown to your lawyer):"
        );
        if (reason === null) return;
        if (!reason.trim()) {
            toast.show("A reason is required to end an engagement.", "warn", 3500);
            return;
        }
        setEngBusy(e.id);
        const { error } = await terminateEngagement(e.id, reason.trim());
        setEngBusy(null);
        if (error) {
            toast.show(error.message || "Could not end the engagement.", "error", 4000);
            return;
        }
        toast.show("Engagement ended. Your case is open again.", "success", 4000);
        refreshEngagements();
    };

    const markComplete = async (e) => {
        const note = window.prompt("Optional: add a note about how the matter concluded");
        if (note === null) return;
        setEngBusy(e.id);
        const { data, error } = await completeEngagement(e.id, { note: note.trim() || null });
        setEngBusy(null);
        if (error) {
            toast.show(error.message || "Could not mark this complete.", "error", 4000);
            return;
        }
        toast.show(
            data?.status === "completed"
                ? "Engagement completed."
                : "Completion proposed — your lawyer needs to confirm it.",
            "success", 4000,
        );
        refreshEngagements();
    };

    // ── HIRE MODAL ────────────────────────────────────────────────
    // Called as functions, NOT rendered as <HireModal />: a component declared
    // inside the render is a new type on every render, so React remounted the
    // whole form on each keystroke and the text box lost focus after every
    // character.
    const renderHireModal = () => {
        if (!hireLawyer || typeof document === "undefined") return null;
        const hireConsult = hireConsults.find(a => a.id === hireAppointmentId) || null;
        const hireCaseOptions = casesForConsult(hireConsult);
        return createPortal(
            <div style={{
                position: "fixed", inset: 0, zIndex: 9999,
                background: "rgba(0,0,0,0.65)", backdropFilter: "blur(4px)",
                display: "flex", alignItems: "center", justifyContent: "center",
            }}>
                <div style={{
                    background: t.card, borderRadius: 20, border: `1.5px solid ${t.border}`,
                    padding: 28, width: "100%", maxWidth: 460, maxHeight: "90vh", overflowY: "auto",
                    boxShadow: "0 24px 64px rgba(0,0,0,0.4)",
                }}>
                    {/* Header */}
                    <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 18 }}>
                        <div style={{ width: 46, height: 46, borderRadius: 14, background: t.primaryGlow, border: `1.5px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20, fontWeight: 800, color: t.primary, flexShrink: 0 }}>
                            {hireLawyer.name.split(" ").map(w => w[0]).join("").slice(0, 2)}
                        </div>
                        <div style={{ flex: 1 }}>
                            <div style={{ fontWeight: 800, color: t.text, fontSize: 15 }}>Request to Hire {hireLawyer.name}</div>
                            <div style={{ fontSize: 12, color: t.textMuted }}>{hireLawyer.spec} · {fmtFee(hireLawyer.fee)}/hr</div>
                        </div>
                        <button onClick={() => setShowHireModal(false)} style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 8, width: 30, height: 30, cursor: "pointer", color: t.textMuted, fontSize: 16, display: "flex", alignItems: "center", justifyContent: "center" }}>✕</button>
                    </div>

                    <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6, marginBottom: 18, padding: "10px 14px", borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}` }}>
                        The lawyer will review your case and respond with their fee and scope.
                        Nothing is assigned until they accept — you'll get a notification either way.
                    </div>

                    {/* Consultation picker. A choice only when there is one to
                        make; a single consultation is simply stated. */}
                    <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 6 }}>Consultation *</label>
                        {hireConsults.length > 1 ? (
                            <select value={hireAppointmentId}
                                onChange={e => chooseConsult(hireConsults.find(a => a.id === e.target.value) || null)}
                                style={{ width: "100%", padding: "10px 14px", borderRadius: 10, border: `1.5px solid ${hireAppointmentId ? t.primary : t.border}`, background: t.inputBg, color: t.text, fontSize: 13, outline: "none", boxSizing: "border-box" }}>
                                <option value="">Select the consultation this request follows…</option>
                                {hireConsults.map(a => (
                                    <option key={a.id} value={a.id}>{consultLabel(a)}</option>
                                ))}
                            </select>
                        ) : (
                            <div style={{ fontSize: 13, color: t.text, padding: "10px 14px", borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}` }}>
                                {hireConsults[0] ? consultLabel(hireConsults[0]) : ""}
                            </div>
                        )}
                    </div>

                    {/* Case picker */}
                    <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 6 }}>Case *</label>
                        <select value={hireCaseId} onChange={e => setHireCaseId(e.target.value)}
                            style={{ width: "100%", padding: "10px 14px", borderRadius: 10, border: `1.5px solid ${hireCaseId ? t.primary : t.border}`, background: t.inputBg, color: t.text, fontSize: 13, outline: "none", boxSizing: "border-box" }}>
                            {hireCaseOptions.map(c => (
                                <option key={c._id} value={c._id}>
                                    {c.title} ({c.case_number})
                                </option>
                            ))}
                        </select>
                        {!hireConsult && hireConsults.length > 1 && (
                            <div style={{ fontSize: 12, color: t.textMuted, marginTop: 6 }}>Choose a consultation first.</div>
                        )}
                        {hireConsult && !hireCaseOptions.length && (
                            <div style={{ fontSize: 12, color: t.textMuted, marginTop: 6 }}>The case this consultation was booked for can no longer be sent to a lawyer.</div>
                        )}
                    </div>

                    {/* Message */}
                    <div style={{ marginBottom: 22 }}>
                        <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 6 }}>Message to the Lawyer (optional)</label>
                        <textarea value={hireMessage} onChange={e => setHireMessage(e.target.value)}
                            placeholder="Briefly describe what you need help with, your urgency, and anything the lawyer should know…"
                            style={{ width: "100%", minHeight: 88, padding: "10px 14px", borderRadius: 10, border: `1.5px solid ${t.border}`, background: t.inputBg, color: t.text, fontSize: 13, outline: "none", resize: "vertical", boxSizing: "border-box", fontFamily: "inherit" }} />
                    </div>

                    {/* Actions */}
                    <div style={{ display: "flex", gap: 10 }}>
                        <BtnOutline onClick={() => setShowHireModal(false)} style={{ flex: 1, fontSize: 13 }}>Cancel</BtnOutline>
                        <BtnPrimary disabled={hireSubmitting} onClick={submitHire} style={{ flex: 2, fontSize: 13, padding: "12px", opacity: hireSubmitting ? 0.7 : 1 }}>
                            {hireSubmitting ? "Sending…" : "Send Hire Request →"}
                        </BtnPrimary>
                    </div>
                </div>
            </div>,
            document.body
        );
    };

    // ── APPOINTMENT MODAL ─────────────────────────────────────────
    const renderAppointmentModal = () => {
        if (!apptLawyer || typeof document === "undefined") return null;
        return createPortal(
            <div style={{
                position: "fixed", inset: 0, zIndex: 9999,
                background: "rgba(0,0,0,0.65)",
                backdropFilter: "blur(4px)",
                display: "flex", alignItems: "center", justifyContent: "center",
                borderRadius: 0,
            }}>
                <div style={{
                    background: t.card, borderRadius: 20, border: `1.5px solid ${t.border}`,
                    padding: 28, width: "100%", maxWidth: 460, maxHeight: "90vh", overflowY: "auto",
                    boxShadow: "0 24px 64px rgba(0,0,0,0.4)", position: "relative",
                }}>
                    {/* Header */}
                    <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 22 }}>
                        <div style={{ width: 46, height: 46, borderRadius: 14, background: t.primaryGlow, border: `1.5px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20, fontWeight: 800, color: t.primary, flexShrink: 0 }}>
                            {apptLawyer.name.split(" ").map(w => w[0]).join("").slice(0, 2)}
                        </div>
                        <div style={{ flex: 1 }}>
                            <div style={{ fontWeight: 800, color: t.text, fontSize: 15 }}>{apptLawyer.name}</div>
                            <div style={{ fontSize: 12, color: t.textMuted }}>{apptLawyer.spec} · {fmtFee(apptLawyer.fee)}/hr</div>
                        </div>
                        <button onClick={() => setShowApptModal(false)} style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 8, width: 30, height: 30, cursor: "pointer", color: t.textMuted, fontSize: 16, display: "flex", alignItems: "center", justifyContent: "center" }}>✕</button>
                    </div>

                    {/* Date */}
                    <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 6 }}>Date *</label>
                        <input type="date" value={apptDate} min={pktToday()} onChange={e => setApptDate(e.target.value)}
                            style={{ width: "100%", padding: "10px 14px", borderRadius: 10, border: `1.5px solid ${apptDate ? t.primary : t.border}`, background: t.inputBg, color: t.text, fontSize: 13, outline: "none", boxSizing: "border-box" }} />
                    </div>

                    {/* Time — whatever the SERVER says is bookable, never a
                        hardcoded list. The heading says "requested" while
                        enforcement is off, because a time the booking path will
                        accept without checking the lawyer's hours is a request,
                        not an availability guarantee. */}
                    <div style={{ marginBottom: 14 }}>
                        <label id="appt-time-label" style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 6 }}>
                            {slotsEnforced ? "Available Times (PKT)" : "Requested Time (PKT)"}
                        </label>

                        {slotState === "idle" && (
                            <div style={{ fontSize: 12, color: t.textMuted }}>
                                Choose a date to see times.
                            </div>
                        )}

                        {slotState === "loading" && (
                            <div role="status" style={{ fontSize: 12, color: t.textMuted }}>
                                Checking this lawyer&apos;s availability…
                            </div>
                        )}

                        {slotState === "error" && (
                            <div role="alert" style={{ fontSize: 12, color: t.danger }}>
                                We could not load this lawyer&apos;s availability. That is
                                not the same as having none — please try another date or
                                try again shortly.
                            </div>
                        )}

                        {slotState === "unconfigured" && (
                            <div style={{ fontSize: 12, color: t.textMuted }}>
                                {slotNotice || "This lawyer has not set their working hours yet."}
                            </div>
                        )}

                        {slotState === "ready" && slots.length === 0 && (
                            <div style={{ fontSize: 12, color: t.textMuted }}>
                                No times are available on this date. Try another day.
                            </div>
                        )}

                        {slotState === "ready" && slots.length > 0 && (
                            <div role="group" aria-labelledby="appt-time-label"
                                style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                {slots.map(slot => {
                                    const label = slot.local_time;
                                    const chosen = apptTime === label;
                                    return (
                                        <button key={slot.start} type="button"
                                            aria-pressed={chosen}
                                            onClick={() => setApptTime(label)}
                                            style={{ minHeight: 40, padding: "8px 14px", borderRadius: 8, border: `1.5px solid ${chosen ? t.primary : t.border}`, background: chosen ? t.primaryGlow : "transparent", color: chosen ? t.primary : t.textMuted, fontSize: 12, fontWeight: 700, cursor: "pointer", transition: "all 0.15s", fontFamily: "inherit" }}>
                                            {label}
                                        </button>
                                    );
                                })}
                            </div>
                        )}

                        {slotState === "ready" && !slotsEnforced && slotNotice && (
                            <div style={{ fontSize: 11, color: t.textFaint, marginTop: 6 }}>
                                {slotNotice}
                            </div>
                        )}
                    </div>

                    {/* Notes */}
                    <div style={{ marginBottom: 22 }}>
                        <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 6 }}>Consultation Notes (optional)</label>
                        <textarea value={apptDetails} onChange={e => setApptDetails(e.target.value)}
                            placeholder={`Brief description of your case for ${apptLawyer.name}…`}
                            style={{ width: "100%", minHeight: 72, padding: "10px 14px", borderRadius: 10, border: `1.5px solid ${t.border}`, background: t.inputBg, color: t.text, fontSize: 13, outline: "none", resize: "vertical", boxSizing: "border-box" }} />
                    </div>

                    {/* Consultation mode */}
                    <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 6 }}>Consultation Mode</label>
                        <div style={{ display: "flex", gap: 8 }}>
                            {[["video", "Video Call"], ["in_person", "In-Person"], ["phone", "Phone"]].map(([val, label]) => (
                                <button key={val} onClick={() => setApptMode(val)}
                                    style={{ flex: 1, padding: "8px 10px", borderRadius: 8, border: `1.5px solid ${apptMode === val ? t.primary : t.border}`, background: apptMode === val ? t.primaryGlow : "transparent", color: apptMode === val ? t.primary : t.textMuted, fontSize: 12, fontWeight: 700, cursor: "pointer", transition: "all 0.15s" }}>
                                    {label}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Working hours info */}
                    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}`, marginBottom: 18 }}>
                        <Ic n="clock" s={13} c={t.textMuted} />
                        <span style={{ fontSize: 12, color: t.textMuted }}>{apptLawyer.hours || "Office hours not provided"}</span>
                    </div>

                    {/* Actions */}
                    <div style={{ display: "flex", gap: 10 }}>
                        <BtnOutline onClick={() => setShowApptModal(false)} style={{ flex: 1, fontSize: 13 }}>Cancel</BtnOutline>
                        <BtnPrimary disabled={apptSubmitting} onClick={submitBooking} style={{ flex: 2, fontSize: 13, padding: "12px", opacity: apptSubmitting ? 0.7 : 1 }}>
                            {apptSubmitting ? "Booking…" : "Confirm Appointment →"}
                        </BtnPrimary>
                    </div>
                </div>
            </div>,
            document.body
        );
    };

    // Stable single-item array so LeafletMap doesn't re-run on every render
    // eslint-disable-next-line react-hooks/exhaustive-deps
    const profileMapLawyers = useMemo(() => selectedLawyer ? [selectedLawyer] : [], [selectedLawyer?._id]);

    // ── PROFILE VIEW ──────────────────────────────────────────────
    if (activeView === "profile" && selectedLawyer) {
        const l = selectedLawyer;
        const ac = getAccent(l);
        return (
            <div style={{ position: "relative" }}>
                {showApptModal && renderAppointmentModal()}
                {showHireModal && renderHireModal()}
                <button onClick={() => setActiveView("list")} style={{ display: "flex", alignItems: "center", gap: 8, background: "none", border: "none", color: t.primary, cursor: "pointer", fontSize: 13, fontWeight: 600, marginBottom: 20, padding: 0 }}>
                    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke={t.primary} strokeWidth="2"><path d="M19 12H5M12 5l-7 7 7 7" /></svg>
                    Back to Lawyers
                </button>
                <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                        <Card>
                            <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
                                <div style={{ width: 72, height: 72, borderRadius: 20, background: ac.light, border: `2px solid ${ac.solid}55`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, fontWeight: 800, color: ac.solid, flexShrink: 0 }}>
                                    {l.name.split(" ").map(w => w[0]).join("").slice(0, 2)}
                                </div>
                                <div style={{ flex: 1 }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                                        <span style={{ fontWeight: 800, color: t.text, fontSize: 17 }}>{l.name}</span>
                                        <Badge type={l.avail ? "success" : "gray"}>{l.avail ? "Available" : "Busy"}</Badge>
                                    </div>
                                    <div style={{ fontSize: 13, color: ac.solid, fontWeight: 600, marginTop: 2 }}>{l.spec}</div>
                                    <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>Bar No: {l.bar || UNAVAILABLE}</div>
                                    <div style={{ display: "flex", gap: 6, marginTop: 6, alignItems: "center" }}>
                                        <StarRow rating={l.rating} color={ac.solid} size={13} />
                                        <span style={{ fontSize: 12, color: t.textMuted, marginLeft: 4 }}>{l.rating} · {l.reviews} reviews</span>
                                    </div>
                                </div>
                            </div>
                            {l.bio && (
                                <p style={{ fontSize: 13, color: t.textDim, margin: "12px 0 0", lineHeight: 1.6 }}>{l.bio}</p>
                            )}
                            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 10, marginTop: 16, background: t.inputBg, borderRadius: 12, padding: 14 }}>
                                {[["Experience", `${l.exp} yrs`], ["Fee/hr", fmtFee(l.fee)], ["City", l.city]].map(([k, v]) => (
                                    <div key={k} style={{ textAlign: "center" }}>
                                        <div style={{ fontSize: 10, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.5px" }}>{k}</div>
                                        <div style={{ fontSize: 14, fontWeight: 700, color: t.text, marginTop: 3 }}>{v}</div>
                                    </div>
                                ))}
                            </div>
                            <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
                                <BtnOutline
                                    onClick={() => l.avail && !l._id?.startsWith("api-") && openBooking(l)}
                                    style={{ flex: 1, fontSize: 13, opacity: (!l.avail || l._id?.startsWith("api-")) ? 0.5 : 1, cursor: (!l.avail || l._id?.startsWith("api-")) ? "not-allowed" : "pointer" }}
                                >Book Appointment</BtnOutline>
                                {(() => {
                                    const engState = engagementWith(l._id);
                                    if (engState === "accepted") return (
                                        <BtnPrimary disabled style={{ flex: 1, fontSize: 13, opacity: 0.75 }}>✓ Engaged on Your Case</BtnPrimary>
                                    );
                                    if (engState === "requested") return (
                                        <BtnPrimary disabled style={{ flex: 1, fontSize: 13, opacity: 0.75 }}>Request Pending…</BtnPrimary>
                                    );
                                    return (
                                        <BtnPrimary
                                            disabled={l._id?.startsWith("api-")}
                                            onClick={() => openHire(l)}
                                            style={{ flex: 1, fontSize: 13 }}
                                            title={l._id?.startsWith("api-") ? "Sample profile — cannot be hired" : "Ask this lawyer to take your case"}
                                        >Request to Hire</BtnPrimary>
                                    );
                                })()}
                            </div>
                        </Card>
                        <Card>
                            <div style={{ fontWeight: 700, color: t.text, fontSize: 14, marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
                                <Ic n="shield" s={15} c={t.primary} /> Credentials & Qualifications
                            </div>
                            {/* The platform reviews what a lawyer submits; it does not
                                confirm enrolment with any Bar Council — no such check
                                exists in the system. Saying so here is the difference
                                between a listing and a guarantee. */}
                            <div style={{ fontSize: 11.5, color: t.textMuted, lineHeight: 1.5, marginBottom: 12, padding: "8px 10px", borderRadius: 8, background: `color-mix(in srgb, ${t.border} 25%, transparent)` }}>
                                Credentials below are provided by the lawyer and reviewed by our team.
                                We do not independently confirm Bar Council enrolment — please verify
                                directly before engaging.
                            </div>
                            {l.credentials.map((c, i) => (
                                <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderBottom: i < l.credentials.length - 1 ? `1px solid ${t.border}` : "none" }}>
                                    <div style={{ width: 6, height: 6, borderRadius: "50%", background: ac.solid, flexShrink: 0 }} />
                                    <span style={{ fontSize: 13, color: t.text }}>{c}</span>
                                </div>
                            ))}
                        </Card>
                        <Card>
                            <div style={{ fontWeight: 700, color: t.text, fontSize: 14, marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
                                <Ic n="clock" s={15} c={t.primary} /> Office Info
                            </div>
                            {[["Working Hours", l.hours || UNAVAILABLE], ["Office Address", l.address || UNAVAILABLE], ["Consultation Fee", l.fee ? `${fmtFee(l.fee)} / hour` : UNAVAILABLE]].map(([k, v]) => (
                                <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 10 }}>
                                    <span style={{ fontSize: 12, color: t.textMuted, flexShrink: 0 }}>{k}</span>
                                    <span style={{ fontSize: 13, color: t.text, fontWeight: 600, textAlign: "right" }}>{v}</span>
                                </div>
                            ))}
                        </Card>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                        <Card style={{ padding: 0, overflow: "hidden" }}>
                            {/* Real embedded map centred on this lawyer */}
                            <LeafletMap
                                lawyers={profileMapLawyers} dark={t.mode === "dark"}
                                height={200}
                                onSelect={() => { }}
                            />
                            <div style={{ padding: "10px 14px", borderTop: `1px solid ${t.border}` }}>
                                <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 8 }}>
                                    <strong style={{ color: t.text }}>{l.address || UNAVAILABLE}</strong>
                                    {l.city && l.address !== l.city && (
                                        <span> · {l.city}</span>
                                    )}
                                </div>
                                {/* Navigation is offered ONLY for a real address.
                                    Both buttons used to fall back to the pin, and the pin is a
                                    province centre plus an invented offset of up to ~44 km
                                    whenever the lawyer never entered an address — so "Get
                                    Directions" routed a client to a fabricated destination, with
                                    nothing on screen suggesting it was not their lawyer's office.
                                    The address fallback was no better: `l.address` is null for
                                    such a lawyer, and `encodeURIComponent(null)` is the string
                                    "null", which was being sent to Google Maps as a search term. */}
                                {l.precision === "exact" ? (
                                    <div style={{ display: "flex", gap: 10 }}>
                                        <BtnOutline style={{ flex: 1, fontSize: 12, padding: "9px" }}
                                            onClick={() => {
                                                const q = `${l.lat},${l.lng}`;
                                                window.open(`https://www.google.com/maps/search/?api=1&query=${q}`, "_blank");
                                            }}>
                                            <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                                                <Ic n="map" s={13} c={t.primary} /> View on Map
                                            </span>
                                        </BtnOutline>
                                        <BtnPrimary style={{ flex: 1, fontSize: 12, padding: "9px" }}
                                            onClick={() => {
                                                const dest = `${l.lat},${l.lng}`;
                                                window.open(`https://www.google.com/maps/dir/?api=1&destination=${dest}`, "_blank");
                                            }}>
                                            <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                                                <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2L4.5 20.29l.71.71L12 18l6.79 3 .71-.71z" /></svg>
                                                Get Directions
                                            </span>
                                        </BtnPrimary>
                                    </div>
                                ) : (
                                    <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6 }}>
                                        This lawyer has not published an office address, so the pin
                                        above shows {l.city ? <strong style={{ color: t.text }}>{l.city}</strong> : "their province"} only
                                        and directions are not available. Ask them for the address
                                        when you book.
                                    </div>
                                )}
                            </div>
                        </Card>
                        <Card>
                            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
                                <div style={{ fontWeight: 700, color: t.text, fontSize: 14, display: "flex", alignItems: "center", gap: 8 }}>
                                    <Ic n="star" s={15} c={t.warn} /> Reviews
                                    <span style={{ fontSize: 13, color: t.primary, fontWeight: 700 }}>{l.rating}</span>
                                    <span style={{ fontSize: 12, color: t.textMuted }}>({l.reviews})</span>
                                </div>
                                {/* The sort control only makes sense once there
                                    is something to sort. */}
                                {reviews?.length ? (
                                    <select value={reviewSort} onChange={e => setReviewSort(e.target.value)} style={{ background: t.inputBg, border: `1px solid ${t.border}`, color: t.text, borderRadius: 8, padding: "5px 10px", fontSize: 12, outline: "none" }}>
                                        <option value="date">By Date</option>
                                        <option value="rating">By Rating</option>
                                    </select>
                                ) : null}
                            </div>
                            {/* Three distinct states, deliberately not collapsed
                                into one. `null` is "still loading, or the
                                request failed" — NOT "there are none". Telling a
                                client that a lawyer with five reviews has none,
                                because a fetch was in flight or errored,
                                misrepresents that lawyer; the count beside the
                                rating would also visibly contradict it. */}
                            {reviews === null ? (
                                <div style={{ fontSize: 12, color: t.textMuted, padding: "10px 0" }}>
                                    {l.reviews > 0
                                        ? `Loading ${l.reviews} review${l.reviews === 1 ? "" : "s"}…`
                                        : "Loading reviews…"}
                                </div>
                            ) : reviews.length === 0 ? (
                                <div style={{ fontSize: 12, color: t.textMuted, padding: "10px 0" }}>
                                    No reviews yet.
                                </div>
                            ) : null}
                            {sortedReviews(reviews).map((r, i) => (
                                <div key={i} style={{ background: t.inputBg, borderRadius: 12, padding: "12px 14px", marginBottom: 10 }}>
                                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                                        <span style={{ fontWeight: 700, fontSize: 13, color: t.text }}>{r.user}</span>
                                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                            <StarRow rating={r.rating} color={t.warn} size={10} />
                                            <span style={{ fontSize: 11, color: t.textMuted }}>{r.date}</span>
                                        </div>
                                    </div>
                                    <p style={{ fontSize: 12, color: t.textDim, margin: 0, lineHeight: 1.6 }}>{r.text}</p>
                                </div>
                            ))}

                            {/* Write a Review */}
                            <div style={{ marginTop: 12, borderTop: `1px solid ${t.border}`, paddingTop: 12 }}>
                                {!showReviewForm ? (
                                    <button onClick={() => setShowReviewForm(true)}
                                        style={{ width: "100%", padding: "9px", borderRadius: 10, border: `1.5px solid ${t.primary}`, background: "transparent", color: t.primary, fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                                        Write a Review
                                    </button>
                                ) : (
                                    <div>
                                        <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 8 }}>Your Rating</div>
                                        <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 12 }}>
                                            {[1, 2, 3, 4, 5].map(s => (
                                                <button key={s} onClick={() => setReviewStars(s)}
                                                    style={{ background: "none", border: "none", cursor: "pointer", padding: 2, lineHeight: 0 }}>
                                                    <svg width={22} height={22} viewBox="0 0 24 24">
                                                        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"
                                                            fill={s <= reviewStars ? t.warn : "transparent"}
                                                            stroke={s <= reviewStars ? t.warn : t.border} strokeWidth="1.5" />
                                                    </svg>
                                                </button>
                                            ))}
                                            <span style={{ fontSize: 12, color: t.textMuted, marginLeft: 4 }}>{reviewStars} / 5</span>
                                        </div>
                                        <textarea value={reviewComment} onChange={e => setReviewComment(e.target.value)}
                                            placeholder="Share your experience with this lawyer…"
                                            style={{ width: "100%", minHeight: 72, padding: "8px 12px", borderRadius: 10, border: `1.5px solid ${t.border}`, background: t.inputBg, color: t.text, fontSize: 12, outline: "none", resize: "vertical", boxSizing: "border-box", fontFamily: "inherit" }} />
                                        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                                            <button onClick={() => setShowReviewForm(false)}
                                                style={{ flex: 1, padding: "8px", borderRadius: 8, border: `1px solid ${t.border}`, background: "transparent", color: t.textMuted, fontSize: 12, cursor: "pointer", fontFamily: "inherit" }}>
                                                Cancel
                                            </button>
                                            <button onClick={() => submitUserReview(l._id)} disabled={reviewSubmitting}
                                                style={{ flex: 2, padding: "8px", borderRadius: 8, border: "none", background: t.primary, color: t.mode === "dark" ? "#1A2E35" : "#fff", fontSize: 12, fontWeight: 700, cursor: reviewSubmitting ? "not-allowed" : "pointer", opacity: reviewSubmitting ? 0.7 : 1, fontFamily: "inherit" }}>
                                                {reviewSubmitting ? "Submitting…" : "Submit Review"}
                                            </button>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </Card>
                    </div>
                </div>
            </div>
        );
    }

    // ── MAP VIEW ──────────────────────────────────────────────────
    // (2026-10-10) The map fills the view; the list floats over its left edge
    // and folds away. Fee pills for pins, the chosen lawyer's card over the
    // map. Pins show a PROVINCE where the lawyer gave no address -- the panel
    // says so, and those pins are dashed.
    if (activeView === "map") {
        const idOf = l => String(l._id || l.bar || l.name);
        const picked = filtered.find(l => idOf(l) === mapPick) || null;
        const initials = l => l.name.split(" ").map(w => w[0]).join("").slice(0, 2);
        const feeText = l => (l.fee ? `Rs ${l.fee.toLocaleString()}` : "Fee on request");
        const ratingText = l => (l.reviews > 0 ? `★ ${Number(l.rating).toFixed(1)} (${l.reviews})` : "No reviews yet");
        const panelIcon = (
            <svg width={17} height={17} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2.5" /><path d="M9 4v16" /></svg>
        );
        const grid = mapLayout === "grid";
        // Distance is shown only to a lawyer whose pin is their OFFICE (an
        // address they gave): a province centre is not a place to measure to.
        const exact = l => l.precision === "exact" && l.lat != null && l.lng != null;
        const kmTo = l => {
            if (!myPos || !exact(l)) return null;
            const rad = d => (d * Math.PI) / 180;
            const dLat = rad(l.lat - myPos.lat), dLng = rad(l.lng - myPos.lng);
            const a = Math.sin(dLat / 2) ** 2 + Math.cos(rad(myPos.lat)) * Math.cos(rad(l.lat)) * Math.sin(dLng / 2) ** 2;
            return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        };
        const kmText = km => (km == null ? null : km < 1 ? `${Math.round(km * 1000)} m away` : `${km < 10 ? km.toFixed(1) : Math.round(km)} km away`);
        // Located: the nearest offices first, then everyone without one, in the server's order.
        const shown = !myPos ? filtered : [...filtered].sort((a, b) => {
            const da = kmTo(a), db = kmTo(b);
            if (da == null && db == null) return 0;
            if (da == null) return 1;
            if (db == null) return -1;
            return da - db;
        });
        const directionsUrl = l => `https://www.google.com/maps/dir/?api=1&destination=${l.lat},${l.lng}`
            + (myPos ? `&origin=${myPos.lat},${myPos.lng}` : "");
        return (
            <div data-lawyers-map-page>
            <style>{LAWYERS_TOOLS_CSS + "\n" + LAWYERS_MAP_CSS}</style>
            {/* The page's header, above the map (2026-10-10). */}
            <header className="lm-pagehead">
                <button type="button" className="lm-back" onClick={() => setActiveView("list")} aria-label="Back to list" title="Back to list">
                    <span className="ic" aria-hidden="true">
                        <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5M12 5l-7 7 7 7" /></svg>
                    </span>
                    List
                </button>
                <div style={{ flex: 1, minWidth: 0 }}>
                    <h2 className="lm-title">All lawyers</h2>
                    <div className="lm-sub">{filtered.length} lawyer{filtered.length === 1 ? "" : "s"} · {myPos ? "nearest office first" : "pins show province"}</div>
                </div>
                <button type="button" className="lm-toggle" aria-pressed={mapPanelOpen} onClick={() => setMapPanelOpen(o => !o)}>
                    <span className="ic" aria-hidden="true">{panelIcon}</span>
                    {mapPanelOpen ? "Hide list" : "Show list"}
                    {!mapPanelOpen && <span className="n">{filtered.length}</span>}
                </button>
            </header>
            <div data-lawyers-map style={{ position: "relative", height: "calc(100vh - 140px)", minHeight: 520, borderRadius: 20, overflow: "hidden", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}>
                {/* Book from the map: the same dialogs as the list (portals). */}
                {showApptModal && renderAppointmentModal()}
                {showHireModal && renderHireModal()}

                <LeafletMap lawyers={filtered} height="100%" dark={t.mode === "dark"} controls
                    selectedId={mapPick} hoveredId={mapHover} leftInset={mapPanelOpen ? 340 : 0}
                    onSelect={l => setMapPick(idOf(l))}
                    onLocate={(pos, problem) => {
                        if (pos) { setMyPos(pos); toast.show("Showing lawyers nearest to you first.", "success", 2500); }
                        else toast.show(problem || "Your location could not be found.", "error", 3500);
                    }} />

                <aside aria-label="Lawyers on the map" className="lm-panel" data-closed={mapPanelOpen ? undefined : "true"} aria-hidden={!mapPanelOpen}>
                    <div data-lawyers-tools className="lm-tools">
                        <label className="lm-search">
                            <Ic n="search" s={15} c="var(--faint)" />
                            <span style={{ position: "absolute", left: -9999 }}>Search lawyers</span>
                            <input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search lawyers…" tabIndex={mapPanelOpen ? 0 : -1} />
                        </label>
                        <div role="group" aria-label="Layout" className="lm-seg">
                            <button type="button" aria-pressed={!grid} aria-label="List" title="List" onClick={() => setMapLayout("list")}>
                                <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01" /></svg>
                            </button>
                            <button type="button" aria-pressed={grid} aria-label="Grid" title="Grid" onClick={() => setMapLayout("grid")}>
                                <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden="true"><rect x="3.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="3.5" y="13.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="13.5" width="7" height="7" rx="1.5" /></svg>
                            </button>
                        </div>
                        <LawyerSort compact value={sortBy} options={sortOptions} onChange={setSortBy} />
                    </div>
                    <div className="lm-list" data-grid={grid ? "true" : undefined} data-lenis-prevent>
                        {shown.map(l => {
                            const id = idOf(l);
                            const away = kmText(kmTo(l));
                            return (
                                <div key={id} role="button" tabIndex={mapPanelOpen ? 0 : -1} className="lm-card" data-on={id === mapPick ? "true" : undefined}
                                    onClick={() => setMapPick(id)} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setMapPick(id); } }}
                                    onMouseEnter={() => setMapHover(id)} onMouseLeave={() => setMapHover(h => (h === id ? null : h))}>
                                    <span className="lm-av" aria-hidden="true">{initials(l)}</span>
                                    <div className="lm-body">
                                        <div className="lm-name">{l.name}</div>
                                        <div className="lm-meta">
                                            <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z" /><circle cx="12" cy="10" r="2.5" /></svg>
                                            {away ? <b className="lm-km">{away}</b> : null}{away ? " · " : ""}{l.city}{l.lat == null ? " · no map location" : ""}
                                        </div>
                                        {!grid && <div className="lm-meta"><span className="lm-rate" data-none={l.reviews > 0 ? undefined : "true"}>{ratingText(l)}</span> · {l.spec}</div>}
                                        <div className="lm-foot">
                                            <span><b>{feeText(l)}</b>{l.fee && !grid ? " / consultation" : ""}</span>
                                            {!grid && <span className="lm-tag" data-off={l.avail ? undefined : "true"}>{l.avail ? "Accepting" : "Not accepting"}</span>}
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                        {filtered.length === 0 && <div className="lm-sub" style={{ padding: 16 }}>No lawyer matches these filters.</div>}
                    </div>
                </aside>

                {picked && (
                    <div className="lm-pop" role="dialog" aria-label={`${picked.name}, on the map`}>
                        <div className="lm-pop-band">
                            <span className="lm-pop-av" aria-hidden="true">{initials(picked)}</span>
                            <button type="button" className="lm-close" aria-label="Close" onClick={() => setMapPick(null)}>
                                <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
                            </button>
                        </div>
                        <div style={{ padding: "14px 16px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
                            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10 }}>
                                <div className="lm-name" style={{ fontSize: 16.5 }}>{picked.name}</div>
                                <span className="lm-rate" data-none={picked.reviews > 0 ? undefined : "true"} style={{ whiteSpace: "nowrap" }}>{ratingText(picked)}</span>
                            </div>
                            <div className="lm-sub" style={{ fontSize: 13.5 }}>{picked.spec} · {picked.city}</div>
                            <div className="lm-facts">
                                <div><b>{picked.exp ? `${picked.exp} yrs` : "New"}</b><span>experience</span></div>
                                <div><b>{feeText(picked)}</b><span>consultation</span></div>
                                <div><b>{picked.avail ? "Accepting" : "Not now"}</b><span>requests</span></div>
                            </div>
                            {exact(picked) ? (
                                <div className="lm-addr">
                                    <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z" /><circle cx="12" cy="10" r="2.5" /></svg>
                                    <span>{picked.address || "Office location on the map"}{kmText(kmTo(picked)) ? <b> · {kmText(kmTo(picked))}</b> : null}</span>
                                </div>
                            ) : (
                                <div className="lm-sub" style={{ fontSize: 12 }}>Office address not shared — the pin is the province centre, so there is no route to it.</div>
                            )}
                            <div style={{ display: "flex", gap: 8, marginTop: 2 }}>
                                <button type="button" className="lm-btn ghost" onClick={() => { setSelectedLawyer(picked); setActiveView("profile"); }}>View profile</button>
                                {exact(picked) && (
                                    <a className="lm-btn ghost" href={directionsUrl(picked)} target="_blank" rel="noopener noreferrer"
                                        title={myPos ? "Route from your location, in Google Maps" : "Route to the office, in Google Maps"}>
                                        <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 11l18-8-8 18-2-8z" /></svg>
                                        Directions
                                    </a>
                                )}
                            </div>
                            <button type="button" className="lm-btn" style={{ flex: "none", width: "100%" }} disabled={!picked.avail}
                                title={picked.avail ? undefined : "This lawyer is not taking new requests"}
                                onClick={() => picked.avail && openBooking(picked)}>Book consultation</button>
                        </div>
                    </div>
                )}
            </div>
            </div>
        );
    }

    // ── LIST VIEW (default) ───────────────────────────────────────
    // `terms_proposed` is the one a client must not miss — it is the only
    // screen where they see a price before agreeing to it.
    const VISIBLE_ENG = ["requested", "terms_proposed", "accepted"];
    const visibleEngagements = myEngagements.filter(e => VISIBLE_ENG.includes(e.status));
    // Ended ones stay visible as a short history. They used to vanish the
    // moment a lawyer declined or an engagement ended, so the client could not
    // see what happened to a request, or why.
    const ENDED_ENG = ["declined", "cancelled", "completed", "terminated"];
    const endedEngagements = myEngagements
        .filter(e => ENDED_ENG.includes(e.status))
        .sort((a, b) => new Date(b.updated_at || b.responded_at || b.created_at || 0) - new Date(a.updated_at || a.responded_at || a.created_at || 0))
        .slice(0, 5);
    const endedText = (e) => {
        const why = (r) => (r ? ` Reason: ${r}` : "");
        if (e.status === "declined") {
            return e.declined_by === "client"
                ? `You declined the terms.${why(e.decline_reason)}`
                : e.terms_withdrawn
                    ? `${e.lawyer_name || "The lawyer"} withdrew the terms they proposed.${why(e.decline_reason)}`
                    : `${e.lawyer_name || "The lawyer"} declined this request.${why(e.decline_reason)}`;
        }
        if (e.status === "cancelled") return "You withdrew this request.";
        if (e.status === "completed") return "The engagement was completed.";
        return `The engagement was ended.${why(e.termination_reason)}`;
    };
    const FEE_SUFFIX = { hourly: "/hr", per_hearing: "/hearing" };
    const feeLabel = (e) =>
        e.fee_amount
            ? `PKR ${Number(e.fee_amount).toLocaleString()}${FEE_SUFFIX[e.fee_type] || ""}`
            : "";

    const engBtn = (t) => ({
        fontSize: 11, fontWeight: 600, color: t.textMuted, background: "none",
        border: `1px solid ${t.border}`, borderRadius: 8, padding: "4px 10px",
        cursor: "pointer", flexShrink: 0,
    });

    const ENG_BADGE = {
        requested:      { label: "Pending",       color: "#EF9F27" },
        terms_proposed: { label: "Terms received", color: "#3B82F6" },
        accepted:       { label: "Engaged",       color: "#1D9E75" },
        completed:      { label: "Completed",     color: "#6B7280" },
        terminated:     { label: "Ended",         color: "#9CA3AF" },
        declined:       { label: "Declined",      color: "#9CA3AF" },
        cancelled:      { label: "Withdrawn",     color: "#9CA3AF" },
    };
    return (
        <div style={{ position: "relative" }}>
            {showApptModal && renderAppointmentModal()}
            {showHireModal && renderHireModal()}

            {/* The page's own title, as Documents has (2026-10-10): the
                dashboard's top bar is not shown on this page. */}
            <div style={{ margin: "4px 0 24px", display: "flex", alignItems: "center", gap: 16 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                    <h1 style={{ margin: 0, fontFamily: DOCS_FONT, fontSize: 34, fontWeight: 600, color: t.text, letterSpacing: "-0.2px", lineHeight: 1.15 }}>Lawyers</h1>
                    <div style={{ marginTop: 6, fontFamily: DOCS_FONT, fontSize: 14, color: t.textMuted }}>Find a verified lawyer, compare fees and request a consultation.</div>
                </div>
                {/* This page is the list; the map is its own view (2026-10-10). */}
                <style>{MAP_OPEN_CSS}</style>
                <button type="button" data-map-open data-going={mapGoing ? "" : undefined} aria-label="Open map view"
                    onClick={() => {
                        if (mapGoing) return;
                        setMapGoing(true);
                        setTimeout(() => { setMapGoing(false); setActiveView("map"); }, 420);
                    }}>
                    <span className="mo-ic" aria-hidden="true">
                        <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round">
                            <ellipse className="mo-shadow" cx="12" cy="21.5" rx="4" ry="1.2" fill="currentColor" stroke="none" opacity=".45" />
                            <g className="mo-pin">
                                <path d="M12 19.5s6.5-5.6 6.5-11a6.5 6.5 0 1 0-13 0c0 5.4 6.5 11 6.5 11z" />
                                <circle cx="12" cy="8.5" r="2.3" />
                            </g>
                        </svg>
                    </span>
                    <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", lineHeight: 1.15, whiteSpace: "nowrap" }}>
                        Map view
                        <span className="mo-sub">See lawyers on the map</span>
                    </span>
                    <svg className="mo-arrow" width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
                </button>
            </div>

            {/* ── Directory hero (2026-10-10) ─────────────────────────────
                Left: what this page is, and the directory's real totals (the
                server's, never one page's). Right: the AI match -- the way in
                for a client who does not know whom to choose. Below: a running
                request, when there is one, and what every listing guarantees. */}
            <style>{LAWYERS_HERO_CSS}</style>
            <section data-lawyers-hero aria-label="Legal directory">
                <div className="lh-main">
                    <div className="lh-left">
                        <div className="lh-tag"><i aria-hidden="true" />Legal directory</div>
                        <h2 className="lh-title">Find Expert Legal Counsel</h2>
                        <p className="lh-text">Browse listed lawyers and request a consultation time.</p>
                        <div className="lh-stats">
                            {[
                                ["Lawyers listed", dirTotals.all, "All verified", "var(--brand-text)",
                                    "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8",
                                    () => { setFilter("All"); setFilters({ specialization: "All", city: "All", rating: 0, availability: "All" }); }],
                                ["Accepting requests", dirTotals.accepting, "Show only these", "var(--teal-ink)", "M20 6L9 17l-5-5",
                                    () => { setFilter("Available"); setFilters(f => ({ ...f, availability: "Available" })); }],
                                ["Areas of law", AREA_CHIPS.filter(([, v]) => areaCounts[v] > 0).length || null, "With listed lawyers", "var(--gold)",
                                    "M12 3v18M5 7h14M5 7l-3 6a3 3 0 0 0 6 0zM19 7l-3 6a3 3 0 0 0 6 0z",
                                    () => document.querySelector("[data-area-chips]")?.scrollIntoView({ behavior: "smooth", block: "center" })],
                            ].map(([label, value, sub, c, d, go]) => (
                                <button key={label} type="button" className="lh-stat" style={{ "--c": c }} onClick={go}>
                                    <span className="ic" aria-hidden="true">
                                        <svg width={17} height={17} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>
                                    </span>
                                    <span className="v">{value ?? "—"}</span>
                                    <span className="l">{label}</span>
                                    <span className="s">{sub}</span>
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* The AI match: the same states and wording as before, here. */}
                    <div className="lh-ai">
                        <div className="lh-ai-tag">
                            <span aria-hidden="true">
                                <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /></svg>
                            </span>
                            AI match
                        </div>
                        {/* A listing is not a recommendation, so it does not get the
                            recommendation heading. */}
                        <h3 className="lh-ai-title">
                            {aiMatch ? "AI-Recommended Match"
                                : (matchKind === "general_listing" || matchKind === "none") ? "No strong match yet"
                                    : "Not sure who to choose?"}
                        </h3>
                        <p className="lh-ai-text">
                            {aiMatch
                                // No `|| 0.97` fallback, and "match score" -- not
                                // "case compatibility": match_score blends five
                                // factors, of which semantic fit is only half.
                                ? [aiMatch.name, aiMatch.spec,
                                    aiMatch.match_score != null ? `${Math.round(aiMatch.match_score * 100)}% match score` : null,
                                    aiMatch.match_reason || null].filter(Boolean).join(" — ")
                                : matchNotice
                                    ? matchNotice
                                    : getCaseId()
                                        ? "We read your Legal Intake and suggest the lawyer who fits your case best."
                                        : "Fill in your Legal Intake first — it takes about 2 minutes — and we will suggest a lawyer for your case."}
                        </p>
                        <div className="lh-ai-row">
                            {!aiMatch && !getCaseId() ? (
                                <button type="button" className="lh-ai-btn" onClick={() => router.push("/intake")}>
                                    Start intake (2 min)
                                    <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
                                </button>
                            ) : (
                                <button type="button" className="lh-ai-btn" disabled={loadingMatch}
                                    onClick={aiMatch ? () => { setSelectedLawyer(aiMatch); setActiveView("profile"); } : handleAiMatch}>
                                    <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /></svg>
                                    {loadingMatch ? "Matching…" : aiMatch ? "View Match" : "Find My Match"}
                                </button>
                            )}
                            <span className="lh-ai-note">Uses your case type, city and details.</span>
                        </div>
                    </div>
                </div>

                {/* A running hire request, so the next step is one click away. */}
                {(() => {
                    const due = visibleEngagements.find(e => e.status === "terms_proposed");
                    const e = due || visibleEngagements.find(x => x.status === "requested") || visibleEngagements.find(x => x.status === "accepted");
                    if (!e) return null;
                    const more = visibleEngagements.length - 1;
                    const text = e.status === "terms_proposed" ? `${e.lawyer_name || "A lawyer"} sent you terms for ${e.case_title || "your case"}`
                        : e.status === "requested" ? `Waiting for ${e.lawyer_name || "the lawyer"} to answer your request`
                            : `${e.lawyer_name || "Your lawyer"} is engaged on ${e.case_title || "your case"}`;
                    return (
                        <div className="lh-running" data-due={due ? "true" : undefined}>
                            <span className="dot" aria-hidden="true" />
                            <span style={{ flex: 1, minWidth: 0 }}>{text}{more > 0 ? ` · +${more} more` : ""}</span>
                            <button type="button" onClick={() => document.getElementById("my-hire-requests")?.scrollIntoView({ behavior: "smooth", block: "start" })}>
                                {due ? "Review terms" : "View requests"}
                            </button>
                        </div>
                    );
                })()}

                <div className="lh-trust">
                    <span><svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5" /></svg>Every listed lawyer is KYC-verified</span>
                    <span><svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5" /></svg>Fees shown before you book</span>
                    <span><svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5" /></svg>Hire only after a consultation</span>
                </div>
            </section>

            {/* Toolbar (2026-10-10, the approved redesign): search, the
                "Accepting requests" chip, Filters, Sort and List | Map in one
                line. The Filters panel below is unchanged. */}
            <style>{LAWYERS_TOOLS_CSS}</style>
            <div data-lawyers-tools style={{ display: "flex", gap: 10, marginBottom: 14, alignItems: "center", flexWrap: "wrap" }}>
                <label className="lt-search">
                    <Ic n="search" s={17} c="var(--faint)" />
                    <span style={{ position: "absolute", left: -9999 }}>Search lawyers</span>
                    <input ref={searchRef} type="search" value={query} onChange={e => setQuery(e.target.value)}
                        placeholder="Search by name, specialization or city" />
                    {query
                        ? <button type="button" onClick={() => setQuery("")} aria-label="Clear search" className="lt-clear">×</button>
                        : <span className="lt-kbd" aria-hidden="true">/</span>}
                </label>

                {/* Only lawyers taking new requests -- not a live schedule claim. */}
                <button type="button" className="lt-pill lt-accepting" aria-pressed={filter === "Available"}
                    onClick={() => {
                        const on = filter !== "Available";
                        setFilter(on ? "Available" : "All");
                        setFilters(prev => ({ ...prev, availability: on ? "Available" : "All" }));
                    }}>
                    <span className="dot" aria-hidden="true" />Accepting requests
                </button>

                <LawyerSort value={sortBy} options={sortOptions} onChange={setSortBy} />

                <button type="button" className="lt-pill" aria-expanded={showFilters} data-open={showFilters ? "true" : undefined} onClick={() => setShowFilters(f => !f)}>
                    <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="var(--teal-ink)" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M4 7h16M7 12h10M10 17h4" /></svg>
                    Filters
                    {activeFilterCount > 0 && <span className="lt-count">{activeFilterCount}</span>}
                </button>
            </div>

            {/* Areas of law, one tap each (2026-10-10). The same filter as
                Filters → Specialization; counts are the server's. */}
            <div data-lawyers-tools data-area-chips role="group" aria-label="Area of law" className="lt-areas" style={{ display: "flex", gap: 8, flexWrap: "nowrap", alignItems: "center", margin: "22px 0 28px", overflowX: "auto" }}>
                {[["All", "All areas", null], ...AREA_CHIPS.map(([label, value, c]) => [value, label, c])].map(([value, label, c]) => (
                    <button key={value} type="button" className="lt-area" aria-pressed={filters.specialization === value}
                        style={c ? { "--c": c } : undefined}
                        onClick={() => setFilters(f => ({ ...f, specialization: value }))}>
                        {c && <span className="dot" aria-hidden="true" />}{label}
                        {areaCounts[value] != null && value !== "All" && <span className="n">{areaCounts[value]}</span>}
                    </button>
                ))}
            </div>

            {/* Filter Panel (restyled 2026-10-10 on the client theme; same fields) */}
            {showFilters && (
                <section data-lawyers-panel aria-label="Filters">
                    <style>{LAWYERS_PANEL_CSS}</style>
                    <header className="lp-head">
                        <span className="lp-ic" aria-hidden="true">
                            <svg width={17} height={17} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" /></svg>
                        </span>
                        <div>
                            <h3 className="lp-title">Filters</h3>
                            <div className="lp-sub">Narrow the directory. Changes apply as you choose.</div>
                        </div>
                        <button type="button" className="lp-x" aria-label="Close filters" onClick={() => setShowFilters(false)}>
                            <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
                        </button>
                    </header>

                    <div className="lp-body rgrid-2">
                        <div>
                            <div className="lp-label">
                                <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><rect x="2" y="7" width="20" height="14" rx="2" /><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2" /></svg>
                                Specialization
                            </div>
                            <div className="lp-select" data-on={filters.specialization !== "All" ? "" : undefined}>
                                <select aria-label="Specialization" value={filters.specialization} onChange={e => setFilters(f => ({ ...f, specialization: e.target.value }))}>
                                    <option value="All">All specializations</option>
                                    {AREA_CHIPS.map(([label, value]) => <option key={value} value={value}>{label}</option>)}
                                </select>
                                <svg className="chev" width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
                            </div>
                        </div>
                        <div>
                            <div className="lp-label">
                                <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" /><circle cx="12" cy="10" r="3" /></svg>
                                City
                            </div>
                            <div className="lp-select" data-on={filters.city !== "All" ? "" : undefined}>
                                <select aria-label="City" value={filters.city} onChange={e => setFilters(f => ({ ...f, city: e.target.value }))}>
                                    <option value="All">All cities</option>
                                    {cities.filter(c => c !== "All").map(c => <option key={c}>{c}</option>)}
                                </select>
                                <svg className="chev" width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
                            </div>
                        </div>

                        <div>
                            <div className="lp-label">
                                <svg className="gold" width={13} height={13} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" /></svg>
                                Rating
                            </div>
                            <div role="radiogroup" aria-label="Rating" className="lp-chips">
                                {[{ label: "Any", val: 0 }, { label: "3+", val: 3 }, { label: "4+", val: 4 }, { label: "4.5+", val: 4.5 }, { label: "5.0", val: 5 }].map(({ label, val }) => (
                                    <button key={label} type="button" role="radio" aria-checked={filters.rating === val} className={val > 0 ? "lp-chip star" : "lp-chip"}
                                        onClick={() => setFilters(f => ({ ...f, rating: val }))}>
                                        {val > 0 && <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" /></svg>}
                                        {label}
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Availability: whether a lawyer is taking new requests -- the
                            server's own flag, not a live schedule. Kept in step with the
                            toolbar's "Accepting requests" chip. */}
                        <div>
                            <div className="lp-label">
                                <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
                                Availability
                            </div>
                            <div data-availability-options role="radiogroup" aria-label="Availability" className="lp-chips">
                                {[{ label: "Any", val: "All", c: null }, { label: "Accepting requests", val: "Available", c: "var(--brand-text)" }, { label: "Not accepting", val: "Busy", c: "var(--faint)" }].map(({ label, val, c }) => (
                                    <button key={val} type="button" role="radio" aria-checked={filters.availability === val} className="lp-chip"
                                        style={c ? { "--c": c } : undefined}
                                        onClick={() => { setFilter(val === "Available" ? "Available" : "All"); setFilters(f => ({ ...f, availability: val })); }}>
                                        {c && <span className="dot" aria-hidden="true" />}
                                        {label}
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>

                    <footer className="lp-foot">
                        <span className="lp-count"><b>{filtered.length}</b> {filtered.length === 1 ? "lawyer matches" : "lawyers match"}</span>
                        <button type="button" className="lp-reset" onClick={() => { setFilter("All"); setFilters({ specialization: "All", city: "All", rating: 0, availability: "All" }); }}>
                            <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><polyline points="1 4 1 10 7 10" /><path d="M3.51 15a9 9 0 1 0 .49-4.5" /></svg>
                            Reset
                        </button>
                        <button type="button" className="lp-show" onClick={() => setShowFilters(false)}>
                            Show {filtered.length} {filtered.length === 1 ? "lawyer" : "lawyers"}
                            <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
                        </button>
                    </footer>
                </section>
            )}

            {/* My hire requests */}
            {(visibleEngagements.length > 0 || endedEngagements.length > 0) && (
                <div id="my-hire-requests" style={{ scrollMarginTop: 16, background: t.card, border: `1.5px solid ${t.border}`, borderRadius: 16, padding: "14px 18px", marginBottom: 20 }}>
                    <div style={{ fontSize: 12, fontWeight: 800, color: t.text, textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
                        <Ic n="shield" s={14} c={t.primary} /> My Hire Requests
                    </div>
                    {visibleEngagements.map(e => {
                        const badge = ENG_BADGE[e.status];
                        return (
                            <div key={e.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 0", borderBottom: `1px solid ${t.border}` }}>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontSize: 13, fontWeight: 700, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                        {e.lawyer_name || "Lawyer"} · {e.case_title || e.case_number}
                                    </div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>
                                        {e.status === "accepted"
                                            ? `Engaged${feeLabel(e) ? ` — ${feeLabel(e)}` : ""}. Track progress on the Tracking page.`
                                            : e.status === "terms_proposed"
                                                ? `${e.lawyer_name || "The lawyer"} proposed ${feeLabel(e) || "terms"}. Nothing is agreed until you accept.`
                                                : "Waiting for the lawyer to respond…"}
                                    </div>
                                    {e.status === "terms_proposed" && e.scope_note && (
                                        <div style={{ fontSize: 11, color: t.textDim, marginTop: 4, fontStyle: "italic" }}>
                                            Scope: {e.scope_note}
                                        </div>
                                    )}
                                    {e.status === "accepted" && e.completion_proposed_by && (
                                        <div style={{ fontSize: 11, color: t.primary, marginTop: 4 }}>
                                            {e.completion_proposed_by === "lawyer"
                                                ? "Your lawyer says the work is finished — confirm to close this engagement."
                                                : "You proposed completion; waiting for your lawyer to confirm."}
                                        </div>
                                    )}
                                </div>
                                <span style={{ fontSize: 11, fontWeight: 700, color: badge.color, background: `${badge.color}18`, borderRadius: 20, padding: "3px 10px", flexShrink: 0 }}>{badge.label}</span>

                                {e.status === "requested" && (
                                    <button onClick={() => withdrawRequest(e.id)} disabled={engBusy === e.id}
                                        style={engBtn(t)}>
                                        Withdraw
                                    </button>
                                )}

                                {e.status === "terms_proposed" && (
                                    <>
                                        <button onClick={() => declineTerms(e)} disabled={engBusy === e.id}
                                            style={engBtn(t)}>
                                            Decline
                                        </button>
                                        <button onClick={() => acceptTerms(e)} disabled={engBusy === e.id}
                                            style={{ ...engBtn(t), color: "#fff", background: t.primary, border: `1px solid ${t.primary}` }}>
                                            {engBusy === e.id ? "Accepting…" : "Accept terms"}
                                        </button>
                                    </>
                                )}

                                {e.status === "accepted" && (
                                    <>
                                        <button onClick={() => markComplete(e)} disabled={engBusy === e.id}
                                            style={engBtn(t)}>
                                            {e.completion_proposed_by === "lawyer" ? "Confirm complete" : "Mark complete"}
                                        </button>
                                        <button onClick={() => endEngagement(e)} disabled={engBusy === e.id}
                                            style={{ ...engBtn(t), color: "#B91C1C", borderColor: "#FCA5A5" }}>
                                            End engagement
                                        </button>
                                    </>
                                )}
                            </div>
                        );
                    })}
                    {endedEngagements.length > 0 && (
                        <div data-ended-engagements style={{ marginTop: visibleEngagements.length ? 12 : 0 }}>
                            <div style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.6px", margin: "4px 0 2px" }}>Past requests</div>
                            {endedEngagements.map(e => {
                                const badge = ENG_BADGE[e.status];
                                return (
                                    <div key={e.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 0", borderBottom: `1px solid ${t.border}` }}>
                                        <div style={{ flex: 1, minWidth: 0 }}>
                                            <div style={{ fontSize: 12.5, fontWeight: 600, color: t.textDim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                                {e.lawyer_name || "Lawyer"} · {e.case_title || e.case_number}
                                            </div>
                                            <div style={{ fontSize: 11, color: t.textMuted, overflowWrap: "anywhere" }}>{endedText(e)}</div>
                                        </div>
                                        <span style={{ fontSize: 11, fontWeight: 700, color: badge.color, background: `${badge.color}18`, borderRadius: 20, padding: "3px 10px", flexShrink: 0 }}>{badge.label}</span>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            )}

            {/* AI Match box (2026-10-10). "Find My Match" turns the text into a
                message box; what the client writes is read in the browser into
                the list's own filters (area of law, province), which they can
                see and clear. Nothing typed here is sent to the server. */}
            <section data-ai-ask data-open={askOpen ? "" : undefined} aria-label="AI match">
                <style>{AI_ASK_CSS}</style>
                {!askOpen ? (
                <div className="aa-row">
                    <div style={{ width: 42, height: 42, borderRadius: 13, background: `${t.primary}20`, display: "flex", alignItems: "center", justifyContent: "center" }}>
                        <Ic n="zap" s={20} c={t.primary} />
                    </div>
                    <div style={{ flex: 1 }}>
                        {/* A listing is not a recommendation, so it does not get the
                            recommendation heading. */}
                        <div style={{ fontWeight: 700, color: t.text, fontSize: 13 }}>
                            {!aiMatch && (matchKind === "general_listing" || matchKind === "none")
                                ? "No strong match yet"
                                : "AI-Recommended Match"}
                        </div>
                        <div style={{ fontSize: 12, color: t.textMuted }}>
                            {aiMatch
                                // No `|| 0.97` fallback. A missing score used to
                                // render as "97% case compatibility" on lawyers the
                                // matcher had never scored against the case.
                                ? [
                                    aiMatch.name,
                                    aiMatch.spec,
                                    // "match score", not "case compatibility".
                                    // match_score is a weighted blend of five
                                    // factors — semantic fit is only half of it,
                                    // the rest is specialization, province, rating,
                                    // availability and experience. A lawyer with no
                                    // measured relevance to the case still scores
                                    // ~0.48 on the other factors alone, and calling
                                    // that "48% case compatibility" claims a
                                    // measurement of fit the number does not carry.
                                    aiMatch.match_score != null
                                        ? `${Math.round(aiMatch.match_score * 100)}% match score`
                                        : null,
                                    aiMatch.match_reason || null,
                                ].filter(Boolean).join(" — ")
                                : matchNotice
                                    ? matchNotice
                                    : getCaseId()
                                        ? "Describe your problem to filter the list, or match from your intake case"
                                        : "Describe your problem and we'll filter the list for you"}
                        </div>
                    </div>
                    <BtnPrimary
                        disabled={loadingMatch}
                        onClick={aiMatch
                            ? () => { setSelectedLawyer(aiMatch); setActiveView("profile"); }
                            : () => { setAskOpen(true); setTimeout(() => askRef.current?.focus(), 0); }
                        }
                        style={{ fontSize: 12, padding: "10px 18px", flexShrink: 0, opacity: loadingMatch ? 0.7 : 1 }}
                    >
                        {loadingMatch ? "Matching…" : aiMatch ? "View Match" : "Find My Match"}
                    </BtnPrimary>
                </div>
                ) : (
                    <form className="aa-row" onSubmit={e => {
                        e.preventDefault();
                        const text = askText.trim();
                        if (!text) return;
                        const read = readProblem(text);
                        setAskResult({ ...read, text });
                        if (read.area || read.province) {
                            setFilters(f => ({
                                ...f,
                                specialization: read.area || "All",
                                city: read.province || "All",
                            }));
                        }
                    }}>
                        <span className="aa-ic" aria-hidden="true"><Ic n="zap" s={20} c={t.primary} /></span>
                        <label className="aa-field">
                            <span style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>Describe your problem</span>
                            <input ref={askRef} type="text" value={askText} maxLength={PROBLEM_MAX_LENGTH}
                                onChange={e => setAskText(e.target.value)}
                                onKeyDown={e => { if (e.key === "Escape") setAskOpen(false); }}
                                placeholder="Apna masla likhein… e.g. mere bhai ne plot par qabza kar liya hai (Lahore)" />
                            <span className="aa-hint" aria-hidden="true">Enter ↵</span>
                        </label>
                        <button type="submit" className="aa-send" disabled={!askText.trim()}>
                            <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" /></svg>
                            Send
                        </button>
                        <button type="button" className="aa-x" aria-label="Close" onClick={() => setAskOpen(false)}>
                            <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
                        </button>
                    </form>
                )}

                {askOpen && askResult && (
                    <div className="aa-out" role="status">
                        {askResult.area || askResult.province ? (<>
                            <span>Filtered the list for:</span>
                            {askResult.area && <span className="aa-tag">{askResult.areaLabel}</span>}
                            {askResult.province && <span className="aa-tag">{askResult.province}</span>}
                            <span>· {pageInfo.total} lawyer{pageInfo.total === 1 ? "" : "s"}</span>
                            <button type="button" className="aa-link" onClick={() => {
                                setAskResult(null);
                                setFilters(f => ({ ...f, specialization: "All", city: "All" }));
                            }}>Clear</button>
                        </>) : (
                            <span>Could not tell the area of law from that. Try words like "divorce", "FIR", "plot" or "salary", or pick an area above.</span>
                        )}
                        {getCaseId() && (
                            <button type="button" className="aa-link" disabled={loadingMatch} onClick={handleAiMatch}>
                                {loadingMatch ? "Matching…" : "Or match from my intake case"}
                            </button>
                        )}
                    </div>
                )}
            </section>

            {/* Results count.
                Reports the page AND the total, because `filtered.length` alone
                is the size of one page — it read "Showing 20 lawyers" whether
                the directory held 20 or 2000. */}
            <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 12 }}>
                Showing <span style={{ color: t.primary, fontWeight: 700 }}>{filtered.length}</span>
                {" "}of <span style={{ color: t.primary, fontWeight: 700 }}>{pageInfo.total}</span> lawyers
                {pageInfo.pages > 1 && <> · page {page} of {pageInfo.pages}</>}
            </div>

            {/* ── LAWYER CARDS (2026-10-10, the approved mockup) ──────────
                Every lawyer listed here is KYC-verified (the directory query
                requires it). Empty fields say so in words, never "0yr" or "—". */}
            <style>{LAWYERS_CARD_CSS}</style>
            <div data-lawyers-grid style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(270px,320px))", gap: 16 }}>
                {filtered.map((l) => {
                    const specs = String(l.spec || "").split(",").map(s => s.trim()).filter(Boolean);
                    const shownSpecs = specs.slice(0, 2);
                    return (
                        <article key={l._id || l.bar} className="lc-card" onClick={() => { setSelectedLawyer(l); setActiveView("profile"); }}>
                            <div className="lc-head">
                                <span className="lc-av" aria-hidden="true">{l.name.split(" ").map(w => w[0]).join("").slice(0, 2)}</span>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div className="lc-name-row">
                                        <div className="lc-name">{l.name}</div>
                                        <span className="lc-verified">
                                            <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5" /></svg>
                                            Verified
                                        </span>
                                    </div>
                                    <div className="lc-bar">{l.bar ? `Bar: ${l.bar}` : "Bar number not provided"}</div>
                                </div>
                                <span className="lc-avail" data-off={l.avail ? undefined : "true"}>{l.avail ? "● Accepting" : "○ Not accepting"}</span>
                            </div>

                            <div className="lc-chips">
                                {shownSpecs.map(s => <span key={s}>{s}</span>)}
                                {specs.length > shownSpecs.length && <span>+{specs.length - shownSpecs.length}</span>}
                            </div>

                            <div className="lc-rating" data-none={l.reviews > 0 ? undefined : "true"}>
                                {l.reviews > 0 ? <>★ {Number(l.rating).toFixed(1)} · {l.reviews} review{l.reviews === 1 ? "" : "s"}</> : "No reviews yet"}
                            </div>

                            <div className="lc-facts">
                                <div><b>{l.exp > 0 ? `${l.exp} yr${l.exp === 1 ? "" : "s"}` : "New"}</b><span>experience</span></div>
                                <div><b>{l.fee ? `Rs ${l.fee.toLocaleString()}` : "On request"}</b><span>fee per hour</span></div>
                                <div><b>{l.city}</b><span>province</span></div>
                            </div>

                            <div className="lc-actions" onClick={e => e.stopPropagation()}>
                                <button type="button" className="lc-book" disabled={!l.avail}
                                    title={l.avail ? undefined : "This lawyer is not taking new requests"}
                                    onClick={() => { if (l.avail) openBooking(l); }}>
                                    <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M16 3v4M8 3v4M3 11h18" /></svg>
                                    Book consultation
                                </button>
                                <button type="button" className="lc-view" onClick={() => { setSelectedLawyer(l); setActiveView("profile"); }}>
                                    View profile
                                    <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
                                </button>
                            </div>
                        </article>
                    );
                })}

                {filtered.length === 0 && (
                    <div style={{ gridColumn: "1/-1", textAlign: "center", padding: "48px 0", color: t.textMuted }}>
                        <Ic n="search" s={32} c={t.border} />
                        <div style={{ marginTop: 12, fontSize: 14 }}>No lawyers match your search criteria.</div>
                        <button onClick={() => { setQuery(""); setFilter("All"); setFilters({ specialization: "All", city: "All", rating: 0, availability: "All" }); }} style={{ marginTop: 10, background: "none", border: "none", color: t.primary, cursor: "pointer", fontSize: 13, fontWeight: 600 }}>Clear all filters</button>
                    </div>
                )}
            </div>

            {/* ── Pagination ─────────────────────────────────────────
                The control that makes the rest of the directory reachable at
                all. Everything past the first page existed in the database and
                had no route to the screen. */}
            {pageInfo.pages > 1 && (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 14, marginTop: 24 }}>
                    <BtnOutline
                        onClick={() => setPage(p => Math.max(1, p - 1))}
                        disabled={page <= 1 || loadingLawyers}
                        style={{ opacity: page <= 1 ? 0.45 : 1, cursor: page <= 1 ? "not-allowed" : "pointer" }}>
                        ← Previous
                    </BtnOutline>
                    <span style={{ fontSize: 13, color: t.textMuted }}>
                        Page <span style={{ color: t.text, fontWeight: 700 }}>{page}</span> of {pageInfo.pages}
                    </span>
                    <BtnOutline
                        onClick={() => setPage(p => Math.min(pageInfo.pages, p + 1))}
                        disabled={page >= pageInfo.pages || loadingLawyers}
                        style={{ opacity: page >= pageInfo.pages ? 0.45 : 1, cursor: page >= pageInfo.pages ? "not-allowed" : "pointer" }}>
                        Next →
                    </BtnOutline>
                </div>
            )}
        </div>
    );
};

export default ModLawyers;
