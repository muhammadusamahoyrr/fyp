'use client';
import { useState, useMemo, useEffect } from "react";
import { StatCard, IconBox, Badge, Avatar, Btn, Modal, Ic, SortTh, EmptyState } from "./components.jsx";
import { IC } from "./icons.js";
import { adminListLawyers } from "@/lib/api.js";

export const LawyerMonitoring = ({ T }) => {
  const [lawyers, setLawyers]   = useState([]);
  const [loading, setLoading]   = useState(true);
  const [modal, setModal]       = useState(null);
  const [sort, setSort]         = useState({ field: "full_name", dir: "asc" });
  const handleSort = (field) => setSort(p => ({ field, dir: p.field === field && p.dir === "asc" ? "desc" : "asc" }));

  useEffect(() => {
    adminListLawyers().then(({ data, error }) => {
      if (!error && Array.isArray(data)) setLawyers(data);
      setLoading(false);
    });
  }, []);

  const sorted = useMemo(() => {
    return [...lawyers].sort((a, b) => {
      const av = a[sort.field] ?? "", bv = b[sort.field] ?? "";
      if (typeof av === "number") return sort.dir === "asc" ? av - bv : bv - av;
      return sort.dir === "asc" ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
    });
  }, [lawyers, sort]);

  const totalActive   = lawyers.reduce((s, l) => s + (l.active_cases || 0), 0);
  const avgRating     = lawyers.length ? (lawyers.reduce((s, l) => s + (l.rating || 0), 0) / lawyers.length).toFixed(2) : "—";
  const verified      = lawyers.filter(l => l.kyc_verified).length;

  const ratingColor = (r) => r >= 4.5 ? T.success : r >= 3.5 ? T.warn : T.danger;

  const specLabel = (specs) => {
    if (!specs?.length) return "—";
    return specs[0].replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  };

  return (
    <div>
      <div style={{ marginBottom: 26 }}>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, color: T.text, letterSpacing: -0.5 }}>Lawyer Monitoring</h1>
        <p style={{ margin: "4px 0 0", color: T.textMuted, fontSize: 14 }}>Track lawyer activity, performance metrics, and ratings</p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 14, marginBottom: 22 }}>
        <StatCard label="Total Active Cases"  value={loading ? "…" : totalActive}  sub={`Across ${lawyers.length} lawyers`}  iconEl={<IconBox icon={IC.briefcase} variant="Primary" T={T} size={42} />} T={T} />
        <StatCard label="Avg. Rating"         value={loading ? "…" : avgRating}     sub={`${lawyers.filter(l => l.total_reviews > 0).length} reviewed`} iconEl={<IconBox icon={IC.star}      variant="Warn"    T={T} size={42} />} T={T} />
        <StatCard label="KYC Verified"        value={loading ? "…" : verified}      sub={`${lawyers.length - verified} pending`} iconEl={<IconBox icon={IC.checkCircle} variant="Success" T={T} size={42} />} T={T} />
        <StatCard label="Total Lawyers"       value={loading ? "…" : lawyers.length} sub="Registered on platform" iconEl={<IconBox icon={IC.balance} variant="Info" T={T} size={42} />} T={T} />
      </div>

      <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 14, overflow: "hidden", boxShadow: T.shadowCard }}>
        <div style={{ padding: "18px 22px", borderBottom: `1px solid ${T.border}` }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: T.text }}>Lawyer Performance Overview · click column headers to sort</div>
        </div>

        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: T.textMuted, fontSize: 14 }}>Loading lawyers…</div>
        ) : sorted.length === 0 ? (
          <EmptyState T={T} icon={IC.balance} title="No lawyers registered" sub="Lawyers will appear here once they register." />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 700 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${T.border}`, background: T.mode === "dark" ? "rgba(255,255,255,0.02)" : "rgba(26,46,53,0.02)" }}>
                  <SortTh label="Lawyer"         field="full_name"      sort={sort} onSort={handleSort} T={T} />
                  <SortTh label="Specialization" field="specializations" sort={sort} onSort={handleSort} T={T} />
                  <SortTh label="Active/Done"    field="active_cases"   sort={sort} onSort={handleSort} T={T} />
                  <SortTh label="Rating"         field="rating"         sort={sort} onSort={handleSort} T={T} />
                  <th style={{ padding: "12px 18px", textAlign: "left", color: T.textMuted, fontSize: 12, fontWeight: 600 }}>KYC</th>
                  <SortTh label="Experience"     field="experience_years" sort={sort} onSort={handleSort} T={T} />
                  <th style={{ padding: "12px 18px", width: 50 }} />
                </tr>
              </thead>
              <tbody>
                {sorted.map((l, i) => (
                  <tr key={l._id} style={{ borderBottom: i < sorted.length - 1 ? `1px solid ${T.border}40` : "none", transition: "background 0.15s" }}
                    onMouseEnter={e => e.currentTarget.style.background = T.cardHi}
                    onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                    <td style={{ padding: "14px 18px" }}>
                      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                        <Avatar name={l.full_name} size={36} />
                        <div>
                          <div style={{ color: T.text, fontWeight: 600, fontSize: 14 }}>{l.full_name}</div>
                          <div style={{ color: T.textFaint, fontSize: 11 }}>{l.bar_number ? `Bar #${l.bar_number}` : "No bar # on file"}</div>
                        </div>
                      </div>
                    </td>
                    <td style={{ padding: "14px 18px" }}><Badge label={specLabel(l.specializations)} type="gray" T={T} /></td>
                    <td style={{ padding: "14px 18px" }}>
                      <span style={{ color: T.text, fontWeight: 700, fontSize: 14 }}>{l.active_cases}</span>
                      <span style={{ color: T.textMuted, fontSize: 14 }}> / {l.completed_cases}</span>
                    </td>
                    <td style={{ padding: "14px 18px" }}>
                      {l.total_reviews > 0 ? (
                        <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
                          <Ic d={IC.star} size={14} color={ratingColor(l.rating)} fill={ratingColor(l.rating)} sw={0} />
                          <span style={{ color: ratingColor(l.rating), fontWeight: 700 }}>{l.rating.toFixed(1)}</span>
                          <span style={{ color: T.textFaint, fontSize: 11 }}>({l.total_reviews})</span>
                        </div>
                      ) : (
                        <span style={{ color: T.textFaint, fontSize: 12 }}>No reviews</span>
                      )}
                    </td>
                    <td style={{ padding: "14px 18px" }}>
                      <Badge label={l.kyc_verified ? "Verified" : "Pending"} type={l.kyc_verified ? "success" : "warn"} T={T} />
                    </td>
                    <td style={{ padding: "14px 18px", color: T.textMuted, fontSize: 13 }}>
                      {l.experience_years > 0 ? `${l.experience_years} yr${l.experience_years !== 1 ? "s" : ""}` : "—"}
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
        )}
      </div>

      <Modal open={!!modal} onClose={() => setModal(null)} title="Lawyer Details" T={T}>
        {modal && (
          <div>
            <div style={{ display: "flex", gap: 14, alignItems: "center", background: T.mode === "dark" ? T.surface : T.bg, borderRadius: 12, padding: 16, marginBottom: 18 }}>
              <Avatar name={modal.full_name} size={52} />
              <div>
                <div style={{ color: T.text, fontWeight: 700, fontSize: 15 }}>{modal.full_name}</div>
                <div style={{ color: T.textMuted, fontSize: 13 }}>{specLabel(modal.specializations)} {modal.bar_number ? `• Bar #${modal.bar_number}` : ""}</div>
                <div style={{ marginTop: 6, display: "flex", gap: 6 }}>
                  <Badge label={modal.kyc_verified ? "KYC Verified" : "Pending KYC"} type={modal.kyc_verified ? "success" : "warn"} T={T} />
                  <Badge label={modal.is_active ? "Active" : "Inactive"} type={modal.is_active ? "info" : "gray"} T={T} />
                </div>
              </div>
            </div>
            {[
              ["Email",             modal.email],
              ["Active Cases",      modal.active_cases],
              ["Completed Cases",   modal.completed_cases],
              ["Rating",            modal.total_reviews > 0 ? `${modal.rating.toFixed(1)}/5.0 (${modal.total_reviews} reviews)` : "No reviews yet"],
              ["Experience",        modal.experience_years > 0 ? `${modal.experience_years} years` : "—"],
              ["Specializations",   modal.specializations?.map(s => s.replace(/_/g, " ")).join(", ") || "—"],
            ].map(([k, v]) => (
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
