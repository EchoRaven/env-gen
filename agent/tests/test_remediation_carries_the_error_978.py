"""#978: the remediation message must carry the error, not a container id.

r158 dispatched this to the verifier:

    FAILING-CHECK remediation dispatched to verifier (task …): docker_up —
    bcd1251d323e44bd8ebf4367215be5d1fc9b289acd296408d28e66b4f732f1bf

64 hex characters of container id. The raw `docker_up` detail begins with one
(`docker_up:<container> <ts> UTC [58] ERROR: …`) and the dispatcher sliced `detail[:160]`,
so the lane was handed the prefix and none of the error.

This is #182 verbatim — "a blind prefix slice lands on the meaningless banner and hides the
real cause" — and `_salient_error` exists to end it. The reporting path calls it; this call
site never did. It is the one text whose entire job is telling an agent what to fix.

Cap is 600 rather than the reporting path's 200: a lane acts on this, a human skims that.
"""

import pytest

from env_generator.llm_generator.multi_agent.runtime.framework_validation import (
    _salient_error)

# r158's actual docker_up detail shape.
DOCKER_UP_DETAIL = (
    "docker_up:bcd1251d323e44bd8ebf4367215be5d1fc9b289acd296408d28e66b4f732f1bf "
    "2026-08-19 00:20:10.317 UTC [58] ERROR:  syntax error at or near \"?\" at character 170\n"
    "2026-08-19 00:20:10.317 UTC [58] STATEMENT:  SELECT * FROM titles WHERE id = ?\n"
)


def test_the_prefix_slice_yields_only_the_container_id():
    """What the lane actually received in r158 — the control for this fix."""
    assert "ERROR" not in DOCKER_UP_DETAIL[:70], (
        "if the raw prefix already contained the error there would be nothing to fix"
    )


def test_the_salient_line_reaches_the_lane():
    out = _salient_error(DOCKER_UP_DETAIL, cap=600)
    assert "syntax error" in out
    assert "SELECT * FROM titles" in out, "#973 pairs the STATEMENT with the ERROR"


def test_the_id_is_no_longer_the_whole_message():
    """`_salient_error` keeps whole LINES, and the container id shares a line with the
    error, so it rides along — that is fine. What must change is that the error is present
    at all instead of 160 characters of hex."""
    out = _salient_error(DOCKER_UP_DETAIL, cap=600)
    assert "syntax error" in out[:600]
    assert len(out.replace("bcd1251d323e44bd8ebf4367215be5d1fc9b289acd296408d28e66b4f732f1bf",
                           "")) > 40, "the message must be more than the id"


def test_the_dispatcher_routes_detail_through_it():
    """Pinned on the source, because the behavioural path needs a live orchestrator."""
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd
    src = inspect.getsource(rd)
    assert "_salient_978" in src, "the dispatcher must extract before it truncates"
    # anchor on the CALL, not the substring — this module's own comment quotes the slice
    i_extract = src.index("detail = _salient_978(")
    i_slice = src.index("name, detail[:160])")
    assert i_extract < i_slice, "extraction has to happen before the slice, not after"


def test_a_short_plain_detail_is_untouched():
    """Most checks already report one clean line; extraction must not mangle them."""
    plain = "GET /api/titles/trending → 500; GET /api/titles/top10 → 500"
    assert _salient_error(plain, cap=600) == plain


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
