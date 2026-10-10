r"""#1203hc: a truncated vision reply threw away every component that DID arrive.

`decompose_reference` extracted the component array with
`re.search(r"\[.*\]", text, re.DOTALL)` — which needs the closing bracket — from a call
made with `max_tokens=3000`. A component-dense screen overruns that: the reply stops
mid-array, there is no `]`, the regex matches nothing, and the WHOLE reply is discarded.

MEASURED over the corpus. `component decompose produced nothing for ...` appears 177
times; 91 of them say `no component JSON array in the vision response` — the single
largest cause (the rest are credit exhaustion and spend caps, not defects). By screen:
explore_grid 55, following_suggested_creators 15, friends_suggested_creators 14,
live_discover 10 — grids and card lists, i.e. the screens with the most components.
70 calls report `completion_tokens=3000` and 66 of those `finish=length`, and the
per-run counts line up ONE FOR ONE with the no-array errors: r166 2/2, r163 1/1,
r161 1/1, r169 0/0, r175 0/0. In r166 the capped response at 04:19:44 is followed on
the NEXT log line by `component decompose produced nothing for explore_grid.png`.

THE COST IS SILENT FIDELITY LOSS. `design/component_specs/<stem>.json` is the frontend
lane's per-component build spec with MEASURED colors (PIPELINE.md §2-4). On disk, 22 of
59 recent runs have no `explore_grid.json` while its reference image sits right there —
so the most component-dense screen in the app is the one built without a spec.

★ I GOT THE CAUSE WRONG TWICE FIRST. The failing screens are also the LARGEST files
(explore_grid.png 5.9MB), so I spent a while on an image-size limit; and I claimed "no
log names the failed image" when `component decompose produced nothing for` names it
177 times — my grep's `(fail|error|skip)` alternation simply had no word for "produced
nothing". The reply length, not the image size, is what `finish=length` measures.

★ SALVAGING IS NOT MASKING. The shortfall is reported: `truncated_1203hc` travels out of
`decompose_reference` and `reference_materials` logs it by image name, so `11/11
decomposed` can no longer read as complete when one of the eleven is half a screen.
"""
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.material_prep import (  # noqa: E402
    salvage_component_array_1203hc)

_C1 = '{"name": "feed_tile", "region": [0, 0, 100, 100], "role": "grid_item"}'
_C2 = '{"name": "nav_bar", "region": [0, 900, 400, 60], "role": "navigation"}'


def test_a_complete_array_is_parsed_unchanged():
    """★ The no-op guarantee: the overwhelming majority of replies close their bracket
    and must come back byte-identical in meaning."""
    comps, note = salvage_component_array_1203hc(f"here you go:\n[{_C1}, {_C2}]\nthanks")
    assert [c["name"] for c in comps] == ["feed_tile", "nav_bar"]
    assert note == "", note


def test_a_truncated_array_keeps_the_components_that_arrived():
    """★ THE defect. The reply stops mid-object; two whole components precede it."""
    text = f'[{_C1}, {_C2}, {{"name": "half_a_comp", "region": [0, 0,'
    comps, note = salvage_component_array_1203hc(text)
    assert [c["name"] for c in comps] == ["feed_tile", "nav_bar"], comps
    assert "cut off" in note and "2 complete" in note, note


def test_the_note_says_how_many_survived():
    """A count the reader can act on: 18 of a promised 24 is a different situation from
    2 of 24, and only the note distinguishes them."""
    body = "[" + ", ".join([_C1] * 7) + ', {"name": "cut'
    comps, note = salvage_component_array_1203hc(body)
    assert len(comps) == 7
    assert "7 complete" in note, note


def test_an_unbalanced_brace_inside_a_string_does_not_end_an_object():
    """★ The scanner must track string state. The first version of this test used a
    BALANCED `{new}` inside the label, so brace depth returned to zero anyway and
    disabling string tracking stayed green — the mutation exposed the test, not the code.
    An UNMATCHED `{` inside a string is what actually distinguishes them: without string
    tracking the depth never returns to zero and the component is lost."""
    tricky = '{"name": "btn", "label": "Add { item", "role": "action"}'
    comps, _note = salvage_component_array_1203hc(f'[{tricky}, {{"name": "x"')
    assert [c["name"] for c in comps] == ["btn"], comps


def test_an_escaped_quote_does_not_resync_the_string_state():
    """★ Same lesson one level DEEPER, and it took three tries. An unmatched brace AFTER
    the escaped quotes costs nothing: with or without backslash handling it still lands
    inside a string region, because `\\"hi\\"` flips the state an even number of times.
    The brace has to sit BETWEEN the two escaped quotes -- there, correct handling keeps
    it inside one string while dropping the escape rule puts it outside, the depth never
    returns to zero and the component is lost."""
    tricky = ('{"name": "btn", "label": "say \\"{\\" done", '
              '"role": "action"}')
    comps, _note = salvage_component_array_1203hc(f'[{tricky}, {{"nam')
    assert comps and comps[0]["name"] == "btn", comps
    assert comps[0]["label"] == 'say "{" done', comps


def test_a_reply_with_no_array_at_all_salvages_nothing():
    """★ The no-over-reach guard: a refusal or a prose answer must stay an error, not
    become an empty success."""
    comps, note = salvage_component_array_1203hc(
        "I'm unable to analyse this image.")
    assert comps == [] and note == ""


def test_an_empty_reply_salvages_nothing():
    for empty in ("", None):
        comps, note = salvage_component_array_1203hc(empty)
        assert comps == [] and note == ""


def test_a_truncated_reply_with_no_complete_object_salvages_nothing():
    """Half of one component is not a component. Reporting it as salvaged would be the
    #1202xc mistake: trading one silence for another."""
    comps, note = salvage_component_array_1203hc('[{"name": "half_a_co')
    assert comps == [] and note == ""


def test_objects_after_the_truncation_point_are_not_invented():
    """The note must claim only what arrived."""
    comps, note = salvage_component_array_1203hc(f'[{_C1}, {{"name": "lost"')
    assert len(comps) == 1
    assert "any after them are missing" in note, note


def test_the_salvage_never_raises():
    """It runs on the vision path, whose contract is "best-effort, never raises into the
    caller"."""
    for junk in ("[[[[", "[}", '[{"a": }]', "[" * 500, '[{"a": "' + "x" * 5000):
        comps, note = salvage_component_array_1203hc(junk)
        assert isinstance(comps, list) and isinstance(note, str)


# --------------------------------------------------------------- the real caller
class _FakeResp:
    def __init__(self, content, finish_reason):
        self.content = content
        self.finish_reason = finish_reason


class _FakeClient:
    def __init__(self, content, finish_reason="length"):
        self._content = content
        self._finish = finish_reason
        self.max_tokens_seen = None

    async def chat(self, messages, temperature=0.0, max_tokens=None):
        self.max_tokens_seen = max_tokens
        return _FakeResp(self._content, self._finish)


def _decompose(tmp_path, content, finish_reason="length"):
    import asyncio

    from PIL import Image

    from multi_agent.runtime.material_prep import decompose_reference
    img = tmp_path / "explore_grid.png"
    Image.new("RGB", (40, 40), (10, 20, 30)).save(img)
    client = _FakeClient(content, finish_reason)
    res = asyncio.run(decompose_reference(str(img), client))
    return res, client


def test_the_caller_salvages_instead_of_returning_an_error(tmp_path):
    """★ THE CALLER, not the helper. Before this patch a truncated reply came back as
    `{"error": "no component JSON array ..."}` and `precompute_component_specs` skipped
    the screen, so no `component_specs/explore_grid.json` was ever written."""
    body = "[" + ", ".join([_C1] * 6) + ', {"name": "cut'
    res, _client = _decompose(tmp_path, body)
    assert "error" not in res, res
    assert res["count"] == 6, res
    assert "cut off" in res["truncated_1203hc"], res


def test_the_truncation_note_reaches_the_result(tmp_path):
    """It has to travel out of here, because `reference_materials` is what logs it and
    `11/11 decomposed` otherwise reads as complete."""
    res, _c = _decompose(tmp_path, "[" + _C1 + ', {"name": "cut')
    assert res.get("truncated_1203hc"), res


def test_a_clean_reply_carries_no_truncation_note(tmp_path):
    """★ The no-op guarantee at the caller: a complete reply must not be editorialised."""
    res, _c = _decompose(tmp_path, f"[{_C1}, {_C2}]", finish_reason="stop")
    assert "truncated_1203hc" not in res, res
    assert res["count"] == 2, res


def test_an_unsalvageable_reply_names_the_token_cap_as_the_reason(tmp_path):
    """★ `finish_reason` is the fact that separates "the model answered something else"
    from "the model was cut off", and the old error named neither. 66 of the corpus's 70
    capped calls report finish=length."""
    res, _c = _decompose(tmp_path, "I cannot analyse this", finish_reason="length")
    assert "error" in res, res
    assert "finish_reason=length" in res["error"], res["error"]
    assert res.get("finish_reason_1203hc") == "length", res


def test_a_non_truncation_failure_does_not_blame_the_token_cap(tmp_path):
    """A refusal is not a truncation; saying it was sends the reader to the wrong fix."""
    res, _c = _decompose(tmp_path, "I cannot analyse this", finish_reason="stop")
    assert "error" in res, res
    assert "finish_reason=length" not in res["error"], res["error"]


def test_the_token_budget_matches_the_component_contract(tmp_path):
    """★ 3000 was the defect's root: `max_components=24` promises 24 components with
    regions, roles and states, which does not fit. 70 corpus calls hit exactly 3000 and
    66 reported finish=length. Salvage is the net; the budget is the fix."""
    _res, client = _decompose(tmp_path, f"[{_C1}]", finish_reason="stop")
    assert client.max_tokens_seen is not None, "the call stopped passing a budget"
    assert client.max_tokens_seen >= 8000, client.max_tokens_seen
