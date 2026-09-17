"""#1202qj: the test-user API journey holds a stack lease (r127: api_smoke `down -v` mid-journey
-> '0/0 steps'), the browser walk takes its own data scope on the database it uses, and a scope
whose database was recreated reports that honestly instead of a leftover-data warning."""
import ast
import logging
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import heal_pipeline, verification_isolation as VI


def _src(name):
    src = Path(heal_pipeline.__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node)
    return ""


def test_the_api_journey_runs_under_a_stack_lease():
    body = _src("run_test_user_validation")
    lease = body.index('"test-user API journey"')
    assert lease < body.index("report = run_test_user_validation(")


def test_the_walk_has_its_own_data_scope_inside_its_lease():
    body = _src("_walk")
    assert body.index("stack_lease_1202nx") < body.index('"browser_walk"') < body.index(
        "run_browser_test_user(")


def test_a_recreated_database_is_reported_as_nothing_to_restore(tmp_path, monkeypatch, caplog):
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / "docker-compose.yml").write_text("services: {database: {}}\n")
    monkeypatch.setattr(VI, "_db_cid", lambda compose, timeout: "c1")
    monkeypatch.setattr(VI, "snapshot_db_1202qe", lambda compose, tag: {"ok": True})
    monkeypatch.setattr(VI, "restore_db_1202qe", lambda compose, tag: {
        "ok": False, "error": "no snapshot in the container (it was recreated)"})
    VI._ACTIVE_1202QE.clear()
    log = logging.getLogger("qj")
    with caplog.at_level(logging.INFO, logger="qj"):
        with VI.isolated_verification_1202qe(tmp_path, "test_user_validation", log):
            pass
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("recreated" in r.getMessage() for r in caplog.records)
