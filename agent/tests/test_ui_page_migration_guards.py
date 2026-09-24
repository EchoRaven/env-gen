"""B2 (2026-06-12): structural guards for the ui_page → registryhub migration.

Before any data-model change (phase A), freeze "who reads ui_page" so that an
A-phase wiring miss turns a test RED instead of silently leaving a stale reader
on the old workhub store.

Two guards:
  1. consumer inventory — every site that filters ``kind == "ui_page"`` by
     directly reading the pages store (bypassing the ``get_ui_pages()`` public
     method) must be in a known whitelist. A NEW direct reader (the classic
     "added X, didn't wire Y" regression) breaks this immediately.
  2. contract symmetry — registryhub must expose register/list/get ``ui_page``
     methods symmetric to its ``table`` contract. Marked xfail until A1 lands;
     flips to XPASS the moment A1 implements them (remove the decorator then).
"""

import re
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
LLM_GEN = AGENT_DIR / "env_generator" / "llm_generator"
sys.path.insert(0, str(LLM_GEN))

# Real-code (non-comment) occurrences of a kind==/!="ui_page" discriminator
# (coverage_audit filters with ``kind != "ui_page"``; others with ``==``).
_UI_PAGE_KIND_RE = re.compile(
    r"""kind["']?\s*\)?\s*[!=]=\s*["']ui_page["']|["']ui_page["']\s*[!=]=\s*[\w.()"']*kind"""
)


class UiPageConsumerInventoryTests(unittest.TestCase):
    """Freeze the set of files that discriminate kind=="ui_page" in real code.

    A2 (2026-06-12) repointed coverage_audit, hub_pulse, and
    workflow_policies at ``registryhub.list_ui_pages()`` (the registryhub
    ui_pages store is purely ui_pages, so no ``kind`` filter is needed) —
    they no longer discriminate ``kind`` and were removed from the WHITELIST.
    A3 (2026-06-12) made the RegistryHub the SOLE OWNER: workhub/service.py's
    update_ui_page/get_ui_pages became thin delegates to registryhub and no
    longer carry a ``kind=="ui_page"`` filter — so the WHITELIST is now EMPTY.
    A new direct ``kind=="ui_page"`` reader anywhere in the tree is a
    regression (it should read ``registryhub.list_ui_pages()`` instead).
    """

    WHITELIST: set = set()

    def _scan(self):
        base = LLM_GEN / "multi_agent"
        hits = {}
        for py in base.rglob("*.py"):
            if "/tests/" in str(py) or py.name.startswith("test_"):
                continue
            try:
                lines = py.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue
            for ln in lines:
                stripped = ln.strip()
                if stripped.startswith("#"):
                    continue  # skip comment lines
                if _UI_PAGE_KIND_RE.search(ln):
                    rel = str(py.relative_to(LLM_GEN))
                    hits.setdefault(rel, 0)
                    hits[rel] += 1
                    break
        return set(hits)

    def test_kind_filter_sites_frozen(self):
        found = self._scan()
        unexpected = found - self.WHITELIST
        self.assertEqual(
            unexpected, set(),
            f"NEW direct kind=='ui_page' reader(s) not in whitelist: {unexpected}. "
            "Either route them through get_ui_pages()/registryhub.list_ui_pages(), "
            "or add to WHITELIST with a migration note.")

    def test_whitelist_has_no_dead_entries(self):
        # Keep the whitelist honest — a file that no longer discriminates
        # ui_page should be removed (so it can't mask a future regression).
        found = self._scan()
        dead = self.WHITELIST - found
        self.assertEqual(
            dead, set(),
            f"WHITELIST entries no longer read kind=='ui_page': {dead} — remove them.")


class UiPageContractSymmetryTests(unittest.TestCase):
    """registryhub exposes ui_page contract methods mirroring its table
    contract (A1 landed 2026-06-12)."""

    def test_registryhub_exposes_ui_page_methods(self):
        from multi_agent.runtime.registryhub import RegistryHub
        for meth in ("register_ui_page", "list_ui_pages", "get_ui_page",
                     "register_ui_component", "list_ui_components",
                     "get_ui_component"):
            self.assertTrue(
                hasattr(RegistryHub, meth), f"RegistryHub missing {meth}")


class WorkHubUiPageDelegationTests(unittest.TestCase):
    """A3 (2026-06-12): WorkHub's ui_page methods are pure delegates to the
    RegistryHub (the sole owner) — they MUST reference ``self._registryhub`` and
    MUST NOT resurrect a local pages-store write. This freezes the delegation so
    a future edit that re-introduces dual storage turns this test RED."""

    def _source(self, fn):
        import inspect
        return inspect.getsource(fn)

    def test_workhub_ui_page_methods_are_pure_delegates(self):
        from multi_agent.runtime.hubs.workhub.service import WorkHub
        for meth in ("get_ui_pages", "get_ui_components",
                     "update_ui_page", "update_ui_component"):
            src = self._source(getattr(WorkHub, meth))
            self.assertIn(
                "self._registryhub", src,
                f"WorkHub.{meth} must delegate to self._registryhub (A3)")
            # No local dual-storage: a delegate must not write the pages store.
            self.assertNotIn(
                "self.stores.pages.update", src,
                f"WorkHub.{meth} must NOT write stores.pages — that would "
                f"resurrect dual ui_page storage (A3 made registryhub the owner)")


if __name__ == "__main__":
    unittest.main()
