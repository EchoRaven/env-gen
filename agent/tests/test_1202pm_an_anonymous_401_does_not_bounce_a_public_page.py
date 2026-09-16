"""#1202pm: an anonymous visitor's 401 must not bounce a public page to /login.

The global guard sent ANY /api/ 401 to /login. A logged-out feed whose badge call needs a
user therefore could not be viewed; lanes exempted '/' by hand (r124 23 times, r123 8,
r121 7) and every framework delivery restored the redirect. Only a request that carried a
token has a session to lose.
"""
import json
import shutil
import subprocess
import sys
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

  // A. anonymous visitor (no token anywhere) on a public page
  delete store['access_token'];
  nextStatus = 401; pathname = '/'; assigned = null;
  out.anon_401 = await settles(window.fetch('/api/notifications/unread'), 120);
  out.anon_redirect = assigned;

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


def _run(tmp_path):
    f = tmp_path / "h.mjs"
    f.write_text(_HARNESS.replace("__GUARD__", fs._BC_AUTH_GUARD_JS), encoding="utf-8")
    p = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[-2000:]
    return json.loads(p.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not NODE, reason="node not available")
def test_an_anonymous_401_does_not_redirect_and_resolves(tmp_path):
    out = _run(tmp_path)
    assert out["anon_redirect"] is None, out
    assert out["anon_401"] == "settled", out


@pytest.mark.skipif(not NODE, reason="node not available")
def test_an_expired_session_still_redirects(tmp_path):
    out = _run(tmp_path)
    assert out["protected_redirect"] == "/login", out
    assert out["protected_401"] == "pending", out
