r"""#957: every table reports "dead" because nothing ever registers a table consumer.

★ VERDICT CHANGED BY #1023b: when the index is wholly unpopulated the scan now reports NO dead
tables instead of all of them. #957's reasoning below is kept as written (item 48) — what it
got wrong was only the disposition, on the grounds that a live run was needed. It is not:
while the index is empty the old answer was 100% false positives, so suppressing it can only
remove false blockers, and one registration anywhere restores the original behaviour exactly.

`scan_dead_tables` calls a table dead when `get_table_consumers(name)` is empty. Corpus-wide,
`registryhub_table_consumers.json` holds **0 records in every run**, while
`registryhub_consumers.json` holds **1145** — every one keyed by `endpoint_id`, none by table. So
the scan returns EVERY table, every run: r154's twelve are all reported dead while its database
serves 60 titles, 57 title_genres, 16 episodes and five more populated tables.

The count feeds a delivery blocker ("N dead artifact(s)", relaxed once `functionally_validated`),
so it is not inert — it inflates every pre-validation tick by the whole table count and says
nothing about any table.

★ Not silently zeroed. Removing tables from the count changes a blocker's arithmetic, and that
needs a live run to validate — the rule this session adopted after #566j's 75-minute no-deliver
abort. Announced once instead, which is the same disposition as #956.
"""
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import coverage_audit as ca


class _Hub:
    def __init__(self, tables, consumers=None):
        self._t, self._c = tables, consumers or {}
        self.schema_hub = self

    def list_tables(self):
        return self._t

    def get_table_consumers(self, name):
        return self._c.get(name) or []


def test_an_empty_index_now_reports_NOTHING_1023b(caplog):
    """★ #957 announced the constant and deliberately changed no verdict, because dropping the
    tables term alters a blocker's arithmetic and that "needs a live run". #1023b overturns
    that, and the reason it does not need a run is that the change is safe by CONSTRUCTION:

        index empty      the old answer was 100% false positives -> suppressing it can only
                         remove false blockers (#566j cost r117/r120 a 75-minute abort)
        index non-empty  `registered_any` is True and behaviour is byte-identical

    Corpus: 0 real records in `registryhub_table_consumers.json` in 172 of 172 runs, while the
    `registryhub_register_table_consumer` tool is offered to every lane and has never been
    called once. r172 reported "12 dead tables" against a database serving eight populated ones.
    """
    hub = _Hub({"titles": {}, "users": {}, "genres": {}})
    with caplog.at_level(logging.WARNING,
                         logger="env_generator.llm_generator.multi_agent.runtime.coverage_audit"):
        out = ca.scan_dead_tables(hub)
    assert out == [], "an unpopulated index must not read as 'every table is dead'"
    assert "index is EMPTY" in " ".join(r.getMessage() for r in caplog.records)


def test_the_suppression_is_announced_not_silent(caplog):
    """It must still be audible: a term that stopped contributing must say so, or the next
    reader sees a clean dead-count and believes it was measured."""
    hub = _Hub({"titles": {}, "users": {}})
    with caplog.at_level(logging.WARNING,
                         logger="env_generator.llm_generator.multi_agent.runtime.coverage_audit"):
        ca.scan_dead_tables(hub)
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "#1023b" in msg and "register_table_consumer" in msg


def test_a_genuinely_dead_table_is_STILL_reported_once_anything_registers(caplog):
    """★ The guarantee that makes it safe: the check is suppressed only while the index is
    wholly unpopulated. One registration anywhere restores the original behaviour, including
    reporting a table that really has no consumer."""
    hub = _Hub({"titles": {}, "users": {}, "orphan": {}},
               consumers={"titles": [{"file": "x.py"}]})
    out = ca.scan_dead_tables(hub)
    assert sorted(d["table"] for d in out) == ["orphan", "users"]


def test_a_partial_result_is_not_announced(caplog):
    """If even one table has a consumer the number is informative and must stay quiet (#845)."""
    hub = _Hub({"titles": {}, "users": {}}, consumers={"titles": [{"file": "x.py"}]})
    with caplog.at_level(logging.WARNING,
                         logger="env_generator.llm_generator.multi_agent.runtime.coverage_audit"):
        out = ca.scan_dead_tables(hub)
    assert [d["table"] for d in out] == ["users"]
    assert "report as dead" not in " ".join(r.getMessage() for r in caplog.records)


def test_no_tables_is_not_announced(caplog):
    with caplog.at_level(logging.WARNING,
                         logger="env_generator.llm_generator.multi_agent.runtime.coverage_audit"):
        assert ca.scan_dead_tables(_Hub({})) == []
    assert "report as dead" not in " ".join(r.getMessage() for r in caplog.records)


def test_a_hub_without_the_method_is_survivable():
    class Bare:
        schema_hub = None
    assert ca.scan_dead_tables(Bare()) == []


def test_the_corpus_premise_still_holds():
    """★ Non-vacuity: if table consumers ever start being registered, this ticket's premise —
    and its warning — become wrong, and the test should say so rather than rot."""
    import json
    import pathlib
    gen = pathlib.Path(__file__).resolve().parents[1] / "generated"
    files = list(gen.glob("*/shared/hubs/registryhub_table_consumers.json"))
    if not files:
        pytest.skip("no runs on this box")
    total = 0
    for f in files:
        try:
            total += sum(1 for k in json.loads(f.read_text()) if k != "_meta")
        except Exception:
            pass
    assert total == 0, f"table consumers are now being registered ({total}); revisit #957"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
