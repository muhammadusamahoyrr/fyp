'use client';
// Lawyer Cases Page — paste your code here
import { useState, useRef, useEffect } from "react";
import { useTheme } from "./theme.js";
import { useCase } from "./theme.js";
import { useNotif } from "./theme.js";
import { Card, Btn, Input, Sel, Label, Badge, Divider, Pills } from "./components.jsx";
import { Icon, I } from "./icons.jsx";
import { seedCases, seedHearings, seedDocs, seedTimeline, fmtDate, fmtTime, CSB, typeColor, typeIcon, DSB, APSB, PRIO, casesData, tasksData, qData } from "./data.js";
import { avatarBg } from "./utils.js";

function WorkspaceOverview({ c, docs, apts, msgs, tasks, hearings, setTab, setPage }) {
    const { t } = useTheme();
    const pendingTasks = tasks.filter(t => !t.done);
    const upcomingHearings = hearings.filter(h => !h.outcome);
    const unreadMsgs = msgs.filter(m => m.status === "Unanswered");

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            {/* Stats row */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12 }} className="fade-up">
                {[
                    { l: "Documents", v: docs.length, c: t.primary, ic: "documents", tab: "documents" },
                    { l: "Hearings", v: hearings.length, c: t.info, ic: "gavel", tab: "hearings" },
                    { l: "Pending Tasks", v: pendingTasks.length, c: pendingTasks.length > 0 ? t.warn : t.success, ic: "checkCircle", tab: "tasks" },
                    { l: "Unread Messages", v: unreadMsgs.length, c: unreadMsgs.length > 0 ? t.danger : t.success, ic: "chat", tab: "messages" },
                ].map(s => (
                    <Card key={s.l} style={{ padding: 16, cursor: "pointer" }} onClick={() => setTab(s.tab)}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                            <div>
                                <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 600 }}>{s.l}</div>
                                <div style={{ fontSize: 28, fontWeight: 700, color: s.c, lineHeight: 1 }}>{s.v}</div>
                            </div>
                            <div style={{ width: 34, height: 34, borderRadius: 10, background: `${s.c}18`, display: "flex", alignItems: "center", justifyContent: "center" }}>
                                <Icon d={I[s.ic]} size={14} style={{ color: s.c }} />
                            </div>
                        </div>
                    </Card>
                ))}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
                {/* Upcoming Hearing */}
                <Card style={{ padding: 18 }} className="fade-up s1">
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                        <div className="serif" style={{ fontSize: 15, fontWeight: 600, color: t.text }}>Next Hearing</div>
                        <button onClick={() => setTab("hearings")} style={{ fontSize: 11, color: t.primary, background: "none", border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: 3 }}>All <Icon d={I.arrowRight} size={10} /></button>
                    </div>
                    {upcomingHearings.length === 0 ? (
                        <div style={{ fontSize: 12, color: t.textFaint, padding: "20px 0", textAlign: "center" }}>No upcoming hearings</div>
                    ) : upcomingHearings.slice(0, 1).map(h => (
                        <div key={h.id} style={{ padding: 14, borderRadius: 10, background: t.primaryGlow2, border: `1px solid ${t.primary}30` }}>
                            <div style={{ fontSize: 16, fontWeight: 700, color: t.primary }}>{h.date}</div>
                            <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginTop: 4 }}>{h.purpose}</div>
                            <div style={{ display: "flex", gap: 12, marginTop: 8, flexWrap: "wrap" }}>
                                <span style={{ fontSize: 11, color: t.textMuted, display: "flex", alignItems: "center", gap: 4 }}><Icon d={I.clock} size={11} />{h.time}</span>
                                <span style={{ fontSize: 11, color: t.textMuted, display: "flex", alignItems: "center", gap: 4 }}><Icon d={I.map} size={11} />{h.court}</span>
                            </div>
                            <div style={{ fontSize: 11, color: t.textFaint, marginTop: 6 }}>{h.judge}</div>
                        </div>
                    ))}
                </Card>

                {/* Pending Tasks */}
                <Card style={{ padding: 18 }} className="fade-up s2">
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                        <div className="serif" style={{ fontSize: 15, fontWeight: 600, color: t.text }}>Pending Tasks</div>
                        <button onClick={() => setTab("tasks")} style={{ fontSize: 11, color: t.primary, background: "none", border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: 3 }}>All <Icon d={I.arrowRight} size={10} /></button>
                    </div>
                    {pendingTasks.length === 0 ? (
                        <div style={{ fontSize: 12, color: t.success, padding: "8px 0", display: "flex", alignItems: "center", gap: 6 }}><Icon d={I.checkCircle} size={14} /> All tasks complete!</div>
                    ) : pendingTasks.slice(0, 3).map(task => (
                        <div key={task.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderBottom: `1px solid ${t.border}` }}>
                            <div style={{ width: 8, height: 8, borderRadius: "50%", background: t[PRIO[task.priority]] || t.textMuted, flexShrink: 0 }} />
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 12, fontWeight: 500, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{task.title}</div>
                                <div style={{ fontSize: 10, color: t.textFaint }}>Due {task.due}</div>
                            </div>
                        </div>
                    ))}
                </Card>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
                {/* Recent Documents */}
                <Card style={{ padding: 18 }} className="fade-up s3">
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                        <div className="serif" style={{ fontSize: 15, fontWeight: 600, color: t.text }}>Documents</div>
                        <button onClick={() => setTab("documents")} style={{ fontSize: 11, color: t.primary, background: "none", border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: 3 }}>All <Icon d={I.arrowRight} size={10} /></button>
                    </div>
                    {docs.length === 0 ? <div style={{ fontSize: 12, color: t.textFaint, padding: "10px 0" }}>No documents yet</div> : docs.map(doc => (
                        <div key={doc.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 0", borderBottom: `1px solid ${t.border}` }}>
                            <div style={{ width: 32, height: 32, borderRadius: 8, background: t.primaryGlow2, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                                <Icon d={I.fileText} size={13} style={{ color: t.primary }} />
                            </div>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 12, fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{doc.title}</div>
                                <div style={{ fontSize: 10, color: t.textFaint }}>{doc.modified}</div>
                            </div>
                            <Badge type={DSB[doc.status]}>{doc.status}</Badge>
                        </div>
                    ))}
                </Card>

                {/* Client Messages */}
                <Card style={{ padding: 18 }} className="fade-up s4">
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                        <div className="serif" style={{ fontSize: 15, fontWeight: 600, color: t.text }}>Client Messages</div>
                        <button onClick={() => setTab("messages")} style={{ fontSize: 11, color: t.primary, background: "none", border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: 3 }}>All <Icon d={I.arrowRight} size={10} /></button>
                    </div>
                    {msgs.length === 0 ? <div style={{ fontSize: 12, color: t.textFaint, padding: "10px 0" }}>No messages</div> : msgs.map(msg => (
                        <div key={msg.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 0", borderBottom: `1px solid ${t.border}` }}>
                            <div style={{ width: 32, height: 32, borderRadius: "50%", flexShrink: 0, background: avatarBg(msg.initials), display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: "#fff" }}>{msg.initials}</div>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 12, fontWeight: 600, color: t.text }}>{msg.client}</div>
                                <div style={{ fontSize: 11, color: t.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{msg.question}</div>
                            </div>
                            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, flexShrink: 0 }}>
                                <span style={{ fontSize: 10, color: t.textFaint }}>{msg.time}</span>
                                {msg.status === "Unanswered" && <div style={{ width: 7, height: 7, borderRadius: "50%", background: t.warn }} />}
                            </div>
                        </div>
                    ))}
                    <div style={{ marginTop: 12 }}>
                        <Btn variant="accent" size="sm" full onClick={() => setPage("communications")}>
                            <Icon d={I.chat} size={12} /> Open in Communications
                        </Btn>
                    </div>
                </Card>
            </div>
        </div>
    );
}

// ── Documents Tab ────────────────────────────────────────────
function WorkspaceDocuments({ docs, caseId, setPage }) {
    const { t } = useTheme();
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }} className="fade-up">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div className="serif" style={{ fontSize: 16, fontWeight: 600, color: t.text }}>Documents — {docs.length} file{docs.length !== 1 ? "s" : ""}</div>
                <div style={{ display: "flex", gap: 8 }}>
                    <Btn variant="secondary" size="sm" onClick={() => setPage("upload")}><Icon d={I.upload} size={12} /> Upload</Btn>
                    <Btn variant="accent" size="sm" onClick={() => setPage("doc-automation")}><Icon d={I.wand} size={12} /> Generate</Btn>
                </div>
            </div>
            {docs.length === 0 ? (
                <Card style={{ padding: 40, textAlign: "center" }}>
                    <Icon d={I.fileText} size={32} style={{ color: t.textFaint, opacity: .3, display: "block", margin: "0 auto 12px" }} />
                    <div style={{ fontSize: 13, color: t.textMuted }}>No documents linked to this case yet.</div>
                    <div style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "center" }}>
                        <Btn variant="primary" size="sm" onClick={() => setPage("upload")}>Upload Document</Btn>
                        <Btn variant="secondary" size="sm" onClick={() => setPage("doc-automation")}>Generate with AI</Btn>
                    </div>
                </Card>
            ) : (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: 12 }}>
                    {docs.map(doc => (
                        <Card key={doc.id} style={{ padding: 16 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
                                <div style={{ width: 38, height: 38, borderRadius: 10, background: t.primaryGlow2, display: "flex", alignItems: "center", justifyContent: "center" }}>
                                    <Icon d={I.fileText} size={16} style={{ color: t.primary }} />
                                </div>
                                <Badge type={DSB[doc.status]}>{doc.status}</Badge>
                            </div>
                            <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 4, lineHeight: 1.4 }}>{doc.title}</div>
                            <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 12 }}>{doc.type} · {doc.modified}</div>
                            <div style={{ display: "flex", gap: 6 }}>
                                <Btn variant="ghost" size="sm" style={{ flex: 1 }}><Icon d={I.eye} size={11} /> View</Btn>
                                <Btn variant="ghost" size="sm" style={{ flex: 1 }}><Icon d={I.download} size={11} /> Download</Btn>
                            </div>
                        </Card>
                    ))}
                </div>
            )}
        </div>
    );
}

// ── Hearings Tab ─────────────────────────────────────────────
function WorkspaceHearings({ hearings, c }) {
    const { t } = useTheme();
    const upcoming = hearings.filter(h => !h.outcome);
    const past = hearings.filter(h => h.outcome);
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }} className="fade-up">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div className="serif" style={{ fontSize: 16, fontWeight: 600, color: t.text }}>Hearing Schedule</div>
                <Btn variant="accent" size="sm"><Icon d={I.plus} size={12} /> Add Hearing</Btn>
            </div>

            {upcoming.length > 0 && (
                <div>
                    <div style={{ fontSize: 11, fontWeight: 700, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>Upcoming</div>
                    {upcoming.map(h => (
                        <div key={h.id} style={{ padding: 16, borderRadius: 12, background: t.primaryGlow2, border: `1px solid ${t.primary}30`, marginBottom: 10 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
                                <div style={{ fontSize: 16, fontWeight: 700, color: t.primary }}>{h.date}</div>
                                <Badge type="info">Upcoming</Badge>
                            </div>
                            <div style={{ fontSize: 14, fontWeight: 600, color: t.text, marginBottom: 6 }}>{h.purpose}</div>
                            <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                                <span style={{ fontSize: 12, color: t.textMuted, display: "flex", alignItems: "center", gap: 5 }}><Icon d={I.clock} size={12} />{h.time}</span>
                                <span style={{ fontSize: 12, color: t.textMuted, display: "flex", alignItems: "center", gap: 5 }}><Icon d={I.map} size={12} />{h.court}</span>
                                <span style={{ fontSize: 12, color: t.textMuted, display: "flex", alignItems: "center", gap: 5 }}><Icon d={I.user} size={12} />{h.judge}</span>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {past.length > 0 && (
                <div>
                    <div style={{ fontSize: 11, fontWeight: 700, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>Past Hearings</div>
                    {past.map(h => (
                        <Card key={h.id} style={{ padding: 14, opacity: .8, marginBottom: 8 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                <div>
                                    <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{h.purpose}</div>
                                    <div style={{ fontSize: 11, color: t.textMuted, marginTop: 3 }}>{h.date} · {h.court}</div>
                                </div>
                                <div style={{ textAlign: "right" }}>
                                    <Badge type="gray">Concluded</Badge>
                                    {h.outcome && <div style={{ fontSize: 11, color: t.textMuted, marginTop: 4, maxWidth: 200, textAlign: "right" }}>{h.outcome}</div>}
                                </div>
                            </div>
                        </Card>
                    ))}
                </div>
            )}

            {hearings.length === 0 && (
                <Card style={{ padding: 40, textAlign: "center" }}>
                    <div style={{ fontSize: 13, color: t.textMuted }}>No hearings recorded yet.</div>
                </Card>
            )}
        </div>
    );
}

// ── Messages Tab ─────────────────────────────────────────────
function WorkspaceMessages({ msgs, c, setPage }) {
    const { t } = useTheme();
    const [selectedMsg, setSelectedMsg] = useState(msgs[0] || null);
    const [reply, setReply] = useState("");
    const [localThreads, setLocalThreads] = useState(() => {
        const init = {};
        msgs.forEach(m => { init[m.id] = [...m.thread]; });
        return init;
    });
    const msgEndRef = useRef(null);
    useEffect(() => { msgEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [selectedMsg, localThreads]);

    // Clear draft when switching conversation
    useEffect(() => { setReply(""); }, [selectedMsg]);

    const sendReply = () => {
        if (!reply.trim() || !selectedMsg) return;
        const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        setLocalThreads(prev => ({
            ...prev,
            [selectedMsg.id]: [...(prev[selectedMsg.id] || []), { who: "lawyer", text: reply.trim(), time: now }]
        }));
        setReply("");
    };

    if (msgs.length === 0) return (
        <Card style={{ padding: 48, textAlign: "center" }} className="fade-up">
            <Icon d={I.chat} size={28} style={{ color: t.textFaint, opacity: .3, display: "block", margin: "0 auto 12px" }} />
            <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 16 }}>No messages for this case yet.</div>
            <Btn variant="primary" size="sm" onClick={() => setPage("communications")}>Open Communications</Btn>
        </Card>
    );

    return (
        <div style={{ display: "flex", gap: 16, height: "calc(100vh - 320px)", minHeight: 320 }} className="fade-up">
            {/* Left list */}
            <div style={{ width: 260, flexShrink: 0, background: t.surface, borderRadius: 12, border: `1px solid ${t.border}`, overflow: "hidden" }}>
                {msgs.map(msg => {
                    const sel = selectedMsg?.id === msg.id;
                    return (
                        <div key={msg.id} onClick={() => setSelectedMsg(msg)}
                            style={{
                                display: "flex", alignItems: "center", gap: 10, padding: "12px 14px", cursor: "pointer",
                                borderBottom: `1px solid ${t.border}`, background: sel ? t.cardHi : t.surface,
                                borderLeft: sel ? `3px solid ${t.primary}` : "3px solid transparent", transition: "background .1s"
                            }}
                            onMouseEnter={e => { if (!sel) e.currentTarget.style.background = t.cardHi; }}
                            onMouseLeave={e => { if (!sel) e.currentTarget.style.background = t.surface; }}>
                            <div style={{ width: 38, height: 38, borderRadius: "50%", flexShrink: 0, background: avatarBg(msg.initials), display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700, color: "#fff" }}>{msg.initials}</div>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>{msg.client}</div>
                                <div style={{ fontSize: 11, color: t.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{msg.question}</div>
                                <div style={{ fontSize: 10, color: t.textFaint, marginTop: 2 }}>{msg.time}</div>
                            </div>
                            {msg.status === "Unanswered" && <div style={{ width: 7, height: 7, borderRadius: "50%", background: t.warn, flexShrink: 0 }} />}
                        </div>
                    );
                })}
            </div>

            {/* Right chat */}
            {selectedMsg && (
                <div style={{ flex: 1, background: t.surface, borderRadius: 12, border: `1px solid ${t.border}`, display: "flex", flexDirection: "column", overflow: "hidden" }}>
                    <div style={{ padding: "12px 16px", borderBottom: `1px solid ${t.border}`, display: "flex", alignItems: "center", gap: 10 }}>
                        <div style={{ width: 36, height: 36, borderRadius: "50%", flexShrink: 0, background: avatarBg(selectedMsg.initials), display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700, color: "#fff" }}>{selectedMsg.initials}</div>
                        <div>
                            <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>{selectedMsg.client}</div>
                            <div style={{ fontSize: 11, color: t.textMuted }}>Re: {c.id} — {c.title}</div>
                        </div>
                        <div style={{ flex: 1 }} />
                        <Btn variant="secondary" size="sm" onClick={() => setPage("communications")}><Icon d={I.externalLink} size={11} /> Full View</Btn>
                    </div>
                    <div style={{ flex: 1, overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 8, background: t.mode === "dark" ? "rgba(11,21,25,0.95)" : "rgba(234,240,234,0.95)" }}>
                        {(localThreads[selectedMsg.id] || []).map((msg, i) => {
                            const isL = msg.who === "lawyer";
                            return (
                                <div key={`${selectedMsg.id}-${i}`} style={{ display: "flex", justifyContent: isL ? "flex-end" : "flex-start" }}>
                                    <div style={{
                                        maxWidth: "60%", padding: "9px 13px", borderRadius: isL ? "10px 0 10px 10px" : "0 10px 10px 10px",
                                        background: isL ? t.primary : (t.mode === "dark" ? "rgba(26,44,52,0.95)" : t.surface),
                                        border: !isL ? `1px solid ${t.border}` : "none"
                                    }}>
                                        <div style={{ fontSize: 13, color: isL ? (t.mode === "dark" ? "#0D1E24" : "#fff") : t.text, lineHeight: 1.55 }}>{msg.text}</div>
                                        <div style={{ fontSize: 10, color: isL ? (t.mode === "dark" ? "rgba(13,30,36,0.55)" : "rgba(255,255,255,0.6)") : t.textFaint, marginTop: 3, textAlign: "right" }}>{msg.time}</div>
                                    </div>
                                </div>
                            );
                        })}
                        <div ref={msgEndRef} />
                    </div>
                    <div style={{ padding: "10px 14px", borderTop: `1px solid ${t.border}`, display: "flex", gap: 8 }}>
                        <input value={reply} onChange={e => setReply(e.target.value)}
                            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendReply(); } }}
                            placeholder="Type a reply..."
                            style={{ flex: 1, height: 38, border: `1px solid ${t.border}`, borderRadius: 10, background: t.inputBg, color: t.text, fontSize: 13, padding: "0 14px", outline: "none" }} />
                        <button onClick={sendReply}
                            style={{ width: 38, height: 38, borderRadius: "50%", border: "none", background: reply.trim() ? t.primary : t.cardHi, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
                            <Icon d={I.send} size={14} style={{ color: reply.trim() ? (t.mode === "dark" ? "#0D1E24" : "#fff") : t.textMuted }} />
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}

// ── AI Assistant Tab ─────────────────────────────────────────
function WorkspaceAI({ c, addNotif }) {
    const { t } = useTheme();
    const [msgs, setMsgs] = useState([]);
    const [query, setQuery] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [lastQuery, setLastQuery] = useState("");
    const bottomRef = useRef(null);
    useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

    const SYSTEM = `You are an expert Indian legal assistant. The lawyer is working on case "${c.id} — ${c.title}" (${c.type} case, ${c.court}). Client: ${c.client}. Next hearing: ${c.nextHearing}. Provide concise, case-relevant answers about Indian law. Reference specific acts and sections.`;

    const send = async (override) => {
        const q = (override || query).trim();
        if (!q || loading) return;
        setQuery(""); setError(null); setLastQuery(q);
        const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        if (!override) setMsgs(p => [...p, { role: "user", content: q, time: now }]);
        setLoading(true);
        try {
            const r = await fetch("https://api.anthropic.com/v1/messages", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    model: "claude-sonnet-4-20250514", max_tokens: 1000, system: SYSTEM,
                    messages: msgs.concat([{ role: "user", content: q }]).map(m => ({ role: m.role === "assistant" ? "assistant" : "user", content: m.content }))
                })
            });
            if (!r.ok) throw new Error(`API error ${r.status}`);
            const d = await r.json();
            const aiTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
            setMsgs(p => [...p, { role: "assistant", content: d.content?.[0]?.text || "No response.", time: aiTime }]);
        } catch (err) { setError(err.message || "Connection error"); }
        finally { setLoading(false); }
    };

    const hasMessages = msgs.length > 0;
    const prompts = [
        `Key legal sections for ${c.type.toLowerCase()} case`,
        `What to argue in the next hearing for ${c.id}`,
        `Recent precedents relevant to this case`,
        `Draft an argument outline for ${c.title}`,
    ];

    return (
        <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 320px)", minHeight: 340, background: t.card, borderRadius: 12, border: `1px solid ${t.border}`, overflow: "hidden" }} className="fade-up">
            {/* Context banner */}
            <div style={{ padding: "8px 16px", background: t.primaryGlow2, borderBottom: `1px solid ${t.primary}30`, display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                <div style={{ width: 20, height: 20, borderRadius: 6, background: t.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center" }}><Icon d={I.ai} size={11} style={{ color: t.primary }} /></div>
                <span style={{ fontSize: 11, color: t.primary, fontWeight: 600 }}>AI context loaded:</span>
                <span className="mono" style={{ fontSize: 11, color: t.primary }}>{c.id}</span>
                <span style={{ fontSize: 11, color: t.textMuted }}>— {c.title} · {c.type} · {c.court}</span>
            </div>
            {/* Messages */}
            <div style={{ flex: 1, overflowY: "auto", padding: hasMessages ? "16px 20px" : "0 20px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: hasMessages ? "flex-start" : "center" }}>
                {!hasMessages ? (
                    <div style={{ textAlign: "center", maxWidth: 520, width: "100%" }}>
                        <div className="serif" style={{ fontSize: 18, fontWeight: 700, color: t.text, marginBottom: 6 }}>AI Legal Assistant</div>
                        <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 20 }}>Ask anything about <strong style={{ color: t.primary }}>{c.title}</strong></div>
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
                            {prompts.map((p, i) => (
                                <button key={i} onClick={() => setQuery(p)}
                                    style={{ padding: "8px 14px", borderRadius: 50, border: `1px solid ${t.border}`, background: t.cardHi, color: t.textMuted, cursor: "pointer", fontSize: 12, transition: "all .15s" }}
                                    onMouseEnter={e => { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.color = t.primary; e.currentTarget.style.background = t.primaryGlow2; }}
                                    onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textMuted; e.currentTarget.style.background = t.cardHi; }}>
                                    {p}
                                </button>
                            ))}
                        </div>
                    </div>
                ) : (
                    <div style={{ width: "100%", maxWidth: 700, display: "flex", flexDirection: "column", gap: 14 }}>
                        {msgs.map((m, i) => (
                            <div key={i} style={{ display: "flex", flexDirection: m.role === "user" ? "row-reverse" : "row", gap: 10, alignItems: "flex-start" }} className="fade-in">
                                {m.role === "assistant" && <div style={{ width: 30, height: 30, borderRadius: 8, background: t.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}><Icon d={I.ai} size={14} style={{ color: t.primary }} /></div>}
                                <div style={{ maxWidth: "80%" }}>
                                    <div style={{
                                        background: m.role === "user" ? t.grad1 : t.surface, border: m.role === "assistant" ? `1px solid ${t.border}` : "none",
                                        borderRadius: m.role === "user" ? "14px 14px 4px 14px" : "14px 14px 14px 4px", padding: "10px 14px",
                                        fontSize: 13, lineHeight: 1.7, color: m.role === "user" ? (t.mode === "dark" ? "#111B1F" : "#fff") : t.text, whiteSpace: "pre-wrap"
                                    }}>{m.content}</div>
                                    {m.time && <div style={{ fontSize: 10, color: t.textFaint, marginTop: 3, textAlign: m.role === "user" ? "right" : "left" }}>{m.time}</div>}
                                </div>
                            </div>
                        ))}
                        {loading && <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                            <div style={{ width: 30, height: 30, borderRadius: 8, background: t.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}><Icon d={I.ai} size={14} style={{ color: t.primary }} /></div>
                            <div style={{ background: t.surface, border: `1px solid ${t.border}`, borderRadius: "14px 14px 14px 4px", padding: "12px 16px", display: "flex", gap: 5 }}>
                                {[0, 1, 2].map(d => <div key={d} style={{ width: 6, height: 6, borderRadius: "50%", background: t.primary, animation: `pulse 1.2s ease ${d * .2}s infinite` }} />)}
                            </div>
                        </div>}
                        {error && !loading && (
                            <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "10px 14px", borderRadius: 10, background: `${t.danger}12`, border: `1px solid ${t.danger}30` }}>
                                <Icon d={I.alert} size={13} style={{ color: t.danger }} />
                                <span style={{ fontSize: 12, color: t.danger, flex: 1 }}>Connection error</span>
                                <button onClick={() => send(lastQuery)} style={{ display: "flex", alignItems: "center", gap: 4, padding: "4px 10px", borderRadius: 6, border: `1px solid ${t.danger}`, background: "transparent", color: t.danger, cursor: "pointer", fontSize: 11 }}>
                                    <Icon d={I.refresh} size={11} /> Retry
                                </button>
                            </div>
                        )}
                        <div ref={bottomRef} />
                    </div>
                )}
            </div>
            {/* Input */}
            <div style={{ padding: "10px 16px", borderTop: `1px solid ${t.border}`, flexShrink: 0 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <input value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === "Enter" && !e.shiftKey && send()}
                        placeholder={`Ask about ${c.title}...`}
                        style={{ flex: 1, height: 38, border: `1px solid ${t.border}`, borderRadius: 10, background: t.inputBg, color: t.text, fontSize: 13, padding: "0 14px", outline: "none" }} />
                    <button onClick={() => send()} style={{ width: 38, height: 38, borderRadius: 10, border: "none", background: query.trim() ? t.primary : t.cardHi, cursor: query.trim() ? "pointer" : "default", display: "flex", alignItems: "center", justifyContent: "center", transition: "all .2s" }}>
                        <Icon d={I.send} size={14} style={{ color: query.trim() ? (t.mode === "dark" ? "#111B1F" : "#fff") : t.textMuted }} />
                    </button>
                </div>
            </div>
        </div>
    );
}

// ── Tasks Tab ────────────────────────────────────────────────
function WorkspaceTasks({ tasks, c }) {
    const { t } = useTheme();
    const [localTasks, setLocalTasks] = useState(tasks);
    const toggle = (id) => setLocalTasks(p => p.map(t => t.id === id ? { ...t, done: !t.done } : t));
    const pending = localTasks.filter(t => !t.done);
    const done = localTasks.filter(t => t.done);

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }} className="fade-up">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div className="serif" style={{ fontSize: 16, fontWeight: 600, color: t.text }}>Tasks — {pending.length} pending</div>
                <Btn variant="accent" size="sm"><Icon d={I.plus} size={12} /> Add Task</Btn>
            </div>

            {localTasks.length === 0 ? (
                <Card style={{ padding: 40, textAlign: "center" }}>
                    <div style={{ fontSize: 13, color: t.textMuted }}>No tasks for this case.</div>
                </Card>
            ) : (
                <>
                    {pending.length > 0 && (
                        <div>
                            <div style={{ fontSize: 11, fontWeight: 700, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>Pending ({pending.length})</div>
                            {pending.map(task => (
                                <div key={task.id} onClick={() => toggle(task.id)}
                                    style={{
                                        display: "flex", alignItems: "center", gap: 12, padding: "13px 16px", borderRadius: 10,
                                        background: t.card, border: `1px solid ${t.border}`, marginBottom: 7, cursor: "pointer",
                                        transition: "all .15s"
                                    }}
                                    onMouseEnter={e => e.currentTarget.style.borderColor = t.primary}
                                    onMouseLeave={e => e.currentTarget.style.borderColor = t.border}>
                                    <div style={{ width: 18, height: 18, borderRadius: 5, border: `2px solid ${t[PRIO[task.priority]] || t.border}`, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
                                    </div>
                                    <div style={{ flex: 1 }}>
                                        <div style={{ fontSize: 13, fontWeight: 500, color: t.text }}>{task.title}</div>
                                        <div style={{ fontSize: 11, color: t.textFaint, marginTop: 2 }}>Due {task.due}</div>
                                    </div>
                                    <Badge type={PRIO[task.priority]}>{task.priority}</Badge>
                                </div>
                            ))}
                        </div>
                    )}
                    {done.length > 0 && (
                        <div>
                            <div style={{ fontSize: 11, fontWeight: 700, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>Completed ({done.length})</div>
                            {done.map(task => (
                                <div key={task.id} onClick={() => toggle(task.id)}
                                    style={{
                                        display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", borderRadius: 10,
                                        background: t.card, border: `1px solid ${t.border}`, marginBottom: 6, cursor: "pointer", opacity: .6
                                    }}>
                                    <div style={{ width: 18, height: 18, borderRadius: 5, background: t.success, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
                                        <Icon d={I.check} size={10} style={{ color: "#fff" }} />
                                    </div>
                                    <div style={{ flex: 1 }}>
                                        <div style={{ fontSize: 13, color: t.textMuted, textDecoration: "line-through" }}>{task.title}</div>
                                        <div style={{ fontSize: 11, color: t.textFaint, marginTop: 2 }}>Due {task.due}</div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </>
            )}
        </div>
    );
}

const CASE_TABS = [
    { id: "overview", label: "Overview", emoji: "🏠" },
    { id: "documents", label: "Documents", emoji: "📄" },
    { id: "timeline", label: "Timeline", emoji: "🕐" },
    { id: "messages", label: "Messages", emoji: "💬" },
    { id: "tasks", label: "Tasks", emoji: "✅" },
];

// ─────────────────────────────────────────────
// SHARED HELPERS: Modal, Input (field), Select, Textarea, Toast
// ─────────────────────────────────────────────

function Modal({ title, subtitle, onClose, children, width = 560 }) {
    const { t } = useTheme();
    return (
        <div style={{ position: "fixed", inset: 0, zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.55)" }} onClick={onClose}>
            <div onClick={e => e.stopPropagation()} style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 16, padding: 26, width, maxWidth: "95vw", boxShadow: t.shadowCard, maxHeight: "90vh", overflowY: "auto" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                    <div>
                        <div style={{ fontSize: 17, fontWeight: 700, color: t.text, fontFamily: "Georgia,serif" }}>{title}</div>
                        {subtitle && <div style={{ fontSize: 12, color: t.textMuted, marginTop: 3 }}>{subtitle}</div>}
                    </div>
                    <button onClick={onClose} style={{ background: "none", border: "none", color: t.textMuted, cursor: "pointer", padding: 4, borderRadius: 6 }}><Icon d={I.x} size={16} /></button>
                </div>
                {children}
            </div>
        </div>
    );
}

function FieldInput({ label, value, onChange, type = "text", placeholder }) {
    const { t } = useTheme();
    return (
        <div>
            {label && <Label>{label}</Label>}
            <input type={type} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
                style={{ width: "100%", height: 40, border: `1px solid ${t.border}`, borderRadius: 9, background: t.inputBg, color: t.text, fontSize: 14, padding: "0 14px", outline: "none", boxSizing: "border-box" }} />
        </div>
    );
}

// Alias used inside tab components
const Input2 = FieldInput;

function Select({ label, value, onChange, options = [] }) {
    const { t } = useTheme();
    return (
        <div>
            {label && <Label>{label}</Label>}
            <div style={{ position: "relative" }}>
                <select value={value} onChange={e => onChange(e.target.value)}
                    style={{ width: "100%", height: 40, border: `1px solid ${t.border}`, borderRadius: 9, background: t.inputBg, color: t.text, fontSize: 14, padding: "0 32px 0 14px", outline: "none", appearance: "none", cursor: "pointer", boxSizing: "border-box" }}>
                    {options.map(o => <option key={o.value} value={o.value} style={{ background: t.surface }}>{o.label}</option>)}
                </select>
                <div style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none", color: t.textMuted }}><Icon d={I.chevronDown} size={14} /></div>
            </div>
        </div>
    );
}

function Textarea({ label, value, onChange, rows = 4, placeholder }) {
    const { t } = useTheme();
    return (
        <div>
            {label && <Label>{label}</Label>}
            <textarea value={value} onChange={e => onChange(e.target.value)} rows={rows} placeholder={placeholder}
                style={{ width: "100%", border: `1px solid ${t.border}`, borderRadius: 9, background: t.inputBg, color: t.text, fontSize: 14, padding: "9px 14px", outline: "none", resize: "vertical", lineHeight: 1.6, boxSizing: "border-box", fontFamily: "DM Sans, system-ui" }} />
        </div>
    );
}

function Toast({ msg }) {
    const { t } = useTheme();
    if (!msg) return null;
    return (
        <div style={{ position: "fixed", bottom: 28, left: "50%", transform: "translateX(-50%)", zIndex: 9999, background: t.card, border: `1px solid ${t.border}`, borderRadius: 10, padding: "10px 20px", fontSize: 13, color: t.text, boxShadow: t.shadowCard, animation: "fadeUp .25s ease" }}>
            {msg}
        </div>
    );
}

// ─────────────────────────────────────────────
// HEARINGS TAB
// ─────────────────────────────────────────────
function HearingsTab({ caseId, cases, setCases, hearings, setHearings, timeline, setTimeline }) {
    const { t: T } = useTheme();
    const c = cases.find(x => x.id === caseId);
    const cHearings = (hearings[caseId] || []).slice().sort((a, b) => new Date(b.date) - new Date(a.date));
    const [modal, setModal] = useState(null); // null | "add" | {id}
    const emptyForm = { date: "", time: "10:00", court: c?.court || "", judge: c?.judge || "", purpose: "", outcome: "", status: "upcoming" };
    const [form, setForm] = useState(emptyForm);
    const [toast, setToast] = useState(null);

    const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(null), 2500); };

    const openAdd = () => { setForm(emptyForm); setModal("add"); };
    const openEdit = (h) => { setForm({ ...h }); setModal(h.id); };

    const save = () => {
        if (!form.date || !form.purpose || !form.court) { showToast("⚠️ Date, court and purpose are required"); return; }
        const isEdit = modal !== "add";
        const updated = { ...form, id: isEdit ? modal : "H-" + Date.now(), status: form.outcome ? "past" : "upcoming" };

        setHearings(prev => {
            const list = prev[caseId] || [];
            return { ...prev, [caseId]: isEdit ? list.map(h => h.id === modal ? updated : h) : [...list, updated] };
        });

        // Update case next hearing date
        if (!form.outcome) {
            setCases(prev => prev.map(x => x.id === caseId ? { ...x, nextHearing: form.date } : x));
        }

        // Add to timeline
        if (!isEdit) {
            const tlEntry = { id: "TL-" + Date.now(), date: form.date, type: "hearing", text: `Hearing scheduled — ${form.purpose}`, icon: "⚖️" };
            setTimeline(prev => ({ ...prev, [caseId]: [tlEntry, ...(prev[caseId] || [])] }));
        }

        showToast(isEdit ? "✅ Hearing updated" : "✅ Hearing scheduled");
        setModal(null);
    };

    const remove = (id) => {
        setHearings(prev => ({ ...prev, [caseId]: (prev[caseId] || []).filter(h => h.id !== id) }));
        showToast("🗑 Hearing removed");
    };

    const markOutcome = (h) => { setForm({ ...h }); setModal(h.id); };

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: T.text, fontFamily: "Georgia, serif" }}>Hearings</div>
                    <div style={{ fontSize: 12, color: T.textMuted, marginTop: 2 }}>{cHearings.filter(h => h.status === "upcoming").length} upcoming · {cHearings.filter(h => h.status === "past").length} past</div>
                </div>
                <Btn onClick={openAdd}>+ Schedule Hearing</Btn>
            </div>

            {/* Upcoming */}
            {cHearings.filter(h => h.status === "upcoming").length > 0 && (
                <div>
                    <div style={{ fontSize: 11, fontWeight: 700, color: T.primary, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>📅 Upcoming</div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                        {cHearings.filter(h => h.status === "upcoming").map(h => (
                            <Card key={h.id} style={{ padding: 18, borderLeft: `4px solid ${T.primary}` }}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
                                    <div style={{ flex: 1 }}>
                                        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                                            <div style={{ fontSize: 16, fontWeight: 700, color: T.primary }}>{fmtDate(h.date)}</div>
                                            <span style={{ fontSize: 12, color: T.textMuted, background: T.primaryGlow2, padding: "2px 8px", borderRadius: 6, fontWeight: 600 }}>{fmtTime(h.time)}</span>
                                            <Badge type="info">Upcoming</Badge>
                                        </div>
                                        <div style={{ fontSize: 14, fontWeight: 600, color: T.text, marginBottom: 8 }}>{h.purpose}</div>
                                        <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
                                            <span style={{ fontSize: 12, color: T.textMuted, display: "flex", alignItems: "center", gap: 5 }}>🏛 {h.court}</span>
                                            <span style={{ fontSize: 12, color: T.textMuted, display: "flex", alignItems: "center", gap: 5 }}>👨‍⚖️ {h.judge}</span>
                                        </div>
                                    </div>
                                    <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                                        <Btn variant="secondary" size="sm" onClick={() => openEdit(h)}>✏️ Edit</Btn>
                                        <Btn variant="success" size="sm" onClick={() => markOutcome(h)}>📋 Add Outcome</Btn>
                                        <Btn variant="danger" size="sm" onClick={() => remove(h.id)}>🗑</Btn>
                                    </div>
                                </div>
                            </Card>
                        ))}
                    </div>
                </div>
            )}

            {/* Past */}
            {cHearings.filter(h => h.status === "past").length > 0 && (
                <div>
                    <div style={{ fontSize: 11, fontWeight: 700, color: T.textMuted, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>🕐 Past Hearings</div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                        {cHearings.filter(h => h.status === "past").map(h => (
                            <Card key={h.id} style={{ padding: 16, opacity: 0.8 }}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
                                    <div style={{ flex: 1 }}>
                                        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 5 }}>
                                            <div style={{ fontSize: 14, fontWeight: 600, color: T.textMuted }}>{fmtDate(h.date)}</div>
                                            <span style={{ fontSize: 11, color: T.textFaint }}>{fmtTime(h.time)}</span>
                                            <Badge type="gray">Past</Badge>
                                        </div>
                                        <div style={{ fontSize: 13, color: T.text, marginBottom: 6 }}>{h.purpose}</div>
                                        <div style={{ display: "flex", gap: 14 }}>
                                            <span style={{ fontSize: 11, color: T.textFaint }}>🏛 {h.court}</span>
                                            <span style={{ fontSize: 11, color: T.textFaint }}>👨‍⚖️ {h.judge}</span>
                                        </div>
                                        {h.outcome && (
                                            <div style={{ marginTop: 8, padding: "7px 12px", background: `${T.warn}14`, border: `1px solid ${T.warn}35`, borderRadius: 8, fontSize: 12, color: T.warn, display: "inline-block" }}>
                                                📋 {h.outcome}
                                            </div>
                                        )}
                                    </div>
                                    <Btn variant="ghost" size="sm" onClick={() => openEdit(h)}>✏️</Btn>
                                </div>
                            </Card>
                        ))}
                    </div>
                </div>
            )}

            {cHearings.length === 0 && (
                <Card style={{ padding: 48, textAlign: "center" }}>
                    <div style={{ fontSize: 36, marginBottom: 10 }}>⚖️</div>
                    <div style={{ fontSize: 14, color: T.textMuted, marginBottom: 14 }}>No hearings recorded yet</div>
                    <Btn onClick={openAdd}>Schedule First Hearing</Btn>
                </Card>
            )}

            {/* Add / Edit Modal */}
            {modal && (
                <Modal title={modal === "add" ? "Schedule New Hearing" : "Edit Hearing"} subtitle={`Case: ${caseId}`} onClose={() => setModal(null)}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                            <Input label="Date *" type="date" value={form.date} onChange={v => setForm(p => ({ ...p, date: v }))} />
                            <Input label="Time" type="time" value={form.time} onChange={v => setForm(p => ({ ...p, time: v }))} />
                        </div>
                        <Input label="Court *" value={form.court} onChange={v => setForm(p => ({ ...p, court: v }))} placeholder="e.g. High Court Mumbai" />
                        <Input label="Judge / Presiding Officer" value={form.judge} onChange={v => setForm(p => ({ ...p, judge: v }))} placeholder="e.g. Hon. Justice Mehta" />
                        <Input label="Purpose / Agenda *" value={form.purpose} onChange={v => setForm(p => ({ ...p, purpose: v }))} placeholder="e.g. Evidence hearing — witness examination" />
                        <div style={{ borderTop: `1px dashed ${T.border}`, paddingTop: 14, marginTop: 2 }}>
                            <Textarea label="Outcome / Order (fill after hearing)" value={form.outcome} onChange={v => setForm(p => ({ ...p, outcome: v }))} rows={3} placeholder="Leave blank if hearing hasn't occurred yet..." />
                        </div>
                        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 6 }}>
                            <Btn variant="secondary" onClick={() => setModal(null)}>Cancel</Btn>
                            <Btn onClick={save}>{modal === "add" ? "Schedule Hearing" : "Save Changes"}</Btn>
                        </div>
                    </div>
                </Modal>
            )}
            <Toast msg={toast} />
        </div>
    );
}

// ─────────────────────────────────────────────
// DOCUMENTS TAB
// ─────────────────────────────────────────────
function DocumentsTab({ caseId, docs, setDocs, timeline, setTimeline }) {
    const { t: T } = useTheme();
    const { setPage, setActiveCase } = useCase();
    const cDocs = docs[caseId] || [];
    const [modal, setModal] = useState(null); // null | "add" | "view:{id}" | "edit:{id}"
    const [editDoc, setEditDoc] = useState(null);
    const [toast, setToast] = useState(null);
    const emptyForm = { title: "", type: "Plaint", status: "Draft", content: "" };
    const [form, setForm] = useState(emptyForm);

    const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(null), 2500); };

    const docTypes = ["Plaint", "Written Statement", "Vakalatnama", "Affidavit", "Agreement", "Legal Notice", "Application", "Order", "Judgement", "Other"].map(v => ({ value: v, label: v }));
    const docStatuses = ["Draft", "Under Review", "Approved", "Final"].map(v => ({ value: v, label: v }));
    const DSB = { Draft: "gray", "Under Review": "warn", Approved: "success", Final: "primary" };

    const openAdd = () => { setForm(emptyForm); setModal("add"); };
    const openEdit = (d) => { setForm({ ...d }); setEditDoc(d); setModal("edit"); };
    const openView = (d) => { setEditDoc(d); setModal("view"); };

    const save = () => {
        if (!form.title.trim() || !form.content.trim()) { showToast("⚠️ Title and content are required"); return; }
        const today = new Date().toISOString().split("T")[0];
        if (modal === "add") {
            const newDoc = { ...form, id: "DOC-" + Date.now(), modified: today };
            setDocs(prev => ({ ...prev, [caseId]: [...(prev[caseId] || []), newDoc] }));
            const tlEntry = { id: "TL-" + Date.now(), date: today, type: "document", text: `Document added — ${form.title}`, icon: "📄" };
            setTimeline(prev => ({ ...prev, [caseId]: [tlEntry, ...(prev[caseId] || [])] }));
            showToast("✅ Document added");
        } else {
            setDocs(prev => ({ ...prev, [caseId]: (prev[caseId] || []).map(d => d.id === editDoc.id ? { ...form, id: editDoc.id, modified: today } : d) }));
            showToast("✅ Document saved");
        }
        setModal(null);
    };

    const remove = (id) => {
        setDocs(prev => ({ ...prev, [caseId]: (prev[caseId] || []).filter(d => d.id !== id) }));
        showToast("🗑 Document removed");
    };

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: T.text, fontFamily: "Georgia, serif" }}>Documents</div>
                    <div style={{ fontSize: 12, color: T.textMuted, marginTop: 2 }}>{cDocs.length} document{cDocs.length !== 1 ? "s" : ""}</div>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                    <Btn variant="accent" onClick={openAdd}>+ Add Document</Btn>
                </div>
            </div>

            {cDocs.length === 0 ? (
                <Card style={{ padding: 48, textAlign: "center" }}>
                    <div style={{ fontSize: 36, marginBottom: 10 }}>📄</div>
                    <div style={{ fontSize: 14, color: T.textMuted, marginBottom: 14 }}>No documents yet</div>
                    <Btn onClick={openAdd}>Add First Document</Btn>
                </Card>
            ) : (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: 12 }}>
                    {cDocs.map(doc => (
                        <Card key={doc.id} style={{ padding: 18 }}>
                            <div style={{ display: "flex", gap: 12, alignItems: "flex-start", marginBottom: 12 }}>
                                <div style={{ width: 42, height: 42, borderRadius: 10, background: T.primaryGlow2, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20, flexShrink: 0 }}>📄</div>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontSize: 13, fontWeight: 700, color: T.text, marginBottom: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{doc.title}</div>
                                    <div style={{ fontSize: 11, color: T.textFaint }}>Modified {fmtDate(doc.modified)}</div>
                                    <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                                        <Badge type={DSB[doc.status]} style={{ fontSize: 10, padding: "2px 8px" }}>{doc.status}</Badge>
                                        <Badge type="gray" style={{ fontSize: 10, padding: "2px 8px" }}>{doc.type}</Badge>
                                    </div>
                                </div>
                            </div>
                            {/* Content preview */}
                            <div style={{ fontSize: 11, color: T.textFaint, background: T.bg, borderRadius: 8, padding: "8px 10px", marginBottom: 12, lineHeight: 1.5, overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", fontFamily: "monospace" }}>
                                {doc.content.slice(0, 120)}…
                            </div>
                            <div style={{ display: "flex", gap: 8 }}>
                                <Btn variant="secondary" size="sm" style={{ flex: 1 }} onClick={() => openView(doc)}>👁 View</Btn>
                                <Btn variant="accent" size="sm" style={{ flex: 1 }} onClick={() => openEdit(doc)}>✏️ Edit</Btn>
                                <Btn variant="danger" size="sm" onClick={() => remove(doc.id)}>🗑</Btn>
                            </div>
                        </Card>
                    ))}
                </div>
            )}

            {/* View Modal */}
            {modal === "view" && editDoc && (
                <Modal title={editDoc.title} subtitle={`${editDoc.type} · Last modified ${fmtDate(editDoc.modified)}`} onClose={() => setModal(null)} width={680}>
                    <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
                        <Badge type={DSB[editDoc.status]}>{editDoc.status}</Badge>
                        <Badge type="gray">{editDoc.type}</Badge>
                    </div>
                    <div style={{ background: T.bg, border: `1px solid ${T.border}`, borderRadius: 10, padding: 20, fontSize: 13, color: T.textDim, lineHeight: 1.8, whiteSpace: "pre-wrap", fontFamily: "Georgia, serif", minHeight: 200 }}>
                        {editDoc.content}
                    </div>
                    <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>
                        <Btn variant="secondary" onClick={() => setModal(null)}>Close</Btn>
                        <Btn onClick={() => openEdit(editDoc)}>✏️ Edit Document</Btn>
                    </div>
                </Modal>
            )}

            {/* Add / Edit Modal */}
            {(modal === "add" || modal === "edit") && (
                <Modal title={modal === "add" ? "Add Document" : "Edit Document"} subtitle={`Case: ${caseId}`} onClose={() => setModal(null)} width={700}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                        <Input label="Document Title *" value={form.title} onChange={v => setForm(p => ({ ...p, title: v }))} placeholder="e.g. Plaint — Singh vs. Municipal Corp." />
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                            <Select label="Document Type" value={form.type} onChange={v => setForm(p => ({ ...p, type: v }))} options={docTypes} />
                            <Select label="Status" value={form.status} onChange={v => setForm(p => ({ ...p, status: v }))} options={docStatuses} />
                        </div>
                        <Textarea label="Document Content *" value={form.content} onChange={v => setForm(p => ({ ...p, content: v }))} rows={12} placeholder="Enter the full text of the document here..." />
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
                            <Btn
                                variant="accent"
                                onClick={() => {
                                    setActiveCase(caseId);
                                    setModal(null);
                                    setPage("doc-automation");
                                }}>
                                <Icon d={I.wand} size={13} /> Generate with AI
                            </Btn>
                            <div style={{ display: "flex", gap: 10 }}>
                                <Btn variant="secondary" onClick={() => setModal(null)}>Cancel</Btn>
                                <Btn onClick={save}>{modal === "add" ? "Add Document" : "Save Changes"}</Btn>
                            </div>
                        </div>
                    </div>
                </Modal>
            )}
            <Toast msg={toast} />
        </div>
    );
}

// ─────────────────────────────────────────────
// TIMELINE TAB
// ─────────────────────────────────────────────
function TimelineTab({ caseId, timeline, setTimeline, cases }) {
    const { t: T } = useTheme();
    const c = cases.find(x => x.id === caseId);
    const entries = (timeline[caseId] || []).slice().sort((a, b) => new Date(b.date) - new Date(a.date));
    const [modal, setModal] = useState(false);
    const [editEntry, setEditEntry] = useState(null);
    const [toast, setToast] = useState(null);
    const emptyForm = { date: new Date().toISOString().split("T")[0], type: "note", text: "", icon: "📝" };
    const [form, setForm] = useState(emptyForm);

    const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(null), 2500); };

    const openAdd = () => { setForm(emptyForm); setEditEntry(null); setModal(true); };
    const openEdit = (e) => { setForm({ ...e }); setEditEntry(e); setModal(true); };

    const save = () => {
        if (!form.text.trim() || !form.date) { showToast("⚠️ Date and description are required"); return; }
        const icon = typeIcon[form.type] || "📝";
        const entry = { ...form, icon, id: editEntry ? editEntry.id : "TL-" + Date.now() };
        setTimeline(prev => {
            const list = prev[caseId] || [];
            return { ...prev, [caseId]: editEntry ? list.map(e => e.id === editEntry.id ? entry : e) : [entry, ...list] };
        });
        showToast(editEntry ? "✅ Entry updated" : "✅ Timeline entry added");
        setModal(false);
    };

    const remove = (id) => {
        setTimeline(prev => ({ ...prev, [caseId]: (prev[caseId] || []).filter(e => e.id !== id) }));
        showToast("🗑 Entry removed");
    };

    const typeOptions = ["hearing", "document", "task", "filed", "milestone", "note"].map(v => ({ value: v, label: `${typeIcon[v]} ${v.charAt(0).toUpperCase() + v.slice(1)}` }));

    // Group by month
    const grouped = entries.reduce((acc, e) => {
        const key = new Date(e.date).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
        if (!acc[key]) acc[key] = [];
        acc[key].push(e);
        return acc;
    }, {});

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: T.text, fontFamily: "Georgia, serif" }}>Case Timeline</div>
                    <div style={{ fontSize: 12, color: T.textMuted, marginTop: 2 }}>Full chronological history of this case · {entries.length} entries</div>
                </div>
                <Btn onClick={openAdd}>+ Add Entry</Btn>
            </div>

            {/* Stats bar */}
            <div style={{ display: "flex", gap: 10 }}>
                {Object.entries(typeIcon).map(([type, icon]) => {
                    const cnt = entries.filter(e => e.type === type).length;
                    if (!cnt) return null;
                    return (
                        <div key={type} style={{ display: "flex", alignItems: "center", gap: 5, padding: "5px 12px", borderRadius: 100, background: `${typeColor[type]}15`, border: `1px solid ${typeColor[type]}30`, fontSize: 12, color: typeColor[type], fontWeight: 600 }}>
                            {icon} {cnt} {type}
                        </div>
                    );
                })}
            </div>

            {entries.length === 0 ? (
                <Card style={{ padding: 48, textAlign: "center" }}>
                    <div style={{ fontSize: 36, marginBottom: 10 }}>🕐</div>
                    <div style={{ fontSize: 14, color: T.textMuted, marginBottom: 14 }}>No timeline entries yet</div>
                    <Btn onClick={openAdd}>Add First Entry</Btn>
                </Card>
            ) : (
                <div>
                    {Object.entries(grouped).map(([month, monthEntries]) => (
                        <div key={month} style={{ marginBottom: 24 }}>
                            <div style={{ fontSize: 11, fontWeight: 700, color: T.textFaint, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 12, paddingLeft: 22 }}>{month}</div>
                            <div style={{ position: "relative", paddingLeft: 28 }}>
                                <div style={{ position: "absolute", left: 9, top: 0, bottom: 0, width: 2, background: `linear-gradient(to bottom, ${T.border}, transparent)`, borderRadius: 2 }} />
                                {monthEntries.map((e, i) => (
                                    <div key={e.id} style={{ position: "relative", marginBottom: 12 }}>
                                        <div style={{ position: "absolute", left: -25, top: 10, width: 12, height: 12, borderRadius: "50%", background: typeColor[e.type] || T.textMuted, border: `2px solid ${T.bg}`, boxShadow: `0 0 0 2px ${(typeColor[e.type] || T.textMuted)}40`, zIndex: 1 }} />
                                        <Card style={{ padding: "12px 16px" }}>
                                            <div style={{ display: "flex", alignItems: "flex-start", gap: 10, justifyContent: "space-between" }}>
                                                <div style={{ display: "flex", gap: 10, alignItems: "flex-start", flex: 1 }}>
                                                    <span style={{ fontSize: 18, flexShrink: 0, lineHeight: 1.3 }}>{e.icon}</span>
                                                    <div>
                                                        <div style={{ fontSize: 13, color: T.text, fontWeight: 500, lineHeight: 1.4 }}>{e.text}</div>
                                                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
                                                            <span style={{ fontSize: 11, color: T.textFaint }}>{fmtDate(e.date)}</span>
                                                            <span style={{ fontSize: 10, padding: "1px 7px", borderRadius: 100, background: `${typeColor[e.type] || T.textFaint}18`, color: typeColor[e.type] || T.textFaint, border: `1px solid ${typeColor[e.type] || T.textFaint}25`, fontWeight: 600 }}>{e.type}</span>
                                                        </div>
                                                    </div>
                                                </div>
                                                <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                                                    <button onClick={() => openEdit(e)} style={{ background: "none", border: "none", cursor: "pointer", color: T.textFaint, fontSize: 13, padding: "3px 6px", borderRadius: 6, transition: "color .12s" }}
                                                        onMouseEnter={e2 => e2.currentTarget.style.color = T.primary}
                                                        onMouseLeave={e2 => e2.currentTarget.style.color = T.textFaint}>✏️</button>
                                                    <button onClick={() => remove(e.id)} style={{ background: "none", border: "none", cursor: "pointer", color: T.textFaint, fontSize: 13, padding: "3px 6px", borderRadius: 6, transition: "color .12s" }}
                                                        onMouseEnter={e2 => e2.currentTarget.style.color = T.danger}
                                                        onMouseLeave={e2 => e2.currentTarget.style.color = T.textFaint}>🗑</button>
                                                </div>
                                            </div>
                                        </Card>
                                    </div>
                                ))}
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {modal && (
                <Modal title={editEntry ? "Edit Timeline Entry" : "Add Timeline Entry"} subtitle={`Case: ${caseId}`} onClose={() => setModal(false)}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                            <Input label="Date *" type="date" value={form.date} onChange={v => setForm(p => ({ ...p, date: v }))} />
                            <Select label="Entry Type" value={form.type} onChange={v => setForm(p => ({ ...p, type: v }))} options={typeOptions} />
                        </div>
                        <Textarea label="Description *" value={form.text} onChange={v => setForm(p => ({ ...p, text: v }))} rows={3} placeholder="Describe what happened or what was done..." />
                        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
                            <Btn variant="secondary" onClick={() => setModal(false)}>Cancel</Btn>
                            <Btn onClick={save}>{editEntry ? "Save Changes" : "Add to Timeline"}</Btn>
                        </div>
                    </div>
                </Modal>
            )}
            <Toast msg={toast} />
        </div>
    );
}

// ─────────────────────────────────────────────
// CASE WORKSPACE
// ─────────────────────────────────────────────
function CaseWorkspace({ caseId, cases, setCases, hearings, setHearings, docs, setDocs, timeline, setTimeline, onBack }) {
    const { t: T } = useTheme();
    const [tab, setTab] = useState("overview");
    const c = cases.find(x => x.id === caseId);
    if (!c) return null;

    const cHearings = hearings[caseId] || [];
    const cDocs = docs[caseId] || [];
    const cTimeline = timeline[caseId] || [];
    const nextHearing = cHearings.filter(h => h.status === "upcoming").sort((a, b) => new Date(a.date) - new Date(b.date))[0];

    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden", background: T.bg, fontFamily: "'DM Sans', system-ui, sans-serif" }}>

            {/* Header */}
            <div style={{ flexShrink: 0, background: T.surface, borderBottom: `1px solid ${T.border}` }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 22px 0", borderBottom: `1px solid ${T.border}40` }}>
                    <button onClick={onBack} style={{ display: "flex", alignItems: "center", gap: 4, background: "none", border: "none", cursor: "pointer", color: T.textMuted, fontSize: 13, padding: "3px 8px", borderRadius: 6, fontFamily: "inherit" }}
                        onMouseEnter={e => e.currentTarget.style.color = T.primary}
                        onMouseLeave={e => e.currentTarget.style.color = T.textMuted}>
                        ← Cases
                    </button>
                    <span style={{ color: T.border }}>/</span>
                    <span style={{ fontSize: 12, color: T.primary, fontFamily: "monospace", fontWeight: 700 }}>{c.id}</span>
                    <span style={{ fontSize: 12, color: T.textMuted, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.title}</span>
                    <Badge type={CSB[c.status]}>{c.status}</Badge>
                    {c.urgent && <Badge type="danger">🔴 Urgent</Badge>}
                </div>

                <div style={{ display: "flex", alignItems: "flex-start", gap: 16, padding: "14px 22px 0" }}>
                    <div style={{ width: 44, height: 44, borderRadius: 12, background: T.grad1, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, fontSize: 20 }}>⚖️</div>
                    <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 19, fontWeight: 700, color: T.text, fontFamily: "Georgia, serif" }}>{c.title}</div>
                        <div style={{ display: "flex", gap: 14, marginTop: 5, flexWrap: "wrap" }}>
                            {[["👤", c.client], ["🏛", c.court], ["📁", c.type], ["💰", c.value]].map(([ic, val]) => (
                                <span key={val} style={{ fontSize: 12, color: T.textMuted, display: "flex", alignItems: "center", gap: 5 }}>{ic} {val}</span>
                            ))}
                        </div>
                    </div>
                    <div style={{ display: "flex", gap: 0, borderLeft: `1px solid ${T.border}`, flexShrink: 0 }}>
                        {[
                            ["Next Hearing", nextHearing ? fmtDate(nextHearing.date) : "None", T.primary],
                            ["Docs", cDocs.length, T.info],
                            ["Hearings", cHearings.length, T.textMuted],
                            ["Timeline", cTimeline.length, T.textMuted],
                        ].map(([l, v, clr]) => (
                            <div key={l} style={{ textAlign: "center", padding: "0 16px", borderRight: `1px solid ${T.border}` }}>
                                <div style={{ fontSize: 10, fontWeight: 700, color: T.textFaint, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 3 }}>{l}</div>
                                <div style={{ fontSize: 13, fontWeight: 700, color: clr }}>{v}</div>
                            </div>
                        ))}
                    </div>
                </div>

                <div style={{ display: "flex", gap: 0, padding: "0 14px", marginTop: 10 }}>
                    {CASE_TABS.map(tb => {
                        const active = tab === tb.id;
                        return (
                            <button key={tb.id} onClick={() => setTab(tb.id)}
                                style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 18px", border: "none", background: "none", cursor: "pointer", fontSize: 15, fontWeight: active ? 700 : 600, color: active ? T.primary : T.textDim, borderBottom: active ? `3px solid ${T.primary}` : "3px solid transparent", transition: "all .15s", marginBottom: "-1px", fontFamily: "inherit" }}>
                                <span style={{ fontSize: 16 }}>{tb.emoji}</span> {tb.label}
                            </button>
                        );
                    })}
                </div>
            </div>

            <div style={{ flex: 1, overflowY: "auto", padding: 22 }}>
                {tab === "overview" && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12 }}>
                            {[
                                { l: "Documents", v: cDocs.length, c: T.primary, emoji: "📄", gotoTab: "documents" },
                                { l: "Hearings", v: cHearings.length, c: T.info, emoji: "⚖️", gotoTab: "hearings" },
                                { l: "Upcoming", v: cHearings.filter(h => h.status === "upcoming").length, c: T.warn, emoji: "📅", gotoTab: "hearings" },
                                { l: "Timeline Events", v: cTimeline.length, c: T.textMuted, emoji: "🕐", gotoTab: "timeline" },
                            ].map(s => (
                                <Card key={s.l} style={{ padding: 16, cursor: "pointer" }} onClick={() => setTab(s.gotoTab)}>
                                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                                        <div>
                                            <div style={{ fontSize: 11, color: T.textMuted, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 600 }}>{s.l}</div>
                                            <div style={{ fontSize: 28, fontWeight: 700, color: s.c }}>{s.v}</div>
                                        </div>
                                        <div style={{ width: 34, height: 34, borderRadius: 10, background: `${s.c}18`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>{s.emoji}</div>
                                    </div>
                                </Card>
                            ))}
                        </div>

                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
                            {/* Next Hearing */}
                            <Card style={{ padding: 18 }}>
                                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
                                    <div style={{ fontSize: 14, fontWeight: 700, color: T.text, fontFamily: "Georgia, serif" }}>Next Hearing</div>
                                    <button onClick={() => setTab("hearings")} style={{ fontSize: 11, color: T.primary, background: "none", border: "none", cursor: "pointer" }}>Manage →</button>
                                </div>
                                {nextHearing ? (
                                    <div style={{ padding: 14, borderRadius: 10, background: T.primaryGlow2, border: `1px solid ${T.primary}30` }}>
                                        <div style={{ fontSize: 18, fontWeight: 700, color: T.primary }}>{fmtDate(nextHearing.date)}</div>
                                        <div style={{ fontSize: 13, fontWeight: 600, color: T.text, marginTop: 4 }}>{nextHearing.purpose}</div>
                                        <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
                                            <span style={{ fontSize: 11, color: T.textMuted }}>🕐 {fmtTime(nextHearing.time)}</span>
                                            <span style={{ fontSize: 11, color: T.textMuted }}>🏛 {nextHearing.court}</span>
                                        </div>
                                    </div>
                                ) : (
                                    <div style={{ textAlign: "center", padding: "20px 0" }}>
                                        <div style={{ fontSize: 12, color: T.textFaint, marginBottom: 10 }}>No upcoming hearings</div>
                                        <Btn variant="accent" size="sm" onClick={() => setTab("hearings")}>Schedule One</Btn>
                                    </div>
                                )}
                            </Card>

                            {/* Recent Docs */}
                            <Card style={{ padding: 18 }}>
                                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
                                    <div style={{ fontSize: 14, fontWeight: 700, color: T.text, fontFamily: "Georgia, serif" }}>Recent Documents</div>
                                    <button onClick={() => setTab("documents")} style={{ fontSize: 11, color: T.primary, background: "none", border: "none", cursor: "pointer" }}>Manage →</button>
                                </div>
                                {cDocs.slice(0, 3).map(doc => {
                                    const DSB = { Draft: "gray", "Under Review": "warn", Approved: "success", Final: "primary" };
                                    return (
                                        <div key={doc.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderBottom: `1px solid ${T.border}` }}>
                                            <span style={{ fontSize: 14 }}>📄</span>
                                            <div style={{ flex: 1, minWidth: 0 }}>
                                                <div style={{ fontSize: 12, color: T.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 500 }}>{doc.title}</div>
                                                <div style={{ fontSize: 10, color: T.textFaint }}>{doc.type}</div>
                                            </div>
                                            <Badge type={DSB[doc.status]} style={{ fontSize: 10, padding: "1px 7px" }}>{doc.status}</Badge>
                                        </div>
                                    );
                                })}
                                {cDocs.length === 0 && <div style={{ fontSize: 12, color: T.textFaint, padding: "12px 0", textAlign: "center" }}>No documents yet</div>}
                            </Card>
                        </div>

                        {/* Recent timeline */}
                        <Card style={{ padding: 18 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
                                <div style={{ fontSize: 14, fontWeight: 700, color: T.text, fontFamily: "Georgia, serif" }}>Recent Activity</div>
                                <button onClick={() => setTab("timeline")} style={{ fontSize: 11, color: T.primary, background: "none", border: "none", cursor: "pointer" }}>Full Timeline →</button>
                            </div>
                            <div style={{ position: "relative", paddingLeft: 22 }}>
                                <div style={{ position: "absolute", left: 7, top: 0, bottom: 0, width: 2, background: `linear-gradient(to bottom, ${T.primary}80, transparent)`, borderRadius: 2 }} />
                                {cTimeline.slice(0, 4).map(e => (
                                    <div key={e.id} style={{ position: "relative", marginBottom: 14 }}>
                                        <div style={{ position: "absolute", left: -18, top: 5, width: 10, height: 10, borderRadius: "50%", background: typeColor[e.type] || T.textMuted, border: `2px solid ${T.bg}` }} />
                                        <div style={{ fontSize: 13, color: T.text }}>{e.icon} {e.text}</div>
                                        <div style={{ fontSize: 11, color: T.textFaint, marginTop: 2 }}>{fmtDate(e.date)}</div>
                                    </div>
                                ))}
                                {cTimeline.length === 0 && <div style={{ fontSize: 12, color: T.textFaint, paddingLeft: 4 }}>No activity recorded</div>}
                            </div>
                        </Card>
                    </div>
                )}

                {tab === "hearings" && (
                    <HearingsTab caseId={caseId} cases={cases} setCases={setCases} hearings={hearings} setHearings={setHearings} timeline={timeline} setTimeline={setTimeline} />
                )}
                {tab === "documents" && (
                    <DocumentsTab caseId={caseId} docs={docs} setDocs={setDocs} timeline={timeline} setTimeline={setTimeline} />
                )}
                {tab === "timeline" && (
                    <TimelineTab caseId={caseId} timeline={timeline} setTimeline={setTimeline} cases={cases} />
                )}
                {tab === "messages" && <WorkspaceMessages msgs={qData.filter(q => q.case === caseId)} c={c} setPage={() => { }} />}
                {tab === "tasks" && <WorkspaceTasks tasks={tasksData.filter(t => t.case === caseId)} c={c} />}
            </div>
        </div>
    );
}

// ─────────────────────────────────────────────
// CASES LIST
// ─────────────────────────────────────────────
function CasesList({ cases, onOpen }) {
    const { t: T } = useTheme();
    const [search, setSearch] = useState("");
    const [statusF, setStatusF] = useState("All");
    const [sort, setSort] = useState({ field: "id", dir: "asc" });

    const statuses = ["All", "Filed", "Under Hearing", "Adjourned", "Closed"];
    const filtered = cases.filter(c =>
        (statusF === "All" || c.status === statusF) &&
        (c.title.toLowerCase().includes(search.toLowerCase()) || c.id.toLowerCase().includes(search.toLowerCase()) || c.client.toLowerCase().includes(search.toLowerCase()))
    ).sort((a, b) => sort.dir === "asc" ? (a[sort.field] || "").localeCompare(b[sort.field] || "") : (b[sort.field] || "").localeCompare(a[sort.field] || ""));

    const stats = [
        { l: "Total", v: cases.length, c: T.text, f: null },
        { l: "Under Hearing", v: cases.filter(c => c.status === "Under Hearing").length, c: T.info, f: "Under Hearing" },
        { l: "Filed", v: cases.filter(c => c.status === "Filed").length, c: T.success, f: "Filed" },
        { l: "Adjourned", v: cases.filter(c => c.status === "Adjourned").length, c: T.warn, f: "Adjourned" },
        { l: "Closed", v: cases.filter(c => c.status === "Closed").length, c: T.textMuted, f: "Closed" },
    ];

    return (
        <div style={{ padding: 22, display: "flex", flexDirection: "column", gap: 18, height: "100%", overflowY: "auto", background: T.bg, fontFamily: "'DM Sans', system-ui, sans-serif" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                    <div style={{ fontSize: 22, fontWeight: 700, color: T.text, fontFamily: "Georgia, serif" }}>Case Management</div>
                    <div style={{ fontSize: 13, color: T.textMuted, marginTop: 3 }}>Track and manage all legal cases</div>
                </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 10 }}>
                {stats.map(s => (
                    <Card key={s.l} style={{ padding: "14px 16px", cursor: s.f ? "pointer" : undefined, border: statusF === s.f ? `1px solid ${s.c}60` : undefined }} onClick={() => s.f && setStatusF(s.f === statusF ? "All" : s.f)}>
                        <div style={{ fontSize: 11, color: T.textMuted, marginBottom: 4, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>{s.l}</div>
                        <div style={{ fontSize: 28, fontWeight: 700, color: s.c, lineHeight: 1 }}>{s.v}</div>
                    </Card>
                ))}
            </div>

            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <div style={{ position: "relative" }}>
                    <span style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: T.textMuted, fontSize: 13 }}>🔍</span>
                    <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search cases..."
                        style={{ height: 38, border: `1px solid ${T.border}`, borderRadius: 9, background: "rgba(44,96,110,0.2)", color: T.text, fontSize: 13, padding: "0 14px 0 34px", outline: "none", width: 220, fontFamily: "inherit" }} />
                </div>
                <select value={statusF} onChange={e => setStatusF(e.target.value)}
                    style={{ height: 38, border: `1px solid ${T.border}`, borderRadius: 9, background: "rgba(44,96,110,0.2)", color: statusF !== "All" ? T.primary : T.textMuted, fontSize: 13, padding: "0 14px", outline: "none", cursor: "pointer", fontFamily: "inherit" }}>
                    {statuses.map(o => <option key={o} value={o} style={{ background: T.surface }}>{o === "All" ? "All Statuses" : o}</option>)}
                </select>
                <span style={{ marginLeft: "auto", fontSize: 12, color: T.textMuted }}>{filtered.length} cases</span>
            </div>

            <Card style={{ overflow: "hidden" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                        <tr>
                            {[["id", "Case ID"], ["title", "Title"], ["client", "Client"], ["court", "Court"], ["status", "Status"], ["nextHearing", "Next Hearing"]].map(([f, l]) => (
                                <th key={f} onClick={() => setSort({ field: f, dir: sort.field === f && sort.dir === "asc" ? "desc" : "asc" })}
                                    style={{ padding: "12px 16px", textAlign: "left", fontWeight: 700, fontSize: 11, color: sort.field === f ? T.primary : T.textFaint, textTransform: "uppercase", letterSpacing: "0.07em", borderBottom: `1px solid ${T.border}`, cursor: "pointer", whiteSpace: "nowrap" }}>
                                    {l} {sort.field === f ? (sort.dir === "asc" ? "↑" : "↓") : "↕"}
                                </th>
                            ))}
                            <th style={{ padding: "12px 16px", borderBottom: `1px solid ${T.border}` }} />
                        </tr>
                    </thead>
                    <tbody>
                        {filtered.map(c => (
                            <tr key={c.id} onClick={() => onOpen(c.id)} style={{ borderBottom: `1px solid ${T.border}`, cursor: "pointer", transition: "background .12s" }}
                                onMouseEnter={e => e.currentTarget.style.background = "rgba(64,240,220,0.04)"}
                                onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                                <td style={{ padding: "13px 16px" }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                        {c.urgent && <span style={{ fontSize: 11 }}>🔴</span>}
                                        <span style={{ fontSize: 12, color: T.primary, fontWeight: 700, fontFamily: "monospace" }}>{c.id}</span>
                                    </div>
                                </td>
                                <td style={{ padding: "12px 16px", fontSize: 13, color: T.text, fontWeight: 600, maxWidth: 200 }}>
                                    <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.title}</div>
                                </td>
                                <td style={{ padding: "12px 16px", fontSize: 12, color: T.textMuted }}>{c.client}</td>
                                <td style={{ padding: "12px 16px", fontSize: 12, color: T.textMuted, whiteSpace: "nowrap" }}>{c.court}</td>
                                <td style={{ padding: "12px 16px" }}><Badge type={CSB[c.status]}>{c.status}</Badge></td>
                                <td style={{ padding: "12px 16px", fontSize: 12, color: c.nextHearing ? T.primary : T.textMuted, fontWeight: 600, whiteSpace: "nowrap" }}>{c.nextHearing ? fmtDate(c.nextHearing) : "—"}</td>
                                <td style={{ padding: "12px 16px" }}>
                                    <Btn variant="accent" size="sm" onClick={e => { e.stopPropagation(); onOpen(c.id); }}>Open →</Btn>
                                </td>
                            </tr>
                        ))}
                        {!filtered.length && (
                            <tr><td colSpan={7} style={{ padding: 40, textAlign: "center", color: T.textMuted, fontSize: 13 }}>No cases match filters</td></tr>
                        )}
                    </tbody>
                </table>
            </Card>
        </div>
    );
}

// ─────────────────────────────────────────────
// CASES PAGE — ties CasesList + CaseWorkspace
// ─────────────────────────────────────────────

function CasesPage() {
    const { t: T } = useTheme();
    const { activeCase, setActiveCase, openCaseId, setOpenCaseId, docs, setDocs, setPage } = useCase();
    const [cases, setCases] = useState(seedCases);
    const [hearings, setHearings] = useState(seedHearings);
    const [timeline, setTimeline] = useState(seedTimeline);

    const handleOpenCase = (caseId) => {
        setOpenCaseId(caseId);
        setActiveCase(caseId);
    };

    const handleBack = () => {
        setOpenCaseId(null);
    };

    if (openCaseId) {
        return (
            <CaseWorkspace
                caseId={openCaseId}
                cases={cases}
                setCases={setCases}
                hearings={hearings}
                setHearings={setHearings}
                docs={docs}
                setDocs={setDocs}
                timeline={timeline}
                setTimeline={setTimeline}
                onBack={handleBack}
            />
        );
    }

    return <CasesList cases={cases} onOpen={handleOpenCase} />;
}

export { CasesPage };
