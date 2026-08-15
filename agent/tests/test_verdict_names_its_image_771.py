r"""#771: the verdict gave a number with no way back to the pixels.

`verdict.json` recorded thirteen fields per screen and neither of the two that matter for
checking it: **which screenshot was scored, and against which reference.** Both are carried on
the capture record; both projections dropped them.

That cost this session its most decisive step. r150 scored nine screens 0.00 and I spent three
passes on scores, logs and stores before opening a PNG — which showed a complete Netflix clone,
and reversed the conclusion, the recommendation I had given, and the sign of the result. Finding
the right file meant matching mtimes against round timestamps, and I got it **wrong once**: the
images I first read were from the 0.75 rounds, not the 0.00 one.

A path is 60 bytes. It turns "look at the image" from an inference into a lookup.

The sweep that found it: after #767b and #768b both turned out to be fixed-key projections
dropping a new field, the class was swept properly — 39 such projections in the tree, validated
against the three known ones before the result was trusted. Most are boundary projections (an
API response, a preview) and legitimately drop fields; the hazard is a projection in a PIPELINE,
which is why this one chain got a key-set comparison rather than the whole 39 getting an audit.
"""
import json

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _persist(tmp_path, **over):
    row = {"name": "browse_home", "route": "/browse", "similarity": 0.0, "passed": False,
           "advisory": False, "blank": False, "capture_missing": False,
           "screenshot": "design/visual_gate/browse_home.png",
           "reference": "design/references/browse_home.jpg",
           "deviations": [], "dimensions": {}}
    row.update(over)
    vf._persist_verdict(tmp_path, passed=False, min_similarity=0.65, summary="t",
                        coverage=None, results=[row])
    v = json.loads((tmp_path / "design" / "visual_gate" / "verdict.json").read_text())
    return v["screens"][0]


def test_the_verdict_names_the_screenshot(tmp_path):
    assert _persist(tmp_path)["screenshot"] == "design/visual_gate/browse_home.png"


def test_the_verdict_names_the_reference(tmp_path):
    assert _persist(tmp_path)["reference"] == "design/references/browse_home.jpg"


def test_a_screen_with_no_shot_says_so_rather_than_omitting(tmp_path):
    """The no-capture case (#768) is exactly when someone will ask 'which image?' — the answer
    must be an explicit None, not a missing key that reads as 'nobody recorded it'."""
    s = _persist(tmp_path, screenshot=None, capture_missing=True)
    assert "screenshot" in s and s["screenshot"] is None


def test_the_zero_that_started_this_can_be_traced(tmp_path):
    """r150's shape end to end: a 0.00 whose image is one lookup away."""
    s = _persist(tmp_path, similarity=0.0)
    assert s["similarity"] == 0.0
    assert s["screenshot"] and s["reference"]


@pytest.mark.parametrize("field", ["name", "route", "similarity", "passed", "blank",
                                   "capture_missing", "deviations", "dimensions"])
def test_nothing_else_was_lost(field):
    import inspect
    assert f'"{field}"' in inspect.getsource(vf._persist_verdict)


def test_the_chain_carries_the_same_keys_end_to_end():
    """The guard against a fourth repeat: a field added at the capture and not here vanishes
    silently. #767's crumb and #768's flag were both lost exactly this way."""
    import inspect
    import re
    src = inspect.getsource(vf.run_visual_fidelity)
    i = src.index('results.append({"name": screen["name"], "route": screen["route"],')
    j = src.index('"summary": verdict.get("summary", "")})', i)
    produced = set(re.findall(r'"(\w+)"\s*:', src[i:j]))
    persisted = set(re.findall(r'"(\w+)"\s*:', inspect.getsource(vf._persist_verdict)))
    # `measured_deviations` is computed at the capture and re-read here; everything else the
    # judged path produces must reach disk.
    lost = produced - persisted
    assert not lost, f"produced at capture and never persisted: {sorted(lost)}"


def test_the_reason_is_recorded():
    import inspect
    src = " ".join(inspect.getsource(vf._persist_verdict).replace("#", " ").split())
    assert "no way back to the pixels" in src
    assert "I got it WRONG once" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
