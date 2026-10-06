import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import { websocketUrl } from "../src/lib/api.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("websocket URLs follow the page origin and upgrade HTTPS to WSS", () => {
    const previous = globalThis.window;
    const configured = process.env.NEXT_PUBLIC_WS_URL;
    delete process.env.NEXT_PUBLIC_WS_URL;
    globalThis.window = { location: { protocol: "https:", host: "demo.example" } };
    try {
        assert.equal(websocketUrl("/ws/notifications"),
                     "wss://demo.example/ws/notifications");
        assert.equal(websocketUrl("ws/chat/thread-1"),
                     "wss://demo.example/ws/chat/thread-1");
    } finally {
        if (previous === undefined) delete globalThis.window;
        else globalThis.window = previous;
        if (configured === undefined) delete process.env.NEXT_PUBLIC_WS_URL;
        else process.env.NEXT_PUBLIC_WS_URL = configured;
    }
});

test("an explicit WebSocket origin remains supported", () => {
    const previous = process.env.NEXT_PUBLIC_WS_URL;
    process.env.NEXT_PUBLIC_WS_URL = "wss://socket.example/";
    try {
        assert.equal(websocketUrl("/ws/chat/a"), "wss://socket.example/ws/chat/a");
    } finally {
        if (previous === undefined) delete process.env.NEXT_PUBLIC_WS_URL;
        else process.env.NEXT_PUBLIC_WS_URL = previous;
    }
});

test("Next proxies both HTTP API and WebSocket paths", async () => {
    const require = createRequire(import.meta.url);
    const config = require("../next.config.js");
    const rewrites = await config.rewrites();
    assert.ok(rewrites.some(rule => rule.source === "/api/v1/:path*"));
    assert.ok(rewrites.some(rule => rule.source === "/ws/:path*"));
});

test("manual browser-facing smokes default to the Next proxy", () => {
    const env = read("../../backend/scripts/manual_smoke/_smoke_env.py");
    assert.match(env, /SMOKE_ORIGIN.*http:\/\/127\.0\.0\.1:3000/);
    for (const file of ["smoke_intake_e2e.py", "smoke_lawyer_matching.py",
                        "smoke_chat_ws.py", "smoke_full_e2e.py"]) {
        const source = read(`../../backend/scripts/manual_smoke/${file}`);
        assert.match(source, /smoke_origins/);
        assert.doesNotMatch(source, /(?:ws|http):\/\/(?:127\.0\.0\.1|localhost):8000/);
    }
});

test("both live socket consumers use the shared origin-safe URL helper", () => {
    const api = read("../src/lib/api.js");
    const chatbot = read("../src/components/client/ModChatbot.jsx");
    assert.match(api, /websocketUrl\('\/ws\/notifications'\)/);
    assert.match(chatbot, /websocketUrl\(`\/ws\/chat\//);
    assert.doesNotMatch(chatbot, /ws:\/\/localhost:8000/);
});

test("document and research failures are visible and preserve existing state", () => {
    const documents = read("../src/components/client/MyDocumentsPanel.jsx");
    const research = read("../src/components/lawyer/AILegalPage.jsx");
    assert.match(documents, /role="alert"/);
    assert.match(documents, /Could not open that document/);
    assert.match(research, /Could not open that conversation/);
    assert.match(research, /Could not start a new conversation/);

    const failedOpen = research.slice(
        research.indexOf("if (!thread)"),
        research.indexOf("const { header", research.indexOf("if (!thread)")),
    );
    assert.doesNotMatch(failedOpen, /setMsgs\(\[\]\)/);
    assert.doesNotMatch(failedOpen, /writeActiveSession/);
});

test("older-message and pending-outcome paging failures are not silent", () => {
    const client = read("../src/components/client/ModChatbot.jsx");
    const research = read("../src/components/lawyer/AILegalPage.jsx");
    const appointments = read("../src/components/lawyer/AppointmentsPage.jsx");
    assert.match(client, /Could not load earlier messages/);
    assert.match(research, /Could not load earlier messages/);
    assert.match(appointments, /Could not load more outcomes/);
});
