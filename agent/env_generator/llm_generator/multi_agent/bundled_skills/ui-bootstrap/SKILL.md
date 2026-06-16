---
name: ui-bootstrap
description: Use when the frontend lane scaffolds a Vite + React UI for a sandbox env, or retrofits the standard tenant-picker / register flow / api.js wrapper onto an existing UI. Symptoms: page loads 401 because api.js auth:false mismatches a backend authRequired route; tenant CRUD 404s because UI nginx blanket-strips /api/ ahead of /api/v1/; "Create account" button does nothing; UI unreachable through gateway-proxy; wrong token storage key bleeds tokens across envs. Triggers on "create UI for", "frontend for env X", "add tenant picker", "wire login UI", "register flow on UI", "MCP nginx proxy /api". Not the env API itself (env-oauth-blueprint) or MCP wiring (mcp-server-bootstrap); for look-and-feel polish use frontend-design. Pairs with multi-tenancy-pattern (UI sends X-Tenant-ID) and env-oauth-blueprint (UI calls /auth/login + /auth/register).
---

# UI bootstrap for a sandbox env

**Frontend-lane** guide: how to write a React + Vite UI for a new env that follows the
conventions every other env's UI uses: standard token storage,
tenant picker, register flow, gateway-proxy integration. The orchestrator routes UI
scaffolding here; record `build:npm_install` / `build:docker_build` / `validation:ui_smoke`
via `codehub_record_check` as you go (don't claim the UI works before they're green — see
`verification-before-completion`).

**Boundary:** this skill is the STRUCTURE/plumbing (skeleton, api.js, login/register, tenant
picker, nginx proxy) plus just-enough brand recognizability. Production-grade look,
distinctive design, and reference-image fidelity when cloning a real product are
`frontend-design` (judged by `visual_review_gate` / `visual_similarity`); UX
state/hierarchy/consistency review is `ui-ux-review`.

Pair with `multi-tenancy-pattern` (UI sends `X-Tenant-ID` header) and
`env-oauth-blueprint` (UI calls `/auth/login` + `/auth/register`).

## The standard architecture

```
Browser
  ↓
gateway-proxy (port 22050, public-facing)
  ↓ location /<env>/  →
  <env>-ui container (port 22<NN>0, nginx serving Vite build)
  ↓ location /api/    →
  <env>-api container (port 22<NN>1, FastAPI / Express)
```

Three nginx-level concerns:
1. **gateway-proxy** routes `/<env>/` → UI container
2. **UI nginx** serves the SPA + reverse-proxies `/api/` → env API
3. **UI nginx** must NOT strip `/api/v1/` — that's a real path on most
   backends (tenant CRUD, reset). See gotcha #1 below.

## Visual style: match the real product

When the env mimics a real SaaS (Salesforce, Slack, Zoom, PayPal,
Atlassian, Telegram, ...), use the real product's visual
conventions so agents and humans see something recognizable.

| Aspect | What to copy |
|---|---|
| Primary brand color | Pull from the product's public homepage / login page |
| Terminology | "Leads/Opportunities" not "users/deals" (Salesforce); "channels/workspaces" not "rooms/groups" (Slack) |
| Layout idiom | Top tabs (Salesforce), left sidebar with channels (Slack), centered cards (Zoom meetings) |
| Logo / wordmark | Simple text in brand color — don't try to pixel-recreate the real logo |

Brand-color quick reference (from each product's site):
`Salesforce #00a1e0` · `Slack #611f69` · `PayPal #0070ba` ·
`Zoom #2d8cff` · `Atlassian #0052cc` · `WhatsApp #25d366` ·
`Telegram #0088cc` · `GitHub #24292f`.

**Why bother**: the env exists so an agent can operate in a realistic
target. If `salesforce-ui` looks like a generic Bootstrap CRM, the
agent's training-time mental model and what it actually sees diverge
— and prompt-engineering has to compensate. Matching brand color
+ terminology removes that tax cheaply.

**Scope**: ship only what red-data tasks exercise. Skip marketing
pages, onboarding wizards, settings panels, billing screens. UI
fidelity matters most on the **login page** (first impression and
the screen graders judge auth flows from) and the **primary list
screens** (where the agent spends most of its time).

When unsure: screenshot the real product's login page and use a
color picker.

## File layout

```
src/envs/<env>/
├── docker-compose.yml
└── <env>_ui/                  ← (or just ui/, follow neighbor envs)
    ├── Dockerfile
    ├── nginx.conf.template
    ├── start.sh
    ├── package.json
    ├── vite.config.js
    ├── index.html
    └── src/
        ├── main.jsx
        ├── App.jsx
        ├── api.js             ← token + tenant + http wrapper
        ├── tenantApi.js       ← (optional) tenant CRUD if api.js gets cluttered
        └── components/
            ├── LoginPage.jsx  ← email + password + Create account
            └── TenantPicker.jsx
```

## api.js — the standard HTTP wrapper

```javascript
// api.js — every env's UI follows this shape
const API_URL = import.meta.env.VITE_API_URL || ((window.__GATEWAY_BASE__ || '') + '/api');
const TOKEN_STORAGE_KEY = '<env>_token';   // <-- per-env key, not "access_token" alone

// ─── Tenant ──────────────────────────────────────────────────────────
export function getTenant() {
  try { return localStorage.getItem('X_TENANT_ID') || 'default'; }
  catch { return 'default'; }
}
export function setTenant(tid) {
  try { localStorage.setItem('X_TENANT_ID', tid || 'default'); } catch {}
}

// ─── Token ───────────────────────────────────────────────────────────
function getToken()   { try { return localStorage.getItem(TOKEN_STORAGE_KEY); } catch { return null; } }
export function setAuthToken(t) {
  try {
    if (t) localStorage.setItem(TOKEN_STORAGE_KEY, t);
    else   localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {}
}

// ─── Headers ─────────────────────────────────────────────────────────
function buildHeaders({ json = true, auth = true } = {}) {
  const h = {};
  if (json) h['Content-Type'] = 'application/json';
  if (auth) {
    const t = getToken();
    if (t) h.Authorization = `Bearer ${t}`;
  }
  h['X-Tenant-ID'] = getTenant();   // every request, authenticated or not
  return h;
}

// ─── Request wrapper ─────────────────────────────────────────────────
async function request(path, { method = 'GET', body, auth = true } = {}) {
  const r = await fetch(`${API_URL}${path}`, {
    method,
    headers: buildHeaders({ json: body !== undefined, auth }),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (r.status === 204) return null;
  const ct = r.headers.get('content-type') || '';
  const data = ct.includes('application/json') ? await r.json().catch(() => null) : await r.text().catch(() => null);
  if (!r.ok) {
    const err = new Error((data && (data.message || data.error)) || 'Request failed');
    err.status = r.status; err.details = data;
    throw err;
  }
  return data;
}

// ─── Auth ────────────────────────────────────────────────────────────
export async function login({ email, password }) {
  const data = await request('/auth/login', { method: 'POST', body: { email, password }, auth: false });
  if (data?.access_token) setAuthToken(data.access_token);
  return data;
}
export async function register({ email, name, password }) {
  return request('/auth/register', { method: 'POST', body: { email, name, password }, auth: false });
}
export async function getMe() { return request('/auth/me', { auth: true }); }
export function logout() { setAuthToken(null); }

// ─── Tenant CRUD (no auth — sandbox harness) ─────────────────────────
export async function listTenants() {
  const r = await fetch(`${API_URL}/v1/tenants`);
  if (!r.ok) throw new Error('Failed to list tenants');
  return r.json();
}
export async function createTenant(id, name) {
  const r = await fetch(`${API_URL}/v1/tenants`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, name: name || id }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// ─── Domain endpoints — every authRequired call uses auth: true ──────
export async function listThings(params = {}) { return request(`/things${qs(params)}`, { auth: true }); }
// ...
```

Key choices and why:

| Choice | Reason |
|---|---|
| `TOKEN_STORAGE_KEY = '<env>_token'` (not just `access_token`) | Avoids cross-env token confusion when multiple UIs share `localhost:22050` origin via gateway-proxy. The 5 Google envs DO share `access_token` on purpose (SSO); other envs should isolate. |
| `X-Tenant-ID` on every request | Even authenticated requests carry it as a redundant signal. Backend should trust JWT.tenant_id when present (server-signed), but the header lets unauth flows (register/login) carry tenant context too. |
| `request()` central wrapper | One place to add 401 handling, retries, error shape normalization. |
| Tenant CRUD via raw `fetch` | These are intentionally unauthenticated (sandbox harness). Don't run them through `buildHeaders` — no need for Authorization. |

## LoginPage — sign in + Create account

```jsx
// LoginPage.jsx
import { useState } from 'react';
import * as api from '../api';
import TenantPicker from './TenantPicker';

export default function LoginPage({ onLogin }) {
  // 'email' (sign-in step 1), 'password' (sign-in step 2), 'register' (create account)
  const [step, setStep] = useState('email');
  const [email, setEmail] = useState('');
  const [name,  setName]  = useState('');
  const [password, setPw] = useState('');
  const [err, setErr] = useState('');
  const [loading, setLoading] = useState(false);

  const persistAndContinue = (data) => {
    if (data?.access_token) localStorage.setItem('<env>_token', data.access_token);
    onLogin(data?.user || null);
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    if (!email.trim() || !name.trim() || !password) {
      setErr('Email, name, and password are all required'); return;
    }
    setLoading(true); setErr('');
    try {
      await api.register({ email: email.trim(), name: name.trim(), password });
      const data = await api.login({ email: email.trim(), password });
      persistAndContinue(data);
    } catch (e) { setErr(String(e.message || e)); }
    finally     { setLoading(false); }
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    if (step === 'email') {
      if (!email.trim()) { setErr('enter email'); return; }
      setStep('password'); return;
    }
    setLoading(true); setErr('');
    try { persistAndContinue(await api.login({ email, password })); }
    catch (e) { setErr('Wrong password'); }
    finally   { setLoading(false); }
  };

  return (
    <div className="login-screen">
      {/* TenantPicker visible on the login page so users can pick tenant before auth */}
      <div style={{ position: 'fixed', top: 16, right: 16, zIndex: 1000 }}>
        <TenantPicker />
      </div>

      <form onSubmit={step === 'register' ? handleRegister : handleLogin}>
        {step === 'email' && (
          <>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" autoFocus />
            <button type="submit">Next</button>
            {/* Critical: Create account must have onClick — see anti-pattern */}
            <button type="button" onClick={() => { setErr(''); setStep('register'); }}>
              Create account
            </button>
          </>
        )}
        {step === 'password' && (
          <>
            <input type="password" value={password} onChange={(e) => setPw(e.target.value)} placeholder="Password" autoFocus />
            <button type="submit" disabled={loading}>{loading ? 'Signing in...' : 'Sign in'}</button>
          </>
        )}
        {step === 'register' && (
          <>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" />
            <input type="text"  value={name}  onChange={(e) => setName(e.target.value)}  placeholder="Display name" />
            <input type="password" value={password} onChange={(e) => setPw(e.target.value)} placeholder="Password" />
            <button type="submit" disabled={loading}>{loading ? 'Creating...' : 'Create'}</button>
            <button type="button" onClick={() => { setErr(''); setStep('email'); }}>Sign in instead</button>
          </>
        )}
        {err && <div style={{ color: 'red' }}>{err}</div>}
      </form>
    </div>
  );
}
```

## TenantPicker — drop-in component

```jsx
// TenantPicker.jsx — copy verbatim from any of paypal/slack/whatsapp/zoom/telegram
// (they're all the same shape; src/envs/paypal/paypal_ui/src/TenantPicker.jsx is the canonical copy)
//
// Key prop: align="right" (default) for fixed-position top-right mounts on
// login screens; align="left" for in-sidebar mounts where the picker is on
// the left edge of a narrow container.

<TenantPicker />               {/* default — dropdown opens to the LEFT */}
<TenantPicker align="left" />  {/* dropdown opens to the RIGHT (sidebar) */}
```

The component:
- Reads `getTenant()` from `tenantApi.js` (or `api.js`)
- Shows current tenant in a chip-style button
- Click → dropdown listing tenants from `listTenants()`
- Switching: calls `setTenant(newId)`, `setAuthToken(null)`, then `window.location.reload()` — tokens are tenant-bound, can't be reused

## nginx.conf.template — the proxy gotcha

```nginx
server {
  listen $<ENV>_UI_PORT;
  server_name localhost;

  location / {
    root /usr/share/nginx/html;
    index index.html;
    try_files $uri /index.html;
  }

  # ★ CRITICAL: /api/v1/ MUST come BEFORE /api/ — see anti-pattern #1
  # Tenant CRUD + reset live at /api/v1/* on most backends with NO prefix
  # stripping (the path is already /api/v1/... on the backend).
  location /api/v1/ {
    proxy_pass http://127.0.0.1:${<ENV>_API_PORT};
    proxy_set_header Host $host;
    proxy_http_version 1.1;
  }

  # Other /api/* paths (legacy /auth/*, /tools/call) — strip /api/ prefix
  # because the backend serves them at root level.
  location /api/ {
    rewrite ^/api/(.*)$ /$1 break;
    proxy_pass http://127.0.0.1:${<ENV>_API_PORT};
    proxy_set_header Host $host;
    proxy_http_version 1.1;
  }
}
```

If your backend serves EVERYTHING under `/api/` (no rewrite needed),
collapse to one block without the rewrite. If your backend has a mix
(like paypal — `/auth/login` AND `/api/v1/tenants`), use the two-block
pattern above.

## start.sh (renders nginx config from env vars)

```bash
#!/bin/sh
set -eu
export <ENV>_UI_PORT="${<ENV>_UI_PORT:-80}"
export <ENV>_API_PORT="${<ENV>_API_PORT:-8000}"
envsubst '$<ENV>_UI_PORT $<ENV>_API_PORT' < /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf
exec nginx -g 'daemon off;'
```

## gateway-proxy registration

Add to `src/gateway-proxy/nginx.conf`:

```nginx
location /<env>/ {
    proxy_pass http://127.0.0.1:<UI_PORT>/;     # ← UI container's port
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection 'upgrade';

    sub_filter_once off;
    sub_filter_types text/html application/javascript text/javascript;
    sub_filter 'href="/' 'href="/<env>/';
    sub_filter 'src="/' 'src="/<env>/';
    sub_filter '"/assets/' '"/<env>/assets/';
    sub_filter '<head>' '<head><script>window.__GATEWAY_BASE__="/<env>";</script>';
}

# Optional: if your UI calls /api/* and gateway needs to passthrough
location /<env>/api/ {
    proxy_pass http://127.0.0.1:<UI_PORT>/api/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
}
```

The `<script>window.__GATEWAY_BASE__="/<env>"</script>` injection is
how UIs know they're running through gateway. `api.js` reads it:
```js
const API_URL = import.meta.env.VITE_API_URL || ((window.__GATEWAY_BASE__ || '') + '/api');
```

## Anti-patterns we've actually shipped (and fixed)

### ❌ #1: nginx blanket-strips /api/, breaking /api/v1/tenants

**paypal bug**: nginx had a single `location /api/ { rewrite ^/api/(.*)$ /$1 break; }`.
Tenant CRUD at `/api/v1/tenants` got rewritten to `/v1/tenants` —
which the backend doesn't serve there → 404.

**Fix**: split into two location blocks, `/api/v1/` first (passthrough),
`/api/` second (rewrite). nginx matches longest prefix.

### ❌ #2: frontend `auth: false` mismatched with backend `authRequired`

**atlassian bug**: frontend `api.js` had `listProjects` / `getIssues` /
etc. with `auth: false` (no Authorization header). Backend had
`router.get('/', authRequired, ...)` — added during the multi-tenancy
migration to scope by tenant. Result: every page load → 401 "Missing
Authorization header."

**Audit**: grep your `api.js` for `auth: false` and cross-check each
against the backend route. Default to `auth: true` for any read that
returns user-scoped data.

### ❌ #3: "Create account" button has no onClick

**gmail bug**: button was a styled `<button type="button">` with no
handler. Clicking did literally nothing. UI shipped that way for
weeks.

**Fix**: `onClick={() => setStep('register')}` and a register branch
in the form.

### ❌ #4: Wrong token storage key key for cross-UI sharing

**Convention**: each env's UI uses a per-env localStorage key
(`<env>_token`) so tokens don't bleed across envs sharing the
gateway-proxy origin.

**Exception**: the 5 Google envs (gmail, calendar, googledocs,
googlesheets, googledrive) intentionally share `access_token` for SSO
— their JWTs have multi-audience `aud` claim and are accepted by all
5 backends.

If your env is part of an SSO family, share the key. Otherwise, use a
unique key.

## Verification checklist

```bash
# 1. UI builds + serves
docker compose -f src/envs/<env>/docker-compose.yml build <env>-ui
docker compose -f src/envs/<env>/docker-compose.yml up -d --force-recreate <env>-ui
curl -s -o /dev/null -w "direct: %{http_code}\n" http://localhost:<UI_PORT>/

# 2. Reachable through gateway-proxy
curl -s -o /dev/null -w "gateway: %{http_code}\n" http://localhost:22050/<env>/

# 3. Tenant CRUD works through UI nginx (NOT 404)
curl -s -o /dev/null -w "tenants list: %{http_code}\n" http://localhost:<UI_PORT>/api/v1/tenants
curl -s -o /dev/null -w "tenant create: %{http_code}\n" -X POST http://localhost:<UI_PORT>/api/v1/tenants \
    -H 'Content-Type: application/json' -d '{"id":"smoke-test"}'

# 4. Auth works
curl -s -X POST http://localhost:<UI_PORT>/api/auth/login \
    -H 'Content-Type: application/json' -H 'X-Tenant-ID: default' \
    -d '{"email":"dev@virtueai.com","password":"virtue"}' | python3 -m json.tool
```

## Reference implementations

| Need | Best example |
|---|---|
| Vite + React, REST backend, no special quirks | `src/envs/whatsapp/ui/` |
| Vite + React, tools/call backend (MCP-style) | `src/envs/paypal/paypal_ui/` |
| Tenant picker drop-in | `src/envs/paypal/paypal_ui/src/TenantPicker.jsx` |
| Two-step login (email → password) | `src/envs/gmail/gmail_ui/src/components/LoginPage.jsx` |
| Single-step login | `src/envs/slack/slack_ui/src/App.js` |
| Express backend with /api/v1/* | `src/envs/atlassian/app/frontend/src/services/api.js` |

When in doubt, copy whatsapp's UI shape — it's the cleanest layout
post-multi-tenancy migration.
