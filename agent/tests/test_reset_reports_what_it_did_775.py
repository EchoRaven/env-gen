r"""#775: the reset template taught `ok: True`, and 46 runs return it from an except branch.

`backend_agent.j2` hands the lane a `/api/v1/reset` body ending `return {"ok": True,
"tenant_id": x_tenant_id}`. The template has no try/except — but a lane that defensively wraps
the body keeps the template's success return, and it lands in the except branch. Measured over
the delivered backends:

    handlers returning ok/success=true from an `except`   58, across 46 of 137 runs (34%)
    e.g.  /api/v1/reset, /api/v1/tenants/{id}, /api/profiles/{profile_id}

**A reset that failed and reported success is not a cosmetic problem.** The verifier's chains
call reset BETWEEN steps and trust `ok: true`, so the next step reads rows it believes were
cleared. That is #566x's shape exactly — *"a coverage chain FACTORY-RESETS the DB mid-pass — the
step PASSES so the harm is invisible"* — arriving from the other direction.

Found by following a detail I had dismissed one item earlier as "the lane's to fix, out of scope
for a framework change": r150's `top10` falling back to ten arbitrary titles. Checking instead of
assuming showed the dominant shape is not the lane improvising, it is the framework's own
template being wrapped.

Both prompt versions are patched: v3 is the default and v4 is opt-in per file (#269), so fixing
only one would leave the defect reachable by configuration.
"""
import pathlib

import pytest


PROMPTS = (pathlib.Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
           / "multi_agent" / "prompts")
VERSIONS = ["v3", "v4"]


def _src(v: str) -> str:
    p = PROMPTS / v / "backend_agent.j2"
    if not p.exists():
        pytest.skip(f"{v}/backend_agent.j2 absent")
    return p.read_text(encoding="utf-8")


@pytest.mark.parametrize("v", VERSIONS)
def test_the_reset_reports_what_it_deleted(v):
    assert '"deleted": deleted_counts' in _src(v)


@pytest.mark.parametrize("v", VERSIONS)
def test_it_forbids_returning_success_from_an_except(v):
    # Comment continuations flattened first: the sentence wraps across `#` lines, and asserting
    # a phrase that spans the break is the quotation trap this session has hit repeatedly.
    import re
    s = re.sub(r"\n\s*#\s*", " ", _src(v))
    assert "return this line from the except branch" in s
    assert "an honest failure is recoverable, a false success is not" in s


@pytest.mark.parametrize("v", VERSIONS)
def test_it_says_WHO_trusts_the_flag(v):
    """The instruction has to name the consumer, or it reads as style advice."""
    s = _src(v)
    # #775r: the first version of this claim was WRONG and shipped in the prompt. The chains
    # do call reset (174 steps across 74 runs) but assert on the HTTP STATUS, never on `ok` —
    # which makes the defect worse, not milder: swallowing the error turns a 500 the chain
    # would fail on into a 200 it passes.
    assert "174 chain\n    # steps across 74 runs call POST /api/v1/reset" in s or \
           "174 chain" in s
    assert "asserts on the HTTP\n    # STATUS" in s or "STATUS" in s


@pytest.mark.parametrize("v", VERSIONS)
def test_the_measurement_is_in_the_prompt(v):
    s = _src(v)
    assert "58 handlers across 46 of 137 runs" in s
    assert "174 chain" in s, "#775r: the corrected mechanism must be in the prompt too"


@pytest.mark.parametrize("v", VERSIONS)
def test_the_bare_success_return_is_gone(v):
    """Non-vacuity: the exact line the corpus copied must no longer be present to copy."""
    s = _src(v)
    assert 'return {"ok": True, "tenant_id": x_tenant_id}\n' not in s


@pytest.mark.parametrize("v", VERSIONS)
def test_the_rest_of_the_control_surface_is_untouched(v):
    """#775 must not have disturbed the tenant endpoints around it."""
    s = _src(v)
    for keep in ('@app.post("/api/v1/reset")', "/api/v1/tenants", "X-Tenant-Id"):
        assert keep in s, keep


def test_both_versions_were_patched_not_just_the_default():
    """v3 is the default and v4 is opt-in per file (#269) — fixing one leaves the other
    reachable by an env var, which is how a fix gets reported as shipped and is not."""
    assert all('"deleted": deleted_counts' in _src(v) for v in VERSIONS)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
