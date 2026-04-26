'use client';
// Lawyer Document Automation Page — paste your code here
import { useState, useRef, useEffect } from "react";
import { useTheme } from "./theme.js";
import { useCase } from "./theme.js";
import { Icon, I } from "./icons.jsx";
import { casesData } from "./data.js";

// ============================================================
// DATA
// ============================================================

const CATEGORIES = ["All", "Agreement/Contract", "Application/Petition", "Litigation", "Criminal", "Property", "Labour", "Administrative"];

const TEMPLATES = [
    { id: 1, name: "Dissolution of Marriage Application", cat: "Application/Petition", desc: "Seek divorce with compliant petition under Muslim Family Laws Ordinance. Outlines grounds, reliefs, and clarity for family court filings.", icon: "⚖️", popular: true },
    { id: 2, name: "Plaint — Civil Suit", cat: "Litigation", desc: "Standard plaint under Order VII Rule 1 CPC for civil suits. Covers facts, cause of action, and prayer clause.", icon: "🏛️", popular: true },
    { id: 3, name: "Service Agreement", cat: "Agreement/Contract", desc: "Professional service contract covering scope, payment, timelines, and breach clauses. Suitable for B2B engagements.", icon: "🤝", popular: false },
    { id: 4, name: "Legal Notice", cat: "Application/Petition", desc: "Formal legal notice to demand compliance, payment, or action before initiating legal proceedings.", icon: "📬", popular: true },
    { id: 5, name: "Affidavit (General)", cat: "Application/Petition", desc: "Sworn affidavit format for court submission. General-purpose with fields for deponent details and declarations.", icon: "🔏", popular: false },
    { id: 6, name: "Bail Application", cat: "Criminal", desc: "Regular bail application under CrPC with grounds, antecedents, and sureties. Includes statutory reference.", icon: "🔑", popular: true },
    { id: 7, name: "Written Statement", cat: "Litigation", desc: "Defence written statement template for civil suits. Includes preliminary objections, para-wise reply, and counter-claim.", icon: "📝", popular: false },
    { id: 8, name: "Power of Attorney (General)", cat: "Agreement/Contract", desc: "General POA authorising an agent to act on behalf of the principal for specified legal and financial matters.", icon: "📋", popular: false },
    { id: 9, name: "Vakalatnama", cat: "Litigation", desc: "Court authority-to-plead form granting an advocate right to appear and act in proceedings.", icon: "📄", popular: false },
    { id: 10, name: "RTI Application", cat: "Administrative", desc: "Right to Information application under RTI Act to obtain public records from government authorities.", icon: "🗂️", popular: false },
    { id: 11, name: "Employment Contract", cat: "Agreement/Contract", desc: "Standard employment agreement covering designation, salary, confidentiality, termination, and dispute resolution.", icon: "💼", popular: false },
    { id: 12, name: "Property Sale Deed", cat: "Property", desc: "Registered sale deed for immovable property transfer. Includes survey details, consideration, and possession clause.", icon: "🏠", popular: true },
    { id: 13, name: "Labour Dispute Notice", cat: "Labour", desc: "Formal notice to employer for wrongful termination, unpaid wages, or violation of labour laws.", icon: "⚡", popular: false },
    { id: 14, name: "NDA / Confidentiality Agreement", cat: "Agreement/Contract", desc: "Mutual or one-way non-disclosure agreement for trade secrets, business plans, and proprietary information.", icon: "🛡️", popular: false },
];

function buildContent(tmpl, caseObj) {
    const caseRef = caseObj?.id || "CS-2024-089";
    const clientRef = caseObj?.client || "[Client Name]";
    const court = caseObj?.court || "[Court Name]";
    const today = new Date().toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" });

    const map = {
        1: `IN THE FAMILY COURT AT [LOCATION]\n\nSuit No. ______/2026\n\n${clientRef.toUpperCase()}, W/O [Husband's Name],\nResident of [Full Address], CNIC No. [__________],\n\n...Petitioner\n\nVERSUS\n\n[Respondent's Name], S/O [Father's Name],\nResident of [Full Address],\n\n...Respondent\n\n\nPETITION FOR DISSOLUTION OF MARRIAGE (DIVORCE)\nUNDER THE MUSLIM FAMILY LAWS ORDINANCE, 1961\n\nRespectfully Sheweth:\n\n1. That the petitioner and the respondent were duly married on [Date] at [Place] in accordance with Muslim personal law.\n\n2. That the respondent has treated the petitioner with cruelty and has failed to maintain the petitioner without reasonable cause.\n\n3. That the petitioner is entitled to seek dissolution of marriage under Section 2(ix) of the Dissolution of Muslim Marriages Act, 1939.\n\nPRAYER:\nIt is therefore respectfully prayed that this Honourable Court may be pleased to:\n(a) Grant decree of dissolution of marriage;\n(b) Award maintenance to the petitioner;\n(c) Award costs of the proceedings.\n\nDate: ${today}\n\n_________________________\nPetitioner / Advocate`,
        2: `IN THE COURT OF THE CIVIL JUDGE, LAHORE\n\nCase No. ${caseRef} of 2026\n\n${clientRef.toUpperCase()}\n...Plaintiff\n\nVERSUS\n\n[Defendant Name]\n...Defendant\n\n\nPLAINT UNDER ORDER VII RULE 1, C.P.C.\n\nMost Respectfully Sheweth:\n\n1. That the plaintiff is a resident of [Address] and is entitled to file the present suit.\n\n2. That the defendant is indebted to the plaintiff in the sum of PKR [Amount] on account of [cause of action].\n\n3. That the cause of action arose on [Date] when the defendant failed to honour the obligation despite written demand dated [Date].\n\n4. That this Court has territorial and pecuniary jurisdiction to try the present suit.\n\nPRAYER:\nThe plaintiff humbly prays that this Honourable Court may be pleased to:\n(a) Decree the suit for PKR [Amount];\n(b) Award markup at the rate of [Rate]% per annum;\n(c) Award costs of the suit.\n\nVerified: The contents of the above plaint are true to the best of my knowledge.\n\nDate: ${today}\t\t\t_______________________\n\t\t\t\t\tPlaintiff / Advocate`,
        default: `IN THE COURT OF THE HONOURABLE JUDGE\n\nCase Reference: ${caseRef}\n\n${tmpl.name.toUpperCase()}\n\nIN THE MATTER OF: ${clientRef}\n\nBefore: ${court}\n\nDate: ${today}\n\n${"─".repeat(60)}\n\n1. INTRODUCTION\n\nThis ${tmpl.name} is filed on behalf of ${clientRef} in connection with the above-referenced matter.\n\n2. FACTS\n\nThe relevant facts are as follows:\n\n   a) [State first material fact]\n   b) [State second material fact]\n   c) [State third material fact]\n\n3. GROUNDS\n\n   i.  [Ground one — legal basis]\n   ii. [Ground two — factual basis]\n\n4. PRAYER\n\nIn light of the above, it is respectfully prayed that this Honourable Court may be pleased to grant the relief sought herein, along with costs.\n\n${"─".repeat(60)}\n\nDate: ${today}\t\t\t_______________________\n\t\t\t\t\tJohn Doe, Advocate\n\t\t\t\t\tEnrollment: MH/2015/4582`,
    };

    return map[tmpl.id] || map.default;
}

// ============================================================
// TOOLBAR BUTTON
// ============================================================
function ToolBtn({ label, active, onClick, children, style = {} }) {
    const { t } = useTheme();
    const [hov, setHov] = useState(false);
    return (
        <button
            title={label} onClick={onClick}
            onMouseEnter={() => setHov(true)}
            onMouseLeave={() => setHov(false)}
            style={{
                height: 30, minWidth: 30, padding: "0 7px",
                borderRadius: 6,
                border: active
                    ? `1.5px solid ${t.primary}50`
                    : `1.5px solid ${hov ? t.border : "transparent"}`,
                cursor: "pointer",
                display: "flex", alignItems: "center", justifyContent: "center",
                gap: 3, fontSize: 12, fontWeight: 600, fontFamily: "inherit",
                background: active
                    ? t.primaryGlow
                    : hov ? t.cardHi
                        : "transparent",
                color: active ? t.primary : hov ? t.text : t.textMuted,
                transition: "all .1s",
                boxShadow: active ? `0 0 0 1px ${t.primary}20` : "none",
                ...style,
            }}
        >
            {children || label}
        </button>
    );
}

function ToolSep() {
    const { t } = useTheme();
    return <div style={{ width: 1, height: 18, background: t.border, margin: "0 5px", flexShrink: 0 }} />;
}

// ============================================================
// STATUS BADGE
// ============================================================
function StatusBadge({ status, t }) {
    const cfg = {
        Draft: { bg: t.cardHi, color: t.textMuted, border: t.border },
        "Under Review": { bg: `${t.warn}15`, color: t.warn, border: `${t.warn}40` },
        Approved: { bg: `${t.success}15`, color: t.success, border: `${t.success}40` },
        Final: { bg: t.primaryGlow2, color: t.primary, border: `${t.primary}40` },
    };
    const c = cfg[status] || cfg.Draft;
    return (
        <span style={{
            fontSize: 10, padding: "3px 9px", borderRadius: 6,
            background: c.bg, color: c.color,
            fontWeight: 700, border: `1px solid ${c.border}`,
            letterSpacing: "0.05em", textTransform: "uppercase", whiteSpace: "nowrap",
            flexShrink: 0,
        }}>{status}</span>
    );
}

// ============================================================
// STAGE 1 — TEMPLATE GALLERY
// ============================================================
function StageGallery({ onSelect, t }) {
    const [search, setSearch] = useState("");
    const [cat, setCat] = useState("All");
    const [bookmarked, setBookmarked] = useState(new Set([1, 6, 12]));

    const filtered = TEMPLATES.filter(tmpl =>
        (cat === "All" || tmpl.cat === cat) &&
        (tmpl.name.toLowerCase().includes(search.toLowerCase()) || tmpl.desc.toLowerCase().includes(search.toLowerCase()))
    );

    const toggleBookmark = (e, id) => {
        e.stopPropagation();
        setBookmarked(prev => { const s = new Set(prev); s.has(id) ? s.delete(id) : s.add(id); return s; });
    };

    return (
        <div style={{ display: "flex", flexDirection: "column", padding: "24px 28px" }} className="fade-in">
            {/* Header */}
            <div style={{ marginBottom: 24 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                    <div style={{ width: 32, height: 32, borderRadius: 9, background: t.primaryGlow, border: `1.5px solid ${t.primary}30`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15 }}>⚖️</div>
                    <div className="serif" style={{ fontSize: 26, fontWeight: 700, color: t.text, letterSpacing: "0.02em" }}>Drafter</div>
                </div>
                <div style={{ fontSize: 13, color: t.textMuted, marginTop: 2 }}>AI-powered legal document generation for Indian &amp; Pakistani law</div>
            </div>

            {/* Search */}
            <div style={{ position: "relative", marginBottom: 18, border: `1.5px solid ${t.border}`, borderRadius: 12, background: t.card, overflow: "hidden", boxShadow: t.shadowCard, transition: "border-color .15s" }}
                onFocusCapture={e => e.currentTarget.style.borderColor = t.primary}
                onBlurCapture={e => e.currentTarget.style.borderColor = t.border}>
                <div style={{ position: "absolute", left: 15, top: "50%", transform: "translateY(-50%)", color: t.textFaint }}><Icon d={I.search} size={16} /></div>
                <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search templates…"
                    style={{ width: "100%", height: 46, paddingLeft: 44, paddingRight: 16, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 14, fontFamily: "inherit" }} />
            </div>

            {/* Category Pills */}
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 24 }}>
                {CATEGORIES.map(c => (
                    <button key={c} onClick={() => setCat(c)}
                        style={{ padding: "6px 14px", borderRadius: 100, fontSize: 12, fontWeight: 600, border: `1.5px solid ${cat === c ? t.primary : t.border}`, background: cat === c ? t.primary : "transparent", color: cat === c ? (t.mode === "dark" ? t.bg : t.surface) : t.textMuted, cursor: "pointer", transition: "all .15s", whiteSpace: "nowrap" }}>
                        {c}
                    </button>
                ))}
            </div>

            {/* Hero Cards */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 20 }}>
                {[
                    { label: "New Document", sub: "Start with a blank legal document.", icon: I.plus, color: t.primary, onClick: () => onSelect({ id: 0, name: "Blank Document", cat: "General", desc: "", icon: "📄" }) },
                    { label: "Personal Templates", sub: "Create from your saved templates.", icon: I.bookmark, color: t.warn, onClick: () => { } },
                ].map(h => (
                    <button key={h.label} onClick={h.onClick}
                        style={{ padding: "20px 20px", borderRadius: 14, textAlign: "left", border: `1.5px solid ${t.border}`, background: t.card, cursor: "pointer", transition: "all .18s" }}
                        onMouseEnter={e => { e.currentTarget.style.borderColor = h.color; e.currentTarget.style.background = `${h.color}08`; e.currentTarget.style.transform = "translateY(-1px)"; }}
                        onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.background = t.card; e.currentTarget.style.transform = "none"; }}>
                        <div style={{ width: 38, height: 38, borderRadius: 11, border: `1.5px solid ${h.color}40`, background: `${h.color}14`, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 12 }}>
                            <Icon d={h.icon} size={18} style={{ color: h.color }} />
                        </div>
                        <div style={{ fontSize: 14, fontWeight: 700, color: t.text, marginBottom: 3 }}>{h.label}</div>
                        <div style={{ fontSize: 11.5, color: t.textMuted, lineHeight: 1.5 }}>{h.sub}</div>
                    </button>
                ))}
            </div>

            {search === "" && cat === "All" && (
                <div style={{ fontSize: 10, fontWeight: 700, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 10 }}>Popular Templates</div>
            )}

            {/* Template Grid */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                {filtered.map(tmpl => (
                    <button key={tmpl.id} onClick={() => onSelect(tmpl)}
                        style={{ padding: "18px 18px 16px", borderRadius: 14, textAlign: "left", border: `1.5px solid ${t.border}`, background: t.card, cursor: "pointer", transition: "all .18s", position: "relative" }}
                        onMouseEnter={e => { e.currentTarget.style.borderColor = t.borderHi; e.currentTarget.style.background = t.cardHi; e.currentTarget.style.transform = "translateY(-1px)"; }}
                        onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.background = t.card; e.currentTarget.style.transform = "none"; }}>
                        <div onClick={e => toggleBookmark(e, tmpl.id)}
                            style={{ position: "absolute", top: 12, right: 12, width: 26, height: 26, borderRadius: 7, background: bookmarked.has(tmpl.id) ? `${t.warn}18` : "transparent", border: `1px solid ${bookmarked.has(tmpl.id) ? t.warn + "40" : "transparent"}`, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", color: bookmarked.has(tmpl.id) ? t.warn : t.textFaint, transition: "all .12s" }}
                            onMouseEnter={e => { e.currentTarget.style.color = t.warn; e.currentTarget.style.background = `${t.warn}18`; e.currentTarget.style.borderColor = `${t.warn}40`; }}
                            onMouseLeave={e => { e.currentTarget.style.color = bookmarked.has(tmpl.id) ? t.warn : t.textFaint; e.currentTarget.style.background = bookmarked.has(tmpl.id) ? `${t.warn}18` : "transparent"; }}>
                            <Icon d={I.bookmark} size={13} />
                        </div>
                        <div style={{ width: 36, height: 36, borderRadius: 9, background: t.cardHi, border: `1px solid ${t.border}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 17, marginBottom: 10 }}>{tmpl.icon}</div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 5, paddingRight: 26, lineHeight: 1.35 }}>{tmpl.name}</div>
                        <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.6, marginBottom: 12 }}>{tmpl.desc}</div>
                        <div style={{ display: "flex", gap: 5 }}>
                            <span style={{ fontSize: 9.5, padding: "2px 7px", borderRadius: 5, background: t.primaryGlow2, color: t.primary, fontWeight: 700 }}>{tmpl.cat}</span>
                            {tmpl.popular && <span style={{ fontSize: 9.5, padding: "2px 7px", borderRadius: 5, background: `${t.warn}14`, color: t.warn, fontWeight: 700 }}>Popular</span>}
                        </div>
                    </button>
                ))}
                {filtered.length === 0 && (
                    <div style={{ gridColumn: "1/-1", padding: "48px 0", textAlign: "center", color: t.textFaint, fontSize: 13 }}>No templates found for "{search}"</div>
                )}
            </div>
        </div>
    );
}

// ============================================================
// STAGE 2 — EDITOR
// ============================================================
function StageEditor({ tmpl, caseObj, onBack, t }) {
    const rawContent = buildContent(tmpl, caseObj);
    const [aiMessages, setAiMessages] = useState([]);
    const [aiInput, setAiInput] = useState("");
    const [aiLoading, setAiLoading] = useState(false);
    const [status, setStatus] = useState("Draft");
    const [saved, setSaved] = useState(false);
    const [fontSize, setFontSize] = useState("13");
    const [font, setFont] = useState("Default Font");
    const [wordCount, setWordCount] = useState(0);
    const editorRef = useRef(null);
    const aiEndRef = useRef(null);
    const aiInputRef = useRef(null);

    const h = new Date().getHours();
    const greeting = h < 12 ? "Good Morning" : h < 17 ? "Good Afternoon" : "Good Evening";
    const userName = "Muhammad";
    const greetIcon = h < 12 ? "🌅" : h < 17 ? "☀️" : "🌙";

    useEffect(() => { aiEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [aiMessages, aiLoading]);
    useEffect(() => { setWordCount(rawContent.trim().split(/\s+/).filter(Boolean).length); }, []);

    const exec = (cmd, val = null) => { editorRef.current?.focus(); document.execCommand(cmd, false, val); };
    const queryState = (cmd) => document.queryCommandState(cmd);

    const sendToAI = async () => {
        const q = aiInput.trim();
        if (!q || aiLoading) return;
        setAiInput("");
        setAiMessages(prev => [...prev, { role: "user", text: q }]);
        setAiLoading(true);
        try {
            const res = await fetch("https://api.anthropic.com/v1/messages", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    model: "claude-sonnet-4-20250514",
                    max_tokens: 1000,
                    system: `You are an expert legal document assistant for Indian and Pakistani law. Document type: ${tmpl.name}. When asked to modify or redraft, respond with the COMPLETE updated document text only — no explanation, no markdown fences. If asked a question, answer concisely.`,
                    messages: [
                        ...aiMessages.map(m => ({ role: m.role === "user" ? "user" : "assistant", content: m.text })),
                        { role: "user", content: `Current document:\n\n${editorRef.current?.innerText || rawContent}\n\n---\nInstruction: ${q}` },
                    ],
                }),
            });
            const data = await res.json();
            const reply = data.content?.[0]?.text || "Sorry, I couldn't process that.";
            const looksLikeDoc = reply.length > 300 && (reply.includes("\n\n") || reply.includes("PRAYER") || reply.includes("Respectfully") || reply.includes("IN THE COURT") || reply.includes("PETITION") || reply.includes("AGREEMENT"));
            if (looksLikeDoc && editorRef.current) {
                editorRef.current.innerText = reply;
                setWordCount(reply.trim().split(/\s+/).filter(Boolean).length);
            }
            setAiMessages(prev => [...prev, { role: "assistant", text: looksLikeDoc ? "✅ Document updated. Review the changes in the editor." : reply }]);
        } catch {
            setAiMessages(prev => [...prev, { role: "assistant", text: "Connection error. Please try again." }]);
        } finally {
            setAiLoading(false);
        }
    };

    const FONT_OPTIONS = ["Default Font", "Georgia", "Times New Roman", "Courier New", "Arial"];
    const SIZE_OPTIONS = ["10", "11", "12", "13", "14", "16", "18", "20"];
    const selStyle = { height: 26, borderRadius: 7, border: `1.5px solid ${t.border}`, background: t.card, color: t.text, fontSize: 11.5, padding: "0 6px", cursor: "pointer", fontFamily: "inherit", outline: "none" };

    return (
        <div style={{ display: "flex", flexDirection: "column", position: "fixed", top: 0, left: 56, right: 0, bottom: 0, background: t.bg, zIndex: 10, transition: "left .25s ease" }}>

            {/* ── Enhanced Top bar ── */}
            <div style={{
                height: 64, minHeight: 64,
                display: "flex", alignItems: "center", justifyContent: "space-between",
                borderBottom: `2px solid ${t.border}`,
                background: `linear-gradient(90deg, ${t.surface} 0%, ${t.cardHi} 100%)`,
                padding: "0 24px",
                flexShrink: 0,
                gap: 32,
                boxShadow: `0 2px 8px ${t.border}20`,
            }}>

                {/* LEFT — Enhanced navigation and document info */}
                <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>

                    <button onClick={onBack}
                        style={{
                            display: "flex", alignItems: "center", gap: 6,
                            background: `linear-gradient(135deg, ${t.primary}15, ${t.primary}05)`,
                            border: `1.5px solid ${t.primary}30`,
                            color: t.primary, cursor: "pointer",
                            fontSize: 12, fontWeight: 600,
                            padding: "8px 12px 8px 8px", borderRadius: 10,
                            transition: "all .15s", flexShrink: 0, whiteSpace: "nowrap",
                        }}
                        onMouseEnter={e => {
                            e.currentTarget.style.background = `linear-gradient(135deg, ${t.primary}25, ${t.primary}10)`;
                            e.currentTarget.style.borderColor = t.primary;
                            e.currentTarget.style.transform = "translateY(-1px)";
                        }}
                        onMouseLeave={e => {
                            e.currentTarget.style.background = `linear-gradient(135deg, ${t.primary}15, ${t.primary}05)`;
                            e.currentTarget.style.borderColor = `${t.primary}30`;
                            e.currentTarget.style.transform = "translateY(0)";
                        }}>
                        <Icon d={I.chevronLeft} size={14} /> Back to Templates
                    </button>

                    {/* Enhanced separator */}
                    <div style={{
                        width: 1, height: 24,
                        background: `linear-gradient(to bottom, transparent, ${t.border}, transparent)`,
                        flexShrink: 0
                    }} />

                    {/* Enhanced document info with icon */}
                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
                        <div style={{
                            width: 36, height: 36, borderRadius: 10,
                            background: `linear-gradient(135deg, ${t.primary}20, ${t.primary}10)`,
                            border: `1.5px solid ${t.primary}35`,
                            display: "flex", alignItems: "center", justifyContent: "center",
                            fontSize: 16, flexShrink: 0,
                        }}>
                            {tmpl.icon}
                        </div>

                        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                            <div style={{
                                fontSize: 14, fontWeight: 700, color: t.text,
                                whiteSpace: "nowrap", letterSpacing: "-0.01em",
                                lineHeight: 1.2
                            }}>
                                {tmpl.name}
                            </div>
                            <div style={{
                                fontSize: 11, color: t.textMuted, whiteSpace: "nowrap",
                                letterSpacing: "0.02em", display: "flex", alignItems: "center", gap: 6
                            }}>
                                <span style={{
                                    padding: "2px 6px", borderRadius: 4,
                                    background: `${t.primary}15`, color: t.primary,
                                    fontSize: 10, fontWeight: 600
                                }}>
                                    {tmpl.cat}
                                </span>
                                <span style={{ color: t.border }}>•</span>
                                <span>{new Date().toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</span>
                                <span style={{ color: t.border }}>•</span>
                                <span style={{ color: t.success, fontWeight: 600 }}>{wordCount} words</span>
                            </div>
                        </div>
                    </div>

                    {/* Enhanced status badge */}
                    <div style={{ marginLeft: 4 }}>
                        <StatusBadge status={status} t={t} />
                    </div>
                </div>

                {/* RIGHT — Enhanced action buttons */}
                <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>

                    {saved && (
                        <span style={{
                            fontSize: 11, color: t.success,
                            display: "flex", alignItems: "center", gap: 5,
                            padding: "6px 12px", borderRadius: 10,
                            background: `linear-gradient(135deg, ${t.success}20, ${t.success}10)`,
                            border: `1.5px solid ${t.success}40`,
                            whiteSpace: "nowrap", fontWeight: 600,
                            boxShadow: `0 2px 8px ${t.success}25`,
                        }}>
                            <Icon d={I.checkCircle} size={12} /> Document Saved
                        </span>
                    )}

                    {/* Enhanced status workflow buttons */}
                    {status === "Draft" && (
                        <button onClick={() => setStatus("Under Review")}
                            style={{
                                padding: "7px 14px", borderRadius: 10,
                                border: `1.5px solid ${t.warn}40`,
                                background: `linear-gradient(135deg, ${t.warn}20, ${t.warn}10)`,
                                color: t.warn, cursor: "pointer",
                                fontSize: 11.5, fontWeight: 700, fontFamily: "inherit",
                                whiteSpace: "nowrap", display: "flex", alignItems: "center", gap: 5,
                                transition: "all .15s",
                                boxShadow: `0 2px 6px ${t.warn}20`,
                            }}
                            onMouseEnter={e => {
                                e.currentTarget.style.background = `linear-gradient(135deg, ${t.warn}30, ${t.warn}15)`;
                                e.currentTarget.style.transform = "translateY(-1px)";
                            }}
                            onMouseLeave={e => {
                                e.currentTarget.style.background = `linear-gradient(135deg, ${t.warn}20, ${t.warn}10)`;
                                e.currentTarget.style.transform = "translateY(0)";
                            }}>
                            <Icon d={I.send} size={12} /> Send for Review
                        </button>
                    )}
                    {status === "Under Review" && (
                        <button onClick={() => setStatus("Approved")}
                            style={{
                                padding: "7px 14px", borderRadius: 10,
                                border: `1.5px solid ${t.success}40`,
                                background: `linear-gradient(135deg, ${t.success}20, ${t.success}10)`,
                                color: t.success, cursor: "pointer",
                                fontSize: 11.5, fontWeight: 700, fontFamily: "inherit",
                                whiteSpace: "nowrap", display: "flex", alignItems: "center", gap: 5,
                                transition: "all .15s",
                                boxShadow: `0 2px 6px ${t.success}20`,
                            }}
                            onMouseEnter={e => {
                                e.currentTarget.style.background = `linear-gradient(135deg, ${t.success}30, ${t.success}15)`;
                                e.currentTarget.style.transform = "translateY(-1px)";
                            }}
                            onMouseLeave={e => {
                                e.currentTarget.style.background = `linear-gradient(135deg, ${t.success}20, ${t.success}10)`;
                                e.currentTarget.style.transform = "translateY(0)";
                            }}>
                            <Icon d={I.check} size={12} /> Approve Document
                        </button>
                    )}
                    {status === "Approved" && (
                        <button onClick={() => setStatus("Final")}
                            style={{
                                padding: "7px 14px", borderRadius: 10,
                                border: `1.5px solid ${t.primary}40`,
                                background: `linear-gradient(135deg, ${t.primary}25, ${t.primary}15)`,
                                color: t.primary, cursor: "pointer",
                                fontSize: 11.5, fontWeight: 700, fontFamily: "inherit",
                                whiteSpace: "nowrap", display: "flex", alignItems: "center", gap: 5,
                                transition: "all .15s",
                                boxShadow: `0 2px 6px ${t.primary}25`,
                            }}
                            onMouseEnter={e => {
                                e.currentTarget.style.background = `linear-gradient(135deg, ${t.primary}35, ${t.primary}20)`;
                                e.currentTarget.style.transform = "translateY(-1px)";
                            }}
                            onMouseLeave={e => {
                                e.currentTarget.style.background = `linear-gradient(135deg, ${t.primary}25, ${t.primary}15)`;
                                e.currentTarget.style.transform = "translateY(0)";
                            }}>
                            <Icon d={I.star} size={12} /> Mark as Final
                        </button>
                    )}

                    {/* Enhanced divider */}
                    <div style={{
                        width: 1, height: 20,
                        background: `linear-gradient(to bottom, transparent, ${t.border}, transparent)`,
                        flexShrink: 0, margin: "0 4px"
                    }} />

                    {/* Enhanced Save button */}
                    <button
                        onClick={() => { setSaved(true); setTimeout(() => setSaved(false), 2500); }}
                        style={{
                            padding: "7px 14px", borderRadius: 10,
                            border: `1.5px solid ${t.border}`,
                            background: `linear-gradient(135deg, ${t.cardHi}, ${t.card})`,
                            color: t.text, cursor: "pointer",
                            fontSize: 11.5, fontWeight: 600, fontFamily: "inherit",
                            display: "flex", alignItems: "center", gap: 5,
                            whiteSpace: "nowrap", transition: "all .15s",
                            boxShadow: `0 2px 4px ${t.border}30`,
                        }}
                        onMouseEnter={e => {
                            e.currentTarget.style.background = `linear-gradient(135deg, ${t.primary}15, ${t.primary}05)`;
                            e.currentTarget.style.borderColor = t.primary;
                            e.currentTarget.style.color = t.primary;
                            e.currentTarget.style.transform = "translateY(-1px)";
                        }}
                        onMouseLeave={e => {
                            e.currentTarget.style.background = `linear-gradient(135deg, ${t.cardHi}, ${t.card})`;
                            e.currentTarget.style.borderColor = t.border;
                            e.currentTarget.style.color = t.text;
                            e.currentTarget.style.transform = "translateY(0)";
                        }}>
                        <Icon d={I.save} size={13} /> Save Draft
                    </button>

                    <button style={{
                        padding: "5px 13px", borderRadius: 8,
                        border: `1px solid ${t.primary}50`, background: t.primaryGlow2,
                        color: t.primary, cursor: "pointer",
                        fontSize: 11.5, fontWeight: 700, fontFamily: "inherit",
                        display: "flex", alignItems: "center", gap: 4,
                        whiteSpace: "nowrap",
                    }}>
                        <Icon d={I.download} size={12} /> Export .docx
                    </button>
                </div>
            </div>

            {/* ── Rich-text Toolbar ── */}
            <div style={{
                display: "flex", alignItems: "center", gap: 2,
                padding: "0 10px", height: 40, minHeight: 40,
                borderBottom: `1px solid ${t.border}`,
                background: t.surface,
                flexWrap: "nowrap", overflowX: "auto", flexShrink: 0,
            }}>

                {/* History */}
                <div style={{ display: "flex", gap: 1, alignItems: "center" }}>
                    <ToolBtn label="Undo (Ctrl+Z)" onClick={() => exec("undo")}>
                        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M2.5 7.5H10a4 4 0 010 8H6" /><path d="M.5 7.5l3-3M.5 7.5l3 3" /></svg>
                    </ToolBtn>
                    <ToolBtn label="Redo (Ctrl+Y)" onClick={() => exec("redo")}>
                        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M13.5 7.5H6a4 4 0 000 8h4" /><path d="M15.5 7.5l-3-3M15.5 7.5l-3 3" /></svg>
                    </ToolBtn>
                </div>
                <ToolSep />

                {/* Font family + size */}
                <select value={font} onChange={e => { setFont(e.target.value); exec("fontName", e.target.value); }} style={{ ...selStyle, width: 124 }}>
                    {FONT_OPTIONS.map(f => <option key={f} value={f} style={{ background: t.surface }}>{f}</option>)}
                </select>
                <select value={fontSize} onChange={e => { setFontSize(e.target.value); exec("fontSize", e.target.value); }} style={{ ...selStyle, width: 44 }}>
                    {SIZE_OPTIONS.map(s => <option key={s} value={s} style={{ background: t.surface }}>{s}</option>)}
                </select>
                <ToolSep />

                {/* Text formatting */}
                <div style={{ display: "flex", gap: 1, alignItems: "center" }}>
                    <ToolBtn label="Bold (Ctrl+B)" active={queryState("bold")} onClick={() => exec("bold")}
                        style={{ fontFamily: "Georgia, serif", fontWeight: 900, fontSize: 14, letterSpacing: "-0.5px" }}>B</ToolBtn>
                    <ToolBtn label="Italic (Ctrl+I)" active={queryState("italic")} onClick={() => exec("italic")}
                        style={{ fontFamily: "Georgia, serif", fontStyle: "italic", fontWeight: 400, fontSize: 14 }}>I</ToolBtn>
                    <ToolBtn label="Underline (Ctrl+U)" active={queryState("underline")} onClick={() => exec("underline")}
                        style={{ textDecoration: "underline", fontSize: 13, fontWeight: 700 }}>U</ToolBtn>
                    <ToolBtn label="Strikethrough" onClick={() => exec("strikeThrough")}
                        style={{ textDecoration: "line-through", fontSize: 12, fontWeight: 500, color: "inherit", opacity: 0.8 }}>S</ToolBtn>
                    <ToolBtn label="Subscript" onClick={() => exec("subscript")} style={{ fontSize: 11, fontWeight: 600 }}>
                        X<sub style={{ fontSize: "65%", lineHeight: 0, verticalAlign: "sub" }}>2</sub>
                    </ToolBtn>
                    <ToolBtn label="Superscript" onClick={() => exec("superscript")} style={{ fontSize: 11, fontWeight: 600 }}>
                        X<sup style={{ fontSize: "65%", lineHeight: 0, verticalAlign: "super" }}>2</sup>
                    </ToolBtn>
                </div>
                <ToolSep />

                {/* Alignment */}
                <div style={{ display: "flex", gap: 1, alignItems: "center" }}>
                    <ToolBtn label="Align Left" active={queryState("justifyLeft")} onClick={() => exec("justifyLeft")}>
                        <svg width="15" height="13" viewBox="0 0 15 13" fill="currentColor">
                            <rect x="0" y="0" width="15" height="2" rx="1" />
                            <rect x="0" y="3.5" width="10" height="2" rx="1" />
                            <rect x="0" y="7" width="15" height="2" rx="1" />
                            <rect x="0" y="10.5" width="7" height="2" rx="1" />
                        </svg>
                    </ToolBtn>
                    <ToolBtn label="Align Center" active={queryState("justifyCenter")} onClick={() => exec("justifyCenter")}>
                        <svg width="15" height="13" viewBox="0 0 15 13" fill="currentColor">
                            <rect x="0" y="0" width="15" height="2" rx="1" />
                            <rect x="2.5" y="3.5" width="10" height="2" rx="1" />
                            <rect x="0" y="7" width="15" height="2" rx="1" />
                            <rect x="4" y="10.5" width="7" height="2" rx="1" />
                        </svg>
                    </ToolBtn>
                    <ToolBtn label="Align Right" active={queryState("justifyRight")} onClick={() => exec("justifyRight")}>
                        <svg width="15" height="13" viewBox="0 0 15 13" fill="currentColor">
                            <rect x="0" y="0" width="15" height="2" rx="1" />
                            <rect x="5" y="3.5" width="10" height="2" rx="1" />
                            <rect x="0" y="7" width="15" height="2" rx="1" />
                            <rect x="8" y="10.5" width="7" height="2" rx="1" />
                        </svg>
                    </ToolBtn>
                    <ToolBtn label="Justify" active={queryState("justifyFull")} onClick={() => exec("justifyFull")}>
                        <svg width="15" height="13" viewBox="0 0 15 13" fill="currentColor">
                            <rect x="0" y="0" width="15" height="2" rx="1" />
                            <rect x="0" y="3.5" width="15" height="2" rx="1" />
                            <rect x="0" y="7" width="15" height="2" rx="1" />
                            <rect x="0" y="10.5" width="15" height="2" rx="1" />
                        </svg>
                    </ToolBtn>
                </div>
                <ToolSep />

                {/* Lists */}
                <div style={{ display: "flex", gap: 1, alignItems: "center" }}>
                    <ToolBtn label="Bullet List" active={queryState("insertUnorderedList")} onClick={() => exec("insertUnorderedList")}>
                        <svg width="15" height="13" viewBox="0 0 15 13" fill="currentColor">
                            <circle cx="1.5" cy="2" r="1.5" />
                            <circle cx="1.5" cy="6.5" r="1.5" />
                            <circle cx="1.5" cy="11" r="1.5" />
                            <rect x="4.5" y="1" width="10" height="2" rx="1" />
                            <rect x="4.5" y="5.5" width="10" height="2" rx="1" />
                            <rect x="4.5" y="10" width="10" height="2" rx="1" />
                        </svg>
                    </ToolBtn>
                    <ToolBtn label="Numbered List" active={queryState("insertOrderedList")} onClick={() => exec("insertOrderedList")}>
                        <svg width="15" height="13" viewBox="0 0 15 13" fill="currentColor">
                            <text x="0" y="3.5" fontSize="4" fontFamily="monospace" fontWeight="bold">1.</text>
                            <text x="0" y="8" fontSize="4" fontFamily="monospace" fontWeight="bold">2.</text>
                            <text x="0" y="12.5" fontSize="4" fontFamily="monospace" fontWeight="bold">3.</text>
                            <rect x="5.5" y="1" width="9" height="2" rx="1" />
                            <rect x="5.5" y="5.5" width="9" height="2" rx="1" />
                            <rect x="5.5" y="10" width="9" height="2" rx="1" />
                        </svg>
                    </ToolBtn>
                </div>
                <ToolSep />

                {/* Headings */}
                <div style={{ display: "flex", gap: 1, alignItems: "center" }}>
                    <ToolBtn label="Heading 1" onClick={() => exec("formatBlock", "h1")}
                        style={{ fontSize: 13, fontWeight: 900, fontFamily: "Georgia,serif", letterSpacing: "-0.3px" }}>H1</ToolBtn>
                    <ToolBtn label="Heading 2" onClick={() => exec("formatBlock", "h2")}
                        style={{ fontSize: 11.5, fontWeight: 800, fontFamily: "Georgia,serif" }}>H2</ToolBtn>
                    <ToolBtn label="Heading 3" onClick={() => exec("formatBlock", "h3")}
                        style={{ fontSize: 10, fontWeight: 700, fontFamily: "Georgia,serif" }}>H3</ToolBtn>
                </div>
                <ToolSep />

                {/* Extras */}
                <div style={{ display: "flex", gap: 1, alignItems: "center" }}>
                    <ToolBtn label="Block Quote" onClick={() => exec("formatBlock", "blockquote")}>
                        <svg width="14" height="12" viewBox="0 0 14 12" fill="currentColor" opacity="0.9">
                            <path d="M0 0h5v5H3C3 7 4 8 6 8v2C2 10 0 8 0 5V0zm8 0h5v5h-2C11 7 12 8 14 8v2c-4 0-6-2-6-5V0z" />
                        </svg>
                    </ToolBtn>
                    <ToolBtn label="Insert Link" onClick={() => { }}>
                        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                            <path d="M6.5 9.5a4 4 0 005.66 0l2-2a4 4 0 00-5.66-5.66l-1 1" />
                            <path d="M9.5 6.5a4 4 0 00-5.66 0l-2 2a4 4 0 005.66 5.66l1-1" />
                        </svg>
                    </ToolBtn>
                    <ToolBtn label="Horizontal Rule" onClick={() => exec("insertHorizontalRule")}>
                        <svg width="14" height="10" viewBox="0 0 14 10" fill="currentColor">
                            <rect x="0" y="4" width="14" height="2" rx="1" />
                            <rect x="0" y="0" width="3" height="1.5" rx="0.5" opacity="0.4" />
                            <rect x="11" y="0" width="3" height="1.5" rx="0.5" opacity="0.4" />
                            <rect x="0" y="8.5" width="3" height="1.5" rx="0.5" opacity="0.4" />
                            <rect x="11" y="8.5" width="3" height="1.5" rx="0.5" opacity="0.4" />
                        </svg>
                    </ToolBtn>
                </div>

                {/* Word count */}
                <div style={{ marginLeft: "auto", fontSize: 10, color: t.textFaint, whiteSpace: "nowrap", paddingLeft: 12, paddingRight: 4, display: "flex", alignItems: "center", gap: 4 }}>
                    <svg width="10" height="10" viewBox="0 0 12 12" fill={t.textFaint}><rect x="1" y="1" width="10" height="1.5" rx="0.6" /><rect x="1" y="4" width="7" height="1.5" rx="0.6" /><rect x="1" y="7" width="10" height="1.5" rx="0.6" /><rect x="1" y="10" width="5" height="1.5" rx="0.6" /></svg>
                    {wordCount} words
                </div>
            </div>

            {/* ── Main Split ── */}
            <div style={{ display: "flex", flexDirection: "row", flex: 1, minHeight: 0, overflow: "hidden" }}>

                {/* LEFT — Paper canvas */}
                <div style={{
                    flex: 1, minWidth: 0,
                    overflowY: "auto", overflowX: "hidden",
                    background: t.bg, padding: "32px 28px",
                }}>
                    <div
                        ref={editorRef}
                        contentEditable
                        suppressContentEditableWarning
                        spellCheck={false}
                        onInput={e => setWordCount(e.currentTarget.innerText.trim().split(/\s+/).filter(Boolean).length)}
                        style={{
                            minHeight: 600, maxWidth: 780, margin: "0 auto",
                            background: t.card, borderRadius: 4,
                            boxShadow: t.shadowCard,
                            padding: "68px 80px",
                            fontFamily: font === "Default Font" ? "Georgia, 'Times New Roman', serif" : font,
                            fontSize: 13.5, lineHeight: 1.95,
                            color: t.text, outline: "none", whiteSpace: "pre-wrap", letterSpacing: "0.01em",
                        }}
                        dangerouslySetInnerHTML={{ __html: rawContent.replace(/\n/g, "<br>") }}
                    />
                    <div style={{ textAlign: "center", marginTop: 10, fontSize: 10, color: t.textFaint, letterSpacing: "0.05em" }}>— Page 1 —</div>
                </div>

                {/* RIGHT — AI Panel */}
                <div style={{ display: "flex", flexDirection: "column", width: 370, flexShrink: 0, borderLeft: `1px solid ${t.border}`, background: t.surface, overflow: "hidden" }}>

                    {/* Messages */}
                    <div style={{ flex: 1, overflowY: "auto", padding: "12px 14px 8px", display: "flex", flexDirection: "column", gap: 10, minHeight: 0 }}>

                        {aiMessages.length === 0 && (
                            <div className="fade-in">
                                <div style={{ background: t.mode === "dark" ? `linear-gradient(140deg, ${t.primaryGlow} 0%, ${t.primaryGlow2} 100%)` : `linear-gradient(140deg, ${t.primaryGlow2} 0%, ${t.cardHi} 100%)`, border: `1.5px solid ${t.primary}20`, borderRadius: 14, padding: "14px 14px 12px", marginBottom: 12 }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                                        <span style={{ fontSize: 20 }}>{greetIcon}</span>
                                        <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>{greeting}, {userName}!</div>
                                    </div>
                                    <div style={{ fontSize: 11.5, color: t.textMuted, lineHeight: 1.6 }}>
                                        <strong style={{ color: t.primary }}>{tmpl.name}</strong> is loaded. What would you like to change?
                                    </div>
                                </div>

                                <div style={{ fontSize: 10, fontWeight: 700, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 7 }}>Quick Actions</div>
                                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                                    {[
                                        { icon: "⚡", text: "Add a stronger prayer clause" },
                                        { icon: "🎩", text: "Make the tone more formal" },
                                        { icon: "📍", text: "Add a jurisdiction paragraph" },
                                        { icon: "📋", text: "Summarise key arguments" },
                                    ].map(s => (
                                        <button key={s.text} onClick={() => { setAiInput(s.text); aiInputRef.current?.focus(); }}
                                            style={{ padding: "8px 11px", borderRadius: 10, border: `1.5px solid ${t.border}`, background: t.card, color: t.textMuted, cursor: "pointer", fontSize: 11.5, textAlign: "left", transition: "all .15s", fontFamily: "inherit", display: "flex", alignItems: "center", gap: 7 }}
                                            onMouseEnter={e => { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.color = t.text; e.currentTarget.style.background = t.primaryGlow2; }}
                                            onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textMuted; e.currentTarget.style.background = t.card; }}>
                                            <span style={{ fontSize: 14 }}>{s.icon}</span>{s.text}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}

                        {aiMessages.map((msg, i) => (
                            <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: msg.role === "user" ? "flex-end" : "flex-start", gap: 3 }}>
                                {msg.role === "assistant" && (
                                    <div style={{ display: "flex", alignItems: "center", gap: 5, marginLeft: 2 }}>
                                        <div style={{ width: 16, height: 16, borderRadius: 5, background: t.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center" }}>
                                            <Icon d={I.sparkles} size={9} style={{ color: t.primary }} />
                                        </div>
                                        <span style={{ fontSize: 10, color: t.textFaint, fontWeight: 600 }}>Claude</span>
                                    </div>
                                )}
                                <div style={{
                                    maxWidth: "90%", padding: "9px 12px",
                                    borderRadius: msg.role === "user" ? "13px 13px 3px 13px" : "3px 13px 13px 13px",
                                    background: msg.role === "user" ? t.primary : t.surface,
                                    border: msg.role === "user" ? "none" : `1.5px solid ${t.border}`,
                                    color: msg.role === "user" ? (t.mode === "dark" ? t.bg : t.surface) : t.text,
                                    fontSize: 12.5, lineHeight: 1.65,
                                }}>
                                    {msg.text}
                                </div>
                            </div>
                        ))}

                        {aiLoading && (
                            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 3 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 5, marginLeft: 2 }}>
                                    <div style={{ width: 16, height: 16, borderRadius: 5, background: t.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center" }}><Icon d={I.sparkles} size={9} style={{ color: t.primary }} /></div>
                                    <span style={{ fontSize: 10, color: t.textFaint, fontWeight: 600 }}>Claude</span>
                                </div>
                                <div style={{ background: t.surface, border: `1.5px solid ${t.border}`, borderRadius: "3px 13px 13px 13px", padding: "11px 16px", display: "flex", gap: 5, alignItems: "center" }}>
                                    {[0, 1, 2].map(d => <div key={d} style={{ width: 6, height: 6, borderRadius: "50%", background: t.primary, animation: `pulse 1.2s ease ${d * 0.2}s infinite`, opacity: 0.8 }} />)}
                                </div>
                            </div>
                        )}
                        <div ref={aiEndRef} />
                    </div>

                    {/* Input */}
                    <div style={{ padding: "10px 12px 13px", borderTop: `1px solid ${t.border}`, flexShrink: 0, background: t.surface }}>
                        <div style={{ border: `1.5px solid ${t.border}`, borderRadius: 13, background: t.card, overflow: "hidden", transition: "border-color .15s, box-shadow .15s" }}
                            onFocusCapture={e => { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.boxShadow = `0 0 0 3px ${t.primary}12`; }}
                            onBlurCapture={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.boxShadow = "none"; }}>
                            <textarea
                                ref={aiInputRef}
                                value={aiInput} onChange={e => setAiInput(e.target.value)}
                                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendToAI(); } }}
                                placeholder="Describe changes or ask a question…"
                                rows={3}
                                style={{ width: "100%", background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 12.5, padding: "11px 13px 5px", resize: "none", fontFamily: "inherit", lineHeight: 1.6, boxSizing: "border-box" }}
                            />
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "3px 9px 9px" }}>
                                <span style={{ fontSize: 10, color: t.textFaint }}>⏎ Send · Shift+⏎ New line</span>
                                <button onClick={sendToAI} disabled={!aiInput.trim() || aiLoading}
                                    style={{ height: 29, paddingLeft: 13, paddingRight: 13, borderRadius: 8, border: "none", background: aiInput.trim() && !aiLoading ? t.primary : t.border, color: aiInput.trim() && !aiLoading ? (t.mode === "dark" ? t.bg : t.surface) : t.textFaint, cursor: aiInput.trim() && !aiLoading ? "pointer" : "default", display: "flex", alignItems: "center", gap: 5, fontSize: 12, fontWeight: 700, fontFamily: "inherit", transition: "all .15s" }}>
                                    <Icon d={I.send} size={11} style={{ transform: "rotate(45deg)" }} />
                                    Generate
                                </button>
                            </div>
                        </div>
                        <div style={{ fontSize: 10, color: t.textFaint, textAlign: "center", marginTop: 8, display: "flex", alignItems: "center", justifyContent: "center", gap: 4 }}>
                            <svg width="10" height="10" viewBox="0 0 12 12" fill={t.textFaint}><path d="M6 1a5 5 0 100 10A5 5 0 006 1zm0 1.5a.75.75 0 110 1.5.75.75 0 010-1.5zm0 2.5a.75.75 0 01.75.75v3a.75.75 0 01-1.5 0v-3A.75.75 0 016 5z" /></svg>
                            AI-generated draft — verify before filing
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

// ============================================================
// ROOT
// ============================================================
function DocAutomationPage() {
    const { t } = useTheme();
    const { activeCaseObj } = useCase();
    const [stage, setStage] = useState("gallery");
    const [selectedTemplate, setSelectedTemplate] = useState(null);
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

    // Listen for sidebar collapse changes
    useEffect(() => {
        const checkSidebarState = () => {
            const sidebar = document.querySelector('[data-sidebar]');
            if (sidebar) {
                const isCollapsed = sidebar.style.width === '56px' || sidebar.style.minWidth === '56px';
                setSidebarCollapsed(isCollapsed);
            }
        };

        // Initial check
        checkSidebarState();

        // Listen for changes
        const observer = new MutationObserver(checkSidebarState);
        const sidebar = document.querySelector('[data-sidebar]');
        if (sidebar) {
            observer.observe(sidebar, { attributes: true, attributeFilter: ['style'] });
        }

        return () => observer.disconnect();
    }, []);

    return (
        <div style={{ display: "flex", flexDirection: "column", position: "fixed", top: 0, left: sidebarCollapsed ? 56 : 240, right: 0, bottom: 0, background: t.bg, zIndex: 10, transition: "left .25s ease" }}>
            {stage === "gallery" && (
                <StageGallery onSelect={tmpl => { setSelectedTemplate(tmpl); setStage("editor"); }} t={t} />
            )}
            {stage === "editor" && selectedTemplate && (
                <StageEditor tmpl={selectedTemplate} caseObj={activeCaseObj} onBack={() => setStage("gallery")} t={t} />
            )}
        </div>
    );
}

export { DocAutomationPage };
