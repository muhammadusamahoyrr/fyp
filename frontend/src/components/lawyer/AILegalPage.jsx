'use client';
// Lawyer AI Legal Page — paste your code here
import { useState, useEffect, useRef } from "react";
import { useTheme } from "./theme.js";
import { useCase } from "./theme.js";
import { useNotif } from "./theme.js";
import { Icon, I } from "./icons.jsx";
import { casesData } from "./data.js";

// ============================================================
// AI LEGAL PAGE — Full chatbot UI with case context injection
// ============================================================
function AILegalPage() {
    const { t } = useTheme();
    const { activeCase } = useCase();
    const { addNotif } = useNotif();
    const activeCaseObj = casesData.find(c => c.id === activeCase);
    const [msgs, setMsgs] = useState([]);
    const [query, setQuery] = useState("");
    const [loading, setLoading] = useState(false);
    const [sideOpen, setSideOpen] = useState(true);
    const [lang, setLang] = useState("EN");
    const [history, setHistory] = useState([
        { group: "This Week", items: ["What is wrongful termination?", "Employment law basics", "CPC Section 9 explanation"] },
        { group: "Last Week", items: ["Contract dispute analysis", "NDA review help", "Bail application under CrPC"] },
    ]);
    const bottomRef = useRef(null);
    useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

    // Auto-inject active case context when case changes
    useEffect(() => {
        if (activeCaseObj) {
            const ctx = `I'm working on case ${activeCaseObj.id}: "${activeCaseObj.title}" — ${activeCaseObj.type} case for client ${activeCaseObj.client} at ${activeCaseObj.court}. Next hearing: ${activeCaseObj.nextHearing}. What should I prepare?`;
            setQuery(ctx);
            setMsgs([]); // reset conversation when case changes
        }
    }, [activeCase]); // runs whenever active case changes, not just mount

    const systemPrompt = activeCaseObj
        ? `You are an expert Indian legal assistant for a lawyer. You are currently helping with case ${activeCaseObj.id}: "${activeCaseObj.title}" — a ${activeCaseObj.type} case for client ${activeCaseObj.client} at ${activeCaseObj.court}. Next hearing: ${activeCaseObj.nextHearing}. Provide concise, accurate answers about Indian law, court procedures, case precedents, and legal sections. Reference specific acts and sections where relevant.`
        : `You are an expert Indian legal assistant for a lawyer. Provide concise, accurate answers about Indian law, court procedures, case precedents, and legal sections. Reference specific acts and sections where relevant.`;

    const h = new Date().getHours();
    const greetEmoji = h < 12 ? "🌅" : h < 17 ? "⛅" : "🌙";
    const greetWord = h < 12 ? "Good Morning" : h < 17 ? "Good Afternoon" : "Good Evening";
    const greetSub = activeCaseObj ? `Working on: ${activeCaseObj.id} — ${activeCaseObj.title}` : "The details are in the dark. Let's find them.";

    const send = async () => {
        if (!query.trim() || loading) return;
        const q = query.trim(); setQuery("");
        const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        setMsgs(p => [...p, { role: "user", content: q, time: now }]);
        setHistory(prev => { const u = [...prev]; if (u[0] && !u[0].items.includes(q)) u[0] = { ...u[0], items: [q, ...u[0].items] }; return u; });
        setLoading(true);
        try {
            const r = await fetch("https://api.anthropic.com/v1/messages", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    model: "claude-sonnet-4-20250514", max_tokens: 1000,
                    system: systemPrompt,
                    messages: msgs.filter(m => m.role !== "system").concat([{ role: "user", content: q }]).map(m => ({ role: m.role === "assistant" ? "assistant" : "user", content: m.content }))
                })
            });
            const d = await r.json();
            const aiTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
            setMsgs(p => [...p, { role: "assistant", content: d.content?.[0]?.text || "Error occurred.", time: aiTime }]);
        } catch { setMsgs(p => [...p, { role: "assistant", content: "Connection error. Please try again.", time: "" }]); }
        finally { setLoading(false); }
    };

    const hasMessages = msgs.length > 0;

    return (
        <div style={{ display: "flex", flex: 1, overflow: "hidden", borderRadius: 0, border: "none", background: t.card, boxShadow: "none" }}>

            {/* ── SIDEBAR ── */}
            <div style={{
                width: sideOpen ? 200 : 0, minWidth: sideOpen ? 200 : 0, flexShrink: 0, overflow: "hidden",
                transition: "width .3s cubic-bezier(.4,0,.2,1),min-width .3s cubic-bezier(.4,0,.2,1)",
                background: t.surface, borderRight: `1px solid ${t.border}`, display: "flex", flexDirection: "column"
            }}>

                {/* New Chat button */}
                <div style={{ padding: "14px 12px 10px" }}>
                    <button onClick={() => setMsgs([])} style={{
                        width: "100%", padding: "9px 14px", borderRadius: 50,
                        background: t.primary, color: t.mode === "dark" ? "#111B1F" : "#fff",
                        border: "none", fontSize: 13, fontWeight: 700, cursor: "pointer",
                        display: "flex", alignItems: "center", justifyContent: "center", gap: 7,
                        boxShadow: `0 4px 14px ${t.primaryGlow}`, transition: "opacity .2s", whiteSpace: "nowrap"
                    }}
                        onMouseEnter={e => e.currentTarget.style.opacity = ".85"}
                        onMouseLeave={e => e.currentTarget.style.opacity = "1"}>
                        <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="16" /><line x1="8" y1="12" x2="16" y2="12" /></svg>
                        New Chat
                    </button>
                </div>

                {/* History header */}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "4px 14px 4px" }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>History</span>
                    <div style={{ display: "flex", gap: 2 }}>
                        <button style={{ background: "none", border: "none", cursor: "pointer", padding: 5, borderRadius: 7, color: t.textMuted, display: "flex" }}>
                            <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="18 15 12 9 6 15" /></svg>
                        </button>
                        <button style={{ background: "none", border: "none", cursor: "pointer", padding: 5, borderRadius: 7, color: t.textMuted, display: "flex" }}>
                            <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="5" r="1.2" /><circle cx="12" cy="12" r="1.2" /><circle cx="12" cy="19" r="1.2" /></svg>
                        </button>
                    </div>
                </div>

                {/* History list */}
                <div style={{ flex: 1, overflowY: "auto", padding: "4px 8px 8px" }}>
                    {history.map((g, gi) => (
                        <div key={gi} style={{ marginBottom: 12 }}>
                            <div style={{
                                fontSize: 10, fontWeight: 700, color: t.textMuted, padding: "5px 6px 3px",
                                textTransform: "uppercase", letterSpacing: "0.07em", display: "flex", alignItems: "center", gap: 4
                            }}>
                                <svg width={9} height={9} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 12 15 18 9" /></svg>
                                {g.group}
                            </div>
                            {g.items.map((item, ii) => (
                                <div key={ii} onClick={() => setQuery(item)}
                                    style={{
                                        padding: "8px 10px", borderRadius: 9, fontSize: 12, color: t.textMuted, cursor: "pointer",
                                        marginBottom: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", transition: "all .15s"
                                    }}
                                    onMouseEnter={e => { e.currentTarget.style.background = t.cardHi; e.currentTarget.style.color = t.text; }}
                                    onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = t.textMuted; }}>
                                    {item}
                                </div>
                            ))}
                        </div>
                    ))}
                </div>

                {/* Sidebar footer */}
                <div style={{ padding: "8px 12px 12px", borderTop: `1px solid ${t.border}` }}>
                    <button onClick={() => setSideOpen(false)} style={{
                        width: "100%", padding: "8px", borderRadius: 9, fontSize: 12,
                        background: "transparent", border: `1px solid ${t.border}`, color: t.textMuted, cursor: "pointer",
                        display: "flex", alignItems: "center", justifyContent: "center", gap: 5, transition: "all .2s"
                    }}
                        onMouseEnter={e => { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.color = t.primary; }}
                        onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textMuted; }}>
                        <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M15 18l-6-6 6-6" /></svg>
                        Collapse
                    </button>
                </div>
            </div>

            {/* ── MAIN CHAT AREA ── */}
            <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }}>

                {/* Floating top bar */}
                <div style={{
                    position: "absolute", top: 0, left: 0, right: 0, zIndex: 10,
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "14px 20px 0", pointerEvents: "none"
                }}>
                    {/* Left: expand btn + Chat label */}
                    <div style={{ display: "flex", alignItems: "center", gap: 10, pointerEvents: "auto" }}>
                        {!sideOpen && (
                            <button onClick={() => setSideOpen(true)} style={{
                                width: 34, height: 34, borderRadius: "50%",
                                background: t.primary, border: "none", display: "flex", alignItems: "center", justifyContent: "center",
                                cursor: "pointer", boxShadow: `0 4px 14px ${t.primaryGlow}`, transition: "opacity .2s"
                            }}
                                onMouseEnter={e => e.currentTarget.style.opacity = ".85"}
                                onMouseLeave={e => e.currentTarget.style.opacity = "1"}>
                                <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke={t.mode === "dark" ? "#111B1F" : "#fff"} strokeWidth="2.5"><path d="M9 18l6-6-6-6" /></svg>
                            </button>
                        )}
                        <span className="serif" style={{ fontSize: 17, fontWeight: 700, color: t.text }}>Chat</span>
                    </div>
                    {/* Right: Upgrade Plan pill */}
                    <button style={{
                        background: t.primary, color: t.mode === "dark" ? "#111B1F" : "#fff",
                        border: "none", borderRadius: 50, padding: "9px 20px", fontSize: 12, fontWeight: 700,
                        cursor: "pointer", boxShadow: `0 4px 14px ${t.primaryGlow}`, transition: "opacity .2s",
                        pointerEvents: "auto"
                    }}
                        onMouseEnter={e => e.currentTarget.style.opacity = ".85"}
                        onMouseLeave={e => e.currentTarget.style.opacity = "1"}>
                        Upgrade Plan
                    </button>
                </div>

                {/* Messages / Welcome */}
                <div style={{
                    flex: 1, overflowY: "auto",
                    display: "flex", flexDirection: "column", alignItems: "center",
                    justifyContent: hasMessages ? "flex-start" : "center",
                    padding: hasMessages ? "68px 24px 16px" : "0 24px"
                }}>

                    {!hasMessages ? (
                        /* Welcome screen */
                        <div style={{ textAlign: "center", maxWidth: 640, width: "100%", padding: "0 16px" }}>
                            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 14, marginBottom: 16 }}>
                                <span style={{ fontSize: 42 }}>{greetEmoji}</span>
                                <h2 className="serif" style={{ fontSize: 26, fontWeight: 700, color: t.text, margin: 0 }}>{greetWord}, John!</h2>
                            </div>
                            {/* Active case context pill */}
                            {activeCaseObj && (
                                <div style={{
                                    display: "inline-flex", alignItems: "center", gap: 8, padding: "8px 16px", borderRadius: 50,
                                    background: t.primaryGlow, border: `1px solid ${t.primary}40`, marginBottom: 16
                                }}>
                                    <div style={{ width: 7, height: 7, borderRadius: "50%", background: t.primary }} />
                                    <span style={{ fontSize: 12, color: t.primary, fontWeight: 600 }}>Context: {activeCaseObj.id} — {activeCaseObj.title}</span>
                                </div>
                            )}
                            <p className="serif" style={{ fontSize: activeCaseObj ? 22 : 30, fontWeight: 700, color: t.text, marginBottom: 32, lineHeight: 1.35 }}>{greetSub}</p>
                            {/* Quick prompt chips — case-aware when active */}
                            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
                                {(activeCaseObj ? [
                                    `What sections apply to ${activeCaseObj.type} cases in India?`,
                                    `Key arguments for ${activeCaseObj.title}`,
                                    `Documents needed for next hearing at ${activeCaseObj.court}`,
                                    `Recent precedents for ${activeCaseObj.type} law`
                                ] : [
                                    "Relevant sections for property dispute",
                                    "IPC sections for cheque bounce",
                                    "Bail conditions under CrPC",
                                    "Contempt of court procedure"
                                ]).map((p, i) => (
                                    <button key={i} onClick={() => setQuery(p)} style={{
                                        padding: "9px 16px", borderRadius: 50,
                                        border: `1px solid ${t.border}`, background: t.cardHi, color: t.textMuted, cursor: "pointer",
                                        fontSize: 12, fontWeight: 500, transition: "all .15s", textAlign: "left"
                                    }}
                                        onMouseEnter={e => { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.color = t.primary; e.currentTarget.style.background = t.primaryGlow2; }}
                                        onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textMuted; e.currentTarget.style.background = t.cardHi; }}>
                                        {p}
                                    </button>
                                ))}
                            </div>
                        </div>
                    ) : (
                        /* Message thread */
                        <div style={{ width: "100%", maxWidth: 800, display: "flex", flexDirection: "column", gap: 18 }}>
                            {msgs.map((m, i) => (
                                <div key={i} style={{ display: "flex", flexDirection: m.role === "user" ? "row-reverse" : "row", gap: 10, alignItems: "flex-start" }} className="fade-in">
                                    {m.role === "assistant" && (
                                        <div style={{ width: 34, height: 34, borderRadius: 10, background: t.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                                            <Icon d={I.ai} size={16} style={{ color: t.primary }} />
                                        </div>
                                    )}
                                    <div style={{ maxWidth: "75%" }}>
                                        <div style={{
                                            background: m.role === "user" ? t.grad1 : t.surface,
                                            border: m.role === "assistant" ? `1px solid ${t.border}` : "none",
                                            borderRadius: m.role === "user" ? "18px 18px 6px 18px" : "18px 18px 18px 6px",
                                            padding: "12px 16px", fontSize: 13.5, lineHeight: 1.8,
                                            color: m.role === "user" ? (t.mode === "dark" ? "#111B1F" : "#fff") : t.text,
                                            whiteSpace: "pre-wrap"
                                        }}>
                                            {m.content}
                                        </div>
                                        {m.time && <div style={{ fontSize: 10, color: t.textFaint, marginTop: 4, textAlign: m.role === "user" ? "right" : "left" }}>{m.time}</div>}
                                    </div>
                                </div>
                            ))}
                            {loading && (
                                <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                                    <div style={{ width: 34, height: 34, borderRadius: 10, background: t.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                                        <Icon d={I.ai} size={16} style={{ color: t.primary }} />
                                    </div>
                                    <div style={{ background: t.surface, border: `1px solid ${t.border}`, borderRadius: "18px 18px 18px 6px", padding: "14px 18px", display: "flex", gap: 5, alignItems: "center" }}>
                                        {[0, 1, 2].map(d => <div key={d} style={{ width: 7, height: 7, borderRadius: "50%", background: t.primary, animation: `pulse 1.2s ease ${d * .2}s infinite` }} />)}
                                    </div>
                                </div>
                            )}
                            <div ref={bottomRef} />
                        </div>
                    )}
                </div>

                {/* ── Rich input box ── */}
                <div style={{ padding: "0 24px 18px", display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                    <div style={{
                        width: "100%", maxWidth: 800,
                        background: t.mode === "dark" ? "rgba(20,42,50,0.97)" : t.surface,
                        border: `1.5px solid ${t.border}`, borderRadius: 18,
                        padding: "13px 15px 11px 18px", boxShadow: t.shadowCard
                    }}>

                        {/* Text input */}
                        <input value={query} onChange={e => setQuery(e.target.value)}
                            onKeyDown={e => e.key === "Enter" && !e.shiftKey && send()}
                            placeholder="Ask AI Attorney..."
                            style={{
                                width: "100%", background: "transparent", border: "none", outline: "none",
                                color: t.text, fontSize: 14, padding: "3px 0 10px", lineHeight: 1.6
                            }} />

                        {/* Toolbar row */}
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                            {/* Search globe button */}
                            <button style={{
                                display: "flex", alignItems: "center", gap: 6,
                                background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 50,
                                padding: "6px 14px", fontSize: 12, color: t.textMuted, cursor: "pointer", transition: "all .15s"
                            }}
                                onMouseEnter={e => { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.color = t.primary; }}
                                onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textMuted; }}>
                                <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                    <circle cx="12" cy="12" r="10" /><path d="M2 12h20" /><ellipse cx="12" cy="12" rx="4" ry="10" />
                                </svg>
                                Search
                            </button>

                            {/* Right controls */}
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                {/* Clock / history */}
                                <button style={{ background: "none", border: "none", cursor: "pointer", padding: 6, borderRadius: 8, color: t.textMuted, display: "flex", transition: "all .15s" }}
                                    onMouseEnter={e => { e.currentTarget.style.background = t.cardHi; e.currentTarget.style.color = t.primary; }}
                                    onMouseLeave={e => { e.currentTarget.style.background = "none"; e.currentTarget.style.color = t.textMuted; }}>
                                    <Icon d={I.clock} size={16} />
                                </button>

                                {/* Pro badge */}
                                <span style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 6, padding: "3px 9px" }}>Pro</span>

                                {/* EN / UR language toggle */}
                                <div style={{ display: "flex", borderRadius: 8, overflow: "hidden", border: `1px solid ${t.border}`, background: t.inputBg }}>
                                    {["EN", "UR"].map(l => (
                                        <button key={l} onClick={() => setLang(l)}
                                            style={{
                                                padding: "4px 11px", fontSize: 11, fontWeight: 700, border: "none", cursor: "pointer",
                                                background: lang === l ? t.primary : "transparent",
                                                color: lang === l ? (t.mode === "dark" ? "#111B1F" : "#fff") : t.textMuted,
                                                transition: "all .15s"
                                            }}>
                                            {l}
                                        </button>
                                    ))}
                                </div>

                                {/* Mic */}
                                <button style={{ background: "none", border: "none", cursor: "pointer", padding: 6, borderRadius: 8, color: t.textMuted, display: "flex", transition: "all .15s" }}
                                    onMouseEnter={e => { e.currentTarget.style.background = t.cardHi; e.currentTarget.style.color = t.primary; }}
                                    onMouseLeave={e => { e.currentTarget.style.background = "none"; e.currentTarget.style.color = t.textMuted; }}>
                                    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                                        <rect x="9" y="2" width="6" height="11" rx="3" /><path d="M19 10a7 7 0 01-14 0" /><line x1="12" y1="19" x2="12" y2="22" /><line x1="8" y1="22" x2="16" y2="22" />
                                    </svg>
                                </button>

                                {/* Send button */}
                                <button onClick={send} style={{
                                    width: 36, height: 36, borderRadius: 10,
                                    background: query.trim() ? t.primary : t.inputBg,
                                    border: `1.5px solid ${query.trim() ? t.primary : t.border}`,
                                    display: "flex", alignItems: "center", justifyContent: "center",
                                    cursor: query.trim() ? "pointer" : "default",
                                    transition: "all .2s", transform: "rotate(45deg)",
                                    boxShadow: query.trim() ? `0 4px 12px ${t.primaryGlow}` : "none"
                                }}>
                                    <Icon d={I.send} size={15} style={{ color: query.trim() ? (t.mode === "dark" ? "#111B1F" : "#fff") : t.textMuted }} />
                                </button>
                            </div>
                        </div>
                    </div>
                    <div style={{ marginTop: 7, fontSize: 11, color: t.textFaint, textAlign: "center" }}>
                        Authentic citations only. Verify applicability before use.
                    </div>
                </div>
            </div>
        </div>
    );
}
export { AILegalPage };
