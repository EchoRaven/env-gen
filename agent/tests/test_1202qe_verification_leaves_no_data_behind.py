"""#1202qe: verification snapshots the seeded data and restores it afterwards, once, after the
last overlapping verifier on the same database finishes (tiktok-r126: verifier accounts in
'Suggested LIVE creators', 409 duplicate follow left by an earlier pass)."""
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import verification_isolation as VI
from env_generator.llm_generator.multi_agent.runtime import validation_runner as VR


@pytest.fixture
def db(tmp_path, monkeypatch):
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / "docker-compose.yml").write_text("services: {database: {}}\n")
    calls = []
    state = {"cid": "c1", "fail_snapshot": False}
    monkeypatch.setattr(VI, "_db_cid", lambda compose, timeout: state["cid"])

    def _exec(cid, script, timeout):
        kind = "snapshot" if "pg_dump" in script else "restore"
        calls.append((kind, cid))
        rc = 1 if (kind == "snapshot" and state["fail_snapshot"]) else 0
        return type("R", (), {"returncode": rc, "stdout": "", "stderr": ""})()
    monkeypatch.setattr(VI, "_exec", _exec)
    monkeypatch.delenv("ENVGEN_VERIFY_DB_ISOLATION", raising=False)
    VI._ACTIVE_1202QE.clear()
    return tmp_path, calls, state


def test_one_scope_snapshots_then_restores(db):
    proj, calls, _ = db
    with VI.isolated_verification_1202qe(proj, "validation"):
        assert calls == [("snapshot", "c1")]
    assert calls == [("snapshot", "c1"), ("restore", "c1")]


def test_overlapping_scopes_restore_once_after_the_last(db):
    proj, calls, _ = db
    squad = VI.isolated_verification_1202qe(proj, "squad").__enter__()
    with VI.isolated_verification_1202qe(proj, "walk"):
        pass
    assert [c for c in calls if c[0] == "restore"] == [], "the walk restored under the squad"
    squad.__exit__(None, None, None)
    assert calls == [("snapshot", "c1"), ("restore", "c1")]


def test_a_new_container_is_a_new_group(db):
    proj, calls, state = db
    squad = VI.isolated_verification_1202qe(proj, "squad").__enter__()
    state["cid"] = "c2"                      # validation's down -v recreated the database
    with VI.isolated_verification_1202qe(proj, "validation"):
        pass
    assert ("snapshot", "c2") in calls and ("restore", "c2") in calls
    squad.__exit__(None, None, None)


def test_a_failed_snapshot_restores_nothing(db):
    proj, calls, state = db
    state["fail_snapshot"] = True
    with VI.isolated_verification_1202qe(proj, "validation"):
        pass
    assert [c for c in calls if c[0] == "restore"] == []


def test_the_switch_turns_it_off(db, monkeypatch):
    proj, calls, _ = db
    monkeypatch.setenv("ENVGEN_VERIFY_DB_ISOLATION", "0")
    with VI.isolated_verification_1202qe(proj, "validation"):
        pass
    assert calls == []


def test_validation_finalize_closes_the_scope(db):
    proj, calls, _ = db
    scope = VI.isolated_verification_1202qe(proj, "validation")
    scope.__enter__()
    VR._VALIDATION_SCOPE_1202QE.append(scope)
    VR._finalize([{"name": "x", "status": "pass"}], 1)
    assert calls[-1] == ("restore", "c1") and VR._VALIDATION_SCOPE_1202QE == []


def _fn_src(mod_file, name):
    import ast
    src = Path(mod_file).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node)
    return ""


def test_every_writer_is_wrapped():
    from env_generator.llm_generator.multi_agent.runtime import heal_pipeline, test_user_squad
    assert "isolated_verification_1202qe" in _fn_src(heal_pipeline.__file__, "run_test_user_validation")
    assert "isolated_verification_1202qe" in _fn_src(test_user_squad.__file__, "_run_squad_for_delivery_impl")
    body = _fn_src(VR.__file__, "run_smoke_validation")
    assert body.index("isolated_verification_1202qe") > body.index('_add("backend_health", True)')
