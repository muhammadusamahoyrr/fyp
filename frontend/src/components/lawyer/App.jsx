'use client';
// Lawyer App — paste your code here
import { useState, useEffect, useRef } from "react";
import { DARK, LIGHT, ThemeCtx, ToggleCtx, CaseCtx, NotifCtx } from "./theme.js";
import { ToastContainer } from "@/components/shared/Toast.jsx";
import { injectGS } from "./globalStyles.js";
import { Sidebar, Topbar, ActiveCaseBanner } from "./layout.jsx";
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
import { ProfilePage } from "./ProfilePage.jsx";
import { SettingsPage } from "./SettingsPage.jsx";
import { DisputesInboxPage } from "./DisputesInboxPage.jsx";
import { OnboardingPage, ONBOARDED_KEY, isLawyerOnboarded } from "./OnboardingPage.jsx";
import { getMe, getNotifications, markNotificationRead, markAllNotificationsRead, openNotificationSocket } from "@/lib/api.js";

// LoginPage not yet implemented
const LoginPage = () => null;
const DocumentsPage = DocWorkflowApp;
const pageMap = { dashboard: DashboardPage, cases: CasesPage, documents: DocumentsPage, appointments: AppointmentsPage, agreements: AgreementsPage, causelist: CauselistPage, caselaw: CaseLawPage, payments: PaymentsPage, clients: ClientsPage, "ai-legal": AILegalPage, "doc-automation": DocAutomationPage, "overseas-disputes": DisputesInboxPage, profile: ProfilePage, settings: SettingsPage, onboarding: OnboardingPage };

const _fmtAgo = (iso) => {
    if (!iso) return "";
    const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    if (mins < 60) return `${mins}m ago`;
    if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
    return `${Math.round(mins / 1440)}d ago`;
};

export default function App({ initialPage = "dashboard" }) {
    const [isDark, setIsDark] = useState(true);
    const t = isDark ? DARK : LIGHT;
    const [page, setPage] = useState(initialPage);

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
    const [collapsed, setCollapsed] = useState(false);
    const [activeCase, setActiveCaseState] = useState(null);
    const [openCaseId, setOpenCaseId] = useState(null);           // FIX: global workspace state
    const [notifs, setNotifs] = useState([]);
    const [docs, setDocs] = useState({});
    const toggle = () => setIsDark(d => !d);
    const mainRef = useRef(null);

    useEffect(() => {
        getNotifications().then(({ data }) => {
            if (!Array.isArray(data)) return;
            setNotifs(data.map(n => ({
                id: n.id || n._id,
                type: n.type || "info",
                title: n.title || "",
                body: n.body || "",
                route: n.payload?.route || null,   // deep-link target for click-through
                time: _fmtAgo(n.created_at),
                unread: !n.read,
            })));
        }).catch(() => {});

        // Live updates — new notifications land without a refresh
        let ws;
        let cancelled = false;
        openNotificationSocket((msg) => {
            if (msg?.type !== "notification" || !msg.notification) return;
            const n = msg.notification;
            const id = n.id || n._id;
            setNotifs(p => [
                { id, type: n.type || "info", title: n.title || "", body: n.body || "", route: n.payload?.route || null, time: _fmtAgo(n.created_at), unread: true },
                ...p.filter(x => x.id !== id),
            ]);
        }).then(sock => {
            if (cancelled) { try { sock?.close(); } catch {} return; }
            ws = sock;
        });
        return () => { cancelled = true; try { ws?.close(); } catch {} };
    }, []);

    useEffect(() => {
        if (mainRef.current) mainRef.current.scrollTop = 0;
    }, [page]);

    useEffect(() => { injectGS(t); }, [t]);

    useEffect(() => {
        const id = "ag-extra"; if (document.getElementById(id)) return;
        const s = document.createElement("style"); s.id = id;
        s.textContent = `@keyframes slideInRight{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}`;
        document.head.appendChild(s);
    }, []);

    const setActiveCase = (id) => { setActiveCaseState(id); };
    const addNotif = (n) => setNotifs(p => [{ id: Date.now(), unread: true, ...n }, ...p]);
    const clearNotif = (id) => {
        setNotifs(p => p.map(n => n.id === id ? { ...n, unread: false } : n));
        markNotificationRead(id).catch(() => {});
    };
    const clearAll = () => {
        setNotifs(p => p.map(n => ({ ...n, unread: false })));
        markAllNotificationsRead().catch(() => {});
    };

    // Unread messages count: drives the sidebar badge dynamically
    const unreadMsgs = notifs.filter(n => n.type === "message" && n.unread).length;

    const caseCtxVal = { activeCase, setActiveCase, openCaseId, setOpenCaseId, docs, setDocs, setPage };
    const notifCtxVal = { notifs, addNotif, clearNotif, clearAll };

    if (page === "login") return (
        <ToastContainer theme={t}>
            <ThemeCtx.Provider value={t}><ToggleCtx.Provider value={toggle}>
                <CaseCtx.Provider value={caseCtxVal}><NotifCtx.Provider value={notifCtxVal}>
                    <LoginPage onLogin={() => {
                        let onboarded = false;
                        try { onboarded = localStorage.getItem(ONBOARDED_KEY) === "1"; } catch { }
                        setPage(onboarded ? "dashboard" : "onboarding");
                    }} />
                </NotifCtx.Provider></CaseCtx.Provider>
            </ToggleCtx.Provider></ThemeCtx.Provider>
        </ToastContainer>
    );

    const Page = pageMap[page] || DashboardPage;
    const hideTopbar = true;

    return (
        <ToastContainer theme={t}>
            <ThemeCtx.Provider value={t}><ToggleCtx.Provider value={toggle}>
                <CaseCtx.Provider value={caseCtxVal}><NotifCtx.Provider value={notifCtxVal}>
                    <div style={{ display: "flex", minHeight: "100vh", background: t.bg, position: "relative" }}>
                        {/* Gradient mesh background */}
                        <div aria-hidden style={{ position: "absolute", inset: 0, pointerEvents: "none", zIndex: 0, backgroundImage: t.mode === "dark"
                            ? "radial-gradient(ellipse at 15% 12%, rgba(64,240,220,0.08) 0%, transparent 52%), radial-gradient(ellipse at 82% 78%, rgba(64,200,220,0.06) 0%, transparent 48%), radial-gradient(ellipse at 48% 95%, rgba(91,179,255,0.05) 0%, transparent 42%)"
                            : "radial-gradient(ellipse at 15% 12%, rgba(44,96,110,0.07) 0%, transparent 52%), radial-gradient(ellipse at 82% 78%, rgba(44,140,150,0.05) 0%, transparent 48%), radial-gradient(ellipse at 48% 95%, rgba(91,140,212,0.04) 0%, transparent 42%)" }} />
                        {/* Noise texture overlay */}
                        <div aria-hidden style={{ position: "absolute", inset: 0, pointerEvents: "none", zIndex: 0, opacity: t.mode === "dark" ? 0.035 : 0.022, backgroundImage: "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")" }} />
                        {page !== "onboarding" && <Sidebar page={page} setPage={setPage} collapsed={collapsed} setCollapsed={setCollapsed} unreadMsgs={unreadMsgs} toggleTheme={toggle} isDark={isDark} />}
                        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0, position: "relative", zIndex: 1 }}>
                            {!hideTopbar && <Topbar page={page} collapsed={collapsed} setCollapsed={setCollapsed} toggleTheme={toggle} />}
                            {/* Active case banner — visible on all pages except ai-legal */}
                            {activeCase && !hideTopbar && page !== "ai-legal" && (
                                <ActiveCaseBanner caseId={activeCase} onClear={() => { setActiveCaseState(null); setOpenCaseId(null); }} />
                            )}
                            {/* FIX: removed key={page} — was destroying all page state on every navigation */}
                            <main ref={mainRef} data-lenis-prevent className="page-enter" style={{ flex: 1, display: "flex", flexDirection: "column", overflow: ["ai-legal", "cases", "doc-automation", "documents", "onboarding"].includes(page) ? "hidden" : "auto", scrollBehavior: "smooth", padding: ["ai-legal", "cases", "doc-automation", "documents", "onboarding"].includes(page) ? 0 : 24 }}>
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
