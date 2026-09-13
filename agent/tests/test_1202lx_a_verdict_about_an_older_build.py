"""#1202lx — the visual gate passed a build that predated the fix it was scoring.

GROUND TRUTH (tiktok-web-r121 resume #3, 2026-09-13), one timeline from its own log:

    11:56:15  DELIVERY DEFERRED: browser test-user found the app UNUSABLE
              (blank_pages=['friends_suggested_creators_page', 'live_discover_page',
                            'messages_dm_empty_page'])
    11:58:25  docker build -> rc=0            <- the image every photograph below shows
    12:00:00  the frontend lane rewrites SecondaryScreenContent.jsx — the ONE shared
              component behind all three of those routes
    12:07:38  #713 3 screens captured the SAME image (md5 d226ac543c60)  <- same hash as the
              11:59 capture: the bundle had not changed
    12:07:38  Visual fidelity PASSED
    12:08:43  docker build -> rc=0            <- the fix finally enters an image
    12:09:21  #1202ex: chains are about to judge an app whose image may not be the source on
              disk — app/ has changed since the image was built

The chain executor has asked this question since #1202ex. The visual gate never did, and it
is the gate whose output is a per-screen score a reader later takes as a statement about the
delivered UI.

#1202lk cannot see it: that predicate compares SOURCE signatures, and the source WAS current
— it was the image that was not. Verified the same way the defect was found: by the file's own
mtime against the build's, not by reading the code.

Reused, not re-derived (#665/#1136: the copy drifts, and #1136 WAS that drift):
`build_currency_1202ex` already measures this and carries its own never-raises contract.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


class _Orch:
    def __init__(self, sig):
        self._sig = sig
        self.output_dir = "/nonexistent"

    def _compute_app_source_signature(self):
        return self._sig


def _gate(sig="S"):
    return vf.VisualFidelityGate(_Orch(sig))


# ------------------------------------------------------------------ the predicate

def test_a_stale_image_is_not_coverage():
    """★ r121's exact shape: source current, image two edits old."""
    g = _gate("S")
    g.last_judged_sig = "S"
    g.last_result = {"build_currency_1202lx": {
        "verdict": "changed",
        "detail": "app/ has changed since the image was built (source abc, built def)"}}
    assert g.verdict_covers_delivered_source_1202lk() is False


def test_a_current_image_with_a_matching_source_is_coverage():
    g = _gate("S")
    g.last_judged_sig = "S"
    g.last_result = {"build_currency_1202lx": {"verdict": "current", "detail": "..."}}
    assert g.verdict_covers_delivered_source_1202lk() is True


@pytest.mark.parametrize("cur", [
    {"verdict": "unknown", "detail": "no recorded build to compare"},
    {},
    None,
])
def test_an_unmeasurable_build_does_not_withdraw_coverage(cur):
    """Only a POSITIVE "changed" withdraws it. `unknown` is the pre-#1202lx state and must
    not start deferring every release on hosts where the fingerprint is unavailable."""
    g = _gate("S")
    g.last_judged_sig = "S"
    g.last_result = {"build_currency_1202lx": cur}
    assert g.verdict_covers_delivered_source_1202lk() is True


def test_a_stale_source_still_loses_coverage_regardless_of_the_build():
    """★ Non-regression: #1202lk's original reason must survive."""
    g = _gate("NEW")
    g.last_judged_sig = "OLD"
    g.last_result = {"build_currency_1202lx": {"verdict": "current"}}
    assert g.verdict_covers_delivered_source_1202lk() is False


def test_no_result_at_all_is_not_coverage():
    g = _gate("S")
    g.last_judged_sig = None
    assert g.verdict_covers_delivered_source_1202lk() is False


# ------------------------------------------------------------------ the wiring

def test_the_measurement_is_reused_not_reimplemented():
    src = inspect.getsource(vf._build_currency_1202lx)
    assert "build_currency_1202ex" in src
    assert "_app_source_fingerprint" not in src, (
        "a second copy of the fingerprint comparison is the #1136 drift")


def test_it_lands_on_the_verdict_artifact():
    src = inspect.getsource(vf)
    assert '"build_currency_1202lx": _build_currency_1202lx(project_dir)' in src, (
        "the answer must reach the artifact a reader consults, not only the log")


def test_a_stale_build_is_announced_in_the_log():
    src = inspect.getsource(vf.VisualFidelityGate.maybe_run)
    assert "#1202lx VISUAL VERDICT IS ABOUT AN OLDER BUILD" in src
    i_set = src.index("self.last_result = result")
    i_warn = src.index("#1202lx VISUAL VERDICT IS ABOUT AN OLDER BUILD")
    assert i_set < i_warn, "the warning must read the result it was just handed"


def test_the_wrapper_never_raises():
    """A diagnostic that can fail the gate it diagnoses is worse than no diagnostic."""
    out = vf._build_currency_1202lx(object())
    assert isinstance(out, dict) and out.get("verdict") in ("current", "changed", "unknown")
    assert vf._build_currency_1202lx(None).get("verdict") in ("current", "changed", "unknown")
