/* The Legal Drafting screens' palette (2026-10-09): the approved v18 design,
 * shared by the template home (DraftingHome.jsx) and the editor
 * (DocAutomationPage.jsx). Lawyer-owned and scoped by [data-drafting-theme],
 * so it can never colour a client screen. Dark is the default; the light set
 * follows the lawyer app's theme toggle through data-mode. */
export const DRAFTING_TOKENS_CSS = `@import url('https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700&family=Literata:opsz,wght@7..72,500;7..72,600&family=JetBrains+Mono:wght@500&display=swap');
[data-drafting-theme]{--bg:#403E42;--bg-a:#403E42E6;--surface:#183840;--hover:#1E4550;--surface-2:#0F2429;--input:#16323A;--chip-n:rgba(255,255,255,.08);--line:rgba(150,215,220,.11);--line-strong:rgba(150,215,220,.22);--ink:#F1F5F6;--muted:#BFCACC;--faint:#93A4A8;--hover-line:rgba(62,224,161,.55);--hover-tint:rgba(62,224,161,.10);--hover-ink:#6FEBBB;--brand-solid:linear-gradient(135deg,#3EE0A1,#2EC4D6);--brand-solid-hover:linear-gradient(135deg,#5BE8B1,#4BD0E0);--on-brand:#04212A;--teal:#3CCFE0;--teal-hover:#5CD9E8;--on-teal:#04212A;--teal-soft:rgba(60,207,224,.14);--teal-ink:#6ADDEB;--brand-text:#5EE6B0;--brand-soft:rgba(62,224,161,.13);--focus:#5EE6B0;--gold:#F2C35E;--danger:#FF8A80;--danger-soft:rgba(255,138,128,.14);--chip-on-bg:#F3F2F4;--chip-on-ink:#2A282C;--c-contract:#8DB4F0;--c-petition:#7FD39F;--c-general:#A9B7BC;--paper:#F2F4F3;--paper-ink:#1C1E22;--paper-line:#C8CFCD;--shadow-rest:0 1px 0 rgba(255,255,255,.04) inset,0 2px 6px rgba(0,0,0,.22);--shadow:0 1px 0 rgba(255,255,255,.05) inset,0 20px 36px -18px rgba(0,0,0,.7);--glow:rgba(62,224,161,.05)}
[data-drafting-theme][data-mode="light"]{--bg:#F1F0F3;--bg-a:#F1F0F3E6;--surface:#FFFFFF;--hover:#FFFFFF;--surface-2:#EBE9EE;--input:#FFFFFF;--chip-n:rgba(0,0,0,.07);--line:#DFDCE3;--line-strong:#C9C5CE;--ink:#1E1C21;--muted:#5A5660;--faint:#7F7B85;--hover-line:rgba(14,138,95,.5);--hover-tint:rgba(14,138,95,.08);--hover-ink:#0E7A55;--brand-solid:linear-gradient(135deg,#0E8A5F,#0B7A8C);--brand-solid-hover:linear-gradient(135deg,#0B7550,#096878);--on-brand:#FFFFFF;--teal:#0B7A8C;--teal-hover:#096878;--on-teal:#FFFFFF;--teal-soft:rgba(11,122,140,.10);--teal-ink:#0B7A8C;--brand-text:#0E7A55;--brand-soft:rgba(14,138,95,.10);--focus:#0E7A55;--gold:#92650B;--danger:#B42318;--danger-soft:rgba(180,35,24,.08);--chip-on-bg:#1A2E35;--chip-on-ink:#EAF2F4;--c-contract:#2C5FA8;--c-petition:#0E7044;--c-general:#4F6269;--paper:#FFFFFF;--paper-ink:#1C1E22;--paper-line:#D9E0E3;--shadow-rest:0 1px 2px rgba(10,30,40,.06);--shadow:0 2px 4px rgba(10,30,40,.04),0 18px 34px -16px rgba(10,40,50,.28);--glow:rgba(62,224,161,.08)}`;

export const draftingMode = t => (t?.mode === "light" ? "light" : "dark");

/* A screen drawn from the lawyer theme object `t` moves onto these tokens by
 * pointing t's NEUTRAL colours at them (2026-10-09; Cases, Appointments): the
 * same palette as the document screens, light and dark, with no layout
 * touched. Accent colours stay hex, because callers append alpha to them
 * (`${t.success}cc`). Render inside an element carrying data-drafting-theme. */
export function themeOnTokens(t) {
    return {
        ...t,
        bg: "var(--bg)", surface: "var(--surface)", card: "var(--surface)", cardHi: "var(--surface-2)",
        border: "var(--line)", borderHi: "var(--line-strong)", text: "var(--ink)", textDim: "var(--ink)",
        textMuted: "var(--muted)", textFaint: "var(--faint)", inputBg: "var(--input)",
        shadowCard: "var(--shadow-rest)",
    };
}
