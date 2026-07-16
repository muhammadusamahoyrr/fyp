'use client';
import { useState, useEffect } from "react";
import { useTheme } from "./theme.js";
import { Card, Btn, Label, Badge, Divider, Input } from "./components.jsx";
import { Icon, I } from "./icons.jsx";
import { useToast } from "@/components/shared/Toast.jsx";
import { getMe, updateMe, updateLawyerProfile } from "@/lib/api.js";

function ProfilePage() {
    const { t } = useTheme();
    const toast = useToast();
    const [saving, setSaving] = useState(false);
    const [form, setForm] = useState({
        first_name: "", last_name: "", email: "", phone: "",
        specialization: "", bar_number: "", experience: "", bio: "", province: "",
    });
    const [initials, setInitials] = useState("JD");

    useEffect(() => {
        getMe().then(({ data }) => {
            if (!data) return;
            const parts = (data.full_name || "").split(" ");
            setInitials((parts[0]?.[0] || "") + (parts[1]?.[0] || ""));
            const lp = data.lawyer_profile || {};
            setForm({
                first_name: parts[0] || "",
                last_name: parts.slice(1).join(" ") || "",
                email: data.email || "",
                phone: data.phone || "",
                specialization: (lp.specializations || []).join(", "),
                bar_number: lp.bar_number || "",
                experience: lp.experience_years ? String(lp.experience_years) : "",
                bio: lp.bio || "",
                province: lp.province || data.province || "",
            });
        });
    }, []);

    const f = (k) => (e) => setForm(p => ({ ...p, [k]: e.target.value }));

    const PROVINCE_MAP = { punjab: "punjab", sindh: "sindh", kpk: "kpk", balochistan: "balochistan", federal: "federal" };

    const handleSave = async () => {
        setSaving(true);
        const full_name = [form.first_name, form.last_name].filter(Boolean).join(" ");
        const provinceVal = form.province ? (PROVINCE_MAP[form.province.toLowerCase()] || null) : null;
        const specializations = form.specialization
            ? form.specialization.split(",").map(s => s.trim().toLowerCase()).filter(Boolean)
            : null;
        const [r1, r2] = await Promise.all([
            updateMe({ full_name, phone: form.phone || null, province: provinceVal }),
            updateLawyerProfile({
                bar_number: form.bar_number || null,
                experience_years: form.experience ? parseInt(form.experience) : null,
                bio: form.bio || null,
                specializations: specializations?.length ? specializations : null,
            }),
        ]);
        setSaving(false);
        if (r1.error || r2.error) {
            toast.show("❌ " + ((r1.error || r2.error)?.detail || "Save failed"), "danger");
        } else {
            toast.show("✅ Profile updated", "success");
        }
    };

    const infoRows = [
        { ic: I.mail, v: form.email || "—" },
        { ic: I.phone, v: form.phone || "—" },
        { ic: I.map, v: form.province || "—" },
        { ic: I.award, v: form.bar_number || "—" },
        { ic: I.clock, v: form.experience ? `${form.experience} years experience` : "—" },
    ];

    return (
        <div style={{ maxWidth: 880 }}>
            <div className="fade-up" style={{ marginBottom: 18 }}>
                <div className="serif" style={{ fontSize: 22, fontWeight: 700, color: t.text }}>Lawyer Profile</div>
                <div style={{ fontSize: 13, color: t.textMuted, marginTop: 3 }}>Manage your professional profile and credentials</div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "250px 1fr", gap: 18 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                    <Card className="fade-up" style={{ padding: 20, textAlign: "center" }}>
                        <div style={{ position: "relative", width: 76, height: 76, margin: "0 auto 12px" }}>
                            <div style={{ width: 76, height: 76, borderRadius: "50%", background: t.grad1, display: "flex", alignItems: "center", justifyContent: "center" }}>
                                <span className="serif" style={{ fontSize: 22, fontWeight: 700, color: t.mode === "dark" ? "#111B1F" : "#fff" }}>{initials || "?"}</span>
                            </div>
                            <button style={{ position: "absolute", bottom: 0, right: 0, width: 24, height: 24, borderRadius: "50%", background: t.primary, border: "none", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }}>
                                <Icon d={I.camera} size={11} style={{ color: t.mode === "dark" ? "#111B1F" : "#fff" }} />
                            </button>
                        </div>
                        <div className="serif" style={{ fontSize: 16, fontWeight: 700, color: t.text }}>{[form.first_name, form.last_name].filter(Boolean).join(" ") || "—"}</div>
                        <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 9 }}>{form.specialization?.split(",")[0]?.trim() || "Lawyer"}</div>
                        <div style={{ display: "flex", gap: 5, justifyContent: "center", flexWrap: "wrap" }}>
                            <Badge type="success">Verified</Badge>
                            {form.province && <Badge type="gray">{form.province}</Badge>}
                        </div>
                        <Divider />
                        {infoRows.map((r, i) => (
                            <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12, color: t.textMuted, marginBottom: 6, textAlign: "left" }}>
                                <Icon d={r.ic} size={12} style={{ flexShrink: 0, color: t.primary }} />
                                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.v}</span>
                            </div>
                        ))}
                    </Card>
                </div>

                <Card className="fade-up s1" style={{ padding: 22 }}>
                    <div className="serif" style={{ fontSize: 16, fontWeight: 600, color: t.text, marginBottom: 18 }}>Edit Profile</div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                            <div><Label>First Name</Label><Input value={form.first_name} onChange={f("first_name")} placeholder="First name" /></div>
                            <div><Label>Last Name</Label><Input value={form.last_name} onChange={f("last_name")} placeholder="Last name" /></div>
                        </div>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                            <div><Label>Email</Label><Input value={form.email} onChange={f("email")} type="email" placeholder="Email" /></div>
                            <div><Label>Phone</Label><Input value={form.phone} onChange={f("phone")} placeholder="+92 3XX XXXXXXX" /></div>
                        </div>
                        <div><Label>Specialization (comma-separated)</Label><Input value={form.specialization} onChange={f("specialization")} placeholder="e.g. Civil Law, Property Law" /></div>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                            <div><Label>Bar License / Registration No.</Label><Input value={form.bar_number} onChange={f("bar_number")} placeholder="e.g. PBA-2015-4582" /></div>
                            <div><Label>Experience (years)</Label><Input value={form.experience} onChange={f("experience")} type="number" placeholder="e.g. 8" /></div>
                        </div>
                        <div>
                            <Label>Province</Label>
                            <select value={form.province} onChange={f("province")} style={{ width: "100%", height: 40, border: `1px solid ${t.border}`, borderRadius: 9, background: t.inputBg, color: t.text, fontSize: 14, padding: "0 14px", outline: "none", cursor: "pointer", boxSizing: "border-box" }}>
                                <option value="">— Select Province —</option>
                                {["punjab", "sindh", "kpk", "balochistan", "federal"].map(p => <option key={p} value={p} style={{ background: t.surface }}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>)}
                            </select>
                        </div>
                        <div><Label>Bio</Label><Input type="textarea" value={form.bio} onChange={f("bio")} rows={3} placeholder="Brief professional biography…" /></div>
                        <div style={{ display: "flex", justifyContent: "flex-end" }}>
                            <Btn onClick={handleSave} disabled={saving}>
                                <Icon d={I.save} size={13} /> {saving ? "Saving…" : "Save Changes"}
                            </Btn>
                        </div>
                    </div>
                </Card>
            </div>
        </div>
    );
}

export { ProfilePage };
