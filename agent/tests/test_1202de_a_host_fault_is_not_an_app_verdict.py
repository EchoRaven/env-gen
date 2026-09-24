"""#1202de: a host fault is not a verdict about the app.

#1202dc taught the gate to NAME a host-level boot failure — "port is already allocated",
"no space left on device" — instead of reporting the tail of docker's stderr. It changed
the WORDING and nothing else: `_compose_up` returns a string, and the one consumer folds
it into

    {"passed": False, "summary": f"visual gate could not boot app: {err}", "screens": []}

which is byte-identical in SHAPE to "the app is broken". So the classification was correct
and inert. Two runs paid for that:

  * netflix-r43 (port clash, 2026-09-04): the gate failed to boot 7 times, `_best_by_screen`
    stayed empty, plateau climbed to 7, and $400 bought zero scored screens.
  * netflix-r43 (disk full, 2026-09-05): the SAME tuple's next entry. `pg_wal` could not be
    written, and 39 `docker_up` attempts produced no judgment at all.

The gate already has the right category for this. `capture_unavailable` means "not a
judgment — the app wasn't reachable", and the handler refunds the attempt so the budget
only counts REAL verdicts. A host fault belongs in that category by construction: nobody
can score a screenshot of a container that could not start, and no lane can fix a full
disk.

What must NOT change: a compose failure that is genuinely the app's fault (a Dockerfile
that will not build) stays a real verdict, because that one IS the lane's to fix. The
discriminator is the daemon's own wording, which is what #1202dc already keys on — and a
deprecation warning must never qualify, the exact false positive #1202dc was written to
avoid.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    _boot_failure_result_1202de,
    _host_fatal_1202de,
)

DEPRECATION = (
    "yml: the attribute `version` is obsolete, it will be ignored, please remove it "
    "to avoid potential confusion"
)


@pytest.mark.parametrize("err,token", [
    ("port is already allocated — a HOST PORT this app's compose binds is taken by "
     "another container. Raw: Bind for 0.0.0.0:8006 failed", "port is already allocated"),
    ("no space left on device — the host disk is full. Raw: FATAL: could not write to "
     'file "pg_wal/xlogtemp.38": No space left on device', "no space left on device"),
    ("address pool — docker has no free address pool left", "address pool"),
    ("Cannot connect to the Docker daemon — the docker daemon is not reachable",
     "Cannot connect to the Docker daemon"),
])
def test_a_host_cause_is_recognised(err, token):
    assert _host_fatal_1202de(err) == token


@pytest.mark.parametrize("err", [
    DEPRECATION,
    "failed to solve: dockerfile parse error on line 3: unknown instruction RUNN",
    "no compose file at /x/docker/docker-compose.yml",
    "",
])
def test_an_app_fault_or_a_warning_is_not_a_host_cause(err):
    """The false positive #1202dc was written to avoid stays avoided."""
    assert _host_fatal_1202de(err) == ""


def test_a_host_fault_is_routed_to_the_refund_category():
    """`capture_unavailable` is the gate's existing 'not a judgment' channel."""
    r = _boot_failure_result_1202de("no space left on device — the host disk is full", [])
    assert r["capture_unavailable"] is True, r
    assert r["host_fatal"] == "no space left on device", r
    assert r["passed"] is False
    assert r["screens"] == []


def test_the_host_cause_still_leads_the_summary():
    """#1202dc's gain is kept: the reader still learns which host fault it was."""
    r = _boot_failure_result_1202de("no space left on device — the host disk is full", [])
    assert "no space left on device" in r["summary"]


def test_an_app_compose_failure_stays_a_real_verdict():
    """A Dockerfile the lane broke must still be judged and remediated as before."""
    r = _boot_failure_result_1202de("failed to solve: dockerfile parse error", ["login"])
    assert not r.get("capture_unavailable"), r
    assert not r.get("host_fatal"), r
    assert r["passed"] is False
    assert r["skipped"] == ["login"]
    assert "could not boot app" in r["summary"]
