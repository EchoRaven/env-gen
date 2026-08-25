r"""#1102: the framework discards 8% of every lane's custom routes and says nothing.

``main.py`` filters the lane's router before including it:

    # Keep only the custom routes that legitimately override (or add) — drop the
    # ones duplicating a standard-CRUD endpoint so the safe projected handler serves.
    _custom_router.routes = [ _r for _r in ... if _custom_route_overrides_projected(...) ]

The policy is right and has three incidents behind it (#77/#528/#566w): a lane CRUD
handler routinely runs raw SQL over columns that do not exist, 500s, and starves the
page, so the projected read must win. Nothing here changes that.

What it did not do is SAY SO. Measured by booting all 65 corpus backends in-process
and diffing each one's declared custom routes against its live route table: 105 of
1216 declared routes are missing at runtime — 7 written with Express `:id` params
(never valid in FastAPI) and **98 dropped by this filter, across 57 of the 65 runs**.
56 of those are ``DELETE /api/v1/tenants/{tenant_id}``, a control-surface path the
framework rightly owns; the rest are business routes the lane wrote and never saw run.

What a lane does with an unexplained missing handler is fight it. Fourteen runs reach
into ``sys.modules["main"]`` to patch the live app; five rebind ``app.router.routes``.
tiktok-r58 shipped a DELIVERED milestone whose ``/health``, ``/docs``, ``/openapi.json``
and ``/api/videos`` all answer 404, because its patch ran

    _app3.router.routes = _kept
    _app3.routes.clear()          # app.routes IS router.routes — this clears _kept
    _app3.routes.extend(_kept)    # …then extends the emptied list with itself

Its own sanity check caught it (``/health MISSING after patch — unexpected``) and it
shipped anyway. The ImportError branch a few lines below already learned this lesson
for its own case — "silently dropping the WHOLE router 404'd every custom-only
endpoint … invisible for hours" — and the same reasoning applies to the filter.

★ The first version of this notice used ``log.info`` and was invisible: uvicorn leaves
the root logger at WARNING, so an info() on a non-uvicorn logger is dropped on the
floor. Booting a rendered app produced no line at all. A notice nobody sees is the
silence this fix exists to end, so the level is asserted below.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    render_skeleton_main, write_backend_skeleton)
from multi_agent.runtime.oauth_scaffold import write_oauth_as  # noqa: E402

_TABLES = {"videos": {"schema": {"columns": [
    {"name": "id", "type": "integer", "primary_key": True},
    {"name": "title", "type": "text"}]}}}
_EPS = [{"method": "GET", "path": "/api/videos"},
        {"method": "GET", "path": "/api/videos/{id}"},
        {"method": "POST", "path": "/api/videos/{id}/publish"}]


def _boot(tmp_path, custom_src):
    """Render the backend, drop in a custom_routes.py, import main — return stderr.

    A subprocess, not an in-process import: main.py creates an engine and tables and
    installs middleware, and doing that inside the suite would leak into every later
    test in the session (see test_temporal_alias_columns' note on exactly that)."""
    write_backend_skeleton(tmp_path, _EPS, _TABLES)
    write_oauth_as(tmp_path)
    be = tmp_path / "app" / "backend"
    (be / "custom_routes.py").write_text(custom_src)
    keys = tmp_path / "k"
    keys.mkdir(exist_ok=True)
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{tmp_path}/t.db",
               JWT_SECRET="x", JWT_DATA_DIR=str(keys))
    r = subprocess.run(
        [sys.executable, "-c", "import sys;sys.path.insert(0,'.');import main"],
        cwd=str(be), env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-1500:]
    return r.stderr


_DROPPED = ('from fastapi import APIRouter\nrouter = APIRouter()\n\n'
            '@router.get("/api/videos")\ndef lane_list():\n    return {"items": []}\n')
_KEPT = ('from fastapi import APIRouter\nrouter = APIRouter()\n\n'
         '@router.post("/api/videos/{id}/publish")\ndef lane_publish(id: int):\n'
         '    return {"item": {"id": id}}\n')


def test_a_dropped_route_is_named(tmp_path):
    err = _boot(tmp_path, _DROPPED)
    assert "NOT registered" in err
    assert "GET /api/videos" in err


def test_the_notice_is_emitted_above_uvicorns_threshold(tmp_path):
    """★ The whole fix turns on this: uvicorn leaves the root logger at WARNING and
    installs no handler for other loggers, so logging's lastResort handler — itself
    WARNING-level — is what carries the record. An info() reaches nobody.

    The BEHAVIOURAL half is `test_a_dropped_route_is_named`: that test only passes
    because the record clears the default threshold. (It cannot assert the level from
    the text — lastResort writes the bare message with no level prefix, which is what
    the first version of this test got wrong.) This pins the level in the emitted
    source so it cannot drift back to info."""
    src = render_skeleton_main(_EPS, _TABLES)
    # landmark-anchored, not a byte window: #943's ratchet exists because a window
    # sized in bytes breaks the moment a comment above it grows, and this very test
    # tripped it on its first draft.
    i = src.index("_dropped_cr:")
    j = src.index("app.include_router(_custom_router)", i)
    seg = src[i:j]
    assert 'getLogger("custom_routes").warning(' in seg
    assert ".info(" not in seg


def test_a_kept_route_is_not_named(tmp_path):
    """An action segment overrides — it must not appear in the drop list."""
    err = _boot(tmp_path, _KEPT)
    assert "NOT registered" not in err


def test_nothing_dropped_says_nothing(tmp_path):
    """No noise on the happy path: a lane that only adds routes hears silence."""
    err = _boot(tmp_path, 'from fastapi import APIRouter\nrouter = APIRouter()\n\n'
                          '@router.get("/api/lane-only")\ndef only():\n    return {"items": []}\n')
    assert "NOT registered" not in err


def test_the_notice_says_not_to_patch_the_route_table(tmp_path):
    """The failure this prevents: r58 patched the table and lost /health."""
    err = _boot(tmp_path, _DROPPED)
    assert "do NOT patch" in err


def test_the_notice_says_how_to_legitimately_own_the_path(tmp_path):
    """#798: a notice that only says 'no' costs a cycle. Name the way through."""
    err = _boot(tmp_path, _DROPPED)
    assert "SHAPE" in err and "publish" in err


def test_the_drop_policy_itself_is_unchanged(tmp_path):
    """This ticket adds a log line. If it moved the policy, that is the regression."""
    src = render_skeleton_main(_EPS, _TABLES)
    assert "_custom_route_overrides_projected(" in src
    assert "app.include_router(_custom_router)" in src


def test_the_kept_routes_still_reach_the_app(tmp_path):
    """Rewriting the comprehension as a loop must not lose the kept routes."""
    src = render_skeleton_main(_EPS, _TABLES)
    i = src.index("_kept_cr, _dropped_cr = [], []")
    j = src.index("app.include_router(_custom_router)", i)
    assert "_custom_router.routes = [_t[0] for _t in _kept_cr]" in src[i:j]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
