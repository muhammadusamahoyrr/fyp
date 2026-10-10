'use client';
/* Line icons for the client Documents screens (2026-10-08).
 *
 * The paths are from Lucide (https://lucide.dev, ISC licence) -- the same thin,
 * rounded line family PakLawBot uses -- so the drafting screens read as one
 * designed set instead of mixed glyphs and emoji. Client-only: the lawyer side
 * keeps its own icons (tests/role_boundaries.test.mjs). */
import React from "react";

const PATHS = {
    back: ["M19 12H5", "M12 19l-7-7 7-7"],
    sliders: ["M21 4h-7", "M10 4H3", "M21 12h-9", "M8 12H3", "M21 20h-5", "M12 20H3", "M14 2v4", "M8 10v4", "M16 18v4"],
    listChecks: ["M3 17l2 2 4-4", "M3 7l2 2 4-4", "M13 6h8", "M13 12h8", "M13 18h8"],
    pencil: ["M21.17 6.81a1 1 0 0 0-3.99-3.99L3.84 16.17a2 2 0 0 0-.5.83l-1.32 4.35a.5.5 0 0 0 .62.62l4.35-1.32a2 2 0 0 0 .83-.5z", "M15 5l4 4"],
    undo: ["M9 14L4 9l5-5", "M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5 5.5 5.5 0 0 1-5.5 5.5H11"],
    redo: ["M15 14l5-5-5-5", "M20 9H9.5A5.5 5.5 0 0 0 4 14.5 5.5 5.5 0 0 0 9.5 20H13"],
    download: ["M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4", "M7 10l5 5 5-5", "M12 15V3"],
    send: ["M14.54 21.69a.5.5 0 0 0 .94-.02l6.5-19a.5.5 0 0 0-.64-.64l-19 6.5a.5.5 0 0 0-.02.94l7.93 3.18a2 2 0 0 1 1.11 1.11z", "M21.85 2.15L10.91 13.09"],
    x: ["M18 6L6 18", "M6 6l12 12"],
    check: ["M20 6L9 17l-5-5"],
    checkCircle: ["M21.8 10A10 10 0 1 1 17 3.34", "M9 11l3 3L22 4"],
    alertCircle: ["M12 8v4", "M12 16h.01", "CIRCLE"],
    alertTriangle: ["M21.73 18l-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3", "M12 9v4", "M12 17h.01"],
    minusCircle: ["CIRCLE", "M8 12h8"],
    arrowRight: ["M5 12h14", "M12 5l7 7-7 7"],
    lock: ["M5 11h14v10H5z", "M7 11V7a5 5 0 0 1 10 0v4"],
    save: ["M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z", "M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7", "M7 3v4a1 1 0 0 0 1 1h7"],
    bold: ["M6 12h9a4 4 0 0 1 0 8H7a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h7a4 4 0 0 1 0 8"],
    italic: ["M19 4h-9", "M14 20H5", "M15 4L9 20"],
    underline: ["M6 4v6a6 6 0 0 0 12 0V4", "M4 20h16"],
    strike: ["M16 4H9a3 3 0 0 0-2.83 4", "M14 12a4 4 0 0 1 0 8H6", "M4 12h16"],
    list: ["M3 12h.01", "M3 18h.01", "M3 6h.01", "M8 12h13", "M8 18h13", "M8 6h13"],
    listOrdered: ["M10 12h11", "M10 18h11", "M10 6h11", "M4 10h2", "M4 6h1v4", "M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"],
    quote: ["M16 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z", "M5 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z"],
    alignLeft: ["M15 12H3", "M17 18H3", "M21 6H3"],
    alignCenter: ["M17 12H7", "M19 18H5", "M21 6H3"],
    alignRight: ["M21 12H9", "M21 18H7", "M21 6H3"],
    alignJustify: ["M3 12h18", "M3 18h18", "M3 6h18"],
    minus: ["M5 12h14"],
    chevronDown: ["M6 9l6 6 6-6"],
    externalLink: ["M15 3h6v6", "M10 14L21 3", "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"],
    scale: ["M16 16l3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1z", "M2 16l3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1z", "M7 21h10", "M12 3v18", "M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"],
    paperclip: ["M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"],
    shield: ["M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"],
    // A pen over a square: edit (the template cards' Edit, 2026-10-08).
    squarePen: ["M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7", "M18.38 2.63a1 1 0 0 1 3 3l-9.01 9.01a2 2 0 0 1-.85.51l-2.87.84a.5.5 0 0 1-.62-.62l.84-2.87a2 2 0 0 1 .51-.85z"],
    sparkles: ["M9.94 15.5A2 2 0 0 0 8.5 14.06l-6.14-1.58a.5.5 0 0 1 0-.96L8.5 9.94A2 2 0 0 0 9.94 8.5l1.58-6.14a.5.5 0 0 1 .96 0L14.06 8.5a2 2 0 0 0 1.44 1.44l6.14 1.58a.5.5 0 0 1 0 .96l-6.14 1.58a2 2 0 0 0-1.44 1.44l-1.58 6.14a.5.5 0 0 1-.96 0z", "M20 3v4", "M22 5h-4", "M4 17v2", "M5 18H3"],
    arrowUp: ["M5 12l7-7 7 7", "M12 19V5"],
    moreHorizontal: ["M5 12h.01", "M12 12h.01", "M19 12h.01"],
    moreVertical: ["M12 5h.01", "M12 12h.01", "M12 19h.01"],
    trash: ["M3 6h18", "M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6", "M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"],
    eye: ["M2.06 12.35a1 1 0 0 1 0-.7 10.75 10.75 0 0 1 19.88 0 1 1 0 0 1 0 .7 10.75 10.75 0 0 1-19.88 0", "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"],
    mail: ["M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z", "M22 7l-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"],
    history: ["M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8", "M3 3v5h5", "M12 7v5l4 2"],
    bookmark: ["M19 21l-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"],
    fileText: ["M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z", "M14 2v4a2 2 0 0 0 2 2h4", "M10 9H8", "M16 13H8", "M16 17H8"],
    store: ["M2 7l4.41-4.41A2 2 0 0 1 7.83 2h8.34a2 2 0 0 1 1.42.59L22 7", "M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8", "M15 22v-4a2 2 0 0 0-2-2h-2a2 2 0 0 0-2 2v4", "M2 7h20", "M22 7v3a2 2 0 0 1-2 2 2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 16 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 12 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 8 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 4 12a2 2 0 0 1-2-2V7"],
};

/* One icon: <LIcon name="pencil" size={17} />. Decorative unless given a label. */
export function LIcon({ name, size = 17, stroke = 1.75, label = null, style }) {
    const parts = PATHS[name] || [];
    return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke}
            strokeLinecap="round" strokeLinejoin="round" role={label ? "img" : undefined}
            aria-label={label || undefined} aria-hidden={label ? undefined : "true"} style={{ flexShrink: 0, ...style }}>
            {parts.map((d, i) => (d === "CIRCLE"
                ? <circle key={i} cx="12" cy="12" r="10" />
                : <path key={i} d={d} />))}
        </svg>
    );
}
