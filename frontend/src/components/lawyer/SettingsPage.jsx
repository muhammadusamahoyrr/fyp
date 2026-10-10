'use client';
// Lawyer settings (redesigned 2026-10-09, second pass): an account summary on
// top, a searchable section list, and one section at a time — Overview first.
// Every control here calls a real endpoint. Things the backend does not do yet
// (2-step sign-in, notification preferences, connected apps, team seats,
// stored cards, invoices, data export) are left out rather than shown as
// switches that do nothing.
import { useEffect, useMemo, useRef, useState } from "react";
import { useTheme, useCase } from "./theme.js";
import { useToast } from "@/components/lawyer/Toast.jsx";
import { useAuth } from "@/context/AuthContext.jsx";
import { DRAFTING_TOKENS_CSS, draftingMode } from "./draftingTheme.js";
import SessionsPanel from "./SessionsPanel.jsx";
import {
    changePassword, mySubscription, billingPlans, subscribePlan, cancelSubscription, mockPay, closeAccount,
    getMe, listMyKycDocuments, uploadKycDocument, resubmitKyc, listSessions,
} from "@/lib/api.js";

/* ── icons ── */
const P = {
    grid: ["M4 4h6v6H4z", "M14 4h6v6h-6z", "M4 14h6v6H4z", "M14 14h6v6h-6z"],
    shield: ["M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z", "m9 12 2 2 4-4"],
    lock: ["M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1z", "M8 11V7a4 4 0 0 1 8 0v4"],
    monitor: ["M3 5h18a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z", "M8 21h8M12 17v4"],
    sun: ["M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"],
    card: ["M3 6h18a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1z", "M2 10h20"],
    trash: ["M3 6h18", "M8 6V4h8v2", "M19 6l-1 14H6L5 6", "M10 11v6M14 11v6"],
    search: ["M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14z", "m20 20-3.5-3.5"],
    chev: "m9 18 6-6-6-6",
    check: "M20 6 9 17l-5-5",
    clock: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M12 6v6l4 2"],
    alert: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M12 8v4M12 16h.01"],
    user: ["M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M4 21a8 8 0 0 1 16 0"],
};
const Svg = ({ d, size = 18 }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {[].concat(d).map((p, i) => <path key={i} d={p} />)}
    </svg>
);

/* ── the section list ── */
const NAV = [
    { id: "overview", label: "Overview", icon: "grid", keys: "summary checklist" },
    { group: "Account" },
    { id: "verification", label: "Verification", icon: "shield", keys: "kyc bar council certificate documents upload" },
    { group: "Security" },
    { id: "password", label: "Password", icon: "lock", keys: "change password security" },
    { id: "devices", label: "Devices & activity", icon: "monitor", keys: "sessions sign out signed in" },
    { group: "Preferences" },
    { id: "appearance", label: "Appearance", icon: "sun", keys: "theme dark light" },
    { group: "Billing" },
    { id: "plan", label: "Plan & usage", icon: "card", keys: "subscription upgrade professional firm price" },
];
const IDS = NAV.filter(n => n.id).map(n => n.id).concat("account");

const KYC_DOCS = [
    ["bar_certificate", "Bar Council certificate", "Your enrolment certificate or licence", "PDF, JPEG or PNG"],
    ["education", "Educational credentials", "LLB degree from an HEC-recognised university", "PDF, JPEG or PNG"],
    ["professional", "Professional certificates", "LLM, mediation, specialisations", "PDF, JPEG or PNG"],
    ["photo", "Verification photo", "A clear, recent photo of you", "JPEG or PNG"],
];
const KYC_STATE = {
    approved: ["good", "Verified"],
    pending: ["warn", "Under review"],
    rejected: ["bad", "Action needed"],
    none: ["neutral", "Not submitted"],
};

function strength(pw) {
    if (!pw) return 0;
    if (pw.length < 8) return 1;                 // too short is always the lowest
    let n = 0;
    if (pw.length >= 8) n++;
    if (pw.length >= 12) n++;
    if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) n++;
    if (/\d/.test(pw)) n++;
    if (/[^A-Za-z0-9]/.test(pw)) n++;
    return Math.min(4, n);
}
const STRENGTH = [["", ""], ["Too weak", "#F28B80"], ["Fair", "#F2C35E"], ["Good", "#5AD69A"], ["Strong", "#2EC4A0"]];
const fmtSize = (b) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
const fmtDay = (d) => (d ? new Date(d).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "");

const CSS = `[data-settings-ws]{flex:none;min-height:100%;color:var(--ink);font-family:"Hanken Grotesk",system-ui,sans-serif;-webkit-font-smoothing:antialiased;background:var(--bg);padding:22px 30px 48px;box-sizing:border-box}
[data-settings-ws] *{box-sizing:border-box}
[data-settings-ws] button,[data-settings-ws] input{font-family:inherit}
[data-settings-ws] .st-wrap{max-width:1180px;margin:0 auto;display:grid;gap:18px}
[data-settings-ws] .st-crumb{font-size:13px;color:var(--muted)}
[data-settings-ws] .st-crumb b{color:var(--ink);font-weight:600}
[data-settings-ws] .st-h1{margin:2px 0 0;font-family:"Literata",Georgia,serif;font-size:34px;font-weight:600;letter-spacing:-.01em}
/* account summary */
[data-settings-ws] .st-who{display:flex;align-items:center;gap:20px;flex-wrap:wrap;padding:20px 24px;border-radius:18px;background:var(--surface);border:1px solid var(--line)}
[data-settings-ws] .st-av{position:relative;width:68px;height:68px;flex:none;border-radius:16px;display:grid;place-items:center;background:linear-gradient(135deg,#3EE0A1,#2EC4D6);color:#04212A;font-size:22px;font-weight:800}
[data-settings-ws] .st-av i{position:absolute;right:-4px;bottom:-4px;width:18px;height:18px;border-radius:50%;border:3px solid var(--surface)}
[data-settings-ws] .st-who-tx{flex:1;min-width:240px;display:grid;gap:4px}
[data-settings-ws] .st-who-tx b{font-size:19px}
[data-settings-ws] .st-who-tx span{font-size:13.5px;color:var(--muted)}
[data-settings-ws] .st-mono{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:12.5px;color:var(--brand-text);margin-left:12px}
[data-settings-ws] .st-link{justify-self:start;padding:0;border:0;background:none;color:var(--brand-text);font-size:13.5px;font-weight:700;cursor:pointer}
[data-settings-ws] .st-link:hover{text-decoration:underline}
[data-settings-ws] .st-chips{display:flex;gap:8px;flex-wrap:wrap}
[data-settings-ws] .st-chip{display:inline-flex;align-items:center;gap:8px;height:36px;padding:0 14px;border-radius:999px;background:var(--surface-2);border:1px solid var(--line);font-size:13px;font-weight:600;cursor:pointer;color:var(--ink)}
[data-settings-ws] .st-chip:hover{border-color:var(--brand-text)}
[data-settings-ws] .st-dot{width:8px;height:8px;border-radius:50%;flex:none;background:var(--faint)}
[data-settings-ws] .good .st-dot,[data-settings-ws] .st-dot.good{background:#5AD69A}
[data-settings-ws] .warn .st-dot,[data-settings-ws] .st-dot.warn{background:#F2C35E}
[data-settings-ws] .bad .st-dot,[data-settings-ws] .st-dot.bad{background:#F28B80}
/* layout */
[data-settings-ws] .st-grid{display:grid;grid-template-columns:260px minmax(0,1fr);gap:24px;align-items:start}
[data-settings-ws] .st-grid > div:last-child{min-height:calc(100vh - 28px)}
[data-settings-ws] .st-rail{position:sticky;top:14px;max-height:calc(100vh - 28px);overflow-y:auto;scrollbar-width:none;align-content:start;display:grid;gap:2px;padding:12px;border-radius:18px;background:var(--surface);border:1px solid var(--line)}
[data-settings-ws] .st-find{display:flex;align-items:center;gap:8px;height:40px;padding:0 10px;margin-bottom:6px;border-radius:11px;border:1px solid var(--line-strong);background:var(--input);color:var(--faint)}
[data-settings-ws] .st-find:focus-within{border-color:var(--brand-text)}
[data-settings-ws] .st-find input{flex:1;min-width:0;border:0;background:none;outline:none;color:var(--ink);font-size:13.5px}
[data-settings-ws] .st-find kbd{padding:0 6px;border-radius:5px;border:1px solid var(--line-strong);font-family:"JetBrains Mono",monospace;font-size:11px}
[data-settings-ws] .st-grp{padding:12px 10px 4px;font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--faint)}
[data-settings-ws] .st-nav{display:flex;align-items:center;gap:11px;height:40px;padding:0 10px;border:1px solid transparent;border-radius:10px;background:none;color:var(--muted);font-size:14px;font-weight:600;text-align:left;cursor:pointer}
[data-settings-ws] .st-nav:hover{background:var(--hover-tint);color:var(--ink)}
[data-settings-ws] .st-nav[aria-current="page"]{background:var(--surface-2);border-color:var(--line);color:var(--ink)}
[data-settings-ws] .st-nav[aria-current="page"] svg{color:var(--brand-text)}
[data-settings-ws] .st-nav span{flex:1}
[data-settings-ws] .st-nav.danger{color:#F28B80;margin-top:10px}
[data-settings-ws] .st-nav.danger[aria-current="page"] svg{color:#F28B80}
[data-settings-ws] .st-none{padding:10px;font-size:12.5px;color:var(--faint)}
/* sections */
[data-settings-ws] .st-sec{display:grid;gap:16px;animation:stIn .18s ease-out}
@keyframes stIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
[data-settings-ws] .st-sec > header h2{margin:0;font-family:"Literata",Georgia,serif;font-size:28px;font-weight:600}
[data-settings-ws] .st-sec > header p{margin:6px 0 0;font-size:14px;color:var(--muted);max-width:720px;line-height:1.55}
[data-settings-ws] .st-card{background:var(--surface);border:1px solid var(--line);border-radius:18px;overflow:hidden}
[data-settings-ws] .st-card-h{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:18px 22px;border-bottom:1px solid var(--line)}
[data-settings-ws] .st-card-h h3{margin:0;font-size:16px;font-weight:700}
[data-settings-ws] .st-card-h p{margin:3px 0 0;font-size:13px;color:var(--muted)}
[data-settings-ws] .st-pill{flex:none;display:inline-flex;align-items:center;gap:7px;height:28px;padding:0 12px;border-radius:999px;font-size:12.5px;font-weight:700;border:1px solid var(--line-strong);background:var(--surface-2);color:var(--muted)}
[data-settings-ws] .st-pill.good{color:#5AD69A;border-color:rgba(90,214,154,.4);background:rgba(90,214,154,.1)}
[data-settings-ws] .st-pill.warn{color:#F2C35E;border-color:rgba(242,195,94,.4);background:rgba(242,195,94,.1)}
[data-settings-ws] .st-pill.bad{color:#F28B80;border-color:rgba(242,139,128,.4);background:rgba(242,139,128,.1)}
[data-settings-ws] .st-row{display:flex;align-items:center;gap:14px;padding:16px 22px;border-top:1px solid var(--line)}
[data-settings-ws] .st-row:first-child{border-top:0}
[data-settings-ws] .st-row .tx{flex:1;min-width:0}
[data-settings-ws] .st-row b{display:block;font-size:14.5px}
[data-settings-ws] .st-row small{display:block;font-size:13px;color:var(--muted);margin-top:2px;line-height:1.5}
[data-settings-ws] .st-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 22px;background:var(--surface-2);border-top:1px solid var(--line);font-size:13px;color:var(--muted)}
/* checklist */
[data-settings-ws] .st-progress{display:flex;align-items:center;gap:14px}
[data-settings-ws] .st-progress b{font-family:"Literata",Georgia,serif;font-size:30px}
[data-settings-ws] .st-bar{width:200px;height:6px;border-radius:6px;background:var(--line-strong);overflow:hidden}
[data-settings-ws] .st-bar i{display:block;height:100%;border-radius:6px;background:linear-gradient(90deg,#3EE0A1,#2EC4D6);transition:width .4s}
[data-settings-ws] .st-tick{width:26px;height:26px;flex:none;display:grid;place-items:center;border-radius:50%;border:2px dashed var(--line-strong);color:transparent}
[data-settings-ws] .st-tick.on{border:0;background:#2EC4A0;color:#04212A}
[data-settings-ws] .st-row.done b{text-decoration:line-through;color:var(--muted)}
[data-settings-ws] .st-done{font-size:13px;font-weight:700;color:#5AD69A}
/* tiles */
[data-settings-ws] .st-tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
[data-settings-ws] .st-tile{display:flex;align-items:center;gap:16px;padding:20px;border-radius:18px;border:1px solid var(--line);background:var(--surface);color:var(--ink);text-align:left;cursor:pointer;transition:border-color .15s,transform .15s}
[data-settings-ws] .st-tile:hover{border-color:var(--brand-text);transform:translateY(-1px)}
[data-settings-ws] .st-tile .ic{width:48px;height:48px;flex:none;display:grid;place-items:center;border-radius:13px;background:var(--surface-2);color:var(--brand-text)}
[data-settings-ws] .st-tile .ic.bad{color:#F28B80}
[data-settings-ws] .st-tile .ic.warn{color:#F2C35E}
[data-settings-ws] .st-tile .tx{flex:1;min-width:0}
[data-settings-ws] .st-tile b{display:block;font-size:16px}
[data-settings-ws] .st-tile small{display:block;font-size:13.5px;color:var(--muted);margin-top:3px}
[data-settings-ws] .st-tile > svg{color:var(--faint)}
/* verification */
[data-settings-ws] .st-steps{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;padding:18px 22px;border-bottom:1px solid var(--line)}
[data-settings-ws] .st-steps div{display:grid;gap:8px;font-size:13.5px;color:var(--muted)}
[data-settings-ws] .st-steps i{height:5px;border-radius:5px;background:var(--line-strong)}
[data-settings-ws] .st-steps .on{color:var(--ink);font-weight:700}
[data-settings-ws] .st-steps .on i{background:#F2C35E}
[data-settings-ws] .st-steps .ok i{background:#2EC4A0}
[data-settings-ws] .st-doc-ic{width:44px;height:44px;flex:none;display:grid;place-items:center;border-radius:12px;border:2px dashed var(--line-strong);color:var(--faint);font-size:18px}
[data-settings-ws] .st-doc-ic.on{border:1px solid rgba(46,196,160,.5);background:rgba(46,196,160,.15);color:#5AD69A}
[data-settings-ws] .st-row.drop{background:color-mix(in srgb,var(--brand-text) 10%,transparent);outline:2px dashed var(--brand-text);outline-offset:-6px}
[data-settings-ws] .st-row small.err{color:#F7A79E}
[data-settings-ws] .st-why{margin:16px 22px 0;padding:12px 14px;border-radius:12px;background:rgba(242,139,128,.1);border:1px solid rgba(242,139,128,.35);font-size:13px;line-height:1.5}
[data-settings-ws] .st-note{display:flex;gap:10px;align-items:flex-start;margin:6px 22px 20px;padding:14px 16px;border-radius:12px;background:var(--surface-2);border:1px solid var(--line);font-size:13px;color:var(--muted);line-height:1.5}
[data-settings-ws] .st-note svg{color:var(--brand-text);flex:none;margin-top:1px}
/* forms */
[data-settings-ws] .st-frow{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.2fr);gap:20px;align-items:start;padding:18px 22px;border-top:1px solid var(--line)}
[data-settings-ws] .st-frow b{display:block;font-size:14.5px}
[data-settings-ws] .st-frow small{display:block;font-size:13px;color:var(--muted);margin-top:3px;line-height:1.5}
[data-settings-ws] .st-pw{position:relative}
[data-settings-ws] .st-in{width:100%;height:44px;padding:0 12px;border-radius:11px;border:1px solid var(--line-strong);background:var(--input);color:var(--ink);font-size:14px;outline:none}
[data-settings-ws] .st-in:focus{border-color:var(--brand-text)}
[data-settings-ws] .st-pw .st-in{padding-right:64px}
[data-settings-ws] .st-peek{position:absolute;right:6px;top:50%;transform:translateY(-50%);height:32px;padding:0 10px;border:0;border-radius:8px;background:none;color:var(--muted);font-size:12.5px;font-weight:700;cursor:pointer}
[data-settings-ws] .st-peek:hover{background:var(--hover-tint);color:var(--ink)}
[data-settings-ws] .st-meter{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin-top:10px}
[data-settings-ws] .st-meter i{height:5px;border-radius:5px;background:var(--line-strong);transition:background .2s}
[data-settings-ws] .st-hint{margin-top:8px;font-size:12.5px;color:var(--muted)}
[data-settings-ws] .st-issue{margin:0 22px 16px;padding:10px 12px;border-radius:10px;background:rgba(242,139,128,.1);border:1px solid rgba(242,139,128,.4);color:#F7B4AC;font-size:13px}
[data-settings-ws] .st-btn{height:42px;padding:0 18px;border-radius:11px;border:0;background:linear-gradient(135deg,#3EE0A1,#2EC4D6);color:#04212A;font-size:14px;font-weight:700;cursor:pointer;white-space:nowrap}
[data-settings-ws] .st-btn:disabled{opacity:.55;cursor:default}
[data-settings-ws] .st-btn.ghost{background:none;border:1px solid var(--line-strong);color:var(--ink)}
[data-settings-ws] .st-btn.ghost:hover:not(:disabled){border-color:var(--brand-text)}
[data-settings-ws] .st-btn.danger{background:#D9534F;color:#fff}
[data-settings-ws] .st-btn.sm{height:36px;padding:0 14px;font-size:13px}
/* appearance */
[data-settings-ws] .st-themes{display:grid;grid-template-columns:repeat(2,minmax(0,240px));gap:14px;padding:20px 22px}
[data-settings-ws] .st-theme{padding:10px;border-radius:14px;border:2px solid var(--line);background:none;cursor:pointer;text-align:left;color:var(--ink)}
[data-settings-ws] .st-theme[aria-pressed="true"]{border-color:var(--brand-text)}
[data-settings-ws] .st-theme .sw{height:84px;border-radius:9px;margin-bottom:8px;display:grid;grid-template-columns:28% 1fr;gap:6px;padding:7px}
[data-settings-ws] .st-theme .sw i{border-radius:5px}
/* plans */
[data-settings-ws] .st-plan-head{display:flex;align-items:center;justify-content:space-between;gap:12px}
[data-settings-ws] .st-plan-head h3{margin:0;font-size:17px}
[data-settings-ws] .st-cycle{display:inline-flex;gap:4px;padding:4px;border-radius:12px;background:var(--surface);border:1px solid var(--line)}
[data-settings-ws] .st-cycle button{height:34px;padding:0 14px;border:0;border-radius:9px;background:none;color:var(--muted);font-size:13px;font-weight:700;cursor:pointer}
[data-settings-ws] .st-cycle button[aria-pressed="true"]{background:var(--surface-2);color:var(--ink);box-shadow:inset 0 0 0 1px var(--line)}
[data-settings-ws] .st-plans{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}
[data-settings-ws] .st-plan{position:relative;display:flex;flex-direction:column;gap:6px;padding:22px;border-radius:18px;border:1px solid var(--line);background:var(--surface)}
[data-settings-ws] .st-plan.cur{border-color:var(--brand-text)}
[data-settings-ws] .st-plan .tag{position:absolute;top:-12px;left:50%;transform:translateX(-50%);padding:3px 12px;border-radius:999px;background:linear-gradient(135deg,#3EE0A1,#2EC4D6);color:#04212A;font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;white-space:nowrap}
[data-settings-ws] .st-plan .price{font-family:"Literata",Georgia,serif;font-size:32px;font-weight:600}
[data-settings-ws] .st-plan .price small{font-family:"Hanken Grotesk",sans-serif;font-size:13px;color:var(--muted)}
[data-settings-ws] .st-plan p{margin:0 0 6px;font-size:13.5px;color:var(--muted)}
[data-settings-ws] .st-plan ul{margin:0 0 14px;padding:0;list-style:none;display:grid;gap:8px;flex:1}
[data-settings-ws] .st-plan li{display:flex;gap:8px;font-size:13.5px;line-height:1.45}
[data-settings-ws] .st-plan li svg{color:#2EC4A0;flex:none;margin-top:2px}
/* account */
[data-settings-ws] .s4{border-color:rgba(242,139,128,.35)}
[data-settings-ws] .s4 .st-card-h h3{color:#F28B80}`;

function PasswordInput({ id, value, onChange, placeholder, autoComplete, onEnter }) {
    const [show, setShow] = useState(false);
    return (
        <div className="st-pw">
            <input id={id} className="st-in" type={show ? "text" : "password"} value={value} onChange={onChange}
                placeholder={placeholder} autoComplete={autoComplete} onKeyDown={e => e.key === "Enter" && onEnter?.()} />
            <button type="button" className="st-peek" onClick={() => setShow(v => !v)} aria-label={show ? "Hide password" : "Show password"}>
                {show ? "Hide" : "Show"}
            </button>
        </div>
    );
}

function readSection() {
    try { const h = window.location.hash.replace("#", ""); return IDS.includes(h) ? h : "overview"; } catch { return "overview"; }
}

function SettingsPage() {
    const { t, toggle } = useTheme();
    const { setPage } = useCase();
    const toast = useToast();
    const { logout } = useAuth();
    const [section, setSection] = useState("overview");
    const [query, setQuery] = useState("");
    const findRef = useRef(null);
    const [me, setMe] = useState(null);
    const [sessions, setSessions] = useState(null);
    const [pwd, setPwd] = useState({ current: "", newPwd: "", confirm: "" });
    const [pwdIssue, setPwdIssue] = useState(null);
    const [saving, setSaving] = useState(false);
    const [sub, setSub] = useState(null);
    const [plans, setPlans] = useState([]);
    const [subBusy, setSubBusy] = useState(false);
    const [annual, setAnnual] = useState(false);
    const [kyc, setKyc] = useState({ status: "none", reason: null, docs: {}, busy: null, issues: {}, resubmitting: false, over: null });
    const fileRefs = useRef({});

    useEffect(() => {
        setSection(readSection());
        mySubscription().then(({ data }) => { if (data) setSub(data); });
        billingPlans().then(({ data }) => { if (Array.isArray(data)) setPlans(data); });
        getMe().then(({ data }) => {
            if (!data) return;
            setMe(data);
            const lp = data.lawyer_profile || {};
            setKyc(k => ({ ...k, status: lp.kyc_status || (lp.kyc_verified ? "approved" : "none"), reason: lp.kyc_rejection_reason || null }));
        });
        listMyKycDocuments().then(({ data }) => { if (data && typeof data === "object") setKyc(k => ({ ...k, docs: data })); });
        listSessions().then(({ data }) => { if (data?.items) setSessions(data.items); });
    }, []);

    // Back/Forward and a changed #hash pick the section too.
    useEffect(() => {
        const onHash = () => setSection(readSection());
        window.addEventListener("hashchange", onHash);
        return () => window.removeEventListener("hashchange", onHash);
    }, []);

    // "/" jumps to the settings search.
    useEffect(() => {
        const onKey = (e) => {
            if (e.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "")) { e.preventDefault(); findRef.current?.focus(); }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, []);

    const go = (id) => {
        setSection(id);
        try { window.history.replaceState(window.history.state, "", `#${id}`); } catch { /* no history */ }
        // Bring the section list and the new section to the top of the view.
        // Scrolling to 0 left the account card above them, which pushed most
        // of the list off the bottom of the screen.
        const main = document.querySelector("main");
        const grid = document.querySelector("[data-settings-ws] .st-grid");
        if (main && grid) {
            const top = main.scrollTop + grid.getBoundingClientRect().top - main.getBoundingClientRect().top - 14;
            main.scrollTo?.({ top: Math.max(0, top), behavior: "smooth" });
        }
    };

    const navItems = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q) return NAV;
        const hit = NAV.filter(n => n.id && `${n.label} ${n.keys}`.toLowerCase().includes(q));
        return hit;
    }, [query]);

    const refreshSub = async () => {
        const { data } = await mySubscription();
        if (data) setSub(data);
    };

    const doSubscribe = async (tier) => {
        setSubBusy(true);
        const { data, error } = await subscribePlan(tier, annual ? "annual" : "monthly");
        if (error) { setSubBusy(false); toast.show("❌ " + (error.message || "Subscription failed"), "error", 3000); return; }
        if (data?.dry_run) {
            await mockPay(data.payment_id);       // dev/test: settle immediately
        } else if (data?.checkout_url) {
            window.open(data.checkout_url, "_blank", "noopener");
        }
        await refreshSub();
        setSubBusy(false);
        toast.show("✅ Plan activated", "success", 2500);
    };

    const doCancel = async () => {
        setSubBusy(true);
        const { error } = await cancelSubscription();
        setSubBusy(false);
        if (error) { toast.show("❌ " + (error.message || "Cancel failed"), "error", 3000); return; }
        await refreshSub();
        toast.show("Subscription cancelled — access continues until period end", "info", 3000);
    };

    const handleChangePassword = async () => {
        setPwdIssue(null);
        if (!pwd.current || !pwd.newPwd) return setPwdIssue("Fill in all three fields.");
        if (pwd.newPwd.length < 8) return setPwdIssue("The new password needs at least 8 characters.");
        if (pwd.newPwd !== pwd.confirm) return setPwdIssue("The new passwords do not match.");
        if (pwd.newPwd === pwd.current) return setPwdIssue("Choose a password different from the current one.");
        setSaving(true);
        const { error } = await changePassword(pwd.current, pwd.newPwd);
        setSaving(false);
        if (error) {
            setPwdIssue(error.message || "Password change failed.");
        } else {
            toast.show("✅ Password updated. Please sign in again.", "success");
            setPwd({ current: "", newPwd: "", confirm: "" });
            await logout();
            window.location.assign("/login");
        }
    };

    const uploadDoc = async (kind, file) => {
        setKyc(k => ({ ...k, busy: kind, over: null, issues: { ...k.issues, [kind]: null } }));
        const { data, error } = await uploadKycDocument(kind, file);
        if (error || !data?.[kind]) {
            setKyc(k => ({ ...k, busy: null, issues: { ...k.issues, [kind]: error?.message || "Upload failed. Please try again." } }));
            return;
        }
        setKyc(k => ({ ...k, busy: null, docs: { ...k.docs, [kind]: data[kind] } }));
        toast.show("✅ Document uploaded", "success");
    };

    const askReview = async () => {
        setKyc(k => ({ ...k, resubmitting: true }));
        const { data, error } = await resubmitKyc();
        if (error) {
            setKyc(k => ({ ...k, resubmitting: false }));
            toast.show("❌ " + (error.message || "Could not request a review"), "danger");
            return;
        }
        const lp = data?.lawyer_profile || {};
        setKyc(k => ({ ...k, resubmitting: false, status: lp.kyc_status || "pending", reason: null }));
        toast.show("✅ Sent for review", "success");
    };

    // Account closure. The server re-checks the password (closure is
    // irreversible) and refuses while engagements or payments are live, naming
    // them — that reason is shown verbatim.
    const [closing, setClosing] = useState(null);   // null | { password, busy, issue }
    const handleClose = async () => {
        if (!closing?.password) { setClosing(c => ({ ...c, issue: "Enter your password to confirm." })); return; }
        setClosing(c => ({ ...c, busy: true, issue: null }));
        const { data, error } = await closeAccount(closing.password);
        if (error || !data?.closed) {
            setClosing(c => ({ ...c, busy: false, password: "",
                               issue: error?.message || data?.error || "Could not close the account." }));
            return;
        }
        setClosing(c => ({ ...c, busy: true, issue: null, done: true }));
        await logout();
        window.location.assign("/login");
    };

    const handleSignOut = async () => {
        await logout();
        // Hard redirect: clears all in-memory app state along with the session
        window.location.assign("/login");
    };

    /* ── derived ── */
    const lp = me?.lawyer_profile || {};
    const name = me?.full_name || "Your account";
    const initials = name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
    const province = lp.province || me?.province || "";
    const docCount = KYC_DOCS.filter(([k]) => kyc.docs?.[k]).length;
    const [kycTone, kycLabel] = KYC_STATE[kyc.status === "pending" && docCount === 0 ? "none" : kyc.status] || KYC_STATE.none;
    const tier = sub?.tier || "free";
    const paid = sub && tier !== "free" && sub.status === "active";
    const dark = t.mode === "dark";
    const nSessions = sessions ? sessions.length : null;
    const profileFields = [me?.phone, lp.bar_number, lp.experience_years, lp.hourly_rate, province, lp.address, (lp.bio || "").trim().length >= 40, (lp.specializations || []).length];
    const profileDone = profileFields.filter(Boolean).length;
    const checklist = [
        { id: "kyc", title: "Upload verification documents", sub: `${docCount} of ${KYC_DOCS.length} documents uploaded`, done: kyc.status === "approved" || docCount === KYC_DOCS.length, go: () => go("verification") },
        { id: "profile", title: "Complete your public profile", sub: `${profileDone} of ${profileFields.length} details added — clients choose on these`, done: profileDone === profileFields.length, go: () => setPage?.("profile") },
        { id: "devices", title: "Review signed-in devices", sub: nSessions == null ? "Checking…" : `${nSessions} active session${nSessions === 1 ? "" : "s"}`, done: nSessions === 1, go: () => go("devices") },
    ];
    const doneCount = checklist.filter(c => c.done).length;
    const score = strength(pwd.newPwd);
    // "Pending" with nothing uploaded is still the upload step: there is nothing to review yet.
    const kycStep = kyc.status === "approved" ? 3 : kyc.status === "pending" && docCount > 0 ? 2 : 1;

    const head = (title, sub) => (
        <header><h2>{title}</h2>{sub && <p>{sub}</p>}</header>
    );

    /* ── sections ── */
    const overview = (
        <section className="st-sec" aria-label="Overview">
            {head("Overview", "Your account at a glance. Finish the checklist to make your account secure and visible to clients.")}
            <div className="st-card">
                <div className="st-card-h">
                    <div><h3>Account checklist</h3><p>{doneCount === checklist.length ? "All done." : `${checklist.length - doneCount} thing${checklist.length - doneCount === 1 ? "" : "s"} left to do`}</p></div>
                    <div className="st-progress"><b>{doneCount}/{checklist.length}</b><div className="st-bar"><i style={{ width: `${(doneCount / checklist.length) * 100}%` }} /></div></div>
                </div>
                {checklist.map(c => (
                    <div key={c.id} className={`st-row${c.done ? " done" : ""}`}>
                        <span className={`st-tick${c.done ? " on" : ""}`}><Svg d={P.check} size={14} /></span>
                        <span className="tx"><b>{c.title}</b><small>{c.sub}</small></span>
                        {c.done ? <span className="st-done">Done</span> : <button type="button" className="st-btn ghost sm" onClick={c.go}>Fix</button>}
                    </div>
                ))}
            </div>
            <div className="st-tiles">
                {[
                    ["verification", "shield", kycTone === "good" ? "" : kycTone, "Verification", `${kycLabel} · ${docCount} of ${KYC_DOCS.length} documents`],
                    ["password", "lock", "", "Password", "Change it, and sign out everywhere"],
                    ["devices", "monitor", "", "Devices & activity", nSessions == null ? "Signed-in devices" : `${nSessions} signed-in device${nSessions === 1 ? "" : "s"}`],
                    ["appearance", "sun", "", "Appearance", `${dark ? "Dark" : "Light"} theme`],
                    ["plan", "card", "", "Plan & usage", `${tier.charAt(0).toUpperCase() + tier.slice(1)} plan${paid && sub.current_period_end ? ` · renews ${fmtDay(sub.current_period_end)}` : ""}`],
                    ["account", "trash", "bad", "Sign out & delete", "Leave this device, or close your account"],
                ].map(([id, icon, tone, title, sub]) => (
                    <button key={id} type="button" className="st-tile" onClick={() => go(id)}>
                        <span className={`ic ${tone}`}><Svg d={P[icon]} size={20} /></span>
                        <span className="tx"><b>{title}</b><small>{sub}</small></span>
                        <Svg d={P.chev} />
                    </button>
                ))}
            </div>
        </section>
    );

    const verification = (
        <section className="st-sec" aria-label="Verification">
            {head("Verification", "Clients see the verified mark once our team has checked your Bar enrolment. Upload each document below; you can replace a file until you're verified.")}
            <div className="st-card">
                <div className="st-card-h">
                    <div>
                        <h3>{kyc.status === "approved" ? "You're verified" : kyc.status === "pending" && docCount > 0 ? "Your documents are being reviewed" : kyc.status === "rejected" ? "Something needs fixing" : `${KYC_DOCS.length - docCount} document${KYC_DOCS.length - docCount === 1 ? "" : "s"} to upload`}</h3>
                        <p>{docCount} of {KYC_DOCS.length} uploaded</p>
                    </div>
                    <span className={`st-pill ${kycTone}`}><span className={`st-dot ${kycTone}`} />{kycLabel}</span>
                </div>
                <div className="st-steps">
                    {["Upload", "Review", "Verified"].map((s, i) => (
                        <div key={s} className={i + 1 < kycStep || kycStep === 3 ? "ok" : i + 1 === kycStep ? "on" : ""}><i />{i + 1} · {s}</div>
                    ))}
                </div>
                {kyc.status === "rejected" && kyc.reason && <div className="st-why"><b>Reviewer's note:</b> {kyc.reason}</div>}
                {KYC_DOCS.map(([kind, label, hint, types]) => {
                    const doc = kyc.docs?.[kind];
                    const issue = kyc.issues[kind];
                    const locked = kyc.status === "approved";
                    return (
                        <div key={kind} className={`st-row${kyc.over === kind ? " drop" : ""}`}
                            onDragOver={e => { if (locked) return; e.preventDefault(); if (kyc.over !== kind) setKyc(k => ({ ...k, over: kind })); }}
                            onDragLeave={() => setKyc(k => ({ ...k, over: null }))}
                            onDrop={e => { if (locked) return; e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) uploadDoc(kind, f); else setKyc(k => ({ ...k, over: null })); }}>
                            <span className={`st-doc-ic${doc ? " on" : ""}`} aria-hidden="true">{doc ? <Svg d={P.check} size={18} /> : "+"}</span>
                            <span className="tx">
                                <b>{label}</b>
                                {issue ? <small className="err" role="alert">{issue}</small>
                                    : <small>{doc ? `${doc.filename}${doc.size ? ` · ${fmtSize(doc.size)}` : ""}${doc.uploaded_at ? ` · uploaded ${fmtDay(doc.uploaded_at)}` : ""}` : `${hint} · ${types}`}</small>}
                            </span>
                            <input type="file" hidden accept={kind === "photo" ? "image/jpeg,image/png" : "application/pdf,image/jpeg,image/png"}
                                ref={el => { fileRefs.current[kind] = el; }}
                                onChange={e => { const f = e.target.files?.[0]; e.target.value = ""; if (f) uploadDoc(kind, f); }} />
                            <button type="button" className={`st-btn sm${doc ? " ghost" : ""}`} disabled={kyc.busy === kind || locked}
                                onClick={() => fileRefs.current[kind]?.click()}>
                                {kyc.busy === kind ? "Uploading…" : doc ? "Replace" : "Upload"}
                            </button>
                        </div>
                    );
                })}
                {kyc.status === "rejected" && (
                    <div className="st-foot">
                        <span>Uploaded the fixes? Send your profile back to the review queue.</span>
                        <button type="button" className="st-btn" onClick={askReview} disabled={kyc.resubmitting}>{kyc.resubmitting ? "Sending…" : "Request a new review"}</button>
                    </div>
                )}
                <div className="st-note"><Svg d={P.clock} /><span>Drop a file on a row to upload it. Your documents are only seen by our verification team.</span></div>
            </div>
        </section>
    );

    const password = (
        <section className="st-sec" aria-label="Change password">
            {head("Password", "Keep your account and your clients' files safe.")}
            <div className="st-card">
                <div className="st-card-h"><div><h3>Change password</h3><p>You'll be signed out on every device after changing it, and sign in again with the new one.</p></div></div>
                <div className="st-frow" style={{ borderTop: 0 }}>
                    <span><b>Current password</b></span>
                    <PasswordInput id="st-cur" placeholder="Enter current password" autoComplete="current-password"
                        value={pwd.current} onChange={e => setPwd(p => ({ ...p, current: e.target.value }))} />
                </div>
                <div className="st-frow">
                    <span><b>New password</b><small>At least 8 characters. A short phrase with a number works well.</small></span>
                    <div>
                        <PasswordInput id="st-new" placeholder="New password" autoComplete="new-password"
                            value={pwd.newPwd} onChange={e => setPwd(p => ({ ...p, newPwd: e.target.value }))} />
                        <div className="st-meter">{[1, 2, 3, 4].map(i => <i key={i} style={{ background: score >= i ? STRENGTH[score][1] : undefined }} />)}</div>
                        <div className="st-hint" style={{ color: score ? STRENGTH[score][1] : undefined }}>{score ? STRENGTH[score][0] : "Use 8+ characters."}</div>
                    </div>
                </div>
                <div className="st-frow">
                    <span><b>Confirm new password</b></span>
                    <div>
                        <PasswordInput id="st-conf" placeholder="Type it again" autoComplete="new-password" onEnter={handleChangePassword}
                            value={pwd.confirm} onChange={e => setPwd(p => ({ ...p, confirm: e.target.value }))} />
                        {pwd.confirm && <div className="st-hint" style={{ color: pwd.confirm === pwd.newPwd ? "#5AD69A" : "#F7A79E" }}>{pwd.confirm === pwd.newPwd ? "✓ Passwords match" : "Doesn't match yet"}</div>}
                    </div>
                </div>
                {pwdIssue && <div className="st-issue" role="alert">{pwdIssue}</div>}
                <div className="st-foot">
                    <span>Forgot it? Sign out and use “Forgot password” on the sign-in page.</span>
                    <button type="button" className="st-btn" onClick={handleChangePassword} disabled={saving}>{saving ? "Updating…" : "Update Password"}</button>
                </div>
            </div>
        </section>
    );

    const devices = (
        <section className="st-sec" aria-label="Active sessions">
            {head("Devices & activity", "Where you're signed in. If you don't recognise a device, sign it out and change your password.")}
            <div className="st-card" style={{ padding: "18px 22px" }}>
                <SessionsPanel t={t} onSignedOut={logout} />
            </div>
        </section>
    );

    const appearance = (
        <section className="st-sec" aria-label="Appearance">
            {head("Appearance", "How your workspace looks on this device.")}
            <div className="st-card">
                <div className="st-card-h"><div><h3>Theme</h3><p>Dark is easier on the eyes in long drafting sessions.</p></div></div>
                <div className="st-themes" role="group" aria-label="Theme">
                    {[["dark", "Dark", ["#403E42", "#183840", "#0F2429"]], ["light", "Light", ["#ECEBEE", "#FFFFFF", "#DCE3E5"]]].map(([mode, label, [bg, a, b]]) => (
                        <button key={mode} type="button" className="st-theme" aria-pressed={(mode === "dark") === dark}
                            onClick={() => { if ((mode === "dark") !== dark) toggle(); }}>
                            <div className="sw" style={{ background: bg }}>
                                <i style={{ background: a }} />
                                <span style={{ display: "grid", gap: 6 }}><i style={{ background: a, height: 22 }} /><i style={{ background: b, height: 40 }} /></span>
                            </div>
                            <b style={{ fontSize: 13.5 }}>{label}{(mode === "dark") === dark ? " · in use" : ""}</b>
                        </button>
                    ))}
                </div>
            </div>
        </section>
    );

    const allPlans = [{ tier: "free", name: "Free", price: { monthly: 0, annual: 0 }, blurb: "Try the platform.", features: [] }, ...plans.filter(p => p.tier !== "free")];
    const plan = (
        <section className="st-sec" aria-label="Subscription">
            {head("Plan & usage", paid ? `You're on the ${sub.tier} plan.${sub.current_period_end ? ` It renews on ${fmtDay(sub.current_period_end)}.` : ""}` : "You're on the Free plan. Upgrade when you need more; you can cancel any time.")}
            {paid && (
                <div className="st-card">
                    <div className="st-row">
                        <span className="tx"><b style={{ textTransform: "capitalize" }}>{sub.tier} · {sub.cycle || "monthly"}</b><small>{sub.status === "cancelled" ? "Cancelled — access continues until the period ends." : "Unlimited cause-list watches, AI research and case-law are unlocked."}</small></span>
                        <button type="button" className="st-btn ghost" onClick={doCancel} disabled={subBusy}>Cancel plan</button>
                    </div>
                </div>
            )}
            <div className="st-plan-head">
                <h3>Compare plans</h3>
                <div className="st-cycle" role="group" aria-label="Billing cycle">
                    <button type="button" aria-pressed={!annual} onClick={() => setAnnual(false)}>Monthly</button>
                    <button type="button" aria-pressed={annual} onClick={() => setAnnual(true)}>Annual · save 25%</button>
                </div>
            </div>
            <div className="st-plans">
                {allPlans.map(p => {
                    const current = p.tier === tier;
                    return (
                        <div key={p.tier} className={`st-plan${current ? " cur" : ""}`}>
                            {p.tier === "professional" && !current && <span className="tag">Most chosen</span>}
                            <b style={{ fontSize: 15 }}>{p.name}</b>
                            <div className="price">Rs {Number(annual ? p.price.annual : p.price.monthly).toLocaleString()}<small>/mo</small></div>
                            <p>{p.blurb}</p>
                            {p.features?.length > 0 && <ul>{p.features.map(f => <li key={f}><Svg d={P.check} size={15} />{f}</li>)}</ul>}
                            {current
                                ? <button type="button" className="st-btn ghost" disabled>Current plan</button>
                                : p.tier !== "free" && <button type="button" className="st-btn" onClick={() => doSubscribe(p.tier)} disabled={subBusy}>{subBusy ? "…" : `Choose ${p.name}`}</button>}
                        </div>
                    );
                })}
            </div>
            {plans.length === 0 && <div style={{ fontSize: 13, color: "var(--muted)" }}>Plans could not be loaded right now.</div>}
        </section>
    );

    const account = (
        <section className="st-sec" aria-label="Account">
            {head("Sign out & delete", "Leave this device, or close your account for good.")}
            <div className="st-card fade-up s4">
                <div className="st-card-h"><div><h3>Danger Zone</h3><p>These can't be reversed from here.</p></div></div>
                <div className="st-row">
                    <span className="tx"><b>Sign out</b><small>Sign out of your account on this device. You will need to log back in to access your cases.</small></span>
                    <button type="button" className="st-btn ghost" onClick={handleSignOut}>Sign Out</button>
                </div>
                <div className="st-row">
                    <span className="tx"><b style={{ color: "#F28B80" }}>Delete account</b><small>Permanently delete your account. This cannot be undone.</small></span>
                    {!closing && <button type="button" className="st-btn danger" onClick={() => setClosing({ password: "", busy: false, issue: null })}>Delete Account</button>}
                </div>
                {closing && (
                    <div style={{ display: "grid", gap: 10, padding: "0 22px 20px" }}>
                        <div style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.55 }}>
                            Your personal details are erased and you are signed out everywhere. Case, payment and audit records are kept where the law or a client's rights require it. Enter your password to confirm.
                        </div>
                        <input className="st-in" type="password" placeholder="Current password" autoComplete="current-password"
                            value={closing.password} onChange={e => setClosing(c => ({ ...c, password: e.target.value }))} />
                        {closing.issue && <div role="alert" className="st-issue" style={{ margin: 0 }}>{closing.issue}</div>}
                        <div style={{ display: "flex", gap: 8 }}>
                            <button type="button" className="st-btn danger" onClick={handleClose} disabled={closing.busy}>
                                {closing.done ? "Account closed. Signing out…" : closing.busy ? "Closing…" : "Permanently close account"}
                            </button>
                            <button type="button" className="st-btn ghost" onClick={() => setClosing(null)} disabled={closing.busy}>Cancel</button>
                        </div>
                    </div>
                )}
            </div>
        </section>
    );

    const body = { overview, verification, password, devices, appearance, plan, account }[section] || overview;

    return (
        <div data-settings-ws data-drafting-theme data-mode={draftingMode(t)}>
            <style>{`${DRAFTING_TOKENS_CSS}\n${CSS}`}</style>
            <div className="st-wrap">
                <div>
                    <div className="st-crumb">Account / <b>Settings</b></div>
                    <h1 className="st-h1">Settings</h1>
                </div>

                {/* Who this account is, and what needs attention */}
                <section className="st-who" aria-label="Account summary">
                    <span className="st-av">{initials}<i style={{ background: kycTone === "good" ? "#5AD69A" : kycTone === "bad" ? "#F28B80" : "#F2C35E" }} /></span>
                    <div className="st-who-tx">
                        <b>{name}</b>
                        <span>Advocate{province ? `, ${province.charAt(0).toUpperCase() + province.slice(1)}` : ""}{lp.bar_number && <span className="st-mono">Enrolment {lp.bar_number}</span>}</span>
                        {me?.email && <span>{me.email}</span>}
                        {setPage && <button type="button" className="st-link" onClick={() => setPage("profile")}>Edit profile on your Profile page →</button>}
                    </div>
                    <div className="st-chips">
                        <button type="button" className={`st-chip ${kycTone}`} onClick={() => go("verification")}><span className="st-dot" />Verification {docCount}/{KYC_DOCS.length}</button>
                        <button type="button" className="st-chip" onClick={() => go("devices")}><span className="st-dot good" />{nSessions == null ? "Devices" : `${nSessions} device${nSessions === 1 ? "" : "s"}`}</button>
                        <button type="button" className={`st-chip ${paid ? "good" : ""}`} onClick={() => go("plan")}><span className="st-dot" /><span style={{ textTransform: "capitalize" }}>{tier}</span> plan</button>
                    </div>
                </section>

                <div className="st-grid">
                    <nav className="st-rail" aria-label="Settings sections">
                        <label className="st-find">
                            <Svg d={P.search} size={16} />
                            <input ref={findRef} value={query} onChange={e => setQuery(e.target.value)} placeholder="Search settings" aria-label="Search settings"
                                onKeyDown={e => { if (e.key === "Enter" && navItems.find(n => n.id)) { go(navItems.find(n => n.id).id); setQuery(""); } if (e.key === "Escape") setQuery(""); }} />
                            <kbd>/</kbd>
                        </label>
                        {navItems.map((n, i) => n.group
                            ? <div key={`g${i}`} className="st-grp">{n.group}</div>
                            : (
                                <button key={n.id} type="button" className="st-nav" aria-current={section === n.id ? "page" : undefined} onClick={() => go(n.id)}>
                                    <Svg d={P[n.icon]} /><span>{n.label}</span>
                                    {n.id === "verification" && kycTone !== "good" && <span className={`st-dot ${kycTone}`} style={{ flex: "none" }} />}
                                </button>
                            ))}
                        {query && !navItems.some(n => n.id) && <div className="st-none">No setting matches “{query}”.</div>}
                        {!query && (
                            <button type="button" className="st-nav danger" aria-current={section === "account" ? "page" : undefined} onClick={() => go("account")}>
                                <Svg d={P.trash} /><span>Sign out & delete</span>
                            </button>
                        )}
                    </nav>
                    <div>{body}</div>
                </div>
            </div>
        </div>
    );
}

export { SettingsPage };
