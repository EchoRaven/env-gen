"""#1202iz: the build:* check that blocks delivery must record WHY it failed.

`_record_build_checks` derived four CodeHub checks from run_validation's report and wrote
`evidence={"source": "run_validation"}` — so the record was `status=failure, details=None`.

The reason sat one function away. validation_runner's `_add(name, ok, detail)` writes
`backend_health` failures as "/health not 200 within timeout. logs:\\n" plus 1200 characters
of the backend container's own log, fetched by a `docker logs --tail 30 backend` the
framework runs for exactly this purpose.

That record is what blocks delivery. r110's last gate evaluation before the watchdog fired:
`verification_checklist_not_ready — observed {'sql_syntax': 'success', 'docker_build':
'success', 'npm_install': 'success', 'backend_start': 'failure'}`. What reached the lane was
"FAILED: backend_health" and the suggested fix "Run and record verification/build checks
until checklist is ready for delivery" — the blocker restated, not a cause.
"""
import sys
import pathlib
import types

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.tools.validation_tools import RunValidationTool  # noqa: E402


class _Codehub:
    def __init__(self):
        self.records = []

    def record_check(self, **kw):
        self.records.append(kw)


def _tool(codehub):
    t = RunValidationTool.__new__(RunValidationTool)
    t._hubs = types.SimpleNamespace(codehub=codehub)
    return t


_BACKEND_LOG = ("/health not 200 within timeout. logs:\n"
                "Traceback (most recent call last):\n"
                '  File "/app/main.py", line 12, in <module>\n'
                "    from models import Video\n"
                "ImportError: cannot import name 'Video'")


def _run(checks):
    ch = _Codehub()
    n = _tool(ch)._record_build_checks({"checks": checks})
    return ch.records, n


def test_a_failing_check_carries_the_cause():
    recs, n = _run([
        {"name": "docker_up", "status": "pass", "detail": ""},
        {"name": "backend_health", "status": "fail", "detail": _BACKEND_LOG},
        {"name": "frontend_reachable", "status": "pass", "detail": ""},
        {"name": "business_writes_persist", "status": "pass", "detail": ""},
    ])
    assert n == 4
    backend = next(r for r in recs if r["name"] == "build:backend")
    assert backend["status"] == "failure"
    assert "ImportError" in backend["evidence"]["detail"], backend["evidence"]
    assert backend["evidence"]["from_check"] == "backend_health"


def test_a_passing_check_stays_lean():
    """A success needs no reason; carrying one would only grow every ledger."""
    recs, _ = _run([{"name": n, "status": "pass", "detail": ""} for n in
                    ("docker_up", "backend_health", "frontend_reachable",
                     "business_writes_persist")])
    for r in recs:
        assert r["status"] == "success"
        assert "detail" not in r["evidence"], r


def test_a_substituted_verdict_says_it_was_substituted():
    """`by_name.get(src, docker_up)` silently stands in for an ABSENT check. "backend_health
    failed" and "backend_health never ran and docker_up failed" are different repairs, and
    the old record could not tell them apart."""
    recs, _ = _run([{"name": "docker_up", "status": "fail",
                     "detail": "compose up returned 1"}])
    backend = next(r for r in recs if r["name"] == "build:backend")
    assert backend["status"] == "failure"
    assert backend["evidence"]["derived_from_docker_up"] is True
    assert "compose up returned 1" in backend["evidence"]["detail"]

    docker = next(r for r in recs if r["name"] == "build:docker")
    assert docker["evidence"]["derived_from_docker_up"] is False, docker["evidence"]


def test_the_mapping_did_not_change():
    """#1202iz rewrote the loop; the four components must still derive from the same checks,
    or the checklist reads a different app than it did before."""
    recs, _ = _run([{"name": n, "status": "pass", "detail": ""} for n in
                    ("docker_up", "backend_health", "frontend_reachable",
                     "business_writes_persist")])
    got = {r["name"]: r["evidence"]["from_check"] for r in recs}
    assert got == {"build:docker": "docker_up",
                   "build:backend": "backend_health",
                   "build:frontend": "frontend_reachable",
                   "build:database": "business_writes_persist"}


def test_the_detail_is_bounded():
    recs, _ = _run([{"name": "backend_health", "status": "fail", "detail": "x" * 9000}])
    backend = next(r for r in recs if r["name"] == "build:backend")
    assert len(backend["evidence"]["detail"]) <= 2000
