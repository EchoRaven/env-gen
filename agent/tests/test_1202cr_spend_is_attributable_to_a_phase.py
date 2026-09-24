"""#1202cr — every LLM dollar must name the phase that spent it.

r40 delivered on $283.86 having judged 11 visual rounds; r41 reached $297.73 having
judged ONE. Same budget, opposite outcome. `_LLM_USAGE` is a single global with no
dimension that can tell those two runs apart, so the question "where did it go?" had
no answer and every optimisation was aimed at what happened to be measurable.

These lock the three properties that make the split trustworthy: it RECONCILES with
the authoritative total, it SURVIVES concurrency (lanes are concurrent asyncio tasks),
and it REACHES run_budget.json (per #947 — a detector that only logs has no ceiling).
"""
import asyncio
import json
import logging
import time
from pathlib import Path

import pytest

from utils import llm as llm_mod
from utils.llm import (
    attribute_llm_1202cr,
    llm_usage,
    llm_usage_by_label_1202cr,
    _record_usage_1163,
)


@pytest.fixture(autouse=True)
def _fresh_counters():
    llm_mod._LLM_BY_LABEL_1202CR.clear()
    before = dict(llm_mod._LLM_USAGE)
    yield
    llm_mod._LLM_BY_LABEL_1202CR.clear()
    llm_mod._LLM_USAGE.update(before)


def test_the_split_reconciles_with_the_authoritative_total():
    """The per-phase numbers must ADD UP to the global counter.

    A breakdown that disagrees with the total is worse than no breakdown: it gets
    trusted and it is wrong. The global stays authoritative — this asserts the split
    is a partition of it, not a parallel estimate.
    """
    with attribute_llm_1202cr("frontend:action"):
        _record_usage_1163(1000, 900, 50)
    with attribute_llm_1202cr("backend:planning"):
        _record_usage_1163(2000, 100, 10)

    by = llm_usage_by_label_1202cr()
    total = llm_usage()
    assert sum(v["prompt"] for v in by.values()) == total["prompt"]
    assert sum(v["cached"] for v in by.values()) == total["cached"]
    assert sum(v["completion"] for v in by.values()) == total["completion"]
    assert sum(v["calls"] for v in by.values()) == total["calls"]


def test_an_unlabelled_call_is_counted_not_dropped():
    """Design-prep, the judge and the condenser do not route through the staged path.

    Dropping them would make the split silently understate the run. They must land
    under a name that is visibly not a phase, so the gap is legible rather than absent.
    """
    _record_usage_1163(500, 400, 5)
    by = llm_usage_by_label_1202cr()
    assert llm_mod._UNATTRIBUTED_1202CR in by
    assert by[llm_mod._UNATTRIBUTED_1202CR]["prompt"] == 500


def test_concurrent_lanes_do_not_contaminate_each_others_accounting():
    """Lanes run as concurrent asyncio tasks interleaved at every await.

    This is the property that makes ContextVar the right primitive and a module-level
    "current label" the wrong one — under a plain global, whichever lane set the label
    last would be billed for all of them.
    """
    async def lane(name, n):
        with attribute_llm_1202cr(name):
            for _ in range(n):
                await asyncio.sleep(0)          # yield: another lane runs here
                _record_usage_1163(10, 5, 1)

    async def main():
        await asyncio.gather(*[lane(f"lane{i}", 20) for i in range(6)])

    asyncio.run(main())
    by = llm_usage_by_label_1202cr()
    assert llm_mod._UNATTRIBUTED_1202CR not in by
    assert {k: v["calls"] for k, v in by.items()} == {f"lane{i}": 20 for i in range(6)}


def test_a_nested_block_restores_the_outer_phase():
    """A retry or an action round re-enters the block; exiting must not lose the outer
    label, or everything after the first nested call is misattributed."""
    with attribute_llm_1202cr("frontend:action"):
        with attribute_llm_1202cr("frontend:condense"):
            _record_usage_1163(100, 0, 1)
        _record_usage_1163(100, 0, 1)
    by = llm_usage_by_label_1202cr()
    assert by["frontend:action"]["calls"] == 1
    assert by["frontend:condense"]["calls"] == 1


def test_the_breakdown_reaches_run_budget_json(tmp_path):
    """#947: a measurement that only exists in memory has no ceiling and cannot be
    read after the run — which is exactly when the r40-vs-r41 question gets asked."""
    from env_generator.llm_generator.multi_agent.runtime.run_budget import RunBudget

    with attribute_llm_1202cr("frontend:action"):
        _record_usage_1163(900_000, 850_000, 9_000)

    RunBudget(Path(tmp_path), logging.getLogger("t")).write(
        {"max_wall_sec": 1e5, "max_ticks": 500}, time.time(), 12.0, 3, "running")

    payload = json.loads((Path(tmp_path) / "run_budget.json").read_text())
    split = payload["llm_by_phase_1202cr"]
    assert "frontend:action" in split
    assert abs(sum(v["usd"] for v in split.values()) - payload["llm"]["usd"]) < 0.01


def test_the_staged_call_labels_with_agent_and_stage():
    """The label must carry BOTH dimensions. Agent alone cannot separate 'planning
    burned the budget' from 'action did'; stage alone cannot separate the lanes."""
    src = Path("env_generator/llm_generator/multi_agent/agents/runtime/"
               "step_pipeline/tooling.py").read_text()
    body = src[src.index("async def _call_stage_llm"):src.index("async def _maybe_condense_messages_in_place")]
    assert '"%s:%s" % (getattr(self, "agent_id", "?"), stage_name)' in body
    assert "attribute_llm_1202cr" in body
