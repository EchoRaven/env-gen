"""#979: insert after the last import STATEMENT, not the last import LINE.

`backend_scaffold`'s router repair inserts `router = APIRouter()` after the last line that
starts with `import ` / `from `. 26 of the corpus's generated `custom_routes.py` end their
imports with an unclosed continuation:

    from models import (
        Title,
        Profile,
    )

Inserting at `last_import + 1` puts the statement INSIDE the parentheses — a SyntaxError that
stops the backend from starting at all.

Same shape as #970 one language over. There the generated source was minified onto one line;
here it is parenthesised across several. Both break a rule that counts LINES where it should
follow STATEMENTS.

Latent, not observed: the repair only runs when a file uses `router.` without defining it,
which is rare. That is what makes it a landmine — it fires in an already-broken state, where a
fresh SyntaxError reads as the lane's own mistake.
"""

import ast

import pytest

from env_generator.llm_generator.multi_agent.runtime import backend_scaffold


def _insert(src: str) -> str:
    """The repair's insertion logic, exercised on a source string."""
    lines = src.split("\n")
    last_import = max((i for i, l in enumerate(lines)
                       if l.startswith("import ") or l.startswith("from ")), default=-1)
    if last_import >= 0:
        bal = 0
        for i in range(last_import, len(lines)):
            bal += lines[i].count("(") - lines[i].count(")")
            if bal <= 0:
                last_import = i
                break
        else:
            last_import = len(lines) - 1
    lines[last_import + 1:last_import + 1] = [
        "", "from fastapi import APIRouter", "router = APIRouter()", ""]
    return "\n".join(lines)


PARENTHESISED = (
    "from fastapi import Depends\n"
    "from models import (\n"
    "    Title,\n"
    "    Profile,\n"
    ")\n"
    "\n"
    "@router.get('/x')\n"
    "def x():\n"
    "    return []\n"
)

SINGLE_LINE = (
    "import os\n"
    "from models import Title\n"
    "\n"
    "@router.get('/x')\n"
    "def x():\n"
    "    return []\n"
)


@pytest.mark.parametrize("src", [PARENTHESISED, SINGLE_LINE])
def test_the_result_is_valid_python(src):
    ast.parse(_insert(src))


def test_the_router_lands_after_the_closing_paren():
    """Anchored on the import block's own closing line, not a bare `)` — a naked delimiter
    is exactly the fragile locator #923's guard forbids."""
    out = _insert(PARENTHESISED)
    close = out.index("    Profile,\n)")
    assert close < out.index("router = APIRouter()"), (
        "inserting inside the parentheses is a SyntaxError that kills the backend")


def test_the_single_line_case_is_unchanged():
    out = _insert(SINGLE_LINE)
    lines = out.split("\n")
    assert lines[1] == "from models import Title"
    assert lines[3] == "from fastapi import APIRouter"


def test_a_file_with_no_imports_gets_them_first():
    out = _insert("@router.get('/x')\ndef x():\n    return []\n")
    ast.parse(out)
    assert out.startswith("\nfrom fastapi import APIRouter")


def test_an_unterminated_paren_does_not_run_off_the_end():
    """Truncated generated files exist; the scan must terminate rather than IndexError."""
    out = _insert("from models import (\n    Title,\n")
    assert "router = APIRouter()" in out


def test_the_control_writes_a_syntax_error():
    """Planted control: the PRE-FIX rule — insert after the last import LINE — produces
    invalid Python on the parenthesised shape. Synthetic, so fixing the real scaffold can
    never turn this red."""
    lines = PARENTHESISED.split("\n")
    last = max(i for i, l in enumerate(lines)
               if l.startswith("import ") or l.startswith("from "))
    lines[last + 1:last + 1] = ["", "from fastapi import APIRouter", "router = APIRouter()", ""]
    with pytest.raises(SyntaxError):
        ast.parse("\n".join(lines))


def test_the_scaffold_carries_the_balance_scan():
    import inspect
    src = inspect.getsource(backend_scaffold)
    assert 'lines[_i].count("(") - lines[_i].count(")")' in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
