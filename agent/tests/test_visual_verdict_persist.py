"""#419 (2026-08-02): the VLM judge scores 7 rich dimensions per screen (layout /
components / style / color / typography / iconography / copy) plus concrete
deviations/fixes/measured color diffs, but only the AGGREGATE similarity reached
the run log and the full detail went ONLY into the transient frontend remediation
task — so post-hoc you could not tell WHICH dimension a screen lost points on
(is browse_home 0.25 a layout, color, or chrome-copy miss?), making every fidelity
iteration a guess. FIX: _persist_verdict writes design/visual_gate/verdict.json
(latest attempt) with each screen's per-dimension detail, so the next lever fixes
the ACTUAL weak dimension. Best-effort + write-only (never changes gate behavior).
This locks the persistence + shape in.

Self-contained harness (mirrors test_visual_capture_param_route.py)."""
import json
import sys
import types
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
        / "multi_agent" / "runtime" / "visual_fidelity.py")


def _load():
    pkg = types.ModuleType("vf_pkg")
    pkg.__path__ = []
    vr = types.ModuleType("vf_pkg.validation_runner")
    vr._service_host_port = lambda *a, **k: None
    sys.modules["vf_pkg"] = pkg
    sys.modules["vf_pkg.validation_runner"] = vr
    # #898: `visual_fidelity` derives its ceilings via `stage_contract.llm_ceiling_898`, imported
    # inside the accessor. This harness hand-stubs each module the source reaches, so a new one
    # must be added here too — the same contract `validation_runner` above is satisfying.
    import env_generator.llm_generator.multi_agent.runtime.stage_contract as _sc
    sys.modules["vf_pkg.stage_contract"] = _sc
    mod = types.ModuleType("vf_pkg.visual_fidelity")
    mod.__package__ = "vf_pkg"
    exec(compile(_SRC.read_text(encoding="utf-8"), str(_SRC), "exec"), mod.__dict__)
    return mod


VF = _load()


def _results():
    return [
        {"name": "browse_home", "route": "/browse", "similarity": 0.25,
         "passed": False, "advisory": False, "empty_state": False,
         "dimensions": {"layout": {"score": 0.2, "note": "no top nav"},
                        "color": {"score": 0.6, "note": "close"},
                        "copy": {"score": 0.1, "note": "wrong nav labels"}},
         "deviations": ["missing hero billboard"], "fixes": ["add hero"],
         "measured_deviations": [{"component": "nav", "spec": "#141414", "got": "#222"}],
         "summary": "structurally off"},
        {"name": "account_menu", "route": "/account", "similarity": 0.4,
         "passed": False, "advisory": True, "empty_state": False,
         "dimensions": {"layout": {"score": 0.4}}, "deviations": [], "fixes": [],
         "measured_deviations": [], "summary": ""},
    ]


def test_writes_verdict_json_with_per_dimension_detail(tmp_path):
    VF._persist_verdict(tmp_path, passed=False, min_similarity=0.65,
                        summary="below 0.65: browse_home(0.25)",
                        coverage={"judged": 1, "measured": 2}, results=_results())
    vp = tmp_path / "design" / "visual_gate" / "verdict.json"
    assert vp.is_file(), "verdict.json must be written"
    data = json.loads(vp.read_text())
    assert data["passed"] is False
    assert data["min_similarity"] == 0.65
    assert data["coverage"]["judged"] == 1
    bh = next(s for s in data["screens"] if s["name"] == "browse_home")
    # the whole point: per-dimension detail survives to disk
    assert bh["dimensions"]["copy"]["note"] == "wrong nav labels"
    assert bh["dimensions"]["layout"]["score"] == 0.2
    assert bh["deviations"] == ["missing hero billboard"]
    assert bh["fixes"] == ["add hero"]
    assert bh["measured_deviations"][0]["spec"] == "#141414"
    # advisory screens are recorded too (with the flag) for completeness
    am = next(s for s in data["screens"] if s["name"] == "account_menu")
    assert am["advisory"] is True


def test_merges_best_per_screen_not_overwrite_500(tmp_path):
    # #500: a later capture MERGES best-per-screen instead of blindly overwriting — a transient
    # empty/low capture (env mid-rebuild) must NOT wipe a prior good measurement. Run-level fields
    # (summary/passed) still reflect the latest call; per-screen detail is max-latched.
    VF._persist_verdict(tmp_path, passed=False, min_similarity=0.65, summary="a",
                        coverage={}, results=_results())
    VF._persist_verdict(tmp_path, passed=True, min_similarity=0.65, summary="b",
                        coverage={}, results=[])
    data = json.loads((tmp_path / "design" / "visual_gate" / "verdict.json").read_text())
    assert data["summary"] == "b"                       # run-level fields reflect the latest call
    names = {s["name"] for s in data["screens"]}
    assert "browse_home" in names, "prior screen must be carried over, not wiped"
    bh = next(s for s in data["screens"] if s["name"] == "browse_home")
    assert bh["similarity"] == 0.25                     # prior capture's detail preserved (max-latch)


def test_best_effort_never_raises(tmp_path):
    # a non-serializable value in a screen must not crash the judge loop (default=str)
    bad = [{"name": "x", "dimensions": {"o": object()}}]
    VF._persist_verdict(tmp_path, passed=False, min_similarity=0.65, summary="s",
                        coverage={}, results=bad)  # must not raise
    assert (tmp_path / "design" / "visual_gate" / "verdict.json").is_file()


def test_missing_project_dir_is_silent(tmp_path):
    # unwritable/None project dir → best-effort no-op, never raises
    VF._persist_verdict(None, passed=False, min_similarity=0.65, summary="s",
                        coverage={}, results=_results())


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
