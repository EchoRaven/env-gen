"""#1114: the framework's own re-projection must not read as "the bug moved on".

`_stale_open_p0_evidence_1023` tells the assignee of an open P0 that "every affected
file changed since the evidence was taken" — grounds to re-verify. It decided that on
mtime. But the framework rewrites every file it OWNS on every tick, deterministically
and byte-identically, so those mtimes advance several times a minute on their own.

Measured live on the smoke-notes run: 17 commits in the tree, `git log --
app/backend/Dockerfile` naming exactly one of them, worktree clean against HEAD — and
#1023 announcing the host-seccomp P0 as "may already be resolved" at +0m, +2m, +3m,
+4m while `docker build` failed rc=1 one second after each report. Over those ticks the
report grew from 1-of-2 to 2-of-3 open P0s, i.e. it was on its way to covering all of
them.
"""
import os
import subprocess
import time

import pytest

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    _stale_open_p0_evidence_1023,
)

DOCKERFILE = "app/backend/Dockerfile"


def _git(repo, *args, when=None):
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    })
    if when is not None:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(when))
        env["GIT_AUTHOR_DATE"] = stamp
        env["GIT_COMMITTER_DATE"] = stamp
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _repo_with_dockerfile(tmp_path, body, when):
    (tmp_path / "app" / "backend").mkdir(parents=True)
    (tmp_path / DOCKERFILE).write_text(body, encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "initial", when=when)
    return tmp_path


def _task(ref):
    return {
        "created_at": ref,
        "metadata": {"bug_artifacts": {"affected_files": [DOCKERFILE]}},
    }


@pytest.fixture
def _needs_git():
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        pytest.skip("git unavailable")


def test_identical_bytes_rewritten_with_a_fresh_mtime_are_not_a_change(_needs_git, tmp_path):
    ref = time.time()
    body = "FROM python:3.11-slim\nRUN chmod +x /reset.sh\n"
    repo = _repo_with_dockerfile(tmp_path, body, when=ref - 600)

    # the framework re-projects: same bytes, new mtime. Nothing to commit.
    (repo / DOCKERFILE).write_text(body, encoding="utf-8")
    later = ref + 240
    os.utime(repo / DOCKERFILE, (later, later))

    assert _stale_open_p0_evidence_1023(_task(ref), repo) == "", (
        "a re-projection that wrote identical bytes was reported as the code having "
        "moved on — this is what told the backend lane its still-failing seccomp P0 "
        "'may already be resolved'"
    )


def test_a_real_edit_is_still_reported(_needs_git, tmp_path):
    """The signal must survive: #1114 removes false staleness, not the mechanism."""
    ref = time.time()
    repo = _repo_with_dockerfile(
        tmp_path, "FROM python:3.11-slim\nRUN chmod +x /reset.sh\n", when=ref - 600)

    (repo / DOCKERFILE).write_text(
        "FROM python:3.11-slim\nCOPY --chmod=755 reset.sh /reset.sh\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "drop the RUN chmod", when=ref + 600)
    later = ref + 600
    os.utime(repo / DOCKERFILE, (later, later))

    out = _stale_open_p0_evidence_1023(_task(ref), repo)
    assert DOCKERFILE in out, "a genuine content change stopped being reported: %r" % out
    assert "changed since the evidence was taken" in out


def test_an_unchanged_mtime_still_short_circuits(_needs_git, tmp_path):
    """The cheap mtime pre-filter stays first: no git call when nothing was touched."""
    ref = time.time()
    repo = _repo_with_dockerfile(tmp_path, "FROM python:3.11-slim\n", when=ref - 600)
    earlier = ref - 60
    os.utime(repo / DOCKERFILE, (earlier, earlier))

    assert _stale_open_p0_evidence_1023(_task(ref), repo) == ""


def test_without_a_repo_the_old_mtime_behaviour_is_kept(tmp_path):
    """git cannot answer -> None -> keep reporting, rather than silently losing a signal.

    Suppressing here would trade a false positive for a false negative, and #1023's whole
    posture is to hand the assignee evidence and let them decide.
    """
    (tmp_path / "app" / "backend").mkdir(parents=True)
    (tmp_path / DOCKERFILE).write_text("FROM python:3.11-slim\n", encoding="utf-8")
    ref = time.time() - 300
    later = time.time()
    os.utime(tmp_path / DOCKERFILE, (later, later))

    out = _stale_open_p0_evidence_1023(_task(ref), tmp_path)
    assert DOCKERFILE in out
