/* Who owns the live socket.
 *
 * WHY THIS EXISTS
 * ---------------
 * The guard in front of a connect used to be a readyState check:
 *
 *     if (ws?.readyState === OPEN || ws?.readyState === CONNECTING) return;
 *     const ticket = await getWsTicket();          // <-- the hole
 *     ws = new WebSocket(url);
 *
 * Nothing is CONNECTING during that await, because no socket exists yet. A
 * reconnect timer firing while a conversation switch is fetching its ticket
 * passes the same guard, and two sockets open for one conversation. Both
 * receive every frame, both call setMsgs, and whichever closes last schedules
 * another retry — so the duplicates compound rather than settle.
 *
 * The fix is to claim the RIGHT to open a socket synchronously, before the
 * first await, and to hold that claim across it. A claim is also a generation:
 * a slower connect whose claim has since been superseded closes the socket it
 * opened instead of installing it, which is what makes "no overlapping
 * sockets" a property rather than a hope.
 */

/* Every state a claim can be in is deliberate. `opening` is not derivable from
 * the socket, because during the ticket fetch there is no socket to ask. */
export function createSocketOwner(WebSocketImpl) {
    const WS = WebSocketImpl
        || (typeof WebSocket !== "undefined" ? WebSocket : null);
    const OPEN = WS ? WS.OPEN : 1;
    const CONNECTING = WS ? WS.CONNECTING : 0;

    let generation = 0;
    let socket = null;
    let opening = false;

    return {
        /* Claim the right to open a socket, or null if one is already open or
         * being opened. Synchronous by contract — a caller that awaits before
         * claiming has already lost the race it is trying to win. */
        claim() {
            if (opening) return null;
            const state = socket ? socket.readyState : null;
            if (state === OPEN || state === CONNECTING) return null;
            opening = true;
            generation += 1;
            return generation;
        },

        /* The claim produced no socket — no ticket, no token, an error on the
         * way. Must be called, or nothing can ever connect again. */
        abandon(token) {
            if (token === generation) opening = false;
        },

        /* Install the socket this claim opened. A claim that has been
         * superseded closes its socket instead and reports false, so the caller
         * knows not to wire handlers to it. */
        adopt(token, ws) {
            if (token !== generation) {
                try { ws.close(); } catch { /* already dead */ }
                return false;
            }
            opening = false;
            socket = ws;
            return true;
        },

        /* Is this the socket in charge? Handlers ask before acting: a close on
         * a socket we have already replaced must not schedule a reconnect. */
        isCurrent(ws) {
            return !!ws && ws === socket;
        },

        current() {
            return socket;
        },

        isOpen() {
            return !!socket && socket.readyState === OPEN;
        },

        /* True while a socket exists or is being fetched — the honest answer to
         * "is a connection in hand?", which readyState alone cannot give during
         * the ticket fetch. */
        isBusy() {
            return opening || this.isOpen()
                || (!!socket && socket.readyState === CONNECTING);
        },

        /* Close and disown. Bumping the generation is the point: an in-flight
         * claim becomes stale, so the socket it is about to open gets closed on
         * adopt rather than quietly replacing this one. */
        close() {
            generation += 1;
            opening = false;
            const ws = socket;
            socket = null;
            if (ws) {
                try { ws.close(); } catch { /* already dead */ }
            }
            return ws;
        },
    };
}
