'use client';
// Paste your ModTracking.jsx code here
import { useState, useEffect, useRef } from "react";
import { DARK, LIGHT, useT } from "./theme.js";
import { useCase } from "./CaseContext.jsx";

// ─── DATA ─────────────────────────────────────────────────────────────────────
const CASES = [
    {
        id: "C-001", title: "Ahmad vs. Tech Corp Ltd.", status: "In Progress", type: "Employment Dispute",
        filed: "Feb 10, 2026", court: "Civil Court, Lahore", judge: "Judge M. Tariq",
        lawyer: "Ahmad Raza Khan", progress: 3, total: 5, nextHearing: "Feb 25, 9:00 AM", pct: 60
    },
    {
        id: "C-002", title: "Ahmad vs. City Council", status: "In Progress", type: "Property Dispute",
        filed: "Jan 5, 2026", court: "High Court, Lahore", judge: "Judge S. Iqbal",
        lawyer: "Sana Mirza", progress: 1, total: 5, nextHearing: "Mar 12, 10:00 AM", pct: 20
    },
];

const MILESTONES = [
    { id: 1, status: "done", event: "Case Filed", date: "Feb 10", time: "10:30 AM", desc: "Case registered with court.", tag: "complete", milestoneId: "m1" },
    { id: 2, status: "done", event: "Initial Hearing", date: "Feb 14", time: "11:00 AM", desc: "Opening arguments presented.", tag: "hearing", milestoneId: "m2" },
    { id: 3, status: "done", event: "Discovery Documents", date: "Feb 20", time: "04:00 PM", desc: "All discovery documents submitted.", tag: "complete", milestoneId: "m3" },
    { id: 4, status: "active", event: "Court Hearing", date: "Feb 25", time: "9:00 AM", desc: "Pre-trial conference scheduled.", tag: "hearing", milestoneId: "m4" },
    { id: 5, status: "pending", event: "Trial Commencement", date: "Mar 10", time: "TBD", desc: "Awaiting court confirmation.", tag: "pending", milestoneId: "m5" },
];

const DOCUMENTS_INIT = [
    { id: 1, name: "Exhibit_C_Financials.pdf", type: "PDF", date: "Feb 20, 2026", category: "Evidence", size: "2.4 MB", version: 2, seenByLawyer: true, milestoneId: "m3" },
    { id: 2, name: "Pre-Trial_Brief_v3.docx", type: "DOCX", date: "Feb 18, 2026", category: "Legal Brief", size: "890 KB", version: 3, seenByLawyer: true, milestoneId: "m4" },
    { id: 3, name: "Court_Order_Feb14.pdf", type: "PDF", date: "Feb 14, 2026", category: "Court Order", size: "1.1 MB", version: 1, seenByLawyer: true, milestoneId: "m2" },
    { id: 4, name: "Contract_Scan_Original.jpg", type: "IMG", date: "Feb 10, 2026", category: "Evidence", size: "4.7 MB", version: 1, seenByLawyer: false, milestoneId: "m1" },
    { id: 5, name: "Discovery_Request.pdf", type: "PDF", date: "Feb 08, 2026", category: "Discovery", size: "670 KB", version: 1, seenByLawyer: true, milestoneId: "m3" },
    { id: 6, name: "Witness_List_Draft.docx", type: "DOCX", date: "Feb 07, 2026", category: "Legal Brief", size: "340 KB", version: 2, seenByLawyer: false, milestoneId: "m4" },
];

// Unified feed: all events in one array
const UNIFIED_FEED_INIT = [
    { id: "f1", type: "hearing", urgency: "critical", title: "Court Hearing", date: "Feb 25", dateRaw: "2026-02-25", time: "9:00 AM", desc: "Pre-trial conference — attend in person", milestoneId: "m4", done: false },
    { id: "f2", type: "deadline", urgency: "overdue", title: "Pre-Trial Brief", date: "Feb 20", dateRaw: "2026-02-20", time: "Due", desc: "Response to opposition motion — 1 day overdue", milestoneId: "m4", done: false },
    { id: "f3", type: "deadline", urgency: "urgent", title: "Witness List Sign-off", date: "Feb 23", dateRaw: "2026-02-23", time: "EOD", desc: "Confirm final witness list with your lawyer", milestoneId: "m4", done: false },
    { id: "f4", type: "reminder", urgency: "normal", title: "Review Exhibit C", date: "Feb 23", dateRaw: "2026-02-23", time: "9:00 AM", desc: "Review pages 8–14 before the hearing", milestoneId: "m4", done: false },
    { id: "f5", type: "document", urgency: "info", title: "Document Updated", date: "Feb 18", dateRaw: "2026-02-18", time: "11:00 AM", desc: "Pre-Trial Brief revised — v3 now available", milestoneId: "m4", done: true },
    { id: "f6", type: "response", urgency: "info", title: "Lawyer Response", date: "Feb 19", dateRaw: "2026-02-19", time: "2:30 PM", desc: "Atty. Ahmad Raza replied about Exhibit C", milestoneId: "m3", done: true },
    { id: "f7", type: "status", urgency: "info", title: "Status Updated", date: "Feb 20", dateRaw: "2026-02-20", time: "10:00 AM", desc: "Case moved to Pre-Trial Discovery phase", milestoneId: "m3", done: true },
    { id: "f8", type: "deadline", urgency: "upcoming", title: "Trial Commencement", date: "Mar 10", dateRaw: "2026-03-10", time: "TBD", desc: "Court trial begins — confirm availability", milestoneId: "m5", done: false },
];

const MESSAGES_INIT = [
    { id: 1, from: "lawyer", text: "The hearing on Feb 25 is critical. Please review Exhibit C pages 8–14. I need your witness list sign-off by Feb 23.", date: "Feb 18, 3:15 PM", milestoneId: "m4", milestoneName: "Court Hearing", seenByLawyer: true },
    { id: 2, from: "client", text: "Understood. Can you clarify what Exhibit C covers? I want to prepare properly.", date: "Feb 19, 10:42 AM", status: "answered", milestoneId: "m3", milestoneName: "Discovery Documents", seenByLawyer: true },
    { id: 3, from: "lawyer", text: "Exhibit C covers financial records for Jan–Jun 2025. Focus on the salary discrepancy on pg. 11.", date: "Feb 19, 2:30 PM", milestoneId: "m3", milestoneName: "Discovery Documents", seenByLawyer: true },
    { id: 4, from: "client", text: "Should I attend in person or is virtual attendance allowed for the Feb 25 hearing?", date: "Feb 21, 9:00 AM", status: "pending", milestoneId: "m4", milestoneName: "Court Hearing", seenByLawyer: false },
];

// ─── PRIMITIVES ───────────────────────────────────────────────────────────────
const DotGrid = ({ t }) => (
    <div style={{
        position: "absolute", inset: 0, pointerEvents: "none", zIndex: 0,
        backgroundImage: `radial-gradient(circle,${t.mode === "dark" ? "rgba(64,240,220,0.06)" : "rgba(44,96,110,0.05)"} 1px,transparent 1px)`,
        backgroundSize: "22px 22px"
    }} />
);

const Badge = ({ variant = "primary", children, t, sm }) => {
    const map = { primary: t.badgePrimary, success: t.badgeSuccess, danger: t.badgeDanger, warn: t.badgeWarn, info: t.badgeInfo, gray: t.badgeGray };
    const b = map[variant] || map.primary;
    return (
        <span style={{
            display: "inline-flex", alignItems: "center", gap: 4, fontSize: sm ? 10 : 11, fontWeight: 700,
            padding: sm ? "2px 7px" : "3px 10px", borderRadius: 20, background: b.bg, color: b.color, border: `1px solid ${b.border}`, whiteSpace: "nowrap"
        }}>
            {children}
        </span>
    );
};

const Card = ({ children, t, style = {}, onClick }) => (
    <div onClick={onClick} style={{
        background: t.card, borderRadius: 16, border: `1px solid ${t.border}`,
        boxShadow: t.shadowCard, overflow: "hidden", position: "relative", cursor: onClick ? "pointer" : "default", transition: "all 0.2s", ...style
    }}
        onMouseEnter={onClick ? e => { e.currentTarget.style.boxShadow = t.shadowHover; e.currentTarget.style.borderColor = t.borderHi; } : undefined}
        onMouseLeave={onClick ? e => { e.currentTarget.style.boxShadow = t.shadowCard; e.currentTarget.style.borderColor = t.border; } : undefined}>
        <DotGrid t={t} />
        <div style={{ position: "relative", zIndex: 1 }}>{children}</div>
    </div>
);

const SH = ({ icon, title, desc, badge, t }) => (
    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 20px", borderBottom: `1px solid ${t.border}` }}>
        <div style={{
            width: 36, height: 36, borderRadius: 10, background: t.primaryGlow2, border: `1px solid ${t.border}`,
            display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15, flexShrink: 0
        }}>{icon}</div>
        <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>{title}</div>
            {desc && <div style={{ fontSize: 11, color: t.textMuted, marginTop: 1 }}>{desc}</div>}
        </div>
        {badge}
    </div>
);

const Btn = ({ children, variant = "ghost", onClick, style = {}, t, full, disabled }) => {
    const [hov, setHov] = useState(false);
    const vs = {
        ghost: { background: hov ? t.cardHi : "transparent", border: `1px solid ${hov ? t.borderHi : t.border}`, color: t.textDim },
        primary: { background: disabled ? "rgba(64,240,220,0.12)" : hov ? t.primaryDim : t.primary, border: `1px solid ${disabled ? t.border : t.primary}`, color: disabled ? t.textFaint : t.mode === "dark" ? "#1A2E35" : "#fff" },
        danger: { background: "rgba(255,107,122,0.1)", border: "1px solid rgba(255,107,122,0.3)", color: t.danger },
    };
    return (
        <button onClick={disabled ? undefined : onClick} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)} disabled={disabled}
            style={{
                display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6, padding: "8px 16px",
                borderRadius: 10, cursor: disabled ? "not-allowed" : "pointer", fontSize: 12, fontWeight: 700, transition: "all 0.18s",
                width: full ? "100%" : undefined, opacity: disabled ? 0.6 : 1, ...(vs[variant] || vs.ghost), ...style
            }}>
            {children}
        </button>
    );
};

const Toggle = ({ value, onChange, t }) => (
    <div onClick={() => onChange(!value)} style={{
        width: 42, height: 24, borderRadius: 12, cursor: "pointer",
        background: value ? t.primary : t.accent, position: "relative", transition: "background 0.2s",
        border: `1px solid ${value ? t.primary : t.border}`, flexShrink: 0
    }}>
        <div style={{
            position: "absolute", width: 18, height: 18, background: "#fff", borderRadius: "50%",
            top: 2, left: value ? 20 : 2, transition: "left 0.2s", boxShadow: "0 1px 4px rgba(0,0,0,0.3)"
        }} />
    </div>
);

const Inp = ({ placeholder, value, onChange, type = "text", t, style = {} }) => {
    const [f, setF] = useState(false);
    return (
        <input type={type} placeholder={placeholder} value={value} onChange={e => onChange(e.target.value)}
            onFocus={() => setF(true)} onBlur={() => setF(false)}
            style={{
                width: "100%", background: f ? t.inputFocus : t.inputBg, border: `1px solid ${f ? t.primary : t.border}`,
                borderRadius: 10, padding: "9px 14px", color: t.text, fontSize: 13, outline: "none",
                transition: "all 0.2s", boxSizing: "border-box", ...style
            }} />
    );
};

const Tabs = ({ tabs, active, onChange, t }) => (
    <div style={{ display: "flex", gap: 0, borderBottom: `1px solid ${t.border}`, padding: "0 20px" }}>
        {tabs.map(tab => (
            <button key={tab.key} onClick={() => onChange(tab.key)} style={{
                padding: "10px 14px", border: "none",
                background: "transparent", cursor: "pointer", fontSize: 12, fontWeight: 700, transition: "all 0.15s",
                borderBottom: `2px solid ${active === tab.key ? t.primary : "transparent"}`, marginBottom: -1,
                color: active === tab.key ? t.primary : t.textMuted
            }}>
                {tab.label}{tab.count != null ? ` (${tab.count})` : ""}</button>
        ))}
    </div>
);

const Ring = ({ pct, t, size = 88 }) => {
    const r = 32, c = 2 * Math.PI * r, fill = c - (pct / 100) * c;
    return (
        <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
            <svg width={size} height={size} viewBox="0 0 80 80" style={{ transform: "rotate(-90deg)" }}>
                <circle cx="40" cy="40" r={r} fill="none" stroke={t.accent} strokeWidth="5" />
                <circle cx="40" cy="40" r={r} fill="none" stroke={t.primary} strokeWidth="5"
                    strokeDasharray={c} strokeDashoffset={fill} strokeLinecap="round" style={{ transition: "stroke-dashoffset 1.2s ease" }} />
            </svg>
            <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
                <span style={{ fontSize: 18, fontWeight: 800, color: t.text }}>{pct}%</span>
                <span style={{ fontSize: 9, color: t.textMuted, fontWeight: 600 }}>done</span>
            </div>
        </div>
    );
};

// ─── NAV ICONS ────────────────────────────────────────────────────────────────
const TrackIc = ({ name, s = 18, c = "currentColor" }) => {
    const icons = {
        overview: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></svg>,
        timeline: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>,
        documents: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14,2 14,8 20,8" /><line x1="8" y1="13" x2="16" y2="13" /><line x1="8" y1="17" x2="13" y2="17" /></svg>,
        notifications: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 01-3.46 0" /></svg>,
        communication: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" /></svg>,
        reminders: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" /></svg>,
    };
    return icons[name] || null;
};

// ─── URGENCY CONFIG ───────────────────────────────────────────────────────────
const urgencyConfig = (t) => ({
    critical: { color: t.danger, bg: "rgba(255,107,122,0.10)", border: "rgba(255,107,122,0.30)", label: "Critical", dot: t.danger },
    overdue: { color: t.danger, bg: "rgba(255,107,122,0.08)", border: "rgba(255,107,122,0.20)", label: "Overdue", dot: t.danger },
    urgent: { color: t.warn, bg: `${t.warn}18`, border: `${t.warn}33`, label: "Soon", dot: t.warn },
    upcoming: { color: t.info, bg: `${t.info}14`, border: `${t.info}28`, label: "Upcoming", dot: t.info },
    normal: { color: t.primary, bg: t.primaryGlow2, border: `${t.primary}33`, label: "Reminder", dot: t.primary },
    info: { color: t.textMuted, bg: t.cardHi, border: t.border, label: "Info", dot: t.textFaint },
});

const typeIcon = { hearing: "⚖️", deadline: "📅", reminder: "⏰", document: "📄", status: "🔄", response: "💬" };
const priorityOrder = { critical: 0, overdue: 1, urgent: 2, upcoming: 3, normal: 4, info: 5 };

// ─── SIDEBAR ──────────────────────────────────────────────────────────────────
const TRACKING_PAGES = [
    { key: "overview", label: "Overview", ico: "overview", badge: null },
    { key: "timeline", label: "Case Timeline", ico: "timeline", badge: null },
    { key: "documents", label: "Documents", ico: "documents", badge: 6, bv: "primary" },
    { key: "notifications", label: "Notifications", ico: "notifications", badge: 4, bv: "danger" },
    { key: "communication", label: "Communication", ico: "communication", badge: 2, bv: "info" },
    { key: "reminders", label: "Reminders", ico: "reminders", badge: 1, bv: "warn" },
];

const Sidebar = ({ page, onNavigate, collapsed, onToggle }) => {
    const t = useT();
    return (
        <div style={{
            width: collapsed ? 56 : 200, flexShrink: 0, background: t.surface, borderRight: `1px solid ${t.border}`,
            display: "flex", flexDirection: "column", transition: "width 0.25s cubic-bezier(0.4,0,0.2,1)", overflow: "hidden", height: "100%"
        }}>
            <div style={{
                height: 67, padding: collapsed ? "0 14px" : "0 16px", borderBottom: `1px solid ${t.border}`,
                display: "flex", alignItems: "center", justifyContent: collapsed ? "center" : "space-between", gap: 10, flexShrink: 0
            }}>
                {!collapsed && (
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div style={{
                            width: 32, height: 32, borderRadius: 10, background: `linear-gradient(135deg,${t.primary},${t.secondary})`,
                            display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, boxShadow: `0 4px 12px ${t.primaryGlow}`
                        }}>
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={t.mode === "dark" ? "#1A2E35" : "#fff"} strokeWidth="2.5">
                                <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
                            </svg>
                        </div>
                        <span style={{ fontSize: 15, fontWeight: 800, color: t.text, fontFamily: "'Sora','Inter',sans-serif", letterSpacing: "-0.3px", whiteSpace: "nowrap" }}>
                            Case<span style={{ color: t.primary }}>Track</span>
                        </span>
                    </div>
                )}
                <button onClick={onToggle} style={{
                    width: 32, height: 32, borderRadius: 8, background: "transparent",
                    border: `1px solid ${t.border}`, display: "flex", flexDirection: "column", alignItems: "center",
                    justifyContent: "center", gap: 4, cursor: "pointer", flexShrink: 0, transition: "all 0.15s"
                }}
                    onMouseEnter={e => { e.currentTarget.style.background = t.cardHi; e.currentTarget.style.borderColor = t.borderHi; }}
                    onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.borderColor = t.border; }}>
                    <span style={{ display: "block", width: 14, height: 1.5, background: t.textMuted, borderRadius: 1 }} />
                    <span style={{ display: "block", width: 14, height: 1.5, background: t.textMuted, borderRadius: 1 }} />
                    <span style={{ display: "block", width: 14, height: 1.5, background: t.textMuted, borderRadius: 1 }} />
                </button>
            </div>
            <div style={{ padding: "10px 8px", flex: 1, overflow: "auto" }}>
                {TRACKING_PAGES.map(l => {
                    const active = page === l.key;
                    return (
                        <div key={l.key} onClick={() => onNavigate(l.key)} style={{
                            display: "flex", alignItems: "center",
                            gap: collapsed ? 0 : 12, justifyContent: collapsed ? "center" : "flex-start",
                            padding: collapsed ? "12px 0" : "9px 12px", borderRadius: 10, marginBottom: 2, cursor: "pointer",
                            transition: "all 0.2s cubic-bezier(0.4,0,0.2,1)", background: active ? t.primaryGlow : "transparent",
                            color: active ? t.primary : t.textMuted, position: "relative"
                        }}
                            onMouseEnter={e => { if (!active) { e.currentTarget.style.background = t.inputBg; e.currentTarget.style.color = t.text; } }}
                            onMouseLeave={e => { if (!active) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = t.textMuted; } }}>
                            <div style={{ position: "relative", flexShrink: 0 }}>
                                <TrackIc name={l.ico} s={18} c={active ? t.primary : "currentColor"} />
                                {collapsed && l.badge != null && (
                                    <span style={{
                                        position: "absolute", top: -4, right: -4, minWidth: 14, height: 14, borderRadius: 7,
                                        background: t[l.bv || "primary"] || t.primary, color: t.mode === "dark" ? "#1A2E35" : "#fff",
                                        fontSize: 8, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center",
                                        padding: "0 3px", lineHeight: 1, border: `2px solid ${t.surface}`
                                    }}>{l.badge}</span>
                                )}
                            </div>
                            {!collapsed && (
                                <>
                                    <span style={{ fontSize: 13, fontWeight: active ? 700 : 500, whiteSpace: "nowrap", flex: 1, color: "inherit" }}>{l.label}</span>
                                    {l.badge != null && (
                                        <span style={{
                                            minWidth: 18, padding: "2px 6px", borderRadius: 999, fontSize: 10, fontWeight: 700, textAlign: "center",
                                            background: active ? t.primary : t.cardHi, color: active ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.textDim,
                                            border: `1px solid ${active ? t.primary : t.border}`
                                        }}>{l.badge}</span>
                                    )}
                                </>
                            )}
                            {active && !collapsed && (
                                <div style={{ width: 6, height: 6, borderRadius: "50%", background: t.primary, boxShadow: `0 0 8px ${t.primaryGlow}`, flexShrink: 0 }} />
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

// ─── TOP HEADER ───────────────────────────────────────────────────────────────
const TopHeader = ({ t, onBack, activeCaseId, cases, onCaseSwitch, unreadCount }) => {
    const [caseOpen, setCaseOpen] = useState(false);
    const activeCase = cases.find(c => c.id === activeCaseId) || cases[0];
    return (
        <div style={{
            height: 67, background: t.surface, borderBottom: `1px solid ${t.border}`,
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "0 20px", flexShrink: 0, gap: 12, position: "relative", zIndex: 20
        }}>
            <button onClick={onBack} style={{
                display: "flex", alignItems: "center", gap: 8, background: "transparent",
                border: `1px solid ${t.border}`, borderRadius: 8, padding: "6px 12px", cursor: "pointer",
                color: t.textMuted, fontSize: 12, fontWeight: 600, transition: "all 0.15s"
            }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = t.borderHi; e.currentTarget.style.color = t.text; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textMuted; }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="15 18 9 12 15 6" />
                </svg>
                Overview
            </button>

            {/* Multi-case switcher */}
            <div style={{ position: "relative" }}>
                <button onClick={() => setCaseOpen(p => !p)} style={{
                    display: "flex", alignItems: "center", gap: 8,
                    background: t.cardHi, border: `1px solid ${t.border}`, borderRadius: 8, padding: "6px 14px",
                    cursor: "pointer", color: t.text, fontSize: 12, fontWeight: 700, transition: "all 0.15s"
                }}
                    onMouseEnter={e => { e.currentTarget.style.borderColor = t.borderHi; }}
                    onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; }}>
                    <span style={{ width: 8, height: 8, borderRadius: "50%", background: t.success, flexShrink: 0 }} />
                    {activeCase.id} — {activeCase.title.length > 22 ? activeCase.title.slice(0, 22) + "…" : activeCase.title}
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                        <polyline points="6 9 12 15 18 9" />
                    </svg>
                </button>
                {caseOpen && (
                    <div style={{
                        position: "absolute", top: "calc(100% + 6px)", left: 0, minWidth: 260,
                        background: t.card, border: `1px solid ${t.border}`, borderRadius: 12,
                        boxShadow: t.shadowHover, zIndex: 100, overflow: "hidden"
                    }}>
                        <div style={{
                            padding: "8px 14px", fontSize: 10, fontWeight: 700, color: t.textMuted,
                            letterSpacing: "0.1em", textTransform: "uppercase", borderBottom: `1px solid ${t.border}`
                        }}>Switch Case</div>
                        {cases.map(cs => (
                            <div key={cs.id} onClick={() => { onCaseSwitch(cs.id); setCaseOpen(false); }}
                                style={{
                                    padding: "10px 14px", cursor: "pointer", display: "flex", alignItems: "center", gap: 10,
                                    background: cs.id === activeCaseId ? t.primaryGlow : "transparent", transition: "background 0.15s"
                                }}
                                onMouseEnter={e => { if (cs.id !== activeCaseId) e.currentTarget.style.background = t.cardHi; }}
                                onMouseLeave={e => { if (cs.id !== activeCaseId) e.currentTarget.style.background = "transparent"; }}>
                                <span style={{ width: 7, height: 7, borderRadius: "50%", background: cs.id === activeCaseId ? t.primary : t.textFaint, flexShrink: 0 }} />
                                <div style={{ flex: 1 }}>
                                    <div style={{ fontSize: 12, fontWeight: 700, color: cs.id === activeCaseId ? t.primary : t.text }}>{cs.id} — {cs.title}</div>
                                    <div style={{ fontSize: 10, color: t.textMuted }}>{cs.type} · {cs.court}</div>
                                </div>
                                {cs.id === activeCaseId && <span style={{ fontSize: 10, color: t.primary, fontWeight: 700 }}>Active</span>}
                            </div>
                        ))}
                    </div>
                )}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{ position: "relative" }}>
                    <button style={{
                        width: 34, height: 34, borderRadius: 8, background: "transparent", border: `1px solid ${t.border}`,
                        display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", color: t.textMuted, transition: "all 0.15s"
                    }}
                        onMouseEnter={e => { e.currentTarget.style.borderColor = t.borderHi; e.currentTarget.style.color = t.text; }}
                        onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textMuted; }}>
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 01-3.46 0" />
                        </svg>
                    </button>
                    {unreadCount > 0 && (
                        <span style={{
                            position: "absolute", top: -4, right: -4, width: 16, height: 16, borderRadius: "50%",
                            background: t.danger || "#ff6b7a", color: "#fff", fontSize: 9, fontWeight: 800,
                            display: "flex", alignItems: "center", justifyContent: "center", border: `2px solid ${t.surface}`
                        }}>{unreadCount}</span>
                    )}
                </div>
                <div style={{
                    width: 34, height: 34, borderRadius: "50%", background: `linear-gradient(135deg,${t.primary},${t.secondary})`,
                    display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 800,
                    color: t.mode === "dark" ? "#1A2E35" : "#fff", cursor: "pointer", flexShrink: 0, boxShadow: `0 2px 8px ${t.primaryGlow}`
                }}>MU</div>
            </div>
        </div>
    );
};

// ─── PAGE: OVERVIEW ───────────────────────────────────────────────────────────
function PageOverview({ setPage, activeCase, feed }) {
    const t = useT();
    const uc = urgencyConfig(t);
    const critical = feed.filter(f => !f.done && (f.urgency === "critical" || f.urgency === "overdue"));
    const upcoming = feed.filter(f => !f.done && (f.urgency === "urgent" || f.urgency === "upcoming")).slice(0, 2);
    const activeM = MILESTONES.find(m => m.status === "active");

    return (
        <div>
            {/* Hero card */}
            <Card t={t} style={{ marginBottom: 20 }}>
                <div style={{ padding: "20px 24px 14px" }}>
                    <div style={{ display: "flex", alignItems: "flex-start", gap: 16 }}>
                        <div style={{ flex: 1 }}>
                            <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                                <Badge variant="success" t={t}>● In Progress</Badge>
                                <Badge variant="warn" t={t}>{activeCase.type}</Badge>
                            </div>
                            <div style={{ fontSize: 26, fontWeight: 800, color: t.text, letterSpacing: "-0.4px", marginBottom: 4 }}>{activeCase.title}</div>
                            <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 14 }}>Filed {activeCase.filed} · {activeCase.court} · {activeCase.judge}</div>
                            <div style={{ marginBottom: 6 }}>
                                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                                    <span style={{ fontSize: 11, color: t.textMuted }}>Case progress ({activeCase.progress}/{activeCase.total} milestones)</span>
                                    <span style={{ fontSize: 11, color: t.primary, fontWeight: 700 }}>{activeCase.pct}%</span>
                                </div>
                                <div style={{ height: 6, background: t.accent, borderRadius: 3, overflow: "hidden" }}>
                                    <div style={{ height: "100%", width: `${activeCase.pct}%`, background: `linear-gradient(90deg,${t.primary},${t.secondary})`, borderRadius: 3 }} />
                                </div>
                            </div>
                            <div style={{ fontSize: 12, color: t.textDim }}>
                                Next: <span style={{ color: t.primary, fontWeight: 700 }}>Court Hearing</span> on <strong>Feb 25</strong> at 9:00 AM
                            </div>
                        </div>
                        <Ring pct={activeCase.pct} t={t} />
                    </div>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", borderTop: `1px solid ${t.border}` }}>
                    {[
                        { icon: "🗂", label: "CASE ID", val: activeCase.id, color: t.primary },
                        { icon: "✅", label: "PROGRESS", val: `${activeCase.progress}/${activeCase.total} Steps`, color: t.success },
                        { icon: "📅", label: "NEXT HEARING", val: activeCase.nextHearing, color: t.danger },
                        { icon: "👤", label: "ASSIGNED", val: activeCase.lawyer, color: t.info },
                    ].map((s, i) => (
                        <div key={s.label} style={{ padding: "14px 18px", display: "flex", alignItems: "center", gap: 10, borderRight: i < 3 ? `1px solid ${t.border}` : "none" }}>
                            <div style={{
                                width: 30, height: 30, borderRadius: 8, background: t.primaryGlow2, border: `1px solid ${t.border}`,
                                display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13
                            }}>{s.icon}</div>
                            <div>
                                <div style={{ fontSize: 9, fontWeight: 700, color: t.textMuted, letterSpacing: "0.1em", textTransform: "uppercase" }}>{s.label}</div>
                                <div style={{ fontSize: 12, fontWeight: 700, color: s.color, marginTop: 1 }}>{s.val}</div>
                            </div>
                        </div>
                    ))}
                </div>
            </Card>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 16 }}>
                {/* Action Required — unified feed preview */}
                <Card t={t} onClick={() => setPage("reminders")}>
                    <SH icon="🚨" title="Action Required" desc="Deadlines, hearings & reminders"
                        badge={<Badge variant="danger" t={t}>● {critical.length} Critical</Badge>} t={t} />
                    <div style={{ padding: 16 }}>
                        {critical.length > 0 && (
                            <>
                                <div style={{ fontSize: 10, fontWeight: 700, color: t.danger, letterSpacing: "0.1em", marginBottom: 8 }}>⚠ NEEDS ATTENTION</div>
                                {critical.map(f => {
                                    const u = uc[f.urgency];
                                    return (
                                        <div key={f.id} style={{
                                            display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: 10,
                                            background: u.bg, border: `1px solid ${u.border}`, marginBottom: 8
                                        }}>
                                            <span style={{ fontSize: 16, flexShrink: 0 }}>{typeIcon[f.type]}</span>
                                            <div style={{ flex: 1 }}>
                                                <div style={{ fontSize: 13, fontWeight: 700, color: u.color }}>{f.title}</div>
                                                <div style={{ fontSize: 11, color: t.textMuted }}>{f.date} · {f.time}</div>
                                            </div>
                                            <Badge variant="danger" t={t} sm>{u.label}</Badge>
                                        </div>
                                    );
                                })}
                            </>
                        )}
                        {upcoming.length > 0 && (
                            <>
                                <div style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, letterSpacing: "0.1em", marginBottom: 8, marginTop: 4 }}>UPCOMING</div>
                                {upcoming.map(f => {
                                    const u = uc[f.urgency];
                                    return (
                                        <div key={f.id} style={{
                                            display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: 10,
                                            background: t.cardHi, border: `1px solid ${t.border}`, marginBottom: 8
                                        }}>
                                            <span style={{ fontSize: 16, flexShrink: 0 }}>{typeIcon[f.type]}</span>
                                            <div style={{ flex: 1 }}>
                                                <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{f.title}</div>
                                                <div style={{ fontSize: 11, color: t.textMuted }}>{f.date}</div>
                                            </div>
                                            <Badge variant={f.urgency === "urgent" ? "warn" : "info"} t={t} sm>{u.label}</Badge>
                                        </div>
                                    );
                                })}
                            </>
                        )}
                    </div>
                </Card>

                {/* Timeline with "you are here" */}
                <Card t={t} onClick={() => setPage("timeline")}>
                    <SH icon="🕐" title="Case Timeline" desc="Milestones, hearings & court instructions"
                        badge={<Badge variant="success" t={t}>3/5 Done</Badge>} t={t} />
                    <div style={{ padding: "16px 20px" }}>
                        {activeM && (
                            <div style={{
                                padding: "8px 12px", borderRadius: 10, background: t.primaryGlow2,
                                border: `1px solid ${t.primary}44`, marginBottom: 14
                            }}>
                                <div style={{ fontSize: 10, fontWeight: 700, color: t.primary, letterSpacing: "0.08em", marginBottom: 2 }}>▶ YOU ARE HERE</div>
                                <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>{activeM.event}</div>
                                <div style={{ fontSize: 11, color: t.textMuted }}>{activeM.date} · {activeM.time}</div>
                            </div>
                        )}
                        {MILESTONES.slice(0, 4).map((m, i) => {
                            const isDone = m.status === "done", isActive = m.status === "active";
                            return (
                                <div key={m.id} style={{ display: "flex", gap: 12, paddingBottom: i < 3 ? 14 : 0, position: "relative" }}>
                                    {i < 3 && <div style={{ position: "absolute", left: 13, top: 28, width: 2, bottom: 0, background: t.border }} />}
                                    <div style={{
                                        width: 26, height: 26, borderRadius: "50%", border: `2px solid ${isActive ? t.primary : isDone ? t.success : t.border}`,
                                        background: isActive ? t.primaryGlow2 : isDone ? `${t.success}22` : "transparent",
                                        display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11,
                                        color: isActive ? t.primary : isDone ? t.success : t.textFaint,
                                        boxShadow: isActive ? `0 0 10px ${t.primaryGlow}` : "none", zIndex: 1, flexShrink: 0
                                    }}>
                                        {isDone ? "✓" : isActive ? "▶" : "○"}
                                    </div>
                                    <div style={{ flex: 1 }}>
                                        <div style={{ fontSize: 12, fontWeight: 700, color: isActive ? t.text : isDone ? t.textDim : t.textFaint }}>{m.event}</div>
                                        <div style={{ fontSize: 10, color: t.textFaint }}>{m.date}</div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </Card>

                {/* Notifications with urgency tiers */}
                <Card t={t} onClick={() => setPage("notifications")}>
                    <SH icon="🔔" title="Notifications" desc="Sorted by urgency"
                        badge={<Badge variant="warn" t={t}>{feed.filter(f => !f.done).length} Unread</Badge>} t={t} />
                    <div style={{ padding: "12px 20px" }}>
                        {[...feed].sort((a, b) => priorityOrder[a.urgency] - priorityOrder[b.urgency]).slice(0, 4).map((n, i) => {
                            const u = uc[n.urgency];
                            return (
                                <div key={n.id} style={{ display: "flex", gap: 10, padding: "9px 0", borderBottom: `1px solid ${t.border}`, opacity: n.done ? 0.5 : 1 }}>
                                    <div style={{
                                        width: 32, height: 32, borderRadius: 8, flexShrink: 0, background: u.bg, border: `1px solid ${u.border}`,
                                        display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14
                                    }}>{typeIcon[n.type] || "🔔"}</div>
                                    <div style={{ flex: 1 }}>
                                        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                                            <span style={{ fontSize: 12, fontWeight: 700, color: t.text }}>{n.title}</span>
                                            {!n.done && <span style={{ width: 6, height: 6, borderRadius: "50%", background: u.dot, display: "inline-block" }} />}
                                        </div>
                                        <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.4 }}>{n.desc}</div>
                                        <div style={{ fontSize: 10, color: t.textFaint, marginTop: 2 }}>{n.date}</div>
                                    </div>
                                </div>
                            );
                        })}
                        <div style={{ padding: "10px 0", textAlign: "center" }}>
                            <span onClick={e => { e.stopPropagation(); setPage("notifications"); }}
                                style={{ fontSize: 12, color: t.primary, fontWeight: 700, cursor: "pointer" }}>View all →</span>
                        </div>
                    </div>
                </Card>
            </div>

            {/* Bottom row */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                <Card t={t} onClick={() => setPage("documents")}>
                    <SH icon="📁" title="Documents" desc="Case files & uploads"
                        badge={<Badge variant="primary" t={t}>{DOCUMENTS_INIT.length} Files</Badge>} t={t} />
                    <div style={{ padding: "12px 20px" }}>
                        {DOCUMENTS_INIT.slice(0, 3).map((d, i) => (
                            <div key={d.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 0", borderBottom: i < 2 ? `1px solid ${t.border}` : "none" }}>
                                <span style={{ fontSize: 18 }}>{d.type === "PDF" ? "📄" : d.type === "DOCX" ? "📝" : "🖼"}</span>
                                <div style={{ flex: 1 }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                        <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>{d.name}</span>
                                        {d.version > 1 && <Badge variant="warn" t={t} sm>v{d.version}</Badge>}
                                    </div>
                                    <div style={{ fontSize: 10, color: t.textMuted }}>{d.category} · {d.date}</div>
                                </div>
                                <span style={{ fontSize: 10, color: d.seenByLawyer ? t.success : t.textFaint, fontWeight: 600, flexShrink: 0 }}>
                                    {d.seenByLawyer ? "✓✓" : "● Unseen"}
                                </span>
                            </div>
                        ))}
                        <div style={{ padding: "10px 0", textAlign: "center" }}>
                            <span style={{ fontSize: 12, color: t.primary, fontWeight: 700, cursor: "pointer" }}>View all documents →</span>
                        </div>
                    </div>
                </Card>

                <Card t={t} onClick={() => setPage("communication")}>
                    <SH icon="💬" title="Communication" desc="Messages & notes with your lawyer"
                        badge={<Badge variant="info" t={t}>2 Pending</Badge>} t={t} />
                    <div style={{ padding: "12px 20px" }}>
                        {MESSAGES_INIT.slice(0, 2).map((m, i) => (
                            <div key={m.id} style={{
                                padding: "10px 12px", borderRadius: 10, marginBottom: 8,
                                background: m.from === "client" ? t.primaryGlow2 : t.cardHi,
                                border: `1px solid ${m.from === "client" ? t.primary + "44" : t.border}`
                            }}>
                                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
                                    <span style={{ fontSize: 10, color: t.textFaint, fontWeight: 700 }}>
                                        {m.from === "lawyer" ? "Atty. Ahmad Raza" : "You"} · {m.date}
                                    </span>
                                    {m.from === "client" && (
                                        <span style={{ fontSize: 10, color: m.seenByLawyer ? t.success : t.textFaint, fontWeight: 600 }}>
                                            {m.seenByLawyer ? "✓✓ Seen" : "✓ Sent"}
                                        </span>
                                    )}
                                </div>
                                {m.milestoneName && <div style={{ fontSize: 10, color: t.primary, fontWeight: 600, marginBottom: 3 }}>● {m.milestoneName}</div>}
                                <div style={{ fontSize: 12, color: t.textDim, lineHeight: 1.5 }}>
                                    {m.text.slice(0, 80)}{m.text.length > 80 ? "…" : ""}
                                </div>
                            </div>
                        ))}
                        <div style={{ padding: "6px 0", textAlign: "center" }}>
                            <span style={{ fontSize: 12, color: t.primary, fontWeight: 700, cursor: "pointer" }}>Open conversation →</span>
                        </div>
                    </div>
                </Card>
            </div>
        </div>
    );
}

// ─── PAGE: TIMELINE ───────────────────────────────────────────────────────────
// Fix #5: accepts milestones prop — includes both static MILESTONES and any
// appointment milestones written by ModLawyers via CaseContext.
function PageTimeline({ milestones: propMilestones }) {
    const t = useT();
    const allMilestones = propMilestones || MILESTONES;
    const [tab, setTab] = useState("all");
    const [addNote, setAddNote] = useState(null);
    const [noteText, setNoteText] = useState("");
    const [tagLawyer, setTagLawyer] = useState(false);
    const [notes, setNotes] = useState({});
    const activeRef = useRef(null);

    useEffect(() => {
        setTimeout(() => activeRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }), 200);
    }, [tab]);

    const list = tab === "hearings" ? allMilestones.filter(m => m.tag === "hearing" || m.tag === "appointment")
        : tab === "done" ? allMilestones.filter(m => m.status === "done")
            : allMilestones;
    const tagStyle = { complete: { v: "success", l: "Complete" }, hearing: { v: "warn", l: "⚖ Hearing" }, pending: { v: "gray", l: "Pending" } };

    return (
        <div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 288px", gap: 16 }}>
                <Card t={t}>
                    <SH icon="🕐" title="Case Timeline" desc="Milestones, hearings & court instructions"
                        badge={<Badge variant="success" t={t}>{allMilestones.filter(m => m.status === "done").length}/{allMilestones.length} Done</Badge>} t={t} />
                    <Tabs tabs={[
                        { key: "all", label: "All", count: allMilestones.length },
                        { key: "hearings", label: "Hearings" },
                        { key: "done", label: "Completed" },
                    ]} active={tab} onChange={setTab} t={t} />
                    <div style={{ padding: "20px 24px" }}>
                        {list.map((m, i) => {
                            const isDone = m.status === "done", isActive = m.status === "active";
                            const tc = tagStyle[m.tag] || tagStyle.pending;
                            return (
                                <div key={m.id} ref={isActive ? activeRef : null}
                                    style={{ display: "flex", gap: 16, paddingBottom: i < list.length - 1 ? 28 : 0, position: "relative" }}>
                                    {i < list.length - 1 && <div style={{ position: "absolute", left: 15, top: 32, width: 2, bottom: 0, background: t.border }} />}
                                    <div style={{
                                        width: 32, height: 32, borderRadius: "50%",
                                        border: `2px solid ${isActive ? t.primary : isDone ? t.success : t.border}`,
                                        background: isActive ? t.primaryGlow2 : isDone ? `${t.success}22` : "transparent",
                                        display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, flexShrink: 0, zIndex: 1,
                                        color: isActive ? t.primary : isDone ? t.success : t.textFaint,
                                        boxShadow: isActive ? `0 0 14px ${t.primaryGlow}` : "none"
                                    }}>
                                        {isDone ? "✓" : isActive ? "▶" : "○"}
                                    </div>
                                    <div style={{ flex: 1, paddingTop: 4 }}>
                                        {isActive && <div style={{ fontSize: 10, fontWeight: 700, color: t.primary, letterSpacing: "0.08em", marginBottom: 4 }}>▶ YOU ARE HERE</div>}
                                        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                                            <div style={{ fontSize: 14, fontWeight: 700, color: isActive ? t.text : isDone ? t.textDim : t.textFaint }}>{m.event}</div>
                                            <div style={{ fontSize: 10, color: t.textFaint, textAlign: "right", flexShrink: 0, marginLeft: 12 }}>{m.date}<br />{m.time}</div>
                                        </div>
                                        <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 6 }}>{m.desc}</div>
                                        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                                            <Badge variant={tc.v} t={t} sm>{tc.l}</Badge>
                                            {notes[m.id] && <Badge variant="info" t={t} sm>📝 Note added</Badge>}
                                        </div>
                                        {addNote === m.id ? (
                                            <div style={{ marginTop: 10, background: t.cardHi, border: `1px solid ${t.border}`, borderRadius: 12, padding: 12 }}>
                                                <textarea value={noteText} onChange={e => setNoteText(e.target.value)} placeholder="Write note…"
                                                    style={{
                                                        width: "100%", minHeight: 60, background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 8,
                                                        padding: "8px 12px", color: t.text, fontSize: 12, outline: "none", resize: "vertical", boxSizing: "border-box", marginBottom: 8
                                                    }} />
                                                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                                                    <Toggle value={tagLawyer} onChange={setTagLawyer} t={t} />
                                                    <span style={{ fontSize: 11, color: t.textDim }}>Tag lawyer for review</span>
                                                </div>
                                                <div style={{ display: "flex", gap: 6 }}>
                                                    <Btn t={t} variant="primary" style={{ fontSize: 11 }} onClick={() => { setNotes(p => ({ ...p, [m.id]: noteText })); setAddNote(null); setNoteText(""); }}>Save Note</Btn>
                                                    <Btn t={t} variant="ghost" style={{ fontSize: 11 }} onClick={() => { setAddNote(null); setNoteText(""); }}>Cancel</Btn>
                                                </div>
                                            </div>
                                        ) : (
                                            <div style={{ marginTop: 6 }}>
                                                <span onClick={() => setAddNote(m.id)} style={{ fontSize: 11, color: t.primary, cursor: "pointer", fontWeight: 700 }}>+ Add Note / Tag Lawyer</span>
                                            </div>
                                        )}
                                        {notes[m.id] && addNote !== m.id && (
                                            <div style={{ marginTop: 6, background: t.inputBg, borderRadius: 8, padding: "8px 12px", borderLeft: `3px solid ${t.primary}`, fontSize: 12, color: t.textDim }}>{notes[m.id]}</div>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </Card>

                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                    <Card t={t}>
                        <SH icon="📊" title="Progress" desc="Milestone completion" t={t} />
                        <div style={{ padding: 16 }}>
                            {[{ l: "Completed", c: 3, col: t.success }, { l: "In Progress", c: 1, col: t.primary }, { l: "Pending", c: 1, col: t.textFaint }].map(item => (
                                <div key={item.l} style={{ marginBottom: 14 }}>
                                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                                        <span style={{ fontSize: 12, color: t.textDim, fontWeight: 500 }}>{item.l}</span>
                                        <span style={{ fontSize: 11, color: item.col, fontWeight: 700 }}>{item.c}/5</span>
                                    </div>
                                    <div style={{ height: 5, background: t.accent, borderRadius: 3, overflow: "hidden" }}>
                                        <div style={{ height: "100%", width: `${(item.c / 5) * 100}%`, background: item.col, borderRadius: 3 }} />
                                    </div>
                                </div>
                            ))}
                            <div style={{ fontSize: 11, color: t.textFaint, marginTop: 4, padding: "8px 10px", background: t.cardHi, borderRadius: 8 }}>
                                % = milestones marked complete by your lawyer
                            </div>
                        </div>
                    </Card>
                    <Card t={t}>
                        <SH icon="📋" title="Court Instructions" t={t} />
                        <div style={{ padding: 14 }}>
                            {[
                                { color: t.warn, label: "⚖ Feb 14 Hearing", text: "Both parties to submit discovery docs by Feb 20." },
                                { color: t.textFaint, label: "📋 Pending", text: "Awaiting court instruction for trial schedule." },
                            ].map((c, i) => (
                                <div key={i} style={{ background: t.cardHi, border: `1px solid ${t.border}`, borderRadius: 10, padding: 12, marginBottom: i === 0 ? 10 : 0 }}>
                                    <div style={{ fontSize: 10, color: c.color, fontWeight: 700, marginBottom: 4 }}>{c.label}</div>
                                    <div style={{ fontSize: 12, color: t.textDim, lineHeight: 1.5 }}>{c.text}</div>
                                </div>
                            ))}
                        </div>
                    </Card>
                </div>
            </div>
        </div>
    );
}

// ─── PAGE: DOCUMENTS ──────────────────────────────────────────────────────────
function PageDocuments() {
    const t = useT();
    const [filter, setFilter] = useState("All");
    const [search, setSearch] = useState("");
    const [sort, setSort] = useState("date");
    const [expandedId, setExpandedId] = useState(null);
    const cats = ["All", "PDF", "DOCX", "Evidence", "Court Order", "Legal Brief", "Discovery"];
    const filtered = DOCUMENTS_INIT.filter(d =>
        (filter === "All" || d.type === filter || d.category === filter) &&
        (!search || d.name.toLowerCase().includes(search.toLowerCase()))
    );
    const dm = (type) => ({
        PDF: { icon: "📄", color: t.danger, bg: `${t.danger}18`, border: `${t.danger}33` },
        DOCX: { icon: "📝", color: t.primary, bg: t.primaryGlow2, border: `${t.primary}33` },
        IMG: { icon: "🖼", color: t.success, bg: `${t.success}18`, border: `${t.success}33` },
    }[type] || { icon: "📎", color: t.textMuted, bg: t.inputBg, border: t.border });

    return (
        <div>
            <Card t={t}>
                <SH icon="📁" title="Uploaded Documents" desc="View, open & download case documents"
                    badge={<Badge variant="primary" t={t}>{DOCUMENTS_INIT.length} Files</Badge>} t={t} />
                <div style={{ padding: "14px 20px", borderBottom: `1px solid ${t.border}` }}>
                    <div style={{ display: "flex", gap: 10, marginBottom: 10 }}>
                        <div style={{ flex: 1, position: "relative" }}>
                            <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: t.textMuted }}>🔍</span>
                            <Inp placeholder="Search documents…" value={search} onChange={setSearch} t={t} style={{ paddingLeft: 36 }} />
                        </div>
                        <select value={sort} onChange={e => setSort(e.target.value)}
                            style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 10, padding: "0 14px", color: t.textDim, fontSize: 12, fontWeight: 600, outline: "none", cursor: "pointer" }}>
                            {["date", "name", "type", "size"].map(s => <option key={s} value={s}>Sort: {s[0].toUpperCase() + s.slice(1)}</option>)}
                        </select>
                    </div>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        {cats.map(c => (
                            <button key={c} onClick={() => setFilter(c)}
                                style={{
                                    padding: "5px 12px", borderRadius: 20, border: `1px solid ${filter === c ? t.primary : t.border}`,
                                    background: filter === c ? t.primaryGlow2 : "transparent", color: filter === c ? t.primary : t.textMuted,
                                    fontSize: 11, fontWeight: 700, cursor: "pointer", transition: "all 0.15s"
                                }}>{c}</button>
                        ))}
                    </div>
                </div>
                <div style={{ padding: 20 }}>
                    {filtered.map(doc => {
                        const d = dm(doc.type);
                        const ms = MILESTONES.find(m => m.milestoneId === doc.milestoneId);
                        const isExpanded = expandedId === doc.id;
                        return (
                            <div key={doc.id} style={{ borderRadius: 12, border: `1px solid ${t.border}`, marginBottom: 8, background: t.cardHi, overflow: "hidden" }}>
                                <div onClick={() => setExpandedId(isExpanded ? null : doc.id)}
                                    style={{ display: "flex", alignItems: "center", gap: 14, padding: "12px 14px", cursor: "pointer" }}
                                    onMouseEnter={e => { e.currentTarget.style.background = t.card; }}
                                    onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}>
                                    <div style={{
                                        width: 38, height: 44, borderRadius: 8, background: d.bg, border: `1px solid ${d.border}`,
                                        display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, flexShrink: 0
                                    }}>{d.icon}</div>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3, flexWrap: "wrap" }}>
                                            <span style={{ fontSize: 13, fontWeight: 700, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{doc.name}</span>
                                            {doc.version > 1 && <Badge variant="warn" t={t} sm>v{doc.version} Updated</Badge>}
                                            <span style={{ fontSize: 10, color: doc.seenByLawyer ? t.success : t.textFaint, fontWeight: 600 }}>
                                                {doc.seenByLawyer ? "✓✓ Seen by lawyer" : "● Not yet seen"}
                                            </span>
                                        </div>
                                        <div style={{ display: "flex", gap: 10, fontSize: 11, color: t.textMuted, flexWrap: "wrap" }}>
                                            <span style={{ color: d.color, fontWeight: 700 }}>{doc.type}</span>
                                            <span>{doc.date}</span><span>{doc.category}</span><span>{doc.size}</span>
                                            {ms && <span style={{ color: t.primary, fontWeight: 600 }}>● {ms.event}</span>}
                                        </div>
                                    </div>
                                    <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                                        {["↗ Open", "↓ Download"].map(a => (
                                            <button key={a} onClick={e => e.stopPropagation()}
                                                style={{
                                                    padding: "5px 12px", borderRadius: 8, border: `1px solid ${t.border}`, background: "transparent",
                                                    color: t.textMuted, fontSize: 11, fontWeight: 600, cursor: "pointer", transition: "all 0.15s"
                                                }}
                                                onMouseEnter={e => { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.color = t.primary; }}
                                                onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textMuted; }}>{a}</button>
                                        ))}
                                    </div>
                                </div>
                                {/* Version history expand */}
                                {isExpanded && (
                                    <div style={{ padding: "0 14px 14px", borderTop: `1px solid ${t.border}` }}>
                                        <div style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, letterSpacing: "0.1em", textTransform: "uppercase", margin: "10px 0 8px" }}>Version History</div>
                                        {Array.from({ length: doc.version }, (_, i) => doc.version - i).map(v => (
                                            <div key={v} style={{
                                                display: "flex", alignItems: "center", gap: 10, padding: "6px 0",
                                                borderBottom: `1px solid ${t.border}`, opacity: v === doc.version ? 1 : 0.5
                                            }}>
                                                <span style={{ fontSize: 11, fontWeight: 700, color: v === doc.version ? t.primary : t.textMuted }}>v{v}</span>
                                                <span style={{ fontSize: 11, color: t.textMuted, flex: 1 }}>{v === doc.version ? "Current version" : "Previous version"}</span>
                                                {v === doc.version && <Badge variant="success" t={t} sm>Latest</Badge>}
                                                <button style={{ fontSize: 11, color: t.textMuted, background: "transparent", border: "none", cursor: "pointer" }}>↓</button>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </Card>
        </div>
    );
}

// ─── PAGE: NOTIFICATIONS ──────────────────────────────────────────────────────
// Fix #4: reads from CaseContext feed; mutations go through context helpers.
function PageNotifications({ feed, onMarkDone, onMarkAllDone }) {
    const t = useT();
    const [tab, setTab] = useState("all");
    const [settings, setSettings] = useState({
        pushHearing: true, pushStatus: true, pushDocs: true, pushReply: false,
        emailAll: true, emailDigest: true, emailWeekly: false, emailDeadline: true,
    });
    const uc = urgencyConfig(t);
    const unread = feed.filter(f => !f.done).length;
    const displayed = (
        tab === "unread" ? feed.filter(f => !f.done) :
            tab === "critical" ? feed.filter(f => f.urgency === "critical" || f.urgency === "overdue") :
                [...feed]
    ).sort((a, b) => priorityOrder[a.urgency] - priorityOrder[b.urgency]);

    const settingSections = [
        {
            title: "Push Notifications", icon: "📲", items: [
                { k: "pushHearing", l: "Hearing Reminders", d: "Reminders before scheduled hearings" },
                { k: "pushStatus", l: "Status Updates", d: "Case phase change alerts" },
                { k: "pushDocs", l: "Document Alerts", d: "When lawyer uploads documents" },
                { k: "pushReply", l: "Lawyer Replies", d: "Responses to your questions" },
            ]
        },
        {
            title: "Email Notifications", icon: "✉️", items: [
                { k: "emailAll", l: "Enable Email Notifications", d: "Global email toggle" },
                { k: "emailDigest", l: "Daily Digest", d: "End-of-day case summary" },
                { k: "emailWeekly", l: "Weekly Report", d: "Weekly progress summary" },
                { k: "emailDeadline", l: "Deadline Reminders", d: "48hrs before overdue items" },
            ]
        },
    ];

    return (
        <div>
            <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
                <Btn t={t} variant="ghost" onClick={onMarkAllDone}>✓ Mark All Read</Btn>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 308px", gap: 16 }}>
                <Card t={t}>
                    <SH icon="🔔" title="Notifications" desc="Sorted by urgency — critical items first"
                        badge={unread > 0 ? <Badge variant="danger" t={t}>{unread} Unread</Badge> : null} t={t} />
                    <Tabs tabs={[
                        { key: "all", label: "All", count: feed.length },
                        { key: "unread", label: "Unread", count: unread },
                        { key: "critical", label: "⚠ Critical", count: feed.filter(f => f.urgency === "critical" || f.urgency === "overdue").length },
                    ]} active={tab} onChange={setTab} t={t} />
                    <div style={{ padding: "4px 20px 20px" }}>
                        {displayed.map(n => {
                            const u = uc[n.urgency];
                            const ms = n.milestoneId ? MILESTONES.find(m => m.milestoneId === n.milestoneId) : null;
                            return (
                                <div key={n.id} onClick={() => !n.done && onMarkDone(n.id)}
                                    style={{
                                        display: "flex", gap: 12, padding: "14px 0", borderBottom: `1px solid ${t.border}`,
                                        opacity: n.done ? 0.45 : 1, cursor: "pointer", transition: "opacity 0.2s"
                                    }}>
                                    <div style={{
                                        width: 38, height: 38, borderRadius: 10, flexShrink: 0, background: u.bg, border: `1px solid ${u.border}`,
                                        display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16
                                    }}>{typeIcon[n.type] || "🔔"}</div>
                                    <div style={{ flex: 1 }}>
                                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3, flexWrap: "wrap" }}>
                                            <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>{n.title}</span>
                                            {!n.done && <span style={{ width: 7, height: 7, borderRadius: "50%", background: u.dot, display: "inline-block" }} />}
                                            <Badge variant={
                                                n.urgency === "critical" || n.urgency === "overdue" ? "danger" :
                                                    n.urgency === "urgent" ? "warn" :
                                                        n.urgency === "upcoming" ? "info" : "gray"
                                            } t={t} sm>{u.label}</Badge>
                                        </div>
                                        <div style={{ fontSize: 12, color: t.textDim, lineHeight: 1.5, marginBottom: 3 }}>{n.desc}</div>
                                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                                            <span style={{ fontSize: 10, color: t.textFaint }}>{n.date} · {n.time}</span>
                                            {ms && <span style={{ fontSize: 10, color: t.primary, fontWeight: 600 }}>● {ms.event}</span>}
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </Card>
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                    {settingSections.map(section => (
                        <Card key={section.title} t={t}>
                            <SH icon={section.icon} title={section.title} t={t} />
                            <div style={{ padding: "4px 20px 16px" }}>
                                {section.items.map((s, i) => (
                                    <div key={s.k} style={{
                                        display: "flex", alignItems: "center", gap: 12, padding: "10px 0",
                                        borderBottom: i < section.items.length - 1 ? `1px solid ${t.border}` : "none"
                                    }}>
                                        <div style={{ flex: 1 }}>
                                            <div style={{ fontSize: 13, color: t.text, fontWeight: 600 }}>{s.l}</div>
                                            <div style={{ fontSize: 11, color: t.textFaint }}>{s.d}</div>
                                        </div>
                                        <Toggle value={settings[s.k]} onChange={v => setSettings(p => ({ ...p, [s.k]: v }))} t={t} />
                                    </div>
                                ))}
                            </div>
                        </Card>
                    ))}
                </div>
            </div>
        </div>
    );
}

// ─── PAGE: COMMUNICATION ──────────────────────────────────────────────────────
function PageCommunication() {
    const t = useT();
    const [msgs, setMsgs] = useState(MESSAGES_INIT);
    const [input, setInput] = useState("");
    const [tab, setTab] = useState("messages");
    const [selMilestone, setSelMilestone] = useState("");
    const [selDoc, setSelDoc] = useState("");
    const [noteInput, setNoteInput] = useState("");
    const [tagL, setTagL] = useState(false);
    const [noteMilestone, setNoteMilestone] = useState("");
    const [notes, setNotes] = useState([
        { id: 1, milestone: "Court Hearing", note: "Review Exhibit C pages 8–14 carefully.", tagged: true, date: "Feb 20" },
    ]);
    const endRef = useRef(null);
    useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

    const canSend = input.trim() && selMilestone;
    const send = () => {
        if (!canSend) return;
        const milestoneName = MILESTONES.find(m => m.milestoneId === selMilestone)?.event || "";
        setMsgs(p => [...p, {
            id: Date.now(), from: "client", text: input, date: "Just now", status: "pending",
            milestoneId: selMilestone, milestoneName, seenByLawyer: false
        }]);
        setInput(""); setSelMilestone(""); setSelDoc("");
    };
    const saveNote = () => {
        if (!noteInput.trim() || !noteMilestone) return;
        setNotes(p => [...p, { id: Date.now(), milestone: MILESTONES.find(m => m.milestoneId === noteMilestone)?.event || noteMilestone, note: noteInput, tagged: tagL, date: "Just now" }]);
        setNoteInput(""); setTagL(false); setNoteMilestone("");
    };

    return (
        <div>
            <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
                <Badge variant="success" t={t}>● Atty. Ahmad Raza — Online</Badge>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 290px", gap: 16 }}>
                <Card t={t} style={{ display: "flex", flexDirection: "column" }}>
                    <SH icon="💬" title="Client–Lawyer Communication" desc="Messages, Q&A & milestone notes"
                        badge={<Badge variant="warn" t={t}>1 Awaiting</Badge>} t={t} />
                    <Tabs tabs={[
                        { key: "messages", label: "Messages & Q&A" },
                        { key: "notes", label: "Milestone Notes", count: notes.length },
                    ]} active={tab} onChange={setTab} t={t} />

                    {tab === "messages" ? (
                        <>
                            <div style={{ flex: 1, padding: "16px 20px", overflowY: "auto", maxHeight: 340 }}>
                                {msgs.map(m => (
                                    <div key={m.id} style={{
                                        display: "flex", flexDirection: "column",
                                        alignItems: m.from === "client" ? "flex-end" : "flex-start", marginBottom: 16
                                    }}>
                                        <div style={{ fontSize: 10, color: t.textFaint, marginBottom: 4, fontWeight: 600 }}>
                                            {m.from === "lawyer" ? "Atty. Ahmad Raza Khan" : "You"} · {m.date}
                                            {m.milestoneName && <span style={{ marginLeft: 8, color: t.primary }}>● {m.milestoneName}</span>}
                                        </div>
                                        <div style={{
                                            maxWidth: "82%", padding: "10px 14px", borderRadius: 12,
                                            background: m.from === "client" ? t.primaryGlow2 : t.cardHi,
                                            border: `1px solid ${m.from === "client" ? t.primary + "44" : t.border}`,
                                            color: t.text, fontSize: 13, lineHeight: 1.6
                                        }}>
                                            {m.text}
                                            {m.status && (
                                                <div style={{ marginTop: 6 }}>
                                                    <Badge variant={m.status === "answered" ? "success" : "warn"} t={t} sm>
                                                        {m.status === "answered" ? "✓ Answered" : "⏳ Awaiting Response"}
                                                    </Badge>
                                                </div>
                                            )}
                                        </div>
                                        {m.from === "client" && (
                                            <div style={{ fontSize: 10, color: m.seenByLawyer ? t.success : t.textFaint, marginTop: 3, fontWeight: 600 }}>
                                                {m.seenByLawyer ? "✓✓ Seen by lawyer" : "✓ Sent"}
                                            </div>
                                        )}
                                    </div>
                                ))}
                                <div ref={endRef} />
                            </div>
                            {/* Context-required send panel */}
                            <div style={{ padding: "12px 20px", borderTop: `1px solid ${t.border}` }}>
                                <div style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>
                                    Link to context before sending
                                </div>
                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
                                    <select value={selMilestone} onChange={e => setSelMilestone(e.target.value)}
                                        style={{
                                            background: t.inputBg, border: `1px solid ${selMilestone ? t.primary : t.border}`, borderRadius: 10,
                                            padding: "8px 12px", color: selMilestone ? t.text : t.textFaint, fontSize: 12, outline: "none", boxSizing: "border-box"
                                        }}>
                                        <option value="">— Milestone (required) —</option>
                                        {MILESTONES.map(m => <option key={m.id} value={m.milestoneId}>{m.event}</option>)}
                                    </select>
                                    <select value={selDoc} onChange={e => setSelDoc(e.target.value)}
                                        style={{
                                            background: t.inputBg, border: `1px solid ${selDoc ? t.primary : t.border}`, borderRadius: 10,
                                            padding: "8px 12px", color: selDoc ? t.text : t.textFaint, fontSize: 12, outline: "none", boxSizing: "border-box"
                                        }}>
                                        <option value="">— Document (optional) —</option>
                                        {DOCUMENTS_INIT.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                                    </select>
                                </div>
                                <div style={{ display: "flex", gap: 8 }}>
                                    <div style={{ flex: 1 }}>
                                        <Inp placeholder="Ask your lawyer a question…" value={input} onChange={setInput} t={t} />
                                    </div>
                                    <Btn t={t} variant="primary" onClick={send} disabled={!canSend}>Send ↗</Btn>
                                </div>
                                {!selMilestone && input.trim() && (
                                    <div style={{ fontSize: 11, color: t.warn, marginTop: 6 }}>⚠ Please link to a milestone before sending</div>
                                )}
                            </div>
                        </>
                    ) : (
                        <div style={{ padding: "16px 20px" }}>
                            {notes.map(n => (
                                <div key={n.id} style={{ background: t.cardHi, border: `1px solid ${t.border}`, borderRadius: 12, padding: 14, marginBottom: 10 }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                                        <span style={{ fontSize: 11, color: t.primary, fontWeight: 700 }}>● {n.milestone}</span>
                                        {n.tagged && <Badge variant="info" t={t} sm>👤 Lawyer Tagged</Badge>}
                                        <span style={{ marginLeft: "auto", fontSize: 10, color: t.textFaint }}>{n.date}</span>
                                    </div>
                                    <div style={{ fontSize: 13, color: t.textDim, lineHeight: 1.5 }}>{n.note}</div>
                                </div>
                            ))}
                        </div>
                    )}
                </Card>

                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                    <Card t={t}>
                        <SH icon="📌" title="Add Note to Milestone" t={t} />
                        <div style={{ padding: 16 }}>
                            <div style={{ marginBottom: 10 }}>
                                <div style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>Milestone</div>
                                <select value={noteMilestone} onChange={e => setNoteMilestone(e.target.value)}
                                    style={{
                                        width: "100%", background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 10,
                                        padding: "9px 12px", color: t.text, fontSize: 13, outline: "none", boxSizing: "border-box"
                                    }}>
                                    <option value="">— Select —</option>
                                    {MILESTONES.map(m => <option key={m.id} value={m.milestoneId}>{m.event}</option>)}
                                </select>
                            </div>
                            <div style={{ marginBottom: 10 }}>
                                <div style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>Note</div>
                                <textarea value={noteInput} onChange={e => setNoteInput(e.target.value)} placeholder="Add note or comment…"
                                    style={{
                                        width: "100%", minHeight: 70, background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 10,
                                        padding: "9px 12px", color: t.text, fontSize: 12, outline: "none", resize: "vertical", boxSizing: "border-box"
                                    }} />
                            </div>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                                <Toggle value={tagL} onChange={setTagL} t={t} />
                                <span style={{ fontSize: 12, color: t.textDim }}>Tag lawyer for review</span>
                            </div>
                            <Btn t={t} variant="primary" full onClick={saveNote}>Save Note</Btn>
                        </div>
                    </Card>
                    <Card t={t}>
                        <SH icon="❓" title="Question Status" t={t} />
                        <div style={{ padding: "0 16px 16px" }}>
                            {[
                                { q: "What does Exhibit C cover?", s: "answered", ms: "Discovery Documents" },
                                { q: "In person or virtual for Feb 25?", s: "pending", ms: "Court Hearing" },
                            ].map((q, i) => (
                                <div key={i} style={{ padding: "10px 0", borderBottom: i === 0 ? `1px solid ${t.border}` : "none" }}>
                                    <div style={{ fontSize: 11, color: t.primary, fontWeight: 600, marginBottom: 4 }}>● {q.ms}</div>
                                    <div style={{ fontSize: 12, fontWeight: 600, color: t.text, marginBottom: 6 }}>{q.q}</div>
                                    <Badge variant={q.s === "answered" ? "success" : "warn"} t={t} sm>
                                        {q.s === "answered" ? "✓ Answered" : "⏳ Awaiting Response"}
                                    </Badge>
                                </div>
                            ))}
                        </div>
                    </Card>
                </div>
            </div>
        </div>
    );
}

// ─── PAGE: REMINDERS — unified feed ──────────────────────────────────────────
function PageReminders({ feed, setFeed }) {
    const t = useT();
    const [tab, setTab] = useState("all");
    const [form, setForm] = useState({ desc: "", date: "", time: "", milestoneId: "" });
    const [editId, setEditId] = useState(null);
    const [editForm, setEditForm] = useState({});
    const uc = urgencyConfig(t);

    const displayed = (
        tab === "overdue" ? feed.filter(f => !f.done && (f.urgency === "overdue" || f.urgency === "critical")) :
            tab === "upcoming" ? feed.filter(f => !f.done && (f.urgency === "upcoming" || f.urgency === "urgent")) :
                tab === "done" ? feed.filter(f => f.done) :
                    [...feed]
    ).sort((a, b) => priorityOrder[a.urgency] - priorityOrder[b.urgency]);

    const conflictOn = (date) => date ? feed.find(f => f.dateRaw === date && !f.done) : null;

    const addReminder = () => {
        if (!form.desc || !form.date) return;
        const conflict = conflictOn(form.date);
        const ms = MILESTONES.find(m => m.milestoneId === form.milestoneId);
        setFeed(p => [...p, {
            id: "r" + Date.now(), type: "reminder", urgency: "normal",
            title: form.desc, date: form.date, dateRaw: form.date, time: form.time || "Any time",
            desc: ms ? `Linked to: ${ms.event}` : "Personal reminder",
            milestoneId: form.milestoneId || undefined, done: false,
            conflict: conflict ? conflict.title : null,
        }]);
        setForm({ desc: "", date: "", time: "", milestoneId: "" });
    };

    return (
        <div>
            <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
                <Btn t={t} variant="primary" onClick={() => document.getElementById("reminder-form")?.scrollIntoView({ behavior: "smooth" })}>+ New Reminder</Btn>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                <Card t={t}>
                    <SH icon="📋" title="All Events & Deadlines" desc="Hearings, deadlines & reminders — one view"
                        badge={<Badge variant="danger" t={t}>{feed.filter(f => !f.done && (f.urgency === "overdue" || f.urgency === "critical")).length} Overdue</Badge>} t={t} />
                    <Tabs tabs={[
                        { key: "all", label: "All", count: feed.length },
                        { key: "overdue", label: "Overdue", count: feed.filter(f => !f.done && (f.urgency === "overdue" || f.urgency === "critical")).length },
                        { key: "upcoming", label: "Upcoming", count: feed.filter(f => !f.done && (f.urgency === "upcoming" || f.urgency === "urgent")).length },
                        { key: "done", label: "Done", count: feed.filter(f => f.done).length },
                    ]} active={tab} onChange={setTab} t={t} />
                    <div style={{ padding: "12px 20px" }}>
                        {displayed.map(f => {
                            const u = uc[f.urgency];
                            const ms = f.milestoneId ? MILESTONES.find(m => m.milestoneId === f.milestoneId) : null;
                            const isEditing = editId === f.id;
                            return (
                                <div key={f.id} style={{
                                    borderRadius: 12, border: `1px solid ${f.done ? t.border : u.border}`,
                                    marginBottom: 10, overflow: "hidden", opacity: f.done ? 0.5 : 1, transition: "opacity 0.2s"
                                }}>
                                    <div style={{ display: "flex", alignItems: "flex-start", gap: 12, padding: "12px 14px", background: f.done ? t.cardHi : u.bg }}>
                                        <div onClick={() => setFeed(p => p.map(x => x.id === f.id ? { ...x, done: !x.done } : x))}
                                            style={{
                                                width: 22, height: 22, borderRadius: 6, border: `2px solid ${f.done ? t.success : u.color}`,
                                                background: f.done ? t.success : "transparent", cursor: "pointer", flexShrink: 0, marginTop: 2,
                                                display: "flex", alignItems: "center", justifyContent: "center",
                                                color: "#fff", fontSize: 11, fontWeight: 800, transition: "all 0.15s"
                                            }}>{f.done ? "✓" : ""}</div>
                                        <div style={{ flex: 1, minWidth: 0 }}>
                                            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
                                                <span style={{ fontSize: 16 }}>{typeIcon[f.type]}</span>
                                                <span style={{ fontSize: 13, fontWeight: 700, color: f.done ? t.textMuted : t.text, textDecoration: f.done ? "line-through" : "none" }}>{f.title}</span>
                                                <Badge variant={
                                                    f.urgency === "critical" || f.urgency === "overdue" ? "danger" :
                                                        f.urgency === "urgent" ? "warn" :
                                                            f.urgency === "upcoming" ? "info" :
                                                                f.urgency === "normal" ? "primary" : "gray"
                                                } t={t} sm>{u.label}</Badge>
                                                {f.conflict && <Badge variant="danger" t={t} sm>⚡ Conflicts with {f.conflict}</Badge>}
                                            </div>
                                            <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 4 }}>{f.desc}</div>
                                            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                                                <span style={{ fontSize: 11, color: u.color, fontWeight: 600 }}>{f.date} · {f.time}</span>
                                                {ms && <span style={{ fontSize: 11, color: t.primary, fontWeight: 600 }}>● {ms.event}</span>}
                                            </div>
                                        </div>
                                        <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                                            {f.type === "reminder" && !f.done && (
                                                <button onClick={() => { setEditId(f.id); setEditForm({ desc: f.title, date: f.dateRaw, time: f.time }); }}
                                                    style={{ background: "transparent", border: "none", color: t.textFaint, cursor: "pointer", fontSize: 13 }}>✏</button>
                                            )}
                                            {f.type === "reminder" && (
                                                <button onClick={() => setFeed(p => p.filter(x => x.id !== f.id))}
                                                    style={{ background: "transparent", border: "none", color: t.textFaint, cursor: "pointer", fontSize: 16, padding: "0 2px" }}>×</button>
                                            )}
                                        </div>
                                    </div>
                                    {isEditing && (
                                        <div style={{ padding: "10px 14px", borderTop: `1px solid ${t.border}`, background: t.cardHi }}>
                                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
                                                <Inp placeholder="Description" value={editForm.desc} onChange={v => setEditForm(p => ({ ...p, desc: v }))} t={t} />
                                                <Inp type="date" value={editForm.date} onChange={v => setEditForm(p => ({ ...p, date: v }))} t={t} />
                                            </div>
                                            <div style={{ display: "flex", gap: 6 }}>
                                                <Btn t={t} variant="primary" style={{ fontSize: 11 }} onClick={() => { setFeed(p => p.map(x => x.id === f.id ? { ...x, title: editForm.desc, dateRaw: editForm.date, date: editForm.date } : x)); setEditId(null); }}>Save</Btn>
                                                <Btn t={t} variant="ghost" style={{ fontSize: 11 }} onClick={() => setEditId(null)}>Cancel</Btn>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </Card>

                <div id="reminder-form" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                    <Card t={t}>
                        <SH icon="⏰" title="Set Custom Reminder" desc="Link to a milestone for context" t={t} />
                        <div style={{ padding: 16 }}>
                            <div style={{ marginBottom: 10 }}>
                                <div style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>Description</div>
                                <Inp placeholder="e.g. Review witness statement before hearing…" value={form.desc} onChange={v => setForm(p => ({ ...p, desc: v }))} t={t} />
                            </div>
                            <div style={{ marginBottom: 10 }}>
                                <div style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>Link to Milestone</div>
                                <select value={form.milestoneId} onChange={e => setForm(p => ({ ...p, milestoneId: e.target.value }))}
                                    style={{
                                        width: "100%", background: t.inputBg, border: `1px solid ${form.milestoneId ? t.primary : t.border}`, borderRadius: 10,
                                        padding: "9px 12px", color: t.text, fontSize: 12, outline: "none", boxSizing: "border-box"
                                    }}>
                                    <option value="">— No milestone —</option>
                                    {MILESTONES.map(m => <option key={m.id} value={m.milestoneId}>{m.event}</option>)}
                                </select>
                            </div>
                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 14 }}>
                                <div>
                                    <div style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>Date</div>
                                    <Inp type="date" value={form.date} onChange={v => setForm(p => ({ ...p, date: v }))} t={t} />
                                </div>
                                <div>
                                    <div style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>Time</div>
                                    <Inp type="time" value={form.time} onChange={v => setForm(p => ({ ...p, time: v }))} t={t} />
                                </div>
                            </div>
                            {form.date && conflictOn(form.date) && (
                                <div style={{
                                    padding: "8px 12px", borderRadius: 8, background: "rgba(255,107,122,0.08)",
                                    border: "1px solid rgba(255,107,122,0.2)", marginBottom: 10, fontSize: 11, color: t.danger
                                }}>
                                    ⚡ Another event on this date: <strong>{conflictOn(form.date)?.title}</strong>
                                </div>
                            )}
                            <Btn t={t} variant="primary" full onClick={addReminder} disabled={!form.desc || !form.date}>+ Create Reminder</Btn>
                        </div>
                    </Card>

                    <Card t={t}>
                        <SH icon="📊" title="Event Summary" t={t} />
                        <div style={{ padding: "8px 20px 16px" }}>
                            {[
                                { label: "Overdue", count: feed.filter(f => !f.done && (f.urgency === "overdue" || f.urgency === "critical")).length, color: t.danger },
                                { label: "Due soon", count: feed.filter(f => !f.done && f.urgency === "urgent").length, color: t.warn },
                                { label: "Upcoming", count: feed.filter(f => !f.done && f.urgency === "upcoming").length, color: t.info },
                                { label: "Completed", count: feed.filter(f => f.done).length, color: t.success },
                            ].map((s, i) => (
                                <div key={s.label} style={{
                                    display: "flex", justifyContent: "space-between", alignItems: "center",
                                    padding: "8px 0", borderBottom: i < 3 ? `1px solid ${t.border}` : "none"
                                }}>
                                    <span style={{ fontSize: 13, color: t.textDim }}>{s.label}</span>
                                    <span style={{ fontSize: 16, fontWeight: 800, color: s.color }}>{s.count}</span>
                                </div>
                            ))}
                        </div>
                    </Card>
                </div>
            </div>
        </div>
    );
}

// ─── ROOT ─────────────────────────────────────────────────────────────────────
// Fix #2: accepts isDark from Dashboard — no longer owns its own theme state.
// Fix #5: reads appointmentMilestones from CaseContext so booked appointments
//         appear on the timeline immediately.
export default function Module7({ isDark }) {
    const t = isDark ? DARK : LIGHT;
    const { notifications, markNotificationDone, markAllNotificationsDone, appointmentMilestones } = useCase();
    const [page, setPage] = useState("overview");
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
    const [activeCaseId, setActiveCaseId] = useState("C-001");

    // Merge static feed with CaseContext notifications so both sources appear
    const feed = notifications;
    const setFeed = () => { }; // mutations go through CaseContext helpers

    // Merge static milestones with any appointment milestones from Module 4
    const allMilestones = [...MILESTONES, ...appointmentMilestones];

    const activeCase = CASES.find(c => c.id === activeCaseId) || CASES[0];
    const unreadCount = feed.filter(f => !f.done).length;

    const pages = {
        overview: (props) => <PageOverview      {...props} activeCase={activeCase} feed={feed} />,
        timeline: (props) => <PageTimeline      {...props} milestones={allMilestones} />,
        documents: (props) => <PageDocuments     {...props} />,
        notifications: (props) => <PageNotifications {...props} feed={feed}
            onMarkDone={markNotificationDone}
            onMarkAllDone={markAllNotificationsDone} />,
        communication: (props) => <PageCommunication {...props} />,
        reminders: (props) => <PageReminders     {...props} feed={feed} setFeed={setFeed} />,
    };
    const PageComp = pages[page] || pages.overview;

    return (
        <>
            <style>{`
        ::-webkit-scrollbar{width:4px;height:4px;}
        ::-webkit-scrollbar-track{background:transparent;}
        ::-webkit-scrollbar-thumb{background:${t.accent};border-radius:2px;}
        input[type=date],input[type=time]{color-scheme:${t.mode};}
        textarea::placeholder,input::placeholder{color:${t.textFaint};}
        select option{background:${t.card};}
      `}</style>
            <div style={{ display: "flex", position: "absolute", inset: 0, background: t.bg, fontFamily: "'Inter',sans-serif", color: t.text, overflow: "hidden" }}>
                <Sidebar page={page} onNavigate={setPage} collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed(p => !p)} t={t} />
                <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
                    <TopHeader t={t} onBack={() => setPage("overview")}
                        activeCaseId={activeCaseId} cases={CASES} onCaseSwitch={setActiveCaseId} unreadCount={unreadCount} />
                    <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
                        <PageComp setPage={setPage} t={t} />
                    </div>
                </div>
            </div>
        </>
    );
}