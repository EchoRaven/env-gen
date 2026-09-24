"""Milestone-transition phase derivation (youtube run #15, 2026-06-20):

M1 delivered, then the M2 kickoff TIMED OUT because the fresh backend lane's phase
pulse still read VALIDATION (M1's endpoints persist in the registry across
milestones) → it was told "do not start new features" → it ignored the M2
kickoff_request as stale → no M2 backend section → kickoff timeout → hard abort.

current_run_phase must let an OPEN (un-finalized) kickoff meeting override the
registry-derived VALIDATION read, re-arming KICKOFF for every milestone.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.agents.runtime.hub_pulse import current_run_phase  # noqa: E402


def _impl_endpoints():
    # a fully-implemented business surface → registry-read would say VALIDATION
    return {"e1": {"path": "/api/videos", "status": "implemented"}}


def _hubs(endpoints=None, meeting=None):
    eps = endpoints or {}
    rh = SimpleNamespace(
        _endpoints=SimpleNamespace(value=lambda: eps),
        get_endpoints=lambda: eps,
    )
    pages = {}
    if meeting is not None:
        pages[meeting["id"]] = meeting
    wh = SimpleNamespace(
        list_tasks=lambda: [],
        stores=SimpleNamespace(pages=SimpleNamespace(value=lambda: pages)),
        # run_kickoff._read_meeting_decisions reads decisions via this supported
        # mock point (or stores.documents live) — NOT off page.metadata inline.
        get_meeting_decisions=lambda mid: (pages.get(mid) or {}).get("metadata", {}).get("decisions", []),
    )
    return SimpleNamespace(registryhub=rh, workhub=wh)


def _meeting(mid, phase, created_at=1.0):
    decisions = []
    if phase == "finalized":
        decisions = [{"section": "phase_transition", "content": {"phase": "finalized"}}]
    return {
        "id": mid, "kind": "kickoff", "created_at": created_at,
        "metadata": {"phase": "open", "decisions": decisions},
    }


class MilestoneKickoffPhaseTests(unittest.TestCase):
    def test_open_kickoff_meeting_forces_kickoff_despite_implemented_endpoints(self):
        # the M2 scenario: M1 endpoints implemented AND a fresh open kickoff meeting
        h = _hubs(endpoints=_impl_endpoints(), meeting=_meeting("page_m2", "open"))
        self.assertEqual(current_run_phase(h), "KICKOFF")

    def test_finalized_meeting_with_endpoints_is_validation(self):
        # M1 mid-validation: meeting finalized, endpoints implemented → VALIDATION
        h = _hubs(endpoints=_impl_endpoints(), meeting=_meeting("page_m1", "finalized"))
        self.assertEqual(current_run_phase(h), "VALIDATION")

    def test_most_recent_meeting_wins(self):
        # M1 finalized (older) + M2 open (newer) → KICKOFF
        pages = {
            "page_m1": _meeting("page_m1", "finalized", created_at=1.0),
            "page_m2": _meeting("page_m2", "open", created_at=2.0),
        }
        rh = SimpleNamespace(get_endpoints=lambda: _impl_endpoints(),
                             _endpoints=SimpleNamespace(value=lambda: _impl_endpoints()))
        wh = SimpleNamespace(list_tasks=lambda: [],
                             stores=SimpleNamespace(pages=SimpleNamespace(value=lambda: pages)),
                             get_meeting_decisions=lambda mid: (pages.get(mid) or {}).get("metadata", {}).get("decisions", []))
        h = SimpleNamespace(registryhub=rh, workhub=wh)
        self.assertEqual(current_run_phase(h), "KICKOFF")

    def test_no_kickoff_meeting_falls_through_to_registry_read(self):
        # no meeting store at all → helper degrades to False → VALIDATION read stands
        h = _hubs(endpoints=_impl_endpoints(), meeting=None)
        self.assertEqual(current_run_phase(h), "VALIDATION")

    def test_no_meeting_no_endpoints_is_kickoff(self):
        h = _hubs(endpoints={}, meeting=None)
        self.assertEqual(current_run_phase(h), "KICKOFF")


if __name__ == "__main__":
    unittest.main()
