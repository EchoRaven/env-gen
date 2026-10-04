r"""#1203e7: the blocker guarding the gate's probe evidence could not fire, and r152 shipped a 500.

    last_run = runhub.last_successful_run_since(session_start_ts)   # filters fail_count == 0
    ep_counts = _probe_counts(last_run.get("probes") if last_run else [])
    if ep_counts.get("failed", 0) > 0:
        blockers.append(f"latest run has {ep_counts['failed']} failed endpoint probe(s)")

`fail_count` counts exactly the failing probes, so `ep_counts["failed"]` on a run selected for
`fail_count == 0` is zero BY CONSTRUCTION. MEASURED across every gate ledger on disk: that prose
appears in **0 files**, and so does the MCP twin — against 47 files for "dead artifact" and 56 for
"no successful RunHub run", so the corpus does carry blocker prose and these two simply never
fired, in 191 runs.

★ r152 shipped through the hole, hours after #1203d6 made the battery probe at all.
`GET /api/users/suggested` (status `implemented`, so invisible to the prober before #1203d6) read
`pass/200` at 22:52 and then `fail/500` in six consecutive validation runs from 23:45. Those runs
were `failed` and could not qualify, so the gate read a `validation_tools` run instead — the other
writer (#1203e4), which probes only what api_smoke exercised and never touched that endpoint. The
final gate record: `ok=True`, `failed_checks=[]`. v1.0.0 delivered with a P1 server error. The
remediation HAD been dispatched — 124 mentions in the run log — but nothing required it to land.

★ ONLY 5xx, deliberately. Of the 369 failing probe records on disk, #1203e3, #1203d9 and #1203e0
account for 266 (211 + 50 + 5). Of the 154 left, 91 are 401 and 54 are 404 — two classes this does
NOT block on, because a 401 on a write whose contract says `auth_required: false` may be the
CONTRACT's error (#1202zr: the framework itself advised declaring writes public) and a 404 on a
declared endpoint is already GATE-C1's job through `_unimplemented_route`'s calibrated exemptions.
A 5xx is never the correct answer to any probe. Residual: 6 records, all r152's regression — so
this new hard blocker would have fired exactly once in the whole corpus, on a real one.
"""
import inspect
import os
import re
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime import deliverability as D  # noqa: E402
from multi_agent.runtime.deliverability import _server_error_probes_1203e7  # noqa: E402

# r152's own records, verbatim.
R152_500 = {"method": "GET", "path": "/api/users/suggested", "verdict": "fail",
            "status_code": 500, "severity": "P1", "note": "server error 500"}
R152_200 = {"method": "GET", "path": "/api/users/suggested", "verdict": "pass",
            "status_code": 200}
R152_401 = {"method": "POST", "path": "/auth/login", "verdict": "fail", "status_code": 401,
            "severity": "P2", "note": "unexpected status 401"}
R152_422 = {"method": "POST", "path": "/oauth/token", "verdict": "fail", "status_code": 422}


def _run(probes, by="orchestrator", at=100.0):
    return {"id": "run_x", "started_by": by, "started_at": at, "probes": list(probes)}


def _f(runs, since=0.0):
    return _server_error_probes_1203e7(runs, since_ts=since)


# ---------------------------------------------------------------- the predicate

def test_r152s_five_hundred_is_reported():
    """★ The one that shipped."""
    assert _f([_run([R152_500])]) == ["GET /api/users/suggested (500)"]


def test_a_401_is_not_a_server_error():
    """★ The deliberate limit: 91 of the 154 residual failures are 401 and this must not touch
    them — the contract may be the wrong half."""
    assert _f([_run([R152_401])]) == []


def test_a_404_and_a_422_are_not_server_errors():
    assert _f([_run([R152_422,
                     {"verdict": "fail", "status_code": 404, "method": "GET", "path": "/x"}])]) == []


def test_every_5xx_counts_not_just_500():
    got = _f([_run([{"verdict": "fail", "status_code": c, "method": "GET", "path": "/p%d" % c}
                    for c in (500, 502, 503, 599)])])
    assert len(got) == 4, got


def test_a_passing_probe_is_never_reported():
    """A 5xx that somehow scored `pass` is a different bug; this reads verdicts, not codes alone."""
    assert _f([_run([dict(R152_500, verdict="pass")])]) == []


def test_duplicates_collapse_and_the_order_is_stable():
    """Six consecutive runs reported the same endpoint; one line per endpoint, sorted, so two
    gate records can be compared."""
    assert _f([_run([R152_500], at=1.0 + i) for i in range(6)]) == [
        "GET /api/users/suggested (500)"]
    got = _f([_run([{"verdict": "fail", "status_code": 500, "method": "GET", "path": "/b"},
                    {"verdict": "fail", "status_code": 500, "method": "GET", "path": "/a"}])])
    assert got == ["GET /a (500)", "GET /b (500)"], got


def test_malformed_records_do_not_raise():
    """This runs inside the delivery gate."""
    assert _f(None) == []
    assert _f([None, "x", 7, {}, _run([None, "x", 7, {}, {"verdict": "fail"},
                                       {"verdict": "fail", "status_code": "oops"}])]) == []


# ---------------------------------------------------------------- the wiring

def _stanza():
    """Bounded by landmarks, comments stripped — a source assertion that cannot tell code from
    the comment explaining it keeps catching the explanation (#1203e6 learned this)."""
    src = inspect.getsource(D)
    i = src.index("_5xx1203e7: List[str] = []")
    j = src.index("# A deterministically functionally-validated WORKING app", i)
    body = src[i:j]
    return "\n".join(ln for ln in body.split("\n") if not ln.lstrip().startswith("#"))


def test_the_runs_are_read_not_the_newest_successful_one():
    """★ The structural defect in one assertion: `list_runs`, not `last_successful_run_since`."""
    s = _stanza()
    assert "runhub.list_runs(" in s, s
    assert "last_successful_run_since" not in s, "it is still reading the flattering run:\n" + s


def test_the_session_boundary_is_respected():
    """A 5xx from a previous session must not block this one."""
    assert "session_start_ts" in _stanza()


def test_the_blocker_is_appended():
    s = _stanza()
    assert "blockers.append(" in s, s
    assert "5xx" in s, s


def test_the_old_successful_run_term_survives_elsewhere():
    """★ The invariant: "a clean run happened this session" is a DIFFERENT question and must keep
    its original source."""
    src = inspect.getsource(D)
    assert "runhub.last_successful_run_since(session_start_ts)" in src


def test_the_lookup_cannot_break_the_gate():
    """#1201: a best-effort lookup that raises would take the whole gate down."""
    s = _stanza()
    assert "except Exception" in s and "warn_once_1201" in s, s


def test_the_blocker_names_the_endpoints():
    """#1202wc/#1086: a blocker that reports only a count cannot be acted on."""
    s = _stanza()
    assert "join_capped(" in s, s
    assert 'ep_counts["server_errors_1203e7"]' in s, s


def test_the_prose_says_a_rerun_will_not_clear_it():
    """The reader's next move. A 5xx is not the stack being slow (#1202od's class), so "retry" is
    the wrong instinct and the message has to say so."""
    s = _stanza()
    assert "does not clear by" in s or "re-running" in s, s


def test_the_other_writers_200_does_not_cancel_the_batterys_500():
    """★ The whole point of the third draft, and r152's real sequence: `api_smoke` probes WITH a
    token and the battery ANONYMOUSLY, so a 200 from one says nothing about a 500 from the other.
    Letting them cancel averaged a real defect — a handler that crashes with no user context
    instead of answering 401 — straight out of the gate."""
    runs = [_run([R152_500], by="orchestrator", at=100.0),
            _run([R152_200], by="", at=200.0)]
    assert _f(runs) == ["GET /api/users/suggested (500)"], _f(runs)


def test_the_same_writer_getting_200_later_does_retire_it():
    """★ The invariant: a fix must clear the blocker, or it is a permanent wedge."""
    runs = [_run([R152_500], by="orchestrator", at=100.0),
            _run([R152_200], by="orchestrator", at=200.0)]
    assert _f(runs) == []


def test_a_5xx_from_before_this_session_is_ignored():
    assert _f([_run([R152_500], at=50.0)], since=100.0) == []
    assert _f([_run([R152_500], at=150.0)], since=100.0) == ["GET /api/users/suggested (500)"]


def test_a_skip_record_says_nothing_either_way():
    """Skips carry no status code; they must neither raise nor retire a 5xx."""
    runs = [_run([R152_500], by="orchestrator", at=100.0),
            _run([{"method": "GET", "path": "/api/users/suggested",
                   "verdict": "skipped", "reason": "auth_required"}],
                 by="orchestrator", at=200.0)]
    assert _f(runs) == ["GET /api/users/suggested (500)"]
