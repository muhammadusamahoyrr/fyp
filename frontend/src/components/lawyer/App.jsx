'use client';
// Lawyer App — paste your code here
import { useState, useEffect, useRef } from "react";
import { DARK, LIGHT, ThemeCtx, ToggleCtx, CaseCtx, NotifCtx } from "./theme.js";
import { ToastContainer } from "@/components/lawyer/Toast.jsx";
import { injectGS } from "./globalStyles.js";
import { Sidebar, ActiveCaseBanner } from "./layout.jsx";
import { Icon, I } from "./icons.jsx";
import { DashboardPage } from "./DashboardPage.jsx";
import { CasesPage } from "./CasesPage.jsx";
import { DocWorkflowApp } from "./DocumentsPage.jsx";
import { AppointmentsPage } from "./AppointmentsPage.jsx";
import { AgreementsPage } from "./AgreementsPage.jsx";
import { CauselistPage } from "./CauselistPage.jsx";
import { CaseLawPage } from "./CaseLawPage.jsx";
import { PaymentsPage } from "./PaymentsPage.jsx";
import { ClientsPage } from "./ClientsPage.jsx";
import { AILegalPage } from "./AILegalPage.jsx";
import { DocAutomationPage } from "./DocAutomationPage.jsx";
import { DocAnalyzerPage } from "./DocAnalyzerPage.jsx";
import { VaultPage } from "./VaultPage.jsx";
import { ReviewQueuePage } from "./ReviewQueuePage.jsx";
import { ProfilePage } from "./ProfilePage.jsx";
import { SettingsPage } from "./SettingsPage.jsx";
import { DisputesInboxPage } from "./DisputesInboxPage.jsx";
import { BailCheckerPage, CalculatorsPage } from "./LegalToolsPage.jsx";
import { OnboardingPage, ONBOARDED_KEY, isLawyerOnboarded } from "./OnboardingPage.jsx";
import { getMe, getNotifications, listReviewInbox, reviewQueueV2, markNotificationRead, markAllNotificationsRead, openNotificationSocket } from "@/lib/api.js";
import { lawyerNotificationTarget, broadcastNotification, reconnectDelay } from "@/lib/notificationTarget.js";

const DocumentsPage = DocWorkflowApp;
const pageMap = { dashboard: DashboardPage, cases: CasesPage, documents: DocumentsPage, appointments: AppointmentsPage, agreements: AgreementsPage, causelist: CauselistPage, caselaw: CaseLawPage, payments: PaymentsPage, clients: ClientsPage, "ai-legal": AILegalPage, "doc-automation": DocAutomationPage, "doc-analyzer": DocAnalyzerPage, vault: VaultPage, "review-queue": ReviewQueuePage, "overseas-disputes": DisputesInboxPage, profile: ProfilePage, settings: SettingsPage, onboarding: OnboardingPage, "bail-checker": BailCheckerPage, calculators: CalculatorsPage };

const _fmtAgo = (iso) => {
    if (!iso) return "";
    const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    if (mins < 60) return `${mins}m ago`;
    if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
    return `${Math.round(mins / 1440)}d ago`;
};

/* THE ADDRESS FOLLOWS THE PAGE (2026-10-09). Navigation is state, so a sidebar
 * click left the URL on the entry route: a refresh, a bookmark or a copied
 * link went back to wherever the lawyer had first landed. Each page with its
 * own route (src/app/lawyer/**) now writes it, and Back/Forward walk them.
 * Pages without a route (onboarding) leave the address alone. */
export const PAGE_PATH = {
    dashboard: "/lawyer", cases: "/lawyer/cases", documents: "/lawyer/documents",
    "doc-automation": "/lawyer/doc-automation", vault: "/lawyer/vault",
    "doc-analyzer": "/lawyer/documents/analyzer", "review-queue": "/lawyer/documents/review-queue",
    agreements: "/lawyer/agreements", appointments: "/lawyer/appointments", causelist: "/lawyer/causelist",
    caselaw: "/lawyer/caselaw", payments: "/lawyer/payments", clients: "/lawyer/clients",
    "ai-legal": "/lawyer/ai-assistant", "overseas-disputes": "/lawyer/disputes", profile: "/lawyer/profile",
    "bail-checker": "/lawyer/tools/bail", calculators: "/lawyer/tools/calculators", settings: "/lawyer/settings",
};
const pageOfPath = path => Object.keys(PAGE_PATH).find(p => PAGE_PATH[p] === path.replace(/\/+$/, "") ) || null;

export default function App({ initialPage = "dashboard" }) {
    const [isDark, setIsDark] = useState(true);
    const t = isDark ? DARK : LIGHT;
    const [page, setPage] = useState(initialPage);
    useEffect(() => {
        const path = PAGE_PATH[page];
        if (!path || typeof window === "undefined" || window.location.pathname === path) return;
        window.history.pushState({ lawyerPage: page }, "", path);
    }, [page]);
    useEffect(() => {
        const onPop = () => { const p = pageOfPath(window.location.pathname); if (p) setPage(p); };
        window.addEventListener("popstate", onPop);
        return () => window.removeEventListener("popstate", onPop);
    }, []);

    // Onboarding gate. The SERVER decides whether this lawyer has onboarded;
    // localStorage is only a cache so a returning lawyer doesn't flash the wizard
    // while /users/me is in flight.
    useEffect(() => {
        let cancelled = false;

        let cached = null;
        try { cached = localStorage.getItem(ONBOARDED_KEY); } catch {}
        if (cached !== "1") setPage("onboarding");   // optimistic, corrected below

        (async () => {
            const { data, error } = await getMe();
            // Fail OPEN. A network blip must never lock a lawyer out of the app —
            // that was the whole failure mode this gate used to have.
            if (cancelled || error || !data) return;

            const onboarded = isLawyerOnboarded(data);
            try { localStorage.setItem(ONBOARDED_KEY, onboarded ? "1" : "0"); } catch {}

            setPage(prev => {
                if (!onboarded) return "onboarding";
                if (prev !== "onboarding") return prev;
                // Server says they're done but we optimistically showed the wizard —
                // send them where they were actually headed.
                return initialPage === "onboarding" ? "dashboard" : initialPage;
            });
        })();

        return () => { cancelled = true; };
    }, [initialPage]);
    // Document review requests: the Review Queue is listed only once the
    // server confirms the feature is on (a 404 feature_disabled hides it).
    const [reviewQueueOn, setReviewQueueOn] = useState(false);
    useEffect(() => {
        let alive = true;
        listReviewInbox({ limit: 1 }).then(res => {
            if (alive) setReviewQueueOn(Boolean(res && !res.error && res.data));
        }).catch(() => {});
        return () => { alive = false; };
    }, []);
    // How many documents wait for this lawyer's decision: the Document review
    // badge. The server's own count, re-read as the lawyer moves between pages
    // (a decision lowers it). Off, or on any failure, there is no badge.
    const [pendingReviews, setPendingReviews] = useState(0);
    useEffect(() => {
        let alive = true;
        const read = () => reviewQueueV2({ status: "submitted", limit: 1 }).then(res => {
            if (alive) setPendingReviews(Number(res?.data?.counts?.submitted) || 0);
        }).catch(() => {});
        read();
        // A decision on Document review lowers it without a page change.
        window.addEventListener("attorney:review-decided", read);
        return () => { alive = false; window.removeEventListener("attorney:review-decided", read); };
    }, [page]);
    const [collapsed, setCollapsed] = useState(false);
    const [navOpen, setNavOpen] = useState(false);   // mobile sidebar drawer
    const [activeCase, setActiveCaseState] = useState(null);
    const [openCaseId, setOpenCaseId] = useState(null);           // FIX: global workspace state
    const [notifs, setNotifs] = useState([]);
    const [docs, setDocs] = useState({});
    const toggle = () => setIsDark(d => !d);
    const mainRef = useRef(null);

    useEffect(() => {
        const toNotif = (n, unread) => ({
            id: n.id || n._id,
            type: n.type || "info",
            title: n.title || "",
            body: n.body || "",
            payload: n.payload || {},
            route: n.payload?.route || null,
            time: _fmtAgo(n.created_at),
            unread,
        });
        // The server's list, merged over what is shown: local-only notices
        // (this browser's own action results) stay; server rows are replaced.
        const loadAll = () => getNotifications().then(({ data }) => {
            if (!Array.isArray(data)) return;
            setNotifs(p => [...data.map(n => toNotif(n, !n.read)), ...p.filter(x => x.local)]);
        }).catch(() => {});
        loadAll();

        // Live updates. The socket used to be opened once: a server restart, a
        // dropped Wi-Fi or a sleeping laptop closed it for good, and nothing
        // arrived until a manual reload. Now it reconnects with backoff and
        // re-reads the list, so anything sent while it was down is not lost.
        let ws = null;
        let cancelled = false;
        let attempt = 0;
        let retryTimer = null;
        const scheduleRetry = () => {
            if (cancelled) return;
            retryTimer = setTimeout(connect, reconnectDelay(attempt));
            attempt += 1;
        };
        const connect = () => {
            if (cancelled) return;
            openNotificationSocket((msg) => {
                if (msg?.type !== "notification" || !msg.notification) return;
                const n = msg.notification;
                const row = toNotif(n, true);
                setNotifs(p => [row, ...p.filter(x => x.id !== row.id)]);
                // Open pages refresh themselves from this (appointments, cases).
                broadcastNotification(row);
            }).then(sock => {
                if (cancelled) { try { sock?.close(); } catch {} return; }
                if (!sock) { scheduleRetry(); return; }
                ws = sock;
                sock.addEventListener?.("open", () => {
                    if (attempt > 0) loadAll();   // catch up on what was missed
                    attempt = 0;
                });
                sock.addEventListener?.("close", () => { if (ws === sock) { ws = null; scheduleRetry(); } });
            }).catch(scheduleRetry);
        };
        connect();
        return () => {
            cancelled = true;
            clearTimeout(retryTimer);
            try { ws?.close(); } catch {}
        };
    }, []);

    useEffect(() => {
        if (mainRef.current) mainRef.current.scrollTop = 0;
    }, [page]);

    useEffect(() => { injectGS(t); }, [t]);
    // The lawyer app's global styles (`* {margin:0}`, `html {font-size:15px}`,
    // DM Sans on body and controls) leave with it. Left in <head>, they styled
    // every client screen reached afterwards without a full page load.
    useEffect(() => () => {
        for (const id of ["ag-gs", "ag-extra"]) document.getElementById(id)?.remove();
    }, []);

    useEffect(() => {
        const id = "ag-extra"; if (document.getElementById(id)) return;
        const s = document.createElement("style"); s.id = id;
        s.textContent = `@keyframes slideInRight{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}`;
        document.head.appendChild(s);
    }, []);

    const setActiveCase = (id) => { setActiveCaseState(id); };
    // A notice made in this browser (an action's result). It has no server
    // row, so it is marked local and never sent to the server to be "read":
    // its made-up id used to produce a failing request on every click.
    const addNotif = (n) => setNotifs(p => [{ ...n, id: `local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, unread: true, local: true }, ...p]);
    const clearNotif = (id) => {
        const row = notifs.find(n => n.id === id);
        setNotifs(p => p.map(n => n.id === id ? { ...n, unread: false } : n));
        if (row && !row.local) markNotificationRead(id).catch(() => {});
    };
    /** Open what a notification is about: its page, and its case if it has one. */
    const openNotif = (n) => {
        clearNotif(n.id);
        const target = lawyerNotificationTarget(n.type, n.payload);
        if (target) {
            if (target.caseId) setOpenCaseId(target.caseId);
            // A document notification opens THAT document on Document review:
            // read on mount if the page is not open yet, heard live if it is.
            if (target.docId) {
                try { sessionStorage.setItem("attorney:lawyer-open-doc", target.docId); } catch { /* storage off */ }
                window.dispatchEvent(new CustomEvent("attorney:open-review-doc", { detail: target.docId }));
            }
            setPage(target.page);
            return true;
        }
        if (n.route) { window.location.href = n.route; return true; }
        return false;
    };
    const clearAll = () => {
        setNotifs(p => p.map(n => ({ ...n, unread: false })));
        markAllNotificationsRead().catch(() => {});
    };

    // Sidebar badges, from unread SERVER notifications of the real types.
    const unreadMsgs = notifs.filter(n => n.type === "case_message" && n.unread && !n.local).length;
    const unreadAppts = notifs.filter(n => n.type === "appointment_booked" && n.unread && !n.local).length;

    const caseCtxVal = { activeCase, setActiveCase, openCaseId, setOpenCaseId, docs, setDocs, setPage };
    const notifCtxVal = { notifs, addNotif, clearNotif, clearAll, openNotif };

    const Page = pageMap[page] || DashboardPage;
    // Gates only the active-case banner now (off by design). The Topbar it also
    // gated was never shown and has been removed with its inert search box.
    const hideTopbar = true;

    return (
        <ToastContainer theme={t}>
            <ThemeCtx.Provider value={t}><ToggleCtx.Provider value={toggle}>
                <CaseCtx.Provider value={caseCtxVal}><NotifCtx.Provider value={notifCtxVal}>
                    {/* The shell is exactly the window's height and never scrolls
                        itself: only <main> scrolls, so the sidebar stays put the
                        way an app sidebar should. With `minHeight` a long page
                        (Settings) grew the window, the whole document scrolled,
                        and the sidebar went with it. */}
                    <div data-app-shell style={{ display: "flex", height: "100vh", overflow: "hidden", background: t.bg, position: "relative" }}>
                        {/* Gradient mesh background */}
                        <div aria-hidden style={{ position: "absolute", inset: 0, pointerEvents: "none", zIndex: 0, backgroundImage: t.mode === "dark"
                            ? "radial-gradient(ellipse at 15% 12%, rgba(64,240,220,0.08) 0%, transparent 52%), radial-gradient(ellipse at 82% 78%, rgba(64,200,220,0.06) 0%, transparent 48%), radial-gradient(ellipse at 48% 95%, rgba(91,179,255,0.05) 0%, transparent 42%)"
                            : "radial-gradient(ellipse at 15% 12%, rgba(44,96,110,0.07) 0%, transparent 52%), radial-gradient(ellipse at 82% 78%, rgba(44,140,150,0.05) 0%, transparent 48%), radial-gradient(ellipse at 48% 95%, rgba(91,140,212,0.04) 0%, transparent 42%)" }} />
                        {/* Noise texture overlay */}
                        <div aria-hidden style={{ position: "absolute", inset: 0, pointerEvents: "none", zIndex: 0, opacity: t.mode === "dark" ? 0.035 : 0.022, backgroundImage: "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")" }} />
                        {page !== "onboarding" && (
                            <>
                                {/* Mobile hamburger — .lw-burger hides it above 900px */}
                                <button
                                    className="lw-burger"
                                    onClick={() => setNavOpen(true)}
                                    aria-label="Open navigation"
                                    aria-expanded={navOpen}
                                    style={{
                                        position: "fixed", top: 12, left: 12, zIndex: 50,
                                        width: 38, height: 38, borderRadius: 10,
                                        background: t.surface, border: `1px solid ${t.border}`,
                                        color: t.primary, cursor: "pointer",
                                    }}>
                                    <Icon d={I.menu} size={17} />
                                </button>
                                {navOpen && <div className="lw-scrim" onClick={() => setNavOpen(false)} aria-hidden />}
                                <Sidebar page={page} setPage={setPage} collapsed={collapsed} setCollapsed={setCollapsed}
                                    unreadMsgs={unreadMsgs} unreadAppts={unreadAppts} pendingReviews={pendingReviews} toggleTheme={toggle} isDark={isDark}
                                    mobileOpen={navOpen} onNavigate={() => setNavOpen(false)}
                                    reviewQueueOn={reviewQueueOn} />
                            </>
                        )}
                        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0, position: "relative", zIndex: 1 }}>
                            {/* Active case banner — visible on all pages except ai-legal */}
                            {activeCase && !hideTopbar && page !== "ai-legal" && (
                                <ActiveCaseBanner caseId={activeCase} onClear={() => { setActiveCaseState(null); setOpenCaseId(null); }} />
                            )}
                            {/* FIX: removed key={page} — was destroying all page state on every navigation */}
                            <main ref={mainRef} data-lenis-prevent className="page-enter lw-main" style={{ flex: 1, display: "flex", flexDirection: "column", overflow: ["ai-legal", "cases", "doc-automation", "doc-analyzer", "documents", "vault", "onboarding"].includes(page) ? "hidden" : "auto", scrollBehavior: "smooth", padding: ["ai-legal", "cases", "doc-automation", "doc-analyzer", "documents", "vault", "onboarding", "appointments", "bail-checker", "calculators", "profile", "settings", "dashboard"].includes(page) ? 0 : 24 }}>
                                {page === "onboarding"
                                    ? <OnboardingPage t={t} role="lawyer" onComplete={() => {
                                        try { localStorage.setItem(ONBOARDED_KEY, "1"); } catch {}
                                        setPage("dashboard");
                                    }} />
                                    : <Page />
                                }
                            </main>
                        </div>
                    </div>
                </NotifCtx.Provider></CaseCtx.Provider>
            </ToggleCtx.Provider></ThemeCtx.Provider>
        </ToastContainer>
    );
}
