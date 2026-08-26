"""#1108: the login page stores the token under a key the app never reads.

The scaffolded login page writes ``localStorage.setItem('access_token', token)``.
A lane-authored ``services/api.js`` routinely namespaces its own key —
``const TOKEN_KEY = 'tiktok_token'`` — and reads THAT. Nothing writes it, so
``getToken()`` returns null, no Authorization header is attached, and every
authenticated request 401s. The user logs in and the app stays on the login wall.

Found by driving the delivered frontends in a real browser (bundled chromium, built
with the run's own package.json, served same-origin with its API proxied, logged in as
a SEEDED user — which only became possible after #1105 put users in the database).
tiktok-r54, measured before and after this repair:

    rendered text over 13 pages   2053  ->  14668
    401 responses                   17  ->      0
    every page                 157 chars (the login wall)  ->  1276-1387 chars

Eight of the 67 frontends that both read and write a token carry such a read-only key
(tiktok_token / tt_access_token / tk_token / tiktok_web_r87_token …).

★ The repair writes the missing keys at the sites that already store the token, and it
GUARDS each added write. The first version appended unconditionally after the closing
brace of ``if (token) { … }``; on a failed login that stores ``undefined``, which
localStorage stringifies, so ``getToken()`` returns the truthy string "undefined" and
the app believes it holds a session. That regression came out of running the repair on
r54's real login page, not out of reading it.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    repair_token_key_mismatch_1108 as repair)

_LOGIN = """import { setToken } from '../services/api';
export default function LoginPage() {
  const onSubmit = async () => {
    const token = await login();
    if (token) { localStorage.setItem('access_token', token); }
  };
}
"""
_API = """const TOKEN_KEY = 'tiktok_token';
export function getToken() { return localStorage.getItem(TOKEN_KEY); }
"""


def _fe(tmp_path, login=_LOGIN, api=_API):
    src = tmp_path / "src"
    (src / "pages").mkdir(parents=True)
    (src / "services").mkdir(parents=True)
    (src / "pages" / "LoginPage.jsx").write_text(login)
    (src / "services" / "api.js").write_text(api)
    return tmp_path


def _login_src(tmp_path):
    return (tmp_path / "src" / "pages" / "LoginPage.jsx").read_text()


def test_the_key_the_app_reads_is_now_written(tmp_path):
    fe = _fe(tmp_path)
    assert repair(fe)["added"], "nothing repaired"
    assert "setItem('tiktok_token'" in _login_src(tmp_path)


def test_the_added_write_is_guarded(tmp_path):
    """★ The regression the first version shipped: an unguarded append stores
    `undefined`, localStorage stringifies it, and getToken() returns "undefined" —
    truthy, so the app believes it is authenticated."""
    fe = _fe(tmp_path)
    repair(fe)
    line = next(l for l in _login_src(tmp_path).splitlines() if "tiktok_token" in l)
    assert "if (token) localStorage.setItem('tiktok_token'" in line, line


def test_the_original_write_is_untouched(tmp_path):
    """Additive only — no key stops being written."""
    fe = _fe(tmp_path)
    repair(fe)
    assert "setItem('access_token', token)" in _login_src(tmp_path)


def test_it_writes_the_value_that_site_already_writes(tmp_path):
    """Not a literal: whatever expression the existing setItem stores."""
    fe = _fe(tmp_path, login=_LOGIN.replace("token)", "resp.access_token)")
                                  .replace("if (token) {", "if (resp) {"))
    repair(fe)
    line = next(l for l in _login_src(tmp_path).splitlines() if "tiktok_token" in l)
    assert "resp.access_token" in line, line


def test_a_matching_key_is_left_alone(tmp_path):
    """Non-vacuity: an app that reads what it writes must not be edited."""
    fe = _fe(tmp_path, api="export function getToken(){return localStorage.getItem('access_token');}\n")
    assert repair(fe)["added"] == []
    assert _login_src(tmp_path) == _LOGIN


def test_a_non_token_key_is_not_chased(tmp_path):
    """`theme` is read and never written here; only auth-ish keys are the subject."""
    fe = _fe(tmp_path, api="export const t = () => localStorage.getItem('theme');\n"
                           "export const g = () => localStorage.getItem('access_token');\n")
    assert repair(fe)["added"] == []


def test_it_is_idempotent(tmp_path):
    fe = _fe(tmp_path)
    repair(fe)
    once = _login_src(tmp_path)
    assert repair(fe)["added"] == []
    assert _login_src(tmp_path) == once


def test_the_result_still_parses(tmp_path):
    node = "/home/haibotong/.nvm/versions/node/v20.20.0/bin/node"
    if not Path(node).exists():
        pytest.skip("node not installed")
    fe = _fe(tmp_path)
    repair(fe)
    # strip JSX-free file for `node --check`: api.js is plain JS and is edited too
    r = subprocess.run([node, "--check", str(tmp_path / "src" / "services" / "api.js")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_a_frontend_with_no_token_at_all_is_untouched(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "App.jsx").write_text("export default function App(){return null;}\n")
    assert repair(tmp_path)["added"] == []


def test_it_is_wired_into_the_heal_pipeline():
    """★ An unwired repair is inert — the failure shape this repo calls #201."""
    hp = (LLM / "multi_agent" / "runtime" / "heal_pipeline.py").read_text()
    assert "repair_token_key_mismatch_1108" in hp
    i = hp.index("repair_frontend_api_exports(fe)")
    j = hp.index("repair_token_key_mismatch_1108")
    assert j > i, "must run after the api.js repairs so it sees the final key"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_a_trailing_comment_does_not_swallow_the_repair(tmp_path):
    """The copied line may end in `// ...`.

    Appending the extra write to that same line puts it inside the comment: the
    repair reports success and writes code the parser never sees. 1 of the 286
    token setItem lines in the corpus carries exactly this shape
    (tiktok-web-r56 api.js: ``setItem('token', t); // legacy key kept ...``).
    """
    from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
        repair_token_key_mismatch_1108,
    )

    src = tmp_path / "src"
    (src / "services").mkdir(parents=True)
    (src / "pages").mkdir()
    (src / "pages" / "Login.jsx").write_text(
        "export function onLogin(token) {\n"
        "  localStorage.setItem('access_token', token); // legacy key kept for older paths\n"
        "}\n",
        encoding="utf-8",
    )
    (src / "services" / "api.js").write_text(
        "const TOKEN_KEY = 'tiktok_token';\n"
        "export const getToken = () => localStorage.getItem(TOKEN_KEY);\n",
        encoding="utf-8",
    )

    out = repair_token_key_mismatch_1108(tmp_path)
    assert out["added"], "the read-only key was not repaired at all"

    text = (src / "pages" / "Login.jsx").read_text(encoding="utf-8")
    assert "tiktok_token" in text

    # the write must NOT sit behind the `//` on the original line
    for line in text.splitlines():
        if "tiktok_token" not in line:
            continue
        before = line.split("tiktok_token")[0]
        assert "//" not in before, (
            "the appended write landed inside a line comment — inert code, "
            "reported as a successful repair: %r" % line
        )
        break
    else:  # pragma: no cover - the assert above already failed
        raise AssertionError("no line carries the repaired key")

    # and it is still guarded, so a failed login cannot store the string "undefined"
    assert "if (token) localStorage.setItem('tiktok_token', token);" in text


def test_repairing_twice_changes_nothing_the_second_time(tmp_path):
    """heal re-runs its repairs; a non-idempotent one would stack duplicates."""
    from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
        repair_token_key_mismatch_1108,
    )

    src = tmp_path / "src"
    (src / "services").mkdir(parents=True)
    (src / "pages").mkdir()
    (src / "pages" / "Login.jsx").write_text(
        "export function onLogin(token) {\n"
        "  if (token) {\n"
        "    localStorage.setItem('access_token', token);\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    (src / "services" / "api.js").write_text(
        "const TOKEN_KEY = 'tk_token';\n"
        "export const getToken = () => localStorage.getItem(TOKEN_KEY);\n",
        encoding="utf-8",
    )

    repair_token_key_mismatch_1108(tmp_path)
    once = (src / "pages" / "Login.jsx").read_text(encoding="utf-8")
    assert once.count("setItem('tk_token'") == 1

    out2 = repair_token_key_mismatch_1108(tmp_path)
    twice = (src / "pages" / "Login.jsx").read_text(encoding="utf-8")
    assert twice == once, "second repair pass rewrote the file"
    assert not out2["added"], "second pass claimed to add a key that was already there"
