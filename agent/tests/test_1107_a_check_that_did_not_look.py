"""#1107: the consumer gate answers "clean" identically whether it found nothing or read nothing.

`validate_contract_alignment` hard-blocks on "Frontend calls unregistered endpoint(s)",
and it builds that list from `extract_frontend_calls`, whose regex recognises
``request(...)`` and ``fetch(...)`` only. A lane that names its helper ``apiFetch`` or
``fetchWithAuth``, or exports ``api.get(...)``, yields ZERO matches — and an empty call
set produces an empty violation list, which reads exactly like a frontend that is
correct.

Measured over the corpus: the extractor reads 727 of 949 real API calls, and for **19
frontends — SIXTEEN with a delivered milestone — it reads fewer than half the API paths
their own source spells out** (0 of 10, 1 of 8, 2 of 10 …).

instagram-run70 is the shape: 2 paths read out of 10, and BOTH of the calls that 404 at
runtime — ``GET /api/posts/{id}/comments`` and ``GET /api/users/{id}/posts`` — are among
the 8 it never saw, so the gate reported no violations at all. A first draft of this
ticket warned only when the extractor found ZERO, which run70 (finding 2) walked
straight past; reading 2 of 10 is no less blind.

★ Widening the enumeration is NOT the fix, and the attempt is instructive: this gate
HARD-BLOCKS, its own comments record a false block wedging r65's delivery, and a wider
net immediately flags React-Router page paths (`/login`) and the AS's `/api`-prefixed
mounts as "unregistered". Eleven such new flags appeared across five runs, several of
them false. Turning a silent miss into a wrongly-wedged run is a worse trade.

What the gate must not do is claim it looked. So when it reads fewer than half the API
paths the source spells out, it says so — as a warning, leaving enforcement exactly where
it was. The threshold is stable rather than tuned: the corpus is bimodal (an extractor
either reads almost every path — 5/6, 8/8, 9/11 — or almost none), and 34% and 50% select
the same 19 runs.
"""
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.delivery_gate import validate_contract_alignment  # noqa: E402
from multi_agent.delivery.contract_extract import extract_frontend_calls  # noqa: E402

_MARK = "read only"

# a helper the extractor does not recognise — the corpus shape
_INVISIBLE = """
export async function apiFetch(path, opts) {
  return (await fetch(path, opts)).json();
}
export const getVideos = () => apiFetch('/api/videos');
export const getUser = (id) => apiFetch(`/api/users/${id}`);
export const getFeed = () => apiFetch('/api/feed/for-you');
"""

# the shape it does recognise
_VISIBLE = """
export const getVideos = () => request('/api/videos');
export const getFeed = () => request('/api/feed/for-you');
"""


def _tree(tmp_path, api_js: str):
    be = tmp_path / "app" / "backend"
    fe = tmp_path / "app" / "frontend" / "src" / "services"
    be.mkdir(parents=True)
    fe.mkdir(parents=True)
    (be / "main.py").write_text("app = None\n")
    (fe / "api.js").write_text(api_js)
    return tmp_path


def _hubs(endpoints=()):
    eps = {f"GET {p}": {"method": "GET", "path": p, "status": "implemented"}
           for p in endpoints}
    return types.SimpleNamespace(
        registryhub=types.SimpleNamespace(get_endpoints=lambda: eps),
        schema_hub=types.SimpleNamespace(list_tables=lambda: {}))


def _run(tmp_path, api_js, endpoints=("/api/videos",)):
    return validate_contract_alignment(_tree(tmp_path, api_js), _hubs(endpoints))


def test_the_premise_the_extractor_really_is_blind_here():
    """★ Non-vacuity: if it ever learns `apiFetch`, this ticket is moot and the next
    reader should find that out from a failing test, not by reading the regex."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        fe = Path(td) / "src" / "services"
        fe.mkdir(parents=True)
        (fe / "api.js").write_text(_INVISIBLE)
        assert extract_frontend_calls(Path(td)) == set()


def test_it_says_so_when_it_read_nothing(tmp_path):
    out = _run(tmp_path, _INVISIBLE)
    assert any(_MARK in w for w in out.get("warnings") or []), out


_PARTIAL = """
export async function apiFetch(path, opts) { return (await fetch(path, opts)).json(); }
export const login = () => request('/api/auth/login');
export const getVideos = () => apiFetch('/api/videos');
export const getUser = (id) => apiFetch(`/api/users/${id}`);
export const getFeed = () => apiFetch('/api/feed/for-you');
export const getSounds = () => apiFetch('/api/sounds');
export const getSaves = () => apiFetch('/api/saves');
"""


def test_partial_blindness_counts_too(tmp_path):
    """★ run70's shape: it DID read something, and still missed both dead calls.
    The first draft warned only on zero and let this through."""
    out = _run(tmp_path, _PARTIAL)
    assert any(_MARK in w for w in out.get("warnings") or []), out


def test_it_is_a_warning_not_a_block(tmp_path):
    """Enforcement must be untouched: a silent miss is bad, a wrongly wedged run is
    worse, and that is what a false hard-block did to r65."""
    out = _run(tmp_path, _INVISIBLE)
    assert not any(_MARK in e for e in out.get("errors") or [])


def test_it_is_silent_when_it_did_read_the_calls(tmp_path):
    out = _run(tmp_path, _VISIBLE)
    assert not any(_MARK in w for w in out.get("warnings") or [])


def test_a_frontend_with_no_api_paths_is_not_flagged(tmp_path):
    """A static page really does call nothing — that is a pass, not a blind spot."""
    out = _run(tmp_path, "export const Hello = () => 'hi';\n")
    assert not any(_MARK in w for w in out.get("warnings") or [])


def test_one_stray_path_is_not_enough(tmp_path):
    """A single literal (a comment's example, a constant) must not raise the notice."""
    out = _run(tmp_path, "export const DOCS = '/api/docs-link';\n")
    assert not any(_MARK in w for w in out.get("warnings") or [])


def test_the_notice_names_the_cause_and_the_way_out(tmp_path):
    """#798: a notice without a next step costs a cycle."""
    w = next(w for w in _run(tmp_path, _INVISIBLE)["warnings"] if _MARK in w)
    assert "request(" in w and "fetch(" in w      # what it can see
    assert "request()" in w                        # what to route calls through


def test_the_real_violation_still_reports(tmp_path):
    """Non-regression: a call the extractor DOES see, against an endpoint nobody
    declared, must still be an error."""
    out = _run(tmp_path, _VISIBLE, endpoints=("/api/videos",))
    assert any("unregistered endpoint" in e for e in out.get("errors") or []), out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
