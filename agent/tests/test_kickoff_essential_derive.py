"""Kickoff robustness: derive a MISSING ESSENTIAL lane's section from the milestone
slice (youtube run #17, 2026-06-21). M1 delivered, then the M2 kickoff stalled because
the slow Gemini frontend lane never authored its section in time → frontend "missing" →
non-deferrable → the whole run aborted. The milestone slice already lists the
endpoints/tables, so derive the missing lane's section from it (attributed to that lane),
clear quorum, and finalize instead of aborting.

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import unittest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.kickoff_driver import KickoffDriver  # noqa: E402
from multi_agent.runtime import kickoff_driver as kd  # noqa: E402
from multi_agent.runtime.kickoff.run_kickoff import (  # noqa: E402
    derive_frontend_pages_from_endpoints)

# a slice in the structured spec shape FIX #42 extracts from
_SLICE = (
    "M2 adds channels + engagement.\n"
    "- GET /api/channels\n"
    "- POST /api/channels\n"
    "- GET /api/videos\n"
    "- channels: id, owner_id, name, handle\n"
)
_HANDLE = {"meeting_id": "page_x", "milestone_index": 2,
           "expected_attendees": ["backend", "frontend", "verifier"],
           "description": _SLICE}


class _Orch:
    def __init__(self):
        self.decisions = []  # (decision, agent)
        wh = SimpleNamespace(add_meeting_decision=self._add)
        self.hubs = SimpleNamespace(workhub=wh)
        self._logger = SimpleNamespace(warning=lambda *a, **k: None, info=lambda *a, **k: None)

    def _add(self, meeting_id, decision=None, agent="", milestone_index=None):
        self.decisions.append((decision, agent))
        return {"ok": True}

    def _author_kickoff_docs(self, synth):
        pass


def _driver(orch):
    with mock.patch.object(kd.KickoffDriver, "__init__", lambda self, o: setattr(self, "_orch", o)):
        return KickoffDriver(orch)


class DeriveFrontendPagesTests(unittest.TestCase):
    def test_login_always_present(self):
        pages = derive_frontend_pages_from_endpoints([])
        self.assertEqual([p["route"] for p in pages], ["/login", "/signup"])

    def test_collection_get_becomes_page(self):
        pages = derive_frontend_pages_from_endpoints([{"method": "GET", "path": "/api/videos"}])
        routes = {p["route"] for p in pages}
        self.assertIn("/videos", routes)
        vp = next(p for p in pages if p["route"] == "/videos")
        self.assertEqual(vp["component"], "VideosPage")
        self.assertEqual(vp["apis_used"], ["GET /api/videos"])

    def test_param_me_post_nonapi_skipped(self):
        eps = [{"method": "GET", "path": "/api/videos/{id}"},
               {"method": "GET", "path": "/api/channels/me"},
               {"method": "POST", "path": "/api/videos"},
               {"method": "GET", "path": "/health"}]
        routes = {p["route"] for p in derive_frontend_pages_from_endpoints(eps)}
        self.assertEqual(routes, {"/login", "/signup"})  # only the auth baseline

    def test_dedup(self):
        eps = [{"method": "GET", "path": "/api/videos"}, {"method": "GET", "path": "/api/videos"}]
        pages = derive_frontend_pages_from_endpoints(eps)
        self.assertEqual(len([p for p in pages if p["route"] == "/videos"]), 1)

    def test_string_shaped_endpoints_tolerated(self):
        # a backend draft may store endpoints as "METHOD /path" strings
        pages = derive_frontend_pages_from_endpoints(["GET /api/videos", "POST /api/videos"])
        routes = {p["route"] for p in pages}
        self.assertIn("/videos", routes)

    def test_table_fallback_when_no_endpoints(self):
        # prose spec → 0 endpoints → derive one page per business table (skip infra)
        tables = [{"name": "videos"}, {"name": "channels"}, {"name": "users"}]
        pages = derive_frontend_pages_from_endpoints([], tables)
        routes = {p["route"] for p in pages}
        self.assertIn("/videos", routes)
        self.assertIn("/channels", routes)
        self.assertNotIn("/users", routes)  # infra/spine skipped

    def test_endpoints_win_over_tables(self):
        # if endpoints yield pages, the table fallback does NOT also fire
        pages = derive_frontend_pages_from_endpoints(
            [{"method": "GET", "path": "/api/videos"}], [{"name": "channels"}])
        routes = {p["route"] for p in pages}
        self.assertIn("/videos", routes)
        self.assertNotIn("/channels", routes)


class EssentialDeriveSalvageTests(unittest.TestCase):
    def test_missing_frontend_derived_from_slice_then_finalizes(self):
        orch = _Orch()
        drv = _driver(orch)
        synth_seq = [
            {"status": "awaiting", "missing": ["frontend"]},   # 1st: frontend missing
            {"status": "ready", "reconciled_added": [], "reconciled_normalized": []},  # after derive
        ]
        with mock.patch("multi_agent.runtime.kickoff.run_kickoff.try_synthesize",
                        side_effect=synth_seq) as ts, \
             mock.patch("multi_agent.runtime.kickoff.run_kickoff.finalize_kickoff",
                        return_value={"receipt": "ok"}) as fin:
            receipt = drv._attempt_reconciled_finalize(_HANDLE, "initial_stall")
        self.assertEqual(receipt, {"receipt": "ok"})
        self.assertEqual(ts.call_count, 2)
        self.assertTrue(fin.called)
        # a frontend decision was recorded with derived ui_pages
        self.assertEqual(len(orch.decisions), 1)
        decision, agent = orch.decisions[0]
        self.assertEqual(agent, "frontend")
        self.assertEqual(decision["section"], "frontend")
        self.assertTrue(decision["content"]["ui_pages"])

    def test_missing_frontend_AND_verifier_derive_then_defer_then_finalize(self):
        orch = _Orch()
        drv = _driver(orch)
        synth_seq = [
            {"status": "awaiting", "missing": ["frontend", "verifier"]},  # 1st
            {"status": "awaiting", "missing": ["verifier"]},              # after frontend derive
            {"status": "ready", "reconciled_added": [], "reconciled_normalized": []},  # after verifier defer
        ]
        with mock.patch("multi_agent.runtime.kickoff.run_kickoff.try_synthesize",
                        side_effect=synth_seq), \
             mock.patch("multi_agent.runtime.kickoff.run_kickoff.finalize_kickoff",
                        return_value={"receipt": "ok"}):
            receipt = drv._attempt_reconciled_finalize(_HANDLE, "initial_stall")
        self.assertEqual(receipt, {"receipt": "ok"})
        agents = [a for _, a in orch.decisions]
        self.assertIn("frontend", agents)  # derived
        self.assertIn("verifier", agents)  # deferred

    def test_empty_slice_no_salvage_honest_fail(self):
        # no description → nothing derivable → must NOT manufacture a contract
        orch = _Orch()
        drv = _driver(orch)
        handle = {"meeting_id": "page_y", "milestone_index": 2,
                  "expected_attendees": ["backend", "frontend", "verifier"]}  # no description
        with mock.patch("multi_agent.runtime.kickoff.run_kickoff.try_synthesize",
                        return_value={"status": "awaiting", "missing": ["frontend"]}) as ts, \
             mock.patch("multi_agent.runtime.kickoff.run_kickoff.finalize_kickoff") as fin:
            receipt = drv._attempt_reconciled_finalize(handle, "initial_stall")
        self.assertIsNone(receipt)
        self.assertEqual(orch.decisions, [])
        self.assertEqual(ts.call_count, 1)  # no re-synthesize
        self.assertFalse(fin.called)

    def test_missing_backend_endpoints_only_slice_salvages_deferred_at_m2plus(self):
        # reviewer #4 originally: endpoints but NO table line → honest-fail, because a
        # table-less backend section re-failed roadmap validation. FIX #115 (run-31,
        # live): #96/#108 made those shapes WARNINGS at milestone 2+ (cumulative
        # contract), so that guard was stale — run-31 aborted an M1+M2-delivered run
        # on exactly this path. At M2+ the salvage now records a DEFERRED backend
        # section carrying whatever WAS derivable (the endpoints) and re-synthesizes.
        orch = _Orch()
        drv = _driver(orch)
        handle = {"meeting_id": "page_z", "milestone_index": 2,
                  "expected_attendees": ["backend", "frontend", "verifier"],
                  "description": "- GET /api/videos\n- POST /api/videos\n"}  # no table line
        with mock.patch("multi_agent.runtime.kickoff.run_kickoff.try_synthesize",
                        return_value={"status": "awaiting", "missing": ["backend"]}) as ts, \
             mock.patch("multi_agent.runtime.kickoff.run_kickoff.finalize_kickoff"):
            drv._attempt_reconciled_finalize(handle, "initial_stall")
        agents = [a for _, a in orch.decisions]
        self.assertIn("backend", agents)
        _dec = next(d for d, a in orch.decisions if a == "backend")
        self.assertTrue(_dec["content"].get("deferred"))
        self.assertTrue(_dec["content"].get("endpoints"))   # keeps what WAS derivable
        self.assertEqual(ts.call_count, 2)                  # re-synthesized after salvage

    def test_missing_backend_endpoints_only_slice_NO_salvage_at_m1(self):
        # milestone 1 keeps the original honest-fail: no cumulative base exists, so
        # a table-less backend section really would re-fail validation there.
        orch = _Orch()
        drv = _driver(orch)
        handle = {"meeting_id": "page_z1", "milestone_index": 1,
                  "expected_attendees": ["backend", "frontend", "verifier"],
                  "description": "- GET /api/videos\n- POST /api/videos\n"}  # no table line
        with mock.patch("multi_agent.runtime.kickoff.run_kickoff.try_synthesize",
                        return_value={"status": "awaiting", "missing": ["backend"]}) as ts, \
             mock.patch("multi_agent.runtime.kickoff.run_kickoff.finalize_kickoff") as fin:
            receipt = drv._attempt_reconciled_finalize(handle, "initial_stall")
        self.assertIsNone(receipt)
        self.assertEqual([a for _, a in orch.decisions], [], "M1: no table → no section")
        self.assertEqual(ts.call_count, 1)
        self.assertFalse(fin.called)

    def test_missing_backend_derived_endpoints_and_tables(self):
        orch = _Orch()
        drv = _driver(orch)
        synth_seq = [
            {"status": "awaiting", "missing": ["backend"]},
            {"status": "ready", "reconciled_added": [], "reconciled_normalized": []},
        ]
        with mock.patch("multi_agent.runtime.kickoff.run_kickoff.try_synthesize",
                        side_effect=synth_seq), \
             mock.patch("multi_agent.runtime.kickoff.run_kickoff.finalize_kickoff",
                        return_value={"receipt": "ok"}):
            drv._attempt_reconciled_finalize(_HANDLE, "initial_stall")
        decision, agent = orch.decisions[0]
        self.assertEqual(agent, "backend")
        self.assertTrue(decision["content"]["endpoints"])
        self.assertTrue(decision["content"]["data_model"]["tables"])


if __name__ == "__main__":
    unittest.main()
