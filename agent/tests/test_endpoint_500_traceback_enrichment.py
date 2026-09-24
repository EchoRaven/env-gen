"""FIX #157 (gmrun5 wedge lesson) — a 5xx endpoint probe must report the backend ROOT
CAUSE, not just "→ 500".

gmrun5: `GET /api/transit/{id}/departures → 500` was dispatched to the backend lane with
NO further detail; the real cause (custom_routes.py:202 comparing a TEXT column to an
integer param — `operator does not exist: text = integer`) sat in the backend container
logs the whole time. The lane guessed "parameter type", guessed wrong, reported done, and
7 re-dispatches never re-engaged it → 50min wedge → STUCK-abort. Third instance of the
"gate knows more than it says" class (run-4 blank→#154 file:line; run-5 500→this).

The smoke runner now, when any business endpoint answers 5xx, pulls the backend
container's log tail and appends the salient last-traceback line (innermost /app/ frame
+ exception message) to the ``business_endpoints_reachable`` check detail — which flows
verbatim into the remediation task description. LOCAL-ONLY (agent/tests/ gitignored).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.validation_runner import (  # noqa: E402
    compose_unreachable_detail, extract_salient_traceback)

# The REAL gmrun5 backend traceback shape (chained: psycopg inner block → cause marker →
# outer block through uvicorn/fastapi/sqlalchemy frames + the lane's custom_routes frame).
_RUN5_TRACEBACK = '''INFO:     172.18.0.4:51774 - "GET /api/transit/1/departures HTTP/1.1" 500 Internal Server Error
Traceback (most recent call last):
  File "/usr/local/lib/python3.11/site-packages/sqlalchemy/engine/base.py", line 1964, in _exec_single_context
    self.dialect.do_execute(
  File "/usr/local/lib/python3.11/site-packages/sqlalchemy/engine/default.py", line 952, in do_execute
    cursor.execute(statement, parameters)
  File "/usr/local/lib/python3.11/site-packages/psycopg/cursor.py", line 117, in execute
    raise ex.with_traceback(None)
psycopg.errors.UndefinedFunction: operator does not exist: text = integer
LINE 3: WHERE transit_lines.from_stop = $1::INTEGER
                                      ^
HINT:  No operator matches the given name and argument types. You might need to add explicit type casts.

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/usr/local/lib/python3.11/site-packages/uvicorn/protocols/http/h11_impl.py", line 416, in run_asgi
    result = await app(  # type: ignore[func-returns-value]
  File "/usr/local/lib/python3.11/site-packages/fastapi/applications.py", line 1163, in __call__
    await super().__call__(scope, receive, send)
  File "/app/custom_routes.py", line 202, in get_transit_departures
    lines = db.query(TransitLine).filter(TransitLine.from_stop == id).limit(5).all()
  File "/usr/local/lib/python3.11/site-packages/sqlalchemy/orm/query.py", line 2711, in all
    return self._iter().all()  # type: ignore
  File "/usr/local/lib/python3.11/site-packages/sqlalchemy/orm/session.py", line 2373, in execute
    return self._execute_internal(statement, params)
sqlalchemy.exc.ProgrammingError: (psycopg.errors.UndefinedFunction) operator does not exist: text = integer
LINE 3: WHERE transit_lines.from_stop = $1::INTEGER
[SQL: SELECT transit_lines.id AS transit_lines_id FROM transit_lines WHERE transit_lines.from_stop = %(from_stop_1)s::INTEGER]
'''


def test_real_run5_traceback_yields_file_line_and_cause():
    s = extract_salient_traceback(_RUN5_TRACEBACK)
    assert "custom_routes.py:202" in s, s
    assert "get_transit_departures" in s, s
    assert "operator does not exist: text = integer" in s, s


def test_compose_logs_container_prefix_stripped():
    prefixed = "\n".join(f"backend-1  | {ln}" for ln in _RUN5_TRACEBACK.splitlines())
    s = extract_salient_traceback(prefixed)
    assert "custom_routes.py:202" in s, s


def test_last_traceback_wins():
    older = _RUN5_TRACEBACK.replace("202", "111").replace(
        "get_transit_departures", "old_handler")
    s = extract_salient_traceback(older + "\nsome noise\n" + _RUN5_TRACEBACK)
    assert "custom_routes.py:202" in s and "old_handler" not in s, s


def test_no_traceback_returns_empty():
    assert extract_salient_traceback("INFO: all good\nINFO: 200 OK\n") == ""
    assert extract_salient_traceback("") == ""


def test_no_app_frame_still_reports_exception():
    tb = ("Traceback (most recent call last):\n"
          '  File "/usr/local/lib/python3.11/site-packages/x.py", line 5, in go\n'
          "    raise ValueError('boom')\n"
          "ValueError: boom\n")
    s = extract_salient_traceback(tb)
    assert "boom" in s, s


def test_detail_without_salient_is_plain_join():
    d = compose_unreachable_detail(["GET /api/a → 500", "GET /api/b → 502"], "")
    assert d == "GET /api/a → 500; GET /api/b → 502"


def test_detail_with_salient_carries_root_cause_early():
    salient = ("custom_routes.py:202 in get_transit_departures — "
               "psycopg.errors.UndefinedFunction: operator does not exist: text = integer")
    d = compose_unreachable_detail(["GET /api/transit/{id}/departures → 500"], salient)
    assert "backend traceback:" in d
    # the urgent-wake message truncates detail to 300 chars — the file:line root cause
    # must survive that cut (gmrun5: the lane acted on the first 300 chars it saw)
    assert "custom_routes.py:202" in d[:300], d


def test_detail_with_salient_caps_long_endpoint_list():
    salient = "custom_routes.py:202 in get_transit_departures — boom"
    many = [f"GET /api/e{i} → 500" for i in range(40)]
    d = compose_unreachable_detail(many, salient)
    assert "custom_routes.py:202" in d
    assert len(d) <= 800


# FIX #161 (gmrun7 LIVE): the REAL run-7 traceback — the endpoint is a FRAMEWORK-PROJECTED
# handler (main.py), NOT a lane custom_routes.py handler, and the innermost /app/ frame is
# the framework DB wrapper database.py:80. The salient frame must name the HANDLER
# (main.py:519), not database.py. (My #157 fixture omitted the database.py frame → the test
# passed while the live behaviour picked database.py — lesson: fixtures must match reality.)
_RUN7_REAL_TRACEBACK = '''backend-1  | INFO:     172.18.0.4:51774 - "GET /api/transit/1/departures HTTP/1.1" 500 Internal Server Error
backend-1  | Traceback (most recent call last):
backend-1  |   File "/usr/local/lib/python3.11/site-packages/sqlalchemy/engine/default.py", line 952, in do_execute
backend-1  |     cursor.execute(statement, parameters)
backend-1  | psycopg.errors.UndefinedFunction: operator does not exist: text = integer
backend-1  | LINE 3: WHERE tenants.id = $1::INTEGER
backend-1  |
backend-1  | The above exception was the direct cause of the following exception:
backend-1  |
backend-1  | Traceback (most recent call last):
backend-1  |   File "/usr/local/lib/python3.11/site-packages/uvicorn/protocols/http/h11_impl.py", line 416, in run_asgi
backend-1  |     result = await app(scope, receive, send)
backend-1  |   File "/app/main.py", line 229, in _framework_auth_guard
backend-1  |     return await call_next(request)
backend-1  |   File "/app/main.py", line 519, in _projected_get_api_transit_id_departures_5
backend-1  |     obj = db.query(Tenant).filter(Tenant.id == id).first()
backend-1  |   File "/app/database.py", line 80, in execute
backend-1  |     return super().execute(statement, params, *args, **kwargs)
backend-1  | sqlalchemy.exc.ProgrammingError: (psycopg.errors.UndefinedFunction) operator does not exist: text = integer
'''


def test_run7_salient_frame_is_the_handler_not_db_wrapper():
    s = extract_salient_traceback(_RUN7_REAL_TRACEBACK)
    assert "main.py:519" in s, s
    assert "_projected_get_api_transit_id_departures_5" in s, s
    assert "database.py" not in s, s
    assert "operator does not exist: text = integer" in s, s


def test_infra_only_stack_falls_back_to_innermost_app_frame():
    # if every /app/ frame IS infra, still report something (the innermost /app/ frame)
    tb = ("Traceback (most recent call last):\n"
          '  File "/app/database.py", line 80, in execute\n'
          "    return super().execute(s)\n"
          "sqlalchemy.exc.ProgrammingError: boom\n")
    s = extract_salient_traceback(tb)
    assert "database.py:80" in s and "boom" in s, s


def test_lane_custom_routes_frame_preferred_over_db_wrapper():
    # the run-5 variant: a lane handler + the db wrapper → prefer the lane handler
    tb = ("Traceback (most recent call last):\n"
          '  File "/app/custom_routes.py", line 202, in get_transit_departures\n'
          "    lines = db.query(TransitLine).filter(TransitLine.from_stop == id).all()\n"
          '  File "/app/database.py", line 80, in execute\n'
          "    return super().execute(s)\n"
          "sqlalchemy.exc.ProgrammingError: operator does not exist: text = integer\n")
    s = extract_salient_traceback(tb)
    assert "custom_routes.py:202" in s and "database.py" not in s, s


def test_smoke_runner_wires_traceback_enrichment_source_contract():
    """The probe section must call the enrichment when a 5xx occurred and feed the
    salient text into the business_endpoints_reachable detail."""
    import inspect
    from multi_agent.runtime import validation_runner as vr
    src = inspect.getsource(vr.run_smoke_validation)
    assert "extract_salient_traceback" in src
    assert "compose_unreachable_detail" in src
