'use client';
/* Small UI primitives (buttons, cards, pills, labels, icons, fonts, layout
 * helpers) of the CLIENT screens. Since 2026-10-08 the lawyer side has its own
 * copy (components/lawyer/primitives.jsx), so a change here reaches client
 * screens only, and a lawyer redesign never reaches them. Nothing here is a
 * screen, reads data or holds one role's palette: the client Documents
 * palette (MOCKUP_DARK / docsTheme) stays in components/client/documents/ui.jsx.
 *
 * Moved from components/client/documents/ui.jsx, which re-exports it.
 *
 * Every colour comes from the app theme (`useT`), so these screens follow the
 * light/dark toggle like the rest of the dashboard. The one exception is the
 * document "paper", which is white in both themes because it stands for the
 * printed page. */
import React from "react";
import { createPortal } from "react-dom";
import { useT } from "./theme.js";

// The mockup's typefaces (loaded in app/globals.css).
export const SERIF = "'Fraunces', Georgia, serif";
export const PAPER_FONT = "'Source Serif 4', Georgia, 'Times New Roman', serif";
export const MONO = "'JetBrains Mono', ui-monospace, monospace";

/* Popups render into <body>, not where they are declared.
 *
 * The dashboard animates its content in with `transform` (`.aFadeUp`), and a
 * transformed ancestor becomes the containing block for `position: fixed`. So a
 * "full-screen" overlay declared inside the page was pinned to the scrolled
 * content area instead: it opened far down the page and could not cover the
 * sidebar. A portal takes it out of that ancestor. React context still flows
 * through a portal, so the theme and toasts keep working. */
export function ModalPortal({ children }) {
    if (typeof document === "undefined" || !document.body) return null;
    return createPortal(children, document.body);
}

export const BACKDROP = {
    position: "fixed", inset: 0, zIndex: 1000, background: "rgba(4,14,17,.62)",
    backdropFilter: "blur(6px)", WebkitBackdropFilter: "blur(6px)", boxSizing: "border-box",
};

export const onPrimary = t => (t.mode === "dark" ? "#0b2a2d" : "#ffffff");

/* Workspace layout: columns side by side that each scroll on their own on a
 * desktop, and one stacked, page-scrolling column on a phone.
 *
 * NEVER `flex-wrap: wrap` for these rows. A wrapping flex container sizes its
 * line to the CONTENT, not to the screen, so the row grew as tall as the
 * longest column, the inner `overflow: auto` never had anything to scroll, and
 * the parent's `overflow: hidden` clipped the rest — a page you could not
 * scroll at all. */
export function splitLayout(isMobile) {
    return {
        root: isMobile
            ? { flex: 1, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", paddingTop: 56 }
            : { flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" },
        row: isMobile
            ? { display: "flex", flexDirection: "column" }
            : { flex: 1, minHeight: 0, display: "flex" },
        col: desktopFlex => (isMobile
            ? { flex: "none", width: "100%", minWidth: 0 }
            : { flex: desktopFlex, minWidth: 0, minHeight: 0 }),
    };
}

/* Severity colours used by risk pills and highlights. Fixed rather than themed:
 * they carry meaning (high / medium / low) and must read the same everywhere. */
export const SEVERITY = {
    high: { bg: "#4a2226", fg: "#f5a3a8", paper: "#fde2e2", line: "#d9534f" },
    medium: { bg: "#4a3a1c", fg: "#f7cf7d", paper: "#fdf0cf", line: "#e0a82e" },
    low: { bg: "#1d4a36", fg: "#8ff0b5", paper: "#e3f6ec", line: "#2e9d62" },
    info: { bg: "#1d3f5a", fg: "#9fd0f5", paper: "#e6f4ff", line: "#5aa9e6" },
    muted: { bg: "#26434b", fg: "#cfe3e6", paper: "#eef2f3", line: "#8aa1a6" },
};

export function Btn({ kind = "ghost", children, style, ...rest }) {
    const t = useT();
    const base = {
        display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8,
        minHeight: 42, padding: "0 16px", borderRadius: 11, fontSize: 13.5, fontWeight: 600,
        cursor: rest.disabled ? "not-allowed" : "pointer", boxSizing: "border-box",
        fontFamily: "'Inter', sans-serif", textDecoration: "none", whiteSpace: "nowrap",
        opacity: rest.disabled ? 0.55 : 1,
    };
    const kinds = {
        primary: { background: t.primary, color: onPrimary(t), border: "none" },
        ghost: { background: "transparent", color: t.textDim || t.text, border: `1px solid ${t.ghostBorder || t.border}` },
        quiet: { background: "transparent", color: t.textMuted, border: "1px solid transparent" },
        danger: { background: "transparent", color: t.danger, border: `1px solid ${t.danger}66` },
    };
    const Tag = rest.href ? "a" : "button";
    return (
        <Tag type={Tag === "button" ? "button" : undefined} {...rest}
            style={{ ...base, ...kinds[kind], ...style }}>{children}</Tag>
    );
}

export function IconBtn({ label, children, active, style, ...rest }) {
    const t = useT();
    return (
        <button type="button" aria-label={label} title={label} {...rest}
            style={{
                width: 38, height: 38, borderRadius: 10, flexShrink: 0,
                border: `1px solid ${active ? t.primary : (t.ghostBorder || t.border)}`,
                background: active ? t.primaryGlow2 : "transparent", color: active ? t.primary : (t.textDim || t.text),
                display: "inline-flex", alignItems: "center", justifyContent: "center", cursor: "pointer",
                ...style,
            }}>{children}</button>
    );
}

export function Chip({ active, children, style, ...rest }) {
    const t = useT();
    return (
        <button type="button" aria-pressed={active} {...rest}
            style={{
                display: "inline-flex", alignItems: "center", gap: 6, minHeight: 34, padding: "0 12px",
                borderRadius: 999, fontSize: 13, cursor: "pointer", fontFamily: "'Inter', sans-serif",
                border: `1px solid ${active ? t.primary : (t.chipBorder || t.border)}`,
                background: active ? t.primaryGlow2 : (t.chipBg || t.inputBg),
                color: active ? t.primary : (t.textDim || t.text), fontWeight: active ? 600 : 500,
                ...style,
            }}>{children}</button>
    );
}

export function Pill({ tone = "muted", children, style }) {
    const c = SEVERITY[tone] || SEVERITY.muted;
    return (
        <span style={{
            display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11.5, fontWeight: 600,
            padding: "3px 10px", borderRadius: 999, background: c.bg, color: c.fg, whiteSpace: "nowrap",
            ...style,
        }}>{children}</span>
    );
}

export function Label({ children, style }) {
    const t = useT();
    return (
        <div style={{ fontSize: 11.5, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: t.label || t.primary, ...style }}>
            {children}
        </div>
    );
}

export function Card({ children, style, ...rest }) {
    const t = useT();
    return (
        <div {...rest} style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 16, ...style }}>
            {children}
        </div>
    );
}

export function fieldStyle(t, extra) {
    return {
        width: "100%", boxSizing: "border-box", background: t.inputBg, border: `1px solid ${t.inputBorder || t.border}`,
        borderRadius: 10, color: t.text, fontFamily: "'Inter', sans-serif", fontSize: 14,
        padding: "10px 12px", outline: "none", ...extra,
    };
}

/* A visible statement that a screen is not wired to a backend yet. The screens
 * that carry it run on sample content only — never on the user's own file. */
export function PreviewBadge({ what = "This screen" }) {
    return (
        <span role="note" title={`${what} is a design preview and is not connected yet.`}
            style={{ fontSize: 11.5, fontWeight: 700, padding: "4px 10px", borderRadius: 999, background: "#2f2a4a", color: "#c9bff5", whiteSpace: "nowrap" }}>
            Preview · not connected yet
        </span>
    );
}

/* The printed page. */
export function Paper({ title, width = 620, titleSize = 18, children, style }) {
    return (
        <article style={{
            width: `min(${width}px, 100%)`, background: "#ffffff", color: "#1d2a2e", borderRadius: 8,
            padding: "clamp(22px, 5vw, 46px) clamp(18px, 5vw, 52px)", boxSizing: "border-box",
            fontFamily: PAPER_FONT, fontSize: 14.5, lineHeight: 1.8,
            boxShadow: "0 10px 40px rgba(0,0,0,.28)", ...style,
        }}>
            {title && <h2 style={{ margin: `0 0 ${titleSize > 18 ? 22 : 18}px`, textAlign: "center", fontSize: titleSize, letterSpacing: titleSize > 18 ? ".16em" : ".14em", fontWeight: 600 }}>{title}</h2>}
            {children}
        </article>
    );
}

/* Inline marks used on the paper. */
export const TOKEN_STYLE = {
    fontFamily: "'Inter', sans-serif", fontSize: 12, fontWeight: 600, background: "#fdf0cf", color: "#7a5200",
    border: "1px solid #e9c46a", borderRadius: 5, padding: "0 5px",
};
export const VALUE_STYLE = { background: "#e3f6f3", color: "#0d5c54", borderRadius: 4, padding: "0 3px" };

/* A screen's own header row: back link, title, extras, actions. */
export function ScreenHeader({ onBack, backLabel = "Documents", title, children, actions }) {
    const t = useT();
    return (
        <header style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", padding: "12px 18px", borderBottom: `1px solid ${t.border}`, background: t.surface }}>
            {onBack && (
                <button type="button" onClick={onBack} style={{ background: "none", border: "none", color: t.primary, fontSize: 14, cursor: "pointer", padding: "6px 4px", fontFamily: "'Inter', sans-serif" }}>
                    ← {backLabel}
                </button>
            )}
            <h1 style={{ margin: 0, fontFamily: SERIF, fontSize: 21, fontWeight: 600, color: t.text }}>{title}</h1>
            {children}
            <div style={{ flex: 1 }} />
            {actions}
        </header>
    );
}

export const Icon = {
    eye: <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></svg>,
    pen: <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16z" /></svg>,
    arrow: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>,
    spark: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9z" /></svg>,
    mail: <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 7l9 6 9-6" /></svg>,
    contract: <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /><path d="M8 17c1.5-2 2.5-2 3 0s1.5 2 3-1" /></svg>,
    court: <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3v18M7 21h10M5 7h14M5 7l-3 6h6zM19 7l-3 6h6z" /></svg>,
    folder: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></svg>,
    upload: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 16V4M7 9l5-5 5 5" /><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" /></svg>,
    download: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 4v12M7 11l5 5 5-5M4 20h16" /></svg>,
    search: <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>,
};
