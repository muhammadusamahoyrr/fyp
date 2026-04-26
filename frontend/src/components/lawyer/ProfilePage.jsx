'use client';
// Lawyer Profile Page — paste your code here
import { useState } from "react";
import { useTheme } from "./theme.js";
import { Card, Btn, Label, Badge, Divider, Input } from "./components.jsx";
import { Icon, I } from "./icons.jsx";

// ============================================================
// PROFILE + SETTINGS (concise)
// ============================================================
function ProfilePage() {
    const { t } = useTheme();
    return (
        <div style={{ maxWidth: 880 }}>
            <div className="fade-up" style={{ marginBottom: 18 }}><div className="serif" style={{ fontSize: 22, fontWeight: 700, color: t.text }}>Lawyer Profile</div><div style={{ fontSize: 13, color: t.textMuted, marginTop: 3 }}>Manage your professional profile and credentials</div></div>
            <div style={{ display: "grid", gridTemplateColumns: "250px 1fr", gap: 18 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                    <Card className="fade-up" style={{ padding: 20, textAlign: "center" }}>
                        <div style={{ position: "relative", width: 76, height: 76, margin: "0 auto 12px" }}>
                            <div style={{ width: 76, height: 76, borderRadius: "50%", background: t.grad1, display: "flex", alignItems: "center", justifyContent: "center" }}><span className="serif" style={{ fontSize: 22, fontWeight: 700, color: t.mode === "dark" ? "#111B1F" : "#fff" }}>JD</span></div>
                            <button style={{ position: "absolute", bottom: 0, right: 0, width: 24, height: 24, borderRadius: "50%", background: t.primary, border: "none", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }}><Icon d={I.camera} size={11} style={{ color: t.mode === "dark" ? "#111B1F" : "#fff" }} /></button>
                        </div>
                        <div className="serif" style={{ fontSize: 16, fontWeight: 700, color: t.text }}>John Doe</div>
                        <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 9 }}>Senior Advocate</div>
                        <div style={{ display: "flex", gap: 5, justifyContent: "center", flexWrap: "wrap" }}><Badge type="success">Verified</Badge><Badge type="gray">Civil Law</Badge></div>
                        <Divider />
                        {[{ ic: I.mail, v: "john.doe@lawfirm.com" }, { ic: I.phone, v: "+91 98765 43210" }, { ic: I.map, v: "Mumbai, Maharashtra" }, { ic: I.award, v: "MH-2015-4582" }, { ic: I.clock, v: "11 years experience" }].map((r, i) => (
                            <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12, color: t.textMuted, marginBottom: 6, textAlign: "left" }}><Icon d={r.ic} size={12} style={{ flexShrink: 0, color: t.primary }} /><span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.v}</span></div>
                        ))}
                    </Card>
                </div>
                <Card className="fade-up s1" style={{ padding: 22 }}>
                    <div className="serif" style={{ fontSize: 16, fontWeight: 600, color: t.text, marginBottom: 18 }}>Edit Profile</div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}><div><Label>First Name</Label><Input defaultValue="John" /></div><div><Label>Last Name</Label><Input defaultValue="Doe" /></div></div>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}><div><Label>Email</Label><Input defaultValue="john.doe@lawfirm.com" type="email" /></div><div><Label>Phone</Label><Input defaultValue="+91 98765 43210" /></div></div>
                        <div><Label>Specialization</Label><Input defaultValue="Civil Law, Property Law" /></div>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}><div><Label>Bar License</Label><Input defaultValue="MH-2015-4582" /></div><div><Label>Experience (yrs)</Label><Input defaultValue="11" type="number" /></div></div>
                        <div><Label>Bio</Label><Input type="textarea" defaultValue="Senior Advocate with 11 years of experience specializing in Civil, Property, and Commercial Law at the Bombay High Court." rows={3} /></div>
                        <div style={{ display: "flex", justifyContent: "flex-end" }}><Btn><Icon d={I.save} size={13} /> Save Changes</Btn></div>
                    </div>
                </Card>
            </div>
        </div>
    );
}

export { ProfilePage };
