'use client';
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { formatPkt } from "@/lib/bookingTime.js";
import { useCase } from "@/components/shared/CaseContext.jsx";
import { useAuth } from "@/context/AuthContext.jsx";
import { activeCases, isDraftCase, isEndedCase } from "@/lib/caseStatus.js";
import { listEngagements, myDocumentsV2 } from "@/lib/api.js";
import { DOCS_FONT } from "./documents/ui.jsx";

/* The client Overview (2026-10-11, the approved "Overview v2" design).
 *
 * Every number and line here comes from the server: cases, appointments,
 * notifications, the client's documents and their engagements. Nothing is
 * estimated. The old "AI Insight" card claimed "Employment Dispute has a 78%
 * win probability" for every client -- a hardcoded sentence about a case most
 * clients did not have, presented as analysis. It is gone, not restyled.
 *
 * Scoped by [data-overview]; colours are the client tokens (clientTheme.js). */
const OVERVIEW_CSS = `[data-overview]{display:flex;flex-direction:column;gap:18px}
[data-overview] .ov-card{position:relative;border-radius:20px;border:1px solid color-mix(in srgb,var(--brand-text) 14%,var(--line));background:radial-gradient(120% 110% at 100% 0%,color-mix(in srgb,var(--c,var(--brand-text)) 9%,transparent) 0%,transparent 55%),linear-gradient(180deg,color-mix(in srgb,var(--surface) 88%,#fff 12%),var(--surface));box-shadow:inset 0 1px 0 rgba(255,255,255,.1),inset 0 -3px 0 rgba(0,0,0,.2),0 14px 28px -16px rgba(0,0,0,.7)}
[data-overview] .ov-well{border-radius:14px;background:radial-gradient(120% 120% at 100% 0%,color-mix(in srgb,var(--c,var(--brand-text)) 9%,transparent) 0%,transparent 60%),linear-gradient(180deg,color-mix(in srgb,var(--surface-2) 88%,#fff 4%),var(--surface-2));border:1px solid color-mix(in srgb,var(--c,var(--brand-text)) 16%,var(--line));box-shadow:inset 0 1px 0 rgba(255,255,255,.06)}
[data-overview] .ov-lbl{font-size:10.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}
[data-overview] .ov-h{margin:0;font-size:16px;font-weight:700;color:var(--ink)}
[data-overview] .ov-link{border:0;background:none;padding:4px 6px;border-radius:8px;color:var(--brand-text);font:inherit;font-size:12.5px;font-weight:600;cursor:pointer}
[data-overview] .ov-link{background-image:linear-gradient(currentColor,currentColor);background-size:0% 1.5px;background-position:6px 100%;background-repeat:no-repeat;transition:background-size .25s ease}
[data-overview] .ov-link:hover{background-size:calc(100% - 12px) 1.5px}
[data-overview] .ov-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;height:40px;padding:0 18px;border-radius:999px;border:1px solid color-mix(in srgb,var(--brand-text) 22%,var(--line));background:color-mix(in srgb,var(--brand-text) 7%,var(--surface));color:var(--ink);font:inherit;font-size:13.5px;font-weight:700;cursor:pointer;transition:background .15s,transform .15s}
[data-overview] .ov-btn{transition:background .2s,color .2s,border-color .2s,transform .12s}
[data-overview] .ov-btn[style*="--a"]{background:color-mix(in srgb,var(--a) 13%,var(--surface));border-color:color-mix(in srgb,var(--a) 38%,transparent);color:var(--a)}
[data-overview] .ov-btn:hover{background:var(--a,var(--brand-text));border-color:transparent;color:#04262c}
[data-overview] .ov-btn:hover span{color:inherit!important}
[data-overview] .ov-btn:active{transform:scale(.95);background:var(--a,var(--brand-text));border-color:transparent;color:#04262c;filter:brightness(.9)}
[data-overview] .ov-btn svg{transition:transform .3s cubic-bezier(.3,1.4,.5,1)}
[data-overview] .ov-btn:hover svg{transform:rotate(90deg)}
[data-overview] .ov-btn.chat:hover svg{transform:rotate(-12deg) scale(1.12)}
[data-overview] .ov-btn:active{transform:scale(.97)}
[data-overview] .ov-btn.go{border:0;background:linear-gradient(135deg,#12897f,#1c9c66);color:#fff;box-shadow:0 8px 20px -10px rgba(28,156,102,.8)}
[data-overview] .ov-btn.go:hover{filter:brightness(1.07)}
[data-overview] .ov-btn.sm{height:34px;padding:0 12px;font-size:12.5px}
[data-overview] .ov-top{display:flex;align-items:center;gap:12px}
[data-overview] .ov-search{flex:1;max-width:560px;display:flex;align-items:center;gap:10px;height:44px;padding:0 14px;border-radius:14px;background:var(--surface);border:1px solid var(--line);box-shadow:inset 0 1px 0 rgba(255,255,255,.06);transition:border-color .15s,box-shadow .15s}
[data-overview] .ov-search:focus-within{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-overview] .ov-search input{flex:1;min-width:0;border:0;outline:none;background:transparent;color:var(--ink);font:inherit;font-size:14px}
[data-overview] .ov-search input::placeholder{color:var(--faint)}
[data-overview] .ov-kbd{font:500 11px "JetBrains Mono",monospace;color:var(--faint);border:1px solid var(--line-strong);border-bottom-width:2px;border-radius:5px;padding:0 6px}
[data-overview] .ov-bell{position:relative;width:44px;height:44px;border-radius:14px;border:1px solid var(--line);background:var(--surface);color:var(--muted);display:grid;place-items:center;cursor:pointer;transition:background .15s,color .15s}
[data-overview] .ov-bell:hover{color:var(--gold)}
[data-overview] .ov-bell:hover svg{animation:ovRing .6s ease}
@keyframes ovRing{0%,100%{transform:rotate(0)}20%{transform:rotate(16deg)}40%{transform:rotate(-14deg)}60%{transform:rotate(9deg)}80%{transform:rotate(-5deg)}}
[data-overview] .ov-bell i{position:absolute;top:9px;right:10px;width:8px;height:8px;border-radius:50%;background:#f28b80}
[data-overview] .ov-hero{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:24px;padding:24px 26px;background:radial-gradient(80% 140% at 100% 0%,color-mix(in srgb,var(--brand-text) 16%,transparent) 0%,transparent 60%),linear-gradient(180deg,color-mix(in srgb,var(--surface) 85%,#fff 15%),var(--surface))}
[data-overview] .ov-hello{margin:4px 0 0;font-size:34px;font-weight:600;line-height:1.15;color:var(--ink);letter-spacing:-.2px}
[data-overview] .ov-need{--nb:#1c9c66;display:flex;align-items:center;gap:14px;padding:14px 16px;color:var(--ink);border-color:color-mix(in srgb,var(--nb) 40%,transparent);background:linear-gradient(90deg,color-mix(in srgb,var(--nb) 16%,var(--surface-2)),var(--surface-2) 65%)}
[data-overview] .ov-need.calm{border-color:color-mix(in srgb,var(--brand-text) 30%,transparent);background:linear-gradient(90deg,color-mix(in srgb,var(--brand-text) 12%,var(--surface-2)),var(--surface-2) 65%)}
[data-overview] .ov-ic{width:40px;height:40px;flex:none;border-radius:12px;display:grid;place-items:center;color:var(--c);background:color-mix(in srgb,var(--c) 17%,transparent)}
[data-overview] .ov-need .ov-btn{height:38px;padding:0 18px;border:0;background:linear-gradient(135deg,#12897f,#1c9c66);color:#fff;box-shadow:0 8px 20px -10px rgba(28,156,102,.85)}
[data-overview] .ov-need .ov-btn:hover{filter:brightness(1.08);background:linear-gradient(135deg,#12897f,#1c9c66)}
[data-overview] .ov-need .ov-btn .arr{display:inline-block;transition:transform .2s}
[data-overview] .ov-need .ov-btn:hover .arr{transform:translateX(3px)}
[data-overview] .ov-need .ov-badge{width:40px;height:40px;flex:none;border-radius:50%;display:grid;place-items:center;background:#fff;color:#12897f;box-shadow:0 6px 14px -8px rgba(0,0,0,.6)}
[data-overview] .ov-date{width:62px;flex:none;border-radius:14px;overflow:hidden;text-align:center;background:var(--surface-2);border:1px solid color-mix(in srgb,var(--brand-text) 25%,transparent)}
[data-overview] .ov-date b{display:block;padding:4px 0;font-size:10.5px;font-weight:800;letter-spacing:.1em;background:linear-gradient(135deg,#12897f,#1c9c66);color:#fff}
[data-overview] .ov-date span{display:block;padding:4px 0 6px;font-size:26px;font-weight:600;color:var(--ink)}
[data-overview] .ov-bar{flex:1;height:6px;border-radius:6px;background:var(--line);overflow:hidden}
[data-overview] .ov-bar i{display:block;height:100%;background:linear-gradient(90deg,#12897f,#3ee0a1)}
[data-overview] .ov-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:8px 0}
[data-overview] .ov-stat{display:flex;align-items:center;gap:14px;padding:16px 18px;text-align:left;font:inherit;color:var(--ink);cursor:pointer;transition:transform .2s cubic-bezier(.22,1,.36,1),box-shadow .2s,border-color .2s}
[data-overview] .ov-stat:hover{transform:translateY(-3px);border-color:color-mix(in srgb,var(--c) 45%,var(--line));box-shadow:inset 0 1px 0 rgba(255,255,255,.12),0 18px 30px -16px color-mix(in srgb,var(--c) 65%,#000)}
[data-overview] .ov-stat .n{font-size:28px;font-weight:600;color:var(--ink)}
[data-overview] .ov-stat .t{display:block;font-weight:700;font-size:13.5px}
[data-overview] .ov-stat .d{display:block;font-size:11.5px;color:var(--faint)}
[data-overview] .ov-main{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(0,1fr);gap:16px;align-items:start}
[data-overview] .ov-col{display:flex;flex-direction:column;gap:16px;min-width:0}
[data-overview] .ov-sec{padding:18px 20px}
[data-overview] .ov-sec-head{display:flex;align-items:center;gap:10px;margin-bottom:12px}
[data-overview] .ov-seg{display:flex;gap:4px;padding:3px;border-radius:999px;background:var(--surface-2);border:1px solid var(--line)}
[data-overview] .ov-seg button{height:26px;padding:0 12px;border:0;border-radius:999px;background:transparent;color:var(--muted);font:inherit;font-size:12px;font-weight:600;cursor:pointer}
[data-overview] .ov-seg button[aria-pressed="true"]{background:color-mix(in srgb,var(--brand-text) 16%,transparent);color:var(--brand-text);font-weight:700}
[data-overview] .ov-case{display:grid;grid-template-columns:44px minmax(0,1fr) auto;gap:14px;align-items:center;width:100%;margin-bottom:10px;padding:14px;text-align:left;font:inherit;color:var(--ink);cursor:pointer;transition:border-color .15s,background .15s}
[data-overview] .ov-case:hover{border-color:color-mix(in srgb,var(--c) 50%,transparent);background:radial-gradient(120% 120% at 100% 0%,color-mix(in srgb,var(--c) 16%,transparent) 0%,transparent 60%),linear-gradient(180deg,color-mix(in srgb,var(--surface-2) 84%,#fff 6%),var(--surface-2))}
[data-overview] .ov-av{width:44px;height:44px;border-radius:50%;display:grid;place-items:center;font-weight:800;font-size:13.5px;color:var(--c);background:color-mix(in srgb,var(--c) 16%,transparent)}
[data-overview] .ov-pill{display:inline-flex;align-items:center;height:22px;padding:0 9px;border-radius:999px;font-size:11px;font-weight:700;color:var(--c);background:color-mix(in srgb,var(--c) 15%,transparent);white-space:nowrap}
[data-overview] .ov-stages{display:flex;gap:4px}
[data-overview] .ov-stages i{flex:1;height:4px;border-radius:4px;background:var(--line)}
[data-overview] .ov-stages i[data-on]{background:var(--brand-text)}
[data-overview] .ov-stages i[data-now]{background:linear-gradient(90deg,var(--brand-text) 50%,var(--line) 50%)}
[data-overview] .ov-docs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
[data-overview] .ov-doc{display:flex;flex-direction:column;gap:8px;padding:12px;text-align:left;font:inherit;color:var(--ink);cursor:pointer;min-width:0}
[data-overview] .ov-doc:hover{border-color:color-mix(in srgb,var(--brand-text) 40%,transparent)}
[data-overview] .ov-type{min-width:34px;height:22px;padding:0 6px;box-sizing:border-box;border-radius:6px;display:inline-grid;place-items:center;font-size:10px;font-weight:800;color:var(--c);background:color-mix(in srgb,var(--c) 15%,transparent)}
[data-overview] .ov-feed{display:flex;gap:12px;padding-bottom:12px}
[data-overview] .ov-feed .dot{width:10px;height:10px;border-radius:50%;background:var(--c);box-shadow:0 0 0 4px color-mix(in srgb,var(--c) 15%,transparent)}
[data-overview] .ov-feed .line{flex:1;width:2px;margin-top:4px;background:var(--line)}
[data-overview] .ov-empty{padding:12px 0;font-size:13px;color:var(--faint)}
[data-overview] .ov-clip{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media (prefers-reduced-motion:reduce){[data-overview] *{animation:none!important;transition:none!important}}
@media (max-width:1100px){[data-overview] .ov-hero,[data-overview] .ov-main{grid-template-columns:minmax(0,1fr)}[data-overview] .ov-stats{grid-template-columns:repeat(2,minmax(0,1fr))}}`;

// The case journey, as the server's statuses read on it.
const STAGES = ["Intake", "Open", "Lawyer", "In progress", "Closed"];
const STAGE_OF = { draft: 0, open: 1, pending_lawyer: 2, in_progress: 3, closed: 5, dismissed: 5 };
const STATUS_LOOK = {
    draft: ["Draft", "var(--gold)"],
    open: ["Open", "#6addeb"],
    pending_lawyer: ["Waiting for a lawyer", "#6addeb"],
    in_progress: ["In progress", "var(--brand-text)"],
    closed: ["Closed", "var(--faint)"],
    dismissed: ["Dismissed", "var(--faint)"],
};
// Engagements a client is actually working under.
const WORKING = new Set(["accepted"]);
const ENDED_APPT = new Set(["cancelled", "declined", "rejected", "no_show", "completed"]);

const FEED_COLOUR = { appointment: "#6addeb", hearing: "#f28b80", document: "#b9a6f2", status: "var(--brand-text)" };
const TYPE_LOOK = (doc) => {
    const t = String(doc?.template_type || "").toLowerCase();
    if (t.includes("notice")) return ["NOTICE", "#f28b80"];
    if (t.includes("agreement") || t.includes("deed") || t.includes("contract")) return ["AGRMT", "var(--gold)"];
    return ["DOC", "#b9a6f2"];
};

const Svg = ({ d, s = 16, w = 2 }) => (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={w} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
);
const I = {
    search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-4.3-4.3",
    bell: "M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0",
    plus: "M12 5v14M5 12h14",
    chat: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
    doc: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6",
    check: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M9 15l2 2 4-4",
    brief: "M3 7h18v13H3zM8 7V4h8v3",
    cal: "M4 5h16v16H4zM4 10h16M9 3v4M15 3v4",
    user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
    hand: "M9 11V5a1.5 1.5 0 0 1 3 0v6M12 10V4a1.5 1.5 0 0 1 3 0v6M15 10V6a1.5 1.5 0 0 1 3 0v8a6 6 0 0 1-6 6h-1a6 6 0 0 1-5-2.7L3.5 13a1.5 1.5 0 0 1 2.5-1.6L9 15",
};

const initials = (s) => String(s || "?").split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join("").toUpperCase() || "?";
const ago = (iso) => {
    const t = new Date(iso).getTime();
    if (!t) return "";
    const m = Math.round((Date.now() - t) / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m} min ago`;
    const h = Math.round(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.round(h / 24);
    return d === 1 ? "yesterday" : d < 7 ? `${d} days ago` : formatPkt(iso, { day: "numeric", month: "short" });
};

const ModOverview = ({ onOpenNotifications }) => {
    const router = useRouter();
    const { user } = useAuth();
    const {
        cases, appointments, notifications, unreadCount,
        appointmentsComplete, appointmentsTotal, loadMoreAppointments,
    } = useCase();
    const [loadingMore, setLoadingMore] = useState(false);
    const [moreError, setMoreError] = useState(null);
    const [engagements, setEngagements] = useState([]);
    const [docs, setDocs] = useState({ items: [], more: false, loaded: false });
    const [query, setQuery] = useState("");
    const [caseTab, setCaseTab] = useState("active");
    const searchRef = useRef(null);

    // The client's engagements (who works on which case) and documents.
    useEffect(() => {
        let live = true;
        Promise.resolve(listEngagements()).then(res => {
            if (!live) return;
            const rows = res?.data?.items || res?.data || [];
            setEngagements(Array.isArray(rows) ? rows : []);
        }).catch(() => {});
        Promise.resolve(myDocumentsV2({ limit: 10 })).then(res => {
            if (!live) return;
            const items = res?.data?.items || [];
            setDocs({ items: Array.isArray(items) ? items : [], more: Boolean(res?.data?.next_cursor), loaded: !res?.error });
        }).catch(() => {});
        return () => { live = false; };
    }, []);

    // "/" puts the cursor in search, as on the Lawyers page.
    useEffect(() => {
        const onKey = (e) => {
            if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
            const tag = (e.target?.tagName || "").toLowerCase();
            if (tag === "input" || tag === "textarea" || e.target?.isContentEditable) return;
            e.preventDefault();
            searchRef.current?.focus();
        };
        document.addEventListener("keydown", onKey);
        return () => document.removeEventListener("keydown", onKey);
    }, []);

    const q = query.trim().toLowerCase();
    const match = (...xs) => !q || xs.some(x => String(x || "").toLowerCase().includes(q));

    // NOT cases.length: a draft is not an open case.
    const activeCount = activeCases(cases).length;
    // The server's total where we have it; the cache is one page.
    const apptCount = Number.isInteger(appointmentsTotal) ? appointmentsTotal : appointments.length;

    const now = Date.now();
    const upcoming = useMemo(() => appointments
        .filter(a => new Date(a.scheduled_at).getTime() > now && !ENDED_APPT.has(a.status))
        .sort((a, b) => new Date(a.scheduled_at) - new Date(b.scheduled_at)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [appointments]);
    const next = upcoming[0];
    const daysTo = next ? Math.max(0, Math.ceil((new Date(next.scheduled_at).getTime() - now) / 86400000)) : null;

    const engagementFor = (caseId) => engagements.find(e => e.case_id === caseId && WORKING.has(e.status));
    // WHO WORKS ON A CASE: an accepted engagement, or the lawyer the case
    // itself names (cases assigned outside the hire flow carry only
    // `lawyer_id`). Names come from engagements and appointments, which both
    // carry them; the case does not.
    const lawyerNames = {};
    appointments.forEach(a => { if (a.lawyer_id && a.lawyer_name) lawyerNames[a.lawyer_id] = a.lawyer_name; });
    engagements.forEach(e => { if (e.lawyer_id && e.lawyer_name) lawyerNames[e.lawyer_id] = e.lawyer_name; });
    const lawyerOf = (c) => {
        const e = engagementFor(c._id);
        if (e) return { id: e.lawyer_id, name: e.lawyer_name || lawyerNames[e.lawyer_id] || "", c };
        if (c.lawyer_id && !isEndedCase(c) && !isDraftCase(c)) return { id: c.lawyer_id, name: lawyerNames[c.lawyer_id] || "", c };
        return null;
    };
    const working = [];
    cases.forEach(c => { const l = lawyerOf(c); if (l && !working.some(w => w.id === l.id)) working.push(l); });
    const lawyer = working[0];

    // What waits on the client: a draft to confirm, terms a lawyer proposed.
    const needs = [
        ...cases.filter(isDraftCase).map(c => ({
            key: `draft-${c._id}`, label: `Confirm your draft case — ${c.title || "Untitled case"}`,
            action: "Review", go: "/intake",
        })),
        ...engagements.filter(e => e.status === "terms_proposed").map(e => ({
            key: `terms-${e.id}`, label: `${e.lawyer_name || "A lawyer"} proposed terms for ${e.case_title || "your case"}`,
            action: "Review", go: "/lawyers",
        })),
    ];

    const shownCases = cases
        .filter(c => (caseTab === "closed" ? isEndedCase(c) : !isEndedCase(c)))
        .filter(c => match(c.title, c.case_number, c.case_type))
        .slice(0, 4);
    const closedCount = cases.filter(isEndedCase).length;
    const openCount = cases.length - closedCount;
    const shownDocs = docs.items.filter(d => match(d.title, d.template_type)).slice(0, 3);
    const feed = (notifications || []).slice(0, 5);

    const firstName = String(user?.full_name || "").trim().split(/\s+/)[0] || "";
    const todayLine = formatPkt(new Date(), { weekday: "long", day: "numeric", month: "long" });
    const summary = [
        needs.length ? `${needs.length === 1 ? "One thing needs" : `${needs.length} things need`} you` : "Nothing needs you right now",
        next ? `your next appointment is ${daysTo === 0 ? "today" : daysTo === 1 ? "tomorrow" : `in ${daysTo} days`}` : "no appointment is booked",
    ].join(", and ") + ".";

    const stats = [
        { n: activeCount, t: "Active cases", d: "Open or in progress", c: "var(--brand-text)", icon: I.brief, go: "/tracking" },
        { n: apptCount, t: "Appointments", d: next ? `Next: ${formatPkt(next.scheduled_at, { day: "numeric", month: "short" })}` : "None ahead", c: "#6addeb", icon: I.cal, go: "/tracking" },
        { n: docs.loaded ? `${docs.items.length}${docs.more ? "+" : ""}` : "—", t: "Documents", d: "Drafts and vault", c: "#b9a6f2", icon: I.doc, go: "/documents" },
        { n: working.length, t: "Lawyers", d: "Working with you", c: "var(--gold)", icon: I.user, go: "/lawyers" },
    ];

    return (
        <div data-overview>
            <style>{OVERVIEW_CSS}</style>

            <div className="ov-top">
                <label className="ov-search">
                    <Svg d={I.search} />
                    <span style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>Search your cases and documents</span>
                    <input ref={searchRef} type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search your cases and documents" />
                    <span className="ov-kbd" aria-hidden="true">/</span>
                </label>
                <span style={{ flex: 1 }} />
                <button type="button" className="ov-bell" aria-label={`Notifications${unreadCount ? `, ${unreadCount} unread` : ""}`} onClick={() => onOpenNotifications?.()}>
                    <Svg d={I.bell} s={18} />
                    {unreadCount > 0 && <i aria-hidden="true" />}
                </button>
            </div>

            <section className="ov-card ov-hero">
                <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
                    <div>
                        <div style={{ fontSize: 13, color: "var(--muted)" }}>{todayLine}</div>
                        <h1 className="ov-hello" style={{ fontFamily: DOCS_FONT }}>Assalam o Alaikum{firstName ? `, ${firstName}` : ""}</h1>
                        <div style={{ marginTop: 6, fontSize: 14.5, color: "var(--muted)" }}>{summary}</div>
                    </div>
                    {needs.length ? (
                        <div className="ov-well ov-need">
                            <span className="ov-badge" aria-hidden="true"><Svg d={I.check} s={18} /></span>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div className="ov-lbl" style={{ color: "var(--brand-text)" }}>Needs you{needs.length > 1 ? ` · ${needs.length}` : ""}</div>
                                <div className="ov-clip" style={{ fontWeight: 700, fontSize: 14.5, marginTop: 2, color: "var(--ink)" }}>{needs[0].label}</div>
                            </div>
                            <button type="button" className="ov-btn" onClick={() => router.push(needs[0].go)}>{needs[0].action} <span className="arr" aria-hidden="true">→</span></button>
                        </div>
                    ) : (
                        <div className="ov-well ov-need calm">
                            <span className="ov-ic" style={{ "--c": "var(--brand-text)" }}><Svg d={I.hand} s={18} /></span>
                            <div style={{ flex: 1, minWidth: 0, fontSize: 13.5, color: "var(--muted)" }}>
                                You are all caught up. Drafts to confirm and terms from a lawyer will appear here.
                            </div>
                        </div>
                    )}
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                        <button type="button" className={needs.length ? "ov-btn" : "ov-btn go"} style={{ "--a": "var(--brand-text)" }} onClick={() => router.push("/intake")}>
                            <span style={{ color: needs.length ? "var(--brand-text)" : "inherit", display: "inline-flex" }}><Svg d={I.plus} s={15} w={2.4} /></span>Start a new matter
                        </button>
                        <button type="button" className="ov-btn chat" style={{ "--a": "#b9a6f2" }} onClick={() => router.push("/chat")}><span style={{ color: "#b9a6f2", display: "inline-flex" }}><Svg d={I.chat} s={15} /></span>Ask AI</button>
                    </div>
                </div>

                <div className="ov-well" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
                    <div className="ov-lbl" style={{ color: "var(--brand-text)" }}>Next appointment</div>
                    {next ? (<>
                        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                            <div className="ov-date">
                                <b>{formatPkt(next.scheduled_at, { month: "short" }).toUpperCase()}</b>
                                <span style={{ fontFamily: DOCS_FONT }}>{formatPkt(next.scheduled_at, { day: "numeric" })}</span>
                            </div>
                            <div style={{ minWidth: 0 }}>
                                <div style={{ fontWeight: 700, fontSize: 14 }}>{next.mode === "video" ? "Video consultation" : next.mode === "in_person" ? "In-person meeting" : next.mode === "court" ? "Court hearing" : "Consultation"}</div>
                                <div style={{ fontSize: 12.5, color: "var(--muted)" }}>{formatPkt(next.scheduled_at, { weekday: "short", hour: "numeric", minute: "2-digit" })} PKT</div>
                                {(next.lawyer_name || next.lawyer?.full_name) && <div className="ov-clip" style={{ fontSize: 12.5, color: "var(--muted)" }}>with {next.lawyer_name || next.lawyer?.full_name}</div>}
                            </div>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: "var(--ink)" }}>
                            <span className="ov-bar" aria-hidden="true"><i style={{ width: `${Math.max(6, 100 - Math.min(daysTo, 30) * (100 / 30))}%` }} /></span>
                            {daysTo === 0 ? "today" : daysTo === 1 ? "tomorrow" : `in ${daysTo} days`}
                        </div>
                    </>) : (
                        <div className="ov-empty">No upcoming appointments.</div>
                    )}
                    <div style={{ display: "flex", gap: 8 }}>
                        <button type="button" className="ov-btn sm" style={{ flex: 1, "--a": "#6addeb" }} onClick={() => router.push("/tracking")}>{next ? "Details" : "See all"}</button>
                        <button type="button" className="ov-btn sm" style={{ flex: 1, "--a": "var(--gold)" }} onClick={() => router.push("/lawyers")}>Book a meeting</button>
                    </div>
                    {upcoming.length > 1 && <div style={{ fontSize: 12, color: "var(--faint)" }}>{upcoming.length - 1} more upcoming</div>}
                    {/* The cache holds one page; the rest is the client's click. */}
                    {appointmentsComplete === false && (
                        <div>
                            <button type="button" className="ov-link" disabled={loadingMore} aria-busy={loadingMore || undefined}
                                onClick={async () => {
                                    if (loadingMore) return;
                                    setLoadingMore(true);
                                    setMoreError(null);
                                    const ok = await loadMoreAppointments?.();
                                    setLoadingMore(false);
                                    if (!ok) setMoreError("Could not load more appointments.");
                                }}>
                                {loadingMore ? "Loading…" : "Load more appointments"}
                            </button>
                            {moreError && (
                                <div role="alert" style={{ fontSize: 11, color: "var(--danger)", marginTop: 4 }}>
                                    {moreError} The appointments already shown are unaffected.
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </section>

            <div className="ov-stats">
                {stats.map(s => (
                    <button key={s.t} type="button" className="ov-card ov-stat" style={{ "--c": s.c }} onClick={() => router.push(s.go)}>
                        <span className="ov-ic" style={{ width: 42, height: 42 }}><Svg d={s.icon} s={18} /></span>
                        <span style={{ flex: 1, minWidth: 0 }}>
                            <span className="t">{s.t}</span>
                            <span className="d ov-clip">{s.d}</span>
                        </span>
                        <span className="n" style={{ fontFamily: DOCS_FONT }}>{s.n}</span>
                    </button>
                ))}
            </div>

            <div className="ov-main">
                <div className="ov-col">
                    <section className="ov-card ov-sec">
                        <div className="ov-sec-head">
                            <h2 className="ov-h">Your cases</h2>
                            <div className="ov-seg" role="group" aria-label="Filter cases">
                                <button type="button" aria-pressed={caseTab === "active"} onClick={() => setCaseTab("active")}>Active {openCount}</button>
                                <button type="button" aria-pressed={caseTab === "closed"} onClick={() => setCaseTab("closed")}>Closed {closedCount}</button>
                            </div>
                            <span style={{ flex: 1 }} />
                            <button type="button" className="ov-link" onClick={() => router.push("/tracking")}>All cases →</button>
                        </div>
                        {shownCases.length ? shownCases.map(c => {
                            const [label, colour] = STATUS_LOOK[c.status] || [c.status || "Unknown", "var(--muted)"];
                            const stage = STAGE_OF[c.status] ?? 1;
                            const eng = lawyerOf(c);
                            const latest = isDraftCase(c) ? "Analysed — waiting for you to confirm"
                                : eng ? `With ${eng.name || "your lawyer"}`
                                : isEndedCase(c) ? "Closed"
                                : "No lawyer yet — find one";
                            return (
                                <button key={c._id} type="button" className="ov-well ov-case" style={{ "--c": colour }}
                                    onClick={() => router.push(isDraftCase(c) ? "/intake" : "/tracking")}>
                                    <span className="ov-av">{initials(c.title)}</span>
                                    <span style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 6 }}>
                                        <span style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                                            <span className="ov-clip" style={{ fontWeight: 700, fontSize: 14 }}>{c.title || "Untitled case"}</span>
                                            <span className="ov-pill">{label}</span>
                                        </span>
                                        <span className="ov-clip" style={{ fontSize: 12, color: "var(--muted)" }}>
                                            {latest}{c.updated_at ? ` · ${ago(c.updated_at)}` : ""}
                                        </span>
                                        <span className="ov-stages" aria-label={`Stage: ${STAGES[Math.min(stage, 4)]}`}>
                                            {STAGES.map((s, i) => <i key={s} title={s} data-on={i < stage ? "" : undefined} data-now={i === stage ? "" : undefined} />)}
                                        </span>
                                    </span>
                                    <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, fontSize: 11.5, color: "var(--faint)" }}>
                                        <span style={{ fontFamily: "'JetBrains Mono',monospace" }}>{c.case_number || c._id?.slice(-6)}</span>
                                        <span>{STAGES[Math.min(stage, 4)]}</span>
                                    </span>
                                </button>
                            );
                        }) : (
                            <div className="ov-empty">
                                {q ? "No case matches your search."
                                    : caseTab === "closed" ? "No closed cases."
                                    : "No cases yet — complete intake to create your first case."}
                            </div>
                        )}
                    </section>

                    <section className="ov-card ov-sec">
                        <div className="ov-sec-head">
                            <h2 className="ov-h">Recent documents</h2>
                            <span style={{ flex: 1 }} />
                            <button type="button" className="ov-link" onClick={() => router.push("/documents")}>Documents →</button>
                        </div>
                        {shownDocs.length ? (
                            <div className="ov-docs">
                                {shownDocs.map(d => {
                                    const [kind, colour] = TYPE_LOOK(d);
                                    return (
                                        <button key={d.id} type="button" className="ov-well ov-doc" onClick={() => router.push("/documents")}>
                                            <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                                <span className="ov-type" style={{ "--c": colour }}>{kind}</span>
                                                <span style={{ fontSize: 11.5, color: "var(--faint)" }}>{ago(d.updated_at || d.created_at)}</span>
                                            </span>
                                            <span className="ov-clip" style={{ fontWeight: 600, fontSize: 13 }}>{d.title || "Untitled document"}</span>
                                            <span className="ov-clip" style={{ fontSize: 11.5, color: "var(--muted)", textTransform: "capitalize" }}>{String(d.status || "draft").replace(/_/g, " ")}</span>
                                        </button>
                                    );
                                })}
                            </div>
                        ) : (
                            <div className="ov-empty">{q ? "No document matches your search." : "No documents yet — draft one from a template."}</div>
                        )}
                    </section>
                </div>

                <div className="ov-col">
                    <section className="ov-card ov-sec">
                        <h2 className="ov-h" style={{ marginBottom: 12 }}>Your lawyer</h2>
                        {lawyer ? (<>
                            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                                <span style={{ width: 48, height: 48, flex: "none", borderRadius: "50%", display: "grid", placeItems: "center", fontWeight: 800, color: "#04212a", background: "linear-gradient(135deg,#3ee0a1,#2ec4d6)" }}>{initials(lawyer.name || "L")}</span>
                                <div style={{ minWidth: 0 }}>
                                    <div className="ov-clip" style={{ fontWeight: 700, fontSize: 14.5 }}>{lawyer.name || "Your lawyer"}</div>
                                    <div className="ov-clip" style={{ fontSize: 12, color: "var(--muted)", textTransform: "capitalize" }}>
                                        {[lawyer.c.case_type, lawyer.c.title && `on ${lawyer.c.title}`].filter(Boolean).join(" · ")}
                                    </div>
                                </div>
                            </div>
                            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                                <button type="button" className="ov-btn sm" style={{ flex: 1, "--a": "var(--brand-text)" }} onClick={() => router.push("/tracking")}>Open case</button>
                                <button type="button" className="ov-btn sm" style={{ flex: 1, "--a": "var(--gold)" }} onClick={() => router.push("/lawyers")}>Book a meeting</button>
                            </div>
                            {working.length > 1 && <div style={{ marginTop: 8, fontSize: 12, color: "var(--faint)" }}>+ {working.length - 1} more lawyer{working.length > 2 ? "s" : ""} on your cases</div>}
                        </>) : (<>
                            <div className="ov-empty" style={{ paddingTop: 0 }}>No lawyer is working with you yet.</div>
                            <button type="button" className="ov-btn sm" style={{ "--a": "#6addeb" }} onClick={() => router.push("/lawyers")}>Find a lawyer →</button>
                        </>)}
                    </section>

                    <section className="ov-card ov-sec">
                        <h2 className="ov-h" style={{ marginBottom: 12 }}>Latest activity</h2>
                        {feed.length ? feed.map((n, i) => (
                            <div key={n.id || i} className="ov-feed" style={{ "--c": FEED_COLOUR[n.type] || "var(--brand-text)" }}>
                                <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                                    <span className="dot" aria-hidden="true" />
                                    {i < feed.length - 1 && <span className="line" aria-hidden="true" />}
                                </div>
                                <div style={{ minWidth: 0 }}>
                                    <div style={{ fontSize: 13, fontWeight: n.done ? 500 : 700, color: "var(--ink)" }}>{n.title}</div>
                                    {n.desc && <div className="ov-clip" style={{ fontSize: 12, color: "var(--muted)" }}>{n.desc}</div>}
                                    <div style={{ fontSize: 11.5, color: "var(--faint)" }}>{[n.date, n.time].filter(Boolean).join(" · ")}</div>
                                </div>
                            </div>
                        )) : (
                            <div className="ov-empty">No activity yet.</div>
                        )}
                        {feed.length > 0 && <button type="button" className="ov-link" onClick={() => onOpenNotifications?.()}>See all updates →</button>}
                    </section>
                </div>
            </div>
        </div>
    );
};

export default ModOverview;
