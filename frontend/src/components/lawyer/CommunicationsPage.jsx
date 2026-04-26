'use client';
// Lawyer Communications Page — paste your code here
import { useState, useEffect, useRef } from "react";
import { useTheme } from "./theme.js";
import { useCase } from "./theme.js";
import { qData } from "./data.js";
import { avatarBg } from "./utils.js";

/* ================= Tick Icon ================= */
function CommTick({ status }) {
    const color = status === "seen" ? "#3b82f6" : "rgba(120,120,120,.6)";
    return (
        <svg width={16} height={10} viewBox="0 0 20 12" fill="none">
            <path d="M1 6L5 10L13 2" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
            <path d="M7 6L11 10L19 2" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
        </svg>
    );
}

/* ================= Component ================= */
function CommunicationsPage() {
    const { t } = useTheme();
    const { setPage, setActiveCase, setOpenCaseId } = useCase();

    const [threads, setThreads] = useState(() => {
        const init = {};
        qData.forEach(q => { init[q.id] = q.thread || []; });
        return init;
    });

    const [sel, setSel] = useState(qData[0]);
    const [reply, setReply] = useState("");
    const [search, setSearch] = useState("");
    const msgEndRef = useRef(null);

    useEffect(() => {
        msgEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [threads, sel]);

    const sendReply = () => {
        if (!reply.trim()) return;
        const now = new Date();
        const newMsg = {
            who: "lawyer",
            text: reply.trim(),
            time: now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
            date: now.toDateString(),
            status: "sent",
        };
        setThreads(prev => ({ ...prev, [sel.id]: [...(prev[sel.id] || []), newMsg] }));
        setReply("");
    };

    const openCaseWorkspace = () => {
        setActiveCase(sel.case);
        setOpenCaseId(sel.case);
        setPage("cases");
    };

    const filtered = qData.filter(q =>
        q.client.toLowerCase().includes(search.toLowerCase())
    );

    return (
        <div style={{
            flex: 1,
            display: "flex",
            height: "100%",
            minHeight: 0,
            overflow: "hidden",
            background: t.bg,
            padding: "14px 16px",
            gap: 12,
            boxSizing: "border-box",
        }}>

            {/* ══════════════ LEFT PANEL ══════════════ */}
            <div style={{
                width: 280,
                flexShrink: 0,
                display: "flex",
                flexDirection: "column",
                background: t.surface,
                borderRadius: 16,
                border: `1px solid ${t.border}`,
                overflow: "hidden",
                minHeight: 0,
            }}>

                {/* Header */}
                <div style={{
                    padding: "16px 14px 10px",
                    borderBottom: `1px solid ${t.border}`,
                    flexShrink: 0,
                }}>
                    <div style={{
                        fontSize: 15, fontWeight: 700, color: t.text, marginBottom: 10,
                    }}>
                        Messages
                    </div>

                    {/* Search */}
                    <div style={{ position: "relative" }}>
                        <svg width="13" height="13" viewBox="0 0 16 16" fill="none"
                            style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", pointerEvents: "none" }}
                            stroke={t.textFaint} strokeWidth="1.8" strokeLinecap="round">
                            <circle cx="7" cy="7" r="5" /><path d="M12 12l2 2" />
                        </svg>
                        <input
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            placeholder="Search conversations…"
                            style={{
                                width: "100%", height: 36, borderRadius: 10,
                                border: `1px solid ${t.border}`,
                                background: t.cardHi,
                                paddingLeft: 32, paddingRight: 12,
                                outline: "none", fontSize: 12.5,
                                color: t.text, fontFamily: "inherit",
                                boxSizing: "border-box",
                            }}
                        />
                    </div>
                </div>

                {/* Thread list — this scrolls */}
                <div style={{ flex: 1, overflowY: "auto", padding: "6px 8px" }}>
                    {filtered.map(q => {
                        const isSel = sel.id === q.id;
                        return (
                            <div
                                key={q.id}
                                onClick={() => setSel(q)}
                                style={{
                                    display: "flex", alignItems: "center", gap: 10,
                                    padding: "10px 10px",
                                    cursor: "pointer",
                                    marginBottom: 2,
                                    borderRadius: 12,
                                    background: isSel ? t.primaryGlow2 : "transparent",
                                    border: `1px solid ${isSel ? t.primary + "30" : "transparent"}`,
                                    transition: "all .15s",
                                }}
                                onMouseEnter={e => { if (!isSel) { e.currentTarget.style.background = t.cardHi; e.currentTarget.style.borderColor = t.border; } }}
                                onMouseLeave={e => { if (!isSel) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.borderColor = "transparent"; } }}
                            >
                                {/* Avatar */}
                                <div style={{
                                    width: 40, height: 40, flexShrink: 0,
                                    borderRadius: "50%",
                                    background: avatarBg(q.initials),
                                    display: "flex", alignItems: "center", justifyContent: "center",
                                    fontWeight: 700, fontSize: 13, color: "#fff",
                                }}>
                                    {q.initials}
                                </div>

                                {/* Text */}
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{
                                        display: "flex", justifyContent: "space-between",
                                        alignItems: "baseline", gap: 4, marginBottom: 1,
                                    }}>
                                        <span style={{
                                            fontWeight: 700, fontSize: 13, color: t.text,
                                            whiteSpace: "nowrap", overflow: "hidden",
                                            textOverflow: "ellipsis", minWidth: 0,
                                        }}>
                                            {q.client}
                                        </span>
                                        <span style={{
                                            fontSize: 10.5, color: t.textFaint, flexShrink: 0,
                                        }}>
                                            {q.time}
                                        </span>
                                    </div>

                                    <div style={{
                                        fontSize: 11, color: t.primary, fontWeight: 600,
                                        whiteSpace: "nowrap", overflow: "hidden",
                                        textOverflow: "ellipsis", marginBottom: 1,
                                    }}>
                                        {q.case}
                                    </div>

                                    <div style={{
                                        fontSize: 11.5, color: t.textMuted,
                                        whiteSpace: "nowrap", overflow: "hidden",
                                        textOverflow: "ellipsis",
                                    }}>
                                        {q.lastMsg}
                                    </div>
                                </div>

                                {/* Unread badge */}
                                {q.unread && (
                                    <div style={{
                                        minWidth: 20, height: 20, flexShrink: 0,
                                        borderRadius: 10, background: t.primary,
                                        color: t.mode === "dark" ? t.bg : "#fff",
                                        fontSize: 10.5, fontWeight: 700,
                                        display: "flex", alignItems: "center", justifyContent: "center",
                                    }}>
                                        {q.unread}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* ══════════════ RIGHT PANEL ══════════════ */}
            <div style={{
                flex: 1,
                minWidth: 0,
                minHeight: 0,
                display: "flex",
                flexDirection: "column",
                gap: 10,
            }}>

                {/* ── Contact header card ── */}
                <div style={{
                    flexShrink: 0,
                    background: t.surface,
                    borderRadius: 16,
                    border: `1px solid ${t.border}`,
                    padding: "14px 18px",
                    display: "flex",
                    alignItems: "center",
                    gap: 14,
                }}>
                    <div style={{
                        width: 46, height: 46, flexShrink: 0,
                        borderRadius: "50%",
                        background: avatarBg(sel.initials),
                        display: "flex", alignItems: "center", justifyContent: "center",
                        color: "#fff", fontWeight: 700, fontSize: 15,
                    }}>
                        {sel.initials}
                    </div>

                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{
                            fontWeight: 700, fontSize: 15, color: t.text, marginBottom: 2,
                        }}>
                            {sel.client}
                        </div>
                        <div style={{ fontSize: 12.5, color: t.textMuted, marginBottom: 2 }}>
                            {sel.phone}
                        </div>
                        <div style={{ fontSize: 11.5, color: t.primary }}>
                            {sel.case}&nbsp;&nbsp;·&nbsp;&nbsp;{sel.caseStatus}&nbsp;&nbsp;·&nbsp;&nbsp;{sel.nextHearing}
                        </div>
                    </div>

                    <button
                        onClick={openCaseWorkspace}
                        style={{
                            padding: "8px 16px", borderRadius: 10, flexShrink: 0,
                            border: `1.5px solid ${t.primary}50`,
                            background: t.primaryGlow2,
                            color: t.primary, cursor: "pointer",
                            fontSize: 12.5, fontWeight: 700,
                            fontFamily: "inherit", transition: "all .15s",
                            whiteSpace: "nowrap",
                        }}
                        onMouseEnter={e => { e.currentTarget.style.background = t.primaryGlow; }}
                        onMouseLeave={e => { e.currentTarget.style.background = t.primaryGlow2; }}
                    >
                        Open Case
                    </button>
                </div>

                {/* ── Chat card (fills all remaining height) ── */}
                <div style={{
                    flex: 1,
                    minHeight: 0,
                    background: t.surface,
                    borderRadius: 16,
                    border: `1px solid ${t.border}`,
                    display: "flex",
                    flexDirection: "column",
                    overflow: "hidden",
                }}>

                    {/* Messages scroll area */}
                    <div style={{
                        flex: 1,
                        minHeight: 0,
                        overflowY: "auto",
                        padding: "20px 24px 12px",
                        display: "flex",
                        flexDirection: "column",
                    }}>
                        {(threads[sel.id] || []).map((msg, i) => {
                            const prev = threads[sel.id]?.[i - 1];
                            const grouped = prev && prev.who === msg.who;
                            const showDate = !prev || prev.date !== msg.date;
                            const isLawyer = msg.who === "lawyer";

                            return (
                                <div key={i}>
                                    {showDate && msg.date && (
                                        <div style={{
                                            textAlign: "center",
                                            fontSize: 11.5, color: t.textFaint,
                                            margin: "16px 0 10px",
                                        }}>
                                            <span style={{
                                                background: t.cardHi,
                                                border: `1px solid ${t.border}`,
                                                padding: "4px 14px",
                                                borderRadius: 20,
                                            }}>
                                                {msg.date}
                                            </span>
                                        </div>
                                    )}

                                    <div style={{
                                        display: "flex",
                                        justifyContent: isLawyer ? "flex-end" : "flex-start",
                                        marginTop: grouped ? 4 : 12,
                                    }}>
                                        <div style={{
                                            maxWidth: "60%",
                                            background: isLawyer ? t.primary : t.card,
                                            color: isLawyer
                                                ? (t.mode === "dark" ? t.bg : "#fff")
                                                : t.text,
                                            padding: "10px 14px",
                                            borderRadius: isLawyer
                                                ? "18px 18px 5px 18px"
                                                : "18px 18px 18px 5px",
                                            fontSize: 13.5,
                                            lineHeight: 1.55,
                                            border: isLawyer ? "none" : `1px solid ${t.border}`,
                                        }}>
                                            <div>{msg.text}</div>
                                            <div style={{
                                                fontSize: 10.5, marginTop: 5,
                                                display: "flex", justifyContent: "flex-end",
                                                alignItems: "center", gap: 4,
                                                opacity: 0.65,
                                            }}>
                                                {msg.time}
                                                <CommTick status={msg.status} />
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                        <div ref={msgEndRef} />
                    </div>

                    {/* Input bar */}
                    <div style={{
                        flexShrink: 0,
                        padding: "10px 16px 16px",
                        borderTop: `1px solid ${t.border}`,
                    }}>
                        <div
                            style={{
                                display: "flex", alignItems: "center", gap: 8,
                                background: t.card,
                                border: `1.5px solid ${t.border}`,
                                borderRadius: 14,
                                padding: "6px 6px 6px 16px",
                                transition: "border-color .15s",
                            }}
                            onFocusCapture={e => e.currentTarget.style.borderColor = t.primary}
                            onBlurCapture={e => e.currentTarget.style.borderColor = t.border}
                        >
                            <input
                                value={reply}
                                onChange={e => setReply(e.target.value)}
                                onKeyDown={e => {
                                    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendReply(); }
                                }}
                                placeholder="Type your message…"
                                style={{
                                    flex: 1, border: "none", outline: "none",
                                    background: "transparent",
                                    fontSize: 13.5, color: t.text,
                                    padding: "5px 0", fontFamily: "inherit",
                                }}
                            />
                            <button
                                onClick={sendReply}
                                style={{
                                    width: 38, height: 38, flexShrink: 0,
                                    borderRadius: 11, border: "none",
                                    background: t.primary,
                                    color: t.mode === "dark" ? t.bg : "#fff",
                                    cursor: "pointer",
                                    display: "flex", alignItems: "center", justifyContent: "center",
                                    transition: "opacity .15s",
                                }}
                                onMouseEnter={e => e.currentTarget.style.opacity = ".8"}
                                onMouseLeave={e => e.currentTarget.style.opacity = "1"}
                            >
                                <svg width="15" height="15" viewBox="0 0 16 16" fill="none"
                                    stroke="currentColor" strokeWidth="2.2"
                                    strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M14 2L2 8l5 2 2 5 5-13z" />
                                </svg>
                            </button>
                        </div>
                    </div>

                </div>
            </div>

        </div>
    );
}

export { CommunicationsPage };