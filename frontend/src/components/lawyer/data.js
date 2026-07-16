// Shared display constants for the lawyer dashboard.
// All case/appointment/document data comes from the backend API (lib/api.js).

const CSB = { "Under Hearing": "info", Filed: "success", Adjourned: "warn", Closed: "gray" };
const DSB = { Draft: "gray", "Under Review": "warn", Approved: "success", Final: "primary" };
const APSB = { Upcoming: "info", Completed: "success", Cancelled: "danger", Pending: "warn" };
const PRIO = { high: "danger", medium: "warn", low: "success" };

const typeColor = { hearing: "#5AB3FF", document: "#40F0DC", task: "#4DD4A3", filed: "#4DD4A3", milestone: "#FFC857", note: "#9A9A94" };
const typeIcon = { hearing: "⚖️", document: "📄", task: "✅", filed: "📁", milestone: "🏁", note: "📝" };

const fmtDate = (d) => { if (!d) return "—"; const dt = new Date(d); return dt.toLocaleDateString("en-PK", { day: "numeric", month: "short", year: "numeric" }); };
const fmtTime = (t) => { if (!t) return ""; const [h, m] = t.split(":"); const hr = parseInt(h); return `${hr > 12 ? hr - 12 : hr}:${m} ${hr >= 12 ? "PM" : "AM"}`; };

export {
    fmtDate, fmtTime, CSB, typeColor, typeIcon, DSB, APSB, PRIO,
};
