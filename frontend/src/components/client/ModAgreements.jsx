'use client';
// Paste your ModAgreements.jsx code here
import React, { useState, Fragment, useRef, useCallback, useEffect } from "react";
import { useT } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import Ic from "./Ic.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput, Badge } from "@/components/shared/shared.jsx";
import { useAuth } from "@/context/AuthContext.jsx";
import { createAgreement, signAgreement, listAgreements, searchLawyers } from "@/lib/api.js";

/* ══════════════════════════════════════════════════════
   MODULE: AGREEMENTS — 5-Step Wizard
══════════════════════════════════════════════════════ */
const AGMT_TEMPLATES = [
    { name: "Service Agreement", cat: "Business", ico: "💼", desc: "Professional services contract between two parties.", popular: true },
    { name: "Non-Disclosure (NDA)", cat: "NDA", ico: "🔒", desc: "Protect confidential information shared between parties.", popular: true },
    { name: "Employment Contract", cat: "Employment", ico: "👔", desc: "Terms and conditions of employment.", popular: false },
    { name: "Lease Agreement", cat: "Property", ico: "🏠", desc: "Rental or lease of property with terms and rent schedule.", popular: false },
    { name: "Partnership Deed", cat: "Business", ico: "🤝", desc: "Formal partnership agreement defining roles and profit sharing.", popular: true },
    { name: "Freelance Contract", cat: "Business", ico: "💻", desc: "Contract for freelance or contract-based project delivery.", popular: false },
    { name: "Divorce Settlement", cat: "Family", ico: "⚖️", desc: "Mutual agreement on asset division and custody.", popular: false },
    { name: "Power of Attorney", cat: "Business", ico: "📜", desc: "Authorize another person to act on your behalf.", popular: false },
    { name: "Joint Venture Agmt.", cat: "Business", ico: "🏢", desc: "Agreement to collaborate on a joint business venture.", popular: false },
];

const AGMT_CLAUSES_INIT = [
    { title: "Definitions & Interpretation", text: "All terms used shall have their standard legal meaning unless otherwise specified.", required: true },
    { title: "Scope of Work", text: "The parties agree to the scope and deliverables as outlined in Schedule A attached hereto.", required: true },
    { title: "Payment Terms", text: "Payment shall be made within 30 days of invoice. Click to edit payment schedule details.", required: false },
    { title: "Confidentiality", text: "Both parties shall maintain strict confidentiality of all information exchanged under this agreement.", required: false },
    { title: "Dispute Resolution", text: "Any dispute shall be resolved through arbitration in accordance with the Arbitration Act 1940.", required: true },
    { title: "Termination", text: "Either party may terminate this agreement with 30 days written notice.", required: false },
];


// ─────────────────────────────────────────────
//  ModAgreements — redesigned to match new UI screens
//  Pages: Dashboard → Templates → Create (4-step) → All Agreements
// ─────────────────────────────────────────────


// ── Theme tokens (passed in via useT() in host app, replicated here for self-contained demo) ──
const useTheme = useT;

// ── Shared micro-components ──────────────────
const Btn = ({ children, primary, outline, danger, style, disabled, onClick, ...p }) => {
    const t = useTheme();
    const base = {
        display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6,
        fontFamily: "'Inter',sans-serif", fontWeight: 600, fontSize: 13, cursor: disabled ? "not-allowed" : "pointer",
        border: "none", borderRadius: 10, padding: "10px 20px", transition: "all 0.18s", outline: "none",
        opacity: disabled ? 0.45 : 1,
    };
    const variants = primary
        ? { background: t.grad1, color: "#1A2E35", boxShadow: `0 4px 16px ${t.primaryGlow}` }
        : danger
            ? { background: "transparent", color: t.danger, border: `1.5px solid ${t.danger}` }
            : { background: "transparent", color: t.textDim, border: `1.5px solid ${t.border}` };
    return <button onClick={disabled ? undefined : onClick} style={{ ...base, ...variants, ...style }} {...p}>{children}</button>;
};

const StatusBadge = ({ status }) => {
    const t = useTheme();
    const map = {
        Signed: { bg: "rgba(77,212,163,0.15)", color: "#4DD4A3", border: "rgba(77,212,163,0.3)" },
        Pending: { bg: "rgba(255,200,87,0.15)", color: "#FFC857", border: "rgba(255,200,87,0.3)" },
        Rejected: { bg: "rgba(255,107,122,0.15)", color: "#FF6B7A", border: "rgba(255,107,122,0.3)" },
        Draft: { bg: "rgba(154,154,148,0.2)", color: "#ACACAA", border: "rgba(154,154,148,0.3)" },
    };
    const s = map[status] || map.Draft;
    return (
        <span style={{
            fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 20,
            background: s.bg, color: s.color, border: `1px solid ${s.border}`
        }}>
            {status}
        </span>
    );
};

const Input = ({ style, ...p }) => {
    const t = useTheme();
    return (
        <input style={{
            background: t.inputBg, border: `1.5px solid ${t.border}`, color: t.text,
            borderRadius: 10, padding: "11px 14px", fontSize: 13, outline: "none", width: "100%",
            fontFamily: "'Inter',sans-serif", boxSizing: "border-box",
            ...style
        }} {...p} />
    );
};



// ── TEMPLATE DATA ────────────────────────────
const TEMPLATES = [
    {
        ico: "💼", name: "Employment Contract", cat: "Employment", popular: true,
        desc: "Standard employment agreement with terms, compensation, and responsibilities.",
        body: `Employment Contract\n\nThis Employment Agreement ("Agreement") is entered into as of [Date], by and between:\n\n1. Parties\nEmployer: [Company Name], a [State] corporation ("Employer")\nEmployee: [Employee Name] ("Employee")\n\n2. Position and Duties\nEmployee shall serve as [Job Title] and shall perform duties as reasonably assigned by Employer.\n\n3. Compensation\nBase Salary: $[Amount] per year\nPayment Schedule: Bi-weekly\nBenefits: As per company policy\n\n4. Term\nThis Agreement commences on [Start Date] and continues until terminated.\n\n5. Confidentiality\nEmployee agrees to maintain strict confidentiality of all proprietary information during and after employment.\n\n6. Non-Compete\nFor a period of [Duration] following termination, Employee shall not engage in competing business activities within [Geographic Area].`
    },
    {
        ico: "🔒", name: "Non-Disclosure Agreement", cat: "NDA", popular: true,
        desc: "Mutual or one-way NDA for protecting confidential information.",
        body: `Non-Disclosure Agreement\n\nThis Non-Disclosure Agreement is entered into as of [Date] between the parties listed below.\n\n1. Definition of Confidential Information\nAll non-public information disclosed by either party.\n\n2. Obligations\nEach party agrees to keep confidential information strictly confidential.\n\n3. Term\nThis agreement remains in effect for [Duration] years.`
    },
    {
        ico: "🏠", name: "Lease Agreement", cat: "Property", popular: true,
        desc: "Residential or commercial property lease with standard terms.",
        body: `Lease Agreement\n\nThis Lease Agreement is entered into as of [Date].\n\n1. Parties\nLandlord: [Landlord Name]\nTenant: [Tenant Name]\n\n2. Property\nAddress: [Property Address]\n\n3. Term\nLease period: [Start Date] to [End Date]\n\n4. Rent\nMonthly rent: $[Amount] due on the 1st of each month.`
    },
    {
        ico: "📄", name: "Service Agreement", cat: "Business", popular: true,
        desc: "Professional services agreement for contractors and clients.",
        body: `Service Agreement\n\nThis Service Agreement is entered into as of [Date].\n\n1. Services\nService Provider agrees to perform: [Description of Services]\n\n2. Compensation\nClient agrees to pay: $[Amount]\n\n3. Timeline\nServices to be completed by: [Date]`
    },
    {
        ico: "🤝", name: "Partnership Agreement", cat: "Business", popular: false,
        desc: "Business partnership terms, profit sharing, and responsibilities.",
        body: `Partnership Agreement\n\nThis Partnership Agreement is entered into as of [Date].\n\n1. Partners\nPartner 1: [Name]\nPartner 2: [Name]\n\n2. Purpose\n[Business Purpose]\n\n3. Profit Sharing\nProfits and losses split equally unless otherwise agreed.`
    },
    {
        ico: "💼", name: "Freelancer Contract", cat: "Employment", popular: false,
        desc: "Independent contractor agreement for freelance work.",
        body: `Freelancer Contract\n\nThis Independent Contractor Agreement is entered into as of [Date].\n\n1. Contractor: [Name]\n2. Client: [Name]\n3. Project: [Description]\n4. Payment: $[Amount]\n5. Deadline: [Date]`
    },
];

// ── REAL AGREEMENT HELPERS ───────────────────
const AG_STATUS_LABEL = { pending: "Pending", executed: "Signed", cancelled: "Rejected", draft: "Draft" };

const mapAgreement = (a, myId) => {
    const parties = a.parties || [];
    const me = parties.find(p => p.user_id === myId);
    return {
        id: a.id || a._id,
        name: a.title || "Agreement",
        body: a.body_html || "",
        status: AG_STATUS_LABEL[a.status] || "Pending",
        rawStatus: a.status,
        parties,
        signedCount: parties.filter(p => p.signed).length,
        totalParties: parties.length,
        needsMySig: a.status === "pending" && !!me && !me.signed,
        date: a.created_at ? new Date(a.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "",
        counterparts: parties.filter(p => p.user_id !== myId).map(p => p.full_name).join(" · "),
        eto: a.eto_classification,
        isEngagementLetter: !!a.engagement_id,
    };
};

// Fetch + map the user's real agreements; returns [items, loading, reload]
const useMyAgreements = (userId) => {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const reload = useCallback(() => {
        listAgreements().then(({ data }) => {
            if (Array.isArray(data)) setItems(data.map(a => mapAgreement(a, userId)));
            setLoading(false);
        }).catch(() => setLoading(false));
    }, [userId]);
    useEffect(() => { reload(); }, [reload]);
    return [items, loading, reload];
};

// ── STEP PROGRESS BAR ────────────────────────
const StepBar = ({ steps, current }) => {
    const t = useTheme();
    return (
        <div style={{ display: "flex", alignItems: "center", gap: 0, marginBottom: 28 }}>
            {steps.map((s, i) => {
                const done = i < current, active = i === current;
                return (
                    <Fragment key={s}>
                        <div style={{
                            display: "flex", alignItems: "center", gap: 8,
                            background: active ? t.primaryGlow : done ? "transparent" : "transparent",
                            border: active ? `1.5px solid ${t.primary}` : done ? `1.5px solid ${t.border}` : `1.5px solid ${t.border}`,
                            borderRadius: 12, padding: "8px 16px", transition: "all 0.25s",
                        }}>
                            <div style={{
                                width: 22, height: 22, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
                                fontSize: 10, fontWeight: 800, flexShrink: 0,
                                background: done ? t.primary : active ? t.primary : t.border,
                                color: done || active ? "#1A2E35" : t.textMuted,
                            }}>
                                {done ? "✓" : i + 1}
                            </div>
                            <span style={{
                                fontSize: 13, fontWeight: active ? 700 : 500,
                                color: active ? t.primary : done ? t.text : t.textMuted, whiteSpace: "nowrap"
                            }}>
                                {s}
                            </span>
                        </div>
                        {i < steps.length - 1 && (
                            <div style={{
                                flex: 1, height: 2, background: done ? t.primary : t.border,
                                margin: "0 4px", minWidth: 24, transition: "background 0.3s"
                            }} />
                        )}
                    </Fragment>
                );
            })}
        </div>
    );
};

// ── PAGE: DASHBOARD ──────────────────────────
const PageDashboard = ({ onNavigate }) => {
    const t = useTheme();
    const { user } = useAuth();
    const [agmts, loading] = useMyAgreements(user?._id);
    const awaitingMe = agmts.filter(a => a.needsMySig).length;
    const stats = [
        { label: "Total Agreements", val: agmts.length, sub: null, icon: "📄", color: t.primary },
        { label: "Awaiting My Signature", val: awaitingMe, sub: awaitingMe ? "Action needed" : null, icon: "✍️", color: t.warn },
        { label: "Pending Others", val: agmts.filter(a => a.status === "Pending" && !a.needsMySig).length, sub: null, icon: "⏰", color: t.info },
        { label: "Executed", val: agmts.filter(a => a.status === "Signed").length, sub: null, icon: "✅", color: t.success },
    ];
    return (
        <div>
            <div style={{ marginBottom: 28 }}>
                <h1 style={{ fontSize: 28, fontWeight: 800, color: t.text, margin: 0, fontFamily: "'Sora','Inter',sans-serif" }}>Dashboard</h1>
                <p style={{ fontSize: 13, color: t.textMuted, margin: "4px 0 0" }}>Overview of your digital agreements</p>
            </div>

            {/* Stats row */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14, marginBottom: 20 }}>
                {stats.map(s => (
                    <Card key={s.label} style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", padding: 20 }}>
                        <div>
                            <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 6 }}>{s.label}</div>
                            <div style={{ fontSize: 32, fontWeight: 800, color: t.text, fontFamily: "'Sora','Inter',sans-serif", lineHeight: 1 }}>{s.val}</div>
                            {s.sub && <div style={{ fontSize: 11, color: t.success, marginTop: 6 }}>{s.sub}</div>}
                        </div>
                        <div style={{
                            width: 40, height: 40, borderRadius: 10, background: t.primaryGlow,
                            display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18
                        }}>{s.icon}</div>
                    </Card>
                ))}
            </div>

            {/* Quick actions */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 20 }}>
                {[
                    { ico: "📄", title: "Create Agreement", sub: "Start from a template or scratch", page: "templates" },
                    { ico: "✍️", title: "Sign Agreement", sub: "Review and sign pending documents", page: "all" },
                ].map(a => (
                    <div key={a.title} onClick={() => onNavigate(a.page)} style={{
                        display: "flex", alignItems: "center", gap: 16, padding: "20px 24px",
                        background: t.card, border: `1.5px solid ${t.border}`, borderRadius: 16,
                        cursor: "pointer", transition: "all 0.2s", boxShadow: t.shadowCard,
                    }}
                        onMouseEnter={e => { e.currentTarget.style.border = `1.5px solid ${t.primary}`; e.currentTarget.style.boxShadow = t.shadowHover; }}
                        onMouseLeave={e => { e.currentTarget.style.border = `1.5px solid ${t.border}`; e.currentTarget.style.boxShadow = t.shadowCard; }}
                    >
                        <div style={{
                            width: 48, height: 48, borderRadius: 12, background: t.grad1,
                            display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, flexShrink: 0
                        }}>{a.ico}</div>
                        <div style={{ flex: 1 }}>
                            <div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>{a.title}</div>
                            <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>{a.sub}</div>
                        </div>
                        <span style={{ color: t.primary, fontSize: 18 }}>→</span>
                    </div>
                ))}
            </div>

            {/* Recent agreements */}
            <Card style={{ padding: 0, overflow: "hidden" }}>
                <div style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "14px 20px", borderBottom: `1px solid ${t.border}`
                }}>
                    <span style={{ fontSize: 15, fontWeight: 700, color: t.text }}>Recent Agreements</span>
                    <span onClick={() => onNavigate("all")} style={{ fontSize: 12, color: t.primary, cursor: "pointer", fontWeight: 600 }}>View All</span>
                </div>
                {loading ? (
                    <div style={{ padding: "28px 20px", textAlign: "center", color: t.textMuted, fontSize: 13 }}>Loading…</div>
                ) : agmts.length === 0 ? (
                    <div style={{ padding: "28px 20px", textAlign: "center", color: t.textMuted, fontSize: 13 }}>
                        No agreements yet — create one, or hire a lawyer to receive an engagement letter here.
                    </div>
                ) : agmts.slice(0, 4).map((a, i) => (
                    <div key={a.id} onClick={() => onNavigate("all")} style={{
                        display: "flex", alignItems: "center", gap: 12, padding: "14px 20px",
                        borderBottom: i < Math.min(agmts.length, 4) - 1 ? `1px solid ${t.border}` : "none",
                        transition: "background 0.15s", cursor: "pointer",
                    }}
                        onMouseEnter={e => e.currentTarget.style.background = t.cardHi}
                        onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                    >
                        <div style={{
                            width: 36, height: 36, borderRadius: 10, background: t.primaryGlow,
                            display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, flexShrink: 0
                        }}>{a.isEngagementLetter ? "⚖️" : "📄"}</div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: 13, fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</div>
                            <div style={{ fontSize: 11, color: t.textMuted, marginTop: 1 }}>
                                {a.signedCount} of {a.totalParties} signed{a.needsMySig ? " · your signature needed" : ""}
                            </div>
                        </div>
                        <div style={{ fontSize: 11, color: t.textMuted, marginRight: 10 }}>{a.date}</div>
                        <StatusBadge status={a.status} />
                    </div>
                ))}
            </Card>
        </div>
    );
};

// ── PAGE: TEMPLATE GALLERY ───────────────────
const PageTemplates = ({ onNavigate, onSelectTemplate }) => {
    const t = useTheme();
    const [cat, setCat] = useState("All Templates");
    const [search, setSearch] = useState("");
    const cats = ["All Templates", "Employment", "NDA", "Lease", "Service", "Partnership"];
    const filtered = TEMPLATES.filter(tmpl =>
        (cat === "All Templates" || tmpl.cat === cat || tmpl.name.toLowerCase().includes(cat.toLowerCase())) &&
        tmpl.name.toLowerCase().includes(search.toLowerCase())
    );
    return (
        <div>
            <div style={{ marginBottom: 24 }}>
                <h1 style={{ fontSize: 28, fontWeight: 800, color: t.text, margin: 0, fontFamily: "'Sora','Inter',sans-serif" }}>Agreement Templates</h1>
                <p style={{ fontSize: 13, color: t.textMuted, margin: "4px 0 0" }}>Browse and select a template to get started</p>
            </div>

            {/* Category pills */}
            <div style={{ display: "flex", gap: 8, marginBottom: 24, flexWrap: "wrap" }}>
                {cats.map(c => (
                    <button key={c} onClick={() => setCat(c)} style={{
                        padding: "9px 18px", borderRadius: 50, fontSize: 13, fontWeight: cat === c ? 700 : 500,
                        cursor: "pointer", fontFamily: "'Inter',sans-serif",
                        border: `1.5px solid ${cat === c ? t.primary : t.border}`,
                        background: cat === c ? t.primaryGlow : "transparent",
                        color: cat === c ? t.primary : t.textMuted, transition: "all 0.18s",
                    }}>{c}</button>
                ))}
            </div>

            {/* Template grid */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16 }}>
                {filtered.map((tmpl, i) => (
                    <Card key={i} style={{
                        padding: 24, display: "flex", flexDirection: "column", gap: 0, position: "relative",
                        transition: "all 0.2s",
                    }}
                        onMouseEnter={e => { e.currentTarget.style.border = `1px solid ${t.primary}`; e.currentTarget.style.boxShadow = t.shadowHover; }}
                        onMouseLeave={e => { e.currentTarget.style.border = `1px solid ${t.border}`; e.currentTarget.style.boxShadow = t.shadowCard; }}
                    >
                        {tmpl.popular && (
                            <div style={{
                                position: "absolute", top: 16, right: 16, fontSize: 10, fontWeight: 800,
                                letterSpacing: "0.6px", color: t.primary, background: t.primaryGlow,
                                border: `1px solid ${t.primary}40`, borderRadius: 6, padding: "3px 8px"
                            }}>POPULAR</div>
                        )}
                        <div style={{
                            width: 44, height: 44, borderRadius: 12, background: t.primaryGlow,
                            display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20,
                            border: `1px solid ${t.primary}30`, marginBottom: 14
                        }}>{tmpl.ico}</div>
                        <div style={{
                            fontSize: 16, fontWeight: 700, color: t.text, marginBottom: 8,
                            fontFamily: "'Sora','Inter',sans-serif"
                        }}>{tmpl.name}</div>
                        <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.55, marginBottom: 20, flex: 1 }}>{tmpl.desc}</div>
                        <div style={{ display: "flex", gap: 8 }}>
                            <Btn outline style={{ flex: 1, fontSize: 12, padding: "9px 0" }}
                                onClick={() => alert(`Preview: ${tmpl.name}`)}>👁 Preview</Btn>
                            <Btn primary style={{ flex: 1, fontSize: 12, padding: "9px 0" }}
                                onClick={() => { onSelectTemplate(tmpl); onNavigate("create"); }}>✓ Use</Btn>
                        </div>
                    </Card>
                ))}
            </div>
        </div>
    );
};

// ── PAGE: CREATE AGREEMENT (4 steps) ─────────
const TOOLBAR_ACTIONS = [
    { label: "¶", title: "Paragraph" }, { label: "H1", title: "Heading 1", bold: true },
    { label: "H2", title: "Heading 2" }, { label: "H3", title: "Heading 3" }, null,
    { label: "B", title: "Bold" }, { label: "I", title: "Italic" }, { label: "U", title: "Underline" },
    { label: "S", title: "Strikethrough" }, { label: "🖊", title: "Highlight" }, null,
    { label: "≡", title: "Left" }, { label: "≡", title: "Center" }, { label: "≡", title: "Right" }, { label: "≡", title: "Justify" }, null,
    { label: "•", title: "Bullet list" }, { label: "1.", title: "Numbered list" }, { label: "❝", title: "Quote" }, { label: "—", title: "Divider" },
    { label: "⊞", title: "Table" }, null,
    { label: "Tx", title: "Clear format" }, { label: "↩", title: "Undo" }, { label: "↪", title: "Redo" },
];

const SIG_METHOD_MAP = { draw: "canvas", type: "typed", upload: "image_upload" };

const PageCreate = ({ template, onNavigate, onDone }) => {
    const t = useTheme();
    const toast = useToast();
    const { user } = useAuth();
    const [step, setStep] = useState(0);
    const [title, setTitle] = useState(template?.name || "New Agreement");
    const [body, setBody] = useState(template?.body || "");
    // Real counterparty — a registered user who will counter-sign from their dashboard
    const [counterparty, setCounterparty] = useState(null);
    const [cpList, setCpList] = useState([]);
    const [cpLoading, setCpLoading] = useState(true);
    const [cpSearch, setCpSearch] = useState("");
    const [fullName, setFullName] = useState("");
    const [hasSig, setHasSig] = useState(false);
    const [sigMode, setSigMode] = useState("draw");
    const [typedSig, setTypedSig] = useState("");
    const [uploadedSig, setUploadedSig] = useState(null);
    const [submitting, setSubmitting] = useState(false);
    const canvasRef = useRef(null);
    const drawing = useRef(false);
    const lastPos = useRef({ x: 0, y: 0 });

    const STEPS = ["Edit Agreement", "Choose Counterparty", "Your Signature", "Review & Send"];

    // Verified lawyers are the counterparties available on the platform
    useEffect(() => {
        searchLawyers({ page_size: 50 }).then(({ data }) => {
            const items = Array.isArray(data) ? data : (data?.items || []);
            setCpList(items.map(l => ({
                _id: l._id,
                name: l.full_name || "Lawyer",
                spec: ((l.lawyer_profile?.specializations || [])[0] || "General Practice").replace(/_/g, " "),
                avatar: (l.full_name || "L").split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase(),
            })));
            setCpLoading(false);
        }).catch(() => setCpLoading(false));
    }, []);

    // Canvas drawing
    const startDraw = useCallback(e => {
        drawing.current = true;
        const r = canvasRef.current.getBoundingClientRect();
        const x = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
        const y = (e.touches ? e.touches[0].clientY : e.clientY) - r.top;
        lastPos.current = { x, y };
    }, []);
    const draw = useCallback(e => {
        if (!drawing.current || !canvasRef.current) return;
        e.preventDefault();
        const r = canvasRef.current.getBoundingClientRect();
        const x = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
        const y = (e.touches ? e.touches[0].clientY : e.clientY) - r.top;
        const ctx = canvasRef.current.getContext("2d");
        ctx.beginPath();
        ctx.moveTo(lastPos.current.x, lastPos.current.y);
        ctx.lineTo(x, y);
        ctx.strokeStyle = "#40F0DC";
        ctx.lineWidth = 2;
        ctx.lineCap = "round";
        ctx.stroke();
        lastPos.current = { x, y };
        setHasSig(true);
    }, []);
    const stopDraw = useCallback(() => { drawing.current = false; }, []);
    const clearSig = () => {
        if (canvasRef.current) {
            canvasRef.current.getContext("2d").clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
        }
        setHasSig(false);
        setTypedSig("");
        setUploadedSig(null);
    };

    const nav = (n) => {
        if (n > step && step === 0 && !title.trim()) return;
        if (n > 1 && step === 1 && !counterparty) { toast.show("⚠️ Select a counterparty first", "warn"); return; }
        setStep(Math.max(0, Math.min(3, n)));
    };

    return (
        <div>
            {/* Header */}
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 24 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <button onClick={() => onNavigate("templates")} style={{
                        width: 36, height: 36, borderRadius: 10, border: `1.5px solid ${t.border}`,
                        background: t.inputBg, color: t.textMuted, fontSize: 14, cursor: "pointer",
                        display: "flex", alignItems: "center", justifyContent: "center",
                    }}>←</button>
                    <div>
                        <h2 style={{ fontSize: 20, fontWeight: 800, color: t.text, margin: 0, fontFamily: "'Sora','Inter',sans-serif" }}>Create Agreement</h2>
                        <div style={{ fontSize: 12, color: t.textMuted, marginTop: 1 }}>{template?.name || "Custom"}</div>
                    </div>
                </div>
                <Btn outline style={{ fontSize: 12, padding: "9px 16px" }} onClick={() => alert("Draft saved!")}>
                    💾 Save Draft
                </Btn>
            </div>

            {/* Steps */}
            <StepBar steps={STEPS} current={step} />

            {/* ── STEP 0: Edit Agreement ── */}
            {step === 0 && (
                <div>
                    <div style={{ marginBottom: 16 }}>
                        <div style={{
                            fontSize: 11, fontWeight: 600, color: t.textMuted, textTransform: "uppercase",
                            letterSpacing: "0.7px", marginBottom: 6
                        }}>Agreement Title</div>
                        <Input value={title} onChange={e => setTitle(e.target.value)}
                            style={{ fontSize: 15, fontWeight: 600, padding: "14px 16px" }} />
                    </div>
                    {/* Editor */}
                    <Card style={{ padding: 0, overflow: "hidden" }}>
                        {/* Toolbar */}
                        <div style={{
                            display: "flex", alignItems: "center", gap: 1, padding: "8px 12px",
                            borderBottom: `1px solid ${t.border}`, flexWrap: "wrap", background: t.surface
                        }}>
                            {TOOLBAR_ACTIONS.map((a, i) => a === null
                                ? <div key={i} style={{ width: 1, height: 20, background: t.border, margin: "0 4px" }} />
                                : (
                                    <button key={i} title={a.title} style={{
                                        width: 28, height: 28, borderRadius: 6, border: "none", background: "transparent",
                                        color: a.bold ? t.text : t.textMuted, fontWeight: a.bold ? 700 : 400,
                                        fontSize: a.label.length > 1 ? 10 : 13, cursor: "pointer", display: "flex",
                                        alignItems: "center", justifyContent: "center", transition: "background 0.12s",
                                        fontFamily: "'Inter',sans-serif",
                                    }}
                                        onMouseEnter={e => e.currentTarget.style.background = t.inputBg}
                                        onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                                    >{a.label}</button>
                                )
                            )}
                        </div>
                        {/* Body */}
                        <textarea value={body} onChange={e => setBody(e.target.value)}
                            style={{
                                width: "100%", minHeight: 380, background: t.card, border: "none", color: t.text,
                                fontSize: 14, lineHeight: 1.8, padding: "20px 24px", outline: "none", resize: "vertical",
                                fontFamily: "Georgia, 'Times New Roman', serif", boxSizing: "border-box",
                            }} />
                    </Card>
                </div>
            )}

            {/* ── STEP 1: Choose Counterparty ── */}
            {step === 1 && (
                <div>
                    <div style={{ marginBottom: 16 }}>
                        <div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>Counterparty</div>
                        <div style={{ fontSize: 12, color: t.textMuted }}>
                            Choose who signs this agreement with you. They'll be notified and counter-sign from their own dashboard.
                        </div>
                    </div>

                    {counterparty && (
                        <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", borderRadius: 12, background: t.primaryGlow, border: `1.5px solid ${t.primary}`, marginBottom: 14 }}>
                            <div style={{ width: 36, height: 36, borderRadius: "50%", background: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 800, color: t.mode === "dark" ? "#1A2E35" : "#fff" }}>{counterparty.avatar}</div>
                            <div style={{ flex: 1 }}>
                                <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>{counterparty.name}</div>
                                <div style={{ fontSize: 11, color: t.primary, textTransform: "capitalize" }}>{counterparty.spec} · will counter-sign</div>
                            </div>
                            <button onClick={() => setCounterparty(null)} style={{ background: "none", border: `1px solid ${t.border}`, borderRadius: 8, padding: "5px 12px", color: t.textMuted, fontSize: 11, cursor: "pointer" }}>Change</button>
                        </div>
                    )}

                    <div style={{ position: "relative", marginBottom: 12 }}>
                        <span style={{ position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)", fontSize: 13, color: t.textMuted }}>🔍</span>
                        <Input placeholder="Search verified lawyers…" value={cpSearch} onChange={e => setCpSearch(e.target.value)} style={{ paddingLeft: 38 }} />
                    </div>

                    <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 380, overflowY: "auto" }}>
                        {cpLoading ? (
                            <div style={{ padding: "28px 0", textAlign: "center", color: t.textMuted, fontSize: 13 }}>Loading verified lawyers…</div>
                        ) : cpList.filter(l => l.name.toLowerCase().includes(cpSearch.toLowerCase())).map(l => (
                            <div key={l._id} onClick={() => setCounterparty(l)} style={{
                                display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", borderRadius: 12,
                                border: `1.5px solid ${counterparty?._id === l._id ? t.primary : t.border}`,
                                background: counterparty?._id === l._id ? t.primaryGlow : t.card,
                                cursor: "pointer", transition: "all 0.15s",
                            }}>
                                <div style={{ width: 34, height: 34, borderRadius: "50%", background: `${t.primary}18`, border: `1.5px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700, color: t.primary }}>{l.avatar}</div>
                                <div style={{ flex: 1 }}>
                                    <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{l.name}</div>
                                    <div style={{ fontSize: 11, color: t.textMuted, textTransform: "capitalize" }}>{l.spec}</div>
                                </div>
                                {counterparty?._id === l._id && <span style={{ color: t.primary, fontWeight: 800, fontSize: 14 }}>✓</span>}
                            </div>
                        ))}
                        {!cpLoading && !cpList.length && (
                            <div style={{ padding: "28px 0", textAlign: "center", color: t.textMuted, fontSize: 13 }}>
                                No verified lawyers available yet — counterparties must be registered users.
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* ── STEP 2: Your Signature ── */}
            {step === 2 && (
                <div style={{ maxWidth: 780 }}>

                    {/* ── Top info row ── */}
                    <div style={{
                        display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 22,
                    }}>
                        {/* Creator info card */}
                        <div style={{
                            display: "flex", alignItems: "flex-start", gap: 14, padding: "16px 18px",
                            borderRadius: 14, background: t.primaryGlow2,
                            border: `1.5px solid ${t.primary}30`,
                        }}>
                            <div style={{
                                width: 40, height: 40, borderRadius: 12, background: t.primaryGlow,
                                border: `1.5px solid ${t.primary}50`,
                                display: "flex", alignItems: "center", justifyContent: "center",
                                fontSize: 20, flexShrink: 0,
                            }}>✍️</div>
                            <div>
                                <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 4 }}>
                                    Sign as creator
                                </div>
                                <div style={{ fontSize: 11.5, color: t.textMuted, lineHeight: 1.6 }}>
                                    Your signature is applied first, then{" "}
                                    <span style={{ color: t.primary, fontWeight: 700 }}>{counterparty?.name || "the counterparty"}</span>{" "}
                                    is asked to counter-sign.
                                </div>
                            </div>
                        </div>

                        {/* Security card */}
                        <div style={{
                            display: "flex", alignItems: "flex-start", gap: 14, padding: "16px 18px",
                            borderRadius: 14, background: `${t.success}0D`,
                            border: `1.5px solid ${t.success}30`,
                        }}>
                            <div style={{
                                width: 40, height: 40, borderRadius: 12,
                                background: `${t.success}18`, border: `1.5px solid ${t.success}40`,
                                display: "flex", alignItems: "center", justifyContent: "center",
                                fontSize: 20, flexShrink: 0,
                            }}>🔒</div>
                            <div>
                                <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 4 }}>
                                    Legally binding
                                </div>
                                <div style={{ fontSize: 11.5, color: t.textMuted, lineHeight: 1.6 }}>
                                    AES-256 encrypted · Timestamped · Compliant with e-signature laws.
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* ── Full name ── */}
                    <div style={{ marginBottom: 20 }}>
                        <div style={{
                            fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase",
                            letterSpacing: "0.8px", marginBottom: 8,
                        }}>Your Full Name</div>
                        <div style={{ position: "relative" }}>
                            <span style={{
                                position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)",
                                fontSize: 16, pointerEvents: "none",
                            }}>👤</span>
                            <Input
                                placeholder="Enter your full name..."
                                value={fullName}
                                onChange={e => setFullName(e.target.value)}
                                style={{ fontSize: 14, padding: "13px 16px 13px 42px" }}
                            />
                        </div>
                    </div>

                    {/* ── Signature card ── */}
                    <div style={{
                        borderRadius: 18, overflow: "hidden",
                        border: `1.5px solid ${hasSig ? t.primary : t.border}`,
                        background: t.card,
                        boxShadow: hasSig ? `0 0 0 3px ${t.primaryGlow2}` : "none",
                        transition: "all 0.3s",
                    }}>

                        {/* Card header */}
                        <div style={{
                            display: "flex", alignItems: "center", justifyContent: "space-between",
                            padding: "14px 18px", borderBottom: `1px solid ${t.border}`,
                            background: t.surface,
                        }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                                <div style={{
                                    width: 32, height: 32, borderRadius: 9, background: t.primaryGlow,
                                    display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15,
                                }}>✍️</div>
                                <div>
                                    <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>Your Signature</div>
                                    <div style={{ fontSize: 10, color: t.textMuted }}>
                                        {hasSig ? "✓ Signature captured" : "Draw or type below"}
                                    </div>
                                </div>
                            </div>

                            {/* Mode tabs + clear */}
                            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                <div style={{
                                    display: "flex", background: t.inputBg,
                                    border: `1px solid ${t.border}`, borderRadius: 10, padding: 3, gap: 2,
                                }}>
                                    {[["draw", "✏️", "Draw"], ["type", "Aa", "Type"], ["upload", "📎", "Upload"]].map(([mode, ico, lbl]) => (
                                        <button key={mode} onClick={() => { setSigMode(mode); clearSig(); }} style={{
                                            display: "flex", alignItems: "center", gap: 5,
                                            padding: "6px 12px", borderRadius: 8, fontSize: 12,
                                            fontWeight: sigMode === mode ? 700 : 500,
                                            border: "none",
                                            background: sigMode === mode ? t.primary : "transparent",
                                            color: sigMode === mode ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.textMuted,
                                            cursor: "pointer", fontFamily: "'Inter',sans-serif",
                                            transition: "all 0.2s",
                                        }}>
                                            <span style={{ fontSize: 13 }}>{ico}</span>{lbl}
                                        </button>
                                    ))}
                                </div>
                                <button onClick={clearSig} style={{
                                    display: "flex", alignItems: "center", gap: 5,
                                    padding: "7px 13px", borderRadius: 9, fontSize: 12,
                                    border: `1px solid ${t.border}`, background: "transparent",
                                    color: t.textMuted, cursor: "pointer", fontFamily: "'Inter',sans-serif",
                                    transition: "all 0.15s",
                                }}
                                    onMouseEnter={e => { e.currentTarget.style.borderColor = t.danger; e.currentTarget.style.color = t.danger; }}
                                    onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textMuted; }}
                                >↺ Clear</button>
                            </div>
                        </div>

                        {/* Draw canvas */}
                        {sigMode === "draw" && (
                            <div style={{ position: "relative", background: t.inputBg }}>
                                {/* Grid lines for feel */}
                                <div style={{
                                    position: "absolute", inset: 0, pointerEvents: "none",
                                    backgroundImage: `linear-gradient(${t.border}44 1px, transparent 1px)`,
                                    backgroundSize: "100% 40px",
                                    opacity: 0.5,
                                }} />
                                {/* Baseline */}
                                <div style={{
                                    position: "absolute", left: 24, right: 24, bottom: 52,
                                    height: 1, background: `${t.primary}40`,
                                    pointerEvents: "none",
                                }} />
                                <canvas
                                    ref={canvasRef}
                                    width={760} height={200}
                                    onMouseDown={startDraw} onMouseMove={draw}
                                    onMouseUp={stopDraw} onMouseLeave={stopDraw}
                                    onTouchStart={startDraw} onTouchMove={draw} onTouchEnd={stopDraw}
                                    style={{
                                        display: "block", width: "100%", height: 200,
                                        cursor: "crosshair", touchAction: "none",
                                        position: "relative", zIndex: 1,
                                    }}
                                />
                                {!hasSig && (
                                    <div style={{
                                        position: "absolute", inset: 0, zIndex: 2,
                                        display: "flex", flexDirection: "column",
                                        alignItems: "center", justifyContent: "center",
                                        pointerEvents: "none", gap: 8,
                                    }}>
                                        <div style={{ fontSize: 28, opacity: 0.25 }}>✍️</div>
                                        <div style={{ fontSize: 13, color: t.textFaint, fontWeight: 500 }}>
                                            Draw your signature here
                                        </div>
                                        <div style={{ fontSize: 11, color: t.textFaint, opacity: 0.7 }}>
                                            Use your mouse or touch
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Type mode */}
                        {sigMode === "type" && (
                            <div style={{ position: "relative", background: t.inputBg }}>
                                <div style={{
                                    position: "absolute", left: 24, right: 24, bottom: 52,
                                    height: 1, background: `${t.primary}40`, pointerEvents: "none",
                                }} />
                                <input
                                    value={typedSig}
                                    onChange={e => { setTypedSig(e.target.value); setHasSig(!!e.target.value); }}
                                    placeholder="Type your name..."
                                    style={{
                                        display: "block", width: "100%", height: 200,
                                        background: "transparent", border: "none", outline: "none",
                                        color: t.primary, fontSize: 42, textAlign: "center",
                                        fontFamily: "'Brush Script MT','Segoe Script',cursive",
                                        padding: "20px 24px", boxSizing: "border-box",
                                    }}
                                />
                                {!typedSig && (
                                    <div style={{
                                        position: "absolute", inset: 0, display: "flex", alignItems: "center",
                                        justifyContent: "center", pointerEvents: "none",
                                        fontSize: 13, color: t.textFaint,
                                    }}>Type your signature...</div>
                                )}
                            </div>
                        )}

                        {/* Upload mode */}
                        {sigMode === "upload" && (
                            <div style={{
                                minHeight: 200, background: t.inputBg,
                                display: "flex", alignItems: "center", justifyContent: "center",
                            }}>
                                {uploadedSig ? (
                                    /* Preview uploaded image */
                                    <div style={{ position: "relative", width: "100%", padding: "16px 24px", textAlign: "center" }}>
                                        <img
                                            src={uploadedSig} alt="Uploaded signature"
                                            style={{
                                                maxHeight: 140, maxWidth: "100%", objectFit: "contain",
                                                borderRadius: 8, filter: t.mode === "dark" ? "invert(1) brightness(1.5)" : "none",
                                            }}
                                        />
                                        <div style={{
                                            marginTop: 10, fontSize: 11, color: t.success,
                                            display: "flex", alignItems: "center", justifyContent: "center", gap: 5,
                                        }}>
                                            <span>✓</span> Signature image uploaded
                                        </div>
                                    </div>
                                ) : (
                                    /* Drop zone */
                                    <label style={{
                                        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
                                        gap: 12, width: "100%", height: 200, cursor: "pointer",
                                    }}>
                                        <input
                                            type="file" accept="image/*" style={{ display: "none" }}
                                            onChange={e => {
                                                const file = e.target.files?.[0];
                                                if (!file) return;
                                                const reader = new FileReader();
                                                reader.onload = ev => {
                                                    setUploadedSig(ev.target.result);
                                                    setHasSig(true);
                                                };
                                                reader.readAsDataURL(file);
                                            }}
                                        />
                                        <div style={{
                                            width: 56, height: 56, borderRadius: 16,
                                            background: t.primaryGlow, border: `1.5px dashed ${t.primary}`,
                                            display: "flex", alignItems: "center", justifyContent: "center", fontSize: 24,
                                        }}>📎</div>
                                        <div style={{ textAlign: "center" }}>
                                            <div style={{ fontSize: 14, fontWeight: 600, color: t.text, marginBottom: 4 }}>
                                                Upload signature image
                                            </div>
                                            <div style={{ fontSize: 12, color: t.textMuted }}>
                                                PNG, JPG or SVG · Max 2MB
                                            </div>
                                        </div>
                                        <div style={{
                                            padding: "9px 22px", borderRadius: 10, fontSize: 12, fontWeight: 700,
                                            background: t.primaryGlow, border: `1.5px solid ${t.primary}`,
                                            color: t.primary, transition: "all 0.15s",
                                        }}>Browse Files</div>
                                    </label>
                                )}
                            </div>
                        )}

                        {/* Footer strip */}
                        <div style={{
                            padding: "10px 18px",
                            borderTop: `1px solid ${t.border}`,
                            display: "flex", alignItems: "center", justifyContent: "space-between",
                            background: t.surface,
                        }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: t.textMuted }}>
                                <span>🔒</span>
                                <span>Encrypted & timestamped on submission</span>
                            </div>
                            {hasSig && (
                                <div style={{
                                    display: "flex", alignItems: "center", gap: 6,
                                    fontSize: 11, fontWeight: 700, color: t.success,
                                }}>
                                    <span>✓</span> Signature ready
                                </div>
                            )}
                        </div>
                    </div>

                </div>
            )}

            {/* ── STEP 3: Review & Send ── */}
            {step === 3 && (
                <div>
                    <Card style={{ padding: 0, overflow: "hidden", marginBottom: 16 }}>
                        <div style={{
                            display: "flex", alignItems: "center", gap: 10, padding: "14px 20px",
                            borderBottom: `1px solid ${t.border}`, background: t.surface
                        }}>
                            <span style={{ fontSize: 16 }}>📄</span>
                            <span style={{ fontSize: 14, fontWeight: 700, color: t.text }}>{title}</span>
                        </div>
                        <div style={{
                            padding: "20px 24px", fontSize: 13.5, lineHeight: 1.85, color: t.text,
                            fontFamily: "Georgia, 'Times New Roman', serif", maxHeight: 420, overflowY: "auto",
                            whiteSpace: "pre-wrap"
                        }}>
                            {body || "(No content)"}
                        </div>
                    </Card>

                    {/* Signing order */}
                    <Card style={{ marginBottom: 16 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
                            <span style={{ fontSize: 16 }}>👥</span>
                            <span style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Signing Order</span>
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                            {/* You — already signed */}
                            <div style={{ display: "flex", gap: 16, paddingBottom: 16 }}>
                                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0 }}>
                                    <div style={{
                                        width: 28, height: 28, borderRadius: "50%", background: t.success,
                                        display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12,
                                        color: "#1A2E35", fontWeight: 700, flexShrink: 0
                                    }}>✓</div>
                                    <div style={{ width: 2, flex: 1, background: t.border, marginTop: 4 }} />
                                </div>
                                <div style={{ flex: 1 }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                                        <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{fullName || "You"}</span>
                                        <span style={{
                                            fontSize: 10, fontWeight: 700, color: t.success, background: "rgba(77,212,163,0.15)",
                                            border: "1px solid rgba(77,212,163,0.3)", borderRadius: 5, padding: "2px 7px"
                                        }}>SIGNED</span>
                                    </div>
                                    <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 8 }}>Creator · Signed just now</div>
                                    {hasSig && (
                                        <div style={{
                                            width: 140, height: 56, borderRadius: 8, background: t.inputBg,
                                            border: `1px solid ${t.border}`, display: "flex", alignItems: "center",
                                            justifyContent: "center", overflow: "hidden"
                                        }}>
                                            <canvas ref={r => {
                                                if (r && canvasRef.current) {
                                                    const ctx = r.getContext("2d");
                                                    ctx.drawImage(canvasRef.current, 0, 0, r.width, r.height);
                                                }
                                            }} width={140} height={56} style={{ width: 140, height: 56 }} />
                                        </div>
                                    )}
                                </div>
                            </div>
                            <div style={{ display: "flex", gap: 16 }}>
                                <div style={{
                                    width: 28, height: 28, borderRadius: "50%", background: t.warn + "30",
                                    border: `2px solid ${t.warn}`, display: "flex", alignItems: "center", justifyContent: "center",
                                    fontSize: 12, color: t.warn, flexShrink: 0
                                }}>⏰</div>
                                <div style={{ flex: 1, paddingTop: 4 }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                                        <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{counterparty?.name || "Counterparty"}</span>
                                        <span style={{
                                            fontSize: 10, fontWeight: 700, color: t.info, background: "rgba(90,179,255,0.12)",
                                            border: "1px solid rgba(90,179,255,0.25)", borderRadius: 5, padding: "2px 7px"
                                        }}>IN-APP</span>
                                    </div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>
                                        Notified immediately · counter-signs from their Agreements page
                                    </div>
                                </div>
                            </div>
                        </div>
                    </Card>

                    {/* Security notice */}
                    <Card style={{ background: t.primaryGlow2, borderColor: `${t.primary}30`, marginBottom: 16 }}>
                        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                            <span style={{ fontSize: 18 }}>🛡️</span>
                            <div>
                                <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>Secure & Legally Binding</div>
                                <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>
                                    All signatures are encrypted with AES-256, timestamped, and comply with e-signature laws.
                                </div>
                            </div>
                        </div>
                    </Card>
                </div>
            )}

            {/* Bottom nav */}
            <div style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                marginTop: 24, paddingTop: 20, borderTop: `1px solid ${t.border}`
            }}>
                <Btn outline onClick={() => step > 0 ? nav(step - 1) : onNavigate("templates")}
                    style={{ padding: "11px 20px" }}>
                    ← {step === 0 ? "Back" : "Back"}
                </Btn>
                <span style={{ fontSize: 12, color: t.textMuted }}>Step {step + 1} of {STEPS.length}</span>
                {step < 3
                    ? <Btn primary onClick={() => nav(step + 1)} style={{ padding: "11px 24px" }}>Next →</Btn>
                    : <Btn primary disabled={submitting} onClick={async () => {
                        if (!user?._id) { toast.show("⚠️ Please log in first", "warn"); return; }
                        if (!counterparty?._id) { toast.show("⚠️ Select a counterparty (Step 2) — an agreement needs two parties", "warn"); return; }
                        const sigData = sigMode === "draw"
                            ? (canvasRef.current?.toDataURL() || "")
                            : sigMode === "type" ? typedSig
                            : (uploadedSig || "");
                        if (!sigData) { toast.show("⚠️ Please add your signature first", "warn"); return; }
                        setSubmitting(true);
                        try {
                            const createRes = await createAgreement(
                                title,
                                body,
                                [
                                    { user_id: user._id, full_name: fullName || user.full_name || "User" },
                                    { user_id: counterparty._id, full_name: counterparty.name },
                                ]
                            );
                            if (createRes.error) {
                                toast.show("❌ " + (createRes.error?.detail || "Failed to create agreement"), "danger");
                                setSubmitting(false); return;
                            }
                            const agreementId = createRes.data?._id;
                            const signRes = await signAgreement(agreementId, SIG_METHOD_MAP[sigMode], sigData);
                            if (signRes.error) {
                                toast.show("❌ " + (signRes.error?.detail || "Failed to sign"), "danger");
                                setSubmitting(false); return;
                            }
                            toast.show(`✅ Signed & sent — awaiting ${counterparty.name}'s signature`, "success", 4000);
                            onDone();
                        } catch {
                            toast.show("❌ Network error — check backend", "danger");
                        } finally {
                            setSubmitting(false);
                        }
                    }} style={{ padding: "11px 24px" }}>
                        {submitting ? "⏳ Sending…" : "✈️ Sign & Send"}
                    </Btn>
                }
            </div>
        </div>
    );
};

// ── PAGE: ALL AGREEMENTS ─────────────────────
const PageAllAgreements = ({ onNavigate }) => {
    const t = useTheme();
    const toast = useToast();
    const { user } = useAuth();
    const [agmts, loading, reload] = useMyAgreements(user?._id);
    const [search, setSearch] = useState("");
    const [filter, setFilter] = useState("All");
    const [viewing, setViewing] = useState(null);       // mapped agreement being viewed
    const [signName, setSignName] = useState("");
    const [signBusy, setSignBusy] = useState(false);
    const filters = ["All", "Signed", "Pending", "Rejected", "Draft"];
    const filtered = agmts.filter(a =>
        (filter === "All" || a.status === filter) &&
        a.name.toLowerCase().includes(search.toLowerCase())
    );

    const doSign = async () => {
        if (!signName.trim()) { toast.show("⚠️ Type your full name to sign", "warn"); return; }
        setSignBusy(true);
        const { data, error } = await signAgreement(viewing.id, "typed", signName.trim());
        setSignBusy(false);
        if (error) { toast.show("❌ " + (error.message || "Failed to sign"), "danger"); return; }
        toast.show(data?.status === "executed" ? "🎉 Agreement fully executed!" : "✅ Signed — awaiting the other party", "success", 4000);
        setViewing(null);
        setSignName("");
        reload();
    };
    return (
        <div>
            <div style={{ marginBottom: 24 }}>
                <h1 style={{ fontSize: 28, fontWeight: 800, color: t.text, margin: 0, fontFamily: "'Sora','Inter',sans-serif" }}>All Agreements</h1>
                <p style={{ fontSize: 13, color: t.textMuted, margin: "4px 0 0" }}>View and manage all your agreements</p>
            </div>

            {/* Search */}
            <div style={{ position: "relative", marginBottom: 16 }}>
                <span style={{ position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)", fontSize: 14, color: t.textMuted }}>🔍</span>
                <Input placeholder="Search agreements..." value={search} onChange={e => setSearch(e.target.value)}
                    style={{ paddingLeft: 40, fontSize: 14, padding: "13px 14px 13px 40px" }} />
            </div>

            {/* Filter pills */}
            <div style={{ display: "flex", gap: 8, marginBottom: 20, flexWrap: "wrap" }}>
                {filters.map(f => (
                    <button key={f} onClick={() => setFilter(f)} style={{
                        padding: "8px 18px", borderRadius: 50, fontSize: 13, fontWeight: filter === f ? 700 : 500,
                        cursor: "pointer", fontFamily: "'Inter',sans-serif", transition: "all 0.15s",
                        border: `1.5px solid ${filter === f ? t.primary : t.border}`,
                        background: filter === f ? t.primaryGlow : "transparent",
                        color: filter === f ? t.primary : t.textMuted,
                    }}>{f}</button>
                ))}
            </div>

            {/* Table */}
            <Card style={{ padding: 0, overflow: "hidden" }}>
                {/* Header */}
                <div style={{
                    display: "grid", gridTemplateColumns: "2fr 1fr 80px 120px 100px",
                    padding: "10px 20px", borderBottom: `1px solid ${t.border}`, background: t.surface
                }}>
                    {["AGREEMENT", "WITH", "SIGNED", "STATUS", "ACTIONS"].map(h => (
                        <div key={h} style={{
                            fontSize: 10, fontWeight: 700, color: t.textMuted,
                            letterSpacing: "0.7px", textTransform: "uppercase"
                        }}>{h}</div>
                    ))}
                </div>
                {filtered.map((a, i) => (
                    <div key={a.id} onClick={() => { setViewing(a); setSignName(user?.full_name || ""); }} style={{
                        display: "grid", gridTemplateColumns: "2fr 1fr 80px 120px 100px",
                        alignItems: "center", padding: "16px 20px",
                        borderBottom: i < filtered.length - 1 ? `1px solid ${t.border}` : "none",
                        transition: "background 0.15s", cursor: "pointer",
                    }}
                        onMouseEnter={e => e.currentTarget.style.background = t.cardHi}
                        onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                    >
                        <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                            <div style={{
                                width: 36, height: 36, borderRadius: 10, background: t.primaryGlow,
                                display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, flexShrink: 0
                            }}>{a.isEngagementLetter ? "⚖️" : "📄"}</div>
                            <div style={{ minWidth: 0 }}>
                                <div style={{ fontSize: 13, fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</div>
                                <div style={{ fontSize: 11, color: t.textMuted, marginTop: 1 }}>
                                    {a.date}{a.needsMySig && <span style={{ color: t.warn, fontWeight: 700 }}> · your signature needed</span>}
                                </div>
                            </div>
                        </div>
                        <div style={{ fontSize: 12, color: t.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.counterparts || "—"}</div>
                        <div style={{ fontSize: 13, color: t.textMuted, paddingLeft: 10 }}>{a.signedCount}/{a.totalParties}</div>
                        <StatusBadge status={a.status} />
                        <div style={{ display: "flex", gap: 6 }}>
                            {a.needsMySig ? (
                                <Btn primary style={{ fontSize: 11, padding: "7px 14px" }}
                                    onClick={e => { e.stopPropagation(); setViewing(a); setSignName(user?.full_name || ""); }}>
                                    ✍️ Sign
                                </Btn>
                            ) : (
                                <button onClick={e => { e.stopPropagation(); setViewing(a); }} style={{
                                    width: 30, height: 30, borderRadius: 8, border: `1px solid ${t.border}`,
                                    background: t.inputBg, color: t.textMuted, cursor: "pointer", fontSize: 13,
                                    display: "flex", alignItems: "center", justifyContent: "center",
                                }}>👁</button>
                            )}
                        </div>
                    </div>
                ))}
                {loading ? (
                    <div style={{ padding: "40px 20px", textAlign: "center", color: t.textMuted, fontSize: 13 }}>Loading agreements…</div>
                ) : filtered.length === 0 && (
                    <div style={{ padding: "40px 20px", textAlign: "center", color: t.textMuted, fontSize: 13 }}>
                        No agreements found.
                    </div>
                )}
            </Card>

            {/* View / Sign modal */}
            {viewing && (
                <div onClick={() => setViewing(null)} style={{
                    position: "fixed", inset: 0, zIndex: 9999, background: "rgba(0,0,0,0.65)",
                    backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20,
                }}>
                    <div onClick={e => e.stopPropagation()} style={{
                        background: t.card, borderRadius: 20, border: `1.5px solid ${t.border}`,
                        width: "100%", maxWidth: 640, maxHeight: "88vh", display: "flex", flexDirection: "column",
                        boxShadow: "0 24px 64px rgba(0,0,0,0.4)", overflow: "hidden",
                    }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "18px 22px", borderBottom: `1px solid ${t.border}` }}>
                            <span style={{ fontSize: 20 }}>{viewing.isEngagementLetter ? "⚖️" : "📄"}</span>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 15, fontWeight: 800, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{viewing.name}</div>
                                <div style={{ fontSize: 11, color: t.textMuted }}>{viewing.eto || "Awaiting first signature"}</div>
                            </div>
                            <StatusBadge status={viewing.status} />
                            <button onClick={() => setViewing(null)} style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 8, width: 30, height: 30, cursor: "pointer", color: t.textMuted, fontSize: 15 }}>✕</button>
                        </div>

                        <div style={{ flex: 1, overflowY: "auto", padding: "18px 22px" }}>
                            {/* Parties */}
                            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 16 }}>
                                {viewing.parties.map(p => (
                                    <div key={p.user_id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 12px", borderRadius: 10, background: p.signed ? `${t.success}12` : t.inputBg, border: `1px solid ${p.signed ? t.success + "40" : t.border}` }}>
                                        <span style={{ fontSize: 12 }}>{p.signed ? "✅" : "⏰"}</span>
                                        <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>{p.full_name}</span>
                                        <span style={{ fontSize: 10, color: p.signed ? t.success : t.textMuted }}>
                                            {p.signed ? `signed ${p.signed_at ? new Date(p.signed_at).toLocaleDateString() : ""}` : "pending"}
                                        </span>
                                    </div>
                                ))}
                            </div>
                            {/* Body */}
                            <div style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 12, padding: "18px 20px", fontSize: 13, lineHeight: 1.85, color: t.text, whiteSpace: "pre-wrap", fontFamily: "Georgia,serif" }}>
                                {viewing.body || "No content."}
                            </div>
                        </div>

                        {viewing.needsMySig && (
                            <div style={{ padding: "14px 22px", borderTop: `1px solid ${t.border}`, background: t.surface }}>
                                <div style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.7px", marginBottom: 8 }}>
                                    Sign — type your full legal name
                                </div>
                                <div style={{ display: "flex", gap: 10 }}>
                                    <Input placeholder="Your full name" value={signName} onChange={e => setSignName(e.target.value)} style={{ flex: 1 }} />
                                    <Btn primary disabled={signBusy} onClick={doSign} style={{ padding: "11px 22px", flexShrink: 0 }}>
                                        {signBusy ? "Signing…" : "✍️ Sign Agreement"}
                                    </Btn>
                                </div>
                                <div style={{ fontSize: 10.5, color: t.textMuted, marginTop: 8, lineHeight: 1.5 }}>
                                    Your typed signature is recorded with a timestamp and classified under the Electronic Transactions Ordinance 2002.
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};

// ── SIDEBAR NAV ICONS ────────────────────────
const AgmtIc = ({ name, s = 18, c = "currentColor" }) => {
    const icons = {
        dashboard: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></svg>,
        templates: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14,2 14,8 20,8" /><line x1="8" y1="13" x2="16" y2="13" /><line x1="8" y1="17" x2="13" y2="17" /></svg>,
        create: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><path d="M12 20h9M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4z" /></svg>,
        all: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" /></svg>,
    };
    return icons[name] || null;
};

// ── SIDEBAR NAV ──────────────────────────────
const Sidebar = ({ page, onNavigate, collapsed }) => {
    const t = useTheme();
    const links = [
        { id: "dashboard", ico: "dashboard", label: "Dashboard" },
        { id: "templates", ico: "templates", label: "Templates" },
        { id: "create", ico: "create", label: "Create" },
        { id: "all", ico: "all", label: "All Agreements" },
    ];
    return (
        <div style={{
            width: collapsed ? 64 : 230, flexShrink: 0,
            background: t.surface,
            borderRight: `1px solid ${t.border}`, display: "flex", flexDirection: "column",
            transition: "width 0.25s cubic-bezier(0.4,0,0.2,1)", overflow: "hidden",
            height: "100%",
        }}>
            {/* Brand */}
            <div style={{
                padding: collapsed ? "18px 0" : "18px 20px",
                borderBottom: `1px solid ${t.border}`,
                display: "flex", alignItems: "center",
                justifyContent: collapsed ? "center" : "flex-start",
                gap: 10, flexShrink: 0,
            }}>
                <div style={{
                    width: 32, height: 32, borderRadius: 10,
                    background: `linear-gradient(135deg, ${t.primary}, ${t.primaryDim})`,
                    display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                    boxShadow: `0 4px 12px ${t.primaryGlow}`,
                }}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={t.mode === "dark" ? "#1A2E35" : "#fff"} strokeWidth="2.5">
                        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                    </svg>
                </div>
                {!collapsed && (
                    <span style={{
                        fontSize: 15, fontWeight: 800, color: t.text,
                        fontFamily: "'Sora','Inter',sans-serif", letterSpacing: "-0.3px",
                        whiteSpace: "nowrap",
                    }}>Agreement<span style={{ color: t.primary }}>Hub</span></span>
                )}
            </div>

            {/* Nav links */}
            <div style={{ padding: "10px 10px", flex: 1, overflow: "auto" }}>
                {links.map(l => {
                    const active = page === l.id || (page === "create" && l.id === "create");
                    return (
                        <div key={l.id} onClick={() => onNavigate(l.id)} style={{
                            display: "flex", alignItems: "center",
                            gap: collapsed ? 0 : 12,
                            justifyContent: collapsed ? "center" : "flex-start",
                            padding: collapsed ? "13px 0" : "12px 14px",
                            borderRadius: 12, marginBottom: 4, cursor: "pointer",
                            transition: "all 0.2s cubic-bezier(0.4,0,0.2,1)",
                            background: active ? t.primaryGlow : "transparent",
                            color: active ? t.primary : t.textMuted,
                            position: "relative",
                        }}
                            onMouseEnter={e => { if (!active) { e.currentTarget.style.background = t.inputBg; e.currentTarget.style.color = t.text; } }}
                            onMouseLeave={e => { if (!active) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = t.textMuted; } }}
                        >
                            <AgmtIc name={l.ico} s={18} c={active ? t.primary : "currentColor"} />
                            {!collapsed && (
                                <span style={{
                                    fontSize: 13, fontWeight: active ? 700 : 500,
                                    whiteSpace: "nowrap", flex: 1,
                                }}>{l.label}</span>
                            )}
                            {active && !collapsed && (
                                <div style={{ width: 7, height: 7, borderRadius: "50%", background: t.primary, boxShadow: `0 0 8px ${t.primaryGlow}`, flexShrink: 0 }} />
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

// ── ModAgreements ─────────────────────────────
function ModAgreements() {
    const t = useTheme();
    const [page, setPage] = useState("dashboard");
    const [selectedTemplate, setSelectedTemplate] = useState(null);
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

    const navigate = (p) => setPage(p);

    return (
        <div style={{
            display: "flex", height: "100%", background: t.bg, fontFamily: "'Inter',sans-serif",
            color: t.text, overflow: "hidden",
        }}>
            {/* Sidebar */}
            <Sidebar page={page} onNavigate={navigate} collapsed={sidebarCollapsed} />

            {/* Main area */}
            <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
                {/* Top bar */}
                <div style={{
                    height: 52, flexShrink: 0, background: t.surface, borderBottom: `1px solid ${t.border}`,
                    display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 20px",
                }}>
                    <button onClick={() => setSidebarCollapsed(!sidebarCollapsed)} style={{
                        width: 32, height: 32, borderRadius: 8, border: `1px solid ${t.border}`,
                        background: "transparent", color: t.textMuted, cursor: "pointer", fontSize: 14,
                        display: "flex", alignItems: "center", justifyContent: "center",
                    }}>☰</button>
                    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <button style={{
                            width: 32, height: 32, borderRadius: 8, border: "none",
                            background: "transparent", color: t.textMuted, cursor: "pointer", fontSize: 16
                        }}>🔍</button>
                        <button style={{
                            width: 32, height: 32, borderRadius: 8, border: "none",
                            background: "transparent", color: t.textMuted, cursor: "pointer", fontSize: 16, position: "relative"
                        }}>
                            🔔
                            <span style={{
                                position: "absolute", top: 4, right: 4, width: 8, height: 8,
                                borderRadius: "50%", background: t.primary, border: `2px solid ${t.surface}`
                            }} />
                        </button>
                        <div style={{
                            width: 34, height: 34, borderRadius: "50%", background: t.grad1,
                            display: "flex", alignItems: "center", justifyContent: "center",
                            fontSize: 13, fontWeight: 700, color: "#1A2E35", cursor: "pointer"
                        }}>JD</div>
                    </div>
                </div>

                {/* Page content */}
                <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
                    {page === "dashboard" && <PageDashboard onNavigate={navigate} />}
                    {page === "templates" && (
                        <PageTemplates onNavigate={navigate} onSelectTemplate={t => setSelectedTemplate(t)} />
                    )}
                    {page === "create" && (
                        <PageCreate template={selectedTemplate} onNavigate={navigate} onDone={() => navigate("all")} />
                    )}
                    {page === "all" && <PageAllAgreements onNavigate={navigate} />}
                </div>
            </div>
        </div>
    );
}

export default ModAgreements;

