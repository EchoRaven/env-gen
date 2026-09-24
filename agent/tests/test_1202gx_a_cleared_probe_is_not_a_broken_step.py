"""#1202gx — #78 clears a false leak in `kind`; #798 re-reports it by reading `ok`.

A cross-user denial probe that answers 2xx looks like a leak. #78 re-runs it with a
GUARANTEED-fresh intruder before failing anyone, and when that intruder is DENIED it writes:

    kind = "skipped"
    note = "cross-user denial re-verified with a FRESH intruder → DENIED; the original 200 was
            a stale/owner-colliding probe token, not a real cross-user leak (#78)"

It does not touch `ok`, which stays False. `_chain_broken_detail_798` builds the
"THE BROKEN STEP(S) ... fix THESE" list for the verifier with one filter —
`if st.get("ok") is True: continue` — so every step #78 just cleared is handed back as
something to go and fix.

r100, live: four chains carried such a step (PUT /api/videos/42, 46, 47, 50), each already
re-verified as DENIED, and every one appeared in the remediation the verifier was working
while `business_chain_failing` was the run's last blocker. The chains' own `broken` lists were
0, so this is misdirected attention rather than a false gate — but it is attention spent on
the one check standing between that run and delivery.

One datum, two readers, each implementing a different half of the rule — the same shape as
#1202ga, #1202fu, #1202fq and #1202gr.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.remediation_dispatcher import (  # noqa: E402
    _step_is_actionable_1202gx)

# Verbatim shapes from generated/tiktok-web-r100/shared/hubs/registryhub_verification_chains.json
_CLEARED = {"action": "framework_isolation_probe_videos", "method": "PUT",
            "path": "/api/videos/42", "status": 200, "ok": False, "kind": "skipped",
            "note": ("cross-user denial re-verified with a FRESH intruder → DENIED; the "
                     "original 200 was a stale/owner-colliding probe token, not a real "
                     "cross-user leak (#78)")}
_REAL_BREAK = {"action": "read back the video", "method": "GET", "path": "/api/videos/40",
               "status": 500, "ok": False, "kind": "broken",
               "note": "Internal Server Error"}
_STARVED = {"action": "like the video", "method": "POST", "path": "/api/videos/${videoId}/like",
            "status": None, "ok": True, "kind": "skipped", "note": "unresolved ${videoId}"}


def test_a_probe_number_78_already_cleared_is_not_reported_as_broken():
    assert _step_is_actionable_1202gx(_CLEARED) is False, (
        "the verifier is still told to fix a step the framework proved is not a defect")


def test_a_real_failure_is_still_reported():
    assert _step_is_actionable_1202gx(_REAL_BREAK) is True


def test_an_ok_step_is_still_skipped():
    assert _step_is_actionable_1202gx(_STARVED) is False


def test_a_skipped_step_without_the_reverification_is_still_reported():
    """#647 — narrow to what #78 actually cleared. A step skipped for any OTHER reason is
    still unexplained, and swallowing it would hide the starvation class #188 exists for."""
    other = {**_CLEARED, "note": "skipped because an upstream save failed"}
    assert _step_is_actionable_1202gx(other) is True, (
        "every skipped step was swallowed, not just the re-verified probes")


def test_hostile_rows_never_raise():
    for bad in (None, [], "x", 3, {}):
        assert isinstance(_step_is_actionable_1202gx(bad), bool)


def test_the_builder_uses_it():
    src = (LLM / "multi_agent" / "runtime" / "remediation_dispatcher.py").read_text(
        encoding="utf-8")
    at = src.index("def _chain_broken_detail_798")
    body = src[at:src.index("\ndef ", at + 10)]
    assert "_step_is_actionable_1202gx(" in body, (
        "the broken-step list still filters on `ok` alone:\n%s" % body[:600])
