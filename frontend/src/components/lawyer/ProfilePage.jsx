'use client';
// The lawyer's own profile (redesigned 2026-10-09). Shows what clients see and
// where verification stands — read from the account, never assumed: the old
// page printed "Verified" for everyone, including lawyers still in KYC review.
import { useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "./theme.js";
import { useToast } from "@/components/lawyer/Toast.jsx";
import { DRAFTING_TOKENS_CSS, draftingMode } from "./draftingTheme.js";
import { ModalPortal } from "./ui.jsx";
import { useAuth } from "@/context/AuthContext.jsx";
import { getMe, updateMe, updateLawyerProfile, changePassword, closeAccount } from "@/lib/api.js";

const PROVINCES = [["punjab", "Punjab"], ["sindh", "Sindh"], ["kpk", "Khyber Pakhtunkhwa"], ["balochistan", "Balochistan"], ["federal", "Federal (Islamabad)"]];
const PRACTICE_AREAS = ["civil", "criminal", "family", "constitutional", "property", "corporate", "banking", "tax", "labour", "cyber"];
const BIO_MAX = 600;

const KYC = {
    approved: { label: "Verified lawyer", tone: "good", note: "Your Bar enrolment was checked by our team." },
    pending: { label: "Verification pending", tone: "warn", note: "Your documents are with our team for review." },
    rejected: { label: "Verification rejected", tone: "bad", note: "Fix the issue below and submit your documents again from Settings." },
    none: { label: "Not verified", tone: "neutral", note: "Submit your Bar documents from Settings to get verified." },
};

const PROFILE_CSS = `[data-profile-ws]{flex:none;min-height:100%;color:var(--ink);font-family:"Hanken Grotesk",system-ui,sans-serif;-webkit-font-smoothing:antialiased;background:var(--bg);padding:26px 30px 40px;box-sizing:border-box}
[data-profile-ws] *{box-sizing:border-box}
[data-profile-ws] button,[data-profile-ws] input,[data-profile-ws] select,[data-profile-ws] textarea{font-family:inherit}
[data-profile-ws] .pf-wrap{max-width:1120px;margin:0 auto;display:grid;gap:16px}
[data-profile-ws] .pf-title h1{margin:0;font-family:"Literata",Georgia,serif;font-size:28px;font-weight:600;letter-spacing:-.01em}
[data-profile-ws] .pf-title p{margin:4px 0 0;font-size:13.5px;color:var(--muted)}
[data-profile-ws] .pf-card{background:var(--surface);border:1px solid var(--line);border-radius:16px}
[data-profile-ws] .pf-hero{display:flex;align-items:center;gap:20px;padding:22px 24px;flex-wrap:wrap;background:radial-gradient(600px 180px at 0% 0%,color-mix(in srgb,var(--brand-text) 14%,transparent),transparent 70%),var(--surface)}
[data-profile-ws] .pf-av{width:84px;height:84px;flex:none;border-radius:50%;display:grid;place-items:center;overflow:hidden;background:linear-gradient(135deg,#3EE0A1,#2EC4D6);color:#04212A;font-family:"Literata",Georgia,serif;font-size:28px;font-weight:700;box-shadow:0 0 0 4px var(--surface),0 0 0 5px var(--line-strong)}
[data-profile-ws] .pf-av img{width:100%;height:100%;object-fit:cover}
[data-profile-ws] .pf-who{flex:1;min-width:220px}
[data-profile-ws] .pf-who h2{margin:0;font-size:22px;font-weight:700}
[data-profile-ws] .pf-who .role{font-size:13.5px;color:var(--muted);margin-top:2px;text-transform:capitalize}
[data-profile-ws] .pf-chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
[data-profile-ws] .pf-chip{display:inline-flex;align-items:center;gap:6px;height:26px;padding:0 10px;border-radius:999px;font-size:12px;font-weight:700;border:1px solid var(--line-strong);color:var(--muted);background:var(--surface-2)}
[data-profile-ws] .pf-chip i{width:7px;height:7px;border-radius:50%;background:currentColor}
[data-profile-ws] .pf-chip.good{color:#5AD69A;border-color:rgba(90,214,154,.4);background:rgba(90,214,154,.1)}
[data-profile-ws] .pf-chip.warn{color:#F2C35E;border-color:rgba(242,195,94,.4);background:rgba(242,195,94,.1)}
[data-profile-ws] .pf-chip.bad{color:#F28B80;border-color:rgba(242,139,128,.4);background:rgba(242,139,128,.1)}
[data-profile-ws] .pf-meter{display:flex;align-items:center;gap:14px;padding:12px 16px;border-radius:14px;background:var(--surface-2);border:1px solid var(--line)}
[data-profile-ws] .pf-meter b{display:block;font-size:14px}
[data-profile-ws] .pf-meter small{display:block;font-size:12px;color:var(--muted);max-width:200px}
[data-profile-ws] .pf-grid{display:grid;grid-template-columns:300px minmax(0,1fr);gap:16px;align-items:start}
[data-profile-ws] .pf-side{display:grid;gap:16px}
[data-profile-ws] .pf-sec{padding:18px 20px}
[data-profile-ws] .pf-sec h3{margin:0 0 2px;font-size:15px;font-weight:700}
[data-profile-ws] .pf-sec > p{margin:0 0 14px;font-size:12.5px;color:var(--muted)}
[data-profile-ws] .pf-facts{display:grid;gap:12px;margin-top:4px}
[data-profile-ws] .pf-fact{display:flex;gap:10px;align-items:flex-start;font-size:13px}
[data-profile-ws] .pf-fact svg{flex:none;margin-top:1px;color:var(--brand-text)}
[data-profile-ws] .pf-fact span{min-width:0;overflow-wrap:anywhere}
[data-profile-ws] .pf-fact small{display:block;font-size:11px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--faint)}
[data-profile-ws] .pf-fact .none{color:var(--faint)}
[data-profile-ws] .pf-kyc{padding:14px 16px;border-radius:14px;border:1px solid var(--line);font-size:12.5px;line-height:1.5;color:var(--muted)}
[data-profile-ws] .pf-kyc b{display:block;font-size:13.5px;margin-bottom:2px}
[data-profile-ws] .pf-kyc.good b{color:#5AD69A}
[data-profile-ws] .pf-kyc.warn b{color:#F2C35E}
[data-profile-ws] .pf-kyc.bad b{color:#F28B80}
[data-profile-ws] .pf-kyc .why{margin-top:8px;padding:8px 10px;border-radius:9px;background:rgba(242,139,128,.1);color:var(--ink)}
[data-profile-ws] .pf-form{display:grid;gap:16px}
[data-profile-ws] .pf-row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
[data-profile-ws] .pf-field label{display:block;font-size:11.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--faint);margin-bottom:6px}
[data-profile-ws] .pf-in{width:100%;height:42px;padding:0 12px;border-radius:10px;border:1px solid var(--line-strong);background:var(--input);color:var(--ink);font-size:14px;outline:none;transition:border-color .15s}
[data-profile-ws] .pf-in:focus{border-color:var(--brand-text)}
[data-profile-ws] .pf-in[readonly]{color:var(--muted);cursor:not-allowed;background:var(--surface-2)}
[data-profile-ws] textarea.pf-in{height:auto;min-height:110px;padding:10px 12px;line-height:1.55;resize:vertical}
[data-profile-ws] .pf-hint{font-size:11.5px;color:var(--faint);margin-top:5px;display:flex;justify-content:space-between;gap:8px}
[data-profile-ws] .pf-pre{position:relative}
[data-profile-ws] .pf-pre span{position:absolute;left:12px;top:50%;transform:translateY(-50%);font-size:13px;font-weight:700;color:var(--faint)}
[data-profile-ws] .pf-pre .pf-in{padding-left:42px}
[data-profile-ws] .pf-areas{display:flex;gap:7px;flex-wrap:wrap}
[data-profile-ws] .pf-area{height:32px;padding:0 13px;border-radius:999px;border:1px solid var(--line-strong);background:none;color:var(--muted);font-size:13px;font-weight:600;cursor:pointer;text-transform:capitalize;transition:all .15s}
[data-profile-ws] .pf-area:hover{border-color:var(--brand-text);color:var(--ink)}
[data-profile-ws] .pf-area[aria-pressed="true"]{background:color-mix(in srgb,var(--brand-text) 16%,transparent);border-color:var(--brand-text);color:var(--brand-text)}
[data-profile-ws] .pf-switch{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 14px;border-radius:12px;border:1px solid var(--line);background:var(--surface-2);cursor:pointer}
[data-profile-ws] .pf-switch b{display:block;font-size:13.5px}
[data-profile-ws] .pf-switch small{display:block;font-size:12px;color:var(--muted)}
[data-profile-ws] .pf-switch input{appearance:none;width:42px;height:24px;border-radius:999px;background:var(--line-strong);position:relative;cursor:pointer;flex:none;transition:background .15s}
[data-profile-ws] .pf-switch input::after{content:"";position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:50%;background:#fff;transition:left .15s}
[data-profile-ws] .pf-switch input:checked{background:#2EC4A0}
[data-profile-ws] .pf-switch input:checked::after{left:21px}
[data-profile-ws] .pf-save{position:sticky;bottom:14px;z-index:5;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;border-radius:14px;border:1px solid var(--line-strong);background:var(--surface);box-shadow:0 -14px 28px -6px var(--bg),0 16px 34px -14px rgba(0,0,0,.7)}
[data-profile-ws] .pf-save span{font-size:13px;color:var(--muted)}
[data-profile-ws] .pf-save span.dirty{color:#F2C35E;font-weight:600}
[data-profile-ws] .pf-btn{height:40px;padding:0 18px;border-radius:10px;border:0;background:linear-gradient(135deg,#3EE0A1,#2EC4D6);color:#04212A;font-size:13.5px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;gap:8px}
[data-profile-ws] .pf-btn:disabled{opacity:.55;cursor:default}
[data-profile-ws] .pf-btn.ghost{background:none;border:1px solid var(--line-strong);color:var(--ink)}
[data-profile-ws] .pf-btn.danger{background:#D9534F;color:#fff}
[data-profile-ws] .pf-in.invalid{border-color:#F28B80;background:color-mix(in srgb,#F28B80 6%,var(--input))}
[data-profile-ws] .pf-err{margin-top:5px;font-size:12px;color:#F7A79E}
[data-profile-ws] .pf-flash{animation:pfFlash 1.1s ease-out}
@keyframes pfFlash{0%,40%{box-shadow:0 0 0 3px color-mix(in srgb,var(--brand-text) 55%,transparent)}100%{box-shadow:0 0 0 0 transparent}}
[data-profile-ws] .pf-miss{display:flex;flex-wrap:wrap;gap:5px;margin-top:5px;max-width:260px}
[data-profile-ws] .pf-miss button{height:24px;padding:0 9px;border-radius:999px;border:1px dashed var(--line-strong);background:none;color:var(--brand-text);font-size:11.5px;font-weight:700;cursor:pointer}
[data-profile-ws] .pf-miss button:hover{border-style:solid;border-color:var(--brand-text)}
[data-profile-ws] .pf-miss small{align-self:center}
[data-profile-ws] .pf-kbd{margin-left:8px;padding:1px 6px;border-radius:5px;border:1px solid var(--line-strong);border-bottom-width:2px;font-family:"JetBrains Mono",ui-monospace,monospace;font-size:10.5px;color:var(--muted)}
[data-profile-ws] .pf-prev{padding:14px;border-radius:14px;background:var(--surface-2);border:1px solid var(--line);display:grid;gap:11px}
[data-profile-ws] .pf-prev-top{display:flex;align-items:center;gap:10px}
[data-profile-ws] .pf-prev-av{width:42px;height:42px;flex:none;border-radius:50%;display:grid;place-items:center;overflow:hidden;background:linear-gradient(135deg,#3EE0A1,#2EC4D6);color:#04212A;font-weight:800;font-size:14px}
[data-profile-ws] .pf-prev-av img{width:100%;height:100%;object-fit:cover}
[data-profile-ws] .pf-prev-top b{display:flex;align-items:center;gap:6px;font-size:14.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-profile-ws] .pf-prev-top small{display:block;font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-profile-ws] .pf-tick{display:inline-grid;place-items:center;width:16px;height:16px;border-radius:50%;background:#2EC4A0;color:#04212A;font-size:10px;font-weight:900}
[data-profile-ws] .pf-prev-areas{display:flex;flex-wrap:wrap;gap:5px}
[data-profile-ws] .pf-prev-areas span{height:22px;padding:0 8px;display:inline-flex;align-items:center;border-radius:999px;background:color-mix(in srgb,var(--brand-text) 14%,transparent);color:var(--brand-text);font-size:11.5px;font-weight:700;text-transform:capitalize}
[data-profile-ws] .pf-prev-areas span.none{background:none;color:var(--faint);padding:0;font-weight:500}
[data-profile-ws] .pf-prev-stats{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid var(--line);border-radius:10px;overflow:hidden}
[data-profile-ws] .pf-prev-stats div{padding:8px 6px;text-align:center;border-left:1px solid var(--line)}
[data-profile-ws] .pf-prev-stats div:first-child{border-left:0}
[data-profile-ws] .pf-prev-stats b{display:block;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-profile-ws] .pf-prev-stats small{display:block;font-size:10.5px;color:var(--faint);text-transform:uppercase;letter-spacing:.06em}
[data-profile-ws] .pf-prev-bio{margin:0;font-size:12.5px;color:var(--muted);line-height:1.5;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
[data-profile-ws] .pf-prev-cta{height:34px;display:grid;place-items:center;border-radius:9px;background:linear-gradient(135deg,#3EE0A1,#2EC4D6);color:#04212A;font-size:12.5px;font-weight:800}
[data-profile-ws] .pf-prev-cta.off{background:var(--surface);color:var(--faint);border:1px solid var(--line)}
[data-profile-ws] .pf-act{display:flex;align-items:center;gap:12px;width:100%;padding:11px 12px;margin-top:8px;border-radius:12px;border:1px solid var(--line);background:var(--surface-2);color:var(--ink);text-align:left;cursor:pointer;transition:border-color .15s,background .15s}
[data-profile-ws] .pf-act:hover{border-color:var(--brand-text)}
[data-profile-ws] .pf-act svg{color:var(--brand-text);flex:none}
[data-profile-ws] .pf-act b{display:block;font-size:13.5px}
[data-profile-ws] .pf-act small{display:block;font-size:12px;color:var(--muted)}
[data-profile-ws] .pf-act.danger svg,[data-profile-ws] .pf-act.danger b{color:#F28B80}
[data-profile-ws] .pf-act.danger:hover{border-color:rgba(242,139,128,.6);background:rgba(242,139,128,.08)}
[data-profile-ws] .pf-scrim{position:fixed;inset:0;z-index:300;display:grid;place-items:center;padding:20px;background:rgba(5,14,18,.6);backdrop-filter:blur(3px);animation:pfFade .15s ease-out}
@keyframes pfFade{from{opacity:0}to{opacity:1}}
[data-profile-ws] .pf-dialog{width:min(440px,100%);display:grid;gap:12px;padding:22px;border-radius:18px;background:var(--surface);border:1px solid var(--line-strong);box-shadow:0 30px 70px -20px rgba(0,0,0,.8)}
[data-profile-ws] .pf-dialog h3{margin:0;font-size:18px;font-weight:700}
[data-profile-ws] .pf-dialog p{margin:0;font-size:13px;color:var(--muted);line-height:1.55}
[data-profile-ws] .pf-issue{padding:9px 12px;border-radius:10px;background:rgba(242,139,128,.1);border:1px solid rgba(242,139,128,.4);color:#F7B4AC;font-size:12.5px}
[data-profile-ws] .pf-dlg-acts{display:flex;justify-content:flex-end;gap:8px;margin-top:4px}`;

const Svg = ({ d, size = 16 }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {[].concat(d).map((p, i) => <path key={i} d={p} />)}
    </svg>
);
const ICON = {
    mail: ["M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z", "m3 7 9 6 9-6"],
    phone: "M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z",
    pin: ["M12 22s7-6.1 7-12a7 7 0 0 0-14 0c0 5.9 7 12 7 12z", "M12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z"],
    badge: ["M12 15a6 6 0 1 0 0-12 6 6 0 0 0 0 12z", "M8.2 13.9 7 22l5-3 5 3-1.2-8.1"],
    clock: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M12 6v6l4 2"],
    coin: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M15 9.5c-.5-1-1.6-1.5-3-1.5-1.7 0-3 .8-3 2s1.3 1.7 3 2 3 .8 3 2-1.3 2-3 2c-1.4 0-2.5-.5-3-1.5", "M12 6v2M12 16v2"],
    lock: ["M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1z", "M8 11V7a4 4 0 0 1 8 0v4"],
    trash: ["M3 6h18", "M8 6V4h8v2", "M19 6l-1 14H6L5 6", "M10 11v6M14 11v6"],
    star: "m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z",
    save: ["M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z", "M17 21v-8H7v8M7 3v5h8"],
};

const EMPTY = {
    first_name: "", last_name: "", email: "", phone: "", areas: [], bar_number: "",
    experience: "", hourly_rate: "", address: "", bio: "", province: "", availability: true,
};

function Ring({ pct }) {
    const r = 22, c = 2 * Math.PI * r;
    return (
        <svg width={56} height={56} viewBox="0 0 56 56" aria-hidden="true">
            <circle cx="28" cy="28" r={r} fill="none" stroke="var(--line-strong)" strokeWidth="5" />
            <circle cx="28" cy="28" r={r} fill="none" stroke="#2EC4A0" strokeWidth="5" strokeLinecap="round"
                strokeDasharray={c} strokeDashoffset={c * (1 - pct / 100)} transform="rotate(-90 28 28)" style={{ transition: "stroke-dashoffset .4s" }} />
            <text x="28" y="32" textAnchor="middle" fontSize="13" fontWeight="800" fill="var(--ink)">{pct}%</text>
        </svg>
    );
}

function ProfilePage() {
    const { t } = useTheme();
    const toast = useToast();
    const [saving, setSaving] = useState(false);
    const [form, setForm] = useState(EMPTY);
    const [saved, setSaved] = useState(EMPTY);     // what the server holds, for "unsaved changes"
    const [meta, setMeta] = useState({ kyc: "none", reason: null, rating: 0, reviews: 0, since: null, avatar: null });

    useEffect(() => {
        getMe().then(({ data }) => {
            if (!data) return;
            const parts = (data.full_name || "").split(" ");
            const lp = data.lawyer_profile || {};
            const next = {
                first_name: parts[0] || "",
                last_name: parts.slice(1).join(" ") || "",
                email: data.email || "",
                phone: data.phone || "",
                areas: (lp.specializations || []).map(s => String(s).toLowerCase()),
                bar_number: lp.bar_number || "",
                experience: lp.experience_years ? String(lp.experience_years) : "",
                hourly_rate: lp.hourly_rate ? String(lp.hourly_rate) : "",
                address: lp.address || "",
                bio: lp.bio || "",
                province: lp.province || data.province || "",
                availability: lp.availability !== false,
            };
            setForm(next); setSaved(next);
            setMeta({
                kyc: lp.kyc_status || (lp.kyc_verified ? "approved" : "none"),
                reason: lp.kyc_rejection_reason || null,
                rating: Number(lp.rating) || 0,
                reviews: Number(lp.total_reviews) || 0,
                since: data.created_at || null,
                avatar: data.avatar_url || null,
            });
        });
    }, []);

    // Account & security: the same two actions Settings offers, reached from here.
    const { logout } = useAuth();
    const [dialog, setDialog] = useState(null);   // null | "password" | "delete"
    const [pwd, setPwd] = useState({ current: "", next: "", confirm: "", busy: false, issue: null });
    const [del, setDel] = useState({ password: "", typed: "", busy: false, issue: null, done: false });
    const closeDialog = () => {
        if (pwd.busy || del.busy) return;
        setDialog(null);
        setPwd({ current: "", next: "", confirm: "", busy: false, issue: null });
        setDel({ password: "", typed: "", busy: false, issue: null, done: false });
    };
    const submitPassword = async () => {
        if (!pwd.current || !pwd.next) return setPwd(p => ({ ...p, issue: "Fill in all three fields." }));
        if (pwd.next.length < 8) return setPwd(p => ({ ...p, issue: "The new password needs at least 8 characters." }));
        if (pwd.next !== pwd.confirm) return setPwd(p => ({ ...p, issue: "The new passwords do not match." }));
        setPwd(p => ({ ...p, busy: true, issue: null }));
        const { error } = await changePassword(pwd.current, pwd.next);
        if (error) return setPwd(p => ({ ...p, busy: false, issue: error.message || "Password change failed." }));
        toast.show("✅ Password updated. Please sign in again.", "success");
        await logout();
        window.location.assign("/login");
    };
    // Closure is irreversible: the server re-checks the password and refuses
    // while engagements or payments are live, naming them; that reason is shown.
    const submitDelete = async () => {
        if (!del.password) return setDel(d => ({ ...d, issue: "Enter your password to confirm." }));
        setDel(d => ({ ...d, busy: true, issue: null }));
        const { data, error } = await closeAccount(del.password);
        if (error || !data?.closed) {
            return setDel(d => ({ ...d, busy: false, password: "", issue: error?.message || data?.error || "Could not close the account." }));
        }
        setDel(d => ({ ...d, done: true }));
        await logout();
        window.location.assign("/login");
    };

    const f = (k) => (e) => setForm(p => ({ ...p, [k]: e.target.value }));
    const toggleArea = (a) => setForm(p => ({ ...p, areas: p.areas.includes(a) ? p.areas.filter(x => x !== a) : [...p.areas, a] }));
    const dirty = JSON.stringify(form) !== JSON.stringify(saved);

    const fullName = [form.first_name, form.last_name].filter(Boolean).join(" ");
    const initials = ((form.first_name[0] || "") + (form.last_name[0] || "")).toUpperCase() || "?";
    const kyc = KYC[meta.kyc] || KYC.none;
    const provinceLabel = (PROVINCES.find(([v]) => v === form.province) || [])[1] || "";
    const areas = [...new Set([...PRACTICE_AREAS, ...form.areas])];

    // What a client needs to choose a lawyer; each filled field counts once.
    const checks = useMemo(() => [
        ["Name", fullName, "pf-first"], ["Phone", form.phone, "pf-phone"], ["Practice areas", form.areas.length, "pf-areas"],
        ["Bar number", form.bar_number, "pf-bar"], ["Experience", form.experience, "pf-exp"], ["Fee", form.hourly_rate, "pf-fee"],
        ["Province", form.province, "pf-prov"], ["Office address", form.address, "pf-addr"], ["Bio", form.bio.trim().length >= 40, "pf-bio"],
    ], [form, fullName]);
    const done = checks.filter(([, v]) => Boolean(v)).length;
    const pct = Math.round((done / checks.length) * 100);
    const missing = checks.filter(([, v]) => !v);

    // Take the lawyer to a field: scroll it into view, focus it, flash it.
    const goTo = (id) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        const target = el.matches("input,select,textarea") ? el : el.querySelector("button,input");
        setTimeout(() => target?.focus({ preventScroll: true }), 250);
        el.classList.remove("pf-flash"); void el.offsetWidth; el.classList.add("pf-flash");
    };

    // Checked here so a typo is caught next to the field, not as a server 422.
    // The bar-number rule is the server's own (LawyerProfileUpdate.bar_number).
    const errors = useMemo(() => {
        const e = {};
        if (!form.first_name.trim()) e["pf-first"] = "Your first name is required.";
        const digits = form.phone.replace(/\D/g, "");
        if (form.phone && (digits.length < 10 || digits.length > 13)) e["pf-phone"] = "Enter a full phone number, e.g. +92 300 1234567.";
        if (form.bar_number && (form.bar_number.length < 4 || !/^[A-Za-z0-9][A-Za-z0-9\-/ .]*[A-Za-z0-9]$/.test(form.bar_number)))
            e["pf-bar"] = "Letters, numbers and - / . only, at least 4 characters.";
        const exp = Number(form.experience);
        if (form.experience && (!Number.isInteger(exp) || exp < 0 || exp > 70)) e["pf-exp"] = "Whole years, 0 to 70.";
        const fee = Number(String(form.hourly_rate).replace(/[^0-9]/g, ""));
        if (form.hourly_rate && (!fee || fee > 1000000)) e["pf-fee"] = "Enter an amount up to Rs 1,000,000.";
        return e;
    }, [form]);
    const err = (id) => errors[id] ? <div className="pf-err" role="alert">{errors[id]}</div> : null;
    const bad = (id) => (errors[id] ? " invalid" : "");

    const handleSave = async () => {
        const firstBad = Object.keys(errors)[0];
        if (firstBad) {
            toast.show("⚠️ Fix the highlighted field before saving", "warn");
            goTo(firstBad);
            return;
        }
        setSaving(true);
        const provinceVal = PROVINCES.some(([v]) => v === form.province) ? form.province : null;
        const [r1, r2] = await Promise.all([
            updateMe({ full_name: fullName, phone: form.phone || null, province: provinceVal }),
            updateLawyerProfile({
                bar_number: form.bar_number || null,
                experience_years: form.experience ? parseInt(form.experience, 10) : null,
                hourly_rate: form.hourly_rate ? parseInt(String(form.hourly_rate).replace(/[^0-9]/g, ""), 10) || null : null,
                address: form.address || null,
                availability: form.availability,
                bio: form.bio || null,
                specializations: form.areas.length ? form.areas : null,
            }),
        ]);
        setSaving(false);
        if (r1.error || r2.error) {
            // `.message` is the formatted string; `.detail` is the raw body field,
            // undefined on the error envelope and an array of objects on a 422.
            toast.show("❌ " + ((r1.error || r2.error)?.message || "Save failed"), "danger");
        } else {
            setSaved(form);
            toast.show("✅ Profile updated", "success");
        }
    };

    // Ctrl/Cmd+S saves; leaving with unsaved edits asks first.
    const saveRef = useRef(handleSave);
    saveRef.current = handleSave;
    useEffect(() => {
        const onKey = (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); saveRef.current(); }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, []);
    useEffect(() => {
        if (!dirty) return undefined;
        const warn = (e) => { e.preventDefault(); e.returnValue = ""; };
        window.addEventListener("beforeunload", warn);
        return () => window.removeEventListener("beforeunload", warn);
    }, [dirty]);

    const feeNum = Number(String(form.hourly_rate).replace(/[^0-9]/g, "") || 0);

    const fact = (icon, label, value) => (
        <div className="pf-fact"><Svg d={ICON[icon]} /><span><small>{label}</small>{value || <span className="none">Not added</span>}</span></div>
    );

    return (
        <div data-profile-ws data-drafting-theme data-mode={draftingMode(t)}>
            <style>{`${DRAFTING_TOKENS_CSS}\n${PROFILE_CSS}`}</style>
            <div className="pf-wrap">
                <div className="pf-title">
                    <h1>Profile</h1>
                    <p>How you appear to clients, and the details your verification is checked against.</p>
                </div>

                {/* Who you are, at a glance */}
                <section className="pf-card pf-hero" aria-label="Profile summary">
                    <div className="pf-av">{meta.avatar ? <img src={meta.avatar} alt="" /> : initials}</div>
                    <div className="pf-who">
                        <h2>{fullName || "Your name"}</h2>
                        <div className="role">{form.areas.length ? `${form.areas.slice(0, 3).join(" · ")} lawyer` : "Advocate"}</div>
                        <div className="pf-chips">
                            <span className={`pf-chip ${kyc.tone}`}><i />{kyc.label}</span>
                            <span className={`pf-chip ${form.availability ? "good" : ""}`}><i />{form.availability ? "Accepting new clients" : "Not taking new clients"}</span>
                            {provinceLabel && <span className="pf-chip">{provinceLabel}</span>}
                            {meta.reviews > 0 && <span className="pf-chip"><Svg d={ICON.star} size={12} />{meta.rating.toFixed(1)} · {meta.reviews} review{meta.reviews === 1 ? "" : "s"}</span>}
                        </div>
                    </div>
                    <div className="pf-meter">
                        <Ring pct={pct} />
                        <div>
                            <b>{pct === 100 ? "Profile complete" : "Profile strength"}</b>
                            {missing.length ? (
                                <div className="pf-miss">
                                    {missing.slice(0, 4).map(([label, , id]) => (
                                        <button key={id} type="button" onClick={() => goTo(id)}>+ {label}</button>
                                    ))}
                                    {missing.length > 4 && <small>+{missing.length - 4} more</small>}
                                </div>
                            ) : <small>Clients see everything they need.</small>}
                        </div>
                    </div>
                </section>

                <div className="pf-grid">
                    {/* What clients see */}
                    <aside className="pf-side">
                        <div className="pf-card pf-sec">
                            <h3>Client preview</h3>
                            <p>Your card in a client's lawyer search. It updates as you type.</p>
                            <div className="pf-prev" aria-label="Preview of your public card">
                                <div className="pf-prev-top">
                                    <span className="pf-prev-av">{meta.avatar ? <img src={meta.avatar} alt="" /> : initials}</span>
                                    <span style={{ minWidth: 0 }}>
                                        <b>{fullName || "Your name"}{meta.kyc === "approved" && <span className="pf-tick" title="Verified lawyer">✓</span>}</b>
                                        <small>{[provinceLabel, form.address].filter(Boolean).join(" · ") || "Location not added"}</small>
                                    </span>
                                </div>
                                <div className="pf-prev-areas">
                                    {form.areas.length ? form.areas.slice(0, 3).map(a => <span key={a}>{a}</span>) : <span className="none">No practice areas</span>}
                                    {form.areas.length > 3 && <span>+{form.areas.length - 3}</span>}
                                </div>
                                <div className="pf-prev-stats">
                                    <div><b>{form.experience || "—"}</b><small>Years</small></div>
                                    <div><b>{feeNum ? `Rs ${feeNum.toLocaleString()}` : "—"}</b><small>Per hour</small></div>
                                    <div><b>{meta.reviews ? meta.rating.toFixed(1) : "New"}</b><small>{meta.reviews ? `${meta.reviews} reviews` : "Rating"}</small></div>
                                </div>
                                {form.bio.trim() && <p className="pf-prev-bio">{form.bio.trim()}</p>}
                                <div className={`pf-prev-cta${form.availability ? "" : " off"}`}>{form.availability ? "Book consultation" : "Not taking new clients"}</div>
                            </div>
                            <div className="pf-facts" style={{ marginTop: 14 }}>
                                {fact("mail", "Email", form.email)}
                                {fact("phone", "Phone", form.phone)}
                                {fact("badge", "Bar number", form.bar_number)}
                            </div>
                        </div>
                        <div className={`pf-kyc ${kyc.tone}`}>
                            <b>{kyc.label}</b>
                            {kyc.note}
                            {meta.kyc === "rejected" && meta.reason && <div className="why">{meta.reason}</div>}
                        </div>
                        <div className="pf-card pf-sec" aria-label="Account and security">
                            <h3>Account & security</h3>
                            <p>Sign-in and your account itself.</p>
                            <button type="button" className="pf-act" onClick={() => setDialog("password")}>
                                <Svg d={ICON.lock} />
                                <span><b>Change password</b><small>You'll be signed out everywhere after.</small></span>
                            </button>
                            <button type="button" className="pf-act danger" onClick={() => setDialog("delete")}>
                                <Svg d={ICON.trash} />
                                <span><b>Delete account</b><small>Permanent. Can't be undone.</small></span>
                            </button>
                        </div>
                        {meta.since && (
                            <div className="pf-hint" style={{ padding: "0 4px" }}>
                                Member since {new Date(meta.since).toLocaleDateString("en-GB", { month: "long", year: "numeric" })}
                            </div>
                        )}
                    </aside>

                    {/* Edit */}
                    <div className="pf-form">
                        <section className="pf-card pf-sec" aria-label="Personal details">
                            <h3>Personal details</h3>
                            <p>Your name as enrolled with the Bar Council.</p>
                            <div className="pf-row">
                                <div className="pf-field"><label htmlFor="pf-first">First name</label><input id="pf-first" className={`pf-in${bad("pf-first")}`} value={form.first_name} onChange={f("first_name")} placeholder="First name" />{err("pf-first")}</div>
                                <div className="pf-field"><label htmlFor="pf-last">Last name</label><input id="pf-last" className="pf-in" value={form.last_name} onChange={f("last_name")} placeholder="Last name" /></div>
                            </div>
                            <div className="pf-row" style={{ marginTop: 12 }}>
                                <div className="pf-field">
                                    <label htmlFor="pf-email">Email</label>
                                    <input id="pf-email" className="pf-in" value={form.email} readOnly />
                                    <div className="pf-hint">Your sign-in email can't be changed here.</div>
                                </div>
                                <div className="pf-field"><label htmlFor="pf-phone">Phone</label><input id="pf-phone" className={`pf-in${bad("pf-phone")}`} inputMode="tel" value={form.phone} onChange={f("phone")} placeholder="+92 3XX XXXXXXX" />{err("pf-phone")}</div>
                            </div>
                        </section>

                        <section className="pf-card pf-sec" aria-label="Practice">
                            <h3>Practice</h3>
                            <p>Clients search and filter lawyers by these.</p>
                            <div className="pf-field">
                                <label>Practice areas</label>
                                <div className="pf-areas" id="pf-areas">
                                    {areas.map(a => (
                                        <button key={a} type="button" className="pf-area" aria-pressed={form.areas.includes(a)} onClick={() => toggleArea(a)}>{a}</button>
                                    ))}
                                </div>
                            </div>
                            <div className="pf-row" style={{ marginTop: 14 }}>
                                <div className="pf-field"><label htmlFor="pf-bar">Bar licence / enrolment no.</label><input id="pf-bar" className={`pf-in${bad("pf-bar")}`} value={form.bar_number} onChange={f("bar_number")} placeholder="e.g. PBA-2015-4582" />{err("pf-bar")}</div>
                                <div className="pf-field"><label htmlFor="pf-exp">Experience (years)</label><input id="pf-exp" className={`pf-in${bad("pf-exp")}`} type="number" min="0" max="70" value={form.experience} onChange={f("experience")} placeholder="e.g. 8" />{err("pf-exp")}</div>
                            </div>
                            <div className="pf-row" style={{ marginTop: 12 }}>
                                <div className="pf-field">
                                    <label htmlFor="pf-fee">Consultation fee (per hour)</label>
                                    <div className="pf-pre"><span>Rs</span><input id="pf-fee" className={`pf-in${bad("pf-fee")}`} inputMode="numeric" value={form.hourly_rate} onChange={f("hourly_rate")} placeholder="e.g. 5000" /></div>
                                    {err("pf-fee")}
                                </div>
                                <div className="pf-field">
                                    <label htmlFor="pf-prov">Province</label>
                                    <select id="pf-prov" className="pf-in" value={form.province} onChange={f("province")}>
                                        <option value="">Select province</option>
                                        {PROVINCES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                                    </select>
                                </div>
                            </div>
                            <div className="pf-field" style={{ marginTop: 12 }}>
                                <label htmlFor="pf-addr">Office address</label>
                                <input id="pf-addr" className="pf-in" value={form.address} onChange={f("address")} placeholder="e.g. Chamber 12, Lahore High Court Bar" />
                            </div>
                            <label className="pf-switch" style={{ marginTop: 14 }}>
                                <span><b>Accepting new clients</b><small>When off, clients can still see your profile but not book you.</small></span>
                                <input type="checkbox" checked={form.availability} onChange={e => setForm(p => ({ ...p, availability: e.target.checked }))} aria-label="Accepting new clients" />
                            </label>
                        </section>

                        <section className="pf-card pf-sec" aria-label="About">
                            <h3>About you</h3>
                            <p>A short introduction clients read before booking.</p>
                            <textarea id="pf-bio" className="pf-in" value={form.bio} maxLength={BIO_MAX} onChange={f("bio")} aria-label="Bio"
                                placeholder="e.g. Advocate High Court with 8 years in civil and property litigation in Lahore…" />
                            <div className="pf-hint"><span>Two or three sentences work best.</span><span>{form.bio.length}/{BIO_MAX}</span></div>
                        </section>

                        <div className="pf-save">
                            <span className={Object.keys(errors).length ? "dirty" : dirty ? "dirty" : ""}>
                                {Object.keys(errors).length
                                    ? `${Object.keys(errors).length} field${Object.keys(errors).length === 1 ? " needs" : "s need"} fixing`
                                    : dirty ? "You have unsaved changes" : "All changes saved"}
                                {dirty && <kbd className="pf-kbd">Ctrl S</kbd>}
                            </span>
                            <div style={{ display: "flex", gap: 8 }}>
                                {dirty && <button type="button" className="pf-btn ghost" onClick={() => setForm(saved)} disabled={saving}>Discard</button>}
                                <button type="button" className="pf-btn" onClick={handleSave} disabled={saving}>
                                    <Svg d={ICON.save} /> {saving ? "Saving…" : "Save Changes"}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* On <body>: the page area animates with a transform, which would
                trap a fixed overlay inside it. The wrapper carries the theme. */}
            {dialog && (
                <ModalPortal>
                <div data-profile-ws data-drafting-theme data-mode={draftingMode(t)} style={{ minHeight: 0, padding: 0, background: "none" }}>
                <div className="pf-scrim" onMouseDown={e => { if (e.target === e.currentTarget) closeDialog(); }}>
                    <div className="pf-dialog" role="dialog" aria-modal="true" aria-labelledby="pf-dlg-title">
                        {dialog === "password" ? (
                            <>
                                <h3 id="pf-dlg-title">Change password</h3>
                                <p>At least 8 characters. Every device signed in to this account is signed out after the change.</p>
                                <div className="pf-field"><label htmlFor="pf-cur">Current password</label><input id="pf-cur" className="pf-in" type="password" autoComplete="current-password" value={pwd.current} onChange={e => setPwd(p => ({ ...p, current: e.target.value }))} /></div>
                                <div className="pf-field"><label htmlFor="pf-new">New password</label><input id="pf-new" className="pf-in" type="password" autoComplete="new-password" value={pwd.next} onChange={e => setPwd(p => ({ ...p, next: e.target.value }))} /></div>
                                <div className="pf-field"><label htmlFor="pf-conf">Confirm new password</label><input id="pf-conf" className="pf-in" type="password" autoComplete="new-password" value={pwd.confirm} onChange={e => setPwd(p => ({ ...p, confirm: e.target.value }))} onKeyDown={e => e.key === "Enter" && submitPassword()} /></div>
                                {pwd.issue && <div className="pf-issue" role="alert">{pwd.issue}</div>}
                                <div className="pf-dlg-acts">
                                    <button type="button" className="pf-btn ghost" onClick={closeDialog} disabled={pwd.busy}>Cancel</button>
                                    <button type="button" className="pf-btn" onClick={submitPassword} disabled={pwd.busy}>{pwd.busy ? "Updating…" : "Update password"}</button>
                                </div>
                            </>
                        ) : (
                            <>
                                <h3 id="pf-dlg-title" style={{ color: "#F28B80" }}>Delete your account</h3>
                                <p>Your profile is removed from client search and you can no longer sign in. This can't be undone. Live engagements or payments must be settled first; we'll tell you if any are.</p>
                                <div className="pf-field"><label htmlFor="pf-del-pw">Your password</label><input id="pf-del-pw" className="pf-in" type="password" autoComplete="current-password" value={del.password} onChange={e => setDel(d => ({ ...d, password: e.target.value }))} /></div>
                                <div className="pf-field"><label htmlFor="pf-del-type">Type DELETE to confirm</label><input id="pf-del-type" className="pf-in" value={del.typed} onChange={e => setDel(d => ({ ...d, typed: e.target.value }))} placeholder="DELETE" /></div>
                                {del.issue && <div className="pf-issue" role="alert">{del.issue}</div>}
                                <div className="pf-dlg-acts">
                                    <button type="button" className="pf-btn ghost" onClick={closeDialog} disabled={del.busy}>Cancel</button>
                                    <button type="button" className="pf-btn danger" onClick={submitDelete} disabled={del.busy || del.typed.trim() !== "DELETE"}>
                                        {del.done ? "Account closed. Signing out…" : del.busy ? "Closing…" : "Permanently delete account"}
                                    </button>
                                </div>
                            </>
                        )}
                    </div>
                </div>
                </div>
                </ModalPortal>
            )}
        </div>
    );
}

export { ProfilePage };
