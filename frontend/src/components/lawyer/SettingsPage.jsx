'use client';
import { useEffect, useState } from "react";
import { useTheme } from "./theme.js";
import { Card, Btn, Label, Input, Divider } from "./components.jsx";
import { Icon, I } from "./icons.jsx";
import { useToast } from "@/components/shared/Toast.jsx";
import { changePassword, authLogout, mySubscription, billingPlans, subscribePlan, cancelSubscription, mockPay } from "@/lib/api.js";

function SettingsPage() {
    const { t } = useTheme();
    const toast = useToast();
    const [pwd, setPwd] = useState({ current: "", newPwd: "", confirm: "" });
    const [saving, setSaving] = useState(false);
    const [sub, setSub] = useState(null);
    const [plans, setPlans] = useState([]);
    const [subBusy, setSubBusy] = useState(false);
    const [annual, setAnnual] = useState(false);

    useEffect(() => {
        mySubscription().then(({ data }) => { if (data) setSub(data); });
        billingPlans().then(({ data }) => { if (Array.isArray(data)) setPlans(data); });
    }, []);

    const refreshSub = async () => {
        const { data } = await mySubscription();
        if (data) setSub(data);
    };

    const doSubscribe = async (tier) => {
        setSubBusy(true);
        const { data, error } = await subscribePlan(tier, annual ? "annual" : "monthly");
        if (error) { setSubBusy(false); toast.show("❌ " + (error.message || "Subscription failed"), "error", 3000); return; }
        if (data?.dry_run) {
            await mockPay(data.payment_id);       // dev/test: settle immediately
        } else if (data?.checkout_url) {
            window.open(data.checkout_url, "_blank", "noopener");
        }
        await refreshSub();
        setSubBusy(false);
        toast.show("✅ Plan activated", "success", 2500);
    };

    const doCancel = async () => {
        setSubBusy(true);
        const { error } = await cancelSubscription();
        setSubBusy(false);
        if (error) { toast.show("❌ " + (error.message || "Cancel failed"), "error", 3000); return; }
        await refreshSub();
        toast.show("Subscription cancelled — access continues until period end", "info", 3000);
    };

    const handleChangePassword = async () => {
        if (!pwd.current || !pwd.newPwd) { toast.show("⚠️ Please fill all password fields", "warn"); return; }
        if (pwd.newPwd !== pwd.confirm) { toast.show("⚠️ New passwords do not match", "warn"); return; }
        if (pwd.newPwd.length < 8) { toast.show("⚠️ New password must be at least 8 characters", "warn"); return; }
        setSaving(true);
        const { error } = await changePassword(pwd.current, pwd.newPwd);
        setSaving(false);
        if (error) {
            toast.show("❌ " + (error.message || "Password change failed"), "danger");
        } else {
            toast.show("✅ Password updated successfully", "success");
            setPwd({ current: "", newPwd: "", confirm: "" });
        }
    };

    const handleSignOut = async () => {
        await authLogout();
        try { localStorage.removeItem("aai-role"); } catch { }
        // Hard redirect: clears all in-memory app state along with the session
        window.location.assign("/login");
    };

    return (
        <div style={{ maxWidth: 620 }}>
            <div className="fade-up" style={{ marginBottom: 18 }}>
                <div className="serif" style={{ fontSize: 22, fontWeight: 700, color: t.text }}>Settings</div>
                <div style={{ fontSize: 13, color: t.textMuted, marginTop: 3 }}>Manage account and preferences</div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <Card className="fade-up s1" style={{ padding: 18 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
                        <Icon d={I.shield} size={14} style={{ color: t.primary }} />
                        <div className="serif" style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Change Password</div>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
                        <div>
                            <Label>Current Password</Label>
                            <Input type="password" placeholder="Enter current password" value={pwd.current} onChange={e => setPwd(p => ({ ...p, current: e.target.value }))} />
                        </div>
                        <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 11 }}>
                            <div>
                                <Label>New Password</Label>
                                <Input type="password" placeholder="New password (min 8 chars)" value={pwd.newPwd} onChange={e => setPwd(p => ({ ...p, newPwd: e.target.value }))} />
                            </div>
                            <div>
                                <Label>Confirm</Label>
                                <Input type="password" placeholder="Confirm new password" value={pwd.confirm} onChange={e => setPwd(p => ({ ...p, confirm: e.target.value }))} />
                            </div>
                        </div>
                        <Btn style={{ alignSelf: "flex-start" }} onClick={handleChangePassword} disabled={saving}>
                            {saving ? "Updating…" : "Update Password"}
                        </Btn>
                    </div>
                </Card>

                <Card className="fade-up s2" style={{ padding: 18 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
                        <Icon d={I.bell} size={14} style={{ color: t.primary }} />
                        <div className="serif" style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Notifications</div>
                    </div>
                    {["Email for new appointments", "Case status change alerts", "Document review reminders", "Client message notifications", "Hearing date reminders"].map(item => (
                        <label key={item} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "9px 11px", borderRadius: 8, border: `1px solid ${t.border}`, marginBottom: 7, cursor: "pointer" }}>
                            <span style={{ fontSize: 13, color: t.text }}>{item}</span>
                            <input type="checkbox" defaultChecked style={{ accentColor: t.primary, width: 15, height: 15 }} />
                        </label>
                    ))}
                </Card>

                <Card className="fade-up s3" style={{ padding: 18 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                        <span style={{ fontSize: 14 }}>⭐</span>
                        <div className="serif" style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Subscription</div>
                        {sub && (
                            <span style={{
                                fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 10, textTransform: "uppercase",
                                background: sub.tier === "free" ? t.border : t.primary + "22",
                                color: sub.tier === "free" ? t.textMuted : t.primary,
                                border: `1px solid ${sub.tier === "free" ? t.border : t.primary + "55"}`
                            }}>
                                {sub.tier}{sub.status === "cancelled" ? " · ending" : ""}
                            </span>
                        )}
                    </div>

                    {sub && sub.tier !== "free" && sub.status === "active" ? (
                        <>
                            <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 14 }}>
                                You're on the <b style={{ color: t.text }}>{sub.tier}</b> plan.
                                {sub.current_period_end && ` Renews ${new Date(sub.current_period_end).toLocaleDateString()}.`}
                                {" "}Unlimited cause-list watches, AI research and case-law are unlocked.
                            </div>
                            <Btn variant="outline" onClick={doCancel} disabled={subBusy} style={{ borderColor: t.border, color: t.text }}>Cancel plan</Btn>
                        </>
                    ) : (
                        <>
                            <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 12 }}>
                                Upgrade to unlock <b style={{ color: t.text }}>unlimited cause-list watches</b>, unlimited AI research + case-law, and document generation.
                            </div>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, fontSize: 12, color: t.textMuted }}>
                                <button onClick={() => setAnnual(false)} style={{ padding: "4px 12px", borderRadius: 20, border: "none", cursor: "pointer", fontFamily: "inherit", fontWeight: 700, background: !annual ? t.primary : t.cardHi, color: !annual ? (t.mode === "dark" ? "#111B1F" : "#fff") : t.textMuted }}>Monthly</button>
                                <button onClick={() => setAnnual(true)} style={{ padding: "4px 12px", borderRadius: 20, border: "none", cursor: "pointer", fontFamily: "inherit", fontWeight: 700, background: annual ? t.primary : t.cardHi, color: annual ? (t.mode === "dark" ? "#111B1F" : "#fff") : t.textMuted }}>Annual <span style={{ opacity: 0.8 }}>−25%</span></button>
                            </div>
                            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                                {plans.filter(p => p.tier !== "free").map(p => (
                                    <div key={p.tier} style={{ flex: 1, minWidth: 150, border: `1px solid ${t.border}`, borderRadius: 12, padding: 14 }}>
                                        <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>{p.name}</div>
                                        <div style={{ fontSize: 20, fontWeight: 800, color: t.text, margin: "4px 0" }}>
                                            ₨{Number(annual ? p.price.annual : p.price.monthly).toLocaleString()}<span style={{ fontSize: 11, color: t.textMuted, fontWeight: 500 }}>/mo</span>
                                        </div>
                                        <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 10, minHeight: 28 }}>{p.blurb}</div>
                                        <Btn onClick={() => doSubscribe(p.tier)} disabled={subBusy} style={{ width: "100%" }}>
                                            {subBusy ? "…" : `Choose ${p.name}`}
                                        </Btn>
                                    </div>
                                ))}
                            </div>
                        </>
                    )}
                </Card>

                <Card className="fade-up s3" style={{ padding: 18 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
                        <Icon d={I.logout} size={14} style={{ color: t.text }} />
                        <div className="serif" style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Sign Out</div>
                    </div>
                    <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 14 }}>Sign out of your account on this device. You will need to log back in to access your cases.</div>
                    <Btn variant="outline" onClick={handleSignOut} style={{ borderColor: t.border, color: t.text }}>Sign Out</Btn>
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
