import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";


test("the loser of a cross-tab refresh race adopts the winner's token", async () => {
    const channels = [];
    globalThis.BroadcastChannel = class {
        constructor(name) {
            assert.equal(name, "aai-auth");
            this.onmessage = null;
            channels.push(this);
        }

        postMessage(message) {
            if (message.type === "token-request") {
                queueMicrotask(() => this.onmessage?.({
                    data: { type: "token", token: "new-from-sibling" },
                }));
            }
        }
    };

    const calls = [];
    globalThis.fetch = async (url, options = {}) => {
        calls.push({ url, options });
        if (url.endsWith("/users/me") && calls.filter(c => c.url.endsWith("/users/me")).length === 1) {
            return new Response("{}", { status: 401 });
        }
        if (url.endsWith("/auth/refresh")) {
            return new Response("{}", { status: 401 });
        }
        return new Response(JSON.stringify({ _id: "u1", role: "client" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        });
    };

    const api = await import(`../src/lib/api.js?auth-race=${Date.now()}`);
    api.setToken("old-access");
    const result = await api.getMe();

    assert.equal(result.status, 200);
    assert.equal(api.getToken(), "new-from-sibling");
    const refresh = calls.find(call => call.url.endsWith("/auth/refresh"));
    assert.equal(refresh.options.headers.Authorization, "Bearer old-access",
        "the server cannot revoke the replaced access token if it is omitted");
    const userCalls = calls.filter(call => call.url.endsWith("/users/me"));
    assert.equal(userCalls.length, 2);
    assert.equal(userCalls[1].options.headers.Authorization, "Bearer new-from-sibling");
    assert.equal(channels.length, 1);
});


test("a backend restart during refresh does not clear the access token", async () => {
    globalThis.BroadcastChannel = undefined;
    globalThis.fetch = async (url) => {
        if (url.endsWith("/users/me")) return new Response("{}", { status: 401 });
        if (url.endsWith("/auth/refresh")) throw new TypeError("ECONNRESET");
        throw new Error(`unexpected request: ${url}`);
    };

    const api = await import(`../src/lib/api.js?auth-outage=${Date.now()}`);
    api.setToken("keep-during-restart");
    const result = await api.getMe();

    assert.equal(result.status, 0);
    assert.match(result.error.message, /server is restarting or unavailable/i);
    assert.equal(api.getToken(), "keep-during-restart");
});


test("a cold load distinguishes an unavailable backend from a signed-out session", async () => {
    globalThis.BroadcastChannel = undefined;
    globalThis.fetch = async () => { throw new TypeError("ECONNRESET"); };

    const api = await import(`../src/lib/api.js?auth-bootstrap-outage=${Date.now()}`);
    const result = await api.bootstrapAuth();

    assert.equal(result, api.AUTH_BOOTSTRAP_UNAVAILABLE);
    assert.equal(api.getToken(), null);
});


test("an explicit rejected refresh still clears an expired access token", async () => {
    globalThis.BroadcastChannel = undefined;
    globalThis.fetch = async (url) => {
        if (url.endsWith("/users/me")) return new Response("{}", { status: 401 });
        if (url.endsWith("/auth/refresh")) return new Response("{}", { status: 401 });
        throw new Error(`unexpected request: ${url}`);
    };

    const api = await import(`../src/lib/api.js?auth-invalid=${Date.now()}`);
    api.setToken("expired-access");
    const result = await api.getMe();

    assert.equal(result.status, 401);
    assert.equal(api.getToken(), null);
});


test("protected pages show retry UI instead of redirecting during an outage", () => {
    const code = readFileSync(
        new URL("../src/components/shared/ProtectedRoute.jsx", import.meta.url), "utf8");
    assert.match(code, /if \(authUnavailable\) return;/,
        "the redirect effect must stop while the backend is unavailable");
    assert.match(code, /<AuthUnavailable onRetry=\{retryAuth\}/,
        "the user needs an explicit connection retry action");
});


test("both account screens use the shared logout path", () => {
    const files = [
        "../src/components/client/ModProfile.jsx",
        "../src/components/lawyer/SettingsPage.jsx",
    ];
    for (const file of files) {
        const code = readFileSync(new URL(file, import.meta.url), "utf8");
        assert.match(code, /useAuth\(\)/,
            `${file} bypasses the shared authentication state`);
        assert.doesNotMatch(code, /\bauthLogout\b/,
            `${file} logs out only its own tab`);
        assert.match(code, /Password (?:changed|updated)\. Please sign in again\./,
            `${file} leaves a password-changed session looking usable`);
    }
});


test("registration does not collect an identifier it discards", () => {
    const code = readFileSync(
        new URL("../src/app/(auth)/register/page.jsx", import.meta.url), "utf8");
    assert.doesNotMatch(code, /CNIC \/ Bar Council ID/,
        "the form implies a sensitive identifier was registered but never sends it");
    assert.doesNotMatch(code, /\[cnic, setCnic\]/,
        "discarded identity data is still held in page state");
});
