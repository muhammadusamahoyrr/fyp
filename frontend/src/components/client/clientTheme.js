'use client';
/* THE CLIENT DASHBOARD'S PALETTE (2026-10-10): the same look as the lawyer's
 * document screens (lawyer/draftingTheme.js), as the client's OWN copy, so a
 * lawyer restyle can never recolour a client screen and this file can never
 * reach a lawyer screen.
 *
 * How it applies without touching any layout: the tokens below are CSS custom
 * properties scoped by [data-client-theme]. ClientApp puts that attribute on
 * <body> while the client dashboard is mounted (and removes it on unmount), so
 * dialogs portalled to <body> get the tokens too. `clientThemeOnTokens` then
 * points the theme object's NEUTRAL colours at the tokens; every screen keeps
 * reading `t.bg`, `t.card`, … exactly as before.
 *
 * Accent colours stay HEX: callers append an alpha to them (`${t.primary}33`),
 * which a var() cannot take. */
export const CLIENT_TOKENS_CSS = `@import url('https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700&family=Literata:opsz,wght@7..72,500;7..72,600&family=JetBrains+Mono:wght@500&display=swap');
[data-client-theme]{--bg:#403E42;--bg-a:#403E42F5;--surface:#183840;--hover:#1E4550;--surface-2:#0F2429;--input:#16323A;--chip-n:rgba(255,255,255,.08);--line:rgba(150,215,220,.11);--line-strong:rgba(150,215,220,.22);--ink:#F1F5F6;--muted:#BFCACC;--faint:#93A4A8;--brand-solid:linear-gradient(135deg,#3EE0A1,#2EC4D6);--brand-solid-hover:linear-gradient(135deg,#5BE8B1,#4BD0E0);--on-brand:#04212A;--brand-text:#5EE6B0;--hover-tint:rgba(62,224,161,.10);--hover-ink:#6FEBBB;--danger:#FF8A80;--danger-soft:rgba(255,138,128,.14);--glow:rgba(62,224,161,.05);--hover-line:rgba(62,224,161,.55);--focus:#5EE6B0;--brand-soft:rgba(62,224,161,.13);--teal:#3CCFE0;--teal-hover:#5CD9E8;--on-teal:#04212A;--teal-ink:#6ADDEB;--chip-on-bg:#F3F2F4;--chip-on-ink:#2A282C;--gold:#F2C35E;--c-contract:#8DB4F0;--c-petition:#7FD39F;--c-general:#A9B7BC;--shadow-rest:0 1px 0 rgba(255,255,255,.04) inset,0 2px 6px rgba(0,0,0,.22);--shadow:0 1px 0 rgba(255,255,255,.05) inset,0 20px 36px -18px rgba(0,0,0,.7)}
[data-client-theme][data-mode="light"]{--bg:#F1F0F3;--bg-a:#F1F0F3F5;--surface:#FFFFFF;--hover:#F7F6F9;--surface-2:#EBE9EE;--input:#FFFFFF;--chip-n:rgba(0,0,0,.07);--line:#DFDCE3;--line-strong:#C9C5CE;--ink:#1E1C21;--muted:#5A5660;--faint:#7F7B85;--brand-solid:linear-gradient(135deg,#0E8A5F,#0B7A8C);--brand-solid-hover:linear-gradient(135deg,#0B7550,#096878);--on-brand:#FFFFFF;--brand-text:#0E7A55;--hover-tint:rgba(14,138,95,.08);--hover-ink:#0E7A55;--danger:#B42318;--danger-soft:rgba(180,35,24,.08);--glow:rgba(62,224,161,.08);--hover-line:rgba(14,138,95,.5);--focus:#0E7A55;--brand-soft:rgba(14,138,95,.10);--teal:#0B7A8C;--teal-hover:#096878;--on-teal:#FFFFFF;--teal-ink:#0B7A8C;--chip-on-bg:#1A2E35;--chip-on-ink:#EAF2F4;--gold:#92650B;--c-contract:#2C5FA8;--c-petition:#0E7044;--c-general:#4F6269;--shadow-rest:0 1px 2px rgba(10,30,40,.06);--shadow:0 2px 4px rgba(10,30,40,.04),0 18px 34px -16px rgba(10,40,50,.28)}
[data-client-theme]{font-family:"Hanken Grotesk",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
[data-client-theme] .ch-tcard{transition:transform .28s cubic-bezier(.22,1,.36,1),box-shadow .28s ease,background .2s ease,border-color .2s ease;will-change:transform}
[data-client-theme] .ch-tcard:hover,[data-client-theme] .ch-tcard:focus-within{transform:translateY(-4px);background:var(--hover)!important;border-color:color-mix(in srgb,var(--brand-text) 40%,transparent)!important;box-shadow:0 18px 34px -18px color-mix(in srgb,var(--brand-text) 45%,#000)!important}
@media (prefers-reduced-motion:reduce){[data-client-theme] .ch-tcard{transition:background .2s,border-color .2s}[data-client-theme] .ch-tcard:hover,[data-client-theme] .ch-tcard:focus-within{transform:none}}
[data-client-theme] .ch-tcard .ch-ib{background:transparent!important;border:1px solid var(--line)!important;color:var(--muted)!important;transition:color .15s,border-color .15s}
[data-client-theme] .ch-tcard .ch-ib:hover{color:var(--brand-text)!important;border-color:color-mix(in srgb,var(--brand-text) 40%,transparent)!important}
[data-client-theme] .ch-card-use{background:color-mix(in srgb,var(--brand-text) 10%,transparent)!important;color:var(--brand-text)!important;border:1px solid color-mix(in srgb,var(--brand-text) 35%,transparent)!important;transition:background .18s,color .18s,border-color .18s}
[data-client-theme] .ch-tcard:hover .ch-card-use,[data-client-theme] .ch-tcard:focus-within .ch-card-use{background:var(--brand-solid)!important;color:var(--on-brand)!important;border-color:transparent!important}
[data-client-theme] .ch-tcard .ch-card-use:hover{background:var(--brand-solid-hover)!important}
[data-client-theme] .ch-chip{min-height:38px!important;padding:0 8px 0 16px!important;gap:10px!important;font-size:14px!important;border:1px solid transparent!important;background:var(--chip-n)!important;color:var(--ink)!important;transition:background .15s,color .15s}
[data-client-theme] .ch-chip:hover{background:color-mix(in srgb,var(--chip-on-bg) 82%,transparent)!important;color:var(--chip-on-ink)!important}
[data-client-theme] .ch-chip[aria-pressed="true"]{background:var(--chip-on-bg)!important;color:var(--chip-on-ink)!important;font-weight:600!important}
[data-client-theme] .ch-chip .n{min-width:22px;text-align:center;font-size:11.5px;font-weight:600;padding:2px 7px;border-radius:999px;background:var(--chip-n);color:var(--muted);box-sizing:border-box}
[data-client-theme] .ch-chip:hover .n,[data-client-theme] .ch-chip[aria-pressed="true"] .n{background:rgba(127,127,127,.2);color:var(--chip-on-ink)}
[data-client-theme] .ch-pill-solid{background:linear-gradient(135deg,#12897f 0%,#1c9c66 100%)!important;color:#fff!important;border:1px solid transparent!important;border-radius:999px!important;font-weight:700!important;box-shadow:0 4px 14px rgba(28,156,102,.28);transition:filter .15s,box-shadow .15s}
[data-client-theme] .ch-pill-solid:hover{filter:brightness(1.08);box-shadow:0 6px 18px rgba(28,156,102,.36)}
[data-client-theme] .ch-pill-go{min-height:44px!important;height:44px;padding:0 14px 0 8px!important;gap:10px!important;font-size:14px!important}
[data-client-theme] .ch-pill-go .b{width:28px;height:28px;border-radius:50%;display:grid;place-items:center;background:rgba(255,255,255,.18);box-shadow:0 0 0 1px rgba(255,255,255,.12) inset}
[data-client-theme] .ch-pill-go .go{display:inline-flex;margin-left:2px;opacity:.85;transition:transform .2s ease,opacity .2s ease}
[data-client-theme] .ch-pill-go:hover .go{transform:translateX(3px);opacity:1}
[data-client-theme] .ch-search{border:1px solid var(--line)!important;box-shadow:var(--shadow-rest);transition:border-color .15s,box-shadow .15s}
[data-client-theme] .ch-search:hover{border-color:var(--hover-line)!important}
[data-client-theme] .ch-search:focus-within{border-color:var(--focus)!important;box-shadow:0 0 0 3px var(--brand-soft)}
[data-client-theme] .ch-search input::placeholder{color:var(--faint)}
[data-client-theme] .ch-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px}
[data-client-theme] .ch-stat{position:relative;display:grid;grid-template-columns:auto 1fr;grid-template-areas:"ic l" "v v" "s s";column-gap:12px;align-items:center;padding:18px 18px 16px;border-radius:20px;border:1px solid color-mix(in srgb,var(--c) 14%,var(--line));background:radial-gradient(120% 90% at 100% 0%,color-mix(in srgb,var(--c) 13%,transparent) 0%,transparent 55%),linear-gradient(180deg,color-mix(in srgb,var(--surface) 92%,#fff 8%),var(--surface));box-shadow:0 1px 0 rgba(255,255,255,.05) inset,0 10px 24px -18px rgba(0,0,0,.65);overflow:hidden;transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
[data-client-theme] .ch-stat:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--c) 45%,var(--line));box-shadow:0 1px 0 rgba(255,255,255,.06) inset,0 18px 32px -20px color-mix(in srgb,var(--c) 70%,#000)}
[data-client-theme] .ch-stat .ic{grid-area:ic;width:38px;height:38px;border-radius:12px;display:grid;place-items:center;color:var(--c);background:color-mix(in srgb,var(--c) 16%,transparent);box-shadow:0 0 0 1px color-mix(in srgb,var(--c) 22%,transparent) inset}
[data-client-theme] .ch-stat .ic svg{transition:transform .35s cubic-bezier(.34,1.56,.64,1)}
[data-client-theme] .ch-stat:hover .ic svg{transform:scale(1.12) rotate(-6deg)}
[data-client-theme] .ch-stat .l{grid-area:l;font-size:13.5px;font-weight:600;color:var(--muted);line-height:1.25}
[data-client-theme] .ch-stat:hover .l{color:var(--ink)}
[data-client-theme] .ch-stat .v{grid-area:v;font:600 34px/1 "Literata",Georgia,serif;color:var(--ink);margin:16px 0 6px;letter-spacing:-.01em}
[data-client-theme] .ch-stat .s{grid-area:s;font-size:12.5px;color:var(--muted)}
[data-client-theme][data-mode="light"] .ch-stat,[data-client-theme] [data-mode="light"] .ch-stat{box-shadow:0 1px 2px rgba(10,30,40,.06)}`;
/* `.ch-tcard`: a template card — on hover its border turns mint and it lifts to
 * the hover surface. `.ch-card-use`: its action, a mint outline until the card
 * is hovered or focused, then the brand gradient. `.ch-ib`: its round icon
 * buttons. (!important: the primitives set their colours inline.) */

// The lawyer documents' brand: mint in dark, deep green in light.
const ACCENT = {
    dark: {
        primary: "#3EE0A1", primaryDim: "#2EC4D6",
        primaryGlow: "rgba(62,224,161,0.25)", primaryGlow2: "rgba(62,224,161,0.12)",
        badgePrimary: { bg: "rgba(62,224,161,0.13)", color: "#5EE6B0", border: "rgba(62,224,161,0.3)" },
        iconPrimary: { bg: "rgba(62,224,161,0.13)", color: "#5EE6B0" },
    },
    light: {
        primary: "#0E8A5F", primaryDim: "#0B7A8C",
        primaryGlow: "rgba(14,138,95,0.12)", primaryGlow2: "rgba(14,138,95,0.07)",
        badgePrimary: { bg: "rgba(14,138,95,0.10)", color: "#0E7A55", border: "rgba(14,138,95,0.22)" },
        iconPrimary: { bg: "rgba(14,138,95,0.10)", color: "#0E7A55" },
    },
};

export const clientMode = t => (t?.mode === "light" ? "light" : "dark");

export function clientThemeOnTokens(t) {
    return {
        ...t,
        ...ACCENT[clientMode(t)],
        onTokens: true,
        bg: "var(--bg)", surface: "var(--surface)", card: "var(--surface)", cardHi: "var(--surface-2)",
        border: "var(--line)", borderHi: "var(--line-strong)", text: "var(--ink)", textDim: "var(--ink)",
        textMuted: "var(--muted)", textFaint: "var(--faint)", inputBg: "var(--input)",
        navBg: "var(--bg-a)", grad1: "var(--brand-solid)",
        shadowCard: "var(--shadow-rest)", shadowHover: "var(--shadow)",
        // Read by the client primitives (shared/ui/primitives.jsx), each with a
        // fallback, so a theme without them draws exactly as before.
        primaryFill: "var(--brand-solid)", onPrimaryFill: "var(--on-brand)",
        chipBg: "var(--chip-n)", chipBorder: "transparent", ghostBorder: "var(--line-strong)",
    };
}

/* The palette's soft accents, for icon tiles: a tinted square with the ink on top. */
export const tint = (ink, pct = 14) => ({ background: `color-mix(in srgb, ${ink} ${pct}%, transparent)`, color: ink });
