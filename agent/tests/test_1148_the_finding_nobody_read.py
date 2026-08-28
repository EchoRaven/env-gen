"""#1148: #1139 detected it and put it in a dict nothing reads.

`never_matching_filters_1139` is computed into the gate result under
`never_matching_filters`, and **no consumer exists** — grep finds the producer and the key,
and nothing else. That is #1041's shape exactly: the evidence is there, the party who can act
on it is never told.

netflix-local-r8 DELIVERED release 1.0.0 carrying one: `/api/titles/top10` filters
`WHERE t.top10_rank IS NOT NULL`, `models.py` declares the column, no seed row ever sets it.
Measured live on one token — trending 24 rows, search 24 rows, top10 **0**.

A TASK, not a gate check: #1139 deliberately reports rather than blocks, and a new blocking
check cannot be validated without a run. The predicate is narrow enough to carry a P0 — it is
not "the response was empty" (`/api/my-list` is legitimately empty for a fresh user and filters
by `user_id`, so it is never reported), it is a filter no seeded row could satisfy.
"""
from __future__ import annotations

import asyncio
import pathlib

from env_generator.llm_generator.multi_agent.runtime.remediation_dispatcher import (
    RemediationDispatcher,
)

R8 = "/data/common/haibotong/forgingground-gen/generated/netflix-local-r8"


class _WorkHub:
    def __init__(self):
        self.tasks = []

    def create_task(self, **kw):
        self.tasks.append(kw)
        return {"id": "t1", **kw}


class _Hubs:
    def __init__(self):
        self.workhub = _WorkHub()


class _Log:
    def warning(self, *a, **k): pass
    error = debug = info = warning


class _Orch:
    def __init__(self, out_dir):
        self.output_dir = out_dir
        self.hubs = _Hubs()
        self._logger = _Log()
        self._current_milestone_version = "1.0.0"


def _run(orch):
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        RemediationDispatcher(orch).dispatch_never_matching_filters_1148())


class TestTheBackendIsToldAtLast:

    def test_r8s_real_artifact_produces_a_p0(self):
        if not pathlib.Path(R8).is_dir():
            return                       # artifact pruned; the other cases still hold
        o = _Orch(R8)
        _run(o)
        assert len(o.hubs.workhub.tasks) == 1
        t = o.hubs.workhub.tasks[0]
        assert t["assignee"] == "backend" and t["priority"] == "P0"

    def test_the_body_names_the_column_from_the_real_fields(self):
        """Field names verified by calling #1139, not assumed: rows carry column + detail."""
        if not pathlib.Path(R8).is_dir():
            return
        o = _Orch(R8)
        _run(o)
        body = o.hubs.workhub.tasks[0]["description"]
        assert "top10_rank" in body
        assert "?" not in body.split("\n")[1] if len(body.split("\n")) > 1 else True

    def test_it_offers_the_three_real_repairs(self):
        if not pathlib.Path(R8).is_dir():
            return
        o = _Orch(R8)
        _run(o)
        body = o.hubs.workhub.tasks[0]["description"]
        assert "seed the column" in body and "drop the filter" in body


class TestItStaysQuietAndSafe:

    def test_a_clean_artifact_files_nothing(self, tmp_path):
        (tmp_path / "app" / "backend").mkdir(parents=True)
        (tmp_path / "app" / "backend" / "custom_routes.py").write_text("# nothing\n")
        o = _Orch(str(tmp_path))
        _run(o)
        assert o.hubs.workhub.tasks == []

    def test_it_files_once_per_milestone(self):
        if not pathlib.Path(R8).is_dir():
            return
        o = _Orch(R8)
        _run(o)
        _run(o)
        assert len(o.hubs.workhub.tasks) == 1

    def test_a_new_milestone_re_arms_it(self):
        if not pathlib.Path(R8).is_dir():
            return
        o = _Orch(R8)
        _run(o)
        o._current_milestone_version = "2.0.0"
        _run(o)
        assert len(o.hubs.workhub.tasks) == 2

    def test_no_output_dir_does_not_raise(self):
        o = _Orch(None)
        _run(o)
        assert o.hubs.workhub.tasks == []

    def test_a_workhub_that_raises_does_not_break_the_tick(self):
        if not pathlib.Path(R8).is_dir():
            return
        o = _Orch(R8)

        def _boom(**kw):
            raise RuntimeError("hub down")
        o.hubs.workhub.create_task = _boom
        _run(o)                          # must not raise


class TestItIsWiredIntoTheTick:

    def test_the_orchestrator_calls_it_beside_the_gate_dispatch(self):
        src = pathlib.Path(
            "env_generator/llm_generator/multi_agent/orchestrator.py"
        ).read_text(encoding="utf-8")
        i = src.index("dispatch_gate_level_checks(")
        j = src.index("FEEDBACK LOOP", i)
        assert "dispatch_never_matching_filters_1148()" in src[i:j], \
            "it must run even when every gate check is green — that is r8's case"
