// Thin fetch wrapper: adds bearer token + active profile, throws on errors.
const TOKEN_KEY = 'nf_token';
const PROFILE_KEY = 'nf_profile';

export const session = {
  get token() { return localStorage.getItem(TOKEN_KEY); },
  set token(v) { v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY); },
  get profileId() { return localStorage.getItem(PROFILE_KEY); },
  set profileId(v) { v ? localStorage.setItem(PROFILE_KEY, String(v)) : localStorage.removeItem(PROFILE_KEY); },
};

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

export async function api(path, { method = 'GET', body, auth = true } = {}) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (auth && session.token) headers.Authorization = `Bearer ${session.token}`;
  if (auth && session.profileId) headers['X-Profile-Id'] = session.profileId;
  const res = await fetch(path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  let data = null;
  const text = await res.text();
  if (text) { try { data = JSON.parse(text); } catch { data = text; } }
  if (!res.ok) {
    if (res.status === 401 && auth) onUnauthorized();
    if (res.status === 403 && auth && session.profileId) { session.profileId = null; }
    const msg = (data && (typeof data.detail === 'string' ? data.detail : data.message)) || `Request failed (${res.status})`;
    throw new ApiError(res.status, msg);
  }
  // List endpoints answer {items, total}; callers work with the array.
  if (data && typeof data === 'object' && Array.isArray(data.items)) return data.items;
  return data;
}

export const API = {
  register: (b) => api('/auth/register', { method: 'POST', body: b, auth: false }),
  login: (b) => api('/auth/login', { method: 'POST', body: b, auth: false }),
  me: () => api('/api/me'),
  profiles: () => api('/api/profiles'),
  createProfile: (b) => api('/api/profiles', { method: 'POST', body: b }),
  updateProfile: (id, b) => api(`/api/profiles/${id}`, { method: 'PATCH', body: b }),
  deleteProfile: (id) => api(`/api/profiles/${id}`, { method: 'DELETE' }),
  titles: (params = {}) => api('/api/titles?' + new URLSearchParams(params)),
  title: (id) => api(`/api/titles/${id}`),
  episodes: (id) => api(`/api/titles/${id}/episodes`),
  trending: (params = {}) => api('/api/titles/trending?' + new URLSearchParams(params)),
  top10: (params = {}) => api('/api/titles/top10?' + new URLSearchParams(params)),
  genres: (params = {}) => api('/api/genres?' + new URLSearchParams(params)),
  genre: (id) => api(`/api/genres/${id}`),
  genreTitles: (id, params = {}) => api(`/api/genres/${id}/titles?` + new URLSearchParams(params)),
  search: (q) => api('/api/search?' + new URLSearchParams({ q })),
  myList: () => api('/api/my-list'),
  addMyList: (titleId) => api('/api/my-list', { method: 'POST', body: { title_id: titleId } }),
  removeMyList: (titleId) => api(`/api/my-list/${titleId}?by=title`, { method: 'DELETE' }),
  rate: (titleId, value) => api(`/api/titles/${titleId}/rating`, { method: 'POST', body: { value } }),
  ratings: () => api('/api/ratings'),
  continueWatching: () => api('/api/continue-watching'),
  saveProgress: (b) => api('/api/continue-watching', { method: 'POST', body: b }),
  removeProgress: (titleId) => api(`/api/continue-watching/${titleId}`, { method: 'DELETE' }),
};
