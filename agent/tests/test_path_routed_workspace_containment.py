"""Adversarial containment tests for ``PathRoutedWorkspace``.

Phase 0.2 Fix 1 (reviewer audit 3.1 critical #1: path-traversal escape)
plus reviewer 2026-05-30 follow-up findings #1, #3, #4 — fixture is
PRODUCTION GEOMETRY (code_root = base_root/worktrees/<agent_id>) so
that the suite can catch the bypass class the original sibling
fixture was structurally incapable of catching.

Every test here exercises the security boundary of ``resolve()`` and
``is_write_allowed()``: a request that resolves OUTSIDE the route's
assigned root (``base_root`` for base-routed prefixes, ``code_root``
for code-routed prefixes) MUST be rejected, never silently served,
never fallback to a default.

Covered attack shapes:
  * ``..`` traversal (shallow, deep, post-prefix)
  * absolute paths outside both roots (e.g. ``/etc/passwd``)
  * symlink escape (a link inside the workspace pointing OUT)
  * NUL byte in path (POSIX-invalid)
  * Unicode NFD form of ``..`` (separately a normalization issue)
  * NESTED-GEOMETRY ``..`` from code_root that lands in base_root —
    must be rejected per-route (reviewer 2026-05-30 fix #3)
  * cross-agent worktree access (reviewer 2026-05-30 fix #3)
  * write-gate evaluated on RESOLVED path's route, not raw input
    prefix (reviewer 2026-05-30 fix #4)
  * ``.gates/`` operator-only read-only route exists (reviewer
    2026-05-30 fix #1)

Acceptance gate: ≥10 adversarial cases (Phase 0.2). This file is
well over that now (≥25 with the new regression tests).
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.path_routed_workspace import (  # noqa: E402
    PathRoutedWorkspace,
    ROUTING_TABLE,
)


class _WorkspaceFixture(unittest.TestCase):
    """Shared fixture: a ``base_root`` with ``code_root`` NESTED INSIDE.

    PRODUCTION GEOMETRY — reviewer 2026-05-30 required-fix #6:
    ``code_root = base_root/worktrees/<agent_id>``. Under this layout
    a single ``..`` from ``code_root`` lands BACK INSIDE ``base_root``;
    the per-route containment check (fix #3) must reject that, since
    a code-routed input must resolve inside ``code_root`` specifically,
    not "anywhere in either root".

    The previous sibling-fixture (``ws/base`` and ``ws/code`` as
    siblings) was structurally incapable of catching this bypass —
    a ``..`` from sibling-code went to ``ws/`` which is outside both
    roots, so a too-lax "in EITHER root" containment check would have
    passed the old suite. This fixture closes that gap.
    """

    def setUp(self) -> None:
        # Layout:
        #   <tmp>/base/                       <- base_root
        #   <tmp>/base/worktrees/             <- per-agent worktree dir
        #   <tmp>/base/worktrees/test_agent_001/  <- code_root (NESTED)
        #   <tmp>/outside/                    <- escape target outside both roots
        #
        # Containment must be per-route under this geometry:
        #   * code-routed input resolves to <code_root>/... or rejected
        #   * base-routed input resolves to <base_root>/... or rejected
        # A `..` escape from code_root that lands in base_root must be
        # rejected because the input claimed a code route.
        self._td = tempfile.TemporaryDirectory()
        td = Path(self._td.name)
        self.base = td / "base"
        self.base.mkdir(parents=True)
        self.worktrees = self.base / "worktrees"
        self.worktrees.mkdir(parents=True)
        self.code = self.worktrees / "test_agent_001"
        self.code.mkdir(parents=True)
        # Sibling worktree to test cross-agent access rejection.
        self.other_agent = self.worktrees / "test_agent_002"
        self.other_agent.mkdir(parents=True)
        (self.other_agent / "secrets.yaml").write_text("nope")
        # Outside-of-workspace area to use as escape target.
        self.outside = td / "outside"
        self.outside.mkdir(parents=True)
        (self.outside / "secret.txt").write_text("oops")
        self.ws = PathRoutedWorkspace(base_root=self.base, code_root=self.code)

    def tearDown(self) -> None:
        self._td.cleanup()


class ResolveRejectsPathTraversal(_WorkspaceFixture):

    # 1
    def test_dotdot_escape_relative(self):
        """Reviewer audit 3.1 #1: ``../../etc/passwd`` MUST be rejected —
        even under nested geometry, escapes beyond both roots fail."""
        with self.assertRaises(ValueError):
            self.ws.resolve("../../etc/passwd")

    # 2
    def test_dotdot_escape_deep(self):
        """Reviewer audit 3.1 #1: many ``..`` segments — escapes beyond
        both roots even if the prefix is valid."""
        with self.assertRaises(ValueError):
            self.ws.resolve("a/b/../../../../etc/passwd")

    # 3
    def test_dotdot_escape_after_valid_prefix(self):
        """Reviewer audit 3.1 #1: starts under a valid code route then
        escapes upward. Under nested geometry just one ``..`` past
        ``app/backend/`` lands back in ``code_root`` (still inside
        code_root, so allowed); enough ``..``s eventually escape — and
        per-route containment (fix #3) rejects landings outside code_root
        EVEN IF they're inside base_root."""
        with self.assertRaises(ValueError):
            self.ws.resolve("app/backend/../../../../etc/passwd")

    # 4
    def test_absolute_outside_root_rejected(self):
        """Reviewer audit 3.1 #1: ``/etc/passwd`` MUST be rejected,
        not silently returned."""
        with self.assertRaises(ValueError):
            self.ws.resolve("/etc/passwd")

    # 5
    def test_absolute_to_other_tempdir_rejected(self):
        """Reviewer audit 3.1 #1: an absolute path INSIDE the temp area
        but OUTSIDE both roots must still be rejected."""
        target = self.outside / "secret.txt"
        with self.assertRaises(ValueError):
            self.ws.resolve(str(target))


class ResolveAcceptsInsideWorkspace(_WorkspaceFixture):

    # 6
    def test_legitimate_relative_inside_code_root(self):
        """Reviewer audit 3.1 #1: relative path under a code route
        resolves inside code_root (positive: legitimate flow not broken)."""
        resolved = self.ws.resolve("app/backend/server.js")
        self.assertTrue(resolved.is_relative_to(self.code.resolve()))

    # 7
    def test_legitimate_nested_inside_code_root(self):
        """Reviewer audit 3.1 #1: deep nesting still inside code_root
        is fine (positive: legitimate flow not broken)."""
        resolved = self.ws.resolve("app/frontend/src/components/Button.tsx")
        self.assertTrue(resolved.is_relative_to(self.code.resolve()))

    # 8
    def test_legitimate_relative_inside_base_root(self):
        """Reviewer audit 3.1 #1: a ``design/`` path routes to base_root
        and is contained (positive: legitimate flow not broken)."""
        resolved = self.ws.resolve("design/spec.api.json")
        self.assertTrue(resolved.is_relative_to(self.base.resolve()))

    # 9
    def test_absolute_inside_code_root_allowed(self):
        """Reviewer audit 3.1 #1: an absolute path that LIVES inside
        code_root must work (positive: legitimate flow not broken)."""
        target = self.code / "app" / "backend" / "server.js"
        resolved = self.ws.resolve(str(target))
        self.assertEqual(resolved, target.resolve())

    # 10
    def test_absolute_inside_base_root_allowed(self):
        """Reviewer audit 3.1 #1: an absolute path that lives inside
        base_root (but not under the per-agent worktree) is still
        inside the workspace (positive: legitimate flow not broken)."""
        target = self.base / "design" / "spec.api.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}")
        resolved = self.ws.resolve(str(target))
        self.assertEqual(resolved, target.resolve())


class ResolveRejectsSymlinkEscape(_WorkspaceFixture):

    # 11
    def test_symlink_escape_inside_to_outside(self):
        """Reviewer audit 3.1 #1: a symlink created INSIDE the workspace
        that points OUT of it must be rejected when used as a resolve
        target — ``.resolve()`` follows symlinks so the resolved path
        lives outside. Defense-in-depth: the agent doesn't get to step
        outside even via a symlink they planted inside.

        R1 round-7: with ``_DEFAULT_TARGET = "code"`` restored, an
        unrouted relative top-level ``escape_link`` lands in
        ``code_root`` (the worktree), then resolve follows the symlink
        outside. The containment check rejects."""
        # Create the link under code_root pointing to ``self.outside``.
        link = self.code / "escape_link"
        try:
            os.symlink(str(self.outside), str(link))
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not supported on this platform")
        with self.assertRaises(ValueError):
            self.ws.resolve("escape_link/secret.txt")


class IsWriteAllowedContainment(_WorkspaceFixture):

    # 12
    def test_is_write_allowed_rejects_absolute_outside(self):
        """Reviewer audit 3.1 #1: the old code returned True for any
        absolute path — this is the very gap that finding flags. Must
        be False now."""
        self.assertFalse(self.ws.is_write_allowed("/etc/passwd", "backend"))

    # 13
    def test_is_write_allowed_rejects_absolute_outside_no_agent(self):
        """Reviewer audit 3.1 #1: even without an agent_id, an
        out-of-root absolute path is not writable (containment is
        unconditional)."""
        self.assertFalse(self.ws.is_write_allowed("/etc/passwd", None))

    # 14
    def test_is_write_allowed_accepts_absolute_inside_code(self):
        """Reviewer audit 3.1 #1: absolute paths INSIDE the workspace
        must still work — we only want to plug escapes, not break
        legitimate flows."""
        inside = self.code / "scratch.txt"
        self.assertTrue(self.ws.is_write_allowed(str(inside), "orchestrator"))

    # 15
    def test_is_write_allowed_accepts_absolute_inside_base_routed(self):
        """Reviewer audit 3.1 #1 + attempt-7 R1 round-6: absolute paths
        inside base_root that hit a routed prefix with the agent in the
        writer set must still work.

        attempt-7 calibration: an UNROUTED top-level base file
        (``shared_log.json``) is no longer writable by anyone — that's
        the structural fix. To test "absolute base inside is allowed
        for the right writer", use a path that matches a routed
        prefix (``design/`` is base-routed; after Round 8e.1 the
        writers are backend + frontend (plus broad writers like
        orchestrator) — design is no longer in the writer set since
        the design agent role was absorbed into backend/frontend)."""
        # design/ is a base route; frontend is a role-gated writer
        inside = self.base / "design" / "spec.api.json"
        self.assertTrue(self.ws.is_write_allowed(str(inside), "frontend"))

    # 15b (new — pins the structural fix itself)
    def test_is_write_allowed_rejects_unrouted_absolute_base(self):
        """attempt-7 R1 round-6 structural fix: unrouted top-level
        base files (anything not matching a route) are read-only by
        default. Previously these were ungated — the bug R1 caught."""
        for path in ("shared_log.json", "anything.json", "random.txt"):
            inside = self.base / path
            for agent in ("backend", "frontend", "design", "verifier",
                          "orchestrator"):
                self.assertFalse(
                    self.ws.is_write_allowed(str(inside), agent),
                    f"unrouted base file {path!r} must be read-only "
                    f"to agent {agent!r} (attempt-7 R1 round-6)",
                )


class ResolveRejectsExoticInputs(_WorkspaceFixture):

    # 16
    def test_null_byte_in_path(self):
        """Reviewer audit 3.1 #1: NUL is invalid in POSIX paths; Python
        ``Path`` raises ValueError on construction. Either way the call
        must NOT succeed."""
        with self.assertRaises((ValueError, OSError)):
            self.ws.resolve("foo\x00.py")

    # 17
    def test_unicode_nfd_dotdot_still_rejected(self):
        """Reviewer audit 3.1 #1: ``..`` in unicode-decomposed form
        should still be caught by the post-resolve containment check
        (it's two ASCII dots either way once normalized by the
        filesystem)."""
        nfd = unicodedata.normalize("NFD", "faè")
        with self.assertRaises(ValueError):
            self.ws.resolve(f"{nfd}/../../../etc/passwd")


# ============================================================================
# NEW regression tests for reviewer 2026-05-30 findings — the bypass class
# the original sibling-fixture suite was structurally incapable of catching.
# ============================================================================


class ProductionGeometryNestingBypass(_WorkspaceFixture):
    """Reviewer 2026-05-30 fix #3 regression: under PRODUCTION geometry
    (code_root nested inside base_root at base/worktrees/<agent>), a
    ``..`` from code_root lands BACK INSIDE base_root.

    The old too-lax "is inside EITHER root" containment check would
    silently let this through — letting an agent reach ``shared/``,
    ``design/``, ``.gates/``, sibling worktrees, etc. via traversal.

    Per-route containment (fix #3) closes this: a code-route input
    MUST resolve inside ``code_root`` specifically.

    These tests are the bypass that the original SIBLING fixture
    structurally could not catch.
    """

    def test_dotdot_from_code_into_base_rejected(self):
        """fix #3: code is base/worktrees/<agent>; ``../../shared/x``
        lands in base_root (which is "still inside workspace") but is
        NOT inside code_root — must be rejected because the input
        claimed a code route."""
        with self.assertRaises(ValueError):
            self.ws.resolve("../../shared/something")

    def test_dotdot_into_other_agent_worktree_rejected(self):
        """fix #3: cross-agent worktree access — my code is
        base/worktrees/test_agent_001; cannot reach
        base/worktrees/test_agent_002 via ``..``. The resolved path
        is still under base_root (under worktrees/) but is NOT under
        my own code_root."""
        with self.assertRaises(ValueError):
            self.ws.resolve("../test_agent_002/secrets.yaml")

    def test_dotdot_into_design_rejected(self):
        """fix #3: design/ is a base-routed prefix that must NOT be
        reachable from a code-route input via ``..``. The named
        ``design/...`` route is the only legitimate way."""
        with self.assertRaises(ValueError):
            self.ws.resolve("../../design/spec.api.json")

    def test_dotdot_into_gates_dir_rejected(self):
        """fix #3 + fix #1: the exact RCE delivery path the reviewer
        found — agent tries to write
        ``.gates/allowed_code_checks.yaml`` via ``..`` traversal from
        its code_root. Must be rejected on containment (the input
        looks like a code-route relative path that climbs out)."""
        with self.assertRaises(ValueError):
            self.ws.resolve("../../.gates/allowed_code_checks.yaml")

    def test_dotdot_just_one_level_into_worktrees_dir_rejected(self):
        """fix #3: even a single ``..`` from code_root lands in
        ``base/worktrees/`` — inside base_root but outside code_root.
        A code-route input claiming that location must be rejected."""
        with self.assertRaises(ValueError):
            self.ws.resolve("../some_other_file.txt")


class WriteGateResolvesBeforeRoute(_WorkspaceFixture):
    """Reviewer 2026-05-30 fix #4 regression: the write-gate must be
    evaluated against the RESOLVED path's route, NOT the raw input
    string prefix.

    The bypass: raw input ``"../screenshots/x.png"`` doesn't match the
    ``screenshots/`` prefix as a raw string (it starts with ``..``).
    A naive raw-prefix lookup finds no matching route, defaults to
    ungated, and allows the write — even though the path actually
    resolves into the ``screenshots/`` read-only route.
    """

    def test_raw_input_dotdot_screenshots_rejected_despite_raw_prefix(self):
        """fix #4: raw input is ``"../screenshots/x.png"`` whose raw
        string does NOT prefix-match the ``screenshots/`` route.
        But it resolves to a path inside the screenshots route
        (read-only). With per-route containment (fix #3) the
        ``..``-escape from code_root into base_root is rejected at
        resolve-time, so is_write_allowed sees the ValueError and
        returns False (also correct: the write is not allowed)."""
        self.assertFalse(
            self.ws.is_write_allowed("../screenshots/x.png", agent_id="someone")
        )

    def test_absolute_spelling_of_readonly_route_rejected(self):
        """fix #4: absolute path that lands in a read-only route
        (``screenshots/``) must be rejected on route lookup of the
        RESOLVED path, not raw input prefix. The raw input is an
        absolute path that does not start with any routing-table
        prefix, so a raw-prefix scan finds nothing; but after
        resolution the path lives in the read-only screenshots/
        route and the writer set is ``frozenset()``."""
        target = self.base / "screenshots" / "x.png"
        self.assertFalse(
            self.ws.is_write_allowed(str(target), agent_id="someone_unauthorized")
        )

    def test_absolute_spelling_of_shared_route_rejected(self):
        """fix #4: same shape for ``shared/`` (hub state, read-only).
        Raw input is an absolute path; the gate must look up the
        resolved path's route and find writers=frozenset()."""
        target = self.base / "shared" / "x.json"
        self.assertFalse(
            self.ws.is_write_allowed(str(target), agent_id="frontend")
        )

    def test_absolute_spelling_of_design_route_role_gated(self):
        """fix #4: a ROLE-gated base route must still gate on the
        resolved path. After Round 8e.1 the design/ writer set is
        backend + frontend (plus broad writers). ``frontend`` is a
        role-gated writer; ``knowledge``/``verifier``/``debugger`` are
        not in the writer set and must be rejected."""
        target = self.base / "design" / "spec.api.json"
        self.assertTrue(
            self.ws.is_write_allowed(str(target), agent_id="frontend")
        )
        for non_writer in ("knowledge", "verifier", "debugger"):
            self.assertFalse(
                self.ws.is_write_allowed(str(target), agent_id=non_writer),
                f"{non_writer!r} must NOT be in the design/ writer set "
                f"(Round 8e.1: writers are backend + frontend only)",
            )


class GatesRouteIsReadOnly(_WorkspaceFixture):
    """Reviewer 2026-05-30 fix #1 regression: ``.gates/`` is present
    in ``ROUTING_TABLE`` as a base-routed READ-ONLY entry. This is
    defense-in-depth so that even if an operator copies the YAML
    allowlist into the workspace tree, no agent can rewrite it
    (the real allowlist file is loaded from ENVGEN_ALLOWED_CODE_CHECKS_FILE
    OUTSIDE the workspace; this routing entry exists to neutralise
    the in-workspace copy as an RCE delivery vector)."""

    def test_gates_dir_is_in_routing_table(self):
        """fix #1: confirms the routing entry exists at (or near) the
        top of ROUTING_TABLE so it shadows any later route."""
        table = ROUTING_TABLE
        gates_entries = [e for e in table if e[0].startswith(".gates/")]
        self.assertTrue(
            gates_entries,
            ".gates/ must have a ROUTING_TABLE entry per fix #1",
        )

    def test_gates_dir_is_read_only(self):
        """fix #1: the .gates/ entry must have writers=frozenset()
        (READ-ONLY for all agents, no exceptions)."""
        table = ROUTING_TABLE
        gates_entries = [e for e in table if e[0].startswith(".gates/")]
        self.assertTrue(gates_entries)
        entry = gates_entries[0]
        writers = entry[2]
        self.assertEqual(
            writers,
            frozenset(),
            ".gates/ entry must be writers=frozenset() (read-only)",
        )

    def test_gates_dir_is_base_routed(self):
        """fix #1: the .gates/ entry must be base-routed so it lives
        at the project root (single canonical location), not per-worktree."""
        table = ROUTING_TABLE
        gates_entries = [e for e in table if e[0].startswith(".gates/")]
        self.assertTrue(gates_entries)
        entry = gates_entries[0]
        target = entry[1]
        self.assertEqual(target, "base", ".gates/ must be base-routed")

    def test_agent_cannot_write_gates_file(self):
        """fix #1: the RCE delivery path. An agent attempts to write
        ``.gates/allowed_code_checks.yaml``. Must be False (read-only)."""
        self.assertFalse(
            self.ws.is_write_allowed(
                ".gates/allowed_code_checks.yaml", agent_id="backend"
            )
        )

    def test_orchestrator_cannot_write_gates_file(self):
        """fix #1: even the broad-write orchestrator must NOT be able
        to write .gates/ — writers=frozenset() means no exceptions."""
        self.assertFalse(
            self.ws.is_write_allowed(
                ".gates/allowed_code_checks.yaml", agent_id="orchestrator"
            )
        )

    def test_absolute_path_to_gates_file_rejected(self):
        """fix #1 + fix #4: absolute spelling of the gates file must
        also be rejected — the write-gate looks up the RESOLVED path's
        route (.gates/ read-only), not the raw input prefix."""
        target = self.base / ".gates" / "allowed_code_checks.yaml"
        self.assertFalse(
            self.ws.is_write_allowed(str(target), agent_id="orchestrator")
        )

    def test_gates_entry_precedes_other_base_routes(self):
        """fix #1: ``.gates/`` should appear FIRST in the table so it
        shadows any later (broader) base-routed prefix that might
        accidentally include it. Defense-in-depth on table ordering.

        attempt-6 R1 round-5 update (2026-05-29): the base-root
        control-file entries (``run_budget.json``, ``.checkpoint.json``,
        ``project.json``, ``team_practices.json``, ``logs/``) now
        appear at the VERY TOP of the table — they are required to
        shadow the ungated base default. None of them overlap with
        ``.gates/`` (different prefix, no startswith collision), so
        the original ``.gates/``-shadow invariant is unaffected by
        the new entries. Only writable (non-frozenset) dot-prefixed
        base routes (e.g. ``.memory/``) must still come AFTER
        ``.gates/``.
        """
        table = ROUTING_TABLE
        gates_idx = next(
            (i for i, e in enumerate(table) if e[0].startswith(".gates/")),
            None,
        )
        self.assertIsNotNone(gates_idx)
        # Read-only fail-closed control entries that may legitimately
        # appear BEFORE .gates/ (they are themselves read-only and do
        # not overlap with .gates/, so order between them is moot).
        readonly_control_prefixes = {
            "run_budget.json",
            ".checkpoint.json",
            "project.json",
            "team_practices.json",
            "logs/",
        }
        for i, entry in enumerate(table):
            if i == gates_idx:
                continue
            if entry[1] == "base" and entry[0].startswith("."):
                if entry[0] in readonly_control_prefixes:
                    # .checkpoint.json is read-only and non-overlapping
                    # — ordering between read-only control entries and
                    # .gates/ is irrelevant.
                    continue
                # Other dot-prefixed base routes (e.g. .memory/) — order
                # doesn't strictly matter between non-overlapping prefixes,
                # but the gates entry should be first among them.
                self.assertGreater(
                    i,
                    gates_idx,
                    f".gates/ entry should precede other dot-prefixed base "
                    f"routes; found {entry[0]!r} at index {i} before .gates/",
                )


class CrossWorktreeAbsolutePathRejected(unittest.TestCase):
    """R1 round-4 Hole A: absolute-spelling cross-worktree write was
    bypassing the relative-spelling guard.

    Reproduces R1's live PoC: under production geometry where multiple
    agent worktrees share a base_root at ``<base>/worktrees/<agent>``,
    an agent could spell a peer's worktree as an ABSOLUTE path and have
    ``resolve()`` happily return it (no ValueError) and
    ``is_write_allowed`` return True — because the absolute branch only
    enforced containment against base-OR-code roots, and
    ``_route_of_resolved`` had no ``worktrees/`` route, so the path fell
    through to the ungated ``('base','base',None)`` default.

    The relative spelling (``../<other_agent>/...``) was correctly
    blocked by per-route containment; this regression test pins the
    absolute spelling to the SAME rejection so the two spellings agree.
    """

    def setUp(self):
        self.base = tempfile.mkdtemp()
        (Path(self.base) / "worktrees" / "agent_self").mkdir(parents=True)
        (Path(self.base) / "worktrees" / "agent_other").mkdir(parents=True)
        self.ws = PathRoutedWorkspace(
            base_root=Path(self.base),
            code_root=Path(self.base) / "worktrees" / "agent_self",
            agent_id="agent_self",
        )

    def test_absolute_to_sibling_worktree_REJECTED(self):
        """Reproduces R1's live PoC: absolute path to peer worktree must fail."""
        sibling = str(Path(self.base) / "worktrees" / "agent_other" / "pwned.py")
        with self.assertRaises(ValueError):
            self.ws.resolve(sibling)
        self.assertFalse(self.ws.is_write_allowed(sibling, "agent_self"))

    def test_absolute_to_own_worktree_ALLOWED(self):
        """Sanity: writes to OWN worktree still work."""
        mine = str(Path(self.base) / "worktrees" / "agent_self" / "foo.py")
        resolved = self.ws.resolve(mine)
        self.assertTrue(self.ws.is_write_allowed(mine, "agent_self"))

    def test_relative_dotdot_to_sibling_still_blocked(self):
        """Don't regress the relative-spelling block already in place."""
        with self.assertRaises(ValueError):
            self.ws.resolve("../agent_other/pwned.py")


if __name__ == "__main__":
    unittest.main()
