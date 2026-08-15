r"""#756: the finished-run banner used a POSITION test for a whole-file fact, and I believed it.

`check_pending_experiments.sh` decides whether a run finished with

    tail -5 "$LOG" | grep -q -- "[main-exit]"

`[main-exit]` is printed the instant `main()` returns, and asyncio tasks already in flight keep
flushing after it. r149 printed it **26 lines from the end** of a 21,088-line log, so the checker
stamped a FINISHED run with the "this is a snapshot, a zero means 'not yet'" banner.

The cost was not the banner. I read it as evidence the run had been killed, and spent a turn on a
death that never happened: I checked `tail -5`, found no marker, saw the process gone from `ps`,
and concluded SIGKILL. The run had exited normally — `[main-exit] main() returned 1`, and the
crash-forensics file (#55, which already existed and which I should have read first) recorded
`clean interpreter exit pid=1396182` for that exact pid.

The whole-file grep is the fix. It cannot regress the thing the banner is FOR: a still-running
run has not printed the marker anywhere, so it still warns.
"""
import pathlib
import re
import subprocess
import tempfile

import pytest


SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "tools" / "check_pending_experiments.sh"
BANNER = "WARNING: this run has NOT finished"


def _run(log_text: str) -> str:
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        (d / "shared" / "hubs").mkdir(parents=True)
        log = d / "run.log"
        log.write_text(log_text, encoding="utf-8")
        p = subprocess.run(["bash", str(SCRIPT), str(d), str(log)],
                           capture_output=True, text=True, timeout=120)
        return p.stdout + p.stderr


def _tail_lines(n: int) -> str:
    return "\n".join(f"trailing async line {i}" for i in range(n))


# --- the r149 shape ------------------------------------------------------------------------------

def test_a_marker_26_lines_from_the_end_counts_as_finished():
    out = _run("start\n[main-exit] main() returned 1\n" + _tail_lines(26))
    assert BANNER not in out


def test_a_marker_at_the_very_end_still_counts():
    out = _run("start\n[main-exit] main() returned 0\n")
    assert BANNER not in out


def test_a_marker_thousands_of_lines_back_counts():
    out = _run("[main-exit] main() returned 1\n" + _tail_lines(2000))
    assert BANNER not in out


@pytest.mark.parametrize("marker", [
    "[main-exit] main() returned 0",
    "[main-exit] main() returned 1",
    "[main-exit] main() raised RuntimeError: boom",
    "[main-exit] shutdown watchdog fired — forcing exit (rc=7)",
])
def test_every_exit_path_marker_is_accepted(marker):
    """main() prints one of exactly these three shapes; the banner must accept all of them."""
    out = _run(f"start\n{marker}\n" + _tail_lines(30))
    assert BANNER not in out, marker


# --- the banner still does its job -----------------------------------------------------------------

def test_a_run_with_no_marker_anywhere_still_warns():
    """Non-vacuity, and the whole purpose of #717: an unfinished log must still be flagged."""
    out = _run("start\n" + _tail_lines(50))
    assert BANNER in out


def test_an_empty_log_still_warns():
    out = _run("")
    assert BANNER in out


def test_the_warning_still_says_a_zero_means_not_yet():
    out = _run("start\nnothing here\n")
    assert "A zero here means" in out
    assert "'not yet', not 'never'" in out


# --- the position test is gone -----------------------------------------------------------------------

def test_the_script_no_longer_tests_only_the_tail():
    src = SCRIPT.read_text(encoding="utf-8")
    assert 'tail -5 "$LOG" | grep -q' not in src
    assert re.search(r'if ! grep -q -- "\\\[main-exit\\\]" "\$LOG"', src), (
        "the finished test must read the whole file")


def test_the_reason_is_recorded_at_the_call_site():
    src = SCRIPT.read_text(encoding="utf-8")
    i = src.index("#756")
    blk = src[i:src.index('if ! grep -q', i)]
    assert "26 lines from the end" in blk
    assert "declared a FINISHED run unfinished" in blk


def test_it_records_what_the_wrong_banner_cost():
    src = SCRIPT.read_text(encoding="utf-8")
    i = src.index("#756")
    blk = src[i:src.index('if ! grep -q', i)]
    assert "spent a turn on a death that never happened" in blk


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
