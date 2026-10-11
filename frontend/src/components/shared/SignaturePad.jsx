'use client';
/* The three ways to sign: draw, type, upload.
 *
 * EXTRACTED so every signing surface offers the same three. The agreement
 * BUILDER had all three from the start, while everyone asked to counter-sign --
 * the client in the detail modal, the lawyer on their own page, and an invited
 * signer on /sign -- was given a single "type your name" box. The backend
 * accepted `canvas`, `typed` and `image_upload` on both signing paths the whole
 * time; only the UI was narrower, and only for the people receiving an
 * agreement rather than sending one.
 *
 * It reports `{ method, data }` using the server's own method names, so a caller
 * passes them straight through and there is no mapping table to drift.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useT } from "@/components/shared/ui/theme.js";

/* WHAT THE SERVER WILL ACTUALLY TAKE.
 *
 * `signature_data` is capped at 200,000 characters (schemas/agreement.py
 * `_MAX_SIGNATURE`). Base64 costs 4 bytes per 3, plus the data-URL prefix, so
 * the real ceiling on an uploaded image is about 146 KB.
 *
 * The old drop zone said "Max 2MB". Anything near that was rejected by the
 * server with a 422 the user had no way to interpret, after they had already
 * chosen the file. Checking here means the limit is enforced where it can be
 * explained. */
const MAX_SIGNATURE_CHARS = 200_000;
const MAX_IMAGE_BYTES = Math.floor((MAX_SIGNATURE_CHARS - 64) * 3 / 4);
const MAX_IMAGE_LABEL = `${Math.floor(MAX_IMAGE_BYTES / 1024)} KB`;

/* Line icons (Lucide, ISC licence) in place of the emoji that stood here --
 * a ✍️ rendered at low opacity on the canvas read as a squiggle, not a hand. */
const PATHS = {
    draw: ["M12 20h9", "M16.38 3.62a1 1 0 0 1 3 3L7.37 18.64a2 2 0 0 1-.86.5l-2.87.84a.5.5 0 0 1-.62-.62l.84-2.87a2 2 0 0 1 .5-.86z"],
    type: ["M12 4v16", "M4 7V5a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v2", "M9 20h6"],
    upload: ["M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4", "M17 8l-5-5-5 5", "M12 3v12"],
    clear: ["M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8", "M3 3v5h5"],
    signature: ["M21 17l-2.156-1.868A.5.5 0 0 0 18 15.5v.5a1 1 0 0 1-1 1h-2a1 1 0 0 1-1-1c0-2.545-3.991-3.97-8.5-4a1 1 0 0 0 0 5c4.153 0 4.745-11.295 5.708-13.5a2.5 2.5 0 1 1 3.31 3.284", "M3 21h18"],
    image: ["M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z", "M9 11a2 2 0 1 0 0-4 2 2 0 0 0 0 4z", "M21 15l-3.086-3.086a2 2 0 0 0-2.828 0L6 21"],
};
const Icon = ({ name, size = 16 }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9}
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ flexShrink: 0 }}>
        {PATHS[name].map((d, i) => <path key={i} d={d} />)}
    </svg>
);

const MODES = [
    ["draw", "Draw"],
    ["type", "Type"],
    ["upload", "Upload"],
];

/* The server's vocabulary, not ours. */
const METHOD = { draw: "canvas", type: "typed", upload: "image_upload" };

export default function SignaturePad({ onChange, height = 200 }) {
    const t = useT();
    const [mode, setMode] = useState("draw");

    // THE DRAWING LIVES IN STATE, NOT ON THE CANVAS. A canvas unmounts with the
    // view that holds it, and reading `canvasRef.current.toDataURL()` at submit
    // time then yields nothing -- which is exactly how the builder's Sign & Send
    // came to look like a dead button. Captured at the end of each stroke.
    const [drawn, setDrawn] = useState(null);
    const [typed, setTyped] = useState("");
    const [uploaded, setUploaded] = useState(null);
    const [uploadError, setUploadError] = useState(null);

    const canvasRef = useRef(null);
    const drawing = useRef(false);
    const lastPos = useRef({ x: 0, y: 0 });

    const current = mode === "draw" ? drawn : mode === "type" ? typed.trim() : uploaded;

    useEffect(() => {
        onChange?.({ method: METHOD[mode], data: current || "" });
        // `onChange` is intentionally not a dependency: callers pass an inline
        // arrow, so including it would fire this on every render of the parent.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [mode, current]);

    const pos = (e) => {
        const r = canvasRef.current.getBoundingClientRect();
        const src = e.touches ? e.touches[0] : e;
        // The canvas is drawn at its intrinsic size but displayed stretched, so
        // a click at the right edge is further right in canvas coordinates than
        // in CSS pixels. Without this the ink lags behind the cursor.
        return {
            x: (src.clientX - r.left) * (canvasRef.current.width / r.width),
            y: (src.clientY - r.top) * (canvasRef.current.height / r.height),
        };
    };

    const startDraw = useCallback((e) => {
        if (!canvasRef.current) return;
        e.preventDefault();
        drawing.current = true;
        lastPos.current = pos(e);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const draw = useCallback((e) => {
        if (!drawing.current || !canvasRef.current) return;
        e.preventDefault();
        const p = pos(e);
        const ctx = canvasRef.current.getContext("2d");
        ctx.beginPath();
        ctx.moveTo(lastPos.current.x, lastPos.current.y);
        ctx.lineTo(p.x, p.y);
        ctx.strokeStyle = t.primary;
        ctx.lineWidth = 2.5;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.stroke();
        lastPos.current = p;
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [t.primary]);

    const stopDraw = useCallback(() => {
        if (drawing.current && canvasRef.current) {
            // At the end of a stroke, not on every movement: toDataURL
            // serialises the whole bitmap and is far too costly per pixel.
            setDrawn(canvasRef.current.toDataURL());
        }
        drawing.current = false;
    }, []);

    const clear = () => {
        const c = canvasRef.current;
        if (c) c.getContext("2d").clearRect(0, 0, c.width, c.height);
        setDrawn(null);
        setTyped("");
        setUploaded(null);
        setUploadError(null);
    };

    const onFile = (e) => {
        const file = e.target.files?.[0];
        e.target.value = "";           // so re-picking the same file still fires
        if (!file) return;
        setUploadError(null);

        if (!file.type.startsWith("image/")) {
            setUploadError("That is not an image file.");
            return;
        }
        if (file.size > MAX_IMAGE_BYTES) {
            setUploadError(
                `That image is ${Math.round(file.size / 1024)} KB. The limit is `
                + `${MAX_IMAGE_LABEL} — try a smaller or more compressed one.`);
            return;
        }
        const reader = new FileReader();
        reader.onerror = () => setUploadError("That file could not be read.");
        reader.onload = (ev) => {
            const data = String(ev.target.result || "");
            // The byte check above is the useful one; this catches the edge
            // where encoding pushes a borderline file over the server's cap.
            if (data.length > MAX_SIGNATURE_CHARS) {
                setUploadError(
                    `That image encodes to more than the server accepts. Try one `
                    + `under ${MAX_IMAGE_LABEL}.`);
                return;
            }
            setUploaded(data);
        };
        reader.readAsDataURL(file);
    };

    const pane = {
        position: "relative", background: t.inputBg,
        borderRadius: 12, border: `1px solid ${t.border}`, overflow: "hidden",
    };

    return (
        <div>
            {/* Mode tabs + clear: one even segmented control across the top,
                Clear apart on the right and quiet until there is something
                to clear. */}
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
                <div role="tablist" aria-label="How to sign" style={{
                    display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", flex: "0 1 360px",
                    background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 12, padding: 4, gap: 4,
                }}>
                    {MODES.map(([m, lbl]) => {
                        const on = mode === m;
                        return (
                            <button key={m} type="button" role="tab" aria-selected={on}
                                onClick={() => { setMode(m); setUploadError(null); }}
                                style={{
                                    display: "flex", alignItems: "center", justifyContent: "center", gap: 7,
                                    height: 34, borderRadius: 9, fontSize: 13, fontWeight: on ? 700 : 600,
                                    border: "none", fontFamily: "inherit",
                                    background: on ? t.primary : "transparent",
                                    color: on ? (t.mode === "dark" ? "#0b2b26" : "#fff") : t.textMuted,
                                    boxShadow: on ? `0 6px 14px -8px ${t.primary}` : "none",
                                    cursor: "pointer", transition: "background .2s, color .2s",
                                }}>
                                <Icon name={m} size={15} />{lbl}
                            </button>
                        );
                    })}
                </div>
                <span style={{ flex: 1 }} />
                <button type="button" onClick={clear} disabled={!drawn && !typed && !uploaded}
                    title="Clear the signature" style={{
                        display: "flex", alignItems: "center", gap: 6, height: 36, padding: "0 13px",
                        borderRadius: 10, fontSize: 12.5, fontWeight: 600, fontFamily: "inherit",
                        border: `1px solid ${t.border}`, background: "transparent",
                        color: t.textMuted, cursor: (!drawn && !typed && !uploaded) ? "default" : "pointer",
                        opacity: (!drawn && !typed && !uploaded) ? 0.45 : 1,
                    }}><Icon name="clear" size={14} />Clear</button>
            </div>

            {mode === "draw" && (
                <div style={pane}>
                    <div style={{
                        position: "absolute", left: 20, right: 20, bottom: Math.round(height * 0.26),
                        height: 1, background: `${t.primary}40`, pointerEvents: "none",
                    }} />
                    <canvas
                        ref={canvasRef} width={760} height={height}
                        onMouseDown={startDraw} onMouseMove={draw}
                        onMouseUp={stopDraw} onMouseLeave={stopDraw}
                        onTouchStart={startDraw} onTouchMove={draw} onTouchEnd={stopDraw}
                        style={{
                            display: "block", width: "100%", height,
                            cursor: "crosshair", touchAction: "none",
                            position: "relative", zIndex: 1,
                        }}
                    />
                    {!drawn && (
                        <div style={{
                            position: "absolute", inset: 0, zIndex: 2, gap: 6,
                            display: "flex", flexDirection: "column",
                            alignItems: "center", justifyContent: "center",
                            pointerEvents: "none",
                        }}>
                            <div style={{ color: t.primary, opacity: 0.45 }}><Icon name="signature" size={30} /></div>
                            <div style={{ fontSize: 12.5, color: t.textFaint }}>Draw your signature here</div>
                            <div style={{ fontSize: 11, color: t.textFaint, opacity: 0.7 }}>Mouse or touch</div>
                        </div>
                    )}
                </div>
            )}

            {mode === "type" && (
                <div style={pane}>
                    <div style={{
                        position: "absolute", left: 20, right: 20, bottom: Math.round(height * 0.26),
                        height: 1, background: `${t.primary}40`, pointerEvents: "none",
                    }} />
                    <input
                        value={typed}
                        onChange={e => setTyped(e.target.value)}
                        placeholder="Type your name…"
                        style={{
                            display: "block", width: "100%", height,
                            background: "transparent", border: "none", outline: "none",
                            color: t.primary, fontSize: Math.round(height * 0.2),
                            textAlign: "center", boxSizing: "border-box",
                            fontFamily: "'Brush Script MT','Segoe Script',cursive",
                            padding: "0 20px",
                        }}
                    />
                </div>
            )}

            {mode === "upload" && (
                <div style={{ ...pane, minHeight: height, display: "flex", alignItems: "center", justifyContent: "center" }}>
                    {uploaded ? (
                        <div style={{ width: "100%", padding: "14px 20px", textAlign: "center" }}>
                            <img src={uploaded} alt="Your signature" style={{
                                maxHeight: height - 60, maxWidth: "100%", objectFit: "contain",
                                filter: t.mode === "dark" ? "invert(1) brightness(1.5)" : "none",
                            }} />
                            <div style={{ marginTop: 8, fontSize: 11, color: t.success }}>
                                ✓ Signature image ready
                            </div>
                        </div>
                    ) : (
                        <label style={{
                            display: "flex", flexDirection: "column", alignItems: "center",
                            justifyContent: "center", gap: 10, width: "100%",
                            minHeight: height, cursor: "pointer", padding: "14px 20px",
                            boxSizing: "border-box",
                        }}>
                            <input type="file" accept="image/*" style={{ display: "none" }} onChange={onFile} />
                            <div style={{
                                width: 48, height: 48, borderRadius: 14,
                                background: t.primaryGlow, border: `1.5px dashed ${t.primary}`,
                                display: "flex", alignItems: "center", justifyContent: "center", color: t.primary,
                            }}><Icon name="image" size={22} /></div>
                            <div style={{ textAlign: "center" }}>
                                <div style={{ fontSize: 13.5, fontWeight: 600, color: t.text }}>
                                    Upload a signature image
                                </div>
                                {/* The REAL limit. The old drop zone said 2MB, which the
                                    server rejects with a 422 nobody could interpret. */}
                                <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 3 }}>
                                    PNG or JPG · up to {MAX_IMAGE_LABEL}
                                </div>
                            </div>
                        </label>
                    )}
                </div>
            )}

            {uploadError && (
                <div style={{
                    marginTop: 8, padding: "9px 12px", borderRadius: 9,
                    background: `${t.danger}14`, border: `1px solid ${t.danger}45`,
                    fontSize: 12, color: t.danger, lineHeight: 1.5,
                }}>{uploadError}</div>
            )}
        </div>
    );
}

export { MAX_IMAGE_BYTES, MAX_SIGNATURE_CHARS };
