"""FIX #115 — a missing-backend kickoff at milestone 2+ salvages with a deferred
section instead of aborting the run (instagram-core-di run-31, 2026-07-08 15:29).

run-31 had M1+M2 DELIVERED, then the M3 kickoff landed in a Gemini
MALFORMED_FUNCTION_CALL storm (142 total; the backend lane's LLM failed all-3-attempts
repeatedly for ~15 min) → kickoff timed out at 1200s, the FIX #95 retry window ALSO
burned in the storm → Missing=['backend'] → RuntimeError abort, rc=1. Two rescue
mechanisms both misfired:
  * the lane's terminal auto-backup stub (messaging.py) landed at 15:29:50 — FIVE
    SECONDS AFTER the 15:29:45 abort (it triggers on the kickoff_request ENDING,
    which on this path is the abort itself → always too late);
  * `_derive_missing_essential_sections`' backend guard requires the slice
    description to parse BOTH endpoints AND tables — a guard written before
    #96/#108 made empty tables / missing data_model LEGITIMATE (warning, not
    error) at milestone 2+ under the cumulative contract. run-31's M3 description
    had neither → `continue` → salvage returned [] → honest fallback → abort.

Fix: at milestone_index >= 2 the backend salvage no longer requires the slice to
parse; when extraction yields nothing it authors a DEFERRED backend section
(endpoints/tables empty — legitimate at M2+ per #96/#108; the cumulative contract
carries the prior milestones, reconcile prunes dangling UI calls, and the milestone
proceeds degraded instead of killing a run with delivered releases). Milestone-1
behavior is UNCHANGED — with no cumulative base, aborting stays honest.
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.kickoff_driver import KickoffDriver  # noqa: E402


class _WorkHub:
    def __init__(self):
        self.decisions = []

    def add_meeting_decision(self, meeting_id, decision=None, agent=None,
                             milestone_index=None, **kw):
        self.decisions.append({"meeting_id": meeting_id, "decision": decision,
                               "agent": agent, "milestone_index": milestone_index})


class _Orch:
    def __init__(self):
        self.hubs = types.SimpleNamespace(workhub=_WorkHub())
        import logging
        self._logger = logging.getLogger("test115")


def _handle(milestone_index, description):
    return {"meeting_id": "doc_test115", "milestone_index": milestone_index,
            "description": description, "expected_attendees": ["backend", "frontend"]}


PROSE = ("M3 social interactions and profile: users follow each other, like and "
         "repost posts, and view profiles.")   # NO '- METHOD /path' / table lines

STRUCTURED = ("Deliver:\n"
              "- POST /api/follows\n"
              "- GET /api/profiles/{id}\n"
              "- follows: id, follower_id, following_id\n")


def test_m2plus_backend_salvaged_as_deferred_when_slice_unparseable():
    orch = _Orch()
    d = KickoffDriver(orch)
    out = d._derive_missing_essential_sections(_handle(3, PROSE), ["backend"], "t")
    assert out == ["backend"]
    recs = orch.hubs.workhub.decisions
    assert len(recs) == 1
    assert recs[0]["agent"] == "backend"          # load-bearing: quorum counts by agent
    assert recs[0]["milestone_index"] == 3
    content = recs[0]["decision"]["content"]
    assert content["section"] == "backend"
    assert content.get("deferred") is True        # honest: framework did not invent APIs


def test_milestone1_backend_unparseable_still_aborts():
    orch = _Orch()
    d = KickoffDriver(orch)
    out = d._derive_missing_essential_sections(_handle(1, PROSE), ["backend"], "t")
    assert out == []
    assert orch.hubs.workhub.decisions == []      # M1: no cumulative base → honest abort


def test_structured_slice_still_fully_derived_not_deferred():
    orch = _Orch()
    d = KickoffDriver(orch)
    out = d._derive_missing_essential_sections(_handle(3, STRUCTURED), ["backend"], "t")
    assert out == ["backend"]
    content = orch.hubs.workhub.decisions[0]["decision"]["content"]
    assert content.get("endpoints")               # rich path unchanged: real derivation
    assert content.get("data_model", {}).get("tables")
    assert not content.get("deferred")
