'use client';
// Lawyer Clients Page — paste your code here
import { useState } from "react";
import { useTheme } from "./theme.js";
import { useCase } from "./theme.js";
import { useNotif } from "./theme.js";
import { Card, Btn, Input, Badge, Divider } from "./components.jsx";
import { Icon, I } from "./icons.jsx";

// ============================================================
// CLIENTS PAGE
// ============================================================
const clientsData = [
    { id: 1, name: "Rajesh Singh", email: "rajesh.singh@email.com", phone: "+91 98765 11111", cases: 2, status: "Active", since: "Jan 2026" },
    { id: 2, name: "Priya Sharma", email: "priya.sharma@email.com", phone: "+91 98765 22222", cases: 1, status: "Active", since: "Jan 2026" },
    { id: 3, name: "Amit Patel", email: "amit.patel@email.com", phone: "+91 98765 33333", cases: 1, status: "Active", since: "Feb 2026" },
    { id: 4, name: "Vikram Kumar", email: "vikram.kumar@email.com", phone: "+91 98765 44444", cases: 1, status: "Active", since: "Feb 2026" },
    { id: 5, name: "Lakshmi Reddy", email: "lakshmi.reddy@email.com", phone: "+91 98765 55555", cases: 1, status: "Active", since: "Feb 2026" },
    { id: 6, name: "Anand Gupta", email: "anand.gupta@email.com", phone: "+91 98765 66666", cases: 0, status: "Inactive", since: "Nov 2025" },
];
function ClientsPage() {
    const { t } = useTheme();
    const { setPage, setOpenCommsClientId } = useCase();
    const { addNotif } = useNotif();
    const [search, setSearch] = useState("");

    const openMessageFor = (clientName) => {
        setOpenCommsClientId(clientName);
        setPage("communications");
    };
    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
            <div style={{ flex: 1, overflowY: "auto" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }} className="fade-up">
                        <div><div className="serif" style={{ fontSize: 22, fontWeight: 700, color: t.text }}>Clients</div><div style={{ fontSize: 13, color: t.textMuted, marginTop: 3 }}>Manage your client relationships</div></div>
                        <Btn onClick={() => addNotif({ type: "appointment", title: "New Client Added", body: "Client profile has been created", time: "Just now" })}><Icon d={I.plus} size={14} /> Add Client</Btn>
                    </div>
                    <Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search clients..." prefix={<Icon d={I.search} size={13} />} style={{ width: 240 }} className="fade-up s1" />
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14 }} className="fade-up s2">
                        {clientsData.filter(c => c.name.toLowerCase().includes(search.toLowerCase())).map(client => {
                            const ini = client.name.split(" ").map(n => n[0]).join("");
                            return (
                                <Card key={client.id} style={{ padding: 16 }}>
                                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
                                        <div style={{ display: "flex", gap: 11, alignItems: "center" }}>
                                            <div style={{ width: 42, height: 42, borderRadius: 11, background: t.grad1, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 700, color: t.mode === "dark" ? t.bg : t.surface }}>{ini}</div>
                                            <div><div style={{ fontSize: 14, fontWeight: 600, color: t.text }}>{client.name}</div><div style={{ marginTop: 3 }}><Badge type={client.status === "Active" ? "success" : "gray"}>{client.status}</Badge></div></div>
                                        </div>
                                        <button style={{ background: "none", border: "none", color: t.textFaint, cursor: "pointer" }}><Icon d={I.more} size={13} /></button>
                                    </div>
                                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                        {[{ ic: I.mail, v: client.email }, { ic: I.phone, v: client.phone }, { ic: I.cases, v: `${client.cases} active case${client.cases !== 1 ? "s" : ""}` }, { ic: I.clock, v: `Client since ${client.since}` }].map((r, i) => (
                                            <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12, color: t.textMuted }}><Icon d={r.ic} size={12} style={{ flexShrink: 0 }} /><span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.v}</span></div>
                                        ))}
                                    </div>
                                    <Divider />
                                    <div style={{ display: "flex", gap: 6 }}>
                                        <Btn variant="accent" size="sm" style={{ flex: 1 }} onClick={() => openMessageFor(client.name)}><Icon d={I.chat} size={12} /> Message</Btn>
                                        <Btn variant="secondary" size="sm" style={{ flex: 1 }} onClick={() => { addNotif({ type: "appointment", title: "Appointment Requested", body: `Booking for ${client.name}`, time: "Just now" }); setPage("appointments"); }}><Icon d={I.calendar} size={12} /> Schedule</Btn>
                                    </div>
                                </Card>
                            );
                        })}
                    </div>
                </div>
            </div>
        </div>
    );
}
export { ClientsPage };
