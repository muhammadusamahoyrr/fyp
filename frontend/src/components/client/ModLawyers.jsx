'use client';
// Paste your ModLawyers.jsx code here
import React, { useState } from "react";
import { useT } from "./theme.js";
import { useCase } from "./CaseContext.jsx";
import Ic from "./Ic.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput, Badge } from "@/components/shared/shared.jsx";

/* ══════════════════════════════════════════════════════
   MODULE: LAWYER DISCOVERY
══════════════════════════════════════════════════════ */
const ModLawyers = () => {
    const t = useT();
    const { selectLawyer, confirmAppointment, addNotification, caseType } = useCase();
    const [query, setQuery] = useState("");
    const [filter, setFilter] = useState("All");
    const [activeView, setActiveView] = useState("list");
    const [selectedLawyer, setSelectedLawyer] = useState(null);
    const [showFilters, setShowFilters] = useState(false);
    // Fix #5: appointment modal state
    const [showApptModal, setShowApptModal] = useState(false);
    const [apptLawyer, setApptLawyer] = useState(null);
    const [apptDate, setApptDate] = useState("");
    const [apptTime, setApptTime] = useState("10:00");
    const [apptDetails, setApptDetails] = useState("");
    const [sortBy, setSortBy] = useState("Rating: High to Low");
    const [filters, setFilters] = useState({
        specialization: "All",
        city: "All",
        experience: [0, 20],
        price: [0, 15000],
        rating: 0,
        availability: "All",
    });
    const [reviewSort, setReviewSort] = useState("date");
    const [locationInput, setLocationInput] = useState("");
    const [searchMode, setSearchMode] = useState("name");

    const lawyers = [
        { name: "Ahmad Raza Khan", spec: "Employment Law", city: "Lahore", exp: 12, fee: 8000, rating: 4.9, avail: true, reviews: 84, bar: "BAR-001", lat: 31.5204, lng: 74.3587, distance: 2.4, hours: "Mon–Fri: 9am–6pm", address: "12 Mall Road, Lahore", credentials: ["LLB – Punjab University", "LLM – Harvard Law", "10+ Supreme Court Cases"], reviewList: [{ user: "Kamran A.", rating: 5, date: "2026-01-10", text: "Excellent counsel, won my wrongful termination case." }, { user: "Sana M.", rating: 5, date: "2026-01-05", text: "Very professional and thorough." }, { user: "Usman T.", rating: 4, date: "2025-12-28", text: "Good communication throughout the process." }] },
        { name: "Sara Minhas", spec: "Family Law", city: "Karachi", exp: 8, fee: 5500, rating: 4.7, avail: true, reviews: 61, bar: "BAR-002", lat: 24.8607, lng: 67.0011, distance: 5.1, hours: "Mon–Sat: 10am–5pm", address: "45 Clifton Block 4, Karachi", credentials: ["LLB – Karachi University", "Family Law Specialist Cert."], reviewList: [{ user: "Ayesha K.", rating: 5, date: "2026-01-15", text: "Handled my divorce case with sensitivity." }, { user: "Rehman B.", rating: 4, date: "2026-01-01", text: "Professional and responsive." }] },
        { name: "Bilal Chaudhry", spec: "Property", city: "Islamabad", exp: 15, fee: 10000, rating: 4.8, avail: false, reviews: 102, bar: "BAR-003", lat: 33.6844, lng: 73.0479, distance: 1.8, hours: "Mon–Fri: 8am–5pm", address: "F-7 Markaz, Islamabad", credentials: ["LLB – LUMS", "LLM – Oxford", "Property Law Expert"], reviewList: [{ user: "Imran C.", rating: 5, date: "2026-01-12", text: "Resolved complex property dispute efficiently." }, { user: "Hina F.", rating: 5, date: "2025-12-20", text: "Very knowledgeable about land laws." }] },
        { name: "Nadia Hussain", spec: "Criminal Defense", city: "Rawalpindi", exp: 10, fee: 7200, rating: 4.6, avail: true, reviews: 55, bar: "BAR-004", lat: 33.5651, lng: 73.0169, distance: 3.2, hours: "Mon–Sat: 9am–7pm", address: "Saddar, Rawalpindi", credentials: ["LLB – QAU", "Criminal Law Cert.", "High Court Advocate"], reviewList: [{ user: "Asad N.", rating: 5, date: "2026-01-08", text: "Got me acquitted! Brilliant defense strategy." }, { user: "Farrukh L.", rating: 4, date: "2025-12-15", text: "Very thorough in preparing the case." }] },
        { name: "Tariq Mehmood", spec: "Contract", city: "Lahore", exp: 6, fee: 4800, rating: 4.5, avail: true, reviews: 39, bar: "BAR-005", lat: 31.5497, lng: 74.3436, distance: 4.7, hours: "Mon–Fri: 10am–6pm", address: "Gulberg III, Lahore", credentials: ["LLB – UCP", "Contract & Commercial Law Cert."], reviewList: [{ user: "Zainab R.", rating: 4, date: "2026-01-03", text: "Helped draft airtight business contracts." }] },
        { name: "Zara Ali", spec: "Civil Rights", city: "Karachi", exp: 9, fee: 6300, rating: 4.8, avail: false, reviews: 77, bar: "BAR-006", lat: 24.8906, lng: 67.0022, distance: 6.3, hours: "Mon–Fri: 9am–5pm", address: "Defence Phase 2, Karachi", credentials: ["LLB – IBA", "Human Rights Law Fellow", "UN Advocacy Training"], reviewList: [{ user: "Mariam Q.", rating: 5, date: "2026-01-11", text: "Fought my civil rights case fearlessly." }, { user: "Shahid O.", rating: 5, date: "2025-12-30", text: "Exceptional dedication to justice." }] },
    ];

    // Accent color palette — one per lawyer slot, cycles if more lawyers added
    const accentPalette = [
        { solid: "#1D9E75", light: "#E1F5EE", text: "#085041" },  // teal
        { solid: "#378ADD", light: "#E6F1FB", text: "#0C447C" },  // blue
        { solid: "#EF9F27", light: "#FAEEDA", light2: "#FAEEDA", text: "#633806" },  // amber
        { solid: "#7F77DD", light: "#EEEDFE", text: "#3C3489" },  // purple
        { solid: "#D85A30", light: "#FAECE7", text: "#712B13" },  // coral
        { solid: "#D4537E", light: "#FBEAF0", text: "#72243E" },  // pink
    ];

    const specializations = ["All", ...new Set(lawyers.map(l => l.spec))];
    const cities = ["All", ...new Set(lawyers.map(l => l.city))];
    const sortOptions = ["Rating: High to Low", "Rating: Low to High", "Price: Low to High", "Price: High to Low", "Experience: High", "A–Z", "Z–A", "Distance: Nearest"];

    const getAccent = (l) => accentPalette[lawyers.findIndex(x => x.bar === l.bar) % accentPalette.length];

    const applySort = (arr) => {
        const s = [...arr];
        if (sortBy === "Rating: High to Low") return s.sort((a, b) => b.rating - a.rating);
        if (sortBy === "Rating: Low to High") return s.sort((a, b) => a.rating - b.rating);
        if (sortBy === "Price: Low to High") return s.sort((a, b) => a.fee - b.fee);
        if (sortBy === "Price: High to Low") return s.sort((a, b) => b.fee - a.fee);
        if (sortBy === "Experience: High") return s.sort((a, b) => b.exp - a.exp);
        if (sortBy === "A–Z") return s.sort((a, b) => a.name.localeCompare(b.name));
        if (sortBy === "Z–A") return s.sort((a, b) => b.name.localeCompare(a.name));
        if (sortBy === "Distance: Nearest") return s.sort((a, b) => a.distance - b.distance);
        return s;
    };

    const filtered = applySort(lawyers.filter(l => {
        const matchFilter = filter === "All" || (filter === "Available" && l.avail) || (filter === "Top Rated" && l.rating >= 4.8);
        const matchQuery = searchMode === "bar"
            ? l.bar.toLowerCase().includes(query.toLowerCase())
            : (l.name + l.spec + l.city).toLowerCase().includes(query.toLowerCase());
        const matchSpec = filters.specialization === "All" || l.spec === filters.specialization;
        const matchCity = filters.city === "All" || l.city === filters.city;
        const matchExp = l.exp >= filters.experience[0] && l.exp <= filters.experience[1];
        const matchFee = l.fee >= filters.price[0] && l.fee <= filters.price[1];
        const matchRating = l.rating >= filters.rating;
        const matchAvail = filters.availability === "All" || (filters.availability === "Available" && l.avail) || (filters.availability === "Busy" && !l.avail);
        return matchFilter && matchQuery && matchSpec && matchCity && matchExp && matchFee && matchRating && matchAvail;
    }));

    const sortedReviews = (list) => [...list].sort((a, b) =>
        reviewSort === "date" ? new Date(b.date) - new Date(a.date) : b.rating - a.rating
    );

    // ── STAR RENDERER ─────────────────────────────────────────────
    const StarRow = ({ rating, color, size = 12 }) => (
        <div style={{ display: "flex", alignItems: "center", gap: 3 }}>
            {[1, 2, 3, 4, 5].map(s => (
                <svg key={s} width={size} height={size} viewBox="0 0 24 24">
                    <polygon
                        points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"
                        fill={s <= Math.round(rating) ? color : "transparent"}
                        stroke={s <= Math.round(rating) ? color : t.border}
                        strokeWidth="1.5"
                    />
                </svg>
            ))}
        </div>
    );

    // ── BOOKING HELPERS ───────────────────────────────────────────
    // Fix #5: opens the modal and pre-selects the lawyer in CaseContext
    const openBooking = (lawyer) => {
        setApptLawyer(lawyer);
        selectLawyer(lawyer);                 // write to CaseContext immediately
        setApptDate("");
        setApptTime("10:00");
        setApptDetails("");
        setShowApptModal(true);
    };

    const submitBooking = () => {
        if (!apptDate) return;
        // Fix #5: writes appointment into CaseContext → creates milestone in Module 7
        confirmAppointment({ date: apptDate, time: apptTime, details: apptDetails || `Consultation with ${apptLawyer?.name}` });
        addNotification({
            type: "hearing",
            urgency: "upcoming",
            title: `Appointment — ${apptLawyer?.name}`,
            date: new Date(apptDate).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
            time: apptTime,
            desc: `Consultation confirmed · ${apptLawyer?.spec} · ₨${apptLawyer?.fee?.toLocaleString()}/hr`,
        });
        setShowApptModal(false);
    };

    // ── APPOINTMENT MODAL ─────────────────────────────────────────
    // Fix #5: renders over any view; no position:fixed (iframe constraint) — uses
    // an in-flow overlay wrapper with min-height so it contributes layout height.
    const AppointmentModal = () => apptLawyer ? (
        <div style={{
            position: "absolute", inset: 0, zIndex: 100,
            background: "rgba(0,0,0,0.55)",
            display: "flex", alignItems: "center", justifyContent: "center",
            borderRadius: 0,
        }}>
            <div style={{
                background: t.card, borderRadius: 20, border: `1.5px solid ${t.border}`,
                padding: 28, width: "100%", maxWidth: 460,
                boxShadow: "0 24px 64px rgba(0,0,0,0.4)", position: "relative",
            }}>
                {/* Header */}
                <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 22 }}>
                    <div style={{ width: 46, height: 46, borderRadius: 14, background: t.primaryGlow, border: `1.5px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20, fontWeight: 800, color: t.primary, flexShrink: 0 }}>
                        {apptLawyer.name.split(" ").map(w => w[0]).join("").slice(0, 2)}
                    </div>
                    <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 800, color: t.text, fontSize: 15 }}>{apptLawyer.name}</div>
                        <div style={{ fontSize: 12, color: t.textMuted }}>{apptLawyer.spec} · ₨{apptLawyer.fee?.toLocaleString()}/hr</div>
                    </div>
                    <button onClick={() => setShowApptModal(false)} style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 8, width: 30, height: 30, cursor: "pointer", color: t.textMuted, fontSize: 16, display: "flex", alignItems: "center", justifyContent: "center" }}>✕</button>
                </div>

                {/* Date */}
                <div style={{ marginBottom: 14 }}>
                    <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 6 }}>Date *</label>
                    <input type="date" value={apptDate} onChange={e => setApptDate(e.target.value)}
                        style={{ width: "100%", padding: "10px 14px", borderRadius: 10, border: `1.5px solid ${apptDate ? t.primary : t.border}`, background: t.inputBg, color: t.text, fontSize: 13, outline: "none", boxSizing: "border-box" }} />
                </div>

                {/* Time */}
                <div style={{ marginBottom: 14 }}>
                    <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 6 }}>Preferred Time</label>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                        {["09:00", "10:00", "11:00", "14:00", "15:00", "16:00"].map(slot => (
                            <button key={slot} onClick={() => setApptTime(slot)}
                                style={{ padding: "8px 14px", borderRadius: 8, border: `1.5px solid ${apptTime === slot ? t.primary : t.border}`, background: apptTime === slot ? t.primaryGlow : "transparent", color: apptTime === slot ? t.primary : t.textMuted, fontSize: 12, fontWeight: 700, cursor: "pointer", transition: "all 0.15s" }}>
                                {slot}
                            </button>
                        ))}
                    </div>
                </div>

                {/* Notes */}
                <div style={{ marginBottom: 22 }}>
                    <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 6 }}>Consultation Notes (optional)</label>
                    <textarea value={apptDetails} onChange={e => setApptDetails(e.target.value)}
                        placeholder={`Brief description of your case for ${apptLawyer.name}…`}
                        style={{ width: "100%", minHeight: 72, padding: "10px 14px", borderRadius: 10, border: `1.5px solid ${t.border}`, background: t.inputBg, color: t.text, fontSize: 13, outline: "none", resize: "vertical", boxSizing: "border-box" }} />
                </div>

                {/* Working hours info */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}`, marginBottom: 18 }}>
                    <Ic n="clock" s={13} c={t.textMuted} />
                    <span style={{ fontSize: 12, color: t.textMuted }}>{apptLawyer.hours}</span>
                </div>

                {/* Actions */}
                <div style={{ display: "flex", gap: 10 }}>
                    <BtnOutline onClick={() => setShowApptModal(false)} style={{ flex: 1, fontSize: 13 }}>Cancel</BtnOutline>
                    <BtnPrimary disabled={!apptDate} onClick={submitBooking} style={{ flex: 2, fontSize: 13, padding: "12px" }}>
                        Confirm Appointment →
                    </BtnPrimary>
                </div>
            </div>
        </div>
    ) : null;

    // ── PROFILE VIEW ──────────────────────────────────────────────
    if (activeView === "profile" && selectedLawyer) {
        const l = selectedLawyer;
        const ac = getAccent(l);
        return (
            <div style={{ position: "relative" }}>
                {showApptModal && <AppointmentModal />}
                <button onClick={() => setActiveView("list")} style={{ display: "flex", alignItems: "center", gap: 8, background: "none", border: "none", color: t.primary, cursor: "pointer", fontSize: 13, fontWeight: 600, marginBottom: 20, padding: 0 }}>
                    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke={t.primary} strokeWidth="2"><path d="M19 12H5M12 5l-7 7 7 7" /></svg>
                    Back to Lawyers
                </button>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                        <Card>
                            <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
                                <div style={{ width: 72, height: 72, borderRadius: 20, background: ac.light, border: `2px solid ${ac.solid}55`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, fontWeight: 800, color: ac.solid, flexShrink: 0 }}>
                                    {l.name.split(" ").map(w => w[0]).join("").slice(0, 2)}
                                </div>
                                <div style={{ flex: 1 }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                                        <span style={{ fontWeight: 800, color: t.text, fontSize: 17 }}>{l.name}</span>
                                        <Badge type={l.avail ? "success" : "gray"}>{l.avail ? "Available" : "Busy"}</Badge>
                                    </div>
                                    <div style={{ fontSize: 13, color: ac.solid, fontWeight: 600, marginTop: 2 }}>{l.spec}</div>
                                    <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>Bar No: {l.bar}</div>
                                    <div style={{ display: "flex", gap: 6, marginTop: 6, alignItems: "center" }}>
                                        <StarRow rating={l.rating} color={ac.solid} size={13} />
                                        <span style={{ fontSize: 12, color: t.textMuted, marginLeft: 4 }}>{l.rating} · {l.reviews} reviews</span>
                                    </div>
                                </div>
                            </div>
                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginTop: 16, background: t.inputBg, borderRadius: 12, padding: 14 }}>
                                {[["Experience", `${l.exp} yrs`], ["Fee/hr", `₨${l.fee.toLocaleString()}`], ["City", l.city]].map(([k, v]) => (
                                    <div key={k} style={{ textAlign: "center" }}>
                                        <div style={{ fontSize: 10, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.5px" }}>{k}</div>
                                        <div style={{ fontSize: 14, fontWeight: 700, color: t.text, marginTop: 3 }}>{v}</div>
                                    </div>
                                ))}
                            </div>
                            <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
                                <BtnOutline style={{ flex: 1, fontSize: 13 }}>Message</BtnOutline>
                                <BtnPrimary disabled={!l.avail} onClick={() => l.avail && openBooking(l)} style={{ flex: 1, fontSize: 13 }}>Book Appointment</BtnPrimary>
                            </div>
                        </Card>
                        <Card>
                            <div style={{ fontWeight: 700, color: t.text, fontSize: 14, marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
                                <Ic n="shield" s={15} c={t.primary} /> Credentials & Qualifications
                            </div>
                            {l.credentials.map((c, i) => (
                                <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderBottom: i < l.credentials.length - 1 ? `1px solid ${t.border}` : "none" }}>
                                    <div style={{ width: 6, height: 6, borderRadius: "50%", background: ac.solid, flexShrink: 0 }} />
                                    <span style={{ fontSize: 13, color: t.text }}>{c}</span>
                                </div>
                            ))}
                        </Card>
                        <Card>
                            <div style={{ fontWeight: 700, color: t.text, fontSize: 14, marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
                                <Ic n="clock" s={15} c={t.primary} /> Office Info
                            </div>
                            {[["Working Hours", l.hours], ["Office Address", l.address], ["Consultation Fee", `₨${l.fee.toLocaleString()} / hour`]].map(([k, v]) => (
                                <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 10 }}>
                                    <span style={{ fontSize: 12, color: t.textMuted, flexShrink: 0 }}>{k}</span>
                                    <span style={{ fontSize: 13, color: t.text, fontWeight: 600, textAlign: "right" }}>{v}</span>
                                </div>
                            ))}
                        </Card>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                        <Card style={{ padding: 0, overflow: "hidden" }}>
                            <div style={{ background: `linear-gradient(135deg, ${t.primaryGlow}, ${t.inputBg})`, height: 200, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10, position: "relative" }}>
                                <div style={{ position: "absolute", inset: 0, opacity: 0.08 }}>
                                    {[...Array(8)].map((_, i) => <div key={i} style={{ position: "absolute", left: 0, right: 0, top: `${i * 14}%`, height: 1, background: t.primary }} />)}
                                    {[...Array(10)].map((_, i) => <div key={i} style={{ position: "absolute", top: 0, bottom: 0, left: `${i * 11}%`, width: 1, background: t.primary }} />)}
                                </div>
                                <div style={{ width: 44, height: 44, borderRadius: "50%", background: `${t.primary}30`, border: `2px solid ${t.primary}`, display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1 }}>
                                    <Ic n="map" s={20} c={t.primary} />
                                </div>
                                <span style={{ fontSize: 13, color: t.text, fontWeight: 600, zIndex: 1 }}>{l.address}</span>
                                <span style={{ fontSize: 11, color: t.textMuted, zIndex: 1 }}>{l.distance} km away · {l.city}</span>
                            </div>
                            <div style={{ padding: "12px 16px", display: "flex", gap: 10 }}>
                                <BtnOutline style={{ flex: 1, fontSize: 12, padding: "9px" }}>
                                    <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                                        <Ic n="map" s={13} c={t.primary} /> View on Map
                                    </span>
                                </BtnOutline>
                                <BtnPrimary style={{ flex: 1, fontSize: 12, padding: "9px" }}>
                                    <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                                        <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2L4.5 20.29l.71.71L12 18l6.79 3 .71-.71z" /></svg>
                                        Get Directions
                                    </span>
                                </BtnPrimary>
                            </div>
                        </Card>
                        <Card>
                            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
                                <div style={{ fontWeight: 700, color: t.text, fontSize: 14, display: "flex", alignItems: "center", gap: 8 }}>
                                    <Ic n="star" s={15} c={t.warn} /> Reviews
                                    <span style={{ fontSize: 13, color: t.primary, fontWeight: 700 }}>{l.rating}</span>
                                    <span style={{ fontSize: 12, color: t.textMuted }}>({l.reviews})</span>
                                </div>
                                <select value={reviewSort} onChange={e => setReviewSort(e.target.value)} style={{ background: t.inputBg, border: `1px solid ${t.border}`, color: t.text, borderRadius: 8, padding: "5px 10px", fontSize: 12, outline: "none" }}>
                                    <option value="date">By Date</option>
                                    <option value="rating">By Rating</option>
                                </select>
                            </div>
                            {sortedReviews(l.reviewList).map((r, i) => (
                                <div key={i} style={{ background: t.inputBg, borderRadius: 12, padding: "12px 14px", marginBottom: 10 }}>
                                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                                        <span style={{ fontWeight: 700, fontSize: 13, color: t.text }}>{r.user}</span>
                                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                            <StarRow rating={r.rating} color={t.warn} size={10} />
                                            <span style={{ fontSize: 11, color: t.textMuted }}>{r.date}</span>
                                        </div>
                                    </div>
                                    <p style={{ fontSize: 12, color: t.textDim, margin: 0, lineHeight: 1.6 }}>{r.text}</p>
                                </div>
                            ))}
                        </Card>
                    </div>
                </div>
            </div>
        );
    }

    // ── MAP VIEW ──────────────────────────────────────────────────
    if (activeView === "map") {
        return (
            <div>
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
                    <button onClick={() => setActiveView("list")} style={{ display: "flex", alignItems: "center", gap: 8, background: "none", border: "none", color: t.primary, cursor: "pointer", fontSize: 13, fontWeight: 600, padding: 0 }}>
                        <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke={t.primary} strokeWidth="2"><path d="M19 12H5M12 5l-7 7 7 7" /></svg>
                        Back to List
                    </button>
                    <span style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Lawyers Near You</span>
                </div>
                <Card style={{ marginBottom: 16 }}>
                    <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                        <div style={{ flex: 1, position: "relative" }}>
                            <ThemedInput value={locationInput} onChange={e => setLocationInput(e.target.value)} placeholder="Enter your location (e.g. F-7 Islamabad)..." style={{ paddingLeft: 40 }} />
                            <div style={{ position: "absolute", left: 13, top: "50%", transform: "translateY(-50%)" }}><Ic n="map" s={15} c={t.textMuted} /></div>
                        </div>
                        <BtnPrimary style={{ fontSize: 13, padding: "11px 20px", flexShrink: 0 }}>Find Nearby</BtnPrimary>
                    </div>
                </Card>
                <Card style={{ padding: 0, overflow: "hidden", marginBottom: 16 }}>
                    <div style={{ height: 340, background: `linear-gradient(135deg, ${t.primaryGlow} 0%, ${t.inputBg} 50%, ${t.surface} 100%)`, position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
                        <div style={{ position: "absolute", inset: 0, opacity: 0.06 }}>
                            {[...Array(12)].map((_, i) => <div key={i} style={{ position: "absolute", left: 0, right: 0, top: `${i * 9}%`, height: 1, background: t.primary }} />)}
                            {[...Array(16)].map((_, i) => <div key={i} style={{ position: "absolute", top: 0, bottom: 0, left: `${i * 7}%`, width: 1, background: t.primary }} />)}
                        </div>
                        {filtered.slice(0, 4).map((l, i) => {
                            const positions = [{ top: "30%", left: "25%" }, { top: "50%", left: "55%" }, { top: "25%", left: "68%" }, { top: "65%", left: "35%" }];
                            const ac = getAccent(l);
                            return (
                                <div key={l.bar} onClick={() => { setSelectedLawyer(l); setActiveView("profile"); }} style={{ position: "absolute", ...positions[i], cursor: "pointer", display: "flex", flexDirection: "column", alignItems: "center", gap: 4, zIndex: 2 }}>
                                    <div style={{ background: t.card, border: `2px solid ${ac.solid}`, borderRadius: 10, padding: "6px 10px", fontSize: 11, fontWeight: 700, color: t.text, whiteSpace: "nowrap", boxShadow: "0 4px 14px rgba(0,0,0,0.3)" }}>
                                        {l.name.split(" ")[0]} · ₨{(l.fee / 1000).toFixed(1)}k
                                    </div>
                                    <div style={{ width: 10, height: 10, borderRadius: "50%", background: ac.solid, boxShadow: `0 0 8px ${ac.solid}` }} />
                                </div>
                            );
                        })}
                        <div style={{ zIndex: 1, textAlign: "center" }}>
                            <Ic n="map" s={32} c={`${t.primary}40`} />
                            <div style={{ fontSize: 12, color: t.textMuted, marginTop: 8 }}>Click pins to view profiles</div>
                        </div>
                    </div>
                </Card>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {[...filtered].sort((a, b) => a.distance - b.distance).map((l) => {
                        const ac = getAccent(l);
                        return (
                            <Card key={l.bar} style={{ display: "flex", alignItems: "center", gap: 14, cursor: "pointer", transition: "all 0.2s" }}
                                onMouseEnter={e => e.currentTarget.style.boxShadow = t.shadowHover}
                                onMouseLeave={e => e.currentTarget.style.boxShadow = t.shadowCard}
                                onClick={() => { setSelectedLawyer(l); setActiveView("profile"); }}>
                                <div style={{ width: 44, height: 44, borderRadius: 14, background: ac.light, border: `2px solid ${ac.solid}44`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 800, color: ac.solid, flexShrink: 0 }}>
                                    {l.name.split(" ").map(w => w[0]).join("").slice(0, 2)}
                                </div>
                                <div style={{ flex: 1 }}>
                                    <div style={{ fontWeight: 700, color: t.text, fontSize: 13 }}>{l.name}</div>
                                    <div style={{ fontSize: 12, color: t.textMuted }}>{l.spec} · {l.city}</div>
                                </div>
                                <div style={{ textAlign: "right" }}>
                                    <div style={{ fontSize: 13, fontWeight: 700, color: t.primary }}>{l.distance} km</div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>away</div>
                                </div>
                                <BtnOutline style={{ fontSize: 12, padding: "7px 14px", flexShrink: 0 }} onClick={e => { e.stopPropagation(); setSelectedLawyer(l); setActiveView("profile"); }}>Directions</BtnOutline>
                            </Card>
                        );
                    })}
                </div>
            </div>
        );
    }

    // ── LIST VIEW (default) ───────────────────────────────────────
    return (
        <div style={{ position: "relative" }}>
            {showApptModal && <AppointmentModal />}
            {/* Toolbar */}
            <div style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "center", flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 220, position: "relative" }}>
                    <ThemedInput
                        value={query}
                        onChange={e => setQuery(e.target.value)}
                        placeholder="Search by name, specialization, city..."
                        style={{ paddingLeft: 40 }}
                    />
                    <div style={{ position: "absolute", left: 13, top: "50%", transform: "translateY(-50%)" }}>
                        <Ic n="search" s={15} c={t.textMuted} />
                    </div>
                </div>

                <div style={{ display: "flex", borderRadius: 10, overflow: "hidden", border: `1px solid ${t.border}`, flexShrink: 0 }}>
                    {["All", "Available", "Top Rated"].map(f => (
                        <button key={f} onClick={() => {
                            setFilter(f);
                            if (f === "Available") setFilters(prev => ({ ...prev, availability: "Available" }));
                            else if (f === "All") setFilters(prev => ({ ...prev, availability: "All" }));
                        }} style={{
                            padding: "9px 14px", fontSize: 12, fontWeight: 600, border: "none",
                            cursor: "pointer", whiteSpace: "nowrap",
                            background: filter === f ? t.primary : t.inputBg,
                            color: filter === f ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.textMuted,
                            transition: "all 0.15s", fontFamily: "'Inter',sans-serif",
                        }}>{f}</button>
                    ))}
                </div>

                <button onClick={() => setShowFilters(f => !f)} style={{
                    display: "flex", alignItems: "center", gap: 6,
                    padding: "10px 16px", borderRadius: 10, flexShrink: 0,
                    border: `1.5px solid ${showFilters ? t.primary : t.border}`,
                    background: showFilters ? t.primaryGlow : "transparent",
                    color: showFilters ? t.primary : t.textMuted,
                    fontSize: 13, fontWeight: 600, cursor: "pointer",
                }}>
                    <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
                    </svg>
                    Filters
                </button>

                <select value={sortBy} onChange={e => setSortBy(e.target.value)} style={{
                    background: t.inputBg, border: `1.5px solid ${t.border}`, color: t.text,
                    borderRadius: 10, padding: "10px 14px", fontSize: 13, outline: "none", flexShrink: 0,
                }}>
                    {sortOptions.map(s => <option key={s}>{s}</option>)}
                </select>

                <button onClick={() => setActiveView("map")} style={{
                    display: "flex", alignItems: "center", gap: 6,
                    padding: "10px 16px", borderRadius: 10, flexShrink: 0,
                    border: `1.5px solid ${t.border}`, background: "transparent",
                    color: t.textMuted, fontSize: 13, fontWeight: 600, cursor: "pointer",
                }}>
                    <Ic n="map" s={14} c={t.textMuted} /> Map View
                </button>
            </div>

            {/* Filter Panel */}
            {showFilters && (
                <div style={{ marginBottom: 20, background: t.inputBg, border: `1.5px solid ${t.primary}25`, borderRadius: 20, padding: "20px 24px 18px", boxShadow: `0 8px 32px rgba(0,0,0,0.2), inset 0 1px 0 ${t.primary}15` }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 20, paddingBottom: 14, borderBottom: `1px solid ${t.border}` }}>
                        <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke={t.primary} strokeWidth="2.5"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" /></svg>
                        <span style={{ fontSize: 14, fontWeight: 800, color: t.text }}>Filters</span>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 20 }}>
                        <div>
                            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                                <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke={t.textMuted} strokeWidth="2"><rect x="2" y="7" width="20" height="14" rx="2" /><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2" /></svg>
                                <span style={{ fontSize: 10, color: t.textMuted, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px" }}>Specialization</span>
                            </div>
                            <div style={{ position: "relative" }}>
                                <select value={filters.specialization} onChange={e => setFilters(f => ({ ...f, specialization: e.target.value }))} style={{ width: "100%", background: t.surface, border: `1.5px solid ${filters.specialization !== "All" ? t.primary : t.border}`, color: filters.specialization !== "All" ? t.primary : t.text, borderRadius: 10, padding: "10px 36px 10px 14px", fontSize: 13, outline: "none", appearance: "none", cursor: "pointer", fontWeight: filters.specialization !== "All" ? 700 : 400, transition: "all 0.15s" }}>
                                    <option value="All">All Specializations</option>
                                    {specializations.filter(s => s !== "All").map(s => <option key={s}>{s}</option>)}
                                </select>
                                <svg style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none" }} width={13} height={13} viewBox="0 0 24 24" fill="none" stroke={t.textMuted} strokeWidth="2"><polyline points="6 9 12 15 18 9" /></svg>
                            </div>
                        </div>
                        <div>
                            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                                <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke={t.textMuted} strokeWidth="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" /><circle cx="12" cy="10" r="3" /></svg>
                                <span style={{ fontSize: 10, color: t.textMuted, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px" }}>City</span>
                            </div>
                            <div style={{ position: "relative" }}>
                                <select value={filters.city} onChange={e => setFilters(f => ({ ...f, city: e.target.value }))} style={{ width: "100%", background: t.surface, border: `1.5px solid ${filters.city !== "All" ? t.primary : t.border}`, color: filters.city !== "All" ? t.primary : t.text, borderRadius: 10, padding: "10px 36px 10px 14px", fontSize: 13, outline: "none", appearance: "none", cursor: "pointer", fontWeight: filters.city !== "All" ? 700 : 400, transition: "all 0.15s" }}>
                                    <option value="All">Search city...</option>
                                    {cities.filter(c => c !== "All").map(c => <option key={c}>{c}</option>)}
                                </select>
                                <svg style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none" }} width={13} height={13} viewBox="0 0 24 24" fill="none" stroke={t.textMuted} strokeWidth="2"><polyline points="6 9 12 15 18 9" /></svg>
                            </div>
                        </div>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 20 }}>
                        <div>
                            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
                                <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke={t.textMuted} strokeWidth="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /></svg>
                                <span style={{ fontSize: 10, color: t.textMuted, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px" }}>Experience</span>
                            </div>
                            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                {[{ label: "Any", min: 0 }, { label: "1–3 yrs", min: 1 }, { label: "3–5 yrs", min: 3 }, { label: "5–10 yrs", min: 5 }, { label: "10+ yrs", min: 10 }].map(({ label, min }) => {
                                    const isActive = filters.experience[0] === min;
                                    return (
                                        <button key={label} onClick={() => setFilters(f => ({ ...f, experience: [min, 20] }))} style={{ padding: "8px 14px", borderRadius: 8, fontSize: 12, fontWeight: isActive ? 700 : 500, border: `1.5px solid ${isActive ? t.primary : t.border}`, background: isActive ? t.primaryGlow : "transparent", color: isActive ? t.primary : t.textMuted, cursor: "pointer", transition: "all 0.15s" }}>{label}</button>
                                    );
                                })}
                            </div>
                        </div>
                        <div>
                            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
                                <svg width={12} height={12} viewBox="0 0 24 24" fill={t.warn} stroke={t.warn} strokeWidth="1"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" /></svg>
                                <span style={{ fontSize: 10, color: t.textMuted, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px" }}>Rating</span>
                            </div>
                            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                {[{ label: "Any", val: 0 }, { label: "3+", val: 3 }, { label: "4+", val: 4 }, { label: "4.5+", val: 4.5 }, { label: "5.0", val: 5 }].map(({ label, val }) => {
                                    const isActive = filters.rating === val;
                                    return (
                                        <button key={label} onClick={() => setFilters(f => ({ ...f, rating: val }))} style={{ padding: "8px 14px", borderRadius: 8, fontSize: 12, fontWeight: isActive ? 700 : 500, border: `1.5px solid ${isActive ? t.warn : t.border}`, background: isActive ? `${t.warn}18` : "transparent", color: isActive ? t.warn : t.textMuted, cursor: "pointer", transition: "all 0.15s", display: "flex", alignItems: "center", gap: 5 }}>
                                            {val > 0 && <svg width={10} height={10} viewBox="0 0 24 24" fill={isActive ? t.warn : "none"} stroke={isActive ? t.warn : t.textMuted} strokeWidth="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" /></svg>}
                                            {label}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    </div>

                    <div style={{ marginBottom: 20 }}>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke={t.textMuted} strokeWidth="2"><line x1="12" y1="1" x2="12" y2="23" /><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" /></svg>
                                <span style={{ fontSize: 10, color: t.textMuted, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px" }}>Fee Range / hr</span>
                            </div>
                            <div style={{ background: t.primaryGlow, border: `1px solid ${t.primary}40`, borderRadius: 20, padding: "3px 14px", fontSize: 12, color: t.primary, fontWeight: 700 }}>
                                {filters.price[0] === 0 && filters.price[1] >= 15000 ? "Any budget" : filters.price[1] >= 15000 ? `₨${filters.price[0].toLocaleString()}+` : `₨${filters.price[0].toLocaleString()} – ₨${filters.price[1].toLocaleString()}`}
                            </div>
                        </div>
                        <div style={{ position: "relative", height: 20, margin: "0 8px" }}>
                            <div style={{ position: "absolute", top: "50%", left: 0, right: 0, height: 4, background: t.border, borderRadius: 2, transform: "translateY(-50%)" }} />
                            <div style={{ position: "absolute", top: "50%", height: 4, borderRadius: 2, background: t.primary, transform: "translateY(-50%)", left: `${(filters.price[0] / 15000) * 100}%`, right: `${100 - (filters.price[1] / 15000) * 100}%` }} />
                            <input type="range" min={0} max={15000} step={500} value={filters.price[0]} onChange={e => { const v = parseInt(e.target.value); if (v < filters.price[1]) setFilters(f => ({ ...f, price: [v, f.price[1]] })); }} style={{ position: "absolute", width: "100%", height: "100%", opacity: 0, cursor: "pointer", zIndex: 2 }} />
                            <input type="range" min={0} max={15000} step={500} value={filters.price[1]} onChange={e => { const v = parseInt(e.target.value); if (v > filters.price[0]) setFilters(f => ({ ...f, price: [f.price[0], v] })); }} style={{ position: "absolute", width: "100%", height: "100%", opacity: 0, cursor: "pointer", zIndex: 2 }} />
                            <div style={{ position: "absolute", top: "50%", left: `${(filters.price[0] / 15000) * 100}%`, width: 16, height: 16, borderRadius: "50%", background: t.primary, border: `2px solid ${t.card}`, transform: "translate(-50%, -50%)", boxShadow: `0 0 8px ${t.primary}60`, pointerEvents: "none", zIndex: 3 }} />
                            <div style={{ position: "absolute", top: "50%", left: `${(filters.price[1] / 15000) * 100}%`, width: 16, height: 16, borderRadius: "50%", background: t.primary, border: `2px solid ${t.card}`, transform: "translate(-50%, -50%)", boxShadow: `0 0 8px ${t.primary}60`, pointerEvents: "none", zIndex: 3 }} />
                        </div>
                        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
                            {["₨1k", "₨2k", "₨4k", "₨6k", "₨8k", "₨10k", "₨15k+"].map(v => <span key={v} style={{ fontSize: 9, color: t.textMuted }}>{v}</span>)}
                        </div>
                    </div>

                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingTop: 14, borderTop: `1px solid ${t.border}` }}>
                        <div style={{ fontSize: 12, color: t.textMuted }}>
                            <span style={{ color: t.primary, fontWeight: 700 }}>{filtered.length}</span> lawyers match
                        </div>
                        <div style={{ display: "flex", gap: 10 }}>
                            <button onClick={() => setFilters({ specialization: "All", city: "All", experience: [0, 20], price: [0, 15000], rating: 0, availability: "All" })} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: t.textMuted, background: "none", border: `1.5px solid ${t.border}`, cursor: "pointer", padding: "9px 18px", borderRadius: 10, transition: "all 0.15s" }}
                                onMouseEnter={e => { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.color = t.primary; }}
                                onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textMuted; }}>
                                <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="1 4 1 10 7 10" /><path d="M3.51 15a9 9 0 1 0 .49-4.5" /></svg>
                                Reset
                            </button>
                            <button onClick={() => setShowFilters(false)} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 700, color: t.mode === "dark" ? "#1A2E35" : "#fff", background: t.primary, border: "none", cursor: "pointer", padding: "9px 22px", borderRadius: 10 }}
                                onMouseEnter={e => e.currentTarget.style.opacity = "0.9"}
                                onMouseLeave={e => e.currentTarget.style.opacity = "1"}>
                                Show {filtered.length} Lawyers
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* AI Match Banner */}
            <div style={{ background: `linear-gradient(135deg,${t.primaryGlow},transparent)`, border: `1.5px dashed ${t.primary}40`, borderRadius: 16, padding: 16, marginBottom: 20, display: "flex", alignItems: "center", gap: 14 }}>
                <div style={{ width: 42, height: 42, borderRadius: 13, background: `${t.primary}20`, display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <Ic n="zap" s={20} c={t.primary} />
                </div>
                <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 700, color: t.text, fontSize: 13 }}>AI-Recommended Match</div>
                    <div style={{ fontSize: 12, color: t.textMuted }}>Ahmad Raza Khan — employment specialist — 97% case-type compatibility</div>
                </div>
                <BtnPrimary onClick={() => { setSelectedLawyer(lawyers[0]); setActiveView("profile"); }} style={{ fontSize: 12, padding: "10px 18px", flexShrink: 0 }}>View Match</BtnPrimary>
            </div>

            {/* Results count */}
            <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 12 }}>
                Showing <span style={{ color: t.primary, fontWeight: 700 }}>{filtered.length}</span> lawyers
            </div>

            {/* ── LAWYER CARDS (redesigned) ─────────────────────────── */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(290px,1fr))", gap: 16 }}>
                {filtered.map((l) => {
                    const ac = getAccent(l);
                    return (
                        <div
                            key={l.bar}
                            onClick={() => { setSelectedLawyer(l); setActiveView("profile"); }}
                            style={{
                                background: t.card,
                                border: `1px solid ${t.border}`,
                                borderRadius: 18,
                                overflow: "hidden",
                                cursor: "pointer",
                                transition: "transform 0.18s, box-shadow 0.18s",
                                position: "relative",
                            }}
                            onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-3px)"; e.currentTarget.style.boxShadow = t.shadowHover; }}
                            onMouseLeave={e => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = "none"; }}
                        >
                            {/* Accent top bar */}
                            <div style={{ height: 4, background: ac.solid, width: "100%" }} />

                            <div style={{ padding: "16px 18px 18px" }}>

                                {/* Header row: avatar + name + distance badge */}
                                <div style={{ display: "flex", gap: 14, alignItems: "flex-start", marginBottom: 12 }}>
                                    <div style={{
                                        width: 52, height: 52, borderRadius: 15,
                                        background: ac.light,
                                        border: `1.5px solid ${ac.solid}44`,
                                        display: "flex", alignItems: "center", justifyContent: "center",
                                        fontSize: 17, fontWeight: 800, color: ac.solid, flexShrink: 0,
                                    }}>
                                        {l.name.split(" ").map(w => w[0]).join("").slice(0, 2)}
                                    </div>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ fontWeight: 800, color: t.text, fontSize: 14, lineHeight: 1.2 }}>{l.name}</div>
                                        <div style={{ fontSize: 12, color: ac.solid, fontWeight: 600, marginTop: 2 }}>{l.spec}</div>
                                        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 1 }}>{l.bar}</div>
                                    </div>
                                    {/* Distance pill */}
                                    <div style={{
                                        display: "flex", alignItems: "center", gap: 4,
                                        background: t.inputBg, borderRadius: 20,
                                        padding: "4px 9px", fontSize: 11, color: t.textMuted, flexShrink: 0,
                                    }}>
                                        <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" /><circle cx="12" cy="10" r="3" />
                                        </svg>
                                        {l.distance}km
                                    </div>
                                </div>

                                {/* Stars + availability */}
                                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                        <StarRow rating={l.rating} color={ac.solid} size={12} />
                                        <span style={{ fontSize: 12, color: t.textMuted }}>{l.rating} <span style={{ fontSize: 11 }}>({l.reviews})</span></span>
                                    </div>
                                    {/* Availability chip */}
                                    <div style={{
                                        display: "flex", alignItems: "center", gap: 5,
                                        padding: "3px 10px", borderRadius: 20, fontSize: 11, fontWeight: 600,
                                        background: l.avail ? `${ac.solid}18` : t.inputBg,
                                        color: l.avail ? ac.solid : t.textMuted,
                                    }}>
                                        <div style={{ width: 6, height: 6, borderRadius: "50%", background: l.avail ? ac.solid : t.textMuted }} />
                                        {l.avail ? "Available" : "Busy"}
                                    </div>
                                </div>

                                {/* Stats row */}
                                <div style={{
                                    display: "grid", gridTemplateColumns: "1fr 1px 1fr 1px 1fr",
                                    background: t.inputBg, borderRadius: 12, padding: "10px 0",
                                    marginBottom: 14,
                                }}>
                                    {[["Experience", `${l.exp}yr`], null, ["Fee/hr", `₨${(l.fee / 1000).toFixed(1)}k`], null, ["City", l.city]].map((item, i) => {
                                        if (item === null) return <div key={i} style={{ background: t.border, width: 1, margin: "4px 0" }} />;
                                        const [label, val] = item;
                                        return (
                                            <div key={label} style={{ textAlign: "center", padding: "0 8px" }}>
                                                <div style={{ fontSize: 10, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 3 }}>{label}</div>
                                                <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>{val}</div>
                                            </div>
                                        );
                                    })}
                                </div>

                                {/* Action buttons */}
                                <div style={{ display: "flex", gap: 8 }} onClick={e => e.stopPropagation()}>
                                    <BtnOutline
                                        onClick={() => { setSelectedLawyer(l); setActiveView("profile"); }}
                                        style={{ flex: 1, fontSize: 12, padding: "10px" }}
                                    >
                                        View Profile
                                    </BtnOutline>
                                    <button
                                        disabled={!l.avail}
                                        onClick={() => { if (l.avail) { openBooking(l); } }}
                                        style={{
                                            flex: 1, fontSize: 12, padding: "10px",
                                            borderRadius: 10, border: "none",
                                            background: l.avail ? ac.solid : t.inputBg,
                                            color: l.avail ? "#fff" : t.textMuted,
                                            fontWeight: 700, cursor: l.avail ? "pointer" : "not-allowed",
                                            opacity: l.avail ? 1 : 0.5,
                                            transition: "opacity 0.15s",
                                            fontFamily: "'Inter',sans-serif",
                                        }}
                                        onMouseEnter={e => { if (l.avail) e.currentTarget.style.opacity = "0.88"; }}
                                        onMouseLeave={e => { if (l.avail) e.currentTarget.style.opacity = "1"; }}
                                    >
                                        Book Now
                                    </button>
                                </div>
                            </div>
                        </div>
                    );
                })}

                {filtered.length === 0 && (
                    <div style={{ gridColumn: "1/-1", textAlign: "center", padding: "48px 0", color: t.textMuted }}>
                        <Ic n="search" s={32} c={t.border} />
                        <div style={{ marginTop: 12, fontSize: 14 }}>No lawyers match your search criteria.</div>
                        <button onClick={() => { setQuery(""); setFilter("All"); setFilters({ specialization: "All", city: "All", experience: [0, 20], price: [0, 15000], rating: 0, availability: "All" }); }} style={{ marginTop: 10, background: "none", border: "none", color: t.primary, cursor: "pointer", fontSize: 13, fontWeight: 600 }}>Clear all filters</button>
                    </div>
                )}
            </div>
        </div>
    );
};

export default ModLawyers;