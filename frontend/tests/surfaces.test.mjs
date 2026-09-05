/* The three AI surfaces must describe the same backend fields the same way.
 *
 * Client chatbot, lawyer AI Legal page, and the AI tab inside a case workspace
 * all render `citations`, `claims`, `confidence_band` and `request_id`. Each
 * used to map them itself and they HAD drifted:
 *
 *   - the workspace tab dropped `url` and `source`, so a judgment linking to a
 *     court PDF on one lawyer screen was an unclickable label on the other;
 *   - the workspace tab stored citation status, claim support and confidence on
 *     every message and rendered none of it — an answer shown with no
 *     provenance, inside the case file where it is most likely to be acted on;
 *   - the client dropped the source link entirely, so "Verify before relying on
 *     them" was an instruction with no way to follow it.
 *
 * There is no component renderer in this repo, so these assert on the source.
 * That is weaker than mounting the components, and it is enough to catch the
 * regression that actually happened: a surface quietly growing its own copy of
 * the vocabulary.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const src = (p) => readFileSync(
    fileURLToPath(new URL(`../src/${p}`, import.meta.url)), "utf8");

const SURFACES = {
    "client chatbot": "components/client/ModChatbot.jsx",
    "lawyer AI Legal page": "components/lawyer/AILegalPage.jsx",
    "case workspace AI tab": "components/lawyer/CasesPage.jsx",
};

for (const [name, path] of Object.entries(SURFACES)) {
    const code = src(path);

    test(`${name} takes its citation vocabulary from lib/trust.js`, () => {
        assert.match(code, /from "@\/lib\/trust\.js"/,
            `${name} does not import the shared trust module`);
    });

    test(`${name} does not hand-roll the citation status list`, () => {
        // The literal that drifted. Groups come from CITATION_GROUPS now.
        const handRolled = /\[\s*\[\s*"matched"\s*,/;
        assert.ok(!handRolled.test(code),
            `${name} still has its own matched/unresolved/retrieved list`);
        assert.match(code, /CITATION_GROUPS/);
    });

    test(`${name} does not re-map citations itself`, () => {
        // `label: [c.statute, ...]` was the shape each surface built by hand,
        // and it is where fields got dropped.
        assert.ok(!/label:\s*\[\s*\w+\.statute/.test(code),
            `${name} builds its own citation objects again`);
        assert.match(code, /normaliseCitations\(/);
    });

    test(`${name} shows the request id`, () => {
        assert.match(code, /requestId/,
            `${name} drops request_id, so its answers cannot be named`);
        assert.match(code, /shortRequestId|copyText/,
            `${name} shows an id nobody can copy`);
    });

    test(`${name} never declares its own REPEALED constant`, () => {
        assert.ok(!/const\s+REPEALED\s*=/.test(code),
            `${name} redefines REPEALED instead of importing it`);
    });

    test(`${name} does not invent a source link from a filename`, () => {
        // Only the server knows whether a source_file resolves to a document it
        // actually holds; about half the corpus by chunk count does not.
        assert.ok(!/\/ai\/source\//.test(code),
            `${name} builds a source URL client-side`);
    });
}

test("the workspace AI tab renders the trust data it fetches", () => {
    // It stored citations, claims and confidence on every message and displayed
    // only the answer text.
    const code = src("components/lawyer/CasesPage.jsx");
    assert.match(code, /WorkspaceTrust/);
    assert.match(code, /claimWarnings|citationSummary/,
        "warnings must be computed, not just stored");
});

test("only the lawyer surfaces can open the audit view", () => {
    // The client is shown the FINDINGS. The audit view is the machinery behind
    // them and is lawyer-only on the server; the client must not call it and
    // then render a 403.
    assert.ok(!/aiProvenance/.test(src("components/client/ModChatbot.jsx")),
        "the client chatbot calls the lawyer-only provenance endpoint");
    assert.match(src("components/lawyer/AILegalPage.jsx"), /aiProvenance/);
});

test("the provenance helper targets the redacted view, not the raw record", () => {
    const api = src("lib/api.js");
    const fn = api.match(/export async function aiProvenance[\s\S]*?\n\}/);
    assert.ok(fn, "aiProvenance is not defined");
    assert.match(fn[0], /\/view/,
        "the UI reads the raw stored record instead of the whitelist projection");
    assert.match(fn[0], /encodeURIComponent/,
        "the request id is interpolated into a URL unescaped");
});

test("both client-visible surfaces still send case_id and no case facts", () => {
    // Guarding the P3 property from a P8 edit: these files were both touched.
    for (const path of ["components/lawyer/AILegalPage.jsx",
                        "components/lawyer/CasesPage.jsx"]) {
        const code = src(path);
        assert.ok(!/caseContext/.test(code), `${path} rebuilt a case-facts payload`);
        for (const m of code.matchAll(/case_id:\s*([^,\n]+)/g)) {
            assert.match(m[1], /\._id/,
                `${path} sends ${m[1].trim()} instead of the database id`);
        }
    }
});

test("no surface renders a credentialed API path as a plain anchor", () => {
    // /ai/source is bearer-authenticated like every other API route. A new tab
    // sends no Authorization header, so `<a href={c.sourceUrl}>` opens a 401
    // page — a "view the source" affordance that reliably fails. Corpus
    // documents must go through api.openSourceDocument (fetch, then blob).
    for (const [name, path] of Object.entries(SURFACES)) {
        const code = src(path);
        assert.ok(!/href=\{[\w.]*\.?sourceUrl/.test(code),
            `${name} renders sourceUrl as an anchor href`);
        if (/sourceUrl/.test(code)) {
            assert.match(code, /openSourceDocument\(/,
                `${name} uses sourceUrl without the authenticated opener`);
        }
    }
});

test("the source opener strips the prefix the API base already carries", () => {
    // `source_url` is published with /api/v1 on it; BASE has it too.
    const fn = src("lib/api.js").match(/export async function openSourceDocument[\s\S]*?\n\}/);
    assert.ok(fn, "openSourceDocument is not defined");
    assert.ok(fn[0].includes("/^\\/api\\/v1/"),
        "the helper would request /api/v1/api/v1/...");
    assert.match(fn[0], /returnResponse: true/,
        "the helper parses a PDF as JSON");
});

test("a failure to open one source is never reported through an undefined handler", () => {
    // Both of these were wrong on the first pass and neither is caught by
    // `next build`: an undefined identifier inside a click handler is a runtime
    // ReferenceError, and `useToast()` returns { show }, not a callable.
    const lawyer = src("components/lawyer/AILegalPage.jsx");
    assert.ok(!/setError\(/.test(lawyer),
        "AILegalPage calls setError, which it does not define");

    const client = src("components/client/ModChatbot.jsx");
    assert.ok(!/[^.\w]toast\(/.test(client),
        "ModChatbot calls toast() — useToast returns { show }, not a function");
});

test("every surface reports a failed source open somewhere", () => {
    for (const [name, path] of Object.entries(SURFACES)) {
        const code = src(path);
        if (!/openSourceDocument\(/.test(code)) continue;
        assert.match(code, /res\.error|\.error\b/,
            `${name} ignores the result of openSourceDocument`);
    }
});

test("every anchor with an href carries target=_blank and rel=noopener noreferrer", () => {
    // `target=_blank` without `rel=noopener` hands the opened page a live
    // `window.opener` back into this one; `noreferrer` keeps the lawyer's
    // current URL — which can name a case — out of the court site's logs.
    for (const [name, path] of Object.entries(SURFACES)) {
        const code = src(path);
        const anchors = code.match(/<a\s[^>]*href=\{[^}]*\}[^>]*>/g) || [];
        assert.ok(anchors.length > 0, `${name} renders no citation anchors`);
        for (const tag of anchors) {
            assert.match(tag, /target="_blank"/,
                `${name}: anchor without target=_blank -> ${tag.slice(0, 90)}`);
            assert.match(tag, /rel="noopener noreferrer"/,
                `${name}: anchor without rel=noopener noreferrer -> ${tag.slice(0, 90)}`);
        }
    }
});

test("no surface renders an href it has not scheme-checked", () => {
    // Only `href` (validated by normaliseCitation via safeExternalUrl) may
    // reach an anchor. A raw payload field would bypass the check entirely.
    for (const [name, path] of Object.entries(SURFACES)) {
        const code = src(path);
        for (const m of code.matchAll(/<a\s[^>]*href=\{([^}]*)\}/g)) {
            assert.match(m[1].trim(), /^\w+\.href$/,
                `${name} renders ${m[1].trim()} as an href without validating it`);
        }
    }
});

test("the scheme allowlist lives in one place", () => {
    // A second copy is a second thing to forget when a scheme is added.
    const trust = src("lib/trust.js");
    assert.match(trust, /SAFE_SCHEMES/);
    for (const [name, path] of Object.entries(SURFACES)) {
        assert.ok(!/javascript:|SAFE_SCHEMES\s*=/.test(src(path)),
            `${name} carries its own scheme handling`);
    }
});

/* ── persistent conversations (P2) ─────────────────────────────────────── */

test("the client chat no longer mints its own session id", () => {
    // A browser-minted id meant a refresh started a new conversation and the
    // previous one became unreachable — still in the database, with nothing
    // pointing at it. The id is a server fact now.
    const code = src("components/client/ModChatbot.jsx");
    assert.ok(!/sessionIdRef\.current\s*=\s*\n?\s*typeof crypto/.test(code),
        "ModChatbot still generates its own session id");
    assert.match(code, /createConversation\(/,
        "New Chat must create a real persisted conversation");
    assert.match(code, /readActiveSession\("client", user/,
        "the restored conversation is not scoped to the signed-in user");
});

test("the lawyer research page restores its conversation too", () => {
    const code = src("components/lawyer/AILegalPage.jsx");
    assert.ok(!/sessionIdRef = useRef\(`\$\{Date\.now\(\)\}/.test(code),
        "AILegalPage still mints its own session id");
    assert.match(code, /readActiveSession\("research", user/,
        "the restored thread is not scoped to the signed-in user");
    assert.match(code, /createResearchConversation\(/);
});

test("both surfaces send an idempotency key tied to the ATTEMPT", () => {
    // The key must be minted once per attempt and reused across retries of it.
    // Minting it per transmission — `client_message_id: newMessageId()` inline
    // at the send — meant a retry after an ambiguous failure looked like a new
    // question, so the server ran the provider again and the whole
    // turn-idempotency mechanism was unreachable from the UI.
    // ALL THREE surfaces, including the case workspace tab — which sent no
    // turn id at all, so every retry there was a brand-new question: the graph
    // ran again and a provider was paid again for one asking.
    for (const path of Object.values(SURFACES)) {
        const code = src(path);
        assert.ok(!/client_message_id:\s*newMessageId\(\)/.test(code),
            `${path} still mints an id per transmission`);
        // The lawyer surface sends inside a `send(a)` closure so that one
        // ATTEMPT can be transmitted twice; what matters either way is that
        // the id comes off an attempt object rather than being minted here.
        assert.match(code, /client_message_id:\s*(attempt|a)\.id/,
            `${path} does not send the attempt's id`);
        assert.match(code, /newAttempt\(/,
            `${path} never creates an attempt`);
    }
});

test("both surfaces guard conversation opens with a generation ticket", () => {
    // Selecting A then B let A's slower page loop call setMsgs last: B's
    // socket live, A's history on screen, and the next message into B under
    // A's visible conversation.
    for (const [name, path] of Object.entries(SURFACES)) {
        const code = src(path);
        if (!/openConversation/.test(code)) continue;
        assert.match(code, /openGeneration\.next\(\)/,
            `${name} does not take a generation ticket when opening`);
        assert.match(code, /openGeneration\.isCurrent\(ticket\)/,
            `${name} does not drop a stale open response`);
    }
});

test("the connect guard is claimed before the first await", () => {
    // Checking readyState let a reconnect timer, a conversation switch and the
    // previous socket's onclose each start a connection — and readyState is
    // blind during the ticket fetch, because no socket exists yet to be
    // CONNECTING. The claim is synchronous and is held across that await.
    const code = src("components/client/ModChatbot.jsx");
    assert.match(code, /const claim = socket\.claim\(\);/,
        "the connect does not claim ownership before opening a socket");
    const claimAt = code.indexOf("socket.claim()");
    const awaitAt = code.indexOf("await getWsTicket()");
    assert.ok(claimAt > 0 && awaitAt > claimAt,
        "the claim must be taken BEFORE the ticket fetch, not after it");
    assert.match(code, /socket\.adopt\(claim, ws\)/,
        "a superseded connect can still install its socket");
    assert.match(code, /if \(!socket\.isCurrent\(ws\)\) return;/,
        "a replaced socket can still schedule a reconnect");

    // And the owner itself is what knows about CONNECTING.
    assert.match(src("lib/socket.js"), /CONNECTING/);
});

test("both surfaces warn when an answer was not saved", () => {
    // The backend computes history_saved on both paths; ignoring it meant a
    // user read an answer, refreshed, and found it gone with no explanation.
    for (const path of ["components/client/ModChatbot.jsx",
                        "components/lawyer/AILegalPage.jsx"]) {
        const code = src(path);
        assert.match(code, /historySaved === false/,
            `${path} never surfaces a failed history write`);
        assert.match(code, /history_saved/,
            `${path} does not read history_saved from the response`);
    }
});

test("the lawyer surface restores jurisdiction like the client does", () => {
    // It dropped jurisdiction, basis and convergence — so the surface that
    // shows MORE trust detail showed LESS of it after a refresh.
    const code = src("lib/conversations.js");
    const fn = code.slice(code.indexOf("export function toResearchMessage"));
    const body = fn.slice(0, fn.indexOf("\n}"));
    for (const field of ["jurisdiction", "jurisdiction_basis",
                         "convergence_status"]) {
        assert.ok(body.includes(field),
            `toResearchMessage drops ${field} on reload`);
    }
});

test("the client chat frame no longer carries a case id", () => {
    // It was read off the frame and written to the session with no check, so
    // the browser could bind a conversation to any case id it could name.
    const code = src("components/client/ModChatbot.jsx");
    const send = code.match(/socket\.current\(\)\.send\(JSON\.stringify\(\{[\s\S]*?\}\)\);/);
    assert.ok(send, "the send frame could not be located");
    // The KEY, not the substring — the comment above the frame explains why
    // case_id is absent, and matching that would be matching the explanation.
    const keys = send[0]
        .split("\n")
        .filter(line => !line.trim().startsWith("//"))
        .join("\n");
    assert.ok(!/\bcase_id\s*:/.test(keys),
        "the chat frame still sends a case_id the server would have to trust");
    assert.ok(/\bclient_message_id\s*:/.test(keys));
});

test("only the research surface binds a conversation to a case", () => {
    const api = src("lib/api.js");
    const clientCreate = api.match(/export async function createConversation[\s\S]*?\n\}/);
    assert.ok(clientCreate, "createConversation is not defined");
    assert.match(clientCreate[0], /case_id:\s*null/,
        "the client conversation helper sends a case id");

    const researchCreate = api.match(
        /export async function createResearchConversation[\s\S]*?\n\}/);
    assert.match(researchCreate[0], /case_id:\s*caseId/);
});

/* The body of one exported function, by index rather than by regex — a
 * hand-escaped pattern built inside a template literal is one backslash away
 * from matching nothing and passing silently. */
function fnBody(source, name) {
    const start = source.indexOf(`export async function ${name}(`);
    if (start < 0) return null;
    const end = source.indexOf("\n}", start);
    return end < 0 ? null : source.slice(start, end + 2);
}

const CONVERSATION_HELPERS = [
    "listConversations", "createConversation", "getConversation",
    "renameConversation", "deleteConversation",
    "listResearchConversations", "createResearchConversation",
    "getResearchConversation", "renameResearchConversation",
    "archiveResearchConversation", "deleteResearchConversation",
];

test("no conversation helper sends a user or owner id", () => {
    // The server scopes every read and write to the authenticated caller. A
    // client-supplied owner would be a claim the server had to trust.
    const api = src("lib/api.js");
    for (const name of CONVERSATION_HELPERS) {
        const body = fnBody(api, name);
        assert.ok(body, `${name} is not defined`);
        assert.ok(!/user_id|owner_id|client_id/.test(body),
            `${name} sends an owner id the server would have to trust`);
    }
});

test("a session id is escaped before it reaches a URL", () => {
    const api = src("lib/api.js");
    for (const name of ["getConversation", "renameConversation", "deleteConversation",
                        "getResearchConversation", "renameResearchConversation",
                        "archiveResearchConversation", "deleteResearchConversation"]) {
        const body = fnBody(api, name);
        assert.ok(body, `${name} is not defined`);
        assert.ok(body.includes("encodeURIComponent(session_id)"),
            `${name} interpolates a session id into a URL unescaped`);
    }
});

test("restored messages go through the shared rehydration, not a local copy", () => {
    // A second copy is a second place for a trust signal to be dropped.
    for (const [path, fn] of [
        ["components/client/ModChatbot.jsx", "toClientMessages"],
        ["components/lawyer/AILegalPage.jsx", "toResearchMessages"],
    ]) {
        assert.ok(src(path).includes(`${fn}(`),
            `${path} rehydrates stored messages itself`);
    }
});

test("the lawyer surface shows a thread that stopped on a question", () => {
    const code = src("components/lawyer/AILegalPage.jsx");
    assert.match(code, /pendingQuestion/,
        "a reopened thread waiting on a clarification looks like it just stopped");
    assert.match(code, /awaiting_clarification/,
        "the conversation list does not flag threads waiting on an answer");
});

test("both surfaces scope their remembered conversation to the user", () => {
    // A shared key meant a different account inherited the previous one's
    // session id and the page tried to open it.
    for (const [name, path] of Object.entries(SURFACES)) {
        const code = src(path);
        if (!/writeActiveSession\(/.test(code)) continue;
        for (const m of code.matchAll(/writeActiveSession\(([^)]*)\)/g)) {
            assert.match(m[1], /user/,
                `${name} remembers a conversation without scoping it to a user`);
        }
    }
});

test("both surfaces re-bootstrap when the account changes", () => {
    // Mount-only would leave a new user looking at the previous one's thread.
    for (const path of ["components/client/ModChatbot.jsx",
                        "components/lawyer/AILegalPage.jsx"]) {
        assert.match(src(path), /\}, \[user\?\._id\]\);/,
            `${path} does not re-run its bootstrap on an account change`);
    }
});

test("signing out clears the remembered conversations", () => {
    assert.match(src("context/AuthContext.jsx"), /clearActiveSessions\(\)/,
        "logout leaves a record of what was being read on a shared machine");
});

test("both surfaces load every page of a restored conversation", () => {
    // A conversation is no longer bounded by a document, so one response is not
    // the whole history. Stopping at the first page would show a truncated
    // conversation as though it were complete.
    for (const path of ["components/client/ModChatbot.jsx",
                        "components/lawyer/AILegalPage.jsx"]) {
        const code = src(path);
        assert.match(code, /has_more/, `${path} ignores the pagination cursor`);
        assert.match(code, /next_cursor/, `${path} never follows the cursor`);
        assert.match(code, /mergeMessages\(/,
            `${path} concatenates pages instead of reconciling them by id`);
    }
});

/* ── P2.3 ──────────────────────────────────────────────────────────────── */

test("the lawyer New Chat button starts a real conversation", () => {
    // It only ran setMsgs([]), so the conversation carried on underneath: the
    // next message was appended to the same stored thread and its tail kept
    // feeding the model. A lawyer who believed they had started a fresh matter
    // was still being answered with the previous one in context.
    const code = src("components/lawyer/AILegalPage.jsx");
    assert.ok(!/onClick=\{\(\) => setMsgs\(\[\]\)\}/.test(code),
        "New Chat still only clears the display");
    assert.match(code, /onClick=\{\(\) => startConversation\(/,
        "New Chat does not start a conversation");
});

test("no callback reads the user without depending on it", () => {
    // useAuth resolves asynchronously, so the first render has a null user. A
    // callback memoised with [] captures that null forever, and
    // writeActiveSession then returns early because the storage key is scoped
    // by user id — the conversation is created, used, and never remembered.
    for (const [name, path] of Object.entries(SURFACES)) {
        const code = src(path);
        // Each useCallback body, paired with its dependency array.
        const callbacks = code.matchAll(
            /useCallback\(([\s\S]*?)\n\s*\}, \[([^\]]*)\]\);/g);
        for (const [, body, deps] of callbacks) {
            if (!/\buser\??\.\_id/.test(body)) continue;
            assert.match(deps, /user\?\._id/,
                `${name}: a callback reads user._id but does not depend on it`);
        }
    }
});

/* ══════════════════════════════════════════════════════════════════════════
 * P2.4 — a turn that outlives the connection that asked for it
 * ══════════════════════════════════════════════════════════════════════════ */

test("a reconnect asks about the interrupted turn instead of re-asking it", () => {
    // Re-sending the question would be a second question at a second cost. The
    // resume frame carries an id and no content, so the server can only read
    // its ledger — it has no way to start anything from it.
    const code = src("components/client/ModChatbot.jsx");
    assert.match(code, /action: "resume", client_message_id: waiting\.id/,
        "a reconnect does not recover the turn it was waiting on");
    const resume = code.match(/action: "resume"[\s\S]{0,160}/)[0];
    assert.ok(!/\bcontent\s*:/.test(resume),
        "the resume frame carries a question, so it can become one");
});

test("a refresh mid-turn remembers what it is waiting for", () => {
    // The server reports the in-flight turn on open; ignoring it left the user
    // looking at their own question with no reply and no explanation.
    const code = src("components/client/ModChatbot.jsx");
    assert.match(code, /header\?\.pending_turn/,
        "the client ignores the turn the server says is still running");
    assert.match(code, /newAttempt\(pending\.client_message_id\)/,
        "the recovered id is not the one the server named");
});

test("both surfaces can stop a turn, and stopping discards the answer", () => {
    // Aborting the wait alone is not stopping: the answer would still be filed
    // and would reappear on the next reload.
    // The client goes over HTTP, always — see "Stop never goes over the
    // WebSocket" below for why the socket cannot serve this.
    const client = src("components/client/ModChatbot.jsx");
    assert.match(client, /cancelClientTurn\(sid, waiting\.id\)/);

    const lawyer = src("components/lawyer/AILegalPage.jsx");
    assert.match(lawyer, /cancelResearchTurn\(sid, waiting\.id\)/,
        "the lawyer surface aborts the wait without cancelling the turn");
    assert.match(lawyer, /controller\?\.abort\(\)/);
});

test("neither surface waits forever", () => {
    // Nothing coming back at all — no answer, no error, no closed socket — used
    // to leave the dots spinning and the composer locked with no way out.
    for (const [name, path] of Object.entries(SURFACES)) {
        const code = src(path);
        assert.match(code, /TIMEOUT_MS/,
            `${name} has no deadline on a turn`);
    }
});

test("the client timeout is longer than the server's own", () => {
    // Otherwise the browser gives up first and reports "no answer" for turns
    // the server could have explained.
    const code = src("components/client/ModChatbot.jsx");
    const ms = Number(code.match(/CLIENT_TURN_TIMEOUT_MS = (\d+)/)[1]);
    assert.ok(ms > 120000, `client timeout ${ms}ms preempts the server's 120s`);
});

test("the lawyer retry reuses the attempt id, and only when it is safe", () => {
    // A retry with a fresh id is a second question. A retry after a 4xx repeats
    // a decision the server already made.
    const code = src("components/lawyer/AILegalPage.jsx");
    assert.match(code, /isAmbiguousFailure\(status\)/,
        "the lawyer surface retries failures a retry cannot fix");
    assert.match(code, /attempt = retryAttempt\(attempt\)/,
        "the retry does not keep the attempt's id");
});

test("progress stages are shown but never stored as messages", () => {
    // A stage is a note about the turn, not part of it. Appending one would put
    // "Searching Pakistani law" into the saved conversation.
    const code = src("components/client/ModChatbot.jsx");
    const branch = code.match(/msg\.type === "stage"[\s\S]{0,300}/)[0];
    assert.ok(!/setMsgs/.test(branch),
        "a progress stage is written into the transcript");
    assert.match(branch, /setStage\(/);
});

/* ══════════════════════════════════════════════════════════════════════════
 * P2.5.1 — cancellation and recovery correctness
 * ══════════════════════════════════════════════════════════════════════════ */

test("recovery reloads the whole thread, not the page it polled", () => {
    // It used to end with setMsgs(...) built from a single pageSize:100 read,
    // replacing the fully paginated history openConversation had just
    // assembled — so an interrupted turn landing on a long thread deleted the
    // earlier half of the conversation from the screen.
    const code = src("components/lawyer/AILegalPage.jsx");
    const fn = code.slice(code.indexOf("const recoverPending"),
                          code.indexOf("const openConversation"));
    assert.ok(!/setMsgs\(toResearchMessages\(data\.messages\)\)/.test(fn),
        "recovery still paints one page over the whole thread");
    assert.match(fn, /await loadThread\(id, ticket\)/,
        "recovery does not reload the full history");
    // And one loop serves both, so they cannot drift apart again.
    assert.match(code, /const loadThread = useCallback/);
    const open = code.slice(code.indexOf("const openConversation"));
    assert.match(open.slice(0, 600), /await loadThread\(id, ticket\)/,
        "opening no longer shares the paging loop");
});

test("the pending-turn header comes from the opening read", () => {
    // This used to be a real hazard: opening walked every page in a loop and
    // overwrote the header each time, so a multi-page thread took its header
    // from the LAST page — and the server reports `pending_turn` only on the
    // opening read. Recovery was silently absent from exactly the long threads
    // it mattered most for.
    //
    // Lazy loading removes the loop, so there is one read and one header. The
    // property is now structural, and what has to be asserted is that the
    // opening read carries NO cursor — a cursored read reports no pending
    // turn, by design.
    for (const [name, path] of [["client", "components/client/ModChatbot.jsx"],
                                ["lawyer", "components/lawyer/AILegalPage.jsx"]]) {
        const code = src(path);
        assert.ok(!/header = header \|\| data;/.test(code),
            `${name} still carries the multi-page header loop`);
        assert.match(code, /pending_turn/,
            `${name} ignores the unfinished turn the server reports`);
    }
    // The client reads it off the opening response directly.
    assert.match(src("components/client/ModChatbot.jsx"),
        /const pending = header\?\.pending_turn;/);
    // The lawyer surface passes the opening response through as the header.
    assert.match(src("components/lawyer/AILegalPage.jsx"),
        /header: data,/);
});

test("recovery says so when it gives up", () => {
    // A banner that simply disappears leaves the user believing an answer is
    // still on its way.
    const code = src("components/lawyer/AILegalPage.jsx");
    const fn = code.slice(code.indexOf("const recoverPending"),
                          code.indexOf("const openConversation"));
    assert.match(fn, /didn't finish/,
        "the poll gives up silently");
});

test("every wait for an answer is bounded, including a recovered one", () => {
    // Recovery used to set the attempt and the typing indicator without arming
    // a deadline, so a turn whose worker had died left the dots spinning and
    // the composer locked — the one failure a user cannot get out of, reachable
    // only through the path that exists to rescue them.
    const code = src("components/client/ModChatbot.jsx");
    assert.match(code, /const awaitTurn = useCallback/,
        "there is no single place that arms the deadline");
    // Both entry points go through it.
    assert.match(code, /awaitTurn\(newAttempt\(pending\.client_message_id\)\)/,
        "the recovered wait does not go through awaitTurn");
    assert.match(code, /awaitTurn\(attempt\);/,
        "the fresh send does not go through awaitTurn");
    // And nothing starts a wait behind awaitTurn's back. Outside its body,
    // every assignment to attemptRef clears it — a live attempt installed
    // anywhere else is a wait with no deadline on it.
    const bodyStart = code.indexOf("const awaitTurn = useCallback");
    const bodyEnd = code.indexOf("    }, []);", bodyStart);
    const elsewhere = code.slice(0, bodyStart) + code.slice(bodyEnd);
    const strays = (elsewhere.match(/attemptRef\.current = (\w+)/g) || [])
        .filter(line => !line.endsWith("null"));
    assert.deepEqual(strays, [],
        "an attempt is installed outside awaitTurn, skipping the deadline");
});

test("Stop still works when the socket is gone", () => {
    // The socket is exactly what is missing in the case Stop matters most: the
    // connection dropped, the turn is still running server-side, and the user
    // wants it to end. Returning silently there left a dead button.
    const code = src("components/client/ModChatbot.jsx");
    const fn = code.slice(code.indexOf("const stop = async"),
                          code.indexOf("const send ="));
    assert.match(fn, /cancelClientTurn\(sid, waiting\.id\)/,
        "Stop has no HTTP fallback for a closed socket");
    assert.ok(!/if \(!waiting \|\| !socket\.isOpen\(\)\) return;/.test(fn),
        "Stop still gives up when the socket is closed");
});

test("the client reports the server's cancellation outcome, not its own", () => {
    // "Stopped." for a turn that had already answered is a claim the next
    // reload contradicts.
    const code = src("components/client/ModChatbot.jsx");
    const branch = code.match(/msg\.type === "cancelled"[\s\S]{0,700}/)[0];
    assert.match(branch, /msg\.content/,
        "the client invents its own cancellation wording");
});

/* ══════════════════════════════════════════════════════════════════════════
 * Cancellation transport, and clearing a jurisdiction
 * ══════════════════════════════════════════════════════════════════════════ */

test("Stop never goes over the WebSocket", () => {
    // The server reads one frame at a time from a connection and is parked
    // inside the graph for the whole turn, so a cancel frame sent down the same
    // socket is not read until generation FINISHES — at which point the turn
    // has completed and there is nothing left to cancel. Stop reported success
    // and stopped nothing.
    const code = src("components/client/ModChatbot.jsx");
    const fn = code.slice(code.indexOf("const stop = async"),
                          code.indexOf("const send ="));
    assert.match(fn, /await cancelClientTurn\(sid, waiting\.id\)/,
        "Stop does not use the HTTP endpoint");
    assert.ok(!/action: "cancel"/.test(fn),
        "Stop still sends a cancel frame the server cannot read while busy");
});

test("the chat frame sends an explicit null to clear a jurisdiction", () => {
    // The server distinguishes absent from null; sending nothing at all would
    // leave a previously chosen province in force with no way back to a
    // national search.
    const code = src("components/client/ModChatbot.jsx");
    assert.match(code, /province: province \|\| null/,
        "the client cannot express \"All Pakistan\"");
});

test("the lawyer Stop reports the server's outcome too", () => {
    // Displaying "Stopped." regardless is a claim the next reload contradicts:
    // the answer it says was discarded is sitting in the thread.
    const code = src("components/lawyer/AILegalPage.jsx");
    assert.match(code, /stopNoticeRef\.current = data\?\.message/,
        "the lawyer surface ignores the server's cancellation outcome");
    assert.ok(!/content: "Stopped\.", notice: true/.test(code),
        "the lawyer surface still hard-codes its cancellation wording");
});

test("both surfaces restore and render the audit status", () => {
    // The live answer, the replayed turn and the restored message must report
    // the same thing. An answer that warned about its audit record and then
    // stopped warning after a refresh is worse than one that never warned —
    // the user concludes the first warning was noise.
    const lib = src("lib/conversations.js");
    const restores = lib.match(/auditSaved: m\.audit_saved !== false/g) || [];
    assert.equal(restores.length, 2,
        "one of the two surfaces does not restore the audit status");
    assert.match(lib, /auditPending: m\.audit_pending === true/);

    for (const path of ["components/client/ModChatbot.jsx",
                        "components/lawyer/AILegalPage.jsx"]) {
        const code = src(path);
        assert.match(code, /audit_saved !== false/,
            `${path} drops the audit status from a live answer`);
        assert.match(code, /auditNotice\(m\)/,
            `${path} never renders the audit status`);
    }
});

test("neither surface invents its own audit wording", () => {
    // One helper, so a client and a lawyer cannot be told different things
    // about the same fact.
    for (const path of ["components/client/ModChatbot.jsx",
                        "components/lawyer/AILegalPage.jsx"]) {
        const code = src(path);
        assert.ok(!/Audit record pending/.test(code),
            `${path} hard-codes wording that belongs in lib/trust`);
        assert.ok(!/Not recorded in the audit trail/.test(code),
            `${path} hard-codes wording that belongs in lib/trust`);
    }
});

/* ══════════════════════════════════════════════════════════════════════════
 * Conversation lists — every conversation must be reachable
 * ══════════════════════════════════════════════════════════════════════════ */

test("both sidebars follow a cursor instead of a fixed cap", () => {
    // They asked for 50 and stopped. A user with a fifty-first conversation
    // could not reach it by any route — not slow, unreachable.
    for (const [name, path] of [["client", "components/client/ModChatbot.jsx"],
                                ["lawyer", "components/lawyer/AILegalPage.jsx"]]) {
        const code = src(path);
        assert.match(code, /const loadHistory = useCallback/,
            `${name} sidebar has no paged loader`);
        assert.match(code, /after: listCursor/,
            `${name} sidebar never continues from a cursor`);
        assert.ok(!/limit: 50/.test(code),
            `${name} sidebar still asks for a fixed 50`);
    }
});

test("load more follows has_more, not whether rows came back", () => {
    // The research list filters out threads on revoked cases AFTER reading
    // them, so a page can legitimately come back empty while more accessible
    // threads wait behind it. Gating the button on rows.length would strand
    // everything past a block of revoked matters.
    for (const path of ["components/client/ModChatbot.jsx",
                        "components/lawyer/AILegalPage.jsx"]) {
        const code = src(path);
        assert.match(code, /\{listMore && \(/,
            `${path} gates "load more" on something other than has_more`);
        assert.match(code, /setListMore\(!!data\.has_more\)/);
    }
});

test("appending a page cannot render the same conversation twice", () => {
    // A conversation answered while the user is scrolling legitimately appears
    // in a later read. Rendering it twice looks like data corruption.
    for (const path of ["components/client/ModChatbot.jsx",
                        "components/lawyer/AILegalPage.jsx"]) {
        const code = src(path);
        assert.match(code, /seen\.has\(r\.session_id\)/,
            `${path} appends pages without de-duplicating`);
    }
});

test("a slow list response cannot paint over a newer one", () => {
    // Typing in the search box issues several requests; the slowest must not
    // win. Same generation ticket the conversation opens use.
    for (const path of ["components/client/ModChatbot.jsx",
                        "components/lawyer/AILegalPage.jsx"]) {
        const code = src(path);
        assert.match(code, /listGeneration\.next\(\)/);
        assert.match(code, /listGeneration\.isCurrent\(ticket\)/,
            `${path} lets a stale list response win`);
    }
});

test("search is debounced and restarts from the top", () => {
    // A request per keystroke has the same stale-response problem at several
    // times the cost, and a search continuing from an old cursor would page
    // through the wrong result set.
    for (const path of ["components/client/ModChatbot.jsx",
                        "components/lawyer/AILegalPage.jsx"]) {
        const code = src(path);
        assert.match(code, /setTimeout\(\s*\(\) => \{ loadHistory\(\{ term: search \|\| null \}\); \}, 250\)/,
            `${path} does not debounce its search`);
    }
});

test("the list helpers send the cursor and the search term", () => {
    const api = src("lib/api.js");
    for (const fn of ["listConversations", "listResearchConversations"]) {
        const body = api.slice(api.indexOf(`export async function ${fn}`));
        const head = body.slice(0, body.indexOf("\n}"));
        assert.match(head, /params\.set\('after', after\)/, fn);
        assert.match(head, /params\.set\('search', search\)/, fn);
    }
});

/* ══════════════════════════════════════════════════════════════════════════
 * Lazy history — a conversation opens at its end
 * ══════════════════════════════════════════════════════════════════════════ */

test("neither surface downloads a whole conversation to open it", () => {
    // Opening used to walk forward from the first message until has_more went
    // false — every page of a two-year thread before anything appeared.
    for (const [name, path] of [["client", "components/client/ModChatbot.jsx"],
                                ["lawyer", "components/lawyer/AILegalPage.jsx"]]) {
        const code = src(path);
        const open = name === "client"
            ? code.slice(code.indexOf("const openConversation"),
                         code.indexOf("/* ── New chat"))
            : code.slice(code.indexOf("const loadThread"),
                         code.indexOf("const loadOlder"));
        assert.ok(!/for \(let guard = 0; guard < 200/.test(open),
            `${name} still walks every page on open`);
        assert.ok(!/afterSeq: cursor/.test(open),
            `${name} still pages forward from the start`);
    }
});

test("both surfaces fetch older messages on demand", () => {
    for (const [name, path] of [["client", "components/client/ModChatbot.jsx"],
                                ["lawyer", "components/lawyer/AILegalPage.jsx"]]) {
        const code = src(path);
        assert.match(code, /const loadOlder = useCallback/,
            `${name} has no way back through history`);
        assert.match(code, /beforeSeq: olderCursor/,
            `${name} does not continue from the older cursor`);
        assert.match(code, /setHasOlder\(!!data\.has_older\)/);
    }
});

test("loading older messages does not cancel the open it belongs to", () => {
    // `current()` reads the generation without claiming it. Calling `next()`
    // here would invalidate the very open this fetch is part of — the guard
    // exists to notice the user switching away, not to cause it.
    for (const path of ["components/client/ModChatbot.jsx",
                        "components/lawyer/AILegalPage.jsx"]) {
        const code = src(path);
        const fn = code.slice(code.indexOf("const loadOlder = useCallback"));
        const body = fn.slice(0, fn.indexOf("}, ["));
        assert.match(body, /openGeneration\.current\(\)/,
            `${path} claims a new generation when loading older messages`);
        assert.ok(!/openGeneration\.next\(\)/.test(body),
            `${path} cancels its own open by claiming a generation`);
        assert.match(body, /openGeneration\.isCurrent\(ticket\)/,
            `${path} lets a stale older page land on another conversation`);
    }
});

test("an older page is merged, never concatenated blindly", () => {
    // mergeMessages sorts by the server-allocated seq and de-duplicates by id,
    // so a message arriving twice — once live, once in a page — renders once
    // and in the right place.
    for (const path of ["components/client/ModChatbot.jsx",
                        "components/lawyer/AILegalPage.jsx"]) {
        const code = src(path);
        const fn = code.slice(code.indexOf("const loadOlder = useCallback"));
        assert.match(fn.slice(0, fn.indexOf("}, [")), /mergeMessages\(\s*current,/,
            `${path} does not merge older messages into the transcript`);
    }
});

test("the load-earlier control follows has_older", () => {
    for (const path of ["components/client/ModChatbot.jsx",
                        "components/lawyer/AILegalPage.jsx"]) {
        const code = src(path);
        assert.match(code, /\{hasOlder && \(/, path);
        assert.match(code, /Load earlier messages/, path);
    }
});

test("switching conversation resets the history cursor", () => {
    // A cursor from the previous conversation would page into the wrong
    // thread's history.
    const client = src("components/client/ModChatbot.jsx");
    const open = client.slice(client.indexOf("const openConversation"));
    assert.match(open.slice(0, open.indexOf("}, [")), /setOlderCursor\(null\)/,
        "the client keeps the previous conversation's cursor");

    const lawyer = src("components/lawyer/AILegalPage.jsx");
    assert.match(lawyer, /setOlderCursor\(thread\.olderCursor\)/,
        "the lawyer surface never adopts the new thread's cursor");
});

test("recovery reloads the newest page and resets the cursor with it", () => {
    // The recovered answer is the newest message, so the newest page is the
    // right reload — and the thread has grown, so the old boundary no longer
    // describes it.
    const code = src("components/lawyer/AILegalPage.jsx");
    const fn = code.slice(code.indexOf("const recoverPending"),
                          code.indexOf("const openConversation"));
    assert.match(fn, /setMsgs\(thread\.messages\)/);
    assert.match(fn, /setOlderCursor\(thread\.olderCursor\)/,
        "recovery leaves a stale older cursor behind");
});

test("the message helpers can ask for older messages", () => {
    const api = src("lib/api.js");
    for (const fn of ["getConversation", "getResearchConversation"]) {
        const body = api.slice(api.indexOf(`export async function ${fn}`));
        const head = body.slice(0, body.indexOf("\n}"));
        assert.match(head, /params\.set\('before_seq', String\(beforeSeq\)\)/, fn);
    }
});

/* ══════════════════════════════════════════════════════════════════════════
 * Lawyer research progress stages
 * ══════════════════════════════════════════════════════════════════════════ */

test("the lawyer surface reports what the pipeline is doing", () => {
    // It showed a blinking cursor for the whole turn, which is
    // indistinguishable from a hang. The stage says whether a long wait is a
    // hard search or a shaky answer being re-checked.
    const code = src("components/lawyer/AILegalPage.jsx");
    assert.match(code, /const watchStage = useCallback/,
        "the lawyer surface never asks what the pipeline is doing");
    assert.match(code, /researchTurnStatus\(sid, attemptId\)/);
    assert.match(code, /\{m\.streaming && stage && \(/,
        "the stage is fetched and never shown");
});

test("the stage poll stops when the turn does", () => {
    // A poll that outlives its turn is a request every two seconds forever.
    const code = src("components/lawyer/AILegalPage.jsx");
    const fn = code.slice(code.indexOf("const watchStage = useCallback"));
    const body = fn.slice(0, fn.indexOf("}, ["));
    // Stops on a settled turn...
    assert.match(body, /data\.status !== "in_progress"/);
    assert.match(body, /clearInterval\(stagePollRef\.current\)/);
    // ...and on the attempt moving on.
    assert.match(body, /attemptRef\.current\?\.id !== attemptId/);
    // And unconditionally when the request settles, rather than in each branch
    // — the branch that forgot would be the rare one nobody exercises.
    assert.match(code, /stopWatchingStage\(\);\s*\n\s*setLoading\(false\);/);
});

test("a stale poll cannot label the wrong turn", () => {
    // The attempt id is captured at call time and compared before every write,
    // so a poll left over from a previous question cannot narrate the current
    // one.
    const code = src("components/lawyer/AILegalPage.jsx");
    const fn = code.slice(code.indexOf("const watchStage = useCallback"));
    const body = fn.slice(0, fn.indexOf("}, ["));
    assert.match(body, /if \(attemptRef\.current\?\.id === attemptId\) setStage/);
});

test("a same-id retry re-arms the poll", () => {
    // Retrying keeps the turn id but replaces the attempt object, which is
    // what the poll watches — so it has to be started again or the retry runs
    // with no progress at all.
    const code = src("components/lawyer/AILegalPage.jsx");
    const retries = code.match(/watchStage\(sid, attempt\.id\)/g) || [];
    assert.equal(retries.length, 2,
        "the retry path does not re-arm the progress poll");
});

/* ══════════════════════════════════════════════════════════════════════════
 * Conversation search — finding a thread by what was said in it
 * ══════════════════════════════════════════════════════════════════════════ */

test("both surfaces search message bodies, not just titles", () => {
    // A sidebar capped at fifty entries with a title-only filter meant a
    // conversation from six months ago was reachable only by scrolling past
    // everything since.
    for (const [name, path, fn] of [
        ["client", "components/client/ModChatbot.jsx", "searchConversations"],
        ["lawyer", "components/lawyer/AILegalPage.jsx", "searchResearchConversations"],
    ]) {
        const code = src(path);
        assert.ok(code.includes(`await ${fn}(phrase)`),
            `${name} never searches message bodies`);
        assert.match(code, /Found in messages/,
            `${name} fetches message matches and never shows them`);
    }
});

test("the message search runs under the list's generation ticket", () => {
    // It is a second await in the same loader. Without the check, a response
    // for a term the user has moved on from paints results over the current
    // one — the same race the list itself already guards.
    for (const path of ["components/client/ModChatbot.jsx",
                        "components/lawyer/AILegalPage.jsx"]) {
        const code = src(path);
        const block = code.slice(code.indexOf("Message-body search"));
        const body = block.slice(0, block.indexOf("setListCursor"));
        assert.match(body, /if \(!listGeneration\.isCurrent\(ticket\)\) return;/,
            `${path} lets a stale message search land`);
    }
});

test("a one-character query does not trigger a text search", () => {
    // One character matches most of a corpus and ranks none of it usefully,
    // and it costs a text query per keystroke.
    for (const path of ["components/client/ModChatbot.jsx",
                        "components/lawyer/AILegalPage.jsx"]) {
        const code = src(path);
        assert.match(code, /phrase\.length >= MIN_SEARCH_CHARS/, path);
        assert.match(code, /const MIN_SEARCH_CHARS = 2;/, path);
    }
});

test("the search reads the term it was called with, not component state", () => {
    // The list above was filtered by the caller's term. Reading state here
    // would let the two searches disagree about what was asked.
    for (const path of ["components/client/ModChatbot.jsx",
                        "components/lawyer/AILegalPage.jsx"]) {
        const code = src(path);
        assert.match(code, /const phrase = \(term \|\| ""\)\.trim\(\);/, path);
    }
});

test("unsearchable legacy history is disclosed, not hidden", () => {
    // The thread is still there and still findable by name. Silence would have
    // the user conclude it is gone.
    for (const path of ["components/client/ModChatbot.jsx",
                        "components/lawyer/AILegalPage.jsx"]) {
        const code = src(path);
        assert.match(code, /has_unsearchable_history/, path);
        // Collapsed, because the sentence is wrapped across JSX lines.
        const flat = src(path).replace(/\s+/g, " ");
        assert.ok(flat.includes("can only be found by their title"), path);
    }
});

test("a message hit keeps its snippet", () => {
    // Merging hits into the title list would drop it, and the snippet is the
    // only part that tells the user why the result came back.
    for (const path of ["components/client/ModChatbot.jsx",
                        "components/lawyer/AILegalPage.jsx"]) {
        assert.match(src(path), /\{hit\.snippet\}/, path);
    }
});
