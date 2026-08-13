r"""#635: `lint` refused to answer in every single run.

Sweeping the 56 run logs by error class, this is the most universal entry in the corpus:

    lint FAILED (Nms): ruff is not available; install ruff to lint Python files.
    125 occurrences — in 50 of 50 runs

Advice the agent cannot act on, in an environment where ruff is not installed. Every run, every
time, a turn spent learning nothing about the file.

`ast.parse` needs no dependency and answers what the caller actually asked — *is this file
valid?* — and a syntax error is precisely the failure that matters in this pipeline: the same
corpus carries 157 `write FAILED: your proposed edit has introduced syntax…` and P0s like
"Frontend build fails — syntax error in GenreCategoryPage.jsx:35".

The fallback is honest about its scope, so a green verdict is never mistaken for a full lint.
"""
import pytest

from env_generator.llm_generator.tools.code_tools import LintTool


@pytest.fixture()
def tool():
    t = LintTool.__new__(LintTool)
    t._tool_cache = {"ruff": False}          # ruff absent, as in every measured run
    return t


def _py(tmp_path, text, name="m.py"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# --- it answers instead of refusing ---------------------------------------------------------------

def test_valid_python_now_passes(tmp_path, tool):
    res = tool._lint_python(_py(tmp_path, "x = 1\ndef f():\n    return x\n"))
    assert res.success is True


def test_a_syntax_error_is_reported_with_its_line(tmp_path, tool):
    res = tool._lint_python(_py(tmp_path, "def f(:\n    pass\n"))
    assert res.success is False
    assert res.data["errors"][0]["line"] == 1
    assert "SyntaxError" in res.error_message


def test_the_error_shape_matches_the_ruff_path(tmp_path, tool):
    """Callers already parse data['errors'] from the ruff branch."""
    res = tool._lint_python(_py(tmp_path, "x = (\n"))
    err = res.data["errors"][0]
    assert set(err) == {"line", "column", "code", "msg", "fix"}


def test_the_unactionable_instruction_is_gone(tmp_path, tool):
    """The old text was `install ruff to lint Python files` — an action unavailable to the
    agent. The only surviving mention must be the one telling it NOT to."""
    res = tool._lint_python(_py(tmp_path, "x = 1\n"))
    blob = str(res.data) + str(res.error_message or "")
    assert "install ruff to lint" not in blob
    assert blob.count("install ruff") == 1 and "do not try to install ruff" in blob


# --- honesty about scope ---------------------------------------------------------------------------

def test_a_pass_says_style_rules_did_not_run(tmp_path, tool):
    res = tool._lint_python(_py(tmp_path, "import os\nx=1\n"))
    assert "STYLE rules were not run" in res.data["message"]


def test_a_failure_says_so_too(tmp_path, tool):
    res = tool._lint_python(_py(tmp_path, "def f(:\n"))
    assert "syntax checked only" in res.error_message


def test_it_tells_the_agent_not_to_chase_the_install(tmp_path, tool):
    """The old message sent agents after a dependency they cannot add."""
    res = tool._lint_python(_py(tmp_path, "x = 1\n"))
    assert "do not try to install ruff" in res.data["message"]


def test_the_tool_field_says_which_check_ran(tmp_path, tool):
    assert tool._lint_python(_py(tmp_path, "x = 1\n")).data["tool"] == "syntax"


# --- it must not break -----------------------------------------------------------------------------

def test_an_unreadable_file_fails_cleanly(tmp_path, tool):
    res = tool._lint_python(tmp_path / "does-not-exist.py")
    assert res.success is False and "could not read" in res.error_message


def test_an_empty_file_is_valid(tmp_path, tool):
    assert tool._lint_python(_py(tmp_path, "")).success is True


def test_undefined_names_are_not_flagged(tmp_path, tool):
    """A syntax check is not a linter — it must not invent findings it cannot support."""
    assert tool._lint_python(_py(tmp_path, "print(undefined_name)\n")).success is True


def test_ruff_is_still_preferred_when_present(tmp_path):
    """The fallback must never displace a real lint."""
    import inspect
    src = inspect.getsource(LintTool._lint_python)
    assert "if not self._check_tool_available('ruff')" in src
    assert src.index("_check_tool_available") < src.index("_syntax_check_python_635")


def test_the_measurement_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(LintTool._syntax_check_python_635).split())
    assert "125 times in 50 of 50 runs" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
