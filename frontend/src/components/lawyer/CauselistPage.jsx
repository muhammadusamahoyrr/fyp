'use client';
// Cause List Watcher — the munshi's evening job, automated.
// Watch a court case number; the backend checks the LHC cause list on a
// schedule (and on demand) and matched listings land here + as notifications.
import { useEffect, useState } from "react";
import { useTheme } from "./theme.js";
import { Icon, I } from "./icons.jsx";
import { useToast } from "@/components/shared/Toast.jsx";
import {
    createCauselistWatch, listCauselistWatches, deleteCauselistWatch,
    checkCauselist, listCauselistEntries, matchCauselistText,
} from "@/lib/api.js";

const fmtDate = (iso) => iso
    ? new Date(iso + "T00:00:00").toLocaleDateString("en-PK", { weekday: "long", day: "numeric", month: "long", year: "numeric" })
    : "—";

function shareEntryOnWhatsApp(e) {
    const lines = [
        "⚖️ Cause List Alert — Attorney.AI",
        "",
        `Case: ${e.case_no}${e.title ? ` — ${e.title}` : ""}`,
        `Listed: ${fmtDate(e.hearing_date)}`,
        e.judge ? `Court: ${e.judge}` : null,
        e.court_room ? `Room: ${e.court_room}` : null,
        e.seq ? `Serial #: ${e.seq}` : null,
        e.list_type ? `List: ${e.list_type}` : null,
    ].filter(Boolean).join("\n");
    window.open(`https://wa.me/?text=${encodeURIComponent(lines)}`, "_blank", "noopener,noreferrer");
}

function CauselistPage() {
    const { t } = useTheme();
    const toast = useToast();
    const [watches, setWatches] = useState([]);
    const [entries, setEntries] = useState([]);
    const [caseNo, setCaseNo] = useState("");
    const [titleHint, setTitleHint] = useState("");
    const [adding, setAdding] = useState(false);
    const [checking, setChecking] = useState(false);
    const [pasteText, setPasteText] = useState("");
    const [pasteHits, setPasteHits] = useState(null);
    const [matching, setMatching] = useState(false);

    const refresh = async () => {
        const [w, e] = await Promise.all([listCauselistWatches(), listCauselistEntries()]);
        if (Array.isArray(w.data)) setWatches(w.data);
        if (Array.isArray(e.data)) setEntries(e.data);
    };
    useEffect(() => { refresh(); }, []);

    const addWatch = async () => {
        if (!caseNo.trim() || adding) return;
        setAdding(true);
        const { error } = await createCauselistWatch({ case_no: caseNo.trim(), title_hint: titleHint.trim() });
        setAdding(false);
        if (error) { toast.show("❌ " + (error.message || "Could not add watch"), "error", 3500); return; }
        setCaseNo(""); setTitleHint("");
        toast.show("✅ Watching — we'll alert you when it's listed", "success", 3000);
        refresh();
    };

    const removeWatch = async (id) => {
        const { error } = await deleteCauselistWatch(id);
        if (error) { toast.show("❌ " + (error.message || "Delete failed"), "error", 3000); return; }
        refresh();
    };

    const checkNow = async () => {
        if (checking) return;
        setChecking(true);
        const { data, error } = await checkCauselist();
        setChecking(false);
        if (error) { toast.show("❌ " + (error.message || "Check failed"), "error", 4000); return; }
        const n = data?.new_entries?.length || 0;
        const errs = data?.source_errors || 0;
        toast.show(
            n > 0 ? `📋 ${n} new listing${n === 1 ? "" : "s"} found!`
                : errs > 0 ? "⚠️ Court website unreachable — try again shortly"
                    : "✓ Checked — no new listings",
            n > 0 ? "success" : errs > 0 ? "warn" : "info", 3500,
        );
        refresh();
    };

    const runPasteMatch = async () => {
        if (!pasteText.trim() || matching) return;
        setMatching(true);
        const { data, error } = await matchCauselistText(pasteText);
        setMatching(false);
        if (error) { toast.show("❌ " + (error.message || "Match failed"), "error", 3000); return; }
        setPasteHits(Array.isArray(data) ? data : []);
    };

    const inputStyle = {
        height: 38, padding: "0 12px", borderRadius: 9, border: `1.5px solid ${t.border}`,
        background: t.inputBg, color: t.text, fontSize: 13, outline: "none", fontFamily: "inherit",
    };

    return (
        <div style={{ maxWidth: 860 }}>
            {/* Header */}
            <div className="fade-up" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18, flexWrap: "wrap", gap: 10 }}>
                <div>
                    <div className="serif" style={{ fontSize: 22, fontWeight: 700, color: t.text }}>Cause List Watcher</div>
                    <div style={{ fontSize: 13, color: t.textMuted, marginTop: 3 }}>
                        Lahore High Court (Principal Seat, Multan, Bahawalpur & Rawalpindi benches) — checked automatically every few hours
                    </div>
                </div>
                <button onClick={checkNow} disabled={checking || !watches.length}
                    style={{
                        padding: "9px 18px", borderRadius: 10, border: `1.5px solid ${t.primary}50`,
                        background: t.primaryGlow2, color: t.primary, fontSize: 12.5, fontWeight: 700,
                        cursor: checking || !watches.length ? "not-allowed" : "pointer", fontFamily: "inherit",
                        opacity: checking || !watches.length ? 0.55 : 1,
                    }}>
                    {checking ? "Checking LHC…" : "⟳ Check Now"}
                </button>
            </div>

            {/* Add watch */}
            <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 14, padding: 16, marginBottom: 16 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>Watch a case</div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <input value={caseNo} onChange={e => setCaseNo(e.target.value)}
                        onKeyDown={e => e.key === "Enter" && addWatch()}
                        placeholder="Court case no. — e.g. 39043/26" style={{ ...inputStyle, width: 220 }} />
                    <input value={titleHint} onChange={e => setTitleHint(e.target.value)}
                        onKeyDown={e => e.key === "Enter" && addWatch()}
                        placeholder="Label (optional) — e.g. Fayyaz bail matter" style={{ ...inputStyle, flex: 1, minWidth: 200 }} />
                    <button onClick={addWatch} disabled={!caseNo.trim() || adding}
                        style={{
                            padding: "0 20px", height: 38, borderRadius: 9, border: "none",
                            background: caseNo.trim() ? t.primary : t.border,
                            color: caseNo.trim() ? (t.mode === "dark" ? "#111B1F" : "#fff") : t.textFaint,
                            fontSize: 13, fontWeight: 700, cursor: caseNo.trim() ? "pointer" : "default", fontFamily: "inherit",
                        }}>
                        {adding ? "Adding…" : "+ Watch"}
                    </button>
                </div>

                {/* Watches */}
                {watches.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
                        {watches.map(w => (
                            <div key={w.id} style={{
                                display: "flex", alignItems: "center", gap: 8, padding: "6px 8px 6px 12px",
                                borderRadius: 20, border: `1.5px solid ${t.border}`, background: t.cardHi, fontSize: 12,
                            }}>
                                <span className="mono" style={{ fontWeight: 700, color: t.primary }}>{w.case_no}</span>
                                {w.title_hint && <span style={{ color: t.textMuted, maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{w.title_hint}</span>}
                                {w.last_listed_date && <span style={{ color: t.success, fontSize: 10.5, fontWeight: 600 }}>listed {w.last_listed_date}</span>}
                                <button onClick={() => removeWatch(w.id)} title="Stop watching"
                                    style={{ width: 20, height: 20, borderRadius: "50%", border: "none", background: "transparent", color: t.textFaint, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}
                                    onMouseEnter={e => e.currentTarget.style.color = t.danger}
                                    onMouseLeave={e => e.currentTarget.style.color = t.textFaint}>
                                    <Icon d={I.x} size={11} />
                                </button>
                            </div>
                        ))}
                    </div>
                )}
                {watches.length === 0 && (
                    <div style={{ fontSize: 12.5, color: t.textMuted, marginTop: 10 }}>
                        No watches yet — add the court's case number (as printed on the cause list) and we'll tell you the moment it's listed.
                    </div>
                )}
            </div>

            {/* Upcoming listings */}
            <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 14, padding: 16, marginBottom: 16 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>Upcoming listings</div>
                {entries.length === 0 ? (
                    <div style={{ fontSize: 12.5, color: t.textMuted }}>Nothing matched yet — listings appear here (and as notifications) when a watched case shows up on the cause list.</div>
                ) : entries.map(e => (
                    <div key={e.id} style={{
                        display: "flex", alignItems: "flex-start", gap: 12, padding: "12px 4px",
                        borderTop: `1px solid ${t.border}`,
                    }}>
                        <div style={{
                            minWidth: 52, textAlign: "center", padding: "6px 4px", borderRadius: 10,
                            background: t.primaryGlow2, border: `1px solid ${t.primary}30`,
                        }}>
                            <div style={{ fontSize: 16, fontWeight: 800, color: t.primary, lineHeight: 1.1 }}>
                                {e.hearing_date ? new Date(e.hearing_date + "T00:00:00").getDate() : "?"}
                            </div>
                            <div style={{ fontSize: 9.5, fontWeight: 700, color: t.primary, textTransform: "uppercase" }}>
                                {e.hearing_date ? new Date(e.hearing_date + "T00:00:00").toLocaleDateString("en", { month: "short" }) : ""}
                            </div>
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: 13.5, fontWeight: 700, color: t.text }}>
                                <span className="mono" style={{ color: t.primary }}>{e.case_no}</span>
                                {e.title ? ` — ${e.title}` : ""}
                                {e.connected && <span style={{ fontSize: 10, color: t.warn, fontWeight: 700 }}> (connected matter)</span>}
                            </div>
                            <div style={{ fontSize: 12, color: t.textMuted, marginTop: 3 }}>
                                {[e.judge, e.court_room, e.seq ? `Seq #${e.seq}` : null, e.list_type].filter(Boolean).join(" · ")}
                            </div>
                            <div style={{ fontSize: 11.5, color: t.textFaint, marginTop: 2 }}>{fmtDate(e.hearing_date)}{e.remarks ? ` · ${e.remarks}` : ""}</div>
                        </div>
                        <button onClick={() => shareEntryOnWhatsApp(e)} title="Share on WhatsApp"
                            style={{
                                display: "flex", alignItems: "center", gap: 5, padding: "5px 12px", borderRadius: 8,
                                border: "1px solid #25D36650", background: "#25D36615", color: "#25D366",
                                fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", flexShrink: 0,
                            }}>
                            Share
                        </button>
                    </div>
                ))}
            </div>

            {/* Paste fallback */}
            <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 14, padding: 16 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>Paste a cause list</div>
                <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 10 }}>
                    District court list from a WhatsApp group? Paste the text — we'll scan it for your watched cases.
                </div>
                <textarea value={pasteText} onChange={e => setPasteText(e.target.value)} rows={5}
                    placeholder="Paste the cause-list text here…"
                    style={{ ...inputStyle, width: "100%", height: "auto", padding: 12, resize: "vertical", lineHeight: 1.6, boxSizing: "border-box" }} />
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8 }}>
                    <button onClick={runPasteMatch} disabled={!pasteText.trim() || matching}
                        style={{
                            padding: "8px 18px", borderRadius: 9, border: `1.5px solid ${t.border}`,
                            background: t.cardHi, color: t.text, fontSize: 12.5, fontWeight: 700,
                            cursor: pasteText.trim() ? "pointer" : "default", fontFamily: "inherit",
                            opacity: pasteText.trim() ? 1 : 0.5,
                        }}>
                        {matching ? "Scanning…" : "🔍 Find my cases"}
                    </button>
                    {pasteHits !== null && (
                        <span style={{ fontSize: 12.5, fontWeight: 600, color: pasteHits.length ? t.success : t.textMuted }}>
                            {pasteHits.length ? `${pasteHits.length} match${pasteHits.length === 1 ? "" : "es"} found` : "No watched cases in this list"}
                        </span>
                    )}
                </div>
                {pasteHits?.length > 0 && pasteHits.map((h, i) => (
                    <div key={i} style={{ marginTop: 8, padding: "8px 12px", borderRadius: 9, background: `${t.success}12`, border: `1px solid ${t.success}35`, fontSize: 12 }}>
                        <span className="mono" style={{ fontWeight: 700, color: t.success }}>{h.case_no}</span>
                        <span style={{ color: t.textDim }}> — {h.line}</span>
                    </div>
                ))}
            </div>
        </div>
    );
}

export { CauselistPage };
