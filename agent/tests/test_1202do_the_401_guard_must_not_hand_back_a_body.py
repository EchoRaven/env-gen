r"""#1202do: the auth guard starts a redirect and then hands the caller the 401 anyway.

`_BC_AUTH_GUARD_JS` is framework-owned code injected into EVERY generated frontend. Its
fetch wrapper ends:

    const res = await _origFetch(input, init);
    if (res.status === 401) _bcOn401(url);
    return res;

`_bcOn401` calls `window.location.assign('/login')`, which SCHEDULES a navigation — it does
not stop execution. The wrapper then returns the 401 response, so the page carries on and
does what pages do with a list response:

    const data = await res.json();   // {"detail": "..."} — no `items`
    data.items.map(...)              // TypeError

netflix-r44's delivery died on exactly that, and it was one of the two final blockers:

    ui_smoke [failed] - UI smoke partially exercised: /, /login, /signup, /profiles,
    /episodes loaded; /titles crashed with 401-triggered TypeError. Remaining pages not
    certified because pass already failed.

    ui_flow:episodes_page [failed] - episodes_page flow reaches an episodes route but fails
    due unexpected auth/login 401 network error; green evidence not produced.

The backend was not at fault — the run's own orchestrator recorded "backend endpoints are
contract-correct and passing (17/17 endpoint probes passing); the 401 is expected", and the
verifier's own message says a tokenless request "is SUPPOSED to be rejected". The crash is
the guard's, and it is the framework's code, shipped into every environment.

The fix is the standard interceptor pattern: once a redirect is underway, never settle the
caller's promise, so no page code runs against a body that is not there.

The case that must NOT hang is the one `_bcOn401` already guards: a 401 while ON /login (or
/register, /signup) does not redirect, so its promise must still resolve normally — otherwise
the login page itself freezes, trading a crash for a hang.
"""
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime import frontend_scaffold as fs  # noqa: E402

NODE = shutil.which("node")

_HARNESS = r"""
globalThis.window = globalThis;
let assigned = null;
let nextStatus = 200;
let pathname = '/titles';
globalThis.window.location = {
  origin: 'http://x', get pathname() { return pathname; },
  assign: (u) => { assigned = u; },
};
const store = {};
globalThis.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = v; },
  removeItem: (k) => { delete store[k]; },
};
globalThis.sessionStorage = { getItem: () => null };
function XHR() {}
XHR.prototype.setRequestHeader = function () {};
XHR.prototype.open = function () {};
XHR.prototype.send = function () {};
XHR.prototype.addEventListener = function () {};
globalThis.XMLHttpRequest = XHR;
globalThis.window.fetch = async () => ({
  status: nextStatus, json: async () => ({ detail: 'Not authenticated' }),
});

__GUARD__

async function settles(p, ms) {
  return await Promise.race([
    p.then(() => 'settled'),
    new Promise((r) => setTimeout(() => r('pending'), ms)),
  ]);
}

(async () => {
  const out = {};

  // 1. 401 on a normal page: redirect starts, caller must NEVER get a body
  store['access_token'] = 't';
  nextStatus = 401; pathname = '/titles'; assigned = null;
  out.protected_401 = await settles(window.fetch('/api/titles'), 120);
  out.protected_redirect = assigned;

  // 2. 401 while already on /login: no redirect, so it must resolve (not hang)
  nextStatus = 401; pathname = '/login'; assigned = null;
  out.login_401 = await settles(window.fetch('/api/titles'), 120);
  out.login_redirect = assigned;

  // 3. a normal response is untouched
  nextStatus = 200; pathname = '/titles'; assigned = null;
  out.ok_200 = await settles(window.fetch('/api/titles'), 120);

  console.log(JSON.stringify(out));
})();
"""


def _run_guard(tmp_path: Path) -> dict:
    js = _HARNESS.replace("__GUARD__", fs._BC_AUTH_GUARD_JS)
    f = tmp_path / "guard_harness.mjs"
    f.write_text(js, encoding="utf-8")
    p = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[-2000:]
    return json.loads(p.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not NODE, reason="node not available")
def test_a_401_that_redirects_never_settles(tmp_path):
    """The r44 crash: page code must not run against a body that is not there."""
    out = _run_guard(tmp_path)
    assert out["protected_redirect"] == "/login", out
    assert out["protected_401"] == "pending", (
        "the guard handed the 401 back to the caller — `await res.json()` then "
        "`data.items.map(...)` is the TypeError that killed r44's /titles: %r" % out)


@pytest.mark.skipif(not NODE, reason="node not available")
def test_a_401_on_the_login_page_still_resolves(tmp_path):
    """No redirect means no hang — otherwise a crash is traded for a frozen login page."""
    out = _run_guard(tmp_path)
    assert out["login_redirect"] is None, out
    assert out["login_401"] == "settled", out


@pytest.mark.skipif(not NODE, reason="node not available")
def test_a_normal_response_is_untouched(tmp_path):
    out = _run_guard(tmp_path)
    assert out["ok_200"] == "settled", out


def test_the_guard_states_why_it_withholds_the_response():
    """Always-on floor: the behaviour is visible in the shipped source.

    Anchored on the EXPLANATION rather than on a ticket number. It used to assert
    `"1202do" in ...`, which made a passing test require the framework's own
    changelog tag to ship inside every generated app -- the thing the standing
    rule (2026-06-18) forbids and `#1202mi` now strips. The number was only ever
    a proxy for "the reason is stated"; assert the reason.
    """
    src = fs._BC_AUTH_GUARD_JS
    assert "SCHEDULES a navigation" in src, src[:400]
    assert "does not stop execution" in src
    assert "Report whether a navigation was actually started" in src
    # and the proxy it replaced must NOT come back
    assert "1202do" not in src
