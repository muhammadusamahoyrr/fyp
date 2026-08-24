const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

// ─── Token store (in-memory, audit #5) ────────────────────────────────────────
// The access token lives ONLY in memory — never localStorage — so an XSS payload
// can't read it out of persistent storage. The durable credential is the HttpOnly
// refresh cookie; on a hard refresh we silently re-mint the access token via
// /auth/refresh (see bootstrapAuth). Sibling tabs share the token over a
// BroadcastChannel so each cold load doesn't independently rotate the cookie.
let accessToken = null;

export function getToken() { return accessToken; }
export function setToken(t) { accessToken = t || null; if (t) _broadcastToken(t); }
export function clearToken() { accessToken = null; }

// ─── Cross-tab auth channel (BroadcastChannel) ────────────────────────────────
let _bc = null;                 // BroadcastChannel | false (unsupported) | null (uninit)
const _tokenWaiters = [];       // resolvers awaiting a sibling's token during boot

function _getBC() {
  if (_bc === null) {
    if (typeof BroadcastChannel !== 'undefined') {
      try {
        _bc = new BroadcastChannel('aai-auth');
        _bc.onmessage = (e) => {
          const msg = e?.data || {};
          if (msg.type === 'token' && msg.token) {
            accessToken = msg.token;                 // adopt without re-broadcasting
            while (_tokenWaiters.length) _tokenWaiters.shift()(msg.token);
          } else if (msg.type === 'token-request') {
            if (accessToken) { try { _bc.postMessage({ type: 'token', token: accessToken }); } catch { } }
          } else if (msg.type === 'logout') {
            accessToken = null;
            if (typeof window !== 'undefined') { try { window.location.href = '/login'; } catch { } }
          }
        };
      } catch { _bc = false; }
    } else { _bc = false; }
  }
  return _bc || null;
}

function _broadcastToken(t) { const bc = _getBC(); if (bc) { try { bc.postMessage({ type: 'token', token: t }); } catch { } } }
export function broadcastLogout() { const bc = _getBC(); if (bc) { try { bc.postMessage({ type: 'logout' }); } catch { } } }

// Ask sibling tabs for a token; resolve with one if it arrives within `ms`.
function _requestSiblingToken(ms = 150) {
  const bc = _getBC();
  if (!bc) return Promise.resolve(null);
  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } };
    _tokenWaiters.push(finish);
    try { bc.postMessage({ type: 'token-request' }); } catch { finish(null); }
    setTimeout(() => finish(null), ms);
  });
}

// Cross-tab-safe boot: adopt an in-memory/sibling token, else silently refresh.
// Returns true if an access token is available afterward. Used by AuthContext.
export async function bootstrapAuth() {
  if (accessToken) return true;                       // already have one this tab
  const sibling = await _requestSiblingToken();       // election: another tab holds one?
  if (sibling) { accessToken = sibling; return true; }
  if (await _tryRefresh()) return true;               // single-flight /auth/refresh
  // Simultaneous cold-load rotation race: give a sibling's broadcast a beat, retry once.
  const late = await _requestSiblingToken(250);
  if (late) { accessToken = late; return true; }
  return !!accessToken;
}

// Helper to format error details (including Pydantic arrays) into a safe, user-friendly error message string.
function formatResponseError(body) {
  let errorObj = typeof body === 'object' && body !== null ? body : { detail: body };
  let message = 'An unexpected error occurred.';
  if (errorObj.detail) {
    if (Array.isArray(errorObj.detail)) {
      message = errorObj.detail
        .map(e => {
          const field = e.loc ? e.loc[e.loc.length - 1] : '';
          const msg = e.msg || 'invalid value';
          const capitalizedField = field ? field.charAt(0).toUpperCase() + field.slice(1) : '';
          return capitalizedField ? `${capitalizedField}: ${msg}` : msg;
        })
        .join('; ');
    } else if (typeof errorObj.detail === 'string') {
      message = errorObj.detail;
    } else {
      message = JSON.stringify(errorObj.detail);
    }
  } else if (errorObj.message) {
    message = String(errorObj.message);
  } else if (errorObj.error) {
    message = String(errorObj.error);
  }
  errorObj.message = message;
  return errorObj;
}

// ─── Core fetch wrapper ───────────────────────────────────────────────────────
// Returns { data, error, status }
// Automatically attaches Bearer token and retries once on 401 via refresh cookie.
//
// opts.returnResponse — resolve `data` with the raw Response instead of parsed
// JSON, so callers can use .blob() (downloads) or .body.getReader() (SSE
// streams) while still getting the 401 auto-refresh. Errors are still parsed
// into `error`, so the response body is only consumed on the failure path.
async function apiFetch(path, options = {}) {
  const { returnResponse = false, ...fetchOptions } = options;
  const token = getToken();
  const headers = { 'Content-Type': 'application/json', ...fetchOptions.headers };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let res;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...fetchOptions,
      headers,
      credentials: 'include', // sends httpOnly refresh_token cookie
    });
  } catch {
    return { data: null, error: formatResponseError({ detail: 'Network error. Please check your connection.' }), status: 0 };
  }

  // Auto-refresh on 401
  if (res.status === 401 && token) {
    const refreshed = await _tryRefresh();
    if (refreshed) {
      headers['Authorization'] = `Bearer ${getToken()}`;
      try {
        res = await fetch(`${BASE}${path}`, { ...fetchOptions, headers, credentials: 'include' });
      } catch {
        return { data: null, error: formatResponseError({ detail: 'Network error. Please check your connection.' }), status: 0 };
      }
    } else {
      clearToken();
      return { data: null, error: formatResponseError({ detail: 'Session expired. Please sign in again.' }), status: 401 };
    }
  }

  if (returnResponse) {
    if (res.ok) return { data: res, error: null, status: res.status };
    const errBody = await res.json().catch(() => ({}));
    return { data: null, error: formatResponseError(errBody), status: res.status };
  }

  const body = await res.json().catch(() => ({}));
  return { data: res.ok ? body : null, error: res.ok ? null : formatResponseError(body), status: res.status };
}

// Streams a text/event-stream Response, invoking onToken(chunk) per SSE token.
// Shared by aiQueryStream / aiDraftStream / aiPleadingUrduStream.
async function _consumeSSE(res, onToken) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const raw = line.slice(6).trim();
      if (raw === '[DONE]') return;
      try {
        const parsed = JSON.parse(raw);
        if (parsed.error) throw new Error(parsed.error);
        if (parsed.content) onToken(parsed.content);
      } catch (e) {
        if (!(e instanceof SyntaxError)) throw e;
      }
    }
  }
}

// Single-flight: concurrent callers (parallel 401s + boot) collapse into ONE
// /auth/refresh. Critical because the refresh token is single-use + rotating —
// parallel refreshes would race, and all but the first would get "revoked".
let _refreshPromise = null;
async function _tryRefresh() {
  if (_refreshPromise) return _refreshPromise;
  _refreshPromise = (async () => {
    try {
      const res = await fetch(`${BASE}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      });
      if (res.ok) {
        const body = await res.json();
        setToken(body.access_token);   // sets in-memory + broadcasts to siblings
        return true;
      }
      return false;
    } catch {
      return false;
    } finally {
      _refreshPromise = null;
    }
  })();
  return _refreshPromise;
}

// ─── Auth ─────────────────────────────────────────────────────────────────────
export async function authLogin(email, password) {
  const { data, error, status } = await apiFetch('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  if (data?.access_token) setToken(data.access_token);
  return { data, error, status };
}

export async function authRegister({ full_name, email, password, role, phone }) {
  return apiFetch('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ full_name, email, password, role, phone: phone || null }),
  });
}

export async function authLogout() {
  const result = await apiFetch('/auth/logout', { method: 'POST' });
  clearToken();
  return result;
}

export async function authForgotPassword(email) {
  return apiFetch('/auth/forgot-password', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });
}

export async function authResetPassword(token, new_password) {
  return apiFetch('/auth/reset-password', {
    method: 'POST',
    body: JSON.stringify({ token, new_password }),
  });
}

// ─── Intake ───────────────────────────────────────────────────────────────────
export async function intakeStart() {
  return apiFetch('/intake/start', { method: 'POST' });
}

// step = 1..5,  data = plain object matching IntakeStep{n} fields
export async function intakeSaveStep(sessionToken, step, data) {
  return apiFetch(`/intake/${sessionToken}/step/${step}`, {
    method: 'PATCH',
    body: JSON.stringify({ data }),
  });
}

export async function intakeConvert(sessionToken, { language = "en", urgency = null } = {}) {
  return apiFetch(`/intake/${sessionToken}/convert`, {
    method: 'POST',
    body: JSON.stringify({ language, urgency }),
  });
}

export async function intakeGet(sessionToken) {
  return apiFetch(`/intake/${sessionToken}`);
}

export async function uploadIntakeEvidence(sessionToken, file) {
  const formData = new FormData();
  formData.append('file', file);
  return apiFetchMultipart(`/intake/${sessionToken}/evidence`, formData);
}

// answer = null on first call (get Q1); answer = string on second call (get Q2 or done)
export async function intakeClarify(sessionToken, answer = null) {
  return apiFetch(`/intake/${sessionToken}/clarify`, {
    method: 'POST',
    body: JSON.stringify({ answer }),
  });
}

// ─── Multipart fetch wrapper ──────────────────────────────────────────────────
// Mirrors apiFetch for FormData uploads: attaches Bearer token + retries on 401.
// Never sets Content-Type — browser must set it to inject the multipart boundary.
async function apiFetchMultipart(path, formData) {
  const token = getToken();
  const headers = token ? { Authorization: `Bearer ${token}` } : {};

  let res;
  try {
    res = await fetch(`${BASE}${path}`, { method: 'POST', headers, credentials: 'include', body: formData });
  } catch {
    return { data: null, error: formatResponseError({ detail: 'Network error. Please check your connection.' }), status: 0 };
  }

  if (res.status === 401 && token) {
    const refreshed = await _tryRefresh();
    if (refreshed) {
      headers['Authorization'] = `Bearer ${getToken()}`;
      try {
        res = await fetch(`${BASE}${path}`, { method: 'POST', headers, credentials: 'include', body: formData });
      } catch {
        return { data: null, error: formatResponseError({ detail: 'Network error. Please check your connection.' }), status: 0 };
      }
    } else {
      clearToken();
      return { data: null, error: formatResponseError({ detail: 'Session expired. Please sign in again.' }), status: 401 };
    }
  }

  const body = await res.json().catch(() => ({}));
  return { data: res.ok ? body : null, error: res.ok ? null : formatResponseError(body), status: res.status };
}

// ─── Voice / STT ─────────────────────────────────────────────────────────────
export async function transcribeAudio(audioBlob) {
  const formData = new FormData();
  const filename = audioBlob.type === 'audio/wav' ? 'recording.wav' : 'recording.webm';
  formData.append('audio', audioBlob, filename);
  return apiFetchMultipart('/voice/transcribe', formData);
}

// ─── Cases ───────────────────────────────────────────────────────────────────
export async function listCases({ page = 1, page_size = 10 } = {}) {
  const p = new URLSearchParams({ page, page_size });
  return apiFetch(`/cases?${p}`);
}

export async function getCase(caseId) {
  return apiFetch(`/cases/${caseId}`);
}

export async function createCase({ title, description, case_type, province }) {
  return apiFetch('/cases', {
    method: 'POST',
    body: JSON.stringify({ title, description, case_type, province }),
  });
}

export async function updateCase(caseId, updates) {
  return apiFetch(`/cases/${caseId}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });
}

export async function getCaseTimeline(caseId) {
  return apiFetch(`/cases/${caseId}/timeline`);
}

// Peshi tracker: record what happened at a hearing (lawyer only).
// outcome: adjourned | arguments_heard | evidence_recorded | order_reserved | decided | judge_on_leave | other
export async function recordHearingOutcome(caseId, hearingId, { outcome, note, next_date, next_time, next_purpose } = {}) {
  return apiFetch(`/cases/${caseId}/hearings/${hearingId}`, {
    method: 'PATCH',
    body: JSON.stringify({ outcome, note, next_date, next_time, next_purpose }),
  });
}

export async function addHearing(caseId, { date, court, judge, purpose, time, outcome }) {
  return apiFetch(`/cases/${caseId}/hearings`, {
    method: 'POST',
    body: JSON.stringify({
      date,
      court,
      judge: judge || null,
      purpose: purpose || null,
      time: time || null,
      outcome: outcome || null,
    }),
  });
}

export async function addMilestone(caseId, { title, description, date }) {
  return apiFetch(`/cases/${caseId}/milestones`, {
    method: 'POST',
    body: JSON.stringify({ title, description: description || null, date }),
  });
}

export async function listMessages(caseId) {
  return apiFetch(`/cases/${caseId}/messages`);
}

export async function sendMessage(caseId, text) {
  return apiFetch(`/cases/${caseId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
}

export async function listTasks(caseId) {
  return apiFetch(`/cases/${caseId}/tasks`);
}

export async function addTask(caseId, { title, due, priority, description }) {
  return apiFetch(`/cases/${caseId}/tasks`, {
    method: 'POST',
    body: JSON.stringify({ title, due: due || null, priority: priority || 'medium', description: description || null }),
  });
}

export async function toggleTask(caseId, taskId, done) {
  return apiFetch(`/cases/${caseId}/tasks/${taskId}`, {
    method: 'PATCH',
    body: JSON.stringify({ done }),
  });
}

// ─── Users ────────────────────────────────────────────────────────────────────
export async function getMe() {
  return apiFetch('/users/me');
}

export async function updateMe(updates) {
  return apiFetch('/users/me', { method: 'PATCH', body: JSON.stringify(updates) });
}

export async function changePassword(current_password, new_password) {
  return apiFetch('/users/me/password', { method: 'PATCH', body: JSON.stringify({ current_password, new_password }) });
}

// Close your own account: revokes access and erases personal details. Refuses
// while engagements or payments are still live, and says which.
export async function closeAccount(password) {
  return apiFetch('/users/me/close', { method: 'POST', body: JSON.stringify({ password }) });
}

// ─── Lawyers ─────────────────────────────────────────────────────────────────
export async function searchLawyers({ province, case_type, min_rating, availability, page = 1, page_size = 10 } = {}) {
  const p = new URLSearchParams();
  if (province) p.set('province', province);
  if (case_type) p.set('case_type', case_type);
  if (min_rating !== undefined) p.set('min_rating', min_rating);
  if (availability !== undefined && availability !== null) p.set('availability', availability);
  p.set('page', page);
  p.set('page_size', page_size);
  return apiFetch(`/lawyers?${p}`);
}

export async function matchLawyers(case_id) {
  return apiFetch(`/lawyers/match/${case_id}`);
}

export async function submitReview(lawyer_id, stars, comment) {
  return apiFetch(`/lawyers/${lawyer_id}/review`, {
    method: 'POST',
    body: JSON.stringify({ stars, comment: comment || null }),
  });
}

// ── Appointments ─────────────────────────────────────────────────────────────

export async function bookAppointment({ lawyer_id, case_id, scheduled_at, duration_minutes, mode, notes }) {
  return apiFetch('/appointments', {
    method: 'POST',
    body: JSON.stringify({
      lawyer_id,
      case_id: case_id || null,
      scheduled_at,
      duration_minutes: duration_minutes || 60,
      mode: mode || 'video',
      notes: notes || null,
    }),
  });
}

export async function listAppointments({ status, page, page_size } = {}) {
  const p = new URLSearchParams();
  if (status) p.set('status', status);
  if (page) p.set('page', page);
  if (page_size) p.set('page_size', page_size);
  const qs = p.toString() ? `?${p}` : '';
  return apiFetch(`/appointments${qs}`);
}

export async function getAppointment(id) {
  return apiFetch(`/appointments/${id}`);
}

export async function confirmAppointment(id) {
  return apiFetch(`/appointments/${id}/confirm`, { method: 'PATCH' });
}

// ─── Documents ────────────────────────────────────────────────────────────────

export async function extractDocumentFields(case_id, template_type) {
  return apiFetch('/documents/extract', {
    method: 'POST',
    body: JSON.stringify({ case_id, template_type }),
  });
}

export async function generateDocument(case_id, template_type, fields = {}) {
  return apiFetch('/documents/generate', {
    method: 'POST',
    body: JSON.stringify({ case_id, template_type, fields }),
  });
}

export async function listDocuments(case_id) {
  return apiFetch(`/documents/case/${case_id}`);
}

export async function downloadDocument(doc_id, filename = 'document.pdf') {
  // BASE already includes /api/v1 — do not append it again
  const { data: res, error } = await apiFetch(`/documents/${doc_id}/download`, { returnResponse: true });
  if (error) return { error: error.message || 'Download failed' };
  return _saveBlob(res, filename);
}

// Streams a Response body to a browser download. Shared by the PDF endpoints.
async function _saveBlob(res, filename) {
  let blob;
  try {
    blob = await res.blob();
  } catch {
    return { error: 'Download failed' };
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoke on the next tick — revoking synchronously can abort the download
  // in Firefox/Safari before the browser has read the object URL.
  setTimeout(() => URL.revokeObjectURL(url), 0);
  return { data: true };
}

// ─── Document review pipeline ────────────────────────────────────────────────
// Client submits a generated document to a lawyer; lawyer approves/returns/rejects.

export async function submitDocumentForReview(doc_id, { lawyer_id, note, urgency } = {}) {
  return apiFetch(`/documents/${doc_id}/submit`, {
    method: 'POST',
    body: JSON.stringify({
      lawyer_id: lawyer_id || null,
      note: note || null,
      urgency: urgency || 'normal',
    }),
  });
}

export async function reviewDocument(doc_id, { action, note } = {}) {
  return apiFetch(`/documents/${doc_id}/review`, {
    method: 'PATCH',
    body: JSON.stringify({ action, note: note || null }),
  });
}

export async function listReviewQueue() {
  return apiFetch('/documents/review-queue');
}

// ─── Live notifications ──────────────────────────────────────────────────────
// Exchanges the JWT for a one-time 60s WS ticket (the JWT itself never goes in
// the URL). Goes through apiFetch so an expired access token is refreshed and
// retried rather than failing the socket connect. Returns the ticket or null.
export async function getWsTicket() {
  if (!getToken()) return null;
  const { data } = await apiFetch('/auth/ws-ticket', { method: 'POST' });
  return data?.ticket ?? null;
}

// Opens the notification socket. Returns the WebSocket or null.
export async function openNotificationSocket(onMessage) {
  const ticket = await getWsTicket();
  if (!ticket) return null;

  const wsBase = BASE.replace(/\/api\/v1$/, '').replace(/^http/, 'ws');
  const ws = new WebSocket(`${wsBase}/ws/notifications?ticket=${encodeURIComponent(ticket)}`);
  ws.onmessage = (ev) => {
    try { onMessage(JSON.parse(ev.data)); } catch { }
  };
  return ws;
}

// ─── Case-law citator ────────────────────────────────────────────────────────

export async function citatorSearch(q, n = 8) {
  return apiFetch(`/citator/search?q=${encodeURIComponent(q)}&n=${n}`);
}

export async function citatorCitedBy(cite) {
  return apiFetch(`/citator/cited-by?cite=${encodeURIComponent(cite)}`);
}

export async function citatorStats() {
  return apiFetch('/citator/stats');
}

export async function citatorJudgment(id) {
  return apiFetch(`/citator/judgment/${id}`);
}

// ─── Payments (peshi/professional fees) ──────────────────────────────────────

export async function createFeeRequest({ case_id, amount, purpose, note, hearing_id, engagement_id }) {
  return apiFetch('/payments/fee-request', {
    method: 'POST',
    body: JSON.stringify({ case_id, amount, purpose, note, hearing_id, engagement_id }),
  });
}

export async function listPayments() {
  return apiFetch('/payments');
}

export async function paymentSummary() {
  return apiFetch('/payments/summary');
}

export async function getPayment(id) {
  return apiFetch(`/payments/${id}`);
}

export async function startCheckout(id) {
  return apiFetch(`/payments/${id}/checkout`, { method: 'POST' });
}

export async function mockPay(id) {
  return apiFetch(`/payments/${id}/mock-pay`, { method: 'POST' });
}

export async function downloadReceipt(id, filename = 'receipt.pdf') {
  const { data: res, error } = await apiFetch(`/payments/${id}/receipt`, { returnResponse: true });
  if (error) return { error: error.message || 'Download failed' };
  return _saveBlob(res, filename);
}

// ─── Billing / subscription ──────────────────────────────────────────────────

export async function billingPlans() {
  return apiFetch('/billing/plans');
}

export async function mySubscription() {
  return apiFetch('/billing/subscription');
}

export async function subscribePlan(tier, cycle = 'monthly') {
  return apiFetch('/billing/subscribe', {
    method: 'POST',
    body: JSON.stringify({ tier, cycle }),
  });
}

export async function cancelSubscription() {
  return apiFetch('/billing/cancel', { method: 'POST' });
}

// ─── Cause-list watcher (lawyer) ─────────────────────────────────────────────

export async function createCauselistWatch({ case_no, title_hint, case_id } = {}) {
  return apiFetch('/causelist/watches', {
    method: 'POST',
    body: JSON.stringify({ case_no, title_hint: title_hint || null, case_id: case_id || null }),
  });
}

export async function listCauselistWatches() {
  return apiFetch('/causelist/watches');
}

export async function deleteCauselistWatch(id) {
  return apiFetch(`/causelist/watches/${id}`, { method: 'DELETE' });
}

export async function checkCauselist() {
  return apiFetch('/causelist/check', { method: 'POST' });
}

export async function listCauselistEntries() {
  return apiFetch('/causelist/entries');
}

export async function matchCauselistText(text) {
  return apiFetch('/causelist/match-text', {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
}

// ─── Editor drafts (lawyer Drafter page) ─────────────────────────────────────

export async function saveDocDraft({ draft_id, title, content, template_name, template_icon, case_id } = {}) {
  return apiFetch('/documents/drafts', {
    method: 'POST',
    body: JSON.stringify({
      draft_id: draft_id || null,
      title,
      content,
      template_name: template_name || null,
      template_icon: template_icon || null,
      case_id: case_id || null,
    }),
  });
}

export async function listDocDrafts() {
  return apiFetch('/documents/drafts');
}

export async function deleteDocDraft(id) {
  return apiFetch(`/documents/drafts/${id}`, { method: 'DELETE' });
}

export async function cancelAppointment(id, reason) {
  return apiFetch(`/appointments/${id}/cancel`, {
    method: 'PATCH',
    body: JSON.stringify({ reason: reason || null }),
  });
}

export async function completeAppointment(id, { lawyer_notes, meeting_link } = {}) {
  return apiFetch(`/appointments/${id}/complete`, {
    method: 'PATCH',
    body: JSON.stringify({ lawyer_notes: lawyer_notes || null, meeting_link: meeting_link || null }),
  });
}

export async function markNoShow(id) {
  return apiFetch(`/appointments/${id}/no-show`, { method: 'PATCH' });
}

export async function getLawyerAvailability(lawyer_id, date) {
  return apiFetch(`/appointments/availability/${lawyer_id}?date=${date}`);
}

// ─── Engagements (hire a lawyer) ─────────────────────────────────────────────
// Client requests → lawyer accepts/declines → case is linked. The only path
// that assigns a lawyer to a case.

export async function requestEngagement({ case_id, lawyer_id, message }) {
  return apiFetch('/engagements', {
    method: 'POST',
    body: JSON.stringify({ case_id, lawyer_id, message: message || null }),
  });
}

export async function listEngagements({ status } = {}) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : '';
  return apiFetch(`/engagements${qs}`);
}

export async function acceptEngagement(engagement_id, { fee_amount, fee_type, scope_note } = {}) {
  return apiFetch(`/engagements/${engagement_id}/accept`, {
    method: 'PATCH',
    body: JSON.stringify({
      fee_amount: fee_amount ?? null,
      fee_type: fee_type || null,
      scope_note: scope_note || null,
    }),
  });
}

export async function declineEngagement(engagement_id, reason) {
  return apiFetch(`/engagements/${engagement_id}/decline`, {
    method: 'PATCH',
    body: JSON.stringify({ reason: reason || null }),
  });
}

export async function cancelEngagement(engagement_id) {
  return apiFetch(`/engagements/${engagement_id}/cancel`, { method: 'PATCH' });
}

// ─── Notifications ────────────────────────────────────────────────────────────
export async function getNotifications() {
  return apiFetch('/notifications');
}

export async function markNotificationRead(notification_id) {
  return apiFetch(`/notifications/${notification_id}/read`, { method: 'PATCH' });
}

export async function markAllNotificationsRead() {
  return apiFetch('/notifications/read-all', { method: 'POST' });
}

// ─── Agreements ───────────────────────────────────────────────────────────────

export async function createAgreement(title, body_html, party_ids) {
  return apiFetch('/agreements', {
    method: 'POST',
    body: JSON.stringify({ title, body_html, party_ids }),
  });
}

export async function signAgreement(agreement_id, method, signature_data) {
  return apiFetch(`/agreements/${agreement_id}/sign`, {
    method: 'POST',
    body: JSON.stringify({ method, signature_data }),
  });
}

export async function getAgreement(agreement_id) {
  return apiFetch(`/agreements/${agreement_id}`);
}

// ─── Lawyer Profile ───────────────────────────────────────────────────────────
export async function updateLawyerProfile(updates) {
  return apiFetch('/users/me/lawyer-profile', {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });
}

export async function listAgreements() {
  return apiFetch('/agreements');
}

// ─── AI ──────────────────────────────────────────────────────────────────────
// opts: { templateId?: "chat" | "case_context", context?: object, history?: array }
// `context` is a whitelisted set of case fields (case_title, case_type, court,
// client_name, next_hearing) — the server ignores any free-text system prompt.
export async function aiQuery(message, { templateId = "chat", context = {}, history = [] } = {}) {
  return apiFetch('/ai/query', {
    method: 'POST',
    body: JSON.stringify({ message, template_id: templateId, context, history }),
  });
}

// ─── Inheritance (Faraid) calculator ─────────────────────────────────────────
export async function inheritanceCalculate(estate_value, heirs) {
  return apiFetch('/inheritance/calculate', {
    method: 'POST',
    body: JSON.stringify({ estate_value, heirs }),
  });
}

export async function inheritanceSettlementPdf({ estate_value, heirs, deceased_name, date_of_death, estate_description }) {
  return apiFetch('/inheritance/settlement-pdf', {
    method: 'POST',
    body: JSON.stringify({ estate_value, heirs, deceased_name, date_of_death, estate_description }),
  });
}

export async function inheritanceDemandLetter(payload) {
  return apiFetch('/inheritance/demand-letter', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function wasiyyatCompute(payload) {
  return apiFetch('/inheritance/wasiyyat', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function wasiyyatPdf(payload) {
  return apiFetch('/inheritance/wasiyyat-pdf', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

// ─── Special-Court forum lookup (property disputes) ──────────────────────────

export async function disputeSpecialCourtProvinces() {
  return apiFetch('/disputes/special-court/provinces');
}
export async function disputeSpecialCourtPath(province) {
  return apiFetch(`/disputes/special-court/path?province=${encodeURIComponent(province)}`);
}

// Property-dispute intake (Special Courts, 2024 Act) — Phase 5a/5b/5c
export async function disputeFilingRisk(province) {
  return apiFetch(`/disputes/filing-risk?province=${encodeURIComponent(province)}`);
}
export async function disputeEligibility(id_type, days_abroad) {
  return apiFetch('/disputes/eligibility', { method: 'POST', body: JSON.stringify({ id_type, days_abroad }) });
}
export async function disputeClassify(text) {
  return apiFetch('/disputes/classify', { method: 'POST', body: JSON.stringify({ text }) });
}
export async function disputeCreate(payload) {
  return apiFetch('/disputes', { method: 'POST', body: JSON.stringify(payload) });
}
export async function disputeList() {
  return apiFetch('/disputes');
}
export async function disputeDraftPetition(id) {
  return apiFetch(`/disputes/${id}/petition`, { method: 'POST' });
}
// Case-brief handoff (read/handoff only — no fee, engagement or payment)
export async function disputeSendToLawyer(id) {
  return apiFetch(`/disputes/${id}/send-to-lawyer`, { method: 'POST' });
}
export async function disputeBrief(id) {
  return apiFetch(`/disputes/${id}/brief`);
}
export async function disputeLawyerInbox() {
  return apiFetch('/disputes/lawyer/inbox');
}

// ─── Legal calculators ────────────────────────────────────────────────────────

export async function courtFeeCalculate(payload) {
  return apiFetch('/calculators/court-fee', { method: 'POST', body: JSON.stringify(payload) });
}

export async function labourDuesCalculate(payload) {
  return apiFetch('/calculators/labour-dues', { method: 'POST', body: JSON.stringify(payload) });
}

export async function labourDemandPdf(payload) {
  return apiFetch('/calculators/labour-demand-pdf', { method: 'POST', body: JSON.stringify(payload) });
}

// ─── Bail checker ─────────────────────────────────────────────────────────────

export async function bailSearch(q, limit = 12) {
  const params = new URLSearchParams({ q: q || '', limit: String(limit) });
  return apiFetch(`/bail/search?${params.toString()}`);
}

export async function bailCheck({ law = 'PPC', section, arrested = true }) {
  return apiFetch('/bail/check', { method: 'POST', body: JSON.stringify({ law, section, arrested }) });
}

// Thumbs up/down on an AI answer (quality-feedback flywheel).
export async function rateAnswer({ session_id, rating, answer_preview = '', question_preview = '', comment = null, source = 'chat' }) {
  return apiFetch('/ai/rate', {
    method: 'POST',
    body: JSON.stringify({ session_id, rating, answer_preview, question_preview, comment, source }),
  });
}

// One-description fast path: legal notice / FIR pack / FIA complaint without a case.
export async function quickNotice(text, template_type = 'legal_notice', fields = null) {
  return apiFetch('/documents/quick-notice', {
    method: 'POST',
    body: JSON.stringify({ text, template_type, fields }),
  });
}

// RAG-grounded research (LangGraph pipeline) — returns { answer, citations, confidence } or a clarification question.
export async function aiResearch(message, session_id, { language = 'en', province = null, history = [] } = {}) {
  return apiFetch('/ai/research', {
    method: 'POST',
    body: JSON.stringify({ message, session_id, language, province, history }),
  });
}

// Streaming version — calls onToken(chunk) for each token, resolves when done.
// opts: { templateId?: "chat" | "case_context", context?: object, history?: array }
export async function aiQueryStream(message, { templateId = "chat", context = {}, history = [] } = {}, onToken) {
  const { data: res, error, status } = await apiFetch('/ai/query/stream', {
    method: 'POST',
    returnResponse: true,
    body: JSON.stringify({ message, template_id: templateId, context, history }),
  });
  if (error) throw new Error(error.message || `HTTP ${status}`);
  return _consumeSSE(res, onToken);
}

// RAG-grounded drafting: retrieves real Pakistani law before the LLM drafts.
export async function aiDraftStream({ instruction, document = '', template = '', case_type = 'civil', province = 'federal', history = [] }, onToken) {
  const { data: res, error, status } = await apiFetch('/ai/draft/stream', {
    method: 'POST',
    returnResponse: true,
    body: JSON.stringify({ instruction, document, template, case_type, province, history }),
  });
  if (error) throw new Error(error.message || `HTTP ${status}`);
  return _consumeSSE(res, onToken);
}

// ─── Court-Urdu pleading generator ────────────────────────────────────────────

export async function aiPleadingUrduStream({ document = '', template = '' }, onToken) {
  const { data: res, error, status } = await apiFetch('/ai/pleading-urdu/stream', {
    method: 'POST',
    returnResponse: true,
    body: JSON.stringify({ document, template }),
  });
  if (error) throw new Error(error.message || `HTTP ${status}`);
  return _consumeSSE(res, onToken);
}

export async function pleadingUrduPdf({ urdu_text, title_ur = '', court_ur = '', english_label = '' }) {
  return apiFetch('/ai/pleading-urdu/pdf', {
    method: 'POST',
    body: JSON.stringify({ urdu_text, title_ur, court_ur, english_label }),
  });
}

// ─── Admin ────────────────────────────────────────────────────────────────────
export async function adminGetAnalytics() {
  return apiFetch('/admin/analytics/overview');
}

export async function adminListPendingKYC() {
  return apiFetch('/admin/kyc/pending');
}

export async function adminProcessKYC(lawyerId, approved, rejectionReason = null) {
  return apiFetch(`/admin/kyc/${lawyerId}`, {
    method: 'PATCH',
    body: JSON.stringify({ approved, rejection_reason: rejectionReason }),
  });
}

export async function adminListUsers({ page = 1, pageSize = 20, role, search } = {}) {
  const q = new URLSearchParams({ page, page_size: pageSize });
  if (role && role !== 'all') q.set('role', role);
  if (search) q.set('search', search);
  return apiFetch(`/admin/users?${q}`);
}

export async function adminCreateUser({ full_name, email, role, password }) {
  return apiFetch('/admin/users', {
    method: 'POST',
    body: JSON.stringify({ full_name, email, role, password }),
  });
}

export async function adminUpdateUser(userId, data) {
  return apiFetch(`/admin/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function adminResetPassword(userId, newPassword) {
  return apiFetch(`/admin/users/${userId}/reset-password`, {
    method: 'POST',
    body: JSON.stringify({ new_password: newPassword }),
  });
}

export async function adminDeleteUser(userId) {
  return apiFetch(`/admin/users/${userId}`, { method: 'DELETE' });
}

export async function adminListCases({ page = 1, pageSize = 20, status, search } = {}) {
  const q = new URLSearchParams({ page, page_size: pageSize });
  if (status && status !== 'all') q.set('status', status);
  if (search) q.set('search', search);
  return apiFetch(`/admin/cases?${q}`);
}

export async function adminUpdateCaseStatus(caseId, status) {
  return apiFetch(`/admin/cases/${caseId}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  });
}

export async function adminListLawyers() {
  return apiFetch('/admin/lawyers/monitoring');
}
