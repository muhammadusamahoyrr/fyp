/* Declining an agreement — the counterpart to signing.
 *
 * The backend has had POST /agreements/{id}/decline all along, and the UI had
 * no way to reach it. A client could sign or ignore, nothing else, while the
 * list rendered a "Rejected" filter for a state nothing could produce. A legal
 * product that lets someone commit but not refuse is one-sided.
 *
 * The client contract is checked against a stubbed fetch. The UI wiring is
 * checked at the source, because ModAgreements is a 1,400-line screen whose
 * dependencies (auth, toast, theme, hooks) would need stubbing wholesale to
 * mount — and what actually needs guarding is small and specific: that decline
 * is reachable, that it takes two deliberate actions, and that the old
 * "coming soon" placeholders are gone.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (rel) => readFileSync(new URL(rel, import.meta.url), "utf8");

// ── the client contract ──────────────────────────────────────────────────────

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

test("declineAgreement POSTs to the decline endpoint with the reason", async () => {
    const calls = [];
    globalThis.fetch = async (url, options = {}) => {
        calls.push({ url: String(url), options });
        return new Response(JSON.stringify({ id: "a1", status: "cancelled" }),
                            { status: 200, headers: { "content-type": "application/json" } });
    };
    const api = await loadApi();
    await api.declineAgreement("a1", "The fee schedule is wrong");

    const call = calls.find(c => c.url.includes("/agreements/a1/decline"));
    assert.ok(call, `no request to the decline endpoint; saw ${calls.map(c => c.url)}`);
    assert.equal(call.options.method, "POST");
    assert.deepEqual(JSON.parse(call.options.body),
                     { reason: "The fee schedule is wrong" });
});

test("an omitted or blank reason is sent as null, not an empty string", async () => {
    // The server bounds `reason` but treats it as optional. "" is not a reason,
    // and storing one would render an empty quote to the counterparty.
    const bodies = [];
    globalThis.fetch = async (url, options = {}) => {
        if (String(url).includes("/decline")) bodies.push(JSON.parse(options.body));
        return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
    };
    const api = await loadApi();
    await api.declineAgreement("a1");
    await api.declineAgreement("a2", "   ");
    await api.declineAgreement("a3", null);
    assert.deepEqual(bodies, [{ reason: null }, { reason: null }, { reason: null }]);
});

test("the agreement id is placed in the path, not the body", async () => {
    const urls = [];
    globalThis.fetch = async (url) => {
        urls.push(String(url));
        return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
    };
    const api = await loadApi();
    await api.declineAgreement("agr-123", "no");
    assert.ok(urls.some(u => u.endsWith("/agreements/agr-123/decline")), urls);
});

// ── the UI is actually wired ─────────────────────────────────────────────────

const AGREEMENTS = read("../src/components/client/ModAgreements.jsx");

test("the agreements screen imports and calls declineAgreement", () => {
    assert.match(AGREEMENTS, /import \{[^}]*declineAgreement[^}]*\} from "@\/lib\/api\.js"/,
        "declineAgreement is not imported");
    assert.match(AGREEMENTS, /await declineAgreement\(/,
        "declineAgreement is imported but never called");
});

test("declining takes two deliberate actions, not one click", () => {
    // Decline ends the agreement for every party and cannot be undone. A single
    // button beside "Sign Agreement" is one mis-click away from cancelling a
    // contract, so the destructive call must sit behind a confirmation.
    assert.match(AGREEMENTS, /declineOpen/,
        "no reveal/confirm state — decline appears to be a single click");
    const declineCall = AGREEMENTS.indexOf("await declineAgreement(");
    const confirmGate = AGREEMENTS.indexOf("setDeclineOpen(true)");
    assert.ok(confirmGate !== -1 && declineCall !== -1);
    assert.match(AGREEMENTS, /Confirm decline/,
        "no explicit confirm control");
});

test("the decline reason is bounded in the UI as it is on the server", () => {
    // AgreementDecline caps reason at 2000 characters. Letting the field exceed
    // that turns a considered refusal into a 422 after the user has typed it.
    assert.match(AGREEMENTS, /maxLength=\{2000\}/,
        "the reason field is not bounded to the server's limit");
});

test("the user is told decline is irreversible before confirming", () => {
    assert.match(AGREEMENTS, /cannot be undone/i);
});

// ── the placeholders are gone ────────────────────────────────────────────────

const PROFILE = read("../src/components/client/ModProfile.jsx");

test("the client profile no longer says session management is unavailable", () => {
    assert.doesNotMatch(PROFILE, /Session management is not available yet/,
        "the placeholder text survived the wiring");
    assert.doesNotMatch(PROFILE, /Session management coming soon/,
        "the 'coming soon' toast survived the wiring");
    assert.match(PROFILE, /SessionsPanel/, "the real panel is not mounted");
});

test("both shells mount the sessions panel", () => {
    const settings = read("../src/components/lawyer/SettingsPage.jsx");
    for (const [name, source] of [["client profile", PROFILE], ["lawyer settings", settings]]) {
        assert.match(source, /import SessionsPanel from "@\/components\/shared\/SessionsPanel\.jsx"/,
            `${name} does not import the panel`);
        assert.match(source, /<SessionsPanel[\s\S]{0,120}onSignedOut=\{logout\}/,
            `${name} mounts the panel without wiring onSignedOut to logout — ` +
            `revoking your own session would leave a signed-out page looking signed in`);
    }
});


// ── the lawyer side ──────────────────────────────────────────────────────────
//
// Decline is NOT client-only, and this was verified against the backend rather
// than assumed from the UI: `decline_agreement` and `submit_signature` apply the
// IDENTICAL check —
//
//     party_ids = {p["user_id"] for p in agreement["parties"]}
//     if user_id not in party_ids: raise ForbiddenError(...)
//
// — with no role condition anywhere. Lawyers are parties (they counter-sign via
// `needsMySig`), so a lawyer sent an agreement they disagree with could only
// sign it or leave it pending forever. That is the exact situation the
// backend's own docstring says the endpoint exists to end.

const LAWYER = read("../src/components/lawyer/AgreementsPage.jsx");

test("the lawyer agreements screen can decline too", () => {
    assert.match(LAWYER, /import \{[^}]*declineAgreement[^}]*\} from "@\/lib\/api\.js"/,
        "the lawyer screen cannot decline — it only signs");
    assert.match(LAWYER, /await declineAgreement\(/,
        "declineAgreement imported but never called on the lawyer screen");
});

test("the lawyer decline is guarded the same way as the client one", () => {
    assert.match(LAWYER, /declineOpen/, "no reveal/confirm state");
    assert.match(LAWYER, /Confirm decline/, "no explicit confirm control");
    assert.match(LAWYER, /cannot be undone/i, "the user is not warned it is final");
    assert.match(LAWYER, /maxLength=\{2000\}/, "reason not bounded to the server limit");
});

test("closing the lawyer modal clears a half-typed decline", () => {
    // Both dismiss paths (backdrop and ✕) must reset, or opening a DIFFERENT
    // agreement shows a decline form already filled in for the previous one —
    // and the confirm button then applies it to the wrong contract.
    assert.match(LAWYER, /const closeModal = \(\) => \{[^}]*setDeclineOpen\(false\)[^}]*\}/,
        "no reset helper");
    const dismissals = LAWYER.match(/onClick=\{closeModal\}/g) || [];
    assert.ok(dismissals.length >= 2,
        `expected backdrop and close button to reset; found ${dismissals.length}`);
    assert.doesNotMatch(LAWYER, /onClick=\{\(\) => setActive\(null\)\}/,
        "a dismiss path still clears only `active`, leaving decline state behind");
});

test("both agreement screens offer decline wherever they offer signing", () => {
    // The asymmetry this whole change removes: a party who can commit must be
    // able to refuse. If a future screen adds signing, this is the reminder.
    for (const [name, source] of [["client", AGREEMENTS], ["lawyer", LAWYER]]) {
        assert.match(source, /signAgreement/, `${name} screen does not sign`);
        assert.match(source, /declineAgreement/,
            `${name} screen can sign but not decline — the one-sided flow is back`);
    }
});

// ── the backend assumption this UI rests on ──────────────────────────────────

test("the backend still authorises decline by party, not by role", () => {
    // The lawyer UI is only correct while this holds. If someone later
    // restricts decline to clients, this fails and says why, instead of the
    // lawyer screen quietly returning 403 at the moment of use.
    const service = read("../../backend/app/services/agreement_service.py");
    const decline = service.slice(service.indexOf("async def decline_agreement"));
    const body = decline.slice(0, decline.indexOf("\nasync def ", 10) + 1 || undefined);
    assert.match(body, /party_ids\s*=\s*\{p\["user_id"\] for p in agreement\.get\("parties", \[\]\)\}/,
        "decline no longer derives its allowlist from the parties");
    assert.match(body, /if user_id not in party_ids:\s*\n\s*raise ForbiddenError/,
        "decline no longer refuses non-parties the same way");
    assert.doesNotMatch(body, /role\s*==|current_user\[["']role["']\]|require_lawyer|require_client/,
        "decline has grown a ROLE condition — the lawyer decline UI may now 403");
});
