'use client';
import React from "react";
import { useT } from "./theme.js";
import Ic from "./Ic.jsx";
import { Card, Badge } from "@/components/shared/shared.jsx";
import { useCase } from "@/components/shared/CaseContext.jsx";

const STATUS_BADGE = {
  active:      "success",
  in_progress: "success",
  pending:     "warn",
  in_review:   "info",
  closed:      "gray",
  cancelled:   "gray",
};

const STitle = ({ icon, sub, children }) => {
    const t = useT();
    return (
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
            <Ic n={icon} s={18} c={t.primary} />
            <div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>{children}</div>
            {sub && <div style={{ marginLeft: "auto", fontSize: 11, color: t.textMuted }}>{sub}</div>}
        </div>
    );
};

/* ══════════════════════════════════════════════════════
   MODULE: OVERVIEW
══════════════════════════════════════════════════════ */
const ModOverview = () => {
    const t = useT();
    const { cases, appointments } = useCase();

    const activeCasesCount  = cases.length;
    const apptCount         = appointments.length;
    const nextAppt          = appointments[0];
    const nextApptLabel     = nextAppt
        ? new Date(nextAppt.scheduled_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })
        : null;

    const stats = [
        { label: "Active Cases",  val: activeCasesCount || "—", sub: activeCasesCount ? `${activeCasesCount} case${activeCasesCount !== 1 ? "s" : ""} open` : "No cases yet", color: t.primary,  icon: "brief", pct: Math.min(activeCasesCount * 20, 100) || 10 },
        { label: "Pending Docs",  val: "—", sub: "Upload via case",   color: t.info,    icon: "file",  pct: 45 },
        { label: "Appointments",  val: apptCount || "—", sub: nextApptLabel ? `Next: ${nextApptLabel}` : "None scheduled", color: t.success, icon: "cal",   pct: Math.min(apptCount * 25, 100) || 10 },
        { label: "Agreements",    val: "—", sub: "Via lawyer portal",  color: t.warn,    icon: "pen",   pct: 80 },
    ];

    const recentCases = cases.slice(0, 3);
    const upcomingAppts = appointments.slice(0, 3);

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
                {stats.map(({ label, val, sub, color, icon, pct }) => (
                    <Card key={label} style={{ transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
                            <div style={{
                                width: 46, height: 46, borderRadius: 13,
                                background: `${color}25`,
                                display: "flex", alignItems: "center", justifyContent: "center",
                                boxShadow: `0 6px 20px ${color}35`,
                            }}>
                                <Ic n={icon} s={21} c={color} />
                            </div>
                            <span style={{
                                fontSize: 36, fontWeight: 900, color,
                                letterSpacing: "-1px",
                                fontFamily: "'Playfair Display', serif",
                            }}>
                                {val}
                            </span>
                        </div>
                        <div style={{ fontSize: 15, fontWeight: 700, color: t.text, marginBottom: 4 }}>{label}</div>
                        <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 12 }}>{sub}</div>
                        <div style={{ height: 5, background: t.inputBg, borderRadius: 4, overflow: "hidden" }}>
                            <div style={{
                                width: `${pct}%`, height: "100%",
                                background: `linear-gradient(90deg, ${color}, ${color}99)`,
                                borderRadius: 4,
                                transition: "width 0.6s cubic-bezier(0.25, 0.46, 0.45, 0.94)",
                            }} />
                        </div>
                    </Card>
                ))}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 18 }}>
                <Card>
                    <STitle icon="brief" sub="Your latest active cases">Recent Cases</STitle>
                    {recentCases.length > 0 ? recentCases.map(c => {
                        const badgeType = STATUS_BADGE[c.status] || "warn";
                        const filed = c.created_at
                            ? new Date(c.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })
                            : "—";
                        return (
                            <div key={c._id} style={{
                                display: "flex", alignItems: "center", justifyContent: "space-between",
                                padding: "13px 0", borderBottom: `1px solid ${t.border}`,
                            }}>
                                <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                                    <div style={{
                                        width: 40, height: 40, borderRadius: 12,
                                        background: t.primaryGlow,
                                        display: "flex", alignItems: "center", justifyContent: "center",
                                    }}>
                                        <Ic n="brief" s={17} c={t.primary} />
                                    </div>
                                    <div>
                                        <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{c.title}</div>
                                        <div style={{ fontSize: 11, color: t.textMuted }}>{c.case_number || c._id?.slice(-6)} · {filed}</div>
                                    </div>
                                </div>
                                <Badge type={badgeType}>{c.status}</Badge>
                            </div>
                        );
                    }) : (
                        <div style={{ fontSize: 13, color: t.textMuted, padding: "12px 0" }}>No cases yet — complete intake to create your first case.</div>
                    )}
                </Card>

                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                    <Card>
                        <STitle icon="cal" sub="Events & deadlines">Upcoming</STitle>
                        {upcomingAppts.length > 0 ? upcomingAppts.map((a, i) => {
                            const apptDate = new Date(a.scheduled_at);
                            const label = apptDate.toLocaleDateString("en-US", { month: "short", day: "numeric" });
                            const time  = apptDate.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
                            const accentColor = a.mode === "court" ? t.danger : a.mode === "video" ? t.info : t.primary;
                            const title = a.mode === "court" ? "Court Hearing"
                                        : a.mode === "video" ? "Video Meeting"
                                        : a.mode === "in_person" ? "In-Person Meeting"
                                        : "Appointment";
                            return (
                                <div key={a._id || i} style={{ display: "flex", gap: 12, marginBottom: 14, alignItems: "center" }}>
                                    <div style={{
                                        width: 4, borderRadius: 2,
                                        background: accentColor, alignSelf: "stretch",
                                        flexShrink: 0, minHeight: 36,
                                    }} />
                                    <div>
                                        <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{title}</div>
                                        <div style={{ fontSize: 11, color: t.textMuted }}>{label} · {time}</div>
                                    </div>
                                </div>
                            );
                        }) : (
                            <div style={{ fontSize: 13, color: t.textMuted, padding: "12px 0" }}>No upcoming appointments.</div>
                        )}
                    </Card>

                    <Card style={{ background: t.primaryGlow, border: `1px solid ${t.primary}25` }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                            <Ic n="sparkle" s={20} c={t.primary} />
                            <div style={{ fontSize: 13, fontWeight: 700, color: t.primary }}>AI Insight</div>
                        </div>
                        <p style={{ fontSize: 12, color: t.textDim, lineHeight: 1.7 }}>
                            Employment Dispute has a{" "}
                            <strong style={{ color: t.primary }}>78% win probability</strong>{" "}
                            based on evidence &amp; precedents.
                        </p>
                    </Card>
                </div>
            </div>
        </div>
    );
};

export default ModOverview;