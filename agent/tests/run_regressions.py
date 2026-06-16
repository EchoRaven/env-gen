"""Regression runner — DEPRECATED entry point.

This used to be the only declared regression runner, but it only
loaded 3 test classes out of the 216+ in this directory (reviewer
audit 3.7 high #2: "唯一声明的 runner 只接了 216 个测试文件里的 3 个").
Phase 0.1 of the SDLC refactor (docs/progressive_elaboration_refactor.md)
swapped it for a thin pytest delegate so the legacy entry point still
works against the whole suite.

Run all tests:
    python -m pytest tests/

Run with verbose output:
    python -m pytest tests/ -v

Run a single file:
    python -m pytest tests/test_<name>.py -v

CI: .github/workflows/test.yml runs the full suite on every PR.

Monitor-layer invariant (Phase 0.2 attempt-6 pin-count refinement,
per R2 round-5): tests/test_monitor_call_gate_invariant.py now pins
the 53 known-deferred bypassers in KNOWN_DEFERRED_TO_EXT. The invariant
goes GREEN as long as the current bypasser set equals the pinned set;
it RED's only on regression (a 54th endpoint added) or progress
(Phase 0.2-EXT closes a bypasser but the pin isn't updated). This
replaces the earlier --deselect approach, which left the monitor
layer un-guarded in CI between Phase 0.2 narrow ship and Phase 0.2-EXT.
"""

import subprocess
import sys
from pathlib import Path


def main() -> int:
    tests_dir = Path(__file__).resolve().parent
    cmd = [sys.executable, "-m", "pytest", str(tests_dir), "--tb=short", "-q"]
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())
