r"""#717: the checker read a growing log as if it were a result, four times.

Every line the checker prints is a grep over a run log. If the run is still going, each count is
a snapshot of something that has not finished happening — and a zero means "not yet", which is
indistinguishable from "never" at a glance. I hit that four times on r147 alone, reading it at
~9,000 lines of an eventual 12,237:

    "r147 did not deliver"                    it delivered v1.0.0 in the 3,000 lines after I looked
    "#700 x17"                                final: 37
    "160 attempts, 80 failures"               final: 178, 84
    "the rate accelerates rather than
     tapering"                                drawn from a distribution whose tail (8000s: 0,
                                              9000s: 2) had not happened yet

Three of those reached the record and one reached the user before being corrected. The habit, not
the arithmetic, is the defect.

`[main-exit]` is written by `main()` on every exit path — r145 (rc=1), r146 (rc=0), r147
(watchdog) all carry it, and a running log does not. The banner is loud, costs one `tail`, and
does not change any verdict the checker prints.
"""
import re
import subprocess
from pathlib import Path

import pytest


CHECKER = Path(__file__).resolve().parents[2] / "tools" / "check_pending_experiments.sh"
BANNER = "this run has NOT finished"


def _block() -> str:
    src = CHECKER.read_text(encoding="utf-8")
    i = src.index("#717: REFUSE TO BE READ AS A RESULT")
    return src[i:src.index('echo "=== run:', i)]


def _run(tmp_path: Path, log_tail: str):
    rundir = tmp_path / "run"
    (rundir / "shared" / "hubs").mkdir(parents=True)
    log = tmp_path / "r.log"
    log.write_text(log_tail, encoding="utf-8")
    out = subprocess.run(["bash", str(CHECKER), str(rundir), str(log)],
                         capture_output=True, text=True)
    return out.stdout + out.stderr


# --- it fires on a growing log and stays quiet on a finished one ------------------------------

def test_a_running_log_gets_the_banner(tmp_path):
    assert BANNER in _run(tmp_path, "12:00 [I] something\n12:01 [I] more\n")


@pytest.mark.parametrize("marker", [
    "[main-exit] main() returned 0",
    "[main-exit] main() returned 1",
    "[main-exit] shutdown watchdog fired — forcing exit (rc=0)",
])
def test_every_real_exit_path_suppresses_it(marker):
    """r146, r145 and r147 respectively — all three shapes must count as finished."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        assert BANNER not in _run(Path(td), f"12:00 [I] work\n{marker}\n")


def test_an_exit_far_above_the_tail_still_counts_as_running(tmp_path):
    """The marker is the LAST thing main writes; one buried 50 lines up is not an exit."""
    body = "[main-exit] main() returned 0\n" + "".join(f"line {i}\n" for i in range(50))
    assert BANNER in _run(tmp_path, body)


def test_no_log_at_all_does_not_claim_anything(tmp_path):
    rundir = tmp_path / "run"
    (rundir / "shared" / "hubs").mkdir(parents=True)
    out = subprocess.run(["bash", str(CHECKER), str(rundir)], capture_output=True, text=True)
    assert BANNER not in out.stdout


# --- it says the right thing ---------------------------------------------------------------------

def test_the_banner_explains_what_a_zero_means(tmp_path):
    out = _run(tmp_path, "still going\n")
    assert "'not yet', not 'never'" in out


def test_the_banner_says_to_re_run_after_exit(tmp_path):
    assert "after the run exits" in _run(tmp_path, "still going\n")


def test_the_banner_precedes_the_findings(tmp_path):
    out = _run(tmp_path, "still going\n")
    assert out.index(BANNER) < out.index("=== run:")


# --- it changes no verdict --------------------------------------------------------------------------

def test_the_checker_still_reports_its_sections(tmp_path):
    out = _run(tmp_path, "still going\n")
    assert "did this session's fixes actually execute" in out


def test_the_banner_is_the_only_difference(tmp_path):
    running = _run(tmp_path, "same body\n")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        done = _run(Path(td), "same body\n[main-exit] main() returned 0\n")

    # Compare the VERDICT lines only. Stripping the banner out of the running output by hand
    # was the first draft and it contained `"x" in l is False`, which parses as a chained
    # comparison and is always False — the assertion passed on a mangled string.
    def verdicts(t):
        return [l for l in t.split("\n")
                if re.match(r"^(LIVE|NOT SEEN|GONE|STILL|DATA|n/a|MANUAL)", l)]
    assert verdicts(running) == verdicts(done)


# --- provenance ---------------------------------------------------------------------------------------

def test_the_four_wrong_conclusions_are_recorded():
    # Fold the comment markers and wrapping: "…tail had not" / "# happened yet" is one
    # sentence in the file and two lines in the bytes.
    block = " ".join(_block().replace("#", " ").split())
    assert "r147 did not deliver" in block
    assert "final: 37" in block
    assert "178 / 84" in block
    assert "had not happened yet" in block


def test_the_marker_choice_is_justified():
    block = " ".join(_block().replace("#", " ").split())
    assert "every exit path" in block
    assert "r145" in block and "r146" in block and "r147" in block


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
