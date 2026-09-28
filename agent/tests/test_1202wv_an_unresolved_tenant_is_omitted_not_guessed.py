"""#1202wv: an unresolved `${tenant}` in a chain body must be omitted, like its header.

#1202qb drops an unresolved placeholder from a HEADER because "`${...}` never names anything
real". The identical literal in the BODY was left alone -- and #1202wu established that
`/auth/register` and `/auth/login` read the body FIRST and the `X-Tenant-Id` header second,
so the repair removed the side that loses and kept the side that decides. The delivered r135
records exactly that pairing: `autofilled: ["header-omitted-unresolved:X-Tenant-ID"]` on a
step whose body still read `{"tenant_id": "${tenantA}"}`.

Both landings are visible in the delivered tiktok-web-r126 `tenants` table:
  * the literal survives (a register is usually a chain's first step, so `last_id` is None)
    and `oauth_store.create_user` INSERTs the tenant ON CONFLICT DO NOTHING -- three rows
    named `${tenantA}` / `${tenantId}` / `${tenant_id}`, holding 14 of that app's users;
  * `_resolve_unresolved_dollar_vars` falls through to `return last_id` -- `${tenantA}` ends
    in no `_id`, so no resource candidate matches -- filing the actor under the last row
    created: eight more tenants named `13`, `37`, `39`, `45`, `48`, `49`, `56`, `58`.

MEASURED over all 150 chain hubs: `tenant_id` is the most common body key authored as a bare
placeholder (558 occurrences across 75 runs), and 508 of them -- 91%, across 66 runs -- name
a variable no prior step in that chain saves, so they cannot resolve by construction. Of the
steps that actually EXECUTED, 22 across 3 runs recorded `header-omitted-unresolved` while
carrying the identical unresolved tenant in the body -- the most recent being r135, the
latest delivered run.

Dating the harm honestly: the r126 `tenants` rows are from 2026-09-16. r132 and r135 run
`_is_factory_reset` steps near the end, so their delivered databases hold none of their own
chain writes and cannot say whether the literal still lands there. What is current is the
SEND -- r135 shows it going out -- and that the guess is wrong under any circumstance.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.chain_executor import (  # noqa: E402
    _drop_unresolved_tenancy_1202wv,
    _resolve_unresolved_dollar_vars,
)


def test_an_unresolved_tenant_is_dropped_and_named():
    body, dropped = _drop_unresolved_tenancy_1202wv(
        {"email": "a@b.c", "tenant_id": "${tenantA}"})
    assert body == {"email": "a@b.c"}, body
    assert dropped == ["tenant_id"], dropped


def test_the_bare_brace_form_is_dropped_too():
    """`_resolve_unresolved_dollar_vars` treats a whole-value `{name}` as a ref; so must this."""
    body, dropped = _drop_unresolved_tenancy_1202wv({"tenant_id": "{tenant_id}"})
    assert body == {} and dropped == ["tenant_id"], (body, dropped)


def test_the_spellings_the_corpus_actually_uses():
    for key in ("tenant_id", "tenantId", "TENANT_ID", "tenant"):
        _body, dropped = _drop_unresolved_tenancy_1202wv({key: "${tenantA}"})
        assert dropped == [key], "%s was left in the body" % key


def test_a_resolved_tenant_is_left_alone():
    """★ The whole point is to stop GUESSING, not to stop tenancy working."""
    body, dropped = _drop_unresolved_tenancy_1202wv({"tenant_id": "tenant_a3"})
    assert body == {"tenant_id": "tenant_a3"} and dropped == [], (body, dropped)


def test_a_tenant_that_merely_contains_a_placeholder_is_not_whole():
    """`acme-${rand}` is a NAME being built, not an unresolved reference."""
    body, dropped = _drop_unresolved_tenancy_1202wv({"tenant_id": "acme-${rand}"})
    assert dropped == [], (body, dropped)


def test_other_keys_are_not_this_rule_s_business():
    """#575 owns owner FKs and the generic fallback owns resource ids; don't widen silently."""
    src = {"profile_id": "${profileA}", "video_id": "${vid}", "email": "${e}"}
    body, dropped = _drop_unresolved_tenancy_1202wv(dict(src))
    assert body == src and dropped == [], (body, dropped)


def test_a_non_mapping_body_passes_through():
    for val in (None, "raw", [1, 2]):
        body, dropped = _drop_unresolved_tenancy_1202wv(val)
        assert body == val and dropped == [], (body, dropped)


def test_the_caller_s_body_is_not_mutated():
    src = {"tenant_id": "${tenantA}", "email": "a@b.c"}
    _drop_unresolved_tenancy_1202wv(src)
    assert src == {"tenant_id": "${tenantA}", "email": "a@b.c"}, src


def test_the_guesser_is_what_we_are_protecting_against():
    """★ Pin the behaviour that makes the drop necessary, so a change there is visible here.

    Left to itself the generic fallback turns a tenant into whatever row was created last --
    the eight numeric tenants in r126. If this ever stops being true the drop can be revisited;
    until then it is the reason the drop must run FIRST.
    """
    got = _resolve_unresolved_dollar_vars({"tenant_id": "${tenantA}"}, 58, {})
    assert got == {"tenant_id": 58}, (
        "the fallback no longer files a tenant under a row id: %r" % (got,))


# --- the wiring, structurally: a drop nothing calls is #1202wm's dead mechanism, and a
# --- silent body edit is what #575 and #1202qb both refuse to be.
import ast  # noqa: E402

_CHAIN = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime",
                      "chain_executor.py")


def _execute_chain():
    with open(_CHAIN, encoding="utf-8") as fh:      # #1202eu
        tree = ast.parse(fh.read())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "execute_chain"), None)
    assert fn is not None, "execute_chain not found"
    return fn


def _call_lines(fn, name):
    return [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == name]


def test_the_step_path_calls_the_drop():
    assert _call_lines(_execute_chain(), "_drop_unresolved_tenancy_1202wv"), (
        "the helper exists and nothing in execute_chain calls it")


def test_the_drop_runs_BEFORE_the_guesser():
    """★ After it, the tenant is already a row id and there is nothing left to omit."""
    fn = _execute_chain()
    drop = min(_call_lines(fn, "_drop_unresolved_tenancy_1202wv"))
    guess = min(_call_lines(fn, "_resolve_unresolved_dollar_vars"))
    assert drop < guess, (
        "the drop runs at line %d, after the fallback at line %d" % (drop, guess))


def test_the_drop_is_not_conditional_on_the_denial_carve_out():
    """#575b spares a denial step's owner FK; a tenant has the opposite reason -- see the
    helper's docstring. The call must therefore sit under no `if` at all: the step loop is
    the only thing allowed to enclose it."""
    fn = _execute_chain()
    parent = {}
    for node in ast.walk(fn):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    call = next(n for n in ast.walk(fn)
                if isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "_drop_unresolved_tenancy_1202wv")
    branches = []
    node = call
    while node in parent:
        node = parent[node]
        if isinstance(node, (ast.If, ast.Try)):
            branches.append("%s:%d" % (type(node).__name__, node.lineno))
    assert not branches, (
        "the drop is conditional (%s), so some steps keep the literal" % ", ".join(branches))


def test_the_omission_reaches_the_record():
    """#575/#1202qb convention: never a silent body edit -- say it in `autofilled`."""
    src = ast.unparse(_execute_chain())
    assert "tenant-omitted-unresolved:" in src, (
        "the body was edited and the step record does not say so")
    assert "_dropped_tenancy_1202wv" in src
