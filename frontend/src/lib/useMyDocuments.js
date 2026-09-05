/* The client's own document history — paging, and the three states that are
 * not "here is a list".
 *
 * `/documents/v2/mine` existed and only the lawyer UI called it, so a client
 * could reach a document they had made only by still having it on screen. Close
 * the tab and the work was there on the server and unreachable through the
 * product.
 *
 * EMPTY, LOADING AND ERROR ARE NOT THE SAME THING, and a list that renders all
 * three as "no documents" is worse than one that crashes: the client concludes
 * their documents are gone. So this distinguishes:
 *
 *   loading  — we have not been told yet
 *   error    — we asked and could not find out (with the reason)
 *   empty    — we asked, and there genuinely are none
 *
 * OWNERSHIP IS NOT DECIDED HERE. The endpoint scopes every query to the caller;
 * this module never sends an owner id and never filters by one. A client-side
 * ownership check would be a second, weaker answer to a question the backend
 * has already answered properly — and the first thing to diverge.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export function useMyDocuments({ fetchPage, pageSize = 20, enabled = true }) {
    const [items, setItems] = useState([]);
    const [cursor, setCursor] = useState(null);
    const [hasMore, setHasMore] = useState(false);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    // `loaded` is what separates "no documents" from "not asked yet". Without
    // it the first render shows an empty-state to a client whose documents are
    // still in flight.
    const [loaded, setLoaded] = useState(false);

    // Bumped on every load and on unmount, so a slow first page cannot land
    // after a refresh has already replaced the list.
    const token = useRef(0);
    const mounted = useRef(true);
    useEffect(() => () => { mounted.current = false; token.current++; }, []);

    // THE FETCHER LIVES IN A REF, and that is not a style choice.
    //
    // `load` used to be a useCallback over `fetchPage`, with the mount effect
    // depending on `load`. A caller writing the obvious thing —
    //
    //     useMyDocuments({ fetchPage: () => myDocumentsV2({ cursor, limit }) })
    //
    // hands in a new function identity on every render, so the effect re-ran,
    // which set state, which re-rendered, forever: a tight loop against the API
    // that never painted a list. The panel in this repo happened to wrap its
    // fetcher in `useCallback([])`, so the tests passed by coincidence and the
    // hook was one ordinary call site away from hammering the backend.
    //
    // A hook must not require its caller to memoise a callback in order to be
    // safe. The ref always holds the latest fetcher; `load` never changes.
    const fetchRef = useRef(fetchPage);
    fetchRef.current = fetchPage;
    const sizeRef = useRef(pageSize);
    sizeRef.current = pageSize;

    const load = useCallback(async ({ append = false, cursor: from = null } = {}) => {
        const mine = ++token.current;
        setLoading(true);
        setError(null);
        const { data, error: err } = await fetchRef.current({
            cursor: from, limit: sizeRef.current,
        });
        if (!mounted.current || token.current !== mine) return;

        setLoading(false);
        setLoaded(true);
        if (err) {
            // The existing list is KEPT. Replacing it with an error state would
            // throw away documents already on screen because one more page
            // failed to arrive.
            setError(err);
            return;
        }
        const page = (data && data.items) || [];
        setItems(prev => (append ? [...prev, ...page] : page));
        setHasMore(Boolean(data && data.has_more));
        setCursor((data && data.next_cursor) || null);
        // `load` is stable by construction: everything variable is behind a ref.
    }, []);

    useEffect(() => {
        if (!enabled) return;
        load();
    }, [enabled, load]);

    const loadMore = useCallback(() => {
        if (!hasMore || loading || !cursor) return;
        return load({ append: true, cursor });
    }, [hasMore, loading, cursor, load]);

    return {
        items,
        loading,
        error,
        hasMore,
        // Only ever true once an answer has actually arrived.
        isEmpty: loaded && !loading && !error && items.length === 0,
        loaded,
        reload: () => load(),
        loadMore,
    };
}

/**
 * What a row needs to be opened, previewed or downloaded.
 *
 * The revision id and hash travel TOGETHER, always. They are the pair every
 * guarded endpoint compares, so a row offering one without the other produces a
 * download or a submission that fails a staleness check the user can do nothing
 * about. A row with no generated revision is not downloadable and says so,
 * rather than offering a button that returns 409.
 */
export function rowActions(row) {
    const revisionId = (row && row.revision_id) || null;
    const pdfSha256 = revisionId ? (row.pdf_sha256 || null) : null;
    const ready = Boolean(revisionId && pdfSha256 && row.downloadable);
    return {
        canOpen: Boolean(row && row.id),
        canPreview: ready,
        canDownload: ready,
        revisionId,
        pdfSha256,
        // Said plainly so the UI can grey the control instead of failing later.
        reason: ready ? null
            : !revisionId ? "This document has not been generated yet."
            : "This document's file is not available.",
    };
}
