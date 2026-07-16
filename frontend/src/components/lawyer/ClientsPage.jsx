'use client';
import { useState, useEffect } from "react";
import { useTheme } from "./theme.js";
import { useCase } from "./theme.js";
import { useNotif } from "./theme.js";
import { Card, Btn, Input, Badge, Divider } from "./components.jsx";
import { Icon, I } from "./icons.jsx";
import { listCases } from "@/lib/api.js";

function ClientsPage() {
    const { t } = useTheme();
    const { setPage, setOpenCaseId } = useCase();
    const { addNotif } = useNotif();
    const [search, setSearch] = useState("");
    const [clients, setClients] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        listCases({ page_size: 50 }).then(({ data }) => {
            if (!data?.items) { setLoading(false); return; }
            const map = {};
            data.items.forEach(c => {
                const cid = c.client_id;
                if (!cid) return;
                if (!map[cid]) {
                    map[cid] = {
                        id: cid,
                        caseId: c.id,
                        name: c.client_name || `Client ${cid.slice(0, 6)}`,
                        email: c.client_email || "—",
                        phone: "—",
                        cases: 0,
                        status: "Active",
                        since: new Date(c.created_at).toLocaleDateString("en-US", { month: "short", year: "numeric" }),
                        province: c.province || "—",
                    };
                }
                map[cid].cases += 1;
            });
            setClients(Object.values(map));
            setLoading(false);
        }).catch(() => setLoading(false));
    }, []);

    // Messages live per-case: open the client's case workspace (messages tab is inside it)
    const openMessageFor = (client) => {
        if (client.caseId) setOpenCaseId(client.caseId);
        setPage("cases");
    };

    const filtered = clients.filter(c => c.name.toLowerCase().includes(search.toLowerCase()));

    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
            <div style={{ flex: 1, overflowY: "auto" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }} className="fade-up">
                        <div>
                            <div className="serif" style={{ fontSize: 22, fontWeight: 700, color: t.text }}>Clients</div>
                            <div style={{ fontSize: 13, color: t.textMuted, marginTop: 3 }}>
                                {loading ? "Loading…" : `${clients.length} client${clients.length !== 1 ? "s" : ""} across your cases`}
                            </div>
                        </div>
                        <Btn onClick={() => addNotif({ type: "appointment", title: "New Client Added", body: "Client profile has been created", time: "Just now" })}>
                            <Icon d={I.plus} size={14} /> Add Client
                        </Btn>
                    </div>

                    <Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search clients…" prefix={<Icon d={I.search} size={13} />} style={{ width: 240 }} className="fade-up s1" />

                    {loading ? (
                        <div style={{ padding: 40, textAlign: "center", fontSize: 13, color: t.textMuted }}>Loading clients…</div>
                    ) : filtered.length === 0 ? (
                        <div style={{ padding: 40, textAlign: "center", fontSize: 13, color: t.textMuted }}>
                            {clients.length === 0 ? "No cases assigned yet — clients will appear here once cases are linked." : "No clients match your search."}
                        </div>
                    ) : (
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14 }} className="fade-up s2">
                            {filtered.map(client => {
                                const ini = client.name.split(" ").map(n => n[0]).join("").toUpperCase().slice(0, 2);
                                return (
                                    <Card key={client.id} style={{ padding: 16 }}>
                                        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
                                            <div style={{ display: "flex", gap: 11, alignItems: "center" }}>
                                                <div style={{ width: 42, height: 42, borderRadius: 11, background: t.grad1, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 700, color: t.mode === "dark" ? t.bg : t.surface }}>{ini}</div>
                                                <div>
                                                    <div style={{ fontSize: 14, fontWeight: 600, color: t.text }}>{client.name}</div>
                                                    <div style={{ marginTop: 3 }}><Badge type={client.status === "Active" ? "success" : "gray"}>{client.status}</Badge></div>
                                                </div>
                                            </div>
                                            <button style={{ background: "none", border: "none", color: t.textFaint, cursor: "pointer" }}><Icon d={I.more} size={13} /></button>
                                        </div>
                                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                            {[
                                                { ic: I.mail, v: client.email },
                                                { ic: I.map, v: client.province },
                                                { ic: I.cases, v: `${client.cases} active case${client.cases !== 1 ? "s" : ""}` },
                                                { ic: I.clock, v: `Client since ${client.since}` },
                                            ].map((r, i) => (
                                                <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12, color: t.textMuted }}>
                                                    <Icon d={r.ic} size={12} style={{ flexShrink: 0 }} />
                                                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.v}</span>
                                                </div>
                                            ))}
                                        </div>
                                        <Divider />
                                        <div style={{ display: "flex", gap: 6 }}>
                                            <Btn variant="accent" size="sm" style={{ flex: 1 }} onClick={() => openMessageFor(client)}>
                                                <Icon d={I.chat} size={12} /> Message
                                            </Btn>
                                            <Btn variant="secondary" size="sm" style={{ flex: 1 }} onClick={() => { addNotif({ type: "appointment", title: "Appointment Requested", body: `Booking for ${client.name}`, time: "Just now" }); setPage("appointments"); }}>
                                                <Icon d={I.calendar} size={12} /> Schedule
                                            </Btn>
                                        </div>
                                    </Card>
                                );
                            })}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
export { ClientsPage };
