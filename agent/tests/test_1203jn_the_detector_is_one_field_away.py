r"""#1203jn: the deterministic detector for #1203jf is blocked by a missing CONTRACT FIELD.

An anonymous `GET /api/auth/me` returning 401 is the commonest nameable cause of the top
final-gate blocker (15 records across 7 runs; r170's terminal blocker was exactly that).
#1203jf fixed the framework's own half-stated advice, and said honestly that prose moves
agent behaviour weakly — so the question is what the deterministic form needs.

★ NOT "is this call token-gated". That needs control flow through lane JSX, which is how
#1202td's ratchet got its blind spot. The contract-level question is "does a page a
LOGGED-OUT visitor can reach call a protected endpoint?", and two of its three inputs
already exist: `frontend_audit._effective_page_apis_1202vg` for a page's APIs and
`route_projector.resolve_endpoint_auth` for an endpoint's auth.

★★ THE THIRD DOES NOT EXIST. `registryhub_ui_pages.json` records no page-level auth: over
tiktok-web-r185's 15 registered pages, ZERO carry `auth_required`, `requires_auth`,
`public` or any equivalent. So "reachable logged out" cannot be answered from the contract,
and inferring it from names (`login_page`, `*_logged_out`) would be product vocabulary —
the predicate this repo refuses in #670 and #1203ip.

So this module is a ratchet on a BLOCKER, not on a fix: it goes red the day page-level auth
appears, which is the day the detector becomes buildable. A documented impossibility that
cannot announce its own expiry is how `#1203jj`'s park ended up pointing at a referent
nobody could evaluate.
"""
import glob
import json
import os
import pathlib
import re
import sys

import pytest

_AGENT = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(_AGENT / "env_generator" / "llm_generator"))

_AUTHISH = ("auth_required", "requires_auth", "needs_auth", "public", "authenticated",
            "auth", "access", "visibility")
_PAGE_HUBS = sorted(glob.glob(str(_AGENT.parent / "generated" / "*" / "shared" / "hubs"
                                 / "registryhub_ui_pages.json")))


def _comment_block_1203jn(src, marker):
    """The contiguous comment block that starts at `marker`, as text.

    ★ NOT `src[i:i + N]`. #943 forbids a fixed-width source window in a test and two
    ratchets caught the first version of this file doing it — a byte count drifts the day
    the comment is reworded, and then the assertion silently reads the wrong lines (which is
    how a byte-window ratchet came to read my own comment, #1202w3). The landmark is the
    block itself: start at the marker's line, stop at the first line that is not a comment.
    """
    lines = src.splitlines()
    start = next(i for i, l in enumerate(lines) if marker in l and l.strip().startswith("#"))
    out = []
    for l in lines[start:]:
        if not l.strip().startswith("#"):
            break
        out.append(l)
    return "\n".join(out)


def test_the_two_inputs_that_exist_still_exist():
    """★ The comment claims the detector is ONE field away. If either half is renamed the
    claim is silently wrong, and the next reader is told a tractable thing is intractable."""
    from multi_agent.runtime import frontend_audit as FA
    from multi_agent.runtime import route_projector as RP
    assert callable(getattr(FA, "_effective_page_apis_1202vg", None)), \
        "frontend_audit._effective_page_apis_1202vg is gone — #1203jn's claim needs re-reading"
    assert callable(getattr(RP, "resolve_endpoint_auth", None)), \
        "route_projector.resolve_endpoint_auth is gone — same"


@pytest.mark.skipif(not _PAGE_HUBS, reason="no generated/ corpus in this checkout")
def test_no_registered_page_carries_auth_metadata():
    """★ THE RATCHET ON THE BLOCKER. Red here is GOOD NEWS: it means a page now says
    whether a logged-out visitor can reach it, so the #1203jf detector can be written and
    this module plus the comment it guards should be replaced by it."""
    carriers = []
    pages = 0
    for p in _PAGE_HUBS:
        try:
            hub = json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
        except Exception:
            continue
        for k, v in hub.items():
            if k == "_meta" or not isinstance(v, dict):
                continue
            pages += 1
            for f in _AUTHISH:
                if f in v:
                    carriers.append("%s/%s.%s" % (pathlib.Path(p).parent.parent.parent.name,
                                                  k, f))
    assert pages > 50, "only %d pages scanned; the corpus or the predicate is wrong" % pages
    assert not carriers, (
        "page-level auth now EXISTS on %d page record(s) — the #1203jf detector is "
        "buildable: pair it with `_effective_page_apis_1202vg` and "
        "`resolve_endpoint_auth`, then delete this test and the #1203jn comment. "
        "Examples: %s" % (len(carriers), carriers[:5]))


@pytest.mark.skipif(not _PAGE_HUBS, reason="no generated/ corpus in this checkout")
def test_the_page_records_do_carry_their_apis():
    """The OTHER half of "one field away": a page already says which APIs it uses, so the
    missing piece really is only the auth side. Without this the claim would be two fields
    away and the comment would overstate how close it is."""
    with_apis = pages = 0
    for p in _PAGE_HUBS:
        try:
            hub = json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
        except Exception:
            continue
        for k, v in hub.items():
            if k == "_meta" or not isinstance(v, dict):
                continue
            pages += 1
            if v.get("apis_used") or (isinstance(v.get("metadata"), dict)
                                      and v["metadata"].get("apis_used")):
                with_apis += 1
    assert pages, "no page records found"
    assert with_apis, (
        "no page record carries `apis_used`, so the detector is TWO fields away, not one — "
        "#1203jn's comment overstates how close it is")


def test_the_comment_records_the_measurement():
    """A documented impossibility has to carry its own numbers, or the next reader redoes
    the measurement — #1203jj's lesson, one ticket earlier."""
    import inspect
    from multi_agent.runtime import test_user_runner as TUR
    window = _comment_block_1203jn(inspect.getsource(TUR), "#1203jn")
    assert "registryhub_ui_pages.json" in window, "the comment no longer names the store"
    assert "15" in window and "ZERO" in window, (
        "the comment no longer carries the count that makes it checkable")
    assert "_effective_page_apis_1202vg" in window and "resolve_endpoint_auth" in window, (
        "the comment no longer names the two inputs that DO exist")
