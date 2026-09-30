'use client';
/* Documents home — the prompt card, the template catalogue with its Preview
 * and Customize overlays, and whatever "continue" list the parent passes in.
 *
 * PRESENTATION ONLY. What "use a template" or "plan a draft" does stays in
 * ModDocuments; this component is handed the catalogue and callbacks. The
 * catalogue is the server's (`GET /documents/templates`); nothing here invents
 * an entry, a risk level or a clause.
 *
 * The preview shows what the template ASKS FOR and what the law expects of it.
 * It does not show wording: the wording lives in the PDF builders, and a page
 * of made-up clauses presented as "the template" would be a fabrication.
 *
 * The requirements list is `GET /documents/requirements/{type}` — what the
 * Code requires, for the user to CONFIRM. The server marks every item
 * `to_confirm`, and so does this screen. It is never shown as a pass.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useT } from "./theme.js";
import { humanise } from "@/lib/fieldReview.js";
import { pleadingRequirements } from "@/lib/api.js";
import TemplateEditor from "./documents/TemplateEditor.jsx";
import {
    Btn, IconBtn, Chip, Pill, Label, Card, Paper, Icon, ModalPortal, BACKDROP,
    SERIF, TOKEN_STYLE, VALUE_STYLE, fieldStyle, onPrimary,
} from "./documents/ui.jsx";

/* What each drafting mode means to the person choosing, in their words. */
const MODE_VIEW = {
    ai: { pill: "AI reads your case", tone: "info", explain: "Link a case and the AI fills the details from it. You check every value before anything is drafted." },
    manual: { pill: "You fill the details", tone: "muted", explain: "You enter the details yourself in a short form. Nothing is guessed for you." },
    dedicated: { pill: "Calculator", tone: "medium", explain: "Built by a dedicated calculator, because it needs exact figures and tables rather than free text." },
};

const COURT_CATEGORIES = ["Civil", "Criminal", "Court", "Family"];

function tileFor(spec) {
    if (/notice/i.test(spec.label || "")) return { icon: Icon.mail, bg: "#1d3f5a", fg: "#9fd0f5" };
    if (COURT_CATEGORIES.includes(spec.category)) return { icon: Icon.court, bg: "#2f2a4a", fg: "#c9bff5" };
    return { icon: Icon.contract, bg: "#1f4a4f", fg: "#3fd6c6" };
}

const TRY_PROMPTS = [
    "Notice to a tenant for unpaid rent",
    "Employment contract for a sales manager",
    "Affidavit for a lost CNIC",
];

export function templateMatches(spec, query) {
    const q = (query || "").trim().toLowerCase();
    if (!q) return true;
    return [spec.label, spec.description, spec.category]
        .some(v => (v || "").toLowerCase().includes(q));
}

function textFields(spec) {
    return (spec.fields || []).filter(f => !(spec.structured_fields || []).includes(f));
}

function useRequirements(templateType) {
    const [state, setState] = useState({ loading: true, report: null });
    useEffect(() => {
        let live = true;
        setState({ loading: true, report: null });
        pleadingRequirements(templateType).then(res => {
            if (live) setState({ loading: false, report: res?.error ? null : (res?.data || null) });
        });
        return () => { live = false; };
    }, [templateType]);
    return state;
}

function RequirementsList({ t, templateType }) {
    const { loading, report } = useRequirements(templateType);
    if (loading) return <div style={{ fontSize: 12.5, color: t.textMuted }}>Checking what this document must contain…</div>;
    const items = report?.covered ? (report.items || []) : [];
    if (!items.length) return null;
    return (
        <div data-requirements-preview>
            <Label>What the law expects in it</Label>
            <ul style={{ margin: "8px 0 0", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
                {items.map(item => (
                    <li key={item.clause + item.requirement} style={{ display: "flex", gap: 8, fontSize: 12.5, color: t.text, lineHeight: 1.5 }}>
                        <span aria-hidden="true" style={{ color: t.textMuted }}>○</span>
                        <span>{item.requirement}{item.clause ? <span style={{ color: t.textMuted }}> — {item.clause}</span> : null}</span>
                    </li>
                ))}
            </ul>
            <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 8 }}>
                A checklist to confirm against your draft — not checked automatically.
            </div>
        </div>
    );
}

/* Escape closes, focus starts on the close button. */
function useDialog(onClose) {
    const closeRef = useRef(null);
    useEffect(() => {
        closeRef.current?.focus();
        const onKey = e => { if (e.key === "Escape") onClose(); };
        document.addEventListener("keydown", onKey);
        return () => document.removeEventListener("keydown", onKey);
    }, [onClose]);
    return closeRef;
}

function Overlay({ children, onClose, pad = 26 }) {
    return (
        // data-lenis-prevent: the app's smooth scroll takes wheel events for the
        // page, so without it this overlay could not be scrolled with a mouse.
        <ModalPortal>
            <div data-lenis-prevent onClick={onClose} style={{ ...BACKDROP, display: "flex", alignItems: "flex-start", justifyContent: "center", padding: `clamp(8px, 3vw, ${pad}px)`, overflowY: "auto" }}>
                {children}
            </div>
        </ModalPortal>
    );
}

/* The paper for a template: its purpose and the details it will carry. */
function TemplatePaper({ spec, values = {} }) {
    const fields = textFields(spec);
    return (
        <Paper title={(spec.label || "").toUpperCase()} width={580}>
            <p style={{ margin: "0 0 14px" }}>{spec.description}</p>
            {fields.length > 0 && (
                <>
                    <p style={{ margin: "0 0 8px", fontFamily: "'Inter', sans-serif", fontSize: 12, fontWeight: 700, letterSpacing: ".06em", color: "#5b6b6f" }}>
                        DETAILS THIS DOCUMENT CARRIES
                    </p>
                    {fields.map(f => {
                        const v = (values[f] || "").trim();
                        return (
                            <p key={f} style={{ margin: "0 0 8px" }}>
                                <b>{humanise(f)}: </b>
                                {v ? <span style={VALUE_STYLE}>{v}</span> : <span style={TOKEN_STYLE}>{humanise(f)}</span>}
                            </p>
                        );
                    })}
                </>
            )}
        </Paper>
    );
}

function PreviewDialog({ t, list, index, onIndex, onClose, onUse, onCustomize, dedicatedHref }) {
    const closeRef = useDialog(onClose);
    const spec = list[index];
    const mode = MODE_VIEW[spec.drafting_mode] || MODE_VIEW.manual;
    const fields = textFields(spec);
    const go = d => onIndex((index + d + list.length) % list.length);
    const dedicated = spec.drafting_mode === "dedicated";
    return (
        <Overlay onClose={onClose} pad={60}>
            <div role="dialog" aria-modal="true" aria-label="Template preview" onClick={e => e.stopPropagation()}
                style={{ width: "min(1120px, 100%)", background: t.surface, border: `1px solid ${t.border}`, borderRadius: 20, display: "flex", flexDirection: "column", overflow: "hidden", boxShadow: "0 30px 80px rgba(0,0,0,.5)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", padding: "14px 18px", borderBottom: `1px solid ${t.border}` }}>
                    <IconBtn label="Previous template" onClick={() => go(-1)}>‹</IconBtn>
                    <IconBtn label="Next template" onClick={() => go(1)}>›</IconBtn>
                    <div style={{ fontFamily: SERIF, fontSize: 21, fontWeight: 600, color: t.text, marginLeft: 4 }}>{spec.label}</div>
                    <Pill tone="info">{spec.category}</Pill>
                    <Pill tone={mode.tone}>{mode.pill}</Pill>
                    <div style={{ flex: 1 }} />
                    <span style={{ fontSize: 12.5, color: t.textMuted }}>{index + 1} of {list.length}</span>
                    <IconBtn label="Close preview" onClick={onClose} ref={closeRef}>×</IconBtn>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", minHeight: 0 }}>
                    <div style={{ flex: "1 1 460px", display: "flex", justifyContent: "center", padding: 24, background: t.bg }}>
                        <TemplatePaper spec={spec} />
                    </div>
                    <div style={{ flex: "0 1 360px", borderLeft: `1px solid ${t.border}`, padding: 20, boxSizing: "border-box", display: "flex", flexDirection: "column", gap: 18 }}>
                        <div><Label>Use this when</Label><div style={{ fontSize: 14, lineHeight: 1.6, marginTop: 6, color: t.text }}>{spec.description}</div></div>
                        {!dedicated && fields.length > 0 && (
                            <div>
                                <Label>You'll fill {fields.length} details</Label>
                                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                                    {fields.map(f => <Pill key={f} tone="medium" style={{ fontSize: 12.5, fontWeight: 500 }}>{humanise(f)}</Pill>)}
                                </div>
                            </div>
                        )}
                        <RequirementsList t={t} templateType={spec.template_type} />
                        <div style={{ padding: "12px 14px", borderRadius: 12, background: t.card, border: `1px solid ${t.border}`, fontSize: 13, lineHeight: 1.55, color: t.text }}>{mode.explain}</div>
                        <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 10 }}>
                            {dedicated ? (
                                <Btn kind="primary" href={dedicatedHref(spec)}>Open dedicated calculator</Btn>
                            ) : (
                                <>
                                    <Btn kind="primary" onClick={() => onUse(spec)}>Use this template</Btn>
                                    <Btn onClick={() => onCustomize(spec)}>Edit wording first</Btn>
                                </>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </Overlay>
    );
}

const POPULAR_DRAFTS = [
    ["Non-disclosure agreement", "Protect confidential information between parties.", "Draft a non-disclosure agreement", Icon.contract],
    ["Employment agreement", "Set clear terms for employees or contractors.", "Draft an employment agreement", Icon.contract],
    ["Legal notice", "Send a formal notice for breach or payment.", "Draft a legal notice", Icon.court],
    ["Affidavit", "Create a sworn statement for official or legal use.", "Draft an affidavit", Icon.contract],
];

export function PromptCard({ t, templates, cases, onPlan, workspace = false }) {
    const [text, setText] = useState("");
    const [type, setType] = useState("");
    const [caseId, setCaseId] = useState("");
    const ready = text.trim().length > 0;
    const plan = () => ready && onPlan({ prompt: text.trim(), templateType: type || null, caseId: caseId || null });
    const composer = (
        <Card style={{ padding: workspace ? 16 : "clamp(18px, 3vw, 26px) clamp(16px, 3vw, 28px)", display: "flex", flexDirection: "column", gap: workspace ? 12 : 14, ...(t.mode === "dark" ? { background: workspace ? "#15343c" : "#183840", borderColor: "#2d5a62" } : { background: t.cardHi || t.card }) }}>
            {!workspace && <label htmlFor="docs-need" style={{ fontFamily: SERIF, fontSize: 22, fontWeight: 600, color: t.text }}>What do you need to draft?</label>}
            <div style={{ borderRadius: 13, border: `1px solid ${ready ? t.primary : (t.inputBorder || t.border)}`, background: t.inputBg, overflow: "hidden" }}>
                <textarea id="docs-need" rows={workspace ? 4 : 3} value={text} onChange={e => setText(e.target.value)}
                    onKeyDown={e => { if (workspace && e.key === "Enter" && !e.shiftKey) { e.preventDefault(); plan(); } }}
                    placeholder="e.g. Draft a 6-month NDA between ABC Pvt Ltd and a freelance designer in Karachi"
                    style={{ width: "100%", boxSizing: "border-box", resize: "none", border: "none", outline: "none", background: "transparent", color: t.text, fontFamily: "'Inter', sans-serif", fontSize: 15, lineHeight: 1.55, padding: "16px 18px 8px" }} />
                {workspace && (
                    <div style={{ minHeight: 42, display: "flex", alignItems: "center", gap: 8, padding: "0 16px", borderTop: `1px solid ${t.divider || t.border}`, color: t.textMuted, fontSize: 12.5 }}>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21.4 11.6l-8.9 8.9a6 6 0 01-8.5-8.5l9.6-9.6a4 4 0 015.7 5.7l-9.6 9.6a2 2 0 01-2.8-2.8l8.9-8.9" /></svg>
                        <span>Add files (optional)</span><span style={{ flex: 1 }} />
                        <span style={{ color: t.primary, display: "flex", alignItems: "center", gap: 6 }}>{Icon.spark} Use AI to refine</span>
                    </div>
                )}
            </div>
            {!workspace && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                    <span style={{ fontSize: 12.5, color: t.textMuted, marginRight: 4 }}>Try:</span>
                    {TRY_PROMPTS.map(p => <Chip key={p} onClick={() => setText(p)}>{p}</Chip>)}
                </div>
            )}
            <div style={{ display: "flex", gap: workspace ? 10 : 14, alignItems: "flex-end", flexWrap: "wrap" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 6, flex: "1 1 190px", maxWidth: workspace ? "none" : 280 }}>
                    <label htmlFor="docs-dtype" style={{ fontSize: 11.5, color: t.textMuted }}>Document type</label>
                    <select id="docs-dtype" value={type} onChange={e => setType(e.target.value)} style={fieldStyle(t, { minHeight: 44 })}>
                        <option value="">Auto-detect</option>
                        {(templates || []).filter(s => s.drafting_mode === "ai").map(s => <option key={s.template_type} value={s.template_type}>{s.label}</option>)}
                    </select>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6, flex: "1 1 190px", maxWidth: workspace ? "none" : 320 }}>
                    <label htmlFor="docs-dcase" style={{ fontSize: 11.5, color: t.textMuted }}>Linked case</label>
                    <select id="docs-dcase" value={caseId} onChange={e => setCaseId(e.target.value)} style={fieldStyle(t, { minHeight: 44 })}>
                        <option value="">Standalone — no linked case</option>
                        {(cases || []).map(c => <option key={c._id || c.id} value={c._id || c.id}>{c.title || c.case_type || (c._id || c.id)}</option>)}
                    </select>
                </div>
                <Btn kind="primary" disabled={!ready} onClick={plan} style={{ padding: "0 22px", minHeight: 44 }}>
                    {workspace ? "Create draft plan" : "Plan my draft"} {Icon.arrow}
                </Btn>
            </div>
        </Card>
    );

    if (!workspace) return composer;

    return (
        <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 26 }}>
            <div>
                <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 28 }}>Workspace&nbsp;&nbsp;/&nbsp;&nbsp;<span style={{ color: t.text }}>New draft</span></div>
                <h1 style={{ margin: 0, fontFamily: SERIF, fontSize: "clamp(30px, 3.1vw, 46px)", lineHeight: 1.08, fontWeight: 600, color: t.text }}>What would you like to draft?</h1>
                <p style={{ margin: "8px 0 18px", color: t.textMuted, fontSize: 15 }}>Describe the document you need. You can refine every detail before generating.</p>
                {composer}
            </div>
            <section aria-label="Popular documents" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <h2 style={{ margin: 0, fontFamily: SERIF, fontSize: 19, fontWeight: 600, color: t.text }}>Start with a popular document</h2>
                    <span style={{ flex: 1 }} />
                    <span style={{ color: t.textMuted, fontSize: 12.5 }}>View all templates&nbsp; {Icon.arrow}</span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 12 }}>
                    {POPULAR_DRAFTS.map(([title, description, prompt, icon]) => (
                        <button key={title} type="button" onClick={() => setText(prompt)}
                            style={{ minHeight: 170, padding: 16, display: "flex", flexDirection: "column", alignItems: "flex-start", textAlign: "left", borderRadius: 14, border: `1px solid ${t.border}`, background: t.card, color: t.text, cursor: "pointer", fontFamily: "'Inter', sans-serif" }}>
                            <span style={{ width: 42, height: 42, borderRadius: 12, display: "flex", alignItems: "center", justifyContent: "center", background: t.primaryGlow2, color: t.primary }}>{icon}</span>
                            <strong style={{ marginTop: 13, fontSize: 14, lineHeight: 1.3 }}>{title}</strong>
                            <span style={{ marginTop: 6, fontSize: 12.5, lineHeight: 1.45, color: t.textMuted }}>{description}</span>
                            <span style={{ marginTop: "auto", width: 32, height: 32, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", background: t.primaryGlow2, color: t.primary }}>{Icon.arrow}</span>
                        </button>
                    ))}
                </div>
            </section>
        </div>
    );
}

export default function DocumentsHome({
    templates, templateIssue, cases, draftingMode, dedicatedToolHref,
    onUse, onPlan, onOpenView, continueSlot,
}) {
    const t = useT();
    const [query, setQuery] = useState("");
    const [category, setCategory] = useState("All");
    const [preview, setPreview] = useState(null);     // index into `shown`
    const [customize, setCustomize] = useState(null); // spec

    const list = useMemo(() => (templates || []).map(s => ({ ...s, drafting_mode: draftingMode(s) })), [templates, draftingMode]);
    const categories = useMemo(() => {
        const counts = new Map();
        for (const spec of list) counts.set(spec.category, (counts.get(spec.category) || 0) + 1);
        return [["All", list.length], ...[...counts.entries()].sort(([a], [b]) => a.localeCompare(b))];
    }, [list]);
    const shown = list.filter(spec =>
        (category === "All" || spec.category === category) && templateMatches(spec, query));
    const availableCount = templates === null ? "—" : list.length;
    const aiCount = templates === null ? "—" : list.filter(spec => spec.drafting_mode === "ai").length;
    const categoryCount = templates === null ? "—" : new Set(list.map(spec => spec.category).filter(Boolean)).size;
    const overview = [
        { label: "Total templates", value: availableCount, color: "#4d7df3", bg: "#edf3ff", icon: Icon.contract },
        { label: "AI-assisted", value: aiCount, color: "#16a45b", bg: "#eaf9f0", icon: Icon.spark },
        { label: "Categories", value: categoryCount, color: "#9333ea", bg: "#f7efff", icon: Icon.folder },
        { label: "Available", value: availableCount, color: "#e85d04", bg: "#fff4e8", icon: Icon.download },
    ];

    const use = (spec, prefill) => { setPreview(null); setCustomize(null); onUse(spec, prefill); };

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
            <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                <div>
                    <h1 style={{ margin: 0, fontFamily: SERIF, fontSize: 34, fontWeight: 600, color: t.text }}>Documents</h1>
                    <div style={{ marginTop: 4, fontSize: 14, color: t.textMuted }}>Draft with AI, start from a template, or continue your work.</div>
                </div>
                <Btn onClick={() => onOpenView?.("vault")}>{Icon.folder} Vault</Btn>
            </div>

            <section aria-label="Template overview" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 16 }}>
                {overview.map(item => (
                    <Card key={item.label} style={{ minHeight: 112, padding: "20px 22px", display: "flex", alignItems: "center", gap: 16, boxSizing: "border-box", background: t.mode === "dark" ? (t.cardHi || t.card) : "#ffffff", boxShadow: t.mode === "dark" ? "none" : "0 2px 8px rgba(24, 42, 48, 0.06)" }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ color: t.textDim || t.text, fontSize: 14, fontWeight: 500 }}>{item.label}</div>
                            <div style={{ marginTop: 8, color: t.text, fontSize: 28, lineHeight: 1, fontWeight: 700 }}>{item.value}</div>
                        </div>
                        <span style={{ width: 52, height: 52, flexShrink: 0, borderRadius: 13, display: "flex", alignItems: "center", justifyContent: "center", background: t.mode === "dark" ? `${item.color}22` : item.bg, color: item.color }}>
                            {item.icon}
                        </span>
                    </Card>
                ))}
            </section>

            <section id="templates" aria-label="Document templates" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <div role="group" aria-label="Filter by category" style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                    <h2 style={{ margin: 0, fontFamily: SERIF, fontSize: 20, fontWeight: 600, color: t.text }}>Start from a template</h2>
                    <span style={{ fontSize: 13, color: t.textMuted }}>Reviewed builders · you only fill the details</span>
                    <div style={{ flex: 1 }} />
                    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 12px", borderRadius: 10, border: `1px solid ${query ? t.primary : (t.inputBorder || t.border)}`, background: t.inputBg, width: "min(220px, 100%)" }}>
                        <span style={{ color: t.textMuted, display: "flex" }}>{Icon.search}</span>
                        <label htmlFor="tpl-search" style={{ position: "absolute", left: -9999 }}>Search templates</label>
                        <input id="tpl-search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search templates"
                            style={{ flex: 1, minWidth: 0, minHeight: 40, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 14, fontFamily: "'Inter', sans-serif" }} />
                        {query && <button type="button" onClick={() => setQuery("")} aria-label="Clear search" style={{ background: "none", border: "none", color: t.textMuted, cursor: "pointer", fontSize: 18 }}>×</button>}
                    </div>
                    {categories.length > 2 && categories.map(([name, count]) => (
                        <Chip key={name} active={category === name} onClick={() => setCategory(name)}>
                            {name}<span style={{ opacity: 0.7, fontWeight: 500 }}>{count}</span>
                        </Chip>
                    ))}
                </div>

                {templateIssue ? (
                    <div role="alert" style={{ padding: "14px 16px", borderRadius: 12, background: `${t.warn}14`, border: `1px solid ${t.warn}55`, color: t.text, fontSize: 13 }}>{templateIssue}</div>
                ) : templates === null ? (
                    <div aria-busy="true" style={{ textAlign: "center", padding: 48, color: t.textMuted, fontSize: 13 }}>Loading available templates…</div>
                ) : shown.length === 0 ? (
                    <div style={{ textAlign: "center", padding: "40px 16px", color: t.textMuted, fontSize: 13.5 }}>
                        {list.length === 0 ? "No templates found." : <>No template matches{query ? <> “{query}”</> : null}.{" "}
                            <button type="button" onClick={() => { setQuery(""); setCategory("All"); }}
                                style={{ background: "none", border: "none", color: t.primary, fontWeight: 700, cursor: "pointer", fontSize: 13.5, padding: 0 }}>
                                Show all templates
                            </button></>}
                    </div>
                ) : (
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(min(290px, 100%), 1fr))", gap: 16 }}>
                        {shown.map((spec, i) => {
                            const mode = MODE_VIEW[spec.drafting_mode] || MODE_VIEW.manual;
                            const tile = tileFor(spec);
                            const dedicated = spec.drafting_mode === "dedicated";
                            const n = textFields(spec).length;
                            return (
                                <Card key={spec.template_type} data-template={spec.template_type}
                                    style={{ display: "flex", flexDirection: "column", gap: 10, padding: 18, minHeight: 236, boxSizing: "border-box" }}>
                                    <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                                        <span style={{ width: 46, height: 46, borderRadius: 13, background: tile.bg, color: tile.fg, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>{tile.icon}</span>
                                        <div style={{ flex: 1, minWidth: 0 }}>
                                            <div style={{ fontSize: 12, fontWeight: 600, color: t.textMuted }}>{spec.category}</div>
                                            <h3 style={{ margin: "2px 0 0", fontSize: 16, fontWeight: 600, color: t.text, lineHeight: 1.3 }}>{spec.label}</h3>
                                        </div>
                                        <Pill tone={mode.tone}>{mode.pill}</Pill>
                                    </div>
                                    <p style={{ margin: 0, fontSize: 13.5, color: t.textMuted, lineHeight: 1.55, display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{spec.description}</p>
                                    <div style={{ display: "flex", gap: 14, fontSize: 12.5, color: t.textMuted }}>
                                        {!dedicated && n > 0 && <span>{n} details</span>}
                                        <span>PDF</span>
                                    </div>
                                    <div style={{ display: "flex", gap: 8, marginTop: "auto", paddingTop: 4 }}>
                                        <IconBtn label={`Preview ${spec.label}`} onClick={() => setPreview(i)}>{Icon.eye}</IconBtn>
                                        {!dedicated && <IconBtn label={`Edit ${spec.label}`} onClick={() => setCustomize(spec)}>{Icon.pen}</IconBtn>}
                                        {dedicated ? (
                                            <Btn href={dedicatedToolHref(spec)} style={{ flex: 1, minHeight: 38, color: t.primary }}>Open dedicated calculator</Btn>
                                        ) : (
                                            <Btn kind="primary" onClick={() => use(spec)} style={{ flex: 1, minHeight: 38 }}>Use template</Btn>
                                        )}
                                    </div>
                                </Card>
                            );
                        })}
                    </div>
                )}
            </section>

            {continueSlot}

            {preview !== null && shown[preview] && (
                <PreviewDialog t={t} list={shown} index={preview} onIndex={setPreview}
                    onClose={() => setPreview(null)} onUse={spec => use(spec)}
                    onCustomize={spec => { setPreview(null); setCustomize(spec); }}
                    dedicatedHref={dedicatedToolHref} />
            )}
            {customize && (
                <TemplateEditor spec={customize} onClose={() => setCustomize(null)}
                    onUse={(spec, values) => use(spec, values)} />
            )}
        </div>
    );
}
