'use client';
import React, { useState, useEffect, useMemo, useRef } from "react";
import dynamic from "next/dynamic";
import { createPortal } from "react-dom";
import { useSearchParams, useRouter as useNextRouter } from "next/navigation";
import { useT } from "./theme.js";
import { useCase } from "./CaseContext.jsx";
import { useToast } from "@/components/shared/Toast.jsx";
import Ic from "./Ic.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput, Badge } from "@/components/shared/shared.jsx";
import { searchLawyers, matchLawyers, submitReview, getLawyerReviews, bookAppointment, getLawyerAvailability, listCases, listEngagements, requestEngagement, cancelEngagement, acceptEngagementTerms, declineEngagementTerms, completeEngagement, terminateEngagement } from "@/lib/api.js";
import { useAuth } from "@/context/AuthContext.jsx";
import { hireableCases as hireable, isDraftCase } from "@/lib/caseStatus.js";
import { readIntakeValue } from "@/lib/intakeStorage.js";
import { pktToday, pktSlotToDate, pktSlotToUtcISO, isPktSlotPast, formatPkt } from "@/lib/bookingTime.js";
import { createBookingKeyHolder } from "@/lib/bookingIdempotency.js";

const LeafletMap = dynamic(() => import("./LeafletMap"), {
    ssr: false,
    loading: () => (
        <div style={{ height: 340, display: "flex", alignItems: "center", justifyContent: "center", color: "#6b7280", fontSize: 13 }}>
            Loading map…
        </div>
    ),
});

// Province and case-type mappings for server-side filter requests
const CITY_TO_PROVINCE = {
    lahore: "punjab", rawalpindi: "punjab", multan: "punjab", faisalabad: "punjab",
    karachi: "sindh", hyderabad: "sindh",
    islamabad: "federal",
    peshawar: "kpk",
    quetta: "balochistan",
    punjab: "punjab", sindh: "sindh", kpk: "kpk", balochistan: "balochistan", federal: "federal",
};
// Directory page size.
const PAGE_SIZE = 20;

const SPEC_TO_CASE_TYPE = {
    "employment law": "civil", "civil rights": "civil", "contract": "civil", "property": "civil",
    "criminal defense": "criminal", "criminal": "criminal",
    "family law": "family", "family": "family",
    "constitutional": "constitutional",
    "civil": "civil",
};

/* ══════════════════════════════════════════════════════
   MODULE: LAWYER DISCOVERY
══════════════════════════════════════════════════════ */
const ModLawyers = () => {
    const t = useT();
    const searchParams = useSearchParams();
    const router = useNextRouter();
    const { selectLawyer, confirmAppointment, addNotification, caseType } = useCase();
    const toast = useToast();
    const { user } = useAuth();
    const lawyerUserId = user?._id || user?.id || null;
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
    const [apptMode, setApptMode] = useState("video");
    const [apptSubmitting, setApptSubmitting] = useState(false);
    const [bookedSlots, setBookedSlots] = useState([]);
    const [sortBy, setSortBy] = useState("Rating: High to Low");
    const [filters, setFilters] = useState({
        specialization: "All",
        city: "All",
        rating: 0,
        availability: "All",
    });
    const [reviewSort, setReviewSort] = useState("date");

    const [searchMode, setSearchMode] = useState("name");
    const [apiLawyers, setApiLawyers] = useState([]);
    const [loadingLawyers, setLoadingLawyers] = useState(true);
    const [aiMatch, setAiMatch] = useState(null);
    const [loadingMatch, setLoadingMatch] = useState(false);
    // A general listing is NOT a match. The API says which it returned via
    // result_kind; these two carry that answer so the banner can render a
    // browse list differently instead of dressing it up as a recommendation.
    const [matchKind, setMatchKind] = useState(null);
    const [matchNotice, setMatchNotice] = useState(null);
    const [showReviewForm, setShowReviewForm] = useState(false);
    const [reviewStars, setReviewStars] = useState(5);
    const [reviewComment, setReviewComment] = useState("");
    const [reviewSubmitting, setReviewSubmitting] = useState(false);
    // Engagement (hire a lawyer) state
    const [showHireModal, setShowHireModal] = useState(false);
    const [hireLawyer, setHireLawyer] = useState(null);
    const [hireCaseId, setHireCaseId] = useState("");
    const [hireMessage, setHireMessage] = useState("");
    const [hireSubmitting, setHireSubmitting] = useState(false);
    const [myCases, setMyCases] = useState([]);
    const [myEngagements, setMyEngagements] = useState([]);

    const refreshEngagements = () => {
        listEngagements().then(({ data }) => {
            if (Array.isArray(data)) setMyEngagements(data);
        }).catch(() => { });
    };

    useEffect(() => {
        listCases({ page_size: 50 }).then(({ data }) => {
            if (data?.items) setMyCases(data.items);
        }).catch(() => { });
        refreshEngagements();
    }, []);

    // Cases you can still hire a lawyer for: CONFIRMED, no lawyer yet, not
    // closed, and no request already pending on them.
    //
    // `draft` is excluded because the server refuses it — a draft is a case the
    // client has not confirmed at the end of intake, and sending one to a
    // lawyer is rejected. Offering it here would put a case in the picker whose
    // only possible outcome is an error the client cannot act on from this
    // screen; the action they actually need is on the intake page.
    const pendingByCase = useMemo(() => {
        const m = {};
        myEngagements.filter(e => e.status === "requested").forEach(e => { m[e.case_id] = e; });
        return m;
    }, [myEngagements]);
    const hireableCases = useMemo(
        () => hireable(myCases, pendingByCase),
        [myCases, pendingByCase]);

    // Engagement state for one lawyer: "requested" | "accepted" | null
    const engagementWith = (lawyerId) => {
        if (!lawyerId) return null;
        if (myEngagements.some(e => e.lawyer_id === lawyerId && e.status === "requested")) return "requested";
        if (myEngagements.some(e => e.lawyer_id === lawyerId && e.status === "accepted")) return "accepted";
        return null;
    };

    // Prevent background scrolling when a modal is open
    useEffect(() => {
        if (showApptModal || showHireModal) {
            document.body.style.overflow = "hidden";
        } else {
            document.body.style.overflow = "";
        }
        return () => {
            document.body.style.overflow = "";
        };
    }, [showApptModal, showHireModal]);

    // Map a backend user document to the shape the UI expects
    const mapApiLawyer = (raw, idx) => {
        const lp = raw.lawyer_profile || {};
        const specs = (lp.specializations || []).map(s =>
            s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ")
        );
        const province = raw.province || "";
        const provinceLabel = province.charAt(0).toUpperCase() + province.slice(1);
        return {
            _id: raw._id || `api-${idx}`,
            name: raw.full_name || "Unknown",
            spec: specs.join(", ") || "General Practice",
            city: provinceLabel || "Pakistan",
            exp: lp.experience_years || 0,
            fee: lp.hourly_rate || null,          // null = not set
            rating: lp.rating || 0,
            avail: !!lp.availability,
            reviews: lp.total_reviews || 0,
            // null, never a generated placeholder. This field is displayed as a
            // BAR COUNCIL REGISTRATION NUMBER for a real, KYC-verified advocate,
            // and it used to fall back to `BAR-API-001`, `BAR-API-002`, … —
            // numbered by position in the current page, so the same lawyer got a
            // different "registration number" depending on how the list was
            // sorted. Inventing a professional registration number is not a
            // display placeholder, it is a false credential. The UI shows "Not
            // provided" instead.
            bar: lp.bar_number || null,
            bio: lp.bio || null,
            lat: lp.lat ?? null,
            lng: lp.lng ?? null,
            // "exact" = geocoded from an address the lawyer entered.
            // "approximate" = a province centre plus an offset the backend
            // invented, up to ~44 km out. The two arrive in the SAME lat/lng
            // fields, so without this flag the UI cannot tell an office from a
            // fabricated point — and it was offering turn-by-turn directions to
            // both. Anything that sends a client somewhere must check it.
            precision: lp.location_precision ?? (lp.lat != null ? "exact" : "none"),
            // No `distance` field at all. Nothing in the product collects the
            // client's location, so there is no distance to compute; it used to
            // be a hardcoded null that the UI rendered literally as "null km".
            // Office hours are not collected from lawyers anywhere in the
            // product. This was the constant string "Mon–Fri: 9am–5pm" shown on
            // every profile as though it were that lawyer's own schedule, which
            // a client could rely on to turn up at a closed office.
            hours: lp.office_hours || null,
            address: lp.address || null,
            credentials: specs,
            // No `reviewList` here. Review text comes from its own endpoint
            // (`getLawyerReviews`) into the `reviews` state, which stays null
            // until a response arrives — so the profile can tell "not loaded"
            // apart from "none" instead of showing a lawyer with five reviews
            // as having none.
            match_score: raw.match_score,
            match_reason: raw.match_reason,
        };
    };

    const fmtFee = (fee) => fee ? `₨${fee.toLocaleString()}` : "Consult";
    const fmtFeeK = (fee) => fee ? `₨${(fee / 1000).toFixed(1)}k` : "—";

    const [backendUp, setBackendUp] = useState(false);

    // ── The directory: one fetch, and the SERVER does the narrowing ─────────
    //
    // There were two effects here — a mount load and a filter reload — and both
    // asked for `page_size: 20` and nothing else. Everything a client typed or
    // dragged was then applied in the browser to those 20 rows: the search box,
    // the price and experience sliders, and all seven sort options. Each of
    // them answered a question about one page while appearing to answer it
    // about the directory, and the 21st lawyer was unreachable by any
    // combination of controls.
    //
    // Sorting was the clearest case. Sorting a page is not sorting a list: the
    // cheapest lawyer on the platform is very unlikely to be among the 20 you
    // happen to hold, so "Price: Low to High" showed the cheapest of a
    // rating-ordered sample and called it the cheapest.
    const [page, setPage] = useState(1);
    const [pageInfo, setPageInfo] = useState({ total: 0, pages: 1 });

    // UI sort label -> the server's sort key. The server owns what each key
    // orders by, so the client cannot ask it to sort on an arbitrary field.
    const SORT_KEYS = {
        "Rating: High to Low": "rating_desc",
        "Rating: Low to High": "rating_asc",
        "Price: Low to High": "fee_asc",
        "Price: High to Low": "fee_desc",
        "Experience: High": "experience_desc",
        "A–Z": "name_asc",
        "Z–A": "name_desc",
    };

    // The debounce is for TYPING and slider drags, so it must not delay the
    // first load. Folding the mount fetch into this effect without this made
    // every visitor wait 300 ms for a directory that could have been requested
    // immediately — a regression paid by every user to save requests only a
    // user mid-keystroke generates.
    const hasLoadedOnce = React.useRef(false);

    useEffect(() => {
        let cancelled = false;
        setLoadingLawyers(true);
        const delay = hasLoadedOnce.current ? 300 : 0;
        const timer = setTimeout(async () => {
            hasLoadedOnce.current = true;
            const params = { page, page_size: PAGE_SIZE, sort: SORT_KEYS[sortBy] };

            if (filters.city !== "All") {
                const prov = CITY_TO_PROVINCE[filters.city.toLowerCase()];
                if (prov) params.province = prov;
            }
            if (filters.specialization !== "All") {
                const ct = SPEC_TO_CASE_TYPE[filters.specialization.toLowerCase()];
                if (ct) params.case_type = ct;
            }
            if (filters.rating > 0) params.min_rating = filters.rating;
            if (filters.availability === "Available") params.availability = true;
            else if (filters.availability === "Busy") params.availability = false;

            // "Top Rated" is a rating floor, so it is a server filter too —
            // client-side it only ever promoted the best of the loaded page.
            if (filter === "Available") params.availability = true;
            else if (filter === "Top Rated") params.min_rating = Math.max(params.min_rating ?? 0, 4.8);

            if (query.trim()) {
                if (searchMode === "bar") params.bar_number = query.trim();
                else params.q = query.trim();
            }

            const { data, error } = await searchLawyers(params);
            if (cancelled) return;
            if (!error && data) {
                const items = Array.isArray(data) ? data : (data.items || []);
                setApiLawyers(items.map((l, i) => mapApiLawyer(l, i)));
                setPageInfo({
                    total: data.total ?? items.length,
                    pages: data.pages ?? 1,
                });
                setBackendUp(true);
            }
            setLoadingLawyers(false);
        }, delay);
        return () => { cancelled = true; clearTimeout(timer); };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [page, sortBy, query, searchMode, filter,
        filters.city, filters.specialization, filters.rating, filters.availability]);

    // Any change to what is being asked for returns to page 1. Without this a
    // client on page 3 who then searches sees page 3 of the new result set —
    // usually empty — and concludes there are no matches.
    useEffect(() => {
        setPage(1);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [sortBy, query, searchMode, filter,
        filters.city, filters.specialization, filters.rating, filters.availability]);

    // Reset review form whenever the selected lawyer changes
    useEffect(() => {
        setShowReviewForm(false);
        setReviewComment("");
        setReviewStars(5);
    }, [selectedLawyer]);

    // Load the reviews behind the rating.
    //
    // The rating and the count came back with the profile, so the UI could show
    // "4.6 (5)" with nothing behind it — there was no read endpoint for the
    // review text at all. `reviews` stays null until a response arrives, which
    // is what lets the profile distinguish "not loaded" from "none", rather
    // than telling a client that a lawyer with five reviews has none.
    const [reviews, setReviews] = useState(null);
    useEffect(() => {
        const id = selectedLawyer?._id;
        if (!id) { setReviews(null); return; }
        let cancelled = false;
        setReviews(null);
        getLawyerReviews(id).then(({ data, error }) => {
            if (cancelled) return;
            // On error `reviews` stays null, so the profile says the text is
            // unavailable rather than claiming there are none.
            if (!error && data) {
                setReviews((data.items || []).map(r => ({
                    user: r.reviewer,
                    rating: r.stars,
                    text: r.comment || "",
                    date: r.created_at ? String(r.created_at).slice(0, 10) : "",
                })));
            }
        });
        return () => { cancelled = true; };
    }, [selectedLawyer?._id]);

    // Fetch booked slots when date or lawyer changes inside the booking modal
    useEffect(() => {
        if (!apptDate || !apptLawyer?._id || apptLawyer._id.startsWith("api-")) {
            setBookedSlots([]);
            return;
        }
        getLawyerAvailability(apptLawyer._id, apptDate).then(({ data }) => {
            setBookedSlots(data?.booked_slots || []);
        });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [apptDate, apptLawyer?._id]);

    const isSlotBooked = (timeStr) => {
        if (!apptDate || !bookedSlots.length) return false;
        // Build UTC timestamp for the slot (local → ISO → UTC via Date)
        // PKT wall-clock, not the browser's zone.
        const slotStart = pktSlotToDate(apptDate, timeStr);
        if (!slotStart) return false;
        const slotEnd = new Date(slotStart.getTime() + 60 * 60 * 1000);
        return bookedSlots.some(b => {
            // Ensure strings without 'Z' are treated as UTC (backend now always sends Z)
            const ensureUtc = s => new Date(s.endsWith("Z") || s.includes("+") ? s : s + "Z");
            const bStart = ensureUtc(b.start);
            const bEnd = ensureUtc(b.end);
            return slotStart < bEnd && slotEnd > bStart;
        });
    };

    const isSlotPast = (timeStr) => {
        if (!apptDate) return false;
        return isPktSlotPast(apptDate, timeStr);
    };

    // Reads the same user-scoped key ModIntake writes. It used to read a
    // shared `aai-case-id`, which on a browser that had signed in as someone
    // else meant matching lawyers against a case this account cannot open.
    const getCaseId = () =>
        searchParams?.get("case_id") || readIntakeValue("aai-case-id", lawyerUserId) || null;

    const MAX_POLL_ATTEMPTS = 5;
    const POLL_INTERVAL_MS = 3000;

    const handleAiMatch = async () => {
        if (loadingMatch) return; // prevent concurrent calls
        const caseId = getCaseId();
        if (!caseId) {
            toast.show("Complete the intake form first to get AI-matched lawyers.", "info", 3500);
            return;
        }
        setLoadingMatch(true);

        let items = [];
        let lastError = null;
        let kind = null;
        let notice = null;

        for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt++) {
            // Wait 3 s before every retry (not before the first try)
            if (attempt > 0) {
                await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));
            }

            const { data, error, status } = await matchLawyers(caseId);

            if (error) {
                if (status === 0) {
                    // Connection refused — backend is not running, no point retrying
                    lastError = "Cannot reach the server. Please make sure the backend is running.";
                    break;
                }
                if (status === 401 || status === 403) {
                    // Auth failure — no point retrying
                    lastError = status === 401
                        ? "Session expired. Please sign in again."
                        : "Access denied. This case does not belong to your account.";
                    break;
                }
                if (status === 404) {
                    // Case not created yet (race condition) — treat as empty and keep polling
                } else {
                    lastError = error?.error || error?.detail || JSON.stringify(error);
                    break;
                }
            }

            items = Array.isArray(data) ? data : (data?.matches || data?.items || []);
            kind = data?.result_kind ?? null;
            notice = data?.notice ?? null;
            // "none" is a settled answer, not a slow one — there are no
            // verified lawyers to find, so polling again cannot change it.
            if (items.length > 0 || kind === "none") break;
            // else: background task still running, poll again
        }

        setMatchKind(kind);
        setMatchNotice(notice);

        if (lastError) {
            toast.show(lastError, "error", 4000);
        } else if (kind === "matched" && items.length) {
            const top = mapApiLawyer(items[0], 0);
            setAiMatch(top);
            toast.show(`AI matched you with ${top.name}`, "success", 3000);
        } else if (notice) {
            // A listing (or nothing at all). Deliberately does NOT set aiMatch:
            // these lawyers were not ranked against the case and must not be
            // presented as a recommendation.
            setAiMatch(null);
            toast.show(notice, "info", 5000);
        } else {
            toast.show("Lawyer matching is still processing — try again in a moment.", "info", 3500);
        }

        setLoadingMatch(false);
    };

    // Auto-trigger match when arriving from intake, but only once backend is confirmed reachable.
    useEffect(() => {
        if (!backendUp) return;
        const caseId = getCaseId();
        if (caseId && !aiMatch) {
            handleAiMatch();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [backendUp, searchParams]);

    const lawyers = apiLawyers;

    // Accent color palette — one per lawyer slot, cycles if more lawyers added
    const accentPalette = [
        { solid: "#1D9E75", light: "#E1F5EE", text: "#085041" },  // teal
        { solid: "#378ADD", light: "#E6F1FB", text: "#0C447C" },  // blue
        { solid: "#EF9F27", light: "#FAEEDA", light2: "#FAEEDA", text: "#633806" },  // amber
        { solid: "#7F77DD", light: "#EEEDFE", text: "#3C3489" },  // purple
        { solid: "#D85A30", light: "#FAECE7", text: "#712B13" },  // coral
        { solid: "#D4537E", light: "#FBEAF0", text: "#72243E" },  // pink
    ];

    // Fixed option lists, NOT derived from the rows on screen.
    //
    // These were built from `lawyers`, which is now one page of the directory —
    // so the specialization and province a client can filter by would be only
    // those the current page happens to contain, and choosing one could never
    // reveal anyone outside it. They are closed sets on the server (CaseType and
    // Province), so they are closed sets here.
    const specializations = ["All", "Criminal", "Civil", "Family", "Constitutional"];
    const cities = ["All", "Punjab", "Sindh", "KPK", "Balochistan", "Federal"];
    // No "Distance: Nearest". Nothing in the product collects the client's
    // location, so there is no distance to sort by — the option compared
    // `null - null` for every pair, silently returned the list untouched, and
    // presented that as a proximity ranking.
    const sortOptions = ["Rating: High to Low", "Rating: Low to High", "Price: Low to High", "Price: High to Low", "Experience: High", "A–Z", "Z–A"];

    // Shown wherever the backend genuinely has no value for a field. Saying so
    // is the honest option; the alternative is inventing one, which is how a
    // generated `BAR-API-001` came to be displayed as a bar council number.
    const UNAVAILABLE = "Not provided";

    const getAccent = (l) => {
        // Keyed on _id alone. `bar` is null whenever a lawyer has not supplied a
        // registration number, and `null === null` matched the first such lawyer
        // for every other one, giving them all the same accent colour.
        const idx = lawyers.findIndex(x => x._id === l._id);
        return accentPalette[Math.max(idx, 0) % accentPalette.length];
    };

    // The page the SERVER returned, already filtered and already sorted.
    //
    // This used to re-run every filter and the sort over `lawyers` — and while
    // the server now applies all of them, re-applying locally would not be
    // merely redundant, it would be wrong. The rows here are one page of a
    // larger ordered result, so sorting them again reorders within the page
    // (page 2 of a price sort would be re-sorted as though it were the whole
    // list), and filtering them again can only ever remove rows the server has
    // already decided belong — leaving a page that looks short for no visible
    // reason while the count beneath it says otherwise.
    const filtered = lawyers;

    // `list` is null when review text was never loaded (there is no endpoint for
    // it yet) and [] when there genuinely are none. Guarded because the caller
    // used to spread it unconditionally, which throws on null.
    const sortedReviews = (list) => [...(list || [])].sort((a, b) =>
        reviewSort === "date" ? new Date(b.date) - new Date(a.date) : b.rating - a.rating
    );

    // ── REVIEW SUBMISSION ─────────────────────────────────────────
    const submitUserReview = async (lawyerId) => {
        if (!lawyerId || lawyerId.startsWith("api-")) {
            toast.show("Reviews can only be submitted for listed lawyers.", "warn", 3000);
            return;
        }
        setReviewSubmitting(true);
        const { error } = await submitReview(lawyerId, reviewStars, reviewComment.trim() || null);
        setReviewSubmitting(false);
        if (error) {
            toast.show(error.message || "Failed to submit review. Please try again.", "error", 3000);
        } else {
            toast.show("⭐ Review submitted — thank you!", "success", 3000);
            setShowReviewForm(false);
            setReviewComment("");
            setReviewStars(5);
        }
    };

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
        selectLawyer(lawyer);
        setApptDate(pktToday()); // default to today IN PAKISTAN
        setApptTime("10:00");
        setApptDetails("");
        setApptMode("video");
        setBookedSlots([]);
        setShowApptModal(true);
    };

    // Survives re-renders, so a retry after a failed attempt carries the same
    // key. A useState would work too; a ref makes it explicit that this is not
    // rendered and must not trigger one.
    const bookingKey = useRef(createBookingKeyHolder());

    const submitBooking = async () => {
        try {
            if (!apptDate) {
                toast.show("Please select an appointment date first.", "warn", 3500);
                return;
            }

            if (!apptTime) {
                toast.show("Please select a time slot.", "warn", 3500);
                return;
            }

            // Guard: reject past date+time before hitting the API
            if (isPktSlotPast(apptDate, apptTime)) {
                toast.show("That time slot has already passed. Please select a future time.", "warn", 3500);
                return;
            }

            const isApiLawyer = apptLawyer?._id && !apptLawyer._id.startsWith("api-");
            if (!isApiLawyer) {
                toast.show("This lawyer is a sample profile — only listed lawyers can be booked.", "warn", 4000);
                return;
            }
            let bookingData = null;
            if (isApiLawyer) {
                setApptSubmitting(true);
                const scheduled_at = pktSlotToUtcISO(apptDate, apptTime);

                // One key for this booking INTENT, reused on every retry of it.
                // A key minted per request would make a second click after a
                // dropped response look like a second booking, which is exactly
                // what idempotency is here to stop.
                const intent = {
                    lawyer_id: apptLawyer._id,
                    case_id: getCaseId(),
                    scheduled_at,
                    duration_minutes: 60,
                    mode: apptMode,
                    notes: apptDetails || null,
                };
                const { error, data } = await bookAppointment({
                    ...intent,
                    idempotency_key: bookingKey.current.keyFor(intent),
                });

                setApptSubmitting(false);

                if (error) {
                    // 422 detail is a Pydantic array: [{msg: "...", loc: [...]}]
                    const raw = error.detail;
                    const errMsg = Array.isArray(raw)
                        ? raw.map(e => e.msg?.replace(/^Value error,\s*/i, "")).join("; ")
                        : (raw || error.error || "Booking failed. Please try again.");
                    toast.show(errMsg, "error", 4000);
                    return;
                }
                bookingData = data;
            }

            confirmAppointment({
                date: apptDate,
                time: apptTime,
                details: apptDetails || `Consultation with ${apptLawyer?.name}`,
                appointmentId: bookingData?.id || null,
            });

            addNotification({
                type: "hearing",
                urgency: "upcoming",
                title: `Appointment — ${apptLawyer?.name}`,
                date: formatPkt(pktSlotToDate(apptDate, apptTime), { month: "short", day: "numeric" }),
                time: apptTime,
                desc: `Consultation booked · ${apptLawyer?.spec} · ${fmtFee(apptLawyer?.fee)}/hr`,
            });

            // The intent is finished, so its key is retired: the next booking
            // is a NEW booking, and reusing this key would make the server
            // replay this appointment instead of creating that one.
            bookingKey.current.complete();

            toast.show("Appointment booked! Redirecting to tracking…", "success", 2500);
            setShowApptModal(false);
            setTimeout(() => router.push("/tracking"), 600);

        } catch {
            toast.show("An unexpected error occurred. Please try again.", "error", 4000);
            setApptSubmitting(false);
        }
    };

    // ── HIRE (ENGAGEMENT) HELPERS ─────────────────────────────────
    const openHire = (lawyer) => {
        if (!lawyer?._id || lawyer._id.startsWith("api-")) {
            toast.show("This lawyer is a sample profile — only listed lawyers can be hired.", "warn", 4000);
            return;
        }
        if (!hireableCases.length) {
            toast.show(
                myCases.some(isDraftCase)
                    ? "Finish confirming your case at the end of the intake — a draft cannot be sent to a lawyer yet."
                    : myCases.length
                        ? "All your cases already have a lawyer or a pending request."
                        : "Create a case first (via Intake) — then you can request a lawyer for it.",
                "info", 4500
            );
            return;
        }
        setHireLawyer(lawyer);
        const urlCase = getCaseId();
        const preselect = hireableCases.find(c => c._id === urlCase) || hireableCases[0];
        setHireCaseId(preselect?._id || "");
        setHireMessage("");
        setShowHireModal(true);
    };

    const submitHire = async () => {
        if (!hireCaseId) {
            toast.show("Select the case you want this lawyer to handle.", "warn", 3500);
            return;
        }
        setHireSubmitting(true);
        const { error } = await requestEngagement({
            case_id: hireCaseId,
            lawyer_id: hireLawyer._id,
            message: hireMessage.trim() || null,
        });
        setHireSubmitting(false);
        if (error) {
            toast.show(error.message || "Could not send the request. Please try again.", "error", 4000);
            return;
        }
        toast.show(`Request sent to ${hireLawyer.name}. You'll be notified when they respond.`, "success", 4000);
        setShowHireModal(false);
        refreshEngagements();
    };

    const withdrawRequest = async (engagementId) => {
        const { error } = await cancelEngagement(engagementId);
        if (error) {
            toast.show(error.message || "Could not withdraw the request.", "error", 3500);
        } else {
            toast.show("Request withdrawn.", "success", 2500);
            refreshEngagements();
        }
    };

    // ── Responding to proposed terms ──────────────────────────────
    // This is the decision the client never used to get: the lawyer set a fee
    // and took the case in the same action, so the price arrived attached to a
    // relationship that had already started and could not be ended.
    const [engBusy, setEngBusy] = useState(null);

    const acceptTerms = async (e) => {
        setEngBusy(e.id);
        const { error } = await acceptEngagementTerms(e.id);
        setEngBusy(null);
        if (error) {
            toast.show(error.message || "Could not accept the terms.", "error", 4000);
            return;
        }
        toast.show(`${e.lawyer_name || "Your lawyer"} is now engaged. The engagement letter is ready to sign on the Agreements page.`, "success", 5000);
        refreshEngagements();
    };

    const declineTerms = async (e) => {
        const reason = window.prompt("Optional: tell the lawyer why these terms don't work (leave blank to skip)");
        if (reason === null) return;
        setEngBusy(e.id);
        const { error } = await declineEngagementTerms(e.id, reason.trim() || null);
        setEngBusy(null);
        if (error) {
            toast.show(error.message || "Could not decline the terms.", "error", 3500);
            return;
        }
        toast.show("Terms declined. Your case is open again — you can approach another lawyer.", "success", 4000);
        refreshEngagements();
    };

    const endEngagement = async (e) => {
        const reason = window.prompt(
            "Ending this engagement releases your case so you can engage someone else.\n\n" +
            "Give a reason (required — it is recorded and shown to your lawyer):"
        );
        if (reason === null) return;
        if (!reason.trim()) {
            toast.show("A reason is required to end an engagement.", "warn", 3500);
            return;
        }
        setEngBusy(e.id);
        const { error } = await terminateEngagement(e.id, reason.trim());
        setEngBusy(null);
        if (error) {
            toast.show(error.message || "Could not end the engagement.", "error", 4000);
            return;
        }
        toast.show("Engagement ended. Your case is open again.", "success", 4000);
        refreshEngagements();
    };

    const markComplete = async (e) => {
        const note = window.prompt("Optional: add a note about how the matter concluded");
        if (note === null) return;
        setEngBusy(e.id);
        const { data, error } = await completeEngagement(e.id, { note: note.trim() || null });
        setEngBusy(null);
        if (error) {
            toast.show(error.message || "Could not mark this complete.", "error", 4000);
            return;
        }
        toast.show(
            data?.status === "completed"
                ? "Engagement completed."
                : "Completion proposed — your lawyer needs to confirm it.",
            "success", 4000,
        );
        refreshEngagements();
    };

    // ── HIRE MODAL ────────────────────────────────────────────────
    const HireModal = () => {
        if (!hireLawyer || typeof document === "undefined") return null;
        return createPortal(
            <div style={{
                position: "fixed", inset: 0, zIndex: 9999,
                background: "rgba(0,0,0,0.65)", backdropFilter: "blur(4px)",
                display: "flex", alignItems: "center", justifyContent: "center",
            }}>
                <div style={{
                    background: t.card, borderRadius: 20, border: `1.5px solid ${t.border}`,
                    padding: 28, width: "100%", maxWidth: 460, maxHeight: "90vh", overflowY: "auto",
                    boxShadow: "0 24px 64px rgba(0,0,0,0.4)",
                }}>
                    {/* Header */}
                    <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 18 }}>
                        <div style={{ width: 46, height: 46, borderRadius: 14, background: t.primaryGlow, border: `1.5px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20, fontWeight: 800, color: t.primary, flexShrink: 0 }}>
                            {hireLawyer.name.split(" ").map(w => w[0]).join("").slice(0, 2)}
                        </div>
                        <div style={{ flex: 1 }}>
                            <div style={{ fontWeight: 800, color: t.text, fontSize: 15 }}>Request to Hire {hireLawyer.name}</div>
                            <div style={{ fontSize: 12, color: t.textMuted }}>{hireLawyer.spec} · {fmtFee(hireLawyer.fee)}/hr</div>
                        </div>
                        <button onClick={() => setShowHireModal(false)} style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 8, width: 30, height: 30, cursor: "pointer", color: t.textMuted, fontSize: 16, display: "flex", alignItems: "center", justifyContent: "center" }}>✕</button>
                    </div>

                    <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6, marginBottom: 18, padding: "10px 14px", borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}` }}>
                        The lawyer will review your case and respond with their fee and scope.
                        Nothing is assigned until they accept — you'll get a notification either way.
                    </div>

                    {/* Case picker */}
                    <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 6 }}>Case *</label>
                        <select value={hireCaseId} onChange={e => setHireCaseId(e.target.value)}
                            style={{ width: "100%", padding: "10px 14px", borderRadius: 10, border: `1.5px solid ${hireCaseId ? t.primary : t.border}`, background: t.inputBg, color: t.text, fontSize: 13, outline: "none", boxSizing: "border-box" }}>
                            {hireableCases.map(c => (
                                <option key={c._id} value={c._id}>
                                    {c.title} ({c.case_number})
                                </option>
                            ))}
                        </select>
                    </div>

                    {/* Message */}
                    <div style={{ marginBottom: 22 }}>
                        <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 6 }}>Message to the Lawyer (optional)</label>
                        <textarea value={hireMessage} onChange={e => setHireMessage(e.target.value)}
                            placeholder="Briefly describe what you need help with, your urgency, and anything the lawyer should know…"
                            style={{ width: "100%", minHeight: 88, padding: "10px 14px", borderRadius: 10, border: `1.5px solid ${t.border}`, background: t.inputBg, color: t.text, fontSize: 13, outline: "none", resize: "vertical", boxSizing: "border-box", fontFamily: "inherit" }} />
                    </div>

                    {/* Actions */}
                    <div style={{ display: "flex", gap: 10 }}>
                        <BtnOutline onClick={() => setShowHireModal(false)} style={{ flex: 1, fontSize: 13 }}>Cancel</BtnOutline>
                        <BtnPrimary disabled={hireSubmitting} onClick={submitHire} style={{ flex: 2, fontSize: 13, padding: "12px", opacity: hireSubmitting ? 0.7 : 1 }}>
                            {hireSubmitting ? "Sending…" : "Send Hire Request →"}
                        </BtnPrimary>
                    </div>
                </div>
            </div>,
            document.body
        );
    };

    // ── APPOINTMENT MODAL ─────────────────────────────────────────
    const AppointmentModal = () => {
        if (!apptLawyer || typeof document === "undefined") return null;
        return createPortal(
            <div style={{
                position: "fixed", inset: 0, zIndex: 9999,
                background: "rgba(0,0,0,0.65)",
                backdropFilter: "blur(4px)",
                display: "flex", alignItems: "center", justifyContent: "center",
                borderRadius: 0,
            }}>
                <div style={{
                    background: t.card, borderRadius: 20, border: `1.5px solid ${t.border}`,
                    padding: 28, width: "100%", maxWidth: 460, maxHeight: "90vh", overflowY: "auto",
                    boxShadow: "0 24px 64px rgba(0,0,0,0.4)", position: "relative",
                }}>
                    {/* Header */}
                    <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 22 }}>
                        <div style={{ width: 46, height: 46, borderRadius: 14, background: t.primaryGlow, border: `1.5px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20, fontWeight: 800, color: t.primary, flexShrink: 0 }}>
                            {apptLawyer.name.split(" ").map(w => w[0]).join("").slice(0, 2)}
                        </div>
                        <div style={{ flex: 1 }}>
                            <div style={{ fontWeight: 800, color: t.text, fontSize: 15 }}>{apptLawyer.name}</div>
                            <div style={{ fontSize: 12, color: t.textMuted }}>{apptLawyer.spec} · {fmtFee(apptLawyer.fee)}/hr</div>
                        </div>
                        <button onClick={() => setShowApptModal(false)} style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 8, width: 30, height: 30, cursor: "pointer", color: t.textMuted, fontSize: 16, display: "flex", alignItems: "center", justifyContent: "center" }}>✕</button>
                    </div>

                    {/* Date */}
                    <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 6 }}>Date *</label>
                        <input type="date" value={apptDate} min={pktToday()} onChange={e => setApptDate(e.target.value)}
                            style={{ width: "100%", padding: "10px 14px", borderRadius: 10, border: `1.5px solid ${apptDate ? t.primary : t.border}`, background: t.inputBg, color: t.text, fontSize: 13, outline: "none", boxSizing: "border-box" }} />
                    </div>

                    {/* Time */}
                    <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 6 }}>Preferred Time</label>
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                            {["09:00", "10:00", "11:00", "14:00", "15:00", "16:00"].map(slot => {
                                const booked = isSlotBooked(slot);
                                const past = isSlotPast(slot);
                                const unavailable = booked || past;
                                return (
                                    <button key={slot} disabled={unavailable} onClick={() => !unavailable && setApptTime(slot)}
                                        style={{ padding: "8px 14px", borderRadius: 8, border: `1.5px solid ${unavailable ? t.border : apptTime === slot ? t.primary : t.border}`, background: unavailable ? t.inputBg : apptTime === slot ? t.primaryGlow : "transparent", color: unavailable ? t.border : apptTime === slot ? t.primary : t.textMuted, fontSize: 12, fontWeight: 700, cursor: unavailable ? "not-allowed" : "pointer", transition: "all 0.15s", textDecoration: booked ? "line-through" : "none", opacity: unavailable ? 0.35 : 1 }}>
                                        {slot}{past && !booked ? " ✕" : ""}
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    {/* Notes */}
                    <div style={{ marginBottom: 22 }}>
                        <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 6 }}>Consultation Notes (optional)</label>
                        <textarea value={apptDetails} onChange={e => setApptDetails(e.target.value)}
                            placeholder={`Brief description of your case for ${apptLawyer.name}…`}
                            style={{ width: "100%", minHeight: 72, padding: "10px 14px", borderRadius: 10, border: `1.5px solid ${t.border}`, background: t.inputBg, color: t.text, fontSize: 13, outline: "none", resize: "vertical", boxSizing: "border-box" }} />
                    </div>

                    {/* Consultation mode */}
                    <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 6 }}>Consultation Mode</label>
                        <div style={{ display: "flex", gap: 8 }}>
                            {[["video", "Video Call"], ["in_person", "In-Person"], ["phone", "Phone"]].map(([val, label]) => (
                                <button key={val} onClick={() => setApptMode(val)}
                                    style={{ flex: 1, padding: "8px 10px", borderRadius: 8, border: `1.5px solid ${apptMode === val ? t.primary : t.border}`, background: apptMode === val ? t.primaryGlow : "transparent", color: apptMode === val ? t.primary : t.textMuted, fontSize: 12, fontWeight: 700, cursor: "pointer", transition: "all 0.15s" }}>
                                    {label}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Working hours info */}
                    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}`, marginBottom: 18 }}>
                        <Ic n="clock" s={13} c={t.textMuted} />
                        <span style={{ fontSize: 12, color: t.textMuted }}>{apptLawyer.hours || "Office hours not provided"}</span>
                    </div>

                    {/* Actions */}
                    <div style={{ display: "flex", gap: 10 }}>
                        <BtnOutline onClick={() => setShowApptModal(false)} style={{ flex: 1, fontSize: 13 }}>Cancel</BtnOutline>
                        <BtnPrimary disabled={apptSubmitting} onClick={submitBooking} style={{ flex: 2, fontSize: 13, padding: "12px", opacity: apptSubmitting ? 0.7 : 1 }}>
                            {apptSubmitting ? "Booking…" : "Confirm Appointment →"}
                        </BtnPrimary>
                    </div>
                </div>
            </div>,
            document.body
        );
    };

    // Stable single-item array so LeafletMap doesn't re-run on every render
    // eslint-disable-next-line react-hooks/exhaustive-deps
    const profileMapLawyers = useMemo(() => selectedLawyer ? [selectedLawyer] : [], [selectedLawyer?._id]);

    // ── PROFILE VIEW ──────────────────────────────────────────────
    if (activeView === "profile" && selectedLawyer) {
        const l = selectedLawyer;
        const ac = getAccent(l);
        return (
            <div style={{ position: "relative" }}>
                {showApptModal && <AppointmentModal />}
                {showHireModal && <HireModal />}
                <button onClick={() => setActiveView("list")} style={{ display: "flex", alignItems: "center", gap: 8, background: "none", border: "none", color: t.primary, cursor: "pointer", fontSize: 13, fontWeight: 600, marginBottom: 20, padding: 0 }}>
                    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke={t.primary} strokeWidth="2"><path d="M19 12H5M12 5l-7 7 7 7" /></svg>
                    Back to Lawyers
                </button>
                <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
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
                                    <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>Bar No: {l.bar || UNAVAILABLE}</div>
                                    <div style={{ display: "flex", gap: 6, marginTop: 6, alignItems: "center" }}>
                                        <StarRow rating={l.rating} color={ac.solid} size={13} />
                                        <span style={{ fontSize: 12, color: t.textMuted, marginLeft: 4 }}>{l.rating} · {l.reviews} reviews</span>
                                    </div>
                                </div>
                            </div>
                            {l.bio && (
                                <p style={{ fontSize: 13, color: t.textDim, margin: "12px 0 0", lineHeight: 1.6 }}>{l.bio}</p>
                            )}
                            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 10, marginTop: 16, background: t.inputBg, borderRadius: 12, padding: 14 }}>
                                {[["Experience", `${l.exp} yrs`], ["Fee/hr", fmtFee(l.fee)], ["City", l.city]].map(([k, v]) => (
                                    <div key={k} style={{ textAlign: "center" }}>
                                        <div style={{ fontSize: 10, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.5px" }}>{k}</div>
                                        <div style={{ fontSize: 14, fontWeight: 700, color: t.text, marginTop: 3 }}>{v}</div>
                                    </div>
                                ))}
                            </div>
                            <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
                                <BtnOutline
                                    onClick={() => l.avail && !l._id?.startsWith("api-") && openBooking(l)}
                                    style={{ flex: 1, fontSize: 13, opacity: (!l.avail || l._id?.startsWith("api-")) ? 0.5 : 1, cursor: (!l.avail || l._id?.startsWith("api-")) ? "not-allowed" : "pointer" }}
                                >Book Appointment</BtnOutline>
                                {(() => {
                                    const engState = engagementWith(l._id);
                                    if (engState === "accepted") return (
                                        <BtnPrimary disabled style={{ flex: 1, fontSize: 13, opacity: 0.75 }}>✓ Engaged on Your Case</BtnPrimary>
                                    );
                                    if (engState === "requested") return (
                                        <BtnPrimary disabled style={{ flex: 1, fontSize: 13, opacity: 0.75 }}>Request Pending…</BtnPrimary>
                                    );
                                    return (
                                        <BtnPrimary
                                            disabled={l._id?.startsWith("api-")}
                                            onClick={() => openHire(l)}
                                            style={{ flex: 1, fontSize: 13 }}
                                            title={l._id?.startsWith("api-") ? "Sample profile — cannot be hired" : "Ask this lawyer to take your case"}
                                        >Request to Hire</BtnPrimary>
                                    );
                                })()}
                            </div>
                        </Card>
                        <Card>
                            <div style={{ fontWeight: 700, color: t.text, fontSize: 14, marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
                                <Ic n="shield" s={15} c={t.primary} /> Credentials & Qualifications
                            </div>
                            {/* The platform reviews what a lawyer submits; it does not
                                confirm enrolment with any Bar Council — no such check
                                exists in the system. Saying so here is the difference
                                between a listing and a guarantee. */}
                            <div style={{ fontSize: 11.5, color: t.textMuted, lineHeight: 1.5, marginBottom: 12, padding: "8px 10px", borderRadius: 8, background: t.border + "40" }}>
                                Credentials below are provided by the lawyer and reviewed by our team.
                                We do not independently confirm Bar Council enrolment — please verify
                                directly before engaging.
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
                            {[["Working Hours", l.hours || UNAVAILABLE], ["Office Address", l.address || UNAVAILABLE], ["Consultation Fee", l.fee ? `${fmtFee(l.fee)} / hour` : UNAVAILABLE]].map(([k, v]) => (
                                <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 10 }}>
                                    <span style={{ fontSize: 12, color: t.textMuted, flexShrink: 0 }}>{k}</span>
                                    <span style={{ fontSize: 13, color: t.text, fontWeight: 600, textAlign: "right" }}>{v}</span>
                                </div>
                            ))}
                        </Card>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                        <Card style={{ padding: 0, overflow: "hidden" }}>
                            {/* Real embedded map centred on this lawyer */}
                            <LeafletMap
                                lawyers={profileMapLawyers}
                                height={200}
                                onSelect={() => { }}
                            />
                            <div style={{ padding: "10px 14px", borderTop: `1px solid ${t.border}` }}>
                                <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 8 }}>
                                    <strong style={{ color: t.text }}>{l.address || UNAVAILABLE}</strong>
                                    {l.city && l.address !== l.city && (
                                        <span> · {l.city}</span>
                                    )}
                                </div>
                                {/* Navigation is offered ONLY for a real address.
                                    Both buttons used to fall back to the pin, and the pin is a
                                    province centre plus an invented offset of up to ~44 km
                                    whenever the lawyer never entered an address — so "Get
                                    Directions" routed a client to a fabricated destination, with
                                    nothing on screen suggesting it was not their lawyer's office.
                                    The address fallback was no better: `l.address` is null for
                                    such a lawyer, and `encodeURIComponent(null)` is the string
                                    "null", which was being sent to Google Maps as a search term. */}
                                {l.precision === "exact" ? (
                                    <div style={{ display: "flex", gap: 10 }}>
                                        <BtnOutline style={{ flex: 1, fontSize: 12, padding: "9px" }}
                                            onClick={() => {
                                                const q = `${l.lat},${l.lng}`;
                                                window.open(`https://www.google.com/maps/search/?api=1&query=${q}`, "_blank");
                                            }}>
                                            <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                                                <Ic n="map" s={13} c={t.primary} /> View on Map
                                            </span>
                                        </BtnOutline>
                                        <BtnPrimary style={{ flex: 1, fontSize: 12, padding: "9px" }}
                                            onClick={() => {
                                                const dest = `${l.lat},${l.lng}`;
                                                window.open(`https://www.google.com/maps/dir/?api=1&destination=${dest}`, "_blank");
                                            }}>
                                            <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                                                <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2L4.5 20.29l.71.71L12 18l6.79 3 .71-.71z" /></svg>
                                                Get Directions
                                            </span>
                                        </BtnPrimary>
                                    </div>
                                ) : (
                                    <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6 }}>
                                        This lawyer has not published an office address, so the pin
                                        above shows {l.city ? <strong style={{ color: t.text }}>{l.city}</strong> : "their province"} only
                                        and directions are not available. Ask them for the address
                                        when you book.
                                    </div>
                                )}
                            </div>
                        </Card>
                        <Card>
                            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
                                <div style={{ fontWeight: 700, color: t.text, fontSize: 14, display: "flex", alignItems: "center", gap: 8 }}>
                                    <Ic n="star" s={15} c={t.warn} /> Reviews
                                    <span style={{ fontSize: 13, color: t.primary, fontWeight: 700 }}>{l.rating}</span>
                                    <span style={{ fontSize: 12, color: t.textMuted }}>({l.reviews})</span>
                                </div>
                                {/* The sort control only makes sense once there
                                    is something to sort. */}
                                {reviews?.length ? (
                                    <select value={reviewSort} onChange={e => setReviewSort(e.target.value)} style={{ background: t.inputBg, border: `1px solid ${t.border}`, color: t.text, borderRadius: 8, padding: "5px 10px", fontSize: 12, outline: "none" }}>
                                        <option value="date">By Date</option>
                                        <option value="rating">By Rating</option>
                                    </select>
                                ) : null}
                            </div>
                            {/* Three distinct states, deliberately not collapsed
                                into one. `null` is "still loading, or the
                                request failed" — NOT "there are none". Telling a
                                client that a lawyer with five reviews has none,
                                because a fetch was in flight or errored,
                                misrepresents that lawyer; the count beside the
                                rating would also visibly contradict it. */}
                            {reviews === null ? (
                                <div style={{ fontSize: 12, color: t.textMuted, padding: "10px 0" }}>
                                    {l.reviews > 0
                                        ? `Loading ${l.reviews} review${l.reviews === 1 ? "" : "s"}…`
                                        : "Loading reviews…"}
                                </div>
                            ) : reviews.length === 0 ? (
                                <div style={{ fontSize: 12, color: t.textMuted, padding: "10px 0" }}>
                                    No reviews yet.
                                </div>
                            ) : null}
                            {sortedReviews(reviews).map((r, i) => (
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

                            {/* Write a Review */}
                            <div style={{ marginTop: 12, borderTop: `1px solid ${t.border}`, paddingTop: 12 }}>
                                {!showReviewForm ? (
                                    <button onClick={() => setShowReviewForm(true)}
                                        style={{ width: "100%", padding: "9px", borderRadius: 10, border: `1.5px solid ${t.primary}`, background: "transparent", color: t.primary, fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                                        Write a Review
                                    </button>
                                ) : (
                                    <div>
                                        <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 8 }}>Your Rating</div>
                                        <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 12 }}>
                                            {[1, 2, 3, 4, 5].map(s => (
                                                <button key={s} onClick={() => setReviewStars(s)}
                                                    style={{ background: "none", border: "none", cursor: "pointer", padding: 2, lineHeight: 0 }}>
                                                    <svg width={22} height={22} viewBox="0 0 24 24">
                                                        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"
                                                            fill={s <= reviewStars ? t.warn : "transparent"}
                                                            stroke={s <= reviewStars ? t.warn : t.border} strokeWidth="1.5" />
                                                    </svg>
                                                </button>
                                            ))}
                                            <span style={{ fontSize: 12, color: t.textMuted, marginLeft: 4 }}>{reviewStars} / 5</span>
                                        </div>
                                        <textarea value={reviewComment} onChange={e => setReviewComment(e.target.value)}
                                            placeholder="Share your experience with this lawyer…"
                                            style={{ width: "100%", minHeight: 72, padding: "8px 12px", borderRadius: 10, border: `1.5px solid ${t.border}`, background: t.inputBg, color: t.text, fontSize: 12, outline: "none", resize: "vertical", boxSizing: "border-box", fontFamily: "inherit" }} />
                                        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                                            <button onClick={() => setShowReviewForm(false)}
                                                style={{ flex: 1, padding: "8px", borderRadius: 8, border: `1px solid ${t.border}`, background: "transparent", color: t.textMuted, fontSize: 12, cursor: "pointer", fontFamily: "inherit" }}>
                                                Cancel
                                            </button>
                                            <button onClick={() => submitUserReview(l._id)} disabled={reviewSubmitting}
                                                style={{ flex: 2, padding: "8px", borderRadius: 8, border: "none", background: t.primary, color: t.mode === "dark" ? "#1A2E35" : "#fff", fontSize: 12, fontWeight: 700, cursor: reviewSubmitting ? "not-allowed" : "pointer", opacity: reviewSubmitting ? 0.7 : 1, fontFamily: "inherit" }}>
                                                {reviewSubmitting ? "Submitting…" : "Submit Review"}
                                            </button>
                                        </div>
                                    </div>
                                )}
                            </div>
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
                {/* The location input and its "Find Nearby" button are gone.
                    Nothing in the product geocodes the client, and the button
                    carried no onClick at all — typing an address and pressing it
                    did nothing, while the screen still promised proximity
                    search. The pins below are province-centre approximations,
                    which the notice says plainly rather than implying a
                    surveyed office location. */}
                <Card style={{ marginBottom: 16 }}>
                    <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                        <Ic n="map" s={15} c={t.textMuted} />
                        <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6 }}>
                            Pins show each lawyer&apos;s <strong style={{ color: t.text }}>province</strong>, not their
                            office address. Distances are not calculated. Open a
                            profile for the address the lawyer has provided.
                        </div>
                    </div>
                </Card>
                <Card style={{ padding: 0, overflow: "hidden", marginBottom: 16 }}>
                    <LeafletMap
                        lawyers={filtered}
                        height={340}
                        onSelect={l => { setSelectedLawyer(l); setActiveView("profile"); }}
                    />
                </Card>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {filtered.map((l) => {
                        const ac = getAccent(l);
                        return (
                            <Card key={l._id || l.bar} style={{ display: "flex", alignItems: "center", gap: 14, cursor: "pointer", transition: "all 0.2s" }}
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
                                    <div style={{ fontSize: 13, fontWeight: 700, color: t.primary }}>{l.city}</div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>province</div>
                                </div>
                                {/* Labelled for what it does. It was "Directions" and opened the
                                    profile — it has never navigated anywhere. */}
                                <BtnOutline style={{ fontSize: 12, padding: "7px 14px", flexShrink: 0 }} onClick={e => { e.stopPropagation(); setSelectedLawyer(l); setActiveView("profile"); }}>View Profile</BtnOutline>
                            </Card>
                        );
                    })}
                </div>
            </div>
        );
    }

    // ── LIST VIEW (default) ───────────────────────────────────────
    // `terms_proposed` is the one a client must not miss — it is the only
    // screen where they see a price before agreeing to it.
    const VISIBLE_ENG = ["requested", "terms_proposed", "accepted"];
    const visibleEngagements = myEngagements.filter(e => VISIBLE_ENG.includes(e.status));
    const FEE_SUFFIX = { hourly: "/hr", per_hearing: "/hearing" };
    const feeLabel = (e) =>
        e.fee_amount
            ? `PKR ${Number(e.fee_amount).toLocaleString()}${FEE_SUFFIX[e.fee_type] || ""}`
            : "";

    const engBtn = (t) => ({
        fontSize: 11, fontWeight: 600, color: t.textMuted, background: "none",
        border: `1px solid ${t.border}`, borderRadius: 8, padding: "4px 10px",
        cursor: "pointer", flexShrink: 0,
    });

    const ENG_BADGE = {
        requested:      { label: "Pending",       color: "#EF9F27" },
        terms_proposed: { label: "Terms received", color: "#3B82F6" },
        accepted:       { label: "Engaged",       color: "#1D9E75" },
        completed:      { label: "Completed",     color: "#6B7280" },
        terminated:     { label: "Ended",         color: "#9CA3AF" },
    };
    return (
        <div style={{ position: "relative" }}>
            {showApptModal && <AppointmentModal />}
            {showHireModal && <HireModal />}

            {/* ── Directory Banner ─────────────────────────── */}
            <div style={{ position: "relative", marginBottom: 22, borderRadius: 20, overflow: "hidden", border: `1px solid ${t.border}`, boxShadow: t.shadowCard }}>
                <div style={{ height: 210, background: "linear-gradient(135deg,#0d1117 0%,#161b2e 100%)" }} />

                {/* Left gradient overlay with text */}
                <div style={{
                    position: "absolute", inset: 0,
                    background: "linear-gradient(to right, rgba(8,10,18,0.88) 0%, rgba(8,10,18,0.55) 45%, transparent 72%)",
                    display: "flex", alignItems: "center", padding: "0 32px",
                    pointerEvents: "none",
                }}>
                    <div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                            <div style={{ width: 6, height: 6, borderRadius: "50%", background: t.primary }} />
                            <span style={{ fontSize: 11, color: t.primary, fontWeight: 700, textTransform: "uppercase", letterSpacing: "1.5px" }}>Legal Directory</span>
                        </div>
                        <div style={{ fontSize: 22, fontWeight: 800, color: "#fff", lineHeight: 1.25, marginBottom: 8, maxWidth: 280 }}>
                            Find Expert Legal Counsel
                        </div>
                        <div style={{ fontSize: 13, color: "rgba(255,255,255,0.62)", maxWidth: 260, lineHeight: 1.6, marginBottom: 18 }}>
                            Browse listed lawyers and request a consultation time.
                        </div>
                        {/* Quick stats */}
                        <div style={{ display: "flex", gap: 20 }}>
                            {[
                                [lawyers.length, "Lawyers"],
                                [lawyers.filter(l => l.avail).length, "Accepting Requests"],
                                [new Set(lawyers.map(l => l.city)).size, "Cities"],
                            ].map(([val, label]) => (
                                <div key={label}>
                                    <div style={{ fontSize: 20, fontWeight: 800, color: t.primary }}>{val}</div>
                                    <div style={{ fontSize: 11, color: "rgba(255,255,255,0.5)", marginTop: 1 }}>{label}</div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>

            </div>

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

                    <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 20 }}>
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

                    <div style={{ marginBottom: 20 }}>
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

                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingTop: 14, borderTop: `1px solid ${t.border}` }}>
                        <div style={{ fontSize: 12, color: t.textMuted }}>
                            <span style={{ color: t.primary, fontWeight: 700 }}>{filtered.length}</span> lawyers match
                        </div>
                        <div style={{ display: "flex", gap: 10 }}>
                            <button onClick={() => setFilters({ specialization: "All", city: "All", rating: 0, availability: "All" })} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: t.textMuted, background: "none", border: `1.5px solid ${t.border}`, cursor: "pointer", padding: "9px 18px", borderRadius: 10, transition: "all 0.15s" }}
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

            {/* My hire requests */}
            {visibleEngagements.length > 0 && (
                <div style={{ background: t.card, border: `1.5px solid ${t.border}`, borderRadius: 16, padding: "14px 18px", marginBottom: 20 }}>
                    <div style={{ fontSize: 12, fontWeight: 800, color: t.text, textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
                        <Ic n="shield" s={14} c={t.primary} /> My Hire Requests
                    </div>
                    {visibleEngagements.map(e => {
                        const badge = ENG_BADGE[e.status];
                        return (
                            <div key={e.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 0", borderBottom: `1px solid ${t.border}` }}>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontSize: 13, fontWeight: 700, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                        {e.lawyer_name || "Lawyer"} · {e.case_title || e.case_number}
                                    </div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>
                                        {e.status === "accepted"
                                            ? `Engaged${feeLabel(e) ? ` — ${feeLabel(e)}` : ""}. Track progress on the Tracking page.`
                                            : e.status === "terms_proposed"
                                                ? `${e.lawyer_name || "The lawyer"} proposed ${feeLabel(e) || "terms"}. Nothing is agreed until you accept.`
                                                : "Waiting for the lawyer to respond…"}
                                    </div>
                                    {e.status === "terms_proposed" && e.scope_note && (
                                        <div style={{ fontSize: 11, color: t.textDim, marginTop: 4, fontStyle: "italic" }}>
                                            Scope: {e.scope_note}
                                        </div>
                                    )}
                                    {e.status === "accepted" && e.completion_proposed_by && (
                                        <div style={{ fontSize: 11, color: t.primary, marginTop: 4 }}>
                                            {e.completion_proposed_by === "lawyer"
                                                ? "Your lawyer says the work is finished — confirm to close this engagement."
                                                : "You proposed completion; waiting for your lawyer to confirm."}
                                        </div>
                                    )}
                                </div>
                                <span style={{ fontSize: 11, fontWeight: 700, color: badge.color, background: `${badge.color}18`, borderRadius: 20, padding: "3px 10px", flexShrink: 0 }}>{badge.label}</span>

                                {e.status === "requested" && (
                                    <button onClick={() => withdrawRequest(e.id)} disabled={engBusy === e.id}
                                        style={engBtn(t)}>
                                        Withdraw
                                    </button>
                                )}

                                {e.status === "terms_proposed" && (
                                    <>
                                        <button onClick={() => declineTerms(e)} disabled={engBusy === e.id}
                                            style={engBtn(t)}>
                                            Decline
                                        </button>
                                        <button onClick={() => acceptTerms(e)} disabled={engBusy === e.id}
                                            style={{ ...engBtn(t), color: "#fff", background: t.primary, border: `1px solid ${t.primary}` }}>
                                            {engBusy === e.id ? "Accepting…" : "Accept terms"}
                                        </button>
                                    </>
                                )}

                                {e.status === "accepted" && (
                                    <>
                                        <button onClick={() => markComplete(e)} disabled={engBusy === e.id}
                                            style={engBtn(t)}>
                                            {e.completion_proposed_by === "lawyer" ? "Confirm complete" : "Mark complete"}
                                        </button>
                                        <button onClick={() => endEngagement(e)} disabled={engBusy === e.id}
                                            style={{ ...engBtn(t), color: "#B91C1C", borderColor: "#FCA5A5" }}>
                                            End engagement
                                        </button>
                                    </>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}

            {/* AI Match Banner */}
            <div style={{ background: `linear-gradient(135deg,${t.primaryGlow},transparent)`, border: `1.5px dashed ${t.primary}40`, borderRadius: 16, padding: 16, marginBottom: 20, display: "flex", alignItems: "center", gap: 14 }}>
                <div style={{ width: 42, height: 42, borderRadius: 13, background: `${t.primary}20`, display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <Ic n="zap" s={20} c={t.primary} />
                </div>
                <div style={{ flex: 1 }}>
                    {/* A listing is not a recommendation, so it does not get the
                        recommendation heading. */}
                    <div style={{ fontWeight: 700, color: t.text, fontSize: 13 }}>
                        {!aiMatch && (matchKind === "general_listing" || matchKind === "none")
                            ? "No strong match yet"
                            : "AI-Recommended Match"}
                    </div>
                    <div style={{ fontSize: 12, color: t.textMuted }}>
                        {aiMatch
                            // No `|| 0.97` fallback. A missing score used to
                            // render as "97% case compatibility" on lawyers the
                            // matcher had never scored against the case.
                            ? [
                                aiMatch.name,
                                aiMatch.spec,
                                // "match score", not "case compatibility".
                                // match_score is a weighted blend of five
                                // factors — semantic fit is only half of it,
                                // the rest is specialization, province, rating,
                                // availability and experience. A lawyer with no
                                // measured relevance to the case still scores
                                // ~0.48 on the other factors alone, and calling
                                // that "48% case compatibility" claims a
                                // measurement of fit the number does not carry.
                                aiMatch.match_score != null
                                    ? `${Math.round(aiMatch.match_score * 100)}% match score`
                                    : null,
                                aiMatch.match_reason || null,
                            ].filter(Boolean).join(" — ")
                            : matchNotice
                                ? matchNotice
                                : getCaseId()
                                    ? "Click to find your AI-matched lawyer"
                                    : "Complete intake form first to get your AI match"}
                    </div>
                </div>
                <BtnPrimary
                    disabled={loadingMatch}
                    onClick={aiMatch
                        ? () => { setSelectedLawyer(aiMatch); setActiveView("profile"); }
                        : handleAiMatch
                    }
                    style={{ fontSize: 12, padding: "10px 18px", flexShrink: 0, opacity: loadingMatch ? 0.7 : 1 }}
                >
                    {loadingMatch ? "Matching…" : aiMatch ? "View Match" : "Find My Match"}
                </BtnPrimary>
            </div>

            {/* Results count.
                Reports the page AND the total, because `filtered.length` alone
                is the size of one page — it read "Showing 20 lawyers" whether
                the directory held 20 or 2000. */}
            <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 12 }}>
                Showing <span style={{ color: t.primary, fontWeight: 700 }}>{filtered.length}</span>
                {" "}of <span style={{ color: t.primary, fontWeight: 700 }}>{pageInfo.total}</span> lawyers
                {pageInfo.pages > 1 && <> · page {page} of {pageInfo.pages}</>}
            </div>

            {/* ── LAWYER CARDS (redesigned) ─────────────────────────── */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(290px,1fr))", gap: 16 }}>
                {filtered.map((l) => {
                    const ac = getAccent(l);
                    return (
                        <div
                            key={l._id || l.bar}
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

                                {/* Header row: avatar + name + province badge */}
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
                                        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 1 }}>{l.bar || UNAVAILABLE}</div>
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
                                        {l.city}
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
                                    {[["Experience", `${l.exp}yr`], null, ["Fee/hr", fmtFeeK(l.fee)], null, ["City", l.city]].map((item, i) => {
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
                        <button onClick={() => { setQuery(""); setFilter("All"); setFilters({ specialization: "All", city: "All", rating: 0, availability: "All" }); }} style={{ marginTop: 10, background: "none", border: "none", color: t.primary, cursor: "pointer", fontSize: 13, fontWeight: 600 }}>Clear all filters</button>
                    </div>
                )}
            </div>

            {/* ── Pagination ─────────────────────────────────────────
                The control that makes the rest of the directory reachable at
                all. Everything past the first page existed in the database and
                had no route to the screen. */}
            {pageInfo.pages > 1 && (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 14, marginTop: 24 }}>
                    <BtnOutline
                        onClick={() => setPage(p => Math.max(1, p - 1))}
                        disabled={page <= 1 || loadingLawyers}
                        style={{ opacity: page <= 1 ? 0.45 : 1, cursor: page <= 1 ? "not-allowed" : "pointer" }}>
                        ← Previous
                    </BtnOutline>
                    <span style={{ fontSize: 13, color: t.textMuted }}>
                        Page <span style={{ color: t.text, fontWeight: 700 }}>{page}</span> of {pageInfo.pages}
                    </span>
                    <BtnOutline
                        onClick={() => setPage(p => Math.min(pageInfo.pages, p + 1))}
                        disabled={page >= pageInfo.pages || loadingLawyers}
                        style={{ opacity: page >= pageInfo.pages ? 0.45 : 1, cursor: page >= pageInfo.pages ? "not-allowed" : "pointer" }}>
                        Next →
                    </BtnOutline>
                </div>
            )}
        </div>
    );
};

export default ModLawyers;
