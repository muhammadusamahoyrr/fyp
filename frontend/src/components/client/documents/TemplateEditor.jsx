'use client';
/* Customize a template — a full-screen rich-text editor.
 *
 * WHAT IT EDITS. The reviewed wording of a template lives in its PDF builder
 * on the server; the browser never has it. So the editor opens on an OUTLINE
 * of the template — its heading, purpose and every detail as a [PLACEHOLDER] —
 * which the client writes into freely. It says so on screen. Presenting an
 * outline as "the template's text" would be a fabrication.
 *
 * WHAT IS REAL.
 *   - Formatting (contentEditable + the browser's editing commands).
 *   - Download as Word (.doc, HTML Word opens) and as PDF (the browser's print
 *     dialog, "Save as PDF") — both built from the page, in the browser.
 *   - Save: to THIS BROWSER only (localStorage), and labelled that way. There
 *     is no server store for a client's own template text yet.
 *   - Fill details: values replace their placeholders in the page, and are
 *     carried into the guided template flow by "Use template".
 *
 * Exported HTML is the user's own text, but it is still cleaned (no scripts,
 * no event-handler attributes, no javascript: links) before it leaves the
 * editor, because paste can bring markup from anywhere. */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useT, ThemeCtx } from "../theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import { humanise } from "@/lib/fieldReview.js";
import { Btn, IconBtn, Label, SERIF, PAPER_FONT, fieldStyle, ModalPortal, BACKDROP } from "./ui.jsx";

const STORE_PREFIX = "attorney.templateCopy.";

/* The editor's own light-teal look, in both app themes: a writing surface
 * reads better light, and the dark workspace around it made the whole window
 * feel heavy. Handed down through ThemeCtx so the shared buttons and inputs
 * inside the editor pick it up too. */
export const EDITOR_LIGHT = {
    mode: "light",
    bg: "#eaf7f5", surface: "#f6fcfb", card: "#e3f4f1", cardHi: "#d6efeb",
    border: "#bfe3dd", borderHi: "#9fd3cb", ghostBorder: "#9fd3cb", inputBorder: "#b5ddd6",
    inputBg: "#ffffff", primary: "#139486", primaryGlow: "rgba(19,148,134,0.18)", primaryGlow2: "#d2f0eb",
    text: "#12343a", textDim: "#27525a", textMuted: "#5b7d83", textFaint: "#86a4a9", label: "#0f7f73",
    success: "#1f9d63", warn: "#b07800", danger: "#c8354c", info: "#1d6fa8",
    chipBg: "#e3f4f1", chipBorder: "#bfe3dd", shadowCard: "none",
};

/* One solid colour per action, readable with white text. */
const solid = (bg, border = bg) => ({ background: bg, color: "#ffffff", border: `1px solid ${border}` });
export const ACTION = {
    word: solid("#2b579a"),      // Word blue
    pdf: solid("#c0392b"),       // PDF red
    save: solid("#1f8a5b"),      // save = green
    use: solid("#0f7f73"),       // the main next step = deep teal
    details: solid("#27525a"),   // panel toggle = slate teal
    reset: { background: "#ffffff", color: "#b3261e", border: "1px solid #e8b4b4" },
};

const FileIcon = () => (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" />
    </svg>
);
const FONTS = ["Arial", "Times New Roman", "Georgia", "Calibri", "Garamond", "Courier New"];
const SIZES = [10, 11, 12, 14, 16, 18, 20, 24];

const escapeHtml = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function templateFields(spec) {
    return (spec?.fields || []).filter(f => !(spec.structured_fields || []).includes(f));
}

/* The starting page: an outline, never invented clauses. */
export function outlineHtml(spec) {
    const title = escapeHtml((spec?.label || "Document").toUpperCase());
    const rows = templateFields(spec).map(f => {
        const label = humanise(f);
        return `<p><strong>${escapeHtml(label)}:</strong> <span data-field="${escapeHtml(f)}">[${escapeHtml(label.toUpperCase())}]</span></p>`;
    }).join("");
    return `<h1 style="text-align:center">${title}</h1>`
        + (spec?.description ? `<p><em>${escapeHtml(spec.description)}</em></p>` : "")
        + rows
        + "<p><br></p><p>Write the body of your document here…</p>";
}

/* Remove anything executable before the HTML leaves the editor. */
export function cleanHtml(html) {
    // No parser: never pass markup through unchecked — keep the text only.
    if (typeof DOMParser === "undefined") {
        return escapeHtml(String(html || "").replace(/<(script|style)[\s\S]*?<\/\1>/gi, "").replace(/<[^>]*>/g, ""));
    }
    const doc = new DOMParser().parseFromString(`<div>${html}</div>`, "text/html");
    doc.querySelectorAll("script, style, iframe, frame, object, embed, link, meta, base, form, input, button, textarea, select").forEach(n => n.remove());
    doc.querySelectorAll("*").forEach(el => {
        for (const attr of [...el.attributes]) {
            const name = attr.name.toLowerCase();
            const value = attr.value.replace(/[\u0000- ]+/g, "").toLowerCase();
            if (name.startsWith("on") || name === "srcdoc" || name === "formaction") { el.removeAttribute(attr.name); continue; }
            if (["href", "src", "xlink:href", "action"].includes(name)
                && (/^(javascript|vbscript):/.test(value) || (/^data:/.test(value) && !/^data:image\//.test(value)))) {
                el.removeAttribute(attr.name);
            }
        }
    });
    return doc.body.firstChild ? doc.body.firstChild.innerHTML : "";
}

export function countWords(text) {
    const trimmed = (text || "").trim();
    return { chars: (text || "").length, words: trimmed ? trimmed.split(/\s+/).length : 0 };
}

function readSaved(type) {
    try {
        const raw = window.localStorage.getItem(STORE_PREFIX + type);
        return raw ? JSON.parse(raw) : null;
    } catch { return null; }
}

function exportDoc(title, html) {
    return `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word"><head><meta charset="utf-8"><title>${escapeHtml(title)}</title>`
        + `<style>body{font-family:'Times New Roman',serif;font-size:12pt;line-height:1.6}h1{font-size:16pt}</style></head><body>${cleanHtml(html)}</body></html>`;
}

const I = {
    undo: <path d="M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3" />,
    redo: <path d="M15 14l5-5-5-5M20 9H9a5 5 0 0 0 0 10h3" />,
    alignL: <path d="M4 6h16M4 10h10M4 14h16M4 18h10" />,
    alignC: <path d="M4 6h16M7 10h10M4 14h16M7 18h10" />,
    alignR: <path d="M4 6h16M10 10h10M4 14h16M10 18h10" />,
    alignJ: <path d="M4 6h16M4 10h16M4 14h16M4 18h16" />,
    ul: <><path d="M9 6h11M9 12h11M9 18h11" /><circle cx="4.5" cy="6" r="1" /><circle cx="4.5" cy="12" r="1" /><circle cx="4.5" cy="18" r="1" /></>,
    ol: <path d="M10 6h10M10 12h10M10 18h10M4 5h1v4M4 9h2M4 15h2l-2 3h2" />,
    quote: <path d="M7 7h4v4c0 3-2 5-4 5M15 7h4v4c0 3-2 5-4 5" />,
    link: <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />,
    hr: <path d="M4 12h16" />,
};
const Svg = ({ d }) => <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>;

export default function TemplateEditor(props) {
    const base = useT();
    const t = useMemo(() => ({ ...base, ...EDITOR_LIGHT }), [base]);
    return (
        <ThemeCtx.Provider value={t}>
            <EditorWindow {...props} />
        </ThemeCtx.Provider>
    );
}

function EditorWindow({ spec, onClose, onUse }) {
    const t = useT();
    const toast = useToast();
    const editorRef = useRef(null);
    const rangeRef = useRef(null);
    const closeRef = useRef(null);
    const fields = useMemo(() => templateFields(spec), [spec]);
    const saved = useMemo(() => (typeof window !== "undefined" ? readSaved(spec.template_type) : null), [spec.template_type]);

    const [values, setValues] = useState(saved?.values || {});
    const [counts, setCounts] = useState({ chars: 0, words: 0 });
    const [dirty, setDirty] = useState(false);
    const [savedAt, setSavedAt] = useState(saved?.savedAt || null);
    const [active, setActive] = useState({});
    const [font, setFont] = useState("Arial");
    const [size, setSize] = useState(12);
    const [panelOpen, setPanelOpen] = useState(fields.length > 0);

    const canEdit = typeof document !== "undefined" && typeof document.execCommand === "function";

    const recount = useCallback(() => {
        setCounts(countWords(editorRef.current?.innerText || ""));
    }, []);

    // Load the page once: the saved copy on this device, else the outline.
    useEffect(() => {
        if (!editorRef.current) return;
        editorRef.current.innerHTML = saved?.html ? cleanHtml(saved.html) : outlineHtml(spec);
        recount();
        closeRef.current?.focus();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        const onKey = e => { if (e.key === "Escape") onClose(); };
        document.addEventListener("keydown", onKey);
        return () => document.removeEventListener("keydown", onKey);
    }, [onClose]);

    /* The toolbar steals focus; remember where the cursor was so each command
     * applies to the text the user selected. */
    const remember = () => {
        const sel = typeof window !== "undefined" && window.getSelection ? window.getSelection() : null;
        if (sel && sel.rangeCount && editorRef.current?.contains(sel.anchorNode)) rangeRef.current = sel.getRangeAt(0).cloneRange();
        if (!canEdit || typeof document.queryCommandState !== "function") return;
        const q = c => { try { return document.queryCommandState(c); } catch { return false; } };
        setActive({ bold: q("bold"), italic: q("italic"), underline: q("underline"), strikeThrough: q("strikeThrough"),
            justifyLeft: q("justifyLeft"), justifyCenter: q("justifyCenter"), justifyRight: q("justifyRight"), justifyFull: q("justifyFull"),
            insertUnorderedList: q("insertUnorderedList"), insertOrderedList: q("insertOrderedList") });
    };
    const restore = () => {
        editorRef.current?.focus();
        const sel = window.getSelection?.();
        if (sel && rangeRef.current) { sel.removeAllRanges(); sel.addRange(rangeRef.current); }
    };
    const exec = (cmd, arg = null) => {
        if (!canEdit) return;
        restore();
        try { document.execCommand(cmd, false, arg); } catch { /* unsupported command: no-op */ }
        setDirty(true);
        recount();
        remember();
    };
    const applySize = px => {
        setSize(px);
        exec("fontSize", "7");
        // execCommand only knows sizes 1–7; swap its marker for the real size.
        editorRef.current?.querySelectorAll('font[size="7"]').forEach(el => {
            el.removeAttribute("size");
            el.style.fontSize = `${px}px`;
        });
    };
    const addLink = () => {
        const url = window.prompt("Link address (https://…)", "https://");
        if (!url) return;
        if (!/^(https?:|mailto:)/i.test(url.trim())) { toast.show("Only web (https://) and email (mailto:) links can be added.", "warn", 3500); return; }
        exec("createLink", url.trim());
    };

    const applyDetails = () => {
        let n = 0;
        editorRef.current?.querySelectorAll("[data-field]").forEach(el => {
            const v = (values[el.getAttribute("data-field")] || "").trim();
            if (v) { el.textContent = v; el.style.background = "#e3f6f3"; n++; }
        });
        setDirty(true);
        recount();
        toast.show(n ? `${n} detail${n === 1 ? "" : "s"} filled into the page.` : "Fill a detail first, then apply it.", n ? "success" : "warn", 3000);
    };

    const save = () => {
        const html = cleanHtml(editorRef.current?.innerHTML || "");
        try {
            const at = new Date().toISOString();
            window.localStorage.setItem(STORE_PREFIX + spec.template_type, JSON.stringify({ html, values, savedAt: at }));
            setSavedAt(at);
            setDirty(false);
            toast.show("Saved on this device.", "success", 2500);
        } catch {
            toast.show("Could not save — this browser is not allowing storage.", "danger", 4000);
        }
    };
    const resetToOutline = () => {
        if (!window.confirm("Replace your copy with the original outline? Your changes on this device will be lost.")) return;
        try { window.localStorage.removeItem(STORE_PREFIX + spec.template_type); } catch { /* storage blocked */ }
        editorRef.current.innerHTML = outlineHtml(spec);
        setValues({}); setSavedAt(null); setDirty(false); recount();
    };

    const fileName = (spec.label || "document").replace(/[\\/:*?"<>|]+/g, " ").trim();
    const downloadWord = () => {
        const blob = new Blob(["﻿", exportDoc(spec.label, editorRef.current?.innerHTML || "")], { type: "application/msword" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url; a.download = `${fileName}.doc`;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    const downloadPdf = () => {
        // The browser's own print dialog, where "Save as PDF" is the destination.
        const frame = document.createElement("iframe");
        frame.setAttribute("aria-hidden", "true");
        frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";
        document.body.appendChild(frame);
        const doc = frame.contentDocument;
        doc.open();
        doc.write(exportDoc(spec.label, editorRef.current?.innerHTML || ""));
        doc.close();
        setTimeout(() => {
            try { frame.contentWindow.focus(); frame.contentWindow.print(); }
            finally { setTimeout(() => frame.remove(), 1000); }
        }, 150);
    };

    const tb = on => ({
        minWidth: 36, height: 36, padding: "0 8px", borderRadius: 8, border: `1px solid ${on ? t.primary : "transparent"}`,
        background: on ? t.primaryGlow2 : "transparent", color: on ? t.primary : t.text, cursor: canEdit ? "pointer" : "not-allowed",
        display: "inline-flex", alignItems: "center", justifyContent: "center", fontFamily: "'Inter', sans-serif", fontSize: 14,
    });
    const Tool = ({ label, cmd, arg, on, children, style }) => (
        <button type="button" aria-label={label} title={label} aria-pressed={on || undefined} disabled={!canEdit}
            onMouseDown={e => e.preventDefault()} onClick={() => exec(cmd, arg)} style={{ ...tb(on), ...style }}>{children}</button>
    );
    const sep = <span aria-hidden="true" style={{ width: 1, height: 24, background: t.border, margin: "0 6px" }} />;
    const select = { height: 36, borderRadius: 8, border: `1px solid ${t.inputBorder || t.border}`, background: t.inputBg, color: t.text, padding: "0 10px", fontSize: 13.5, fontFamily: "'Inter', sans-serif", cursor: "pointer" };
    const filled = fields.filter(f => (values[f] || "").trim()).length;

    return (
        <ModalPortal>
        <div data-lenis-prevent data-docs-font onClick={onClose} style={{ ...BACKDROP, background: "rgba(12,40,44,.35)", display: "flex", alignItems: "center", justifyContent: "center", padding: "clamp(6px, 1.5vw, 20px)" }}>
            <div role="dialog" aria-modal="true" aria-label="Customize template" onClick={e => e.stopPropagation()}
                style={{ width: "min(1680px, 100%)", height: "100%", maxHeight: "calc(100vh - 12px)", background: t.surface, border: `1px solid ${t.border}`, borderRadius: 20, display: "flex", flexDirection: "column", overflow: "hidden", boxShadow: "0 30px 80px rgba(8,40,44,.35)" }}>

                {/* Title */}
                <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", padding: "12px 20px", borderBottom: `1px solid ${t.border}` }}>
                    <span style={{ width: 46, height: 46, borderRadius: 12, background: t.primary, color: t.mode === "dark" ? "#0b2a2d" : "#fff", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></svg>
                    </span>
                    <div style={{ flex: 1, minWidth: 220 }}>
                        <div style={{ fontFamily: SERIF, fontSize: 22, fontWeight: 600, color: t.text }}>Edit: {spec.label}</div>
                        <div style={{ fontSize: 12.5, color: t.textMuted }}>
                            Your own copy — the official template is untouched.{" "}
                            {savedAt ? `Saved on this device · ${new Date(savedAt).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}` : "Not saved yet"}
                            {dirty ? " · unsaved changes" : ""}
                        </div>
                    </div>
                    {fields.length > 0 && <Btn onClick={() => setPanelOpen(o => !o)} aria-pressed={panelOpen} style={{ ...ACTION.details, minHeight: 38 }}>{panelOpen ? "Hide details" : `Fill details (${filled}/${fields.length})`}</Btn>}
                    <IconBtn label="Close editor" onClick={onClose} ref={closeRef}>×</IconBtn>
                </div>

                {/* Toolbar */}
                <div role="toolbar" aria-label="Formatting" style={{ display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap", padding: "8px 16px", borderBottom: `1px solid ${t.border}`, background: t.card }}>
                    <Tool label="Undo" cmd="undo"><Svg d={I.undo} /></Tool>
                    <Tool label="Redo" cmd="redo"><Svg d={I.redo} /></Tool>
                    {sep}
                    <label htmlFor="te-font" style={{ position: "absolute", left: -9999 }}>Font</label>
                    <select id="te-font" value={font} disabled={!canEdit} onMouseDown={remember}
                        onChange={e => { setFont(e.target.value); exec("fontName", e.target.value); }} style={{ ...select, width: 150 }}>
                        {FONTS.map(f => <option key={f} value={f}>{f}</option>)}
                    </select>
                    <label htmlFor="te-size" style={{ position: "absolute", left: -9999 }}>Font size</label>
                    <select id="te-size" value={size} disabled={!canEdit} onMouseDown={remember}
                        onChange={e => applySize(Number(e.target.value))} style={{ ...select, width: 72, marginLeft: 6 }}>
                        {SIZES.map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                    {sep}
                    <Tool label="Bold" cmd="bold" on={active.bold} style={{ fontWeight: 800 }}>B</Tool>
                    <Tool label="Italic" cmd="italic" on={active.italic} style={{ fontStyle: "italic", fontFamily: "Georgia, serif" }}>I</Tool>
                    <Tool label="Underline" cmd="underline" on={active.underline} style={{ textDecoration: "underline" }}>U</Tool>
                    <Tool label="Strikethrough" cmd="strikeThrough" on={active.strikeThrough} style={{ textDecoration: "line-through" }}>S</Tool>
                    {sep}
                    <Tool label="Align left" cmd="justifyLeft" on={active.justifyLeft}><Svg d={I.alignL} /></Tool>
                    <Tool label="Align centre" cmd="justifyCenter" on={active.justifyCenter}><Svg d={I.alignC} /></Tool>
                    <Tool label="Align right" cmd="justifyRight" on={active.justifyRight}><Svg d={I.alignR} /></Tool>
                    <Tool label="Justify" cmd="justifyFull" on={active.justifyFull}><Svg d={I.alignJ} /></Tool>
                    {sep}
                    <Tool label="Bulleted list" cmd="insertUnorderedList" on={active.insertUnorderedList}><Svg d={I.ul} /></Tool>
                    <Tool label="Numbered list" cmd="insertOrderedList" on={active.insertOrderedList}><Svg d={I.ol} /></Tool>
                    {sep}
                    <Tool label="Heading 1" cmd="formatBlock" arg="<h1>" style={{ fontWeight: 700 }}>H1</Tool>
                    <Tool label="Heading 2" cmd="formatBlock" arg="<h2>" style={{ fontWeight: 700 }}>H2</Tool>
                    <Tool label="Heading 3" cmd="formatBlock" arg="<h3>" style={{ fontWeight: 700 }}>H3</Tool>
                    <Tool label="Normal text" cmd="formatBlock" arg="<p>" style={{ fontSize: 12.5 }}>¶</Tool>
                    {sep}
                    <Tool label="Quote" cmd="formatBlock" arg="<blockquote>"><Svg d={I.quote} /></Tool>
                    <button type="button" aria-label="Insert link" title="Insert link" disabled={!canEdit} onMouseDown={e => e.preventDefault()} onClick={addLink} style={tb(false)}><Svg d={I.link} /></button>
                    <Tool label="Horizontal line" cmd="insertHorizontalRule"><Svg d={I.hr} /></Tool>
                </div>

                {/* Page + details */}
                <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
                    <div data-lenis-prevent style={{ flex: 1, minWidth: 0, overflowY: "auto", background: t.bg, padding: "clamp(10px, 3vw, 32px)" }}>
                        <div
                            ref={editorRef}
                            contentEditable={canEdit}
                            suppressContentEditableWarning
                            role="textbox"
                            aria-multiline="true"
                            aria-label="Document text"
                            spellCheck
                            onInput={() => { setDirty(true); recount(); }}
                            onKeyUp={remember}
                            onMouseUp={remember}
                            onBlur={remember}
                            className="doc-editor-page"
                            style={{
                                maxWidth: 820, minHeight: "100%", margin: "0 auto", background: "#fff", color: "#1d2a2e",
                                borderRadius: 6, boxShadow: "0 6px 28px rgba(19,90,84,.14)", border: `1px solid ${t.border}`, boxSizing: "border-box",
                                padding: "clamp(24px, 6vw, 72px) clamp(20px, 7vw, 80px)", outline: "none",
                                fontFamily: `Arial, ${PAPER_FONT}`, fontSize: 15, lineHeight: 1.75,
                            }}
                        />
                    </div>

                    {panelOpen && fields.length > 0 && (
                        <aside aria-label="Fill details" style={{ flex: "0 0 320px", borderLeft: `1px solid ${t.border}`, display: "flex", flexDirection: "column", minHeight: 0 }}>
                            <div style={{ padding: "14px 18px", borderBottom: `1px solid ${t.border}` }}>
                                <div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>Fill details</div>
                                <div style={{ fontSize: 12.5, color: t.textMuted }}>{filled} of {fields.length} filled · Apply puts them into the page</div>
                            </div>
                            <div data-lenis-prevent style={{ flex: 1, overflowY: "auto", padding: "12px 18px", display: "flex", flexDirection: "column", gap: 12 }}>
                                <Label>Details</Label>
                                {fields.map(f => (
                                    <div key={f} style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                                        <label htmlFor={`cz_${f}`} style={{ fontSize: 13, color: t.text }}>{humanise(f)}</label>
                                        <input id={`cz_${f}`} value={values[f] || ""}
                                            onChange={e => setValues(v => ({ ...v, [f]: e.target.value }))}
                                            placeholder={`Enter ${humanise(f).toLowerCase()}…`}
                                            style={fieldStyle(t, { borderColor: (values[f] || "").trim() ? t.primary : (t.inputBorder || t.border) })} />
                                    </div>
                                ))}
                            </div>
                            <div style={{ padding: "12px 18px", borderTop: `1px solid ${t.border}` }}>
                                <Btn onClick={applyDetails} style={{ ...ACTION.use, width: "100%" }}>✓ Apply to page</Btn>
                            </div>
                        </aside>
                    )}
                </div>

                {/* Footer — one slim row, so the page gets the height. Each
                    action has its own solid colour: what it does, at a glance. */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", padding: "8px 18px", borderTop: `1px solid ${t.border}`, background: t.card }}>
                    <span style={{ fontSize: 12.5, color: t.textMuted, marginRight: "auto" }}>
                        {counts.chars.toLocaleString()} characters · {counts.words.toLocaleString()} words
                        {!canEdit && " · editing isn't supported in this browser"}
                    </span>
                    {savedAt && <Btn onClick={resetToOutline} style={{ ...ACTION.reset, minHeight: 38 }}>Reset to outline</Btn>}
                    <Btn onClick={downloadWord} style={{ ...ACTION.word, minHeight: 38 }}><FileIcon /> Download as Word</Btn>
                    <Btn onClick={downloadPdf} style={{ ...ACTION.pdf, minHeight: 38 }}><FileIcon /> Download as PDF</Btn>
                    <Btn onClick={save} disabled={!dirty && Boolean(savedAt)} style={{ ...ACTION.save, minHeight: 38 }}>
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 3h11l3 3v13a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2z" /><path d="M8 3v5h7V3M8 21v-7h8v7" /></svg>
                        {dirty || !savedAt ? "Save changes" : "Saved ✓"}
                    </Btn>
                    <Btn onClick={() => onUse(spec, values)} style={{ ...ACTION.use, minHeight: 38 }}>Use template →</Btn>
                </div>
            </div>
        </div>
        </ModalPortal>
    );
}
