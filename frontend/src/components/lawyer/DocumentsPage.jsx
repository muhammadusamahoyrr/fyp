'use client';
// Lawyer Documents Page — paste your code here
import { useState } from "react";
import { useTheme } from "./theme.js";
import { useCase } from "./theme.js";
import { Btn, Input } from "./components.jsx";
import { Icon, I } from "./icons.jsx";

function StatusBadge({ status }) {
    const s = STATUS_STYLES[status] || STATUS_STYLES.Draft;
    return (
        <span style={{
            background: s.bg, color: s.color, border: `1px solid ${s.border}`,
            borderRadius: 20, padding: "3px 10px", fontSize: 11.5, fontWeight: 600, whiteSpace: "nowrap"
        }}>{status}</span>
    );
}

function EditMenu({ doc, onClose, anchorRef }) {
    const menuRef = useRef(null);
    const [pos, setPos] = useState({ top: 0, left: 0 });

    useEffect(() => {
        if (anchorRef?.current && menuRef?.current) {
            const rect = anchorRef.current.getBoundingClientRect();
            const menu = menuRef.current;
            const vw = window.innerWidth;
            let left = rect.right + 8;
            if (left + 220 > vw) left = rect.left - 228;
            setPos({ top: rect.top + window.scrollY, left });
        }
    }, []);

    useEffect(() => {
        const handler = (e) => { if (menuRef.current && !menuRef.current.contains(e.target) && !anchorRef?.current?.contains(e.target)) onClose(); };
        setTimeout(() => document.addEventListener("mousedown", handler), 0);
        return () => document.removeEventListener("mousedown", handler);
    }, []);

    return (
        <>
            <div style={{ position: "fixed", inset: 0, zIndex: 999 }} onClick={onClose} />
            <div ref={menuRef} style={{
                position: "fixed", top: pos.top, left: pos.left, zIndex: 1000,
                background: "#fff", borderRadius: 10, boxShadow: "0 8px 32px rgba(0,0,0,0.14), 0 2px 8px rgba(0,0,0,0.08)",
                border: "1px solid #e5e7eb", width: 220, overflow: "hidden",
                animation: "menuPop 0.15s cubic-bezier(.34,1.56,.64,1)"
            }}>
                <div style={{ padding: "10px 14px 6px", borderBottom: "1px solid #f1f5f9" }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: 0.5 }}>Editing</div>
                    <div style={{ fontSize: 12, color: "#374151", fontWeight: 600, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{doc.title}</div>
                </div>
                {EDIT_MENU.map((group, gi) => (
                    <div key={gi}>
                        <div style={{ padding: "6px 14px 2px", fontSize: 10, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: 0.5 }}>{group.group}</div>
                        {group.items.map((item, ii) => (
                            <button key={ii} onClick={onClose} style={{
                                display: "flex", alignItems: "center", gap: 9, width: "100%",
                                padding: "6px 14px", border: "none", background: "none", cursor: "pointer",
                                color: item.danger ? "#ef4444" : "#374151", fontSize: 12.5,
                                fontWeight: item.bold ? 700 : item.italic ? 400 : 500,
                                fontStyle: item.italic ? "italic" : "normal",
                                textDecoration: item.underline ? "underline" : "none",
                                textAlign: "left", transition: "background 0.1s",
                            }}
                                onMouseEnter={e => e.currentTarget.style.background = item.danger ? "#fef2f2" : "#f8fafc"}
                                onMouseLeave={e => e.currentTarget.style.background = "none"}
                            >
                                <span style={{ width: 18, textAlign: "center", fontSize: 13 }}>{item.icon}</span>
                                <span style={{ flex: 1 }}>{item.label}</span>
                                {item.shortcut && <span style={{ fontSize: 10, color: "#9ca3af", fontFamily: "monospace" }}>{item.shortcut}</span>}
                            </button>
                        ))}
                        {gi < EDIT_MENU.length - 1 && <div style={{ height: 1, background: "#f1f5f9", margin: "4px 0" }} />}
                    </div>
                ))}
            </div>
        </>
    );
}



// ─── THEME ────────────────────────────────────────────────────


// ─── SEED DATA ────────────────────────────────────────────────
const PENDING_DOCS = [
    { id: "ADOC-001", client: "Rajesh Singh", caseId: "CS-2024-089", caseCategory: "Civil", title: "Plaint — Singh vs. Municipal Corp.", type: "Plaint", status: "Pending Review", urgency: "Priority", fee: "PKR 5,000", submitted: "Mar 9, 2026", note: "Please verify property boundaries and cite CPC Order VII Rule 1." },
    { id: "ADOC-002", client: "Priya Sharma", caseId: "CS-2024-887", caseCategory: "Property", title: "Written Statement — Sharma Property", type: "Written Statement", status: "Pending Review", urgency: "Normal", fee: "PKR 4,500", submitted: "Mar 8, 2026", note: "" },
    { id: "ADOC-007", client: "Neha Verma", caseId: "CS-2024-091", caseCategory: "Criminal", title: "Bail Application — Verma", type: "Bail Application", status: "Pending Review", urgency: "Urgent", fee: "PKR 6,000", submitted: "Mar 10, 2026", note: "Urgent — hearing on Mar 12. Please prioritise." },
    { id: "ADOC-003", client: "Amit Patel", caseId: "CS-2024-085", caseCategory: "Labor", title: "Affidavit — Patel Employment", type: "Affidavit", status: "Under Review", urgency: "Normal", fee: "PKR 3,500", submitted: "Mar 7, 2026", note: "" },
    { id: "ADOC-004", client: "Vikram Kumar", caseId: "CS-2024-082", caseCategory: "Commercial", title: "Contract Agreement — Kumar", type: "Agreement", status: "Approved", urgency: "Normal", fee: "PKR 5,500", submitted: "Feb 28, 2026", note: "" },
    { id: "ADOC-006", client: "Rajesh Singh", caseId: "CS-2024-089", caseCategory: "Civil", title: "Vakalatnama — Singh Case", type: "Vakalatnama", status: "Final", urgency: "Normal", fee: "PKR 2,000", submitted: "Feb 20, 2026", note: "" },
];

const DOC_CONTENT = `IN THE COURT OF THE CIVIL JUDGE, LAHORE

Employment Dispute — Plaint No. ____/2026

Plaintiff: M. Usama, S/O [Father Name], CNIC [__________], R/O [Address], Rawalpindi.

Defendant: XYZ Corporation (Pvt.) Ltd., [Registered Address], Islamabad.

PLAINT UNDER ORDER VII RULE 1 CPC

1. That the plaintiff was employed with the defendant company as [Designation] since [Date], vide Employment Contract dated [__________].

2. That on February 12, 2026, the defendant unlawfully terminated the plaintiff's services without lawful cause and without serving the required notice period.

3. That the plaintiff is entitled to receive salary in lieu of notice period, unpaid dues, and compensation for wrongful termination.

PRAYER:
The plaintiff respectfully prays that this Honourable Court may be pleased to award PKR 500,000 as compensation together with costs of the suit.`;

const STEPS = [
    { id: "inbox", label: "Document Inbox", icon: "📥" },
    { id: "review", label: "Review & Validate", icon: "✏️" },
    { id: "decision", label: "Approve / Edit", icon: "⚖️" },
    { id: "notify", label: "Notify Client", icon: "📨" },
    { id: "final", label: "Final & Export", icon: "📤" },
];
const STEP_IDX = { inbox: 0, review: 1, decision: 2, notify: 3, final: 4 };

const STATUS_COLOR = {
    "Pending Review": { dot: "#FFC857", badge: "rgba(255,200,87,0.15)", text: "#FFC857", border: "rgba(255,200,87,0.3)" },
    "Under Review": { dot: "#5AB3FF", badge: "rgba(90,179,255,0.15)", text: "#5AB3FF", border: "rgba(90,179,255,0.3)" },
    "Approved": { dot: "#4DD4A3", badge: "rgba(77,212,163,0.15)", text: "#4DD4A3", border: "rgba(77,212,163,0.3)" },
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

// ─── TOPBAR ───────────────────────────────────────────────────
function DocTopbar({ title, step, onBack, onSave, onContinue, t, isDark, setIsDark, showContinue = true }) {
    return (
        <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "10px 24px", background: t.surface, borderBottom: `1px solid ${t.border}`
        }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <div style={{
                        width: 30, height: 30, borderRadius: 8,
                        background: `linear-gradient(135deg,${t.primary},#2C606E)`,
                        display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16
                    }}>⚖️</div>
                    <span style={{ fontSize: 14, fontWeight: 700, color: t.text }}>
                        Attorney<span style={{ color: t.primary }}>.AI</span>
                        <span style={{ fontSize: 10, color: t.textFaint, marginLeft: 6, fontWeight: 400 }}>Lawyer</span>
                    </span>
                </div>
                <div style={{ width: 1, height: 18, background: t.border }} />
                <div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>{title}</div>
                    <div style={{ fontSize: 10, color: t.textFaint }}>Tuesday, March 10, 2026</div>
                </div>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                {onBack && <Btn variant="secondary" size="sm" onClick={onBack}>← Back</Btn>}
                {onSave && <Btn variant="ghost" size="sm" onClick={onSave}>💾 Save Draft</Btn>}
                {showContinue && onContinue && <Btn size="sm" onClick={onContinue}>Continue →</Btn>}
                <button onClick={() => setIsDark(d => !d)}
                    style={{
                        padding: "4px 10px", borderRadius: 20, border: `1px solid ${t.border}`,
                        background: t.cardHi, color: t.textMuted, fontSize: 10, cursor: "pointer", fontFamily: "inherit"
                    }}>
                    {isDark ? "☀️" : "🌙"}
                </button>
                <div style={{
                    width: 30, height: 30, borderRadius: "50%", background: t.primaryGlow,
                    border: `1.5px solid ${t.primary}40`, display: "flex", alignItems: "center",
                    justifyContent: "center", fontSize: 12, color: t.primary, cursor: "pointer"
                }}>🔔</div>
            </div>
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

const STATUS_COLOR_V2 = {
    "Pending Review": { dot: "#e8b84b", text: "#e8b84b", badge: "rgba(232,184,75,0.14)", border: "rgba(232,184,75,0.45)" },
    "Under Review": { dot: "#5aafd4", text: "#5aafd4", badge: "rgba(90,175,212,0.14)", border: "rgba(90,175,212,0.45)" },
    "Approved": { dot: "#3ec99a", text: "#3ec99a", badge: "rgba(62,201,154,0.14)", border: "rgba(62,201,154,0.45)" },
    "Final": { dot: "#38d8c4", text: "#38d8c4", badge: "rgba(56,216,196,0.14)", border: "rgba(56,216,196,0.45)" },
};

const URGENCY_V2 = {
    Normal: { dot: "#7a8f96", label: "#9ab0b8" },
    Priority: { dot: "#e8b84b", label: "#e8b84b" },
    Urgent: { dot: "#e8526a", label: "#e8526a" },
};

const ACTION_CFG = {
    "Pending Review": { label: "Review Now", icon: "👁", bg: "#b8890e", glow: "rgba(184,137,14,0.45)" },
    "Under Review": { label: "Review", icon: "📋", bg: "#2660a8", glow: "rgba(38,96,168,0.45)" },
    "Approved": { label: "Open", icon: "📁", bg: "#1e9868", glow: "rgba(30,152,104,0.45)" },
    "Final": { label: "Open", icon: "📁", bg: "#189888", glow: "rgba(24,152,136,0.45)" },
};

function ScreenInbox({ t, onOpen }) {
    const [statusF, setStatusF] = useState("All");
    const [search, setSearch] = useState("");

    const statusTabs = ["All", "Pending Review", "Under Review", "Approved", "Final"];
    const counts = Object.fromEntries(
        statusTabs.map(s => [s, s === "All"
            ? PENDING_DOCS.length
            : PENDING_DOCS.filter(d => d.status === s).length])
    );

    const filtered = PENDING_DOCS.filter(d =>
        (statusF === "All" || d.status === statusF) &&
        (d.title.toLowerCase().includes(search.toLowerCase()) ||
            d.client.toLowerCase().includes(search.toLowerCase()) ||
            d.caseId.toLowerCase().includes(search.toLowerCase()))
    );

    // Stat cards — each with a distinct, visible tinted background
    const statCards = [
        {
            label: "Pending Review", value: counts["Pending Review"], icon: "📥",
            numColor: "#e05565",
            bg: "linear-gradient(135deg, rgba(150,195,225,0.22) 0%, rgba(130,180,215,0.14) 100%)",
            border: "rgba(160,200,228,0.32)"
        },
        {
            label: "Under Review", value: counts["Under Review"], icon: "🔍",
            numColor: "#58b8d8",
            bg: "linear-gradient(135deg, rgba(90,145,170,0.20) 0%, rgba(70,125,155,0.12) 100%)",
            border: "rgba(95,150,178,0.30)"
        },
        {
            label: "Approved", value: counts["Approved"], icon: "✅",
            numColor: "#2ec890",
            bg: "linear-gradient(135deg, rgba(55,175,125,0.22) 0%, rgba(40,155,108,0.13) 100%)",
            border: "rgba(55,180,128,0.32)"
        },
        {
            label: "Finalized", value: counts["Final"], icon: "📤",
            numColor: "#20d0c0",
            bg: "linear-gradient(135deg, rgba(32,205,190,0.22) 0%, rgba(24,188,172,0.12) 100%)",
            border: "rgba(32,208,192,0.32)"
        },
    ];

    // Table column header labels + dedicated visible color
    const tableHeaders = ["DOCUMENT", "CLIENT", "CASE", "TYPE", "STATUS", "URGENCY", "ACTIONS", ""];

    return (
        <div style={{ flex: 1, padding: "22px 28px 36px", overflowY: "auto" }}>

            {/* ── Page header ────────────────────────────────── */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 22 }}>
                <div>
                    <div style={{ fontSize: 24, fontWeight: 700, color: t.text, fontFamily: "Georgia,serif", marginBottom: 4 }}>
                        Document Inbox
                    </div>
                    <div style={{ fontSize: 13, color: t.textMuted }}>
                        Client-submitted documents awaiting your legal review
                    </div>
                </div>
                <div style={{ display: "flex", gap: 10 }}>
                    <button style={{
                        display: "inline-flex", alignItems: "center", gap: 6,
                        padding: "9px 18px", borderRadius: 10,
                        border: `1.5px solid ${t.border}`, background: "transparent",
                        color: t.text, fontSize: 13, fontWeight: 600, fontFamily: "inherit", cursor: "pointer",
                        transition: "border-color .15s",
                    }}
                        onMouseEnter={e => e.currentTarget.style.borderColor = t.primary}
                        onMouseLeave={e => e.currentTarget.style.borderColor = t.border}
                    >↑ Upload Document</button>

                    <button style={{
                        display: "inline-flex", alignItems: "center", gap: 7,
                        padding: "9px 20px", borderRadius: 10, border: "none",
                        background: `linear-gradient(135deg, ${t.primary} 0%, #22a898 100%)`,
                        color: t.mode === "dark" ? "#0b1c22" : "#fff",
                        fontSize: 13, fontWeight: 700, fontFamily: "inherit", cursor: "pointer",
                        boxShadow: `0 3px 14px ${t.primary}45`,
                    }}>✨ AI Generate</button>
                </div>
            </div>

            {/* ── Stat cards ─────────────────────────────────── */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14, marginBottom: 26 }}>
                {statCards.map(s => (
                    <div key={s.label} style={{
                        display: "flex", justifyContent: "space-between", alignItems: "center",
                        padding: "18px 20px", borderRadius: 14,
                        background: s.bg, border: `1px solid ${s.border}`,
                        cursor: "pointer", transition: "transform .15s, box-shadow .15s",
                    }}
                        onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = `0 6px 20px ${s.border}`; }}
                        onMouseLeave={e => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = "none"; }}
                    >
                        <div>
                            <div style={{
                                fontSize: 10, fontWeight: 700, color: "rgba(200,220,230,0.75)",
                                textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 8,
                            }}>{s.label}</div>
                            <div style={{ fontSize: 32, fontWeight: 700, color: s.numColor, lineHeight: 1 }}>{s.value}</div>
                        </div>
                        <span style={{ fontSize: 30, opacity: 0.75 }}>{s.icon}</span>
                    </div>
                ))}
            </div>

            {/* ── Filter pills ──────────────────────────────── */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 18, flexWrap: "wrap" }}>
                {statusTabs.map(tab => {
                    const active = statusF === tab;
                    return (
                        <button key={tab} onClick={() => setStatusF(tab)} style={{
                            display: "inline-flex", alignItems: "center", gap: 6,
                            padding: "7px 14px", borderRadius: 999, border: "none",
                            background: active ? t.primary : "rgba(255,255,255,0.07)",
                            color: active ? (t.mode === "dark" ? "#0b1c22" : "#fff") : "rgba(200,220,230,0.75)",
                            fontSize: 12.5, fontWeight: active ? 700 : 500,
                            fontFamily: "inherit", cursor: "pointer",
                            boxShadow: active ? `0 2px 10px ${t.primary}45` : "none",
                            transition: "all .15s",
                        }}>
                            {tab === "All" ? "All Documents" : tab}
                            <span style={{
                                display: "inline-flex", alignItems: "center", justifyContent: "center",
                                minWidth: 20, height: 20, borderRadius: 999, padding: "0 5px",
                                background: active ? "rgba(255,255,255,0.22)" : "rgba(255,255,255,0.10)",
                                color: active ? (t.mode === "dark" ? "#0b1c22" : "#fff") : "rgba(200,220,230,0.7)",
                                fontSize: 11, fontWeight: 700,
                            }}>{counts[tab]}</span>
                        </button>
                    );
                })}
            </div>

            {/* ── Document Table ─────────────────────────────── */}
            <div style={{
                background: t.card, borderRadius: 14,
                border: `1px solid ${t.border}`, overflow: "hidden",
            }}>

                {/* ── Table header — high contrast, clearly visible ── */}
                <div style={{
                    display: "grid",
                    gridTemplateColumns: "2.4fr 0.9fr 0.9fr 1.1fr 1.15fr 0.85fr 1.25fr 32px",
                    padding: "14px 22px",
                    /* Distinct teal-tinted dark background so headers stand out */
                    background: "linear-gradient(90deg, rgba(28,68,80,0.95) 0%, rgba(22,58,70,0.95) 100%)",
                    borderBottom: `2px solid ${t.primary}40`,
                    alignItems: "center", gap: 8,
                }}>
                    {tableHeaders.map((h, i) => (
                        <div key={i} style={{
                            fontSize: 11.5,
                            fontWeight: 800,
                            /* Bright teal-white so text is unmistakably visible */
                            color: h ? "rgba(160,230,220,0.95)" : "transparent",
                            letterSpacing: "0.09em",
                            textTransform: "uppercase",
                            /* Subtle text shadow to lift off background */
                            textShadow: h ? "0 0 12px rgba(80,220,200,0.3)" : "none",
                        }}>{h}</div>
                    ))}
                </div>

                {/* Rows */}
                {filtered.map((doc, idx) => {
                    const sc = STATUS_COLOR_V2[doc.status] || STATUS_COLOR_V2["Under Review"];
                    const urg = URGENCY_V2[doc.urgency] || URGENCY_V2.Normal;
                    const ac = ACTION_CFG[doc.status] || ACTION_CFG["Final"];

                    return (
                        <div key={doc.id} style={{
                            display: "grid",
                            gridTemplateColumns: "2.4fr 0.9fr 0.9fr 1.1fr 1.15fr 0.85fr 1.25fr 32px",
                            padding: "14px 22px", alignItems: "center", gap: 8,
                            borderBottom: idx < filtered.length - 1 ? `1px solid ${t.border}` : "none",
                            transition: "background .12s", cursor: "pointer",
                        }}
                            onMouseEnter={e => e.currentTarget.style.background = `${t.primary}09`}
                            onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                        >
                            {/* DOCUMENT */}
                            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                                <div style={{
                                    width: 30, height: 36, borderRadius: 5, flexShrink: 0,
                                    background: `${t.primary}12`, border: `1px solid ${t.primary}28`,
                                    display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14,
                                }}>📄</div>
                                <div>
                                    <div style={{ fontSize: 13.5, fontWeight: 700, color: t.text, lineHeight: 1.3 }}>
                                        {doc.title}
                                    </div>
                                    <div style={{ fontSize: 11, color: t.textFaint, marginTop: 3 }}>{doc.submitted}</div>
                                </div>
                            </div>

                            {/* CLIENT */}
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <div style={{
                                    width: 30, height: 30, borderRadius: "50%", flexShrink: 0,
                                    background: `${t.primary}22`, border: `1.5px solid ${t.primary}50`,
                                    display: "flex", alignItems: "center", justifyContent: "center",
                                    fontSize: 10.5, fontWeight: 700, color: t.primary,
                                }}>
                                    {doc.client.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase()}
                                </div>
                                <span style={{ fontSize: 13, color: t.text, fontWeight: 500 }}>
                                    {doc.client.split(" ")[0]}
                                </span>
                            </div>

                            {/* CASE */}
                            <div style={{ fontSize: 12, color: "#4fb8e0", fontFamily: "monospace", fontWeight: 700 }}>
                                {doc.caseId}
                            </div>

                            {/* TYPE */}
                            <div style={{ fontSize: 12.5, color: t.textMuted, fontWeight: 400 }}>
                                {doc.type}
                            </div>

                            {/* STATUS */}
                            <span style={{
                                display: "inline-flex", alignItems: "center", gap: 6,
                                padding: "5px 12px", borderRadius: 999,
                                background: sc.badge, color: sc.text,
                                border: `1.5px solid ${sc.border}`,
                                fontSize: 12, fontWeight: 700, whiteSpace: "nowrap",
                            }}>
                                <span style={{
                                    width: 6, height: 6, borderRadius: "50%",
                                    background: sc.dot, flexShrink: 0,
                                    boxShadow: `0 0 5px ${sc.dot}`,
                                }} />
                                {doc.status}
                            </span>

                            {/* URGENCY */}
                            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                                <span style={{
                                    width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                                    background: urg.dot, display: "inline-block",
                                    boxShadow: `0 0 5px ${urg.dot}`,
                                }} />
                                <span style={{ fontSize: 12.5, fontWeight: 600, color: urg.label }}>
                                    {doc.urgency}
                                </span>
                            </div>

                            {/* ACTIONS */}
                            <button
                                onClick={e => { e.stopPropagation(); onOpen(doc); }}
                                style={{
                                    display: "inline-flex", alignItems: "center", gap: 7,
                                    padding: "8px 16px", borderRadius: 999, border: "none",
                                    background: ac.bg, color: "#fff",
                                    fontSize: 12.5, fontWeight: 700, fontFamily: "inherit",
                                    cursor: "pointer", whiteSpace: "nowrap",
                                    boxShadow: `0 3px 10px ${ac.glow}`,
                                    transition: "opacity .15s, transform .15s",
                                }}
                                onMouseEnter={e => { e.currentTarget.style.opacity = "0.82"; e.currentTarget.style.transform = "translateY(-1px)"; }}
                                onMouseLeave={e => { e.currentTarget.style.opacity = "1"; e.currentTarget.style.transform = "translateY(0)"; }}
                            >
                                {ac.icon} {ac.label}
                            </button>

                            {/* Checkbox */}
                            <div style={{
                                width: 18, height: 18, borderRadius: 4, flexShrink: 0,
                                border: `1.5px solid rgba(160,210,225,0.35)`,
                                background: "rgba(255,255,255,0.04)", cursor: "pointer",
                            }} />
                        </div>
                    );
                })}

                {/* Empty */}
                {!filtered.length && (
                    <div style={{ padding: "52px", textAlign: "center" }}>
                        <div style={{ fontSize: 34, marginBottom: 12 }}>📂</div>
                        <div style={{ fontSize: 15, fontWeight: 600, color: t.textMuted }}>No documents found</div>
                        <div style={{ fontSize: 12, color: t.textFaint, marginTop: 5 }}>Try adjusting your search or filter</div>
                    </div>
                )}
            </div>
        </div>
    );
}

// ═══════════════════════════════════════════════════════════════
// SCREEN 2 — REVIEW & VALIDATE
// Lawyer reads the full document, runs compliance checks
// Mirrors client Screen 2 (Review & Edit) — but lawyer perspective
// ═══════════════════════════════════════════════════════════════
function ScreenReview({ doc, t, onBack, onContinue }) {
    const [mode, setMode] = useState("view");
    const [content, setContent] = useState(DOC_CONTENT);
    const [checks] = useState([
        { label: "Legal Compliance", status: "verified" },
        { label: "Case Details", status: "verified" },
        { label: "Factual Info", status: "review" },
        { label: "Format", status: "passed" },
    ]);
    const statusStyle = {
        verified: { bg: "rgba(77,212,163,0.15)", color: "#4DD4A3", border: "rgba(77,212,163,0.3)", label: "✓ Verified" },
        review: { bg: "rgba(255,200,87,0.15)", color: "#FFC857", border: "rgba(255,200,87,0.3)", label: "⚠ Review" },
        passed: { bg: "rgba(64,240,220,0.15)", color: "#40F0DC", border: "rgba(64,240,220,0.3)", label: "✓ Passed" }
    };

    return (
        <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 300px", gap: 0, overflow: "hidden" }}>
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
                                {doc.type} · <span style={{ fontFamily: "monospace", color: t.primary, fontSize: 10 }}>{doc.caseId}</span> · {doc.client}
                            </div>
                        </div>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <StatusPill status={doc.status} t={t} />
                        <button onClick={() => setMode(m => m === "edit" ? "view" : "edit")}
                            style={{
                                padding: "5px 12px", borderRadius: 7, border: `1px solid ${t.border}`,
                                background: mode === "edit" ? t.primaryGlow : "transparent", color: mode === "edit" ? t.primary : t.textMuted,
                                fontSize: 11, cursor: "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", gap: 5
                            }}>
                            {mode === "edit" ? "👁 Preview" : "✏️ Edit"}
                        </button>
                    </div>
                </div>

                {/* Document content */}
                {mode === "view" ? (
                    <div style={{
                        background: t.card, borderRadius: 12, border: `1px solid ${t.border}`,
                        padding: "28px 36px", lineHeight: 1.85, color: t.text, fontSize: 13,
                        whiteSpace: "pre-wrap", fontFamily: "Georgia,serif", flex: 1, minHeight: 400
                    }}>
                        {content.split("\n").map((line, i) => {
                            const isBold = line.startsWith("Plaintiff:") || line.startsWith("Defendant:") || line.match(/^[A-Z\s]{4,}:?$/) || line.match(/^\d+\. /);
                            return <div key={i} style={{
                                fontWeight: isBold && line.match(/^[A-Z\s]{4,}:?$/) ? 700 : 400,
                                textAlign: line.includes("COURT") || line.includes("Employment Dispute") || line.includes("PRAYER") || line.includes("PLAINT") ? "center" : "left",
                                marginBottom: line === "" ? 8 : 3
                            }}>{line}</div>;
                        })}
                    </div>
                ) : (
                    <textarea value={content} onChange={e => setContent(e.target.value)} rows={24}
                        style={{
                            background: t.card, borderRadius: 12, border: `1px solid ${t.primary}`,
                            padding: "20px", lineHeight: 1.8, color: t.text, fontSize: 12,
                            fontFamily: "JetBrains Mono,monospace", flex: 1, outline: "none", resize: "vertical",
                            boxShadow: `0 0 0 3px rgba(64,240,220,0.1)`
                        }} />
                )}

                {/* Export bar */}
                <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                    {["📄 PDF", "⬇ Download", "✉️ Email", "🖨 Print"].map(lbl => (
                        <button key={lbl} style={{
                            flex: 1, padding: "9px 0", borderRadius: 9,
                            border: `1px solid ${t.border}`, background: t.card, color: t.textMuted,
                            fontSize: 11, cursor: "pointer", fontFamily: "inherit", fontWeight: 500
                        }}>{lbl}</button>
                    ))}
                </div>
            </div>

            {/* Right — compliance + client note */}
            <div style={{ display: "flex", flexDirection: "column", gap: 14, padding: "20px 18px", overflowY: "auto" }}>

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

                {/* Legal Compliance */}
                <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 12, padding: "14px 16px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 10 }}>
                        <span style={{ fontSize: 15 }}>✅</span>
                        <div>
                            <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>Legal Compliance</div>
                            <div style={{ fontSize: 10, color: t.textMuted }}>Automated checks</div>
                        </div>
                    </div>
                    {checks.map(c => {
                        const s = statusStyle[c.status];
                        return (
                            <div key={c.label} style={{
                                display: "flex", justifyContent: "space-between",
                                alignItems: "center", padding: "7px 0", borderBottom: `1px solid ${t.border}30`
                            }}>
                                <span style={{ fontSize: 12, color: t.textDim }}>{c.label}</span>
                                <span style={{
                                    fontSize: 10, padding: "2px 8px", borderRadius: 20,
                                    background: s.bg, color: s.color, border: `1px solid ${s.border}`, fontWeight: 700
                                }}>
                                    {s.label}
                                </span>
                            </div>
                        );
                    })}
                </div>

                {/* Document meta */}
                <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 12, padding: "14px 16px" }}>
                    <div style={{
                        fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase",
                        letterSpacing: "0.07em", marginBottom: 10
                    }}>Document Info</div>
                    {[
                        ["Type", doc.type],
                        ["Case Ref", doc.caseId],
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

                {/* Lawyer note input */}
                <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 12, padding: "14px 16px" }}>
                    <div style={{
                        fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase",
                        letterSpacing: "0.07em", marginBottom: 8
                    }}>✏️ Lawyer Notes</div>
                    <textarea placeholder="Add internal notes for this review..."
                        rows={3} style={{
                            width: "100%", border: `1px solid rgba(42,86,100,0.6)`,
                            borderRadius: 8, background: "rgba(42,86,100,0.2)", color: t.text, fontSize: 12,
                            padding: "8px 10px", outline: "none", resize: "vertical",
                            fontFamily: "DM Sans,system-ui", lineHeight: 1.6, boxSizing: "border-box"
                        }} />
                </div>

                {/* Continue to decision */}
                <Btn full onClick={onContinue}>⚖️ Proceed to Decision →</Btn>
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
function ScreenDecision({ doc, t, onBack, onApprove, onReject }) {
    const [decision, setDecision] = useState(null); // null | "approve" | "edit" | "reject"
    const [editNotes, setEditNotes] = useState("");
    const [rejectReason, setRejectReason] = useState("");
    const [returnNote, setReturnNote] = useState("");
    const [fee, setFee] = useState(doc.fee);

    return (
        <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 320px", gap: 0, overflow: "hidden" }}>

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
                            <div style={{ fontSize: 11, color: t.textMuted }}>{doc.client} · <span style={{ color: t.primary, fontFamily: "monospace" }}>{doc.caseId}</span></div>
                        </div>
                    </div>
                    <span style={{
                        fontSize: 11, padding: "3px 10px", borderRadius: 20,
                        background: "rgba(90,179,255,0.15)", color: "#5AB3FF", border: "1px solid rgba(90,179,255,0.3)",
                        fontWeight: 700
                    }}>Under Review</span>
                </div>

                <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 4 }}>⚖️ Your Decision</div>
                <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 18 }}>Select an action for this document</div>

                {/* Decision cards */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16, marginBottom: 28 }}>
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
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
                            <div>
                                <div style={{ fontSize: 10, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>Fee Charged</div>
                                <Input value={fee} onChange={e => setFee(e.target.value)} placeholder="PKR 5,000" />
                            </div>
                            <div>
                                <div style={{ fontSize: 10, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>Approval Date</div>
                                <Input value="Mar 10, 2026" placeholder="Date" />
                            </div>
                        </div>
                        <div style={{ marginBottom: 16 }}>
                            <div style={{ fontSize: 10, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>Approval Note to Client</div>
                            <Input type="textarea" rows={3} value={editNotes} onChange={e => setEditNotes(e.target.value)}
                                placeholder="e.g. Document approved. Please file within 7 working days..." />
                        </div>
                        <Btn full variant="success" onClick={onApprove}>✅ Confirm Approval & Notify Client</Btn>
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
                        <Btn full variant="warn" onClick={() => onReject("edit")}>↩ Return to Client with Notes</Btn>
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
                        <Btn full variant="danger" onClick={() => onReject("reject")}>❌ Confirm Rejection</Btn>
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
                        <StatusPill status="Under Review" t={t} />
                    </div>
                </div>

                {/* Fee selector */}
                <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 12, padding: "16px" }}>
                    <div style={{
                        fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase",
                        letterSpacing: "0.07em", marginBottom: 12
                    }}>💰 Review Fee</div>
                    {["PKR 2,000", "PKR 3,500", "PKR 5,000", "PKR 6,000"].map(f => (
                        <div key={f} onClick={() => setFee(f)}
                            style={{
                                display: "flex", justifyContent: "space-between", alignItems: "center",
                                padding: "10px 12px", borderRadius: 8, marginBottom: 6, cursor: "pointer",
                                border: `1px solid ${fee === f ? t.primary : t.border}`,
                                background: fee === f ? t.primaryGlow : "transparent", transition: "all .14s"
                            }}>
                            <span style={{ fontSize: 12, color: fee === f ? t.primary : t.textDim }}>{f}</span>
                            {fee === f && <span style={{ fontSize: 10, color: t.primary }}>✓</span>}
                        </div>
                    ))}
                </div>

                {/* Response timeline */}
                <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 12, padding: "16px" }}>
                    <div style={{
                        fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase",
                        letterSpacing: "0.07em", marginBottom: 12
                    }}>⏱ Response SLA</div>
                    {[
                        { l: "Normal", t2: "2–4 hours", extra: "", sel: doc.urgency === "Normal" },
                        { l: "Priority", t2: "~2 hours", extra: "+25%", sel: doc.urgency === "Priority" },
                        { l: "Urgent", t2: "< 1 hour", extra: "+60%", sel: doc.urgency === "Urgent" },
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
// SCREEN 4 — NOTIFY CLIENT
// Lawyer-approved doc — send notification to client
// Mirrors client "Submit to Lawyer" reversed perspective
// ═══════════════════════════════════════════════════════════════
function ScreenNotify({ doc, t, onBack, onContinue }) {
    const [notifType, setNotifType] = useState(doc.rejectionAction === "edit" ? "changes" : doc.rejectionAction === "reject" ? "rejected" : "approved");
    const [channel, setChannel] = useState("both");

    // Set default message based on notification type
    const getDefaultMessage = () => {
        if (doc.rejectionAction === "edit") {
            return "Your document requires some revisions. Please review the lawyer's notes and make the requested changes before resubmitting.";
        } else if (doc.rejectionAction === "reject") {
            return "Unfortunately, your document cannot proceed in its current form. Please review the rejection reason and contact your lawyer for guidance.";
        }
        return "Your document has been reviewed and approved by your lawyer. Please proceed to download the final version and file within 7 working days.";
    };

    const [msg, setMsg] = useState(getDefaultMessage());

    return (
        <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 300px", gap: 0, overflow: "hidden" }}>

            {/* Left */}
            <div style={{ padding: "22px 26px", overflowY: "auto", borderRight: `1px solid ${t.border}` }}>

                {/* Doc status banner */}
                <div style={{
                    display: "flex", alignItems: "center", gap: 10, padding: "12px 16px",
                    background: doc.rejectionAction === "edit" ? "rgba(255,200,87,0.1)" :
                        doc.rejectionAction === "reject" ? "rgba(255,107,122,0.1)" :
                            "rgba(77,212,163,0.1)",
                    border: doc.rejectionAction === "edit" ? "1px solid rgba(255,200,87,0.3)" :
                        doc.rejectionAction === "reject" ? "1px solid rgba(255,107,122,0.3)" :
                            "1px solid rgba(77,212,163,0.3)",
                    borderRadius: 12, marginBottom: 20
                }}>
                    <span style={{ fontSize: 20 }}>
                        {doc.rejectionAction === "edit" ? "✏️" : doc.rejectionAction === "reject" ? "❌" : "✅"}
                    </span>
                    <div>
                        <div style={{
                            fontSize: 13, fontWeight: 700,
                            color: doc.rejectionAction === "edit" ? "#FFC857" :
                                doc.rejectionAction === "reject" ? "#FF6B7A" :
                                    "#4DD4A3"
                        }}>
                            {doc.rejectionAction === "edit" ? "Document Needs Changes" :
                                doc.rejectionAction === "reject" ? "Document Rejected" :
                                    "Document Approved — Ready to Notify"}
                        </div>
                        <div style={{ fontSize: 11, color: t.textMuted }}>{doc.title} · {doc.client}</div>
                    </div>
                    <span style={{
                        marginLeft: "auto", fontSize: 11, padding: "3px 10px", borderRadius: 20,
                        background: doc.rejectionAction === "edit" ? "rgba(255,200,87,0.15)" :
                            doc.rejectionAction === "reject" ? "rgba(255,107,122,0.15)" :
                                "rgba(77,212,163,0.15)",
                        color: doc.rejectionAction === "edit" ? "#FFC857" :
                            doc.rejectionAction === "reject" ? "#FF6B7A" :
                                "#4DD4A3",
                        border: doc.rejectionAction === "edit" ? "1px solid rgba(255,200,87,0.3)" :
                            doc.rejectionAction === "reject" ? "1px solid rgba(255,107,122,0.3)" :
                                "1px solid rgba(77,212,163,0.3)",
                        fontWeight: 700
                    }}>
                        {doc.rejectionAction === "edit" ? "📝 Needs Edit" :
                            doc.rejectionAction === "reject" ? "❌ Rejected" :
                                "✓ Lawyer Approved"}
                    </span>
                </div>

                {/* Notification type */}
                <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 12 }}>📨 Notification Type</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10, marginBottom: 22 }}>
                    {[
                        { id: "approved", icon: "✅", label: "Approved", color: "#4DD4A3" },
                        { id: "changes", icon: "✏️", label: "Needs Edit", color: "#FFC857" },
                        { id: "rejected", icon: "❌", label: "Rejected", color: "#FF6B7A" },
                    ].map(n => (
                        <div key={n.id} onClick={() => setNotifType(n.id)}
                            style={{
                                padding: "12px", borderRadius: 11, cursor: "pointer", textAlign: "center",
                                border: `2px solid ${notifType === n.id ? n.color : t.border}`,
                                background: notifType === n.id ? `${n.color}12` : t.card, transition: "all .15s"
                            }}>
                            <div style={{ fontSize: 22, marginBottom: 5 }}>{n.icon}</div>
                            <div style={{ fontSize: 12, fontWeight: 700, color: notifType === n.id ? n.color : t.text }}>{n.label}</div>
                        </div>
                    ))}
                </div>

                {/* Message */}
                <div style={{ marginBottom: 18 }}>
                    <div style={{
                        fontSize: 10, fontWeight: 700, color: t.textFaint, textTransform: "uppercase",
                        letterSpacing: "0.07em", marginBottom: 7
                    }}>Message to Client</div>
                    <Input type="textarea" rows={5} value={msg} onChange={e => setMsg(e.target.value)}
                        placeholder="Write your message to the client..." />
                </div>

                {/* Channel */}
                <div style={{ fontSize: 12, fontWeight: 700, color: t.text, marginBottom: 10 }}>Notification Channel</div>
                <div style={{ display: "flex", gap: 10, marginBottom: 22 }}>
                    {[
                        { id: "email", label: "📧 Email only" },
                        { id: "sms", label: "📱 SMS only" },
                        { id: "both", label: "📧📱 Both" },
                    ].map(c => (
                        <button key={c.id} onClick={() => setChannel(c.id)}
                            style={{
                                flex: 1, padding: "9px", borderRadius: 9, cursor: "pointer",
                                border: `1.5px solid ${channel === c.id ? t.primary : t.border}`,
                                background: channel === c.id ? t.primaryGlow : t.card,
                                color: channel === c.id ? t.primary : t.textMuted, fontSize: 12, fontFamily: "inherit",
                                transition: "all .14s"
                            }}>
                            {c.label}
                        </button>
                    ))}
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    <Btn full variant="secondary" onClick={onBack}>← Back</Btn>
                    <Btn full onClick={onContinue}>📨 Send Notification →</Btn>
                </div>
            </div>

            {/* Right — preview */}
            <div style={{ padding: "22px 18px", overflowY: "auto" }}>
                <div style={{
                    fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase",
                    letterSpacing: "0.07em", marginBottom: 14
                }}>Notification Preview</div>

                {/* Mock message preview */}
                <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 12, padding: "16px", marginBottom: 14 }}>
                    <div style={{
                        display: "flex", alignItems: "center", gap: 8, marginBottom: 10, paddingBottom: 10,
                        borderBottom: `1px solid ${t.border}`
                    }}>
                        <Avatar name={doc.client} size={30} t={t} />
                        <div>
                            <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>To: {doc.client}</div>
                            <div style={{ fontSize: 10, color: t.textFaint }}>Re: {doc.title}</div>
                        </div>
                    </div>
                    <div style={{ fontSize: 12, color: t.textDim, lineHeight: 1.7 }}>{msg}</div>
                    <div style={{
                        marginTop: 10, paddingTop: 10, borderTop: `1px solid ${t.border}`,
                        fontSize: 10, color: t.textFaint
                    }}>
                        — John Doe, Advocate · AttorneyAI
                    </div>
                </div>

                {/* What client will see */}
                <div style={{
                    background: "rgba(64,240,220,0.06)", border: `1px solid ${t.primary}25`,
                    borderRadius: 12, padding: "12px 14px"
                }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: t.primary, marginBottom: 8 }}>📱 Client App Update</div>
                    {[
                        ["Document Status", "Approved"],
                        ["Step", "Final & Export"],
                        ["Reviewed by", "John Doe, Advocate"],
                        ["Date", "Mar 10, 2026"],
                    ].map(([k, v]) => (
                        <div key={k} style={{
                            display: "flex", justifyContent: "space-between",
                            padding: "4px 0", borderBottom: `1px solid ${t.border}20`
                        }}>
                            <span style={{ fontSize: 11, color: t.textFaint }}>{k}</span>
                            <span style={{ fontSize: 11, fontWeight: 600, color: t.primary }}>{v}</span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

// ═══════════════════════════════════════════════════════════════
// SCREEN 5 — FINAL & EXPORT
// Mirrors client Screen 4 exactly — final document view
// ═══════════════════════════════════════════════════════════════
function ScreenFinal({ doc, t, onBack }) {
    return (
        <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 300px", gap: 0, overflow: "hidden" }}>

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

                {/* Document */}
                <div style={{
                    background: t.card, borderRadius: 12, border: `1px solid ${t.border}`,
                    padding: "28px 36px", lineHeight: 1.85, color: t.text, fontSize: 13,
                    fontFamily: "Georgia,serif", marginBottom: 16
                }}>
                    {DOC_CONTENT.split("\n").map((line, i) => (
                        <div key={i} style={{
                            fontWeight: line.match(/^[A-Z\s]{4,}:?$/) ? 700 : 400,
                            textAlign: line.includes("COURT") || line.includes("Dispute") || line.includes("PRAYER") || line.includes("PLAINT") ? "center" : "left",
                            marginBottom: line === "" ? 8 : 3
                        }}>{line}</div>
                    ))}
                    {/* Footer */}
                    <div style={{
                        marginTop: 20, paddingTop: 12, borderTop: `1px solid ${t.border}`,
                        display: "flex", justifyContent: "space-between", alignItems: "center"
                    }}>
                        <span style={{ fontSize: 11, color: t.textFaint }}>🖊 Approved by Lawyer · John Doe</span>
                        <span style={{ fontSize: 11, color: t.textFaint }}>📅 Mar 10, 2026</span>
                    </div>
                </div>

                {/* Export options */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 8 }}>
                    {[["📄", "PDF"], ["⬇", "Download"], ["✉️", "Email"], ["🖨", "Print"]].map(([ic, lbl]) => (
                        <button key={lbl} style={{
                            padding: "10px 0", borderRadius: 10,
                            border: `1px solid ${t.border}`, background: t.card, color: t.textMuted,
                            fontSize: 11, cursor: "pointer", fontFamily: "inherit",
                            display: "flex", flexDirection: "column", alignItems: "center", gap: 4, fontWeight: 500
                        }}>
                            <span style={{ fontSize: 18 }}>{ic}</span>{lbl}
                        </button>
                    ))}
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
                        ["Case Ref", doc.caseId],
                        ["Client", doc.client],
                        ["Reviewer", "John Doe, Advocate"],
                        ["Status", "Final"],
                        ["Compliance", "✓ Verified"],
                    ].map(([k, v]) => (
                        <div key={k} style={{
                            display: "flex", justifyContent: "space-between", padding: "5px 0",
                            borderBottom: `1px solid ${t.border}20`
                        }}>
                            <span style={{ fontSize: 11, color: t.textFaint }}>{k}</span>
                            <span style={{
                                fontSize: 11, fontWeight: 600,
                                color: k === "Status" ? t.primary : k === "Compliance" ? t.success : t.textDim
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
function DocWorkflowApp() {
    const { t } = useTheme();
    const [screen, setScreen] = useState("inbox");   // inbox | review | decision | notify | final
    const [activeDoc, setActiveDoc] = useState(null);

    const openDoc = (doc) => { setActiveDoc(doc); setScreen("review"); };
    const reset = () => { setScreen("inbox"); setActiveDoc(null); };

    const screenTitles = { inbox: "Documents", review: "Documents", decision: "Documents", notify: "Documents", final: "Documents" };

    return (
        <div style={{
            minHeight: "100vh", display: "flex", flexDirection: "column",
            background: t.bg, fontFamily: "DM Sans,system-ui,sans-serif", color: t.text
        }}>

            <Stepper step={screen} t={t} />

            {screen === "inbox" && <ScreenInbox t={t} onOpen={openDoc} />}
            {screen === "review" && activeDoc && (
                <ScreenReview doc={activeDoc} t={t}
                    onBack={() => setScreen("inbox")}
                    onContinue={() => setScreen("decision")} />
            )}
            {screen === "decision" && activeDoc && (
                <ScreenDecision doc={activeDoc} t={t}
                    onBack={() => setScreen("review")}
                    onApprove={() => setScreen("notify")}
                    onReject={(action) => {
                        // Store the rejection action type for the notify screen
                        setActiveDoc(prev => ({ ...prev, rejectionAction: action }));
                        setScreen("notify");
                    }} />
            )}
            {screen === "notify" && activeDoc && (
                <ScreenNotify doc={activeDoc} t={t}
                    onBack={() => setScreen("decision")}
                    onContinue={() => setScreen("final")} />
            )}
            {screen === "final" && activeDoc && (
                <ScreenFinal doc={activeDoc} t={t} onBack={reset} />
            )}
        </div>
    );
}
// ============================================================
// APPOINTMENTS PAGE — exactly matching screenshots 1 & 2
// ============================================================

const CAL_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const CAL_DATES = [27, 28, 29, 30, 31, 1, 2];
const CAL_HOURS = ["9:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00"];
const calAppts = [
    { day: 4, hour: "9:00", client: "Rajesh Singh", purpose: "Case Review", type: "gavel" },
    { day: 1, hour: "10:00", client: "Rajesh Singh", purpose: "Case Review", type: "gavel" },
    { day: 2, hour: "10:00", client: "Priya Sharma", purpose: "Property Dispute", type: "video" },
    { day: 4, hour: "10:00", client: "Amit Patel", purpose: "Employment St...", type: "video" },
    { day: 0, hour: "11:00", client: "Priya Sharma", purpose: "Property Dispute", type: "gavel" },
    { day: 1, hour: "11:00", client: "Rajesh Singh", purpose: "Case Review", type: "gavel" },
    { day: 0, hour: "12:00", client: "Amit Patel", purpose: "Case Review", type: "gavel" },
    { day: 1, hour: "12:00", client: "Amit Patel", purpose: "Employment Strategy", type: "video" },
    { day: 4, hour: "12:00", client: "Neha Verma", purpose: "Property Dispute", type: "gavel" },
    { day: 0, hour: "13:00", client: "Vikram Kumar", purpose: "Employment Strategy", type: "video" },
];
export { DocWorkflowApp };
