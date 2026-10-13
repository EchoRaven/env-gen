r"""#582: the LLM retry log printed a bare exception as ``[AssertionError] `` and nothing else.

Mined offline from 107 run logs: **2313** three-attempt failure groups of exactly that shape —
`[LLM] All 3 attempts failed. Last error: [AssertionError] ` — with an EMPTY message. The trigger
sequence is visible in the log (the model rejects `temperature`, the client drops it and
retries, and the retry dies on the streaming path), but the type alone says neither what
asserted nor where, and `agent/utils/llm.py` contains no `assert` — so these originate in the
SDK/transport and only the frame identifies them.

`error_msg = str(e)[:200]` yields `""` for `AssertionError()`, so every one of those retries
taught the caller nothing. This attaches the innermost frame so ONE failure names its own cause.
Log-only: the retry/abort decisions are untouched.
"""
import pytest

from utils.llm import _blank_error_origin as origin


def _raise_bare_assert():
    x = 0
    assert x                       # noqa: S101 — the shape under test


def test_a_bare_assert_now_names_its_frame():
    try:
        _raise_bare_assert()
    except AssertionError as e:
        got = origin(e)
    assert got.startswith("(no message) at "), got
    assert "test_blank_error_origin_582.py:" in got, got
    assert "_raise_bare_assert" in got, got
    assert "assert x" in got, got


def test_an_exception_with_no_traceback_degrades_cleanly():
    assert origin(AssertionError()) == "(no message)"


def test_it_never_raises_on_a_hostile_input():
    class Weird(BaseException):
        @property
        def __traceback__(self):            # pragma: no cover - exercised via origin()
            raise RuntimeError("boom")
    try:
        w = Weird()
    except Exception:                        # pragma: no cover
        pytest.skip("cannot construct")
    assert origin(w) == "(no message)"
    assert origin(None) == "(no message)"


def test_the_source_line_is_bounded():
    try:
        exec("def f():\n    assert " + "0 or " * 60 + "0\nf()", {})
    except AssertionError as e:
        got = origin(e)
    assert len(got) < 300, len(got)


def test_only_an_EMPTY_message_is_replaced():
    """A normal exception keeps its own message — the call site guards on `.strip()`.

    Ordered by AST line number, not by `str.index` on a source literal. The literal version
    pinned `error_msg = str(e)[:200]`, so #1203im replacing that cut with
    `_error_msg_1203im(e)` raised ValueError ("substring not found") although the property —
    assign, then guard on `.strip()`, then substitute — was untouched. What matters is the
    ORDER of the three statements, so assert that directly.
    """
    import ast
    import inspect
    from utils import llm
    src = inspect.getsource(llm)
    tree = ast.parse(src)

    assigns, guards, calls = [], [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "error_msg" for t in node.targets):
            seg = ast.get_source_segment(src, node.value) or ""
            (calls if "_blank_error_origin" in seg else assigns).append(node.lineno)
        if isinstance(node, ast.If):
            if "not error_msg.strip()" in (ast.get_source_segment(src, node.test) or ""):
                guards.append(node.lineno)

    assert assigns, "error_msg is never given the exception's own message"
    assert guards, "the empty-message guard on error_msg.strip() is gone"
    assert calls, "_blank_error_origin is no longer the substitute"
    first_assign, guard, call = min(assigns), min(guards), min(calls)
    assert first_assign < guard < call, (first_assign, guard, call)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
