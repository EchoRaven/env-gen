"""PROPOSAL #30 (S1 + S2 + S4) — close the remaining structural blockers from run #28.

S1: the STATUS finish-gate (kickoff_endpoints_implemented) must skip the FRAMEWORK-owned
    fixed surface via the canonical lifecycle.is_business ({auth,oauth,infra,spine}) — NOT
    a copied kind literal (which missed oauth). The tenant control-plane (kind=infra,
    provider=backend) was counted against the backend → it was told to implement framework
    endpoints → deadlock. The code gate is converged onto is_business too.
S2: get_skill is force-offered in the orchestrator's `action` always-include so the
    release_readiness_consulted gate on deliver_project is satisfiable (run #28: the ranker
    crowded get_skill out → deliver_project blocked 33×).
S4: agent-visible file errors are workspace-relative — the lock-timeout message no longer
    leaks the absolute host path; _redact_ws strips the workspace root from exceptions.

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.agents.runtime.preconditions import kickoff_endpoints_implemented  # noqa: E402


def _agent(endpoints):
    rh = SimpleNamespace(get_endpoints=lambda: endpoints)
    return SimpleNamespace(_hubs=SimpleNamespace(registryhub=rh),
                           _config_key="backend", agent_id="backend")


class S1StatusGateSkipsFrameworkKinds(unittest.TestCase):
    def test_framework_kinds_do_not_block_backend_finish(self):
        # the tenant control-plane: provider=backend, kind=infra/oauth, status=defined.
        # These must NOT block the backend's finish (they're framework-owned).
        eps = {
            "POST /api/v1/admin/init-tenant": {"method": "POST", "path": "/api/v1/admin/init-tenant",
                                               "provider": "backend", "kind": "infra", "status": "defined"},
            "POST /oauth/token": {"method": "POST", "path": "/oauth/token",
                                  "provider": "backend", "kind": "oauth", "status": "defined"},
            "GET /api/users": {"method": "GET", "path": "/api/users",
                               "provider": "backend", "kind": "auth", "status": "defined"},
        }
        self.assertIsNone(kickoff_endpoints_implemented(_agent(eps), "finish", {}),
                          "framework-owned (infra/oauth/auth/spine) endpoints must not block finish")

    def test_real_business_endpoint_still_blocks(self):
        eps = {"GET /api/notes": {"method": "GET", "path": "/api/notes",
                                  "provider": "backend", "status": "defined"}}  # no fixed kind → business
        msg = kickoff_endpoints_implemented(_agent(eps), "finish", {})
        self.assertIsNotNone(msg, "a real un-implemented business endpoint must still block")
        self.assertIn("/api/notes", msg)

    def test_metadata_nested_kind_respected(self):
        # is_business reads kind OR metadata.kind — a metadata-nested infra must skip
        eps = {"POST /api/v1/reset": {"method": "POST", "path": "/api/v1/reset",
                                      "provider": "backend", "metadata": {"kind": "infra"},
                                      "status": "defined"}}
        self.assertIsNone(kickoff_endpoints_implemented(_agent(eps), "finish", {}))

    def test_uses_canonical_is_business(self):
        src = inspect.getsource(kickoff_endpoints_implemented)
        self.assertIn("is_business", src)


class S2GetSkillForceOffered(unittest.TestCase):
    def test_get_skill_in_action_always_include(self):
        from multi_agent.agents.base import EnvGenAgent
        # the orchestrator runs a single `action` stage with no allowlist — `action`
        # is the load-bearing key (a deliver-only edit would be a no-op for it).
        self.assertIn("get_skill", EnvGenAgent.ACTION_STAGE_ALWAYS_INCLUDE["action"])
        self.assertIn("get_skill", EnvGenAgent.ACTION_STAGE_ALWAYS_INCLUDE["deliver"])

    def test_get_skill_survives_knowledge_fetch_subtraction(self):
        # Membership in ACTION_STAGE_ALWAYS_INCLUDE is necessary but NOT sufficient:
        # action.py subtracts KNOWLEDGE_FETCH_TOOL_NAMES (which CONTAINS get_skill)
        # from the candidate pool BEFORE ranking, and tool_surface only keeps
        # always_include tools that are still in the pool — so the force-offer was
        # silently nullified and deliver_project deadlocked (smoke run #6). This
        # exercises the real subtraction expression: the stage's force-offer set is
        # exempt from the knowledge-fetch subtraction.
        from multi_agent.agents.base import EnvGenAgent
        KNOWLEDGE_FETCH_TOOL_NAMES = EnvGenAgent.KNOWLEDGE_FETCH_TOOL_NAMES
        for stage in ("deliver", "action"):
            _force_offer = set(EnvGenAgent.ACTION_STAGE_ALWAYS_INCLUDE.get(stage, set()))
            if (stage in set(getattr(EnvGenAgent, "ACTION_INTERNAL_STAGES", ()) or ())
                    and stage != "action"):
                _force_offer |= set(EnvGenAgent.ACTION_STAGE_ALWAYS_INCLUDE.get("action", set()))
            # the orchestrator's granted pool includes get_skill + other knowledge tools
            candidate = {"get_skill", "query_knowledge", "read_memory_bank",
                         "deliver_project", "deliverability_check", "finish"}
            candidate -= ((KNOWLEDGE_FETCH_TOOL_NAMES - _force_offer))  # the fixed expr
            self.assertIn("get_skill", candidate,
                          f"get_skill must survive the subtraction for stage {stage}")
            # non-force-offered knowledge tools are still removed
            self.assertNotIn("query_knowledge", candidate)
            self.assertNotIn("read_memory_bank", candidate)
            # delivery tools (never knowledge tools) are unaffected
            self.assertIn("deliver_project", candidate)


class S4NoAbsolutePathLeak(unittest.TestCase):
    def test_lock_timeout_message_has_no_abs_path(self):
        from tools.file_tools import _FileLock
        src = inspect.getsource(_FileLock.__enter__)
        # the redacted raise must not interpolate the lock path
        self.assertNotIn("{self._lock_path}", src)
        self.assertIn("file busy", src)

    def test_redact_ws_strips_workspace_root(self):
        from tools.canonical_file_tools.shared import _redact_ws
        ws = SimpleNamespace(base_root="/data/common/haibotong/forgingground-gen/generated/x/worktrees/backend")
        e = OSError("[Errno 2] No such file: /data/common/haibotong/forgingground-gen/generated/x/worktrees/backend/app/main.py")
        red = _redact_ws(ws, e)
        self.assertNotIn("/data/common/haibotong", red)
        self.assertIn("<workspace>", red)


if __name__ == "__main__":
    unittest.main()
