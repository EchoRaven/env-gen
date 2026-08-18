r"""#956: the seed audit returns "clean" after examining zero tables.

    for name, table in tables.items():
        if (table.get("status") or "defined") != "defined":
            continue

Corpus: **1729 `implemented` against 16 `defined`, and 145 of 147 runs have no `defined` table at
all.** So this audit has reported a clean verdict while inspecting nothing, for essentially the
whole project.

★ Deliberately NOT widened to `implemented`. r154 would then flag all twelve tables `missing_seed`
while its live database holds titles 60, title_genres 57, episodes 16, genres 10, my_list 8,
continue_watching 7, profiles 6, ratings 5 — every one above `_DEFAULT_MIN_ROWS = 5`. The app seeds
through SQL INSERT and this audit's notion of seeded is `list_seed_registrations()`, which returns
0. Widening the filter without fixing the definition converts a dead check into twelve false
blockers on a correctly seeded app, and false blockers wedge runs (#566j; r117/r120 lost 75
minutes to a no-deliver abort).

So: say the state, change no verdict. The real repair counts ROWS at gate time — the database is up
when this runs — and that needs a live run to validate, not a unit test.
"""
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import seed_audit as sa


class _Hub:
    def __init__(self, tables, regs=None):
        self._t, self._r = tables, regs or {}
        self.schema_hub = self

    def list_tables(self):
        return self._t

    def list_seed_registrations(self):
        return self._r


def test_it_announces_when_it_examined_nothing(caplog):
    """★ THE point: a clean verdict from zero inspections must not read as 'nothing wrong'."""
    hub = _Hub({"titles": {"status": "implemented"}, "users": {"status": "implemented"}})
    with caplog.at_level(logging.WARNING,
                         logger="env_generator.llm_generator.multi_agent.runtime.seed_audit"):
        r = sa.audit_seed_data(hub)
    msg = " ".join(x.getMessage() for x in caplog.records)
    assert "EXAMINED 0 OF 2 TABLES" in msg, msg
    assert r.is_clean, "the verdict itself must not change — this ticket adds no blocker"


def test_it_stays_quiet_when_it_did_examine_tables(caplog):
    """A line that fires on every run stops being read (#845)."""
    hub = _Hub({"titles": {"status": "defined"}}, regs={"titles": {"rows": 10}})
    with caplog.at_level(logging.WARNING,
                         logger="env_generator.llm_generator.multi_agent.runtime.seed_audit"):
        sa.audit_seed_data(hub)
    assert "EXAMINED 0" not in " ".join(x.getMessage() for x in caplog.records)


def test_it_stays_quiet_when_there_are_no_tables_at_all(caplog):
    """No tables is not the same fact as tables-all-skipped, and only the second is a finding."""
    with caplog.at_level(logging.WARNING,
                         logger="env_generator.llm_generator.multi_agent.runtime.seed_audit"):
        sa.audit_seed_data(_Hub({}))
    assert "EXAMINED 0" not in " ".join(x.getMessage() for x in caplog.records)


def test_a_defined_table_without_a_registration_is_still_flagged():
    """The audit's real behaviour, unchanged: this ticket must add nothing and remove nothing."""
    r = sa.audit_seed_data(_Hub({"titles": {"status": "defined"}}))
    assert [f["reason"] for f in r.flagged_tables] == ["missing_seed"]


def test_the_message_carries_the_registration_count():
    """The number that explains why widening the filter is not the fix."""
    import inspect
    src = inspect.getsource(sa.audit_seed_data)
    assert "len(seed_regs)" in src and "seeded-ness" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
