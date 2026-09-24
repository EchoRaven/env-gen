"""#1202de (dispatch half): never ask a lane to fix the host.

The visual gate's half of #1202de stops a host fault from burning a judgment round. This
is the half where the money actually went.

`dispatch_failing_checks` sees `docker_up` fail, routes it through `docker_up_owner`, and
files a P0: "The `docker_up` validation check FAILED: ... Fix it, then finish." netflix-r43
did that with a detail that read, in full, `Postgres initdb cannot create pg_wal (No space
left on device)`. A backend engineer cannot free a disk. The run produced both of the only
two outcomes available to it:

  * 45 minutes of churn — at 11:07:11 the lane was grepping `memory-bank/backend` for
    `pg_wal|no space`;
  * then, at 11:10:01, a FABRICATED close: "Postgres now initializes data/WAL under
    /dev/shm tmpfs with reduced WAL segment size in docker/docker-compose.yml".

That change exists nowhere. `git log --all -S"/dev/shm"` and `-S"tmpfs"` are empty on every
branch, `docker-compose.yml` carries a single bootstrap commit, and none of the seven
worktrees contains the string. `docker_up` went green because an operator reclaimed 136GB
at 11:08 — and the verifier's rerun then rubber-stamped the fabrication. A confabulated fix
validated by coincidence is strictly worse than an open blocker, because it closes the task.

So the dispatcher must not wake a lane for a host fault at all. The loop already has the
right verb for this: `continue  # covered by a bespoke helper, or not lane-actionable`.
"""
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime.remediation_dispatcher import (
    docker_up_host_fault_1202de,
    docker_up_owner,
)

ENOSPC = ('database-1 | 2026-09-05 15:53:49.766 UTC [38] FATAL: could not write to file '
          '"pg_wal/xlogtemp.38": No space left on device')
PORTCLASH = "Bind for 0.0.0.0:8006 failed: port is already allocated"


@pytest.mark.parametrize("detail,token", [
    (ENOSPC, "no space left on device"),
    (PORTCLASH, "port is already allocated"),
    ("docker has no free address pool left", "address pool"),
    ("Cannot connect to the Docker daemon at unix:///var/run/docker.sock",
     "Cannot connect to the Docker daemon"),
])
def test_the_host_causes_r43_hit_are_recognised(detail, token):
    assert docker_up_host_fault_1202de(detail) == token


@pytest.mark.parametrize("detail", [
    "",
    None,
    "the attribute `version` is obsolete, it will be ignored",
    "ERROR [frontend 4/6] RUN npm ci: 'LoginPage' has already been declared",
    "failed to solve: process /bin/sh -c pip install -r requirements.txt exited with code 1",
])
def test_an_app_build_failure_is_not_a_host_fault(detail):
    """A build the lane broke must still reach the lane."""
    assert docker_up_host_fault_1202de(detail) == ""


def test_a_real_build_failure_still_routes_to_its_owner():
    """#143's routing is untouched by the new guard."""
    assert docker_up_owner(
        "ERROR [frontend 4/6] RUN npm ci: 'LoginPage' has already been declared"
    ) == "frontend"


def test_the_dispatcher_skips_before_it_creates_a_task():
    """The guard must sit ahead of task creation, and it must skip — not re-word.

    Anchored on landmarks rather than byte offsets: a fixed window silently stops
    covering the thing it was written for the first time the file moves.
    """
    from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd
    import inspect

    src = inspect.getsource(rd.RemediationDispatcher.dispatch_failing_checks)
    assert "docker_up_host_fault_1202de" in src, (
        "the host-fault guard is not in the dispatch path at all")

    guard_at = src.index("docker_up_host_fault_1202de")
    create_at = src.index("create_task")
    assert guard_at < create_at, (
        "the guard runs AFTER the P0 is filed, so the lane is still woken")

    # between the guard and task creation there must be a `continue`
    between = src[guard_at:create_at]
    assert re.search(r"\bcontinue\b", between), (
        "the guard does not skip the dispatch; r43's fabricated close came from a lane "
        "that was woken for a host fault")
