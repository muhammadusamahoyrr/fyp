'use client';
/* The client Documents screens' building blocks.
 *
 * The neutral primitives live in components/shared/ui/primitives.jsx (lawyer
 * screens use them too) and are re-exported here, so client code keeps
 * importing from this file. What is CLIENT-ONLY stays here: the approved
 * mockup palette for the Documents screens. Restyle the client here — never
 * in the shared primitives — so a client design change cannot reach a lawyer
 * screen. */
export * from "@/components/shared/ui/primitives.jsx";

/* THE MOCKUP'S PALETTE, exactly, for the Documents screens in dark mode.
 *
 * These screens were first built on the app-wide theme, whose dark values are
 * lighter and more saturated (#1A2E35 / #2A4750 / neon #40F0DC / warm-grey
 * text). The result read as a different design from the approved mockup. The
 * mockup's own values are used here instead; light mode keeps the app theme,
 * which the mockup never specified. */
export const MOCKUP_DARK = {
    bg: "#0f2228", surface: "#132a31", card: "#172f36", cardHi: "#1b363e",
    border: "#28464f", borderHi: "#3a5e68",
    primary: "#3fd6c6", primaryGlow: "rgba(63,214,198,0.22)", primaryGlow2: "#1f4a4f",
    text: "#e6f1f2", textDim: "#cfe3e6", textMuted: "#93aeb4", textFaint: "#6f9199",
    inputBg: "#0f2429", success: "#4fd18b", warn: "#f2b84b", danger: "#f07a7a", info: "#9fd0f5",
    shadowCard: "none",
    // Finer mockup values; absent in light mode, where each falls back.
    inputBorder: "#33555e", chipBg: "#1d3a42", chipBorder: "#2f5059", ghostBorder: "#3a5e68",
    label: "#6fcfc3", divider: "#22404a", hover: "#21414a", navText: "#a9c3c8",
};

/* THE DOCUMENTS MODULE'S TYPEFACE (2026-10-08): the Vault's Nunito Sans, a free
 * near-match for Avenir, across Templates, Drafts, the guided flow, the Vault
 * and their dialogs. Scoped by [data-docs-font] so no other screen changes.
 * !important because the shared primitives set their font inline.
 * `data-keep-font` opts an element out (a serif heading, a monospace citation). */
export const DOCS_FONT = "'Nunito Sans', 'Avenir Next', Avenir, system-ui, sans-serif";
export const DOCS_FONT_CSS = `[data-docs-font], [data-docs-font] *:not([data-keep-font]) { font-family: ${DOCS_FONT} !important; }`;

export function docsTheme(t) {
    return t && t.mode === "dark" ? { ...t, ...MOCKUP_DARK } : t;
}
