r"""#1203mg: the action stub carried unreachable code, referencing a name never bound.

When `_action_unmapped` fires, the projector REPLACES `body_lines` with a single
`raise HTTPException(404, "action endpoint not implemented by the projection …")`. The two
POST blocks after it kept appending, so the projected handler ended with unreachable
statements — among them `valid.setdefault("user_id", …)`, where `valid` is never bound. The
create/commit footer was already guarded by `if not _action_unmapped:`; these two were not,
and #124's guard only ever read `body_lines[0]`.

MEASURED: scripts/undefined_names.py reports `valid` 72 times across the delivered backends,
every one in an action-stub handler — and since the first block is gated on `auth`, every hit
sits in a handler with `user=Depends(...)`. The statements are unreachable so nothing ever
crashed; the costs were a latent trap (the day that raise becomes conditional, `valid` is live
and unbound) and 72 of the 203 candidates in the delivered scan, burying the signal that
found #1203md and #1203me.
"""
from __future__ import annotations

import ast
import textwrap

import pytest

from env_generator.llm_generator.multi_agent.runtime.route_projector import _generate_handler


def _meta(cls, cols, fks):
    return {"cls": cls, "cols": cols, "fks": fks}


MODELS = {
    "posts": _meta("Post", ["id", "user_id", "body"], {"user_id": "users"}),
    "users": _meta("User", ["id", "email"], {}),
    "post_likes": _meta("PostLike", ["id", "post_id", "user_id"],
                        {"post_id": "posts", "user_id": "users"}),
}

STUB = "/api/posts/{id}/repost"       # a POST action the projection does not implement


def _fn(path, auth=True, method="POST"):
    out = _generate_handler(method, path, auth, MODELS, 0)
    src = out if isinstance(out, str) else "\n".join(map(str, out))
    tree = ast.parse(textwrap.dedent(src))
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    return src, fns[-1]


def _after_top_level_raise(fn):
    for i, st in enumerate(fn.body):
        if isinstance(st, ast.Raise):
            return fn.body[i + 1:]
    return []


@pytest.mark.parametrize("auth", [True, False])
def test_the_action_stub_ends_at_its_raise(auth):
    """★ The invariant: an unconditional raise is the end of the body."""
    src, fn = _fn(STUB, auth=auth)
    assert "action endpoint not implemented" in src, "the stub shape stopped being projected"
    dead = _after_top_level_raise(fn)
    assert dead == [], "unreachable statements after the stub raise: %s" % (
        [ast.unparse(d)[:60] for d in dead])


def test_the_stub_references_no_unbound_name():
    """The concrete harm the invariant removes: `valid` was read where nothing binds it."""
    src, fn = _fn(STUB)
    params = {a.arg for grp in (fn.args.posonlyargs, fn.args.args, fn.args.kwonlyargs)
              for a in grp}
    assigned = {n.id for n in ast.walk(fn)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    loaded = {n.id for n in ast.walk(fn)
              if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    assert "valid" not in (loaded - params - assigned)


def test_a_normal_create_still_gets_its_whole_body():
    """The regression direction: gating must not strip a real POST."""
    src, fn = _fn("/api/posts")
    assert "action endpoint not implemented" not in src
    assert "_fw_fill_required_defaults" in src, "the #566t defaults step disappeared"
    assert "db.add(obj)" in src and "db.commit()" in src, "the create footer disappeared"
    assert _after_top_level_raise(fn) == []


def test_an_authenticated_create_still_gets_the_owner_guard():
    """The first gated block is `if m == POST and auth` — #566s/#577 must survive it."""
    src, _fn_ = _fn("/api/posts", auth=True)
    assert "_fw_owner_val" in src or "_fw_owns" in src, \
        "the cross-user create guard was gated away with the stub"


def test_an_unauthenticated_create_is_unchanged_too():
    src, fn = _fn("/api/posts", auth=False)
    assert "_fw_fill_required_defaults" in src and _after_top_level_raise(fn) == []
