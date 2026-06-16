"""Smoke #21 root-cause reproduction — WorkHub meeting page lost under
concurrent lane writes.

Background (2026-06-03, branch ac282498):

  Smoke #21 = first run after Stage 1+5 (KickoffBootstrapGate landed +
  retired profiles cleaned up). Lanes WOKE successfully (proved by
  Frontend Step 1/20, "Reply-phase housekeeping" finish at 17:23:32 —
  Frontend went through initial + comment + reply phases).

  But kickoff TIMED OUT at 1200s. checkpoint.last_error = "Kickoff
  timed out... Missing=['backend', 'frontend', 'verifier']". The
  expected meeting `page_6363c52bb9` (from kickoff_failed event
  payload) was MISSING from workhub_pages.json — replaced by a
  probe page `page_d1c76fdbac` (title="lookup probe only",
  metadata.probe=True) that the orchestrator LLM created when it
  found the real one gone.

  workhub_pages.json _meta.version = 3 → 3 writes happened. The real
  meeting was in some intermediate version that got overwritten by
  v3. Either:
    (a) Concurrent add_meeting_decision calls race + overwrite the
        meeting away
    (b) Some Python path issued a literal pages.delete on the meeting
    (c) MapView semantics + JsonStore.update lambda lose a key on
        certain mutation patterns

  Pre-Stage 1, lanes were blocked by `ImplementationBootstrapPolicy`
  and never wrote to WorkHub concurrently → this bug was hidden.

This test fires N concurrent `add_meeting_decision` calls against the
same kickoff meeting from M "agents", then asserts:

  1. The meeting page STILL EXISTS at the original id (the symptom
     of #21 was that the id mysteriously vanished from pages).
  2. ALL N decisions are present in metadata.decisions (no LWW
     overwriting).
  3. The pages dict is not corrupted (other unrelated pages
     present in the store survive).

If the test reproduces the loss, it pins the bug + the fix.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


class ConcurrentMeetingDecisionWritesReproduce(unittest.TestCase):
    """Smoke #21 root-cause reproduction harness."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="smoke21_repro_")
        from multi_agent.runtime.hub_registry import HubRegistry
        self.reg = HubRegistry(Path(self.tmp))
        # Drop a "decoy" non-meeting page so we can verify the
        # store isn't being globally wiped.
        self.reg.workhub.create_page(
            title="unrelated",
            kind="design",
            agent="orchestrator",
        )
        # Create the kickoff meeting like start_kickoff() does.
        self.meeting = self.reg.workhub.create_meeting(
            agenda="M1 kickoff: minimal blog walking skeleton",
            attendees=["backend", "frontend", "verifier"],
            milestone_index=1,
            kind="kickoff",
            metadata={"phase": "open"},
            agent="orchestrator",
        )
        self.meeting_id = self.meeting["id"]
        self.assertIn(
            self.meeting_id,
            self.reg.workhub.stores.pages.value(),
            "meeting must exist immediately after create",
        )

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_concurrent_decisions_from_4_lanes_all_persist(self):
        """4 lanes (backend/frontend/verifier/orchestrator) each
        write 3 decisions concurrently via threads. After all
        complete, every decision must be in metadata.decisions and
        the meeting page must still exist."""
        lanes = ["backend", "frontend", "verifier", "orchestrator"]
        per_lane = 3
        barrier = threading.Barrier(len(lanes))

        def writer(lane: str):
            barrier.wait()  # maximize contention
            for i in range(per_lane):
                self.reg.workhub.add_meeting_decision(
                    meeting_id=self.meeting_id,
                    decision={
                        "section": "comment" if i == 1 else (
                            f"{lane}.proposal_v2" if i == 0 else "phase_ack"
                        ),
                        "round": 1,
                        "content": {"i": i, "from": lane},
                    },
                    agent=lane,
                    milestone_index=1,
                )

        threads = [threading.Thread(target=writer, args=(lane,)) for lane in lanes]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        for t in threads:
            self.assertFalse(
                t.is_alive(),
                "writer thread hung — likely deadlock on JsonStore lock",
            )

        # Assertion 1: meeting page survives.
        pages = self.reg.workhub.stores.pages.value()
        self.assertIn(
            self.meeting_id, pages,
            f"meeting {self.meeting_id} vanished from pages after "
            f"{len(lanes)*per_lane} concurrent decision writes. "
            f"Remaining pages: {sorted(pages.keys())}. "
            f"This reproduces smoke #21's wedge cause.",
        )

        # Assertion 2: every decision persisted (no LWW overwrites).
        meeting = pages[self.meeting_id]
        decisions = meeting.get("metadata", {}).get("decisions", [])
        self.assertEqual(
            len(decisions), len(lanes) * per_lane,
            f"only {len(decisions)} of {len(lanes)*per_lane} decisions "
            f"persisted — concurrent writes are clobbering each other. "
            f"Decisions: {[(d.get('recorded_by'), d.get('content', {}).get('i')) for d in decisions]}",
        )

        # Assertion 3: decoy page still there (no global pages wipe).
        decoys = [p for p in pages.values() if p.get("title") == "unrelated"]
        self.assertEqual(
            len(decoys), 1,
            "decoy 'unrelated' page disappeared — the store is being "
            "globally overwritten, not just losing the meeting.",
        )

    def test_concurrent_add_decision_plus_archive_keeps_meeting(self):
        """A late `archive_page` call should set status='archived' but
        NOT remove the meeting from the pages dict. If a concurrent
        add_meeting_decision after archive removes the page, that's
        the bug."""
        # First add a few decisions sequentially.
        for i in range(3):
            self.reg.workhub.add_meeting_decision(
                meeting_id=self.meeting_id,
                decision={"section": "comment", "round": 1, "content": {"i": i}},
                agent="backend",
                milestone_index=1,
            )

        # Then archive + a concurrent decision write race.
        results = {}
        def archiver():
            results["archive"] = self.reg.workhub.archive_page(
                self.meeting_id, agent="orchestrator"
            )

        def decision_writer():
            results["decision"] = self.reg.workhub.add_meeting_decision(
                meeting_id=self.meeting_id,
                decision={"section": "facilitator_note", "round": 1,
                          "content": {"action": "consensus"}},
                agent="orchestrator",
                milestone_index=1,
            )

        t1 = threading.Thread(target=archiver)
        t2 = threading.Thread(target=decision_writer)
        t1.start(); t2.start()
        t1.join(timeout=15); t2.join(timeout=15)

        pages = self.reg.workhub.stores.pages.value()
        self.assertIn(
            self.meeting_id, pages,
            f"meeting {self.meeting_id} vanished after archive+decision race",
        )

    def test_asyncio_concurrent_decisions(self):
        """Same as the thread test but via asyncio.gather — this is
        the actual concurrency model agents use (asyncio tasks)."""
        async def writer(lane: str, i: int):
            self.reg.workhub.add_meeting_decision(
                meeting_id=self.meeting_id,
                decision={"section": "comment", "round": 1,
                          "content": {"lane": lane, "i": i}},
                agent=lane,
                milestone_index=1,
            )

        async def driver():
            tasks = []
            for lane in ("backend", "frontend", "verifier"):
                for i in range(4):
                    tasks.append(writer(lane, i))
            await asyncio.gather(*tasks)

        asyncio.run(driver())

        pages = self.reg.workhub.stores.pages.value()
        self.assertIn(
            self.meeting_id, pages,
            "asyncio.gather of decision writes lost the meeting",
        )
        decisions = pages[self.meeting_id]["metadata"]["decisions"]
        self.assertEqual(
            len(decisions), 12,
            f"asyncio race lost decisions: only {len(decisions)} / 12 persisted",
        )

    def test_multiprocess_hub_registry_construction_does_not_wipe_pages(self):
        """Smoke #21 candidate root cause: live_monitor is a SEPARATE
        PROCESS that constructs HubRegistry on every HTTP request to
        serve UI state. HubRegistry.__init__ calls
        WorkHub.__init__ → stores.ensure_documents() →
        pages.update(lambda m: m). If two processes do this
        concurrently (smoke main + live_monitor) AND one process'
        `_load_raw` sees a transient partial-write OR returns {} due
        to a brief file-corruption window, the no-op update WIPES
        the file because mutator(view) returns the empty view.

        This test forks N child processes that each construct a fresh
        HubRegistry against the same workspace concurrently. After
        all children rejoin, the meeting page MUST still exist."""
        import multiprocessing as mp

        # First add some decisions so the meeting has content the
        # bug would visibly lose.
        for i in range(3):
            self.reg.workhub.add_meeting_decision(
                meeting_id=self.meeting_id,
                decision={"section": "comment", "round": 1, "content": {"i": i}},
                agent="backend",
                milestone_index=1,
            )

        def child(workspace_str: str):
            import sys as _sys
            _sys.path.insert(0, str(ROOT))
            _sys.path.insert(0, str(LLM_DIR))
            from multi_agent.runtime.hub_registry import HubRegistry
            # Repeatedly construct + re-construct HubRegistry to
            # maximize ensure_documents contention.
            from pathlib import Path as _Path
            for _ in range(40):
                _ = HubRegistry(_Path(workspace_str))

        procs = [
            mp.Process(target=child, args=(self.tmp,)) for _ in range(6)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)
        for p in procs:
            self.assertFalse(
                p.is_alive(),
                "child HubRegistry-construction process hung",
            )

        # Re-read pages with a fresh registry instance.
        from multi_agent.runtime.hub_registry import HubRegistry
        post = HubRegistry(Path(self.tmp))
        pages = post.workhub.stores.pages.value()
        self.assertIn(
            self.meeting_id, pages,
            f"Meeting {self.meeting_id} vanished after multi-process "
            f"HubRegistry construction race. Surviving pages: "
            f"{sorted(pages.keys())}. "
            f"This reproduces smoke #21's multi-process file-write race "
            f"(smoke main + live_monitor sharing workhub_pages.json).",
        )
        decisions = pages[self.meeting_id]["metadata"]["decisions"]
        self.assertEqual(
            len(decisions), 3,
            f"only {len(decisions)} / 3 pre-existing decisions survived "
            "the multi-process race",
        )


if __name__ == "__main__":
    unittest.main()
