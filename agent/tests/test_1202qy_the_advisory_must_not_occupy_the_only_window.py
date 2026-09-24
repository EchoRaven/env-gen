r"""#1202qy: the chain detail's salient line is a failing STEP, not the advisory above it.

tiktok-r129, 20:24:35:

    RELEASE HELD: the post-smoke backend edit FAILS a fresh api_smoke
    (['business_chain:[build currency #1202ex] These verdicts may not be about the'])

Four chains were failing on `POST /api/videos/{id}/comments -> 404`, and the framework had
already worked out what that meant -- "PARENT EXISTS: `GET /api/videos/35` answers 200 right
now, so neither the id this step names nor the route is missing". None of it reached the log
line the lane acts on.

Two mechanisms, each right on its own. #1202ex inserts its build-currency caveat at index 0 of
`broken` so a human reading the whole list meets it first. `_salient_error` (#182) promises the
marker-matching lines and "never the misleading prefix". Between them sat `"; ".join(...)`,
which makes the whole list ONE line -- so there is exactly one line, it matches, and the
200-char clip shows whatever is at position 0. The advisory then occupies the only window there
is.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.framework_validation import _salient_error  # noqa: E402
from multi_agent.runtime.validation_runner import _business_chain_detail  # noqa: E402

CAVEAT = ("[build currency #1202ex] These verdicts may not be about the code on disk: app/ has "
          "changed since the image was built (source c8290913c506, built fc459a94ec01) -- the "
          "container may predate the handler under test; rebuild AND recreate the stack before "
          "trusting these results.")
STEP = ("[create_video_comment] POST /api/videos/35/comments -> 404 (expected [200, 201]; "
        "referenced resource not found) -- PARENT EXISTS: `GET /api/videos/35` answers 200 "
        "right now, so neither the id this step names nor the route is missing")


def _shown(broken):
    """What the orchestrator actually logs and hands the lane."""
    return _salient_error(_business_chain_detail(broken, ""), cap=200)


def test_the_r129_case_shows_the_failing_step():
    shown = _shown([CAVEAT, STEP])
    assert "/api/videos/35/comments" in shown
    assert "build currency" not in shown


def test_the_advisory_keeps_its_place_in_the_full_detail():
    """#1202ex's own intent: first in the list, for whoever reads all of it."""
    detail = _business_chain_detail([CAVEAT, STEP], "")
    assert detail.startswith("[build currency #1202ex]")


def test_each_broken_step_is_its_own_line():
    detail = _business_chain_detail([CAVEAT, STEP], "")
    assert detail.count("\n") >= 1


def test_the_advisory_alone_is_still_shown():
    """It is the only thing there -- saying nothing would be worse. (The extractor hands back
    its TAIL when no line carries an error marker, so the [#1202ex] label is trimmed and the
    substance kept; that is the pre-existing shape, not something this fix changed.)"""
    shown = _shown([CAVEAT])
    assert "image was built" in shown and "recreate the stack" in shown


def test_a_backend_traceback_is_still_attached():
    detail = _business_chain_detail([STEP], "File \"custom_routes.py\", line 12")
    assert "backend traceback:" in detail and "custom_routes.py" in detail


def test_the_last_steps_win_when_several_fail():
    """More failing steps must not push the real ones out in favour of the advisory."""
    steps = [f"[chain_{i}] POST /api/x/{i} -> 404 (referenced resource not found)"
             for i in range(6)]
    shown = _shown([CAVEAT] + steps)
    assert "build currency" not in shown
    assert "/api/x/5" in shown
