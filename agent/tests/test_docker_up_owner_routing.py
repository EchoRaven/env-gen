"""FIX #143 — content-based owner routing for docker_up build failures.

run-65 M4 live (2nd occurrence of the run-52 class): the frontend introduced
a syntax error (Unterminated regular expression in HomeFeedPage.jsx) during
visual-remediation churn → docker build broke at 06:05 → the docker_up
failing-check was dispatched to the VERIFIER (two-hop design: diagnose, then
file a bug to the owner). Under contention the verifier only filed that bug
47 minutes later — one minute before the 75-min no-convergence FAIL-FAST
killed the run. The build-error tail the framework ALREADY captures
(validation_runner: 3000-char up tail + container logs) names the offending
file — deterministic content classification can route the P0 DIRECTLY to the
owning lane, no LLM hop. Ambiguous tails keep the verifier route (the
2026-06-19 smoke-note concern: a lane without docker tools dead-ends — but a
tail that names file:line needs no docker tools to act on).
"""
import sys
import asyncio
from pathlib import Path
from types import SimpleNamespace

AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT))

from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd


VITE_TAIL = """#12 [frontend build 6/6] RUN npm run build
#12 3.417 > vite build
#12 4.102 x Build failed in 682ms
#12 4.103 error during build:
#12 4.103 [vite:esbuild] Transform failed with 1 error:
#12 4.103 /app/src/pages/HomeFeedPage.jsx:214:31: ERROR: Unterminated regular expression
failed to solve: process "/bin/sh -c npm run build" did not complete successfully: exit code: 1"""

PY_TAIL = """#9 [backend 5/6] RUN pip install -e .
#9 12.3 Traceback (most recent call last):
#9 12.3   File "/app/main.py", line 12, in <module>
#9 12.3 ModuleNotFoundError: No module named 'routers'
failed to solve: process "/bin/sh -c pip install -e ." did not complete successfully"""

AMBIGUOUS_TAIL = """failed to solve: rpc error: code = Unknown desc = failed to compute cache key
--- container logs (tail) ---
(empty)"""


def test_vite_error_routes_to_frontend():
    assert rd.docker_up_owner(VITE_TAIL) == "frontend"


def test_python_error_routes_to_backend():
    assert rd.docker_up_owner(PY_TAIL) == "backend"


def test_ambiguous_keeps_verifier():
    assert rd.docker_up_owner(AMBIGUOUS_TAIL) == "verifier"
    assert rd.docker_up_owner("") == "verifier"


def test_mixed_signals_keep_verifier():
    assert rd.docker_up_owner(VITE_TAIL + "\n" + PY_TAIL) == "verifier"


# ---------------------------------------------------------------------------
# dispatch-level: a docker_up fail with a vite tail lands on the frontend
# ---------------------------------------------------------------------------
class _WorkHub:
    def __init__(self):
        self.tasks = []

    def create_task(self, **kw):
        self.tasks.append(kw)
        return {"id": f"task_{len(self.tasks)}"}


class _Bus:
    def __init__(self):
        self.sent = []

    async def send(self, m):
        self.sent.append(m)


def _orch():
    wh = _WorkHub()
    return SimpleNamespace(
        hubs=SimpleNamespace(workhub=wh),
        message_bus=_Bus(),
        _current_milestone_version="v1.3.0",
        _check_owner_dispatched={},
        _logger=SimpleNamespace(warning=lambda *a: None,
                                error=lambda *a: None,
                                info=lambda *a: None)), wh


def _dispatch(detail):
    orch, wh = _orch()
    disp = rd.RemediationDispatcher(orch) if hasattr(rd, "RemediationDispatcher") else None
    if disp is None:  # dispatcher class name lookup
        for n in dir(rd):
            o = getattr(rd, n)
            if isinstance(o, type) and hasattr(o, "dispatch_failing_checks"):
                disp = o(orch)
                break
    data = {"checks": [{"name": "docker_up", "status": "fail", "detail": detail}]}
    asyncio.run(disp.dispatch_failing_checks(data))
    return wh.tasks, orch.message_bus.sent


def test_dispatch_docker_up_vite_assigns_frontend():
    tasks, sent = _dispatch(VITE_TAIL)
    assert len(tasks) == 1
    assert tasks[0]["assignee"] == "frontend"
    assert tasks[0]["priority"] == "P0"
    assert "HomeFeedPage.jsx" in tasks[0]["description"]
    assert len(sent) == 1 and sent[0].header.target_agent_id == "frontend"


def test_dispatch_docker_up_ambiguous_assigns_verifier():
    tasks, _ = _dispatch(AMBIGUOUS_TAIL)
    assert len(tasks) == 1
    assert tasks[0]["assignee"] == "verifier"
