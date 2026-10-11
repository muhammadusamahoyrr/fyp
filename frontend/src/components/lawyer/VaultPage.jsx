'use client';
/* The lawyer's Document Vault (2026-10-09): the documents a lawyer saved from
 * the drafter, organised into folders.
 *
 * ON THE LAWYER DOCUMENT THEME. Same palette, type and motion as the other
 * lawyer document screens (draftingTheme.js; DraftingHome, the review inbox),
 * built from the lawyer's own UI layer so it never reaches a client screen
 * (tests/role_boundaries.test.mjs, tests/docs_isolation.test.mjs).
 *
 * WHAT IS REAL
 *   - the list: the lawyer's OWN documents (GET /documents/v2/mine);
 *   - folders: create, rename, delete, file a document (services/document_folders.py);
 *     deleting a folder never deletes a document -- they go back to "no folder";
 *   - delete with "Recently deleted" and restore, for the lawyer's own documents;
 *   - preview and download of the exact revision a row names.
 * "Upload file" has no backend yet: shown disabled and labelled. */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
    myDocumentsV2, downloadDocumentFile, listDocumentFoldersV2, createDocumentFolderV2,
    renameDocumentFolderV2, deleteDocumentFolderV2, moveDocumentToFolderV2,
} from "@/lib/api.js";
import { useMyDocuments, rowActions, DOCUMENTS_UNAVAILABLE } from "@/lib/useMyDocuments.js";
import { documentStatusView } from "@/lib/documentStatus.js";
import { humanise } from "@/lib/fieldReview.js";
import { formatWhen } from "@/features/documents/formatWhen.js";
import { ThemeCtx as WorkspaceThemeCtx } from "@/components/shared/ui/theme.js";
import { useTheme } from "./theme.js";
import { useToast } from "./Toast.jsx";
import { ModalPortal } from "./ui.jsx";
import { DRAFTING_TOKENS_CSS, draftingMode } from "./draftingTheme.js";
import { DeleteDocumentDialog, RecentlyDeleted } from "./VaultTrash.jsx";
import VaultPreview from "./VaultPreview.jsx";
import { tiltHandlers } from "./tilt.js";

// Status colours in the palette's own terms.
const STATUS_TONE = { info: "var(--teal-ink)", ok: "var(--brand-text)", warn: "var(--gold)", danger: "var(--danger)", muted: "var(--muted)" };

/* The Vault's look: the lawyer document theme, scoped by [data-lawyer-vault]
 * (the page, and its dialogs, which render in a portal). */
export const LAWYER_VAULT_CSS = `[data-lawyer-vault]{color:var(--ink);font:15px/1.5 "Hanken Grotesk",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
[data-lawyer-vault].lv-page{flex:1;min-height:0;overflow-y:auto;background:radial-gradient(900px 360px at 25% -80px,var(--glow),transparent 70%) no-repeat,var(--bg)}
[data-lawyer-vault] *{box-sizing:border-box}
[data-lawyer-vault] button,[data-lawyer-vault] input,[data-lawyer-vault] select{font:inherit;color:inherit}
[data-lawyer-vault] :focus-visible{outline:2px solid var(--focus);outline-offset:2px}
[data-lawyer-vault] .lv-wrap{max-width:1240px;margin:0 auto;padding:22px clamp(16px,3.2vw,40px) 64px;display:grid;gap:22px}
[data-lawyer-vault] .lv-crumbs{font-size:13px;color:var(--muted)}
[data-lawyer-vault] .lv-crumbs b{color:var(--ink);font-weight:600}
[data-lawyer-vault] .lv-crumbs button{background:none;border:0;padding:0;color:var(--muted);cursor:pointer}
[data-lawyer-vault] .lv-crumbs button:hover{color:var(--hover-ink)}
[data-lawyer-vault] .lv-head{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;flex-wrap:wrap}
[data-lawyer-vault] .lv-head h1{margin:0;font:600 clamp(28px,3.4vw,38px)/1.1 "Literata",Georgia,serif;letter-spacing:-.01em}
[data-lawyer-vault] .lv-accent{background:linear-gradient(90deg,var(--brand-text),var(--teal-ink));-webkit-background-clip:text;background-clip:text;color:transparent}
[data-lawyer-vault] .lv-head p{margin:8px 0 0;color:var(--muted);max-width:62ch}
[data-lawyer-vault] .lv-btn{display:inline-flex;align-items:center;gap:8px;height:42px;padding:0 16px;border-radius:12px;border:1px solid var(--line-strong);background:var(--surface);font-weight:600;font-size:14px;white-space:nowrap;cursor:pointer;transition:border-color .15s,background .15s,color .15s}
[data-lawyer-vault] .lv-btn:hover:not(:disabled){border-color:var(--hover-line);background:var(--hover-tint);color:var(--hover-ink)}
[data-lawyer-vault] .lv-btn:disabled{opacity:.5;cursor:not-allowed}
[data-lawyer-vault] .lv-btn.danger{color:var(--danger);border-color:color-mix(in srgb,var(--danger) 35%,transparent)}
[data-lawyer-vault] .lv-btn.danger:hover:not(:disabled){background:var(--danger-soft);color:var(--danger);border-color:var(--danger)}
[data-lawyer-vault] .lv-cta{position:relative;overflow:hidden;display:inline-flex;align-items:center;gap:10px;height:48px;padding:0 22px;border-radius:14px;border:0;background:var(--brand-solid);color:var(--on-brand);font-weight:700;font-size:15px;cursor:pointer;box-shadow:0 10px 24px -12px rgba(46,196,214,.8);transition:transform .15s,box-shadow .15s}
[data-lawyer-vault] .lv-cta:hover:not(:disabled){background:var(--brand-solid-hover);transform:translateY(-1px);box-shadow:0 14px 28px -12px rgba(46,196,214,.9)}
[data-lawyer-vault] .lv-cta:disabled{opacity:.5;cursor:not-allowed}
[data-lawyer-vault] .lv-cta::after{content:"";position:absolute;top:0;bottom:0;left:0;width:40%;pointer-events:none;background:linear-gradient(90deg,transparent,rgba(255,255,255,.45),transparent);transform:translateX(-130%) skewX(-20deg)}
[data-lawyer-vault] .lv-cta:hover::after{animation:lvShine .8s ease}
[data-lawyer-vault] .lv-soon{font-size:10.5px;font-weight:700;letter-spacing:.04em;padding:1px 7px;border-radius:999px;background:var(--chip-n);color:var(--muted)}
[data-lawyer-vault] .lv-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
[data-lawyer-vault] .lv-stat,[data-lawyer-vault] .lv-folder{position:relative;border-radius:20px;overflow:hidden;border:1px solid color-mix(in srgb,var(--c) 14%,var(--line));background:radial-gradient(120% 100% at 100% 0%,color-mix(in srgb,var(--c) 13%,transparent) 0%,transparent 55%),linear-gradient(180deg,color-mix(in srgb,var(--surface) 92%,#fff 8%),var(--surface));box-shadow:0 1px 0 rgba(255,255,255,.05) inset,0 10px 24px -18px rgba(0,0,0,.65);transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
[data-lawyer-vault] .lv-stat{display:grid;grid-template-columns:auto 1fr;grid-template-areas:"ic l" "v v" "s s";column-gap:12px;align-items:center;padding:18px}
[data-lawyer-vault] .lv-stat:hover,[data-lawyer-vault] .lv-folder:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--c) 45%,var(--line));box-shadow:0 1px 0 rgba(255,255,255,.06) inset,0 18px 32px -20px color-mix(in srgb,var(--c) 70%,#000)}
[data-lawyer-vault] .lv-ic{width:40px;height:40px;flex:none;border-radius:12px;display:grid;place-items:center;color:var(--c);background:color-mix(in srgb,var(--c) 16%,transparent);box-shadow:0 0 0 1px color-mix(in srgb,var(--c) 22%,transparent) inset}
[data-lawyer-vault] .lv-ic svg{transition:transform .35s cubic-bezier(.34,1.56,.64,1)}
[data-lawyer-vault] .lv-stat .lv-ic{grid-area:ic}
[data-lawyer-vault] .lv-stat .l{grid-area:l;font-size:13.5px;font-weight:600;color:var(--muted)}
[data-lawyer-vault] .lv-stat .v{grid-area:v;font:600 32px/1 "Literata",Georgia,serif;margin:14px 0 6px}
[data-lawyer-vault] .lv-stat .s{grid-area:s;font-size:12.5px;color:var(--muted)}
[data-lawyer-vault] .lv-stat:hover .lv-ic svg{transform:translateY(-2px) scale(1.08)}
[data-lawyer-vault] .lv-tools{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
[data-lawyer-vault] .lv-search{flex:1 1 420px;display:flex;align-items:center;gap:10px;height:48px;padding:0 14px;border-radius:12px;background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow-rest)}
[data-lawyer-vault] .lv-search:hover{border-color:var(--hover-line)}
[data-lawyer-vault] .lv-search:focus-within{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-lawyer-vault] .lv-search svg{color:var(--faint);flex:none}
[data-lawyer-vault] .lv-search input{flex:1;min-width:0;border:0;outline:none;background:transparent;font-size:15px}
[data-lawyer-vault] .lv-search input::placeholder{color:var(--faint)}
[data-lawyer-vault] .lv-kbd{font-family:"JetBrains Mono",monospace;font-size:11px;color:var(--faint);border:1px solid var(--line-strong);border-bottom-width:2px;border-radius:5px;padding:0 6px;line-height:18px}
[data-lawyer-vault] .lv-sort{position:relative;display:flex;align-items:center;height:48px;border-radius:12px;background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow-rest);min-width:220px}
[data-lawyer-vault] .lv-sort:hover{border-color:var(--hover-line)}
[data-lawyer-vault] .lv-sort:focus-within{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-lawyer-vault] .lv-sort > svg{position:absolute;left:14px;color:var(--muted);pointer-events:none}
[data-lawyer-vault] .lv-sort .chev{left:auto;right:14px}
[data-lawyer-vault] .lv-sort select{appearance:none;-webkit-appearance:none;width:100%;height:100%;border:0;outline:none;background:transparent;padding:0 38px 0 42px;font-weight:600;font-size:14.5px;cursor:pointer}
[data-lawyer-vault] .lv-sort select option{background:var(--surface);color:var(--ink)}
[data-lawyer-vault] .lv-card{border-radius:18px;border:1px solid var(--line);background:var(--surface);box-shadow:var(--shadow-rest);overflow:hidden}
[data-lawyer-vault] .lv-bar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:12px 16px;border-bottom:1px solid var(--line)}
[data-lawyer-vault] .lv-tabs{display:inline-flex;gap:4px;padding:4px;border-radius:12px;background:var(--surface-2);border:1px solid var(--line)}
[data-lawyer-vault] .lv-tab{height:36px;padding:0 14px;border-radius:9px;border:0;background:transparent;color:var(--muted);font-weight:600;font-size:14px;cursor:pointer;display:inline-flex;align-items:center;gap:8px}
[data-lawyer-vault] .lv-tab:hover{color:var(--hover-ink)}
[data-lawyer-vault] .lv-tab[aria-selected="true"]{background:var(--brand-solid);color:var(--on-brand)}
[data-lawyer-vault] .lv-n{font-family:"JetBrains Mono",monospace;font-size:11px;padding:1px 7px;border-radius:999px;background:var(--chip-n)}
[data-lawyer-vault] .lv-tab[aria-selected="true"] .lv-n{background:rgba(0,0,0,.18)}
[data-lawyer-vault] .lv-filter{display:flex;align-items:center;gap:8px;font-size:13.5px;color:var(--muted)}
[data-lawyer-vault] .lv-filter b{color:var(--ink)}
[data-lawyer-vault] .lv-grid{display:grid;grid-template-columns:minmax(0,2.6fr) minmax(0,1fr) minmax(0,1.1fr) 110px 120px 190px;gap:14px;align-items:center;padding:12px 20px;position:relative}
[data-lawyer-vault] .lv-th{font-size:12px;font-weight:600;letter-spacing:.04em;color:var(--muted);background:var(--surface-2);border-bottom:1px solid var(--line);padding-block:10px}
[data-lawyer-vault] .lv-th span:last-child{text-align:right}
[data-lawyer-vault] .lv-row{border-bottom:1px solid var(--line);transition:background .15s,box-shadow .15s}
[data-lawyer-vault] .lv-row:last-child{border-bottom:0}
[data-lawyer-vault] .lv-row:hover{background:var(--hover-tint);box-shadow:inset 0 0 0 1px var(--hover-line)}
[data-lawyer-vault] .lv-row:hover .lv-name{color:var(--hover-ink)}
[data-lawyer-vault] .lv-pdf{width:34px;height:40px;flex:none;border-radius:8px;display:grid;place-items:center;font:800 9.5px "JetBrains Mono",monospace;color:#B3261E;background:#FDECEC;transition:transform .3s cubic-bezier(.34,1.56,.64,1)}
[data-lawyer-vault] .lv-row:hover .lv-pdf{transform:rotate(-6deg) translateY(-2px)}
[data-lawyer-vault] .lv-name{font:600 16px/1.3 "Literata",Georgia,serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-lawyer-vault] .lv-sub{font-size:12.5px;color:var(--muted)}
[data-lawyer-vault] .lv-chip{display:inline-flex;align-items:center;gap:6px;max-width:100%;font-size:12.5px;font-weight:600;padding:3px 10px;border-radius:999px;background:rgba(242,195,94,.13);color:var(--gold);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-lawyer-vault] .lv-pill{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:700;padding:3px 10px;border-radius:999px;white-space:nowrap}
[data-lawyer-vault] .lv-pill i{width:6px;height:6px;border-radius:50%;background:currentColor}
[data-lawyer-vault] .lv-acts{display:flex;justify-content:flex-end;gap:6px}
[data-lawyer-vault] .lv-ib{width:36px;height:36px;border-radius:11px;border:1px solid var(--line);background:var(--surface-2);color:var(--muted);display:grid;place-items:center;cursor:pointer;transition:color .15s,border-color .15s,background .15s}
[data-lawyer-vault] .lv-ib:hover:not(:disabled){color:var(--hover-ink);border-color:var(--hover-line);background:var(--hover-tint)}
[data-lawyer-vault] .lv-ib:disabled{opacity:.4;cursor:not-allowed}
[data-lawyer-vault] .lv-ib.danger:hover:not(:disabled){color:var(--danger);border-color:var(--danger);background:var(--danger-soft)}
[data-lawyer-vault] .lv-ib.k-eye:hover:not(:disabled) svg{animation:lvBlink 1.2s ease infinite}
[data-lawyer-vault] .lv-ib.k-down:hover:not(:disabled) svg{animation:lvBounce .6s ease}
[data-lawyer-vault] .lv-ib.k-move:hover:not(:disabled) svg{animation:lvNudge .5s ease}
[data-lawyer-vault] .lv-ib.k-trash:hover:not(:disabled) svg{animation:lvShake .45s ease}
[data-lawyer-vault] .lv-ib.k-pen:hover svg{animation:lvNudge .5s ease}
[data-lawyer-vault] .lv-folders{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px;padding:18px}
[data-lawyer-vault] .lv-folder{display:flex;flex-direction:column;gap:12px;padding:16px}
[data-lawyer-vault] .lv-folder .open{display:flex;align-items:center;gap:12px;padding:0;border:0;background:transparent;text-align:left;cursor:pointer;min-width:0}
[data-lawyer-vault] .lv-folder:hover .lv-ic svg{transform:translateY(-2px) rotate(-6deg) scale(1.08)}
[data-lawyer-vault] .lv-folder .nm{display:block;font:600 16px/1.3 "Literata",Georgia,serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-lawyer-vault] .lv-new{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;min-height:128px;border-radius:20px;border:1.5px dashed var(--line-strong);background:transparent;color:var(--muted);font-weight:700;cursor:pointer;transition:border-color .15s,color .15s,background .15s}
[data-lawyer-vault] .lv-new:hover{border-color:var(--hover-line);color:var(--hover-ink);background:var(--hover-tint)}
[data-lawyer-vault] .lv-new span{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;background:var(--brand-soft);color:var(--brand-text);transition:transform .35s cubic-bezier(.34,1.56,.64,1)}
[data-lawyer-vault] .lv-new:hover span{transform:rotate(90deg)}
[data-lawyer-vault] .lv-cta:hover svg{animation:lvNudge .5s ease}
[data-lawyer-vault] .lv-empty{padding:48px 20px;text-align:center;color:var(--muted)}
[data-lawyer-vault] .lv-empty b{display:block;font:600 20px "Literata",Georgia,serif;color:var(--ink);margin:12px 0 6px}
[data-lawyer-vault] .lv-foot{display:flex;align-items:center;gap:10px;padding:12px 20px 14px;font-size:13px;color:var(--muted);border-top:1px solid var(--line)}
[data-lawyer-vault].lv-backdrop{position:fixed;inset:0;z-index:1000;background:rgba(4,14,17,.62);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);display:grid;place-items:start center;padding-top:14vh}
[data-lawyer-vault] .lv-dialog{width:min(470px,calc(100vw - 32px));padding:24px;border-radius:20px;background:var(--surface);border:1px solid var(--line-strong);box-shadow:0 30px 60px -30px rgba(0,0,0,.8);animation:lvIn .22s cubic-bezier(.34,1.56,.64,1)}
[data-lawyer-vault] .lv-dialog h2{margin:0 0 14px;font:600 20px/1.25 "Literata",Georgia,serif}
[data-lawyer-vault] .lv-dialog label.f{display:block;font-size:13.5px;font-weight:600;margin-bottom:6px}
[data-lawyer-vault] .lv-dialog input[type="text"]{width:100%;height:46px;padding:0 14px;border-radius:12px;border:1px solid var(--line-strong);background:var(--input);font-size:15px;outline:none}
[data-lawyer-vault] .lv-dialog input[type="text"]:focus{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-lawyer-vault] .lv-opt{display:flex;gap:10px;align-items:center;min-height:44px;padding:0 12px;border-radius:12px;border:1px solid var(--line);cursor:pointer;transition:border-color .15s,background .15s}
[data-lawyer-vault] .lv-opt:hover{border-color:var(--hover-line);background:var(--hover-tint)}
[data-lawyer-vault] .lv-opt.on{border-color:var(--brand-text);background:var(--brand-soft)}
[data-lawyer-vault] .lv-problem{margin-top:10px;color:var(--danger);font-size:13.5px}
[data-lawyer-vault] .lv-dialog .row{display:flex;gap:10px;justify-content:flex-end;margin-top:20px}
/* 3D (2026-10-09). Cards tilt toward the pointer and their icon lifts off (tilt.js). */
[data-lawyer-vault] .d3{transform:perspective(900px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg));transition:transform .2s ease-out,box-shadow .18s ease,border-color .18s ease}
[data-lawyer-vault] .d3:hover{transform:perspective(900px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg)) translateY(-3px)}
[data-lawyer-vault] .lv-stat.d3 .lv-ic{position:relative;transition:transform .45s cubic-bezier(.34,1.56,.64,1),box-shadow .3s}
[data-lawyer-vault] .lv-stat.d3 .lv-ic::before{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;opacity:0;transition:opacity .2s;background:radial-gradient(circle at calc((var(--px,0) + .5) * 100%) calc((var(--py,0) + .5) * 100%),rgba(255,255,255,.5),transparent 60%)}
[data-lawyer-vault] .lv-stat.d3:hover .lv-ic{transform:translate(calc(var(--px,0) * 6px),calc(var(--py,0) * 6px - 6px)) scale(1.16) rotate(-5deg);box-shadow:0 0 0 1px color-mix(in srgb,var(--c) 40%,transparent) inset,0 16px 22px -10px color-mix(in srgb,var(--c) 75%,#000),0 4px 8px -4px rgba(0,0,0,.5)}
[data-lawyer-vault] .lv-stat.d3:hover .lv-ic::before{opacity:1}
[data-lawyer-vault] .lv-stat.d3:hover .lv-ic svg{transform:translate(calc(var(--px,0) * 7px),calc(var(--py,0) * 7px)) scale(1.06)}
/* The folder that opens: back, a page, and a front flap that swings forward in 3D. */
[data-lawyer-vault] .lv-f3d{position:relative;width:62px;height:50px;flex:none;perspective:170px;margin:12px 4px 0 0;transition:transform .45s cubic-bezier(.34,1.56,.64,1)}
[data-lawyer-vault] .lv-f3d::after{content:"";position:absolute;left:8%;right:8%;bottom:-9px;height:8px;border-radius:50%;background:rgba(0,0,0,.45);filter:blur(4px);transition:transform .45s,opacity .45s;opacity:.6}
[data-lawyer-vault] .lv-f3d i{position:absolute;display:block}
[data-lawyer-vault] .lv-f3d .bk{inset:0;border-radius:6px 11px 11px 11px;background:linear-gradient(180deg,color-mix(in srgb,var(--gold) 55%,#000),color-mix(in srgb,var(--gold) 70%,#000))}
[data-lawyer-vault] .lv-f3d .bk::before{content:"";position:absolute;left:0;top:-7px;width:25px;height:10px;border-radius:5px 5px 0 0;background:color-mix(in srgb,var(--gold) 55%,#000)}
[data-lawyer-vault] .lv-f3d .pg{left:8px;right:9px;top:4px;height:38px;border-radius:4px;background:repeating-linear-gradient(180deg,transparent 0 6px,rgba(40,60,70,.25) 6px 7px) 6px 9px/68% 70% no-repeat,#FBF8EF;box-shadow:0 2px 5px rgba(0,0,0,.3);transition:transform .5s cubic-bezier(.34,1.56,.64,1)}
[data-lawyer-vault] .lv-f3d .pg.b{left:14px;right:4px;top:6px;background:#E9E2D0;transition-delay:.05s}
[data-lawyer-vault] .lv-f3d .fr{left:0;right:0;bottom:0;height:37px;border-radius:6px 6px 11px 11px;transform-origin:50% 100%;background:linear-gradient(180deg,color-mix(in srgb,var(--gold) 90%,#fff),var(--gold));box-shadow:0 -1px 0 rgba(255,255,255,.4) inset,0 10px 16px -8px rgba(0,0,0,.6);transition:transform .5s cubic-bezier(.34,1.56,.64,1),filter .5s}
[data-lawyer-vault] .lv-folder:hover .lv-f3d{transform:translateY(-4px) scale(1.06)}
[data-lawyer-vault] .lv-folder:hover .lv-f3d::after{transform:scale(.8);opacity:.35}
[data-lawyer-vault] .lv-folder:hover .lv-f3d .pg{transform:translateY(-20px) rotate(-8deg)}
[data-lawyer-vault] .lv-folder:hover .lv-f3d .pg.b{transform:translateY(-15px) translateX(3px) rotate(10deg)}
[data-lawyer-vault] .lv-folder:hover .lv-f3d .fr{transform:rotateX(-62deg);filter:brightness(1.08)}
/* Download: a 3D press, the arrow drops in, a burst says it's done. */
[data-lawyer-vault] .lv-ib{position:relative}
[data-lawyer-vault] .lv-ib.k-down:active:not(:disabled){transform:perspective(200px) translateZ(-14px)}
[data-lawyer-vault] .lv-ib.k-down.hit svg,[data-lawyer-vault] .lv-ib.k-down.hit:hover:not(:disabled) svg{animation:lvDrop .55s cubic-bezier(.34,1.56,.64,1)}
[data-lawyer-vault] .lv-burst{position:absolute;left:50%;top:50%;width:0;height:0;pointer-events:none}
[data-lawyer-vault] .lv-burst i{position:absolute;left:-3px;top:-3px;width:6px;height:6px;border-radius:50%;background:var(--brand-text);opacity:0;animation:lvBurst .6s ease-out forwards;transform:rotate(var(--a)) translateY(0)}
[data-lawyer-vault] .lv-burst i:nth-child(even){background:var(--gold);width:4px;height:4px}
/* Create Folder: a raised 3D key that presses down. */
[data-lawyer-vault] .lv-cta.k3d{box-shadow:0 4px 0 color-mix(in srgb,var(--brand-solid) 55%,#000),0 12px 24px -12px rgba(46,196,214,.8)}
[data-lawyer-vault] .lv-cta.k3d:hover:not(:disabled){transform:translateY(-2px);box-shadow:0 6px 0 color-mix(in srgb,var(--brand-solid) 55%,#000),0 16px 28px -12px rgba(46,196,214,.9)}
[data-lawyer-vault] .lv-cta.k3d:active:not(:disabled){transform:translateY(3px);box-shadow:0 1px 0 color-mix(in srgb,var(--brand-solid) 55%,#000),0 6px 14px -10px rgba(46,196,214,.8)}
@keyframes lvDrop{0%{transform:translateY(-9px);opacity:0}60%{transform:translateY(2px);opacity:1}100%{transform:none}}
@keyframes lvBurst{0%{opacity:1;transform:rotate(var(--a)) translateY(0) scale(1)}100%{opacity:0;transform:rotate(var(--a)) translateY(-22px) scale(.4)}}
@keyframes lvShine{to{transform:translateX(360%) skewX(-20deg)}}
@keyframes lvBlink{0%,42%,52%,100%{transform:scaleY(1)}47%{transform:scaleY(.1)}}
@keyframes lvBounce{0%,100%{transform:translateY(0)}40%{transform:translateY(3px)}70%{transform:translateY(-1px)}}
@keyframes lvNudge{0%,100%{transform:translateX(0) rotate(0)}40%{transform:translateX(2px) rotate(-8deg)}}
@keyframes lvShake{0%,100%{transform:rotate(0)}25%{transform:rotate(-12deg)}50%{transform:rotate(10deg)}75%{transform:rotate(-6deg)}}
@keyframes lvIn{from{opacity:0;transform:translateY(8px) scale(.98)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){[data-lawyer-vault] *,[data-lawyer-vault] *::after{transition:none!important;animation:none!important}}`;

const SORTS = [["newest", "Newest first"], ["oldest", "Oldest first"], ["name", "Name (A–Z)"]];
export function sortRows(rows, how) {
    const when = r => new Date(r.updated_at || r.created_at || 0).getTime() || 0;
    const copy = [...rows];
    if (how === "oldest") return copy.sort((a, b) => when(a) - when(b));
    if (how === "name") return copy.sort((a, b) => (a.title || "").localeCompare(b.title || ""));
    return copy.sort((a, b) => when(b) - when(a));
}
export function addedThisWeek(items, now = new Date()) {
    const since = now.getTime() - 7 * 86400000;
    return (items || []).filter(r => {
        const d = new Date(r.created_at || r.updated_at || 0).getTime();
        return !Number.isNaN(d) && d >= since && d <= now.getTime();
    }).length;
}

const svg = (d, s = 18) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>;
const G = {
    folder: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />,
    folderPlus: <><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M12 10.5v5M9.5 13h5" /></>,
    folderMove: <><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M10 13h6M13.5 10.5 16 13l-2.5 2.5" /></>,
    cloud: <><path d="M7 18a5 5 0 0 1-.6-9.96A6 6 0 0 1 18 9a4.5 4.5 0 0 1-.5 9" /><path d="M12 12v7M9 15l3-3 3 3" /></>,
    stack: <><path d="M12 3 3 8l9 5 9-5z" /><path d="m3 13 9 5 9-5" /></>,
    search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>,
    sort: <path d="M4 7h16M7 12h10M10 17h4" />,
    chev: <path d="m6 9 6 6 6-6" />,
    eye: <><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></>,
    down: <><path d="M12 4v11M7 10l5 5 5-5" /><path d="M5 20h14" /></>,
    trash: <><path d="M4 7h16M10 11v6M14 11v6" /><path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3" /></>,
    pencil: <><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></>,
    plus: <path d="M12 5v14M5 12h14" />,
};
const hidden = { position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" };

/* A dialog in the Vault's theme (it renders in a portal, so it carries the scope itself). */
function VaultDialog({ mode, busy, onClose, labelledBy, children, ...rest }) {
    return (
        <ModalPortal>
            <div data-lawyer-vault data-drafting-theme data-mode={mode} className="lv-backdrop"
                onMouseDown={e => { if (e.target === e.currentTarget && !busy) onClose(); }}>
                <div role="dialog" aria-modal="true" aria-labelledby={labelledBy} className="lv-dialog" {...rest}>{children}</div>
            </div>
        </ModalPortal>
    );
}

function FolderNameDialog({ mode, title, initial = "", submitLabel, onSubmit, onClose }) {
    const [name, setName] = useState(initial);
    const [problem, setProblem] = useState(null);
    const [busy, setBusy] = useState(false);
    const submit = async e => {
        e.preventDefault();
        if (busy) return;
        setBusy(true);
        const issue = await onSubmit(name);
        setBusy(false);
        if (issue) setProblem(issue);
    };
    return (
        <VaultDialog mode={mode} busy={busy} onClose={onClose} labelledBy="lvf-title" data-folder-dialog>
            <form onSubmit={submit}>
                <h2 id="lvf-title">{title}</h2>
                <label className="f" htmlFor="lvf-name">Folder name</label>
                <input id="lvf-name" type="text" autoFocus value={name} maxLength={60}
                    onChange={e => { setName(e.target.value); setProblem(null); }} placeholder="e.g. Bail matters" />
                {problem && <div role="alert" data-folder-problem className="lv-problem">{problem}</div>}
                <div className="row">
                    <button type="button" className="lv-btn" onClick={onClose} disabled={busy}>Cancel</button>
                    <button type="submit" className="lv-cta" style={{ height: 42 }} disabled={busy || !name.trim()}>{busy ? "Saving…" : submitLabel}</button>
                </div>
            </form>
        </VaultDialog>
    );
}

function ConfirmFolderDelete({ mode, folder, onConfirm, onClose }) {
    const [busy, setBusy] = useState(false);
    const [problem, setProblem] = useState(null);
    const go = async () => {
        if (busy) return;
        setBusy(true);
        const issue = await onConfirm();
        setBusy(false);
        if (issue) setProblem(issue);
    };
    const n = folder.document_count || 0;
    return (
        <VaultDialog mode={mode} busy={busy} onClose={onClose} labelledBy="lvfd-title" data-folder-delete-dialog>
            <h2 id="lvfd-title">Delete the folder “{folder.name}”?</h2>
            <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.6, color: "var(--muted)" }}>
                {n ? `Its ${n} document${n === 1 ? "" : "s"} stay${n === 1 ? "s" : ""} in your Vault, in no folder. ` : ""}
                No document is deleted.
            </p>
            {problem && <div role="alert" className="lv-problem">{problem}</div>}
            <div className="row">
                <button type="button" className="lv-btn" onClick={onClose} disabled={busy}>Keep it</button>
                <button type="button" className="lv-btn danger" onClick={go} disabled={busy}>{busy ? "Deleting…" : "Delete folder"}</button>
            </div>
        </VaultDialog>
    );
}

/* Move one document. "New folder…" (2026-10-10) creates the folder and files
 * the document into it in one step, so a lawyer with no folder yet is not sent
 * back out of the dialog to make one first. */
function MoveDialog({ mode, row, folders, onMove, onCreate, onClose }) {
    const [choice, setChoice] = useState(row.folder_id || "");
    const [busy, setBusy] = useState(false);
    const [problem, setProblem] = useState(null);
    const [newName, setNewName] = useState(null);           // null: not making a folder
    const submit = async e => {
        e.preventDefault();
        if (busy) return;
        setBusy(true);
        let target = choice || null;
        if (newName !== null) {
            const made = await onCreate(newName);
            if (made.error) { setBusy(false); setProblem(made.error); return; }
            target = made.folder.id;
        }
        const issue = await onMove(target);
        setBusy(false);
        if (issue) setProblem(issue);
    };
    const making = newName !== null;
    return (
        <VaultDialog mode={mode} busy={busy} onClose={onClose} labelledBy="lvm-title" data-move-dialog>
            <form onSubmit={submit}>
                <h2 id="lvm-title">Move “{row.title || "Untitled document"}”</h2>
                <fieldset style={{ border: "none", margin: 0, padding: 0, display: "grid", gap: 8, maxHeight: 300, overflowY: "auto" }}>
                    <legend className="lv-sub" style={{ marginBottom: 8 }}>Choose a folder</legend>
                    {[{ id: "", name: "No folder" }, ...folders].map(f => (
                        <label key={f.id || "none"} className={`lv-opt${!making && choice === f.id ? " on" : ""}`}>
                            <input type="radio" name="lvm-folder" value={f.id} checked={!making && choice === f.id} onChange={() => { setChoice(f.id); setNewName(null); setProblem(null); }} style={{ accentColor: "#3EE0A1" }} />
                            <span style={{ display: "flex", color: f.id ? "var(--gold)" : "var(--faint)" }}>{svg(G.folder, 17)}</span>
                            {f.name}
                        </label>
                    ))}
                    {making ? (
                        <label className="lv-opt on" data-move-new-folder>
                            <span style={{ display: "flex", color: "var(--brand-text)" }}>{svg(G.folderPlus, 17)}</span>
                            <span style={hidden}>New folder name</span>
                            <input type="text" autoFocus value={newName} maxLength={60} placeholder="New folder name, e.g. Bail matters"
                                onChange={e => { setNewName(e.target.value); setProblem(null); }}
                                style={{ flex: 1, height: 36, border: 0, background: "transparent", boxShadow: "none", padding: 0 }} />
                        </label>
                    ) : (
                        <button type="button" className="lv-opt" data-move-new-folder-start onClick={() => { setNewName(""); setProblem(null); }}
                            style={{ background: "transparent", color: "var(--brand-text)", fontWeight: 600, width: "100%", textAlign: "left" }}>
                            {svg(G.plus, 17)} New folder…
                        </button>
                    )}
                </fieldset>
                {problem && <div role="alert" className="lv-problem">{problem}</div>}
                <div className="row">
                    <button type="button" className="lv-btn" onClick={onClose} disabled={busy}>Cancel</button>
                    <button type="submit" className="lv-cta" style={{ height: 42 }}
                        disabled={busy || (making ? !newName.trim() : choice === (row.folder_id || ""))}>
                        {busy ? "Moving…" : making ? "Create & move" : "Move"}
                    </button>
                </div>
            </form>
        </VaultDialog>
    );
}

/* ADD DOCUMENTS TO A FOLDER (2026-10-10). A matter has several papers (a plaint,
 * an affidavit, a notice): filing them one row at a time from "All documents"
 * took a dialog per document. This lists every one of the lawyer's documents
 * not already in the folder -- with where each is now -- to pick several at
 * once. Filing only moves `folder_id` (PUT /documents/v2/{id}/folder): nothing
 * is copied or deleted, and a document is in one folder at a time. Moves run
 * one after another; any that fail are named and stay selected. (The client
 * Vault has its own copy: client/documents/DocsVault.jsx.) */
const PICK_PAGES = 4;                  // up to 4 × 50 documents, the newest first
async function loadAllDocuments() {
    const out = [];
    let cursor = null;
    for (let i = 0; i < PICK_PAGES; i += 1) {
        const res = await myDocumentsV2({ cursor, limit: 50 });
        if (res?.error) return { error: res.error.message || "Could not load your documents." };
        out.push(...(res.data?.items || []));
        cursor = res.data?.has_more ? res.data.next_cursor : null;
        if (!cursor) return { items: out, more: false };
    }
    return { items: out, more: true };
}

function AddDocumentsDialog({ mode, folder, folderName, fresh = false, onDone, onClose }) {
    const [list, setList] = useState(null);                 // null: loading
    const [more, setMore] = useState(false);
    const [problem, setProblem] = useState(null);
    const [q, setQ] = useState("");
    const [picked, setPicked] = useState(() => new Set());
    const [busy, setBusy] = useState(false);
    const [progress, setProgress] = useState(0);
    useEffect(() => {
        let live = true;
        loadAllDocuments().then(res => {
            if (!live) return;
            if (res.error) { setProblem(res.error); setList([]); return; }
            setList(res.items.filter(d => d.folder_id !== folder.id));
            setMore(res.more);
        });
        return () => { live = false; };
    }, [folder.id]);
    const shown = useMemo(() => {
        const s = q.trim().toLowerCase();
        return (list || []).filter(d => !s || (d.title || "").toLowerCase().includes(s)
            || (d.template_type || "").toLowerCase().includes(s) || (folderName[d.folder_id] || "").toLowerCase().includes(s));
    }, [list, q, folderName]);
    const allShown = shown.length > 0 && shown.every(d => picked.has(d.id));
    const toggle = id => setPicked(p => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
    const toggleAll = () => setPicked(p => {
        const n = new Set(p);
        shown.forEach(d => (allShown ? n.delete(d.id) : n.add(d.id)));
        return n;
    });
    const submit = async e => {
        e.preventDefault();
        if (busy || picked.size === 0) return;
        setBusy(true);
        setProblem(null);
        const ids = [...picked];
        const failed = [];
        for (let i = 0; i < ids.length; i += 1) {
            setProgress(i + 1);
            const res = await moveDocumentToFolderV2(ids[i], folder.id);
            if (res?.error) failed.push(ids[i]);
        }
        setBusy(false);
        const moved = ids.length - failed.length;
        if (failed.length) {
            // The ones that worked leave the list; the failures stay selected to retry.
            const title = id => (list.find(d => d.id === id)?.title || "Untitled document");
            setList(l => l.filter(d => !ids.includes(d.id) || failed.includes(d.id)));
            setPicked(new Set(failed));
            setProblem(`${failed.length} could not be added: ${failed.map(title).join(", ")}. Try again.`);
            if (moved) onDone(moved, false);
            return;
        }
        onDone(moved, true);
    };
    const n = picked.size;
    return (
        <VaultDialog mode={mode} busy={busy} onClose={onClose} labelledBy="lva-title" data-add-documents-dialog style={{ width: "min(560px, calc(100vw - 32px))" }}>
            <form onSubmit={submit}>
                <h2 id="lva-title" style={{ marginBottom: 6 }}>{fresh ? `“${folder.name}” is ready. Add documents?` : `Add documents to “${folder.name}”`}</h2>
                <p className="lv-sub" style={{ margin: "0 0 14px", fontSize: 13.5, lineHeight: 1.55 }}>
                    Pick the papers that belong to this matter. Each one moves here from where it is now — nothing is copied or deleted.
                </p>
                {list === null ? (
                    <div aria-busy="true" className="lv-empty" style={{ padding: 28 }}>Loading your documents…</div>
                ) : list.length === 0 && !problem ? (
                    <div className="lv-empty" style={{ padding: 28 }}>
                        <b>{fresh ? "No documents to add yet" : "Nothing left to add"}</b>
                        {fresh ? "Documents you save from Legal drafting appear in your Vault; file them here from there." : "Every one of your documents is already in this folder."}
                    </div>
                ) : (<>
                    <label className="lv-search" style={{ height: 42, marginBottom: 10, boxShadow: "none" }}>
                        {svg(G.search, 16)}
                        <span style={hidden}>Search your documents</span>
                        <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Search by name, type or folder" style={{ fontSize: 14 }} />
                    </label>
                    {shown.length > 0 && (
                        <label className="lv-opt" style={{ minHeight: 38, marginBottom: 8, borderStyle: "dashed" }}>
                            <input type="checkbox" checked={allShown} onChange={toggleAll} style={{ accentColor: "#3EE0A1" }} data-add-all />
                            <span style={{ fontWeight: 600 }}>{allShown ? "Clear the ones shown" : `Select all shown (${shown.length})`}</span>
                        </label>
                    )}
                    <div role="group" aria-label="Your documents" style={{ display: "grid", gap: 8, maxHeight: 300, overflowY: "auto", paddingRight: 2 }} data-lenis-prevent>
                        {shown.map(d => (
                            <label key={d.id} className={`lv-opt${picked.has(d.id) ? " on" : ""}`} data-add-doc={d.id} style={{ minHeight: 54 }}>
                                <input type="checkbox" checked={picked.has(d.id)} onChange={() => toggle(d.id)} style={{ accentColor: "#3EE0A1" }} />
                                <span className="lv-pdf" aria-hidden="true" style={{ width: 26, height: 32, fontSize: 8 }}>PDF</span>
                                <span style={{ minWidth: 0, flex: 1 }}>
                                    <span style={{ display: "block", fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{d.title || "Untitled document"}</span>
                                    <span className="lv-sub">
                                        {d.template_type ? humanise(d.template_type) : "Document"} · {folderName[d.folder_id] ? `now in “${folderName[d.folder_id]}”` : "no folder"}
                                    </span>
                                </span>
                            </label>
                        ))}
                        {shown.length === 0 && <div className="lv-sub" style={{ padding: 12 }}>No document matches “{q}”.</div>}
                    </div>
                    {more && <div className="lv-sub" style={{ marginTop: 8 }}>Showing your {list.length} newest documents.</div>}
                </>)}
                {problem && <div role="alert" className="lv-problem">{problem}</div>}
                <div className="row">
                    <button type="button" className="lv-btn" onClick={onClose} disabled={busy}>{fresh ? "Skip for now" : "Cancel"}</button>
                    <button type="submit" className="lv-cta" style={{ height: 42 }} disabled={busy || n === 0} data-add-submit>
                        {busy ? `Adding ${progress} of ${n}…` : n ? `Add ${n} document${n === 1 ? "" : "s"}` : "Add documents"}
                    </button>
                </div>
            </form>
        </VaultDialog>
    );
}

function VaultScreen() {
    const { t } = useTheme();
    const mode = draftingMode(t);
    const toast = useToast();
    const [tab, setTab] = useState("all");
    const [query, setQuery] = useState("");
    const [sort, setSort] = useState(null);
    const searchRef = useRef(null);
    // The folder the list is narrowed to (null: every document).
    const [folder, setFolder] = useState(null);
    const [folders, setFolders] = useState([]);
    const [foldersError, setFoldersError] = useState(null);
    const [naming, setNaming] = useState(null);          // { mode: "create" } | { mode: "rename", folder }
    const [removingFolder, setRemovingFolder] = useState(null);
    const [moving, setMoving] = useState(null);
    const [deleting, setDeleting] = useState(null);
    const [trashReload, setTrashReload] = useState(0);
    const [viewing, setViewing] = useState(null);
    // The row whose Download was just pressed, for its burst (a new key replays it).
    const [hit, setHit] = useState(null);

    const loadFolders = useCallback(async () => {
        const res = await listDocumentFoldersV2();
        if (res?.error) { setFoldersError(res.error.message || "Could not load your folders."); return; }
        setFoldersError(null);
        setFolders(res.data?.items || []);
    }, []);
    useEffect(() => { loadFolders(); }, [loadFolders]);

    const folderRef = useRef(folder);
    folderRef.current = folder;
    const fetchPage = useCallback(({ cursor, limit }) => myDocumentsV2({ cursor, limit, folder: folderRef.current?.id || null }), []);
    const docs = useMyDocuments({ fetchPage, pageSize: 25 });
    const firstFolderRun = useRef(true);
    useEffect(() => {
        if (firstFolderRun.current) { firstFolderRun.current = false; return; }
        docs.reload();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [folder?.id]);

    // "/" jumps to the search, as the hint in it says (not while typing elsewhere).
    useEffect(() => {
        const onKey = e => {
            if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
            const el = e.target;
            if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
            e.preventDefault();
            searchRef.current?.focus();
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, []);

    const folderName = useMemo(() => Object.fromEntries(folders.map(f => [f.id, f.name])), [folders]);
    const rows = useMemo(() => {
        const q = query.trim().toLowerCase();
        const hits = docs.items.filter(r => !q || (r.title || "").toLowerCase().includes(q)
            || (r.template_type || "").toLowerCase().includes(q)
            || (folderName[r.folder_id] || "").toLowerCase().includes(q));
        return sort ? sortRows(hits, sort) : hits;
    }, [docs.items, query, sort, folderName]);
    const week = addedThisWeek(docs.items);

    const download = async row => {
        const a = rowActions(row);
        const res = await downloadDocumentFile(row.id, `${row.title || "document"}.pdf`,
            { revisionId: a.revisionId, expectedPdfSha256: a.pdfSha256 });
        if (res?.error) toast.show(`Download failed: ${res.error}`, "danger", 4000);
    };
    const openFolder = f => { setFolder(f); setTab("all"); };

    // A new folder opens at once, with the picker to fill it: a folder is made
    // to hold a matter's papers, so that is the next step, not a hunt for rows.
    const createFolder = async name => {
        const res = await createDocumentFolderV2(name);
        if (res?.error) return res.error.message || "Could not create the folder.";
        setNaming(null);
        await loadFolders();
        openFolder(res.data);
        setAdding({ folder: res.data, fresh: true });
        return null;
    };
    // "New folder…" inside the Move dialog: make it, then the dialog files into it.
    const createForMove = async name => {
        const res = await createDocumentFolderV2(name);
        if (res?.error) return { error: res.error.message || "Could not create the folder." };
        justMade.current[res.data.id] = res.data.name;      // named in the toast before the list re-reads
        setFolders(fs => [...fs, res.data]);
        return { folder: res.data };
    };
    const [adding, setAdding] = useState(null);             // { folder, fresh } while the picker is open
    const justMade = useRef({});
    const added = (folderFor, n, close) => {
        toast.show(`Added ${n} document${n === 1 ? "" : "s"} to “${folderFor.name}”.`, "success", 3000);
        if (close) setAdding(null);
        docs.reload();
        loadFolders();
    };
    const renameFolder = async (f, name) => {
        const res = await renameDocumentFolderV2(f.id, name);
        if (res?.error) return res.error.message || "Could not rename the folder.";
        setNaming(null);
        if (folder?.id === f.id) setFolder({ ...folder, name: res.data.name });
        await loadFolders();
        return null;
    };
    const deleteFolder = async f => {
        const res = await deleteDocumentFolderV2(f.id);
        if (res?.error) return res.error.message || "Could not delete the folder.";
        setRemovingFolder(null);
        if (folder?.id === f.id) setFolder(null); else docs.reload();
        toast.show(`Folder “${f.name}” deleted. Its documents are still in your Vault.`, "success", 3500);
        await loadFolders();
        return null;
    };
    const moveRow = async (row, folderId) => {
        const res = await moveDocumentToFolderV2(row.id, folderId);
        if (res?.error) return res.error.message || "Could not move the document.";
        setMoving(null);
        toast.show(folderId ? `Moved to “${folderName[folderId] || justMade.current[folderId] || "the folder"}”.` : "Moved out of its folder.", "success", 2500);
        docs.reload();
        await loadFolders();
        return null;
    };

    const stats = [
        ["Total Documents", String(docs.items.length) + (docs.hasMore ? "+" : ""), !docs.loaded ? "Loading…" : folder ? `in “${folder.name}”` : `+${week} this week`, G.stack, "var(--brand-text)"],
        ["Folders Created", String(folders.length), "to organize by matter or client", G.folder, "var(--gold)"],
        ["Storage Used", "—", "tracked once uploads are connected", G.cloud, "var(--teal-ink)"],
    ];
    const tabs = [["all", "All documents", folder ? null : docs.items.length + (docs.hasMore ? "+" : "")], ["folders", "Folders", folders.length], ["trash", "Recently deleted", null]];

    return (
        <div data-lawyer-vault data-drafting-theme data-mode={mode} className="lv-page" data-lenis-prevent>
            <style>{`${DRAFTING_TOKENS_CSS}\n${LAWYER_VAULT_CSS}`}</style>
            <div className="lv-wrap">
                {viewing ? (
                    <VaultPreview row={viewing} folderName={folderName[viewing.folder_id] || null}
                        onBack={() => setViewing(null)} onDownload={download} />
                ) : (<>
                <nav className="lv-crumbs" aria-label="Breadcrumb">
                    Documents <span aria-hidden="true">/</span>{" "}
                    {folder
                        ? <><button type="button" onClick={() => setFolder(null)}>Vault</button> <span aria-hidden="true">/</span> <b>{folder.name}</b></>
                        : <b>Vault</b>}
                </nav>

                <div className="lv-head">
                    <div>
                        <h1>Document <span className="lv-accent">vault</span></h1>
                        <p>Keep the documents you draft in one place, and organize them into folders by matter, court or client.</p>
                    </div>
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                        {/* No upload backend yet: shown disabled and labelled, never as a working action. */}
                        <button type="button" className="lv-btn" disabled data-vault-soon="Upload File" title="Uploading files isn't connected yet — coming soon." style={{ height: 48 }}>
                            {svg(G.cloud, 18)} Upload File <span className="lv-soon">Soon</span>
                        </button>
                        <button type="button" className="lv-cta k3d" data-create-folder onClick={() => setNaming({ mode: "create" })}>
                            {svg(G.folderPlus, 19)} Create Folder
                        </button>
                    </div>
                </div>

                <div className="lv-stats">
                    {stats.map(([label, value, sub, icon, colour]) => (
                        <div key={label} className="lv-stat d3" {...tiltHandlers()} data-vault-stat={label} style={{ "--c": colour }}>
                            <span className="lv-ic">{svg(icon, 19)}</span>
                            <span className="l">{label}</span>
                            <span className="v">{value}</span>
                            <span className="s">{sub}</span>
                        </div>
                    ))}
                </div>

                <div className="lv-tools">
                    <label className="lv-search">
                        {svg(G.search, 18)}
                        <span style={hidden}>Search documents</span>
                        <input id="lvault-search" ref={searchRef} value={query} onChange={e => setQuery(e.target.value)} placeholder="Search your documents and folders" />
                        {query
                            ? <button type="button" onClick={() => setQuery("")} aria-label="Clear search" style={{ background: "none", border: 0, color: "var(--muted)", cursor: "pointer", fontSize: 20, lineHeight: 1 }}>×</button>
                            : <span className="lv-kbd" aria-hidden="true">/</span>}
                    </label>
                    <label className="lv-sort">
                        {svg(G.sort, 17)}
                        <span style={hidden}>Sort documents</span>
                        <select value={sort || ""} onChange={e => setSort(e.target.value || null)} data-vault-sort>
                            <option value="">Newest saved first</option>
                            {SORTS.filter(([k]) => k !== "newest").map(([k, name]) => <option key={k} value={k}>{name}</option>)}
                        </select>
                        <svg className="chev" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">{G.chev}</svg>
                    </label>
                </div>

                <section className="lv-card">
                    <div className="lv-bar">
                        <div role="tablist" aria-label="Vault" className="lv-tabs">
                            {tabs.map(([id, name, n]) => (
                                <button key={id} type="button" role="tab" className="lv-tab" aria-selected={tab === id} onClick={() => setTab(id)}>
                                    {name}{n !== null && n !== undefined && <span className="lv-n">{n}</span>}
                                </button>
                            ))}
                        </div>
                        {tab === "all" && folder && (
                            <div data-folder-filter className="lv-filter">
                                <span style={{ color: "var(--gold)", display: "flex" }}>{svg(G.folder, 16)}</span>
                                Showing the folder <b>{folder.name}</b>
                                <button type="button" className="lv-cta" style={{ height: 32, padding: "0 12px", fontSize: 13, borderRadius: 10 }} data-add-documents
                                    onClick={() => setAdding({ folder, fresh: false })}>{svg(G.plus, 15)} Add documents</button>
                                <button type="button" className="lv-btn" style={{ height: 32, fontSize: 13 }} onClick={() => setFolder(null)}>Show all</button>
                            </div>
                        )}
                    </div>

                    {tab === "trash" ? (
                        <RecentlyDeleted reloadSignal={trashReload}
                            onRestored={item => { toast.show(`“${item.title || "Document"}” is back in your Vault.`, "success", 3000); docs.reload(); loadFolders(); }} />
                    ) : tab === "folders" ? (
                        foldersError ? (
                            <div role="alert" className="lv-empty">{foldersError} <button type="button" className="lv-btn" onClick={loadFolders}>Try again</button></div>
                        ) : (
                            <div data-folder-grid className="lv-folders">
                                {folders.map(f => (
                                    <div key={f.id} data-folder={f.id} className="lv-folder d3" {...tiltHandlers()} style={{ "--c": "var(--gold)" }}>
                                        <button type="button" className="open" onClick={() => openFolder(f)} aria-label={`Open folder ${f.name}`}>
                                            <span className="lv-f3d" aria-hidden="true"><i className="bk" /><i className="pg b" /><i className="pg" /><i className="fr" /></span>
                                            <span style={{ minWidth: 0 }}>
                                                <span className="nm">{f.name}</span>
                                                <span className="lv-sub">{f.document_count} document{f.document_count === 1 ? "" : "s"}</span>
                                            </span>
                                        </button>
                                        <div className="lv-acts">
                                            <button type="button" className="lv-ib k-move" aria-label={`Add documents to ${f.name}`} title="Add documents" data-add-to-folder={f.id} onClick={() => setAdding({ folder: f, fresh: false })}>{svg(G.plus, 16)}</button>
                                            <button type="button" className="lv-ib k-pen" aria-label={`Rename folder ${f.name}`} title="Rename" data-rename-folder={f.id} onClick={() => setNaming({ mode: "rename", folder: f })}>{svg(G.pencil, 16)}</button>
                                            <button type="button" className="lv-ib danger k-trash" aria-label={`Delete folder ${f.name}`} title="Delete folder" data-delete-folder={f.id} onClick={() => setRemovingFolder(f)}>{svg(G.trash, 16)}</button>
                                        </div>
                                    </div>
                                ))}
                                <button type="button" className="lv-new" onClick={() => setNaming({ mode: "create" })}>
                                    <span>{svg(G.plus, 18)}</span> New folder
                                </button>
                                {folders.length === 0 && (
                                    <div style={{ gridColumn: "1 / -1", color: "var(--muted)", fontSize: 13.5 }}>No folders yet. Make one for each matter — a client, a case, a court — and add its documents in one go.</div>
                                )}
                            </div>
                        )
                    ) : docs.error ? (
                        <div role="alert" className="lv-empty">{docs.unavailable ? DOCUMENTS_UNAVAILABLE : <>Could not load your documents. <button type="button" className="lv-btn" onClick={docs.reload}>Try again</button></>}</div>
                    ) : !docs.loaded ? (
                        <div aria-busy="true" className="lv-empty">Loading your documents…</div>
                    ) : docs.isEmpty ? (
                        <div className="lv-empty">
                            <span className="lv-ic" style={{ "--c": "var(--brand-text)", width: 56, height: 56, margin: "0 auto", borderRadius: 16 }}>{svg(G.folder, 26)}</span>
                            <b>{folder ? `“${folder.name}” is empty` : "Your vault is empty"}</b>
                            {folder ? "Add the documents that belong to this matter. They move here; nothing is copied." : "Documents you save from Legal drafting with “Save to Documents” appear here."}
                            {folder && (
                                <div style={{ marginTop: 14, display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
                                    <button type="button" className="lv-cta" style={{ height: 42 }} data-add-documents-empty onClick={() => setAdding({ folder, fresh: false })}>{svg(G.plus, 17)} Add documents</button>
                                    <button type="button" className="lv-btn" onClick={() => setFolder(null)}>Show all documents</button>
                                </div>
                            )}
                        </div>
                    ) : (
                        <div>
                            <div className="lv-grid lv-th">
                                <span>Document</span><span>Type</span><span>Folder</span><span>Status</span><span>Last modified</span><span>Actions</span>
                            </div>
                            {rows.length === 0 && <div className="lv-empty">No document matches “{query}”.</div>}
                            {rows.map(row => {
                                const a = rowActions(row);
                                const status = documentStatusView(row);
                                const tone = STATUS_TONE[status.tone] || STATUS_TONE.muted;
                                const inFolder = folderName[row.folder_id];
                                const title = row.title || "document";
                                return (
                                    <div key={row.id} data-vault-row={row.id} className="lv-grid lv-row">
                                        <span style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                                            <span className="lv-pdf" aria-hidden="true">PDF</span>
                                            <span style={{ minWidth: 0 }}>
                                                <span className="lv-name" style={{ display: "block" }}>{row.title || "Untitled document"}</span>
                                                {row.version ? <span className="lv-sub">Version {row.version}</span> : null}
                                            </span>
                                        </span>
                                        <span className="lv-sub" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{row.template_type ? humanise(row.template_type) : "—"}</span>
                                        <span style={{ minWidth: 0 }}>
                                            {inFolder ? <span className="lv-chip">{svg(G.folder, 13)}{inFolder}</span> : <span className="lv-sub">No folder</span>}
                                        </span>
                                        <span><span className="lv-pill" style={{ color: tone, background: `color-mix(in srgb, ${tone} 14%, transparent)` }}><i />{status.label}</span></span>
                                        <span className="lv-sub">{formatWhen(row.updated_at || row.created_at)}</span>
                                        <span className="lv-acts">
                                            <button type="button" className="lv-ib k-eye" aria-label={`Preview ${title}`} title="Preview" onClick={() => setViewing(row)}>{svg(G.eye, 17)}</button>
                                            <button type="button" className={`lv-ib k-down${hit?.id === row.id ? " hit" : ""}`} aria-label={a.canDownload ? `Download ${title}` : a.reason} title={a.canDownload ? "Download" : a.reason}
                                                onClick={() => { if (!a.canDownload) return; setHit({ id: row.id, n: (hit?.n || 0) + 1 }); download(row); }} disabled={!a.canDownload}>
                                                <span key={hit?.id === row.id ? hit.n : 0} style={{ display: "grid" }}>{svg(G.down, 17)}</span>
                                                {hit?.id === row.id && <span key={`b${hit.n}`} className="lv-burst" aria-hidden="true">{[0, 45, 90, 135, 180, 225, 270, 315].map(d => <i key={d} style={{ "--a": `${d}deg` }} />)}</span>}
                                            </button>
                                            <button type="button" className="lv-ib k-move" aria-label={`Move ${title} to a folder`} title="Move to a folder" data-move-document={row.id} onClick={() => setMoving(row)}>{svg(G.folderMove, 17)}</button>
                                            <button type="button" className="lv-ib danger k-trash" aria-label={`Delete ${title}`} title="Delete" data-delete-document={row.id} onClick={() => setDeleting(row)}>{svg(G.trash, 17)}</button>
                                        </span>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                    {tab === "all" && docs.loaded && !docs.isEmpty && !docs.error && (
                        <div className="lv-foot">
                            <span style={{ flex: 1 }}>Showing {rows.length} of {docs.items.length}{docs.hasMore ? "+" : ""} documents</span>
                            {docs.hasMore && <button type="button" className="lv-btn" onClick={docs.loadMore} disabled={docs.loading} style={{ height: 34 }}>{docs.loading ? "Loading…" : "Load more"}</button>}
                        </div>
                    )}
                </section>
                </>)}
            </div>

            {naming?.mode === "create" && (
                <FolderNameDialog mode={mode} title="Create a folder" submitLabel="Create" onSubmit={createFolder} onClose={() => setNaming(null)} />
            )}
            {naming?.mode === "rename" && (
                <FolderNameDialog mode={mode} title="Rename the folder" initial={naming.folder.name} submitLabel="Rename"
                    onSubmit={name => renameFolder(naming.folder, name)} onClose={() => setNaming(null)} />
            )}
            {removingFolder && (
                <ConfirmFolderDelete mode={mode} folder={removingFolder} onConfirm={() => deleteFolder(removingFolder)} onClose={() => setRemovingFolder(null)} />
            )}
            {moving && <MoveDialog mode={mode} row={moving} folders={folders} onMove={id => moveRow(moving, id)} onCreate={createForMove} onClose={() => setMoving(null)} />}
            {adding && (
                <AddDocumentsDialog mode={mode} folder={adding.folder} fresh={adding.fresh} folderName={folderName}
                    onDone={(n, close) => added(adding.folder, n, close)} onClose={() => setAdding(null)} />
            )}
            {deleting && (
                <DeleteDocumentDialog row={deleting} onClose={() => setDeleting(null)}
                    onDeleted={() => {
                        setDeleting(null);
                        toast.show("Moved to Recently deleted. You can restore it from there.", "success", 3500);
                        docs.reload();
                        loadFolders();
                        setTrashReload(n => n + 1);
                    }} />
            )}
        </div>
    );
}

/* The lawyer theme for the shared primitives (they read the role-neutral
 * ThemeCtx), as the Document Analyzer does. */
export function VaultPage() {
    const { t } = useTheme();
    return (
        <WorkspaceThemeCtx.Provider value={t}>
            <VaultScreen />
        </WorkspaceThemeCtx.Provider>
    );
}

export default VaultPage;
