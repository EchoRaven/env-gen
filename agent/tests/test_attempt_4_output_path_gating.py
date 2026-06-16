"""Phase 0.2 attempt-4 PHASE 2 FIX A — gate the three genuinely
traversal-class ``output_path`` tools that PHASE 1 AUDIT A confirmed
are FULLY_AGENT_CONTROLLED writes:

  * ``generate_seed_sql`` — HIGH severity. ``data_engine_tools.py``
    lines 810-813 bypass ``workspace.resolve()`` entirely (raw
    ``self.workspace.root / output_file`` join, plus an absolute-path
    pass-through). A malicious ``output_file="/etc/cron.d/evil"`` or
    ``output_file="../../etc/passwd"`` escapes the workspace base —
    same traversal class as the Phase 0.2 RCE. Even if a future fix
    to the tool routes through ``workspace.resolve()`` (we recommend
    that too), the role-write gate must still fire so that, e.g., a
    ``frontend`` agent cannot generate SQL into ``app/database/``.
    Its write parameter is ``output_file`` (NOT ``file_path`` /
    ``path``), which means the gate's extraction needs the explicit
    ``output_file`` fallback that this fix wires in.
  * ``save_image`` — MEDIUM. ``image_search_tools.py:619`` routes
    through ``workspace.resolve()`` (which contains escape via the
    leading-``../`` strip and ``contains()`` enforcement), so true
    base escape is impossible. But there is NO per-agent role gate:
    a generator-role agent can write into a sibling role's prefix
    (e.g. ``design/`` or ``app/backend/``) within the same workspace
    base. The gate closes that role-confusion gap.
  * ``capture_webpage`` — MEDIUM, same shape as ``save_image``. The
    optional ``path`` parameter goes through ``workspace.resolve()``
    when provided; the fallback writes ``screenshots/<domain>.png``
    where ``screenshots/`` is a READ-ONLY route — so any
    fallback-mode call by any agent must be denied. The gate's
    fallback handling surfaces ``screenshots/`` as the write target
    when ``path`` is absent, so the universally-read-only route
    rejects it.

The shape of these tests mirrors
``tests/test_update_path_tools_write_gate.py`` (the attempt-3 FIX A
analogue): three scenarios per tool — out-of-role denial,
read-only-route denial (where applicable), and in-role legit allow.

The structural invariant test in ``tests/test_write_gate_invariant.py``
also recognises these three names in ``GATED_TOOL_NAMES``; it will
turn green for them once both the runtime set AND the invariant
constant are updated in lock-step (this fix does both).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace  # noqa: E402
from multi_agent.workspace_manager import WorkspaceManager  # noqa: E402
from multi_agent.agents.runtime.tooling import AgentTooling  # noqa: E402


class _StubAgent(AgentTooling):
    """Minimal AgentTooling subclass exposing exactly what
    ``_enforce_write_permissions`` reads. Mirrors the stub in
    ``test_update_path_tools_write_gate.py`` /
    ``test_write_permission_gate_live.py`` — same wiring, same gate
    surface, just exercises the three newly-gated tool names."""

    def __init__(self, agent_id: str, workspace, routed_workspace=None):
        self.agent_id = agent_id
        self.workspace = workspace
        if routed_workspace is not None:
            self._routed_workspace = routed_workspace
        self._logger = MagicMock()


def _make_agent(tmp: Path, agent_id: str) -> _StubAgent:
    base = tmp
    code = tmp / "worktrees" / agent_id
    code.mkdir(parents=True)
    routed = PathRoutedWorkspace(base_root=base, code_root=code)
    return _StubAgent(agent_id,
                      workspace=WorkspaceManager(base),
                      routed_workspace=routed)


class GenerateSeedSqlRoutesThroughGate(unittest.TestCase):
    """The HIGH-severity finding from PHASE 1 AUDIT A.

    ``GenerateSeedSQLTool`` (data_engine_tools.py:673) writes SQL
    INSERT statements to an agent-controlled ``output_file`` that
    skipped ``workspace.resolve()`` — a real traversal-class write.
    Gating it ensures (a) the role-write gate rejects out-of-role
    writes, and (b) the legitimate ``database``-role flow that
    seeds ``app/database/init/*.sql`` still passes."""

    def test_generate_seed_sql_rejects_out_of_role_write(self):
        """A ``frontend`` agent must NOT be able to seed
        ``app/database/init/02_seed.sql`` via ``generate_seed_sql``.
        ``app/database/`` is owned by the ``database`` role per
        ROUTING_TABLE — frontend has no business writing there."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = _make_agent(Path(tmp), "frontend")
            outcome = agent._enforce_write_permissions(
                "generate_seed_sql",
                {"dataset_id": "x/y",
                 "table_name": "games",
                 "output_file": "app/database/init/02_seed.sql"},
            )
            self.assertIsNotNone(
                outcome,
                "generate_seed_sql writing app/database/* by frontend "
                "MUST be denied — the gate now intercepts this tool "
                "and extracts the write target from its `output_file` "
                "parameter (the new fallback in the extraction).",
            )
            self.assertFalse(outcome.success)
            self.assertIn("app/database/init/02_seed.sql",
                          outcome.error_message)

    def test_generate_seed_sql_rejects_readonly_route(self):
        """``shared/`` is READ-ONLY in ROUTING_TABLE. NO agent —
        including the ``database`` role — may seed SQL there via
        ``generate_seed_sql``. This is also the closest analogue to
        the HIGH-severity traversal vector: a path that targets a
        privileged region of the workspace must hit the gate, not
        slip through because the tool's parameter name was unknown
        to the extraction."""
        for agent_id in ("frontend", "backend", "database", "verifier"):
            with self.subTest(agent_id=agent_id):
                with tempfile.TemporaryDirectory() as tmp:
                    agent = _make_agent(Path(tmp), agent_id)
                    outcome = agent._enforce_write_permissions(
                        "generate_seed_sql",
                        {"dataset_id": "x/y",
                         "table_name": "games",
                         "output_file": "shared/seed.sql"},
                    )
                    self.assertIsNotNone(
                        outcome,
                        f"{agent_id} writing shared/* via "
                        f"generate_seed_sql must be denied — read-only "
                        f"route in ROUTING_TABLE",
                    )
                    self.assertFalse(outcome.success)

    def test_generate_seed_sql_accepts_legit(self):
        """The mirror image: the ``database`` agent seeding its own
        ``app/database/init/02_seed.sql`` is the canonical use of
        this tool (matches the example in the tool's docstring).
        Gate must NOT block — otherwise the fix breaks the happy
        path that DataEngineToolKit was written for."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = _make_agent(Path(tmp), "database")
            outcome = agent._enforce_write_permissions(
                "generate_seed_sql",
                {"dataset_id": "x/y",
                 "table_name": "games",
                 "output_file": "app/database/init/02_seed.sql"},
            )
            self.assertIsNone(
                outcome,
                "database role seeding its own app/database/init/* "
                "via generate_seed_sql must pass the gate cleanly",
            )


class SaveImageRoutesThroughGate(unittest.TestCase):
    """MEDIUM-severity finding from PHASE 1 AUDIT A.

    ``SaveImageTool`` (image_search_tools.py:551) writes downloaded
    bytes through ``workspace.resolve()`` (containment OK) but had
    no per-agent role gate, allowing role-confusion writes inside
    the same workspace base."""

    def test_save_image_rejects_out_of_role_write(self):
        """A ``verifier`` agent must NOT be able to drop an image
        into ``design/`` (owned by backend+frontend per ROUTING_TABLE
        after the Round 8e.1 design+frontend merge). Before this gate
        ``save_image`` was not in the gated set and the write would
        have proceeded — same role-confusion shape as the
        ``update_json_path`` bypass that attempt-3 FIX A closed."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = _make_agent(Path(tmp), "verifier")
            outcome = agent._enforce_write_permissions(
                "save_image",
                {"url": "https://example.com/logo.png",
                 "path": "design/logo.png"},
            )
            self.assertIsNotNone(
                outcome,
                "save_image writing design/* by verifier MUST be "
                "denied — design/ writers are backend+frontend only.",
            )
            self.assertFalse(outcome.success)
            self.assertIn("design/logo.png", outcome.error_message)

    def test_save_image_rejects_readonly_route(self):
        """``images/`` is READ-ONLY in ROUTING_TABLE (a shared
        asset bucket maintained by an offline process, not by
        agents). Every agent must be denied a ``save_image`` write
        into that prefix — until the fix that meant
        any-agent-could-clobber-shared-assets."""
        for agent_id in ("frontend", "backend", "database", "verifier"):
            with self.subTest(agent_id=agent_id):
                with tempfile.TemporaryDirectory() as tmp:
                    agent = _make_agent(Path(tmp), agent_id)
                    outcome = agent._enforce_write_permissions(
                        "save_image",
                        {"url": "https://example.com/pic.png",
                         "path": "images/pic.png"},
                    )
                    self.assertIsNotNone(
                        outcome,
                        f"{agent_id} writing images/* via save_image "
                        f"must be denied — read-only route in "
                        f"ROUTING_TABLE",
                    )
                    self.assertFalse(outcome.success)

    def test_save_image_accepts_legit(self):
        """The legitimate use case: a ``frontend`` agent saving an
        icon into its own per-role worktree at
        ``app/frontend/assets/icons/home.svg``. The gate must NOT
        block — otherwise frontend can't build the UI it was
        constructed to build."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = _make_agent(Path(tmp), "frontend")
            outcome = agent._enforce_write_permissions(
                "save_image",
                {"url": "https://example.com/home.svg",
                 "path": "app/frontend/assets/icons/home.svg"},
            )
            self.assertIsNone(
                outcome,
                "frontend saving into its own app/frontend/* via "
                "save_image must pass the gate cleanly",
            )


class CaptureWebpageRoutesThroughGate(unittest.TestCase):
    """MEDIUM-severity finding from PHASE 1 AUDIT A.

    ``CaptureWebpageTool`` (image_search_tools.py:665) writes a
    Playwright screenshot through ``workspace.resolve()`` when
    ``path`` is provided; otherwise it writes to
    ``screenshots/<sanitised_domain>.png`` — and ``screenshots/`` is
    READ-ONLY in ROUTING_TABLE. The gate must intercept both the
    explicit-path and the fallback-path shapes."""

    def test_capture_webpage_rejects_out_of_role_write(self):
        """A ``verifier`` agent capturing a webpage into ``design/``
        must be denied. ``design/`` writers are backend+frontend only
        per ROUTING_TABLE after the Round 8e.1 design+frontend merge —
        same role-confusion shape as ``save_image``."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = _make_agent(Path(tmp), "verifier")
            outcome = agent._enforce_write_permissions(
                "capture_webpage",
                {"url": "https://example.com",
                 "path": "design/competitor.png"},
            )
            self.assertIsNotNone(
                outcome,
                "capture_webpage writing design/* by verifier MUST be "
                "denied — design/ writers are backend+frontend only.",
            )
            self.assertFalse(outcome.success)
            self.assertIn("design/competitor.png", outcome.error_message)

    def test_capture_webpage_rejects_default_screenshots_fallback(self):
        """Fallback path (no ``path`` supplied) writes to
        ``screenshots/<domain>.png``. ``screenshots/`` is READ-ONLY
        in ROUTING_TABLE → every agent must be denied. The gate's
        fallback handling surfaces ``screenshots/`` as the write
        target when ``path`` is absent."""
        for agent_id in ("frontend", "backend", "database", "verifier"):
            with self.subTest(agent_id=agent_id):
                with tempfile.TemporaryDirectory() as tmp:
                    agent = _make_agent(Path(tmp), agent_id)
                    outcome = agent._enforce_write_permissions(
                        "capture_webpage",
                        {"url": "https://example.com"},
                    )
                    self.assertIsNotNone(
                        outcome,
                        f"{agent_id} fallback-path capture_webpage "
                        f"must be denied — default screenshots/ "
                        f"target is read-only",
                    )
                    self.assertFalse(outcome.success)

    def test_capture_webpage_accepts_legit(self):
        """A ``frontend`` agent capturing a reference webpage into
        its own worktree (``app/frontend/refs/stripe.png``) is the
        legitimate use of the tool — the gate must NOT block."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = _make_agent(Path(tmp), "frontend")
            outcome = agent._enforce_write_permissions(
                "capture_webpage",
                {"url": "https://stripe.com",
                 "path": "app/frontend/refs/stripe.png"},
            )
            self.assertIsNone(
                outcome,
                "frontend capturing into its own app/frontend/* via "
                "capture_webpage must pass the gate cleanly",
            )


if __name__ == "__main__":
    unittest.main()
