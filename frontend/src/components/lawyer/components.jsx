'use client';
// Lawyer shared components — paste your code here
import { useState } from "react";
import { useTheme } from "./theme.js";
import { Icon, I } from "./icons.jsx";

// ============================================================
// BASE COMPONENTS
// ============================================================
function Card({ children, style = {}, className = "", onClick, hover = true }) {
    const { t } = useTheme();
    const [hov, setHov] = useState(false);
    return (
        <div onClick={onClick} onMouseEnter={() => hover && setHov(true)} onMouseLeave={() => setHov(false)}
            className={className}
            style={{
                background: t.card, border: `1px solid ${hov && hover ? t.borderHi : t.border}`, borderRadius: 12,
                boxShadow: hov && hover ? t.shadowHover : t.shadowCard, transition: "all .2s ease",
                cursor: onClick ? "pointer" : undefined, ...style
            }}>
            {children}
        </div>
    );
}

function Btn({ children, variant = "primary", size = "md", onClick, style = {}, disabled = false, full = false }) {
    const { t } = useTheme();
    const [hov, setHov] = useState(false);
    const vs = {
        primary: { bg: hov ? t.primaryDim : t.primary, color: t.mode === "dark" ? "#111B1F" : "#fff", border: "none", box: hov ? `0 4px 16px ${t.primaryGlow}` : "none" },
        secondary: { bg: hov ? t.cardHi : t.card, color: t.text, border: `1px solid ${t.border}`, box: "none" },
        ghost: { bg: hov ? t.cardHi : "transparent", color: t.textMuted, border: "none", box: "none" },
        danger: { bg: hov ? t.danger : "transparent", color: hov ? "#fff" : t.danger, border: `1px solid ${t.danger}`, box: "none" },
        accent: { bg: hov ? t.primaryGlow : "transparent", color: t.primary, border: `1px solid ${t.primary}`, box: "none" },
        success: { bg: hov ? `${t.success}cc` : t.success, color: "#fff", border: "none", box: "none" },
        warn: { bg: hov ? `${t.warn}cc` : t.warn, color: "#111", border: "none", box: "none" },
    };
    const ss = { sm: { p: "6px 13px", fs: 13 }, md: { p: "9px 17px", fs: 14 }, lg: { p: "12px 24px", fs: 15 } };
    const v = vs[variant] || vs.primary, s = ss[size] || ss.md;
    return (
        <button disabled={disabled} onClick={onClick} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
            style={{
                display: "inline-flex", alignItems: "center", gap: 7, justifyContent: "center", borderRadius: 9,
                fontWeight: 600, transition: "all .18s ease", width: full ? "100%" : undefined,
                letterSpacing: "0.01em",
                opacity: disabled ? .45 : 1, cursor: disabled ? "not-allowed" : "pointer",
                background: v.bg, color: v.color, border: v.border || "none", boxShadow: v.box,
                padding: s.p, fontSize: s.fs, ...style
            }}>
            {children}
        </button>
    );
}

function Input({ value, onChange, placeholder, type = "text", style = {}, prefix, suffix, defaultValue, id, rows, onKeyDown, ...rest }) {
    const { t } = useTheme();
    const [focused, setFocused] = useState(false);
    const isTA = type === "textarea"; const Tag = isTA ? "textarea" : "input";
    return (
        <div style={{ position: "relative", width: "100%" }}>
            {prefix && <div style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: t.textMuted, display: "flex", pointerEvents: "none" }}>{prefix}</div>}
            <Tag id={id} type={isTA ? undefined : type} value={value} onChange={onChange} placeholder={placeholder}
                defaultValue={defaultValue} rows={rows} onKeyDown={onKeyDown}
                onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} {...rest}
                style={{
                    width: "100%", border: `1px solid ${focused ? t.primary : t.border}`, borderRadius: 9,
                    background: focused ? t.inputFocus : t.inputBg, color: t.text, fontSize: 14, outline: "none",
                    transition: "all .18s ease", padding: prefix ? "9px 12px 9px 36px" : "9px 14px",
                    paddingRight: suffix ? 38 : 14, boxShadow: focused ? `0 0 0 3px ${t.primaryGlow}` : "none",
                    ...(isTA ? { resize: "vertical", minHeight: 88, lineHeight: 1.6 } : { height: 40 }), ...style
                }} />
            {suffix && <div style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", color: t.textMuted, cursor: "pointer" }}>{suffix}</div>}
        </div>
    );
}

function Sel({ value, onChange, children, style = {} }) {
    const { t } = useTheme();
    const [f, setF] = useState(false);
    return (
        <div style={{ position: "relative", display: "inline-flex", alignItems: "center", ...style }}>
            <select value={value} onChange={onChange} onFocus={() => setF(true)} onBlur={() => setF(false)}
                style={{
                    height: 40, border: `1px solid ${f ? t.primary : t.border}`, borderRadius: 9,
                    background: t.inputBg, color: t.text, fontSize: 14, padding: "0 32px 0 14px",
                    outline: "none", cursor: "pointer", appearance: "none", width: "100%",
                    boxShadow: f ? `0 0 0 3px ${t.primaryGlow}` : "none", transition: "all .18s"
                }}>
                {children}
            </select>
            <div style={{ position: "absolute", right: 11, pointerEvents: "none", color: t.textMuted }}>
                <Icon d={I.chevronDown} size={14} />
            </div>
        </div>
    );
}

function Label({ children, htmlFor }) {
    const { t } = useTheme();
    return <label htmlFor={htmlFor} style={{ fontSize: 12, fontWeight: 700, color: t.textMuted, display: "block", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.06em" }}>{children}</label>;
}

function Badge({ children, type = "gray", style = {} }) {
    const { t } = useTheme();
    const map = { primary: t.badgePrimary, success: t.badgeSuccess, danger: t.badgeDanger, warn: t.badgeWarn, info: t.badgeInfo, gray: t.badgeGray };
    const s = map[type] || t.badgeGray;
    return <span style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 10px", borderRadius: 100, background: s.bg, color: s.color, border: `1px solid ${s.border}`, fontSize: 12, fontWeight: 600, whiteSpace: "nowrap", letterSpacing: "0.01em", ...style }}>{children}</span>;
}

function Divider({ style = {} }) {
    const { t } = useTheme();
    return <div style={{ height: 1, background: t.border, margin: "12px 0", ...style }} />;
}

function Pills({ tabs, active, onChange }) {
    const { t } = useTheme();
    return (
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {tabs.map(tb => (
                <button key={tb} onClick={() => onChange(tb)}
                    style={{
                        padding: "5px 12px", borderRadius: 20, fontSize: 12, fontWeight: 500,
                        border: `1px solid ${active === tb ? t.primary : t.border}`,
                        background: active === tb ? t.primaryGlow : "transparent",
                        color: active === tb ? t.primary : t.textMuted, cursor: "pointer", transition: "all .15s ease", whiteSpace: "nowrap"
                    }}>
                    {tb}
                </button>
            ))}
        </div>
    );
}
export { Card, Btn, Input, Sel, Label, Badge, Divider, Pills };
