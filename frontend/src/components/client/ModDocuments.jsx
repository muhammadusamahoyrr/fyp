'use client';
// Paste your ModDocuments.jsx code here
import React, { useState, Fragment, useEffect, useRef } from "react";
import { useT, useHeaderActions } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import Ic from "./Ic.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput, Badge } from "@/components/shared/shared.jsx";
import { useCase } from "./CaseContext.jsx";
import RevisionHistory from "@/components/shared/RevisionHistory.jsx";
import MyDocumentsPanel from "./MyDocumentsPanel.jsx";
import { documentStatusView } from "@/lib/documentStatus.js";
import { rememberDraft } from "@/lib/documentResume.js";
import { useDocumentResume, resolveCaseId } from "@/lib/useDocumentResume.js";
import {
    extractDocumentFields, generateDocument, downloadDocumentFile,
    fetchRevisionPreview, submitDocumentForReview, listDocuments,
    searchLawyers, getCaseTimeline,
    createDocumentV2, generateRevisionV2, submitDocumentV2, getDocumentV2,
    withdrawDocumentV2, listTemplates,
    idempotencyKey, errorCode, isRetryable,
} from "@/lib/api.js";

const STitle = ({ icon, sub, children }) => {
    const t = useT();
    return (
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
            <Ic n={icon} s={18} c={t.primary} />
            <div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>{children}</div>
            {sub && <div style={{ marginLeft: "auto", fontSize: 11, color: t.textMuted }}>{sub}</div>}
        </div>
    );
};

const Lbl = ({ children }) => {
    const t = useT();
    return <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 8, fontWeight: 600, letterSpacing: "0.6px", textTransform: "uppercase" }}>{children}</div>;
};

/* ══════════════════════════════════════════════════════
   MODULE: DOCUMENT AUTOMATION — 5-Step Wizard
══════════════════════════════════════════════════════ */
const DRAFTS_DATA = [
    { name: "Special Power of Attorney", cat: "Civil" },
    { name: "Order I, Rule 10 — Intervenor App.", cat: "Civil" },
    { name: "Joint Venture Agreement", cat: "Corporate" },
    { name: "Condonation Application", cat: "Civil" },
    { name: "Certified Copy Application", cat: "Civil" },
    { name: "Articles of Association — SMC", cat: "Corporate" },
    { name: "Employment Termination Letter", cat: "Employment" },
    { name: "Non-Disclosure Agreement", cat: "Corporate" },
    { name: "Bail Application", cat: "Criminal" },
    { name: "Suit for Recovery of Money", cat: "Civil" },
    { name: "Property Transfer Deed", cat: "Property" },
    { name: "Labour Court Complaint", cat: "Employment" },
];


const GEN_STEPS_LABELS = ["Extracting case data…", "Applying AI recommendations…", "Populating template…", "Formatting document…", "Generating draft…"];



/* Catalogue entries grouped for the picker, categories in a stable order.
 *
 * Ordered by the server's category name rather than by a list held here: a
 * category this file did not anticipate would otherwise vanish from the picker,
 * which is the same class of bug as the hardcoded template lists this replaced.
 */
function _byCategory(items) {
    const groups = new Map();
    for (const spec of items) {
        if (!groups.has(spec.category)) groups.set(spec.category, []);
        groups.get(spec.category).push(spec);
    }
    return [...groups.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([category, specs]) => [
            category,
            specs.sort((a, b) => a.label.localeCompare(b.label)),
        ]);
}

const ModDocuments = () => {
    const t = useT();
    const toast = useToast();
    const { cases } = useCase();

    /* ── State ── */
    const [step, setStep] = useState(0);                       // 0–4
    const [selectedDraft, setSelectedDraft] = useState(null);
    const [selectedCaseId, setSelectedCaseId] = useState("");
    const [docId, setDocId] = useState(null);
    // Object URL of the REAL generated PDF, rendered inline. Replaces the
    // hardcoded plaint this screen used to show — the bytes here are the exact
    // bytes of the downloaded document.
    // Which revision the preview pane is showing. Null means "the current one".
    //
    // DELIBERATELY NOT docRevisionId. That pair is what gets SUBMITTED - it is
    // the version and hash the server checks the submission against. Looking at
    // an old revision must not change what a later Submit sends, or a client who
    // glanced at v1 before submitting would submit v1's hash against v3's
    // document and be told, correctly but incomprehensibly, that it changed.
    const [viewRev, setViewRev] = useState(null);
    const [previewUrl, setPreviewUrl] = useState(null);
    // Why the preview is missing, when it is. Distinct from `previewUrl` being
    // null, which is also the state before anything has been generated — an
    // empty frame with no explanation reads as a broken page.
    const [previewIssue, setPreviewIssue] = useState(null);
    // The exact revision on screen, and the hash we read for it. Null on the
    // legacy path, where "the current file" is all the backend can offer; set
    // once a V2 generate returns, which is what makes the preview refuse to
    // silently serve different bytes.
    const [docRevisionId, setDocRevisionId] = useState(null);
    const [docPdfSha256, setDocPdfSha256] = useState(null);
    // The version the user is looking at. Sent back on submit, where the
    // server matches it against the document's own — so a draft that moved
    // in another tab is refused rather than submitted blind.
    const [docVersion, setDocVersion] = useState(null);

    // ONE KEY PER LOGICAL ACTION, held across retries of THAT action.
    //
    // A key minted per HTTP call makes the whole idempotency mechanism
    // unreachable: a retry after a lost response looks like a new intent, and
    // the server obliges by rendering a second revision or recording a second
    // submission. Held in refs rather than state because they must not be lost
    // to a re-render between the failure and the retry.
    //
    // Cleared when the intent genuinely changes — pressing Generate again after
    // changing answers IS a new intent and must produce a NEW revision, which
    // is exactly what a fresh key expresses.
    const generateKeyRef = useRef(null);
    const submitKeyRef = useRef(null);
    // Withdrawal is its own logical action, so it gets its own key. Reusing the
    // submit key would make the server treat a withdrawal as a replay of the
    // submission it is undoing — the two are opposites, not the same intent.
    const withdrawKeyRef = useRef(null);

    // A V2 failure the user must see and act on, rather than a toast that
    // vanishes. Null on the happy path.
    const [docIssue, setDocIssue] = useState(null);
    const [selectedCat, setSelectedCat] = useState("All");
    const [searchQ, setSearchQ] = useState("");
    const [selectedType, setSelectedType] = useState(null);   // chosen doc type
    // What the server can actually render, fetched rather than hardcoded.
    //
    // This screen used to hold its own opinion of what exists, in two hardcoded
    // lists, and they disagreed with the backend: they offered a "Settlement
    // Draft" nothing could build and a "Contract" wired to the NDA builder.
    // The server owns this fact now, and owns it because the catalogue is
    // derived from the builder map itself rather than written alongside it.
    const [templates, setTemplates] = useState(null);   // null = still loading
    const [templateIssue, setTemplateIssue] = useState(null);
    const [docTitle, setDocTitle] = useState("");
    const [caseRef, setCaseRef] = useState("");
    const [jurisdiction, setJurisdiction] = useState("Lahore High Court");
    const [language, setLanguage] = useState("English");
    const [instructions, setInstructions] = useState("");
    const [generating, setGenerating] = useState(false);
    const [genPct, setGenPct] = useState(0);
    const [genDone, setGenDone] = useState(false);
    // Statutory completeness of the generated draft, returned by the API.
    const [compliance, setCompliance] = useState(null);
    // Existence-check of every authority the draft cites, frozen at generation.
    const [verification, setVerification] = useState(null);
    // Which submitted keys the builder could not read. Not a compliance verdict
    // and never shown as one: it is the shape check, and its one unambiguous
    // finding is that a key went nowhere.
    const [fieldShape, setFieldShape] = useState(null);
    // Step 3 — review / edit
    const [userApproved, setUserApproved] = useState(false);
    // Step 4 — lawyer submission (real pipeline: submit → lawyer reviews → notified)
    const [selLawyer, setSelLawyer] = useState(null);         // _id of the chosen lawyer
    const [revLawyers, setRevLawyers] = useState([]);         // verified lawyers from the API
    const [caseLawyerId, setCaseLawyerId] = useState(null);   // assigned lawyer of the linked case, if any
    const [genCaseId, setGenCaseId] = useState(null);         // case the document was generated for
    const [reviewNote, setReviewNote] = useState("");
    const [urgency, setUrgency] = useState("Normal");
    const [withdrawing, setWithdrawing] = useState(false);
    const [reviewSent, setReviewSent] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [reviewStatus, setReviewStatus] = useState(null);   // submitted | approved | returned | rejected | needs_reapproval | migration_unrecoverable
    // The API's own account of a status the migration could not fully carry
    // over: headline, explanation and the way out. Kept as given — the wording
    // is the migration policy's, not this component's to paraphrase.
    const [reviewRecovery, setReviewRecovery] = useState(null);
    const [lawyerNote, setLawyerNote] = useState("");         // lawyer's note from the review
    const [revLawyerName, setRevLawyerName] = useState("");   // display name of the reviewing lawyer
    // Step 5 — final
    const [exported, setExported] = useState(false);

    /* ── Data ── */
    const STEPS = [
        { label: "Select Template", icon: "📋" },
        { label: "AI Generate Draft", icon: "✨" },
        { label: "Review", icon: "🔍" },
        { label: "Submit to Lawyer", icon: "⚖️" },
        { label: "Final & Export", icon: "📤" },
    ];
    const categories = ["All", "Civil", "Criminal", "Corporate", "Employment", "Property"];
    const catIcons = { All: "📋", Civil: "⚖️", Criminal: "🔒", Corporate: "🏢", Employment: "💼", Property: "🏠" };
    const statusColors = { Draft: "gray", "Under Review": "warn", Approved: "success", Returned: "warn", Rejected: "danger", Final: "info" };
    // The shared view, not a ternary chain. The chain's default arm displayed
    // every status nobody had enumerated as "Under Review" — which is how both
    // migration recovery states came to be shown as work in progress.
    const statusView = documentStatusView({ review_status: reviewStatus, recovery: reviewRecovery });
    const docStatus = genDone
        ? (reviewSent
            ? statusView.label
            : userApproved ? "Approved" : "Draft")
        : "Draft";
    const GEN_STEPS = ["Extracting case data…", "Applying AI recommendations…", "Populating template…", "Formatting document…", "Finalising draft…"];

    // The PDF for inline preview — of an EXACT revision where one is known.
    //
    // Two things were wrong here.
    //
    // REVISION SAFETY. This fetched "the current file". A regeneration between
    // reading the document and fetching its bytes returned different bytes than
    // the ones whose hash and verification verdict were on screen, and nothing
    // said so. Passing the revision id and the hash we read makes that a 409 we
    // can act on instead of a silent swap.
    //
    // THE LEAK. The old cleanup revoked `url`, a local set inside `.then`. When
    // the component unmounted while the fetch was in flight, `revoked` was set,
    // `.then` returned early, and `url` stayed null — while the object URL had
    // ALREADY been created inside the fetch helper. Cleanup revoked nothing and
    // the blob stayed alive for the life of the page. A URL that arrives after
    // unmount is now revoked on arrival, because by then no cleanup function
    // holds a reference to it.
    useEffect(() => {
        let live = true;
        let url = null;
        if (!docId) { setPreviewUrl(null); setPreviewIssue(null); return; }

        fetchRevisionPreview(docId, {
            revisionId: viewRev?.revision_id || docRevisionId,
            expectedPdfSha256: viewRev?.pdf_sha256 || docPdfSha256,
        }).then((res) => {
            if (!live) {
                // Arrived too late to be shown. Revoke it HERE — the cleanup
                // below has already run and cannot see this.
                if (res?.data?.url) URL.revokeObjectURL(res.data.url);
                return;
            }
            if (res?.data?.url) {
                url = res.data.url;
                setPreviewUrl(res.data.url);
                setPreviewIssue(null);
            } else {
                setPreviewUrl(null);
                // `revision_changed` is not a failure the user caused; it means
                // the document moved under them, and the honest response is to
                // say so and offer a reload rather than show a stale page.
                setPreviewIssue(res?.code === "revision_changed"
                    ? "This document was regenerated. Reload to see the current version."
                    : (res?.error?.message || null));
            }
        });

        return () => {
            live = false;
            if (url) URL.revokeObjectURL(url);
        };
    }, [docId, docRevisionId, docPdfSha256, viewRev]);

    useEffect(() => {
        if (step !== 3 || revLawyers.length) return;
        searchLawyers({ page_size: 50 }).then(({ data }) => {
            const items = Array.isArray(data) ? data : (data?.items || []);
            setRevLawyers(items.map(l => ({
                _id: l._id,
                name: l.full_name || "Lawyer",
                spec: ((l.lawyer_profile?.specializations || [])[0] || "General Practice").replace(/_/g, " "),
                rating: l.lawyer_profile?.rating || 0,
                avail: !!l.lawyer_profile?.availability,
                avatar: (l.full_name || "L").split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase(),
            })));
        }).catch(() => { });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [step]);

    // The catalogue. Read once — it changes when the server deploys, not while
    // somebody is filling in a form.
    useEffect(() => {
        let live = true;
        listTemplates().then(({ data, error }) => {
            if (!live) return;
            if (error) {
                // No silent fallback to a hardcoded list. A stale list is how
                // this screen came to offer documents nothing could render; an
                // empty picker that says why is recoverable, a wrong one that
                // looks right is not.
                setTemplates([]);
                setTemplateIssue(error.message
                    || "Could not load the list of documents. Reload to try again.");
                return;
            }
            setTemplates(Array.isArray(data) ? data : []);
            setTemplateIssue(null);
        });
        return () => { live = false; };
    }, []);

    // If the linked case already has a lawyer, the document goes to them
    useEffect(() => {
        const c = cases.find(x => (x._id || x.id) === genCaseId);
        setCaseLawyerId(c?.lawyer_id || null);
        if (c?.lawyer_id) setSelLawyer(c.lawyer_id);
    }, [genCaseId, cases]);

    // RESUME AFTER A REFRESH.
    //
    // `docId` lives in React state, so a reload used to drop it and return the
    // user to an empty Step 1 — with the document still on the server, and no
    // way to say which one it was. Regenerating is not a neutral fallback: it is
    // a second render, a second version, and for a document already sent, a
    // second thing in a lawyer's queue nobody can tell from the first.
    // THE CASE MUST BE RESOLVED FROM WHAT LOADED, not from generation state.
    //
    // This used to key off `genCaseId`, which is only ever set BY a generation
    // and starts null. After a refresh there is no generation, so it stayed
    // null, the effect returned early every time, and nothing was ever
    // restored — the feature existed and never ran once.
    const resumeCaseId = genCaseId || resolveCaseId(selectedCaseId, cases);

    useDocumentResume({
        caseId: resumeCaseId,
        hasDocument: Boolean(docId),
        getDocument: getDocumentV2,
        onRestore: (restored, forCase) => {
            if (!restored) return;
            setGenCaseId(forCase);
            setDocId(restored.docId);
            if (restored.docTitle) setDocTitle(restored.docTitle);
            setDocRevisionId(restored.docRevisionId);
            setDocPdfSha256(restored.docPdfSha256);
            setGenDone(restored.genDone);
            setReviewSent(restored.reviewSent);
            setReviewStatus(restored.reviewStatus);
            setReviewRecovery(restored.reviewRecovery);
            setStep(restored.step);
        },
    });

    // Poll the real review status while waiting for the lawyer
    useEffect(() => {
        if (!reviewSent || !docId || !genCaseId) return;
        if (reviewStatus && reviewStatus !== "submitted") return; // terminal state reached
        const refresh = async () => {
            const { data } = await listDocuments(genCaseId);
            const d = (Array.isArray(data) ? data : []).find(x => x._id === docId);
            if (d?.review_status) {
                setReviewStatus(d.review_status);
                setReviewRecovery(d.recovery || null);
                setLawyerNote(d.lawyer_note || "");
            }
        };
        refresh();
        const iv = setInterval(refresh, 12000);
        return () => clearInterval(iv);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [reviewSent, docId, genCaseId, reviewStatus]);

    const submitToLawyer = async (retryKey = null) => {
        if (!docId) { toast.show("⚠️ Generate the document first (Step 2)", "warn"); return; }
        if (!selLawyer) { toast.show("⚠️ Select a lawyer first", "warn"); return; }
        setSubmitting(true);
        setDocIssue(null);

        // The same rule as generation: one key per intent, reused by a retry.
        submitKeyRef.current = retryKey || submitKeyRef.current || idempotencyKey();

        // V2 only when this document HAS a revision and a hash — i.e. it was
        // generated through V2. Submitting without them is what the server
        // refuses, and refusing here would strand every legacy draft.
        const viaV2 = docRevisionId && docPdfSha256 && docVersion != null;
        const { data, error, status } = viaV2
            ? await submitDocumentV2(docId, {
                expectedVersion: docVersion,
                expectedPdfSha256: docPdfSha256,
                lawyerId: selLawyer,
                urgency: urgency.toLowerCase(),
                note: reviewNote.trim() || null,
            }, submitKeyRef.current)
            : await submitDocumentForReview(docId, {
                lawyer_id: selLawyer,
                note: reviewNote.trim() || null,
                urgency: urgency.toLowerCase(),
            });
        setSubmitting(false);
        if (error) {
            // The document moved under the user — almost always their own
            // regeneration in another tab. Shown as a blocking issue, not a
            // toast, and NOT reported as submitted: a client who believes a
            // lawyer has their document when nobody does will wait for a reply
            // that is never coming.
            if (status === 409) {
                setDocIssue({
                    message: "This document changed after you opened it. "
                        + "Regenerate or reload before submitting.",
                    code: errorCode(error), retryable: false,
                });
                return;
            }
            const issue = _v2Issue({ error, status });
            if (issue.retryable) { setDocIssue(issue); return; }
            toast.show("❌ " + issue.message, "danger", 4000);
            return;
        }
        setReviewStatus("submitted");
        setLawyerNote("");
        setRevLawyerName(data?.lawyer_name || revLawyers.find(l => l._id === selLawyer)?.name || "your lawyer");
        setReviewSent(true);
        toast.show(`📤 Submitted — ${data?.lawyer_name || "the lawyer"} has been notified`, "success", 3500);
    };

    /* Take the document back off the lawyer's desk.
     *
     * ONLY WHILE IT IS STILL UNDER REVIEW. The server enforces that — a
     * decided document cannot be un-decided — but the button is hidden once a
     * verdict lands too, because offering an action that will certainly be
     * refused reads as a broken screen rather than a rule.
     *
     * A 409 here means the lawyer decided WHILE the click was in flight. That
     * is not an error to apologise for: the poll below will bring the verdict
     * in a moment, so the message says what happened rather than asking the
     * user to try again at something that can no longer succeed.
     */
    const withdrawFromReview = async (retryKey = null) => {
        if (!docId || reviewStatus !== "submitted") return;
        setWithdrawing(true);
        setDocIssue(null);
        withdrawKeyRef.current = retryKey || withdrawKeyRef.current || idempotencyKey();

        const { error, status } = await withdrawDocumentV2(docId, withdrawKeyRef.current);
        setWithdrawing(false);

        if (error) {
            if (status === 404 && errorCode(error) === "feature_disabled") {
                // Legacy documents have no withdraw path at all. Say so plainly
                // instead of implying the click failed.
                toast.show("⚠️ This document was submitted the old way and "
                    + "cannot be withdrawn — ask your lawyer to return it.", "warn", 5000);
                return;
            }
            if (status === 409) {
                toast.show("⚖️ Your lawyer has already responded — "
                    + "this document can no longer be withdrawn.", "warn", 4500);
                return;
            }
            const issue = _v2Issue({ error, status });
            if (issue.retryable) { setDocIssue({ ...issue, onRetry: "withdraw" }); return; }
            toast.show("❌ " + issue.message, "danger", 4000);
            return;
        }

        // Back to a draft the client owns. The submit key is cleared with it:
        // re-submitting after a withdrawal is a NEW intent, and reusing the old
        // key would have the server replay the withdrawn submission instead.
        withdrawKeyRef.current = null;
        submitKeyRef.current = null;
        setReviewSent(false);
        setReviewStatus(null);
        setLawyerNote("");
        toast.show("↩️ Withdrawn — the document is yours again", "success", 3500);
    };

    const filteredDrafts = DRAFTS_DATA.filter(d =>
        (selectedCat === "All" || d.cat === selectedCat) &&
        d.name.toLowerCase().includes(searchQ.toLowerCase())
    );

    /* ── Helpers ── */
    const catBadgeColor = c => c === "Civil" ? "success" : c === "Criminal" ? "danger" : c === "Employment" ? "warn" : "gray";
    const pillStyle = active => ({
        padding: "7px 15px", borderRadius: 50, fontSize: 12, fontWeight: active ? 700 : 500, cursor: "pointer",
        border: `1.5px solid ${active ? t.primary : t.border}`, background: active ? t.primaryGlow : "transparent",
        color: active ? t.primary : t.textMuted, transition: "all 0.2s", fontFamily: "'Inter',sans-serif",
    });
    const tbBtn = { padding: "5px 10px", borderRadius: 8, border: `1px solid ${t.border}`, background: t.card, color: t.textMuted, fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "'Inter',sans-serif" };

    const goTo = n => setStep(n);
    const nextStep = () => {
        if (step === 0 && selectedDraft === null) {
            toast.show("⚠️ Select a template first", "warn"); return;
        }
        // The final step is only reachable once the lawyer has actually approved
        if (step === 3 && reviewStatus !== "approved") {
            toast.show("⚠️ The final version unlocks after your lawyer approves the document", "warn", 3500); return;
        }
        if (step < STEPS.length - 1) setStep(s => s + 1);
    };
    const prevStep = () => { if (step > 0) setStep(s => s - 1); };

    const pickDraft = i => {
        setSelectedDraft(i);
        if (selectedType) setDocTitle(DRAFTS_DATA[i].name + " — " + selectedType.label);
    };
    // `spec` is the catalogue entry, not a label. handleGenerate needs the
    // template_type the server keys builders by, and deriving it from a display
    // name is exactly the mapping step that used to send "Contract" to the NDA
    // builder.
    const pickType = spec => {
        setSelectedType(spec);
        if (selectedDraft !== null) {
            setDocTitle(DRAFTS_DATA[selectedDraft].name + " — " + spec.label);
        }
    };

    // The one fact the whole draft step depends on: is there a case to draft
    // from? handleGenerate resolves the id exactly this way, so the readiness
    // strip and the button can never disagree with what the handler will do.
    const activeCaseId = selectedCaseId || (cases[0]?._id || cases[0]?.id) || "";
    const activeCase = cases.find(c => (c._id || c.id) === activeCaseId);
    const activeCaseTitle = activeCase?.title || activeCase?.case_type || "your case";
    // Nothing in the catalogue is unsupported: it is built FROM the builder
    // map, so an entry cannot exist without something able to render it. The
    // flag stays as a named constant rather than being deleted, because the
    // readiness strip and the button both branch on it and a bare `false` at
    // two call sites is harder to reason about than one explained name.
    const unsupportedType = false;
    // A document type MUST be chosen. Without this, an unset type used to fall
    // through to a civil plaint (see backendType below), silently handing the
    // user a real, filable plaint they never asked for.
    const canGenerate = Boolean(activeCaseId) && Boolean(selectedType) && !unsupportedType;

    const handleGenerate = async (retryKey = null) => {
        const templateKey = selectedType?.template_type;
        if (!selectedType) {
            toast.show("⚠️ Choose a document type first", "warn"); return;
        }
        if (templateKey === null) {
            toast.show("⚠️ This document type is not yet supported by the AI", "warn"); return;
        }
        const caseId = selectedCaseId || (cases[0]?._id || cases[0]?.id);
        if (!caseId) {
            toast.show("⚠️ No case found — complete your legal intake first", "warn"); return;
        }
        // No fallback: an unmapped type is refused above, never coerced to a plaint.
        const backendType = templateKey;
        setGenerating(true); setGenPct(10); setGenDone(false); setDocId(null);
        // Clear the revision being previewed BEFORE rendering a new one.
        //
        // Without this the preview keeps asking for the old revision id while a
        // new one is generated, and the moment the document id changes it would
        // pair a new document with an old revision — a request that either
        // 404s or, worse, renders bytes from the wrong draft under the new
        // document's heading. A regeneration produces a NEW revision; nothing
        // about the previous one survives it on screen.
        setDocRevisionId(null); setDocPdfSha256(null); setDocVersion(null);
        setGenCaseId(caseId);
        // A regenerated document restarts the review pipeline
        setReviewSent(false); setReviewStatus(null); setLawyerNote(""); setUserApproved(false);
        // A NEW intent unless this is a retry of the one that just failed.
        // `retryKey` is passed only by the retry button, which reuses the key so
        // a render that already happened is replayed rather than repeated.
        generateKeyRef.current = retryKey || idempotencyKey();
        setViewRev(null);   // a new draft is what the pane should show
        setDocIssue(null);

        try {
            // Phase 1 — AI field extraction. Unchanged, and deliberately
            // outside the idempotent unit: it is a read, it produces no
            // revision, and re-running it costs nothing anyone is billed for.
            const extractRes = await extractDocumentFields(caseId, backendType);
            setGenPct(45);
            if (extractRes.error) {
                toast.show("❌ " + (extractRes.error?.detail || "Field extraction failed"), "danger");
                setGenerating(false); return;
            }
            const fields = extractRes.data?.fields || {};

            // Phase 2 — the revision itself.
            const viaV2 = await _generateViaV2({
                caseId, backendType, fields, key: generateKeyRef.current,
            });
            if (viaV2.unavailable) {
                // The flag is off. Legacy still renders a document; it simply
                // carries no revision id or hash, so the preview falls back to
                // "the current file" and the lawyer-side staleness guard has
                // nothing to check. That is the pre-V2 behaviour, unchanged.
                const genRes = await generateDocument(caseId, backendType, fields);
                setGenPct(90);
                if (genRes.error) {
                    toast.show("❌ " + (genRes.error?.detail || "PDF generation failed"), "danger");
                    setGenerating(false); return;
                }
                const legacyId = genRes.data?._id || genRes.data?.doc_id;
                setDocId(legacyId);
                rememberDraft(caseId, legacyId);
                setDocRevisionId(null);
                setDocPdfSha256(null);
                if (genRes.data?.title) setDocTitle(genRes.data.title);
                setCompliance(genRes.data?.compliance || null);
                setVerification(genRes.data?.verification || null);
                setFieldShape(null);   // the legacy path produces no shape report
            } else if (viaV2.error) {
                setGenerating(false);
                setDocIssue(viaV2.issue);
                // NOT reported as generated. A draft the user believes exists
                // and then submits is worse than a visible failure.
                return;
            } else {
                setDocId(viaV2.documentId);
            // Remembered as soon as it exists, so a refresh at any point after
            // this returns to THIS document rather than to an empty form.
            // `caseId`, not `genCaseId`. `setGenCaseId(caseId)` above does not
            // update the state this closure reads, so using the state here saved
            // the draft under the PREVIOUS case — or under null on the first
            // generation, where nothing would ever find it again.
            rememberDraft(caseId, viaV2.documentId);
                // These two are what make the preview revision-safe: the effect
                // that loads the PDF asks for exactly this revision and refuses
                // bytes whose hash differs.
                setDocRevisionId(viaV2.revisionId);
                setDocPdfSha256(viaV2.pdfSha256);
                setDocVersion(viaV2.version);
                setCompliance(viaV2.compliance || null);
                setVerification(viaV2.verification || null);
                setFieldShape(viaV2.fieldShape || null);
            }

            setGenPct(100);
            // A new revision invalidates any submission intent formed against
            // the previous one — otherwise a retry of the old submit would send
            // a version the user is no longer looking at.
            submitKeyRef.current = null;
            setTimeout(() => { setGenerating(false); setGenDone(true); toast.show("✅ Draft generated!", "success"); }, 300);
        } catch {
            toast.show("❌ Generation failed — check backend connection", "danger");
            setGenerating(false);
        }
    };

    /* One revision through V2, or a signal that V2 is not available.
     *
     * Returns {unavailable} when the feature flag is off — that 404 is the
     * flag saying "not here", not a failure worth showing anyone. Otherwise
     * {revisionId, pdfSha256, version} or {error, issue}.
     *
     * The document identity and the revision are two calls sharing ONE key.
     * That is safe because they are keyed independently on the server —
     * `create` by (client, key) and `generate` by (document, key) — so a retry
     * of the pair returns the same document AND the same revision rather than
     * a second of either.
     */
    const _generateViaV2 = async ({ caseId, backendType, fields, key }) => {
        const created = await createDocumentV2({
            templateType: backendType,
            title: docTitle || `${selectedType?.label || "Document"} draft`,
            caseId,
        }, key);
        if (created.error) {
            if (created.status === 404 && errorCode(created.error) === "feature_disabled") {
                return { unavailable: true };
            }
            return { error: true, issue: _v2Issue(created) };
        }

        const documentId = created.data.id;
        const rev = await generateRevisionV2(
            documentId, { fields, templateType: backendType }, key);
        if (rev.error) return { error: true, issue: _v2Issue(rev) };

        return {
            documentId,
            revisionId: rev.data.revision_id,
            pdfSha256: rev.data.pdf_sha256,
            version: rev.data.version,
            compliance: rev.data.compliance,
            verification: rev.data.verification,
            fieldShape: rev.data.field_shape,
        };
    };

    /* What to tell the user about a V2 failure, and whether to offer a retry.
     *
     * 503 is the one where the outcome is genuinely unknown — the work may or
     * may not have happened, which is precisely what the key is for, so the
     * retry reuses it. A 409 or 422 is a decision the server made; repeating
     * the identical request cannot change it. */
    const _v2Issue = ({ error, status }) => ({
        message: error?.message || "The request could not be completed.",
        code: errorCode(error),
        retryable: isRetryable(status, error),
    });

    /* ── Header actions ── */
    const { setHeaderActions } = useHeaderActions();
    useEffect(() => {
        setHeaderActions(
            <>
                {step > 0 && <BtnOutline onClick={prevStep} style={{ fontSize: 11, padding: "7px 14px" }}>← Back</BtnOutline>}
                {step > 0 && step < 4 && <BtnPrimary onClick={nextStep} style={{ fontSize: 11, padding: "7px 18px" }}>Continue →</BtnPrimary>}
            </>
        );
        return () => setHeaderActions(null);
    }, [step, setHeaderActions]);

    /* ── Stepper ── */
    const Stepper = () => (
        <div style={{ display: "flex", alignItems: "center", paddingBottom: 22, flexShrink: 0 }}>
            {STEPS.map((s, i) => {
                const done = i < step, active = i === step;
                return (
                    <Fragment key={s.label}>
                        <div onClick={() => i < step && goTo(i)} style={{ display: "flex", alignItems: "center", gap: 7, cursor: i < step ? "pointer" : "default", padding: "4px 8px", borderRadius: 50 }}>
                            <div style={{
                                width: 28, height: 28, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
                                fontSize: done ? 11 : 12, fontWeight: 800, flexShrink: 0, transition: "all 0.25s",
                                background: done ? t.primary : active ? t.primaryGlow : "transparent",
                                color: done ? (t.mode === "dark" ? "#1A2E35" : "#fff") : active ? t.primary : t.textMuted,
                                border: `2px solid ${done ? t.primary : active ? t.primary : t.border}`,
                                boxShadow: active ? `0 0 0 4px ${t.primaryGlow}` : "none",
                            }}>{done ? "✓" : s.icon}</div>
                            <span style={{ fontSize: 12.5, fontWeight: active ? 700 : 500, color: done ? t.primary : active ? t.text : t.textMuted, whiteSpace: "nowrap" }}>{s.label}</span>
                        </div>
                        {i < STEPS.length - 1 && <div style={{ flex: 1, height: 2, background: done ? t.primary : t.border, margin: "0 4px", minWidth: 12, transition: "background 0.4s" }} />}
                    </Fragment>
                );
            })}
        </div>
    );

    /* ── Workflow sidebar — always visible from step 1+ ── */
    const FLOW = [
        { label: "Template Selection", active: step === 0, done: step > 0 },
        { label: "AI Generate Draft", active: step === 1 && !genDone, done: genDone },
        { label: "Draft Status: Created", active: step === 1 && genDone && !userApproved, done: userApproved },
        { label: "User Review", active: step === 2 && !userApproved, done: step > 2 || userApproved },
        { label: "Submit to Lawyer", active: step === 3 && !reviewSent, done: reviewSent },
        { label: "Lawyer Review", active: reviewSent && reviewStatus === "submitted", done: reviewSent && reviewStatus !== "submitted" && reviewStatus !== null },
        { label: "Lawyer Decision", active: false, done: ["approved", "returned", "rejected"].includes(reviewStatus) },
        { label: "Final Version", active: reviewStatus === "approved" && !exported, done: exported },
        { label: "Export", active: exported, done: exported },
    ];

    return (
        <div style={{ display: "flex", flexDirection: "column" }}>
            <Stepper />

            <div style={{ flex: 1, overflow: "auto", paddingBottom: 8 }} className="aFadeUp" key={step}>

                {/* ════════════════════════════════════════════════
            STEP 1 — Template Selection (full width)
        ════════════════════════════════════════════════ */}
                {step === 0 && (
                    <div>
                        {/* EVERY DOCUMENT THIS CLIENT OWNS, on the dashboard.
                            It was first placed inside the step-3 review pane,
                            which is only reachable part-way through creating a
                            NEW document — so the history of old ones was behind
                            the flow you would use precisely because you could
                            not find them. A mounted test caught it; nothing
                            about the source looked wrong. */}
                        <div style={{ marginBottom: 14 }}>
                            <MyDocumentsPanel
                                t={t}
                                onOpen={restored => {
                                    setDocId(restored.docId);
                                    if (restored.docTitle) setDocTitle(restored.docTitle);
                                    setDocRevisionId(restored.docRevisionId);
                                    setDocPdfSha256(restored.docPdfSha256);
                                    setGenDone(restored.genDone);
                                    setReviewSent(restored.reviewSent);
                                    setReviewStatus(restored.reviewStatus);
                                    setReviewRecovery(restored.reviewRecovery);
                                    setViewRev(null);
                                    setStep(restored.step);
                                    if (resumeCaseId) rememberDraft(resumeCaseId, restored.docId);
                                }}
                                onPreview={(id, actions) => setViewRev({
                                    revision_id: actions.revisionId,
                                    pdf_sha256: actions.pdfSha256,
                                })} />
                        </div>

                        {/* Stats bar */}
                        <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: 10, marginBottom: 14 }}>
                            {[["Templates", String(DRAFTS_DATA.length), "📄", t.primary], ["Categories", String(new Set(DRAFTS_DATA.map(d => d.cat)).size), "📁", t.success]].map(([label, val, ico, col]) => (
                                <div key={label} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 18px", borderRadius: 14, background: t.card, border: `1px solid ${t.border}` }}>
                                    <div>
                                        <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>{label}</div>
                                        <div style={{ fontSize: 22, fontWeight: 800, color: t.text, fontFamily: "'Playfair Display',serif" }}>{val}</div>
                                    </div>
                                    <div style={{ width: 40, height: 40, borderRadius: 12, background: `${col}18`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20 }}>{ico}</div>
                                </div>
                            ))}
                        </div>

                        {/* Filters + search row */}
                        <div style={{ display: "flex", gap: 7, marginBottom: 14, alignItems: "center", flexWrap: "wrap" }}>
                            {categories.map(c => (
                                <button key={c} onClick={() => setSelectedCat(c)} style={pillStyle(selectedCat === c)}>{catIcons[c]} {c}</button>
                            ))}
                            <div style={{ flex: 1, minWidth: 200, display: "flex", alignItems: "center", gap: 9, padding: "8px 14px", borderRadius: 12, border: `1.5px solid ${t.border}`, background: t.card }}>
                                <Ic n="search" s={14} c={t.textMuted} />
                                <input value={searchQ} onChange={e => setSearchQ(e.target.value)} placeholder="Search legal drafts…" style={{ flex: 1, background: "transparent", border: "none", outline: "none", fontFamily: "'Inter',sans-serif", fontSize: 12.5, color: t.text }} />
                            </div>
                        </div>

                        {/* Template grid — 3 columns, full width */}
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 14 }}>
                            {filteredDrafts.length ? filteredDrafts.map(d => {
                                const gi = DRAFTS_DATA.indexOf(d);
                                const sel = selectedDraft === gi;
                                return (
                                    <div key={gi} onClick={() => pickDraft(gi)} style={{ background: sel ? t.primaryGlow : t.card, border: `2px solid ${sel ? t.primary : t.border}`, borderRadius: 18, padding: 18, cursor: "pointer", transition: "all 0.2s", position: "relative", display: "flex", flexDirection: "column", minHeight: 200, boxShadow: sel ? `0 0 0 1px ${t.primary}, ${t.shadowCard}` : t.shadowCard }}
                                        onMouseEnter={e => { if (!sel) { e.currentTarget.style.borderColor = t.primary + "60"; e.currentTarget.style.background = t.primaryGlow + "50"; } }}
                                        onMouseLeave={e => { if (!sel) { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.background = t.card; } }}
                                    >
                                        {/* Selected badge */}
                                        {sel && <div style={{ position: "absolute", top: 12, left: 12, width: 22, height: 22, borderRadius: "50%", background: t.primary, color: t.mode === "dark" ? "#1A2E35" : "#fff", fontSize: 10, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: `0 2px 8px ${t.primaryGlow}` }}>✓</div>}
                                        {/* PDF badge */}
                                        <div style={{ position: "absolute", top: 12, right: 12 }}><Badge type="gray">PDF</Badge></div>
                                        {/* Icon */}
                                        <div style={{ width: 46, height: 46, borderRadius: 12, background: sel ? `${t.primary}25` : `${t.danger}12`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, marginBottom: 10, marginTop: 4 }}>{sel ? "📗" : "📕"}</div>
                                        {/* Category */}
                                        <Badge type={catBadgeColor(d.cat)} style={{ marginBottom: 7, alignSelf: "flex-start", fontSize: 10 }}>{d.cat}</Badge>
                                        {/* Name */}
                                        <div style={{ fontSize: 13, fontWeight: 700, color: sel ? t.primary : t.text, lineHeight: 1.35, marginBottom: 6, flex: 1 }}>{d.name}</div>
                                        {/* Action */}
                                        <div style={{ display: "flex", gap: 7 }}>
                                            <button onClick={e => { e.stopPropagation(); sel ? nextStep() : pickDraft(gi); }} style={{ flex: 1, padding: "7px", borderRadius: 10, border: `1.5px solid ${sel ? t.primary : t.border}`, background: sel ? t.primary : t.card, color: sel ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.textMuted, fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "'Inter',sans-serif", transition: "all 0.2s" }}>{sel ? "✓ Use Template" : "Select"}</button>
                                        </div>
                                    </div>
                                );
                            }) : <div style={{ gridColumn: "span 3", textAlign: "center", padding: 48, color: t.textMuted, fontSize: 13 }}>No templates found.</div>}
                        </div>

                        {/* Bottom CTA bar — shows when template selected */}
                        {selectedDraft !== null && (
                            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", marginTop: 16, borderRadius: 14, background: t.primaryGlow, border: `1.5px solid ${t.primary}` }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                                    <div style={{ width: 34, height: 34, borderRadius: 9, background: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>📗</div>
                                    <div>
                                        <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>{DRAFTS_DATA[selectedDraft].name}</div>
                                        <div style={{ fontSize: 10, color: t.textMuted }}>Template selected · Ready to proceed</div>
                                    </div>
                                </div>
                                <BtnPrimary onClick={nextStep} style={{ fontSize: 12, padding: "10px 22px", borderRadius: 12, boxShadow: `0 4px 16px ${t.primaryGlow}` }}>
                                    Continue to AI Generation →
                                </BtnPrimary>
                            </div>
                        )}
                    </div>
                )}

                {/* ════════════════════════════════════════════════
            STEP 2 — AI Generate Draft
        ════════════════════════════════════════════════ */}
                {step === 1 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

                        {/* Doc identity */}
                        <Card>
                            <STitle icon="sparkle" sub="Configure your document before AI drafting">Generation Settings</STitle>
                            <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
                                <div>
                                    <Lbl>Document Type</Lbl>
                                    {templates === null ? (
                                        <div style={{ fontSize: 12, color: t.textMuted, padding: "10px 0" }}>
                                            Loading the available documents…
                                        </div>
                                    ) : templateIssue ? (
                                        <div style={{ fontSize: 12, color: t.warn, padding: "10px 13px", borderRadius: 10, background: `${t.warn}12`, border: `1px solid ${t.warn}35` }}>
                                            {templateIssue}
                                        </div>
                                    ) : (
                                        <>
                                            <select
                                                value={selectedType?.template_type || ""}
                                                onChange={e => {
                                                    const spec = templates.find(
                                                        x => x.template_type === e.target.value);
                                                    if (spec) pickType(spec);
                                                }}
                                                style={{ background: t.inputBg, border: `1.5px solid ${t.border}`, color: t.text, borderRadius: 12, padding: "11px 13px", width: "100%", outline: "none", fontSize: 12.5, fontFamily: "'Inter',sans-serif" }}>
                                                <option value="">Select a document type…</option>
                                                {_byCategory(templates).map(([category, items]) => (
                                                    <optgroup key={category} label={category}>
                                                        {items.map(spec => (
                                                            <option key={spec.template_type} value={spec.template_type}>
                                                                {spec.label}
                                                            </option>
                                                        ))}
                                                    </optgroup>
                                                ))}
                                            </select>
                                            {/* The server's own description of what this
                                                builder emits. Shown because several of
                                                them are narrower than their name suggests
                                                — the Vakalatnama entry is an execution
                                                checklist and says so, and a user who picks
                                                it expecting an appointment instrument needs
                                                to read that BEFORE drafting, not after
                                                filing. */}
                                            {selectedType?.description && (
                                                <div style={{ fontSize: 11.5, color: t.textMuted, lineHeight: 1.6, marginTop: 7, padding: "9px 12px", borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}` }}>
                                                    {selectedType.description}
                                                </div>
                                            )}
                                        </>
                                    )}
                                </div>
                                <div><Lbl>Document Title</Lbl><ThemedInput value={docTitle} onChange={e => setDocTitle(e.target.value)} placeholder={`${selectedDraft !== null ? DRAFTS_DATA[selectedDraft].name : "Employment Dispute"} — ${selectedType?.label || "Plaint"}`} /></div>
                                {cases.length > 0 && (
                                    <div>
                                        <Lbl>Linked Case</Lbl>
                                        <select value={selectedCaseId} onChange={e => setSelectedCaseId(e.target.value)} style={{ background: t.inputBg, border: `1.5px solid ${t.border}`, color: t.text, borderRadius: 12, padding: "11px 13px", width: "100%", outline: "none", fontSize: 12.5, fontFamily: "'Inter',sans-serif" }}>
                                            <option value="">Select a case…</option>
                                            {cases.map(c => <option key={c._id || c.id} value={c._id || c.id}>{c.title || c.case_type || (c._id || c.id)}</option>)}
                                        </select>
                                    </div>
                                )}
                                <div><Lbl>Case Reference No.</Lbl><ThemedInput value={caseRef} onChange={e => setCaseRef(e.target.value)} placeholder="e.g. CASE-2026-00142" /></div>
                                <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                                    <div><Lbl>Jurisdiction</Lbl>
                                        <select value={jurisdiction} onChange={e => setJurisdiction(e.target.value)} style={{ background: t.inputBg, border: `1.5px solid ${t.border}`, color: t.text, borderRadius: 12, padding: "11px 13px", width: "100%", outline: "none", fontSize: 12.5 }}>
                                            <option>Lahore High Court</option><option>Islamabad High Court</option><option>Sindh High Court</option><option>Supreme Court</option>
                                        </select>
                                    </div>
                                    <div><Lbl>Language</Lbl>
                                        <select value={language} onChange={e => setLanguage(e.target.value)} style={{ background: t.inputBg, border: `1.5px solid ${t.border}`, color: t.text, borderRadius: 12, padding: "11px 13px", width: "100%", outline: "none", fontSize: 12.5 }}>
                                            <option>English</option><option>Urdu</option><option>Both</option>
                                        </select>
                                    </div>
                                </div>
                                <div><Lbl>Special Instructions</Lbl>
                                    <textarea value={instructions} onChange={e => setInstructions(e.target.value)} placeholder="e.g. Emphasise wrongful termination, cite Labour Act 1934, include salary dues…" rows={3} style={{ background: t.inputBg, border: `1.5px solid ${t.border}`, color: t.text, borderRadius: 12, padding: "11px 13px", width: "100%", outline: "none", fontSize: 12.5, resize: "vertical", fontFamily: "'Inter',sans-serif", lineHeight: 1.6, boxSizing: "border-box" }} />
                                </div>
                            </div>

                            {/* Readiness strip — reflects real state.
                                This used to be hardcoded to "Case data extracted · AI
                                recommendations ready / ✓ Ready" regardless of whether a
                                case existed. It told users everything was ready, they
                                pressed Generate, and handleGenerate bailed before making
                                any request because there was no case to generate from.
                                A panel that asserts state it never checks turns a working
                                feature into a dead button. */}
                            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 13px", borderRadius: 10, background: canGenerate ? t.primaryGlow : t.inputBg, border: `1px solid ${canGenerate ? t.primary + "30" : t.border}`, marginTop: 12 }}>
                                <div style={{ width: 8, height: 8, borderRadius: "50%", background: canGenerate ? t.success : t.warn, flexShrink: 0 }} />
                                <span style={{ fontSize: 11.5, color: t.textMuted, flex: 1 }}>
                                    {canGenerate
                                        ? `Linked to "${activeCaseTitle}" · ready to draft`
                                        : "No case linked yet — complete your Legal Intake first, then come back to draft a document."}
                                </span>
                                <Badge type={canGenerate ? "success" : "warn"}>{canGenerate ? "✓ Ready" : "Not ready"}</Badge>
                            </div>

                            {/* Progress bar */}
                            {(generating || genDone) && (
                                <div style={{ marginTop: 12 }}>
                                    <div style={{ height: 6, borderRadius: 6, background: t.inputBg, overflow: "hidden", marginBottom: 6 }}>
                                        <div style={{ height: "100%", background: t.grad1, borderRadius: 6, width: `${genPct}%`, transition: "width 0.4s ease" }} />
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: t.textMuted }}>
                                        <span>{genDone ? "✅ Draft created successfully" : GEN_STEPS[Math.min(Math.floor(genPct / 20), 4)]}</span>
                                        <span>{genPct}%</span>
                                    </div>
                                </div>
                            )}

                            {/* What the Code requires, and what this draft is missing.
                                Deterministic and cited — Order VII Rule 1 CPC lists the
                                particulars a plaint must contain, and Order VI Rule 3
                                makes the Appendix A forms mandatory. Advisory: it reports,
                                it does not block. */}
                            {/* A value that went nowhere.
                                 *
                                 * The document rendered with an empty line exactly
                                 * where the user believes they supplied something,
                                 * and until now nothing anywhere said so — the key
                                 * was dropped in silence. Shown ABOVE compliance
                                 * because it is a fact about what was submitted,
                                 * which the reader needs before reading a verdict
                                 * on what was produced from it. */}
                            {genDone && fieldShape?.unknown?.length > 0 && (
                                <div style={{ marginTop: 12, padding: "11px 14px", borderRadius: 12,
                                    background: `${t.warn}12`, border: `1.5px solid ${t.warn}45` }}>
                                    <div style={{ fontSize: 12.5, fontWeight: 700, color: t.warn, marginBottom: 4 }}>
                                        {fieldShape.unknown.length} answer{fieldShape.unknown.length === 1 ? " was" : "s were"} not used
                                    </div>
                                    <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.6 }}>
                                        This document type does not have {fieldShape.unknown.length === 1 ? "a field" : "fields"} called{" "}
                                        {fieldShape.unknown.join(", ")}. Whatever was entered there is
                                        not in the draft — check the document before submitting it.
                                    </div>
                                </div>
                            )}

                            {genDone && compliance?.checked && (
                                <div style={{ marginTop: 13, padding: 13, borderRadius: 11,
                                    background: compliance.complete ? `${t.success}12` : `${t.warn}12`,
                                    border: `1.5px solid ${compliance.complete ? t.success : t.warn}45` }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7 }}>
                                        <span style={{ fontSize: 12.5, fontWeight: 700, color: compliance.complete ? t.success : t.warn }}>
                                            {compliance.complete
                                                ? "✓ Contains every particular the Code requires"
                                                : `${compliance.missing} required particular${compliance.missing === 1 ? "" : "s"} missing`}
                                        </span>
                                    </div>
                                    <div style={{ fontSize: 10.5, color: t.textMuted, marginBottom: compliance.complete ? 0 : 9 }}>
                                        Checked against {compliance.basis}
                                    </div>
                                    {compliance.items.filter(i => i.status === "missing").map(i => (
                                        <div key={i.clause} style={{ marginBottom: 8, paddingLeft: 10, borderLeft: `2px solid ${t.warn}55` }}>
                                            <div style={{ fontSize: 11.5, color: t.text, fontWeight: 600 }}>
                                                {i.clause} — {i.requirement}
                                            </div>
                                            <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>{i.hint}</div>
                                        </div>
                                    ))}
                                    <div style={{ fontSize: 10, color: t.textMuted, marginTop: 6, fontStyle: "italic" }}>
                                        {compliance.advisory}
                                    </div>
                                </div>
                            )}

                            {/* Citation verification. Deliberately NOT a green tick:
                                this checks only that an authority EXISTS, never that
                                it supports the point it is cited for, and the corpus
                                cannot speak to every statute. So the "cannot check"
                                count is always on screen next to the verified count —
                                a panel that showed only "4 verified" would read as a
                                clean bill of health the check never gave. A run that
                                failed says so rather than showing nothing, because a
                                silent panel looks identical to a clean one. */}
                            {genDone && verification && (
                                <div style={{ marginTop: 13, padding: 13, borderRadius: 11,
                                    background: (verification.counts?.not_in_corpus > 0 || verification.counts?.omitted > 0) ? `${t.danger}12` : `${t.textMuted}0e`,
                                    border: `1.5px solid ${(verification.counts?.not_in_corpus > 0 || verification.counts?.omitted > 0) ? `${t.danger}55` : `${t.textMuted}33`}` }}>
                                    <div style={{ fontSize: 12.5, fontWeight: 700, marginBottom: 7,
                                        color: (verification.counts?.not_in_corpus > 0 || verification.counts?.omitted > 0) ? t.danger : t.text }}>
                                        {verification.ran === false
                                            ? "Citations were not checked"
                                            : verification.counts?.omitted > 0
                                                ? `${verification.counts.omitted} REPEALED section${verification.counts.omitted === 1 ? "" : "s"} cited`
                                                : verification.counts?.not_in_corpus > 0
                                                    ? `${verification.counts.not_in_corpus} citation${verification.counts.not_in_corpus === 1 ? "" : "s"} could not be found in the statute`
                                                    : "Citations checked for existence"}
                                    </div>

                                    {verification.ran === false ? (
                                        <div style={{ fontSize: 11, color: t.textMuted }}>
                                            {verification.summary}
                                        </div>
                                    ) : (
                                        <>
                                            <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 9 }}>
                                                {verification.counts?.verified || 0} found in the corpus ·{" "}
                                                {verification.counts?.omitted > 0 && (
                                                    <>{verification.counts.omitted} repealed · </>
                                                )}
                                                {verification.counts?.unverifiable || 0} this corpus cannot check
                                            </div>

                                            {(verification.checks || [])
                                                .filter(c => c.status !== "VERIFIED")
                                                .map((c, i) => (
                                                    <div key={`${c.canonical}-${i}`} style={{ marginBottom: 8, paddingLeft: 10,
                                                        borderLeft: `2px solid ${(c.status === "NOT_IN_CORPUS" || c.status === "OMITTED") ? `${t.danger}66` : `${t.textMuted}44`}` }}>
                                                        <div style={{ fontSize: 11.5, fontWeight: 600,
                                                            color: (c.status === "NOT_IN_CORPUS" || c.status === "OMITTED") ? t.danger : t.text }}>
                                                            {c.canonical}
                                                            <span style={{ fontWeight: 500, color: t.textMuted }}>
                                                                {c.status === "OMITTED" ? " — REPEALED"
                                                                    : c.status === "NOT_IN_CORPUS" ? " — not found"
                                                                        : " — cannot verify"}
                                                            </span>
                                                        </div>
                                                        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>{c.detail}</div>
                                                    </div>
                                                ))}
                                        </>
                                    )}

                                    <div style={{ fontSize: 10, color: t.textMuted, marginTop: 6, fontStyle: "italic" }}>
                                        Existence only — a real provision cited for something it does not
                                        say still shows as found. Read every authority before filing.
                                    </div>
                                    {/* The adopted scope statement, shipped from the backend so this
                                        panel and the lawyer's review panel cannot drift apart about
                                        what was promised. See backend/app/core/claims.py. */}
                                    {verification.scope && (
                                        <div style={{ fontSize: 10, color: t.textMuted, marginTop: 8,
                                            paddingTop: 8, borderTop: `1px solid ${t.textMuted}22`, lineHeight: 1.5 }}>
                                            {verification.scope}
                                        </div>
                                    )}
                                </div>
                            )}

                            {!genDone ? (
                                <BtnPrimary onClick={handleGenerate} disabled={generating || !canGenerate} style={{ width: "100%", marginTop: 13, fontSize: 13, padding: "13px", borderRadius: 12, justifyContent: "center" }}>
                                    {generating
                                        ? "⏳ Generating…"
                                        : !activeCaseId
                                            ? "Link a case to generate"
                                            : unsupportedType
                                                ? `${selectedType?.label} isn't supported yet`
                                                : "✨ Generate Draft"}
                                </BtnPrimary>
                            ) : (
                                <div style={{ display: "flex", gap: 8, marginTop: 13 }}>
                                    <BtnOutline onClick={() => { setGenDone(false); setGenPct(0); }} style={{ flex: 1, fontSize: 11, padding: "11px", borderRadius: 12 }}>🔄 Regenerate</BtnOutline>
                                    <BtnPrimary onClick={() => { goTo(2); }} style={{ flex: 2, fontSize: 12, padding: "11px", borderRadius: 12, justifyContent: "center" }}>Review Draft →</BtnPrimary>
                                </div>
                            )}
                        </Card>

                    </div>
                )}

                {/* ════════════════════════════════════════════════
            STEP 3 — User Review
        ════════════════════════════════════════════════ */}
                {step === 2 && (
                    <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 18 }}>

                        {/* Left: editable document */}
                        <Card style={{ display: "flex", flexDirection: "column", minHeight: 540 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
                                <div style={{ width: 36, height: 36, borderRadius: 10, background: t.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, flexShrink: 0 }}>📄</div>
                                <div style={{ flex: 1 }}>
                                    <div style={{ fontWeight: 700, color: t.text, fontSize: 14 }}>{docTitle || "Generated Document"}</div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>{selectedType?.label || "—"} · {caseRef || "No ref"}</div>
                                </div>
                                <Badge type={statusColors[docStatus]}>{docStatus}</Badge>
                                {/* "Change answers", not "Edit".
                                    THE DOCUMENT IS A PDF IN AN IFRAME. The old
                                    Edit toggle revealed a formatting toolbar
                                    whose buttons called document.execCommand on
                                    it — bold, italic, underline — none of which
                                    can touch a PDF, and none of which were ever
                                    saved or regenerated. A control that looks
                                    like it edits and does not is worse than no
                                    control: the user believes their changes
                                    exist and submits a document that never
                                    contained them.

                                    Changing the answers and regenerating IS the
                                    edit, and it is the only one this format
                                    supports. It also maps exactly onto how the
                                    document is versioned: a change produces a
                                    new revision, not a mutated file. */}
                                <button
                                    onClick={() => goTo(1)}
                                    title="Go back and change your answers, then regenerate"
                                    style={{
                                        padding: "6px 13px", borderRadius: 10,
                                        border: `1.5px solid ${t.border}`,
                                        background: t.card, color: t.textMuted,
                                        fontSize: 11, fontWeight: 700, cursor: "pointer",
                                    }}>
                                    ✏️ Change answers
                                </button>
                            </div>

                            {/* A V2 failure the user must act on.
                                Not a toast: a draft that failed to generate, or
                                a submission that did not land, is something the
                                user will otherwise assume succeeded — and a
                                client who believes a lawyer has their document
                                waits for a reply nobody is going to send.

                                The retry reuses the SAME key, so a request that
                                did reach the server before the connection
                                dropped is replayed rather than repeated. */}
                            {docIssue && (
                                <div style={{
                                    marginBottom: 12, padding: "10px 14px", borderRadius: 10,
                                    background: "#f59e0b14", border: "1px solid #f59e0b55",
                                    color: t.text, fontSize: 12.5,
                                    display: "flex", alignItems: "center", gap: 12,
                                }}>
                                    <span style={{ flex: 1 }}>⚠ {docIssue.message}</span>
                                    {docIssue.retryable && (
                                        <button
                                            onClick={() => {
                                                setDocIssue(null);
                                                if (docIssue.onRetry === "withdraw") withdrawFromReview(withdrawKeyRef.current);
                                                else if (docId) submitToLawyer(submitKeyRef.current);
                                                else handleGenerate(generateKeyRef.current);
                                            }}
                                            style={{
                                                background: t.primary, color: "#fff", border: "none",
                                                borderRadius: 8, padding: "6px 14px",
                                                fontSize: 12, fontWeight: 700, cursor: "pointer",
                                                whiteSpace: "nowrap",
                                            }}>
                                            Retry
                                        </button>
                                    )}
                                </div>
                            )}

                            <div style={{ flex: 1, border: `1.5px solid ${t.border}`, borderRadius: 12, overflow: "hidden", background: "#fff", minHeight: 460 }}>
                                {previewUrl ? (
                                    <iframe title="Document preview" src={previewUrl} style={{ width: "100%", height: 460, border: "none", display: "block" }} />
                                ) : (
                                    <div style={{ padding: 40, textAlign: "center", color: t.textMuted, fontSize: 13, minHeight: 460, display: "flex", alignItems: "center", justifyContent: "center" }}>
                                        {previewIssue
                                            ? previewIssue
                                            : docId ? "Loading document preview…"
                                                : "Generate the document to preview it here."}
                                    </div>
                                )}
                            </div>

                            {viewRev && (
                                <div style={{ marginTop: 10, padding: "9px 12px", borderRadius: 10, background: `${t.warn}12`, border: `1px solid ${t.warn}35`, fontSize: 11.5, color: t.text, display: "flex", alignItems: "center", gap: 10 }}>
                                    <span style={{ flex: 1 }}>
                                        Showing an earlier version (v{viewRev.version}). Submitting still sends the latest.
                                    </span>
                                    <button
                                        onClick={() => setViewRev(null)}
                                        style={{ background: "transparent", border: `1px solid ${t.border}`, borderRadius: 8, padding: "5px 11px", fontSize: 11, fontWeight: 700, color: t.text, cursor: "pointer", whiteSpace: "nowrap", fontFamily: "'Inter',sans-serif" }}>
                                        Back to latest
                                    </button>
                                </div>
                            )}

                            <RevisionHistory
                                docId={docId} t={t} reloadKey={docRevisionId}
                                currentRevisionId={viewRev?.revision_id || docRevisionId}
                                onPreview={rev => setViewRev(
                                    rev.revision_id === docRevisionId ? null : rev)} />

                            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                                <BtnOutline onClick={() => { if (docId) { downloadDocumentFile(docId, docTitle || "document", {
                                        revisionId: viewRev?.revision_id || docRevisionId,
                                        expectedPdfSha256: viewRev?.pdf_sha256 || docPdfSha256,
                                    }); } else { toast.show("⚠️ Generate the document first", "warn"); } }} style={{ flex: 1, fontSize: 11, padding: "9px", borderRadius: 10 }}>📥 Download</BtnOutline>
                            </div>
                        </Card>

                        {/* Right: review controls + workflow */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

                            {/* Compliance — REAL records computed at generation.
                                These replaced four hardcoded green ticks that
                                showed "Verified" on every document regardless of
                                content. compliance/verification are frozen on the
                                document when it was generated. */}
                            <Card>
                                <STitle icon="check" sub="Frozen at generation">Legal Compliance</STitle>
                                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 10px", borderRadius: 9, background: t.inputBg, border: `1px solid ${t.border}`, marginBottom: 6 }}>
                                    <span style={{ fontSize: 11.5, color: t.text }}>Statutory particulars</span>
                                    {compliance?.checked
                                        ? <Badge type={compliance.complete ? "success" : "warn"}>{compliance.complete ? "✓ Complete" : `${compliance.missing} missing`}</Badge>
                                        : <Badge type="gray">Not encoded</Badge>}
                                </div>
                                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 10px", borderRadius: 9, background: t.inputBg, border: `1px solid ${t.border}` }}>
                                    <span style={{ fontSize: 11.5, color: t.text }}>Citation check</span>
                                    {verification
                                        ? (verification.ran === false
                                            ? <Badge type="warn">Not checked</Badge>
                                            : (verification.counts?.not_in_corpus > 0
                                                ? <Badge type="danger">{verification.counts.not_in_corpus} not found</Badge>
                                                : <Badge type="success">✓ {verification.counts?.verified || 0} found</Badge>))
                                        : <Badge type="gray">—</Badge>}
                                </div>
                                <div style={{ fontSize: 10, color: t.textMuted, marginTop: 8, fontStyle: "italic" }}>
                                    Existence only — read every authority before filing. A lawyer must review this.
                                </div>
                            </Card>

                            {/* User review decision */}
                            <Card>
                                <STitle icon="eye" sub="Your review decision">User Review</STitle>
                                <div style={{ padding: "10px 12px", borderRadius: 10, background: userApproved ? `${t.success}12` : t.inputBg, border: `1.5px solid ${userApproved ? t.success : t.border}`, marginBottom: 10, textAlign: "center" }}>
                                    <div style={{ fontSize: 18, marginBottom: 4 }}>{userApproved ? "✅" : "👀"}</div>
                                    <div style={{ fontSize: 12, fontWeight: 600, color: userApproved ? t.success : t.text }}>{userApproved ? "Approved by you" : "Awaiting your review"}</div>
                                    <div style={{ fontSize: 10, color: t.textMuted, marginTop: 2 }}>{userApproved ? "Ready to submit to lawyer" : "Review the document and approve or edit"}</div>
                                </div>
                                {!userApproved ? (
                                    <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                                        <BtnPrimary onClick={() => { setUserApproved(true); toast.show("Marked as approved by you. Send it to a lawyer for their review.", "success", 4000); }} style={{ width: "100%", fontSize: 12, padding: "10px", borderRadius: 10, justifyContent: "center" }}>✅ Approve Draft</BtnPrimary>
                                        <BtnOutline onClick={() => { setEditMode(true); toast.show("✏️ Edit mode enabled", "info"); }} style={{ width: "100%", fontSize: 12, padding: "10px", borderRadius: 10 }}>✏️ Edit / Modify</BtnOutline>
                                    </div>
                                ) : (
                                    <BtnPrimary onClick={() => goTo(3)} style={{ width: "100%", fontSize: 12, padding: "11px", borderRadius: 10, justifyContent: "center", boxShadow: `0 4px 16px ${t.primaryGlow}` }}>
                                        ⚖️ Submit to Lawyer →
                                    </BtnPrimary>
                                )}
                            </Card>


                        </div>
                    </div>
                )}

                {/* ════════════════════════════════════════════════
            STEP 4 — Submit to Lawyer → Lawyer Review
        ════════════════════════════════════════════════ */}
                {step === 3 && !reviewSent && (
                    <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 18 }}>

                        {/* Left: lawyer selection */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                            {/* Doc strip */}
                            <div style={{ display: "flex", alignItems: "center", gap: 13, padding: "13px 18px", borderRadius: 14, background: `linear-gradient(135deg,${t.primaryGlow},${t.card})`, border: `1px solid ${t.primary}30` }}>
                                <div style={{ width: 38, height: 46, borderRadius: 8, background: t.card, border: `1.5px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, flexShrink: 0 }}>📄</div>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{docTitle || "Employment Dispute"}</div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>{selectedType?.label || "—"} · {caseRef || "No ref"}</div>
                                </div>
                                <Badge type="success">✓ User Approved</Badge>
                            </div>

                            <Card>
                                <STitle icon="scale" sub={caseLawyerId ? "Your case lawyer will review this document" : "Select a verified lawyer to review your document"}>Choose Lawyer</STitle>
                                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                                    {caseLawyerId && (
                                        <div style={{ fontSize: 11.5, color: t.textMuted, padding: "8px 12px", borderRadius: 10, background: t.primaryGlow, border: `1px solid ${t.primary}30`, lineHeight: 1.55 }}>
                                            This case already has an engaged lawyer — documents for it are reviewed by them.
                                        </div>
                                    )}
                                    {(caseLawyerId ? revLawyers.filter(l => l._id === caseLawyerId) : revLawyers).map(l => (
                                        <div key={l._id} onClick={() => setSelLawyer(l._id)} style={{ display: "flex", alignItems: "center", gap: 13, padding: "13px 15px", borderRadius: 13, border: `2px solid ${selLawyer === l._id ? t.primary : t.border}`, background: selLawyer === l._id ? t.primaryGlow : t.inputBg, cursor: "pointer", transition: "all 0.2s", position: "relative" }}>
                                            <div style={{ width: 44, height: 44, borderRadius: "50%", background: selLawyer === l._id ? t.primary : `${t.primary}18`, border: `2px solid ${selLawyer === l._id ? t.primary : t.border}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 800, color: selLawyer === l._id ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.primary, flexShrink: 0, transition: "all 0.2s" }}>{l.avatar}</div>
                                            <div style={{ flex: 1, minWidth: 0 }}>
                                                <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 3 }}>{l.name}</div>
                                                <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4, textTransform: "capitalize" }}>{l.spec}</div>
                                                <div style={{ display: "flex", gap: 10, fontSize: 11 }}>
                                                    {l.rating > 0 && <span style={{ color: t.warn }}>⭐ {l.rating}</span>}
                                                    <span style={{ color: l.avail ? t.success : t.textMuted }}>{l.avail ? "● Available" : "○ Busy"}</span>
                                                </div>
                                            </div>
                                            {selLawyer === l._id && <div style={{ position: "absolute", top: 8, right: 8, width: 20, height: 20, borderRadius: "50%", background: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 800, color: t.mode === "dark" ? "#1A2E35" : "#fff" }}>✓</div>}
                                        </div>
                                    ))}
                                    {caseLawyerId && !revLawyers.some(l => l._id === caseLawyerId) && (
                                        <div style={{ display: "flex", alignItems: "center", gap: 13, padding: "13px 15px", borderRadius: 13, border: `2px solid ${t.primary}`, background: t.primaryGlow }}>
                                            <div style={{ width: 44, height: 44, borderRadius: "50%", background: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 800, color: t.mode === "dark" ? "#1A2E35" : "#fff", flexShrink: 0 }}>⚖️</div>
                                            <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>Your engaged case lawyer</div>
                                        </div>
                                    )}
                                    {!caseLawyerId && !revLawyers.length && (
                                        <div style={{ fontSize: 12, color: t.textMuted, textAlign: "center", padding: "18px 0" }}>Loading verified lawyers…</div>
                                    )}
                                </div>
                            </Card>

                            <Card>
                                <STitle icon="edit" sub="Optional notes for the reviewer">Note to Lawyer</STitle>
                                <textarea value={reviewNote} onChange={e => setReviewNote(e.target.value)} placeholder="e.g. Please check wrongful termination clauses, verify PKR 500,000 compensation, confirm notice period…" rows={3} style={{ width: "100%", background: t.inputBg, border: `1.5px solid ${t.border}`, color: t.text, borderRadius: 11, padding: "11px 13px", fontSize: 12.5, outline: "none", resize: "vertical", fontFamily: "'Inter',sans-serif", lineHeight: 1.65, boxSizing: "border-box" }} onFocus={e => e.target.style.borderColor = t.primary} onBlur={e => e.target.style.borderColor = t.border} />
                            </Card>
                        </div>

                        {/* Right: config + send */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

                            {/* Selected lawyer preview */}
                            <Card style={{ minHeight: 90, display: "flex", alignItems: !selLawyer ? "center" : "flex-start" }}>
                                {!selLawyer ? (
                                    <div style={{ textAlign: "center", color: t.textMuted, fontSize: 12, width: "100%" }}><div style={{ fontSize: 24, marginBottom: 5 }}>👤</div>Select a lawyer</div>
                                ) : (() => {
                                    const l = revLawyers.find(x => x._id === selLawyer);
                                    return (
                                        <div style={{ width: "100%" }}>
                                            <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: t.textMuted, marginBottom: 8 }}>Reviewing Lawyer</div>
                                            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 11px", borderRadius: 11, background: t.primaryGlow, border: `1px solid ${t.primary}40` }}>
                                                <div style={{ width: 34, height: 34, borderRadius: "50%", background: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 800, color: t.mode === "dark" ? "#1A2E35" : "#fff", flexShrink: 0 }}>{l?.avatar || "⚖️"}</div>
                                                <div>
                                                    <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>{l?.name || "Your case lawyer"}</div>
                                                    <div style={{ fontSize: 10, color: t.primary, textTransform: "capitalize" }}>{l?.spec || (caseLawyerId ? "Engaged on this case" : "")}</div>
                                                </div>
                                            </div>
                                        </div>
                                    );
                                })()}
                            </Card>

                            {/* Urgency — tells the lawyer how quickly you need this back */}
                            <Card>
                                <STitle icon="clock" sub="How urgent is this review?">Urgency</STitle>
                                {[["Normal", "No rush", t.success], ["Priority", "Needed soon", t.warn], ["Urgent", "Time-critical", t.danger]].map(([lvl, desc, col]) => (
                                    <div key={lvl} onClick={() => setUrgency(lvl)} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: 10, border: `1.5px solid ${urgency === lvl ? col : t.border}`, background: urgency === lvl ? `${col}10` : t.inputBg, cursor: "pointer", marginBottom: 7, transition: "all 0.2s" }}>
                                        <div style={{ width: 13, height: 13, borderRadius: "50%", border: `2px solid ${urgency === lvl ? col : t.border}`, background: urgency === lvl ? col : "transparent", flexShrink: 0 }} />
                                        <div style={{ flex: 1 }}>
                                            <div style={{ fontSize: 12, fontWeight: urgency === lvl ? 700 : 500, color: urgency === lvl ? col : t.text }}>{lvl}</div>
                                            <div style={{ fontSize: 10, color: t.textFaint }}>{desc}</div>
                                        </div>
                                    </div>
                                ))}
                            </Card>

                            <BtnPrimary onClick={submitToLawyer} disabled={submitting} style={{ width: "100%", fontSize: 13, padding: "14px", borderRadius: 12, justifyContent: "center", boxShadow: `0 6px 20px ${t.primaryGlow}`, opacity: !selLawyer || submitting ? 0.6 : 1 }}>
                                {submitting ? "⏳ Submitting…" : "📤 Submit to Lawyer"}
                            </BtnPrimary>
                            <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.6, textAlign: "center" }}>
                                The lawyer is notified immediately and you'll get a notification when they respond.
                            </div>
                        </div>
                    </div>
                )}

                {/* ── Lawyer Review in Progress ── */}
                {step === 3 && reviewSent && (
                    <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>

                        {/* Left: live tracking */}
                        <Card>
                            <div style={{ textAlign: "center", padding: "18px 0 16px", borderBottom: `1px solid ${t.border}`, marginBottom: 16 }}>
                                <div style={{ width: 60, height: 60, borderRadius: "50%", background: t.primaryGlow, border: `2px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 26, margin: "0 auto 12px" }}>📬</div>
                                <div style={{ fontSize: 16, fontWeight: 800, color: t.text, fontFamily: "'Playfair Display',serif", marginBottom: 5 }}>Submitted for Legal Review</div>
                                <div style={{ display: "inline-flex", alignItems: "center", gap: 8, marginTop: 6, padding: "7px 14px", borderRadius: 50, background: t.primaryGlow, border: `1px solid ${t.primary}40` }}>
                                    <div style={{ width: 24, height: 24, borderRadius: "50%", background: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 800, color: t.mode === "dark" ? "#1A2E35" : "#fff" }}>⚖️</div>
                                    <span style={{ fontSize: 13, fontWeight: 700, color: t.primary }}>{revLawyerName}</span>
                                </div>
                            </div>

                            <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: t.textMuted, marginBottom: 14 }}>Review Progress</div>
                            <div style={{ position: "relative" }}>
                                <div style={{ position: "absolute", left: 13, top: 26, bottom: 26, width: 2, background: `linear-gradient(${t.primary}, ${t.border})`, borderRadius: 2 }} />
                                {[
                                    { ico: "✅", label: "Document submitted", sub: "Done", done: true, active: false },
                                    { ico: "🔔", label: "Lawyer notified", sub: "Done", done: true, active: false },
                                    {
                                        ico: statusView.isRecovery ? "⚠️" : "🔍",
                                        label: "Lawyer review",
                                        // NEVER "Complete" for a recovery state: the review is
                                        // exactly what could not be carried over.
                                        sub: statusView.isRecovery ? statusView.headline
                                            : reviewStatus === "submitted" ? "In progress — updates automatically"
                                            : "Complete",
                                        done: !statusView.isRecovery && reviewStatus !== "submitted",
                                        active: reviewStatus === "submitted",
                                    },
                                    {
                                        ico: statusView.isRecovery ? "⚠️" : reviewStatus === "approved" ? "✅" : reviewStatus === "returned" ? "↩️" : reviewStatus === "rejected" ? "❌" : "⚖️",
                                        label: statusView.isRecovery ? statusView.headline : reviewStatus === "approved" ? "Approved by lawyer" : reviewStatus === "returned" ? "Returned with changes" : reviewStatus === "rejected" ? "Rejected by lawyer" : "Lawyer decision",
                                        sub: statusView.isRecovery ? "Could not be carried over"
                                            : reviewStatus === "submitted" ? "Pending" : "Recorded",
                                        done: ["approved", "returned", "rejected"].includes(reviewStatus), active: false,
                                    },
                                ].map((item, i) => (
                                    <div key={i} style={{ display: "flex", gap: 13, marginBottom: 14, alignItems: "flex-start", position: "relative" }}>
                                        <div style={{ width: 28, height: 28, borderRadius: "50%", background: item.done ? t.primary : item.active ? t.primaryGlow : t.inputBg, border: `2px solid ${item.done ? t.primary : item.active ? t.primary : t.border}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, flexShrink: 0, zIndex: 1, boxShadow: item.active ? `0 0 0 4px ${t.primaryGlow}` : "none" }}>{item.ico}</div>
                                        <div style={{ flex: 1, paddingTop: 3 }}>
                                            <div style={{ fontSize: 12.5, fontWeight: item.done || item.active ? 700 : 500, color: item.done ? t.primary : item.active ? t.text : t.textMuted }}>{item.label}</div>
                                            <div style={{ fontSize: 10, color: item.active ? t.primary : t.textFaint, marginTop: 1 }}>{item.sub}</div>
                                        </div>
                                        {item.active && <div style={{ width: 8, height: 8, borderRadius: "50%", background: t.primary, marginTop: 10, flexShrink: 0, boxShadow: `0 0 0 3px ${t.primaryGlow}` }} />}
                                    </div>
                                ))}
                            </div>

                            {/* Real status-driven actions */}
                            {reviewStatus === "submitted" && (
                                <div style={{ marginTop: 4 }}>
                                    <div style={{ padding: "12px 14px", borderRadius: 12, background: t.primaryGlow, border: `1px solid ${t.primary}30`, fontSize: 11.5, color: t.textMuted, lineHeight: 1.6, marginBottom: 8 }}>
                                        ⏳ Waiting for {revLawyerName} to review. This page checks automatically —
                                        you'll also get a notification the moment they respond.
                                    </div>
                                    <button
                                        onClick={() => withdrawFromReview()}
                                        disabled={withdrawing}
                                        style={{ width: "100%", padding: "10px", borderRadius: 11, border: `1px solid ${t.border}`, background: "transparent", color: t.textMuted, fontSize: 12, fontWeight: 600, cursor: withdrawing ? "default" : "pointer", fontFamily: "'Inter',sans-serif", opacity: withdrawing ? 0.6 : 1 }}>
                                        {withdrawing ? "Withdrawing…" : "↩️ Withdraw from review"}
                                    </button>
                                </div>
                            )}
                            {statusView.isRecovery && (
                                <div style={{ marginTop: 4 }}>
                                    <div style={{ padding: "12px 14px", borderRadius: 12, background: `${t.warn}10`, border: `1px solid ${t.warn}30`, marginBottom: 8 }}>
                                        <div style={{ fontSize: 11, fontWeight: 700, color: t.warn, marginBottom: 4 }}>
                                            ⚠️ {statusView.headline}
                                        </div>
                                        {/* The API's words. A client did nothing wrong here and
                                            cannot be expected to know what the status means; left
                                            to infer, they assume their work is gone. */}
                                        <div style={{ fontSize: 12, color: t.text, lineHeight: 1.6 }}>
                                            {statusView.explanation}
                                        </div>
                                    </div>
                                    <BtnPrimary
                                        onClick={() => { setReviewSent(false); setReviewStatus(null); setReviewRecovery(null); goTo(1); }}
                                        style={{ width: "100%", fontSize: 12, padding: "11px", borderRadius: 11, justifyContent: "center" }}>
                                        ✏️ {statusView.actionLabel} →
                                    </BtnPrimary>
                                </div>
                            )}
                            {(reviewStatus === "returned" || reviewStatus === "rejected") && (
                                <div style={{ marginTop: 4 }}>
                                    <div style={{ padding: "12px 14px", borderRadius: 12, background: reviewStatus === "returned" ? `${t.warn}10` : `${t.danger}10`, border: `1px solid ${reviewStatus === "returned" ? t.warn : t.danger}30`, marginBottom: 8 }}>
                                        <div style={{ fontSize: 11, fontWeight: 700, color: reviewStatus === "returned" ? t.warn : t.danger, marginBottom: 4 }}>
                                            {reviewStatus === "returned" ? "↩️ Lawyer requested changes" : "❌ Lawyer rejected this document"}
                                        </div>
                                        <div style={{ fontSize: 12, color: t.text, lineHeight: 1.6 }}>{lawyerNote || "No note provided."}</div>
                                    </div>
                                    {reviewStatus === "returned" && (
                                        <BtnPrimary onClick={() => { setReviewSent(false); setReviewStatus(null); goTo(1); }} style={{ width: "100%", fontSize: 12, padding: "11px", borderRadius: 11, justifyContent: "center" }}>
                                            ✏️ Revise & Regenerate →
                                        </BtnPrimary>
                                    )}
                                </div>
                            )}
                            {reviewStatus === "approved" && (
                                <BtnPrimary onClick={() => goTo(4)} style={{ width: "100%", fontSize: 13, padding: "13px", borderRadius: 12, justifyContent: "center", marginTop: 4, boxShadow: `0 4px 18px ${t.primaryGlow}` }}>
                                    🏛 View Final Version →
                                </BtnPrimary>
                            )}
                        </Card>

                        {/* Right: submission details + export */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                            <Card>
                                <STitle icon="file" sub="Submission overview">Details</STitle>
                                <div style={{ padding: "9px 12px", borderRadius: 10, background: t.primaryGlow, border: `1px solid ${t.primary}30`, marginBottom: 10 }}>
                                    <div style={{ fontSize: 12, fontWeight: 700, color: t.text, marginBottom: 1 }}>{docTitle || "Employment Dispute"}</div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>{selectedType?.label || "—"} · {caseRef || "No ref"}</div>
                                </div>
                                {[["Lawyer", revLawyerName], ["Urgency", urgency], ["Type", selectedType?.label || "—"], ["Status", null]].map(([k, v]) => (
                                    <div key={k} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "7px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>{k}</span>
                                        {k === "Status" ? <Badge type={statusColors[docStatus]}>{docStatus}</Badge>
                                            : k === "Urgency" ? <Badge type={urgency === "Urgent" ? "danger" : urgency === "Priority" ? "warn" : "success"}>{urgency}</Badge>
                                                : <span style={{ fontWeight: 600, color: t.text }}>{v}</span>}
                                    </div>
                                ))}
                                {reviewNote ? <div style={{ marginTop: 9, padding: "9px 11px", borderRadius: 9, background: t.inputBg, fontSize: 11, color: t.textMuted, fontStyle: "italic" }}>📝 "{reviewNote.slice(0, 90)}{reviewNote.length > 90 ? "…" : ""}"</div> : null}
                            </Card>

                            <Card>
                                <STitle icon="dl" sub="Download the generated PDF">Export</STitle>
                                <BtnOutline
                                    onClick={() => { if (docId) { downloadDocumentFile(docId, docTitle || "document", {
                                        revisionId: viewRev?.revision_id || docRevisionId,
                                        expectedPdfSha256: viewRev?.pdf_sha256 || docPdfSha256,
                                    }); } else { toast.show("Generate the document first", "warn"); } }}
                                    disabled={!docId}
                                    style={{ width: "100%", fontSize: 12, padding: "11px", borderRadius: 11, justifyContent: "center" }}>
                                    {docId ? "📥 Download PDF" : "Generate the document first"}
                                </BtnOutline>
                            </Card>

                            <div style={{ padding: "12px 15px", borderRadius: 13, background: `${t.success}10`, border: `1px solid ${t.success}30`, display: "flex", gap: 11, alignItems: "center" }}>
                                <div style={{ width: 30, height: 30, borderRadius: "50%", background: `${t.success}20`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, flexShrink: 0 }}>🔔</div>
                                <div>
                                    <div style={{ fontSize: 12, fontWeight: 700, color: t.text, marginBottom: 2 }}>You'll be notified</div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>Alert when {revLawyerName} completes review.</div>
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* ════════════════════════════════════════════════
            STEP 5 — Final Version + Export
        ════════════════════════════════════════════════ */}
                {step === 4 && (
                    <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 18 }}>

                        {/* Left: final document */}
                        <Card style={{ display: "flex", flexDirection: "column" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
                                <div style={{ width: 36, height: 36, borderRadius: 10, background: `${t.success}20`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, flexShrink: 0 }}>🏛</div>
                                <div style={{ flex: 1 }}>
                                    <div style={{ fontWeight: 700, color: t.text, fontSize: 14 }}>Final Legal Document</div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>{docTitle || "Employment Dispute"}</div>
                                </div>
                                <Badge type="info">Final</Badge>
                            </div>

                            {/* Final doc preview — the REAL approved PDF, rendered inline. */}
                            <div style={{ flex: 1, border: `1.5px solid ${t.success}40`, borderRadius: 12, background: "#fff", overflow: "hidden", minHeight: 420 }}>
                                {previewUrl ? (
                                    <iframe title="Approved document" src={previewUrl} style={{ width: "100%", height: 420, border: "none", display: "block" }} />
                                ) : (
                                    <div style={{ padding: 40, textAlign: "center", color: t.textMuted, fontSize: 13, minHeight: 420, display: "flex", alignItems: "center", justifyContent: "center" }}>Loading the approved document…</div>
                                )}
                            </div>

                            {/* Export actions */}
                            <div style={{ marginTop: 14 }}>
                                {/* Only Download was ever wired. Generate PDF / Email /
                                    Print each toasted a completed action and did none of
                                    it — and the PDF already exists by this point, so
                                    "generate" was meaningless too. */}
                                <div style={{ marginBottom: 8 }}>
                                    <BtnOutline
                                        onClick={() => { if (docId) { setExported(true); downloadDocumentFile(docId, docTitle || "document", {
                                        revisionId: viewRev?.revision_id || docRevisionId,
                                        expectedPdfSha256: viewRev?.pdf_sha256 || docPdfSha256,
                                    }); } else { toast.show("Generate the document first", "warn"); } }}
                                        disabled={!docId}
                                        style={{ width: "100%", fontSize: 12, padding: "12px", borderRadius: 11, justifyContent: "center" }}>
                                        {docId ? "📥 Download PDF" : "Generate the document first"}
                                    </BtnOutline>
                                </div>
                            </div>
                        </Card>

                        {/* Right: summary + completed workflow */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

                            {/* Completion badge */}
                            <div style={{ textAlign: "center", padding: "20px 16px", borderRadius: 16, background: `linear-gradient(135deg,${t.primaryGlow},${t.card})`, border: `1px solid ${t.primary}30` }}>
                                <div style={{ fontSize: 42, marginBottom: 10 }}>🎉</div>
                                <div style={{ fontSize: 14, fontWeight: 800, color: t.text, fontFamily: "'Playfair Display',serif", marginBottom: 5 }}>Document Complete</div>
                                <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 12 }}>Reviewed and approved by {revLawyerName || "your lawyer"}</div>
                                <Badge type="info" style={{ fontSize: 12, padding: "5px 14px" }}>● Final Version</Badge>
                            </div>

                            {/* Document summary */}
                            <Card>
                                <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: t.textMuted, marginBottom: 10 }}>Document Summary</div>
                                {[["Type", selectedType?.label || "—"], ["Template", selectedDraft !== null ? DRAFTS_DATA[selectedDraft].name : "—"], ["Case Ref", caseRef || "—"], ["Reviewer", revLawyerName || "—"], ["Status", null], ["Compliance", null]].map(([k, v]) => (
                                    <div key={k} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "7px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>{k}</span>
                                        {k === "Status" ? <Badge type="info">Final</Badge> : k === "Compliance" ? <Badge type="success">✓ Verified</Badge> : <span style={{ fontWeight: 600, color: t.text, textAlign: "right", maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{v}</span>}
                                    </div>
                                ))}
                            </Card>

                            {/* Completed workflow */}
                            <Card>
                                <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: t.textMuted, marginBottom: 12 }}>Workflow Complete</div>
                                {FLOW.map((f, i) => (
                                    <div key={i} style={{ display: "flex", gap: 9, marginBottom: i < FLOW.length - 1 ? 8 : 0 }}>
                                        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                                            <div style={{ width: 18, height: 18, borderRadius: "50%", background: t.primary, border: `2px solid ${t.primary}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 7, fontWeight: 800, color: t.mode === "dark" ? "#1A2E35" : "#fff" }}>✓</div>
                                            {i < FLOW.length - 1 && <div style={{ width: 1, height: 12, background: t.primary, marginTop: 1 }} />}
                                        </div>
                                        <div style={{ fontSize: 10.5, color: t.primary, fontWeight: 500, paddingTop: 1 }}>{f.label}</div>
                                    </div>
                                ))}
                            </Card>
                        </div>
                    </div>
                )}

            </div>
        </div>
    );
};


/* ══════════════════════════════════════════════════════
   MODULE: CASE TRACKING
══════════════════════════════════════════════════════ */
const ModTracking = () => {
    const t = useT();
    const [notifs, setNotifs] = useState([
        { id: 1, text: "Court Hearing scheduled for Feb 25", read: false, type: "danger" },
        { id: 2, text: "Ahmad Raza Khan responded to your question", read: false, type: "info" },
        { id: 3, text: "NDA Agreement has been signed", read: true, type: "success" },
    ]);
    // Case timeline and hearing dates, from the case itself.
    //
    // These were three hardcoded arrays presented as the user's own case:
    // milestones ("Court Hearing — Feb 25", "Ahmad Raza Khan assigned"),
    // deadlines ("Submit Evidence — 1 day left", "Pay Court Fees — Mar 5") and
    // a Lawyer Q&A whose sample answer put a fabricated "approximately 75-80%"
    // win probability in the client's hands. A client can act on a court date
    // and miss a real one; nobody should ever read an invented probability as
    // their lawyer's opinion. The Q&A card is gone entirely — there is no
    // backend for it, and case messaging already exists under Tracking.
    const [timeline, setTimeline] = useState({ milestones: [], hearing_dates: [] });
    const timelineCaseId = genCaseId || activeCaseId;
    useEffect(() => {
        if (!timelineCaseId) { setTimeline({ milestones: [], hearing_dates: [] }); return; }
        getCaseTimeline(timelineCaseId).then(({ data }) => {
            if (data) setTimeline({ milestones: data.milestones || [], hearing_dates: data.hearing_dates || [] });
        });
    }, [timelineCaseId]);
    const milestones = timeline.milestones;
    const deadlines = timeline.hearing_dates;
    const markRead = (id) => setNotifs(n => n.map(x => x.id === id ? { ...x, read: true } : x));
    return (
        <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 18 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <Card>
                    <STitle icon="clock" sub={timelineCaseId ? activeCaseTitle : "No case linked"}>Case Timeline</STitle>
                    {!milestones.length && (
                        <div style={{ padding: "14px 4px", fontSize: 12.5, color: t.textMuted }}>
                            {timelineCaseId
                                ? "No milestones recorded yet. Your lawyer adds these as the case progresses."
                                : "Link a case to see its timeline."}
                        </div>
                    )}
                    <div style={{ position: "relative", paddingLeft: 20 }}>
                        <div style={{ position: "absolute", left: 28, top: 0, bottom: 0, width: 2, background: t.border, borderRadius: 2 }} />
                        {milestones.map((m, i) => {
                            const isDone = Boolean(m.completed);
                            // The first not-yet-completed milestone is the live one.
                            const isActive = !isDone && milestones.findIndex(x => !x.completed) === i;
                            return (
                                <div key={i} style={{ display: "flex", gap: 16, alignItems: "flex-start", marginBottom: 24, position: "relative" }}>
                                    <div style={{ width: 22, height: 22, borderRadius: "50%", background: isDone ? t.success : isActive ? t.primary : t.inputBg, border: `2px solid ${isDone ? t.success : isActive ? t.primary : t.border}`, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, zIndex: 1, boxShadow: isActive ? `0 0 14px ${t.primaryGlow}` : "none" }}>
                                        {isDone && <Ic n="check" s={11} c={t.mode === "dark" ? "#1A2E35" : "#fff"} />}
                                        {isActive && <div style={{ width: 8, height: 8, background: t.mode === "dark" ? "#1A2E35" : "#fff", borderRadius: "50%" }} />}
                                    </div>
                                    <div style={{ flex: 1, paddingTop: 1 }}>
                                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                                            <div style={{ fontWeight: isActive ? 700 : 600, color: isActive ? t.primary : isDone ? t.text : t.textMuted, fontSize: 13 }}>{m.title}</div>
                                            <div style={{ fontSize: 11, color: t.textMuted }}>{m.date ? new Date(m.date).toLocaleDateString("en-PK", { day: "numeric", month: "short" }) : ""}</div>
                                        </div>
                                        <div style={{ fontSize: 12, color: t.textMuted, marginTop: 3 }}>{m.description || ""}</div>
                                        {!isDone && <button style={{ marginTop: 6, background: "none", border: "none", color: t.primary, fontSize: 11, cursor: "pointer", padding: 0 }}>+ Add Note</button>}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </Card>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <Card>
                    <STitle icon="cal" sub="Scheduled hearings for this case">Hearings</STitle>
                    {!deadlines.length && (
                        <div style={{ padding: "14px 4px", fontSize: 12.5, color: t.textMuted }}>
                            {timelineCaseId ? "No hearings scheduled yet." : "Link a case to see its hearings."}
                        </div>
                    )}
                    {deadlines.map((d, i) => {
                        const when = d.date ? new Date(d.date) : null;
                        const days = when ? Math.ceil((when - new Date()) / 86400000) : null;
                        const soon = days !== null && days <= 3;
                        return (
                            <div key={d.id || i} style={{ padding: "12px 14px", borderRadius: 12, background: soon ? `${t.danger}12` : t.inputBg, marginBottom: 9 }}>
                                <div style={{ fontWeight: 600, fontSize: 13, color: soon ? t.danger : t.text }}>{d.purpose || d.court || "Hearing"}</div>
                                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 5 }}>
                                    <span style={{ fontSize: 11, color: t.textMuted }}>{when ? when.toLocaleDateString("en-PK", { day: "numeric", month: "short", year: "numeric" }) : "Date not set"}</span>
                                    {days !== null && days >= 0 && (
                                        <span style={{ fontSize: 11, fontWeight: 700, color: soon ? t.danger : t.warn }}>{days}d left</span>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </Card>
                <Card>
                    <STitle icon="bell" sub="Hearing, status & alert updates">Notifications</STitle>
                    {notifs.map(n => (
                        <div key={n.id} onClick={() => markRead(n.id)} style={{ display: "flex", gap: 10, padding: "10px 0", borderBottom: `1px solid ${t.border}`, cursor: "pointer", opacity: n.read ? 0.55 : 1 }}>
                            <div style={{ width: 8, height: 8, borderRadius: "50%", background: n.read ? "transparent" : t[n.type] || t.primary, flexShrink: 0, marginTop: 5 }} />
                            <div style={{ fontSize: 12, color: t.text, lineHeight: 1.6, flex: 1 }}>{n.text}</div>
                        </div>
                    ))}
                </Card>
                <Card>
                    <STitle icon="clock" sub="Set custom reminders for deadlines">Reminders</STitle>
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                        <div><Lbl>Description</Lbl><ThemedInput placeholder="e.g. File plaint tomorrow" /></div>
                        <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                            <div><Lbl>Date</Lbl><ThemedInput type="date" /></div>
                            <div><Lbl>Time</Lbl><ThemedInput type="time" /></div>
                        </div>
                        <BtnPrimary style={{ fontSize: 13, padding: "12px" }}>Set Reminder</BtnPrimary>
                    </div>
                </Card>
            </div>
        </div>
    );
};

export default ModDocuments;

