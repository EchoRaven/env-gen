"""#1147: the plan classifier read `items`; the plan tool sends `stages`.

`plan`'s schema (reasoning_tools.py) declares action / plan_name / plan_description /
**stages**, and every recorded call in the corpus is
`plan(action, plan_name, plan_description, stages)`. The classifier read
`tool_args.get("items", [])`, which is therefore always `[]`, so `action == "create" and items`
never held and the `plan` category was never written.

Measured: `plan` was called 13 times across 5 of 8 netflix runs and produced ZERO `plan` rows.
All 110 of r9's knowledge rows are `tech_context / 0.6`.

Third field-name miss of this session's lineage, after #1029 ("#1017 READ THE COUNT AND TRIED
TO ITERATE IT") and #1128's collector: reader and producer disagree about a name, and the
result is silence rather than an error.
"""
from __future__ import annotations

import pathlib

MEM = pathlib.Path("env_generator/llm_generator/memory/generator_memory.py")


class _Mem:
    def __init__(self):
        self._working_memory = {}
        self.stored = []

    def _record_auto_knowledge_if_new(self, *, content, category, importance):
        self.stored.append((content, category, importance))
        return True


def _extract(mem, **args):
    from env_generator.llm_generator.memory.generator_memory import GeneratorMemory
    GeneratorMemory._maybe_extract_knowledge(mem, "plan", args, None, True)


STAGES = [{"id": f"s{i}", "name": f"stage {i}"} for i in range(7)]


class TestTheRealKeyIsRead:

    def test_a_created_plan_is_recorded_from_stages(self):
        m = _Mem()
        _extract(m, action="create", plan_name="p", stages=STAGES)
        assert len(m.stored) == 1
        content, category, importance = m.stored[0]
        assert category == "plan" and importance == 0.8
        assert "7 items" in content

    def test_stage_names_reach_the_summary(self):
        m = _Mem()
        _extract(m, action="create", stages=STAGES)
        assert "stage 0" in m.stored[0][0]

    def test_more_than_five_stages_is_summarised_not_dumped(self):
        m = _Mem()
        _extract(m, action="create", stages=STAGES)
        assert "and 2 more" in m.stored[0][0]

    def test_dict_stages_do_not_raise_on_join(self):
        """`"; ".join(...)` over dicts would have raised — names are extracted first."""
        m = _Mem()
        _extract(m, action="create", stages=[{"id": "a", "name": "x"}])
        assert m.stored[0][0].endswith("x")


class TestItStaysQuietWhenItShould:

    def test_no_stages_records_nothing(self):
        m = _Mem()
        _extract(m, action="create", stages=[])
        assert m.stored == []

    def test_a_non_create_action_records_nothing(self):
        m = _Mem()
        _extract(m, action="complete", stages=STAGES)
        assert m.stored == []

    def test_malformed_stages_do_not_raise(self):
        for bad in ("nope", 7, None, [None, 3]):
            m = _Mem()
            _extract(m, action="create", stages=bad)   # must not raise

    def test_the_legacy_items_key_still_works(self):
        """Callers that do send `items` keep working — the fix is additive."""
        m = _Mem()
        _extract(m, action="create", items=["a", "b"])
        assert len(m.stored) == 1 and "2 items" in m.stored[0][0]


class TestTheOldKeyIsNoLongerTheOnlySource:

    def test_stages_is_consulted_in_the_source(self):
        src = MEM.read_text(encoding="utf-8")
        i = src.index('if tool_name == "plan":')
        branch = src[i:src.index('if tool_name == "think":', i)]
        assert 'tool_args.get("stages")' in branch
