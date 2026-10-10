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
import { LIcon } from "./documents/icons.jsx";
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
    "NDA with a freelance designer",
    "Legal notice for a bounced cheque",
    "Rent agreement for a shop in Lahore",
    "Power of attorney for property in Pakistan",
];

/* The examples move as a strip under the heading. Twice the list, shifted by
 * half, loops without a jump; hover (or focus) pauses it; reduced motion
 * stops it and lets it scroll by hand instead. */
const TRY_STRIP_CSS = `@keyframes docsTryStrip{from{transform:translateX(0)}to{transform:translateX(-50%)}}
[data-try-strip] [data-try-track]{display:flex;gap:10px;width:max-content;animation:docsTryStrip 38s linear infinite}
[data-try-strip]:hover [data-try-track],[data-try-strip]:focus-within [data-try-track]{animation-play-state:paused}
@media (prefers-reduced-motion: reduce){[data-try-strip]{overflow-x:auto!important}[data-try-strip] [data-try-track]{animation:none}}`;

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
            <div data-lenis-prevent data-docs-font onClick={onClose} style={{ ...BACKDROP, display: "flex", alignItems: "flex-start", justifyContent: "center", padding: `clamp(8px, 3vw, ${pad}px)`, overflowY: "auto" }}>
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

/* The popular documents on the AI drafting start screen. Each fills the
 * description box (it does not send); `law` names the Act the document is
 * written under, shown as a reference, not as a check. */
const POPULAR_DRAFTS = [
    { title: "Non-disclosure agreement", text: "Protect confidential information shared between parties.", law: "Contract Act 1872", prompt: "Draft a non-disclosure agreement" },
    { title: "Employment agreement", text: "Set clear terms for employees or contractors.", law: "Contract Act 1872", prompt: "Draft an employment agreement" },
    { title: "Legal notice", text: "Send a formal notice for breach or payment.", law: "Pre-litigation notice", prompt: "Draft a legal notice" },
    { title: "Affidavit", text: "Create a sworn statement for official or legal use.", law: "Oaths Act 1873", prompt: "Draft an affidavit" },
    { title: "Rent agreement", text: "Tenancy terms for residential or commercial premises.", law: "Punjab Rented Premises Act 2009", prompt: "Draft a rent agreement" },
    { title: "Power of attorney", text: "Authorise someone to act on your behalf.", law: "Powers of Attorney Act 1882", prompt: "Draft a power of attorney" },
];

/* A native select drawn as the composer's pill: icon, value, chevron. Native,
 * so keyboard and screen readers work as they do for any select. */
function PillSelect({ t, id, label, icon, value, onChange, shown = "", warn = false, title, children, ...rest }) {
    return (
        <label htmlFor={id} title={title || shown} data-pill style={{ position: "relative", display: "inline-flex", alignItems: "center", gap: 7, minHeight: 38, padding: "0 26px 0 11px", borderRadius: 10, boxSizing: "border-box", flexShrink: 0,
            border: `1px solid ${warn ? t.warn : t.border}`, boxShadow: warn ? `0 0 0 2px ${t.warn}33` : "none", background: t.bg, color: t.text, fontSize: 13.5, fontWeight: 600, cursor: "pointer" }}>
            {icon && <LIcon name={icon} size={15} style={{ color: t.textMuted }} />}
            <span style={{ position: "absolute", left: -9999 }}>{label}</span>
            <span aria-hidden="true" data-pill-value style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 220 }}>{shown}</span>
            <select id={id} value={value} onChange={onChange} {...rest}
                style={{ position: "absolute", inset: 0, width: "100%", height: "100%", opacity: 0, cursor: "pointer", appearance: "none", WebkitAppearance: "none", border: "none", font: "inherit" }}>
                {children}
            </select>
            <LIcon name="chevronDown" size={14} style={{ position: "absolute", right: 9, pointerEvents: "none", color: t.textMuted }} />
            {/* The select is invisible, so the pill shows its keyboard focus. */}
            <style>{`[data-pill]:has(select:focus-visible){outline:2px solid ${t.primary};outline-offset:2px}`}</style>
        </label>
    );
}

export function PromptCard({ t, templates, cases, onPlan, workspace = false, onViewTemplates = null, typeRequired = false }) {
    const [text, setText] = useState("");
    const [type, setType] = useState("");
    const [caseId, setCaseId] = useState("");
    const boxRef = useRef(null);
    const ready = text.trim().length > 0;
    const plan = () => ready && onPlan({ prompt: text.trim(), templateType: type || null, caseId: caseId || null });
    const fill = value => { setText(value); boxRef.current?.focus(); };
    const needType = typeRequired && !type;
    const optionStyle = { background: t.card, color: t.text };

    const composer = (
        /* The composer (approved design, 2026-10-08): the description, "Try"
         * examples while it is empty, and one toolbar of choices. */
        <div data-prompt-card style={{ borderRadius: 16, border: `1.5px solid ${t.primary}88`, background: t.mode === "dark" ? "#0b2228" : (t.cardHi || t.card), boxShadow: `0 0 0 3px ${t.primary}10`, overflow: "hidden" }}>
            <div style={{ padding: "16px 18px 10px", display: "flex", flexDirection: "column", gap: 10 }}>
                <label htmlFor="docs-need" style={{ position: "absolute", left: -9999 }}>Describe the document you need</label>
                <textarea id="docs-need" ref={boxRef} rows={3} value={text} onChange={e => setText(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); plan(); } }}
                    placeholder="e.g. 6-month NDA between ABC Pvt Ltd and a freelance designer in Karachi"
                    style={{ width: "100%", boxSizing: "border-box", resize: "vertical", minHeight: 84, outline: "none", border: "none", background: "transparent", color: t.text, fontSize: 16.5, lineHeight: 1.55, padding: 0 }} />
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", padding: "10px 14px", borderTop: `1px solid ${t.border}` }}>
                {/* When the description did not say which document it is, the
                    type is asked HERE -- there is no separate page for it. */}
                <PillSelect t={t} id="docs-dtype" label="Document type" icon="fileText" value={type} onChange={e => setType(e.target.value)}
                    shown={type ? ((templates || []).find(s => s.template_type === type)?.label || type) : "Detect from description"}
                    warn={needType} data-type-required={needType ? "true" : undefined}>
                    <option value="" style={optionStyle}>Detect from description</option>
                    {(templates || []).filter(s => s.drafting_mode === "ai").map(s => <option key={s.template_type} value={s.template_type} style={optionStyle}>{s.label}</option>)}
                </PillSelect>
                <PillSelect t={t} id="docs-dcase" label="Linked case" icon="scale" value={caseId} onChange={e => setCaseId(e.target.value)}
                    shown={caseId ? (() => { const c = (cases || []).find(x => (x._id || x.id) === caseId); return c?.title || c?.case_type || caseId; })() : "Standalone"}>
                    <option value="" style={optionStyle}>Standalone</option>
                    {(cases || []).map(c => <option key={c._id || c.id} value={c._id || c.id} style={optionStyle}>{c.title || c.case_type || (c._id || c.id)}</option>)}
                </PillSelect>
                {/* No upload behind it yet: shown, labelled, not clickable. */}
                <button type="button" disabled data-attach-soon title="Attaching files isn't connected yet — coming soon."
                    style={{ display: "inline-flex", alignItems: "center", gap: 6, minHeight: 38, padding: "0 6px", border: "none", background: "transparent", color: t.textMuted, fontSize: 13.5, fontWeight: 600, cursor: "not-allowed", opacity: 0.75 }}>
                    <LIcon name="paperclip" size={15} />Attach
                </button>
                <button type="button" disabled={!ready} onClick={plan} data-plan-draft title="Plan my draft (Ctrl + Enter)"
                    style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 7, height: 38, padding: "0 14px", marginLeft: "auto", borderRadius: 10, border: "none", background: t.primary, color: onPrimary(t), fontSize: 14, fontWeight: 700, lineHeight: 1, whiteSpace: "nowrap", cursor: ready ? "pointer" : "not-allowed", opacity: ready ? 1 : 0.6, boxShadow: ready ? `0 4px 14px ${t.primary}40` : "none", flexShrink: 0 }}>
                    <LIcon name="sparkles" size={15} />Plan my draft
                </button>
            </div>
            {needType && (
                <div role="alert" data-type-hint style={{ padding: "0 16px 12px", fontSize: 13, color: t.warn }}>
                    We couldn't tell which document this is — choose it under "Detect from description", then press Plan my draft.
                </div>
            )}
        </div>
    );

    if (!workspace) return composer;

    return (
        <div style={{ width: "100%", maxWidth: 1240, margin: "0 auto", display: "flex", flexDirection: "column", gap: 30 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 15 }}>
                <nav aria-label="Breadcrumb" style={{ display: "flex", alignItems: "center", gap: 10, color: t.textMuted }}>
                    {onViewTemplates
                        ? <button type="button" onClick={onViewTemplates} style={{ background: "none", border: "none", padding: 0, color: t.textMuted, fontSize: 15, cursor: "pointer" }}>Documents</button>
                        : <span>Documents</span>}
                    <span aria-hidden="true">/</span>
                    <span style={{ color: t.text, fontWeight: 600 }}>New draft</span>
                </nav>
                <span style={{ flex: 1 }} />
                {/* True of every draft: owner-only until the owner sends it. */}
                <span style={{ display: "inline-flex", alignItems: "center", gap: 8, color: t.textMuted, fontSize: 14.5 }}>
                    <LIcon name="shield" size={17} style={{ color: t.warn }} />Private to your workspace
                </span>
            </div>

            <div>
                <h1 style={{ margin: 0, fontSize: 34, fontWeight: 600, color: t.text }}>What do you need to draft?</h1>
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 16 }}>
                    <style>{TRY_STRIP_CSS}</style>
                    <div data-try-strip aria-label="Example requests" style={{ flex: 1, minWidth: 0, overflow: "hidden",
                        maskImage: "linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent)", WebkitMaskImage: "linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent)" }}>
                        <div data-try-track>
                            {[...TRY_PROMPTS, ...TRY_PROMPTS].map((p, i) => (
                                <button key={`${p}-${i}`} type="button" onClick={() => fill(p)}
                                    // The second copy is only for the loop: one tab stop and one announcement per example.
                                    tabIndex={i < TRY_PROMPTS.length ? 0 : -1} aria-hidden={i < TRY_PROMPTS.length ? undefined : "true"}
                                    style={{ flexShrink: 0, padding: "6px 14px", borderRadius: 999, border: `1px solid ${t.border}`, background: t.card, color: t.text, fontSize: 13.5, whiteSpace: "nowrap", cursor: "pointer" }}>{p}</button>
                            ))}
                        </div>
                    </div>
                </div>
            </div>

            {composer}

            <section aria-label="Popular documents" style={{ display: "flex", flexDirection: "column", gap: 18, marginTop: 6 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
                    <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600, color: t.text }}>Start with a popular document</h2>
                    <span style={{ flex: 1 }} />
                    {/* A real link back to the catalogue, or nothing. */}
                    {onViewTemplates && (
                        <button type="button" onClick={onViewTemplates}
                            style={{ display: "inline-flex", alignItems: "center", gap: 6, background: "none", border: "none", color: t.primary, fontSize: 14, fontWeight: 600, cursor: "pointer", padding: 0 }}>
                            View all <LIcon name="arrowRight" size={15} />
                        </button>
                    )}
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(420px, 100%), 1fr))", gap: 18 }}>
                    {POPULAR_DRAFTS.map(d => (
                        <button key={d.title} type="button" data-popular={d.title} onClick={() => fill(d.prompt)}
                            style={{ display: "flex", alignItems: "flex-start", gap: 14, padding: 18, borderRadius: 16, border: `1px solid ${t.border}`, background: t.mode === "dark" ? "#0b1f24" : t.card, color: t.text, textAlign: "left", cursor: "pointer" }}>
                            <span aria-hidden="true" style={{ width: 44, height: 44, flexShrink: 0, borderRadius: 12, display: "flex", alignItems: "center", justifyContent: "center", background: `${t.primary}1a`, border: `1px solid ${t.primary}33`, color: t.primary }}>
                                <LIcon name="fileText" size={19} />
                            </span>
                            <span style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 6 }}>
                                <strong style={{ fontSize: 16, fontWeight: 600 }}>{d.title}</strong>
                                <span style={{ fontSize: 13.5, lineHeight: 1.5, color: t.textMuted }}>{d.text}</span>
                                <span style={{ fontSize: 12.5, fontWeight: 600, color: t.warn, marginTop: 2 }}>{d.law}</span>
                            </span>
                            <LIcon name="arrowRight" size={18} style={{ color: t.textMuted, marginTop: 4 }} />
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
    // The cards' round icon buttons.
    const roundBtn = { width: 40, height: 40, borderRadius: "50%", color: t.primary };

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
                {/* Row 1: the heading, and search on the far right. Row 2: the
                    category filters on a line of their own (2026-10-08). */}
                <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                    <h2 style={{ margin: 0, fontFamily: SERIF, fontSize: 20, fontWeight: 600, color: t.text }}>Start from a template</h2>
                    <span style={{ fontSize: 13, color: t.textMuted }}>Reviewed builders · you only fill the details</span>
                    <div style={{ flex: 1 }} />
                    <div data-template-search style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 12px", borderRadius: 10, border: `1px solid ${query ? t.primary : (t.inputBorder || t.border)}`, background: t.inputBg, width: "min(280px, 100%)", marginLeft: "auto" }}>
                        <span style={{ color: t.textMuted, display: "flex" }}>{Icon.search}</span>
                        <label htmlFor="tpl-search" style={{ position: "absolute", left: -9999 }}>Search templates</label>
                        <input id="tpl-search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search templates"
                            style={{ flex: 1, minWidth: 0, minHeight: 40, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 14, fontFamily: "'Inter', sans-serif" }} />
                        {query && <button type="button" onClick={() => setQuery("")} aria-label="Clear search" style={{ background: "none", border: "none", color: t.textMuted, cursor: "pointer", fontSize: 18 }}>×</button>}
                    </div>
                </div>
                {categories.length > 2 && (
                    <div role="group" aria-label="Filter by category" data-category-filters style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                        {categories.map(([name, count]) => (
                            <Chip key={name} active={category === name} onClick={() => setCategory(name)}>
                                {name}<span style={{ opacity: 0.7, fontWeight: 500 }}>{count}</span>
                            </Chip>
                        ))}
                    </div>
                )}

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
                                /* Balanced card (2026-10-08): icon and mode on top, the
                                   name, the facts, the actions. The
                                   description is not repeated here -- it is the
                                   card's tooltip and the first line of Preview. */
                                <Card key={spec.template_type} data-template={spec.template_type} title={spec.description}
                                    style={{ display: "flex", flexDirection: "column", gap: 12, padding: 18, minHeight: 0, boxSizing: "border-box" }}>
                                    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
                                        <span style={{ width: 44, height: 44, borderRadius: 12, background: tile.bg, color: tile.fg, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>{tile.icon}</span>
                                        <Pill tone={mode.tone}>{mode.pill}</Pill>
                                    </div>
                                    <div style={{ minHeight: 64 }}>
                                        <div data-template-category style={{ fontSize: 12, fontWeight: 600, color: t.textMuted }}>{spec.category}</div>
                                        <h3 style={{ margin: "3px 0 0", fontSize: 16.5, fontWeight: 600, color: t.text, lineHeight: 1.35, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{spec.label}</h3>
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13, color: t.textMuted }}>
                                        <span>{dedicated ? "Calculated figures" : n > 0 ? `${n} details to fill` : "No details needed"}</span>
                                        <span>PDF</span>
                                    </div>
                                    <div style={{ display: "flex", gap: 8, marginTop: "auto" }}>
                                        {/* Round Edit and Preview, in that order (2026-10-08). */}
                                        {!dedicated && <IconBtn label={`Edit ${spec.label}`} onClick={() => setCustomize(spec)} style={roundBtn}><LIcon name="squarePen" size={18} /></IconBtn>}
                                        <IconBtn label={`Preview ${spec.label}`} onClick={() => setPreview(i)} style={roundBtn}><LIcon name="eye" size={18} /></IconBtn>
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
