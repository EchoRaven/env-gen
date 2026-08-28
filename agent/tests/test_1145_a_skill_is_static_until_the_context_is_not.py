"""#1145: a skill is static, so stop re-delivering it — until a condense makes that false.

netflix-local-r9 made 163 `get_skill` calls covering EIGHT distinct skills. The orchestrator
fetched `release-readiness` 56 times and `verification-before-completion` 35; the backend
fetched `api-contract-guard` 22. **155 of 163 were re-fetches of text the caller already
held**, each costing a full turn re-sending 54-65K tokens — the same order as the 179
edit-anchor failures.

`read` already solved this (`_IDENTICAL_READ_ELIDE_AT`, "identical content already delivered
to you Nx … call read(force=true)"), so `get_skill` reuses the mechanism rather than inventing
a rule.

#1145b — the correctness condition the elision depends on: "you already have it" is only true
while the caller's history still holds it. This framework CONDENSES messages
(`_maybe_condense_messages_in_place`; every run logs `#1025 condense`), which can drop exactly
those messages. Both caches are therefore re-armed at the one place that knows the history was
truncated. `read`'s cache had this gap since #613 and is fixed with it.
"""
from __future__ import annotations

import pathlib
import tempfile

from env_generator.llm_generator.tools.canonical_file_tools.read import ReadTool
from env_generator.llm_generator.workspace import Workspace


def _ws():
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "f.txt").write_text("alpha\nbravo\n", encoding="utf-8")
    return d, ReadTool(workspace=Workspace(str(d)))


class TestIdenticalRedeliveryIsElided:

    def test_the_third_identical_read_stops_resending_the_body(self):
        d, r = _ws()
        first = r.execute(file_path="f.txt").data["content"]
        assert "alpha" in first
        r.execute(file_path="f.txt")
        third = r.execute(file_path="f.txt").data["content"]
        assert "already delivered" in third
        assert "alpha" not in third

    def test_it_tells_the_caller_how_to_get_it_back(self):
        d, r = _ws()
        for _ in range(3):
            out = r.execute(file_path="f.txt").data["content"]
        assert "force=true" in out


class TestACondenseReArmsTheCache:
    """The correctness condition: after a condense the caller may no longer hold it."""

    def test_forgetting_makes_the_next_read_deliver_in_full(self):
        d, r = _ws()
        for _ in range(3):
            out = r.execute(file_path="f.txt").data["content"]
        assert "already delivered" in out

        r.forget_deliveries_1145()          # what the condense hook calls

        after = r.execute(file_path="f.txt").data["content"]
        assert "alpha" in after, "a condensed caller must get the content back"
        assert "already delivered" not in after

    def test_the_hook_exists_on_both_delivery_caches(self):
        d, r = _ws()
        assert callable(getattr(r, "forget_deliveries_1145", None))
        from env_generator.llm_generator.tools import knowledge_tools as kt
        assert "forget_deliveries_1145" in pathlib.Path(kt.__file__).read_text(
            encoding="utf-8")

    def test_the_condense_path_calls_it(self):
        src = pathlib.Path(
            "env_generator/llm_generator/multi_agent/agents/runtime/step_pipeline/tooling.py"
        ).read_text(encoding="utf-8")
        # landmark-anchored, not a byte window (#943): from the condense branch to the log
        # line that closes it.
        i = src.index("if len(messages) < before:")
        j = src.index("condensed messages", i)
        assert "forget_deliveries_1145" in src[i:j], \
            "the reset must happen where the history is known to have been truncated"

    def test_a_tool_without_the_hook_is_skipped_not_crashed(self):
        src = pathlib.Path(
            "env_generator/llm_generator/multi_agent/agents/runtime/step_pipeline/tooling.py"
        ).read_text(encoding="utf-8")
        k = src.index("forget_deliveries_1145")
        blk = src[src.rindex("for _t in", 0, k):src.index("self._logger.info", k)]
        assert "getattr(" in blk and "callable(" in blk
