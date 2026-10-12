'use client';
// Paste your ModAgreements.jsx code here
import React, { useState, Fragment, useRef, useCallback, useEffect } from "react";
import { createPortal } from "react-dom";
import { useT } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import Ic from "./Ic.jsx";
import { LIcon } from "./documents/icons.jsx";
// The Documents module's typeface (Nunito Sans), so the two paperwork
// modules read as one product (2026-10-11).
import { DOCS_FONT as AG_FONT } from "./documents/ui.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput, Badge } from "@/components/shared/shared.jsx";
import SignaturePad from "@/components/shared/SignaturePad.jsx";
import { useAuth } from "@/context/AuthContext.jsx";
import AgreementBody from "@/components/shared/AgreementBody.jsx";
import { textToAgreementHtml, agreementPlainText } from "@/lib/agreementHtml.js";
import { AGREEMENTS_DIY_ENABLED, AGREEMENTS_VIEW_EVENT, takePendingAgreementsView, announceAgreementsView } from "@/lib/agreementsNav.js";
import { previewAgreementBody, createAgreement, getAgreement, signAgreement, declineAgreement, listAgreements, searchLawyers, downloadExecutedAgreement, idempotencyKey, reissueAgreementInvitation, archiveAgreement, unarchiveAgreement } from "@/lib/api.js";

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
        fontFamily: "inherit", fontWeight: 600, fontSize: 13, cursor: disabled ? "not-allowed" : "pointer",
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
            fontFamily: "inherit", boxSizing: "border-box",
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
/* The Agreements dashboard (2026-10-11), in the Overview's look: its own
 * scoped CSS on [data-ag-dash], fed the client tokens. Every number and row is
 * the client's real agreements; nothing here is sample data. */
const AG_DASH_CSS = `[data-ag-dash]{display:flex;flex-direction:column;gap:18px;color:var(--ink)}
[data-ag-dash] .ad-card{position:relative;border-radius:18px;border:1px solid color-mix(in srgb,var(--brand-text) 14%,var(--line));background:radial-gradient(120% 110% at 100% 0%,color-mix(in srgb,var(--c,var(--brand-text)) 9%,transparent) 0%,transparent 55%),linear-gradient(180deg,color-mix(in srgb,var(--surface) 88%,#fff 12%),var(--surface));box-shadow:inset 0 1px 0 rgba(255,255,255,.1),inset 0 -3px 0 rgba(0,0,0,.2),0 14px 28px -16px rgba(0,0,0,.7)}
[data-ag-dash] .ad-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px}
[data-ag-dash] .ad-head h1{margin:0;font-size:28px;font-weight:800;font-family:inherit;color:var(--ink)}
[data-ag-dash] .ad-head p{margin:5px 0 0;font-size:14px;color:var(--muted)}
[data-ag-dash] .ad-new{display:inline-flex;align-items:center;gap:8px;height:42px;padding:0 20px;border:0;border-radius:999px;background:linear-gradient(135deg,#12897f,#1c9c66);color:#fff;font:inherit;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 8px 20px -10px rgba(28,156,102,.85);transition:filter .15s,transform .12s}
[data-ag-dash] .ad-new:hover{filter:brightness(1.08)}
[data-ag-dash] .ad-new:active{transform:scale(.96)}
[data-ag-dash] .ad-new svg{transition:transform .3s cubic-bezier(.3,1.4,.5,1)}
[data-ag-dash] .ad-new:hover svg{transform:rotate(90deg)}
[data-ag-dash] .ad-need{display:flex;align-items:center;gap:14px;padding:14px 18px;border-color:color-mix(in srgb,var(--gold) 45%,transparent);background:linear-gradient(90deg,color-mix(in srgb,var(--gold) 14%,var(--surface-2)),var(--surface-2) 65%)}
[data-ag-dash] .ad-badge{width:38px;height:38px;flex:none;border-radius:50%;display:grid;place-items:center;background:#fff;color:#12897f;font-weight:800;font-size:15px;box-shadow:0 6px 14px -8px rgba(0,0,0,.6)}
[data-ag-dash] .ad-need b{display:block;font-size:15px}
[data-ag-dash] .ad-need small{display:block;margin-top:2px;font-size:13px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-ag-dash] .ad-go{display:inline-flex;align-items:center;gap:8px;height:38px;padding:0 18px;border:0;border-radius:999px;background:linear-gradient(135deg,#12897f,#1c9c66);color:#fff;font:inherit;font-size:13.5px;font-weight:700;cursor:pointer;flex:none;box-shadow:0 8px 20px -10px rgba(28,156,102,.85)}
[data-ag-dash] .ad-go:hover{filter:brightness(1.08)}
[data-ag-dash] .ad-go .arr{display:inline-block;transition:transform .2s}
[data-ag-dash] .ad-go:hover .arr{transform:translateX(3px)}
[data-ag-dash] .ad-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
[data-ag-dash] .ad-stat{display:flex;flex-direction:column;gap:12px;padding:18px 20px;transition:transform .2s cubic-bezier(.22,1,.36,1),box-shadow .2s,border-color .2s}
[data-ag-dash] .ad-stat:hover{transform:translateY(-3px);border-color:color-mix(in srgb,var(--c) 45%,var(--line))}
[data-ag-dash] .ad-stat .top{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
[data-ag-dash] .ad-stat .lbl{font-size:13px;font-weight:600;color:var(--muted)}
[data-ag-dash] .ad-stat .n{font-size:32px;font-weight:800;line-height:1;font-family:inherit}
[data-ag-dash] .ad-ic{width:42px;height:42px;flex:none;border-radius:12px;display:grid;place-items:center;color:var(--c);background:color-mix(in srgb,var(--c) 17%,transparent)}
[data-ag-dash] .ad-acts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
[data-ag-dash] .ad-act{display:flex;align-items:center;gap:16px;padding:18px 20px;text-align:left;font:inherit;color:var(--ink);cursor:pointer;transition:border-color .2s,transform .2s}
[data-ag-dash] .ad-act:hover{border-color:color-mix(in srgb,var(--c) 50%,var(--line));transform:translateY(-2px)}
[data-ag-dash] .ad-act b{display:block;font-size:15.5px}
[data-ag-dash] .ad-act small{display:block;margin-top:3px;font-size:13px;color:var(--muted)}
[data-ag-dash] .ad-act .ad-ic{width:48px;height:48px}
[data-ag-dash] .ad-arrow{margin-left:auto;width:38px;height:38px;flex:none;border-radius:50%;display:grid;place-items:center;color:var(--c);background:color-mix(in srgb,var(--c) 15%,transparent);transition:background .2s,color .2s,transform .2s}
[data-ag-dash] .ad-act:hover .ad-arrow{background:var(--c);color:#04262c;transform:translateX(3px)}
[data-ag-dash] .ad-recent{padding:0;overflow:hidden}
[data-ag-dash] .ad-recent-head{display:flex;align-items:center;justify-content:space-between;padding:14px 20px}
[data-ag-dash] .ad-recent-head h2{margin:0;font-size:16px;font-weight:700;font-family:inherit}
[data-ag-dash] .ad-btn{--a:var(--brand-text);display:inline-flex;align-items:center;justify-content:center;gap:6px;height:32px;padding:0 14px;border-radius:999px;border:1px solid color-mix(in srgb,var(--a) 38%,transparent);background:color-mix(in srgb,var(--a) 13%,var(--surface));color:var(--a);font:inherit;font-size:12.5px;font-weight:700;cursor:pointer;white-space:nowrap;transition:background .2s,color .2s,border-color .2s,transform .12s}
[data-ag-dash] .ad-btn:hover{background:var(--a);border-color:transparent;color:#04262c}
[data-ag-dash] .ad-btn:active{transform:scale(.95);filter:brightness(.9)}
[data-ag-dash] .ad-btn.solid{background:var(--a);border-color:transparent;color:#04262c}
[data-ag-dash] .ad-row{display:grid;grid-template-columns:40px minmax(0,1fr) 170px 110px 120px;gap:14px;align-items:center;width:100%;padding:13px 20px;border:0;border-top:1px solid var(--line);background:transparent;text-align:left;font:inherit;color:var(--ink)}
[data-ag-dash] .ad-row .ad-ic{width:40px;height:40px;border-radius:11px}
[data-ag-dash] .ad-row b{display:block;font-size:14.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-ag-dash] .ad-row small{display:block;margin-top:2px;font-size:12.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-ag-dash] .ad-bar{height:6px;border-radius:6px;background:var(--line);overflow:hidden}
[data-ag-dash] .ad-bar i{display:block;height:100%;border-radius:6px;background:var(--c)}
[data-ag-dash] .ad-prog small{margin-top:5px;font-size:12px}
[data-ag-dash] .ad-chip{display:inline-flex;align-items:center;justify-content:center;height:26px;padding:0 11px;border-radius:999px;font-size:12px;font-weight:700;color:var(--c);background:color-mix(in srgb,var(--c) 15%,transparent);white-space:nowrap;width:max-content}
[data-ag-dash] .ad-empty{padding:26px 20px 30px;border-top:1px solid var(--line);text-align:center;font-size:13.5px;color:var(--muted);line-height:1.6}
@media (prefers-reduced-motion:reduce){[data-ag-dash] *{transition:none!important}}`;

// One colour per kind of thing, as on the Overview.
/* The All agreements list (2026-10-11), the same look as the dashboard. */
const AG_ALL_CSS = `[data-ag-all] .al-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:18px}
[data-ag-all] .al-head h1{margin:0;font-size:28px;font-weight:800;font-family:inherit;color:var(--ink)}
[data-ag-all] .al-head p{margin:5px 0 0;font-size:14px;color:var(--muted)}
[data-ag-all] .al-search{display:flex;align-items:center;gap:8px;width:280px;height:42px;padding:0 16px;box-sizing:border-box;border-radius:999px;background:var(--surface);border:1px solid var(--line);color:var(--faint);transition:border-color .15s,box-shadow .15s}
[data-ag-all] .al-search:focus-within{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-ag-all] .al-search input{flex:1;min-width:0;border:0;outline:none;background:transparent;color:var(--ink);font:inherit;font-size:13.5px}
[data-ag-all] .al-search input::placeholder{color:var(--faint)}
[data-ag-all] .al-new{display:inline-flex;align-items:center;gap:8px;height:42px;padding:0 20px;border:0;border-radius:999px;background:linear-gradient(135deg,#12897f,#1c9c66);color:#fff;font:inherit;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 8px 20px -10px rgba(28,156,102,.85)}
[data-ag-all] .al-new:hover{filter:brightness(1.08)}
[data-ag-all] .al-new svg{transition:transform .3s cubic-bezier(.3,1.4,.5,1)}
[data-ag-all] .al-new:hover svg{transform:rotate(90deg)}
[data-ag-all] .al-bar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:16px}
[data-ag-all] .al-seg{display:flex;gap:4px;padding:4px;border-radius:999px;background:var(--surface);border:1px solid var(--line)}
[data-ag-all] .al-seg button{height:34px;padding:0 16px;border:0;border-radius:999px;background:transparent;color:var(--muted);font:inherit;font-size:13.5px;font-weight:600;cursor:pointer;transition:background .15s,color .15s}
[data-ag-all] .al-seg button:hover{color:var(--ink);background:var(--hover)}
[data-ag-all] .al-seg button[aria-pressed="true"]{background:var(--ink);color:var(--bg)}
[data-ag-all] .al-arch{display:inline-flex;align-items:center;gap:8px;height:38px;padding:0 14px;border-radius:999px;border:1px solid var(--line-strong);background:transparent;color:var(--muted);font:inherit;font-size:13px;font-weight:600;cursor:pointer;transition:background .15s,color .15s,border-color .15s}
[data-ag-all] .al-arch:hover{color:var(--ink);border-color:var(--muted)}
[data-ag-all] .al-arch[aria-pressed="true"]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
[data-ag-all] .al-table{border-radius:18px;border:1px solid color-mix(in srgb,var(--brand-text) 14%,var(--line));background:linear-gradient(180deg,color-mix(in srgb,var(--surface) 88%,#fff 12%),var(--surface));box-shadow:inset 0 1px 0 rgba(255,255,255,.1),0 14px 28px -16px rgba(0,0,0,.7)}
[data-ag-all] .al-grid{display:grid;grid-template-columns:minmax(0,2.3fr) minmax(0,1.5fr) 120px 150px 150px;gap:16px;align-items:center;min-width:820px}
[data-ag-all] .al-th{padding:11px 22px;font-size:11px;font-weight:700;letter-spacing:.1em;color:var(--faint);background:color-mix(in srgb,var(--surface-2) 70%,transparent);border-radius:18px 18px 0 0;border-bottom:1px solid var(--line)}
[data-ag-all] .al-tr{padding:14px 22px;border-bottom:1px solid var(--line);cursor:pointer;transition:background .15s}
[data-ag-all] .al-tr:hover{background:color-mix(in srgb,var(--c) 7%,transparent)}
[data-ag-all] .al-ic{width:40px;height:40px;flex:none;border-radius:11px;display:grid;place-items:center;color:var(--c);background:color-mix(in srgb,var(--c) 17%,transparent)}
[data-ag-all] .al-title{font-size:14.5px;font-weight:600;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-ag-all] .al-sub{margin-top:2px;font-size:12.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-ag-all] .al-avs{display:flex;align-items:center}
[data-ag-all] .al-av{width:30px;height:30px;flex:none;border-radius:50%;display:grid;place-items:center;font-size:10.5px;font-weight:800;color:var(--c);background:color-mix(in srgb,var(--c) 20%,var(--surface));border:2px solid var(--surface);box-sizing:border-box}
[data-ag-all] .al-av+.al-av{margin-left:-8px}
[data-ag-all] .al-chip{display:inline-flex;align-items:center;gap:6px;height:26px;padding:0 11px;border-radius:999px;font-size:12px;font-weight:700;color:var(--c);background:color-mix(in srgb,var(--c) 15%,transparent);white-space:nowrap;width:max-content}
[data-ag-all] .al-chip i{width:6px;height:6px;border-radius:50%;background:currentColor}
[data-ag-all] .al-pbar{height:6px;border-radius:6px;background:var(--line);overflow:hidden}
[data-ag-all] .al-pbar i{display:block;height:100%;border-radius:6px;background:var(--c)}
[data-ag-all] .al-acts{display:flex;align-items:center;justify-content:flex-end;gap:4px}
[data-ag-all] .al-btn{--a:var(--brand-text);display:inline-flex;align-items:center;justify-content:center;gap:6px;height:32px;padding:0 14px;border-radius:999px;border:1px solid color-mix(in srgb,var(--a) 38%,transparent);background:color-mix(in srgb,var(--a) 13%,var(--surface));color:var(--a);font:inherit;font-size:12.5px;font-weight:700;cursor:pointer;white-space:nowrap;transition:background .2s,color .2s,border-color .2s,transform .12s}
[data-ag-all] .al-btn:hover{background:var(--a);border-color:transparent;color:#04262c}
[data-ag-all] .al-btn:active{transform:scale(.95);filter:brightness(.9)}
[data-ag-all] .al-btn.solid{background:var(--a);border-color:transparent;color:#04262c}
[data-ag-all] .al-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 22px;flex-wrap:wrap;font-size:12.5px;color:var(--muted)}
[data-ag-all] .al-empty{padding:44px 20px;text-align:center;color:var(--muted);font-size:13.5px;line-height:1.6}
[data-ag-all] .al-empty b{display:block;margin-bottom:4px;font-size:15px;color:var(--ink)}
@media (prefers-reduced-motion:reduce){[data-ag-all] *{transition:none!important}}`;

const AD_MINT = "#3ee0a1", AD_GOLD = "#f2c35e", AD_CYAN = "#6addeb", AD_LAV = "#b9a6f2", AD_CORAL = "#f28b80";

const AdIcon = ({ d, s = 20, w = 2 }) => (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={w} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
);
const AD_PATH = {
    file: "M14 2H6v20h12V8zM14 2v6h6",
    pen: "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z",
    clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
    check: "M5 12l4 4 10-10",
    plus: "M12 5v14M5 12h14",
    scale: "M12 3v18M7 21h10M5 7h14M5 7l-3 7a3.2 3.2 0 0 0 6 0L5 7zM19 7l-3 7a3.2 3.2 0 0 0 6 0l-3-7z",
    x: "M6 6l12 12M18 6L6 18",
    arrow: "M5 12h14M13 6l6 6-6 6",
};

/* How a row reads: its colour, chip, icon and the one button that moves it on. */
const rowLook = (a) => {
    if (a.needsMySig) return { c: AD_GOLD, chip: "Needs you", icon: a.isEngagementLetter ? "scale" : "pen", act: "sign" };
    if (a.status === "Signed") return { c: AD_MINT, chip: "Signed", icon: "check", act: "pdf" };
    if (a.status === "Rejected") return { c: AD_CORAL, chip: "Rejected", icon: "x", act: "open" };
    if (a.status === "Draft") return { c: "#9aa8a6", chip: "Draft", icon: "file", act: "open" };
    return { c: AD_CYAN, chip: "Pending", icon: a.isEngagementLetter ? "scale" : "file", act: "open" };
};

const PageDashboard = ({ onNavigate }) => {
    const { user } = useAuth();
    const toast = useToast();
    const [agmts, loading, , meta] = useMyAgreements(user?._id);
    const waitingMe = agmts.filter(a => a.needsMySig);
    const stats = [
        // The server's total, not the loaded page's length.
        { label: "All agreements", val: meta?.total ?? agmts.length, c: AD_MINT, icon: "file" },
        { label: "Waiting on me", val: waitingMe.length, c: AD_GOLD, icon: "pen", hot: waitingMe.length > 0 },
        { label: "Waiting on others", val: agmts.filter(a => a.status === "Pending" && !a.needsMySig).length, c: AD_CYAN, icon: "clock" },
        { label: "Signed by everyone", val: agmts.filter(a => a.status === "Signed").length, c: AD_LAV, icon: "check" },
    ];
    const download = async (a) => {
        const { error } = await downloadExecutedAgreement(a.id, `${a.name}.pdf`);
        if (error) toast.show("\u274c " + (error.message || "Could not download it"), "danger");
        else toast.show("\u2b07 Downloaded", "success");
    };
    const recent = agmts.slice(0, 5);
    return (
        <div data-ag-dash="">
            <style>{AG_DASH_CSS}</style>
            <header className="ad-head">
                <div>
                    <h1>Agreements</h1>
                    <p>Agreements you are part of, and the ones waiting on you.</p>
                </div>
                {DIY_BUILDER_ENABLED && (
                    <button type="button" className="ad-new" onClick={() => onNavigate("templates")}>
                        <AdIcon d={AD_PATH.plus} s={16} w={2.6} /> New agreement
                    </button>
                )}
            </header>

            {waitingMe.length > 0 && (
                <section className="ad-card ad-need" aria-label="Waiting for your signature">
                    <span className="ad-badge">{waitingMe.length}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <b>{waitingMe.length === 1 ? "1 agreement needs your signature" : `${waitingMe.length} agreements need your signature`}</b>
                        <small>{waitingMe.slice(0, 3).map(a => a.name).join(" · ")}</small>
                    </div>
                    <button type="button" className="ad-go" onClick={() => onNavigate("all", { filter: "Pending" })}>
                        Review now <span className="arr" aria-hidden="true"><LIcon name="arrowRight" size={15} stroke={2.2} /></span>
                    </button>
                </section>
            )}

            <div className="ad-stats">
                {stats.map(s => (
                    <div key={s.label} className="ad-card ad-stat" style={{ "--c": s.c }}>
                        <div className="top">
                            <span className="lbl">{s.label}</span>
                            <span className="ad-ic"><AdIcon d={AD_PATH[s.icon]} /></span>
                        </div>
                        <span className="n" style={s.hot ? { color: s.c } : undefined}>{loading ? "–" : s.val}</span>
                    </div>
                ))}
            </div>

            <div className="ad-acts">
                {/* "Create" is dropped while the builder is parked rather than
                    shown and redirected: a card that advertises a feature and
                    then lands somewhere else is its own small lie. */}
                {DIY_BUILDER_ENABLED && (
                    <button type="button" className="ad-card ad-act" style={{ "--c": AD_MINT }} onClick={() => onNavigate("templates")}>
                        <span className="ad-ic"><AdIcon d={AD_PATH.plus} s={22} w={2.4} /></span>
                        <span><b>Create an agreement</b><small>Start from a template or a blank page</small></span>
                        <span className="ad-arrow"><AdIcon d={AD_PATH.arrow} s={17} /></span>
                    </button>
                )}
                <button type="button" className="ad-card ad-act" style={{ "--c": AD_GOLD }} onClick={() => onNavigate("all", { filter: "Pending" })}>
                    <span className="ad-ic"><AdIcon d={AD_PATH.pen} s={22} /></span>
                    <span><b>Sign what's waiting</b><small>Opens your agreements that are still pending</small></span>
                    <span className="ad-arrow"><AdIcon d={AD_PATH.arrow} s={17} /></span>
                </button>
            </div>

            <section className="ad-card ad-recent" aria-label="Recent agreements">
                <div className="ad-recent-head">
                    <h2>Recent agreements</h2>
                    <button type="button" className="ad-btn" style={{ "--a": AD_CYAN }} onClick={() => onNavigate("all")}>See all</button>
                </div>
                {loading ? (
                    <div className="ad-empty">Loading…</div>
                ) : recent.length === 0 ? (
                    <div className="ad-empty">
                        {DIY_BUILDER_ENABLED
                            ? "No agreements yet. When a lawyer sends you an engagement letter, it appears here, or create one yourself."
                            : "No agreements yet. Agreements shared with you appear here for you to read and sign."}
                    </div>
                ) : recent.map(a => {
                    const look = rowLook(a);
                    const pct = a.totalParties ? Math.round((a.signedCount / a.totalParties) * 100) : 0;
                    const progress = a.status === "Signed" ? "All signed"
                        : `${a.signedCount} of ${a.totalParties} signed`;
                    return (
                        <div key={a.id} className="ad-row" style={{ "--c": look.c }}>
                            <span className="ad-ic"><AdIcon d={AD_PATH[look.icon]} s={18} w={look.icon === "check" ? 2.4 : 2} /></span>
                            <div style={{ minWidth: 0 }}>
                                <b>{a.name}</b>
                                <small>{a.isEngagementLetter ? "Engagement letter" : "Agreement"}{a.date ? ` · ${a.date}` : ""}</small>
                            </div>
                            <div className="ad-prog">
                                <div className="ad-bar"><i style={{ width: `${pct}%` }} /></div>
                                <small>{progress}</small>
                            </div>
                            <span className="ad-chip">{look.chip}</span>
                            {look.act === "sign" ? (
                                <button type="button" className="ad-btn solid" style={{ "--a": AD_MINT }} onClick={() => onNavigate("all", { filter: "Pending" })}>Sign</button>
                            ) : look.act === "pdf" ? (
                                <button type="button" className="ad-btn" style={{ "--a": AD_LAV }} onClick={() => download(a)}>PDF ↓</button>
                            ) : (
                                <button type="button" className="ad-btn" style={{ "--a": AD_CYAN }} onClick={() => onNavigate("all")}>Open</button>
                            )}
                        </div>
                    );
                })}
            </section>
        </div>
    );
};

// ── PAGE: TEMPLATE GALLERY ───────────────────
/* The gallery (2026-10-11), in the dashboard's look. The withdrawal notice is
 * said ONCE, above the grid, instead of the same paragraph in every card; each
 * card still carries a short "Under review" mark, so no card reads as ready. */
const AG_TPL_CSS = `[data-ag-tpl] .tp-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:18px}
[data-ag-tpl] .tp-head h1{margin:0;font-size:28px;font-weight:800;font-family:inherit;color:var(--ink)}
[data-ag-tpl] .tp-head p{margin:5px 0 0;font-size:14px;color:var(--muted)}
[data-ag-tpl] .tp-search{display:flex;align-items:center;gap:8px;width:260px;height:42px;padding:0 16px;box-sizing:border-box;border-radius:999px;background:var(--surface);border:1px solid var(--line);color:var(--faint);transition:border-color .15s,box-shadow .15s}
[data-ag-tpl] .tp-search:focus-within{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-ag-tpl] .tp-search input{flex:1;min-width:0;border:0;outline:none;background:transparent;color:var(--ink);font:inherit;font-size:13.5px}
[data-ag-tpl] .tp-search input::placeholder{color:var(--faint)}
[data-ag-tpl] .tp-note{display:flex;gap:14px;align-items:center;padding:14px 18px;margin-bottom:18px;border-radius:14px;background:color-mix(in srgb,var(--gold) 10%,var(--surface));border:1px solid color-mix(in srgb,var(--gold) 40%,transparent);font-size:13.5px;line-height:1.5;color:var(--ink)}
[data-ag-tpl] .tp-note b{color:var(--gold)}
[data-ag-tpl] .tp-note .ic{width:34px;height:34px;flex:none;border-radius:50%;display:grid;place-items:center;color:var(--gold);background:color-mix(in srgb,var(--gold) 20%,transparent)}
[data-ag-tpl] .tp-cats{display:flex;gap:4px;padding:4px;margin-bottom:18px;border-radius:999px;background:var(--surface);border:1px solid var(--line);width:max-content;max-width:100%;flex-wrap:wrap}
[data-ag-tpl] .tp-cats button{height:34px;padding:0 16px;border:0;border-radius:999px;background:transparent;color:var(--muted);font:inherit;font-size:13.5px;font-weight:600;cursor:pointer;transition:background .15s,color .15s}
[data-ag-tpl] .tp-cats button:hover{color:var(--ink);background:var(--hover)}
[data-ag-tpl] .tp-cats button[aria-pressed="true"]{background:var(--ink);color:var(--bg)}
[data-ag-tpl] .tp-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:16px}
[data-ag-tpl] .tp-card{position:relative;display:flex;flex-direction:column;gap:8px;padding:20px;border-radius:18px;text-align:left;font:inherit;color:var(--ink);cursor:pointer;border:1px solid color-mix(in srgb,var(--brand-text) 14%,var(--line));background:radial-gradient(120% 110% at 100% 0%,color-mix(in srgb,var(--c) 10%,transparent) 0%,transparent 55%),linear-gradient(180deg,color-mix(in srgb,var(--surface) 88%,#fff 12%),var(--surface));box-shadow:inset 0 1px 0 rgba(255,255,255,.1),inset 0 -3px 0 rgba(0,0,0,.2),0 14px 28px -16px rgba(0,0,0,.7);transition:transform .2s cubic-bezier(.22,1,.36,1),border-color .2s,box-shadow .2s}
[data-ag-tpl] .tp-card:hover{transform:translateY(-3px);border-color:color-mix(in srgb,var(--c) 50%,var(--line));box-shadow:inset 0 1px 0 rgba(255,255,255,.12),0 18px 30px -16px color-mix(in srgb,var(--c) 60%,#000)}
[data-ag-tpl] .tp-card:focus-visible{outline:2px solid var(--c);outline-offset:2px}
[data-ag-tpl] .tp-card.blank{border:1.5px dashed color-mix(in srgb,var(--c) 60%,transparent);background:transparent;box-shadow:none}
[data-ag-tpl] .tp-top{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:6px}
[data-ag-tpl] .tp-ic{width:46px;height:46px;flex:none;border-radius:13px;display:grid;place-items:center;color:var(--c);background:color-mix(in srgb,var(--c) 17%,transparent);transition:transform .25s cubic-bezier(.3,1.4,.5,1)}
[data-ag-tpl] .tp-card:hover .tp-ic{transform:scale(1.08) rotate(-4deg)}
[data-ag-tpl] .tp-flag{display:inline-flex;align-items:center;gap:5px;height:22px;padding:0 9px;border-radius:999px;font-size:11px;font-weight:700;color:var(--gold);background:color-mix(in srgb,var(--gold) 14%,transparent);white-space:nowrap}
[data-ag-tpl] .tp-tag{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--c)}
[data-ag-tpl] .tp-card h3{margin:0;font-size:16.5px;font-weight:700;font-family:inherit}
[data-ag-tpl] .tp-card p{margin:0;flex:1;font-size:13px;line-height:1.55;color:var(--muted)}
[data-ag-tpl] .tp-use{display:inline-flex;align-items:center;justify-content:center;gap:8px;height:38px;margin-top:10px;border-radius:999px;font-size:13.5px;font-weight:700;color:var(--c);background:color-mix(in srgb,var(--c) 14%,transparent);border:1px solid color-mix(in srgb,var(--c) 35%,transparent);transition:background .2s,color .2s}
[data-ag-tpl] .tp-use .arr{display:inline-block;transition:transform .2s}
[data-ag-tpl] .tp-card:hover .tp-use{background:var(--c);color:#04262c;border-color:transparent}
[data-ag-tpl] .tp-card:hover .tp-use .arr{transform:translateX(3px)}
[data-ag-tpl] .tp-empty{padding:40px 20px;text-align:center;color:var(--muted);font-size:13.5px}
@media (prefers-reduced-motion:reduce){[data-ag-tpl] *{transition:none!important}}`;

/* Each template's colour and icon, by name. */
const TPL_LOOK = {
    "Employment Contract": { c: "#f2c35e", d: "M3 7h18v13H3zM9 7V4h6v3" },
    "Non-Disclosure Agreement": { c: "#b9a6f2", d: "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4" },
    "Lease Agreement": { c: "#6addeb", d: "M3 11l9-8 9 8v10H3zM9 21v-6h6v6" },
    "Service Agreement": { c: "#6addeb", d: "M14 2H6v20h12V8zM14 2v6h6M9 13h6M9 17h4" },
    "Partnership Agreement": { c: "#b9a6f2", d: "M8 12a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM16 12a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM3 20c0-3 2.5-5 5-5s5 2 5 5M11 20c0-3 2.5-5 5-5s5 2 5 5" },
    "Freelancer Contract": { c: "#f2c35e", d: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 4-6 8-6s8 2 8 6" },
};

const PageTemplates = ({ onNavigate, onSelectTemplate }) => {
    const [cat, setCat] = useState("All");
    const [search, setSearch] = useState("");
    const cats = ["All", "Employment", "NDA", "Lease", "Service", "Partnership"];
    const filtered = TEMPLATES.filter(tmpl =>
        (cat === "All" || tmpl.cat === cat || tmpl.name.toLowerCase().includes(cat.toLowerCase())) &&
        tmpl.name.toLowerCase().includes(search.toLowerCase())
    );
    const start = (tmpl) => { onSelectTemplate(tmpl); onNavigate("create"); };
    const anyUnreviewed = TEMPLATES.some(x => x.unreviewed);
    return (
        <div data-ag-tpl="">
            <style>{AG_TPL_CSS}</style>
            <header className="tp-head">
                <div>
                    <h1>Agreement templates</h1>
                    <p>Pick a starting point. You can change every word before anyone signs.</p>
                </div>
                <label className="tp-search">
                    <AdIcon d="M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-4.3-4.3" s={16} />
                    <input aria-label="Search templates" placeholder="Search templates" value={search} onChange={e => setSearch(e.target.value)} />
                </label>
            </header>

            {/* Said once. The POPULAR badge and the per-card paragraph are gone:
                every template body is the withdrawal notice, and the backend
                refuses it at both create and sign. */}
            {anyUnreviewed && (
                <div className="tp-note" role="note">
                    <span className="ic"><AdIcon d="M12 3l10 18H2zM12 10v5M12 18h.01" s={17} w={2.2} /></span>
                    <span><b>Templates are under review.</b> Their wording was withdrawn pending review by a qualified Pakistani lawyer. You can start from one, but you must replace the notice with your own wording before it can be sent.</span>
                </div>
            )}

            <div className="tp-cats" role="group" aria-label="Filter by category">
                {cats.map(c => (
                    <button key={c} type="button" aria-pressed={cat === c} onClick={() => setCat(c)}>{c}</button>
                ))}
            </div>

            <div className="tp-grid">
                {cat === "All" && !search && (
                    <button type="button" className="tp-card blank" style={{ "--c": AD_MINT }} onClick={() => start(null)}>
                        <div className="tp-top"><span className="tp-ic"><AdIcon d={AD_PATH.plus} s={22} w={2.4} /></span></div>
                        <span className="tp-tag">Your own</span>
                        <h3>Blank agreement</h3>
                        <p>Start from an empty page and write your own terms.</p>
                        <span className="tp-use">Start blank <span className="arr" aria-hidden="true"><LIcon name="arrowRight" size={15} stroke={2.2} /></span></span>
                    </button>
                )}
                {filtered.map(tmpl => {
                    const look = TPL_LOOK[tmpl.name] || { c: AD_CYAN, d: AD_PATH.file };
                    return (
                        <button key={tmpl.name} type="button" className="tp-card" style={{ "--c": look.c }} onClick={() => start(tmpl)}>
                            <div className="tp-top">
                                <span className="tp-ic"><AdIcon d={look.d} s={22} /></span>
                                {tmpl.unreviewed && <span className="tp-flag" title="Wording withdrawn pending a lawyer's review">Under review</span>}
                            </div>
                            <span className="tp-tag">{tmpl.cat}</span>
                            <h3>{tmpl.name}</h3>
                            <p>{tmpl.desc}</p>
                            <span className="tp-use">Start from this <span className="arr" aria-hidden="true"><LIcon name="arrowRight" size={15} stroke={2.2} /></span></span>
                        </button>
                    );
                })}
            </div>
            {filtered.length === 0 && <div className="tp-empty">No template matches. Try another word or category.</div>}
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
   neither. The interim was a plain text box that looked like one.

   2026-10-11: the real thing, on the owner's decision. Every control below
   has a handler, and the body is now a declared rich format (`html`) that
   the server sanitises and the PDF and every viewer render -- so the
   formatting is delivered in both directions. See AgreementEditor. */


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

/* THE RICH EDITOR (2026-10-11). The body is `body_format: "html"`: what the
 * toolbar can make -- paragraphs, headings, bold, italic, underline,
 * strikethrough, alignment, lists, a quote, a divider -- and nothing else. The
 * server sanitises to exactly that allowlist and refuses a body it would have
 * to change (backend agreement_html), so the Review step shows the server's
 * canonical form and that is what is sent, hashed and signed.
 *
 * It replaced a plain-text bar whose note said bold and alignment could not be
 * offered: they could not while the body was plain text. It is no longer.
 *
 * The look is the lawyer drafting toolbar's, as the client's own copy, scoped
 * by [data-ag-tb]; it sticks to the top while the page scrolls under it. */
const AG_TB_CSS = `[data-ag-tb]{position:sticky;top:0;z-index:6;display:flex;align-items:center;gap:6px;margin-bottom:12px;padding:6px;border-radius:16px;border:1px solid var(--line);background:var(--surface);box-shadow:0 12px 24px -16px rgba(0,0,0,.8)}
[data-ag-tb] .tb-scroll{flex:1;min-width:0;display:flex;align-items:center;gap:2px;overflow-x:auto;overflow-y:hidden;scrollbar-width:none;padding:2px}
[data-ag-tb] .tb-scroll::-webkit-scrollbar{display:none}
[data-ag-tb] .tb-sep{flex:none;width:1px;height:22px;background:var(--line);margin:0 5px}
[data-ag-tb] .tb-btn{flex:none;position:relative;width:34px;height:34px;padding:0;border:0;border-radius:9px;background:transparent;color:var(--muted);display:inline-flex;align-items:center;justify-content:center;cursor:pointer;transition:background .15s,color .15s,transform .12s}
[data-ag-tb] .tb-btn:hover:not(:disabled){background:var(--hover);color:var(--ink)}
[data-ag-tb] .tb-btn:active:not(:disabled){transform:scale(.92)}
[data-ag-tb] .tb-btn[data-on="true"]{background:#3fd0e0;color:#062a30}
[data-ag-tb] .tb-btn:disabled{opacity:.4;cursor:not-allowed}
[data-ag-tb] .tb-pk{flex:none;display:inline-flex;align-items:center;gap:5px;height:34px;padding:0 6px 0 8px;border-radius:9px;border:1px solid var(--line);background:var(--surface-2);color:var(--ink);font:inherit;font-size:12.5px;font-weight:600;cursor:pointer;transition:border-color .15s}
[data-ag-tb] .tb-pk:hover,[data-ag-tb] .tb-pk[aria-expanded="true"]{border-color:#3fd0e0}
[data-ag-tb] .tb-pk > svg:first-child{color:var(--muted)}
[data-ag-tb] .tb-pk .v{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left}
[data-ag-tb] .tb-pk .chev{display:inline-flex;color:var(--muted);transition:transform .2s}
[data-ag-tb] .tb-pk[aria-expanded="true"] .chev{transform:rotate(180deg)}
.tb-pk-menu{position:fixed;z-index:80;font-family:${AG_FONT};max-height:260px;overflow-y:auto;padding:5px;border-radius:12px;background:var(--surface);border:1px solid var(--line);box-shadow:0 18px 36px -14px rgba(0,0,0,.75);scrollbar-width:thin}
.tb-pk-menu button{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;padding:7px 10px;border:0;border-radius:8px;background:transparent;color:var(--ink);font-size:13px;text-align:left;cursor:pointer;white-space:nowrap}
.tb-pk-menu button:hover{background:var(--hover)}
.tb-pk-menu button[aria-selected="true"]{background:color-mix(in srgb,#3fd0e0 18%,transparent);color:#3fd0e0;font-weight:700}
.tb-pk-menu .hint{font-size:11px;color:var(--faint);font-family:${AG_FONT};font-weight:500}
[data-ag-tb] .tb-color input{position:absolute;inset:0;opacity:0;cursor:pointer}
[data-ag-tb] .tb-color i{position:absolute;left:9px;right:9px;bottom:5px;height:3px;border-radius:2px}
[data-ag-tb] .tb-drop{position:relative;flex:none}
[data-ag-tb] .tb-pick{height:34px;padding:0 12px;border-radius:9px;border:1px solid var(--line);background:var(--surface-2);color:var(--ink);font:inherit;font-size:13px;font-weight:600;display:inline-flex;align-items:center;gap:7px;cursor:pointer;transition:border-color .15s}
[data-ag-tb] .tb-pick:hover,[data-ag-tb] .tb-pick[aria-expanded="true"]{border-color:#3fd0e0}
[data-ag-tb] .tb-pick .chev{color:var(--muted);transition:transform .2s}
[data-ag-tb] .tb-pick[aria-expanded="true"] .chev{transform:rotate(180deg)}
[data-ag-tb] .tb-menu{position:absolute;top:42px;right:0;z-index:50;min-width:200px;max-height:300px;overflow-y:auto;padding:6px;border-radius:12px;background:var(--surface);border:1px solid var(--line);box-shadow:0 18px 36px -14px rgba(0,0,0,.7)}
[data-ag-tb] .tb-menu button{display:block;width:100%;text-align:left;padding:8px 12px;border:0;border-radius:8px;background:transparent;color:var(--ink);font:inherit;font-size:13px;cursor:pointer}
[data-ag-tb] .tb-menu button:hover{background:var(--hover)}
[data-ag-page] .tb-count{font-size:12px;color:var(--muted);font-weight:500;white-space:nowrap}
[data-ag-page]{padding:10px 10px 8px;border-radius:16px;border:1px solid var(--line);background:var(--surface-2)}
[data-ag-page] [data-ag-paper]{min-height:520px;margin:0;padding:40px 52px;box-sizing:border-box;border-radius:6px;background:#fff;color:#202a2f;font-family:'Source Serif 4',Georgia,serif;font-size:16px;line-height:1.8;outline:none;box-shadow:0 8px 24px rgba(0,0,0,.18)}
[data-ag-page] [data-ag-paper]:focus{box-shadow:0 0 0 3px rgba(63,208,224,.45),0 8px 24px rgba(0,0,0,.18)}
[data-ag-paper] p,[data-ag-paper] div{margin:0 0 10px}
[data-ag-paper] h1{font-size:1.45em;margin:4px 0 12px}
[data-ag-paper] h2{font-size:1.2em;margin:14px 0 8px}
[data-ag-paper] h3{font-size:1.05em;margin:12px 0 6px}
[data-ag-paper] ul,[data-ag-paper] ol{margin:0 0 10px;padding-left:1.6em}
[data-ag-paper] blockquote{margin:0 0 10px;padding:4px 0 4px 14px;border-left:3px solid #9fb6b2;color:#4a5a5e}
[data-ag-paper] hr{border:0;border-top:1px solid #d9dfe0;margin:14px 0}
[data-ag-paper] a{color:#1a5fb4;text-decoration:underline}`;

/* The header's title field: reads as the page's subtitle until touched. */
const AG_TITLE_CSS = `.ag-nav{display:inline-flex;align-items:center;gap:8px;height:42px;padding:0 20px;border-radius:999px;font:inherit;font-size:14px;font-weight:700;cursor:pointer;transition:background .2s,border-color .2s,color .2s,filter .2s,transform .12s}
.ag-nav svg{transition:transform .2s}
.ag-nav:active{transform:scale(.96)}
.ag-nav:focus-visible{outline:2px solid #3fd0e0;outline-offset:2px}
.ag-nav.back{border:1px solid var(--line-strong);background:transparent;color:var(--ink)}
.ag-nav.back:hover{background:var(--surface);border-color:var(--muted)}
.ag-nav.back:hover svg{transform:translateX(-3px)}
.ag-nav.next{border:0;background:linear-gradient(135deg,#12897f,#1c9c66);color:#fff;box-shadow:0 8px 20px -10px rgba(28,156,102,.85)}
.ag-nav.next:hover{filter:brightness(1.08)}
.ag-nav.next:hover svg{transform:translateX(3px)}
.ag-back{width:40px;height:40px;flex:none;display:grid;place-items:center;border-radius:50%;border:1px solid var(--line);background:var(--surface);color:var(--ink);cursor:pointer;transition:background .2s,border-color .2s,color .2s,transform .12s}
.ag-back svg{transition:transform .2s}
.ag-back:hover{background:#3ee0a1;border-color:transparent;color:#06261c}
.ag-back:hover svg{transform:translateX(-3px)}
.ag-back:active{transform:scale(.93)}
.ag-back:focus-visible{outline:2px solid #3fd0e0;outline-offset:2px}
.ag-title{display:block;width:min(560px,60vw);margin-top:2px;padding:2px 6px;margin-left:-6px;border:1px solid transparent;border-radius:8px;background:transparent;color:var(--muted);font:inherit;font-size:13.5px;font-weight:600;outline:none;transition:border-color .15s,background .15s}
.ag-title:hover{border-color:var(--line)}
.ag-title:focus{border-color:#3fd0e0;background:var(--surface);color:var(--ink)}`;

// [command, Lucide icon, title, the state that lights it]
const TB_MARKS = [
    ["bold", "bold", "Bold"], ["italic", "italic", "Italic"], ["underline", "underline", "Underline"],
    ["strikeThrough", "strike", "Strikethrough"],
    ["subscript", "subscript", "Subscript"], ["superscript", "superscript", "Superscript"],
];
// [name, kind]. Must match FONT_FAMILIES on the server (agreement_html).
const TB_FONTS = [["Georgia", "Serif"], ["Times New Roman", "Serif"], ["Garamond", "Serif"],
    ["Arial", "Sans"], ["Verdana", "Sans"], ["Tahoma", "Sans"], ["Trebuchet MS", "Sans"],
    ["Calibri", "Sans"], ["Courier New", "Mono"]];
const TB_SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 28, 32, 36, 40, 48];
const TB_ALIGN = [
    ["justifyLeft", "alignLeft", "Align left"], ["justifyCenter", "alignCenter", "Centre"],
    ["justifyRight", "alignRight", "Align right"], ["justifyFull", "alignJustify", "Justify"],
];
const LIT_BY = ["bold", "italic", "underline", "strikeThrough", "subscript", "superscript", "justifyLeft", "justifyCenter",
    "justifyRight", "justifyFull", "insertUnorderedList", "insertOrderedList"];

/* A compact picker for the toolbar: a small button showing the current value,
 * and a menu of choices. The menu is position:fixed, so the sideways-scrolling
 * strip cannot clip it, and every press keeps the editor's selection (mousedown
 * is cancelled), so the choice lands on the words that were selected. */
const TbPicker = ({ label, icon, value, shown, width, options, onPick }) => {
    const [open, setOpen] = useState(null);   // {top, left} while open
    const btnRef = useRef(null);
    const menuRef = useRef(null);
    useEffect(() => {
        if (!open) return undefined;
        // Anything outside the menu closes it -- but NOT the menu's own list
        // scrolling, which would otherwise shut it the moment it is scrolled.
        const close = (e) => { if (!menuRef.current?.contains(e.target)) setOpen(null); };
        const shut = () => setOpen(null);
        document.addEventListener("mousedown", close);
        window.addEventListener("resize", shut);
        document.addEventListener("scroll", close, true);
        return () => {
            document.removeEventListener("mousedown", close);
            window.removeEventListener("resize", shut);
            document.removeEventListener("scroll", close, true);
        };
    }, [open]);
    const toggle = () => {
        if (open) { setOpen(null); return; }
        const r = btnRef.current?.getBoundingClientRect();
        setOpen(r ? { top: r.bottom + 6, left: r.left } : { top: 0, left: 0 });
    };
    return (
        <>
            <button ref={btnRef} type="button" className="tb-pk" title={label} aria-label={label}
                aria-haspopup="listbox" aria-expanded={!!open}
                onMouseDown={e => { e.preventDefault(); e.stopPropagation(); }} onClick={toggle}>
                <LIcon name={icon} size={14} />
                <span className="v" style={{ width }}>{shown}</span>
                <span className="chev"><LIcon name="chevronDown" size={13} /></span>
            </button>
            {/* In <body>: a transformed ancestor would otherwise make
                position:fixed relative to it, not to the window. The client
                theme's colours are on <body> too, so it is themed there. */}
            {open && typeof document !== "undefined" && createPortal(
                <div ref={menuRef} role="listbox" aria-label={label} className="tb-pk-menu"
                    style={{ top: open.top, left: open.left }}
                    onMouseDown={e => { e.preventDefault(); e.stopPropagation(); }}>
                    {options.map(o => (
                        <button key={o.value} type="button" role="option" aria-selected={o.value === value}
                            style={o.style} onClick={() => { setOpen(null); onPick(o.value); }}>
                            <span>{o.label}</span>{o.hint && <span className="hint">{o.hint}</span>}
                        </button>
                    ))}
                </div>,
                document.body,
            )}
        </>
    );
};

const AgreementEditor = ({ html, onChange }) => {
    const ref = useRef(null);
    const [on, setOn] = useState({});
    const [menu, setMenu] = useState(false);
    const canEdit = typeof document !== "undefined" && typeof document.execCommand === "function";

    // The page is the source of truth while typing; it is written only when
    // the value changes from outside, so the caret never jumps.
    useEffect(() => {
        if (ref.current && ref.current.innerHTML !== html) ref.current.innerHTML = html || "";
    }, [html]);

    const lightUp = useCallback(() => {
        if (!canEdit || typeof document.queryCommandState !== "function") return;
        const next = {};
        for (const c of LIT_BY) { try { next[c] = document.queryCommandState(c); } catch { next[c] = false; } }
        try { next.block = String(document.queryCommandValue("formatBlock") || "").toLowerCase(); } catch { next.block = ""; }
        // The pickers show what the caret is in, not a placeholder.
        try {
            const sel = window.getSelection();
            let el = sel?.anchorNode;
            if (el && el.nodeType !== 1) el = el.parentElement;
            if (el && ref.current?.contains(el)) {
                const cs = window.getComputedStyle(el);
                const fam = (cs.fontFamily || "").split(",")[0].trim().replace(/^['"]|['"]$/g, "");
                next.font = (TB_FONTS.find(([f]) => f.toLowerCase() === fam.toLowerCase()) || [""])[0];
                next.size = String(Math.round(parseFloat(cs.fontSize) || 16));
            }
        } catch { /* no computed style: keep the pickers as they are */ }
        setOn(prev => ({ ...prev, ...next }));
    }, [canEdit]);

    useEffect(() => {
        const onSel = () => {
            const sel = typeof window !== "undefined" && window.getSelection ? window.getSelection() : null;
            if (sel && ref.current && sel.anchorNode && ref.current.contains(sel.anchorNode)) lightUp();
        };
        document.addEventListener("selectionchange", onSel);
        return () => document.removeEventListener("selectionchange", onSel);
    }, [lightUp]);

    useEffect(() => {
        if (!menu) return undefined;
        const close = () => setMenu(false);
        document.addEventListener("click", close);
        return () => document.removeEventListener("click", close);
    }, [menu]);

    const sync = () => { if (ref.current) onChange(ref.current.innerHTML); lightUp(); };
    const run = (command, value = null) => {
        ref.current?.focus();
        if (canEdit) { try { document.execCommand(command, false, value); } catch { /* unsupported: no-op */ } }
        sync();
    };
    // Text at the caret. Where the browser has no editing commands it is
    // appended as a paragraph, so the button never silently does nothing.
    const insertText = (text) => {
        ref.current?.focus();
        let done = false;
        if (canEdit) { try { done = document.execCommand("insertText", false, text); } catch { done = false; } }
        if (!done && ref.current) {
            const p = document.createElement("p");
            p.textContent = text;
            ref.current.appendChild(p);
        }
        sync();
    };

    /* The browser writes font, size and colour as legacy <font> tags. They are
       turned into <span style> here -- the only form the server keeps -- with
       the size taken from the picker, never from the browser's 1-7 scale. */
    const fontsToSpans = (px) => {
        if (!ref.current) return;
        const made = [];
        for (const f of [...ref.current.querySelectorAll("font")]) {
            const span = document.createElement("span");
            const st = [];
            if (f.getAttribute("face")) st.push(`font-family:${f.getAttribute("face")}`);
            if (px && f.getAttribute("size") === "7") st.push(`font-size:${px}px`);
            if (f.getAttribute("color")) st.push(`color:${f.getAttribute("color")}`);
            if (st.length) span.setAttribute("style", st.join(";"));
            while (f.firstChild) span.appendChild(f.firstChild);
            f.replaceWith(span);
            made.push(span);
        }
        // Replacing the elements drops the selection; put it back over the
        // same words, so a font, size and colour can be chosen one after
        // another on one selection.
        if (made.length && typeof window !== "undefined" && window.getSelection && document.createRange) {
            const range = document.createRange();
            range.setStartBefore(made[0]);
            range.setEndAfter(made[made.length - 1]);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        }
    };
    /* Sub- and superscript at a bare caret: the browser nests a second one
       instead of turning it off, so the caret is stepped out of the element. */
    const script = (command) => {
        const tag = command === "subscript" ? "SUB" : "SUP";
        const sel = typeof window !== "undefined" && window.getSelection ? window.getSelection() : null;
        if (sel && sel.isCollapsed && sel.anchorNode && ref.current?.contains(sel.anchorNode)) {
            let el = sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement;
            while (el && el !== ref.current && el.tagName !== tag) el = el.parentElement;
            if (el && el !== ref.current) {
                const after = document.createTextNode("\u200b");
                el.after(after);
                const range = document.createRange();
                range.setStart(after, 1);
                range.collapse(true);
                sel.removeAllRanges();
                sel.addRange(range);
                sync();
                return;
            }
        }
        run(command);
    };
    const runFont = (command, value, px) => {
        ref.current?.focus();
        if (canEdit) {
            try { document.execCommand("styleWithCSS", false, false); } catch { /* not supported */ }
            try { document.execCommand(command, false, value); } catch { /* unsupported: no-op */ }
        }
        fontsToSpans(px);
        sync();
    };
    const heading = (h) => run("formatBlock", on.block === h ? "<p>" : `<${h}>`);
    const addLink = () => {
        const url = typeof window !== "undefined" && window.prompt
            ? (window.prompt("Link address (https://… or mailto:…)", "https://") || "").trim() : "";
        if (!url) return;
        if (!/^(https?:\/\/|mailto:)[^\s"'<>]+$/i.test(url)) {
            if (typeof window !== "undefined" && window.alert) window.alert("Use a web address starting https:// or http://, or mailto:");
            return;
        }
        const sel = typeof window !== "undefined" && window.getSelection ? window.getSelection() : null;
        if (sel && !sel.isCollapsed) run("createLink", url);
        else run("insertHTML", `<a href="${url.replace(/&/g, "&amp;").replace(/"/g, "&quot;")}">${url.replace(/&/g, "&amp;").replace(/</g, "&lt;")}</a>`);
    };
    const [colour, setColour] = useState("#c0392b");

    const btn = (key, label, title, onClick, lit) => (
        <button key={key} type="button" className="tb-btn" title={title} aria-label={title}
            aria-pressed={lit === undefined ? undefined : !!lit} data-on={lit ? "true" : undefined}
            onMouseDown={e => e.preventDefault()} onClick={onClick}>{label}</button>
    );
    const sep = (k) => <span key={k} className="tb-sep" aria-hidden="true" />;
    const used = (html || "").length;
    const near = used > MAX_BODY_CHARS * 0.9;

    return (
        <>
            <style>{AG_TB_CSS}</style>
            <div data-ag-tb="">
                {/* Scrolls sideways with no visible bar; a mouse wheel over it
                    moves it along, since a plain wheel has no sideways axis. */}
                <div className="tb-scroll" role="toolbar" aria-label="Text formatting"
                    onWheel={e => {
                        const el = e.currentTarget;
                        if (el.scrollWidth > el.clientWidth && Math.abs(e.deltaY) > Math.abs(e.deltaX)) el.scrollLeft += e.deltaY;
                    }}>
                    {btn("undo", <LIcon name="undo" size={18} />, "Undo", () => run("undo"))}
                    {btn("redo", <LIcon name="redo" size={18} />, "Redo", () => run("redo"))}
                    {sep("s1")}
                    <TbPicker label="Font" icon="type" width={64}
                        value={on.font || ""} shown={on.font || "Default"}
                        options={TB_FONTS.map(([f, kind]) => ({ value: f, label: f, hint: kind, style: { fontFamily: f } }))}
                        onPick={f => runFont("fontName", f)} />
                    <TbPicker label="Text size" icon="textSize" width={20}
                        value={String(on.size || "16")} shown={on.size || "16"}
                        options={TB_SIZES.map(px => ({ value: String(px), label: String(px), hint: px === 16 ? "Normal" : null }))}
                        onPick={px => runFont("fontSize", "7", +px)} />
                    <label className="tb-btn tb-color" title="Text colour" aria-label="Text colour">
                        <LIcon name="baseline" size={18} />
                        <i style={{ background: colour }} />
                        <input type="color" value={colour} aria-label="Pick a text colour"
                            onChange={e => { setColour(e.target.value); runFont("foreColor", e.target.value); }} />
                    </label>
                    {sep("s2")}
                    {TB_MARKS.map(([c, name, title]) => btn(c, <LIcon name={name} size={18} />, title,
                        () => (c === "subscript" || c === "superscript" ? script(c) : run(c)), on[c]))}
                    {sep("s3")}
                    {TB_ALIGN.map(([c, name, title]) => btn(c, <LIcon name={name} size={18} />, title, () => run(c), on[c]))}
                    {sep("s4")}
                    {btn("ul", <LIcon name="list" size={18} />, "Bulleted list", () => run("insertUnorderedList"), on.insertUnorderedList)}
                    {btn("ol", <LIcon name="listOrdered" size={18} />, "Numbered list", () => run("insertOrderedList"), on.insertOrderedList)}
                    {sep("s5")}
                    {["h1", "h2", "h3"].map(h => btn(h, <LIcon name={`heading${h[1]}`} size={19} />, `Heading ${h[1]}`, () => heading(h), on.block === h))}
                    {sep("s6")}
                    {btn("quote", <LIcon name="quote" size={17} />, "Quote", () => run("formatBlock", "<blockquote>"), on.block === "blockquote")}
                    {btn("link", <LIcon name="link" size={17} />, "Link", addLink)}
                    {btn("hr", <LIcon name="minus" size={18} />, "Divider", () => run("insertHorizontalRule"))}
                    {btn("clear", <LIcon name="removeFormatting" size={18} />, "Clear formatting", () => run("removeFormat"))}
                </div>
                {/* Outside the scrolling strip, so its menu is not clipped. */}
                <div className="tb-drop">
                    <button type="button" className="tb-pick" aria-haspopup="menu" aria-expanded={menu}
                        onMouseDown={e => e.preventDefault()}
                        onClick={e => { e.stopPropagation(); setMenu(m => !m); }}>
                        <LIcon name="plus" size={15} /><span>Insert</span>
                        <span className="chev" style={{ display: "inline-flex" }}><LIcon name="chevronDown" size={14} /></span>
                    </button>
                    {menu && (
                        <div role="menu" className="tb-menu" onClick={e => e.stopPropagation()}>
                            {INSERTABLES.filter(it => it.label !== "Divider").map(it => (
                                <button key={it.label} type="button" role="menuitem"
                                    onMouseDown={e => e.preventDefault()}
                                    onClick={() => { setMenu(false); insertText(it.build()); }}>{it.label}</button>
                            ))}
                        </div>
                    )}
                </div>
            </div>
            <div data-ag-page="">
                <div ref={ref} data-ag-paper="" role="textbox" aria-multiline="true" aria-label="Agreement text"
                    contentEditable suppressContentEditableWarning
                    onInput={sync} onKeyUp={lightUp} onMouseUp={lightUp} />
                <div style={{ margin: "6px 4px 0", textAlign: "right" }}>
                    <span className="tb-count" title={`The server accepts up to ${MAX_BODY_CHARS.toLocaleString()} characters, formatting included`}
                        style={near ? { color: "var(--gold)", fontWeight: 700 } : undefined}>
                        {used.toLocaleString()} / {MAX_BODY_CHARS.toLocaleString()}
                    </span>
                </div>
            </div>
        </>
    );
};

const PageCreate = ({ template, onNavigate, onDone }) => {
    const t = useTheme();
    const toast = useToast();
    const { user } = useAuth();
    const [step, setStep] = useState(0);
    const [title, setTitle] = useState(template?.name || "New Agreement");
    // HTML from here on (the rich editor). A template's plain text becomes one
    // paragraph per line, every character escaped.
    const [body, setBody] = useState(() => textToAgreementHtml(template?.body || ""));
    // The Review step's copy: the SERVER's canonical form of `body`, which is
    // what is sent, hashed and signed. {loading, body, error}.
    const [review, setReview] = useState(null);
    useEffect(() => {
        if (step !== 3) return undefined;
        let live = true;
        setReview({ loading: true, body: null, error: null });
        // The caret helper's zero-width spaces are not part of the agreement.
        Promise.resolve(previewAgreementBody(body.replace(/\u200b/g, ""))).then(res => {
            if (!live) return;
            const clean = res?.data?.body_html;
            if (res?.error || typeof clean !== "string") {
                setReview({ loading: false, body: null, error: res?.error?.message || "The text could not be checked. Try again." });
            } else if (!res.data.has_text) {
                setReview({ loading: false, body: null, error: "The agreement has no text. Go back and write it." });
            } else {
                setReview({ loading: false, body: clean, error: null });
            }
        }).catch(() => { if (live) setReview({ loading: false, body: null, error: "The text could not be checked. Try again." }); });
        return () => { live = false; };
    }, [step, body]);

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
        if (n > step && step === 0 && !title.trim()) {
            toast.show("⚠️ Give the agreement a title (at the top)", "warn");
            return;
        }
        if (n > step && step === 0 && !agreementPlainText(body)) {
            toast.show("⚠️ Write the agreement before adding signers", "warn");
            return;
        }
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
                    <button type="button" className="ag-back" onClick={() => onNavigate("templates")}
                        aria-label="Back to templates" title="Back to templates">
                        <LIcon name="back" size={18} stroke={2} />
                    </button>
                    <div>
                        <h2 style={{ fontSize: 21, fontWeight: 800, color: t.text, margin: 0, fontFamily: "inherit", letterSpacing: "-.01em" }}>Create Agreement</h2>
                        {/* The agreement's title, edited in place: the separate
                            title box above the editor was removed (2026-10-11)
                            so the editor's toolbar sits where it was. */}
                        <style>{AG_TITLE_CSS}</style>
                        <input className="ag-title" aria-label="Agreement title" placeholder="Agreement title"
                            value={title} maxLength={300} onChange={e => setTitle(e.target.value)} />
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
                    {/* The editor brings its own toolbar bar and page; no card
                        around them, which would also stop the bar sticking. */}
                    <AgreementEditor html={body} onChange={setBody} />
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
                /* Two columns that use the width (2026-10-11): the pad, which is
                   the work, on the left; who signs and what is recorded on the
                   right. It was one 780px column with dead space beside it. */
                <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 340px", gap: 18, alignItems: "start" }}>
                  <div style={{ minWidth: 0 }}>
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
                                    display: "flex", alignItems: "center", justifyContent: "center", color: t.primary,
                                }}><LIcon name="pencil" size={16} /></div>
                                <div>
                                    <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>Your Signature</div>
                                    <div style={{ fontSize: 10, color: t.textMuted }}>
                                        {sig.data ? "✓ Signature captured" : "Draw, type or upload below"}
                                    </div>
                                </div>
                            </div>

                        </div>

                        <div style={{ padding: "16px 18px" }}>
                            <SignaturePad height={260} onChange={setSig} />
                        </div>

                        {/* Footer strip */}
                        <div style={{
                            padding: "10px 18px",
                            borderTop: `1px solid ${t.border}`,
                            display: "flex", alignItems: "center", justifyContent: "space-between",
                            background: t.surface,
                        }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: t.textMuted }}>
                                <LIcon name="shield" size={13} />
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

                  <aside style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    {/* ── Full name ── */}
                    <div style={{ padding: "14px 16px", borderRadius: 16, background: t.card, border: `1px solid ${t.border}` }}>
                        <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: 8 }}>
                            Your full name
                        </label>
                        <div style={{ position: "relative" }}>
                            <span style={{ position: "absolute", left: 13, top: "50%", transform: "translateY(-50%)", color: t.textMuted, display: "flex", pointerEvents: "none" }}>
                                <LIcon name="type" size={15} />
                            </span>
                            <Input
                                placeholder="As it should appear"
                                value={fullName}
                                onChange={e => setFullName(e.target.value)}
                                style={{ fontSize: 14, padding: "11px 14px 11px 38px" }}
                            />
                        </div>
                    </div>

                    {/* ── Who signs, in order ── */}
                    <div style={{ padding: "14px 16px", borderRadius: 16, background: t.card, border: `1px solid ${t.border}` }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 4 }}>Sign as creator</div>
                        <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.55, marginBottom: 12 }}>
                            Your signature is applied first, then the others are asked to counter-sign.
                        </div>
                        {[{ name: fullName || "You", note: "Signs now", you: true },
                          ...signers.map(sg => ({ name: sg.name || sg.email || "Your signer", note: sg.kind === "email" ? "Invited by email" : "Signs in the app" }))
                        ].map((p, i, all) => (
                            <div key={i} style={{ display: "flex", gap: 10, position: "relative", paddingBottom: i < all.length - 1 ? 12 : 0 }}>
                                {i < all.length - 1 && <i style={{ position: "absolute", left: 13, top: 28, bottom: 0, width: 2, background: t.border }} />}
                                <span style={{
                                    width: 28, height: 28, flexShrink: 0, borderRadius: "50%", zIndex: 1,
                                    display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 800,
                                    background: p.you ? t.primary : t.surface, color: p.you ? "#06261c" : t.textMuted,
                                    border: p.you ? "none" : `1.5px solid ${t.border}`,
                                }}>{i + 1}</span>
                                <div style={{ minWidth: 0 }}>
                                    <div style={{ fontSize: 13, fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.name}</div>
                                    <div style={{ fontSize: 11.5, color: t.textMuted }}>{p.note}</div>
                                </div>
                            </div>
                        ))}
                    </div>

                    {/* ── What is recorded ── */}
                    <div style={{ display: "flex", gap: 12, padding: "14px 16px", borderRadius: 16, background: `${t.success}0D`, border: `1px solid ${t.success}30` }}>
                        <span style={{ color: t.success, display: "flex", marginTop: 1 }}><LIcon name="shield" size={18} /></span>
                        <div>
                            {/* Two claims used to sit here, both unsupported:
                                "AES-256 encrypted" and "Compliant with
                                e-signature laws". Whether an instrument complies
                                with ETO 2002 is a legal conclusion no lawyer has
                                reviewed, and this panel is the worst place in
                                the product to be wrong. What is left is true. */}
                            <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 4 }}>What we record</div>
                            <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.55 }}>
                                On submission, we record your account, timestamp, IP address,
                                and the agreement content hash.
                            </div>
                        </div>
                    </div>
                  </aside>
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
                        {/* The server's canonical form: exactly what will be
                            hashed and signed, not the editor's raw markup. */}
                        <div style={{ padding: "20px 24px", maxHeight: 420, overflowY: "auto" }}>
                            {review?.loading ? (
                                <div style={{ fontSize: 13, color: t.textMuted }}>Checking the text…</div>
                            ) : review?.error ? (
                                <div style={{ fontSize: 13, color: t.danger }}>{review.error}</div>
                            ) : (
                                <AgreementBody body={review?.body} format="html" empty="(No content)"
                                    style={{ fontSize: 13.5, lineHeight: 1.85, color: t.text, fontFamily: "Georgia, 'Times New Roman', serif" }} />
                            )}
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
                <button type="button" className="ag-nav back" onClick={() => step > 0 ? nav(step - 1) : onNavigate("templates")}>
                    <LIcon name="back" size={16} stroke={2.2} /><span>Back</span>
                </button>
                <span style={{ fontSize: 12, color: t.textMuted }}>Step {step + 1} of {STEPS.length}</span>
                {step < 3
                    ? <button type="button" className="ag-nav next" onClick={() => nav(step + 1)}>
                        <span>Next</span><LIcon name="arrowRight" size={16} stroke={2.2} />
                    </button>
                    : <Btn primary disabled={submitting} onClick={async () => {
                        if (!user?._id) { toast.show("⚠️ Please log in first", "warn"); return; }
                        if (!signersReady) {
                            toast.show("⚠️ Add at least one other signer (Step 2)", "warn"); return;
                        }
                        if (!sig.data) { toast.show("⚠️ Please add your signature first", "warn"); return; }
                        if (!review?.body) { toast.show("⚠️ " + (review?.error || "The text is still being checked"), "warn"); return; }
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
                                // What Review showed, not the editor's markup.
                                body_html: review.body,
                                body_format: "html",
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
                                url: `${window.location.origin}/sign#token=${encodeURIComponent(tok)}`,
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
                        {submitting ? "Sending…" : <><LIcon name="send" size={15} stroke={2} />{" "}Sign & Send</>}
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
                    {item("Open", onOpen)}
                    {/* Only once EXECUTED. The server refuses a PDF before every
                        party has signed, so offering it earlier would be an
                        action that always fails. */}
                    {agreement.rawStatus === "executed" &&
                        item("Download PDF", onDownload)}
                    <div style={{ height: 1, background: t.border, margin: "5px 0" }} />
                    {archivedView
                        ? item("Restore to my list", onUnarchive)
                        : item("Remove from my list", onArchive, t.danger)}
                </div>
            )}
        </div>
    );
};

const PageAllAgreements = ({ onNavigate, initialFilter = "All" }) => {
    const t = useTheme();
    const toast = useToast();
    const { user } = useAuth();
    const [search, setSearch] = useState("");
    const [filter, setFilter] = useState(initialFilter);
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
    const [signConsent, setSignConsent] = useState(false);
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
        setSignConsent(false);
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
        setDoc({ loading: false, body: data.body_html ?? "", format: data.body_format,
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
        if (viewing?.createdBy !== user?._id) {
            toast.show("❌ Only the agreement creator can resend an invitation", "danger", 6000);
            return;
        }
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
            url: `${window.location.origin}/sign#token=${encodeURIComponent(token)}`,
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
    const needMine = agmts.filter(a => a.needsMySig).length;

    const doSign = async () => {
        if (!signSig.data) {
            toast.show("⚠️ Add your signature first — draw, type or upload", "warn");
            return;
        }
        if (!signConsent) {
            toast.show("⚠️ Confirm that you intend to sign this agreement", "warn");
            return;
        }
        setSignBusy(true);
        const { data, error } = await signAgreement(
            viewing.id, signSig.method, signSig.data, true);
        setSignBusy(false);
        if (error) { toast.show("❌ " + (error.message || "Failed to sign"), "danger"); return; }
        toast.show(data?.status === "executed" ? "🎉 Agreement fully executed!" : "✅ Signed — awaiting the other parties", "success", 4000);
        openSeq.current += 1; setViewing(null); setDoc(null);
        setSignSig({ method: "canvas", data: "" });
        setSignConsent(false);
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
        <div data-ag-all="">
            <style>{AG_ALL_CSS}</style>
            {/* ── Header: title and how many, search + primary action ── */}
            <header className="al-head">
                <div>
                    <h1>All agreements</h1>
                    <p>
                        {loading && agmts.length === 0 ? "Loading…"
                            : `${paging.total} ${archivedView ? "archived " : ""}agreement${paging.total === 1 ? "" : "s"}`
                              + (!archivedView && needMine > 0 ? ` · ${needMine} need${needMine === 1 ? "s" : ""} your signature` : "")}
                    </p>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <label className="al-search">
                        <AdIcon d="M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-4.3-4.3" s={16} />
                        <input aria-label="Search agreements" placeholder="Search by title" value={search} onChange={e => setSearch(e.target.value)} />
                    </label>
                    {/* NOT "Upload New". There is no upload-an-agreement endpoint,
                        so that button would offer a feature that does not exist.
                        This opens the builder, and only when the builder is
                        actually enabled -- otherwise the server refuses the send
                        with a 403 and the button would be a second lie. */}
                    {DIY_BUILDER_ENABLED && (
                        <button type="button" className="al-new" onClick={() => onNavigate("templates")}>
                            <AdIcon d={AD_PATH.plus} s={16} w={2.6} /> New agreement
                        </button>
                    )}
                </div>
            </header>

            {/* Status filters in one group; Archived apart, because it is a
                view across all four statuses, not a fifth one. */}
            <div className="al-bar">
                <div className="al-seg" role="group" aria-label="Filter by status">
                    {filters.filter(f => f !== "Archived").map(f => (
                        <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>{f}</button>
                    ))}
                </div>
                <button type="button" className="al-arch" aria-pressed={archivedView}
                    onClick={() => setFilter(archivedView ? "All" : "Archived")}>
                    <AdIcon d="M3 5h18v4H3zM5 9v10h14V9M10 13h4" s={15} />Archived
                </button>
            </div>

            {/* ── Table ── */}
            {/* Desktop layout (the client UI targets desktop). No scroll box: it
                would clip the row menu that opens below each row. */}
            <div className="al-table">
                <div className="al-grid al-th">
                    {["DOCUMENT", "PARTIES", "STATUS", "PROGRESS", "ACTIONS"].map(h => (
                        <div key={h} style={h === "ACTIONS" ? { textAlign: "right" } : undefined}>{h}</div>
                    ))}
                </div>

                {filtered.map(a => {
                    const look = rowLook(a);
                    const others = (a.parties || []).filter(p => p.user_id !== a.createdBy);
                    const sender = (a.parties || []).find(p => p.user_id === a.createdBy);
                    const senderName = sender?.full_name || "You";
                    const pct = a.totalParties ? Math.round((a.signedCount / a.totalParties) * 100) : 0;
                    const ini = n => (n || "?").trim().split(/\s+/).slice(0, 2).map(w => w[0]).join("").toUpperCase() || "?";
                    return (
                        <div key={a.id} className="al-grid al-tr" style={{ "--c": look.c }} onClick={() => openAgreement(a)}>
                            {/* DOCUMENT — the icon is tinted by state, so the
                                column reads at a glance without the chip. */}
                            <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                                <span className="al-ic"><AdIcon d={AD_PATH[look.icon]} s={18} w={look.icon === "check" ? 2.4 : 2} /></span>
                                <div style={{ minWidth: 0 }}>
                                    <div className="al-title">{a.name}</div>
                                    <div className="al-sub">{a.isEngagementLetter ? "Engagement letter" : "Agreement"}{a.date ? ` · ${a.date}` : ""}</div>
                                </div>
                            </div>

                            {/* PARTIES — the sender is labelled; the rest are
                                COUNTED rather than assumed to be one. An
                                agreement may have three parties, and a fixed
                                Sender/Recipient pair would silently drop the
                                third. A recipient's ring is green once signed. */}
                            <div style={{ minWidth: 0 }}>
                                <div className="al-avs">
                                    <span className="al-av" style={{ "--c": "#9aa8a6" }} title={`Sender — ${senderName}`}>{ini(senderName)}</span>
                                    {others.slice(0, 3).map((p, n) => (
                                        <span key={n} className="al-av" style={{ "--c": p.signed ? AD_MINT : AD_GOLD }}
                                            title={`${p.full_name || p.email || "Invited signer"} — ${p.signed ? "signed" : "not signed yet"}`}>
                                            {ini(p.full_name || p.email || "Invited")}
                                        </span>
                                    ))}
                                    {others.length > 3 && <span style={{ marginLeft: 6, fontSize: 11.5, color: "var(--muted)" }}>+{others.length - 3}</span>}
                                </div>
                                <div className="al-sub" style={{ marginTop: 5 }}>
                                    Sender {senderName} · {others.length > 1 ? `Recipients (${others.length})` : `Recipient ${others[0]?.full_name || others[0]?.email || "—"}`}
                                </div>
                            </div>

                            {/* STATUS */}
                            <span className="al-chip"><i />{a.needsMySig ? "Needs you" : a.status}</span>

                            {/* PROGRESS */}
                            <div>
                                <div className="al-pbar"><i style={{ width: `${pct}%` }} /></div>
                                <div className="al-sub" style={{ marginTop: 5 }}>{a.signedCount}/{a.totalParties} signed</div>
                            </div>

                            {/* ACTIONS — the one step that moves it on, then the menu. */}
                            <div className="al-acts" onClick={e => e.stopPropagation()}>
                                {a.needsMySig ? (
                                    <button type="button" className="al-btn solid" style={{ "--a": AD_MINT }} onClick={() => openAgreement(a)}>Sign</button>
                                ) : a.rawStatus === "executed" ? (
                                    <button type="button" className="al-btn" style={{ "--a": AD_LAV }} onClick={() => doDownloadRow(a)}>PDF ↓</button>
                                ) : (
                                    <button type="button" className="al-btn" style={{ "--a": AD_CYAN }} onClick={() => openAgreement(a)}>Open</button>
                                )}
                                <RowMenu
                                    agreement={a}
                                    archivedView={archivedView}
                                    onOpen={() => openAgreement(a)}
                                    onDownload={() => doDownloadRow(a)}
                                    onArchive={() => doArchive(a)}
                                    onUnarchive={() => doUnarchive(a)}
                                />
                            </div>
                        </div>
                    );
                })}

                {/* HOW MANY THERE ARE. Without the total, a list that stops at
                    its page size looks exactly like a complete one. The counts
                    stay honest about loaded-vs-total rather than printing a
                    tidy range the data does not support. */}
                {!loading && agmts.length > 0 && (
                    <div className="al-foot">
                        <span>
                            {filtered.length === agmts.length
                                ? `Showing ${agmts.length} of ${paging.total}`
                                : `Showing ${filtered.length} of ${agmts.length} loaded (${paging.total} total)`}
                        </span>
                        {paging.hasMore && (
                            <button type="button" className="al-btn" style={{ "--a": AD_CYAN }} onClick={paging.loadMore} disabled={loading}>
                                Load more
                            </button>
                        )}
                    </div>
                )}
                {loading && agmts.length === 0 ? (
                    <div className="al-empty">Loading agreements…</div>
                ) : filtered.length === 0 && !loading && (
                    <div className="al-empty">
                        <b>{search ? "Nothing matches your search" : archivedView ? "Nothing archived" : filter === "All" ? "No agreements yet" : `No ${filter.toLowerCase()} agreements`}</b>
                        {search ? "Try another title."
                            : archivedView ? "Agreements you remove from your list appear here."
                                : filter === "All" ? "Agreements shared with you appear here for you to read and sign." : "Try another filter."}
                    </div>
                )}
            </div>

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
                                        {p.external && !p.signed && viewing.rawStatus === "pending"
                                            && viewing.createdBy === user?._id && (
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
                                <AgreementBody body={doc?.body} format={doc?.format}
                                    style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 12, padding: "18px 20px", fontSize: 13, lineHeight: 1.85, color: t.text, fontFamily: "Georgia,serif" }} />
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
                                <label style={{ display: "flex", gap: 9, alignItems: "flex-start", marginTop: 10, fontSize: 12, color: t.textMuted, lineHeight: 1.5, cursor: "pointer" }}>
                                    <input type="checkbox" checked={signConsent}
                                        onChange={e => setSignConsent(e.target.checked)} />
                                    <span>I have read this document and intend the signature above to be my signature on it.</span>
                                </label>
                                <Btn primary disabled={signBusy || !signConsent} onClick={doSign}
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
const DIY_BUILDER_ENABLED = AGREEMENTS_DIY_ENABLED;   // read in lib/agreementsNav.js

/* Page navigation lives in the client sidebar, under "Agreements"
   (2026-10-11), the way Documents' sections do: lib/agreementsNav.js. The
   module's own inner sidebar and its collapse bar were removed with it. */

// ── ModAgreements ─────────────────────────────
function ModAgreements() {
    const t = useTheme();
    const [page, setPage] = useState(() => {
        const p = takePendingAgreementsView();
        return p && (DIY_BUILDER_ENABLED || (p !== "create" && p !== "templates")) ? p : "dashboard";
    });
    const [selectedTemplate, setSelectedTemplate] = useState(null);

    /* Parked pages are unreachable by ROUTE, not merely unlinked. Removing the
       sidebar entries alone would leave `create` reachable from the dashboard's
       own call-to-action and from any stale state, landing the user in a wizard
       whose last click the server refuses. */
    const [allFilter, setAllFilter] = useState("All");   // the list's opening filter
    const navigate = (p, opts) => {
        setAllFilter(opts?.filter || "All");
        setPage(!DIY_BUILDER_ENABLED && (p === "create" || p === "templates")
            ? "all" : p);
    };

    // The sidebar asks for a page; the module says which page it is on.
    useEffect(() => {
        const on = e => { if (e?.detail?.view) { takePendingAgreementsView(); navigate(e.detail.view); } };
        window.addEventListener(AGREEMENTS_VIEW_EVENT, on);
        return () => window.removeEventListener(AGREEMENTS_VIEW_EVENT, on);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    useEffect(() => { announceAgreementsView(page); }, [page]);

    return (
        <div style={{
            display: "flex", height: "100%", background: t.bg, fontFamily: AG_FONT,
            color: t.text, overflow: "hidden",
        }}>
            <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
                {/* Page content */}
                <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
                    {page === "dashboard" && <PageDashboard onNavigate={navigate} />}
                    {DIY_BUILDER_ENABLED && page === "templates" && (
                        <PageTemplates onNavigate={navigate} onSelectTemplate={t => setSelectedTemplate(t)} />
                    )}
                    {DIY_BUILDER_ENABLED && page === "create" && (
                        <PageCreate template={selectedTemplate} onNavigate={navigate} onDone={() => navigate("all")} />
                    )}
                    {page === "all" && <PageAllAgreements key={allFilter} onNavigate={navigate} initialFilter={allFilter} />}
                </div>
            </div>
        </div>
    );
}

export default ModAgreements;
