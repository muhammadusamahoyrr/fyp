'use client';
// Lawyer layout — paste your code here
import { useState } from "react";
import { useTheme } from "./theme.js";
import { useCase } from "./theme.js";
import { useNotif } from "./theme.js";
import { Icon, I } from "./icons.jsx";
import { casesData } from "./data.js";
import logo from "./logo.png";

// ============================================================
// CASE DRAWER — slides in from right, shows full case detail
// ============================================================
// ============================================================
// NOTIFICATION PANEL
// ============================================================
function NotificationPanel({ onClose, notifs, clearNotif, clearAll }) {
    const { t } = useTheme();
    const iconMap = { hearing: I.gavel, message: I.chat, document: I.fileText, appointment: I.calendar, upload: I.upload };
    const colorMap = { hearing: t.info, message: t.primary, document: t.warn, appointment: t.success, upload: t.primary };
    return (
        <>
            <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 198 }} />
            <div style={{
                position: "fixed", top: 58, right: 14, width: 340, background: t.surface, borderRadius: 14,
                border: `1px solid ${t.border}`, zIndex: 199, boxShadow: "0 8px 40px rgba(0,0,0,0.35)",
                overflow: "hidden", animation: "fadeIn .15s ease"
            }}>
                <div style={{ padding: "14px 16px 10px", borderBottom: `1px solid ${t.border}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Notifications</div>
                    {notifs.length > 0 && <button onClick={clearAll} style={{ fontSize: 11, color: t.primary, background: "none", border: "none", cursor: "pointer" }}>Clear all</button>}
                </div>
                <div style={{ maxHeight: 400, overflowY: "auto" }}>
                    {notifs.length === 0 ? (
                        <div style={{ padding: "32px 16px", textAlign: "center", color: t.textFaint, fontSize: 13 }}>
                            <Icon d={I.bell} size={24} style={{ marginBottom: 8, opacity: .3, display: "block", margin: "0 auto 10px" }} />
                            All caught up!
                        </div>
                    ) : notifs.map(n => (
                        <div key={n.id} style={{
                            display: "flex", gap: 11, padding: "11px 16px", borderBottom: `1px solid ${t.border}`,
                            background: n.unread ? t.primaryGlow2 : "transparent", transition: "background .15s", cursor: "pointer"
                        }}
                            onClick={() => clearNotif(n.id)}>
                            <div style={{
                                width: 34, height: 34, borderRadius: 10, flexShrink: 0,
                                background: `${colorMap[n.type] || t.primary}18`,
                                display: "flex", alignItems: "center", justifyContent: "center"
                            }}>
                                <Icon d={iconMap[n.type] || I.bell} size={14} style={{ color: colorMap[n.type] || t.primary }} />
                            </div>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 13, fontWeight: n.unread ? 700 : 500, color: t.text, lineHeight: 1.4 }}>{n.title}</div>
                                <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>{n.body}</div>
                                <div style={{ fontSize: 10, color: t.textFaint, marginTop: 3 }}>{n.time}</div>
                            </div>
                            {n.unread && <div style={{ width: 7, height: 7, borderRadius: "50%", background: t.primary, flexShrink: 0, marginTop: 4 }} />}
                        </div>
                    ))}
                </div>
            </div>
        </>
    );
}

// ============================================================
// ACTIVE CASE BANNER — thin bar shown at top of all pages when a case is active
// ============================================================
function ActiveCaseBanner({ caseId, onClear }) {
    const { t } = useTheme();
    const { setOpenCaseId, setPage } = useCase();
    const c = casesData.find(x => x.id === caseId);
    if (!c) return null;
    const openWorkspace = () => { setOpenCaseId(caseId); setPage("cases"); };
    return (
        <div style={{
            height: 36, background: `${t.primary}14`, borderBottom: `1px solid ${t.primary}30`,
            display: "flex", alignItems: "center", padding: "0 20px", gap: 10, flexShrink: 0
        }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: t.primary, flexShrink: 0 }} />
            <span style={{ fontSize: 11, color: t.primary, fontWeight: 600 }}>Active Case:</span>
            <span className="mono" style={{ fontSize: 11, color: t.primary, fontWeight: 700 }}>{c.id}</span>
            <span style={{ fontSize: 11, color: t.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{c.title}</span>
            <button onClick={openWorkspace} style={{ fontSize: 11, color: t.primary, background: "none", border: `1px solid ${t.primary}50`, borderRadius: 6, padding: "3px 10px", cursor: "pointer", flexShrink: 0 }}>Open Workspace</button>
            <button onClick={onClear} style={{ background: "none", border: "none", color: t.textMuted, cursor: "pointer", display: "flex", flexShrink: 0 }}><Icon d={I.x} size={11} /></button>
        </div>
    );
}

// ============================================================
// SIDEBAR
// ============================================================

const NAV_SECTIONS = [
    {
        id: "main",
        label: "",
        items: [
            { id: "dashboard", label: "Dashboard", icon: "dashboard" },
            { id: "cases", label: "Cases", icon: "cases" },
            { id: "clients", label: "Clients", icon: "clients" },
        ],
    },
    {
        id: "work",
        label: "",
        items: [
            { id: "documents", label: "Documents", icon: "documents" },
            { id: "appointments", label: "Appointments", icon: "calendar" },
        ],
    },
    {
        id: "communication",
        label: "",
        items: [
            { id: "communications", label: "Messages", icon: "chat", badge: 2 },
        ],
    },
    {
        id: "ai",
        label: "",
        items: [
            { id: "ai-legal", label: "AI Assistant", icon: "ai" },
            { id: "drafts", label: "Draft Generator", icon: "wand" },
        ],
    },
    {
        id: "settings-section",
        label: "",
        items: [
            { id: "settings", label: "Settings", icon: "settings" },
        ],
    },
];

const PAGE_REDIRECT = {
    tasks: "documents",
    notifications: "communications",
    research: "ai-legal",
    drafts: "doc-automation",
    reports: "settings",
};

function NavItem({ item, page, setPage, collapsed, t, unreadMsgs }) {
    const targetPage = PAGE_REDIRECT[item.id] || item.id;
    const active = page === item.id || (PAGE_REDIRECT[item.id] && page === PAGE_REDIRECT[item.id]);
    const [hov, setHov] = useState(false);
    const badgeCount = item.id === "communications" ? unreadMsgs : 0;

    return (
        <button
            onClick={() => setPage(targetPage)}
            onMouseEnter={() => setHov(true)}
            onMouseLeave={() => setHov(false)}
            title={collapsed ? item.label : undefined}
            style={{
                display: "flex",
                alignItems: "center",
                gap: collapsed ? 0 : 14,
                width: "100%",
                height: 48,
                padding: collapsed ? "12px 0" : "12px 16px",
                justifyContent: collapsed ? "center" : "flex-start",
                textAlign: "left",
                fontSize: 14,
                fontWeight: 500,
                borderRadius: 8,
                border: "none",
                cursor: "pointer",
                background: active ? t.primaryGlow : hov ? t.primaryGlow2 : "transparent",
                transition: "background .15s ease",
                position: "relative",
            }}
        >
            {active && (
                <div style={{
                    position: "absolute", left: 0, top: "50%",
                    transform: "translateY(-50%)",
                    width: 3, height: 26, borderRadius: "0 3px 3px 0",
                    background: t.primary,
                }} />
            )}
            <div style={{
                width: 38, height: 38, borderRadius: 9, flexShrink: 0,
                display: "flex", alignItems: "center", justifyContent: "center",
                background: active ? `${t.primary}20` : "transparent",
                position: "relative",
            }}>
                <Icon d={I[item.icon] || I.fileText} size={26}
                    style={{ color: active ? t.primary : hov ? t.text : t.textMuted }} />
                {collapsed && badgeCount > 0 && (
                    <div style={{
                        position: "absolute", top: 2, right: 2,
                        width: 8, height: 8, borderRadius: "50%",
                        background: t.danger, border: `2px solid ${t.surface}`,
                    }} />
                )}
            </div>
            {!collapsed && (
                <>
                    <span style={{
                        flex: 1, fontSize: 14.5, fontWeight: active ? 640 : 540,
                        color: active ? t.primary : hov ? t.text : t.textDim,
                        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                        letterSpacing: "0.01em", lineHeight: 1.3,
                    }}>{item.label}</span>
                    {badgeCount > 0 && (
                        <span style={{
                            fontSize: 10, fontWeight: 700, color: "#fff",
                            background: t.danger, borderRadius: 20,
                            padding: "2px 6px", flexShrink: 0,
                        }}>{badgeCount}</span>
                    )}
                </>
            )}
        </button>
    );
}

function SectionLabel({ label, collapsed, t }) {
    return collapsed
        ? <div style={{ height: 1, background: t.border, margin: "6px 8px" }} />
        : null;
}

function Sidebar({ page, setPage, collapsed, setCollapsed, unreadMsgs }) {
    const { t, toggle } = useTheme();

    return (
        <div data-sidebar style={{
            width: collapsed ? 56 : 240,
            minWidth: collapsed ? 56 : 240,
            height: "100vh", background: t.surface,
            borderRight: `1px solid ${t.border}`,
            display: "flex", flexDirection: "column",
            transition: "width .25s ease, min-width .25s ease",
            overflow: "hidden", zIndex: 10, flexShrink: 0,
            position: "sticky", top: 0,
        }}>

            {/* ── Brand ── */}
            <div style={{
                padding: collapsed ? "14px 0" : "14px 16px",
                display: "flex", alignItems: "center", gap: 10,
                borderBottom: `1px solid ${t.border}`, flexShrink: 0,
                justifyContent: collapsed ? "center" : "flex-start",
            }}>
                {collapsed ? (
                    <button
                        onClick={() => setCollapsed(false)}
                        style={{
                            background: "none", border: "none",
                            cursor: "pointer", padding: 0,
                        }}
                        title="Expand sidebar"
                    >
                        <img
                            src={logo}
                            alt="AttorneyAI"
                            style={{ width: 34, height: 34, objectFit: "contain", display: "block" }}
                        />
                    </button>
                ) : (
                    <>
                        <img
                            src={logo}
                            alt="AttorneyAI"
                            style={{ width: 34, height: 34, objectFit: "contain", display: "block", flexShrink: 0 }}
                        />
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <div className="serif" style={{
                                fontSize: 17, fontWeight: 800,
                                letterSpacing: "0.04em", textTransform: "uppercase",
                            }}>Attorney<span style={{ color: t.primary }}>AI</span></div>
                            <div style={{ fontSize: 12, color: t.textFaint, marginTop: 3 }}>
                                Legal Practice Suite
                            </div>
                        </div>
                        <button
                            onClick={() => setCollapsed(true)}
                            style={{
                                width: 26, height: 26, borderRadius: 7, border: "none",
                                background: "transparent", color: t.textFaint,
                                cursor: "pointer", display: "flex", alignItems: "center",
                                justifyContent: "center", flexShrink: 0,
                            }}
                            onMouseEnter={e => e.currentTarget.style.color = t.textMuted}
                            onMouseLeave={e => e.currentTarget.style.color = t.textFaint}>
                            <Icon d={I.chevronLeft} size={14} />
                        </button>
                    </>
                )}
            </div>

            {/* Expand tab when collapsed */}
            {collapsed && (
                <button
                    onClick={() => setCollapsed(false)}
                    style={{
                        position: "absolute", left: 56, top: 16, zIndex: 20,
                        width: 16, height: 24, borderRadius: "0 6px 6px 0",
                        border: `1px solid ${t.border}`, borderLeft: "none",
                        background: t.surface, color: t.textFaint, cursor: "pointer",
                        display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                    <Icon d={I.chevronRight} size={10} />
                </button>
            )}

            {/* ── Nav ── */}
            <div style={{ flex: 1, padding: "6px 6px 0" }}>
                {NAV_SECTIONS.map(section => (
                    <div key={section.id}>
                        <SectionLabel label={section.label} collapsed={collapsed} t={t} />
                        {section.items.map(item => (
                            <NavItem key={item.id} item={item} page={page} setPage={setPage} collapsed={collapsed} t={t} unreadMsgs={unreadMsgs} />
                        ))}
                    </div>
                ))}
            </div>

            {/* ── Profile footer ── */}
            <div style={{ borderTop: `1px solid ${t.border}`, padding: "8px 6px", flexShrink: 0 }}>
                {!collapsed ? (
                    <>
                        <div
                            onClick={() => setPage("profile")}
                            style={{
                                display: "flex", alignItems: "center", gap: 10,
                                padding: "9px 10px", borderRadius: 10, cursor: "pointer",
                                border: `1px solid ${t.border}`, background: t.card,
                                transition: "border-color .15s", marginBottom: 6,
                            }}
                            onMouseEnter={e => e.currentTarget.style.borderColor = t.primary}
                            onMouseLeave={e => e.currentTarget.style.borderColor = t.border}>
                            <div style={{
                                width: 32, height: 32, borderRadius: "50%", background: t.grad1,
                                display: "flex", alignItems: "center", justifyContent: "center",
                                fontSize: 12, fontWeight: 700,
                                color: t.mode === "dark" ? "#111B1F" : "#fff", flexShrink: 0,
                            }}>JD</div>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 14, fontWeight: 650, color: t.text, lineHeight: 1.3 }}>John Doe</div>
                                <div style={{ fontSize: 12.5, color: t.textMuted }}>Senior Advocate</div>
                            </div>
                            <button
                                onClick={e => { e.stopPropagation(); toggle(); }}
                                title={t.mode === "dark" ? "Switch to Light Mode" : "Switch to Dark Mode"}
                                style={{
                                    width: 28, height: 28, borderRadius: 7, border: "none",
                                    background: "transparent", color: t.textFaint,
                                    cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
                                    transition: "background .13s, color .13s", flexShrink: 0,
                                }}
                                onMouseEnter={e => { e.currentTarget.style.background = t.primaryGlow2; e.currentTarget.style.color = t.text; }}
                                onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = t.textFaint; }}>
                                <Icon d={t.mode === "dark" ? I.sun : I.moon} size={15} />
                            </button>
                        </div>
                    </>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
                        <button
                            onClick={() => setPage("profile")}
                            style={{
                                width: 36, height: 36, borderRadius: "50%", background: t.grad1,
                                border: "none", cursor: "pointer", display: "flex",
                                alignItems: "center", justifyContent: "center",
                                fontSize: 12, fontWeight: 700,
                                color: t.mode === "dark" ? "#111B1F" : "#fff",
                            }}>JD</button>
                        <button
                            onClick={toggle}
                            title={t.mode === "dark" ? "Switch to Light Mode" : "Switch to Dark Mode"}
                            style={{
                                width: 32, height: 32, borderRadius: 8, border: "none",
                                background: "transparent", color: t.textFaint,
                                cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
                                transition: "background .15s, color .15s",
                            }}
                            onMouseEnter={e => { e.currentTarget.style.background = t.primaryGlow2; e.currentTarget.style.color = t.text; }}
                            onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = t.textFaint; }}>
                            <Icon d={t.mode === "dark" ? I.sun : I.moon} size={17} />
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}

function Topbar({ page, collapsed, setCollapsed, toggleTheme, children }) {
    const { t } = useTheme();
    const { notifs, clearNotif, clearAll } = useNotif();
    const [showNotifs, setShowNotifs] = useState(false);
    const [searchVal, setSearchVal] = useState("");
    const unreadCount = notifs.filter(n => n.unread).length;
    const labels = {
        dashboard: "Dashboard", cases: "Cases", documents: "Documents",
        appointments: "Appointments", clients: "Clients", "ai-legal": "AI Assistant",
        "doc-automation": "Document Automation", upload: "Upload Documents",
        communications: "Messages", profile: "Lawyer Profile", settings: "Settings",
    };

    const isComm = page === "communications";
    const hideSearch = isComm || page === "documents";

    return (
        <div style={{
            height: 56, background: t.navBg, borderBottom: `1px solid ${t.border}`,
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "0 20px", backdropFilter: "blur(12px)", flexShrink: 0, gap: 14,
        }}>
            {/* Left — hamburger + page title */}
            <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
                <button
                    onClick={() => setCollapsed(!collapsed)}
                    style={{
                        width: 32, height: 32, borderRadius: 8, border: "none",
                        background: "transparent", color: t.textMuted,
                        cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                    <Icon d={I.menu} size={16} />
                </button>
                <div className="serif" style={{ fontSize: 18, fontWeight: 700, color: t.text, whiteSpace: "nowrap" }}>
                    {labels[page] || page}
                </div>
            </div>

            {/* Centre — Global search bar */}
            {!hideSearch && (
                <div style={{ flex: 1, maxWidth: 480, position: "relative", display: "flex", alignItems: "center" }}>
                    <Icon d={I.search} size={15} style={{ position: "absolute", left: 13, color: t.textFaint, pointerEvents: "none" }} />
                    <input
                        value={searchVal}
                        onChange={e => setSearchVal(e.target.value)}
                        placeholder="Search cases, clients, documents…"
                        style={{
                            width: "100%", height: 38,
                            border: `1px solid ${t.border}`, borderRadius: 10,
                            background: t.inputBg, color: t.text,
                            fontSize: 13, padding: "0 14px 0 40px",
                            outline: "none", boxSizing: "border-box",
                            transition: "border-color .15s",
                        }}
                        onFocus={e => e.target.style.borderColor = t.primary}
                        onBlur={e => e.target.style.borderColor = t.border}
                    />
                    {searchVal && (
                        <button
                            onClick={() => setSearchVal("")}
                            style={{
                                position: "absolute", right: 10, width: 18, height: 18,
                                borderRadius: "50%", border: "none", background: t.textFaint,
                                color: t.surface, cursor: "pointer", fontSize: 10,
                                display: "flex", alignItems: "center", justifyContent: "center",
                            }}>
                            <Icon d={I.x} size={10} />
                        </button>
                    )}
                </div>
            )}

            {/* Comms search */}
            {isComm && (
                <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 12, maxWidth: 600 }}>
                    <div style={{ flex: 1, position: "relative" }}>
                        <Icon d={I.search} size={13} style={{
                            position: "absolute", left: 11, top: "50%",
                            transform: "translateY(-50%)", color: t.textMuted, pointerEvents: "none",
                        }} />
                        <input
                            placeholder="Search conversations…"
                            style={{
                                width: "100%", height: 36, border: `1px solid ${t.border}`,
                                borderRadius: 9, background: t.inputBg, color: t.text,
                                fontSize: 13, padding: "0 12px 0 34px",
                                outline: "none", boxSizing: "border-box",
                            }} />
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 0, flexShrink: 0 }}>
                        <span style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, marginRight: 6 }}>Filter:</span>
                        {["All", "Unanswered", "Answered", "Urgent"].map((f, i, arr) => (
                            <span key={f} style={{ display: "flex", alignItems: "center" }}>
                                <button style={{
                                    background: "none", border: "none", cursor: "pointer",
                                    fontSize: 12, fontWeight: i === 0 ? 700 : 400,
                                    color: i === 0 ? t.primary : t.textMuted, padding: "2px 5px",
                                }}>{f}</button>
                                {i < arr.length - 1 && <span style={{ color: t.border }}>|</span>}
                            </span>
                        ))}
                    </div>
                </div>
            )}

            {/* Right */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                {children}
                <button
                    onClick={toggleTheme}
                    style={{
                        width: 34, height: 34, borderRadius: 9, border: `1px solid ${t.border}`,
                        background: "transparent", color: t.textMuted, cursor: "pointer",
                        display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                    <Icon d={t.mode === "dark" ? I.sun : I.moon} size={15} />
                </button>
                <button
                    onClick={() => setShowNotifs(v => !v)}
                    style={{
                        width: 34, height: 34, borderRadius: 9, border: `1px solid ${t.border}`,
                        background: showNotifs ? t.primaryGlow2 : "transparent",
                        color: t.textMuted, cursor: "pointer",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        position: "relative",
                    }}>
                    <Icon d={I.bell} size={15} />
                    {unreadCount > 0 && (
                        <span style={{
                            position: "absolute", top: -4, right: -4,
                            width: 16, height: 16, borderRadius: "50%",
                            background: t.danger, border: `2px solid ${t.surface}`,
                            fontSize: 9, fontWeight: 700, color: "#fff",
                            display: "flex", alignItems: "center", justifyContent: "center",
                        }}>{unreadCount}</span>
                    )}
                </button>
                <div style={{
                    width: 34, height: 34, borderRadius: "50%", background: t.grad1,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: 12, fontWeight: 700,
                    color: t.mode === "dark" ? "#111B1F" : "#fff", cursor: "pointer",
                }}>JD</div>
            </div>
            {showNotifs && (
                <NotificationPanel
                    onClose={() => setShowNotifs(false)}
                    notifs={notifs}
                    clearNotif={clearNotif}
                    clearAll={clearAll}
                />
            )}
        </div>
    );
}

export { NotificationPanel, ActiveCaseBanner, Sidebar, Topbar };