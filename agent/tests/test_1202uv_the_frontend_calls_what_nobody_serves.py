r"""#1202uv: nothing looked at the calls the FRONTEND makes, so broken affordances ship.

#1202h reports routes the backend SERVES that the contract never declared. The opposite
direction -- calls the frontend MAKES that nothing serves -- had no reader at all, and it
ships a button that cannot work.

FOUND BY STARTING THE DELIVERED r135 STACK and driving it with a seeded login (the seed's
default plaintext is `password`: `pw = row.pop('password', None) or 'password'`):

    setVideoLiked -> POST /api/videos/{id}/like  -> 404 WITH a valid token
    setVideoSaved -> POST /api/videos/{id}/save  -> 404
    the contract has 25 endpoints; none is like, save, follow or share

`EngagementRail` fills the heart optimistically, the call 404s, its `catch` reverts it -- a
Like button that springs back. That is the user's standing rule ("if you build UI it must have
real function") broken in a DELIVERED milestone.

WHY NOTHING SAW IT, end to end:
  * `fyp_feed.apis_used` carries three entries and not that one -- non-empty but INCOMPLETE
  * `_page_api_declaration_drift_1202rr` only examines pages whose `apis_used` is EMPTY
  * and even unskipped it reads the PAGE's own file, while `ForYouFeedPage.jsx` makes no call
    at all and delegates to `EngagementRail`
  * `backfill_page_apis` (#579) matches endpoint NAMES and never reads source

So no path in the framework turns frontend source into "what this app tries to call".

MEASURED with this extractor over 155 runs: 29 (18%) call at least one endpoint nobody
implements, 66 in total.

★ VALIDATED IN BOTH DIRECTIONS AGAINST LIVE STACKS BEFORE BEING TRUSTED, because four earlier
attempts at this number were wrong -- 48% (truncated template literals), 69% (POST read as
GET), 79% (I uppercased the whole string, so every path stopped matching), then 29% once the
case bug was fixed. The extractor is only believable because r135 reports 6 and its `/like`
and `/save` really do 404, while r132 reports 0 and its `/like` really does answer 200.

IT REPORTS, IT NEVER BLOCKS. Whether a missing endpoint should stop a release is a separate
decision with real risk both ways -- a milestone may legitimately ship with later slices
unbuilt -- and it deserves a live run to settle. What it must not be is invisible afterwards.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.scaffolder import (  # noqa: E402
    _norm_api_path_1202uv,
    frontend_calls_without_backend_1202uv,
    record_frontend_calls_without_backend_1202uv,
)

EPS = [{"method": "GET", "path": "/api/feed/foryou"},
       {"method": "POST", "path": "/api/comments"},
       {"method": "GET", "path": "/api/videos/{id}/comments"}]


def _app(tmp_path, api_js):
    svc = tmp_path / "app" / "frontend" / "src" / "services"
    svc.mkdir(parents=True)
    (svc / "api.js").write_text(api_js, encoding="utf-8")
    return str(tmp_path)


def test_a_call_nobody_serves_is_reported(tmp_path):
    """★ r135's exact shape: a template path and a ternary method."""
    out = frontend_calls_without_backend_1202uv(_app(tmp_path, """
      export async function setVideoLiked(id, liked) {
        const d = await request(`/api/videos/${encodeURIComponent(id)}/like`,
                                { method: liked ? 'POST' : 'DELETE', body: liked ? {} : undefined });
        return d.item || d;
      }
    """), EPS)
    assert out == ["DELETE /api/videos/{}/like", "POST /api/videos/{}/like"], out


def test_a_call_the_contract_serves_is_not_reported(tmp_path):
    """★ r132's shape, the true negative that makes the true positive believable."""
    out = frontend_calls_without_backend_1202uv(_app(tmp_path, """
      export const feed = () => request(`/api/feed/foryou${qs(p)}`);
      export const add  = (b) => request('/api/comments', { method: 'POST', body: b });
      export const cs   = (v) => request(`/api/videos/${v}/comments`);
    """), EPS)
    assert out == [], out


def test_a_method_it_cannot_read_is_skipped_not_guessed(tmp_path):
    """★ Under-reporting is the design: this writes an artifact a lane may act on, so a wrong
    entry costs more than a missing one. A method held in a variable is unreadable -- and it
    must NOT fall back to GET, which is how one of my earlier counts reached 69%."""
    out = frontend_calls_without_backend_1202uv(_app(tmp_path, """
      export const go = (m) => request('/api/nowhere', { method: m, body: {} });
    """), EPS)
    assert out == [], out


def test_an_unresolvable_template_is_skipped(tmp_path):
    """A `$` left outside a complete `${...}` means the literal was cut; naming a path that
    may not exist is worse than naming none."""
    assert _norm_api_path_1202uv("/api/x$bad") is None
    assert _norm_api_path_1202uv("/api/videos/${id}/like") == "/api/videos/{}/like"
    assert _norm_api_path_1202uv("/api/feed/foryou${q}") == "/api/feed/foryou"
    assert _norm_api_path_1202uv("/api/x?limit=5") == "/api/x"


def test_no_contract_means_no_report(tmp_path):
    """★ #1202tn's rule: an empty registry is 'I cannot tell', not 'everything is missing'."""
    out = frontend_calls_without_backend_1202uv(_app(tmp_path, """
      export const go = () => request('/api/anything');
    """), [])
    assert out == [], out


def test_no_service_module_yet_is_silent(tmp_path):
    """The scaffolder runs before the frontend lane writes anything."""
    (tmp_path / "app" / "backend").mkdir(parents=True)
    assert frontend_calls_without_backend_1202uv(str(tmp_path), EPS) == []


def test_it_never_raises(tmp_path):
    """Best-effort, like every report on this path."""
    assert frontend_calls_without_backend_1202uv(None, EPS) == []
    assert frontend_calls_without_backend_1202uv(str(tmp_path), None) == []
    assert frontend_calls_without_backend_1202uv(str(tmp_path), [{"bad": object()}]) == []


def test_the_finding_reaches_an_artifact(tmp_path):
    """★ #947: a measurement that exists only in a log line is not a measurement, and a run
    log is not kept -- the same reasoning as #1202ui."""
    assert record_frontend_calls_without_backend_1202uv(
        str(tmp_path), ["POST /api/videos/{}/like"]) is True
    rows = [json.loads(x) for x in
            (tmp_path / "logs" / "frontend_calls_without_backend_1202uv.jsonl")
            .read_text().splitlines() if x.strip()]
    assert rows[0]["count"] == 1 and rows[0]["calls"] == ["POST /api/videos/{}/like"]


def test_it_never_creates_a_directory_named_none(tmp_path):
    """#1202ss/#1202ui: `str(None)` is the string 'None', and Path('None') is a real folder."""
    assert record_frontend_calls_without_backend_1202uv(None, ["x"]) is False
    assert record_frontend_calls_without_backend_1202uv(str(tmp_path), []) is False
    assert not (Path.cwd() / "None").exists()


def test_it_is_wired_where_the_sibling_report_is():
    """★ #1202's reachability rule: a detector nothing calls finds nothing."""
    src = (LLM_DIR / "multi_agent" / "runtime" / "scaffolder.py").read_text(encoding="utf-8")
    assert "record_frontend_calls_without_backend_1202uv(out_dir, _fe1202uv)" in src
    assert "frontend_calls_without_backend_1202uv(out_dir, endpoints)" in src
