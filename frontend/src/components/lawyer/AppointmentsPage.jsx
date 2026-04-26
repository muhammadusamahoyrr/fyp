'use client';
// Lawyer Appointments Page — paste your code here
import { useState } from "react";
import { useTheme } from "./theme.js";
import { useNotif } from "./theme.js";
import { Card, Btn, Input, Sel } from "./components.jsx";
import { Icon, I } from "./icons.jsx";
import { APSB, aptDataInitial } from "./data.js";

// ============================================================
// APPOINTMENTS PAGE
// ============================================================

const CAL_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const CAL_DATES = [27, 28, 29, 30, 31, 1, 2];
const CAL_HOURS = ["9:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00"];
const calAppts = [
    { day: 4, hour: "9:00", client: "Rajesh Singh", purpose: "Case Review", type: "gavel" },
    { day: 1, hour: "10:00", client: "Rajesh Singh", purpose: "Case Review", type: "gavel" },
    { day: 2, hour: "10:00", client: "Priya Sharma", purpose: "Property Dispute", type: "video" },
    { day: 4, hour: "10:00", client: "Amit Patel", purpose: "Employment St...", type: "video" },
    { day: 0, hour: "11:00", client: "Priya Sharma", purpose: "Property Dispute", type: "gavel" },
    { day: 1, hour: "11:00", client: "Rajesh Singh", purpose: "Case Review", type: "gavel" },
    { day: 0, hour: "12:00", client: "Amit Patel", purpose: "Case Review", type: "gavel" },
    { day: 1, hour: "12:00", client: "Amit Patel", purpose: "Employment Strategy", type: "video" },
    { day: 4, hour: "12:00", client: "Neha Verma", purpose: "Property Dispute", type: "gavel" },
    { day: 0, hour: "13:00", client: "Vikram Kumar", purpose: "Employment Strategy", type: "video" },
];

// ── Status badge styles — high contrast, clearly visible ─────
const STATUS_STYLES = {
    Upcoming: { bg: "rgba(56,216,196,0.18)", color: "#38d8c4", border: "rgba(56,216,196,0.55)", dot: "#38d8c4" },
    Pending: { bg: "rgba(232,184,75,0.18)", color: "#e8b84b", border: "rgba(232,184,75,0.55)", dot: "#e8b84b" },
    Completed: { bg: "rgba(62,201,154,0.18)", color: "#3ec99a", border: "rgba(62,201,154,0.55)", dot: "#3ec99a" },
    Cancelled: { bg: "rgba(232,82,106,0.18)", color: "#e8526a", border: "rgba(232,82,106,0.55)", dot: "#e8526a" },
};

function StatusBadge({ status }) {
    const s = STATUS_STYLES[status] || STATUS_STYLES.Upcoming;
    return (
        <span style={{
            display: "inline-flex", alignItems: "center", gap: 5,
            padding: "4px 11px", borderRadius: 999,
            background: s.bg, color: s.color,
            border: `1.5px solid ${s.border}`,
            fontSize: 11.5, fontWeight: 700, whiteSpace: "nowrap",
            boxShadow: `0 0 8px ${s.dot}30`,
        }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: s.dot, flexShrink: 0, boxShadow: `0 0 4px ${s.dot}` }} />
            {status}
        </span>
    );
}

// ── Stat card ─────────────────────────────────────────────────
function StatCard({ label, value, color, bg, border }) {
    return (
        <div style={{
            padding: "16px 20px", borderRadius: 14,
            background: bg, border: `1.5px solid ${border}`,
            display: "flex", justifyContent: "space-between", alignItems: "center",
            transition: "transform .15s", cursor: "pointer",
        }}
            onMouseEnter={e => e.currentTarget.style.transform = "translateY(-2px)"}
            onMouseLeave={e => e.currentTarget.style.transform = "translateY(0)"}
        >
            <span style={{ fontSize: 13, color: "rgba(190,215,225,0.8)", fontWeight: 500 }}>{label}</span>
            <span style={{ fontSize: 26, fontWeight: 700, color }}>{value}</span>
        </div>
    );
}

// ── Join Call modal ───────────────────────────────────────────
function JoinCallModal({ apt, onClose, t }) {
    return (
        <div style={{ position: "fixed", inset: 0, zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.65)" }} onClick={onClose}>
            <div onClick={e => e.stopPropagation()} style={{
                background: t.card, border: `1px solid ${t.primary}40`,
                borderRadius: 18, padding: 30, width: 400,
                boxShadow: `0 20px 60px rgba(0,0,0,0.4), 0 0 0 1px ${t.primary}20`,
            }}>
                {/* Header */}
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
                    <div style={{
                        width: 44, height: 44, borderRadius: 12,
                        background: `${t.primary}20`, border: `1.5px solid ${t.primary}50`,
                        display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20,
                    }}>📹</div>
                    <div>
                        <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Join Video Call</div>
                        <div style={{ fontSize: 12, color: t.textMuted }}>with {apt.client}</div>
                    </div>
                    <button onClick={onClose} style={{ marginLeft: "auto", background: "none", border: "none", color: t.textMuted, cursor: "pointer", fontSize: 18 }}>✕</button>
                </div>

                {/* Meeting info */}
                <div style={{ background: t.cardHi, borderRadius: 12, padding: "14px 16px", marginBottom: 18 }}>
                    {[
                        ["📋 Purpose", apt.purpose],
                        ["📅 Date", apt.date],
                        ["⏰ Time", `${apt.time} · ${apt.duration}`],
                        ["🔗 Platform", "Zoom / Google Meet"],
                    ].map(([k, v]) => (
                        <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: `1px solid ${t.border}20` }}>
                            <span style={{ fontSize: 12, color: t.textFaint }}>{k}</span>
                            <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>{v}</span>
                        </div>
                    ))}
                </div>

                {/* Meeting link */}
                <div style={{
                    display: "flex", alignItems: "center", gap: 8, padding: "10px 14px",
                    borderRadius: 10, background: `${t.primary}10`, border: `1px solid ${t.primary}30`,
                    marginBottom: 18,
                }}>
                    <span style={{ fontSize: 12, color: t.primary, fontFamily: "monospace", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        https://meet.attorney.ai/room/{apt.id}-{apt.client.split(" ")[0].toLowerCase()}
                    </span>
                    <button style={{
                        padding: "4px 10px", borderRadius: 7, border: "none",
                        background: t.primary, color: t.mode === "dark" ? "#0b1c22" : "#fff",
                        fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                    }}>Copy</button>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    <button onClick={onClose} style={{
                        padding: "10px", borderRadius: 10, border: `1px solid ${t.border}`,
                        background: "transparent", color: t.textMuted,
                        fontSize: 13, fontWeight: 600, fontFamily: "inherit", cursor: "pointer",
                    }}>Cancel</button>
                    <button style={{
                        padding: "10px", borderRadius: 10, border: "none",
                        background: `linear-gradient(135deg,${t.primary},#22a898)`,
                        color: t.mode === "dark" ? "#0b1c22" : "#fff",
                        fontSize: 13, fontWeight: 700, fontFamily: "inherit", cursor: "pointer",
                        boxShadow: `0 4px 14px ${t.primary}50`,
                    }}>📹 Launch Call</button>
                </div>
            </div>
        </div>
    );
}

// ── Schedule / New Appointment modal ─────────────────────────
function ScheduleModal({ apt, onClose, onConfirm, t }) {
    const isNew = !apt;
    const [form, setForm] = useState({
        client: apt?.client || "",
        purpose: apt?.purpose || "",
        date: apt?.date || "",
        time: apt?.time || "",
        duration: apt?.duration || "30 min",
        type: apt?.type || "In-Person",
    });
    const f = (k) => (v) => setForm(prev => ({ ...prev, [k]: v }));

    const Field = ({ label, children }) => (
        <div style={{ marginBottom: 14 }}>
            <label style={{ fontSize: 11, fontWeight: 700, color: "rgba(180,210,225,0.7)", textTransform: "uppercase", letterSpacing: "0.07em", display: "block", marginBottom: 6 }}>{label}</label>
            {children}
        </div>
    );
    const inp = {
        width: "100%", padding: "9px 12px", borderRadius: 9,
        border: `1px solid ${t.border}`, background: t.cardHi,
        color: t.text, fontSize: 13, outline: "none",
        boxSizing: "border-box", fontFamily: "inherit",
        transition: "border-color .15s",
    };

    return (
        <div style={{ position: "fixed", inset: 0, zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.65)" }} onClick={onClose}>
            <div onClick={e => e.stopPropagation()} style={{
                background: t.card, border: `1px solid ${t.primary}35`,
                borderRadius: 18, padding: 28, width: 420,
                boxShadow: `0 20px 60px rgba(0,0,0,0.4)`,
            }}>
                {/* Header */}
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
                    <div style={{
                        width: 38, height: 38, borderRadius: 10,
                        background: `${t.primary}18`, border: `1.5px solid ${t.primary}45`,
                        display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18,
                    }}>{isNew ? "📅" : "🕐"}</div>
                    <div>
                        <div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>
                            {isNew ? "Schedule New Appointment" : "Reschedule Appointment"}
                        </div>
                        <div style={{ fontSize: 11, color: t.textMuted }}>
                            {isNew ? "Book a new consultation" : `Update time for ${apt.client}`}
                        </div>
                    </div>
                    <button onClick={onClose} style={{ marginLeft: "auto", background: "none", border: "none", color: t.textMuted, cursor: "pointer", fontSize: 18 }}>✕</button>
                </div>

                {isNew && (
                    <>
                        <Field label="Client Name">
                            <input value={form.client} onChange={e => f("client")(e.target.value)}
                                placeholder="e.g. Rajesh Singh" style={inp}
                                onFocus={e => e.target.style.borderColor = t.primary}
                                onBlur={e => e.target.style.borderColor = t.border} />
                        </Field>
                        <Field label="Purpose / Case">
                            <input value={form.purpose} onChange={e => f("purpose")(e.target.value)}
                                placeholder="e.g. Property Dispute Consultation" style={inp}
                                onFocus={e => e.target.style.borderColor = t.primary}
                                onBlur={e => e.target.style.borderColor = t.border} />
                        </Field>
                    </>
                )}

                {!isNew && (
                    <div style={{
                        padding: "10px 14px", borderRadius: 10, marginBottom: 14,
                        background: `${t.primary}10`, border: `1px solid ${t.primary}25`,
                    }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>{apt.purpose}</div>
                        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>with {apt.client}</div>
                    </div>
                )}

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    <Field label="Date">
                        <input value={form.date} onChange={e => f("date")(e.target.value)}
                            placeholder="Mar 15, 2026" style={inp}
                            onFocus={e => e.target.style.borderColor = t.primary}
                            onBlur={e => e.target.style.borderColor = t.border} />
                    </Field>
                    <Field label="Time">
                        <input value={form.time} onChange={e => f("time")(e.target.value)}
                            placeholder="10:00 AM" style={inp}
                            onFocus={e => e.target.style.borderColor = t.primary}
                            onBlur={e => e.target.style.borderColor = t.border} />
                    </Field>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    <Field label="Duration">
                        <select value={form.duration} onChange={e => f("duration")(e.target.value)} style={{ ...inp, cursor: "pointer" }}>
                            {["30 min", "45 min", "60 min", "90 min"].map(d => <option key={d}>{d}</option>)}
                        </select>
                    </Field>
                    <Field label="Meeting Type">
                        <select value={form.type} onChange={e => f("type")(e.target.value)} style={{ ...inp, cursor: "pointer" }}>
                            {["In-Person", "Video Call", "Phone Call"].map(tp => <option key={tp}>{tp}</option>)}
                        </select>
                    </Field>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 6 }}>
                    <button onClick={onClose} style={{
                        padding: "10px", borderRadius: 10,
                        border: `1px solid ${t.border}`, background: "transparent",
                        color: t.textMuted, fontSize: 13, fontWeight: 600,
                        fontFamily: "inherit", cursor: "pointer",
                    }}>Cancel</button>
                    <button onClick={() => onConfirm(form)} style={{
                        padding: "10px", borderRadius: 10, border: "none",
                        background: `linear-gradient(135deg,${t.primary},#22a898)`,
                        color: t.mode === "dark" ? "#0b1c22" : "#fff",
                        fontSize: 13, fontWeight: 700, fontFamily: "inherit", cursor: "pointer",
                        boxShadow: `0 4px 14px ${t.primary}50`,
                    }}>✓ {isNew ? "Book Appointment" : "Confirm Reschedule"}</button>
                </div>
            </div>
        </div>
    );
}

// ── Main page ─────────────────────────────────────────────────
function AppointmentsPage() {
    const { t } = useTheme();
    const { addNotif } = useNotif();
    const [viewMode, setViewMode] = useState("list");
    const [statusF, setStatusF] = useState("All");
    const [search, setSearch] = useState("");
    const [appointments, setAppointments] = useState(aptDataInitial);
    const [scheduleModal, setScheduleModal] = useState(undefined); // undefined=closed, null=new, apt=reschedule
    const [joinModal, setJoinModal] = useState(null);
    const tabs = ["All", "Upcoming", "Pending", "Completed", "Cancelled"];

    const filtered = appointments.filter(a =>
        (statusF === "All" || a.status === statusF) &&
        (a.client.toLowerCase().includes(search.toLowerCase()) ||
            a.purpose.toLowerCase().includes(search.toLowerCase()))
    );

    const handleAccept = (id) => {
        setAppointments(prev => prev.map(a => a.id === id ? { ...a, status: "Upcoming" } : a));
        const apt = appointments.find(a => a.id === id);
        addNotif({ type: "appointment", title: "Appointment Accepted", body: `Accepted appointment with ${apt?.client}`, time: "Just now" });
    };
    const handleReject = (id) => {
        setAppointments(prev => prev.map(a => a.id === id ? { ...a, status: "Cancelled" } : a));
        const apt = appointments.find(a => a.id === id);
        addNotif({ type: "appointment", title: "Appointment Rejected", body: `Rejected with ${apt?.client}`, time: "Just now" });
    };
    const confirmSchedule = (form) => {
        if (scheduleModal === null) {
            // New appointment
            const newApt = {
                id: Date.now(), client: form.client, purpose: form.purpose,
                date: form.date, time: form.time, duration: form.duration,
                type: form.type, status: "Upcoming",
                initials: form.client.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase(),
            };
            setAppointments(prev => [newApt, ...prev]);
            addNotif({ type: "appointment", title: "Appointment Booked", body: `Booked ${form.client} for ${form.date}`, time: "Just now" });
        } else {
            setAppointments(prev => prev.map(a => a.id === scheduleModal.id
                ? { ...a, date: form.date, time: form.time, duration: form.duration, type: form.type, status: "Upcoming" } : a));
            addNotif({ type: "appointment", title: "Rescheduled", body: `${scheduleModal.client} → ${form.date} ${form.time}`, time: "Just now" });
        }
        setScheduleModal(undefined);
    };

    const statCounts = {
        today: appointments.filter(a => a.status === "Upcoming" && a.date === "Mar 11, 2026").length || 4,
        upcoming: appointments.filter(a => a.status === "Upcoming").length,
        pending: appointments.filter(a => a.status === "Pending").length,
        completed: appointments.filter(a => a.status === "Completed").length,
    };

    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
            <div style={{ flex: 1, overflowY: "auto" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

                    {/* ── Modals ──────────────────────────────────── */}
                    {scheduleModal !== undefined && (
                        <ScheduleModal
                            apt={scheduleModal}
                            onClose={() => setScheduleModal(undefined)}
                            onConfirm={confirmSchedule}
                            t={t}
                        />
                    )}
                    {joinModal && (
                        <JoinCallModal apt={joinModal} onClose={() => setJoinModal(null)} t={t} />
                    )}

                    {/* ── Header ──────────────────────────────────── */}
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div>
                            <div style={{ fontSize: 22, fontWeight: 700, color: t.text, fontFamily: "Georgia,serif" }}>Appointments</div>
                            <div style={{ fontSize: 13, color: t.textMuted, marginTop: 3 }}>Manage consultations and client meetings</div>
                        </div>
                        {/* Schedule button — opens new appointment modal */}
                        <button
                            onClick={() => setScheduleModal(null)}
                            style={{
                                display: "inline-flex", alignItems: "center", gap: 8,
                                padding: "10px 22px", borderRadius: 12, border: "none",
                                background: `linear-gradient(135deg,${t.primary},#22a898)`,
                                color: t.mode === "dark" ? "#0b1c22" : "#fff",
                                fontSize: 13.5, fontWeight: 700, fontFamily: "inherit", cursor: "pointer",
                                boxShadow: `0 4px 16px ${t.primary}50`,
                                transition: "opacity .15s, transform .15s",
                            }}
                            onMouseEnter={e => { e.currentTarget.style.opacity = "0.88"; e.currentTarget.style.transform = "translateY(-1px)"; }}
                            onMouseLeave={e => { e.currentTarget.style.opacity = "1"; e.currentTarget.style.transform = "translateY(0)"; }}
                        >
                            + Schedule
                        </button>
                    </div>

                    {/* ── Enhanced Filter row ──────────────────────────────── */}
                    <div style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: 16,
                        padding: "12px 16px",
                        background: `${t.cardHi}`,
                        borderRadius: 12,
                        border: `1px solid ${t.border}`,
                        flexWrap: "wrap"
                    }}>
                        {/* Left side - Search and Status together */}
                        <div style={{ display: "flex", gap: 12, alignItems: "center", flex: 1, minWidth: 0 }}>
                            <div style={{ position: "relative", flex: 1, maxWidth: 280 }}>
                                <span style={{
                                    position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)",
                                    fontSize: 13, color: t.textMuted, pointerEvents: "none", zIndex: 1
                                }}>
                                    <Icon d={I.search} size={13} />
                                </span>
                                <input
                                    value={search}
                                    onChange={e => setSearch(e.target.value)}
                                    placeholder="Search appointments, clients, or cases..."
                                    style={{
                                        width: "100%", height: 38,
                                        paddingLeft: 36, paddingRight: 14,
                                        borderRadius: 8,
                                        border: `1.5px solid ${t.border}`,
                                        background: t.card,
                                        color: t.text,
                                        fontSize: 12.5,
                                        outline: "none",
                                        fontFamily: "inherit",
                                        transition: "border-color .15s",
                                        boxSizing: "border-box"
                                    }}
                                    onFocus={e => e.target.style.borderColor = t.primary}
                                    onBlur={e => e.target.style.borderColor = t.border}
                                />
                            </div>

                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <span style={{ fontSize: 12, color: t.textMuted, fontWeight: 500, whiteSpace: "nowrap" }}>Status:</span>
                                <select
                                    value={statusF}
                                    onChange={e => setStatusF(e.target.value)}
                                    style={{
                                        height: 38,
                                        padding: "0 12px",
                                        borderRadius: 8,
                                        border: `1.5px solid ${t.border}`,
                                        background: t.card,
                                        color: t.text,
                                        fontSize: 12.5,
                                        cursor: "pointer",
                                        fontFamily: "inherit",
                                        outline: "none",
                                        minWidth: 140,
                                        transition: "border-color .15s"
                                    }}
                                    onFocus={e => e.target.style.borderColor = t.primary}
                                    onBlur={e => e.target.style.borderColor = t.border}
                                >
                                    {tabs.map(s => <option key={s} value={s}>{s === "All" ? "All Status" : s}</option>)}
                                </select>
                            </div>
                        </div>

                        {/* Right side - View toggle */}
                        <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
                            <span style={{ fontSize: 12, color: t.textMuted, fontWeight: 500, whiteSpace: "nowrap" }}>View:</span>
                            <div style={{ display: "flex", background: t.card, borderRadius: 8, border: `1.5px solid ${t.border}`, padding: 2 }}>
                                {["list", "calendar"].map(v => (
                                    <button
                                        key={v}
                                        onClick={() => setViewMode(v)}
                                        style={{
                                            padding: "6px 12px",
                                            border: "none",
                                            background: viewMode === v ? t.primary : "transparent",
                                            color: viewMode === v ? (t.mode === "dark" ? "#0b1c22" : "#fff") : t.textMuted,
                                            cursor: "pointer",
                                            fontSize: 12,
                                            fontWeight: viewMode === v ? 600 : 500,
                                            borderRadius: 6,
                                            transition: "all .15s",
                                            fontFamily: "inherit",
                                            whiteSpace: "nowrap"
                                        }}
                                        onMouseEnter={e => {
                                            if (!viewMode === v) {
                                                e.currentTarget.style.background = `${t.primary}15`;
                                                e.currentTarget.style.color = t.primary;
                                            }
                                        }}
                                        onMouseLeave={e => {
                                            if (!viewMode === v) {
                                                e.currentTarget.style.background = "transparent";
                                                e.currentTarget.style.color = t.textMuted;
                                            }
                                        }}
                                    >
                                        {v.charAt(0).toUpperCase() + v.slice(1)}
                                        {v === "list" ? " 📋" : " 📅"}
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>

                    {viewMode === "list" ? (
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 260px", gap: 18 }}>
                            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

                                {/* ── Stat cards ──────────────────────── */}
                                <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10 }}>
                                    <StatCard label="Today" value={statCounts.today} color="#38d8c4" bg="rgba(56,216,196,0.12)" border="rgba(56,216,196,0.30)" />
                                    <StatCard label="Upcoming" value={statCounts.upcoming} color="#5ab3ff" bg="rgba(90,179,255,0.12)" border="rgba(90,179,255,0.30)" />
                                    <StatCard label="Pending" value={statCounts.pending} color="#e8b84b" bg="rgba(232,184,75,0.12)" border="rgba(232,184,75,0.30)" />
                                    <StatCard label="Completed" value={statCounts.completed} color="#3ec99a" bg="rgba(62,201,154,0.12)" border="rgba(62,201,154,0.30)" />
                                </div>

                                {/* ── Filter tabs ─────────────────────── */}
                                <div style={{ display: "flex", gap: 4, padding: "6px 0", borderTop: `1px solid ${t.border}`, borderBottom: `1px solid ${t.border}` }}>
                                    {tabs.map(tab => (
                                        <button key={tab} onClick={() => setStatusF(tab)} style={{
                                            padding: "5px 14px", borderRadius: 8, border: "none", cursor: "pointer",
                                            fontSize: 12, fontWeight: 600, fontFamily: "inherit",
                                            background: statusF === tab ? t.primaryGlow : "transparent",
                                            color: statusF === tab ? t.primary : t.textMuted,
                                            transition: "all .15s",
                                        }}>
                                            {tab}
                                            {tab !== "All" && (
                                                <span style={{
                                                    marginLeft: 5, fontSize: 10, padding: "1px 5px", borderRadius: 6,
                                                    background: statusF === tab ? `${t.primary}22` : t.cardHi,
                                                    color: statusF === tab ? t.primary : t.textFaint,
                                                }}>
                                                    {appointments.filter(a => a.status === tab).length}
                                                </span>
                                            )}
                                        </button>
                                    ))}
                                </div>

                                {/* ── Appointment cards ───────────────── */}
                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                                    {filtered.map(apt => (
                                        <Card key={apt.id} style={{ padding: 16 }}>
                                            {/* Card header */}
                                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
                                                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                                                    <div style={{
                                                        width: 40, height: 40, borderRadius: 11,
                                                        background: t.primaryGlow2,
                                                        display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                                                    }}>
                                                        <Icon d={I.user} size={16} style={{ color: t.primary }} />
                                                    </div>
                                                    <div>
                                                        <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>{apt.client}</div>
                                                        <div style={{ fontSize: 12, color: t.textMuted, marginTop: 1 }}>{apt.purpose}</div>
                                                    </div>
                                                </div>
                                                {/* Visible status badge */}
                                                <StatusBadge status={apt.status} />
                                            </div>

                                            {/* Meta row */}
                                            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
                                                <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: t.textFaint }}>
                                                    <Icon d={I.calendar} size={11} />{apt.date}
                                                </span>
                                                <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: t.textFaint }}>
                                                    <Icon d={I.clock} size={11} />{apt.time} · {apt.duration}
                                                </span>
                                                <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: t.textFaint }}>
                                                    {apt.type === "Video Call" ? <Icon d={I.video} size={11} /> : <Icon d={I.map} size={11} />}
                                                    {apt.type}
                                                </span>
                                            </div>

                                            {/* Action buttons */}
                                            <div style={{ display: "flex", gap: 8 }}>
                                                {apt.status === "Pending" && (<>
                                                    <Btn variant="success" size="sm" style={{ flex: 1 }} onClick={() => handleAccept(apt.id)}>
                                                        <Icon d={I.check} size={12} /> Accept
                                                    </Btn>
                                                    <Btn variant="danger" size="sm" style={{ flex: 1 }} onClick={() => handleReject(apt.id)}>
                                                        <Icon d={I.x} size={12} /> Reject
                                                    </Btn>
                                                    <Btn variant="accent" size="sm" onClick={() => setScheduleModal(apt)}>
                                                        <Icon d={I.calendar} size={12} />
                                                    </Btn>
                                                </>)}

                                                {apt.status === "Upcoming" && (<>
                                                    {apt.type === "Video Call" ? (
                                                        <button
                                                            onClick={() => setJoinModal(apt)}
                                                            style={{
                                                                flex: 1, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6,
                                                                padding: "7px 0", borderRadius: 9, border: "none",
                                                                background: `linear-gradient(135deg,${t.primary},#22a898)`,
                                                                color: t.mode === "dark" ? "#0b1c22" : "#fff",
                                                                fontSize: 12, fontWeight: 700, fontFamily: "inherit", cursor: "pointer",
                                                                boxShadow: `0 3px 10px ${t.primary}45`,
                                                            }}>
                                                            📹 Join Call
                                                        </button>
                                                    ) : (
                                                        <Btn variant="primary" size="sm" style={{ flex: 1 }}>
                                                            <Icon d={I.map} size={12} /> View Details
                                                        </Btn>
                                                    )}
                                                    <Btn variant="accent" size="sm" onClick={() => setScheduleModal(apt)}>
                                                        <Icon d={I.clock} size={12} /> Reschedule
                                                    </Btn>
                                                    <Btn variant="danger" size="sm" onClick={() => handleReject(apt.id)}>
                                                        <Icon d={I.x} size={12} />
                                                    </Btn>
                                                </>)}

                                                {apt.status === "Completed" && (
                                                    <Btn variant="secondary" size="sm" style={{ flex: 1 }}>
                                                        <Icon d={I.eye} size={12} /> View Summary
                                                    </Btn>
                                                )}
                                                {apt.status === "Cancelled" && (
                                                    <Btn variant="accent" size="sm" style={{ flex: 1 }} onClick={() => setScheduleModal(apt)}>
                                                        <Icon d={I.calendar} size={12} /> Reschedule
                                                    </Btn>
                                                )}
                                            </div>
                                        </Card>
                                    ))}

                                    {filtered.length === 0 && (
                                        <div style={{ gridColumn: "1 / -1", textAlign: "center", padding: 40, color: t.textMuted, fontSize: 14 }}>
                                            No appointments found for "{statusF}" filter.
                                        </div>
                                    )}
                                </div>
                            </div>

                            {/* ── Right sidebar ──────────────────────── */}
                            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                                <Card style={{ padding: 16 }}>
                                    <div style={{ fontSize: 12, fontWeight: 700, color: t.textFaint, letterSpacing: "0.1em", textTransform: "uppercase", textAlign: "center", marginBottom: 12 }}>
                                        TODAY'S SCHEDULE
                                    </div>
                                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 5, marginBottom: 14 }}>
                                        {["09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30", "14:00", "14:30", "15:00", "15:30", "16:00", "16:30"].map(slot => {
                                            const booked = ["10:00", "12:30"].includes(slot);
                                            return (
                                                <button key={slot} disabled={booked} style={{
                                                    padding: "6px 4px", borderRadius: 7, fontSize: 11, fontWeight: 500,
                                                    border: `1px solid ${booked ? t.border : t.borderHi}`,
                                                    background: booked ? t.cardHi : t.primaryGlow2,
                                                    color: booked ? t.textFaint : t.primary,
                                                    cursor: booked ? "not-allowed" : "pointer",
                                                    textDecoration: booked ? "line-through" : "none",
                                                }}>{slot}</button>
                                            );
                                        })}
                                    </div>
                                    <div style={{ borderRadius: 10, background: t.primaryGlow2, border: `1px solid ${t.primary}30`, padding: 14, textAlign: "center" }}>
                                        <div style={{ fontSize: 11, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.07em", fontWeight: 600, marginBottom: 4 }}>Next Meeting</div>
                                        <div style={{ fontSize: 20, fontWeight: 700, color: t.text, fontFamily: "Georgia,serif" }}>Rajesh Singh</div>
                                        <div style={{ fontSize: 16, fontWeight: 700, color: t.primary, marginTop: 3 }}>10:00 AM</div>
                                    </div>
                                </Card>

                                <Card style={{ padding: 16 }}>
                                    <div style={{ fontSize: 12, fontWeight: 700, color: t.textFaint, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 12 }}>
                                        Quick Actions
                                    </div>
                                    <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                                        <button onClick={() => setScheduleModal(null)} style={{
                                            display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 7,
                                            width: "100%", padding: "9px 0", borderRadius: 9, border: "none",
                                            background: `linear-gradient(135deg,${t.primary},#22a898)`,
                                            color: t.mode === "dark" ? "#0b1c22" : "#fff",
                                            fontSize: 12.5, fontWeight: 700, fontFamily: "inherit", cursor: "pointer",
                                            boxShadow: `0 3px 10px ${t.primary}40`,
                                        }}>+ New Appointment</button>
                                        <Btn variant="secondary" full size="sm">
                                            <Icon d={I.clock} size={13} /> Block Time
                                        </Btn>
                                    </div>
                                </Card>
                            </div>
                        </div>
                    ) : (
                        /* ── Calendar view ──────────────────────────── */
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 18 }}>
                            <Card style={{ overflow: "hidden" }}>
                                <div style={{ overflowX: "auto" }}>
                                    <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 650 }}>
                                        <thead>
                                            <tr>
                                                <th style={{ width: 56, padding: "10px 8px", borderBottom: `1px solid ${t.border}`, borderRight: `1px solid ${t.border}`, background: t.surface }} />
                                                {CAL_DAYS.map((d, i) => (
                                                    <th key={d} style={{ padding: "10px 6px", borderBottom: `1px solid ${t.border}`, borderRight: `1px solid ${t.border}`, background: t.surface, textAlign: "center", minWidth: 95 }}>
                                                        <div style={{ fontSize: 10, color: t.textFaint, fontWeight: 600, textTransform: "uppercase" }}>{d} Day</div>
                                                        <div style={{ fontSize: 18, fontWeight: 700, color: i === 4 ? t.primary : t.text, marginTop: 1 }}>{CAL_DATES[i]}</div>
                                                    </th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {CAL_HOURS.map(hr => (
                                                <tr key={hr}>
                                                    <td style={{ padding: "6px 8px", fontSize: 11, color: t.textFaint, borderRight: `1px solid ${t.border}`, borderBottom: `1px solid ${t.border}`, fontWeight: 500, textAlign: "right", verticalAlign: "top", whiteSpace: "nowrap" }}>{hr}</td>
                                                    {CAL_DAYS.map((_, di) => {
                                                        const evs = calAppts.filter(e => e.day === di && e.hour === hr);
                                                        return (
                                                            <td key={di} style={{ padding: 3, borderRight: `1px solid ${t.border}`, borderBottom: `1px solid ${t.border}`, verticalAlign: "top", height: 50 }}>
                                                                {evs.map((ev, ei) => (
                                                                    <div key={ei} style={{
                                                                        background: ev.type === "video" ? `${t.info}22` : `${t.primary}18`,
                                                                        border: `1px solid ${ev.type === "video" ? t.info : t.primary}40`,
                                                                        borderRadius: 6, padding: "4px 6px", marginBottom: 2, cursor: "pointer",
                                                                    }}>
                                                                        <div style={{ fontSize: 11, fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ev.client}</div>
                                                                        <div style={{ fontSize: 10, color: t.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ev.purpose}</div>
                                                                    </div>
                                                                ))}
                                                            </td>
                                                        );
                                                    })}
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </Card>

                            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                                <Card style={{ padding: 16 }}>
                                    <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 10 }}>Quick Summary</div>
                                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 8, marginBottom: 12 }}>
                                        {[{ l: "Upcoming", v: statCounts.upcoming, c: "#5ab3ff" }, { l: "Pending", v: statCounts.pending, c: "#e8b84b" }, { l: "Done", v: statCounts.completed, c: "#3ec99a" }].map(s => (
                                            <div key={s.l} style={{ padding: "8px 6px", borderRadius: 8, background: t.cardHi, border: `1px solid ${t.border}`, textAlign: "center" }}>
                                                <div style={{ fontSize: 15, fontWeight: 700, color: s.c }}>{s.v}</div>
                                                <div style={{ fontSize: 10, color: t.textMuted, marginTop: 2 }}>{s.l}</div>
                                            </div>
                                        ))}
                                    </div>
                                    {appointments.slice(0, 4).map((a, i) => (
                                        <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", padding: "7px 0", borderBottom: i < 3 ? `1px solid ${t.border}` : "none" }}>
                                            <div style={{ width: 28, height: 28, borderRadius: 8, background: t.grad1, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 700, color: t.mode === "dark" ? "#111B1F" : "#fff", flexShrink: 0 }}>{a.initials}</div>
                                            <div style={{ flex: 1, minWidth: 0 }}>
                                                <div style={{ fontSize: 12, fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.client}</div>
                                                <div style={{ fontSize: 10, color: t.textFaint }}>{a.purpose.slice(0, 22)}…</div>
                                            </div>
                                        </div>
                                    ))}
                                </Card>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

export { AppointmentsPage };