'use client';
// Paste your Dashboard.jsx code here
import React, { useState, useRef, useEffect } from "react";
import { DARK, LIGHT, ThemeCtx, HeaderActionsCtx } from "./theme.js";
import { CaseProvider, useCase } from "./CaseContext.jsx";
import Ic from "./Ic.jsx";
import ThemeToggle from "./ThemeToggle.jsx";
import ModOverview from "./ModOverview.jsx";
import ModProfile from "./ModProfile.jsx";
import ModIntake from "./ModIntake.jsx";
import ModChatbot from "./ModChatbot.jsx";
import ModLawyers from "./ModLawyers.jsx";
import ModAgreements from "./ModAgreements.jsx";
import ModDocuments from "./ModDocuments.jsx";
import ModTracking from "./ModTracking.jsx";

/* ── paste logo1.jpg in the same folder as Dashboard.jsx ── */
const logoImg = "data:image/png;base64,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";

/* ─── Helpers ───────────────────────────────────────────────── */
const getLiveDate = () =>
    new Date().toLocaleDateString("en-US", {
        weekday: "long", year: "numeric", month: "long", day: "numeric",
    });

const SIDE_ITEMS = [
    { id: "overview", icon: "home", label: "Overview" },
    { id: "profile", icon: "user", label: "Profile" },
    { id: "intake", icon: "brief", label: "Legal Intake" },
    { id: "chatbot", icon: "bot", label: "AI Chat" },
    { id: "lawyers", icon: "search", label: "Lawyers" },
    { id: "agreements", icon: "pen", label: "Agreements" },
    { id: "documents", icon: "file", label: "Documents" },
    { id: "tracking", icon: "clock", label: "Tracking" },
];

/* ─── Notification Drawer ───────────────────────────────────── */
const NotifDrawer = ({ open, onClose, onGoTracking, t }) => {
    const { notifications, markNotificationDone, markAllNotificationsDone, unreadCount } = useCase();
    const drawerRef = useRef(null);

    useEffect(() => {
        if (!open) return;
        const handler = (e) => {
            if (drawerRef.current && !drawerRef.current.contains(e.target)) onClose();
        };
        document.addEventListener("mousedown", handler);
        return () => document.removeEventListener("mousedown", handler);
    }, [open, onClose]);

    const urgencyColor = (urgency) => {
        if (urgency === "critical" || urgency === "overdue") return t.danger;
        if (urgency === "urgent") return t.warn;
        if (urgency === "upcoming") return t.info;
        return t.textMuted;
    };

    const typeIcon = {
        hearing: "⚖️", deadline: "🗓", reminder: "🔔",
        document: "📄", response: "💬", status: "📊", appointment: "📅",
    };

    if (!open) return null;

    return (
        <div
            style={{ position: "fixed", inset: 0, zIndex: 200, background: "rgba(0,0,0,0.35)" }}
            onMouseDown={onClose}
        >
            <div
                ref={drawerRef}
                onMouseDown={e => e.stopPropagation()}
                style={{
                    position: "absolute", top: 0, right: 0, bottom: 0,
                    width: 380, background: t.surface,
                    borderLeft: `1.5px solid ${t.border}`,
                    display: "flex", flexDirection: "column",
                    boxShadow: "-8px 0 32px rgba(0,0,0,0.25)",
                    animation: "slideInRight 0.22s cubic-bezier(0.4,0,0.2,1)",
                }}
            >
                {/* Header */}
                <div style={{
                    padding: "18px 20px 14px",
                    borderBottom: `1.5px solid ${t.border}`,
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                }}>
                    <div>
                        <div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>Notifications</div>
                        <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>
                            {unreadCount > 0 ? `${unreadCount} unread` : "All caught up"}
                        </div>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        {unreadCount > 0 && (
                            <button onClick={markAllNotificationsDone} style={{
                                fontSize: 11, fontWeight: 700, color: t.primary,
                                background: t.primaryGlow2,
                                border: `1px solid ${t.primary}40`,
                                borderRadius: 8, padding: "5px 10px", cursor: "pointer",
                            }}>
                                Mark all read
                            </button>
                        )}
                        <button onClick={onClose} style={{
                            width: 28, height: 28, borderRadius: 8,
                            background: t.inputBg, border: `1px solid ${t.border}`,
                            color: t.textMuted, cursor: "pointer", fontSize: 14,
                            display: "flex", alignItems: "center", justifyContent: "center",
                        }}>✕</button>
                    </div>
                </div>

                {/* List */}
                <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
                    {notifications.length === 0 && (
                        <div style={{ textAlign: "center", padding: "48px 24px", color: t.textMuted, fontSize: 13 }}>
                            No notifications yet
                        </div>
                    )}
                    {notifications.map(n => (
                        <div
                            key={n.id}
                            onClick={() => !n.done && markNotificationDone(n.id)}
                            style={{
                                display: "flex", gap: 12, padding: "13px 20px",
                                borderBottom: `1px solid ${t.border}`,
                                opacity: n.done ? 0.45 : 1,
                                cursor: n.done ? "default" : "pointer",
                                transition: "opacity 0.18s, background 0.15s",
                                background: n.done ? "transparent" : `${urgencyColor(n.urgency)}06`,
                            }}
                            onMouseEnter={e => { if (!n.done) e.currentTarget.style.background = t.inputBg; }}
                            onMouseLeave={e => { if (!n.done) e.currentTarget.style.background = `${urgencyColor(n.urgency)}06`; }}
                        >
                            <div style={{
                                width: 36, height: 36, borderRadius: 10, flexShrink: 0,
                                background: `${urgencyColor(n.urgency)}18`,
                                border: `1px solid ${urgencyColor(n.urgency)}30`,
                                display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15,
                            }}>
                                {typeIcon[n.type] || "🔔"}
                            </div>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                                    <span style={{
                                        fontSize: 13, fontWeight: 700, color: t.text,
                                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                                    }}>{n.title}</span>

                                    <span style={{
                                        fontSize: 13, fontWeight: 700, color: t.text,
                                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                                    }}>{n.title}</span>
                                    {!n.done && (
                                        <span style={{
                                            width: 7, height: 7, borderRadius: "50%",
                                            background: urgencyColor(n.urgency), flexShrink: 0,
                                        }} />
                                    )}
                                </div>
                                <div style={{
                                    fontSize: 12, color: t.textDim, lineHeight: 1.5, marginBottom: 3,
                                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                                }}>{n.desc}</div>
                                <div style={{ fontSize: 10, color: t.textFaint }}>{n.date} · {n.time}</div>
                            </div>
                        </div>
                    ))}
                </div>

                {/* Footer */}
                <div style={{ padding: "14px 20px", borderTop: `1.5px solid ${t.border}` }}>
                    <button
                        onClick={() => { onGoTracking(); onClose(); }}
                        style={{
                            width: "100%", padding: "11px", borderRadius: 12,
                            background: t.primaryGlow2, border: `1.5px solid ${t.primary}40`,
                            color: t.primary, fontSize: 13, fontWeight: 700, cursor: "pointer",
                            display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
                        }}
                    >
                        <Ic n="clock" s={14} c={t.primary} /> View all in Tracking
                    </button>
                </div>
            </div>
            <style>{`@keyframes slideInRight { from { transform: translateX(100%); } to { transform: translateX(0); } }`}</style>
        </div>
    );
};

/* ─── Inner Dashboard ───────────────────────────────────────── */
const DashboardInner = ({ go, isDark, toggleTheme, initialTab = "overview" }) => {
    const t = isDark ? DARK : LIGHT;
    const { unreadCount } = useCase();
    const [tab, setTab] = useState(initialTab);
    const [headerActions, setHeaderActions] = useState(null);
    const [drawerOpen, setDrawerOpen] = useState(false);
    const [isCollapsed, setIsCollapsed] = useState(false);

    const liveDate = getLiveDate();

    const modules = {
        overview: <ModOverview />,
        profile: <ModProfile />,
        intake: <ModIntake />,
        chatbot: <ModChatbot />,
        lawyers: <ModLawyers />,
        agreements: <ModAgreements />,
        documents: <ModDocuments />,
        tracking: <ModTracking isDark={isDark} />,
    };

    const noTopbar = tab === "agreements" || tab === "chatbot" || tab === "tracking";
    const noPadding = tab === "agreements" || tab === "chatbot";

    return (
        <ThemeCtx.Provider value={t}>
            <HeaderActionsCtx.Provider value={{ setHeaderActions }}>

                <NotifDrawer
                    open={drawerOpen}
                    onClose={() => setDrawerOpen(false)}
                    onGoTracking={() => setTab("tracking")}
                    t={t}
                />

                <div style={{
                    display: "flex", height: "100vh", overflow: "hidden",
                    background: t.bg,
                    transition: "background 0.5s cubic-bezier(0.4,0,0.2,1)",
                }}>

                    {/* ══════════════ SIDEBAR ══════════════ */}
                    <div style={{
                        width: isCollapsed ? 70 : 238,
                        minWidth: isCollapsed ? 70 : 238,
                        background: t.surface,
                        borderRight: `1.5px solid ${t.border}`,
                        display: "flex", flexDirection: "column",
                        transition: "all 0.4s cubic-bezier(0.4,0,0.2,1)",
                        boxShadow: isDark ? "none" : "3px 0 16px rgba(26,46,53,0.08)",
                        zIndex: 10,
                        overflow: "hidden",
                    }}>

                        {/* ══ LOGO AREA ══ */}
                        <div style={{
                            padding: isCollapsed ? "10px 0" : "10px 14px",
                            borderBottom: `1.5px solid ${t.border}`,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: isCollapsed ? "center" : "flex-start",
                            gap: 8,
                            minHeight: 62,
                            height: 62,
                        }}>
                            {/* Logo image */}
                            <img
                                src="./logo.png"
                                alt="Attorney.AI"
                                onClick={() => isCollapsed && setTab("overview")}
                                style={{
                                    width: 48,
                                    height: 49,
                                    objectFit: "contain",
                                    flexShrink: 0,
                                    cursor: isCollapsed ? "pointer" : "default",
                                    borderRadius: 10,
                                    display: "block",
                                }}
                            />

                            {/* Brand text — hidden when collapsed */}
                            {!isCollapsed && (
                                <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.25 }}>
                                    <span style={{
                                        fontFamily: "'Playfair Display', serif",
                                        fontSize: 23,
                                        fontWeight: 900,
                                        color: t.text,
                                        letterSpacing: "-0.6px",
                                        whiteSpace: "nowrap",
                                        lineHeight: 1,
                                    }}>
                                        Attorney<span style={{ color: t.primary }}>.AI</span>
                                    </span>
                                </div>
                            )}

                            {/* Collapse toggle */}
                            <button
                                onClick={() => setIsCollapsed(!isCollapsed)}
                                style={{
                                    marginLeft: isCollapsed ? 0 : "auto",
                                    width: 30, height: 30,
                                    background: "transparent", border: "none",
                                    cursor: "pointer",
                                    display: "flex", alignItems: "center", justifyContent: "center",
                                    color: t.textMuted, borderRadius: 8, flexShrink: 0,
                                    transition: "background 0.2s, color 0.2s",
                                }}
                                onMouseEnter={e => {
                                    e.currentTarget.style.background = t.inputBg;
                                    e.currentTarget.style.color = t.primary;
                                }}
                                onMouseLeave={e => {
                                    e.currentTarget.style.background = "transparent";
                                    e.currentTarget.style.color = t.textMuted;
                                }}
                            >
                                <Ic n="menu" s={20} />
                            </button>
                        </div>

                        {/* ══ NAV ITEMS ══ */}
                        <nav className="hide-scrollbar" style={{ flex: 1, overflowY: "auto", padding: "16px 10px" }}>
                            {SIDE_ITEMS.map(item => {
                                const active = tab === item.id;
                                const showDot = item.id === "tracking" && unreadCount > 0 && !active;
                                return (
                                    <button
                                        key={item.id}
                                        onClick={() => setTab(item.id)}
                                        style={{
                                            display: "flex",
                                            alignItems: "center",
                                            gap: isCollapsed ? 0 : 13,
                                            width: "100%",
                                            justifyContent: isCollapsed ? "center" : "flex-start",
                                            padding: isCollapsed ? "15px 0" : "13px 16px",
                                            borderRadius: isCollapsed ? 14 : 16,
                                            border: "none",
                                            background: active ? t.primaryGlow : "transparent",
                                            color: active ? t.primary : t.textDim,
                                            fontSize: 15,
                                            fontWeight: active ? 700 : 500,
                                            cursor: "pointer",
                                            marginBottom: 4,
                                            transition: "all 0.25s cubic-bezier(0.4,0,0.2,1)",
                                            textAlign: "left",
                                            fontFamily: "'Inter', sans-serif",
                                            letterSpacing: "0.1px",
                                            borderLeft: active ? `3px solid ${t.primary}` : "3px solid transparent",
                                            position: "relative",
                                        }}
                                        onMouseEnter={e => {
                                            if (!active) {
                                                e.currentTarget.style.background = t.inputBg;
                                                e.currentTarget.style.color = t.text;
                                            }
                                        }}
                                        onMouseLeave={e => {
                                            if (!active) {
                                                e.currentTarget.style.background = "transparent";
                                                e.currentTarget.style.color = t.textDim;
                                            }
                                        }}
                                    >
                                        <Ic n={item.icon} s={21} c={active ? t.primary : t.textDim} />
                                        {!isCollapsed && item.label}
                                        {!isCollapsed && (
                                            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
                                                {showDot && (
                                                    <span style={{
                                                        fontSize: 10, fontWeight: 800,
                                                        background: t.danger, color: "#fff",
                                                        borderRadius: 10, padding: "1px 6px",
                                                        minWidth: 18, textAlign: "center",
                                                    }}>
                                                        {unreadCount}
                                                    </span>
                                                )}
                                                {active && (
                                                    <div style={{
                                                        width: 7, height: 7, borderRadius: "50%",
                                                        background: t.primary,
                                                        boxShadow: `0 0 8px ${t.primaryGlow}`,
                                                    }} />
                                                )}
                                            </div>
                                        )}
                                        {isCollapsed && showDot && (
                                            <span style={{
                                                position: "absolute", top: 8, right: 8,
                                                width: 8, height: 8, borderRadius: "50%",
                                                background: t.danger,
                                            }} />
                                        )}
                                    </button>
                                );
                            })}
                        </nav>

                        {/* ══ USER + THEME TOGGLE ══ */}
                        <div style={{
                            padding: isCollapsed ? "14px 0" : "10px 12px",
                            borderTop: `1.5px solid ${t.border}`,
                            display: "flex", flexDirection: "column", alignItems: "center",
                        }}>
                            <div style={{
                                display: "flex",
                                alignItems: "center",
                                gap: isCollapsed ? 0 : 10,
                                marginBottom: isCollapsed ? 0 : 8,
                                justifyContent: isCollapsed ? "center" : "flex-start",
                                width: "100%",
                            }}>
                                <div
                                    onClick={() => isCollapsed && setTab("profile")}
                                    style={{
                                        width: 34, height: 34, borderRadius: "50%",
                                        background: t.grad1,
                                        display: "flex", alignItems: "center", justifyContent: "center",
                                        fontSize: 13, fontWeight: 800,
                                        color: t.mode === "dark" ? "#1A2E35" : "#FFFFFF",
                                        flexShrink: 0,
                                        boxShadow: `0 4px 12px ${t.primaryGlow}`,
                                        cursor: isCollapsed ? "pointer" : "default",
                                    }}
                                >MU</div>

                                {!isCollapsed && (
                                    <div>
                                        <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>M. Usama</div>
                                        <div style={{ fontSize: 12, color: t.textMuted }}>Client</div>
                                    </div>
                                )}
                            </div>

                            {!isCollapsed && (
                                <div style={{ display: "flex", gap: 6, width: "100%" }}>
                                    <ThemeToggle isDark={isDark} toggle={toggleTheme} />
                                    <button
                                        onClick={() => go("landing")}
                                        style={{
                                            flex: 1, background: t.inputBg,
                                            border: `1.5px solid ${t.border}`,
                                            color: t.textDim, borderRadius: 50,
                                            display: "flex", alignItems: "center", gap: 6,
                                            justifyContent: "center", fontSize: 13,
                                            fontFamily: "'Inter', sans-serif",
                                            cursor: "pointer", transition: "all 0.25s",
                                            padding: "9px 12px",
                                        }}
                                        onMouseEnter={e => {
                                            e.currentTarget.style.borderColor = t.primary;
                                            e.currentTarget.style.color = t.primary;
                                        }}
                                        onMouseLeave={e => {
                                            e.currentTarget.style.borderColor = t.border;
                                            e.currentTarget.style.color = t.textDim;
                                        }}
                                    >
                                        <Ic n="logout" s={14} /> Sign Out
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>
                    {/* ══════════════ END SIDEBAR ══════════════ */}

                    {/* ══ MAIN CONTENT ══ */}
                    <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>

                        {!noTopbar && (
                            <div style={{
                                padding: "0 36px",
                                height: 62,
                                minHeight: 62,
                                borderBottom: `1.5px solid ${t.border}`,
                                display: "flex", alignItems: "center", justifyContent: "space-between",
                                background: t.surface,
                                position: "sticky", top: 0, zIndex: 20,
                                transition: "all 0.4s",
                                boxShadow: isDark ? "none" : "0 2px 12px rgba(26,46,53,0.08)",
                            }}>
                                <div>
                                    <h1 style={{
                                        fontSize: 22,
                                        fontWeight: 700,
                                        color: t.text,
                                        letterSpacing: "-0.5px",
                                        fontFamily: "'Playfair Display', serif",
                                    }}>
                                        {SIDE_ITEMS.find(i => i.id === tab)?.label}
                                    </h1>
                                    <p style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>{liveDate}</p>
                                </div>

                                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                                    {headerActions}

                                    {/* ══ POLISHED NOTIFICATION BELL ══ */}
                                    <button
                                        onClick={() => setDrawerOpen(v => !v)}
                                        style={{
                                            background: drawerOpen ? t.primaryGlow : "transparent",
                                            border: `1.5px solid ${drawerOpen ? t.primary : "transparent"}`,
                                            color: drawerOpen ? t.primary : t.textMuted,
                                            borderRadius: 12,
                                            padding: "8px 10px",
                                            cursor: "pointer",
                                            position: "relative",
                                            transition: "all 0.25s cubic-bezier(0.4,0,0.2,1)",
                                            boxShadow: drawerOpen ? `0 4px 20px ${t.primaryGlow}` : "none",
                                            display: "flex",
                                            alignItems: "center",
                                            justifyContent: "center",
                                        }}
                                        onMouseEnter={e => {
                                            e.currentTarget.style.borderColor = t.primary;
                                            e.currentTarget.style.background = t.primaryGlow;
                                            e.currentTarget.style.transform = "translateY(-1px)";
                                        }}
                                        onMouseLeave={e => {
                                            if (!drawerOpen) {
                                                e.currentTarget.style.borderColor = "transparent";
                                                e.currentTarget.style.background = "transparent";
                                            }
                                            e.currentTarget.style.transform = "translateY(0)";
                                        }}
                                    >
                                        <Ic n="bell" s={22} c={drawerOpen ? t.primary : t.textMuted} />
                                        {unreadCount > 0 && (
                                            <span style={{
                                                position: "absolute", top: 2, right: 2,
                                                minWidth: 20, height: 20, borderRadius: "50%",
                                                background: `linear-gradient(135deg, ${t.danger} 0%, #ff4757 100%)`,
                                                color: "#fff",
                                                fontSize: 11, fontWeight: 700, lineHeight: "20px",
                                                textAlign: "center", padding: "0 5px",
                                                border: `2px solid ${t.surface}`,
                                                boxShadow: `0 3px 10px ${t.danger}80, 0 0 0 1px ${t.danger}30`,
                                                animation: "pulse 2s infinite",
                                            }}>
                                                {unreadCount > 9 ? "9+" : unreadCount}
                                            </span>
                                        )}
                                    </button>
                                </div>
                            </div>
                        )}

                        <div
                            style={{
                                flex: 1,
                                padding: noPadding ? 0 : 32,
                                overflow: noPadding ? "hidden" : "auto",
                                display: "flex", flexDirection: "column",
                            }}
                            className="aFadeUp"
                            key={tab}
                        >
                            {modules[tab]}
                        </div>
                    </div>

                </div>
            </HeaderActionsCtx.Provider>
        </ThemeCtx.Provider>
    );
};

/* ─── Public export ─────────────────────────────────────────── */
const Dashboard = ({ go, isDark, toggleTheme, initialTab = "overview" }) => (
    <CaseProvider>
        <DashboardInner go={go} isDark={isDark} toggleTheme={toggleTheme} initialTab={initialTab} />
    </CaseProvider>
);

export default Dashboard;