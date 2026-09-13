/**
 * What the chat surface tells a client about lawyer matching.
 *
 * The service returns three genuinely different verdicts, and the chat path
 * flattened them into a list. Two consequences, both asserted here:
 *
 *   - a lawyer the service explicitly REFUSED to rank (`match_score: null`) was
 *     rendered as "0% match", because `Math.round((null || 0) * 100)` is 0 — a
 *     precise-looking score for a measurement never made;
 *   - "we could not check" and "there are none" were the same empty list.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
    KIND_BROWSING,
    KIND_MATCHED,
    KIND_NONE,
    KIND_UNAVAILABLE,
    lawyerSubtitle,
    matchFallbackNotice,
    matchHeading,
    matchScoreLabel,
} from "../src/lib/lawyerMatch.js";

// ── the rule that matters ──────────────────────────────────────────────────

test("a null score produces no percentage at all", () => {
    // Not "0%", not "". null, so a caller must decide rather than render a
    // falsy value that happens to look like a number.
    assert.equal(matchScoreLabel(null), null);
    assert.equal(matchScoreLabel(undefined), null);
    assert.equal(matchScoreLabel(""), null);
});

test("a real score is rendered as a percentage", () => {
    assert.equal(matchScoreLabel(0.83), "83% match");
    assert.equal(matchScoreLabel(1), "100% match");
});

test("a genuine zero score is still a zero, not a null", () => {
    // 0.0 from the service is a real measurement of a poor fit. Only null means
    // "not ranked", and collapsing the two would lose that.
    assert.equal(matchScoreLabel(0), "0% match");
});

test("a non-numeric score is refused rather than coerced", () => {
    assert.equal(matchScoreLabel("banana"), null);
    assert.equal(matchScoreLabel(NaN), null);
    assert.equal(matchScoreLabel({}), null);
});

test("an unranked lawyer's subtitle carries no percentage", () => {
    const line = lawyerSubtitle({ province: "sindh", match_score: null, rating: 4 });

    assert.doesNotMatch(line, /%/, `"${line}" invented a score`);
    assert.match(line, /sindh/);
    assert.match(line, /★ 4\.0/);
});

test("a ranked lawyer's subtitle carries the percentage", () => {
    const line = lawyerSubtitle({ province: "punjab", match_score: 0.83, rating: 4.5 });

    assert.equal(line, "punjab · 83% match · ★ 4.5");
});

test("a missing rating is omitted rather than shown as zero stars", () => {
    assert.equal(lawyerSubtitle({ province: "punjab", match_score: null }), "punjab");
    assert.equal(lawyerSubtitle({ province: "punjab", match_score: null, rating: 0 }),
                 "punjab");
});

// ── the three kinds stay apart ─────────────────────────────────────────────

test("a browsing listing is never described as a match", () => {
    const head = matchHeading(KIND_BROWSING, { count: 2 });

    assert.equal(head.show, true);
    assert.equal(head.ranked, false);
    assert.doesNotMatch(head.title, /personalized advice/);
    assert.match(head.title, /browse/i);
});

test("ranked matches keep their existing headings", () => {
    // Both pre-existing headings must survive, because they say different
    // things: one is an offer, the other is the AI conceding its limit.
    assert.match(matchHeading(KIND_MATCHED, { count: 2 }).title,
                 /Connect with a lawyer/);
    assert.match(matchHeading(KIND_MATCHED, { count: 2, suggestLawyer: true }).title,
                 /reached its limit/);
});

test("no candidates and unavailable both show no list", () => {
    assert.equal(matchHeading(KIND_NONE, { count: 0 }).show, false);
    assert.equal(matchHeading(KIND_UNAVAILABLE, { count: 0 }).show, false);
});

test("an empty list is never given a heading, whatever the kind", () => {
    for (const kind of [KIND_MATCHED, KIND_BROWSING, KIND_NONE, KIND_UNAVAILABLE]) {
        assert.equal(matchHeading(kind, { count: 0 }).show, false);
    }
});

test("unavailable never claims there are no lawyers", () => {
    const notice = matchFallbackNotice(KIND_UNAVAILABLE, "");

    assert.match(notice, /unavailable/i);
    assert.doesNotMatch(notice, /no verified lawyers/i,
        "a failed lookup was reported as an absence of lawyers");
});

test("no candidates says so plainly", () => {
    assert.match(matchFallbackNotice(KIND_NONE, ""), /No verified lawyers/i);
});

test("the service's own notice wins when it sends one", () => {
    assert.equal(
        matchFallbackNotice(KIND_NONE, "Nobody is verified in Balochistan yet."),
        "Nobody is verified in Balochistan yet.");
});

test("unavailable and none produce different text", () => {
    assert.notEqual(matchFallbackNotice(KIND_NONE, ""),
                    matchFallbackNotice(KIND_UNAVAILABLE, ""));
});

// ── the wiring, in both message paths ──────────────────────────────────────

const CHATBOT = readFileSync(
    new URL("../src/components/client/ModChatbot.jsx", import.meta.url), "utf8");

const PANEL = readFileSync(
    new URL("../src/components/client/LawyerMatchPanel.jsx", import.meta.url), "utf8");

test("the 0%-match render exists in neither component", () => {
    // Swept across BOTH files rather than the one that happened to hold it when
    // this was written — the render moved into the extracted panel, and a check
    // pinned to a single file would have gone quietly true.
    for (const [name, source] of [["ModChatbot", CHATBOT], ["LawyerMatchPanel", PANEL]]) {
        assert.ok(!source.includes("match_score || 0"),
            `the fabricated-score render is still present in ${name}`);
    }
    assert.ok(PANEL.includes("lawyerSubtitle"),
        "the panel does not use the shared subtitle contract");
});

test("both the final-answer and clarification paths carry the verdict", () => {
    // A correct lib that no message path populates discloses nothing. Two
    // occurrences: one per path.
    const kinds = CHATBOT.match(/matchResultKind: msg\.match_result_kind/g) || [];
    const notices = CHATBOT.match(/matchNotice: msg\.match_notice/g) || [];

    assert.equal(kinds.length, 2,
        `expected both message paths to carry match_result_kind, found ${kinds.length}`);
    assert.equal(notices.length, 2,
        `expected both message paths to carry match_notice, found ${notices.length}`);
});
