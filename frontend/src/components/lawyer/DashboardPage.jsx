'use client';
// Lawyer dashboard (v3, 2026-10-10). Built to current dashboard practice:
//   • one clear lead — the Daily brief says what matters today and what to do
//   • few, glanceable blocks; detail on demand (tabs, "show more")
//   • critical dates first — overdue and upcoming tasks and hearings, by urgency
//   • colour only where it means something (overdue, due soon, done)
//   • empty dashboards teach: a setup checklist until the practice is ready
//   • the lawyer's own layout: sections can be hidden and brought back
// Everything comes from real records. The brief is assembled from the
// lawyer's calendar, cases and inbox by rules — it is not model output.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTheme, useCase, useNotif } from "./theme.js";
import { formatPkt, pktToday, pktDayKey } from "@/lib/bookingTime.js";
import { useAuth } from "@/context/AuthContext.jsx";
import { DRAFTING_TOKENS_CSS, draftingMode } from "./draftingTheme.js";
import { CSB, fmtDate } from "./data.js";
import { Badge } from "./components.jsx";
import { ModalPortal } from "./ui.jsx";
import {
    listCases, listAppointments, listLawyerEvents, reviewQueueV2, listReviewQueue, errorCode,
    listTasks, getMe, listMyKycDocuments, getMyWorkingHours,
} from "@/lib/api.js";
import { caseStatusLabel } from "@/lib/caseStatus.js";

/* ── time ── */
const addDays = (key, n) => { const d = new Date(`${key}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const dayName = (key, opts) => new Date(`${key}T12:00:00Z`).toLocaleDateString("en-GB", { timeZone: "UTC", ...opts });
const hm = (iso) => formatPkt(iso, { hour: "2-digit", minute: "2-digit", hour12: false });
const daysBetween = (a, b) => Math.round((new Date(`${b}T12:00:00Z`) - new Date(`${a}T12:00:00Z`)) / 864e5);
const ago = (t0, now) => {
    const m = Math.max(0, Math.round((now - t0) / 60000));
    return m < 1 ? "just now" : m < 60 ? `${m} min ago` : `${Math.round(m / 60)} h ago`;
};
const whenWord = (key, today) => {
    const d = daysBetween(today, key);
    return d === 0 ? "Today" : d === 1 ? "Tomorrow" : d === -1 ? "Yesterday" : d < 0 ? `${-d} days ago` : d < 7 ? dayName(key, { weekday: "long" }) : dayName(key, { day: "numeric", month: "short" });
};

function _mapCase(c) {
    return {
        id: c.case_number || c._id,
        _id: c._id,
        title: c.title || "Untitled Case",
        client: c.client_name || "—",
        court: c.province || "—",
        type: c.case_type ? c.case_type.charAt(0).toUpperCase() + c.case_type.slice(1) : "Other",
        status: caseStatusLabel(c.status),
        // The earliest hearing still ahead with no outcome. Insertion order is
        // not date order: a hearing added later can be sooner, and a
        // rescheduled one moves in place.
        nextHearing: (c.hearing_dates || [])
            .filter(h => !h.outcome && h.date && pktDayKey(h.date) >= pktToday())
            .sort((x, y) => new Date(x.date) - new Date(y.date))[0]?.date || "",
    };
}

/* ── icons ── */
const P = {
    sparkle: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z",
    pen: ["M12 20h9", "M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"],
    cal: ["M4 6h16a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1z", "M16 3v4M8 3v4M3 11h18"],
    doc: ["M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z", "M14 3v6h6", "m9 15 2 2 4-4"],
    chat: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
    clock: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M12 6v6l4 2"],
    shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
    gavel: ["M14 4l6 6-8 8-2-2", "M5.5 7l2 2", "M3 21l5.5-5.5", "M14.5 4.5L18 8"],
    arrow: "M5 12h14M13 6l6 6-6 6",
    alert: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M12 8v4M12 16h.01"],
    search: ["M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14z", "m20 20-3.5-3.5"],
    list: ["M8 6h13M8 12h13M8 18h13", "M3.5 6h.01M3.5 12h.01M3.5 18h.01"],
    refresh: ["M21 12a9 9 0 1 1-2.6-6.4", "M21 4v5h-5"],
    check: "M20 6 9 17l-5-5",
    sliders: ["M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3", "M1 14h6M9 8h6M17 16h6"],
};
const Svg = ({ d, size = 18 }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {[].concat(d).map((p, i) => <path key={i} d={p} />)}
    </svg>
);

const KIND = {
    hearing: { c: "#B9A6F5", label: "Hearing" },
    appointment: { c: "#3CCFE0", label: "Appointment" },
    event: { c: "#93A4A8", label: "Diary" },
};
// One quiet row of shortcuts: the sidebar already lists every page, so these
// are the six a lawyer starts the day with, not a second navigation.
const QUICK = [
    { pg: "cases", icon: "shield", title: "Cases" },
    { pg: "appointments", icon: "cal", title: "Calendar" },
    { pg: "causelist", icon: "list", title: "Cause List" },
    { pg: "ai-legal", icon: "chat", title: "AI Assistant" },
    { pg: "doc-automation", icon: "pen", title: "Legal Drafting" },
    { pg: "documents", icon: "doc", title: "Documents" },
];
// Sections the lawyer can hide. Saved in this browser, per account.
const SECTIONS = [
    ["setup", "Setup checklist"], ["brief", "Daily brief"], ["numbers", "Key numbers"], ["quick", "Shortcuts"],
    ["dates", "Critical dates"], ["schedule", "Schedule"], ["activity", "Recent activity"], ["cases", "Recent cases"],
];

/* A number that counts up to its value once. Text that is not a plain count is
   shown as it is; so is everything under reduced motion or without animation
   frames (tests). */
function CountUp({ value }) {
    const m = /^(\d+)(\+?)$/.exec(String(value));
    const target = m ? Number(m[1]) : null;
    const [shown, setShown] = useState(target);
    const prev = useRef(null);
    useEffect(() => {
        if (target === null) return undefined;
        const from = prev.current ?? 0;
        prev.current = target;
        const still = typeof requestAnimationFrame !== "function"
            || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
        if (still || from === target) { setShown(target); return undefined; }
        let raf = 0;
        const t0 = performance.now();
        const step = (t) => {
            const k = Math.min(1, (t - t0) / 700);
            setShown(Math.round(from + (target - from) * (1 - Math.pow(1 - k, 3))));
            if (k < 1) raf = requestAnimationFrame(step);
        };
        raf = requestAnimationFrame(step);
        return () => cancelAnimationFrame(raf);
    }, [target]);
    return target === null ? value : `${shown ?? target}${m[2]}`;
}

/* Ctrl/Cmd+K: every page, and "ask the AI" for whatever was typed. */
const PAGES = [
    ["cases", "Cases"], ["clients", "Clients"], ["appointments", "Appointments"], ["causelist", "Cause List"],
    ["ai-legal", "AI Assistant"], ["caselaw", "Legal Library"], ["doc-automation", "Legal Drafting"], ["documents", "Document Review"],
    ["vault", "Vault"], ["doc-analyzer", "Document Analyzer"], ["agreements", "Agreements"], ["payments", "Payments"],
    ["bail-checker", "Bail Checker"], ["calculators", "Calculators"], ["profile", "Profile"], ["settings", "Settings"],
].map(([pg, label]) => ({ pg, label }));
function Palette({ mode, onClose, onGo, onAsk }) {
    const [q, setQ] = useState("");
    const [i, setI] = useState(0);
    const listRef = useRef(null);
    // Arrow keys keep the chosen row in view.
    useEffect(() => { listRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" }); }, [i]);
    const term = q.trim().toLowerCase();
    const rows = [
        ...PAGES.filter(p => !term || p.label.toLowerCase().includes(term)).map(p => ({ kind: "page", ...p })),
        ...(term ? [{ kind: "ask", label: `Ask AI: “${q.trim()}”` }] : []),
    ];
    const pick = (r) => (r.kind === "ask" ? onAsk(q.trim()) : onGo(r.pg));
    const onKey = (e) => {
        if (e.key === "Escape") onClose();
        else if (e.key === "ArrowDown") { e.preventDefault(); setI(v => Math.min(rows.length - 1, v + 1)); }
        else if (e.key === "ArrowUp") { e.preventDefault(); setI(v => Math.max(0, v - 1)); }
        else if (e.key === "Enter" && rows[i]) pick(rows[i]);
    };
    return (
        <ModalPortal>
            <div data-dash-ws data-drafting-theme data-mode={mode} style={{ minHeight: 0, padding: 0, background: "none" }}>
                <div className="db-pal-scrim" data-lenis-prevent onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
                    <div className="db-pal" role="dialog" aria-modal="true" aria-label="Search or jump to">
                        <label className="db-pal-in">
                            <Svg d={P.search} />
                            <input autoFocus value={q} onChange={e => { setQ(e.target.value); setI(0); }} onKeyDown={onKey}
                                placeholder="Go to a page, or type a question for the AI…" aria-label="Search or jump to" />
                            <kbd>Esc</kbd>
                        </label>
                        <div className="db-pal-list" role="listbox" data-lenis-prevent ref={listRef}>
                            {rows.map((r, n) => (
                                <button key={r.kind + (r.pg || "")} type="button" role="option" aria-selected={n === i}
                                    className={`db-pal-row${n === i ? " on" : ""}`} onMouseEnter={() => setI(n)} onClick={() => pick(r)}>
                                    <Svg d={r.kind === "ask" ? P.sparkle : P.arrow} size={16} />
                                    <span>{r.label}</span>
                                    {n === i && <kbd>Enter</kbd>}
                                </button>
                            ))}
                            {!rows.length && <div className="db-empty">Nothing matches.</div>}
                        </div>
                    </div>
                </div>
            </div>
        </ModalPortal>
    );
}

const CSS = `[data-dash-ws]{flex:none;min-height:100%;color:var(--ink);font-family:"Hanken Grotesk",system-ui,sans-serif;-webkit-font-smoothing:antialiased;background:var(--bg);padding:22px 30px 48px;box-sizing:border-box}
[data-dash-ws] *{box-sizing:border-box}
[data-dash-ws] button,[data-dash-ws] input,[data-dash-ws] textarea{font-family:inherit}
[data-dash-ws] :focus-visible{outline:2px solid var(--brand-text);outline-offset:2px}
[data-dash-ws] .db-wrap{max-width:1280px;margin:0 auto;display:grid;gap:18px}
[data-dash-ws] .db-wrap > *{animation:dbUp .5s cubic-bezier(.2,.7,.2,1) both}
[data-dash-ws] .db-wrap > :nth-child(2){animation-delay:.05s}
[data-dash-ws] .db-wrap > :nth-child(3){animation-delay:.1s}
[data-dash-ws] .db-wrap > :nth-child(n+4){animation-delay:.15s}
@keyframes dbUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){[data-dash-ws] *{animation:none!important;transition:none!important}}
[data-dash-ws] .db-top{position:relative;z-index:20;display:flex;align-items:flex-end;justify-content:space-between;gap:18px;flex-wrap:wrap}
[data-dash-ws] .db-date{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:13.5px;color:var(--muted)}
[data-dash-ws] .db-date b{color:var(--ink);font-weight:600}
[data-dash-ws] .db-h1{margin:4px 0 0;font-family:"Literata",Georgia,serif;font-size:36px;font-weight:600;letter-spacing:-.01em;line-height:1.15}
[data-dash-ws] .db-fresh{display:inline-flex;align-items:center;gap:6px;height:26px;padding:0 10px;border-radius:999px;border:1px solid var(--line);background:none;color:var(--muted);font-size:12.5px;cursor:pointer}
[data-dash-ws] .db-fresh:hover{border-color:var(--brand-text);color:var(--ink)}
[data-dash-ws] .db-fresh.spin svg{animation:dbSpin .8s linear infinite}
@keyframes dbSpin{to{transform:rotate(360deg)}}
[data-dash-ws] .db-tools{display:flex;gap:8px;align-items:center;position:relative}
[data-dash-ws] .db-cmdk{display:inline-flex;align-items:center;gap:10px;height:42px;min-width:280px;padding:0 10px 0 14px;border-radius:12px;border:1px solid var(--line-strong);background:var(--input);color:var(--muted);font-size:14px;cursor:pointer;text-align:left}
[data-dash-ws] .db-cmdk span{flex:1}
[data-dash-ws] .db-cmdk:hover{border-color:var(--brand-text);color:var(--ink)}
[data-dash-ws] .db-icon{width:42px;height:42px;display:grid;place-items:center;border-radius:12px;border:1px solid var(--line-strong);background:var(--surface);color:var(--muted);cursor:pointer}
[data-dash-ws] .db-icon:hover,[data-dash-ws] .db-icon[aria-expanded="true"]{border-color:var(--brand-text);color:var(--ink)}
[data-dash-ws] kbd{padding:2px 7px;border-radius:6px;border:1px solid var(--line-strong);border-bottom-width:2px;font-family:"JetBrains Mono",ui-monospace,monospace;font-size:11.5px;color:var(--muted);background:var(--surface)}
[data-dash-ws] .db-btn{display:inline-flex;align-items:center;gap:8px;height:42px;padding:0 16px;border-radius:12px;border:1px solid var(--line-strong);background:var(--surface);color:var(--ink);font-size:14px;font-weight:700;cursor:pointer;white-space:nowrap}
[data-dash-ws] .db-btn:hover{border-color:var(--brand-text)}
[data-dash-ws] .db-btn.pri{border:0;background:linear-gradient(135deg,#3EE0A1,#2EC4D6);color:#04212A}
[data-dash-ws] .db-btn.sm{height:34px;padding:0 12px;font-size:13px;border-radius:10px}
[data-dash-ws] .db-custom{position:absolute;top:calc(100% + 8px);right:0;z-index:30;width:260px;padding:10px;border-radius:14px;background:var(--surface);border:1px solid var(--line-strong);box-shadow:0 20px 44px -14px rgba(0,0,0,.65)}
[data-dash-ws] .db-custom b{display:block;padding:4px 6px 8px;font-size:13px}
[data-dash-ws] .db-tog{display:flex;align-items:center;justify-content:space-between;width:100%;height:36px;padding:0 8px;border:0;border-radius:8px;background:none;color:var(--ink);font-size:13.5px;cursor:pointer}
[data-dash-ws] .db-tog:hover{background:var(--surface-2)}
[data-dash-ws] .db-tog i{position:relative;width:34px;height:20px;border-radius:999px;background:var(--line-strong);transition:background .15s}
[data-dash-ws] .db-tog i::after{content:"";position:absolute;top:3px;left:3px;width:14px;height:14px;border-radius:50%;background:#fff;transition:left .15s}
[data-dash-ws] .db-tog[aria-pressed="true"] i{background:#2EC4A0}
[data-dash-ws] .db-tog[aria-pressed="true"] i::after{left:17px}
[data-dash-ws] .db-card{background:var(--surface);border:1px solid var(--line);border-radius:18px;overflow:hidden}
[data-dash-ws] .db-ch{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:16px 20px;border-bottom:1px solid var(--line)}
[data-dash-ws] .db-ch h2{margin:0;font-family:"Literata",Georgia,serif;font-size:20px;font-weight:600}
[data-dash-ws] .db-ch h2 small{font-family:"Hanken Grotesk",sans-serif;font-size:13px;font-weight:500;color:var(--muted);margin-left:8px}
[data-dash-ws] .db-link{border:0;background:none;padding:0;color:var(--brand-text);font-size:13.5px;font-weight:700;cursor:pointer}
[data-dash-ws] .db-link:hover{text-decoration:underline}
[data-dash-ws] .db-empty{padding:20px;font-size:14px;color:var(--muted);line-height:1.5}
[data-dash-ws] .db-case{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:12px;font-weight:700;color:var(--brand-text);padding:2px 8px;border-radius:7px;border:1px solid color-mix(in srgb,var(--brand-text) 35%,transparent);white-space:nowrap}
[data-dash-ws] .db-setup{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;padding:16px 20px 20px}
[data-dash-ws] .db-step{display:grid;gap:6px;align-content:start;padding:16px;border-radius:14px;background:var(--surface-2);border:1px solid var(--line);text-align:left;color:var(--ink);cursor:pointer}
[data-dash-ws] .db-step:hover:not(:disabled){border-color:var(--brand-text)}
[data-dash-ws] .db-step .n{width:30px;height:30px;display:grid;place-items:center;border-radius:50%;border:2px solid var(--line-strong);font-weight:800;font-size:13px;color:var(--muted);margin-bottom:6px}
[data-dash-ws] .db-step.done .n{border:0;background:#2EC4A0;color:#04212A}
[data-dash-ws] .db-step b{font-size:14.5px}
[data-dash-ws] .db-step small{font-size:12.5px;color:var(--muted)}
[data-dash-ws] .db-step:disabled{cursor:default}
[data-dash-ws] .db-step.done b{color:var(--muted)}
[data-dash-ws] .db-bento{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(320px,1fr);gap:18px}
[data-dash-ws] .db-brief-h{display:flex;align-items:baseline;gap:10px;padding:18px 22px 6px;flex-wrap:wrap}
[data-dash-ws] .db-brief-h h2{margin:0;font-family:"Literata",Georgia,serif;font-size:24px;font-weight:600}
[data-dash-ws] .db-brief-h span{font-size:12.5px;color:var(--faint)}
[data-dash-ws] .db-brief{list-style:none;margin:0;padding:6px 12px 14px;display:grid;gap:2px}
[data-dash-ws] .db-brief li{display:flex;align-items:center;gap:12px;padding:10px;border-radius:12px}
[data-dash-ws] .db-brief li:hover{background:var(--surface-2)}
[data-dash-ws] .db-brief .dot{width:10px;height:10px;border-radius:50%;flex:none;background:var(--c)}
[data-dash-ws] .db-brief p{flex:1;margin:0;font-size:15px;line-height:1.5}
[data-dash-ws] .db-brief p b{font-weight:700}
[data-dash-ws] .db-brief p em{font-style:normal;color:var(--muted)}
[data-dash-ws] .db-next{display:grid;gap:10px;align-content:start;padding:20px 22px;background:var(--surface-2)}
[data-dash-ws] .db-tag{display:flex;align-items:center;gap:8px;font-size:12px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--c,#3CCFE0)}
[data-dash-ws] .db-tag i{width:9px;height:9px;border-radius:50%;background:currentColor;box-shadow:0 0 0 4px color-mix(in srgb,currentColor 20%,transparent)}
[data-dash-ws] .db-next h3{margin:0;font-family:"Literata",Georgia,serif;font-size:22px;font-weight:600;line-height:1.25}
[data-dash-ws] .db-meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:14px;color:var(--muted);line-height:1.5}
[data-dash-ws] .db-count-down{display:flex;align-items:baseline;gap:8px}
[data-dash-ws] .db-count-down b{font-family:"Literata",Georgia,serif;font-size:40px;font-weight:600;line-height:1}
[data-dash-ws] .db-count-down span{font-size:14px;color:var(--muted)}
[data-dash-ws] .db-row{display:flex;gap:8px;flex-wrap:wrap}
[data-dash-ws] .db-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr))}
[data-dash-ws] .db-kpi{position:relative;display:grid;gap:3px;padding:16px 20px;border-left:1px solid var(--line);cursor:pointer;text-align:left;transition:background .15s}
[data-dash-ws] .db-kpi:first-child{border-left:0}
[data-dash-ws] .db-kpi:hover{background:var(--surface-2)}
[data-dash-ws] .db-kpi-ic{position:absolute;top:16px;right:18px;color:var(--faint)}
[data-dash-ws] .db-kpi-l{padding-right:24px;font-size:12px;font-weight:800;letter-spacing:.08em;color:var(--muted)}
[data-dash-ws] .db-kpi-v{font-family:"Literata",Georgia,serif;font-size:32px;font-weight:600;line-height:1.15}
[data-dash-ws] .db-kpi-s{font-size:12.5px;color:var(--muted)}
[data-dash-ws] .db-kpi-s.warn{color:#F2C35E}
[data-dash-ws] .db-skel{display:inline-block;width:52px;height:28px;border-radius:8px;vertical-align:middle;background:linear-gradient(90deg,var(--surface-2) 0%,color-mix(in srgb,var(--line-strong) 70%,transparent) 50%,var(--surface-2) 100%);background-size:200% 100%;animation:dbShim 1.2s linear infinite}
@keyframes dbShim{from{background-position:200% 0}to{background-position:-200% 0}}
[data-dash-ws] .db-quick{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
[data-dash-ws] .db-q{display:flex;align-items:center;gap:12px;min-width:0;height:72px;padding:0 14px;border-radius:16px;border:1px solid var(--line);background:var(--surface);color:var(--ink);font-size:15px;font-weight:700;cursor:pointer;transition:border-color .15s,transform .15s,box-shadow .15s}
[data-dash-ws] .db-q .ql{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-dash-ws] .db-q .qi{width:40px;height:40px;flex:none;display:grid;place-items:center;border-radius:12px;background:color-mix(in srgb,var(--brand-text) 13%,transparent)}
[data-dash-ws] .db-q:hover{box-shadow:0 12px 24px -16px rgba(0,0,0,.7)}
[data-dash-ws] .db-q svg{color:var(--brand-text);flex:none}
[data-dash-ws] .db-q:hover{border-color:var(--brand-text);transform:translateY(-1px)}
[data-dash-ws] .db-pair{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:18px;align-items:stretch}
[data-dash-ws] .db-pair.b{grid-template-columns:minmax(0,1.4fr) minmax(0,1fr)}
[data-dash-ws] .db-pair > .db-card:only-child{grid-column:1 / -1}
[data-dash-ws] .db-grp{display:flex;justify-content:space-between;padding:9px 20px;background:var(--surface-2);border-top:1px solid var(--line);font-size:12px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
[data-dash-ws] .db-grp.over{color:#F28B80}
[data-dash-ws] .db-grp.soon{color:#F2C35E}
[data-dash-ws] .db-dl{display:grid;grid-template-columns:96px minmax(0,1fr) auto;gap:14px;align-items:center;padding:12px 20px;border-top:1px solid var(--line);cursor:pointer}
[data-dash-ws] .db-dl:hover{background:var(--hover-tint)}
[data-dash-ws] .db-dl .when{font-size:13px;font-weight:700;color:var(--muted)}
[data-dash-ws] .db-dl .when.over{color:#F28B80}
[data-dash-ws] .db-dl .when.soon{color:#F2C35E}
[data-dash-ws] .db-dl b{display:flex;align-items:center;gap:8px;font-size:14.5px;min-width:0}
[data-dash-ws] .db-dl b span:last-child{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-dash-ws] .db-dl small{display:block;font-size:12.5px;color:var(--muted);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-dash-ws] .db-kindtag{flex:none;font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;padding:2px 7px;border-radius:6px;color:var(--c);background:color-mix(in srgb,var(--c) 14%,transparent)}
[data-dash-ws] .db-more{display:block;width:100%;padding:12px;border:0;border-top:1px solid var(--line);background:none;color:var(--brand-text);font-size:13.5px;font-weight:700;cursor:pointer}
[data-dash-ws] .db-tabs{display:inline-flex;gap:4px;padding:3px;border-radius:10px;background:var(--surface-2);border:1px solid var(--line)}
[data-dash-ws] .db-tabs button{height:30px;padding:0 12px;border:0;border-radius:7px;background:none;color:var(--muted);font-size:13px;font-weight:700;cursor:pointer}
[data-dash-ws] .db-tabs button[aria-pressed="true"]{background:var(--surface);color:var(--ink);box-shadow:inset 0 0 0 1px var(--line)}
[data-dash-ws] .db-tl{padding:10px 20px 16px}
[data-dash-ws] .db-ti{display:grid;grid-template-columns:52px 22px minmax(0,1fr) auto;gap:10px;padding:10px 0;align-items:start}
[data-dash-ws] .db-ti .tm{font-family:"JetBrains Mono",monospace;font-size:12.5px;line-height:1.4}
[data-dash-ws] .db-ti .tm small{display:block;color:var(--faint);font-size:11.5px}
[data-dash-ws] .db-ti .pin{position:relative;display:grid;justify-items:center;height:100%}
[data-dash-ws] .db-ti .pin::after{content:"";position:absolute;top:16px;bottom:-12px;width:2px;background:var(--line)}
[data-dash-ws] .db-ti:last-child .pin::after{display:none}
[data-dash-ws] .db-ti .pin i{position:relative;z-index:1;width:12px;height:12px;border-radius:50%;border:2.5px solid var(--c);background:var(--surface);margin-top:3px}
[data-dash-ws] .db-ti b{display:block;font-size:14.5px}
[data-dash-ws] .db-ti small{display:block;font-size:12.5px;color:var(--muted);margin-top:2px}
[data-dash-ws] .db-ti.past{opacity:.5}
[data-dash-ws] .db-soon{font-size:12px;font-weight:700;color:#F2C35E}
[data-dash-ws] .db-now{display:grid;grid-template-columns:52px 22px 1fr;gap:10px;align-items:center;padding:2px 0}
[data-dash-ws] .db-now span{font-family:"JetBrains Mono",monospace;font-size:12.5px;font-weight:700;color:#F28B80}
[data-dash-ws] .db-now i{width:12px;height:12px;border-radius:50%;background:#F28B80;justify-self:center}
[data-dash-ws] .db-now hr{margin:0;border:0;height:2px;background:#F28B80;opacity:.7}
[data-dash-ws] .db-week{display:grid;gap:2px;padding:8px 12px 14px}
[data-dash-ws] .db-wd{display:grid;grid-template-columns:86px minmax(0,1fr);gap:12px;padding:9px 8px;border-radius:10px;cursor:pointer}
[data-dash-ws] .db-wd:hover{background:var(--surface-2)}
[data-dash-ws] .db-wd .d{font-size:13px;color:var(--muted)}
[data-dash-ws] .db-wd .d b{display:block;font-size:14px;color:var(--ink)}
[data-dash-ws] .db-wd.today .d b{color:var(--brand-text)}
[data-dash-ws] .db-wd ul{list-style:none;margin:0;padding:0;display:grid;gap:4px;font-size:13.5px}
[data-dash-ws] .db-wd li{display:flex;align-items:center;gap:8px;min-width:0}
[data-dash-ws] .db-wd li i{width:8px;height:8px;border-radius:50%;flex:none}
[data-dash-ws] .db-wd li span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-dash-ws] .db-wd li em{font-style:normal;font-family:"JetBrains Mono",monospace;font-size:12px;color:var(--muted);flex:none}
[data-dash-ws] .db-wd .free{font-size:13px;color:var(--faint)}
[data-dash-ws] .db-act{display:flex;gap:12px;padding:12px 20px;border-top:1px solid var(--line);cursor:pointer}
[data-dash-ws] .db-act:first-of-type{border-top:0}
[data-dash-ws] .db-act:hover{background:var(--hover-tint)}
[data-dash-ws] .db-act .av{width:34px;height:34px;flex:none;display:grid;place-items:center;border-radius:50%;background:var(--surface-2);color:var(--brand-text)}
[data-dash-ws] .db-act b{display:block;font-size:14px}
[data-dash-ws] .db-act small{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:13px;color:var(--muted);margin-top:2px;line-height:1.45}
[data-dash-ws] .db-act .when{font-size:12px;color:var(--faint);margin-top:3px}
[data-dash-ws] .db-act.unread b::after{content:"";display:inline-block;width:7px;height:7px;margin-left:6px;border-radius:50%;background:#3CCFE0;vertical-align:2px}
[data-dash-ws] table{width:100%;border-collapse:collapse}
[data-dash-ws] th{padding:10px 20px;text-align:left;font-size:11.5px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);border-bottom:1px solid var(--line)}
[data-dash-ws] td{padding:12px 20px;font-size:14px;border-bottom:1px solid var(--line)}
[data-dash-ws] tbody tr{cursor:pointer}
[data-dash-ws] td.t{font-weight:600;max-width:320px}
[data-dash-ws] td.t small{display:block;font-weight:500;font-size:12.5px;color:var(--muted);margin-top:2px}
[data-dash-ws] th:last-child,[data-dash-ws] td:last-child{white-space:nowrap}
[data-dash-ws] tbody tr:hover td{background:var(--hover-tint)}
[data-dash-ws] tbody tr:last-child td{border-bottom:0}
[data-dash-ws] .db-pal-scrim{position:fixed;inset:0;z-index:400;display:flex;justify-content:center;align-items:flex-start;padding-top:12vh;background:rgba(5,14,18,.55);backdrop-filter:blur(3px)}
[data-dash-ws] .db-pal{width:min(620px,92vw);border-radius:18px;background:var(--surface);border:1px solid var(--line-strong);box-shadow:0 30px 80px -20px rgba(0,0,0,.8);overflow:hidden;animation:dbUp .16s ease-out}
[data-dash-ws] .db-pal-in{display:flex;align-items:center;gap:12px;padding:16px 18px;border-bottom:1px solid var(--line);color:var(--muted)}
[data-dash-ws] .db-pal-in input{flex:1;border:0;background:none;outline:none;color:var(--ink);font-size:16px}
[data-dash-ws] .db-pal-list{max-height:min(420px,60vh);overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin;padding:8px;display:grid;gap:2px}
[data-dash-ws] .db-pal-row{display:flex;align-items:center;gap:12px;height:44px;padding:0 12px;border:0;border-radius:10px;background:none;color:var(--ink);font-size:14.5px;text-align:left;cursor:pointer}
[data-dash-ws] .db-pal-row span{flex:1}
[data-dash-ws] .db-pal-row svg{color:var(--faint)}
[data-dash-ws] .db-pal-row.on{background:var(--surface-2)}
[data-dash-ws] .db-pal-row.on svg{color:var(--brand-text)}`;

function DashboardPage() {
    const { t } = useTheme();
    const { setActiveCase, setOpenCaseId, setPage } = useCase();
    const { notifs = [], openNotif } = useNotif() || {};
    const { user } = useAuth();
    const [rawCases, setRawCases] = useState([]);
    // The server's total case count, or null until the list has answered. When
    // it exceeds the rows loaded (the API caps a page at 50), counts derived
    // from those rows are a floor, and are shown as one ("50+").
    const [casesTotal, setCasesTotal] = useState(null);
    // Exact active total: the server's counts of `open` + `in_progress`; null = not known.
    const [activeTotal, setActiveTotal] = useState(null);
    // Documents awaiting this lawyer's review; null = not known.
    const [pendingDocs, setPendingDocs] = useState(null);
    // `null` = not known (not yet read, or the read failed). Distinct from 0.
    const [aptCount, setAptCount] = useState(null);
    const [aptPending, setAptPending] = useState(null);
    const [weekAppts, setWeekAppts] = useState([]);
    const [diary, setDiary] = useState([]);
    const [tasks, setTasks] = useState([]);           // open tasks across live cases
    const [setup, setSetup] = useState(null);         // practice set-up, once known
    // null = still asking, true = the read failed, false = loaded.
    const [todayFailed, setTodayFailed] = useState(null);
    const [now, setNow] = useState(() => Date.now());
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [updatedAt, setUpdatedAt] = useState(null);
    const [palette, setPalette] = useState(false);
    const [tab, setTab] = useState("today");
    const [allDates, setAllDates] = useState(false);

    const today = pktToday();
    const weekEnd = addDays(today, 7);
    const horizon = addDays(today, 30);

    // The lawyer's layout: hidden sections, remembered in this browser.
    const layoutKey = `attorney:dash-hidden:${user?._id || "me"}`;
    const [hidden, setHidden] = useState([]);
    const [customOpen, setCustomOpen] = useState(false);
    useEffect(() => {
        try { const v = JSON.parse(localStorage.getItem(layoutKey) || "[]"); setHidden(Array.isArray(v) ? v : []); } catch { /* storage off */ }
    }, [layoutKey]);
    const toggleSection = (id) => setHidden(prev => {
        const next = prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id];
        try { localStorage.setItem(layoutKey, JSON.stringify(next)); } catch { /* storage off */ }
        return next;
    });
    const show = (id) => !hidden.includes(id);

    const load = useCallback(() => {
        const jobs = [];
        jobs.push(listCases({ page_size: 50 }).then(async ({ data }) => {
            if (!data?.items) return;
            setRawCases(data.items);
            setCasesTotal(Number.isInteger(data.total) ? data.total : data.items.length);
            // Open tasks, from the cases being worked (at most twelve reads).
            const live = data.items.filter(c => c.status === "in_progress" || c.status === "open").slice(0, 12);
            const lists = await Promise.all(live.map(c => listTasks(c._id).then(r => (Array.isArray(r?.data) ? r.data.map(x => ({ ...x, case: c })) : []))));
            setTasks(lists.flat().filter(x => !x.done));
        }));

        // ACTIVE = open + in_progress, counted by the server. One row of each
        // status is enough: `total` is the count, whatever the list's length.
        jobs.push(Promise.all([
            listCases({ status: "open", page_size: 1 }),
            listCases({ status: "in_progress", page_size: 1 }),
        ]).then(([open, inProgress]) => {
            const n = (r) => (!r.error && Number.isInteger(r.data?.total) ? r.data.total : null);
            const a = n(open), b = n(inProgress);
            setActiveTotal(a === null || b === null ? null : a + b);
        }));

        // The review queue's own `submitted` total (first page carries counts);
        // on the legacy queue, which is unpaginated, counting its rows is exact.
        jobs.push(reviewQueueV2({ status: "submitted", limit: 1 }).then(async (v2) => {
            if (!v2.error) {
                const n = v2.data?.counts?.submitted;
                setPendingDocs(Number.isInteger(n) ? n : null);
                return;
            }
            if (v2.status === 404 && errorCode(v2.error) === "feature_disabled") {
                const legacy = await listReviewQueue();
                if (Array.isArray(legacy.data)) {
                    setPendingDocs(legacy.data.filter(d => d.review_status === "submitted").length);
                }
            }
        }));

        // THE COUNT COMES FROM THE SERVER'S `total`, NOT FROM COUNTING ROWS: a
        // single row of each status reads the real figure without downloading
        // an appointment history to count it.
        jobs.push(Promise.all([
            listAppointments({ status: "pending", page_size: 1 }),
            listAppointments({ status: "confirmed", page_size: 1 }),
        ]).then(([pending, confirmed]) => {
            if (pending.error || confirmed.error) { setAptCount(null); return; }
            const count = (n) => (Number.isInteger(n?.data?.total) ? n.data.total : null);
            const p = count(pending), c = count(confirmed);
            setAptPending(p);
            setAptCount(p === null || c === null ? null : p + c);
        }));

        // The coming week, asked for by Pakistan date — today's agenda is the
        // first day of it. The first page of the full list is the OLDEST fifty,
        // so asking by date is the only way to reach today.
        jobs.push(listAppointments({
            page_size: 50,
            starts_from: `${today}T00:00:00+05:00`,
            starts_before: `${weekEnd}T00:00:00+05:00`,
        }).then(({ data, error }) => {
            // A failed read is not an empty day.
            if (error || !data?.items) { setTodayFailed(true); return; }
            setTodayFailed(false);
            setWeekAppts(data.items.filter(a => a.status === "confirmed" || a.status === "pending"));
        }));

        jobs.push(listLawyerEvents({ start: `${today}T00:00:00+05:00`, end: `${weekEnd}T00:00:00+05:00` })
            .then(({ data }) => { if (Array.isArray(data)) setDiary(data); }));

        // Is the practice set up? Verification files, profile, working hours.
        jobs.push(Promise.all([getMe(), listMyKycDocuments(), getMyWorkingHours()]).then(([me, docs, hours]) => {
            if (!me?.data) return;
            const lp = me.data.lawyer_profile || {};
            const profileFields = [me.data.phone, lp.bar_number, lp.experience_years, lp.hourly_rate, lp.province || me.data.province, lp.address, (lp.bio || "").trim().length >= 40, (lp.specializations || []).length];
            setSetup({
                verified: lp.kyc_status === "approved" || lp.kyc_verified === true,
                docs: docs?.data && typeof docs.data === "object" ? Object.keys(docs.data).length : 0,
                profile: profileFields.filter(Boolean).length, profileOf: profileFields.length,
                hours: hours?.data ? Boolean(hours.data.configured) : null,
            });
        }));
        return Promise.allSettled(jobs);
    }, [today, weekEnd]);

    useEffect(() => {
        load().then(() => { setLoading(false); setUpdatedAt(Date.now()); });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    const refresh = () => {
        if (refreshing) return;
        setRefreshing(true);
        load().then(() => { setRefreshing(false); setUpdatedAt(Date.now()); setNow(Date.now()); });
    };

    // The countdown, the "now" line and "updated … ago" move on their own.
    useEffect(() => {
        const id = setInterval(() => setNow(Date.now()), 30000);
        return () => clearInterval(id);
    }, []);

    // Ctrl/Cmd+K: jump anywhere, or ask the AI, from the keyboard.
    useEffect(() => {
        const onKey = (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette(v => !v); }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, []);

    const cases = useMemo(() => rawCases.map(_mapCase), [rawCases]);
    const byId = useMemo(() => new Map(rawCases.map(c => [c._id, c])), [rawCases]);
    const partial = casesTotal !== null && casesTotal > rawCases.length;
    const fromCases = (n) => (casesTotal === null ? "—" : partial ? `${n}+` : String(n));

    const openCase = (c) => {
        if (!c) { setPage("cases"); return; }
        const id = c.case_number || c.id || c._id;
        setActiveCase(id);
        setOpenCaseId(id);
        setPage("cases");
    };
    const askAI = (q) => { try { sessionStorage.setItem("attorney:ai-prefill", q); } catch { /* storage off */ } setPage("ai-legal"); };

    // Every dated thing in the next 7 days: hearings, appointments, diary.
    const items = useMemo(() => {
        const out = [];
        for (const c of rawCases) {
            for (const h of c.hearing_dates || []) {
                if (h.outcome || !h.date) continue;
                const key = pktDayKey(h.date);
                if (key < today || key >= weekEnd) continue;
                const time = /^\d{1,2}:\d{2}/.test(h.time || "") ? h.time.slice(0, 5) : null;
                const at = time ? new Date(`${key}T${time.padStart(5, "0")}:00+05:00`) : new Date(`${key}T09:00:00+05:00`);
                out.push({ kind: "hearing", key, at, end: new Date(+at + 60 * 60000), timed: Boolean(time),
                    title: c.title || "Hearing", sub: [h.purpose, h.court, h.judge].filter(Boolean).join(" · "), caseNo: c.case_number, case: c, hearing: h });
            }
        }
        for (const a of weekAppts) {
            if (!a.scheduled_at) continue;
            const at = new Date(a.scheduled_at);
            out.push({ kind: "appointment", key: pktDayKey(a.scheduled_at), at, end: new Date(+at + (a.duration_minutes || 30) * 60000), timed: true,
                title: `Consultation · ${a.client_name || "Client"}`,
                sub: [a.mode === "video" ? "Video call" : a.mode === "phone" ? "Phone call" : "In person", a.status === "pending" ? "awaiting your answer" : null].filter(Boolean).join(" · "),
                caseNo: byId.get(a.case_id)?.case_number, case: byId.get(a.case_id) });
        }
        for (const e of diary) {
            if (!e.starts_at) continue;
            out.push({ kind: "event", key: pktDayKey(e.starts_at), at: new Date(e.starts_at), end: new Date(e.ends_at || e.starts_at), timed: true,
                title: e.title, sub: [e.kind === "meeting" ? "Meeting" : "Event", e.location].filter(Boolean).join(" · "),
                caseNo: byId.get(e.case_id)?.case_number, case: byId.get(e.case_id) });
        }
        return out.sort((a, b) => a.at - b.at);
    }, [rawCases, weekAppts, diary, byId, today, weekEnd]);

    const todays = items.filter(i => i.key === today);
    const next = todays.find(i => +i.end > now) || items.find(i => +i.end > now) || null;
    const minsAway = next ? Math.round((+next.at - now) / 60000) : null;
    const hearingsWeek = items.filter(i => i.kind === "hearing");
    const apptsToday = todays.filter(i => i.kind === "appointment");
    const noDateCases = rawCases.filter(c => c.status === "in_progress" && !_mapCase(c).nextHearing);

    // Critical dates: open tasks with a due date and upcoming hearings, within
    // 30 days, plus overdue tasks. Sorted by date; grouped by urgency.
    const dates = useMemo(() => {
        const out = [];
        for (const tk of tasks) {
            if (!tk.due) continue;
            const key = pktDayKey(tk.due);
            if (key > horizon) continue;
            out.push({ key, kind: "task", title: tk.title || "Task", sub: [tk.case?.title, tk.case?.case_number].filter(Boolean).join(" · "), case: tk.case, high: tk.priority === "high" });
        }
        for (const c of rawCases) {
            for (const h of c.hearing_dates || []) {
                if (h.outcome || !h.date) continue;
                const key = pktDayKey(h.date);
                if (key < today || key > horizon) continue;
                out.push({ key, kind: "hearing", title: c.title || "Hearing", sub: [h.purpose, h.court, c.case_number].filter(Boolean).join(" · "), case: c });
            }
        }
        return out.sort((a, b) => a.key.localeCompare(b.key));
    }, [tasks, rawCases, today, horizon]);
    const overdue = dates.filter(d => d.key < today);
    const soon = dates.filter(d => d.key >= today && d.key < weekEnd);
    const later = dates.filter(d => d.key >= weekEnd);

    // The brief: what matters today, said plainly, each with its next step.
    const unread = notifs.filter(n => n.unread && n.type === "case_message");
    const nextHearing = hearingsWeek.find(h => +h.end > now);
    const brief = [];
    if (overdue.length) brief.push({ c: "#F28B80", text: <><b>{overdue.length} task{overdue.length === 1 ? " is" : "s are"} overdue</b><em> — oldest: {overdue[0].title}, {whenWord(overdue[0].key, today).toLowerCase()}</em></>, act: "Open", go: () => openCase(overdue[0].case) });
    if (todays.length) {
        const first = todays.find(i => +i.end > now);
        brief.push({ c: "#3CCFE0", text: <><b>{todays.length} thing{todays.length === 1 ? "" : "s"} on today</b>{first ? <em> — next: {first.title}{first.timed ? ` at ${hm(first.at.toISOString())}` : ""}</em> : <em> — all done</em>}</>, act: "Schedule", go: () => setTab("today") });
    }
    if (nextHearing) brief.push({ c: "#B9A6F5", text: <><b>Next hearing {whenWord(nextHearing.key, today).toLowerCase()}</b><em> — {nextHearing.title}{nextHearing.hearing?.court ? `, ${nextHearing.hearing.court}` : ""}</em></>, act: "Open case", go: () => openCase(nextHearing.case) });
    if (pendingDocs) brief.push({ c: "#F2C35E", text: <><b>{pendingDocs} document{pendingDocs === 1 ? "" : "s"} waiting for your review</b><em> — clients are waiting on your decision</em></>, act: "Review", go: () => setPage("documents") });
    if (aptPending) brief.push({ c: "#F2C35E", text: <><b>{aptPending} appointment request{aptPending === 1 ? "" : "s"}</b><em> — accept, or suggest another time</em></>, act: "Answer", go: () => setPage("appointments") });
    if (unread.length) brief.push({ c: "#8DB8FF", text: <><b>{unread.length} unread client message{unread.length === 1 ? "" : "s"}</b><em> — {unread[0].title}</em></>, act: "Read", go: () => (openNotif ? openNotif(unread[0]) : setPage("cases")) });
    if (noDateCases.length) brief.push({ c: "#93A4A8", text: <><b>{noDateCases.length} active case{noDateCases.length === 1 ? " has" : "s have"} no next hearing</b><em> — {noDateCases[0].title}{noDateCases.length > 1 ? " and others" : ""}</em></>, act: "Set date", go: () => openCase(noDateCases[0]) });

    // Setup: shown until done, or until the lawyer hides it.
    const steps = setup ? [
        { done: true, title: "Create your account", sub: "Done", go: null },
        { done: setup.verified || setup.docs >= 4, title: "Upload verification documents", sub: setup.verified ? "Verified" : `${setup.docs} of 4 uploaded — clients see the verified mark`, go: () => { try { window.history.replaceState(window.history.state, "", "#verification"); } catch { /* no history */ } setPage("settings"); } },
        { done: setup.profile === setup.profileOf, title: "Complete your public profile", sub: `${setup.profile} of ${setup.profileOf} details — clients choose on these`, go: () => setPage("profile") },
        { done: setup.hours === true, title: "Set working hours", sub: setup.hours ? "Clients can request your free slots" : "So clients can request appointments", go: () => setPage("appointments") },
    ] : [];
    const setupLeft = steps.filter(s => !s.done).length;

    const greetName = user?.full_name?.split(" ")[0] || "Counselor";
    const hour = Number(formatPkt(new Date(now).toISOString(), { hour: "numeric", hour12: false }));
    const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
    const activeCnt = activeTotal === null ? "—" : String(activeTotal);

    const kpis = [
        { l: "Active Cases", v: activeCnt, s: noDateCases.length ? `${noDateCases.length} need a hearing date` : "Open + in progress", tone: noDateCases.length ? "warn" : "", icon: "shield", pg: "cases" },
        { l: "Hearings This Week", v: fromCases(hearingsWeek.length), s: nextHearing ? `Next: ${dayName(nextHearing.key, { weekday: "short" })}${nextHearing.timed ? ` ${hm(nextHearing.at.toISOString())}` : ""}` : "None in the next 7 days", icon: "gavel", pg: "causelist" },
        { l: "Docs to Review", v: pendingDocs === null ? "—" : String(pendingDocs), s: pendingDocs ? "Awaiting your decision" : "All caught up", tone: pendingDocs ? "warn" : "", icon: "doc", pg: "documents" },
        { l: "Appointments Today", v: todayFailed ? "—" : String(apptsToday.length), s: aptCount === null ? "Pending + confirmed" : `${aptCount} upcoming in total`, icon: "clock", pg: "appointments" },
    ];

    const recentCases = cases.slice(0, 5);
    const activity = notifs.slice(0, 3);
    const dateRow = (d, n) => (
        <div key={`${d.kind}${n}${d.key}${d.title}`} className="db-dl" onClick={() => openCase(d.case)}>
            <span className={`when ${d.key < today ? "over" : d.key < weekEnd ? "soon" : ""}`}>{whenWord(d.key, today)}</span>
            <span style={{ minWidth: 0 }}>
                <b><span className="db-kindtag" style={{ "--c": d.kind === "hearing" ? "#B9A6F5" : d.high ? "#F28B80" : "#3CCFE0" }}>{d.kind === "hearing" ? "Hearing" : d.high ? "Task · high" : "Task"}</span><span>{d.title}</span></b>
                {d.sub && <small>{d.sub}</small>}
            </span>
            <span className="db-link" aria-hidden="true"><Svg d={P.arrow} size={16} /></span>
        </div>
    );
    const nowLine = <div key="now" className="db-now"><span>{formatPkt(new Date(now).toISOString(), { hour: "2-digit", minute: "2-digit", hour12: false })}</span><i /><hr /></div>;
    const showLater = allDates || (!overdue.length && !soon.length);

    return (
        <div data-dash-ws data-drafting-theme data-mode={draftingMode(t)}>
            <style>{`${DRAFTING_TOKENS_CSS}\n${CSS}`}</style>
            <div className="db-wrap">
                {/* Header: when, how fresh; search, layout, the one primary action */}
                <div className="db-top">
                    <div>
                        <div className="db-date">
                            <span><b>{dayName(today, { weekday: "long", day: "numeric", month: "long" })}</b> · {formatPkt(new Date(now).toISOString(), { hour: "numeric", minute: "2-digit" })} PKT</span>
                            {updatedAt && (
                                <button type="button" className={`db-fresh${refreshing ? " spin" : ""}`} onClick={refresh} title="Refresh the dashboard">
                                    <Svg d={P.refresh} size={14} />{refreshing ? "Refreshing…" : `Updated ${ago(updatedAt, now)}`}
                                </button>
                            )}
                        </div>
                        <h1 className="db-h1">{greeting}, {greetName}</h1>
                    </div>
                    <div className="db-tools">
                        <button type="button" className="db-cmdk" onClick={() => setPalette(true)} aria-label="Search or jump to (Ctrl K)">
                            <Svg d={P.search} size={17} /><span>Search or jump to…</span><kbd>Ctrl K</kbd>
                        </button>
                        <button type="button" className="db-icon" aria-expanded={customOpen} aria-label="Customize dashboard" title="Customize dashboard" onClick={() => setCustomOpen(v => !v)}>
                            <Svg d={P.sliders} />
                        </button>
                        <button type="button" className="db-btn pri" onClick={() => setPage("ai-legal")}><Svg d={P.sparkle} />Ask AI</button>
                        {customOpen && (
                            <div className="db-custom" role="dialog" aria-label="Customize dashboard" onMouseLeave={() => setCustomOpen(false)}>
                                <b>Show on my dashboard</b>
                                {SECTIONS.map(([id, label]) => (
                                    <button key={id} type="button" className="db-tog" aria-pressed={show(id)} onClick={() => toggleSection(id)}>
                                        {label}<i aria-hidden="true" />
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                </div>

                {/* Setup, while the practice is not ready */}
                {show("setup") && setup && setupLeft > 0 && (
                    <section className="db-card" aria-label="Get your practice set up">
                        <div className="db-ch">
                            <h2>Get your practice set up<small>{steps.length - setupLeft} of {steps.length} done</small></h2>
                            <button type="button" className="db-link" onClick={() => toggleSection("setup")}>Hide</button>
                        </div>
                        <div className="db-setup">
                            {steps.map((s, n) => (
                                <button key={s.title} type="button" className={`db-step${s.done ? " done" : ""}`} disabled={s.done} onClick={s.go || undefined}>
                                    <span className="n">{s.done ? <Svg d={P.check} size={15} /> : n + 1}</span>
                                    <b>{s.title}</b>
                                    <small>{s.sub}</small>
                                </button>
                            ))}
                        </div>
                    </section>
                )}

                {/* The lead: the brief, and what is next */}
                {show("brief") && (
                    <div className="db-bento">
                        <section className="db-card" aria-label="Daily brief">
                            <div className="db-brief-h"><h2>Daily brief</h2><span>From your calendar, cases and inbox</span></div>
                            {loading && !brief.length ? (
                                <div className="db-empty"><span className="db-skel" style={{ width: "70%" }} /></div>
                            ) : brief.length ? (
                                <ul className="db-brief">
                                    {brief.map((b, n) => (
                                        <li key={n} style={{ "--c": b.c }}>
                                            <span className="dot" />
                                            <p>{b.text}</p>
                                            <button type="button" className="db-btn sm" onClick={b.go}>{b.act}</button>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <div className="db-empty">Your day is clear: nothing overdue, nothing waiting on you. A good time for research or drafting.</div>
                            )}
                        </section>
                        <section className="db-card db-next" aria-label="Next up" style={next ? { "--c": KIND[next.kind].c } : undefined}>
                            <div className="db-tag"><i />{next ? (next.key === today ? "Next up" : `Next · ${dayName(next.key, { weekday: "long" })}`) : "Next up"}</div>
                            {next ? (
                                <>
                                    <h3>{next.title}</h3>
                                    <div className="db-meta">
                                        <span>{next.timed ? `${hm(next.at.toISOString())}–${hm(next.end.toISOString())}` : "Time not set"}{next.sub ? ` · ${next.sub}` : ""}</span>
                                        {next.caseNo && <span className="db-case">{next.caseNo}</span>}
                                    </div>
                                    {next.key === today && minsAway !== null && (
                                        <div className="db-count-down">
                                            {minsAway > 0
                                                ? <><b>{minsAway >= 60 ? `${Math.floor(minsAway / 60)}h ${minsAway % 60}m` : minsAway}</b><span>{minsAway >= 60 ? "from now" : `minute${minsAway === 1 ? "" : "s"} from now`}</span></>
                                                : <><b>Now</b><span>in progress</span></>}
                                        </div>
                                    )}
                                    <div className="db-row">
                                        {next.case && <button type="button" className="db-btn sm" onClick={() => openCase(next.case)}>Open case file</button>}
                                        <button type="button" className="db-btn sm" onClick={() => askAI(`Prepare me for: ${next.title}`)}>Prepare with AI</button>
                                    </div>
                                </>
                            ) : (
                                <>
                                    <h3>Nothing scheduled</h3>
                                    <div className="db-meta">The next 7 days are open. Clients can book you once your working hours are set.</div>
                                    <div className="db-row"><button type="button" className="db-btn sm" onClick={() => setPage("appointments")}>Open calendar</button></div>
                                </>
                            )}
                        </section>
                    </div>
                )}

                {/* Numbers: one neutral strip; colour only for what needs action */}
                {show("numbers") && (
                    <section className="db-card db-kpis" aria-label="Key numbers">
                        {kpis.map(k => (
                            <div key={k.l} role="button" tabIndex={0} className="db-kpi" onClick={() => setPage(k.pg)} onKeyDown={e => e.key === "Enter" && setPage(k.pg)}>
                                <span className="db-kpi-ic"><Svg d={P[k.icon]} size={16} /></span>
                                <div className="db-kpi-l" style={{ textTransform: "uppercase" }}>{k.l}</div>
                                <div className="db-kpi-v">{loading && k.v === "—" ? <span className="db-skel" aria-label="Loading" /> : <CountUp value={k.v} />}</div>
                                <div className={`db-kpi-s ${k.tone || ""}`}>{k.s}</div>
                            </div>
                        ))}
                    </section>
                )}

                {/* Shortcuts: one quiet row */}
                {show("quick") && (
                    <nav className="db-quick" aria-label="Shortcuts">
                        {QUICK.map(q => (
                            <button key={q.pg} type="button" className="db-q" onClick={() => setPage(q.pg)}><span className="qi"><Svg d={P[q.icon]} size={20} /></span><span className="ql">{q.title}</span></button>
                        ))}
                    </nav>
                )}

                <div className="db-pair">
                {/* Critical dates, by urgency */}
                {show("dates") && (
                    <section className="db-card" aria-label="Critical dates">
                        <div className="db-ch">
                            <h2>Critical dates<small>tasks and hearings · next 30 days</small></h2>
                            <button type="button" className="db-link" onClick={() => setPage("cases")}>All cases →</button>
                        </div>
                        {!loading && !dates.length && <div className="db-empty">No deadlines or hearings in the next 30 days. Tasks you add to a case with a due date appear here.</div>}
                        {overdue.length > 0 && <div className="db-grp over"><span>Overdue</span><span>{overdue.length}</span></div>}
                        {overdue.slice(0, allDates ? 99 : 3).map(dateRow)}
                        {soon.length > 0 && <div className="db-grp soon"><span>Next 7 days</span><span>{soon.length}</span></div>}
                        {soon.slice(0, allDates ? 99 : 4).map(dateRow)}
                        {showLater && later.length > 0 && <div className="db-grp"><span>Later this month</span><span>{later.length}</span></div>}
                        {showLater && later.slice(0, allDates ? 99 : 4).map(dateRow)}
                        {dates.length > 7 && (
                            <button type="button" className="db-more" onClick={() => setAllDates(v => !v)}>{allDates ? "Show less" : `Show all ${dates.length}`}</button>
                        )}
                    </section>
                )}

                {/* Schedule: today's timeline, or the week as a list */}
                {show("schedule") && (
                    <section className="db-card" aria-label="Schedule">
                        <div className="db-ch">
                            <h2>Schedule</h2>
                            <div className="db-tabs" role="group" aria-label="Schedule range">
                                <button type="button" aria-pressed={tab === "today"} onClick={() => setTab("today")}>Today</button>
                                <button type="button" aria-pressed={tab === "week"} onClick={() => setTab("week")}>7 days</button>
                            </div>
                        </div>
                        {tab === "today" ? (
                            <>
                                {todayFailed === true && <div role="alert" className="db-empty" style={{ color: "#F7A79E" }}>Could not load today&apos;s appointments.</div>}
                                {todayFailed === false && !todays.length && <div className="db-empty">No appointments today.</div>}
                                {todays.length > 0 && (
                                    <div className="db-tl">
                                        {(() => {
                                            const rows = [];
                                            let drawn = false;
                                            todays.forEach((i, n) => {
                                                if (!drawn && +i.at > now) { drawn = true; rows.push(nowLine); }
                                                const past = +i.end <= now;
                                                const mins = Math.round((+i.at - now) / 60000);
                                                rows.push(
                                                    <div key={n} className={`db-ti${past ? " past" : ""}`} style={{ "--c": KIND[i.kind].c }}>
                                                        <span className="tm">{i.timed ? hm(i.at.toISOString()) : "—"}{i.timed && <small>{hm(i.end.toISOString())}</small>}</span>
                                                        <span className="pin"><i /></span>
                                                        <span>
                                                            <b>{i.title}</b>
                                                            {i.sub && <small>{i.sub}</small>}
                                                            {!past && mins > 0 && mins <= 60 && <span className="db-soon">Starts in {mins} min</span>}
                                                        </span>
                                                        {!past && <button type="button" className="db-btn sm" onClick={() => (i.case ? openCase(i.case) : setPage("appointments"))}>Open</button>}
                                                    </div>,
                                                );
                                            });
                                            if (!drawn) rows.push(nowLine);
                                            return rows;
                                        })()}
                                    </div>
                                )}
                            </>
                        ) : (
                            <div className="db-week">
                                {Array.from({ length: 7 }, (_, n) => addDays(today, n)).map(k => {
                                    const day = items.filter(i => i.key === k);
                                    return (
                                        <div key={k} className={`db-wd${k === today ? " today" : ""}`} onClick={() => setPage("appointments")}>
                                            <span className="d"><b>{k === today ? "Today" : dayName(k, { weekday: "short" })}</b>{dayName(k, { day: "numeric", month: "short" })}</span>
                                            {day.length ? (
                                                <ul>{day.slice(0, 3).map((i, n) => <li key={n}><i style={{ background: KIND[i.kind].c }} /><em>{i.timed ? hm(i.at.toISOString()) : "—"}</em><span>{i.title}</span></li>)}{day.length > 3 && <li className="free">+{day.length - 3} more</li>}</ul>
                                            ) : <span className="free">Free</span>}
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </section>
                )}
                </div>

                <div className="db-pair b">
                    {/* Recent cases */}
                    {show("cases") && (
                        <section className="db-card" aria-label="Recent cases">
                            <div className="db-ch">
                                <h2>Recent cases</h2>
                                <button type="button" className="db-link" onClick={() => setPage("cases")}>All cases →</button>
                            </div>
                            <table>
                                <thead><tr>{["Case", "Title", "Status", "Next hearing"].map(h => <th key={h}>{h}</th>)}</tr></thead>
                                <tbody>
                                        {recentCases.map(c => (
                                            <tr key={c._id || c.id} onClick={() => openCase(byId.get(c._id) || c)}>
                                                <td><span className="db-case">{c.id}</span></td>
                                                <td className="t" title={`${c.title} · ${c.type}`}>{c.title}<small>{c.type}{c.client && c.client !== "—" ? ` · ${c.client}` : ""}</small></td>
                                                        <td><Badge type={CSB[c.status]}>{c.status}</Badge></td>
                                                <td style={{ color: "var(--muted)" }}>{c.nextHearing ? fmtDate(c.nextHearing) : "—"}</td>
                                            </tr>
                                        ))}
                                        {!recentCases.length && <tr><td colSpan={4} style={{ textAlign: "center", color: "var(--muted)" }}>No cases assigned yet</td></tr>}
                                </tbody>
                            </table>
                        </section>
                    )}

                    {/* Recent activity */}
                    {show("activity") && (
                        <section className="db-card" aria-label="Recent activity">
                            <div className="db-ch"><h2>Recent activity</h2></div>
                            {activity.length === 0 && <div className="db-empty">No recent activity.</div>}
                            {activity.map(n => (
                                <div key={n.id} className={`db-act${n.unread ? " unread" : ""}`} onClick={() => openNotif?.(n)}>
                                    <span className="av"><Svg d={n.type === "case_message" ? P.chat : n.type?.startsWith("appointment") ? P.cal : n.type?.includes("document") || n.type?.includes("review") ? P.doc : P.alert} size={16} /></span>
                                    <span style={{ minWidth: 0 }}>
                                        <b>{n.title}</b>
                                        {n.body && <small>{n.body}</small>}
                                        <div className="when">{n.time}</div>
                                    </span>
                                </div>
                            ))}
                        </section>
                    )}
                </div>

                {hidden.length > 0 && (
                    <div style={{ textAlign: "center", fontSize: 13, color: "var(--faint)" }}>
                        {hidden.length} section{hidden.length === 1 ? " is" : "s are"} hidden. <button type="button" className="db-link" onClick={() => setCustomOpen(true)}>Customize</button>
                    </div>
                )}
            </div>

            {palette && <Palette mode={draftingMode(t)} onClose={() => setPalette(false)}
                onGo={(pg) => { setPalette(false); setPage(pg); }}
                onAsk={(q) => { setPalette(false); askAI(q); }} />}
        </div>
    );
}
export { DashboardPage };
