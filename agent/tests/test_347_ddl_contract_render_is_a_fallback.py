"""#347: don't re-render the contract DDL when the ORM is the authority.

`app/database/init/01_init.sql` has two framework writers, both firing on every
validation tick:

    framework_validation:551  orch._generate_database()   -> contract render
    framework_validation:569  orch._repair_ddl_from_orm() -> ORM render (#43)

Counts: 122 vs 121 (r91), 102 vs 100 (r92), 34 vs 33 (r93). The ORM render runs
LAST and always wins, so ~100 contract renders per run are overwritten
immediately -- and the two outputs are NOT equivalent. Re-rendered from each
run's own persisted state, the contract version emits a bogus
`CREATE TABLE "_meta" ("id" SERIAL PRIMARY KEY)` and STRIPS every DEFAULT
(`"verified" BOOLEAN` vs `"verified" boolean default false`;
`"created_at" TIMESTAMPTZ` vs `timestamptz default now()`).

The delivered file is the good one in all three runs only because the ORM
writer happens to run second. The 1-tick gap where the counts differ (122 vs
121) is exactly the window where the `_meta`-polluted, default-less variant is
what sits on disk.

#43 already states why the ORM wins: "the model is the runtime truth, so
project the DDL from it". So the contract render should be a FALLBACK -- it is
still the only writer before the skeleton has emitted models.py, and the
delivery gate requires app/database/*.sql to exist, so it cannot be deleted.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _decide(**kw):
    from multi_agent.runtime.framework_validation import (
        contract_ddl_render_needed)
    return contract_ddl_render_needed(**kw)


class TheContractRenderIsSkippedWhenTheOrmIsAuthoritative(unittest.TestCase):

    def test_skipped_once_models_exist_and_the_ddl_is_present(self):
        self.assertFalse(_decide(orm_introspectable=True, ddl_exists=True))


class ItStillRunsWhenItIsTheOnlyWriter(unittest.TestCase):

    def test_runs_before_models_py_exists(self):
        """The scaffold is the only DDL author until the skeleton emits models."""
        self.assertTrue(_decide(orm_introspectable=False, ddl_exists=False))

    def test_runs_when_models_exist_but_no_ddl_has_been_written_yet(self):
        """The delivery gate globs app/database/*.sql -- the file must exist even
        if the ORM writer has not run yet this tick."""
        self.assertTrue(_decide(orm_introspectable=True, ddl_exists=False))

    def test_runs_when_the_orm_cannot_be_read_even_if_a_ddl_exists(self):
        """A broken/absent models.py means the ORM render will no-op, so the
        contract render must keep the file fresh."""
        self.assertTrue(_decide(orm_introspectable=False, ddl_exists=True))


class TheCallSiteUsesTheDecision(unittest.TestCase):

    def test_framework_validation_gates_the_call(self):
        from multi_agent.runtime import framework_validation
        src = Path(framework_validation.__file__).read_text()
        self.assertIn("contract_ddl_render_needed", src)
        # There are TWO call sites now. The other one is an UNCONDITIONAL
        # write-if-missing each tick, added because a merge that wipes app/database
        # without changing the backend-skeleton signature leaves it gone —
        # database_has_sql stays False, the post-loop gate raises, and the run dies
        # with 0 releases while 10/10 chains passed (r54). That call is SUPPOSED to
        # be ungated, so anchoring on the first occurrence tested the wrong one.
        #
        # Anchor on the decision and require the call to follow it, which is what
        # #347 is: the render happens only when the contract fallback is needed.
        idx = src.index("if contract_ddl_render_needed(")
        rest = src[idx:src.index("\n    def ", idx) if "\n    def " in src[idx:] else len(src)]
        self.assertIn("await orch._generate_database()", rest,
                      "the contract_ddl_render_needed decision no longer guards a render")


if __name__ == "__main__":
    unittest.main()
