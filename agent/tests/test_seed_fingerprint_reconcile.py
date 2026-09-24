"""The seed loader re-applies the seed when its SOURCE changes (outlook run-30, 2026-07-01).

The loader used to fill only EMPTY tables, so the fallback _SEED applied at first boot
PERMANENTLY shadowed the agent-authored seed_data.json written later: the DELIVERED app
carried the bland fallback (live: DB had avachen@… fallback users while seed_data.json said
alice@… → demo login 401 → QA/visual flows lost their populated session; inbox showed 2 rows
vs the spec's populated screens). The loader now stamps a sha256 fingerprint of the APPLIED
source into a `_seed_meta` table; when the source changes it resets the seed-managed tables
(TRUNCATE…RESTART IDENTITY CASCADE, child-first DELETE fallback on sqlite) and re-applies.
Same fingerprint → boot is a no-op. ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import render_seed_data  # noqa: E402

_TABLES = {
    "users": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "email", "type": "text"}, {"name": "name", "type": "text"},
        {"name": "password_hash", "type": "text"}, {"name": "tenant_id", "type": "text"}]},
    "messages": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "user_id", "type": "integer", "foreign_key": "users.id"},
        {"name": "subject", "type": "text"}, {"name": "body", "type": "text"}]},
}


def _boot(tmp_path, seed_json=None):
    """One app 'boot': fresh module namespace + loader run against the SAME sqlite file."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base, sessionmaker
    eng = create_engine(f"sqlite:///{tmp_path}/app.db")
    Base = declarative_base()
    db_mod = types.ModuleType("database")
    db_mod.Base = Base
    db_mod.SessionLocal = sessionmaker(bind=eng)
    sys.modules["database"] = db_mod

    src = render_seed_data(_TABLES)
    seed_dir = tmp_path / "backend"
    seed_dir.mkdir(exist_ok=True)
    loader = seed_dir / "seed_data.py"
    loader.write_text(src, encoding="utf-8")
    if seed_json is not None:
        (seed_dir / "seed_data.json").write_text(json.dumps(seed_json), encoding="utf-8")

    # models module rendered from the same contract
    from multi_agent.runtime.backend_skeleton import render_models
    models_mod = types.ModuleType("models")
    exec(compile(render_models(_TABLES), "models.py", "exec"), models_mod.__dict__)
    sys.modules["models"] = models_mod
    Base.metadata.create_all(eng)

    ns = {"__file__": str(loader)}
    exec(compile(src, str(loader), "exec"), ns)
    ns["seed_if_empty"]()

    s = db_mod.SessionLocal()
    users = [u.email for u in s.query(models_mod.User).all()]
    msgs = [m.subject for m in s.query(models_mod.Message).all()]
    s.close()
    for m in ("database", "models"):
        sys.modules.pop(m, None)
    return users, msgs


_AUTHORED = {
    "users": [{"email": "alice@example.com", "name": "Alice"},
              {"email": "bob@example.com", "name": "Bob"}],
    "messages": [{"user_id": 1, "subject": f"Authored subject {i}", "body": "real"}
                 for i in range(12)],
}


def test_first_boot_seeds_fallback_then_authored_json_reconciles(tmp_path):
    # boot 1: no JSON → fallback _SEED lands
    users1, msgs1 = _boot(tmp_path)
    assert users1 and "alice@example.com" not in users1          # fallback users
    # the lane authors seed_data.json AFTER first boot (the run-30 timeline)
    users2, msgs2 = _boot(tmp_path, seed_json=_AUTHORED)
    assert "alice@example.com" in users2 and "bob@example.com" in users2
    assert not (set(users1) & set(users2))                       # fallback users replaced
    assert len(msgs2) == 12 and all(s.startswith("Authored") for s in msgs2)


def test_same_source_is_a_noop(tmp_path):
    users1, msgs1 = _boot(tmp_path, seed_json=_AUTHORED)
    users2, msgs2 = _boot(tmp_path, seed_json=_AUTHORED)         # boot again, same JSON
    assert users2 == users1 and msgs2 == msgs1                   # no duplication, no reset


def test_updated_json_reapplies(tmp_path):
    _boot(tmp_path, seed_json=_AUTHORED)
    updated = {"users": [{"email": "carol@example.com", "name": "C"}],
               "messages": [{"user_id": 1, "subject": "V2 only", "body": "x"}]}
    users, msgs = _boot(tmp_path, seed_json=updated)
    assert users == ["carol@example.com"]
    assert msgs == ["V2 only"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
