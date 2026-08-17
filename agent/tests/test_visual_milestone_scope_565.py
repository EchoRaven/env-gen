"""#565 (netflix r111, 2026-08-07) — NON-FINAL MILESTONE advisory-judge SCOPING.

GROUND TRUTH: on an INTERMEDIATE milestone the advisory visual judge (driven from
framework_validation once api_smoke passes) scored the WHOLE reference set — every screen
across every milestone — and filed frontend remediation for pages a LATER milestone owns.
So M1 churned the frontend for ~1h on M2/M3's movies/my_list (screens M1 doesn't own yet),
because run_visual_fidelity's blocking pass/average/`failing`/remediation covered ALL
blocking screens (only the `passed` verdict was owned-scoped, via registered ui_pages).

FIX #565: VisualFidelityGate.maybe_run passes THIS milestone's OWNED routes
(`milestone_owned_routes`) to run_visual_fidelity ONLY for a non-final milestone; non-owned
blocking screens are demoted to ADVISORY (still captured/reported, but out of `passed`, the
blocking average, `failing`, and remediation_text). Final / single-milestone passes None →
the full set → BYTE-IDENTICAL to the r107-r109 path.

SURPRISE (verified while implementing): per-milestone UI routes are NOT stored
structurally anywhere — a milestone_registry record carries only prose
(description_slice / detail / acceptance) and no registered ui_page carries a milestone
tag — so `_milestone_declared_routes` EXTRACTS the owned routes from that prose (generous,
under-scoping-biased; empty on a miss → caller falls back to NO scoping).

These tests lock:
  * the route helpers (normalize / inclusive ownership / prose extraction);
  * run_visual_fidelity demotes non-owned screens: `failing`, summary, remediation, and the
    blocking average all reflect OWNED screens only;
  * milestone_owned_routes=None is BYTE-IDENTICAL to today (full set);
  * over-scoping safety: a scope that would hide ALL blocking screens is skipped (full set);
  * maybe_run computes+passes the scope ONLY for a non-final milestone (final → None).

Run from agent/:
  PYTHONPATH=. ../.venv/bin/python -m pytest tests/test_visual_milestone_scope_565.py -q
"""
import asyncio
import sys
import types
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    _norm_route_for_scope, _route_in_scope, _route_resource_token,
    _milestone_declared_routes, run_visual_fidelity, remediation_text,
    VisualFidelityGate,
)


# ── (a) route helpers ───────────────────────────────────────────────────────────────────────

def test_norm_route_for_scope():
    assert _norm_route_for_scope("/Movies/") == "/movies"          # trailing slash + case
    assert _norm_route_for_scope("/api/movies?x=1#f") == "/api/movies"  # query/fragment
    assert _norm_route_for_scope("  movies ") == "/movies"         # whitespace + leading slash
    assert _norm_route_for_scope("/title/:id") == "/title/*"       # param collapse
    assert _norm_route_for_scope("/title/{id}") == "/title/*"      # brace param collapse
    assert _norm_route_for_scope("/title/1") == "/title/*"         # numeric id collapse
    assert _norm_route_for_scope("/") == "/"
    assert _norm_route_for_scope("") == "" and _norm_route_for_scope(None) == ""


def test_route_in_scope_is_inclusive_and_safe():
    own = {"/feed", "/login"}
    assert _route_in_scope("/feed", own) is True          # exact
    assert _route_in_scope("/feed/", own) is True         # normalized exact
    assert _route_in_scope("/movies", own) is False       # not owned
    assert _route_in_scope("/", own) is False             # token-less, not in set
    assert _route_in_scope("", own) is False
    # resource-token match: /api/movies owned ⇒ the /movies page counts as owned (inclusive)
    assert _route_in_scope("/movies", {"/api/movies"}) is True
    assert _route_resource_token("/title/*") == "title"
    assert _route_resource_token("/") == ""


def test_milestone_declared_routes_extracts_from_prose():
    ms = {"description_slice": "Build GET /api/movies and the /my-list page",
          "detail": "Login lives at /login",
          "acceptance": ["the user lands on /feed"]}
    got = _milestone_declared_routes(ms)
    # method-path + bare paths + the /api-stripped mirror of /api/movies
    assert {"/api/movies", "/movies", "/my-list", "/login", "/feed"} <= got


def test_milestone_declared_routes_empty_on_miss_or_bad_input():
    assert _milestone_declared_routes({"description_slice": "prose, no paths",
                                       "detail": "", "acceptance": []}) == set()
    assert _milestone_declared_routes({}) == set()
    assert _milestone_declared_routes(None) == set()          # non-Mapping → empty (safe)


# ── (b) run_visual_fidelity integration: scoped vs full-set ──────────────────────────────────

def _project(tmp_path):
    """A minimal tmp app whose App.jsx declares 4 routes so map_reference_screens maps the
    4 reference files to /feed, /login, /movies, /my-list (all blocking)."""
    src = tmp_path / "app" / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "App.jsx").write_text(
        '<Route path="/feed"/><Route path="/login"/>'
        '<Route path="/movies"/><Route path="/my-list"/>', encoding="utf-8")
    refs = []
    for n in ("feed.png", "login.png", "movies.png", "my_list.png"):
        p = tmp_path / n
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        refs.append(str(p))
    return tmp_path, refs


# feed passes (0.90); login fails (0.50) so it must appear in failing+remediation; the
# non-owned movies/my_list score low → they DRAG the full-set average and, unscoped, appear
# in failing+remediation. Scoped, only feed+login are blocking.
_SIM = {"feed": 0.90, "login": 0.50, "movies": 0.40, "my_list": 0.35}


def _capture_factory(tmp_path):
    async def _capture(screens):
        shots = {}
        for s in screens:
            shot = tmp_path / f"shot_{s['name']}.png"
            shot.write_bytes(b"\x89PNG\r\n\x1a\n")
            shots[s["name"]] = str(shot)
        return shots
    return _capture


async def _judge(llm, screen, shot):
    return {"similarity": _SIM.get(screen["name"], 0.5), "deviations": ["x"],
            "dimensions": {}, "fixes": [], "summary": ""}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _fidelity(tmp_path, refs, owned):
    return _run(run_visual_fidelity(
        tmp_path, refs, object(), min_similarity=0.65,
        capture_fn=_capture_factory(tmp_path), judge_fn=_judge,
        milestone_owned_routes=owned))


def _summary_failing_head(summary):
    """The failing/blocking part of the summary — everything BEFORE the advisory note
    (demoted screens are still REPORTED in that note; they must be out of the failing part)."""
    return summary.split(" [advisory", 1)[0]


def test_scoped_excludes_nonowned_from_blocking_and_average(tmp_path):
    tmp_path, refs = _project(tmp_path)
    res = _fidelity(tmp_path, refs, {"/feed", "/login"})
    blocking = [r for r in res["screens"] if not r.get("advisory")]
    advisory = [r for r in res["screens"] if r.get("advisory")]
    blk_names = {r["name"] for r in blocking}
    adv_names = {r["name"] for r in advisory}
    # (a) failing part of the summary excludes the non-owned screens; they are still
    # captured/reported (advisory), just not blocking.
    assert blk_names == {"feed", "login"}, blk_names
    assert {"movies", "my_list"} <= adv_names, adv_names
    head = _summary_failing_head(res["summary"])
    assert "movies" not in head and "my_list" not in head, head
    assert res["scope_excluded_screens"] == ["movies", "my_list"], res["scope_excluded_screens"]
    # (b) the blocking average reflects OWNED screens only: (0.90 + 0.50)/2 = 0.70, NOT dragged
    # to (0.90+0.50+0.40+0.35)/4 = 0.5375 by the non-owned ones.
    assert abs(res["blocking_average"] - 0.70) < 1e-6, res["blocking_average"]
    # (a') remediation_text excludes the non-owned screens; the failing OWNED screen (login) is in.
    rem = remediation_text(res)
    assert "movies" not in rem and "my_list" not in rem
    assert "login" in rem            # owned + failing → remediated
    assert "feed" not in rem         # owned + passing → not remediated


def test_none_scope_is_byte_identical_to_full_set(tmp_path):
    tmp_path, refs = _project(tmp_path)
    full = _fidelity(tmp_path, refs, None)
    # (c) with no scope every screen is blocking, the average is dragged, and the non-owned
    # screens appear in the failing summary + remediation — today's behavior, unchanged.
    blk_names = {r["name"] for r in full["screens"] if not r.get("advisory")}
    assert blk_names == {"feed", "login", "movies", "my_list"}, blk_names
    assert full["scope_excluded_screens"] == []          # no scoping → nothing excluded
    head = _summary_failing_head(full["summary"])
    assert "movies" in head and "my_list" in head, head
    assert abs(full["blocking_average"] - 0.5375) < 1e-6, full["blocking_average"]
    rem = remediation_text(full)
    assert "movies" in rem and "my_list" in rem and "login" in rem
    # an EMPTY owned set is treated exactly like None (no scoping) — never hide everything
    empty = _fidelity(tmp_path, refs, set())
    assert {r["name"] for r in empty["screens"] if not r.get("advisory")} == blk_names
    assert empty["scope_excluded_screens"] == []


def test_over_scope_that_would_hide_all_falls_back_to_full_set(tmp_path):
    tmp_path, refs = _project(tmp_path)
    # a scope matching NONE of the four screens would demote all → vacuous gate; the safety
    # guard must skip scoping and judge the full set instead.
    res = _fidelity(tmp_path, refs, {"/nonexistent-page"})
    blk_names = {r["name"] for r in res["screens"] if not r.get("advisory")}
    assert blk_names == {"feed", "login", "movies", "my_list"}, blk_names


# ── (c) maybe_run computes+passes the scope ONLY for a non-final milestone ───────────────────
# Isolation harness (mirrors test_visual_avg_fast_release_558): exec the module under a
# synthetic package with validation_runner stubbed, then capture the kwargs maybe_run passes
# to run_visual_fidelity — no docker / real judge.

_SRC = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
        / "multi_agent" / "runtime" / "visual_fidelity.py")


def _load_vf():
    pkg = types.ModuleType("vf565_pkg")
    pkg.__path__ = []
    vr = types.ModuleType("vf565_pkg.validation_runner")
    vr._service_host_port = lambda *a, **k: None
    sys.modules["vf565_pkg"] = pkg
    sys.modules["vf565_pkg.validation_runner"] = vr
    mod = types.ModuleType("vf565_pkg.visual_fidelity")
    mod.__package__ = "vf565_pkg"
    exec(compile(_SRC.read_text(encoding="utf-8"), str(_SRC), "exec"), mod.__dict__)
    return mod


class _Log:
    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class _Hub:
    def create_task(self, **kw):
        return {"id": "t1"}


class _Hubs:
    workhub = _Hub()


class _Bus:
    async def send(self, msg):
        return None


class _Orch:
    def __init__(self, tmp, *, is_final, milestone):
        self._reference_images = [str(Path(tmp) / "ref.png")]
        Path(self._reference_images[0]).write_bytes(b"\x89PNG\r\n")
        self.output_dir = str(tmp)
        self.hubs = _Hubs()
        self.message_bus = _Bus()
        self._logger = _Log()
        self.llm = object()
        self._is_final_milestone = is_final
        self._current_milestone = milestone
        self._n = 0

    def _compute_app_source_signature(self):
        self._n += 1
        return f"sig-{self._n}"


def _drive_capture_scope(mod, orch):
    """Run one maybe_run tick capturing the milestone_owned_routes kwarg it forwards."""
    seen = {}

    async def _fake_run(*a, **k):
        seen["milestone_owned_routes"] = k.get("milestone_owned_routes")
        return {"passed": False, "summary": "t", "min_similarity": 0.65,
                "blocking_average": 0.5,
                "coverage": {"measured": 1, "judged": 1, "blocking_judged": 1,
                             "unjudged": [], "coverage": 1.0},
                "screens": [{"name": "s", "route": "/s", "similarity": 0.5,
                             "passed": False, "advisory": False}]}

    mod.run_visual_fidelity = _fake_run
    gate = mod.VisualFidelityGate(orch)
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(gate.maybe_run())
    finally:
        loop.close()
    return seen.get("milestone_owned_routes")


def test_maybe_run_scopes_only_on_non_final_milestone(tmp_path):
    mod = _load_vf()
    ms = {"description_slice": "Build the /login and /feed pages", "detail": "",
          "acceptance": []}
    # NON-final milestone → scope computed from the milestone prose and forwarded
    scope = _drive_capture_scope(mod, _Orch(tmp_path, is_final=False, milestone=ms))
    assert scope and {"/login", "/feed"} <= scope, scope
    # FINAL milestone → None (full set → byte-identical to r107-r109)
    assert _drive_capture_scope(mod, _Orch(tmp_path, is_final=True, milestone=ms)) is None
    # non-final but milestone prose has no parseable routes → None (never hide everything)
    empty_ms = {"description_slice": "prose only", "detail": "", "acceptance": []}
    assert _drive_capture_scope(mod, _Orch(tmp_path, is_final=False, milestone=empty_ms)) is None
    # non-final but no current milestone at all → None
    assert _drive_capture_scope(mod, _Orch(tmp_path, is_final=False, milestone={})) is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
