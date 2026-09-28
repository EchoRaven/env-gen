"""#1202xl: the path-param guard inspected only segments that were already well-formed.

`register_endpoint` has rejected a nameless `{}` since #57, because the projector emits it
verbatim and `def h(: str, ...)` is a SyntaxError that crash-loops the backend. The test it
applied was `_seg.startswith("{") and _seg.endswith("}")` -- so a segment that opens a brace
and does NOT close it was skipped entirely, which is the malformed case the guard exists for.

tiktok-r121's backend lane registered `GET /api/videos/{encodeURIComponent}(id)` -- a JS
template expression pasted into a contract -- at status=implemented. Nothing objected, and it
shipped into that run's MCP server as a tool `get_videos_by_encodeURIComponent_id` pointing at
a path no route can match. Its sibling `.../comments` went the same way.

Same shape as #1202xf: a guard that covers the case that was never in danger.

BLAST RADIUS MEASURED BEFORE WIDENING, because tightening a validator can reject work that
was fine: of the 4,940 endpoint paths registered across the corpus, exactly 2 are newly
rejected -- r121's two. Zero collateral.
"""
import os
import sys

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402


@pytest.fixture
def hub(tmp_path):
    return RegistryHub(str(tmp_path))


_OK = [
    "/api/videos",
    "/api/videos/{id}",
    "/api/videos/{videoId}/comments",
    "/api/users/{user_id}/followers",
    "/api/v1/tenants/{tenant_id}",
    "/health",
]

_BAD = [
    "/api/messages/{}",                        # #57's original: nameless
    "/api/videos/{encodeURIComponent}(id)",    # #1202xl: r121's, opens and never closes
    "/api/videos/{encodeURIComponent}(id)/comments",
    "/api/videos/{id",                         # unclosed
    "/api/videos/id}",                         # unopened
    "/api/videos/{2id}",                       # not an identifier
    "/api/videos/x{id}",                       # brace not the whole segment
    "/api/videos/{id}x",
]


@pytest.mark.parametrize("path", _OK)
def test_a_well_formed_path_still_registers(hub, path):
    """★ The measurement said zero collateral; this is that claim as a test."""
    got = hub.register_endpoint("GET", path, provider="backend", agent="backend")
    assert got, path


@pytest.mark.parametrize("path", _BAD)
def test_a_malformed_segment_is_rejected(hub, path):
    with pytest.raises(ValueError) as exc:
        hub.register_endpoint("GET", path, provider="backend", agent="backend")
    assert "NAMED identifier" in str(exc.value), str(exc.value)


def test_the_message_names_the_offending_segment(hub):
    """#983's rule for a rejection too: say WHAT was wrong, not only that something was.

    Uses a segment that does NOT appear in the guidance text. The first draft asserted on
    `{encodeURIComponent}(id)` -- which the message quotes as its own EXAMPLE -- so a mutation
    that dropped the f-string and stopped naming the real segment still passed.
    """
    with pytest.raises(ValueError) as exc:
        hub.register_endpoint("GET", "/api/widgets/{zzTopSecret}(k)",
                              provider="backend", agent="backend")
    msg = str(exc.value)
    assert "{zzTopSecret}(k)" in msg, ("the offending segment is not named: %s" % msg)
    assert "/api/widgets/{zzTopSecret}(k)" in msg, ("the whole path is not shown: %s" % msg)


def test_the_r121_shape_is_what_regressed(hub):
    """★ Pins the exact input that got through, so a future rewrite of the condition cannot
    quietly re-open it. The old test was `startswith('{') and endswith('}')`, which this
    segment fails on the RIGHT side -- so it was skipped rather than checked."""
    seg = "{encodeURIComponent}(id)"
    assert seg.startswith("{") and not seg.endswith("}"), (
        "the fixture no longer reproduces the skip that caused this")
    with pytest.raises(ValueError):
        hub.register_endpoint("GET", "/api/videos/" + seg, provider="backend", agent="backend")


# --- #1202xm: the defense for garbage ALREADY stored had the identical hole ----------------

from multi_agent.runtime.route_projector import (  # noqa: E402
    _sanitize_path_params,
    _path_params,
)


@pytest.mark.parametrize("path,expect", [
    ("/api/videos/{id}", "/api/videos/{id}"),
    ("/api/users/{user_id}/followers", "/api/users/{user_id}/followers"),
    ("/health", "/health"),
])
def test_a_well_formed_path_is_left_alone(path, expect):
    """★ 4,940 corpus paths, 2 differ under the widened rule. This is that claim."""
    assert _sanitize_path_params(path) == expect


@pytest.mark.parametrize("path", [
    "/api/videos/{}",
    "/api/videos/{2id}",
    "/api/videos/{encodeURIComponent}(id)",
    "/api/videos/{encodeURIComponent}(id)/comments",
    "/api/videos/{id",
    "/api/videos/id}",
])
def test_a_malformed_segment_is_rewritten_to_a_positional_param(path):
    got = _sanitize_path_params(path)
    assert "param_" in got, got
    for bad in ("encodeURIComponent", "{}", "{2id}"):
        assert bad not in got, (path, got)


def test_the_rewritten_path_yields_a_usable_param_name():
    """★ The point of rewriting: the projected handler must have a valid Python parameter.
    Before this, `{encodeURIComponent}(id)` produced NO param at all while the route text
    still carried a brace -- a handler whose signature and route disagree."""
    got = _sanitize_path_params("/api/videos/{encodeURIComponent}(id)")
    params = _path_params(got)
    assert params == ["param_4"], params
    assert all(p.isidentifier() for p in params), params


def test_both_doors_are_closed():
    """★ #1202xl guards registration; this guards what is already stored. Fixing only one is
    worse than fixing neither, because the stored garbage is what the second one exists for."""
    bad = "/api/widgets/{zzOpenNeverClosed}(k)"

    # Door 1: registration refuses it. Behavioural, not a source-text match -- the first
    # draft asserted on the literal `"{" in seg` and failed because the guard spells the
    # same idea as `"{" not in _seg: continue`. Third time this session that a source-text
    # assertion measured the spelling instead of the behaviour.
    import tempfile
    from multi_agent.runtime.registryhub import RegistryHub as _RH
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(ValueError):
            _RH(d).register_endpoint("GET", bad, provider="backend", agent="backend")

    # Door 2: what is already stored is rewritten rather than projected verbatim.
    got = _sanitize_path_params(bad)
    assert "zzOpenNeverClosed" not in got, got
    assert _path_params(got) and all(p.isidentifier() for p in _path_params(got)), got
