'use client';
/* What PII masking did -- and did NOT prove (ANALYZER_PII_MASKING.md).
 *
 * Never "all personal data removed": how many names or addresses detection
 * misses is not measured, and the AI's accuracy on masked input has not been
 * evaluated. Shown wherever an AI result made from masked input appears. */
import React from "react";

export const MASKING_TEXT = "Personal details that were detected (such as names, CNIC numbers, phone numbers and "
    + "addresses) were replaced with placeholders like [NAME_1] before the text was sent to the AI. Detection is "
    + "not complete: some names or addresses may not have been detected.";
export const MASKED_NOT_EVALUATED = "The AI's accuracy on masked input has not been evaluated.";

export default function MaskingNote({ t, pii, evaluation }) {
    if (!pii) return null;
    return (
        <div data-pii-masking={pii.masking_version} style={{ fontSize: 12.5, marginTop: 6, color: t?.textMuted }}>
            <div>{MASKING_TEXT}</div>
            {evaluation?.masked_input === "not_yet_evaluated" && (
                <div data-masked-not-evaluated>{MASKED_NOT_EVALUATED}</div>
            )}
        </div>
    );
}
