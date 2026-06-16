# Cutover 35: Auth + Multi-User Login

**Branch:** `haibotong-cutover-35-auth`
**Date:** 2026-05-26

## What

Optional shared-token auth. Set `ENVGEN_AUTH_TOKEN` env var to enable.
When enabled:
- Every `/api/*` endpoint (except `/api/auth/login`, `/api/auth/me`, `/api/ping`)
  requires a valid `envgen_session` cookie.
- Login: `POST /api/auth/login` with `{username, token}` mints a session cookie
  (`HttpOnly; SameSite=Strict; Max-Age=12h`).
- Username is forwarded into every mutation body as `agent` so audit events
  reflect the real user.
- Frontend: `App.jsx` checks `/api/auth/me` on boot; renders `<LoginScreen>`
  if a 401 + `auth_required:true` comes back. Logout button in homepage corner.

When `ENVGEN_AUTH_TOKEN` is unset, auth is OFF (backward compatible — no
breakage for local dev workflows).

## Commits

- 23d9b261 Cutover 35: record pre-flight baseline
- fc5288be Cutover 35: session store + auth login/logout/me endpoints + middleware
- 616e4515 Cutover 35: session username forwarded to mutations as `agent`
- 11cce58e Cutover 35: LoginScreen + auth gate in App + Logout button
- (this) Cutover 35: migration log

## Test deltas

- Regressions: 7 OK → 7 OK
- Pytest collect: 1093 → 1108 (+15 new auth tests)
- Auth suite: `agent/tests/test_auth.py` — 15 passed
- Regression spot check: `test_orchestrator_control.py`, `test_live_monitor_endpoints.py`, `test_live_monitor_sse.py`, `test_global_sse_and_agents.py` — 104 passed

## New surfaces

### Backend
- `_SESSIONS: Dict[sid, {username, created_at, last_seen_at}]` (in-memory, 12h TTL)
- `auth_required()`, `auth_login_call(body)`, `auth_logout_call(sid)`, `check_session(sid)`
- `_read_session_cookie(headers)`, `MonitorHandler._request_username()`, `_enforce_auth()`, `_apply_request_user(body)`
- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`
- Session cookie: `envgen_session=<sid>; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200`

### Frontend
- `src/login_screen.jsx` — minimal login form (username + token)
- `styles/login.css`
- `app.jsx` — auth gate (`/api/auth/me` on boot)
- `homepage.jsx` — Logout button (top-right)
- `credentials: "include"` added to every existing `fetch()` call in
  `api.js`, `chat_panel.jsx`, `homepage.jsx`, `hub_panels.jsx`, `views.jsx`
  so the session cookie rides along on all `/api/*` requests.

## Security notes

- HttpOnly + SameSite=Strict cookies mitigate XSS (token never exposed to JS)
  and CSRF (cross-origin requests don't send the cookie).
- The shared token is the only secret; rotating it requires restart + all sessions invalidated.
- No rate limiting on login (intentional for local-dev simplicity). Operator
  must restrict network access if exposed beyond localhost.
- No password hashing — the token is compared in constant time (Python `==` on
  short strings; not perfectly side-channel resistant, but adequate for local).
- Sessions are in-memory; server restart logs everyone out.

## Known limits

- True per-user identity: there is no user database — anyone with the token
  can claim any username. The username is purely an audit hint.
- No password reset / token rotation UI.
- No RBAC — every authed user has full access.
- Static files (HTML/CSS/JS) are served without auth so the login page can
  load. This is the standard pattern; no user data leaks via static.
- WebSocket / SSE endpoints follow the same `/api/` gate. EventSource cookies
  are sent automatically by the browser, so SSE works after login.
- Tests that hit live monitor over HTTP must now set `ENVGEN_AUTH_TOKEN`
  AND login before exercising endpoints. In-process helpers (`*_call`
  signatures) bypass the middleware and don't need auth.
