'use client';
// Legal Tools — deterministic, high-trust utilities:
//   1. Islamic Inheritance (Faraid) Calculator + settlement PDF + demand letter
//   2. NADRA Succession Certificate Navigator (eligibility triage + checklist)
//   3. Instant Documents (one description → legal notice / FIR pack / FIA complaint)
import React, { useState } from "react";
import { useT } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import Ic from "./Ic.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput } from "@/components/shared/shared.jsx";
import {
    inheritanceCalculate,
    inheritanceSettlementPdf,
    inheritanceDemandLetter,
    wasiyyatCompute,
    wasiyyatPdf,
    courtFeeCalculate,
    labourDuesCalculate,
    labourDemandPdf,
    bailSearch,
    bailCheck,
    quickNotice,
    downloadDocument,
} from "@/lib/api.js";

const Lbl = ({ children }) => {
    const t = useT();
    return <div style={{ fontSize: 11.5, color: t.textMuted, marginBottom: 6, fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase" }}>{children}</div>;
};

/* Small +/- counter for heir counts */
const Counter = ({ label, value, onChange, max = 20 }) => {
    const t = useT();
    return (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "9px 12px", borderRadius: 10, border: `1.5px solid ${t.border}`, background: t.inputBg }}>
            <span style={{ fontSize: 13, color: t.text, fontWeight: 600 }}>{label}</span>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <button onClick={() => onChange(Math.max(0, value - 1))} style={{ width: 24, height: 24, borderRadius: 7, border: `1px solid ${t.border}`, background: t.card, color: t.text, cursor: "pointer", fontWeight: 700 }}>−</button>
                <span style={{ fontSize: 14, fontWeight: 700, color: value > 0 ? t.primary : t.textMuted, minWidth: 18, textAlign: "center" }}>{value}</span>
                <button onClick={() => onChange(Math.min(max, value + 1))} style={{ width: 24, height: 24, borderRadius: 7, border: `1px solid ${t.border}`, background: t.card, color: t.text, cursor: "pointer", fontWeight: 700 }}>+</button>
            </div>
        </div>
    );
};

/* ══════════════ TAB 1 — INHERITANCE CALCULATOR ══════════════ */
const EMPTY_HEIRS = { husband: 0, wives: 0, sons: 0, daughters: 0, father: 0, mother: 0, predeceased_sons: 0, predeceased_daughters: 0, full_brothers: 0, full_sisters: 0 };

function InheritanceCalc() {
    const t = useT();
    const toast = useToast();
    const [heirs, setHeirs] = useState(EMPTY_HEIRS);
    const [estate, setEstate] = useState("");
    const [result, setResult] = useState(null);
    const [busy, setBusy] = useState(false);
    // settlement PDF extras
    const [deceasedName, setDeceasedName] = useState("");
    const [dateOfDeath, setDateOfDeath] = useState("");
    const [estateDesc, setEstateDesc] = useState("");
    // demand letter modal
    const [demandOpen, setDemandOpen] = useState(false);
    const [demand, setDemand] = useState({ claimant_name: "", claimant_address: "", recipient_name: "", recipient_address: "", relation: "", share_fraction: "", share_amount: "" });

    const set = (k) => (v) => setHeirs(p => ({ ...p, [k]: v }));
    const estateNum = parseInt(String(estate).replace(/[^0-9]/g, "")) || 0;

    const run = async () => {
        if (!estateNum) return toast.show("Enter the estate value first", "warn");
        if (!Object.values(heirs).some(v => v > 0)) return toast.show("Select at least one heir", "warn");
        setBusy(true);
        const { data, error } = await inheritanceCalculate(estateNum, heirs);
        setBusy(false);
        if (error || !data) return toast.show("❌ " + (error?.detail || "Calculation failed"), "danger");
        setResult(data);
    };

    const settlementPdf = async () => {
        setBusy(true);
        const { data, error } = await inheritanceSettlementPdf({
            estate_value: estateNum, heirs,
            deceased_name: deceasedName, date_of_death: dateOfDeath, estate_description: estateDesc,
        });
        setBusy(false);
        if (error || !data?.doc_id) return toast.show("❌ " + (error?.detail || "PDF failed"), "danger");
        await downloadDocument(data.doc_id, "inheritance-share-statement");
        toast.show("✅ Share statement downloaded", "success");
    };

    const demandPdf = async () => {
        if (!demand.claimant_name || !demand.recipient_name) return toast.show("Claimant and recipient names are required", "warn");
        setBusy(true);
        const { data, error } = await inheritanceDemandLetter({
            ...demand,
            share_amount: parseInt(String(demand.share_amount).replace(/[^0-9]/g, "")) || null,
            deceased_name: deceasedName || "the deceased",
            date_of_death: dateOfDeath,
            estate_description: estateDesc,
        });
        setBusy(false);
        if (error || !data?.doc_id) return toast.show("❌ " + (error?.detail || "PDF failed"), "danger");
        await downloadDocument(data.doc_id, "inheritance-demand-notice");
        setDemandOpen(false);
        toast.show("✅ Demand notice downloaded", "success");
    };

    return (
        <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "minmax(300px, 380px) 1fr", gap: 18, alignItems: "start" }}>
            {/* left: inputs */}
            <Card style={{ padding: 18 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: t.text, marginBottom: 4 }}>Who survives the deceased?</div>
                <div style={{ fontSize: 11.5, color: t.textMuted, marginBottom: 14 }}>Sunni (Hanafi) rules as applied in Pakistan, incl. MFLO 1961 s.4</div>

                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
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

                <div style={{ marginTop: 14 }}>
                    <Lbl>Total estate value (PKR)</Lbl>
                    <ThemedInput value={estate} onChange={e => setEstate(e.target.value)} placeholder="e.g. 10,000,000" />
                </div>

                <div style={{ marginTop: 14 }}>
                    <BtnPrimary onClick={run} disabled={busy} style={{ width: "100%" }}>
                        {busy ? "Calculating…" : "Calculate Shares"}
                    </BtnPrimary>
                </div>
            </Card>

            {/* right: result */}
            <Card style={{ padding: 18, minHeight: 300 }}>
                {!result ? (
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: t.textMuted, gap: 10, padding: 40 }}>
                        <Ic n="scale" s={34} c={t.border} />
                        <div style={{ fontSize: 13, textAlign: "center" }}>Select the surviving heirs and estate value —<br />exact shares appear here, in rupees.</div>
                    </div>
                ) : (
                    <>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                            <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Distribution of PKR {result.estate_value.toLocaleString()}</div>
                            <span style={{ fontSize: 11, color: t.textMuted }}>{result.school}</span>
                        </div>

                        <div style={{ border: `1px solid ${t.border}`, borderRadius: 12, overflow: "hidden" }}>
                            <div style={{ display: "grid", gridTemplateColumns: "1fr 60px 60px 110px", gap: 0, padding: "8px 12px", background: t.inputBg, fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.4px" }}>
                                <span>Heir</span><span>Share</span><span>%</span><span style={{ textAlign: "right" }}>Amount</span>
                            </div>
                            {result.breakdown.map((r, i) => (
                                <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 60px 60px 110px", padding: "10px 12px", borderTop: `1px solid ${t.border}`, fontSize: 13, color: t.text, alignItems: "center" }}>
                                    <span style={{ fontWeight: 600 }}>{r.heir}{r.note && <div style={{ fontSize: 10.5, color: t.textMuted, fontWeight: 400 }}>{r.note}</div>}</span>
                                    <span style={{ color: t.primary, fontWeight: 700 }}>{r.fraction}</span>
                                    <span>{r.percentage}%</span>
                                    <span style={{ textAlign: "right", fontWeight: 700 }}>Rs {r.amount.toLocaleString()}</span>
                                </div>
                            ))}
                        </div>

                        {result.notes.map((n, i) => (
                            <div key={i} style={{ fontSize: 11.5, color: t.textMuted, marginTop: 8 }}>• {n}</div>
                        ))}
                        {result.warnings.map((w, i) => (
                            <div key={i} style={{ fontSize: 11.5, color: t.warn, marginTop: 8 }}>⚠ {w}</div>
                        ))}

                        <div style={{ marginTop: 16, paddingTop: 14, borderTop: `1px solid ${t.border}` }}>
                            <Lbl>For the PDF documents (optional)</Lbl>
                            <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
                                <ThemedInput value={deceasedName} onChange={e => setDeceasedName(e.target.value)} placeholder="Deceased's name" />
                                <ThemedInput value={dateOfDeath} onChange={e => setDateOfDeath(e.target.value)} placeholder="Date of death e.g. 12 March 2026" />
                            </div>
                            <ThemedInput value={estateDesc} onChange={e => setEstateDesc(e.target.value)} placeholder="Estate description e.g. house in Gulberg, bank deposits" />
                            <div style={{ display: "flex", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
                                <BtnPrimary onClick={settlementPdf} disabled={busy}>📥 Share Statement PDF</BtnPrimary>
                                <BtnOutline onClick={() => setDemandOpen(o => !o)}>✉️ My share is being withheld</BtnOutline>
                            </div>
                        </div>

                        {demandOpen && (
                            <div style={{ marginTop: 14, padding: 14, borderRadius: 12, border: `1.5px solid ${t.primary}40`, background: t.inputBg }}>
                                <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 10 }}>Generate a demand notice for your share</div>
                                <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                                    <ThemedInput value={demand.claimant_name} onChange={e => setDemand(p => ({ ...p, claimant_name: e.target.value }))} placeholder="Your full name *" />
                                    <ThemedInput value={demand.relation} onChange={e => setDemand(p => ({ ...p, relation: e.target.value }))} placeholder="Your relation e.g. daughter" />
                                    <ThemedInput value={demand.claimant_address} onChange={e => setDemand(p => ({ ...p, claimant_address: e.target.value }))} placeholder="Your address" />
                                    <ThemedInput value={demand.recipient_name} onChange={e => setDemand(p => ({ ...p, recipient_name: e.target.value }))} placeholder="Who is withholding it? *" />
                                    <ThemedInput value={demand.recipient_address} onChange={e => setDemand(p => ({ ...p, recipient_address: e.target.value }))} placeholder="Their address" />
                                    <ThemedInput value={demand.share_fraction} onChange={e => setDemand(p => ({ ...p, share_fraction: e.target.value }))} placeholder="Your share e.g. 7/40" />
                                </div>
                                <div style={{ marginTop: 10 }}>
                                    <BtnPrimary onClick={demandPdf} disabled={busy}>{busy ? "Generating…" : "Generate Demand Notice PDF"}</BtnPrimary>
                                </div>
                            </div>
                        )}

                        <div style={{ fontSize: 10.5, color: t.textMuted, marginTop: 14 }}>{result.disclaimer}</div>
                    </>
                )}
            </Card>
        </div>
    );
}

/* ══════════════ TAB — WASIYYAT (ISLAMIC WILL) ══════════════ */
const _STATUS = {
    valid: { c: "#10b981", label: "Within 1/3 — valid" },
    exceeds_one_third_needs_consent: { c: "#f59e0b", label: "Excess — needs heirs' consent" },
    to_heir_needs_consent: { c: "#f59e0b", label: "To an heir — needs heirs' consent" },
};

function WasiyyatBuilder() {
    const t = useT();
    const toast = useToast();
    const [gross, setGross] = useState("");
    const [funeral, setFuneral] = useState("");
    const [debts, setDebts] = useState("");
    const [bequests, setBequests] = useState([{ beneficiary: "", relation: "", amount: "", is_heir: false }]);
    const [heirs, setHeirs] = useState(EMPTY_HEIRS);
    const [result, setResult] = useState(null);
    const [busy, setBusy] = useState(false);
    const [willOpen, setWillOpen] = useState(false);
    const [will, setWill] = useState({ testator_name: "", testator_father_name: "", testator_cnic: "", testator_address: "", executor_name: "", executor_relation: "", guardian_name: "", funeral_instructions: "", witness1_name: "", witness2_name: "", place: "" });

    const set = (k) => (v) => setHeirs(p => ({ ...p, [k]: v }));
    const num = (s) => parseInt(String(s).replace(/[^0-9]/g, "")) || 0;
    const setW = (k) => (e) => setWill(p => ({ ...p, [k]: e.target.value }));

    const cleanBequests = () => bequests
        .filter(b => num(b.amount) > 0)
        .map(b => ({ beneficiary: b.beneficiary, relation: b.relation, amount: num(b.amount), is_heir: !!b.is_heir }));

    const payload = () => ({
        gross_estate: num(gross), funeral_expenses: num(funeral), debts: num(debts),
        bequests: cleanBequests(), heirs,
    });

    const compute = async () => {
        if (!num(gross)) return toast.show("Enter the gross estate value", "warn");
        setBusy(true);
        const { data, error } = await wasiyyatCompute(payload());
        setBusy(false);
        if (error || !data) return toast.show("❌ " + (error?.detail || "Calculation failed"), "danger");
        setResult(data);
    };

    const generateWill = async () => {
        setBusy(true);
        const { data, error } = await wasiyyatPdf({ ...payload(), ...will });
        setBusy(false);
        if (error || !data?.doc_id) return toast.show("❌ " + (error?.detail || "PDF failed"), "danger");
        await downloadDocument(data.doc_id, "wasiyyat-nama");
        toast.show("✅ Wasiyyat Nama downloaded", "success");
    };

    const money = (n) => "Rs " + Number(n || 0).toLocaleString();

    return (
        <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "minmax(300px, 400px) 1fr", gap: 18, alignItems: "start" }}>
            {/* left: inputs */}
            <Card style={{ padding: 18 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: t.text, marginBottom: 4 }}>The estate</div>
                <div style={{ fontSize: 11.5, color: t.textMuted, marginBottom: 14 }}>Funeral & debts are paid first; you may bequeath up to one-third of the rest.</div>

                <Lbl>Gross estate (PKR)</Lbl>
                <ThemedInput value={gross} onChange={e => setGross(e.target.value)} placeholder="e.g. 6,000,000" />
                <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 10 }}>
                    <div><Lbl>Funeral expenses</Lbl><ThemedInput value={funeral} onChange={e => setFuneral(e.target.value)} placeholder="0" /></div>
                    <div><Lbl>Debts owed</Lbl><ThemedInput value={debts} onChange={e => setDebts(e.target.value)} placeholder="0" /></div>
                </div>

                <div style={{ marginTop: 16, marginBottom: 6, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <Lbl>Bequests (wasiyyat)</Lbl>
                    <button onClick={() => setBequests(b => [...b, { beneficiary: "", relation: "", amount: "", is_heir: false }])}
                        style={{ fontSize: 11, fontWeight: 700, color: t.primary, background: "transparent", border: "none", cursor: "pointer" }}>+ Add</button>
                </div>
                {bequests.map((b, i) => (
                    <div key={i} style={{ border: `1px solid ${t.border}`, borderRadius: 10, padding: 10, marginBottom: 8 }}>
                        <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                            <ThemedInput value={b.beneficiary} onChange={e => setBequests(p => p.map((x, xi) => xi === i ? { ...x, beneficiary: e.target.value } : x))} placeholder="Beneficiary" />
                            <ThemedInput value={b.amount} onChange={e => setBequests(p => p.map((x, xi) => xi === i ? { ...x, amount: e.target.value } : x))} placeholder="Amount (PKR)" />
                        </div>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 8 }}>
                            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: t.textMuted, cursor: "pointer" }}>
                                <input type="checkbox" checked={b.is_heir} onChange={e => setBequests(p => p.map((x, xi) => xi === i ? { ...x, is_heir: e.target.checked } : x))} style={{ accentColor: t.primary }} />
                                Beneficiary is a legal heir
                            </label>
                            {bequests.length > 1 && (
                                <button onClick={() => setBequests(p => p.filter((_, xi) => xi !== i))} style={{ fontSize: 11, color: t.warn, background: "transparent", border: "none", cursor: "pointer" }}>Remove</button>
                            )}
                        </div>
                    </div>
                ))}

                <div style={{ marginTop: 12, fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 8 }}>Heirs (for the residue)</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <Counter label="Husband" value={heirs.husband} max={1} onChange={v => setHeirs(p => ({ ...p, husband: v, wives: v ? 0 : p.wives }))} />
                    <Counter label="Wives" value={heirs.wives} max={4} onChange={v => setHeirs(p => ({ ...p, wives: v, husband: v ? 0 : p.husband }))} />
                    <Counter label="Sons" value={heirs.sons} onChange={set("sons")} />
                    <Counter label="Daughters" value={heirs.daughters} onChange={set("daughters")} />
                    <Counter label="Father" value={heirs.father} max={1} onChange={set("father")} />
                    <Counter label="Mother" value={heirs.mother} max={1} onChange={set("mother")} />
                </div>

                <div style={{ marginTop: 14 }}>
                    <BtnPrimary onClick={compute} disabled={busy} style={{ width: "100%" }}>{busy ? "Calculating…" : "Compute Estate"}</BtnPrimary>
                </div>
            </Card>

            {/* right: result */}
            <Card style={{ padding: 18, minHeight: 300 }}>
                {!result ? (
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: t.textMuted, gap: 10, padding: 40 }}>
                        <Ic n="scale" s={34} c={t.border} />
                        <div style={{ fontSize: 13, textAlign: "center" }}>Enter the estate, debts and any bequests —<br />the lawful distribution appears here.</div>
                    </div>
                ) : (
                    <>
                        {/* waterfall */}
                        <div style={{ fontSize: 14, fontWeight: 700, color: t.text, marginBottom: 10 }}>Estate waterfall</div>
                        <div style={{ border: `1px solid ${t.border}`, borderRadius: 12, overflow: "hidden", marginBottom: 12 }}>
                            {[
                                ["Gross estate", result.gross_estate],
                                ["− Funeral expenses", result.funeral_expenses],
                                ["− Debts", result.debts],
                                ["Net estate", result.net_estate],
                                ["One-third limit", result.one_third_limit],
                                ["Valid bequests", result.valid_bequests_total],
                                ["Residue to heirs", result.residue],
                            ].map(([k, v], i) => (
                                <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "8px 12px", borderTop: i ? `1px solid ${t.border}` : "none", fontSize: 13, color: t.text, fontWeight: (k === "Net estate" || k === "Residue to heirs") ? 700 : 400 }}>
                                    <span>{k}</span><span>{money(v)}</span>
                                </div>
                            ))}
                        </div>

                        {result.bequests.length > 0 && (
                            <div style={{ marginBottom: 12 }}>
                                {result.bequests.map((b, i) => {
                                    const st = _STATUS[b.status] || _STATUS.valid;
                                    return (
                                        <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 0", fontSize: 12.5, color: t.text }}>
                                            <span>{b.beneficiary || "Bequest"} — {money(b.amount)}</span>
                                            <span style={{ fontSize: 10.5, fontWeight: 700, color: st.c }}>{st.label}</span>
                                        </div>
                                    );
                                })}
                            </div>
                        )}

                        {result.faraid?.breakdown?.length > 0 && (
                            <>
                                <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 6 }}>Residue by Faraid</div>
                                <div style={{ border: `1px solid ${t.border}`, borderRadius: 12, overflow: "hidden" }}>
                                    {result.faraid.breakdown.map((r, i) => (
                                        <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 60px 110px", padding: "9px 12px", borderTop: i ? `1px solid ${t.border}` : "none", fontSize: 13, color: t.text, alignItems: "center" }}>
                                            <span style={{ fontWeight: 600 }}>{r.heir}</span>
                                            <span style={{ color: t.primary, fontWeight: 700 }}>{r.fraction}</span>
                                            <span style={{ textAlign: "right", fontWeight: 700 }}>Rs {r.amount.toLocaleString()}</span>
                                        </div>
                                    ))}
                                </div>
                            </>
                        )}

                        {result.notes?.map((n, i) => <div key={i} style={{ fontSize: 11.5, color: t.textMuted, marginTop: 8 }}>• {n}</div>)}
                        {result.warnings?.map((w, i) => <div key={i} style={{ fontSize: 11.5, color: t.warn, marginTop: 8 }}>⚠ {w}</div>)}

                        <div style={{ marginTop: 16, paddingTop: 14, borderTop: `1px solid ${t.border}` }}>
                            <BtnOutline onClick={() => setWillOpen(o => !o)}>📜 Draft my Wasiyyat Nama (will)</BtnOutline>
                            {willOpen && (
                                <div style={{ marginTop: 12, padding: 14, borderRadius: 12, border: `1.5px solid ${t.primary}40`, background: t.inputBg }}>
                                    <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                                        <ThemedInput value={will.testator_name} onChange={setW("testator_name")} placeholder="Your full name" />
                                        <ThemedInput value={will.testator_father_name} onChange={setW("testator_father_name")} placeholder="Father's name" />
                                        <ThemedInput value={will.testator_cnic} onChange={setW("testator_cnic")} placeholder="CNIC" />
                                        <ThemedInput value={will.testator_address} onChange={setW("testator_address")} placeholder="Address" />
                                        <ThemedInput value={will.executor_name} onChange={setW("executor_name")} placeholder="Executor (wasi) name" />
                                        <ThemedInput value={will.executor_relation} onChange={setW("executor_relation")} placeholder="Executor relation" />
                                        <ThemedInput value={will.guardian_name} onChange={setW("guardian_name")} placeholder="Guardian for minors (optional)" />
                                        <ThemedInput value={will.place} onChange={setW("place")} placeholder="Place (city)" />
                                        <ThemedInput value={will.witness1_name} onChange={setW("witness1_name")} placeholder="Witness 1 name" />
                                        <ThemedInput value={will.witness2_name} onChange={setW("witness2_name")} placeholder="Witness 2 name" />
                                    </div>
                                    <div style={{ marginTop: 8 }}>
                                        <ThemedInput value={will.funeral_instructions} onChange={setW("funeral_instructions")} placeholder="Funeral instructions (optional)" />
                                    </div>
                                    <div style={{ marginTop: 12 }}>
                                        <BtnPrimary onClick={generateWill} disabled={busy}>{busy ? "Generating…" : "Generate Wasiyyat Nama PDF"}</BtnPrimary>
                                    </div>
                                </div>
                            )}
                        </div>

                        <div style={{ fontSize: 10.5, color: t.textMuted, marginTop: 14 }}>{result.disclaimer}</div>
                    </>
                )}
            </Card>
        </div>
    );
}

/* ══════════════ TAB — LEGAL CALCULATORS ══════════════ */
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

function CourtFeePanel() {
    const t = useT();
    const toast = useToast();
    const [claim, setClaim] = useState("");
    const [suit, setSuit] = useState("money_recovery");
    const [prov, setProv] = useState("punjab");
    const [res, setRes] = useState(null);
    const [busy, setBusy] = useState(false);
    const sel = { width: "100%", height: 42, borderRadius: 10, border: `1.5px solid ${t.border}`, background: t.inputBg, color: t.text, fontSize: 13.5, padding: "0 12px", fontFamily: "inherit" };

    const run = async () => {
        setBusy(true);
        const { data, error } = await courtFeeCalculate({ claim_value: parseInt(String(claim).replace(/[^0-9]/g, "")) || 0, suit_type: suit, province: prov });
        setBusy(false);
        if (error || !data) return toast.show("❌ " + (error?.detail || "Failed"), "danger");
        setRes(data);
    };

    return (
        <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "minmax(280px,360px) 1fr", gap: 18, alignItems: "start" }}>
            <Card style={{ padding: 18 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: t.text, marginBottom: 12 }}>Estimate the court fee</div>
                <Lbl>Suit type</Lbl>
                <select value={suit} onChange={e => setSuit(e.target.value)} style={{ ...sel, marginBottom: 10 }}>{SUIT_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
                <Lbl>Province</Lbl>
                <select value={prov} onChange={e => setProv(e.target.value)} style={{ ...sel, marginBottom: 10 }}>{PROVINCES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
                <Lbl>Claim value (PKR)</Lbl>
                <ThemedInput value={claim} onChange={e => setClaim(e.target.value)} placeholder="for ad valorem suits" />
                <div style={{ marginTop: 14 }}><BtnPrimary onClick={run} disabled={busy} style={{ width: "100%" }}>{busy ? "…" : "Calculate court fee"}</BtnPrimary></div>
            </Card>
            <Card style={{ padding: 18, minHeight: 200 }}>
                {!res ? (
                    <div style={{ color: t.textMuted, fontSize: 13, padding: 30, textAlign: "center" }}>Enter the suit details to see the estimated court fee and its legal basis.</div>
                ) : (
                    <>
                        <div style={{ fontSize: 12, color: t.textMuted }}>{res.suit_label} · {res.province}</div>
                        <div style={{ fontSize: 30, fontWeight: 800, color: t.primary, margin: "6px 0" }}>Rs {res.court_fee.toLocaleString()}</div>
                        <div style={{ fontSize: 11.5, color: t.textMuted }}>{res.computation === "ad_valorem" ? "Ad valorem (on claim value)" : "Fixed fee"} · rates as of {res.effective_as_of}</div>
                        <div style={{ marginTop: 10, fontSize: 11.5, color: t.textMuted }}>{res.legal_basis}</div>
                        {res.assumptions?.map((a, i) => <div key={i} style={{ fontSize: 11.5, color: t.textMuted, marginTop: 6 }}>• {a}</div>)}
                        <div style={{ marginTop: 12, padding: 10, borderRadius: 8, background: "#f59e0b12", border: `1px solid #f59e0b40`, fontSize: 11.5, color: t.text }}>⚠ {res.verify}</div>
                    </>
                )}
            </Card>
        </div>
    );
}

function LabourDuesPanel() {
    const t = useT();
    const toast = useToast();
    const [f, setF] = useState({ monthly_wage: "", years_of_service: "", extra_months: "", unpaid_months: "", overtime_hours: "", terminated_without_notice: false });
    const [res, setRes] = useState(null);
    const [busy, setBusy] = useState(false);
    const [dm, setDm] = useState({ worker_name: "", worker_address: "", employer_name: "", employer_address: "", designation: "", employment_period: "" });
    const [dmOpen, setDmOpen] = useState(false);
    const num = (k) => parseInt(String(f[k]).replace(/[^0-9]/g, "")) || 0;
    const set = (k) => (e) => setF(p => ({ ...p, [k]: e.target.value }));

    const payload = () => ({
        monthly_wage: num("monthly_wage"), years_of_service: num("years_of_service"), extra_months: num("extra_months"),
        unpaid_months: num("unpaid_months"), overtime_hours: num("overtime_hours"), terminated_without_notice: f.terminated_without_notice,
    });

    const run = async () => {
        if (!num("monthly_wage")) return toast.show("Enter the monthly wage", "warn");
        setBusy(true);
        const { data, error } = await labourDuesCalculate(payload());
        setBusy(false);
        if (error || !data) return toast.show("❌ " + (error?.detail || "Failed"), "danger");
        setRes(data);
    };

    const demand = async () => {
        if (!dm.worker_name || !dm.employer_name) return toast.show("Worker and employer names are required", "warn");
        setBusy(true);
        const { data, error } = await labourDemandPdf({ ...payload(), ...dm });
        setBusy(false);
        if (error || !data?.doc_id) return toast.show("❌ " + (error?.detail || "PDF failed"), "danger");
        await downloadDocument(data.doc_id, "labour-demand-notice");
        toast.show("✅ Demand notice downloaded", "success");
    };

    return (
        <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "minmax(280px,360px) 1fr", gap: 18, alignItems: "start" }}>
            <Card style={{ padding: 18 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: t.text, marginBottom: 12 }}>What are you owed?</div>
                <Lbl>Monthly wage (PKR)</Lbl>
                <ThemedInput value={f.monthly_wage} onChange={set("monthly_wage")} placeholder="e.g. 50,000" />
                <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 10 }}>
                    <div><Lbl>Years of service</Lbl><ThemedInput value={f.years_of_service} onChange={set("years_of_service")} placeholder="0" /></div>
                    <div><Lbl>+ extra months</Lbl><ThemedInput value={f.extra_months} onChange={set("extra_months")} placeholder="0" /></div>
                    <div><Lbl>Unpaid months</Lbl><ThemedInput value={f.unpaid_months} onChange={set("unpaid_months")} placeholder="0" /></div>
                    <div><Lbl>Overtime hours</Lbl><ThemedInput value={f.overtime_hours} onChange={set("overtime_hours")} placeholder="0" /></div>
                </div>
                <label style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 12, fontSize: 13, color: t.text, cursor: "pointer" }}>
                    <input type="checkbox" checked={f.terminated_without_notice} onChange={e => setF(p => ({ ...p, terminated_without_notice: e.target.checked }))} style={{ accentColor: t.primary }} />
                    Terminated without notice
                </label>
                <div style={{ marginTop: 14 }}><BtnPrimary onClick={run} disabled={busy} style={{ width: "100%" }}>{busy ? "…" : "Calculate dues"}</BtnPrimary></div>
            </Card>
            <Card style={{ padding: 18, minHeight: 200 }}>
                {!res ? (
                    <div style={{ color: t.textMuted, fontSize: 13, padding: 30, textAlign: "center" }}>Enter your employment details to see gratuity, unpaid wages, overtime and notice pay.</div>
                ) : (
                    <>
                        <div style={{ border: `1px solid ${t.border}`, borderRadius: 12, overflow: "hidden" }}>
                            {res.breakdown.map((r, i) => (
                                <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "10px 12px", borderTop: i ? `1px solid ${t.border}` : "none", fontSize: 13, color: t.text }}>
                                    <span>{r.item}</span><span style={{ fontWeight: 700 }}>Rs {r.amount.toLocaleString()}</span>
                                </div>
                            ))}
                            <div style={{ display: "flex", justifyContent: "space-between", padding: "12px", borderTop: `2px solid ${t.border}`, fontSize: 14, fontWeight: 800, color: t.primary }}>
                                <span>Total owed</span><span>Rs {res.total.toLocaleString()}</span>
                            </div>
                        </div>
                        <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 10 }}>{res.legal_basis}</div>
                        <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 6 }}>{res.remedy}</div>
                        <div style={{ marginTop: 12 }}>
                            <BtnOutline onClick={() => setDmOpen(o => !o)}>✉️ Generate demand letter</BtnOutline>
                            {dmOpen && (
                                <div style={{ marginTop: 12, padding: 14, borderRadius: 12, border: `1.5px solid ${t.primary}40`, background: t.inputBg }}>
                                    <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                                        <ThemedInput value={dm.worker_name} onChange={e => setDm(p => ({ ...p, worker_name: e.target.value }))} placeholder="Your name *" />
                                        <ThemedInput value={dm.designation} onChange={e => setDm(p => ({ ...p, designation: e.target.value }))} placeholder="Your designation" />
                                        <ThemedInput value={dm.worker_address} onChange={e => setDm(p => ({ ...p, worker_address: e.target.value }))} placeholder="Your address" />
                                        <ThemedInput value={dm.employment_period} onChange={e => setDm(p => ({ ...p, employment_period: e.target.value }))} placeholder="Employment period" />
                                        <ThemedInput value={dm.employer_name} onChange={e => setDm(p => ({ ...p, employer_name: e.target.value }))} placeholder="Employer name *" />
                                        <ThemedInput value={dm.employer_address} onChange={e => setDm(p => ({ ...p, employer_address: e.target.value }))} placeholder="Employer address" />
                                    </div>
                                    <div style={{ marginTop: 10 }}><BtnPrimary onClick={demand} disabled={busy}>{busy ? "…" : "Download demand notice"}</BtnPrimary></div>
                                </div>
                            )}
                        </div>
                        <div style={{ fontSize: 10.5, color: t.textMuted, marginTop: 12 }}>{res.disclaimer}</div>
                    </>
                )}
            </Card>
        </div>
    );
}

function CalculatorsTab() {
    const t = useT();
    const [sub, setSub] = useState("court");
    return (
        <div>
            <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
                {[["court", "Court Fee"], ["labour", "Labour Dues"]].map(([v, l]) => (
                    <button key={v} onClick={() => setSub(v)} style={{
                        padding: "7px 16px", borderRadius: 9, fontSize: 12.5, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                        border: `1.5px solid ${sub === v ? t.primary : t.border}`, background: sub === v ? t.primary + "15" : "transparent", color: sub === v ? t.primary : t.textMuted,
                    }}>{l}</button>
                ))}
            </div>
            {sub === "court" && <CourtFeePanel />}
            {sub === "labour" && <LabourDuesPanel />}
        </div>
    );
}

/* ══════════════ TAB 2 — NADRA SUCCESSION NAVIGATOR ══════════════ */
const NADRA_DOCS = [
    "Death certificate of the deceased (NADRA / Union Council)",
    "Family Registration Certificate (FRC) showing all legal heirs",
    "Original CNICs of all legal heirs (B-Forms for minors)",
    "Details of assets: bank accounts, plots, vehicles, shares, insurance",
    "No-objection / consent of all heirs (recorded at the NADRA counter with biometrics)",
];

const NADRA_STEPS = [
    "Any legal heir applies at a NADRA Succession Facilitation Unit (most NADRA mega-centres) or via nadra.gov.pk",
    "NADRA verifies the family tree from its own records and issues notices",
    "All heirs give consent with biometric verification",
    "A public notice runs for 14 days inviting objections",
    "If no objection is filed, the Succession Certificate (movable assets) or Letters of Administration (immovable property) is issued",
];

function NadraNavigator() {
    const t = useT();
    const [answers, setAnswers] = useState({});
    const questions = [
        { id: "muslim", q: "Was the deceased a Pakistani citizen (or NICOP holder)?", detail: "The NADRA route requires the deceased to be registered with NADRA." },
        { id: "uncontested", q: "Do ALL legal heirs agree on the distribution — no disputes?", detail: "One objection during the 14-day notice period moves the matter to court." },
        { id: "heirsKnown", q: "Are all heirs alive, known, and able to give biometric consent?", detail: "Minors need a guardian; heirs abroad can consent at Pakistani consulates/embassies." },
    ];
    const allAnswered = questions.every(q => answers[q.id] !== undefined);
    const eligible = allAnswered && questions.every(q => answers[q.id] === true);

    return (
        <div style={{ maxWidth: 760 }}>
            <Card style={{ padding: 18, marginBottom: 16 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: t.text, marginBottom: 4 }}>Do you need court — or just NADRA?</div>
                <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 16 }}>
                    Since the <b>Letters of Administration and Succession Certificates Act, 2021</b>, uncontested inheritance
                    no longer requires a 1–2 year court case. Answer three questions:
                </div>
                {questions.map(q => (
                    <div key={q.id} style={{ padding: "12px 0", borderTop: `1px solid ${t.border}` }}>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                            <div>
                                <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{q.q}</div>
                                <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 2 }}>{q.detail}</div>
                            </div>
                            <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                                {[true, false].map(val => (
                                    <button key={String(val)} onClick={() => setAnswers(p => ({ ...p, [q.id]: val }))} style={{
                                        padding: "6px 16px", borderRadius: 8, fontSize: 12, fontWeight: 700, cursor: "pointer",
                                        border: `1.5px solid ${answers[q.id] === val ? t.primary : t.border}`,
                                        background: answers[q.id] === val ? t.primary : "transparent",
                                        color: answers[q.id] === val ? "#fff" : t.textMuted,
                                    }}>{val ? "Yes" : "No"}</button>
                                ))}
                            </div>
                        </div>
                    </div>
                ))}
            </Card>

            {allAnswered && (eligible ? (
                <Card style={{ padding: 18, border: `1.5px solid ${t.primary}50` }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: t.primary, marginBottom: 10 }}>✅ You qualify for the NADRA route — no court case needed</div>
                    <div style={{ fontSize: 12.5, color: t.text, marginBottom: 12 }}>Typical time: <b>3–5 weeks</b> (vs 1–2 years in civil court). Fixed NADRA fee applies.</div>
                    <Lbl>Documents to gather</Lbl>
                    {NADRA_DOCS.map((d, i) => <div key={i} style={{ fontSize: 12.5, color: t.text, padding: "4px 0" }}>☐ {d}</div>)}
                    <div style={{ height: 10 }} />
                    <Lbl>The process</Lbl>
                    {NADRA_STEPS.map((sStep, i) => <div key={i} style={{ fontSize: 12.5, color: t.text, padding: "4px 0" }}><b style={{ color: t.primary }}>{i + 1}.</b> {sStep}</div>)}
                    <div style={{ fontSize: 11, color: t.textMuted, marginTop: 12 }}>
                        Use the Inheritance Calculator tab to compute each heir's exact share before you apply — NADRA
                        issues the certificate to all legal heirs per Islamic shares.
                    </div>
                </Card>
            ) : (
                <Card style={{ padding: 18, border: `1.5px solid ${t.warn}50` }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: t.warn, marginBottom: 10 }}>⚖️ Your case needs the civil court route</div>
                    <div style={{ fontSize: 12.5, color: t.text, lineHeight: 1.7 }}>
                        Because {answers.uncontested === false ? "the heirs are not in agreement" : answers.heirsKnown === false ? "not all heirs can consent" : "the deceased was not NADRA-registered"},
                        you'll need a <b>succession petition under the Succession Act, 1925</b> in the civil court of the district
                        where the deceased resided or the property is located. A lawyer is strongly recommended —
                        use the <b>Lawyers</b> tab to find a verified inheritance lawyer, and generate a
                        <b> demand notice</b> from the Calculator tab if a co-heir is withholding your share.
                    </div>
                </Card>
            ))}
        </div>
    );
}

/* ══════════════ TAB 3 — INSTANT DOCUMENTS ══════════════ */
const QUICK_TEMPLATES = [
    { id: "legal_notice", ico: "📮", name: "Legal Notice", desc: "Formal demand before going to court — unpaid dues, deposits, breach of contract" },
    { id: "fir_application", ico: "🚔", name: "FIR Application", desc: "Application to the SHO under s.154 CrPC to register a criminal case" },
    { id: "complaint_154_3", ico: "📢", name: "Complaint to SP", desc: "When the police station refuses to register your FIR — s.154(3) CrPC" },
    { id: "petition_22a", ico: "⚖️", name: "Justice of Peace Petition", desc: "Court order directing the police to register the FIR — s.22-A CrPC" },
    { id: "fia_cybercrime", ico: "💻", name: "FIA Cybercrime Complaint", desc: "Online fraud, hacking, blackmail, harassment — PECA 2016" },
];

function InstantDocs() {
    const t = useT();
    const toast = useToast();
    const [tmpl, setTmpl] = useState("legal_notice");
    const [text, setText] = useState("");
    const [busy, setBusy] = useState(false);
    const [done, setDone] = useState(null); // { doc_id, title, fields }

    const generate = async () => {
        if (text.trim().length < 10) return toast.show("Describe your situation in a sentence or two", "warn");
        setBusy(true);
        setDone(null);
        const { data, error } = await quickNotice(text.trim(), tmpl);
        setBusy(false);
        if (error || !data?.doc_id) return toast.show("❌ " + (error?.detail || "Generation failed"), "danger");
        setDone(data);
        toast.show("✅ Document ready", "success");
    };

    const selected = QUICK_TEMPLATES.find(q => q.id === tmpl);

    return (
        <div style={{ maxWidth: 860 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10, marginBottom: 16 }}>
                {QUICK_TEMPLATES.map(q => (
                    <div key={q.id} onClick={() => { setTmpl(q.id); setDone(null); }} style={{
                        padding: "12px 12px", borderRadius: 12, cursor: "pointer", transition: "all .15s",
                        border: `1.5px solid ${tmpl === q.id ? t.primary : t.border}`,
                        background: tmpl === q.id ? `${t.primary}12` : t.surface,
                    }}>
                        <div style={{ fontSize: 20 }}>{q.ico}</div>
                        <div style={{ fontSize: 12.5, fontWeight: 700, color: tmpl === q.id ? t.primary : t.text, marginTop: 4 }}>{q.name}</div>
                    </div>
                ))}
            </div>

            <Card style={{ padding: 18 }}>
                <div style={{ fontSize: 13.5, fontWeight: 700, color: t.text, marginBottom: 2 }}>{selected.ico} {selected.name}</div>
                <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 12 }}>{selected.desc}</div>

                <Lbl>Describe what happened — names, places, dates, amounts</Lbl>
                <textarea
                    value={text}
                    onChange={e => setText(e.target.value)}
                    rows={4}
                    placeholder={tmpl === "fia_cybercrime"
                        ? "e.g. Someone hacked my JazzCash account on 20 June and stole Rs 85,000, then started blackmailing me on WhatsApp from 0300-1234567…"
                        : tmpl === "legal_notice"
                            ? "e.g. My landlord Malik Riaz of Model Town Lahore has not returned my Rs 200,000 security deposit two months after I vacated…"
                            : "e.g. On 15 June my shop in Anarkali was broken into and goods worth Rs 500,000 stolen. The police station Old Anarkali is not registering my FIR…"}
                    style={{
                        width: "100%", boxSizing: "border-box", resize: "vertical",
                        background: t.inputBg, border: `1.5px solid ${t.border}`, borderRadius: 12,
                        color: t.text, fontSize: 13, padding: "12px 14px", outline: "none", fontFamily: "inherit", lineHeight: 1.6,
                    }}
                />
                <div style={{ display: "flex", gap: 10, marginTop: 12, alignItems: "center", flexWrap: "wrap" }}>
                    <BtnPrimary onClick={generate} disabled={busy}>
                        {busy ? "✨ Drafting…" : "✨ Generate Document"}
                    </BtnPrimary>
                    {done && (
                        <BtnOutline onClick={() => downloadDocument(done.doc_id, done.title || "document")}>
                            📥 Download {done.title}
                        </BtnOutline>
                    )}
                </div>

                {done?.fields && (
                    <div style={{ marginTop: 14, padding: 12, borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}` }}>
                        <Lbl>What the AI understood — check before sending</Lbl>
                        {Object.entries(done.fields).filter(([, v]) => v).map(([k, v]) => (
                            <div key={k} style={{ fontSize: 12, color: t.text, padding: "3px 0" }}>
                                <span style={{ color: t.textMuted }}>{k.replace(/_/g, " ")}:</span> {String(v).slice(0, 160)}
                            </div>
                        ))}
                        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 8 }}>
                            Something wrong? Edit your description above and regenerate.
                        </div>
                    </div>
                )}

                {tmpl !== "legal_notice" && (
                    <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 14, lineHeight: 1.6 }}>
                        <b>The escalation ladder:</b> ① FIR application to the SHO → ② if refused, complaint to the SP under
                        s.154(3) → ③ if still refused, petition the Justice of Peace under s.22-A. Generate each step as you need it.
                        For online offences, the FIA complaint can also be filed at complaint.fia.gov.pk or helpline 1991.
                    </div>
                )}
            </Card>
        </div>
    );
}

/* ══════════════ TAB — BAIL CHECKER ══════════════ */
const Chip = ({ children, tone }) => {
    const t = useT();
    const map = {
        good: { bg: "#16a34a18", fg: "#16a34a", bd: "#16a34a55" },
        bad: { bg: "#dc262618", fg: "#dc2626", bd: "#dc262655" },
        warn: { bg: "#d9770618", fg: "#d97706", bd: "#d9770655" },
        neutral: { bg: t.inputBg, fg: t.textMuted, bd: t.border },
    };
    const c = map[tone] || map.neutral;
    return <span style={{ display: "inline-block", padding: "3px 9px", borderRadius: 7, fontSize: 11, fontWeight: 700, background: c.bg, color: c.fg, border: `1px solid ${c.bd}` }}>{children}</span>;
};

function BailCheckerTab() {
    const t = useT();
    const toast = useToast();
    const [q, setQ] = useState("");
    const [results, setResults] = useState([]);
    const [searched, setSearched] = useState(false);
    const [busy, setBusy] = useState(false);
    const [selected, setSelected] = useState(null); // the raw offence chosen
    const [arrested, setArrested] = useState(true);
    const [res, setRes] = useState(null); // /bail/check response

    const runSearch = async () => {
        if (!q.trim()) return toast.show("Type an offence or a section number (e.g. 302 or 'theft')", "warn");
        setBusy(true);
        const { data, error } = await bailSearch(q.trim());
        setBusy(false);
        if (error) return toast.show("❌ " + (error?.detail || "Search failed"), "danger");
        setSearched(true);
        setResults(data?.results || []);
        setRes(null); setSelected(null);
    };

    const runCheck = async (offence, isArrested) => {
        setSelected(offence);
        setBusy(true);
        const { data, error } = await bailCheck({ law: offence.law, section: offence.section, arrested: isArrested });
        setBusy(false);
        if (error || !data) return toast.show("❌ " + (error?.detail || "Check failed"), "danger");
        setRes(data);
    };

    const boolChip = (v, yes, no) =>
        v === null || v === undefined ? <Chip tone="neutral">depends</Chip> : v ? <Chip tone="good">{yes}</Chip> : <Chip tone="bad">{no}</Chip>;

    return (
        <div style={{ maxWidth: 820 }}>
            <Card style={{ padding: 18, marginBottom: 16 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: t.text, marginBottom: 4 }}>Is this offence bailable?</div>
                <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 14 }}>
                    Look up a common Pakistani offence by section number (e.g. <b>302</b>, <b>489-F</b>) or by name (e.g. <b>theft</b>, <b>cheque</b>)
                    to see its bail classification under the Second Schedule of the CrPC 1898, plus pre/post-arrest bail steps.
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                    <div style={{ flex: 1 }}>
                        <ThemedInput value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === "Enter" && runSearch()} placeholder="Section number or offence name…" />
                    </div>
                    <BtnPrimary onClick={runSearch} disabled={busy}>{busy && !selected ? "…" : "Search"}</BtnPrimary>
                </div>
            </Card>

            {searched && results.length === 0 && (
                <Card style={{ padding: 18, marginBottom: 16 }}>
                    <div style={{ fontSize: 13, color: t.textMuted }}>
                        No matching offence in the reference list. Confirm the exact section against the Second Schedule of the CrPC 1898, or consult a criminal lawyer.
                    </div>
                </Card>
            )}

            {results.length > 0 && (
                <Card style={{ padding: 8, marginBottom: 16 }}>
                    {results.map(o => {
                        const active = selected && selected.id === o.id;
                        return (
                            <button key={o.id} onClick={() => runCheck(o, arrested)} style={{
                                display: "block", width: "100%", textAlign: "left", padding: "11px 12px", borderRadius: 10,
                                border: `1.5px solid ${active ? t.primary : "transparent"}`, background: active ? t.primary + "12" : "transparent",
                                cursor: "pointer", fontFamily: "inherit", marginBottom: 2,
                            }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                                    <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>{o.law} s.{o.section}</span>
                                    <span style={{ fontSize: 13, color: t.text }}>— {o.title}</span>
                                    {boolChip(o.bailable, "bailable", "non-bailable")}
                                    {o.confidence === "verify" && <Chip tone="warn">verify</Chip>}
                                </div>
                                <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 3 }}>{o.punishment} · {o.court}</div>
                            </button>
                        );
                    })}
                </Card>
            )}

            {res && (
                <Card style={{ padding: 18 }}>
                    {res.found ? (
                        <>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
                                <span style={{ fontSize: 15, fontWeight: 800, color: t.text }}>{res.offence.law} s.{res.offence.section}</span>
                                <span style={{ fontSize: 13, color: t.textMuted }}>{res.offence.title}</span>
                            </div>
                            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
                                {boolChip(res.offence.bailable, "bailable", "non-bailable")}
                                {boolChip(res.offence.cognizable, "cognizable", "non-cognizable")}
                                {boolChip(res.offence.compoundable, "compoundable", "non-compoundable")}
                                {res.offence.prohibitory && <Chip tone="bad">prohibitory clause (s.497(1))</Chip>}
                                <Chip tone={res.confidence === "verify" ? "warn" : "neutral"}>{res.confidence === "verify" ? "verify classification" : "established"}</Chip>
                            </div>

                            {/* Arrested toggle — re-runs the guidance */}
                            <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
                                {[["Not yet arrested", false], ["Already arrested", true]].map(([lbl, v]) => (
                                    <button key={String(v)} onClick={() => { setArrested(v); runCheck(res.offence, v); }} style={{
                                        padding: "6px 14px", borderRadius: 8, fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                                        border: `1.5px solid ${arrested === v ? t.primary : t.border}`, background: arrested === v ? t.primary + "15" : "transparent", color: arrested === v ? t.primary : t.textMuted,
                                    }}>{lbl}</button>
                                ))}
                            </div>

                            <div style={{ padding: 14, borderRadius: 12, border: `1.5px solid ${t.primary}30`, background: t.inputBg }}>
                                <div style={{ fontSize: 13.5, fontWeight: 700, color: t.text, marginBottom: 8 }}>{res.guidance.summary}</div>
                                {res.guidance.sections?.length > 0 && (
                                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
                                        {res.guidance.sections.map((s, i) => <Chip key={i} tone="neutral">{s}</Chip>)}
                                    </div>
                                )}
                                <ol style={{ margin: 0, paddingLeft: 18 }}>
                                    {res.guidance.steps.map((s, i) => (
                                        <li key={i} style={{ fontSize: 12.5, color: t.text, marginBottom: 6, lineHeight: 1.5 }}>{s}</li>
                                    ))}
                                </ol>
                            </div>

                            {res.offence.note && <div style={{ fontSize: 12, color: t.textMuted, marginTop: 12 }}>⚠️ {res.offence.note}</div>}
                            <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 10 }}>{res.legal_basis}</div>
                            <div style={{ fontSize: 10.5, color: t.textMuted, marginTop: 8, lineHeight: 1.5 }}>{res.disclaimer}</div>
                        </>
                    ) : (
                        <>
                            <div style={{ fontSize: 13, color: t.text, marginBottom: 8 }}>{res.guidance.summary}</div>
                            <ol style={{ margin: 0, paddingLeft: 18 }}>
                                {res.guidance.steps.map((s, i) => <li key={i} style={{ fontSize: 12.5, color: t.text, marginBottom: 6 }}>{s}</li>)}
                            </ol>
                            <div style={{ fontSize: 12, color: t.textMuted, marginTop: 12 }}>{res.general_rule?.text}</div>
                            <div style={{ fontSize: 10.5, color: t.textMuted, marginTop: 10 }}>{res.disclaimer}</div>
                        </>
                    )}
                </Card>
            )}
        </div>
    );
}

/* ══════════════ MODULE SHELL ══════════════ */
const TABS = [
    { id: "calc", label: "Inheritance Calculator", icon: "scale" },
    { id: "wasiyyat", label: "Wasiyyat (Will)", icon: "scale" },
    { id: "calculators", label: "Calculators", icon: "scale" },
    { id: "bail", label: "Bail Checker", icon: "shield" },
    { id: "nadra", label: "Succession Navigator", icon: "map" },
    { id: "instant", label: "Instant Documents", icon: "zap" },
];

const ModTools = () => {
    const t = useT();
    const [tab, setTab] = useState("calc");

    return (
        <div>
            <div style={{ display: "flex", gap: 8, marginBottom: 18, flexWrap: "wrap" }}>
                {TABS.map(x => (
                    <button key={x.id} onClick={() => setTab(x.id)} style={{
                        display: "flex", alignItems: "center", gap: 8, padding: "9px 16px", borderRadius: 10,
                        border: `1.5px solid ${tab === x.id ? t.primary : t.border}`,
                        background: tab === x.id ? `${t.primary}15` : "transparent",
                        color: tab === x.id ? t.primary : t.textMuted,
                        fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                    }}>
                        <Ic n={x.icon} s={15} c={tab === x.id ? t.primary : t.textMuted} /> {x.label}
                    </button>
                ))}
            </div>
            {tab === "calc" && <InheritanceCalc />}
            {tab === "wasiyyat" && <WasiyyatBuilder />}
            {tab === "calculators" && <CalculatorsTab />}
            {tab === "bail" && <BailCheckerTab />}
            {tab === "nadra" && <NadraNavigator />}
            {tab === "instant" && <InstantDocs />}
        </div>
    );
};

export default ModTools;
