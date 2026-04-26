'use client';
// Admin Case Tracking — paste your code here
import { useState } from "react";
import { Badge, Btn, Modal, Ic } from "./components.jsx";
import { IC } from "./icons.js";

export const CaseTracking = ({ T }) => {
  const [sf, setSf]         = useState("all");
  const [search, setSearch] = useState("");
  const [modal, setModal]   = useState(null);

  const cases = [
    { id:"CASE-2024-001", client:"Sarah Johnson", lawyer:"James Rivera",  type:"Criminal", status:"Under Hearing", filed:"Jan 20, 2024", next:"Apr 15, 2024", milestones:["Filed","Initial Hearing","Evidence"],         instructions:"Submit evidence by Apr 10. All exhibits must be certified copies.", hearingDate:"Apr 15, 2024 — RTC Branch 12, 9:00 AM", courtOrder:"Court ordered submission of employment contract originals." },
    { id:"CASE-2024-002", client:"Michael Chen",  lawyer:"Maria Santos",  type:"Family",   status:"Filed",         filed:"Feb 25, 2024", next:"Apr 20, 2024", milestones:["Filed"],                                       instructions:"Prepare all financial disclosure documents before next hearing.",   hearingDate:"Apr 20, 2024 — Family Court, 2:00 PM",  courtOrder:"" },
    { id:"CASE-2024-003", client:"Robert Kim",    lawyer:"James Rivera",  type:"Criminal", status:"Adjourned",     filed:"Jan 10, 2024", next:"May 1, 2024",  milestones:["Filed","Initial Hearing","Adjourned"],         instructions:"",                                                                 hearingDate:"May 1, 2024 — RTC Branch 8, 10:00 AM", courtOrder:"Case adjourned. Parties to submit position papers by Apr 25." },
    { id:"CASE-2024-004", client:"Aisha Patel",   lawyer:"Lisa Tan",      type:"Labor",    status:"Closed",        filed:"Oct 5, 2023",  next:null,           milestones:["Filed","Hearing 1","Hearing 2","Resolved","Closed"], instructions:"",                                                              hearingDate:null,                                    courtOrder:"Case resolved. Settlement enforced per court order dated Mar 1, 2024." },
  ];
  const sc = { "Filed":"info","Under Hearing":"warn","Adjourned":"danger","Closed":"gray" };
  const all5 = ["Filed","Initial Hearing","Evidence","Resolution","Closed"];
  const filtered = cases.filter(c => (sf==="all"||c.status===sf) && (c.id.toLowerCase().includes(search.toLowerCase())||c.client.toLowerCase().includes(search.toLowerCase())));

  return (
    <div>
      <div style={{ marginBottom: 26 }}>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, color: T.text, letterSpacing: -0.5 }}>Case Tracking</h1>
        <p style={{ margin: "4px 0 0", color: T.textMuted, fontSize: 14 }}>Monitor case timelines, statuses, milestones, and court instructions</p>
      </div>
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        {["all","Filed","Under Hearing","Adjourned","Closed"].map(s => (
          <button key={s} onClick={() => setSf(s)}
            style={{ padding: "7px 14px", borderRadius: 9, border: `1px solid ${sf===s ? T.primary : T.border}`, background: sf===s ? T.primaryGlow2 : "transparent", color: sf===s ? T.primary : T.textMuted, fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>
            {s==="all" ? "All" : s}
          </button>
        ))}
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center", background: T.inputBg, border: `1px solid ${T.border}`, borderRadius: 9, padding: "7px 12px" }}>
          <Ic d={IC.search} size={14} color={T.textFaint} />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search cases..."
            style={{ background: "none", border: "none", outline: "none", color: T.text, fontSize: 13, width: 150 }} />
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {filtered.map(c => (
          <div key={c.id} style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 14, padding: 20, boxShadow: T.shadowCard }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
              <div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
                  <span style={{ color: T.primary, fontWeight: 600, fontSize: 14 }}>{c.id}</span>
                  <Badge label={c.status} type={sc[c.status]} T={T} />
                  <Badge label={c.type} type="gray" T={T} />
                </div>
                <div style={{ color: T.textMuted, fontSize: 13 }}>{c.client} · <span style={{ color: T.textDim }}>{c.lawyer}</span></div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ color: T.textFaint, fontSize: 12 }}>Filed: {c.filed}</div>
                {c.next && <div style={{ color: T.warn, fontSize: 12, fontWeight: 600 }}>Next: {c.next}</div>}
              </div>
            </div>

            {/* Milestone tracker */}
            <div style={{ display: "flex", alignItems: "flex-start", gap: 0, marginBottom: 14 }}>
              {all5.map((m, i) => {
                const done = c.milestones.length > i;
                return (
                  <div key={m} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center" }}>
                    <div style={{ width: "100%", display: "flex", alignItems: "center" }}>
                      {i > 0 && <div style={{ flex: 1, height: 2, background: done ? T.success : T.border }} />}
                      <div style={{ width: 20, height: 20, borderRadius: "50%", background: done ? T.success : T.border, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                        {done && <Ic d={IC.check} size={10} color={T.mode === "dark" ? T.bg : "#fff"} sw={2.5} />}
                      </div>
                      {i < all5.length-1 && <div style={{ flex: 1, height: 2, background: c.milestones.length > i+1 ? T.success : T.border }} />}
                    </div>
                    <span style={{ color: done ? T.textMuted : T.textFaint, fontSize: 9.5, marginTop: 4, textAlign: "center" }}>{m}</span>
                  </div>
                );
              })}
            </div>

            {c.hearingDate && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", background: T.mode==="dark"?"rgba(255,200,87,0.08)":"rgba(176,120,0,0.06)", border: `1px solid ${T.warn}30`, borderRadius: 9, marginBottom: 8 }}>
                <Ic d={IC.clock} size={14} color={T.warn} />
                <div>
                  <span style={{ fontSize: 12, fontWeight: 700, color: T.warn }}>Next hearing: </span>
                  <span style={{ fontSize: 12, color: T.textDim }}>{c.hearingDate}</span>
                </div>
              </div>
            )}
            {c.instructions && (
              <div style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "9px 12px", background: T.mode==="dark"?"rgba(90,179,255,0.08)":"rgba(8,104,192,0.05)", border: `1px solid ${T.info}30`, borderRadius: 9, marginBottom: 8 }}>
                <Ic d={IC.file} size={14} color={T.info} />
                <div>
                  <span style={{ fontSize: 12, fontWeight: 700, color: T.info }}>Instruction: </span>
                  <span style={{ fontSize: 12, color: T.textDim }}>{c.instructions}</span>
                </div>
              </div>
            )}
            {c.courtOrder && (
              <div style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "9px 12px", background: T.mode==="dark"?"rgba(77,212,163,0.07)":"rgba(46,138,104,0.05)", border: `1px solid ${T.success}30`, borderRadius: 9, marginBottom: 8 }}>
                <Ic d={IC.checkCircle} size={14} color={T.success} />
                <div>
                  <span style={{ fontSize: 12, fontWeight: 700, color: T.success }}>Court order: </span>
                  <span style={{ fontSize: 12, color: T.textDim }}>{c.courtOrder}</span>
                </div>
              </div>
            )}

            <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center" }}>
              <button onClick={() => setModal(c)} style={{ display: "flex", gap: 6, alignItems: "center", padding: "7px 14px", border: `1px solid ${T.border}`, borderRadius: 9, background: "transparent", color: T.textMuted, fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>
                <Ic d={IC.eye} size={13} color={T.textMuted} /> View Details
              </button>
              <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
                {["Filed","Under Hearing","Adjourned","Closed"].map(s => (
                  <button key={s} style={{ padding: "5px 10px", borderRadius: 7, border: `1px solid ${c.status===s ? T.primary : T.border}`, background: c.status===s ? T.primaryGlow2 : "transparent", color: c.status===s ? T.primary : T.textFaint, fontSize: 11, fontWeight: 600, cursor: "pointer" }}>{s}</button>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>

      <Modal open={!!modal} onClose={() => setModal(null)} title="Case Details" T={T}>
        {modal && (
          <>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
              <span style={{ color: T.primary, fontWeight: 700, fontSize: 15 }}>{modal.id}</span>
              <Badge label={modal.status} type={sc[modal.status]} T={T} />
            </div>
            {[["Client",modal.client],["Lawyer",modal.lawyer],["Type",modal.type],["Filed",modal.filed],["Next Hearing",modal.next||"N/A"]].map(([k,v]) => (
              <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "9px 0", borderBottom: `1px solid ${T.border}40` }}>
                <span style={{ color: T.textMuted, fontSize: 13 }}>{k}</span>
                <span style={{ color: T.text, fontWeight: 600, fontSize: 13 }}>{v}</span>
              </div>
            ))}
            {modal.hearingDate   && <div style={{ marginTop: 10, padding: "9px 12px", background: `${T.warn}10`,    border: `1px solid ${T.warn}25`,    borderRadius: 8, fontSize: 12, color: T.textDim }}><strong style={{ color: T.warn    }}>Hearing:</strong> {modal.hearingDate}</div>}
            {modal.instructions  && <div style={{ marginTop: 8,  padding: "9px 12px", background: `${T.info}10`,    border: `1px solid ${T.info}25`,    borderRadius: 8, fontSize: 12, color: T.textDim }}><strong style={{ color: T.info    }}>Instruction:</strong> {modal.instructions}</div>}
            {modal.courtOrder    && <div style={{ marginTop: 8,  padding: "9px 12px", background: `${T.success}10`, border: `1px solid ${T.success}25`, borderRadius: 8, fontSize: 12, color: T.textDim }}><strong style={{ color: T.success }}>Court order:</strong> {modal.courtOrder}</div>}
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 18 }}>
              <Btn T={T} variant="ghost" onClick={() => setModal(null)}>Close</Btn>
            </div>
          </>
        )}
      </Modal>
    </div>
  );
};
