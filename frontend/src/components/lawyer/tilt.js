/* The 3D tilt for lawyer document cards (2026-10-09): the card leans toward
 * the pointer and its icon floats above it. Sets --rx/--ry (degrees) and
 * --px/--py (-0.5..0.5) on the card; the screen's CSS turns them into the
 * tilt, the icon's parallax and its gloss. Off under reduced motion. */
const reduced = () => typeof window !== "undefined"
    && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export function tiltHandlers(max = 8) {
    return {
        onPointerMove(e) {
            if (e.pointerType === "touch" || reduced()) return;
            const el = e.currentTarget;
            const r = el.getBoundingClientRect();
            const px = (e.clientX - r.left) / r.width - 0.5;
            const py = (e.clientY - r.top) / r.height - 0.5;
            el.style.setProperty("--px", px.toFixed(3));
            el.style.setProperty("--py", py.toFixed(3));
            el.style.setProperty("--rx", `${(-py * max).toFixed(2)}deg`);
            el.style.setProperty("--ry", `${(px * max).toFixed(2)}deg`);
        },
        onPointerLeave(e) {
            const el = e.currentTarget;
            for (const k of ["--px", "--py", "--rx", "--ry"]) el.style.removeProperty(k);
        },
    };
}
