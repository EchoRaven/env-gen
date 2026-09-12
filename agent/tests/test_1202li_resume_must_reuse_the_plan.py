"""#1202li: a resume re-planned the milestones, so #1202bz could not recognise its own work.

`plan_milestones` is an LLM call. Re-running it on a resume produces DIFFERENT NAMES for the
same work, and #1202bz keys a completed milestone by `milestone:<idx>:<name>` deliberately --
"the key carries the milestone's identity, not just its position, so editing the milestone list
between attempts cannot make a resume skip work it never did". A re-planned name cannot match,
so the resume re-does a milestone it already delivered.

tiktok-r120's resume is the case, and it is the FIRST time #1202bz has ever fired in 310 run
logs:

    17:30:42  #1202bz milestone 1/3 (M1-core-fyp-auth-comments) already completed in an
              earlier attempt and the run moved past it — skipping

Milestone 1 kept its name and was skipped. Milestone 2 came back from the planner as
`M2-discovery-creators-engagement@1.1.0` where the first attempt had delivered
`M2-discovery-creators-live@1.1.0`, the key missed, and the run started rebuilding 1.1.0 from
scratch. Its checkpoint now holds BOTH names, one `complete` and one `planning`.

The plan was already durable and already authoritative. `milestones.json` holds it with
per-milestone status -- for r120: `M1 delivered / M2 active / M3 pending`. Reusing it is the
same move #1202ca makes for `reference_spec.json` and #1202bv for `design_system.json`, both of
which announce their reuse a few lines earlier in that very log. The milestone plan was the one
durable artefact a resume still threw away.

Replayed against r120's real hub and the checkpoint its first attempt left:
    reused plan -> skip=True, skip=True, skip=False   (M1 and M2 skipped, M3 re-entered)
    re-planned  -> skip=True, skip=False, skip=False  (M2 rebuilt from scratch)

WHY #1202bz LOOKED DEAD FOR SO LONG, measured without truncation: of 159 checkpoints, 39 carry
milestone records, 16 runs resumed, 4 had a skippable milestone -- and the intersection is ZERO.
The runs that could skip were never resumed; the runs that were resumed were single-milestone,
where the rule can never fire (it needs a LATER milestone to have a record).

WHAT IS VERIFIED: on a resume the plan comes from the hub and keeps its names; a fresh run still
plans; an explicit --milestones list still wins; a hub with one milestone or none falls through
to planning; and the reuse is announced.

WHAT IS NOT: that M2 will now pass. Reuse restores the IDENTITY that lets #1202bz skip already
delivered work; whether the remaining milestone converges is a different question.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.milestone_resume import (  # noqa: E402
    milestone_key_1202bz, should_skip_milestone_1202bz)

_ORCH = _ROOT / "env_generator/llm_generator/multi_agent/orchestrator.py"

# The phases tiktok-r120's FIRST attempt left behind.
_R120_PHASES = {
    "agent_workflow": "planning",
    "milestone:1:M1-core-fyp-auth-comments@1.0.0": "complete",
    "milestone:2:M2-discovery-creators-live@1.1.0": "complete",
    "milestone:3:M3-account-inbox-activity-settings@1.2.0": "planning",
}
_HUB_PLAN = [                       # what milestones.json still held
    {"name": "M1-core-fyp-auth-comments", "version": "1.0.0"},
    {"name": "M2-discovery-creators-live", "version": "1.1.0"},
    {"name": "M3-live-messages-activity-profile-settings", "version": "1.2.0"},
]
_REPLANNED = [                      # what the resume's planner actually produced
    {"name": "M1-core-fyp-auth-comments", "version": "1.0.0"},
    {"name": "M2-discovery-creators-engagement", "version": "1.1.0"},
    {"name": "M3-account-inbox-activity-settings", "version": "1.2.0"},
]


def _skips(plan):
    return [should_skip_milestone_1202bz(_R120_PHASES, i, m)
            for i, m in enumerate(plan, start=1)]


class TheIdentityIsWhatMatters(unittest.TestCase):

    def test_the_reused_plan_skips_both_delivered_milestones(self):
        """★ r120: M1 AND M2 were delivered; reuse lets #1202bz recognise both."""
        self.assertEqual(_skips(_HUB_PLAN), [True, True, False])

    def test_the_replanned_names_lose_milestone_2(self):
        """★ What actually happened: 1.1.0 was rebuilt from scratch."""
        self.assertEqual(_skips(_REPLANNED), [True, False, False])

    def test_the_milestone_in_flight_is_still_re_entered(self):
        """#1202bz's own rule survives the reuse — remediation lives inside the body."""
        self.assertFalse(should_skip_milestone_1202bz(_R120_PHASES, 3, _HUB_PLAN[2]))

    def test_the_key_is_name_bearing_not_positional(self):
        a = milestone_key_1202bz(2, _HUB_PLAN[1])
        b = milestone_key_1202bz(2, _REPLANNED[1])
        self.assertNotEqual(a, b, "position-only keys would skip work never done")


def _reuse_if_node():
    """The `if` that performs the reuse, from the AST.

    Not a byte window (#943): these blocks carry long comments and a window sized in bytes
    breaks the moment one grows. I wrote the first version of this file with `src[i:i+900]`
    and caught it before the ratchet did, having already been caught by it once today.
    """
    tree = ast.parse(_ORCH.read_text(encoding="utf-8"))
    best = None
    for n in ast.walk(tree):
        if not isinstance(n, ast.If):
            continue
        if "_resume" not in ast.unparse(n.test):
            continue
        if "_reused_plan_1202li" not in ast.unparse(n.body):
            continue
        # innermost such `if` — an ancestor would also contain the text
        if best is None or n.lineno > best.lineno:
            best = n
    if best is None:
        raise AssertionError("the #1202li reuse guard is gone")
    return best


class TheReuseIsWiredAndGuarded(unittest.TestCase):

    def test_it_only_reuses_on_a_resume(self):
        test = ast.unparse(_reuse_if_node().test)
        self.assertIn("_resume", test,
                      "the reuse is not gated on a resume — a fresh run must still plan")

    def test_an_explicit_milestone_list_still_wins(self):
        self.assertIn("_milestones_explicit", ast.unparse(_reuse_if_node().test))

    def test_it_requires_more_than_one_milestone_in_the_hub(self):
        """A single-milestone hub is the shape #1202bz can never skip anyway; falling through
        to the planner there keeps this narrow."""
        body = ast.unparse(_reuse_if_node())
        self.assertIn("len(_hub_ms) > 1", body)

    def test_the_planner_is_still_reachable_when_nothing_is_reused(self):
        """The consumer `if` must keep an `elif` that plans, or a fresh run has no plan."""
        tree = ast.parse(_ORCH.read_text(encoding="utf-8"))
        node = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.If)
                    and ast.unparse(n.test).strip() == "_reused_plan_1202li")
        self.assertTrue(node.orelse, "no else/elif — the planner became unreachable")
        self.assertIn("plan_milestones", ast.unparse(node.orelse))

    def test_the_reuse_is_announced(self):
        self.assertIn("#1202li Milestone plan: reusing",
                      _ORCH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
