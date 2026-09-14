"""Per-agent workspace with a DATA-DRIVEN routing + write-scope table.

Each ``resolve(relpath)`` decision consults a single declarative
table (``ROUTING_TABLE`` below). Each table entry says:

  * which root the path lives under (``"code"`` per-worktree or
    ``"base"`` shared project root), AND
  * who is allowed to write there (``allowed_writers``).

Defaults for unmatched paths: ``"code"`` root, no write gate (safe
local — files created by an agent without a declared prefix stay
in its own worktree).

To add or change a route, edit ``ROUTING_TABLE`` and add a test in
``tests/test_workspace_routing.py``. There is no other place to
hide a routing decision OR a write-scope decision.

Quacks like ``workspace.Workspace`` for the file-tool surface — same
``root``, ``resolve(path)``, ``relative(path)``, ``contains(path)``,
``is_write_allowed(path, agent)`` interface — so existing tools
accept it without changes.
"""

from __future__ import annotations

import logging as _logging
import os as _os
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Tuple, Union


# Agents whose writes are not role-gated. ``orchestrator`` is the
# admin/coordinator and can repair any branch. ``worker``,
# ``analysis_worker``, ``review_worker`` are short-lived broad-scope
# agents that have always had unrestricted write access by design.
_BROAD_WRITERS: FrozenSet[str] = frozenset(
    {"orchestrator", "worker", "analysis_worker", "review_worker"}
)


def _writers(*extra: str) -> FrozenSet[str]:
    """Return a writer set = broad writers ∪ the given role-specific ids."""
    return _BROAD_WRITERS | frozenset(extra)


# Spawned short-lived lane helpers (latent today) — they assist the OWNING lane and
# share its write scope, but they are NOT coordinators.
_LANE_HELPER_WRITERS: FrozenSet[str] = frozenset({"worker", "analysis_worker", "review_worker"})


def _lane_writers(lane: str) -> FrozenSet[str]:
    """Writer set for LANE-owned application code: the owning lane (+ its spawned
    helpers) ONLY — deliberately EXCLUDING the coordinator broad-writers (orchestrator).

    User directive 2026-06-24 ("为什么是orchestrator在改代码"): the orchestrator diagnosed a
    backend column-name bug and PATCHED ``app/backend/custom_routes.py`` itself instead of
    re-waking the backend. That violates the builder/coordinator split (lanes are the
    DIRECT builders of their own code; orchestrator/debugger COORDINATE and DISPATCH) and
    is mechanically unsound — the orchestrator edits its OWN worktree copy, which then
    conflicts on merge to integration. A lane bug is re-routed to the owning lane via a
    dispatched remediation task (task_created → for-self wakeup re-wakes an idle lane)."""
    return _LANE_HELPER_WRITERS | frozenset({lane})


_FW_OWNED_MAP_CACHE: Optional[List[Tuple[str, FrozenSet[str]]]] = None
_FW_OWNED_WARNED = False   # #789: announce the degradation once, not per write


def _framework_owned_routes() -> List[Tuple[str, FrozenSet[str]]]:
    """CLASS B (#36): the canonical (prefix, framework-owned-basenames) list, reused
    from the conflict resolver's ownership map so the WRITE GUARD denies exactly what
    the resolver resolves framework-side (no divergence). Lazy + cached to avoid a
    module-load cycle. Empty on any import failure (fail-open — never wedge writes)."""
    global _FW_OWNED_MAP_CACHE
    if _FW_OWNED_MAP_CACHE is None:
        try:
            from ..agents.runtime.auto_commit import _OWNERSHIP
            _FW_OWNED_MAP_CACHE = [
                (prefix, fw_owned)
                for (_lane, (prefix, fw_owned, _lane_owned)) in _OWNERSHIP.items()
            ]
        except Exception as exc:
            # #789: this used to be a SILENT and STICKY fail-open, and the two combined into a
            # real (not hypothetical) way for the guard to switch itself off for good. This
            # function is lazy precisely BECAUSE it can be reached during module load — a call at
            # that moment raises, cached `[]`, and left every framework-owned file writable for
            # the rest of the process, after the cycle resolved, with no log line anywhere. The
            # prompt meanwhile tells the lane "the write is denied + discarded" (#788's shape,
            # but with a live enforcer that can vanish). Now only SUCCESS is cached, so a
            # load-time miss self-heals on the next call, and the degradation is announced once.
            # Still fail-open by design — the trade is unchanged, only its visibility.
            global _FW_OWNED_WARNED
            if not _FW_OWNED_WARNED:
                _FW_OWNED_WARNED = True
                _logging.getLogger(__name__).warning(
                    "WRITE GUARD DEGRADED (#789): the framework-owned ownership map could not be "
                    "loaded (%s: %s), so writes to framework-owned files are NOT being denied. "
                    "Failing open on purpose (never wedge writes); retrying on the next call. If "
                    "this repeats, the lane can overwrite main.py/models.py/Dockerfile and the "
                    "prompt's \"the write is denied + discarded\" is false.",
                    type(exc).__name__, exc)
            return []
    return _FW_OWNED_MAP_CACHE


# (prefix, target, allowed_writers, notes)
# target ∈ {"code", "base"}.
# allowed_writers:
#   * ``None``           → ungated; anyone with the workspace can write.
#   * ``FrozenSet[str]`` → only the listed agent ids may write.
#   * ``frozenset()``    → READ-ONLY for everyone (an attempt is an error).
#
# Order matters — first match wins. Put longer / more specific
# prefixes FIRST so they shadow broader ones. E.g. ``app/backend/``
# must precede ``app/``.
ROUTING_TABLE: Tuple[Tuple[str, str, Optional[FrozenSet[str]], str], ...] = (
    # ------ base-root control files — READ-ONLY to ALL agents ------
    # attempt-6 R1 round-5 BLOCKER fix (2026-05-29): the base-root
    # default writer set was ``None`` (ungated), so ANY relative path
    # at the project base that didn't match a named route was silently
    # writable by any agent. PoC: an agent writes
    # ``base/run_budget.json`` with ``{"caps": {"unlimited": true}}``
    # and on the next tick the orchestrator's
    # ``_load_run_budget_caps`` re-reads it (orchestrator.py:614),
    # defeating the kill-switch and re-opening unbounded LLM spend.
    # Same hole exposed ``.checkpoint.json`` (session checkpoint),
    # ``project.json`` (project metadata), ``team_practices.json``
    # (team practices) and ``logs/`` (orchestrator logs). The
    # orchestrator writes these via raw ``Path(...).write_text`` (see
    # orchestrator.py:1349 ``_write_run_budget``), NOT through the
    # PathRoutedWorkspace, so locking them down to ``frozenset()``
    # blocks agents without breaking the operator/orchestrator path.
    # MUST appear at the top of the table so it shadows any later
    # entry; first-match-wins.
    # attempt-6 had 5 brittle named control-file routes here. R1 round-6
    # caught that ".team_practices.json" (real file has leading dot,
    # orchestrator.py:198) and ".checkpoint.json.bak" (CheckpointManager
    # backup, checkpoint.py:177) were not covered, and the entire CLASS of
    # other base files (foo.json, secrets/x.txt) was still open via
    # _DEFAULT_WRITERS = None. attempt-7 replaces all 5 with a structural
    # fail-closed default for base paths (see _DEFAULT_BASE_WRITERS
    # below). The 5 names are NOT removed for "we don't need them anymore" —
    # they were the wrong tool. A named-route denylist always misses the
    # leading-dot / .bak / new-control-file class. The fail-closed default
    # catches them by construction.
    # ------ operator-only, READ-ONLY to ALL agents ------
    # MUST be first so it shadows any later route. The actual allowlist
    # file does NOT live inside the workspace at all (loaded via the
    # ENVGEN_ALLOWED_CODE_CHECKS_FILE env var, see user_gates.py); this
    # routing entry is defense-in-depth so that even if an operator copies
    # a YAML into the workspace tree, no agent can write to it.
    (".gates/",       "base", frozenset(),           "code_check allowlist — operator-only, read-only to agents"),
    # ------ per-agent code (role-gated) ------
    ("app/backend/",  "code", _lane_writers("backend"),   "backend implements API; per-worktree — coordinators DISPATCH, never patch"),
    ("app/frontend/", "code", _lane_writers("frontend"),  "frontend implements UI; per-worktree — coordinators DISPATCH, never patch"),
    ("app/database/", "code", _lane_writers("database"),  "database implements schema/seed; per-worktree — coordinators DISPATCH, never patch"),
    ("app/",          "code", _BROAD_WRITERS,        "app/* catch-all — broad writers only"),
    # ------ shared (project root), role-gated ------
    # design/ holds README.md + the kickoff-coordinator-authored reference image
    # manifest + (Design-Prep) the design_analyst's design_system.json / crops /
    # component_specs. RegistryHub / WorkHub are the source of truth for the
    # contract — these on-disk artifacts are supplementary. The one-shot
    # design_analyst OWNS design/design_system.json + design/crops/, so it must be
    # a writer here (else its write-scope gate fails closed and the whole
    # measure-per-component phase silently produces nothing).
    ("design/",       "base", _writers("backend", "frontend", "design_analyst"),
                                                     "supplementary artifacts (README + reference images + Design-Prep design_system/crops)"),
    ("docker/",       "base", _writers("backend", "frontend", "database", "verifier"),
                                                     "compose / runtime files (any infra-aware agent)"),
    ("scripts/",      "base", _writers("verifier"),  "verification scripts"),
    ("tasks/",        "base", _writers("verifier"),  "task definitions / suites"),
    # Kickoff briefings/milestones/roadmap. orchestrator.py authors via
    # raw Path.write_text (bypasses routing); agents are read-only.
    ("docs/",         "base", frozenset(),           "kickoff-authored briefings/milestones/roadmap — orchestrator-owned, read-only to agents"),
    # ------ shared (project root), per-agent file, ungated ------
    # Knowledge/memory bank lives at the project base (one file per
    # agent, e.g. .memory/<agent>.knowledge.jsonl). Anchored at base so
    # it is co-located and survives worktree cleanup, matching the
    # memory module which writes via base_dir directly. MUST stay
    # "base" — routing it to "code" splits it from the memory module.
    (".memory/",      "base", None,                  "per-agent knowledge / memory bank — shared base, each writes own file"),
    # ------ shared (project root), READ-ONLY ------
    ("screenshots/",  "base", frozenset(),           "reference screenshots — read-only"),
    ("references/",   "base", frozenset(),           "UI-uploaded refs — read-only"),
    ("mockups/",      "base", frozenset(),           "design mockups — read-only"),
    ("images/",       "base", frozenset(),           "shared image assets — read-only"),
    ("shared/",       "base", frozenset(),           "hub state — canonical writes via HubRegistry only"),
)
# attempt-7 R1 round-7 correction: _DEFAULT_TARGET STAYS "code" —
# reverting an attempt-7-initial over-reach. The security fix lives
# in _DEFAULT_BASE_WRITERS = frozenset() below; flipping the target
# was unnecessary for security AND broke the agent-owns-its-worktree
# model (README.md, STRUCTURE.md, scratch.txt, .gitignore at worktree
# root are non-routed but legitimate writes — the generated project
# actually puts README.md + STRUCTURE.md there).
#
# Why the security fix doesn't need the target flip: the base-poisoning
# exploit goes through ABSOLUTE paths landing in base_root. The
# _route_of_resolved branch sees the resolved path under base_root,
# matches no prefix, and falls through to _DEFAULT_BASE_WRITERS =
# frozenset() — exploit blocked. _DEFAULT_TARGET only governs UNMATCHED
# RELATIVE routing, and a relative path can't reach actual base control
# files (it resolves into the agent's own worktree). So target="code"
# preserves the agent-owns-worktree model with zero security cost.
_DEFAULT_TARGET: str = "code"
# attempt-7 (R1 round-6 structural fix): split the default-writers
# constant into two roots. Code remains ungated (agent owns its own
# worktree, no need to enumerate writable files there). Base goes
# FAIL-CLOSED — any unrouted base path is read-only for all agents.
# This catches the entire CLASS of "agent writes a base-root file
# it shouldn't" instead of trying to hand-list every such file
# (attempt-6 tried and missed .team_practices.json + .checkpoint.json.bak
# + the open class). Legitimate per-agent base writes go through the
# explicit .memory/ route below.
_DEFAULT_CODE_WRITERS: Optional[FrozenSet[str]] = None  # ungated (agent owns worktree)
_DEFAULT_BASE_WRITERS: Optional[FrozenSet[str]] = frozenset()  # fail-closed (read-only to all agents)
# Back-compat alias: _DEFAULT_WRITERS still resolves to the code default
# for any caller that historically read it (the only path that hit the
# alias was _match_route's relative-path fallback, which is code-targeted).
_DEFAULT_WRITERS: Optional[FrozenSet[str]] = _DEFAULT_CODE_WRITERS

# Frontend-lane redirect: bare Vite-app paths the frontend authors at the repo
# root belong under ``app/frontend/`` (the build + delivery root). Dir prefixes
# and top-level files that constitute a Vite app — extend if a new standard
# Vite/React file shows up. (Routing happens only for the frontend lane and only
# for paths NOT already under ``app/``.)
_FRONTEND_APP_DIRS: Tuple[str, ...] = ("src/", "public/", "pages/", "components/")
_FRONTEND_APP_FILES: FrozenSet[str] = frozenset({
    "package.json", "package-lock.json", "index.html",
    "vite.config.js", "vite.config.ts", "tailwind.config.js", "tailwind.config.ts",
    "postcss.config.js", "eslint.config.js", "tsconfig.json", "tsconfig.node.json",
    "Dockerfile", "start.sh", "nginx.conf.template",
})


def _normalize_prefix(p: str) -> str:
    s = str(p).strip().lstrip("/")
    if s and not s.endswith("/"):
        s = s + "/"
    return s


class PathRoutedWorkspace:
    """``resolve(path)`` consults ``ROUTING_TABLE`` to decide whether a
    relative path lives under ``code_root`` (the agent's worktree) or
    ``base_root`` (the shared project root)."""

    def __init__(
        self,
        *,
        base_root: Union[str, Path],
        code_root: Union[str, Path],
        agent_id: Optional[str] = None,
        # Test-time override — production callers should NEVER pass this.
        # Add to ROUTING_TABLE instead.
        routing_table: Iterable[Tuple[str, str, Optional[FrozenSet[str]], str]] = ROUTING_TABLE,
    ):
        self._base = Path(base_root).resolve()
        self._code = Path(code_root).resolve()
        # Per-worktree isolation (attempt-5 Fix A / R1 round-4 hole A):
        # Identify which agent OWNS this workspace so we can reject
        # absolute / resolved paths that land in a sibling worktree's
        # tree (base_root/worktrees/<other_agent>/...). The relative
        # ``../<other_agent>/...`` spelling is already blocked by
        # per-route containment (fix #3), but the absolute spelling
        # of the same target previously slipped through the absolute
        # branch of ``resolve()`` because it landed in base_root and
        # had no explicit ``worktrees/`` route in the table.
        #
        # If the caller didn't pass an explicit agent_id, infer it
        # from the code_root layout: when code_root lives at
        # ``<base_root>/worktrees/<X>``, ``X`` is the self agent id.
        # Otherwise self_agent stays None and the cross-worktree
        # check is a no-op (e.g. non-worktree code_root geometries).
        self._self_agent: Optional[str] = agent_id
        if self._self_agent is None:
            try:
                rel = self._code.relative_to(self._base / "worktrees")
                # First path component under worktrees/ is the agent id.
                parts = rel.parts
                if parts:
                    self._self_agent = parts[0]
            except ValueError:
                self._self_agent = None
        normalized: List[Tuple[str, str, Optional[FrozenSet[str]]]] = []
        for entry in routing_table:
            prefix = _normalize_prefix(entry[0])
            target = str(entry[1]).lower()
            writers = entry[2] if len(entry) > 2 else None
            if not prefix:
                continue
            if target not in ("code", "base"):
                raise ValueError(
                    f"PathRoutedWorkspace: invalid route target {target!r} for "
                    f"prefix {entry[0]!r}; expected 'code' or 'base'"
                )
            if writers is not None and not isinstance(writers, frozenset):
                writers = frozenset(writers)
            normalized.append((prefix, target, writers))
        self._routes: Tuple[Tuple[str, str, Optional[FrozenSet[str]]], ...] = tuple(normalized)
        # Back-compat: keep the legacy ``_code_prefixes`` so any old
        # diagnostic code that pokes at this attribute still gets the
        # per-agent prefix list.
        self._code_prefixes: Tuple[str, ...] = tuple(
            p for p, t, _w in self._routes if t == "code"
        )
        self._base.mkdir(parents=True, exist_ok=True)
        self._code.mkdir(parents=True, exist_ok=True)

    # ------ Workspace-compat surface -------------------------------

    @property
    def root(self) -> Path:
        """Tree-traversal root. Returns the agent's CODE root because
        most tree-walking tools (Glob, project_structure) care about
        the agent's own changeable files, not the shared base."""
        return self._code

    @property
    def name(self) -> str:
        return self._code.name

    @property
    def base_root(self) -> Path:
        return self._base

    @property
    def code_root(self) -> Path:
        return self._code

    @property
    def agent_id(self) -> Optional[str]:
        """The owning agent id this workspace is built for.

        PR2.3.1 / Smoke #34: ``ensure_workspace_home`` reads
        ``workspace.agent_id`` to pick the per-agent sandbox HOME path
        ``<base_root>/.agent_homes/<agent_id>/`` (sibling of
        ``worktrees/``, NOT inside any worktree). Without this property
        the helper saw ``None`` and fell back to the legacy
        ``<code_root>/.agent_home/`` layout — which dirtied the
        worktree on every subprocess call, the very wedge PR2.3.1 was
        meant to close.
        """
        return self._self_agent

    def _sibling_worktree_owner(self, resolved: Path) -> Optional[str]:
        """If ``resolved`` lives under ``<base_root>/worktrees/<X>`` and
        ``X`` is NOT this workspace's owner, return ``X``. Otherwise None.

        Used to plug attempt-5 Fix A (R1 round-4 hole A) — the absolute
        spelling of a peer-worktree path landed under base_root with no
        named ``worktrees/`` route in the table, so it fell through to
        the ungated base default. This helper lets the absolute-branch
        of ``resolve()`` and the resolved-route lookup reject those
        landings explicitly with a clear cross-worktree message.

        attempt-6 R1 Residual 1 fix (2026-05-29): when ``self_agent`` is
        ``None`` (production caller did not pass ``agent_id`` AND the
        code_root layout does not match ``base/worktrees/<X>`` so the
        inference fallback also fails), the previous behaviour was to
        return ``None`` ("no cross-worktree violation detected") — this
        FAILED OPEN. A workspace with unknown owner could resolve into
        ANY sibling worktree because the gate had nothing to compare
        against. Now we FAIL CLOSED: if the resolved path lands under
        ``worktrees/<owner>`` and we don't know our own identity, we
        return that owner so the absolute-branch of ``resolve()`` and
        ``_route_of_resolved()`` both refuse the access with a clear
        error rather than silently letting it through the ungated base
        default.
        """
        base = self._base.resolve()
        worktrees_dir = (base / "worktrees").resolve()
        try:
            rel = resolved.relative_to(worktrees_dir)
        except ValueError:
            return None
        parts = rel.parts
        if not parts:
            return None
        owner = parts[0]
        if self._self_agent is None:
            # No self identity known — fail closed. Returning the owner
            # forces the caller's cross-worktree check to refuse the
            # access; the alternative (returning None) silently allows
            # arbitrary sibling-worktree reach for any workspace built
            # without agent_id and with non-standard code_root.
            return owner
        if owner == self._self_agent:
            return None
        return owner

    def _frontend_app_redirect(self, as_str: str) -> str:
        """Redirect the frontend lane's BARE Vite-app paths under ``app/frontend/``.

        The frontend agent perceives its root as ``.`` and naturally authors a
        Vite app at the repo root (``src/App.jsx``, ``package.json``, …). Those
        bare paths fall to the worktree-root default, but the docker build and the
        delivery gate use ONLY ``app/frontend/`` — so the real app was invisible
        (blank-shell ``frontend_navigable``) and, worse, the wrong-root
        ``src/App.jsx`` collided with integration's as an unresolvable add/add
        merge conflict that WEDGED the whole run in idle ticks (run #7). Routing
        these to ``app/frontend/`` at the resolution boundary makes the lane build
        in the right place from the start — reads and writes stay consistent
        because both flow through here. Paths already under ``app/`` (or
        ``shared/``/``design/``/dotfiles) are untouched; only the frontend lane is
        affected."""
        if not (self._self_agent and self._self_agent.startswith("frontend")):
            return as_str
        if as_str.startswith("app/") or as_str.startswith("."):
            return as_str
        if as_str.startswith(_FRONTEND_APP_DIRS) or as_str in _FRONTEND_APP_FILES:
            return "app/frontend/" + as_str
        return as_str

    def _match_route(
        self, path: Union[str, Path, None]
    ) -> Tuple[str, str, Optional[FrozenSet[str]]]:
        """Find the matching route entry for ``path``.

        Returns ``(normalized_path, target, allowed_writers)``.
        Unmatched paths default to ``(path, _DEFAULT_TARGET, _DEFAULT_WRITERS)``.
        Absolute paths bypass the table — they return target='' to
        signal "no route lookup; caller handles".
        """
        if path is None or path == "":
            return ("", "code", None)
        p = Path(str(path))
        if p.is_absolute():
            return (str(p), "", None)
        as_str = str(p).replace("\\", "/").lstrip("/")
        as_str = self._frontend_app_redirect(as_str)
        for prefix, route_target, writers in self._routes:
            if as_str == prefix.rstrip("/") or as_str.startswith(prefix):
                return (as_str, route_target, writers)
        return (as_str, _DEFAULT_TARGET, _DEFAULT_WRITERS)

    def _is_contained(self, resolved: Path, route_target: str) -> bool:
        """Return True iff ``resolved`` lives under the ROOT for its
        assigned route — NOT the OR of both roots.

        Under production geometry the per-agent ``code_root`` may be
        nested inside ``base_root`` (e.g. ``base/worktrees/<agent>``).
        A ``..``-escape from ``code_root`` then lands back inside
        ``base_root``; the old OR-of-both check would silently treat
        that as "contained" and let an agent reach ``shared/``,
        ``design/``, ``.gates/``, sibling worktrees, etc.

        Per-route containment closes the gap:
          * ``"code"`` route → MUST be inside ``code_root``.
          * ``"base"`` route → MUST be inside ``base_root``.
          * unknown / unrouted target → fail-closed.
        """
        if route_target == "code":
            return resolved.is_relative_to(self._code.resolve())
        if route_target == "base":
            return resolved.is_relative_to(self._base.resolve())
        # Unknown / unset route — fail closed.
        return False

    def _route_of_resolved(
        self, resolved: Path
    ) -> Tuple[str, str, Optional[FrozenSet[str]]]:
        """Determine the routing entry the RESOLVED path lives under.

        Used by ``is_write_allowed`` to re-derive the write-scope gate
        from the path's TRUE location, not the raw input string prefix
        (a raw-prefix lookup of ``"../screenshots/x"`` finds no
        read-only route and would silently allow the write, even though
        the resolved path lands inside the read-only ``screenshots/``
        route — that gap is what this helper closes).

        Returns ``(route_label, target, writers)`` where:
          * ``route_label == "code:<prefix>"`` → resolved is in code_root
                                                AND matched a code-routed
                                                table prefix (e.g. role-gated
                                                ``app/backend/``).
          * ``route_label == "code"``        → in code_root, no prefix matched
                                                (agent's own worktree scratch).
          * ``route_label == "base:<prefix>"`` → resolved matched a
                                                base-routed table prefix.
          * ``route_label == "base"``        → in base_root, no prefix matched.
          * ``route_label == "outside"``     → not in either root (caller rejects).

        Writers are re-derived from the FIRST matching table entry whose
        target matches the resolved location's root — so an attempted write
        to ``app/backend/x`` via a ``..``-escape (when permitted by the route
        geometry) still hits the role-gated writer set.
        """
        code = self._code.resolve()
        base = self._base.resolve()
        # attempt-5 Fix A (R1 round-4 hole A): defense-in-depth. If a
        # resolved path lands in a SIBLING worktree, return the closed
        # "outside" label so the write-gate fail-closes. ``resolve()``
        # already raises for this case, but routing should also refuse
        # to derive an ungated base default for a cross-worktree path.
        if self._sibling_worktree_owner(resolved) is not None:
            return ("outside", "", None)
        if resolved.is_relative_to(code):
            rel = resolved.relative_to(code)
            rel_str = str(rel).replace("\\", "/")
            for prefix, target, writers in self._routes:
                if target != "code":
                    continue
                if rel_str == prefix.rstrip("/") or rel_str.startswith(prefix):
                    return (f"code:{prefix}", "code", writers)
            # In code_root but no specific prefix — ungated default
            # (agent's own scratch space).
            return ("code", "code", _DEFAULT_CODE_WRITERS)
        if not resolved.is_relative_to(base):
            return ("outside", "", None)
        rel = resolved.relative_to(base)
        rel_str = str(rel).replace("\\", "/")
        for prefix, target, writers in self._routes:
            if target != "base":
                continue
            if rel_str == prefix.rstrip("/") or rel_str.startswith(prefix):
                return (f"base:{prefix}", "base", writers)
        # In base_root but no specific prefix — FAIL-CLOSED default
        # (attempt-7 R1 round-6: the entire CLASS of unrouted base paths
        # is read-only for agents. Legitimate per-agent base writes go
        # through .memory/ which has its own explicit route above).
        return ("base", "base", _DEFAULT_BASE_WRITERS)

    def resolve(self, path: Union[str, Path, None]) -> Path:
        """Resolve a user-provided path to an absolute file location.

        Walks ``ROUTING_TABLE`` top-to-bottom for the first prefix that
        matches. Unmatched paths fall through to ``_DEFAULT_TARGET``
        (``code`` — safe local default).

        Containment is enforced PER-ROUTE: a code-route input MUST
        resolve inside ``code_root``; a base-route input MUST resolve
        inside ``base_root``. ``..`` traversal from a code-route input
        that lands back inside ``base_root`` (possible under nested
        production geometry) is therefore rejected — the agent must
        reach base assets via the named route (e.g. ``shared/...``),
        not by escaping out of its worktree.
        """
        if path is None or path == "":
            return self._code
        # ``Path`` itself will raise ``ValueError`` on embedded NUL
        # ("\x00"); let that propagate as the containment failure.
        as_str, target, _writers = self._match_route(path)
        if target == "":
            # Absolute path — resolve symlinks, then enforce containment
            # against whichever root the absolute path claims to live in.
            resolved = Path(as_str).resolve()
            code = self._code.resolve()
            base = self._base.resolve()
            # attempt-5 Fix A (R1 round-4 hole A): the relative
            # ``../<other_agent>/...`` spelling is already blocked by
            # per-route containment (a code-route input must resolve
            # inside code_root). But the absolute spelling lands in
            # base_root with no named ``worktrees/`` route, so it
            # previously fell through to the ungated base default.
            # Reject cross-worktree landings explicitly BEFORE the
            # base-containment branch allows them through.
            sibling = self._sibling_worktree_owner(resolved)
            if sibling is not None:
                raise ValueError(
                    f"PathRoutedWorkspace: cross-worktree access forbidden "
                    f"— own worktree {self._self_agent!r} vs target {sibling!r} "
                    f"(path={str(path)!r}, resolved={resolved})"
                )
            if resolved.is_relative_to(code):
                inferred = "code"
            elif resolved.is_relative_to(base):
                inferred = "base"
            else:
                inferred = ""  # outside — _is_contained will reject
            if not self._is_contained(resolved, inferred):
                # A leading-slash path the agent means as PROJECT-ROOT-relative
                # (e.g. "/app/backend") is NOT a real host path — re-interpret it
                # as workspace-root-relative (chroot semantics) instead of treating
                # it as a host escape. Sibling-worktree escapes are already raised
                # above; `..` traversal stays caught (re-rooted path still fails
                # containment → the redacted error below, which never leaks the
                # host roots).
                rel = str(path).replace("\\", "/").lstrip("/")
                rerooted = (self._code / rel).resolve()
                # Only honor the chroot re-root when the target (or its parent,
                # for a new-file write) actually EXISTS in THIS workspace. A real
                # host path like /etc/passwd or /other/tmp has no in-workspace
                # counterpart → it stays rejected, preserving the
                # absolute-outside-is-rejected security invariant.
                if (self._is_contained(rerooted, "code")
                        and (rerooted.exists() or rerooted.parent.exists())):
                    return rerooted
                raise ValueError(
                    f"path {str(path)!r} is outside the project workspace "
                    f"and cannot be resolved relative to the project root"
                )
            return resolved
        root = self._code if target == "code" else self._base
        resolved = (root / as_str).resolve()
        if not self._is_contained(resolved, target):
            raise ValueError(
                f"path {str(path)!r} escapes its route's root "
                f"(route={target!r}) — use a path inside the project workspace"
            )
        return resolved

    def is_write_allowed(
        self, path: Union[str, Path], agent_id: Optional[str]
    ) -> bool:
        """Check whether ``agent_id`` may write to ``path`` per
        ``ROUTING_TABLE``'s ``allowed_writers`` column.

        IMPORTANT: the gate is evaluated on the RESOLVED path's route,
        re-derived from the real resolved location — NOT on the raw
        input string prefix. Otherwise a path like
        ``"../screenshots/foo"`` would have no raw-prefix match and
        be silently allowed, despite resolving into the read-only
        ``screenshots/`` route.

        Rules (post-resolve):
          * Resolved escapes workspace      → False.
          * Resolved in ``code_root``       → True (agent owns its worktree).
          * Resolved matches a base prefix:
              - ``writers is None``         → True (ungated).
              - ``writers == frozenset()``  → False (READ-ONLY).
              - ``agent_id in writers``     → True; else False.
              - ``agent_id is None`` and writers non-empty → False
                (writer-gated route needs an identity).
          * Resolved in base_root, no prefix match → True (ungated default).
        """
        try:
            resolved = self.resolve(path)
        except (ValueError, OSError):
            return False
        route_label, _target, writers = self._route_of_resolved(resolved)
        if route_label == "outside":
            return False
        # CLASS B (#36): the framework DETERMINISTICALLY generates + overwrites certain
        # files in app/backend & app/frontend (skeleton/infra). A lane editing one (run
        # #34: the backend rewrote the framework Dockerfile with a broken apt line) only
        # creates a merge conflict + a pre-overwrite broken build — it cannot stick (the
        # scaffold + the ownership resolver discard it). Deny ALL lane writes to those
        # framework-owned files (even in the lane's own worktree, where it otherwise owns
        # everything). Lane-owned files (custom_routes.py / App.jsx) + lane-authored
        # pages are NOT framework-owned, so they stay writable.
        if self.is_framework_owned(resolved):
            return False
        # Code- and base-routed entries both consult ROUTING_TABLE's
        # writer column from the RESOLVED path's matching prefix. A
        # raw-prefix lookup against the input string would let
        # ``"../screenshots/x"`` slip past the read-only gate.
        if writers is None:
            return True
        if not writers:
            return False  # explicit read-only route
        if agent_id is None:
            return False
        return agent_id in writers

    def is_lane_owned(self, path: Union[str, Path]) -> bool:
        """#1011: True if ``path`` belongs to a LANE — the mirror of `is_framework_owned`.

        The ownership map has always been enforced in one direction. `is_framework_owned`
        has a single call site that matters (`tooling.py`'s write guard) and it stops a LANE
        from touching framework files. Nothing ever asked the reverse question, so the
        framework's own writers overwrite lane files freely.

        Measured across all 164 generated projects (`tools/sweep_write_conflicts.py`), that
        costs roughly 22,000 alternating overwrites in the top 25 files alone:

            LoginPage.jsx     1162 framework / 1054 lane writes, 2004 alternations, 70 runs
            App.jsx            947 /  940, 1620 alternations,  93 runs   (lane-owned!)
            custom_routes.py   507 /  987,  795 alternations, 114 runs   (lane-owned!)

        Every contested file is already covered by the existing map — `_*_LANE_OWNED` plus
        `_FRONTEND_LANE_OWNED_DIRS` (src/pages/, src/components/, src/services/, …). This is
        purely an enforcement gap, not a coverage gap.
        """
        try:
            from ..agents.runtime.auto_commit import (  # local: avoids an import cycle
                _OWNERSHIP, _FRONTEND_LANE_OWNED_DIRS)
        except Exception:
            return False
        try:
            rel = self.relative(self.resolve(path)).replace("\\", "/")
        except (ValueError, OSError):
            return False
        for _lane, (prefix, _fw_owned, lane_owned) in (_OWNERSHIP or {}).items():
            if not rel.startswith(prefix):
                continue
            if rel.rsplit("/", 1)[-1] in (lane_owned or ()):
                return True
            tail = rel[len(prefix):]
            if any(tail.startswith(d) for d in (_FRONTEND_LANE_OWNED_DIRS or ())):
                return True
        return False

    def framework_may_write(self, path: Union[str, Path]) -> bool:
        """#1011: False when the framework would clobber existing lane work.

        Deliberately narrow — it blocks only when the file is lane-owned AND already exists
        with content. First-run scaffolding still works (nothing there yet), and a file the
        lane emptied is still repairable. What it stops is the tick-after-tick overwrite that
        deleted the frontend's componentised LoginPage 46 times in r164 while the lane kept
        rewriting it (#1010 fixed one classifier; this closes the class).
        """
        try:
            p = Path(self.resolve(path))
        except (ValueError, OSError):
            return True
        if not self.is_lane_owned(p):
            return True
        try:
            return not (p.is_file() and p.stat().st_size > 0)
        except Exception as _exc_1202bd:
            # #1202bd: this guard failed OPEN. By the time we are here the path is
            # KNOWN lane-owned, so "I could not tell whether it has content" was
            # answered with "go ahead and overwrite it" — the one outcome #1011 exists
            # to prevent, and the one the docstring above measures at 46 deleted
            # LoginPages in r164.
            #
            # The two directions are not symmetric. Refusing costs one tick: the
            # projection runs again every tick, which is the whole reason the clobber
            # loop exists at all. Allowing costs the work permanently — netflix-r32's
            # 138-line lane GenresPage survives in neither worktree nor any branch.
            # So an unreadable lane-owned path is treated as occupied.
            from .message_format import warn_once_1201
            warn_once_1201(
                "framework_may_write.stat",
                "the check for whether a lane-owned file already has content — "
                "refusing the framework write rather than risking a clobber",
                _exc_1202bd)
            return False

    def is_framework_owned(self, path: Union[str, Path]) -> bool:
        """CLASS B (#36): True if ``path`` is a framework-OWNED file in app/backend or
        app/frontend (the files the scaffold generates + overwrites every tick). Uses the
        SAME ownership map the conflict resolver resolves framework-side, so the write
        guard and the resolver never disagree. Lane-owned files (custom_routes.py /
        App.jsx) and lane-authored pages return False. Used both as the write-deny gate
        and to enrich the lane-facing denial message."""
        try:
            resolved = self.resolve(path)
        except (ValueError, OSError):
            return False
        rel = self.relative(resolved).replace("\\", "/")
        for prefix, fw_owned in _framework_owned_routes():
            if rel.startswith(prefix) and rel.rsplit("/", 1)[-1] in fw_owned:
                return True
        return False

    def relative(self, path: Union[str, Path]) -> str:
        """Path relative to whichever root contains it (for display)."""
        ap = Path(str(path)).resolve()
        try:
            return str(ap.relative_to(self._code))
        except ValueError:
            pass
        try:
            return str(ap.relative_to(self._base))
        except ValueError:
            return str(ap)

    def contains(self, path: Union[str, Path]) -> bool:
        ap = Path(str(path)).resolve()
        try:
            ap.relative_to(self._code)
            return True
        except ValueError:
            pass
        try:
            ap.relative_to(self._base)
            return True
        except ValueError:
            return False


# ---- #1202cw ----------------------------------------------------------------
# CLOBBERING LANE WORK MUST BE A DECLARED EXCEPTION, NOT THE DEFAULT.
#
# #1011 built `framework_may_write` to stop the framework overwriting lane files, citing
# 46 deleted LoginPages in r164, and `is_lane_owned` measured the cost across all 164
# generated projects: ~22,000 alternating overwrites in the top 25 files alone
# (LoginPage.jsx 1162 framework / 1054 lane writes over 70 runs; App.jsx 947/940 over 93;
# custom_routes.py 507/987 over 114). Its docstring concludes the ownership map is
# complete and this is "purely an enforcement gap".
#
# Then nothing called it: grepping the tree found one hit, the warning string inside its
# own body, while the projector modules performed 62 raw `Path.write_text` calls straight
# to lane files. r41 is what that costs. The frontend lane wrote the exact nav the judge
# had asked for — Home, Shows, Movies, Games, New & Popular, My List, Browse by Languages
# — and #520's projection replaced it with one assembled from the CAPTURE route table
# (/browse/card-hover, /browse/rate, /profiles). Seven screens share that header; all
# seven regressed in one round, and the run ended below its own round-3 peak.
#
# A handful of projectors DO overwrite lane files by design, and their tests say so
# ("the projection must still win until that decision is made"). Those decisions are
# preserved — but they must now be DECLARED. The default is refusal, so a projector
# written tomorrow is safe without its author knowing this file exists, and every
# surviving clobber names the ticket that argued for it. That inverts the failure mode:
# forgetting the guard used to destroy lane work silently, and now it only costs a tick.
#
# As narrow as #1011 in what it blocks: lane-owned AND already holding content. First-run
# scaffolding is untouched, and a file the lane emptied stays repairable.
_LANE_CLOBBERS_1202CW: Dict[str, Dict[str, int]] = {"refused": {}, "declared": {}}


def _app_relative_1202cw(path: Any) -> Optional[str]:
    """``app/...``-relative form of ``path``, or None when it is outside a generated app.

    Ownership is defined on that relative shape, so a projector holding an absolute
    worktree path can be classified without a workspace instance.
    """
    try:
        # normpath first: a projector composing "src/pages/../services/api.js" would
        # otherwise be classified by the segment it passed THROUGH, and the census would
        # key two names for one file.
        parts = list(Path(_os.path.normpath(str(path))).parts)
    except Exception:
        return None
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "app":
            return "/".join(parts[i:])
    return None


def path_is_lane_owned_1202cw(path: Any) -> bool:
    """True when ``path`` belongs to a lane, by the SAME map ``is_lane_owned`` consults.

    Mirrors that method exactly — prefix, then the lane-owned basename set, then the
    lane-owned directory list. An unknown path is NOT lane-owned: this must never stop
    the framework writing its own scaffold, the direction #1011 already errs in.
    """
    rel = _app_relative_1202cw(path)
    if not rel:
        return False
    try:
        from ..agents.runtime.auto_commit import (  # local: avoids an import cycle
            _OWNERSHIP, _FRONTEND_LANE_OWNED_DIRS)
    except Exception:
        return False
    try:
        for _lane, (prefix, _fw_owned, lane_owned) in (_OWNERSHIP or {}).items():
            if not rel.startswith(prefix):
                continue
            if rel.rsplit("/", 1)[-1] in (lane_owned or ()):
                return True
            tail = rel[len(prefix):]
            if any(tail.startswith(d) for d in (_FRONTEND_LANE_OWNED_DIRS or ())):
                return True
    except Exception:
        return False
    return False


def _calling_site_1202fc() -> str:
    """`module:function:line` of the framework code that attempted the write.

    #1202cw's own note says the `refused` bucket "should stay empty — a name appearing there
    is a projector clobbering lane work without having said why". netflix-r41 (live) put
    seven page files in it, and the line named every FILE and no ACTOR, so acting on the
    alarm meant reading 52 call sites in frontend_scaffold alone (only 20 of which declare
    `clobber_ok=`) and guessing which one it was.

    Naming the target and not the actor is the same shape as reporting a category without
    its instance, which this repo has removed in a dozen places -- arriving from one step
    further out.

    Walks past this module so the answer is the projector, not the guard. Best-effort: a
    diagnostic must never be the reason a write path raises.
    """
    try:
        import inspect
        _here = __name__
        for fr in inspect.stack()[1:8]:
            mod = fr.frame.f_globals.get("__name__", "")
            if mod and mod != _here:
                return "%s:%s:%d" % (mod.rsplit(".", 1)[-1], fr.function, fr.lineno)
    except Exception:
        pass
    return "an unidentified site"


def _scrubbed_1202mi(text: str, filename: str) -> str:
    """#1202mi: strip the framework's own ticket tags and past-run names from the
    comments and docstrings this write puts INSIDE the generated application.

    Applied here because this is the one point every projector write passes
    through, rather than at the ~140 template sites that would each have to
    remember. Never raises: a scrub that fails must not stop the projection.
    """
    try:
        from .provenance_scrub import scrub_provenance_1202mi
        return scrub_provenance_1202mi(text, filename)
    except Exception:
        return text


def framework_write_1202cw(path: Any, text: str, *, clobber_ok: str = "",
                           encoding: str = "utf-8") -> bool:
    """Write ``text`` to ``path``; refuse if that would clobber lane work.

    ``clobber_ok`` is the ticket that argued for overwriting lane files at THIS site
    (e.g. "#520: the lane nav did not converge across r91/r92"). Empty — the default —
    means refuse. Returns True when written; never raises, because a projector that
    cannot write must leave the lane's file alone and let the next tick try.
    """
    try:
        p = Path(str(path))
    except Exception:
        return False
    try:
        occupied = p.is_file() and p.stat().st_size > 0
    except Exception:
        # #1202bd's asymmetry: refusing costs one tick, allowing costs the work
        # permanently. An unreadable lane-owned path is treated as occupied.
        occupied = True
    if occupied and path_is_lane_owned_1202cw(p):
        key = _app_relative_1202cw(p) or str(p)
        bucket = "declared" if clobber_ok else "refused"
        _LANE_CLOBBERS_1202CW[bucket][key] = _LANE_CLOBBERS_1202CW[bucket].get(key, 0) + 1
        if not clobber_ok:
            if _LANE_CLOBBERS_1202CW["refused"][key] == 1:
                try:
                    _logging.getLogger(__name__).warning(
                        "#1202cw refused a framework write to lane-owned %s from %s — the "
                        "lane's version stands. A site that must overwrite declares why via "
                        "clobber_ok=.", key, _calling_site_1202fc())
                except Exception:
                    pass
            return False
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_scrubbed_1202mi(text, p.name), encoding=encoding)
        return True
    except Exception:
        return False


def lane_clobbers_1202cw() -> Dict[str, Dict[str, int]]:
    """{"refused": {path: n}, "declared": {path: n}}.

    ``declared`` is not a healthy/unhealthy signal — it is the census of overwrites the
    framework performs on purpose, which is the number #1011 measured at ~22,000 and
    which nothing has been able to see since.
    """
    return {k: dict(v) for k, v in _LANE_CLOBBERS_1202CW.items()}
