'use client';
import React, { useContext, useEffect, useState } from "react";
import { useT } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import { useAuth } from "@/context/AuthContext.jsx";
import { CaseCtx } from "@/components/shared/CaseContext.jsx";
import SessionsPanel from "@/components/shared/SessionsPanel.jsx";
import { updateMe, changePassword, closeAccount, myDocumentsV2 } from "@/lib/api.js";
import { useLang } from "@/lib/i18n.jsx";
import { ThemedInput, ConfirmDialog } from "@/components/shared/shared.jsx";
import { DOCS_FONT } from "./documents/ui.jsx";

/* The client Profile (2026-10-11, the approved "Profile v2" design).
 *
 * Everything shown is the account's own data. The page this replaces showed
 * every client the same "Last login 2 hours ago from Pixel 6", "3 active
 * devices", "Security score: Good" and "Member since December 2025" -- all
 * hardcoded -- beside a real member-since date that disagreed with it, and
 * fell back to a developer's own name and email when a field was empty. A
 * photo "upload" only changed this browser's preview and announced success.
 * None of that survives: sessions come from the sessions panel, the date from
 * `created_at`, and a missing field says it is missing.
 *
 * Scoped by [data-profile-c]; colours are the client tokens (clientTheme.js). */
const PROFILE_CSS = `[data-profile-c]{display:flex;flex-direction:column;gap:18px}
[data-profile-c] .pc-card{position:relative;border-radius:20px;border:1px solid color-mix(in srgb,var(--brand-text) 14%,var(--line));background:radial-gradient(120% 110% at 100% 0%,color-mix(in srgb,var(--c,var(--brand-text)) 8%,transparent) 0%,transparent 55%),linear-gradient(180deg,color-mix(in srgb,var(--surface) 88%,#fff 12%),var(--surface));box-shadow:inset 0 1px 0 rgba(255,255,255,.1),inset 0 -3px 0 rgba(0,0,0,.2),0 14px 28px -16px rgba(0,0,0,.7)}
[data-profile-c] .pc-well{border-radius:14px;background:linear-gradient(180deg,color-mix(in srgb,var(--surface-2) 88%,#fff 4%),var(--surface-2));border:1px solid color-mix(in srgb,var(--c,var(--brand-text)) 16%,var(--line))}
[data-profile-c] .pc-head{display:flex;align-items:center;gap:18px;padding:18px 22px}
[data-profile-c] .pc-av{width:72px;height:72px;flex:none;border-radius:50%;display:grid;place-items:center;overflow:hidden;font-size:26px;font-weight:600;color:#04212a;background:linear-gradient(135deg,#3ee0a1,#2ec4d6);box-shadow:0 0 0 4px color-mix(in srgb,var(--brand-text) 15%,transparent)}
[data-profile-c] .pc-av img{width:100%;height:100%;object-fit:cover}
[data-profile-c] .pc-name{margin:0;font-size:27px;font-weight:600;color:var(--ink)}
[data-profile-c] .pc-chip{display:inline-flex;align-items:center;gap:6px;height:26px;padding:0 11px;border-radius:999px;font-size:12px;font-weight:700;color:var(--c);background:color-mix(in srgb,var(--c) 15%,transparent)}
[data-profile-c] .pc-ring{width:58px;height:58px;flex:none;border-radius:50%;display:grid;place-items:center}
[data-profile-c] .pc-ring span{width:46px;height:46px;border-radius:50%;display:grid;place-items:center;background:var(--surface-2);font-weight:800;font-size:14px;color:var(--ink)}
[data-profile-c] .pc-tabs{display:flex;gap:6px;padding:5px;border-radius:999px;background:var(--surface-2);border:1px solid var(--line);flex:none}
[data-profile-c] .pc-tab{height:40px;padding:0 18px;border-radius:999px;border:0;background:transparent;color:var(--muted);font:inherit;font-size:13.5px;font-weight:600;cursor:pointer;transition:background .2s,color .2s}
[data-profile-c] .pc-tab:hover{color:var(--ink);background:var(--hover-tint)}
[data-profile-c] .pc-tab[aria-selected="true"]{background:linear-gradient(135deg,#12897f,#1c9c66);color:#fff}
[data-profile-c] .pc-grid{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:16px;align-items:start}
[data-profile-c] .pc-sec-head{padding:18px 22px 14px;border-bottom:1px solid var(--line)}
[data-profile-c] .pc-sec-head p{margin:3px 0 0;font-size:12.5px;color:var(--muted)}
[data-profile-c] .pc-line{display:grid;grid-template-columns:34px 150px minmax(0,1fr) auto;align-items:center;gap:14px;padding:14px 22px;border-bottom:1px solid var(--line);transition:background .15s}
[data-profile-c] .pc-line:last-child{border-bottom:0}
[data-profile-c] .pc-line:hover{background:color-mix(in srgb,var(--c) 5%,transparent)}
[data-profile-c] .pc-line .pc-k{width:auto;font-size:13.5px;font-weight:700;letter-spacing:0;text-transform:none;color:var(--ink)}
[data-profile-c] .pc-val{display:flex;flex-direction:column;gap:2px;min-width:0}
[data-profile-c] .pc-v.none{font-style:italic}
[data-profile-c] .pc-why{font-size:12px;color:var(--faint)}
[data-profile-c] .pc-act{display:flex;gap:8px;justify-content:flex-end}
[data-profile-c] .pc-seg{display:inline-flex;padding:3px;border-radius:12px;background:var(--surface-2);border:1px solid var(--line)}
[data-profile-c] .pc-seg button{height:32px;padding:0 14px;border:0;border-radius:9px;background:transparent;color:var(--muted);font:inherit;font-size:13px;font-weight:700;cursor:pointer}
[data-profile-c] .pc-seg button[aria-checked="true"]{background:color-mix(in srgb,#b9a6f2 20%,var(--surface));color:var(--ink)}
[data-profile-c] .pc-checklist{display:flex;flex-direction:column;gap:8px;margin:16px 0}
[data-profile-c] .pc-check-row{display:flex;align-items:center;gap:10px;height:42px;padding:0 14px;border-radius:12px;background:var(--surface-2);border:1px solid var(--line);font-size:13.5px;font-weight:600;color:var(--ink)}
[data-profile-c] .pc-check-row[data-ok]{color:var(--muted)}
[data-profile-c] .pc-check-row .tick{width:20px;height:20px;flex:none;border-radius:50%;display:grid;place-items:center;border:1.5px dashed var(--line-strong)}
[data-profile-c] .pc-check-row[data-ok] .tick{border:0;background:var(--brand-text);color:#04262c}
[data-profile-c] .pc-cta{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;height:46px;border:0;border-radius:14px;background:linear-gradient(135deg,#12897f,#1c9c66);color:#fff;font:inherit;font-size:14.5px;font-weight:700;cursor:pointer;box-shadow:0 10px 22px -12px rgba(28,156,102,.85);transition:filter .15s,transform .12s}
[data-profile-c] .pc-cta:hover{filter:brightness(1.08)}
[data-profile-c] .pc-cta:hover span{transform:translateX(3px)}
[data-profile-c] .pc-cta span{transition:transform .2s}
[data-profile-c] .pc-cta:active{transform:scale(.97)}
[data-profile-c] .pc-quick{display:flex;flex-direction:column;padding:6px}
[data-profile-c] .pc-quick button{display:flex;align-items:center;gap:12px;height:46px;padding:0 14px;border:0;border-radius:12px;background:transparent;color:var(--ink);font:inherit;font-size:14px;font-weight:600;text-align:left;cursor:pointer;transition:background .15s,color .15s}
[data-profile-c] .pc-quick button svg{color:var(--c)}
[data-profile-c] .pc-quick button i{margin-left:auto;font-style:normal;font-size:18px;color:var(--faint);transition:transform .2s,color .2s}
[data-profile-c] .pc-quick button:hover{background:color-mix(in srgb,var(--c) 12%,transparent);color:var(--c)}
[data-profile-c] .pc-quick button:hover i{transform:translateX(3px);color:var(--c)}
[data-profile-c] .pc-col{display:flex;flex-direction:column;gap:16px;min-width:0}
[data-profile-c] .pc-sec{padding:20px 24px}
[data-profile-c] .pc-h{margin:0;font-size:17px;font-weight:700;color:var(--ink)}
[data-profile-c] .pc-row{display:flex;align-items:center;gap:14px;padding:14px 4px;border-bottom:1px solid var(--line)}
[data-profile-c] .pc-row:last-child{border-bottom:0}
[data-profile-c] .pc-ic{width:34px;height:34px;flex:none;border-radius:10px;display:grid;place-items:center;color:var(--c);background:color-mix(in srgb,var(--c) 15%,transparent)}
[data-profile-c] .pc-k{width:130px;flex:none;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--faint)}
[data-profile-c] .pc-v{flex:1;min-width:0;font-size:14.5px;font-weight:600;color:var(--ink);overflow-wrap:anywhere}
[data-profile-c] .pc-v.none{color:var(--faint);font-weight:500}
[data-profile-c] .pc-ed{width:32px;height:32px;flex:none;border-radius:10px;border:1px solid color-mix(in srgb,var(--brand-text) 25%,transparent);background:color-mix(in srgb,var(--brand-text) 8%,transparent);color:var(--brand-text);display:grid;place-items:center;cursor:pointer;transition:background .2s,color .2s,transform .15s}
[data-profile-c] .pc-ed:hover{background:var(--brand-text);color:#04262c}
[data-profile-c] .pc-ed:active{transform:scale(.92)}
[data-profile-c] .pc-input{flex:1;min-width:0;height:38px;padding:0 12px;border-radius:10px;border:1px solid var(--brand-text);box-shadow:0 0 0 3px color-mix(in srgb,var(--brand-text) 16%,transparent);background:var(--input);color:var(--ink);font:inherit;font-size:14px;outline:none}
[data-profile-c] .pc-btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;height:36px;padding:0 16px;border-radius:999px;border:1px solid color-mix(in srgb,var(--a,var(--brand-text)) 38%,transparent);background:color-mix(in srgb,var(--a,var(--brand-text)) 13%,var(--surface));color:var(--a,var(--brand-text));font:inherit;font-size:13px;font-weight:700;cursor:pointer;transition:background .2s,color .2s,transform .12s}
[data-profile-c] .pc-btn:hover:not(:disabled){background:var(--a,var(--brand-text));border-color:transparent;color:#04262c}
[data-profile-c] .pc-btn:active:not(:disabled){transform:scale(.95)}
[data-profile-c] .pc-btn:disabled{opacity:.55;cursor:not-allowed}
[data-profile-c] .pc-btn.go{border:0;background:linear-gradient(135deg,#12897f,#1c9c66);color:#fff}
[data-profile-c] .pc-btn.go:hover:not(:disabled){filter:brightness(1.08);background:linear-gradient(135deg,#12897f,#1c9c66);color:#fff}
[data-profile-c] .pc-link{border:0;background:none;padding:0;color:var(--brand-text);font:inherit;font-size:12.5px;font-weight:700;cursor:pointer}
[data-profile-c] .pc-link:hover{text-decoration:underline}
[data-profile-c] .pc-provs{display:flex;flex-wrap:wrap;gap:6px}
[data-profile-c] .pc-prov{height:32px;padding:0 12px;border-radius:10px;border:1px solid var(--line-strong);background:var(--surface-2);color:var(--ink);font:inherit;font-size:13px;font-weight:600;text-align:left;cursor:pointer}
[data-profile-c] .pc-prov[aria-checked="true"]{border-color:var(--brand-text);background:color-mix(in srgb,var(--brand-text) 14%,var(--surface-2))}
[data-profile-c] .pc-glance{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
[data-profile-c] .pc-glance button{display:flex;flex-direction:column;gap:4px;padding:12px;text-align:left;font:inherit;cursor:pointer;transition:transform .2s,border-color .2s}
[data-profile-c] .pc-glance button:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--c) 50%,transparent)}
[data-profile-c] .pc-glance b{font-size:24px;font-weight:600;color:var(--c)}
[data-profile-c] .pc-glance span{font-size:12px;color:var(--muted)}
[data-profile-c] .pc-checks{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
[data-profile-c] .pc-check{padding:18px;display:flex;flex-direction:column;gap:12px}
[data-profile-c] .pc-ic.big{width:44px;height:44px;border-radius:13px}
@media (max-width:1100px){[data-profile-c] .pc-grid{grid-template-columns:minmax(0,1fr)}[data-profile-c] .pc-checks{grid-template-columns:minmax(0,1fr)}[data-profile-c] .pc-head{flex-wrap:wrap}[data-profile-c] .pc-line{grid-template-columns:34px minmax(0,1fr) auto}[data-profile-c] .pc-line .pc-k{display:none}}`;

const PROVINCES = [
    ["punjab", "Punjab"], ["sindh", "Sindh"], ["kpk", "Khyber Pakhtunkhwa"],
    ["balochistan", "Balochistan"], ["federal", "Islamabad (Federal)"],
];
const provinceName = (v) => (PROVINCES.find(p => p[0] === v) || [null, ""])[1];

const Svg = ({ d, s = 16, w = 2 }) => (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={w} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
);
const I = {
    user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
    mail: "M4 6h16v12H4zM4 7l8 6 8-6",
    phone: "M22 16.9v3a2 2 0 0 1-2.2 2A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7l.7 2.8-1.8 2.4a16 16 0 0 0 6 6l2.4-1.8 2.8.7a2 2 0 0 1 1.7 2z",
    pin: "M12 21s6.5-5.6 6.5-11a6.5 6.5 0 1 0-13 0c0 5.4 6.5 11 6.5 11zM12 12.3a2.3 2.3 0 1 0 0-4.6 2.3 2.3 0 0 0 0 4.6z",
    lang: "M4 5h7M8 3v2M5 9c1.5 3 4 5 6 6M11 5c-1 4-3 7-6 9M13 21l4-10 4 10M14.5 17h5",
    pen: "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z",
    check: "M20 6 9 17l-5-5",
    x: "M6 6l12 12M18 6 6 18",
    lock: "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4",
    shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10zM9 12l2 2 4-4",
    trash: "M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14",
    plus: "M12 5v14M5 12h14",
    help: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01",
    out: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
};

const ModProfile = () => {
    const t = useT();
    const toast = useToast();
    const { user, updateUser, logout } = useAuth();
    const { lang, toggleLang } = useLang();
    // The profile can render outside the dashboard's case provider (tests,
    // standalone), so it reads the context without requiring it.
    const caseCtx = useContext(CaseCtx);
    const [tab, setTab] = useState("personal");
    const [editing, setEditing] = useState(null);      // "full_name" | "phone" | "province"
    const [draft, setDraft] = useState("");
    const [saving, setSaving] = useState(false);
    const [pwdMode, setPwdMode] = useState(false);
    const [pwdData, setPwdData] = useState({ current: "", next: "", confirm: "" });
    const [delConfirm, setDelConfirm] = useState(false);
    const [delPassword, setDelPassword] = useState("");
    const [docCount, setDocCount] = useState(null);

    useEffect(() => {
        let live = true;
        Promise.resolve(myDocumentsV2({ limit: 25 })).then(res => {
            if (!live || res?.error) return;
            const items = res?.data?.items;
            if (Array.isArray(items)) setDocCount(`${items.length}${res.data.next_cursor ? "+" : ""}`);
        }).catch(() => {});
        return () => { live = false; };
    }, []);

    const name = (user?.full_name || "").trim();
    const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join("").toUpperCase() || "?";
    const roleName = user?.role ? user.role.charAt(0).toUpperCase() + user.role.slice(1) : "Client";
    const memberSince = user?.created_at
        ? new Date(user.created_at).toLocaleDateString("en-US", { month: "long", year: "numeric" })
        : "";

    // What a complete profile has, from the fields the account really holds.
    const checklist = [
        ["full_name", "your name", Boolean(name)],
        ["email", "an email", Boolean(user?.email)],
        ["phone", "a phone number", Boolean(user?.phone)],
        ["province", "your province", Boolean(user?.province)],
    ];
    const done = checklist.filter(c => c[2]).length;
    const pct = Math.round((done / checklist.length) * 100);
    const missing = checklist.find(c => !c[2]);

    const startEdit = (key) => {
        setEditing(key);
        setDraft(key === "full_name" ? name : (user?.[key] || ""));
    };
    const saveField = async (key, value) => {
        const v = String(value ?? "").trim();
        if (key === "full_name" && !v) { toast.show("Your name cannot be empty.", "warn", 2500); return; }
        setSaving(true);
        const payload = { [key]: v };
        const { error } = await updateMe(payload);
        setSaving(false);
        if (error) { toast.show(error.message || "Could not save. Please try again.", "error"); return; }
        updateUser(payload);
        setEditing(null);
        toast.show("Saved.", "success", 2000);
    };

    const handlePasswordUpdate = async () => {
        if (!pwdData.current) { toast.show("Please enter your current password.", "warn", 2500); return; }
        if (pwdData.next.length < 8) { toast.show("New password must be at least 8 characters.", "warn", 2500); return; }
        if (pwdData.next !== pwdData.confirm) { toast.show("Passwords don't match.", "warn", 2500); return; }
        setSaving(true);
        const { error } = await changePassword(pwdData.current, pwdData.next);
        if (error) {
            toast.show(error.message || "Failed to change password. Please try again.", "error");
        } else {
            toast.show("Password changed. Please sign in again.", "success");
            setPwdMode(false);
            setPwdData({ current: "", next: "", confirm: "" });
            await logout();
            window.location.assign("/login");
        }
        setSaving(false);
    };

    // Closure is irreversible, so the password is re-checked server-side, and
    // the server's own reason for refusing (open engagements, payments) is
    // shown as it said it.
    const handleDeleteConfirm = async () => {
        setDelConfirm(false);
        if (!delPassword.trim()) { toast.show("Enter your password to confirm", "warn"); return; }
        const { data, error } = await closeAccount(delPassword);
        setDelPassword("");
        if (error || !data?.closed) {
            toast.show(error?.message || data?.error || "Could not close the account", "danger");
            return;
        }
        toast.show("Account closed. Signing you out…", "info", 4000);
        setTimeout(async () => {
            await logout();
            window.location.assign("/login");
        }, 1500);
    };

    const go = (path) => { if (typeof window !== "undefined") window.location.assign(path); };
    const cases = caseCtx?.cases || [];
    const apptTotal = Number.isInteger(caseCtx?.appointmentsTotal) ? caseCtx.appointmentsTotal : (caseCtx?.appointments || []).length;

    const rows = [
        { key: "full_name", k: "Full name", v: name, icon: I.user, c: "var(--brand-text)", empty: "Not added", why: "As on your CNIC — used on your documents" },
        { key: "email", k: "Email", v: user?.email || "", icon: I.mail, c: "#6addeb", empty: "Not added", why: "Used to sign in · change it in Security" },
        { key: "phone", k: "Phone", v: user?.phone || "", icon: I.phone, c: "var(--gold)", type: "tel", empty: "Not added", why: "So your lawyer can call you" },
        { key: "province", k: "Province", v: provinceName(user?.province), icon: I.pin, c: "#5ad69a", empty: "Not chosen", why: "Decides which laws apply and which lawyers we suggest" },
    ];

    return (
        <div data-profile-c>
            <style>{PROFILE_CSS}</style>
            <ConfirmDialog isOpen={delConfirm} isDanger title="Close your account?"
                message={"This cannot be undone. Your personal details are erased and you are signed out everywhere. Case, payment and audit records are kept where the law or another party's rights require it. Enter your password below to confirm."}
                onConfirm={handleDeleteConfirm} onCancel={() => { setDelConfirm(false); setDelPassword(""); }}>
                <ThemedInput type="password" value={delPassword} autoComplete="current-password"
                    onChange={e => setDelPassword(e.target.value)} placeholder="Your password" />
            </ConfirmDialog>

            <section className="pc-card pc-head">
                <div className="pc-av" style={{ fontFamily: DOCS_FONT }}>
                    {user?.avatar_url ? <img src={user.avatar_url} alt="" /> : initials}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                    <h1 className="pc-name" style={{ fontFamily: DOCS_FONT }}>{name || "Your name is not set"}</h1>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
                        <span className="pc-chip" style={{ "--c": "var(--brand-text)" }}>{roleName}</span>
                        {memberSince && <span style={{ fontSize: 13, color: "var(--muted)" }}>Member since {memberSince}</span>}
                        <span style={{ fontSize: 13, color: "var(--faint)" }} aria-hidden="true">•</span>
                        {user?.province
                            ? <span style={{ fontSize: 13, color: "var(--muted)" }}>{provinceName(user.province)}</span>
                            : <span style={{ fontSize: 13, color: "var(--gold)" }}>Province not set</span>}
                    </div>
                </div>
                <div className="pc-tabs" role="tablist" aria-label="Profile sections">
                    {[["personal", "Personal"], ["security", "Security"]].map(([id, label]) => (
                        <button key={id} type="button" role="tab" className="pc-tab" aria-selected={tab === id}
                            onClick={() => { setTab(id); setEditing(null); setPwdMode(false); }}>{label}</button>
                    ))}
                </div>
            </section>

            {tab === "personal" && (
                <div className="pc-grid">
                    <div className="pc-col">
                        <section className="pc-card" style={{ overflow: "hidden" }}>
                            <header className="pc-sec-head">
                                <h2 className="pc-h">Personal details</h2>
                                <p>Lawyers you send a case to see your name and phone.</p>
                            </header>
                            {rows.map(r => (
                                <div key={r.key} className="pc-line" style={{ "--c": r.c }}>
                                    <span className="pc-ic"><Svg d={r.icon} /></span>
                                    <span className="pc-k">{r.k}</span>
                                    {editing === r.key ? (
                                        <span className="pc-val">
                                            {r.key === "province" ? (
                                                <span className="pc-provs" role="radiogroup" aria-label="Province">
                                                    {PROVINCES.map(([v, label]) => (
                                                        <button key={v} type="button" role="radio" aria-checked={draft === v} className="pc-prov" onClick={() => setDraft(v)}>{label}</button>
                                                    ))}
                                                </span>
                                            ) : (
                                                <input className="pc-input" type={r.type || "text"} value={draft} autoFocus aria-label={r.k}
                                                    onChange={e => setDraft(e.target.value)}
                                                    onKeyDown={e => { if (e.key === "Enter") saveField(r.key, draft); if (e.key === "Escape") setEditing(null); }} />
                                            )}
                                        </span>
                                    ) : (
                                        <span className="pc-val">
                                            <span className={r.v ? "pc-v" : "pc-v none"}>{r.v || r.empty}</span>
                                            <span className="pc-why">{r.why}</span>
                                        </span>
                                    )}
                                    <span className="pc-act">
                                        {editing === r.key ? (<>
                                            <button type="button" className="pc-btn go" disabled={saving || (r.key === "province" && !draft)} onClick={() => saveField(r.key, draft)}>{saving ? "Saving…" : "Save"}</button>
                                            <button type="button" className="pc-btn" style={{ "--a": "var(--muted)" }} onClick={() => setEditing(null)}>Cancel</button>
                                        </>) : r.key === "email" ? (
                                            <button type="button" className="pc-btn" style={{ "--a": "#6addeb" }} onClick={() => setTab("security")}>Manage</button>
                                        ) : r.v ? (
                                            <button type="button" className="pc-btn" style={{ "--a": "var(--muted)" }} onClick={() => startEdit(r.key)}><Svg d={I.pen} s={13} w={2.2} />Edit</button>
                                        ) : (
                                            <button type="button" className="pc-btn" style={{ "--a": "var(--brand-text)" }} onClick={() => startEdit(r.key)}>+ Add</button>
                                        )}
                                    </span>
                                </div>
                            ))}
                        </section>

                        <section className="pc-card" style={{ overflow: "hidden" }}>
                            <header className="pc-sec-head">
                                <h2 className="pc-h">Preferences</h2>
                                <p>How Attorney.AI talks to you.</p>
                            </header>
                            <div className="pc-line" style={{ "--c": "#b9a6f2" }}>
                                <span className="pc-ic"><Svg d={I.lang} /></span>
                                <span className="pc-k">Language</span>
                                <span className="pc-val">
                                    <span className="pc-v">{lang === "ur" ? "اردو" : "English"}</span>
                                    <span className="pc-why">Menus and screens across the app</span>
                                </span>
                                <span className="pc-act">
                                    <span className="pc-seg" role="radiogroup" aria-label="Language">
                                        <button type="button" role="radio" aria-checked={lang !== "ur"} onClick={() => { if (lang === "ur") toggleLang?.(); }}>English</button>
                                        <button type="button" role="radio" aria-checked={lang === "ur"} onClick={() => { if (lang !== "ur") toggleLang?.(); }}>اردو</button>
                                    </span>
                                </span>
                            </div>
                        </section>
                    </div>

                    <aside className="pc-col">
                        <section className="pc-card pc-sec">
                            <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                                <div className="pc-ring" style={{ background: `conic-gradient(var(--brand-text) 0 ${pct}%, var(--line) ${pct}% 100%)` }}>
                                    <span>{pct}%</span>
                                </div>
                                <div style={{ minWidth: 0 }}>
                                    <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)" }}>{missing ? "Finish your profile" : "Profile complete"}</div>
                                    <div style={{ fontSize: 12.5, color: "var(--muted)" }}>{done} of {checklist.length} done{missing ? " · takes a minute" : ""}</div>
                                </div>
                            </div>
                            <div className="pc-checklist">
                                {checklist.map(([key, label, ok]) => (
                                    <div key={key} className="pc-check-row" data-ok={ok ? "" : undefined}>
                                        <span className="tick" aria-hidden="true">{ok && <Svg d={I.check} s={11} w={3} />}</span>
                                        <span style={{ flex: 1, textTransform: "capitalize" }}>{label.replace(/^(your|a|an) /, "")}</span>
                                        {!ok && key !== "email" && <button type="button" className="pc-link" onClick={() => startEdit(key)}>Add</button>}
                                    </div>
                                ))}
                            </div>
                            {missing && missing[0] !== "email" && (
                                <button type="button" className="pc-cta" onClick={() => startEdit(missing[0])}>
                                    Add {missing[1].replace(/^(your|a|an) /, "")} <span aria-hidden="true">→</span>
                                </button>
                            )}
                        </section>

                        {caseCtx && (
                            <section className="pc-card pc-sec">
                                <h2 className="pc-h" style={{ marginBottom: 12 }}>Your account at a glance</h2>
                                <div className="pc-glance">
                                    {[[cases.length, cases.length === 1 ? "Case" : "Cases", "var(--brand-text)", "/tracking"],
                                      [apptTotal, apptTotal === 1 ? "Appointment" : "Appointments", "#6addeb", "/tracking"],
                                      [docCount ?? "—", docCount === "1" ? "Document" : "Documents", "#b9a6f2", "/documents"]].map(([n, label, c, path]) => (
                                        <button key={label} type="button" className="pc-well" style={{ "--c": c }} onClick={() => go(path)}>
                                            <b style={{ fontFamily: DOCS_FONT }}>{n}</b>
                                            <span>{label}</span>
                                        </button>
                                    ))}
                                </div>
                            </section>
                        )}

                        <nav className="pc-card pc-quick" aria-label="Quick links">
                            <button type="button" style={{ "--c": "var(--brand-text)" }} onClick={() => go("/intake")}><Svg d={I.plus} />Start a new legal intake<i aria-hidden="true">›</i></button>
                            <button type="button" style={{ "--c": "#6addeb" }} onClick={() => go("/faqs")}><Svg d={I.help} />Help &amp; support<i aria-hidden="true">›</i></button>
                            <button type="button" style={{ "--c": "#f28b80" }} onClick={async () => { await logout(); window.location.assign("/login"); }}><Svg d={I.out} />Sign out<i aria-hidden="true">›</i></button>
                        </nav>
                    </aside>
                </div>
            )}

            {tab === "security" && (
                <>
                    <div className="pc-checks">
                        <section className="pc-card pc-check" style={{ "--c": "var(--brand-text)" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                                <span className="pc-ic big"><Svg d={I.mail} s={19} /></span>
                                <span className="pc-chip" style={{ marginLeft: "auto" }}>Sign-in email</span>
                            </div>
                            <div>
                                <div style={{ fontWeight: 700, fontSize: 15.5, color: "var(--ink)" }}>Email</div>
                                <div style={{ marginTop: 3, fontSize: 12.5, color: "var(--muted)", overflowWrap: "anywhere" }}>{user?.email || "No email on file"}</div>
                            </div>
                        </section>
                        <section className="pc-card pc-check" style={{ "--c": "#6addeb" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                                <span className="pc-ic big"><Svg d={I.lock} s={19} /></span>
                                <span className="pc-chip" style={{ marginLeft: "auto" }}>Set</span>
                            </div>
                            <div>
                                <div style={{ fontWeight: 700, fontSize: 15.5, color: "var(--ink)" }}>Password</div>
                                <div style={{ marginTop: 3, fontSize: 12.5, color: "var(--muted)" }}>Use a strong password you use nowhere else.</div>
                            </div>
                            {!pwdMode && <button type="button" className="pc-btn" style={{ "--a": "#6addeb", alignSelf: "flex-start" }} onClick={() => setPwdMode(true)}>Change password</button>}
                        </section>
                        <section className="pc-card pc-check" style={{ "--c": "var(--gold)" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                                <span className="pc-ic big"><Svg d={I.shield} s={19} /></span>
                                <span className="pc-chip" style={{ marginLeft: "auto" }}>Not available yet</span>
                            </div>
                            <div>
                                <div style={{ fontWeight: 700, fontSize: 15.5, color: "var(--ink)" }}>Two-step sign-in</div>
                                <div style={{ marginTop: 3, fontSize: 12.5, color: "var(--muted)" }}>A code on your phone as well as your password. Not offered yet, so it is not protecting your account.</div>
                            </div>
                        </section>
                    </div>

                    {pwdMode && (
                        <section className="pc-card pc-sec" style={{ "--c": "#6addeb" }}>
                            <h2 className="pc-h" style={{ marginBottom: 14 }}>Change password</h2>
                            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 12 }}>
                                {[["current", "Current password", "current-password"], ["next", "New password", "new-password"], ["confirm", "Confirm new password", "new-password"]].map(([k, label, ac]) => (
                                    <label key={k} style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 11, fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase", color: "var(--faint)" }}>
                                        {label}
                                        <ThemedInput type="password" autoComplete={ac} value={pwdData[k]} onChange={e => setPwdData(d => ({ ...d, [k]: e.target.value }))} />
                                    </label>
                                ))}
                            </div>
                            <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
                                <button type="button" className="pc-btn go" disabled={saving} onClick={handlePasswordUpdate}>{saving ? "Updating…" : "Update password"}</button>
                                <button type="button" className="pc-btn" style={{ "--a": "var(--muted)" }} disabled={saving} onClick={() => { setPwdMode(false); setPwdData({ current: "", next: "", confirm: "" }); }}>Cancel</button>
                            </div>
                        </section>
                    )}

                    <section className="pc-card pc-sec">
                        {/* The panel says what to do with an unknown device itself. */}
                        <h2 className="pc-h" style={{ marginBottom: 10 }}>Devices signed in</h2>
                        <SessionsPanel t={t} onSignedOut={logout} />
                    </section>

                    <section className="pc-card" style={{ "--c": "#f28b80", padding: "18px 24px", display: "flex", alignItems: "center", gap: 14, borderColor: "color-mix(in srgb, #f28b80 28%, transparent)" }}>
                        <span className="pc-ic big"><Svg d={I.trash} s={19} /></span>
                        <div style={{ flex: 1 }}>
                            <div style={{ fontWeight: 700, fontSize: 15, color: "var(--ink)" }}>Delete Account</div>
                            <div style={{ fontSize: 12.5, color: "var(--muted)" }}>Permanently removes your account. This cannot be undone.</div>
                        </div>
                        <button type="button" className="pc-btn" style={{ "--a": "#f28b80" }} onClick={() => setDelConfirm(true)}>Delete account…</button>
                    </section>
                </>
            )}
        </div>
    );
};

export default ModProfile;
