"""Step 1 cross-hub sync: RegistryHub status='implemented' → WorkHub task completed.

Smoke #25 wedged because backend wrote 8 files + called
``registryhub_register_endpoint(status='implemented')`` for each, then called
``finish()`` — which was blocked by the ``claim-assigned-tasks`` lifecycle
gate (``workflow_policies.py:836``). The gate fired because kickoff
created parallel WorkHub ``implement_endpoint`` + ``implement_table``
tasks at finalize, and backend's prompt teaches the RegistryHub-side workflow
but not the WorkHub-side claim+complete dance.

The fix makes RegistryHub the single source of truth: when an endpoint flips
to ``status='implemented'``, RegistryHub drives the matching WorkHub task to
``status='completed'`` via the new ``sync_impl_endpoint_completed``
helper. Same for tables via SchemaHub → ``sync_impl_table_completed``.

This test pins:
  1. register_endpoint(status='implemented') auto-completes the matching
     WorkHub task (idempotently)
  2. register_table same
  3. Orphan endpoint (no matching task) is a no-op (back-compat)
  4. Already-completed task is a no-op (idempotent)
  5. Sync survives WorkHub-side errors (best-effort, doesn't raise)
  6. Sync respects depends_on: a dep-blocked task is NOT prematurely
     completed (the deps would also be completed in order anyway by
     subsequent register calls)
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _seed_kickoff_impl_endpoint_task(
    workhub, *, method: str, path: str, owner: str = "backend",
    depends_on=None,
) -> str:
    """Mirror the REAL live kickoff write path. Smoke #26 evidence:
    ``runtime/kickoff/run_kickoff.py:1050-1073`` flattens
    ``schema_tolerance.build_impl_task_tree``'s task dict via
    ``workhub.create_task(**metadata)``, which preserves only
    ``kind`` under ``metadata.kind`` and DROPS the ``endpoint`` /
    ``owner`` / ``summary`` signal fields entirely. So the live
    task only carries:
      * id (canonical ``impl.endpoint.<method>.<munged>``)
      * assignee, depends_on, status (named create_task args)
      * metadata.kind = "implement_endpoint" (nested)
    NO top-level ``kind``, NO ``endpoint`` dict. The matcher MUST
    work against THAT shape, not against schema_tolerance's pre-
    flatten dict.

    The seed driver goes through ``workhub.create_task`` exactly the
    way run_kickoff does, so the test exercises the same on-disk
    shape that smoke runs produce."""
    return _create_kickoff_task(
        workhub,
        task_id=(
            f"impl.endpoint.{method.lower()}.{path}"
            .replace("/", "_").replace("__", "_").strip("_")
        ),
        title=f"Implement {method.upper()} {path}",
        assignee=owner,
        depends_on=depends_on,
        kind="implement_endpoint",
    )


def _seed_kickoff_impl_table_task(
    workhub, *, name: str, owner: str = "backend",
) -> str:
    return _create_kickoff_task(
        workhub,
        task_id=f"impl.table.{name}",
        title=f"Implement table {name}",
        assignee=owner,
        depends_on=None,
        kind="implement_table",
    )


def _seed_kickoff_impl_page_task(
    workhub, *, name: str, owner: str = "frontend",
) -> str:
    return _create_kickoff_task(
        workhub,
        task_id=f"impl.page.{name}",
        title=f"Implement page {name}",
        assignee=owner,
        depends_on=None,
        kind="implement_page",
    )


def _seed_kickoff_impl_component_task(
    workhub, *, name: str, owner: str = "frontend",
) -> str:
    return _create_kickoff_task(
        workhub,
        task_id=f"impl.component.{name}",
        title=f"Implement component {name}",
        assignee=owner,
        depends_on=None,
        kind="implement_component",
    )


def _create_kickoff_task(workhub, *, task_id, title, assignee, depends_on, kind):
    """Drive ``workhub.create_task`` exactly the way run_kickoff does:
    pass ``kind=<...>`` as a kwarg which create_task funnels into
    ``metadata.kind`` via ``**metadata``. No top-level kind, no
    endpoint dict — same shape smoke #26 produced on disk."""
    result = workhub.create_task(
        title=title,
        assignee=assignee,
        depends_on=list(depends_on or []),
        agent="orchestrator",
        task_id=task_id,
        kind=kind,
    )
    assert "error" not in result, f"create_task failed: {result}"
    return task_id


class RegistryHubWorkHubCrossSync(unittest.TestCase):
    """Smoke #25 follow-on: register_endpoint(implemented) must close the
    matching WorkHub task so finish() is not blocked by claim-assigned."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory(prefix="cross_hub_sync_")
        self.hubs = HubRegistry(Path(self._td.name))
        self.registryhub = self.hubs.registryhub
        self.schema_hub = self.hubs.schema_hub
        self.workhub = self.hubs.workhub

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_register_endpoint_implemented_completes_matching_task(self):
        """Pin: the smoke #25 unblocker. When backend calls
        ``registryhub_register_endpoint(method='POST',
        path='/api/auth/register', status='implemented', agent='backend')``,
        the matching WorkHub ``impl.endpoint.post._api_auth_register``
        task auto-transitions from pending → completed."""
        tid = _seed_kickoff_impl_endpoint_task(
            self.workhub, method="POST", path="/api/auth/register",
        )
        self.assertEqual(self.workhub.stores.tasks.get(tid)["status"], "pending")

        # Register the endpoint twice — first define, then implement.
        # Pre-fix: the WorkHub task stayed pending forever; finish()
        # was blocked by claim-assigned-tasks; smoke #25 wedged silent.
        self.registryhub.register_endpoint(
            method="POST", path="/api/auth/register",
            agent="backend", status="defined",
        )
        self.assertEqual(
            self.workhub.stores.tasks.get(tid)["status"], "pending",
            "status='defined' must NOT close the WorkHub task",
        )
        self.registryhub.register_endpoint(
            method="POST", path="/api/auth/register",
            agent="backend", status="implemented",
        )
        t = self.workhub.stores.tasks.get(tid)
        self.assertEqual(
            t["status"], "completed",
            f"WorkHub task should auto-complete on status=implemented, "
            f"got status={t['status']!r}",
        )
        self.assertEqual(t["claimed_by"], "backend")
        # Evidence trail so post-mortems can attribute the closure.
        self.assertIn(
            "registryhub_sync", str(t.get("evidence") or {}),
            f"completion evidence should attribute to registryhub_sync; "
            f"got {t.get('evidence')!r}",
        )

    def test_register_table_implemented_completes_matching_task(self):
        """Same pin for SchemaHub.register_table."""
        tid = _seed_kickoff_impl_table_task(self.workhub, name="users")
        self.assertEqual(self.workhub.stores.tasks.get(tid)["status"], "pending")

        self.schema_hub.register_table(
            name="users", agent="backend", status="implemented",
        )
        t = self.workhub.stores.tasks.get(tid)
        self.assertEqual(
            t["status"], "completed",
            f"WorkHub impl_table task should auto-complete; got "
            f"status={t['status']!r}",
        )
        self.assertEqual(t["claimed_by"], "backend")

    def test_orphan_endpoint_no_matching_task_is_noop(self):
        """An endpoint registered WITHOUT a matching kickoff task
        (e.g. backend added an endpoint beyond the M{n} baseline)
        must not raise. The hub call still succeeds."""
        # No task seeded.
        ep = self.registryhub.register_endpoint(
            method="GET", path="/api/extra",
            agent="backend", status="implemented",
        )
        # Hub call succeeded.
        self.assertEqual(ep.get("status"), "implemented")
        # No orphan task got created.
        self.assertEqual(self.workhub.stores.tasks.value() or {}, {})

    def test_already_completed_task_is_idempotent(self):
        """Re-registering an endpoint as 'implemented' (e.g. a retry
        after a transient failure) must not error when the WorkHub
        task is already in a terminal state."""
        tid = _seed_kickoff_impl_endpoint_task(
            self.workhub, method="GET", path="/api/posts",
        )
        self.registryhub.register_endpoint(
            method="GET", path="/api/posts",
            agent="backend", status="implemented",
        )
        self.assertEqual(
            self.workhub.stores.tasks.get(tid)["status"], "completed",
        )
        # Second register with same status — must not raise + task
        # remains completed.
        self.registryhub.register_endpoint(
            method="GET", path="/api/posts",
            agent="backend", status="implemented",
        )
        self.assertEqual(
            self.workhub.stores.tasks.get(tid)["status"], "completed",
        )

    def test_sync_completes_task_already_claimed_by_same_agent(self):
        """If backend pre-claimed the task (e.g. via workhub_task
        ``action='claim'`` before writing code, per the gate's hint),
        the sync's claim-then-complete logic must still drive it to
        ``completed`` without redundant re-claim. This pins the
        ``in_progress + claimed_by == agent`` branch in
        ``_sync_complete_impl_task``."""
        tid = _seed_kickoff_impl_endpoint_task(
            self.workhub, method="GET", path="/api/posts",
        )
        # Backend claims it first (the gate's recommended flow).
        self.workhub.claim_task(tid, "backend")
        self.assertEqual(
            self.workhub.stores.tasks.get(tid)["status"], "in_progress",
        )
        self.assertEqual(
            self.workhub.stores.tasks.get(tid)["claimed_by"], "backend",
        )
        # Now register the endpoint. Sync should complete the task.
        self.registryhub.register_endpoint(
            method="GET", path="/api/posts",
            agent="backend", status="implemented",
        )
        t = self.workhub.stores.tasks.get(tid)
        self.assertEqual(t["status"], "completed")
        self.assertEqual(t["claimed_by"], "backend")

    def test_register_ui_page_implemented_completes_matching_task(self):
        """A3 pin: when register_ui_page flips a page to ``implemented``, the
        matching WorkHub ``impl.page.<name>`` task auto-completes. The cascade
        lives on RegistryHub (register_ui_page → sync_impl_page_completed) now
        that workhub.update_ui_page is a thin delegate. ``agent='orchestrator'``
        because the lifecycle-authority gate downgrades a non-orchestrator
        ``implemented`` to ``defined``."""
        tid = _seed_kickoff_impl_page_task(self.workhub, name="login")
        self.assertEqual(self.workhub.stores.tasks.get(tid)["status"], "pending")

        # defined first — must NOT complete the task. (PROPOSAL #47: a ui_page needs a
        # real route + component, as the kickoff declaration always provides; the later
        # implemented flip inherits them.)
        self.registryhub.register_ui_page(
            "login", route="/login", component="LoginPage",
            agent="orchestrator", status="defined",
        )
        self.assertEqual(
            self.workhub.stores.tasks.get(tid)["status"], "pending",
            "status='defined' must NOT close the impl.page task",
        )
        self.registryhub.register_ui_page(
            "login", agent="orchestrator", status="implemented",
        )
        t = self.workhub.stores.tasks.get(tid)
        self.assertEqual(
            t["status"], "completed",
            f"impl.page task should auto-complete on status=implemented, "
            f"got status={t['status']!r}",
        )
        self.assertEqual(t["claimed_by"], "frontend")
        self.assertIn("registryhub_sync", str(t.get("evidence") or {}))

    def test_register_ui_component_implemented_completes_matching_task(self):
        """A3 pin: register_ui_component(status='implemented') auto-completes the
        matching ``impl.component.<name>`` task (register_ui_component is
        ungated, so any agent value works)."""
        tid = _seed_kickoff_impl_component_task(self.workhub, name="nav_bar")
        self.assertEqual(self.workhub.stores.tasks.get(tid)["status"], "pending")

        self.registryhub.register_ui_component(
            "nav_bar", agent="frontend", status="implemented",
        )
        t = self.workhub.stores.tasks.get(tid)
        self.assertEqual(
            t["status"], "completed",
            f"impl.component task should auto-complete; got "
            f"status={t['status']!r}",
        )
        self.assertEqual(t["claimed_by"], "frontend")

    def test_dep_blocked_task_is_not_prematurely_completed(self):
        """``schema_tolerance`` links impl_endpoint tasks to their
        consumed-table tasks via ``depends_on``. If backend registers
        the endpoint BEFORE the underlying table is completed, the
        sync must NOT bypass that gate. (The lane's correct path is to
        register the table FIRST — which auto-completes the table task —
        and only then register the endpoint.)"""
        table_tid = _seed_kickoff_impl_table_task(self.workhub, name="users")
        ep_tid = _seed_kickoff_impl_endpoint_task(
            self.workhub,
            method="POST", path="/api/auth/register",
            depends_on=[table_tid],
        )
        # Register endpoint as implemented while the table task is still
        # pending. Sync's claim attempt is rejected by claim_task's
        # depends_on guard; task stays pending. Idempotent + safe.
        self.registryhub.register_endpoint(
            method="POST", path="/api/auth/register",
            agent="backend", status="implemented",
        )
        self.assertEqual(
            self.workhub.stores.tasks.get(ep_tid)["status"], "pending",
            "dep-blocked task must stay pending (claim_task rejects on dep)",
        )

        # Now backend registers the table first — that auto-completes
        # the table task; the endpoint task is now unblocked.
        self.schema_hub.register_table(
            name="users", agent="backend", status="implemented",
        )
        self.assertEqual(
            self.workhub.stores.tasks.get(table_tid)["status"], "completed",
        )
        # Re-register endpoint (idempotent on RegistryHub side); sync should
        # now succeed.
        self.registryhub.register_endpoint(
            method="POST", path="/api/auth/register",
            agent="backend", status="implemented",
        )
        self.assertEqual(
            self.workhub.stores.tasks.get(ep_tid)["status"], "completed",
        )


if __name__ == "__main__":
    unittest.main()
