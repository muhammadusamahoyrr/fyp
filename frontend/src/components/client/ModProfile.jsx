'use client';
// Paste your ModProfile.jsx code here
import React, { useState, useRef } from "react";
import { useT } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
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

/** Edit input field */
const EditField = ({ label, value, icon, type = "text" }) => {
    const tk = useTokens();
    return (
        <div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 7, fontSize: 10, color: tk.textMuted, fontWeight: 700, letterSpacing: "0.6px", textTransform: "uppercase" }}>
                {icon && <Ic n={icon} s={11} c={tk.textMuted} />}
                {label}
            </div>
            <ThemedInput defaultValue={value} type={type} />
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

/* ══════════════════════════════════════════════════════════════
   MODULE: PROFILE
══════════════════════════════════════════════════════════════ */
const ModProfile = () => {
    const tk = useTokens();
    const t = useT();
    const toast = useToast();
    const [edit, setEdit] = useState(false);
    const [pwdMode, setPwdMode] = useState(false);
    const [delConfirm, setDelConfirm] = useState(false);
    const [twoFAEnabled, setTwoFAEnabled] = useState(false);
    const [activeTab, setActiveTab] = useState("profile");
    const [avatarHover, setAvatarHover] = useState(false);
    const [photoSrc, setPhotoSrc] = useState(null);
    const fileInputRef = useRef(null);

    const handlePhotoChange = (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => { setPhotoSrc(ev.target.result); toast.show("Profile photo updated!", "success"); };
        reader.readAsDataURL(file);
    };

    const handleSave = () => { setEdit(false); toast.show("Profile updated successfully!", "success"); };
    const handlePasswordUpdate = () => { setPwdMode(false); toast.show("Password changed successfully!", "success"); };
    const handleDeleteConfirm = () => {
        setDelConfirm(false);
        toast.show("Account deletion in progress...", "warn");
        setTimeout(() => toast.show("Your account has been deleted", "danger"), 2000);
    };
    const handle2FA = () => {
        setTwoFAEnabled(v => !v);
        toast.show(twoFAEnabled ? "Two-factor authentication disabled" : "Two-factor authentication enabled!", "success");
    };

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <ConfirmDialog isOpen={delConfirm} isDanger title="Delete Account?"
                message="This action cannot be undone. All your data will be permanently deleted. Are you absolutely sure?"
                onConfirm={handleDeleteConfirm} onCancel={() => setDelConfirm(false)} />
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
                                        : "MU"
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
                                    Muhammad Usama
                                </h2>
                                <Badge type="primary" style={{ fontSize: 11, fontWeight: 700, padding: "4px 10px" }}>Client</Badge>
                                <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: t.success, fontWeight: 600 }}>
                                    <Ic n="check" s={12} c={t.success} /> Verified
                                </div>
                            </div>
                            <div style={{ fontSize: 12, color: t.textMuted, marginTop: 5 }}>
                                musamahoy@gmail.com · Member since December 2025
                            </div>
                        </div>

                        {/* CTA */}
                        <div style={{ display: "flex", gap: 8, paddingBottom: 6 }}>
                            {!edit ? (
                                <BtnOutline onClick={() => setEdit(true)} style={{ fontSize: 13, padding: "10px 20px" }}>
                                    <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
                                        <Ic n="edit" s={13} c={t.primary} /> Edit Profile
                                    </span>
                                </BtnOutline>
                            ) : (
                                <>
                                    <BtnOutline onClick={() => setEdit(false)} style={{ fontSize: 13, padding: "10px 18px" }}>Cancel</BtnOutline>
                                    <BtnPrimary onClick={handleSave} style={{ fontSize: 13, padding: "10px 20px" }}>
                                        <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
                                            <Ic n="check" s={13} c={t.mode === "dark" ? "#1A2E35" : "#fff"} /> Save Changes
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
                                    <ContactCell icon="mail" label="Primary Email" value="musamahoy@gmail.com" extra="Add Recovery Email" />
                                    <ContactCell icon="phone" label="Phone" value="+92 300 0000000" />
                                    <ContactCell icon="map" label="Location" value="Rawalpindi, Punjab, PK" last />
                                </div>
                            </div>

                            {/* Personal details grid */}
                            <div>
                                <SectionLabel>Personal Details</SectionLabel>
                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 12 }}>
                                    <FieldTile label="First Name" value="Muhammad" icon="user" />
                                    <FieldTile label="Last Name" value="Usama" icon="user" />
                                    <FieldTile label="Member Since" value="December 2025" icon="clock" />
                                    <FieldTile label="Account Type" value="Free Client" icon="briefcase" />
                                </div>
                            </div>
                        </div>
                    )}

                    {/* ══ EDIT MODE ═════════════════════════════════════ */}
                    {activeTab === "profile" && edit && (
                        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
                            <div>
                                <SectionLabel>Contact Information</SectionLabel>
                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                                    <EditField label="Email" value="musamahoy@gmail.com" icon="mail" type="email" />
                                    <EditField label="Phone" value="+92 300 0000000" icon="phone" type="tel" />
                                </div>
                            </div>
                            <div>
                                <SectionLabel>Personal Details</SectionLabel>
                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                                    <EditField label="First Name" value="Muhammad" icon="user" />
                                    <EditField label="Last Name" value="Usama" icon="user" />
                                    <EditField label="Address" value="Rawalpindi, Punjab, PK" icon="map" />
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
                                    <EditField label="Current Password" value="" icon="lock" type="password" />
                                    <EditField label="New Password" value="" icon="lock" type="password" />
                                    <EditField label="Confirm New Password" value="" icon="lock" type="password" />
                                </div>
                                <div style={{ display: "flex", gap: 10 }}>
                                    <BtnPrimary onClick={handlePasswordUpdate} style={{ fontSize: 13, padding: "12px 22px" }}>
                                        <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
                                            <Ic n="check" s={13} c={t.mode === "dark" ? "#1A2E35" : "#fff"} /> Update Password
                                        </span>
                                    </BtnPrimary>
                                    <BtnOutline onClick={() => setPwdMode(false)} style={{ fontSize: 13, padding: "12px 22px" }}>Cancel</BtnOutline>
                                </div>
                            </div>
                        ) : (
                            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                                <SectionLabel>Account Security</SectionLabel>
                                <SecurityRow icon="lock" label="Password" desc="Last changed: December 2025 · Use a strong, unique password" onClick={() => setPwdMode(true)} />
                                <SecurityRow icon="shield" label="Two-Factor Authentication" desc={twoFAEnabled ? "2FA is active — your account is extra secure" : "Add a second layer of protection to your account"}>
                                    <button onClick={handle2FA} style={{
                                        padding: "8px 18px", borderRadius: 10, fontSize: 12, fontWeight: 700,
                                        border: `1.5px solid ${twoFAEnabled ? t.success : t.primary}`,
                                        background: twoFAEnabled
                                            ? (t.mode === "dark" ? "rgba(0,200,100,0.14)" : "rgba(0,160,80,0.09)")
                                            : t.primaryGlow,
                                        color: twoFAEnabled ? t.success : t.primary,
                                        cursor: "pointer", transition: "all 0.15s", flexShrink: 0,
                                        fontFamily: "'Inter', sans-serif",
                                    }}>
                                        {twoFAEnabled ? "Disable" : "Enable"}
                                    </button>
                                </SecurityRow>
                                <SecurityRow icon="monitor" label="Active Sessions" desc="3 devices connected · Manage or revoke access" onClick={() => toast.show("Session management coming soon", "info")} />
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