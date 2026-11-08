export class ApiError extends Error {
  constructor(message, status, body) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

export async function request(path, options = {}, token = null, profileId = null) {
  const headers = { Accept: 'application/json', ...(options.headers || {}) }
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  if (token) headers.Authorization = `Bearer ${token}`
  if (profileId) headers['X-Profile-Id'] = String(profileId)
  let response
  try {
    response = await fetch(path, {
      ...options,
      headers,
      body:
        options.body !== undefined && !(options.body instanceof FormData)
          ? JSON.stringify(options.body)
          : options.body,
    })
  } catch {
    throw new ApiError('Unable to reach the Netflix service.', 0, null)
  }
  const contentType = response.headers.get('content-type') || ''
  const body = contentType.includes('application/json') ? await response.json() : await response.text()
  if (!response.ok) {
    const detail =
      (body && typeof body === 'object' && (body.detail || body.message)) ||
      (typeof body === 'string' && body) ||
      `Request failed (${response.status})`
    throw new ApiError(Array.isArray(detail) ? detail.map((d) => d.msg).join(', ') : detail, response.status, body)
  }
  return body
}

