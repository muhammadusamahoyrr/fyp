'use client';
// Paste your ModDocuments.jsx code here
import React, { useState, Fragment, useEffect, useRef } from "react";
import { useT, ThemeCtx } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import Ic from "./Ic.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput, Badge } from "@/components/shared/shared.jsx";
import { useCase } from "./CaseContext.jsx";
import { confirmedCases } from "@/lib/caseStatus.js";
import RevisionHistory from "@/components/shared/RevisionHistory.jsx";
import MyDocumentsPanel from "./MyDocumentsPanel.jsx";
import DocumentsHome from "./DocumentsHome.jsx";
import DocsDrafts from "./documents/DocsDrafts.jsx";
import DocsVault from "./documents/DocsVault.jsx";
import { readReviewRequestLink } from "@/lib/reviewRequests.js";
import { Btn, Pill, Label, Paper, SERIF, TOKEN_STYLE, VALUE_STYLE, docsTheme, DOCS_FONT_CSS } from "./documents/ui.jsx";
import { useIsMobile } from "@/lib/i18n.jsx";
import { useAuth } from "@/context/AuthContext.jsx";
import FieldReview from "./FieldReview.jsx";
import { buildReviewRows, toSubmittedFields, missingFields, editRow, hasEdits, humanise as humaniseField }
    from "@/lib/fieldReview.js";
import { documentStatusView } from "@/lib/documentStatus.js";
import { complianceSummary } from "@/lib/complianceSummary.js";
import { verificationView } from "@/lib/draftVerification.js";
import { isReloadNavigation, rememberDraft, restoreStateFromDocument } from "@/lib/documentResume.js";
import { loadDocumentDetail, reviewStateFromDetail } from "@/lib/documentLoader.js";
import { useDocumentResume, NO_CASE } from "@/lib/useDocumentResume.js";
import { caseSelection } from "@/lib/caseSelection.js";
import {
    DOCUMENTS_VIEW_EVENT, peekPendingDocumentsView, takePendingDocumentsView,
    announceDocumentsView, DOCUMENT_OPEN_EVENT, takePendingDocument,
    readOpenDocumentLink, linkOpenDocument, unlinkOpenDocument,
} from "@/lib/documentsNav.js";
import {
    extractDocumentFields, generateDocument, downloadDocumentFile,
    fetchRevisionPreview, submitDocumentForReview,
    listEngagements, getCaseTimeline,
    createDocumentV2, generateRevisionV2, submitDocumentV2, getDocumentV2,
    withdrawDocumentV2, listTemplates, getDocumentLegacy,
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

// complianceSummary tone → this module's Badge types.
const _PARTICULARS_BADGE = { success: "success", warn: "warn", neutral: "gray" };
// verificationView tone → Badge types. Only "ok" is green.
const _CITATION_BADGE = { ok: "success", warn: "warn", danger: "danger", neutral: "gray" };

const Lbl = ({ children }) => {
    const t = useT();
    return <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 8, fontWeight: 600, letterSpacing: "0.6px", textTransform: "uppercase" }}>{children}</div>;
};

/* ══════════════════════════════════════════════════════
   MODULE: DOCUMENT AUTOMATION — 5-Step Wizard
══════════════════════════════════════════════════════ */
const GEN_STEPS_LABELS = ["Extracting case data…", "Applying AI recommendations…", "Populating template…", "Formatting document…", "Generating draft…"];



/* Catalogue entries grouped for the picker, categories in a stable order.
 *
 * Ordered by the server's category name rather than by a list held here: a
 * category this file did not anticipate would otherwise vanish from the picker,
 * which is the same class of bug as the hardcoded template lists this replaced.
 */
/* A retry key, or null. The handlers below take an optional key, and a button
 * wired as `onClick={handler}` hands them the click EVENT instead. That object
 * became the Idempotency-Key — sent as "[object Object]", which the server
 * refuses (422: no spaces) — so Generate and Submit failed on every click. */
function asKey(retryKey) {
    return typeof retryKey === "string" && retryKey ? retryKey : null;
}

function draftingMode(spec) {
    if (spec?.drafting_mode) return spec.drafting_mode;
    if (spec?.structured_fields?.length) return "dedicated";
    // Compatibility with a backend deployed just before this catalogue field:
    // its old entries were exactly the AI-assisted set used by this screen.
    return "ai";
}

// Structured templates are produced by deterministic tools, not by the generic
// free-text drafter. Keep this small routing map next to that boundary so every
// catalogue card opens the tool that can actually create its document.
const DEDICATED_TOOL_TABS = {
    inheritance_settlement: "calc",
    wasiyyat_nama: "wasiyyat",
    labour_demand: "calculators",
};

function dedicatedToolHref(spec) {
    const tab = DEDICATED_TOOL_TABS[spec?.template_type];
    return tab ? `/tools?tab=${encodeURIComponent(tab)}` : "/tools";
}

/* The words for what extraction managed, or null when there is nothing to say.
 * "failed" and "empty" produce the same blank form and mean opposite things:
 * one is the AI not reading the case, the other the case not saying. */
export function extractionNotice(result) {
    const status = result?.extraction_status;
    const parts = [];
    if (status === "failed") {
        parts.push("The AI could not read your case this time. Fill in the fields yourself, "
            + "or go back and try Generate Draft again.");
    } else if (status === "empty") {
        parts.push("The AI read your case but found none of these details in it. "
            + "Fill in the fields yourself before generating.");
    }
    if (result?.truncated) {
        parts.push("Your case description is very long, so the AI read only its first part — "
            + "check that the details below are complete.");
    }
    return parts.length ? { kind: status === "ok" ? "truncated" : status, message: parts.join(" ") } : null;
}

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
    // The Documents screens use the approved mockup's palette in dark mode
    // (see documents/ui.jsx), and hand it down so every child — including
    // shared panels — draws in the same colours.
    const t = docsTheme(useT());
    const { user } = useAuth();
    const toast = useToast();
    const { cases: allCases, casesReady, casesError, casesReloading, reloadCases } = useCase();
    // A draft has not been confirmed by the client, so it must not be offered
    // as something to generate a legal document against.
    const cases = confirmedCases(allCases);

    /* ── State ── */
    const [step, setStep] = useState(0);                       // 0–4
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
    // A revision stays on one identity only while its case and instrument do.
    // Changing either creates a new document rather than disguising a different
    // legal instrument as version 2 of the old one.
    const [documentTemplateType, setDocumentTemplateType] = useState(null);
    // The open document's current version is edited TEXT (see documentResume):
    // "Change answers" and "Revise" then go to the drafting workspace rather
    // than rebuilding the document from the template's fields.
    const [textEdited, setTextEdited] = useState(false);
    const [documentIdentityTitle, setDocumentIdentityTitle] = useState(null);

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
    // What the AI managed to read from the case, in words, shown above the
    // field review. A failed read used to arrive as blank fields that looked
    // exactly like "your case does not say" — see extractionNotice().
    const [extractNotice, setExtractNotice] = useState(null);
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
    const [generating, setGenerating] = useState(false);
    const [genPct, setGenPct] = useState(0);
    const [genDone, setGenDone] = useState(false);
    // Statutory completeness of the generated draft, returned by the API.
    const [compliance, setCompliance] = useState(null);
    // What the final screen may truthfully say about it — never "Verified".
    const finalParticulars = complianceSummary(compliance);
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
    const [revLawyers, setRevLawyers] = useState([]);         // lawyers of the client's ACCEPTED engagements
    const [revLawyersLoaded, setRevLawyersLoaded] = useState(false);
    const [caseLawyerId, setCaseLawyerId] = useState(null);   // assigned lawyer of the linked case, if any
    const [genCaseId, setGenCaseId] = useState(null);         // case the document was generated for
    // THE EXTRACTION, BEFORE IT BECOMES A DOCUMENT.
    //
    // Generation used to run extraction and rendering back to back, so a model
    // decided who the parties were and what the amounts were and those values
    // entered a legal document without the client ever seeing them. `rawFields`
    // is what the model returned; `reviewRows` is that, editable.
    const [rawFields, setRawFields] = useState(null);
    const [reviewRows, setReviewRows] = useState(null);
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
        if (step !== 3 || revLawyersLoaded) return;
        // D1 (2026-10-03): a document goes to a lawyer only through an ACCEPTED
        // engagement -- the server refuses anyone else. So the choice is the
        // lawyers the client has engaged, never the whole directory.
        listEngagements({ status: "accepted" }).then(({ data }) => {
            const items = Array.isArray(data) ? data : (data?.items || []);
            const byLawyer = new Map();
            for (const e of items) {
                if (!e?.lawyer_id || byLawyer.has(e.lawyer_id)) continue;
                const name = e.lawyer_name || "Your lawyer";
                byLawyer.set(e.lawyer_id, {
                    _id: e.lawyer_id,
                    name,
                    spec: e.case_title ? `Engaged on: ${e.case_title}` : "Engaged lawyer",
                    rating: 0,
                    avail: null,
                    avatar: name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase(),
                });
            }
            setRevLawyers([...byLawyer.values()]);
        }).catch(() => { }).finally(() => setRevLawyersLoaded(true));
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

    // Restoring happens independently of the catalogue request. Once both have
    // arrived, restore the actual backend template into the picker so a returned
    // document can be revised after a refresh without choosing an instrument
    // again (or accidentally choosing a different one).
    useEffect(() => {
        if (!documentTemplateType || !templates?.length) return;
        const spec = templates.find(x => x.template_type === documentTemplateType);
        if (spec) setSelectedType(spec);
    }, [documentTemplateType, templates]);

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
    // THE CASE ON SCREEN, not the one a past generation happened to use.
    //
    // This was `genCaseId || resolveCaseId(...)`, and `genCaseId` is only ever
    // set BY a generation — so once the client generated anything, switching
    // to another matter could not move the resume key. The draft of the first
    // case followed them around, and the second case's own draft was
    // unreachable.
    //
    // Generation sets `genCaseId` to the same value this resolves to, so the
    // two agree until the user deliberately switches, which is exactly when the
    // new case should win.
    /* ONE derivation, shared by the resume hook, the selector, the readiness
     * badge and both halves of generation. There were three and they could
     * disagree — opening a case-B document moved the internal case to B while
     * the selector stayed on A, and generation read the selector.
     *
     * A standalone V2 document uses manual field entry because there is no case
     * description to extract. The legacy fallback reports that limitation.
     */
    const selection = caseSelection({
        selectedCaseId, cases, casesReady, allowStandaloneCreation: true,
    });
    const resumeCaseId = selection.activeCaseId;

    /* Put a restored document on screen. Shared by the refresh-resume hook,
     * by opening a row in My Documents, and by previewing one — three callers
     * that must not drift apart in what "opening a document" means. */
    const applyRestored = (restored) => {
        setDocId(restored.docId);
        if (restored.docTitle) setDocTitle(restored.docTitle);
        setDocRevisionId(restored.docRevisionId);
        setDocPdfSha256(restored.docPdfSha256);
        setDocVersion(restored.docVersion);
        setDocumentTemplateType(restored.templateType);
        setTextEdited(Boolean(restored.textEdited));
        setDocumentIdentityTitle(restored.docTitle || null);
        setCompliance(restored.compliance ?? null);
        setVerification(restored.verification ?? null);
        setGenDone(restored.genDone);
        setReviewSent(restored.reviewSent);
        setReviewStatus(restored.reviewStatus);
        setReviewRecovery(restored.reviewRecovery);
        setStep(restored.step);
        // REMEMBERED UNDER ITS OWN CASE — including when that case is NONE.
        //
        // This was `restored.caseId || resumeCaseId`, and `||` cannot tell a
        // deliberate null from a missing value. `restoreStateFromDocument`
        // returns null precisely to say "this document belongs to no case", and
        // the fallback then filed a standalone draft under whichever matter
        // happened to be selected — re-creating, for caseless documents, the
        // exact wrong-matter bug the caseId was added to fix.
        //
        // A caseless document lives in its own bucket (`rememberDraft` keys it
        // under "no-case"), so it is restored when no case is selected and never
        // mistaken for a matter's work.
        const owningCase = restored.caseId ?? null;
        setGenCaseId(owningCase);
        // THE SELECTOR FOLLOWS THE DOCUMENT.
        //
        // Opening a case-B document set `genCaseId` to B and left
        // `selectedCaseId` on A, so the picker said one matter while the
        // document on screen belonged to another — and `resumeCaseId`, derived
        // from the selector, then pointed the resume hook back at A.
        //
        // `NO_CASE` rather than "" for a standalone document: an empty
        // selection falls through to the first case in the list, which would
        // drag the document into a matter it does not belong to.
        setSelectedCaseId(owningCase || NO_CASE);
        rememberDraft(owningCase, restored.docId);
    };

    /* Take the current document off screen.
     *
     * Called when the selected case has no draft of its own: leaving the
     * previous case's document up, under the new case's heading, is the same
     * wrong-matter confusion reached from the other direction. */
    const clearOpenDocument = () => {
        // `genCaseId` GOES TOO. It was left pointing at the case just cleared,
        // and four other things read it: the assigned-lawyer lookup, the review
        // poller, the generation target and the timeline. The document
        // disappeared from the screen while the rest of the page carried on
        // describing the matter it had belonged to.
        setGenCaseId(null);
        setDocId(null);
        setDocTitle("");
        setDocRevisionId(null);
        setDocPdfSha256(null);
        setDocVersion(null);
        setDocumentTemplateType(null);
        setTextEdited(false);
        setDocumentIdentityTitle(null);
        setGenDone(false);
        setReviewSent(false);
        setReviewStatus(null);
        setReviewRecovery(null);
        setViewRev(null);
        setReviewRows(null);
        setRawFields(null);
        setStep(0);
    };

    /* Leave the open document and start over from the catalogue.
     *
     * The document is NOT deleted and stays in My Documents; this only takes
     * it off screen. The template choice and every held key go too — a key
     * kept from the previous document would make the server replay that
     * document's generate or submit for the new one. */
    const startNewDocument = () => {
        clearOpenDocument();
        unlinkOpenDocument();
        setSelectedType(null);
        setDocTitle("");
        setExtractNotice(null);
        setDocIssue(null);
        setCompliance(null);
        setVerification(null);
        setFieldShape(null);
        setLawyerNote("");
        setUserApproved(false);
        setExported(false);
        generateKeyRef.current = null;
        submitKeyRef.current = null;
        withdrawKeyRef.current = null;
    };

    /* The sidebar's Documents menu. A request made before this mounted is
     * read on the first render, so it wins over the refresh-resume that would
     * otherwise jump to the last draft.
     *
     * NOT consumed on mount. The module can mount more than once for one
     * visit (the dashboard keys it by tab, and providers settle in stages),
     * and the mount that consumed it was not the one that met the restore.
     * It is consumed when it has done its job: it held back a restore, or the
     * user picked a template. */
    const [initialView] = useState(peekPendingDocumentsView);
    const stayHomeRef = useRef(Boolean(initialView));
    // A hard browser refresh is a fresh entry to Documents. The previous
    // document remains available in My Documents, but must not take over the
    // page and drop the user directly into its review step.
    const skipReloadResumeRef = useRef(isReloadNavigation());
    // Which screen the module shows. "flow" is the template flow (home and
    // its steps); the others are whole screens of their own.
    const [view, setView] = useState("flow");
    // A notification deep link (/documents?tab=review-requests&request=…):
    // read once from the address, it opens the Vault on its Review requests tab.
    const [reviewLink] = useState(() => (typeof window === "undefined"
        ? { open: false, requestId: null, invalid: false }
        : readReviewRequestLink(window.location.search)));
    useEffect(() => { if (reviewLink.open) setView("vault"); }, [reviewLink]);
    const [draftsSeed, setDraftsSeed] = useState(null);
    // The document the address names (`?doc=<id>`), read once: a refresh of an
    // open document reopens it -- see lib/documentsNav.js.
    const [linkedDoc] = useState(() => (typeof window === "undefined" ? null
        : readOpenDocumentLink(window.location.search)));
    const [vaultPreviewId, setVaultPreviewId] = useState(null);
    /* Where the flow was entered from. "Send to lawyer" in the AI drafting
     * workspace opens the send screen directly (the workspace IS the review),
     * and its way back returns to that document in the workspace rather than
     * to the guided flow's review step. The sidebar keeps "AI drafting" lit. */
    const [flowOrigin, setFlowOrigin] = useState(null);       // { from: "drafts", documentId } | null
    const [draftsOpen, setDraftsOpen] = useState(null);       // { id, at } — reopen in the workspace
    useEffect(() => {
        announceDocumentsView(view === "flow" ? (flowOrigin?.from === "drafts" ? "drafts" : "new") : view);
    }, [view, flowOrigin]);
    const backToDraft = () => {
        const id = flowOrigin?.documentId || docId;
        setFlowOrigin(null);
        setDraftsOpen(id ? { id, at: Date.now() } : null);
        setView("drafts");
    };
    // Details typed in the template's Customize editor, carried into the
    // drafting form so nothing typed there is lost.
    const prefillRef = useRef(null);
    const showView = view => {
        setFlowOrigin(null);
        unlinkOpenDocument();
        setVaultPreviewId(null);
        if (view === "drafts" || view === "vault") {
            if (view === "drafts") setDraftsOpen(null);
            setView(view);
            return;
        }
        if (view === "new" || view === "mine") { startNewDocument(); setView("flow"); }
        if (view === "mine" && typeof document !== "undefined") {
            // After the home renders, bring the user's documents into view.
            setTimeout(() => document.getElementById("my-documents")
                ?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
        }
    };
    useEffect(() => {
        if (initialView) showView(initialView);
        const onView = e => {
            takePendingDocumentsView();
            showView(e?.detail?.view);
        };
        // A notification asked for one document: it opens in the workspace.
        const openDocument = id => {
            if (!id) return;
            stayHomeRef.current = true;          // no draft resume over it
            setFlowOrigin(null);
            setDraftsOpen({ id, at: Date.now() });
            setView("drafts");
        };
        // A notification's request wins; otherwise the address's document
        // (a refresh). A sidebar request made before mount wins over both.
        const asked = takePendingDocument();
        if (asked) openDocument(asked);
        else if (!initialView && linkedDoc) {
            if (linkedDoc.preview) { stayHomeRef.current = true; setVaultPreviewId(linkedDoc.id); setView("vault"); }
            else openDocument(linkedDoc.id);
        }
        const onOpen = e => { takePendingDocument(); openDocument(e?.detail?.id); };
        window.addEventListener(DOCUMENTS_VIEW_EVENT, onView);
        window.addEventListener(DOCUMENT_OPEN_EVENT, onOpen);
        return () => {
            window.removeEventListener(DOCUMENTS_VIEW_EVENT, onView);
            window.removeEventListener(DOCUMENT_OPEN_EVENT, onOpen);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // A document generated or opened in the guided flow is linked too; a
    // refresh reopens it in the drafting workspace -- the one editor.
    useEffect(() => { if (view === "flow" && docId) linkOpenDocument(docId); }, [view, docId]);

    useDocumentResume({
        caseId: resumeCaseId,
        // From the CONTEXT, not from `Array.isArray(cases)`. `cases` is
        // initialised to [], so that expression was true before `listCases` had
        // even been called — the hook then treated "still asking" as "this user
        // has no cases" and restored a standalone draft a beat before the real
        // case arrived.
        ready: casesReady && !skipReloadResumeRef.current,
        // WHICH case the open document belongs to, not merely that one is open.
        // A boolean meant the first loaded document blocked restoration for
        // every case thereafter, so switching matters kept showing the first
        // matter's draft.
        loaded: { hasDocument: Boolean(docId), caseId: genCaseId },
        // V2 first; the legacy route only when V2 is switched off. See
        // lib/documentLoader.js for why nothing else falls back.
        getDocument: (id) => loadDocumentDetail(id, {
            getV2: getDocumentV2, getLegacy: getDocumentLegacy }),
        onRestore: (restored, forCase) => {
            // Opened from the sidebar's menu: stay on the home screen. The
            // draft is still one click away in My Documents.
            // Cleared only when it actually holds a draft back: an earlier
            // "nothing to restore" (the case list still empty) is not it.
            if (restored && stayHomeRef.current) {
                stayHomeRef.current = false;
                takePendingDocumentsView();
                return;
            }
            if (restored) {
                applyRestored(restored);
                return;
            }
            // Nothing saved for this case. Clear whatever belongs to another
            // one — but only then, so a failed restore of THIS case's draft
            // does not wipe the screen the user is already working on.
            if (docId && genCaseId !== forCase) clearOpenDocument();
        },
    });

    // Poll the real review status while waiting for the lawyer
    useEffect(() => {
        // THIS document's own detail — not the case list, which cannot carry a
        // V2 document and does not exist for a caseless one. See
        // reviewStateFromDetail in lib/documentLoader.js.
        if (!reviewSent || !docId) return;
        if (reviewStatus && reviewStatus !== "submitted") return; // terminal state reached
        let live = true;
        const refresh = async () => {
            const { data } = await loadDocumentDetail(docId, {
                getV2: getDocumentV2, getLegacy: getDocumentLegacy });
            const s = live ? reviewStateFromDetail(data) : null;
            if (s) {
                setReviewStatus(s.reviewStatus);
                setReviewRecovery(s.recovery);
                setLawyerNote(s.lawyerNote);
            }
        };
        refresh();
        const iv = setInterval(refresh, 12000);
        return () => { live = false; clearInterval(iv); };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [reviewSent, docId, reviewStatus]);

    const submitToLawyer = async (retryKey = null) => {
        if (!docId) { toast.show("⚠️ Generate the document first (Step 2)", "warn"); return; }
        if (!selLawyer) { toast.show("⚠️ Select a lawyer first", "warn"); return; }
        setSubmitting(true);
        setDocIssue(null);

        // The same rule as generation: one key per intent, reused by a retry.
        submitKeyRef.current = asKey(retryKey) || submitKeyRef.current || idempotencyKey();

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
        withdrawKeyRef.current = asKey(retryKey) || withdrawKeyRef.current || idempotencyKey();

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

    const tbBtn = { padding: "5px 10px", borderRadius: 8, border: `1px solid ${t.border}`, background: t.card, color: t.textMuted, fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "'Inter',sans-serif" };

    // Step 1 rebuilds the document from the template's fields. For edited
    // text that would replace the owner's words, so it opens the workspace.
    const openInWorkspace = () => { if (docId) { setDraftsOpen({ id: docId, at: Date.now() }); setFlowOrigin(null); setView("drafts"); } };
    const goTo = n => (n === 1 && textEdited ? openInWorkspace() : setStep(n));
    const reviseLabel = textEdited ? "Edit in workspace" : "Change answers";
    // Fixing what the send screen flags: in the workspace when the document
    // came from there (that is where its details are edited), else the step.
    const fixAt = n => (flowOrigin?.from === "drafts" ? backToDraft() : goTo(n));

    const pickDraft = spec => {
        if (!spec || draftingMode(spec) === "dedicated") return;
        setSelectedType(spec);
        setDocTitle(`${spec.label} draft`);
    };
    /* Proceed from the catalogue to drafting. Takes the spec when the caller
     * selects and proceeds in one action (the details panel): reading
     * `selectedType` there would see the selection from before this render. */
    const useTemplate = (spec, prefill = null) => {
        const chosen = spec || selectedType;
        if (!chosen) { toast.show("⚠️ Select a template first", "warn"); return; }
        setFlowOrigin(null);
        takePendingDocumentsView();
        if (draftingMode(chosen) === "dedicated") return;
        if (spec && spec.template_type !== selectedType?.template_type) pickDraft(spec);
        const typed = Object.fromEntries(Object.entries(prefill || {})
            .map(([k, v]) => [k, typeof v === "string" ? v.trim() : v])
            .filter(([, v]) => v));
        prefillRef.current = Object.keys(typed).length ? typed : null;
        setView("flow");
        setStep(1);
    };
    // `spec` is the catalogue entry, not a label. handleGenerate needs the
    // template_type the server keys builders by, and deriving it from a display
    // name is exactly the mapping step that used to send "Contract" to the NDA
    // builder.
    const pickType = spec => {
        setSelectedType(spec);
        setDocTitle(`${spec.label} draft`);
    };

    // The one fact the whole draft step depends on: is there a case to draft
    // from? handleGenerate resolves the id exactly this way, so the readiness
    // strip and the button can never disagree with what the handler will do.
    const activeCaseId = selection.activeCaseId || "";
    const activeCase = cases.find(c => (c._id || c.id) === activeCaseId);
    const activeCaseTitle = activeCase?.title || activeCase?.case_type || "your case";
    // Structured calculations cannot safely be collected as text. Those
    // builders stay visible but route to their deterministic calculator; they
    // are not passed arbitrary client-authored JSON by this generic form.
    const unsupportedType = draftingMode(selectedType) === "dedicated";
    // A document type MUST be chosen. Without this, an unset type used to fall
    // through to a civil plaint (see backendType below), silently handing the
    // user a real, filable plaint they never asked for.
    // `selection.canGenerate` already accounts for readiness, a real case and
    // the standalone sentinel — which is a non-empty string, so a plain
    // `Boolean(selectedCaseId)` read it as a case and reported Ready for a
    // selection generation refuses.
    const canGenerate = selection.canGenerate && Boolean(selectedType) && !unsupportedType;

    const handleGenerate = async (retryKey = null) => {
        const templateKey = selectedType?.template_type;
        if (!selectedType) {
            toast.show("⚠️ Choose a document type first", "warn"); return;
        }
        if (templateKey === null) {
            toast.show("⚠️ This document type is not yet supported by the AI", "warn"); return;
        }
        // ONE derivation of "the current case", shared with the resume hook and
        // the selector. There were three, and they could disagree: opening a
        // case-B document moved `genCaseId` to B while this still read the
        // selector, so extraction pulled case A's facts into a document
        // belonging to case B.
        const caseId = resumeCaseId;
        if (!caseId && !selection.isStandalone) {
            toast.show("⚠️ No case found — complete your legal intake first", "warn"); return;
        }
        // No fallback: an unmapped type is refused above, never coerced to a plaint.
        const backendType = templateKey;
        setGenerating(true); setGenPct(10); setGenDone(false);
        // Keep the last successful revision visible and addressable until its
        // replacement succeeds. Clearing the identity here made every
        // "Regenerate" create a second document and reduced version history to
        // a decorative one-row list.
        // A new extraction replaces the previous review outright. Keeping the
        // old rows would show the client fields read from a run they have
        // already abandoned.
        setReviewRows(null); setRawFields(null); setExtractNotice(null);
        setGenCaseId(caseId);
        // A NEW intent unless this is a retry of the one that just failed.
        // `retryKey` is passed only by the retry button, which reuses the key so
        // a render that already happened is replayed rather than repeated.
        generateKeyRef.current = asKey(retryKey) || idempotencyKey();
        setViewRev(null);   // a new draft is what the pane should show
        setDocIssue(null);

        try {
            // Case-backed templates with a reviewed prompt get AI assistance.
            // Everything else gets an honest manual form generated from the
            // builder's declared scalar fields. We never call an extractor the
            // backend says does not exist.
            let fields = {};
            if (caseId && draftingMode(selectedType) === "ai") {
                const extractRes = await extractDocumentFields(caseId, backendType);
                setGenPct(45);
                if (extractRes.error) {
                    toast.show("❌ " + (extractRes.error?.detail || "Field extraction failed"), "danger");
                    setGenerating(false); return;
                }
                fields = extractRes.data?.fields || {};
                setExtractNotice(extractionNotice(extractRes.data));
            } else {
                setGenPct(45);
            }

            // STOP HERE AND ASK.
            //
            // This used to fall straight through to rendering, so a model's
            // reading of a free-text case — the parties, the amounts, the dates
            // — became a legal document nobody had checked. The review that
            // follows generation looks at the finished PDF, and spotting a
            // wrong figure in three formatted pages is a different task from
            // seeing `demand: 500000` in a list.
            //
            // This is the last point where the mistake is cheap: after this it
            // is an immutable revision, and after submission it is in a
            // lawyer's queue.
            // What the client typed in Customize wins over what was read from
            // the case: they wrote it on purpose, for this document.
            if (prefillRef.current) fields = { ...fields, ...prefillRef.current };
            setRawFields(fields);
            setReviewRows(buildReviewRows(fields, selectedType?.fields || []));
            setGenerating(false);
            setGenPct(0);
            return;
        } catch (e) {
            setGenerating(false);
            toast.show("❌ " + (e?.message || "Could not read your case details"), "danger");
            return;
        }
    };

    /* The client has seen the fields and either accepted or corrected them.
     *
     * `toSubmittedFields` sends only what this template consumes and omits
     * blanks — an empty string is a value the renderer prints, where an absent
     * key lets `pleading_rules` report the field as missing, which is true. */
    const confirmFieldsAndGenerate = async (retryKey = null) => {
        const caseId = genCaseId ?? resumeCaseId;
        const backendType = selectedType?.template_type;
        if ((!caseId && !selection.isStandalone) || !backendType) return;

        const fields = toSubmittedFields(reviewRows || []);
        if (!Object.keys(fields).length) {
            setDocIssue({
                message: "Enter at least one document detail before generating.",
                retryable: false,
            });
            return;
        }
        setGenerating(true); setGenPct(55); setDocIssue(null);
        generateKeyRef.current = asKey(retryKey) || generateKeyRef.current || idempotencyKey();

        try {
            // Phase 2 — the revision itself.
            const viaV2 = await _generateViaV2({
                caseId, backendType, fields, key: generateKeyRef.current,
            });
            if (viaV2.unavailable) {
                // The flag is off. Legacy still renders a document; it simply
                // carries no revision id or hash, so the preview falls back to
                // "the current file" and the lawyer-side staleness guard has
                // nothing to check. That is the pre-V2 behaviour, unchanged.
                if (!caseId) {
                    setGenerating(false);
                    setDocIssue({
                        message: "Standalone drafting requires Documents V2. Link a case or enable V2 before generating this document.",
                        retryable: false,
                    });
                    return;
                }
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
                setDocumentIdentityTitle(genRes.data?.title || docTitle || null);
                setCompliance(genRes.data?.compliance || null);
                setVerification(genRes.data?.verification || null);
                setFieldShape(null);   // the legacy path produces no shape report
                setDocumentTemplateType(backendType);
            } else if (viaV2.error) {
                setGenerating(false);
                if (viaV2.issue?.code === "generation_failed") {
                    // The revision under this key FAILED and is final: replaying
                    // the same key returns the same failure forever. A retry is
                    // a new attempt, so the key is spent and Retry mints a new one.
                    generateKeyRef.current = null;
                    setDocIssue({ ...viaV2.issue, retryable: true });
                } else {
                    setDocIssue(viaV2.issue);
                }
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
                setDocumentTemplateType(backendType);
                setDocumentIdentityTitle(viaV2.title);
                setCompliance(viaV2.compliance || null);
                setVerification(viaV2.verification || null);
                setFieldShape(viaV2.fieldShape || null);
            }

            setGenPct(100);
            // Only a successful replacement restarts review. If extraction or
            // rendering fails, the returned/rejected state and lawyer note are
            // still true and must remain visible.
            setReviewSent(false); setReviewStatus(null); setLawyerNote(""); setUserApproved(false);
            // A new revision invalidates any submission intent formed against
            // the previous one — otherwise a retry of the old submit would send
            // a version the user is no longer looking at.
            submitKeyRef.current = null;
            // And the generate key is spent. Editing the fields and confirming
            // again is a NEW render; reusing this key returned the previous
            // revision (a PDF of the old answers) and is now refused as reuse.
            generateKeyRef.current = null;
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
        const requestedTitle = docTitle || `${selectedType?.label || "Document"} draft`;
        const canAppend = Boolean(docId
            && genCaseId === caseId
            && documentTemplateType === backendType
            && documentIdentityTitle === requestedTitle);
        let documentId = canAppend ? docId : null;

        if (!documentId) {
            const created = await createDocumentV2({
                templateType: backendType,
                title: requestedTitle,
                caseId,
            }, key);
            if (created.error) {
                if (created.status === 404 && errorCode(created.error) === "feature_disabled") {
                    return { unavailable: true };
                }
                return { error: true, issue: _v2Issue(created) };
            }
            documentId = created.data.id;
        }

        const rev = await generateRevisionV2(
            documentId, { fields, templateType: backendType }, key);
        if (rev.error) return { error: true, issue: _v2Issue(rev) };

        return {
            documentId,
            appended: canAppend,
            title: requestedTitle,
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

    /* A V2 failure the user must act on, on whichever step raised it.
     *
     * Not a toast: a draft that failed to generate, or a submission that did
     * not land, is something the user will otherwise assume succeeded. It was
     * rendered on step 2 only, while generation runs on step 1 — so a refused
     * generate cleared the spinner and showed nothing at all.
     *
     * `retry` receives the issue. It reuses the SAME key, so a request that did
     * reach the server before the connection dropped is replayed, not repeated. */
    const docIssueBanner = (retry) => docIssue && (
        <div style={{
            marginBottom: 12, padding: "10px 14px", borderRadius: 10,
            background: "#f59e0b14", border: "1px solid #f59e0b55",
            color: t.text, fontSize: 12.5,
            display: "flex", alignItems: "center", gap: 12,
        }}>
            <span style={{ flex: 1 }}>⚠ {docIssue.message}</span>
            {docIssue.retryable && (
                <button
                    onClick={() => { const issue = docIssue; setDocIssue(null); retry(issue); }}
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
    );

    /* ── Where the user is in the template flow ──
     *
     * The five-circle stepper at the top is gone: the documents screens have
     * their own header now. The step is still said in words, next to the way
     * back to the Documents home. */
    const STEP_LABELS = ["Templates", "Draft details", "Review", "Send to lawyer", "Final & export"];
    const isMobile = useIsMobile();
    /* The approved design's header (2026-10-07): a way back, the document, and
     * a progress rail — no "Step x of 4" pill and no Back/Continue pair. Every
     * step carries its own forward action (Review Draft, Send to a lawyer, Send
     * for review, View Final Version) and its own way back, so the pair only
     * duplicated them. The send screen has the mockup's own header. */
    const sendScreen = step === 3 && !reviewSent;
    const linkBtn = { background: "none", border: "none", color: t.primary, fontSize: 14, cursor: "pointer", padding: "6px 2px", fontFamily: "'Inter',sans-serif" };
    const flowHeader = step > 0 && (sendScreen ? (
        <div data-flow-header="send" style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap", paddingBottom: 18 }}>
            <button type="button" onClick={() => fixAt(2)} style={linkBtn}>← Back to draft</button>
            <h1 style={{ margin: 0, fontFamily: SERIF, fontSize: 26, fontWeight: 600, color: t.text }}>Send for lawyer review</h1>
        </div>
    ) : (
        <div data-flow-header style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", paddingBottom: 18 }}>
            <button type="button" onClick={() => startNewDocument()} style={linkBtn}>← Documents</button>
            <span style={{ color: t.textMuted }}>/</span>
            <span style={{ fontSize: 15, fontWeight: 700, color: t.text }}>{selectedType?.label || docTitle || "Document"}</span>
            <div style={{ flex: 1 }} />
            <ol aria-label="Progress" style={{ display: "flex", alignItems: "center", gap: 12, listStyle: "none", margin: 0, padding: 0, fontSize: 12.5, flexWrap: "wrap" }}>
                {STEP_LABELS.slice(1).map((label, i) => {
                    const n = i + 1, done = n < step, current = n === step;
                    return (
                        <li key={label} aria-current={current ? "step" : undefined}
                            style={{ color: done ? t.success : current ? t.text : t.textMuted, fontWeight: current ? 700 : 500 }}>
                            {done ? "✓ " : `${n}. `}{label}
                        </li>
                    );
                })}
            </ol>
        </div>
    ));


    /* ── Shared pieces of the flow steps (mockup workspace layout) ── */
    const STATUS_TONE = { info: "info", ok: "low", warn: "medium", danger: "high", muted: "muted" };
    const workspaceGrid = { display: "grid", gridTemplateColumns: isMobile ? "minmax(0,1fr)" : "minmax(0,1fr) 360px", gap: 18, alignItems: "start" };
    const sidePanel = { display: "flex", flexDirection: "column", gap: 14, position: isMobile ? "static" : "sticky", top: 0 };
    const panelCard = { background: t.card, border: `1px solid ${t.border}`, borderRadius: 16, padding: 16 };
    const selectStyle = { background: t.inputBg, border: `1px solid ${t.border}`, color: t.text, borderRadius: 10, padding: "10px 12px", width: "100%", outline: "none", fontSize: 13.5, fontFamily: "'Inter',sans-serif" };
    const docPane = children => (
        <div style={{ borderRadius: 16, background: t.mode === "dark" ? "rgba(0,0,0,0.22)" : "rgba(26,46,53,0.05)", border: `1px solid ${t.border}`, padding: isMobile ? 8 : 18, display: "flex", justifyContent: "center" }}>
            {children}
        </div>
    );
    // The PDF itself, as tall as the screen allows — a 460px letterbox hid
    // most of every page.
    const pdfFrame = (title, emptyText) => (previewUrl ? (
        <iframe title={title} src={previewUrl} style={{ width: "100%", height: "max(520px, calc(100vh - 230px))", border: "none", display: "block", borderRadius: 8, background: "#fff" }} />
    ) : (
        <div style={{ width: "100%", minHeight: 420, display: "flex", alignItems: "center", justifyContent: "center", padding: 40, boxSizing: "border-box", textAlign: "center", color: t.textMuted, fontSize: 13.5, background: t.card, borderRadius: 8 }}>
            {previewIssue || emptyText}
        </div>
    ));
    // Before generation: the document's outline, filled live from the review
    // rows — values in green, what is still missing as a marked placeholder.
    const paperRows = reviewRows
        ? reviewRows.filter(r => r.used)
        : (selectedType?.fields || []).filter(f => !(selectedType?.structured_fields || []).includes(f))
            .map(name => ({ name, label: humaniseField(name), value: "" }));
    const fieldsPaper = (
        <Paper title={(selectedType?.label || "Your document").toUpperCase()} width={640}>
            {selectedType?.description && <p style={{ margin: "0 0 14px" }}>{selectedType.description}</p>}
            {paperRows.map(r => (
                <p key={r.name} style={{ margin: "0 0 8px" }}>
                    <b>{r.label}: </b>
                    {String(r.value || "").trim()
                        ? <span style={VALUE_STYLE}>{r.value}</span>
                        : <span style={TOKEN_STYLE}>{r.label}</span>}
                </p>
            ))}
            <p style={{ margin: "16px 0 0", fontFamily: "'Inter',sans-serif", fontSize: 12, color: "#5b6b6f" }}>
                {reviewRows ? "Check each detail on the right, then generate the PDF." : "Press Generate Draft to fill these details."}
            </p>
        </Paper>
    );
    const checkRow = (label, badge) => (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, padding: "10px 12px", borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}` }}>
            <span style={{ fontSize: 13, color: t.text }}>{label}</span>{badge}
        </div>
    );

    const backHome = () => { startNewDocument(); setView("flow"); };
    const frame = content => (
        <ThemeCtx.Provider value={t}>
            <div data-docs-font style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", background: t.bg, color: t.text }}>
                <style>{DOCS_FONT_CSS}</style>
                {content}
            </div>
        </ThemeCtx.Provider>
    );
    if (view === "drafts") {
        return frame(<DocsDrafts seed={draftsSeed} templates={templates} cases={cases} onBack={backHome}
            onOpenView={v => setView(v)} openDocument={draftsOpen} />);
        // (Sending is done in the workspace's own send panel since 2026-10-08;
        // the drafting workspace no longer hands a document to the guided flow.)
    }
    if (view === "vault") {
        // Open from the Vault edits in the AI drafting workspace -- one editor
        // for a document, wherever it is opened from. (The guided flow stays
        // for building a document from a template.)
        return frame(<DocsVault onBack={backHome} reviewLink={reviewLink} previewId={vaultPreviewId}
            onEdit={id => { setDraftsOpen({ id, at: Date.now() }); setFlowOrigin(null); setView("drafts"); }} />);
    }

    return frame(
        <div data-lenis-prevent style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: isMobile ? "60px 14px 20px" : "30px 40px 32px", boxSizing: "border-box" }}>
            {flowHeader}

            <div style={{ paddingBottom: 8 }} className="aFadeUp" key={step}>

                {/* ════════════════════════════════════════════════
            STEP 1 — Template Selection (full width)
        ════════════════════════════════════════════════ */}
                {step === 0 && (
                    <div>
                        <DocumentsHome
                            templates={templates}
                            templateIssue={templateIssue}
                            cases={cases}
                            draftingMode={draftingMode}
                            dedicatedToolHref={dedicatedToolHref}
                            onUse={useTemplate}
                            onPlan={seed => { setDraftsSeed({ ...seed, at: Date.now() }); setView("drafts"); }}
                            onOpenView={v => setView(v)}
                            continueSlot={(
                                <>
                        {/* EVERY DOCUMENT THIS CLIENT OWNS, on the dashboard.
                            It was first placed inside the step-3 review pane,
                            which is only reachable part-way through creating a
                            NEW document — so the history of old ones was behind
                            the flow you would use precisely because you could
                            not find them. A mounted test caught it; nothing
                            about the source looked wrong. */}
                        <div id="my-documents" style={{ scrollMarginTop: 12 }}>
                            <MyDocumentsPanel
                                t={t}
                                onOpen={restored => {
                                    setViewRev(null);
                                    applyRestored(restored);
                                }}
                                onPreview={async (id, actions) => {
                                    // OPEN IT FIRST. This used to take the row's
                                    // document id and ignore it, then pin the
                                    // revision — while the preview effect asked
                                    // for whatever document was already open. The
                                    // request therefore carried one document's id
                                    // with another document's revision: a pair
                                    // belonging to no document at all, saved from
                                    // showing the wrong bytes only by the hash
                                    // guard rejecting it.
                                    if (id && id !== docId) {
                                        const { data, error } = await getDocumentV2(id);
                                        if (error || !data) return { error: error || new Error("Could not open that document.") };
                                        const restored = restoreStateFromDocument(data);
                                        if (!restored) return { error: new Error("That document response was incomplete.") };
                                        applyRestored(restored);
                                    }
                                    setViewRev({
                                        revision_id: actions.revisionId,
                                        pdf_sha256: actions.pdfSha256,
                                    });
                                    return { error: null };
                                }} />
                        </div>

                                </>
                            )} />
                    </div>
                )}

                {/* ════════════════════════════════════════════════
            STEP 2 — Draft details (workspace: document + panel)
        ════════════════════════════════════════════════ */}
                {step === 1 && (
                    <div style={workspaceGrid}>
                        <div>{genDone && docId
                            ? docPane(pdfFrame("Document preview", "Loading document preview…"))
                            : docPane(fieldsPaper)}</div>

                        <div style={sidePanel}>
                            <div style={panelCard}>
                                <div style={{ fontSize: 15, fontWeight: 700, color: t.text, marginBottom: 12 }}>Draft details</div>
                                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                                    <div>
                                        <Lbl>Document Type</Lbl>
                                        {templates === null ? (
                                            <div style={{ fontSize: 12.5, color: t.textMuted, padding: "10px 0" }}>
                                                Loading the available documents…
                                            </div>
                                        ) : templateIssue ? (
                                            <div style={{ fontSize: 12.5, color: t.warn, padding: "10px 13px", borderRadius: 10, background: `${t.warn}12`, border: `1px solid ${t.warn}35` }}>
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
                                                    style={selectStyle}>
                                                    <option value="">Select a document type…</option>
                                                    {_byCategory(templates).map(([category, items]) => (
                                                        <optgroup key={category} label={category}>
                                                            {items.map(spec => (
                                                                <option key={spec.template_type} value={spec.template_type} disabled={draftingMode(spec) === "dedicated"}>
                                                                    {spec.label}{draftingMode(spec) === "dedicated" ? " — dedicated calculator" : ""}
                                                                </option>
                                                            ))}
                                                        </optgroup>
                                                    ))}
                                                </select>
                                                {/* The server's own description of what this
                                                    builder emits: several are narrower than their
                                                    name suggests, and the user must read that
                                                    BEFORE drafting, not after filing. */}
                                                {selectedType?.description && (
                                                    <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6, marginTop: 7 }}>
                                                        {selectedType.description}
                                                    </div>
                                                )}
                                                {unsupportedType && (
                                                    <a href={dedicatedToolHref(selectedType)} style={{ display: "inline-block", marginTop: 8, color: t.primary, fontSize: 12, fontWeight: 700 }}>
                                                        Open the dedicated calculator →
                                                    </a>
                                                )}
                                            </>
                                        )}
                                    </div>
                                    <div><Lbl>Document Title</Lbl><ThemedInput value={docTitle} onChange={e => setDocTitle(e.target.value)} placeholder={selectedType ? `${selectedType.label} draft` : "Choose a document type"} /></div>
                                    <div>
                                        <Lbl>Linked Case</Lbl>
                                        <select value={selectedCaseId} onChange={e => setSelectedCaseId(e.target.value)} style={selectStyle}>
                                            <option value="">Select a case…</option>
                                            <option value={NO_CASE}>Standalone — no linked case</option>
                                            {cases.map(c => <option key={c._id || c.id} value={c._id || c.id}>{c.title || c.case_type || (c._id || c.id)}</option>)}
                                        </select>
                                        {selection.isStandalone && (
                                            <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 5 }}>No case facts will be read automatically; you will enter the document details yourself.</div>
                                        )}
                                    </div>
                                </div>

                                {/* Readiness strip — reflects real state, never a
                                    hardcoded "Ready": a panel that asserts state it
                                    never checks turns a working feature into a dead
                                    button. */}
                                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", padding: "10px 12px", borderRadius: 10, background: canGenerate ? t.primaryGlow2 : t.inputBg, border: `1px solid ${canGenerate ? t.primary + "40" : t.border}`, marginTop: 14 }}>
                                    <div style={{ width: 8, height: 8, borderRadius: "50%", background: canGenerate ? t.success : t.warn, flexShrink: 0 }} />
                                    <span style={{ fontSize: 12, color: t.textMuted, flex: 1, minWidth: 160 }}>
                                        {canGenerate
                                            ? (selection.isStandalone ? "Standalone · ready to draft" : `Linked to "${activeCaseTitle}" · ready to draft`)
                                            : selection.blockedReason === "loading"
                                            ? "Loading your cases…"
                                            : selection.blockedReason === "standalone_unsupported"
                                            ? "Documents drafted here are always linked to a case. Choose one above."
                                            : casesError
                                            ? (casesReloading
                                                ? "Trying your cases again…"
                                                : "We could not load your cases. This does not mean they are gone — only that we could not reach them just now.")
                                            : "No case linked yet — complete your Legal Intake first, or draft standalone."}
                                    </span>
                                    {/* A way out of the error: `reloadCases` touches the
                                        case list alone, so the draft on screen survives. */}
                                    {casesError && (
                                        <button
                                            onClick={() => reloadCases()}
                                            disabled={casesReloading}
                                            style={{ padding: "5px 11px", borderRadius: 9, border: `1px solid ${t.border}`, background: "transparent", color: t.text, fontSize: 11.5, fontWeight: 600, cursor: casesReloading ? "default" : "pointer", fontFamily: "'Inter',sans-serif", opacity: casesReloading ? 0.6 : 1, whiteSpace: "nowrap" }}>
                                            {casesReloading ? "Retrying…" : "Try again"}
                                        </button>
                                    )}
                                    <Badge type={canGenerate ? "success" : "warn"}>{canGenerate ? "✓ Ready" : "Not ready"}</Badge>
                                </div>
                            </div>

                            {/* THE EXTRACTION, BEFORE IT BECOMES A DOCUMENT —
                                the last point where a wrong name or amount is a
                                two-second fix rather than a new revision. */}
                            {reviewRows && !genDone && (
                                <div style={panelCard}>
                                    {/* The same fields retry under the same key. */}
                                    {docIssueBanner(() => confirmFieldsAndGenerate(generateKeyRef.current))}
                                    {extractNotice && (
                                        <div role="status" data-extraction={extractNotice.kind} style={{
                                            marginBottom: 12, padding: "10px 14px", borderRadius: 10,
                                            background: "#f59e0b14", border: "1px solid #f59e0b55",
                                            color: t.text, fontSize: 12.5, lineHeight: 1.55,
                                        }}>
                                            ⚠ {extractNotice.message}
                                        </div>
                                    )}
                                    <FieldReview
                                        t={t}
                                        source={genCaseId && draftingMode(selectedType) === "ai" ? "ai" : "manual"}
                                        rows={reviewRows}
                                        missing={missingFields(reviewRows)}
                                        edited={hasEdits(reviewRows, rawFields)}
                                        busy={generating}
                                        onEdit={(name, value) => {
                                            // Changed fields are a NEW render. The key of a
                                            // failed attempt would be refused as reuse (409).
                                            generateKeyRef.current = null;
                                            setDocIssue(null);
                                            setReviewRows(rows => editRow(rows, name, value));
                                        }}
                                        onGenerate={() => confirmFieldsAndGenerate()}
                                        onBack={() => { setReviewRows(null); setRawFields(null); }} />
                                </div>
                            )}

                            {(generating || genDone) && (
                                <div style={panelCard}>
                                    <div style={{ height: 6, borderRadius: 6, background: t.inputBg, overflow: "hidden", marginBottom: 6 }}>
                                        <div style={{ height: "100%", background: t.primary, borderRadius: 6, width: `${genPct}%`, transition: "width 0.4s ease" }} />
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: t.textMuted }}>
                                        <span>{genDone ? "✅ Draft created successfully" : GEN_STEPS[Math.min(Math.floor(genPct / 20), 4)]}</span>
                                        <span>{genPct}%</span>
                                    </div>
                                </div>
                            )}

                            {/* A value that went nowhere: the document rendered an
                                empty line where the user believes they supplied
                                something. Shown before any verdict. */}
                            {genDone && fieldShape?.unknown?.length > 0 && (
                                <div style={{ padding: "11px 14px", borderRadius: 12, background: `${t.warn}12`, border: `1.5px solid ${t.warn}45` }}>
                                    <div style={{ fontSize: 13, fontWeight: 700, color: t.warn, marginBottom: 4 }}>
                                        {fieldShape.unknown.length} answer{fieldShape.unknown.length === 1 ? " was" : "s were"} not used
                                    </div>
                                    <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6 }}>
                                        This document type does not have {fieldShape.unknown.length === 1 ? "a field" : "fields"} called{" "}
                                        {fieldShape.unknown.join(", ")}. Whatever was entered there is
                                        not in the draft — check the document before submitting it.
                                    </div>
                                </div>
                            )}

                            {genDone && compliance?.checked && (
                                <div style={{ padding: 14, borderRadius: 12, background: compliance.complete ? `${t.success}12` : `${t.warn}12`, border: `1.5px solid ${compliance.complete ? t.success : t.warn}45` }}>
                                    <div style={{ fontSize: 13, fontWeight: 700, color: compliance.complete ? t.success : t.warn, marginBottom: 6 }}>
                                        {compliance.complete
                                            ? "✓ Contains every particular the Code requires"
                                            : `${compliance.missing} required particular${compliance.missing === 1 ? "" : "s"} missing`}
                                    </div>
                                    <div style={{ fontSize: 11.5, color: t.textMuted, marginBottom: compliance.complete ? 0 : 9 }}>Checked against {compliance.basis}</div>
                                    {compliance.items.filter(i => i.status === "missing").map(i => (
                                        <div key={i.clause} style={{ marginBottom: 8, paddingLeft: 10, borderLeft: `2px solid ${t.warn}55` }}>
                                            <div style={{ fontSize: 12, color: t.text, fontWeight: 600 }}>{i.clause} — {i.requirement}</div>
                                            <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 2 }}>{i.hint}</div>
                                        </div>
                                    ))}
                                    <div style={{ fontSize: 11, color: t.textMuted, marginTop: 6, fontStyle: "italic" }}>{compliance.advisory}</div>
                                </div>
                            )}

                            {/* Citation verification. Never a bare green tick: it
                                checks existence only, so the "cannot check" count
                                is always shown next to the verified one. */}
                            {genDone && verification && (
                                <div style={{ padding: 14, borderRadius: 12,
                                    background: (verification.counts?.not_in_corpus > 0 || verification.counts?.omitted > 0) ? `${t.danger}12` : `${t.textMuted}0e`,
                                    border: `1.5px solid ${(verification.counts?.not_in_corpus > 0 || verification.counts?.omitted > 0) ? `${t.danger}55` : `${t.textMuted}33`}` }}>
                                    <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6,
                                        color: (verification.counts?.not_in_corpus > 0 || verification.counts?.omitted > 0) ? t.danger : t.text }}>
                                        {verification.ran === false
                                            ? "Citations were not checked"
                                            : verification.counts?.omitted > 0
                                                ? `${verification.counts.omitted} REPEALED section${verification.counts.omitted === 1 ? "" : "s"} cited`
                                                : verification.counts?.not_in_corpus > 0
                                                    ? `${verification.counts.not_in_corpus} citation${verification.counts.not_in_corpus === 1 ? "" : "s"} could not be found in the statute`
                                                    : verification.counts?.total === 0
                                                        ? "No citations found to check"
                                                        : "Citations checked for existence"}
                                    </div>
                                    {verification.ran === false ? (
                                        <div style={{ fontSize: 12, color: t.textMuted }}>{verification.summary}</div>
                                    ) : (
                                        <>
                                            <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 9 }}>
                                                {verification.counts?.verified || 0} found in the corpus ·{" "}
                                                {verification.counts?.omitted > 0 && <>{verification.counts.omitted} repealed · </>}
                                                {verification.counts?.unverifiable || 0} this corpus cannot check
                                            </div>
                                            {(verification.checks || [])
                                                .filter(c => c.status !== "VERIFIED")
                                                .map((c, i) => (
                                                    <div key={`${c.canonical}-${i}`} style={{ marginBottom: 8, paddingLeft: 10,
                                                        borderLeft: `2px solid ${(c.status === "NOT_IN_CORPUS" || c.status === "OMITTED") ? `${t.danger}66` : `${t.textMuted}44`}` }}>
                                                        <div style={{ fontSize: 12, fontWeight: 600, color: (c.status === "NOT_IN_CORPUS" || c.status === "OMITTED") ? t.danger : t.text }}>
                                                            {c.canonical}
                                                            <span style={{ fontWeight: 500, color: t.textMuted }}>
                                                                {c.status === "OMITTED" ? " — REPEALED" : c.status === "NOT_IN_CORPUS" ? " — not found" : " — cannot verify"}
                                                            </span>
                                                        </div>
                                                        <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 2 }}>{c.detail}</div>
                                                    </div>
                                                ))}
                                        </>
                                    )}
                                    <div style={{ fontSize: 11, color: t.textMuted, marginTop: 6, fontStyle: "italic" }}>
                                        Existence only — a real provision cited for something it does not
                                        say still shows as found. Read every authority before filing.
                                    </div>
                                    {/* The adopted scope statement, shipped from the backend. */}
                                    {verification.scope && (
                                        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 8, paddingTop: 8, borderTop: `1px solid ${t.textMuted}22`, lineHeight: 1.5 }}>
                                            {verification.scope}
                                        </div>
                                    )}
                                </div>
                            )}

                            {!genDone ? (
                                <Btn kind="primary" onClick={() => handleGenerate()} disabled={generating || !canGenerate} style={{ width: "100%", minHeight: 46 }}>
                                    {generating
                                        ? "⏳ Generating…"
                                        : !selection.canGenerate
                                            ? "Choose a case or standalone drafting"
                                            : unsupportedType
                                                ? `${selectedType?.label} isn't supported yet`
                                                : "✨ Generate Draft"}
                                </Btn>
                            ) : (
                                <div style={{ display: "flex", gap: 8 }}>
                                    <Btn onClick={() => { setGenDone(false); setGenPct(0); }} style={{ flex: 1 }}>🔄 Regenerate</Btn>
                                    <Btn kind="primary" onClick={() => { goTo(2); }} style={{ flex: 2 }}>Review Draft →</Btn>
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {/* ════════════════════════════════════════════════
            STEP 3 — Review (workspace: the real PDF + checks)
        ════════════════════════════════════════════════ */}
                {step === 2 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                            <Pill tone="info">{selectedType?.label || "Document"}</Pill>
                            <Pill tone={STATUS_TONE[statusView.tone] || "muted"}>{docStatus}</Pill>
                            {docVersion != null && <Pill tone="muted">Version {docVersion}</Pill>}
                            <span style={{ flex: 1 }} />
                            {/* "Change answers", not "Edit": THE DOCUMENT IS A PDF.
                                Changing the answers and regenerating IS the edit,
                                and it maps onto how the document is versioned. */}
                            <Btn onClick={() => goTo(1)} data-change-answers title={textEdited ? "This document's wording was edited: keep editing it as text" : "Go back and change your answers, then regenerate"} style={{ minHeight: 38 }}>✏️ {reviseLabel}</Btn>
                            <Btn onClick={() => { if (docId) { downloadDocumentFile(docId, docTitle || "document", {
                                    revisionId: viewRev?.revision_id || docRevisionId,
                                    expectedPdfSha256: viewRev?.pdf_sha256 || docPdfSha256,
                                }); } else { toast.show("⚠️ Generate the document first", "warn"); } }} style={{ minHeight: 38 }}>📥 Download</Btn>
                        </div>

                        <div style={workspaceGrid}>
                            <div>
                                {/* A client who believes a lawyer has their document
                                    waits for a reply nobody is going to send. */}
                                {docIssueBanner(issue => {
                                    if (issue.onRetry === "withdraw") withdrawFromReview(withdrawKeyRef.current);
                                    else if (docId) submitToLawyer(submitKeyRef.current);
                                    else handleGenerate(generateKeyRef.current);
                                })}
                                {viewRev && (
                                    <div style={{ marginBottom: 10, padding: "9px 12px", borderRadius: 10, background: `${t.warn}12`, border: `1px solid ${t.warn}35`, fontSize: 12.5, color: t.text, display: "flex", alignItems: "center", gap: 10 }}>
                                        <span style={{ flex: 1 }}>
                                            Showing an earlier version (v{viewRev.version}). Submitting still sends the latest.
                                        </span>
                                        <Btn onClick={() => setViewRev(null)} style={{ minHeight: 32, fontSize: 12 }}>Back to latest</Btn>
                                    </div>
                                )}
                                {docPane(pdfFrame("Document preview", docId ? "Loading document preview…" : "Generate the document to preview it here."))}
                            </div>

                            <div style={sidePanel}>
                                {/* Compliance — REAL records frozen at generation,
                                    never a hardcoded "Verified". */}
                                <div style={panelCard}>
                                    <div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>Checks</div>
                                    <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 12 }}>Frozen when this version was generated</div>
                                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                                        {checkRow("Statutory particulars", compliance?.checked
                                            ? <Badge type={compliance.complete ? "success" : "warn"}>{compliance.complete ? "✓ Complete" : `${compliance.missing} missing`}</Badge>
                                            : <Badge type="gray">Not encoded</Badge>)}
                                        {/* One set of rules for every citation display
                                            (lib/draftVerification.js). */}
                                        {checkRow("Citation check", verification
                                            ? (() => { const v = verificationView(verification);
                                                return <Badge type={_CITATION_BADGE[v.tone]}>{v.tone === "ok" ? "✓ " : ""}{v.headline}</Badge>; })()
                                            : <Badge type="gray">—</Badge>)}
                                    </div>
                                    <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 10, fontStyle: "italic" }}>
                                        Existence only — read every authority before filing. A lawyer must review this.
                                    </div>
                                </div>

                                <div style={panelCard}>
                                    <div style={{ fontSize: 15, fontWeight: 700, color: t.text, marginBottom: 10 }}>Your review</div>
                                    <div style={{ padding: "12px", borderRadius: 12, background: userApproved ? `${t.success}12` : t.inputBg, border: `1px solid ${userApproved ? t.success : t.border}`, marginBottom: 10 }}>
                                        <div style={{ fontSize: 13, fontWeight: 600, color: userApproved ? t.success : t.text }}>{userApproved ? "✅ Approved by you" : "👀 Awaiting your review"}</div>
                                        <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>{userApproved ? "Ready to send to a lawyer" : "Read the document, then approve it or change your answers"}</div>
                                    </div>
                                    {!userApproved ? (
                                        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                                            <Btn kind="primary" onClick={() => { setUserApproved(true); toast.show("Marked as approved by you. Send it to a lawyer for their review.", "success", 4000); }}>✅ Approve Draft</Btn>
                                            <Btn onClick={() => goTo(1)}>✏️ {reviseLabel}</Btn>
                                        </div>
                                    ) : (
                                        <Btn kind="primary" onClick={() => goTo(3)} style={{ width: "100%" }}>⚖️ Send to a lawyer →</Btn>
                                    )}
                                </div>

                                <div style={panelCard}>
                                    {/* The rows are drawn HERE, by the client: RevisionHistory
                                        keeps the data and which version is current, and its
                                        default look belongs to the lawyer screens. */}
                                    <RevisionHistory
                                        heading={<div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: t.textMuted, margin: "14px 0 8px" }}>Version history</div>}
                                        docId={docId} t={t} reloadKey={docRevisionId}
                                        currentRevisionId={viewRev?.revision_id || docRevisionId}
                                        onPreview={rev => setViewRev(
                                            rev.revision_id === docRevisionId ? null : rev)}
                                        renderRow={(rev, { isCurrent, failed, verdict }) => (
                                            <div key={rev.revision_id} data-client-version={rev.version}
                                                onClick={() => !failed && setViewRev(rev.revision_id === docRevisionId ? null : rev)}
                                                style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 9px", borderRadius: 8, marginBottom: 3,
                                                    cursor: failed ? "default" : "pointer", opacity: failed ? 0.6 : 1,
                                                    background: isCurrent ? t.primaryGlow : "transparent", border: `1px solid ${isCurrent ? `${t.primary}40` : "transparent"}` }}>
                                                <span style={{ fontSize: 11.5, fontWeight: 700, color: isCurrent ? t.primary : t.text, minWidth: 30 }}>v{rev.version}</span>
                                                <span style={{ flex: 1, fontSize: 11.5, color: t.textMuted }}>{verdict}</span>
                                                {isCurrent && <span style={{ fontSize: 10, fontWeight: 700, color: t.primary }}>CURRENT</span>}
                                            </div>
                                        )} />
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* ════════════════════════════════════════════════
            STEP 4 — Send for lawyer review (mockup screen 4)
        ════════════════════════════════════════════════ */}
                {step === 3 && !reviewSent && (() => {
                    const chosen = revLawyers.find(x => x._id === selLawyer);
                    const lawyerName = chosen?.name || (caseLawyerId ? "your case lawyer" : null);
                    const cv = verification ? verificationView(verification) : null;
                    const ready = [
                        { ok: Boolean(docId), label: "Draft generated", sub: docId ? `Version ${docVersion ?? 1}` : "Generate it first", fix: 1 },
                        // Approved here, in place: a trip back to the review step
                        // only to press one button was the old flow's detour.
                        { ok: userApproved, label: "Approved by you", sub: userApproved ? "You read and approved it" : "You have read the draft and it is right", approve: true },
                        compliance?.checked
                            ? { ok: compliance.complete, label: "Required particulars", sub: compliance.complete ? "Every particular is present" : `${compliance.missing} missing`, fix: 1 }
                            : { ok: null, label: "Required particulars", sub: "Not encoded for this document type" },
                        cv ? { ok: cv.tone === "ok" ? true : cv.tone === "neutral" ? null : false, label: "Citations", sub: cv.headline } : null,
                    ].filter(Boolean);
                    const notes = ["Check the amounts", "Check the dates and deadlines", "Is this enforceable?", "Explain it in plain words"];
                    const stepLbl = (n, text) => <Label style={{ marginBottom: 10 }}>{n} · {text}</Label>;
                    return (
                        <div style={{ display: "grid", gridTemplateColumns: isMobile ? "minmax(0,1fr)" : "minmax(280px,380px) minmax(0,1fr)", gap: 18, alignItems: "start" }}>
                            <div style={sidePanel}>
                                <div style={{ ...panelCard, display: "flex", gap: 12, alignItems: "center" }}>
                                    <div style={{ width: 42, height: 50, borderRadius: 8, background: "#fdecec", color: "#b3261e", fontSize: 10, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>PDF</div>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ fontSize: 14.5, fontWeight: 700, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{docTitle || selectedType?.label || "Your document"}</div>
                                        <div style={{ fontSize: 12, color: t.textMuted }}>{selectedType?.label || "—"}{docVersion != null ? ` · v${docVersion}` : ""}</div>
                                    </div>
                                </div>
                                <div style={panelCard}>
                                    <div style={{ fontSize: 15, fontWeight: 700, color: t.text, marginBottom: 10 }}>Ready to send?</div>
                                    {ready.map(r => (
                                        <div key={r.label} style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "8px 0", borderTop: `1px solid ${t.border}` }}>
                                            <span aria-hidden="true" style={{ width: 22, height: 22, borderRadius: "50%", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 800, background: r.ok === true ? `${t.success}25` : r.ok === false ? `${t.warn}25` : t.inputBg, color: r.ok === true ? t.success : r.ok === false ? t.warn : t.textMuted }}>{r.ok === true ? "✓" : r.ok === false ? "!" : "–"}</span>
                                            <div style={{ flex: 1 }}>
                                                <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{r.label}</div>
                                                <div style={{ fontSize: 12, color: t.textMuted }}>{r.sub}</div>
                                            </div>
                                            {r.ok === false && r.approve && (
                                                <button type="button" data-approve-draft onClick={() => setUserApproved(true)} style={{ background: "none", border: "none", color: t.primary, fontWeight: 700, fontSize: 12.5, cursor: "pointer" }}>Approve</button>
                                            )}
                                            {r.ok === false && r.fix != null && (
                                                <button type="button" onClick={() => fixAt(r.fix)} style={{ background: "none", border: "none", color: t.primary, fontWeight: 700, fontSize: 12.5, cursor: "pointer" }}>Fix</button>
                                            )}
                                        </div>
                                    ))}
                                </div>
                                <div style={{ ...panelCard, background: "transparent", borderStyle: "dashed", fontSize: 13, color: t.textMuted, lineHeight: 1.6 }}>
                                    <b style={{ color: t.text }}>Don't need a lawyer?</b> The draft can be downloaded as it is — it stays marked as not reviewed.{" "}
                                    <button type="button" data-download-draft disabled={!docId} onClick={() => downloadDocumentFile(docId, docTitle || "document", {
                                            revisionId: docRevisionId, expectedPdfSha256: docPdfSha256 })}
                                        style={{ background: "none", border: "none", padding: 0, color: t.primary, fontWeight: 700, textDecoration: "underline", cursor: docId ? "pointer" : "default", fontSize: 13, fontFamily: "'Inter',sans-serif" }}>
                                        Download draft
                                    </button>
                                </div>
                            </div>

                            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                                <div style={panelCard}>
                                    {stepLbl(1, caseLawyerId ? "Your case lawyer" : "Choose a lawyer")}
                                    <div role="radiogroup" aria-label="Reviewing lawyer" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                                        {caseLawyerId && (
                                            <div style={{ fontSize: 12, color: t.textMuted, padding: "8px 12px", borderRadius: 10, background: t.primaryGlow2, lineHeight: 1.55 }}>
                                                This case already has an engaged lawyer — documents for it are reviewed by them.
                                            </div>
                                        )}
                                        {(caseLawyerId ? revLawyers.filter(l => l._id === caseLawyerId) : revLawyers).map(l => {
                                            const on = selLawyer === l._id;
                                            return (
                                                <button key={l._id} type="button" role="radio" aria-checked={on} onClick={() => setSelLawyer(l._id)}
                                                    style={{ display: "flex", alignItems: "center", gap: 12, width: "100%", textAlign: "left", padding: "12px 14px", borderRadius: 12, border: `1.5px solid ${on ? t.primary : t.border}`, background: on ? t.primaryGlow2 : t.inputBg, cursor: "pointer", color: t.text, fontFamily: "'Inter',sans-serif" }}>
                                                    <span style={{ width: 40, height: 40, borderRadius: "50%", background: on ? t.primary : t.primaryGlow2, color: on ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 800, flexShrink: 0 }}>{l.avatar}</span>
                                                    <span style={{ flex: 1, minWidth: 0 }}>
                                                        <span style={{ display: "block", fontSize: 14, fontWeight: 700 }}>{l.name}</span>
                                                        <span style={{ display: "block", fontSize: 12, color: t.textMuted }}>{l.spec}</span>
                                                    </span>

                                                </button>
                                            );
                                        })}
                                        {caseLawyerId && !revLawyers.some(l => l._id === caseLawyerId) && (
                                            <div style={{ padding: "12px 14px", borderRadius: 12, border: `1.5px solid ${t.primary}`, background: t.primaryGlow2, fontSize: 14, fontWeight: 700, color: t.text }}>⚖️ Your engaged case lawyer</div>
                                        )}
                                        {!caseLawyerId && !revLawyers.length && !revLawyersLoaded && (
                                            <div style={{ fontSize: 12.5, color: t.textMuted, textAlign: "center", padding: "18px 0" }}>Loading your lawyers…</div>
                                        )}
                                        {!caseLawyerId && !revLawyers.length && revLawyersLoaded && (
                                            <div data-no-engaged-lawyer role="note" style={{ fontSize: 13, color: t.textMuted, textAlign: "center", padding: "18px 8px", lineHeight: 1.55 }}>
                                                You have no lawyer engaged yet. A document can be sent only to a lawyer you have hired — hire a lawyer first, then send it for review.
                                            </div>
                                        )}
                                    </div>
                                </div>

                                <div style={panelCard}>
                                    {stepLbl(2, "How soon?")}
                                    <div role="radiogroup" aria-label="Urgency" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                        {[["Normal", "No rush", t.success], ["Priority", "Needed soon", t.warn], ["Urgent", "Time-critical", t.danger]].map(([lvl, desc, col]) => (
                                            <button key={lvl} type="button" role="radio" aria-checked={urgency === lvl} onClick={() => setUrgency(lvl)}
                                                style={{ flex: "1 1 120px", padding: "10px 12px", borderRadius: 10, border: `1.5px solid ${urgency === lvl ? col : t.border}`, background: urgency === lvl ? `${col}14` : t.inputBg, cursor: "pointer", textAlign: "left", fontFamily: "'Inter',sans-serif" }}>
                                                <span style={{ display: "block", fontSize: 13.5, fontWeight: 700, color: urgency === lvl ? col : t.text }}>{lvl}</span>
                                                <span style={{ display: "block", fontSize: 11.5, color: t.textMuted }}>{desc}</span>
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                <div style={panelCard}>
                                    {stepLbl(3, "Anything they should look at?")}
                                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
                                        {notes.map(n => (
                                            <button key={n} type="button" onClick={() => setReviewNote(v => (v.trim() ? `${v.trim()}\n${n}` : n))}
                                                style={{ minHeight: 32, padding: "0 12px", borderRadius: 999, border: `1px solid ${t.border}`, background: t.inputBg, color: t.text, fontSize: 12.5, cursor: "pointer", fontFamily: "'Inter',sans-serif" }}>+ {n}</button>
                                        ))}
                                    </div>
                                    <label htmlFor="review-note" style={{ position: "absolute", left: -9999 }}>Note to the lawyer</label>
                                    <textarea id="review-note" value={reviewNote} onChange={e => setReviewNote(e.target.value)} placeholder="Optional — what should the lawyer pay attention to?" rows={3}
                                        style={{ width: "100%", background: t.inputBg, border: `1px solid ${t.border}`, color: t.text, borderRadius: 10, padding: "10px 12px", fontSize: 13.5, outline: "none", resize: "vertical", fontFamily: "'Inter',sans-serif", lineHeight: 1.6, boxSizing: "border-box" }} />
                                </div>

                                {/* A submission that did not land must say so HERE. */}
                                {docIssueBanner(() => submitToLawyer(submitKeyRef.current))}
                                <div style={{ ...panelCard, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", position: isMobile ? "static" : "sticky", bottom: 0 }}>
                                    <span aria-hidden="true" style={{ color: t.textMuted }}>🔒</span>
                                    <div style={{ flex: 1, minWidth: 200 }}>
                                        <div style={{ fontSize: 13.5, fontWeight: 600, color: t.text }}>
                                            {lawyerName ? `Sending version ${docVersion ?? 1} to ${lawyerName} · ${urgency}` : "Choose a lawyer to send this version"}
                                        </div>
                                        <div style={{ fontSize: 12, color: t.textMuted }}>This version is frozen for review — later edits make a new version.</div>
                                    </div>
                                    <Btn onClick={() => fixAt(2)}>Keep editing</Btn>
                                    <Btn kind="primary" onClick={() => submitToLawyer()} disabled={submitting || !selLawyer}>
                                        {submitting ? "⏳ Submitting…" : "📤 Send for review"}
                                    </Btn>
                                </div>
                            </div>
                        </div>
                    );
                })()}

                {/* ── With the lawyer, and what they decided (mockup screen 5) ── */}
                {step === 3 && reviewSent && (
                    <div style={workspaceGrid}>
                        <div>{docPane(pdfFrame("Submitted document", "Loading the submitted document…"))}</div>

                        <div style={sidePanel}>
                            <div style={panelCard}>
                                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
                                    <span style={{ width: 40, height: 40, borderRadius: "50%", background: t.primaryGlow2, color: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, flexShrink: 0 }}>⚖️</span>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ fontSize: 14.5, fontWeight: 700, color: t.text }}>{revLawyerName || "Your lawyer"}</div>
                                        <div style={{ fontSize: 12, color: t.textMuted }}>{urgency} review</div>
                                    </div>
                                    <Pill tone={STATUS_TONE[statusView.tone] || "muted"}>{statusView.label}</Pill>
                                </div>
                                {[
                                    { label: "Document submitted", done: true },
                                    { label: "Lawyer notified", done: true },
                                    { label: statusView.isRecovery ? statusView.headline : "Lawyer review",
                                      // NEVER "Complete" for a recovery state.
                                      sub: statusView.isRecovery ? "Could not be carried over"
                                        : reviewStatus === "submitted" ? "In progress — updates automatically" : "Complete",
                                      done: !statusView.isRecovery && reviewStatus !== "submitted", active: reviewStatus === "submitted" },
                                    { label: reviewStatus === "approved" ? "Approved by lawyer" : reviewStatus === "returned" ? "Returned with changes" : reviewStatus === "rejected" ? "Rejected by lawyer" : "Lawyer decision",
                                      sub: reviewStatus === "submitted" ? "Pending" : statusView.isRecovery ? "—" : "Recorded",
                                      done: ["approved", "returned", "rejected"].includes(reviewStatus) },
                                ].map((item, i) => (
                                    <div key={i} style={{ display: "flex", gap: 10, alignItems: "center", padding: "6px 0" }}>
                                        <span aria-hidden="true" style={{ width: 20, height: 20, borderRadius: "50%", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 800, background: item.done ? t.primary : item.active ? t.primaryGlow : t.inputBg, color: item.done ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.primary, border: `1.5px solid ${item.done || item.active ? t.primary : t.border}` }}>{item.done ? "✓" : ""}</span>
                                        <span style={{ fontSize: 13, color: item.done || item.active ? t.text : t.textMuted, fontWeight: item.active ? 700 : 500, flex: 1 }}>{item.label}</span>
                                        {item.sub && <span style={{ fontSize: 11.5, color: item.active ? t.primary : t.textMuted }}>{item.sub}</span>}
                                    </div>
                                ))}
                            </div>

                            {reviewStatus === "submitted" && (
                                <div style={panelCard}>
                                    <div style={{ fontSize: 12.5, color: t.textMuted, lineHeight: 1.6, marginBottom: 10 }}>
                                        ⏳ Waiting for {revLawyerName} to review. This page checks automatically —
                                        you'll also get a notification the moment they respond.
                                    </div>
                                    <Btn onClick={() => withdrawFromReview()} disabled={withdrawing} style={{ width: "100%" }}>
                                        {withdrawing ? "Withdrawing…" : "↩️ Withdraw from review"}
                                    </Btn>
                                </div>
                            )}
                            {statusView.isRecovery && (
                                <div style={{ ...panelCard, borderColor: `${t.warn}55` }}>
                                    <div style={{ fontSize: 13, fontWeight: 700, color: t.warn, marginBottom: 4 }}>⚠️ {statusView.headline}</div>
                                    {/* The API's words — see lib/documentStatus.js. */}
                                    <div style={{ fontSize: 13, color: t.text, lineHeight: 1.6, marginBottom: 10 }}>{statusView.explanation}</div>
                                    <Btn kind="primary" onClick={() => { setReviewSent(false); setReviewStatus(null); setReviewRecovery(null); goTo(1); }} style={{ width: "100%" }}>
                                        ✏️ {statusView.actionLabel} →
                                    </Btn>
                                </div>
                            )}
                            {(reviewStatus === "returned" || reviewStatus === "rejected") && (
                                <div style={{ ...panelCard, borderColor: `${reviewStatus === "returned" ? t.warn : t.danger}55` }}>
                                    <div style={{ fontSize: 13, fontWeight: 700, color: reviewStatus === "returned" ? t.warn : t.danger, marginBottom: 8 }}>
                                        {reviewStatus === "returned" ? "↩️ Lawyer requested changes" : "❌ Lawyer rejected this document"}
                                    </div>
                                    <div style={{ display: "flex", gap: 10 }}>
                                        <span style={{ width: 32, height: 32, borderRadius: "50%", background: t.primaryGlow2, color: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700, flexShrink: 0 }}>⚖️</span>
                                        <div style={{ fontSize: 13.5, color: t.text, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{lawyerNote || "No note provided."}</div>
                                    </div>
                                    {reviewStatus === "returned" && (
                                        <Btn kind="primary" onClick={() => { setReviewSent(false); setReviewStatus(null); goTo(1); }} style={{ width: "100%", marginTop: 12 }}>
                                            ✏️ {textEdited ? "Revise in workspace" : "Revise & Regenerate"} →
                                        </Btn>
                                    )}
                                </div>
                            )}
                            {reviewStatus === "approved" && (
                                <Btn kind="primary" onClick={() => goTo(4)} style={{ width: "100%", minHeight: 46 }}>🏛 View Final Version →</Btn>
                            )}

                            <div style={panelCard}>
                                {[["Lawyer", revLawyerName || "—"], ["Urgency", urgency], ["Type", selectedType?.label || "—"]].map(([k, v]) => (
                                    <div key={k} style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "6px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12.5 }}>
                                        <span style={{ color: t.textMuted }}>{k}</span><span style={{ fontWeight: 600, color: t.text, textAlign: "right" }}>{v}</span>
                                    </div>
                                ))}
                                {reviewNote ? <div style={{ marginTop: 9, fontSize: 12, color: t.textMuted, fontStyle: "italic", whiteSpace: "pre-wrap" }}>📝 {reviewNote.slice(0, 160)}{reviewNote.length > 160 ? "…" : ""}</div> : null}
                                <Btn onClick={() => { if (docId) { downloadDocumentFile(docId, docTitle || "document", {
                                        revisionId: viewRev?.revision_id || docRevisionId,
                                        expectedPdfSha256: viewRev?.pdf_sha256 || docPdfSha256,
                                    }); } else { toast.show("Generate the document first", "warn"); } }}
                                    disabled={!docId} style={{ width: "100%", marginTop: 12 }}>
                                    {docId ? "📥 Download PDF" : "Generate the document first"}
                                </Btn>
                            </div>
                        </div>
                    </div>
                )}

                {/* ════════════════════════════════════════════════
            STEP 5 — Final version + export
        ════════════════════════════════════════════════ */}
                {step === 4 && (
                    <div style={workspaceGrid}>
                        {/* The REAL approved PDF, rendered inline. */}
                        <div>{docPane(pdfFrame("Approved document", "Loading the approved document…"))}</div>
                        <div style={sidePanel}>
                            <div style={{ ...panelCard, textAlign: "center" }}>
                                <div style={{ fontSize: 36, marginBottom: 6 }}>🎉</div>
                                <div style={{ fontFamily: "'Playfair Display',serif", fontSize: 18, fontWeight: 700, color: t.text }}>Document complete</div>
                                <div style={{ fontSize: 12.5, color: t.textMuted, margin: "4px 0 10px" }}>Reviewed and approved by {revLawyerName || "your lawyer"}</div>
                                <Pill tone="low">● Final version</Pill>
                            </div>
                            <div style={panelCard}>
                                {[["Type", selectedType?.label || "—"], ["Reviewer", revLawyerName || "—"], ["Status", null], ["Required particulars", null]].map(([k, v]) => (
                                    <div key={k} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, padding: "7px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12.5 }}>
                                        <span style={{ color: t.textMuted }}>{k}</span>
                                        {k === "Status" ? <Badge type="info">Final</Badge> : k === "Required particulars" ? <Badge type={_PARTICULARS_BADGE[finalParticulars.tone]}>{finalParticulars.label}</Badge> : <span style={{ fontWeight: 600, color: t.text, textAlign: "right" }}>{v}</span>}
                                    </div>
                                ))}
                            </div>
                            {/* Only Download was ever wired — the PDF already exists. */}
                            <Btn kind="primary"
                                onClick={() => { if (docId) { setExported(true); downloadDocumentFile(docId, docTitle || "document", {
                                    revisionId: viewRev?.revision_id || docRevisionId,
                                    expectedPdfSha256: viewRev?.pdf_sha256 || docPdfSha256,
                                }); } else { toast.show("Generate the document first", "warn"); } }}
                                disabled={!docId} style={{ width: "100%", minHeight: 46 }}>
                                {docId ? "📥 Download PDF" : "Generate the document first"}
                            </Btn>
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
