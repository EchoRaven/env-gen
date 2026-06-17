"""Frontend api.js export-completion — FIX #37.

The frontend lane writes ``src/services/api.js`` (the API client) AND the
components that import from it INDEPENDENTLY, so they drift on names: e.g. a
component does ``import { registerAccount }`` while api.js exports ``register``.
Rollup then fails the build ("registerAccount is not exported by api.js") → the
frontend docker image won't build → ``docker compose up --build`` fails →
api_smoke docker_up FAIL → NO DELIVERY, even though the backend is perfect.

This deterministically reconciles them — the frontend analog of the DDL projector
([[feedback_envgen_api_consistency_by_construction]]): every name a component
imports from api.js MUST resolve. For each missing export, alias it to the
best-matching existing export (name-normalized), or — if no match — emit a
throwing stub so the BUILD always succeeds (one unimplemented call beats a dead
app that won't build at all).
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_EXPORT_RE = re.compile(
    r"export\s+(?:async\s+)?(?:function|const|let|var)\s+([A-Za-z0-9_$]+)"
)
_EXPORT_BRACE_RE = re.compile(r"export\s*\{([^}]*)\}")
_IMPORT_API_RE = re.compile(
    r"import\s*\{([^}]*)\}\s*from\s*['\"][^'\"]*services/api(?:\.js)?['\"]"
)
_FRONT_EXTS = (".js", ".jsx", ".ts", ".tsx", ".mjs")
_STOPWORDS = ("account", "user", "users", "current", "data", "info",
              "details", "request", "api", "async", "the")


def _exported_names(api_src: str) -> Set[str]:
    names: Set[str] = set(_EXPORT_RE.findall(api_src))
    for body in _EXPORT_BRACE_RE.findall(api_src):
        for part in body.split(","):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"[A-Za-z0-9_$]+\s+as\s+([A-Za-z0-9_$]+)", part)
            names.add(m.group(1) if m else part)
    return names


def _imported_api_names(src: str) -> Set[str]:
    out: Set[str] = set()
    for body in _IMPORT_API_RE.findall(src):
        for part in body.split(","):
            part = part.strip()
            if not part:
                continue
            # within braces, `a as b` imports the source name `a`
            m = re.match(r"([A-Za-z0-9_$]+)\s+as\s+[A-Za-z0-9_$]+", part)
            out.add(m.group(1) if m else part)
    return out


def _norm(name: str) -> str:
    s = re.sub(r"[^a-z0-9]", "", name.lower())
    for w in _STOPWORDS:
        s = s.replace(w, "")
    return s


def _best_match(missing: str, exported: Set[str]) -> Optional[str]:
    target = _norm(missing)
    if not target:
        return None
    for e in exported:                       # exact normalized match
        if _norm(e) == target:
            return e
    cands = [e for e in exported if _norm(e) and (_norm(e) in target or target in _norm(e))]
    if cands:
        cands.sort(key=lambda e: abs(len(_norm(e)) - len(target)))
        return cands[0]
    return None


def repair_frontend_api_exports(frontend_dir) -> Dict[str, object]:
    """Ensure every name imported from api.js is exported by it. Mutates api.js
    in place (appends aliases/stubs). Returns a report dict; best-effort and
    never raises on a malformed tree."""
    try:
        frontend_dir = Path(frontend_dir)
        api_js = frontend_dir / "src" / "services" / "api.js"
        if not api_js.exists():
            cands = (list(frontend_dir.glob("src/**/services/api.*"))
                     or list(frontend_dir.glob("src/**/api.js")))
            if not cands:
                return {"repaired": False, "reason": "no api.js"}
            api_js = cands[0]
        api_src = api_js.read_text(encoding="utf-8")
        exported = _exported_names(api_src)

        imported: Set[str] = set()
        for f in frontend_dir.glob("src/**/*"):
            if f.suffix.lower() in _FRONT_EXTS and f.resolve() != api_js.resolve():
                try:
                    imported |= _imported_api_names(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
        missing: List[str] = sorted(n for n in imported if n and n not in exported)
        # apiGet/apiPost are PROJECTOR-OWNED: the page projector's
        # _ensure_api_helpers appends the real implementations. Stubbing them
        # here (live 1.2.0, 2026-06-10) made every projected page throw
        # "apiGet not implemented (auto-stub)" AND blocked the projector's
        # bail-check from ever installing the real ones. Delegate instead.
        if any(n in ("apiGet", "apiPost") for n in missing):
            try:
                from .frontend_page_projector import _ensure_api_helpers
                _ensure_api_helpers(api_js)
                api_src = api_js.read_text(encoding="utf-8")
                exported = _exported_names(api_src)
                missing = sorted(n for n in imported if n and n not in exported)
            except Exception:
                missing = [n for n in missing if n not in ("apiGet", "apiPost")]
        if not missing:
            return {"repaired": False, "missing": []}

        lines = ["", "// FIX #37: auto-reconciled api.js exports (component import/export drift)."]
        aliased, stubbed = [], []
        for name in missing:
            match = _best_match(name, exported)
            if match:
                lines.append(f"export const {name} = {match};")
                aliased.append((name, match))
            else:
                lines.append(
                    f"export const {name} = async (...args) => {{ "
                    f"throw new Error('{name} not implemented (auto-stub)'); }};"
                )
                stubbed.append(name)
        api_js.write_text(
            api_src.rstrip() + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
        return {"repaired": True, "aliased": aliased, "stubbed": stubbed,
                "api_js": str(api_js)}
    except Exception as exc:  # never break generation/validation
        return {"repaired": False, "error": f"{type(exc).__name__}: {exc}"}


_LOCAL_DEFAULT_IMPORT = re.compile(
    r"""import\s+([A-Za-z_$][\w$]*)\s+from\s+['"](\.[^'"]+)['"]""")
_COMPONENT_DIR = re.compile(r"/(pages|components|views|screens|routes)/")


def _stub_page_component(name: str) -> str:
    """A minimal default-exported React component (JSX automatic runtime — no
    React import needed, matching the lane's pages)."""
    label = re.sub(r"(?<!^)(?=[A-Z])", " ", name).replace("Page", "").strip() or name
    return (
        f"export default function {name}() {{\n"
        f"  return (\n"
        f'    <div className="glass rounded-[2rem] border border-white/10 px-8 py-16 text-center">\n'
        f'      <h2 className="text-xl font-semibold text-white">{label}</h2>\n'
        f'      <p className="mt-3 text-sm text-zinc-400">This section is being set up.</p>\n'
        f"    </div>\n"
        f"  );\n"
        f"}}\n"
    )


def scaffold_missing_local_pages(frontend_dir) -> Dict[str, object]:
    """Scaffold a valid stub for any LOCAL default import whose target file is
    missing. Root fix for the frontend half of the hollow-release bug (instagram
    MM, 2026-06-08): the frontend lane wires a page import + route
    (``import MessagesInboxPage from './pages/MessagesInboxPage'``) but never
    creates the file, so ``npm run build`` fails ("Could not resolve") and the
    frontend container can't boot. Build-integrity is framework-owned: project a
    minimal default-exported stub at the expected path so the app always builds.
    Restricted to component dirs (pages/components/views/screens/routes) so
    hooks/utils are never mis-stubbed. Best-effort; never clobbers a real file."""
    try:
        frontend_dir = Path(frontend_dir)
        src_root = (frontend_dir / "src").resolve()
        if not src_root.exists():
            return {"scaffolded": []}
        scaffolded: List[str] = []
        for f in src_root.glob("**/*"):
            if f.suffix.lower() not in _FRONT_EXTS or not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            for name, rel in _LOCAL_DEFAULT_IMPORT.findall(text):
                if not _COMPONENT_DIR.search(rel):
                    continue
                base = (f.parent / rel).resolve()
                if base.suffix:
                    target = base
                    if target.exists():
                        continue
                else:
                    if any(base.with_suffix(e).exists() for e in _FRONT_EXTS):
                        continue
                    if any((base / f"index{e}").exists() for e in _FRONT_EXTS):
                        continue
                    target = base.with_suffix(".jsx")
                try:
                    target.relative_to(src_root)
                except ValueError:
                    continue  # never write outside src/
                if target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(_stub_page_component(name), encoding="utf-8")
                scaffolded.append(str(target.relative_to(frontend_dir)))
        return {"scaffolded": sorted(set(scaffolded))}
    except Exception as exc:  # never break generation/validation
        return {"scaffolded": [], "error": f"{type(exc).__name__}: {exc}"}


def _pascal_case(name: str) -> str:
    """snake/kebab/space → PascalCase component name. ``youtube_home`` →
    ``YoutubeHome``; falls back to ``Page`` for empty input."""
    parts = re.split(r"[^A-Za-z0-9]+", str(name or ""))
    out = "".join(p[:1].upper() + p[1:] for p in parts if p)
    return out or "Page"


def _page_component_name(page: Dict[str, Any]) -> str:
    comp = str((page or {}).get("component") or "").strip()
    if comp and re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", comp):
        return comp
    return _pascal_case((page or {}).get("name"))


def _render_routed_app(entries: List[tuple]) -> str:
    """Generic React-Router App over the declared pages. DOMAIN-AGNOSTIC — no
    feed/login assumptions (unlike the social-shaped _BASELINE_APP_JSX it
    replaces). ``entries``: list of (component, route)."""
    imports = "\n".join(f"import {c} from './pages/{c}.jsx';" for c, _ in entries)
    routes = "\n".join(
        f'          <Route path="{r}" element={{<{c} />}} />' for c, r in entries)
    return (
        f"{_ROUTES_MARKER}\n"
        "// The orchestrator projects these routes from the registered ui_pages\n"
        "// contract so the app is navigable by construction. Filling page bodies?\n"
        "// Edit the files in ./pages/. Taking over routing yourself? Delete the\n"
        "// marker line above and this file becomes yours (never overwritten).\n"
        "import { BrowserRouter, Routes, Route } from 'react-router-dom';\n"
        f"{imports}\n\n"
        "export default function App() {\n"
        "  return (\n"
        "    <BrowserRouter>\n"
        "      <Routes>\n"
        f"{routes}\n"
        "      </Routes>\n"
        "    </BrowserRouter>\n"
        "  );\n"
        "}\n"
    )


def scaffold_pages_from_contract(frontend_dir, ui_pages: List[Dict[str, Any]]) -> Dict[str, object]:
    """Project one page-component STUB per registered ui_page + wire React-Router
    routes in App.jsx — the frontend analogue of the deterministic backend
    skeleton (models/db/schemas/main from the endpoint+table contract).

    Closes the build-asymmetry root cause (youtube run #13): the backend is
    framework-scaffolded from its contract so it completes reliably, but the
    frontend had to hand-author all N pages + routing from scratch — it built 1
    page, left 15 in_progress, and declared a hallucinated 'done' (blank shell →
    frontend_navigable gate = 0). With the contract projected to stubs + routes,
    the lane FILLS page bodies (write/edit) instead of authoring from nothing, and
    the app is navigable-by-construction the moment kickoff finalizes.

    Safety: page stubs are written ONLY when missing (never clobber a real page).
    App.jsx is (re)written ONLY when missing/empty or it still carries the
    ``@framework-managed-routes`` marker (the social-shaped baseline shell carries
    it; a lane that takes over routing deletes the marker → never overwritten).
    Idempotent + domain-agnostic. Best-effort; never raises."""
    try:
        frontend_dir = Path(frontend_dir)
        src = frontend_dir / "src"
        if not src.exists():
            return {"scaffolded": [], "routes": 0, "app_wired": False,
                    "skipped": "no src/ (baseline not scaffolded yet)"}
        pages_dir = src / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)

        scaffolded: List[str] = []
        entries: List[tuple] = []
        seen_components: Set[str] = set()
        used_routes: Set[str] = set()
        for i, page in enumerate(ui_pages or []):
            if not isinstance(page, dict):
                continue
            comp = _page_component_name(page)
            if comp in seen_components:
                continue
            seen_components.add(comp)
            route = str(page.get("route") or "").strip()
            if not route:
                nm = re.sub(r"[^a-z0-9]+", "-",
                            str(page.get("name") or comp).lower()).strip("-")
                route = "/" if not entries else f"/{nm or comp.lower()}"
            # de-dup routes so React-Router doesn't get two identical paths
            base_route, n = route, 2
            while route in used_routes:
                route = f"{base_route.rstrip('/')}/{n}"
                n += 1
            used_routes.add(route)
            entries.append((comp, route))

            target = pages_dir / f"{comp}.jsx"
            if not target.exists():
                target.write_text(_stub_page_component(comp), encoding="utf-8")
                scaffolded.append(str(target.relative_to(frontend_dir)))

        app_wired = False
        if entries:
            app = src / "App.jsx"
            existing = ""
            if app.exists():
                try:
                    existing = app.read_text(encoding="utf-8")
                except Exception:
                    existing = ""
            if (not existing.strip()) or (_ROUTES_MARKER in existing):
                app.write_text(_render_routed_app(entries), encoding="utf-8")
                app_wired = True
        return {"scaffolded": sorted(scaffolded), "routes": len(entries),
                "app_wired": app_wired}
    except Exception as exc:  # never raise into the orchestrator
        return {"scaffolded": [], "routes": 0, "app_wired": False,
                "error": str(exc)}


# FIX #40: framework-owned frontend BASELINE. The frontend lane is the least
# reliable lane — it variably produces nothing (empty app/frontend/, no
# Dockerfile → docker build can't even start → docker_up FAIL → no delivery).
# The frontend INFRASTRUCTURE (Dockerfile/nginx/start.sh/package.json/vite/
# tailwind) is standard, not app-specific, so the framework owns it; we also ship
# a minimal but real login+feed UI that exercises the framework /auth/* + /api/*
# so an empty-frontend run still delivers a working app. Gap-filling: every file
# is written ONLY when missing/empty, so a lane that DID produce code is never
# clobbered (its api.js drift is still healed by repair_frontend_api_exports).

_BASELINE_DOCKERFILE = """FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
# --legacy-peer-deps: lane-authored package.json frequently mixes dev-tool
# versions with conflicting peer ranges (live 2026-06-10: eslint@9 vs
# eslint-plugin-react-hooks@4 wanting eslint<=8 → ERESOLVE → the whole
# frontend image failed). Peer strictness on dev tooling must never block
# the container build; the build's real arbiter is vite build below.
RUN npm install --legacy-peer-deps
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY start.sh /start.sh
RUN chmod +x /start.sh
EXPOSE 3000
CMD ["/start.sh"]
"""

_BASELINE_NGINX = """server {
    listen ${UI_PORT};
    root /usr/share/nginx/html;

    location /api          { proxy_pass ${API_URL}; proxy_http_version 1.1; proxy_set_header Host $host; }
    location /auth         { proxy_pass ${API_URL}; proxy_http_version 1.1; proxy_set_header Host $host; }
    location /oauth        { proxy_pass ${API_URL}; proxy_http_version 1.1; proxy_set_header Host $host; }
    location /.well-known  { proxy_pass ${API_URL}; proxy_http_version 1.1; proxy_set_header Host $host; }
    location /             { try_files $uri $uri/ /index.html; }
}
"""

_BASELINE_START = """#!/bin/sh
set -e
: "${UI_PORT:=3000}"
: "${API_URL:=http://backend:8081}"
envsubst '${UI_PORT} ${API_URL}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf
exec nginx -g 'daemon off;'
"""

_BASELINE_PACKAGE_JSON = """{
  "name": "app-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": { "dev": "vite", "build": "vite build", "preview": "vite preview" },
  "dependencies": { "react": "^18.3.1", "react-dom": "^18.3.1" },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.1",
    "autoprefixer": "^10.4.19",
    "postcss": "^8.4.38",
    "tailwindcss": "^3.4.4",
    "vite": "^5.3.1"
  }
}
"""

_BASELINE_VITE = """import { defineConfig } from 'vite'
// JSX via Vite's BUILT-IN esbuild automatic runtime — NOT @vitejs/plugin-react.
// Round 44 white-screen: plugin-react failed to install (ERESOLVE) → vite fell
// back to esbuild CLASSIC jsx (React.createElement) with no React import →
// "React is not defined" → every page blank. The automatic runtime compiles
// JSX to react/jsx-runtime (no React global needed) and depends on NO external
// plugin, so a missing plugin-react can never blank the UI again.
export default defineConfig({
  esbuild: { jsx: 'automatic', jsxImportSource: 'react' },
  build: { outDir: 'dist' },
})
"""

_BASELINE_TAILWIND = """export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: { extend: {} },
  plugins: [],
}
"""

_BASELINE_POSTCSS = """export default { plugins: { tailwindcss: {}, autoprefixer: {} } }
"""

_BASELINE_INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>__APP_NAME__</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
"""

_BASELINE_INDEX_CSS = "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n"

_BASELINE_MAIN_JSX = """import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'
ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode><App /></React.StrictMode>
)
"""

_BASELINE_API_JS = """// Minimal API client. nginx proxies /api,/auth,/oauth to the backend (same-origin).
function authHeaders() {
  const t = localStorage.getItem('token')
  return t ? { Authorization: `Bearer ${t}` } : {}
}
export async function register({ username, email, password, full_name }) {
  const r = await fetch('/auth/register', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email, password, full_name }),
  })
  const d = await r.json().catch(() => ({}))
  if (d.access_token) localStorage.setItem('token', d.access_token)
  return d
}
export async function login({ email, username, password }) {
  const r = await fetch('/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, username, password }),
  })
  const d = await r.json().catch(() => ({}))
  if (d.access_token) localStorage.setItem('token', d.access_token)
  return d
}
export async function getFeed() {
  const r = await fetch('/api/feed', { headers: { ...authHeaders() } })
  return r.json().catch(() => ([]))
}
export function logout() { localStorage.removeItem('token') }
"""

_ROUTES_MARKER = "// @framework-managed-routes"

_BASELINE_APP_JSX = """// @framework-managed-routes
import React, { useState, useEffect } from 'react'
import { register, login, getFeed, logout } from './services/api.js'

export default function App() {
  const [token, setToken] = useState(localStorage.getItem('token'))
  const [feed, setFeed] = useState(null)
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({ username: '', email: '', password: '' })

  useEffect(() => { if (token) getFeed().then(setFeed).catch(() => {}) }, [token])

  async function submit(e) {
    e.preventDefault()
    const fn = mode === 'register' ? register : login
    const d = await fn(form)
    if (d.access_token) setToken(d.access_token)
  }
  function doLogout() { logout(); setToken(null); setFeed(null) }

  if (!token) {
    return (
      <div className="min-h-screen bg-black text-white flex items-center justify-center">
        <form onSubmit={submit} className="w-80 space-y-3 p-6 border border-gray-800 rounded-lg">
          <h1 className="text-3xl font-bold text-center mb-2">__APP_NAME__</h1>
          <input className="w-full p-2 bg-gray-900 rounded border border-gray-700"
            placeholder="username" value={form.username}
            onChange={e => setForm({ ...form, username: e.target.value })} />
          <input className="w-full p-2 bg-gray-900 rounded border border-gray-700"
            placeholder="email" value={form.email}
            onChange={e => setForm({ ...form, email: e.target.value })} />
          <input className="w-full p-2 bg-gray-900 rounded border border-gray-700"
            type="password" placeholder="password" value={form.password}
            onChange={e => setForm({ ...form, password: e.target.value })} />
          <button className="w-full p-2 bg-blue-600 hover:bg-blue-500 rounded font-semibold">
            {mode === 'register' ? 'Sign up' : 'Log in'}
          </button>
          <button type="button" className="w-full text-sm text-blue-400"
            onClick={() => setMode(mode === 'register' ? 'login' : 'register')}>
            {mode === 'register' ? 'Have an account? Log in' : 'New? Sign up'}
          </button>
        </form>
      </div>
    )
  }
  const posts = Array.isArray(feed) ? feed : (feed && (feed.items || feed.posts)) || []
  return (
    <div className="min-h-screen bg-black text-white">
      <header className="flex justify-between items-center p-4 border-b border-gray-800 sticky top-0 bg-black">
        <h1 className="text-xl font-bold">__APP_NAME__</h1>
        <button className="text-sm text-blue-400" onClick={doLogout}>Log out</button>
      </header>
      <main className="max-w-xl mx-auto p-4 space-y-4">
        {!feed && <p className="text-gray-500">Loading feed…</p>}
        {feed && posts.length === 0 && <p className="text-gray-500">No posts yet.</p>}
        {posts.map((p, i) => (
          <article key={p.id || i} className="border border-gray-800 rounded-lg overflow-hidden">
            <div className="p-3 font-semibold">{(p.author && p.author.username) || p.username || 'user'}</div>
            {p.image_url && <img src={p.image_url} alt="" className="w-full" />}
            <div className="p-3">{p.caption}</div>
          </article>
        ))}
      </main>
    </div>
  )
}
"""

_BC_AUTH_GUARD_JS = """// Global auth guard: any /api/ 401 redirects to /login. Patches BOTH fetch and
// XMLHttpRequest — lanes write their api layer with either (axios uses XHR).
function _bcOn401(url) {
  if (String(url).includes('/api/')
      && !['/login', '/register', '/signup'].includes(window.location.pathname)) {
    localStorage.removeItem('token');
    window.location.assign('/login');
  }
}
const _origFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const res = await _origFetch(input, init);
  if (res.status === 401) _bcOn401(typeof input === 'string' ? input : (input && input.url) || '');
  return res;
};
const _origOpen = XMLHttpRequest.prototype.open;
XMLHttpRequest.prototype.open = function (method, url, ...rest) {
  this.addEventListener('load', () => { if (this.status === 401) _bcOn401(url); });
  return _origOpen.call(this, method, url, ...rest);
};
"""

_BASELINE_FILES = {
    "Dockerfile": _BASELINE_DOCKERFILE,
    "nginx.conf.template": _BASELINE_NGINX,
    "start.sh": _BASELINE_START,
    "package.json": _BASELINE_PACKAGE_JSON,
    "vite.config.js": _BASELINE_VITE,
    "tailwind.config.js": _BASELINE_TAILWIND,
    "postcss.config.js": _BASELINE_POSTCSS,
    "index.html": _BASELINE_INDEX_HTML,
    "src/index.css": _BASELINE_INDEX_CSS,
    "src/main.jsx": _BASELINE_MAIN_JSX,
    "src/services/api.js": _BASELINE_API_JS,
    "src/App.jsx": _BASELINE_APP_JSX,
}


# FIX #44: the frontend BUILD TOOLING is infra, not app code — but the lane writes
# it, and writes it badly (5.5 pinned every dep to "latest", so tailwindcss=latest
# pulled v4 while the postcss config is v3-style → `npm run build` dies). The
# framework owns the tooling: force the pure-infra config files to known-good and
# PIN the build-tooling deps to compatible versions, while preserving the lane's
# src/ + any extra app deps (lucide-react, etc.). Guarantees the frontend builds.
_FRONTEND_TOOLING_PINS = {
    "react": "^18.3.1", "react-dom": "^18.3.1",
    "vite": "^5.3.1", "@vitejs/plugin-react": "^4.3.1",
    "tailwindcss": "^3.4.4", "postcss": "^8.4.38", "autoprefixer": "^10.4.19",
}
_FRONTEND_FORCE_INFRA = {
    "postcss.config.js": _BASELINE_POSTCSS,
    "tailwind.config.js": _BASELINE_TAILWIND,
    "vite.config.js": _BASELINE_VITE,
    "Dockerfile": _BASELINE_DOCKERFILE,
    "nginx.conf.template": _BASELINE_NGINX,
    "start.sh": _BASELINE_START,
}


def pin_frontend_build_tooling(frontend_dir) -> Dict[str, object]:
    """Force the frontend build tooling to known-good versions/configs so the
    image always builds. Overwrites the pure-infra config files and pins the
    build-tooling deps in package.json; preserves src/ + the lane's app deps."""
    try:
        fe = Path(frontend_dir)
        if not fe.exists():
            return {"pinned": False, "reason": "no frontend dir"}
        changed: List[str] = []
        for rel, content in _FRONTEND_FORCE_INFRA.items():
            p = fe / rel
            if (not p.exists()) or p.read_text(encoding="utf-8", errors="ignore") != content:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
                changed.append(rel)
        # CSS wiring is infra too: a lane-written src/main.jsx that omits
        # ``import './index.css'`` ships a bundle with NO stylesheet at all —
        # Tailwind never runs and every page renders as plain links on white
        # (instagram 2026-06-10 08:25). Enforce the import + the directives file.
        main_jsx = fe / "src" / "main.jsx"
        if main_jsx.exists():
            try:
                mtxt = main_jsx.read_text(encoding="utf-8")
                if "index.css" not in mtxt:
                    main_jsx.write_text("import './index.css';\n" + mtxt,
                                        encoding="utf-8")
                    changed.append("src/main.jsx (+index.css import)")
            except Exception:
                pass
        idx_css = fe / "src" / "index.css"
        try:
            if not idx_css.exists() or "@tailwind" not in idx_css.read_text(encoding="utf-8"):
                idx_css.parent.mkdir(parents=True, exist_ok=True)
                idx_css.write_text(_BASELINE_INDEX_CSS, encoding="utf-8")
                changed.append("src/index.css (tailwind directives)")
        except Exception:
            pass
        # Auth UX is infra too: every /api/ route is auth-gated by construction,
        # so an unauthenticated visit must land on /login — not an empty page
        # with a console full of 401s. A global fetch guard guarantees this
        # regardless of how the lane wrote its api helpers.
        try:
            bc_auth = fe / "src" / "bc_auth.js"
            if not bc_auth.exists() or bc_auth.read_text(encoding="utf-8") != _BC_AUTH_GUARD_JS:
                bc_auth.write_text(_BC_AUTH_GUARD_JS, encoding="utf-8")
                changed.append("src/bc_auth.js (401 → /login guard)")
            if main_jsx.exists():
                mtxt = main_jsx.read_text(encoding="utf-8")
                if "bc_auth" not in mtxt:
                    main_jsx.write_text("import './bc_auth.js';\n" + mtxt,
                                        encoding="utf-8")
                    changed.append("src/main.jsx (+bc_auth import)")
        except Exception:
            pass
        import json as _json
        pj = fe / "package.json"
        if pj.exists():
            try:
                data = _json.loads(pj.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            if isinstance(data, dict):
                for sect in ("dependencies", "devDependencies"):
                    d = data.get(sect)
                    if isinstance(d, dict):
                        for pkg, ver in _FRONTEND_TOOLING_PINS.items():
                            if pkg in d:
                                d[pkg] = ver
                dd = data.setdefault("devDependencies", {})
                if isinstance(dd, dict):
                    for pkg in ("tailwindcss", "postcss", "autoprefixer"):
                        if pkg not in (data.get("dependencies") or {}):
                            dd.setdefault(pkg, _FRONTEND_TOOLING_PINS[pkg])
                # Runtime deps the PROJECTED code requires (round 22: a lane
                # that skipped routing shipped no react-router-dom → projected
                # pages' imports failed the vite build).
                deps = data.setdefault("dependencies", {})
                if isinstance(deps, dict):
                    deps.setdefault("react-router-dom", "^6.26.0")
                # SCRIPTS are build INFRASTRUCTURE, not lane content (round 46:
                # a lane overwrote package.json with no "scripts" at all →
                # `npm run build` had no build script → docker build failed →
                # docker_up FAILED forever → no release). The Dockerfile runs
                # `vite build`, so force it regardless of what the lane wrote;
                # dev/preview are setdefault so a lane custom is kept.
                if not isinstance(data.get("scripts"), dict):
                    data["scripts"] = {}
                _scripts = data["scripts"]
                _scripts.setdefault("dev", "vite")
                _scripts["build"] = "vite build"
                _scripts.setdefault("preview", "vite preview")
                pj.write_text(_json.dumps(data, indent=2) + "\n", encoding="utf-8")
                changed.append("package.json")
        return {"pinned": bool(changed), "changed": changed}
    except Exception as exc:
        return {"pinned": False, "error": f"{type(exc).__name__}: {exc}"}


def scaffold_frontend_baseline(frontend_dir) -> Dict[str, object]:
    """Gap-fill a minimal buildable Vite+React+Tailwind+nginx frontend. Writes
    each standard file ONLY when missing/empty, so a lane that produced code is
    never clobbered. An empty-frontend run gets a complete login+feed app that
    builds + serves and hits the framework /auth/* + /api/feed. Best-effort."""
    try:
        frontend_dir = Path(frontend_dir)
        frontend_dir.mkdir(parents=True, exist_ok=True)
        written: List[str] = []
        # GENERALITY: baseline copy derives the display name from the project
        # directory — the templates carry __APP_NAME__, never a real brand.
        try:
            _app_name = frontend_dir.parent.parent.name.replace("_", " ").replace("-", " ").title() or "App"
        except Exception:
            _app_name = "App"
        for rel, content in _BASELINE_FILES.items():
            content = content.replace("__APP_NAME__", _app_name)
            p = frontend_dir / rel
            try:
                if p.exists() and p.read_text(encoding="utf-8", errors="ignore").strip():
                    continue
            except Exception:
                pass
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            written.append(rel)
        return {"scaffolded": bool(written), "written": written}
    except Exception as exc:
        return {"scaffolded": False, "error": f"{type(exc).__name__}: {exc}"}


__all__ = [
    "repair_frontend_api_exports",
    "scaffold_frontend_baseline",
    "pin_frontend_build_tooling",
]
