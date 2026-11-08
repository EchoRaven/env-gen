function authHeaders(extra = {}) {
  const headers = { ...extra }
  const token = localStorage.getItem('nf_token')
  if (token) headers.Authorization = `Bearer ${token}`
  try {
    const profile = JSON.parse(localStorage.getItem('nf_profile') || 'null')
    if (profile?.id) headers['X-Profile-Id'] = String(profile.id)
  } catch { /* ignore malformed local state */ }
  return headers
}

async function request(path, options = {}) {
  const headers = authHeaders(options.headers || {})
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  const response = await fetch(path, {
    ...options,
    headers,
    body: options.body && !(options.body instanceof FormData) ? JSON.stringify(options.body) : options.body,
  })
  const text = await response.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!response.ok) {
    const error = new Error(data?.detail || `Request failed (${response.status})`)
    error.status = response.status
    error.data = data
    if (response.status === 401 && !path.startsWith('/auth/')) {
      window.dispatchEvent(new CustomEvent('nf:unauthorized'))
    }
    throw error
  }
  return data
}

const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: 'POST', body }),
  patch: (path, body) => request(path, { method: 'PATCH', body }),
  delete: (path) => request(path, { method: 'DELETE' }),
  raw: request,
}
export default api
