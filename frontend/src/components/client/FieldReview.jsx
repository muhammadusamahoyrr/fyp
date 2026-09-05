'use client';
/* What the AI pulled out of your case, shown before it becomes a document.
 *
 * Deliberately thin. Every decision — which fields exist, which the model
 * missed, which it returned that this template cannot use, what actually gets
 * submitted — lives in `lib/fieldReview.js`, where it is tested. What is left
 * here is presentation.
 */
import { EMPTY, UNUSED } from "@/lib/fieldReview.js";

export default function FieldReview({
    t, rows, missing, edited, busy, onEdit, onGenerate, onBack,
}) {
    const unused = rows.filter(r => r.status === UNUSED);
    const used = rows.filter(r => r.status !== UNUSED);

    return (
        <div>
            <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 4 }}>
                    Check these details before we draft
                </div>
                <div style={{ fontSize: 11.5, color: t.textMuted, lineHeight: 1.6 }}>
                    These were read from your case description automatically.
                    Correct anything that is wrong — it is much easier to fix
                    here than in the finished document.
                </div>
            </div>

            {missing.length > 0 && (
                <div style={{ padding: "11px 13px", borderRadius: 11, background: `${t.warn}10`, border: `1px solid ${t.warn}30`, marginBottom: 12 }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: t.warn, marginBottom: 3 }}>
                        {missing.length === 1
                            ? "1 detail was not found"
                            : `${missing.length} details were not found`}
                    </div>
                    {/* WARNED, NEVER BLOCKED. Whether a field is legally
                        required is a question `pleading_rules` answers on the
                        server for the templates the statutes actually speak
                        to. Blocking here would invent a requirement nobody
                        checked. */}
                    <div style={{ fontSize: 11.5, color: t.text, lineHeight: 1.6 }}>
                        {missing.join(", ")}. You can fill them in now or leave
                        them — the draft will simply not mention them.
                    </div>
                </div>
            )}

            {used.map(row => (
                <label key={row.name} style={{ display: "block", marginBottom: 10 }}>
                    <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4, display: "flex", gap: 6, alignItems: "center" }}>
                        {row.label}
                        {row.status === EMPTY && (
                            <span style={{ fontSize: 10, color: t.warn }}>not found</span>
                        )}
                    </div>
                    {row.name.endsWith("_body") || row.name === "grounds" ? (
                        <textarea
                            value={row.value}
                            onChange={e => onEdit(row.name, e.target.value)}
                            rows={4}
                            style={{ width: "100%", background: t.inputBg, border: `1.5px solid ${row.status === EMPTY ? `${t.warn}55` : t.border}`, color: t.text, borderRadius: 11, padding: "10px 12px", fontSize: 12.5, outline: "none", fontFamily: "'Inter',sans-serif", resize: "vertical" }} />
                    ) : (
                        <input
                            value={row.value}
                            onChange={e => onEdit(row.name, e.target.value)}
                            style={{ width: "100%", background: t.inputBg, border: `1.5px solid ${row.status === EMPTY ? `${t.warn}55` : t.border}`, color: t.text, borderRadius: 11, padding: "10px 12px", fontSize: 12.5, outline: "none", fontFamily: "'Inter',sans-serif" }} />
                    )}
                </label>
            ))}

            {/* A value the model returned that this template cannot use. The
                builder drops it; saying so is the difference between a value
                the client chose not to use and one thrown away silently. */}
            {unused.length > 0 && (
                <div style={{ padding: "10px 12px", borderRadius: 11, background: t.inputBg, border: `1px solid ${t.border}`, marginBottom: 12 }}>
                    <div style={{ fontSize: 10.5, color: t.textMuted, marginBottom: 4 }}>
                        Also found, but this document does not use them:
                    </div>
                    <div style={{ fontSize: 11.5, color: t.textFaint, lineHeight: 1.6 }}>
                        {unused.map(r => `${r.label}: ${r.value}`).join(" · ")}
                    </div>
                </div>
            )}

            <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                <button
                    onClick={onBack}
                    disabled={busy}
                    style={{ padding: "11px 16px", borderRadius: 11, border: `1px solid ${t.border}`, background: "transparent", color: t.textMuted, fontSize: 12, fontWeight: 600, cursor: busy ? "default" : "pointer", fontFamily: "'Inter',sans-serif" }}>
                    Back
                </button>
                <button
                    onClick={onGenerate}
                    disabled={busy}
                    style={{ flex: 1, padding: "11px 16px", borderRadius: 11, border: "none", background: t.primary, color: "#fff", fontSize: 12, fontWeight: 700, cursor: busy ? "default" : "pointer", fontFamily: "'Inter',sans-serif", opacity: busy ? 0.6 : 1 }}>
                    {busy ? "Generating…"
                        : edited ? "Generate with my corrections →"
                        : "These are correct — generate →"}
                </button>
            </div>
        </div>
    );
}
