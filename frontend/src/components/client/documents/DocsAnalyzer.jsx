'use client';
/* Document analyzer — "read it with me", then the analysis dashboard.
 *
 * NOT CONNECTED YET: there is no analysis endpoint. So the user's own file is
 * NEVER analysed here — choosing one says the analyzer is not connected. Only
 * the named samples run, and every result on screen is labelled as the
 * sample's. Showing invented risks against a real person's lease would be
 * advice nobody gave. */
import React, { useEffect, useRef, useState } from "react";
import { useT } from "../theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import { useIsMobile } from "@/lib/i18n.jsx";
import {
    Btn, Chip, Pill, Label, Card, Paper, PreviewBadge, ScreenHeader, Icon,
    SERIF, SEVERITY, onPrimary, splitLayout,
} from "./ui.jsx";

const RISKS = [
    { id: 6, at: 2, sev: "high", title: "Clause 6 · Eviction on 7 days’ notice", why: "The landlord can end the lease for any reason within a week — you could lose the shop and your fit-out.", fix: "Require a stated ground and at least 60 days’ notice; give the tenant the same right.", cite: "Punjab Rented Premises Act, 2009 · verified" },
    { id: 9, at: 3, sev: "high", title: "Clause 9 · Deposit is non-refundable", why: "Three months’ rent (PKR 255,000) is lost even if you hand the shop back in good order.", fix: "Refund within 30 days of handover, less documented damage.", cite: "Contract Act, 1872 · verified" },
    { id: 4, at: 4, sev: "medium", title: "Clause 4 · Rent increase at any time", why: "Up to 20% whenever the landlord chooses, with no limit on how often.", fix: "One increase, on renewal only, capped at 10%.", cite: "Punjab Rented Premises Act, 2009 · verified" },
    { id: 5, at: 5, sev: "medium", title: "Clause 5 · Structural repairs on you", why: "Roof, walls and foundations are normally the owner’s job.", fix: "Tenant does day-to-day repairs; landlord does structural ones.", cite: "Punjab Rented Premises Act, 2009 · verified" },
];
const CLAUSES = [
    [1, "1. The Landlord lets the shop at [shop address], Lahore, to the Tenant for eleven (11) months from 1 October 2026."],
    [2, "2. Rent is PKR 85,000 per month, payable by the 5th of each month."],
    [4, "4. The Landlord may increase the rent by up to twenty percent (20%) at any time at the Landlord’s discretion."],
    [5, "5. The Tenant shall bear the cost of all repairs to the premises, including structural repairs."],
    [6, "6. The Landlord may terminate this tenancy by giving seven (7) days’ notice, for any reason."],
    [7, "7. The Tenant shall not sub-let the premises without the Landlord’s written consent."],
    [9, "9. The security deposit of three months’ rent is non-refundable."],
    [11, "11. Signed at Lahore in the presence of two witnesses."],
];
const MISSING = [
    ["Tenant's right to end the lease", "Only the landlord can terminate. Add a notice period for you too."],
    ["Registration with the Rent Registrar", "The 2009 Act expects the agreement to be filed with the Rent Registrar."],
];
const TERMS = [
    ["Monthly rent", "PKR 85,000"], ["Due", "5th of each month"], ["Term", "11 months"],
    ["Starts", "1 Oct 2026"], ["Deposit", "PKR 255,000"], ["Landlord notice", "7 days"],
];
const SUMMARY = "An 11-month shop lease in Lahore at PKR 85,000 a month. It favours the landlord: eviction on 7 days' notice, a non-refundable deposit, open-ended rent increases and structural repairs on you.";
const SAMPLES = [
    ["Shop rent agreement", "Lahore · 4 pages · landlord-friendly"],
    ["Job offer letter", "Sales role · probation & notice"],
    ["Freelancer NDA", "Karachi · one-way · 6 months"],
];
const READING = [0, 6, 6, 9, 4, 5, 0];
const STATUS = ["Starting…", "Reading the text", "Checking clause 6", "Checking clause 9", "Checking clause 4", "Checking clause 5", "Comparing with the checklist"];

function RiskCard({ t, r, open, onPick, fixLabel = "Fix" }) {
    const c = SEVERITY[r.sev];
    return (
        <button type="button" onClick={onPick} aria-expanded={open}
            style={{ display: "block", width: "100%", textAlign: "left", padding: "12px 14px", borderRadius: 12, background: t.card, border: `1px solid ${open ? t.primary : t.border}`, cursor: "pointer", color: t.text, fontFamily: ANALYZER_FONT }}>
            <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 10.5, fontWeight: 700, padding: "2px 7px", borderRadius: 5, background: c.bg, color: c.fg }}>{r.sev.toUpperCase()}</span>
                <span style={{ fontSize: 14, fontWeight: 600 }}>{r.title}</span>
            </span>
            {open && (
                <>
                    <span style={{ display: "block", marginTop: 7, fontSize: 13, lineHeight: 1.55 }}>{r.why}</span>
                    <span style={{ display: "block", marginTop: 7, padding: "8px 10px", borderRadius: 8, background: t.primaryGlow2, fontSize: 13 }}><b>{fixLabel}:</b> {r.fix}</span>
                    <span style={{ display: "block", marginTop: 5, fontSize: 12, color: t.success }}>{r.cite}</span>
                </>
            )}
        </button>
    );
}

function Tabs({ t, tabs, value, onChange }) {
    return (
        <div role="tablist" style={{ display: "flex", gap: 2, flexWrap: "wrap", borderBottom: `1px solid ${t.border}` }}>
            {tabs.map(([id, name]) => (
                <button key={id} type="button" role="tab" aria-selected={value === id} onClick={() => onChange(id)}
                    style={{ minHeight: 42, padding: "0 10px", background: "transparent", border: "none", borderBottom: `2px solid ${value === id ? t.primary : "transparent"}`, color: value === id ? t.primary : t.textMuted, fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: ANALYZER_FONT }}>
                    {name}
                </button>
            ))}
        </div>
    );
}

/* ── The finished analysis: a dashboard with a tab per kind of finding ──────
 *
 * Every figure here belongs to THE SAMPLE (see the file header). Precedents
 * are deliberately empty: inventing case names and citations for a sample
 * would put fake law on screen, and fake citations are exactly the failure
 * this product exists to prevent. */
const KEY_CLAUSES = [
    { id: 6, title: "Termination by the landlord", quote: "The Landlord may terminate this tenancy by giving seven (7) days’ notice, for any reason.",
      issues: ["The landlord can end the lease for any reason", "Only 7 days’ notice", "The tenant has no matching right"] },
    { id: 9, title: "Security deposit", quote: "The security deposit of three months’ rent is non-refundable.",
      issues: ["Non-refundable even if the shop is returned in good order", "PKR 255,000 at stake"] },
    { id: 4, title: "Rent increase", quote: "The Landlord may increase the rent by up to twenty percent (20%) at any time at the Landlord’s discretion.",
      issues: ["Up to 20% at any time", "No limit on how often"] },
];
const OBLIGATIONS = [
    { party: "Tenant", text: "Pay rent of PKR 85,000.", deadline: "By the 5th of each month", status: "Recurring" },
    { party: "Tenant", text: "Bear the cost of all repairs, including structural repairs.", deadline: "Throughout the term", status: "Ongoing" },
    { party: "Tenant", text: "Do not sub-let without the landlord’s written consent.", deadline: "Throughout the term", status: "Ongoing" },
    { party: "Landlord", text: "Give seven days’ notice before terminating.", deadline: "Before termination", status: "Pending" },
];
const COMPLIANCE = [
    { title: "Registration with the Rent Registrar", status: "missing", detail: "The agreement is expected to be filed with the Rent Registrar.", law: "Punjab Rented Premises Act, 2009" },
    { title: "Tenant’s right to end the lease", status: "missing", detail: "Only the landlord can terminate. Add a notice period for the tenant too.", law: "Contract Act, 1872" },
    { title: "Stamp duty", status: "check", detail: "A lease must be on stamp paper of the right value. Check it before signing.", law: "Stamp Act, 1899" },
    { title: "Signed before two witnesses", status: "present", detail: "Clause 11 records signature at Lahore before two witnesses.", law: null },
];
const COMPLIANCE_TONE = { missing: ["high", "Missing"], check: ["medium", "Check"], present: ["low", "Present"] };

const DI = {
    spark: <path d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9z" />,
    clause: <><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></>,
    risk: <><path d="M12 3l9.5 17h-19z" /><path d="M12 10v4M12 17.5v.01" /></>,
    check: <><circle cx="12" cy="12" r="9" /><path d="M8 12.5l2.5 2.5L16 9.5" /></>,
    shield: <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" />,
    gavel: <path d="M14 4l6 6M11 7l6 6M8.5 9.5l6-6M13 15.5l6-6M12 12l-8 8" />,
    doc: <><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M9 8h6M9 12h6M9 16h4" /></>,
    chat: <path d="M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H10l-5 4v-4H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" />,
    back: <path d="M15 5l-7 7 7 7" />,
    redo: <path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5" />,
    upload: <path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />,
    send: <path d="M4 12l16-8-6 16-2.5-6.5z" />,
    book: <path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zM4 19V5" />,
};
/* The analyzer's typeface: Nunito Sans, a free face close to the Avenir the
 * reference design uses (Avenir itself is a licensed font). Loaded in
 * app/globals.css; falls back to Avenir where it is installed. */
export const ANALYZER_FONT = "'Nunito Sans', 'Avenir Next', Avenir, system-ui, sans-serif";

const DIcon = ({ d, s = 17 }) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>;

function SectionHead({ t, icon, tone, title, sub, count }) {
    const c = SEVERITY[tone] || SEVERITY.info;
    return (
        <div style={{ display: "flex", alignItems: "center", gap: 14, margin: "6px 0 14px" }}>
            <span style={{ width: 46, height: 46, borderRadius: 12, background: c.bg, color: c.fg, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}><DIcon d={icon} s={21} /></span>
            <div style={{ flex: 1 }}>
                <div style={{ fontFamily: ANALYZER_FONT, fontSize: 26, fontWeight: 500, color: t.text }}>{title}</div>
                {sub && <div style={{ fontSize: 12.5, color: t.textMuted }}>{sub}</div>}
            </div>
            {count != null && <span style={{ minWidth: 30, height: 30, padding: "0 8px", borderRadius: 999, background: t.card, border: `1px solid ${t.border}`, color: t.text, fontSize: 13, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{count}</span>}
        </div>
    );
}

export function AnalysisDashboard({ sample, side, depth, onDepth, onBack, onReanalyze }) {
    const t = useT();
    const toast = useToast();
    const isMobile = useIsMobile();
    const [tab, setTab] = useState("summary");
    const [hl, setHl] = useState(null);          // clause highlighted on the Document tab
    const [ask, setAsk] = useState("");
    const [chat, setChat] = useState([]);
    const notYet = what => () => toast.show(`${what} isn't connected yet — coming soon.`, "warn", 3000);
    const light = t.mode !== "dark";
    const issueBox = light ? { background: "#fdf7e6", color: "#7a5200" } : { background: "rgba(242,184,75,0.12)", color: "#f7cf7d" };
    const recBox = light ? { background: "#e8f1fc", color: "#1d4f91" } : { background: "rgba(90,169,230,0.13)", color: "#b9dcf7" };
    const high = RISKS.filter(r => r.sev === "high").length;
    const missing = COMPLIANCE.filter(c => c.status === "missing").length;

    const TABS = [
        ["summary", "Summary", DI.spark, null],
        ["clauses", "Key Clauses", DI.clause, KEY_CLAUSES.length],
        ["risks", "Risks", DI.risk, RISKS.length],
        ["obligations", "Obligations", DI.check, OBLIGATIONS.length],
        ["compliance", "Compliance", DI.shield, COMPLIANCE.length],
        ["precedents", "Precedents", DI.gavel, 0],
        ["document", "Document", DI.doc, null],
        ["ask", "Ask AI", DI.chat, null],
    ];
    const card = { background: t.card, border: `1px solid ${t.border}`, borderRadius: 16, padding: "18px 20px" };
    const showInDoc = id => { setHl(id); setTab("document"); };

    const clausesSection = (
        <section key="clauses" aria-label="Key clauses">
            <SectionHead t={t} icon={DI.clause} tone="info" title="Key Clauses" sub={`${KEY_CLAUSES.length} clause(s) flagged with issues`} count={KEY_CLAUSES.length} />
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {KEY_CLAUSES.map(k => (
                    <article key={k.id} style={card}>
                        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                            <h3 style={{ margin: 0, fontSize: 16.5, fontWeight: 600, color: t.text, flex: 1 }}>{k.title}</h3>
                            <button type="button" onClick={() => showInDoc(k.id)} style={{ background: "none", border: "none", color: t.primary, fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>View in document →</button>
                        </div>
                        <blockquote style={{ margin: "10px 0 12px", padding: "2px 0 2px 14px", borderLeft: `3px solid ${t.border}`, fontStyle: "italic", color: t.textDim || t.text, fontSize: 14, lineHeight: 1.6 }}>“{k.quote}”</blockquote>
                        <div style={{ ...issueBox, borderRadius: 10, padding: "10px 14px", fontSize: 13.5, lineHeight: 1.55 }}><b>Issues:</b> {k.issues.join(", ")}</div>
                    </article>
                ))}
            </div>
        </section>
    );
    const risksSection = (
        <section key="risks" aria-label="Risks">
            <SectionHead t={t} icon={DI.risk} tone="high" title="Risks" sub={`${high} high · ${RISKS.length - high} medium — for the ${side.toLowerCase()}`} count={RISKS.length} />
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {RISKS.map(r => {
                    const c = SEVERITY[r.sev];
                    return (
                        <article key={r.id} style={card}>
                            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                                <span style={{ color: c.fg, display: "flex" }}><DIcon d={DI.risk} s={19} /></span>
                                <h3 style={{ margin: 0, fontSize: 16.5, fontWeight: 600, color: t.text }}>{r.title}</h3>
                                <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 9px", borderRadius: 999, background: c.bg, color: c.fg }}>{r.sev.toUpperCase()} RISK</span>
                                <span style={{ flex: 1 }} />
                                <button type="button" onClick={() => showInDoc(r.id)} style={{ background: "none", border: "none", color: t.primary, fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>View in document →</button>
                            </div>
                            <p style={{ margin: "8px 0 12px", fontSize: 14, color: t.textDim || t.text, lineHeight: 1.6 }}>{r.why}</p>
                            <div style={{ ...recBox, borderRadius: 10, padding: "10px 14px", fontSize: 13.5, lineHeight: 1.55 }}><b>Recommendation:</b> {r.fix}</div>
                            <div style={{ fontSize: 12, color: t.success, marginTop: 8 }}>{r.cite}</div>
                        </article>
                    );
                })}
            </div>
        </section>
    );
    const obligationsSection = (
        <section key="obligations" aria-label="Obligations">
            <SectionHead t={t} icon={DI.check} tone="info" title="Obligations" sub={`${OBLIGATIONS.length} with deadlines`} count={OBLIGATIONS.length} />
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {OBLIGATIONS.map((o, i) => (
                    <article key={i} style={{ ...card, display: "flex", gap: 12, alignItems: "flex-start" }}>
                        <div style={{ flex: 1 }}>
                            <h3 style={{ margin: 0, fontSize: 16.5, fontWeight: 600, color: t.text }}>{o.party}</h3>
                            <p style={{ margin: "6px 0 6px", fontSize: 14, color: t.textDim || t.text, lineHeight: 1.55 }}>{o.text}</p>
                            <div style={{ fontSize: 12.5, color: t.textMuted }}>Deadline: {o.deadline}</div>
                        </div>
                        <Pill tone="info" style={{ fontSize: 11, letterSpacing: ".04em" }}>{o.status.toUpperCase()}</Pill>
                    </article>
                ))}
            </div>
        </section>
    );
    const complianceSection = (
        <section key="compliance" aria-label="Compliance">
            <SectionHead t={t} icon={DI.shield} tone="low" title="Compliance" sub={`${missing} missing · checked against the rent-agreement playbook`} count={COMPLIANCE.length} />
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {COMPLIANCE.map(c => {
                    const [tone, label] = COMPLIANCE_TONE[c.status];
                    return (
                        <article key={c.title} style={{ ...card, display: "flex", gap: 12, alignItems: "flex-start" }}>
                            <div style={{ flex: 1 }}>
                                <h3 style={{ margin: 0, fontSize: 16.5, fontWeight: 600, color: t.text }}>{c.title}</h3>
                                <p style={{ margin: "6px 0 4px", fontSize: 14, color: t.textDim || t.text, lineHeight: 1.55 }}>{c.detail}</p>
                                {c.law && <div style={{ fontSize: 12, color: t.success }}>{c.law}</div>}
                            </div>
                            <Pill tone={tone} style={{ fontSize: 11, letterSpacing: ".04em" }}>{label.toUpperCase()}</Pill>
                        </article>
                    );
                })}
            </div>
        </section>
    );
    const precedentsSection = (
        <section key="precedents" aria-label="Precedents">
            <SectionHead t={t} icon={DI.gavel} tone="low" title="Precedents" sub="Case law that bears on these clauses" count={0} />
            <div data-precedents-empty style={{ ...card, textAlign: "center", padding: "30px 24px" }}>
                <div style={{ fontSize: 15, fontWeight: 600, color: t.text, marginBottom: 6 }}>Precedent matching isn't connected yet</div>
                <div style={{ fontSize: 13.5, color: t.textMuted, lineHeight: 1.6, maxWidth: 560, margin: "0 auto" }}>
                    When it is, cases will come from the judgments in Attorney.AI's library and each citation will be checked before it is shown. No case is listed until then — a made-up citation is worse than none.
                </div>
            </div>
        </section>
    );
    const documentSection = (
        <section key="document" aria-label="Document" style={{ display: "flex", justifyContent: "center" }}>
            <Paper title="TENANCY AGREEMENT" width={680} style={{ fontSize: 14.5, lineHeight: 1.75 }}>
                {CLAUSES.map(([id, text]) => {
                    const r = RISKS.find(x => x.id === id);
                    if (!r) return <p key={id} style={{ margin: "0 0 8px" }}>{text}</p>;
                    const c = SEVERITY[r.sev];
                    return (
                        <button key={id} type="button" onClick={() => { setTab("risks"); }}
                            style={{ display: "block", width: "100%", textAlign: "left", font: "inherit", color: "inherit", border: "none", borderRadius: 6, padding: "6px 8px", margin: "0 -8px 8px", cursor: "pointer", background: hl === id ? c.paper : `${c.paper}99`, outline: hl === id ? `2px solid ${c.line}` : "none" }}>
                            <span style={{ fontFamily: ANALYZER_FONT, fontSize: 10.5, fontWeight: 700, padding: "1px 6px", borderRadius: 4, marginRight: 6, background: c.bg, color: c.fg }}>{r.sev.toUpperCase()}</span>
                            {text}
                        </button>
                    );
                })}
            </Paper>
        </section>
    );
    const send = () => {
        const q = ask.trim();
        if (!q) return;
        setChat(c => [...c, { who: "you", text: q }, { who: "ai", text: "I can't answer yet — the analyzer isn't connected, so there is no reading of your document to answer from. This is a preview of how asking will work." }]);
        setAsk("");
    };
    const askSection = (
        <section key="ask" aria-label="Ask about this document">
            <SectionHead t={t} icon={DI.chat} tone="low" title="Ask about this document" sub="Chat with the analysis of your document" />
            <div style={{ ...card, padding: 0, overflow: "hidden" }}>
                <div data-lenis-prevent style={{ minHeight: 240, maxHeight: 420, overflowY: "auto", padding: 20, display: "flex", flexDirection: "column", gap: 10 }}>
                    {chat.length === 0 ? (
                        <div style={{ margin: "auto", textAlign: "center", color: t.textMuted, fontSize: 14 }}>
                            <div style={{ color: t.primary, marginBottom: 8, display: "flex", justifyContent: "center" }}><DIcon d={DI.spark} s={26} /></div>
                            Start asking questions about this document — e.g. “can I leave early?”
                        </div>
                    ) : chat.map((m, i) => (
                        <div key={i} style={{ alignSelf: m.who === "you" ? "flex-end" : "flex-start", maxWidth: "80%", padding: "10px 14px", borderRadius: 14, fontSize: 14, lineHeight: 1.55, background: m.who === "you" ? t.primary : t.inputBg, color: m.who === "you" ? onPrimary(t) : t.text, border: m.who === "you" ? "none" : `1px solid ${t.border}` }}>{m.text}</div>
                    ))}
                </div>
                <div style={{ borderTop: `1px solid ${t.border}`, padding: 12 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "6px 6px 6px 14px", borderRadius: 12, background: t.inputBg, border: `1px solid ${ask ? t.primary : (t.inputBorder || t.border)}` }}>
                        <label htmlFor="ask-doc" style={{ position: "absolute", left: -9999 }}>Ask a question about this document</label>
                        <input id="ask-doc" value={ask} onChange={e => setAsk(e.target.value)} onKeyDown={e => { if (e.key === "Enter") send(); }}
                            placeholder="Ask a question about this document…"
                            style={{ flex: 1, minHeight: 34, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 14, fontFamily: ANALYZER_FONT }} />
                        <button type="button" aria-label="Send question" onClick={send} disabled={!ask.trim()}
                            style={{ width: 38, height: 38, borderRadius: 10, border: "none", background: t.primary, color: onPrimary(t), cursor: ask.trim() ? "pointer" : "not-allowed", opacity: ask.trim() ? 1 : 0.5, display: "flex", alignItems: "center", justifyContent: "center" }}><DIcon d={DI.send} s={16} /></button>
                    </div>
                    <div style={{ fontSize: 11.5, color: t.textMuted, textAlign: "center", marginTop: 8 }}>Attorney.AI can make mistakes — check important answers with a lawyer.</div>
                </div>
            </div>
        </section>
    );

    const stats = [
        ["Risks", RISKS.length, `${high} high/critical`, "high", DI.risk, "risks"],
        ["Obligations", OBLIGATIONS.length, `${OBLIGATIONS.length} with deadlines`, "info", DI.check, "obligations"],
        ["Key Clauses", KEY_CLAUSES.length, `${KEY_CLAUSES.length} with issues`, "medium", DI.clause, "clauses"],
        ["Compliance", COMPLIANCE.length, `${missing} missing`, "low", DI.shield, "compliance"],
    ];
    const seg = on => ({ minHeight: 34, padding: "0 14px", borderRadius: 8, border: "none", background: on ? t.card : "transparent", color: on ? t.primary : t.textMuted, fontWeight: on ? 600 : 500, fontSize: 17, cursor: "pointer", fontFamily: ANALYZER_FONT, boxShadow: on ? "0 1px 3px rgba(0,0,0,.2)" : "none" });

    return (
        <div data-lenis-prevent style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", fontFamily: ANALYZER_FONT }}>
            {/* Title row — "← Document Analyzer", as in the reference */}
            <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", padding: isMobile ? "60px 14px 6px" : "16px 22px 8px", background: t.surface }}>
                <button type="button" onClick={onBack} aria-label="Back to Document Analyzer" title="Back to Document Analyzer"
                    style={{ width: 36, height: 36, borderRadius: 9, border: "none", background: "transparent", color: t.text, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M19 12H5M11 6l-6 6 6 6" /></svg>
                </button>
                <h1 style={{ margin: 0, fontSize: 30, fontWeight: 600, letterSpacing: "-0.2px", color: t.text, fontFamily: ANALYZER_FONT }}>Document Analyzer</h1>
                <PreviewBadge what="The analyzer" />
            </div>

            {/* Action row */}
            <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", padding: isMobile ? "4px 14px 12px" : "6px 22px 14px", borderBottom: `1px solid ${t.border}`, background: t.surface }}>
                <button type="button" onClick={notYet("Resources")}
                    style={{ display: "inline-flex", alignItems: "center", gap: 10, minHeight: 42, padding: "0 12px 0 14px", borderRadius: 10, border: `1px solid ${t.border}`, background: t.card, color: t.text, fontSize: 18, fontWeight: 500, cursor: "pointer", fontFamily: ANALYZER_FONT }}>
                    <DIcon d={DI.book} s={17} /> Resources
                    <span style={{ minWidth: 24, height: 24, borderRadius: 999, background: t.primaryGlow2, color: t.primary, fontSize: 12, fontWeight: 700, display: "inline-flex", alignItems: "center", justifyContent: "center", marginLeft: 8 }}>1</span>
                </button>
                <button type="button" onClick={onBack}
                    style={{ display: "inline-flex", alignItems: "center", gap: 8, minHeight: 42, padding: "0 10px", borderRadius: 10, border: "none", background: "transparent", color: t.textMuted, fontSize: 18, fontWeight: 400, cursor: "pointer", fontFamily: ANALYZER_FONT }}>
                    <DIcon d={DI.back} s={16} /> Back to Document Analyzer
                </button>
                {/* Pushes Add Resource and Re-analyze to the right edge. */}
                <span aria-hidden="true" style={{ flex: 1 }} />
                <button type="button" onClick={notYet("Adding another document")}
                    style={{ display: "inline-flex", alignItems: "center", gap: 10, minHeight: 42, padding: "0 18px", borderRadius: 10, border: "none", background: "linear-gradient(135deg, #1f8a5b, #0f7f73)", color: "#fff", fontSize: 18, fontWeight: 500, cursor: "pointer", fontFamily: ANALYZER_FONT }}>
                    <DIcon d={DI.upload} s={16} /> Add Resource
                </button>
                <button type="button" onClick={onReanalyze}
                    style={{ display: "inline-flex", alignItems: "center", gap: 10, minHeight: 42, padding: "0 18px", borderRadius: 10, border: `1px solid ${t.border}`, background: t.card, color: t.textMuted, fontSize: 18, fontWeight: 400, cursor: "pointer", fontFamily: ANALYZER_FONT }}>
                    <DIcon d={DI.redo} s={16} /> Re-analyze
                </button>
            </div>

            <div data-lenis-prevent style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
                {/* Heading */}
                <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", padding: isMobile ? "18px 14px 12px" : "26px 32px 16px" }}>
                    <div style={{ flex: 1, minWidth: 240 }}>
                        <h1 style={{ margin: 0, fontFamily: ANALYZER_FONT, fontSize: 36, fontWeight: 600, letterSpacing: "-0.3px", color: t.text }}>Aggregated Dashboard</h1>
                        <div style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 8, fontSize: 16, fontWeight: 600, letterSpacing: ".12em", textTransform: "uppercase", color: t.primary }}>
                            <DIcon d={DI.redo} s={17} /> Analyzing 1 document
                        </div>
                        {/* Whose analysis this is, kept out of the heading line but never dropped. */}
                        <div style={{ marginTop: 4, fontSize: 12.5, color: t.textMuted }}>{sample} (sample) · as the {side}</div>
                    </div>
                    <div role="group" aria-label="Language" style={{ display: "flex", gap: 2, padding: 4, borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}` }}>
                        <button type="button" aria-pressed="true" style={seg(true)}>English</button>
                        <button type="button" aria-pressed="false" onClick={notYet("Urdu analysis")} style={seg(false)}>اردو</button>
                    </div>
                    <div role="group" aria-label="Scan depth" style={{ display: "flex", gap: 2, padding: 4, borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}` }}>
                        {[["quick", "Quick scan"], ["medium", "Medium"], ["deep", "Deep scan"]].map(([k, name]) => (
                            <button key={k} type="button" aria-pressed={depth === k} onClick={() => { if (depth !== k) onDepth(k); }} style={seg(depth === k)}>{name}</button>
                        ))}
                    </div>
                </div>

                {/* Tabs */}
                <div role="tablist" aria-label="Analysis sections" className="thin-scrollbar"
                    style={{ position: "sticky", top: 0, zIndex: 2, display: "flex", gap: 8, overflowX: "auto", padding: isMobile ? "10px 14px" : "12px 32px", background: t.bg, borderBottom: `1px solid ${t.border}` }}>
                    {TABS.map(([id, name, icon, count]) => {
                        const on = tab === id;
                        return (
                            <button key={id} type="button" role="tab" aria-selected={on} onClick={() => setTab(id)}
                                style={{ display: "inline-flex", alignItems: "center", gap: 8, flexShrink: 0, minHeight: 42, padding: "0 16px", borderRadius: 12, border: `1px solid ${on ? t.primary : t.border}`, background: on ? t.primary : t.card, color: on ? onPrimary(t) : t.text, fontSize: 18, fontWeight: on ? 600 : 500, cursor: "pointer", fontFamily: ANALYZER_FONT }}>
                                <DIcon d={icon} s={16} /> {name}
                                {count != null && <span style={{ minWidth: 22, height: 22, padding: "0 6px", borderRadius: 999, fontSize: 12, fontWeight: 700, display: "inline-flex", alignItems: "center", justifyContent: "center", background: on ? "rgba(255,255,255,.25)" : t.inputBg, color: on ? onPrimary(t) : t.textMuted }}>{count}</span>}
                            </button>
                        );
                    })}
                </div>

                {/* Content */}
                <div style={{ padding: isMobile ? "18px 14px 28px" : "22px 32px 36px", display: "flex", flexDirection: "column", gap: 28, maxWidth: 1180 }}>
                    {tab === "summary" && (
                        <>
                            <SectionHead t={t} icon={DI.spark} tone="low" title="Summary" />
                            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 14, marginTop: -14 }}>
                                {stats.map(([label, n, sub, tone, icon, go]) => {
                                    const c = SEVERITY[tone];
                                    return (
                                        <button key={label} type="button" onClick={() => setTab(go)}
                                            style={{ ...card, textAlign: "left", cursor: "pointer", fontFamily: ANALYZER_FONT }}>
                                            <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 15, fontWeight: 600, letterSpacing: ".12em", color: c.fg }}><DIcon d={icon} s={20} /> {label.toUpperCase()}</div>
                                            <div style={{ fontSize: 48, fontWeight: 700, color: t.text, margin: "14px 0 8px", lineHeight: 1 }}>{n}</div>
                                            <div style={{ fontSize: 16, fontWeight: 600, color: c.fg }}>{sub}</div>
                                        </button>
                                    );
                                })}
                            </div>
                            <article style={{ ...card, padding: "22px 24px" }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
                                    <span style={{ width: 42, height: 42, borderRadius: 11, background: SEVERITY.low.bg, color: SEVERITY.low.fg, display: "flex", alignItems: "center", justifyContent: "center" }}><DIcon d={DI.spark} s={19} /></span>
                                    <h2 style={{ margin: 0, fontFamily: ANALYZER_FONT, fontSize: 26, fontWeight: 500, color: t.text }}>Aggregated Executive Summary</h2>
                                </div>
                                <p style={{ margin: "0 0 10px", fontSize: 15, lineHeight: 1.7, color: t.text }}>{SUMMARY}</p>
                                <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 14 }}>Governing law detected: Punjab Rented Premises Act, 2009.</div>
                                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
                                    {TERMS.map(([k, v]) => (
                                        <div key={k} style={{ padding: "10px 12px", borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}` }}>
                                            <div style={{ fontSize: 12, color: t.textMuted }}>{k}</div>
                                            <div style={{ fontSize: 14.5, fontWeight: 600, marginTop: 2, color: t.text }}>{v}</div>
                                        </div>
                                    ))}
                                </div>
                            </article>
                            {clausesSection}
                            {risksSection}
                            {obligationsSection}
                            {complianceSection}
                            {precedentsSection}
                        </>
                    )}
                    {tab === "clauses" && clausesSection}
                    {tab === "risks" && risksSection}
                    {tab === "obligations" && obligationsSection}
                    {tab === "compliance" && complianceSection}
                    {tab === "precedents" && precedentsSection}
                    {tab === "document" && documentSection}
                    {tab === "ask" && askSection}
                </div>
            </div>
        </div>
    );
}

/* ── The start screen: history on the left; greeting, upload and focus ──────
 *
 * The user's own file is still never analysed (see the file header): a file
 * chosen or dropped is announced as not read. The sample is reachable from
 * History and from the drop zone, and is named "(sample)" wherever it shows. */
export function greetingFor(date = new Date()) {
    const h = date.getHours();
    if (h < 5 || h >= 18) return { text: "Good Evening", sub: "Let's dig into the file.", icon: "moon", night: true };
    if (h < 12) return { text: "Good Morning", sub: "Let's review your documents.", icon: "sun", night: false };
    return { text: "Good Afternoon", sub: "Get instant insights from your file.", icon: "cloud", night: false };
}

const Moon = () => (
    <svg width="46" height="46" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" fill="#a9b4ff" /></svg>
);
const Sun = () => (
    <svg width="46" height="46" viewBox="0 0 24 24" fill="none" stroke="#f2b84b" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.5" fill="#f2b84b" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
);

/* Afternoon: the sun behind a cloud. */
const SunCloud = () => (
    <svg width="50" height="46" viewBox="0 0 28 26" aria-hidden="true">
        <g stroke="#f7a23b" strokeWidth="1.8" strokeLinecap="round">
            <path d="M17 1.5v2.2M24.3 4.6l-1.6 1.6M26.9 11.5h-2.2M9.7 4.6l1.6 1.6" />
        </g>
        <circle cx="17" cy="11" r="5" fill="#f7a23b" />
        <path d="M7.5 24.5h13.2a4.8 4.8 0 0 0 .4-9.6 6.6 6.6 0 0 0-12.6 1.5 4.1 4.1 0 0 0-1 8.1z" fill="#f47a25" />
    </svg>
);

const HISTORY_CLEARED_KEY = "attorney.analyzer.historyCleared";

function UploadScreen({ userName, stage, sample, side, onSide, depth, onDepth, focusText, onFocusText,
    onPickFile, onDropFiles, onPickSample, onClearSample, onAnalyze, onOpenSample, onNewReview }) {
    const t = useT();
    const isMobile = useIsMobile();
    const [historyOpen, setHistoryOpen] = useState(true);
    const [groupOpen, setGroupOpen] = useState(true);
    const [collapsed, setCollapsed] = useState(false);
    const [dragging, setDragging] = useState(false);
    const [menuOpen, setMenuOpen] = useState(false);
    const [cleared, setCleared] = useState(() => {
        try { return window.localStorage.getItem(HISTORY_CLEARED_KEY) === "1"; } catch { return false; }
    });
    const menuRef = useRef(null);
    useEffect(() => {
        if (!menuOpen) return;
        const close = e => { if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false); };
        const esc = e => { if (e.key === "Escape") setMenuOpen(false); };
        document.addEventListener("mousedown", close);
        document.addEventListener("keydown", esc);
        return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
    }, [menuOpen]);
    const setClearedSaved = value => {
        setCleared(value);
        try {
            if (value) window.localStorage.setItem(HISTORY_CLEARED_KEY, "1");
            else window.localStorage.removeItem(HISTORY_CLEARED_KEY);
        } catch { /* storage blocked: the choice lasts for this visit only */ }
    };
    const deleteHistory = () => {
        setMenuOpen(false);
        if (!window.confirm("Delete your analysis history? This removes it from this list.")) return;
        setClearedSaved(true);
    };
    const g = greetingFor();
    const first = (userName || "").trim().split(/\s+/)[0] || "there";
    const ready = stage === "ready";
    const bigCard = { background: t.surface, border: `1px solid ${t.border}`, borderRadius: 20, padding: isMobile ? 14 : 22 };
    const select = { height: 40, borderRadius: 10, border: `1px solid ${t.inputBorder || t.border}`, background: t.inputBg, color: t.text, padding: "0 10px", fontSize: 13, fontWeight: 600, fontFamily: ANALYZER_FONT, cursor: "pointer" };

    return (
        <div data-lenis-prevent style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: isMobile ? "column" : "row", overflow: isMobile ? "auto" : "hidden", paddingTop: isMobile ? 56 : 0, fontFamily: ANALYZER_FONT }}>
            {/* History — a collapsible column (the round button on its edge) */}
            {!isMobile && collapsed ? (
                <div style={{ position: "relative", flex: "0 0 0px" }}>
                    <button type="button" onClick={() => setCollapsed(false)} aria-label="Show history" title="Show history"
                        style={{ position: "absolute", left: 12, bottom: 24, zIndex: 3, width: 44, height: 44, borderRadius: "50%", border: "none", background: "linear-gradient(135deg, #1f8a5b, #0f7f73)", color: "#fff", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 6px 18px rgba(0,0,0,.3)" }}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
                    </button>
                </div>
            ) : (
            <aside aria-label="Analysis history" style={{ position: "relative", flex: isMobile ? "none" : "0 0 230px", borderRight: isMobile ? "none" : `1px solid ${t.border}`, borderBottom: isMobile ? `1px solid ${t.border}` : "none", display: "flex", flexDirection: "column", minHeight: 0, background: t.surface }}>
                <div style={{ padding: "16px 14px 14px" }}>
                    <button type="button" onClick={onNewReview}
                        style={{ width: "100%", minHeight: 38, borderRadius: 999, border: "1px solid rgba(255,255,255,.25)", background: "linear-gradient(90deg, #1f8a5b, #127a70)", color: "#e8fff9", fontSize: 13, fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 8, fontFamily: ANALYZER_FONT, boxShadow: "0 3px 10px rgba(15,127,115,.22)" }}>
                        <DIcon d={DI.doc} s={14} /> Document Review
                    </button>
                </div>
                <div style={{ height: 1, background: t.border }} />
                <div data-lenis-prevent style={{ flex: 1, overflowY: "auto", padding: "18px 10px 90px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "0 4px 14px" }}>
                        <span style={{ flex: 1, fontSize: 16, fontWeight: 700, color: t.text }}>History</span>
                        <button type="button" onClick={() => setHistoryOpen(o => !o)} aria-expanded={historyOpen} aria-label={historyOpen ? "Collapse history" : "Expand history"}
                            style={{ width: 34, height: 34, borderRadius: 8, border: "none", background: "transparent", color: t.text, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ transform: historyOpen ? "none" : "rotate(180deg)", transition: "transform .2s" }}><path d="M6 15l6-6 6 6" /></svg>
                        </button>
                        <div ref={menuRef} style={{ position: "relative" }}>
                            <button type="button" onClick={() => setMenuOpen(o => !o)} aria-label="History options" title="History options"
                                aria-haspopup="menu" aria-expanded={menuOpen}
                                style={{ width: 34, height: 34, borderRadius: 8, border: "none", background: menuOpen ? t.inputBg : "transparent", color: t.text, cursor: "pointer", fontSize: 18, lineHeight: 1 }}>&#8943;</button>
                            {menuOpen && (
                                <div role="menu" aria-label="History options"
                                    style={{ position: "absolute", right: 0, top: 34, zIndex: 5, width: "max-content", padding: 2, borderRadius: 7, background: t.card, border: `1px solid ${t.border}`, boxShadow: "0 6px 16px rgba(0,0,0,.3)" }}>
                                    <button type="button" role="menuitem" onClick={deleteHistory} disabled={cleared} aria-label={cleared ? "History is empty" : "Delete history"}
                                        style={{ display: "flex", alignItems: "center", gap: 6, width: "100%", padding: "4px 8px", borderRadius: 5, border: "none", background: "transparent", color: cleared ? t.textMuted : "#f07a7a", fontSize: 12, fontWeight: 600, whiteSpace: "nowrap", cursor: cleared ? "not-allowed" : "pointer", fontFamily: ANALYZER_FONT, textAlign: "left" }}
                                        onMouseEnter={e => { if (!cleared) e.currentTarget.style.background = "rgba(240,122,122,.12)"; }}
                                        onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}>
                                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></svg>
                                        {cleared ? "Empty" : "Delete"}
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>
                    {historyOpen && cleared && (
                        <div data-history-empty style={{ padding: "6px 8px", fontSize: 13, color: t.textMuted, lineHeight: 1.55 }}>
                            No history yet.{" "}
                            <button type="button" onClick={() => setClearedSaved(false)}
                                style={{ background: "none", border: "none", padding: 0, color: t.primary, fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
                                Restore sample
                            </button>
                        </div>
                    )}
                    {historyOpen && !cleared && (
                        <>
                            <button type="button" onClick={() => setGroupOpen(o => !o)} aria-expanded={groupOpen}
                                style={{ display: "flex", alignItems: "center", gap: 8, width: "100%", padding: "4px 6px 8px", background: "none", border: "none", color: t.text, fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: ANALYZER_FONT }}>
                                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ transform: groupOpen ? "none" : "rotate(-90deg)", transition: "transform .2s" }}><path d="M6 9l6 6 6-6" /></svg>
                                Samples
                            </button>
                            {groupOpen && (
                                <button type="button" onClick={onOpenSample} data-history-sample title="Opens the sample analysis"
                                    style={{ display: "block", width: "100%", textAlign: "left", padding: "8px 14px", borderRadius: 10, border: "none", background: "transparent", color: t.text, fontSize: 13.5, cursor: "pointer", fontFamily: ANALYZER_FONT, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
                                    onMouseEnter={e => { e.currentTarget.style.background = t.inputBg; }}
                                    onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}>
                                    {SAMPLES[0][0]} (sample)
                                </button>
                            )}
                        </>
                    )}
                </div>
                {!isMobile && (
                    <button type="button" onClick={() => setCollapsed(true)} aria-label="Hide history" title="Hide history"
                        style={{ position: "absolute", right: -22, bottom: 24, zIndex: 3, width: 44, height: 44, borderRadius: "50%", border: "none", background: "linear-gradient(135deg, #1f8a5b, #0f7f73)", color: "#fff", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 6px 18px rgba(0,0,0,.3)" }}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
                    </button>
                )}
            </aside>
            )}

            {/* Main */}
            <main data-lenis-prevent style={{ flex: 1, minWidth: 0, overflowY: isMobile ? "visible" : "auto", padding: isMobile ? "18px 14px 24px" : "28px 32px 24px" }}>
                <div style={{ maxWidth: 1120, margin: "0 auto", display: "flex", flexDirection: "column", gap: 18 }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                        <div>
                            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                                {g.icon === "moon" ? <Moon /> : g.icon === "cloud" ? <SunCloud /> : <Sun />}
                                <h1 style={{ margin: 0, fontSize: isMobile ? 24 : 32, fontWeight: 400, letterSpacing: "-0.2px", color: t.text, fontFamily: ANALYZER_FONT }}>{g.text}, {first}!</h1>
                            </div>
                            <div style={{ fontSize: isMobile ? 16 : 22, fontWeight: 400, color: t.textMuted, marginTop: 10 }}>{g.sub}</div>
                        </div>
                        <PreviewBadge what="The analyzer" />
                    </div>

                    {/* Upload */}
                    <section style={{ ...bigCard, display: "flex", gap: isMobile ? 16 : 24, flexDirection: isMobile ? "column" : "row", alignItems: "stretch" }}>
                        <div style={{ flex: isMobile ? "none" : "0 0 260px", display: "flex", flexDirection: "column", gap: 10 }}>
                            <span style={{ width: 42, height: 42, borderRadius: 11, background: "linear-gradient(135deg, #1f8a5b, #0f7f73)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center" }}><DIcon d={DI.spark} s={19} /></span>
                            <h2 style={{ margin: "4px 0 0", fontSize: 17, fontWeight: 700, color: t.text, lineHeight: 1.3 }}>Upload a Legal Document</h2>
                            <p style={{ margin: 0, fontSize: 13, color: t.textMuted, lineHeight: 1.55 }}>Upload contracts, agreements, policies or legal files for AI-powered review.</p>
                        </div>
                        <div
                            onDragOver={e => { e.preventDefault(); setDragging(true); }}
                            onDragLeave={() => setDragging(false)}
                            onDrop={e => { e.preventDefault(); setDragging(false); onDropFiles(e.dataTransfer?.files); }}
                            style={{ flex: 1, minWidth: 0, minHeight: isMobile ? 200 : 260, borderRadius: 16, border: `2px dashed ${dragging ? t.primary : t.borderHi || t.border}`, background: dragging ? t.primaryGlow2 : "transparent", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10, padding: "20px 18px", textAlign: "center" }}>
                            {ready ? (
                                <>
                                    <span style={{ width: 44, height: 54, borderRadius: 8, background: "#fdecec", color: "#b3261e", fontSize: 12, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center" }}>PDF</span>
                                    <div style={{ fontSize: 15.5, fontWeight: 700, color: t.text }}>{sample}.pdf <span style={{ fontSize: 13, fontWeight: 500, color: t.textMuted }}>(sample)</span></div>
                                    <div style={{ fontSize: 13.5, color: t.textMuted }}>4 pages · text found · ready to analyze</div>
                                    <Btn onClick={onClearSample} style={{ minHeight: 38 }}>Remove</Btn>
                                </>
                            ) : (
                                <>
                                    <span style={{ color: t.primary, opacity: 0.55 }}><DIcon d={DI.upload} s={26} /></span>
                                    <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Drag & Drop Documents Here</div>
                                    <div style={{ fontSize: 11.5, color: t.textMuted, letterSpacing: ".06em" }}>OR</div>
                                    <button type="button" onClick={onPickFile}
                                        style={{ minHeight: 38, padding: "0 20px", borderRadius: 10, border: `1px solid ${t.text}`, background: "transparent", color: t.primary, fontSize: 14, fontWeight: 700, cursor: "pointer", fontFamily: ANALYZER_FONT }}>
                                        Select Files
                                    </button>
                                    <div style={{ fontSize: 12, color: t.textMuted }}>PDF • DOCX • DOC • Max 50MB</div>
                                    <button type="button" onClick={onPickSample}
                                        style={{ background: "none", border: "none", color: t.primary, fontSize: 12, fontWeight: 600, cursor: "pointer", marginTop: 0 }}>
                                        No document handy? Try the sample rent agreement →
                                    </button>
                                </>
                            )}
                        </div>
                    </section>

                    {/* Focus */}
                    <section style={{ ...bigCard, display: "flex", flexDirection: "column", gap: 18 }}>
                        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                            <span style={{ color: t.primary, alignSelf: "center" }}><DIcon d={DI.spark} s={19} /></span>
                            <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: t.text }}>Tell AI What To Focus On</h2>
                            <span style={{ fontSize: 13, color: t.textMuted }}>(optional)</span>
                        </div>
                        <label htmlFor="an-focus" style={{ position: "absolute", left: -9999 }}>What should the review focus on</label>
                        <textarea id="an-focus" rows={4} value={focusText} onChange={e => onFocusText(e.target.value)}
                            placeholder="Review risks in this contract… check compliance issues… Summarize this agreement…"
                            style={{ width: "100%", boxSizing: "border-box", resize: "vertical", borderRadius: 14, border: `1px solid ${t.inputBorder || t.border}`, background: t.inputBg, color: t.text, padding: "12px 16px", fontSize: 14, lineHeight: 1.6, fontFamily: ANALYZER_FONT, outline: "none" }} />
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 12, flexWrap: "wrap" }}>
                            <label htmlFor="an-side" style={{ fontSize: 12.5, color: t.textMuted }}>Your side</label>
                            <select id="an-side" value={side} onChange={e => onSide(e.target.value)} style={select}>
                                {["Tenant", "Landlord", "Neutral"].map(s => <option key={s} value={s}>{s}</option>)}
                            </select>
                            <label htmlFor="an-depth" style={{ position: "absolute", left: -9999 }}>Review depth</label>
                            <select id="an-depth" value={depth} onChange={e => onDepth(e.target.value)} style={select}>
                                <option value="quick">✦ Quick</option>
                                <option value="medium">✦ Medium</option>
                                <option value="deep">✦ Deep</option>
                            </select>
                            <button type="button" onClick={onAnalyze} disabled={!ready}
                                title={ready ? "Analyze the sample" : "Add a document first"}
                                style={{ minHeight: 42, padding: "0 20px", borderRadius: 12, border: "none", background: "linear-gradient(135deg, #1f8a5b, #0f7f73)", color: "#fff", fontSize: 14.5, fontWeight: 700, cursor: ready ? "pointer" : "not-allowed", opacity: ready ? 1 : 0.5, display: "flex", alignItems: "center", gap: 10, fontFamily: ANALYZER_FONT }}>
                                <DIcon d={<><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></>} s={16} /> Analyze Document
                            </button>
                        </div>
                    </section>

                    <div style={{ textAlign: "center", fontSize: 12, color: t.textMuted }}>Attorney.AI may make mistakes, so review all responses.</div>
                </div>
            </main>
        </div>
    );
}

export default function DocsAnalyzer({ onBack, userName }) {
    const t = useT();
    const toast = useToast();
    const L = splitLayout(useIsMobile());
    const fileRef = useRef(null);
    const timers = useRef([]);
    const [stage, setStage] = useState("empty");   // empty | ready | analyzing | done (dashboard)
    const [sample, setSample] = useState(SAMPLES[0][0]);
    const [side, setSide] = useState("Tenant");
    const [depth, setDepth] = useState("medium");
    const [focus, setFocus] = useState({ risks: true, missing: true, money: true, law: false, summary: false });
    const [step, setStep] = useState(0);
    const [sel, setSel] = useState(null);
    const [tab, setTab] = useState("risks");
    const [focusText, setFocusText] = useState("");

    useEffect(() => () => timers.current.forEach(clearTimeout), []);
    const notYet = what => () => toast.show(`${what} isn't connected yet — coming soon.`, "warn", 3000);
    const reset = () => { timers.current.forEach(clearTimeout); setStage("empty"); setStep(0); setSel(null); };
    // Only the rent agreement has sample findings. The other two would show
    // that lease's risks under another document's name.
    const pickSample = name => {
        if (name !== SAMPLES[0][0]) {
            toast.show(`Only the “${SAMPLES[0][0]}” sample is available in this preview.`, "warn", 3500);
            return;
        }
        setSample(name); setStage("ready");
    };
    const notRead = () => toast.show("The analyzer isn't connected yet, so your file was not read. Try the sample to see how it will work.", "warn", 5000);
    const onFile = e => {
        // The user's own file is not analysed: there is nothing to analyse it with.
        if (e.target.files?.length) toast.show("The analyzer isn't connected yet, so your file was not read. Try a sample to see how it will work.", "warn", 5000);
        e.target.value = "";
    };
    const analyze = () => {
        timers.current.forEach(clearTimeout);
        setStage("analyzing"); setStep(0); setSel(null); setTab("risks");
        timers.current = [1, 2, 3, 4, 5, 6].map(n => setTimeout(() => {
            setStep(n);
            if (n === 6) setStage("done");
        }, n * 850));
    };

    if (stage === "empty" || stage === "ready") {
        return (
            <>
                <input ref={fileRef} type="file" accept=".pdf,.doc,.docx,image/*" onChange={onFile} style={{ display: "none" }} />
                <UploadScreen userName={userName} stage={stage} sample={sample}
                    side={side} onSide={setSide} depth={depth} onDepth={setDepth}
                    focusText={focusText} onFocusText={setFocusText}
                    onPickFile={() => fileRef.current?.click()}
                    onDropFiles={files => { if (files?.length) notRead(); }}
                    onPickSample={() => pickSample(SAMPLES[0][0])}
                    onClearSample={reset}
                    onAnalyze={analyze}
                    onOpenSample={() => { setSample(SAMPLES[0][0]); setStep(6); setStage("done"); }}
                    onNewReview={reset} />
            </>
        );
    }
    if (stage === "done") {
        return <AnalysisDashboard sample={sample} side={side} depth={depth}
            onDepth={k => { setDepth(k); analyze(); }}
            onBack={reset} onReanalyze={analyze} />;
    }

    const analyzing = stage === "analyzing" || stage === "done";
    const found = RISKS.filter(r => analyzing && step >= r.at);
    const reading = stage === "analyzing" ? READING[step] : 0;
    const segBtn = on => ({ flex: 1, minHeight: 40, borderRadius: 10, border: `1px solid ${on ? t.primary : t.border}`, background: on ? t.primaryGlow2 : t.card, color: t.text, fontSize: 13.5, fontWeight: 600, cursor: "pointer", fontFamily: ANALYZER_FONT });
    const panelTitle = stage === "empty" ? "What should I look for?" : stage === "ready" ? "Ready when you are" : stage === "analyzing" ? "Reading your document…" : "Here is what I found";
    const panelSub = stage === "empty" ? "Sensible defaults are set — change anything."
        : stage === "ready" ? "Sample loaded · 4 pages · text found"
        : `As the ${side.toLowerCase()} · ${depth === "deep" ? "deep review" : depth === "medium" ? "medium review" : "quick scan"}`;

    return (
        <div data-lenis-prevent style={{ ...L.root, fontFamily: ANALYZER_FONT }}>
            <ScreenHeader onBack={onBack} title="Document analyzer"
                actions={<>
                    {stage === "ready" && <Btn onClick={reset} style={{ minHeight: 38 }}>Replace file</Btn>}
                </>}>
                {stage !== "empty" && <span style={{ fontSize: 13, color: t.textMuted }}>· {sample} (sample)</span>}
                <PreviewBadge what="The analyzer" />
            </ScreenHeader>
            <input ref={fileRef} type="file" accept=".pdf,.doc,.docx,image/*" onChange={onFile} style={{ display: "none" }} />

            <div style={L.row}>
                <section data-lenis-prevent style={{ ...L.col("1 1 460px"), overflowY: "auto", background: t.bg, display: "flex", flexDirection: "column" }}>
                    {stage === "empty" ? (
                        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 18, padding: "24px clamp(14px, 3vw, 28px)" }}>
                            {/* The dashboard only exists after an analysis, and only
                                the sample can be analysed — so offer it up front
                                instead of behind a sample card and a second button. */}
                            <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", padding: "14px 18px", borderRadius: 14, background: t.primaryGlow2, border: `1px solid ${t.primary}55` }}>
                                <div style={{ flex: 1, minWidth: 220 }}>
                                    <div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>See what an analysis looks like</div>
                                    <div style={{ fontSize: 13, color: t.textMuted }}>Open the full dashboard for the sample shop rent agreement — risks, obligations, compliance and more.</div>
                                </div>
                                <Btn kind="primary" onClick={() => { setSample(SAMPLES[0][0]); setStep(6); setStage("done"); }}>See a sample analysis →</Btn>
                            </div>
                            <button type="button" onClick={() => fileRef.current?.click()}
                                style={{ flex: 1, minHeight: 300, border: `2px dashed ${t.border}`, borderRadius: 22, background: t.surface, color: t.text, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 40, flexWrap: "wrap", padding: 30, fontFamily: ANALYZER_FONT }}>
                                <div aria-hidden="true" style={{ position: "relative", width: 170, height: 210, flexShrink: 0 }}>
                                    <div style={{ position: "absolute", left: 22, top: 14, width: 140, height: 190, borderRadius: 10, background: t.card, transform: "rotate(6deg)" }} />
                                    <div style={{ position: "absolute", left: 6, top: 4, width: 140, height: 190, borderRadius: 10, background: "#f4f7f7", boxShadow: "0 10px 30px rgba(0,0,0,.35)", padding: "18px 16px", boxSizing: "border-box", display: "flex", flexDirection: "column", gap: 9 }}>
                                        {[["70%", "#c9d4d6"], ["100%", "#dde5e6"], ["92%", "#fbd3d3"], ["100%", "#dde5e6"], ["80%", "#fbe6b4"], ["100%", "#dde5e6"], ["88%", "#dde5e6"], ["60%", "#bfe9e3"]].map(([w, c], i) => (
                                            <span key={i} style={{ height: i ? 6 : 8, width: w, borderRadius: 3, background: c, alignSelf: i ? "auto" : "center" }} />
                                        ))}
                                    </div>
                                </div>
                                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 10, textAlign: "left", maxWidth: 380 }}>
                                    <div style={{ fontFamily: ANALYZER_FONT, fontSize: 28, fontWeight: 600, lineHeight: 1.2 }}>Drop a document.<br />I'll read it with you.</div>
                                    <div style={{ fontSize: 14, color: t.textMuted, lineHeight: 1.6 }}>You'll see each clause light up as I check it — risks for your side, what's missing, and the law behind it.</div>
                                    <span style={{ marginTop: 6, display: "inline-flex", alignItems: "center", minHeight: 44, padding: "0 18px", borderRadius: 11, background: t.primary, color: onPrimary(t), fontWeight: 600, fontSize: 14 }}>Select file</span>
                                    <span style={{ fontSize: 12.5, color: t.textMuted }}>PDF · DOCX · DOC · photo or scan · max 50 MB</span>
                                </div>
                            </button>
                            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                                <Label>No document handy? Try one</Label>
                                <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                                    {SAMPLES.map(([name, sub]) => (
                                        <button key={name} type="button" onClick={() => pickSample(name)}
                                            style={{ flex: "1 1 180px", display: "flex", flexDirection: "column", gap: 6, textAlign: "left", padding: 14, borderRadius: 14, background: t.card, border: `1px solid ${t.border}`, color: t.text, cursor: "pointer", fontFamily: ANALYZER_FONT }}>
                                            <span style={{ fontSize: 14, fontWeight: 600 }}>{name}</span>
                                            <span style={{ fontSize: 12.5, color: t.textMuted }}>{sub}</span>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div style={{ display: "flex", justifyContent: "center", padding: "22px 12px" }}>
                            <Paper title="TENANCY AGREEMENT" width={600} style={{ fontSize: 14, lineHeight: 1.7 }}>
                                {CLAUSES.map(([id, text]) => {
                                    const r = found.find(x => x.id === id);
                                    const c = r ? SEVERITY[r.sev] : null;
                                    const isReading = reading === id;
                                    return (
                                        <button key={id} type="button" onClick={() => { if (r) { setSel(id); setTab("risks"); } }}
                                            style={{ display: "block", width: "100%", textAlign: "left", font: "inherit", color: "inherit", border: "none", borderRadius: 6, padding: "5px 8px", margin: "0 -8px 6px", cursor: r ? "pointer" : "default", background: isReading ? "#e6f4ff" : c ? c.paper : "transparent", outline: isReading ? "2px solid #5aa9e6" : sel === id && c ? `2px solid ${c.line}` : "none" }}>
                                            {r && <span style={{ fontFamily: ANALYZER_FONT, fontSize: 10.5, fontWeight: 700, padding: "1px 6px", borderRadius: 4, marginRight: 6, background: c.bg, color: c.fg }}>{r.sev.toUpperCase()}</span>}
                                            {text}
                                        </button>
                                    );
                                })}
                            </Paper>
                        </div>
                    )}
                </section>

                <aside style={{ ...L.col("0 1 440px"), borderLeft: `1px solid ${t.border}`, background: t.surface, display: "flex", flexDirection: "column", minHeight: 0 }}>
                    <div style={{ padding: "18px 20px 14px", borderBottom: `1px solid ${t.border}`, display: "flex", alignItems: "center", gap: 12 }}>
                        <div style={{ width: 38, height: 38, borderRadius: 11, background: t.primaryGlow2, color: t.primary, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>{Icon.spark}</div>
                        <div><div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>{panelTitle}</div><div style={{ fontSize: 12.5, color: t.textMuted }}>{panelSub}</div></div>
                    </div>

                    {!analyzing ? (
                        <>
                            <div data-lenis-prevent style={{ flex: 1, overflowY: "auto", padding: "18px 20px", display: "flex", flexDirection: "column", gap: 18 }}>
                                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                                    <Label>Your side</Label>
                                    <div style={{ display: "flex", gap: 8 }}>{["Tenant", "Landlord", "Neutral"].map(x => <button key={x} type="button" aria-pressed={side === x} onClick={() => setSide(x)} style={segBtn(side === x)}>{x}</button>)}</div>
                                    <div style={{ fontSize: 12.5, color: t.textMuted }}>Risks are judged for this party.</div>
                                </div>
                                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                                    <Label>Look for</Label>
                                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                        {[["risks", "Risks for me"], ["missing", "Missing clauses"], ["money", "Money & deadlines"], ["law", "Law compliance"], ["summary", "Plain summary"]].map(([k, name]) => (
                                            <Chip key={k} active={focus[k]} onClick={() => setFocus(f => ({ ...f, [k]: !f[k] }))}>{focus[k] ? "✓" : "+"} {name}</Chip>
                                        ))}
                                    </div>
                                </div>
                                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                                    <Label>Depth</Label>
                                    <div style={{ display: "flex", gap: 8 }}>{[["quick", "Quick scan"], ["deep", "Deep review"]].map(([k, name]) => <button key={k} type="button" aria-pressed={depth === k} onClick={() => setDepth(k)} style={segBtn(depth === k)}>{name}</button>)}</div>
                                    <div style={{ fontSize: 12.5, color: t.textMuted }}>{depth === "deep" ? "Every clause, missing clauses and dates · about a minute." : "Summary and the top 3 risks · about 20 seconds."}</div>
                                </div>
                                <Card style={{ marginTop: "auto", padding: "12px 14px", fontSize: 12.5, color: t.textMuted, lineHeight: 1.55 }}>
                                    Private to you, never used for training. Guidance, not legal advice — send the result to a lawyer in one click.
                                </Card>
                            </div>
                            <div style={{ padding: "14px 20px", borderTop: `1px solid ${t.border}` }}>
                                {stage === "ready"
                                    ? <Btn kind="primary" onClick={analyze} style={{ width: "100%" }}>Analyze as {side}</Btn>
                                    : <Btn disabled style={{ width: "100%" }}>Add a document to start</Btn>}
                            </div>
                        </>
                    ) : (
                        <>
                            <div style={{ padding: "14px 20px 0", display: "flex", flexDirection: "column", gap: 10 }}>
                                <div style={{ height: 6, borderRadius: 3, background: t.border, overflow: "hidden" }}><div style={{ height: "100%", width: `${Math.round(Math.min(step, 6) / 6 * 100)}%`, background: t.primary, transition: "width .4s" }} /></div>
                                <div aria-live="polite" style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13 }}>
                                    <span style={{ flex: 1, color: t.text }}>{stage === "done" ? `Done · ${RISKS.length} risks, ${MISSING.length} missing clauses` : STATUS[step]}</span>
                                    <span style={{ color: SEVERITY.high.fg }}>{found.filter(r => r.sev === "high").length} high</span>
                                    <span style={{ color: SEVERITY.medium.fg }}>{found.filter(r => r.sev === "medium").length} medium</span>
                                </div>
                                <Tabs t={t} value={tab} onChange={setTab} tabs={[["risks", "Risks"], ["missing", `Missing · ${MISSING.length}`], ["summary", "Summary"], ["terms", "Key terms"]]} />
                            </div>
                            <div data-lenis-prevent style={{ flex: 1, overflowY: "auto", padding: "12px 20px", display: "flex", flexDirection: "column", gap: 10 }}>
                                {tab === "risks" && <>
                                    {found.map((r, i) => <RiskCard key={r.id} t={t} r={r} onPick={() => setSel(sel === r.id ? null : r.id)}
                                        open={sel === r.id || (sel === null && stage === "analyzing" && i === found.length - 1)} />)}
                                    {stage === "analyzing" && <div style={{ padding: "12px 14px", borderRadius: 12, border: `1px dashed ${t.border}`, fontSize: 13, color: t.textMuted }}>Reading the next clause…</div>}
                                </>}
                                {tab === "missing" && MISSING.map(([title, sub]) => <Card key={title} style={{ padding: "12px 14px" }}><div style={{ fontSize: 14, fontWeight: 600, color: t.text }}>{title}</div><div style={{ fontSize: 13, color: t.textMuted, marginTop: 4 }}>{sub}</div></Card>)}
                                {tab === "summary" && <div style={{ fontSize: 14, lineHeight: 1.65, color: t.text }}>{SUMMARY}</div>}
                                {tab === "terms" && (
                                    <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
                                        {TERMS.map(([k, v]) => <Card key={k} style={{ padding: "10px 12px" }}><div style={{ fontSize: 12, color: t.textMuted }}>{k}</div><div style={{ fontSize: 14, fontWeight: 600, marginTop: 2, color: t.text }}>{v}</div></Card>)}
                                    </div>
                                )}
                            </div>
                            <div style={{ padding: "12px 20px 14px", borderTop: `1px solid ${t.border}`, display: "flex", flexDirection: "column", gap: 10 }}>
                                <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "6px 6px 6px 12px", borderRadius: 12, background: t.inputBg, border: `1px solid ${t.border}` }}>
                                    <label htmlFor="askdoc" style={{ position: "absolute", left: -9999 }}>Ask about this document</label>
                                    <input id="askdoc" placeholder="Ask about this document… e.g. can I leave early?" style={{ flex: 1, background: "transparent", border: "none", color: t.text, fontFamily: ANALYZER_FONT, fontSize: 13.5, outline: "none", minHeight: 32 }} />
                                    <button type="button" aria-label="Ask" onClick={notYet("Asking about a document")} style={{ width: 36, height: 36, borderRadius: 9, border: "none", background: t.primaryGlow2, color: t.primary, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>{Icon.arrow}</button>
                                </div>
                                <div style={{ display: "flex", gap: 8 }}>
                                    <Btn kind="primary" onClick={notYet("Fixing in a new draft")} style={{ flex: 1 }}>Fix in a new draft</Btn>
                                    <Btn onClick={notYet("Sending to a lawyer from the analyzer")}>Send to lawyer</Btn>
                                </div>
                            </div>
                        </>
                    )}
                </aside>
            </div>
        </div>
    );
}
