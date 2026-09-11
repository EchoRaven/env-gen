"""#1202ks: #1190 promised the profile header could "only NARROW", and delegated to a fail-open check.

`_fw_owner_val` lets a client-supplied `X-Profile-ID` override the resolved owner — but only,
its own comment says, "after `_fw_owns` confirms the caller owns it", so that "the header can
therefore only ever NARROW to another of the caller's OWN profiles", and that ownership gate is
"the difference from the earlier attempt at this, which fail-opened and was reverted".

`_fw_owns` fail-opens by design. Its docstring says so: "Fail-OPEN only on an
introspection/query FAULT (a framework bug must never block a legitimate write)". That is the
right trade for a WRITE. For the READ decision above it means the earlier attempt is exactly
what runs whenever introspection faults — and FK introspection faulting is not hypothetical
here: #1158 and #1158b both exist because `render_models` emits plain `Column(Integer)` for FKs,
so `foreign_keys` is empty and the target has to be resolved by name.

Executed against the generated source, with introspection forced to raise:

    _fw_owns(cls, "profile_id", "44", user)                -> True    (header honoured)
    _fw_owns(cls, "profile_id", "44", user, strict=True)   -> False   (header ignored)

netflix-r41's verifier caught the consequence and wrote it down verbatim:

    chain profile_scoped_my_list_isolation
    "user B cannot use user A profile header for My List"
    GET /api/my-list -> 200 {"items":[{"id":42,"profile_id":44,"title_id":1}],"total":1}
    "DENIAL-PROBE got success — the request was NOT rejected (expected denial [401, 403])"

A cross-profile read, out of a framework-PROJECTED handler, which no lane can edit.

WHAT IS VERIFIED: strict mode fails closed on every fault path in the function; non-strict is
byte-for-byte the old behaviour so writes keep #566s's bargain; an absent header is still a
no-op; and the #1190 call site is the one that asks strictly.

WHAT IS NOT: that this was the cause of every "expected denial, got 200" in the corpus. Of the
22 such steps in the last 10 days, 18 are on projected handlers and 2 were re-verified by the
framework itself as NOT leaks (#78). This closes one mechanism, on one call site.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
_LLM = _AGENT / "env_generator" / "llm_generator"
for _p in (str(_LLM), str(_AGENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import inspect     # noqa: E402
import re          # noqa: E402


def _gen_fw_owns():
    """Compile the GENERATED `_fw_owns` out of the skeleton source and return it.

    Executing the shipped text, not a reimplementation — this defect is entirely about what the
    generated function does on a fault."""
    from multi_agent.runtime import backend_skeleton as BK
    src = inspect.getsource(BK)
    i = src.index("def _fw_owns(cls, col, fk_val, user, strict=False):")
    j = src.index("\ndef _fw_fill_required_defaults", i)
    g = {"_fw_uid": lambda u: 1, "_fw_dbg": lambda *a: None,
         "Base": None, "SessionLocal": None}
    exec(compile(src[i:j], "<generated>", "exec"), g)     # noqa: S102 — the shipped source
    return g["_fw_owns"], src[i:j]


class _Boom:
    """Any FK introspection raises — #1158's real-world shape."""
    def __getattr__(self, k):
        raise RuntimeError("introspection fault")


def test_the_read_decision_fails_closed():
    """★ The fix."""
    f, _ = _gen_fw_owns()
    assert f(_Boom(), "profile_id", "44", {"id": 1}, strict=True) is False


def test_the_write_decision_still_fails_open():
    """★ #566s's bargain is untouched: a framework bug must never block a legitimate write."""
    f, _ = _gen_fw_owns()
    assert f(_Boom(), "profile_id", "44", {"id": 1}) is True


def test_an_absent_header_is_still_a_no_op():
    """Nothing to widen, so strict must not turn 'no value' into a denial."""
    f, _ = _gen_fw_owns()
    for empty in (None, ""):
        assert f(_Boom(), "profile_id", empty, {"id": 1}, strict=True) is True


def test_every_fail_open_return_is_conditional_in_strict_mode():
    """★ The whole function, not just the paths a test happens to reach: one unconditional
    `return True` left behind would restore the leak on that branch. Found exactly that way —
    the first pass missed the `if _Sub is None` arm."""
    _, src = _gen_fw_owns()
    body = src.split('"""', 2)[-1]          # skip the docstring
    bare = [ln.strip() for ln in body.splitlines() if ln.strip() == "return True"]
    assert not bare, (
        f"{len(bare)} unconditional fail-open return(s) remain; strict mode must cover all")


def test_the_1190_call_site_asks_strictly():
    """★ Reachability: the parameter is inert unless the header decision uses it."""
    from multi_agent.runtime import backend_skeleton as BK
    src = inspect.getsource(BK)
    m = re.search(r"_act1190 not in \(None, \"\"\) and _fw_owns\(([^)]*)\)", src)
    assert m, "the #1190 header override no longer calls _fw_owns"
    assert "strict=True" in m.group(1), m.group(1)


def test_writes_do_not_silently_become_strict():
    """★ Scope, the other direction: the projector's create-path ownership check must keep
    calling it non-strictly, or a framework introspection bug starts 403ing legitimate writes —
    the regression #1158 documents ("the half fix is WORSE than the bug")."""
    from multi_agent.runtime import route_projector as RP
    src = inspect.getsource(RP)
    for m in re.finditer(r"_fw_owns\(([^)]*)\)", src):
        assert "strict=True" not in m.group(1), (
            "a write-path ownership check must not fail closed: " + m.group(1)[:90])
