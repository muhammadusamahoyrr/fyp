'use client';
// Case Law Research — semantic search over the LHC judgment corpus plus a
// citator: "which judgments cite PLD 2019 SC 675?" Every result links to the
// court's original PDF.
import { useEffect, useState } from "react";
import { useTheme } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import { citatorSearch, citatorCitedBy, citatorStats } from "@/lib/api.js";

function JudgmentCard({ j, t, onCiteClick }) {
    return (
        <div style={{ padding: "14px 4px", borderTop: `1px solid ${t.border}` }}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 10, flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 240 }}>
                    <div style={{ fontSize: 13.5, fontWeight: 700, color: t.text, lineHeight: 1.45 }}>
                        {j.title || j.case_no || j.id}
                    </div>
                    <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 3 }}>
                        {[j.case_no, j.judge, j.id].filter(Boolean).join(" · ")}
                        {typeof j.score === "number" && <span style={{ color: t.primary, fontWeight: 700 }}> · {(j.score * 100).toFixed(0)}% match</span>}
                    </div>
                </div>
                <a href={j.pdf_url} target="_blank" rel="noopener noreferrer"
                    style={{ fontSize: 11, fontWeight: 700, color: t.primary, border: `1px solid ${t.primary}40`, borderRadius: 8, padding: "4px 10px", textDecoration: "none", flexShrink: 0 }}>
                    Court PDF ↗
                </a>
            </div>
            {(j.tag_line || j.snippet) && (
                <div style={{ fontSize: 12, color: t.textDim, lineHeight: 1.6, marginTop: 6 }}>
                    {j.tag_line || j.snippet}
                </div>
            )}
            {j.citations_out?.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 8 }}>
                    <span style={{ fontSize: 10, color: t.textFaint, fontWeight: 700, alignSelf: "center" }}>CITES:</span>
                    {j.citations_out.slice(0, 8).map(c => (
                        <button key={c} onClick={() => onCiteClick(c)}
                            title={`Who else cites ${c}?`}
                            style={{ fontSize: 10.5, fontWeight: 700, padding: "2px 8px", borderRadius: 10, cursor: "pointer", border: `1px solid ${t.border}`, background: t.cardHi, color: t.textMuted, fontFamily: "inherit" }}
                            onMouseEnter={e => { e.currentTarget.style.color = t.primary; e.currentTarget.style.borderColor = t.primary; }}
                            onMouseLeave={e => { e.currentTarget.style.color = t.textMuted; e.currentTarget.style.borderColor = t.border; }}>
                            {c}
                        </button>
                    ))}
                    {j.citations_out.length > 8 && <span style={{ fontSize: 10.5, color: t.textFaint, alignSelf: "center" }}>+{j.citations_out.length - 8} more</span>}
                </div>
            )}
        </div>
    );
}

function CaseLawPage() {
    const { t } = useTheme();
    const toast = useToast();
    const [stats, setStats] = useState(null);
    const [mode, setMode] = useState("search"); // search | citedby
    const [q, setQ] = useState("");
    const [cite, setCite] = useState("");
    const [results, setResults] = useState(null);
    const [citedBy, setCitedBy] = useState(null);
    const [busy, setBusy] = useState(false);

    useEffect(() => { citatorStats().then(({ data }) => { if (data) setStats(data); }); }, []);

    const runSearch = async () => {
        if (!q.trim() || busy) return;
        setBusy(true); setMode("search"); setCitedBy(null);
        const { data, error } = await citatorSearch(q.trim());
        setBusy(false);
        if (error) { toast.show("❌ " + (error.message || "Search failed"), "error", 3000); return; }
        setResults(Array.isArray(data) ? data : []);
    };

    const runCitedBy = async (citation) => {
        setBusy(true); setMode("citedby"); setResults(null);
        setCite(citation);
        const { data, error } = await citatorCitedBy(citation);
        setBusy(false);
        if (error) { toast.show("❌ " + (error.message || "Lookup failed"), "error", 3000); return; }
        setCitedBy(data);
    };

    const inputStyle = {
        flex: 1, minWidth: 220, height: 42, padding: "0 14px", borderRadius: 10,
        border: `1.5px solid ${t.border}`, background: t.inputBg, color: t.text,
        fontSize: 13.5, outline: "none", fontFamily: "inherit",
    };
    const goBtn = (label, onClick, disabled) => (
        <button onClick={onClick} disabled={disabled}
            style={{
                padding: "0 22px", height: 42, borderRadius: 10, border: "none",
                background: disabled ? t.border : t.primary,
                color: disabled ? t.textFaint : (t.mode === "dark" ? "#111B1F" : "#fff"),
                fontSize: 13, fontWeight: 700, cursor: disabled ? "default" : "pointer", fontFamily: "inherit",
            }}>{label}</button>
    );

    return (
        <div style={{ maxWidth: 860 }}>
            <div className="fade-up" style={{ marginBottom: 16 }}>
                <div className="serif" style={{ fontSize: 22, fontWeight: 700, color: t.text }}>Case Law Research</div>
                <div style={{ fontSize: 13, color: t.textMuted, marginTop: 3 }}>
                    Lahore High Court reported judgments — semantic search + citation lookups, linked to the court's own PDFs
                    {stats && <span style={{ color: t.primary, fontWeight: 700 }}> · {stats.judgments} judgments · {stats.citation_edges} citation links</span>}
                </div>
            </div>

            {/* Semantic search */}
            <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 14, padding: 16, marginBottom: 14 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>Search judgments</div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === "Enter" && runSearch()}
                        placeholder='e.g. "post-arrest bail in narcotics cases" or "specific performance of oral agreement"'
                        style={inputStyle} />
                    {goBtn(busy && mode === "search" ? "Searching…" : "Search", runSearch, !q.trim() || busy)}
                </div>
            </div>

            {/* Citator */}
            <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 14, padding: 16, marginBottom: 14 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>
                    Citator — who cites this precedent?
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <input value={cite} onChange={e => setCite(e.target.value)} onKeyDown={e => e.key === "Enter" && cite.trim() && runCitedBy(cite.trim())}
                        placeholder="e.g. 1996 SCMR 1544 or PLD 2019 SC 675"
                        style={inputStyle} className="mono" />
                    {goBtn(busy && mode === "citedby" ? "Looking…" : "Find citing judgments", () => runCitedBy(cite.trim()), !cite.trim() || busy)}
                </div>
            </div>

            {/* Results */}
            {mode === "search" && results !== null && (
                <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 14, padding: 16 }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>
                        {results.length} result{results.length === 1 ? "" : "s"}
                    </div>
                    {results.length === 0 && <div style={{ fontSize: 12.5, color: t.textMuted, padding: "8px 0" }}>Nothing matched — try different wording.</div>}
                    {results.map(j => <JudgmentCard key={j.id} j={j} t={t} onCiteClick={runCitedBy} />)}
                </div>
            )}

            {mode === "citedby" && citedBy !== null && (
                <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 14, padding: 16 }}>
                    <div style={{ fontSize: 12.5, color: t.text, marginBottom: 4 }}>
                        <span className="mono" style={{ fontWeight: 800, color: t.primary }}>{citedBy.citation}</span>
                        <span style={{ color: t.textMuted }}> is cited by </span>
                        <b>{citedBy.count}</b>
                        <span style={{ color: t.textMuted }}> judgment{citedBy.count === 1 ? "" : "s"} in the corpus</span>
                    </div>
                    {citedBy.cited_by.length === 0 && (
                        <div style={{ fontSize: 12.5, color: t.textMuted, padding: "8px 0" }}>
                            No citing judgments found yet — the corpus grows with every ingest run.
                        </div>
                    )}
                    {citedBy.cited_by.map(j => <JudgmentCard key={j.id} j={j} t={t} onCiteClick={runCitedBy} />)}
                </div>
            )}
        </div>
    );
}

export { CaseLawPage };
