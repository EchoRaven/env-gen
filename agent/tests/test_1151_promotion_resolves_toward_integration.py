"""#1151: the integration -> main promotion had never once succeeded.

#706 wired ``promote_integration_to_main`` so that `main` follows the release.
Across 213 kept run logs its success line appears ZERO times.  The only two
runs that ever reached the call site — r5 and r8, the two deliveries — both
came back "promotion merge conflict: 21 file(s)" / "22 file(s)", and `main`
stayed frozen at the orphan bootstrap commit in every repo (r5 106 behind,
r8 79, r11 108, 0 in sync).

A plain merge asks which side is right; the function's own docstring already
answers it — the release is CUT from integration and `main` FOLLOWS it — so
main's side of a conflicting hunk is the stale orphan.  Replayed against the
real r8 and r11 repos, the retry takes both to ``main..integration == 0``
while keeping every file that exists only on `main`.
"""
import subprocess
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime import auto_commit as ac


def _g(repo, *a):
    return subprocess.run(["git", "-C", str(repo)] + list(a),
                          capture_output=True, text=True)


@pytest.fixture
def diverged(tmp_path):
    """main and integration edit the same file, and main also holds a file
    integration has never seen — the measured shape of every generated repo."""
    r = tmp_path / "gen"
    r.mkdir()
    assert _g(r, "init", "-q").returncode == 0   # `git init -b` needs git >= 2.28
    _g(r, "symbolic-ref", "HEAD", "refs/heads/main")
    _g(r, "config", "user.email", "t@t"); _g(r, "config", "user.name", "t")
    (r / "shared.py").write_text("base\n")
    _g(r, "add", "-A"); _g(r, "commit", "-qm", "bootstrap")
    _g(r, "branch", "integration")

    # the orphan framework-delivery commit, on main only
    (r / "shared.py").write_text("stale orphan side\n")
    (r / "only_on_main.sql").write_text("-- seed\n")
    _g(r, "add", "-A")
    _g(r, "commit", "-qm", "framework delivery: backend skeleton + projections")

    # the run itself, on integration
    _g(r, "checkout", "-q", "integration")
    (r / "shared.py").write_text("the delivered side\n")
    _g(r, "add", "-A"); _g(r, "commit", "-qm", "lane work")
    return r


def test_a_plain_merge_really_does_conflict(diverged):
    """Guard the premise: without the retry there is nothing to fix."""
    _g(diverged, "checkout", "-q", "main")
    p = _g(diverged, "merge", "--no-ff", "-m", "x", "integration")
    assert p.returncode != 0
    _g(diverged, "merge", "--abort")


def test_promotion_now_completes(diverged):
    ok, info = ac.promote_integration_to_main(
        repo_root=diverged, actor="orchestrator", blessed_run_id="t")
    assert ok, info
    behind = _g(diverged, "rev-list", "--count", "main..integration").stdout.strip()
    assert behind == "0", "main must follow the release, was %s behind" % behind


def test_integration_wins_the_conflicting_hunk(diverged):
    ok, _ = ac.promote_integration_to_main(
        repo_root=diverged, actor="orchestrator", blessed_run_id="t")
    assert ok
    assert _g(diverged, "show", "main:shared.py").stdout == "the delivered side\n"


def test_a_file_only_on_main_is_not_dropped(diverged):
    """-X theirs resolves conflicting HUNKS; it must not cost main its own
    files. r11's main keeps the 2 files integration lacks after promotion."""
    ok, _ = ac.promote_integration_to_main(
        repo_root=diverged, actor="orchestrator", blessed_run_id="t")
    assert ok
    assert _g(diverged, "cat-file", "-e", "main:only_on_main.sql").returncode == 0


def test_the_success_path_names_how_it_resolved():
    """The outcome must not read like a clean fast-forward."""
    src = Path(ac.__file__).read_text(encoding="utf-8")
    i = src.index("def promote_integration_to_main(")
    body = src[i:src.index("\ndef ", i + 1)]
    assert "#1151" in body
    assert '"-X", "theirs"' in body
    assert "conflicts resolved toward" in body
