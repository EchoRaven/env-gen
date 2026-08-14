r"""#725: the dispatch log dropped exactly the arguments worth asking about.

`_log_tool_call` builds up to three `name=value` pairs and then stops. Its filter was:

    elif not isinstance(_v, (str, int, float, bool)):
        continue

so every dict and list argument was skipped in silence. That is not a small gap: both times this
session I asked "what did the lane actually send?", the value was a dict —

    registryhub_register_endpoint(schema={...})   item 32's contract mismatch
    register_seed_data(sample_excerpt=[...])      item 33

— and both were invisible, leaving only the tool NAME in prose. I then counted those names and
read mention counts as call counts, twice, which is item 36's own catalogued trap.

It also corrects item 47, written one commit earlier, which concluded "tool arguments are
recorded nowhere". Scalar arguments ARE recorded, up to three. What was recorded nowhere is the
structured ones. The sweep behind item 47 was right about the artifacts and wrong about the
cause, because I read the absence in the log without reading the code that writes it.

The fix is a compact repr under the same 120-char cap the scalar branch already uses, so a large
dict costs one line rather than a dump.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime import tooling


def _block() -> str:
    """The #725 branch only — anchored on its own trailing `continue`, not on later code."""
    src = inspect.getsource(tooling)
    i = src.index("#725: SUMMARISE a structured argument instead of dropping it")
    j = src.index("_t.append(f\"{_k}={truncate(str(_v), 120)}\")", i)
    return src[i:j]


# --- the value is summarised rather than dropped ------------------------------------------------

def test_a_structured_value_is_appended_as_a_SHAPE():
    b = _block()
    assert '_t.append(f"{_k}={truncate(_sh, 120)}")' in b
    assert "def _shape725" in b


def test_it_uses_the_same_cap_as_the_scalar_branch():
    # The scalar append sits AFTER this branch, not before it — the filter runs first.
    src = inspect.getsource(tooling)
    i = src.index("#725: SUMMARISE")
    assert 'truncate(str(_v), 120)' in src[i:], "the scalar branch's cap moved — match it"
    assert "truncate(_sh, 120)" in _block()


def test_it_still_continues_afterwards():
    """The branch must not fall through into the scalar formatting."""
    b = _block()
    assert b.rstrip().endswith("continue"), "must not fall through into the scalar formatting"


def test_a_repr_failure_cannot_break_dispatch():
    b = _block()
    assert "try:" in b and "except Exception:" in b


def test_the_three_argument_cap_is_untouched():
    src = inspect.getsource(tooling)
    assert "if len(_t) >= 3:" in src


# --- it would have answered the two questions -------------------------------------------------------

def _shape(v, depth=0):
    """Mirror of the production shaper, exercised on the cases that motivated it."""
    if isinstance(v, dict):
        if depth >= 1:
            return "{…}" if v else "{}"
        return "{" + ",".join(
            f"{k}:{_shape(x, depth + 1)}" if isinstance(x, (dict, list, tuple)) else str(k)
            for k, x in list(v.items())[:8]) + "}"
    if isinstance(v, (list, tuple)):
        return f"[{len(v)}]"
    return ""


def test_a_schema_dict_shows_its_keys_and_no_values():
    schema = {"request": {"kind": "string?", "genre": "string?"}, "response_key": "items"}
    out = _shape(schema)
    assert "request" in out and "response_key" in out
    assert "string?" not in out and "items" not in out, "values must never appear"


def test_a_deep_structure_is_not_dumped():
    """#611's discipline: test_a_non_scalar_value_is_skipped_not_dumped guards this."""
    out = _shape({"path": {"deep": ["structure"] * 50}})
    assert "structure" not in out


def test_a_list_becomes_its_length():
    assert _shape({"sample_excerpt": [1, 2, 3]}) == "{sample_excerpt:[3]}"


def test_nesting_stops_at_one_level():
    assert _shape({"a": {"b": {"c": 1}}}) == "{a:{…}}"


def test_an_oversized_dict_is_bounded_before_truncation_is_needed():
    """The 8-key cap does the work; truncate(…, 120) is the belt to its braces."""
    big = {f"k{i}": "x" * 50 for i in range(100)}
    out = _shape(big)
    assert out.count(",") == 7, "eight keys, so seven separators"
    assert len(out) < 120 and "\n" not in out
    assert "xxxx" not in out, "no values"


# --- provenance -------------------------------------------------------------------------------------

def test_both_lost_questions_are_named():
    b = " ".join(_block().replace("#", " ").split())
    assert "registryhub_register_endpoint" in b
    assert "register_seed_data" in b


def test_the_downstream_mistake_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "mention counts as call counts" in b or "read mention counts" in b


def test_item_47s_overreach_is_recorded_here():
    """item 47 said 'recorded nowhere'; scalars were always recorded."""
    d = __doc__ or ""
    assert "corrects item 47" in d
    assert "Scalar arguments ARE recorded" in d


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
