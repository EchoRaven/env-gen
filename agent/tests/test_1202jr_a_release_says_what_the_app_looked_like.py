"""#1202jr: a release record did not say whether the delivered app rendered.

Measured over this corpus: 51 runs cut a release and only 3 ever recorded a passing visual
verdict — counting EVERY round, not just the last, since #500's merge makes `passed` monotonic
through `_merged_passed`. So 50 of the 51 went out through an escape (wall-clock, plateau,
attempts, #558) with the gate never satisfied, and `codehub_releases.json` said none of it.
r43's record reads `notes: "Final delivery: delivery gate fully clear."`, which is true of the
gate it names and silent about this one.

No causal claim is attached and none is needed: the release is the durable record of a
delivery, and it did not carry the one measurement that says what was delivered.

Stamped inside `create_release` rather than at its callers because there are three — the
orchestrator's two plus the tool a lane can call — and #706b records the cost of hooking one:
"#706 hooked the api_smoke-validated cut further down this file and missed this one, which is
the path r147 actually took".
"""
import sys
import pathlib
import json

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

import ast                                                             # noqa: E402
import inspect                                                         # noqa: E402

import pytest                                                          # noqa: E402

from env_generator.llm_generator.multi_agent.runtime.hubs.codehub import (  # noqa: E402
    service as SVC)


@pytest.fixture
def hub(tmp_path):
    """A real CodeHubService rooted the way a run is: <root>/shared/hubs."""
    root = tmp_path / "run"
    hub_dir = root / "shared" / "hubs"
    hub_dir.mkdir(parents=True)
    (root / "repo").mkdir()
    return SVC.CodeHub(repo_root=root / "repo", hub_dir=hub_dir), root


def _write_verdict(root, **kw):
    d = root / "design" / "visual_gate"
    d.mkdir(parents=True, exist_ok=True)
    (d / "verdict.json").write_text(json.dumps(kw), encoding="utf-8")


def test_a_release_carries_the_verdict_that_stood_when_it_was_cut(hub):
    svc, root = hub
    _write_verdict(root, passed=False, min_similarity=0.65, blocking_average_live=0.6663,
                   code_state="93f56e53",
                   screens=[{"name": "explore_grid", "similarity_live": 0.63},
                            {"name": "profile_own", "similarity_live": 0.72},
                            {"name": "login_modal", "similarity_live": 0.13,
                             "advisory": True}])
    rec = svc.create_release(tag="1.0.0", source="main", agent="orchestrator")
    assert rec.get("visual_passed") is False
    assert rec.get("visual_blocking_average_live") == 0.6663
    assert rec.get("visual_screens_below") == ["explore_grid"], (
        "only screens the gate BLOCKS on: an advisory overlay is excluded by design (#128)")
    assert rec.get("visual_code_state") == "93f56e53"


def test_a_passing_verdict_is_recorded_as_passing(hub):
    svc, root = hub
    _write_verdict(root, passed=True, min_similarity=0.65, blocking_average_live=0.81,
                   screens=[{"name": "home", "similarity_live": 0.80}])
    rec = svc.create_release(tag="1.0.0", source="main", agent="orchestrator")
    assert rec.get("visual_passed") is True and rec.get("visual_screens_below") == []


def test_a_missing_verdict_says_not_recorded_rather_than_failing(hub):
    """#1039's invariant: an empty result must never read as a measured one — in EITHER
    direction. `visual_passed: False` on a run nobody photographed would be a fabrication."""
    svc, _ = hub
    rec = svc.create_release(tag="1.0.0", source="main", agent="orchestrator")
    assert rec.get("visual_passed") is None
    assert rec.get("visual_verdict_source") == "not recorded"


def test_a_corrupt_verdict_never_breaks_the_release(hub):
    svc, root = hub
    d = root / "design" / "visual_gate"
    d.mkdir(parents=True)
    (d / "verdict.json").write_text("{not json", encoding="utf-8")
    rec = svc.create_release(tag="1.0.0", source="main", agent="orchestrator")
    assert rec.get("tag") == "1.0.0", "the release must still be cut"
    assert rec.get("visual_verdict_source") == "not recorded"


def test_the_falls_back_to_merged_when_this_round_took_no_capture(hub):
    """A screen not captured this round has `similarity_live: None` (#928); its best-ever
    score is what the gate last knew, so that is what the release should report."""
    svc, root = hub
    _write_verdict(root, passed=False, min_similarity=0.65,
                   screens=[{"name": "player", "similarity_live": None, "similarity": 0.40}])
    rec = svc.create_release(tag="1.0.0", source="main", agent="orchestrator")
    assert rec.get("visual_screens_below") == ["player"]


def test_it_is_stamped_at_the_single_writer_not_at_the_callers():
    """★ #706b's lesson: there are three release sites and hooking one leaves two silent."""
    tree = ast.parse(inspect.getsource(SVC))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "attr", None) == "_visual_state_1202jr"]
    assert len(calls) == 1, f"expected exactly one stamp site, found {len(calls)}"
    src = inspect.getsource(SVC.CodeHub.create_release)
    assert "_visual_state_1202jr()" in src, "and it must be inside create_release itself"
