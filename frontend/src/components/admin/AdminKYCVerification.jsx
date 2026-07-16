'use client';
import { useState, useEffect, useMemo } from "react";
import { useAutoAnimate } from "@formkit/auto-animate/react";
import { StatCard, IconBox, Badge, DocTag, Avatar, Btn, Modal, EmptyState, Ic } from "./components.jsx";
import { IC } from "./icons.js";
import { adminListPendingKYC, adminProcessKYC } from "@/lib/api.js";

function fmtDate(iso) {
  if (!iso) return "Unknown";
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export const KYCVerification = ({ T }) => {
  const [lawyers, setLawyers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal]             = useState(null);
  const [notif, setNotif]             = useState(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [search, setSearch]           = useState("");

  useEffect(() => {
    adminListPendingKYC().then(({ data }) => {
      if (data) {
        const mapped = data.map(u => ({
          id: u._id,
          name: u.full_name,
          email: u.email,
          bar: u.lawyer_profile?.bar_number || "N/A",
          docs: ["Bar License", "ID Proof"],
          status: "pending",
          submitted: fmtDate(u.created_at),
        }));
        setLawyers(mapped);
      }
      setLoading(false);
    });
  }, []);

  const pending  = lawyers.filter(l => l.status === "pending").length;
  const approved = lawyers.filter(l => l.status === "approved").length;
  const rejected = lawyers.filter(l => l.status === "rejected").length;

  const setStatus = async (id, st) => {
    const lawyer = lawyers.find(l => l.id === id);
    const { error } = await adminProcessKYC(id, st === "approved");
    if (error) {
      setNotif({ name: lawyer.name, email: lawyer.email, action: "error" });
      setTimeout(() => setNotif(null), 4000);
      return;
    }
    setLawyers(p => p.map(l => l.id === id ? { ...l, status: st } : l));
    setNotif({ name: lawyer.name, email: lawyer.email, action: st });
    setTimeout(() => setNotif(null), 4000);
    if (modal) setModal(null);
  };

  const filtered = useMemo(() => lawyers.filter(l => {
    const matchStatus = statusFilter === "all" || l.status === statusFilter;
    const matchSearch = (l.name + l.email + l.bar).toLowerCase().includes(search.toLowerCase());
    return matchStatus && matchSearch;
  }), [lawyers, statusFilter, search]);

  const [listRef] = useAutoAnimate({ duration: 220, easing: 'ease-out' });
  const sb = s => ({ pending: { label: "Pending", type: "warn" }, approved: { label: "Approved", type: "success" }, rejected: { label: "Rejected", type: "danger" } }[s]);

  return (
    <div style={{ position: "relative" }}>
      {notif && (
        <div style={{ position: "fixed", bottom: 24, right: 24, zIndex: 999, background: notif.action === "approved" ? T.success : notif.action === "error" ? T.warn : T.danger, color: "#fff", padding: "12px 18px", borderRadius: 12, fontSize: 13, fontWeight: 600, boxShadow: "0 6px 24px rgba(0,0,0,0.22)", maxWidth: 340, display: "flex", gap: 10, alignItems: "flex-start" }}>
          <Ic d={notif.action === "approved" ? IC.checkCircle : IC.xCircle} size={18} color="#fff" />
          <div>
            {notif.action === "error"
              ? <div style={{ fontWeight: 700 }}>Failed to update {notif.name} — check connection</div>
              : <>
                  <div style={{ fontWeight: 700 }}>Notification sent to {notif.name}</div>
                  <div style={{ fontSize: 12, opacity: 0.88, marginTop: 2 }}>Email to <strong>{notif.email}</strong>: KYC {notif.action}</div>
                </>
            }
          </div>
        </div>
      )}

      <div style={{ marginBottom: 22 }}>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, color: T.text, letterSpacing: -0.5 }}>KYC Verification</h1>
        <p style={{ margin: "4px 0 0", color: T.textMuted, fontSize: 14 }}>Review and verify lawyer credentials · click cards to filter</p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14, marginBottom: 22 }}>
        <StatCard label="Pending Requests" value={pending} sub="Requires attention" subColor={T.danger}
          sparkData={[1,2,2,3,2,2,2,pending]} sparkColor={T.warn}
          iconEl={<IconBox icon={IC.clock} variant="Warn" T={T} size={42} />}
          onClick={() => setStatusFilter(statusFilter === "pending" ? "all" : "pending")} T={T} />
        <StatCard label="Approved" value={approved} sub="This month"
          sparkData={[1,1,2,2,3,3,4,approved]} sparkColor={T.success}
          iconEl={<IconBox icon={IC.checkCircle} variant="Success" T={T} size={42} />}
          onClick={() => setStatusFilter(statusFilter === "approved" ? "all" : "approved")} T={T} />
        <StatCard label="Rejected" value={rejected} sub="This month" subColor={T.textMuted}
          sparkData={[0,1,1,1,1,1,1,rejected]} sparkColor={T.danger}
          iconEl={<IconBox icon={IC.xCircle} variant="Danger" T={T} size={42} />}
          onClick={() => setStatusFilter(statusFilter === "rejected" ? "all" : "rejected")} T={T} />
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "center", flexWrap: "wrap" }}>
        {["all","pending","approved","rejected"].map(f => (
          <button key={f} onClick={() => setStatusFilter(f)}
            style={{ padding: "6px 14px", borderRadius: 9, border: `1px solid ${statusFilter === f ? T.primary : T.border}`, background: statusFilter === f ? T.primaryGlow2 : "transparent", color: statusFilter === f ? T.primary : T.textMuted, fontSize: 12.5, fontWeight: 600, cursor: "pointer", textTransform: "capitalize", transition: "all 0.14s" }}>
            {f === "all" ? "All" : f}
            {f !== "all" && <span style={{ marginLeft: 5, fontSize: 11, opacity: 0.7 }}>({f === "pending" ? pending : f === "approved" ? approved : rejected})</span>}
          </button>
        ))}
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center", background: T.inputBg, border: `1px solid ${T.border}`, borderRadius: 9, padding: "7px 12px" }}>
          <Ic d={IC.search} size={14} color={T.textFaint} />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search name, email, or bar #…"
            style={{ background: "none", border: "none", outline: "none", color: T.text, fontSize: 13, width: 220 }} />
          {search && <button onClick={() => setSearch("")} style={{ background: "none", border: "none", cursor: "pointer", display: "flex", padding: 0 }}><Ic d={IC.x} size={13} color={T.textFaint} /></button>}
        </div>
      </div>

      {statusFilter !== "all" && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 14px", background: T.primaryGlow2, border: `1px solid ${T.primary}30`, borderRadius: 9, marginBottom: 12, fontSize: 13, color: T.primary }}>
          <Ic d={IC.filter} size={13} color={T.primary} />
          Showing <strong>{statusFilter}</strong> requests
          <button onClick={() => setStatusFilter("all")} style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: 4, color: T.textMuted, fontSize: 12 }}>
            <Ic d={IC.x} size={12} color={T.textMuted} /> Clear
          </button>
        </div>
      )}

      {loading
        ? <div style={{ textAlign: "center", padding: 48, color: T.textMuted, fontSize: 14 }}>Loading pending KYC submissions…</div>
        : filtered.length === 0
        ? <EmptyState T={T} icon={IC.verify} title={lawyers.length === 0 ? "No pending KYC submissions" : "No lawyers match"} sub={lawyers.length === 0 ? "All submitted applications have been reviewed." : "Try a different filter or search term."} actionLabel="Clear filters" onAction={() => { setStatusFilter("all"); setSearch(""); }} />
        : (
          <div ref={listRef} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {filtered.map(l => (
              <div key={l.id} style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 14, padding: "16px 20px", boxShadow: T.shadowCard, display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
                <Avatar name={l.name} size={42} />
                <div style={{ flex: 1, minWidth: 160 }}>
                  <div style={{ fontWeight: 700, fontSize: 15, color: T.text }}>{l.name}</div>
                  <div style={{ color: T.textMuted, fontSize: 12.5, marginTop: 1 }}>{l.email} · Bar #{l.bar}</div>
                  <div style={{ color: T.textFaint, fontSize: 11.5, marginTop: 2 }}>Submitted {l.submitted}</div>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                  {l.docs.map(d => <DocTag key={d} label={d} T={T} />)}
                  <Badge label={sb(l.status).label} type={sb(l.status).type} T={T} />
                </div>
                <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                  <button onClick={() => setModal(l)} style={{ display: "flex", gap: 6, alignItems: "center", padding: "7px 14px", border: `1px solid ${T.border}`, borderRadius: 9, background: "transparent", color: T.textMuted, fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
                    <Ic d={IC.eye} size={14} color={T.textMuted} /> Review
                  </button>
                  {l.status === "pending" && <>
                    <Btn T={T} variant="success" onClick={() => setStatus(l.id, "approved")}>Approve</Btn>
                    <Btn T={T} variant="danger"  onClick={() => setStatus(l.id, "rejected")}>Reject</Btn>
                  </>}
                </div>
              </div>
            ))}
          </div>
        )
      }

      <Modal open={!!modal} onClose={() => setModal(null)} title="Lawyer Profile Review" T={T}>
        {modal && (
          <div>
            <div style={{ display: "flex", gap: 14, alignItems: "center", background: T.mode === "dark" ? T.surface : T.bg, borderRadius: 12, padding: 16, marginBottom: 18 }}>
              <Avatar name={modal.name} size={52} />
              <div>
                <div style={{ color: T.text, fontWeight: 700, fontSize: 15 }}>{modal.name}</div>
                <div style={{ color: T.textMuted, fontSize: 13 }}>{modal.email}</div>
                <div style={{ marginTop: 6 }}><Badge label={sb(modal.status).label} type={sb(modal.status).type} T={T} /></div>
              </div>
            </div>
            {[["Bar License No.", `#${modal.bar}`], ["Documents", modal.docs.join(", ")], ["Submitted", modal.submitted], ["Status", sb(modal.status).label]].map(([k, v]) => (
              <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "9px 0", borderBottom: `1px solid ${T.border}40` }}>
                <span style={{ color: T.textMuted, fontSize: 13 }}>{k}</span>
                <span style={{ color: T.text, fontWeight: 600, fontSize: 13 }}>{v}</span>
              </div>
            ))}
            <div style={{ marginTop: 14, padding: "10px 12px", background: `${T.info}12`, border: `1px solid ${T.info}25`, borderRadius: 8, display: "flex", gap: 8, alignItems: "center" }}>
              <Ic d={IC.bell} size={14} color={T.info} />
              <span style={{ fontSize: 12, color: T.textMuted }}>Approving or rejecting will <strong style={{ color: T.text }}>automatically send a notification email</strong> to the lawyer.</span>
            </div>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 18 }}>
              <Btn T={T} variant="ghost" onClick={() => setModal(null)}>Close</Btn>
              {modal.status === "pending" && <>
                <Btn T={T} variant="success" onClick={() => setStatus(modal.id, "approved")}>Approve & Notify</Btn>
                <Btn T={T} variant="danger"  onClick={() => setStatus(modal.id, "rejected")}>Reject & Notify</Btn>
              </>}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};
