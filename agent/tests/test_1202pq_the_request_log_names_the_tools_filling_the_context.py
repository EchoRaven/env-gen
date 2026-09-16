"""#1202pq: the request log names which tools' results fill the context."""
from utils.llm import Message, _prompt_split_1202oc


def _call(cid, name, size):
    return [Message.assistant(tool_calls=[{"id": cid, "type": "function",
                                           "function": {"name": name, "arguments": "{}"}}]),
            Message.tool("x" * size, cid)]


def test_results_are_summed_per_tool_and_ranked():
    msgs = [Message.system("s"), Message.user("u")]
    msgs += _call("a", "read", 5000) + _call("b", "grep", 700) + _call("c", "read", 1000)
    out = _prompt_split_1202oc([], msgs)
    assert out.endswith(" ctx=read:6000|grep:700"), out


def test_no_tool_results_keeps_the_old_format():
    assert _prompt_split_1202oc([], [Message.user("hi")]) == " split=sys:0,tools:0,hist:2"
