const TOKEN_KEY = 'netflix_access_token'
const USER_KEY = 'netflix_user'
const PROFILE_KEY = 'netflix_profile_id'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const getStoredUser = () => {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null') } catch { return null }
}
export const getStoredProfileId = () => {
  const value = localStorage.getItem(PROFILE_KEY)
  return value ? Number(value) : null
}

export function storeSession({ access_token, user }) {
  if (access_token) localStorage.setItem(TOKEN_KEY, access_token)
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  localStorage.removeItem(PROFILE_KEY)
}

export function storeProfile(id) {
  if (id == null) localStorage.removeItem(PROFILE_KEY)
  else localStorage.setItem(PROFILE_KEY, String(id))
}

export async function api(path, options = {}) {
  const headers = { Accept: 'application/json', ...(options.headers || {}) }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const profileId = options.profileId ?? getStoredProfileId()
  if (profileId) headers['X-Profile-Id'] = String(profileId)
  let body = options.body
  if (body !== undefined && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(body)
  }
  const response = await fetch(path, { ...options, headers, body })
  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent('netflix:unauthorized'))
  }
  const text = await response.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!response.ok) {
    const message = data?.detail || data?.message || `Request failed (${response.status})`
    const error = new Error(Array.isArray(message) ? message.map(x => x.msg).join(', ') : message)
    error.status = response.status
    error.data = data
    throw error
  }
  return data
}

export const assetUrl = (path) => {
  if (!path) return ''
  if (/^https?:\/\//.test(path)) return path
  return '/' + String(path).replace(/^\/+/, '')
}

export const formatRuntime = (seconds) => {
  if (!seconds) return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return h ? `${h}h ${m}m` : `${m}m`
}
