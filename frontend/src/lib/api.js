const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

// ─── Token helpers ────────────────────────────────────────────────────────────
export function getToken() {
  try { return localStorage.getItem('aai-token'); } catch { return null; }
}
export function setToken(t) {
  try { localStorage.setItem('aai-token', t); } catch {}
}
export function clearToken() {
  try { localStorage.removeItem('aai-token'); } catch {}
}

// ─── Core fetch wrapper ───────────────────────────────────────────────────────
// Returns { data, error, status }
// Automatically attaches Bearer token and retries once on 401 via refresh cookie.
async function apiFetch(path, options = {}) {
  const token = getToken();
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let res;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...options,
      headers,
      credentials: 'include', // sends httpOnly refresh_token cookie
    });
  } catch {
    return { data: null, error: { detail: 'Network error. Please check your connection.' }, status: 0 };
  }

  // Auto-refresh on 401
  if (res.status === 401 && token) {
    const refreshed = await _tryRefresh();
    if (refreshed) {
      headers['Authorization'] = `Bearer ${getToken()}`;
      try {
        res = await fetch(`${BASE}${path}`, { ...options, headers, credentials: 'include' });
      } catch {
        return { data: null, error: { detail: 'Network error. Please check your connection.' }, status: 0 };
      }
    } else {
      clearToken();
      return { data: null, error: { detail: 'Session expired. Please sign in again.' }, status: 401 };
    }
  }

  const body = await res.json().catch(() => ({}));
  return { data: res.ok ? body : null, error: res.ok ? null : body, status: res.status };
}

async function _tryRefresh() {
  try {
    const res = await fetch(`${BASE}/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
    });
    if (res.ok) {
      const body = await res.json();
      setToken(body.access_token);
      return true;
    }
    return false;
  } catch {
    return false;
  }
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
    return { data: null, error: { detail: 'Network error. Please check your connection.' }, status: 0 };
  }

  if (res.status === 401 && token) {
    const refreshed = await _tryRefresh();
    if (refreshed) {
      headers['Authorization'] = `Bearer ${getToken()}`;
      try {
        res = await fetch(`${BASE}${path}`, { method: 'POST', headers, credentials: 'include', body: formData });
      } catch {
        return { data: null, error: { detail: 'Network error. Please check your connection.' }, status: 0 };
      }
    } else {
      clearToken();
      return { data: null, error: { detail: 'Session expired. Please sign in again.' }, status: 401 };
    }
  }

  const body = await res.json().catch(() => ({}));
  return { data: res.ok ? body : null, error: res.ok ? null : body, status: res.status };
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

export async function getCaseTimeline(caseId) {
  return apiFetch(`/cases/${caseId}/timeline`);
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

// ─── Lawyers ─────────────────────────────────────────────────────────────────
export async function searchLawyers({ province, case_type, min_rating, availability, page = 1, page_size = 10 } = {}) {
  const p = new URLSearchParams();
  if (province)                             p.set('province', province);
  if (case_type)                            p.set('case_type', case_type);
  if (min_rating !== undefined)             p.set('min_rating', min_rating);
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
  const token = typeof window !== 'undefined' ? localStorage.getItem('aai-token') : '';
  const base  = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000') + '/api/v1';
  const res   = await fetch(`${base}/documents/${doc_id}/download`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) return { error: 'Download failed' };
  const blob = await res.blob();
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
  return { data: true };
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
