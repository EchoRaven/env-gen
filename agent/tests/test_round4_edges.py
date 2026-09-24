"""Round-4 edges: inbox eviction, integration→main promotion, endpoint
id normalization, git-lock retry, bug validation, subscription cleanup."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402


class EndpointIdNormalization(unittest.TestCase):
    def test_trailing_slash_collapses(self):
        self.assertEqual(
            RegistryHub.endpoint_id("GET", "/api/posts/"),
            RegistryHub.endpoint_id("GET", "/api/posts"),
        )

    def test_missing_leading_slash_added(self):
        self.assertEqual(
            RegistryHub.endpoint_id("POST", "api/posts"),
            RegistryHub.endpoint_id("POST", "/api/posts"),
        )

    def test_method_case_normalized(self):
        self.assertEqual(
            RegistryHub.endpoint_id("get", "/api/posts"),
            RegistryHub.endpoint_id("GET", "/api/posts"),
        )

    def test_bare_root_path_preserved(self):
        # "/" should NOT become "" — that's a real endpoint.
        self.assertEqual(RegistryHub.endpoint_id("GET", "/"), "GET /")

    def test_consumer_matches_normalized_endpoint(self):
        """Frontend registers consumer with trailing-slash URL; backend
        registers endpoint without. They must connect after normalization."""
        with tempfile.TemporaryDirectory() as tmp:
            hubs = HubRegistry(Path(tmp))
            hubs.registryhub.register_endpoint(
                "GET", "/api/posts", schema={"response": {"items": []}},
                provider="backend", agent="backend", status="implemented",
            )
            # Frontend uses the trailing-slash form.
            res = hubs.registryhub.register_consumer(
                "GET /api/posts/", "src/Feed.jsx", "frontend",
            )
            self.assertNotIn("error", res)
            consumers = hubs.registryhub.get_consumers("GET /api/posts")
            self.assertEqual(len(consumers), 1)


class InboxEviction(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="evict_"))
        self.hubs = HubRegistry(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_only_old_read_events_evicted(self):
        # Publish two events.
        e1 = self.hubs.eventhub.publish_event(
            source_hub="registryhub", event_type="x", payload={},
            recipients=["backend"], priority="normal",
        )
        e2 = self.hubs.eventhub.publish_event(
            source_hub="registryhub", event_type="y", payload={},
            recipients=["backend"], priority="normal",
        )
        # Mark both read, but artificially age e1's read_at.
        self.hubs.eventhub.mark_read("backend", e1["id"])
        self.hubs.eventhub.mark_read("backend", e2["id"])
        inbox = self.hubs.eventhub._inboxes.value()["backend"]
        inbox["items"][e1["id"]]["read_at"] = time.time() - 200000.0
        self.hubs.eventhub._inboxes.update(
            lambda m: m.set("backend", inbox, "test"),
            change_info={"agent": "test"},
        )
        # Cut keep_min to 0 so age threshold actually fires.
        evicted = self.hubs.eventhub.prune_read_inbox(
            "backend", older_than_seconds=86400, keep_min=0,
        )
        self.assertEqual(evicted, 1)
        remaining = self.hubs.eventhub._inboxes.value()["backend"]["items"]
        self.assertNotIn(e1["id"], remaining)
        self.assertIn(e2["id"], remaining)

    def test_unread_events_never_evicted(self):
        e = self.hubs.eventhub.publish_event(
            source_hub="registryhub", event_type="x", payload={},
            recipients=["backend"], priority="normal",
        )
        inbox = self.hubs.eventhub._inboxes.value()["backend"]
        inbox["items"][e["id"]]["received_at"] = time.time() - 200000.0
        self.hubs.eventhub._inboxes.update(
            lambda m: m.set("backend", inbox, "test"),
            change_info={"agent": "test"},
        )
        self.assertEqual(
            self.hubs.eventhub.prune_read_inbox(
                "backend", older_than_seconds=1, keep_min=0,
            ),
            0,
        )

    def test_keep_min_protects_recent_reads(self):
        ids = []
        for i in range(5):
            ev = self.hubs.eventhub.publish_event(
                source_hub="registryhub", event_type=f"e{i}", payload={},
                recipients=["backend"], priority="normal",
            )
            self.hubs.eventhub.mark_read("backend", ev["id"])
            ids.append(ev["id"])
        # Age all reads.
        inbox = self.hubs.eventhub._inboxes.value()["backend"]
        for eid in ids:
            inbox["items"][eid]["read_at"] = time.time() - 200000.0
        self.hubs.eventhub._inboxes.update(
            lambda m: m.set("backend", inbox, "test"),
            change_info={"agent": "test"},
        )
        # keep_min=3 → only 2 get evicted.
        evicted = self.hubs.eventhub.prune_read_inbox(
            "backend", older_than_seconds=86400, keep_min=3,
        )
        self.assertEqual(evicted, 2)


class IntegrationToMainPromotion(unittest.TestCase):
    """promote_integration_to_main fast-forwards (or merges) integration
    onto main, called by the verifier after a green run."""

    def _init_repo(self, tmp: Path) -> Path:
        repo = tmp / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        # Force the branch to ``main`` regardless of the default
        # (older gits use ``master``).
        subprocess.run(
            ["git", "symbolic-ref", "HEAD", "refs/heads/main"],
            cwd=repo, check=True,
        )
        (repo / "README.md").write_text("init\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@e.local", "-c", "user.name=t",
             "commit", "-qm", "init"],
            cwd=repo, check=True,
        )
        return repo

    def test_ff_promotion_after_integration_progresses(self):
        from multi_agent.agents.runtime.auto_commit import (
            promote_integration_to_main,
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._init_repo(Path(tmp))
            # Create integration off main, add a commit to it.
            subprocess.run(
                ["git", "checkout", "-q", "-b", "integration"],
                cwd=repo, check=True,
            )
            (repo / "feature.txt").write_text("done\n")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(
                ["git", "-c", "user.email=t@e.local", "-c", "user.name=t",
                 "commit", "-qm", "feat"],
                cwd=repo, check=True,
            )
            ok, info = promote_integration_to_main(
                repo_root=repo, integration_branch="integration",
                main_branch="main", actor="verifier", blessed_run_id="run_abc",
            )
            self.assertTrue(ok, info)
            # main should now have the feature commit.
            subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)
            self.assertTrue((repo / "feature.txt").exists())

    def test_nothing_to_promote_returns_true_with_note(self):
        from multi_agent.agents.runtime.auto_commit import (
            promote_integration_to_main,
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._init_repo(Path(tmp))
            subprocess.run(
                ["git", "checkout", "-q", "-b", "integration"],
                cwd=repo, check=True,
            )
            ok, info = promote_integration_to_main(
                repo_root=repo, integration_branch="integration",
                main_branch="main",
            )
            self.assertTrue(ok)
            self.assertIn("nothing to promote", info.lower())


class BugCreateValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bug_val_"))
        self.hubs = HubRegistry(self.tmp)
        from tools.bug_tools import BugCreateTool
        self.tool = BugCreateTool(agent_id="verifier", hub_workspace=self.hubs)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_title_rejected(self):
        result = asyncio.run(self.tool._run(
            title="   ", source="verifier", severity="P1",
            bug_artifacts={"failing_test": "test_x"},
        ))
        self.assertFalse(result.success)
        self.assertIn("title", (result.error_message or "").lower())

    def test_empty_bug_artifacts_rejected(self):
        result = asyncio.run(self.tool._run(
            title="thing broke", source="verifier", severity="P2",
            bug_artifacts={},
        ))
        self.assertFalse(result.success)
        self.assertIn("artifact", (result.error_message or "").lower())

    def test_valid_bug_succeeds(self):
        result = asyncio.run(self.tool._run(
            title="login broken", source="verifier", severity="P0",
            bug_artifacts={"failing_test": "tests/test_login.py::test_ok"},
        ))
        self.assertTrue(result.success, result.error_message)
        self.assertEqual(result.data.get("title"), "login broken")


class SubscriptionCleanupOnTerminate(unittest.TestCase):
    """unsubscribe_all reaps every subscription owned by an agent so
    worker_* terminations don't grow the subs table forever."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="unsub_"))
        self.hubs = HubRegistry(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unsubscribe_all_removes_only_target_agent_rows(self):
        self.hubs.eventhub.subscribe(
            agent="worker_x", source_hub="registryhub", event_type="endpoint_defined",
        )
        self.hubs.eventhub.subscribe(
            agent="worker_x", source_hub="workhub", event_type="task_created",
        )
        self.hubs.eventhub.subscribe(
            agent="backend", source_hub="registryhub", event_type="endpoint_defined",
        )
        count = self.hubs.eventhub.unsubscribe_all("worker_x")
        self.assertEqual(count, 2)
        # backend's row survives.
        backend_subs = self.hubs.eventhub.get_subscriptions(agent="backend")
        self.assertEqual(len(backend_subs), 1)
        # worker_x has zero active subs.
        self.assertEqual(self.hubs.eventhub.get_subscriptions(agent="worker_x"), [])


if __name__ == "__main__":
    unittest.main()
