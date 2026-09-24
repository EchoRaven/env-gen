r"""#1202k: an outage produces a cascade of failing records, and only the first quotes the error.

Measured from r25's own check records. ONE says:

    POST http://localhost:8021/auth/login request_failed/ERR_CONNECTION_REFUSED

and TWELVE more describe the same outage as its consequence:

    "Login-to-profiles flow blocked by login submit failing against frontend-origin /auth/login"
    "Account sign-out flow cannot be reached because the two-step login flow fails before ..."
    "Movies critical flow could only load unauthenticated/static view; authenticated journey
     blocked by login submit failure"

Only the first carries a marker #1154 recognises, so the gate discounted 1 and scored 12 as
product defects. Its ledger across the run: 28 discounted against 655 counted as failures. The
nginx template proxies /auth correctly — the backend was simply not up when the walk ran.

Discounting the other twelve is deliberately NOT attempted. #1154 exists because
over-discounting hides a genuinely dead app, and "blocked by X" is prose an agent wrote, not a
dependency the framework recorded; inferring the closure from it would be guessing with a
delivery gate. What can be said without guessing is the arithmetic — N discounted and M
counted in the SAME pass — so whoever reads the line can see one outage may be behind both.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.delivery_gate import _co_failure_note_1202k  # noqa: E402


def test_it_names_the_co_counted_failures():
    note = _co_failure_note_1202k({"failed_records": 12, "passed_records": 3})
    assert "12" in note
    assert "same outage" in note


def test_it_says_nothing_when_nothing_else_failed():
    assert _co_failure_note_1202k({"failed_records": 0}) == ""


def test_it_never_raises_on_a_broken_breadth():
    for bad in (None, {}, {"failed_records": "x"}, "nonsense", 17):
        assert isinstance(_co_failure_note_1202k(bad), str)


def test_the_discount_itself_is_unchanged():
    """The note is a note. Which records get discounted is #1154's decision and is untouched —
    including its fold-back, which still blocks when nothing passed."""
    from multi_agent.runtime.delivery_gate import _ui_evidence_breadth_739

    dead = {"name": "validation:ui_flow:login", "status": "failed",
            "detail": "POST /auth/login request_failed/ERR_CONNECTION_REFUSED"}
    alive = {"name": "validation:ui_flow:browse", "status": "passed", "detail": "ok"}
    prose = {"name": "validation:ui_flow:movies", "status": "failed",
             "detail": "authenticated journey blocked by login submit failure"}

    b = _ui_evidence_breadth_739([dead, alive, prose])
    assert int(b.get("unreachable_records") or 0) == 1     # the one that named the error
    assert int(b.get("failed_records") or 0) == 1          # the prose one still counts
    assert _co_failure_note_1202k(b)                       # and the note says so
