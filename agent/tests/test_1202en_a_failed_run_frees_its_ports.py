r"""#1202en: a failed run keeps its stack up and blocks every later one.

The port guard is right to refuse:

    REFUSING: host port(s) 3001 8005 8006 are already bound by a running container

It is what stops two runs of one env from colliding -- the failure mode that once cost a
whole run. But nothing tears the stack down when a run ABORTS, so the guard turns a failed
run into a blocker for the next one until a human runs `docker compose down`.

Hit twice in one session: googlemaps-r16's no-convergence fail-fast left
`googlemaps-r16-database-1` holding 8006, and the following launch was refused.
`validation_runner` already ADVISES the operator to "stop the finished runs' stacks
(`docker compose down`, without `-v`)" -- advice, with nothing acting on it.

Only on failure. A delivered run's stack IS the artifact: you open the app on those ports
to see what shipped.
"""
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
ORCH = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
        / "orchestrator.py").read_text(encoding="utf-8")


def _teardown():
    i = ORCH.index("#1202en: A FAILED RUN MUST NOT HOLD THE PORTS")
    return ORCH[i:ORCH.index("#1175: stop the refresher", i)]


def test_it_only_runs_when_the_run_did_not_succeed():
    """A delivered run keeps its stack -- that is how you inspect what shipped."""
    assert "if not success:" in _teardown()


def test_it_takes_down_this_runs_own_compose_file():
    seg = _teardown()
    assert '"compose", "-f"' in seg
    assert "self.output_dir" in seg, "it must target THIS run's compose file, not a guess"
    assert '"down"' in seg


def test_it_does_not_remove_volumes():
    """`-v` would destroy the seeded database a post-mortem may still want."""
    assert '"-v"' not in _teardown()


def test_it_is_bounded_and_cannot_hang_the_exit():
    assert "timeout=" in _teardown()


def test_a_teardown_failure_is_reported_not_swallowed():
    """Silence here reproduces the bug: the next run is refused with no explanation."""
    seg = _teardown()
    assert "except Exception" in seg
    assert "REFUSED" in seg, "the operator must learn the ports are still held"


def test_it_runs_before_the_final_ledger_write():
    """So the record on disk describes a run whose stack is already down."""
    assert ORCH.index("#1202en: A FAILED RUN") < ORCH.index("#1175: stop the refresher")


def test_a_missing_compose_file_is_not_an_error():
    """A run that aborted before scaffolding has nothing to tear down."""
    assert "is_file()" in _teardown()


def test_the_executable_is_resolved_not_hardcoded():
    """#936b: the host may be podman. My first version wrote the binary literally and that
    ratchet caught it in the suite.

    Asserted on the COMMAND, not on the segment: `output_dir / "docker" / "docker-compose.yml"`
    is a directory name and entirely correct, and two earlier versions of this test failed on
    it and on the comment that quotes the command an operator would type by hand.
    """
    cmd = [l for l in _teardown().split("\n")
           if '"compose", "-f"' in l and not l.strip().startswith("#")]
    assert cmd, "the teardown command line moved"
    assert "runtime_bin" in cmd[0] or "_rt_1202en()" in cmd[0], cmd[0]
    assert '"docker", "compose"' not in cmd[0], cmd[0]
