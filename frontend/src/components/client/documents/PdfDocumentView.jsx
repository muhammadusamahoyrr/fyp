'use client';
/* Render the saved PDF itself, not the browser's embedded PDF viewer.  Chrome's
 * iframe viewer adds an unstyleable grey frame/toolbar around the white page.
 * PDF.js keeps the real revision bytes and lets this workspace show only the
 * page plus a small, functional page/zoom control. */
import React, { useEffect, useRef, useState } from "react";

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

export default function PdfDocumentView({ url, t }) {
    const hostRef = useRef(null);
    const canvasRef = useRef(null);
    const [width, setWidth] = useState(0);
    const [pdf, setPdf] = useState(null);
    const [pageNumber, setPageNumber] = useState(1);
    const [zoom, setZoom] = useState(1);
    const [message, setMessage] = useState("Loading PDF…");
    const [pageText, setPageText] = useState("");

    useEffect(() => {
        const host = hostRef.current;
        if (!host) return;
        const measure = () => setWidth(Math.max(0, Math.floor(host.clientWidth)));
        measure();
        if (typeof ResizeObserver === "undefined") {
            window.addEventListener("resize", measure);
            return () => window.removeEventListener("resize", measure);
        }
        const observer = new ResizeObserver(measure);
        observer.observe(host);
        return () => observer.disconnect();
    }, []);

    useEffect(() => {
        let cancelled = false;
        let task = null;
        let documentProxy = null;
        setPdf(null);
        setPageNumber(1);
        setZoom(1);
        setMessage("Loading PDF…");
        setPageText("");
        if (url) {
            // This import stays client-only; pdfjs-dist/webpack.mjs supplies its
            // matching worker from the installed package, not a remote CDN.
            import("pdfjs-dist/webpack.mjs").then(pdfjs => {
                if (cancelled) return null;
                task = pdfjs.getDocument({ url });
                return task.promise;
            }).then(loaded => {
                if (!loaded) return;
                documentProxy = loaded;
                if (cancelled) { loaded.destroy(); return; }
                setPdf(loaded);
                setMessage("Rendering page…");
            }).catch(() => {
                if (!cancelled) setMessage("This PDF could not be displayed. Use Export PDF to download the saved version.");
            });
        }
        return () => {
            cancelled = true;
            if (task) task.destroy();
            else if (documentProxy) documentProxy.destroy();
        };
    }, [url]);

    useEffect(() => {
        if (!pdf || !width || !canvasRef.current) return;
        let cancelled = false;
        let renderTask = null;
        setMessage("Rendering page…");
        setPageText("");
        (async () => {
            try {
                const page = await pdf.getPage(pageNumber);
                if (cancelled) return;
                const natural = page.getViewport({ scale: 1 });
                const viewport = page.getViewport({ scale: ((width - 4) / natural.width) * zoom });
                const canvas = canvasRef.current;
                const context = canvas?.getContext("2d");
                if (!canvas || !context) throw new Error("Canvas is unavailable");
                const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
                canvas.width = Math.floor(viewport.width * pixelRatio);
                canvas.height = Math.floor(viewport.height * pixelRatio);
                canvas.style.width = `${viewport.width}px`;
                canvas.style.height = `${viewport.height}px`;
                renderTask = page.render({
                    canvasContext: context, viewport,
                    transform: pixelRatio === 1 ? undefined : [pixelRatio, 0, 0, pixelRatio, 0, 0],
                });
                await renderTask.promise;
                if (!cancelled) {
                    // Canvas is visual; keep the actual page text available to
                    // screen readers. Export PDF remains the selectable copy.
                    try {
                        const text = await page.getTextContent();
                        if (!cancelled) setPageText(text.items.map(item => item.str || "").join(" "));
                    } catch { /* The rendered PDF is still readable visually. */ }
                    if (!cancelled) setMessage(null);
                }
            } catch (error) {
                if (!cancelled && error?.name !== "RenderingCancelledException") {
                    setMessage("This PDF page could not be displayed. Use Export PDF to download it.");
                }
            }
        })();
        return () => { cancelled = true; renderTask?.cancel(); };
    }, [pdf, pageNumber, zoom, width]);

    const button = disabled => ({
        width: 32, height: 32, border: 0, borderRadius: 7, background: "transparent",
        color: disabled ? t.textMuted : t.text, cursor: disabled ? "default" : "pointer", fontSize: 19,
    });
    const pages = pdf?.numPages || 0;
    return <section ref={hostRef} aria-label="PDF document pages" style={{ width: "min(900px,100%)", display: "flex", flexDirection: "column", alignItems: "center" }}>
        {pages > 0 && <div role="toolbar" aria-label="PDF page controls" style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6, maxWidth: "100%", marginBottom: 12, padding: "4px 10px", borderRadius: 10, background: t.card, color: t.text, fontSize: 13 }}>
            <button type="button" aria-label="Zoom out" disabled={zoom <= 0.5} onClick={() => setZoom(z => clamp(Number((z - 0.1).toFixed(1)), 0.5, 2))} style={button(zoom <= 0.5)}>−</button>
            <span style={{ minWidth: 44, textAlign: "center" }}>{Math.round(zoom * 100)}%</span>
            <button type="button" aria-label="Zoom in" disabled={zoom >= 2} onClick={() => setZoom(z => clamp(Number((z + 0.1).toFixed(1)), 0.5, 2))} style={button(zoom >= 2)}>+</button>
            <span aria-hidden="true" style={{ width: 1, height: 22, background: t.border, margin: "0 5px" }} />
            <button type="button" aria-label="Previous page" disabled={pageNumber <= 1} onClick={() => setPageNumber(n => n - 1)} style={button(pageNumber <= 1)}>‹</button>
            <span aria-live="polite" style={{ minWidth: 54, textAlign: "center" }}>{pageNumber} / {pages}</span>
            <button type="button" aria-label="Next page" disabled={pageNumber >= pages} onClick={() => setPageNumber(n => n + 1)} style={button(pageNumber >= pages)}>›</button>
        </div>}
        {message && <div role="status" style={{ padding: 18, color: t.textMuted, textAlign: "center", fontSize: 13 }}>{message}</div>}
        <div style={{ width: "100%", overflowX: "auto", display: "flex", justifyContent: zoom > 1 ? "flex-start" : "center" }}>
            <canvas ref={canvasRef} role="img" aria-label={`PDF page ${pageNumber}${pages ? ` of ${pages}` : ""}`}
                style={{ display: pages && !message ? "block" : "none", flexShrink: 0, maxWidth: "none", background: "#fff", borderRadius: 5, boxShadow: "0 8px 24px rgba(0,0,0,0.14)" }} />
        </div>
        {pageText && <div style={{ position: "absolute", width: 1, height: 1, padding: 0, margin: -1, overflow: "hidden", clip: "rect(0,0,0,0)", whiteSpace: "nowrap", border: 0 }}>{pageText}</div>}
    </section>;
}
