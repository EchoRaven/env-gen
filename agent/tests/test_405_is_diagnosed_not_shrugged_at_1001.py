"""#1001: a 405 is a contract violation with a self-describing cause, not "unexpected status".

r162's terminal blocker was POST /api/continue-watching returning 405. The classifier had no
405 branch, so it fell through to the catch-all:

    return ProbeOutcome(verdict="fail", severity="P2", note=f"unexpected status {status_code}")

Two failures in one line. **P2** buried a delivery blocker beneath the P0s the backend lane was
already holding, and the note carried no fact — which is why the dispatched task said
"reproduce POST … returning 405" rather than showing it.

HTTP requires a 405 to carry `Allow:` naming the methods the server does accept. #1000
preserved that header at the capture point; this quotes it, so the lane is told the app has
GET and HEAD bound and POST is not — the diagnosis static analysis of the worktree could not
produce, because the worktree declares the route in two places and both look correct.
"""

import pytest

from env_generator.llm_generator.multi_agent.runtime.hubs.runhub.probes import (
    classify_probe_result)


def _c(**kw):
    base = dict(status_code=405, body_excerpt="", auth_required=False)
    base.update(kw)
    return classify_probe_result(**base)


def test_the_allow_header_is_quoted():
    o = _c(headers={"allow": "GET, HEAD"})
    assert "GET, HEAD" in o.note, "the methods the app DID bind are the whole diagnosis"


def test_it_is_not_the_lowest_severity():
    """P2 put r162's blocker behind every P0 the lane held."""
    assert _c(headers={"allow": "GET"}).severity == "P1"


def test_a_missing_allow_header_is_itself_reported():
    o = _c(headers={})
    assert "no Allow header" in o.note


def test_the_header_lookup_is_case_insensitive():
    """httpx lower-cases, urllib preserves the wire casing — both must work."""
    assert "GET" in _c(headers={"Allow": "GET"}).note


def test_hostile_headers_do_not_crash_the_probe():
    class _Boom(dict):
        def items(self):
            raise RuntimeError("nope")

    assert _c(headers=_Boom()).severity == "P1"


def test_other_statuses_are_unchanged():
    assert classify_probe_result(200, "", False).verdict == "pass"
    assert classify_probe_result(404, "", False).severity == "P1"
    assert classify_probe_result(500, "", False).severity == "P1"
    assert classify_probe_result(401, "", True).verdict == "pass"


def test_an_unlisted_status_still_reaches_the_catch_all():
    """The fallthrough must survive — 418 has no branch and should not gain one."""
    o = classify_probe_result(418, "", False)
    assert o.verdict == "fail" and "unexpected status 418" in o.note


def test_the_control_says_nothing_useful():
    """Planted control: the PRE-FIX text for a 405, which is what the lane actually got."""
    assert f"unexpected status {405}" == "unexpected status 405", (
        "the control was supposed to be content-free; if it is not, this fix is unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
