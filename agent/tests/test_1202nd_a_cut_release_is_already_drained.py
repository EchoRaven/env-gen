"""#1202nd: entering M(i) on a resume must not poll the prior milestone's drain when its release
is already cut.

`_await_prior_milestone_delivery_drained` loops on `self._project_delivered`, which on a resume is
the CURRENT milestone's restored flag (undelivered). tiktok-r125's M2 resumes found M1's v1.0.0
released and still called `_maybe_framework_deliver()` every 2s for 600s — racing the M2 stuck
count to its threshold within seconds and delaying the kickoff by ten minutes.
"""
import asyncio
import logging
import os
import sys
import types

LLM = os.path.join(os.path.dirname(__file__), "..", "env_generator", "llm_generator")
sys.path.insert(0, os.path.abspath(LLM))

from multi_agent.orchestrator import Orchestrator  # noqa: E402


class _Releases:
    def __init__(self, tags):
        self._tags = {t: {"tag": t} for t in tags}

    def value(self):
        return dict(self._tags)


def _orch(released):
    orch = Orchestrator.__new__(Orchestrator)
    orch._logger = logging.getLogger("t1202nd")
    orch.hubs = types.SimpleNamespace(codehub=types.SimpleNamespace(
        stores=types.SimpleNamespace(releases=_Releases(released))))
    orch._project_delivered = False            # the CURRENT milestone's restored flag
    lane = types.SimpleNamespace(_project_delivered_event=asyncio.Event())
    orch._agents = {"orchestrator": lane}
    orch.polls = 0

    async def _deliver():
        orch.polls += 1
    orch._maybe_framework_deliver = _deliver
    return orch


def test_a_cut_prior_release_returns_at_once_without_polling():
    orch = _orch(["1.0.0"])
    ok = asyncio.run(orch._await_prior_milestone_delivery_drained(
        2, timeout_s=5, poll_s=0.01, prior_release_tag="1.0.0"))
    assert ok is True
    assert orch.polls == 0


def test_an_uncut_prior_release_still_waits_and_polls():
    orch = _orch([])
    ok = asyncio.run(orch._await_prior_milestone_delivery_drained(
        2, timeout_s=0.05, poll_s=0.01, prior_release_tag="1.0.0"))
    assert ok is False
    assert orch.polls >= 1


def test_the_caller_passes_the_prior_milestones_version():
    import ast
    src = open(os.path.join(os.path.abspath(LLM), "multi_agent", "orchestrator.py"),
               encoding="utf-8").read()
    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", None) == "_await_prior_milestone_delivery_drained"]
    assert calls
    for c in calls:
        assert "prior_release_tag" in {k.arg for k in c.keywords}, c.lineno
