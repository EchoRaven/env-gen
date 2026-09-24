"""Fix #55 — automatic crash forensics (run-40, 2026-07-02: the main process
died SILENTLY mid-run — no exception in the log, no shutdown record, no OOM
trace). main.py now arms, at import: faulthandler.enable → crash file (native
faults), sys/threading excepthooks (uncaught Python exceptions), and an atexit
"clean interpreter exit" marker (its ABSENCE + no traceback ⇒ SIGKILL/OOM).
Each path is proven with a real subprocess. LOCAL-ONLY (agent/tests/ gitignored).
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
_IMPORT = "import env_generator.llm_generator.main"


def _run(tmp_path, code, crash_log="crash.log"):
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{ROOT}{os.pathsep}{LLM}"
    if crash_log is not None:
        env["ENVGEN_CRASH_LOG"] = str(tmp_path / crash_log)
    proc = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=120)
    log = tmp_path / (crash_log or "envgen_crash.log")
    return proc, (log.read_text(encoding="utf-8", errors="replace")
                  if log.exists() else "")


def test_uncaught_exception_lands_in_crash_log(tmp_path):
    proc, log = _run(tmp_path, f"{_IMPORT}\nraise RuntimeError('boom-forensics')")
    assert proc.returncode != 0
    assert "UNCAUGHT EXCEPTION" in log
    assert "boom-forensics" in log


def test_uncaught_thread_exception_lands_in_crash_log(tmp_path):
    code = (f"{_IMPORT}\nimport threading\n"
            "t = threading.Thread(target=lambda: 1/0, name='w')\n"
            "t.start(); t.join()")
    proc, log = _run(tmp_path, code)
    assert "UNCAUGHT THREAD EXCEPTION" in log
    assert "ZeroDivisionError" in log
    # review w6x6art4t: the PRIOR hook must be CHAINED — the default
    # "Exception in thread" traceback must still reach stderr/the run log
    assert "ZeroDivisionError" in proc.stderr


def test_hard_native_fault_lands_in_crash_log(tmp_path):
    """The run-40 shape: the process VANISHES. faulthandler must write the dying
    stacks to the crash file even though nohup/stderr shows nothing."""
    proc, log = _run(tmp_path, f"{_IMPORT}\nimport faulthandler\nfaulthandler._sigsegv()")
    assert proc.returncode != 0
    assert "Segmentation fault" in log or "SIGSEGV" in log


def test_clean_exit_writes_marker(tmp_path):
    proc, log = _run(tmp_path, _IMPORT)
    assert proc.returncode == 0
    assert "crash-forensics armed" in log
    assert "clean interpreter exit" in log


def test_watchdog_exit_note_reaches_crash_log(tmp_path):
    """Review w6x6art4t: main.py's shutdown watchdog exits via os._exit, which
    SKIPS atexit — without an explicit note a SUCCESSFUL watchdog-exit run reads
    as SIGKILL/OOM in the crash log. _force_exit now writes through
    _forensics_note; prove the armed note helper hits the file, and pin the
    _force_exit call site in source."""
    code = (f"{_IMPORT} as m\n"
            "m._forensics_note('shutdown-watchdog exit rc=0 (result durable; asyncio cleanup hung)')")
    proc, log = _run(tmp_path, code)
    assert proc.returncode == 0
    assert "shutdown-watchdog exit rc=0" in log
    src = (LLM / "main.py").read_text(encoding="utf-8")
    fe = src.index("def _force_exit():")
    assert "_forensics_note" in src[fe:src.index("_os._exit", fe)]


def test_kill_switch_writes_nothing(tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{ROOT}{os.pathsep}{LLM}"
    env["ENVGEN_CRASH_LOG"] = "0"
    proc = subprocess.run([sys.executable, "-c", _IMPORT], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0
    assert not (tmp_path / "envgen_crash.log").exists()
    assert not (tmp_path / "0").exists()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
