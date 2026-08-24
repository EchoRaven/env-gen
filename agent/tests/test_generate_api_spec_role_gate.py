"""attempt-4 Phase 2 Fix B: GenerateAPISpecTool role-gate.

Reviewer 2 reframing: this is the *ownership-class* defect, not a
path-traversal one. Before this fix, ANY agent (frontend, design,
random_worker) could call ``generate_api_spec`` and have the tool
write to ``design/api_spec_generated.json`` (or, via the ``output=``
parameter, to ``design/spec.api.json`` directly). That violates the
Phase 1/2 ownership invariant: *backend owns spec.api*. Frontend
**consumes** it; design owns ``spec.ui.json``, NOT ``spec.api.json``.

The fix gates ``GenerateAPISpecTool.execute`` on ``self._agent_id``:

  * ``backend`` — allowed (intended caller; tool's docstring even says
    "Backend Agent should call this BEFORE finish()").
  * ``orchestrator`` + broad-writer agents (``worker``,
    ``analysis_worker``, ``review_worker``) — allowed as the admin /
    coordination override path, mirroring
    ``path_routed_workspace._BROAD_WRITERS``.
  * everyone else (``frontend``, ``design``, ``database``,
    ``verifier``, anonymous, ...) — denied with
    ``ToolResult(success=False, error_message=<role-denied>)`` BEFORE
    any file write happens.

The three tests pin the three behaviours the reviewer specifically
demanded: frontend blocked, design blocked, backend allowed,
orchestrator override allowed. A fifth test pins the unknown-caller
default-deny posture.

Tests run with the workspace pointed at a real Express-ish route
fixture so ``_extract_backend_routes`` returns at least one route — we
need the spec-write path to actually be reached when the role check
passes, otherwise the "backend allowed" assertion would be vacuous.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from workspace import Workspace  # noqa: E402
from tools.verification_tools import GenerateAPISpecTool  # noqa: E402


_FIXTURE_ROUTE_JS = """\
const express = require('express');
const router = express.Router();

router.get('/movies', (req, res) => { res.json({items: []}); });
router.get('/movies/:id', (req, res) => { res.json({item: {}}); });
router.post('/movies', (req, res) => { res.status(201).json({item: {}}); });

module.exports = router;
"""


def _make_workspace_with_routes(tmp: Path) -> Workspace:
    """Build a workspace whose ``app/backend/src/routes`` dir contains
    one parsable Express route file. We need ``_extract_backend_routes``
    to return non-empty so the post-role-check write path is reached.
    Otherwise the "backend allowed" test would pass even with the gate
    incorrectly returning early. """
    routes_dir = tmp / "app" / "backend" / "src" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    (routes_dir / "movies.js").write_text(_FIXTURE_ROUTE_JS, encoding="utf-8")
    return Workspace(tmp)


def _run(coro):
    """Drive an async coroutine to completion in the test thread."""
    return asyncio.run(coro)


class _StubAgent:
    """Minimal stand-in for an agent — only ``agent_id`` is read by
    ``GenerateAPISpecTool.set_agent``."""
    def __init__(self, agent_id: str):
        self.agent_id = agent_id


class TestGenerateAPISpecRoleGate(unittest.TestCase):
    """Pin the role-gate on ``GenerateAPISpecTool.execute``."""

    def test_frontend_blocked(self):
        """Frontend Agent must NOT be allowed to author spec.api.json
        (or its default ``api_spec_generated.json`` sibling). Frontend
        is the CONSUMER of the API spec; backend is the producer.
        Without this gate, any frontend prompt-injection could
        rewrite the backend contract under the frontend agent's
        credentials."""
        with tempfile.TemporaryDirectory() as td:
            ws = _make_workspace_with_routes(Path(td))
            tool = GenerateAPISpecTool(workspace=ws)
            tool.set_agent(_StubAgent("frontend"))

            result = _run(tool.execute())

            self.assertFalse(result.success, result)
            err = (result.error_message or "").lower()
            # Must mention role/permission/denied to be a clear gate signal.
            self.assertTrue(
                any(kw in err for kw in ("role", "permission", "denied")),
                f"expected role/permission/denied keyword in error, got: {result.error_message!r}",
            )
            # The output file must NOT have been written.
            out = Path(td) / "design" / "api_spec_generated.json"
            self.assertFalse(
                out.exists(),
                "GenerateAPISpecTool wrote spec file despite role denial",
            )

    def test_design_blocked(self):
        """Design Agent owns ``spec.ui.json``, NOT ``spec.api.json``.
        The Phase 1/2 ownership model splits API-vs-UI authorship
        between backend and design respectively. Even though
        ``design/`` is design's writable area, the API spec inside
        that directory is backend's content. The role-gate enforces
        the *content* ownership independently of the *path* ownership."""
        with tempfile.TemporaryDirectory() as td:
            ws = _make_workspace_with_routes(Path(td))
            tool = GenerateAPISpecTool(workspace=ws)
            tool.set_agent(_StubAgent("design"))

            # Even with an explicit ``output="design/spec.api.json"`` the
            # gate must trigger BEFORE the write attempt — the call is
            # role-denied regardless of which design-area path the caller
            # tries to clobber.
            result = _run(tool.execute(output="design/spec.api.json"))

            self.assertFalse(result.success, result)
            err = (result.error_message or "").lower()
            self.assertTrue(
                any(kw in err for kw in ("role", "permission", "denied")),
                f"expected role/permission/denied keyword in error, got: {result.error_message!r}",
            )
            spec_api = Path(td) / "design" / "spec.api.json"
            self.assertFalse(
                spec_api.exists(),
                "design agent was able to write spec.api.json — ownership invariant violated",
            )

    def test_backend_allowed(self):
        """Backend IS the intended caller (per the tool's own docstring:
        \"Backend Agent should call this BEFORE finish()\"). The gate
        must let backend through and produce a populated spec file."""
        with tempfile.TemporaryDirectory() as td:
            ws = _make_workspace_with_routes(Path(td))
            tool = GenerateAPISpecTool(workspace=ws)
            tool.set_agent(_StubAgent("backend"))

            result = _run(tool.execute())

            self.assertTrue(
                result.success,
                f"backend agent denied by role gate: {result.error_message!r}",
            )
            # File must actually be written so we know the post-gate
            # codepath ran.
            out = Path(td) / "design" / "api_spec_generated.json"
            self.assertTrue(
                out.exists(),
                f"backend was allowed by gate but spec file not produced at {out}",
            )
            # And contain >=1 of the fixture's three routes.
            self.assertGreaterEqual(result.data.get("total_routes", 0), 1)

    def test_orchestrator_allowed(self):
        """Orchestrator is the admin/coordinator override — mirrors
        ``_BROAD_WRITERS`` in path_routed_workspace. Pinned separately
        so a future refactor that narrows the allowed set to just
        ``{"backend"}`` is caught by review."""
        with tempfile.TemporaryDirectory() as td:
            ws = _make_workspace_with_routes(Path(td))
            tool = GenerateAPISpecTool(workspace=ws)
            tool.set_agent(_StubAgent("orchestrator"))

            result = _run(tool.execute())

            self.assertTrue(
                result.success,
                f"orchestrator denied by role gate: {result.error_message!r}",
            )
            out = Path(td) / "design" / "api_spec_generated.json"
            self.assertTrue(out.exists())

    def test_unknown_caller_denied(self):
        """Default posture is deny: a fresh tool instance with no
        ``set_agent`` call (empty ``_agent_id``) must be refused.
        This pins the "fail-closed" default against the historic
        "any agent can call this" bug. If the wiring (``set_agent`` /
        the setattr fallback in tooling.py:147-150) is ever broken,
        the tool stays safe rather than silently authoring on behalf
        of an unknown caller."""
        with tempfile.TemporaryDirectory() as td:
            ws = _make_workspace_with_routes(Path(td))
            tool = GenerateAPISpecTool(workspace=ws)
            # Note: deliberately no set_agent call.

            result = _run(tool.execute())

            self.assertFalse(
                result.success,
                "unknown caller was not denied — default posture is NOT fail-closed",
            )
            out = Path(td) / "design" / "api_spec_generated.json"
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
