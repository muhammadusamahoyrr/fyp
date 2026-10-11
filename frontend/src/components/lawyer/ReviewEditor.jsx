'use client';
/* The reviewing lawyer's editor (2026-10-11): the submitted wording on a page,
 * editable, under a toolbar in the agreement editor's look.
 *
 * What the lawyer writes here is sent back to the client as a PROPOSAL (see
 * returnWithEditsV2): it never becomes an approval by itself.
 *
 * FORMATTING IS TAG-BASED (<b>, <font face/size>, align) rather than inline CSS:
 * the server cleans this HTML against an allowlist that keeps those tags and
 * only `text-align` of any style -- a colour or a CSS size would be removed on
 * save, so the bar offers no control whose result would be thrown away. */
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Icon, Picker } from "./ReviewPdfView.jsx";

const P = {
    undo: "M9 14 4 9l5-5M4 9h10.5a5.5 5.5 0 0 1 0 11H11",
    redo: "m15 14 5-5-5-5M20 9H9.5a5.5 5.5 0 0 0 0 11H13",
    type: "M4 7V4h16v3M9 20h6M12 4v16",
    size: "M21 14h-5M16 16v-3.5a2.5 2.5 0 0 1 5 0V16M4.5 13h6M3 16l4.5-9 4.5 9",
    bold: "M6 12h9a4 4 0 0 1 0 8H7a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h7a4 4 0 0 1 0 8",
    italic: "M19 4h-9M14 20H5M15 4 9 20",
    underline: "M6 4v6a6 6 0 0 0 12 0V4M4 20h16",
    strike: "M16 4H9a3 3 0 0 0-2.83 4M14 12a4 4 0 0 1 0 8H6M4 12h16",
    sub: "m4 5 8 8M12 5l-8 8M20 19h-4c0-1.5.44-2 1.5-2.5S20 15.33 20 14c0-.47-.17-.93-.48-1.29a2.11 2.11 0 0 0-2.62-.44c-.42.24-.74.62-.9 1.07",
    sup: "m4 19 8-8M12 19l-8-8M20 12h-4c0-1.5.44-2 1.5-2.5S20 8.33 20 7c0-.47-.17-.93-.48-1.29a2.11 2.11 0 0 0-2.62-.44c-.42.24-.74.62-.9 1.07",
    left: "M15 12H3M17 18H3M21 6H3",
    center: "M17 12H7M19 18H5M21 6H3",
    right: "M21 12H9M21 18H7M21 6H3",
    justify: "M3 12h18M3 18h18M3 6h18",
    ul: "M3 12h.01M3 18h.01M3 6h.01M8 12h13M8 18h13M8 6h13",
    ol: "M10 12h11M10 18h11M10 6h11M4 10h2M4 6h1v4M6 18H4c0-1 2-2 2-3s-1-1.5-2-1",
    h1: "M4 12h8M4 18V6M12 18V6M17 12l3-2v8",
    h2: "M4 12h8M4 18V6M12 18V6M21 18h-4c0-4 4-3 4-6 0-1.5-2-2.5-4-1",
    h3: "M4 12h8M4 18V6M12 18V6M17.5 10.5c1.7-1 3.5 0 3.5 1.5a2 2 0 0 1-2 2M17 17.5c2 1.5 4 .3 4-1.5a2 2 0 0 0-2-2",
    quote: "M16 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2zM5 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z",
    clear: "M4 7V4h16v3M5 20h6M13 4 8 20M15 15l5 5M20 15l-5 5",
};

const FONTS = ["Georgia", "Times New Roman", "Garamond", "Book Antiqua", "Arial", "Helvetica", "Verdana", "Tahoma", "Calibri", "Courier New"];
// <font size> takes 1-7; shown as the pixel size each one renders at.
const SIZES = [["1", "10"], ["2", "13"], ["3", "16"], ["4", "18"], ["5", "24"], ["6", "32"], ["7", "48"]];

export const REVIEW_EDITOR_CSS = `
[data-review-ws] .re-paper{max-width:1120px;min-height:100%;margin:0 auto;padding:48px 60px 64px;border-radius:8px;background:#fff;color:#1c1e22;font:15px/1.7 Georgia,"Times New Roman",serif;outline:none;box-shadow:0 10px 24px -14px rgba(0,0,0,.6);caret-color:#0f6e7a}
[data-review-ws] .re-paper:focus{box-shadow:0 0 0 2px color-mix(in srgb,var(--teal-ink) 55%,transparent),0 10px 24px -14px rgba(0,0,0,.6)}
[data-review-ws] .re-paper h1{font-size:1.5em;margin:.4em 0}
[data-review-ws] .re-paper h2{font-size:1.25em;margin:.5em 0}
[data-review-ws] .re-paper h3{font-size:1.1em;margin:.5em 0}
[data-review-ws] .re-paper p{margin:0 0 .7em}
[data-review-ws] .re-paper blockquote{margin:.6em 0;padding-left:14px;border-left:3px solid #c9d3d6;color:#3a4245}
[data-review-ws] .re-paper table{border-collapse:collapse;margin:.6em 0}
[data-review-ws] .re-paper td,[data-review-ws] .re-paper th{border:1px solid #cfd6d8;padding:4px 8px}
[data-review-ws] .rp-b[aria-pressed="true"]{background:#3fd0e0;color:#062a30}
/* One row that scrolls sideways when the column is narrow, with no visible
   scrollbar -- as the agreement editor's bar does. */
[data-review-ws] .re-scroll{flex:1;min-width:0;display:flex;align-items:center;gap:2px;overflow-x:auto;overflow-y:hidden;scrollbar-width:none;padding:1px}
[data-review-ws] .re-scroll::-webkit-scrollbar{display:none}
[data-review-ws] .re-scroll > *{flex:none}
[data-review-ws] .re-banner{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--line);font-size:13px;color:var(--gold);background:color-mix(in srgb,var(--gold) 9%,transparent)}
`;

export default function ReviewEditor({ html, editorRef, onDirty }) {
    const ref = useRef(null);
    const [on, setOn] = useState({});
    // The page's content is written ONCE, here, and never by React's render.
    // Rendered as dangerouslySetInnerHTML it was written again on re-renders
    // (every keystroke marks the edit dirty, which re-renders), and whatever
    // the lawyer had typed vanished. `html` is the server's: cleaned by nh3
    // against the draft allowlist (no scripts, handlers, or any style but
    // text-align) before it is sent, so it is safe to place into the page.
    const [initial] = useState(html);
    useLayoutEffect(() => {
        if (ref.current) ref.current.innerHTML = initial;
    }, [initial]);

    useEffect(() => {
        if (editorRef) editorRef.current = ref.current;
        try { document.execCommand("styleWithCSS", false, false); } catch { /* not supported */ }
    }, [editorRef]);

    // What the caret sits in, for the pressed buttons and the pickers.
    useEffect(() => {
        const read = () => {
            const sel = document.getSelection();
            if (!sel || !ref.current || !ref.current.contains(sel.anchorNode)) return;
            const q = c => { try { return document.queryCommandState(c); } catch { return false; } };
            const v = c => { try { return document.queryCommandValue(c); } catch { return ""; } };
            setOn({
                bold: q("bold"), italic: q("italic"), underline: q("underline"), strikeThrough: q("strikeThrough"),
                subscript: q("subscript"), superscript: q("superscript"),
                justifyLeft: q("justifyLeft"), justifyCenter: q("justifyCenter"),
                justifyRight: q("justifyRight"), justifyFull: q("justifyFull"),
                insertUnorderedList: q("insertUnorderedList"), insertOrderedList: q("insertOrderedList"),
                block: String(v("formatBlock") || "").toLowerCase(),
                font: String(v("fontName") || "").replace(/["']/g, ""),
                size: String(v("fontSize") || ""),
            });
        };
        document.addEventListener("selectionchange", read);
        return () => document.removeEventListener("selectionchange", read);
    }, []);

    const run = (cmd, val = null) => {
        ref.current?.focus();
        try { document.execCommand(cmd, false, val); } catch { /* unsupported command */ }
        onDirty?.();
    };
    const block = tag => run("formatBlock", on.block === tag ? "<p>" : `<${tag}>`);
    const btn = (label, d, onClick, pressed) => (
        <button type="button" className="rp-b" title={label} aria-label={label}
            aria-pressed={pressed === undefined ? undefined : Boolean(pressed)}
            onMouseDown={e => e.preventDefault()} onClick={onClick}>
            <Icon d={d} />
        </button>
    );
    const sep = <span className="rp-sep" aria-hidden="true" />;
    const sizeShown = (SIZES.find(([v]) => v === on.size) || SIZES[2])[1];

    return (
        <section className="rp re" aria-label="Edit the document">
            <div className="rp-bar">
            {/* A mouse wheel moves it along: a plain wheel has no sideways axis. */}
            <div className="re-scroll" role="toolbar" aria-label="Text formatting"
                onWheel={e => {
                    const el = e.currentTarget;
                    if (el.scrollWidth > el.clientWidth && Math.abs(e.deltaY) > Math.abs(e.deltaX)) el.scrollLeft += e.deltaY;
                }}>
                {btn("Undo", P.undo, () => run("undo"))}
                {btn("Redo", P.redo, () => run("redo"))}
                {sep}
                <Picker label="Font" icon={P.type} keepFocus width={92}
                    value={on.font} shown={on.font || "Georgia"}
                    options={FONTS.map(f => ({ value: f, label: f, style: { fontFamily: f } }))}
                    onPick={f => run("fontName", f)} />
                <Picker label="Text size" icon={P.size} keepFocus width={20}
                    value={on.size || "3"} shown={sizeShown}
                    options={SIZES.map(([v, px]) => ({ value: v, label: px, hint: v === "3" ? "Normal" : null }))}
                    onPick={v => run("fontSize", v)} />
                {sep}
                {btn("Bold", P.bold, () => run("bold"), on.bold)}
                {btn("Italic", P.italic, () => run("italic"), on.italic)}
                {btn("Underline", P.underline, () => run("underline"), on.underline)}
                {btn("Strikethrough", P.strike, () => run("strikeThrough"), on.strikeThrough)}
                {btn("Subscript", P.sub, () => run("subscript"), on.subscript)}
                {btn("Superscript", P.sup, () => run("superscript"), on.superscript)}
                {sep}
                {btn("Align left", P.left, () => run("justifyLeft"), on.justifyLeft)}
                {btn("Align centre", P.center, () => run("justifyCenter"), on.justifyCenter)}
                {btn("Align right", P.right, () => run("justifyRight"), on.justifyRight)}
                {btn("Justify", P.justify, () => run("justifyFull"), on.justifyFull)}
                {sep}
                {btn("Bulleted list", P.ul, () => run("insertUnorderedList"), on.insertUnorderedList)}
                {btn("Numbered list", P.ol, () => run("insertOrderedList"), on.insertOrderedList)}
                {sep}
                {btn("Heading 1", P.h1, () => block("h1"), on.block === "h1")}
                {btn("Heading 2", P.h2, () => block("h2"), on.block === "h2")}
                {btn("Heading 3", P.h3, () => block("h3"), on.block === "h3")}
                {btn("Quote", P.quote, () => block("blockquote"), on.block === "blockquote")}
                {sep}
                {btn("Clear formatting", P.clear, () => run("removeFormat"))}
            </div>
            </div>
            <div className="rp-card">
                <div className="re-banner">
                    You are editing the client's wording. It goes back to them as your proposal —
                    they send it again if they accept it.
                </div>
                <div className="rp-scroll">
                    <div ref={ref} className="re-paper" contentEditable suppressContentEditableWarning
                        role="textbox" aria-multiline="true" aria-label="Document text" spellCheck
                        onInput={() => onDirty?.()} />
                </div>
            </div>
        </section>
    );
}
