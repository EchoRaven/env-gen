const API_ROOT = import.meta.env.VITE_API_URL || ''

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message)
    this.status = status
    this.body = body
  }
}

async function request(path, { method = 'GET', body, token, profileId, signal } = {}) {
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Bearer ${token}`
  if (profileId) headers['X-Profile-Id'] = String(profileId)
  const response = await fetch(`${API_ROOT}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
  const text = await response.text()
  let payload = null
  try { payload = text ? JSON.parse(text) : null } catch { payload = { detail: text } }
  if (!response.ok) {
    if (response.status === 401 && path.startsWith('/api/') && typeof window !== 'undefined') {
      window.dispatchEvent(new Event('netflix:unauthorized'))
    }
    const detail = payload?.detail
    const message = typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map((entry) => entry.msg || JSON.stringify(entry)).join(', ')
        : `Request failed (${response.status})`
    throw new ApiError(message, response.status, payload)
  }
  return payload
}

export function createApi(token, profileId) {
  const auth = { token, profileId }
  return {
    token,
    profileId,
    get: (path, opts = {}) => request(path, { ...opts, ...auth }),
    post: (path, body, opts = {}) => request(path, { ...opts, ...auth, method: 'POST', body }),
    put: (path, body, opts = {}) => request(path, { ...opts, ...auth, method: 'PUT', body }),
    delete: (path, opts = {}) => request(path, { ...opts, ...auth, method: 'DELETE' }),
  }
}

export const publicApi = {
  post: (path, body) => request(path, { method: 'POST', body }),
  get: (path) => request(path),
}

export function assetUrl(path) {
  if (!path) return ''
  if (/^https?:\/\//.test(path)) return path
  return path.startsWith('/') ? path : `/${path}`
}
