"""#1123: codehub_get_file_content could not succeed, and agents kept calling it.

It demands a PR id. The framework runs commit-only: every one of the 85 corpus runs
has an EMPTY pull_requests store (the single key in each is `_meta`) — which
`tool_bundles` already states outright, "impossible in commit-only mode".

Measured across the corpus: 83 calls in 31 runs (36%), and ZERO succeeded. Of the 80
recorded rejections, 76 passed 'main' and the rest 'agent/verifier' and
'agent/backend' — branch names, every one, because a branch is the only thing there is
to name when no PR exists.

A branch is exactly what `git show <ref>:<path>` takes, and the PR path already goes
through it with a commit sha. The agents were asking a well-formed question the tool
refused to hear.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.hub_registry import HubRegistry


def _git(repo, *args):
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.fixture
def codehub():
    tmp = Path(tempfile.mkdtemp(prefix="ch_1123_"))
    try:
        (tmp / "app").mkdir()
        (tmp / "app" / "main.py").write_text("print('hello')\n", encoding="utf-8")
        _git(tmp, "init", "-q")
        # this git predates `init -b`; name the branch before the first commit
        _git(tmp, "symbolic-ref", "HEAD", "refs/heads/main")
        _git(tmp, "add", "-A")
        _git(tmp, "commit", "-q", "-m", "initial")
        yield HubRegistry(tmp).codehub, tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_branch_name_now_resolves(codehub):
    """The corpus's dominant call: pr_id='main'."""
    ch, _tmp = codehub
    got = ch.get_file_content("main", "app/main.py")
    assert "error" not in got, "the only shape agents ever used still fails: %r" % got
    assert "hello" in got["content"]
    assert got.get("resolved_as") == "ref", "the caller is not told how it resolved"


def test_the_pull_requests_store_really_is_empty(codehub):
    """Guard the premise: if PRs ever start existing, this ticket's reasoning changes."""
    ch, _tmp = codehub
    prs = [p for p in (ch.stores.pull_requests.value() or {}).values()
           if isinstance(p, dict) and p.get("id")]
    assert prs == [], "a PR exists now; re-check #1123's commit-only premise"


def test_an_unresolvable_ref_says_there_are_no_prs_at_all(codehub):
    ch, _tmp = codehub
    got = ch.get_file_content("no-such-branch", "app/main.py")
    assert "error" in got
    msg = got["error"]
    assert "NO pull requests at all" in msg, (
        "the message still implies some other pr_id would work: %r" % msg
    )
    assert "read(file_path=" in msg, "it does not name a tool that does work"


def test_a_missing_path_on_a_real_ref_is_still_an_error(codehub):
    ch, _tmp = codehub
    got = ch.get_file_content("main", "app/nope.py")
    assert "error" in got


def test_a_real_pr_still_wins_over_a_same_named_branch(codehub):
    """The PR path is tried first and unchanged."""
    ch, tmp = codehub
    (tmp / "app" / "main.py").write_text("print('on the pr head')\n", encoding="utf-8")
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-q", "-m", "second")
    head = _git(tmp, "rev-parse", "HEAD").strip()
    _git(tmp, "checkout", "-q", "-b", "feature")
    _git(tmp, "checkout", "-q", "main")
    _git(tmp, "reset", "-q", "--hard", "HEAD~1")

    ch.stores.pull_requests.update(
        lambda m: m.set("main", {"id": "main", "head": head}, "t"),
        change_info={"agent": "t"})

    got = ch.get_file_content("main", "app/main.py")
    assert "error" not in got
    assert got.get("commit") == head, "the branch shadowed a real PR of the same name"
    assert "on the pr head" in got["content"]
