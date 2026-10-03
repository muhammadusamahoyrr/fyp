'use client';
/* AnalyzerWorkspace — the Document Analyzer, a LAWYER's tool (2026-10-03).
 *
 * Mounted only on the lawyer dashboard (components/lawyer/DocAnalyzerPage.jsx);
 * the client dashboard has no analyzer and its old URL redirects. The
 * server refuses every analyzer endpoint to a client account.
 *
 * Document analyzer — a FICTIONAL DEMONSTRATION until the backend exists.
 *
 * There is no analysis endpoint (see DOC_ANALYZER_PLAN.md). So:
 *   - nothing offers to take the user's own file: upload says it is not
 *     available, and there is no file picker to choose one with;
 *   - the one sample (a shop tenancy) is fictional, and every view of its
 *     result carries a banner saying no uploaded document was analysed;
 *   - no line claims a legal source was checked, no check says a clause is
 *     absent (the real analyzer will only say "not located"), and no control
 *     pretends to do something that does not exist yet (Ask, Precedents, Fix,
 *     Send to lawyer, Resources, Add document).
 * documents_home_dom.test.mjs ("P-1: …") asserts each of these stays true.
 *
 * LIVE MODE. When the server offers the real analyzer (GET
 * /documents/analyses/attestation answers 200), `AnalyzerLive` is shown
 * instead -- it reads and maps a synthetic document and says it does not
 * review risks yet. Off (404), unavailable (503) or no answer: this
 * fictional demonstration, unchanged. */
import React, { useEffect, useRef, useState } from "react";
import { useT } from "@/components/client/theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import { useIsMobile } from "@/lib/i18n.jsx";
import { analyzerAttestation } from "@/lib/api.js";
import AnalyzerLive from "./AnalyzerLive.jsx";
import {
    Btn, Chip, Pill, Label, Card, Paper, PreviewBadge, ScreenHeader, Icon,
    SERIF, SEVERITY, onPrimary, splitLayout,
} from "@/components/client/documents/ui.jsx";

/* Shown wherever the sample names a legal source. The sample's law is not
 * checked against anything: our library holds none of these statutes yet. */
export const ILLUSTRATIVE = "Illustrative only — legal source not checked.";
export const FICTIONAL = "Fictional demonstration — no uploaded document was analysed.";
export const SAMPLE_NAME = "Shop rent agreement";

const RISKS = [
    { id: 6, at: 2, sev: "high", title: "Clause 6 · Eviction on 7 days’ notice", why: "The landlord can end the lease for any reason within a week — you could lose the shop and your fit-out.", fix: "Require a stated ground and at least 60 days’ notice; give the tenant the same right.", cite: ILLUSTRATIVE },
    { id: 9, at: 3, sev: "high", title: "Clause 9 · Deposit is non-refundable", why: "Three months’ rent (PKR 255,000) is lost even if you hand the shop back in good order.", fix: "Refund within 30 days of handover, less documented damage.", cite: ILLUSTRATIVE },
    { id: 4, at: 4, sev: "medium", title: "Clause 4 · Rent increase at any time", why: "Up to 20% whenever the landlord chooses, with no limit on how often.", fix: "One increase, on renewal only, capped at 10%.", cite: ILLUSTRATIVE },
    { id: 5, at: 5, sev: "medium", title: "Clause 5 · Structural repairs on you", why: "Roof, walls and foundations are normally the owner’s job.", fix: "Tenant does day-to-day repairs; landlord does structural ones.", cite: ILLUSTRATIVE },
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
// Illustrative checks for the fictional sample. The real analyzer reports
// "not located automatically", never a bare absence (DOC_ANALYZER_PLAN.md §4.5).
const SAMPLE_CHECKS = [
    ["Tenant's right to end the lease", "Not located in this fictional sample: only the landlord has a notice clause."],
    ["Registration with the Rent Registrar", "A reminder, not a finding: whether it was registered cannot be seen from the text."],
];
const TERMS = [
    ["Monthly rent", "PKR 85,000"], ["Due", "5th of each month"], ["Term", "11 months"],
    ["Starts", "1 Oct 2026"], ["Deposit", "PKR 255,000"], ["Landlord notice", "7 days"],
];
const SUMMARY = "An 11-month shop lease in Lahore at PKR 85,000 a month. It favours the landlord: eviction on 7 days' notice, a non-refundable deposit, open-ended rent increases and structural repairs on you.";
const READING = [0, 6, 6, 9, 4, 5, 0];
const STATUS = ["Starting…", "Reading the text", "Checking clause 6", "Checking clause 9", "Checking clause 4", "Checking clause 5", "Comparing with the illustrative checklist"];

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
                    <span style={{ display: "block", marginTop: 5, fontSize: 12, color: t.textMuted }}>{r.cite}</span>
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
 * Every figure here belongs to THE FICTIONAL SAMPLE (see the file header).
 * There is no Precedents tab: we hold no case law, and inventing case names
 * for a sample would put fake law on screen. No Ask tab either, until the
 * document itself can be searched (plan P5). */
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
    { title: "Registration with the Rent Registrar", status: "reminder", detail: "Whether the agreement was presented to the Rent Registrar cannot be seen from its text.", law: ILLUSTRATIVE },
    { title: "Tenant’s right to end the lease", status: "not_located", detail: "Only the landlord has a notice clause in this fictional sample.", law: ILLUSTRATIVE },
    { title: "Stamp duty", status: "check", detail: "Stamp paper would be checked here in a real review.", law: ILLUSTRATIVE },
    { title: "Signed before two witnesses", status: "present", detail: "Clause 11 records signature at Lahore before two witnesses.", law: null },
];
const COMPLIANCE_TONE = { not_located: ["high", "Not located"], reminder: ["medium", "Reminder"], check: ["medium", "Check"], present: ["low", "Found"] };

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

/* On every view of the sample and its result. Not dismissible: the result is
 * fictional for as long as it is on screen. */
export function FictionalBanner({ t, style }) {
    return (
        <div role="note" data-fictional-banner
            style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderRadius: 10, background: "rgba(242,184,75,0.14)", border: "1px solid rgba(242,184,75,0.55)", color: t.text, fontSize: 13.5, fontWeight: 600, fontFamily: ANALYZER_FONT, ...style }}>
            <span aria-hidden="true">⚠</span> {FICTIONAL}
        </div>
    );
}

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
    const isMobile = useIsMobile();
    const [tab, setTab] = useState("summary");
    const [hl, setHl] = useState(null);          // clause highlighted on the Document tab
    const light = t.mode !== "dark";
    const issueBox = light ? { background: "#fdf7e6", color: "#7a5200" } : { background: "rgba(242,184,75,0.12)", color: "#f7cf7d" };
    const recBox = light ? { background: "#e8f1fc", color: "#1d4f91" } : { background: "rgba(90,169,230,0.13)", color: "#b9dcf7" };
    const high = RISKS.filter(r => r.sev === "high").length;
    const notLocated = COMPLIANCE.filter(c => c.status === "not_located").length;

    const TABS = [
        ["summary", "Summary", DI.spark, null],
        ["clauses", "Key Clauses", DI.clause, KEY_CLAUSES.length],
        ["risks", "Risks", DI.risk, RISKS.length],
        ["obligations", "Obligations", DI.check, OBLIGATIONS.length],
        ["compliance", "Illustrative checks", DI.shield, COMPLIANCE.length],
        ["document", "Document", DI.doc, null],
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
                            <div style={{ fontSize: 12, color: t.textMuted, marginTop: 8 }}>{r.cite}</div>
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
            <SectionHead t={t} icon={DI.shield} tone="low" title="Illustrative checks" sub={`${notLocated} not located in this fictional sample · no playbook has been applied`} count={COMPLIANCE.length} />
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {COMPLIANCE.map(c => {
                    const [tone, label] = COMPLIANCE_TONE[c.status];
                    return (
                        <article key={c.title} style={{ ...card, display: "flex", gap: 12, alignItems: "flex-start" }}>
                            <div style={{ flex: 1 }}>
                                <h3 style={{ margin: 0, fontSize: 16.5, fontWeight: 600, color: t.text }}>{c.title}</h3>
                                <p style={{ margin: "6px 0 4px", fontSize: 14, color: t.textDim || t.text, lineHeight: 1.55 }}>{c.detail}</p>
                                {c.law && <div style={{ fontSize: 12, color: t.textMuted }}>{c.law}</div>}
                            </div>
                            <Pill tone={tone} style={{ fontSize: 11, letterSpacing: ".04em" }}>{label.toUpperCase()}</Pill>
                        </article>
                    );
                })}
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

    const stats = [
        ["Risks", RISKS.length, `${high} high/critical`, "high", DI.risk, "risks"],
        ["Obligations", OBLIGATIONS.length, `${OBLIGATIONS.length} with deadlines`, "info", DI.check, "obligations"],
        ["Key Clauses", KEY_CLAUSES.length, `${KEY_CLAUSES.length} with issues`, "medium", DI.clause, "clauses"],
        ["Checks", COMPLIANCE.length, `${notLocated} not located`, "low", DI.shield, "compliance"],
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
            <div style={{ padding: isMobile ? "0 14px 10px" : "0 22px 10px", background: t.surface }}><FictionalBanner t={t} /></div>

            {/* Action row */}
            <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", padding: isMobile ? "4px 14px 12px" : "6px 22px 14px", borderBottom: `1px solid ${t.border}`, background: t.surface }}>
                <button type="button" onClick={onBack}
                    style={{ display: "inline-flex", alignItems: "center", gap: 8, minHeight: 42, padding: "0 10px", borderRadius: 10, border: "none", background: "transparent", color: t.textMuted, fontSize: 18, fontWeight: 400, cursor: "pointer", fontFamily: ANALYZER_FONT }}>
                    <DIcon d={DI.back} s={16} /> Back to Document Analyzer
                </button>
                {/* Pushes Re-analyze to the right edge. */}
                <span aria-hidden="true" style={{ flex: 1 }} />
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
                            <DIcon d={DI.redo} s={17} /> Fictional sample · 1 document
                        </div>
                        {/* Whose analysis this is, kept out of the heading line but never dropped. */}
                        <div style={{ marginTop: 4, fontSize: 12.5, color: t.textMuted }}>{sample} (fictional sample) · as the {side}</div>
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
                                <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 14 }}>Fictional sample — governing law was not determined.</div>
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
                        </>
                    )}
                    {tab === "clauses" && clausesSection}
                    {tab === "risks" && risksSection}
                    {tab === "obligations" && obligationsSection}
                    {tab === "compliance" && complianceSection}
                    {tab === "document" && documentSection}
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
// The lines under the greeting describe what this screen actually offers:
// a fictional review. They used to promise insights "from your file".
export function greetingFor(date = new Date()) {
    const h = date.getHours();
    if (h < 5 || h >= 18) return { text: "Good Evening", sub: "Take a look at a fictional document review.", icon: "moon", night: true };
    if (h < 12) return { text: "Good Morning", sub: "Explore a fictional document review.", icon: "sun", night: false };
    return { text: "Good Afternoon", sub: "See how a document review will look.", icon: "cloud", night: false };
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

function UploadScreen({ userName, stage, sample, side, onSide, depth, onDepth,
    onDropAttempt, onPickSample, onClearSample, onAnalyze, onOpenSample, onNewReview }) {
    const t = useT();
    const isMobile = useIsMobile();
    const [historyOpen, setHistoryOpen] = useState(true);
    const [groupOpen, setGroupOpen] = useState(true);
    const [collapsed, setCollapsed] = useState(false);
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
                                    {SAMPLE_NAME} (fictional sample)
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
                    <FictionalBanner t={t} />

                    {/* Upload — not available yet, and says so. No file picker:
                        a control that accepts a file it cannot read invites the
                        user to hand over a real lease for nothing. */}
                    <section style={{ ...bigCard, display: "flex", gap: isMobile ? 16 : 24, flexDirection: isMobile ? "column" : "row", alignItems: "stretch" }}>
                        <div style={{ flex: isMobile ? "none" : "0 0 260px", display: "flex", flexDirection: "column", gap: 10 }}>
                            <span style={{ width: 42, height: 42, borderRadius: 11, background: "linear-gradient(135deg, #1f8a5b, #0f7f73)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center" }}><DIcon d={DI.spark} s={19} /></span>
                            <h2 style={{ margin: "4px 0 0", fontSize: 17, fontWeight: 700, color: t.text, lineHeight: 1.3 }}>Document review</h2>
                            <p style={{ margin: 0, fontSize: 13, color: t.textMuted, lineHeight: 1.55 }}>Reviewing your own documents is being built. Until then, a fictional sample shows how a review will look.</p>
                        </div>
                        {/* A file dropped here must not navigate the tab to it, so the
                            drop is swallowed -- and the user is told it was not read. */}
                        <div data-upload-unavailable
                            onDragOver={e => e.preventDefault()}
                            onDrop={e => { e.preventDefault(); onDropAttempt(); }}
                            style={{ flex: 1, minWidth: 0, minHeight: isMobile ? 180 : 220, borderRadius: 16, border: `1px solid ${t.border}`, background: "transparent", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10, padding: "20px 18px", textAlign: "center" }}>
                            {ready ? (
                                <>
                                    <span style={{ width: 44, height: 54, borderRadius: 8, background: "#fdecec", color: "#b3261e", fontSize: 12, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center" }}>PDF</span>
                                    <div style={{ fontSize: 15.5, fontWeight: 700, color: t.text }}>{sample} <span style={{ fontSize: 13, fontWeight: 500, color: t.textMuted }}>(fictional sample)</span></div>
                                    <div style={{ fontSize: 13.5, color: t.textMuted }}>Fictional text · ready to open</div>
                                    <Btn onClick={onClearSample} style={{ minHeight: 38 }}>Remove</Btn>
                                </>
                            ) : (
                                <>
                                    <span style={{ color: t.textMuted, opacity: 0.7 }}><DIcon d={DI.upload} s={26} /></span>
                                    <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Real document upload is not available yet.</div>
                                    <div style={{ fontSize: 13, color: t.textMuted, maxWidth: 420, lineHeight: 1.55 }}>Nothing you have is read or stored here.</div>
                                    <button type="button" onClick={onPickSample}
                                        style={{ minHeight: 38, padding: "0 20px", borderRadius: 10, border: `1px solid ${t.primary}`, background: "transparent", color: t.primary, fontSize: 14, fontWeight: 700, cursor: "pointer", fontFamily: ANALYZER_FONT }}>
                                        Use the fictional sample rent agreement
                                    </button>
                                </>
                            )}
                        </div>
                    </section>

                    {/* Focus */}
                    <section style={{ ...bigCard, display: "flex", flexDirection: "column", gap: 18 }}>
                        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                            <span style={{ color: t.primary, alignSelf: "center" }}><DIcon d={DI.spark} s={19} /></span>
                            <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: t.text }}>Open the sample review</h2>
                            <span style={{ fontSize: 13, color: t.textMuted }}>(fictional)</span>
                        </div>
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
                                title={ready ? "Open the fictional sample" : "Choose the fictional sample first"}
                                style={{ minHeight: 42, padding: "0 20px", borderRadius: 12, border: "none", background: "linear-gradient(135deg, #1f8a5b, #0f7f73)", color: "#fff", fontSize: 14.5, fontWeight: 700, cursor: ready ? "pointer" : "not-allowed", opacity: ready ? 1 : 0.5, display: "flex", alignItems: "center", gap: 10, fontFamily: ANALYZER_FONT }}>
                                <DIcon d={<><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></>} s={16} /> Open fictional analysis
                            </button>
                        </div>
                    </section>

                    <div style={{ textAlign: "center", fontSize: 12, color: t.textMuted }}>Attorney.AI may make mistakes, so review all responses.</div>
                </div>
            </main>
        </div>
    );
}

function FictionalAnalyzer({ onBack, userName }) {
    const t = useT();
    const toast = useToast();
    const L = splitLayout(useIsMobile());
    const timers = useRef([]);
    // empty | ready | analyzing | done (dashboard). Only the fictional sample
    // ever reaches "ready": there is no way to hand over a real file.
    const [stage, setStage] = useState("empty");
    const sample = SAMPLE_NAME;
    const [side, setSide] = useState("Tenant");
    const [depth, setDepth] = useState("medium");
    const [step, setStep] = useState(0);
    const [sel, setSel] = useState(null);
    const [tab, setTab] = useState("risks");

    useEffect(() => () => timers.current.forEach(clearTimeout), []);
    const reset = () => { timers.current.forEach(clearTimeout); setStage("empty"); setStep(0); setSel(null); };
    const notRead = () => toast.show("Real document upload is not available yet, so your file was not read.", "warn", 5000);
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
            <UploadScreen userName={userName} stage={stage} sample={sample}
                side={side} onSide={setSide} depth={depth} onDepth={setDepth}
                onDropAttempt={notRead}
                onPickSample={() => setStage("ready")}
                onClearSample={reset}
                onAnalyze={analyze}
                onOpenSample={() => { setStep(6); setStage("done"); }}
                onNewReview={reset} />
        );
    }
    if (stage === "done") {
        return <AnalysisDashboard sample={sample} side={side} depth={depth}
            onDepth={k => { setDepth(k); analyze(); }}
            onBack={reset} onReanalyze={analyze} />;
    }

    // Only "analyzing" reaches here: the stages above return early.
    const found = RISKS.filter(r => step >= r.at);
    const reading = READING[step];
    const panelSub = `As the ${side.toLowerCase()} · ${depth === "deep" ? "deep review" : depth === "medium" ? "medium review" : "quick scan"}`;

    return (
        <div data-lenis-prevent style={{ ...L.root, fontFamily: ANALYZER_FONT }}>
            <ScreenHeader onBack={onBack} title="Document analyzer">
                <span style={{ fontSize: 13, color: t.textMuted }}>· {sample} (fictional sample)</span>
                <PreviewBadge what="The analyzer" />
            </ScreenHeader>
            <div style={{ padding: "10px clamp(14px, 3vw, 28px) 0" }}><FictionalBanner t={t} /></div>

            <div style={L.row}>
                <section data-lenis-prevent style={{ ...L.col("1 1 460px"), overflowY: "auto", background: t.bg, display: "flex", flexDirection: "column" }}>
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
                </section>

                <aside style={{ ...L.col("0 1 440px"), borderLeft: `1px solid ${t.border}`, background: t.surface, display: "flex", flexDirection: "column", minHeight: 0 }}>
                    <div style={{ padding: "18px 20px 14px", borderBottom: `1px solid ${t.border}`, display: "flex", alignItems: "center", gap: 12 }}>
                        <div style={{ width: 38, height: 38, borderRadius: 11, background: t.primaryGlow2, color: t.primary, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>{Icon.spark}</div>
                        <div><div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>Reading the fictional sample…</div><div style={{ fontSize: 12.5, color: t.textMuted }}>{panelSub}</div></div>
                    </div>

                    <div style={{ padding: "14px 20px 0", display: "flex", flexDirection: "column", gap: 10 }}>
                        <div style={{ height: 6, borderRadius: 3, background: t.border, overflow: "hidden" }}><div style={{ height: "100%", width: `${Math.round(Math.min(step, 6) / 6 * 100)}%`, background: t.primary, transition: "width .4s" }} /></div>
                        <div aria-live="polite" style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13 }}>
                            <span style={{ flex: 1, color: t.text }}>{STATUS[step]}</span>
                            <span style={{ color: SEVERITY.high.fg }}>{found.filter(r => r.sev === "high").length} high</span>
                            <span style={{ color: SEVERITY.medium.fg }}>{found.filter(r => r.sev === "medium").length} medium</span>
                        </div>
                        <Tabs t={t} value={tab} onChange={setTab} tabs={[["risks", "Risks"], ["checks", `Illustrative checks · ${SAMPLE_CHECKS.length}`], ["summary", "Summary"], ["terms", "Key terms"]]} />
                    </div>
                    <div data-lenis-prevent style={{ flex: 1, overflowY: "auto", padding: "12px 20px", display: "flex", flexDirection: "column", gap: 10 }}>
                        {tab === "risks" && <>
                            {found.map((r, i) => <RiskCard key={r.id} t={t} r={r} onPick={() => setSel(sel === r.id ? null : r.id)}
                                open={sel === r.id || (sel === null && i === found.length - 1)} />)}
                            <div style={{ padding: "12px 14px", borderRadius: 12, border: `1px dashed ${t.border}`, fontSize: 13, color: t.textMuted }}>Reading the next clause…</div>
                        </>}
                        {tab === "checks" && SAMPLE_CHECKS.map(([title, sub]) => <Card key={title} style={{ padding: "12px 14px" }}><div style={{ fontSize: 14, fontWeight: 600, color: t.text }}>{title}</div><div style={{ fontSize: 13, color: t.textMuted, marginTop: 4 }}>{sub}</div></Card>)}
                        {tab === "summary" && <div style={{ fontSize: 14, lineHeight: 1.65, color: t.text }}>{SUMMARY}</div>}
                        {tab === "terms" && (
                            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
                                {TERMS.map(([k, v]) => <Card key={k} style={{ padding: "10px 12px" }}><div style={{ fontSize: 12, color: t.textMuted }}>{k}</div><div style={{ fontSize: 14, fontWeight: 600, marginTop: 2, color: t.text }}>{v}</div></Card>)}
                            </div>
                        )}
                    </div>
                </aside>
            </div>
        </div>
    );
}


/* Live when the server says so; the fictional demonstration otherwise. */
export default function AnalyzerWorkspace(props) {
    const [live, setLive] = useState(undefined);      // undefined = still asking
    const [showDemo, setShowDemo] = useState(false);
    useEffect(() => {
        let mounted = true;
        Promise.resolve(analyzerAttestation())
            .then(r => { if (mounted) setLive(r?.data?.version && r?.data?.text ? r.data : null); })
            .catch(() => { if (mounted) setLive(null); });
        return () => { mounted = false; };
    }, []);
    if (live === undefined) return null;
    if (live && !showDemo) return <AnalyzerLive attestation={live} onShowDemo={() => setShowDemo(true)} />;
    return <FictionalAnalyzer {...props} />;
}
