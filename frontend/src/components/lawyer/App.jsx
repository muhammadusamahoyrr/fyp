'use client';
// Lawyer App — paste your code here
import { useState, useEffect } from "react";
import { DARK, LIGHT, ThemeCtx, ToggleCtx, CaseCtx, NotifCtx } from "./theme.js";
import { injectGS } from "./globalStyles.js";
import { Sidebar, Topbar, ActiveCaseBanner } from "./layout.jsx";
import { DashboardPage } from "./DashboardPage.jsx";
import { CasesPage } from "./CasesPage.jsx";
import { DocWorkflowApp } from "./DocumentsPage.jsx";
import { AppointmentsPage } from "./AppointmentsPage.jsx";
import { ClientsPage } from "./ClientsPage.jsx";
import { AILegalPage } from "./AILegalPage.jsx";
import { DocAutomationPage } from "./DocAutomationPage.jsx";
import { UploadPage } from "./UploadPage.jsx";
import { CommunicationsPage } from "./CommunicationsPage.jsx";
import { ProfilePage } from "./ProfilePage.jsx";
import { SettingsPage } from "./SettingsPage.jsx";
import { OnboardingPage, ONBOARDED_KEY } from "./OnboardingPage.jsx";
import { seedDocs } from "./data.js";

// LoginPage not yet implemented
const LoginPage = () => null;
const DocumentsPage = DocWorkflowApp;
const pageMap = { dashboard: DashboardPage, cases: CasesPage, documents: DocumentsPage, appointments: AppointmentsPage, clients: ClientsPage, "ai-legal": AILegalPage, "doc-automation": DocAutomationPage, upload: UploadPage, communications: CommunicationsPage, profile: ProfilePage, settings: SettingsPage, onboarding: OnboardingPage };

const SEED_NOTIFS = [
    { id: 1, type: "hearing", title: "Hearing Tomorrow", body: "CS-2024-089 at High Court Mumbai — 10:00 AM", time: "1h ago", unread: true },
    { id: 2, type: "message", title: "New Message from Priya Sharma", body: "Can you explain the court order?", time: "2h ago", unread: true },
    { id: 3, type: "document", title: "Document Approved", body: "Affidavit — Patel Employment marked Final", time: "5h ago", unread: false },
    { id: 4, type: "appointment", title: "Appointment Request", body: "Neha Verma — New Client Consultation", time: "1d ago", unread: false },
];

export default function App({ initialPage = "dashboard" }) {
    const [isDark, setIsDark] = useState(true);
    const t = isDark ? DARK : LIGHT;
    const [page, setPage] = useState(initialPage);

    useEffect(() => {
        try { if (localStorage.getItem(ONBOARDED_KEY) !== "1") setPage("onboarding"); } catch {}
    }, []);
    const [collapsed, setCollapsed] = useState(false);
    const [activeCase, setActiveCaseState] = useState(null);
    const [openCaseId, setOpenCaseId] = useState(null);           // FIX: global workspace state
    const [openCommsClientId, setOpenCommsClientId] = useState(null); // FIX: comms pre-select
    const [notifs, setNotifs] = useState(SEED_NOTIFS);
    const [docs, setDocs] = useState(seedDocs);
    const toggle = () => setIsDark(d => !d);

    useEffect(() => { injectGS(t); }, [t]);

    useEffect(() => {
        const id = "ag-extra"; if (document.getElementById(id)) return;
        const s = document.createElement("style"); s.id = id;
        s.textContent = `@keyframes slideInRight{from{transform:translateX(100%);opacity:0}to{transform:none;opacity:1}}`;
        document.head.appendChild(s);
    }, []);

    const setActiveCase = (id) => { setActiveCaseState(id); };
    const addNotif = (n) => setNotifs(p => [{ id: Date.now(), unread: true, ...n }, ...p]);
    const clearNotif = (id) => setNotifs(p => p.map(n => n.id === id ? { ...n, unread: false } : n));
    const clearAll = () => setNotifs(p => p.map(n => ({ ...n, unread: false })));

    // Unread messages count: drives the sidebar badge dynamically
    const unreadMsgs = notifs.filter(n => n.type === "message" && n.unread).length;

    const caseCtxVal = { activeCase, setActiveCase, openCaseId, setOpenCaseId, openCommsClientId, setOpenCommsClientId, docs, setDocs, setPage };
    const notifCtxVal = { notifs, addNotif, clearNotif, clearAll };

    if (page === "login") return (
        <ThemeCtx.Provider value={t}><ToggleCtx.Provider value={toggle}>
            <CaseCtx.Provider value={caseCtxVal}><NotifCtx.Provider value={notifCtxVal}>
                <LoginPage onLogin={() => {
                    let onboarded = false;
                    try { onboarded = localStorage.getItem(ONBOARDED_KEY) === "1"; } catch { }
                    setPage(onboarded ? "dashboard" : "onboarding");
                }} />
            </NotifCtx.Provider></CaseCtx.Provider>
        </ToggleCtx.Provider></ThemeCtx.Provider>
    );

    const Page = pageMap[page] || DashboardPage;
    const hideTopbar = true;

    return (
        <ThemeCtx.Provider value={t}><ToggleCtx.Provider value={toggle}>
            <CaseCtx.Provider value={caseCtxVal}><NotifCtx.Provider value={notifCtxVal}>
                <div style={{ display: "flex", minHeight: "100vh", background: t.bg }}>
                    {page !== "onboarding" && <Sidebar page={page} setPage={setPage} collapsed={collapsed} setCollapsed={setCollapsed} unreadMsgs={unreadMsgs} toggleTheme={toggle} isDark={isDark} />}
                    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>
                        {!hideTopbar && <Topbar page={page} collapsed={collapsed} setCollapsed={setCollapsed} toggleTheme={toggle} />}
                        {/* Active case banner — visible on all pages except communications/ai-legal */}
                        {activeCase && !hideTopbar && page !== "ai-legal" && (
                            <ActiveCaseBanner caseId={activeCase} onClear={() => { setActiveCaseState(null); setOpenCaseId(null); }} />
                        )}
                        {/* FIX: removed key={page} — was destroying all page state on every navigation */}
                        <main style={{ flex: 1, display: "flex", flexDirection: "column", overflow: ["ai-legal", "communications", "cases", "doc-automation", "onboarding"].includes(page) ? "hidden" : "auto", padding: ["ai-legal", "cases", "doc-automation", "onboarding"].includes(page) ? 0 : 24 }}>
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
    );
}
