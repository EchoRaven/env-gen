"""#1203kn: the four squad-coverage patches, as one behaviour, across cycles.

Each has its own unit tests and none of them pinned the composition — which is where the
interesting failure would be, because they feed each other:

    #1203km  a goal the CAP dropped is recorded as never-run      -> enters the ledger
    #1203kk  a goal whose own agent timed out is recorded failed   -> stays in the ledger
    #1203kl  the ledger's open failures survive the next cap       -> reaches the plan
    #1203ki  the replay count describes the planned half only      -> the line stays honest

The risk the composition has to rule out is CHURN: #1203km must not take back a pass, or a
goal would alternate between passed and open forever. That is why it records a FIRST SIGHTING
only, and this is the test that says so across three cycles rather than in one call.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_squad import (  # noqa: E402
    FailureLedger, plan_test_user_goals as PLAN, _dropped_goals_1203go as DROPPED,
    goal_agent_finished_1203kk as FINISHED)

_EPS = [{"method": "GET", "path": "/api/a", "status": "implemented"}]
_PAGES = [{"name": "p%d" % i, "route": "/p%d" % i} for i in range(12)]
_CAP = 5


class _Run:
    """One run's worth of squad cycles against one ledger file."""

    def __init__(self, path):
        path.write_text(json.dumps({"cycle": 0, "goals": {}}), encoding="utf-8")
        self.path = path

    def cycle(self, finishes):
        L = FailureLedger(self.path)
        replay = L.open_failures()
        plan = PLAN(business_eps=_EPS, ui_pages=_PAGES, max_goals=_CAP, replay_first=replay)
        full = PLAN(business_eps=_EPS, ui_pages=_PAGES, max_goals=99, replay_first=replay)
        L.note_never_run_1203km(DROPPED(full, plan))                      # #1203km
        in_plan, carried = L.replay_split_1203ki(plan)                    # #1203ki
        agents = [{"name": g["name"], "modality": g["modality"],
                   "completed": g["name"] in finishes} for g in plan]
        by_mod = {}
        for a in agents:
            by_mod.setdefault(a["modality"], []).append(a)
        L.record_cycle([{"modality": g["modality"], "name": g["name"],
                         "passed": FINISHED(g, by_mod.get(g["modality"], [])),  # #1203kk
                         "defects": 0} for g in plan])
        return {"plan": [g["name"] for g in plan], "in_plan": sorted(in_plan),
                "carried": sorted(carried),
                "open": sorted(FailureLedger(self.path).open_failures())}


def test_a_dropped_goal_reaches_the_next_plan_1203kn(tmp_path):
    r = _Run(tmp_path / "failure_ledger.json")
    c1 = r.cycle({"page_p0", "page_p1"})
    assert "page_p4" not in c1["plan"], c1["plan"]
    assert "browser::page_p4" in c1["open"], "#1203km must record what the cap dropped"
    c2 = r.cycle(set(c1["plan"]))
    assert "page_p4" in c2["plan"], (
        "#1203kl must let it through the next cap — this is the whole chain", c2["plan"])


def test_a_timed_out_goal_is_open_even_when_a_sibling_finished_1203kn(tmp_path):
    """#1203kk's half of the composition, which the other assertions did not reach.

    Found by mutation: with #1203kk off, `page_p2` would pass because `page_p0` — the same
    `browser` modality — completed, and every other assertion here stayed green.
    """
    r = _Run(tmp_path / "failure_ledger.json")
    c1 = r.cycle({"page_p0", "page_p1"})
    assert "page_p2" in c1["plan"] and "page_p0" in c1["plan"], c1["plan"]
    assert "browser::page_p2" in c1["open"], (
        "page_p2's own agent timed out; a sibling finishing must not pass it", c1["open"])
    assert "browser::page_p0" not in c1["open"], "and the one that did finish must pass"


def test_a_pass_is_not_taken_back_when_the_goal_leaves_the_plan_1203kn(tmp_path):
    """The churn #1203km's first-sighting guard exists to prevent."""
    r = _Run(tmp_path / "failure_ledger.json")
    r.cycle({"page_p0", "page_p1"})
    c2 = r.cycle({"page_p2", "page_p3"})
    assert "page_p0" not in c2["plan"], "it was displaced by the replay set"
    assert "browser::page_p0" not in c2["open"], (
        "a goal that PASSED must not become an open failure again just because the cap "
        "dropped it later", c2["open"])


def test_the_untested_set_shrinks_as_the_rotation_works_through_it_1203kn(tmp_path):
    r = _Run(tmp_path / "failure_ledger.json")
    sizes = []
    finishes = {"page_p0", "page_p1"}
    for _ in range(3):
        out = r.cycle(finishes)
        sizes.append(len(out["carried"]))
        finishes = set(out["plan"])          # next cycle everything planned finishes
    assert sizes == sorted(sizes, reverse=True) and sizes[0] > sizes[-1], sizes


def test_the_replay_count_only_counts_the_planned_half_1203kn(tmp_path):
    """#1203ki, in the situation that produced it: more open failures than agents."""
    r = _Run(tmp_path / "failure_ledger.json")
    c1 = r.cycle({"page_p0", "page_p1"})
    c2 = r.cycle(set(c1["plan"]))
    assert len(c1["open"]) > _CAP, "the fixture must over-fill the plan"
    assert len(c2["in_plan"]) <= _CAP, c2["in_plan"]
    assert c2["carried"], "and the rest must be named, not silently counted as replayed"
    assert not (set(c2["in_plan"]) & set(c2["carried"]))


def test_the_cap_is_never_exceeded_by_any_of_it_1203kn(tmp_path):
    r = _Run(tmp_path / "failure_ledger.json")
    finishes = set()
    for _ in range(4):
        out = r.cycle(finishes)
        assert len(out["plan"]) == _CAP, out["plan"]
        finishes = set()                     # everything times out, worst case for the ledger
