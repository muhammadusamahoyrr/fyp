'use client';
// Lawyer Document Automation Page — paste your code here
import { useState, useRef, useEffect } from "react";
import { useTheme } from "./theme.js";
import { useCase } from "./theme.js";
import { Icon, I } from "./icons.jsx";
import { listCases, getCase, aiDraftStream, saveDocDraft, listDocDrafts, deleteDocDraft, aiPleadingUrduStream, pleadingUrduPdf, pleadingUrduDocumentV2, publishDraftAsDocumentV2, downloadDocumentFile, idempotencyKey, errorCode } from "@/lib/api.js";

// Infer the statute collection to ground drafting in, from the template.
function templateCaseType(name = "") {
    const n = name.toLowerCase();
    if (/bail|criminal|fir|crpc|ppc|remand|acquittal|f\.?i\.?r/.test(n)) return "criminal";
    if (/marriage|divorce|khula|custody|nikah|dower|maintenance|guardian|family/.test(n)) return "family";
    if (/writ|constitution|fundamental right|article 199|mandamus|habeas/.test(n)) return "constitutional";
    return "civil";
}
import { useAuth } from "@/context/AuthContext.jsx";
import DraftingHome from "./DraftingHome.jsx";
import { DRAFTING_TOKENS_CSS, draftingMode } from "./draftingTheme.js";
import { ModalPortal } from "./ui.jsx";
import { TEMPLATES, buildContent } from "@/lib/lawyerDraftTemplates.js";
import {
    NO_CASE, bindingForNewDocument, pendingBindingForDraft, bindingForDraft,
    caseActionsBlocked, boundCaseId,
} from "@/lib/draftCaseBinding.js";
import { verificationView } from "@/lib/draftVerification.js";

// ============================================================
// EDITOR LOOK (2026-10-09) — the approved drafting-editor design, on the
// Legal Drafting palette (draftingTheme.js). Scoped by [data-drafter-editor].
// ============================================================
export const EDITOR_CSS = `[data-drafter-editor]{flex:1;min-height:0;overflow:hidden;display:flex;flex-direction:column;--top-h:72px;--tools-h:72px;background:var(--bg);color:var(--ink);font:15px/1.5 "Hanken Grotesk",system-ui,sans-serif;-webkit-font-smoothing:antialiased;--stage:rgba(0,0,0,.16)}
[data-drafter-editor][data-mode="light"]{--stage:#E6E4EA}
[data-drafter-editor] *{box-sizing:border-box;scrollbar-width:thin;scrollbar-color:var(--line-strong) transparent}
[data-drafter-editor] ::-webkit-scrollbar{width:8px;height:6px}
[data-drafter-editor] ::-webkit-scrollbar-track{background:transparent}
[data-drafter-editor] ::-webkit-scrollbar-thumb{background:var(--line-strong);border-radius:6px}
[data-drafter-editor] button,[data-drafter-editor] select,[data-drafter-editor] textarea{font:inherit;color:inherit}
[data-drafter-editor] :focus-visible{outline:2px solid var(--focus);outline-offset:2px}
[data-drafter-editor] .de-top{position:sticky;top:0;z-index:8;min-height:var(--top-h);background:var(--bg);box-shadow:0 2px 0 var(--bg);display:flex;align-items:center;gap:14px;padding:14px 26px;flex-wrap:wrap}
[data-drafter-editor] .de-back{width:44px;height:44px;flex:none;border-radius:12px;border:1px solid transparent;background:transparent;color:var(--ink);display:grid;place-items:center;cursor:pointer}
[data-drafter-editor] .de-back:hover{background:var(--hover-tint);border-color:var(--hover-line);color:var(--hover-ink)}
[data-drafter-editor] .de-title{min-width:0;flex:1}
[data-drafter-editor] .de-title h1{margin:0;font:600 19px/1.25 "Literata",Georgia,serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-drafter-editor] .de-meta{display:flex;gap:8px;align-items:center;font-size:12.5px;color:var(--muted);flex-wrap:wrap}
[data-drafter-editor] .de-cat{font-weight:600;color:var(--brand-text)}
[data-drafter-editor] .de-right{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-left:auto}
[data-drafter-editor] .de-btn{display:inline-flex;align-items:center;gap:7px;height:40px;padding:0 15px;border-radius:10px;border:1px solid var(--line-strong);background:var(--surface);font-weight:600;font-size:13.5px;white-space:nowrap;cursor:pointer}
[data-drafter-editor] .de-btn:hover:not(:disabled){border-color:var(--hover-line);background:var(--hover-tint);color:var(--hover-ink)}
[data-drafter-editor] .de-btn:disabled{opacity:.55;cursor:not-allowed}
[data-drafter-editor] .de-btn.primary{background:var(--brand-solid);border-color:transparent;color:var(--on-brand)}
[data-drafter-editor] .de-btn.primary:hover:not(:disabled){background:var(--brand-solid-hover);color:var(--on-brand)}
[data-drafter-editor] .de-note{font-size:12.5px;font-weight:600;padding:5px 11px;border-radius:999px;white-space:nowrap}
[data-drafter-editor] .de-note.ok{background:var(--brand-soft);color:var(--brand-text)}
[data-drafter-editor] .de-note.bad{background:var(--danger-soft);color:var(--danger)}
[data-drafter-editor] .de-drop{position:relative;flex:none}
[data-drafter-editor] .de-case{display:flex;align-items:center;gap:8px;height:38px;max-width:260px;padding:0 11px 0 4px;border-radius:999px;border:1px solid var(--line);background:var(--surface);color:var(--ink);font:inherit;cursor:pointer;text-align:left;transition:border-color .15s,background .15s}
[data-drafter-editor] .de-case:hover,[data-drafter-editor] .de-case[aria-expanded="true"]{border-color:var(--hover-line);background:var(--hover-tint)}
[data-drafter-editor] .de-case .ic{width:30px;height:30px;flex:none;display:grid;place-items:center;border-radius:50%;background:var(--brand-soft);color:var(--brand-text)}
[data-drafter-editor] .de-case[data-case-binding="unavailable"]{border-color:color-mix(in srgb,var(--danger) 55%,transparent)}
[data-drafter-editor] .de-case[data-case-binding="unavailable"] .ic{background:var(--danger-soft);color:var(--danger)}
[data-drafter-editor] .de-case b{display:block;font-size:12.5px;font-weight:600;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-drafter-editor] .de-case small{display:block;font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-drafter-editor] .de-pop{position:absolute;top:calc(100% + 8px);right:0;z-index:60;width:min(380px,90vw);max-height:60vh;overflow-y:auto;padding:8px;border-radius:16px;border:1px solid var(--line-strong);background:var(--surface);box-shadow:0 24px 48px -18px rgba(0,0,0,.8);scrollbar-width:thin}
[data-drafter-editor] .de-pop[hidden]{display:none}
[data-drafter-editor] .de-pop h3{margin:4px 8px 8px;font:600 15px/1.2 Literata,Georgia,serif}
[data-drafter-editor] .de-opt{display:flex;flex-direction:column;align-items:flex-start;gap:1px;width:100%;padding:8px 10px;border:0;border-radius:10px;background:transparent;color:var(--ink);font:inherit;font-size:13px;text-align:left;cursor:pointer}
[data-drafter-editor] .de-opt small{font-size:11.5px;color:var(--muted)}
[data-drafter-editor] .de-opt:hover{background:var(--hover-tint)}
[data-drafter-editor] .de-opt[aria-selected="true"]{background:var(--brand-soft);color:var(--brand-text);font-weight:650}
[data-drafter-editor] .de-save{display:flex}
/* A pill, like the case button beside it. */
[data-drafter-editor] .de-save .de-btn{height:38px;font-size:13px}
[data-drafter-editor] .de-save .de-save-main{border-radius:999px 0 0 999px;padding:0 14px 0 16px}
[data-drafter-editor] .de-save .de-save-more{width:36px;padding:0;justify-content:center;border-radius:0 999px 999px 0;border-left:1px solid rgba(4,33,42,.22);width:36px;padding-right:3px}
[data-drafter-editor] .de-save .de-save-more[aria-expanded="true"] svg{transform:rotate(180deg)}
[data-drafter-editor] .de-save-menu{width:min(330px,90vw)}
[data-drafter-editor] .de-opt:disabled{opacity:.5;cursor:not-allowed}
[data-drafter-editor] .de-sep-h{height:1px;margin:6px 4px;background:var(--line)}
[data-drafter-editor] .de-acct{display:flex;align-items:center;gap:10px;height:46px;padding:0 14px 0 6px;border-radius:999px;border:1px solid var(--line);background:var(--surface);max-width:250px}
[data-drafter-editor] .de-acct b{display:block;font-size:13px;font-weight:600;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-drafter-editor] .de-acct small{font-size:11.5px;color:var(--muted)}
[data-drafter-editor] .de-avatar{width:34px;height:34px;flex:none;border-radius:50%;display:grid;place-items:center;font-size:12px;font-weight:700;background:#5B7BE0;color:#fff}
/* Edge to edge (2026-10-11): no strip of page colour between the sidebar and the stage. */
[data-drafter-editor] .de-stage{flex:1;min-height:0;margin:0;border-radius:24px 24px 0 0;background:var(--stage);display:flex;flex-direction:column;padding:0 18px 6px}
[data-drafter-editor] .de-tools{position:sticky;top:var(--top-h);z-index:7;padding-top:8px;margin:0 -18px;padding-inline:18px;border-radius:24px 24px 0 0;background:linear-gradient(var(--stage),var(--stage)) top/100% 8px no-repeat,linear-gradient(var(--bg),var(--bg)) top/100% 8px no-repeat}
[data-drafter-editor] .de-toolbar{display:flex;align-items:center;gap:2px;padding:6px 8px;border-radius:16px;border:1px solid var(--line);background:var(--surface);overflow-x:auto;scrollbar-width:none;box-shadow:var(--shadow-rest)}
/* Scrolls sideways when narrow, with no visible scrollbar. */
[data-drafter-editor] .de-toolbar::-webkit-scrollbar{display:none}
[data-drafter-editor] .de-tb{height:34px;min-width:34px;padding:0 6px;border-radius:9px;border:1px solid transparent;background:transparent;color:var(--muted);display:grid;place-items:center;cursor:pointer;font-weight:700;font-size:15px;flex:none}
[data-drafter-editor] .de-tb:hover{background:var(--hover-tint);color:var(--hover-ink)}
[data-drafter-editor] .de-tb[aria-pressed="true"]{background:var(--teal);color:var(--on-teal)}
[data-drafter-editor] .de-sep{width:1px;height:22px;background:var(--line-strong);margin:0 4px;flex:none}
[data-drafter-editor] .de-select{height:34px;padding:0 8px;border-radius:9px;border:1px solid var(--line);background:var(--input);font-size:13px;flex:none;cursor:pointer}
[data-drafter-editor] .de-select:hover{border-color:var(--hover-line)}
/* Two columns of one height that fill the screen (2026-10-11): the page scrolls
   inside its own column, so its top and bottom always line up with the assistant's. */
[data-drafter-editor] .de-split{display:flex;gap:16px;margin-top:16px;align-items:stretch;flex:1;min-height:0}
/* The page sits straight on the stage's grey (2026-10-11): no card around it. */
[data-drafter-editor] .de-doc{flex:1;min-width:0;display:flex;flex-direction:column}
[data-drafter-editor] .de-strips{flex:none;font-size:12px;color:var(--muted);border-bottom:1px solid var(--line)}
[data-drafter-editor] .de-strips > div{padding:7px 20px}
[data-drafter-editor] .de-strips > div + div{border-top:1px solid var(--line)}
[data-drafter-editor] .de-doc{min-height:0}
[data-drafter-editor] .de-scroll{flex:1;min-height:0;overflow-y:auto;padding:0 6px 0 0;border-radius:6px}
[data-drafter-editor] .de-scroll::-webkit-scrollbar{width:6px}
[data-drafter-editor] .de-scroll::-webkit-scrollbar-thumb{border-radius:6px;background:color-mix(in srgb,var(--ink) 22%,transparent)}
[data-drafter-editor] .de-scroll::-webkit-scrollbar-track{background:transparent}
[data-drafter-editor] .de-paper{max-width:820px;margin:0 auto;min-height:640px;background:var(--paper);color:var(--paper-ink);border-radius:6px;padding:64px 76px;line-height:1.95;font-size:15px;outline:none;white-space:pre-wrap;box-shadow:0 18px 40px -22px rgba(0,0,0,.65)}
[data-drafter-editor] .de-assist{width:400px;flex:none;display:flex;flex-direction:column;border-radius:18px;border:1px solid var(--line);background:var(--surface);overflow:hidden}
[data-drafter-editor] .de-assist-head{padding:14px 22px;background:var(--surface-2);border-bottom:1px solid var(--line)}
[data-drafter-editor] .de-assist-head b{display:block;font-size:17px}
[data-drafter-editor] .de-assist-head span{font-size:13.5px;color:var(--muted)}
[data-drafter-editor] .de-assist-body{flex:1;min-height:0;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:12px}
/* Just the greeting now (2026-10-11): no second title or icon card around it. */
[data-drafter-editor] .de-hello{padding:0}
[data-drafter-editor] .de-hello-top{display:flex;gap:14px;align-items:center}
[data-drafter-editor] .de-hello-ic{width:58px;height:58px;flex:none;border-radius:14px;background:var(--brand-solid);color:var(--on-brand);display:grid;place-items:center}
[data-drafter-editor] .de-hello-top b{display:block;font-size:19px;line-height:1.2}
[data-drafter-editor] .de-hello-top span{font-size:14px;color:var(--muted)}
[data-drafter-editor] .de-greet{margin-top:0;border:1px solid var(--line);border-radius:12px;padding:12px 14px;background:var(--surface)}
[data-drafter-editor] .de-greet b{font-size:16px}
[data-drafter-editor] .de-greet b em{font-style:normal;color:var(--brand-text)}
[data-drafter-editor] .de-greet p{margin:4px 0 0;font-size:13px;color:var(--muted);line-height:1.5}
[data-drafter-editor] .de-label{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--faint);font-weight:600}
/* Quick actions as small pills that wrap (2026-10-11). */
[data-drafter-editor] .de-quick{display:flex;flex-wrap:wrap;gap:6px}
/* The panel stays put; whatever is inside it -- the opening note or the
   conversation -- scrolls within it, on a slim bar. */
[data-drafter-editor] .de-assist-body::-webkit-scrollbar{width:6px}
[data-drafter-editor] .de-assist-body::-webkit-scrollbar-thumb{border-radius:6px;background:color-mix(in srgb,var(--ink) 22%,transparent)}
[data-drafter-editor] .de-assist-body::-webkit-scrollbar-track{background:transparent}
[data-drafter-editor] .de-quick button{padding:6px 12px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--muted);text-align:left;font-size:13px;cursor:pointer}
[data-drafter-editor] .de-quick button:hover{border-color:var(--hover-line);background:var(--hover-tint);color:var(--hover-ink)}
[data-drafter-editor] .de-msg{max-width:92%;padding:10px 13px;font-size:13.5px;line-height:1.6;white-space:pre-wrap}
[data-drafter-editor] .de-msg.user{align-self:flex-end;border-radius:14px 14px 4px 14px;background:var(--teal);color:var(--on-teal)}
[data-drafter-editor] .de-msg.ai{align-self:flex-start;border-radius:4px 14px 14px 14px;background:var(--surface-2);border:1px solid var(--line)}
[data-drafter-editor] .de-dots{display:flex;gap:5px;padding:12px 16px}
[data-drafter-editor] .de-dots i{width:6px;height:6px;border-radius:50%;background:var(--brand-text);animation:pulse 1.2s ease infinite}
[data-drafter-editor] .de-compose{flex:none;padding:14px 16px;border-top:1px solid var(--line)}
[data-drafter-editor] .de-compose-box{border:1px solid var(--line);border-radius:18px;background:var(--surface-2);overflow:hidden}
[data-drafter-editor] .de-compose-box:focus-within{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-drafter-editor] .de-compose textarea{width:100%;border:0;outline:none;background:transparent;resize:none;padding:12px 16px 2px;font-size:14px;line-height:1.5}
[data-drafter-editor] .de-compose textarea::placeholder{color:var(--faint)}
[data-drafter-editor] .de-compose-row{display:flex;justify-content:space-between;align-items:center;padding:0 8px 8px 16px;gap:10px}
[data-drafter-editor] .de-hint{font-size:11.5px;color:var(--faint)}
[data-drafter-editor] .de-foot{font-size:11.5px;color:var(--faint);text-align:center;margin-top:9px}
[data-drafter-editor] .de-send{overflow:hidden}
/* Send: a small round arrow, like a chat app's (2026-10-11). */
[data-drafter-editor] .de-send-ic{width:34px;height:34px;flex:none;display:grid;place-items:center;border:0;border-radius:50%;background:var(--brand-solid);color:var(--on-brand);cursor:pointer;transition:transform .15s,opacity .15s}
[data-drafter-editor] .de-send-ic:hover:not(:disabled){transform:translateY(-1px)}
[data-drafter-editor] .de-send-ic:disabled{opacity:.35;cursor:default}
[data-drafter-editor] .de-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
[data-drafter-editor] .de-send:hover:not(:disabled) svg{animation:deFly .75s cubic-bezier(.5,0,.3,1)}
[data-drafter-editor] .de-tb svg{transition:transform .3s cubic-bezier(.34,1.56,.64,1)}
[data-drafter-editor] .de-tb:hover svg{transform:translateY(-1px) scale(1.12)}
[data-drafter-editor] .de-back svg{transition:transform .3s cubic-bezier(.34,1.56,.64,1)}
[data-drafter-editor] .de-back:hover svg{transform:translateX(-3px)}
@keyframes deFly{0%{transform:translate(0,0)}40%{transform:translate(16px,-16px);opacity:0}41%{transform:translate(-16px,16px);opacity:0}100%{transform:translate(0,0);opacity:1}}
@media (prefers-reduced-motion:reduce){[data-drafter-editor] *{transition:none!important;animation:none!important}}`;

/* One toolbar button: an icon with its name for screen readers and hover. */
function TB({ label, active, onClick, children, style }) {
    return (
        <button type="button" className="de-tb" title={label} aria-label={label}
            aria-pressed={active === undefined ? undefined : Boolean(active)}
            onMouseDown={e => e.preventDefault()} onClick={onClick} style={style}>
            {children}
        </button>
    );
}

// STAGE 1 — the template home lives in DraftingHome.jsx (2026-10-09).

// ============================================================
// STAGE 2 — EDITOR
// ============================================================

/* THE CITATION CHECK, ONLY WHEN IT MATTERS (2026-10-11). The always-on strip
 * was noise. What stays is the one finding a lawyer must not miss: an
 * authority the check could not find, or one that is repealed -- the kind of
 * wrong citation that otherwise reaches a filed document. Shown for the draft
 * as last saved; once the text changes the finding is about other words, so
 * it goes until the next save checks again. Nothing is shown for a clean or
 * an unchecked draft: no finding is not a pass, and is not claimed as one. */
function CitationWarning({ draftCheck, stale }) {
    const d = verificationView(draftCheck);
    if (!d || stale || d.tone !== "danger") return null;
    return (
        <span className="de-note bad" role="alert" data-citation-warning title={d.detail}>
            ⚠ {d.headline}
        </span>
    );
}

function StageEditor({ tmpl, binding = NO_CASE, draft, onBack, t, cases = [], onRebind }) {
    // The case this document is bound to — fixed when the editor opened, never
    // the page selector's current value. See lib/draftCaseBinding.js.
    const caseObj = binding.caseObj;
    const caseId = boundCaseId(binding);
    const { setPage } = useCase();
    const caseBlocked = caseActionsBlocked(binding);
    const [caseOpen, setCaseOpen] = useState(false);
    const [saveOpen, setSaveOpen] = useState(false);
    const [justPublished, setJustPublished] = useState(false);
    const caseRef = useRef(null), saveRef = useRef(null);
    useEffect(() => {
        if (!caseOpen && !saveOpen) return undefined;
        const onDown = e => {
            if (!caseRef.current?.contains(e.target)) setCaseOpen(false);
            if (!saveRef.current?.contains(e.target)) setSaveOpen(false);
        };
        const onKey = e => { if (e.key === "Escape") { setCaseOpen(false); setSaveOpen(false); } };
        document.addEventListener("mousedown", onDown);
        window.addEventListener("keydown", onKey);
        return () => { document.removeEventListener("mousedown", onDown); window.removeEventListener("keydown", onKey); };
    }, [caseOpen, saveOpen]);
    // The lawyer's own choice of case -- the only way the binding changes.
    const pickCase = (c) => { setCaseOpen(false); onRebind?.(bindingForNewDocument(c)); };
    // A saved draft stores editor HTML; a fresh template is plain text
    const initialHtml = draft ? draft.content : buildContent(tmpl, caseObj).replace(/\n/g, "<br>");
    const [aiMessages, setAiMessages] = useState([]);
    const [aiInput, setAiInput] = useState("");
    const [aiLoading, setAiLoading] = useState(false);
    const [draftId, setDraftId] = useState(draft?.id || null);
    const [saving, setSaving] = useState(false);
    const [saveErr, setSaveErr] = useState("");
    const [saved, setSaved] = useState(false);
    const [fontSize, setFontSize] = useState("13");
    const [font, setFont] = useState("Default Font");
    const [wordCount, setWordCount] = useState(0);
    // Court-Urdu pleading generator
    const [urduOpen, setUrduOpen] = useState(false);
    const [urduText, setUrduText] = useState("");
    const [urduBusy, setUrduBusy] = useState(false);
    const [urduPdfBusy, setUrduPdfBusy] = useState(false);
    const [urduMeta, setUrduMeta] = useState({ court_ur: "", title_ur: "" });
    // One key for one pleading. Held in a ref so a re-render between a failed
    // download and the retry cannot lose it — losing it is what turns a retry
    // into a second document.
    //
    // Cleared when the TEXT changes, because a different translation is a
    // different pleading: reusing the key there would replay the old revision
    // and hand the lawyer a PDF of text they had already replaced.
    const urduKeyRef = useRef(null);
    const urduKeyedTextRef = useRef(null);
    const [urduIssue, setUrduIssue] = useState("");

    // Publishing the draft as a real document. Same key discipline as the
    // pleading: one key per intent, dropped when the CONTENT changes, because
    // republishing edited prose under the old key would return the old
    // revision and tell the lawyer their edits were filed when they were not.
    const [publishing, setPublishing] = useState(false);
    const [published, setPublished] = useState(null);   // {docId, revisionId, ...}
    const [publishIssue, setPublishIssue] = useState("");
    const publishKeyRef = useRef(null);
    const publishedHtmlRef = useRef(null);
    // The server's citation check over the text AS LAST SAVED — restored with a
    // reopened draft, replaced on every save, and stale from the first edit
    // after it. `editSeq` counts edits so a save that raced a keystroke is
    // still marked stale when its answer lands.
    const [savedCheck, setSavedCheck] = useState(draft?.verification ?? null);
    const [checkStale, setCheckStale] = useState(false);
    const editSeq = useRef(0);
    const markEdited = () => { editSeq.current += 1; setCheckStale(true); };
    const editorRef = useRef(null);
    const aiEndRef = useRef(null);
    const aiInputRef = useRef(null);
    // "Draft with AI" from the template home opens here, ready to describe the facts.
    useEffect(() => { if (tmpl?.aiFirst) aiInputRef.current?.focus(); }, [tmpl]);

    const h = new Date().getHours();
    const greeting = h < 12 ? "Good Morning" : h < 17 ? "Good Afternoon" : "Good Evening";
    const { user } = useAuth();
    const userName = user?.full_name?.split(" ")[0] || "Counselor";

    // Follow the conversation once there is one. On an empty panel this would
    // scroll the assistant's introduction out of view.
    useEffect(() => {
        if (aiMessages.length || aiLoading) aiEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }, [aiMessages, aiLoading]);
    useEffect(() => { setWordCount((editorRef.current?.innerText || "").trim().split(/\s+/).filter(Boolean).length); }, []);

    // Emit tag-based formatting (<b>, <font face>, align=) rather than inline
    // CSS. The server sanitises draft HTML against an allowlist that permits
    // those and drops `style` -- nh3 does not filter CSS, so a permitted style
    // attribute would still admit url(...) inside an otherwise clean draft.
    // Without this, browsers that default to styleWithCSS would emit
    // <span style="font-weight:bold"> and the lawyer's formatting would be
    // silently stripped on save.
    useEffect(() => {
        try { document.execCommand("styleWithCSS", false, false); } catch { /* not supported */ }
    }, []);

    const exec = (cmd, val = null) => { editorRef.current?.focus(); document.execCommand(cmd, false, val); };
    const queryState = (cmd) => document.queryCommandState(cmd);

    const handleSave = async () => {
        if (saving || caseBlocked) return;
        setSaving(true); setSaveErr("");
        const seqAtSave = editSeq.current;
        const { data, error } = await saveDocDraft({
            draft_id: draftId,
            title: draft?.title || tmpl.name,
            content: editorRef.current?.innerHTML || "",
            template_name: tmpl.name,
            template_icon: tmpl.icon,
            case_id: caseId,
        });
        setSaving(false);
        if (error) { setSaveErr(error.message || "Save failed"); setTimeout(() => setSaveErr(""), 4000); return; }
        setDraftId(data.id);
        setSavedCheck(data.verification ?? null);
        setCheckStale(editSeq.current !== seqAtSave);
        setSaved(true); setTimeout(() => setSaved(false), 2500);
    };

    /* Save this draft into the system as a document.
     *
     * "SAVE", NOT "FILE". Filing is what a court accepts, and nothing here goes
     * near a court — implying otherwise on a legal product is the kind of wrong
     * word a user acts on. What this does is keep a fixed, hashed copy the
     * system can name, check citations on, and reproduce identically.
     *
     * The .doc export below remains, and is still the right tool for handing a
     * file to someone who will edit it. They are not alternatives.
     */
    const publishAsDocument = async () => {
        if (publishing || caseBlocked) return;
        const bodyHtml = editorRef.current?.innerHTML || "";
        if (!(editorRef.current?.innerText || "").trim()) {
            setPublishIssue("There is nothing in the draft to save.");
            return;
        }

        setPublishing(true);
        setPublishIssue("");

        // Edited prose is a new document, not a retry of the old one.
        if (publishedHtmlRef.current !== bodyHtml) {
            publishKeyRef.current = null;
            publishedHtmlRef.current = bodyHtml;
        }
        publishKeyRef.current = publishKeyRef.current || idempotencyKey();

        const res = await publishDraftAsDocumentV2({
            title: draft?.title || tmpl.name,
            bodyHtml,
            authorName: user?.full_name || "",
            caseId,
        }, publishKeyRef.current);
        setPublishing(false);

        if (res.error) {
            setPublishIssue(res.status === 404 && res.code === "feature_disabled"
                // Not an error the lawyer caused, and not one they can act on.
                // The export below is what they have until the flag is on.
                ? "Saving a draft to Documents is not enabled yet — use Export."
                : (res.error.message || "Could not save the draft."));
            return;
        }
        setPublished(res);
        setJustPublished(true); setTimeout(() => setJustPublished(false), 3500);
    };

    const handleExport = () => {
        // Word-compatible download: HTML body wrapped in a Word-namespaced
        // document, saved as .doc — opens with formatting in MS Word.
        const body = editorRef.current?.innerHTML || "";
        const html = `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word"><head><meta charset="utf-8"><title>${tmpl.name}</title></head><body style="font-family:Georgia,'Times New Roman',serif;line-height:1.9;">${body}</body></html>`;
        const blob = new Blob(["﻿", html], { type: "application/msword" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${(draft?.title || tmpl.name).replace(/[^\w\s-]/g, "").trim() || "document"}.doc`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    };

    const sendToAI = async () => {
        const q = aiInput.trim();
        if (!q || aiLoading || caseBlocked) return;
        setAiInput("");
        setAiMessages(prev => [...prev, { role: "user", text: q }]);
        setAiLoading(true);
        try {
            const history = aiMessages.map(m => ({ role: m.role === "user" ? "user" : "assistant", content: m.text }));
            let reply = "";
            // RAG-grounded: the backend retrieves real Pakistani law for this template
            // and instructs the model to cite only genuine sections/precedents.
            let verif = null;
            await aiDraftStream(
                {
                    instruction: q,
                    document: editorRef.current?.innerText || "",
                    template: tmpl.name,
                    // CASE-BOUND when a case is selected: the server authorises it
                    // and derives jurisdiction from it (so a Punjab matter no
                    // longer retrieves federal law). case_type is the fallback.
                    case_id: caseId,
                    case_type: templateCaseType(tmpl.name),
                    history,
                },
                (token) => { reply += token; },
                (evt) => { if (evt?.verification) verif = evt.verification; },
            );
            if (!reply) reply = "Sorry, I couldn't process that.";
            const looksLikeDoc = reply.length > 300 && (reply.includes("\n\n") || reply.includes("PRAYER") || reply.includes("Respectfully") || reply.includes("IN THE COURT") || reply.includes("PETITION") || reply.includes("AGREEMENT"));
            if (looksLikeDoc && editorRef.current) {
                editorRef.current.innerText = reply;
                markEdited();
                setWordCount(reply.trim().split(/\s+/).filter(Boolean).length);
            }
            setAiMessages(prev => [...prev, { role: "assistant", text: looksLikeDoc ? "✅ Document updated. Review the changes in the editor." : reply }]);
            // Surface the citation check the backend runs on the finished draft.
            // It used to be computed, streamed, and silently dropped by the client.
            if (verif) {
                // Same rules as every other citation display: repealed and
                // uncheckable citations are named, and "nothing to check" is
                // never phrased as a pass.
                const v = verificationView(verif);
                const note = `${v.tone === "ok" ? "⚖️" : "⚠️"} Citation check: ${v.headline}.${v.detail ? " " + v.detail : ""}`;
                setAiMessages(prev => [...prev, { role: "assistant", text: note }]);
            }
        } catch {
            setAiMessages(prev => [...prev, { role: "assistant", text: "Connection error. Please try again." }]);
        } finally {
            setAiLoading(false);
        }
    };

    const translateToUrdu = async () => {
        const src = (editorRef.current?.innerText || "").trim();
        if (!src) return;
        setUrduOpen(true); setUrduBusy(true); setUrduText("");
        try {
            let out = "";
            await aiPleadingUrduStream({ document: src, template: tmpl.name }, (tok) => { out += tok; setUrduText(out); });
            if (!out) setUrduText("(No translation returned — please try again.)");
        } catch (e) {
            setUrduText("Translation failed: " + (e?.message || "error"));
        } finally { setUrduBusy(false); }
    };

    const downloadUrduPdf = async () => {
        if (!urduText.trim() || urduPdfBusy) return;
        setUrduPdfBusy(true);
        setUrduIssue("");

        const filename = ((draft?.title || tmpl.name) + "-urdu")
            .replace(/[^\w\s-]/g, "").trim() || "pleading-urdu";
        const payload = {
            urdu_text: urduText, title_ur: urduMeta.title_ur,
            court_ur: urduMeta.court_ur, english_label: tmpl.name,
        };

        // A new translation is a new intent and must get a new key.
        if (urduKeyedTextRef.current !== urduText) {
            urduKeyRef.current = null;
            urduKeyedTextRef.current = urduText;
        }
        urduKeyRef.current = urduKeyRef.current || idempotencyKey();

        const v2 = await pleadingUrduDocumentV2(payload, urduKeyRef.current);

        if (!v2.error) {
            const saved = await downloadDocumentFile(v2.docId, filename, {
                revisionId: v2.revisionId, expectedPdfSha256: v2.pdfSha256,
            });
            setUrduPdfBusy(false);
            if (saved?.error) setUrduIssue(saved.error);
            return;
        }

        if (!(v2.status === 404 && v2.code === "feature_disabled")) {
            // A real failure. Reported rather than swallowed: the old code
            // returned silently on error, so a lawyer pressed Download, nothing
            // happened, and nothing said why.
            setUrduPdfBusy(false);
            setUrduIssue(v2.error.message || "Could not produce the PDF.");
            return;
        }

        // The flag is off. The legacy route still works; it just cannot be
        // retried safely, which is why it is the fallback and not the default.
        const { data, error } = await pleadingUrduPdf(payload, urduKeyRef.current);
        setUrduPdfBusy(false);
        if (error || !data?.doc_id) {
            setUrduIssue(error?.message || "Could not produce the PDF.");
            return;
        }
        const saved = await downloadDocumentFile(data.doc_id, filename, {
            revisionId: data.revision_id, expectedPdfSha256: data.pdf_sha256 });
        if (saved?.error) setUrduIssue(saved.error);
    };

    const FONT_OPTIONS = ["Default Font", "Georgia", "Times New Roman", "Courier New", "Arial"];
    const SIZE_OPTIONS = ["10", "11", "12", "13", "14", "16", "18", "20"];
    const mode = draftingMode(t);
    const docFile = (draft?.title || tmpl.name).replace(/[^\w\s-]/g, "").trim() || "document";
    const lineIcon = d => <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">{d}</svg>;

    return (
        <div data-drafter-editor data-drafting-theme data-mode={mode}>
            <style>{DRAFTING_TOKENS_CSS + "\n" + EDITOR_CSS}</style>

            {/* ── Top bar: back, the document, its actions, the account ── */}
            <header className="de-top">
                <button type="button" className="de-back" onClick={onBack} aria-label="Back to templates" title="Back to templates">
                    <Icon d={I.chevronLeft} size={20} />
                </button>
                <div className="de-title">
                    <h1>{draft?.title || tmpl.name}</h1>
                    <div className="de-meta">
                        <span className="de-cat">{tmpl.cat}</span>
                        <span aria-hidden="true">·</span>
                        <span>{new Date().toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}</span>
                        <span aria-hidden="true">·</span>
                        <span>{wordCount} words</span>
                    </div>
                </div>
                <div className="de-right">
                    {saved && <span className="de-note ok"><Icon d={I.checkCircle} size={12} /> Saved to My Drafts</span>}
                    {justPublished && <span className="de-note ok" role="status"><Icon d={I.checkCircle} size={12} /> PDF saved to the Vault</span>}
                    {saveErr && <span className="de-note bad" role="alert">{saveErr}</span>}
                    {publishIssue && <span className="de-note bad" role="alert">{publishIssue}</span>}
                    <CitationWarning draftCheck={savedCheck} stale={checkStale} />
                    {/* ONE SAVE (2026-10-11). Two side-by-side buttons, "Save Draft" and
                        "Save to Documents", saved to two different places and said
                        neither. Now the button saves the working draft (My Drafts, where
                        it stays editable), and its menu holds the other save -- a fixed
                        PDF copy kept in the Vault -- with where each one goes in words.
                        The menu stays mounted while closed so its items keep their
                        state. A Vault copy does NOT file anything with a court. */}
                    <div className="de-drop de-save" ref={saveRef}>
                        <button type="button" className="de-btn primary de-save-main" onClick={handleSave} disabled={saving || caseBlocked}
                            title="Save your working draft. It stays in My Drafts, where you can keep editing it.">
                            <Icon d={I.save} size={15} /> {saving ? "Saving…" : "Save Draft"}
                        </button>
                        <button type="button" className="de-btn primary de-save-more" aria-label="More ways to save"
                            aria-haspopup="menu" aria-expanded={saveOpen} onClick={() => setSaveOpen(o => !o)}>
                            <Icon d="m6 9 6 6 6-6" size={15} />
                        </button>
                        <div className="de-pop de-save-menu" role="menu" aria-label="Save" hidden={!saveOpen}>
                            <button type="button" role="menuitem" className="de-opt" onClick={() => { setSaveOpen(false); handleSave(); }}
                                disabled={saving || caseBlocked}>
                                Save draft<small>Your working copy, in Legal Drafting → My Drafts. Stays editable.</small>
                            </button>
                            <button type="button" role="menuitem" className="de-opt" onClick={() => { setSaveOpen(false); publishAsDocument(); }}
                                disabled={publishing || caseBlocked}
                                title="Save a fixed, hashed copy of this draft into your documents">
                                {publishing ? "Saving PDF…" : published ? "Save a new PDF copy to the Vault" : "Save as PDF to the Vault"}
                                <small>A fixed PDF in Documents → Vault{caseId ? ", filed under this case" : ""}. It cannot be edited; save again for a new copy.</small>
                            </button>
                            {/* Where the saved copy lives, once there is one. */}
                            {published && <>
                                <div className="de-sep-h" aria-hidden="true" />
                                <button type="button" role="menuitem" className="de-opt" data-open-vault
                                    onClick={() => { setSaveOpen(false); setPage?.("vault"); }}>
                                    Open in Vault<small>Where the PDF copy is kept</small>
                                </button>
                                <button type="button" role="menuitem" className="de-opt"
                                    onClick={async () => {
                                        setSaveOpen(false); setPublishIssue("");
                                        const saved = await downloadDocumentFile(published.docId, `${docFile}.pdf`,
                                            { revisionId: published.revisionId, expectedPdfSha256: published.pdfSha256 });
                                        if (saved?.error) setPublishIssue(saved.error);
                                    }}>
                                    Saved PDF — download<small>The copy kept in the Vault</small>
                                </button>
                            </>}
                        </div>
                    </div>
                    {/* Which matter this document belongs to (2026-10-11): one button in
                        place of the account. The binding changes ONLY when the lawyer
                        picks another case here -- never by itself; see
                        lib/draftCaseBinding.js. */}
                    <div className="de-drop" ref={caseRef}>
                        <button type="button" className="de-case" data-case-binding={binding.state}
                            aria-haspopup="listbox" aria-expanded={caseOpen} onClick={() => setCaseOpen(o => !o)}
                            title={binding.state === "unavailable"
                                ? "This draft's case could not be loaded. Save, AI drafting and Save to Documents are paused."
                                : "The case this draft belongs to"}>
                            <span className="ic"><Icon d="M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16M4 6h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2Z" size={16} /></span>
                            <span style={{ minWidth: 0, flex: 1 }}>
                                {binding.state === "bound" && <><b>{caseObj?.id} — {caseObj?.title}</b><small>{caseObj?.client}</small></>}
                                {binding.state === "none" && <><b>No case</b><small>Standalone document</small></>}
                                {binding.state === "loading" && <><b>Loading case…</b><small>Please wait</small></>}
                                {binding.state === "unavailable" && <><b>Case unavailable</b><small>Saving is paused</small></>}
                            </span>
                            <Icon d="m6 9 6 6 6-6" size={14} />
                        </button>
                        {caseOpen && (
                            <div className="de-pop" role="listbox" aria-label="Choose the case">
                                <h3>Attach to a case</h3>
                                <button type="button" role="option" className="de-opt"
                                    aria-selected={binding.state === "none"} onClick={() => pickCase(null)}>
                                    No case<small>Standalone document</small>
                                </button>
                                {cases.map(c => (
                                    <button key={c._id} type="button" role="option" className="de-opt"
                                        aria-selected={binding.state === "bound" && binding.caseId === c._id}
                                        onClick={() => pickCase(c)}>
                                        {c.id} — {c.title}<small>{c.client} · {c.type} · {c.status}</small>
                                    </button>
                                ))}
                                {cases.length === 0 && <div style={{ padding: "8px 10px", fontSize: 12.5, color: "var(--muted)" }}>You have no cases yet.</div>}
                            </div>
                        )}
                    </div>
                </div>
            </header>

            <div className="de-stage">
                {/* ── Formatting toolbar ── */}
                <div className="de-tools">
                <div className="de-toolbar" role="toolbar" aria-label="Formatting"
                    onWheel={e => {
                        // With the scrollbar hidden, a mouse wheel moves the bar along.
                        const el = e.currentTarget;
                        if (el.scrollWidth > el.clientWidth && Math.abs(e.deltaY) > Math.abs(e.deltaX)) el.scrollLeft += e.deltaY;
                    }}>
                    <TB label="Undo (Ctrl+Z)" onClick={() => exec("undo")}>{lineIcon(<><path d="M9 14 4 9l5-5" /><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" /></>)}</TB>
                    <TB label="Redo (Ctrl+Y)" onClick={() => exec("redo")}>{lineIcon(<><path d="m15 14 5-5-5-5" /><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13" /></>)}</TB>
                    <span className="de-sep" />
                    <label style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }} htmlFor="de-font">Font</label>
                    <select id="de-font" className="de-select" style={{ width: 146 }} value={font}
                        onChange={e => { setFont(e.target.value); exec("fontName", e.target.value); }}>
                        {FONT_OPTIONS.map(f => <option key={f} value={f}>{f}</option>)}
                    </select>
                    <label style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }} htmlFor="de-size">Font size</label>
                    <select id="de-size" className="de-select" style={{ width: 62 }} value={fontSize}
                        onChange={e => { setFontSize(e.target.value); exec("fontSize", e.target.value); }}>
                        {SIZE_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <span className="de-sep" />
                    <TB label="Bold (Ctrl+B)" active={queryState("bold")} onClick={() => exec("bold")} style={{ fontFamily: "Georgia, serif", fontWeight: 900, fontSize: 17 }}>B</TB>
                    <TB label="Italic (Ctrl+I)" active={queryState("italic")} onClick={() => exec("italic")} style={{ fontFamily: "Georgia, serif", fontStyle: "italic", fontWeight: 400, fontSize: 17 }}>I</TB>
                    <TB label="Underline (Ctrl+U)" active={queryState("underline")} onClick={() => exec("underline")} style={{ textDecoration: "underline", fontSize: 16 }}>U</TB>
                    <TB label="Subscript" onClick={() => exec("subscript")} style={{ fontSize: 15 }}><span>X<sub style={{ fontSize: "60%" }}>1</sub></span></TB>
                    <TB label="Superscript" onClick={() => exec("superscript")} style={{ fontSize: 15 }}><span>X<sup style={{ fontSize: "60%" }}>1</sup></span></TB>
                    <TB label="Strikethrough" onClick={() => exec("strikeThrough")} style={{ textDecoration: "line-through", fontSize: 16 }}>S</TB>
                    <span className="de-sep" />
                    <TB label="Align left" active={queryState("justifyLeft")} onClick={() => exec("justifyLeft")}>{lineIcon(<path d="M4 6h16M4 10h10M4 14h16M4 18h10" />)}</TB>
                    <TB label="Align centre" active={queryState("justifyCenter")} onClick={() => exec("justifyCenter")}>{lineIcon(<path d="M4 6h16M7 10h10M4 14h16M7 18h10" />)}</TB>
                    <TB label="Align right" active={queryState("justifyRight")} onClick={() => exec("justifyRight")}>{lineIcon(<path d="M4 6h16M10 10h10M4 14h16M10 18h10" />)}</TB>
                    <TB label="Justify" active={queryState("justifyFull")} onClick={() => exec("justifyFull")}>{lineIcon(<path d="M4 6h16M4 10h16M4 14h16M4 18h16" />)}</TB>
                    <span className="de-sep" />
                    <TB label="Bullet list" active={queryState("insertUnorderedList")} onClick={() => exec("insertUnorderedList")}>{lineIcon(<><path d="M9 6h11M9 12h11M9 18h11" /><path d="M4.5 6h.01M4.5 12h.01M4.5 18h.01" strokeWidth="3" /></>)}</TB>
                    <TB label="Numbered list" active={queryState("insertOrderedList")} onClick={() => exec("insertOrderedList")}>{lineIcon(<><path d="M10 6h10M10 12h10M10 18h10" /><path d="M4 5h1.5v4M4 9h3M4 13.5c0-1 2.8-1 2.8.4 0 1-2.8 1.8-2.8 3.1h3" strokeWidth="1.5" /></>)}</TB>
                    <span className="de-sep" />
                    <TB label="Heading 1" onClick={() => exec("formatBlock", "h1")} style={{ fontSize: 15 }}>H1</TB>
                    <TB label="Heading 2" onClick={() => exec("formatBlock", "h2")} style={{ fontSize: 15 }}>H2</TB>
                    <TB label="Heading 3" onClick={() => exec("formatBlock", "h3")} style={{ fontSize: 15 }}>H3</TB>
                    <span className="de-sep" />
                    <TB label="Block quote" onClick={() => exec("formatBlock", "blockquote")}>{lineIcon(<path d="M7 7h4v4H8.5c0 2 1 3 2.5 3.5M14 7h4v4h-2.5c0 2 1 3 2.5 3.5" />)}</TB>
                    <TB label="Horizontal rule" onClick={() => exec("insertHorizontalRule")}>{lineIcon(<path d="M4 12h16" strokeWidth="2.6" />)}</TB>
                    <span className="de-sep" />
                    <TB label="Export Word (.doc)" onClick={handleExport} style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: ".04em" }}>
                        <span style={{ display: "grid", placeItems: "center", gap: 1 }}><Icon d={I.fileText} size={15} />DOC</span>
                    </TB>
                    <TB label="Translate this draft into court Urdu" onClick={translateToUrdu} style={{ fontSize: 14, fontWeight: 600, padding: "0 10px" }}>اردو</TB>
                </div>
                </div>

                <div className="de-split">
                    {/* ── The document ── */}
                    <section className="de-doc" aria-label="Document">
                        {/* The one note that stays on the page: the actions it explains
                            are paused, so the lawyer must see why. */}
                        {binding.state === "unavailable" && (
                            <div className="de-strips" role="alert">
                                <div style={{ fontWeight: 600, background: "var(--danger-soft)", color: "var(--danger)" }}>
                                    This draft belongs to a case that could not be loaded — it may have been
                                    reassigned, or you may be offline. Save, AI drafting and Save to Documents
                                    are paused so this draft is not attached to another matter. Export still works.
                                </div>
                            </div>
                        )}
                        <div className="de-scroll">
                            <div
                                ref={editorRef}
                                className="de-paper"
                                contentEditable
                                suppressContentEditableWarning
                                spellCheck={false}
                                aria-label={`${tmpl.name} — document text`}
                                onInput={e => { markEdited(); setWordCount(e.currentTarget.innerText.trim().split(/\s+/).filter(Boolean).length); }}
                                style={{ fontFamily: font === "Default Font" ? "Georgia, 'Times New Roman', serif" : font }}
                                dangerouslySetInnerHTML={{ __html: initialHtml }}
                            />
                        </div>
                    </section>

                    {/* ── Draft Assistant ── */}
                    <aside className="de-assist" aria-label="Draft Assistant">
                        <div className="de-assist-head">
                            <b>Draft Assistant</b>
                        </div>
                        <div className="de-assist-body">
                            {aiMessages.length === 0 && (
                                <>
                                    <div className="de-hello">
                                        <div className="de-greet">
                                            <b>{greeting}, <em>{userName}</em></b>
                                            <p><strong style={{ color: "var(--ink)" }}>{tmpl.name}</strong> is loaded. Ask for a new clause, a rewrite, a tone change or an improvement to the current draft.</p>
                                        </div>
                                    </div>
                                    <div className="de-label">Quick actions</div>
                                    <div className="de-quick">
                                        {/* A short name on the pill; the full instruction goes into the prompt. */}
                                        {[["Stronger prayer", "Add a stronger prayer clause"], ["Formal tone", "Make the tone more formal"],
                                          ["Jurisdiction", "Add a jurisdiction paragraph"], ["Key arguments", "Summarise key arguments"]].map(([label, text]) => (
                                            <button key={text} type="button" title={text} onClick={() => { setAiInput(text); aiInputRef.current?.focus(); }}>{label}</button>
                                        ))}
                                    </div>
                                </>
                            )}
                            {aiMessages.map((msg, i) => (
                                <div key={i} className={`de-msg ${msg.role === "user" ? "user" : "ai"}`}>{msg.text}</div>
                            ))}
                            {aiLoading && <div className="de-msg ai de-dots" aria-label="Drafting"><i /><i style={{ animationDelay: ".2s" }} /><i style={{ animationDelay: ".4s" }} /></div>}
                            <div ref={aiEndRef} />
                        </div>
                        <div className="de-compose">
                            <div className="de-compose-box">
                                <label style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }} htmlFor="de-prompt">Prompt for the draft assistant</label>
                                <textarea
                                    id="de-prompt"
                                    ref={aiInputRef}
                                    value={aiInput} onChange={e => setAiInput(e.target.value)}
                                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendToAI(); } }}
                                    placeholder="Enter prompt to generate or modify draft"
                                    rows={1}
                                />
                                <div className="de-compose-row">
                                    <span className="de-hint">Enter to send · Shift+Enter for a new line</span>
                                    <button type="button" className="de-send-ic" onClick={sendToAI} disabled={!aiInput.trim() || aiLoading || caseBlocked}
                                        aria-label="Generate" title="Generate (Enter)">
                                        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
                                        <span className="de-sr">Generate</span>
                                    </button>
                                </div>
                            </div>
                        </div>
                    </aside>
                </div>
            </div>

            {urduOpen && (<ModalPortal>
                <div onClick={() => setUrduOpen(false)} style={{
                    position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 60,
                    display: "flex", alignItems: "center", justifyContent: "center", padding: 20,
                }}>
                    <div onClick={e => e.stopPropagation()} style={{
                        width: "min(760px, 96vw)", maxHeight: "92vh", display: "flex", flexDirection: "column",
                        background: t.surface, border: `1px solid ${t.border}`, borderRadius: 14, boxShadow: "0 20px 60px rgba(0,0,0,0.4)",
                    }}>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 18px", borderBottom: `1px solid ${t.border}` }}>
                            <div>
                                <div style={{ fontSize: 14, fontWeight: 800, color: t.text }}>Court Urdu — عدالتی اردو</div>
                                <div style={{ fontSize: 11, color: t.textFaint, marginTop: 2 }}>{tmpl.name} · review the translation, then export as an RTL PDF</div>
                            </div>
                            <button onClick={() => setUrduOpen(false)} style={{ background: "none", border: "none", color: t.textMuted, fontSize: 20, cursor: "pointer", lineHeight: 1 }}>×</button>
                        </div>

                        <div style={{ padding: 16, overflowY: "auto" }}>
                            <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
                                <input value={urduMeta.court_ur} onChange={e => setUrduMeta(m => ({ ...m, court_ur: e.target.value }))} placeholder="عدالت (court header, optional)" dir="rtl"
                                    style={{ padding: "8px 10px", borderRadius: 8, border: `1.5px solid ${t.border}`, background: t.card, color: t.text, fontSize: 13, fontFamily: "inherit", outline: "none" }} />
                                <input value={urduMeta.title_ur} onChange={e => setUrduMeta(m => ({ ...m, title_ur: e.target.value }))} placeholder="عنوان (title, optional)" dir="rtl"
                                    style={{ padding: "8px 10px", borderRadius: 8, border: `1.5px solid ${t.border}`, background: t.card, color: t.text, fontSize: 13, fontFamily: "inherit", outline: "none" }} />
                            </div>
                            <textarea value={urduText} onChange={e => setUrduText(e.target.value)} dir="rtl" readOnly={urduBusy}
                                placeholder={urduBusy ? "ترجمہ ہو رہا ہے…" : ""}
                                style={{ width: "100%", minHeight: 320, boxSizing: "border-box", padding: "12px 14px", borderRadius: 10, border: `1.5px solid ${t.border}`, background: t.card, color: t.text, fontSize: 15, lineHeight: 2, fontFamily: "'Noto Naskh Arabic','Jameel Noori Nastaleeq',serif", resize: "vertical", outline: "none" }} />
                            {urduBusy && <div style={{ fontSize: 11.5, color: t.primary, marginTop: 8 }}>Translating… ترجمہ ہو رہا ہے…</div>}
                        </div>

                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 18px", borderTop: `1px solid ${t.border}`, gap: 10 }}>
                            {/* A failed download used to return silently: the
                                lawyer pressed Download, nothing arrived, and
                                nothing said why. */}
                            <span style={{ fontSize: 10.5, color: urduIssue ? t.danger : t.textFaint, flex: 1 }}>
                                {urduIssue || "Machine-assisted — verify legal terms before filing"}
                            </span>
                            <div style={{ display: "flex", gap: 8 }}>
                                <button onClick={translateToUrdu} disabled={urduBusy} style={{ padding: "8px 14px", borderRadius: 8, border: `1px solid ${t.border}`, background: t.card, color: t.text, fontSize: 12, fontWeight: 700, cursor: urduBusy ? "default" : "pointer", fontFamily: "inherit" }}>↻ Retranslate</button>
                                <button onClick={downloadUrduPdf} disabled={urduBusy || urduPdfBusy || !urduText.trim()} style={{ padding: "8px 16px", borderRadius: 8, border: "none", background: (urduBusy || urduPdfBusy || !urduText.trim()) ? t.border : "#16a34a", color: "#fff", fontSize: 12, fontWeight: 800, cursor: (urduBusy || urduPdfBusy || !urduText.trim()) ? "default" : "pointer", fontFamily: "inherit" }}>{urduPdfBusy ? "Generating…" : "⬇ Download Urdu PDF"}</button>
                            </div>
                        </div>
                    </div>
                </div>
            </ModalPortal>)}
        </div>
    );
}

// ============================================================
// ROOT
// ============================================================
const _DA_MAP = { open: "Filed", active: "Under Hearing", closed: "Closed", dismissed: "Closed" };

// One shape for a case, whether it came from the list or was fetched by id.
const _mapCase = (c) => ({
    id: c.case_number || c._id,
    _id: c._id,
    title: c.title || "Untitled",
    client: c.client_name || "—",
    court: c.province || "—",
    type: c.case_type ? c.case_type.charAt(0).toUpperCase() + c.case_type.slice(1) : "Other",
    status: _DA_MAP[c.status] || "Filed",
});

function DocAutomationPage() {
    const { t } = useTheme();
    const { activeCase } = useCase();
    const [stage, setStage] = useState("gallery");
    const [selectedTemplate, setSelectedTemplate] = useState(null);
    const [apiCases, setApiCases] = useState([]);
    const [selectedCaseId, setSelectedCaseId] = useState("");
    const [drafts, setDrafts] = useState([]);
    const [activeDraft, setActiveDraft] = useState(null);
    // The open editor's case, fixed when it opened. See lib/draftCaseBinding.js.
    const [editorBinding, setEditorBinding] = useState(NO_CASE);
    // Guards against a slow case lookup for one draft landing after another
    // draft (or a new document) has been opened.
    const openSeq = useRef(0);

    useEffect(() => {
        if (stage !== "gallery") return;
        listDocDrafts().then(({ data }) => { if (Array.isArray(data)) setDrafts(data); });
    }, [stage]);

    const openDraft = async (d) => {
        const seq = ++openSeq.current;
        setActiveDraft(d);
        setEditorBinding(pendingBindingForDraft(d));
        setSelectedTemplate({ id: -1, name: d.template_name || d.title, cat: "Draft", desc: "", icon: d.template_icon || "📄" });
        setStage("editor");
        const binding = await bindingForDraft(d, apiCases, getCase, _mapCase);
        if (seq === openSeq.current) setEditorBinding(binding);
    };

    const openTemplate = (tmpl) => {
        ++openSeq.current;
        setActiveDraft(null);
        setEditorBinding(bindingForNewDocument(activeCaseObj));
        setSelectedTemplate(tmpl);
        setStage("editor");
    };

    const removeDraft = async (id) => {
        const { error } = await deleteDocDraft(id);
        if (!error) setDrafts(prev => prev.filter(x => x.id !== id));
    };

    useEffect(() => {
        listCases({ page_size: 50 }).then(({ data }) => {
            if (data?.items) {
                const mapped = data.items.map(_mapCase);
                setApiCases(mapped);
                // A CASE IS OPTIONAL. Only the case the lawyer is already working
                // in is preselected. It used to fall back to the FIRST listed case,
                // so a new template silently bound itself -- prefilled with that
                // case's client -- to a matter the lawyer never chose, and "Save to
                // Documents" filed it there. No active case: no case.
                if (activeCase) {
                    const match = mapped.find(c => c.id === activeCase || c._id === activeCase);
                    if (match) setSelectedCaseId(match.id);
                }
            }
        });
    }, []);

    const activeCaseObj = apiCases.find(c => c.id === selectedCaseId) || null;

    // Fills the app's <main> in normal flow (2026-10-09). It used to be
    // position:fixed at the sidebar's guessed width, but <main> animates in
    // with a transform, which makes it the containing block: the offset
    // applied twice and left an empty band beside the sidebar.
    return (
        <div data-drafter-pane style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0, minWidth: 0, background: t.bg }}>
            {stage === "gallery" && (
                <DraftingHome
                    onSelect={openTemplate}
                    drafts={drafts}
                    onOpenDraft={openDraft}
                    onDeleteDraft={removeDraft}
                    t={t}
                />
            )}
            {stage === "editor" && selectedTemplate && (
                <StageEditor tmpl={selectedTemplate} binding={editorBinding} draft={activeDraft} onBack={() => setStage("gallery")} t={t}
                    cases={apiCases} onRebind={b => { ++openSeq.current; setEditorBinding(b); }} />
            )}
        </div>
    );
}

export { DocAutomationPage };
