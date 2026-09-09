r"""#1202il: a screen that photographed another screen's page still blocked the gate.

#713 detects it and says so in its own warning — "their similarity scores measure that
page, not those screens" — and #714 already stops the phantom REMEDIATION from reaching
the lane. The SCORE was left driving the blocking criterion anyway.

`_demote_duplicate_route_screens` is the right treatment and cannot reach this case: it
groups by the RESOLVED route and skips a screen that has none (`if not r: continue`),
while a missing route is exactly why the browser fell through to a common page.
Route-intent de-duplication cannot see a duplicate created by the absence of route intent.

tiktok-r108, live: `profile_own` and `fyp_feed_logged_out` share one capture md5 — the
verdict recorded it. The app serves its profile at `/@:username`, which no filename-derived
candidate matches, so `profile_own` was photographed as the logged-out feed (verified by
eye: the PNG is the feed, with a "Log in" button) and judged 0.20 against a profile
reference. Lowest score of the run, counted as blocking, describing a page the capture
never visited.
"""
from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as V


def _src():
    """The #713 duplicate-detection block."""
    src = inspect.getsource(V)
    i = src.index('_verdict.setdefault("identical_captures_713"')
    return src[i:src.index("# #714", i)]


def test_the_duplicate_group_is_demoted_to_advisory():
    seg = _src()
    assert "#1202il" in seg
    assert '_r["advisory"] = True' in seg, "the duplicates still block"


def test_one_member_stays_canonical():
    """One of them DID photograph its page; demoting all would lose a real signal."""
    seg = _src()
    assert "_canon713" in seg
    assert "_r is not _canon713" in seg


def test_it_reuses_the_same_ordering_the_route_demotion_uses():
    """`_demote_duplicate_route_screens` picks by (advisory, transient, name); a second
    ordering here would make two duplicates disagree about which one is real."""
    seg = _src()
    for key in ("advisory", "_screen_is_transient", "name"):
        assert key in seg, f"canonical choice ignores {key}"


def test_it_announces_the_demotion():
    seg = _src()
    assert "#1202il" in seg and "advisory" in seg
    assert "_LOG.warning" in seg


def test_a_failure_here_is_reported_not_swallowed():
    """#1201: this sits on the path to a delivery verdict; a silent except is how a fix
    ships dead."""
    seg = _src()
    assert "warn_once_1201" in seg


def test_the_detection_still_records_the_finding():
    """#932 carries `identical_captures_713` into the ledger; demoting must not replace
    reporting."""
    seg = _src()
    assert 'identical_captures_713' in seg


def test_the_route_based_demotion_still_skips_routeless_screens():
    """The premise. If this ever changes, #1202il is redundant and should go."""
    src = inspect.getsource(V._demote_duplicate_route_screens)
    tree = ast.parse(src.lstrip())
    assert any(isinstance(n, ast.Continue) for n in ast.walk(tree)), (
        "the route grouping no longer skips anything; re-check whether #1202il is needed")
    assert 'if not r:' in src


# --- against r108's own verdict ---------------------------------------------------------

def test_r108_recorded_the_pair_this_fix_is_about():
    p = (Path(__file__).resolve().parents[2]
         / "generated/tiktok-web-r108/design/visual_gate/verdict.json")
    if not p.is_file():
        pytest.skip("r108 corpus not on this machine")
    v = json.loads(p.read_text())
    groups = v.get("identical_captures_713") or []
    assert groups, "premise: r108 recorded a shared capture"
    names = {n for g in groups for n in (g.get("screens") or [])}
    assert "profile_own" in names and "fyp_feed_logged_out" in names, (
        f"expected the r108 pair, got {sorted(names)}")
