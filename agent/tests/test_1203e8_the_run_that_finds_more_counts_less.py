r"""#1203e8: the run that finds more is the run that counts less, and the ledger showed only one.

The gate judges ONE run — `last_successful_run_since`, which requires `completed` AND
`fail_count == 0`. Two writers produce runs (#1203e4), and the one with the WIDER coverage is
systematically disqualified by its own findings: `RunHub.run_start`'s battery probes every live
endpoint anonymously, so a single 404 anywhere marks its run `failed`, and the gate reads
`validation_tools`' authenticated sweep instead.

★ r153, live: the gate record read `endpoint_probes {total: 7, passed: 7, source: (unset)}` —
api_smoke's seven business endpoints — while the battery's runs carried
`POST /auth/signup (404)` twice, `POST /api/auth/signup (404)` and `POST /api/auth/login (401)`.
Four findings that nothing in the ledger mentioned.

This RECORDS and never blocks. #1203e7 blocks on 5xx alone, because a 401 on a write whose
contract says `auth_required: false` may be the CONTRACT's error (#1202zr) and a declared
endpoint's 404 is already GATE-C1's job. Those judgements are deliberately not made here — but
"not blockable" is not "not worth writing down".

Newest run PER WRITER, the same semantics #1203e7 arrived at, and r153 shows why that is right:
the `/auth/signup` 404s were fixed by the lane between 01:48 and 02:12, so by 02:14 the battery's
newest run carried only the 401 and that is exactly what this reports. Fixed findings retire on
their own.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.deliverability import (  # noqa: E402
    _other_writers_failures_1203e8)

F404 = {"method": "POST", "path": "/auth/signup", "verdict": "fail", "status_code": 404}
F401 = {"method": "POST", "path": "/api/auth/login", "verdict": "fail", "status_code": 401}
PASS = {"method": "GET", "path": "/api/videos/feed", "verdict": "pass", "status_code": 200}


def _run(rid, probes, by="orchestrator", at=100.0, status="failed"):
    return {"id": rid, "started_by": by, "started_at": at, "status": status,
            "probes": list(probes)}


def test_the_chosen_runs_own_findings_are_not_repeated():
    """★ The gate already reports the run it read; this is about the OTHERS."""
    runs = [_run("A", [F404], by="", at=100.0)]
    assert _other_writers_failures_1203e8(runs, "A") == []


def test_the_unread_writers_findings_are_recorded():
    """★ r153's shape: the gate read api_smoke's run, the battery found a 401."""
    runs = [_run("A", [PASS], by="", at=200.0, status="completed"),
            _run("B", [F401], by="orchestrator", at=100.0)]
    assert _other_writers_failures_1203e8(runs, "A") == ["POST /api/auth/login (401)"]


def test_only_the_newest_run_per_writer_counts():
    """★ r153 live: the `/auth/signup` 404 was fixed between 01:48 and 02:12, so the battery's
    newest run carried only the 401 — a retired finding must not be re-reported."""
    runs = [_run("B1", [F404, F401], by="orchestrator", at=100.0),
            _run("B2", [F401], by="orchestrator", at=200.0)]
    assert _other_writers_failures_1203e8(runs, "A") == ["POST /api/auth/login (401)"]


def test_each_writer_is_read_separately():
    """Two writers, two newest runs, both reported — they cover different sets."""
    runs = [_run("A", [F404], by="", at=100.0),
            _run("B", [F401], by="orchestrator", at=200.0)]
    got = _other_writers_failures_1203e8(runs, "C")
    assert got == ["POST /api/auth/login (401)", "POST /auth/signup (404)"], got


def test_passing_probes_are_not_reported():
    runs = [_run("B", [PASS], by="orchestrator", at=100.0)]
    assert _other_writers_failures_1203e8(runs, "A") == []


def test_a_run_from_before_the_session_is_ignored():
    runs = [_run("B", [F401], by="orchestrator", at=50.0)]
    assert _other_writers_failures_1203e8(runs, "A", since_ts=100.0) == []
    runs = [_run("B", [F401], by="orchestrator", at=150.0)]
    assert _other_writers_failures_1203e8(runs, "A", since_ts=100.0) == [
        "POST /api/auth/login (401)"]


def test_malformed_input_does_not_raise():
    """This runs inside the delivery gate."""
    assert _other_writers_failures_1203e8(None, "A") == []
    assert _other_writers_failures_1203e8([None, "x", 7, {}, {"started_at": "nope"}], "A") == []
    assert _other_writers_failures_1203e8([_run("B", [None, "x", {}], at=1.0)], "A") == []


def test_the_status_code_is_reported_verbatim_even_when_absent():
    """A transport failure has no status; the record must still name the endpoint rather than
    being dropped, because "it did not answer at all" is the loudest finding there is."""
    runs = [_run("B", [{"method": "GET", "path": "/api/x", "verdict": "fail",
                        "status_code": None}], at=100.0)]
    assert _other_writers_failures_1203e8(runs, "A") == ["GET /api/x (None)"]


# ---------------------------------------------------------------- wiring

def _stanza():
    """Landmarks, comments stripped (#1203e6's lesson)."""
    import inspect
    from multi_agent.runtime import deliverability as D
    src = inspect.getsource(D)
    i = src.index("_other1203e8 = _other_writers_failures_1203e8(")
    j = src.index("if _5xx1203e7:", i)
    body = src[i:j]
    return "\n".join(ln for ln in body.split("\n") if not ln.lstrip().startswith("#"))


def test_it_is_recorded_and_not_appended_as_a_blocker():
    """★ The deliberate limit: this must never decline delivery. #1202tu's ratchet would also
    catch a blocker here with no owner, but the intent is pinned explicitly."""
    s = _stanza()
    assert 'ep_counts["other_writer_failures_1203e8"]' in s, s
    assert "blockers.append" not in s, "this must record, not block:\n" + s


def test_the_chosen_run_id_is_passed_so_it_is_not_double_reported():
    assert "last_run" in _stanza()


def test_the_lookup_cannot_break_the_gate():
    s = _stanza()
    assert "except Exception" in s and "warn_once_1201" in s, s
