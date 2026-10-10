'use client';
/* Legal Drafting — the lawyer's template home (2026-10-09).
 *
 * The approved "Document templates" design (v18): a header with the page's
 * actions, a strip of three ways to start, a sticky toolbar (search, sort,
 * grid/list), category chips, and the template cards.
 *
 * It shows only what the drafter really has. The catalogue is deliberately
 * short (see lib/lawyerDraftTemplates.js): a card exists only for a template
 * with a body of its own, so there are no usage counts, page counts or
 * statute mappings the system cannot back. "Upload template" has no backend
 * yet: it is shown disabled and says so. Saved (bookmarked) templates are a
 * per-browser convenience, kept in localStorage.
 *
 * Lawyer-owned UI: its CSS is scoped by [data-drafting-home] and never reaches
 * a client screen (tests/docs_isolation.test.mjs). */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon, I } from "./icons.jsx";
import { ModalPortal, BACKDROP } from "./ui.jsx";
import { DRAFTING_TOKENS_CSS } from "./draftingTheme.js";
import { tiltHandlers } from "./tilt.js";
import MyDocuments from "./MyDocuments.jsx";
import { useTheme, useCase } from "./theme.js";
import { useAuth } from "@/context/AuthContext.jsx";
import { TEMPLATES, BLANK_TEMPLATE, buildContent } from "@/lib/lawyerDraftTemplates.js";

const SAVED_KEY = "attorney:lawyer-saved-templates";
const CAT_VAR = { Family: "--c-petition", Litigation: "--c-contract", General: "--c-general" };
// The practice areas the library is growing into. Listed so a lawyer sees the
// whole map; each says honestly that it has no template yet (count 0).
const MORE_CATS = [
    ["Agreement / Contract", "#8DB4F0"], ["Application / Petition", "#7FD39F"], ["Business / Commercial", "#C9A2F0"],
    ["Notice / Letter", "#F0A07F"], ["Property", "#E6C36A"], ["Criminal", "#F08FA8"],
];
const MORE_COLOR = Object.fromEntries(MORE_CATS);
const catColor = cat => MORE_COLOR[cat] || `var(${CAT_VAR[cat] || "--c-general"})`;

function readSaved() {
    try {
        const ids = JSON.parse(window.localStorage.getItem(SAVED_KEY) || "[]");
        return new Set(Array.isArray(ids) ? ids : []);
    } catch { return new Set(); }
}
function writeSaved(set) {
    try { window.localStorage.setItem(SAVED_KEY, JSON.stringify([...set])); } catch { /* a convenience only */ }
}

/* The page's components. The palette is shared with the editor:
 * draftingTheme.js (DRAFTING_TOKENS_CSS, scoped by [data-drafting-theme]). */
export const DRAFTING_HOME_CSS = `[data-drafting-home]{flex:1;min-height:0;overflow-y:auto;background:radial-gradient(900px 360px at 25% -80px,var(--glow),transparent 70%) no-repeat,var(--bg);color:var(--ink);font:15px/1.5 "Hanken Grotesk",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
[data-drafting-home] *{box-sizing:border-box}
[data-drafting-home] button,[data-drafting-home] input,[data-drafting-home] select{font:inherit;color:inherit}
[data-drafting-home] button{cursor:pointer}
[data-drafting-home] :focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:6px}
[data-drafting-home] .dh-wrap{max-width:1240px;margin:0 auto;padding:22px clamp(16px,3.2vw,40px) 64px;display:grid;gap:26px}
[data-drafting-home] .dh-topbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
[data-drafting-home] .dh-topbar-right{margin-left:auto;display:flex;gap:8px;align-items:center}
[data-drafting-home] .dh-pill{height:44px;border-radius:999px;border-color:var(--line);padding:0 16px}
[data-drafting-home] .dh-acct{display:flex;align-items:center;gap:10px;height:44px;padding:0 14px 0 6px;border-radius:999px;border:1px solid var(--line);background:var(--surface);max-width:240px}
[data-drafting-home] .dh-acct b{display:block;font-size:13px;font-weight:600;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-drafting-home] .dh-acct small{font-size:11.5px;color:var(--muted)}
[data-drafting-home] .dh-avatar{width:32px;height:32px;flex:none;border-radius:50%;display:grid;place-items:center;font-size:12px;font-weight:700;background:#5B7BE0;color:#fff}
[data-drafting-home] .dh-crumbs{font-size:13px;color:var(--muted)}
[data-drafting-home] .dh-crumbs b{color:var(--ink);font-weight:600}
[data-drafting-home] .dh-head{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;flex-wrap:wrap}
[data-drafting-home] .dh-head h1{font-family:"Literata",Georgia,serif;font-weight:600;font-size:clamp(28px,3.4vw,38px);line-height:1.1;margin:0;letter-spacing:-.01em}
[data-drafting-home] .dh-accent{background:linear-gradient(90deg,var(--brand-text),var(--teal-ink));-webkit-background-clip:text;background-clip:text;color:transparent}
[data-drafting-home] .dh-head p{margin:8px 0 0;color:var(--muted);max-width:62ch}
[data-drafting-home] .dh-head p b{color:var(--ink)}
[data-drafting-home] .dh-btn{display:inline-flex;align-items:center;gap:8px;height:40px;padding:0 16px;border-radius:10px;border:1px solid var(--line-strong);background:var(--surface);font-weight:600;font-size:14px;white-space:nowrap}
[data-drafting-home] .dh-btn:hover:not(:disabled){border-color:var(--hover-line);background:var(--hover-tint);color:var(--hover-ink)}
[data-drafting-home] .dh-btn:disabled{opacity:.55;cursor:not-allowed}
[data-drafting-home] .dh-btn.primary{background:var(--brand-solid);border-color:transparent;color:var(--on-brand);box-shadow:0 8px 18px -10px rgba(46,196,214,.6)}
[data-drafting-home] .dh-btn.primary:hover{background:var(--brand-solid-hover);color:var(--on-brand)}
[data-drafting-home] .dh-soon{font-size:10.5px;font-weight:700;letter-spacing:.04em;padding:1px 7px;border-radius:999px;background:var(--chip-n);color:var(--muted)}
[data-drafting-home] .dh-start{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
[data-drafting-home] .dh-sc{position:relative;display:flex;align-items:center;gap:14px;padding:18px 18px;border-radius:20px;text-align:left;cursor:pointer;overflow:hidden;border:1px solid color-mix(in srgb,var(--c) 14%,var(--line));background:radial-gradient(120% 110% at 100% 0%,color-mix(in srgb,var(--c) 13%,transparent) 0%,transparent 55%),linear-gradient(180deg,color-mix(in srgb,var(--surface) 92%,#fff 8%),var(--surface));box-shadow:0 1px 0 rgba(255,255,255,.05) inset,0 10px 24px -18px rgba(0,0,0,.65);transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
[data-drafting-home] .dh-sc:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--c) 45%,var(--line));box-shadow:0 1px 0 rgba(255,255,255,.06) inset,0 18px 32px -20px color-mix(in srgb,var(--c) 70%,#000)}
[data-drafting-home] .dh-sc:active{transform:translateY(0)}
[data-drafting-home] .dh-ic{width:46px;height:46px;flex:none;border-radius:14px;display:grid;place-items:center;color:var(--c);background:color-mix(in srgb,var(--c) 16%,transparent);box-shadow:0 0 0 1px color-mix(in srgb,var(--c) 22%,transparent) inset;transition:background .18s,color .18s}
[data-drafting-home] .dh-sc:hover .dh-ic{background:var(--c);color:var(--surface-2)}
[data-drafting-home] .blank .dh-ic{background:var(--brand-solid);color:var(--on-brand);box-shadow:0 8px 18px -10px rgba(46,196,214,.8)}
[data-drafting-home] .dh-sc .t{display:block;font-weight:700;font-size:15.5px}
[data-drafting-home] .dh-sc .d{display:block;font-size:13px;color:var(--muted);margin-top:2px}
[data-drafting-home] .dh-sc .go{margin-left:auto;width:32px;height:32px;flex:none;border-radius:50%;display:grid;place-items:center;color:var(--faint);background:color-mix(in srgb,var(--c) 0%,transparent);transition:transform .18s,background .18s,color .18s}
[data-drafting-home] .dh-sc:hover .go{transform:translateX(3px);color:var(--c);background:color-mix(in srgb,var(--c) 14%,transparent)}
[data-drafting-home] .dh-toolbar{position:sticky;top:0;z-index:5;background:var(--bg-a);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);padding-block:12px;margin-block:-12px;display:grid;gap:12px;border-bottom:1px solid var(--line)}
[data-drafting-home] .dh-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
[data-drafting-home] .dh-search{flex:1 1 320px;min-width:0;display:flex;align-items:center;gap:10px;height:42px;padding:0 12px;border-radius:10px;background:var(--input);border:1px solid var(--line);box-shadow:inset 0 1px 2px rgba(0,0,0,.18)}
[data-drafting-home] .dh-search:hover,[data-drafting-home] .dh-select:hover{border-color:var(--hover-line)}
[data-drafting-home] .dh-search:focus-within{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-drafting-home] .dh-search input{flex:1;min-width:0;border:0;background:none;outline:none;height:100%}
[data-drafting-home] .dh-search input::placeholder{color:var(--faint)}
[data-drafting-home] .dh-search svg{color:var(--faint)}
[data-drafting-home] .dh-select{height:42px;padding:0 12px;border-radius:10px;background:var(--input);border:1px solid var(--line)}
[data-drafting-home] .dh-seg{display:flex;border:1px solid var(--line);border-radius:10px;background:var(--input);padding:3px}
[data-drafting-home] .dh-seg button{width:34px;height:34px;border:0;background:none;border-radius:7px;color:var(--faint);display:grid;place-items:center}
[data-drafting-home] .dh-seg button:hover{color:var(--hover-ink)}
[data-drafting-home] .dh-seg button[aria-pressed="true"]{background:var(--surface);color:var(--ink);box-shadow:var(--shadow-rest)}
[data-drafting-home] .dh-chipbar{position:relative;display:flex;align-items:center;min-width:0}
[data-drafting-home] .dh-chips{display:flex;align-items:center;gap:6px;min-width:0;flex:1;overflow-x:auto;scroll-behavior:smooth;scrollbar-width:none;padding:3px 2px}
[data-drafting-home] .dh-chips::-webkit-scrollbar{display:none}
[data-drafting-home] .dh-chipbar.fl .dh-chips{-webkit-mask-image:linear-gradient(90deg,transparent 0,#000 56px);mask-image:linear-gradient(90deg,transparent 0,#000 56px)}
[data-drafting-home] .dh-chipbar.fr .dh-chips{-webkit-mask-image:linear-gradient(90deg,#000 calc(100% - 56px),transparent 100%);mask-image:linear-gradient(90deg,#000 calc(100% - 56px),transparent 100%)}
[data-drafting-home] .dh-chipbar.fl.fr .dh-chips{-webkit-mask-image:linear-gradient(90deg,transparent 0,#000 56px,#000 calc(100% - 56px),transparent 100%);mask-image:linear-gradient(90deg,transparent 0,#000 56px,#000 calc(100% - 56px),transparent 100%)}
[data-drafting-home] .dh-chev{position:absolute;top:50%;z-index:1;width:34px;height:34px;margin-top:-17px;border-radius:50%;display:grid;place-items:center;border:1px solid var(--line-strong);background:var(--surface);color:var(--ink);box-shadow:0 6px 14px -6px rgba(0,0,0,.6);cursor:pointer;transition:transform .15s,border-color .15s,color .15s}
[data-drafting-home] .dh-chev:hover{border-color:var(--hover-line);color:var(--hover-ink);transform:scale(1.08)}
[data-drafting-home] .dh-chev.l{left:-4px}
[data-drafting-home] .dh-chev.r{right:-4px}
[data-drafting-home] .dh-chip{flex:none}
[data-drafting-home] .dh-chip.zero .n{opacity:.6}
[data-drafting-home] .dh-chip{display:inline-flex;align-items:center;gap:8px;height:36px;padding:0 8px 0 14px;border-radius:999px;border:1px solid transparent;background:transparent;color:var(--muted);font-size:13.5px;font-weight:500;white-space:nowrap}
[data-drafting-home] .dh-chip:hover{background:var(--hover-tint);color:var(--hover-ink)}
[data-drafting-home] .dh-chip .sw{width:8px;height:8px;border-radius:50%;background:var(--c)}
[data-drafting-home] .dh-chip .n{font-family:"JetBrains Mono",monospace;font-size:11px;color:var(--muted);background:var(--chip-n);padding:1px 7px;border-radius:999px}
[data-drafting-home] .dh-chip[aria-pressed="true"]{background:var(--chip-on-bg);color:var(--chip-on-ink);font-weight:600}
[data-drafting-home] .dh-chip[aria-pressed="true"] .n{color:var(--chip-on-ink);background:rgba(127,127,127,.18)}
[data-drafting-home] .dh-chip[aria-pressed="true"] .sw{background:currentColor}
[data-drafting-home] .dh-result{display:flex;justify-content:space-between;align-items:center;font-size:13px;color:var(--muted);gap:12px;flex-wrap:wrap}
[data-drafting-home] .dh-result b{color:var(--ink)}
[data-drafting-home] .dh-link{background:none;border:0;color:var(--brand-text);font-weight:600;padding:0}
[data-drafting-home] .dh-link:hover{color:var(--hover-ink)}
[data-drafting-home] .dh-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:16px}
[data-drafting-home] .dh-card{position:relative;display:flex;flex-direction:column;border:1px solid rgba(150,215,220,.10);border-radius:14px;background:var(--surface);box-shadow:var(--shadow-rest);overflow:hidden;transition:border-color .15s,box-shadow .2s,transform .2s,background .15s}
[data-drafting-home][data-mode="light"] .dh-card{border-color:var(--line)}
[data-drafting-home] .dh-card:hover{border-color:var(--hover-line);background:var(--hover);box-shadow:var(--shadow);transform:translateY(-2px)}
[data-drafting-home] .dh-card:focus-within{border-color:var(--teal)}
[data-drafting-home] .dh-thumb{position:relative;height:118px;background:var(--surface-2);border-bottom:1px solid var(--line);overflow:hidden;transition:background .2s}
[data-drafting-home] .dh-card:hover .dh-thumb{background:var(--hover-tint)}
[data-drafting-home] .dh-paper{position:absolute;left:22px;right:22px;top:20px;height:130px;background:var(--paper);border-radius:4px 4px 0 0;box-shadow:0 8px 20px -8px rgba(0,0,0,.6);padding:14px 16px;display:grid;gap:6px;align-content:start;transition:transform .25s}
[data-drafting-home] .dh-card:hover .dh-paper{transform:translateY(-6px)}
[data-drafting-home] .dh-paper i{display:block;height:4px;border-radius:2px;background:var(--paper-line)}
[data-drafting-home] .dh-paper i.h{height:6px;width:46%;margin:0 auto 4px;background:#7d8783}
[data-drafting-home] .dh-paper i.s{width:72%}
[data-drafting-home] .dh-paper i.xs{width:38%}
[data-drafting-home] .dh-seal{position:absolute;right:30px;top:62px;width:22px;height:22px;border-radius:50%;border:2px solid var(--c);opacity:.85}
[data-drafting-home] .dh-lang{position:absolute;left:12px;bottom:10px;display:flex;gap:4px}
[data-drafting-home] .dh-lang span{font-family:"JetBrains Mono",monospace;font-size:10px;padding:1px 6px;border-radius:4px;background:var(--surface);color:var(--muted);border:1px solid var(--line)}
[data-drafting-home] .dh-bm{position:absolute;top:10px;right:10px;width:32px;height:32px;border-radius:8px;border:1px solid var(--line);background:var(--surface);display:grid;place-items:center;color:var(--faint);z-index:2}
[data-drafting-home] .dh-bm:hover{color:var(--hover-ink);border-color:var(--hover-line)}
[data-drafting-home] .dh-bm[aria-pressed="true"]{color:var(--gold);border-color:var(--gold)}
[data-drafting-home] .dh-bm[aria-pressed="true"] path{fill:currentColor}
[data-drafting-home] .dh-body{padding:14px 16px 16px;display:flex;flex-direction:column;gap:8px;flex:1}
[data-drafting-home] .dh-cat{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:var(--c)}
[data-drafting-home] .dh-cat::before{content:"";width:7px;height:7px;border-radius:2px;background:var(--c)}
[data-drafting-home] .dh-card h3{font-family:"Literata",Georgia,serif;font-weight:600;font-size:17.5px;line-height:1.3;margin:0}
[data-drafting-home] .dh-card p{margin:0;color:var(--muted);font-size:13.5px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
[data-drafting-home] .dh-meta{margin-top:auto;padding-top:10px;border-top:1px dashed var(--line);display:flex;align-items:center;gap:8px;font-size:12px;color:var(--faint);min-width:0}
[data-drafting-home] .dh-meta .law{font-family:"JetBrains Mono",monospace;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
[data-drafting-home] .dh-meta .pp{margin-left:auto;white-space:nowrap}
[data-drafting-home] .dh-actions{display:flex;gap:8px;padding:0 16px 16px}
[data-drafting-home] .dh-actions .dh-btn{height:36px;font-size:13px;flex:1;justify-content:center}
[data-drafting-home] .dh-actions .dh-btn.ghost{flex:0 0 auto;padding:0 12px;background:transparent;border-color:var(--line)}
[data-drafting-home] .dh-actions .dh-btn.use{background:var(--surface-2);color:var(--ink);border-color:var(--line)}
[data-drafting-home] .dh-card:hover .dh-btn.use,[data-drafting-home] .dh-card:focus-within .dh-btn.use{background:var(--teal);color:var(--on-teal);border-color:transparent}
[data-drafting-home] .dh-card .dh-btn.use:hover{background:var(--teal-hover);color:var(--on-teal)}
[data-drafting-home] .dh-grid.list{grid-template-columns:1fr;gap:8px}
[data-drafting-home] .dh-grid.list .dh-card{flex-direction:row;align-items:center}
[data-drafting-home] .dh-grid.list .dh-card:hover{transform:none}
[data-drafting-home] .dh-grid.list .dh-thumb{display:none}
[data-drafting-home] .dh-grid.list .dh-body{flex-direction:row;align-items:center;gap:16px;padding:14px 16px;flex-wrap:wrap}
[data-drafting-home] .dh-grid.list .dh-body > div{min-width:0;flex:1 1 280px}
[data-drafting-home] .dh-grid.list .dh-card p{-webkit-line-clamp:1}
[data-drafting-home] .dh-grid.list .dh-meta{margin:0;padding:0;border:0;flex:0 1 auto}
[data-drafting-home] .dh-grid.list .dh-actions{padding:0 16px 0 0}
[data-drafting-home] .dh-grid.list .dh-actions .dh-btn{flex:0 0 auto}
[data-drafting-home] .dh-grid.list .dh-bm{position:static;margin-right:12px;flex:none}
[data-drafting-home] .dh-empty{border:1px dashed var(--line-strong);border-radius:14px;padding:48px 20px;text-align:center;color:var(--muted)}
[data-drafting-home] .dh-empty h3{font-family:"Literata",Georgia,serif;color:var(--ink);margin:0 0 6px;font-size:20px}
[data-drafting-home] .dh-drafts{display:grid;gap:8px}
[data-drafting-home] .dh-draft{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:12px;border:1px solid var(--line);background:var(--surface)}
[data-drafting-home] .dh-label{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--faint);font-weight:600}
[data-drafting-home] .dh-ic svg,[data-drafting-home] .dh-btn svg{transition:transform .35s cubic-bezier(.34,1.56,.64,1)}
[data-drafting-home] .blank:hover .dh-ic svg{transform:rotate(90deg) scale(1.1)}
[data-drafting-home] .drafts:hover .dh-ic svg{animation:dhNudge .6s ease}
[data-drafting-home] .ai:hover .dh-ic svg{animation:dhTwinkle 1s ease-in-out infinite}
[data-drafting-home] .dh-sc .go svg{display:block}
[data-drafting-home] .dh-sc:hover .go svg{animation:dhArrow .5s ease}
[data-drafting-home] .dh-sc::after{content:"";position:absolute;top:0;bottom:0;left:0;width:45%;pointer-events:none;background:linear-gradient(90deg,transparent,rgba(255,255,255,.09),transparent);transform:translateX(-130%) skewX(-20deg)}
[data-drafting-home] .dh-sc:hover::after{animation:dhShine .85s ease}
[data-drafting-home] .dh-btn.primary:hover svg{transform:rotate(90deg)}
[data-drafting-home] .dh-bm[aria-pressed="true"] svg{animation:dhPop .35s cubic-bezier(.34,1.56,.64,1)}
[data-drafting-home] .dh-card:hover .dh-btn.use{letter-spacing:.01em}
@keyframes dhNudge{0%,100%{transform:rotate(0)}30%{transform:rotate(-10deg) translateY(-2px)}60%{transform:rotate(7deg)}}
@keyframes dhTwinkle{0%,100%{transform:scale(1) rotate(0)}50%{transform:scale(1.2) rotate(20deg)}}
@keyframes dhArrow{0%{transform:translateX(0);opacity:1}45%{transform:translateX(14px);opacity:0}46%{transform:translateX(-14px);opacity:0}100%{transform:translateX(0);opacity:1}}
@keyframes dhShine{to{transform:translateX(330%) skewX(-20deg)}}
@keyframes dhPop{0%{transform:scale(.6)}60%{transform:scale(1.25)}100%{transform:scale(1)}}
[data-drafting-home] .dh-sc.d3{transform:perspective(900px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg));transition:transform .2s ease-out,box-shadow .18s ease,border-color .18s ease}
[data-drafting-home] .dh-sc.d3:hover{transform:perspective(900px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg)) translateY(-3px)}
[data-drafting-home] .dh-sc.d3:active{transform:perspective(900px) translateY(1px) scale(.985)}
[data-drafting-home] .dh-sc.d3 .dh-ic{position:relative;transition:transform .45s cubic-bezier(.34,1.56,.64,1),box-shadow .3s,background .18s,color .18s}
[data-drafting-home] .dh-sc.d3 .dh-ic svg{transition:transform .45s cubic-bezier(.34,1.56,.64,1)}
[data-drafting-home] .dh-sc.d3 .dh-ic::before{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;opacity:0;transition:opacity .2s;background:radial-gradient(circle at calc((var(--px,0) + .5) * 100%) calc((var(--py,0) + .5) * 100%),rgba(255,255,255,.55),transparent 60%)}
[data-drafting-home] .dh-sc.d3:hover .dh-ic{transform:translate(calc(var(--px,0) * 6px),calc(var(--py,0) * 6px - 6px)) scale(1.14) rotate(-4deg);box-shadow:0 0 0 1px color-mix(in srgb,var(--c) 40%,transparent) inset,0 16px 22px -10px color-mix(in srgb,var(--c) 75%,#000),0 4px 8px -4px rgba(0,0,0,.5)}
[data-drafting-home] .dh-sc.d3:hover .dh-ic::before{opacity:1}
[data-drafting-home] .dh-sc.d3:hover .dh-ic svg{transform:translate(calc(var(--px,0) * 7px),calc(var(--py,0) * 7px)) scale(1.08)}
@media (prefers-reduced-motion:reduce){[data-drafting-home] *,[data-drafting-home] *::after{transition:none!important;animation:none!important}}`;

/* The preview reads the starter itself: the same body the editor opens with,
 * before any case is chosen. buildContent escapes every value, so the text is
 * safe to place as HTML. */
function PreviewDialog({ tmpl, mode, onClose, onUse }) {
    useEffect(() => {
        const onKey = e => { if (e.key === "Escape") onClose(); };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [onClose]);
    return (
        <ModalPortal>
            <div style={{ ...BACKDROP, display: "grid", placeItems: "center", padding: 24 }} onClick={onClose}>
                <div data-drafting-home data-drafting-theme data-mode={mode} role="dialog" aria-modal="true" aria-label={`Preview: ${tmpl.name}`}
                    onClick={e => e.stopPropagation()}
                    style={{ flex: "none", width: "min(820px, 100%)", maxHeight: "86vh", borderRadius: 16, border: "1px solid var(--line-strong)", display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--surface)" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", borderBottom: "1px solid var(--line)" }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <div className="dh-cat" style={{ "--c": catColor(tmpl.cat) }}>{tmpl.cat}</div>
                            <div style={{ fontFamily: "Literata, Georgia, serif", fontWeight: 600, fontSize: 19 }}>{tmpl.name}</div>
                        </div>
                        <button type="button" className="dh-btn primary" onClick={() => onUse(tmpl)}>Use template</button>
                        <button type="button" className="dh-btn" aria-label="Close preview" onClick={onClose} style={{ width: 40, padding: 0, justifyContent: "center" }}><Icon d={I.x} size={16} /></button>
                    </div>
                    <div style={{ overflowY: "auto", padding: 24, background: "var(--surface-2)" }}>
                        <div data-preview-text
                            style={{ background: "#FBFAF7", color: "#1C1E22", borderRadius: 4, padding: "40px 48px", fontFamily: "Literata, Georgia, serif", fontSize: 14.5, lineHeight: 1.7, whiteSpace: "pre-wrap", boxShadow: "0 18px 36px -20px rgba(0,0,0,.6)" }}
                            dangerouslySetInnerHTML={{ __html: buildContent(tmpl, null) }} />
                    </div>
                </div>
            </div>
        </ModalPortal>
    );
}

export default function DraftingHome({ onSelect, drafts = [], onOpenDraft, onDeleteDraft, t }) {
    const { setPage } = useCase();
    const mode = t?.mode === "light" ? "light" : "dark";
    // The app's own theme switch and signed-in lawyer, shown in the top bar.
    const { toggle } = useTheme();
    const { user } = useAuth();
    const displayName = user?.full_name || "Advocate";
    const initials = displayName.split(/\s+/).filter(Boolean).map(w => w[0]).join("").slice(0, 2).toUpperCase();
    const [search, setSearch] = useState("");
    const [cat, setCat] = useState("All");
    // The category row scrolls sideways; its arrows and edge fades show only
    // where there is more to see.
    const chipsRef = useRef(null);
    const [edges, setEdges] = useState({ l: false, r: false });
    const readEdges = useCallback(() => {
        const el = chipsRef.current;
        if (!el) return;
        const l = el.scrollLeft > 4, r = el.scrollLeft + el.clientWidth < el.scrollWidth - 4;
        setEdges(e => (e.l === l && e.r === r ? e : { l, r }));
    }, []);
    useEffect(() => {
        readEdges();
        // Fonts and the sidebar change the row width after mount, not only a resize.
        const ro = typeof ResizeObserver !== "undefined" && chipsRef.current ? new ResizeObserver(readEdges) : null;
        ro?.observe(chipsRef.current);
        window.addEventListener("resize", readEdges);
        return () => { ro?.disconnect(); window.removeEventListener("resize", readEdges); };
    }, [readEdges]);
    const nudge = dir => chipsRef.current?.scrollBy({ left: dir * Math.max(240, (chipsRef.current.clientWidth || 0) * 0.6), behavior: "smooth" });
    const [sort, setSort] = useState("category");
    const [view, setView] = useState("grid");
    const [showDrafts, setShowDrafts] = useState(false);
    const [saved, setSaved] = useState(() => new Set());
    const [preview, setPreview] = useState(null);
    useEffect(() => { setSaved(readSaved()); }, []);

    const cats = useMemo(() => [...new Set(TEMPLATES.map(x => x.cat))], []);
    const toggleSaved = id => setSaved(prev => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id); else next.add(id);
        writeSaved(next);
        return next;
    });

    const q = search.trim().toLowerCase();
    const shown = TEMPLATES
        .filter(x => cat === "All" || (cat === "Saved" ? saved.has(x.id) : x.cat === cat))
        .filter(x => !q || [x.name, x.desc, x.law, x.cat].some(v => String(v || "").toLowerCase().includes(q)))
        .sort((a, b) => sort === "name" ? a.name.localeCompare(b.name)
            : (cats.indexOf(a.cat) - cats.indexOf(b.cat)) || a.name.localeCompare(b.name));
    const filtered = cat !== "All" || q;
    const clear = () => { setCat("All"); setSearch(""); };
    const where = cat === "All" ? "in all categories" : cat === "Saved" ? "in saved" : `in ${cat}`;
    const draftWord = drafts.length ? `${drafts.length} saved — continue where you left off` : "No saved drafts yet";

    return (
        <div data-drafting-home data-drafting-theme data-mode={mode}>
            <style>{`${DRAFTING_TOKENS_CSS}\n${DRAFTING_HOME_CSS}`}</style>
            <div className="dh-wrap">
                <div className="dh-topbar">
                    <nav className="dh-crumbs" aria-label="Breadcrumb">Documents <span aria-hidden="true">/</span> <b>Legal drafting</b></nav>
                    <div className="dh-topbar-right">
                        <button type="button" className="dh-btn dh-pill" data-theme-toggle onClick={toggle}
                            aria-label={mode === "dark" ? "Switch to light theme" : "Switch to dark theme"}>
                            <Icon d={mode === "dark" ? I.sun : I.moon} size={16} />Theme
                        </button>
                        <div className="dh-acct" data-account>
                            <span className="dh-avatar" aria-hidden="true">{initials}</span>
                            <span style={{ minWidth: 0 }}>
                                <b>{displayName}</b>
                                <small>Advocate</small>
                            </span>
                        </div>
                    </div>
                </div>

                <div className="dh-head">
                    <div>
                        <h1>Document <span className="dh-accent">templates</span></h1>
                        <p>Court-ready starting points for Pakistani practice, each naming the law it is drafted under. <b>{TEMPLATES.length}</b> templates across {cats.length} categories.</p>
                    </div>
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                        <button type="button" className="dh-btn" disabled data-upload-template
                            title="Uploading your own templates is not available yet">
                            <Icon d={I.upload} size={16} />Upload template<span className="dh-soon">Soon</span>
                        </button>
                        <button type="button" className="dh-btn primary" data-new-document onClick={() => onSelect(BLANK_TEMPLATE)}>
                            <Icon d={I.plus} size={16} />New document
                        </button>
                    </div>
                </div>

                <div className="dh-start">
                    <button type="button" className="dh-sc d3 blank" {...tiltHandlers()} style={{ "--c": "var(--brand-text)" }} onClick={() => onSelect(BLANK_TEMPLATE)}>
                        <span className="dh-ic"><Icon d={I.plus} size={20} /></span>
                        <span><span className="t">Blank document</span><span className="d">Start from an empty scaffold</span></span>
                        <span className="go" aria-hidden="true"><Icon d={I.arrowRight} size={16} /></span>
                    </button>
                    <button type="button" className="dh-sc d3 drafts" {...tiltHandlers()} style={{ "--c": "var(--gold)" }} aria-expanded={showDrafts} onClick={() => setShowDrafts(v => !v)}>
                        <span className="dh-ic"><Icon d={I.fileText} size={20} /></span>
                        <span><span className="t">My Drafts</span><span className="d">{draftWord}</span></span>
                        <span className="go" aria-hidden="true"><Icon d={I.arrowRight} size={16} /></span>
                    </button>
                    <button type="button" className="dh-sc d3 ai" {...tiltHandlers()} style={{ "--c": "var(--teal-ink)" }} data-draft-with-ai onClick={() => onSelect({ ...BLANK_TEMPLATE, aiFirst: true })}>
                        <span className="dh-ic"><Icon d={I.sparkles} size={20} /></span>
                        <span><span className="t">Draft with AI</span><span className="d">Describe the facts, get a draft</span></span>
                        <span className="go" aria-hidden="true"><Icon d={I.arrowRight} size={16} /></span>
                    </button>
                </div>

                {showDrafts && (
                    <section aria-label="My Drafts" className="dh-drafts">
                        <div className="dh-label">My Drafts</div>
                        {/* Two kinds of saved work, said plainly: a draft here is work in
                            progress you can keep editing; "Save to Documents" makes a fixed,
                            hashed PDF that lives in the Vault. */}
                        <div data-drafts-vs-vault style={{ fontSize: 13, color: "var(--muted)" }}>
                            Drafts are work in progress. Fixed copies saved with “Save to Documents” are in your{" "}
                            <button type="button" className="dh-link" data-open-vault onClick={() => setPage?.("vault")}>Vault</button>.
                        </div>
                        {drafts.length === 0 && <div className="dh-empty" style={{ padding: "20px 16px" }}>No saved drafts yet — open a template and choose “Save Draft”.</div>}
                        {drafts.map(d => (
                            <div key={d.id} className="dh-draft">
                                <span className="dh-ic" style={{ width: 36, height: 36, "--c": "var(--gold)" }}><Icon d={I.fileText} size={17} /></span>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{d.title}</div>
                                    <div style={{ fontSize: 12.5, color: "var(--muted)" }}>
                                        Last saved {d.updated_at ? new Date(d.updated_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "—"}
                                    </div>
                                </div>
                                <button type="button" className="dh-btn" style={{ height: 34 }} onClick={() => onOpenDraft(d)}>Open</button>
                                <button type="button" className="dh-btn" style={{ height: 34 }} onClick={() => onDeleteDraft(d.id)}>Delete</button>
                            </div>
                        ))}
                    </section>
                )}

                <div className="dh-toolbar">
                    <div className="dh-row">
                        <label className="dh-search">
                            <Icon d={I.search} size={17} />
                            <span style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>Search templates</span>
                            <input type="search" value={search} onChange={e => setSearch(e.target.value)}
                                placeholder="Search by name, law or keyword (e.g. khula, Order VII)" />
                        </label>
                        <label style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }} htmlFor="dh-sort">Sort templates</label>
                        <select id="dh-sort" className="dh-select" value={sort} onChange={e => setSort(e.target.value)}>
                            <option value="category">By category</option>
                            <option value="name">Name A–Z</option>
                        </select>
                        <div className="dh-seg" role="group" aria-label="Layout">
                            <button type="button" aria-label="Grid view" aria-pressed={view === "grid"} onClick={() => setView("grid")}><Icon d={I.grid} size={16} /></button>
                            <button type="button" aria-label="List view" aria-pressed={view === "list"} onClick={() => setView("list")}><Icon d={I.list} size={16} /></button>
                        </div>
                    </div>
                    <div className={`dh-chipbar${edges.l ? " fl" : ""}${edges.r ? " fr" : ""}`}>
                    {edges.l && <button type="button" className="dh-chev l" aria-label="Scroll categories left" onClick={() => nudge(-1)}><Icon d={I.arrowRight} size={16} style={{ transform: "rotate(180deg)" }} /></button>}
                    <div className="dh-chips" role="group" aria-label="Categories" ref={chipsRef} onScroll={readEdges}>
                        <button type="button" className="dh-chip" aria-pressed={cat === "All"} onClick={() => setCat("All")}>All <span className="n">{TEMPLATES.length}</span></button>
                        <button type="button" className="dh-chip" aria-pressed={cat === "Saved"} onClick={() => setCat("Saved")} style={{ "--c": "var(--gold)" }}><span className="sw" />Saved <span className="n">{saved.size}</span></button>
                        {cats.map(c => (
                            <button key={c} type="button" className="dh-chip" aria-pressed={cat === c} onClick={() => setCat(c)} style={{ "--c": catColor(c) }}>
                                <span className="sw" />{c} <span className="n">{TEMPLATES.filter(x => x.cat === c).length}</span>
                            </button>
                        ))}
                        {MORE_CATS.map(([c]) => (
                            <button key={c} type="button" className="dh-chip zero" data-empty-category aria-pressed={cat === c} onClick={() => setCat(c)} style={{ "--c": catColor(c) }}>
                                <span className="sw" />{c} <span className="n">0</span>
                            </button>
                        ))}
                    </div>
                    {edges.r && <button type="button" className="dh-chev r" aria-label="Scroll categories right" onClick={() => nudge(1)}><Icon d={I.arrowRight} size={16} /></button>}
                    </div>
                </div>

                <div className="dh-result">
                    <span data-result-line>Showing <b>{shown.length}</b> of {TEMPLATES.length} {where}</span>
                    {filtered && <button type="button" className="dh-link" onClick={clear}>Clear filters</button>}
                </div>

                {shown.length === 0 ? (
                    <div className="dh-empty">
                        {MORE_COLOR[cat] && !q ? (<>
                            <h3>No {cat} templates yet</h3>
                            <div>This part of the library is still being written. Meanwhile, start from a Blank document or Draft with AI.</div>
                        </>) : (<>
                            <h3>{cat === "Saved" && !q ? "No saved templates yet" : "No templates match"}</h3>
                            <div>{cat === "Saved" && !q ? "Use the bookmark on a card to keep it here." : `Nothing matches “${search}”. Try a name or a law.`}</div>
                        </>)}
                    </div>
                ) : (
                    <div className={`dh-grid${view === "list" ? " list" : ""}`} data-template-grid>
                        {shown.map(x => (
                            <article key={x.id} className="dh-card" data-template={x.id} style={{ "--c": catColor(x.cat) }}>
                                <div className="dh-thumb" aria-hidden="true">
                                    <div className="dh-paper"><i className="h" /><i /><i /><i className="s" /><i /><i className="xs" /></div>
                                    <span className="dh-seal" />
                                    <span className="dh-lang"><span>EN</span></span>
                                </div>
                                <button type="button" className="dh-bm" aria-pressed={saved.has(x.id)}
                                    aria-label={saved.has(x.id) ? `Remove ${x.name} from saved` : `Save ${x.name}`}
                                    onClick={() => toggleSaved(x.id)}>
                                    <Icon d={I.bookmark} size={15} />
                                </button>
                                <div className="dh-body">
                                    <div>
                                        <span className="dh-cat">{x.cat}</span>
                                        <h3>{x.name}</h3>
                                        <p>{x.desc}</p>
                                    </div>
                                    <div className="dh-meta">
                                        <span className="law">{x.law}</span>
                                        <span className="pp">{x.id === BLANK_TEMPLATE.id ? "Your wording" : "Starter body"}</span>
                                    </div>
                                </div>
                                <div className="dh-actions">
                                    <button type="button" className="dh-btn ghost" onClick={() => setPreview(x)}>Preview</button>
                                    <button type="button" className="dh-btn use" onClick={() => onSelect(x)}>Use template</button>
                                </div>
                            </article>
                        ))}
                    </div>
                )}

                {/* Persistent, unlike the editor's in-session "Saved" state: this
                    reads the server every time the page mounts. */}
                <MyDocuments t={t} />
            </div>
            {preview && <PreviewDialog tmpl={preview} mode={mode} onClose={() => setPreview(null)}
                onUse={tmpl => { setPreview(null); onSelect(tmpl); }} />}
        </div>
    );
}
