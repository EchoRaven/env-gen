r"""#636: the largest error class in the corpus, and its instruction was last.

Sweeping the 56 run logs by error class, `register_verification_chain FAILED … chain rejected:
these steps reference endpoints NOT registered` is the single biggest entry:

    514 occurrences in 50 of 50 runs
    median 18 per run for a median of 2 distinct causes   (r129: 81 rejections, 5 causes)
    71% of them one endpoint: PUT /api/profiles/{}

The verifier re-submits the same unsatisfiable chain about nine times per cause. It is not
authoring nonsense — 41 of 45 runs register NO item-level `/api/profiles/{…}` endpoint at all, so
the chain is unsatisfiable by construction and the rejection is right.

An escalation for exactly this already existed and is correct: from the second rejection of an
endpoint it says "⚠ … rejected N times … DROP those steps". It was simply LAST, appended after a
dump of every registered endpoint — median **669** chars, max 825 across 45 runs.

    A note on evidence: the escalation appears 0 times in 55 log files, and that is NOT proof the
    agent never saw it. Logs truncate the error at 300 chars, so a warning starting ~669 chars in
    could never appear there. That zero is an artifact of the instrument. What IS provable is the
    ordering — and #619/#620 already settled it: lead with what to DO, put the data after.

Two changes, both provable from the string: the escalation moves to the front, and the catalogue
is narrowed to the path actually referenced. "Every endpoint in the contract" is not an answer to
"this one is missing"; its siblings are.
"""
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub


def _rh(tmp_path):
    rh = RegistryHub(Path(tmp_path))
    for m, p in (("POST", "/auth/register"), ("POST", "/auth/login"),
                 ("GET", "/api/profiles"), ("POST", "/api/profiles"),
                 ("GET", "/api/titles"), ("GET", "/api/genres"),
                 ("GET", "/api/my-list"), ("POST", "/api/my-list")):
        rh.register_endpoint(m, p, status="implemented", agent="backend")
    return rh


def _reject(rh, name="c", path="/api/profiles/{id}", method="PUT"):
    return rh.register_verification_chain(
        name, [{"method": method, "path": path}]).get("error", "")


# --- the ordering ---------------------------------------------------------------------------------

def test_the_first_rejection_still_explains_itself(tmp_path):
    err = _reject(_rh(tmp_path))
    assert "NOT registered in" in err
    assert "PUT /api/profiles/{}" in err


def test_the_repeat_warning_comes_FIRST(tmp_path):
    """It fired before, at the end of a ~669-char dump. The instruction has to lead."""
    rh = _rh(tmp_path)
    _reject(rh, "c1")
    err = _reject(rh, "c2")
    assert err.startswith("⚠"), err[:80]
    assert err.index("rejected") < err.index("Registered on the same path")


def test_the_warning_still_says_what_to_do(tmp_path):
    rh = _rh(tmp_path)
    _reject(rh, "c1")
    err = _reject(rh, "c2")
    assert "DROP those steps" in err


def test_it_escalates_across_DIFFERENT_chain_names(tmp_path):
    """The counter is per-ENDPOINT precisely because the verifier varies the chain name."""
    rh = _rh(tmp_path)
    _reject(rh, "alpha")
    assert _reject(rh, "beta").startswith("⚠")


# --- the catalogue --------------------------------------------------------------------------------

def test_only_the_relevant_path_is_listed(tmp_path):
    err = _reject(_rh(tmp_path))
    assert "GET /api/profiles" in err and "POST /api/profiles" in err
    assert "/api/titles" not in err and "/api/genres" not in err


def test_the_rest_are_counted_not_dumped(tmp_path):
    err = _reject(_rh(tmp_path))
    assert "endpoint(s) on other paths" in err


def test_a_path_with_no_siblings_says_so(tmp_path):
    err = _reject(_rh(tmp_path), path="/api/nowhere/{id}")
    assert "(none on that path)" in err


def test_the_message_is_far_shorter_than_the_full_dump(tmp_path):
    """The dump it replaces measured 669 chars median, 825 max, across 45 runs."""
    rh = _rh(tmp_path)
    assert len(_reject(rh)) < 500


# --- it must still point at the right actor -------------------------------------------------------

def test_it_names_the_lane_that_can_actually_register(tmp_path):
    """The old text told the VERIFIER to register the endpoint — it cannot."""
    err = _reject(_rh(tmp_path))
    assert "BACKEND lane registers endpoints" in err
    assert "as the verifier, fix the chain" in err


def test_a_satisfiable_chain_is_unaffected(tmp_path):
    rh = _rh(tmp_path)
    res = rh.register_verification_chain("ok", [{"method": "GET", "path": "/api/titles"}])
    assert "error" not in res


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub
    flat = " ".join(inspect.getsource(registryhub.RegistryHub.register_verification_chain)
                    .replace("#", " ").split())
    assert "514 occurrences in 50 of 50 runs" in flat
    assert "artifact of the log, not evidence" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
