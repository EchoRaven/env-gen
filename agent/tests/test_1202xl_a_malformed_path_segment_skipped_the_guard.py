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
