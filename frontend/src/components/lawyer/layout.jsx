'use client';
// Lawyer layout — paste your code here
import { useEffect, useState } from "react";
import { useTheme } from "./theme.js";
import { useCase } from "./theme.js";
import { useNotif } from "./theme.js";
import { Icon, I } from "./icons.jsx";
import { notificationCategory, lawyerNotificationTarget } from "@/lib/notificationTarget.js";
import { useAuth } from "@/context/AuthContext.jsx";
const logo = "/logo.png";

// ============================================================
// CASE DRAWER — slides in from right, shows full case detail
// ============================================================
// ============================================================
// NOTIFICATION PANEL
// ============================================================
function NotificationPanel({ onClose, notifs, clearNotif, clearAll, openNotif, anchorStyle }) {
    const { t } = useTheme();
    // Keyed on the CATEGORY of the server's type (see notificationTarget.js).
    const iconMap = { hearing: I.gavel, message: I.chat, document: I.fileText, appointment: I.calendar, case: I.cases || I.gavel, payment: I.fileText, dispute: I.gavel };
    const colorMap = { hearing: t.info, message: t.primary, document: t.warn, appointment: t.success, case: t.info, payment: t.success, dispute: t.info };
    const kind = (n) => notificationCategory(n.type);
    // Every notification about something opens it: its page, and its case.
    const handleClick = (n) => {
        const opened = openNotif ? openNotif(n) : (clearNotif(n.id), false);
        if (opened) onClose?.();
    };
    const opens = (n) => !!(lawyerNotificationTarget(n.type, n.payload) || n.route);
    return (
        <>
            <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 198 }} />
            <div style={{
                position: "fixed", top: 58, right: 14, width: 340, background: t.surface, borderRadius: 14,
                border: `1px solid ${t.border}`, zIndex: 199, boxShadow: "0 8px 40px rgba(0,0,0,0.35)",
                overflow: "hidden", animation: "fadeIn .15s ease",
                ...anchorStyle,
            }}>
                <div style={{ padding: "14px 16px 10px", borderBottom: `1px solid ${t.border}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Notifications</div>
                    {notifs.length > 0 && <button onClick={clearAll} style={{ fontSize: 11, color: t.primary, background: "none", border: "none", cursor: "pointer" }}>Clear all</button>}
                </div>
                <div data-lenis-prevent style={{ maxHeight: 400, overflowY: "auto" }}>
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
                            onClick={() => handleClick(n)}>
                            <div style={{
                                width: 34, height: 34, borderRadius: 10, flexShrink: 0,
                                background: `${colorMap[kind(n)] || t.primary}18`,
                                display: "flex", alignItems: "center", justifyContent: "center"
                            }}>
                                <Icon d={iconMap[kind(n)] || I.bell} size={14} style={{ color: colorMap[kind(n)] || t.primary }} />
                            </div>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 13, fontWeight: n.unread ? 700 : 500, color: t.text, lineHeight: 1.4 }}>{n.title}</div>
                                <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>{n.body}</div>
                                <div style={{ fontSize: 10, color: t.textFaint, marginTop: 3, display: "flex", alignItems: "center", gap: 5 }}>
                                    {n.time}
                                    {opens(n) && <span style={{ color: t.primary, fontWeight: 600 }}>· Open →</span>}
                                </div>
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
    if (!caseId) return null;
    const openWorkspace = () => { setOpenCaseId(caseId); setPage("cases"); };
    return (
        <div style={{
            height: 36, background: `${t.primary}14`, borderBottom: `1px solid ${t.primary}30`,
            display: "flex", alignItems: "center", padding: "0 20px", gap: 10, flexShrink: 0
        }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: t.primary, flexShrink: 0 }} />
            <span style={{ fontSize: 11, color: t.primary, fontWeight: 600 }}>Active Case:</span>
            <span className="mono" style={{ fontSize: 11, color: t.primary, fontWeight: 700 }}>{caseId}</span>
            <button onClick={openWorkspace} style={{ fontSize: 11, color: t.primary, background: "none", border: `1px solid ${t.primary}50`, borderRadius: 6, padding: "3px 10px", cursor: "pointer", flexShrink: 0 }}>Open Workspace</button>
            <button onClick={onClear} style={{ background: "none", border: "none", color: t.textMuted, cursor: "pointer", display: "flex", flexShrink: 0 }}><Icon d={I.x} size={11} /></button>
        </div>
    );
}

// ============================================================
// SIDEBAR
// ============================================================

// Icons the shared set does not have.
const NAV_ICONS = {
    library: ["M3 21h18", "M4 10h16", "M12 3 3 8h18z", "M6 10v8", "M10 10v8", "M14 10v8", "M18 10v8"],
    briefcase: ["M4 7h16a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1z", "M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2", "M3 13h18"],
    pages: ["M15 3H8a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V7z", "M15 3v4h4", "M3 8v12a2 2 0 0 0 2 2h9"],
    review: ["M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4", "M14 3v5h5", "M15.5 18.5a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M17.6 17.6 20 20"],
    calc: ["M6 3h12a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z", "M8 7h8", "M8 12h.01", "M12 12h.01", "M16 12h.01", "M8 16h.01", "M12 16h.01", "M16 16h.01"],
    scale: ["M12 3v18", "M7 21h10", "M5 7h14", "M5 7l-3 6a3 3 0 0 0 6 0z", "M19 7l-3 6a3 3 0 0 0 6 0z"],
};
const navIcon = (name) => NAV_ICONS[name] || I[name] || I.fileText;

/* The lawyer's navigation (2026-10-09): two single destinations, then three
   groups that open and close. Grouped by what the lawyer is doing — finding
   law, working on documents, running the practice — not by which module
   built the page. Only pages that exist are listed. */
const NAV_SECTIONS = [
    { id: "dashboard", label: "Dashboard", icon: "dashboard" },
    { id: "ai-legal", label: "AI Assistant", icon: "chat" },
    {
        id: "research",
        label: "Research",
        icon: "search",
        items: [
            { id: "caselaw", label: "Legal Library", icon: "library" },
            // The bail checker and the calculators (2026-10-09): served by the
            // backend all along, with no lawyer page until now.
            { id: "bail-checker", label: "Bail Checker", icon: "shield" },
            { id: "calculators", label: "Calculators", icon: "calc" },
        ],
    },
    // THE DOCUMENT MODULE in one group: review, drafting, the Vault, the
    // analyzer, review requests and agreements.
    {
        id: "documents-group",
        label: "Documents",
        icon: "pages",
        items: [
            { id: "documents", label: "Document Review", icon: "review" },
            { id: "doc-automation", label: "Legal Drafting", icon: "edit" },
            // The lawyer's own Document Vault: saved drafts, in folders.
            { id: "vault", label: "Vault", icon: "folder" },
            // The Document Analyzer: a lawyer's tool only (2026-10-03).
            { id: "doc-analyzer", label: "Document Analyzer", icon: "search" },
            // Document review requests (Phase 2). Listed only while the server
            // has DOCUMENT_REVIEW_REQUESTS on -- see `reviewQueueOn`.
            { id: "review-queue", label: "Review Queue", icon: "checkSquare", requires: "reviewQueue" },
            { id: "agreements", label: "Agreements", icon: "fileText" },
        ],
    },
    {
        id: "work",
        label: "Work Management",
        icon: "briefcase",
        items: [
            { id: "cases", label: "Cases", icon: "cases" },
            { id: "clients", label: "Clients", icon: "clients" },
            { id: "appointments", label: "Appointments", icon: "calendar" },
            // OUT OF SCOPE, 2026-09-23: "Overseas Disputes" stays hidden with the
            // client's "Property Dispute" module (see client/Dashboard.jsx).
            { id: "causelist", label: "Cause Lists", icon: "scale" },
            { id: "payments", label: "Payments", icon: "dollar" },
        ],
    },
];
const NAV_OPEN_KEY = "attorney:lawyer-nav-open";

const PAGE_REDIRECT = {
    tasks: "documents",
    notifications: "dashboard",
    research: "ai-legal",
    drafts: "doc-automation",
    reports: "settings",
};

function badgeFor(id, { unreadMsgs, unreadAppts, pendingReviews }) {
    // Unread client messages on Cases (where they are read), new booking
    // requests on Appointments, documents waiting on Document Review.
    return id === "cases" ? (unreadMsgs || 0)
        : id === "appointments" ? (unreadAppts || 0)
        : id === "documents" ? (pendingReviews || 0) : 0;
}

function Badge({ id, count }) {
    if (!count) return null;
    const pending = id === "documents";
    return (
        <span className={`ln-badge${pending ? " pending" : ""}`}
            aria-label={pending ? `${count} waiting for review` : undefined}>{count}</span>
    );
}

/* A destination. `sub` = inside a group (smaller, on the group's rail). */
function NavItem({ item, page, setPage, collapsed, counts, sub = false }) {
    const targetPage = PAGE_REDIRECT[item.id] || item.id;
    const active = page === item.id || (PAGE_REDIRECT[item.id] && page === PAGE_REDIRECT[item.id]);
    const count = badgeFor(item.id, counts);
    return (
        <button type="button" onClick={() => setPage(targetPage)}
            className={`ln-item${sub ? " sub" : ""}${active ? " on" : ""}`}
            aria-current={active ? "page" : undefined}
            title={collapsed ? item.label : undefined}>
            <span className="ln-ic">
                <Icon d={navIcon(item.icon)} size={sub ? 17 : 19} />
                {collapsed && count > 0 && <i className="ln-dot" />}
            </span>
            {!collapsed && (
                <>
                    <span className="ln-label">{item.label}</span>
                    <Badge id={item.id} count={count} />
                </>
            )}
        </button>
    );
}

/* A group: a header that opens and closes, its pages on a rail beneath. */
function NavGroup({ group, items, page, setPage, collapsed, counts, open, onToggle, onExpand }) {
    const holdsPage = items.some(i => page === i.id || page === PAGE_REDIRECT[i.id]);
    const total = items.reduce((n, i) => n + badgeFor(i.id, counts), 0);
    if (collapsed) {
        // Narrow bar: the group's icon widens the bar and opens the group.
        return (
            <button type="button" className={`ln-item${holdsPage ? " on" : ""}`} title={group.label}
                onClick={() => onExpand(group.id)}>
                <span className="ln-ic">
                    <Icon d={navIcon(group.icon)} size={19} />
                    {total > 0 && <i className="ln-dot" />}
                </span>
            </button>
        );
    }
    return (
        <div className={`ln-group${open ? " open" : ""}`}>
            <button type="button" className={`ln-item ln-head${holdsPage ? " holds" : ""}`}
                aria-expanded={open} onClick={() => onToggle(group.id)}>
                <span className="ln-ic"><Icon d={navIcon(group.icon)} size={19} /></span>
                <span className="ln-label">{group.label}</span>
                {!open && total > 0 && <span className="ln-badge sum">{total}</span>}
                <span className="ln-chev" aria-hidden="true"><Icon d={I.chevronDown} size={15} /></span>
            </button>
            {open && (
                <div className="ln-rail">
                    {items.map(item => (
                        <NavItem key={item.id} item={item} page={page} setPage={setPage} collapsed={false} counts={counts} sub />
                    ))}
                </div>
            )}
        </div>
    );
}

// Scoped to the sidebar; colours follow the lawyer theme's tokens.
const NAV_CSS = `
[data-sidebar] .ln-item{position:relative;display:flex;align-items:center;gap:11px;width:100%;height:38px;padding:0 10px;margin:2px 0;border:0;border-radius:9px;background:transparent;color:var(--ln-dim);font:inherit;font-size:14.5px;font-weight:550;text-align:left;cursor:pointer;transition:background .15s,color .15s}
[data-sidebar] .ln-item:hover{background:var(--ln-hover);color:var(--ln-ink)}
[data-sidebar] .ln-ic{position:relative;width:24px;height:24px;flex:none;display:grid;place-items:center;color:var(--ln-muted);transition:color .15s}
[data-sidebar] .ln-item:hover .ln-ic{color:var(--ln-ink)}
[data-sidebar] .ln-label{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-sidebar] .ln-item.on:not(.sub){background:linear-gradient(90deg,#1F7A4D,#147C74);color:#fff;font-weight:650;box-shadow:0 8px 18px -12px rgba(20,124,116,.9)}
[data-sidebar] .ln-item.on:not(.sub) .ln-ic{color:#fff}
[data-sidebar] .ln-head.holds{color:var(--ln-ink);font-weight:650}
[data-sidebar] .ln-head.holds .ln-ic{color:var(--ln-accent)}
[data-sidebar] .ln-chev{display:grid;place-items:center;color:var(--ln-muted);transition:transform .2s}
[data-sidebar] .ln-group.open .ln-chev{transform:rotate(180deg)}
[data-sidebar] .ln-rail{position:relative;margin:2px 0 6px 23px;padding-left:10px;animation:lnIn .18s ease-out}
[data-sidebar] .ln-rail::after{content:"";position:absolute;left:0;top:-11px;bottom:0;width:1px;background:var(--ln-line);pointer-events:none}
@keyframes lnIn{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
[data-sidebar] .ln-item.sub{height:33px;padding:0 10px;gap:10px;font-size:13.5px;font-weight:520}
[data-sidebar] .ln-item.sub.on{background:var(--ln-hover);color:var(--ln-accent);font-weight:650}
[data-sidebar] .ln-item.sub.on .ln-ic{color:var(--ln-accent)}
[data-sidebar] .ln-item.sub.on::before{content:"";position:absolute;left:-10.5px;top:8px;bottom:8px;width:2px;border-radius:2px;background:var(--ln-accent);z-index:1}
[data-sidebar] .ln-badge{flex:none;min-width:20px;height:20px;padding:0 6px;display:grid;place-items:center;border-radius:999px;background:var(--ln-danger);color:#fff;font-size:11px;font-weight:700}
[data-sidebar] .ln-badge.pending{background:#F2C35E;color:#1A2B3F}
[data-sidebar] .ln-badge.sum{background:var(--ln-hover);color:var(--ln-ink);border:1px solid var(--ln-line)}
[data-sidebar] .ln-dot{position:absolute;top:-2px;right:-3px;width:8px;height:8px;border-radius:50%;background:var(--ln-danger);border:2px solid var(--ln-bg)}
[data-sidebar][data-collapsed] .ln-item{justify-content:center;padding:0}
[data-sidebar] nav::-webkit-scrollbar{width:4px}
[data-sidebar] nav::-webkit-scrollbar-track{background:transparent}
[data-sidebar] nav::-webkit-scrollbar-thumb{background:rgba(150,215,220,.16);border-radius:4px}
[data-sidebar] nav:hover::-webkit-scrollbar-thumb{background:rgba(150,215,220,.28)}
@supports not selector(::-webkit-scrollbar){[data-sidebar] nav{scrollbar-width:thin;scrollbar-color:rgba(150,215,220,.2) transparent}}
[data-sidebar] .ln-logo{width:38px;height:38px;flex:none;display:grid;place-items:center}
[data-sidebar] .ln-logo img{width:38px;height:38px;object-fit:contain;display:block}
[data-sidebar] .ln-word{flex:1;min-width:0;font-size:18px;font-weight:800;letter-spacing:-.01em;color:var(--ln-ink);white-space:nowrap}
[data-sidebar] .ln-word span{color:var(--ln-accent)}
[data-sidebar] .ln-fold{width:42px;height:42px;flex:none;display:grid;place-items:center;border:0;border-radius:8px;background:transparent;color:var(--ln-muted);cursor:pointer;transition:background .15s,color .15s}
[data-sidebar] .ln-fold .fl,[data-sidebar] .ln-fold .fa{transform-box:fill-box;transform-origin:left center}
@keyframes lnArrow{0%,100%{transform:translateX(0)}50%{transform:translateX(-3px)}}
@keyframes lnLine{0%,100%{transform:scaleX(1)}50%{transform:scaleX(.45)}}
[data-sidebar] .ln-fold.go .fa{animation:lnArrowGo .22s ease-in forwards}
[data-sidebar] .ln-fold.go .fl{animation:lnLineGo .22s ease-in forwards}
@keyframes lnArrowGo{to{transform:translateX(-5px);opacity:.6}}
@keyframes lnLineGo{to{transform:scaleX(.2)}}
@media (prefers-reduced-motion:reduce){[data-sidebar] .ln-fold *{animation:none!important}}
[data-sidebar] .ln-av{width:36px;height:36px;flex:none;display:grid;place-items:center;border-radius:50%;background:var(--ln-hover);color:var(--ln-ink);border:1px solid var(--ln-line);font-size:12.5px;font-weight:700}
[data-sidebar] .ln-me{flex:1;min-width:0;display:flex;align-items:center;gap:10px;padding:8px;border:0;border-radius:10px;background:transparent;color:var(--ln-ink);font:inherit;cursor:pointer;transition:background .15s}
[data-sidebar] .ln-me:hover,[data-sidebar] .ln-me[aria-expanded="true"]{background:var(--ln-hover)}
[data-sidebar] .ln-me b,[data-sidebar] .ln-menu-who b{display:block;font-size:14px;font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-sidebar] .ln-me small,[data-sidebar] .ln-menu-who small{display:block;font-size:12.5px;color:var(--ln-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-sidebar] .ln-menu{position:absolute;left:8px;right:8px;bottom:calc(100% + 6px);z-index:60;padding:6px;border-radius:14px;background:var(--ln-bg);border:1px solid var(--ln-line);box-shadow:0 20px 44px -14px rgba(0,0,0,.65);animation:lnUp .16s ease-out}
@keyframes lnUp{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
[data-sidebar] .ln-menu-who{display:flex;align-items:center;gap:10px;padding:10px;margin-bottom:4px;border-radius:10px;background:var(--ln-hover);color:var(--ln-ink)}
[data-sidebar] .ln-menu button{display:flex;align-items:center;justify-content:space-between;width:100%;height:38px;padding:0 12px;border:0;border-radius:8px;background:none;color:var(--ln-dim);font:inherit;font-size:14px;font-weight:550;cursor:pointer}
[data-sidebar] .ln-menu button:hover{background:var(--ln-hover);color:var(--ln-ink)}
[data-sidebar] .ln-menu button.danger{color:var(--ln-danger)}
[data-sidebar] .ln-menu-sep{height:1px;background:var(--ln-line);margin:4px 6px}
`;

function Sidebar({ page, setPage, collapsed, setCollapsed, unreadMsgs, unreadAppts, pendingReviews = 0, mobileOpen = false, onNavigate, reviewQueueOn = false }) {
    const { t, toggle } = useTheme();
    const { user, logout } = useAuth();
    const [menuOpen, setMenuOpen] = useState(false);   // the account menu
    const [folding, setFolding] = useState(false);     // the collapse button's click motion
    useEffect(() => {
        if (!menuOpen) return undefined;
        const close = (e) => { if (!e.target.closest?.("[data-account]")) setMenuOpen(false); };
        const esc = (e) => { if (e.key === "Escape") setMenuOpen(false); };
        document.addEventListener("mousedown", close);
        document.addEventListener("keydown", esc);
        return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
    }, [menuOpen]);
    const signOut = async () => {
        setMenuOpen(false);
        await logout();
        // Hard redirect: clears all in-memory app state along with the session.
        window.location.assign("/login");
    };
    const { notifs, clearNotif, clearAll, openNotif } = useNotif();
    const [showNotifs, setShowNotifs] = useState(false);
    const unreadCount = notifs.filter(n => n.unread).length;
    const displayName = user?.full_name || "Advocate";
    const initials = displayName.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
    // Navigating always dismisses the mobile drawer; a no-op on desktop.
    const navigate = (p) => { setPage(p); onNavigate?.(); };
    const counts = { unreadMsgs, unreadAppts, pendingReviews };

    // Which groups are open: remembered, and the group holding the current
    // page always opens, so where you are is never folded away.
    const groupOf = (p) => NAV_SECTIONS.find(g => g.items?.some(i => i.id === p || PAGE_REDIRECT[i.id] === p))?.id;
    const [openGroups, setOpenGroups] = useState(() => new Set([groupOf(page)].filter(Boolean)));
    // The remembered groups load after mount (the server render cannot read them).
    useEffect(() => {
        let saved = null;
        try { saved = JSON.parse(localStorage.getItem(NAV_OPEN_KEY) || "null"); } catch { /* storage off */ }
        if (Array.isArray(saved)) setOpenGroups(prev => new Set([...prev, ...saved]));
    }, []);
    useEffect(() => {
        const g = groupOf(page);
        if (g) setOpenGroups(prev => (prev.has(g) ? prev : new Set([...prev, g])));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [page]);
    useEffect(() => {
        try { localStorage.setItem(NAV_OPEN_KEY, JSON.stringify([...openGroups])); } catch { /* storage off */ }
    }, [openGroups]);
    const toggleGroup = (id) => setOpenGroups(prev => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id); else next.add(id);
        return next;
    });
    const expandTo = (id) => { setCollapsed(false); setOpenGroups(prev => new Set([...prev, id])); };

    const bellBtn = (size) => (
        <button
            onClick={e => { e.stopPropagation(); setShowNotifs(v => !v); }}
            title="Notifications"
            style={{
                width: size, height: size, borderRadius: 7, border: "none",
                background: showNotifs ? t.primaryGlow2 : "transparent", color: t.textFaint,
                cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
                transition: "background .13s, color .13s", flexShrink: 0, position: "relative",
            }}
            onMouseEnter={e => { e.currentTarget.style.background = t.primaryGlow2; e.currentTarget.style.color = t.text; }}
            onMouseLeave={e => { e.currentTarget.style.background = showNotifs ? t.primaryGlow2 : "transparent"; e.currentTarget.style.color = t.textFaint; }}>
            <Icon d={I.bell} size={15} />
            {unreadCount > 0 && (
                <span style={{
                    position: "absolute", top: -2, right: -2,
                    minWidth: 15, height: 15, borderRadius: 8, padding: "0 3px",
                    background: t.danger, border: `2px solid ${t.surface}`,
                    fontSize: 8.5, fontWeight: 700, color: "#fff", boxSizing: "content-box",
                    display: "flex", alignItems: "center", justifyContent: "center",
                }}>{unreadCount > 99 ? "99+" : unreadCount}</span>
            )}
        </button>
    );

    return (
        <div data-sidebar data-collapsed={collapsed || undefined} className={`lw-sidebar${mobileOpen ? " open" : ""}`} style={{
            "--ln-bg": t.surface, "--ln-ink": t.text, "--ln-dim": t.textDim, "--ln-muted": t.textMuted,
            "--ln-hover": t.primaryGlow2, "--ln-line": t.border, "--ln-accent": t.primary, "--ln-danger": t.danger,
            width: collapsed ? 56 : 216,
            minWidth: collapsed ? 56 : 216,
            height: "100vh", background: t.surface,
            borderRight: `1px solid ${t.border}`,
            display: "flex", flexDirection: "column",
            transition: "width .25s ease, min-width .25s ease",
            overflowX: "hidden", zIndex: 10, flexShrink: 0,
            position: "sticky", top: 0,
        }}>

            {/* ── Brand ── */}
            <div style={{
                padding: collapsed ? "14px 0" : "0 10px 0 14px", minHeight: 64,
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
                            style={{ width: 28, height: 28, objectFit: "contain", display: "block", borderRadius: 6 }}
                        />
                    </button>
                ) : (
                    <>
                        <span className="ln-logo"><img src={logo} alt="AttorneyAI" /></span>
                        <div className="ln-word">Attorney<span>AI</span></div>
                        <button type="button" className={`ln-fold${folding ? " go" : ""}`}
                            onClick={() => { if (folding) return; setFolding(true); setTimeout(() => { setFolding(false); setCollapsed(true); }, 220); }}
                            aria-label="Collapse sidebar" title="Collapse sidebar">
                            <svg width={30} height={30} viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="2" y="3" width="20" height="18" rx="4.5" fill="var(--ln-accent)" opacity=".16" /><path d="M6.5 3H10v18H6.5A4.5 4.5 0 0 1 2 16.5v-9A4.5 4.5 0 0 1 6.5 3z" fill="var(--ln-accent)" /><g stroke="#04212A" strokeWidth="2" strokeLinecap="round"><path className="fl fl1" d="M4.3 7.2h3.9" /><path className="fl fl2" d="M4.3 10.4h3.9" /><path className="fl fl3" d="M4.3 13.6h3.9" /></g><path className="fa" d="M21.2 12.5h-8.4M16.6 8.7l-3.8 3.8 3.8 3.8" stroke="var(--ln-ink)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
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
            <style>{NAV_CSS}</style>
            <nav aria-label="Main" data-lenis-prevent style={{ flex: 1, padding: collapsed ? "10px 6px 0" : "12px 10px 0", overflowY: "auto", overflowX: "hidden" }}>
                {NAV_SECTIONS.map(section => section.items ? (
                    <NavGroup key={section.id} group={section}
                        items={section.items.filter(item => item.requires !== "reviewQueue" || reviewQueueOn)}
                        page={page} setPage={navigate} collapsed={collapsed} counts={counts}
                        open={openGroups.has(section.id)} onToggle={toggleGroup} onExpand={expandTo} />
                ) : (
                    <NavItem key={section.id} item={section} page={page} setPage={navigate} collapsed={collapsed} counts={counts} />
                ))}
            </nav>

            {/* ── Account: click the person for the menu ── */}
            <div data-account style={{ borderTop: `1px solid ${t.border}`, padding: collapsed ? "8px 6px" : "8px 8px", flexShrink: 0, position: "relative" }}>
                {menuOpen && (
                    <div role="menu" className="ln-menu" style={collapsed ? { left: 6, width: 240 } : undefined}>
                        <div className="ln-menu-who">
                            <span className="ln-av">{initials}</span>
                            <span style={{ minWidth: 0 }}>
                                <b>{displayName}</b>
                                {user?.email && <small>{user.email}</small>}
                            </span>
                        </div>
                        <button type="button" role="menuitem" onClick={() => { setMenuOpen(false); navigate("profile"); }}>
                            Profile <Icon d={I.user} size={17} />
                        </button>
                        <button type="button" role="menuitem" onClick={() => { setMenuOpen(false); navigate("settings"); }}>
                            Settings <Icon d={I.settings} size={17} />
                        </button>
                        <button type="button" role="menuitem" onClick={() => toggle()}>
                            {t.mode === "dark" ? "Light mode" : "Dark mode"} <Icon d={t.mode === "dark" ? I.sun : I.moon} size={17} />
                        </button>
                        <div className="ln-menu-sep" />
                        <button type="button" role="menuitem" className="danger" onClick={signOut}>
                            Logout <Icon d={I.logout} size={17} />
                        </button>
                    </div>
                )}
                {!collapsed ? (
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <button type="button" className="ln-me" aria-haspopup="menu" aria-expanded={menuOpen}
                            onClick={() => setMenuOpen(v => !v)}>
                            <span className="ln-av">{initials}</span>
                            <span style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
                                <b>{displayName}</b>
                                <small>View profile</small>
                            </span>
                        </button>
                        {bellBtn(30)}
                    </div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
                        {bellBtn(32)}
                        <button type="button" className="ln-av" style={{ border: 0, cursor: "pointer" }}
                            aria-haspopup="menu" aria-expanded={menuOpen} title={displayName}
                            onClick={() => setMenuOpen(v => !v)}>{initials}</button>
                    </div>
                )}
            </div>

            {showNotifs && (
                <NotificationPanel
                    onClose={() => setShowNotifs(false)}
                    notifs={notifs}
                    clearNotif={clearNotif}
                    clearAll={clearAll}
                    openNotif={openNotif}
                    anchorStyle={{ top: "auto", right: "auto", bottom: 14, left: collapsed ? 64 : 224 }}
                />
            )}
        </div>
    );
}

export { NotificationPanel, ActiveCaseBanner, Sidebar };