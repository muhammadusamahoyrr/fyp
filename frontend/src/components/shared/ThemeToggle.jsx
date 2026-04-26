// Paste your ThemeToggle.jsx code here
import React from "react";
import { DARK, LIGHT } from "@/components/admin/themes.js";
import Ic from "./Ic.jsx";

const ThemeToggle = ({ isDark, toggle }) => {
    const t = isDark ? DARK : LIGHT;
    return (
        <button onClick={toggle} style={{
            display: "flex", alignItems: "center", gap: 8,
            background: isDark ? t.primaryGlow : t.primaryGlow2,
            border: `2px solid ${isDark ? "rgba(64,240,220,0.35)" : "rgba(44,96,110,0.3)"}`,
            borderRadius: 50, padding: "10px 18px",
            cursor: "pointer", transition: "all 0.4s cubic-bezier(0.4, 0, 0.2, 1)", color: isDark ? t.primary : t.primary,
            fontFamily: "'Inter',sans-serif", fontSize: 13, fontWeight: 600,
            boxShadow: `0 4px 12px ${t.primaryGlow}`
        }}
            onMouseEnter={e => { e.currentTarget.style.transform = "scale(1.05)"; e.currentTarget.style.boxShadow = `0 6px 16px ${t.primaryGlow}`; }}
            onMouseLeave={e => { e.currentTarget.style.transform = "scale(1)"; e.currentTarget.style.boxShadow = `0 4px 12px ${t.primaryGlow}`; }}>
            <span style={{ transition: "transform 0.5s cubic-bezier(0.4, 0, 0.2, 1)", display: "inline-block", transform: isDark ? "rotate(0deg)" : "rotate(180deg)" }}>
                {isDark ? <Ic n="sun" s={13} c={isDark ? DARK.primary : LIGHT.primary} /> : <Ic n="moon" s={13} c={isDark ? DARK.primary : LIGHT.primary} />}
            </span>
            {isDark ? "Light" : "Dark"}
        </button>
    );
};

export default ThemeToggle;
