'use client';
// Admin Lawyer Monitoring — paste your code here
import { useState, useMemo } from "react";
import { StatCard, IconBox, Badge, Avatar, Btn, Modal, Ic, SortTh } from "./components.jsx";
import { IC } from "./icons.js";

export const LawyerMonitoring = ({ T }) => {
  const [modal, setModal] = useState(null);
  const [sort, setSort]   = useState({ field: "name", dir: "asc" });
  const handleSort = (field) => setSort(p => ({ field, dir: p.field === field && p.dir === "asc" ? "desc" : "asc" }));

  const rawLawyers = [
    { name: "Sarah Johnson", bar: "KA-4521", spec: "Property Law",  active: 12, completed: 45, rating: 4.8, satisfaction: 94, acceptance: 88, response: "1.8h" },
    { name: "Robert Brown",  bar: "KA-3892", spec: "Corporate Law", active: 15, completed: 62, rating: 4.6, satisfaction: 91, acceptance: 92, response: "2.1h" },
    { name: "James Rivera",  bar: "KA-7410", spec: "Criminal Law",  active:  9, completed: 38, rating: 4.9, satisfaction: 97, acceptance: 95, response: "1.2h" },
    { name: "Maria Santos",  bar: "KA-2201", spec: "Family Law",    active:  8, completed: 29, rating: 4.5, satisfaction: 89, acceptance: 85, response: "3.0h" },
    { name: "Lisa Tan",      bar: "KA-6234", spec: "Labor Law",     active:  7, completed: 54, rating: 4.7, satisfaction: 74, acceptance: 91, response: "2.4h" },
  ];

  const lawyers = useMemo(() => {
    return [...rawLawyers].sort((a, b) => {
      const av = a[sort.field], bv = b[sort.field];
      if (typeof av === "number") return sort.dir === "asc" ? av - bv : bv - av;
      return sort.dir === "asc" ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
    });
  }, [sort]);

  const satColor = (pct) => pct >= 90 ? T.success : pct >= 75 ? T.warn : T.danger;

  const total = lawyers.reduce((s, l) => s + l.active, 0);
  const avgR  = (lawyers.reduce((s, l) => s + l.rating, 0) / lawyers.length).toFixed(2);
  const avgS  = (lawyers.reduce((s, l) => s + l.satisfaction, 0) / lawyers.length).toFixed(1);

  return (
    <div>
      <div style={{ marginBottom: 26 }}>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, color: T.text, letterSpacing: -0.5 }}>Lawyer Monitoring</h1>
        <p style={{ margin: "4px 0 0", color: T.textMuted, fontSize: 14 }}>Track lawyer activity, performance metrics, and ratings</p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14, marginBottom: 22 }}>
        <StatCard label="Total Active Cases"  value={total}      sub={`Across ${lawyers.length} lawyers`} subColor={T.textMuted} iconEl={<IconBox icon={IC.briefcase} variant="Primary" T={T} size={42} />} T={T} />
        <StatCard label="Avg. Rating"         value={avgR}       sub="+0.12 this month"                   iconEl={<IconBox icon={IC.star}      variant="Warn"    T={T} size={42} />} T={T} />
        <StatCard label="Avg. Response Time"  value="2.4h"       sub="-15 min improvement"               iconEl={<IconBox icon={IC.clock}     variant="Info"    T={T} size={42} />} T={T} />
        <StatCard label="Avg. Satisfaction"   value={`${avgS}%`} sub="+2.3% from last quarter"           iconEl={<IconBox icon={IC.trendUp}   variant="Success" T={T} size={42} />} T={T} />
      </div>

      <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 14, overflow: "hidden", boxShadow: T.shadowCard }}>
        <div style={{ padding: "18px 22px", borderBottom: `1px solid ${T.border}` }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: T.text }}>Lawyer Performance Overview · click column headers to sort</div>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 700 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${T.border}`, background: T.mode === "dark" ? "rgba(255,255,255,0.02)" : "rgba(26,46,53,0.02)" }}>
                <SortTh label="Lawyer"          field="name"         sort={sort} onSort={handleSort} T={T} />
                <SortTh label="Specialization"  field="spec"         sort={sort} onSort={handleSort} T={T} />
                <SortTh label="Active/Done"     field="active"       sort={sort} onSort={handleSort} T={T} />
                <SortTh label="Rating"          field="rating"       sort={sort} onSort={handleSort} T={T} />
                <SortTh label="Satisfaction"    field="satisfaction" sort={sort} onSort={handleSort} T={T} />
                <SortTh label="Acceptance Rate" field="acceptance"   sort={sort} onSort={handleSort} T={T} />
                <th style={{ padding: "12px 18px", width: 50 }} />
              </tr>
            </thead>
            <tbody>
              {lawyers.map((l, i) => (
                <tr key={l.name} style={{ borderBottom: i < lawyers.length - 1 ? `1px solid ${T.border}40` : "none", transition: "background 0.15s" }}
                  onMouseEnter={e => e.currentTarget.style.background = T.cardHi}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <td style={{ padding: "14px 18px" }}>
                    <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                      <Avatar name={l.name} size={36} />
                      <div>
                        <div style={{ color: T.text, fontWeight: 600, fontSize: 14 }}>{l.name}</div>
                        <div style={{ color: T.textFaint, fontSize: 11 }}>Bar #{l.bar}</div>
                      </div>
                    </div>
                  </td>
                  <td style={{ padding: "14px 18px" }}><Badge label={l.spec} type="gray" T={T} /></td>
                  <td style={{ padding: "14px 18px" }}>
                    <span style={{ color: T.text, fontWeight: 700, fontSize: 14 }}>{l.active}</span>
                    <span style={{ color: T.textMuted, fontSize: 14 }}> / {l.completed}</span>
                  </td>
                  <td style={{ padding: "14px 18px" }}>
                    <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
                      <Ic d={IC.star} size={14} color={T.warn} fill={T.warn} sw={0} />
                      <span style={{ color: T.text, fontWeight: 700 }}>{l.rating}</span>
                    </div>
                  </td>
                  <td style={{ padding: "14px 18px", minWidth: 160 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <div style={{ flex: 1, height: 7, background: T.mode === "dark" ? "rgba(255,255,255,0.08)" : "rgba(26,46,53,0.1)", borderRadius: 4, overflow: "hidden" }}>
                        <div style={{ width: `${l.satisfaction}%`, height: "100%", background: satColor(l.satisfaction), borderRadius: 4, transition: "width 0.4s" }} />
                      </div>
                      <span style={{ color: satColor(l.satisfaction), fontSize: 12, fontWeight: 700, flexShrink: 0 }}>{l.satisfaction}%</span>
                    </div>
                  </td>
                  <td style={{ padding: "14px 18px", minWidth: 130 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <div style={{ flex: 1, height: 6, background: T.mode === "dark" ? "rgba(255,255,255,0.08)" : "rgba(26,46,53,0.1)", borderRadius: 3, overflow: "hidden" }}>
                        <div style={{ width: `${l.acceptance}%`, height: "100%", background: T.info, borderRadius: 3 }} />
                      </div>
                      <span style={{ color: T.textMuted, fontSize: 12, fontWeight: 600, flexShrink: 0 }}>{l.acceptance}%</span>
                    </div>
                  </td>
                  <td style={{ padding: "14px 18px" }}>
                    <button onClick={() => setModal(l)} style={{ background: "none", border: "none", cursor: "pointer" }}>
                      <Ic d={IC.eye} size={18} color={T.textMuted} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Modal open={!!modal} onClose={() => setModal(null)} title="Lawyer Details" T={T}>
        {modal && (
          <div>
            <div style={{ display: "flex", gap: 14, alignItems: "center", background: T.mode === "dark" ? T.surface : T.bg, borderRadius: 12, padding: 16, marginBottom: 18 }}>
              <Avatar name={modal.name} size={52} />
              <div>
                <div style={{ color: T.text, fontWeight: 700, fontSize: 15 }}>{modal.name}</div>
                <div style={{ color: T.textMuted, fontSize: 13 }}>{modal.spec} • Bar #{modal.bar}</div>
              </div>
            </div>
            {[["Active Cases", modal.active], ["Completed Cases", modal.completed], ["Rating", `${modal.rating}/5.0`], ["Satisfaction", `${modal.satisfaction}%`], ["Acceptance Rate", `${modal.acceptance}%`], ["Avg Response", modal.response]].map(([k, v]) => (
              <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "9px 0", borderBottom: `1px solid ${T.border}40` }}>
                <span style={{ color: T.textMuted, fontSize: 13 }}>{k}</span>
                <span style={{ color: T.text, fontWeight: 700, fontSize: 13 }}>{v}</span>
              </div>
            ))}
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 18 }}>
              <Btn T={T} variant="ghost" onClick={() => setModal(null)}>Close</Btn>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};
