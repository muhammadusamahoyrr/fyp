'use client';
import { useEffect, useState } from "react";
import { listRevisionsV2, errorCode } from "@/lib/api.js";

/* What versions of this document exist, and what was checked on each.
 *
 * ONE COMPONENT FOR BOTH SURFACES. A client asking "what did I change?" and a
 * lawyer asking "what changed since I last saw this?" are the same question
 * about the same rows, and two implementations of it would drift — most likely
 * in which revision they call current, which is the one detail that must not
 * be wrong on a screen someone signs off from.
 *
 * NO BODY TEXT. The endpoint deliberately omits it: a history list needs
 * versions, hashes and verdicts, and shipping the prose of every past revision
 * to draw a sidebar would send the whole back-catalogue on every open. Reading
 * a revision is what the preview is for.
 *
 * Silent when the feature is off. `feature_disabled` is the flag saying "not
 * here", not an error worth showing someone who was never offered the feature.
 */
export default function RevisionHistory({ docId, t, currentRevisionId, reloadKey, onPreview }) {
    const [items, setItems] = useState(null);   // null = not loaded, [] = none
    const [issue, setIssue] = useState(null);

    useEffect(() => {
        let live = true;
        if (!docId) { setItems(null); return; }

        listRevisionsV2(docId).then(({ data, error, status }) => {
            if (!live) return;
            if (error) {
                // Off, or unavailable. Either way there is no history to show
                // and nothing useful to say about it.
                setItems([]);
                setIssue(status === 404 && errorCode(error) === "feature_disabled"
                    ? null
                    : (error.message || "Could not load version history"));
                return;
            }
            setItems(data?.items || []);
            setIssue(null);
        });

        return () => { live = false; };
        // `reloadKey`, not `currentRevisionId`. The caller highlights whichever
        // revision it is DISPLAYING, which changes on every click in this list —
        // re-reading on that would refetch the whole history each time someone
        // browsed it. `reloadKey` is the document's real current revision, so
        // the list reloads when a new one is generated and not otherwise.
    }, [docId, reloadKey]);

    // Nothing to show, and nothing worth saying: one revision is not a history.
    if (!items || (items.length <= 1 && !issue)) return null;

    return (
        <div style={{ marginTop: 14 }}>
            <div style={{
                fontSize: 10, fontWeight: 700, textTransform: "uppercase",
                letterSpacing: "0.8px", color: t.textMuted, marginBottom: 8,
            }}>
                Version history
            </div>

            {issue && (
                <div style={{ fontSize: 11.5, color: t.textMuted, marginBottom: 8 }}>
                    {issue}
                </div>
            )}

            {items.map(rev => {
                const isCurrent = rev.revision_id === currentRevisionId;
                // `failed` is a revision whose file was never produced — a
                // migrated document with no artifact, or a render that died.
                // Shown rather than hidden: a gap in the version numbers is
                // more alarming than a row that explains itself.
                const failed = rev.status !== "generated";
                return (
                    <div
                        key={rev.revision_id}
                        onClick={() => !failed && onPreview?.(rev)}
                        style={{
                            display: "flex", alignItems: "center", gap: 10,
                            padding: "7px 9px", borderRadius: 8, marginBottom: 3,
                            cursor: failed ? "default" : "pointer",
                            background: isCurrent ? t.primaryGlow : "transparent",
                            border: `1px solid ${isCurrent ? `${t.primary}40` : "transparent"}`,
                            opacity: failed ? 0.6 : 1,
                        }}>
                        <span style={{
                            fontSize: 11.5, fontWeight: 700,
                            color: isCurrent ? t.primary : t.text, minWidth: 30,
                        }}>
                            v{rev.version}
                        </span>
                        <span style={{ flex: 1, fontSize: 11.5, color: t.textMuted }}>
                            {failed
                                ? "No file was produced for this version"
                                : _verdict(rev)}
                        </span>
                        {isCurrent && (
                            <span style={{ fontSize: 10, fontWeight: 700, color: t.primary }}>
                                CURRENT
                            </span>
                        )}
                    </div>
                );
            })}
        </div>
    );
}

/* What was actually checked on this revision.
 *
 * Never invents a verdict. A revision the corpus could not verify says so —
 * "not verified" and "verified and passed" are different facts, and collapsing
 * them into a tick is the most expensive lie a legal document screen can tell.
 */
function _verdict(rev) {
    if (rev.extraction_status && rev.extraction_status !== "ok") {
        return "Text could not be read — not verified";
    }
    const verdict = rev.verification?.verdict;
    if (!verdict) return "Not verified";
    if (verdict === "pass") return "Checked against its sources";
    return `Verification: ${verdict}`;
}
