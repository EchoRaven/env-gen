"""#1202fn -- compute_coverage's single ``app_root`` served two scans that need
DIFFERENT bases, so each of its two callers was right about one scan and wrong about
the other:

    base                    pages_without_files      dead_files
    <root>      (coverage)            0  correct     50  (phantoms under worktrees/)
    <root>/app  (delivery)           19  ALL FALSE   25  correct

The false 19 was published by deliverability_check as a delivery blocker. These tests
build the real layout on disk and assert the PROPERTY that matters: whichever base a
caller holds, the verdict is the same and it is the true one.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime.coverage_audit import (  # noqa: E402
    compute_coverage, scan_pages_without_files, _coverage_bases_1202fn)

PAGE_REL = "app/frontend/src/pages/HomePage.jsx"


class _Reg:
    def __init__(self, pages):
        self._p = pages

    def list_ui_pages(self):
        return self._p

    def __getattr__(self, n):           # no mcp/endpoint registries in this fixture
        raise AttributeError(n)


class _Hubs:
    def __init__(self, pages):
        self.registryhub = _Reg(pages)


@pytest.fixture
def out_root(tmp_path):
    """The framework layout: <root>/app/{backend,frontend} plus lane worktrees that
    are copies of the same app and must never be audited as the delivered tree."""
    root = tmp_path / "generated" / "env-r1"
    (root / "app" / "backend").mkdir(parents=True)
    (root / "app" / "frontend" / "src" / "pages").mkdir(parents=True)
    (root / PAGE_REL).write_text("export default function Home(){return <div/>}\n")
    (root / "app" / "frontend" / "src" / "App.jsx").write_text(
        "import Home from './pages/HomePage';\nexport default Home;\n")
    for lane in ("frontend", "backend", "verifier"):
        wt = root / "worktrees" / lane / "app" / "frontend" / "src" / "pages"
        wt.mkdir(parents=True)
        (wt / "OrphanCopy.jsx").write_text("export default function O(){return null}\n")
    return root


@pytest.fixture
def hubs():
    return _Hubs({"home": {"id": "home", "name": "home", "path": PAGE_REL}})


def test_both_callers_agree(out_root, hubs):
    """The two production callers hold different directories -- coverage_tools the
    output ROOT, deliverability the APP dir (#563 descends on purpose). They must not
    disagree about the same tree."""
    a = compute_coverage(hubs, out_root)
    b = compute_coverage(hubs, out_root / "app")
    assert len(a.pages_without_files) == len(b.pages_without_files), (
        f"callers disagree on pages: {a.pages_without_files} vs {b.pages_without_files}")
    assert len(a.dead_files) == len(b.dead_files), (
        f"callers disagree on dead files: {len(a.dead_files)} vs {len(b.dead_files)}")


@pytest.mark.parametrize("base", ["root", "app"])
def test_present_page_is_never_reported_missing(out_root, hubs, base):
    """The defect that blocked delivery: a page whose file is right there on disk was
    reported missing because the ``app/`` segment got joined twice."""
    root = out_root if base == "root" else out_root / "app"
    assert (out_root / PAGE_REL).is_file()          # the file really is present
    rep = compute_coverage(hubs, root)
    assert rep.pages_without_files == [], (
        f"declared page exists but was reported missing from base={base}: "
        f"{rep.pages_without_files}")


@pytest.mark.parametrize("base", ["root", "app"])
def test_worktree_copies_are_not_audited(out_root, hubs, base):
    """Lane worktrees are copies of the app; no lane worktree is ever a build context,
    so a file inside one is not a dead file of the delivered tree."""
    root = out_root if base == "root" else out_root / "app"
    rep = compute_coverage(hubs, root)
    inside = [d for d in rep.dead_files
              if "worktrees" in str(d.get("path") if isinstance(d, dict) else d)]
    assert inside == [], f"audited lane worktree copies from base={base}: {inside}"


def test_genuinely_missing_page_is_still_caught(out_root):
    """The check must keep its teeth: a registration with no file is still a lie."""
    hubs = _Hubs({"ghost": {"id": "ghost", "name": "ghost",
                            "path": "app/frontend/src/pages/GhostPage.jsx"}})
    for root in (out_root, out_root / "app"):
        rep = compute_coverage(hubs, root)
        assert len(rep.pages_without_files) == 1, (
            f"a page with no file must still be reported (base={root.name})")


def test_unrecognisable_layout_keeps_previous_behaviour(tmp_path):
    """We only override a base we can positively identify -- an unrecognisable
    directory must behave exactly as before, not guess."""
    d = tmp_path / "whatever"
    d.mkdir()
    assert _coverage_bases_1202fn(d) == (d, d)


def test_bases_resolve_from_either_direction(out_root):
    tree, decl = _coverage_bases_1202fn(out_root)
    assert (tree, decl) == (out_root / "app", out_root)
    tree, decl = _coverage_bases_1202fn(out_root / "app")
    assert (tree, decl) == (out_root / "app", out_root)


def test_scan_alone_still_takes_the_declaration_root(out_root, hubs):
    """Guard the low-level contract the fix relies on: ui_page paths are declared
    relative to the OUTPUT ROOT."""
    assert scan_pages_without_files(hubs, out_root) == []
    assert len(scan_pages_without_files(hubs, out_root / "app")) == 1
