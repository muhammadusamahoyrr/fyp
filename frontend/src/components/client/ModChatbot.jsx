'use client';
// Paste your ModChatbot.jsx code here
import React, { useState } from "react";
import { useT } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import Ic from "./Ic.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput, Badge, Tooltip } from "@/components/shared/shared.jsx";

/* ══════════════════════════════════════════════════════
   MODULE: AI CHATBOT
══════════════════════════════════════════════════════ */
const ModChatbot = () => {
    const t = useT();
    const toast = useToast();
    const [msgs, setMsgs] = useState([]);
    const [inp, setInp] = useState("");
    const [typing, setTyping] = useState(false);
    const [lang, setLang] = useState("EN");
    const [sideOpen, setSideOpen] = useState(true);
    const [history, setHistory] = useState([
        { group: "This Week", items: ["What is wrongful termination?", "Employment law basics"] },
        { group: "Last Week", items: ["Contract dispute analysis", "NDA review help"] },
    ]);

    const h = new Date().getHours();
    const greetingText = h < 12 ? "Good Morning" : h < 17 ? "Good Afternoon" : "Good Evening";
    const greetingEmoji = h < 12 ? "🌅" : h < 17 ? "⛅" : "🌙";
    const greetingSub = h >= 20 || h < 5
        ? "Dark mode is on. What are we researching?"
        : h < 12 ? "The details are in the dark. Let's find them."
            : "The details are in the dark. Let's find them.";

    const send = () => {
        if (!inp.trim()) return;
        const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        const txt = inp.trim();
        setMsgs(m => [...m, { role: "user", text: txt, time: now }]);
        setHistory(prev => {
            const updated = [...prev];
            if (!updated[0]) return prev;
            if (!updated[0].items.includes(txt)) updated[0] = { ...updated[0], items: [txt, ...updated[0].items] };
            return updated;
        });
        toast.show("Message sent", "info", 1500);
        setInp("");
        setTyping(true);
        setTimeout(() => {
            setTyping(false);
            setMsgs(m => [...m, {
                role: "ai",
                text: "Based on current precedents, your case shows strong indicators for a successful claim. I recommend consulting a qualified employment attorney for full evaluation.",
                time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
                refs: ["McDonnell Douglas v. Green", "42 U.S.C. § 2000e"],
            }]);
            toast.show("AI response received", "success", 1500);
        }, 1600);
    };

    const hasMessages = msgs.length > 0;

    /* ── shared icon button style ── */
    const iconBtn = (extra = {}) => ({
        background: "none", border: "none", cursor: "pointer", padding: 6,
        borderRadius: 8, color: t.textMuted, display: "flex",
        alignItems: "center", justifyContent: "center",
        transition: "background 0.15s, color 0.15s", ...extra,
    });

    return (
        <div style={{
            position: "relative", inset: 0, width: "100%", height: "100%",
            display: "flex", overflow: "hidden",
            background: t.bg, fontFamily: "'Inter',sans-serif",
        }}>

            {/* ══ SIDEBAR ══ */}
            <div style={{
                width: sideOpen ? 200 : 0, minWidth: sideOpen ? 200 : 0,
                flexShrink: 0, overflow: "hidden",
                transition: "width 0.3s cubic-bezier(0.4,0,0.2,1), min-width 0.3s cubic-bezier(0.4,0,0.2,1)",
                background: t.surface, borderRight: `1px solid ${t.border}`,
                display: "flex", flexDirection: "column",
            }}>

                {/* New Chat */}
                <div style={{ padding: "14px 14px 10px" }}>
                    <button onClick={() => setMsgs([])} style={{
                        width: "100%", padding: "10px 18px", borderRadius: 50,
                        background: t.primary, color: t.mode === "dark" ? "#1A2E35" : "#fff",
                        border: "none", fontSize: 13, fontWeight: 700, cursor: "pointer",
                        display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
                        fontFamily: "'Inter',sans-serif", transition: "opacity 0.2s",
                        boxShadow: `0 4px 16px ${t.primaryGlow}`, whiteSpace: "nowrap",
                    }}
                        onMouseEnter={e => e.currentTarget.style.opacity = "0.88"}
                        onMouseLeave={e => e.currentTarget.style.opacity = "1"}
                    >
                        <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                            <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="16" /><line x1="8" y1="12" x2="16" y2="12" />
                        </svg>
                        New Chat
                    </button>
                </div>

                {/* History header */}
                <div style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "6px 16px 4px",
                }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>History</span>
                    <div style={{ display: "flex", gap: 2 }}>
                        <button style={iconBtn()}>
                            <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <polyline points="18 15 12 9 6 15" />
                            </svg>
                        </button>
                        <button style={iconBtn()}>
                            <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <circle cx="12" cy="5" r="1.2" /><circle cx="12" cy="12" r="1.2" /><circle cx="12" cy="19" r="1.2" />
                            </svg>
                        </button>
                    </div>
                </div>

                {/* History list */}
                <div style={{ flex: 1, overflowY: "auto", padding: "4px 10px 8px" }}>
                    {history.map((g, gi) => (
                        <div key={gi} style={{ marginBottom: 14 }}>
                            <div style={{
                                fontSize: 11, fontWeight: 600, color: t.textMuted,
                                padding: "6px 6px 4px", display: "flex", alignItems: "center", gap: 5,
                                textTransform: "uppercase", letterSpacing: "0.6px",
                            }}>
                                <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                    <polyline points="6 9 12 15 18 9" />
                                </svg>
                                {g.group}
                            </div>
                            {g.items.map((item, ii) => (
                                <div key={ii} onClick={() => setInp(item)} style={{
                                    padding: "9px 12px", borderRadius: 10, fontSize: 12.5,
                                    color: t.textDim, cursor: "pointer", transition: "all 0.15s",
                                    marginBottom: 2, whiteSpace: "nowrap", overflow: "hidden",
                                    textOverflow: "ellipsis",
                                }}
                                    onMouseEnter={e => { e.currentTarget.style.background = t.inputBg; e.currentTarget.style.color = t.text; }}
                                    onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = t.textDim; }}
                                >{item}</div>
                            ))}
                        </div>
                    ))}
                </div>

                {/* Sidebar footer: collapse toggle */}
                <div style={{ padding: "10px 14px 14px", borderTop: `1px solid ${t.border}` }}>
                    <button onClick={() => setSideOpen(false)} style={{
                        width: "100%", padding: "9px", borderRadius: 10, fontSize: 12,
                        background: "transparent", border: `1px solid ${t.border}`,
                        color: t.textMuted, cursor: "pointer", fontFamily: "'Inter',sans-serif",
                        display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
                        transition: "all 0.2s",
                    }}
                        onMouseEnter={e => { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.color = t.primary; }}
                        onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textMuted; }}
                    >
                        <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M15 18l-6-6 6-6" />
                        </svg>
                        Collapse
                    </button>
                </div>
            </div>

            {/* ══ MAIN AREA ══ */}
            <div style={{
                flex: 1, display: "flex", flexDirection: "column",
                overflow: "hidden", position: "relative",
            }}>

                {/* ── Truly floating labels — NO background, NO border, NO box ── */}
                {/* Chat label — top left, plain text only */}
                <div style={{
                    position: "absolute", top: 18, left: 22, zIndex: 10,
                    display: "flex", alignItems: "center", gap: 10, pointerEvents: "none",
                }}>
                    {!sideOpen && (
                        <button onClick={() => setSideOpen(true)} style={{
                            width: 36, height: 36, borderRadius: "50%",
                            background: t.primary, border: "none",
                            display: "flex", alignItems: "center", justifyContent: "center",
                            cursor: "pointer", pointerEvents: "auto",
                            boxShadow: `0 4px 14px ${t.primaryGlow}`, transition: "opacity 0.2s",
                        }}
                            onMouseEnter={e => e.currentTarget.style.opacity = "0.85"}
                            onMouseLeave={e => e.currentTarget.style.opacity = "1"}
                        >
                            <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke={t.mode === "dark" ? "#1A2E35" : "#fff"} strokeWidth="2.5">
                                <path d="M9 18l6-6-6-6" />
                            </svg>
                        </button>
                    )}
                    <span style={{
                        fontSize: 17, fontWeight: 700, color: t.text,
                        fontFamily: "'Playfair Display',serif",
                    }}>Chat</span>
                </div>

                {/* Upgrade Plan — top right pill only */}
                <div style={{
                    position: "absolute", top: 12, right: 18, zIndex: 10,
                    pointerEvents: "auto",
                }}>
                    <button style={{
                        background: t.primary, color: t.mode === "dark" ? "#1A2E35" : "#fff",
                        border: "none", borderRadius: 50, padding: "10px 22px",
                        fontSize: 13, fontWeight: 700, cursor: "pointer",
                        fontFamily: "'Inter',sans-serif",
                        boxShadow: `0 4px 16px ${t.primaryGlow}`, transition: "opacity 0.2s",
                    }}
                        onMouseEnter={e => e.currentTarget.style.opacity = "0.88"}
                        onMouseLeave={e => e.currentTarget.style.opacity = "1"}
                    >Upgrade Plan</button>
                </div>

                {/* ── Messages / Welcome ── */}
                <div style={{
                    flex: 1, overflowY: "auto",
                    display: "flex", flexDirection: "column",
                    alignItems: "center",
                    justifyContent: hasMessages ? "flex-start" : "center",
                    padding: hasMessages ? "68px 28px 16px" : "0 28px",
                }}>
                    {!hasMessages ? (
                        /* ── Welcome screen ── */
                        <div style={{ textAlign: "center", maxWidth: 700, width: "100%", padding: "0 20px" }}>
                            {/* Emoji + greeting inline like reference */}
                            <div style={{
                                display: "flex", alignItems: "center", justifyContent: "center",
                                gap: 14, marginBottom: 16,
                            }}>
                                <span style={{ fontSize: 44 }}>{greetingEmoji}</span>
                                <h2 style={{
                                    fontFamily: "'Playfair Display',serif", fontSize: 26, fontWeight: 700,
                                    color: t.text, margin: 0, letterSpacing: "-0.4px",
                                }}>{greetingText}, Muhammad!</h2>
                            </div>
                            <p style={{
                                fontFamily: "'Playfair Display',serif", fontSize: 32, fontWeight: 700,
                                color: t.text, marginBottom: 44, lineHeight: 1.35, letterSpacing: "-0.6px",
                            }}>{greetingSub}</p>
                        </div>
                    ) : (
                        /* ── Message thread ── */
                        <div style={{ width: "100%", maxWidth: 820, display: "flex", flexDirection: "column", gap: 18 }}>
                            {msgs.map((m, i) => (
                                <div key={i} style={{
                                    display: "flex",
                                    flexDirection: m.role === "user" ? "row-reverse" : "row",
                                    gap: 10, alignItems: "flex-start",
                                }}>
                                    {m.role === "ai" && (
                                        <div style={{
                                            width: 34, height: 34, borderRadius: 10,
                                            background: t.primaryGlow, flexShrink: 0,
                                            display: "flex", alignItems: "center", justifyContent: "center",
                                        }}>
                                            <Ic n="scale" s={16} c={t.primary} />
                                        </div>
                                    )}
                                    <div style={{ maxWidth: "75%" }}>
                                        <div style={{
                                            background: m.role === "user" ? t.grad1 : t.surface,
                                            border: m.role === "ai" ? `1px solid ${t.border}` : "none",
                                            borderRadius: m.role === "user" ? "18px 18px 6px 18px" : "18px 18px 18px 6px",
                                            padding: "13px 17px", fontSize: 13.5, lineHeight: 1.8,
                                            color: m.role === "user" ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.text,
                                        }}>{m.text}</div>
                                        {m.refs && (
                                            <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
                                                {m.refs.map((r, ri) => <Badge key={ri} type="info">{r}</Badge>)}
                                            </div>
                                        )}
                                        <div style={{ fontSize: 10, color: t.textFaint, marginTop: 5, textAlign: m.role === "user" ? "right" : "left" }}>
                                            {m.time}
                                        </div>
                                    </div>
                                </div>
                            ))}
                            {typing && (
                                <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                                    <div style={{ width: 34, height: 34, borderRadius: 10, background: t.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                                        <Ic n="scale" s={16} c={t.primary} />
                                    </div>
                                    <div style={{
                                        background: t.surface, border: `1px solid ${t.border}`,
                                        borderRadius: "18px 18px 18px 6px", padding: "14px 18px",
                                        display: "flex", gap: 5, alignItems: "center",
                                    }}>
                                        {[0, 1, 2].map(d => (
                                            <div key={d} style={{
                                                width: 7, height: 7, borderRadius: "50%", background: t.primary,
                                                animation: `pulse 1.2s ease ${d * 0.2}s infinite`,
                                            }} />
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </div>

                {/* ── Input box ── */}
                <div style={{
                    padding: "0 28px 20px",
                    display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0,
                }}>
                    <div style={{
                        width: "100%", maxWidth: 820,
                        background: t.mode === "dark" ? "rgba(20,42,50,0.97)" : t.surface,
                        border: `1.5px solid ${t.border}`,
                        borderRadius: 18, padding: "14px 16px 12px 20px",
                        boxShadow: t.shadowCard,
                    }}>
                        {/* Text input */}
                        <input
                            value={inp}
                            onChange={e => setInp(e.target.value)}
                            onKeyDown={e => e.key === "Enter" && !e.shiftKey && send()}
                            placeholder="Ask AI Attorney..."
                            style={{
                                width: "100%", background: "transparent", border: "none", outline: "none",
                                color: t.text, fontSize: 15, fontFamily: "'Inter',sans-serif",
                                padding: "4px 0 12px", lineHeight: 1.6,
                            }}
                        />

                        {/* Bottom toolbar */}
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                            {/* Search button */}
                            <button style={{
                                display: "flex", alignItems: "center", gap: 7,
                                background: t.inputBg, border: `1px solid ${t.border}`,
                                borderRadius: 50, padding: "7px 16px",
                                fontSize: 13, color: t.textMuted, cursor: "pointer",
                                fontFamily: "'Inter',sans-serif", transition: "all 0.15s",
                            }}
                                onMouseEnter={e => { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.color = t.primary; }}
                                onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textMuted; }}
                            >
                                <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                    <circle cx="12" cy="12" r="10" /><path d="M2 12h20" /><ellipse cx="12" cy="12" rx="4" ry="10" />
                                </svg>
                                Search
                            </button>

                            {/* Right controls */}
                            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                                {/* Clock */}
                                <Tooltip text="Recent chats">
                                    <button style={iconBtn()}
                                        onMouseEnter={e => { e.currentTarget.style.background = t.inputBg; e.currentTarget.style.color = t.primary; }}
                                        onMouseLeave={e => { e.currentTarget.style.background = "none"; e.currentTarget.style.color = t.textMuted; }}
                                    >
                                        <Ic n="clock" s={17} c="currentColor" />
                                    </button>
                                </Tooltip>

                                {/* Pro badge */}
                                <span style={{
                                    fontSize: 11, fontWeight: 700, color: t.textMuted,
                                    background: t.inputBg, border: `1px solid ${t.border}`,
                                    borderRadius: 6, padding: "3px 9px",
                                }}>Pro</span>

                                {/* EN/UR switcher */}
                                <div style={{
                                    display: "flex", borderRadius: 8, overflow: "hidden",
                                    border: `1px solid ${t.border}`, background: t.inputBg,
                                }}>
                                    {["EN", "UR"].map(l => (
                                        <button key={l} onClick={() => setLang(l)} style={{
                                            padding: "5px 12px", fontSize: 11, fontWeight: 700,
                                            border: "none", cursor: "pointer",
                                            background: lang === l ? t.primary : "transparent",
                                            color: lang === l ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.textMuted,
                                            transition: "all 0.15s", fontFamily: "'Inter',sans-serif",
                                        }}>{l}</button>
                                    ))}
                                </div>

                                {/* Mic */}
                                <Tooltip text="Voice input (beta)">
                                    <button style={iconBtn()}
                                        onMouseEnter={e => { e.currentTarget.style.background = t.inputBg; e.currentTarget.style.color = t.primary; }}
                                        onMouseLeave={e => { e.currentTarget.style.background = "none"; e.currentTarget.style.color = t.textMuted; }}
                                    >
                                        <Ic n="mic" s={17} c="currentColor" />
                                    </button>
                                </Tooltip>

                                {/* Send */}
                                <button onClick={send} style={{
                                    width: 36, height: 36, borderRadius: 10,
                                    background: inp.trim() ? t.primary : t.inputBg,
                                    border: `1.5px solid ${inp.trim() ? t.primary : t.border}`,
                                    display: "flex", alignItems: "center", justifyContent: "center",
                                    cursor: inp.trim() ? "pointer" : "default",
                                    transition: "all 0.2s", transform: "rotate(45deg)",
                                    boxShadow: inp.trim() ? `0 4px 12px ${t.primaryGlow}` : "none",
                                }}>
                                    <Ic n="send" s={16} c={inp.trim() ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.textMuted} />
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* Disclaimer */}
                    <div style={{ marginTop: 8, fontSize: 11, color: t.textFaint, textAlign: "center" }}>
                        Authentic citations. Verify applicability. Avoid web searches for Pakistani cases.
                    </div>
                </div>

            </div>
        </div>
    );
};

export default ModChatbot;

