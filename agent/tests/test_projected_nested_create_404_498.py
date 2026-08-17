"""#498 (netflix r67, live): a projected nested create under /parents/{id}/children whose
path-derived parent does NOT resolve must return 404 — NOT silently omit the target FK and
let the INSERT NULL-violate.

r67 wedged exactly here: the verifier chain rated ``POST /api/titles/11/rating`` but the seed
had only 6 titles (ids 1-6). ``_parent`` was None, the old template's ``if _parent is not None``
guard simply skipped binding title_id, and the INSERT 400'd
``null value in column "title_id" violates not-null constraint``. That OPAQUE 400 read like a
handler bug, so the verifier re-authored the chain 303× chasing it (business_chain never
converged → 0 releases). A 404 is the honest, correct-REST outcome (a child can't be created
under a non-existent parent), every chain expect-family tolerates 404 (see #124), and remediation
routes to the missing parent (chain/seed) instead of the handler — breaking the churn.

The HAPPY PATH (parent exists) is byte-identical to before: only the parent-missing branch
changed, which previously produced a wedging 400 or an orphan row. Generalizes to every projected
nested create in every app.
"""
import ast

from env_generator.llm_generator.multi_agent.runtime.route_projector import _generate_handler

_MODELS = {
    "titles":   {"cls": "Title",   "cols": ["id", "name"], "fks": {}},
    "ratings":  {"cls": "Rating",  "cols": ["id", "title_id", "profile_id", "value", "created_at"],
                 "fks": {"title_id": "titles", "profile_id": "profiles"}},
    "profiles": {"cls": "Profile", "cols": ["id", "user_id", "name"], "fks": {"user_id": "users"}},
    "users":    {"cls": "User",    "cols": ["id", "email"], "fks": {}},
}


def _nested():
    return _generate_handler("POST", "/api/titles/{title_id}/rating", True, _MODELS, 13)


def test_nested_create_has_404_guard_on_missing_parent():
    src = _nested()
    assert "if _parent is None:" in src, src
    assert 'raise HTTPException(status_code=404, detail="parent resource not found")' in src, src


def test_fk_bound_after_guard_on_happy_path():
    # the target FK is still bound from the resolved parent (happy path unchanged)
    src = _nested()
    assert 'valid["title_id"] = _parent.id' in src, src


def test_old_unconditional_bind_is_gone():
    # the pre-#498 ``if _parent is not None:`` skip-bind pattern must not survive
    assert "if _parent is not None:" not in _nested()


def test_generated_handler_is_valid_python():
    # the 404 raise + the (now-unindented) FK bind must parse cleanly
    ast.parse(_nested())


def test_guard_precedes_the_insert_try():
    src = _nested()
    assert src.index("if _parent is None:") < src.index("try:"), src


def test_non_nested_create_unaffected():
    # a plain (non-nested) create has no parent context → no _parent lookup / 404 guard
    src = _generate_handler("POST", "/api/titles", True, _MODELS, 1)
    assert "_parent" not in src, src
    assert 'detail="parent resource not found"' not in src, src


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
