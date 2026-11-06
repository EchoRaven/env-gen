// API client — same-origin via the nginx proxy (/api, /auth -> backend).
const TOKEN_KEY = "nf_token";
const PROFILE_KEY = "nf_profile";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(t) {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}
export function getProfileId() {
  return localStorage.getItem(PROFILE_KEY);
}
export function setProfileId(p) {
  if (p) localStorage.setItem(PROFILE_KEY, String(p));
  else localStorage.removeItem(PROFILE_KEY);
}

export async function api(path, { method = "GET", body } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers["Authorization"] = "Bearer " + token;
  const profile = getProfileId();
  if (profile) headers["X-Profile-Id"] = profile;
  let res;
  try {
    res = await fetch(path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined
    });
  } catch (e) {
    return { status: 0, ok: false, data: {} };
  }
  let data = {};
  try {
    data = await res.json();
  } catch (e) {
    data = {};
  }
  return { status: res.status, ok: res.ok, data };
}

export const unwrapItem = (r) => (r.data && r.data.item ? r.data.item : {});
export const unwrapItems = (r) => (r.data && Array.isArray(r.data.items) ? r.data.items : []);
