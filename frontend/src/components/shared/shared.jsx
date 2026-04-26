'use client';
// Paste your shared.jsx code here
import React, { useState } from "react";
import { useT } from "./theme.js";
import Ic from "./Ic.jsx";

export const ConfirmDialog = ({ isOpen, title, message, onConfirm, onCancel, isDanger = false }) => {
    const t = useT();
    if (!isOpen) return null;

    return (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 9998 }}>
            <Card style={{ maxWidth: 420, animation: "scaleIn 0.3s ease" }}>
                <div style={{ marginBottom: 18 }}>
                    <h3 style={{ fontSize: 18, fontWeight: 800, color: t.text, fontFamily: "'Playfair Display',serif" }}>{title}</h3>
                    <p style={{ fontSize: 13, color: t.textMuted, marginTop: 8, lineHeight: 1.6 }}>{message}</p>
                </div>
                <div style={{ display: "flex", gap: 10 }}>
                    <BtnOutline onClick={onCancel} style={{ flex: 1, fontSize: 13, padding: "12px" }}>Cancel</BtnOutline>
                    <button onClick={onConfirm} style={{
                        flex: 1, fontSize: 13, padding: "12px 24px", borderRadius: 50,
                        background: isDanger ? t.danger : t.grad1, color: isDanger ? "#fff" : (t.mode === "dark" ? "#1A2E35" : "#fff"),
                        border: "none", fontWeight: 700, cursor: "pointer", transition: "all 0.3s"
                    }}
                        onMouseEnter={e => e.currentTarget.style.transform = "translateY(-2px)"}
                        onMouseLeave={e => e.currentTarget.style.transform = "translateY(0)"}
                    >{isDanger ? "Delete" : "Confirm"}</button>
                </div>
            </Card>
        </div>
    );
};

export const Tooltip = ({ text, children, position = "top" }) => {
    const [show, setShow] = useState(false);
    const t = useT();

    return (
        <div style={{ position: "relative", display: "inline-block" }} onMouseEnter={() => setShow(true)} onMouseLeave={() => setShow(false)}>
            {children}
            {show && (
                <div style={{
                    position: "absolute", bottom: "calc(100% + 10px)", left: "50%", transform: "translateX(-50%)",
                    background: t.inputBg, border: `1px solid ${t.border}`, color: t.text, padding: "8px 12px",
                    borderRadius: 10, fontSize: 12, whiteSpace: "nowrap", zIndex: 1000, pointerEvents: "none",
                    boxShadow: t.shadowCard, animation: "fadeUp 0.2s ease"
                }}>
                    {text}
                    <div style={{ position: "absolute", bottom: -4, left: "50%", width: 8, height: 8, background: t.inputBg, border: `1px solid ${t.border}`, borderTop: "none", borderLeft: "none", transform: "translateX(-50%) rotate(45deg)" }} />
                </div>
            )}
        </div>
    );
};

export const PasswordStrengthMeter = ({ password }) => {
    const t = useT();

    const getStrength = () => {
        let strength = 0;
        if (/[a-z]/.test(password)) strength++;
        if (/[A-Z]/.test(password)) strength++;
        if (/[0-9]/.test(password)) strength++;
        if (/[^a-zA-Z0-9]/.test(password)) strength++;
        if (password.length >= 12) strength++;
        return Math.min(strength - 1, 4);
    };

    const strength = getStrength();
    const levels = [
        { label: "Very Weak", color: t.danger, pct: 20 },
        { label: "Weak", color: "#FF9C57", pct: 40 },
        { label: "Fair", color: t.warn, pct: 60 },
        { label: "Good", color: "#7ED321", pct: 80 },
        { label: "Strong", color: t.success, pct: 100 },
    ];
    const level = levels[Math.max(0, strength)];

    if (!password) return null;

    return (
        <div style={{ marginTop: 10 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.6px" }}>Password Strength</span>
                <span style={{ fontSize: 12, fontWeight: 700, color: level.color }}>{level.label}</span>
            </div>
            <div style={{ height: 4, background: t.inputBg, borderRadius: 4, overflow: "hidden" }}>
                <div style={{ width: `${level.pct}%`, height: "100%", background: level.color, borderRadius: 4, transition: "all 0.3s" }} />
            </div>
            <div style={{ fontSize: 11, color: t.textMuted, marginTop: 6, lineHeight: 1.5 }}>
                {strength < 2 && "Use uppercase, numbers & symbols"}
                {strength >= 2 && "Great! Your password is secure"}
            </div>
        </div>
    );
};

export const Card = ({ children, style = {}, className = "" }) => {
    const t = useT();
    const [isHover, setIsHover] = useState(false);
    return (
        <div className={className} style={{
            background: t.card,
            border: `1.5px solid ${isHover ? `${t.primary}35` : t.border}`,
            borderRadius: 24,
            padding: 28,
            boxShadow: isHover ? `0 16px 48px -8px ${t.primary}25, ${t.shadowCard}` : t.shadowCard,
            transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
            cursor: "default",
            ...style
        }} onMouseEnter={() => setIsHover(true)} onMouseLeave={() => setIsHover(false)}>{children}</div>
    );
};

export const Badge = ({ children, type = "primary" }) => {
    const t = useT();
    const map = {
        primary: t.badgePrimary, success: t.badgeSuccess, danger: t.badgeDanger,
        warn: t.badgeWarn, info: t.badgeInfo, gray: t.badgeGray
    };
    const b = map[type] || map.primary;
    return (
        <span style={{ display: "inline-flex", alignItems: "center", padding: "5px 14px", borderRadius: 36, fontSize: 11, fontWeight: 600, letterSpacing: "0.6px", background: b.bg, color: b.color, border: `1.5px solid ${b.border}`, transition: "all 0.2s" }}>
            {children}
        </span>
    );
};

export const BtnPrimary = ({ children, onClick, style = {}, disabled }) => {
    const t = useT();
    return (
        <button onClick={onClick} disabled={disabled} style={{
            background: t.grad1, color: t.mode === "dark" ? "#1A2E35" : "#FFFFFF", border: "none",
            borderRadius: 50, padding: "16px 32px", fontWeight: 700, fontSize: 15,
            fontFamily: "'Inter',sans-serif", cursor: disabled ? "not-allowed" : "pointer",
            transition: "all 0.35s cubic-bezier(0.4, 0, 0.2, 1)", letterSpacing: "0.3px",
            opacity: disabled ? 0.5 : 1, boxShadow: disabled ? "none" : `0 6px 20px ${t.primaryGlow}`,
            ...style
        }}
            onMouseEnter={e => { if (!disabled) { e.currentTarget.style.transform = "translateY(-3px)"; e.currentTarget.style.boxShadow = `0 12px 36px ${t.primaryGlow}`; } }}
            onMouseLeave={e => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = `0 6px 20px ${t.primaryGlow}`; }}
        >{children}</button>
    );
};

export const BtnOutline = ({ children, onClick, style = {} }) => {
    const t = useT();
    return (
        <button onClick={onClick} style={{
            background: "transparent", color: t.primary, border: `2px solid ${t.primary}`,
            borderRadius: 50, padding: "14px 28px", fontWeight: 600, fontSize: 15,
            fontFamily: "'Inter',sans-serif", cursor: "pointer", transition: "all 0.35s cubic-bezier(0.4, 0, 0.2, 1)", ...style
        }}
            onMouseEnter={e => { e.currentTarget.style.background = t.primaryGlow; e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = `0 6px 20px ${t.primaryGlow}`; }}
            onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = "none"; }}
        >{children}</button>
    );
};

export const ThemedInput = ({ style = {}, error, helperText, validator, onChange, onBlur, ...props }) => {
    const t = useT();
    const [val, setVal] = useState(props.value || "");
    const [err, setErr] = useState(null);
    const [touched, setTouched] = useState(false);

    const handleChange = (e) => {
        setVal(e.target.value);
        if (validator && touched) {
            setErr(validator(e.target.value));
        }
        onChange?.(e);
    };

    const handleBlur = (e) => {
        setTouched(true);
        if (validator) {
            setErr(validator(e.target.value));
        }
        onBlur?.(e);
    };

    return (
        <div style={{ width: "100%" }}>
            <input {...props} value={val} onChange={handleChange} onBlur={e => {
                e.target.style.borderColor = err ? t.danger : t.border;
                e.target.style.background = err ? `${t.danger}10` : t.inputBg;
                e.target.style.boxShadow = "none";
                handleBlur(e);
            }} style={{
                background: err ? `${t.danger}10` : t.inputBg,
                border: `1.5px solid ${err ? t.danger : error ? t.danger : t.border}`,
                color: t.text, borderRadius: 16, padding: "14px 18px",
                fontFamily: "'Inter',sans-serif", fontSize: 14, width: "100%", outline: "none",
                transition: "all 0.35s cubic-bezier(0.4, 0, 0.2, 1)", ...style
            }}
                onFocus={e => { e.target.style.borderColor = err ? t.danger : t.primary; e.target.style.background = err ? `${t.danger}10` : t.inputFocus; e.target.style.boxShadow = `0 0 0 5px ${err ? t.danger + "20" : t.primaryGlow}`; }}
            />
            {touched && (err || error) && (
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8, fontSize: 12, color: t.danger, animation: "fadeUp 0.3s ease" }}>
                    <div style={{ width: 4, height: 4, background: t.danger, borderRadius: "50%" }} />
                    {err || error}
                </div>
            )}
            {helperText && !err && !error && (
                <div style={{ fontSize: 12, color: t.textMuted, marginTop: 6 }}>{helperText}</div>
            )}
        </div>
    );
};
