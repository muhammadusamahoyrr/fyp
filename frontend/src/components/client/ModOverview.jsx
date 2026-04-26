// Paste your ModOverview.jsx code here
import React from "react";
import { useT } from "./theme.js";
import Ic from "./Ic.jsx";
import { Card, Badge } from "@/components/shared/shared.jsx";

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
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
                {[
                    { label: "Active Cases", val: "4", sub: "+1 this week", color: t.primary, icon: "brief", pct: 65 },
                    { label: "Pending Docs", val: "7", sub: "2 need review", color: t.info, icon: "file", pct: 45 },
                    { label: "Appointments", val: "2", sub: "Next: Feb 25", color: t.success, icon: "cal", pct: 30 },
                    { label: "Agreements", val: "3", sub: "1 awaiting sign", color: t.warn, icon: "pen", pct: 80 },
                ].map(({ label, val, sub, color, icon, pct }) => (
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
                    {[
                        { id: "C-001", name: "Employment Dispute", status: "Active", date: "Feb 10", type: "success" },
                        { id: "C-002", name: "Property Settlement", status: "In Review", date: "Feb 15", type: "info" },
                        { id: "C-003", name: "Contract Breach", status: "Pending", date: "Feb 18", type: "warn" },
                    ].map(c => (
                        <div key={c.id} style={{
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
                                    <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{c.name}</div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>{c.id} · {c.date}</div>
                                </div>
                            </div>
                            <Badge type={c.type}>{c.status}</Badge>
                        </div>
                    ))}
                </Card>

                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                    <Card>
                        <STitle icon="cal" sub="Events & deadlines">Upcoming</STitle>
                        {[
                            { ti: "Court Hearing", d: "Feb 25", c: t.danger },
                            { ti: "Lawyer Meeting", d: "Feb 28", c: t.info },
                            { ti: "Doc Deadline", d: "Mar 3", c: t.primary },
                        ].map((e, i) => (
                            <div key={i} style={{ display: "flex", gap: 12, marginBottom: 14, alignItems: "center" }}>
                                <div style={{
                                    width: 4, borderRadius: 2,
                                    background: e.c, alignSelf: "stretch",
                                    flexShrink: 0, minHeight: 36,
                                }} />
                                <div>
                                    <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{e.ti}</div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>{e.d}</div>
                                </div>
                            </div>
                        ))}
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