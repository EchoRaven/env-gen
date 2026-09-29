r"""#1202z9: the prompt split says when its characters are not text.

`_prompt_split_1202oc` reports `sys`/`tools`/`hist` in CHARACTERS, and its docstring
promises the split "makes the answer arithmetic instead of inference". That holds only while
characters and tokens track each other. A base64 image breaks it by two orders of magnitude.

MEASURED on r140, pairing every `[LLM Request]` with its `[LLM Response]` on `call=`:

    chars/token   p10 3.2   median 3.5   p90 4.0   max 2546
    calls above 20 chars/token: 240 of 6807 (3.5%)
      their share of ALL CHARS : 51.4%
      their share of ALL TOKENS:  4.7%

So attributing cost by character share hands half the weight to calls worth a twentieth of
it. I did exactly that reading this line, and the figure it produced — "tool results are 19%
of uncached" — had to be withdrawn (#1202z8).

★ A COUNT, NOT A CORRECTION. The existing numbers are untouched and no ratio is computed
here: the paired Response line already answers that exactly, and a second answer would be a
second thing to keep in sync (#1032). The flag exists so nobody divides `hist` by 3.5 on a
call carrying an image.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from utils.llm import _prompt_split_1202oc as split  # noqa: E402


def _text(s):
    return {"role": "user", "content": s}


def _with_image(n=1):
    parts = [{"type": "text", "text": "look"}]
    parts += [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}] * n
    return {"role": "user", "content": parts}


def test_a_text_only_prompt_carries_no_flag():
    """The common case must read exactly as before — 6567 of r140's 6807 calls."""
    out = split(None, [{"role": "system", "content": "sys"}, _text("hello")])
    assert "split=sys:" in out
    assert "nontext:" not in out, out


def test_one_image_is_counted():
    out = split(None, [{"role": "system", "content": "sys"}, _with_image()])
    assert ",nontext:1" in out, out


def test_several_images_across_messages_are_counted():
    out = split(None, [_with_image(2), _text("x"), _with_image(3)])
    assert ",nontext:5" in out, out


def test_the_char_counts_are_unchanged_by_the_flag():
    """★ Additive only: the numbers a reader already relies on must not move."""
    import re
    msgs = [{"role": "system", "content": "sysprompt"}, _with_image()]
    out = split(None, msgs)
    m = re.search(r"split=sys:(\d+),tools:(\d+),hist:(\d+)", out)
    assert m, out
    plain = split(None, msgs)
    m2 = re.search(r"split=sys:(\d+),tools:(\d+),hist:(\d+)", plain)
    assert m.groups() == m2.groups()
    assert int(m.group(1)) == len("sysprompt")


def test_a_text_part_list_is_not_non_text():
    """A content LIST is how multi-part prompts arrive; only a part whose declared type is
    not `text` is payload the ratio cannot survive."""
    msgs = [{"role": "user", "content": [{"type": "text", "text": "a"},
                                         {"type": "text", "text": "b"}]}]
    assert "nontext:" not in split(None, msgs)


def test_an_unparseable_message_does_not_break_the_split():
    """This decorates every LLM request line; a formatting slip must never be able to break
    a call — the same rule the function it joins already follows."""
    class _Weird:
        content = object()
    out = split(None, [_Weird()])
    assert "split=sys:" in out, out


def test_no_ratio_is_computed_here():
    """★ #1032: the paired Response line carries `prompt_tokens`, which is the exact answer.
    A chars-per-token computed here would be a second, approximate one to keep in sync."""
    import ast
    import inspect
    import utils.llm as LL
    src = inspect.getsource(LL._nontext_parts_1202z9)
    tree = ast.parse(src.lstrip())
    for node in ast.walk(tree):
        assert not isinstance(node, ast.Div), "a ratio is being computed in the flag"
    assert "token" not in src.split('"""')[2].lower(), "the body must not reason about tokens"
