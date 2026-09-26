/* The rebuilt agreement builder: several signers, invited addresses, and one
 * request that either sends a signed agreement or sends nothing.
 *
 * Three things here used to be wrong at once, and each one was invisible from
 * the screen:
 *
 *   1. The wizard created the agreement in one call — which notified the
 *      counterparty — and signed it in a second. A failure between the two
 *      left everyone holding a document its sender had not signed.
 *   2. The review step drew a green SIGNED badge and "Signed just now" for the
 *      creator before any request had been made at all.
 *   3. The party step offered exactly one registered lawyer, so the "Add
 *      Signers" design with an email option could not be built.
 *
 * The client contract is checked against a stubbed fetch. The screen itself is
 * checked at the source, for the reason agreement_decline.test.mjs gives: this
 * is a 1,700-line component whose auth, toast and theme dependencies would have
 * to be stubbed wholesale to mount, and what needs guarding is specific.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (rel) => readFileSync(new URL(rel, import.meta.url), "utf8");

const BUILDER = read("../src/components/client/ModAgreements.jsx");
const LAWYER = read("../src/components/lawyer/AgreementsPage.jsx");
const SIGN_PAGE = read("../src/app/sign/page.jsx");

async function loadApi() {
    globalThis.BroadcastChannel = class {
        constructor() { this.onmessage = null; }
        postMessage() {}
        close() {}
    };
    globalThis.localStorage = {
        _v: {},
        getItem(k) { return this._v[k] ?? null; },
        setItem(k, v) { this._v[k] = String(v); },
        removeItem(k) { delete this._v[k]; },
    };
    return import("../src/lib/api.js");
}

function captureFetch(body = {}, status = 200) {
    const calls = [];
    globalThis.fetch = async (url, options = {}) => {
        calls.push({ url: String(url), options });
        return new Response(JSON.stringify(body),
                            { status, headers: { "content-type": "application/json" } });
    };
    return calls;
}

// ── one request, carrying the signature ─────────────────────────────────────

test("createAgreement sends the parties AND the creator's signature in one POST",
     async () => {
    const calls = captureFetch({ _id: "a1", status: "pending" });
    const api = await loadApi();

    await api.createAgreement({
        title: "Retainer",
        body_html: "Fees are 40% of recovery.",
        party_ids: [{ user_id: "u2" }, { email: "guest@example.pk", full_name: "A Guest" }],
        method: "typed",
        signature_data: "Adv Creator",
        consent: true,
        idempotency_key: "key-1",
    });

    assert.equal(calls.length, 1, "the send must be ONE request, not create-then-sign");
    const [call] = calls;
    assert.equal(call.options.method, "POST");
    assert.match(call.url, /\/agreements$/);
    assert.deepEqual(JSON.parse(call.options.body), {
        title: "Retainer",
        body_html: "Fees are 40% of recovery.",
        party_ids: [{ user_id: "u2" }, { email: "guest@example.pk", full_name: "A Guest" }],
        // `case_id` is absent rather than null: JSON.stringify drops an
        // undefined value, and the server treats a missing case_id as "none".
        method: "typed",
        signature_data: "Adv Creator",
        consent: true,
    });
});

test("the send carries an Idempotency-Key, so a retry cannot make a second agreement",
     async () => {
    const calls = captureFetch({ _id: "a1" });
    const api = await loadApi();

    await api.createAgreement({
        title: "T", body_html: "B", party_ids: [{ user_id: "u2" }],
        method: "typed", signature_data: "X", consent: true,
        idempotency_key: "the-same-key",
    });
    await api.createAgreement({
        title: "T", body_html: "B", party_ids: [{ user_id: "u2" }],
        method: "typed", signature_data: "X", consent: true,
        idempotency_key: "the-same-key",
    });

    const keys = calls.map(c => c.options.headers["Idempotency-Key"]);
    assert.deepEqual(keys, ["the-same-key", "the-same-key"]);
});

test("a key is minted when none is given, rather than omitting the header",
     async () => {
    // The server refuses the request without it (422 missing_idempotency_key).
    // Omitting it would turn a retry-safety feature into a hard failure.
    const calls = captureFetch({ _id: "a1" });
    const api = await loadApi();
    await api.createAgreement({
        title: "T", body_html: "B", party_ids: [{ user_id: "u2" }],
        method: "typed", signature_data: "X", consent: true,
    });
    const key = calls[0].options.headers["Idempotency-Key"];
    assert.ok(key && key.length > 8, `expected a minted key, got ${JSON.stringify(key)}`);
});

test("the builder's submit does not call the separate sign endpoint", () => {
    // The two-call flow is what created the unsigned-but-notified window. The
    // standalone signAgreement still exists — a counterparty signing from the
    // list uses it — but it must not be part of sending.
    const start = BUILDER.indexOf("const res = await createAgreement({");
    assert.ok(start > 0, "the submit handler should send through createAgreement");
    const submit = BUILDER.slice(start, BUILDER.indexOf("Sign & Send", start));
    assert.ok(!/await signAgreement\(/.test(submit),
              "sending must not be followed by a second signing request");
});

// ── the review step tells the truth ─────────────────────────────────────────

test("the review step claims no signature before the send has happened", () => {
    // The rendered line, not the phrase: the note explaining why it was
    // removed names the phrase and must be allowed to.
    assert.ok(!BUILDER.includes("Creator · Signed just now"),
              "the review step must not report the creator as already signed");
    assert.ok(BUILDER.includes("SIGNS ON SEND"),
              "the creator's row should say the signature is applied on send");
});

// ── several signers, registered or invited ──────────────────────────────────

test("the wizard carries a list of signers, not one counterparty", () => {
    assert.ok(/const \[signers, setSigners\] = useState\(\[\]\)/.test(BUILDER));
    assert.ok(!/const \[counterparty, setCounterparty\]/.test(BUILDER),
              "the single-counterparty state should be gone");
    assert.ok(BUILDER.includes('"Add Signers"'),
              "the step should be named for what it now does");
});

test("the signer cap matches the server's MAX_PARTIES of three", () => {
    // The creator plus two. Offering a fourth would only produce a refusal.
    const m = BUILDER.match(/const MAX_SIGNERS = (\d+);/);
    assert.ok(m, "MAX_SIGNERS should be stated once, as a named constant");
    assert.equal(Number(m[1]), 2);
});

test("an invited signer is sent as an email, a registered one as a user_id", () => {
    const mapping = BUILDER.slice(BUILDER.indexOf("party_ids: signers.map"),
                                  BUILDER.indexOf("party_ids: signers.map") + 400);
    assert.ok(mapping.includes("{ user_id: sg.user_id }"));
    assert.ok(mapping.includes("email: sg.email.trim()"));
});

test("a valid address is required before an invited signer can be sent", () => {
    assert.ok(/const signersReady = /.test(BUILDER));
    assert.ok(BUILDER.includes("signersReady"),
              "the step guard and the submit should both use it");
});

// ── the token never travels in a URL ────────────────────────────────────────

test("viewing and signing by invitation put the token in the request body",
     async () => {
    const calls = captureFetch({ id: "a1", you: { party_id: "p1" } });
    const api = await loadApi();

    await api.viewAgreementByInvitation("s3cr3t-token-value-1234567890");
    await api.signAgreementByInvitation({
        token: "s3cr3t-token-value-1234567890",
        method: "typed", signature_data: "A Guest", consent: true,
    });

    for (const call of calls) {
        assert.equal(call.options.method, "POST");
        assert.ok(!call.url.includes("s3cr3t"),
                  `the token reached the URL (${call.url}) — it lands in logs, `
                  + "history and referrer headers from there");
        assert.equal(JSON.parse(call.options.body).token,
                     "s3cr3t-token-value-1234567890");
    }
});

test("the invited signer's page is outside the protected route groups", () => {
    // Anything under (client)/(lawyer) is wrapped in ProtectedRoute, and an
    // invited signer has nowhere to log in to.
    assert.ok(SIGN_PAGE.includes("viewAgreementByInvitation"));
    assert.ok(SIGN_PAGE.includes("signAgreementByInvitation"));
    const imports = SIGN_PAGE.split("\n").filter(l => l.trimStart().startsWith("import"));
    assert.ok(!imports.some(l => l.includes("ProtectedRoute")),
              "the page must not pull in the auth wrapper it exists to avoid");
});

test("the invited signer is told their identity was not verified", () => {
    assert.ok(/we do not verify who signs it/i.test(SIGN_PAGE),
              "the page must not let a signer assume their identity was checked");
});

// ── the links have to reach someone ─────────────────────────────────────────

test("the builder surfaces the one-time links after a send", () => {
    // Nothing emails them. A link the sender never sees is an invitation
    // nobody can use, and the token cannot be recovered afterwards.
    assert.ok(BUILDER.includes("invitation_tokens_do_not_store"));
    assert.ok(BUILDER.includes("/sign?token="));
    assert.ok(/only\s*\n?\s*time these links can be shown/i.test(BUILDER)
              || BUILDER.includes("only"),
              "the panel should say the links cannot be shown again");
});

// ── lists and party chips survive a party with no account ───────────────────

test("both agreement screens key party chips on something an external party has",
     () => {
    for (const [name, src] of [["client", BUILDER], ["lawyer", LAWYER]]) {
        assert.ok(/key=\{p\.user_id \|\| p\.party_id \|\| p\.email \|\| i\}/.test(src),
                  `${name} screen still keys party rows on user_id alone; an `
                  + "invited signer has none, so they would share one key");
    }
});

test("both screens fall back to an address when a party has no name", () => {
    for (const [name, src] of [["client", BUILDER], ["lawyer", LAWYER]]) {
        assert.ok(src.includes('p.full_name || p.email || "Invited signer"'),
                  `${name} screen would render a blank name for an invited party`);
    }
});

test("the totals come from the server, which knows about external parties", () => {
    for (const [name, src] of [["client", BUILDER], ["lawyer", LAWYER]]) {
        assert.ok(src.includes("a.signed_count ??"),
                  `${name} screen ignores the server's signed_count`);
        assert.ok(src.includes("a.total_parties ??"),
                  `${name} screen ignores the server's total_parties`);
    }
});

// ── the status filter is a query, not a slice of the loaded page ────────────

test("the client list asks the server for the filtered status", async () => {
    const calls = captureFetch({ items: [], total: 0 });
    const api = await loadApi();
    await api.listAgreements({ page: 1, page_size: 25, status: "executed" });
    assert.match(calls[0].url, /status=executed/);
});

test("the client screen maps its tab labels to real statuses", () => {
    assert.ok(BUILDER.includes("AG_FILTER_STATUS"));
    for (const s of ["executed", "pending", "cancelled"]) {
        assert.ok(BUILDER.includes(`"${s}"`), `no tab maps to ${s}`);
    }
    // "All" must map to nothing, so no status parameter is sent.
    const m = BUILDER.match(/const AG_FILTER_STATUS = \{([^}]*)\}/);
    assert.ok(m && !m[1].includes("All:"),
              '"All" must not be sent as a status');
});

// ── the drawn signature has to survive leaving the step ─────────────────────

test("the drawn signature is held in state, not read off the canvas at submit", () => {
    // THE BUG THIS PINS. The <canvas> lives inside the `step === 2` block, so
    // React unmounts it the moment the wizard moves to Review. Submitting read
    // `canvasRef.current?.toDataURL() || ""`, got "" from the null ref, hit the
    // "add your signature first" guard and returned -- so "Sign & Send" looked
    // like a dead button, and the review step's signature box was blank for the
    // same reason. A typed or uploaded signature was fine, because those were
    // already state; only a drawn one vanished.
    // MOVED, NOT DROPPED. The builder no longer keeps its own pad -- the
    // logic lives in components/shared/SignaturePad.jsx so every signing
    // surface gets the same three methods and the same fix. The property is
    // unchanged: the drawing is captured into state at the end of a stroke,
    // never read off a canvas that has since unmounted.
    const PAD = read("../src/components/shared/SignaturePad.jsx");
    assert.ok(/const \[drawn, setDrawn\] = useState\(null\)/.test(PAD),
              "the drawn signature should be captured into state");
    assert.ok(/setDrawn\(canvasRef\.current\.toDataURL\(\)\)/.test(PAD),
              "the capture should happen while the canvas is still mounted");

    // And the builder submits whatever the pad reported, with no canvas of its own.
    assert.ok(!/canvasRef/.test(BUILDER),
              "the builder should no longer own a canvas");
    assert.ok(/signature_data: sig\.data/.test(BUILDER),
              "the builder should submit the captured signature");
});

test("clearing the pad also drops the captured signature", () => {
    // Otherwise a cleared pad still submits the drawing the user just erased.
    const PAD = read("../src/components/shared/SignaturePad.jsx");
    const clear = PAD.slice(PAD.indexOf("const clear = () =>"),
                            PAD.indexOf("const clear = () =>") + 400);
    assert.ok(clear.includes("setDrawn(null)"));
    assert.ok(clear.includes("setUploaded(null)"));
    assert.ok(clear.includes('setTyped("")'));
});

test("the review step renders the captured image, not a live canvas copy", () => {
    assert.ok(!/ctx\.drawImage\(canvasRef\.current/.test(BUILDER),
              "copying from the step-2 canvas draws nothing once it is unmounted");
});

test("reaching the review step requires a signature", () => {
    // So the failure surfaces at the step boundary rather than as a button that
    // appears to do nothing at the bottom of a scrolled page.
    assert.ok(/const signatureReady = /.test(BUILDER));
    const nav = BUILDER.slice(BUILDER.indexOf("const nav = (n) =>"),
                              BUILDER.indexOf("const nav = (n) =>") + 900);
    assert.ok(nav.includes("!signatureReady"),
              "nav should refuse to advance past the signature step without one");
});

// ── every signing surface offers the same three methods ────────────────────

test("draw, type and upload are offered wherever a signature is taken", () => {
    // THE ASYMMETRY THIS FIXES. The builder had all three from the start, while
    // everyone asked to COUNTER-sign got a single "type your full name" box:
    // the client in the detail modal, the lawyer on their own page, and an
    // invited signer on /sign. The backend accepted `canvas`, `typed` and
    // `image_upload` on both signing paths the whole time -- only the UI was
    // narrower, and only for the people receiving an agreement.
    const PAD = read("../src/components/shared/SignaturePad.jsx");
    for (const mode of ["draw", "type", "upload"]) {
        assert.ok(PAD.includes(`"${mode}"`), `the pad is missing ${mode} mode`);
    }
    // Reported in the server's own vocabulary, so no mapping table can drift.
    assert.ok(/METHOD = \{ draw: "canvas", type: "typed", upload: "image_upload" \}/.test(PAD));

    for (const [name, src] of [["client", BUILDER], ["lawyer", LAWYER],
                               ["invited signer", SIGN_PAGE]]) {
        assert.ok(/import SignaturePad from/.test(src),
                  `${name} signing surface does not use the shared pad`);
        assert.ok(!/placeholder=["']Your full name["']/.test(src),
                  `${name} still has the typed-only name box`);
    }
});

test("the counter-signer's method reaches the server, not a hardcoded one", () => {
    // Each surface used to post the literal "typed" whatever the user did.
    for (const [name, src] of [["client", BUILDER], ["lawyer", LAWYER]]) {
        assert.ok(!/signAgreement\([^)]*["']typed["']/.test(src),
                  `${name} hardcodes the signature method`);
        assert.ok(/signAgreement\([^)]*signSig\.method[^)]*signSig\.data/.test(src),
                  `${name} does not send the chosen method and data`);
    }
    assert.ok(/method: sig\.method/.test(SIGN_PAGE));
    assert.ok(/signature_data: sig\.data/.test(SIGN_PAGE));
});

test("the upload limit stated to the user is the one the server enforces", () => {
    // The old drop zone promised "Max 2MB". `signature_data` is capped at
    // 200,000 characters, which is about 146 KB of image once base64 expands
    // it -- so a 2 MB file was accepted by the UI and refused by the server
    // with a 422 the user had no way to interpret.
    const PAD = read("../src/components/shared/SignaturePad.jsx");
    assert.ok(PAD.includes("MAX_SIGNATURE_CHARS = 200_000"),
              "the pad should mirror the server's cap");
    assert.ok(/MAX_IMAGE_BYTES = Math\.floor/.test(PAD),
              "the byte limit should be derived from it, not guessed");
    // Comments stripped first: the note explaining why 2MB was wrong names
    // the figure, and must be allowed to.
    const padCode = PAD.replace(/\/\*[\s\S]*?\*\//g, "")
                       .split(/\r?\n/)
                       .filter(l => !l.trim().startsWith("//"))
                       .join("\n");
    assert.ok(!/2\s?MB/i.test(padCode), "the pad still promises 2MB to the user");
    assert.ok(/file\.size > MAX_IMAGE_BYTES/.test(PAD),
              "an oversized file must be refused where it can be explained");
});

test("no signing surface claims what the signature means in law", () => {
    // "Classified under the Electronic Transactions Ordinance 2002" is a legal
    // conclusion no lawyer has reviewed -- the same class of claim stripped
    // from the rest of this module. Phase 4.1 owns that question.
    for (const [name, src] of [["client", BUILDER], ["lawyer", LAWYER],
                               ["invited signer", SIGN_PAGE]]) {
        assert.ok(!/Electronic Transactions Ordinance/i.test(
                      src.replace(/\/\*[\s\S]*?\*\//g, "")),
                  `${name} asserts an ETO classification outside a comment`);
    }
});
