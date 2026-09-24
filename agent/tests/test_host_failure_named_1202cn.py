"""#1202cn — say when the HOST is the problem, because no lane can fix it.

r37 ran 168 minutes and spent $371.74 over 4910 calls without ever reaching a single visual
judgment. Every `docker up` failed the same way, forty times: "could not find an available,
non-overlapping IPv4 address pool among the defaults" — Docker's pools run out near 31
networks and sixteen finished runs still held theirs. Nothing said so. The failure arrived as
a plain docker_up failure, the orchestrator kept escalating stalls and nudging silent lanes,
and the lanes kept being asked to fix an application that was never the problem.

tools/docker_tools.py already recognises two of these shapes for the tools an AGENT calls;
this is the path the FRAMEWORK calls, and it recognised none.

LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.validation_runner import _HOST_LEVEL_1202CN as H  # noqa: E402

VR = (LLM / "multi_agent" / "runtime" / "validation_runner.py").read_text(encoding="utf-8")

# The exact line r37's daemon produced, forty times.
R37 = ("failed to create network netflix-local-r37_default: Error response from daemon: "
       "could not find an available, non-overlapping IPv4 address pool among the defaults "
       "to assign to the network")


def _match(text):
    low = text.lower()
    return next((m for k, m in H.items() if k in low), None)


def test_the_r37_line_is_recognised():
    assert _match(R37) is not None


def test_the_r37_remedy_is_actionable():
    """The message is read by whoever has to clear it, so it must name the fix, not just the
    condition."""
    m = _match(R37)
    assert "docker compose down" in m and "network prune" in m


def test_the_remedy_preserves_data():
    """`down -v` would delete the volumes of every finished run, including the two that ever
    delivered. The remedy must not casually suggest that."""
    assert "without `-v`" in _match(R37) and "keeps the volumes" in _match(R37)


def test_the_other_host_shapes_are_recognised():
    for text in ("Cannot connect to the Docker daemon at unix:///var/run/docker.sock",
                 "write /var/lib/docker/tmp/x: no space left on device",
                 "driver failed programming external connectivity: port is already allocated"):
        assert _match(text) is not None, text


def test_an_ordinary_build_failure_is_NOT_called_a_host_problem():
    """THE control. Calling an app failure environmental would send the operator to the host
    while the lane stops being asked to fix real code — worse than saying nothing."""
    for text in ("npm ERR! code ELIFECYCLE\nvite build failed",
                 "ModuleNotFoundError: No module named 'app.routers.titles'",
                 "Error: Cannot find module '../components/CatalogExperience.jsx'",
                 "exit code 1: 3 tests failed"):
        assert _match(text) is None, text


def test_matching_is_case_insensitive():
    """The daemon capitalises differently across versions and verbs."""
    assert _match(R37.upper()) is not None


def test_it_announces_rather_than_aborts():
    """Aborting on a transient — a port freed a second later, a daemon restarting — would be
    worse than a wasted retry, and this repo has been burned acting on static inference."""
    i = VR.index("#1202cn this is a HOST failure")
    stanza = VR[VR.rindex("try:", 0, i):VR.index("except Exception:", i)]
    assert "_LOG.error" in stanza
    for word in ("raise", "sys.exit", "return None"):
        assert word not in stanza, word


def test_the_check_runs_on_the_full_transcript_not_the_tail():
    """The tail is truncated to ~900 chars by the salient-error extractor; the daemon's line
    can fall outside it, and a classifier that only sees the tail would miss its own case."""
    i = VR.index("_low = (_full or \"\").lower()")
    assert VR.index("_tail = ", 0, i) < i, "must read _full, which is set before _tail"
    assert "_tail.lower()" not in VR


def test_the_guard_cannot_take_the_run_down():
    i = VR.index("#1202cn this is a HOST failure")
    assert VR.rindex("try:", 0, i) < i < VR.index("except Exception:", i)
