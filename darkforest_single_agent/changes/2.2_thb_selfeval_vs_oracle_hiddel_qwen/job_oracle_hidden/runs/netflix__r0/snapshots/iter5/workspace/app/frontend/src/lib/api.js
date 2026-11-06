const TOKEN_KEY = 'nf_token';
const USER_KEY = 'nf_user';
const PROFILE_KEY = 'nf_profile';

export function getToken() { return localStorage.getItem(TOKEN_KEY) || null; }
export function getStoredUser() {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null'); } catch { return null; }
}
export function getStoredProfile() {
  try { return JSON.parse(localStorage.getItem(PROFILE_KEY) || 'null'); } catch { return null; }
}
export function setSession(token, user, profileId) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
  if (profileId != null) localStorage.setItem(PROFILE_KEY, String(profileId));
}
export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(PROFILE_KEY);
}

export async function api(path, { method = 'GET', body = null, profileId = null } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const pid = profileId ?? getStoredProfile();
  if (pid != null) headers['X-Profile-Id'] = String(pid);
  let res;
  try {
    res = await fetch(path, {
      method,
      headers,
      body: body != null ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new Error('Network error');
  }
  if (res.status === 401 && token) {
    clearSession();
    if (!window.location.pathname.startsWith('/login')) window.location.href = '/login';
    throw new Error('Unauthorized');
  }
  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch { data = text; }
  }
  if (
    data && typeof data === 'object' && !Array.isArray(data)
    && Array.isArray(data.items) && Object.keys(data).length === 1
  ) {
    data = data.items;
  }
  if (!res.ok) {
    const msg = data && data.detail ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : res.statusText;
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return data;
}
