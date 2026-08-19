"""#964: a compose spawn must announce itself BEFORE it blocks.

``_compose`` owns the longest silent windows in a run — ``build`` (up to
``_DOCKER_BUILD_TIMEOUT``, 900s) and ``up`` (up to ``_DOCKER_UP_TIMEOUT``, 1200s) —
and used to emit nothing at all: no start line, no argv, no elapsed. From outside,
an in-progress cold build looked exactly like a wedged process (netflix r155).

The load-bearing assertion is ORDERING: the log record must exist at the moment
``subprocess.run`` is entered, not merely after it returns. A completion-only log
would still leave the whole build window unexplained.
"""

import logging
import subprocess

import pytest

from env_generator.llm_generator.multi_agent.runtime import validation_runner as vr


def _fake_cp(argv, rc=0, out="", err=""):
    return subprocess.CompletedProcess(argv, rc, out, err)


def test_the_spawn_is_logged_before_the_call_blocks(tmp_path, caplog, monkeypatch):
    seen_at_spawn = {}

    def _capture_then_return(argv, **kw):
        seen_at_spawn["records"] = [r.message for r in caplog.records]
        return _fake_cp(argv)

    monkeypatch.setattr(vr.subprocess, "run", _capture_then_return)
    with caplog.at_level(logging.INFO, logger=vr.__name__):
        vr._compose(tmp_path / "docker-compose.yml", "build", cwd=tmp_path, timeout=900)

    announced = [m for m in seen_at_spawn.get("records", []) if "compose spawn" in m]
    assert announced, (
        "nothing was logged before subprocess.run was entered — the whole build "
        "window stays invisible, which is the defect #964 exists to fix")
    assert "build" in announced[0], "the log must name the verb being run"
    assert "900" in announced[0], "the log must name the timeout cap so a long wait is explainable"


def test_the_completion_reports_rc_and_elapsed(tmp_path, caplog, monkeypatch):
    monkeypatch.setattr(vr.subprocess, "run", lambda argv, **kw: _fake_cp(argv, rc=1))
    with caplog.at_level(logging.INFO, logger=vr.__name__):
        vr._compose(tmp_path / "docker-compose.yml", "up", "-d", cwd=tmp_path, timeout=240)

    done = [r.message for r in caplog.records if "rc=" in r.message]
    assert done, "the spawn never reported a completion line"
    assert "rc=1" in done[-1]
    assert "up -d" in done[-1], "the completion must identify WHICH spawn finished"


def test_a_timeout_is_named_not_swallowed(tmp_path, caplog, monkeypatch):
    def _boom(argv, **kw):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=1)

    monkeypatch.setattr(vr.subprocess, "run", _boom)
    with caplog.at_level(logging.INFO, logger=vr.__name__):
        with pytest.raises(subprocess.TimeoutExpired):
            vr._compose(tmp_path / "docker-compose.yml", "build", cwd=tmp_path, timeout=1)

    warned = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("TIMED OUT" in m for m in warned), (
        "a timeout must be visible in the log; _compose_capture converts it to rc=124 "
        "upstream, so without this line the cap is hit silently")


def test_the_control_is_silent(tmp_path, caplog, monkeypatch):
    """Planted control: a synthetic spawn helper WITHOUT the logging must fail the
    ordering assertion, proving the assertion discriminates rather than passing on
    any log traffic that happens to be present."""

    def _unlogged_compose(compose_file, *args, cwd, timeout=300):
        return subprocess.run(["true"], capture_output=True, text=True, timeout=timeout)

    with caplog.at_level(logging.INFO, logger=vr.__name__):
        _unlogged_compose(tmp_path / "docker-compose.yml", "build", cwd=tmp_path)

    assert not [r for r in caplog.records if "compose spawn" in r.message], (
        "the control emitted a spawn line it was never given — the assertion in the "
        "main test would pass for the wrong reason")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- #972 ---------------------------------------------------------------------------

def test_a_failing_spawn_reports_its_transcript(tmp_path, caplog, monkeypatch):
    """#972: #964 announced `rc=1 in 0s` and stopped there — enough to see that something
    broke, useless for diagnosing it. netflix r158 produced two instant build failures and
    left no other trace, so the cause was unrecoverable from the log."""
    monkeypatch.setattr(vr.subprocess, "run", lambda argv, **kw: _fake_cp(
        argv, rc=1, err="ERROR: no configuration file provided: not found"))
    with caplog.at_level(logging.INFO, logger=vr.__name__):
        vr._compose(tmp_path / "docker-compose.yml", "build", cwd=tmp_path, timeout=900)

    warned = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("no configuration file provided" in m for m in warned), (
        "the captured transcript must reach the log; capture_output=True already collects "
        "it, so dropping it is pure loss")


def test_a_successful_spawn_stays_quiet(tmp_path, caplog, monkeypatch):
    """The failure tail must not fire on success — every compose call would drown the log."""
    monkeypatch.setattr(vr.subprocess, "run", lambda argv, **kw: _fake_cp(
        argv, rc=0, out="Successfully built abc123"))
    with caplog.at_level(logging.INFO, logger=vr.__name__):
        vr._compose(tmp_path / "docker-compose.yml", "ps", cwd=tmp_path, timeout=30)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_the_tail_is_bounded(tmp_path, caplog, monkeypatch):
    monkeypatch.setattr(vr.subprocess, "run", lambda argv, **kw: _fake_cp(
        argv, rc=1, err="x" * 50_000))
    with caplog.at_level(logging.INFO, logger=vr.__name__):
        vr._compose(tmp_path / "docker-compose.yml", "build", cwd=tmp_path, timeout=900)
    worst = max(len(r.message) for r in caplog.records)
    assert worst < 1500, f"an unbounded tail would flood the log ({worst} chars)"


def test_stdout_is_used_when_stderr_is_empty(tmp_path, caplog, monkeypatch):
    """Classic-builder compose writes the real error to stdout on some failures."""
    monkeypatch.setattr(vr.subprocess, "run", lambda argv, **kw: _fake_cp(
        argv, rc=1, out="failed to solve: executor failed running", err="   "))
    with caplog.at_level(logging.INFO, logger=vr.__name__):
        vr._compose(tmp_path / "docker-compose.yml", "build", cwd=tmp_path, timeout=900)
    warned = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("failed to solve" in m for m in warned)
