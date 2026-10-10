'use client';
// Legal Tools for the lawyer (2026-10-09): the bail checker and the
// calculators the backend already serves (court fee, inheritance, labour
// dues). The client has its own copies in client/ModTools.jsx; this is the
// lawyer's, in the lawyer theme, and imports nothing from the client side.
import { useMemo, useRef, useState } from "react";
import { useTheme } from "./theme.js";
import { useToast } from "./Toast.jsx";
import { DRAFTING_TOKENS_CSS, draftingMode } from "./draftingTheme.js";
import { keyForIntent } from "@/lib/intentKey.js";
import {
    bailSearch, bailCheck, courtFeeCalculate, inheritanceCalculate,
    inheritanceSettlementPdf, labourDuesCalculate, downloadDocumentFile,
} from "@/lib/api.js";

const TOOLS_CSS = `[data-tools-ws]{flex:none;min-height:100%;color:var(--ink);font-family:"Hanken Grotesk",system-ui,sans-serif;-webkit-font-smoothing:antialiased;background:var(--bg);padding:26px 30px 48px;box-sizing:border-box}
[data-tools-ws] *{box-sizing:border-box}
[data-tools-ws] button,[data-tools-ws] input,[data-tools-ws] select{font-family:inherit}
[data-tools-ws] .lt-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:18px}
[data-tools-ws] .lt-head h1{margin:0;font-family:"Literata",Georgia,serif;font-size:28px;font-weight:600;letter-spacing:-.01em}
[data-tools-ws] .lt-head p{margin:4px 0 0;font-size:13.5px;color:var(--muted)}
[data-tools-ws] .lt-tabs{display:flex;gap:4px;padding:4px;border-radius:12px;background:var(--surface-2);border:1px solid var(--line)}
[data-tools-ws] .lt-tabs button{height:34px;padding:0 14px;border:0;border-radius:9px;background:none;color:var(--muted);font-size:13px;font-weight:650;cursor:pointer}
[data-tools-ws] .lt-tabs button[aria-pressed="true"]{background:var(--surface);color:var(--ink);box-shadow:inset 0 0 0 1px var(--line)}
[data-tools-ws] .lt-grid{display:grid;grid-template-columns:minmax(300px,380px) minmax(0,1fr);gap:16px;align-items:start}
[data-tools-ws] .lt-card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:18px}
[data-tools-ws] .lt-card h2{margin:0 0 4px;font-size:15px;font-weight:700}
[data-tools-ws] .lt-sub{font-size:12.5px;color:var(--muted);margin:0 0 14px;line-height:1.5}
[data-tools-ws] .lt-lbl{display:block;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);margin:12px 0 6px}
[data-tools-ws] .lt-in{width:100%;height:40px;padding:0 12px;border-radius:10px;border:1px solid var(--line-strong);background:var(--input);color:var(--ink);font-size:13.5px;outline:none}
[data-tools-ws] .lt-in:focus{border-color:var(--brand-text)}
[data-tools-ws] .lt-btn{height:40px;padding:0 16px;border-radius:10px;border:0;background:linear-gradient(135deg,#3EE0A1,#2EC4D6);color:#04212A;font-size:13.5px;font-weight:700;cursor:pointer;white-space:nowrap}
[data-tools-ws] .lt-btn:disabled{opacity:.55;cursor:default}
[data-tools-ws] .lt-btn.ghost{background:none;border:1px solid var(--line-strong);color:var(--ink)}
[data-tools-ws] .lt-empty{padding:40px 20px;text-align:center;color:var(--muted);font-size:13px;line-height:1.6}
[data-tools-ws] .lt-big{font-size:32px;font-weight:800;color:var(--brand-text);margin:6px 0}
[data-tools-ws] .lt-note{font-size:12px;color:var(--muted);margin-top:8px;line-height:1.5}
[data-tools-ws] .lt-warn{margin-top:12px;padding:10px 12px;border-radius:10px;background:rgba(242,195,94,.1);border:1px solid rgba(242,195,94,.35);font-size:12.5px;color:var(--ink)}
[data-tools-ws] .lt-table{border:1px solid var(--line);border-radius:12px;overflow:hidden}
[data-tools-ws] .lt-row{display:grid;grid-template-columns:minmax(0,1fr) 64px 64px 120px;gap:8px;padding:10px 12px;border-top:1px solid var(--line);font-size:13px;align-items:center}
[data-tools-ws] .lt-row:first-child{border-top:0;background:var(--surface-2);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--faint)}
[data-tools-ws] .lt-row.two{grid-template-columns:minmax(0,1fr) 140px}
[data-tools-ws] .lt-row.total{border-top:2px solid var(--line-strong);font-weight:800;color:var(--brand-text)}
[data-tools-ws] .lt-num{text-align:right;font-weight:700}
[data-tools-ws] .lt-count{display:flex;align-items:center;justify-content:space-between;padding:8px 10px 8px 12px;border-radius:10px;border:1px solid var(--line);background:var(--input);font-size:13px;font-weight:600}
[data-tools-ws] .lt-count div{display:flex;align-items:center;gap:8px}
[data-tools-ws] .lt-count button{width:26px;height:26px;border-radius:7px;border:1px solid var(--line-strong);background:var(--surface);color:var(--ink);font-weight:700;cursor:pointer}
[data-tools-ws] .lt-count b{min-width:18px;text-align:center}
[data-tools-ws] .lt-count b.on{color:var(--brand-text)}
[data-tools-ws] .lt-chip{display:inline-flex;align-items:center;height:24px;padding:0 9px;border-radius:999px;font-size:11.5px;font-weight:700;border:1px solid}
[data-tools-ws] .lt-chip.good{color:#5AD69A;border-color:rgba(90,214,154,.4);background:rgba(90,214,154,.1)}
[data-tools-ws] .lt-chip.bad{color:#F28B80;border-color:rgba(242,139,128,.4);background:rgba(242,139,128,.1)}
[data-tools-ws] .lt-chip.warn{color:#F2C35E;border-color:rgba(242,195,94,.4);background:rgba(242,195,94,.1)}
[data-tools-ws] .lt-chip.neutral{color:var(--muted);border-color:var(--line-strong);background:var(--surface-2)}
[data-tools-ws] .lt-hit{display:block;width:100%;text-align:left;padding:11px 12px;border-radius:10px;border:1px solid transparent;background:none;color:var(--ink);cursor:pointer;margin-bottom:2px}
[data-tools-ws] .lt-hit:hover{background:var(--hover-tint)}
[data-tools-ws] .lt-hit.on{border-color:var(--brand-text);background:var(--hover-tint)}
[data-tools-ws] .lt-seg{display:inline-flex;gap:4px;padding:3px;border-radius:10px;background:var(--surface-2);border:1px solid var(--line);margin-bottom:14px}
[data-tools-ws] .lt-seg button{height:30px;padding:0 12px;border:0;border-radius:7px;background:none;color:var(--muted);font-size:12.5px;font-weight:700;cursor:pointer}
[data-tools-ws] .lt-seg button[aria-pressed="true"]{background:var(--surface);color:var(--ink);box-shadow:inset 0 0 0 1px var(--line)}
[data-tools-ws] .lt-guide{padding:14px;border-radius:12px;background:var(--surface-2);border:1px solid var(--line)}
[data-tools-ws] .lt-guide ol{margin:8px 0 0;padding-left:18px}
[data-tools-ws] .lt-guide li{font-size:13px;line-height:1.55;margin-bottom:6px}
[data-tools-ws] .lt-check{display:flex;align-items:center;gap:8px;margin-top:12px;font-size:13px;cursor:pointer}`;

const errText = (error, fallback) => error?.message || error?.detail || fallback;
const toNum = (v) => parseInt(String(v).replace(/[^0-9]/g, ""), 10) || 0;

function Shell({ title, sub, tabs, tab, setTab, children }) {
    const { t } = useTheme();
    return (
        <div data-tools-ws data-drafting-theme data-mode={draftingMode(t)}>
            <style>{`${DRAFTING_TOKENS_CSS}\n${TOOLS_CSS}`}</style>
            <div className="lt-head">
                <div>
                    <h1>{title}</h1>
                    <p>{sub}</p>
                </div>
                {tabs && (
                    <div className="lt-tabs" role="group" aria-label="Calculator">
                        {tabs.map(([id, label]) => (
                            <button key={id} type="button" aria-pressed={tab === id} onClick={() => setTab(id)}>{label}</button>
                        ))}
                    </div>
                )}
            </div>
            {children}
        </div>
    );
}

/* ── Bail checker ─────────────────────────────────────────────────────── */
function Chip({ tone, children }) { return <span className={`lt-chip ${tone}`}>{children}</span>; }
const yesNo = (v, yes, no) => (v === null || v === undefined
    ? <Chip tone="neutral">depends</Chip>
    : v ? <Chip tone="good">{yes}</Chip> : <Chip tone="bad">{no}</Chip>);

function BailChecker() {
    const toast = useToast();
    const [q, setQ] = useState("");
    const [hits, setHits] = useState([]);
    const [searched, setSearched] = useState(false);
    const [busy, setBusy] = useState(false);
    const [picked, setPicked] = useState(null);
    const [arrested, setArrested] = useState(true);
    const [res, setRes] = useState(null);

    const search = async () => {
        if (!q.trim()) return toast.show("Type a section number (e.g. 302) or an offence (e.g. theft)", "warn");
        setBusy(true);
        const { data, error } = await bailSearch(q.trim());
        setBusy(false);
        if (error) return toast.show(errText(error, "Search failed"), "danger");
        setSearched(true); setHits(data?.results || []); setRes(null); setPicked(null);
    };
    const check = async (o, isArrested) => {
        setPicked(o); setBusy(true);
        const { data, error } = await bailCheck({ law: o.law, section: o.section, arrested: isArrested });
        setBusy(false);
        if (error || !data) return toast.show(errText(error, "Check failed"), "danger");
        setRes(data);
    };

    return (
        <div className="lt-grid">
            <div style={{ display: "grid", gap: 16 }}>
                <div className="lt-card">
                    <h2>Is this offence bailable?</h2>
                    <p className="lt-sub">Look up an offence by section (<b>302</b>, <b>489-F</b>) or by name (<b>theft</b>, <b>cheque</b>) for its Second Schedule (CrPC 1898) classification.</p>
                    <div style={{ display: "flex", gap: 8 }}>
                        <input className="lt-in" value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === "Enter" && search()}
                            placeholder="Section or offence…" aria-label="Section or offence" />
                        <button type="button" className="lt-btn" onClick={search} disabled={busy}>{busy && !picked ? "…" : "Search"}</button>
                    </div>
                </div>
                {searched && hits.length === 0 && (
                    <div className="lt-card lt-note" style={{ marginTop: 0 }}>No matching offence in the reference list. Confirm the section against the Second Schedule of the CrPC 1898.</div>
                )}
                {hits.length > 0 && (
                    <div className="lt-card" style={{ padding: 8 }}>
                        {hits.map(o => (
                            <button key={o.id} type="button" className={`lt-hit${picked?.id === o.id ? " on" : ""}`} onClick={() => check(o, arrested)}>
                                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                                    <b style={{ fontSize: 13.5 }}>{o.law} s.{o.section}</b>
                                    <span style={{ fontSize: 13 }}>{o.title}</span>
                                    {yesNo(o.bailable, "bailable", "non-bailable")}
                                    {o.confidence === "verify" && <Chip tone="warn">verify</Chip>}
                                </div>
                                <div className="lt-note" style={{ marginTop: 3 }}>{o.punishment} · {o.court}</div>
                            </button>
                        ))}
                    </div>
                )}
            </div>
            <div className="lt-card" style={{ minHeight: 240 }}>
                {!res ? (
                    <div className="lt-empty">Search an offence and pick it to see its classification and the pre- and post-arrest bail steps.</div>
                ) : res.found ? (
                    <>
                        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                            <h2 style={{ fontSize: 18 }}>{res.offence.law} s.{res.offence.section}</h2>
                            <span className="lt-note" style={{ marginTop: 0 }}>{res.offence.title}</span>
                        </div>
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "10px 0 14px" }}>
                            {yesNo(res.offence.bailable, "bailable", "non-bailable")}
                            {yesNo(res.offence.cognizable, "cognizable", "non-cognizable")}
                            {yesNo(res.offence.compoundable, "compoundable", "non-compoundable")}
                            {res.offence.prohibitory && <Chip tone="bad">prohibitory clause (s.497(1))</Chip>}
                            <Chip tone={res.confidence === "verify" ? "warn" : "neutral"}>{res.confidence === "verify" ? "verify classification" : "established"}</Chip>
                        </div>
                        <div className="lt-seg" role="group" aria-label="Arrest status">
                            {[["Not yet arrested", false], ["Already arrested", true]].map(([label, v]) => (
                                <button key={label} type="button" aria-pressed={arrested === v} onClick={() => { setArrested(v); check(res.offence, v); }}>{label}</button>
                            ))}
                        </div>
                        <div className="lt-guide">
                            <b style={{ fontSize: 13.5 }}>{res.guidance.summary}</b>
                            {res.guidance.sections?.length > 0 && (
                                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                                    {res.guidance.sections.map((s, i) => <Chip key={i} tone="neutral">{s}</Chip>)}
                                </div>
                            )}
                            <ol>{res.guidance.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
                        </div>
                        {res.offence.note && <div className="lt-warn">{res.offence.note}</div>}
                        <div className="lt-note">{res.legal_basis}</div>
                        <div className="lt-note" style={{ fontSize: 11.5 }}>{res.disclaimer}</div>
                    </>
                ) : (
                    <>
                        <b style={{ fontSize: 13.5 }}>{res.guidance.summary}</b>
                        <div className="lt-guide" style={{ marginTop: 10 }}><ol>{res.guidance.steps.map((s, i) => <li key={i}>{s}</li>)}</ol></div>
                        <div className="lt-note">{res.general_rule?.text}</div>
                        <div className="lt-note" style={{ fontSize: 11.5 }}>{res.disclaimer}</div>
                    </>
                )}
            </div>
        </div>
    );
}

/* ── Court fee ────────────────────────────────────────────────────────── */
const SUIT_TYPES = [
    ["money_recovery", "Recovery of money (ad valorem)"],
    ["specific_performance", "Specific performance (ad valorem)"],
    ["declaration_with_consequential", "Declaration + consequential relief"],
    ["declaration_simple", "Simple declaration (fixed)"],
    ["injunction", "Injunction (fixed)"],
    ["family", "Family suit (fixed)"],
    ["rent", "Rent / ejectment (fixed)"],
    ["appeal", "Appeal (fixed)"],
    ["writ", "Writ petition (fixed)"],
];
const PROVINCES = [["punjab", "Punjab"], ["sindh", "Sindh"], ["kp", "Khyber Pakhtunkhwa"], ["balochistan", "Balochistan"], ["islamabad", "Islamabad (ICT)"]];

function CourtFee() {
    const toast = useToast();
    const [claim, setClaim] = useState("");
    const [suit, setSuit] = useState("money_recovery");
    const [prov, setProv] = useState("punjab");
    const [res, setRes] = useState(null);
    const [busy, setBusy] = useState(false);
    const run = async () => {
        setBusy(true);
        const { data, error } = await courtFeeCalculate({ claim_value: toNum(claim), suit_type: suit, province: prov });
        setBusy(false);
        if (error || !data) return toast.show(errText(error, "Calculation failed"), "danger");
        setRes(data);
    };
    return (
        <div className="lt-grid">
            <div className="lt-card">
                <h2>Estimate the court fee</h2>
                <p className="lt-sub">Court Fees Act 1870 as applied in each province.</p>
                <label className="lt-lbl" htmlFor="cf-suit">Suit type</label>
                <select id="cf-suit" className="lt-in" value={suit} onChange={e => setSuit(e.target.value)}>
                    {SUIT_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
                <label className="lt-lbl" htmlFor="cf-prov">Province</label>
                <select id="cf-prov" className="lt-in" value={prov} onChange={e => setProv(e.target.value)}>
                    {PROVINCES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
                <label className="lt-lbl" htmlFor="cf-claim">Claim value (PKR)</label>
                <input id="cf-claim" className="lt-in" value={claim} onChange={e => setClaim(e.target.value)} placeholder="For ad valorem suits" />
                <button type="button" className="lt-btn" style={{ width: "100%", marginTop: 16 }} onClick={run} disabled={busy}>{busy ? "Calculating…" : "Calculate court fee"}</button>
            </div>
            <div className="lt-card" style={{ minHeight: 220 }}>
                {!res ? <div className="lt-empty">Enter the suit details to see the estimated court fee and its legal basis.</div> : (
                    <>
                        <div className="lt-note" style={{ marginTop: 0 }}>{res.suit_label} · {res.province}</div>
                        <div className="lt-big">Rs {res.court_fee.toLocaleString()}</div>
                        <div className="lt-note">{res.computation === "ad_valorem" ? "Ad valorem (on the claim value)" : "Fixed fee"} · rates as of {res.effective_as_of}</div>
                        <div className="lt-note">{res.legal_basis}</div>
                        {res.assumptions?.map((a, i) => <div key={i} className="lt-note">• {a}</div>)}
                        <div className="lt-warn">{res.verify}</div>
                    </>
                )}
            </div>
        </div>
    );
}

/* ── Inheritance (Faraid) ─────────────────────────────────────────────── */
const EMPTY_HEIRS = { husband: 0, wives: 0, sons: 0, daughters: 0, father: 0, mother: 0, predeceased_sons: 0, predeceased_daughters: 0, full_brothers: 0, full_sisters: 0 };

function Counter({ label, value, onChange, max = 20 }) {
    return (
        <div className="lt-count">
            <span>{label}</span>
            <div>
                <button type="button" aria-label={`Fewer ${label}`} onClick={() => onChange(Math.max(0, value - 1))}>−</button>
                <b className={value > 0 ? "on" : ""}>{value}</b>
                <button type="button" aria-label={`More ${label}`} onClick={() => onChange(Math.min(max, value + 1))}>+</button>
            </div>
        </div>
    );
}

function Inheritance() {
    const toast = useToast();
    const [heirs, setHeirs] = useState(EMPTY_HEIRS);
    const [estate, setEstate] = useState("");
    const [res, setRes] = useState(null);
    const [busy, setBusy] = useState(false);
    const [deceased, setDeceased] = useState("");
    const [died, setDied] = useState("");
    const [desc, setDesc] = useState("");
    const pdfKey = useRef(null);   // one Idempotency-Key per request (lib/intentKey.js)
    const set = (k) => (v) => setHeirs(p => ({ ...p, [k]: v }));
    const estateNum = toNum(estate);

    const run = async () => {
        if (!estateNum) return toast.show("Enter the estate value first", "warn");
        if (!Object.values(heirs).some(v => v > 0)) return toast.show("Select at least one heir", "warn");
        setBusy(true);
        const { data, error } = await inheritanceCalculate(estateNum, heirs);
        setBusy(false);
        if (error || !data) return toast.show(errText(error, "Calculation failed"), "danger");
        setRes(data);
    };
    const pdf = async () => {
        const req = { estate_value: estateNum, heirs, deceased_name: deceased, date_of_death: died, estate_description: desc };
        setBusy(true);
        const { data, error } = await inheritanceSettlementPdf(req, keyForIntent(pdfKey, req));
        setBusy(false);
        if (error || !data?.doc_id) return toast.show(errText(error, "PDF failed"), "danger");
        await downloadDocumentFile(data.doc_id, "inheritance-share-statement", { revisionId: data.revision_id, expectedPdfSha256: data.pdf_sha256 });
        toast.show("Share statement downloaded", "success");
    };

    return (
        <div className="lt-grid">
            <div className="lt-card">
                <h2>Surviving heirs</h2>
                <p className="lt-sub">Sunni (Hanafi) rules as applied in Pakistan, incl. MFLO 1961 s.4.</p>
                <div style={{ display: "grid", gap: 7 }}>
                    <Counter label="Husband" value={heirs.husband} max={1} onChange={v => setHeirs(p => ({ ...p, husband: v, wives: v ? 0 : p.wives }))} />
                    <Counter label="Wives" value={heirs.wives} max={4} onChange={v => setHeirs(p => ({ ...p, wives: v, husband: v ? 0 : p.husband }))} />
                    <Counter label="Sons" value={heirs.sons} onChange={set("sons")} />
                    <Counter label="Daughters" value={heirs.daughters} onChange={set("daughters")} />
                    <Counter label="Father" value={heirs.father} max={1} onChange={set("father")} />
                    <Counter label="Mother" value={heirs.mother} max={1} onChange={set("mother")} />
                    <Counter label="Predeceased sons (left children)" value={heirs.predeceased_sons} onChange={set("predeceased_sons")} />
                    <Counter label="Predeceased daughters (left children)" value={heirs.predeceased_daughters} onChange={set("predeceased_daughters")} />
                    <Counter label="Full brothers" value={heirs.full_brothers} onChange={set("full_brothers")} />
                    <Counter label="Full sisters" value={heirs.full_sisters} onChange={set("full_sisters")} />
                </div>
                <label className="lt-lbl" htmlFor="ih-estate">Total estate value (PKR)</label>
                <input id="ih-estate" className="lt-in" value={estate} onChange={e => setEstate(e.target.value)} placeholder="e.g. 10,000,000" />
                <button type="button" className="lt-btn" style={{ width: "100%", marginTop: 16 }} onClick={run} disabled={busy}>{busy ? "Calculating…" : "Calculate shares"}</button>
            </div>
            <div className="lt-card" style={{ minHeight: 300 }}>
                {!res ? <div className="lt-empty">Choose the surviving heirs and the estate value — each share appears here in rupees.</div> : (
                    <>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 10, marginBottom: 12 }}>
                            <h2>Distribution of Rs {res.estate_value.toLocaleString()}</h2>
                            <span className="lt-note" style={{ marginTop: 0 }}>{res.school}</span>
                        </div>
                        <div className="lt-table">
                            <div className="lt-row"><span>Heir</span><span>Share</span><span>%</span><span className="lt-num">Amount</span></div>
                            {res.breakdown.map((r, i) => (
                                <div key={i} className="lt-row">
                                    <span style={{ fontWeight: 600 }}>{r.heir}{r.note && <div className="lt-note" style={{ marginTop: 2, fontWeight: 400 }}>{r.note}</div>}</span>
                                    <span style={{ color: "var(--brand-text)", fontWeight: 700 }}>{r.fraction}</span>
                                    <span>{r.percentage}%</span>
                                    <span className="lt-num">Rs {r.amount.toLocaleString()}</span>
                                </div>
                            ))}
                        </div>
                        {res.notes?.map((n, i) => <div key={i} className="lt-note">• {n}</div>)}
                        {res.warnings?.map((w, i) => <div key={i} className="lt-warn">{w}</div>)}
                        <label className="lt-lbl" style={{ marginTop: 18 }}>For the share statement (optional)</label>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                            <input className="lt-in" value={deceased} onChange={e => setDeceased(e.target.value)} placeholder="Deceased's name" aria-label="Deceased's name" />
                            <input className="lt-in" value={died} onChange={e => setDied(e.target.value)} placeholder="Date of death" aria-label="Date of death" />
                        </div>
                        <input className="lt-in" style={{ marginTop: 8 }} value={desc} onChange={e => setDesc(e.target.value)} placeholder="Estate description, e.g. house in Gulberg, bank deposits" aria-label="Estate description" />
                        <button type="button" className="lt-btn" style={{ marginTop: 12 }} onClick={pdf} disabled={busy}>Download share statement (PDF)</button>
                        <div className="lt-note" style={{ fontSize: 11.5 }}>{res.disclaimer}</div>
                    </>
                )}
            </div>
        </div>
    );
}

/* ── Labour dues ──────────────────────────────────────────────────────── */
function LabourDues() {
    const toast = useToast();
    const [f, setF] = useState({ monthly_wage: "", years_of_service: "", extra_months: "", unpaid_months: "", overtime_hours: "", terminated_without_notice: false });
    const [res, setRes] = useState(null);
    const [busy, setBusy] = useState(false);
    const set = (k) => (e) => setF(p => ({ ...p, [k]: e.target.value }));
    const run = async () => {
        if (!toNum(f.monthly_wage)) return toast.show("Enter the monthly wage", "warn");
        setBusy(true);
        const { data, error } = await labourDuesCalculate({
            monthly_wage: toNum(f.monthly_wage), years_of_service: toNum(f.years_of_service), extra_months: toNum(f.extra_months),
            unpaid_months: toNum(f.unpaid_months), overtime_hours: toNum(f.overtime_hours), terminated_without_notice: f.terminated_without_notice,
        });
        setBusy(false);
        if (error || !data) return toast.show(errText(error, "Calculation failed"), "danger");
        setRes(data);
    };
    const field = (k, label, ph = "0") => (
        <div><label className="lt-lbl" htmlFor={`ld-${k}`}>{label}</label><input id={`ld-${k}`} className="lt-in" value={f[k]} onChange={set(k)} placeholder={ph} /></div>
    );
    return (
        <div className="lt-grid">
            <div className="lt-card">
                <h2>Employee's dues</h2>
                <p className="lt-sub">Gratuity, unpaid wages, overtime and notice pay.</p>
                {field("monthly_wage", "Monthly wage (PKR)", "e.g. 50,000")}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    {field("years_of_service", "Years of service")}
                    {field("extra_months", "+ Extra months")}
                    {field("unpaid_months", "Unpaid months")}
                    {field("overtime_hours", "Overtime hours")}
                </div>
                <label className="lt-check">
                    <input type="checkbox" checked={f.terminated_without_notice} onChange={e => setF(p => ({ ...p, terminated_without_notice: e.target.checked }))} />
                    Terminated without notice
                </label>
                <button type="button" className="lt-btn" style={{ width: "100%", marginTop: 16 }} onClick={run} disabled={busy}>{busy ? "Calculating…" : "Calculate dues"}</button>
            </div>
            <div className="lt-card" style={{ minHeight: 220 }}>
                {!res ? <div className="lt-empty">Enter the employment details to see each amount owed and the total.</div> : (
                    <>
                        <div className="lt-table">
                            <div className="lt-row two"><span>Item</span><span className="lt-num">Amount</span></div>
                            {res.breakdown.map((r, i) => (
                                <div key={i} className="lt-row two"><span>{r.item}</span><span className="lt-num">Rs {r.amount.toLocaleString()}</span></div>
                            ))}
                            <div className="lt-row two total"><span>Total owed</span><span className="lt-num">Rs {res.total.toLocaleString()}</span></div>
                        </div>
                        <div className="lt-note">{res.legal_basis}</div>
                        <div className="lt-note">{res.remedy}</div>
                        <div className="lt-note" style={{ fontSize: 11.5 }}>{res.disclaimer}</div>
                    </>
                )}
            </div>
        </div>
    );
}

/* ── Pages ────────────────────────────────────────────────────────────── */
function BailCheckerPage() {
    return (
        <Shell title="Bail Checker" sub="Bail classification and pre/post-arrest steps for common offences.">
            <BailChecker />
        </Shell>
    );
}

const CALCS = [["court", "Court Fee"], ["inheritance", "Inheritance"], ["labour", "Labour Dues"]];
function CalculatorsPage() {
    const [tab, setTab] = useState("court");
    const body = useMemo(() => ({ court: <CourtFee />, inheritance: <Inheritance />, labour: <LabourDues /> }), []);
    return (
        <Shell title="Calculators" sub="Court fee, Islamic inheritance shares and labour dues — worked out with the rule each one applies."
            tabs={CALCS} tab={tab} setTab={setTab}>
            {body[tab]}
        </Shell>
    );
}

export { BailCheckerPage, CalculatorsPage };
