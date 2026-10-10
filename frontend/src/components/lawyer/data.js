// Shared display constants for the lawyer dashboard.
// All case/appointment/document data comes from the backend API (lib/api.js).

// Badge type per caseStatusLabel (lib/caseStatus.js).
const CSB = { Draft: "gray", Open: "info", "Awaiting Lawyer": "warn", "In Progress": "success", Closed: "gray", Dismissed: "danger", Unknown: "gray" };
const DSB = { Draft: "gray", "Under Review": "warn", Approved: "success", Final: "primary" };
const APSB = { Upcoming: "info", Completed: "success", Cancelled: "danger", Pending: "warn" };
const PRIO = { high: "danger", medium: "warn", low: "success" };

const typeColor = { hearing: "#5AB3FF", document: "#40F0DC", task: "#4DD4A3", filed: "#4DD4A3", milestone: "#FFC857", note: "#9A9A94" };
const typeIcon = { hearing: "⚖️", document: "📄", task: "✅", filed: "📁", milestone: "🏁", note: "📝" };

// Pakistan time, explicitly. Without a zone the BROWSER's was used, and a
// hearing stored as midnight UTC of its day showed as the day before anywhere
// west of UTC.
const fmtDate = (d) => {
    if (!d) return "—";
    const dt = new Date(d);
    if (Number.isNaN(dt.getTime())) return "—";
    return dt.toLocaleDateString("en-PK", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Karachi" });
};
// "HH:MM" (24-hour) as a 12-hour time. Midnight to 00:59 is 12:xx AM; it was
// shown as "0:30 AM".
const fmtTime = (t) => {
    if (!t) return "";
    const [h, m] = String(t).split(":");
    const hr = parseInt(h, 10);
    if (!Number.isInteger(hr) || hr < 0 || hr > 23 || !/^\d{2}$/.test(m || "")) return String(t);
    return `${hr % 12 === 0 ? 12 : hr % 12}:${m} ${hr < 12 ? "AM" : "PM"}`;
};

export {
    fmtDate, fmtTime, CSB, typeColor, typeIcon, DSB, APSB, PRIO,
};
