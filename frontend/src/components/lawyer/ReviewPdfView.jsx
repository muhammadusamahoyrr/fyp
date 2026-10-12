'use client';
/* The lawyer's review reader (2026-10-11). Chrome's embedded PDF viewer put a
 * grey frame and an "(anonymous)" toolbar around the page that the app cannot
 * style. This draws the same saved revision bytes with PDF.js instead -- every
 * page, one under another -- under a toolbar in the review theme.
 *
 * Lawyer-only on purpose: the client has its own viewer
 * (client/documents/PdfDocumentView.jsx) and the two are not shared. */
import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const ZOOMS = [0.5, 0.67, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2];

export const Icon = ({ d, s = 18, w = 1.8 }) => (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={w}
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
);
export const I = {
    prev: "M15 18l-6-6 6-6",
    next: "M9 18l6-6-6-6",
    minus: "M5 12h14",
    plus: "M12 5v14M5 12h14",
    fit: "M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3",
    print: "M6 9V2h12v7M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2M6 14h12v8H6z",
    file: "M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7ZM14 2v4a2 2 0 0 0 2 2h4M10 13h4M10 17h4",
    tools: "M21 4h-7M10 4H3M21 12h-9M8 12H3M21 20h-5M12 20H3M14 2v4M8 10v4M16 18v4",
    close: "M18 6 6 18M6 6l12 12",
    chev: "m6 9 6 6 6-6",
    pages: "M8 3h10a2 2 0 0 1 2 2v12M4 7h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z",
    search: "M21 21l-4.3-4.3M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Z",
};

export const REVIEW_PDF_CSS = `
[data-review-ws] .rp{display:flex;flex-direction:column;gap:12px;min-width:0}
[data-review-ws] .rp-bar{position:relative;z-index:5;display:flex;align-items:center;gap:2px;padding:6px;border-radius:16px;border:1px solid var(--line);background:var(--surface);box-shadow:0 12px 24px -16px rgba(0,0,0,.8);animation:rp-in .22s ease}
@keyframes rp-in{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
[data-review-ws] .rp-pk{flex:none;display:inline-flex;align-items:center;gap:6px;height:34px;padding:0 8px 0 9px;border-radius:9px;border:1px solid var(--line);background:var(--surface-2);color:var(--ink);font:inherit;font-size:12.5px;font-weight:600;white-space:nowrap;cursor:pointer;transition:border-color .15s}
[data-review-ws] .rp-pk:hover,[data-review-ws] .rp-pk[aria-expanded="true"]{border-color:var(--teal-ink)}
[data-review-ws] .rp-pk > svg:first-child{flex:none;color:var(--muted)}
[data-review-ws] .rp-pk .v{max-width:200px;overflow:hidden;text-overflow:ellipsis;font-variant-numeric:tabular-nums;text-align:left}
[data-review-ws] .rp-pk .chev{display:inline-flex;color:var(--muted);transition:transform .2s}
[data-review-ws] .rp-pk[aria-expanded="true"] .chev{transform:rotate(180deg)}
[data-review-ws] .rp-pk.static{cursor:default}
[data-review-ws] .rp-pk.static:hover{border-color:var(--line)}
[data-review-ws]{position:relative}
[data-review-ws] .rp-drop{position:relative;flex:none}
[data-review-ws] .rp-menu{position:absolute;z-index:70;min-width:150px;max-height:260px;overflow-y:auto;padding:5px;border-radius:12px;border:1px solid var(--line);background:var(--surface);box-shadow:0 18px 36px -14px rgba(0,0,0,.75);scrollbar-width:thin}
[data-review-ws] .rp-menu button{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;padding:7px 10px;border:0;border-radius:8px;background:transparent;color:var(--ink);font:inherit;font-size:13px;text-align:left;cursor:pointer;white-space:nowrap}
[data-review-ws] .rp-menu button:hover{background:var(--hover-tint)}
[data-review-ws] .rp-menu button[aria-selected="true"]{background:color-mix(in srgb,var(--teal-ink) 18%,transparent);color:var(--teal-ink);font-weight:700}
[data-review-ws] .rp-menu .hint{font-size:11px;color:var(--faint);font-weight:500}
[data-review-ws] .rp-b{flex:none;width:34px;height:34px;padding:0;display:grid;place-items:center;border:0;border-radius:9px;background:transparent;color:var(--muted);cursor:pointer;transition:background .15s,color .15s,transform .12s}
[data-review-ws] .rp-b:hover:not(:disabled){background:var(--hover-tint);color:var(--ink)}
[data-review-ws] .rp-b:active:not(:disabled){transform:scale(.92)}
[data-review-ws] .rp-b:disabled{opacity:.4;cursor:not-allowed}
[data-review-ws] .rp-sep{flex:none;width:1px;height:22px;margin:0 5px;background:var(--line)}
[data-review-ws] .rp-gap{flex:1 1 0;min-width:4px}
/* A narrow column (the review screen, beside the decision panel): the label
   gives way first, then Print keeps only its icon, then the label goes. */
[data-review-ws] .rp-bar{min-width:0;container-type:inline-size}
[data-review-ws] .rp-pk.static{flex:0 1 auto;min-width:0}
[data-review-ws] .rp-pk.static .v{max-width:none;min-width:0}
@container (max-width:760px){[data-review-ws] .rp-bar .rp-act .t{display:none}[data-review-ws] .rp-bar .rp-act{width:34px;padding:0;justify-content:center}}
[data-review-ws] .rp-act svg,[data-review-ws] .rp-b svg{flex:none}
@container (max-width:560px){[data-review-ws] .rp-pk.static,[data-review-ws] .rp-sep.first{display:none}}
[data-review-ws] .rp-act{flex:none;display:inline-flex;align-items:center;gap:7px;height:34px;padding:0 13px 0 11px;border-radius:9px;border:1px solid var(--line);background:var(--surface-2);color:var(--ink);font:inherit;font-size:13px;font-weight:600;cursor:pointer;transition:border-color .15s}
[data-review-ws] .rp-act:hover:not(:disabled){border-color:var(--teal-ink)}
[data-review-ws] .rp-act:disabled{opacity:.4;cursor:not-allowed}
[data-review-ws] .rp-card{position:relative;overflow:hidden;border-radius:16px;border:1px solid var(--line);background:color-mix(in srgb,var(--surface-2) 55%,transparent)}
[data-review-ws] .rw-btn.rp-on{border-color:transparent;background:var(--brand-soft);color:var(--brand-text)}
[data-review-ws] .rp-scroll{height:max(540px,calc(100vh - 230px));overflow:auto;padding:10px 8px 16px 10px}
/* A slim scrollbar: 6px, a soft thumb, no track. */
[data-review-ws] .rp-scroll::-webkit-scrollbar{width:6px;height:6px}
[data-review-ws] .rp-scroll::-webkit-scrollbar-track{background:transparent}
[data-review-ws] .rp-scroll::-webkit-scrollbar-thumb{border-radius:6px;background:color-mix(in srgb,var(--ink) 22%,transparent)}
[data-review-ws] .rp-scroll::-webkit-scrollbar-thumb:hover{background:color-mix(in srgb,var(--ink) 38%,transparent)}
@supports not selector(::-webkit-scrollbar){[data-review-ws] .rp-scroll{scrollbar-width:thin;scrollbar-color:color-mix(in srgb,var(--ink) 25%,transparent) transparent}}
[data-review-ws] .rp-pages{display:flex;flex-direction:column;align-items:center;gap:12px;min-width:min-content}
[data-review-ws] .rp-pages canvas{display:block;flex:none;background:#fff;border-radius:8px;box-shadow:0 10px 24px -14px rgba(0,0,0,.6)}
[data-review-ws] .rp-msg{min-height:420px;display:grid;place-items:center;color:var(--muted);font-size:13.5px;text-align:center;padding:0 20px}
`;

/* A value with a chevron; its menu opens beneath. `keepFocus` leaves the
 * caret where it was -- for the editor, whose selection a click would lose. */
export function Picker({ label, icon, shown, value, options, onPick, keepFocus = false, width }) {
    const hold = keepFocus ? { onMouseDown: e => e.preventDefault() } : {};
    const [open, setOpen] = useState(false);
    const [at, setAt] = useState(null);
    const boxRef = useRef(null);
    const menuRef = useRef(null);
    // THE MENU IS DRAWN AT THE SCREEN'S ROOT, not inside the bar: the editor's
    // bar scrolls sideways, and a scrolling box clips whatever overflows it --
    // a menu inside it would be cut off at the bar's bottom edge.
    const toggle = () => {
        if (open) { setOpen(false); return; }
        const root = boxRef.current?.closest("[data-review-ws]");
        if (!root) return;
        const b = boxRef.current.getBoundingClientRect(), r = root.getBoundingClientRect();
        setAt({ root, top: b.bottom - r.top + root.scrollTop + 6, left: b.left - r.left + root.scrollLeft });
        setOpen(true);
    };
    useEffect(() => {
        if (!open) return undefined;
        const inside = t => boxRef.current?.contains(t) || menuRef.current?.contains(t);
        const onDown = e => { if (!inside(e.target)) setOpen(false); };
        const onKey = e => { if (e.key === "Escape") setOpen(false); };
        // Anything scrolling under it would leave it pointing at nothing.
        const onScroll = e => { if (!menuRef.current?.contains(e.target)) setOpen(false); };
        const onResize = () => setOpen(false);
        document.addEventListener("mousedown", onDown);
        window.addEventListener("keydown", onKey);
        window.addEventListener("scroll", onScroll, true);
        window.addEventListener("resize", onResize);
        return () => {
            document.removeEventListener("mousedown", onDown); window.removeEventListener("keydown", onKey);
            window.removeEventListener("scroll", onScroll, true); window.removeEventListener("resize", onResize);
        };
    }, [open]);
    return (
        <div className="rp-drop" ref={boxRef}>
            <button type="button" className="rp-pk" aria-haspopup="listbox" aria-expanded={open}
                aria-label={label} title={label} onClick={toggle} {...hold}>
                <Icon d={icon} s={15} /><span className="v" style={width ? { width, display: "inline-block" } : undefined}>{shown}</span>
                <span className="chev"><Icon d={I.chev} s={14} w={2} /></span>
            </button>
            {open && at && createPortal(
                <div className="rp-menu" role="listbox" aria-label={label} ref={menuRef}
                    style={{ top: at.top, left: at.left }}>
                    {options.map(o => (
                        <button key={o.value} type="button" role="option" aria-selected={o.value === value}
                            onClick={() => { onPick(o.value); setOpen(false); }} {...hold} style={o.style}>
                            {o.label}{o.hint && <span className="hint">{o.hint}</span>}
                        </button>
                    ))}
                </div>, at.root)}
        </div>
    );
}

/* The header's button for the view tools: icon only, lit while open. It
 * lives with the other header actions, so it takes no row of its own. */
export function ViewToolsButton({ on, onToggle }) {
    return (
        <button type="button" className={`rw-btn rw-icon-btn${on ? " rp-on" : ""}`} onClick={onToggle}
            aria-pressed={on} aria-label={on ? "Hide view tools" : "View tools"}
            title={on ? "Hide view tools" : "View tools: page, zoom and print"}>
            <Icon d={I.tools} s={17} />
        </button>
    );
}

export default function ReviewPdfView({ url, label, notice = null, tools = false, onTools = () => {} }) {
    const scrollRef = useRef(null);
    const canvasRefs = useRef([]);
    const [width, setWidth] = useState(0);
    const [pdf, setPdf] = useState(null);
    const [zoom, setZoom] = useState(1);
    const [page, setPage] = useState(1);
    const [message, setMessage] = useState("Loading the document…");
    const [pageText, setPageText] = useState("");

    // The page width follows the reading area.
    useEffect(() => {
        const host = scrollRef.current;
        if (!host) return undefined;
        const measure = () => setWidth(Math.max(0, Math.floor(host.clientWidth - 24)));  // the frame's padding and the slim bar
        measure();
        if (typeof ResizeObserver === "undefined") {
            window.addEventListener("resize", measure);
            return () => window.removeEventListener("resize", measure);
        }
        const ro = new ResizeObserver(measure);
        ro.observe(host);
        return () => ro.disconnect();
    }, []);

    useEffect(() => {
        let cancelled = false, task = null, proxy = null;
        setPdf(null); setPage(1); setZoom(1); setPageText("");
        setMessage("Loading the document…");
        if (url) {
            // Client-only import; the worker comes from the installed package.
            import("pdfjs-dist/webpack.mjs").then(pdfjs => {
                if (cancelled) return null;
                task = pdfjs.getDocument({ url });
                return task.promise;
            }).then(loaded => {
                if (!loaded) return;
                proxy = loaded;
                if (cancelled) { loaded.destroy(); return; }
                setPdf(loaded);
            }).catch(() => {
                if (!cancelled) setMessage("This PDF could not be displayed. Use Download to open the saved copy.");
            });
        }
        return () => {
            cancelled = true;
            if (task) task.destroy(); else if (proxy) proxy.destroy();
        };
    }, [url]);

    // Draw every page at the reading width times the zoom.
    useEffect(() => {
        if (!pdf || !width) return undefined;
        let cancelled = false;
        const tasks = [];
        (async () => {
            try {
                const texts = [];
                for (let n = 1; n <= pdf.numPages; n++) {
                    const p = await pdf.getPage(n);
                    if (cancelled) return;
                    const natural = p.getViewport({ scale: 1 });
                    const fit = Math.min(width, 1120) / natural.width;
                    const viewport = p.getViewport({ scale: fit * zoom });
                    const canvas = canvasRefs.current[n - 1];
                    const ctx = canvas?.getContext("2d");
                    if (!canvas || !ctx) continue;
                    const ratio = Math.min(window.devicePixelRatio || 1, 2);
                    canvas.width = Math.floor(viewport.width * ratio);
                    canvas.height = Math.floor(viewport.height * ratio);
                    canvas.style.width = `${viewport.width}px`;
                    canvas.style.height = `${viewport.height}px`;
                    const t = p.render({
                        canvasContext: ctx, viewport,
                        transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
                    });
                    tasks.push(t);
                    await t.promise;
                    try { texts.push((await p.getTextContent()).items.map(i => i.str || "").join(" ")); } catch { /* visual only */ }
                }
                if (!cancelled) { setMessage(null); setPageText(texts.join("\n")); }
            } catch (err) {
                if (!cancelled && err?.name !== "RenderingCancelledException") {
                    setMessage("This PDF could not be displayed. Use Download to open the saved copy.");
                }
            }
        })();
        return () => { cancelled = true; tasks.forEach(t => t.cancel()); };
    }, [pdf, width, zoom]);

    // Which page is in view, for the counter.
    const onScroll = () => {
        const host = scrollRef.current;
        if (!host) return;
        const mid = host.scrollTop + host.clientHeight / 3;
        let current = 1;
        canvasRefs.current.forEach((c, i) => { if (c && c.offsetTop <= mid) current = i + 1; });
        setPage(current);
    };
    const goTo = n => {
        const c = canvasRefs.current[n - 1];
        if (c && scrollRef.current) scrollRef.current.scrollTo({ top: c.offsetTop - 22, behavior: "smooth" });
    };
    const step = dir => {
        const i = ZOOMS.findIndex(z => z >= zoom - 0.001);
        setZoom(ZOOMS[clamp((i < 0 ? 4 : i) + dir, 0, ZOOMS.length - 1)]);
    };
    // Print the saved bytes, not this page.
    const print = () => {
        if (!url) return;
        const f = document.createElement("iframe");
        f.style.cssText = "position:fixed;width:0;height:0;border:0;right:0;bottom:0";
        f.src = url;
        f.onload = () => { try { f.contentWindow.focus(); f.contentWindow.print(); } catch { window.open(url, "_blank", "noopener"); } setTimeout(() => f.remove(), 60000); };
        document.body.appendChild(f);
    };

    const pages = pdf?.numPages || 0;
    return (
        <section className="rp" aria-label="PDF document pages">
            {tools && <div className="rp-bar" role="toolbar" aria-label="Document controls">
                <span className="rp-pk static" title={typeof label === "string" ? label : undefined}>
                    <Icon d={I.file} s={15} /><span className="v">{label}</span>
                </span>
                <span className="rp-sep first" aria-hidden="true" />
                <button type="button" className="rp-b" aria-label="Previous page" title="Previous page" disabled={page <= 1} onClick={() => goTo(page - 1)}><Icon d={I.prev} /></button>
                <Picker label="Go to page" icon={I.pages} value={page} shown={pages ? `${page} / ${pages}` : "– / –"}
                    options={Array.from({ length: pages }, (_, i) => ({ value: i + 1, label: `Page ${i + 1}` }))}
                    onPick={goTo} />
                <button type="button" className="rp-b" aria-label="Next page" title="Next page" disabled={!pages || page >= pages} onClick={() => goTo(page + 1)}><Icon d={I.next} /></button>
                <span className="rp-sep" aria-hidden="true" />
                <button type="button" className="rp-b" aria-label="Zoom out" title="Zoom out" disabled={zoom <= ZOOMS[0]} onClick={() => step(-1)}><Icon d={I.minus} /></button>
                <Picker label="Zoom" icon={I.search} value={zoom} shown={`${Math.round(zoom * 100)}%`}
                    options={ZOOMS.map(z => ({ value: z, label: `${Math.round(z * 100)}%`, hint: z === 1 ? "Fit width" : null }))}
                    onPick={setZoom} />
                <button type="button" className="rp-b" aria-label="Zoom in" title="Zoom in" disabled={zoom >= ZOOMS[ZOOMS.length - 1]} onClick={() => step(1)}><Icon d={I.plus} /></button>
                <span className="rp-sep" aria-hidden="true" />
                <button type="button" className="rp-b" aria-label="Fit to width" title="Fit to width" onClick={() => setZoom(1)}><Icon d={I.fit} /></button>
                <span className="rp-gap" />
                <button type="button" className="rp-act" disabled={!url} onClick={print} title="Print the saved PDF" aria-label="Print">
                    <Icon d={I.print} s={16} /><span className="t">Print</span>
                </button>
                <button type="button" className="rp-b" aria-label="Hide view tools" title="Hide" onClick={() => onTools(false)}><Icon d={I.close} /></button>
            </div>}
            <div className="rp-card">
            {notice}
            <div className="rp-scroll" ref={scrollRef} onScroll={onScroll}>
                {message && <div className="rp-msg" role="status">{message}</div>}
                <div className="rp-pages" style={message ? { display: "none" } : undefined}>
                    {Array.from({ length: pages }, (_, i) => (
                        <canvas key={i} ref={el => { canvasRefs.current[i] = el; }} role="img"
                            aria-label={`PDF page ${i + 1} of ${pages}`} />
                    ))}
                </div>
            </div>
            </div>
            {pageText && <div style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)", whiteSpace: "nowrap" }}>{pageText}</div>}
        </section>
    );
}
