'use client';
// Lawyer Dashboard Page — paste your code here
import { useTheme } from "./theme.js";
import { useCase } from "./theme.js";
import { useNotif } from "./theme.js";
import { Card, Badge, Divider } from "./components.jsx";
import { Icon, I } from "./icons.jsx";
import { CSB } from "./data.js";
import { useState, useEffect } from "react";
import { useAuth } from "@/context/AuthContext.jsx";
import { listCases, listAppointments } from "@/lib/api.js";

const _STAT_MAP = { open: "Filed", active: "Under Hearing", closed: "Closed", dismissed: "Closed" };
function _mapCase(c) {
    return {
        id: c.case_number || c._id,
        _id: c._id,
        title: c.title || "Untitled Case",
        client: c.client_name || "—",
        court: c.province || "—",
        type: c.case_type ? c.case_type.charAt(0).toUpperCase() + c.case_type.slice(1) : "Other",
        status: _STAT_MAP[c.status] || "Filed",
        nextHearing: "",
        urgent: c.urgency === "high",
    };
}

function DashboardPage() {
    const { t } = useTheme();
    const { setActiveCase, setOpenCaseId, setPage } = useCase();
    const { addNotif } = useNotif();
    const { user } = useAuth();
    const [rawCases, setRawCases] = useState([]);
    const [aptCount, setAptCount] = useState(0);
    const [appts, setAppts] = useState([]);

    useEffect(() => {
        listCases({ page_size: 50 }).then(({ data }) => { if (data?.items) setRawCases(data.items); });
        listAppointments({ page_size: 50 }).then(({ data }) => {
            if (!data?.items) return;
            const live = data.items.filter(a => a.status === "confirmed" || a.status === "pending");
            setAptCount(live.length);
            setAppts(live);
        });
    }, []);

    const displayCases = rawCases.slice(0, 4).map(_mapCase);
    const greetName = user?.full_name?.split(" ")[0] || "Counselor";
    const activeCnt = rawCases.filter(c => ["open", "active"].includes(c.status)).length;
    const clientCnt = new Set(rawCases.map(c => c.client_id).filter(Boolean)).size;

    const stats = [
        { l: "Active Cases", v: rawCases.length ? String(activeCnt) : "—", c: "#3EECD6", ic: "cases", ch: "Assigned to you", pg: "cases" },
        { l: "Pending Docs", v: "—", c: "#FFBE45", ic: "fileText", ch: "See documents", pg: "documents" },
        { l: "Total Clients", v: rawCases.length ? String(clientCnt) : "—", c: "#42D4A0", ic: "clients", ch: "Across all cases", pg: "clients" },
        { l: "Appointments", v: String(aptCount), c: "#4AAFFF", ic: "gavel", ch: "Pending + Confirmed", pg: "appointments" },
    ];
    // Today's real appointments. This used to be four hardcoded entries —
    // "Court Hearing 10:00 AM", "Client Meeting 12:30 PM" and so on — shown to
    // a lawyer as their actual agenda. A fabricated schedule in a legal product
    // is something a user can plan a day around.
    const _today = new Date().toDateString();
    const events = appts
        .filter(a => a.scheduled_at && new Date(a.scheduled_at).toDateString() === _today)
        .sort((a, b) => new Date(a.scheduled_at) - new Date(b.scheduled_at))
        .map(a => ({
            time: new Date(a.scheduled_at).toLocaleTimeString("en-PK", { hour: "numeric", minute: "2-digit" }),
            title: a.client_name ? `Consultation — ${a.client_name}` : "Consultation",
            color: a.status === "confirmed" ? "#3EECD6" : "#FFBE45",
            page: "appointments",
        }));

    const openCaseFromDashboard = (c) => {
        setActiveCase(c.id);
        setOpenCaseId(c.id);
        setPage("cases");
    };

    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
            <div style={{ flex: 1, overflowY: "auto", padding: 0 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
                    <div className="fade-up"><div className="serif" style={{ fontSize: 24, fontWeight: 700, color: t.text }}>Good morning, {greetName} ☀️</div><div style={{ fontSize: 13, color: t.textMuted, marginTop: 3 }}>Here's what's happening across your practice today.</div></div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
                        {stats.map((s, i) => (
                            <Card key={s.l} className={`fade-up s${i + 1}`} style={{ padding: 16, cursor: "pointer" }} onClick={() => setPage(s.pg)}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                                    <div><div style={{ fontSize: 12, color: t.textMuted, marginBottom: 7, textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 700 }}>{s.l}</div>
                                        <div style={{ fontSize: 28, fontWeight: 700, color: t.text, lineHeight: 1 }}>{s.v}</div>
                                        <div style={{ fontSize: 12, color: t.textFaint, marginTop: 6 }}>{s.ch}</div></div>
                                    <div style={{ width: 40, height: 40, borderRadius: 11, background: `${s.c}18`, display: "flex", alignItems: "center", justifyContent: "center" }}><Icon d={I[s.ic]} size={18} style={{ color: s.c }} /></div>
                                </div>
                                <div style={{ marginTop: 12, height: 2, borderRadius: 2, background: t.border }}><div style={{ height: "100%", borderRadius: 2, background: s.c, width: `${40 + i * 13}%` }} /></div>
                            </Card>
                        ))}
                    </div>
                    <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "1fr 290px", gap: 18 }}>
                        <Card className="fade-up s2">
                            <div style={{ padding: "14px 18px 10px", display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: `1px solid ${t.border}` }}>
                                <div className="serif" style={{ fontSize: 16, fontWeight: 600, color: t.text }}>Recent Cases</div>
                                <button onClick={() => setPage("cases")} style={{ fontSize: 12, color: t.primary, background: "none", border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: 4 }}>View all <Icon d={I.arrowRight} size={12} /></button>
                            </div>
                            <table style={{ width: "100%", borderCollapse: "collapse" }}>
                                <thead><tr style={{ fontSize: 11, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.07em" }}>{["Case ID", "Title", "Type", "Status", "Date", ""].map(h => <th key={h} style={{ padding: "10px 16px", textAlign: "left", fontWeight: 700, borderBottom: `1px solid ${t.border}` }}>{h}</th>)}</tr></thead>
                                <tbody>
                                {displayCases.map(c => (
                                    <tr key={c.id} style={{ borderBottom: `1px solid ${t.border}`, cursor: "pointer" }} onClick={() => openCaseFromDashboard(c)}>
                                        <td style={{ padding: "12px 16px" }}><div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                                            {c.urgent && <Icon d={I.alert} size={13} style={{ color: t.danger }} />}
                                            <span className="mono" style={{ fontSize: 12, color: t.primary, fontWeight: 600 }}>{c.id}</span>
                                        </div></td>
                                        <td style={{ padding: "12px 16px", fontSize: 13, color: t.text, fontWeight: 500 }}>{c.title}</td>
                                        <td style={{ padding: "12px 16px" }}><Badge type="gray">{c.type}</Badge></td>
                                        <td style={{ padding: "12px 16px" }}><Badge type={CSB[c.status]}>{c.status}</Badge></td>
                                        <td style={{ padding: "12px 16px", fontSize: 12, color: t.textMuted }}>{c.nextHearing || "—"}</td>
                                        <td style={{ padding: "12px 16px" }}><button style={{ background: "none", border: "none", color: t.textFaint, cursor: "pointer" }}><Icon d={I.more} size={15} /></button></td>
                                    </tr>
                                ))}
                                {!displayCases.length && (
                                    <tr><td colSpan={6} style={{ padding: "32px 16px", textAlign: "center", fontSize: 13, color: t.textMuted }}>No cases assigned yet</td></tr>
                                )}
                            </tbody>
                            </table>
                        </Card>
                        <Card className="fade-up s3" style={{ padding: 16 }}>
                            <div className="serif" style={{ fontSize: 15, fontWeight: 600, color: t.text, marginBottom: 14 }}>Today's Schedule</div>
                            {!events.length && (
                                <div style={{ padding: "18px 4px", fontSize: 12.5, color: t.textMuted }}>
                                    Nothing scheduled today.
                                </div>
                            )}
                            {events.map((ev, i) => (
                                <div key={ev.time} style={{ display: "flex", gap: 10, cursor: "pointer" }} onClick={() => setPage(ev.page)}>
                                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                                        <div style={{ width: 8, height: 8, borderRadius: "50%", background: ev.color, marginTop: 3, flexShrink: 0 }} />
                                        {i < events.length - 1 && <div style={{ width: 1, flex: 1, background: t.border, margin: "2px 0" }} />}
                                    </div>
                                    <div style={{ paddingBottom: i < events.length - 1 ? 13 : 0 }}>
                                        <div style={{ fontSize: 11, color: t.textFaint, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em" }}>{ev.time}</div>
                                        <div style={{ fontSize: 13, color: t.textDim, marginTop: 3, lineHeight: 1.4 }}>{ev.title}</div>
                                    </div>
                                </div>
                            ))}
                            <Divider />
                            <div style={{ display: "flex", gap: 6 }}>{[
                                { v: String(events.length), l: "Today", c: t.info, pg: "appointments" },
                                { v: String(aptCount), l: "Upcoming", c: t.success, pg: "appointments" },
                                { v: String(activeCnt), l: "Active cases", c: t.warn, pg: "cases" },
                            ].map(s => (
                                <div key={s.l} onClick={() => setPage(s.pg)} style={{ flex: 1, padding: "9px 6px", borderRadius: 9, background: t.primaryGlow2, border: `1px solid ${t.border}`, textAlign: "center", cursor: "pointer" }}>
                                    <div className="mono" style={{ fontSize: 17, fontWeight: 700, color: s.c }}>{s.v}</div>
                                    <div style={{ fontSize: 11, color: t.textMuted, marginTop: 3 }}>{s.l}</div>
                                </div>
                            ))}</div>
                        </Card>
                    </div>
                </div>
            </div>
        </div>
    );
}
export { DashboardPage };
