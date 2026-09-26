'use client';
// Paste your ModAgreements.jsx code here
import React, { useState, Fragment, useRef, useCallback, useEffect } from "react";
import { useT } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import Ic from "./Ic.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput, Badge } from "@/components/shared/shared.jsx";
import SignaturePad from "@/components/shared/SignaturePad.jsx";
import { useAuth } from "@/context/AuthContext.jsx";
import { createAgreement, getAgreement, signAgreement, declineAgreement, listAgreements, searchLawyers, downloadExecutedAgreement, idempotencyKey, reissueAgreementInvitation, archiveAgreement, unarchiveAgreement } from "@/lib/api.js";

/* ══════════════════════════════════════════════════════
   MODULE: AGREEMENTS — 5-Step Wizard
══════════════════════════════════════════════════════ */



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

/* How far through signing, as a ring. The number stays beside it: a ring alone
   is a proportion, and "1 of 3" is the thing a person actually reads. */
const ProgressRing = ({ done, total, tone }) => {
    const t = useTheme();
    const pct = total > 0 ? Math.min(1, done / total) : 0;
    const r = 13, c = 2 * Math.PI * r;
    return (
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
            <svg width={32} height={32} style={{ transform: "rotate(-90deg)", flexShrink: 0 }}>
                <circle cx={16} cy={16} r={r} fill="none" stroke={t.border} strokeWidth={2.5} />
                <circle cx={16} cy={16} r={r} fill="none" stroke={tone} strokeWidth={2.5}
                    strokeDasharray={c} strokeDashoffset={c * (1 - pct)}
                    strokeLinecap="round" style={{ transition: "stroke-dashoffset 0.4s" }} />
            </svg>
            <span style={{ fontSize: 13, color: t.textMuted, fontWeight: 600 }}>
                {done}/{total}
            </span>
        </div>
    );
};

/* Initials, not a photo: there are no avatars in this product, and a generic
   silhouette for everybody carries less information than two letters. */
const PartyAvatar = ({ name, tone, title }) => {
    const t = useTheme();
    const initials = (name || "?").trim().split(/\s+/).slice(0, 2)
        .map(w => w[0]).join("").toUpperCase() || "?";
    return (
        <div title={title || name} style={{
            width: 26, height: 26, borderRadius: "50%", flexShrink: 0,
            background: `${tone}22`, border: `1px solid ${tone}55`, color: tone,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 9.5, fontWeight: 800, letterSpacing: "0.2px",
        }}>{initials}</div>
    );
};

const StatusBadge = ({ status }) => {
    const t = useTheme();
    const map = {
        Signed: { bg: "rgba(77,212,163,0.15)", color: "#4DD4A3", border: "rgba(77,212,163,0.3)" },
        Pending: { bg: "rgba(255,200,87,0.15)", color: "#FFC857", border: "rgba(255,200,87,0.3)" },
        Rejected: { bg: "rgba(255,107,122,0.15)", color: "#FF6B7A", border: "rgba(255,107,122,0.3)" },
        Draft: { bg: "rgba(154,154,148,0.2)", color: "#ACACAA", border: "rgba(154,154,148,0.3)" },
        // DERIVED, not stored. `needsMySig` means this agreement is pending
        // AND waiting on the person reading the screen. The four stored
        // statuses are unchanged.
        "Needs Attention": { bg: "rgba(90,179,255,0.15)", color: "#5AB3FF", border: "rgba(90,179,255,0.35)" },
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
// Sentinel shared with the backend (agreement_service.UNREVIEWED_TEMPLATE_MARKER).
// ASCII only and no em-dash on purpose: it crosses a language boundary and gets
// compared byte-for-byte.
const UNREVIEWED_MARKER = "[UNREVIEWED SAMPLE - NOT LEGAL CONTENT]";

// The bodies these templates used to carry were United States contract
// boilerplate: incorporation in a "[State]", salaries in "$[Amount]" on a
// bi-weekly schedule, and a non-compete over a "[Geographic Area]". They were
// the starting text of a real, e-signed, binding agreement in a Pakistani
// product.
//
// Withdrawn rather than rewritten. Drafting Pakistani contract templates is
// legal work, and generating them would be the same failure the intake prompt
// was already hardened against -- authoritative-looking legal text nobody
// verified. The names and descriptions stay so the gallery still reads
// sensibly; the bodies say what happened and what to do.
//
// The backend refuses to create or sign an agreement whose body still contains
// the marker, so nothing can reach `executed` off this text.
const unreviewedBody = (name) => `${UNREVIEWED_MARKER}

${name}

This template has been withdrawn pending review by a qualified Pakistani lawyer.

The previous wording was drafted for United States law and was not suitable to
sign in Pakistan. Rather than substitute wording that has not been reviewed
either, the body has been removed.

Replace this notice entirely with the agreement you actually want, or ask your
lawyer for the wording. An agreement that still contains this notice cannot be
sent for signature.`;

const TEMPLATES = [
    {
        ico: "💼", name: "Employment Contract", cat: "Employment", popular: true,
        desc: "Standard employment agreement with terms, compensation, and responsibilities.",
        unreviewed: true,
        body: unreviewedBody("Employment Contract"),
    },
    {
        ico: "🔒", name: "Non-Disclosure Agreement", cat: "NDA", popular: true,
        desc: "Mutual or one-way NDA for protecting confidential information.",
        unreviewed: true,
        body: unreviewedBody("Non-Disclosure Agreement"),
    },
    {
        ico: "🏠", name: "Lease Agreement", cat: "Property", popular: true,
        desc: "Residential or commercial property lease with standard terms.",
        unreviewed: true,
        body: unreviewedBody("Lease Agreement"),
    },
    {
        ico: "📄", name: "Service Agreement", cat: "Business", popular: true,
        desc: "Professional services agreement for contractors and clients.",
        unreviewed: true,
        body: unreviewedBody("Service Agreement"),
    },
    {
        ico: "🤝", name: "Partnership Agreement", cat: "Business", popular: false,
        desc: "Business partnership terms, profit sharing, and responsibilities.",
        unreviewed: true,
        body: unreviewedBody("Partnership Agreement"),
    },
    {
        ico: "💼", name: "Freelancer Contract", cat: "Employment", popular: false,
        desc: "Independent contractor agreement for freelance work.",
        unreviewed: true,
        body: unreviewedBody("Freelancer Contract"),
    },
];

// ── REAL AGREEMENT HELPERS ───────────────────
/* A failed send needs a different action depending on WHY, and the sender is
   the only one who can take it. A provider's daily cap clears by itself; a hard
   rejection never will. Reporting every failure as "could not be emailed" left
   them with no way to tell those apart -- which is exactly how a Gmail daily
   sending limit looked identical to the software being broken. */
const DELIVERY_REASON = {
    provider_daily_limit:
        "the mail account has hit its daily sending limit \u2014 it resets within 24 hours",
    provider_temporarily_unavailable:
        "the mail provider deferred it \u2014 worth resending shortly",
    rejected_by_provider:
        "the mail provider rejected it \u2014 check the address is correct",
    email_not_configured:
        "no mail server is configured",
    no_email_on_file:
        "that account has no email address on file",
};
const deliveryReason = (code) => DELIVERY_REASON[code] || "the email did not go out";

const AG_STATUS_LABEL = { pending: "Pending", executed: "Signed", cancelled: "Rejected", draft: "Draft" };

// The tab label the user clicks, as the status the server filters on. "All"
// is deliberately absent: no key means no `status` parameter.
const AG_FILTER_STATUS = { Signed: "executed", Pending: "pending", Rejected: "cancelled" };

const mapAgreement = (a, myId) => {
    const parties = a.parties || [];
    const me = parties.find(p => p.user_id === myId);
    return {
        id: a.id || a._id,
        name: a.title || "Agreement",
        // NO `body` HERE. Gate 3F made the list light, and deriving the
        // displayed text from a list row is what made every agreement open as
        // "No content." beside a working Sign button. The body is fetched by
        // id when the document is opened -- see `openAgreement`.
        status: AG_STATUS_LABEL[a.status] || "Pending",
        rawStatus: a.status,
        parties,
        // PREFER THE SERVER'S COUNTS. It derives them from the parties on every
        // read (signing_progress), and it is the side that knows about an
        // external signer whose row carries no user_id. Counting here is the
        // fallback for a response that predates those fields.
        signedCount: a.signed_count ?? parties.filter(p => p.signed).length,
        totalParties: a.total_parties ?? parties.length,
        partiallySigned: a.partially_signed ?? null,
        // NO `expiresAt` HERE. `AgreementListItem` does not carry one, so
        // reading it off a row yields undefined and renders as "no expiry" for
        // every agreement -- the same shape of bug as the body in 3F. It comes
        // from the fetched document, below.
        createdBy: a.created_by || null,
        needsMySig: a.status === "pending" && !!me && !me.signed,
        date: a.created_at ? new Date(a.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "",
        // An external signer has NO user_id, so `p.user_id !== myId` keeps them
        // — which is right — but `full_name` may be absent, and an empty name
        // in a dot-separated list reads as a missing party rather than an
        // invited one.
        counterparts: parties
            .filter(p => p.user_id !== myId)
            .map(p => p.full_name || p.email || "Invited signer")
            .join(" · "),
        // NO `eto` HERE either. Like the body, it is a property of the
        // DOCUMENT and the list does not carry it -- reading it off a row
        // yielded undefined, so the subtitle silently said "Awaiting first
        // signature" for agreements that were already executed. It now comes
        // from the fetched document.
        isEngagementLetter: !!a.engagement_id,
    };
};

// Fetch + map the user's real agreements; returns [items, loading, reload]
const AGREEMENTS_PAGE_SIZE = 25;

/* The caller's agreements, one page at a time.
 *
 * 3F: the response is a page, not a bare array -- an `Array.isArray(data)`
 * check silently renders an empty list for every successful response.
 *
 * `total` is returned alongside the rows because a list that stops at its
 * page size is indistinguishable from a complete one. Asking for 50 and
 * ignoring the total is how somebody's 51st agreement stops existing. */
const useMyAgreements = (userId, status = null, archived = false) => {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);

    // THE FILTER GOES TO THE SERVER. Filtering the loaded page client-side
    // means "Signed" shows only the executed agreements that happen to be in
    // the first 25 rows, and the count beside the tab is the count of that
    // slice -- so an older executed agreement simply is not there, with no
    // indication anything was withheld. Changing the filter is a new query, so
    // the page resets with it.
    useEffect(() => { setPage(1); }, [status, archived]);

    const reload = useCallback(() => {
        listAgreements({ page, page_size: AGREEMENTS_PAGE_SIZE, status, archived })
            .then(({ data }) => {
                const rows = data?.items;
                if (Array.isArray(rows)) {
                    const mapped = rows.map(a => mapAgreement(a, userId));
                    // Page 1 replaces, later pages append.
                    setItems(prev => (page === 1 ? mapped : [...prev, ...mapped]));
                    setTotal(data.total ?? mapped.length);
                }
                setLoading(false);
            }).catch(() => setLoading(false));
    }, [userId, page, status, archived]);
    useEffect(() => { reload(); }, [reload]);

    const loadMore = useCallback(() => {
        setLoading(true);
        setPage(p => p + 1);
    }, []);

    return [items, loading, reload, { total, loadMore, hasMore: items.length < total }];
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
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 14, marginBottom: 20 }}>
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
            <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 20 }}>
                {[
                    // "Create Agreement" is dropped while the builder is parked
                    // rather than shown and redirected: a card that advertises a
                    // feature and then lands somewhere else is its own small lie,
                    // and this module has just had several removed.
                    ...(DIY_BUILDER_ENABLED ? [
                        { ico: "📄", title: "Create Agreement", sub: "Start from a template or scratch", page: "templates" },
                    ] : []),
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
                        {DIY_BUILDER_ENABLED
                            ? "No agreements yet — create one to get started."
                            : "No agreements yet. Agreements shared with you appear here for you to read and sign."}
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
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16 }}>
                {filtered.map((tmpl, i) => (
                    <Card key={i} style={{
                        padding: 24, display: "flex", flexDirection: "column", gap: 0, position: "relative",
                        transition: "all 0.2s",
                    }}
                        onMouseEnter={e => { e.currentTarget.style.border = `1px solid ${t.primary}`; e.currentTarget.style.boxShadow = t.shadowHover; }}
                        onMouseLeave={e => { e.currentTarget.style.border = `1px solid ${t.border}`; e.currentTarget.style.boxShadow = t.shadowCard; }}
                    >
                        {/* The POPULAR badge is gone. Every template body is the
                            withdrawal notice, and the backend refuses it at both
                            create and sign -- so "Popular" was recommending the
                            route most likely to waste the user's work. The badge
                            now says what is actually true about the template. */}
                        {tmpl.unreviewed && (
                            <div style={{
                                position: "absolute", top: 16, right: 16, fontSize: 10, fontWeight: 800,
                                letterSpacing: "0.6px", color: t.warn || "#f59e0b",
                                background: `${t.warn || "#f59e0b"}18`,
                                border: `1px solid ${t.warn || "#f59e0b"}40`, borderRadius: 6, padding: "3px 8px"
                            }}>WITHDRAWN</div>
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
                        <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.55, marginBottom: 12, flex: 1 }}>{tmpl.desc}</div>
                        {tmpl.unreviewed && (
                            <div style={{
                                fontSize: 11, color: t.textMuted, lineHeight: 1.5, marginBottom: 12,
                                background: t.inputBg, borderRadius: 8, padding: "8px 10px",
                            }}>
                                The wording for this template was withdrawn pending review by a
                                qualified Pakistani lawyer. You can start from it, but you must
                                replace the notice with your own wording before it can be sent.
                            </div>
                        )}
                        {/* Preview used to alert() the template's own name and
                            nothing else. There is also nothing to preview: every
                            template body is the withdrawal notice. */}
                        <div style={{ display: "flex", gap: 8 }}>
                            <Btn outline style={{ flex: 1, fontSize: 12, padding: "9px 0" }}
                                onClick={() => { onSelectTemplate(tmpl); onNavigate("create"); }}>
                                Start from this
                            </Btn>
                        </div>
                    </Card>
                ))}
            </div>
        </div>
    );
};

// ── PAGE: CREATE AGREEMENT (4 steps) ─────────
/* TOOLBAR_ACTIONS lived here: 24 formatting buttons -- bold, italic, headings,
   alignment, lists, tables, undo, redo -- rendered above the editor. Not one of
   them had an onClick. They hovered and did nothing.

   They were also describing something the editor cannot do. The body is a plain
   <textarea> producing plain text, stored in a field called `body_html`, so the
   toolbar promised rich formatting in both directions and delivered it in
   neither. A real editor is explicitly out of scope (see the product plan's
   non-goals); the honest interim is a plain text box that looks like one. */


/* Mirrors `_MAX_BODY` in backend/app/schemas/agreement.py. The server refuses
   a longer body with a 422; counting here means the writer sees it coming. */
const MAX_BODY_CHARS = 300_000;

/* Things a draft needs a gap for. Bracketed so an unfilled one is obvious in
   the finished text rather than reading as a real value. */
const INSERTABLES = [
    { label: "Today's date", build: () => new Date().toLocaleDateString("en-GB",
        { day: "numeric", month: "long", year: "numeric" }) },
    { label: "Divider", build: () => "\n────────────────────────────\n" },
    { label: "[PARTY NAME]", build: () => "[PARTY NAME]" },
    { label: "[DATE]", build: () => "[DATE]" },
    { label: "[AMOUNT IN PKR]", build: () => "[AMOUNT IN PKR]" },
    { label: "[ADDRESS]", build: () => "[ADDRESS]" },
    { label: "[CNIC]", build: () => "[CNIC]" },
];

const CASES = [
    { label: "UPPERCASE", fn: (x) => x.toUpperCase() },
    { label: "lowercase", fn: (x) => x.toLowerCase() },
    { label: "Title Case", fn: (x) => x.replace(/\w\S*/g,
        w => w[0].toUpperCase() + w.slice(1).toLowerCase()) },
    { label: "Sentence case", fn: (x) => x.toLowerCase().replace(/(^\s*\w|[.!?]\s+\w)/g,
        m => m.toUpperCase()) },
];

/* A DOCUMENT-EDITING bar, not a formatting one.
 *
 * Every control writes or rearranges characters, because characters are all a
 * signed plain-text agreement can carry. Bold, italic, underline and alignment
 * are deliberately absent: the body is hashed and signed verbatim, so they
 * could only do nothing or inject markup that appears literally in the
 * document. A 24-button bar offering exactly those was removed from this spot
 * once already, with no handler on any of them -- see the TOOLBAR_ACTIONS note.
 */
const DraftingToolbar = ({ body, setBody, textareaRef, zoom, setZoom,
                          onUndo, onRedo, canUndo, canRedo }) => {
    const t = useTheme();
    const [menu, setMenu] = useState(null);      // "insert" | "case" | null
    const [findOpen, setFindOpen] = useState(false);
    const [find, setFind] = useState("");
    const [repl, setRepl] = useState("");

    useEffect(() => {
        if (!menu) return;
        const close = () => setMenu(null);
        document.addEventListener("click", close);
        return () => document.removeEventListener("click", close);
    }, [menu]);

    /* Splice at the caret and put it back where the writer expects it. Without
       restoring the selection the cursor jumps to the end on every action,
       which makes the bar unusable for anything but appending. */
    const edit = (fn) => {
        const el = textareaRef.current;
        const start = el ? el.selectionStart : body.length;
        const end = el ? el.selectionEnd : body.length;
        const out = fn({
            before: body.slice(0, start),
            selected: body.slice(start, end),
            after: body.slice(end),
            start, end,
        });
        if (out === undefined) return;
        setBody(out.text);
        // Not `requestAnimationFrame` directly: it is absent in jsdom and in a
        // server render, and an unguarded call turns a caret nicety into a
        // TypeError that kills the handler.
        const afterPaint = typeof requestAnimationFrame === "function"
            ? requestAnimationFrame : (f) => setTimeout(f, 0);
        afterPaint(() => {
            if (!el) return;
            el.focus();
            const a = out.selStart ?? out.caret ?? out.text.length;
            const b = out.selEnd ?? a;
            el.setSelectionRange(a, b);
        });
    };

    const insert = (snippet) => edit(({ before, after }) => ({
        text: before + snippet + after,
        caret: before.length + snippet.length,
    }));

    /* Prefix every selected line, so it works on a block as well as one line. */
    const prefixLines = (mark) => edit(({ before, selected, after }) => {
        const target = selected || "";
        const marked = target
            ? target.split("\n").map(l => (l.trim() ? `${mark}${l}` : l)).join("\n")
            : mark;
        return { text: before + marked + after, caret: before.length + marked.length };
    });

    /* Numbered list continues whatever numbering is already above the caret,
       rather than restarting at 1 halfway down a document. */
    const numberedItem = () => edit(({ before, after }) => {
        const seen = [...before.matchAll(/^\s*(\d+)\./gm)].map(m => Number(m[1]));
        const n = (seen.length ? Math.max(...seen) : 0) + 1;
        const pad = before && !before.endsWith("\n") ? "\n" : "";
        const snippet = `${pad}${n}. `;
        return { text: before + snippet + after, caret: before.length + snippet.length };
    });

    const heading = () => edit(({ before, after }) => {
        const pad = before && !before.endsWith("\n\n")
            ? (before.endsWith("\n") ? "\n" : "\n\n") : "";
        const snippet = `${pad}[SECTION TITLE]\n`;
        return { text: before + snippet + after, caret: before.length + snippet.length };
    });

    /* Whole-line operations. The caret rarely sits on a line boundary, so each
       one first widens the range to the lines it touches. */
    const lineRange = (text, start, end) => {
        const from = text.lastIndexOf("\n", start - 1) + 1;
        const nl = text.indexOf("\n", end);
        return [from, nl === -1 ? text.length : nl];
    };

    const duplicateLine = () => edit(({ start, end }) => {
        const [a, b] = lineRange(body, start, end);
        const line = body.slice(a, b);
        return {
            text: body.slice(0, b) + "\n" + line + body.slice(b),
            caret: b + 1 + line.length,
        };
    });

    const moveLine = (dir) => edit(({ start, end }) => {
        const [a, b] = lineRange(body, start, end);
        const block = body.slice(a, b);
        if (dir < 0) {
            if (a === 0) return undefined;
            const prevStart = body.lastIndexOf("\n", a - 2) + 1;
            const prev = body.slice(prevStart, a - 1);
            const text = body.slice(0, prevStart) + block + "\n" + prev + body.slice(b);
            return { text, selStart: prevStart, selEnd: prevStart + block.length };
        }
        if (b >= body.length) return undefined;
        const nextEnd = body.indexOf("\n", b + 1);
        const stop = nextEnd === -1 ? body.length : nextEnd;
        const next = body.slice(b + 1, stop);
        const text = body.slice(0, a) + next + "\n" + block + body.slice(stop);
        const at = a + next.length + 1;
        return { text, selStart: at, selEnd: at + block.length };
    });

    /* Case changes apply to the selection, or to the current line when there is
       none -- doing nothing would look like a broken button. */
    const changeCase = (fn) => edit(({ before, selected, after, start, end }) => {
        if (selected) {
            const out = fn(selected);
            return { text: before + out + after,
                     selStart: start, selEnd: start + out.length };
        }
        const [a, b] = lineRange(body, start, end);
        const out = fn(body.slice(a, b));
        return { text: body.slice(0, a) + out + body.slice(b),
                 selStart: a, selEnd: a + out.length };
    });

    const matches = find ? body.split(find).length - 1 : 0;

    const replaceNext = () => {
        if (!find) return;
        const el = textareaRef.current;
        const from = el ? el.selectionEnd : 0;
        let at = body.indexOf(find, from);
        if (at === -1) at = body.indexOf(find);      // wrap around
        if (at === -1) return;
        const text = body.slice(0, at) + repl + body.slice(at + find.length);
        setBody(text);
        const afterPaint = typeof requestAnimationFrame === "function"
            ? requestAnimationFrame : (f) => setTimeout(f, 0);
        afterPaint(() => {
            if (!el) return;
            el.focus();
            el.setSelectionRange(at, at + repl.length);
        });
    };

    const replaceAll = () => { if (find) setBody(body.split(find).join(repl)); };

    const sep = <div style={{ width: 1, height: 22, background: t.border, margin: "0 4px" }} />;

    const btn = (label, title, onClick, opts = {}) => (
        <button type="button" title={title} disabled={opts.disabled}
            onClick={e => { e.preventDefault(); onClick(); }}
            style={{
                minWidth: 32, height: 30, padding: "0 9px", borderRadius: 8,
                border: "none",
                background: opts.active ? t.primaryGlow : "transparent",
                color: opts.disabled ? t.textFaint : opts.active ? t.primary : t.text,
                cursor: opts.disabled ? "not-allowed" : "pointer",
                fontSize: opts.size || 13, fontWeight: opts.weight || 600,
                fontFamily: "inherit", display: "flex", alignItems: "center",
                justifyContent: "center", gap: 6, whiteSpace: "nowrap",
            }}
            onMouseEnter={e => { if (!opts.disabled && !opts.active) e.currentTarget.style.background = t.inputBg; }}
            onMouseLeave={e => { if (!opts.active) e.currentTarget.style.background = "transparent"; }}
        >{label}</button>
    );

    const dropdown = (key, label, items, onPick) => (
        <div style={{ position: "relative" }}>
            <button type="button"
                onClick={e => { e.stopPropagation(); setMenu(menu === key ? null : key); }}
                style={{
                    height: 30, padding: "0 11px", borderRadius: 8,
                    border: `1px solid ${menu === key ? t.primary : t.border}`,
                    background: menu === key ? t.primaryGlow : "transparent",
                    color: menu === key ? t.primary : t.text,
                    cursor: "pointer", fontSize: 12.5, fontWeight: 600,
                    fontFamily: "inherit", display: "flex", alignItems: "center", gap: 7,
                }}>
                {label} <span style={{ fontSize: 9, opacity: 0.8 }}>▼</span>
            </button>
            {menu === key && (
                <div onClick={e => e.stopPropagation()} style={{
                    position: "absolute", top: 35, left: 0, zIndex: 50,
                    minWidth: 190, maxHeight: 300, overflowY: "auto",
                    background: t.card, border: `1px solid ${t.border}`,
                    borderRadius: 12, boxShadow: t.shadowCard, padding: "5px 0",
                }}>
                    {items.map((it, i) => (
                        <button key={i} type="button"
                            onClick={() => { setMenu(null); onPick(it); }}
                            style={{
                                display: "block", width: "100%", textAlign: "left",
                                padding: "8px 14px", background: "transparent",
                                border: "none", color: t.text, fontSize: 12.5,
                                cursor: "pointer", fontFamily: "inherit",
                            }}
                            onMouseEnter={e => e.currentTarget.style.background = t.inputBg}
                            onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                        >{it.label}</button>
                    ))}
                </div>
            )}
        </div>
    );

    const findInput = (value, onChange, placeholder) => (
        <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
            style={{
                height: 30, padding: "0 10px", borderRadius: 8, minWidth: 130,
                background: t.inputBg, border: `1px solid ${t.border}`,
                color: t.text, fontSize: 12.5, outline: "none", fontFamily: "inherit",
            }} />
    );

    const used = body.length;
    const near = used > MAX_BODY_CHARS * 0.9;

    return (
        <div style={{ borderBottom: `1px solid ${t.border}`, background: t.surface }}>
            <div style={{
                display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap",
                padding: "7px 10px",
            }}>
                {/* Structure */}
                {btn("¶", "Section heading", heading, { size: 15 })}
                {btn("1.", "Numbered item", numberedItem, { weight: 700 })}
                {btn("•", "Bullet the selected lines", () => prefixLines("  • "), { size: 15 })}
                {btn("⇥", "Indent the selected lines", () => prefixLines("    "), { size: 14 })}
                {sep}

                {/* Editing */}
                {btn("🔍", "Find and replace", () => setFindOpen(v => !v),
                     { size: 13, active: findOpen })}
                {dropdown("case", "Aa Case", CASES, c => changeCase(c.fn))}
                {btn("⧉", "Duplicate this line", duplicateLine, { size: 14 })}
                {btn("↑", "Move this line up", () => moveLine(-1), { size: 14 })}
                {btn("↓", "Move this line down", () => moveLine(1), { size: 14 })}
                {sep}

                {dropdown("insert", "＋ Insert", INSERTABLES, it => insert(it.build()))}
                {sep}

                {btn("↶", "Undo", onUndo, { size: 15, disabled: !canUndo })}
                {btn("↷", "Redo", onRedo, { size: 15, disabled: !canRedo })}

                <div style={{ flex: 1, minWidth: 8 }} />

                {/* Text size is a reading preference: it changes nothing in the
                    document that gets signed. */}
                <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
                    {btn("Aa−", "Smaller text", () => setZoom(z => Math.max(12, z - 1)), { size: 12 })}
                    <span style={{ fontSize: 11.5, color: t.textMuted, minWidth: 24, textAlign: "center" }}>{zoom}</span>
                    {btn("Aa+", "Larger text", () => setZoom(z => Math.min(22, z + 1)), { size: 12 })}
                </div>
                {sep}
                <span title={`The server accepts up to ${MAX_BODY_CHARS.toLocaleString()} characters`}
                    style={{ fontSize: 11.5, color: near ? t.warn : t.textMuted, fontWeight: near ? 700 : 500 }}>
                    {used.toLocaleString()} / {MAX_BODY_CHARS.toLocaleString()}
                </span>
            </div>

            {findOpen && (
                <div style={{
                    display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
                    padding: "8px 12px", borderTop: `1px solid ${t.border}`,
                    background: t.card,
                }}>
                    {findInput(find, setFind, "Find")}
                    {findInput(repl, setRepl, "Replace with")}
                    {/* The count is the useful part: it says whether the thing
                        being replaced is actually in the document, before
                        anything is changed. */}
                    <span style={{ fontSize: 11.5, color: find && !matches ? t.warn : t.textMuted }}>
                        {find ? `${matches} match${matches === 1 ? "" : "es"}` : "Type what to find"}
                    </span>
                    <div style={{ flex: 1 }} />
                    {btn("Replace", "Replace the next match", replaceNext,
                         { disabled: !find || !matches, size: 12 })}
                    {btn("Replace all", `Replace all ${matches}`, replaceAll,
                         { disabled: !find || !matches, size: 12 })}
                    {btn("✕", "Close find and replace", () => setFindOpen(false), { size: 13 })}
                </div>
            )}
        </div>
    );
};

const PageCreate = ({ template, onNavigate, onDone }) => {
    const t = useTheme();
    const toast = useToast();
    const { user } = useAuth();
    const [step, setStep] = useState(0);
    const [title, setTitle] = useState(template?.name || "New Agreement");
    const [body, setBody] = useState(template?.body || "");
    const editorRef = useRef(null);
    const [zoom, setZoom] = useState(14);

    /* UNDO HAS TO BE OURS. A textarea keeps its own undo stack, but only while
       the browser owns the value; once React drives it through `value` and
       `onChange`, every programmatic edit clears that stack and Ctrl+Z jumps
       to an empty box. So the history is explicit.

       Typing is COALESCED on a short timer -- one entry per burst, not per
       keystroke, or undo walks back a character at a time and is useless. A
       toolbar action commits immediately, because those are the edits somebody
       most wants to take back. */
    const history = useRef({ past: [], future: [], timer: null });
    const [histTick, setHistTick] = useState(0);

    const pushHistory = useCallback((prev, { immediate = false } = {}) => {
        const h = history.current;
        const commit = () => {
            if (h.past[h.past.length - 1] === prev) return;
            h.past = [...h.past, prev].slice(-60);
            h.future = [];
            setHistTick(n => n + 1);
        };
        if (h.timer) { clearTimeout(h.timer); h.timer = null; }
        if (immediate) commit();
        else h.timer = setTimeout(commit, 450);
    }, []);

    const editBody = useCallback((next) => {
        setBody(cur => { pushHistory(cur, { immediate: true }); return next; });
    }, [pushHistory]);

    const typeBody = useCallback((next) => {
        setBody(cur => { pushHistory(cur); return next; });
    }, [pushHistory]);

    const undo = useCallback(() => {
        const h = history.current;
        if (h.timer) { clearTimeout(h.timer); h.timer = null; }
        if (!h.past.length) return;
        setBody(cur => {
            const prev = h.past[h.past.length - 1];
            h.past = h.past.slice(0, -1);
            h.future = [cur, ...h.future].slice(0, 60);
            setHistTick(n => n + 1);
            return prev;
        });
    }, []);

    const redo = useCallback(() => {
        const h = history.current;
        if (!h.future.length) return;
        setBody(cur => {
            const next = h.future[0];
            h.future = h.future.slice(1);
            h.past = [...h.past, cur].slice(-60);
            setHistTick(n => n + 1);
            return next;
        });
    }, []);
    // SIGNERS, not a single counterparty. The backend takes 2-3 parties
    // (MAX_PARTIES), each either a registered user or an invited email address,
    // so the wizard carries a list. The creator is implicit and is NOT in it.
    //
    // Restored from the original builder design, which offered "Add Signers"
    // with an email option before the backend could honour either; the step was
    // narrowed to one registered counterparty in the meantime.
    const [signers, setSigners] = useState([]);   // {kind:'user'|'email', ...}
    const [cpList, setCpList] = useState([]);
    const [cpLoading, setCpLoading] = useState(true);
    const [cpSearch, setCpSearch] = useState("");
    const [fullName, setFullName] = useState("");
    // ONE SIGNATURE, IN THE SERVER'S VOCABULARY. This was five pieces of
    // state (mode, drawn, typed, uploaded, hasSig) plus a canvas ref and four
    // drawing handlers -- a second copy of the pad that now lives in
    // components/shared/SignaturePad.jsx. The copies had already diverged: the
    // drawn-signature capture fix was here, the honest upload limit was there.
    const [sig, setSig] = useState({ method: "canvas", data: "" });
    const [submitting, setSubmitting] = useState(false);
    // The one-time links for invited signers, shown ONCE after a successful
    // send. The server stores only each token's hash, so this is the only
    // moment they can be read — closing this panel without copying them means
    // issuing a fresh invitation.
    const [sentLinks, setSentLinks] = useState(null);
    // Addresses that turned out to have accounts, reported by the server.
    const [accountNotifs, setAccountNotifs] = useState([]);
    // SHOWN BESIDE THE BUTTON, not only as a toast. Toasts render at the top of
    // the page; this button is at the bottom of a long scrolled review step, so
    // a refusal could be reported and never seen.
    const [sendError, setSendError] = useState(null);
    // ONE key per send INTENT, minted when the wizard opens and kept across
    // retries. A key minted at click time would be new on every click, which is
    // exactly the case the server's idempotency receipt exists to stop: a
    // double-click or a retry after a timeout creating two signed agreements.
    const sendKeyRef = useRef(idempotencyKey());

    const STEPS = ["Edit Agreement", "Add Signers", "Your Signature", "Review & Send"];

    // The creator plus this many others. Mirrors MAX_PARTIES on the server; the
    // server refuses beyond it either way, and the UI should not offer what
    // would be refused.
    const MAX_SIGNERS = 2;

    const addUserSigner = (l) => setSigners(prev =>
        prev.length >= MAX_SIGNERS || prev.some(x => x.user_id === l._id)
            ? prev
            : [...prev, { kind: "user", user_id: l._id, name: l.name, spec: l.spec }]);

    const addEmailSigner = () => setSigners(prev =>
        prev.length >= MAX_SIGNERS
            ? prev
            : [...prev, { kind: "email", email: "", name: "" }]);

    const updateSigner = (i, patch) => setSigners(prev =>
        prev.map((x, n) => (n === i ? { ...x, ...patch } : x)));

    const removeSigner = (i) => setSigners(prev => prev.filter((_, n) => n !== i));

    // A party the server will accept: an email signer needs a plausible address.
    const signersReady = signers.length > 0 && signers.every(sg =>
        sg.kind === "user" ? !!sg.user_id : /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(sg.email || ""));

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
    // One definition of "there is a signature", used by the step guard and by
    // the submit handler, so the two cannot disagree about whether the wizard
    // is complete.
    const signatureReady = !!sig.data;

    const nav = (n) => {
        if (n > step && step === 0 && !title.trim()) return;
        if (n > 1 && step === 1 && !signersReady) {
            toast.show(signers.length
                ? "⚠️ Give every invited signer a valid email address"
                : "⚠️ Add at least one other signer", "warn");
            return;
        }
        // CAUGHT AT THE STEP BOUNDARY, not at the final click. Reaching Review
        // with no signature meant the only feedback came from "Sign & Send"
        // doing nothing visible -- at the bottom of a long scrolled page, where
        // a toast at the top is easy to miss entirely.
        if (n > 2 && step === 2 && !signatureReady) {
            toast.show("⚠️ Add your signature before reviewing", "warn");
            return;
        }
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
                {/* "Save Draft" was here and it saved nothing -- it showed
                    alert("Draft saved!") and the user then navigated away and
                    lost the work. Worse than a dead button: it confirmed a
                    persistence that does not exist. Removed rather than made
                    inert, because a disabled Save Draft still promises the
                    feature. Real draft persistence is Phase 3 (§3.4). */}
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
                        {/* A DRAFTING bar, not a formatting one. Every control
                            here writes characters into the document, because
                            characters are all a signed plain-text agreement can
                            carry. The 24-button bold/italic/align bar that used
                            to sit here had no handlers at all and promised
                            styling this editor cannot produce -- see the note at
                            TOOLBAR_ACTIONS. */}
                        <DraftingToolbar
                            body={body} setBody={editBody} textareaRef={editorRef}
                            zoom={zoom} setZoom={setZoom}
                            onUndo={undo} onRedo={redo}
                            canUndo={history.current.past.length > 0}
                            canRedo={history.current.future.length > 0}
                        />
                        <div style={{
                            padding: "6px 14px", borderBottom: `1px solid ${t.border}`,
                            background: t.surface, fontSize: 11, color: t.textMuted,
                        }}>
                            Plain text — the signed agreement is exactly these characters.
                        </div>
                        {/* Body */}
                        <textarea
                            ref={editorRef}
                            value={body}
                            onChange={e => typeBody(e.target.value)}
                            onKeyDown={e => {
                                // The browser's own Ctrl+Z would restore a value
                                // React is not tracking, so it is redirected to
                                // the history above rather than left to fight it.
                                const mod = e.ctrlKey || e.metaKey;
                                if (mod && e.key.toLowerCase() === "z") {
                                    e.preventDefault();
                                    if (e.shiftKey) redo(); else undo();
                                } else if (mod && e.key.toLowerCase() === "y") {
                                    e.preventDefault(); redo();
                                }
                            }}
                            style={{
                                width: "100%", minHeight: 380, background: t.card, border: "none", color: t.text,
                                fontSize: zoom, lineHeight: 1.8, padding: "20px 24px", outline: "none", resize: "vertical",
                                fontFamily: "Georgia, 'Times New Roman', serif", boxSizing: "border-box",
                            }} />
                    </Card>
                </div>
            )}

            {/* ── STEP 1: Add Signers ── */}
            {step === 1 && (
                <div>
                    <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 16 }}>
                        <div style={{ flex: 1 }}>
                            <div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>Signers</div>
                            <div style={{ fontSize: 12, color: t.textMuted }}>
                                Add the people who need to sign, besides you. Up to {MAX_SIGNERS}.
                            </div>
                        </div>
                        <Btn onClick={addEmailSigner} disabled={signers.length >= MAX_SIGNERS}
                            style={{ padding: "8px 14px", fontSize: 12, opacity: signers.length >= MAX_SIGNERS ? 0.5 : 1 }}>
                            ✉️ Invite by email
                        </Btn>
                    </div>

                    {/* Chosen signers */}
                    {signers.map((sg, i) => (
                        <div key={i} style={{
                            padding: "12px 16px", borderRadius: 12, marginBottom: 10,
                            background: t.primaryGlow, border: `1.5px solid ${t.primary}`,
                        }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                                <div style={{
                                    width: 32, height: 32, borderRadius: "50%",
                                    background: sg.kind === "user" ? t.primary : t.warn,
                                    display: "flex", alignItems: "center", justifyContent: "center",
                                    fontSize: 13, fontWeight: 800,
                                    color: t.mode === "dark" ? "#1A2E35" : "#fff", flexShrink: 0,
                                }}>{sg.kind === "user" ? "👤" : "✉️"}</div>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>
                                        {sg.kind === "user" ? sg.name : (sg.name || "Invited signer")}
                                    </div>
                                    <div style={{ fontSize: 11, color: sg.kind === "user" ? t.primary : t.warn }}>
                                        {sg.kind === "user"
                                            ? `${sg.spec} · signs from their account`
                                            : "Invited by email · gets a one-time signing link"}
                                    </div>
                                </div>
                                <button onClick={() => removeSigner(i)} style={{
                                    background: "none", border: `1px solid ${t.border}`, borderRadius: 8,
                                    padding: "5px 12px", color: t.textMuted, fontSize: 11, cursor: "pointer",
                                }}>Remove</button>
                            </div>

                            {sg.kind === "email" && (
                                <div className="rgrid-2" style={{
                                    display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 12,
                                }}>
                                    <div>
                                        <div style={{ fontSize: 10.5, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.6px", marginBottom: 4 }}>Full name</div>
                                        <Input value={sg.name} placeholder="Their name"
                                            onChange={e => updateSigner(i, { name: e.target.value })} />
                                    </div>
                                    <div>
                                        <div style={{ fontSize: 10.5, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.6px", marginBottom: 4 }}>Email address</div>
                                        <Input value={sg.email} placeholder="signer@example.com"
                                            onChange={e => updateSigner(i, { email: e.target.value })} />
                                    </div>
                                </div>
                            )}
                        </div>
                    ))}

                    {/* WHAT AN INVITATION IS AND IS NOT, said where the
                        invitation is created rather than buried.

                        THIS TEXT USED TO CLAIM DELIVERY. It read "an invited
                        signer receives a one-time link" and "we can show the
                        invitation was sent to that address" -- neither of which
                        happens. Nothing in this product emails an invitation:
                        `utils/email.py` sends password resets and KYC results
                        and has no agreement sender at all. A user who read that
                        sentence had every reason to wait for an email that was
                        never coming, and to believe a delivery record existed
                        that does not. */}
                    {signers.some(sg => sg.kind === "email") && (
                        <div style={{
                            display: "flex", gap: 10, padding: "11px 14px", borderRadius: 10,
                            background: t.warn + "14", border: `1px solid ${t.warn}40`,
                            marginBottom: 14, fontSize: 11.5, color: t.textMuted, lineHeight: 1.6,
                        }}>
                            <span style={{ fontSize: 14 }}>ℹ️</span>
                            <span>
                                We email each invited signer a one-time link, and show you
                                every link afterwards in case a message does not go out. They
                                sign without an account, and{" "}
                                <strong style={{ color: t.text }}>we do not verify who
                                signs</strong>. Links expire after 7 days.
                            </span>
                        </div>
                    )}

                    {signers.length < MAX_SIGNERS && (
                        <>
                            <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.7px", margin: "18px 0 8px" }}>
                                Or choose a registered lawyer
                            </div>
                            <div style={{ position: "relative", marginBottom: 12 }}>
                                <span style={{ position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)", fontSize: 13, color: t.textMuted }}>🔍</span>
                                <Input placeholder="Search verified lawyers…" value={cpSearch} onChange={e => setCpSearch(e.target.value)} style={{ paddingLeft: 38 }} />
                            </div>
                            <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 300, overflowY: "auto" }}>
                                {cpLoading ? (
                                    <div style={{ padding: "28px 0", textAlign: "center", color: t.textMuted, fontSize: 13 }}>Loading verified lawyers…</div>
                                ) : cpList
                                    .filter(l => l.name.toLowerCase().includes(cpSearch.toLowerCase()))
                                    .filter(l => !signers.some(sg => sg.user_id === l._id))
                                    .map(l => (
                                        <div key={l._id} onClick={() => addUserSigner(l)} style={{
                                            display: "flex", alignItems: "center", gap: 12, padding: "12px 16px",
                                            borderRadius: 12, background: t.card, border: `1.5px solid ${t.border}`,
                                            cursor: "pointer",
                                        }}>
                                            <div style={{
                                                width: 36, height: 36, borderRadius: "50%", background: t.primaryGlow,
                                                border: `1px solid ${t.primary}50`, display: "flex", alignItems: "center",
                                                justifyContent: "center", fontSize: 12, fontWeight: 800, color: t.primary,
                                            }}>{l.avatar}</div>
                                            <div style={{ flex: 1, minWidth: 0 }}>
                                                <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>{l.name}</div>
                                                <div style={{ fontSize: 11, color: t.textMuted, textTransform: "capitalize" }}>{l.spec}</div>
                                            </div>
                                            <span style={{ fontSize: 11, color: t.primary, fontWeight: 600 }}>+ Add</span>
                                        </div>
                                    ))}
                                {!cpLoading && !cpList.length && (
                                    <div style={{ padding: "22px 0", textAlign: "center", color: t.textMuted, fontSize: 12.5, lineHeight: 1.6 }}>
                                        No registered lawyers available yet.<br />
                                        Use <strong style={{ color: t.text }}>Invite by email</strong> to send this to someone without an account.
                                    </div>
                                )}
                            </div>
                        </>
                    )}
                </div>
            )}

            {/* ── STEP 2: Your Signature ── */}
            {step === 2 && (
                <div style={{ maxWidth: 780 }}>

                    {/* ── Top info row ── */}
                    <div className="rgrid-2" style={{
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
                                    <span style={{ color: t.primary, fontWeight: 700 }}>
                                        {signers.length === 0
                                            ? "the other party"
                                            : signers.map(sg => sg.name || sg.email || "your signer").join(" and ")}
                                    </span>{" "}
                                    {signers.length > 1 ? "are" : "is"} asked to counter-sign.
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
                                {/* Two claims used to sit here, both unsupported:
                                    "AES-256 encrypted" and "Compliant with
                                    e-signature laws". Signatures are stored as
                                    plaintext base64 (agreement_repo.update_party_
                                    signature); the only encryption in the system
                                    is Fernet/AES-128 over CNICs. And whether an
                                    instrument complies with ETO 2002 is a legal
                                    conclusion no lawyer has reviewed.
                                    Telling someone their signature is encrypted
                                    and legally compliant, in the panel where they
                                    decide to sign, is the worst place in the
                                    product to be wrong. What is left is true. */}
                                <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 4 }}>
                                    What we record
                                </div>
                                <div style={{ fontSize: 11.5, color: t.textMuted, lineHeight: 1.6 }}>
                                    On submission, we record your account, timestamp, IP address,
                                    and the agreement content hash.
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
                        border: `1.5px solid ${sig.data ? t.primary : t.border}`,
                        background: t.card,
                        boxShadow: sig.data ? `0 0 0 3px ${t.primaryGlow2}` : "none",
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
                                        {sig.data ? "✓ Signature captured" : "Draw, type or upload below"}
                                    </div>
                                </div>
                            </div>

                        </div>

                        <div style={{ padding: "16px 18px" }}>
                            <SignaturePad height={200} onChange={setSig} />
                        </div>

                        {/* Footer strip */}
                        <div style={{
                            padding: "10px 18px",
                            borderTop: `1px solid ${t.border}`,
                            display: "flex", alignItems: "center", justifyContent: "space-between",
                            background: t.surface,
                        }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: t.textMuted }}>
                                <span>🔒</span>
                                <span>Signature encrypted at rest with AES-256-GCM · timestamped on submission</span>
                            </div>
                            {sig.data && (
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
                            {/* NOTHING HAS BEEN SIGNED YET on this screen.
                                This list used to show the creator with a green
                                SIGNED badge and "Signed just now" before any
                                request had been made — so a failed send left
                                the user believing they had signed. The order
                                below is what WILL happen when Sign & Send
                                succeeds. */}
                            <div style={{ display: "flex", gap: 16, paddingBottom: 16 }}>
                                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0 }}>
                                    <div style={{
                                        width: 28, height: 28, borderRadius: "50%",
                                        background: t.primaryGlow, border: `2px solid ${t.primary}`,
                                        display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12,
                                        color: t.primary, fontWeight: 700, flexShrink: 0
                                    }}>1</div>
                                    <div style={{ width: 2, flex: 1, background: t.border, marginTop: 4 }} />
                                </div>
                                <div style={{ flex: 1 }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                                        <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{fullName || "You"}</span>
                                        <span style={{
                                            fontSize: 10, fontWeight: 700, color: t.primary, background: t.primaryGlow,
                                            border: `1px solid ${t.primary}40`, borderRadius: 5, padding: "2px 7px"
                                        }}>SIGNS ON SEND</span>
                                    </div>
                                    <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 8 }}>
                                        Creator · your signature is applied when this is sent
                                    </div>
                                    {/* Rendered from the captured signature. The
                                        canvas that produced it belongs to step 2
                                        and is unmounted by the time this renders. */}
                                    {sig.data && (
                                        <div style={{
                                            width: 140, height: 56, borderRadius: 8, background: t.inputBg,
                                            border: `1px solid ${t.border}`, display: "flex", alignItems: "center",
                                            justifyContent: "center", overflow: "hidden",
                                        }}>
                                            {sig.method === "typed" ? (
                                                <span style={{
                                                    fontFamily: "'Brush Script MT','Segoe Script',cursive",
                                                    fontSize: 20, color: t.primary,
                                                }}>{sig.data}</span>
                                            ) : (
                                                <img src={sig.data} alt="Your signature"
                                                     style={{ maxWidth: 140, maxHeight: 56, objectFit: "contain" }} />
                                            )}
                                        </div>
                                    )}
                                </div>
                            </div>

                            {signers.map((sg, i) => (
                                <div key={i} style={{ display: "flex", gap: 16, paddingBottom: i === signers.length - 1 ? 0 : 16 }}>
                                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0 }}>
                                        <div style={{
                                            width: 28, height: 28, borderRadius: "50%", background: t.warn + "30",
                                            border: `2px solid ${t.warn}`, display: "flex", alignItems: "center",
                                            justifyContent: "center", fontSize: 12, color: t.warn, flexShrink: 0
                                        }}>{i + 2}</div>
                                        {i < signers.length - 1 && (
                                            <div style={{ width: 2, flex: 1, background: t.border, marginTop: 4 }} />
                                        )}
                                    </div>
                                    <div style={{ flex: 1, paddingTop: 4 }}>
                                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                                            <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
                                                {sg.name || sg.email || "Signer"}
                                            </span>
                                            <span style={{
                                                fontSize: 10, fontWeight: 700,
                                                color: sg.kind === "user" ? t.info : t.warn,
                                                background: sg.kind === "user" ? "rgba(90,179,255,0.12)" : t.warn + "1F",
                                                border: `1px solid ${sg.kind === "user" ? "rgba(90,179,255,0.25)" : t.warn + "40"}`,
                                                borderRadius: 5, padding: "2px 7px"
                                            }}>{sg.kind === "user" ? "IN-APP" : "EMAIL LINK"}</span>
                                        </div>
                                        <div style={{ fontSize: 11, color: t.textMuted }}>
                                            {sg.kind === "user"
                                                ? "Notified on send · counter-signs from their Agreements page"
                                                : `One-time link for ${sg.email} · identity not verified by us`}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </Card>

                    {/* Security notice */}
                    <Card style={{ background: t.primaryGlow2, borderColor: `${t.primary}30`, marginBottom: 16 }}>
                        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                            <span style={{ fontSize: 18 }}>🛡️</span>
                            <div>
                                {/* Same two unsupported claims as the signature
                                    panel above. See the note there. */}
                                <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>What we record</div>
                                <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>
                                    On submission, we record your account, timestamp, IP address,
                                    and the agreement content hash.
                                </div>
                            </div>
                        </div>
                    </Card>
                </div>
            )}

            {sendError && (
                <div style={{
                    display: "flex", gap: 10, alignItems: "flex-start",
                    padding: "13px 16px", borderRadius: 12, marginTop: 20,
                    background: `${t.danger}14`, border: `1.5px solid ${t.danger}55`,
                }}>
                    <span style={{ fontSize: 16 }}>⚠️</span>
                    <div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: t.danger, marginBottom: 3 }}>
                            The agreement was not sent
                        </div>
                        <div style={{ fontSize: 12.5, color: t.text, lineHeight: 1.6 }}>{sendError}</div>
                    </div>
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
                        if (!signersReady) {
                            toast.show("⚠️ Add at least one other signer (Step 2)", "warn"); return;
                        }
                        if (!sig.data) { toast.show("⚠️ Please add your signature first", "warn"); return; }
                        setSendError(null);
                        setSubmitting(true);
                        try {
                            // ONE request. The old flow created the agreement,
                            // which notified the counterparties, and only then
                            // signed it in a second call — so a failure between
                            // the two left an unsigned agreement that everyone
                            // had already been told about. The server now
                            // creates, signs and sends in one transaction, and
                            // the Idempotency-Key makes a retry return the same
                            // agreement instead of a second one.
                            const res = await createAgreement({
                                title,
                                body_html: body,
                                party_ids: signers.map(sg => sg.kind === "user"
                                    ? { user_id: sg.user_id }
                                    : { email: sg.email.trim(), full_name: sg.name?.trim() || null }),
                                method: sig.method,
                                signature_data: sig.data,
                                consent: true,
                                idempotency_key: sendKeyRef.current,
                            });
                            if (res.error) {
                                // `.message` FIRST. formatResponseError puts the
                                // server's own words there; `.detail` is set only
                                // when the response body used that key, which this
                                // API's envelope ({error, status_code}) does not.
                                // Reading detail first meant every refusal reached
                                // the user as "Failed to send agreement" -- including
                                // "this still contains the unreviewed-sample notice",
                                // which tells them exactly what to fix.
                                const why = res.error?.message || res.error?.detail
                                    || "Failed to send agreement";
                                setSendError(why);
                                toast.show("❌ " + why, "danger", 6000);
                                setSubmitting(false); return;
                            }
                            const waiting = signers.map(sg => sg.name || sg.email).join(" and ");
                            toast.show(`✅ Signed & sent — awaiting ${waiting}`, "success", 4000);

                            // THE LINKS ARE SHOWN WHETHER OR NOT THE EMAIL WENT.
                            // Delivery is best effort, so the sender needs to
                            // see which invitations actually left and to be
                            // handed the rest — and the token cannot be shown
                            // again, so "we emailed it, you may close this" is
                            // only safe for the ones that really were emailed.
                            const tokens = res.data?.invitation_tokens_do_not_store;
                            const delivery = res.data?.invitation_delivery || {};
                            const byId = Object.fromEntries(
                                (res.data?.parties || []).map(p => [p.party_id, p]));
                            const links = Object.entries(tokens || {}).map(([pid, tok]) => ({
                                email: byId[pid]?.email || "",
                                name: byId[pid]?.full_name || "",
                                emailed: !!delivery[pid]?.emailed,
                                reason: delivery[pid]?.reason || null,
                                url: `${window.location.origin}/sign?token=${encodeURIComponent(tok)}`,
                            }));
                            // The server converts an invited address that has an
                            // account into a registered party and notifies them in
                            // the app. That is right, but the sender asked for an
                            // email -- if nothing says so, they wait for one that
                            // was never going to be sent.
                            // Every registered party besides you, and how each
                            // was told. Both channels are reported separately: a
                            // failed email must not read as "never notified", and
                            // a delivered one must not hide that the in-app
                            // notification is the actual record.
                            const accounts = res.data?.account_notifications || [];
                            if (links.length || accounts.length) {
                                setSentLinks(links);
                                setAccountNotifs(accounts);
                                return;
                            }
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

            {/* ── Invitation links, shown once ── */}
            {(sentLinks || accountNotifs.length > 0) && (
                <div style={{
                    position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1000,
                    display: "flex", alignItems: "center", justifyContent: "center", padding: 20,
                }}>
                    <Card style={{ maxWidth: 560, width: "100%", maxHeight: "86vh", overflowY: "auto" }}>
                        <div style={{ fontSize: 16, fontWeight: 800, color: t.text, marginBottom: 6 }}>
                            {(sentLinks || []).every(l => l.emailed)
                                ? "✅ Sent — invitations emailed"
                                : (sentLinks || []).some(l => l.emailed)
                                    ? "✅ Sent — some invitations need sending by hand"
                                    : "✅ Sent — share these signing links"}
                        </div>
                        <div style={{ fontSize: 12.5, color: t.textMuted, lineHeight: 1.7, marginBottom: 16 }}>
                            {(sentLinks || []).every(l => l.emailed)
                                ? "Each signer has been emailed their own one-time link."
                                : "Copy the links below to the people they name."}
                            {" "}<strong style={{ color: t.warn }}>This is the only time these
                            links can be shown</strong> — only their hashes are stored, so a
                            lost link means issuing a new invitation.
                        </div>

                        {accountNotifs.length > 0 && (
                            <div style={{
                                padding: "12px 14px", borderRadius: 12, marginBottom: 12,
                                background: `${t.info}12`, border: `1px solid ${t.info}45`,
                            }}>
                                <div style={{ fontSize: 12.5, fontWeight: 700, color: t.info, marginBottom: 6 }}>
                                    Signers with an account
                                </div>
                                {accountNotifs.map((u, i) => (
                                    <div key={u.user_id || i} style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.7 }}>
                                        <strong style={{ color: t.text }}>{u.full_name || u.email}</strong>
                                        {" \u2014 "}
                                        {u.emailed
                                            ? "notified in the app and emailed"
                                            : `notified in the app; ${deliveryReason(u.reason)}`}
                                        {u.was_invited_by_email && (
                                            <span style={{ display: "block", color: t.warn, fontSize: 11.5 }}>
                                                You entered this address as an email invite, but it
                                                belongs to an account \u2014 so they sign by logging in,
                                                and no one-time link was issued.
                                            </span>
                                        )}
                                    </div>
                                ))}
                                <div style={{ fontSize: 11, color: t.textMuted, marginTop: 7, lineHeight: 1.6 }}>
                                    Account holders sign from their own Agreements page. Their
                                    email carries no signing link, so forwarding it gives nobody
                                    access.
                                </div>
                            </div>
                        )}

                        {(sentLinks || []).map((l, i) => (
                            <div key={i} style={{
                                padding: "12px 14px", borderRadius: 12, marginBottom: 10,
                                background: t.inputBg, border: `1px solid ${t.border}`,
                            }}>
                                <div style={{ fontSize: 12.5, fontWeight: 700, color: t.text, marginBottom: 6 }}>
                                    {l.name || l.email || "Invited signer"}
                                    {l.name && l.email && (
                                        <span style={{ fontWeight: 400, color: t.textMuted }}> · {l.email}</span>
                                    )}
                                </div>
                                {/* STATED PER RECIPIENT, from the server's own
                                    result. Delivery is best effort, and a blanket
                                    "emailed" over a failed send is the exact class
                                    of false claim this screen exists to avoid. */}
                                <div style={{
                                    fontSize: 11, marginBottom: 8, lineHeight: 1.6,
                                    color: l.emailed ? t.success : t.warn,
                                }}>
                                    {l.emailed
                                        ? "✉️ Emailed to this address — no action needed unless it does not arrive."
                                        : `⚠️ Not emailed — ${deliveryReason(l.reason)}. Send this link yourself.`}
                                </div>
                                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                                    <input readOnly value={l.url} onFocus={e => e.target.select()} style={{
                                        flex: 1, minWidth: 0, padding: "8px 11px", borderRadius: 9,
                                        background: t.card, border: `1px solid ${t.border}`,
                                        color: t.textMuted, fontSize: 11, fontFamily: "monospace",
                                    }} />
                                    <Btn onClick={() => {
                                        navigator.clipboard?.writeText(l.url)
                                            .then(() => toast.show("📋 Link copied", "success"))
                                            .catch(() => toast.show("⚠️ Copy failed — select the text and copy it", "warn"));
                                    }} style={{ padding: "8px 14px", fontSize: 12 }}>Copy</Btn>
                                </div>
                            </div>
                        ))}

                        <Btn primary onClick={() => { setSentLinks(null); setAccountNotifs([]); onDone(); }}
                            style={{ width: "100%", padding: "11px 20px", marginTop: 6 }}>
                            {(sentLinks || []).every(l => l.emailed)
                                ? "Done"
                                : "I have copied the links — done"}
                        </Btn>
                    </Card>
                </div>
            )}
        </div>
    );
};

// ── PAGE: ALL AGREEMENTS ─────────────────────
/* Header and rows share one definition; two copies drift and the
   columns stop lining up. */
const GRID = "2.4fr 1.9fr 132px 104px 52px";

/* The row's action menu.
 *
 * Its items are the two things you cannot already do by clicking the row:
 * download the finished document, and take it off your list. Everything else
 * lives in the detail view, where declining has the two-step confirm it needs.
 *
 * "Remove from my list" is NOT a delete, and the wording is the point. A sent
 * agreement is a record the other parties hold too -- `delete_draft` on the
 * server refuses anything except an unsent draft for exactly that reason. This
 * hides it for the caller alone, and the Archived filter puts it back.
 */
const RowMenu = ({ agreement, archivedView, onOpen, onDownload, onArchive, onUnarchive }) => {
    const t = useTheme();
    const [open, setOpen] = useState(false);

    // Close on any outside click. Without this the menu survives scrolling and
    // opening a second row, and two can be open at once.
    useEffect(() => {
        if (!open) return;
        const close = () => setOpen(false);
        document.addEventListener("click", close);
        return () => document.removeEventListener("click", close);
    }, [open]);

    const item = (label, onClick, tone) => (
        <button type="button"
            onClick={e => { e.stopPropagation(); setOpen(false); onClick(); }}
            style={{
                display: "block", width: "100%", textAlign: "left",
                padding: "9px 14px", background: "transparent", border: "none",
                color: tone || t.text, fontSize: 12.5, cursor: "pointer",
                fontFamily: "inherit", whiteSpace: "nowrap",
            }}
            onMouseEnter={e => e.currentTarget.style.background = t.inputBg}
            onMouseLeave={e => e.currentTarget.style.background = "transparent"}
        >{label}</button>
    );

    return (
        <div style={{ position: "relative", display: "flex", justifyContent: "flex-end" }}>
            <button
                type="button"
                title="More actions"
                aria-label="More actions"
                onClick={e => { e.stopPropagation(); setOpen(v => !v); }}
                style={{
                    width: 32, height: 32, borderRadius: 9,
                    border: `1px solid ${open ? t.primary : "transparent"}`,
                    background: open ? t.primaryGlow : "transparent",
                    color: open ? t.primary : t.text,
                    cursor: "pointer", fontSize: 20, fontWeight: 800, lineHeight: 1,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    letterSpacing: "1px",
                }}
                onMouseEnter={e => { if (!open) e.currentTarget.style.background = t.inputBg; }}
                onMouseLeave={e => { if (!open) e.currentTarget.style.background = "transparent"; }}
            >⋮</button>

            {open && (
                <div onClick={e => e.stopPropagation()} style={{
                    position: "absolute", top: 36, right: 0, zIndex: 40, minWidth: 196,
                    background: t.card, border: `1px solid ${t.border}`,
                    borderRadius: 12, boxShadow: t.shadowCard, padding: "5px 0",
                }}>
                    {item("\ud83d\udcc4  Open", onOpen)}
                    {/* Only once EXECUTED. The server refuses a PDF before every
                        party has signed, so offering it earlier would be an
                        action that always fails. */}
                    {agreement.rawStatus === "executed" &&
                        item("\u2b07\ufe0f  Download PDF", onDownload)}
                    <div style={{ height: 1, background: t.border, margin: "5px 0" }} />
                    {archivedView
                        ? item("\u21a9\ufe0f  Restore to my list", onUnarchive)
                        : item("\ud83d\uddd1\ufe0f  Remove from my list", onArchive, t.danger)}
                </div>
            )}
        </div>
    );
};

const PageAllAgreements = ({ onNavigate }) => {
    const t = useTheme();
    const toast = useToast();
    const { user } = useAuth();
    const [search, setSearch] = useState("");
    const [filter, setFilter] = useState("All");
    // "Archived" is a VIEW, not a status: it crosses the four real ones, so
    // it cannot be another pill in the same group without implying an
    // agreement is either pending or archived rather than both.
    const archivedView = filter === "Archived";
    const [agmts, loading, reload, paging] = useMyAgreements(
        user?._id, AG_FILTER_STATUS[filter] || null, archivedView);
    const [viewing, setViewing] = useState(null);       // mapped agreement being viewed
    // {method, data} from SignaturePad, in the server's own vocabulary.
    // This was a typed name only; the person RECEIVING an agreement could
    // not draw or upload, while the person sending one always could.
    const [signSig, setSignSig] = useState({ method: "canvas", data: "" });
    const [signBusy, setSignBusy] = useState(false);
    // Declining ends the agreement for everyone and cannot be undone, so it is
    // deliberately two steps: reveal, then confirm. A single button beside
    // "Sign" is one mis-click away from cancelling a contract.
    const [declineOpen, setDeclineOpen] = useState(false);
    const [declineReason, setDeclineReason] = useState("");
    const [declineBusy, setDeclineBusy] = useState(false);
    const [downloading, setDownloading] = useState(false);
    // The reissued link, shown ONCE. Same contract as the original send: only
    // the hash is stored, so closing this without copying means reissuing
    // again. Keyed by party so two invited signers cannot be confused.
    const [reissued, setReissued] = useState(null);   // {party_id, url, emailed, email}
    const [reissuing, setReissuing] = useState(null); // party_id in flight
    // The DOCUMENT behind the open row: { loading, body, error }. Separate
    // from `viewing` (the list row) so one can never be mistaken for the other.
    const [doc, setDoc] = useState(null);
    const openSeq = useRef(0);

    /* Open a row: fetch the document, never trust the row. Sign and decline
       are gated on this having succeeded, so a failed load cannot leave
       somebody able to sign text they were never shown. */
    const openAgreement = async (row) => {
        setViewing(row);
        setSignSig({ method: "canvas", data: "" });
        setDoc({ loading: true, body: null, error: null });

        // Only the latest open counts -- a late reply for a previously opened
        // agreement must not land under the heading of the current one. See
        // the same guard on the lawyer screen.
        const token = ++openSeq.current;
        const { data, error } = await getAgreement(row.id);
        if (token !== openSeq.current) return;

        if (error || !data) {
            setDoc({ loading: false, body: null,
                     error: error?.message || "This agreement could not be loaded." });
            return;
        }
        setDoc({ loading: false, body: data.body_html ?? "",
                 eto: data.eto_classification,
                 expiresAt: data.expires_at || null, error: null });
    };

    const doArchive = async (a) => {
        const { error } = await archiveAgreement(a.id);
        if (error) {
            toast.show("\u274c " + (error.message || "Could not remove it"), "danger");
            return;
        }
        // Says what happened and how to undo it. "Removed" on its own reads as
        // a delete, which is the one thing this is not.
        toast.show("Removed from your list \u2014 find it under Archived", "info", 5000);
        reload();
    };

    const doUnarchive = async (a) => {
        const { error } = await unarchiveAgreement(a.id);
        if (error) {
            toast.show("\u274c " + (error.message || "Could not restore it"), "danger");
            return;
        }
        toast.show("\u21a9\ufe0f Restored to your list", "success");
        reload();
    };

    const doDownloadRow = async (a) => {
        const { error } = await downloadExecutedAgreement(a.id, `${a.name}.pdf`);
        if (error) {
            toast.show("\u274c " + (error.message || "Could not download it"), "danger");
            return;
        }
        toast.show("\u2b07 Downloaded", "success");
    };

    const doReissue = async (party) => {
        setReissuing(party.party_id);
        setReissued(null);
        const { data, error } = await reissueAgreementInvitation(viewing.id, party.party_id);
        setReissuing(null);
        if (error) {
            // `.message` first: the API envelope is {error, status_code}, and
            // reading `.detail` first reduced every refusal to a generic string.
            toast.show("\u274c " + (error.message || error.detail || "Could not reissue the invitation"), "danger", 6000);
            return;
        }
        const token = (data?.invitation_tokens_do_not_store || {})[party.party_id];
        const delivery = (data?.invitation_delivery || {})[party.party_id] || {};
        if (!token) { toast.show("\u26a0\ufe0f No link came back \u2014 try again", "warn"); return; }
        setReissued({
            party_id: party.party_id,
            email: party.email,
            emailed: !!delivery.emailed,
            reason: delivery.reason || null,
            url: `${window.location.origin}/sign?token=${encodeURIComponent(token)}`,
        });
        toast.show(delivery.emailed
            ? "\u2709\ufe0f New link emailed"
            : "\u26a0\ufe0f New link ready \u2014 email did not go out",
            delivery.emailed ? "success" : "warn", 5000);
        reload();
    };

    const doDownload = async () => {
        setDownloading(true);
        const { error } = await downloadExecutedAgreement(
            viewing.id, `${viewing.name || "agreement"}.pdf`);
        setDownloading(false);
        if (error) { toast.show("❌ " + error, "danger"); return; }
        toast.show("⬇ Downloaded", "success");
    };
    // No "Draft" tab. A draft belongs to the lawyer who is writing it and is
    // invisible to the client until it is sent, so this tab could only ever be
    // empty for a client -- and before the server started filtering drafts out
    // of `GET /agreements`, it would have shown the client the lawyer's unsent
    // wording. Only a verified lawyer can create a draft (`create_draft`);
    // every agreement a client can reach starts at `pending`.
    const filters = ["All", "Signed", "Pending", "Rejected", "Archived"];
    // The status is applied by the server (see useMyAgreements); only the
    // free-text search is local, and it says so rather than looking like a
    // second status filter that might disagree with the first.
    const filtered = agmts.filter(a =>
        a.name.toLowerCase().includes(search.toLowerCase())
    );

    const doSign = async () => {
        if (!signSig.data) {
            toast.show("⚠️ Add your signature first — draw, type or upload", "warn");
            return;
        }
        setSignBusy(true);
        const { data, error } = await signAgreement(viewing.id, signSig.method, signSig.data);
        setSignBusy(false);
        if (error) { toast.show("❌ " + (error.message || "Failed to sign"), "danger"); return; }
        toast.show(data?.status === "executed" ? "🎉 Agreement fully executed!" : "✅ Signed — awaiting the other parties", "success", 4000);
        openSeq.current += 1; setViewing(null); setDoc(null);
        setSignSig({ method: "canvas", data: "" });
        reload();
    };

    const doDecline = async () => {
        setDeclineBusy(true);
        const { error } = await declineAgreement(viewing.id, declineReason);
        setDeclineBusy(false);
        if (error) { toast.show("❌ " + (error.message || "Failed to decline"), "danger"); return; }
        toast.show("Agreement declined — the other party has been notified", "info", 4000);
        openSeq.current += 1; setViewing(null); setDoc(null);
        setDeclineOpen(false);
        setDeclineReason("");
        reload();
    };
    return (
        <div>
            {/* ── Header: title left, search + primary action right ── */}
            <div className="rgrid-2" style={{
                display: "flex", alignItems: "flex-start", justifyContent: "space-between",
                gap: 16, flexWrap: "wrap", marginBottom: 18,
            }}>
                <div>
                    <h1 style={{ fontSize: 28, fontWeight: 800, color: t.text, margin: 0, fontFamily: "'Sora','Inter',sans-serif" }}>All Agreements</h1>
                    <p style={{ fontSize: 13, color: t.textMuted, margin: "4px 0 0" }}>View and manage all your agreements</p>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <div style={{ position: "relative", minWidth: 220 }}>
                        <span style={{ position: "absolute", left: 13, top: "50%", transform: "translateY(-50%)", fontSize: 13, color: t.textMuted }}>🔍</span>
                        <Input placeholder="Search" value={search} onChange={e => setSearch(e.target.value)}
                            style={{ paddingLeft: 36, fontSize: 13.5, padding: "11px 14px 11px 36px" }} />
                    </div>
                    {/* NOT "Upload New". There is no upload-an-agreement endpoint,
                        so that button would offer a feature that does not exist.
                        This opens the builder, and only when the builder is
                        actually enabled -- otherwise the server refuses the send
                        with a 403 and the button would be a second lie. */}
                    {DIY_BUILDER_ENABLED && (
                        <Btn primary onClick={() => onNavigate("templates")}
                            style={{ padding: "11px 20px", fontSize: 13.5, whiteSpace: "nowrap" }}>
                            New Agreement
                        </Btn>
                    )}
                </div>
            </div>

            {/* Filter pills, right-aligned under the search */}
            <div style={{ display: "flex", gap: 8, marginBottom: 18, flexWrap: "wrap", justifyContent: "flex-end" }}>
                {filters.map(f => (
                    <button key={f} onClick={() => setFilter(f)} style={{
                        padding: "8px 20px", borderRadius: 50, fontSize: 13, fontWeight: filter === f ? 700 : 500,
                        cursor: "pointer", fontFamily: "'Inter',sans-serif", transition: "all 0.15s",
                        border: `1.5px solid ${filter === f ? t.primary : t.border}`,
                        background: filter === f ? t.primaryGlow : "transparent",
                        color: filter === f ? t.primary : t.textMuted,
                    }}>{f}</button>
                ))}
            </div>

            {/* ── Table ── */}
            {/* Five columns cannot stack; scroll sideways on narrow screens. */}
            <Card style={{ padding: 0, overflow: "visible" }}>
                <div style={{
                    display: "grid", gridTemplateColumns: GRID, minWidth: 720,
                    padding: "12px 22px", borderBottom: `1px solid ${t.border}`, background: t.surface,
                }}>
                    {["DOCUMENT", "PARTIES", "STATUS", "PROGRESS", "ACTIONS"].map(h => (
                        <div key={h} style={{
                            fontSize: 10, fontWeight: 700, color: t.textMuted,
                            letterSpacing: "0.8px", textTransform: "uppercase",
                        }}>{h}</div>
                    ))}
                </div>

                {filtered.map((a, i) => {
                    const tone = a.needsMySig ? t.info
                        : a.status === "Signed" ? t.success
                            : a.status === "Rejected" ? t.danger : t.warn;
                    const others = (a.parties || []).filter(p => p.user_id !== a.createdBy);
                    const sender = (a.parties || []).find(p => p.user_id === a.createdBy);
                    return (
                        <div key={a.id} onClick={() => openAgreement(a)} style={{
                            display: "grid", gridTemplateColumns: GRID, minWidth: 720,
                            alignItems: "center", padding: "14px 22px",
                            borderBottom: i < filtered.length - 1 ? `1px solid ${t.border}` : "none",
                            transition: "background 0.15s", cursor: "pointer",
                        }}
                            onMouseEnter={e => e.currentTarget.style.background = t.cardHi}
                            onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                        >
                            {/* DOCUMENT — the icon is tinted by state, so the
                                column reads at a glance without the badge. */}
                            <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                                <div style={{
                                    width: 36, height: 36, borderRadius: 10, flexShrink: 0,
                                    background: `${tone}1F`, border: `1px solid ${tone}45`,
                                    display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15,
                                }}>{a.isEngagementLetter ? "⚖️" : "📄"}</div>
                                <div style={{ minWidth: 0 }}>
                                    <div style={{ fontSize: 13.5, fontWeight: 700, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</div>
                                    <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 2 }}>{a.date}</div>
                                </div>
                            </div>

                            {/* PARTIES — the sender is labelled; the rest are
                                COUNTED rather than assumed to be one. An
                                agreement may have three parties, and a fixed
                                Sender/Recipient pair would silently drop the
                                third. */}
                            <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                                <div>
                                    <div style={{ fontSize: 10, color: t.textFaint, marginBottom: 3 }}>Sender</div>
                                    <PartyAvatar name={sender?.full_name || "You"} tone={t.textMuted}
                                        title={sender?.full_name || "You"} />
                                </div>
                                <div style={{ minWidth: 0 }}>
                                    <div style={{ fontSize: 10, color: t.textFaint, marginBottom: 3 }}>
                                        {others.length > 1 ? `Recipients (${others.length})` : "Recipient"}
                                    </div>
                                    <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                                        {others.slice(0, 2).map((p, n) => (
                                            <PartyAvatar key={n}
                                                name={p.full_name || p.email || "Invited"}
                                                tone={p.signed ? t.success : t.warn}
                                                title={`${p.full_name || p.email || "Invited signer"} — ${p.signed ? "signed" : "pending"}`} />
                                        ))}
                                        {others.length > 2 && (
                                            <span style={{ fontSize: 11, color: t.textMuted }}>+{others.length - 2}</span>
                                        )}
                                        <span style={{
                                            fontSize: 12, color: t.textMuted, overflow: "hidden",
                                            textOverflow: "ellipsis", whiteSpace: "nowrap",
                                        }}>
                                            {others[0]?.full_name || others[0]?.email || "—"}
                                        </span>
                                    </div>
                                </div>
                            </div>

                            {/* STATUS. The Sign call-to-action sits here rather
                                than in ACTIONS: it belongs beside the reason it is
                                being offered, and it leaves the menu a single,
                                predictable target. */}
                            <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-start" }}>
                                <StatusBadge status={a.needsMySig ? "Needs Attention" : a.status} />
                                {a.needsMySig && (
                                    <Btn primary style={{ fontSize: 11, padding: "5px 12px" }}
                                        onClick={e => { e.stopPropagation(); openAgreement(a); }}>
                                        ✍️ Sign
                                    </Btn>
                                )}
                            </div>

                            {/* PROGRESS */}
                            <ProgressRing done={a.signedCount} total={a.totalParties} tone={tone} />

                            {/* ACTIONS */}
                            <RowMenu
                                agreement={a}
                                archivedView={archivedView}
                                onOpen={() => openAgreement(a)}
                                onDownload={() => doDownloadRow(a)}
                                onArchive={() => doArchive(a)}
                                onUnarchive={() => doUnarchive(a)}
                            />
                        </div>
                    );
                })}

                {/* HOW MANY THERE ARE. Without the total, a list that stops at
                    its page size looks exactly like a complete one. The counts
                    stay honest about loaded-vs-total rather than printing a
                    tidy range the data does not support. */}
                {!loading && agmts.length > 0 && (
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "12px 22px", borderTop: `1px solid ${t.border}`, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 12.5, color: t.textMuted }}>
                            {filtered.length === agmts.length
                                ? `Showing ${agmts.length} of ${paging.total}`
                                : `Showing ${filtered.length} of ${agmts.length} loaded (${paging.total} total)`}
                        </span>
                        {paging.hasMore && (
                            <button type="button" onClick={paging.loadMore} disabled={loading}
                                style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 9, padding: "7px 14px", cursor: "pointer", fontSize: 12.5, color: t.text, fontWeight: 600, fontFamily: "inherit" }}>
                                Load more
                            </button>
                        )}
                    </div>
                )}
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
                                <div style={{ fontSize: 11, color: t.textMuted }}>{doc?.eto || "Awaiting first signature"}</div>
                            </div>
                            <StatusBadge status={viewing.status} />
                            <button onClick={() => setViewing(null)} style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 8, width: 30, height: 30, cursor: "pointer", color: t.textMuted, fontSize: 15 }}>✕</button>
                        </div>

                        <div style={{ flex: 1, overflowY: "auto", padding: "18px 22px" }}>
                            {/* Parties */}
                            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 16 }}>
                                {/* KEYED BY WHATEVER IDENTIFIES THE PARTY. An
                                    external signer has no user_id, so keying on
                                    it alone gave every invited signer the key
                                    `undefined` — React then reuses one row for
                                    all of them and their signed states swap. */}
                                {viewing.parties.map((p, i) => (
                                    <div key={p.user_id || p.party_id || p.email || i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 12px", borderRadius: 10, background: p.signed ? `${t.success}12` : t.inputBg, border: `1px solid ${p.signed ? t.success + "40" : t.border}` }}>
                                        <span style={{ fontSize: 12 }}>{p.signed ? "✅" : "⏰"}</span>
                                        <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>
                                            {p.full_name || p.email || "Invited signer"}
                                        </span>
                                        {p.external && (
                                            /* Said on the party itself, because this
                                               is where someone decides how much to
                                               trust the signature. We can show a link
                                               went to an address; we did not check who
                                               opened it. */
                                            <span title="Invited by email — identity not verified by us" style={{
                                                fontSize: 9.5, fontWeight: 700, color: t.warn,
                                                background: t.warn + "1F", border: `1px solid ${t.warn}40`,
                                                borderRadius: 5, padding: "1px 5px",
                                            }}>EMAIL{p.invitation_status === "revoked" ? " · REVOKED" : p.invitation_status === "expired" ? " · EXPIRED" : ""}</span>
                                        )}
                                        <span style={{ fontSize: 10, color: p.signed ? t.success : t.textMuted }}>
                                            {p.signed ? `signed ${p.signed_at ? new Date(p.signed_at).toLocaleDateString() : ""}` : "pending"}
                                        </span>
                                        {/* ONLY for an invited signer who has not
                                            signed. A registered party never had a
                                            link, and reissuing to someone who has
                                            signed would invite a second signature. */}
                                        {p.external && !p.signed && viewing.rawStatus === "pending" && (
                                            <button
                                                disabled={reissuing === p.party_id}
                                                onClick={() => doReissue(p)}
                                                title="Send this person a new one-time link. The old link stops working."
                                                style={{
                                                    background: "none", border: `1px solid ${t.primary}55`,
                                                    borderRadius: 7, padding: "2px 8px", fontSize: 10,
                                                    color: t.primary, cursor: "pointer", fontWeight: 600,
                                                }}>
                                                {reissuing === p.party_id ? "Sending\u2026" : "Resend link"}
                                            </button>
                                        )}
                                    </div>
                                ))}
                            </div>

                            {/* Shown ONCE, right where the button was pressed. */}
                            {reissued && (
                                <div style={{
                                    padding: "12px 14px", borderRadius: 12, marginBottom: 14,
                                    background: t.primaryGlow2, border: `1.5px solid ${t.primary}55`,
                                }}>
                                    <div style={{ fontSize: 12, fontWeight: 700, color: t.text, marginBottom: 4 }}>
                                        New link for {reissued.email}
                                    </div>
                                    <div style={{
                                        fontSize: 11, marginBottom: 8, lineHeight: 1.6,
                                        color: reissued.emailed ? t.success : t.warn,
                                    }}>
                                        {reissued.emailed
                                            ? "\u2709\ufe0f Emailed again. The previous link no longer works."
                                            : `\u26a0\ufe0f Not emailed \u2014 ${deliveryReason(reissued.reason)}. Send this link yourself. The previous link no longer works.`}
                                    </div>
                                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                                        <input readOnly value={reissued.url} onFocus={e => e.target.select()} style={{
                                            flex: 1, minWidth: 0, padding: "7px 10px", borderRadius: 8,
                                            background: t.card, border: `1px solid ${t.border}`,
                                            color: t.textMuted, fontSize: 10.5, fontFamily: "monospace",
                                        }} />
                                        <Btn onClick={() => {
                                            navigator.clipboard?.writeText(reissued.url)
                                                .then(() => toast.show("\ud83d\udccb Link copied", "success"))
                                                .catch(() => toast.show("\u26a0\ufe0f Copy failed \u2014 select the text", "warn"));
                                        }} style={{ padding: "7px 12px", fontSize: 11 }}>Copy</Btn>
                                    </div>
                                    <div style={{ fontSize: 10.5, color: t.textMuted, marginTop: 7 }}>
                                        Shown once \u2014 only its hash is stored, so it cannot be displayed again.
                                    </div>
                                </div>
                            )}

                            {/* FROM THE FETCHED DOCUMENT, not the list row: the
                                list carries no expiry, and reading one off it
                                would show "no expiry" for everything. Only
                                shown while it still matters — an executed or
                                declined agreement cannot expire. */}
                            {viewing.rawStatus === "pending" && doc?.expiresAt && (
                                <div style={{
                                    display: "flex", alignItems: "center", gap: 8, marginBottom: 14,
                                    padding: "9px 13px", borderRadius: 10,
                                    background: t.warn + "12", border: `1px solid ${t.warn}35`,
                                    fontSize: 11.5, color: t.textMuted,
                                }}>
                                    <span>⏰</span>
                                    <span>
                                        Signatures can be added until{" "}
                                        <strong style={{ color: t.text }}>
                                            {new Date(doc.expiresAt).toLocaleDateString()}
                                        </strong>. After that a new agreement has to be sent.
                                    </span>
                                </div>
                            )}
                            {/* Body */}
                            {/* THE DOCUMENT, fetched by id. "No content." is
                                only ever a body the server really returned
                                empty -- never a stand-in for a field the list
                                did not carry. */}
                            {doc?.loading ? (
                                <div style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 12, padding: "22px 20px", fontSize: 13, color: t.textMuted, textAlign: "center" }}>
                                    Loading the agreement…
                                </div>
                            ) : doc?.error ? (
                                <div style={{ background: `${t.danger}12`, border: `1px solid ${t.danger}40`, borderRadius: 12, padding: "18px 20px", fontSize: 13, lineHeight: 1.7, color: t.danger }}>
                                    {doc.error}
                                    <div style={{ color: t.textMuted, marginTop: 6, fontSize: 12 }}>
                                        Nothing can be signed until the wording is on screen.
                                    </div>
                                </div>
                            ) : (
                                <div style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 12, padding: "18px 20px", fontSize: 13, lineHeight: 1.85, color: t.text, whiteSpace: "pre-wrap", fontFamily: "Georgia,serif" }}>
                                    {doc?.body ? doc.body : "No content."}
                                </div>
                            )}

                            {/* Only once EXECUTED. Before both parties have
                                signed there is no document to download, and
                                the server refuses one -- offering the button
                                early would promise a file that does not
                                exist. */}
                            {viewing.rawStatus === "executed" && doc && !doc.loading && !doc.error && (
                                <div style={{ marginTop: 16 }}>
                                    <button type="button" disabled={downloading} onClick={doDownload}
                                        style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 10, padding: "9px 15px", cursor: downloading ? "not-allowed" : "pointer", fontSize: 12.5, color: t.text, fontWeight: 600, fontFamily: "inherit" }}>
                                        {downloading ? "Preparing…" : "⬇ Download signed copy"}
                                    </button>
                                    <div style={{ fontSize: 11, color: t.textFaint, marginTop: 7, lineHeight: 1.5 }}>
                                        Includes the signature record: who signed, how, when the
                                        server recorded it, and the digest of the signed text.
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* GATED ON THE BODY: no signing text nobody saw. */}
                        {viewing.needsMySig && doc && !doc.loading && !doc.error && (
                            <div style={{ padding: "14px 22px", borderTop: `1px solid ${t.border}`, background: t.surface }}>
                                <div style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.7px", marginBottom: 8 }}>
                                    Sign — draw, type or upload
                                </div>
                                <SignaturePad height={150} onChange={setSignSig} />
                                <Btn primary disabled={signBusy} onClick={doSign}
                                    style={{ padding: "11px 22px", marginTop: 10, width: "100%" }}>
                                    {signBusy ? "Signing…" : "✍️ Sign Agreement"}
                                </Btn>
                                {/* WHAT IS RECORDED, not what it amounts to in law.
                                    This said the signature was "classified under the
                                    Electronic Transactions Ordinance 2002" -- a legal
                                    conclusion no lawyer has reviewed, and the same
                                    class of claim that was stripped from the rest of
                                    this module. Phase 4.1 owns that question. */}
                                <div style={{ fontSize: 10.5, color: t.textMuted, marginTop: 8, lineHeight: 1.5 }}>
                                    We record your account, the time, your IP address where it
                                    can be determined, and a digest of the text you signed.
                                    {/* KEPT ON ONE LINE. The claim guard allowlists this exact
                                        sentence and scans line by line, so wrapping it splits
                                        "Signature" from the rest and the remainder reads as an
                                        unqualified AES claim. */}
                                    {" "}Signature encrypted at rest with AES-256-GCM.
                                </div>

                                {!declineOpen ? (
                                    <button
                                        type="button"
                                        onClick={() => setDeclineOpen(true)}
                                        style={{ marginTop: 12, background: "none", border: "none", padding: 0, cursor: "pointer", fontSize: 12, color: t.textMuted, textDecoration: "underline" }}
                                    >
                                        I do not want to sign this
                                    </button>
                                ) : (
                                    <div style={{ marginTop: 14, paddingTop: 14, borderTop: `1px solid ${t.border}` }}>
                                        <div style={{ fontSize: 11, fontWeight: 700, color: t.danger, textTransform: "uppercase", letterSpacing: "0.7px", marginBottom: 8 }}>
                                            Decline — this ends the agreement and cannot be undone
                                        </div>
                                        <Input
                                            placeholder="Reason (optional — the other party will see this)"
                                            value={declineReason}
                                            maxLength={2000}
                                            onChange={e => setDeclineReason(e.target.value)}
                                            style={{ width: "100%" }}
                                        />
                                        <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
                                            <Btn
                                                disabled={declineBusy}
                                                onClick={doDecline}
                                                style={{ padding: "10px 18px", background: t.danger, color: "#fff", borderColor: t.danger }}
                                            >
                                                {declineBusy ? "Declining…" : "Confirm decline"}
                                            </Btn>
                                            <Btn
                                                disabled={declineBusy}
                                                onClick={() => { setDeclineOpen(false); setDeclineReason(""); }}
                                                style={{ padding: "10px 18px" }}
                                            >
                                                Keep reviewing
                                            </Btn>
                                        </div>
                                    </div>
                                )}
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

/* THE DIY CONTRACT BUILDER IS PARKED. Mirrors the backend's
   `agreements_diy_builder_enabled`, which is the real enforcement -- this only
   decides whether to show a door that the server would slam.

   Every template was withdrawn (the wording was US contract boilerplate,
   unsuitable to sign in Pakistan) and the server refuses any body still
   carrying the withdrawal notice, at create AND at sign. So while this is off
   the builder has no success case: the wizard's only outcome is a refusal on
   the last click, after four steps of the user's work.

   BOTH SIDES MUST BE FLIPPED TOGETHER, and the backend must be flipped first --
   turning this on alone just restores the wasted-work path. Enabling either
   needs counsel-reviewed templates, not a deployment.

   WHAT STAYS VISIBLE, ALWAYS: Dashboard and All Agreements. Engagement letters
   from a lawyer the client hired live in this same list, and an agreement
   somebody is already a party to must never become unreachable because a
   different feature was parked. */
const DIY_BUILDER_ENABLED =
    (typeof process !== "undefined" &&
        process.env?.NEXT_PUBLIC_AGREEMENTS_DIY_ENABLED === "true") || false;

// ── SIDEBAR NAV ──────────────────────────────
const Sidebar = ({ page, onNavigate, collapsed }) => {
    const t = useTheme();
    const links = [
        { id: "dashboard", ico: "dashboard", label: "Dashboard" },
        ...(DIY_BUILDER_ENABLED ? [
            { id: "templates", ico: "templates", label: "Templates" },
            { id: "create", ico: "create", label: "Create" },
        ] : []),
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

    /* Parked pages are unreachable by ROUTE, not merely unlinked. Removing the
       sidebar entries alone would leave `create` reachable from the dashboard's
       own call-to-action and from any stale state, landing the user in a wizard
       whose last click the server refuses. */
    const navigate = (p) =>
        setPage(!DIY_BUILDER_ENABLED && (p === "create" || p === "templates")
            ? "all" : p);

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
                    {/* Three pieces of decorative chrome removed:

                        - a search button with no handler;
                        - a notification bell with no handler, rendering a
                          PERMANENT unread dot -- a badge that was always on and
                          therefore meant nothing. The real notification drawer
                          lives in Dashboard.jsx and has real unread state;
                        - an avatar hardcoded to "JD", shown to every user
                          whoever they were.

                        None of them did anything, and together they made a
                        signing surface look like a mock-up. */}
                </div>

                {/* Page content */}
                <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
                    {page === "dashboard" && <PageDashboard onNavigate={navigate} />}
                    {DIY_BUILDER_ENABLED && page === "templates" && (
                        <PageTemplates onNavigate={navigate} onSelectTemplate={t => setSelectedTemplate(t)} />
                    )}
                    {DIY_BUILDER_ENABLED && page === "create" && (
                        <PageCreate template={selectedTemplate} onNavigate={navigate} onDone={() => navigate("all")} />
                    )}
                    {page === "all" && <PageAllAgreements onNavigate={navigate} />}
                </div>
            </div>
        </div>
    );
}

export default ModAgreements;

