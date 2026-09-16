"""#1202oc: one call's request and response share an id, and the request says what the prompt is made of.

tiktok-r126 paid $240 of its $293 for INPUT — 249M prompt tokens over 4437 calls (56k each) for
1.6M tokens of output; even the 92% that hit the cache cost $126. Which part of those 56k is
system prompt, tool schemas or accumulated history decides which fix is worth building, and the
log could not say: five lanes run concurrently, so a [LLM Request] line could not be matched to
the [LLM Response] carrying `prompt_tokens`. Two estimates off the same ab2 log disagreed by 30k
tokens per call (one said history dominates, the other that a ~38k baseline does).
"""
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import llm as L  # noqa: E402

TOOLS = [{"type": "function", "function": {"name": "read", "description": "R" * 300}}]


def _split(text):
    return dict(kv.split(":") for kv in text.split("split=")[1].split()[0].split(","))


def test_the_split_names_system_tools_and_history_separately():
    msgs = [{"role": "system", "content": "S" * 1000},
            {"role": "user", "content": "U" * 50},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "1", "function": {"name": "read", "arguments": "{}"}}]},
            {"role": "tool", "content": "T" * 4000}]
    got = _split(L._prompt_split_1202oc(TOOLS, msgs))
    assert int(got["sys"]) == 1000
    assert int(got["tools"]) == len(json.dumps(TOOLS))
    assert int(got["hist"]) > 4050 and int(got["hist"]) < 4200   # 50 + 4000 + the tool_calls json


def test_history_is_not_charged_to_the_system_prompt():
    a = _split(L._prompt_split_1202oc(None, [{"role": "system", "content": "S" * 10}]))
    b = _split(L._prompt_split_1202oc(None, [{"role": "system", "content": "S" * 10},
                                             {"role": "system", "content": "X" * 900}]))
    assert int(a["sys"]) == int(b["sys"]) == 10     # only the FIRST message is the system prompt
    assert int(b["hist"]) == 900 and int(a["tools"]) == 0


def test_ids_are_unique_and_never_raise():
    ids = {L._call_id_1202oc() for _ in range(50)}
    assert len(ids) == 50
    assert L._prompt_split_1202oc(object(), object()) == ""   # best effort: a bad input logs nothing


def test_both_log_lines_carry_the_same_call_id():
    src = Path(ROOT / "utils" / "llm.py").read_text()
    tree = ast.parse(src)
    fns = [n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "chat"]
    paired = 0
    for fn in fns:
        body = ast.get_source_segment(src, fn) or ""
        code = [ln for ln in body.splitlines() if not ln.strip().startswith("#")]
        req = [ln for ln in code if "[LLM Request]" in ln]
        resp = [ln for ln in code if "[LLM Response]" in ln]
        if not req or not resp:
            continue
        paired += 1
        assert all("call={_cid_1202oc}" in ln for ln in req), fn.name
        assert all("call={_cid_1202oc}" in ln for ln in resp), fn.name
        assert "_prompt_split_1202oc" in body, fn.name   # on the request's continuation line
        assert "_cid_1202oc = _call_id_1202oc()" in body
    assert paired == 2, paired
