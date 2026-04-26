'use client';
// Admin User Management — paste your code here
import { useState, useMemo } from "react";
import { Avatar, Badge, Btn, Modal, Input, EmptyState, Paginator, ActionMenu, SortTh, Ic } from "./components.jsx";
import { IC } from "./icons.js";

export const UserManagement = ({ T }) => {
  const [tab, setTab]       = useState("all");
  const [search, setSearch] = useState("");
  const [modal, setModal]   = useState(null);
  const [sel, setSel]       = useState(null);
  const [confirmDel, setConfirmDel] = useState(null);
  const [toastMsg, setToastMsg]     = useState("");

  const showToast = (msg) => { setToastMsg(msg); setTimeout(() => setToastMsg(""), 2800); };

  const [users, setUsers] = useState([
    { id:1, name:"Sarah Johnson", email:"sarah.j@email.com",   role:"client", status:"active",   joined:"Jan 15, 2024" },
    { id:2, name:"Michael Chen",  email:"m.chen@email.com",    role:"client", status:"active",   joined:"Feb 20, 2024" },
    { id:3, name:"Aisha Patel",   email:"aisha.p@email.com",   role:"client", status:"inactive", joined:"Mar 5, 2024"  },
    { id:4, name:"James Rivera",  email:"j.rivera@law.com",    role:"lawyer", status:"active",   joined:"Nov 10, 2023" },
    { id:5, name:"Maria Santos",  email:"m.santos@law.com",    role:"lawyer", status:"active",   joined:"Dec 1, 2023"  },
    { id:6, name:"Admin User",    email:"admin@legaladmin.com",role:"admin",  status:"active",   joined:"Jan 1, 2023"  },
  ]);

  const toggleStatus = (id) => {
    setUsers(prev => prev.map(u => {
      if (u.id !== id) return u;
      const next = u.status === "active" ? "inactive" : "active";
      showToast(`${u.name} account ${next === "active" ? "activated" : "deactivated"}`);
      return { ...u, status: next };
    }));
  };

  const deleteUser = (id) => {
    const u = users.find(u => u.id === id);
    setUsers(prev => prev.filter(u => u.id !== id));
    setConfirmDel(null);
    showToast(`${u.name} deleted`);
  };

  const [editRole, setEditRole] = useState("client");
  const [sort, setSort]         = useState({ field: "name", dir: "asc" });
  const handleSort = (field) => setSort(p => ({ field, dir: p.field === field && p.dir === "asc" ? "desc" : "asc" }));
  const [page, setPage]         = useState(1);
  const [perPage, setPerPage]   = useState(5);

  const filtered = useMemo(() => {
    let list = users.filter(u => {
      const matchTab = tab === "all" || u.role === tab.slice(0, -1);
      return matchTab && (u.name.toLowerCase().includes(search.toLowerCase()) || u.email.toLowerCase().includes(search.toLowerCase()));
    });
    list = [...list].sort((a, b) => {
      const av = a[sort.field] || "", bv = b[sort.field] || "";
      return sort.dir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
    });
    return list;
  }, [users, tab, search, sort]);

  const paged = filtered.slice((page - 1) * perPage, page * perPage);

  const Toggle = ({ on, onChange }) => (
    <button onClick={onChange} role="switch" aria-checked={on} title={on ? "Click to deactivate" : "Click to activate"}
      style={{ width: 42, height: 24, borderRadius: 12, border: "none", padding: 2, cursor: "pointer", transition: "background 0.22s", background: on ? T.success : (T.mode==="dark"?"rgba(255,255,255,0.12)":"rgba(26,46,53,0.12)"), display: "flex", alignItems: "center", justifyContent: on ? "flex-end" : "flex-start" }}>
      <div style={{ width: 18, height: 18, borderRadius: "50%", background: "#fff", boxShadow: "0 1px 3px rgba(0,0,0,0.2)", transition: "all 0.22s cubic-bezier(0.34,1.56,0.64,1)" }} />
    </button>
  );

  return (
    <div style={{ position: "relative" }}>
      {toastMsg && (
        <div style={{ position: "fixed", bottom: 24, right: 24, zIndex: 999, background: T.success, color: T.mode==="dark"?"#0a1f1a":"#fff", padding: "10px 18px", borderRadius: 10, fontSize: 13, fontWeight: 600, boxShadow: "0 4px 18px rgba(0,0,0,0.18)", display: "flex", alignItems: "center", gap: 8 }}>
          <Ic d={IC.check} size={15} color={T.mode==="dark"?"#0a1f1a":"#fff"} sw={2.5} /> {toastMsg}
        </div>
      )}

      {confirmDel && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 998, display: "flex", alignItems: "center", justifyContent: "center" }} onClick={() => setConfirmDel(null)}>
          <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 16, padding: 28, maxWidth: 400, width: "90%", boxShadow: "0 20px 60px rgba(0,0,0,0.28)" }} onClick={e => e.stopPropagation()}>
            <div style={{ width: 48, height: 48, borderRadius: "50%", background: `${T.danger}15`, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 16 }}>
              <Ic d={IC.trash} size={22} color={T.danger} />
            </div>
            <div style={{ fontSize: 15, fontWeight: 700, color: T.text, marginBottom: 6 }}>Delete account?</div>
            <div style={{ fontSize: 13, color: T.textMuted, marginBottom: 20, lineHeight: 1.65 }}>
              This will permanently remove <strong style={{ color: T.text }}>{confirmDel.name}</strong>'s account and all associated data. This action cannot be undone.
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              <Btn T={T} variant="ghost" onClick={() => setConfirmDel(null)} style={{ flex: 1, justifyContent: "center" }}>Cancel</Btn>
              <Btn T={T} variant="danger" onClick={() => deleteUser(confirmDel.id)} style={{ flex: 1, justifyContent: "center" }}>Delete permanently</Btn>
            </div>
          </div>
        </div>
      )}

      <div style={{ marginBottom: 22 }}>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, color: T.text, letterSpacing: -0.5 }}>User Management</h1>
        <p style={{ margin: "4px 0 0", color: T.textMuted, fontSize: 14 }}>Manage all users, roles, and account access</p>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "center", flexWrap: "wrap" }}>
        {["all","clients","lawyers","admins"].map(t => (
          <button key={t} onClick={() => { setTab(t); setPage(1); }}
            style={{ padding: "7px 16px", borderRadius: 9, border: `1px solid ${tab===t ? T.primary : T.border}`, background: tab===t ? T.primaryGlow2 : "transparent", color: tab===t ? T.primary : T.textMuted, fontSize: 13, fontWeight: 600, cursor: "pointer", textTransform: "capitalize" }}>
            {t}
          </button>
        ))}
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center", background: T.inputBg, border: `1px solid ${T.border}`, borderRadius: 9, padding: "7px 12px" }}>
          <Ic d={IC.search} size={14} color={T.textFaint} />
          <input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} placeholder="Search users..."
            style={{ background: "none", border: "none", outline: "none", color: T.text, fontSize: 13, width: 160 }} />
          {search && <button onClick={() => { setSearch(""); setPage(1); }} style={{ background: "none", border: "none", cursor: "pointer", padding: 0, display: "flex" }}><Ic d={IC.x} size={13} color={T.textFaint} /></button>}
        </div>
        <Btn T={T} icon={IC.plus} onClick={() => { setSel(null); setEditRole("client"); setModal("add"); }}>Add User</Btn>
      </div>

      <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 14, overflow: "hidden", boxShadow: T.shadowCard }}>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 640 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${T.border}`, background: T.mode === "dark" ? "rgba(255,255,255,0.025)" : "rgba(26,46,53,0.025)" }}>
                <SortTh label="User"   field="name"   sort={sort} onSort={handleSort} T={T} />
                <SortTh label="Email"  field="email"  sort={sort} onSort={handleSort} T={T} />
                <SortTh label="Role"   field="role"   sort={sort} onSort={handleSort} T={T} />
                <th style={{ padding: "12px 18px", textAlign: "left", color: T.textMuted, fontSize: 12, fontWeight: 600 }}>Active</th>
                <SortTh label="Joined" field="joined" sort={sort} onSort={handleSort} T={T} />
                <th style={{ padding: "12px 14px", width: 44 }} />
              </tr>
            </thead>
            <tbody>
              {paged.length === 0 ? (
                <tr><td colSpan={6}>
                  <EmptyState T={T} icon={IC.users} title="No users found" sub="Try adjusting the filter or search term." actionLabel="Clear filters" onAction={() => { setSearch(""); setTab("all"); setPage(1); }} />
                </td></tr>
              ) : paged.map((u, i) => (
                <tr key={u.id} style={{ borderBottom: i < paged.length - 1 ? `1px solid ${T.border}40` : "none", transition: "background 0.13s" }}
                  onMouseEnter={e => e.currentTarget.style.background = T.cardHi}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <td style={{ padding: "12px 18px" }}>
                    <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                      <Avatar name={u.name} size={34} />
                      <span style={{ color: T.text, fontWeight: 600, fontSize: 13.5 }}>{u.name}</span>
                    </div>
                  </td>
                  <td style={{ padding: "12px 18px", color: T.textMuted, fontSize: 13 }}>{u.email}</td>
                  <td style={{ padding: "12px 18px" }}><Badge label={u.role.charAt(0).toUpperCase()+u.role.slice(1)} type={u.role==="admin"?"primary":u.role==="lawyer"?"info":"gray"} T={T} /></td>
                  <td style={{ padding: "12px 18px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <Toggle on={u.status==="active"} onChange={() => toggleStatus(u.id)} />
                      <span style={{ fontSize: 12, color: u.status==="active" ? T.success : T.textFaint, fontWeight: 500 }}>{u.status==="active" ? "Active" : "Inactive"}</span>
                    </div>
                  </td>
                  <td style={{ padding: "12px 18px", color: T.textMuted, fontSize: 13 }}>{u.joined}</td>
                  <td style={{ padding: "12px 14px" }}>
                    <ActionMenu T={T} actions={[
                      { label: "Edit user",      icon: IC.edit,  fn: () => { setSel(u); setEditRole(u.role); setModal("edit"); } },
                      { label: "Reset password", icon: IC.key,   fn: () => { setSel(u); setModal("pw"); } },
                      { label: u.status === "active" ? "Deactivate" : "Activate", icon: IC.lock, fn: () => toggleStatus(u.id) },
                      { label: "Delete user",    icon: IC.trash, fn: () => setConfirmDel(u), danger: true },
                    ]} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Paginator T={T} total={filtered.length} page={page} perPage={perPage} onPage={setPage} onPerPage={n => { setPerPage(n); setPage(1); }} />
      </div>

      <Modal open={modal==="add"||modal==="edit"} onClose={() => setModal(null)} title={modal==="add" ? "Add User" : "Edit User"} T={T}>
        <Input label="Full Name" value={sel?.name||""} onChange={() => {}} T={T} placeholder="Full name" />
        <Input label="Email" type="email" value={sel?.email||""} onChange={() => {}} T={T} placeholder="Email" />
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: "block", color: T.textMuted, fontSize: 11.5, fontWeight: 700, marginBottom: 5, textTransform: "uppercase", letterSpacing: 0.6 }}>Role</label>
          <select value={editRole} onChange={e => setEditRole(e.target.value)}
            style={{ width: "100%", background: T.inputBg, border: `1px solid ${T.border}`, borderRadius: 9, padding: "9px 13px", color: T.text, fontSize: 13.5, outline: "none" }}>
            <option value="client">Client</option>
            <option value="lawyer">Lawyer</option>
            <option value="admin">Admin</option>
          </select>
          {modal==="edit" && sel && editRole !== sel.role && (
            <div style={{ marginTop: 6, fontSize: 12, color: T.warn, display: "flex", alignItems: "center", gap: 5 }}>
              <Ic d="M12 9v4M12 17h.01" size={13} color={T.warn} /> Role will change from <strong>{sel.role}</strong> → <strong>{editRole}</strong>
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <Btn T={T} variant="ghost" onClick={() => setModal(null)}>Cancel</Btn>
          <Btn T={T} onClick={() => { showToast(modal==="add" ? "User added" : "Changes saved"); setModal(null); }}>Save changes</Btn>
        </div>
      </Modal>

      <Modal open={modal==="pw"} onClose={() => setModal(null)} title="Reset Password" T={T}>
        <Input label="New Password" type="password" value="" onChange={() => {}} T={T} placeholder="New password" />
        <Input label="Confirm Password" type="password" value="" onChange={() => {}} T={T} placeholder="Confirm" />
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <Btn T={T} variant="ghost" onClick={() => setModal(null)}>Cancel</Btn>
          <Btn T={T} icon={IC.key} onClick={() => { showToast(`Password reset for ${sel?.name}`); setModal(null); }}>Reset</Btn>
        </div>
      </Modal>
    </div>
  );
};
