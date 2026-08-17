"""#482 — THE last Part-B delivery blocker on a fully-converged run (r53 + r54, live).

_generate_database writes app/database/init/01_init.sql at startup, but the per-tick
_merge_committed_agent_work can DROP the working-tree copy (a lane's worktree branched
before the scaffold → the merge removes app/database). The only per-tick re-author was
nested inside `if _should_regen_skeleton(...)`, so a merge that wiped app/database WITHOUT
changing the backend-skeleton signature left it gone → the delivery gate's database_has_sql
(globs app/database/**/*.sql) stayed False → database_sql_missing → the final post-loop gate
RAISED RuntimeError → the run died with 0 releases even though r54 had 10/10 chains passing,
api_smoke green, and ZERO churn. reauthor_missing_database_sql restores it UNCONDITIONALLY
each tick (write-if-missing), independent of skeleton-regen. Generalizable to every env."""
import asyncio
import types
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.framework_validation import (
    reauthor_missing_database_sql)


def _run(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def _orch(tmp_path, gen_writes_sql=True, gen_raises=False):
    """A minimal orch whose _generate_database mimics the real one: writes
    app/database/init/01_init.sql (unless told to fail / no-op)."""
    calls = {"n": 0}

    async def _generate_database():
        calls["n"] += 1
        if gen_raises:
            raise RuntimeError("scaffold boom")
        if gen_writes_sql:
            d = Path(tmp_path) / "app" / "database" / "init"
            d.mkdir(parents=True, exist_ok=True)
            (d / "01_init.sql").write_text("CREATE TABLE t (id INT);\n", encoding="utf-8")

    orch = types.SimpleNamespace(
        output_dir=str(tmp_path),
        _generate_database=_generate_database,
        _logger=types.SimpleNamespace(warning=lambda *a, **k: None),
    )
    orch._gen_calls = calls
    return orch


def test_reauthors_when_sql_missing(tmp_path):
    orch = _orch(tmp_path)
    assert not any((Path(tmp_path) / "app" / "database").glob("**/*.sql"))
    restored = _run(reauthor_missing_database_sql(orch))
    assert restored is True, "#482: must re-author when app/database/*.sql is missing"
    assert orch._gen_calls["n"] == 1, "#482: calls _generate_database exactly once"
    assert any((Path(tmp_path) / "app" / "database").glob("**/*.sql")), \
        "#482: app/database/*.sql now present → database_sql_missing gate clears"


def test_noop_when_sql_present(tmp_path):
    # pre-existing SQL (not merge-wiped) → cheap glob, NO subprocess/regen
    d = Path(tmp_path) / "app" / "database" / "init"
    d.mkdir(parents=True, exist_ok=True)
    (d / "01_init.sql").write_text("CREATE TABLE t (id INT);\n", encoding="utf-8")
    orch = _orch(tmp_path)
    assert _run(reauthor_missing_database_sql(orch)) is False, \
        "#482: present → no-op (don't re-run the scaffold every tick when it exists)"
    assert orch._gen_calls["n"] == 0, "#482: does NOT call _generate_database when SQL present"


def test_best_effort_never_raises(tmp_path):
    # a scaffold failure must be swallowed (best-effort) — never raise into the tick loop
    orch = _orch(tmp_path, gen_raises=True)
    assert _run(reauthor_missing_database_sql(orch)) is False, \
        "#482: on scaffold error, return False and do not raise into the coordination tick"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
