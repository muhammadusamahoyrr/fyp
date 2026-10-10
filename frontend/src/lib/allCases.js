/* Every case the caller can see, not just the first page.
 *
 * GET /cases pages at most 50 per request. Pages that list or count a user's
 * cases (the lawyer's Cases and Clients pages, the client's hire picker) read
 * one page of 50 and treated it as everything, so case 51 onwards silently did
 * not exist there.
 *
 * Bounded: at most MAX_PAGES requests. `complete` says whether the server's
 * own page count was reached, so a caller can say "showing the first N"
 * instead of presenting a partial list as the whole.
 *
 * `listCases` is passed in (the caller's own import of the API client) rather
 * than imported here, so this stays a pure helper over whatever client the
 * page is using.
 */

export const PAGE_SIZE = 50;
export const MAX_PAGES = 20;

export async function listAllCases(listCases, params = {}) {
    const items = [];
    const seen = new Set();
    let page = 1;
    let pages = 1;
    let total = null;
    while (page <= pages && page <= MAX_PAGES) {
        const { data, error } = await listCases({ ...params, page, page_size: PAGE_SIZE });
        if (error || !Array.isArray(data?.items)) {
            // The first page failing is a failed read; a later one keeps what
            // was read and is reported as incomplete, not as the whole list.
            if (page === 1) return { data: null, error: error || { message: "Could not load cases." } };
            return { data: { items, total, complete: false }, error: null };
        }
        for (const c of data.items) {
            const id = c._id || c.id;
            // Rows shift between pages when something changes mid-read.
            if (id && seen.has(id)) continue;
            if (id) seen.add(id);
            items.push(c);
        }
        if (Number.isInteger(data.total)) total = data.total;
        pages = Number.isInteger(data.pages) ? data.pages : page;
        page += 1;
    }
    return { data: { items, total, complete: page > pages }, error: null };
}
