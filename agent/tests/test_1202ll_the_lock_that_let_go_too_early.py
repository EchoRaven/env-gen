"""#1202ll — the compose lock protected the boot and let go before the photographs.

GROUND TRUTH (tiktok-web-r120 resume2, 2026-09-12). The validation loop was recycling the
stack roughly every 90 seconds:

    19:10:10  down -v   19:10:13 up      19:11:09  down -v   19:11:13 build  19:11:38 up
    19:12:50  down -v   19:12:53 build   19:13:06  up        ...

and the delivery capture landed in one of those windows:

    19:16:59  capture FAILED for screen 'explore_grid'  (/explore)     ERR_CONNECTION_REFUSED
    19:16:59  capture FAILED for screen 'fyp_feed_logged_out' (/)      ERR_CONNECTION_REFUSED
    ... all 8 screens, same second, http://localhost:8003

#1202dl took the validation lock for `_compose_up` and released it in the `finally` — so the
two seconds of booting were serialised and the eighteen seconds of `page.goto` that follow,
which is the window a `down -v` actually lands in, were not.

Its docstring gave two reasons, and both are false against measurement:

  * "would block validations for minutes" — a full capture session is a MEDIAN OF 19 SECONDS
    across the 60 corpus runs that kept per-screen captures (p90 49s). One validation cycle's
    own hold is 22-35s. And `run_smoke_validation` waits 600s for the lock before giving up.
  * "already handled by the capture_unavailable refund path" — r120 refunded and then
    delivered 1.2.0 on the 18-minute-old verdict, because the refund buys another round and
    that was the last one (#1202lk).

Also verified rather than assumed: `run_smoke_validation` is dispatched through
`asyncio.to_thread`, so its blocking lock-wait cannot wedge the event loop the capture runs
on — a longer hold cannot deadlock the two against each other.
"""
import asyncio
import ast
import fcntl
import json
import inspect
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _rival_can_take(path):
    """True iff a SEPARATE open file description can take the exclusive lock."""
    with open(path, "w") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            return True
        except OSError:
            return False


def test_the_hold_keeps_the_lock_and_release_gives_it_back(tmp_path):
    async def go():
        fh, got = vf._compose_lock_1202dl(tmp_path)
        assert got
        lockfile = tmp_path / "docker" / ".smoke_validation.lock"
        assert not _rival_can_take(lockfile), "the lock was never actually held"
        hold = vf._CaptureLockHold1202ll(fh, 60.0)
        await asyncio.sleep(0)
        assert not _rival_can_take(lockfile), (
            "handing the lock to the capture session must not drop it — that is the whole fix")
        hold.release()
        assert _rival_can_take(lockfile)
    asyncio.run(go())


def test_release_is_idempotent(tmp_path):
    async def go():
        fh, got = vf._compose_lock_1202dl(tmp_path)
        assert got
        hold = vf._CaptureLockHold1202ll(fh, 60.0)
        hold.release()
        hold.release()            # must not raise, must not double-close
        assert _rival_can_take(tmp_path / "docker" / ".smoke_validation.lock")
    asyncio.run(go())


def test_the_watchdog_gives_the_lock_up_on_its_own(tmp_path):
    """A capture that hangs must not starve validation for 600s."""
    async def go():
        fh, got = vf._compose_lock_1202dl(tmp_path)
        assert got
        lockfile = tmp_path / "docker" / ".smoke_validation.lock"
        vf._CaptureLockHold1202ll(fh, 0.05)      # nobody ever calls release()
        assert not _rival_can_take(lockfile)
        await asyncio.sleep(0.3)
        assert _rival_can_take(lockfile), "the watchdog never fired — the hold is unbounded"
    asyncio.run(go())


def test_without_a_running_loop_it_degrades_to_the_old_scope(tmp_path):
    """No loop ⇒ no watchdog ⇒ holding would be forever. Release immediately instead."""
    fh, got = vf._compose_lock_1202dl(tmp_path)
    assert got
    vf._CaptureLockHold1202ll(fh, 60.0)          # constructed OUTSIDE asyncio.run
    assert _rival_can_take(tmp_path / "docker" / ".smoke_validation.lock")


def test_the_deadline_is_bounded_and_well_under_the_waiters_patience():
    assert 30 <= vf._CAPTURE_LOCK_HOLD_1202LL <= 300, (
        "the hold ceiling must exceed the measured p90 capture (49s) and stay far below "
        "run_smoke_validation's 600s wait")


# ------------------------------------------------------------------ the span

def _run_vf_src():
    return inspect.getsource(vf.run_visual_fidelity)


def test_the_lock_now_spans_the_capture_calls():
    """The hold must be constructed BEFORE the photographs and released AFTER the last one."""
    src = _run_vf_src()
    tree = ast.parse(src)
    made = [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "_CaptureLockHold1202ll"]
    released = [n.lineno for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "release"
                and "_cap_lock_1202ll" in (ast.unparse(n.func.value) or "")]
    shots = [n.lineno for n in ast.walk(tree)
             if isinstance(n, ast.Await)
             and isinstance(n.value, ast.Call)
             and isinstance(n.value.func, ast.Name) and n.value.func.id == "capture"]
    assert made, "the capture-session hold is gone — the lock drops before the photographs"
    assert released, "nothing releases the hold on the fast path"
    assert shots, "the capture calls moved — relocate this landmark"
    assert min(made) < min(shots), "the lock must be held before the first screenshot"
    assert max(shots) < max(released), (
        "the release must come after the LAST capture, including #105's re-mint retry — "
        "that retry re-photographs every screen and is exactly the window a down -v ruins")


def test_the_boot_failure_path_still_drops_the_lock():
    """A host fault returns early; nothing would call release(), so the finally must."""
    src = _run_vf_src()
    tree = ast.parse(src)
    tries = [n for n in ast.walk(tree)
             if isinstance(n, ast.Try) and n.finalbody
             and "_compose_up" in (ast.unparse(n) or "")]
    assert tries, "the compose-lock try/finally moved"
    fin = "\n".join(ast.unparse(s) for s in tries[0].finalbody)
    assert "_cap_lock_1202ll is None" in fin and "_release_compose_lock_1202dl" in fin, (
        "the finally must release whenever the hold was NOT created (boot failure, lock "
        "not acquired, or an exception) — otherwise a host fault leaks the lock")


def test_validation_is_dispatched_off_the_event_loop():
    """★ The premise that makes a longer hold safe. If validation ever ran inline, its
    blocking 600s lock-wait would wedge the loop the capture needs to finish and release."""
    from env_generator.llm_generator.tools import validation_tools as vt
    src = inspect.getsource(vt)
    i = src.index("run_smoke_validation")
    assert "to_thread" in src, (
        "run_smoke_validation is no longer dispatched to a thread — re-check #1202ll's "
        "no-deadlock premise before trusting the longer hold")
    assert i >= 0


def test_the_docstring_carries_the_measurement_not_the_guess():
    """The falsified premise must not survive as a comment somebody trusts later."""
    doc = " ".join((inspect.getdoc(vf._compose_lock_1202dl) or "").split())
    assert "Held only across the compose call" not in doc
    assert "MEDIAN OF 19 SECONDS" in doc, "the measurement that replaced the guess is gone"
    assert "600s" in doc, "the waiter's patience — the reason the hold is safe — is gone"


def test_the_watchdog_leaves_an_artifact_not_just_a_log_line(tmp_path):
    """#947: whoever later reads a round whose screens scored 0.00 has only the run's
    artifacts. "The lock came off mid-capture" has to be among them."""
    async def go():
        fh, got = vf._compose_lock_1202dl(tmp_path)
        assert got
        vf._CaptureLockHold1202ll(fh, 0.05, tmp_path)
        await asyncio.sleep(0.3)
    asyncio.run(go())
    rec = tmp_path / "design" / "visual_gate" / "lock_expiries_1202ll.jsonl"
    assert rec.is_file(), "the expiry reached no artifact"
    row = json.loads(rec.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["held_s"] == 0.05
    assert "raced a validation down -v" in row["note"]


def test_the_artifact_is_append_only(tmp_path):
    """verdict.json is overwritten by the round in progress; this must not be."""
    async def go():
        for _ in range(2):
            fh, got = vf._compose_lock_1202dl(tmp_path)
            assert got
            vf._CaptureLockHold1202ll(fh, 0.05, tmp_path)
            await asyncio.sleep(0.3)
    asyncio.run(go())
    rec = tmp_path / "design" / "visual_gate" / "lock_expiries_1202ll.jsonl"
    assert len(rec.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_a_normal_release_writes_nothing(tmp_path):
    """Only the EXPIRY is notable — the median 19s round must not litter the artifact."""
    async def go():
        fh, got = vf._compose_lock_1202dl(tmp_path)
        assert got
        hold = vf._CaptureLockHold1202ll(fh, 60.0, tmp_path)
        hold.release()
        await asyncio.sleep(0.05)
    asyncio.run(go())
    assert not (tmp_path / "design" / "visual_gate" / "lock_expiries_1202ll.jsonl").exists()
