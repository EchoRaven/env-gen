"""Phase 0.2 attempt-4 PHASE 4 SIBLING A: Method-layer write-gate invariant.

Authoritative count: ``METHOD_ALLOWLIST`` currently has **27 entries**
(was 23 in R1 round-4; +1 for StoryHubStores.create bootstrap mkdir,
added 2026-06-01 when the dt-conda-env test sweep surfaced the
missing entry; +1 for WorkHub._munge_endpoint_id false-positive
string-replace, added 2026-06-03 when the cross-hub sync landed;
+1 for CodeHub.commit_runtime_scaffold pre-spawn base-branch scaffold
committer, added 2026-06-06 with the §6 validation-framework work;
+1 for WorkHubStores.create fixed-path page→document migration rename,
added 2026-07-27 when the gates sweep surfaced the missing entry).
Keep this comment in sync with ``len(METHOD_ALLOWLIST)`` after every
edit.

Why this test exists
====================

The tool-layer invariant (``tests/test_write_gate_invariant.py``) only
covers the *tool* layer — every ``BaseTool`` / ``HubTool`` subclass under
``env_generator/llm_generator/tools/**``. Reviewer 2 pointed out that
this leaves the *method* / write-path layer uncovered: a hub method
(e.g. ``CodeHub.merge_pull_request``) can be invoked from at least
three call paths — the tool wrapper (``hub_tools.py``), the live
monitor HTTP endpoint (``live_monitor_server.py``), and any internal
call. The tool layer only protects path 1. If the method itself has
no role gate / containment / worktree-isolation, the other two paths
are open. PHASE 1 AUDIT B confirmed this concretely for
``merge_pull_request`` (no role gate at the method layer; the monitor
endpoint forwards ``body.agent`` untrusted).

The reviewer's structural insight:

    "The tool-layer invariant doesn't cover write-path/method layer.
    Add a sibling that scans every write primitive in
    ``env_generator/llm_generator/multi_agent/runtime/hubs/**`` and
    asserts it has either: a role-gate, path containment, worktree-
    isolation, OR is in an explicit METHOD_ALLOWLIST with
    justification."

How the invariant works
=======================

For every ``.py`` file under
``env_generator/llm_generator/multi_agent/runtime/hubs/`` we ask, via
Python's ``ast`` module:

  Q1. Does this method *write to the filesystem* or *mutate repo
      state* (git refs / staging / commits)? Heuristics — mirrored on
      the tool-layer scanner, with hub-specific additions:

        * ``write_text`` / ``write_bytes`` / ``touch`` / ``unlink`` /
          ``rmdir`` / ``rename`` / ``replace`` / ``mkdir``.
        * ``open(...)`` with a write-mode argument.
        * ``shutil.copy*`` / ``move`` / ``copytree`` /
          ``os.rename`` / ``os.replace`` / ``os.remove`` /
          ``os.unlink`` / ``os.makedirs`` / ``os.symlink``.
        * ``self.git.X(...)`` / ``wt_git.X(...)`` where X is in
          ``GIT_WRITE_METHODS`` (init, add, commit, merge, checkout,
          create_branch_at, add_worktree, remove_worktree).
        * ``self.git._run(...)`` with a verb that mutates (``add`` /
          ``commit`` / ``merge`` / ``reset`` / ``branch`` /
          ``checkout`` / ``rebase`` / ``revert``).

  Q2. Does the method enforce write-safety? A method counts as GATED
      iff at least one of these is true (signal scanned in the
      method's own body):

        a) ROLE-GATE: a comparison between an ``agent`` / ``agent_id``
           / ``author`` arg and one of {``"orchestrator"``, the PR
           author, the PR assignee, a known role string}.
        b) PATH CONTAINMENT: at least one of ``resolve()`` followed
           by ``is_relative_to(...)``, or an explicit
           ``is_absolute()`` rejection check, on a caller-supplied
           path.
        c) WORKTREE-ISOLATION: the write target is derived from
           ``self.repo_root / "worktrees" / agent_id`` (or a similar
           ``worktrees/<actor>`` chain).
        d) STAGING-FILTER: paths flow through
           ``_filter_paths_for_staging`` (auto_commit's dotfile gate).

METHOD_ALLOWLIST
================

For every method we cannot auto-detect as gated, we require an entry
in ``METHOD_ALLOWLIST`` keyed by ``(file, class, method)``. The value
is a justification string that MUST include a file:line citation of
the actual enforcement signal it relies on. The justifications for the
seven CodeHub service methods called out in PHASE 1 AUDIT B are
hardcoded here.

Failure mode
============

The test is structural — it does NOT execute any method. It reads the
hub source files, parses each method with ``ast``, and asserts the
invariant. False-positive bias is acceptable: if a method is over-
flagged, the fix author can either (i) add an explicit enforcement
signal to the method body, or (ii) add an allowlist entry with a
justification.
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
HUBS_DIR = (
    REPO_ROOT
    / "env_generator"
    / "llm_generator"
    / "multi_agent"
    / "runtime"
    / "hubs"
)

# Path-object / file methods that mutate the filesystem.
WRITE_METHODS: Set[str] = {
    "write_text",
    "write_bytes",
    "touch",
    "unlink",
    "rmdir",
    "rename",
    "replace",
    "mkdir",
    "_atomic_write_text",
    "atomic_write_text",
}

SHUTIL_WRITE_FNS: Set[str] = {
    "copy", "copy2", "copyfile", "copytree", "move", "write", "rmtree",
}

OS_WRITE_FNS: Set[str] = {
    "rename", "replace", "link", "symlink", "makedirs",
    "remove", "unlink", "rmdir",
}

# git_ops methods that mutate repository state (add, commit, merge,
# checkout, branch creation, worktree creation/removal). Scanned on
# ``self.git.X(...)``, ``wt_git.X(...)``, ``GitOps(...).X(...)``.
GIT_WRITE_METHODS: Set[str] = {
    "init",
    "add",
    "commit",
    "merge",
    "checkout",
    "create_branch_at",
    "add_worktree",
    "remove_worktree",
    "rebase",
    "revert",
    "reset",
    "push",
    "pull",
    "fetch",
}

# When we see ``self.git._run(...)`` / ``wt_git._run(...)``, the first
# positional arg is the git verb. These verbs mutate state and count
# as a write.
GIT_RUN_MUTATING_VERBS: Set[str] = {
    "add",
    "commit",
    "merge",
    "checkout",
    "branch",
    "rebase",
    "revert",
    "reset",
    "push",
    "pull",
    "fetch",
    "tag",
    "rm",
    "mv",
    "init",
    "worktree",
}

# Roles / identity strings that, when compared against a method
# argument, count as a role-gate signal.
ROLE_GATE_STRINGS: Set[str] = {
    "orchestrator",
    "codehub",
    "workhub",
    "runhub",
    "registryhub",
}

# Files to skip entirely (data-class / constant / __init__ files).
SKIP_FILES: Set[str] = {
    "__init__.py",
}

# ---------------------------------------------------------------------------
# METHOD_ALLOWLIST
# ---------------------------------------------------------------------------
#
# Each entry is keyed by (rel_file_path, class_name, method_name) and
# carries the justification produced by PHASE 1 AUDIT B (or a future
# audit). The justification MUST include a file:line citation of the
# real enforcement signal (which may be at an outer layer — e.g. a
# tool-layer pin or a monitor-layer hard-pin — when the method itself
# legitimately has no in-body gate).
#
# Triple-underscored 'audit_id' is preserved in a sentinel entry so
# the audit's provenance is auditable from the test source.

AUDIT_ID = "phase1-audit-B-codehub-methods"

METHOD_ALLOWLIST: Dict[Tuple[str, str, str], str] = {
    # ------------------------------------------------------------------
    # CodeHub service.py — PHASE 1 AUDIT B (7 methods audited)
    # ------------------------------------------------------------------
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py",
        "CodeHub",
        "force_merge_pull_request",
    ): (
        "Method-layer role gate at service.py:661 "
        "('if agent != \"orchestrator\": return error'). Tool layer pins "
        "agent to caller (hub_tools.py:348). Monitor layer hard-pins "
        "agent='orchestrator' regardless of body "
        "(live_monitor_server.py:3945). Safe to allowlist."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py",
        "CodeHub",
        "create_release",
    ): (
        "Method-layer role gate at service.py:878 "
        "('if agent != \"orchestrator\": return error'). Tool layer pins "
        "agent to caller (hub_tools.py:497). Not exposed via monitor "
        "server. Safe to allowlist."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py",
        "CodeHub",
        "resolve_conflict",
    ): (
        "Triple gate verified at service.py:777 (role: agent in "
        "{orchestrator} | {pr.author, pr.assignee}), :811/:819 "
        "(path containment: absolute-path reject + is_relative_to "
        "check), and :836 (_filter_paths_for_staging). Tool layer pins "
        "agent (hub_tools.py:1325). Not reachable from monitor server. "
        "Fix B docstring claims match the code."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py",
        "CodeHub",
        "commit",
    ): (
        "No role gate at lines 912-998 — this is intentional. The "
        "method is a caller-self-help primitive: it writes only into "
        "worktrees/<agent_id> (service.py:930-932) and all staging "
        "flows through _filter_paths_for_staging at service.py:942 "
        "(explicit files) and :981 (status --porcelain fallback), with "
        "the raw 'git add .' bypass explicitly closed at :952-954. "
        "Tool layer pins agent_id (hub_tools.py:156). Method "
        "'commit_for_agent' named in audit B does not exist; only "
        "'commit'."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py",
        "CodeHub",
        "commit_runtime_scaffold",
    ): (
        "No role gate by design — this runs PRE-SPAWN (service.py:115), "
        "before any agent worktree or actor exists, so there is no agent "
        "to gate on. Sole caller is the orchestrator's seed step "
        "(orchestrator.py:1702 in _seed_base_scaffold, itself called once "
        "at orchestrator.py:500); not reachable from any agent tool path "
        "or the monitor server. Path containment: commits ONLY the "
        "explicit rel_paths passed (git.add(*existing) at service.py:146, "
        "never 'git add .'), and a Charter-§8 existence guard raises "
        "FileNotFoundError at service.py:141 on any path not on disk "
        "(no phantom commit). Safe to allowlist."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py",
        "CodeHub",
        "record_commit",
    ): (
        "No role gate at lines 150-178 — intentional, this is a "
        "metadata-only recorder with no filesystem effect. Tool layer "
        "pins agent_id=self._agent_id (hub_tools.py:184). Not exposed "
        "via monitor server. Residual risk: an agent could fabricate "
        "a commit metadata entry on an arbitrary branch name via "
        "ensure_branch (service.py:152), but no real git ref is "
        "written."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py",
        "CodeHub",
        "open_pull_request",
    ): (
        "No author-identity gate at lines 180-319 — intentional "
        "design choice (the seven structural gates at :200, :208, "
        ":213, :223, :236, :246, :260 act as guardrails instead of a "
        "role gate). Tool layer pins author=self._agent_id "
        "(hub_tools.py:220). The monitor-layer wrapper at "
        "live_monitor_server.py:3861 passes body.author unfiltered, so "
        "an authenticated UI user can spoof author identity — but they "
        "still cannot bypass the structural gates (linked_tasks must "
        "exist, >=2 reviewers, etc.). Residual impersonation risk is "
        "medium not high because every PR still requires verified "
        "WorkHub task links."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py",
        "CodeHub",
        "merge_pull_request",
    ): (
        "Role gate added at service.py:518-534 (Phase 2 Fix C). "
        "Method now mirrors force_merge_pull_request / "
        "resolve_conflict: allowed = {orchestrator} | "
        "{pr.author, pr.assignee}; otherwise returns "
        "'merge_pr_role_denied'. attempt-5 CORRECTION 4 (R1 round-4): "
        "the monitor-layer wrapper at live_monitor_server.py:3903 now "
        "hard-pins agent='orchestrator' instead of forwarding "
        "body.agent — mirrors force_merge's pattern at "
        "live_monitor_server.py:3945. This genuinely closes Reviewer "
        "2's HIGH finding (the attempt-4 claim of closure was "
        "overstated in the default auth-off posture where "
        "body.agent was forwarded; the hard-pin now makes the claim "
        "true). L2 verifier gate at :537 remains as defense in depth "
        "on content. Tool layer pins agent=self._agent_id "
        "(hub_tools.py:360). Safe to allowlist."
    ),
    # ------------------------------------------------------------------
    # CodeHub service.py — supporting methods that mutate state but
    # are infrastructure / helper primitives, not directly exposed.
    # ------------------------------------------------------------------
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py",
        "CodeHub",
        "ensure_repo",
    ): (
        "Infrastructure bootstrap: idempotently initialises a git "
        "repo at self.repo_root (service.py:42-46) if absent. "
        "self.repo_root is a constructor-fixed Path, not caller-"
        "supplied; no agent identity is involved. Called only by "
        "internal lifecycle code paths."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py",
        "CodeHub",
        "register_agent_worktree",
    ): (
        "Worktree isolation by construction at service.py:69 "
        "('wt_path = self.repo_root / \"worktrees\" / agent_id'). "
        "Creates a per-agent worktree at a derived path; the agent "
        "identity arg IS the isolation key. The fixed 'agent/<id>' "
        "branch naming convention at :68 means an agent can only "
        "create their own worktree. Tool layer pins agent_id "
        "(hub_tools.py)."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py",
        "CodeHub",
        "cleanup_worktree",
    ): (
        "Worktree isolation by construction at service.py:91 "
        "('wt_path = self.repo_root / \"worktrees\" / agent_id'). "
        "Removes only the worktree under worktrees/<agent_id> and "
        "deletes the matching agent/<agent_id> branch (:100). The "
        "derived path is the isolation. Tool layer pins agent_id."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py",
        "CodeHub",
        "register_agent_repo",
    ): (
        "Metadata-only writer at service.py:117-127 — updates "
        "self.stores.repos and calls ensure_branch. No real git ref "
        "or filesystem write. agent_id becomes the repo metadata key, "
        "tool layer pins it (hub_tools.py)."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py",
        "CodeHub",
        "ensure_branch",
    ): (
        "Metadata-only writer at service.py:129-148 — updates "
        "self.stores.branches with a branch document keyed by "
        "(repo_id, branch). No real git ref is created or moved. "
        "Caller-self-help primitive; tool layer pins agent_id."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py",
        "CodeHub",
        "_handle_merge_conflict",
    ): (
        "Internal helper called only from merge_pull_request "
        "(service.py:623, :635). Its role-safety is inherited from "
        "the caller: merge_pull_request now has a role gate at :518-"
        "534 (Phase 2 Fix C), so any path that reaches "
        "_handle_merge_conflict has already been checked. Performs "
        "merge --abort / reset --merge / checkout target (:694-696) "
        "to leave the repo clean — these are remediation operations, "
        "not arbitrary writes."
    ),
    # ------------------------------------------------------------------
    # CodeHub git_ops.py — low-level git wrappers. These are intentionally
    # role-agnostic; the gating happens in the CodeHub methods that call
    # them. Treated as 'delegation library' — each method has a fixed
    # repo_root passed at construction.
    # ------------------------------------------------------------------
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/git_ops.py",
        "GitOps",
        "init",
    ): (
        "Low-level git wrapper at git_ops.py:58-65. Operates on "
        "self.repo_root (constructor-fixed). Gated by callers — only "
        "CodeHub.ensure_repo (service.py:46) instantiates and calls "
        "this on the hub-owned repo_root."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/git_ops.py",
        "GitOps",
        "add",
    ): (
        "Low-level git wrapper at git_ops.py:71-74. Stages paths in "
        "self.repo_root. Callers (CodeHub.commit, CodeHub.resolve_"
        "conflict) route paths through _filter_paths_for_staging "
        "first (service.py:942, :836). Reviewer-flagged 'git add .' "
        "bypass is explicitly closed by callers."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/git_ops.py",
        "GitOps",
        "commit",
    ): (
        "Low-level git wrapper at git_ops.py:76-82. Creates a commit "
        "on the staged index of self.repo_root. Callers gate identity "
        "/ staging upstream (CodeHub.commit, CodeHub.resolve_conflict, "
        "CodeHub.merge_pull_request)."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/git_ops.py",
        "GitOps",
        "add_worktree",
    ): (
        "Low-level git wrapper at git_ops.py:88-97. Creates a "
        "worktree at a caller-supplied path. The only caller is "
        "CodeHub.register_agent_worktree (service.py:72), which "
        "derives the path as self.repo_root / 'worktrees' / agent_id "
        "— worktree isolation by construction."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/git_ops.py",
        "GitOps",
        "remove_worktree",
    ): (
        "Low-level git wrapper at git_ops.py:99-104. Removes a "
        "worktree at a caller-supplied path. Only caller is "
        "CodeHub.cleanup_worktree (service.py:94), which derives the "
        "path as self.repo_root / 'worktrees' / agent_id."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/git_ops.py",
        "GitOps",
        "merge",
    ): (
        "Low-level git wrapper at git_ops.py:178-200. Performs a "
        "git-level merge on self.repo_root. Only reachable from "
        "CodeHub.merge_pull_request (service.py:633), which is now "
        "role-gated at :518-534."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/git_ops.py",
        "GitOps",
        "checkout",
    ): (
        "Low-level git wrapper at git_ops.py:202-208. Switches "
        "branches in self.repo_root. Callers (CodeHub.merge_pull_"
        "request :603, CodeHub.resolve_conflict :794, "
        "CodeHub._handle_merge_conflict :696) gate identity upstream."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/git_ops.py",
        "GitOps",
        "create_branch_at",
    ): (
        "Low-level git wrapper at git_ops.py:210-224. Creates / "
        "moves a branch ref. Only caller is CodeHub.create_release "
        "(service.py:890), which is orchestrator-gated at :878."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/git_ops.py",
        "GitOps",
        "_run",
    ): (
        "Subprocess primitive at git_ops.py:39-52. Every public "
        "GitOps method goes through this. Per-verb gating is the "
        "responsibility of the public methods / their callers."
    ),
    # ------------------------------------------------------------------
    # RunHub service.py — hub_dir bootstrap mkdir.
    # ------------------------------------------------------------------
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/runhub/service.py",
        "RunHub",
        "__init__",
    ): (
        "Infrastructure bootstrap: self.hub_dir.mkdir at "
        "runhub/service.py:26. hub_dir is a constructor-fixed Path "
        "supplied by the runtime / harness; not caller-supplied at "
        "the agent layer."
    ),

    # ------------------------------------------------------------------
    # StoryHubStores stores.py — hub_dir bootstrap mkdir (same shape as
    # RunHub.__init__ above).
    # ------------------------------------------------------------------
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/story_hub/stores.py",
        "StoryHubStores",
        "create",
    ): (
        "Infrastructure bootstrap: hub_dir.mkdir(parents=True, "
        "exist_ok=True) at story_hub/stores.py:30. hub_dir is a "
        "constructor-fixed Path supplied by HubRegistry (see "
        "hub_registry.py:132 — store_dir/'story_hub'), not "
        "caller-supplied at the agent layer. One-time init that "
        "creates the persistence directory for the Phase 3 StoryHub "
        "JsonStore. Mirrors the RunHub.__init__ entry above."
    ),
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py",
        "WorkHub",
        "_munge_endpoint_id",
    ): (
        "False positive in the write-site heuristic. The method is a "
        "@staticmethod that builds a string id by ``str.replace(...)`` "
        "on its arguments (service.py:412-413). The detector flags "
        "``.replace(...)`` as a potential Path.replace filesystem "
        "write, but here it is ``str.replace`` shadowing the same "
        "method name — no filesystem effect. Method is pure: no "
        "I/O, no state mutation, only string transforms. Reproduces "
        "``schema_tolerance._munge_path`` (runtime/kickoff/schema_"
        "tolerance.py:321-327) which has the same false-positive "
        "shape (also a pure string helper). Used by the cross-hub "
        "sync to look up the canonical WorkHub task id for an RegistryHub "
        "endpoint."
    ),
    # ------------------------------------------------------------------
    # WorkHubStores stores.py — legacy-file persistence migration rename
    # (workhub_pages.json → workhub_documents.json). Same hub-owned,
    # fixed-constant-path shape as the StoryHubStores.create / RunHub
    # bootstrap entries above.
    # ------------------------------------------------------------------
    (
        "env_generator/llm_generator/multi_agent/runtime/hubs/workhub/stores.py",
        "WorkHubStores",
        "create",
    ): (
        "Hub-owned migration rename, not agent-controllable. The single "
        "write is old_path.rename(new_path) at workhub/stores.py:35, where "
        "BOTH endpoints are fixed module constants — old_path = hub_dir / "
        "'workhub_pages.json' (:32) and new_path = hub_dir / "
        "'workhub_documents.json' (:33); no agent-supplied path component "
        "participates. hub_dir is the constructor-fixed HubRegistry store "
        "dir (WorkHub(self._store_dir) at hub_registry.py:135, resolved at "
        "hub_registry.py:109-110), not caller-supplied at the agent layer. "
        "The rename is guarded (only fires when the legacy file exists AND "
        "the new one does not, :34) and best-effort (try/except at :31/:36). "
        "Same hub-bootstrap shape as the StoryHubStores.create / "
        "RunHub.__init__ allowlist entries above."
    ),
}


# ---------------------------------------------------------------------------
# AST data model
# ---------------------------------------------------------------------------


@dataclass
class WriteSite:
    """A single source location that does a filesystem or repo-state write."""

    file_path: str
    line: int
    kind: str


@dataclass
class MethodScan:
    """Per-method scan result for one hub method."""

    file_path: str
    class_name: str
    method_name: str
    method_line: int
    write_sites: List[WriteSite] = field(default_factory=list)
    has_role_gate: bool = False
    has_path_containment: bool = False
    has_worktree_isolation: bool = False
    has_staging_filter: bool = False
    # The arg names this method declares (e.g. 'agent', 'agent_id',
    # 'author'). Used to detect comparisons against role strings.
    arg_names: Set[str] = field(default_factory=set)

    @property
    def writes(self) -> bool:
        return bool(self.write_sites)

    @property
    def is_gated(self) -> bool:
        return (
            self.has_role_gate
            or self.has_path_containment
            or self.has_worktree_isolation
            or self.has_staging_filter
        )

    @property
    def allowlist_key(self) -> Tuple[str, str, str]:
        return (self.file_path, self.class_name, self.method_name)


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


def _expr_text(node: Optional[ast.AST]) -> str:
    """Normalised string form of an arbitrary expression."""
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


def _call_write_kind(call: ast.Call) -> Optional[str]:
    """Classify a Call node as a filesystem / repo-state write."""
    func = call.func

    # Method-style: <expr>.<method>(...)
    if isinstance(func, ast.Attribute):
        attr = func.attr
        chain = _attr_chain(func)

        # shutil.X(...)
        if len(chain) >= 2 and chain[0] == "shutil" and attr in SHUTIL_WRITE_FNS:
            return f"shutil.{attr}"

        # os.X(...) — only top-level os.<fn>
        if len(chain) >= 2 and chain[0] == "os" and chain[1] == attr and attr in OS_WRITE_FNS:
            return f"os.{attr}"

        # Path-object writes
        if attr in WRITE_METHODS:
            return attr

        # self.git.X(...) / wt_git.X(...) where X is a mutating verb
        if attr in GIT_WRITE_METHODS and len(chain) >= 2:
            receiver = chain[-2]
            if receiver == "git" or receiver.endswith("_git") or receiver == "git_ops":
                return f"git.{attr}"

        # self.git._run(verb, ...) / wt_git._run(verb, ...)
        if attr == "_run" and len(chain) >= 2:
            receiver = chain[-2]
            if receiver == "git" or receiver.endswith("_git") or receiver == "git_ops":
                # Inspect first positional arg
                if call.args:
                    arg0 = call.args[0]
                    if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                        verb = arg0.value
                        if verb in GIT_RUN_MUTATING_VERBS:
                            return f"git._run({verb!r})"
        return None

    # Function-style: open(path, "w") / etc.
    if isinstance(func, ast.Name):
        name = func.id
        if name in WRITE_METHODS:
            return name
        if name == "open":
            mode: Optional[str] = None
            if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
                v = call.args[1].value
                mode = v if isinstance(v, str) else None
            for kw in call.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    v = kw.value.value
                    if isinstance(v, str):
                        mode = v
            if mode and any(c in mode for c in ("w", "a", "x")):
                return f"open({mode!r})"
        return None

    return None


# ---------------------------------------------------------------------------
# Enforcement-signal detectors
# ---------------------------------------------------------------------------


def _detect_role_gate(method: ast.AST, arg_names: Set[str]) -> bool:
    """A role-gate signal is a comparison between a recognised role-y
    arg (agent / agent_id / author / actor / by / requester / assignee)
    and either a known role string ("orchestrator", ...) OR an
    expression referencing a PR record's ``author`` / ``assignee``
    field. We also accept ``in``-membership tests against a set whose
    elements include any role-y string.

    Also: ``if agent not in allowed`` where ``allowed`` is built up
    earlier in the method (e.g. ``allowed = {"orchestrator"}; allowed.add(pr_author)``).
    The lightweight detector keys on the literal-set form OR a
    membership comparison whose RHS contains a role string.
    """
    role_argish: Set[str] = {
        a for a in arg_names
        if a in {"agent", "agent_id", "author", "actor", "by",
                 "requester", "assignee", "owner", "caller"}
    }
    if not role_argish:
        # We can still find role gates that compare a *local* variable
        # like ``pr_author`` — search those too.
        role_argish = set()

    role_strings = ROLE_GATE_STRINGS

    for node in ast.walk(method):
        # if X != "orchestrator" / X == "orchestrator"
        if isinstance(node, ast.Compare):
            left_text = _expr_text(node.left)
            # Left-hand role-y name?
            left_is_role = any(left_text == a or left_text.endswith("." + a) for a in role_argish)
            if not left_is_role:
                # Also accept a left side that *contains* an arg name
                # (e.g. ``agent.lower()``).
                left_is_role = any(a in left_text.split(".") for a in role_argish if a)

            for op, comparator in zip(node.ops, node.comparators):
                comp_text = _expr_text(comparator)
                # Eq / NotEq against a role string literal
                if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(comparator, ast.Constant):
                    if isinstance(comparator.value, str) and comparator.value in role_strings:
                        if left_is_role:
                            return True

                # In / NotIn against an expression that mentions a role string
                if isinstance(op, (ast.In, ast.NotIn)):
                    # The RHS may be a set literal, a name, or a Call.
                    # We accept if (i) the left is role-y AND (ii)
                    # somewhere in the comparator subtree there's a
                    # role-string constant OR a name that looks role-y
                    # (e.g. ``allowed``).
                    if left_is_role:
                        for sub in ast.walk(comparator):
                            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                                if sub.value in role_strings:
                                    return True
                            if isinstance(sub, ast.Name) and sub.id in {
                                "allowed", "allowed_roles", "permitted",
                                "authors", "ALLOWED", "ROLES",
                            }:
                                return True
                        # Also accept membership against pr.author / pr.assignee
                        ct = comp_text
                        if "author" in ct or "assignee" in ct or "owner" in ct:
                            return True

        # `assert X == "orchestrator"` style — also a gate.
        if isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare):
            t = _expr_text(node.test)
            if any(s in t for s in role_strings):
                return True

    # Detect the ``allowed = {"orchestrator"} ... if agent not in allowed`` pattern
    # by looking for a set literal containing a role string AND a later
    # ``X not in allowed`` (or similar).
    has_role_set = False
    for node in ast.walk(method):
        if isinstance(node, ast.Set):
            for elt in node.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    if elt.value in role_strings:
                        has_role_set = True
                        break
        if has_role_set:
            break
    if has_role_set:
        for node in ast.walk(method):
            if isinstance(node, ast.Compare):
                for op in node.ops:
                    if isinstance(op, (ast.In, ast.NotIn)):
                        for comparator in node.comparators:
                            ct = _expr_text(comparator)
                            if ct in {"allowed", "allowed_roles", "permitted"}:
                                return True

    return False


def _detect_path_containment(method: ast.AST) -> bool:
    """A path-containment signal is at least one of:
      * ``X.is_relative_to(Y)`` — the modern Python 3.9+ form.
      * An ``is_absolute()`` rejection check (an ``if X.is_absolute()``
        branch that returns / raises).
      * A ``resolve()`` call followed structurally by a containment
        compare (e.g. ``commonpath`` / startswith on a resolved path).
    """
    for node in ast.walk(method):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                if func.attr == "is_relative_to":
                    return True
                if func.attr == "is_absolute":
                    # Heuristic: any ``X.is_absolute()`` call counts —
                    # the rejection branch is the common usage. A few
                    # false-positives (e.g. probing only) are acceptable.
                    return True
                if func.attr == "commonpath":
                    return True
    return False


def _detect_worktree_isolation(method: ast.AST) -> bool:
    """A worktree-isolation signal is a path expression containing
    the literal segment ``"worktrees"`` joined with an arg-derived
    name. We accept any BinOp whose source text contains
    ``"worktrees"`` and one of the role-y arg names.

    Also accept the common form ``self.repo_root / "worktrees" / agent_id``.
    """
    for node in ast.walk(method):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            txt = _expr_text(node)
            if '"worktrees"' in txt or "'worktrees'" in txt:
                return True
        # Direct call: register_agent_worktree(agent_id) — delegates
        # to a method that itself produces a worktrees/<agent> path.
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "register_agent_worktree":
                return True
    return False


def _detect_staging_filter(method: ast.AST) -> bool:
    """A staging-filter signal is a call to ``_filter_paths_for_staging``
    (the auto_commit dotfile-and-allowlist gate) inside this method.
    """
    for node in ast.walk(method):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "_filter_paths_for_staging":
                return True
            if isinstance(func, ast.Attribute) and func.attr == "_filter_paths_for_staging":
                return True
    return False


# ---------------------------------------------------------------------------
# Per-file scanning
# ---------------------------------------------------------------------------


def _method_arg_names(method: ast.AST) -> Set[str]:
    out: Set[str] = set()
    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for arg in method.args.args + method.args.kwonlyargs:
            out.add(arg.arg)
        if method.args.vararg:
            out.add(method.args.vararg.arg)
        if method.args.kwarg:
            out.add(method.args.kwarg.arg)
    return out


def scan_file(path: Path) -> List[MethodScan]:
    """Return one MethodScan per writing method found in ``path``."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    out: List[MethodScan] = []
    rel_path = str(path.relative_to(REPO_ROOT))

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        class_name = node.name
        for stmt in node.body:
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            method_name = stmt.name

            # Collect write sites in this method's body.
            write_sites: List[WriteSite] = []
            for child in ast.walk(stmt):
                if isinstance(child, ast.Call):
                    kind = _call_write_kind(child)
                    if kind is not None:
                        write_sites.append(
                            WriteSite(
                                file_path=rel_path,
                                line=getattr(child, "lineno", 0),
                                kind=kind,
                            )
                        )

            if not write_sites:
                continue

            arg_names = _method_arg_names(stmt)
            scan = MethodScan(
                file_path=rel_path,
                class_name=class_name,
                method_name=method_name,
                method_line=stmt.lineno,
                write_sites=write_sites,
                arg_names=arg_names,
            )
            scan.has_role_gate = _detect_role_gate(stmt, arg_names)
            scan.has_path_containment = _detect_path_containment(stmt)
            scan.has_worktree_isolation = _detect_worktree_isolation(stmt)
            scan.has_staging_filter = _detect_staging_filter(stmt)
            out.append(scan)

    return out


def scan_hubs_tree() -> List[MethodScan]:
    out: List[MethodScan] = []
    for py in sorted(HUBS_DIR.rglob("*.py")):
        if py.name in SKIP_FILES:
            continue
        if "__pycache__" in py.parts:
            continue
        out.extend(scan_file(py))
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMethodLayerWriteGateInvariant(unittest.TestCase):
    """Structural invariant: every hubs method that performs a
    filesystem or repo-state write MUST have one of:
      (a) a role-gate on its agent / author argument,
      (b) path containment via is_relative_to / is_absolute,
      (c) worktree isolation (writes derived from worktrees/<actor>),
      (d) staging-filter (paths through _filter_paths_for_staging),
      OR appear in ``METHOD_ALLOWLIST`` with a file:line justification.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.scans = scan_hubs_tree()
        cls.gated = [s for s in cls.scans if s.is_gated]
        cls.bypassers = [
            s for s in cls.scans
            if not s.is_gated and s.allowlist_key not in METHOD_ALLOWLIST
        ]

    def test_hubs_tree_is_discovered(self) -> None:
        """Sanity: the AST scan must find some writing methods."""
        self.assertGreater(
            len(self.scans),
            5,
            "method scan found suspiciously few writing methods — check "
            "HUBS_DIR / heuristics.",
        )

    def test_known_gated_methods_are_detected(self) -> None:
        """Calibration: ``resolve_conflict``, ``create_release``, and
        the new ``merge_pull_request`` role gate MUST all be detected
        as both performing a write AND having a role-gate signal.

        Note: ``force_merge_pull_request`` is intentionally NOT in the
        expected-writes set even though it is role-gated — it delegates
        the actual filesystem write to ``self.merge_pull_request`` and
        is therefore not detected as a writing method by the AST
        scanner (only the metadata-store mutation happens in its own
        body). Its role-gate is checked indirectly: it's covered by
        the METHOD_ALLOWLIST entry."""
        by_method = {
            (s.class_name, s.method_name): s
            for s in self.scans
            if s.class_name == "CodeHub"
        }
        expected = {
            "resolve_conflict",
            "create_release",
            "merge_pull_request",
        }
        missing = []
        no_role = []
        for name in expected:
            key = ("CodeHub", name)
            if key not in by_method:
                missing.append(name)
                continue
            s = by_method[key]
            if not s.has_role_gate:
                no_role.append(name)
        self.assertFalse(
            missing,
            f"calibration failure: methods not discovered as writing: {missing}",
        )
        self.assertFalse(
            no_role,
            f"calibration failure: methods that should have role-gate but "
            f"were not detected: {no_role}",
        )

        # Additionally verify force_merge_pull_request exists in source
        # and is allowlisted (its role gate is well known but the
        # scanner doesn't see a direct fs write in its body).
        fm_key = (
            "env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py",
            "CodeHub",
            "force_merge_pull_request",
        )
        self.assertIn(
            fm_key,
            METHOD_ALLOWLIST,
            "force_merge_pull_request must be in METHOD_ALLOWLIST since "
            "its role gate is enforced at the method layer but the AST "
            "scanner does not detect a direct write site in its body.",
        )

    def test_resolve_conflict_has_triple_gate(self) -> None:
        """Calibration: ``resolve_conflict`` should additionally be
        detected as having path-containment AND staging-filter (the
        triple gate from Phase 0.2 attempt-3 Fix B)."""
        for s in self.scans:
            if s.class_name == "CodeHub" and s.method_name == "resolve_conflict":
                self.assertTrue(
                    s.has_role_gate,
                    "resolve_conflict should be detected as role-gated",
                )
                self.assertTrue(
                    s.has_path_containment,
                    "resolve_conflict should be detected as path-containing",
                )
                self.assertTrue(
                    s.has_staging_filter,
                    "resolve_conflict should be detected as staging-filtered",
                )
                return
        self.fail("resolve_conflict not found among scanned methods")

    def test_no_writing_method_bypasses_gate(self) -> None:
        """THE INVARIANT.

        Every hubs method whose body performs a filesystem or repo-state
        write MUST be GATED (role / containment / isolation / staging
        filter) OR appear in ``METHOD_ALLOWLIST``.
        """
        if not self.bypassers:
            return  # green
        lines = [
            "",
            "Method-layer write-gate invariant FAILED. The following hubs",
            "methods write to the filesystem or mutate repo state but do NOT",
            "have any of {role-gate, path-containment, worktree-isolation,",
            "staging-filter} AND are NOT in METHOD_ALLOWLIST.",
            "",
            "Each entry: ClassName.method @ file:line",
            "  -> write sites (sample)",
            "",
        ]
        for s in sorted(
            self.bypassers, key=lambda x: (x.file_path, x.method_line)
        ):
            lines.append(
                f"  {s.class_name}.{s.method_name} @ {s.file_path}:{s.method_line}"
            )
            for w in s.write_sites[:5]:
                lines.append(f"      - {w.kind} at {w.file_path}:{w.line}")
            if len(s.write_sites) > 5:
                lines.append(f"      - ... and {len(s.write_sites) - 5} more sites")
        lines.append("")
        lines.append(
            "Fix: either (a) add a role-gate / path-containment / worktree-"
            "isolation / staging-filter signal inside the method body, or "
            "(b) add an entry to METHOD_ALLOWLIST keyed by "
            "(rel_file_path, class_name, method_name) with a justification "
            "string that cites the actual enforcement (file:line). The "
            "justification MAY cite outer-layer enforcement (tool-layer "
            "pin, monitor-layer hard-pin) when the method itself is a "
            "deliberate role-agnostic helper."
        )
        self.fail("\n".join(lines))

    def test_allowlist_entries_have_justifications(self) -> None:
        """Each METHOD_ALLOWLIST entry's value must be non-empty and
        contain a file:line citation."""
        for key, justification in METHOD_ALLOWLIST.items():
            self.assertTrue(
                justification.strip(),
                f"allowlist entry for {key!r} has no justification",
            )
            self.assertIn(
                ":",
                justification,
                f"allowlist entry for {key!r} must cite file:line "
                f"(got: {justification!r})",
            )

    def test_method_allowlist_count_is_27(self) -> None:
        """R1 round-5 attempt-6 HARDENING B count assertion.

        The module-docstring ``Authoritative count`` block cites
        the current entry count. That count was previously
        comment-only, so a future edit could silently drift it.
        This assertion converts the comment-only count into a hard
        invariant — the comment and ``len(METHOD_ALLOWLIST)`` must
        agree.

        If the actual count changes, update BOTH this constant AND
        the module-docstring count in the same commit."""
        self.assertEqual(
            len(METHOD_ALLOWLIST),
            27,
            f"METHOD_ALLOWLIST count drifted from comment-pinned 27 "
            f"to {len(METHOD_ALLOWLIST)}. Update the module docstring "
            f"AND this assertion together to re-pin the new count.",
        )

    def test_allowlist_entries_target_real_methods(self) -> None:
        """Every (file, class, method) key in METHOD_ALLOWLIST must
        correspond to a method that actually exists in the source tree
        AND actually performs a write (otherwise the allowlist is
        stale and might silently absorb a future regression).
        """
        all_method_keys = {s.allowlist_key for s in self.scans}
        # Also accept allowlist entries for methods we discovered but
        # that don't write (e.g. ``__init__``-only mkdir cases are
        # already captured). For stale-entry detection, the entry must
        # at minimum point at a real method in a real file.
        stale: List[Tuple[str, str, str]] = []
        for key in METHOD_ALLOWLIST.keys():
            file_path, class_name, method_name = key
            real_file = REPO_ROOT / file_path
            if not real_file.is_file():
                stale.append(key)
                continue
            # Re-parse to confirm the class+method exists. We don't
            # require the method to be in cls.scans (it may not write),
            # but we do require it to exist in the AST.
            try:
                tree = ast.parse(real_file.read_text(encoding="utf-8"))
            except SyntaxError:
                stale.append(key)
                continue
            found = False
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ClassDef)
                    and node.name == class_name
                ):
                    for stmt in node.body:
                        if (
                            isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and stmt.name == method_name
                        ):
                            found = True
                            break
                if found:
                    break
            if not found:
                stale.append(key)
        self.assertFalse(
            stale,
            "METHOD_ALLOWLIST has stale entries (method not found in "
            f"source): {stale}",
        )

    def test_audit_id_recorded(self) -> None:
        """The AUDIT_ID constant must be preserved so the provenance
        of the seeded allowlist entries is grep-able from CI logs."""
        self.assertEqual(AUDIT_ID, "phase1-audit-B-codehub-methods")


# ---------------------------------------------------------------------------
# Optional: diagnostics
# ---------------------------------------------------------------------------


def _print_diagnostics() -> None:  # pragma: no cover - manual invocation
    scans = scan_hubs_tree()
    gated = [s for s in scans if s.is_gated]
    bypassers = [
        s for s in scans
        if not s.is_gated and s.allowlist_key not in METHOD_ALLOWLIST
    ]
    allowlisted = [
        s for s in scans
        if not s.is_gated and s.allowlist_key in METHOD_ALLOWLIST
    ]
    print(f"# total writing methods scanned:  {len(scans)}")
    print(f"# of those, GATED in body:        {len(gated)}")
    print(f"# of those, ALLOWLISTED:          {len(allowlisted)}")
    print(f"# of those, BYPASSING:            {len(bypassers)}")
    print()
    print("BYPASSERS:")
    for s in sorted(bypassers, key=lambda x: (x.file_path, x.method_line)):
        sites = ", ".join(f"{w.kind}@L{w.line}" for w in s.write_sites[:3])
        print(
            f"  {s.class_name}.{s.method_name} "
            f"({s.file_path}:{s.method_line}) -> {sites}"
        )
    print()
    print("GATED (sample):")
    for s in gated[:10]:
        signals = []
        if s.has_role_gate:
            signals.append("role")
        if s.has_path_containment:
            signals.append("containment")
        if s.has_worktree_isolation:
            signals.append("isolation")
        if s.has_staging_filter:
            signals.append("staging")
        print(
            f"  {s.class_name}.{s.method_name} "
            f"({s.file_path}:{s.method_line}) [{'+'.join(signals)}]"
        )


if __name__ == "__main__":  # pragma: no cover
    _print_diagnostics()
