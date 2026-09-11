"""#1190 — the frontend said which profile was active and the server never read it.

netflix-r22's DELIVERED release 1.0.0, probed directly: one account, two profiles. A title
added under profile 12 came back verbatim when reading as profile 13, and continue-watching
behaved the same. `X-Profile-ID` — which api.js sends on every call — appears 0 times in the
delivered main.py and 0 times in custom_routes.py. `_fw_owner_val` resolves "the caller's
FIRST row in T", so every profile of one account resolves to the same owner value.

The run's own description asks for the opposite in as many words: "Each profile sees only its
own My List, ratings and Continue Watching (per-profile private data)."

NOT a cross-account leak: a second account sees none of it (verified — `GET /api/profiles`
for another user returned `{"items":[],"total":0}`, and my_list rows are user-scoped through
the profile). This is the boundary INSIDE one account.

The safety property is what these tests pin. An earlier attempt at per-profile scoping
fail-opened and was reverted; this one can only ever NARROW, because the header is honoured
only after `_fw_owns` confirms the caller owns that sub-entity.
"""
import ast
import re

from env_generator.llm_generator.multi_agent.runtime import backend_skeleton as bs
from env_generator.llm_generator.multi_agent.runtime import backend_scaffold as bsc

_HDR = bs._MAIN_HEADER
_RESOLVER = _HDR[_HDR.index("def _fw_owner_val("):]
_RESOLVER = _RESOLVER[:_RESOLVER.index("\ndef ", 1)]


def test_the_generated_backend_still_parses():
    ast.parse(_HDR)


def test_the_active_profile_is_published_by_the_middleware():
    src = bsc.__loader__.get_source(bsc.__name__)
    i = src.index("async def _framework_auth_guard(")
    body = src[i:src.index("\n    p = request.url.path", i)]
    assert "_FW_PROFILE_CTX_1190.set(" in body, "the header must be published per request"
    assert "x-profile-id" in body.lower()
    assert "except Exception" in body, "publishing must never break a request"


def test_the_override_is_gated_by_ownership():
    """★ The whole safety argument: the header is honoured only for a sub-entity the caller
    owns, so it can narrow to another of their own profiles and nothing else."""
    # #1202ks: the gate is now asked STRICTLY. The old form pinned the exact call text and
    # broke on the added argument; assert the gate and the strictness, since fail-open on that
    # gate is precisely what made #1190's "can only NARROW" claim untrue.
    assert "_fw_owns(cls, col, _act1190, user, strict=True)" in _RESOLVER
    guard = _RESOLVER[_RESOLVER.index("_act1190 = _FW_PROFILE_CTX_1190.get()"):]
    guard = guard[:guard.index("_v = _act1190")]
    assert "_fw_owns(" in guard, "no assignment may precede the ownership check"


def test_an_absent_or_unowned_header_changes_nothing():
    """Both fall through to the resolution that exists today."""
    blk = _RESOLVER[_RESOLVER.index("_act1190 = _FW_PROFILE_CTX_1190.get()"):]
    cond = blk[:blk.index("\n")+ blk.index("_v = _act1190")]
    assert "_act1190 not in (None, \"\")" in blk, "absent must fall through"
    assert "_v = _act1190" in blk and blk.index("if ") < blk.index("_v = _act1190")


def test_a_failure_falls_back_rather_than_raising():
    blk = _RESOLVER[_RESOLVER.index("_act1190 = _FW_PROFILE_CTX_1190.get()"):]
    tail = blk[:blk.index("_pt = getattr(cls, col).type.python_type")]
    assert "except Exception as _e1190" in tail, "resolution must never raise from this"


def test_the_override_precedes_the_type_coercion():
    """The header arrives as a string; the column may be Integer. Overriding after the
    coercion would bind a str against an int column — #134's exact 500."""
    assert _RESOLVER.index("_v = _act1190") < _RESOLVER.index(
        "_pt = getattr(cls, col).type.python_type")


def test_the_context_var_and_its_import_are_both_emitted():
    assert "import contextvars as _cv1190" in _HDR
    assert "_FW_PROFILE_CTX_1190 = _cv1190.ContextVar(" in _HDR
    assert _HDR.index("import contextvars") < _HDR.index("_FW_PROFILE_CTX_1190 =")
