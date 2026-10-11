'use client';
import React, { useState, useEffect, useRef, Fragment } from "react";
import { useRouter } from "next/navigation";
import { useT } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import { useCase } from "./CaseContext.jsx";
import Ic from "./Ic.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput, Badge, Tooltip } from "@/components/shared/shared.jsx";
import { intakeStart, intakeSaveStep, intakeConvert, intakeGet, intakeClarify, transcribeAudio, uploadIntakeEvidence, confirmCase, deleteIntakeEvidence, downloadIntakeEvidence, getResumableIntake, getIntakeOcrReview, confirmIntakeOcrPage } from "@/lib/api.js";
import { useLang, useIsMobile } from "@/lib/i18n.jsx";
import { useAuth } from "@/context/AuthContext.jsx";
import { readIntakeValue, writeIntakeValue, clearIntakeValue } from "@/lib/intakeStorage.js";
import { escapeHtml } from "@/lib/escapeHtml.js";
import { DOCS_FONT } from "./documents/ui.jsx";
import { extractionLabel, incompleteFiles, TONE_OK, TONE_WARN, TONE_BAD, TONE_NEUTRAL } from "@/lib/extractionStatus.js";

/* One colour per tone, so a new state cannot arrive looking like a reassurance
 * simply because nobody added it to a ternary. */
const EXTRACTION_TONE_COLOUR = {
    [TONE_OK]: null,          // falls back to the muted body colour
    [TONE_WARN]: "#b45309",
    [TONE_BAD]: "#b91c1c",
    [TONE_NEUTRAL]: null,
};
const EXTRACTION_TONE_ICON = {
    [TONE_OK]: "✓", [TONE_WARN]: "⚠", [TONE_BAD]: "✕", [TONE_NEUTRAL]: "•",
};

// Encode Float32 PCM as 16-bit mono WAV (no ffmpeg on backend)
function _pcmToWav(samples, sampleRate) {
    const buf = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buf);
    const write4 = (off, str) => [...str].forEach((c, i) => view.setUint8(off + i, c.charCodeAt(0)));
    write4(0, "RIFF");  view.setUint32(4, 36 + samples.length * 2, true);
    write4(8, "WAVE");  write4(12, "fmt ");
    view.setUint32(16, 16, true);   view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);  view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);   write4(36, "data");
    view.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++)
        view.setInt16(44 + i * 2, Math.max(-32768, Math.min(32767, samples[i] * 32768)), true);
    return new Blob([buf], { type: "audio/wav" });
}

const PROVINCES = [
    { value: "punjab",      label: "Punjab" },
    { value: "sindh",       label: "Sindh" },
    { value: "kpk",         label: "KPK (Khyber Pakhtunkhwa)" },
    { value: "balochistan", label: "Balochistan" },
    { value: "federal",     label: "Federal (ICT / National)" },
];

const CASE_TYPES = [
    { value: "civil",          label: "Civil Law" },
    { value: "criminal",       label: "Criminal Law" },
    { value: "family",         label: "Family Law" },
    { value: "constitutional", label: "Constitutional Law" },
];

// Mirrors backend classifier_node._score_query — runs in browser so case type
// is selected before the backend even receives the description.
const quickClassify = (text) => {
    if (!text || text.trim().length < 4) return "";
    const t = text;
    const scores = { family: 0, criminal: 0, civil: 0, constitutional: 0 };

    // Family — English, Romanized Urdu, Urdu script
    if (/\b(divorce|talaq|talaaq|khula|khulaah|nikah|nikaah|marriage|shadi|shaadi|custody|hizanat|maintenance|nafaqa|dowry|jahez|dower|mehr|mehar|inheritance|wirsa|wirasat|MFLO|guardian|iddat|iddah)\b/i.test(t)) scores.family += 0.35;
    if (/(خلع|طلاق|نکاح|شادی|حضانت|نفقہ|مہر|وراثت|خاندان|گھریلو)/.test(t)) scores.family += 0.35;
    if (/\b(wife|husband|biwi|shohar|shauhar|child|bachha|in-laws|susral|sasural)\b/i.test(t)) scores.family += 0.15;

    // Criminal — English, Romanized Urdu, Urdu script
    if (/\b(FIR|murder|qatl|qatal|theft|chori|steal|rob|assault|dacoity|robbery|rape|zina|kidnap|bail|arrest|police|challan|accused|CrPC|PPC|PECA|cybercrime)\b/i.test(t)) scores.criminal += 0.30;
    if (/(قتل|چوری|ڈکیتی|بیل|گرفتاری|مقدمہ|پولیس|ملزم)/.test(t)) scores.criminal += 0.30;
    if (/\b(crime|criminal|jail|prison|sentence|prosecution|qaid)\b/i.test(t)) scores.criminal += 0.20;

    // Civil
    if (/\b(property|tenant|landlord|rent|kiraya|contract|agreement|debt|loan|mortgage|qarz|possession|eviction|damages|injunction|CPC|decree)\b/i.test(t)) scores.civil += 0.30;
    if (/\b(dispute|compensation|nuqsan)\b/i.test(t)) scores.civil += 0.15;

    // Constitutional
    if (/\b(fundamental\s*rights?|article\s*\d+|constitution|Supreme\s*Court|High\s*Court|writ|habeas|mandamus|government|parliament)\b/i.test(t)) scores.constitutional += 0.35;
    if (/\b(rights?|haqooq|azaadi|freedom|liberty|equality|discrimination)\b/i.test(t)) scores.constitutional += 0.15;

    const best = Object.entries(scores).reduce((a, b) => b[1] > a[1] ? b : a);
    return best[1] >= 0.15 ? best[0] : "";
};

const URGENCY_LEVELS = [
    { value: "low",    label: "Low — No immediate deadline" },
    { value: "medium", label: "Medium — Within a month" },
    { value: "high",   label: "High — Within a week" },
    { value: "urgent", label: "Urgent — Immediate action needed" },
];

const RISK_COLORS = { low: "success", medium: "warn", high: "danger", urgent: "danger" };

// Why the recommended actions were not verified against retrieved law. The
// backend distinguishes "we checked and it held" from "we could not check";
// only `grounded` is the former, so every other status gets a visible note.
// Written in the user's terms — they do not know what a retrieval chunk is.
const GROUNDING_NOTE = {
    no_evidence_retrieved: "No matching law was found for this case, so these steps could not be checked against Pakistani legislation. Confirm them with a qualified lawyer before acting.",
    ungrounded: "Some of these steps could not be fully matched to the law sections found for your case. Please confirm them with a qualified lawyer.",
    judge_failed: "The verification step could not run just now, so these steps have not been checked against the law. Please confirm them with a qualified lawyer.",
    pipeline_failed: "Automated analysis was unavailable for this case. Please have a qualified lawyer review your situation.",
    unparseable: "The analysis could not be verified. Please confirm these steps with a qualified lawyer.",
    no_actions: "No specific steps were produced for this case.",
    // A statute was named that does NOT appear in the law found for this case.
    // The generic "not verified" note below would badly undersell that: it
    // reads as a missing check, when what happened is that a citation may be
    // invented. This is the one status a reader most needs stated plainly.
    citations_unverified: "One or more laws cited here could not be matched to any legislation found for your case, and may not exist as stated. Do not rely on these citations — have a qualified lawyer check them.",
    // The verifier passed the analysis but its own per-step assessment
    // contradicted that, so the pass was withdrawn.
    claims_disagree: "The verification of these steps was inconsistent, so they are being treated as unverified. Please confirm them with a qualified lawyer.",
    // Nothing in the analysis rested on a law section that could be resolved,
    // so there was nothing to check it against.
    no_bound_citations: "These steps could not be tied to any specific law section, so they have not been checked. Please confirm them with a qualified lawyer.",
    unverified: "These steps have not been verified against Pakistani law. Please confirm them with a qualified lawyer.",
};

/* The intake's look (2026-10-10), scoped by [data-intake]; client tokens
 * (clientTheme.js), so the lawyer side is untouched. */
const INTAKE_CSS = `[data-intake] .in-head{display:flex;align-items:flex-end;gap:16px;margin:4px 0 22px}
[data-intake] .in-title{margin:0;font-size:34px;font-weight:600;color:var(--ink);letter-spacing:-.2px;line-height:1.15}
[data-intake] .in-sub{margin-top:6px;font-size:14px;color:var(--muted)}
[data-intake] .in-meta .dot{width:7px;height:7px;border-radius:50%;background:var(--brand-text)}
[data-intake] .in-meta{display:inline-flex;align-items:center;gap:8px;height:34px;padding:0 14px;border-radius:999px;font-size:12.5px;font-weight:600;color:var(--muted);background:var(--surface);border:1px solid var(--line)}
[data-intake] .in-meta b{color:var(--brand-text)}
[data-intake] .in-shell{display:block}
[data-intake] .in-main{min-width:0}
[data-intake] .in-rail{position:relative;display:grid;grid-template-columns:repeat(5,minmax(0,1fr));max-width:860px;margin:0 auto 26px;padding:0}
[data-intake] .in-rstep{position:relative;display:flex;flex-direction:column;align-items:center;gap:8px;min-width:0;padding:0 6px;border:0;background:transparent;color:var(--ink);font:inherit;text-align:center;cursor:pointer}
[data-intake] .in-rstep:disabled{cursor:not-allowed}
[data-intake] .in-rstep[aria-current]{cursor:default}
[data-intake] .in-rstep::before{content:"";position:absolute;top:16px;right:calc(50% + 22px);left:calc(-50% + 22px);height:2px;border-radius:2px;background:var(--line-strong)}
[data-intake] .in-rstep:first-child::before{display:none}
[data-intake] .in-rstep[data-done]::before,[data-intake] .in-rstep[aria-current]::before{background:linear-gradient(90deg,#1c9c66,#3ee0a1)}
[data-intake] .in-rstep .num{position:relative;width:34px;height:34px;flex:none;border-radius:50%;display:grid;place-items:center;font-size:13px;font-weight:800;color:var(--muted);background:var(--surface);border:2px solid var(--line-strong);transition:transform .25s cubic-bezier(.3,1.4,.5,1),background .25s,color .25s,border-color .25s,box-shadow .25s}
[data-intake] .in-rstep:hover:not(:disabled):not([aria-current]) .num{transform:scale(1.1);border-color:var(--brand-text);color:var(--brand-text);box-shadow:0 0 0 5px color-mix(in srgb,var(--brand-text) 14%,transparent)}
[data-intake] .in-rstep:hover:not(:disabled):not([aria-current]) .t{color:var(--ink)}
[data-intake] .in-rstep:focus-visible{outline:none}
[data-intake] .in-rstep:focus-visible .num{box-shadow:0 0 0 3px var(--focus)}
[data-intake] .in-rstep .t{display:block;max-width:100%;font-size:13px;font-weight:600;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:color .2s}
[data-intake] .in-rstep .d{display:block;max-width:100%;margin-top:1px;font-size:11.5px;color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-intake] .in-rstep>span:last-child{max-width:100%;min-width:0}
[data-intake] .in-rstep .now{display:none}
[data-intake] .in-rstep[data-done] .num{background:color-mix(in srgb,var(--brand-text) 18%,var(--surface));border-color:transparent;color:var(--brand-text)}
[data-intake] .in-rstep[data-done] .t{color:var(--ink)}
[data-intake] .in-rstep[data-done] .d{color:var(--brand-text)}
[data-intake] .in-rstep[aria-current] .num{background:linear-gradient(135deg,#12897f,#1c9c66);border-color:transparent;color:#fff;box-shadow:0 0 0 5px color-mix(in srgb,var(--brand-text) 20%,transparent);animation:inRing 2.4s ease-out infinite}
[data-intake] .in-rstep[aria-current] .t{color:var(--brand-text);font-weight:700}
[data-intake] .in-rstep[aria-current] .d{color:var(--muted)}
@keyframes inRing{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--brand-text) 45%,transparent)}70%{box-shadow:0 0 0 9px transparent}100%{box-shadow:0 0 0 0 transparent}}
[data-intake] .in-rprog{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
[data-intake] .in-filebtn{display:inline-flex;align-items:center;gap:8px;height:38px;padding:0 8px 0 14px;border-radius:999px;border:1px solid var(--line-strong);background:var(--surface);color:var(--ink);font:inherit;font-size:13px;font-weight:600;cursor:pointer;transition:background .2s,border-color .2s,transform .15s}
[data-intake] .in-filebtn:hover{background:var(--hover)}
[data-intake] .in-filebtn:active{transform:scale(.97)}
[data-intake] .in-filebtn[aria-expanded="true"]{border-color:color-mix(in srgb,var(--brand-text) 60%,transparent);background:color-mix(in srgb,var(--brand-text) 12%,var(--surface))}
[data-intake] .in-filebtn svg{color:var(--brand-text)}
[data-intake] .in-filebtn .n{min-width:22px;height:22px;padding:0 6px;box-sizing:border-box;border-radius:999px;display:grid;place-items:center;font-size:11.5px;font-weight:800;color:var(--on-brand);background:var(--brand-solid)}
[data-intake] .in-file{position:fixed;top:16px;right:16px;bottom:16px;z-index:60;width:340px;max-width:calc(100vw - 32px);box-sizing:border-box;display:flex;flex-direction:column;padding:20px;border-radius:22px;background:var(--surface);border:1px solid var(--line-strong);box-shadow:-24px 0 60px -24px rgba(0,0,0,.8);overflow-y:auto;transform:translateX(calc(100% + 24px));visibility:hidden;transition:transform .35s cubic-bezier(.22,1,.36,1),visibility 0s linear .35s}
[data-intake] .in-file[data-open]{transform:none;visibility:visible;transition:transform .35s cubic-bezier(.22,1,.36,1),visibility 0s}
[data-intake] .in-file-x{margin-left:auto;width:34px;height:34px;flex:none;border-radius:10px;border:0;background:transparent;color:var(--muted);display:grid;place-items:center;cursor:pointer;transition:background .2s,color .2s}
[data-intake] .in-file-x:hover{background:var(--danger-soft);color:var(--danger)}
[data-intake] .in-file-x svg{transition:transform .25s}
[data-intake] .in-file-x:hover svg{transform:rotate(90deg)}
[data-intake] .in-file-head{display:flex;align-items:center;gap:10px;margin-bottom:6px}
[data-intake] .in-file-ic{width:34px;height:34px;flex:none;border-radius:10px;display:grid;place-items:center;color:var(--brand-text);background:color-mix(in srgb,var(--brand-text) 15%,transparent)}
[data-intake] .in-file-row{display:flex;justify-content:space-between;gap:10px;padding:11px 0;border-bottom:1px solid var(--line);font-size:13px}
[data-intake] .in-file-row span:first-child{color:var(--faint)}
[data-intake] .in-file-row b{font-weight:600;color:var(--ink);text-align:right}
[data-intake] .in-file-row b[data-new]{color:var(--brand-text)}
[data-intake] .in-file-row i{font-style:normal;color:var(--faint)}
[data-intake] .in-file-note{margin-top:auto;padding:12px;border-radius:14px;background:var(--surface-2);font-size:12px;line-height:1.5;color:var(--muted)}
[data-intake] .in-file-note b{color:var(--ink)}
[data-intake] .in-card{position:relative;padding:26px 28px;border-radius:22px;border:1px solid var(--line);background:radial-gradient(60% 90% at 100% 0%,color-mix(in srgb,var(--brand-text) 8%,transparent) 0%,transparent 60%),var(--surface);box-shadow:var(--shadow-rest);animation:inUp .3s ease}
[data-intake] .in-card-head{display:flex;align-items:center;gap:14px;margin-bottom:22px}
[data-intake] .in-card-ic{width:42px;height:42px;flex:none;border-radius:13px;display:grid;place-items:center;color:var(--brand-text);background:color-mix(in srgb,var(--brand-text) 15%,transparent)}
[data-intake] .in-card-title{margin:0;font-size:19px;font-weight:700;color:var(--ink)}
[data-intake] .in-card-sub{margin-top:3px;font-size:13.5px;color:var(--muted)}
[data-intake] .in-label{display:flex;align-items:center;gap:8px;margin:0 0 12px;font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--faint)}
[data-intake] .in-label .req{color:var(--brand-text)}
[data-intake] .in-roles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-bottom:22px}
[data-intake] .in-role{position:relative;display:flex;flex-direction:row;align-items:center;gap:16px;padding:16px 18px;border-radius:16px;background:linear-gradient(180deg,color-mix(in srgb,var(--brand-text) 7%,var(--surface)) 0%,color-mix(in srgb,var(--brand-text) 2%,var(--surface)) 100%);border:1px solid color-mix(in srgb,var(--brand-text) 16%,var(--line));box-shadow:inset 0 1px 0 color-mix(in srgb,#fff 6%,transparent);color:var(--ink);font:inherit;text-align:left;cursor:pointer;transition:transform .25s cubic-bezier(.22,1,.36,1),background .2s,border-color .2s,box-shadow .25s}
[data-intake] .in-role:hover{border-color:var(--brand-text);background:var(--hover)}
[data-intake] .in-role[aria-checked="true"]{border-color:color-mix(in srgb,var(--c) 70%,transparent);background:linear-gradient(160deg,color-mix(in srgb,var(--c) 20%,var(--surface)) 0%,color-mix(in srgb,var(--c) 7%,var(--surface)) 70%);box-shadow:0 0 0 3px color-mix(in srgb,var(--c) 18%,transparent)}
[data-intake] .in-role .art{width:64px;height:64px;flex:none;display:grid;place-items:center;border-radius:50%;color:var(--c);background:radial-gradient(closest-side,color-mix(in srgb,var(--c) 14%,transparent),transparent);transition:transform .3s cubic-bezier(.3,1.4,.5,1)}
[data-intake] .in-role .art .glyph{display:block;width:46px;height:46px;transform-origin:50% 80%;background:currentColor;-webkit-mask:var(--icon) center/contain no-repeat;mask:var(--icon) center/contain no-repeat;transition:filter .3s}
[data-intake] .in-credit{margin:-14px 0 18px;font-size:10.5px;color:var(--faint)}
[data-intake] .in-credit a{color:inherit;text-decoration:underline}
[data-intake] .in-role[aria-checked="true"] .art .glyph{filter:drop-shadow(0 0 5px color-mix(in srgb,var(--c) 55%,transparent))}
[data-intake] .in-role:hover .art{transform:scale(1.1)}
[data-intake] .in-role:nth-child(1):hover .art .glyph{animation:inSway 1s ease-in-out infinite}
[data-intake] .in-role:nth-child(2):hover .art .glyph{animation:inShake .6s ease-in-out infinite}
[data-intake] .in-role[aria-checked="true"] .art{animation:inPop .45s cubic-bezier(.3,1.4,.5,1)}
[data-intake] .in-role:active .art{transform:scale(.92)}
@keyframes inSway{0%,100%{transform:rotate(0)}30%{transform:rotate(-7deg)}70%{transform:rotate(5deg)}}
@keyframes inShake{0%,100%{transform:translateX(0)}20%{transform:translateX(-2px) rotate(-3deg)}40%{transform:translateX(2px) rotate(3deg)}60%{transform:translateX(-1.5px)}80%{transform:translateX(1px)}}
@keyframes inPop{0%{transform:scale(.8)}60%{transform:scale(1.18)}100%{transform:scale(1)}}
[data-intake] .in-role:hover .art .glyph{filter:drop-shadow(0 0 6px color-mix(in srgb,var(--c) 70%,transparent))}
[data-intake] .in-role .nm{display:block;padding-right:28px;font-size:15.5px;font-weight:700}
[data-intake] .in-role .ur{margin-left:6px;font-size:13px;font-weight:500;color:var(--faint)}
[data-intake] .in-role .ds{margin-top:3px;font-size:13px;color:var(--muted)}
[data-intake] .in-role .eg{margin-top:5px;font-size:12px;color:var(--faint)}
[data-intake] .in-role .tick{position:absolute;top:14px;right:14px;width:24px;height:24px;border-radius:50%;display:grid;place-items:center;border:2px solid var(--line-strong);color:transparent;transition:background .2s,border-color .2s,color .2s,transform .3s cubic-bezier(.3,1.4,.5,1)}
[data-intake] .in-role[aria-checked="true"] .tick{background:var(--c);border-color:var(--c);color:#0d2a26;transform:scale(1.08)}
[data-intake] .in-provs{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}
[data-intake] .in-prov{min-width:0;display:flex;flex-direction:column;align-items:flex-start;gap:2px;padding:9px 12px;border-radius:12px;background:linear-gradient(180deg,color-mix(in srgb,var(--c) 9%,var(--surface)) 0%,color-mix(in srgb,var(--c) 3%,var(--surface)) 100%);border:1px solid color-mix(in srgb,var(--c) 22%,var(--line));box-shadow:inset 0 1px 0 color-mix(in srgb,#fff 6%,transparent);color:var(--ink);font:inherit;text-align:left;cursor:pointer;transition:background .2s,border-color .2s,transform .15s}
[data-intake] .in-prov:hover{border-color:var(--c);background:linear-gradient(180deg,color-mix(in srgb,var(--c) 14%,var(--hover)),var(--hover))}
[data-intake] .in-prov:hover .pin{transform:scale(1.14)}
[data-intake] .in-prov:hover .pin svg{filter:drop-shadow(0 0 6px color-mix(in srgb,var(--c) 70%,transparent))}
[data-intake] .in-prov .pin svg{transition:filter .3s}
[data-intake] .in-prov:active{transform:scale(.97)}
[data-intake] .in-prov .pin{display:grid;place-items:center;width:40px;height:40px;margin-bottom:4px;border-radius:0;color:var(--c);background:transparent;transition:transform .3s cubic-bezier(.3,1.4,.5,1),box-shadow .3s,color .2s,background .2s}
[data-intake] .in-prov b{font-size:13.5px;font-weight:700;white-space:nowrap}
[data-intake] .in-prov span{max-width:100%;font-size:11.5px;color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-intake] .in-prov[aria-checked="true"]{border-color:color-mix(in srgb,var(--c) 65%,transparent);background:linear-gradient(160deg,color-mix(in srgb,var(--c) 20%,var(--surface)) 0%,color-mix(in srgb,var(--c) 7%,var(--surface)) 70%);box-shadow:0 0 0 3px color-mix(in srgb,var(--c) 14%,transparent)}
[data-intake] .in-prov[aria-checked="true"] .pin{color:var(--c)}
[data-intake] .in-prov[aria-checked="true"] .pin svg{filter:drop-shadow(0 0 5px color-mix(in srgb,var(--c) 55%,transparent))}
[data-intake] .in-hint{margin-top:10px;font-size:12.5px;color:var(--faint)}
[data-intake] .in-foot{display:flex;align-items:center;gap:14px;margin-top:26px;padding-top:18px;border-top:1px solid var(--line)}
[data-intake] .in-foot .why{flex:1;font-size:12.5px;color:var(--muted)}
[data-intake] .in-next{display:inline-flex;align-items:center;gap:8px;height:40px;padding:0 18px;border:0;border-radius:999px;background:linear-gradient(135deg,#12897f,#1c9c66);color:#fff;font:inherit;font-size:13.5px;font-weight:700;cursor:pointer;box-shadow:0 8px 20px -10px rgba(28,156,102,.8);transition:filter .15s,transform .15s,box-shadow .2s}
[data-intake] .in-next:hover:not(:disabled){filter:brightness(1.06)}
[data-intake] .in-next:active:not(:disabled){transform:scale(.94);box-shadow:0 3px 10px -6px rgba(28,156,102,.9)}
[data-intake] .in-next:active:not(:disabled) svg{transform:translateX(6px)}
[data-intake] .in-next svg{transition:transform .18s cubic-bezier(.3,1.4,.5,1)}
[data-intake] .in-next:disabled{background:var(--chip-n);color:var(--faint);box-shadow:none;cursor:not-allowed}
[data-intake] .in-ref{flex:none;display:inline-flex;align-items:center;height:30px;padding:0 12px;border-radius:999px;font-size:12px;font-weight:700;color:var(--gold);background:color-mix(in srgb,var(--gold) 12%,transparent)}
[data-intake] .in-mode{display:inline-flex;padding:3px;margin-bottom:12px;border-radius:999px;background:var(--surface-2);border:1px solid var(--line)}
[data-intake] .in-mode button{display:inline-flex;align-items:center;gap:7px;height:32px;padding:0 14px;border:0;border-radius:999px;background:transparent;color:var(--muted);font:inherit;font-size:12.5px;font-weight:600;cursor:pointer;transition:background .2s,color .2s}
[data-intake] .in-mode button:hover{color:var(--hover-ink)}
[data-intake] .in-mode button[aria-pressed="true"]{background:color-mix(in srgb,var(--brand-text) 16%,transparent);color:var(--brand-text);font-weight:700}
[data-intake] .in-compose{position:relative;border-radius:16px;border:1px solid var(--line-strong);background:var(--input);overflow:hidden;transition:border-color .2s,box-shadow .2s}
[data-intake] .in-compose:focus-within{border-color:var(--brand-text);box-shadow:0 0 0 3px color-mix(in srgb,var(--brand-text) 16%,transparent)}
[data-intake] .in-compose textarea{display:block;width:100%;box-sizing:border-box;min-height:150px;resize:vertical;padding:14px 16px;border:0;outline:none;background:transparent;color:var(--ink);font:inherit;font-size:14.5px;line-height:1.6}
[data-intake] .in-compose textarea::placeholder{color:var(--faint)}
[data-intake] .in-compose-foot{display:flex;align-items:center;gap:10px;padding:8px 10px 8px 16px;border-top:1px solid var(--line);font-size:12px;color:var(--faint)}
[data-intake] .in-ghost{display:inline-flex;align-items:center;gap:7px;height:34px;padding:0 14px;border-radius:999px;border:1px solid var(--line-strong);background:transparent;color:var(--ink);font:inherit;font-size:13px;font-weight:600;cursor:pointer;transition:background .15s}
[data-intake] .in-ghost:hover{background:var(--hover-tint)}
[data-intake] .in-detect{display:flex;align-items:center;flex-wrap:wrap;gap:8px 10px;margin-top:14px;padding:10px 14px;border-radius:14px;font-size:13.5px;color:var(--ink);background:color-mix(in srgb,var(--brand-text) 7%,transparent);border:1px dashed color-mix(in srgb,var(--brand-text) 40%,transparent)}
[data-intake] .in-detect b{color:var(--brand-text)}
[data-intake] .in-detect .muted{font-size:12.5px;color:var(--faint)}
[data-intake] .in-chip{display:inline-flex;align-items:center;height:32px;padding:0 12px;border-radius:999px;border:1px solid var(--line-strong);background:transparent;color:var(--muted);font:inherit;font-size:12.5px;font-weight:600;cursor:pointer;transition:background .15s,color .15s,border-color .15s}
[data-intake] .in-chip:hover{background:var(--hover-tint);color:var(--ink)}
[data-intake] .in-chip[aria-checked="true"]{border-color:color-mix(in srgb,var(--brand-text) 60%,transparent);background:color-mix(in srgb,var(--brand-text) 13%,transparent);color:var(--brand-text)}
[data-intake] .in-two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px;margin-top:20px}
[data-intake] .in-seg{display:flex;padding:3px;border-radius:12px;background:var(--surface-2);border:1px solid var(--line)}
[data-intake] .in-seg button{flex:1;min-width:0;height:34px;padding:0 8px;border:0;border-radius:9px;background:transparent;color:var(--muted);font:inherit;font-size:12.5px;font-weight:600;white-space:nowrap;cursor:pointer;transition:background .2s,color .2s}
[data-intake] .in-seg button:hover{color:var(--hover-ink)}
[data-intake] .in-seg button[aria-checked="true"]{background:color-mix(in srgb,var(--brand-text) 16%,transparent);color:var(--brand-text);font-weight:700}
[data-intake] .in-urg button[aria-checked="true"][data-u="low"]{background:color-mix(in srgb,#3ee0a1 18%,transparent);color:#3ee0a1}
[data-intake] .in-urg button[aria-checked="true"][data-u="medium"]{background:var(--gold);color:#2b2410}
[data-intake] .in-urg button[aria-checked="true"][data-u="high"]{background:#f59e0b;color:#2b1a05}
[data-intake] .in-urg button[aria-checked="true"][data-u="urgent"]{background:#ef6b5e;color:#2a0d0a}
[data-intake] .in-drop{display:flex;flex-direction:column;gap:8px;margin-top:10px;padding:12px;border-radius:14px;border:1.5px dashed var(--line-strong);background:var(--surface-2)}
[data-intake] .in-drop-btn{display:flex;align-items:center;gap:10px;width:100%;padding:8px;border:0;border-radius:10px;background:transparent;color:var(--ink);font:inherit;text-align:left;cursor:pointer;transition:background .15s}
[data-intake] .in-drop-btn:hover{background:var(--hover-tint)}
[data-intake] .in-drop-btn b{display:block;font-size:13.5px}
[data-intake] .in-drop-btn small{display:block;font-size:11px;color:var(--faint)}
[data-intake] .in-input{width:100%;box-sizing:border-box;padding:10px 14px;border-radius:12px;border:1px solid var(--line-strong);background:var(--input);color:var(--ink);font:inherit;font-size:13.5px;line-height:1.5;resize:vertical;outline:none;transition:border-color .2s,box-shadow .2s}
[data-intake] .in-input:focus{border-color:var(--brand-text);box-shadow:0 0 0 3px color-mix(in srgb,var(--brand-text) 16%,transparent)}
[data-intake] .in-back{display:inline-flex;align-items:center;gap:6px;height:36px;padding:0 14px;border-radius:999px;border:1px solid var(--line-strong);background:transparent;color:var(--ink);font:inherit;font-size:13px;font-weight:600;cursor:pointer;transition:background .15s,transform .18s cubic-bezier(.3,1.4,.5,1)}
[data-intake] .in-back:hover{background:var(--hover-tint)}
[data-intake] .in-back:active{transform:translateX(-5px) scale(.95)}
[data-intake] .in-qbars{display:flex;gap:6px;flex:none}
[data-intake] .in-qbars i{width:26px;height:6px;border-radius:6px;background:var(--line);transition:background .3s}
[data-intake] .in-qbars i[data-on]{background:var(--brand-text)}
[data-intake] .in-qbars i[data-now]{background:linear-gradient(90deg,var(--brand-text) 50%,var(--line) 50%)}
[data-intake] .in-thread{display:flex;flex-direction:column;gap:14px;min-height:180px}
[data-intake] .in-msg{display:flex;gap:10px;align-items:flex-start;max-width:86%;animation:inUp .3s ease}
[data-intake] .in-msg.me{align-self:flex-end;max-width:72%}
[data-intake] .in-ai{width:32px;height:32px;flex:none;border-radius:10px;display:grid;place-items:center;font-size:14px;color:var(--brand-text);background:color-mix(in srgb,var(--brand-text) 16%,transparent)}
[data-intake] .in-bub{padding:11px 14px;border-radius:4px 16px 16px 16px;background:var(--surface-2);border:1px solid var(--line);font-size:14px;line-height:1.55;color:var(--ink)}
[data-intake] .in-bub[data-now]{border-color:color-mix(in srgb,var(--brand-text) 45%,transparent)}
[data-intake] .in-msg.me .in-bub{border-radius:16px 4px 16px 16px;border:0;background:linear-gradient(135deg,#12897f,#1c9c66);color:#fff}
[data-intake] .in-qn{display:block;margin-bottom:4px;font-size:10.5px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--brand-text)}
[data-intake] .in-answer{display:flex;flex-direction:column;gap:8px;margin-left:42px}
[data-intake] .in-answer textarea{width:100%;box-sizing:border-box;min-height:64px;padding:12px 14px;border-radius:14px;border:1px solid var(--brand-text);box-shadow:0 0 0 3px color-mix(in srgb,var(--brand-text) 14%,transparent);background:var(--input);color:var(--ink);font:inherit;font-size:14px;line-height:1.5;resize:vertical;outline:none}
[data-intake] .in-quick{display:flex;gap:6px;flex-wrap:wrap}
[data-intake] .in-typing{display:inline-flex;gap:4px;margin-left:8px;vertical-align:middle}
[data-intake] .in-typing i{width:6px;height:6px;border-radius:50%;background:var(--brand-text);animation:inDot 1s ease-in-out infinite}
[data-intake] .in-typing i:nth-child(2){animation-delay:.15s}
[data-intake] .in-typing i:nth-child(3){animation-delay:.3s}
@keyframes inDot{0%,100%{opacity:.3;transform:none}50%{opacity:1;transform:translateY(-3px)}}
[data-intake] .in-facts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:16px}
[data-intake] .in-facts div{padding:12px 14px;border-radius:14px;background:var(--surface-2);border:1px solid var(--line)}
[data-intake] .in-facts small{display:block;font-size:10.5px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--faint)}
[data-intake] .in-facts b{display:block;margin-top:4px;font-size:15px;color:var(--ink)}
[data-intake] .in-facts b[data-u="medium"]{color:var(--gold)}
[data-intake] .in-facts b[data-u="high"],[data-intake] .in-facts b[data-u="urgent"]{color:#ef6b5e}
[data-intake] .in-sections{display:flex;flex-direction:column;gap:12px}
[data-intake] .in-cats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
[data-intake] .in-cat{display:flex;flex-direction:column;align-items:flex-start;gap:5px;padding:16px;border-radius:16px;border:1px solid var(--line-strong);background:var(--surface-2);color:var(--ink);font:inherit;text-align:left;cursor:pointer;transition:transform .2s,background .2s,border-color .2s}
[data-intake] .in-cat:hover:not(:disabled){transform:translateY(-2px);background:var(--hover-tint)}
[data-intake] .in-cat:disabled{cursor:default}
[data-intake] .in-cat small{font-size:10.5px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--brand-text)}
[data-intake] .in-cat b{font-size:16px}
[data-intake] .in-cat span{font-size:12.5px;color:var(--muted);line-height:1.45}
[data-intake] .in-cat[aria-checked="true"]{border-color:color-mix(in srgb,var(--brand-text) 70%,transparent);background:color-mix(in srgb,var(--brand-text) 12%,var(--surface-2));box-shadow:0 0 0 3px color-mix(in srgb,var(--brand-text) 16%,transparent)}
[data-intake] .in-open{display:flex;align-items:center;gap:16px;margin-top:20px;padding:18px 20px;border-radius:18px;background:linear-gradient(135deg,color-mix(in srgb,#12897f 35%,transparent),color-mix(in srgb,#1c9c66 12%,transparent));border:1px solid color-mix(in srgb,var(--brand-text) 35%,transparent)}
[data-intake] .in-open b{display:block;font-size:16px;color:var(--ink)}
[data-intake] .in-open span{display:block;margin-top:2px;font-size:13px;line-height:1.5;color:var(--muted)}
[data-intake] .in-open-ic{width:46px;height:46px;flex:none;border-radius:50%;display:grid;place-items:center;background:var(--brand-text);color:#0d2a26}
[data-intake] .in-done{margin-top:20px;padding:26px;border-radius:22px;text-align:center;background:radial-gradient(70% 120% at 50% 0%,color-mix(in srgb,var(--brand-text) 22%,transparent),transparent 70%),var(--surface-2);border:1px solid color-mix(in srgb,var(--brand-text) 40%,transparent);animation:inUp .4s ease}
[data-intake] .in-done-ic{display:inline-grid;place-items:center;width:60px;height:60px;border-radius:50%;background:linear-gradient(135deg,#12897f,#3ee0a1);color:#fff;box-shadow:0 0 0 10px color-mix(in srgb,var(--brand-text) 12%,transparent)}
[data-intake] .in-done h3{margin:14px 0 0;font-size:22px;font-weight:700;color:var(--ink)}
[data-intake] .in-done p{margin:6px auto 0;max-width:520px;font-size:14px;line-height:1.6;color:var(--muted)}
[data-intake] .in-nexts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
[data-intake] .in-nx{--c:var(--brand-text);display:flex;flex-direction:column;align-items:flex-start;gap:6px;padding:16px;border-radius:18px;border:1px solid var(--line);background:var(--surface-2);color:var(--ink);font:inherit;text-align:left;cursor:pointer;transition:transform .2s,border-color .2s,box-shadow .2s}
[data-intake] .in-nx:hover:not(:disabled){transform:translateY(-3px);border-color:color-mix(in srgb,var(--c) 50%,transparent);box-shadow:0 14px 28px -18px color-mix(in srgb,var(--c) 80%,#000)}
[data-intake] .in-nx:disabled{opacity:.5;cursor:not-allowed}
[data-intake] .in-nx[data-main]{border-color:color-mix(in srgb,var(--brand-text) 40%,transparent)}
[data-intake] .in-nx .ic{width:36px;height:36px;border-radius:11px;display:grid;place-items:center;color:var(--c);background:color-mix(in srgb,var(--c) 16%,transparent)}
[data-intake] .in-nx b{font-size:15px}
[data-intake] .in-nx span:last-child{font-size:12.5px;color:var(--muted);line-height:1.45}
[data-intake] .in-voice{display:flex;flex-direction:column;gap:10px}
[data-intake] .in-rec{display:flex;align-items:center;gap:14px;padding:10px 12px 10px 10px;border-radius:999px;border:1px solid var(--line-strong);background:var(--input)}
[data-intake] .in-voice[data-state="recording"] .in-rec{border-color:color-mix(in srgb,var(--danger) 60%,transparent);box-shadow:0 0 0 3px color-mix(in srgb,var(--danger) 14%,transparent)}
[data-intake] .in-mic{position:relative;width:46px;height:46px;flex:none;border-radius:50%;border:0;display:grid;place-items:center;color:#fff;background:linear-gradient(135deg,#12897f,#1c9c66);cursor:pointer;box-shadow:0 6px 16px -8px rgba(28,156,102,.9);transition:transform .2s,filter .2s}
[data-intake] .in-mic:hover:not(:disabled){transform:scale(1.06);filter:brightness(1.08)}
[data-intake] .in-mic:disabled{opacity:.5;cursor:not-allowed}
[data-intake] .in-mic[aria-pressed="true"]{background:var(--danger);box-shadow:0 0 0 0 color-mix(in srgb,var(--danger) 50%,transparent);animation:inMicPulse 1.4s ease-out infinite}
@keyframes inMicPulse{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--danger) 55%,transparent)}100%{box-shadow:0 0 0 12px transparent}}
[data-intake] .in-wave{flex:1;min-width:0;height:30px;display:flex;align-items:center;gap:3px;overflow:hidden}
[data-intake] .in-wave i{flex:1;min-width:2px;max-width:5px;border-radius:3px;background:color-mix(in srgb,var(--brand-text) 35%,transparent);transform:scaleY(.25);transform-origin:center;transition:transform .3s}
[data-intake] .in-voice[data-state="recording"] .in-wave i{background:var(--brand-text);animation:inWave .9s ease-in-out infinite}
[data-intake] .in-voice[data-state="ready"] .in-wave i,[data-intake] .in-voice[data-state="stopped"] .in-wave i{transform:scaleY(.6)}
@keyframes inWave{0%,100%{transform:scaleY(.3)}50%{transform:scaleY(1)}}
[data-intake] .in-time{flex:none;min-width:48px;font:700 15px "JetBrains Mono",monospace;color:var(--brand-text);text-align:right}
[data-intake] .in-voice[data-state="recording"] .in-time{color:var(--danger)}
[data-intake] .in-vstatus{display:flex;align-items:center;gap:8px;padding-left:16px;font-size:12.5px;font-weight:600}
[data-intake] .in-vstatus .dot{width:7px;height:7px;border-radius:50%;background:currentColor}
[data-intake] .in-transcript{display:flex;flex-direction:column;gap:10px;padding:14px 16px;border-radius:16px;background:var(--surface-2);border:1px solid var(--line)}
[data-intake] .in-tr-head{display:flex;align-items:center;gap:10px;font-size:13px;color:var(--ink)}
[data-intake] .in-bot{width:30px;height:30px;flex:none;border-radius:10px;display:grid;place-items:center;color:var(--brand-text);background:color-mix(in srgb,var(--brand-text) 15%,transparent)}
[data-intake] .in-tag{display:inline-flex;align-items:center;height:22px;padding:0 8px;border-radius:999px;font-size:10.5px;font-weight:700;letter-spacing:.04em;color:var(--muted);background:var(--surface)}
[data-intake] .in-tag[data-tone="danger"]{color:var(--danger);background:var(--danger-soft)}
[data-intake] .in-tag[data-tone="warn"]{color:var(--gold);background:color-mix(in srgb,var(--gold) 14%,transparent)}
[data-intake] .in-tag[data-tone="success"],[data-intake] .in-tag[data-tone="info"]{color:var(--brand-text);background:color-mix(in srgb,var(--brand-text) 14%,transparent)}
[data-intake] .in-transcript textarea{width:100%;box-sizing:border-box;min-height:84px;padding:10px 12px;border-radius:12px;border:1px solid var(--line-strong);background:var(--input);color:var(--ink);font:inherit;font-size:14px;line-height:1.6;resize:vertical;outline:none}
[data-intake] .in-transcript textarea:focus{border-color:var(--brand-text)}
[data-intake] .in-tr-empty{font-size:13px;line-height:1.55;color:var(--faint)}
[data-intake] .in-tr-actions{display:flex;justify-content:flex-end;gap:8px}
[data-intake] .in-ftype{flex:none;min-width:34px;height:22px;padding:0 6px;box-sizing:border-box;border-radius:6px;display:grid;place-items:center;font-size:10px;font-weight:800;letter-spacing:.04em;color:#ff8a80;background:color-mix(in srgb,#ff8a80 14%,transparent)}
[data-intake] .in-ftype[data-k="IMG"]{color:#6aa8ff;background:color-mix(in srgb,#6aa8ff 14%,transparent)}
[data-intake] .in-ftype[data-k="DOC"]{color:var(--gold);background:color-mix(in srgb,var(--gold) 14%,transparent)}
[data-intake] .in-role,[data-intake] .in-prov{position:relative;overflow:hidden;border:1px solid color-mix(in srgb,var(--c) 14%,var(--line));background:radial-gradient(120% 110% at 100% 0%,color-mix(in srgb,var(--c) 13%,transparent) 0%,transparent 55%),linear-gradient(180deg,color-mix(in srgb,var(--surface) 84%,#fff 16%) 0%,color-mix(in srgb,var(--surface) 94%,#fff 6%) 45%,var(--surface) 100%);box-shadow:inset 0 1px 0 rgba(255,255,255,.14),inset 0 -3px 0 rgba(0,0,0,.22),0 2px 3px rgba(0,0,0,.18),0 14px 28px -14px rgba(0,0,0,.7);transition:transform .22s cubic-bezier(.22,1,.36,1),box-shadow .22s ease,border-color .18s ease,background .18s ease}
[data-intake] .in-role{border-radius:20px;padding:18px}
[data-intake] .in-prov{border-radius:16px}
[data-intake] .in-role:hover,[data-intake] .in-prov:hover{border-color:color-mix(in srgb,var(--c) 45%,var(--line));background:radial-gradient(120% 110% at 100% 0%,color-mix(in srgb,var(--c) 20%,transparent) 0%,transparent 60%),linear-gradient(180deg,color-mix(in srgb,var(--surface) 80%,#fff 20%) 0%,color-mix(in srgb,var(--surface) 92%,#fff 8%) 45%,var(--surface) 100%);box-shadow:inset 0 1px 0 rgba(255,255,255,.18),inset 0 -3px 0 rgba(0,0,0,.22),0 2px 3px rgba(0,0,0,.18),0 18px 32px -16px color-mix(in srgb,var(--c) 70%,#000)}
[data-intake] .in-role[aria-checked="true"],[data-intake] .in-prov[aria-checked="true"]{border-color:color-mix(in srgb,var(--c) 70%,transparent);background:radial-gradient(120% 120% at 100% 0%,color-mix(in srgb,var(--c) 26%,transparent) 0%,transparent 60%),linear-gradient(180deg,color-mix(in srgb,var(--c) 18%,color-mix(in srgb,var(--surface) 86%,#fff 14%)) 0%,color-mix(in srgb,var(--c) 8%,var(--surface)) 100%);box-shadow:inset 0 1px 0 rgba(255,255,255,.16),inset 0 -3px 0 rgba(0,0,0,.2),0 0 0 3px color-mix(in srgb,var(--c) 16%,transparent),0 16px 30px -20px color-mix(in srgb,var(--c) 70%,#000)}
[data-intake] .in-role::after,[data-intake] .in-prov::after{content:"";position:absolute;top:0;bottom:0;left:0;width:45%;pointer-events:none;background:linear-gradient(90deg,transparent,rgba(255,255,255,.035),transparent);transform:translateX(-130%) skewX(-20deg)}
[data-intake] .in-role:hover::after,[data-intake] .in-prov:hover::after{animation:inShine .85s ease}
[data-intake] .in-role:hover,[data-intake] .in-prov:hover{transform:translateY(-3px)}
[data-intake] .in-role:active,[data-intake] .in-prov:active{transform:translateY(-1px) scale(.99)}
@keyframes inShine{from{transform:translateX(-130%) skewX(-20deg)}to{transform:translateX(330%) skewX(-20deg)}}
@keyframes inUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){[data-intake] *{animation:none!important;transition:none!important}}`;

// What each province means for the case (shown under its name).
const PROVINCE_NOTE = {
    punjab: "Lahore, Rawalpindi, Multan…",
    sindh: "Karachi, Hyderabad, Sukkur…",
    kpk: "Peshawar, Mardan, Swat…",
    balochistan: "Quetta, Gwadar, Turbat…",
    federal: "Islamabad (ICT)",
};
// Each province's own accent (2026-10-11), from the same palette as the
// Lawyers page's area chips so the whole client UI shares one set of hues:
// Punjab's green, Sindh's ajrak red, KPK's glacier blue, Balochistan's desert
// gold, and a quiet violet for the capital.
const PROVINCE_COLOR = {
    punjab: "#5AD69A", sindh: "#F28B80", kpk: "#6ADDEB", balochistan: "#F2C35E", federal: "#B9A6F2",
};
const PROVINCE_SHORT = { punjab: "Punjab", sindh: "Sindh", kpk: "KPK", balochistan: "Balochistan", federal: "Federal" };

// A landmark for each province (2026-10-11): duotone line drawings in the
// theme's own colour -- a soft tinted fill under a crisp outline.
const _pi = (children) => (
    <svg width={34} height={34} viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{children}</svg>
);
const _tint = { fill: "currentColor", fillOpacity: 0.2 };
const PROVINCE_ICON = {
    // Minar-e-Pakistan, Lahore: the flared base, the tapering shaft, the kiosk.
    punjab: _pi(<>
        <path {..._tint} d="M11 41c2.5-6 6-9.5 9.5-11h7c3.5 1.5 7 5 9.5 11z" />
        <path {..._tint} d="M20.6 30 22 10h4l1.4 20z" />
        <path d="M21.2 22h5.6M21.6 16h4.8" />
        <path {..._tint} d="M21.5 10V8.2a2.5 2.5 0 0 1 5 0V10z" />
        <path d="M24 5.7V3M7 41h34" />
    </>),
    // Makli, Thatta: a domed tomb on an arcaded base, with corner kiosks.
    sindh: _pi(<>
        <path {..._tint} d="M10 41V25h28v16" />
        <path d="M16 41v-7a3 3 0 0 1 6 0v7M26 41v-7a3 3 0 0 1 6 0v7" />
        <path d="M14.5 25v-3h19v3" />
        <path {..._tint} d="M16 22c0-6.2 3.6-10 8-10s8 3.8 8 10z" />
        <path d="M24 12V8.5M9 25c0-3 1.4-4.6 3-4.6s3 1.6 3 4.6M33 25c0-3 1.4-4.6 3-4.6s3 1.6 3 4.6M6 41h36" />
    </>),
    // Bab-e-Khyber: twin crenellated towers and the gate's arch.
    kpk: _pi(<>
        <path {..._tint} d="M8 41V17h8v24M32 41V17h8v24" />
        <path d="M8 17v-3h2v2h4v-2h2v3M32 17v-3h2v2h4v-2h2v3" />
        <path {..._tint} d="M16 41V25h16v16" />
        <path d="M20 41v-8a4 4 0 0 1 8 0v8M16 25v-3h16v3M5 41h38" />
    </>),
    // Balochistan: the province's outline, Quetta marked.
    balochistan: _pi(<>
        <path {..._tint} d="M7 15 15 9l7 2 5-5 8 2 4 6-2 6 4 4-3 6 1 6-5 2-5 3-8-1-7 2-5-1 1-7-3-6 3-6z" />
        <circle cx="31" cy="15" r="2.2" fill="currentColor" stroke="none" />
        <path d="M9 41c2-1 4-1 6 0s4 1 6 0 4-1 6 0" opacity=".55" />
    </>),
    // Faisal Mosque, Islamabad: the tent-like hall between pencil minarets.
    federal: _pi(<>
        <path {..._tint} d="M14 40 24 15l10 25z" />
        <path d="M24 15l-3 25M24 15l3 25" />
        <path d="M8 40V13l1-3.5 1 3.5v27M38 40V13l1-3.5 1 3.5v27" />
        <path d="M12.5 40V19l.8-2.6.8 2.6V40M33.9 40V19l.8-2.6.8 2.6V40" opacity=".6" />
        <path d="M4 40.5h40" />
    </>),
};

const STitle = ({ icon, sub, children }) => {
    const t = useT();
    return (
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
            <Ic n={icon} s={18} c={t.primary} />
            <div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>{children}</div>
            {sub && <div style={{ marginLeft: "auto", fontSize: 11, color: t.textMuted }}>{sub}</div>}
        </div>
    );
};

/* ══════════════════════════════════════════════════════
   MODULE: LEGAL INTAKE
══════════════════════════════════════════════════════ */
const ModIntake = () => {
    const t      = useT();
    const toast  = useToast();
    const router = useRouter();
    const { T, lang } = useLang();
    const isMobile = useIsMobile();
    const { completeIntake, addNotification } = useCase();
    const { user } = useAuth();
    const userId = user?._id || user?.id || null;

    // Every remembered intake value is keyed by the signed-in user. See
    // intakeStorage.js for why a shared key left the NEXT account unable to
    // start an intake at all.
    const scopedGet    = (name)        => readIntakeValue(name, userId);
    const scopedSet    = (name, value) => writeIntakeValue(name, userId, value);
    const scopedRemove = (name)        => clearIntakeValue(name, userId);
    const [step, setStep] = useState(1);

    // ── Core intake fields ─────────────────────────────────────────
    const [role, setRole] = useState("");
    const [province, setProvince] = useState("");
    const [caseTypeInput, setCaseTypeInput] = useState("");
    const [urgency, setUrgency] = useState("medium");
    const [description, setDescription] = useState("");

    // ── Backend session ────────────────────────────────────────────
    const [intakeToken, setIntakeToken] = useState(null);
    const [intakeBootError, setIntakeBootError] = useState("");
    const [intakeBooting, setIntakeBooting] = useState(false);
    const intakeBootInFlight = useRef(null);
    const [intakeSubmitting, setIntakeSubmitting] = useState(false);
    const [converting, setConverting] = useState(false);
    // Whether the draft has been promoted. Drives the final screen, which
    // must not claim a case is ready while it is still a draft.
    const [caseConfirmed, setCaseConfirmed] = useState(false);
    const [caseId, setCaseId] = useState(null);
    // The category the CASE currently holds, as opposed to the one selected in
    // the UI. Keeping them apart is what lets the final step tell an actual
    // change from a confirmation and skip a pointless write.
    const [convertedCaseType, setConvertedCaseType] = useState(null);

    // ── AI output ─────────────────────────────────────────────────
    const [aiStructured, setAiStructured] = useState(null);

    // ── P2: Multi-round AI clarification ──────────────────────────
    const [clarifyLoading, setClarifyLoading] = useState(false);
    const [clarifyQ1, setClarifyQ1]           = useState("");
    const [clarifyA1, setClarifyA1]           = useState("");
    const [clarifyQ2, setClarifyQ2]           = useState("");
    const [clarifyA2, setClarifyA2]           = useState("");
    const [clarifyQ3, setClarifyQ3]           = useState("");
    const [clarifyA3, setClarifyA3]           = useState("");
    const [clarifyQ4, setClarifyQ4]           = useState("");
    const [clarifyA4, setClarifyA4]           = useState("");
    const [clarifyRound, setClarifyRound]     = useState(0);  // 0=loading 1=Q1 2=Q2 3=Q3 4=Q4 5=done
    const [clarifyDone, setClarifyDone]       = useState(false);

    // ── Evidence + desired outcome (collected in step 2, saved on convert) ──
    const [hasEvidence, setHasEvidence]       = useState(false);
    const [evidenceDesc, setEvidenceDesc]     = useState("");
    const [evidenceFiles, setEvidenceFiles]   = useState([]); // [{file_id,filename,size,content_type,uploading,error}]
    const [ocrReviewRequired, setOcrReviewRequired] = useState(false);
    const [ocrReviewPages, setOcrReviewPages] = useState([]);
    const [ocrReviewLoading, setOcrReviewLoading] = useState(false);
    const [ocrConfirming, setOcrConfirming] = useState(null);
    const [ocrReviewError, setOcrReviewError] = useState("");
    const [ocrReviewFileIds, setOcrReviewFileIds] = useState([]);
    const fileInputRef                        = useRef(null);
    const [desiredOutcome, setDesiredOutcome] = useState("");

    // ── UI helpers ─────────────────────────────────────────────────
    const [autosave, setAutosave] = useState(false);
    const steps = [
        T("Select Role", "کردار منتخب کریں"),
        T("Case Input", "کیس کی تفصیل"),
        T("AI Questions", "اے آئی سوالات"),
        T("Case Summary", "کیس کا خلاصہ"),
        T("Categorization", "درجہ بندی"),
    ];
    const completedSteps = Math.max(0, step - 1);
    const [fileOpen, setFileOpen] = useState(false);
    const caseTypePicked = useRef(false);
    // The rail (2026-10-10): each step's name, and a line saying what was
    // chosen once it is done. The case file shows the same answers.
    const caseTypeName = CASE_TYPES.find(c => c.value === caseTypeInput)?.label?.replace(" Law", "") || "";
    const answeredCount = [clarifyA1, clarifyA2, clarifyA3, clarifyA4].filter(a => (a || "").trim()).length;
    const readyFiles = evidenceFiles.filter(f => f.file_id && !f.uploading && !f.error).length;
    const filesText = readyFiles ? `${readyFiles} ${readyFiles === 1 ? T("file", "فائل") : T("files", "فائلیں")}` : "";
    const roleName = role === "Plaintiff" ? T("Plaintiff", "مدعی") : role === "Defendant" ? T("Defendant", "مدعا علیہ") : "";
    const railSteps = [
        { title: T("About you", "آپ کے بارے میں"), text: T("Role and province", "کردار اور صوبہ"),
          doneText: [roleName, PROVINCE_SHORT[province]].filter(Boolean).join(" · ") },
        { title: T("Your story", "آپ کی کہانی"), text: T("What happened, evidence", "کیا ہوا، ثبوت"),
          doneText: [caseTypeName, filesText].filter(Boolean).join(" · ") },
        { title: T("A few questions", "چند سوالات"), text: T("Up to 4, from the AI", "اے آئی سے، زیادہ سے زیادہ 4"),
          nowText: clarifyRound >= 1 && clarifyRound <= 4 ? `${T("Question", "سوال")} ${clarifyRound} ${T("of up to 4", "از 4")}` : "",
          doneText: answeredCount ? `${answeredCount} ${T("answered", "جواب دیے")}` : clarifyDone ? T("No questions needed", "سوال کی ضرورت نہیں") : "" },
        { title: T("Review", "جائزہ"), text: T("Your structured case", "آپ کا منظم کیس"), doneText: T("Summary checked", "خلاصہ دیکھ لیا") },
        { title: T("Confirm", "تصدیق"), text: T("Category, then a lawyer", "زمرہ، پھر وکیل") },
    ];
    const caseFileRows = [
        [T("Role", "کردار"), roleName, step === 1],
        [T("Province", "صوبہ"), PROVINCE_SHORT[province] || "", step === 1],
        [T("Case type", "کیس کی قسم"), caseTypeName, step === 2],
        [T("Urgency", "فوریت"), step >= 2 && urgency ? urgency.charAt(0).toUpperCase() + urgency.slice(1) : "", step === 2],
        [T("Evidence", "ثبوت"), filesText, step === 2],
        [T("Questions", "سوالات"), answeredCount ? `${answeredCount} ${T("of up to 4", "از 4")}` : "", step === 3],
    ];
    const caseFileFilled = caseFileRows.filter(r => r[1]).length;
    const progress = (completedSteps / steps.length) * 100;
    const ocrReviewComplete = ocrReviewFileIds.length > 0
        && ocrReviewPages.length > 0
        && ocrReviewFileIds.every(fileId =>
            ocrReviewPages.some(page => page.file_id === fileId)
        )
        && ocrReviewPages.every(page => page.confirmed === true);

    // ── Evidence removal, on the SERVER ────────────────────────────
    //
    // The ✕ used to do `setEvidenceFiles(prev => prev.filter(...))` and nothing
    // else. The row vanished, the file stayed on disk and on the intake for
    // ever, the per-intake quota still counted it, and the AI analysis still
    // described it as uploaded. The client had every reason to believe it was
    // gone.
    const [removingFile, setRemovingFile] = useState(null);

    const loadOcrReview = async (token, files) => {
        const ids = (files || []).map(f => f.file_id).filter(Boolean);
        setOcrReviewFileIds(ids);
        setOcrReviewError("");
        setOcrReviewLoading(true);
        const responses = await Promise.all(
            ids.map(fileId => getIntakeOcrReview(token, fileId))
        );
        if (responses.some(result => result.error)) {
            setOcrReviewError("Could not load the extracted text.");
            toast.show("Could not load the extracted text. Try again.", "error");
            setOcrReviewLoading(false);
            return false;
        }
        const pagesByFile = responses.map(({ data }, index) =>
            (Array.isArray(data) ? data : [])
                .filter(page => page?.file_id === ids[index])
                .map(page => ({
                    ...page,
                    draft_text: page.confirmed_text ?? page.text ?? "",
                }))
        );
        if (ids.length > 0 && pagesByFile.some(pages => pages.length === 0)) {
            setOcrReviewError("One or more extracted files has no current review pages.");
            toast.show(
                "One or more extracted files has no current review pages. Reload the intake before continuing.",
                "error",
            );
            setOcrReviewPages([]);
            setOcrReviewLoading(false);
            return false;
        }
        const pages = pagesByFile.flat();
        setOcrReviewPages(pages);
        setOcrReviewLoading(false);
        return true;
    };

    const confirmOcrPage = async page => {
        setOcrConfirming(page.revision_id);
        const { error } = await confirmIntakeOcrPage(
            intakeToken,
            page.file_id,
            page.revision_id,
            {
                source_sha256: page.source_sha256,
                text_sha256: page.text_sha256,
                confirmed_text: page.draft_text,
            },
        );
        setOcrConfirming(null);
        if (error) {
            toast.show(error?.message || "Could not confirm this page. Reload and try again.", "error");
            return;
        }
        setOcrReviewPages(prev => prev.map(p =>
            p.revision_id === page.revision_id
                ? { ...p, confirmed: true, review_state: "confirmed", confirmed_text: p.draft_text }
                : p
        ));
    };

    const removeEvidence = async (ef) => {
        // A row that never reached the server (a failed upload) has nothing to
        // delete; drop it locally.
        if (!intakeToken || ef.error || !ef.file_id) {
            setEvidenceFiles(prev => prev.filter(x => x.file_id !== ef.file_id));
            return;
        }
        setRemovingFile(ef.file_id);
        const { error } = await deleteIntakeEvidence(intakeToken, ef.file_id);
        setRemovingFile(null);
        if (error) {
            toast.show(error.message || "Could not remove that file. Please try again.", "error", 3500);
            return;   // keep the row: the file is still there
        }
        setEvidenceFiles(prev => prev.filter(x => x.file_id !== ef.file_id));
        toast.show("File removed.", "success", 2000);
    };

    const downloadEvidence = async (ef) => {
        if (!intakeToken || !ef.file_id) return;
        const result = await downloadIntakeEvidence(
            intakeToken, ef.file_id, ef.filename
        );
        if (result?.error) {
            toast.show(result.error || "Could not download that file.", "error", 3500);
        }
    };

    // ── Export helpers ─────────────────────────────────────────────
    //
    // EVERY value below goes through esc(). The print view is built as a string
    // and handed to document.write(), so an unescaped value is markup: a
    // description containing an <img onerror> tag executed in a popup that
    // shares this origin — able to read the intake token out of localStorage
    // and call the API as the signed-in client.
    //
    // The client's own description is the obvious source, but not the only one:
    // the AI summary, the law list and each citation's note are model output
    // derived from retrieved corpus text, and none of it is trusted markup.
    const esc = escapeHtml;

    const _buildPrintHTML = () => {
        const caseTypeLabel = CASE_TYPES.find(c => c.value === caseTypeInput)?.label || caseTypeInput;
        const provinceLabel = PROVINCES.find(p => p.value === province)?.label || province;
        const date = new Date().toLocaleDateString("en-PK", { year: "numeric", month: "long", day: "numeric" });

        const laws = aiStructured?.applicable_laws?.length
            ? aiStructured.applicable_laws.map((l, i) => `<li>${i + 1}. ${esc(l)}</li>`).join("")
            : "<li>Not available</li>";
        const actions = aiStructured?.recommended_actions?.length
            ? aiStructured.recommended_actions.map((a, i) => `<li>${i + 1}. ${esc(a)}</li>`).join("")
            : "<li>Not available</li>";

        return `<!DOCTYPE html><html><head><meta charset="utf-8"/>
<title>Case Summary — Attorney.AI</title>
<style>
  body{font-family:'Segoe UI',sans-serif;color:#1a1a1a;margin:0;padding:40px;background:#fff;font-size:13px}
  h1{font-size:20px;margin:0 0 4px}
  h2{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#00c2a8;margin:22px 0 8px;padding-bottom:6px;border-bottom:1px solid #e5e5e5}
  .header{display:flex;justify-content:space-between;align-items:flex-start;padding-bottom:16px;border-bottom:2px solid #00c2a8;margin-bottom:24px}
  .brand{font-size:18px;font-weight:800;color:#00c2a8}
  .meta{font-size:11px;color:#666;text-align:right;line-height:1.8}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:4px}
  .field{background:#f8f8f8;border-radius:6px;padding:10px 14px}
  .field-label{font-size:10px;text-transform:uppercase;letter-spacing:0.8px;color:#888;margin-bottom:4px}
  .field-value{font-size:13px;font-weight:600;color:#1a1a1a}
  .summary{background:#f8f8f8;border-radius:8px;padding:14px 18px;line-height:1.7;color:#333}
  ul{margin:0;padding-left:18px;line-height:2}
  .risk{display:inline-block;padding:4px 12px;border-radius:20px;font-weight:700;font-size:12px;text-transform:uppercase}
  .risk-low{background:#d1fae5;color:#065f46} .risk-medium{background:#fef3c7;color:#92400e}
  .risk-high{background:#fee2e2;color:#991b1b} .risk-urgent{background:#fee2e2;color:#991b1b}
  .disclaimer{margin-top:32px;padding:12px 16px;background:#fff8e1;border-left:3px solid #f59e0b;font-size:11px;color:#78350f;line-height:1.6;border-radius:0 6px 6px 0}
  @media print{body{padding:20px}button{display:none}}
</style></head><body>
<div class="header">
  <div><div class="brand">Attorney.AI</div><h1>Legal Case Summary</h1></div>
  <div class="meta">
    <div>Case ID: ${caseId ? `…${esc(caseId.slice(-8))}` : "Pending"}</div>
    <div>Date: ${esc(date)}</div>
    <div>Status: Ready</div>
  </div>
</div>

<h2>Case Details</h2>
<div class="grid">
  <div class="field"><div class="field-label">Case Type</div><div class="field-value">${esc(caseTypeLabel)}</div></div>
  <div class="field"><div class="field-label">Province</div><div class="field-value">${esc(provinceLabel)}</div></div>
  <div class="field"><div class="field-label">Your Role</div><div class="field-value">${esc(role || "Not specified")}</div></div>
  <div class="field"><div class="field-label">Urgency</div><div class="field-value">${esc(urgency)}</div></div>
</div>

<h2>Case Summary</h2>
<div class="summary">${esc(aiStructured?.summary || description || "Not available")}</div>

<h2>Applicable Laws</h2>
<ul>${laws}</ul>

<h2>Recommended Actions</h2>
<ul>${actions}</ul>
${aiStructured?.grounding_status && aiStructured.grounding_status !== "grounded"
                ? `<p class="disclaimer" style="margin-top:8px">⚠️ ${esc(GROUNDING_NOTE[aiStructured.grounding_status] || GROUNDING_NOTE.unverified)}</p>`
                : ""}

${aiStructured?.risk_level ? `<h2>Risk Assessment</h2><span class="risk risk-${esc(aiStructured.risk_level)}">${esc(aiStructured.risk_level)} risk</span>` : ""}

<div class="disclaimer">
  <strong>Disclaimer:</strong> This case summary is generated by an AI system for general informational purposes only and does not constitute legal advice. Please consult a qualified Pakistani lawyer before taking any legal action.
</div>
</body></html>`;
    };

    const _buildTextSummary = () => {
        const caseTypeLabel = CASE_TYPES.find(c => c.value === caseTypeInput)?.label || caseTypeInput;
        const provinceLabel = PROVINCES.find(p => p.value === province)?.label || province;
        const date = new Date().toLocaleDateString("en-PK", { year: "numeric", month: "long", day: "numeric" });
        const laws = aiStructured?.applicable_laws?.join("\n  • ") || "Not available";
        const actions = aiStructured?.recommended_actions?.join("\n  • ") || "Not available";
        return [
            `ATTORNEY.AI — LEGAL CASE SUMMARY`,
            `Generated: ${date}`,
            `Case ID: ${caseId || "Pending"}`,
            ``,
            `CASE DETAILS`,
            `Type: ${caseTypeLabel}`,
            `Province: ${provinceLabel}`,
            `Role: ${role || "Not specified"}`,
            `Urgency: ${urgency}`,
            ``,
            `SUMMARY`,
            aiStructured?.summary || description || "Not available",
            ``,
            `APPLICABLE LAWS`,
            `  • ${laws}`,
            ``,
            `RECOMMENDED ACTIONS`,
            `  • ${actions}`,
            aiStructured?.grounding_status && aiStructured.grounding_status !== "grounded"
                ? `  ! ${GROUNDING_NOTE[aiStructured.grounding_status] || GROUNDING_NOTE.unverified}`
                : "",
            aiStructured?.risk_level ? `\nRISK LEVEL: ${aiStructured.risk_level.toUpperCase()}` : "",
            ``,
            `DISCLAIMER: This summary is AI-generated for informational purposes only and does not constitute legal advice. Consult a qualified Pakistani lawyer before taking any action.`,
        ].join("\n");
    };

    const handleDownloadPDF = () => {
        const win = window.open("", "_blank");
        if (!win) { toast.show("Please allow pop-ups to download the PDF", "warn", 3000); return; }
        win.document.write(_buildPrintHTML());
        win.document.close();
        win.onload = () => { win.focus(); win.print(); };
    };

    const handlePrint = () => {
        const win = window.open("", "_blank");
        if (!win) { toast.show("Please allow pop-ups to print", "warn", 3000); return; }
        win.document.write(_buildPrintHTML());
        win.document.close();
        win.onload = () => { win.focus(); win.print(); };
    };

    const handleEmail = () => {
        const subject = encodeURIComponent(`Legal Case Summary — Attorney.AI${caseId ? ` (${caseId.slice(-8)})` : ""}`);
        const body = encodeURIComponent(_buildTextSummary());
        window.location.href = `mailto:?subject=${subject}&body=${body}`;
    };

    // What each step forward actually requires. Steps 3+ used to need only
    // role + province, the same as step 2, so the stepper let a client jump
    // straight from the first screen to the last and reach a "Case Intake
    // Complete" screen with no description, no analysis and no case in the
    // database — the Case ID simply read "Pending".
    //
    // Going BACK is always allowed; only moving ahead of your own progress is
    // gated.
    const stepBlocker = (target) => {
        // A CONVERTED intake cannot be edited. `save_step` refuses a completed
        // intake, so walking back to the questionnaire ends in "Intake already
        // completed" — an error about a screen the stepper invited them onto.
        // Once a case exists, the earlier steps are history.
        if (caseId && target < 4) {
            return "This case has already been analysed — its details can no longer be edited here";
        }
        if (target <= step) return null;
        if (!role) return "Please select your role first";
        if (!province) return "Please select your province";
        if (target >= 3 && !(description.trim() || voiceTranscript.trim()))
            return "Please describe your legal issue before continuing";
        if (target >= 4 && !caseId)
            return "Your case is still being prepared — finish step 3 first";
        // Step 5 is the confirmation screen. Reaching it is safe: the case
        // remains a draft until its final button atomically saves the chosen
        // category and promotes it to open.
        return null;
    };

    const canGoToStep = (target) => stepBlocker(target) === null;

    const tryGoToStep = (target) => {
        const blocker = stepBlocker(target);
        if (blocker) toast.show(blocker, "warn", 2500);
        else setStep(target);
    };

    useEffect(() => {
        if (step > 1) {
            setAutosave(true);
            const timer = setTimeout(() => {
                toast.show("Form auto-saved", "success", 2000);
                setAutosave(false);
            }, 500);
            return () => clearTimeout(timer);
        }
    }, [step]);

    // Put the form back the way the client left it.
    //
    // The token was the ONLY thing a refresh restored, so the browser held a
    // session pointing at a half-filled intake and showed every field blank.
    // The answers were on the server the whole time; nothing asked for them.
    //
    // Only fills fields that are still empty. A restore that overwrote what the
    // client is currently typing would be a worse bug than the one it fixes —
    // this effect can run after the user has already started.
    const restoreFromServer = (data) => {
        const steps = data?.steps || {};
        const s1 = steps["1"] || {};
        const s2 = steps["2"] || {};
        const s3 = steps["3"] || {};
        const s4 = steps["4"] || {};
        const s5 = steps["5"] || {};

        if (s1.party_role) setRole(r => r || (s1.party_role === "plaintiff" ? "Plaintiff" : "Defendant"));
        if (s1.province) setProvince(p => p || s1.province);
        if (s2.case_type) setCaseTypeInput(c => c || s2.case_type);
        if (s2.urgency) setUrgency(u => (u === "medium" ? s2.urgency : u));
        if (s3.incident_description) setDescription(d => d || s3.incident_description);
        if (typeof s4.has_evidence === "boolean") setHasEvidence(h => h || s4.has_evidence);
        if (s4.evidence_description) setEvidenceDesc(e => e || s4.evidence_description);
        if (s5.desired_outcome) setDesiredOutcome(o => o || s5.desired_outcome);

        // Uploaded files, so the ✕ and the list describe what the SERVER holds
        // rather than what this page happens to remember having sent.
        if (Array.isArray(data?.evidence_files) && data.evidence_files.length) {
            setEvidenceFiles(prev => (prev.length ? prev : data.evidence_files));
        }

        // Clarification is an ordered Q&A list; rounds are positions in it.
        const qa = Array.isArray(data?.clarification_qa) ? data.clarification_qa : [];
        if (qa.length) {
            const setQ = [setClarifyQ1, setClarifyQ2, setClarifyQ3, setClarifyQ4];
            const setA = [setClarifyA1, setClarifyA2, setClarifyA3, setClarifyA4];
            qa.slice(0, 4).forEach((entry, i) => {
                if (entry?.q) setQ[i](v => v || entry.q);
                if (entry?.a) setA[i](v => v || entry.a);
            });
            // The round to resume on is the first unanswered question, or done.
            const firstOpen = qa.findIndex(e => !e?.a);
            if (firstOpen === -1) {
                setClarifyDone(true);
                setClarifyRound(5);
            } else {
                setClarifyRound(r => r || Math.min(firstOpen + 1, 4));
            }
        }
    };

    // Start or resume intake session on mount.
    //
    // Waits for the user id: the storage key contains it, so reading before
    // sign-in resolves would miss a resumable token and mint a second session.
    // Everything needed to put the client back into an intake, from one
    // response. Shared by the token path and the server-resume path below, so
    // the two cannot drift into restoring different things.
    const adoptIntake = (data) => {
        // Case data wins over historical step 2 input. The AI may have
        // corrected it, or the client may have confirmed an override later.
        if (data.case_type) {
            setCaseTypeInput(data.case_type);
            setConvertedCaseType(data.case_type);
        } else if (data.ai_case_type) {
            setConvertedCaseType(data.ai_case_type);
        }
        if (data.case_id) {
            setCaseId(data.case_id);
            scopedSet("aai-case-id", data.case_id);
            // The CASE says whether it was confirmed; the intake only says a
            // case was produced. Without this a refresh would offer to confirm
            // an already-open case.
            if (data.case_status && data.case_status !== "draft") {
                setCaseConfirmed(true);
            }
        }
        if (data.ai_structured_case?.summary &&
            data.ai_structured_case.summary !== "pending") {
            setAiStructured(data.ai_structured_case);
        }
        restoreFromServer(data);

        if (data.ocr_review_required) {
            setOcrReviewRequired(true);
            const reviewFiles = (data.evidence_files || []).filter(
                f => f.ocr_review_required
            );
            void loadOcrReview(data.session_token, reviewFiles);
        }

        // WHERE they were, not just WHAT they typed.
        //
        // `current_step` was returned by the API and read by nothing, so a
        // refresh mid-intake restored every answer and then showed step 1 — the
        // client had to click forward through screens they had already
        // completed, re-reading their own answers to work out where they were.
        //
        // Capped at 3 for an unfinished intake: step 4 is the analysis screen
        // and needs a case, which only conversion produces.
        if (data.completed) {
            setStep(s => (s < 4 ? 4 : s));
        } else {
            const at = Number(data.current_step) || 1;
            setStep(s => (s > 1 ? s : Math.min(Math.max(at, 1), 3)));
        }
    };

    // ASK THE SERVER, then start fresh only if it has nothing.
    //
    // Resuming used to depend entirely on the token in this browser's storage.
    // Sign-out clears it, clearing site data clears it, and a second device
    // never had it — and after conversion that token is the only route to a
    // draft case awaiting confirmation. So signing out between converting and
    // confirming left a real case its owner could never confirm and this screen
    // could never find. The server knows which intakes are unfinished.
    const resumeOrStart = async () => {
        if (intakeBootInFlight.current) return intakeBootInFlight.current;
        const work = (async () => {
            setIntakeBooting(true);
            setIntakeBootError("");
            const { data: resumable, error: resumeError } = await getResumableIntake();
            if (resumeError) {
                // Unknown is not empty. Starting here would create another
                // intake precisely when the server failed to tell us whether
                // one already exists.
                setIntakeBootError("Could not check your saved intake. Try again when your connection is stable.");
                return;
            }
            if (resumable?.session_token) {
                setIntakeToken(resumable.session_token);
                scopedSet("aai-intake-token", resumable.session_token);
                adoptIntake(resumable);
                return;
            }
            const { data: started, error } = await intakeStart();
            if (started?.session_token) {
                setIntakeToken(started.session_token);
                scopedSet("aai-intake-token", started.session_token);
            } else if (error) {
                setIntakeBootError("Could not start an intake. Please try again.");
            }
        })().finally(() => {
            setIntakeBooting(false);
            intakeBootInFlight.current = null;
        });
        intakeBootInFlight.current = work;
        return work;
    };

    useEffect(() => {
        if (!userId) return;
        const saved = scopedGet("aai-intake-token");
        if (!saved) {
            resumeOrStart();
            return;
        }
        setIntakeToken(saved);
        intakeGet(saved).then(({ data, error }) => {
            if (error || !data) {
                // The token is unusable — expired, or belonging to nobody this
                // account can see. Drop it and ASK THE SERVER rather than
                // starting fresh: an unusable token in storage is exactly the
                // situation where an unfinished intake is most likely to exist.
                scopedRemove("aai-intake-token");
                setIntakeToken(null);
                resumeOrStart();
                return;
            }
            adoptIntake(data);
        });
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [userId]);

    // Trigger clarify fetch whenever step 3 is reached via tab navigation
    // (handleStep2Continue sets clarifyLoading=true before its own fetch, so this
    // guard prevents double-firing on the normal Continue → path)
    useEffect(() => {
        if (step !== 3 || clarifyDone || clarifyRound !== 0 || clarifyLoading || !intakeToken) return;
        setClarifyLoading(true);
        intakeClarify(intakeToken, null, lang).then(({ data, error }) => {
            if (error || !data) { setClarifyDone(true); setClarifyRound(5); }
            else if (data.done)  { setClarifyDone(true); setClarifyRound(5); }
            else if (data.question) { setClarifyQ1(data.question); setClarifyRound(1); }
            setClarifyLoading(false);
        });
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [step, intakeToken]);

    // ── Step 1 → 2: save province ─────────────────────────────────
    const handleStep1Continue = async () => {
        if (!role)     { toast.show("Please select your role first", "warn", 2500); return; }
        if (!province) { toast.show("Please select your province", "warn", 2500); return; }
        if (intakeToken) {
            // party_role goes with it. The Plaintiff/Defendant choice drove the
            // whole first screen and then lived only in React state — it was
            // never sent anywhere, so nothing downstream could tell which side
            // of the dispute the client was on.
            const { error } = await intakeSaveStep(intakeToken, 1, {
                province,
                party_role: role.toLowerCase(),
            });
            // STOP. This used to warn and advance anyway, so a client whose save
            // failed carried on through the whole questionnaire while the server
            // held none of it — and the loss only surfaced at conversion, as a
            // "steps not completed" error about a step they had filled in.
            if (error) {
                toast.show("Could not save — check your connection and try again.", "error", 3500);
                return;
            }
        }
        setStep(2);
    };

    // ── Step 2 → 3: save case_type + urgency + description, fetch Q1 ──
    const handleStep2Continue = async () => {
        const desc = description.trim() || voiceTranscript.trim();
        if (!desc) {
            toast.show("Please describe your legal issue before continuing.", "warn", 2500);
            return;
        }
        // Ensure case type is set — fall back to quick JS classify then "civil"
        const effectiveCaseType = caseTypeInput || quickClassify(desc) || "civil";
        if (!caseTypeInput && effectiveCaseType) setCaseTypeInput(effectiveCaseType);

        if (intakeToken) {
            const r2 = await intakeSaveStep(intakeToken, 2, { case_type: effectiveCaseType, urgency });
            const r3 = await intakeSaveStep(intakeToken, 3, {
                incident_description: desc,
                incident_date: null,
                incident_location: null,
            });
            // Same rule as step 1: the description is the single most important
            // thing the client types, and advancing without it stored means the
            // AI analysis later runs on nothing.
            if (r2.error || r3.error) {
                toast.show("Could not save — check your connection and try again.", "error", 3500);
                setClarifyLoading(false);
                return;
            }
        }
        setStep(3);
        // P2 — fetch Q1 immediately after entering step 3
        if (intakeToken) {
            setClarifyLoading(true);
            setClarifyRound(0);
            const { data, error } = await intakeClarify(intakeToken, null, lang);
            if (error || !data) {
                // API failure — skip clarification so user can still proceed
                setClarifyDone(true);
                setClarifyRound(5);
            } else if (data.done) {
                setClarifyDone(true);
                setClarifyRound(5);
            } else if (data.question) {
                setClarifyQ1(data.question);
                setClarifyRound(1);
            }
            setClarifyLoading(false);
        }
    };

    // ── Step 3: current answer getter ─────────────────────────────
    const getCurrentAnswer = () => {
        if (clarifyRound === 1) return clarifyA1;
        if (clarifyRound === 2) return clarifyA2;
        if (clarifyRound === 3) return clarifyA3;
        return "";
    };

    // ── Step 3 Qn answered → fetch next question (rounds 1–3) ────
    const handleClarifyNext = async () => {
        if (!getCurrentAnswer().trim()) {
            toast.show("Please answer the question before continuing.", "warn", 2000);
            return;
        }
        if (!intakeToken) { setClarifyRound(5); setClarifyDone(true); return; }
        setClarifyLoading(true);
        const { data, error } = await intakeClarify(intakeToken, getCurrentAnswer(), lang);
        if (error || !data || data.done || !data.question) {
            setClarifyDone(true);
            setClarifyRound(5);
        } else {
            if (clarifyRound === 1) { setClarifyQ2(data.question); setClarifyRound(2); }
            else if (clarifyRound === 2) { setClarifyQ3(data.question); setClarifyRound(3); }
            else if (clarifyRound === 3) { setClarifyQ4(data.question); setClarifyRound(4); }
        }
        setClarifyLoading(false);
    };

    // ── Step 3 → 4: save remaining steps, convert, fetch AI ───────
    const handleConvertAndSummarise = async () => {
        if (caseId && aiStructured && !ocrReviewRequired) {
            setStep(4);
            return;
        }

        if (!intakeToken) {
            toast.show("Questionnaire complete", "success");
            setStep(4);
            return;
        }

        setConverting(true);

        // Save final answer to clarification_qa BEFORE convert.
        // convert_to_case reads clarification_qa and appends Q&A to the description itself.
        const lastAnswer = clarifyA4.trim() || clarifyA3.trim() || clarifyA2.trim();
        // 409 = the server has already started or finished converting, i.e. an
        // earlier click got through and only its response was lost (the dev
        // proxy gives up long before a conversion ends). Both writes below are
        // refused in that state, and stopping here left the button dead for
        // good. /convert is idempotent: it replays the finished case, or says
        // the conversion is still running.
        let alreadyConverting = false;
        if (intakeToken && lastAnswer) {
            // The result was discarded. `convert_to_case` folds the stored Q&A
            // into the text it analyses, so a failure here meant the analysis
            // ran without the client's final answer — and nothing said so. They
            // had just typed it, so its absence is invisible to them.
            const { error: clarifyErr, status: clarifyStatus } =
                await intakeClarify(intakeToken, lastAnswer, lang);
            alreadyConverting = clarifyStatus === 409;
            if (clarifyErr && !alreadyConverting) {
                toast.show(
                    "Could not save your last answer — check your connection and try again.",
                    "error", 4000,
                );
                setConverting(false);
                return;   // do NOT analyse without it
            }
        }
        if (!alreadyConverting) {
            const r4 = await intakeSaveStep(intakeToken, 4, {
                has_evidence: hasEvidence,
                evidence_description: evidenceDesc.trim() || null,
                opposing_party: null,
            });
            const r5 = await intakeSaveStep(intakeToken, 5, {
                desired_outcome: desiredOutcome.trim() || "Legal assistance and representation",
                additional_notes: null,
            });
            if (r4.error || r5.error) {
                toast.show("Could not save case details — check your connection and try again.", "error", 3000);
                setConverting(false);
                return;
            }
        }

        const savedToken = intakeToken;
        let analysisFailed = false;
        const { data: converted, error: convErr } = await intakeConvert(savedToken, {
            language: voiceLang?.code || "en",
            urgency,
        });

        if (convErr) {
            // Print exact server error so mismatches are visible in the console
            const msg = convErr?.error || convErr?.detail || JSON.stringify(convErr);
            console.error("Intake /convert error:", msg);
            toast.show(`Convert failed: ${msg}`, "error", 5000);
            setConverting(false);
            return; // do not advance to step 4 on failure
        }

        if (converted?.ocr_review_required) {
            setOcrReviewRequired(true);
            const loaded = await loadOcrReview(
                savedToken,
                Array.isArray(converted.ocr_files) ? converted.ocr_files : [],
            );
            setConverting(false);
            if (loaded) {
                toast.show(
                    "Review the extracted text before AI analysis continues.",
                    "info", 5000,
                );
            }
            return;
        }

        if (converted?.case_id) {
            setCaseId(converted.case_id);
            setConvertedCaseType(converted.ai_case_type || null);
            scopedSet("aai-case-id", converted.case_id);
            // THE TOKEN STAYS until the client confirms.
            //
            // It used to be cleared here, at conversion. That was safe while
            // conversion was the last step — but confirmation now happens
            // afterwards, on the next screen, and the token is the only thing
            // that can reopen the intake. Clearing it here meant a refresh
            // between the two started a brand-new intake and left the draft
            // unreachable AND unconfirmable: a case the client owns, that
            // nothing in the UI can ever promote, for the life of the account.
            //
            // `scopedRemove` moved to handleSubmit, where the intake is
            // genuinely finished.

            // If AI corrected the case type, update UI and notify user
            if (converted.type_was_corrected && converted.ai_case_type) {
                const label = { civil: "Civil", criminal: "Criminal", family: "Family", constitutional: "Constitutional" };
                setCaseTypeInput(converted.ai_case_type);
                toast.show(
                    `Case type updated: ${label[converted.user_case_type] || converted.user_case_type} → ${label[converted.ai_case_type] || converted.ai_case_type}`,
                    "info", 5000
                );
            }
            // Fetch the AI-structured case data
            const { data: intake } = await intakeGet(savedToken);
            if (intake?.ai_structured_case?.summary && intake.ai_structured_case.summary !== "pending") {
                setAiStructured(intake.ai_structured_case);
            }
            analysisFailed = intake?.ai_structured_case?.grounding_status === "pipeline_failed";
        }

        setOcrReviewRequired(false);
        setConverting(false);
        // Say what happened. A case is created even when the AI analysis fails,
        // and "analysis complete" over a screen saying it did not run is false.
        if (analysisFailed) {
            toast.show("Your case was created, but the AI analysis was unavailable. A lawyer can still review it.", "warn", 5000);
        } else {
            toast.show("✅ Case analysis complete", "success", 3000);
        }
        setStep(4);
    };

    // ── Step 4: confirm the draft ──────────────────────────────────
    //
    // This button used to show "✅ Case saved!" and advance the screen. It
    // called nothing: the case had been created and made live back at step 3,
    // so the subtitle inviting the client to "review and confirm before saving"
    // described a save that had already happened and a confirmation with
    // nothing to confirm.
    //
    // The case is now created as a DRAFT, and this is the call that makes it
    // real. Until it lands the case cannot be sent to a lawyer, matched, or
    // booked against.
    const handleContinueToCategory = () => {
        if (!caseId) {
            // No case to confirm — the conversion never completed. Advancing
            // would show a "complete" screen for something that does not exist.
            toast.show("Your case is not ready yet — go back and finish step 3.", "warn", 3500);
            return;
        }
        // The next screen is where the client confirms the authoritative
        // category. Opening the case here allowed matching to observe the old
        // AI category before the client's final choice was persisted.
        setStep(5);
    };

    // ── Final submit (Step 5) ──────────────────────────────────────
    const handleSubmit = async () => {
        setIntakeSubmitting(true);

        if (!caseId || !caseTypeInput) {
            toast.show("Choose a case category before confirming.", "warn", 3000);
            setIntakeSubmitting(false);
            return;
        }

        // One backend CAS stores the category and opens the case. There is no
        // interval in which an open case still carries the superseded type.
        const { error } = await confirmCase(caseId, caseTypeInput);
        if (error) {
            toast.show(error.message || "Could not confirm your case. Please try again.", "error", 4000);
            setIntakeSubmitting(false);
            return;
        }
        setConvertedCaseType(caseTypeInput);
        setCaseConfirmed(true);
        scopedRemove("aai-intake-token");
        setIntakeToken(null);

        completeIntake({
            role,
            caseType:    caseTypeInput,
            province,
            caseId,
            description: description.trim() || voiceTranscript.trim(),
            evidenceDocs: [],
        });
        addNotification({
            type: "status",
            urgency: "info",
            title: "Case Intake Complete",
            date: new Date().toLocaleDateString("en-US", { month: "short", day: "numeric" }),
            time: new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
            desc: `Case structured — ${role} · ${CASE_TYPES.find(c => c.value === caseTypeInput)?.label || caseTypeInput} · ${province}`,
        });
        // WHAT ACTUALLY HAPPENED, not what sounds finished.
        //
        // This said "Case submitted for attorney review!" followed by "You'll
        // hear from us within 2 hours". Conversion creates an OPEN case. It
        // assigns no lawyer, notifies no lawyer, and starts no clock — there is
        // nobody reviewing it and no two-hour commitment behind it. A client who
        // believed that would wait instead of choosing a lawyer, which is the
        // one action that actually moves their matter forward.
        toast.show("Case confirmed — you can now choose a lawyer.", "success", 3000);
        setTimeout(
            () => toast.show(
                "Next: choose a lawyer to send it to — nobody is reviewing it yet.",
                "info", 4500),
            3000,
        );
        setIntakeSubmitting(false);
    };

    // ── Voice state ────────────────────────────────────────────────
    const [inputType, setInputType] = useState("text");
    const [voiceStatus, setVoiceStatus] = useState("idle");
    const isRecording  = voiceStatus === "recording";
    const transcribing = voiceStatus === "transcribing";
    const [recTime, setRecTime] = useState(0);
    const [voiceTranscript, setVoiceTranscript] = useState("");
    const [voiceLang, setVoiceLang] = useState(null);
    const mediaRecorderRef = useRef(null);
    const audioChunksRef  = useRef([]);
    const recTimerRef     = useRef(null);
    const MAX_REC_SECS    = 120;
    const formatTime = (s) => `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')}`;

    useEffect(() => () => clearInterval(recTimerRef.current), []);

    const startRecording = async () => {
        if (!navigator.mediaDevices?.getUserMedia) {
            toast.show("Microphone not supported in this browser.", "error", 3000);
            return;
        }
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            audioChunksRef.current = [];
            const mimeType = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
            const mr = new MediaRecorder(stream, mimeType ? { mimeType } : {});
            mr.ondataavailable = e => { if (e.data.size > 0) audioChunksRef.current.push(e.data); };
            mr.start(250);
            mediaRecorderRef.current = mr;
            setVoiceStatus("recording");
            setRecTime(0);
            recTimerRef.current = setInterval(() => {
                setRecTime(prev => {
                    const next = prev + 1;
                    if (next >= MAX_REC_SECS) {
                        clearInterval(recTimerRef.current);
                        try {
                            mediaRecorderRef.current?.stop();
                            mediaRecorderRef.current?.stream?.getTracks().forEach(tr => tr.stop());
                        } catch {}
                        setVoiceStatus("stopped");
                        return MAX_REC_SECS;
                    }
                    return next;
                });
            }, 1000);
        } catch {
            toast.show("Microphone access denied. Please allow mic permission.", "error", 3000);
        }
    };

    const stopRecording = () => {
        if (!mediaRecorderRef.current || !isRecording) return;
        mediaRecorderRef.current.stop();
        mediaRecorderRef.current.stream.getTracks().forEach(tr => tr.stop());
        clearInterval(recTimerRef.current);
        setVoiceStatus("stopped");
    };

    const handleConvert = async () => {
        if (!audioChunksRef.current.length) {
            toast.show("No recording found. Tap the mic to start.", "warn", 2000);
            return;
        }
        setVoiceStatus("transcribing");
        const rawBlob = new Blob(audioChunksRef.current, {
            type: mediaRecorderRef.current?.mimeType || "audio/webm",
        });
        let sendBlob = rawBlob;
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
            const decoded = await ctx.decodeAudioData(await rawBlob.arrayBuffer());
            sendBlob = _pcmToWav(decoded.getChannelData(0), 16000);
        } catch { /* fallback: send raw blob */ }
        const { data, error } = await transcribeAudio(sendBlob);
        if (error) {
            setVoiceStatus("error");
            toast.show(error.message || "Transcription failed. Try again.", "error", 3000);
            return;
        }
        setVoiceTranscript(data.transcript || "");
        if (data.transcript) {
            setVoiceLang({ name: data.language_name, code: data.language, prob: data.language_probability });
            setVoiceStatus("ready");
            toast.show(`Transcript ready — detected ${data.language_name} (${Math.round(data.language_probability * 100)}%)`, "success", 3000);
        } else {
            setVoiceStatus("error");
        }
    };

    const handleSubmitVoice = () => {
        if (!voiceTranscript.trim()) { toast.show("No transcript to submit.", "warn", 2000); return; }
        setDescription(voiceTranscript);
        const detected = quickClassify(voiceTranscript);
        if (detected) setCaseTypeInput(detected);
        setVoiceStatus("idle");
        setInputType("text");
        toast.show("Voice transcript added to your case.", "success", 2000);
    };

    const VOICE_UI = {
        idle:         { icon: "🎙️", text: "Tap mic to start recording",          color: t.textMuted,  badgeType: null },
        recording:    { icon: "🎤", text: "Recording…",                           color: t.danger,     badgeType: "danger",  badgeLabel: "● REC" },
        stopped:      { icon: "⏸️", text: "Stopped — click Convert to Text",      color: t.warn,       badgeType: "warn",    badgeLabel: "STOPPED" },
        transcribing: { icon: "⏳", text: "Transcribing…",                        color: t.primary,    badgeType: "info",    badgeLabel: "⏳ PROCESSING" },
        ready:        { icon: "✅", text: "Transcript ready — review and submit", color: t.success,    badgeType: "success", badgeLabel: "✅ READY" },
        error:        { icon: "❌", text: "Failed — try again",                   color: t.danger,     badgeType: "danger",  badgeLabel: "❌ FAILED" },
    };
    const vui = VOICE_UI[voiceStatus] || VOICE_UI.idle;

    const selectStyle = {
        width: "100%", padding: "10px 14px", borderRadius: 8,
        border: `1px solid ${t.border}`, background: t.inputBg,
        color: t.text, fontSize: 13, outline: "none", cursor: "pointer",
    };

    return (
        <div data-intake>
            <style>{INTAKE_CSS}</style>
            {intakeBootError && (
                <Card style={{ padding: 16, marginBottom: 16, border: `1px solid ${t.danger}55` }}>
                    <div style={{ color: t.danger, fontSize: 13, marginBottom: 10 }}>{intakeBootError}</div>
                    <BtnOutline disabled={intakeBooting} onClick={resumeOrStart}>
                        {intakeBooting ? "Checking…" : "Try again"}
                    </BtnOutline>
                </Card>
            )}
            {/* The page's own title, as Lawyers and Documents have (2026-10-10). */}
            <div className="in-head">
                <div style={{ flex: 1, minWidth: 0 }}>
                    <h1 className="in-title" style={{ fontFamily: DOCS_FONT }}>{T("Legal Intake", "قانونی درخواست")}</h1>
                    <div className="in-sub" style={{ fontFamily: DOCS_FONT }}>{T("Tell us about your matter — we turn it into a structured case you can send to a lawyer.", "اپنا معاملہ بتائیں — ہم اسے ایک منظم کیس بنا دیں گے جو آپ وکیل کو بھیج سکیں۔")}</div>
                </div>
                <span className="in-meta"><span className="dot" aria-hidden="true" />{T("Saved after each step", "ہر مرحلے کے بعد محفوظ")}</span>
                <button type="button" className="in-filebtn" aria-expanded={fileOpen} aria-controls="in-case-file" onClick={() => setFileOpen(o => !o)}>
                    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M9 13h6M9 17h4" /></svg>
                    {T("Case file", "کیس فائل")}
                    <span className="n" aria-label={`${caseFileFilled} ${T("filled", "بھرے")}`}>{caseFileFilled}</span>
                </button>
            </div>

            {/* The layout (2026-10-10, approved design): steps on the left, the
                step's work in the middle, the case file filling in on the right. */}
            <div className="in-shell">
            <nav className="in-rail" aria-label={T("Intake steps", "مراحل")}>
                {railSteps.map((r, i) => {
                    const targetStep = i + 1;
                    const act = step === targetStep;
                    const done = step > targetStep;
                    const locked = !canGoToStep(targetStep) && !done && !act;
                    return (
                        <button key={r.title} type="button" className="in-rstep" disabled={locked}
                            aria-current={act ? "step" : undefined} data-done={done ? "" : undefined}
                            onClick={() => { if (!act) tryGoToStep(targetStep); }}>
                            <span className="num" aria-hidden="true">
                                {done ? <Ic n="check" s={14} c="currentColor" /> : targetStep}
                            </span>
                            <span style={{ minWidth: 0 }}>
                                {act && <span className="now">{T("Now", "ابھی")}</span>}
                                <span className="t">{r.title}</span>
                                <span className="d">{done && r.doneText ? r.doneText : act && r.nowText ? r.nowText : r.text}</span>
                            </span>
                        </button>
                    );
                })}
                <div className="in-rprog">
                    <div className="bar" aria-hidden="true"><i style={{ width: `${Math.max(6, ((step - 1) / (railSteps.length - 1)) * 100)}%` }} /></div>
                    {step < railSteps.length
                        ? `${T("Step", "مرحلہ")} ${step} ${T("of", "از")} ${railSteps.length}`
                        : T("Last step", "آخری مرحلہ")}
                </div>
            </nav>
            <div className="in-main">

            {/* ── STEP 1: Role + Province ─────────────────────────────── */}
            {step === 1 && (
                <section className="in-card">
                    <header className="in-card-head">
                        <span className="in-card-ic" aria-hidden="true"><Ic n="user" s={20} c="currentColor" /></span>
                        <div>
                            <h2 className="in-card-title">{T("First, who are you in this matter?", "پہلے بتائیں، اس معاملے میں آپ کون ہیں؟")}</h2>
                            <div className="in-card-sub">{T("This decides how we structure your case and which law applies.", "اس سے طے ہوتا ہے کہ کیس کیسے بنے گا اور کون سا قانون لاگو ہوگا۔")}</div>
                        </div>
                    </header>

                    <div className="in-label">{T("Your role", "آپ کا کردار")} <span className="req">*</span></div>
                    <div className="in-roles" role="radiogroup" aria-label={T("Your role", "آپ کا کردار")}>
                        {["Plaintiff", "Defendant"].map(r => {
                            const plaintiff = r === "Plaintiff";
                            return (
                                <button key={r} type="button" role="radio" aria-checked={role === r} className="in-role"
                                    style={{ "--c": plaintiff ? "#3ee0a1" : "#5fd0e6" }} onClick={() => setRole(r)}>
                                    {/* Flaticon icons (credited below), painted in the card's colour
                                        through a CSS mask so they follow the theme. */}
                                    <span className="art" aria-hidden="true">
                                        <span className="glyph" style={{ "--icon": `url(/icons/intake/${plaintiff ? "plaintiff" : "defendant"}.png)` }} />
                                    </span>
                                    <span style={{ minWidth: 0 }}>
                                        <span className="nm">{plaintiff ? T("I'm taking action", "میں کارروائی کر رہا ہوں") : T("Someone acted against me", "میرے خلاف کارروائی ہوئی")}</span>
                                        <span className="ds" style={{ display: "block", color: "var(--c)", fontWeight: 600 }}>{plaintiff ? "Plaintiff · مدعی" : "Defendant · مدعا علیہ"}</span>
                                        <span className="eg" style={{ display: "block" }}>{plaintiff
                                            ? T("e.g. recover money, claim property, seek khula or maintenance.", "مثلاً رقم کی واپسی، جائیداد، خلع یا نان نفقہ")
                                            : T("e.g. you got a legal notice, a summons or an FIR.", "مثلاً قانونی نوٹس، سمن یا ایف آئی آر")}</span>
                                    </span>
                                    <span className="tick" aria-hidden="true"><Ic n="check" s={13} c="currentColor" /></span>
                                </button>
                            );
                        })}
                    </div>

                    <div className="in-credit">Icons: <a href="https://www.flaticon.com/free-icon/question_10032072" target="_blank" rel="noopener noreferrer">Plaintiff</a> · <a href="https://www.flaticon.com/free-icon/suspect_15869444" target="_blank" rel="noopener noreferrer">Defendant</a> — Flaticon</div>
                    <div className="in-label">{T("Where is the matter?", "معاملہ کہاں کا ہے؟")} <span className="req">*</span></div>
                    <div className="in-provs" role="radiogroup" aria-label={T("Province / Territory", "صوبہ / علاقہ")}>
                        {PROVINCES.map(p => (
                            <button key={p.value} type="button" role="radio" aria-checked={province === p.value} className="in-prov" style={{ "--c": PROVINCE_COLOR[p.value] }} onClick={() => setProvince(p.value)}>
                                <span className="pin" aria-hidden="true">{PROVINCE_ICON[p.value]}</span>
                                <b>{PROVINCE_SHORT[p.value] || p.label}</b>
                                <span>{PROVINCE_NOTE[p.value]}</span>
                            </button>
                        ))}
                    </div>
                    <div className="in-hint">{T("Used to apply the correct jurisdiction and legal framework to your case.", "آپ کے کیس پر درست دائرہ اختیار اور قانون لاگو کرنے کے لیے۔")}</div>

                    <footer className="in-foot">
                        <span className="why">{!role || !province
                            ? T("Choose your role and province to continue.", "جاری رکھنے کے لیے کردار اور صوبہ منتخب کریں۔")
                            : T("Next: tell us what happened, in your own words.", "اگلا: اپنے الفاظ میں بتائیں کیا ہوا۔")}</span>
                        <button type="button" className="in-next" disabled={!role || !province} onClick={handleStep1Continue}>
                            {T("Continue", "جاری رکھیں")}
                            <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
                        </button>
                    </footer>
                </section>
            )}

            {/* ── STEP 2: Your story (2026-10-10, approved design) ─────── */}
            {step === 2 && (
                <section className="in-card in-story">
                    <header className="in-card-head" style={{ marginBottom: 16 }}>
                        <span className="in-card-ic" aria-hidden="true"><Ic n="pen" s={19} c="currentColor" /></span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <h2 className="in-card-title">{T("What happened?", "کیا ہوا؟")}</h2>
                            <div className="in-card-sub">{T("Write it in your own words — English or Roman Urdu. Or speak it.", "اپنے الفاظ میں لکھیں — انگریزی یا رومن اردو۔ یا بول کر بتائیں۔")}</div>
                        </div>
                        {/* The REAL case reference, or nothing -- never a made-up number. */}
                        {caseId && <span className="in-ref">{T("Case", "کیس")} …{caseId.slice(-8)}</span>}
                    </header>

                    <div className="in-mode" role="group" aria-label={T("How to describe it", "بیان کا طریقہ")}>
                        {["text", "voice"].map(type => (
                            <button key={type} type="button" aria-pressed={inputType === type} onClick={() => setInputType(type)}>
                                <Ic n={type === "text" ? "pen" : "mic"} s={14} c="currentColor" />
                                {type === "text" ? T("Text Input", "تحریری ان پٹ") : T("Voice Input", "آواز سے ان پٹ")}
                            </button>
                        ))}
                    </div>

                    {inputType === "voice" ? (
                        <div className="in-voice" data-state={voiceStatus}>
                            {/* The recorder: one compact row. */}
                            <div className="in-rec">
                                <button type="button" className="in-mic" aria-pressed={isRecording}
                                    aria-label={isRecording ? T("Stop recording", "ریکارڈنگ روکیں") : T("Start recording", "ریکارڈنگ شروع کریں")}
                                    disabled={transcribing}
                                    onClick={() => (isRecording ? stopRecording() : startRecording())}>
                                    {isRecording ? (
                                        <svg width={16} height={16} viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2.5" fill="currentColor" /></svg>
                                    ) : (
                                        <svg width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="9" y="2.5" width="6" height="11.5" rx="3" /><path d="M5 10.5a7 7 0 0 0 14 0M12 17.5V21M8.5 21h7" /></svg>
                                    )}
                                </button>
                                <div className="in-wave" aria-hidden="true">
                                    {Array.from({ length: 28 }, (_, k) => <i key={k} style={{ animationDelay: `${(k % 7) * 0.09}s`, height: `${30 + ((k * 37) % 55)}%` }} />)}
                                </div>
                                <span className="in-time">{formatTime(recTime)}</span>
                                <button type="button" className="in-ghost" onClick={handleConvert}
                                    disabled={transcribing || isRecording || recTime === 0 || voiceStatus === "ready"}>
                                    <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 7h10M4 12h16M4 17h7" /></svg>
                                    {transcribing ? T("Converting…", "تبدیل ہو رہا ہے…") : T("Convert to Text", "متن میں بدلیں")}
                                </button>
                            </div>
                            <div className="in-vstatus" style={{ color: vui.color }} role="status">
                                <span className="dot" aria-hidden="true" />
                                {vui.text}
                                {isRecording && recTime >= MAX_REC_SECS - 15 && <span style={{ opacity: 0.8 }}>({MAX_REC_SECS - recTime}s left)</span>}
                            </div>

                            {/* What the AI heard -- editable before it is used. */}
                            <div className="in-transcript">
                                <div className="in-tr-head">
                                    <span className="in-bot" aria-hidden="true">
                                        <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="8" width="16" height="12" rx="4" /><path d="M12 4v4M9 13h.01M15 13h.01M9.5 16.5h5" /><circle cx="12" cy="3" r="1" /></svg>
                                    </span>
                                    <b>{T("AI transcription", "اے آئی ٹرانسکرپشن")}</b>
                                    <span style={{ flex: 1 }} />
                                    {vui.badgeType && <span className="in-tag" data-tone={vui.badgeType}>{vui.badgeLabel.replace(/^[^A-Za-z●]+\s*/, "")}</span>}
                                    {voiceLang && <span className="in-tag">{voiceLang.name} · {Math.round(voiceLang.prob * 100)}%</span>}
                                </div>
                                {transcribing ? (
                                    <div className="in-tr-empty">{T("Transcribing audio…", "آڈیو متن میں بدل رہی ہے…")}<span className="in-typing"><i /><i /><i /></span></div>
                                ) : voiceTranscript ? (
                                    <textarea aria-label={T("Transcript", "متن")} value={voiceTranscript} onChange={e => setVoiceTranscript(e.target.value)} />
                                ) : (
                                    <div className="in-tr-empty">{T("Tap the mic, speak, then Convert to Text. You can edit the words before using them.", "مائیک دبائیں، بولیں، پھر متن میں بدلیں۔ استعمال سے پہلے الفاظ درست کر سکتے ہیں۔")}</div>
                                )}
                                <div className="in-tr-actions">
                                    <button type="button" className="in-ghost" disabled={transcribing}
                                        onClick={() => { setVoiceTranscript(""); setVoiceLang(null); audioChunksRef.current = []; setRecTime(0); setVoiceStatus("idle"); }}>{T("Clear", "صاف کریں")}</button>
                                    <button type="button" className="in-next" style={{ height: 38, padding: "0 18px", fontSize: 13 }}
                                        disabled={!voiceTranscript.trim() || transcribing} onClick={handleSubmitVoice}>{T("Submit Voice Input ↑", "آواز کا متن شامل کریں ↑")}</button>
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="in-compose">
                            <label htmlFor="in-story-text" style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>{T("Describe what happened", "بتائیں کیا ہوا")}</label>
                            <textarea id="in-story-text" rows={6}
                                placeholder={T("Please describe the events leading up to your dispute in detail...", "براہ کرم اپنے تنازعے کے واقعات کی تفصیل لکھیں...")}
                                value={description}
                                onChange={e => {
                                    setDescription(e.target.value);
                                    // The browser's guess, until the client picks one themselves.
                                    if (caseTypePicked.current) return;
                                    const detected = quickClassify(e.target.value);
                                    if (detected) setCaseTypeInput(detected);
                                }} />
                            <div className="in-compose-foot">
                                <span>{T("Don't include CNIC or phone numbers", "شناختی کارڈ یا فون نمبر نہ لکھیں")} · {description.length} {T("characters", "حروف")}</span>
                                <span style={{ flex: 1 }} />
                                <button type="button" className="in-ghost" onClick={() => setInputType("voice")}>
                                    <Ic n="mic" s={14} c="var(--brand-text)" />{T("Speak instead", "بول کر بتائیں")}
                                </button>
                            </div>
                        </div>
                    )}

                    {/* What the browser's quick reading suggests; the client can correct it. */}
                    <div className="in-detect">
                        <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="var(--brand-text)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4z" /></svg>
                        <span>{caseTypeName
                            ? <>{T("This reads like a", "یہ لگتا ہے")} <b>{caseTypeName}</b> {T("matter.", "معاملہ۔")}</>
                            : T("Which area of law is this?", "یہ قانون کا کون سا شعبہ ہے؟")}</span>
                        <span className="muted">{caseTypeName ? T("Not right? Pick one:", "درست نہیں؟ منتخب کریں:") : ""}</span>
                        <span role="radiogroup" aria-label={T("Case type", "کیس کی قسم")} style={{ display: "contents" }}>
                            {CASE_TYPES.map(c => (
                                <button key={c.value} type="button" role="radio" aria-checked={caseTypeInput === c.value} className="in-chip" onClick={() => { caseTypePicked.current = true; setCaseTypeInput(c.value); }}>
                                    {c.label.replace(" Law", "")}
                                </button>
                            ))}
                        </span>
                    </div>

                    <div className="in-two">
                        <div>
                            <div className="in-label">{T("Evidence", "ثبوت")}</div>
                            <div className="in-seg" role="radiogroup" aria-label={T("Do you have evidence?", "کیا آپ کے پاس ثبوت ہیں؟")}>
                                {[{ v: true, label: T("Yes, I have evidence", "ہاں، ثبوت ہے") }, { v: false, label: T("No evidence yet", "ابھی ثبوت نہیں") }].map(({ v, label }) => (
                                    <button key={String(v)} type="button" role="radio" aria-checked={hasEvidence === v} onClick={() => {
                                        // Uploaded files are part of the case whatever this says; hiding
                                        // them behind "No" would leave files the client cannot see or remove.
                                        if (!v && evidenceFiles.some(f => !f.error)) {
                                            toast.show("Remove your uploaded files first, or keep \"Yes\".", "warn", 3500);
                                            return;
                                        }
                                        setHasEvidence(v);
                                    }}>{label}</button>
                                ))}
                            </div>
                            {hasEvidence && (
                                <div className="in-drop">
                                    <input
                                            ref={fileInputRef}
                                            type="file"
                                            multiple
                                            accept=".pdf,.doc,.docx,.jpg,.jpeg,.png,.gif,.webp"
                                            style={{ display: "none" }}
                                            onChange={async e => {
                                                const files = Array.from(e.target.files || []);
                                                e.target.value = "";
                                                if (!intakeToken) { toast.show("Start intake first to upload files", "error"); return; }
                                                for (const f of files) {
                                                    const tempId = `temp-${Date.now()}-${Math.random()}`;
                                                    setEvidenceFiles(prev => [...prev, { file_id: tempId, filename: f.name, size: f.size, content_type: f.type, uploading: true, error: null }]);
                                                    const { data, error } = await uploadIntakeEvidence(intakeToken, f);
                                                    setEvidenceFiles(prev => prev.map(ef =>
                                                        ef.file_id === tempId
                                                            ? error
                                                                ? { ...ef, uploading: false, error: error?.detail || "Upload failed" }
                                                                : { ...data, uploading: false, error: null }
                                                            : ef
                                                    ));
                                                }
                                            }}
                                        />
                                    <button type="button" className="in-drop-btn" onClick={() => fileInputRef.current?.click()}>
                                        <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="var(--brand-text)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" /></svg>
                                        <span>
                                            <b>{T("Upload Files", "فائلیں اپ لوڈ کریں")}</b>
                                            {/* The REAL limits: count, size and total. */}
                                            <small>PDF, Word, JPG, PNG · max 10 MB each · up to 12 files, 40 MB total</small>
                                        </span>
                                    </button>
                                    {evidenceFiles.length > 0 && (
                                            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                                {evidenceFiles.map(ef => {
                                                    const icon = ef.content_type?.startsWith("image/") ? "IMG" : ef.content_type === "application/pdf" ? "PDF" : "DOC";
                                                    const kb   = ef.size ? `${(ef.size / 1024).toFixed(0)} KB` : "";
                                                    // Absent until the intake has been converted — extraction runs
                                                    // then, and before that there is nothing honest to claim.
                                                    const read = extractionLabel(ef);
                                                    return (
                                                        <div key={ef.file_id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 10px", borderRadius: 8, background: ef.error ? "#fef2f2" : t.inputBg, border: `1px solid ${ef.error ? "#fca5a5" : t.border}` }}>
                                                            <span className="in-ftype" data-k={icon}>{icon}</span>
                                                            <div style={{ flex: 1, minWidth: 0 }}>
                                                                <div style={{ fontSize: 12, fontWeight: 600, color: ef.error ? "#ef4444" : t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                                                    {ef.filename}
                                                                </div>
                                                                <div style={{ fontSize: 10, color: t.textMuted }}>{ef.error || (ef.uploading ? "Uploading…" : kb)}</div>
                                                                {/* Uploading and upload-failure already have the line above;
                                                                    this covers the other five states, including the
                                                                    storage-only one that is known before any extraction runs
                                                                    and the legacy-Urdu-encoding one, which carries its own
                                                                    remedy in the detail line. */}
                                                                {!ef.uploading && !ef.error && (
                                                                    <div data-testid={`extraction-${ef.file_id}`} data-state={read.state} style={{ fontSize: 10, marginTop: 2, whiteSpace: "normal", color: EXTRACTION_TONE_COLOUR[read.tone] || t.textMuted, fontWeight: read.tone === TONE_OK || read.tone === TONE_NEUTRAL ? 400 : 600 }}>
                                                                        {EXTRACTION_TONE_ICON[read.tone] || "•"} {read.title}
                                                                        {read.detail ? ` — ${read.detail}` : ""}
                                                                    </div>
                                                                )}
                                                            </div>
                                                            {ef.uploading && <div style={{ width: 12, height: 12, border: `2px solid ${t.primary}`, borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />}
                                                            {!ef.uploading && !ef.error && (
                                                                <button
                                                                    title="Download"
                                                                    onClick={() => downloadEvidence(ef)}
                                                                    style={{ background: "none", border: "none", cursor: "pointer", color: t.textMuted, fontSize: 13, lineHeight: 1, padding: 2 }}>⭳</button>
                                                            )}
                                                            {!ef.uploading && (
                                                                <button
                                                                    title="Remove"
                                                                    disabled={removingFile === ef.file_id}
                                                                    onClick={() => removeEvidence(ef)}
                                                                    style={{ background: "none", border: "none", cursor: "pointer", color: t.textMuted, fontSize: 14, lineHeight: 1, padding: 2, opacity: removingFile === ef.file_id ? 0.4 : 1 }}>✕</button>
                                                            )}
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        )}
                                    <textarea
                                            placeholder="Optional: add notes about witnesses, context, or additional evidence…"
                                            value={evidenceDesc}
                                            onChange={e => setEvidenceDesc(e.target.value)}
                                            className="in-input" style={{ marginTop: 4, minHeight: 64, background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 8, padding: "8px 12px", color: t.text, fontSize: 12, resize: "vertical", outline: "none", fontFamily: "inherit" }}
                                        />
                                </div>
                            )}
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
                            <div>
                                <div className="in-label">{T("How urgent is it?", "کتنا فوری ہے؟")}</div>
                                <div className="in-seg in-urg" role="radiogroup" aria-label={T("Urgency", "فوری نوعیت")}>
                                    {[["low", T("Low", "کم")], ["medium", T("Medium", "درمیانی")], ["high", T("High", "زیادہ")], ["urgent", T("Urgent", "فوری")]].map(([v, label]) => (
                                        <button key={v} type="button" role="radio" aria-checked={urgency === v} data-u={v} onClick={() => setUrgency(v)}>{label}</button>
                                    ))}
                                </div>
                            </div>
                            <div>
                                <label htmlFor="in-outcome" className="in-label" style={{ display: "flex" }}>{T("What outcome do you want?", "آپ کیا نتیجہ چاہتے ہیں؟")} <span style={{ textTransform: "none", letterSpacing: 0, fontWeight: 500 }}>({T("optional", "اختیاری")})</span></label>
                                <textarea id="in-outcome" className="in-input" rows={2}
                                    placeholder="e.g. File FIR and seek bail, recover unpaid wages, gain custody of children…"
                                    value={desiredOutcome}
                                    onChange={e => setDesiredOutcome(e.target.value)} />
                                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                                    {[T("Get my money back", "میری رقم واپس"), T("Stop them", "انہیں روکنا"), T("Just advice", "صرف مشورہ")].map(o => (
                                        <button key={o} type="button" className="in-chip" onClick={() => setDesiredOutcome(o)}>{o}</button>
                                    ))}
                                </div>
                                <div className="in-hint" style={{ marginTop: 8 }}>{T("Helps the AI build a more targeted case analysis.", "اس سے اے آئی بہتر تجزیہ کرتا ہے۔")}</div>
                            </div>
                        </div>
                    </div>

                    <footer className="in-foot">
                        <button type="button" className="in-back" onClick={() => setStep(1)}>← {T("Back", "واپس")}</button>
                        <span className="why">{T("Next: the AI asks up to 4 short questions.", "اگلا: اے آئی زیادہ سے زیادہ 4 مختصر سوال پوچھے گا۔")}</span>
                        <button type="button" className="in-next" onClick={handleStep2Continue}>
                            {T("Continue", "جاری رکھیں")}
                            <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
                        </button>
                    </footer>
                </section>
            )}

            {/* ── STEP 3: A few questions (2026-10-10, approved design) ─── */}
            {step === 3 && (
                <section className="in-card">
                    <header className="in-card-head">
                        <span className="in-card-ic" aria-hidden="true">
                            <svg width={19} height={19} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4z" /></svg>
                        </span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <h2 className="in-card-title">{ocrReviewRequired ? T("Review Extracted Text", "نکالا گیا متن دیکھیں") : T("A few questions to strengthen your case", "آپ کے کیس کو مضبوط کرنے کے لیے چند سوال")}</h2>
                            <div className="in-card-sub">{ocrReviewRequired
                                ? T("OCR can misread names, dates and amounts. Compare each page with the original and correct it before confirming.", "او سی آر نام، تاریخیں اور رقم غلط پڑھ سکتا ہے۔ ہر صفحہ اصل سے ملا کر درست کریں۔")
                                : T("One at a time. Answer what you know — \"I don't know\" is fine.", "ایک وقت میں ایک۔ جو معلوم ہو وہ لکھیں — \"معلوم نہیں\" بھی ٹھیک ہے۔")}</div>
                        </div>
                        {!ocrReviewRequired && (
                            <span className="in-qbars" aria-label={`${answeredCount} ${T("of up to 4 answered", "از 4 جواب دیے")}`}>
                                {[1, 2, 3, 4].map(n => (
                                    <i key={n} data-on={n <= answeredCount || clarifyDone ? "" : undefined} data-now={!clarifyDone && n === clarifyRound ? "" : undefined} />
                                ))}
                            </span>
                        )}
                    </header>

                    {ocrReviewRequired && (
                        <Card data-testid="ocr-review" style={{ padding: 18, display: "flex", flexDirection: "column", gap: 14 }}>
                            <div style={{ padding: "10px 12px", borderRadius: 9, background: "#fffbeb", border: "1px solid #fcd34d", color: "#78350f", fontSize: 12, lineHeight: 1.55 }}>
                                The text below was generated automatically and has not been used in your case analysis. Confirming means it matches the original page; it does not mean the document itself is legally valid.
                            </div>
                            {ocrReviewLoading && <div style={{ fontSize: 13, color: t.textMuted }}>Loading extracted text…</div>}
                            {!ocrReviewLoading && ocrReviewError && (
                                <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                                    <span role="alert" style={{ flex: 1, color: "#b91c1c", fontSize: 12 }}>
                                        {ocrReviewError} Your intake has not advanced.
                                    </span>
                                    <BtnOutline
                                        onClick={() => loadOcrReview(
                                            intakeToken,
                                            ocrReviewFileIds.map(file_id => ({ file_id })),
                                        )}
                                        style={{ fontSize: 11, padding: "6px 10px" }}
                                    >
                                        Try loading again
                                    </BtnOutline>
                                </div>
                            )}
                            {!ocrReviewLoading && ocrReviewPages.map(page => {
                                const file = evidenceFiles.find(f => f.file_id === page.file_id);
                                return (
                                    <div key={page.revision_id} style={{ border: `1px solid ${t.border}`, borderRadius: 10, padding: 14 }}>
                                        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 9 }}>
                                            <div style={{ flex: 1, fontSize: 12, fontWeight: 700, color: t.text }}>
                                                {file?.filename || "Evidence file"} · page {Number(page.page_number)}
                                            </div>
                                            {file && (
                                                <BtnOutline onClick={() => downloadEvidence(file)} style={{ fontSize: 11, padding: "5px 9px" }}>
                                                    Open original
                                                </BtnOutline>
                                            )}
                                            <Badge type={page.confirmed ? "success" : "warn"}>
                                                {page.confirmed ? "Confirmed" : "Needs review"}
                                            </Badge>
                                        </div>
                                        <textarea
                                            aria-label={`Extracted text page ${Number(page.page_number)}`}
                                            value={page.draft_text}
                                            disabled={page.confirmed}
                                            onChange={e => setOcrReviewPages(prev => prev.map(p =>
                                                p.revision_id === page.revision_id
                                                    ? { ...p, draft_text: e.target.value }
                                                    : p
                                            ))}
                                            style={{ width: "100%", minHeight: 150, resize: "vertical", background: t.inputBg, color: t.text, border: `1px solid ${t.border}`, borderRadius: 8, padding: 10, fontFamily: "inherit", fontSize: 12, lineHeight: 1.6 }}
                                        />
                                        {!page.confirmed && (
                                            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
                                                <BtnPrimary
                                                    disabled={Boolean(ocrConfirming)}
                                                    onClick={() => confirmOcrPage(page)}
                                                    style={{ fontSize: 12, padding: "7px 12px" }}
                                                >
                                                    {ocrConfirming === page.revision_id ? "Confirming…" : "Confirm this page"}
                                                </BtnPrimary>
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                            {ocrReviewComplete && (
                                <div style={{ color: "#15803d", fontSize: 12, fontWeight: 700 }}>
                                    ✓ All extracted pages are confirmed. Continue analysis when ready.
                                </div>
                            )}
                        </Card>
                    )}

                    {!ocrReviewRequired && (
                        <div className="in-thread" aria-live="polite">
                            {clarifyLoading && clarifyRound === 0 && (
                                <div className="in-msg ai"><span className="in-ai" aria-hidden="true">✦</span><div className="in-bub">{T("Reading your story…", "آپ کی کہانی پڑھی جا رہی ہے…")}<span className="in-typing"><i /><i /><i /></span></div></div>
                            )}
                            {clarifyDone && !clarifyQ1 && (
                                <div className="in-msg ai"><span className="in-ai" aria-hidden="true">✦</span><div className="in-bub">{T("All critical facts are already in your story — no additional questions needed.", "تمام اہم حقائق پہلے سے موجود ہیں — مزید سوال کی ضرورت نہیں۔")}</div></div>
                            )}
                            {[[clarifyQ1, clarifyA1, setClarifyA1], [clarifyQ2, clarifyA2, setClarifyA2], [clarifyQ3, clarifyA3, setClarifyA3], [clarifyQ4, clarifyA4, setClarifyA4]].map(([q, a, setA], i) => {
                                const n = i + 1;
                                if (!q || clarifyRound < n) return null;
                                const current = !clarifyDone && n === clarifyRound;
                                return (
                                    <Fragment key={n}>
                                        <div className="in-msg ai">
                                            <span className="in-ai" aria-hidden="true">✦</span>
                                            <div className="in-bub" data-now={current ? "" : undefined}>
                                                <span className="in-qn">{T("Question", "سوال")} {n}</span>
                                                {q}
                                            </div>
                                        </div>
                                        {current || n === 4 ? (
                                            <div className="in-answer">
                                                <label htmlFor={`in-a${n}`} style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>{T("Your answer", "آپ کا جواب")}</label>
                                                <div className="in-quick">
                                                    {[T("I don't know", "معلوم نہیں"), T("Not sure", "یقین نہیں")].map(qa => (
                                                        <button key={qa} type="button" className="in-chip" onClick={() => setA(qa)}>{qa}</button>
                                                    ))}
                                                </div>
                                                <textarea id={`in-a${n}`} rows={2} placeholder="Your answer…" value={a}
                                                    onChange={e => setA(e.target.value)} />
                                            </div>
                                        ) : a ? (
                                            <div className="in-msg me"><div className="in-bub">{a}</div></div>
                                        ) : null}
                                    </Fragment>
                                );
                            })}
                            {clarifyLoading && clarifyRound > 0 && (
                                <div className="in-msg ai"><span className="in-ai" aria-hidden="true">✦</span><div className="in-bub"><span className="in-typing"><i /><i /><i /></span></div></div>
                            )}
                        </div>
                    )}

                    <footer className="in-foot">
                        <button type="button" className="in-back" onClick={() => setStep(2)}>← {T("Back", "واپس")}</button>
                        <span className="why">{clarifyDone || ocrReviewRequired
                            ? T("Next: the AI builds your structured case.", "اگلا: اے آئی آپ کا منظم کیس بنائے گا۔")
                            : T("Each answer helps a lawyer understand your case.", "ہر جواب وکیل کو کیس سمجھنے میں مدد دیتا ہے۔")}</span>
                        {!ocrReviewRequired && (clarifyRound >= 1 && clarifyRound <= 3) && !clarifyDone ? (
                            <BtnPrimary
                                disabled={clarifyLoading || !getCurrentAnswer().trim()}
                                onClick={handleClarifyNext}
                                style={{ fontSize: 14, padding: "12px 24px", borderRadius: 999 }}
                            >
                                {clarifyLoading ? "Thinking…" : "Next Question →"}
                            </BtnPrimary>
                        ) : (
                            <BtnPrimary
                                disabled={converting || clarifyLoading || ocrReviewLoading
                                    || (ocrReviewRequired && !ocrReviewComplete)
                                    || (!ocrReviewRequired && clarifyRound === 4 && !clarifyA4.trim())}
                                onClick={handleConvertAndSummarise}
                                style={{ fontSize: 14, padding: "12px 24px", borderRadius: 999, opacity: converting ? 0.7 : 1 }}
                            >
                                {converting ? "Analysing case…"
                                    : ocrReviewLoading ? "Loading extracted text…"
                                    : ocrReviewRequired ? "Continue analysis →"
                                    : clarifyLoading ? "Thinking…" : "Complete & Continue →"}
                            </BtnPrimary>
                        )}
                    </footer>
                </section>
            )}

            {/* ── STEP 4: Review (2026-10-10, approved design) ─────────── */}
            {step === 4 && (
                <section className="in-card">
                    <header className="in-card-head">
                        <span className="in-card-ic" aria-hidden="true"><Ic n="file" s={19} c="currentColor" /></span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <h2 className="in-card-title">{T("Here is your case, structured", "یہ رہا آپ کا منظم کیس")}</h2>
                            <div className="in-card-sub">{T("Read it like a lawyer would. Fix anything wrong before you confirm.", "اسے وکیل کی طرح پڑھیں۔ تصدیق سے پہلے کوئی غلطی درست کریں۔")}{caseId ? ` · ${T("Case", "کیس")} …${caseId.slice(-8)}` : ""}</div>
                        </div>
                        <button type="button" className="in-ghost" onClick={handleDownloadPDF}>
                            <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" /></svg>
                            {T("Export", "ایکسپورٹ")}
                        </button>
                    </header>

                    <div className="in-facts">
                        {[[T("Role", "کردار"), roleName], [T("Province", "صوبہ"), PROVINCE_SHORT[province] || province], [T("Case type", "کیس کی قسم"), caseTypeName], [T("Urgency", "فوریت"), urgency ? urgency.charAt(0).toUpperCase() + urgency.slice(1) : ""]].map(([k, v]) => (
                            <div key={k}><small>{k}</small><b data-u={k === T("Urgency", "فوریت") ? urgency : undefined}>{v || "—"}</b></div>
                        ))}
                    </div>

                    <div className="in-sections">
        {aiStructured ? (
                            <>
                                {/* AI Summary */}
                                <div style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 12, padding: "16px 20px" }}>
                                    <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: t.primary, marginBottom: 10 }}>📋 Case Summary</div>
                                    <div style={{ fontSize: 13, color: t.textDim, lineHeight: 1.7 }}>{aiStructured.summary}</div>
                                </div>

                                {/* WHAT THE ANALYSIS DID NOT SEE.
                                    Shown beside the summary, not on the upload screen, because
                                    this is the screen where the client decides whether to trust
                                    the analysis. The previous wording — "some uploaded files
                                    could not be read" — was true but unactionable: it never said
                                    which file, or how much of it, so a bundle read down to its
                                    cover sheet looked the same as one missing a blurred photo. */}
                                {(() => {
                                    const records = Array.isArray(aiStructured.evidence_extraction) ? aiStructured.evidence_extraction : [];
                                    if (!records.length) return null;
                                    const nameOf = id => (evidenceFiles.find(f => f.file_id === id) || {}).filename || "an uploaded file";
                                    const gaps = incompleteFiles(records.map(r => ({ ...r, extraction_status: r.status })));
                                    if (!gaps.length) {
                                        return (
                                            <div style={{ padding: "10px 14px", borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}`, fontSize: 12, color: t.textMuted }}>
                                                ✓ All {records.length} uploaded file(s) were read in full and included in this analysis.
                                            </div>
                                        );
                                    }
                                    return (
                                        <div data-testid="evidence-gaps" style={{ padding: "12px 14px", borderRadius: 10, background: "#fffbeb", border: "1px solid #fcd34d", fontSize: 12, color: "#78350f" }}>
                                            <div style={{ fontWeight: 700, marginBottom: 6 }}>
                                                ⚠ This analysis did not see all of your evidence
                                            </div>
                                            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                                                {gaps.map(g => {
                                                    const label = extractionLabel(g);
                                                    return (
                                                        <div key={g.file_id}>
                                                            <strong>{nameOf(g.file_id)}</strong> — {label.title}
                                                            {label.detail ? ` (${label.detail})` : ""}
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                            <div style={{ marginTop: 7, lineHeight: 1.6 }}>
                                                Anything above was not part of the analysis. Type those details into
                                                your description, upload a text-based copy, or continue knowing they
                                                were left out.
                                            </div>
                                        </div>
                                    );
                                })()}

                                {/* Applicable Laws */}
                                {aiStructured.applicable_laws?.length > 0 && (
                                    <div style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 12, padding: "16px 20px" }}>
                                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                                            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: t.primary }}>⚖️ Applicable Laws</div>
                                                                                            </div>
                                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                            {aiStructured.applicable_laws.map((law, i) => (
                                                <div key={i} style={{ fontSize: 13, color: t.textDim, lineHeight: 1.6 }}>
                                                    {i + 1}. {law}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {/* Recommended Actions */}
                                {aiStructured.recommended_actions?.length > 0 && (
                                    <div style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 12, padding: "16px 20px" }}>
                                        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: t.primary, marginBottom: 10 }}>🎯 Recommended Actions</div>
                                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                            {aiStructured.recommended_actions.map((action, i) => (
                                                <div key={i} style={{ fontSize: 13, color: t.textDim, lineHeight: 1.6 }}>
                                                    {i + 1}. {action}
                                                </div>
                                            ))}
                                        </div>
                                        {/* The backend now says whether these actions were actually
                                            checked against retrieved law. "grounded" is the only
                                            status that means they were; everything else means the
                                            check could not run, and that must be visible here rather
                                            than buried in the summary paragraph. */}
                                        {aiStructured.grounding_status && aiStructured.grounding_status !== "grounded" && (
                                            <div style={{ marginTop: 12, paddingTop: 10, borderTop: `1px solid ${t.border}`, display: "flex", gap: 8, alignItems: "flex-start" }}>
                                                <span style={{ fontSize: 13, lineHeight: 1.5 }}>⚠️</span>
                                                <span style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.55 }}>
                                                    {GROUNDING_NOTE[aiStructured.grounding_status] || GROUNDING_NOTE.unverified}
                                                </span>
                                            </div>
                                        )}
                                    </div>
                                )}

                                {/* Risk Level */}
                                {aiStructured.risk_level && (
                                    <div style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 12, padding: "16px 20px" }}>
                                        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: t.primary, marginBottom: 10 }}>⚠️ Risk Assessment</div>
                                        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                                            <Badge type={RISK_COLORS[aiStructured.risk_level] || "warn"} style={{ fontSize: 12, padding: "6px 14px", fontWeight: 700, textTransform: "uppercase" }}>
                                                {aiStructured.risk_level} risk
                                            </Badge>
                                            <span style={{ fontSize: 12, color: t.textMuted }}>Informational only — not legal advice.</span>
                                        </div>
                                    </div>
                                )}
                            </>
                        ) : (
                            // Static fallback when AI analysis not available
                            // `body` carries JSX, not an HTML string. It used to be a
                            // template literal rendered through dangerouslySetInnerHTML,
                            // which meant the "Case Description" card — raw text the user
                            // typed — was parsed as markup. Only the "Parties" card ever
                            // needed real elements, so it supplies them directly and React
                            // escapes everything else.
                            [
                                {
                                    icon: "👤", title: "Parties", c: t.primary,
                                    body: (
                                        <>
                                            <strong>Role:</strong> {role}<br />
                                            <strong>Province:</strong> {PROVINCES.find(p => p.value === province)?.label || province}
                                        </>
                                    ),
                                },
                                { icon: "⚖️", title: "Case Type", body: `${CASE_TYPES.find(c => c.value === caseTypeInput)?.label || caseTypeInput} — Urgency: ${urgency}`, c: t.primary },
                                { icon: "📋", title: "Case Description", body: description || voiceTranscript || "No description provided.", c: t.primary },
                                { icon: "🎯", title: "Desired Outcome", body: "Legal assistance and representation.", c: t.primary },
                            ].map((s, idx) => (
                                <div key={idx} style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 12, padding: "16px 20px" }}>
                                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                                        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: s.c }}>{s.icon} {s.title}</div>
                                    </div>
                                    <div style={{ fontSize: 13, color: t.textDim, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{s.body}</div>
                                </div>
                            ))
                        )}
                    </div>

                    <footer className="in-foot">
                        <button type="button" className="in-back" onClick={() => setStep(3)}>← {T("Back", "واپس")}</button>
                        <span className="why">{T("Looks right? Next you confirm the category.", "درست ہے؟ اگلا: زمرے کی تصدیق۔")}</span>
                        <button type="button" className="in-next" onClick={handleContinueToCategory}>
                            {T("Continue to Category →", "درجہ بندی کی طرف جائیں ←")}
                        </button>
                    </footer>
                </section>
            )}

            {/* ── STEP 5: Confirm (2026-10-10, approved design) ───────── */}
            {step === 5 && (
                <section className="in-card">
                    <header className="in-card-head">
                        <span className="in-card-ic" aria-hidden="true"><Ic n="check" s={19} c="currentColor" /></span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <h2 className="in-card-title">{T("Confirm the category", "زمرے کی تصدیق کریں")}</h2>
                            <div className="in-card-sub">{caseTypeInput
                                ? <>{T("The AI placed your case under", "اے آئی نے آپ کا کیس اس میں رکھا:")} <b style={{ color: "var(--brand-text)" }}>{caseTypeName}</b>. {T("Change it if it is wrong — lawyers are matched on it.", "غلط ہو تو بدلیں — وکیل اسی پر منتخب ہوتے ہیں۔")}</>
                                : T("Select the category that best describes your legal issue.", "وہ زمرہ منتخب کریں جو آپ کے مسئلے کو بہتر بیان کرے۔")}</div>
                        </div>
                    </header>

                    <div className="in-cats" role="radiogroup" aria-label={T("Category", "زمرہ")}>
                        {[
                            { id: "civil", n: T("Civil", "دیوانی"), d: T("Property, money, contracts", "جائیداد، رقم، معاہدے") },
                            { id: "criminal", n: T("Criminal", "فوجداری"), d: T("FIR, bail, criminal defence", "ایف آئی آر، ضمانت، دفاع") },
                            { id: "family", n: T("Family", "عائلی"), d: T("Divorce, khula, custody, maintenance", "طلاق، خلع، حضانت، نان نفقہ") },
                            { id: "constitutional", n: T("Constitutional", "آئینی"), d: T("Fundamental rights, writ petitions", "بنیادی حقوق، رٹ") },
                        ].map(c => (
                            <button key={c.id} type="button" role="radio" aria-checked={c.id === caseTypeInput} className="in-cat"
                                disabled={caseConfirmed} onClick={() => setCaseTypeInput(c.id)}>
                                <small>{c.id === convertedCaseType ? T("AI suggested", "اے آئی کی تجویز") : "\u00a0"}</small>
                                <b>{c.n}</b>
                                <span>{c.d}</span>
                            </button>
                        ))}
                    </div>

                    {!caseConfirmed ? (
                        <div className="in-open">
                            <span className="in-open-ic" aria-hidden="true"><Ic n="check" s={22} c="currentColor" /></span>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <b>{T("Open my case", "میرا کیس کھولیں")}</b>
                                <span>{T("Until you confirm, this stays a draft: it cannot be matched or sent. Once open, it is still private — not sent to anyone until you choose a lawyer.", "تصدیق تک یہ مسودہ ہے۔ کھلنے کے بعد بھی نجی ہے — وکیل چننے تک کسی کو نہیں بھیجا جاتا۔")}</span>
                            </div>
                            <button type="button" className="in-next" disabled={intakeSubmitting}
                                onClick={() => { if (!intakeSubmitting) handleSubmit(); }}>
                                {intakeSubmitting ? "Confirming…" : "Confirm Category & Open Case →"}
                            </button>
                        </div>
                    ) : (
                        <div className="in-done">
                            <span className="in-done-ic" aria-hidden="true"><Ic n="check" s={28} c="currentColor" /></span>
                            <h3>{T("Case Intake Complete", "کیس کی درخواست مکمل")}</h3>
                            <p>{T("Your case is open. Choose a lawyer to send it to — it has not been sent to anyone yet.", "آپ کا کیس کھل چکا ہے۔ اسے بھیجنے کے لیے وکیل منتخب کریں — ابھی کسی کو نہیں بھیجا گیا۔")}{caseId ? ` ${T("Case", "کیس")} …${caseId.slice(-8)}.` : ""}</p>
                        </div>
                    )}

                    <div className="in-label" style={{ marginTop: 22 }}>{T("What you can do next", "آگے کیا کر سکتے ہیں")}</div>
                    <div className="in-nexts">
                        <button type="button" className="in-nx" data-main="" disabled={!caseConfirmed}
                            onClick={() => { if (!caseConfirmed) return; router.push(caseId ? `/lawyers?case_id=${caseId}` : "/lawyers"); }}>
                            <span className="ic" aria-hidden="true"><svg width={17} height={17} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></svg></span>
                            <b>{T("Find a Lawyer →", "وکیل تلاش کریں ←")}</b>
                            <span>{T("AI match for this case, then choose who to send it to.", "اس کیس کے لیے اے آئی میچ، پھر خود چنیں۔")}</span>
                        </button>
                        <button type="button" className="in-nx" style={{ "--c": "#6aa8ff" }} disabled={!caseConfirmed} onClick={() => router.push("/documents")}>
                            <span className="ic" aria-hidden="true"><svg width={17} height={17} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></svg></span>
                            <b>{T("Draft a document", "دستاویز تیار کریں")}</b>
                            <span>{T("e.g. a legal notice.", "مثلاً قانونی نوٹس۔")}</span>
                        </button>
                        <button type="button" className="in-nx" style={{ "--c": "var(--gold)" }} disabled={!caseConfirmed} onClick={() => router.push("/tracking")}>
                            <span className="ic" aria-hidden="true"><svg width={17} height={17} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg></span>
                            <b>{T("Track the case", "کیس دیکھیں")}</b>
                            <span>{T("See its status and updates.", "حیثیت اور اپ ڈیٹس۔")}</span>
                        </button>
                    </div>

                    <footer className="in-foot">
                        {!caseConfirmed && <button type="button" className="in-back" onClick={() => setStep(4)}>← {T("Back", "واپس")}</button>}
                        <span className="why">{T("Export Case", "کیس ایکسپورٹ کریں")}:</span>
                        <button type="button" className="in-ghost" onClick={handleDownloadPDF}>Download Case PDF</button>
                        <button type="button" className="in-ghost" onClick={handleEmail}>Email Summary</button>
                        <button type="button" className="in-ghost" onClick={handlePrint}>Print</button>
                    </footer>
                </section>
            )}
            </div>

            {(
                <aside id="in-case-file" className="in-file" data-open={fileOpen ? "" : undefined} aria-hidden={!fileOpen}
                    aria-label={T("Your case file", "آپ کی کیس فائل")}
                    onKeyDown={e => { if (e.key === "Escape") setFileOpen(false); }}>
                    <div className="in-file-head">
                        <span className="in-file-ic" aria-hidden="true">
                            <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M9 13h6M9 17h4" /></svg>
                        </span>
                        <div>
                            <div style={{ fontWeight: 700, fontSize: 15, color: "var(--ink)" }}>{T("Your case file", "آپ کی کیس فائل")}</div>
                            <div style={{ fontSize: 12, color: "var(--faint)" }}>{T("Fills in as you go", "جیسے جیسے آپ آگے بڑھیں")}</div>
                        </div>
                        <button type="button" className="in-file-x" aria-label={T("Close case file", "کیس فائل بند کریں")} tabIndex={fileOpen ? 0 : -1} onClick={() => setFileOpen(false)}>
                            <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
                        </button>
                    </div>
                    {caseFileRows.map(([label, value, fresh]) => (
                        <div key={label} className="in-file-row">
                            <span>{label}</span>
                            {value ? <b data-new={fresh ? "" : undefined}>{value}</b> : <i>—</i>}
                        </div>
                    ))}
                    <div className="in-file-note">
                        <b>{T("Private draft.", "نجی مسودہ۔")}</b> {T("Nothing is sent to any lawyer until you choose one at the end.", "آخر میں آپ کے انتخاب تک کسی وکیل کو کچھ نہیں بھیجا جاتا۔")}
                    </div>
                </aside>
            )}
            </div>
        </div>
    );
};

export default ModIntake;
