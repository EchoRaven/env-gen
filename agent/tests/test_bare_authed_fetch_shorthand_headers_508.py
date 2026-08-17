"""#508 (netflix r83, 2026-08-05) — bare_authed_fetch_blockers FALSE-BLOCKED a correct app
that attaches auth via an ES6 SHORTHAND `{ headers }`, killing delivery (main()=1, no release).

GROUND TRUTH: r83's post-loop delivery gate failed on deliverability_bare_authed_fetch, flagging
TitleDetailPage.jsx:48,52:
    const token = localStorage.getItem('access_token');
    const headers = token ? { Authorization: `Bearer ${token}` } : {};
    fetch(`/api/titles/${id}`, { headers })
    fetch(`/api/titles/${id}/episodes`, { headers })
Auth WAS attached (via the `headers` variable), but the #233 exclusion only matched
`headers: identifier` (with colon) / `headers: helper()` / `...spread()` — NOT the no-colon ES6
SHORTHAND `{ headers }`. So a CORRECT app was flagged → delivery gate failed → main()=1, release
records: 0 (same class as the r23 83-min #233 false-block abort).

FIX #508: extend the #233 exclusion to also excuse shorthand `{ headers }` (and `{ headers, … }`
/ `{ …, headers }`) — a `headers` variable passed by shorthand is exactly as opaque as
`headers: ident`. An inline LITERAL headers object without auth stays flagged (genuinely bare).

These tests lock: (1) the r83 shorthand cases are excused, (2) genuinely-bare fetches still
flagged, (3) #233 colon/helper/spread cases still excused, (4) public/non-api paths unaffected."""
import tempfile
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.frontend_audit import bare_authed_fetch_blockers


def _blockers(code: str):
    d = Path(tempfile.mkdtemp())
    (d / "Page.jsx").write_text(code, encoding="utf-8")
    return bare_authed_fetch_blockers(d) or []


# ---- the r83 case: shorthand { headers } is EXCUSED ----
def test_shorthand_headers_excused():
    code = ("const token = localStorage.getItem('access_token');\n"
            "const headers = token ? { Authorization: `Bearer ${token}` } : {};\n"
            "fetch(`/api/titles/${id}`, { headers });\n"
            "fetch(`/api/titles/${id}/episodes`, { headers });\n")
    assert _blockers(code) == []


def test_shorthand_headers_first_in_object_excused():
    assert _blockers("fetch('/api/x', { headers, method: 'POST' })") == []


def test_shorthand_headers_last_in_object_excused():
    assert _blockers("fetch('/api/x', { method: 'POST', headers })") == []


# ---- genuinely-bare fetches STILL flagged (no false negatives introduced) ----
def test_no_headers_still_flagged():
    assert len(_blockers("fetch('/api/titles', { method: 'GET' })")) == 1


def test_bare_url_only_still_flagged():
    assert len(_blockers("fetch('/api/titles')")) == 1


def test_inline_literal_headers_without_auth_still_flagged():
    # an INSPECTABLE inline headers literal lacking any auth token → genuinely bare.
    assert len(_blockers("fetch('/api/x', { headers: { 'Content-Type': 'application/json' } })")) == 1


# ---- #233 cases remain excused (no regression) ----
def test_headers_helper_call_excused():
    assert _blockers("fetch('/api/x', { headers: buildHeaders() })") == []


def test_headers_identifier_excused():
    assert _blockers("fetch('/api/x', { headers: myHeaders })") == []


def test_spread_helper_excused():
    assert _blockers("fetch('/api/x', { ...buildOpts() })") == []


def test_explicit_auth_keyword_excused():
    assert _blockers("fetch('/api/x', { headers: { Authorization: `Bearer ${t}` } })") == []


# ---- public / non-api paths unaffected ----
def test_public_auth_path_not_flagged():
    assert _blockers("fetch('/auth/login', { method: 'POST' })") == []


def test_non_api_url_not_flagged():
    assert _blockers("fetch('/static/logo.svg')") == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
