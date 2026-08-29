'use client';
import React, { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useT } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import { useCase } from "@/components/shared/CaseContext.jsx";
import { getToken, rateAnswer, getWsTicket } from "@/lib/api.js";
import { useAuth } from "@/context/AuthContext.jsx";
import Ic from "./Ic.jsx";
import { Badge, Tooltip } from "@/components/shared/shared.jsx";

const WS_BASE = (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_WS_URL) || "ws://localhost:8000";

/* Calibrated-confidence bands come from the server (ai/answer_confidence.py).
   The client shows the BAND only — the raw calibrated figure runs far lower than
   the model's old self-report, and a bare "24%" reads as broken to a non-lawyer
   when it is in fact a normal, honest score. The lawyer surface shows both. */
const CONF_LABEL = { high: "High", moderate: "Moderate", low: "Low" };
const CONF_COLOR = { high: "#22c55e", moderate: "#f59e0b", low: "#ef4444" };

/* Per-statement support verdicts from the grounding judge (answer_citations.py).
   Worded for a non-lawyer, and worded carefully: `unassessed` must read as "we
   did not check", never as "it passed". A statement we could not check is not a
   statement we approved. */
const CLAIM_UI = {
    supported:   { icon: "✓", color: "#22c55e", text: "Backed by the source it cites" },
    partial:     { icon: "!", color: "#f59e0b", text: "Goes further than its source says" },
    unsupported: { icon: "✕", color: "#ef4444", text: "Its source does not establish this" },
    unassessed:  { icon: "–", color: "#94a3b8", text: "Not checked against a source" },
};
const CLAIM_ORDER = ["unsupported", "partial", "unassessed", "supported"];

/* Repeal currency (answer_citations.currency_for). Exactly two values reach the
   UI — `repealed` and `unknown` — and `unknown` must never be dressed up as a
   clean bill of health: repeal data covers 4 of 43 statutes, so silence is
   absence of evidence, not evidence of currency. A repealed provision OVERRIDES
   matched/supported: a source can genuinely say what the answer claims and
   still be law that was abolished. */
const REPEALED = "repealed";
const CURRENCY_TEXT = {
    repealed: "Repealed provision — do not rely on this authority",
    unknown:  "Current status not verified",
};
const repealNote = (c) => {
    const bits = [c.instrument, c.date].filter(Boolean).join(", ");
    return bits ? `Repealed by ${bits}` : "";
};

/* ══════════════════════════════════════════════════════
   MODULE: AI CHATBOT  (WebSocket-backed)
══════════════════════════════════════════════════════ */
const ModChatbot = () => {
    const t = useT();
    const toast = useToast();
    const router = useRouter();
    const { caseType } = useCase();
    const { user } = useAuth();

    /* ── UI state ─────────────────────────────────────────────────────── */
    const [msgs, setMsgs] = useState([]);
    const [inp, setInp] = useState("");
    const [typing, setTyping] = useState(false);
    const [lang, setLang] = useState("EN");
    const [sideOpen, setSideOpen] = useState(true);
    const [webSearch, setWebSearch] = useState(false);
    const [listening, setListening] = useState(false);
    const [history, setHistory] = useState([
        { group: "This Week", items: [] },
        { group: "Last Week", items: ["Contract dispute analysis", "NDA review help"] },
    ]);

    /* ── WebSocket state ──────────────────────────────────────────────── */
    const wsRef = useRef(null);
    const sessionIdRef = useRef(null);
    const bottomRef = useRef(null);
    const retryRef = useRef(null);
    const stableRef = useRef(null); // timer to reset retry count after stable connection
    const retryCount = useRef(0);
    const listeningRef = useRef(false); // mirror of `listening` state for WS closures
    const [wsStatus, setWsStatus] = useState("disconnected");

    /* Generate a stable session ID per component mount */
    if (!sessionIdRef.current) {
        sessionIdRef.current =
            typeof crypto !== "undefined" && crypto.randomUUID
                ? crypto.randomUUID()
                : `chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    }

    /* ── WebSocket connect ────────────────────────────────────────────── */
    const connect = useCallback(async () => {
        const token = getToken();
        if (!token) return;                              // not logged in
        if (wsRef.current?.readyState === WebSocket.OPEN) return;  // already open

        const sid = sessionIdRef.current;

        // Exchange access token for a one-time 60-second WS ticket.
        // Never put the JWT itself in the URL — it ends up in server logs.
        // getWsTicket goes through apiFetch, so an expired access token is
        // refreshed and retried instead of silently failing the connect.
        const ticket = await getWsTicket();
        if (!ticket) return;

        const url = `${WS_BASE}/ws/chat/${sid}?ticket=${encodeURIComponent(ticket)}`;

        setWsStatus("connecting");
        const ws = new WebSocket(url);

        ws.onopen = () => {
            setWsStatus("connected");
            // Reset retry count only after the connection has been stable for 10 s
            // (not immediately on open — that caused an infinite retry loop)
            clearTimeout(stableRef.current);
            stableRef.current = setTimeout(() => { retryCount.current = 0; }, 10000);
        };
        ws.onclose = () => {
            clearTimeout(stableRef.current);
            setWsStatus("disconnected");
            // Don't retry while mic is active — Chrome drops WS when SpeechRecognition
            // grabs the audio device; reconnect happens in rec.onend instead
            if (listeningRef.current) return;
            if (retryCount.current < 5) {
                const delay = Math.min(1000 * 2 ** retryCount.current, 30000);
                retryCount.current += 1;
                retryRef.current = setTimeout(connect, delay);
            }
        };
        ws.onerror = () => { ws.close(); };

        ws.onmessage = (event) => {
            let msg;
            try { msg = JSON.parse(event.data); } catch { return; }

            const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

            if (msg.type === "thinking") {
                setTyping(true);

            } else if (msg.type === "final") {
                setTyping(false);
                // Keep the objects: `status` says whether the answer actually
                // cited a source or whether it was merely consulted, and the two
                // must not be presented as the same thing.
                const citations = (msg.citations || [])
                    .map(c => ({
                        label: [c.statute, c.section ? `§${c.section}` : ""].filter(Boolean).join(" "),
                        status: c.status || "retrieved",
                        currency: c.currency || "unknown",
                        instrument: c.instrument || "",
                        date: c.date || "",
                    }))
                    .filter(c => c.label);
                setMsgs(m => [...m, {
                    role: "ai",
                    text: msg.content || "",
                    time: now,
                    refs: citations,
                    claims: msg.claims || [],
                    confidence: msg.confidence,
                    confidenceBand: msg.confidence_band,
                    status: msg.convergence_status,
                    matchedLawyers: msg.suggest_lawyer ? (msg.matched_lawyers || []) : [],
                    suggestLawyer: !!msg.suggest_lawyer,
                }]);

            } else if (msg.type === "clarification") {
                setTyping(false);
                setMsgs(m => [...m, {
                    role: "ai",
                    text: msg.question || "",
                    time: now,
                    refs: [],
                    isClarification: true,
                    matchedLawyers: msg.matched_lawyers || [],
                }]);

            } else if (msg.type === "error") {
                setTyping(false);
                toast.show("AI pipeline error — please try again.", "error", 3000);
                setMsgs(m => [...m, {
                    role: "ai",
                    text: msg.content || "AI assistant temporarily unavailable.",
                    time: now,
                    refs: [],
                    isError: true,
                }]);
            }
        };

        wsRef.current = ws;
    }, []);   // sessionIdRef is a ref — no dep needed

    /* Connect on mount, close on unmount */
    useEffect(() => {
        connect();
        return () => {
            clearTimeout(retryRef.current);
            clearTimeout(stableRef.current);
            retryCount.current = 99;
            listeningRef.current = false;
            wsRef.current?.close();
        };
    }, [connect]);

    /* Auto-scroll to latest message */
    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [msgs, typing]);

    /* ── New chat ─────────────────────────────────────────────────────── */
    const newChat = () => {
        clearTimeout(retryRef.current);
        retryCount.current = 0;
        wsRef.current?.close();
        sessionIdRef.current =
            typeof crypto !== "undefined" && crypto.randomUUID
                ? crypto.randomUUID()
                : `chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        setMsgs([]);
        setTyping(false);
        connect();
    };

    /* ── Send message ─────────────────────────────────────────────────── */
    const send = () => {
        if (!inp.trim()) return;

        /* Reconnect if socket dropped */
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
            toast.show("Reconnecting...", "info", 1500);
            connect();
            return;
        }

        const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        const txt = inp.trim();

        setMsgs(m => [...m, { role: "user", text: txt, time: now }]);
        setInp("");

        /* Update sidebar history */
        setHistory(prev => {
            const updated = [...prev];
            if (updated[0] && !updated[0].items.includes(txt))
                updated[0] = { ...updated[0], items: [txt, ...updated[0].items.slice(0, 9)] };
            return updated;
        });

        const caseId = typeof window !== "undefined" ? localStorage.getItem("aai-case-id") : null;

        wsRef.current.send(JSON.stringify({
            content: txt,
            case_id: caseId || null,
            case_type: caseType || null,
            province: null,
            language: lang === "UR" ? "ur" : "en",
            web_search: webSearch,
        }));
    };

    /* ── Voice input ─────────────────────────────────────────────────── */
    const startVoice = () => {
        const SR = typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);
        if (!SR) { toast.show("Voice input not supported in this browser.", "warn", 3000); return; }
        if (listening) return;

        const rec = new SR();
        rec.lang = lang === "UR" ? "ur-PK" : "en-US";
        rec.continuous = false;
        rec.interimResults = false;

        rec.onstart = () => { setListening(true); listeningRef.current = true; };
        rec.onend = () => {
            setListening(false);
            listeningRef.current = false;
            // Reconnect WS if it dropped while mic was active
            if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
                retryCount.current = 0;
                connect();
            }
        };
        rec.onerror = () => {
            setListening(false);
            listeningRef.current = false;
            toast.show("Voice recognition failed — please try again.", "error", 2500);
        };
        rec.onresult = (e) => {
            const transcript = e.results[0][0].transcript;
            setInp(prev => prev ? `${prev} ${transcript}` : transcript);
        };
        rec.start();
    };

    const hasMessages = msgs.length > 0;

    /* ── Shared icon-button style ─────────────────────────────────────── */
    const iconBtn = (extra = {}) => ({
        background: "none", border: "none", cursor: "pointer", padding: 6,
        borderRadius: 8, color: t.textMuted, display: "flex",
        alignItems: "center", justifyContent: "center",
        transition: "background 0.15s, color 0.15s", ...extra,
    });

    /* ── WS status dot ────────────────────────────────────────────────── */
    const dotColor = { connected: "#22c55e", connecting: "#f59e0b", disconnected: "#ef4444" }[wsStatus];

    /* ── Greeting ─────────────────────────────────────────────────────── */
    const h = new Date().getHours();
    const greetingText = h < 12 ? "Good Morning" : h < 17 ? "Good Afternoon" : "Good Evening";
    const greetingEmoji = h < 12 ? "🌅" : h < 17 ? "⛅" : "🌙";
    const greetingSub = h >= 20 || h < 5
        ? "Dark mode is on. What are we researching?"
        : "The details are in the dark. Let's find them.";

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
                    <button onClick={newChat} style={{
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

                {/* Sidebar footer */}
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

                {/* Top-left label + expand button */}
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
                    {/* WS status dot */}
                    <Tooltip text={wsStatus}>
                        <span style={{
                            width: 8, height: 8, borderRadius: "50%",
                            background: dotColor, display: "inline-block",
                            pointerEvents: "auto",
                        }} />
                    </Tooltip>
                </div>

                {/* Top-right: Upgrade pill */}
                <div style={{ position: "absolute", top: 12, right: 18, zIndex: 10 }}>
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
                        <div style={{ textAlign: "center", maxWidth: 600, width: "100%", padding: "0 20px" }}>
                            {/* Robot mascot */}
                            <div style={{ marginBottom: 24, display: "flex", justifyContent: "center" }}>
                                <div style={{
                                    width: 160, height: 160, borderRadius: "50%",
                                    background: `radial-gradient(circle at 50% 60%, ${t.primary}25, ${t.primary}08 70%)`,
                                    display: "flex", alignItems: "center", justifyContent: "center",
                                    boxShadow: `0 0 50px ${t.primary}20`,
                                }}>
                                    <img src="/chatbot.gif" alt="AI Assistant" style={{ width: 130, height: 130, objectFit: "contain" }} />
                                </div>
                            </div>
                            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10, marginBottom: 10 }}>
                                <span style={{ fontSize: 26 }}>{greetingEmoji}</span>
                                <h2 style={{
                                    fontFamily: "'Playfair Display',serif", fontSize: 24, fontWeight: 700,
                                    color: t.text, margin: 0, letterSpacing: "-0.4px",
                                }}>{greetingText}, {user?.full_name?.split(" ")[0] || "there"}!</h2>
                            </div>
                            <p style={{
                                fontFamily: "'Playfair Display',serif", fontSize: 28, fontWeight: 700,
                                color: t.text, marginBottom: 44, lineHeight: 1.35, letterSpacing: "-0.6px",
                            }}>{greetingSub}</p>
                            {wsStatus === "disconnected" && (
                                <p style={{ fontSize: 13, color: t.textMuted, marginTop: 8 }}>
                                    AI chat unavailable — please sign in again.
                                </p>
                            )}
                        </div>
                    ) : (
                        <div style={{ width: "100%", maxWidth: 820, display: "flex", flexDirection: "column", gap: 18 }}>
                            {msgs.map((m, i) => (
                                <div key={i} style={{
                                    display: "flex",
                                    flexDirection: m.role === "user" ? "row-reverse" : "row",
                                    gap: 10, alignItems: "flex-start",
                                }}>
                                    {m.role === "ai" && (
                                        <div style={{
                                            width: 36, height: 36, borderRadius: 10,
                                            background: m.isError ? "#fee2e2" : t.primaryGlow,
                                            border: `1px solid ${m.isError ? "#fca5a5" : t.primary + "30"}`,
                                            flexShrink: 0,
                                            display: "flex", alignItems: "center", justifyContent: "center",
                                            overflow: "hidden",
                                        }}>
                                            {m.isError
                                                ? <Ic n="scale" s={16} c="#ef4444" />
                                                : <img src="/chatbot.gif" alt="AI" style={{ width: 30, height: 30, objectFit: "contain" }} />
                                            }
                                        </div>
                                    )}
                                    <div style={{ maxWidth: "75%" }}>
                                        <div style={{
                                            background: m.role === "user" ? t.grad1 : t.surface,
                                            border: m.role === "ai" ? `1px solid ${m.isClarification ? t.primary : t.border}` : "none",
                                            borderRadius: m.role === "user" ? "18px 18px 6px 18px" : "18px 18px 18px 6px",
                                            padding: "13px 17px", fontSize: 13.5, lineHeight: 1.8,
                                            color: m.role === "user" ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.text,
                                            whiteSpace: "pre-wrap",
                                        }}>
                                            {m.isClarification && (
                                                <div style={{ fontSize: 11, color: t.primary, fontWeight: 700, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.5px" }}>
                                                    Clarification needed
                                                </div>
                                            )}
                                            {m.text}
                                        </div>
                                        {/* Statement checks. Surfaced ABOVE the sources panel and
                                            with a always-visible warning line, because the finding
                                            that matters most — "this sentence is not backed by the
                                            law it cites" — is worthless hidden behind a click. */}
                                        {m.claims?.length > 0 && (() => {
                                            const repealed = m.claims.filter(c => c.currency === REPEALED);
                                            const flagged = m.claims.filter(
                                                c => c.support === "unsupported" || c.support === "partial");
                                            const sorted = [...m.claims].sort(
                                                (a, b) => CLAIM_ORDER.indexOf(a.support) - CLAIM_ORDER.indexOf(b.support));
                                            return (
                                                <div style={{ marginTop: 8 }}>
                                                    {repealed.length > 0 && (
                                                        <div style={{
                                                            fontSize: 12, color: "#ef4444", fontWeight: 700,
                                                            marginBottom: 6, padding: "7px 10px", borderRadius: 8,
                                                            background: "#ef444414", border: "1px solid #ef444455",
                                                        }}>
                                                            {"\u26D4"} {CURRENCY_TEXT.repealed}
                                                            <div style={{ fontWeight: 400, fontSize: 11, marginTop: 3 }}>
                                                                {repealed.length === 1 ? "1 statement relies" : `${repealed.length} statements rely`}
                                                                {" "}on law that has been repealed. Speak to a lawyer before acting on this answer.
                                                            </div>
                                                        </div>
                                                    )}
                                                    {flagged.length > 0 && (
                                                        <div style={{
                                                            fontSize: 11.5, color: "#f59e0b", fontWeight: 600,
                                                            marginBottom: 6, display: "flex", gap: 6, alignItems: "center",
                                                        }}>
                                                            ⚠ {flagged.length === 1
                                                                ? "1 statement isn't fully backed by the law it cites"
                                                                : `${flagged.length} statements aren't fully backed by the law they cite`}
                                                        </div>
                                                    )}
                                                    <button
                                                        onClick={() => setMsgs(prev => prev.map((x, xi) => xi === i ? { ...x, claimsOpen: !x.claimsOpen } : x))}
                                                        style={{
                                                            display: "inline-flex", alignItems: "center", gap: 6,
                                                            padding: "5px 12px", borderRadius: 8, fontSize: 11.5, fontWeight: 700,
                                                            border: `1px solid ${t.border}`, background: m.claimsOpen ? t.primaryGlow : "transparent",
                                                            color: t.primary, cursor: "pointer", fontFamily: "inherit",
                                                        }}>
                                                        🔍 Statement checks ({m.claims.length}) {m.claimsOpen ? "▴" : "▾"}
                                                    </button>
                                                    {m.claimsOpen && (
                                                        <div style={{
                                                            marginTop: 6, padding: "10px 12px", borderRadius: 10,
                                                            background: t.surface, border: `1px solid ${t.border}`,
                                                            display: "flex", flexDirection: "column", gap: 9,
                                                        }}>
                                                            {sorted.map((c, ci) => {
                                                                // A repealed source OVERRIDES the support verdict. The source
                                                                // may genuinely say what the claim says and still be law that
                                                                // no longer exists — the more important fact, and the one a
                                                                // reader cannot spot unaided.
                                                                const dead = c.currency === REPEALED;
                                                                const ui = dead
                                                                    ? { icon: "\u26D4", color: "#ef4444", text: CURRENCY_TEXT.repealed }
                                                                    : (CLAIM_UI[c.support] || CLAIM_UI.unassessed);
                                                                return (
                                                                    <div key={ci} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                                                                        <span style={{
                                                                            color: ui.color, fontWeight: 700, fontSize: 12,
                                                                            lineHeight: "1.5", flexShrink: 0, width: 12, textAlign: "center",
                                                                        }}>{ui.icon}</span>
                                                                        <div style={{ minWidth: 0 }}>
                                                                            <div style={{ fontSize: 12, color: t.textDim, lineHeight: 1.5 }}>
                                                                                “{c.text}”
                                                                            </div>
                                                                            <div style={{ fontSize: 10.5, color: ui.color, marginTop: 2 }}>
                                                                                {ui.text}
                                                                                {dead && (c.sources || []).map(repealNote).filter(Boolean).length > 0 && (
                                                                                    <span style={{ color: t.textFaint }}>
                                                                                        {" \u2014 "}{(c.sources || []).map(repealNote).filter(Boolean).join("; ")}
                                                                                    </span>
                                                                                )}
                                                                                {c.sources?.length > 0 && (
                                                                                    <span style={{ color: t.textFaint }}>
                                                                                        {" — "}{c.sources.map(sc => [sc.statute, sc.section ? `§${sc.section}` : ""].filter(Boolean).join(" ")).join("; ")}
                                                                                    </span>
                                                                                )}
                                                                            </div>
                                                                        </div>
                                                                    </div>
                                                                );
                                                            })}
                                                            <div style={{ fontSize: 10, color: t.textFaint, borderTop: `1px solid ${t.border}`, paddingTop: 7 }}>
                                                                These checks compare each statement against the law sections we
                                                                retrieved. Where a provision is not marked repealed its current
                                                                status is simply not verified — that is not a confirmation it is
                                                                still in force. Not a substitute for a lawyer.
                                                            </div>
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        })()}
                                        {m.refs?.length > 0 && (
                                            <div style={{ marginTop: 8 }}>
                                                <button
                                                    onClick={() => setMsgs(prev => prev.map((x, xi) => xi === i ? { ...x, refsOpen: !x.refsOpen } : x))}
                                                    style={{
                                                        display: "inline-flex", alignItems: "center", gap: 6,
                                                        padding: "5px 12px", borderRadius: 8, fontSize: 11.5, fontWeight: 700,
                                                        border: `1px solid ${t.border}`, background: m.refsOpen ? t.primaryGlow : "transparent",
                                                        color: t.primary, cursor: "pointer", fontFamily: "inherit",
                                                    }}>
                                                    📖 {m.refs.some(r => r.status === "matched" || r.status === "unresolved")
                                                        ? `Cited in this answer (${m.refs.filter(r => r.status !== "retrieved").length})`
                                                        : `Sources consulted (${m.refs.length})`} {m.refsOpen ? "▴" : "▾"}
                                                </button>
                                                {m.refsOpen && (
                                                    <div style={{
                                                        marginTop: 6, padding: "10px 12px", borderRadius: 10,
                                                        background: t.surface, border: `1px solid ${t.border}`,
                                                    }}>
                                                        <div style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
                                                            Verify before relying on them
                                                        </div>
                                                        {[
                                                            ["matched", "Cited by this answer, found in our law sources"],
                                                            ["unresolved", "Cited by this answer — we could not locate it in our sources"],
                                                            ["retrieved", "Consulted, not cited in this answer"],
                                                        ].map(([key, caption]) => {
                                                            const group = m.refs.filter(r => r.status === key);
                                                            if (!group.length) return null;
                                                            return (
                                                                <div key={key} style={{ marginBottom: 8 }}>
                                                                    <div style={{ fontSize: 10, color: key === "unresolved" ? "#f59e0b" : t.textFaint, marginBottom: 4 }}>
                                                                        {caption}
                                                                    </div>
                                                                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                                                                        {group.map((r, ri) => (
                                                                            // A repealed chip is red whatever its match status:
                                                                            // being cited AND retrieved says nothing about
                                                                            // whether the provision still exists.
                                                                            <Badge key={ri} type={r.currency === REPEALED ? "danger" : key === "unresolved" ? "warn" : "info"}>
                                                                                {r.currency === REPEALED ? "⛔ " : key === "matched" ? "✓ " : key === "unresolved" ? "? " : ""}{r.label}
                                                                                {r.currency === REPEALED ? " — repealed" : ""}
                                                                            </Badge>
                                                                        ))}
                                                                    </div>
                                                                </div>
                                                            );
                                                        })}
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                        {/* Rating — every substantive AI answer */}
                                        {m.role === "ai" && !m.isError && !m.isClarification && m.text && (
                                            <div style={{ marginTop: 6, display: "flex", gap: 4, alignItems: "center" }}>
                                                {m.rated ? (
                                                    <span style={{ fontSize: 11, color: t.textMuted }}>
                                                        {m.rated === "up" ? "Thanks for the feedback 👍" : "Thanks — we'll use this to improve 👎"}
                                                    </span>
                                                ) : (
                                                    ["up", "down"].map(r => (
                                                        <button key={r}
                                                            onClick={() => {
                                                                setMsgs(prev => prev.map((x, xi) => xi === i ? { ...x, rated: r } : x));
                                                                rateAnswer({
                                                                    session_id: sessionIdRef.current || "unknown",
                                                                    rating: r,
                                                                    answer_preview: (m.text || "").slice(0, 300),
                                                                    question_preview: (msgs[i - 1]?.text || "").slice(0, 300),
                                                                    source: "chat",
                                                                }).catch(() => { });
                                                            }}
                                                            style={{
                                                                width: 26, height: 26, borderRadius: 7, cursor: "pointer",
                                                                border: `1px solid ${t.border}`, background: "transparent",
                                                                fontSize: 12, display: "flex", alignItems: "center", justifyContent: "center",
                                                            }}
                                                            title={r === "up" ? "Helpful" : "Not helpful"}
                                                        >{r === "up" ? "👍" : "👎"}</button>
                                                    ))
                                                )}
                                            </div>
                                        )}
                                        {/* Lawyer connect card — shown on HITL or max_attempts */}
                                        {m.matchedLawyers?.length > 0 && (
                                            <div style={{
                                                marginTop: 12,
                                                background: t.mode === "dark" ? "rgba(0,196,159,0.07)" : "rgba(0,196,159,0.06)",
                                                border: `1.5px solid ${t.primary}`,
                                                borderRadius: 14, padding: "14px 16px",
                                            }}>
                                                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                                                    <Ic n="scale" s={15} c={t.primary} />
                                                    <span style={{ fontSize: 12.5, fontWeight: 700, color: t.primary }}>
                                                        {m.suggestLawyer ? "AI reached its limit — consult a lawyer" : "Connect with a lawyer for personalized advice"}
                                                    </span>
                                                </div>
                                                <div style={{ display: "flex", flexDirection: "column", gap: 7, marginBottom: 12 }}>
                                                    {m.matchedLawyers.map((l, li) => (
                                                        <div key={li} style={{
                                                            background: t.surface,
                                                            border: `1px solid ${t.border}`,
                                                            borderRadius: 10, padding: "9px 12px",
                                                            display: "flex", justifyContent: "space-between",
                                                            alignItems: "center", gap: 8,
                                                        }}>
                                                            <div style={{ flex: 1, minWidth: 0 }}>
                                                                <div style={{ fontWeight: 700, fontSize: 13, color: t.text, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                                                    {l.full_name}
                                                                </div>
                                                                <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>
                                                                    {l.province} · {Math.round((l.match_score || 0) * 100)}% match
                                                                    {l.rating > 0 && ` · ★ ${l.rating.toFixed(1)}`}
                                                                </div>
                                                                {l.specializations?.length > 0 && (
                                                                    <div style={{ fontSize: 11, color: t.textDim, marginTop: 2 }}>
                                                                        {l.specializations.slice(0, 2).join(" · ")}
                                                                    </div>
                                                                )}
                                                            </div>
                                                        </div>
                                                    ))}
                                                </div>
                                                <button
                                                    onClick={() => router.push("/lawyers")}
                                                    style={{
                                                        width: "100%", padding: "9px 0",
                                                        background: t.primary,
                                                        color: t.mode === "dark" ? "#1A2E35" : "#fff",
                                                        border: "none", borderRadius: 10,
                                                        fontSize: 12.5, fontWeight: 700,
                                                        cursor: "pointer", fontFamily: "'Inter',sans-serif",
                                                        transition: "opacity 0.2s",
                                                    }}
                                                    onMouseEnter={e => e.currentTarget.style.opacity = "0.85"}
                                                    onMouseLeave={e => e.currentTarget.style.opacity = "1"}
                                                >
                                                    Book Consultation →
                                                </button>
                                            </div>
                                        )}
                                        <div style={{ fontSize: 10, color: t.textFaint, marginTop: 5, textAlign: m.role === "user" ? "right" : "left" }}>
                                            {m.time}
                                            {m.role === "ai" && !m.isError && !m.isClarification && m.text && (
                                                m.confidenceBand ? (
                                                    <span style={{ marginLeft: 8, color: CONF_COLOR[m.confidenceBand] || t.textMuted }}>
                                                        ⬤ {CONF_LABEL[m.confidenceBand]} confidence
                                                    </span>
                                                ) : (
                                                    <span style={{ marginLeft: 8, color: t.textFaint }}>
                                                        Confidence not calibrated
                                                    </span>
                                                )
                                            )}
                                        </div>
                                    </div>
                                </div>
                            ))}

                            {/* Typing indicator */}
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
                            <div ref={bottomRef} />
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
                        <input
                            value={inp}
                            onChange={e => setInp(e.target.value)}
                            onKeyDown={e => e.key === "Enter" && !e.shiftKey && send()}
                            placeholder={wsStatus === "connected" ? "Ask Attorney AI..." : wsStatus === "connecting" ? "Connecting..." : "Offline — reconnecting..."}
                            style={{
                                width: "100%", background: "transparent", border: "none", outline: "none",
                                color: t.text, fontSize: 15, fontFamily: "'Inter',sans-serif",
                                padding: "4px 0 12px", lineHeight: 1.6,
                            }}
                        />

                        {/* Bottom toolbar */}
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                            {/* Toggle sidebar */}
                            <button onClick={() => setSideOpen(o => !o)} style={{
                                display: "flex", alignItems: "center", gap: 7,
                                background: t.inputBg, border: `1px solid ${t.border}`,
                                borderRadius: 50, padding: "7px 16px",
                                fontSize: 13, color: t.textMuted, cursor: "pointer",
                                fontFamily: "'Inter',sans-serif", transition: "all 0.15s",
                            }}
                                onMouseEnter={e => { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.color = t.primary; }}
                                onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textMuted; }}
                            >
                                <Ic n="clock" s={14} c="currentColor" />
                                History
                            </button>

                            {/* Right controls */}
                            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                                {/* Web search toggle */}
                                <button
                                    onClick={() => setWebSearch(s => !s)}
                                    title={webSearch ? "Web search ON — click to disable" : "Enable web search"}
                                    style={{
                                        display: "flex", alignItems: "center", gap: 6,
                                        background: webSearch ? `${t.primary}18` : t.inputBg,
                                        border: `1px solid ${webSearch ? t.primary : t.border}`,
                                        borderRadius: 50, padding: "7px 14px",
                                        fontSize: 12, color: webSearch ? t.primary : t.textMuted,
                                        cursor: "pointer", fontFamily: "'Inter',sans-serif",
                                        transition: "all 0.15s", fontWeight: webSearch ? 700 : 400,
                                    }}
                                    onMouseEnter={e => { if (!webSearch) { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.color = t.primary; } }}
                                    onMouseLeave={e => { if (!webSearch) { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textMuted; } }}
                                >
                                    <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                        <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
                                    </svg>
                                    Web
                                </button>

                                {/* Mic button */}
                                <button
                                    onClick={startVoice}
                                    title={listening ? "Listening…" : "Voice input"}
                                    style={{
                                        width: 36, height: 36, borderRadius: 10,
                                        background: listening ? `${t.primary}22` : t.inputBg,
                                        border: `1.5px solid ${listening ? t.primary : t.border}`,
                                        display: "flex", alignItems: "center", justifyContent: "center",
                                        cursor: "pointer", transition: "all 0.2s",
                                        animation: listening ? "pulse 1s ease infinite" : "none",
                                    }}
                                >
                                    <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke={listening ? t.primary : t.textMuted} strokeWidth="2">
                                        <rect x="9" y="2" width="6" height="11" rx="3" />
                                        <path d="M5 10a7 7 0 0 0 14 0" />
                                        <line x1="12" y1="19" x2="12" y2="23" />
                                        <line x1="8" y1="23" x2="16" y2="23" />
                                    </svg>
                                </button>

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

                                {/* Send */}
                                <button
                                    onClick={send}
                                    disabled={!inp.trim() || wsStatus !== "connected"}
                                    style={{
                                        width: 36, height: 36, borderRadius: 10,
                                        background: inp.trim() && wsStatus === "connected" ? t.primary : t.inputBg,
                                        border: `1.5px solid ${inp.trim() && wsStatus === "connected" ? t.primary : t.border}`,
                                        display: "flex", alignItems: "center", justifyContent: "center",
                                        cursor: inp.trim() && wsStatus === "connected" ? "pointer" : "default",
                                        transition: "all 0.2s", transform: "rotate(45deg)",
                                        boxShadow: inp.trim() && wsStatus === "connected" ? `0 4px 12px ${t.primaryGlow}` : "none",
                                    }}>
                                    <Ic n="send" s={16} c={inp.trim() && wsStatus === "connected" ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.textMuted} />
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* Disclaimer */}
                    <div style={{ marginTop: 8, fontSize: 11, color: t.textFaint, textAlign: "center" }}>
                        Informational only — not legal advice. Verify with a qualified Pakistani lawyer.
                    </div>
                </div>

            </div>
        </div>
    );
};

export default ModChatbot;
