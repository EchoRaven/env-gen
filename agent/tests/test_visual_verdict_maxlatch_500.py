"""#500 (netflix r68, live): _persist_verdict must persist the BEST per-screen similarity MERGED
across a milestone's captures — a transient mid-rebuild capture (env restarting → auth-bounce →
every catalog page 0.00) must NOT clobber a prior good capture.

r68 delivered but its recorded Part-A read 0.00 for 10/12 screens: the catalog pages measured
0.35–0.65 at one tick, then 0.00 at the next (during a top_nav_bar rebuild), and the 0.00 overwrote
the verdict. The app truly renders ~0.51 (delivery-time test-user: auth_ok, real data, no login
wall). Max-latch fixes the recorded metric. verdict.json is diagnostic-only, so this never changes
gate behavior; a screen that never renders keeps 0.00 (still fails).
"""
import json
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import _persist_verdict


def _screen(name, sim, **kw):
    d = {"name": name, "route": "/" + name, "similarity": sim, "passed": sim >= 0.01,
         "advisory": False, "blank": None, "dimensions": {}, "deviations": [], "fixes": [],
         "measured_deviations": [], "summary": ""}
    d.update(kw)
    return d


def _read(project_dir):
    return json.loads((Path(project_dir) / "design" / "visual_gate" / "verdict.json").read_text())


def _by_name(vj):
    return {s["name"]: s for s in vj["screens"]}


def test_transient_zero_does_not_clobber_prior_good(tmp_path):
    # capture 1: real scores
    _persist_verdict(tmp_path, passed=True, min_similarity=0.01, summary="", coverage={},
                     results=[_screen("browse_home", 0.55), _screen("my_list", 0.65)])
    # capture 2 (mid-rebuild): all 0.00
    _persist_verdict(tmp_path, passed=False, min_similarity=0.01, summary="", coverage={},
                     results=[_screen("browse_home", 0.0), _screen("my_list", 0.0)])
    m = _by_name(_read(tmp_path))
    assert m["browse_home"]["similarity"] == 0.55, m["browse_home"]
    assert m["my_list"]["similarity"] == 0.65, m["my_list"]


def test_higher_later_capture_wins(tmp_path):
    _persist_verdict(tmp_path, passed=False, min_similarity=0.01, summary="", coverage={},
                     results=[_screen("browse_home", 0.30)])
    _persist_verdict(tmp_path, passed=True, min_similarity=0.01, summary="", coverage={},
                     results=[_screen("browse_home", 0.60)])
    assert _by_name(_read(tmp_path))["browse_home"]["similarity"] == 0.60


def test_screen_absent_from_later_capture_is_carried_over(tmp_path):
    _persist_verdict(tmp_path, passed=True, min_similarity=0.01, summary="", coverage={},
                     results=[_screen("browse_home", 0.55), _screen("player", 0.65)])
    # later partial capture only has browse_home (env flaked on player)
    _persist_verdict(tmp_path, passed=False, min_similarity=0.01, summary="", coverage={},
                     results=[_screen("browse_home", 0.0)])
    m = _by_name(_read(tmp_path))
    assert m["browse_home"]["similarity"] == 0.55
    assert m["player"]["similarity"] == 0.65  # carried over


def test_never_renders_stays_zero(tmp_path):
    # a screen that never renders keeps 0.00 across captures — max-latch can't falsely pass it
    _persist_verdict(tmp_path, passed=False, min_similarity=0.01, summary="", coverage={},
                     results=[_screen("player", 0.0)])
    _persist_verdict(tmp_path, passed=False, min_similarity=0.01, summary="", coverage={},
                     results=[_screen("player", 0.0)])
    assert _by_name(_read(tmp_path))["player"]["similarity"] == 0.0


def test_detail_of_best_capture_is_kept(tmp_path):
    _persist_verdict(tmp_path, passed=True, min_similarity=0.01, summary="", coverage={},
                     results=[_screen("browse_home", 0.55, deviations=["good detail"])])
    _persist_verdict(tmp_path, passed=False, min_similarity=0.01, summary="", coverage={},
                     results=[_screen("browse_home", 0.0, deviations=["bounced to /login"])])
    # the KEPT record is the 0.55 capture, so its rich detail (not the bounce) is preserved
    assert _by_name(_read(tmp_path))["browse_home"]["deviations"] == ["good detail"]


def test_first_write_no_prior_works(tmp_path):
    _persist_verdict(tmp_path, passed=True, min_similarity=0.01, summary="s", coverage={},
                     results=[_screen("landing", 0.35)])
    vj = _read(tmp_path)
    assert _by_name(vj)["landing"]["similarity"] == 0.35


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
