"""TDD tests for WorkHub spec completeness (Tasks 2-5 of Cutover 3)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hubs.workhub.service import WorkHub  # noqa: E402


def _hub() -> WorkHub:
    tmp = tempfile.mkdtemp()
    return WorkHub(Path(tmp))


# Tier B B3c (docs/plan_task_stage_tier_b_design_2026_06_03.md):
# the agent-keyed plans store is retired. Tests that previously
# seeded a plan and exercised ``get_plan`` / ``list_plans`` /
# ``update_plan_metadata`` have been removed. The canonical per-task
# plan now lives at ``task.plan`` and is tested in
# ``test_workhub_task_plan_subfield.py`` + ``test_plantool_task_binding.py``.


# ---------------------------------------------------------------------------
# Task 2: fail_task + cancel_task
# ---------------------------------------------------------------------------

class TestFailTask(unittest.TestCase):
    def test_fail_task_transitions_status_to_failed(self):
        """fail_task on an in-progress task sets status=failed and records reason."""
        hub = _hub()
        task = hub.create_task("Build API", assignee="backend", agent="orchestrator")
        hub.claim_task(task["id"], "backend")
        # Completion discipline: the claimer cannot unilaterally fail — the
        # CREATOR (here orchestrator) terminates after being contacted.
        denied = hub.fail_task(task["id"], "backend", reason="timeout")
        self.assertIn("error", denied)
        result = hub.fail_task(task["id"], "orchestrator", reason="timeout")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["fail_reason"], "timeout")
        self.assertIn("failed_at", result)

    def test_fail_task_rejects_non_claimer(self):
        """fail_task by a different agent returns an error dict."""
        hub = _hub()
        task = hub.create_task("Build API", agent="orchestrator")
        hub.claim_task(task["id"], "backend")
        result = hub.fail_task(task["id"], "frontend", reason="wrong agent")
        self.assertIn("error", result)

    def test_fail_task_unknown_task_returns_error(self):
        """fail_task on a missing task_id returns error."""
        hub = _hub()
        result = hub.fail_task("task_nonexistent", "backend", reason="oops")
        self.assertIn("error", result)

    def test_fail_task_persists_in_store(self):
        """After fail_task the task in the store has status=failed."""
        hub = _hub()
        task = hub.create_task("Build API", agent="orchestrator")
        hub.claim_task(task["id"], "backend")
        hub.fail_task(task["id"], "orchestrator", reason="build error")
        stored = hub.stores.tasks.value()[task["id"]]
        self.assertEqual(stored["status"], "failed")


class TestCancelTask(unittest.TestCase):
    def test_cancel_task_transitions_pending_to_cancelled(self):
        """cancel_task on a pending task sets status=cancelled."""
        hub = _hub()
        task = hub.create_task("Build API", agent="orchestrator")
        result = hub.cancel_task(task["id"], agent="orchestrator")
        self.assertEqual(result["status"], "cancelled")
        self.assertIn("cancelled_at", result)

    def test_cancel_task_rejects_completed_task(self):
        """cancel_task on a completed task returns an error (terminal state)."""
        hub = _hub()
        task = hub.create_task("Build API", agent="orchestrator")
        hub.claim_task(task["id"], "backend")
        hub.complete_task(task["id"], "backend", result={})
        result = hub.cancel_task(task["id"], agent="orchestrator")
        self.assertIn("error", result)

    def test_cancel_task_unknown_task_returns_error(self):
        """cancel_task on a missing task_id returns error."""
        hub = _hub()
        result = hub.cancel_task("task_nonexistent", agent="orchestrator")
        self.assertIn("error", result)

    def test_cancel_in_progress_task(self):
        """cancel_task on an in-progress task also sets status=cancelled."""
        hub = _hub()
        task = hub.create_task("Build API", agent="orchestrator")
        hub.claim_task(task["id"], "backend")
        result = hub.cancel_task(task["id"], agent="orchestrator")
        self.assertEqual(result["status"], "cancelled")


# ---------------------------------------------------------------------------
# Task 3: get_task / list_tasks / available_tasks_for / tasks_by_stage
# ---------------------------------------------------------------------------

class TestGetTask(unittest.TestCase):
    def test_get_task_returns_task_dict(self):
        """get_task returns the stored task dict."""
        hub = _hub()
        task = hub.create_task("My Task", description="do stuff", agent="orch")
        fetched = hub.get_task(task["id"])
        self.assertEqual(fetched["id"], task["id"])
        self.assertEqual(fetched["title"], "My Task")

    def test_get_task_missing_returns_none(self):
        """get_task returns None for an unknown task_id."""
        hub = _hub()
        self.assertIsNone(hub.get_task("task_doesnotexist"))


class TestListTasks(unittest.TestCase):
    def test_list_tasks_no_filter_returns_all(self):
        """list_tasks with no filter returns all tasks."""
        hub = _hub()
        hub.create_task("T1", agent="orch")
        hub.create_task("T2", agent="orch")
        tasks = hub.list_tasks()
        self.assertGreaterEqual(len(tasks), 2)

    def test_list_tasks_filter_by_assignee(self):
        """list_tasks(assignee=X) returns only tasks assigned to X."""
        hub = _hub()
        hub.create_task("BackendTask", assignee="backend", agent="orch")
        hub.create_task("FrontendTask", assignee="frontend", agent="orch")
        hub.create_task("UnassignedTask", agent="orch")
        result = hub.list_tasks(assignee="backend")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["assignee"], "backend")

    def test_list_tasks_filter_by_status(self):
        """list_tasks(status='pending') returns only pending tasks."""
        hub = _hub()
        t1 = hub.create_task("T1", agent="orch")
        hub.create_task("T2", agent="orch")
        hub.claim_task(t1["id"], "backend")
        pending = hub.list_tasks(status="pending")
        self.assertTrue(all(t["status"] == "pending" for t in pending))
        self.assertEqual(len(pending), 1)

    def test_list_tasks_filter_by_plan_id(self):
        """list_tasks(plan_id=X) returns only tasks belonging to that plan.

        Tier B B3c: the agent-keyed plans store is gone; ``plan_id`` is
        now just a string field on a task (legacy). The filter still
        works on the field itself."""
        hub = _hub()
        hub.create_task("PlanTask", plan_id="some_plan", agent="orch")
        hub.create_task("StandaloneTask", agent="orch")
        result = hub.list_tasks(plan_id="some_plan")
        self.assertTrue(all(t["plan_id"] == "some_plan" for t in result))
        self.assertGreaterEqual(len(result), 1)


class TestAvailableTasksFor(unittest.TestCase):
    def test_available_tasks_for_excludes_tasks_with_unmet_deps(self):
        """available_tasks_for excludes tasks whose depends_on tasks are not completed."""
        hub = _hub()
        blocker = hub.create_task("Blocker", agent="orch")
        dependent = hub.create_task("Dependent", depends_on=[blocker["id"]], agent="orch")
        available = hub.available_tasks_for("backend")
        avail_ids = [t["id"] for t in available]
        self.assertIn(blocker["id"], avail_ids)
        self.assertNotIn(dependent["id"], avail_ids)

    def test_available_tasks_for_includes_tasks_after_dep_completes(self):
        """available_tasks_for includes a task once its dependency is completed."""
        hub = _hub()
        blocker = hub.create_task("Blocker", agent="orch")
        dependent = hub.create_task("Dependent", depends_on=[blocker["id"]], agent="orch")
        hub.claim_task(blocker["id"], "backend")
        hub.complete_task(blocker["id"], "backend", result={})
        available = hub.available_tasks_for("backend")
        avail_ids = [t["id"] for t in available]
        self.assertIn(dependent["id"], avail_ids)

    def test_available_tasks_for_excludes_non_pending(self):
        """available_tasks_for excludes tasks that are not pending."""
        hub = _hub()
        t1 = hub.create_task("T1", agent="orch")
        hub.claim_task(t1["id"], "backend")
        available = hub.available_tasks_for("backend")
        avail_ids = [t["id"] for t in available]
        self.assertNotIn(t1["id"], avail_ids)


# Tier A retirement (docs/plan_task_stage_review_2026_06_03.md):
# the ``TestTasksByStage`` class (2 tests) tested the retired
# ``WorkHub.tasks_by_stage`` reader. The WorkHub ``stage_id`` field
# is write-only across the live codebase (scheduler / delivery-gate /
# roadmap_validator / ready_set all zero hits); the only reader was
# this helper, retired in the same Tier A pass.


# ---------------------------------------------------------------------------
# Task 4: get_page / list_pages / get_plan / list_plans / link_task_to_pr /
#         link_task_to_apis / comments_for
# ---------------------------------------------------------------------------

class TestGetPage(unittest.TestCase):
    def test_get_page_returns_page_and_blocks(self):
        """get_page with with_blocks=True returns page dict with its blocks."""
        hub = _hub()
        page = hub.create_document("Spec", agent="orch")
        hub.append_block(page["id"], {"type": "text", "content": "hello"}, agent="orch")
        result = hub.get_document(page["id"], with_blocks=True)
        self.assertEqual(result["id"], page["id"])
        self.assertIn("blocks", result)
        self.assertEqual(len(result["blocks"]), 1)

    def test_get_page_without_blocks(self):
        """get_page with with_blocks=False returns page dict without blocks key."""
        hub = _hub()
        page = hub.create_document("Spec", agent="orch")
        hub.append_block(page["id"], {"type": "text", "content": "hello"}, agent="orch")
        result = hub.get_document(page["id"], with_blocks=False)
        self.assertEqual(result["id"], page["id"])
        self.assertNotIn("blocks", result)

    def test_get_page_missing_returns_none(self):
        """get_page returns None for an unknown page_id."""
        hub = _hub()
        self.assertIsNone(hub.get_document("page_nope"))


class TestListPages(unittest.TestCase):
    def test_list_pages_returns_all_pages(self):
        """list_pages with no filters returns all pages."""
        hub = _hub()
        hub.create_document("Page A", agent="orch")
        hub.create_document("Page B", agent="orch")
        pages = hub.list_documents()
        self.assertGreaterEqual(len(pages), 2)

    def test_list_pages_filter_by_status(self):
        """list_pages(status='active') returns only active pages."""
        hub = _hub()
        hub.create_document("Active Page", agent="orch")
        pages = hub.list_documents(status="active")
        self.assertTrue(all(p["status"] == "active" for p in pages))

    def test_list_pages_filter_by_kind(self):
        """list_pages(kind='spec') returns only spec pages."""
        hub = _hub()
        p1 = hub.create_document("Spec Page", agent="orch")
        # Manually set kind on the page
        ts = "orch"
        updated = dict(p1)
        updated["kind"] = "spec"
        hub.stores.documents.update(lambda m: m.set(p1["id"], updated, ts))
        hub.create_document("Notes Page", agent="orch")
        result = hub.list_documents(kind="spec")
        self.assertTrue(all(p.get("kind") == "spec" for p in result))
        self.assertGreaterEqual(len(result), 1)


# Tier B B3c retirement: TestGetPlan, TestListPlans classes removed
# along with ``WorkHub.get_plan`` / ``list_plans``. The canonical per-task
# plan now lives at ``task.plan`` (see test_workhub_task_plan_subfield.py).


class TestLinkTaskToPr(unittest.TestCase):
    def test_link_task_to_pr_sets_linked_pr(self):
        """link_task_to_pr sets linked_pr on the task."""
        hub = _hub()
        task = hub.create_task("T1", agent="orch")
        result = hub.link_task_to_pr(task["id"], "pr_abc123", agent="backend")
        self.assertEqual(result["linked_pr"], "pr_abc123")

    def test_link_task_to_pr_unknown_task_returns_error(self):
        """link_task_to_pr on an unknown task returns an error."""
        hub = _hub()
        result = hub.link_task_to_pr("task_nope", "pr_abc", agent="backend")
        self.assertIn("error", result)


class TestLinkTaskToApis(unittest.TestCase):
    def test_link_task_to_apis_sets_linked_apis(self):
        """link_task_to_apis sets linked_apis on the task."""
        hub = _hub()
        task = hub.create_task("T1", agent="orch")
        result = hub.link_task_to_apis(task["id"], ["GET /api/feed", "POST /api/posts"], agent="backend")
        self.assertIn("GET /api/feed", result["linked_apis"])
        self.assertIn("POST /api/posts", result["linked_apis"])

    def test_link_task_to_apis_unknown_task_returns_error(self):
        """link_task_to_apis on an unknown task returns an error."""
        hub = _hub()
        result = hub.link_task_to_apis("task_nope", ["GET /api/feed"], agent="backend")
        self.assertIn("error", result)


class TestCommentsFor(unittest.TestCase):
    def test_comments_for_returns_comments_for_resource(self):
        """comments_for returns all comments for a given resource_id."""
        hub = _hub()
        page = hub.create_document("Spec", agent="orch")
        hub.comment(page["id"], "Great doc!", agent="frontend")
        hub.comment(page["id"], "Needs more detail", agent="backend")
        hub.comment("other_resource", "Unrelated", agent="orch")
        result = hub.comments_for(page["id"])
        self.assertEqual(len(result), 2)
        self.assertTrue(all(c["resource_id"] == page["id"] for c in result))

    def test_comments_for_returns_empty_for_unknown_resource(self):
        """comments_for returns [] for a resource with no comments."""
        hub = _hub()
        result = hub.comments_for("page_nope")
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# Task 5: update_block / insert_block_after / archive_page
# ---------------------------------------------------------------------------

class TestUpdateBlock(unittest.TestCase):
    def test_update_block_changes_content(self):
        """update_block replaces the block content and updates _updated_by."""
        hub = _hub()
        page = hub.create_document("Spec", agent="orch")
        block = hub.append_block(page["id"], {"type": "text", "content": "old"}, agent="orch")
        result = hub.update_block(block["id"], "new content", agent="backend")
        self.assertEqual(result["content"], "new content")
        self.assertEqual(result["_updated_by"], "backend")

    def test_update_block_unknown_block_returns_error(self):
        """update_block on an unknown block_id returns an error."""
        hub = _hub()
        result = hub.update_block("block_nope", "content", agent="orch")
        self.assertIn("error", result)

    def test_update_block_persists(self):
        """After update_block the store contains the updated content."""
        hub = _hub()
        page = hub.create_document("Spec", agent="orch")
        block = hub.append_block(page["id"], {"type": "text", "content": "old"}, agent="orch")
        hub.update_block(block["id"], "persisted!", agent="orch")
        stored = hub.stores.blocks.value()[block["id"]]
        self.assertEqual(stored["content"], "persisted!")


class TestInsertBlockAfter(unittest.TestCase):
    def test_insert_block_after_places_block_between_two_blocks(self):
        """insert_block_after inserts a new block whose ord is the midpoint."""
        hub = _hub()
        page = hub.create_document("Spec", agent="orch")
        b1 = hub.append_block(page["id"], {"type": "text", "content": "A", "ord": 1024}, agent="orch")
        b2 = hub.append_block(page["id"], {"type": "text", "content": "B", "ord": 2048}, agent="orch")
        new_block = hub.insert_block_after(
            page["id"],
            after_block_id=b1["id"],
            block={"type": "text", "content": "Between"},
            agent="orch",
        )
        self.assertGreater(new_block["ord"], b1.get("ord", 1024))
        self.assertLess(new_block["ord"], b2.get("ord", 2048))

    def test_insert_block_after_unknown_page_returns_error(self):
        """insert_block_after with unknown page_id returns an error."""
        hub = _hub()
        result = hub.insert_block_after(
            "page_nope",
            after_block_id="block_nope",
            block={"type": "text", "content": "x"},
            agent="orch",
        )
        self.assertIn("error", result)

    def test_insert_block_after_at_end_if_after_block_not_found(self):
        """insert_block_after with unknown after_block_id appends at the end."""
        hub = _hub()
        page = hub.create_document("Spec", agent="orch")
        hub.append_block(page["id"], {"type": "text", "content": "A", "ord": 1024}, agent="orch")
        result = hub.insert_block_after(
            page["id"],
            after_block_id="block_nope",
            block={"type": "text", "content": "End"},
            agent="orch",
        )
        self.assertNotIn("error", result)
        self.assertGreater(result["ord"], 1024)


class TestArchivePage(unittest.TestCase):
    def test_archive_page_sets_status_archived(self):
        """archive_page sets the page status to 'archived'."""
        hub = _hub()
        page = hub.create_document("Old Spec", agent="orch")
        result = hub.archive_document(page["id"], agent="orch")
        self.assertEqual(result["status"], "archived")
        self.assertEqual(result["_updated_by"], "orch")

    def test_archive_page_unknown_page_returns_error(self):
        """archive_page on an unknown page_id returns an error."""
        hub = _hub()
        result = hub.archive_document("page_nope", agent="orch")
        self.assertIn("error", result)

    def test_archive_page_persists(self):
        """After archive_page the store has status=archived."""
        hub = _hub()
        page = hub.create_document("Old Spec", agent="orch")
        hub.archive_document(page["id"], agent="orch")
        stored = hub.stores.documents.value()[page["id"]]
        self.assertEqual(stored["status"], "archived")


# ---------------------------------------------------------------------------
# Task 7: (legacy heading — both update_plan_metadata + add_task_to_plan
# retired with the plans store; see Tier A and Tier B B3c comments below.)
# ---------------------------------------------------------------------------

# Tier B B3c retirement: TestUpdatePlanMetadata removed along with
# ``WorkHub.update_plan_metadata``. Plan content for a task now lives
# at ``task.plan`` and is mutated through ``WorkHub.update_task_plan``
# (B2). See test_workhub_task_plan_subfield.py.


# Tier A retirement (docs/plan_task_stage_review_2026_06_03.md):
# ``TestAddTaskToPlan`` deleted along with the retired
# ``WorkHub.add_task_to_plan`` — zero live agent-runtime callers,
# the only HTTP surface had no UI/JSX client.


# ---------------------------------------------------------------------------
# Task 6: reply / react / remove_attendee / record_decision
# ---------------------------------------------------------------------------

class TestReply(unittest.TestCase):
    def test_reply_creates_comment_with_parent_id(self):
        """reply creates a new comment with parent_id set to the original comment."""
        hub = _hub()
        page = hub.create_document("Spec", agent="orch")
        parent = hub.comment(page["id"], "Original comment", agent="orch")
        reply = hub.reply(parent["id"], "Reply body", agent="frontend")
        self.assertEqual(reply["parent_id"], parent["id"])
        self.assertEqual(reply["resource_id"], page["id"])

    def test_reply_inherits_resource_id(self):
        """reply inherits the resource_id from the parent comment."""
        hub = _hub()
        page = hub.create_document("Spec", agent="orch")
        parent = hub.comment(page["id"], "Root", agent="orch")
        reply = hub.reply(parent["id"], "Child", agent="backend")
        self.assertEqual(reply["resource_id"], page["id"])

    def test_reply_unknown_comment_returns_error(self):
        """reply on an unknown comment_id returns an error."""
        hub = _hub()
        result = hub.reply("comment_nope", "body", agent="orch")
        self.assertIn("error", result)

    def test_reply_persists_in_store(self):
        """After reply the reply is stored in comments store."""
        hub = _hub()
        page = hub.create_document("Spec", agent="orch")
        parent = hub.comment(page["id"], "Root", agent="orch")
        reply = hub.reply(parent["id"], "Reply!", agent="backend")
        stored = hub.stores.comments.value().get(reply["id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored["parent_id"], parent["id"])


class TestReact(unittest.TestCase):
    def test_react_stores_reaction(self):
        """react stores the reaction in the reactions store."""
        hub = _hub()
        page = hub.create_document("Spec", agent="orch")
        comment = hub.comment(page["id"], "Nice doc!", agent="orch")
        result = hub.react(comment["id"], "+1", "frontend")
        self.assertEqual(result["reaction"], "+1")
        self.assertEqual(result["agent"], "frontend")

    def test_react_keyed_by_comment_and_agent(self):
        """react uses composite key comment_id:agent (LWW)."""
        hub = _hub()
        page = hub.create_document("Spec", agent="orch")
        comment = hub.comment(page["id"], "Doc", agent="orch")
        hub.react(comment["id"], "+1", "frontend")
        hub.react(comment["id"], "heart", "frontend")  # overwrites
        key = f"{comment['id']}:frontend"
        stored = hub.stores.reactions.value().get(key)
        self.assertEqual(stored["reaction"], "heart")

    def test_react_different_agents_stored_separately(self):
        """Different agents can react to the same comment independently."""
        hub = _hub()
        page = hub.create_document("Spec", agent="orch")
        comment = hub.comment(page["id"], "Doc", agent="orch")
        hub.react(comment["id"], "+1", "frontend")
        hub.react(comment["id"], "-1", "backend")
        reactions = hub.stores.reactions.value()
        self.assertIn(f"{comment['id']}:frontend", reactions)
        self.assertIn(f"{comment['id']}:backend", reactions)


class TestRemoveAttendee(unittest.TestCase):
    def test_remove_attendee_soft_deletes(self):
        """remove_attendee sets _removed=True on the attendee record."""
        hub = _hub()
        page = hub.create_document("Spec", attendees=["frontend"], agent="orch")
        result = hub.remove_attendee("page", page["id"], "frontend", by="orch")
        self.assertTrue(result["_removed"])
        self.assertEqual(result["_removed_by"], "orch")

    def test_remove_attendee_uses_composite_key(self):
        """remove_attendee persists under resource_id:agent_id key."""
        hub = _hub()
        page = hub.create_document("Spec", attendees=["backend"], agent="orch")
        hub.remove_attendee("page", page["id"], "backend", by="orch")
        key = f"{page['id']}:backend"
        stored = hub.stores.attendees.value().get(key)
        self.assertIsNotNone(stored)
        self.assertTrue(stored["_removed"])


class TestRecordDecision(unittest.TestCase):
    def test_record_decision_appends_decision_block(self):
        """record_decision appends a block of type 'decision' to the page."""
        hub = _hub()
        page = hub.create_document("Spec", agent="orch")
        result = hub.record_decision(
            page["id"], "Use PostgreSQL", ["PostgreSQL", "MySQL"], "PostgreSQL", "Better JSONB support", "orch"
        )
        self.assertIn("block_id", result)
        block = hub.stores.blocks.value().get(result["block_id"])
        self.assertEqual(block["type"], "decision")
        self.assertEqual(block["content"]["chosen"], "PostgreSQL")

    def test_record_decision_stores_in_decisions(self):
        """record_decision stores a record in the decisions store."""
        hub = _hub()
        page = hub.create_document("Spec", agent="orch")
        result = hub.record_decision(
            page["id"], "Auth method", ["JWT", "Session"], "JWT", "Stateless", "orch"
        )
        stored = hub.stores.decisions.value().get(result["id"])
        self.assertEqual(stored["chosen"], "JWT")

    def test_record_decision_unknown_page_returns_error(self):
        """record_decision on an unknown page returns an error."""
        hub = _hub()
        result = hub.record_decision("page_nope", "T", [], "x", "r", "orch")
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
