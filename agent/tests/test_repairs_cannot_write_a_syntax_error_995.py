"""#995: a framework repair may not leave a generated file worse than it found it.

46 functions in runtime/ write generated CODE; six validated it first. #979 was one of the
other forty — it spliced `router = APIRouter()` after the last import LINE, which for the 26
corpus files ending in `from models import (` landed inside the parentheses. A SyntaxError,
and the backend does not boot. #979 fixed that splice; the CLASS survived it, one edit away in
every other unguarded repair, and it fires in an already-broken state where the fresh error
reads as the lane's own mistake.

The invariant is narrow and cheap: these repairs MODIFY an existing valid module, so if it
parsed before it must parse after.

The first attempt at this shipped a disaster and was reverted (item 401): the helper was placed
by string position inside `backend_scaffold.py`, which is dense with triple-quoted templates,
and landed in `_AUTH_DEPENDENCY_PY` — it would have been written into every generated app. It
now lives in a module with no templates, placement is AST-located, and the rewrite verifies
every template constant is byte-identical afterwards.
"""

import ast
import hashlib
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import backend_scaffold as bs
from env_generator.llm_generator.multi_agent.runtime.safe_code_write import (
    write_py_if_still_parses)

GOOD = "import os\n\n\ndef f():\n    return os.getcwd()\n"
BROKEN = "import os\n\n\ndef f(:\n    return 1\n"


def test_a_valid_repair_is_written(tmp_path):
    f = tmp_path / "m.py"
    f.write_text(GOOD, encoding="utf-8")
    assert write_py_if_still_parses(f, GOOD.replace("getcwd", "getpid")) is True
    assert "getpid" in f.read_text()


def test_a_repair_that_breaks_the_file_is_refused(tmp_path):
    f = tmp_path / "m.py"
    f.write_text(GOOD, encoding="utf-8")
    assert write_py_if_still_parses(f, BROKEN, what="unit-test") is False
    assert f.read_text() == GOOD, "the file must keep the content it had"


def test_an_already_broken_file_is_not_locked(tmp_path):
    """A repair whose whole job is fixing broken syntax must not be blocked."""
    f = tmp_path / "m.py"
    f.write_text(BROKEN, encoding="utf-8")
    assert write_py_if_still_parses(f, GOOD) is True
    assert f.read_text() == GOOD


def test_a_new_file_is_written_when_valid(tmp_path):
    f = tmp_path / "new.py"
    assert write_py_if_still_parses(f, GOOD) is True
    assert f.exists()


def test_a_new_file_that_would_not_parse_is_refused(tmp_path):
    f = tmp_path / "new.py"
    assert write_py_if_still_parses(f, BROKEN) is False
    assert not f.exists()


def test_non_python_is_written_unchecked(tmp_path):
    """No cheap JSX parser exists here, and a guard that pretends to check is worse than one
    that says it does not."""
    f = tmp_path / "App.jsx"
    assert write_py_if_still_parses(f, "const x = (") is True
    assert f.exists()


def test_every_read_then_write_repair_uses_the_guard():
    """Half a class closed is a class that comes back."""
    tree = ast.parse(inspect.getsource(bs))
    targets = {
        "repair_backend_auth_dependency", "repair_custom_routes_router_prologue",
        "repair_auth_import_paths", "repair_inline_token_auth",
        "repair_auth_enforcement_middleware", "repair_integrity_error_handler",
        "repair_custom_routes_db_handle", "repair_jwt_decode_audience",
        "repair_custom_routes_param_types_vs_projection", "repair_custom_routes_param_types",
    }
    bare = [(fn.name, n.lineno)
            for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef) and fn.name in targets
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "write_text"]
    assert bare == [], f"unguarded write_text in a repair: {bare}"


def test_the_979_repair_is_guarded():
    """The one that actually shipped a SyntaxError."""
    assert "_write_py_995(" in inspect.getsource(bs.repair_custom_routes_router_prologue)


def test_no_helper_leaked_into_a_generated_template():
    """Item 401's disaster, pinned. The first attempt put the helper inside
    _AUTH_DEPENDENCY_PY, where it would have shipped into every generated app."""
    leaked = [n for n in dir(bs)
              if isinstance(getattr(bs, n), str) and len(getattr(bs, n)) > 200
              and ("write_py_if_still_parses" in getattr(bs, n) or "_write_py_995" in getattr(bs, n))]
    assert leaked == [], f"the guard leaked into generated code: {leaked}"


def test_the_templates_still_parse_as_python():
    """A template that stops parsing is how item 401 was detected — 10 suite failures later.
    Check it directly instead."""
    for name in dir(bs):
        v = getattr(bs, name)
        if not (isinstance(v, str) and len(v) > 200 and name.endswith("_PY")):
            continue
        ast.parse(v)


def test_the_control_writes_the_broken_file(tmp_path):
    """Planted control: a plain write_text accepts anything, which is how #979 reached disk."""
    f = tmp_path / "m.py"
    f.write_text(BROKEN, encoding="utf-8")
    with pytest.raises(SyntaxError):
        ast.parse(f.read_text())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
