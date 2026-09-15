"""#1202nm: the post-release test-user phase does not repeat a walk this delivery pass already did.

The pre-release browser gate calls `_run_test_user_validation` (API journey, MCP check, browser
walk, visual judging, P0 dispatch) on the tree about to be cut; after `create_release` the same
function ran again as a "post-release safety net". tiktok-r125 v1.1.0 was cut at 08:44:29 and its
delivery was signalled at 08:59:30, after a second full walk that re-dispatched the same P0 to the
frontend. Across the logs, cut -> signal: median 3 min, p90 14 min, over 33 deliveries — and FIX
#139's cleared-gate stamp waits behind it.

The post-release phase still runs when the pre-release gate is disabled or did not walk this
version in this pass (the flag is reset before each walk, so an older pass cannot vouch).

`_maybe_framework_deliver` is a ~1000-line coroutine with no seam to drive in isolation, so this
pins the three ordering facts by landmark (#943: no fixed byte windows).
"""
from __future__ import annotations

import ast
from pathlib import Path

ORCH = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
        / "multi_agent" / "orchestrator.py")


def _deliver_src():
    text = ORCH.read_text(encoding="utf-8")
    tree = ast.parse(text)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_maybe_framework_deliver")
    return ast.get_source_segment(text, fn)


def test_the_flag_is_reset_before_the_pre_release_walk_and_set_only_when_it_ran():
    src = _deliver_src()
    reset = src.index("self._prerelease_walk_1202nm = None     # #1202nm")
    walk = src.index("self._run_test_user_validation,", reset)
    ran = src.index('if isinstance(_bg_report, dict) and _bg_report.get("ran"):\n'
                    '                    # #1202nm', walk)
    setflag = src.index("self._prerelease_walk_1202nm = str(", ran)
    assert reset < walk < ran < setflag


def test_the_post_release_call_is_guarded_by_this_version():
    src = _deliver_src()
    cut = src.index("ch.create_release(")
    guard = src.index('getattr(self, "_prerelease_walk_1202nm", None) == str(release_tag)', cut)
    branch = src.index("if _walked_1202nm:", guard)
    call = src.index("await _asyncio.to_thread(self._run_test_user_validation, release_tag)",
                     branch)
    else_at = src.rindex("else:", branch, call)
    assert cut < guard < branch < else_at < call


def test_the_flag_is_consumed_so_the_next_milestone_starts_clean():
    src = _deliver_src()
    guard = src.index('_walked_1202nm = getattr(self, "_prerelease_walk_1202nm", None)')
    consume = src.index("self._prerelease_walk_1202nm = None", guard)
    branch = src.index("if _walked_1202nm:", guard)
    assert guard < consume < branch
