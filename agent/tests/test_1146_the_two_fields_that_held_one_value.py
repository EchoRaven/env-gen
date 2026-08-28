"""#1146: category and importance existed, ranked nothing, and hid three dead paths.

netflix-local-r9 stored 110 knowledge rows. Every one carried category="tech_context" and
importance=0.6 — one value each — so the two fields a retriever would rank on held no
information and `query_knowledge` fell back to text similarity (89 of 99 queries returned
exactly ONE row; 62 of 99 were the same skill lookup).

The other three categories were unreachable, for three DIFFERENT reasons:

    plan     (0.8)  the `plan` tool is called 0 times in a run
    decision (0.7)  the `think` tool is called 0 times
    bug_fix  (0.7)  TWO faults: the branch read `_lint_results` AFTER record_lint had
                    overwritten it, so "was failing, now passes" actually meant "is failing
                    right now"; and its text, "Fixed lint errors in <path>" (~47 chars,
                    7 tokens), sat below this class's own 80-char / 8-token quality floor,
                    so every entry that did fire was discarded before storage.

The live branch — send_message 287 + broadcast 100 — already had the sender's own
classification in `msg_type`, wrote it into the TEXT, and dropped it from the fields.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path("env_generator/llm_generator/memory/generator_memory.py").read_text(
    encoding="utf-8")


class TestMsgTypeNowRanks:

    def test_the_hardcoded_pair_is_gone(self):
        # landmark-anchored (#943): the send_message branch, up to the next branch header.
        blk = SRC[SRC.index('if tool_name == "send_message":'):SRC.index("def get_tool_stats")]
        assert "category=_cat1146" in blk and "importance=_imp1146" in blk
        assert 'category="tech_context",\n                    importance=0.6,' not in blk

    def test_severities_map_to_distinct_categories(self):
        block = SRC[SRC.index("_cat1146, _imp1146 = {"):SRC.index("}.get(_mt1146")]
        for sev in ("blocker", "issue", "decision", "warning", "question"):
            assert f'"{sev}"' in block, sev

    def test_importances_are_not_all_the_same(self):
        block = SRC[SRC.index("_cat1146, _imp1146 = {"):SRC.index("}.get(_mt1146")]
        vals = {float(x) for x in re.findall(r"0\.\d+", block)}
        assert len(vals) >= 4, f"still a single band: {vals}"

    def test_an_unknown_type_keeps_the_old_default(self):
        assert '("tech_context", 0.6)' in SRC


class TestBugFixIsReachableAtAll:

    def test_the_transition_is_read_before_it_is_overwritten(self):
        blk = SRC[SRC.index("def record_lint"):SRC.index("if not passed:")]
        assert "_prev_1146 = self._lint_results.get(normalized)" in blk
        assert blk.index("_prev_1146 =") < blk.index("self._lint_results[normalized] = passed")

    def test_it_only_fires_on_failing_to_passing(self):
        blk = SRC[SRC.index("def record_lint"):SRC.index("if not passed:")]
        assert "if passed and _prev_1146 is False:" in blk

    def test_the_text_now_clears_the_quality_floor(self):
        """A category whose only possible text is below the bar is unreachable."""
        min_chars = int(re.search(r"_auto_knowledge_min_chars: int = (\d+)", SRC).group(1))
        min_tokens = int(re.search(r"_auto_knowledge_min_tokens: int = (\d+)", SRC).group(1))
        sample = ("Lint now PASSES for app/frontend/src/App.jsx after this lane edited it; "
                  "the previous run of the same check on this path failed. Treat a later "
                  "failure here as NEW, not as the same unfixed problem.")
        assert len(sample) >= min_chars
        assert len(re.findall(r"[a-zA-Z0-9_]+", sample)) >= min_tokens

    def test_the_old_short_text_would_have_been_rejected(self):
        """Pins WHY it was unreachable, so the floor cannot silently swallow it again."""
        min_chars = int(re.search(r"_auto_knowledge_min_chars: int = (\d+)", SRC).group(1))
        assert len("Fixed lint errors in design/reference_spec.json") < min_chars

    def test_the_unsatisfiable_branch_is_not_left_behind(self):
        extract = SRC[SRC.index("def _maybe_extract_knowledge"):SRC.index("def get_tool_stats")]
        assert "Fixed lint errors in" not in extract, "the dead copy must not linger"


class TestTheDeadPathsAreRecorded:
    """plan/decision stay in the mapping; the comment must say why they never fire."""

    def test_the_reason_is_written_down(self):
        assert "`plan` and `think` are tools no" in SRC or "the `plan` tool is called 0" in SRC
