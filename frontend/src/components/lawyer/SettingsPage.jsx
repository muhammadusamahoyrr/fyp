'use client';
import { useState } from "react";
import { useTheme } from "./theme.js";
import { useCase } from "./theme.js";
import { Card, Btn, Label, Input, Divider } from "./components.jsx";
import { Icon, I } from "./icons.jsx";

function SettingsPage() {
    const { t } = useTheme();
    const { setPage } = useCase();
    return (
        <div style={{ maxWidth: 620 }}>
            <div className="fade-up" style={{ marginBottom: 18 }}><div className="serif" style={{ fontSize: 22, fontWeight: 700, color: t.text }}>Settings</div><div style={{ fontSize: 13, color: t.textMuted, marginTop: 3 }}>Manage account and preferences</div></div>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <Card className="fade-up s1" style={{ padding: 18 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}><Icon d={I.shield} size={14} style={{ color: t.primary }} /><div className="serif" style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Change Password</div></div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
                        <div><Label>Current Password</Label><Input type="password" placeholder="Enter current password" /></div>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 11 }}><div><Label>New Password</Label><Input type="password" placeholder="New password" /></div><div><Label>Confirm</Label><Input type="password" placeholder="Confirm" /></div></div>
                        <Btn style={{ alignSelf: "flex-start" }}>Update Password</Btn>
                    </div>
                </Card>
                <Card className="fade-up s2" style={{ padding: 18 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}><Icon d={I.bell} size={14} style={{ color: t.primary }} /><div className="serif" style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Notifications</div></div>
                    {["Email for new appointments", "Case status change alerts", "Document review reminders", "Client message notifications", "Hearing date reminders"].map(item => (
                        <label key={item} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "9px 11px", borderRadius: 8, border: `1px solid ${t.border}`, marginBottom: 7, cursor: "pointer" }}>
                            <span style={{ fontSize: 13, color: t.text }}>{item}</span>
                            <input type="checkbox" defaultChecked style={{ accentColor: t.primary, width: 15, height: 15 }} />
                        </label>
                    ))}
                </Card>
                <Card className="fade-up s3" style={{ padding: 18, borderColor: `${t.border}` }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}><Icon d={I.logout} size={14} style={{ color: t.text }} /><div className="serif" style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Sign Out</div></div>
                    <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 14 }}>Sign out of your account on this device. You will need to log back in to access your cases.</div>
                    <Btn variant="outline" onClick={() => setPage("login")} style={{ borderColor: t.border, color: t.text }}>Sign Out</Btn>
                </Card>
                <Card className="fade-up s4" style={{ padding: 18, borderColor: `${t.danger}40` }}>
                    <div className="serif" style={{ fontSize: 14, fontWeight: 600, color: t.danger, marginBottom: 8 }}>Danger Zone</div>
                    <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 14 }}>Permanently delete your account. This cannot be undone.</div>
                    <Btn variant="danger">Delete Account</Btn>
                </Card>
            </div>
        </div>
    );
}

export { SettingsPage };
