"""Calibration spike for the simple_blog oracle (R2 round-10 scope:
arm 3 DROPPED — airbnb is cross-domain noise; auth-helper coverage
already provided by arm 1b on a real Bearer simple_blog).

This test file is the calibration harness for the north-star oracle.
It is NOT a regression test in the agent suite; it is a measurement
script run by an operator (or a CI pilot) to confirm the oracle is
both signal-positive on correct apps and signal-negative on a known
subtle bug. Per A2 conftest collect_ignore it is NOT picked up by a
default ``pytest tests/`` run.

Arms (R2 round-10 corrected scope):

  arm_1a_green_on_reference  — Oracle vs reference_impl. ALL flows
      must pass; if any fail, the oracle is broken (false-negative).

  arm_1b_green_on_target     — Oracle vs target_impl (cross-stack:
      Express/Bearer/_api/_ prefix). ALL flows must pass; if any
      fail, the oracle is over-strict on convention (false-fails
      improvements). This is the real make-or-break cross-stack test.

  arm_2_catches_broken       — Oracle vs target_impl_broken (R2
      round-10 Q2: broken is target_impl + ONE auth-middleware line
      mutation, not an independent simpler app). The
      unauthenticated-create flow MUST fail; if it doesn't, the
      oracle is under-strict on behavior (false-negative on a real
      bug). Other flows are expected to pass; if additional flows
      fail unexpectedly the verdict is RAW_DATA so the human can
      route to R2 — do NOT silently re-loosen the oracle.

  arm_4_fixture_reliability  — Run runner.run_app(target_impl) 5
      times, count successes. Docker-compose-up flakiness is the
      hidden A1 #2 R2 named — measure it so we can decide whether
      to add retries.

DROPPED per R2 round-10:
  arm_3_airbnb_auth_helper   — Was a _conventions.authenticate smoke
      against airbnb. Airbnb is wrong-domain (no /posts) and has a
      separate seed-SQL bug (02_seed.sql:70 date+bigint). Coverage
      of the Bearer auth path is provided by arm 1b on the real
      simple_blog. "Real-generated-app oracle test" belongs in
      pilot's calibration arm (PINNED_GENERATED_APP), not this spike.

Output: a single ``##SPIKE_RESULT## {json}`` line at the end of the
final test for machine-parseable consumption by the orchestration
script. Each arm produces verdict PASS / FAIL / RAW_DATA so a
human-in-the-loop can route mixed signals to R2 for adversarial
verification.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple
from xml.etree import ElementTree as ET

import pytest

# Make sibling runner.py importable without requiring simple_blog to
# be a package. The calibration test file lives in
# simple_blog/oracle_validation/; runner.py lives in simple_blog/.
_THIS = Path(__file__).resolve()
_SIMPLE_BLOG_DIR = _THIS.parent.parent
if str(_SIMPLE_BLOG_DIR) not in sys.path:
    sys.path.insert(0, str(_SIMPLE_BLOG_DIR))

import runner  # noqa: E402

_AGENT_DIR = _SIMPLE_BLOG_DIR.parent.parent.parent  # agent/


# ---------------------------------------------------------------------------
# Constants — paths and expectations
# ---------------------------------------------------------------------------

REFERENCE_IMPL = _SIMPLE_BLOG_DIR / "reference_impl"
TARGET_IMPL = _SIMPLE_BLOG_DIR / "target_impl"
TARGET_IMPL_BROKEN = _SIMPLE_BLOG_DIR / "target_impl_broken"
ORACLE_DIR = _SIMPLE_BLOG_DIR / "oracle"

# The flow we expect arm 2 to surface as failing. The test in
# oracle/test_create_post.py is named
# ``test_unauthenticated_post_creation_is_rejected`` — that's the
# unauthenticated-create rejection assertion the broken middleware
# violates by silently treating no-token as anonymous.
EXPECTED_BROKEN_FAILURES = {"test_unauthenticated_post_creation_is_rejected"}

# (R2 round-10 DROP arm 3) AIRBNB_COMPOSE_DIR constant removed.

# Global container for the result blob so the final aggregator can
# print it regardless of which arm tests pass/fail individually. We
# use module-level state because pytest's test ordering for this
# file is deterministic (in-file order).
SPIKE_RESULT: Dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Oracle invocation — subprocess so per-arm env is fully isolated
# ---------------------------------------------------------------------------

def _run_oracle(api_url: str, app_path: str) -> Tuple[List[str], List[str], str]:
    """Run the oracle as a subprocess against the given api_url +
    app_path. Returns (passed_tests, failed_tests, raw_log).

    Why subprocess and not pytest.main(): re-entering pytest mid-test
    is allowed but corrupts the running session's collection cache
    and warning filters in pytest >= 7. A subprocess gets a fresh
    pytest interpreter and lets us pass ORACLE_API_URL / ORACLE_APP_PATH
    via env without leaking into the parent's environ.

    We use --junit-xml for structured per-test outcomes — parsing
    stdout for "PASSED"/"FAILED" is fragile against ANSI escapes and
    capture mode differences.
    """
    with tempfile.TemporaryDirectory() as td:
        xml_path = Path(td) / "oracle.xml"
        env = os.environ.copy()
        env["ORACLE_API_URL"] = api_url
        env["ORACLE_APP_PATH"] = app_path

        # confcutdir MUST be tighter than tests/north_star/ because
        # the conftest at tests/north_star/conftest.py declares a
        # collect_ignore that skips every .py file in the subtree
        # (deliberate — keeps the oracle out of the default agent
        # pytest run). We point confcutdir at simple_blog/ so the
        # oracle's own conftest (which exposes api_url + app_path
        # fixtures) still loads but the north_star collect_ignore
        # doesn't.
        cmd = [
            sys.executable, "-m", "pytest",
            str(ORACLE_DIR),
            "--confcutdir", str(_SIMPLE_BLOG_DIR),
            f"--junit-xml={xml_path}",
            "-q",
            "--tb=short",
            "-p", "no:cacheprovider",
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(_AGENT_DIR),
            capture_output=True,
            timeout=300,
            env=env,
        )
        log = proc.stdout.decode("utf-8", errors="replace") + \
              proc.stderr.decode("utf-8", errors="replace")

        passed: List[str] = []
        failed: List[str] = []
        if xml_path.exists():
            try:
                tree = ET.parse(xml_path)
                root = tree.getroot()
                # JUnit XML: testsuite/testcase elements. A testcase
                # with no failure/error/skipped child = passed.
                for tc in root.iter("testcase"):
                    name = tc.attrib.get("name", "?")
                    is_failure = (
                        tc.find("failure") is not None
                        or tc.find("error") is not None
                    )
                    if is_failure:
                        failed.append(name)
                    elif tc.find("skipped") is not None:
                        # Skipped tests are oracle-inapplicable — we
                        # don't count them as passes or failures.
                        # The calibration arms shouldn't trigger
                        # skips; if they do, surface via log.
                        pass
                    else:
                        passed.append(name)
            except ET.ParseError as e:
                log += f"\n[calibration] junit parse error: {e}"
        else:
            log += "\n[calibration] no junit xml emitted"

        return passed, failed, log


# ---------------------------------------------------------------------------
# Arm 1a — Oracle green on reference_impl
# ---------------------------------------------------------------------------

def test_arm_1a_green_on_reference():
    api_url, app_path, reason = runner.run_app(str(REFERENCE_IMPL))
    try:
        if api_url is None:
            # Fixture failure — record as RAW_DATA so the orchestrator
            # can decide. We do NOT call this a FAIL of the oracle:
            # the oracle never ran.
            SPIKE_RESULT["arm_1a_green_on_reference"] = {
                "flows_passed": 0,
                "flows_failed": 0,
                "verdict": "RAW_DATA",
                "fixture_failure": reason,
            }
            pytest.skip(f"fixture failure (not oracle judgment): {reason}")

        passed, failed, log = _run_oracle(api_url, app_path)
        verdict = "PASS" if (failed == [] and passed) else "FAIL"
        SPIKE_RESULT["arm_1a_green_on_reference"] = {
            "flows_passed": len(passed),
            "flows_failed": len(failed),
            "failed_tests": failed,
            "verdict": verdict,
        }
        assert verdict == "PASS", (
            f"oracle false-fails on reference_impl: {failed}\nlog tail:\n"
            f"{log[-1500:]}"
        )
    finally:
        runner.teardown(str(REFERENCE_IMPL))


# ---------------------------------------------------------------------------
# Arm 1b — Oracle green on target_impl (cross-stack)
# ---------------------------------------------------------------------------

def test_arm_1b_green_on_target():
    api_url, app_path, reason = runner.run_app(str(TARGET_IMPL))
    try:
        if api_url is None:
            SPIKE_RESULT["arm_1b_green_on_target"] = {
                "flows_passed": 0,
                "flows_failed": 0,
                "verdict": "RAW_DATA",
                "fixture_failure": reason,
            }
            pytest.skip(f"fixture failure (not oracle judgment): {reason}")

        passed, failed, log = _run_oracle(api_url, app_path)
        verdict = "PASS" if (failed == [] and passed) else "FAIL"
        SPIKE_RESULT["arm_1b_green_on_target"] = {
            "flows_passed": len(passed),
            "flows_failed": len(failed),
            "failed_tests": failed,
            "verdict": verdict,
        }
        assert verdict == "PASS", (
            f"oracle false-fails on target_impl (cross-stack convention "
            f"mismatch?): {failed}\nlog tail:\n{log[-1500:]}"
        )
    finally:
        runner.teardown(str(TARGET_IMPL))


# ---------------------------------------------------------------------------
# Arm 2 — Oracle catches the subtle auth-break
# ---------------------------------------------------------------------------

def test_arm_2_catches_broken():
    api_url, app_path, reason = runner.run_app(str(TARGET_IMPL_BROKEN))
    try:
        if api_url is None:
            SPIKE_RESULT["arm_2_catches_broken"] = {
                "expected_failed_flows": sorted(EXPECTED_BROKEN_FAILURES),
                "actual_failed_flows": [],
                "verdict": "RAW_DATA",
                "fixture_failure": reason,
            }
            pytest.skip(f"fixture failure (not oracle judgment): {reason}")

        passed, failed, log = _run_oracle(api_url, app_path)
        actual_failed = sorted(failed)
        expected = sorted(EXPECTED_BROKEN_FAILURES)

        # PASS verdict requires:
        #   (a) the expected unauth-create test IS in actual_failed
        #       (oracle caught the subtle bug), AND
        #   (b) no UNEXPECTED extra failures (target_impl_broken is
        #       supposed to be IDENTICAL to target_impl except auth).
        # If (a) holds but (b) doesn't, verdict is RAW_DATA — extras
        # mean target_impl_broken diverged from target_impl in other
        # ways, which is a fixture-quality issue, not an oracle
        # signal failure. Human-in-the-loop decides.
        caught_subtle = EXPECTED_BROKEN_FAILURES.issubset(set(actual_failed))
        unexpected_extra = sorted(set(actual_failed) - EXPECTED_BROKEN_FAILURES)
        if caught_subtle and not unexpected_extra:
            verdict = "PASS"
        elif caught_subtle and unexpected_extra:
            verdict = "RAW_DATA"
        else:
            verdict = "FAIL"

        SPIKE_RESULT["arm_2_catches_broken"] = {
            "expected_failed_flows": expected,
            "actual_failed_flows": actual_failed,
            "unexpected_extra_failures": unexpected_extra,
            "caught_subtle_bug": caught_subtle,
            "verdict": verdict,
        }
        assert caught_subtle, (
            f"oracle MISSED the R2 round-9 subtle auth bypass "
            f"(test_unauthenticated_post_creation_is_rejected should "
            f"have failed but did not). actual failed: {actual_failed}\n"
            f"log tail:\n{log[-1500:]}"
        )
    finally:
        runner.teardown(str(TARGET_IMPL_BROKEN))


# ---------------------------------------------------------------------------
# Arm 3 DROPPED per R2 round-10 (airbnb is cross-domain noise; arm 1b
# already covers the Bearer auth path with a real simple_blog).
# Airbnb's date+bigint seed-SQL bug is a separate demo-bug ticket.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Arm 4 — Fixture reliability (N/5 successes for target_impl up/down)
# ---------------------------------------------------------------------------

def test_arm_4_fixture_reliability():
    attempts = 5
    successes = 0
    reasons: List[Optional[str]] = []
    for _ in range(attempts):
        api_url, app_path, reason = runner.run_app(str(TARGET_IMPL))
        try:
            if api_url is not None:
                successes += 1
            reasons.append(reason)
        finally:
            runner.teardown(str(TARGET_IMPL))

    SPIKE_RESULT["arm_4_fixture_reliability"] = {
        "successes": successes,
        "attempts": attempts,
        "failure_reasons": [r for r in reasons if r],
    }
    # No strict pass/fail threshold — arm 4 is RAW_DATA by design.
    # We surface the rate so the human-in-the-loop can decide whether
    # to add a retry policy to runner.run_app.


# ---------------------------------------------------------------------------
# Aggregator — emits the ##SPIKE_RESULT## machine-parseable line
# ---------------------------------------------------------------------------

def test_zzz_emit_spike_result():
    """Final test (alphabetical ordering after arms 1-4 puts this
    last in the file). Emits the structured ##SPIKE_RESULT## line
    that the orchestration script parses.

    Named with ``zzz_`` to deterministically sort after all arm tests
    without depending on pytest plugins like pytest-ordering. The
    pytest default is file-order then within-file source-order, so
    technically this would already run last by source order — the
    name belt-and-braces against future reordering.
    """
    # Always print, even if individual arms errored. Missing arms
    # appear as absent keys; the consumer can route them to
    # RAW_DATA.
    print("\n##SPIKE_RESULT## " + json.dumps(SPIKE_RESULT, sort_keys=True))
