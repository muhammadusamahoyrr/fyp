/* Intake storage — the keys that stranded the next user.
 *
 * `aai-intake-token` and `aai-case-id` were fixed strings shared by every
 * account that ever signed in on the browser, and sign-out cleared neither.
 * That was not a stale value, it was a dead end: ModIntake calls intakeStart()
 * ONLY when it finds no saved token, so the next person inherited the previous
 * one, skipped session creation, and had every intake call refused by the
 * server's client_id check with nothing in the UI to explain it.
 *
 * These tests hold the property that fixes it — one user cannot read another's
 * value — rather than the key format, so the scheme can change freely.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>",
                      { url: "http://localhost/" });
Object.defineProperty(globalThis, "localStorage", {
    value: dom.window.localStorage, writable: true, configurable: true,
});

const {
    readIntakeValue, writeIntakeValue, clearIntakeValue, clearAllIntakeValues,
} = await import("../src/lib/intakeStorage.js");

const ALICE = "user-alice";
const BOB = "user-bob";

function reset() {
    dom.window.localStorage.clear();
}

test("a value written for one user is readable by that user", () => {
    reset();
    writeIntakeValue("aai-intake-token", ALICE, "tok-alice");
    assert.equal(readIntakeValue("aai-intake-token", ALICE), "tok-alice");
});

test("another user cannot read it", () => {
    reset();
    writeIntakeValue("aai-intake-token", ALICE, "tok-alice");
    assert.equal(readIntakeValue("aai-intake-token", BOB), null);
});

test("the next user gets null, which is what makes ModIntake start a session", () => {
    // The exact sequence that wedged the second account: Alice signs in and
    // starts an intake, Bob signs in on the same browser. Bob must see no
    // token, because a token is what suppresses intakeStart().
    reset();
    writeIntakeValue("aai-intake-token", ALICE, "tok-alice");
    const bobSees = readIntakeValue("aai-intake-token", BOB);
    assert.equal(bobSees, null);
});

test("two users keep separate case ids", () => {
    reset();
    writeIntakeValue("aai-case-id", ALICE, "case-a");
    writeIntakeValue("aai-case-id", BOB, "case-b");
    assert.equal(readIntakeValue("aai-case-id", ALICE), "case-a");
    assert.equal(readIntakeValue("aai-case-id", BOB), "case-b");
});

test("clearing one value leaves the other user's alone", () => {
    reset();
    writeIntakeValue("aai-intake-token", ALICE, "tok-alice");
    writeIntakeValue("aai-intake-token", BOB, "tok-bob");
    clearIntakeValue("aai-intake-token", ALICE);
    assert.equal(readIntakeValue("aai-intake-token", ALICE), null);
    assert.equal(readIntakeValue("aai-intake-token", BOB), "tok-bob");
});

test("no user id means nothing is read or written", () => {
    // ModIntake renders before auth resolves. Writing under a null id would
    // create a key no signed-in user could ever read back.
    reset();
    writeIntakeValue("aai-intake-token", null, "tok-orphan");
    assert.equal(dom.window.localStorage.length, 0);
    assert.equal(readIntakeValue("aai-intake-token", null), null);
});

test("sign-out clears every user's intake values", () => {
    reset();
    writeIntakeValue("aai-intake-token", ALICE, "tok-alice");
    writeIntakeValue("aai-case-id", BOB, "case-b");
    clearAllIntakeValues();
    assert.equal(readIntakeValue("aai-intake-token", ALICE), null);
    assert.equal(readIntakeValue("aai-case-id", BOB), null);
});

test("sign-out also clears the pre-scoping keys", () => {
    /* The upgrade path. A browser already holding the old unscoped token would
     * otherwise carry it forever — and anyone already stuck behind a foreign
     * token would stay stuck, because nothing else ever removes those keys. */
    reset();
    dom.window.localStorage.setItem("aai-intake-token", "legacy-token");
    dom.window.localStorage.setItem("aai-case-id", "legacy-case");
    clearAllIntakeValues();
    assert.equal(dom.window.localStorage.getItem("aai-intake-token"), null);
    assert.equal(dom.window.localStorage.getItem("aai-case-id"), null);
});

test("an empty value removes the key rather than storing an empty string", () => {
    reset();
    writeIntakeValue("aai-case-id", ALICE, "case-a");
    writeIntakeValue("aai-case-id", ALICE, null);
    assert.equal(readIntakeValue("aai-case-id", ALICE), null);
});

test("a blocked storage never throws out of the module", () => {
    /* Some privacy modes make the accessor itself throw. An intake that cannot
     * be resumed is a far smaller problem than an intake page that will not
     * render, so every access is wrapped. */
    const real = globalThis.localStorage;
    Object.defineProperty(globalThis, "localStorage", {
        get() { throw new Error("blocked"); }, configurable: true,
    });
    try {
        assert.equal(readIntakeValue("aai-intake-token", ALICE), null);
        assert.doesNotThrow(() => writeIntakeValue("aai-intake-token", ALICE, "x"));
        assert.doesNotThrow(() => clearAllIntakeValues());
    } finally {
        Object.defineProperty(globalThis, "localStorage", {
            value: real, writable: true, configurable: true,
        });
    }
});
