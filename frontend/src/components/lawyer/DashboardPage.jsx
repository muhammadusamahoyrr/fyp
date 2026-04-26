'use client';
// Lawyer Dashboard Page — paste your code here
import { useTheme } from "./theme.js";
import { useCase } from "./theme.js";
import { useNotif } from "./theme.js";
import { Card, Badge, Divider } from "./components.jsx";
import { Icon, I } from "./icons.jsx";
import { casesData, CSB } from "./data.js";
import { useState } from "react";

function DashboardPage() {
    const { t } = useTheme();
    const { setActiveCase, setOpenCaseId, setPage } = useCase();
    const { addNotif } = useNotif();
    const stats = [{ l: "Active Cases", v: "24", c: "#3EECD6", ic: "cases", ch: "+3 this month", pg: "cases" }, { l: "Pending Docs", v: "12", c: "#FFBE45", ic: "fileText", ch: "5 need review", pg: "documents" }, { l: "Total Clients", v: "67", c: "#42D4A0", ic: "clients", ch: "+8 this month", pg: "clients" }, { l: "Today's Hearings", v: "4", c: "#4AAFFF", ic: "gavel", ch: "Next in 2h", pg: "appointments" }];
    const events = [{ time: "10:00 AM", title: "Court Hearing — Singh vs. Municipal", color: "#4AAFFF", page: "appointments" }, { time: "12:30 PM", title: "Client Meeting — Priya Sharma", color: "#3EECD6", page: "appointments" }, { time: "2:00 PM", title: "Document Review — Patel Case", color: "#42D4A0", page: "documents" }, { time: "4:30 PM", title: "New Client Consultation", color: "#FFBE45", page: "appointments" }];

    const openCaseFromDashboard = (c) => {
        setActiveCase(c.id);
        setOpenCaseId(c.id);
        setPage("cases");
    };

    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
            <div style={{ flex: 1, overflowY: "auto", padding: 0 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
                    <div className="fade-up"><div className="serif" style={{ fontSize: 24, fontWeight: 700, color: t.text }}>Good morning, John ☀️</div><div style={{ fontSize: 13, color: t.textMuted, marginTop: 3 }}>Here's what's happening across your practice today.</div></div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12 }}>
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
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 290px", gap: 18 }}>
                        <Card className="fade-up s2">
                            <div style={{ padding: "14px 18px 10px", display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: `1px solid ${t.border}` }}>
                                <div className="serif" style={{ fontSize: 16, fontWeight: 600, color: t.text }}>Recent Cases</div>
                                <button onClick={() => setPage("cases")} style={{ fontSize: 12, color: t.primary, background: "none", border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: 4 }}>View all <Icon d={I.arrowRight} size={12} /></button>
                            </div>
                            <table style={{ width: "100%", borderCollapse: "collapse" }}>
                                <thead><tr style={{ fontSize: 11, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.07em" }}>{["Case ID", "Title", "Type", "Status", "Date", ""].map(h => <th key={h} style={{ padding: "10px 16px", textAlign: "left", fontWeight: 700, borderBottom: `1px solid ${t.border}` }}>{h}</th>)}</tr></thead>
                                <tbody>{casesData.slice(0, 4).map(c => (
                                    <tr key={c.id} style={{ borderBottom: `1px solid ${t.border}`, cursor: "pointer" }} onClick={() => openCaseFromDashboard(c)}>
                                        <td style={{ padding: "12px 16px" }}><div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                                            {c.urgent && <Icon d={I.alert} size={13} style={{ color: t.danger }} />}
                                            <span className="mono" style={{ fontSize: 12, color: t.primary, fontWeight: 600 }}>{c.id}</span>
                                        </div></td>
                                        <td style={{ padding: "12px 16px", fontSize: 13, color: t.text, fontWeight: 500 }}>{c.title}</td>
                                        <td style={{ padding: "12px 16px" }}><Badge type="gray">{c.type}</Badge></td>
                                        <td style={{ padding: "12px 16px" }}><Badge type={CSB[c.status]}>{c.status}</Badge></td>
                                        <td style={{ padding: "12px 16px", fontSize: 12, color: t.textMuted }}>{c.nextHearing}</td>
                                        <td style={{ padding: "12px 16px" }}><button style={{ background: "none", border: "none", color: t.textFaint, cursor: "pointer" }}><Icon d={I.more} size={15} /></button></td>
                                    </tr>
                                ))}</tbody>
                            </table>
                        </Card>
                        <Card className="fade-up s3" style={{ padding: 16 }}>
                            <div className="serif" style={{ fontSize: 15, fontWeight: 600, color: t.text, marginBottom: 14 }}>Today's Schedule</div>
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
                            <div style={{ display: "flex", gap: 6 }}>{[{ v: "3", l: "Hearings", c: t.info, pg: "appointments" }, { v: "5", l: "Tasks", c: t.success, pg: "documents" }, { v: "2", l: "Pending", c: t.warn, pg: "cases" }].map(s => (
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
