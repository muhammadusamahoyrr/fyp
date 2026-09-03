/* How the UI is allowed to describe an answer's evidence.
 *
 * WHY THIS IS SHARED
 * ------------------
 * Three surfaces render the same backend fields: the client chatbot, the
 * lawyer AI Legal page, and the AI tab inside a case workspace. Each mapped
 * `citations` itself, and they had already drifted — the workspace tab dropped
 * `url` and `source` entirely, so a judgment that links to a court PDF on one
 * lawyer screen was an unclickable label on the other. The backend keeps one
 * `confidence_payload()` so its two transports cannot describe a pipeline
 * differently; this is the same rule on the client side.
 *
 * WHAT THE VOCABULARY MEANS (app/ai/answer_citations.py is the source of truth)
 * ---------------------------------------------------------------------------
 *   matched      the answer cites it AND it is in this answer's evidence
 *   unresolved   the answer cites it and it is NOT — "we cannot show you where
 *                this came from", a statement about our evidence, not about the
 *                law. CrPC s.154 really is the FIR provision; an answer citing
 *                it from memory is correct while being unresolved here.
 *   retrieved    consulted, not cited by the answer
 *
 * There is deliberately no "verified". A section existing in the corpus is not
 * evidence that it says what the answer claims.
 *
 *   repealed     the Act itself declares the section omitted
 *   unknown      everything else — NOT a clean bill of health. Repeal data
 *                covers 4 of 43 statutes, is a self-declared lower bound, and
 *                no statute carries an as-of date, so silence is absence of
 *                evidence rather than evidence of currency.
 */

export const MATCHED = "matched";
export const UNRESOLVED = "unresolved";
export const RETRIEVED = "retrieved";
export const REPEALED = "repealed";

/* Ordered: what the answer leaned on leads, what was merely consulted trails.
 * Two captions because the audiences differ — a lawyer is told to verify
 * independently, a client is told plainly that we could not locate it. */
export const CITATION_GROUPS = [
    {
        key: MATCHED,
        lawyer: "Cited by this answer · found in retrieved sources",
        client: "Cited by this answer, found in our law sources",
        icon: "✓",
    },
    {
        key: UNRESOLVED,
        lawyer: "Cited by this answer · NOT in retrieved sources — verify independently",
        client: "Cited by this answer — we could not locate it in our sources",
        icon: "?",
    },
    {
        key: RETRIEVED,
        lawyer: "Retrieved but not cited in this answer",
        client: "Consulted, not cited in this answer",
        icon: "\u{1F4D6}",
    },
];

/* An external URL fit to render as a link, or "".
 *
 * A judgment carries a court-published PDF URL that reaches the browser through
 * the citator and the API, which makes it data, and this is the last point
 * before it becomes an `href`. An allowlist rather than a blocklist, because
 * the dangerous schemes are the ones nobody thinks to list: `javascript:` runs
 * in the page, `data:text/html` renders attacker markup, `file:` addresses the
 * reader's own disk. A scheme-relative `//host/path` is refused too — it has no
 * scheme of its own and inherits the page's, so it reads as safe while
 * behaving like whatever loaded it.
 *
 * The server applies the same rule (app/ai/source_links.safe_external_url).
 * Both, deliberately: the server decides what is stored and sent, this decides
 * what is rendered, and a cached answer written before the server-side rule
 * existed still reaches this one. */
const SAFE_SCHEMES = new Set(["http:", "https:"]);

export function safeExternalUrl(value) {
    if (typeof value !== "string") return "";
    const text = value.trim();
    if (!text) return "";
    // WHATWG parsing REPAIRS an empty authority: `new URL("http:///x.pdf")`
    // yields `http://x.pdf/`, promoting the first path segment to the host.
    // Python's urlsplit leaves the netloc empty and rejects the same string, so
    // without this the server and the browser would disagree about one input —
    // and a rule enforced in two places that disagree is worse than one place.
    // Require a scheme, `//`, then at least one character that is not a
    // path/query/fragment delimiter.
    if (!/^[a-z][a-z0-9+.-]*:\/\/[^/?#]/i.test(text)) return "";
    let parsed;
    try {
        // No base: a relative or scheme-relative string must FAIL to parse
        // rather than be resolved against the current page.
        parsed = new URL(text);
    } catch {
        return "";
    }
    if (!SAFE_SCHEMES.has(parsed.protocol)) return "";
    return parsed.host ? text : "";
}

export const CURRENCY_TEXT = {
    repealed: "Repealed provision — do not rely on this authority",
    unknown: "Current status not verified",
};

/* Per-statement verdicts from the grounding judge. `unassessed` is a real
 * outcome, not a gap to be filled: a missing verdict is not evidence of
 * support, and a claim whose citation could not be resolved has no source to
 * be judged against at all. */
export const SUPPORT_ORDER = ["unsupported", "partial", "unassessed", "supported"];

export const SUPPORT_LABEL = {
    supported: "Supported by the cited source",
    partial: "Partly supported — check the source",
    unsupported: "Not supported by the cited source",
    unassessed: "Not assessed",
};

/* One citation, in the shape every surface renders.
 *
 * Tolerant by design: this runs on a network payload, and a missing field must
 * degrade to the cautious value. An unknown `status` becomes `retrieved`
 * ("consulted"), never `matched` — overstating what an answer cited is the one
 * direction that misleads. */
export function normaliseCitation(raw) {
    const c = raw || {};
    const judgment = c.type === "judgment";
    const label = [c.statute, c.section ? `§${c.section}` : ""]
        .filter(Boolean).join(" ").trim();
    const status = [MATCHED, UNRESOLVED, RETRIEVED].includes(c.status)
        ? c.status : RETRIEVED;
    return {
        label,
        judgment,
        status,
        // Two kinds of link, and they are NOT interchangeable.
        //
        //   href       an external document — a court's own judgment PDF. A
        //              real anchor: it needs no credentials of ours.
        //   sourceUrl  a corpus document on OUR API, which is bearer-
        //              authenticated like every other route. A new tab carries
        //              no Authorization header, so rendering this as an anchor
        //              opens a 401 page. It must go through
        //              api.openSourceDocument, which fetches then opens a blob.
        //
        // Both are stamped server-side and only when the document really
        // exists — `source_url` covers about half the corpus by chunk count,
        // and a basename the corpus holds twice is left unlinkable because it
        // names no single document — so an empty value means "nothing to
        // open", never a link that 404s.
        //
        // `href` is scheme-checked here as well as on the server: this is the
        // last point before it becomes an anchor, and it is the only check a
        // cached answer written before the server-side rule will pass through.
        href: judgment ? (safeExternalUrl(c.url) || safeExternalUrl(c.source)) : "",
        sourceUrl: judgment ? "" : (c.source_url || ""),
        currency: c.currency === REPEALED ? REPEALED : "unknown",
        instrument: c.instrument || "",
        date: c.date || "",
        jurisdiction: c.jurisdiction || "",
        province: c.province || "",
        chunkId: c.chunk_id || "",
        source: c.source || "",
    };
}

export function normaliseCitations(list) {
    return (list || []).map(normaliseCitation).filter(c => c.label);
}

/* Citations for one group, in the order CITATION_GROUPS declares. */
export function citationsInGroup(citations, key) {
    return (citations || []).filter(c => (c.status || RETRIEVED) === key);
}

/* How the "sources" toggle should label itself.
 *
 * "Cited in this answer (n)" counts only what the answer actually cited.
 * Counting everything retrieved under that label is the original bug this
 * whole area exists to fix: retrieval telemetry wearing a citation label. */
export function citationSummary(citations) {
    const list = citations || [];
    const cited = list.filter(c => c.status !== RETRIEVED);
    return {
        total: list.length,
        cited: cited.length,
        unresolved: list.filter(c => c.status === UNRESOLVED).length,
        repealed: list.filter(c => c.currency === REPEALED).length,
        linkable: list.filter(c => c.href || c.sourceUrl).length,
        label: cited.length > 0
            ? `Cited in this answer (${cited.length})`
            : `Sources consulted (${list.length})`,
    };
}

/* "repealed by <instrument> <date> (punjab only)", or "" when we know no more
 * than the fact of repeal. A province-scoped repeal is stated as scoped: a
 * section killed by a Punjab notification is alive in Sindh, and asserting it
 * dead nationally would be a false statement of law in three provinces. */
export function repealNote(source) {
    const s = source || {};
    if (s.currency !== REPEALED) return "";
    const bits = [s.instrument, s.date].filter(Boolean).join(" ");
    const scope = s.jurisdiction && s.jurisdiction !== "federal"
        ? ` (${s.jurisdiction} only)` : "";
    return bits ? `repealed by ${bits}${scope}` : "";
}

/* Claims worth showing first: a repealed source outranks everything, then the
 * verdicts that need a human, then the rest. A repealed source OVERRIDES a
 * "supported" verdict — the source can genuinely say what the claim says and
 * still have been struck from the books. */
export function sortClaims(claims) {
    return [...(claims || [])].sort((a, b) => {
        const dead = (c) => (c.currency === REPEALED ? 0 : 1);
        if (dead(a) !== dead(b)) return dead(a) - dead(b);
        return SUPPORT_ORDER.indexOf(a.support) - SUPPORT_ORDER.indexOf(b.support);
    });
}

/* The warnings that must be visible WITHOUT opening a panel. The finding that
 * matters most — "this sentence rests on law that has been repealed" — is
 * worthless hidden behind a click. */
export function claimWarnings(claims) {
    const list = claims || [];
    return {
        repealed: list.filter(c => c.currency === REPEALED).length,
        unsupported: list.filter(c => c.support === "unsupported").length,
        partial: list.filter(c => c.support === "partial").length,
    };
}

/* ── the request id ───────────────────────────────────────────────────────
 *
 * Every turn writes a provenance record keyed by this id. Showing it is what
 * makes an answer nameable: quotable in a report, and openable as an audit
 * trail on the lawyer surface. */

export function shortRequestId(id) {
    const value = String(id || "");
    return value.length > 12 ? `${value.slice(0, 8)}…` : value;
}

/* Copy to the clipboard, resolving to whether it worked.
 *
 * navigator.clipboard is undefined outside a secure context, which includes
 * plain-http LAN testing — the exact setup this project is demoed on. Falling
 * back rather than throwing means the button does not silently do nothing on
 * the machine it is most likely to be shown on. */
export async function copyText(text) {
    const value = String(text || "");
    if (!value) return false;
    try {
        if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(value);
            return true;
        }
    } catch {
        /* fall through to the legacy path */
    }
    try {
        if (typeof document === "undefined") return false;
        const el = document.createElement("textarea");
        el.value = value;
        el.setAttribute("readonly", "");
        el.style.position = "fixed";
        el.style.opacity = "0";
        document.body.appendChild(el);
        el.select();
        const ok = document.execCommand("copy");
        document.body.removeChild(el);
        return !!ok;
    } catch {
        return false;
    }
}

/* What to say about a turn's audit record, if anything.
 *
 * Three states, and the first one is the important one: an answer whose audit
 * record is safely written says NOTHING. That is the overwhelmingly common
 * case, and a badge on every answer confirming that the system worked is
 * noise — it trains people to stop reading the badge, which is exactly when
 * the one that matters appears.
 *
 * Returns null when there is nothing to say, otherwise {tone, label, detail}.
 * Shared by both surfaces so a client and a lawyer cannot be told different
 * things about the same fact. */
export function auditNotice({ auditSaved, auditPending } = {}) {
    // Absent on messages stored before the audit status was recorded. Treated
    // as saved: warning about every old answer on a suspicion the data cannot
    // support is how a warning becomes background noise.
    if (auditSaved === false) {
        return {
            tone: "warn",
            label: "Not recorded in the audit trail",
            detail: "This answer was produced but its audit record could not "
                  + "be written, so it cannot be reviewed later. If this "
                  + "answer matters, save a copy.",
        };
    }
    if (auditPending === true) {
        return {
            tone: "info",
            label: "Audit record pending",
            detail: "The audit record for this answer is queued and will be "
                  + "written shortly.",
        };
    }
    return null;
}
