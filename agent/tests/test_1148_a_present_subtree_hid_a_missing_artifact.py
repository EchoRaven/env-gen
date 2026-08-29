"""#1148: `app/` existed, so nothing noticed that the SQL inside it did not.

The delivery recovery asks whether a SUBTREE ROOT is present. #691 documented the mechanism
that strands one — "the writer commits mcp_server/ on `main`, delivery runs on `integration`,
and `git merge-base --is-ancestor` says main is NOT an ancestor of integration" — and measured
125 of 144 corpus runs missing it.

netflix-local-r11 is the same mechanism one level down. `app/` was present (backend and
frontend both there), so the loop skipped, while `app/database/init/01_init.sql` — 2855 bytes,
written by that very delivery — sat on `main` at 43ef69a, not an ancestor of `integration`.
Verified in the run's own repo: every branch including `integration` lacks the file, only
`main` has it, and there is no deletion commit anywhere. `database_sql_missing` then blocked
**20 of that run's 21 gate evaluations**. r10, on the same code, had it on integration.

So the recovery set is the delivery gate's own required artifacts, not three directory names:
`app/database` is checked for a `.sql` because that is literally what `database_sql_missing`
tests.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path("env_generator/llm_generator/multi_agent/runtime/heal_pipeline.py").read_text(
    encoding="utf-8")
GATE = Path("env_generator/llm_generator/multi_agent/runtime/delivery_gate.py").read_text(
    encoding="utf-8")


class TestTheRecoverySetIsArtifactShaped:

    def test_app_database_joins_the_recovery_set(self):
        blk = SRC[SRC.index("_subs_1148 = ["):SRC.index("for sub in _subs_1148")]
        assert '"app/database"' in blk

    def test_it_is_added_only_when_the_sql_is_actually_missing(self):
        blk = SRC[SRC.index("_subs_1148 = ["):SRC.index("for sub in _subs_1148")]
        assert 'glob("**/*.sql")' in blk
        assert "not any(" in blk

    def test_the_loop_condition_also_tests_the_artifact(self):
        i = SRC.index("for sub in _subs_1148")
        cond = SRC[i:SRC.index(":\n", SRC.index("if not (repo / sub).exists()", i))]
        assert 'sub == "app/database"' in cond
        assert 'glob("**/*.sql")' in cond

    def test_a_fault_in_the_probe_cannot_break_delivery(self):
        blk = SRC[SRC.index("_subs_1148 = ["):SRC.index("for sub in _subs_1148")]
        assert "except Exception:" in blk and "pass" in blk


class TestItMatchesWhatTheGateActuallyRequires:
    """A recovery that checks something else than the gate is a recovery that misses."""

    def test_the_gate_tests_app_database_for_sql(self):
        assert 'database_has_sql = any((output_dir / "app/database").glob("**/*.sql"))' in GATE

    def test_the_recovery_uses_the_same_predicate(self):
        blk = SRC[SRC.index("_subs_1148 = ["):SRC.index("for sub in _subs_1148")]
        assert '"app" / "database"' in blk or '"app/database"' in blk
        assert 'glob("**/*.sql")' in blk


class TestTheOriginalThreeAreUntouched:

    def test_the_top_level_subtrees_still_recover(self):
        blk = SRC[SRC.index("_subs_1148 = ["):SRC.index("for sub in _subs_1148")]
        for sub in ("app", "mcp_server", "docker"):
            assert f'"{sub}"' in blk

    def test_a_missing_root_still_triggers_on_existence_alone(self):
        i = SRC.index("for sub in _subs_1148")
        cond = SRC[i:SRC.index(":\n", SRC.index("if not (repo / sub).exists()", i))]
        assert "not (repo / sub).exists()" in cond
