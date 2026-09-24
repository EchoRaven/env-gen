"""A chain's /auth/register step must accept the framework's REAL success code.

The embedded AS register returns 201 Created (200 on some platforms) or 409
(user already exists → still loginable). Verifiers author the `expect` list
INCONSISTENTLY — e.g. [200, 409], forgetting 201 — which then fails an otherwise
correct CRUD chain when register returns 201 (smoke-notes exp7: notes_crud's whole
flow failed only on register→201 ∉ [200,409]). The exact success code is a framework
FACT, not a verifier choice, so normalize_steps must UNION 200/201/409 into any
register step's expect.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.chain_executor import normalize_steps, _status_ok  # noqa: E402


def _expect_for(steps, idx):
    norm, _ = normalize_steps(steps)
    return set(norm[idx].get("expect") or [])


def test_register_expect_unions_201_when_author_forgot_it():
    # the exp7 bug: verifier wrote [200, 409] → 201 must be added
    e = _expect_for([{"method": "POST", "path": "/auth/register", "expect": [200, 409]}], 0)
    assert {200, 201, 409} <= e
    assert _status_ok(201, sorted(e)) is True       # the real register response now passes


def test_register_expect_unions_when_only_200():
    e = _expect_for([{"method": "POST", "path": "/auth/register", "expect": [200]}], 0)
    assert {200, 201, 409} <= e


def test_register_no_expect_gets_full_set():
    e = _expect_for([{"method": "POST", "path": "/auth/register"}], 0)
    assert {200, 201, 409} <= e


def test_register_keeps_authored_extra_codes():
    e = _expect_for([{"method": "POST", "path": "/auth/register", "expect": [200, 201, 422]}], 0)
    assert {200, 201, 409, 422} <= e                # union, never drops authored codes


def test_business_step_expect_untouched():
    # a cross-user isolation step expecting 404 must NOT be loosened (the gate's teeth).
    # NB normalize auto-prepends a register step (it mints the token), so locate the
    # business step by path rather than by a fixed index.
    norm, _ = normalize_steps([
        {"method": "POST", "path": "/auth/register", "save": {"token": "access_token"}},
        {"method": "GET", "path": "/api/notes/${id}", "expect": [404]},
    ])
    biz = next(s for s in norm if str(s.get("path", "")).startswith("/api/notes/"))
    assert set(biz.get("expect") or []) == {404}    # isolation assertion preserved
    assert _status_ok(200, [404]) is False          # a leak still fails the step


def _body_of(steps, path):
    norm, _ = normalize_steps(steps)
    s = next(st for st in norm if str(st.get("path", "")).rstrip("/") == path)
    return s.get("body")


def test_json_string_body_with_bare_var_parses_to_dict():
    # outlook events POST: verifier authored the body as a JSON STRING with a BARE ${var}
    # ('{"calendar_id": ${calendarId}}') → invalid JSON → stayed a string → API 422'd.
    body = _body_of(
        [{"method": "POST", "path": "/api/events", "auth": "token",
          "body": '{"calendar_id": ${calendarId}, "title": "Meeting"}'}],
        "/api/events")
    assert isinstance(body, dict), f"body should parse to a dict, got {type(body)}"
    assert body["calendar_id"] == "${calendarId}"   # var preserved as a string VALUE
    assert body["title"] == "Meeting"


def test_json_string_body_with_quoted_var_still_parses():
    # a ${var} already INSIDE a quoted string is valid JSON — must be left intact.
    body = _body_of(
        [{"method": "POST", "path": "/api/notes", "auth": "token",
          "body": '{"title": "Note ${rand}"}'}],
        "/api/notes")
    assert isinstance(body, dict)
    assert body["title"] == "Note ${rand}"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
