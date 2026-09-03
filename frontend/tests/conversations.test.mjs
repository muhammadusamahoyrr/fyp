/* Restoring a conversation must not quietly change how sure its answers were.
 *
 * The server keeps every trust signal an answer carried. This module turns
 * those stored rows back into what each surface renders, and it is the place
 * where a signal fails to come back — an answer that reloads WITHOUT its repeal
 * warning, or with its claim support missing, looks MORE trustworthy than the
 * one originally shown. That is not a cosmetic regression: it is the answer
 * changing its mind about how sure it was.
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
    toClientMessage, toClientMessages, toResearchMessage, toResearchMessages,
    groupConversations, formatTime, newMessageId,
    readActiveSession, writeActiveSession, clearActiveSessions, mergeMessages,
} from "../src/lib/conversations.js";
import { MATCHED, UNRESOLVED, RETRIEVED, REPEALED } from "../src/lib/trust.js";

/* A stored assistant message, exactly as the API returns one. */
const STORED_ANSWER = {
    role: "assistant",
    content: "Under the Punjab Rented Premises Act 2009, s.30 requires notice.",
    created_at: "2026-09-02T10:30:00+00:00",
    citations: [
        { statute: "Punjab Rented Premises Act 2009", section: "30",
          status: "matched", currency: "unknown",
          source_url: "/api/v1/ai/source/prpa.pdf" },
        { statute: "CrPC 1898", section: "154", status: "unresolved",
          currency: "repealed", instrument: "Act XI of 2015",
          jurisdiction: "punjab" },
        { statute: "CPC 1908", section: "9", status: "retrieved",
          currency: "unknown" },
    ],
    claims: [
        { index: 1, text: "Notice is required.", support: "supported",
          citation_status: "matched", currency: "unknown" },
        { index: 2, text: "The tenancy ends immediately.", support: "unsupported",
          citation_status: "matched", currency: "repealed" },
    ],
    confidence: 0.42,
    confidence_band: "moderate",
    model_confidence: 0.85,
    jurisdiction: "punjab",
    jurisdiction_basis: "user_selected",
    convergence_status: "converged",
    arbitration_source: "decision_engine",
    request_id: "req-abc123",
};

const STORED_QUESTION = {
    role: "user",
    content: "What notice is required to evict a tenant?",
    created_at: "2026-09-02T10:29:00+00:00",
};

/* ── the client surface ───────────────────────────────────────────────── */

test("a restored client answer keeps its citation statuses", () => {
    const m = toClientMessage(STORED_ANSWER);
    assert.deepEqual(m.refs.map(r => r.status), [MATCHED, UNRESOLVED, RETRIEVED]);
});

test("a restored client answer keeps its repeal warning", () => {
    // The single most consequential signal on the surface. An answer that
    // reloads without it is telling the user something it did not say before.
    const m = toClientMessage(STORED_ANSWER);
    const dead = m.refs.filter(r => r.currency === REPEALED);
    assert.equal(dead.length, 1);
    assert.equal(dead[0].label, "CrPC 1898 §154");
    assert.equal(dead[0].instrument, "Act XI of 2015");
});

test("a restored client answer keeps its claim support", () => {
    const m = toClientMessage(STORED_ANSWER);
    assert.equal(m.claims.length, 2);
    assert.equal(m.claims[1].support, "unsupported");
    assert.equal(m.claims[1].currency, REPEALED);
});

test("a restored client answer keeps its confidence and jurisdiction", () => {
    const m = toClientMessage(STORED_ANSWER);
    assert.equal(m.confidence, 0.42);
    assert.equal(m.confidenceBand, "moderate");
    assert.equal(m.jurisdiction, "punjab");
    assert.equal(m.jurisdictionBasis, "user_selected");
});

test("a restored client answer keeps the id naming its audit record", () => {
    assert.equal(toClientMessage(STORED_ANSWER).requestId, "req-abc123");
});

test("a restored source link still points at the source", () => {
    const m = toClientMessage(STORED_ANSWER);
    assert.equal(m.refs[0].sourceUrl, "/api/v1/ai/source/prpa.pdf");
});

test("a restored user message carries no answer metadata", () => {
    const m = toClientMessage(STORED_QUESTION);
    assert.equal(m.role, "user");
    assert.deepEqual(m.refs, []);
    assert.deepEqual(m.claims, []);
});

test("a restored conversation keeps its order and roles", () => {
    const list = toClientMessages([STORED_QUESTION, STORED_ANSWER]);
    assert.deepEqual(list.map(m => m.role), ["user", "ai"]);
    assert.equal(list[0].text, STORED_QUESTION.content);
});

test("a restored message is marked as restored", () => {
    // So the surface can tell a reloaded answer from a live one — a rating was
    // already given, or its moment has passed.
    assert.equal(toClientMessage(STORED_ANSWER).restored, true);
});

/* ── the lawyer surface ───────────────────────────────────────────────── */

test("a restored research answer keeps the same signals in its own shape", () => {
    const m = toResearchMessage(STORED_ANSWER);
    assert.equal(m.role, "assistant");
    assert.equal(m.content, STORED_ANSWER.content);
    assert.deepEqual(m.citations.map(c => c.status), [MATCHED, UNRESOLVED, RETRIEVED]);
    assert.equal(m.claims[1].support, "unsupported");
    assert.equal(m.modelConfidence, 0.85);
    assert.equal(m.arbitrationSource, "decision_engine");
    assert.equal(m.requestId, "req-abc123");
});

test("both surfaces restore the same citation facts", () => {
    // They render differently; they must not DISAGREE.
    const client = toClientMessage(STORED_ANSWER).refs;
    const lawyer = toResearchMessage(STORED_ANSWER).citations;
    assert.deepEqual(client.map(c => [c.label, c.status, c.currency]),
                     lawyer.map(c => [c.label, c.status, c.currency]));
});

test("a restored research conversation keeps its order", () => {
    const list = toResearchMessages([STORED_QUESTION, STORED_ANSWER]);
    assert.deepEqual(list.map(m => m.role), ["user", "assistant"]);
});

/* ── degraded rows ────────────────────────────────────────────────────── */

test("an old row with no metadata restores without throwing", () => {
    // Rows written before the metadata was stored still have to open.
    const m = toClientMessage({ role: "assistant", content: "old answer" });
    assert.deepEqual(m.refs, []);
    assert.deepEqual(m.claims, []);
    assert.equal(m.requestId, "");
    assert.equal(m.confidenceBand, undefined);
});

test("an empty or malformed conversation restores to an empty list", () => {
    assert.deepEqual(toClientMessages(null), []);
    assert.deepEqual(toResearchMessages(undefined), []);
});

test("a restored citation with an unknown status degrades to retrieved", () => {
    // Through normaliseCitations, so restoration cannot overstate what an
    // answer cited any more than a live answer can.
    const m = toClientMessage({
        role: "assistant", content: "x",
        citations: [{ statute: "PPC 1860", section: "302", status: "verified" }],
    });
    assert.equal(m.refs[0].status, RETRIEVED);
});

test("a bad timestamp renders as no time rather than Invalid Date", () => {
    assert.equal(formatTime("not a date"), "");
    assert.equal(formatTime(null), "");
    assert.equal(formatTime(undefined), "");
});

/* ── the sidebar ──────────────────────────────────────────────────────── */

test("conversations are grouped by recency", () => {
    const now = new Date("2026-09-02T12:00:00Z");
    const groups = groupConversations([
        { session_id: "a", updated_at: "2026-09-02T09:00:00Z" },
        { session_id: "b", updated_at: "2026-08-30T09:00:00Z" },
        { session_id: "c", updated_at: "2026-06-01T09:00:00Z" },
    ], now);
    assert.deepEqual(groups.map(g => g.group),
                     ["Today", "Previous 7 days", "Earlier"]);
    assert.deepEqual(groups.map(g => g.items.map(i => i.session_id)),
                     [["a"], ["b"], ["c"]]);
});

test("empty groups are not rendered", () => {
    const groups = groupConversations(
        [{ session_id: "a", updated_at: "2026-09-02T09:00:00Z" }],
        new Date("2026-09-02T12:00:00Z"));
    assert.deepEqual(groups.map(g => g.group), ["Today"]);
});

test("a conversation with no timestamp still appears", () => {
    // Dropping it would make a conversation unreachable from the only list
    // that points at it.
    const groups = groupConversations([{ session_id: "a" }],
                                      new Date("2026-09-02T12:00:00Z"));
    assert.equal(groups.flatMap(g => g.items).length, 1);
});

test("an empty list produces no groups", () => {
    assert.deepEqual(groupConversations([], new Date()), []);
    assert.deepEqual(groupConversations(null, new Date()), []);
});

/* ── the id that makes a retry safe ───────────────────────────────────── */

test("every send gets a distinct id", () => {
    const ids = new Set(Array.from({ length: 200 }, newMessageId));
    assert.equal(ids.size, 200);
});

test("an id is produced even without crypto.randomUUID", () => {
    const saved = Object.getOwnPropertyDescriptor(globalThis, "crypto");
    Object.defineProperty(globalThis, "crypto",
                          { value: {}, configurable: true, writable: true });
    try {
        const id = newMessageId();
        assert.ok(id && typeof id === "string");
    } finally {
        if (saved) Object.defineProperty(globalThis, "crypto", saved);
        else delete globalThis.crypto;
    }
});


/* ── user-scoped, per-tab browser state ────────────────────────────────────
 *
 * One shared key had two failures that both end with someone looking at the
 * wrong conversation: signing in as a different user inherited the previous
 * one's session id, and two open tabs overwrote each other's remembered thread.
 */

function withStorages(fn) {
    const make = () => {
        const map = new Map();
        return {
            get length() { return map.size; },
            key: (i) => Array.from(map.keys())[i] ?? null,
            getItem: (k) => (map.has(k) ? map.get(k) : null),
            setItem: (k, v) => map.set(k, String(v)),
            removeItem: (k) => map.delete(k),
            _map: map,
        };
    };
    const session = make();
    const local = make();
    const saved = ["sessionStorage", "localStorage"].map(
        (k) => [k, Object.getOwnPropertyDescriptor(globalThis, k)]);
    Object.defineProperty(globalThis, "sessionStorage",
        { value: session, configurable: true, writable: true });
    Object.defineProperty(globalThis, "localStorage",
        { value: local, configurable: true, writable: true });
    try {
        return fn({ session, local });
    } finally {
        for (const [k, d] of saved) {
            if (d) Object.defineProperty(globalThis, k, d);
            else delete globalThis[k];
        }
    }
}

test("a different account cannot read the previous one's conversation", () => {
    withStorages(() => {
        writeActiveSession("client", "user-A", "sess-A");
        assert.equal(readActiveSession("client", "user-A"), "sess-A");
        // The next user reads a DIFFERENT key and finds nothing — rather than
        // reading a shared key and having to remember to check the owner.
        assert.equal(readActiveSession("client", "user-B"), null);
    });
});

test("the two surfaces are remembered separately per user", () => {
    withStorages(() => {
        writeActiveSession("client", "user-A", "chat-1");
        writeActiveSession("research", "user-A", "research-1");
        assert.equal(readActiveSession("client", "user-A"), "chat-1");
        assert.equal(readActiveSession("research", "user-A"), "research-1");
    });
});

test("the active conversation lives in sessionStorage so tabs do not fight", () => {
    // Two tabs must keep their OWN active conversation while sharing the same
    // server history. localStorage would make them overwrite each other.
    withStorages(({ session, local }) => {
        writeActiveSession("client", "user-A", "sess-A");
        assert.equal(session._map.size, 1);
        assert.equal(local._map.size, 0);
    });
});

test("signing out clears every remembered conversation", () => {
    withStorages(({ session }) => {
        writeActiveSession("client", "user-A", "chat-1");
        writeActiveSession("research", "user-A", "research-1");
        writeActiveSession("client", "user-B", "chat-2");
        clearActiveSessions();
        assert.equal(session._map.size, 0);
        assert.equal(readActiveSession("client", "user-A"), null);
    });
});

test("signing out also clears the pre-scoping keys", () => {
    // So an already-open session does not keep a stale value forever.
    withStorages(({ session, local }) => {
        session.setItem("aai-active-conversation", "old-chat");
        local.setItem("aai-active-research", "old-research");
        clearActiveSessions();
        assert.equal(session.getItem("aai-active-conversation"), null);
        assert.equal(local.getItem("aai-active-research"), null);
    });
});

test("nothing is remembered without a user id", () => {
    withStorages(({ session }) => {
        writeActiveSession("client", null, "sess-A");
        writeActiveSession("client", undefined, "sess-A");
        assert.equal(session._map.size, 0);
        assert.equal(readActiveSession("client", null), null);
    });
});

test("an unknown surface is not remembered", () => {
    withStorages(({ session }) => {
        writeActiveSession("nonsense", "user-A", "x");
        assert.equal(session._map.size, 0);
        assert.equal(readActiveSession("nonsense", "user-A"), null);
    });
});

test("storage being blocked is not an error", () => {
    const saved = ["sessionStorage", "localStorage"].map(
        (k) => [k, Object.getOwnPropertyDescriptor(globalThis, k)]);
    for (const k of ["sessionStorage", "localStorage"]) {
        Object.defineProperty(globalThis, k, {
            configurable: true, get() { throw new Error("blocked"); },
        });
    }
    try {
        assert.equal(readActiveSession("client", "user-A"), null);
        writeActiveSession("client", "user-A", "sess-A");   // must not throw
        clearActiveSessions();                              // must not throw
    } finally {
        for (const [k, d] of saved) {
            if (d) Object.defineProperty(globalThis, k, d);
            else delete globalThis[k];
        }
    }
});

/* ── reconciling restored history ──────────────────────────────────────── */

test("restored pages merge on the immutable server message id", () => {
    const first = [{ id: "m1", seq: 1, text: "one" },
                   { id: "m2", seq: 2, text: "two" }];
    const second = [{ id: "m2", seq: 2, text: "two" },
                    { id: "m3", seq: 3, text: "three" }];
    const merged = mergeMessages(first, second);
    assert.deepEqual(merged.map(m => m.id), ["m1", "m2", "m3"]);
});

test("two messages with identical text are not merged", () => {
    // Content-based reconciliation would silently drop the second time someone
    // asked the same question.
    const merged = mergeMessages(
        [{ id: "m1", seq: 1, text: "what is the notice period?" }],
        [{ id: "m2", seq: 2, text: "what is the notice period?" }]);
    assert.equal(merged.length, 2);
});

test("a restored copy replaces the live one", () => {
    // The stored copy carries the full metadata; the live one may predate it.
    const merged = mergeMessages(
        [{ id: "m1", seq: 1, text: "x", refs: [] }],
        [{ id: "m1", seq: 1, text: "x", refs: [{ label: "PPC 1860" }] }]);
    assert.equal(merged.length, 1);
    assert.equal(merged[0].refs.length, 1);
});

test("merged history is ordered by server sequence", () => {
    const merged = mergeMessages(
        [{ id: "m3", seq: 3 }, { id: "m1", seq: 1 }],
        [{ id: "m2", seq: 2 }]);
    assert.deepEqual(merged.map(m => m.seq), [1, 2, 3]);
});

test("a local echo with no id or sequence is kept, at the end", () => {
    // It is the only copy of itself until the server stores it.
    const merged = mergeMessages(
        [{ id: "m1", seq: 1, text: "stored" }],
        [{ text: "just typed" }]);
    assert.equal(merged.length, 2);
    assert.equal(merged.at(-1).text, "just typed");
});

test("merging nothing is not an error", () => {
    assert.deepEqual(mergeMessages(null, null), []);
    assert.deepEqual(mergeMessages(undefined, []), []);
});

test("a restored message carries its id and sequence", () => {
    // Both are needed to reconcile a reload against what the tab already shows.
    const m = toClientMessage({ role: "assistant", content: "x",
                                id: "msg-9", seq: 4 });
    assert.equal(m.id, "msg-9");
    assert.equal(m.seq, 4);

    const r = toResearchMessage({ role: "assistant", content: "x",
                                  id: "msg-9", seq: 4 });
    assert.equal(r.id, "msg-9");
    assert.equal(r.seq, 4);
});
