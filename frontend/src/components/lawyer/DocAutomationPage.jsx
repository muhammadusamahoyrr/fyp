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
import { pleadingRequirements } from "@/lib/api.js";

// ============================================================
// EDITOR LOOK (2026-10-09) — the approved drafting-editor design, on the
// Legal Drafting palette (draftingTheme.js). Scoped by [data-drafter-editor].
// ============================================================
export const EDITOR_CSS = `[data-drafter-editor]{flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;--top-h:72px;--tools-h:72px;background:var(--bg);color:var(--ink);font:15px/1.5 "Hanken Grotesk",system-ui,sans-serif;-webkit-font-smoothing:antialiased;--stage:rgba(0,0,0,.16)}
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
[data-drafter-editor] .de-acct{display:flex;align-items:center;gap:10px;height:46px;padding:0 14px 0 6px;border-radius:999px;border:1px solid var(--line);background:var(--surface);max-width:250px}
[data-drafter-editor] .de-acct b{display:block;font-size:13px;font-weight:600;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-drafter-editor] .de-acct small{font-size:11.5px;color:var(--muted)}
[data-drafter-editor] .de-avatar{width:34px;height:34px;flex:none;border-radius:50%;display:grid;place-items:center;font-size:12px;font-weight:700;background:#5B7BE0;color:#fff}
[data-drafter-editor] .de-stage{flex:none;margin:0 18px 18px;border-radius:24px;background:var(--stage);display:flex;flex-direction:column;padding:0 18px 18px}
[data-drafter-editor] .de-tools{position:sticky;top:var(--top-h);z-index:7;padding-top:18px;margin:0 -18px;padding-inline:18px;border-radius:24px 24px 0 0;background:linear-gradient(var(--stage),var(--stage)) top/100% 18px no-repeat,linear-gradient(var(--bg),var(--bg)) top/100% 18px no-repeat}
[data-drafter-editor] .de-toolbar{display:flex;align-items:center;gap:2px;padding:8px;border-radius:16px;border:1px solid var(--line);background:var(--surface);overflow-x:auto;scrollbar-width:thin;box-shadow:var(--shadow-rest)}
[data-drafter-editor] .de-tb{height:36px;min-width:34px;padding:0 6px;border-radius:9px;border:1px solid transparent;background:transparent;color:var(--muted);display:grid;place-items:center;cursor:pointer;font-weight:700;font-size:15px;flex:none}
[data-drafter-editor] .de-tb:hover{background:var(--hover-tint);color:var(--hover-ink)}
[data-drafter-editor] .de-tb[aria-pressed="true"]{background:var(--teal);color:var(--on-teal)}
[data-drafter-editor] .de-sep{width:1px;height:24px;background:var(--line-strong);margin:0 4px;flex:none}
[data-drafter-editor] .de-select{height:40px;padding:0 10px;border-radius:10px;border:1px solid var(--line);background:var(--input);font-size:14px;flex:none;cursor:pointer}
[data-drafter-editor] .de-select:hover{border-color:var(--hover-line)}
[data-drafter-editor] .de-split{display:flex;gap:16px;margin-top:16px;align-items:flex-start}
[data-drafter-editor] .de-doc{flex:1;min-width:0;display:flex;flex-direction:column;border-radius:18px;border:1px solid var(--line);background:var(--surface)}
[data-drafter-editor] .de-strips{flex:none;font-size:12px;color:var(--muted);border-bottom:1px solid var(--line)}
[data-drafter-editor] .de-strips > div{padding:7px 20px}
[data-drafter-editor] .de-strips > div + div{border-top:1px solid var(--line)}
[data-drafter-editor] .de-scroll{padding:28px 24px 24px}
[data-drafter-editor] .de-paper{max-width:820px;margin:0 auto;min-height:640px;background:var(--paper);color:var(--paper-ink);border-radius:6px;padding:64px 76px;line-height:1.95;font-size:15px;outline:none;white-space:pre-wrap;box-shadow:0 18px 40px -22px rgba(0,0,0,.65)}
[data-drafter-editor] .de-page{text-align:center;margin-top:10px;font-size:11px;color:var(--faint)}
[data-drafter-editor] .de-assist{width:400px;flex:none;display:flex;flex-direction:column;border-radius:18px;border:1px solid var(--line);background:var(--surface);overflow:hidden;position:sticky;top:calc(var(--top-h) + var(--tools-h) + 16px);height:calc(100vh - var(--top-h) - var(--tools-h) - 40px);min-height:420px}
[data-drafter-editor] .de-assist-head{padding:18px 24px;background:var(--surface-2);border-bottom:1px solid var(--line)}
[data-drafter-editor] .de-assist-head b{display:block;font-size:17px}
[data-drafter-editor] .de-assist-head span{font-size:13.5px;color:var(--muted)}
[data-drafter-editor] .de-assist-body{flex:1;min-height:0;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:12px;scrollbar-width:thin}
[data-drafter-editor] .de-hello{border:1px solid var(--line);border-radius:18px;background:var(--surface-2);padding:20px}
[data-drafter-editor] .de-hello-top{display:flex;gap:14px;align-items:center}
[data-drafter-editor] .de-hello-ic{width:58px;height:58px;flex:none;border-radius:14px;background:var(--brand-solid);color:var(--on-brand);display:grid;place-items:center}
[data-drafter-editor] .de-hello-top b{display:block;font-size:19px;line-height:1.2}
[data-drafter-editor] .de-hello-top span{font-size:14px;color:var(--muted)}
[data-drafter-editor] .de-greet{margin-top:16px;border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:var(--surface)}
[data-drafter-editor] .de-greet b{font-size:16px}
[data-drafter-editor] .de-greet b em{font-style:normal;color:var(--brand-text)}
[data-drafter-editor] .de-greet p{margin:6px 0 0;font-size:13.5px;color:var(--muted);line-height:1.6}
[data-drafter-editor] .de-label{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--faint);font-weight:600}
[data-drafter-editor] .de-quick{display:flex;flex-direction:column;gap:6px}
[data-drafter-editor] .de-quick button{padding:9px 12px;border-radius:11px;border:1px solid var(--line);background:transparent;color:var(--muted);text-align:left;font-size:13px;cursor:pointer}
[data-drafter-editor] .de-quick button:hover{border-color:var(--hover-line);background:var(--hover-tint);color:var(--hover-ink)}
[data-drafter-editor] .de-msg{max-width:92%;padding:10px 13px;font-size:13.5px;line-height:1.6;white-space:pre-wrap}
[data-drafter-editor] .de-msg.user{align-self:flex-end;border-radius:14px 14px 4px 14px;background:var(--teal);color:var(--on-teal)}
[data-drafter-editor] .de-msg.ai{align-self:flex-start;border-radius:4px 14px 14px 14px;background:var(--surface-2);border:1px solid var(--line)}
[data-drafter-editor] .de-dots{display:flex;gap:5px;padding:12px 16px}
[data-drafter-editor] .de-dots i{width:6px;height:6px;border-radius:50%;background:var(--brand-text);animation:pulse 1.2s ease infinite}
[data-drafter-editor] .de-compose{flex:none;padding:14px 18px 16px;border-top:1px solid var(--line)}
[data-drafter-editor] .de-compose-box{border:1px solid var(--line);border-radius:18px;background:var(--surface-2);overflow:hidden}
[data-drafter-editor] .de-compose-box:focus-within{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-drafter-editor] .de-compose textarea{width:100%;border:0;outline:none;background:transparent;resize:none;padding:16px 18px 6px;font-size:15px;line-height:1.55}
[data-drafter-editor] .de-compose textarea::placeholder{color:var(--faint)}
[data-drafter-editor] .de-compose-row{display:flex;justify-content:space-between;align-items:center;padding:4px 10px 10px 18px;gap:10px}
[data-drafter-editor] .de-hint{font-size:11.5px;color:var(--faint)}
[data-drafter-editor] .de-foot{font-size:11.5px;color:var(--faint);text-align:center;margin-top:9px}
[data-drafter-editor] .de-send{overflow:hidden}
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
const _TONE = (t) => ({
    ok: t.success, warn: t.warn || "#FFC857", danger: t.danger || "#e5484d", neutral: t.textMuted,
});

function CitationStrip({ t, draftCheck, stale, documentCheck }) {
    const d = verificationView(draftCheck);
    const doc = verificationView(documentCheck);
    const tone = _TONE(t);
    return (
        <div data-citation-strip style={{
            fontSize: 12, color: "var(--muted)", display: "flex", flexWrap: "wrap", gap: "4px 18px",
        }}>
            <span data-check="draft">
                <b style={{ color: "var(--ink)" }}>Citation check · last saved draft:</b>{" "}
                {d ? <>
                    <span style={{ color: stale ? t.textMuted : tone[d.tone], fontWeight: 700,
                                   textDecoration: stale ? "line-through" : "none" }}>{d.headline}</span>
                    {stale
                        ? <span data-stale style={{ color: tone.warn, fontWeight: 700 }}> — out of date: the text has changed. Save again to re-check.</span>
                        : d.detail && <span> — {d.detail}</span>}
                </> : <span>not checked yet — citations are checked when you save.</span>}
            </span>
            {doc && (
                <span data-check="document">
                    <b style={{ color: "var(--ink)" }}>Copy saved to Documents (frozen):</b>{" "}
                    <span style={{ color: tone[doc.tone], fontWeight: 700 }}>{doc.headline}</span>
                </span>
            )}
        </div>
    );
}

/* WHAT THE CODE REQUIRES OF THIS INSTRUMENT — for the lawyer to confirm.
 *
 * A prose draft cannot be judged by the field-based compliance check, and
 * deciding from free text that a clause is "satisfied" would be a false pass in
 * a court document. So this lists the requirements with their rule and a hint,
 * and says plainly that nothing was checked. The ticks are the lawyer's own
 * working notes for this session; they are not saved and certify nothing. */
function RequirementsChecklist({ t, report }) {
    const [open, setOpen] = useState(false);
    const [ticked, setTicked] = useState(() => new Set());
    if (!report?.covered || !report.items?.length) return null;
    const toggle = i => setTicked(prev => {
        const next = new Set(prev);
        next.has(i) ? next.delete(i) : next.add(i);
        return next;
    });
    return (
        <div data-requirements style={{ fontSize: 12, color: "var(--muted)" }}>
            <button type="button" onClick={() => setOpen(o => !o)} style={{
                background: "transparent", border: "none", padding: 0, cursor: "pointer",
                color: "var(--ink)", fontSize: 12, fontWeight: 700,
            }}>
                {open ? "▾" : "▸"} Requirements checklist · {report.basis} — {ticked.size}/{report.items.length} confirmed by you
            </button>
            <span> · not checked automatically: confirm each against your draft.</span>
            {open && (
                <ul style={{ listStyle: "none", margin: "6px 0 2px", padding: 0 }}>
                    {report.items.map((item, i) => (
                        <li key={i} style={{ display: "flex", gap: 8, padding: "3px 0", alignItems: "flex-start" }}>
                            <input type="checkbox" checked={ticked.has(i)} onChange={() => toggle(i)}
                                   aria-label={`Confirmed: ${item.clause}`} style={{ marginTop: 2 }} />
                            <span>
                                <b style={{ color: t.textDim }}>{item.clause}</b> — {item.requirement}
                                {item.conditional_on && <i> (only if applicable)</i>}
                                {item.hint && <span style={{ color: t.textFaint }}> · {item.hint}</span>}
                            </span>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}

function StageEditor({ tmpl, binding = NO_CASE, draft, onBack, t }) {
    // The case this document is bound to — fixed when the editor opened, never
    // the page selector's current value. See lib/draftCaseBinding.js.
    const caseObj = binding.caseObj;
    const caseId = boundCaseId(binding);
    const { setPage } = useCase();
    const caseBlocked = caseActionsBlocked(binding);
    // The instrument this draft is, when the system knows one. A reopened draft
    // may carry only the template's name, so the catalogue is asked by name too.
    const requirementsType = tmpl?.template_type
        || TEMPLATES.find(x => x.name === tmpl?.name)?.template_type || null;
    const [requirements, setRequirements] = useState(null);
    useEffect(() => {
        if (!requirementsType) { setRequirements(null); return; }
        let live = true;
        pleadingRequirements(requirementsType).then(({ data }) => {
            // Optional aid: a failed load shows no checklist rather than an error.
            if (live) setRequirements(data || null);
        });
        return () => { live = false; };
    }, [requirementsType]);
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
    const displayName = user?.full_name || "Advocate";
    const initials = displayName.split(/\s+/).filter(Boolean).map(w => w[0]).join("").slice(0, 2).toUpperCase();
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
                    {saved && <span className="de-note ok"><Icon d={I.checkCircle} size={12} /> Draft Saved</span>}
                    {saveErr && <span className="de-note bad" role="alert">{saveErr}</span>}
                    {publishIssue && <span className="de-note bad" role="alert">{publishIssue}</span>}
                    <button type="button" className="de-btn primary" onClick={handleSave} disabled={saving || caseBlocked}>
                        <Icon d={I.save} size={15} /> {saving ? "Saving…" : "Save Draft"}
                    </button>
                    {/* Beside Export, not instead of it. Export hands someone a
                        file they will edit. This keeps the draft as an artifact the
                        system can name, hash and reproduce — which is what makes a
                        citation check on it mean anything later. It does NOT file
                        anything with a court, and the label must not suggest so. */}
                    <button type="button" className="de-btn" onClick={publishAsDocument} disabled={publishing || caseBlocked}
                        title="Save a fixed, hashed copy of this draft into your documents">
                        <Icon d={I.fileText} size={15} /> {publishing ? "Saving…" : published ? "Saved ✓" : "Save to Documents"}
                    </button>
                    {published && (
                        <button type="button" className="de-btn"
                            onClick={async () => {
                                setPublishIssue("");
                                const saved = await downloadDocumentFile(published.docId, `${docFile}.pdf`,
                                    { revisionId: published.revisionId, expectedPdfSha256: published.pdfSha256 });
                                if (saved?.error) setPublishIssue(saved.error);
                            }}>
                            <Icon d={I.download} size={15} /> Saved PDF
                        </button>
                    )}
                    {/* Where the saved copy now lives: the lawyer's Vault, to file it
                        into a folder or find it again. Not a dead end after saving. */}
                    {published && (
                        <button type="button" className="de-btn" data-open-vault onClick={() => setPage?.("vault")}>
                            <Icon d={I.folder} size={15} /> Open in Vault
                        </button>
                    )}
                    <div className="de-acct" data-account>
                        <span className="de-avatar" aria-hidden="true">{initials}</span>
                        <span style={{ minWidth: 0 }}><b>{displayName}</b><small>Advocate</small></span>
                    </div>
                </div>
            </header>

            <div className="de-stage">
                {/* ── Formatting toolbar ── */}
                <div className="de-tools">
                <div className="de-toolbar" role="toolbar" aria-label="Formatting">
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
                        <div className="de-strips">
                            {/* Which matter this document belongs to: the page's case
                                selector is not visible here, so without this the lawyer
                                cannot see which case the AI and Save act on. */}
                            <div data-case-binding={binding.state} style={{
                                fontWeight: 600,
                                background: binding.state === "unavailable" ? "var(--danger-soft)" : "transparent",
                                color: binding.state === "unavailable" ? "var(--danger)" : "var(--muted)",
                            }}>
                                {binding.state === "bound" && <>Case: {caseObj?.id} — {caseObj?.title}</>}
                                {binding.state === "none" && <>No case — this draft is not attached to any matter.</>}
                                {binding.state === "loading" && <>Loading the case this draft belongs to…</>}
                                {binding.state === "unavailable" && <>
                                    This draft belongs to a case that could not be loaded — it may have been
                                    reassigned, or you may be offline. Save, AI drafting and Save to Documents
                                    are paused so this draft is not attached to another matter. Export still works.
                                </>}
                            </div>
                            {/* Citation check — the server's, not the browser's: the
                                draft as last saved (stale on edit) and the copy saved
                                to Documents (frozen). */}
                            <CitationStrip t={t} draftCheck={savedCheck} stale={checkStale}
                                documentCheck={published?.verification ?? null} />
                            <RequirementsChecklist t={t} report={requirements} />
                        </div>
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
                            <div className="de-page">— Page 1 —</div>
                        </div>
                    </section>

                    {/* ── Draft Assistant ── */}
                    <aside className="de-assist" aria-label="Draft Assistant">
                        <div className="de-assist-head">
                            <b>Draft Assistant</b>
                            <span>Prompt edits and improvements</span>
                        </div>
                        <div className="de-assist-body">
                            {aiMessages.length === 0 && (
                                <>
                                    <div className="de-hello">
                                        <div className="de-hello-top">
                                            <span className="de-hello-ic"><Icon d={I.sparkles} size={24} /></span>
                                            <span style={{ flex: 1, minWidth: 0 }}><b>AI Drafter Assistant</b><span>Your legal drafting co-pilot</span></span>
                                            <span aria-hidden="true" style={{ color: "var(--gold)", alignSelf: "flex-start" }}><Icon d={h < 17 ? I.sun : I.moon} size={22} /></span>
                                        </div>
                                        <div className="de-greet">
                                            <b>{greeting}, <em>{userName}</em></b>
                                            <p><strong style={{ color: "var(--ink)" }}>{tmpl.name}</strong> is loaded. Ask for a new clause, a rewrite, a tone change or an improvement to the current draft.</p>
                                        </div>
                                    </div>
                                    <div className="de-label">Quick actions</div>
                                    <div className="de-quick">
                                        {["Add a stronger prayer clause", "Make the tone more formal", "Add a jurisdiction paragraph", "Summarise key arguments"].map(text => (
                                            <button key={text} type="button" onClick={() => { setAiInput(text); aiInputRef.current?.focus(); }}>{text}</button>
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
                                    rows={3}
                                />
                                <div className="de-compose-row">
                                    <span className="de-hint">Enter to send · Shift+Enter for a new line</span>
                                    <button type="button" className="de-btn primary de-send" style={{ height: 36 }} onClick={sendToAI} disabled={!aiInput.trim() || aiLoading || caseBlocked}>
                                        <Icon d={I.send} size={13} /> Generate
                                    </button>
                                </div>
                            </div>
                            <div className="de-foot">AI-generated draft — verify before filing</div>
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
            {/* Case selector strip — always visible */}
            {apiCases.length > 0 && (
                <div style={{ flexShrink: 0, padding: "8px 24px", background: t.surface, borderBottom: `1px solid ${t.border}`, display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ fontSize: 12, color: t.textMuted, fontWeight: 600 }}>Case context:</span>
                    <select value={selectedCaseId} onChange={e => setSelectedCaseId(e.target.value)}
                        style={{ height: 32, border: `1px solid ${t.border}`, borderRadius: 8, background: t.inputBg, color: t.text, fontSize: 12, padding: "0 12px", outline: "none", cursor: "pointer", minWidth: 260 }}>
                        <option value="">No case — standalone document</option>
                        {apiCases.map(c => <option key={c.id} value={c.id} style={{ background: t.surface }}>{c.id} — {c.title}</option>)}
                    </select>
                    {activeCaseObj && <span style={{ fontSize: 11, color: t.primary, fontWeight: 600 }}>{activeCaseObj.type} · {activeCaseObj.status}</span>}
                </div>
            )}
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
                <StageEditor tmpl={selectedTemplate} binding={editorBinding} draft={activeDraft} onBack={() => setStage("gallery")} t={t} />
            )}
        </div>
    );
}

export { DocAutomationPage };
