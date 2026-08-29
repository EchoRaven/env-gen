"""#1150: recover STRANDED FILES, not just stranded subtrees.

#691/#1148 are two symptoms of one mechanism: the framework's own delivery
commit lands on ``main`` while the run — and the release — live on
``integration``, so whatever that commit alone carries never ships.  #1148
checked whether a SUBTREE ROOT existed, so a present ``app/`` hid a missing
``app/database/init/01_init.sql``.  Measured on the kept repos:

    r5   main..integration 106   integration..main 1   files stranded: 0
    r8   main..integration  79   integration..main 1   files stranded: 0
    r11  main..integration 108   integration..main 1   files stranded: 2

r11's two were ``app/database/init/01_init.sql`` (which blocked 20 of that
run's 21 gate evaluations) and ``app/frontend/src/pages/LoginPage.jsx``
(which ``integration`` deliberately removed).  Recovering the first and
leaving the second alone is the whole contract.
"""
import subprocess
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import heal_pipeline as hp

SRC = Path(hp.__file__).read_text(encoding="utf-8")


def _g(repo, *a):
    return subprocess.run(["git", "-C", str(repo)] + list(a),
                          capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "gen"
    (r / "app" / "backend").mkdir(parents=True)
    # `git init -b` needs git >= 2.28; this box is older, and a failed init made
    # every later assertion fail with "not a git repository" rather than the thing
    # under test. Set the branch name the portable way.
    assert _g(r, "init", "-q").returncode == 0
    _g(r, "symbolic-ref", "HEAD", "refs/heads/main")
    _g(r, "config", "user.email", "t@t"); _g(r, "config", "user.name", "t")
    (r / "app" / "backend" / "main.py").write_text("x=1\n")
    _g(r, "add", "-A"); _g(r, "commit", "-qm", "bootstrap")
    _g(r, "branch", "integration")
    # The run — and the release — live on `integration`; `main` is where the
    # framework's orphan delivery commit lands. Stand where the delivery stands.
    _g(r, "checkout", "-q", "integration")
    return r


def _strand(repo, rel, body="-- seed\n"):
    """Commit `rel` on main only, in a framework-delivery commit."""
    _g(repo, "checkout", "-q", "main")
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    _g(repo, "add", "-A")
    _g(repo, "commit", "-qm", "framework delivery: backend skeleton + projections")
    _g(repo, "checkout", "-q", "integration")
    return _g(repo, "log", "--all", "--not", "integration", "--format=%H",
              "--grep=^framework delivery").stdout.split()


def test_the_orphan_query_finds_exactly_the_framework_commit(repo):
    shas = _strand(repo, "app/database/init/01_init.sql")
    assert len(shas) == 1, shas


def test_a_file_this_branch_never_knew_is_recoverable(repo):
    sha = _strand(repo, "app/database/init/01_init.sql")[0]
    rel = "app/database/init/01_init.sql"
    assert _g(repo, "cat-file", "-e", "integration:" + rel).returncode != 0
    assert not _g(repo, "log", "integration", "-1", "--format=%H", "--",
                  rel).stdout.strip()
    assert _g(repo, "checkout", sha, "--", rel).returncode == 0
    assert (repo / rel).exists()


def test_a_file_this_branch_deleted_on_purpose_is_left_alone(repo):
    """LoginPage.jsx's shape: integration KNOWS the file and removed it."""
    rel = "app/frontend/src/pages/LoginPage.jsx"
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("export default function L(){}\n")
    _g(repo, "add", "-A"); _g(repo, "commit", "-qm", "lane adds page")
    p.unlink()
    _g(repo, "add", "-A"); _g(repo, "commit", "-qm", "lane removes page")
    _strand(repo, rel, "stale\n")
    # absent from the tree, but the branch's history carries it -> deliberate
    assert _g(repo, "cat-file", "-e", "integration:" + rel).returncode != 0
    assert _g(repo, "log", "integration", "-1", "--format=%H", "--",
              rel).stdout.strip(), "history must record the deletion"


def _sweep_body():
    """Anchor on the ticket and stop at the loop it precedes (#943: never a
    fixed byte window)."""
    i = SRC.index("# #1150:")
    return SRC[i:SRC.index("for sub in _subs_1148:", i)]


def test_the_sweep_targets_the_framework_commit_not_every_branch():
    """A bare `--all --not HEAD` returns ~200 commits on r11 — every lane
    branch's un-merged WIP — and the one that matters sorts last."""
    body = _sweep_body()
    assert "--grep=^framework delivery" in body
    assert "--not" in body and "HEAD" in body


def test_the_sweep_keeps_its_two_safety_conditions():
    body = _sweep_body()
    assert "exists()" in body, "must skip files already in the working tree"
    assert 'log", "HEAD"' in body or '"log", "HEAD"' in body, \
        "must skip files this branch has known (deliberate deletion)"
    assert "app/" in body and "mcp_server/" in body and "docker/" in body


def test_the_sweep_cannot_break_the_delivery_commit():
    body = _sweep_body()
    assert "except Exception" in body and "debug(" in body
