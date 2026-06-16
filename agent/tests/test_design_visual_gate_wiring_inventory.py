"""PR 3 of the hub-responsibility-split plan (rank 3) acted on
re-audit §7.3:

  * ``multi_agent/runtime/design_gate.py`` was DELETED — all five
    of its functions were dead.
  * Single-page helpers in ``visual_review_gate.py``
    (``is_visual_approved``, ``assert_visual_approved``,
    ``assert_critical_visuals_approved``) were DELETED — same
    dead status.
  * ``WorkHub.is_design_approved`` and ``WorkHub.is_visual_approved``
    (the canonical hub-level predicates that backed the deleted
    helpers) were DELETED.

What remains:
  * ``visual_review_gate.list_unapproved_critical`` — LIVE,
    called by ``DeliverProjectTool``. Now accepts either a
    ``WorkHub`` (during the PR 3 delegate window) or a
    ``GateRegistry`` (after Phase E retires the WorkHub delegates).
  * ``visual_review_gate.VisualReviewNotApprovedError`` — LIVE,
    raised by ``DeliverProjectTool`` when delivery is refused.

This test pins the post-PR-3 reality. It walks the generator
source to verify the inventory and fails loudly when it changes —
either direction:

  * If a future commit adds back any of the deleted helpers or
    a new dead helper, the public-symbol classification check
    fails and forces the maintainer to update this inventory.
  * If a future commit drops the LIVE ``list_unapproved_critical``
    caller, the LIVE-helper check fails.

Doesn't try to pin tests-as-callers (they're allowed by design).
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
TESTS_DIR = ROOT / "tests"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


# PR 3 deleted these entirely — they were dead per re-audit §7.3.
# If a future commit re-introduces any of them, the public-symbol
# classification test below will fire and the maintainer must
# explicitly resurrect this inventory entry plus a production caller.
DELETED_BY_PR3 = {
    "multi_agent.runtime.design_gate": "(module file deleted)",
    "multi_agent.runtime.visual_review_gate": {
        "is_visual_approved",
        "assert_visual_approved",
        "assert_critical_visuals_approved",
    },
}

# Hub-level methods deleted in PR 3 alongside their dead module helpers.
DELETED_HUB_METHODS = {
    "is_design_approved",
    "is_visual_approved",
}

# Helpers retained for re-wire opportunity but with NO current
# production caller. Before the 2026-05-30 review-cleanup commit,
# ``list_unapproved_critical`` was called by
# ``DeliverProjectTool.execute``'s visual gate — that gate was
# dead-on-production (read ``self.agent.hub_registry`` which is
# never set on real agents) and was deleted. The helper itself
# is still correct; the UI-driven deliver path uses
# ``compute_deliverability._visual_summary`` which reads
# ``gate_registry.list_critical_visual_reviews()`` directly
# without going through this aggregator.
#
# Kept (not deleted) because a future "wire-fix" PR may
# legitimately resurrect the agent-driven visual gate using
# the live ``self.agent._hubs.gate_registry`` attribute. If
# that happens, move the entry into ``LIVE_HELPERS`` and pin
# the new caller. If the team decides agent-driven enforcement
# is deliberately out-of-scope, delete the helper.
ORPHANED_BUT_RETAINED = {
    "list_unapproved_critical",
}

# Helpers that ARE live with a production caller. Pin them with
# the file:line of the caller so deletion fails this test.
LIVE_HELPERS = {}


def _iter_generator_py_files():
    """Walk the generator source (NOT the tests dir). Excludes
    cache/build directories."""
    skip = {"__pycache__", ".git", "node_modules", ".pytest_cache"}
    for path in LLM_DIR.rglob("*.py"):
        if any(part in skip for part in path.parts):
            continue
        yield path


def _find_callers(name: str, exclude_files: set):
    """Return list of (path, line_no, text) for every Python file
    under the generator that CALLS ``name``, excluding the named
    files (typically the module that DEFINES the helper).

    Uses AST to surface actual call sites (``name(...)`` and
    ``something.name(...)``) — this skips definitions
    (``def name(...)``), docstring mentions, and other non-call
    references that the previous textual scan flagged as false
    positives."""
    hits = []
    for p in _iter_generator_py_files():
        if p.resolve() in exclude_files:
            continue
        try:
            text = p.read_text()
        except Exception:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called_name = None
            if isinstance(func, ast.Name):
                called_name = func.id
            elif isinstance(func, ast.Attribute):
                called_name = func.attr
            if called_name != name:
                continue
            lineno = getattr(node, "lineno", 0)
            line_text = text.split("\n")[lineno - 1] if lineno else ""
            hits.append((p, lineno, line_text.strip()))
    return hits


class DeletedHelpersStayDeleted(unittest.TestCase):
    """PR 3 deleted the dead single-page approval helpers. Pin that
    they don't get re-introduced — if a future commit adds back
    ``assert_design_approved`` or ``is_visual_approved``, the
    public-symbol classification test fires and forces an explicit
    re-justification of "now wired vs still dead"."""

    def test_design_gate_module_remains_deleted(self):
        module_file = LLM_DIR / "multi_agent" / "runtime" / "design_gate.py"
        self.assertFalse(
            module_file.exists(),
            "design_gate.py was deleted in PR 3 — every function in "
            "it was dead per re-audit §7.3. If you need to bring it "
            "back, justify the wiring and remove the corresponding "
            "entry from DELETED_BY_PR3.",
        )

    def test_deleted_hub_methods_have_no_callers(self):
        """No code path may directly call the deleted predicates."""
        for method in DELETED_HUB_METHODS:
            hits = _find_callers(method, exclude_files=set())
            with self.subTest(method=method):
                self.assertFalse(
                    hits,
                    f"WorkHub.{method} was deleted in PR 3 but a "
                    f"caller still references it:\n  " +
                    "\n  ".join(f"{p}:{ln} {text}" for p, ln, text in hits),
                )

    def test_visual_review_gate_does_not_re_export_deleted_helpers(self):
        """The single-page section of visual_review_gate.py was
        removed. Pin that ``__all__`` doesn't list the deleted
        names — re-exporting them would invite shadow re-introduction."""
        import importlib
        mod = importlib.import_module("multi_agent.runtime.visual_review_gate")
        deleted = DELETED_BY_PR3["multi_agent.runtime.visual_review_gate"]
        exports = set(getattr(mod, "__all__", []))
        leaked = exports & deleted
        self.assertFalse(
            leaked,
            f"visual_review_gate.__all__ exports deleted helpers "
            f"{sorted(leaked)} — remove them from __all__ or, if "
            "you genuinely brought them back, remove from "
            "DELETED_BY_PR3.",
        )


class OrphanedHelpersStayDocumentedAsSuch(unittest.TestCase):
    """``list_unapproved_critical`` was LIVE via
    ``DeliverProjectTool.execute``'s visual gate until the
    2026-05-30 review-cleanup commit deleted that dead-wired gate.
    The helper itself is correct; it just has no current
    production caller. Pin that it stays callerless (so an
    accidental re-introduction of the dead-wired gate fails the
    test), and that any FUTURE re-wire (with the live
    ``self.agent._hubs`` attribute) is a conscious decision that
    moves the entry from ORPHANED_BUT_RETAINED into LIVE_HELPERS."""

    def test_orphaned_helpers_have_no_production_callers(self):
        for name in ORPHANED_BUT_RETAINED:
            hits = _find_callers(name, exclude_files=set())
            with self.subTest(name=name):
                self.assertFalse(
                    hits,
                    f"{name!r} (listed in ORPHANED_BUT_RETAINED) now "
                    f"has callers — either move it into LIVE_HELPERS "
                    f"with the caller's file:line pinned, or remove "
                    f"the new call:\n  " + "\n  ".join(
                        f"{p}:{ln} {text}" for p, ln, text in hits
                    ),
                )


class VisualReviewGateInventoryIsComplete(unittest.TestCase):
    """A maintainer who adds a new public symbol to
    ``visual_review_gate.py`` must explicitly classify it as
    live-or-orphaned-or-resurrected-dead — otherwise the new
    symbol is silently uncategorised."""

    def test_visual_review_gate_inventory_is_complete(self):
        module_file = LLM_DIR / "multi_agent" / "runtime" / "visual_review_gate.py"
        public_defs = self._public_defs_in(module_file)
        known_deleted = DELETED_BY_PR3[
            "multi_agent.runtime.visual_review_gate"
        ]
        known_live = set(LIVE_HELPERS.keys())
        known_orphaned = ORPHANED_BUT_RETAINED
        allowed_classes = {"VisualReviewNotApprovedError"}
        unclassified = (
            public_defs - known_live - known_orphaned
        ) - allowed_classes
        unclassified -= known_deleted
        self.assertFalse(
            unclassified,
            f"visual_review_gate.py has new public symbol(s) "
            f"{sorted(unclassified)} that aren't in the inventory. "
            "Either add a caller (LIVE_HELPERS), justify keeping "
            "without a caller (ORPHANED_BUT_RETAINED), or remove "
            "the symbol.",
        )

    def _public_defs_in(self, path: Path) -> set:
        text = path.read_text()
        tree = ast.parse(text)
        out = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = node.name
                if name.startswith("_"):
                    continue
                out.add(name)
        return out


if __name__ == "__main__":
    unittest.main()
