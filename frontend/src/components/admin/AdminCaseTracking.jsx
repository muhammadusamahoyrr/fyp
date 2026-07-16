'use client';
import { useState, useEffect, useCallback } from "react";
import { Badge, Btn, Modal, Ic, EmptyState, Paginator } from "./components.jsx";
import { IC } from "./icons.js";
import { adminListCases, adminUpdateCaseStatus } from "@/lib/api.js";

// Backend status → display label + badge type
const STATUS_META = {
  open:           { label: "Open",           type: "info"    },
  in_progress:    { label: "In Progress",    type: "warn"    },
  pending_lawyer: { label: "Pending Lawyer", type: "primary" },
  closed:         { label: "Closed",         type: "gray"    },
  draft:          { label: "Draft",          type: "gray"    },
};
const ALL_STATUSES = Object.keys(STATUS_META);

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export const CaseTracking = ({ T }) => {
  const [sf, setSf]           = useState("all");
  const [search, setSearch]   = useState("");
  const [modal, setModal]     = useState(null);
  const [cases, setCases]     = useState([]);
  const [total, setTotal]     = useState(0);
  const [page, setPage]       = useState(1);
  const [perPage, setPerPage] = useState(10);
  const [loading, setLoading] = useState(true);
  const [toast, setToast]     = useState("");

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(""), 2800); };

  const fetchCases = useCallback(async () => {
    setLoading(true);
    const { data, error } = await adminListCases({
      page,
      pageSize: perPage,
      status: sf !== "all" ? sf : undefined,
      search: search || undefined,
    });
    if (!error && data) {
      setCases(data.items || []);
      setTotal(data.total || 0);
    }
    setLoading(false);
  }, [page, perPage, sf, search]);

  useEffect(() => { fetchCases(); }, [fetchCases]);
  useEffect(() => { setPage(1); }, [sf, search]);

  const changeStatus = async (c, newStatus) => {
    setCases(p => p.map(x => x._id === c._id ? { ...x, status: newStatus } : x));
    if (modal?._id === c._id) setModal(prev => ({ ...prev, status: newStatus }));
    const { error } = await adminUpdateCaseStatus(c._id, newStatus);
    if (error) {
      setCases(p => p.map(x => x._id === c._id ? { ...x, status: c.status } : x));
      showToast("Failed to update status");
    } else {
      showToast(`Case ${c.case_number} → ${STATUS_META[newStatus]?.label || newStatus}`);
    }
  };

  const sm = (s) => STATUS_META[s] || { label: s, type: "gray" };

  const MILESTONE_STEPS = ["Open", "Lawyer Assigned", "In Progress", "Hearing", "Closed"];
  const stepsDone = (c) => {
    if (c.status === "closed") return 5;
    if (c.status === "in_progress") return 3;
    if (c.status === "pending_lawyer") return 2;
    if (c.status === "open") return 1;
    return 0;
  };

  return (
    <div>
      {toast && (
        <div style={{ position: "fixed", bottom: 24, right: 24, zIndex: 999, background: T.success, color: "#fff", padding: "10px 18px", borderRadius: 10, fontSize: 13, fontWeight: 600, boxShadow: "0 4px 18px rgba(0,0,0,0.18)" }}>
          {toast}
        </div>
      )}

      <div style={{ marginBottom: 26 }}>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, color: T.text, letterSpacing: -0.5 }}>Case Tracking</h1>
        <p style={{ margin: "4px 0 0", color: T.textMuted, fontSize: 14 }}>Monitor case timelines, statuses, milestones, and court instructions</p>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <button onClick={() => setSf("all")}
          style={{ padding: "7px 14px", borderRadius: 9, border: `1px solid ${sf==="all" ? T.primary : T.border}`, background: sf==="all" ? T.primaryGlow2 : "transparent", color: sf==="all" ? T.primary : T.textMuted, fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>
          All
        </button>
        {ALL_STATUSES.map(s => (
          <button key={s} onClick={() => setSf(s)}
            style={{ padding: "7px 14px", borderRadius: 9, border: `1px solid ${sf===s ? T.primary : T.border}`, background: sf===s ? T.primaryGlow2 : "transparent", color: sf===s ? T.primary : T.textMuted, fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>
            {STATUS_META[s].label}
          </button>
        ))}
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center", background: T.inputBg, border: `1px solid ${T.border}`, borderRadius: 9, padding: "7px 12px" }}>
          <Ic d={IC.search} size={14} color={T.textFaint} />
          <input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} placeholder="Search by case # or title..."
            style={{ background: "none", border: "none", outline: "none", color: T.text, fontSize: 13, width: 190 }} />
          {search && <button onClick={() => { setSearch(""); setPage(1); }} style={{ background: "none", border: "none", cursor: "pointer", padding: 0, display: "flex" }}><Ic d={IC.x} size={13} color={T.textFaint} /></button>}
        </div>
      </div>

      {loading ? (
        <div style={{ padding: 40, textAlign: "center", color: T.textMuted, fontSize: 14 }}>Loading cases…</div>
      ) : cases.length === 0 ? (
        <EmptyState T={T} icon={IC.briefcase} title="No cases found" sub="Try a different filter or search term."
          actionLabel="Clear" onAction={() => { setSf("all"); setSearch(""); setPage(1); }} />
      ) : (
        <>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {cases.map(c => {
              const done = stepsDone(c);
              return (
                <div key={c._id} style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 14, padding: 20, boxShadow: T.shadowCard }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
                    <div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
                        <span style={{ color: T.primary, fontWeight: 600, fontSize: 14 }}>{c.case_number}</span>
                        <Badge label={sm(c.status).label} type={sm(c.status).type} T={T} />
                        <Badge label={c.case_type || c.type || "—"} type="gray" T={T} />
                      </div>
                      <div style={{ color: T.textMuted, fontSize: 13 }}>
                        {c.title && <span style={{ color: T.textDim, marginRight: 8 }}>{c.title}</span>}
                        {c.client_name && <span>Client: <span style={{ color: T.textDim }}>{c.client_name}</span></span>}
                        {c.lawyer_name && <span style={{ marginLeft: 12 }}>Lawyer: <span style={{ color: T.textDim }}>{c.lawyer_name}</span></span>}
                      </div>
                    </div>
                    <div style={{ textAlign: "right", flexShrink: 0 }}>
                      <div style={{ color: T.textFaint, fontSize: 12 }}>Filed: {fmtDate(c.created_at)}</div>
                    </div>
                  </div>

                  {/* Progress tracker */}
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 0, marginBottom: 14 }}>
                    {MILESTONE_STEPS.map((m, i) => {
                      const isDone = done > i;
                      return (
                        <div key={m} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center" }}>
                          <div style={{ width: "100%", display: "flex", alignItems: "center" }}>
                            {i > 0 && <div style={{ flex: 1, height: 2, background: isDone ? T.success : T.border }} />}
                            <div style={{ width: 20, height: 20, borderRadius: "50%", background: isDone ? T.success : T.border, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                              {isDone && <Ic d={IC.check} size={10} color={T.mode === "dark" ? T.bg : "#fff"} sw={2.5} />}
                            </div>
                            {i < MILESTONE_STEPS.length-1 && <div style={{ flex: 1, height: 2, background: done > i+1 ? T.success : T.border }} />}
                          </div>
                          <span style={{ color: isDone ? T.textMuted : T.textFaint, fontSize: 9.5, marginTop: 4, textAlign: "center" }}>{m}</span>
                        </div>
                      );
                    })}
                  </div>

                  <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center", flexWrap: "wrap" }}>
                    <button onClick={() => setModal(c)} style={{ display: "flex", gap: 6, alignItems: "center", padding: "7px 14px", border: `1px solid ${T.border}`, borderRadius: 9, background: "transparent", color: T.textMuted, fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>
                      <Ic d={IC.eye} size={13} color={T.textMuted} /> View Details
                    </button>
                    <div style={{ marginLeft: "auto", display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {ALL_STATUSES.map(s => (
                        <button key={s} onClick={() => changeStatus(c, s)}
                          style={{ padding: "5px 10px", borderRadius: 7, border: `1px solid ${c.status===s ? T.primary : T.border}`, background: c.status===s ? T.primaryGlow2 : "transparent", color: c.status===s ? T.primary : T.textFaint, fontSize: 11, fontWeight: 600, cursor: "pointer" }}>
                          {STATUS_META[s].label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          <div style={{ marginTop: 14 }}>
            <Paginator T={T} total={total} page={page} perPage={perPage} onPage={setPage} onPerPage={n => { setPerPage(n); setPage(1); }} />
          </div>
        </>
      )}

      <Modal open={!!modal} onClose={() => setModal(null)} title="Case Details" T={T}>
        {modal && (
          <>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
              <span style={{ color: T.primary, fontWeight: 700, fontSize: 15 }}>{modal.case_number}</span>
              <Badge label={sm(modal.status).label} type={sm(modal.status).type} T={T} />
            </div>
            {[
              ["Title",       modal.title || "—"],
              ["Type",        modal.case_type || "—"],
              ["Client",      modal.client_name || modal.client_id || "—"],
              ["Lawyer",      modal.lawyer_name || (modal.lawyer_id ? modal.lawyer_id.slice(-8) : "Unassigned")],
              ["Province",    modal.province || "—"],
              ["Status",      sm(modal.status).label],
              ["Filed",       fmtDate(modal.created_at)],
              ["Last Update", fmtDate(modal.updated_at)],
            ].map(([k, v]) => (
              <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "9px 0", borderBottom: `1px solid ${T.border}40` }}>
                <span style={{ color: T.textMuted, fontSize: 13 }}>{k}</span>
                <span style={{ color: T.text, fontWeight: 600, fontSize: 13 }}>{v}</span>
              </div>
            ))}
            {modal.description && (
              <div style={{ marginTop: 12, padding: "10px 12px", background: `${T.info}10`, border: `1px solid ${T.info}25`, borderRadius: 8, fontSize: 12, color: T.textDim }}>
                <strong style={{ color: T.info }}>Description:</strong> {modal.description}
              </div>
            )}
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: T.textMuted, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>Change Status</div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {ALL_STATUSES.map(s => (
                  <button key={s} onClick={() => changeStatus(modal, s)}
                    style={{ padding: "6px 12px", borderRadius: 8, border: `1px solid ${modal.status===s ? T.primary : T.border}`, background: modal.status===s ? T.primaryGlow2 : "transparent", color: modal.status===s ? T.primary : T.textMuted, fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                    {STATUS_META[s].label}
                  </button>
                ))}
              </div>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 18 }}>
              <Btn T={T} variant="ghost" onClick={() => setModal(null)}>Close</Btn>
            </div>
          </>
        )}
      </Modal>
    </div>
  );
};
