'use client';
import React, { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import { useT } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import { useAuth } from "@/context/AuthContext.jsx";
import { updateMe, changePassword, closeAccount, authLogout } from "@/lib/api.js";
import Ic from "./Ic.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput, ConfirmDialog, Tooltip, Badge } from "@/components/shared/shared.jsx";

/* ─────────────────────────────────────────────────────────────
   DESIGN TOKENS — derived from theme but boosted for contrast
───────────────────────────────────────────────────────────── */
const useTokens = () => {
    const t = useT();
    return {
        ...t,
        // Visible card surface — noticeably different from page bg
        cardSurface: t.mode === "dark" ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.03)",
        cardBorder: t.mode === "dark" ? "rgba(255,255,255,0.10)" : "rgba(0,0,0,0.10)",
        // Icon badge — solid tinted pill
        iconBg: t.mode === "dark" ? `${t.primary}28` : `${t.primary}18`,
        iconBorder: t.mode === "dark" ? `${t.primary}45` : `${t.primary}30`,
        // Divider between segments
        divider: t.mode === "dark" ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.08)",
        // Hover lift for stat/contact cells
        hoverBg: t.mode === "dark" ? "rgba(255,255,255,0.07)" : "rgba(0,0,0,0.04)",
    };
};

/* ─────────────────────────────────────────────────────────────
   SUB-COMPONENTS
───────────────────────────────────────────────────────────── */

/** Horizontal ruled section header */
const SectionLabel = ({ children }) => {
    const tk = useTokens();
    return (
        <div style={{
            display: "flex", alignItems: "center", gap: 10,
            marginBottom: 14,
        }}>
            <div style={{ width: 3, height: 14, borderRadius: 2, background: tk.primary, flexShrink: 0 }} />
            <span style={{
                fontSize: 10, letterSpacing: "1.4px", textTransform: "uppercase",
                fontWeight: 800, color: tk.primary,
            }}>{children}</span>
            <div style={{ flex: 1, height: 1, background: tk.divider }} />
        </div>
    );
};

/** Icon badge — always visible regardless of theme */
const IconBadge = ({ icon, size = 16, color, warn }) => {
    const tk = useTokens();
    const c = warn ? tk.warn : (color || tk.primary);
    return (
        <div style={{
            width: 38, height: 38, borderRadius: 11, flexShrink: 0,
            background: warn
                ? (tk.mode === "dark" ? "rgba(255,180,0,0.15)" : "rgba(200,120,0,0.10)")
                : tk.iconBg,
            border: `1px solid ${warn
                ? (tk.mode === "dark" ? "rgba(255,180,0,0.30)" : "rgba(200,120,0,0.25)")
                : tk.iconBorder}`,
            display: "flex", alignItems: "center", justifyContent: "center",
        }}>
            <Ic n={icon} s={size} c={c} />
        </div>
    );
};

/** Visible field tile — solid border + subtle fill */
const FieldTile = ({ label, value, icon }) => {
    const tk = useTokens();
    return (
        <div style={{
            padding: "14px 16px",
            background: tk.cardSurface,
            border: `1px solid ${tk.cardBorder}`,
            borderRadius: 14,
            display: "flex", alignItems: "center", gap: 12,
            transition: "border-color 0.15s, background 0.15s",
        }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = `${tk.primary}50`; e.currentTarget.style.background = tk.hoverBg; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = tk.cardBorder; e.currentTarget.style.background = tk.cardSurface; }}
        >
            <IconBadge icon={icon} size={15} />
            <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 10, color: tk.textMuted, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.6px", marginBottom: 4 }}>{label}</div>
                <div style={{ fontSize: 14, color: tk.text, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{value}</div>
            </div>
        </div>
    );
};

/** Stat cell inside the activity bar */
const StatCell = ({ icon, label, value, sub, warn, last }) => {
    const tk = useTokens();
    return (
        <div style={{
            flex: 1, padding: "14px 18px",
            borderRight: last ? "none" : `1px solid ${tk.divider}`,
            display: "flex", alignItems: "center", gap: 12,
            transition: "background 0.15s",
        }}
            onMouseEnter={e => e.currentTarget.style.background = tk.hoverBg}
            onMouseLeave={e => e.currentTarget.style.background = "transparent"}
        >
            <IconBadge icon={icon} warn={warn} />
            <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 10, color: tk.textMuted, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.5px" }}>{label}</div>
                <div style={{ fontSize: 14, color: warn ? tk.warn : tk.text, fontWeight: 800, marginTop: 2 }}>{value}</div>
                <div style={{ fontSize: 11, color: tk.textMuted, marginTop: 1 }}>{sub}</div>
            </div>
        </div>
    );
};

/** Contact cell inside the contact band */
const ContactCell = ({ icon, label, value, extra, last }) => {
    const tk = useTokens();
    return (
        <div style={{
            flex: 1, padding: "16px 18px",
            borderRight: last ? "none" : `1px solid ${tk.divider}`,
            display: "flex", alignItems: "flex-start", gap: 13,
            transition: "background 0.15s",
        }}
            onMouseEnter={e => e.currentTarget.style.background = tk.hoverBg}
            onMouseLeave={e => e.currentTarget.style.background = "transparent"}
        >
            <IconBadge icon={icon} size={15} />
            <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 10, color: tk.textMuted, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.6px", marginBottom: 5 }}>{label}</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: tk.text }}>{value}</div>
                {extra && (
                    <div
                        style={{ fontSize: 12, color: tk.primary, fontWeight: 600, marginTop: 5, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 4 }}
                        onMouseEnter={e => e.currentTarget.style.textDecoration = "underline"}
                        onMouseLeave={e => e.currentTarget.style.textDecoration = "none"}
                    >
                        <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                        {extra}
                    </div>
                )}
            </div>
        </div>
    );
};

/** Edit input field — supports both controlled (value+onChange) and uncontrolled (defaultValue) */
const EditField = ({ label, value, onChange, icon, type = "text" }) => {
    const tk = useTokens();
    return (
        <div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 7, fontSize: 10, color: tk.textMuted, fontWeight: 700, letterSpacing: "0.6px", textTransform: "uppercase" }}>
                {icon && <Ic n={icon} s={11} c={tk.textMuted} />}
                {label}
            </div>
            {onChange
                ? <ThemedInput value={value} onChange={onChange} type={type} />
                : <ThemedInput defaultValue={value} type={type} />
            }
        </div>
    );
};

/** Security row */
const SecurityRow = ({ icon, label, desc, danger, onClick, children }) => {
    const tk = useTokens();
    return (
        <div style={{
            display: "flex", alignItems: "center", gap: 14, padding: "14px 16px",
            background: tk.cardSurface,
            border: `1px solid ${danger ? `${tk.danger}35` : tk.cardBorder}`,
            borderRadius: 14, transition: "all 0.15s",
        }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = danger ? tk.danger : tk.primary; e.currentTarget.style.background = danger ? `${tk.danger}08` : tk.hoverBg; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = danger ? `${tk.danger}35` : tk.cardBorder; e.currentTarget.style.background = tk.cardSurface; }}
        >
            <div style={{
                width: 40, height: 40, borderRadius: 12, flexShrink: 0,
                background: danger
                    ? (tk.mode === "dark" ? "rgba(255,70,70,0.15)" : "rgba(200,0,0,0.08)")
                    : tk.iconBg,
                border: `1px solid ${danger ? `${tk.danger}35` : tk.iconBorder}`,
                display: "flex", alignItems: "center", justifyContent: "center",
            }}>
                <Ic n={icon} s={17} c={danger ? tk.danger : tk.primary} />
            </div>
            <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: danger ? tk.danger : tk.text, marginBottom: 3 }}>{label}</div>
                <div style={{ fontSize: 12, color: tk.textMuted }}>{desc}</div>
            </div>
            {children || (
                <BtnOutline onClick={onClick} style={{ fontSize: 12, padding: "8px 16px", flexShrink: 0, ...(danger ? { borderColor: tk.danger, color: tk.danger } : {}) }}>
                    {danger ? "Delete" : "Manage"}
                </BtnOutline>
            )}
        </div>
    );
};

/* ─────────────────────────────────────────────────────────────
   HERO BG ICONS
───────────────────────────────────────────────────────────── */
const HeroBgIcons = ({ color }) => (
    <svg viewBox="0 0 520 110" fill="none" xmlns="http://www.w3.org/2000/svg"
        style={{ position: "absolute", right: 0, top: 0, height: "100%", width: "auto", opacity: 0.11, pointerEvents: "none" }}>
        <line x1="260" y1="16" x2="260" y2="96" stroke={color} strokeWidth="2.5" />
        <line x1="200" y1="34" x2="320" y2="34" stroke={color} strokeWidth="2.5" />
        <path d="M200 34 L178 68 L222 68 Z" stroke={color} strokeWidth="2" fill="none" />
        <path d="M320 34 L298 68 L342 68 Z" stroke={color} strokeWidth="2" fill="none" />
        <line x1="235" y1="96" x2="285" y2="96" stroke={color} strokeWidth="2.5" />
        <rect x="375" y="24" width="46" height="20" rx="5" stroke={color} strokeWidth="2" transform="rotate(-35 375 24)" />
        <line x1="394" y1="68" x2="436" y2="98" stroke={color} strokeWidth="3" strokeLinecap="round" />
        <rect x="68" y="36" width="50" height="58" rx="3" stroke={color} strokeWidth="2" />
        <line x1="93" y1="36" x2="93" y2="94" stroke={color} strokeWidth="1.5" />
        <line x1="76" y1="50" x2="91" y2="50" stroke={color} strokeWidth="1.5" />
        <line x1="76" y1="60" x2="91" y2="60" stroke={color} strokeWidth="1.5" />
        <line x1="76" y1="70" x2="91" y2="70" stroke={color} strokeWidth="1.5" />
        <path d="M450 18 L492 27 L492 60 C492 79 471 91 450 96 C429 91 408 79 408 60 L408 27 Z" stroke={color} strokeWidth="2" fill="none" />
        <path d="M436 54 L447 65 L466 43" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="138" y="28" width="46" height="58" rx="4" stroke={color} strokeWidth="2" />
        <line x1="149" y1="44" x2="175" y2="44" stroke={color} strokeWidth="1.5" />
        <line x1="149" y1="53" x2="175" y2="53" stroke={color} strokeWidth="1.5" />
        <line x1="149" y1="62" x2="170" y2="62" stroke={color} strokeWidth="1.5" />
        <line x1="149" y1="71" x2="175" y2="71" stroke={color} strokeWidth="1.5" />
    </svg>
);

const PROVINCE_OPTIONS = [
    { value: "punjab", label: "Punjab", sub: "Lahore · Rawalpindi · Faisalabad", flag: "🌾" },
    { value: "sindh", label: "Sindh", sub: "Karachi · Hyderabad · Sukkur", flag: "🌊" },
    { value: "kpk", label: "KPK", sub: "Peshawar · Abbottabad · Mardan", flag: "⛰️" },
    { value: "balochistan", label: "Balochistan", sub: "Quetta · Gwadar · Turbat", flag: "🏜️" },
    { value: "federal", label: "Federal (ICT)", sub: "Islamabad Capital Territory", flag: "🏛️" },
];

/* ══════════════════════════════════════════════════════════════
   MODULE: PROFILE
══════════════════════════════════════════════════════════════ */
const ModProfile = () => {
    const tk = useTokens();
    const t = useT();
    const toast = useToast();
    const { user, updateUser } = useAuth();
    const [edit, setEdit] = useState(false);
    const [pwdMode, setPwdMode] = useState(false);
    const [delConfirm, setDelConfirm] = useState(false);
    const [delPassword, setDelPassword] = useState("");
    const [closing, setClosing] = useState(false);
    const [twoFAEnabled, setTwoFAEnabled] = useState(false);
    const [activeTab, setActiveTab] = useState("profile");
    const [avatarHover, setAvatarHover] = useState(false);
    const [photoSrc, setPhotoSrc] = useState(null);
    const [saving, setSaving] = useState(false);
    const [editData, setEditData] = useState({ full_name: "", phone: "", province: "" });
    const [pwdData, setPwdData] = useState({ current: "", next: "", confirm: "" });
    const [provinceOpen, setProvinceOpen] = useState(false);
    const [provinceRect, setProvinceRect] = useState(null);
    const [dropUp, setDropUp] = useState(false);
    const provinceButtonRef = useRef(null);
    const provinceDropRef = useRef(null);

    useEffect(() => {
        if (!provinceOpen) return;
        const handler = (e) => {
            if (
                !provinceButtonRef.current?.contains(e.target) &&
                !provinceDropRef.current?.contains(e.target)
            ) setProvinceOpen(false);
        };
        document.addEventListener("mousedown", handler);
        document.addEventListener("touchstart", handler);
        return () => {
            document.removeEventListener("mousedown", handler);
            document.removeEventListener("touchstart", handler);
        };
    }, [provinceOpen]);
    const fileInputRef = useRef(null);

    const displayName = user?.full_name || "Muhammad Usama";
    const displayEmail = user?.email || "musamahoy@gmail.com";
    const displayPhone = user?.phone || "+92 300 0000000";
    const displayAddress = user?.province
        ? `${user.province.charAt(0).toUpperCase() + user.province.slice(1)}, Pakistan`
        : "Rawalpindi, Punjab, PK";
    const initials = displayName.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase() || "MU";

    const handlePhotoChange = (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => { setPhotoSrc(ev.target.result); toast.show("Profile photo updated!", "success"); };
        reader.readAsDataURL(file);
    };

    const startEdit = () => {
        setEditData({
            full_name: displayName,
            phone: user?.phone || "",
            province: user?.province || "",
        });
        setEdit(true);
    };

    const handleSave = async () => {
        setSaving(true);
        const payload = { full_name: editData.full_name, phone: editData.phone };
        if (editData.province) payload.province = editData.province;
        const { error } = await updateMe(payload);
        if (error) {
            toast.show(error.message || "Failed to save profile. Please try again.", "error");
        } else {
            updateUser(payload);
            toast.show("Profile updated successfully!", "success");
            setEdit(false);
        }
        setSaving(false);
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
            toast.show("Password changed successfully!", "success");
            setPwdMode(false);
            setPwdData({ current: "", next: "", confirm: "" });
        }
        setSaving(false);
    };
    // Closure is irreversible, so the password is re-checked server-side. This
    // used to announce "Your account has been deleted" on a two-second timer and
    // call nothing at all — name, email, phone, case and payment records all
    // stayed exactly where they were.
    const handleDeleteConfirm = async () => {
        setDelConfirm(false);
        if (!delPassword.trim()) { toast.show("Enter your password to confirm", "warn"); return; }
        setClosing(true);
        const { data, error } = await closeAccount(delPassword);
        setClosing(false);
        setDelPassword("");
        if (error || !data?.closed) {
            // The server refuses while engagements or payments are live and says
            // which — surface that verbatim rather than a generic failure.
            toast.show(error?.detail || data?.error || "Could not close the account", "danger");
            return;
        }
        toast.show("Account closed. Signing you out…", "info", 4000);
        setTimeout(() => { authLogout(); window.location.href = "/login"; }, 1500);
    };

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <ConfirmDialog isOpen={delConfirm} isDanger title="Close your account?"
                message={"This cannot be undone. Your personal details are erased and you are signed out everywhere. Case, payment and audit records are kept where the law or another party's rights require it. Enter your password below to confirm."}
                onConfirm={handleDeleteConfirm} onCancel={() => { setDelConfirm(false); setDelPassword(""); }}>
                <ThemedInput type="password" value={delPassword} autoComplete="current-password"
                    onChange={e => setDelPassword(e.target.value)} placeholder="Your password" />
            </ConfirmDialog>
            <input ref={fileInputRef} type="file" accept="image/*" style={{ display: "none" }} onChange={handlePhotoChange} />

            {/* ══ HERO CARD ════════════════════════════════════════════ */}
            <Card style={{ padding: 0, overflow: "hidden", border: `1px solid ${tk.cardBorder}` }}>

                {/* Banner */}
                <div style={{
                    height: 108,
                    background: `linear-gradient(120deg, ${t.primary}28 0%, ${t.primaryGlow} 55%, ${t.primary}10 100%)`,
                    position: "relative", overflow: "hidden",
                }}>
                    <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%", opacity: 0.18 }}>
                        <defs>
                            <pattern id="pgrid" x="0" y="0" width="22" height="22" patternUnits="userSpaceOnUse">
                                <circle cx="2" cy="2" r="1" fill={t.primary} />
                            </pattern>
                        </defs>
                        <rect width="100%" height="100%" fill="url(#pgrid)" />
                    </svg>
                    <HeroBgIcons color={t.primary} />
                </div>

                <div style={{ padding: "0 28px 28px" }}>

                    {/* Avatar + name row */}
                    <div style={{ display: "flex", alignItems: "flex-end", gap: 20, marginTop: -46, marginBottom: 22 }}>

                        {/* Circular photo */}
                        <div style={{ position: "relative", flexShrink: 0, cursor: "pointer" }}
                            onMouseEnter={() => setAvatarHover(true)}
                            onMouseLeave={() => setAvatarHover(false)}
                            onClick={() => fileInputRef.current?.click()}
                        >
                            <div style={{
                                width: 92, height: 92, borderRadius: "50%", padding: 3,
                                background: `linear-gradient(145deg, ${t.primary}, ${t.primary}55)`,
                                boxShadow: `0 8px 28px ${t.primary}45`,
                            }}>
                                <div style={{
                                    width: "100%", height: "100%", borderRadius: "50%",
                                    border: `3px solid ${t.card}`,
                                    overflow: "hidden",
                                    background: photoSrc ? "transparent" : t.grad1,
                                    display: "flex", alignItems: "center", justifyContent: "center",
                                    fontSize: 26, fontWeight: 900,
                                    color: t.mode === "dark" ? "#1A2E35" : "#fff",
                                    position: "relative",
                                }}>
                                    {photoSrc
                                        ? <img src={photoSrc} alt="Profile" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                                        : initials
                                    }
                                    <div style={{
                                        position: "absolute", inset: 0, borderRadius: "50%",
                                        background: "rgba(0,0,0,0.52)",
                                        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 3,
                                        opacity: avatarHover ? 1 : 0, transition: "opacity 0.18s",
                                    }}>
                                        <Ic n="edit" s={16} c="#fff" />
                                        <span style={{ fontSize: 9, color: "#fff", fontWeight: 800, letterSpacing: "0.7px" }}>UPLOAD</span>
                                    </div>
                                </div>
                            </div>
                            <div style={{
                                position: "absolute", bottom: 4, right: 4,
                                width: 16, height: 16, borderRadius: "50%",
                                background: t.success, border: `2.5px solid ${t.card}`,
                                boxShadow: `0 0 0 2px ${t.success}35`,
                            }} />
                        </div>

                        {/* Name + meta */}
                        <div style={{ flex: 1, paddingBottom: 6 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                                <h2 style={{ fontSize: 22, fontWeight: 900, color: t.text, margin: 0, fontFamily: "'Playfair Display', serif", letterSpacing: "-0.3px" }}>
                                    {displayName}
                                </h2>
                                <Badge type="primary" style={{ fontSize: 11, fontWeight: 700, padding: "4px 10px" }}>
                                    {user?.role ? user.role.charAt(0).toUpperCase() + user.role.slice(1) : "Client"}
                                </Badge>
                                <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: t.success, fontWeight: 600 }}>
                                    <Ic n="check" s={12} c={t.success} /> Verified
                                </div>
                            </div>
                            <div style={{ fontSize: 12, color: t.textMuted, marginTop: 5 }}>
                                {displayEmail} · Member since {user?.created_at
                                    ? new Date(user.created_at).toLocaleDateString("en-US", { month: "long", year: "numeric" })
                                    : "December 2025"}
                            </div>
                        </div>

                        {/* CTA */}
                        <div style={{ display: "flex", gap: 8, paddingBottom: 6 }}>
                            {!edit ? (
                                <BtnOutline onClick={startEdit} style={{ fontSize: 13, padding: "10px 20px" }}>
                                    <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
                                        <Ic n="edit" s={13} c={t.primary} /> Edit Profile
                                    </span>
                                </BtnOutline>
                            ) : (
                                <>
                                    <BtnOutline onClick={() => setEdit(false)} disabled={saving} style={{ fontSize: 13, padding: "10px 18px" }}>Cancel</BtnOutline>
                                    <BtnPrimary onClick={handleSave} disabled={saving} style={{ fontSize: 13, padding: "10px 20px", opacity: saving ? 0.7 : 1 }}>
                                        <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
                                            <Ic n="check" s={13} c={t.mode === "dark" ? "#1A2E35" : "#fff"} />
                                            {saving ? "Saving…" : "Save Changes"}
                                        </span>
                                    </BtnPrimary>
                                </>
                            )}
                        </div>
                    </div>

                    {/* ── Account Activity Bar ─────────────────────────── */}
                    <div style={{
                        display: "flex", borderRadius: 16,
                        border: `1px solid ${tk.cardBorder}`,
                        background: tk.cardSurface,
                        overflow: "hidden", marginBottom: 24,
                    }}>
                        <StatCell icon="log-in" label="Last Login" value="2 hours ago" sub={'from "Pixel 6"'} />
                        <StatCell icon="monitor" label="Connected Devices" value="3 active" sub="manage sessions" />
                        <StatCell icon="clock" label="Member Since" value="December 2025" sub="3 months ago" />
                        <StatCell icon="shield" label="Security Score" value="Good" sub="2FA not enabled" warn last />
                    </div>

                    {/* ── Tabs ─────────────────────────────────────────── */}
                    <div style={{ display: "flex", borderBottom: `1px solid ${tk.divider}`, marginBottom: 24 }}>
                        {[["profile", "user", "Profile Info"], ["security", "shield", "Security"]].map(([id, icon, label]) => (
                            <button key={id} onClick={() => { setActiveTab(id); setEdit(false); setPwdMode(false); }} style={{
                                display: "flex", alignItems: "center", gap: 7,
                                padding: "10px 20px", fontSize: 13, fontWeight: 600,
                                background: "none", border: "none", cursor: "pointer",
                                color: activeTab === id ? t.primary : t.textMuted,
                                borderBottom: `2px solid ${activeTab === id ? t.primary : "transparent"}`,
                                marginBottom: -1, transition: "all 0.15s",
                                fontFamily: "'Inter', sans-serif",
                            }}>
                                <Ic n={icon} s={14} c={activeTab === id ? t.primary : t.textMuted} />
                                {label}
                            </button>
                        ))}
                    </div>

                    {/* ══ PROFILE INFO TAB ══════════════════════════════ */}
                    {activeTab === "profile" && !edit && (
                        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>

                            {/* Contact band */}
                            <div>
                                <SectionLabel>Contact Information</SectionLabel>
                                <div style={{
                                    display: "flex",
                                    border: `1px solid ${tk.cardBorder}`,
                                    borderRadius: 16,
                                    background: tk.cardSurface,
                                    overflow: "hidden",
                                }}>
                                    <ContactCell icon="mail" label="Primary Email" value={displayEmail} extra="Add Recovery Email" />
                                    <ContactCell icon="phone" label="Phone" value={displayPhone} />
                                    <ContactCell icon="map" label="Location" value={displayAddress} last />
                                </div>
                            </div>

                            {/* Personal details grid */}
                            <div>
                                <SectionLabel>Personal Details</SectionLabel>
                                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
                                    <FieldTile label="First Name" value={displayName.split(" ")[0] || displayName} icon="user" />
                                    <FieldTile label="Last Name" value={displayName.split(" ").slice(1).join(" ") || "—"} icon="user" />
                                    <FieldTile label="Member Since" value={user?.created_at
                                        ? new Date(user.created_at).toLocaleDateString("en-US", { month: "long", year: "numeric" })
                                        : "December 2025"} icon="clock" />
                                    <FieldTile label="Account Type" value={user?.role ? user.role.charAt(0).toUpperCase() + user.role.slice(1) : "Free Client"} icon="briefcase" />
                                </div>
                            </div>
                        </div>
                    )}

                    {/* ══ EDIT MODE ═════════════════════════════════════ */}
                    {activeTab === "profile" && edit && (
                        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
                            <div>
                                <SectionLabel>Contact Information</SectionLabel>
                                <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                                    <div>
                                        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 7, fontSize: 10, color: tk.textMuted, fontWeight: 700, letterSpacing: "0.6px", textTransform: "uppercase" }}>
                                            <Ic n="mail" s={11} c={tk.textMuted} />
                                            Email (cannot be changed)
                                        </div>
                                        <ThemedInput value={displayEmail} disabled type="email" style={{ opacity: 0.55, cursor: "not-allowed" }} />
                                    </div>
                                    <EditField
                                        label="Phone"
                                        value={editData.phone}
                                        onChange={e => setEditData(d => ({ ...d, phone: e.target.value }))}
                                        icon="phone"
                                        type="tel"
                                    />
                                </div>
                            </div>
                            <div>
                                <SectionLabel>Personal Details</SectionLabel>
                                <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                                    <EditField
                                        label="Full Name"
                                        value={editData.full_name}
                                        onChange={e => setEditData(d => ({ ...d, full_name: e.target.value }))}
                                        icon="user"
                                    />
                                    <div style={{ position: "relative" }}>
                                        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 7, fontSize: 10, color: tk.textMuted, fontWeight: 700, letterSpacing: "0.6px", textTransform: "uppercase" }}>
                                            <Ic n="map" s={11} c={tk.textMuted} />
                                            Province
                                        </div>

                                        {/* Trigger button */}
                                        <button
                                            ref={provinceButtonRef}
                                            type="button"
                                            onClick={() => {
                                                if (provinceButtonRef.current) {
                                                    const r = provinceButtonRef.current.getBoundingClientRect();
                                                    const dropdownHeight = 280;
                                                    const dropdownWidth = Math.max(r.width, 280);
                                                    const spaceBelow = window.innerHeight - r.bottom;
                                                    const spaceRight = window.innerWidth - r.right;
                                                    const shouldDropUp = spaceBelow < dropdownHeight + 20;
                                                    const shouldAlignRight = spaceRight < dropdownWidth + 20;

                                                    setDropUp(shouldDropUp);
                                                    setProvinceRect({
                                                        top: shouldDropUp ? r.top - dropdownHeight - 6 : r.bottom + 6,
                                                        left: shouldAlignRight ? r.right - dropdownWidth : r.left,
                                                        width: dropdownWidth,
                                                    });
                                                }
                                                setProvinceOpen(v => !v);
                                            }}
                                            style={{
                                                width: "100%", padding: "10px 14px", borderRadius: 8,
                                                border: `1.5px solid ${provinceOpen ? tk.primary : tk.cardBorder}`,
                                                background: tk.inputBg, color: editData.province ? tk.text : tk.textMuted,
                                                fontSize: 13, outline: "none", cursor: "pointer", fontFamily: "inherit",
                                                display: "flex", alignItems: "center", gap: 8,
                                                transition: "border-color 0.15s, box-shadow 0.15s",
                                                boxShadow: provinceOpen ? `0 0 0 3px ${tk.primary}20` : "none",
                                            }}
                                        >
                                            {editData.province ? (
                                                <>
                                                    <span style={{ fontSize: 16, lineHeight: 1 }}>
                                                        {PROVINCE_OPTIONS.find(p => p.value === editData.province)?.flag}
                                                    </span>
                                                    <span style={{ flex: 1, fontWeight: 600, textAlign: "left" }}>
                                                        {PROVINCE_OPTIONS.find(p => p.value === editData.province)?.label}
                                                    </span>
                                                </>
                                            ) : (
                                                <span style={{ flex: 1, textAlign: "left" }}>— Select province —</span>
                                            )}
                                            <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
                                                style={{ flexShrink: 0, transition: "transform 0.2s", transform: provinceOpen ? "rotate(180deg)" : "rotate(0deg)" }}>
                                                <polyline points="6 9 12 15 18 9" />
                                            </svg>
                                        </button>

                                        {/* Portal — renders into document.body, bypasses all overflow:hidden and CSS transforms */}
                                        {provinceOpen && provinceRect && createPortal(
                                            <>
                                                <style>{`
                                                    @keyframes fadeInDown {
                                                        from { opacity: 0; transform: translateY(-4px); }
                                                        to { opacity: 1; transform: translateY(0); }
                                                    }
                                                    @keyframes fadeInUp {
                                                        from { opacity: 0; transform: translateY(4px); }
                                                        to { opacity: 1; transform: translateY(0); }
                                                    }
                                                `}</style>
                                                <div
                                                    ref={provinceDropRef}
                                                    style={{
                                                        position: "fixed",
                                                        top: provinceRect.top,
                                                        left: provinceRect.left,
                                                        width: provinceRect.width,
                                                        maxHeight: 320,
                                                        zIndex: 9999,
                                                        background: tk.card, border: `1.5px solid ${tk.primary}40`, borderRadius: 12,
                                                        boxShadow: `0 12px 40px rgba(0,0,0,0.22)`, overflow: "hidden",
                                                        overflowY: "auto",
                                                        animation: dropUp ? "fadeInUp 0.15s ease-out" : "fadeInDown 0.15s ease-out",
                                                    }}>
                                                    {PROVINCE_OPTIONS.map((p, i) => {
                                                        const selected = editData.province === p.value;
                                                        return (
                                                            <div
                                                                key={p.value}
                                                                onClick={() => { setEditData(d => ({ ...d, province: p.value })); setProvinceOpen(false); }}
                                                                style={{
                                                                    display: "flex", alignItems: "center", gap: 12,
                                                                    padding: "11px 14px", cursor: "pointer",
                                                                    borderBottom: i < PROVINCE_OPTIONS.length - 1 ? `1px solid ${tk.divider}` : "none",
                                                                    background: selected ? `${tk.primary}14` : "transparent",
                                                                    transition: "background 0.12s",
                                                                }}
                                                                onMouseEnter={e => { if (!selected) e.currentTarget.style.background = tk.hoverBg; }}
                                                                onMouseLeave={e => { if (!selected) e.currentTarget.style.background = selected ? `${tk.primary}14` : "transparent"; }}
                                                            >
                                                                <span style={{ fontSize: 20, lineHeight: 1, flexShrink: 0 }}>{p.flag}</span>
                                                                <div style={{ flex: 1, minWidth: 0 }}>
                                                                    <div style={{ fontSize: 13, fontWeight: 700, color: selected ? tk.primary : tk.text }}>{p.label}</div>
                                                                    <div style={{ fontSize: 11, color: tk.textMuted, marginTop: 1 }}>{p.sub}</div>
                                                                </div>
                                                                {selected && (
                                                                    <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke={tk.primary} strokeWidth="2.5">
                                                                        <polyline points="20 6 9 17 4 12" />
                                                                    </svg>
                                                                )}
                                                            </div>
                                                        );
                                                    })}
                                                </div>
                                            </>,
                                            document.body
                                        )}
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* ══ SECURITY TAB ══════════════════════════════════ */}
                    {activeTab === "security" && (
                        pwdMode ? (
                            <div>
                                <SectionLabel>Change Password</SectionLabel>
                                <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 420, marginBottom: 16 }}>
                                    <EditField label="Current Password" value={pwdData.current} onChange={e => setPwdData(d => ({ ...d, current: e.target.value }))} icon="lock" type="password" />
                                    <EditField label="New Password" value={pwdData.next} onChange={e => setPwdData(d => ({ ...d, next: e.target.value }))} icon="lock" type="password" />
                                    <EditField label="Confirm New Password" value={pwdData.confirm} onChange={e => setPwdData(d => ({ ...d, confirm: e.target.value }))} icon="lock" type="password" />
                                </div>
                                <div style={{ display: "flex", gap: 10 }}>
                                    <BtnPrimary onClick={handlePasswordUpdate} disabled={saving} style={{ fontSize: 13, padding: "12px 22px", opacity: saving ? 0.7 : 1 }}>
                                        <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
                                            <Ic n="check" s={13} c={t.mode === "dark" ? "#1A2E35" : "#fff"} /> {saving ? "Updating…" : "Update Password"}
                                        </span>
                                    </BtnPrimary>
                                    <BtnOutline onClick={() => { setPwdMode(false); setPwdData({ current: "", next: "", confirm: "" }); }} disabled={saving} style={{ fontSize: 13, padding: "12px 22px" }}>Cancel</BtnOutline>
                                </div>
                            </div>
                        ) : (
                            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                                <SectionLabel>Account Security</SectionLabel>
                                <SecurityRow icon="lock" label="Password" desc="Last changed: December 2025 · Use a strong, unique password" onClick={() => setPwdMode(true)} />
                                <SecurityRow icon="shield" label="Two-Factor Authentication" desc={twoFAEnabled ? "2FA is active — your account is extra secure" : "Add a second layer of protection to your account"}>
                                    <button onClick={() => toast.show("Two-factor authentication is not available yet — we will not pretend it is protecting your account.", "info", 5000)} style={{
                                        padding: "8px 18px", borderRadius: 10, fontSize: 12, fontWeight: 700,
                                        border: `1.5px solid ${twoFAEnabled ? t.success : t.primary}`,
                                        background: twoFAEnabled
                                            ? (t.mode === "dark" ? "rgba(0,200,100,0.14)" : "rgba(0,160,80,0.09)")
                                            : t.primaryGlow,
                                        color: twoFAEnabled ? t.success : t.primary,
                                        cursor: "pointer", transition: "all 0.15s", flexShrink: 0,
                                        fontFamily: "'Inter', sans-serif",
                                    }}>
                                        {"Not available"}
                                    </button>
                                </SecurityRow>
                                <SecurityRow icon="monitor" label="Active Sessions" desc="Session management is not available yet" onClick={() => toast.show("Session management coming soon", "info")} />
                                <div style={{ marginTop: 8 }}>
                                    <SectionLabel>Danger Zone</SectionLabel>
                                    <SecurityRow icon="trash" label="Delete Account" desc="Permanently delete your account and all associated data" danger onClick={() => setDelConfirm(true)} />
                                </div>
                            </div>
                        )
                    )}

                </div>
            </Card>
        </div>
    );
};

export default ModProfile;