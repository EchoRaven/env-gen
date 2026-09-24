"""PROPOSAL #26 N1+N2 — framework-decision notices (anti-thrash).

When the framework supersedes a lane's file while resolving a merge/pull conflict by
ownership, the lane is NOTIFIED via a `framework_decision` event delivered
`delivery="inbox_only"` — it lands in the lane's inbox (surfaced at its next hub_pulse)
but NEVER triggers a resident wakeup (the lever the #25 reviewer prescribed; priority
does NOT gate the wakeup). The lane learns its edit was superseded and stops re-editing
the framework-owned file → re-conflict (the run-#3 churn).

Covers:
- N1: framework_decision registered ONLY in INBOX_ONLY_SUBSCRIPTIONS (never live) for
  backend+frontend; emit_framework_decision publishes inbox_only + priority=normal.
- N2: _resolve_conflict_by_ownership populates superseded_out with framework-superseded
  paths (and ONLY those — lane-owned paths kept the lane's version); pull/merge thread it.
- render: a framework_decision in a lane's inbox surfaces its MESSAGE in the pulse,
  filtered to that lane.

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.framework_notice import (  # noqa: E402
    emit_framework_decision, build_message, FRAMEWORK_DECISION_EVENT)
from multi_agent.runtime.agent_subscriptions import (  # noqa: E402
    DEFAULT_SUBSCRIPTIONS, INBOX_ONLY_SUBSCRIPTIONS)
from multi_agent.agents.runtime.auto_commit import (  # noqa: E402
    _resolve_conflict_by_ownership)
from multi_agent.agents.runtime.hub_pulse import build_hub_pulse_prompt  # noqa: E402


# ---- N1: subscription wiring + no live subscription -------------------------------
class N1Subscriptions(unittest.TestCase):
    def test_framework_decision_only_inbox_only(self):
        for lane in ("backend", "frontend"):
            names = {e for (_h, e, _p) in INBOX_ONLY_SUBSCRIPTIONS.get(lane, [])}
            self.assertIn(FRAMEWORK_DECISION_EVENT, names,
                          f"{lane} must inbox_only-subscribe to framework_decision")

    def test_never_live_subscribed(self):
        # CRITICAL: a live subscription would reintroduce the wakeup #24 removed.
        for lane, subs in DEFAULT_SUBSCRIPTIONS.items():
            names = {e for (_h, e, _p) in subs}
            self.assertNotIn(FRAMEWORK_DECISION_EVENT, names,
                             f"{lane} must NOT live-subscribe to framework_decision")


# ---- N1: emit publishes inbox_only + normal priority + gate-admitted caller --------
class _FakeEventHub:
    def __init__(self):
        self.published = []

    def publish_event(self, source_hub, event_type, payload, recipients=None,
                      priority="normal", caller=None, **kw):
        self.published.append(dict(source_hub=source_hub, event_type=event_type,
                                   payload=payload, recipients=recipients,
                                   priority=priority, caller=caller))


class N1Emit(unittest.TestCase):
    def test_emit_shape(self):
        eh = _FakeEventHub()
        ok = emit_framework_decision(eh, lane="backend", kind="conflict_resolved",
                                     paths=["app/backend/main.py"])
        self.assertTrue(ok)
        ev = eh.published[0]
        self.assertEqual(ev["event_type"], FRAMEWORK_DECISION_EVENT)
        self.assertEqual(ev["priority"], "normal")          # never urgent
        self.assertEqual(ev["recipients"], ["backend"])
        self.assertEqual(ev["caller"], ev["source_hub"])    # gate-admitted (caller==source_hub)
        self.assertEqual(ev["payload"]["lane"], "backend")
        self.assertIn("main.py", ev["payload"]["message"])
        self.assertIn("custom_routes.py", ev["payload"]["message"])  # redirect

    def test_noop_on_empty_paths_or_no_hub(self):
        self.assertFalse(emit_framework_decision(_FakeEventHub(), lane="backend",
                                                 kind="conflict_resolved", paths=[]))
        self.assertFalse(emit_framework_decision(None, lane="backend",
                                                 kind="conflict_resolved", paths=["x"]))

    def test_message_per_kind(self):
        self.assertIn("SUPERSEDED", build_message("conflict_resolved", "backend", ["main.py"]))
        self.assertIn("REGENERATED", build_message("framework_scaffolded", "backend", ["main.py"]))


# ---- N2: resolver populates superseded_out with framework-only paths ----------------
def _git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)


def _w(repo, rel, c):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(c, encoding="utf-8")


class N2SupersededOut(unittest.TestCase):
    def _backend_conflict_repo(self):
        repo = tempfile.mkdtemp(prefix="p26_")
        _git(repo, "init", "-q"); _git(repo, "config", "user.email", "t@t"); _git(repo, "config", "user.name", "t")
        _git(repo, "checkout", "-q", "-b", "integration")
        _w(repo, "app/backend/main.py", "# BASE\n")
        _w(repo, "app/backend/custom_routes.py", "# BASE custom\n")
        _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "base")
        base = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _git(repo, "checkout", "-q", "-b", "agent/backend", base)
        _w(repo, "app/backend/main.py", "# LANE main edit\n")
        _w(repo, "app/backend/custom_routes.py", "# LANE custom logic\n")
        _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "lane")
        _git(repo, "checkout", "-q", "integration")
        _w(repo, "app/backend/main.py", "# FRAMEWORK skeleton\n")
        _w(repo, "app/backend/custom_routes.py", "# stale\n")
        _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "framework")
        # start a merge to create the conflict (integration checked out → framework=--ours)
        _git(repo, "merge", "--no-commit", "--no-ff", "agent/backend")
        return repo

    def test_only_framework_superseded_paths_collected(self):
        repo = self._backend_conflict_repo()
        superseded = []
        ok, info = _resolve_conflict_by_ownership(
            Path(repo), lane="backend", framework_side="--ours", superseded_out=superseded)
        self.assertTrue(ok, info)
        # main.py is framework-owned → framework version kept → lane edit SUPERSEDED
        self.assertEqual(superseded, ["app/backend/main.py"])
        # custom_routes.py is lane-owned → lane version kept → NOT superseded (not listed)
        self.assertNotIn("app/backend/custom_routes.py", superseded)

    def test_superseded_out_optional_backcompat(self):
        # callers that don't pass superseded_out still work (no crash)
        repo = self._backend_conflict_repo()
        ok, _ = _resolve_conflict_by_ownership(Path(repo), lane="backend", framework_side="--ours")
        self.assertTrue(ok)


# ---- render: notice message surfaces in the pulse, lane-filtered --------------------
class RenderNotice(unittest.TestCase):
    def test_notice_renders_for_target_lane(self):
        pulse = {"eventhub": {"framework_notices": ["FRAMEWORK SUPERSEDED YOUR EDIT(S): app/backend/main.py."]}}
        out = build_hub_pulse_prompt(pulse)
        self.assertIsNotNone(out)
        self.assertIn("FRAMEWORK NOTICES", out)
        self.assertIn("main.py", out)

    def test_no_notice_no_block(self):
        out = build_hub_pulse_prompt({"eventhub": {"framework_notices": []}})
        self.assertIsNone(out)


class PulseFilterByLane(unittest.TestCase):
    """_pulse_eventhub must filter framework_decision to payload.lane == agent_id."""
    def test_lane_filter(self):
        from multi_agent.agents.runtime.hub_pulse import _pulse_eventhub
        events = [
            {"id": "1", "event_type": "framework_decision", "priority": "normal",
             "payload": {"lane": "backend", "message": "BK note"}},
            {"id": "2", "event_type": "framework_decision", "priority": "normal",
             "payload": {"lane": "frontend", "message": "FE note"}},
        ]
        eh = SimpleNamespace(
            list_inbox=lambda aid, unread_only=True: events,
            get_subscriptions=lambda agent=None: [],
        )
        rep = _pulse_eventhub(SimpleNamespace(eventhub=eh), "backend")
        self.assertEqual(rep["framework_notices"], ["BK note"])  # only backend's


if __name__ == "__main__":
    unittest.main()
