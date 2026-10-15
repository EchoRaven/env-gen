r"""#1203me: the conflict path named a `user` the handler's signature never bound.

`_generate_handler` adds `user=Depends(get_current_user)` under `if auth:`. #566u's
upsert-on-conflict line hardcoded `user` as an argument regardless, so on a PUBLIC write the
`except IntegrityError:` body raised NameError instead of recovering — and a NameError inside
an except clause is NOT caught by the sibling `except Exception` of the same try, so it
reaches FastAPI as a 500. That is the outcome #93 wrote the branch to prevent: its own
comment says the catch-all's 500 "BYPASSED the global IntegrityError handler → reachability
wedged", and the intended mapping (FK 23503→404, unique 23505→409, NotNull→400) never ran.

MEASURED with scripts/undefined_names.py over every delivered backend: r156, r160 and r166
each ship a projected handler whose conflict path names a `user` its signature does not bind.
Once star imports are resolved, `user` is the only such name left in the modern era.

None rather than a disabled branch: the helper reads `valid.get(owner_fk)` first and only
falls back to `_fw_owner_val(cls, owner_fk, user)`, so a public write whose body names the
owner still upserts; with None that fallback yields None (`_fw_uid(None)` → None), the owner
filter matches nothing, the helper returns None and the caller re-raises — the 409 the
contract wanted.
"""
from __future__ import annotations

import ast
import textwrap

import pytest

from env_generator.llm_generator.multi_agent.runtime.route_projector import _generate_handler


def _meta(cls, cols, fks):
    return {"cls": cls, "cols": cols, "fks": fks}


MODELS = {
    # owner FK + one subject FK = the natural key #566u upserts on
    "ratings": _meta("Rating", ["id", "user_id", "title_id", "value"],
                     {"user_id": "users", "title_id": "titles"}),
    "users": _meta("User", ["id", "email"], {}),
    "titles": _meta("Title", ["id", "name"], {}),
}


def _emit(auth):
    out = _generate_handler("POST", "/api/ratings", auth, MODELS, 0)
    if isinstance(out, str):
        return out
    return "\n".join(map(str, out))


def _fn_node(src):
    tree = ast.parse(textwrap.dedent(src))
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    assert fns, "no handler was projected"
    return fns[-1]


def _params(fn):
    a = fn.args
    names = {x.arg for grp in (a.posonlyargs, a.args, a.kwonlyargs) for x in grp}
    for x in (a.vararg, a.kwarg):
        if x:
            names.add(x.arg)
    return names


@pytest.mark.parametrize("auth", [True, False])
def test_the_handler_never_names_a_user_it_did_not_take(auth):
    """★ THE INVARIANT, both ways round. This is the property, not the spelling."""
    src = _emit(auth)
    fn = _fn_node(src)
    params = _params(fn)
    loaded = {n.id for n in ast.walk(fn)
              if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    if "user" in loaded:
        assert "user" in params, (
            "the projected handler reads `user` but its signature does not bind it")


def test_an_authenticated_write_still_scopes_the_upsert_by_the_caller():
    src = _emit(True)
    assert "user=Depends(get_current_user)" in src
    line = [l for l in src.split("\n") if "_fw_upsert_on_conflict" in l]
    assert line and ", valid, user," in line[0], line


def test_a_public_write_passes_none_rather_than_a_name():
    src = _emit(False)
    assert "user=Depends(get_current_user)" not in src
    line = [l for l in src.split("\n") if "_fw_upsert_on_conflict" in l]
    assert line, "the upsert branch disappeared; a body-owned public write can no longer recover"
    assert ", valid, None," in line[0], line


def test_the_branch_is_still_projected_at_all():
    """#566u must not be silently dropped for public writes — that was the other way to
    'fix' this, and it loses the recovery for a body that names its own owner."""
    for auth in (True, False):
        assert "_fw_upsert_on_conflict" in _emit(auth)


def test_the_conflict_path_still_reraises_after_the_attempt():
    """The 409/404/400 mapping depends on the re-raise surviving."""
    src = _emit(False)
    i = src.index("except IntegrityError:")
    j = src.index("except DataError:", i)
    block = src[i:j]
    assert "_fw_upsert_on_conflict" in block and "raise" in block.split("\n")[-3:][0] or "raise" in block
