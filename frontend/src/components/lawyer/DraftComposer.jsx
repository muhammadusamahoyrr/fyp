'use client';
// Writing an agreement — the lawyer's side of the Gate 3C draft routes.
//
// A draft is PRIVATE. It reaches nobody, notifies nobody and binds nobody until
// it is sent, and the server enforces that: another party cannot list it, read
// it, sign it or decline it, and gets a 404 rather than a 403 so the id is not
// even confirmed to exist.
//
// Three rules shape this screen, and each is here because the obvious
// alternative is wrong:
//
//   1. THE VERSION COMES FROM THE SERVER, never from a local counter. Every
//      response carries it; we echo back what we were last told. Counting our
//      own saves works only while this tab is the only writer.
//
//   2. THE DIGEST IS TAKEN OVER THE SAVED BODY, never over the textarea. The
//      server hashes the text AS STORED. Hashing unsaved editor state would
//      attest to wording the server does not hold — the exact failure the hash
//      exists to prevent — and would break on Windows anyway, where a textarea
//      holds \r\n and the stored copy holds \n.
//
//   3. SENDING IS BLOCKED WHILE THERE ARE UNSAVED EDITS. Auto-saving and
//      immediately sending would let someone sign text they had not read in its
//      final form. Save, re-read what came back, then sign.
import { useState, useEffect, useCallback } from "react";
import { useTheme } from "./theme.js";
import { Btn, Badge } from "./components.jsx";
import {
    listCases, createDraft, updateDraft, deleteDraft, sendDraft,
    idempotencyKey, errorCode,
} from "@/lib/api.js";
import { bodyDigestHex } from "@/lib/agreementBody.js";

const input = (T) => ({
    width: "100%", border: `1px solid ${T.border}`, borderRadius: 9,
    background: T.inputBg, color: T.text, fontSize: 13, padding: "9px 12px",
    outline: "none", fontFamily: "inherit", boxSizing: "border-box",
});

/* Pick the case first. The case IS the authorisation (product decision D2):
   the server refuses a draft between a lawyer and a client who share no case,
   so there is no free-form recipient field to offer. The client is read off the
   case rather than chosen, which also means it cannot be mistyped. */
function CasePicker({ T, cases, loading, onPick, onCancel }) {
    if (loading) {
        return <div style={{ padding: 30, textAlign: "center", color: T.textMuted, fontSize: 13 }}>Loading your cases…</div>;
    }
    if (!cases.length) {
        return (
            <div style={{ padding: 30, textAlign: "center" }}>
                <div style={{ fontSize: 30, marginBottom: 10 }}>📁</div>
                <div style={{ fontSize: 13.5, color: T.text, fontWeight: 600, marginBottom: 6 }}>No cases yet</div>
                <div style={{ fontSize: 12.5, color: T.textMuted, lineHeight: 1.6, maxWidth: 380, margin: "0 auto" }}>
                    An agreement is written against a case you are acting on. Accept a
                    client request first — the case is what authorises the agreement.
                </div>
                <div style={{ marginTop: 16 }}><Btn variant="secondary" onClick={onCancel}>Close</Btn></div>
            </div>
        );
    }
    return (
        <div style={{ padding: "14px 20px" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: T.textMuted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>
                Which case is this agreement for?
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {cases.map(c => (
                    <button key={c._id || c.id} type="button" onClick={() => onPick(c)}
                        style={{
                            textAlign: "left", background: T.cardHi, border: `1px solid ${T.border}`,
                            borderRadius: 10, padding: "11px 14px", cursor: "pointer", fontFamily: "inherit",
                        }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: T.text }}>{c.title || "Untitled case"}</div>
                        <div style={{ fontSize: 11.5, color: T.textMuted, marginTop: 3 }}>
                            {c.client_name || "Client"} · {c.case_type || "—"} · {c.case_number || (c._id || c.id)}
                        </div>
                    </button>
                ))}
            </div>
        </div>
    );
}

export function DraftComposer({ draft, onClose, onSaved }) {
    const { t: T } = useTheme();

    // `server` is the last state the SERVER confirmed: body, title and version.
    // Everything sent back to it is derived from here, never from the editor.
    const [server, setServer] = useState(draft || null);
    const [title, setTitle] = useState(draft?.title || "");
    const [body, setBody] = useState(draft?.body_html || "");

    const [cases, setCases] = useState([]);
    const [casesLoading, setCasesLoading] = useState(!draft);
    const [picked, setPicked] = useState(null);

    const [busy, setBusy] = useState(false);
    const [note, setNote] = useState(null);       // { kind: "error" | "ok", text }
    const [signing, setSigning] = useState(false);
    const [signName, setSignName] = useState("");
    const [consent, setConsent] = useState(false);
    const [confirmDelete, setConfirmDelete] = useState(false);

    // Minted once per SEND INTENT and reused by every retry of that send. A
    // fresh key on a retry is a second agreement, which is the failure the key
    // exists to prevent — so it is state, not a value computed at call time.
    const [sendKey, setSendKey] = useState(null);

    useEffect(() => {
        if (draft) return;
        listCases({ page: 1, page_size: 50 })
            .then(({ data }) => setCases(data?.items || []))
            .catch(() => setCases([]))
            .finally(() => setCasesLoading(false));
    }, [draft]);

    const dirty = !!server && (body !== server.body_html || title !== server.title);
    const canSend = !!server && !dirty && !!body.trim();

    const fail = (error, fallback) => {
        setNote({ kind: "error", text: error?.message || fallback });
    };

    /* Take the server's copy as the new truth.
     *
     * Guards against an empty body on a 2xx. That should not happen, but the
     * editor holding a draft is the wrong place to find out: without the check
     * a blank response threw inside the click handler and took the whole
     * screen down, losing text the lawyer had just typed. Refusing to adopt
     * nothing keeps their work on screen and says so. */
    const adoptServerCopy = (doc) => {
        if (!doc || typeof doc !== "object") {
            setNote({
                kind: "error",
                text: "The server did not return the saved agreement. Your text " +
                    "is still here — try saving again.",
            });
            return false;
        }
        setServer(doc);
        setTitle(doc.title || "");
        setBody(doc.body_html || "");
        return true;
    };

    const doCreate = useCallback(async () => {
        if (!picked || !title.trim() || !body.trim()) return;
        setBusy(true); setNote(null);
        const { data, error } = await createDraft({
            title: title.trim(),
            body_html: body,
            client_id: picked.client_id,
            case_id: picked._id || picked.id,
        });
        setBusy(false);
        if (error) return fail(error, "Could not create the draft.");
        if (!adoptServerCopy(data)) return;
        setNote({ kind: "ok", text: "Draft saved. It is private to you until you send it." });
        onSaved?.();
    }, [picked, title, body, onSaved]);

    const doSave = useCallback(async () => {
        if (!server) return doCreate();
        setBusy(true); setNote(null);
        const { data, error } = await updateDraft(server.id || server._id, {
            expected_version: server.version,
            title: title.trim(),
            body_html: body,
        });
        setBusy(false);
        if (error) {
            // A conflict means another save landed first. Saying so and leaving
            // the lawyer's text in the box is the only safe response:
            // overwriting silently is what `expected_version` exists to stop.
            return fail(error, "Could not save. Nothing has been changed.");
        }
        if (!adoptServerCopy(data)) return;
        setNote({ kind: "ok", text: `Saved — version ${data.version}.` });
        onSaved?.();
    }, [server, title, body, doCreate, onSaved]);

    const doDelete = useCallback(async () => {
        if (!server) return onClose();
        setBusy(true); setNote(null);
        const { error } = await deleteDraft(server.id || server._id);
        setBusy(false);
        if (error) return fail(error, "Could not delete the draft.");
        onSaved?.();
        onClose();
    }, [server, onClose, onSaved]);

    const doSend = useCallback(async () => {
        if (!server || dirty) return;
        if (!consent) {
            return setNote({ kind: "error", text: "Confirm you intend to sign and send this agreement." });
        }
        if (!signName.trim()) {
            return setNote({ kind: "error", text: "Type your full legal name to sign." });
        }

        setBusy(true); setNote(null);
        const key = sendKey || idempotencyKey();
        setSendKey(key);

        let digest;
        try {
            // Over the SAVED body — the text displayed above and the text the
            // server holds. Never over the textarea.
            digest = await bodyDigestHex(server.body_html || "");
        } catch (e) {
            setBusy(false);
            return setNote({ kind: "error", text: e.message });
        }

        const { data, error } = await sendDraft(server.id || server._id, {
            expected_version: server.version,
            expected_body_sha256: digest,
            method: "typed",
            signature_data: signName.trim(),
            consent: true,
        }, key);
        setBusy(false);

        if (error) {
            if (errorCode(error) === "conflict" || /changed since/i.test(error.message || "")) {
                // The key is deliberately KEPT. This send never reached the
                // point of creating anything, so resolving the conflict and
                // sending again is still that one intent.
                return setNote({
                    kind: "error",
                    text: (error.message || "This draft changed since you reviewed it.") +
                        " Close and reopen it to read the current wording.",
                });
            }
            return fail(error, "Could not send the agreement.");
        }

        onSaved?.();
        onClose(data?.status === "pending"
            ? "✅ Signed and sent — the client has been notified"
            : "✅ Sent");
    }, [server, dirty, consent, signName, sendKey, onSaved, onClose]);

    const composing = !server && !picked;
    const counterparty = server?.parties?.find(p => p.user_id !== server.created_by);

    return (
        <div onClick={() => onClose()} style={{
            position: "fixed", inset: 0, zIndex: 9999, background: "rgba(0,0,0,0.6)",
            display: "flex", alignItems: "center", justifyContent: "center", padding: 20,
        }}>
            <div onClick={e => e.stopPropagation()} style={{
                background: T.card, border: `1px solid ${T.border}`, borderRadius: 16,
                width: "100%", maxWidth: 720, maxHeight: "90vh", display: "flex",
                flexDirection: "column", overflow: "hidden", boxShadow: T.shadowCard,
            }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 20px", borderBottom: `1px solid ${T.border}` }}>
                    <span style={{ fontSize: 20 }}>📝</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 15, fontWeight: 700, color: T.text, fontFamily: "Georgia,serif" }}>
                            {server ? "Edit draft" : "New agreement"}
                        </div>
                        <div style={{ fontSize: 11, color: T.textMuted }}>
                            {server
                                ? `${counterparty?.full_name || "Client"} · version ${server.version}`
                                : "Private to you until you send it"}
                        </div>
                    </div>
                    {server && <Badge type="gray">Draft</Badge>}
                    <button onClick={() => onClose()} style={{ background: "none", border: `1px solid ${T.border}`, borderRadius: 8, width: 28, height: 28, cursor: "pointer", color: T.textMuted, fontSize: 14 }}>✕</button>
                </div>

                {composing ? (
                    <CasePicker T={T} cases={cases} loading={casesLoading}
                        onPick={setPicked} onCancel={() => onClose()} />
                ) : (
                    <>
                        <div style={{ flex: 1, overflowY: "auto", padding: "14px 20px" }}>
                            {picked && !server && (
                                <div style={{ fontSize: 12, color: T.textMuted, background: T.cardHi, border: `1px solid ${T.border}`, borderRadius: 9, padding: "9px 12px", marginBottom: 12 }}>
                                    For <b style={{ color: T.text }}>{picked.client_name || "the client"}</b> on {picked.title || "this case"}
                                </div>
                            )}

                            <div style={{ fontSize: 10.5, fontWeight: 700, color: T.textMuted, textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 6 }}>Title</div>
                            <input value={title} maxLength={200} onChange={e => setTitle(e.target.value)}
                                placeholder="Retainer agreement" style={input(T)} />

                            <div style={{ fontSize: 10.5, fontWeight: 700, color: T.textMuted, textTransform: "uppercase", letterSpacing: "0.07em", margin: "14px 0 6px" }}>
                                Terms
                            </div>
                            <textarea value={body} onChange={e => setBody(e.target.value)} rows={14}
                                placeholder="Write the terms of this agreement…"
                                style={{ ...input(T), resize: "vertical", lineHeight: 1.7, fontFamily: "Georgia, serif" }} />
                            <div style={{ fontSize: 10.5, color: T.textFaint, marginTop: 6, lineHeight: 1.5 }}>
                                Write the terms yourself. This system does not supply contract
                                templates — wording that has not been reviewed by a Pakistani
                                lawyer is refused.
                            </div>

                            {note && (
                                <div style={{
                                    marginTop: 12, fontSize: 12.5, lineHeight: 1.6, borderRadius: 9, padding: "9px 12px",
                                    color: note.kind === "error" ? T.danger : T.success,
                                    background: note.kind === "error" ? `${T.danger}12` : `${T.success}12`,
                                    border: `1px solid ${note.kind === "error" ? T.danger : T.success}35`,
                                }}>{note.text}</div>
                            )}

                            {signing && server && (
                                <div style={{ marginTop: 14, paddingTop: 14, borderTop: `1px solid ${T.border}` }}>
                                    <div style={{ fontSize: 10.5, fontWeight: 700, color: T.textMuted, textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 8 }}>
                                        Sign and send — this reaches your client immediately
                                    </div>
                                    <label style={{ display: "flex", gap: 9, alignItems: "flex-start", fontSize: 12.5, color: T.text, cursor: "pointer", marginBottom: 10, lineHeight: 1.6 }}>
                                        <input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} style={{ marginTop: 2 }} />
                                        <span>
                                            I have read the terms above and intend to sign and send
                                            them. Signing and sending happen together, and this cannot
                                            be recalled once sent.
                                        </span>
                                    </label>
                                    <input value={signName} onChange={e => setSignName(e.target.value)}
                                        placeholder="Type your full legal name" style={input(T)} />
                                    <div style={{ fontSize: 10.5, color: T.textFaint, marginTop: 7, lineHeight: 1.5 }}>
                                        Recorded with a timestamp, your IP and a digest of the exact
                                        wording above, under the Electronic Transactions Ordinance 2002.
                                    </div>
                                </div>
                            )}
                        </div>

                        <div style={{ padding: "12px 20px 16px", borderTop: `1px solid ${T.border}`, background: T.surface, display: "flex", gap: 9, alignItems: "center", flexWrap: "wrap" }}>
                            <Btn variant="secondary" disabled={busy || (!!server && !dirty) || !title.trim() || !body.trim()}
                                onClick={doSave}>
                                {busy ? "Saving…" : server ? (dirty ? "Save changes" : "Saved") : "Save draft"}
                            </Btn>

                            {server && !signing && (
                                <Btn variant="accent" disabled={busy || !canSend}
                                    title={dirty ? "Save your changes first, then read them before signing" : undefined}
                                    onClick={() => { setSigning(true); setNote(null); }}>
                                    ✍️ Sign &amp; send…
                                </Btn>
                            )}
                            {server && signing && (
                                <>
                                    <Btn variant="accent" disabled={busy || !canSend} onClick={doSend}>
                                        {busy ? "Sending…" : "Confirm — sign & send"}
                                    </Btn>
                                    <Btn variant="ghost" disabled={busy} onClick={() => { setSigning(false); setConsent(false); }}>
                                        Keep editing
                                    </Btn>
                                </>
                            )}

                            <div style={{ flex: 1 }} />

                            {server && (confirmDelete ? (
                                <>
                                    <span style={{ fontSize: 12, color: T.danger }}>Delete this draft?</span>
                                    <Btn variant="danger" size="sm" disabled={busy} onClick={doDelete}>Yes, delete</Btn>
                                    <Btn variant="ghost" size="sm" disabled={busy} onClick={() => setConfirmDelete(false)}>No</Btn>
                                </>
                            ) : (
                                <Btn variant="ghost" size="sm" disabled={busy} onClick={() => setConfirmDelete(true)}>Delete draft</Btn>
                            ))}
                        </div>

                        {dirty && server && (
                            <div style={{ padding: "0 20px 12px", fontSize: 11.5, color: T.warn, background: T.surface }}>
                                Unsaved changes. Save them, then read the saved wording before
                                signing — what you sign is what the server holds, not what is in
                                the box.
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}
