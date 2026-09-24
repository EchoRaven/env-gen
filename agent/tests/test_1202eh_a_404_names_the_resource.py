r"""#1202eh: "a resource 404'd" without saying which one.

tiktok-web-r96's startup screen recorded:

    console.error: Failed to load resource: the server responded with a status of 404
    (Not Found) (on 1 screen(s): (startup))

and the URL appears nowhere in the run. Playwright's console text does not carry it; the
response event does. `browser/_manager.py` and `control_exercise.py` both listen for
responses -- the VISUAL GATE, the one capture that produces the verdict and the deviations
a lane is told to fix, listened for neither.

#935's `capture_errors` is a different thing: the Python exception from the capture
attempt (a navigation timeout), not an HTTP status.
"""
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

VF = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
      / "visual_fidelity.py").read_text(encoding="utf-8")


def _listener_segment():
    i = VF.index('page.on("response"')
    depth, j = 1, VF.index("(", i + len('page.on')) + 1
    while j < len(VF) and depth:
        depth += (VF[j] == "(") - (VF[j] == ")")
        j += 1
    return VF[i:j]


def test_the_failing_url_and_status_are_recorded():
    seg = _listener_segment()
    assert "r.url" in seg and "r.status" in seg
    assert "r.request.method" in seg


def test_only_failures_are_recorded():
    assert "r.status >= 400" in _listener_segment()


def test_a_cosmetic_image_404_does_not_spend_the_budget():
    from multi_agent.runtime.visual_fidelity import _BLANKING_TYPES_1202EH as T
    assert "image" not in T and "font" not in T
    for t in ("document", "script", "stylesheet", "xhr", "fetch"):
        assert t in T, f"{t} can blank a page and must be recorded"


def test_it_feeds_the_existing_sink_not_a_new_out_parameter():
    """So it inherits #740's grouping, the blank deviation and the per-screen record."""
    assert "_rec740(\"http\"" in _listener_segment()


def test_http_failures_cannot_crowd_out_an_uncaught_exception():
    """One shared budget would let a broken bundle's several 404s evict the JS error."""
    i = VF.index("def _rec740")
    seg = VF[i:VF.index('if console_errors is not None:', i)]
    assert "startswith(kind" in seg, "the budget is not per-kind"
    assert "_KIND_BUDGET_1202EH" in seg


def test_the_listener_is_registered_beside_the_other_two():
    """All three hang off the same page, inside the same `console_errors` guard, so a
    caller that passes no sink still registers nothing."""
    i = VF.index("if console_errors is not None:")
    seg = VF[i:VF.index("# #491 (netflix r63)", i)]
    for ev in ('page.on("pageerror"', 'page.on("console"', 'page.on("response"'):
        assert ev in seg, f"{ev} is outside the guarded block"
