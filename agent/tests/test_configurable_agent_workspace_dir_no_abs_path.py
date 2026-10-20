"""Sandbox principle pin #2: agent system-prompt's ``workspace_dir``
context variable must never carry the host's absolute base_dir prefix.

Background (smoke #24, post-Fix-#3):
    Fix #3 plugged the absolute-path leak in the codehub ``worktree_registered``
    event payload (the FIRST surface backend's inbox saw). Smoke #24 confirmed
    that fix live — orchestrator/backend/frontend all read ``path:
    "worktrees/<id>"`` from check_inbox. But backend STILL constructed every
    write as ``/tmp/envgen_demo/.../app/backend/...`` and path_routed_workspace
    denied them all.

Root cause:
    ``ConfigurableAgent._get_context_vars`` rendered
    ``workspace_dir = str(self.workspace.base_dir)`` — the host's absolute
    ``/tmp/envgen_demo/<project>/`` prefix — and the shared prompt template
    ``agents/shared/agent_definition_v3.j2:136`` embedded it as
    ``Workspace scope: `{{ workspace }}` `` in every agent's system prompt.
    Backend learned the host prefix at startup and joined it onto every
    relative path the kickoff briefing referenced.

Fix: hardcode ``"."`` (matches the macro's default; tool surface routes
relative paths through the routing table, so the agent never needs the
host prefix).

This test pins:
  - ``_get_context_vars()`` returns ``workspace_dir`` that does NOT start
    with ``/tmp/`` and does NOT equal the workspace's absolute base_dir.
"""

from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.agents.configurable_agent import ConfigurableAgent  # noqa: E402


class _StubWorkspace:
    """Minimal stand-in for ``self.workspace`` — only needs ``base_dir``."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir


def _make_bare_agent(base_dir: Path) -> ConfigurableAgent:
    """Bypass ConfigurableAgent.__init__ (heavy) and inject only the
    fields ``_get_context_vars`` reads: ``workspace``, ``_spawn_role``,
    ``_requested_agent_type``, ``gen_context``, ``_prompt_cfg``."""
    agent = object.__new__(ConfigurableAgent)
    agent.workspace = _StubWorkspace(base_dir)
    agent._spawn_role = None
    agent._requested_agent_type = None
    agent.gen_context = None
    agent._prompt_cfg = {}
    return agent


def leaks_host_temp_prefix_1203q0(ws_dir, temp_root=None):
    """Does `workspace_dir` carry the host temp prefix? (#1203q0)

    ONE OWNER, so the production assertion and its driver cannot disagree. The prefix was
    spelled `"/tmp/"` inline, which is true-by-accident under any other TMPDIR -- a leak of
    `/data/.../envgen_ctx_var_x/` sailed straight through it, and the suite is run with
    TMPDIR on a roomier filesystem whenever the root disk is tight. The first attempt at a
    driver for this did its own prefix arithmetic on synthetic strings instead of calling
    the code under test, so mutating the real prefix was MISSED twice.
    """
    root = (temp_root if temp_root is not None else tempfile.gettempdir()).rstrip("/") + "/"
    return str(ws_dir).startswith(root)


class TheLeakIsCaughtWhereverTempLives(unittest.TestCase):
    # #1203q0: the anti-leak assertion must not depend on temp being /tmp.
    #
    # The original spelling (startswith("/tmp/")) is true-by-accident under any other
    # TMPDIR, so it would pass while a /data/.../envgen_ctx_var_x/ leak sailed through.
    # The suite is run with TMPDIR on a roomier filesystem whenever the root disk is
    # tight, which makes that the normal case rather than the exception -- #1203pi's
    # family: an assertion that cannot fail is not an assertion.
    #
    # THIS CASE IS WHAT MAKES THE FIX VERIFIABLE. Reverting the prefix to the literal
    # "/tmp/" is behaviour-identical whenever temp happens to BE /tmp, so a mutation
    # would read MISSED and the fix would look untested.

    def test_a_leak_under_a_NON_tmp_temp_root_is_still_caught(self):
        # ★ Drives the OWNER, with the temp root moved off /tmp. Reverting the owner to a
        # hardcoded "/tmp/" makes this fail, which is what the earlier synthetic-string
        # version could not do.
        for root in ("/data/common/haibotong/tmp", "/var/folders/zz/T"):
            self.assertTrue(
                leaks_host_temp_prefix_1203q0(root + "/envgen_ctx_var_abc", temp_root=root),
                "a leak of the host temp root went undetected for root=%r" % root)
            self.assertFalse(
                leaks_host_temp_prefix_1203q0(".", temp_root=root),
                "the post-fix value '.' must never read as a leak")

    def test_the_production_assertion_CALLS_the_owner(self):
        """★ Structural, because it has to be. Re-spelling the prefix inline in the
        production test is behaviour-identical today -- `workspace_dir` is "." post-fix, so
        both spellings answer False -- which is why a mutation doing exactly that read
        MISSED. Only the parse tree can see "one owner" (#1032), the same lesson #1203ps
        learned about its predicate.
        """
        import inspect as _i
        src = _i.getsource(
            ConfigurableAgentWorkspaceDirNoAbsPath.test_workspace_dir_does_not_leak_abs_base_dir)
        tree = ast.parse(src.lstrip())
        called = {getattr(n.func, "id", "") for n in ast.walk(tree)
                  if isinstance(n, ast.Call)}
        self.assertIn("leaks_host_temp_prefix_1203q0", called,
                      "the production assertion stopped consulting the owner")
        spelled = [c.value for c in ast.walk(tree)
                   if isinstance(c, ast.Constant) and isinstance(c.value, str)
                   and c.value.startswith("/tmp")]
        self.assertEqual(spelled, [], spelled)

    def test_the_owner_defaults_to_the_LIVE_temp_root(self):
        real = tempfile.gettempdir
        tempfile.gettempdir = lambda: "/somewhere/else"
        try:
            self.assertTrue(
                leaks_host_temp_prefix_1203q0("/somewhere/else/envgen_x"),
                "the default path ignored tempfile.gettempdir()")
            self.assertFalse(leaks_host_temp_prefix_1203q0("/tmp/envgen_x"),
                             "it is still hardcoded to /tmp")
        finally:
            tempfile.gettempdir = real

    def test_unused_legacy_case(self):
        # A SYNTHETIC root, not a real TemporaryDirectory: the first version of this used
        # `tempfile.TemporaryDirectory(prefix="q0_root_")`, which creates its directory
        # INSIDE the current temp root -- so under the default TMPDIR the "alternative"
        # root was `/tmp/q0_root_xxxx`, still under /tmp, and this test's own guard caught
        # it. Only the prefix arithmetic is under test here, so no directory is needed.
        for alt in ("/data/common/haibotong/tmp", "/var/folders/zz/T"):
            real = tempfile.gettempdir
            tempfile.gettempdir = lambda: alt
            try:
                prefix = tempfile.gettempdir().rstrip("/") + "/"
                self.assertFalse(
                    prefix.startswith("/tmp/"),
                    "the fixture failed to move the temp root off /tmp")
                leaked = prefix + "envgen_ctx_var_abc/"
                self.assertTrue(
                    leaked.startswith(prefix),
                    "the derived prefix no longer matches its own temp root")
                self.assertFalse(
                    leaked.startswith("/tmp/"),
                    "this leak is exactly what the /tmp/ spelling cannot see")
            finally:
                tempfile.gettempdir = real


class ConfigurableAgentWorkspaceDirNoAbsPath(unittest.TestCase):
    """Smoke #24 follow-on: plug the prompt-template leak at source."""

    def test_workspace_dir_does_not_leak_abs_base_dir(self):
        """``_get_context_vars()['workspace_dir']`` must NOT carry the
        host's absolute base_dir prefix. Pre-fix this returned
        ``str(self.workspace.base_dir)``. Post-fix it is ``"."``."""
        with tempfile.TemporaryDirectory(prefix="envgen_ctx_var_") as td:
            base = Path(td)
            agent = _make_bare_agent(base)
            ctx = agent._get_context_vars()

            ws_dir = ctx["workspace_dir"]
            # #1203q0: the host temp ROOT, not the literal "/tmp/". This assertion exists to
            # catch `workspace_dir` leaking the host prefix, and it was spelled against
            # `/tmp/` -- so under any other TMPDIR it is true no matter what, and a leak of
            # `/data/.../envgen_ctx_var_x/` would sail through it. Not academic: the suite is
            # run with TMPDIR on a roomier filesystem whenever the root disk is tight, which
            # makes the weakening the normal case. Exactly one other test in this suite
            # already derives the prefix this way (#1202xr); the sibling
            # `test_codehub_worktree_event_no_absolute_path` survives only because it ORs the
            # hardcoded prefix with the real repo root.
            self.assertFalse(
                leaks_host_temp_prefix_1203q0(ws_dir),
                f"workspace_dir leaks the host temp prefix "
                f"{tempfile.gettempdir()!r}: {ws_dir!r}. "
                f"Agent system prompt would render 'Workspace scope: "
                f"`{ws_dir}`' and the agent would join the prefix onto "
                f"every relative path in its briefing.",
            )
            self.assertNotEqual(
                ws_dir, str(base),
                f"workspace_dir equals absolute base_dir ({base!r}) — "
                f"the sandbox principle is broken. From the agent's POV "
                f"workspace root must be `/` (or `.`), not the host's "
                f"absolute prefix.",
            )

    def test_workspace_dir_falls_back_when_no_workspace(self):
        """If ``self.workspace`` is None (rare, e.g. test stubs),
        the fallback should still be a safe sentinel, not raise."""
        agent = object.__new__(ConfigurableAgent)
        agent.workspace = None
        agent._spawn_role = None
        agent._requested_agent_type = None
        agent.gen_context = None
        agent._prompt_cfg = {}
        ctx = agent._get_context_vars()
        ws_dir = ctx["workspace_dir"]
        self.assertFalse(
            ws_dir.startswith("/tmp/") or ws_dir.startswith("/"),
            f"workspace_dir fallback should not be absolute: {ws_dir!r}",
        )

    def test_workspace_dir_exact_value_pin(self):
        """Exact pin: the value is ``"."`` — matches the j2 macro's
        default (``workspace_dir="."``)."""
        with tempfile.TemporaryDirectory(prefix="envgen_ctx_var_") as td:
            agent = _make_bare_agent(Path(td))
            ctx = agent._get_context_vars()
            self.assertEqual(ctx["workspace_dir"], ".")


if __name__ == "__main__":
    unittest.main()
