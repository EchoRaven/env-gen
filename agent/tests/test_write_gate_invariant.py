"""Phase 0.2 attempt-3 STEP 1: Write-gate invariant.

Caveat (R2 round-4): this invariant catches tools that NEVER CALL
``is_write_allowed`` (or never route through ``GATED_TOOL_NAMES``).
It does NOT catch tools that call ``is_write_allowed`` but ignore
its result, or call it on a different path than the one eventually
written. Detecting that requires data-flow + return-value-honoring
analysis which is statically undecidable in Python. Defense-in-depth:
every Tool added to ``EXPECTED_ALLOWLIST`` gets a code-review check
on the gate-honoring path, and the matched-expression check inside
``has_is_write_allowed_call`` (PHASE 3 FIX #3) raises the bar for
"any is_write_allowed call counts" to "the gate must guard the same
path expression that is actually written".

Authoritative count (R1 round-4): ``EXPECTED_ALLOWLIST`` currently
has **29 entries** (was reported as 27 in attempt-4's commit log —
two CodeHub wrappers were added later in attempt-5 FIX D and the
log was not corrected). Keep this comment in sync with
``len(EXPECTED_ALLOWLIST)`` after every edit.

Why this test exists
====================

Phase 0.2 attempt-2 hand-enumerated the tool names that
``AgentTooling._enforce_write_permissions`` (in
``multi_agent/agents/runtime/tooling.py``) consults when extracting
``write_targets`` to feed into ``workspace.is_write_allowed``. That set
is currently::

    {"write", "delete_file", "edit", "apply_patch", "copy_reference_image"}

Two independent reviewers (Reviewer 1 and Reviewer 2) found tools that
write to the filesystem (or invoke hub-level write primitives) but
whose ``NAME`` is **not** in that set and do **not** call
``is_write_allowed`` themselves. The runtime gate is therefore a
denylist-by-omission: every new write-capable tool that someone adds is
silently un-gated until the next audit notices.

The reviewer's structural insight is the spec for this test:

    "the durable fix is not 'add 2 tools to the set'. This is the third
    time a hand-enumerated gate forgot a member. Make it an invariant:
    derive 'tools that write' structurally and add a test asserting
    every writing tool routes through is_write_allowed. Otherwise the
    next tool re-opens it."

How the invariant works
=======================

For every ``BaseTool`` (or ``HubTool``) subclass under
``env_generator/llm_generator/tools/**/*.py`` we ask, via Python's
``ast`` module:

  Q1. Does this tool *write to the filesystem* from its ``execute()``
      (or any helper defined in the same class / module)? Heuristics:

        * ``write_text`` / ``write_bytes`` / ``touch`` / ``unlink`` /
          ``rmdir`` / ``rename`` / ``replace`` / ``mkdir`` called on
          any expression.
        * ``open(...)`` with a mode argument containing
          ``"w"``/``"a"``/``"x"`` (with optional ``"b"``).
        * ``shutil.copy``/``copy2``/``copyfile``/``copytree``/
          ``move``/``write``.
        * ``os.rename``/``replace``/``link``/``symlink``/``makedirs``/
          ``remove``/``unlink``.
        * Internal write helpers: ``_atomic_write_text`` /
          ``atomic_write_text`` / ``_write_with_lint_guard`` /
          ``write_workspace_file`` / ``_move_to_trash``.
        * Hub-level write primitives: ``codehub.commit``,
          ``codehub.commit_for_agent``, ``codehub.merge_pull_request``,
          ``codehub.force_merge_pull_request``,
          ``codehub.resolve_conflict``, ``codehub.create_release``,
          ``codehub.record_commit``, ``codehub.open_pull_request``.
        * Git staging helpers: ``git.add`` / ``git_ops.add``.

  Q2. Does the write path provably route through the role-write gate?
      A tool counts as GATED iff any of these is true:

        a) The tool's ``NAME`` constant equals one of the names
           recognised by ``_enforce_write_permissions`` (see
           ``GATED_TOOL_NAMES`` below) AND the tool exposes a
           ``file_path`` / ``path`` / ``destination`` parameter that
           the gate can read.
        b) The tool's ``execute()`` (or a same-class helper) makes a
           direct ``is_write_allowed`` call AND the path expression
           passed to ``is_write_allowed`` matches one of the path
           expressions actually written.
        c) The tool delegates its write entirely to another tool whose
           ``NAME`` is in ``GATED_TOOL_NAMES`` (e.g. a wrapper that
           forwards to ``write`` / ``edit``).

Note: routing through ``workspace.resolve()`` is **not** sufficient.
``PathRoutedWorkspace.resolve()`` enforces *containment* (the path
must land inside the worktree or a known base prefix) but NOT
*role permission* (whether THIS agent may write THIS prefix). The
gate that fires the role check is ``is_write_allowed``. Reviewer 1
explicitly called this out: UpdateJsonPathTool / UpdateYamlPathTool
both call ``_resolve_workspace_path`` (which calls
``workspace.resolve``) and yet bypass the role gate.

Blindspots closed in PHASE 3 (2026-05-29)
=========================================

PHASE 3 hardened the scanner against five blindspots that Reviewer 2
flagged on the PHASE 2 scanner, plus two methodology nits from
Reviewer 1:

  #2 (Reviewer 2): Module-level helper following. A tool that called a
     module-level ``def _save(p, data): p.write_text(...)`` was
     silently judged "doesn't write" because the scanner only walked
     the Tool class body. FIX: build a module-wide map of function
     defs and, when the in-class scanner sees a call to a same-module
     function, transitively merge the callee's write sites in.

  #3 (Reviewer 2): ``is_write_allowed`` "exists" check was loose. The
     gate-detection used to look for ANY ``is_write_allowed`` call
     somewhere in the class — so a tool that gated path ``A`` but
     wrote to path ``B`` was scored as gated. FIX: track the
     expression text passed to ``is_write_allowed`` and require it to
     match (string-equal, post normalisation) at least one expression
     actually written. If no overlap, treat as bypass.

  #4 (Reviewer 2 + Reviewer 1 nit): ``cond(a)`` misuse. The docstring
     said ``cond(a) = NAME-in-set AND has-path-param`` but the code
     dropped the second conjunct. FIX: re-apply the AND. Tools whose
     NAME is gated but expose no path-like arg are now flagged.

  #5 (Reviewer 2): Alias resolution. Codehub/git detection required a
     literal ``.codehub.X`` chain; an alias like
     ``ch = self._hubs.codehub; ch.commit()`` was missed. FIX: when
     scanning a method, build a local map of Assign targets to RHS
     attribute chains and resolve aliases before classifying a call.

  #6 (Reviewer 2): ``Path.replace`` is a rename (move/write). FIX:
     add ``replace`` to ``WRITE_METHODS``. ``str.replace`` produces
     false-positives, but per the test's "over-flag is OK" policy
     that's acceptable; allowlist any genuine string-substitution
     callsite if it ever surfaces.

  Methodology nit (Reviewer 1): ``has_file_path_param`` was computed
  but unused in ``is_gated`` — now wired in per #4. Also: per
  ``is_write_allowed`` detection is class-scoped, which may
  false-positive when a same-class helper named ``foo`` reuses a
  module-level ``is_write_allowed`` from a different code path; the
  test's over-flag-is-OK posture means this is acceptable.

Allowlist
=========

``EXPECTED_ALLOWLIST`` documents the tools that legitimately write to
non-role-gated paths (e.g. a tool that creates a temp file outside the
workspace and immediately deletes it). Every entry MUST cite
``file:line`` and a one-line justification. Anything not in the
allowlist OR not gated will fail this test. PHASE 5 (separate
follow-up) is where the actual allowlist entries are authored.

Failure mode
============

The test is structural — it does NOT execute any tool. It reads the
source tree, parses each tool with ``ast``, and asserts the invariant.
False-positive bias is acceptable: if a tool is over-flagged, the fix
author can either (i) make the tool route through the gate or (ii) add
the tool to ``EXPECTED_ALLOWLIST`` with a justification comment.
"""

from __future__ import annotations

import ast
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "env_generator" / "llm_generator" / "tools"

# Tool NAMEs that ``AgentTooling._enforce_write_permissions``
# recognises — i.e. tool calls whose arguments the runtime gate will
# extract paths from and run through ``is_write_allowed``. Kept in
# sync with ``multi_agent/agents/runtime/tooling.py`` lines 244-259.
#
# Phase 0.2 attempt-3 FIX A (2026-05-29): ``update_json_path`` and
# ``update_yaml_path`` joined this set after Reviewer 1 confirmed both
# tools rewrote files (via ``_atomic_write_text``) but skipped the
# role-write gate. They expose a ``path`` argument that the gate's
# ``file_path``-or-``path`` extraction picks up; no further plumbing
# needed inside the tools.
#
# Phase 0.2 attempt-4 PHASE 2 FIX A (2026-05-29): ``generate_seed_sql``,
# ``save_image``, and ``capture_webpage`` joined this set after PHASE 1
# AUDIT A confirmed they are FULLY_AGENT_CONTROLLED writes.
# ``generate_seed_sql`` is HIGH severity (bypasses workspace.resolve()
# entirely, accepts absolute paths verbatim — same traversal class as
# the Phase 0.2 RCE). The other two are MEDIUM (workspace.resolve()
# contains escape, but no per-agent role gate). ``generate_seed_sql``
# uses an ``output_file`` parameter (not ``path``), which the gate
# extracts via the explicit ``output_file`` fallback now wired in
# ``_enforce_write_permissions``.
GATED_TOOL_NAMES: Set[str] = {
    "write",
    "delete_file",
    "edit",
    "apply_patch",
    "copy_reference_image",
    "update_json_path",
    "update_yaml_path",
    "generate_seed_sql",
    "save_image",
    "capture_webpage",
}

# Methods/functions whose call on Path / file objects constitutes a
# filesystem write.
#
# PHASE 3 FIX #6 (2026-05-29): ``replace`` is now included. Reviewer 2
# pointed out that ``Path.replace(target)`` is a rename / move and was
# silently passing the gate. ``str.replace`` (substring substitution)
# will produce some false positives here, but the test's over-flag-is-OK
# posture means we can allowlist any genuine string-substitution
# callsite if it ever surfaces (with a justification).
WRITE_METHODS: Set[str] = {
    # Path / file objects
    "write_text",
    "write_bytes",
    "touch",
    "unlink",
    "rmdir",
    "rename",
    "replace",
    "mkdir",
    # Internal write helpers (atomic, lint-guarded)
    "_atomic_write_text",
    "atomic_write_text",
    "_write_with_lint_guard",
    "write_workspace_file",
    "_move_to_trash",
}

# shutil/os module-level write functions, matched as `shutil.X` /
# `os.X` attribute calls.
SHUTIL_WRITE_FNS: Set[str] = {
    "copy", "copy2", "copyfile", "copytree", "move", "write",
}
OS_WRITE_FNS: Set[str] = {
    "rename", "replace", "link", "symlink", "makedirs",
    "remove", "unlink", "rmdir",
}

# CodeHub-level write primitives. Calls to ``self._hubs.codehub.X(...)``
# (or any ``.codehub.X`` chain) where X is in this set count as a write.
CODEHUB_WRITE_METHODS: Set[str] = {
    "commit",
    "commit_for_agent",
    "merge_pull_request",
    "force_merge_pull_request",
    "resolve_conflict",
    "create_release",
    "record_commit",
    "open_pull_request",
    "revert_commit",
}

# Git-staging helpers — `self.git.add(...)`, `git_ops.add(...)`.
GIT_STAGE_METHODS: Set[str] = {"add", "stage"}

# Files to skip entirely (utilities, not tool implementations).
SKIP_FILES: Set[str] = {
    "_base.py",
    "path_utils.py",
    "__init__.py",
}

# Tools that legitimately write outside the role-gated workspace.
# Each entry MUST cite file:line and a one-line justification.
# Anything not in this list and not gated will FAIL this test —
# that is the structural fix per Reviewer 1.
EXPECTED_ALLOWLIST: Dict[str, str] = {
    # ------------------------------------------------------------------
    # PHASE 5 ALLOWLIST (attempt-4)
    #
    # Each entry MUST cite file:line for the tool AND (a) the file:line
    # of the actual enforcement it relies on, or (b) an explicit
    # statement that there is NO gate AND why that is safe by design.
    # Do not paper over a missing gate with vague prose — if the gate is
    # missing, that's a bug, not an allowlist entry.
    # ------------------------------------------------------------------

    # ============================================================
    # AST FALSE POSITIVES — ``str.replace(...)`` (substring), not
    # ``Path.replace(...)`` (rename). The invariant test deliberately
    # over-flags ``replace`` because it has no type information at AST
    # time — these are the audited false positives. None of these tools
    # perform any filesystem write at the cited line; only string
    # substitution.
    # ============================================================

    "PreviewDatasetTool": (
        "FALSE POSITIVE — env_generator/llm_generator/tools/data_engine_tools.py:263. "
        "The flagged ``replace`` at data_engine_tools.py:428 is "
        "``dataset_id.split('/')[-1].replace('-', ' ').replace('_', ' ')`` — "
        "``str.replace`` for query normalisation in the not-found "
        "remediation branch. PreviewDatasetTool performs no filesystem write."
    ),

    "DockerBuildTool": (
        "FALSE POSITIVE — env_generator/llm_generator/tools/docker_tools.py:193. "
        "The flagged ``replace`` callsites at docker_tools.py:156/176/182/187 "
        "are all ``str.replace('_', '-')`` inside the module-level helper "
        "``_resolve_service_name`` (service-name alias normalisation). "
        "DockerBuildTool itself only runs ``docker-compose build`` via "
        "subprocess; no filesystem write."
    ),

    "DockerUpTool": (
        "FALSE POSITIVE — env_generator/llm_generator/tools/docker_tools.py:309. "
        "Same shared module-helper ``_resolve_service_name`` "
        "(docker_tools.py:156/176/182/187, ``str.replace`` for alias "
        "normalisation). DockerUpTool only runs ``docker-compose up``."
    ),

    "DockerLogsTool": (
        "FALSE POSITIVE — env_generator/llm_generator/tools/docker_tools.py:492. "
        "Same shared module-helper ``_resolve_service_name`` "
        "(docker_tools.py:156/176/182/187, ``str.replace``). DockerLogsTool "
        "only reads container logs."
    ),

    "DockerRestartTool": (
        "FALSE POSITIVE — env_generator/llm_generator/tools/docker_tools.py:642. "
        "Same shared module-helper ``_resolve_service_name`` "
        "(docker_tools.py:156/176/182/187, ``str.replace``). DockerRestartTool "
        "only runs ``docker-compose restart``."
    ),

    "ViewImageTool": (
        "FALSE POSITIVE — env_generator/llm_generator/tools/file_tools.py:835. "
        "The flagged ``replace`` at file_tools.py:903/907 is "
        "``filename.replace(' ', '').lower()`` in ``_fuzzy_match_file`` for "
        "filename normalisation. ViewImageTool only reads images (passes "
        "through ``_resolve_workspace_path`` with ``must_exist=False, "
        "expect_file=True``)."
    ),

    "LogoSearchTool": (
        "FALSE POSITIVE — env_generator/llm_generator/tools/image_search_tools.py:367. "
        "The flagged ``replace`` at image_search_tools.py:459 is "
        "``domain.replace('https://', '').replace('http://', '').replace('www.', '')`` — "
        "URL/domain string cleanup for the logo-API query. LogoSearchTool "
        "does not write to the filesystem (it returns a logo URL/blob to "
        "the caller; downloads go through gated save_image)."
    ),

    "ListMCPToolsTool": (
        "FALSE POSITIVE — env_generator/llm_generator/tools/mcp_tools.py:546. "
        "The flagged ``replace`` at mcp_tools.py:602 is "
        "``path.replace('/api/', '').split('/')`` — substring extraction for "
        "the entity-grouping pass. ListMCPToolsTool only generates an "
        "in-memory recommendation list; no filesystem write."
    ),

    "PlanTool": (
        "FALSE POSITIVE — env_generator/llm_generator/tools/reasoning_tools.py:318. "
        "The flagged ``replace`` callsites at reasoning_tools.py:1827/1832/1839 "
        "are ``task_id.strip().lower().replace('-', '_')`` and the "
        "matching dict comprehension in ``_resolve_task_id`` (fuzzy task-id "
        "lookup). PlanTool mutates in-memory plan state; no filesystem write."
    ),

    "ExecuteBashTool": (
        "FALSE POSITIVE — env_generator/llm_generator/tools/runtime_tools.py:709. "
        "The flagged ``replace`` callsites at runtime_tools.py:810/1014/1020/1033 "
        "are all ``str.replace``: Unicode-punctuation normalisation in "
        "``_normalize_shell_command`` (810), python→python3 rewrites "
        "(1014/1020), and ``sudo`` → ``sudo -n`` rewriting (1033). "
        "ExecuteBashTool itself doesn't write files (it shells out to the "
        "user-supplied command which goes through the bash policy gate "
        "elsewhere — see runtime_tools BashCommandPolicy)."
    ),

    "DefineTaskTool": (
        "FALSE POSITIVE — env_generator/llm_generator/tools/task_definition_tools.py:184. "
        "The flagged ``replace`` at task_definition_tools.py:315 is "
        "``str(task.get('name')).strip().lower().replace(' ', '_')`` — "
        "auto-id-from-name normalisation. DefineTaskTool only appends to "
        "an in-memory ``self._tasks`` list; the filesystem write is the "
        "job of SaveTaskSuiteTool."
    ),

    "VerifyAPIContractTool": (
        "FALSE POSITIVE — env_generator/llm_generator/tools/verification_tools.py:315. "
        "The flagged ``replace`` callsites at verification_tools.py:593/774 are "
        "``full_path.replace('//', '/')`` (route-path normalisation, line 593) "
        "and ``path.replace('${', ':').replace('}', '')`` (template-literal "
        "stripping, line 774). VerifyAPIContractTool only READS backend "
        "routes, frontend api.js, and the spec file; no filesystem write."
    ),

    "AnalyzeImageTool": (
        "FALSE POSITIVE — env_generator/llm_generator/tools/vision_tools.py:152. "
        "The flagged ``replace`` callsites at vision_tools.py:78/82 are "
        "``filename.replace(' ', '').lower()`` and ``file.name.replace(' ', '').lower()`` "
        "in the module-level helper ``_fuzzy_match_filename`` (filename "
        "normalisation). AnalyzeImageTool only calls the vision model on an "
        "image it reads from disk; no filesystem write."
    ),

    "CompareWithScreenshotTool": (
        "FALSE POSITIVE — env_generator/llm_generator/tools/vision_tools.py:322. "
        "Same shared module-helper ``_fuzzy_match_filename`` "
        "(vision_tools.py:78/82, ``str.replace`` for filename normalisation). "
        "CompareWithScreenshotTool only reads two images and calls the "
        "vision model; no filesystem write."
    ),

    "ExtractComponentsTool": (
        "FALSE POSITIVE — env_generator/llm_generator/tools/vision_tools.py:409. "
        "Same shared module-helper ``_fuzzy_match_filename`` "
        "(vision_tools.py:78/82, ``str.replace`` for filename normalisation). "
        "ExtractComponentsTool only reads an image and returns extracted "
        "components; no filesystem write."
    ),

    # ============================================================
    # REAL WRITES — workspace-fixed literal paths, not agent-controlled
    # ============================================================

    "BrowserScreenshotTool": (
        "WORKSPACE-FIXED — env_generator/llm_generator/tools/browser/core.py:107. "
        "The screenshot save path is either (a) the caller-supplied "
        "``save_path`` re-rooted via ``browser.resolve_path(save_path)`` "
        "(core.py:162) which delegates to workspace.resolve and cannot "
        "escape ``base_root``, or (b) a default into the per-workspace "
        "``screenshot_dir`` (core.py:166-167). HONEST CAVEAT: there is NO "
        "per-agent role gate today — any role with access to a browser "
        "can drop a PNG into the workspace's screenshots/ tree, including "
        "into another role's area when ``save_path`` is supplied "
        "explicitly. This is accepted because (i) the file is a PNG "
        "(no code-exec surface from the write itself), (ii) the path is "
        "workspace-contained, and (iii) browser tools are only attached "
        "to design/frontend/orchestrator who are the roles with "
        "legitimate need to capture references. If we later expose "
        "browsers to backend/database, REVISIT this allowlist."
    ),

    "LintTool": (
        "INTERNAL SCAFFOLDING — env_generator/llm_generator/tools/code_tools.py:234. "
        "The flagged ``write_text`` at code_tools.py:471 writes a literal "
        "minimal ``eslint.config.js`` to ``project_dir`` (computed from the "
        "linted file's parent directory) when no existing config is found "
        "(code_tools.py:430-436). The path is derived from the file being "
        "linted, not from agent input. The content is a hard-coded "
        "literal Node/JS config (code_tools.py:437-468) with no agent-"
        "controlled bytes. NO role gate by design — linting is read-only "
        "from the agent's perspective and the config write is invisible "
        "scaffolding; eslint refuses to run without a config."
    ),

    "DockerValidateTool": (
        "WORKSPACE-FIXED — env_generator/llm_generator/tools/docker_tools.py:712. "
        "The flagged ``open('w')`` at docker_tools.py:860 writes back to "
        "``compose_file``, which is the literal ``docker-compose.yml`` "
        "located via ``_find_compose_file_global(self.workspace.base_root)`` "
        "(docker_tools.py:754). Path is workspace-fixed and not agent-"
        "controllable. The write only happens when the caller passes "
        "``fix=True`` AND the tool itself detected wrong-relative-path "
        "issues to auto-fix (line 858). HONEST CAVEAT: there is no "
        "per-agent role gate — any role that can call docker_validate "
        "with ``fix=True`` can rewrite the compose file's build "
        "context paths. This is accepted because the tool is only "
        "attached to orchestrator/runtime roles per the role manifest, "
        "and the rewrite is strictly limited to the build.context "
        "field (line 809/811) — it cannot inject arbitrary content."
    ),

    "DefineActionSpaceTool": (
        "WORKSPACE-FIXED — env_generator/llm_generator/tools/task_definition_tools.py:42. "
        "Writes to ``self.output_dir / 'tasks' / 'action_space.yaml'`` "
        "(task_definition_tools.py:163-166) — a literal path under the "
        "tool-owned ``output_dir`` (configured at tool construction, not "
        "agent input). The flagged ``replace`` at line 27 is "
        "``str(output_path.relative_to(...)).replace('\\\\', '/')`` "
        "(Windows path normalisation in the hub-sync helper "
        "``_sync_task_file_to_hub``) — false-positive str.replace. "
        "DefineActionSpaceTool is exclusively wired to the task-generation "
        "role per AUDIT A; not exposed to other agents."
    ),

    "SaveTaskSuiteTool": (
        "WORKSPACE-FIXED — env_generator/llm_generator/tools/task_definition_tools.py:349. "
        "Writes to ``self.output_dir / 'tasks' / 'tasks.yaml'`` "
        "(task_definition_tools.py:398-401) — a literal path under the "
        "tool-owned ``output_dir``. The flagged ``replace`` at line 27 is "
        "the same str.replace inside ``_sync_task_file_to_hub`` (Windows "
        "path normalisation). Same role-scoping argument as "
        "DefineActionSpaceTool (task-generation role only)."
    ),

    "ExecuteTaskSuiteTool": (
        "WORKSPACE-FIXED — env_generator/llm_generator/tools/task_suite_executor.py:28. "
        "Writes per-task reports to ``workspace.resolve('tasks/execution_results') "
        "/ f'{task_id}.json'`` (task_suite_executor.py:1193-1196). The "
        "directory is a literal workspace-relative path; the filename is "
        "derived from ``task_id`` which is loaded from the validated "
        "tasks.yaml on disk, not from real-time agent input. "
        "workspace.resolve enforces base_root containment. HONEST CAVEAT: "
        "no per-agent role gate; relies on the role-manifest only wiring "
        "execute_task_suite to the task-execution role."
    ),

    "GenerateAPISpecTool": (
        "ROLE-GATED AT METHOD-LAYER — env_generator/llm_generator/tools/verification_tools.py:1039. "
        "Has an in-tool role gate at verification_tools.py:1131-1143 (Phase "
        "2 Fix B): rejects callers whose ``agent_id`` is not in "
        "``_ALLOWED_AGENTS = {backend, orchestrator, worker, "
        "analysis_worker, review_worker}`` BEFORE the file write. Fail-"
        "closed default: empty/unknown agent_id is denied. The AST "
        "scanner does not recognise this role-gate pattern (it only knows "
        "about ``is_write_allowed`` and ``GATED_TOOL_NAMES`` membership), "
        "so the tool is allowlisted explicitly. Pinned by "
        "tests/test_generate_api_spec_role_gate.py (5 tests)."
    ),

    # ============================================================
    # CODEHUB WRAPPERS — each wrapper is a thin one-liner that calls
    # the corresponding ``codehub.X`` method, which performs the
    # enforcement at the service layer. The AST scanner correctly
    # identifies the codehub.X call as a write, but cannot reason
    # across the wrapper→method boundary. We allowlist with HONEST
    # citations of the method-layer enforcement (or its absence).
    # ============================================================

    "CodeHubCommitTool": (
        "METHOD-LAYER GATED — env_generator/llm_generator/tools/hub_tools.py:136. "
        "Thin wrapper at hub_tools.py:155-156 calling "
        "``codehub.commit(self._agent_id, ...)``. Enforcement lives in "
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py:912-998: "
        "``wt_path = self.repo_root / 'worktrees' / agent_id`` "
        "(service.py:930) — the commit ALWAYS targets the caller's own "
        "worktree, derived from the ``_agent_id`` set by "
        "AgentTooling.attach. Plus per-path staging filter via "
        "``_filter_paths_for_staging`` (service.py:942/981) that drops "
        "dotfile paths (e.g. ``.gates/...``) — Phase 0.2 RE-FIX 5. The "
        "tool itself does NOT need to call is_write_allowed because the "
        "underlying ``codehub.commit`` is structurally per-agent."
    ),

    "CodeHubRecordCommitTool": (
        "METHOD-LAYER PARTIAL — env_generator/llm_generator/tools/hub_tools.py:168. "
        "Thin wrapper at hub_tools.py:183-184 calling "
        "``codehub.record_commit(self._agent_id, branch, files, ...)``. "
        "The method (service.py:150-178) writes metadata to "
        "``stores.commits`` and ``stores.branches`` using ``agent_id`` "
        "as the change-author tag. HONEST CAVEAT: ``record_commit`` "
        "does NOT itself reject calls where ``branch`` doesn't belong to "
        "the calling agent — a caller could record a commit on another "
        "agent's branch metadata. This is accepted because (i) the "
        "underlying real-git commit (CodeHubCommitTool) IS gated to the "
        "caller's worktree, (ii) ``record_commit`` only writes hub-"
        "metadata stores (no filesystem outside the hub state dir), "
        "and (iii) the metadata is audit-tagged with ``agent_id`` so "
        "any cross-branch recording is traceable. REVISIT if hub-"
        "metadata writes ever propagate to the filesystem."
    ),

    "CodeHubOpenPRTool": (
        "METHOD-LAYER GATED — env_generator/llm_generator/tools/hub_tools.py:187. "
        "Thin wrapper at hub_tools.py:212-224 calling "
        "``codehub.open_pull_request(..., author=self._agent_id)``. The "
        "method (service.py:180+) enforces five gates BEFORE any state "
        "mutation: linked_tasks required (200-205), orchestrator auto-"
        "inject for non-orchestrator authors (208-209), >=2 distinct "
        "reviewers excluding author (211-219), every linked_api must "
        "exist (221-231), every linked_task must exist (233+). Author "
        "is forced to ``self._agent_id`` by the wrapper so a caller "
        "cannot impersonate. Hub-state-only write — no filesystem "
        "write outside the hub stores."
    ),

    "CodeHubForceMergeTool": (
        "METHOD-LAYER GATED — env_generator/llm_generator/tools/hub_tools.py:330. "
        "Thin wrapper at hub_tools.py:347-351 calling "
        "``codehub.force_merge_pull_request(pr_id, reason, "
        "agent=self._agent_id)``. The method (service.py:659-687) "
        "enforces orchestrator-only at service.py:661-663 "
        "(``if agent != 'orchestrator': return "
        "{'error': 'force_merge_orchestrator_only'}``) and reason-length "
        "minimum at service.py:664-667 (>=20 chars). Then delegates to "
        "merge_pull_request which itself has the method-layer role gate."
    ),

    "CodeHubMergePRTool": (
        "METHOD-LAYER GATED — env_generator/llm_generator/tools/hub_tools.py:354. "
        "Thin wrapper at hub_tools.py:359-360 calling "
        "``codehub.merge_pull_request(pr_id, strategy=strategy, "
        "agent=self._agent_id)``. The method (service.py:500-657) "
        "enforces (i) PR not-ready check at service.py:504-505, then "
        "(ii) role gate at service.py:518-534 (Phase 2 Fix C) — allowed "
        "= {orchestrator} ∪ {pr.author, pr.assignee}; otherwise returns "
        "``merge_pr_role_denied``. Pinned by "
        "tests/test_merge_pull_request_role_gate.py."
    ),

    "CodeHubCreateReleaseTool": (
        "METHOD-LAYER GATED (DOUBLE) — env_generator/llm_generator/tools/hub_tools.py:467. "
        "Wrapper at hub_tools.py:478-497 calling "
        "``codehub.create_release(tag, source=source, notes=notes, "
        "agent=self._agent_id)``. Two layers of enforcement: (i) tool-"
        "layer gate at hub_tools.py:479-496 requires a successful "
        "RunHub render+functional run on record before any release call; "
        "(ii) method-layer gate at service.py:878-880 enforces "
        "orchestrator-only (``if agent != 'orchestrator': return "
        "{'error': 'release_orchestrator_only'}``). Hub-state write only."
    ),

    "CodeHubResolveConflictTool": (
        "METHOD-LAYER GATED (TRIPLE) — env_generator/llm_generator/tools/hub_tools.py:1305. "
        "Wrapper at hub_tools.py:1324-1328 calling "
        "``codehub.resolve_conflict(pr_id, resolution_files, "
        "agent=self._agent_id)``. The method (service.py:737-869) is the "
        "Phase 0.2 attempt-3 Fix B target with three gates: "
        "(1) role-gate at service.py:770-786 (orchestrator or "
        "PR author/assignee); (2) per-path absolute-path rejection at "
        "service.py:811-817 AND repo-root containment check at "
        "service.py:818-824; (3) staging filter via "
        "``_filter_paths_for_staging`` at service.py:836 that drops "
        "dotfile paths even when written in-repo. This is the most "
        "tightly gated codehub primitive."
    ),
}


# ---------------------------------------------------------------------------
# AST data model
# ---------------------------------------------------------------------------


@dataclass
class WriteSite:
    """A single source location that does a filesystem write."""

    file_path: str
    line: int
    kind: str  # short description, e.g. "write_text", "shutil.copy", "codehub.commit"


@dataclass
class ToolScan:
    """Per-class scan result for one tool class."""

    class_name: str
    file_path: str
    class_line: int
    tool_name: Optional[str]  # value of the class-level ``NAME = "..."``
    bases: List[str]
    write_sites: List[WriteSite] = field(default_factory=list)
    # PHASE 3 FIX #3: track the path expressions actually written, plus
    # the path expressions guarded by ``is_write_allowed``. A tool only
    # counts as gated-via-is_write_allowed when at least one guarded
    # expression matches at least one written expression.
    written_path_exprs: Set[str] = field(default_factory=set)
    is_write_allowed_path_exprs: Set[str] = field(default_factory=set)
    has_file_path_param: bool = False
    delegates_to_gated_tool: bool = False
    # The name of the gated helper / tool delegated to (for diagnostics).
    delegate_target: Optional[str] = None

    @property
    def writes_filesystem(self) -> bool:
        return bool(self.write_sites)

    @property
    def has_is_write_allowed_call(self) -> bool:
        """PHASE 3 FIX #3: true iff at least one ``is_write_allowed`` call
        guards a path expression that is also actually written. A loose
        "any is_write_allowed call anywhere" check used to pass tools
        that gated path ``A`` while writing to ``B`` — that's now
        rejected. Note: written_path_exprs may include an empty string
        for writes whose path argument couldn't be string-extracted
        (e.g. a complex subscript); in that case we conservatively
        accept any is_write_allowed call as "good enough" to avoid
        false-flagging legitimate dynamic-path tools."""
        if not self.is_write_allowed_path_exprs:
            return False
        # If we couldn't extract a path expression for any write site,
        # fall back to the looser check (accept any gate call). This
        # preserves the "false-positive bias" doctrine: we'd rather
        # under-flag a dynamic-path tool that does gate properly than
        # noise the report.
        if "" in self.written_path_exprs and len(self.written_path_exprs) == 1:
            return True
        return bool(self.is_write_allowed_path_exprs & self.written_path_exprs)

    @property
    def is_gated(self) -> bool:
        """A tool is GATED iff at least one of the four conditions holds."""
        # (a) PHASE 3 FIX #4: NAME is recognised by
        # ``_enforce_write_permissions`` AND the tool exposes a
        # path-like parameter so the gate can extract a target. Without
        # the path arg the runtime gate has nothing to extract and the
        # name-match is moot — flag as bypass. (Previously the AND was
        # silently dropped, contradicting this docstring.)
        if (
            self.tool_name
            and self.tool_name in GATED_TOOL_NAMES
            and self.has_file_path_param
        ):
            return True
        # (b) Direct is_write_allowed call inside the class whose path
        # expression matches one we actually write (PHASE 3 FIX #3).
        if self.has_is_write_allowed_call:
            return True
        # (c) Delegates write to an already-gated helper.
        if self.delegates_to_gated_tool:
            return True
        return False


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _attr_chain(node: ast.AST) -> List[str]:
    """Flatten an attribute access (a.b.c) to ['a','b','c']; else []."""
    parts: List[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    parts.reverse()
    return parts


def _call_kind(call: ast.Call) -> Optional[str]:
    """Classify a Call node as a filesystem write; return a short tag or None."""
    func = call.func
    # Method-style: <expr>.<method>(...)
    if isinstance(func, ast.Attribute):
        attr = func.attr
        chain = _attr_chain(func)
        # shutil.X(...)
        if len(chain) >= 2 and chain[0] == "shutil" and attr in SHUTIL_WRITE_FNS:
            return f"shutil.{attr}"
        # os.X(...) / os.path.X — only os.<fn>
        if len(chain) >= 2 and chain[0] == "os" and chain[1] == attr and attr in OS_WRITE_FNS:
            return f"os.{attr}"
        # path.write_text / .write_bytes / .mkdir / .touch / .unlink / .rmdir
        # / .rename / .replace
        if attr in WRITE_METHODS:
            return attr
        # codehub method calls — match any chain ending in
        # ``.codehub.<method>``.
        if "codehub" in chain[:-1] and attr in CODEHUB_WRITE_METHODS:
            return f"codehub.{attr}"
        # git staging: ``.git.add(...)`` / ``git_ops.add(...)``.
        if attr in GIT_STAGE_METHODS and len(chain) >= 2:
            preceding = chain[-2]
            if preceding in {"git", "git_ops"}:
                return f"{preceding}.{attr}"
        return None

    # Function-style: open(path, "w") / write_workspace_file(...) / etc.
    if isinstance(func, ast.Name):
        name = func.id
        if name in WRITE_METHODS:
            return name
        if name == "open":
            # Look at the second positional or `mode=` keyword.
            mode: Optional[str] = None
            if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
                mode = call.args[1].value if isinstance(call.args[1].value, str) else None
            for kw in call.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = kw.value.value if isinstance(kw.value.value, str) else mode
            if mode and any(c in mode for c in ("w", "a", "x")):
                return f"open({mode!r})"
        return None

    return None


def _is_is_write_allowed_call(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr == "is_write_allowed":
        return True
    if isinstance(func, ast.Name) and func.id == "is_write_allowed":
        return True
    return False


def _is_delegate_to_gated_tool(call: ast.Call) -> Optional[str]:
    """Heuristic: does this call delegate write to an already-gated tool?

    We accept ``write_workspace_file(workspace, ...)`` and
    ``_write_with_lint_guard(...)`` as "delegating to a gated helper"
    only when those calls happen inside a class whose own ``NAME`` we
    will check separately. The actual gating logic lives in the
    helper (which itself goes through ``_resolve_workspace_path`` then
    ``_atomic_write_text``) — note this still gives only CONTAINMENT,
    not role gating; but we treat it as delegation when the caller's
    NAME maps to a recognised gated tool. So returning a delegate name
    here is only a signal — final gating decision is in
    ``ToolScan.is_gated``.
    """
    func = call.func
    if isinstance(func, ast.Name) and func.id in {
        "write_workspace_file",
        "_write_with_lint_guard",
    }:
        return func.id
    if isinstance(func, ast.Attribute) and func.attr in {
        "write_workspace_file",
        "_write_with_lint_guard",
    }:
        return func.attr
    return None


def _class_param_names(class_node: ast.ClassDef) -> Set[str]:
    """Collect every function arg name across all methods of the class.

    Used to detect whether the tool exposes a ``file_path`` / ``path``
    / ``destination`` argument that the runtime ``_enforce_write_permissions``
    can extract a write target from.
    """
    names: Set[str] = set()
    for node in ast.walk(class_node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in node.args.args + node.args.kwonlyargs:
                names.add(arg.arg)
    return names


def _class_name_constant(class_node: ast.ClassDef) -> Optional[str]:
    """Find ``NAME = "..."`` assigned at class scope; return the literal."""
    for stmt in class_node.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "NAME":
                    if isinstance(stmt.value, ast.Constant) and isinstance(
                        stmt.value.value, str
                    ):
                        return stmt.value.value
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            if stmt.target.id == "NAME" and isinstance(stmt.value, ast.Constant):
                if isinstance(stmt.value.value, str):
                    return stmt.value.value
    return None


def _base_names(class_node: ast.ClassDef) -> List[str]:
    out: List[str] = []
    for base in class_node.bases:
        if isinstance(base, ast.Name):
            out.append(base.id)
        elif isinstance(base, ast.Attribute):
            out.append(base.attr)
    return out


def _is_tool_class(class_node: ast.ClassDef) -> bool:
    """We consider any class that (i) inherits from a *Tool base, or
    (ii) declares a ``NAME = "..."`` string AND defines an
    ``execute``/``_run`` method, to be a tool class."""
    bases = _base_names(class_node)
    if any(b.endswith("Tool") for b in bases):
        return True
    has_name = _class_name_constant(class_node) is not None
    has_exec = any(
        isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
        and stmt.name in {"execute", "_run"}
        for stmt in class_node.body
    )
    return has_name and has_exec


# ---------------------------------------------------------------------------
# PHASE 3 helpers: alias resolution + path-expression extraction +
# module-level helper recursion.
# ---------------------------------------------------------------------------


def _expr_text(node: Optional[ast.AST]) -> str:
    """Normalised string form of an arbitrary expression, used as the
    join key between ``is_write_allowed(P)`` and writes to ``P``.

    Uses ``ast.unparse`` (3.9+) when available; falls back to a tiny
    pretty-printer for the chains we care about. Empty string means
    "couldn't extract", which the gate-match logic treats as "any".
    """
    if node is None:
        return ""
    try:
        return ast.unparse(node).strip()
    except Exception:
        pass
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        chain = _attr_chain(node)
        return ".".join(chain) if chain else ""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return repr(node.value)
    return ""


def _collect_aliases(func_body: List[ast.stmt]) -> Dict[str, ast.AST]:
    """Build a name→RHS map of single-target ``Assign`` nodes whose RHS
    is an attribute-access or a plain Name. Used to resolve aliases
    like ``ch = self._hubs.codehub`` so a subsequent ``ch.commit()`` is
    classified as a codehub write (PHASE 3 FIX #5).

    Note: we do NOT track re-bindings or attempt SSA. If a name is
    re-assigned to something non-attribute-chain we drop it. This is a
    conservative best-effort that still over-flags rather than under.
    """
    out: Dict[str, ast.AST] = {}
    for stmt in func_body:
        # Only top-level statements in the function body — anything
        # nested inside an ``if`` / ``for`` / ``try`` we conservatively
        # skip (the binding may be conditional).
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
            if isinstance(target, ast.Name) and isinstance(
                stmt.value, (ast.Attribute, ast.Name)
            ):
                out[target.id] = stmt.value
    return out


def _resolve_alias_chain(node: ast.AST, aliases: Dict[str, ast.AST]) -> List[str]:
    """Flatten ``a.b.c`` to ``['a','b','c']``, resolving the head
    through ``aliases`` (one level of expansion — sufficient for the
    ``ch = self._hubs.codehub; ch.commit()`` pattern). PHASE 3 FIX #5.
    """
    chain = _attr_chain(node)
    if not chain:
        return chain
    head = chain[0]
    if head in aliases:
        resolved = _attr_chain(aliases[head])
        if resolved:
            chain = resolved + chain[1:]
    return chain


def _call_kind_with_aliases(
    call: ast.Call, aliases: Dict[str, ast.AST]
) -> Optional[str]:
    """Like ``_call_kind`` but resolves alias heads before chain matching.

    Only the codehub / git-staging branches benefit from alias
    resolution; the shutil / os / WRITE_METHODS branches are unaffected
    because they only test the tail-attribute name. We keep them in
    sync with ``_call_kind`` for clarity.
    """
    func = call.func
    if isinstance(func, ast.Attribute):
        attr = func.attr
        chain = _resolve_alias_chain(func, aliases)
        if len(chain) >= 2 and chain[0] == "shutil" and attr in SHUTIL_WRITE_FNS:
            return f"shutil.{attr}"
        if len(chain) >= 2 and chain[0] == "os" and chain[1] == attr and attr in OS_WRITE_FNS:
            return f"os.{attr}"
        if attr in WRITE_METHODS:
            return attr
        # PHASE 3 FIX #5: codehub via alias is now caught.
        if "codehub" in chain[:-1] and attr in CODEHUB_WRITE_METHODS:
            return f"codehub.{attr}"
        if attr in GIT_STAGE_METHODS and len(chain) >= 2:
            preceding = chain[-2]
            if preceding in {"git", "git_ops"}:
                return f"{preceding}.{attr}"
        return None

    if isinstance(func, ast.Name):
        name = func.id
        if name in WRITE_METHODS:
            return name
        if name == "open":
            mode: Optional[str] = None
            if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
                mode = call.args[1].value if isinstance(call.args[1].value, str) else None
            for kw in call.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = kw.value.value if isinstance(kw.value.value, str) else mode
            if mode and any(c in mode for c in ("w", "a", "x")):
                return f"open({mode!r})"
        return None
    return None


def _write_call_path_expr(call: ast.Call) -> str:
    """Return the source text of the path expression that a write call
    targets. Used by PHASE 3 FIX #3 to match against
    ``is_write_allowed(path)`` arguments.

    Heuristics:
      * ``X.write_text(...)`` / ``X.mkdir(...)`` -> text of ``X``.
      * ``open(P, "w")`` -> text of ``P``.
      * ``shutil.copy(SRC, DST)`` / ``shutil.copytree(SRC, DST)`` ->
        text of ``DST`` (the side that gets written).
      * ``os.rename(SRC, DST)`` -> text of ``DST``.
      * ``_atomic_write_text(P, ...)`` / ``write_workspace_file(WS, P, ...)``
        -> text of the path arg.
      * Codehub / git -> "" (these don't write a single Path).
    """
    func = call.func
    if isinstance(func, ast.Attribute):
        attr = func.attr
        if attr in WRITE_METHODS and not isinstance(func.value, ast.Name) is None:
            # Path-method form: receiver IS the path.
            return _expr_text(func.value)
        if attr in WRITE_METHODS:
            return _expr_text(func.value)
        # shutil.copy(src, dst), shutil.copytree(src, dst), shutil.move(src, dst)
        if attr in SHUTIL_WRITE_FNS and len(call.args) >= 2:
            return _expr_text(call.args[1])
        # os.rename(src, dst), os.replace(src, dst), os.link / symlink (src, dst)
        if attr in OS_WRITE_FNS and len(call.args) >= 2:
            return _expr_text(call.args[1])
        if attr in OS_WRITE_FNS and len(call.args) >= 1:
            return _expr_text(call.args[0])
        return ""
    if isinstance(func, ast.Name):
        name = func.id
        if name == "open" and call.args:
            return _expr_text(call.args[0])
        if name in {"_atomic_write_text", "atomic_write_text", "_write_with_lint_guard"}:
            return _expr_text(call.args[0]) if call.args else ""
        if name == "write_workspace_file":
            # signature: write_workspace_file(workspace, path, ...)
            return _expr_text(call.args[1]) if len(call.args) >= 2 else ""
        if name in WRITE_METHODS and call.args:
            return _expr_text(call.args[0])
    return ""


def _is_write_allowed_arg_text(call: ast.Call) -> Optional[str]:
    """If ``call`` is an ``is_write_allowed`` call, return the text of
    its FIRST positional argument (the path being checked). Returns
    None if the call isn't is_write_allowed."""
    if not _is_is_write_allowed_call(call):
        return None
    if call.args:
        return _expr_text(call.args[0])
    # Keyword-only? Look for ``path=`` / ``file_path=``.
    for kw in call.keywords:
        if kw.arg in {"path", "file_path"}:
            return _expr_text(kw.value)
    return ""  # gate call with no extractable arg — accept loosely


def _module_level_functions(tree: ast.Module) -> Dict[str, ast.FunctionDef]:
    """Map module-level ``def name(...)`` to its function-def node.
    Used by PHASE 3 FIX #2 (module-helper following)."""
    out: Dict[str, ast.FunctionDef] = {}
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[stmt.name] = stmt
    return out


def _scan_function_body(
    func: ast.AST,
    rel_path: str,
    module_funcs: Dict[str, ast.FunctionDef],
    seen: Set[str],
) -> Tuple[List[WriteSite], Set[str], Set[str]]:
    """Scan a function body (or any AST subtree) for write sites,
    transitively recursing into same-module helpers (PHASE 3 FIX #2).

    Returns (write_sites, written_path_exprs, is_write_allowed_arg_texts).
    ``seen`` is a recursion guard keyed by function name."""
    write_sites: List[WriteSite] = []
    write_exprs: Set[str] = set()
    gate_exprs: Set[str] = set()

    # Collect aliases from this function's top-level body, if it has one.
    aliases: Dict[str, ast.AST] = {}
    if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
        aliases = _collect_aliases(func.body)

    for child in ast.walk(func):
        if not isinstance(child, ast.Call):
            continue
        kind = _call_kind_with_aliases(child, aliases)
        if kind is not None:
            write_sites.append(
                WriteSite(
                    file_path=rel_path,
                    line=getattr(child, "lineno", 0),
                    kind=kind,
                )
            )
            write_exprs.add(_write_call_path_expr(child))
        gate_arg = _is_write_allowed_arg_text(child)
        if gate_arg is not None:
            gate_exprs.add(gate_arg)
        # PHASE 3 FIX #2: module-level helper recursion. If this Call is
        # invoking a same-module ``def`` we haven't already recursed
        # into, scan that function too. Cycle-safe via ``seen``.
        if isinstance(child.func, ast.Name) and child.func.id in module_funcs:
            target_name = child.func.id
            if target_name not in seen:
                seen.add(target_name)
                sub_sites, sub_w, sub_g = _scan_function_body(
                    module_funcs[target_name], rel_path, module_funcs, seen
                )
                write_sites.extend(sub_sites)
                write_exprs |= sub_w
                gate_exprs |= sub_g

    return write_sites, write_exprs, gate_exprs


# ---------------------------------------------------------------------------
# Scan a single file
# ---------------------------------------------------------------------------


def scan_file(path: Path) -> List[ToolScan]:
    """Return one ToolScan per tool class found in ``path``."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    module_funcs = _module_level_functions(tree)

    out: List[ToolScan] = []
    rel_path = str(path.relative_to(REPO_ROOT))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not _is_tool_class(node):
            continue

        scan = ToolScan(
            class_name=node.name,
            file_path=rel_path,
            class_line=node.lineno,
            tool_name=_class_name_constant(node),
            bases=_base_names(node),
        )

        param_names = _class_param_names(node)
        # PHASE 3 FIX #4: include ``output_file`` (the runtime
        # ``_enforce_write_permissions`` extracts it explicitly per
        # PHASE 2 FIX A) so tools like ``generate_seed_sql`` that name
        # their write target ``output_file`` are correctly recognised
        # as exposing a gate-extractable path argument.
        scan.has_file_path_param = bool(
            param_names & {
                "file_path",
                "path",
                "destination",
                "dest",
                "target",
                "output_path",
                "output_file",
            }
        )

        # PHASE 3: scan each method of the class with alias-aware,
        # module-helper-following logic. Recursion is keyed per-class so
        # one helper-cycle in one tool doesn't pollute another.
        seen: Set[str] = set()
        for stmt in node.body:
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            sites, w_exprs, g_exprs = _scan_function_body(
                stmt, rel_path, module_funcs, seen
            )
            scan.write_sites.extend(sites)
            scan.written_path_exprs |= w_exprs
            scan.is_write_allowed_path_exprs |= g_exprs

        # Detect delegate-to-gated-tool helpers (separate from write
        # detection; the final is_gated decision still requires the
        # tool's own NAME to map into GATED_TOOL_NAMES).
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            delegate = _is_delegate_to_gated_tool(child)
            if delegate is not None:
                scan.delegate_target = delegate
                if scan.tool_name in GATED_TOOL_NAMES:
                    scan.delegates_to_gated_tool = True

        out.append(scan)

    return out


def scan_tools_tree() -> List[ToolScan]:
    out: List[ToolScan] = []
    for py in sorted(TOOLS_DIR.rglob("*.py")):
        if py.name in SKIP_FILES:
            continue
        if "__pycache__" in py.parts:
            continue
        out.extend(scan_file(py))
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWriteGateInvariant(unittest.TestCase):
    """Structural invariant: every tool that writes to the filesystem
    MUST route through the role-write gate (or appear in
    ``EXPECTED_ALLOWLIST`` with a justification).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.scans = scan_tools_tree()
        cls.writing = [s for s in cls.scans if s.writes_filesystem]
        cls.bypassers = [
            s
            for s in cls.writing
            if not s.is_gated and s.class_name not in EXPECTED_ALLOWLIST
        ]

    def test_tools_tree_is_discovered(self) -> None:
        """Sanity: the AST scan must find some tool classes."""
        self.assertGreater(
            len(self.scans),
            20,
            "tool scan found suspiciously few classes — check TOOLS_DIR / heuristics",
        )

    def test_known_gated_tools_are_recognized_as_gated(self) -> None:
        """Calibration: the canonical write/edit/delete/apply_patch tools
        MUST be detected as both 'writes filesystem' AND 'gated', so we
        know the heuristic distinguishes the two states."""
        expected = {"write", "edit", "delete_file", "apply_patch"}
        by_name = {s.tool_name: s for s in self.scans if s.tool_name in expected}
        missing = expected - set(by_name.keys())
        self.assertFalse(
            missing,
            f"calibration failure: canonical tools not discovered: {missing}",
        )
        for name in expected:
            s = by_name[name]
            self.assertTrue(
                s.writes_filesystem,
                f"{s.class_name} ({name}) should be detected as writing the filesystem",
            )
            self.assertTrue(
                s.is_gated,
                f"{s.class_name} ({name}) should be detected as GATED — "
                f"NAME in {GATED_TOOL_NAMES}",
            )

    def test_no_writing_tool_bypasses_the_role_gate(self) -> None:
        """THE INVARIANT.

        Every tool whose ``execute()`` (or same-class helper) writes
        to the filesystem MUST be GATED — i.e. its NAME must be in
        ``GATED_TOOL_NAMES`` (so ``_enforce_write_permissions`` will
        fire), OR it must call ``is_write_allowed`` itself, OR it must
        delegate the write to a gated tool.

        Tools that legitimately write outside the role-gated workspace
        must appear in ``EXPECTED_ALLOWLIST`` with a justification.
        """
        if not self.bypassers:
            return  # green
        lines = [
            "",
            "Write-gate invariant FAILED. The following tools write to the",
            "filesystem but do NOT route through is_write_allowed and are NOT",
            "in EXPECTED_ALLOWLIST.",
            "",
            "Each entry: tool_class @ file:line  NAME=<name>  bases=<bases>",
            "  -> write sites (sample)",
            "",
        ]
        for s in sorted(self.bypassers, key=lambda x: (x.file_path, x.class_line)):
            lines.append(
                f"  {s.class_name} @ {s.file_path}:{s.class_line}  "
                f"NAME={s.tool_name!r}  bases={s.bases}"
            )
            for w in s.write_sites[:5]:
                lines.append(f"      - {w.kind} at {w.file_path}:{w.line}")
            if len(s.write_sites) > 5:
                lines.append(f"      - ... and {len(s.write_sites) - 5} more sites")
        lines.append("")
        lines.append(
            "Fix: either (a) add the tool's NAME to the recognised set in "
            "AgentTooling._enforce_write_permissions and ensure its args "
            "expose a file_path/path/destination, (b) call "
            "workspace.is_write_allowed(...) inside the tool's execute(), "
            "or (c) add an entry to EXPECTED_ALLOWLIST with a file:line "
            "comment justifying why this tool legitimately writes outside "
            "the role-gated workspace."
        )
        self.fail("\n".join(lines))

    def test_allowlist_entries_have_justifications(self) -> None:
        """Each EXPECTED_ALLOWLIST entry's value must be non-empty and
        contain a file:line citation. This keeps the allowlist honest."""
        for class_name, justification in EXPECTED_ALLOWLIST.items():
            self.assertTrue(
                justification.strip(),
                f"allowlist entry for {class_name!r} has no justification",
            )
            self.assertIn(
                ":",
                justification,
                f"allowlist entry for {class_name!r} must cite file:line "
                f"(got: {justification!r})",
            )

    def test_expected_allowlist_count_is_29(self) -> None:
        """R1 round-5 attempt-6 HARDENING B count assertion.

        The doc-comments throughout this file (module docstring + the
        ``Authoritative count`` block) cite a count of **29**. The
        in-tree narrative was logged as comment-only with no machine
        check, so a future allowlist edit could silently drift the
        comment out of sync with ``len(EXPECTED_ALLOWLIST)``. This
        assertion converts the comment-only count into a hard
        invariant.

        If the actual count changes, update BOTH this constant AND the
        comment in the module docstring (``29 entries``) in the same
        commit. Drift between them is what this assertion exists to
        catch."""
        self.assertEqual(
            len(EXPECTED_ALLOWLIST),
            29,
            f"EXPECTED_ALLOWLIST count drifted from comment-pinned 29 "
            f"to {len(EXPECTED_ALLOWLIST)}. Update the module docstring "
            f"AND this assertion together to re-pin the new count.",
        )


# ---------------------------------------------------------------------------
# Optional: diagnostics that pytest prints on test_no_writing_tool_bypasses_*
# failure but that can also be inspected by hand by running this file.
# ---------------------------------------------------------------------------


def _print_diagnostics() -> None:  # pragma: no cover - manual invocation
    scans = scan_tools_tree()
    writing = [s for s in scans if s.writes_filesystem]
    gated = [s for s in writing if s.is_gated]
    bypassers = [
        s for s in writing if not s.is_gated and s.class_name not in EXPECTED_ALLOWLIST
    ]
    print(f"# total tool classes scanned: {len(scans)}")
    print(f"# tools that write filesystem: {len(writing)}")
    print(f"# of those, GATED:             {len(gated)}")
    print(f"# of those, BYPASSING:         {len(bypassers)}")
    print()
    print("BYPASSERS:")
    for s in sorted(bypassers, key=lambda x: (x.file_path, x.class_line)):
        sites = ", ".join(f"{w.kind}@L{w.line}" for w in s.write_sites[:3])
        print(
            f"  {s.class_name} ({s.file_path}:{s.class_line})  "
            f"NAME={s.tool_name!r}  -> {sites}"
        )
    print()
    print("GATED (sample of 8):")
    for s in gated[:8]:
        print(f"  {s.class_name} ({s.file_path}:{s.class_line})  NAME={s.tool_name!r}")


if __name__ == "__main__":  # pragma: no cover
    _print_diagnostics()
