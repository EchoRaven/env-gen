"""#411 (netflix r7/r8, live): business_chain create steps wedged on required NO-DEFAULT
columns the verifier's chain never sent because the endpoint's request schema didn't declare
them — r8: POST /api/my-list -> 400 null title_id (persisted to attempt 6, lane-unfixable: the
CHAIN, not the handler, must send title_id). Two-part fix: (a) the IntegrityError handler now
SURFACES the column for a NOT-NULL (23502) violation — legitimate required-field feedback, unlike
the FK/unique cases #282 keeps generic; (b) the chain-executor's missing-field auto-repair now
parses "null value in column X" (in addition to 422) and fills an _id column with an INTEGER
(a seeded parent is id 1), then retries. SKIPs DB-defaulted/system cols (id/created_at/updated_at/
*_at) whose fix is the handler OMITTING them (#407/#409), not the chain sending a literal.
"""
import importlib
import pathlib
import sys
import types

_RT = pathlib.Path(__file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/runtime")


def _load_chain_executor():
    """Isolation-load chain_executor: stub its only sibling import
    (validation_runner._http / _form_retry_warranted), exec the source under a
    synthetic package (importing by package path pulls the whole engine graph)."""
    pkg = "ce_pkg411"
    if pkg not in sys.modules:
        m = types.ModuleType(pkg)
        m.__path__ = []
        sys.modules[pkg] = m
        vr = types.ModuleType(pkg + ".validation_runner")
        vr._http = lambda *a, **k: {"status": 0, "body_text": ""}
        vr._form_retry_warranted = lambda *a, **k: False
        sys.modules[pkg + ".validation_runner"] = vr
    src = (_RT / "chain_executor.py").read_text(encoding="utf-8")
    mod = types.ModuleType(pkg + ".chain_executor")
    mod.__package__ = pkg
    sys.modules[pkg + ".chain_executor"] = mod
    exec(compile(src, str(_RT / "chain_executor.py"), "exec"), mod.__dict__)
    return mod


_CE = _load_chain_executor()


def test_notnull_column_recovered_from_400():
    body = '{"detail": "null value in column \\"title_id\\" violates not-null constraint"}'
    b, q = _CE._missing_required_fields(body, "POST")
    assert "title_id" in b, (b, q)


def test_system_and_defaulted_cols_skipped():
    # created_at (#407/#409 DDL default) + id + any *_at must NOT be chain-filled
    for col in ("created_at", "updated_at", "id", "expires_at"):
        body = 'null value in column "%s" violates not-null constraint' % col
        b, _ = _CE._missing_required_fields(body, "POST")
        assert col not in b, (col, b)


def test_notnull_recovery_write_methods_only():
    body = 'null value in column "title_id" violates not-null'
    assert "title_id" in _CE._missing_required_fields(body, "POST")[0]
    assert "title_id" not in _CE._missing_required_fields(body, "GET")[0]


def test_422_recovery_still_works():
    # the existing Pydantic-422 path must be untouched (additive change)
    body = '{"detail":[{"type":"missing","loc":["body","content"]}]}'
    b, _ = _CE._missing_required_fields(body, "POST")
    assert "content" in b, b


def test_fk_fill_is_integer_not_string():
    # the repair fills an _id column with int 1 (a string would re-fail FK/type)
    src = (_RT / "chain_executor.py").read_text(encoding="utf-8")
    assert 'if f.endswith("_id") else _filler' in src


def test_handler_surfaces_notnull_column():
    # backend_scaffold: the 23502 branch exposes the column (enables (b) to recover)
    src = (_RT / "backend_scaffold.py").read_text(encoding="utf-8")
    assert 'code == "23502"' in src
    assert 'null value in column "%s" violates not-null constraint' in src


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
