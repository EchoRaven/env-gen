"""#1146: the failing→passing lint branch was unsatisfiable, so one whole category was empty.

`_maybe_extract_knowledge` carried a branch labelled "Was failing, now passes - record the
fix". It cannot fire, in any input:

    tooling.py:633   record_lint(path, result.success)      ← dict updated to the CURRENT result
    tooling.py:647   record_tool_call(...) → _maybe_extract_knowledge(...)
                                              ↑ returns early unless success is True
    branch test:     not self._lint_results.get(path, True) ← that value was just set to True

Measured: netflix-local-r9 ran `lint` 650 times with 13 failures and stored ZERO `bug_fix`
entries. All 110 of its knowledge rows are `category=tech_context, importance=0.6` — the
send_message path is the only one that can fire, because `plan` and `think` were called 0
times by any agent, so their branches are dead too.

The transition is only visible inside `record_lint`, which holds the old value and the new one.
"""
from __future__ import annotations

import pathlib

MEM = pathlib.Path("env_generator/llm_generator/memory/generator_memory.py")


class _Mem:
    """The two attributes record_lint touches, plus a capture of what it stored."""

    def __init__(self):
        self._lint_results = {}
        self._files_linted = set()
        self.stored = []

    def _normalize_path(self, p):
        return str(p)

    def _record_auto_knowledge_if_new(self, *, content, category, importance):
        self.stored.append((content, category, importance))
        return True

    def remember(self, *a, **k):
        pass


def _record_lint(mem, path, passed):
    """Call the real implementation against the stub."""
    from env_generator.llm_generator.memory.generator_memory import GeneratorMemory
    GeneratorMemory.record_lint(mem, path, passed)


class TestTheTransitionIsRecorded:

    def test_failing_then_passing_stores_a_bug_fix(self):
        m = _Mem()
        _record_lint(m, "a.py", False)
        assert m.stored == []
        _record_lint(m, "a.py", True)
        assert len(m.stored) == 1
        content, category, importance = m.stored[0]
        assert "a.py" in content and category == "bug_fix" and importance == 0.7

    def test_the_category_is_one_the_store_never_had(self):
        m = _Mem()
        _record_lint(m, "b.py", False)
        _record_lint(m, "b.py", True)
        assert m.stored[0][1] == "bug_fix"


class TestItDoesNotFireOnAnythingElse:

    def test_a_first_pass_is_not_a_fix(self):
        m = _Mem()
        _record_lint(m, "c.py", True)
        assert m.stored == []

    def test_passing_twice_records_once_at_most(self):
        m = _Mem()
        _record_lint(m, "d.py", False)
        _record_lint(m, "d.py", True)
        _record_lint(m, "d.py", True)
        assert len(m.stored) == 1

    def test_still_failing_records_nothing(self):
        m = _Mem()
        _record_lint(m, "e.py", False)
        _record_lint(m, "e.py", False)
        assert m.stored == []

    def test_a_regression_records_nothing(self):
        m = _Mem()
        _record_lint(m, "f.py", True)
        _record_lint(m, "f.py", False)
        assert m.stored == []

    def test_paths_do_not_bleed_into_each_other(self):
        m = _Mem()
        _record_lint(m, "g.py", False)
        _record_lint(m, "h.py", True)
        assert m.stored == []


class TestTheUnreachableBranchIsGone:

    def test_the_extractor_no_longer_tests_lint_results(self):
        src = MEM.read_text(encoding="utf-8")
        i = src.index("def _maybe_extract_knowledge")
        body = src[i:src.index("\n    def ", i + 10)]
        assert "_lint_results" not in body, \
            "an unreachable branch reads as coverage that does not exist"

    def test_the_state_is_still_recorded_for_the_health_summary(self):
        src = MEM.read_text(encoding="utf-8")
        assert 'self._lint_results[normalized] = passed' in src
        assert '"lint_failed"' in src
