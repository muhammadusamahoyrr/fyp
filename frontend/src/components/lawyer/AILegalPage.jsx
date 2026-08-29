'use client';
// Lawyer AI Legal Page — paste your code here
import { useState, useEffect, useRef } from "react";
import { useTheme } from "./theme.js";
import { useCase } from "./theme.js";
import { Icon, I } from "./icons.jsx";
import { listCases, aiResearch, rateAnswer } from "@/lib/api.js";
import { useAuth } from "@/context/AuthContext.jsx";

/* Calibrated-confidence bands from the server (ai/answer_confidence.py).
   The lawyer surface shows the band AND the raw figure AND which evidence source
   produced it — a research user needs the number; a client does not. */
const CONF_LABEL = { high: "High", moderate: "Moderate", low: "Low" };
const CONF_COLOR = { high: "#22c55e", moderate: "#f59e0b", low: "#ef4444" };

/* Per-claim support verdicts (answer_citations.py). The lawyer wording states
   the legal question precisely rather than reassuringly: "supported" means the
   cited section establishes the proposition, nothing more. It does NOT speak to
   whether the section is still in force — that is citation_verification's
   OMITTED verdict, which runs on the drafting path, not here. */
const CLAIM_UI = {
    supported:   { icon: "✓", color: "#22c55e", label: "Supported",   note: "cited source establishes this" },
    partial:     { icon: "◐", color: "#f59e0b", label: "Partial",     note: "claim goes beyond what the source states" },
    unsupported: { icon: "✕", color: "#ef4444", label: "Unsupported", note: "cited source does not establish this" },
    unassessed:  { icon: "–", color: "#94a3b8", label: "Unassessed",  note: "not checked — no resolvable source" },
};
const CLAIM_ORDER = ["unsupported", "partial", "unassessed", "supported"];

/* Repeal currency (answer_citations.currency_for). Two values only. `unknown`
   is NOT a clean bill of health: repeal data covers 4 of the 43 statutes in the
   corpus and is a self-declared lower bound, amendment is not modelled at all,
   and no statute carries an as-of date. A repealed provision OVERRIDES its
   support verdict — a section can genuinely establish the proposition and still
   have been abolished, which is the fact that decides whether it can be filed. */
const REPEALED = "repealed";
const CURRENCY_TEXT = {
    repealed: "Repealed provision \u2014 do not rely on this authority",
    unknown:  "Current status not verified",
};
const repealNote = (src) => {
    const bits = [src.instrument, src.date].filter(Boolean).join(", ");
    const scope = src.jurisdiction && src.jurisdiction !== "federal" ? ` (${src.jurisdiction} only)` : "";
    return bits ? `repealed by ${bits}${scope}` : "";
};

// ============================================================
// AI LEGAL PAGE — Full chatbot UI with case context injection
// ============================================================
function AILegalPage() {
    const { t } = useTheme();
    const { activeCase } = useCase();
    const { user } = useAuth();
    const firstName = user?.full_name?.split(" ")[0] || "Counselor";
    const [apiCases, setApiCases] = useState([]);
    const [msgs, setMsgs] = useState([]);

    useEffect(() => {
        listCases({ page_size: 50 }).then(({ data }) => {
            if (!data?.items) return;
            setApiCases(data.items.map(c => ({
                id: c.case_number || c._id,
                _id: c._id,
                title: c.title || "Untitled Case",
                type: c.case_type || "general",
                client: c.client_name || "Client",
                court: c.province || "Court",
                // Kept separate from `court`: that field carries a "Court" display
                // fallback, which is not a province and must never reach retrieval.
                // The stored value is already the pipeline's Province enum
                // (punjab | sindh | kpk | balochistan | federal), so it passes
                // through untranslated.
                province: c.province || null,
                nextHearing: c.hearing_dates?.find(h => !h.outcome)?.date?.split("T")[0] || "TBD",
            })));
        });
    }, []);

    const activeCaseObj = apiCases.find(c => c.id === activeCase) || null;
    const [query, setQuery] = useState("");
    const [loading, setLoading] = useState(false);
    const [sideOpen, setSideOpen] = useState(true);
    const [lang, setLang] = useState("EN");
    const [history, setHistory] = useState([
        { group: "This Week", items: [] },
    ]);
    const sessionIdRef = useRef(`${Date.now()}-${Math.random().toString(36).slice(2, 10)}`);
    const bottomRef = useRef(null);
    useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

    // Inject cursor-blink keyframe once
    useEffect(() => {
        const id = "ai-blink-kf";
        if (document.getElementById(id)) return;
        const s = document.createElement("style");
        s.id = id;
        s.textContent = `@keyframes aiBlink{0%,100%{opacity:1}50%{opacity:0}}`;
        document.head.appendChild(s);
    }, []);

    // Auto-inject active case context when case changes
    useEffect(() => {
        if (activeCaseObj) {
            const ctx = `I'm working on case ${activeCaseObj.id}: "${activeCaseObj.title}" — ${activeCaseObj.type} case for client ${activeCaseObj.client} at ${activeCaseObj.court}. Next hearing: ${activeCaseObj.nextHearing}. What should I prepare?`;
            setQuery(ctx);
            setMsgs([]); // reset conversation when case changes
            sessionIdRef.current = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`; // fresh graph thread
        }
    }, [activeCase]); // runs whenever active case changes, not just mount

    const h = new Date().getHours();
    const greetEmoji = h < 12 ? "🌅" : h < 17 ? "⛅" : "🌙";
    const greetWord = h < 12 ? "Good Morning" : h < 17 ? "Good Afternoon" : "Good Evening";
    const greetSub = activeCaseObj ? `Working on: ${activeCaseObj.id} — ${activeCaseObj.title}` : "The details are in the dark. Let's find them.";

    const send = async () => {
        if (!query.trim() || loading) return;
        const q = query.trim();
        setQuery("");
        const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        setMsgs(p => [...p, { role: "user", content: q, time: now }]);
        setHistory(prev => { const u = [...prev]; if (u[0] && !u[0].items.includes(q)) u[0] = { ...u[0], items: [q, ...u[0].items] }; return u; });
        setLoading(true);

        const aiTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        const msgHistory = msgs.filter(m => m.role !== "system").map(m => ({ role: m.role, content: m.content }));

        // Insert placeholder immediately (filled when the pipeline answers)
        setMsgs(p => [...p, { role: "assistant", content: "", time: aiTime, streaming: true }]);

        const fill = (patch) => setMsgs(p => {
            const next = [...p];
            const last = next[next.length - 1];
            if (last?.streaming) next[next.length - 1] = { ...last, streaming: false, ...patch };
            return next;
        });

        try {
            // Province comes from the active case. Without it the pipeline resolves
            // province to "unknown", and the retriever's filter then matches only
            // federal-tagged chunks — hiding every provincial statute in the corpus
            // (~1,600 Punjab sections) unless the lawyer happens to name a city in
            // the query text. The case record already knows the jurisdiction.
            const { data, error } = await aiResearch(q, sessionIdRef.current, {
                language: lang === "UR" ? "ur" : "en",
                province: activeCaseObj?.province || null,
                history: msgHistory,
            });
            if (error || !data) throw new Error(error?.detail || "request failed");

            if (data.type === "clarification") {
                fill({ content: data.question, clarification: true });
            } else {
                const citations = (data.citations || [])
                    .map(c => ({
                        label: [c.statute, c.section ? `§${c.section}` : ""].filter(Boolean).join(" "),
                        url: c.url || (c.type === "judgment" ? c.source : ""),
                        judgment: c.type === "judgment",
                        // matched | unresolved | retrieved — see answer_citations.py
                        status: c.status || "retrieved",
                        // repealed | unknown — never in_force
                        currency: c.currency || "unknown",
                        instrument: c.instrument || "",
                        date: c.date || "",
                        jurisdiction: c.jurisdiction || "",
                        chunkId: c.chunk_id || "",
                        province: c.province || "",
                    }))
                    .filter(c => c.label);
                fill({
                    content: data.answer || "No response received.",
                    citations,
                    claims: data.claims || [],
                    confidence: data.confidence,
                    confidenceBand: data.confidence_band,
                    modelConfidence: data.model_confidence,
                    arbitrationSource: data.arbitration_source,
                });
            }
        } catch {
            fill({ content: "AI service unavailable. Please try again." });
        }
        setLoading(false);
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
                                <h2 className="serif" style={{ fontSize: 26, fontWeight: 700, color: t.text, margin: 0 }}>{greetWord}, {firstName}!</h2>
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
                                    `What sections apply to ${activeCaseObj.type} cases in Pakistan?`,
                                    `Key arguments for ${activeCaseObj.title}`,
                                    `Documents needed for next hearing at ${activeCaseObj.court}`,
                                    `Recent precedents for ${activeCaseObj.type} law`
                                ] : [
                                    "Relevant sections for property dispute",
                                    "PPC sections for cheque bounce",
                                    "Bail conditions under CrPC 1898",
                                    "Contempt of court procedure in Pakistan"
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
                                            // A clarification is a QUESTION to the lawyer, not advice.
                                            // Rendered identically to an answer it reads as one, which is
                                            // the worst possible confusion on a legal surface.
                                            border: m.role === "assistant" ? `1px solid ${m.clarification ? t.primary : t.border}` : "none",
                                            borderRadius: m.role === "user" ? "18px 18px 6px 18px" : "18px 18px 18px 6px",
                                            padding: "12px 16px", fontSize: 13.5, lineHeight: 1.8,
                                            color: m.role === "user" ? (t.mode === "dark" ? "#111B1F" : "#fff") : t.text,
                                            whiteSpace: "pre-wrap", minHeight: m.streaming && !m.content ? 20 : undefined,
                                        }}>
                                            {m.clarification && (
                                                <div style={{ fontSize: 11, color: t.primary, fontWeight: 700, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.5px" }}>
                                                    Clarification needed
                                                </div>
                                            )}
                                            {m.content || (m.streaming ? "" : "No response received.")}
                                            {m.streaming && <span style={{ display: "inline-block", width: 2, height: "1em", background: t.primary, marginLeft: 2, verticalAlign: "text-bottom", animation: "aiBlink 1s step-end infinite" }} />}
                                            {/* Claim-level support. Above the citation chips on
                                                purpose: which proposition rests on which section,
                                                and whether that section carries it, is the research
                                                question — the chip list only says what was cited. */}
                                            {m.role === "assistant" && !m.streaming && m.claims?.length > 0 && (() => {
                                                const counts = m.claims.reduce((acc, c) => {
                                                    acc[c.support] = (acc[c.support] || 0) + 1; return acc;
                                                }, {});
                                                const repealed = m.claims.filter(c => c.currency === REPEALED);
                                                const sorted = [...m.claims].sort(
                                                    (a, b) => CLAIM_ORDER.indexOf(a.support) - CLAIM_ORDER.indexOf(b.support));
                                                return (
                                                    <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid ${t.border}` }}>
                                                        {repealed.length > 0 && (
                                                            <div style={{
                                                                fontSize: 11.5, color: "#ef4444", fontWeight: 700,
                                                                marginBottom: 7, padding: "7px 10px", borderRadius: 7,
                                                                background: "#ef444414", border: "1px solid #ef444455",
                                                            }}>
                                                                {"\u26D4"} {CURRENCY_TEXT.repealed}
                                                                <div style={{ fontWeight: 400, fontSize: 10.5, marginTop: 3, color: t.text }}>
                                                                    {repealed.length} claim{repealed.length === 1 ? "" : "s"} rest
                                                                    {repealed.length === 1 ? "s" : ""} on a repealed section. Do not file on this
                                                                    without substituting the provision now in force.
                                                                </div>
                                                            </div>
                                                        )}
                                                        <div style={{
                                                            fontSize: 10, color: t.textMuted, marginBottom: 6,
                                                            textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 700,
                                                            display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center",
                                                        }}>
                                                            <span>Claim support ({m.claims.length})</span>
                                                            {CLAIM_ORDER.filter(k => counts[k]).map(k => (
                                                                <span key={k} style={{ color: CLAIM_UI[k].color, fontWeight: 700 }}>
                                                                    {counts[k]} {CLAIM_UI[k].label.toLowerCase()}
                                                                </span>
                                                            ))}
                                                        </div>
                                                        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                                                            {sorted.map((c, ci) => {
                                                                const dead = c.currency === REPEALED;
                                                                const ui = dead
                                                                    ? { icon: "\u26D4", color: "#ef4444", label: "Repealed",
                                                                        note: "do not rely on this authority" }
                                                                    : (CLAIM_UI[c.support] || CLAIM_UI.unassessed);
                                                                const notes = (c.sources || []).map(repealNote).filter(Boolean);
                                                                return (
                                                                    <div key={ci} style={{
                                                                        borderLeft: `2px solid ${ui.color}`, paddingLeft: 9,
                                                                    }}>
                                                                        <div style={{ fontSize: 12, color: t.text, lineHeight: 1.55 }}>
                                                                            “{c.text}”
                                                                        </div>
                                                                        <div style={{ fontSize: 10.5, marginTop: 3, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                                                                            <span style={{ color: ui.color, fontWeight: 700 }}>
                                                                                {ui.icon} {ui.label}
                                                                            </span>
                                                                            <span style={{ color: t.textFaint }}>— {ui.note}</span>
                                                                            {dead && notes.length > 0 && (
                                                                                <span style={{ color: "#ef4444" }}>{notes.join("; ")}</span>
                                                                            )}
                                                                            {c.sources?.length > 0 && (
                                                                                <span className="mono" style={{ color: t.primary }}>
                                                                                    {c.sources.map(sc => `[${sc.id}] ${[sc.statute, sc.section ? `§${sc.section}` : ""].filter(Boolean).join(" ")}`).join("  ")}
                                                                                </span>
                                                                            )}
                                                                            {c.unresolved?.length > 0 && (
                                                                                <span style={{ color: "#f59e0b" }}>
                                                                                    cites {c.unresolved.map(u => [u.statute, u.section ? `§${u.section}` : ""].filter(Boolean).join(" ")).join("; ")} — not in retrieved evidence
                                                                                </span>
                                                                            )}
                                                                        </div>
                                                                    </div>
                                                                );
                                                            })}
                                                        </div>
                                                        <div style={{ fontSize: 10, color: t.textFaint, marginTop: 7 }}>
                                                            Support is judged against the retrieved sources only. Where a
                                                            section is not marked repealed its current status is NOT verified —
                                                            repeal data covers 4 of 43 statutes and is a lower bound, and
                                                            amendment is not checked at all.
                                                        </div>
                                                    </div>
                                                );
                                            })()}
                                            {m.role === "assistant" && !m.streaming && m.citations?.length > 0 && (
                                                <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid ${t.border}` }}>
                                                    {[
                                                        ["matched", "Cited by this answer · found in retrieved sources", t.primary],
                                                        ["unresolved", "Cited by this answer · NOT in retrieved sources — verify independently", "#f59e0b"],
                                                        ["retrieved", "Retrieved but not cited in this answer", t.textFaint],
                                                    ].map(([key, caption, tone]) => {
                                                        const group = (m.citations || []).filter(c => (c.status || "retrieved") === key);
                                                        if (!group.length) return null;
                                                        return (
                                                            <div key={key} style={{ marginBottom: 8 }}>
                                                                <div style={{ fontSize: 10, color: tone, marginBottom: 4, fontWeight: key === "unresolved" ? 700 : 500 }}>
                                                                    {caption}
                                                                </div>
                                                                <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                                                                    {group.map((c, ci) => {
                                                                        // Repeal outranks match status on the chip too: being
                                                                        // cited AND retrieved says nothing about whether the
                                                                        // provision still exists.
                                                                        const chipDead = c.currency === REPEALED;
                                                                        const icon = chipDead ? "⛔" : c.judgment ? "⚖️" : key === "matched" ? "✓" : key === "unresolved" ? "?" : "📖";
                                                                        const chipStyle = {
                                                                            fontSize: 11, padding: "3px 9px", borderRadius: 7,
                                                                            background: chipDead ? "#ef444414" : t.cardHi,
                                                                            border: `1px solid ${chipDead ? "#ef444466" : key === "unresolved" ? "#f59e0b55" : t.border}`,
                                                                            color: chipDead ? "#ef4444" : (c.url ? t.primary : (key === "unresolved" ? "#f59e0b" : t.textMuted)),
                                                                            textDecoration: "none", fontWeight: (chipDead || c.url) ? 700 : 400,
                                                                        };
                                                                        const title = chipDead
                                                                            ? (repealNote(c) || "repealed")
                                                                            : [c.province, c.chunkId].filter(Boolean).join(" · ");
                                                                        return c.url
                                                                            ? <a key={ci} href={c.url} target="_blank" rel="noopener noreferrer" style={chipStyle} title={title}>{icon} {c.label}{chipDead ? " — repealed" : ""} ↗</a>
                                                                            : <span key={ci} style={chipStyle} title={title}>{icon} {c.label}{chipDead ? " — repealed" : ""}</span>;
                                                                    })}
                                                                </div>
                                                            </div>
                                                        );
                                                    })}
                                                </div>
                                            )}
                                        </div>
                                        {m.time && (
                                            <div style={{ fontSize: 10, color: t.textFaint, marginTop: 4, textAlign: m.role === "user" ? "right" : "left", display: "flex", alignItems: "center", gap: 8, justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
                                                {m.time}
                                                {m.role === "assistant" && !m.streaming && !m.clarification && m.content && (
                                                    m.confidenceBand ? (
                                                        <span style={{ color: CONF_COLOR[m.confidenceBand] || t.textFaint }}
                                                              title={m.modelConfidence != null ? `model self-report: ${Math.round(m.modelConfidence * 100)}% (diagnostic, not calibrated)` : undefined}>
                                                            ⬤ {CONF_LABEL[m.confidenceBand]} confidence · {Math.round(m.confidence * 100)}%
                                                            {m.arbitrationSource ? ` (evidence: ${m.arbitrationSource})` : ""}
                                                        </span>
                                                    ) : (
                                                        <span style={{ color: t.textFaint }}>Confidence not calibrated</span>
                                                    )
                                                )}
                                                {m.role === "assistant" && !m.streaming && !m.clarification && m.content && (
                                                    m.rated ? <span>feedback recorded ✓</span> : (
                                                        <span style={{ display: "inline-flex", gap: 3 }}>
                                                            {["up", "down"].map(r => (
                                                                <button key={r}
                                                                    onClick={() => {
                                                                        setMsgs(prev => prev.map((x, xi) => xi === i ? { ...x, rated: r } : x));
                                                                        rateAnswer({
                                                                            session_id: sessionIdRef.current,
                                                                            rating: r,
                                                                            answer_preview: (m.content || "").slice(0, 300),
                                                                            question_preview: (msgs[i - 1]?.content || "").slice(0, 300),
                                                                            source: "research",
                                                                        }).catch(() => {});
                                                                    }}
                                                                    style={{ border: `1px solid ${t.border}`, background: "transparent", borderRadius: 6, cursor: "pointer", fontSize: 10, padding: "1px 6px" }}
                                                                >{r === "up" ? "👍" : "👎"}</button>
                                                            ))}
                                                        </span>
                                                    )
                                                )}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            ))}
                            {loading && !msgs.some(m => m.streaming) && (
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
                            placeholder="Ask Attorney AI..."
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
