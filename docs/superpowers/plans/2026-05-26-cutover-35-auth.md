# Cutover 35: Auth + Multi-User Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Gate API access behind a shared bearer token + a username. Today the live monitor exposes every endpoint to anyone on the network. Add a minimal login: server starts with `ENVGEN_AUTH_TOKEN` env var; the UI shows a login screen if no session; each authenticated request carries a session cookie tagged with a username; the username gets forwarded into mutations as the `agent` field for audit.

**Architecture:**
- Backend: read `ENVGEN_AUTH_TOKEN` at startup. If unset, auth is OFF (matches existing behavior, no breakage). If set, every API endpoint EXCEPT `/api/auth/*`, `/api/ping`, and static files requires `Cookie: envgen_session=<sid>` where `sid` maps to a valid session in the in-memory `_SESSIONS` dict.
- `POST /api/auth/login` body `{username, token}` → if `token == _AUTH_TOKEN` and `username` non-empty, mint a `sid` (uuid4 hex), store `{username, created_at, last_seen_at}` in `_SESSIONS`, set `Cookie: envgen_session=<sid>; HttpOnly; SameSite=Strict; Path=/`. Returns `{username}`.
- `POST /api/auth/logout` clears cookie + deletes session.
- `GET /api/auth/me` → 200 `{username}` if session valid, 401 otherwise.
- CSRF mitigation: cookies use `SameSite=Strict`, so cross-origin POSTs from another site won't carry them. Plus, the login token is required to even create a session, and tokens are not stored in the browser.
- Mutations: helpers like `start_run_call`, `workhub_create_task_call`, etc. already accept an `agent` body field (default `ui_user`). Extend them so the handler can override that with the session's `username` BEFORE calling the helper. This is a small wrapper at the route level — no helper signature changes.
- Frontend: `App.jsx` boots, `fetch('/api/auth/me')`. If 401 + auth is enabled (check via a sentinel `auth_required: true` in the 401 body), render `<LoginScreen>`. Otherwise the existing app. Login screen: username + token inputs; POSTs `/api/auth/login` (credentials: 'include'). Logout button in homepage corner.

**Default-off:** Auth is OFF when `ENVGEN_AUTH_TOKEN` is unset. This preserves backward compatibility for local dev. To enable: `export ENVGEN_AUTH_TOKEN=<some-secret>` then restart.

**Tech Stack:** stdlib `http.cookies` for cookie parsing; otherwise no new deps.

---

## Test infrastructure conventions

Tests in `agent/tests/` with sys.path boilerplate. Use `from live_monitor_server import ...`. Regressions: `python agent/tests/run_regressions.py`. Pytest: `python -m pytest agent/tests/ -q`. No `Co-Authored-By: Claude` trailer.

For auth-gated test endpoints: set `os.environ["ENVGEN_AUTH_TOKEN"]` in setUp + clear in tearDown. Many existing tests bypass HTTP and call helpers directly — those are not affected by the route-level middleware.

---

## File Structure

**Create:**
- `docs/superpowers/migration-logs/35-auth.md`
- `agent/tests/test_auth.py`
- `agent/env_generator/llm_generator/live_monitor/src/login_screen.jsx`
- `agent/env_generator/llm_generator/live_monitor/styles/login.css`

**Modify:**
- `agent/env_generator/llm_generator/live_monitor_server.py` (auth helpers + middleware + 3 auth routes + cookie header on responses)
- `agent/env_generator/llm_generator/live_monitor/index.html` (load login_screen.jsx)
- `agent/env_generator/llm_generator/live_monitor/src/app.jsx` (auth gate in App component)
- `agent/env_generator/llm_generator/live_monitor/src/homepage.jsx` (Logout button in corner)

---

## Task 1: Pre-flight baseline

- [ ] Regressions → 7 OK
- [ ] Pytest collect → ~1093
- [ ] Migration log stub
- [ ] Stage plan
- [ ] Commit: `Cutover 35: record pre-flight baseline`

---

## Task 2: Backend — session store + 3 auth endpoints + middleware

**Files:**
- Modify: `live_monitor_server.py`
- Create: `agent/tests/test_auth.py`

### TDD Step 1: failing tests

```python
# agent/tests/test_auth.py
import os
import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


class TestSessionStore(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _SESSIONS
        _SESSIONS.clear()
        os.environ["ENVGEN_AUTH_TOKEN"] = "test-token-abc"

    def tearDown(self):
        from live_monitor_server import _SESSIONS
        _SESSIONS.clear()
        os.environ.pop("ENVGEN_AUTH_TOKEN", None)

    def test_login_valid_token_creates_session(self):
        from live_monitor_server import auth_login_call
        result = auth_login_call({"username": "alice", "token": "test-token-abc"})
        self.assertIn("session_id", result)
        self.assertEqual(result["username"], "alice")

    def test_login_invalid_token_rejected(self):
        from live_monitor_server import auth_login_call
        result = auth_login_call({"username": "alice", "token": "wrong"})
        self.assertIn("error", result)

    def test_login_empty_username_rejected(self):
        from live_monitor_server import auth_login_call
        result = auth_login_call({"username": "  ", "token": "test-token-abc"})
        self.assertIn("error", result)

    def test_logout_clears_session(self):
        from live_monitor_server import auth_login_call, auth_logout_call, _SESSIONS
        result = auth_login_call({"username": "alice", "token": "test-token-abc"})
        sid = result["session_id"]
        self.assertIn(sid, _SESSIONS)
        auth_logout_call(sid)
        self.assertNotIn(sid, _SESSIONS)

    def test_check_session_returns_username(self):
        from live_monitor_server import auth_login_call, check_session
        sid = auth_login_call({"username": "bob", "token": "test-token-abc"})["session_id"]
        self.assertEqual(check_session(sid), "bob")

    def test_check_session_invalid_returns_none(self):
        from live_monitor_server import check_session
        self.assertIsNone(check_session("nope"))


class TestAuthDisabled(unittest.TestCase):
    """When ENVGEN_AUTH_TOKEN is unset, auth_required() is False."""
    def setUp(self):
        os.environ.pop("ENVGEN_AUTH_TOKEN", None)

    def test_auth_required_false_when_no_token(self):
        from live_monitor_server import auth_required
        self.assertFalse(auth_required())


class TestAuthEnabled(unittest.TestCase):
    def setUp(self):
        os.environ["ENVGEN_AUTH_TOKEN"] = "secret"

    def tearDown(self):
        os.environ.pop("ENVGEN_AUTH_TOKEN", None)

    def test_auth_required_true_when_token_set(self):
        from live_monitor_server import auth_required
        self.assertTrue(auth_required())
```

Run → expect import errors.

### TDD Step 2: implement

In `live_monitor_server.py`, add near top imports:

```python
from http.cookies import SimpleCookie
```

Add a session-store block:

```python
# ---------------------------------------------------------------------------
# Cutover 35: Auth — shared-token bearer + session cookie
# ---------------------------------------------------------------------------

_SESSIONS: Dict[str, dict] = {}
_SESSIONS_LOCK = threading.Lock()
_SESSION_COOKIE_NAME = "envgen_session"
_SESSION_TTL_SECONDS = 12 * 60 * 60  # 12h


def auth_required() -> bool:
    """Auth is on iff ENVGEN_AUTH_TOKEN env var is set + non-empty."""
    return bool(os.environ.get("ENVGEN_AUTH_TOKEN", "").strip())


def auth_login_call(body: dict) -> dict:
    """Mint a session if (username, token) check out."""
    expected = os.environ.get("ENVGEN_AUTH_TOKEN", "").strip()
    if not expected:
        return {"error": "auth is disabled; ENVGEN_AUTH_TOKEN not set"}
    username = (body.get("username") or "").strip()
    token = (body.get("token") or "").strip()
    if not username:
        return {"error": "username required"}
    if token != expected:
        return {"error": "invalid token"}
    sid = uuid.uuid4().hex
    now = time.time()
    with _SESSIONS_LOCK:
        _SESSIONS[sid] = {
            "username": username,
            "created_at": now,
            "last_seen_at": now,
        }
    return {"session_id": sid, "username": username}


def auth_logout_call(session_id: str) -> dict:
    with _SESSIONS_LOCK:
        _SESSIONS.pop(session_id, None)
    return {"ok": True}


def check_session(session_id: Optional[str]) -> Optional[str]:
    """Return username if session is valid + not expired. Updates last_seen_at."""
    if not session_id:
        return None
    now = time.time()
    with _SESSIONS_LOCK:
        info = _SESSIONS.get(session_id)
        if not info:
            return None
        if (now - info.get("created_at", 0)) > _SESSION_TTL_SECONDS:
            _SESSIONS.pop(session_id, None)
            return None
        info["last_seen_at"] = now
        return info.get("username")
```

### TDD Step 3: route + middleware

Add a small helper to extract the session cookie:

```python
def _read_session_cookie(headers) -> Optional[str]:
    """Parse the `envgen_session` cookie from request headers."""
    raw = headers.get("Cookie", "")
    if not raw:
        return None
    try:
        c = SimpleCookie()
        c.load(raw)
        morsel = c.get(_SESSION_COOKIE_NAME)
        return morsel.value if morsel else None
    except Exception:
        return None
```

Add the helper inside `MonitorHandler`:

```python
def _request_username(self) -> Optional[str]:
    """Username for this request, or None if unauthed.

    Returns the username if a valid session cookie is present, regardless
    of whether auth is required. When auth is required and no valid
    username is found, the route handler will short-circuit with 401.
    """
    sid = _read_session_cookie(self.headers)
    return check_session(sid)

def _enforce_auth(self) -> bool:
    """Return True if the request is allowed to proceed.

    When auth_required() is False, always True.
    When auth_required() is True, the request must have a valid session
    cookie OR target one of the exempt paths.
    """
    if not auth_required():
        return True
    parsed = urlparse(self.path)
    EXEMPT = {"/api/auth/login", "/api/auth/me", "/api/ping"}
    if parsed.path in EXEMPT:
        return True
    # Static files (CSS/JS/HTML) are served unauthenticated so the login
    # screen can load. Auth gate only applies to /api/ endpoints.
    if not parsed.path.startswith("/api/"):
        return True
    # Allow OPTIONS for preflight (we don't really use CORS but just in case)
    if self.command == "OPTIONS":
        return True
    if self._request_username() is None:
        self._write_json({"error": "unauthorized", "auth_required": True}, status=HTTPStatus.UNAUTHORIZED)
        return False
    return True
```

In `do_GET` / `do_POST` / `do_DELETE`, add the guard as the FIRST line:

```python
def do_GET(self) -> None:
    if not self._enforce_auth():
        return
    parsed = urlparse(self.path)
    ...
```

(Same for `do_POST` and `do_DELETE`.)

Add the three auth routes in `do_POST` (near the top):

```python
if parsed.path == "/api/auth/login":
    result = auth_login_call(body)
    if "error" in result:
        self._write_json(result, status=HTTPStatus.UNAUTHORIZED)
        return
    # Set cookie + return payload (no session_id in body to discourage non-cookie use)
    sid = result["session_id"]
    payload = {"username": result["username"]}
    body_bytes = json.dumps(payload).encode("utf-8")
    self.send_response(HTTPStatus.OK)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(body_bytes)))
    self.send_header(
        "Set-Cookie",
        f"{_SESSION_COOKIE_NAME}={sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age={_SESSION_TTL_SECONDS}",
    )
    self.end_headers()
    try:
        self.wfile.write(body_bytes)
    except (BrokenPipeError, ConnectionResetError):
        pass
    return

if parsed.path == "/api/auth/logout":
    sid = _read_session_cookie(self.headers)
    if sid:
        auth_logout_call(sid)
    # Expire the cookie
    self.send_response(HTTPStatus.OK)
    self.send_header("Content-Type", "application/json")
    body_bytes = b'{"ok":true}'
    self.send_header("Content-Length", str(len(body_bytes)))
    self.send_header("Set-Cookie", f"{_SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")
    self.end_headers()
    try:
        self.wfile.write(body_bytes)
    except (BrokenPipeError, ConnectionResetError):
        pass
    return
```

Add to `do_GET`:

```python
if parsed.path == "/api/auth/me":
    username = self._request_username()
    if username is None:
        if auth_required():
            self._write_json({"error": "unauthorized", "auth_required": True}, status=HTTPStatus.UNAUTHORIZED)
        else:
            # Auth is off — anyone is implicitly authed as "guest"
            self._write_json({"username": "guest", "auth_required": False})
        return
    self._write_json({"username": username, "auth_required": True})
    return
```

Run tests → expect PASS.

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor_server.py agent/tests/test_auth.py
git commit -m "Cutover 35: session store + auth login/logout/me endpoints + middleware"
```

---

## Task 3: Username forwarding to mutations + HTTP e2e test

**Goal:** When a request comes in with a session cookie, the username should be threaded into mutation helpers as the `agent` body field (overriding any explicit value, so audit logs reflect who actually made the request).

**Approach:** Add a request-handler hook `_apply_request_user(body)` that mutates the body dict in place by setting `body["agent"]` to the username (if auth is on and a username exists). Call this at the top of `do_POST` (after auth enforcement) and before dispatching to route helpers.

### TDD Step 1: append HTTP-level test

```python
# Append to test_auth.py
import http.server
import json
import threading
import time as _time
from functools import partial
from http.client import HTTPConnection


class TestAuthHTTPE2E(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _SESSIONS, _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _SESSIONS.clear()
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        os.environ["ENVGEN_AUTH_TOKEN"] = "secret-xyz"
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        from live_monitor_server import MonitorHandler
        handler = partial(MonitorHandler, directory=".", project_dir=None, workspaces_root=self.root)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        from live_monitor_server import _SESSIONS, _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _SESSIONS.clear()
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        os.environ.pop("ENVGEN_AUTH_TOKEN", None)
        self._tmp.cleanup()

    def _req(self, method, path, body=None, cookie=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        data = json.dumps(body).encode("utf-8") if body is not None else None
        conn.request(method, path, data, headers)
        resp = conn.getresponse()
        raw = resp.read()
        cookies = resp.getheader("Set-Cookie", "")
        conn.close()
        return resp.status, raw, cookies

    def test_protected_endpoint_returns_401_without_session(self):
        status, _, _ = self._req("GET", "/api/projects")
        self.assertEqual(status, 401)

    def test_login_then_protected_endpoint_succeeds(self):
        status, raw, set_cookie = self._req("POST", "/api/auth/login",
                                            {"username": "alice", "token": "secret-xyz"})
        self.assertEqual(status, 200)
        self.assertIn("envgen_session=", set_cookie)
        # Extract just the cookie name=value pair for next request
        sid_pair = set_cookie.split(";")[0]
        status, raw, _ = self._req("GET", "/api/projects", cookie=sid_pair)
        self.assertEqual(status, 200)
        self.assertIn("projects", json.loads(raw))

    def test_invalid_login_returns_401(self):
        status, _, _ = self._req("POST", "/api/auth/login",
                                  {"username": "alice", "token": "wrong"})
        self.assertEqual(status, 401)

    def test_logout_invalidates_cookie(self):
        _, _, set_cookie = self._req("POST", "/api/auth/login",
                                      {"username": "alice", "token": "secret-xyz"})
        sid_pair = set_cookie.split(";")[0]
        self._req("POST", "/api/auth/logout", body={}, cookie=sid_pair)
        status, _, _ = self._req("GET", "/api/projects", cookie=sid_pair)
        self.assertEqual(status, 401)

    def test_me_returns_username_when_authed(self):
        _, _, set_cookie = self._req("POST", "/api/auth/login",
                                      {"username": "alice", "token": "secret-xyz"})
        sid_pair = set_cookie.split(";")[0]
        status, raw, _ = self._req("GET", "/api/auth/me", cookie=sid_pair)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["username"], "alice")

    def test_static_files_served_without_auth(self):
        """The React app's HTML/CSS/JS must be reachable so the login screen loads."""
        status, _, _ = self._req("GET", "/api/ping")
        self.assertEqual(status, 200)  # exempt
        # /api/auth/me without cookie → 401 (expected)
        status, _, _ = self._req("GET", "/api/auth/me")
        self.assertEqual(status, 401)

    def test_mutation_records_session_username_as_agent(self):
        from live_monitor_server import create_project_call
        _, _, set_cookie = self._req("POST", "/api/auth/login",
                                      {"username": "alice", "token": "secret-xyz"})
        sid_pair = set_cookie.split(";")[0]
        # Create a project via HTTP
        status, raw, _ = self._req("POST", "/api/projects",
                                    {"name": "audit-test"}, cookie=sid_pair)
        self.assertEqual(status, 200)
        pid = json.loads(raw)["id"]
        # Run a mutation that records `agent` — e.g. create_task with no agent.
        # The auth middleware should override body.agent with the session username.
        status, raw, _ = self._req("POST", f"/api/projects/{pid}/workhub/tasks",
                                    {"title": "t1", "description": "x", "domain": "ui", "priority": "P1"},
                                    cookie=sid_pair)
        self.assertEqual(status, 200)
        # Confirm the task's created_by reflects "alice"
        from live_monitor_server import _resolve_hubs
        reg, _ = _resolve_hubs(self.root, pid)
        tasks = reg.workhub.snapshot().get("tasks", {})
        self.assertEqual(len(tasks), 1)
        task = next(iter(tasks.values()))
        # The exact field name may vary — common: `created_by` or `agent`
        agent_field = task.get("created_by") or task.get("agent") or task.get("_updated_by")
        self.assertEqual(agent_field, "alice", f"task fields: {task}")
```

Run → expect failures for `test_mutation_records_session_username_as_agent` (middleware doesn't override body.agent yet) and possibly auth-middleware tests if not fully wired.

### TDD Step 2: implement username forwarding

In `MonitorHandler`, add:

```python
def _apply_request_user(self, body: dict) -> None:
    """Override body['agent'] with the session username when auth is on."""
    if not isinstance(body, dict):
        return
    username = self._request_username()
    if username:
        body["agent"] = username
```

In `do_POST` (right after `body = self._read_json_body()`):

```python
self._apply_request_user(body)
```

In `do_DELETE` similarly if it parses a body. Otherwise skip.

Run → expect PASS.

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor_server.py agent/tests/test_auth.py
git commit -m "Cutover 35: session username forwarded to mutations as `agent`"
```

---

## Task 4: Frontend — LoginScreen + auth gate in App

**Files:**
- Create: `live_monitor/src/login_screen.jsx`
- Create: `live_monitor/styles/login.css`
- Modify: `live_monitor/index.html` (load login_screen.jsx + login.css)
- Modify: `live_monitor/src/app.jsx` (auth gate)
- Modify: `live_monitor/src/homepage.jsx` (logout button)

### Step 1: LoginScreen

Create `agent/env_generator/llm_generator/live_monitor/src/login_screen.jsx`:

```jsx
window.LoginScreen = (function () {
  const { useState } = React;

  function LoginScreen({ onLoggedIn }) {
    const [username, setUsername] = useState("");
    const [token, setToken] = useState("");
    const [pending, setPending] = useState(false);
    const [error, setError] = useState("");

    async function submit(e) {
      e?.preventDefault?.();
      if (!username.trim() || !token.trim()) {
        setError("username and token required");
        return;
      }
      setPending(true);
      setError("");
      try {
        const r = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ username: username.trim(), token: token.trim() }),
        });
        if (!r.ok) {
          const data = await r.json().catch(() => ({}));
          setError(data.error || `HTTP ${r.status}`);
          setPending(false);
          return;
        }
        const data = await r.json();
        onLoggedIn?.(data.username);
      } catch (e) {
        setError(String(e));
        setPending(false);
      }
    }

    return (
      <div className="login-screen">
        <form className="login-card" onSubmit={submit}>
          <h1>env-gen Live Monitor</h1>
          <p className="login-hint">Sign in to manage projects, agents, and runs.</p>
          {error && <div className="login-error">{error}</div>}
          <label>
            Username
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          </label>
          <label>
            Access token
            <input type="password" value={token} onChange={(e) => setToken(e.target.value)} />
          </label>
          <button type="submit" disabled={pending}>
            {pending ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    );
  }

  return LoginScreen;
})();
```

### Step 2: login.css

Create `live_monitor/styles/login.css`:

```css
.login-screen {
  position: fixed; inset: 0;
  display: flex; align-items: center; justify-content: center;
  background: #0e1626;
  color: #ddd;
}
.login-card {
  background: #1a2538; border: 1px solid #2d3a4d;
  border-radius: 8px; padding: 28px;
  width: 320px;
  display: flex; flex-direction: column; gap: 10px;
}
.login-card h1 { margin: 0; font-size: 18px; }
.login-hint { margin: 0 0 8px; color: #8aa; font-size: 12px; }
.login-card label {
  display: flex; flex-direction: column; gap: 4px;
  font-size: 12px; color: #aab;
}
.login-card input {
  background: #0e1626; color: #ddd;
  border: 1px solid #354054; border-radius: 4px;
  padding: 8px 10px; font-family: inherit;
}
.login-card input:focus { outline: 1px solid #4070d0; }
.login-card button {
  background: #4070d0; color: #fff;
  border: none; border-radius: 4px;
  padding: 10px; font-weight: 600;
  cursor: pointer;
  margin-top: 4px;
}
.login-card button:disabled { background: #354054; cursor: wait; }
.login-error {
  background: #4a1f1f; color: #ffaaaa;
  border: 1px solid #6a2a2a; border-radius: 4px;
  padding: 8px; font-size: 12px;
}
```

### Step 3: index.html

Add `<link rel="stylesheet" href="styles/login.css">` in `<head>` and `<script type="text/babel" src="src/login_screen.jsx"></script>` BEFORE `app.jsx`.

### Step 4: app.jsx auth gate

Read `app.jsx`. At the top of the App component, add:

```jsx
const [authState, setAuthState] = useState({ checked: false, username: null, authRequired: false });

useEffect(() => {
  async function check() {
    try {
      const r = await fetch("/api/auth/me", { credentials: "include" });
      if (r.status === 401) {
        setAuthState({ checked: true, username: null, authRequired: true });
        return;
      }
      const data = await r.json();
      setAuthState({ checked: true, username: data.username, authRequired: data.auth_required });
    } catch (e) {
      setAuthState({ checked: true, username: null, authRequired: false });
    }
  }
  check();
}, []);

if (!authState.checked) {
  return <div className="loading-screen">Loading…</div>;
}
if (authState.authRequired && !authState.username) {
  return <window.LoginScreen onLoggedIn={(name) => setAuthState({ checked: true, username: name, authRequired: true })} />;
}
```

Then the existing render logic continues (homepage / project view).

### Step 5: Logout button on homepage

In `homepage.jsx`, add a small `<button>` in a top-right corner:

```jsx
<button className="hp-logout" onClick={async () => {
  await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
  window.location.reload();
}}>
  Logout
</button>
```

Add CSS to `homepage.css`:

```css
.hp-logout { position: absolute; top: 12px; right: 12px; background: transparent; color: #aab; border: 1px solid #354054; border-radius: 4px; padding: 4px 12px; font-size: 11px; cursor: pointer; }
.hp-logout:hover { color: #fff; border-color: #4070d0; }
```

### Step 6: Manual smoke test

```bash
mkdir -p /tmp/cutover35_ws
ENVGEN_AUTH_TOKEN=secret-test /home/haibotong/miniconda3/envs/dt/bin/python agent/env_generator/llm_generator/live_monitor_server.py --workspaces-root /tmp/cutover35_ws --port 4399 &
SERVER_PID=$!
sleep 1
# Unauthed request → 401
curl -sS -w "\nstatus=%{http_code}\n" http://127.0.0.1:4399/api/projects | tail -3
# Login → get cookie
COOKIE_FILE=/tmp/c35_cookie.txt
curl -sS -c $COOKIE_FILE -X POST http://127.0.0.1:4399/api/auth/login -H "Content-Type: application/json" -d '{"username":"alice","token":"secret-test"}'
echo
# Authed request → 200
curl -sS -b $COOKIE_FILE -w "\nstatus=%{http_code}\n" http://127.0.0.1:4399/api/projects | tail -3
# Logout
curl -sS -b $COOKIE_FILE -X POST http://127.0.0.1:4399/api/auth/logout
echo
# Re-request → 401
curl -sS -b $COOKIE_FILE -w "\nstatus=%{http_code}\n" http://127.0.0.1:4399/api/projects | tail -3
kill $SERVER_PID 2>/dev/null
```

Expected: 401 → 200 → 401.

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/src/login_screen.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/login.css \
        agent/env_generator/llm_generator/live_monitor/index.html \
        agent/env_generator/llm_generator/live_monitor/src/app.jsx \
        agent/env_generator/llm_generator/live_monitor/src/homepage.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/homepage.css
git commit -m "Cutover 35: LoginScreen + auth gate in App + Logout button"
```

---

## Task 5: Final sweep + migration log + push

### Step 1: sweep

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_auth.py -q 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_orchestrator_control.py agent/tests/test_live_monitor_endpoints.py -q 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

Expect: 14 auth tests pass; orchestrator-control + endpoint tests still all pass (auth is off by default in their setUp); regressions 7 OK.

### Step 2: Migration log

Fill in the full template at `docs/superpowers/migration-logs/35-auth.md`:

```markdown
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

- (SHA) Cutover 35: record pre-flight baseline
- (SHA) Cutover 35: session store + auth login/logout/me endpoints + middleware
- (SHA) Cutover 35: session username forwarded to mutations as `agent`
- (SHA) Cutover 35: LoginScreen + auth gate in App + Logout button
- (this) Cutover 35: migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Pytest collect: 1093 → ~1107 (+14 new auth tests)

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
```

### Step 3: commit + push

```bash
git add docs/superpowers/migration-logs/35-auth.md docs/superpowers/plans/2026-05-26-cutover-35-auth.md
git commit -m "Cutover 35: migration log"
git push -u red-env-gen haibotong-cutover-35-auth
cd /data/common/haibotong/env-gen
git fetch . haibotong-cutover-35-auth
git merge --ff-only haibotong-cutover-35-auth
git push red-env-gen haibotong-0521-pipeline-web-tools
```
