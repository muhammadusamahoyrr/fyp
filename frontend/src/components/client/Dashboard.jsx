'use client';
// Paste your Dashboard.jsx code here
import React, { useState, useRef, useEffect } from "react";
import { usePathname, useRouter as useNextRouter } from "next/navigation";
import { reviewRequestDeepLink } from "@/lib/reviewRequests.js";
import { listEngagements } from "@/lib/api.js";
import { isDraftCase } from "@/lib/caseStatus.js";
import { DARK, LIGHT, ThemeCtx, HeaderActionsCtx } from "./theme.js";
import { CLIENT_TOKENS_CSS, clientThemeOnTokens, clientMode } from "./clientTheme.js";
import { CaseProvider, useCase } from "./CaseContext.jsx";
import { LangProvider, useLang, useIsMobile } from "@/lib/i18n.jsx";
import { useAuth } from "@/context/AuthContext.jsx";
import { requestDocumentsView, requestOpenDocument, DOCUMENTS_SHOWN_EVENT } from "@/lib/documentsNav.js";
import { requestAgreementsView, AGREEMENTS_SHOWN_EVENT, AGREEMENTS_DIY_ENABLED } from "@/lib/agreementsNav.js";
import Ic from "./Ic.jsx";
import ModOverview from "./ModOverview.jsx";
import ModProfile from "./ModProfile.jsx";
import ModIntake from "./ModIntake.jsx";
import ModChatbot from "./ModChatbot.jsx";
import ModLawyers from "./ModLawyers.jsx";
import ModAgreements from "./ModAgreements.jsx";
import ModDocuments from "./ModDocuments.jsx";
import ModTracking from "./ModTracking.jsx";
import ModTools from "./ModTools.jsx";
import ModDisputes from "./ModDisputes.jsx";

/* ── paste logo1.jpg in the same folder as Dashboard.jsx ── */
const logoImg = "data:image/png;base64,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";

/* ─── Helpers ───────────────────────────────────────────────── */
const getLiveDate = (lang = "en") =>
    new Date().toLocaleDateString(lang === "ur" ? "ur-PK" : "en-US", {
        weekday: "long", year: "numeric", month: "long", day: "numeric",
    });

const SIDE_ITEMS = [
    // Profile is not here: it lives in the account menu at the bottom.
    { id: "overview", icon: "home", label: "Overview", ur: "جائزہ", group: "matters" },
    { id: "intake", icon: "brief", label: "Legal Intake", ur: "قانونی درخواست", group: "matters" },
    { id: "tracking", icon: "clock", label: "Tracking", ur: "کیس ٹریکنگ", group: "matters" },
    { id: "chatbot", icon: "bot", label: "AI Chat", ur: "اے آئی چیٹ", group: "help" },
    // OUT OF SCOPE, 2026-09-23. "Legal Tools" (`tools`) and "Property Dispute"
    // (`disputes`) are hidden from navigation at the owner's decision: neither
    // is in the current scope, so neither should be reachable from a screen.
    // The modules themselves are NOT deleted -- ModTools.jsx and
    // ModDisputes.jsx still exist and still work -- because this is a scope
    // decision, not an abandonment, and restoring them is putting these two
    // lines back. The lawyer-side counterpart ("Overseas Disputes", which is
    // where a client's property dispute arrives) is hidden in
    // `components/lawyer/layout.jsx` for the same reason.
    { id: "lawyers", icon: "search", label: "Lawyers", ur: "وکلاء", group: "help" },
    { id: "documents", icon: "file", label: "Documents", ur: "دستاویزات", group: "paper" },
    { id: "agreements", icon: "pen", label: "Agreements", ur: "معاہدے", group: "paper" },
];

/* The nav's sections, in order. Plain labels: always open, so the only
 * menu that opens and closes is Documents' own. */
const SIDE_GROUPS = [
    { id: "matters", label: "Your matters", ur: "آپ کے معاملات" },
    { id: "help", label: "Get help", ur: "مدد لیں" },
    { id: "paper", label: "Paperwork", ur: "کاغذات" },
];

/* Sections under a nav item, shown while that item is open. Only views that
 * exist: each one is a request the module itself carries out (see
 * lib/documentsNav.js), not a separate page. */
const SUB_ITEMS = {
    documents: [
        { view: "drafts", label: "AI drafting", ur: "اے آئی ڈرافٹنگ" },
        { view: "new", label: "Templates", ur: "ٹیمپلیٹس" },
        { view: "vault", label: "Vault", ur: "والٹ" },
    ],
    // The Agreements module's pages (its inner sidebar until 2026-10-11).
    // Templates only while the DIY builder is on. No "Create" item: a new
    // agreement starts from Templates (which has "Blank agreement"), so the
    // two were one route listed twice (2026-10-11).
    agreements: [
        { view: "dashboard", label: "Dashboard", ur: "ڈیش بورڈ" },
        ...(AGREEMENTS_DIY_ENABLED ? [
            { view: "templates", label: "Templates", ur: "ٹیمپلیٹس" },
        ] : []),
        { view: "all", label: "All agreements", ur: "تمام معاہدے" },
    ],
};

/* ─── Notification Drawer ───────────────────────────────────── */
const NotifDrawer = ({ open, onClose, onGoTracking, onOpenDocument, onOpenReviewRequest, t }) => {
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

    useEffect(() => {
        if (!open) return;
        document.body.style.overflow = "hidden";
        return () => { document.body.style.overflow = ""; };
    }, [open]);

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
                    width: "min(380px, 100vw)", background: t.surface,
                    borderLeft: `1.5px solid ${t.border}`,
                    display: "flex", flexDirection: "column",
                    boxShadow: "-8px 0 32px rgba(0,0,0,0.25)",
                    animation: "slideInRight 0.32s cubic-bezier(0.34,1.56,0.64,1)",
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
                            data-notification={n.id}
                            onClick={() => {
                                if (!n.done) markNotificationDone(n.id);
                                // A lawyer's decision on a document opens that document.
                                if (n.payload?.doc_id && onOpenDocument) { onOpenDocument(n.payload.doc_id); onClose(); }
                                // A review request (accepted / declined) carries no doc_id: it
                                // opens the request on Documents. Before, the click went nowhere.
                                else if (n.payload?.review_request_id && onOpenReviewRequest) { onOpenReviewRequest(n.payload.review_request_id); onClose(); }
                            }}
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
                                <div style={{ fontSize: 10, color: t.textFaint }}>{n.date} · {n.time}
                                    {n.payload?.doc_id && <span data-open-doc style={{ color: t.primary, fontWeight: 700 }}> · Open document →</span>}
                                </div>
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
/* The client sidebar (2026-10-11): the lawyer sidebar's look, as the
 * client's own copy -- scoped by [data-client-side], fed client tokens, so
 * nothing here can reach the lawyer shell. */
const CLIENT_SIDE_CSS = `
[data-client-side] .cs-item{position:relative;display:flex;align-items:center;gap:11px;width:100%;height:38px;padding:0 10px;margin:2px 0;border:0;border-radius:9px;background:transparent;color:var(--cs-dim);font:inherit;font-size:14.5px;font-weight:550;text-align:left;cursor:pointer;transition:background .15s,color .15s}
[data-client-side] .cs-item:hover{background:var(--cs-hover);color:var(--cs-ink)}
[data-client-side] .cs-ic{position:relative;width:24px;height:24px;flex:none;display:grid;place-items:center;color:var(--cs-muted);transition:color .15s}
[data-client-side] .cs-item:hover .cs-ic{color:var(--cs-ink)}
[data-client-side] .cs-label{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-client-side] .cs-item.on{background:linear-gradient(90deg,#1F7A4D,#147C74);color:#fff;font-weight:650;box-shadow:0 8px 18px -12px rgba(20,124,116,.9)}
[data-client-side] .cs-item.on .cs-ic{color:#fff}
[data-client-side] .cs-chev{display:grid;place-items:center;color:inherit;transition:transform .2s}
[data-client-side] .cs-rail{position:relative;margin:2px 0 6px 14px;padding-left:12px;animation:csIn .18s ease-out}
[data-client-side] .cs-rail::after{content:"";position:absolute;left:0;top:-4px;bottom:0;width:1px;background:var(--cs-line);pointer-events:none}
@keyframes csIn{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
[data-client-side] .cs-item.sub{height:33px;padding:0 10px;gap:10px;font-size:13.5px;font-weight:520}
[data-client-side] .cs-item.sub[aria-current="page"]{background:var(--cs-hover);color:var(--cs-accent);font-weight:650}
[data-client-side] .cs-item.sub[aria-current="page"]::before{content:"";position:absolute;left:-12.5px;top:8px;bottom:8px;width:2px;border-radius:2px;background:var(--cs-accent);z-index:1}
[data-client-side] .cs-badge{flex:none;min-width:20px;height:20px;padding:0 6px;display:grid;place-items:center;border-radius:999px;background:var(--cs-danger);color:#fff;font-size:11px;font-weight:700}
[data-client-side] .cs-badge.gold{background:rgba(242,195,94,.18);color:var(--gold,#f2c35e)}
[data-client-side] .cs-badge.cyan{background:rgba(106,221,235,.16);color:#3fbfd0}
[data-client-side] .cs-item.on .cs-badge.gold,[data-client-side] .cs-item.on .cs-badge.cyan{background:rgba(255,255,255,.2);color:#fff}
[data-client-side] .cs-new{display:flex;align-items:center;justify-content:center;gap:8px;width:calc(100% - 24px);height:36px;margin:12px 12px 2px;border:0;border-radius:999px;background:linear-gradient(135deg,#12897f,#1c9c66);color:#fff;font:inherit;font-size:13.5px;font-weight:650;cursor:pointer;flex-shrink:0;box-shadow:0 6px 14px -10px rgba(28,156,102,.9);transition:filter .15s,transform .12s}
[data-client-side] .cs-new:hover{filter:brightness(1.08)}
[data-client-side] .cs-new:active{transform:scale(.97)}
[data-client-side] .cs-new svg{transition:transform .25s}
[data-client-side] .cs-new:hover svg{transform:rotate(90deg)}
[data-client-side][data-collapsed] .cs-new{width:38px;height:38px;margin:12px auto 4px;padding:0}
[data-client-side] .cs-sec{margin:12px 0 3px;padding:4px 6px;color:var(--cs-muted);font-size:10.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase}
[data-client-side] .cs-sec:first-child{margin-top:2px}
[data-client-side] .cs-gap{height:1px;margin:8px 10px;background:var(--cs-line)}
.cs-tip{position:fixed;z-index:80;transform:translateY(-50%);white-space:nowrap;padding:6px 10px;border-radius:8px;background:var(--cs-tip-bg);border:1px solid var(--cs-tip-line);color:var(--cs-tip-ink);font-size:12.5px;font-weight:600;box-shadow:0 10px 20px -10px rgba(0,0,0,.6);pointer-events:none;animation:csTip .12s ease-out}
@keyframes csTip{from{opacity:0;transform:translate(-4px,-50%)}to{opacity:1;transform:translate(0,-50%)}}
[data-client-side] .cs-dot{position:absolute;top:-2px;right:-3px;width:8px;height:8px;border-radius:50%;background:var(--cs-danger);border:2px solid var(--cs-bg)}
[data-client-side][data-collapsed] .cs-item{justify-content:center;padding:0}
[data-client-side] .cs-logo{width:38px;height:38px;flex:none;display:grid;place-items:center;border:0;padding:0;background:none;cursor:pointer}
[data-client-side] .cs-logo img{width:38px;height:38px;object-fit:contain;display:block}
[data-client-side] .cs-word{flex:1;min-width:0;font-size:18px;font-weight:800;letter-spacing:-.01em;color:var(--cs-ink);white-space:nowrap}
[data-client-side] .cs-word span{color:var(--cs-accent)}
[data-client-side] .cs-fold{width:36px;height:36px;flex:none;display:grid;place-items:center;border:0;border-radius:8px;background:transparent;color:var(--cs-muted);cursor:pointer;transition:background .15s}
[data-client-side] .cs-fold:hover{background:var(--cs-hover)}
[data-client-side] .cs-fold .fl,[data-client-side] .cs-fold .fa{transform-box:fill-box;transform-origin:left center}
[data-client-side] .cs-fold.go .fa{animation:csArrowGo .22s ease-in forwards}
[data-client-side] .cs-fold.go .fl{animation:csLineGo .22s ease-in forwards}
[data-client-side][data-collapsed] .cs-fold .fa{transform:scaleX(-1);transform-origin:center}
@keyframes csArrowGo{to{transform:translateX(-5px);opacity:.6}}
@keyframes csLineGo{to{transform:scaleX(.2)}}
[data-client-side] .cs-av{width:32px;height:32px;flex:none;display:grid;place-items:center;border-radius:50%;background:linear-gradient(135deg,#3ee0a1,#2ec4d6);color:#04212a;font-size:12px;font-weight:800}
[data-client-side] .cs-me{flex:1;min-width:0;display:flex;align-items:center;gap:9px;padding:5px 6px;border:0;border-radius:10px;background:transparent;color:var(--cs-ink);font:inherit;cursor:pointer;transition:background .15s}
[data-client-side] .cs-me:hover,[data-client-side] .cs-me[aria-expanded="true"]{background:var(--cs-hover)}
[data-client-side] .cs-me b,[data-client-side] .cs-menu-who b{display:block;font-size:13.5px;line-height:1.25;font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-client-side] .cs-me small,[data-client-side] .cs-menu-who small{display:block;font-size:12px;line-height:1.25;color:var(--cs-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-client-side] .cs-bell{position:relative;width:34px;height:34px;flex:none;display:grid;place-items:center;border:0;border-radius:9px;background:transparent;color:var(--cs-muted);cursor:pointer;transition:background .15s,color .15s}
[data-client-side] .cs-bell:hover{background:var(--cs-hover);color:var(--cs-ink)}
[data-client-side] .cs-bell b{position:absolute;top:-1px;right:-2px;min-width:16px;height:16px;padding:0 4px;box-sizing:border-box;border-radius:8px;display:grid;place-items:center;background:var(--cs-danger);color:#fff;font-size:9px;font-weight:700}
[data-client-side] .cs-menu{position:absolute;left:8px;right:8px;bottom:calc(100% + 6px);z-index:60;padding:6px;border-radius:14px;background:var(--cs-bg);border:1px solid var(--cs-line);box-shadow:0 20px 44px -14px rgba(0,0,0,.65);animation:csUp .16s ease-out}
@keyframes csUp{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
[data-client-side] .cs-menu-who{display:flex;align-items:center;gap:10px;padding:10px;margin-bottom:4px;border-radius:10px;background:var(--cs-hover);color:var(--cs-ink)}
[data-client-side] .cs-menu button{display:flex;align-items:center;justify-content:space-between;width:100%;height:38px;padding:0 12px;border:0;border-radius:8px;background:none;color:var(--cs-dim);font:inherit;font-size:14px;font-weight:550;cursor:pointer}
[data-client-side] .cs-menu button:hover{background:var(--cs-hover);color:var(--cs-ink)}
[data-client-side] .cs-menu button.danger{color:var(--cs-danger)}
[data-client-side] .cs-menu-sep{height:1px;background:var(--cs-line);margin:4px 6px}
@media (prefers-reduced-motion:reduce){[data-client-side] *{animation:none!important}}
`;

const DashboardInner = ({ go, isDark, toggleTheme, initialTab = "overview" }) => {
    // The lawyer documents' palette, as the client's own copy (clientTheme.js):
    // neutral colours read CSS tokens that <body> carries while this is mounted,
    // so dialogs portalled to <body> are themed too. No layout changes.
    const t = clientThemeOnTokens(isDark ? DARK : LIGHT);
    useEffect(() => {
        const body = document.body;
        body.setAttribute("data-client-theme", "");
        body.setAttribute("data-mode", clientMode(t));
        return () => { body.removeAttribute("data-client-theme"); body.removeAttribute("data-mode"); };
    }, [t.mode]);
    const { unreadCount, cases } = useCase();
    const draftCount = (cases || []).filter(isDraftCase).length;
    const { T, lang, toggleLang } = useLang();
    const { user } = useAuth();
    const isMobile = useIsMobile();
    const [tab, setTab] = useState(initialTab);
    const [headerActions, setHeaderActions] = useState(null);
    const [drawerOpen, setDrawerOpen] = useState(false);
    const [isCollapsed, setIsCollapsed] = useState(false);
    const [mobileNavOpen, setMobileNavOpen] = useState(false);
    const [acctOpen, setAcctOpen] = useState(false);   // the account menu
    const [folding, setFolding] = useState(false);     // the fold button's click motion
    const [tip, setTip] = useState(null);              // the collapsed sidebar's hover label
    const [termsCount, setTermsCount] = useState(0);   // lawyers' proposed terms awaiting the client
    useEffect(() => {
        if (!acctOpen) return undefined;
        const close = (e) => { if (!e.target.closest?.("[data-client-account]")) setAcctOpen(false); };
        const esc = (e) => { if (e.key === "Escape") setAcctOpen(false); };
        document.addEventListener("mousedown", close);
        document.addEventListener("keydown", esc);
        return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
    }, [acctOpen]);
    // The Documents section last opened from its sub-menu, for highlighting.
    const [docSection, setDocSection] = useState("new");
    // Whether the Documents sub-menu is open. Its own toggle (the ▲/▼ on the
    // item), so opening the menu never navigates anywhere by itself.
    const [docMenuOpen, setDocMenuOpen] = useState(initialTab === "documents");
    // The same for Agreements: its page, and whether its sub-menu is open.
    const [agSection, setAgSection] = useState("dashboard");
    const [agMenuOpen, setAgMenuOpen] = useState(initialTab === "agreements");
    useEffect(() => {
        const onShown = e => { if (e?.detail?.view) setDocSection(e.detail.view); };
        // Writing an agreement is reached through Templates, so it lights that.
        const onAgShown = e => { if (e?.detail?.view) setAgSection(e.detail.view === "create" ? "templates" : e.detail.view); };
        window.addEventListener(DOCUMENTS_SHOWN_EVENT, onShown);
        window.addEventListener(AGREEMENTS_SHOWN_EVENT, onAgShown);
        return () => {
            window.removeEventListener(DOCUMENTS_SHOWN_EVENT, onShown);
            window.removeEventListener(AGREEMENTS_SHOWN_EVENT, onAgShown);
        };
    }, []);
    const contentRef = useRef(null);

    const displayName = user?.full_name || "Client";
    const initials = displayName.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();

    useEffect(() => {
        if (contentRef.current) contentRef.current.scrollTop = 0;
    }, [tab]);

    // Terms a lawyer proposed, for the Lawyers badge. Re-read on each tab
    // change, since answering them happens on a tab. A failed read shows none.
    useEffect(() => {
        let live = true;
        Promise.resolve(listEngagements()).then(res => {
            if (!live) return;
            const rows = res?.data?.items || res?.data || [];
            setTermsCount(Array.isArray(rows) ? rows.filter(e => e.status === "terms_proposed").length : 0);
        }).catch(() => {});
        return () => { live = false; };
    }, [tab]);
    useEffect(() => { if (!isCollapsed) setTip(null); }, [isCollapsed]);

    // The mini-collapsed sidebar makes no sense inside the mobile drawer
    useEffect(() => {
        if (isMobile && isCollapsed) setIsCollapsed(false);
    }, [isMobile, isCollapsed]);

    const navRouter = useNextRouter();

    // Sync tab with URL so router.push('/lawyers') correctly switches the active tab
    // even when React reuses this component instance across same-layout navigations.
    const pathname = usePathname();
    useEffect(() => {
        const PATH_TAB = {
            "/dashboard": "overview",
            "/intake": "intake",
            "/chat": "chatbot",
            // "/tools" deliberately absent — see SIDE_ITEMS.
            "/lawyers": "lawyers",
            "/documents": "documents",
            "/agreements": "agreements",
            "/tracking": "tracking",
            "/profile": "profile",
        };
        const next = PATH_TAB[pathname];
        if (next && next !== tab) setTab(next);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [pathname]);

    const liveDate = getLiveDate(lang);

    const modules = {
        overview: <ModOverview onOpenNotifications={() => setDrawerOpen(true)} />,
        profile: <ModProfile />,
        intake: <ModIntake />,
        chatbot: <ModChatbot />,
        lawyers: <ModLawyers />,
        agreements: <ModAgreements />,
        documents: <ModDocuments />,
        tracking: <ModTracking isDark={isDark} />,
        tools: <ModTools />,
        disputes: <ModDisputes />,
    };

    // Documents draws its own header and manages its own scrolling: its
    // screens (drafting) are full-height workspaces.
    // Lawyers (2026-10-10) draws its own title, as Documents does.
    const noTopbar = tab === "agreements" || tab === "chatbot" || tab === "tracking" || tab === "documents" || tab === "lawyers" || tab === "intake" || tab === "overview" || tab === "profile";
    const noPadding = tab === "agreements" || tab === "chatbot" || tab === "documents";

    return (
        <ThemeCtx.Provider value={t}>
            <HeaderActionsCtx.Provider value={{ setHeaderActions }}>
                <style>{CLIENT_TOKENS_CSS}</style>

                <NotifDrawer
                    open={drawerOpen}
                    onClose={() => setDrawerOpen(false)}
                    onGoTracking={() => setTab("tracking")}
                    onOpenDocument={id => { requestOpenDocument(id); if (tab !== "documents") navRouter.push("/documents"); }}
                    onOpenReviewRequest={id => navRouter.push(reviewRequestDeepLink(id))}
                    t={t}
                />

                <div data-client-theme="" data-mode={clientMode(t)} style={{
                    display: "flex", height: "100vh", overflow: "hidden",
                    background: t.bg,
                    transition: "background 0.5s cubic-bezier(0.4,0,0.2,1)",
                }}>

                    {/* Mobile nav backdrop */}
                    {isMobile && mobileNavOpen && (
                        <div onClick={() => setMobileNavOpen(false)}
                            style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 40 }} />
                    )}

                    {/* ══════════════ SIDEBAR (drawer on mobile) ══════════════ */}
                    <style>{CLIENT_SIDE_CSS}</style>
                    <div data-client-side="" data-collapsed={isCollapsed || undefined} style={{
                        "--cs-bg": t.surface, "--cs-ink": t.text, "--cs-dim": t.textDim, "--cs-muted": t.textMuted,
                        "--cs-hover": t.primaryGlow2, "--cs-line": t.border, "--cs-accent": t.primary, "--cs-danger": t.danger,
                        "--cs-tip-bg": t.surface, "--cs-tip-line": t.border, "--cs-tip-ink": t.text,
                        width: isMobile ? 260 : (isCollapsed ? 64 : 216),
                        minWidth: isMobile ? 260 : (isCollapsed ? 64 : 216),
                        background: t.surface,
                        borderRight: `1px solid ${t.border}`,
                        display: "flex", flexDirection: "column",
                        transition: "width .25s ease, min-width .25s ease",
                        zIndex: isMobile ? 41 : 10,
                        overflowX: "hidden",
                        ...(isMobile ? {
                            position: "fixed", top: 0, bottom: 0, left: 0,
                            transform: mobileNavOpen ? "translateX(0)" : "translateX(-105%)",
                            transition: "transform 0.3s cubic-bezier(0.4,0,0.2,1)",
                        } : {}),
                    }}>

                        {/* ══ BRAND ══ */}
                        <div style={{
                            padding: isCollapsed ? "0" : "0 10px 0 14px", minHeight: 64,
                            display: "flex", alignItems: "center", gap: 10,
                            borderBottom: `1px solid ${t.border}`, flexShrink: 0,
                            justifyContent: isCollapsed ? "center" : "flex-start",
                        }}>
                            <button type="button" className="cs-logo" title={isCollapsed ? T("Expand sidebar", "سائیڈبار کھولیں") : "Attorney.AI"}
                                onClick={() => (isCollapsed ? setIsCollapsed(false) : setTab("overview"))}>
                                <img src="./logo.png" alt="Attorney.AI" />
                            </button>
                            {!isCollapsed && (<>
                                <div className="cs-word">Attorney<span>AI</span></div>
                                <button type="button" className={`cs-fold${folding ? " go" : ""}`}
                                    onClick={() => { if (folding) return; setFolding(true); setTimeout(() => { setFolding(false); setIsCollapsed(true); }, 220); }}
                                    aria-label={T("Collapse sidebar", "سائیڈبار بند کریں")} title={T("Collapse sidebar", "سائیڈبار بند کریں")}>
                                    <svg width={30} height={30} viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="2" y="3" width="20" height="18" rx="4.5" fill="var(--cs-accent)" opacity=".16" /><path d="M6.5 3H10v18H6.5A4.5 4.5 0 0 1 2 16.5v-9A4.5 4.5 0 0 1 6.5 3z" fill="var(--cs-accent)" /><g stroke="#04212A" strokeWidth="2" strokeLinecap="round"><path className="fl" d="M4.3 7.2h3.9" /><path className="fl" d="M4.3 10.4h3.9" /><path className="fl" d="M4.3 13.6h3.9" /></g><path className="fa" d="M21.2 12.5h-8.4M16.6 8.7l-3.8 3.8 3.8 3.8" stroke="var(--cs-ink)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
                                </button>
                            </>)}
                        </div>

                        {/* ══ NEW MATTER: the one primary action ══ */}
                        <button type="button" className="cs-new" aria-label={T("New matter", "نیا معاملہ")}
                            title={isCollapsed ? T("New matter", "نیا معاملہ") : undefined}
                            onClick={() => { setDocMenuOpen(false); navRouter.push("/intake"); setMobileNavOpen(false); }}>
                            <Ic n="plus" s={isCollapsed ? 18 : 16} c="currentColor" />
                            {!isCollapsed && T("New matter", "نیا معاملہ")}
                        </button>

                        {/* ══ NAV ITEMS ══ */}
                        {/* `minHeight: 0` is what makes this scroll. A flex child
                            defaults to `min-height: auto` — its content height —
                            so the list grew past the sidebar and was clipped by
                            the sidebar's `overflow: hidden` instead of scrolling. */}
                        {/* `data-lenis-prevent`: the app-wide Lenis smooth scroll
                            takes every wheel event for the page, so without it the
                            wheel did nothing here and only dragging the bar worked. */}
                        <nav data-lenis-prevent className="thin-scrollbar" style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: isCollapsed ? "10px 8px 0" : "12px 10px 0" }}>
                            {SIDE_GROUPS.map((group, gi) => {
                                return (
                                <React.Fragment key={group.id}>
                                {isCollapsed ? (gi > 0 && <div className="cs-gap" aria-hidden="true" />) : (
                                    <div className="cs-sec">{T(group.label, group.ur)}</div>
                                )}
                                {SIDE_ITEMS.filter(item => item.group === group.id).map(item => {
                                const active = tab === item.id;
                                // Real counts only, and only where the client has something to do.
                                const count = item.id === "tracking" ? unreadCount
                                    : item.id === "intake" ? draftCount
                                    : item.id === "lawyers" ? termsCount : 0;
                                const tone = item.id === "intake" ? " gold" : item.id === "lawyers" ? " cyan" : "";
                                const showDot = count > 0 && !(item.id === "tracking" && active);
                                const tipText = T(item.label, item.ur) + (showDot
                                    ? (item.id === "intake" ? T(` · ${count} to confirm`, ` · ${count} تصدیق باقی`)
                                        : item.id === "lawyers" ? T(` · ${count} terms to review`, ` · ${count} شرائط`)
                                        : T(` · ${count} new`, ` · ${count} نئی`)) : "");
                                const hasMenu = Boolean(SUB_ITEMS[item.id]);
                                const isAg = item.id === "agreements";
                                const menuOpen = isAg ? agMenuOpen : docMenuOpen;
                                const section = isAg ? agSection : docSection;
                                const subItems = !isCollapsed && hasMenu && menuOpen ? SUB_ITEMS[item.id] : [];
                                return (
                                    <React.Fragment key={item.id}>
                                    <button
                                        type="button"
                                        className={`cs-item${active ? " on" : ""}`}
                                        aria-current={active ? "page" : undefined}
                                        aria-label={isCollapsed ? tipText : undefined}
                                        onMouseEnter={isCollapsed ? (e => { const r = e.currentTarget.getBoundingClientRect(); setTip({ text: tipText, top: r.top + r.height / 2, left: r.right + 10 }); }) : undefined}
                                        onMouseLeave={isCollapsed ? (() => setTip(null)) : undefined}
                                        aria-expanded={hasMenu ? menuOpen : undefined}
                                        onClick={() => {
                                            const TAB_PATH = {
                                                overview: "/dashboard", intake: "/intake",
                                                chatbot: "/chat", lawyers: "/lawyers",
                                                cases: "/cases", documents: "/documents",
                                                agreements: "/agreements", tracking: "/tracking",
                                                profile: "/profile",
                                                // `tools` deliberately absent — see SIDE_ITEMS.
                                            };
                                            const path = TAB_PATH[item.id];
                                            if (item.id === "documents") {
                                                // Already here: the item only opens or closes its menu.
                                                if (tab === "documents") { setDocMenuOpen(o => !o); return; }
                                                // Arriving: the Documents HOME, never straight into the
                                                // last draft's review step. That draft is still one click
                                                // away under "Continue where you left off".
                                                requestDocumentsView("new");
                                                setDocSection("new");
                                                setDocMenuOpen(true);
                                                setAgMenuOpen(false);
                                            } else if (item.id === "agreements") {
                                                // As Documents: here, toggle; arriving, its first page.
                                                if (tab === "agreements") { setAgMenuOpen(o => !o); return; }
                                                requestAgreementsView("dashboard");
                                                setAgSection("dashboard");
                                                setAgMenuOpen(true);
                                                setDocMenuOpen(false);
                                            } else {
                                                setDocMenuOpen(false);
                                                setAgMenuOpen(false);
                                            }
                                            if (path) navRouter.push(path);
                                            else setTab(item.id);
                                            setMobileNavOpen(false);
                                            setTip(null);
                                        }}
                                    >
                                        <span className="cs-ic">
                                            <Ic n={item.icon} s={19} c="currentColor" />
                                            {isCollapsed && showDot && <i className="cs-dot" aria-hidden="true" style={tone ? { background: tone === " gold" ? "#f2c35e" : "#3fbfd0" } : undefined} />}
                                        </span>
                                        {!isCollapsed && <span className="cs-label">{T(item.label, item.ur)}</span>}
                                        {!isCollapsed && showDot && <span className={`cs-badge${tone}`}>{count > 99 ? "99+" : count}</span>}
                                        {!isCollapsed && hasMenu && (
                                            <span className="cs-chev" aria-hidden="true">
                                                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"
                                                    style={{ transform: menuOpen ? "rotate(180deg)" : "none", transition: "transform 0.2s" }}>
                                                    <path d="M6 9l6 6 6-6" />
                                                </svg>
                                            </span>
                                        )}
                                    </button>
                                    {subItems.length > 0 && (
                                        <div role="group" aria-label={`${item.label} sections`} className="cs-rail">
                                            {subItems.map(sub => (
                                                <button key={sub.view} type="button"
                                                    aria-current={section === sub.view && tab === item.id ? "page" : undefined}
                                                    onClick={() => {
                                                        if (isAg) {
                                                            requestAgreementsView(sub.view);
                                                            setAgSection(sub.view);
                                                            if (tab !== "agreements") navRouter.push("/agreements");
                                                            setMobileNavOpen(false);
                                                            return;
                                                        }
                                                        requestDocumentsView(sub.view);
                                                        setDocSection(sub.view);
                                                        // From another tab the request waits until the
                                                        // module mounts (lib/documentsNav.js).
                                                        if (tab !== "documents") navRouter.push("/documents");
                                                        setMobileNavOpen(false);
                                                    }}
                                                    className="cs-item sub">
                                                    {T(sub.label, sub.ur)}
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                    </React.Fragment>
                                );
                            })}
                                </React.Fragment>
                                );
                            })}
                        </nav>
                        {tip && isCollapsed && <div className="cs-tip" role="tooltip" style={{ top: tip.top, left: tip.left }}>{tip.text}</div>}

                        {/* ══ ACCOUNT: click the person for the menu ══ */}
                        <div data-client-account="" style={{ borderTop: `1px solid ${t.border}`, padding: isCollapsed ? "6px" : "5px 8px", flexShrink: 0, position: "relative" }}>
                            {acctOpen && (
                                <div role="menu" className="cs-menu" style={isCollapsed ? { left: 6, right: "auto", width: 240 } : undefined}>
                                    <div className="cs-menu-who">
                                        <span className="cs-av">{initials}</span>
                                        <span style={{ minWidth: 0 }}>
                                            <b>{displayName}</b>
                                            {user?.email && <small>{user.email}</small>}
                                        </span>
                                    </div>
                                    <button type="button" role="menuitem" onClick={() => { setAcctOpen(false); navRouter.push("/profile"); setMobileNavOpen(false); }}>
                                        {T("Profile", "پروفائل")} <Ic n="user" s={17} />
                                    </button>
                                    <button type="button" role="menuitem" onClick={() => toggleLang()}>
                                        {T("اردو میں دیکھیں", "Switch to English")} <svg width={17} height={17} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 5h7M8 3v2M5 9c1.5 3 4 5 6 6M11 5c-1 4-3 7-6 9M13 21l4-10 4 10M14.5 17h5" /></svg>
                                    </button>
                                    <button type="button" role="menuitem" onClick={() => toggleTheme()}>
                                        {isDark ? T("Light mode", "لائٹ موڈ") : T("Dark mode", "ڈارک موڈ")} <Ic n={isDark ? "sun" : "moon"} s={17} />
                                    </button>
                                    <div className="cs-menu-sep" />
                                    <button type="button" role="menuitem" className="danger" onClick={() => { setAcctOpen(false); go("signout"); }}>
                                        {T("Sign Out", "سائن آؤٹ")} <Ic n="logout" s={17} />
                                    </button>
                                </div>
                            )}
                            {!isCollapsed ? (
                                <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                                    <button type="button" className="cs-me" aria-haspopup="menu" aria-expanded={acctOpen} onClick={() => setAcctOpen(v => !v)}>
                                        <span className="cs-av">{initials}</span>
                                        <span style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
                                            <b>{displayName}</b>
                                            <small>{T("View profile", "پروفائل دیکھیں")}</small>
                                        </span>
                                    </button>
                                    <button type="button" className="cs-bell" aria-label={T("Notifications", "اطلاعات")} onClick={() => setDrawerOpen(true)}>
                                        <Ic n="bell" s={17} c="currentColor" />
                                        {unreadCount > 0 && <b>{unreadCount > 99 ? "99+" : unreadCount}</b>}
                                    </button>
                                </div>
                            ) : (
                                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
                                    <button type="button" className="cs-bell" aria-label={T("Notifications", "اطلاعات")} onClick={() => setDrawerOpen(true)}>
                                        <Ic n="bell" s={17} c="currentColor" />
                                        {unreadCount > 0 && <b>{unreadCount > 99 ? "99+" : unreadCount}</b>}
                                    </button>
                                    <button type="button" className="cs-av" style={{ border: 0, cursor: "pointer" }} aria-haspopup="menu" aria-expanded={acctOpen}
                                        title={displayName} onClick={() => setAcctOpen(v => !v)}>{initials}</button>
                                </div>
                            )}
                        </div>
                    </div>
                    {/* ══════════════ END SIDEBAR ══════════════ */}

                    {/* ══ MAIN CONTENT ══ */}
                    <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>

                        {!noTopbar && (
                            <div style={{
                                padding: isMobile ? "0 14px" : "0 36px",
                                height: 62,
                                minHeight: 62,
                                borderBottom: `1.5px solid ${t.border}`,
                                display: "flex", alignItems: "center", justifyContent: "space-between",
                                background: isDark ? "rgba(26,46,53,0.82)" : "rgba(255,255,255,0.82)",
                                backdropFilter: "blur(18px) saturate(180%)",
                                WebkitBackdropFilter: "blur(18px) saturate(180%)",
                                position: "sticky", top: 0, zIndex: 20,
                                transition: "all 0.4s",
                                boxShadow: isDark ? "0 1px 0 rgba(64,240,220,0.06)" : "0 2px 12px rgba(26,46,53,0.08)",
                            }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                                    {isMobile && (
                                        <button
                                            onClick={() => setMobileNavOpen(true)}
                                            aria-label="Open menu"
                                            style={{
                                                width: 36, height: 36, borderRadius: 10, flexShrink: 0,
                                                border: `1.5px solid ${t.border}`, background: "transparent",
                                                color: t.textMuted, cursor: "pointer",
                                                display: "flex", alignItems: "center", justifyContent: "center",
                                            }}>
                                            <Ic n="menu" s={18} />
                                        </button>
                                    )}
                                    <div style={{ minWidth: 0 }}>
                                        <h1 style={{
                                            fontSize: isMobile ? 18 : 22,
                                            fontWeight: 700,
                                            color: t.text,
                                            letterSpacing: "-0.5px",
                                            fontFamily: "'Playfair Display', serif",
                                            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                                        }}>
                                            {(i => i ? T(i.label, i.ur) : "")(SIDE_ITEMS.find(i => i.id === tab))}
                                        </h1>
                                        <p style={{ fontSize: 12, color: t.textMuted, marginTop: 2, whiteSpace: "nowrap" }}>{liveDate}</p>
                                    </div>
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

                        {/* Floating menu button for full-bleed tabs (no topbar) on mobile */}
                        {isMobile && noTopbar && !mobileNavOpen && (
                            <button
                                onClick={() => setMobileNavOpen(true)}
                                aria-label="Open menu"
                                style={{
                                    position: "fixed", top: 12, left: 12, zIndex: 30,
                                    width: 38, height: 38, borderRadius: 12,
                                    border: `1.5px solid ${t.border}`, background: t.surface,
                                    color: t.textMuted, cursor: "pointer",
                                    display: "flex", alignItems: "center", justifyContent: "center",
                                    boxShadow: "0 4px 16px rgba(0,0,0,0.25)",
                                }}>
                                <Ic n="menu" s={18} />
                            </button>
                        )}

                        <div
                            ref={contentRef}
                            data-lenis-prevent
                            style={{
                                flex: 1,
                                padding: noPadding ? 0 : (isMobile ? 14 : 32),
                                overflow: noPadding ? "hidden" : "auto",
                                display: "flex", flexDirection: "column",
                                scrollBehavior: "smooth",
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
    <LangProvider>
        <CaseProvider>
            <DashboardInner go={go} isDark={isDark} toggleTheme={toggleTheme} initialTab={initialTab} />
        </CaseProvider>
    </LangProvider>
);

export default Dashboard;