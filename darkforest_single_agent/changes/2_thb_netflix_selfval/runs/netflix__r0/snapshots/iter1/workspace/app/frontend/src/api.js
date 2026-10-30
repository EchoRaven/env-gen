// Thin client for the Netflix API. Every call carries the bearer token and the
// active profile id (per-profile My List / ratings / Continue Watching).
const TOKEN_KEY = 'nf_token'
const PROFILE_KEY = 'nf_profile'

export const store = {
  get token() { return localStorage.getItem(TOKEN_KEY) },
  set token(v) { v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY) },
  get profileId() { return localStorage.getItem(PROFILE_KEY) },
  set profileId(v) { v ? localStorage.setItem(PROFILE_KEY, String(v)) : localStorage.removeItem(PROFILE_KEY) },
}

let onUnauthorized = () => {}
export function setUnauthorizedHandler(fn) { onUnauthorized = fn }

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status }
}

async function request(method, path, body) {
  const headers = { 'Content-Type': 'application/json' }
  if (store.token) headers.Authorization = `Bearer ${store.token}`
  if (store.profileId && path.startsWith('/api/')) headers['X-Profile-Id'] = store.profileId
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  let data = null
  try { data = await res.json() } catch { data = null }
  if (!res.ok) {
    if (res.status === 401 && path.startsWith('/api/')) onUnauthorized()
    if (res.status === 403 && path.startsWith('/api/') && store.profileId) {
      // Stale profile id (deleted or from another account): fall back to the default profile.
      store.profileId = null
    }
    const d = data && data.detail
    const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map((x) => x.msg).join(', ') : `Request failed (${res.status})`
    throw new ApiError(res.status, msg)
  }
  return data
}

const qs = (params = {}) => {
  const p = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  return p.length ? '?' + new URLSearchParams(p).toString() : ''
}

export const api = {
  register: (body) => request('POST', '/auth/register', body),
  login: (body) => request('POST', '/auth/login', body),
  me: () => request('GET', '/api/me'),

  profiles: () => request('GET', '/api/profiles'),
  createProfile: (body) => request('POST', '/api/profiles', body),
  updateProfile: (id, body) => request('PUT', `/api/profiles/${id}`, body),
  deleteProfile: (id) => request('DELETE', `/api/profiles/${id}`),

  titles: (params) => request('GET', '/api/titles' + qs(params)),
  title: (id) => request('GET', `/api/titles/${id}`),
  episodes: (id) => request('GET', `/api/titles/${id}/episodes`),
  trending: (params) => request('GET', '/api/titles/trending' + qs(params)),
  top10: (params) => request('GET', '/api/titles/top10' + qs(params)),
  rate: (id, value) => request('POST', `/api/titles/${id}/rating`, { value }),

  genres: (params) => request('GET', '/api/genres' + qs(params)),
  genre: (id) => request('GET', `/api/genres/${id}`),
  genreTitles: (id, params) => request('GET', `/api/genres/${id}/titles` + qs(params)),
  languages: () => request('GET', '/api/languages'),
  search: (q) => request('GET', '/api/search' + qs({ q })),

  myList: () => request('GET', '/api/my-list'),
  addToList: (titleId) => request('POST', '/api/my-list', { title_id: titleId }),
  removeFromList: (titleId) => request('DELETE', `/api/my-list/${titleId}`),

  continueWatching: () => request('GET', '/api/continue-watching'),
  saveProgress: (body) => request('POST', '/api/continue-watching', body),
  clearProgress: (titleId) => request('DELETE', `/api/continue-watching/${titleId}`),
}
