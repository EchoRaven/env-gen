r"""#1203d6: the probe battery skipped every endpoint the framework had verified.

`plan_probe` decided what to ask a freshly-booted app:

    status = (endpoint.get("status") or "defined")
    if status != "defined":
        return ProbeSkip(reason="not_defined")

The intent is visible in the test that pinned it -- `tests/test_runhub_probes.py` passes
`{"status": "draft"}` -- so the branch was written to skip DRAFT endpoints. But no run
directory in this repo has ever held a `draft` status. MEASURED across every
`registryhub_endpoints.json`: **`implemented` 4968 records (94%, 169 runs), `defined` 249,
`deprecated` 83, and nothing else.** `implemented` is what the FRAMEWORK writes after auditing
that an endpoint's route exists and answers.

So the predicate was backwards in both directions at once: it skipped the 94% the framework had
verified, and it probed the ones that are merely declared and may not be built (a `defined`
endpoint with no route 404s, which `classify_probe_result` scores `fail` P1).

**What it cost.** `deliverability.functionally_validated` asked only whether any probe FAILED:

    functionally_validated = (run_within_session and ep_counts["failed"] == 0
                              and mcp_counts["failed"] == 0)

A run that enumerated 29 endpoints and probed none of them satisfies that by construction --
and the flag downgrades the dead-artifact (Cutover 19), visual and ui_flow blockers from hard
to warning. MEASURED over every `delivery_gate.jsonl`: **146 of the 532 `deliverable` verdicts
(27%) across 9 runs rest on a run whose endpoint probes were 100% skipped** -- 47 of them in
r149, 24 in r148, 14 in r145, 11 in r144, 32 in r130. In r149 and r140 every single
`not_defined` skip (256/256 and 424/424) named an `implemented` endpoint.

`passed` and `skipped` were already computed by `_probe_counts` and already written into the
gate ledger. Nothing read them (#1202wk: the fact that only reaches a log).
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.hubs.runhub.probes import (  # noqa: E402
    ProbePlan, ProbeSkip, plan_probe)
from multi_agent.runtime.deliverability import probed_something_1203d6  # noqa: E402

URL = "http://localhost:8000"


def _plan(status, method="GET", path="/api/videos/feed"):
    ep = {"method": method, "path": path, "auth_required": False}
    if status is not None:
        ep["status"] = status
    return plan_probe(ep, base_url=URL)


# ---------------------------------------------------------------- the planner

def test_an_implemented_endpoint_is_probed():
    """★ The defect, in one assertion: 94% of every endpoint record in the corpus."""
    r = _plan("implemented")
    assert isinstance(r, ProbePlan), (
        "the framework audited this endpoint and then refused to ask it anything: %r" % (r,))
    assert r.url == URL + "/api/videos/feed"


def test_a_defined_endpoint_is_still_probed():
    assert isinstance(_plan("defined"), ProbePlan)


def test_a_missing_status_still_defaults_to_probeable():
    assert isinstance(_plan(None), ProbePlan)


def test_the_status_is_read_case_insensitively():
    """RegistryHub compares `str(status).lower()` in six places; the planner must agree."""
    assert isinstance(_plan("IMPLEMENTED"), ProbePlan)


def test_a_deprecated_endpoint_is_skipped():
    r = _plan("deprecated")
    assert isinstance(r, ProbeSkip) and r.reason == "not_live", r


def test_an_unknown_status_is_still_skipped():
    """★ The original intent is preserved as an ALLOW-list: `draft` was what the branch was
    written for, and it stays skipped -- the bug was that `implemented` fell in with it."""
    r = _plan("draft")
    assert isinstance(r, ProbeSkip) and r.reason == "not_live", r


def test_destructive_and_auth_skips_are_untouched():
    """The two skips that were always right must keep their own reasons."""
    d = plan_probe({"method": "DELETE", "path": "/api/videos/1", "status": "implemented"},
                   base_url=URL)
    assert isinstance(d, ProbeSkip) and d.reason == "destructive", d
    a = plan_probe({"method": "POST", "path": "/api/videos", "status": "implemented",
                    "auth_required": True}, base_url=URL, auth_required=True)
    assert isinstance(a, ProbeSkip) and a.reason == "auth_required", a


def test_the_skip_order_puts_destructive_first_on_a_live_endpoint():
    """A live DELETE must still be reported as destructive, not probed."""
    r = _plan("implemented", method="DELETE", path="/api/videos/1")
    assert isinstance(r, ProbeSkip) and r.reason == "destructive", r


# ---------------------------------------------------------------- the flag

def test_a_run_that_skipped_everything_is_not_functionally_validated():
    """★ r149's actual numbers, from its own gate ledger."""
    assert probed_something_1203d6(
        {"total": 29, "passed": 0, "failed": 0, "skipped": 29}) is False


def test_a_run_with_real_passes_still_validates():
    """★ The invariant: 386 of the 532 deliverable verdicts had real passes and must not move."""
    assert probed_something_1203d6(
        {"total": 29, "passed": 14, "failed": 0, "skipped": 15}) is True


def test_no_endpoints_at_all_does_not_wedge_the_run():
    """Nothing to ask about is a different problem, owned by other gates."""
    assert probed_something_1203d6({"total": 0, "passed": 0, "failed": 0, "skipped": 0}) is True


def test_missing_and_non_integer_counts_do_not_raise():
    """`_probe_counts` always supplies the keys, but this predicate gates delivery and must not
    be the reason a run dies."""
    assert probed_something_1203d6({}) is True
    assert probed_something_1203d6({"total": None, "passed": None}) is True
    assert probed_something_1203d6({"total": 5, "passed": None}) is False


def test_the_flag_consults_the_helper():
    """Pin the wiring: the measurement is worthless if the call site drops it (#1202wk)."""
    import inspect
    from multi_agent.runtime import deliverability as D
    src = inspect.getsource(D)
    # ★ #923's ratchet caught the first draft ending this span on a bare `)`: a delimiter is
    # not a landmark -- it moves the moment anything above it gains a parenthesis. End on text
    # that must be there.
    i = src.index("functionally_validated = (")
    stanza = src[i:src.index('mcp_counts.get("failed", 0) == 0', i)]
    assert "probed_something_1203d6(ep_counts)" in stanza, stanza


def test_a_failed_probe_still_blocks_regardless():
    """#1203d6 only adds a requirement; the pre-existing one must survive."""
    assert probed_something_1203d6(
        {"total": 29, "passed": 1, "failed": 3, "skipped": 25}) is True, \
        "the helper answers only 'did it ask'; the failed-probe blocker is separate"
