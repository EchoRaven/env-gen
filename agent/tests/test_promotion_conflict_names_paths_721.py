r"""#721: the refusal that exists to say WHY reported an empty reason.

#706's promotion logs a refusal `(False, info)` distinctly from a raised exception, on the
argument that the callee "declines and names why". r148 fired it and the reason was:

    promotion did not happen (promotion merge conflict: )

The class, and nothing after the colon. The cause is one word: it read `p.stderr`, and git does
not write conflicts there. Verified against a real conflict rather than assumed — two branches
editing one file, then `git merge`:

    rc = 1
    stdout:  Auto-merging f.txt
             CONFLICT (content): Merge conflict in f.txt
             Automatic merge failed; fix conflicts and then commit the result.
    stderr:  (empty)

So the detail was always going to be blank on the single failure mode this branch exists to
explain, in every run, forever.

The fix asks git for the paths instead of parsing its prose — `diff --name-only
--diff-filter=U` lists exactly the unmerged ones — and falls back to stdout, then stderr, then a
literal "no detail" so the message can never end in a bare colon again.
"""
import inspect
import subprocess
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime import auto_commit as ac


def _block() -> str:
    src = inspect.getsource(ac)
    i = src.index("#721: report the CONFLICTING PATHS")
    return src[i:src.index('return False, f"promotion merge conflict:', i)]


# --- the premise, checked against real git ------------------------------------------------------

def test_git_writes_conflicts_to_stdout_not_stderr(tmp_path: Path):
    """The whole fix rests on this; if git ever changes, the fallback order should too."""
    def g(*a):
        return subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, text=True)
    g("init", "-q", ".")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (tmp_path / "f.txt").write_text("base\n")
    g("add", "-A"); g("commit", "-qm", "base")
    g("checkout", "-qb", "other")
    (tmp_path / "f.txt").write_text("theirs\n")
    g("commit", "-qam", "theirs")
    g("checkout", "-q", "-")
    (tmp_path / "f.txt").write_text("ours\n")
    g("commit", "-qam", "ours")
    m = g("merge", "other")

    assert m.returncode != 0
    assert "CONFLICT" in m.stdout
    assert m.stderr.strip() == "", "stderr carried the conflict — revisit the fallback order"


def test_diff_filter_u_lists_the_unmerged_paths(tmp_path: Path):
    """The primary source the fix uses."""
    def g(*a):
        return subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, text=True)
    g("init", "-q", ".")
    g("config", "user.email", "t@t"); g("config", "user.name", "t")
    (tmp_path / "f.txt").write_text("base\n")
    g("add", "-A"); g("commit", "-qm", "base")
    g("checkout", "-qb", "other")
    (tmp_path / "f.txt").write_text("theirs\n"); g("commit", "-qam", "theirs")
    g("checkout", "-q", "-")
    (tmp_path / "f.txt").write_text("ours\n"); g("commit", "-qam", "ours")
    g("merge", "other")
    u = g("diff", "--name-only", "--diff-filter=U")
    assert u.stdout.strip() == "f.txt"


# --- the fix uses that source ---------------------------------------------------------------------

def test_it_asks_git_for_the_unmerged_paths():
    b = _block()
    assert '"diff", "--name-only", "--diff-filter=U"' in b


def test_it_counts_and_caps_the_paths():
    """#1203qd re-pointed the second assertion. It read `"_names[:6]" in b`, and the cut is
    now rendered by `join_capped` -- which keeps the bound AND declares the remainder, the
    thing #721's own log line was missing: 12 of 12 occurrences in the kept run logs say
    17-30 files and name six. The property here is unchanged ("must not flood the log"), so
    this asserts the bound in its new spelling rather than the old slice.
    """
    b = _block()
    assert "len(_names)" in b
    assert "cap=6" in b, "a hundred-file conflict must not flood the log"
    assert "_jc1203qd" in b, "the cut must be rendered by the shared owner (#1032)"
    assert "_names[:6]" not in b, (
        "a bare slice-join is the silent cut #1203qd removed; the cap belongs to join_capped")


def test_the_fallback_order_puts_stdout_before_stderr():
    b = _block()
    i, j = b.index("p.stdout"), b.index("p.stderr")
    assert i < j, "git writes the conflict to stdout; stderr is the last resort"


def test_it_can_never_end_in_a_bare_colon():
    assert '"no detail"' in _block()


def test_the_abort_still_runs():
    """The merge must still be undone regardless of what we managed to report."""
    src = inspect.getsource(ac)
    i = src.index("#721: report the CONFLICTING PATHS")
    tail = src[i:src.index("rev-parse", i)]
    assert '_run_git(["merge", "--abort"], cwd=repo)' in tail


def test_the_probe_cannot_break_the_refusal():
    b = _block()
    assert "try:" in b and "except Exception:" in b


# --- provenance -------------------------------------------------------------------------------------

def test_r148s_empty_message_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert 'r148 produced exactly "promotion merge conflict: "' in b


def test_the_verification_is_recorded_not_assumed():
    b = " ".join(_block().replace("#", " ").split())
    assert "Verified against a real conflict" in b
    assert "leaves stderr EMPTY" in b


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
