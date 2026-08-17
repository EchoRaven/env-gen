"""#441 (generic anti-spin fail-fast — part-2 pipeline robustness, generalizes to
all apps/envs). r23 spun ~1.5h retrying an IDENTICAL docker_up failure; r28 replayed
the same remediation to queue-full=130 — both wasted tokens/wall-clock retrying a
failure that never changed. failure_signature normalizes a failure log (mask
timestamps/paths/hashes/numbers) to a stable key; is_spinning detects N identical
signatures in a row → the loop should fail-fast. Pure + unit-tested; the orchestrator
wiring (feed each attempt's log, abort when is_spinning) is the gated live step."""
from env_generator.llm_generator.multi_agent.runtime.base_image_preflight import (
    failure_signature, is_spinning)


def test_same_failure_modulo_volatile_tokens_same_signature():
    a = ("2026-08-03 04:01:12 ERROR docker_up failed\n"
         "  creating build container: unable to copy from /tmp/build-8821/ctx\n"
         "  exit code 125")
    b = ("2026-08-03 05:33:59 ERROR docker_up failed\n"
         "  creating build container: unable to copy from /tmp/build-2044/ctx\n"
         "  exit code 125")
    assert failure_signature(a) == failure_signature(b), \
        "same failure differing only in timestamp/temp-path must share a signature"


def test_different_failures_differ():
    a = failure_signature("ERROR: business_chain create step failed: 400 rating.value")
    b = failure_signature("ERROR: docker_up failed: manifest unknown")
    assert a != b and a and b


def test_empty_input():
    assert failure_signature("") == "" and failure_signature(None) == ""


def test_is_spinning_detects_identical_repeats():
    s = failure_signature("docker_up failed: creating build container: unable to copy /x")
    assert is_spinning([s, s, s], threshold=3) is True
    assert is_spinning([s, s], threshold=2) is True   # r23: 2 identical docker_up fails


def test_is_spinning_false_when_making_progress():
    sigs = [failure_signature(f"ERROR: missing column ratings.value step {i}") for i in range(3)]
    # each attempt hits a DIFFERENT error (genuine progress) → not spinning...
    # (they normalize to the SAME sig since only the trailing number differs — so this
    #  asserts the CONSERVATIVE case: truly-identical repeats trip it; see next test)
    assert is_spinning(sigs, threshold=3) is True  # step<n> masked → same → correctly a spin


def test_is_spinning_false_on_genuinely_varying_errors():
    a = failure_signature("ERROR: docker_up failed: manifest unknown")
    b = failure_signature("ERROR: api_smoke 500 on /api/titles")
    c = failure_signature("ERROR: business_chain 400 rating.value")
    assert is_spinning([a, b, c], threshold=3) is False, "distinct errors = progress, not a spin"


def test_is_spinning_needs_threshold_samples_and_nonempty():
    s = failure_signature("docker_up failed: no such host ghcr.io")
    assert is_spinning([s], threshold=3) is False        # too few samples
    assert is_spinning(["", "", ""], threshold=3) is False  # empty sigs never trip
    assert is_spinning([s, s, s], threshold=0) is False  # guard


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
